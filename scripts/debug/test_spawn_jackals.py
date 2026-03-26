# scripts/debug/test_spawn_jackals.py
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def _bootstrap_sys_path():
    # scripts/ 폴더를 sys.path에 넣어 spawn 패키지 import가 안정적으로 되게 함
    this = Path(__file__).resolve()
    scripts_dir = this.parents[1]  # .../scripts
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def _import_world_and_stage_utils():
    """
    isaacsim.* / omni.isaac.* 둘 다 대응.
    """
    try:
        from isaacsim.core.api import World  # new
        from isaacsim.core.utils.stage import add_reference_to_stage
        return World, add_reference_to_stage
    except Exception:
        from omni.isaac.core import World  # old
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
        # 버전에 따라 is_loading이 없을 수 있음
        try:
            if not ctx.is_loading():
                return
        except Exception:
            return

    raise RuntimeError(f"Stage did not finish loading: {usd_path}")


def _new_stage_blocking(app, timeout_frames: int = 600):
    import omni.usd
    ctx = omni.usd.get_context()
    ctx.new_stage()

    for _ in range(timeout_frames):
        app.update()
        if ctx.get_stage() is not None:
            return
    raise RuntimeError("Failed to create new stage.")


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


def _hold_window_open(app):
    print("\n[keep-open] window stays open. Close the window or Ctrl+C to exit.\n")
    try:
        while True:
            # is_running()이 있으면 창 닫힘 감지 가능
            try:
                if hasattr(app, "is_running") and not app.is_running():
                    break
            except Exception:
                pass

            app.update()
            time.sleep(1.0 / 60.0)
    except KeyboardInterrupt:
        pass


def main():
    _bootstrap_sys_path()

    from runtime.workspace_config import load_current_world_name

    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default="", help="USD world path (optional)")
    ap.add_argument("--asset", default="assets/jackal/jackal/jackal_scoped.usda")
    ap.add_argument("--spawn-world", default=None, help="spawn csv world name under config/ (비우면 current_world_name 사용)")
    ap.add_argument("--spawn-csv", default=None, help="override spawn pose csv path (default: config/<spawn-world>/spawn/jackal_spawns.csv)")
    ap.add_argument("--num", type=int, default=None, help="spawn count (default: selected csv row count)")
    ap.add_argument("--headless", action="store_true", default=False)
    ap.add_argument("--keep-open", action="store_true", default=False)
    ap.add_argument("--steps", type=int, default=600, help="simulation steps (0이면 움직이지 않고 종료/keep-open)")
    ap.add_argument("--settle-steps", type=int, default=180, help="spawn 후 바닥에 settle 시키는 프레임")

    ap.add_argument(
        "--disable-robot-collision",
        "--disable_robot_collision",
        dest="disable_robot_collision",
        choices=("true", "false"),
        default="true",
        help="로봇끼리 충돌을 비활성화할지 여부. 기본 true, 허용하려면 false",
    )
    args, unknown = ap.parse_known_args()
    args.disable_robot_collision = (str(args.disable_robot_collision).strip().lower() == "true")

    if unknown:
        # Kit가 주입하는 알 수 없는 인자 때문에 종료되지 않게 하려고 의도적으로 무시함
        print("[INFO] ignoring unknown args:", unknown)

    spawn_world = str(args.spawn_world or "").strip() or load_current_world_name()

    asset = Path(args.asset)
    if not asset.is_absolute():
        asset = (Path.cwd() / asset).resolve()
    if not asset.exists():
        raise FileNotFoundError(f"asset not found: {asset}")

    world_usd = args.world.strip()
    if world_usd:
        wp = Path(world_usd)
        if not wp.is_absolute():
            wp = (Path.cwd() / wp).resolve()
        if not wp.exists():
            raise FileNotFoundError(f"world not found: {wp}")
        world_usd = str(wp)

    # 중요: SimulationApp 생성 BEFORE omni/pxr import
    from isaacsim import SimulationApp
    app = SimulationApp({"headless": args.headless})

    try:
        if world_usd:
            _open_stage_blocking(app, world_usd)
        else:
            _new_stage_blocking(app)

        World, add_reference_to_stage = _import_world_and_stage_utils()
        world = World(stage_units_in_meters=1.0, physics_dt=1.0 / 60.0, rendering_dt=1.0 / 60.0)

        # 빈 스테이지일 때만 default ground
        if not world_usd:
            try:
                world.scene.add_default_ground_plane()
            except Exception:
                pass
        
        from pxr import Sdf

        stage = _get_stage()

        # 전역 좌표 기반 스폰
        from spawn.spawn_config import iter_spawn_transforms
        robot_roots = []

        # 스폰 루프
        for i, (x, y, z, yaw) in enumerate(iter_spawn_transforms(args.num, csv_path=args.spawn_csv, world=spawn_world)):
            root = f"/World/jackal_{i:02d}" 
            child = f"{root}/robot"

            stage.DefinePrim(Sdf.Path(root), "Xform")

            add_reference_to_stage(str(asset), child)

            _set_xform_translate(root, (x, y, z))
            _set_xform_yaw_deg(root, yaw)

            robot_roots.append(root)

        # 로봇끼리만 충돌 OFF
        if args.disable_robot_collision:
            from spawn.collision_switch import disable_collisions_between_robots
            disable_collisions_between_robots(robot_roots)

        world.reset()

        # settle
        for _ in range(max(0, int(args.settle_steps))):
            world.step(render=not args.headless)

        # 기본은 “스폰 + 충돌필터 유지 + settle”까지만
        # (주행/제어는 통합 런치 쪽에서 본격적으로 붙이는 게 더 안전해서 여기서는 넣지 않음)
        for _ in range(max(0, int(args.steps))):
            world.step(render=not args.headless)

        if args.keep_open and not args.headless:
            _hold_window_open(app)

    finally:
        app.close()


if __name__ == "__main__":
    main()
