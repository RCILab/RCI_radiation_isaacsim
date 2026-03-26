from __future__ import annotations

import math
import time
import tomllib
from pathlib import Path

from pxr import UsdGeom

from radiation_simulator.authoring.config_loader import apply_radiation_customdata, resolve_config_root
from radiation_simulator.authoring.usd_helpers import (
    get_custom,
    get_world_translation,
    scan_prims_by_custom_flag,
    set_custom,
    set_xform_translate,
)
from radiation_simulator.core.forward_model import RadiationSource, compute_sensor_reading
from radiation_simulator.core.models import RuntimeSettings, SceneSensor, SceneSource
from radiation_simulator.core.raycast import RayHit, get_scene_query_iface, raycast_iterative_hits, thickness_from_hits
from radiation_simulator.types import ObstacleContribution, SensorReading, SourceContribution


def _load_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding='utf-8'))


def _short_name(path_or_name: str) -> str:
    value = str(path_or_name or '')
    if '/' in value:
        value = value.rsplit('/', 1)[-1]
    for prefix in ('radiation_obstacle_', 'radiation_source_', 'radiation_sensor_'):
        if value.startswith(prefix):
            value = value[len(prefix):]
    return value


def _apply_display_color(prim, rgb):
    try:
        from pxr import Gf

        gprim = UsdGeom.Gprim(prim)
        primvar = gprim.CreateDisplayColorPrimvar()
        primvar.Set([Gf.Vec3f(float(rgb[0]), float(rgb[1]), float(rgb[2]))])
    except Exception:
        pass


