from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable


@dataclass(frozen=True)
class RadiationSource:
    prim_path: str
    pos: tuple[float, float, float]
    intensity: float
    radius: float = 0.1
    mu_air: float = 0.0
    enabled: bool = True
    name: str = ""
    host_obstacle: str | None = None


def _default_source_name(source: RadiationSource) -> str:
    if str(getattr(source, 'name', '') or '').strip():
        return str(source.name)
    if getattr(source, 'prim_path', None):
        return str(source.prim_path).split('/')[-1]
    return 'source'


def _unpack_obstacle_solver(obstacle_solver):
    scene_query = None
    raycast_fn = None
    thickness_fn = None
    extra_ignores: list[str] = []
    meters_per_unit = 1.0
    bbox_thickness_fn: Callable[[str, tuple[float, float, float], tuple[float, float, float]], float] | None = None
    mu_by_path: dict[str, float] = {}

    if obstacle_solver is None:
        return scene_query, mu_by_path, raycast_fn, thickness_fn, extra_ignores, meters_per_unit, bbox_thickness_fn

    if isinstance(obstacle_solver, dict):
        scene_query = obstacle_solver.get('scene_query')
        raycast_fn = obstacle_solver.get('raycast_fn')
        thickness_fn = obstacle_solver.get('thickness_fn')
        extra_ignores = list(obstacle_solver.get('extra_ignores') or [])
        meters_per_unit = float(obstacle_solver.get('meters_per_unit', 1.0) or 1.0)
        bbox_thickness_fn = obstacle_solver.get('bbox_thickness_fn')
        for path, mu in obstacle_solver.get('obstacles', []) or []:
            mu_by_path[str(path)] = float(mu)
        return scene_query, mu_by_path, raycast_fn, thickness_fn, extra_ignores, meters_per_unit, bbox_thickness_fn

    if len(obstacle_solver) == 4:
        scene_query, obstacles_list, raycast_fn, thickness_fn = obstacle_solver
    elif len(obstacle_solver) == 5:
        scene_query, obstacles_list, raycast_fn, thickness_fn, extra_ignores = obstacle_solver
    elif len(obstacle_solver) == 6:
        scene_query, obstacles_list, raycast_fn, thickness_fn, extra_ignores, meters_per_unit = obstacle_solver
    else:
        scene_query, obstacles_list, raycast_fn, thickness_fn, extra_ignores, meters_per_unit, bbox_thickness_fn = obstacle_solver

    for path, mu in obstacles_list:
        mu_by_path[str(path)] = float(mu)

    return scene_query, mu_by_path, raycast_fn, thickness_fn, list(extra_ignores or []), float(meters_per_unit), bbox_thickness_fn


def _resolve_mu_path(collision_path: str, mu_by_path: dict[str, float]) -> str | None:
    from pxr import Sdf

    if not collision_path:
        return None
    path = Sdf.Path(collision_path)
    while path and path != Sdf.Path.absoluteRootPath:
        path_str = path.pathString
        if path_str in mu_by_path:
            return path_str
        path = path.GetParentPath()
    return None


def _guess_host_obstacle_from_source_path(source_prim_path: str) -> str | None:
    if not source_prim_path:
        return None
    token = source_prim_path.split('/')[-1]
    if token.startswith('radiation_source_'):
        return '/World/' + token.replace('radiation_source_', 'radiation_obstacle_', 1)
    return None


