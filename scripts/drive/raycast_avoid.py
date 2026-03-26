# scripts/drive/raycast_avoid.py
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple

from drive.pose import get_world_xyz_yaw


def _raycast_closest(origin, direction, max_dist: float) -> float:
    import omni.physx
    q = omni.physx.get_physx_scene_query_interface()
    hit = q.raycast_closest(origin, direction, max_dist)
    if not hit.get("hit", False):
        return max_dist
    return float(hit.get("distance", max_dist))


def make_fan_angles(num_rays: int, fov_deg: float) -> List[float]:
    if num_rays <= 1:
        return [0.0]
    fov = math.radians(float(fov_deg))
    start = -0.5 * fov
    step = fov / (num_rays - 1)
    return [start + i * step for i in range(num_rays)]


def cast_fan_from_base_link(
    base_link: str,
    angles: List[float],
    max_dist: float,
    *,
    z_offset: float = 0.20,
) -> List[float]:
    import carb

    x, y, z, yaw = get_world_xyz_yaw(base_link)
    origin = carb.Float3(float(x), float(y), float(z + z_offset))

    dists: List[float] = []
    for a in angles:
        th = yaw + a
        direction = carb.Float3(float(math.cos(th)), float(math.sin(th)), 0.0)
        dists.append(_raycast_closest(origin, direction, max_dist))

    return dists


@dataclass
class ReactiveAvoider:
    """
    간단하지만 '벽에 박혀서 못 나옴'을 줄이기 위해:
    - 전방이 너무 가까우면 후진 + 회전
    - 전방이 가까우면 감속
    - 좌우 평균거리 차로 회전
    """
    slow_dist: float = 1.5
    stop_dist: float = 0.6
    backup_speed: float = 0.25
    turn_gain: float = 1.2
    turn_in_place: float = 1.6

    def compute_vw(self, dists: List[float], base_speed: float) -> Tuple[float, float]:
        if not dists:
            return base_speed, 0.0

        n = len(dists)
        mid = n // 2

        # 전방 섹터(가운데 주변) 최소거리
        k = max(1, n // 6)  # 중앙 ±k
        front = dists[max(0, mid - k) : min(n, mid + k + 1)]
        front_min = min(front) if front else dists[mid]

        left = sum(dists[:mid]) / max(1, mid)
        right = sum(dists[mid + 1 :]) / max(1, n - mid - 1)

        # 1) 너무 가까우면: 후진 + 더 넓은 쪽으로 회전
        if front_min < self.stop_dist:
            w = self.turn_in_place if right > left else -self.turn_in_place
            return -self.backup_speed, w

        # 2) 가까우면 감속
        v = float(base_speed)
        if front_min < self.slow_dist:
            v *= max(0.0, front_min / self.slow_dist)

        # 3) 좌/우 차로 회전 (왼쪽이 가까우면 오른쪽으로(+))
        w = self.turn_gain * float(right - left)
        return v, w
