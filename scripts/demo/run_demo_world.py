from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from isaacsim import SimulationApp


def _bootstrap_sys_path() -> None:
    scripts_dir = Path(__file__).resolve().parents[1]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


SOURCE_X = -4.0
LINE_Y = 0.0
LINE_Z = 1.0
SENSOR_MIN_X = -2.0
SENSOR_MAX_X = 6.5
SHIELD_X_POSITIONS = (-2.5, 0.5, 3.5)
SHIELD_OFF_Y = 5.5


@dataclass
class ShieldSpec:
    path: str
    material: str
    on_pos: tuple[float, float, float]
    off_pos: tuple[float, float, float]
    color: tuple[float, float, float]
    thickness_m: float
    enabled: bool = False
    current_pos: tuple[float, float, float] = field(init=False)
    target_pos: tuple[float, float, float] = field(init=False)

    def __post_init__(self) -> None:
        self.current_pos = tuple(float(v) for v in self.off_pos)
        self.target_pos = tuple(float(v) for v in self.off_pos)


def _smooth_scalar(current: float, target: float, response_hz: float, dt: float) -> float:
    alpha = 1.0 - math.exp(-max(1e-6, float(response_hz)) * max(0.0, float(dt)))
    return float(current) + (float(target) - float(current)) * alpha


def _smooth_position(
    current: tuple[float, float, float],
    target: tuple[float, float, float],
    response_hz: float,
    dt: float,
) -> tuple[float, float, float]:
    return (
        _smooth_scalar(float(current[0]), float(target[0]), response_hz, dt),
        _smooth_scalar(float(current[1]), float(target[1]), response_hz, dt),
        _smooth_scalar(float(current[2]), float(target[2]), response_hz, dt),
    )


class DemoController:
    def __init__(self, stage, sensor_anchor_path: str, shields: list[ShieldSpec], sensor_range: tuple[float, float]):
        self._stage = stage
        self._sensor_anchor_path = sensor_anchor_path
        self._shields = shields
        self._sensor_min_x, self._sensor_max_x = sensor_range
        self._sensor_x = float(self._sensor_max_x)
        self._sensor_target_x = float(self._sensor_max_x)
        self._shield_response_hz = 4.5
        self._sensor_response_hz = 5.0

    @property
    def shields(self) -> list[ShieldSpec]:
        return self._shields

    @property
    def sensor_x(self) -> float:
        return float(self._sensor_x)

    @property
    def sensor_range(self) -> tuple[float, float]:
        return (float(self._sensor_min_x), float(self._sensor_max_x))

    def initialize_positions(self) -> None:
        from radiation_simulator.authoring.usd_helpers import set_xform_translate

        for shield in self._shields:
            shield.current_pos = tuple(float(v) for v in shield.off_pos)
            shield.target_pos = tuple(float(v) for v in shield.off_pos)
            prim = self._stage.GetPrimAtPath(shield.path)
            set_xform_translate(self._stage, prim, shield.current_pos)

        self._sensor_x = float(self._sensor_max_x)
        self._sensor_target_x = float(self._sensor_max_x)
        sensor_anchor = self._stage.GetPrimAtPath(self._sensor_anchor_path)
        set_xform_translate(self._stage, sensor_anchor, (self._sensor_x, LINE_Y, LINE_Z))

    def toggle_shield(self, index: int) -> None:
        shield = self._shields[index]
        shield.enabled = not shield.enabled
        shield.target_pos = tuple(float(v) for v in (shield.on_pos if shield.enabled else shield.off_pos))

    def set_sensor_target_x(self, value: float) -> None:
        clamped = max(self._sensor_min_x, min(self._sensor_max_x, float(value)))
        self._sensor_target_x = float(clamped)

    def update(self, dt: float) -> None:
        from radiation_simulator.authoring.usd_helpers import set_xform_translate

        for shield in self._shields:
            next_pos = _smooth_position(shield.current_pos, shield.target_pos, self._shield_response_hz, dt)
            if any(abs(a - b) > 1e-4 for a, b in zip(next_pos, shield.current_pos)):
                shield.current_pos = next_pos
                prim = self._stage.GetPrimAtPath(shield.path)
                set_xform_translate(self._stage, prim, shield.current_pos)
            else:
                shield.current_pos = tuple(float(v) for v in shield.target_pos)

        sensor_next_x = _smooth_scalar(self._sensor_x, self._sensor_target_x, self._sensor_response_hz, dt)
        if abs(sensor_next_x - self._sensor_x) > 1e-4:
            self._sensor_x = float(sensor_next_x)
            sensor_anchor = self._stage.GetPrimAtPath(self._sensor_anchor_path)
            set_xform_translate(self._stage, sensor_anchor, (self._sensor_x, LINE_Y, LINE_Z))
        else:
            self._sensor_x = float(self._sensor_target_x)


