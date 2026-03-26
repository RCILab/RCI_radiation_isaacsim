from __future__ import annotations

from radiation_simulator.authoring.usd_helpers import get_custom, set_custom


def apply_source_component(
    prim,
    *,
    intensity: float,
    radius: float = 0.1,
    enabled: bool = True,
    host_obstacle: str | None = None,
):
    payload = {
        "radiation:is_source": bool(enabled),
        "radiation:intensity": float(intensity),
        "radiation:radius": float(radius),
        "radiation:enabled": bool(enabled),
    }
    if host_obstacle:
        payload["radiation:host_obstacle"] = str(host_obstacle)
    set_custom(prim, **payload)


def is_source(prim) -> bool:
    return bool(get_custom(prim, "radiation:is_source", False))
