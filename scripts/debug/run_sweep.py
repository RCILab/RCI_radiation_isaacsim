import argparse
import sys
from pathlib import Path

from isaacsim import SimulationApp

X_MIN = -10
X_MAX = 10
DX = 2

Y_MIN = -10
Y_MAX = 10
DY = 2

# sensor 높이
Z = 0.1

# ============================================================
# 디버깅할 probe 위치는 여기만 수정하면 됩니다
# (x, y, z) in stage units
DEBUG_PROBE_POINTS = [
    (0.0, 0.0, Z),
    (0.4, 2.0, Z),
    (7.0, 0.0, Z),
]
# ============================================================


def _parse_debug_point(value: str, default_z: float) -> tuple[float, float, float]:
    parts = [p.strip() for p in str(value).split(",") if p.strip()]
    if len(parts) not in (2, 3):
        raise argparse.ArgumentTypeError("debug point must be 'x,y' or 'x,y,z'")

    if len(parts) == 2:
        x_str, y_str = parts
        z_str = str(default_z)
    else:
        x_str, y_str, z_str = parts

    try:
        return (float(x_str), float(y_str), float(z_str))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid debug point '{value}'") from exc


def _format_tail_label(value: str, width: int = 18) -> str:
    value = str(value)
    if len(value) <= width:
        return value
    if width <= 3:
        return value[-width:]
    return "..." + value[-(width - 3):]


def _format_source_label(value: str, width: int = 24) -> str:
    value = str(value)
    prefix = "radiation_source_"
    if value.startswith(prefix):
        value = value[len(prefix):]

    parts = value.split("_")
    if len(parts) >= 3:
        head = parts[0]
        tail = "_".join(parts[-2:])
        compact = f"{head}...{tail}"
        if len(compact) <= width:
            return compact

    return _format_tail_label(value, width=width)




def _ensure_scripts_root_on_path():
    scripts_root = Path(__file__).resolve().parents[1]
    if str(scripts_root) not in sys.path:
        sys.path.insert(0, str(scripts_root))


def _ensure_radiation_extension_enabled(app):
    import omni.kit.app

    ws_root = Path(__file__).resolve().parents[2]
    ext_root = ws_root / "extensions"

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