class DemoWindow:
    def __init__(self, controller: DemoController):
        import omni.ui as ui

        self._ui = ui
        self._controller = controller
        self._window = None
        self._status_labels = []
        self._sensor_label = None
        self._intensity_label = None
        self._slider = None
        self._build()
        self.refresh_status(total=None)

    def _build(self) -> None:
        ui = self._ui
        self._status_labels = []
        self._window = ui.Window(
            'Radiation Demo Controls',
            width=430,
            height=330,
            visible=True,
            dock_preference=ui.DockPreference.RIGHT_TOP,
        )
        with self._window.frame:
            with ui.VStack(spacing=8, height=0):
                ui.Label('Shield Toggles', height=20)
                for idx, shield in enumerate(self._controller.shields):
                    with ui.HStack(height=26, spacing=6):
                        ui.Button(f'Toggle Shield {idx + 1}', clicked_fn=lambda i=idx: self._on_toggle(i))
                        status = ui.Label('', width=170)
                        self._status_labels.append(status)

                ui.Spacer(height=6)
                ui.Label('Sensor Distance', height=20)
                self._slider = ui.FloatSlider(
                    min=self._controller.sensor_range[0],
                    max=self._controller.sensor_range[1],
                    step=0.01,
                )
                self._slider.model.set_value(self._controller.sensor_x)
                self._slider.model.add_value_changed_fn(lambda model: self._on_sensor_slider(model.as_float))
                self._sensor_label = ui.Label('', height=20)

                ui.Spacer(height=6)
                ui.Label('Radiation Reading', height=20)
                self._intensity_label = ui.Label('waiting for radiation runtime...', height=20)
                ui.Label('This value is read directly from the radiation extension.', height=20)

    def show(self) -> None:
        if self._window is None:
            self._build()
        if self._window is not None:
            self._window.visible = True

    def hide(self) -> None:
        if self._window is not None:
            self._window.visible = False

    def is_visible(self) -> bool:
        return bool(self._window is not None and getattr(self._window, 'visible', False))

    def _on_toggle(self, index: int) -> None:
        self._controller.toggle_shield(index)
        self.refresh_status(total=None)

    def _on_sensor_slider(self, value: float) -> None:
        self._controller.set_sensor_target_x(float(value))
        self.refresh_status(total=None)

    def refresh_status(self, total: float | None) -> None:
        for label, shield in zip(self._status_labels, self._controller.shields):
            state = 'ON' if shield.enabled else 'OFF'
            label.text = f'{shield.material}: {state}'

        if self._sensor_label is not None:
            self._sensor_label.text = f'sensor x = {self._controller.sensor_x:.2f} m'
        if self._intensity_label is not None:
            if total is None:
                self._intensity_label.text = 'total intensity = waiting...'
            else:
                self._intensity_label.text = f'total intensity = {float(total):.6f}'


def _ensure_xform(stage, path: str):
    from pxr import UsdGeom

    prim = stage.GetPrimAtPath(path)
    if prim and prim.IsValid():
        return prim
    return UsdGeom.Xform.Define(stage, path).GetPrim()


