from __future__ import annotations

from radiation_simulator.authoring.usd_helpers import get_custom, set_custom


def apply_sensor_component(
    prim,
    *,
    name: str,
    enabled: bool = True,
    offset: tuple[float, float, float] | None = None,
    rate_hz: float | None = None,
):
    payload = {
        "radiation:is_sensor": bool(enabled),
        "radiation:sensor_name": str(name),
    }
    if offset is not None:
        payload["radiation:offset"] = [float(v) for v in offset]
    if rate_hz is not None:
        payload["radiation:rate_hz"] = float(rate_hz)
    set_custom(prim, **payload)


def is_sensor(prim) -> bool:
    return bool(get_custom(prim, "radiation:is_sensor", False))
