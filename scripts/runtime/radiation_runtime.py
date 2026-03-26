from __future__ import annotations

import json
import socket
from pathlib import Path

from .workspace_config import resolve_cfg_root, workspace_root
from typing import Callable


# Radiation-specific script helpers live here so scenario scripts stay small.
def _load_toml(path: Path) -> dict:
    import tomllib

    return tomllib.loads(path.read_text(encoding="utf-8"))


# Enable the extension once before importing its Python modules.
def ensure_radiation_extension_enabled(app) -> None:
    import omni.kit.app

    ext_root = workspace_root() / "extensions"
    mgr = omni.kit.app.get_app().get_extension_manager()
    try:
        mgr.add_path(str(ext_root))
    except Exception:
        pass

    try:
        from isaacsim.core.utils.extensions import enable_extension
    except Exception:
        from omni.isaac.core.utils.extensions import enable_extension

    enable_extension("radiation.simulator")

    for _ in range(5):
        app.update()


# Open a world and apply radiation authoring config before simulation starts.
def prepare_radiation_world(
    app,
    *,
    usd: str,
    cfg_root: str | Path,
    world: str,
    physics_scene_path: str = "/World/physicsScene",
    apply_colliders: bool = False,
    collider_approx: str = "mesh",
    warmup_frames_open: int = 60,
    warmup_frames_physx: int = 90,
    no_obstacles: bool = False,
):
    ensure_radiation_extension_enabled(app)

    from pxr import UsdGeom

    from radiation_simulator.authoring.config_loader import apply_radiation_customdata
    from radiation_simulator.authoring.usd_helpers import (
        ensure_obstacle_mesh_colliders,
        ensure_physics_scene,
        get_custom,
        get_stage,
        open_stage,
        scan_prims_by_custom_flag,
        warmup_physics,
    )

    cfg_root_p = resolve_cfg_root(cfg_root)
    usd_path = str(Path(usd).expanduser().resolve())
    print(f"[open] {usd_path}")
    open_stage(usd_path, app, warmup_frames=warmup_frames_open)

    stage = get_stage()
    if stage is None:
        raise RuntimeError("stage is None")

    meters_per_unit = float(UsdGeom.GetStageMetersPerUnit(stage))
    print(f"[stage] metersPerUnit={meters_per_unit}")

    applied = apply_radiation_customdata(stage, cfg_root=str(cfg_root_p), world=world)
    print(f"[apply] obstacles={applied['obstacles_applied']} sources={applied['sources_applied']}")

    obstacle_prims = scan_prims_by_custom_flag(stage, "/World", "radiation:is_obstacle", True)
    obstacles_mu: dict[str, float] = {}
    for prim in obstacle_prims:
        mu = get_custom(prim, "radiation:mu", None)
        if mu is None:
            continue
        obstacles_mu[prim.GetPath().pathString] = float(mu)

    if (not no_obstacles) and obstacles_mu:
        ensure_physics_scene(stage, scene_path=physics_scene_path)

        if apply_colliders:
            mesh_cnt, applied_cnt = ensure_obstacle_mesh_colliders(
                stage,
                obstacle_root_paths=list(obstacles_mu.keys()),
                approximation=collider_approx,
                verbose=True,
            )
            print(f"[colliders] meshes={mesh_cnt} applied={applied_cnt} approx={collider_approx}")

        warmup_physics(app, stage, steps=int(warmup_frames_physx), play=True)
        print(f"[physics] warmup_frames={warmup_frames_physx}")

    return stage, meters_per_unit


# Convert spawned robot roots/base links into the extension's sensor attachment format.
def make_robots_override(robot_roots: list[str], attach_prims: list[str]) -> list[dict[str, str]]:
    robots: list[dict[str, str]] = []
    for robot_root, attach_prim in zip(robot_roots, attach_prims):
        robot_id = robot_root.rsplit("/", 1)[-1]
        attach_link = attach_prim[len(robot_root):].lstrip("/") if attach_prim.startswith(robot_root) else "base_link"
        robots.append({"id": robot_id, "root": robot_root, "attach_link": attach_link})
    return robots


# Configure the runtime and return a tick callback that publishes UDP packets.
def attach_radiation_runtime(
    app,
    stage,
    *,
    cfg_root: str | Path,
    world: str,
    root: str = "/World",
    air_mu: float = 0.001,
    no_obstacles: bool = False,
    apply_source_self_attenuation: bool = False,
    print_every: int = 0,
    robots_override: list[dict] | None = None,
) -> Callable[[], None]:
    ensure_radiation_extension_enabled(app)

    from radiation_simulator.api import configure, get_all_readings, get_sequence, step

    cfg_root_p = resolve_cfg_root(cfg_root)
    base_cfg = _load_toml(cfg_root_p / "base" / "sensor.toml")
    sensor_base = base_cfg.get("sensor", {}) or {}
    udp_host = str(sensor_base.get("udp_host", "127.0.0.1"))
    udp_port = int(sensor_base.get("udp_port", 50050))

    info = configure(
        stage,
        cfg_root=str(cfg_root_p),
        world=world,
        root=root,
        air_mu=float(air_mu),
        no_obstacles=bool(no_obstacles),
        apply_source_self_attenuation=bool(apply_source_self_attenuation),
        robots_override=robots_override,
    )
    print(
        f"[radiation] runtime configured cfg_root={info['cfg_root']} "
        f"sources={info['sources']} obstacles={info['obstacles']} sensors={info['sensors']}"
    )

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    last_sequence = -1
    packet_count = 0

    print(f"[udp] send to udp://{udp_host}:{udp_port}")

    def tick() -> None:
        nonlocal last_sequence, packet_count

        step(force=False)
        sequence = get_sequence()
        if sequence == last_sequence:
            return
        last_sequence = sequence

        for reading in get_all_readings():
            payload = reading.to_dict()
            sock.sendto(json.dumps(payload).encode("utf-8"), (udp_host, udp_port))

            packet_count += 1
            if packet_count == 1:
                print(
                    f"[tx:first] sensor={payload['sensor']} total={payload['total']:.6e} "
                    f"sources={len(payload['per_source'])} -> udp://{udp_host}:{udp_port}"
                )
            if print_every > 0 and (packet_count % int(print_every) == 0):
                pos_m = payload["pos_m"]
                print(
                    f"[tx] sensor={payload['sensor']} total={payload['total']:.6e} "
                    f"pos(m)=({pos_m[0]:.2f},{pos_m[1]:.2f},{pos_m[2]:.2f})"
                )

    setattr(tick, 'radiation_info', info)
    return tick