def _set_scale(prim, xyz: tuple[float, float, float]) -> None:
    from pxr import Gf, UsdGeom

    xf = UsdGeom.Xformable(prim)
    ops = xf.GetOrderedXformOps()
    scale_op = None
    for op in ops:
        if op.GetOpType() == UsdGeom.XformOp.TypeScale:
            scale_op = op
            break
    if scale_op is None:
        scale_op = xf.AddScaleOp()
    scale_op.Set(Gf.Vec3f(float(xyz[0]), float(xyz[1]), float(xyz[2])))


def _set_display_color(prim, rgb: tuple[float, float, float]) -> None:
    from pxr import Gf, UsdGeom

    gprim = UsdGeom.Gprim(prim)
    primvar = gprim.CreateDisplayColorPrimvar()
    primvar.Set([Gf.Vec3f(float(rgb[0]), float(rgb[1]), float(rgb[2]))])


def _apply_moving_shield_physics(prim) -> None:
    from pxr import UsdPhysics

    if not prim.HasAPI(UsdPhysics.CollisionAPI):
        UsdPhysics.CollisionAPI.Apply(prim)

    rigid_api = UsdPhysics.RigidBodyAPI.Apply(prim)

    try:
        attr = rigid_api.GetRigidBodyEnabledAttr()
        if not attr:
            attr = rigid_api.CreateRigidBodyEnabledAttr()
        attr.Set(True)
    except Exception:
        pass

    try:
        attr = rigid_api.GetKinematicEnabledAttr()
        if not attr:
            attr = rigid_api.CreateKinematicEnabledAttr()
        attr.Set(True)
    except Exception:
        pass

    try:
        from pxr import PhysxSchema

        col_api = PhysxSchema.PhysxCollisionAPI.Apply(prim)
        col_attr = col_api.GetCollisionEnabledAttr()
        if not col_attr:
            col_attr = col_api.CreateCollisionEnabledAttr()
        col_attr.Set(True)

        rb_api = PhysxSchema.PhysxRigidBodyAPI.Apply(prim)
        grav_attr = rb_api.GetDisableGravityAttr()
        if not grav_attr:
            grav_attr = rb_api.CreateDisableGravityAttr()
        grav_attr.Set(True)
    except Exception:
        pass


def _style_source_marker(stage) -> None:
    from pxr import UsdGeom

    source_geom = stage.GetPrimAtPath('/World/RadiationSources/radiation_source_demoSource/Geom')
    if source_geom and source_geom.IsValid():
        _set_display_color(source_geom, (1.0, 0.15, 0.15))
        try:
            sphere = UsdGeom.Sphere(source_geom)
            radius_attr = sphere.GetRadiusAttr()
            if radius_attr:
                radius_attr.Set(0.28)
        except Exception:
            pass


