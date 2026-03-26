from __future__ import annotations

from pathlib import Path

from radiation_simulator.runtime.manager import RadiationManager


# Scripts call this thin facade so they do not depend on manager internals.
_MANAGER = RadiationManager()


def get_manager() -> RadiationManager:
    return _MANAGER


# Prepare sources, obstacles, and sensors for the current stage.
def configure(
    stage,
    *,
    cfg_root: str | Path | None,
    world: str,
    root: str = "/World",
    air_mu: float = 0.001,
    no_obstacles: bool = False,
    apply_source_self_attenuation: bool = False,
    robots_override: list[dict] | None = None,
) -> dict:
    return _MANAGER.configure(
        stage,
        cfg_root=cfg_root,
        world=world,
        root=root,
        air_mu=air_mu,
        no_obstacles=no_obstacles,
        apply_source_self_attenuation=apply_source_self_attenuation,
        robots_override=robots_override,
    )


# Clear cached state when the stage or scenario resets.
def clear() -> None:
    _MANAGER.clear()


# Compute fresh readings if the runtime period has elapsed.
def step(*, force: bool = False) -> bool:
    return _MANAGER.step(force=force)


# Read one sensor by display name or prim path.
def get_reading(sensor_key: str):
    return _MANAGER.get_sensor_reading(sensor_key)


# Return the latest cached readings for every sensor.
def get_all_readings():
    return _MANAGER.get_all_sensor_readings()


# This increments whenever a new batch of readings is stored.
def get_sequence() -> int:
    return _MANAGER.get_update_sequence()


# Re-scan stage custom data so live edits take effect without restarting.
def refresh(*, refresh_sensors: bool = False, force_step: bool = True) -> dict:
    return _MANAGER.refresh_from_stage(refresh_sensors=refresh_sensors, force_step=force_step)


# Backward-compatible aliases for older scripts.
configure_runtime = configure
clear_runtime = clear
step_runtime = step
get_sensor_reading = get_reading
get_all_sensor_readings = get_all_readings
get_update_sequence = get_sequence
refresh_runtime = refresh
