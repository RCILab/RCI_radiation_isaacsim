# scripts/spawn/collision_switch.py
from __future__ import annotations

from typing import Iterable, List


def _get_stage():
    import omni.usd
    return omni.usd.get_context().get_stage()


def _find_base_link_path(robot_root: str) -> str:
    """
    /World/jackal_00/base_link  또는  /World/jackal_00/jackal/base_link
    둘 다 대응.
    """
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

    # fallback: root 아래에서 base_link 이름을 탐색(1회)
    from pxr import Usd
    root = stage.GetPrimAtPath(robot_root)
    if root and root.IsValid():
        for prim in Usd.PrimRange(root):
            if prim.GetName() == "base_link":
                return prim.GetPath().pathString

    raise RuntimeError(f"base_link not found under {robot_root}")


def disable_collisions_between_robots(robot_roots: Iterable[str], *, verbose: bool = True) -> List[str]:
    """
    UsdPhysics.FilteredPairsAPI로 '로봇-로봇' 충돌만 OFF.
    - 콜라이더를 직접 찾지 않음 (인스턴싱/프로토타입에서도 안정적)
    - 환경(월드/장애물)과의 충돌은 그대로 유지
    반환: 실제로 필터 적용에 사용한 prim paths (보통 base_link paths)
    """
    from pxr import UsdPhysics

    stage = _get_stage()

    robot_roots = list(robot_roots)
    if not robot_roots:
        return []

    # 필터를 걸 대상 prim = 로봇별 base_link(최우선)
    target_paths: List[str] = []
    for r in robot_roots:
        try:
            target_paths.append(_find_base_link_path(r))
        except Exception:
            # 정말 최악의 경우 root 자체라도 걸어둠
            target_paths.append(r)

    # 모든 로봇에 대해 나머지 로봇을 filteredPairs로 추가 (대칭 적용)
    applied = 0
    for i, p in enumerate(target_paths):
        prim = stage.GetPrimAtPath(p)
        if not prim or not prim.IsValid():
            if verbose:
                print(f"[disable_robot_collision] [WARN] prim invalid: {p}")
            continue

        api = UsdPhysics.FilteredPairsAPI.Apply(prim)
        rel = api.CreateFilteredPairsRel()

        # 중복 실행 대비: 기존 타겟 삭제
        try:
            rel.ClearTargets(True)
        except Exception:
            try:
                rel.SetTargets([])
            except Exception:
                pass

        for j, q in enumerate(target_paths):
            if i == j:
                continue
            rel.AddTarget(q)

        applied += 1

    if verbose:
        print(f"[disable_robot_collision] FilteredPairs applied: {applied}/{len(target_paths)}")
        # 디버깅용으로 어떤 prim에 걸렸는지 출력하고 싶으면 아래 주석 해제
        # for p in target_paths:
        #     print("  -", p)

    return target_paths