def _create_demo_scene(stage):
    from pxr import UsdGeom, UsdLux
    from radiation_simulator.authoring.usd_helpers import set_xform_translate

    _ensure_xform(stage, '/World')
    _ensure_xform(stage, '/World/DemoRig')

    sensor_anchor = _ensure_xform(stage, '/World/DemoSensorAnchor')
    set_xform_translate(stage, sensor_anchor, (SENSOR_MAX_X, LINE_Y, LINE_Z))

    light = UsdLux.DistantLight.Define(stage, '/World/DemoSun')
    light.CreateIntensityAttr(2500.0)

    guide = UsdGeom.Cube.Define(stage, '/World/DemoRayGuide')
    guide.CreateSizeAttr(1.0)
    guide_prim = guide.GetPrim()
    line_center_x = 0.5 * (SOURCE_X + SENSOR_MAX_X)
    line_length = SENSOR_MAX_X - SOURCE_X
    set_xform_translate(stage, guide_prim, (line_center_x, LINE_Y, LINE_Z))
    _set_scale(guide_prim, (line_length, 0.03, 0.03))
    _set_display_color(guide_prim, (1.0, 0.85, 0.2))

    sensor_cyl = UsdGeom.Cylinder.Define(stage, '/World/DemoSensorAnchor/RadiationSensor')
    sensor_cyl.CreateRadiusAttr(0.16)
    sensor_cyl.CreateHeightAttr(0.70)
    _set_display_color(sensor_cyl.GetPrim(), (0.15, 0.95, 0.25))

    shields = [
        ShieldSpec(
            path='/World/radiation_obstacle_demoShield1_concrete',
            material='concrete',
            on_pos=(SHIELD_X_POSITIONS[0], LINE_Y, LINE_Z),
            off_pos=(SHIELD_X_POSITIONS[0], SHIELD_OFF_Y, LINE_Z),
            color=(0.72, 0.61, 0.48),
            thickness_m=0.2,
        ),
        ShieldSpec(
            path='/World/radiation_obstacle_demoShield2_aluminium',
            material='aluminium',
            on_pos=(SHIELD_X_POSITIONS[1], LINE_Y, LINE_Z),
            off_pos=(SHIELD_X_POSITIONS[1], SHIELD_OFF_Y, LINE_Z),
            color=(0.86, 0.88, 0.93),
            thickness_m=0.5,
        ),
        ShieldSpec(
            path='/World/radiation_obstacle_demoShield3_stainlessSteel',
            material='stainlessSteel',
            on_pos=(SHIELD_X_POSITIONS[2], LINE_Y, LINE_Z),
            off_pos=(SHIELD_X_POSITIONS[2], SHIELD_OFF_Y, LINE_Z),
            color=(0.46, 0.57, 0.70),
            thickness_m=1.0,
        ),
    ]

    for shield in shields:
        cube = UsdGeom.Cube.Define(stage, shield.path)
        cube.CreateSizeAttr(1.0)
        prim = cube.GetPrim()
        set_xform_translate(stage, prim, shield.off_pos)
        _set_scale(prim, (float(shield.thickness_m), 2.8, 2.4))
        _set_display_color(prim, shield.color)
        _apply_moving_shield_physics(prim)

    return '/World/DemoSensorAnchor', shields


def _set_camera_view() -> None:
    try:
        from isaacsim.core.utils.viewports import set_camera_view
    except Exception:
        try:
            from omni.isaac.core.utils.viewports import set_camera_view
        except Exception:
            return

    set_camera_view(eye=[0.0, -13.0, 4.7], target=[0.0, 0.0, 1.0], camera_prim_path='/OmniverseKit_Persp')


def _register_timeline_window_callbacks(window_state: dict[str, bool]):
    import omni.timeline

    def _show_window(_event) -> None:
        window_state['visible'] = True

    stream = omni.timeline.get_timeline_interface().get_timeline_event_stream()
    stop_handle = stream.create_subscription_to_pop_by_type(
        int(omni.timeline.TimelineEventType.STOP),
        _show_window,
    )
    play_handle = stream.create_subscription_to_pop_by_type(
        int(omni.timeline.TimelineEventType.PLAY),
        _show_window,
    )
    return stop_handle, play_handle


