# scripts/debug/test_spawn.py
from __future__ import annotations

import argparse
import time
from pathlib import Path

from isaacsim import SimulationApp


def _import_world_and_stage_utils():
    try:
        from isaacsim.core.api import World  # new
        from isaacsim.core.utils.stage import add_reference_to_stage
        return World, add_reference_to_stage
    except Exception:
        from omni.isaac.core import World  # old
        from omni.isaac.core.utils.stage import add_reference_to_stage
        return World, add_reference_to_stage


def get_stage():
    import omni.usd
    return omni.usd.get_context().get_stage()


def open_stage_blocking(app: SimulationApp, usd_path: str):
    import omni.usd
    ctx = omni.usd.get_context()
    ctx.open_stage(usd_path)
    for _ in range(6000):
        app.update()
        st = ctx.get_stage()
        if st is not None:
            try:
                if not ctx.is_loading():
                    return
            except Exception:
                return
    raise RuntimeError("Stage did not finish loading.")


def new_stage_blocking(app: SimulationApp):
    import omni.usd
    ctx = omni.usd.get_context()
    ctx.new_stage()
    for _ in range(600):
        app.update()
        if ctx.get_stage() is not None:
            return
    raise RuntimeError("Failed to create new stage.")


def set_xform_translate(prim_path: str, xyz):
    from pxr import UsdGeom, Gf
    stage = get_stage()
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


def set_xform_yaw_deg(prim_path: str, yaw_deg: float):
    from pxr import UsdGeom, Gf
    stage = get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise RuntimeError(f"Prim not found: {prim_path}")
    xf = UsdGeom.Xformable(prim)

    ops = xf.GetOrderedXformOps()
    r_op = None
    for op in ops:
        if op.GetOpType() in (UsdGeom.XformOp.TypeRotateXYZ, UsdGeom.XformOp.TypeRotateZYX):
            r_op = op
            break
    if r_op is None:
        r_op = xf.AddRotateZYXOp()
    r_op.Set(Gf.Vec3f(0.0, 0.0, float(yaw_deg)))


def find_base_link_path(robot_root: str) -> str:
    stage = get_stage()
    candidates = [
        f"{robot_root}/base_link",
        f"{robot_root}/jackal/base_link",
    ]
    for p in candidates:
        prim = stage.GetPrimAtPath(p)
        if prim and prim.IsValid():
            return p

    root_prim = stage.GetPrimAtPath(robot_root)
    if root_prim and root_prim.IsValid():
        from pxr import Usd
        for prim in Usd.PrimRange(root_prim):
            if prim.GetName() == "base_link":
                return prim.GetPath().pathString
    raise RuntimeError(f"base_link not found under {robot_root}")


def get_world_xyz(prim_path: str):
    from pxr import UsdGeom, Usd
    stage = get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        return (float("nan"), float("nan"), float("nan"))
    xf = UsdGeom.Xformable(prim)
    m = xf.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    p = m.ExtractTranslation()
    return (float(p[0]), float(p[1]), float(p[2]))


def disable_collisions_between_jackals_filtered_pairs(robot_roots: list[str]):
    """
    UsdPhysics.FilteredPairsAPI로 '로봇-로봇' 충돌만 OFF.
    collider prim을 찾지 않아도 동작하는 쪽이라 훨씬 안정적.
    """
    from pxr import UsdPhysics

    stage = get_stage()

    # 로봇마다 "필터를 걸 prim"을 잡는다: base_link(articulation root)가 최우선
    target_prims: list[str] = []
    for r in robot_roots:
        try:
            target_prims.append(find_base_link_path(r))  # 보통 /World/jackal_00/base_link
        except Exception:
            target_prims.append(r)  # fallback

    # 각 로봇 prim에 "나와 충돌하지 않을 대상들"을 전부 추가
    ok = 0
    for i, p in enumerate(target_prims):
        prim = stage.GetPrimAtPath(p)
        if not prim or not prim.IsValid():
            print(f"[disable_robot_collision] [WARN] prim invalid: {p}")
            continue

        api = UsdPhysics.FilteredPairsAPI.Apply(prim)
        rel = api.CreateFilteredPairsRel()

        # i 로봇은 나머지 전부와 충돌하지 않게
        for j, q in enumerate(target_prims):
            if i == j:
                continue
            rel.AddTarget(q)

        ok += 1

    print(f"[disable_robot_collision] FilteredPairs applied: {ok}/{len(target_prims)}")

def setup_dynamic_control():
    from omni.isaac.dynamic_control import _dynamic_control
    return _dynamic_control.acquire_dynamic_control_interface()


def get_articulation_handle(dc, base_link_path: str):
    try:
        return dc.get_articulation(base_link_path)
    except Exception:
        parent = "/".join(base_link_path.split("/")[:-1])
        return dc.get_articulation(parent)


