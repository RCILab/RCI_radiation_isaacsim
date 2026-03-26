from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SceneSource:
    prim_path: str
    name: str
    position_units: tuple[float, float, float]
    intensity: float
    host_obstacle: str | None = None


@dataclass(frozen=True)
class SceneSensor:
    name: str
    prim_path: str
    prim: Any


@dataclass(frozen=True)
class RuntimeSettings:
    cfg_root: str
    world: str
    root: str
    air_mu: float
    no_obstacles: bool
    apply_source_self_attenuation: bool