def main() -> None:
    _bootstrap_sys_path()

    from debug.radiation_debug import print_attachment_summary, scan_attachment_summary
    from runtime.workspace_config import resolve_cfg_root, resolve_world_usd

    parser = argparse.ArgumentParser()
    parser.add_argument('--headless', action='store_true', default=False)
    parser.add_argument('--cfg-root', default='extensions/radiation.simulator/config')
    parser.add_argument('--cfg-world', default='demo_world')
    parser.add_argument('--warmup-frames', type=int, default=90)
    parser.add_argument('--sensor-print-every', type=int, default=0, help='UDP 송신 로그를 주기적으로 출력')
    parser.add_argument('--steps', type=int, default=-1, help='<=0이면 창을 닫을 때까지 실행')
    parser.add_argument('--enable-shield', type=int, action='append', default=[], help='시작 시 켤 shield 번호(1-based), 여러 번 지정 가능')
    parser.add_argument('--sensor-x', type=float, default=None, help='시작 시 sensor x 위치를 강제로 지정')
    args = parser.parse_args()

    app = SimulationApp({'headless': args.headless})
    try:
        from runtime.radiation_runtime import ensure_radiation_extension_enabled

        ensure_radiation_extension_enabled(app)

        from radiation_simulator.api import get_reading, get_sequence
        from radiation_simulator.authoring.config_loader import apply_radiation_customdata
        from radiation_simulator.authoring.usd_helpers import ensure_physics_scene, get_stage, open_stage, warmup_physics
        from runtime import attach_radiation_runtime

        cfg_root = resolve_cfg_root(args.cfg_root)
        world_name = str(args.cfg_world)
        usd_path = resolve_world_usd(cfg_root, world_name)

        print(f'[demo] open world={world_name} usd={usd_path}')
        open_stage(str(usd_path), app, warmup_frames=60)

        stage = get_stage()
        if stage is None:
            raise RuntimeError('stage is None')

        from pxr import UsdGeom

        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        print(f'[demo] stage metersPerUnit={float(UsdGeom.GetStageMetersPerUnit(stage))}')

        sensor_anchor_path, shields = _create_demo_scene(stage)
        controller = DemoController(stage, sensor_anchor_path, shields, sensor_range=(SENSOR_MIN_X, SENSOR_MAX_X))
        controller.initialize_positions()

        for shield_index in args.enable_shield:
            idx = int(shield_index) - 1
            if 0 <= idx < len(shields):
                controller.toggle_shield(idx)

        if args.sensor_x is not None:
            controller.set_sensor_target_x(float(args.sensor_x))

        if args.enable_shield or args.sensor_x is not None:
            for _ in range(180):
                controller.update(1.0 / 60.0)
                app.update()

        applied = apply_radiation_customdata(stage, cfg_root=str(cfg_root), world=world_name)
        _style_source_marker(stage)
        print(f"[demo] applied obstacles={applied['obstacles_applied']} sources={applied['sources_applied']}")
        print_attachment_summary(scan_attachment_summary(stage, root='/World'))

        ensure_physics_scene(stage, scene_path='/World/physicsScene')
        warmup_physics(app, stage, steps=int(args.warmup_frames), play=True)
        _set_camera_view()

        sensor_tick = attach_radiation_runtime(
            app,
            stage,
            cfg_root=str(cfg_root),
            world=world_name,
            root='/World',
            air_mu=0.001,
            no_obstacles=False,
            apply_source_self_attenuation=False,
            print_every=int(args.sensor_print_every),
            robots_override=None,
        )
        info = getattr(sensor_tick, 'radiation_info', None)
        if isinstance(info, dict):
            print(f"[demo] runtime ready sources={info['sources']} obstacles={info['obstacles']} sensors={info['sensors']}")

        window = None if args.headless else DemoWindow(controller)
        window_state = {'visible': not args.headless}
        timeline_handles = () if args.headless else _register_timeline_window_callbacks(window_state)
        last_sequence = -1
        step_count = 0
        dt = 1.0 / 60.0

        print('[demo] controls: toggle three shields, move sensor slider, close the window to exit.')
        while True:
            try:
                if hasattr(app, 'is_running') and not app.is_running():
                    break
            except Exception:
                pass

            controller.update(dt)

            if not args.headless:
                if window_state['visible']:
                    if window is None:
                        window = DemoWindow(controller)
                    elif not window.is_visible():
                        window.show()

            app.update()
            sensor_tick()
            sequence = get_sequence()
            if sequence != last_sequence:
                last_sequence = sequence
                reading = get_reading('demo_sensor')
                if reading is not None and window is not None:
                    window.refresh_status(total=float(reading.total))

            step_count += 1
            if args.steps > 0 and step_count >= int(args.steps):
                break

            if args.headless:
                time.sleep(dt)

        _ = timeline_handles
    finally:
        app.close()


if __name__ == '__main__':
    main()
