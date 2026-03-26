from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

import carb
import omni.physx


@dataclass(frozen=True)
class RayHit:
    distance: float
    collision: str
    rigid_body: str
    position: tuple[float, float, float]
    normal: tuple[float, float, float]
    face_index: int


def get_scene_query_iface():
    return omni.physx.get_physx_scene_query_interface()


def _f3_to_tuple(value) -> tuple[float, float, float]:
    try:
        return (float(value.x), float(value.y), float(value.z))
    except Exception:
        return (float(value[0]), float(value[1]), float(value[2]))


def _make_f3(x: float, y: float, z: float):
    return carb.Float3(float(x), float(y), float(z))


def _resolve_obstacle_path(collision_path: str, mu_by_path: dict[str, float]):
    from pxr import Sdf

    if not collision_path:
        return None, None

    path = Sdf.Path(collision_path)
    while path and path != Sdf.Path.absoluteRootPath:
        path_str = path.pathString
        if path_str in mu_by_path:
            return path_str, float(mu_by_path[path_str])
        path = path.GetParentPath()
    return None, None


def _dedupe_sorted_distances(distances: list[float], epsilon: float) -> list[float]:
    merged: list[float] = []
    for distance in distances:
        value = float(distance)
        if not merged or abs(value - merged[-1]) > float(epsilon):
            merged.append(value)
    return merged


def _paired_thickness(distances: list[float]) -> float:
    thickness = 0.0
    for index in range(0, len(distances) - 1, 2):
        segment = float(distances[index + 1]) - float(distances[index])
        if segment > 0.0:
            thickness += segment
    return thickness


def raycast_all_hits(
    scene_query,
    origin_xyz: tuple[float, float, float],
    target_xyz: tuple[float, float, float],
    *,
    both_sides: bool = True,
    max_hits: int = 256,
    ignore_prefixes: Iterable[str] | None = None,
) -> list[RayHit]:
    ox, oy, oz = origin_xyz
    tx, ty, tz = target_xyz
    dx, dy, dz = (tx - ox, ty - oy, tz - oz)
    total_distance = math.sqrt(dx * dx + dy * dy + dz * dz)
    if total_distance < 1e-9:
        return []

    direction = _make_f3(dx / total_distance, dy / total_distance, dz / total_distance)
    origin = _make_f3(ox, oy, oz)
    ignored_prefixes = tuple(prefix for prefix in (ignore_prefixes or []) if prefix)
    hits: list[RayHit] = []

    def _report_fn(hit) -> bool:
        collision_path = getattr(hit, 'collision', '') or ''
        rigid_body = getattr(hit, 'rigid_body', '') or ''

        if collision_path and ignored_prefixes:
            for prefix in ignored_prefixes:
                if collision_path.startswith(prefix):
                    return True

        hits.append(
            RayHit(
                distance=float(getattr(hit, 'distance', 0.0)),
                collision=collision_path,
                rigid_body=rigid_body,
                position=_f3_to_tuple(getattr(hit, 'position', (0.0, 0.0, 0.0))),
                normal=_f3_to_tuple(getattr(hit, 'normal', (0.0, 0.0, 0.0))),
                face_index=int(getattr(hit, 'face_index', -1)),
            )
        )
        return len(hits) < max_hits

    scene_query.raycast_all(origin, direction, float(total_distance), _report_fn, bothSides=both_sides)
    hits.sort(key=lambda hit: hit.distance)
    return hits