# Owns the live radiation scene state and cached sensor readings.
class RadiationManager:
    def __init__(self):
        self._sub = None
        self._configured = False
        self._settings: RuntimeSettings | None = None
        self._stage = None
        self._scene_query = None
        self._cfg_root = ''
        self._m_per_unit = 1.0
        self._period = 0.1
        self._next_t = 0.0
        self._sequence = 0
        self._sources: list[SceneSource] = []
        self._sensors: list[SceneSensor] = []
        self._robots_override: list[dict] | None = None
        self._obstacles_mu: dict[str, float] = {}
        self._obstacle_thickness_mode: dict[str, str] = {}
        self._readings_by_path: dict[str, SensorReading] = {}
        self._readings_by_name: dict[str, SensorReading] = {}

    def startup(self):
        if self._sub is not None:
            return
        try:
            import omni.physx as physx

            self._sub = physx.get_physx_interface().subscribe_physics_step_events(self._on_physics_step)
        except Exception:
            self._sub = None

    def shutdown(self):
        self._sub = None
        self.clear()

    def clear(self):
        self._configured = False
        self._settings = None
        self._stage = None
        self._scene_query = None
        self._cfg_root = ''
        self._m_per_unit = 1.0
        self._period = 0.1
        self._next_t = 0.0
        self._sequence = 0
        self._sources = []
        self._sensors = []
        self._robots_override = None
        self._obstacles_mu = {}
        self._obstacle_thickness_mode = {}
        self._readings_by_path = {}
        self._readings_by_name = {}

    # Read the stage once and cache the scene needed for runtime updates.
    def configure(
        self,
        stage,
        *,
        cfg_root: str | Path | None,
        world: str,
        root: str = '/World',
        air_mu: float = 0.001,
        no_obstacles: bool = False,
        apply_source_self_attenuation: bool = False,
        robots_override: list[dict] | None = None,
    ) -> dict:
        self._stage = stage
        self._cfg_root = str(resolve_config_root(cfg_root))
        self._settings = RuntimeSettings(
            cfg_root=self._cfg_root,
            world=str(world),
            root=str(root),
            air_mu=float(air_mu),
            no_obstacles=bool(no_obstacles),
            apply_source_self_attenuation=bool(apply_source_self_attenuation),
        )

        applied = apply_radiation_customdata(stage, cfg_root=self._cfg_root, world=world)
        self._m_per_unit = float(UsdGeom.GetStageMetersPerUnit(stage))
        self._robots_override = list(robots_override) if robots_override is not None else None

        self._sources = self._scan_sources()
        self._obstacles_mu, self._obstacle_thickness_mode = self._scan_obstacles()
        self._sensors, sensor_base = self._build_sensors(robots_override=robots_override)

        rate_hz = float(sensor_base.get('rate_hz', 10.0))
        self._period = 1.0 / max(1e-6, rate_hz)
        self._next_t = time.perf_counter()

        self._scene_query = None
        if (not self._settings.no_obstacles) and self._obstacles_mu:
            try:
                self._scene_query = get_scene_query_iface()
            except Exception:
                self._scene_query = None

        self._configured = True
        self.step(force=True)

        return {
            'cfg_root': self._cfg_root,
            'world': world,
            'sources': len(self._sources),
            'obstacles': len(self._obstacles_mu),
            'sensors': len(self._sensors),
            'applied': applied,
        }

    # Re-scan stage custom data without reapplying TOML so live edits can take effect.
    def refresh_from_stage(self, *, refresh_sensors: bool = False, force_step: bool = True) -> dict:
        if (not self._configured) or self._stage is None or self._settings is None:
            raise RuntimeError('Radiation runtime is not configured.')

        self._sources = self._scan_sources()
        self._obstacles_mu, self._obstacle_thickness_mode = self._scan_obstacles()

        if refresh_sensors:
            self._sensors, sensor_base = self._build_sensors(robots_override=self._robots_override)
            rate_hz = float(sensor_base.get('rate_hz', 10.0))
            self._period = 1.0 / max(1e-6, rate_hz)

        self._scene_query = None
        if (not self._settings.no_obstacles) and self._obstacles_mu:
            try:
                self._scene_query = get_scene_query_iface()
            except Exception:
                self._scene_query = None

        if force_step:
            self.step(force=True)

        return {
            'cfg_root': self._cfg_root,
            'world': self._settings.world,
            'sources': len(self._sources),
            'obstacles': len(self._obstacles_mu),
            'sensors': len(self._sensors),
        }

    def _scan_sources(self) -> list[SceneSource]:
        assert self._stage is not None
        assert self._settings is not None

        source_prims = scan_prims_by_custom_flag(self._stage, self._settings.root, 'radiation:is_source', True)
        sources: list[SceneSource] = []
        for prim in source_prims:
            enabled = bool(get_custom(prim, 'radiation:enabled', True))
            intensity = float(get_custom(prim, 'radiation:intensity', 0.0) or 0.0)
            if (not enabled) or intensity <= 0.0:
                continue

            prim_path = prim.GetPath().pathString
            position = get_world_translation(prim)
            host_obstacle = get_custom(prim, 'radiation:host_obstacle', None)
            sources.append(
                SceneSource(
                    prim_path=prim_path,
                    name=_short_name(prim_path),
                    position_units=(float(position[0]), float(position[1]), float(position[2])),
                    intensity=float(intensity),
                    host_obstacle=str(host_obstacle) if host_obstacle else None,
                )
            )
        return sources

    def _refresh_dynamic_scene_from_stage(self):
        if (not self._configured) or self._stage is None or self._settings is None:
            return

        # Sources and obstacle attenuation values are cheap to rescan and can change live.
        self._sources = self._scan_sources()
        self._obstacles_mu, self._obstacle_thickness_mode = self._scan_obstacles()

        if (not self._settings.no_obstacles) and self._obstacles_mu and self._scene_query is None:
            try:
                self._scene_query = get_scene_query_iface()
            except Exception:
                self._scene_query = None

    def _scan_obstacles(self) -> tuple[dict[str, float], dict[str, str]]:
        assert self._stage is not None
        assert self._settings is not None

        obstacle_prims = scan_prims_by_custom_flag(self._stage, self._settings.root, 'radiation:is_obstacle', True)
        obstacles: dict[str, float] = {}
        thickness_mode: dict[str, str] = {}
        for prim in obstacle_prims:
            mu = get_custom(prim, 'radiation:mu', None)
            if mu is None:
                continue
            path = prim.GetPath().pathString
            obstacles[path] = float(mu)
            mode = get_custom(prim, 'radiation:thickness_mode', None)
            if mode not in (None, ''):
                thickness_mode[path] = str(mode)
        return obstacles, thickness_mode

    def _build_sensors(self, *, robots_override: list[dict] | None) -> tuple[list[SceneSensor], dict]:
        assert self._stage is not None
        assert self._settings is not None

        cfg_root_path = Path(self._cfg_root)
        base_cfg = _load_toml(cfg_root_path / 'base' / 'sensor.toml')
        world_cfg = _load_toml(cfg_root_path / 'worlds' / self._settings.world / 'sensors.toml')

        sensor_base = base_cfg.get('sensor', {}) or {}
        default_offset = sensor_base.get('default_offset', [0.0, 0.0, 0.25])
        probe_radius = float(sensor_base.get('probe_radius', 0.03))
        probe_height = float(sensor_base.get('probe_height', 0.05))
        probe_color = sensor_base.get('probe_color', [1.0, 1.0, 0.0])

        sensors_cfg = world_cfg.get('sensors', {}) or {}
        is_sensor_key = str(sensors_cfg.get('is_sensor_key', 'radiation:is_sensor'))
        sensor_name_key = str(sensors_cfg.get('sensor_name_key', 'radiation:sensor_name'))
        default_sensor_prim_name = str(sensors_cfg.get('sensor_prim_name', 'RadiationSensor'))

        robots = list(robots_override if robots_override is not None else (sensors_cfg.get('robots', []) or []))
        items = list(sensors_cfg.get('items', []) or [])

        def ensure_sensor_prim(attach_prim_path: str, sensor_prim_name: str) -> str:
            attach_prim = self._stage.GetPrimAtPath(attach_prim_path)
            if not attach_prim or not attach_prim.IsValid():
                raise RuntimeError(f'attach_prim not found: {attach_prim_path}')

            sensor_path = f'{attach_prim_path}/{sensor_prim_name}'
            prim = self._stage.GetPrimAtPath(sensor_path)
            if prim and prim.IsValid():
                return sensor_path

            cylinder = UsdGeom.Cylinder.Define(self._stage, sensor_path)
            cylinder.CreateRadiusAttr(float(probe_radius))
            cylinder.CreateHeightAttr(float(probe_height))
            _apply_display_color(cylinder.GetPrim(), probe_color)
            return sensor_path

        sensors: list[SceneSensor] = []

        for robot in robots:
            robot_id = str(robot.get('id', 'robot'))
            robot_root = str(robot.get('root', '')).rstrip('/')
            attach_link = str(robot.get('attach_link', 'base_link')).strip('/')
            if not robot_root:
                continue

            attach_prim = f'{robot_root}/{attach_link}'
            sensor_prim_name = str(robot.get('sensor_prim_name', default_sensor_prim_name))
            offset = robot.get('offset', default_offset)

            sensor_path = ensure_sensor_prim(attach_prim, sensor_prim_name)
            sensor_prim = self._stage.GetPrimAtPath(sensor_path)
            display_name = f'{robot_id}/{sensor_prim_name}'

            set_custom(sensor_prim, **{is_sensor_key: True, sensor_name_key: display_name})
            set_xform_translate(self._stage, sensor_prim, (float(offset[0]), float(offset[1]), float(offset[2])))
            sensors.append(SceneSensor(name=display_name, prim_path=sensor_path, prim=sensor_prim))

        for item in items:
            name = str(item.get('name', 'sensor'))
            attach_prim = str(item.get('attach_prim', ''))
            if not attach_prim:
                continue

            sensor_prim_name = str(item.get('sensor_prim_name', default_sensor_prim_name))
            offset = item.get('offset', default_offset)

            sensor_path = ensure_sensor_prim(attach_prim, sensor_prim_name)
            sensor_prim = self._stage.GetPrimAtPath(sensor_path)
            set_custom(sensor_prim, **{is_sensor_key: True, sensor_name_key: name})
            set_xform_translate(self._stage, sensor_prim, (float(offset[0]), float(offset[1]), float(offset[2])))
            sensors.append(SceneSensor(name=name, prim_path=sensor_path, prim=sensor_prim))

        if not sensors:
            authored_sensor_prims = scan_prims_by_custom_flag(self._stage, self._settings.root, is_sensor_key, True)
            for prim in authored_sensor_prims:
                prim_path = prim.GetPath().pathString
                sensor_name = str(get_custom(prim, sensor_name_key, _short_name(prim_path)))
                sensors.append(SceneSensor(name=sensor_name, prim_path=prim_path, prim=prim))

        if not sensors:
            raise RuntimeError('No sensors configured. Pass robots_override, define sensors.items, or author sensor prims on the stage.')

        return sensors, sensor_base

    def _scale_hits_to_meters(self, hits: list[RayHit]) -> list[RayHit]:
        if abs(float(self._m_per_unit) - 1.0) < 1e-12:
            return hits

        scaled_hits: list[RayHit] = []
        for hit in hits:
            scaled_hits.append(
                RayHit(
                    distance=float(hit.distance) * float(self._m_per_unit),
                    collision=hit.collision,
                    rigid_body=hit.rigid_body,
                    position=hit.position,
                    normal=hit.normal,
                    face_index=hit.face_index,
                )
            )
        return scaled_hits

    def _resolve_mu_path(self, collision_path: str) -> str | None:
        from pxr import Sdf

        if not collision_path:
            return None
        path = Sdf.Path(collision_path)
        while path and path != Sdf.Path.absoluteRootPath:
            path_str = path.pathString
            if path_str in self._obstacles_mu:
                return path_str
            path = path.GetParentPath()
        return None

    def _guess_host_obstacle_from_source_path(self, source_prim_path: str) -> str | None:
        token = source_prim_path.split('/')[-1]
        if not token.startswith('radiation_source_'):
            return None
        parent = '/'.join(source_prim_path.split('/')[:-1])
        return parent + '/' + token.replace('radiation_source_', 'radiation_obstacle_', 1)

    # for no mesh walls in demo
    def _bbox_segment_thickness_m(
        self,
        bbox_cache,
        obstacle_path: str,
        origin_units: tuple[float, float, float],
        target_units: tuple[float, float, float],
    ) -> float:
        assert self._stage is not None

        prim = self._stage.GetPrimAtPath(obstacle_path)
        if not prim or not prim.IsValid():
            return 0.0

        try:
            aligned = bbox_cache.ComputeWorldBound(prim).ComputeAlignedBox()
        except Exception:
            return 0.0

        p0 = [float(origin_units[0]), float(origin_units[1]), float(origin_units[2])]
        p1 = [float(target_units[0]), float(target_units[1]), float(target_units[2])]
        d = [p1[i] - p0[i] for i in range(3)]
        t_min = 0.0
        t_max = 1.0
        eps = 1e-9

        mins = aligned.GetMin()
        maxs = aligned.GetMax()
        bounds_min = [float(mins[0]), float(mins[1]), float(mins[2])]
        bounds_max = [float(maxs[0]), float(maxs[1]), float(maxs[2])]

        for axis in range(3):
            if abs(d[axis]) <= eps:
                if p0[axis] < bounds_min[axis] or p0[axis] > bounds_max[axis]:
                    return 0.0
                continue

            inv = 1.0 / d[axis]
            t1 = (bounds_min[axis] - p0[axis]) * inv
            t2 = (bounds_max[axis] - p0[axis]) * inv
            if t1 > t2:
                t1, t2 = t2, t1
            t_min = max(t_min, t1)
            t_max = min(t_max, t2)
            if t_max <= t_min:
                return 0.0

        seg_len_units = math.sqrt(sum((p1[i] - p0[i]) ** 2 for i in range(3)))
        if seg_len_units <= eps:
            return 0.0
        return max(0.0, (t_max - t_min) * seg_len_units * float(self._m_per_unit))

    # Compute one batch of per-sensor readings from the cached scene state.
    def _compute_readings(self) -> list[SensorReading]:
        assert self._settings is not None

        now_unix = time.time()
        readings: list[SensorReading] = []

        runtime_sources = [
            RadiationSource(
                prim_path=source.prim_path,
                pos=source.position_units,
                intensity=float(source.intensity),
                mu_air=float(self._settings.air_mu),
                enabled=True,
                name=str(source.name),
                host_obstacle=source.host_obstacle,
            )
            for source in self._sources
        ]

        bbox_mode_paths = {path for (path, mode) in self._obstacle_thickness_mode.items() if mode == 'bbox'}
        bbox_cache = None
        if bbox_mode_paths:
            bbox_cache = UsdGeom.BBoxCache(
                0,
                [UsdGeom.Tokens.default_, UsdGeom.Tokens.render, UsdGeom.Tokens.proxy, UsdGeom.Tokens.guide],
                useExtentsHint=True,
            )

        def bbox_solver(obstacle_path: str, origin_units, target_units) -> float:
            if bbox_cache is None or obstacle_path not in bbox_mode_paths:
                return 0.0
            return self._bbox_segment_thickness_m(bbox_cache, obstacle_path, origin_units, target_units)

        for sensor in self._sensors:
            position_units = get_world_translation(sensor.prim)
            px_u, py_u, pz_u = float(position_units[0]), float(position_units[1]), float(position_units[2])
            position_m = (px_u * self._m_per_unit, py_u * self._m_per_unit, pz_u * self._m_per_unit)

            solver = None
            if (not self._settings.no_obstacles) and self._scene_query is not None and self._obstacles_mu:
                solver = (
                    self._scene_query,
                    list(self._obstacles_mu.items()),
                    raycast_iterative_hits,
                    thickness_from_hits,
                    [sensor.prim_path],
                    float(self._m_per_unit),
                    bbox_solver,
                )

            result = compute_sensor_reading(
                (px_u, py_u, pz_u),
                runtime_sources,
                mu_air=float(self._settings.air_mu),
                apply_source_self_attenuation=bool(self._settings.apply_source_self_attenuation),
                obstacle_solver=solver,
            )

            per_source: list[SourceContribution] = []
            for item in result['per_source']:
                obstacle_terms = tuple(
                    ObstacleContribution(
                        name=_short_name(str(obstacle['path'])),
                        thickness_m=float(obstacle['thickness_m']),
                        mu=float(obstacle['mu']),
                        att=float(math.exp(-float(obstacle['mu']) * float(obstacle['thickness_m']))),
                    )
                    for obstacle in item['obstacles']
                )
                per_source.append(
                    SourceContribution(
                        idx=int(item['idx']),
                        name=str(item['name']),
                        dist_m=float(item['dist_m']),
                        intensity=float(item['intensity']),
                        base=float(item['base']),
                        att_total=float(item['att_total']),
                        final=float(item['final']),
                        obstacles=obstacle_terms,
                    )
                )

            readings.append(
                SensorReading(
                    t=now_unix,
                    sensor=sensor.name,
                    prim_path=sensor.prim_path,
                    pos_m=position_m,
                    total=float(result['total']),
                    per_source=tuple(per_source),
                )
            )

        return readings

    def _store_readings(self, readings: list[SensorReading]):
        self._readings_by_path = {reading.prim_path: reading for reading in readings}
        self._readings_by_name = {reading.sensor: reading for reading in readings}
        self._sequence += 1

    # Advance the runtime at rate_hz unless force=True is requested.
    def step(self, *, force: bool = False) -> bool:
        if not self._configured:
            return False

        now = time.perf_counter()
        if (not force) and now < self._next_t:
            return False

        while self._next_t <= now:
            self._next_t += self._period

        self._refresh_dynamic_scene_from_stage()
        self._store_readings(self._compute_readings())
        return True

    def _on_physics_step(self, dt: float):
        try:
            self.step(force=False)
        except Exception:
            pass

    def get_sensor_reading(self, sensor_key: str) -> SensorReading | None:
        return self._readings_by_name.get(sensor_key) or self._readings_by_path.get(sensor_key)

    def get_all_sensor_readings(self) -> list[SensorReading]:
        readings = list(self._readings_by_name.values())
        readings.sort(key=lambda item: item.sensor)
        return readings

    def get_update_sequence(self) -> int:
        return int(self._sequence)

    @property
    def configured(self) -> bool:
        return bool(self._configured)
