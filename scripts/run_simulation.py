# scripts/run_simulation.py
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import List, Optional, Callable

from isaacsim import SimulationApp


def _bootstrap_sys_path():
    """
    scripts/를 sys.path에 넣어 spawn, drive, runtime helper import를 안정화합니다.
    """
    this = Path(__file__).resolve()
    scripts_dir = this.parent  # .../scripts
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def _import_world_and_stage_utils():
    try:
        from isaacsim.core.api import World
        from isaacsim.core.utils.stage import add_reference_to_stage
        return World, add_reference_to_stage
    except Exception:
        from omni.isaac.core import World
        from omni.isaac.core.utils.stage import add_reference_to_stage
        return World, add_reference_to_stage


def _get_stage():
    import omni.usd
    return omni.usd.get_context().get_stage()


def _open_stage_blocking(app, usd_path: str, timeout_frames: int = 6000):
    import omni.usd
    ctx = omni.usd.get_context()
    ctx.open_stage(usd_path)

    for _ in range(timeout_frames):
        app.update()
        st = ctx.get_stage()
        if st is None:
            continue
        try:
            if not ctx.is_loading():
                return
        except Exception:
            return

    raise RuntimeError(f"Stage did not finish loading: {usd_path}")


def _set_xform_translate(prim_path: str, xyz):
    from pxr import UsdGeom, Gf
    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise RuntimeError(f"Prim not found: {prim_path}")

    xf = UsdGeom.Xformable(prim)
    ops = xf.GetOrderedXformOps()
    t_op = None
    for op in ops:
        if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
            t_op = op
            break
    if t_op is None:
        t_op = xf.AddTranslateOp()
    t_op.Set(Gf.Vec3d(*xyz))


def _set_xform_yaw_deg(prim_path: str, yaw_deg: float):
    """
    주의: spawn_config의 yaw는 'deg'로 다루는 전제.
    (현재 spawn 유틸도 yaw_deg 기준으로 설정함)
    """
    from pxr import UsdGeom, Gf
    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise RuntimeError(f"Prim not found: {prim_path}")

    xf = UsdGeom.Xformable(prim)
    ops = xf.GetOrderedXformOps()
    r_op = None
    for op in ops:
        if op.GetOpType() in (UsdGeom.XformOp.TypeRotateZYX, UsdGeom.XformOp.TypeRotateXYZ):
            r_op = op
            break
    if r_op is None:
        r_op = xf.AddRotateZYXOp()
    r_op.Set(Gf.Vec3f(0.0, 0.0, float(yaw_deg)))


def _find_base_link_path(robot_root: str) -> str:
    stage = _get_stage()
    candidates = [
        f"{robot_root}/base_link",
        f"{robot_root}/jackal/base_link",
        f"{robot_root}/robot/base_link",
        f"{robot_root}/robot/jackal/base_link",
    ]
    for p in candidates:
        prim = stage.GetPrimAtPath(p)
        if prim and prim.IsValid():
            return p

    from pxr import Usd
    root = stage.GetPrimAtPath(robot_root)
    if root and root.IsValid():
        for prim in Usd.PrimRange(root):
            if prim.GetName() == "base_link":
                return prim.GetPath().pathString

    raise RuntimeError(f"base_link not found under {robot_root}")


def _hold_window_open(app):
    print("\n[keep-open] window stays open. Close the window or Ctrl+C to exit.\n")
    try:
        while True:
            try:
                if hasattr(app, "is_running") and not app.is_running():
                    break
            except Exception:
                pass
            app.update()
            time.sleep(1.0 / 60.0)
    except KeyboardInterrupt:
        pass


def _parse_speed_list(s: str) -> List[float]:
    out = []
    for tok in s.split(","):
        tok = tok.strip()
        if not tok:
            continue
        out.append(float(tok))
    return out