def _compute_source_details(
    index: int,
    source: RadiationSource,
    probe_pos: tuple[float, float, float],
    *,
    mu_air: float,
    apply_source_self_attenuation: bool,
    scene_query,
    mu_by_path: dict[str, float],
    raycast_fn,
    thickness_fn,
    extra_ignores: list[str],
    meters_per_unit: float,
    bbox_thickness_fn: Callable[[str, tuple[float, float, float], tuple[float, float, float]], float] | None,
) -> dict[str, Any] | None:
    if (not source.enabled) or float(source.intensity) <= 0.0:
        return None

    sx, sy, sz = source.pos
    px, py, pz = probe_pos
    dx, dy, dz = (px - sx, py - sy, pz - sz)

    distance_units = math.sqrt(dx * dx + dy * dy + dz * dz)
    if distance_units < 1e-9:
        return None

    distance_m = float(distance_units) * float(meters_per_unit)
    distance_eff_m = max(distance_m, 1.0)
    distance_att = 1.0 / (distance_eff_m * distance_eff_m)
    intensity = float(source.intensity)
    base = intensity * distance_att

    mu_t_sum = 0.0
    terms: list[tuple[str, float, float, float]] = []
    obstacle_thickness_m = 0.0
    host_added = False
    hits = []

    if scene_query is not None and raycast_fn is not None and thickness_fn is not None and mu_by_path:
        hits = raycast_fn(
            scene_query,
            source.pos,
            probe_pos,
            both_sides=True,
            ignore_prefixes=extra_ignores or [],
        )
        mu_t_sum, terms = thickness_fn(hits, mu_by_path)

        for _, thickness_m, _, _ in terms:
            obstacle_thickness_m += float(thickness_m)

        if apply_source_self_attenuation:
            host = source.host_obstacle or _guess_host_obstacle_from_source_path(source.prim_path)
            if host and host in mu_by_path:
                covered_paths = {path for (path, _, _, _) in terms}
                if host not in covered_paths:
                    exit_distance_m = None
                    for hit in hits:
                        distance_hit_m = float(getattr(hit, 'distance', 0.0) or 0.0) * float(meters_per_unit)
                        if distance_hit_m <= 1e-6:
                            continue
                        resolved_path = _resolve_mu_path(getattr(hit, 'collision', '') or '', mu_by_path)
                        if resolved_path == host:
                            exit_distance_m = distance_hit_m
                            break

                    if exit_distance_m is not None:
                        mu = float(mu_by_path[host])
                        mu_t = mu * float(exit_distance_m)
                        mu_t_sum += mu_t
                        obstacle_thickness_m += float(exit_distance_m)
                        terms.append((host, float(exit_distance_m), mu, float(mu_t)))
                        host_added = True

        if bbox_thickness_fn is not None:
            covered_paths = {path for (path, _, _, _) in terms}
            for obstacle_path, mu in mu_by_path.items():
                if obstacle_path in covered_paths:
                    continue
                thickness_m = float(bbox_thickness_fn(obstacle_path, source.pos, probe_pos) or 0.0)
                if thickness_m <= 1e-6:
                    continue
                mu_t = float(mu) * thickness_m
                mu_t_sum += mu_t
                obstacle_thickness_m += thickness_m
                terms.append((obstacle_path, thickness_m, float(mu), mu_t))

        obs_att = math.exp(-float(mu_t_sum))
    else:
        obs_att = 1.0

    air_path_m = max(0.0, distance_m - obstacle_thickness_m)
    air_mu_eff = float(mu_air) if float(mu_air) > 0.0 else float(getattr(source, 'mu_air', 0.0) or 0.0)
    air_att = math.exp(-air_mu_eff * air_path_m) if air_mu_eff > 0.0 else 1.0

    att_total = air_att * obs_att
    final = base * att_total
    terms.sort(key=lambda item: item[3], reverse=True)

    return {
        'idx': int(index),
        'name': _default_source_name(source),
        'dist_m': float(distance_m),
        'dist_eff_m': float(distance_eff_m),
        'distance_att': float(distance_att),
        'intensity': float(intensity),
        'base': float(base),
        'air_mu': float(air_mu_eff),
        'air_path_m': float(air_path_m),
        'air_att': float(air_att),
        'obs_att': float(obs_att),
        'mu_t_sum': float(mu_t_sum),
        'att_total': float(att_total),
        'final': float(final),
        'hit_count': len(hits),
        'host_added': bool(host_added),
        'obstacles': [
            {
                'path': str(obstacle_path),
                'thickness_m': float(thickness_m),
                'mu': float(mu),
                'mu_t': float(mu_t),
            }
            for obstacle_path, thickness_m, mu, mu_t in terms
        ],
    }