def get_dof_name(dc, dof):
    try:
        return dc.get_dof_name(dof)
    except Exception:
        try:
            return dc.get_dof_info(dof).name
        except Exception:
            return ""


def get_articulation_dofs(dc, art):
    dofs = []
    try:
        n = dc.get_articulation_dof_count(art)
        for i in range(n):
            dofs.append(dc.get_articulation_dof(art, i))
    except Exception:
        pass
    return dofs


def pick_wheel_dofs(dc, art):
    dofs = get_articulation_dofs(dc, art)
    named = [(d, get_dof_name(dc, d)) for d in dofs]

    wheels = [(d, n) for (d, n) in named if ("wheel" in n.lower())]
    left = [(d, n) for (d, n) in wheels if ("left" in n.lower())]
    right = [(d, n) for (d, n) in wheels if ("right" in n.lower())]

    if left and right:
        return left, right, wheels
    return [], [], wheels


def set_wheel_velocities(dc, left_dofs, right_dofs, v_left, v_right):
    for d, _ in left_dofs:
        try:
            dc.set_dof_velocity_target(d, float(v_left))
        except Exception:
            pass
    for d, _ in right_dofs:
        try:
            dc.set_dof_velocity_target(d, float(v_right))
        except Exception:
            pass


def maybe_add_large_ground_plane(world, size: float):
    """
    1번(바닥이 '보이는 범위' 문제) 확인을 위해,
    빈 스테이지일 때 기본 ground를 가능한 크게 깔아줌.
    (버전마다 API가 달라서 실패하면 기본 ground로 fallback)
    """
    # 시각적으로 커지게 깔리는 게 목표(“검은 바탕에 떠 보임” 방지)
    try:
        # 어떤 버전은 size 인자를 받음
        world.scene.add_default_ground_plane(size=float(size))
        print(f"[ground] add_default_ground_plane(size={size})")
        return
    except Exception:
        pass

    try:
        world.scene.add_default_ground_plane()
        print("[ground] add_default_ground_plane() (size param not supported)")
    except Exception:
        print("[ground] [WARN] could not add default ground plane via World API")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default="", help="world USD 경로 (비우면 빈 스테이지)")
    ap.add_argument("--asset", default="assets/jackal/jackal/jackal_scoped.usda")
    ap.add_argument("--num", type=int, default=6)
    ap.add_argument("--spacing", type=float, default=2.0)
    ap.add_argument("--x0", type=float, default=0.0)
    ap.add_argument("--y0", type=float, default=0.0)
    ap.add_argument("--z0", type=float, default=0.35)
    ap.add_argument("--yaw0", type=float, default=0.0)
    ap.add_argument("--yaw_step", type=float, default=0.0)
    ap.add_argument("--steps", type=int, default=600)
    ap.add_argument("--headless", action="store_true", default=False)
    ap.add_argument("--keep-open", action="store_true", help="GUI 창을 계속 유지(닫을 때까지 계속 step)")
    ap.add_argument("--realtime", action="store_true", help="GUI에서 프레임을 실제시간에 가깝게 제한")
    ap.add_argument("--disable_robot_collision", action="store_true", help="jackal끼리 충돌을 비활성화합니다. 환경 충돌은 유지합니다.")
    ap.add_argument("--drive", default="mixed", choices=["forward", "spin", "mixed"])
    ap.add_argument("--v", type=float, default=6.0, help="wheel velocity rad/s (대충 테스트용)")
    ap.add_argument("--settle-steps", type=int, default=180, help="스폰 후 바닥 안착용 step 수")
    ap.add_argument("--ground-size", type=float, default=0.0, help="빈 스테이지일 때만: 보이는 바닥 크기(0이면 자동)")
    args = ap.parse_args()

    asset = Path(args.asset).resolve()
    if not asset.exists():
        raise FileNotFoundError(f"asset not found: {asset}")

    world_usd = args.world.strip()
    if world_usd:
        world_path = Path(world_usd)
        if not world_path.is_absolute():
            world_path = Path.cwd() / world_path
        world_path = world_path.resolve()
        if not world_path.exists():
            raise FileNotFoundError(f"world not found: {world_path}")
        world_usd = str(world_path)

    app = SimulationApp({"headless": args.headless})

    try:
        if world_usd:
            open_stage_blocking(app, world_usd)
        else:
            new_stage_blocking(app)

        World, add_reference_to_stage = _import_world_and_stage_utils()
        world = World(stage_units_in_meters=1.0, physics_dt=1.0 / 60.0, rendering_dt=1.0 / 60.0)

        # 빈 스테이지일 때만 ground(크게)
        if not world_usd:
            # 일자 스폰 길이에 맞춰 “보이는 바닥”을 크게
            auto_size = max(50.0, (args.num - 1) * args.spacing + 20.0)
            size = args.ground_size if args.ground_size > 0 else auto_size
            maybe_add_large_ground_plane(world, size=size)

        # Spawn robots (일자 유지)
        robot_roots = []
        for i in range(args.num):
            root = f"/World/jackal_{i:02d}"
            add_reference_to_stage(str(asset), root)
            set_xform_translate(root, (args.x0 + i * args.spacing, args.y0, args.z0))
            set_xform_yaw_deg(root, args.yaw0 + i * args.yaw_step)
            robot_roots.append(root)

        # 로봇-로봇 충돌 OFF
        if args.disable_robot_collision:
            disable_collisions_between_jackals_filtered_pairs(robot_roots)

        world.reset()

        # 스폰 직후 “안착” 시간 확보(중요: z 판정)
        for _ in range(max(0, args.settle_steps)):
            world.step(render=not args.headless)

        # 1번 판정: 바닥에 내려왔는지(z가 spawn 높이 그대로인지)
        base_links = [find_base_link_path(r) for r in robot_roots]
        zs = []
        for bl in base_links:
            _, _, z = get_world_xyz(bl)
            zs.append(z)

        zmin = min(zs) if zs else float("nan")
        zmax = max(zs) if zs else float("nan")
        print(f"\n[ground-check] after settle_steps={args.settle_steps}: z range = {zmin:.4f} .. {zmax:.4f}  (spawn z0={args.z0})")

        # spawn z0 근처에 그대로면 “바닥이 없거나(콜라이더 없음) / 물리 적용이 안 됨” 케이스
        stuck = [i for i, z in enumerate(zs) if abs(z - args.z0) < 1e-3]
        if stuck:
            print(f"[ground-check] [WARN] {len(stuck)} robots still near spawn z0 (likely no floor collider under them OR physics not affecting them)")
            print("               indices:", stuck[:20], ("..." if len(stuck) > 20 else ""))

        # dynamic control 준비 + wheel dof 잡기
        dc = setup_dynamic_control()
        wheel_maps = []
        for i, bl in enumerate(base_links):
            art = get_articulation_handle(dc, bl)
            try:
                dc.wake_up_articulation(art)
            except Exception:
                pass

            left, right, wheels = pick_wheel_dofs(dc, art)
            wheel_maps.append((left, right, wheels))

            print(f"\n[robot {i:02d}] root={robot_roots[i]}")
            print(f"  base_link={bl}")
            if wheels:
                print("  wheel dofs:")
                for _, n in wheels:
                    print("   -", n)
            else:
                print("  wheel dof not found by name filter (wheel).")

        # 시작 위치 기록
        start_xyz = [get_world_xyz(bl) for bl in base_links]

        dt = 1.0 / 60.0
        t0 = time.perf_counter()

        # 주행 명령: 동시에
        for step in range(args.steps):
            for i, (left, right, wheels) in enumerate(wheel_maps):
                if not wheels:
                    continue

                # left/right 못 잡히면 wheels 전체 동일 속도
                if not left or not right:
                    v = args.v
                    for d, _ in wheels:
                        try:
                            dc.set_dof_velocity_target(d, float(v))
                        except Exception:
                            pass
                    continue

                if args.drive == "forward":
                    vL, vR = args.v, args.v
                elif args.drive == "spin":
                    vL, vR = -args.v, args.v
                else:
                    if i % 2 == 0:
                        vL, vR = args.v, args.v
                    else:
                        vL, vR = -args.v, args.v

                set_wheel_velocities(dc, left, right, vL, vR)

            world.step(render=not args.headless)

            if args.realtime and not args.headless:
                target = t0 + (step + 1) * dt
                now = time.perf_counter()
                if target > now:
                    time.sleep(target - now)

        end_xyz = [get_world_xyz(bl) for bl in base_links]

        print("\n=== multi-robot motion report (base_link xyz) ===")
        for i, (s, e) in enumerate(zip(start_xyz, end_xyz)):
            dx, dy, dz = (e[0] - s[0], e[1] - s[1], e[2] - s[2])
            print(f"[{i:02d}] start={s}  end={e}  delta=({dx:.3f}, {dy:.3f}, {dz:.3f})")

        print("\nDone.")

        # keep-open: 창을 닫거나 Ctrl+C 할 때까지 계속 step
        if args.keep_open and not args.headless:
            print("\n[keep-open] window stays open. Close the window or Ctrl+C to exit.")
            while True:
                # is_running이 있으면 창 닫힘 감지
                try:
                    if hasattr(app, "is_running") and (not app.is_running()):
                        break
                except Exception:
                    pass

                world.step(render=True)

                if args.realtime:
                    time.sleep(dt)

    finally:
        app.close()


if __name__ == "__main__":
    main()
