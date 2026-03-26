from __future__ import annotations

from radiation_simulator.authoring.usd_helpers import get_custom, set_custom


def apply_obstacle_component(prim, *, material: str, mu: float, enabled: bool = True):
    set_custom(
        prim,
        **{
            "radiation:is_obstacle": bool(enabled),
            "radiation:material": str(material),
            "radiation:mu": float(mu),
        },
    )


def is_obstacle(prim) -> bool:
    return bool(get_custom(prim, "radiation:is_obstacle", False))
