from __future__ import annotations


def _short_name(path_or_name: str) -> str:
    value = str(path_or_name or "")
    if "/" in value:
        value = value.rsplit("/", 1)[-1]
    for prefix in ("radiation_obstacle_", "radiation_source_", "radiation_sensor_"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    return value


# Scan the stage and summarize whether radiation tags were attached as expected.
def scan_attachment_summary(stage, *, root: str = "/World") -> dict:
    from radiation_simulator.authoring.usd_helpers import get_custom, scan_prims_by_custom_flag

    source_prims = scan_prims_by_custom_flag(stage, root, "radiation:is_source", True)
    obstacle_prims = scan_prims_by_custom_flag(stage, root, "radiation:is_obstacle", True)

    resolved_sources = []
    skipped_sources = []
    for prim in source_prims:
        enabled = bool(get_custom(prim, "radiation:enabled", True))
        intensity = float(get_custom(prim, "radiation:intensity", 0.0) or 0.0)
        entry = {
            "prim": prim,
            "path": prim.GetPath().pathString,
            "name": _short_name(prim.GetPath().pathString),
            "enabled": enabled,
            "intensity": intensity,
        }
        if enabled and intensity > 0.0:
            resolved_sources.append(entry)
        else:
            skipped_sources.append(entry)

    resolved_obstacles = []
    missing_mu = []
    for prim in obstacle_prims:
        mu = get_custom(prim, "radiation:mu", None)
        entry = {
            "prim": prim,
            "path": prim.GetPath().pathString,
            "name": _short_name(prim.GetPath().pathString),
            "mu": None if mu is None else float(mu),
        }
        if mu is None:
            missing_mu.append(entry)
        else:
            resolved_obstacles.append(entry)

    return {
        "root": str(root),
        "source_prims": source_prims,
        "obstacle_prims": obstacle_prims,
        "sources_tagged": len(source_prims),
        "sources_resolved": len(resolved_sources),
        "sources_skipped": skipped_sources,
        "obstacles_tagged": len(obstacle_prims),
        "obstacles_resolved": len(resolved_obstacles),
        "obstacles_missing_mu": missing_mu,
    }


# Print a short startup/debug summary that both simulation runners can share.
def print_attachment_summary(summary: dict) -> None:
    print(f"[scan] sources={summary['sources_tagged']} obstacles={summary['obstacles_tagged']}")
    print(f"[sources] configured={summary['sources_tagged']} resolved={summary['sources_resolved']}")
    print(f"[obstacles] resolved_mu={summary['obstacles_resolved']}")

    skipped_sources = summary.get("sources_skipped", []) or []
    if skipped_sources:
        skipped_names = ", ".join(item["name"] for item in skipped_sources[:3])
        print(f"[sources] skipped={len(skipped_sources)} sample={skipped_names}")

    missing_mu = summary.get("obstacles_missing_mu", []) or []
    if missing_mu:
        missing_names = ", ".join(item["name"] for item in missing_mu[:3])
        print(f"[obstacles] missing_mu={len(missing_mu)} sample={missing_names}")