def raycast_iterative_hits(
    scene_query,
    origin_xyz: tuple[float, float, float],
    target_xyz: tuple[float, float, float],
    *,
    both_sides: bool = True,
    max_hits: int = 256,
    ignore_prefixes: Iterable[str] | None = None,
    epsilon: float = 1e-4,
) -> list[RayHit]:
    """
    Collect boundary hits along a single source->sensor ray.

    For closed triangle meshes with bothSides=True, repeated closest-hit queries return
    entry/exit boundaries in order. Those boundaries are later paired into penetration depth.
    """
    ox, oy, oz = origin_xyz
    tx, ty, tz = target_xyz
    dx, dy, dz = (tx - ox, ty - oy, tz - oz)
    total_distance = math.sqrt(dx * dx + dy * dy + dz * dz)
    if total_distance < 1e-9:
        return []

    direction = _make_f3(dx / total_distance, dy / total_distance, dz / total_distance)
    ignored_prefixes = tuple(prefix for prefix in (ignore_prefixes or []) if prefix)

    hits: list[RayHit] = []
    traveled = 0.0
    remaining = total_distance

    while remaining > 1e-6 and len(hits) < max_hits:
        current_origin = _make_f3(
            ox + (dx / total_distance) * traveled,
            oy + (dy / total_distance) * traveled,
            oz + (dz / total_distance) * traveled,
        )

        hit_info = None
        if hasattr(scene_query, 'raycast_closest'):
            try:
                hit_info = scene_query.raycast_closest(current_origin, direction, float(remaining), bothSides=both_sides)
            except TypeError:
                hit_info = scene_query.raycast_closest(current_origin, direction, float(remaining))
            except Exception:
                hit_info = None

        if isinstance(hit_info, dict) and hit_info.get('hit', False):
            collision_path = str(hit_info.get('collision', '') or '')
            rigid_body = str(hit_info.get('rigidBody', '') or '')
            if collision_path and ignored_prefixes and any(collision_path.startswith(prefix) for prefix in ignored_prefixes):
                traveled += float(epsilon)
                remaining -= float(epsilon)
                continue

            hit_distance = float(hit_info.get('distance', 0.0) or 0.0)
            if hit_distance <= float(epsilon):
                traveled += float(epsilon)
                remaining -= float(epsilon)
                continue

            hits.append(
                RayHit(
                    distance=traveled + hit_distance,
                    collision=collision_path,
                    rigid_body=rigid_body,
                    position=_f3_to_tuple(hit_info.get('position', (0.0, 0.0, 0.0))),
                    normal=_f3_to_tuple(hit_info.get('normal', (0.0, 0.0, 0.0))),
                    face_index=int(hit_info.get('faceIndex', -1)),
                )
            )
            step = hit_distance + float(epsilon)
            traveled += step
            remaining -= step
            continue

        fallback_hits = raycast_all_hits(
            scene_query,
            (
                ox + (dx / total_distance) * traveled,
                oy + (dy / total_distance) * traveled,
                oz + (dz / total_distance) * traveled,
            ),
            target_xyz,
            both_sides=both_sides,
            max_hits=max_hits,
            ignore_prefixes=ignore_prefixes,
        )
        if not fallback_hits:
            break

        closest_hit = fallback_hits[0]
        if float(closest_hit.distance) <= float(epsilon):
            traveled += float(epsilon)
            remaining -= float(epsilon)
            continue

        hits.append(
            RayHit(
                distance=traveled + float(closest_hit.distance),
                collision=closest_hit.collision,
                rigid_body=closest_hit.rigid_body,
                position=closest_hit.position,
                normal=closest_hit.normal,
                face_index=closest_hit.face_index,
            )
        )
        step = float(closest_hit.distance) + float(epsilon)
        traveled += step
        remaining -= step

    hits.sort(key=lambda hit: hit.distance)
    return hits


def thickness_from_hits(
    hits: list[RayHit],
    mu_by_path: dict[str, float],
    *,
    merge_epsilon: float = 1e-5,
) -> tuple[float, list[tuple[str, float, float, float]]]:
    """
    Convert ordered boundary hits into per-obstacle penetration depth.

    The ray is expected to start outside the obstacle volume. Distances are grouped by
    obstacle path, near-duplicate seam hits are merged, and entry/exit boundaries are
    paired with the even-odd rule. An unmatched trailing hit is intentionally ignored;
    the source-host self-attenuation term is handled separately in the forward model.
    """
    distances_by_obstacle: dict[str, list[float]] = {}
    mu_cache: dict[str, float] = {}

    for hit in hits:
        obstacle_path, mu = _resolve_obstacle_path(hit.collision, mu_by_path)
        if obstacle_path is None or mu is None:
            continue
        distances_by_obstacle.setdefault(obstacle_path, []).append(float(hit.distance))
        mu_cache[obstacle_path] = float(mu)

    mu_t_sum = 0.0
    terms: list[tuple[str, float, float, float]] = []

    for obstacle_path, distances in distances_by_obstacle.items():
        distances.sort()
        merged_distances = _dedupe_sorted_distances(distances, merge_epsilon)
        thickness = _paired_thickness(merged_distances)
        mu = mu_cache[obstacle_path]
        mu_t = mu * thickness
        mu_t_sum += mu_t

        if mu_t != 0.0:
            terms.append((obstacle_path, thickness, mu, mu_t))

    terms.sort(key=lambda item: item[3], reverse=True)
    return mu_t_sum, terms