def main():
    _bootstrap_sys_path()

    from runtime.workspace_config import load_current_world_name, resolve_cfg_root, resolve_world_usd, resolve_workspace_path

    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default="", help="override world USD path; 비우면 current_world_name의 world.toml을 사용")
    ap.add_argument("--asset", default="assets/jackal/jackal/jackal_scoped.usda")
    ap.add_argument("--spawn-csv", default=None, help="override spawn pose csv path (default: config/<selected-world>/spawn/jackal_spawns.csv)")
    ap.add_argument("--num", type=int, default=None, help="None/<=0이면 선택된 spawn csv 행 수만큼")
    ap.add_argument("--headless", action="store_true", default=False)
    ap.add_argument("--keep-open", "--keep_open", dest="keep_open", choices=("true", "false"), default="true", help="유한 step 실행 후 GUI 창을 계속 열어둘지 여부. 기본 true")
    ap.add_argument("--realtime", dest="realtime", choices=("true", "false"), default="true", help="GUI에서 프레임을 실제시간(physics_dt)에 가깝게 제한할지 여부. 기본 true")

    ap.add_argument("--steps", type=int, default=-1, help="<=0이면 무한 실행(창 닫거나 Ctrl+C까지)")
    ap.add_argument("--settle-steps", type=int, default=180)

    ap.add_argument(
        "--disable-robot-collision",
        "--disable_robot_collision",
        dest="disable_robot_collision",
        choices=("true", "false"),
        default="true",
        help="로봇끼리 충돌을 비활성화할지 여부. 기본 true, 허용하려면 false",
    )

    # drive params
    ap.add_argument("--base-speed", type=float, default=0.8)
    ap.add_argument("--speed-list", default="", help="로봇별 속도(m/s) 예: 0.6,0.8,1.0  (비우면 base-speed)")
    ap.add_argument("--wheel-radius", type=float, default=0.098)
    ap.add_argument("--wheel-base", type=float, default=0.375)

    # ray/avoid
    ap.add_argument("--max-ray", type=float, default=8.0)
    ap.add_argument("--ray-fov-deg", type=float, default=180.0)
    ap.add_argument("--ray-count", type=int, default=21)
    ap.add_argument("--ray-update-hz", type=float, default=10.0)
    ap.add_argument("--z-offset", type=float, default=0.20)

    ap.add_argument("--slow-dist", type=float, default=1.5)
    ap.add_argument("--stop-dist", type=float, default=0.6)
    ap.add_argument("--backup-speed", type=float, default=0.25)
    ap.add_argument("--turn-gain", type=float, default=1.2)
    ap.add_argument("--turn-in-place", type=float, default=1.6)

    # radiation runtime
    ap.add_argument("--enable-radiation", "--enable_radiation", dest="enable_radiation", choices=("true", "false"), default="true", help="radiation extension runtime tick을 연결할지 여부. 기본 true")
    ap.add_argument("--cfg-root", default="extensions/radiation.simulator/config", help="radiation config root (base/, worlds/ 포함)")
    ap.add_argument("--cfg-world", default=None, help="cfg_root/worlds/<cfg-world>/... 에 사용할 world 이름 (None일 경우 default값으로 current_world_name 사용)")
    ap.add_argument("--sensor-root", default="/World", help="radiation scan root prim")
    ap.add_argument("--sensor-print-every", type=int, default=0, help="sensor tx print_every (0이면 안 찍음)")
    ap.add_argument("--sensor-no-obstacles", action="store_true", default=False, help="센서에서 장애물 감쇠(ray) 끔")

    ap.add_argument(
        "--apply-source-self-attenuation",
        "--apply_source_self_attenuation",
        dest="apply_source_self_attenuation",
        choices=("true", "false"),
        default="false",
        help="source 자신의 self attenuation을 적용할지 여부. 기본 false",
    )

    args = ap.parse_args()
    args.keep_open = (str(args.keep_open).strip().lower() == "true")
    args.realtime = (str(args.realtime).strip().lower() == "true")
    args.enable_radiation = (str(args.enable_radiation).strip().lower() == "true")
    args.disable_robot_collision = (str(args.disable_robot_collision).strip().lower() == "true")
    args.apply_source_self_attenuation = (str(args.apply_source_self_attenuation).strip().lower() == "true")

    cfg_root = resolve_cfg_root(args.cfg_root)
    cfg_world = str(args.cfg_world or "").strip() or load_current_world_name()

    world_arg = str(args.world or "").strip()
    if world_arg:
        world_path = resolve_workspace_path(world_arg)
    else:
        world_path = resolve_world_usd(cfg_root, cfg_world)

    asset_path = resolve_workspace_path(args.asset)

    if not world_path.exists():
        raise FileNotFoundError(f"world not found: {world_path}")
    if not asset_path.exists():
        raise FileNotFoundError(f"asset not found: {asset_path}")

    # per-robot speed
    speed_list = _parse_speed_list(args.speed_list) if args.speed_list.strip() else []

    def speed_for(i: int) -> float:
        if not speed_list:
            return float(args.base_speed)
        if len(speed_list) == 1:
            return float(speed_list[0])
        return float(speed_list[i]) if i < len(speed_list) else float(speed_list[-1])

    # IMPORTANT: SimulationApp 생성 BEFORE omni/pxr 계열 적극 사용
    app = SimulationApp({"headless": args.headless})
    try:
        _open_stage_blocking(app, str(world_path))

        World, add_reference_to_stage = _import_world_and_stage_utils()
        world = World(stage_units_in_meters=1.0, physics_dt=1.0 / 60.0, rendering_dt=1.0 / 60.0)

        # spawn / collision_switch
        from spawn.spawn_config import iter_spawn_transforms
        from spawn.collision_switch import disable_collisions_between_robots

        # drive module
        from drive.diff_drive import acquire_dynamic_control, WheelController
        from drive.raycast_avoid import make_fan_angles, cast_fan_from_base_link, ReactiveAvoider

        from pxr import Sdf
        stage = _get_stage()

        # ---- spawn (spawn_config 그대로 사용) ----
        robot_roots: List[str] = []
        for i, (x, y, z, yaw_deg) in enumerate(iter_spawn_transforms(args.num, csv_path=args.spawn_csv, world=cfg_world)):
            root = f"/World/jackal_{i:02d}"
            child = f"{root}/robot"

            stage.DefinePrim(Sdf.Path(root), "Xform")
            add_reference_to_stage(str(asset_path), child)

            _set_xform_translate(root, (x, y, z))
            _set_xform_yaw_deg(root, float(yaw_deg))

            robot_roots.append(root)

        # ---- disable_robot_collision (collision_switch 사용) ----
        if args.disable_robot_collision:
            disable_collisions_between_robots(robot_roots, verbose=True)

        world.reset()

        # settle
        for _ in range(max(0, int(args.settle_steps))):
            world.step(render=not args.headless)

        base_links = [_find_base_link_path(r) for r in robot_roots]

        # ---- wheel controller ----
        dc = acquire_dynamic_control()
        controllers = [WheelController.from_base_link(dc, bl) for bl in base_links]

        # ---- ray fan + avoider ----
        angles = make_fan_angles(int(args.ray_count), float(args.ray_fov_deg))
        avoider = ReactiveAvoider(
            slow_dist=float(args.slow_dist),
            stop_dist=float(args.stop_dist),
            backup_speed=float(args.backup_speed),
            turn_gain=float(args.turn_gain),
            turn_in_place=float(args.turn_in_place),
        )

        dt = 1.0 / 60.0
        ray_period = (1.0 / float(args.ray_update_hz)) if args.ray_update_hz and args.ray_update_hz > 0 else 0.0
        next_ray_t = [0.0 for _ in base_links]
        cached_vw = [(speed_for(i), 0.0) for i in range(len(base_links))]

        # ---- radiation runtime tick 연결 ----
        sensor_tick: Optional[Callable[[], None]] = None
        if args.enable_radiation:
            from debug.radiation_debug import print_attachment_summary, scan_attachment_summary
            from runtime import attach_radiation_runtime, make_robots_override

            robots_override = make_robots_override(robot_roots, base_links)

            sensor_tick = attach_radiation_runtime(
                app,
                stage,
                cfg_root=str(cfg_root),
                world=cfg_world,
                root=str(args.sensor_root),
                no_obstacles=bool(args.sensor_no_obstacles),
                print_every=int(args.sensor_print_every),
                robots_override=robots_override,
                apply_source_self_attenuation=bool(args.apply_source_self_attenuation),
            )
            print_attachment_summary(scan_attachment_summary(stage, root=str(args.sensor_root)))
            print("[sensor] tick attached")

        t0 = time.perf_counter()
        step = 0

        def _do_one_step(step_idx: int):
            nonlocal t0

            now_t = step_idx * dt

            for i, bl in enumerate(base_links):
                if ray_period == 0.0 or now_t >= next_ray_t[i]:
                    dists = cast_fan_from_base_link(
                        bl, angles, float(args.max_ray), z_offset=float(args.z_offset)
                    )
                    v, w = avoider.compute_vw(dists, base_speed=speed_for(i))
                    cached_vw[i] = (v, w)
                    next_ray_t[i] = now_t + ray_period

                v, w = cached_vw[i]
                controllers[i].command_vw(
                    dc,
                    v,
                    w,
                    wheel_radius=float(args.wheel_radius),
                    wheel_base=float(args.wheel_base),
                )

            world.step(render=not args.headless)

            # 센서 tick 호출 실패 시의 로그
            if sensor_tick is not None:
                try:
                    sensor_tick()
                except Exception as e:
                    print(f"[sensor] [WARN] tick failed: {type(e).__name__}: {e}")

            if args.realtime and (not args.headless):
                target = t0 + (step_idx + 1) * dt
                now = time.perf_counter()
                if target > now:
                    time.sleep(target - now)

        # ---- main loop ----
        if args.steps is not None and int(args.steps) > 0:
            for i in range(int(args.steps)):
                _do_one_step(i)
            print("Done (no-ROS reactive avoidance).")

            if args.keep_open and not args.headless:
                _hold_window_open(app)
        else:
            print("[run] infinite loop (steps<=0). Close the window or Ctrl+C to stop.")
            try:
                while True:
                    # GUI면 창 닫힘 감지
                    try:
                        if hasattr(app, "is_running") and (not app.is_running()):
                            break
                    except Exception:
                        pass

                    _do_one_step(step)
                    step += 1
            except KeyboardInterrupt:
                pass
            print("[exit] stopped.")

    finally:
        app.close()


if __name__ == "__main__":
    main()