def compute_sensor_reading(
    probe_pos: tuple[float, float, float],
    sources: list[RadiationSource],
    *,
    mu_air: float = 0.0,
    apply_source_self_attenuation: bool = False,
    obstacle_solver: Any | None = None,
) -> dict[str, Any]:
    from radiation_simulator.core.sensor_noise import apply_sensor_noise

    scene_query, mu_by_path, raycast_fn, thickness_fn, extra_ignores, meters_per_unit, bbox_thickness_fn = _unpack_obstacle_solver(obstacle_solver)

    per_source: list[dict[str, Any]] = []
    raw_total = 0.0
    for index, source in enumerate(sources):
        details = _compute_source_details(
            index,
            source,
            probe_pos,
            mu_air=float(mu_air),
            apply_source_self_attenuation=bool(apply_source_self_attenuation),
            scene_query=scene_query,
            mu_by_path=mu_by_path,
            raycast_fn=raycast_fn,
            thickness_fn=thickness_fn,
            extra_ignores=extra_ignores,
            meters_per_unit=float(meters_per_unit),
            bbox_thickness_fn=bbox_thickness_fn,
        )
        if details is None:
            continue
        raw_total += float(details['final'])
        per_source.append(details)

    total = apply_sensor_noise(
        raw_total,
        context={
            'probe_pos': tuple(float(v) for v in probe_pos),
            'source_count': len(sources),
            'mu_air': float(mu_air),
            'apply_source_self_attenuation': bool(apply_source_self_attenuation),
        },
    )
    return {
        'total': float(total),
        'raw_total': float(raw_total),
        'per_source': per_source,
    }


def compute_total_intensity(
    probe_pos: tuple[float, float, float],
    sources: list[RadiationSource],
    *,
    mu_air: float = 0.0,
    apply_source_self_attenuation: bool = False,
    obstacle_solver: Any | None = None,
    debug_source_idx: int | None = None,
):
    """
    Simplified forward model currently used by the workspace.

    - distance term: intensity / max(distance_m, 1.0)^2
    - obstacle term: exp(-sum(mu_i * thickness_i))
    - air term: exp(-mu_air * air_path_m)

    Mesh penetration depth is estimated from one source->sensor ray by collecting
    both-sided boundary hits and pairing entry/exit distances per obstacle.
    If the ray starts inside the source host obstacle, that initial exit segment is
    added separately through apply_source_self_attenuation.
    """
    result = compute_sensor_reading(
        probe_pos,
        sources,
        mu_air=mu_air,
        apply_source_self_attenuation=apply_source_self_attenuation,
        obstacle_solver=obstacle_solver,
    )

    debug: dict[str, Any] = {}
    if debug_source_idx is not None:
        for details in result['per_source']:
            if int(details['idx']) != int(debug_source_idx):
                continue
            debug = {
                'dist_m': float(details['dist_m']),
                'dist_eff_m': float(details['dist_eff_m']),
                'distance_att': float(details['distance_att']),
                'base': float(details['base']),
                'air_mu': float(details['air_mu']),
                'air_path_m': float(details['air_path_m']),
                'air_att': float(details['air_att']),
                'obstacle_thickness_m': float(sum(float(item['thickness_m']) for item in details['obstacles'])),
                'mu_t_sum': float(details['mu_t_sum']),
                'obs_att': float(details['obs_att']),
                'hit_count': int(details['hit_count']),
                'hits_fwd': int(details['hit_count']),
                'hits_rev': 0,
                'host_added': bool(details['host_added']),
                'terms_top': [
                    (
                        str(item['path']),
                        float(item['thickness_m']),
                        float(item['mu']),
                        float(item['mu_t']),
                    )
                    for item in details['obstacles'][:5]
                ],
            }
            break

    return float(result['total']), debug