def main():
    _ensure_scripts_root_on_path()

    from runtime.workspace_config import load_current_world_name, resolve_cfg_root, resolve_world_usd, resolve_workspace_path

    parser = argparse.ArgumentParser()

    # world / cfg
    parser.add_argument("--usd", default="", help="override world USD path; 비우면 current_world_name의 world.toml을 사용")
    parser.add_argument("--cfg_root", default="extensions/radiation.simulator/config")
    parser.add_argument("--world", default=None)

    # sweep range (그리드 모드에서만 사용)
    parser.add_argument("--x_min", type=float, default=X_MIN)
    parser.add_argument("--x_max", type=float, default=X_MAX)
    parser.add_argument("--dx", type=float, default=DX)
    parser.add_argument("--y_min", type=float, default=Y_MIN)
    parser.add_argument("--y_max", type=float, default=Y_MAX)
    parser.add_argument("--dy", type=float, default=DY)
    parser.add_argument("--z", type=float, default=Z)

    # radiation params (air)
    parser.add_argument("--air_mu", type=float, default=0.001, help="air attenuation coeff [1/m]")

    # probe
    parser.add_argument("--root", default="/World")
    parser.add_argument("--probe_path", default="/World/RadiationProbe")
    parser.add_argument("--probe_radius", type=float, default=0.03)
    parser.add_argument("--probe_height", type=float, default=0.05)

    # options
    parser.add_argument("--no_obstacles", action="store_true", help="ignore obstacles even if present (debug)")
    parser.add_argument("--save_usd", default="", help="If set, export stage to this path after applying customData.")

    # physics/raycast debug
    parser.add_argument("--physics_scene_path", default="/World/physicsScene")
    parser.add_argument("--apply_colliders", action="store_true", help="force-apply mesh colliders for obstacles")
    parser.add_argument("--collider_approx", default="mesh", help="PhysX collider approximation (mesh recommended)")
    parser.add_argument("--warmup_frames", type=int, default=90, help="frames to warmup PhysX after authoring")
    parser.add_argument("--debug_topk", type=int, default=5, help="top-k obstacles by mu*t to print")

    # 기본은 DEBUG_PROBE_POINTS만 평가하고, 필요하면 --use_grid로 그리드를 순회합니다
    parser.add_argument("--use_grid", action="store_true", help="use grid sweep instead of DEBUG_PROBE_POINTS")
    parser.add_argument(
        "--debug-point",
        dest="debug_points",
        action="append",
        default=[],
        metavar="X,Y[,Z]",
        help="override default debug points; repeatable",
    )

    # 선택: source가 포함된 obstacle까지 감쇠에 포함합니다
    parser.add_argument("--apply-source-self-attenuation", "--apply_source_self_attenuation", dest="apply_source_self_attenuation", choices=("true", "false"), default="false", help="include source self attenuation (default false)")

    parser.add_argument("--headless", action="store_true", default=False)

    args, unknown = parser.parse_known_args()
    if unknown:
        print("[INFO] ignoring unknown args:", unknown)
    args.apply_source_self_attenuation = (str(args.apply_source_self_attenuation).strip().lower() == "true")

    cfg_root = resolve_cfg_root(args.cfg_root)
    world_name = str(args.world or "").strip() or load_current_world_name()
    usd_path = str(resolve_workspace_path(args.usd)) if str(args.usd or "").strip() else str(resolve_world_usd(cfg_root, world_name))

    debug_points = [
        _parse_debug_point(raw, default_z=float(args.z)) for raw in getattr(args, "debug_points", [])
    ]
    if not debug_points:
        debug_points = [(float(x), float(y), float(z)) for (x, y, z) in DEBUG_PROBE_POINTS]

    # Isaac Sim must be launched BEFORE importing omni/pxr
    app = SimulationApp({"headless": args.headless})

    # deferred imports (safe after app exists)
    _ensure_radiation_extension_enabled(app)

    import inspect
    from pxr import UsdGeom

    from debug.radiation_debug import print_attachment_summary, scan_attachment_summary
    from radiation_simulator.authoring.config_loader import apply_radiation_customdata
    from radiation_simulator.authoring.usd_helpers import (
        ensure_obstacle_mesh_colliders,
        ensure_physics_scene,
        ensure_probe,
        get_custom,
        get_stage,
        get_world_translation,
        open_stage,
        set_xform_translate,
        warmup_physics,
    )
    from radiation_simulator.core.forward_model import RadiationSource, compute_total_intensity
    from radiation_simulator.core.raycast import (
        RayHit,
        get_scene_query_iface,
        raycast_iterative_hits,
        thickness_from_hits,
    )

    print(f"[open] {usd_path}")
    open_stage(usd_path, app, warmup_frames=60)

    stage = get_stage()
    if stage is None:
        raise RuntimeError("stage is None")

    m_per_unit = float(UsdGeom.GetStageMetersPerUnit(stage))
    print(f"[stage] metersPerUnit={m_per_unit}")

    # 1) apply customData from TOML (one-time per run)
    applied = apply_radiation_customdata(stage, cfg_root=str(cfg_root), world=world_name)
    print(f"[apply] obstacles={applied['obstacles_applied']} sources={applied['sources_applied']}")

    if args.save_usd:
        out = str(Path(args.save_usd).expanduser().resolve())
        print(f"[save] {out}")
        stage.Export(out)

    # 2) scan sources/obstacles by custom flag (customData only)
    summary = scan_attachment_summary(stage, root=args.root)
    print_attachment_summary(summary)
    sources_prims = summary["source_prims"]
    obstacles_prims = summary["obstacle_prims"]

    # build Source list
    sources: list[RadiationSource] = []
    for p in sources_prims:
        path = p.GetPath().pathString
        pos = get_world_translation(p)

        enabled = bool(get_custom(p, "radiation:enabled", True))
        intensity = float(get_custom(p, "radiation:intensity", 0.0) or 0.0)
        radius = float(get_custom(p, "radiation:radius", 0.1) or 0.1)

        if (not enabled) or intensity <= 0.0:
            continue

        # (선택) host obstacle 힌트가 있으면 Source에 넣어둠(라이브러리에서 지원할 때만 쓰임)
        host_obstacle = get_custom(p, "radiation:host_obstacle", None)
        if host_obstacle is not None:
            host_obstacle = str(host_obstacle)

        # 공기 감쇠 계수는 Source.mu_air로도 넣어 둠(라이브러리 시그니처 차이 방어)
        sources.append(
            RadiationSource(
                prim_path=path,
                pos=pos,
                intensity=intensity,
                radius=radius,
                enabled=True,
                mu_air=float(args.air_mu),
                **({"host_obstacle": host_obstacle} if "host_obstacle" in getattr(RadiationSource, "__annotations__", {}) else {}),
            )
        )

    print(f"[sources] configured={len(sources_prims)} resolved={len(sources)}")

    # build obstacles dict: {prim_path: mu}
    obstacles_mu: dict[str, float] = {}
    for p in obstacles_prims:
        mu = get_custom(p, "radiation:mu", None)
        if mu is None:
            continue
        obstacles_mu[p.GetPath().pathString] = float(mu)

    print(f"[obstacles] resolved_mu={len(obstacles_mu)}")

    # 3) prepare probe
    probe = ensure_probe(stage, args.probe_path, radius=args.probe_radius, height=args.probe_height)
    print(f"[probe] {args.probe_path}")

    # 4) prepare PhysX scene + colliders + warmup
    if not args.no_obstacles and len(obstacles_mu) > 0:
        ensure_physics_scene(stage, scene_path=args.physics_scene_path)

        if args.apply_colliders:
            mesh_cnt, applied_cnt = ensure_obstacle_mesh_colliders(
                stage,
                obstacle_root_paths=list(obstacles_mu.keys()),
                approximation=args.collider_approx,
                verbose=True,
            )
            print(f"[colliders] meshes={mesh_cnt} applied={applied_cnt} approx={args.collider_approx}")

        warmup_physics(app, stage, steps=int(args.warmup_frames), play=True)
        print(f"[physics] warmup_frames={args.warmup_frames}")

    # 5) physx raycast interface
    scene_query = None
    if not args.no_obstacles:
        try:
            scene_query = get_scene_query_iface()
        except Exception as e:
            print(f"[WARN] PhysX scene query interface not available: {type(e).__name__}: {e}")
            args.no_obstacles = True

    # ------------------------------------------------------------
    # metersPerUnit 보정 래퍼
    # thickness_from_hits는 hit.distance 단위를 그대로 쓰므로 metersPerUnit != 1일 때 보정
    # ------------------------------------------------------------
    def thickness_from_hits_meters(hits: list[RayHit], mu_by_path: dict[str, float]):
        if abs(float(m_per_unit) - 1.0) < 1e-12:
            return thickness_from_hits(hits, mu_by_path)

        scaled: list[RayHit] = []
        for h in hits:
            scaled.append(
                RayHit(
                    distance=float(h.distance) * float(m_per_unit),
                    collision=h.collision,
                    rigid_body=h.rigid_body,
                    position=h.position,
                    normal=h.normal,
                    face_index=h.face_index,
                )
            )
        return thickness_from_hits(scaled, mu_by_path)

    # ------------------------------------------------------------
    # compute_total_intensity 안전 호출(시그니처 호환)
    # ------------------------------------------------------------
    def call_compute_total_intensity(*, probe_pos, sources_list, solver, mu_air, apply_source_self_attenuation, debug_source_idx):
        sig = inspect.signature(compute_total_intensity)
        kw = {}

        # air attenuation 이름 호환
        if "mu_air" in sig.parameters:
            kw["mu_air"] = float(mu_air)
        elif "air_mu" in sig.parameters:
            kw["air_mu"] = float(mu_air)

        if "apply_source_self_attenuation" in sig.parameters:
            kw["apply_source_self_attenuation"] = bool(apply_source_self_attenuation)

        # obstacle solver 이름 호환
        if solver is not None:
            for name in ("obstacle_solver", "solver", "obstacles_solver", "obstacles"):
                if name in sig.parameters:
                    kw[name] = solver
                    break

        # debug index 이름 호환
        for name in ("debug_source_idx", "debug_idx", "debug_source"):
            if name in sig.parameters:
                kw[name] = int(debug_source_idx)
                break

        out = compute_total_intensity(probe_pos, sources_list, **kw)
        if isinstance(out, tuple) and len(out) == 2:
            return out
        return out, {}

    # ------------------------------------------------------------
    # 디버그 출력: 지정 위치에서 각 source별 기여도
    # ------------------------------------------------------------
    def debug_at_position(pos):
        # probe 이동
        set_xform_translate(stage, probe, pos)
        for _ in range(2):
            app.update()

        # solver: 라이브러리에서 obstacle_solver로 쓰일 수 있도록 구성
        obstacles_list = list(obstacles_mu.items())
        solver = None
        if (not args.no_obstacles) and (scene_query is not None) and obstacles_mu:
            solver = (
                scene_query,
                obstacles_list,
                raycast_iterative_hits,
                thickness_from_hits_meters,
                # extra ignore prefixes (probe + 소스 마커 root가 있으면 같이)
                [args.probe_path, "/World/RadiationSources"],
            )

        # 전체 합(라이브러리 계산)도 한 번 찍어둠
        total_all, _ = call_compute_total_intensity(
            probe_pos=pos,
            sources_list=sources,
            solver=solver,
            mu_air=float(args.air_mu),
            apply_source_self_attenuation=bool(args.apply_source_self_attenuation),
            debug_source_idx=0,
        )

        print("\n" + "=" * 110)
        print(f"[point] pos=({pos[0]:.3f}, {pos[1]:.3f}, {pos[2]:.3f})  metersPerUnit={m_per_unit}  apply_source_self_attenuation={bool(args.apply_source_self_attenuation)}")
        print("-" * 110)

        header = (
            "idx | source_name_compact      | dist(m) | dist_eff(m) | base | thick(m) | air_path(m) | air_att | mu_t_sum | obs_att | att(air*obs) | contrib"
        )
        print(header)
        print("-" * 110)

        manual_sum = 0.0
        topk = int(getattr(args, "debug_topk", 5))

        for i, s in enumerate(sources):
            # source 이름은 탱크 식별자와 끝 suffix가 같이 보이도록 압축해서 표시
            sname_raw = (s.prim_path.split("/")[-1] if getattr(s, "prim_path", "") else f"src{i}")
            sname = _format_source_label(sname_raw, width=24)

            # “source 1개만 넣어서” 라이브러리 계산 결과를 그대로 사용 → 수식 불일치 방지
            contrib, dbg = call_compute_total_intensity(
                probe_pos=pos,
                sources_list=[s],
                solver=solver,
                mu_air=float(args.air_mu),
                apply_source_self_attenuation=bool(args.apply_source_self_attenuation),
                debug_source_idx=0,
            )
            contrib = float(contrib)
            manual_sum += contrib

            # dbg가 없거나 키가 없을 수도 있으니 방어
            dist_m = float(dbg.get("dist_m", float("nan")))
            dist_eff_m = float(dbg.get("dist_eff_m", float("nan")))
            base = float(dbg.get("base", float("nan")))
            thick = float(dbg.get("obstacle_thickness_m", 0.0))
            air_path = float(dbg.get("air_path_m", float("nan")))
            air_att = float(dbg.get("air_att", float("nan")))
            mu_t_sum = float(dbg.get("mu_t_sum", 0.0))
            obs_att = float(dbg.get("obs_att", 1.0))
            att = float(dbg.get("air_att", 1.0)) * float(dbg.get("obs_att", 1.0))

            print(
                f"{i:>3d} | {sname:<24.24s} | "
                f"{dist_m:>7.3f} | {dist_eff_m:>10.3f} | {base:>8.2e} | "
                f"{thick:>8.4f} | {air_path:>10.4f} | {air_att:>7.2e} | "
                f"{mu_t_sum:>8.3f} | {obs_att:>7.2e} | {att:>11.2e} | {contrib:>8.2e}"
            )

            # obstacle 상세(top-k)
            terms = dbg.get("terms_top", []) or []
            if terms:
                for j, (opath, t, mu, mu_t) in enumerate(terms[:topk]):
                    print(f"     -> [{j}] {opath}  t={float(t):.4f}  mu={float(mu):.4f}  mu*t={float(mu_t):.4f}")

        print("-" * 110)
        print(f"[sum] per-source-sum={manual_sum:.6}   compute_total_intensity(all)={float(total_all):.6}")
        print("=" * 110)

    # ------------------------------------------------------------
    # 실행: 기본은 지정 포인트 디버그, 필요하면 --use_grid로 그리드
    # ------------------------------------------------------------
    if not args.use_grid:
        for p in debug_points:
            debug_at_position((float(p[0]), float(p[1]), float(p[2])))

        if getattr(args, "headless", False):
            print("\n[done] debug points complete. Headless mode: closing app.")
            app.close()
            return

        print("\n[done] debug points complete. Close window to exit.")
        while app.is_running():
            app.update()
        app.close()
        return

    # (옵션) 기존 그리드 스윕 유지
    x = args.x_min
    while x <= args.x_max + 1e-9:
        y = args.y_min
        while y <= args.y_max + 1e-9:
            pos = (float(x), float(y), float(args.z))
            set_xform_translate(stage, probe, pos)
            for _ in range(2):
                app.update()

            obstacles_list = list(obstacles_mu.items())
            solver = None
            if (not args.no_obstacles) and (scene_query is not None) and obstacles_mu:
                solver = (
                    scene_query,
                    obstacles_list,
                    raycast_iterative_hits,
                    thickness_from_hits_meters,
                    [args.probe_path, "/World/RadiationSources"],
                )

            total, _ = call_compute_total_intensity(
                probe_pos=pos,
                sources_list=sources,
                solver=solver,
                mu_air=float(args.air_mu),
                apply_source_self_attenuation=bool(args.apply_source_self_attenuation),
                debug_source_idx=0,
            )
            print(f"[sweep] pos=({pos[0]:.2f},{pos[1]:.2f},{pos[2]:.2f}) total={float(total):.6e}")

            y += args.dy
        x += args.dx

    print("[done] grid sweep complete. Close window to exit.")
    while app.is_running():
        app.update()
    app.close()


if __name__ == "__main__":
    main()
