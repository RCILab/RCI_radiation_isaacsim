from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ObstacleContribution:
    name: str
    thickness_m: float
    mu: float
    att: float

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "thickness_m": float(self.thickness_m),
            "mu": float(self.mu),
            "att": float(self.att),
        }


@dataclass(frozen=True)
class SourceContribution:
    idx: int
    name: str
    dist_m: float
    intensity: float
    base: float
    att_total: float
    final: float
    obstacles: tuple[ObstacleContribution, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "idx": int(self.idx),
            "name": self.name,
            "dist_m": float(self.dist_m),
            "intensity": float(self.intensity),
            "base": float(self.base),
            "att_total": float(self.att_total),
            "final": float(self.final),
            "obstacles": [item.to_dict() for item in self.obstacles],
        }


@dataclass(frozen=True)
class SensorReading:
    t: float
    sensor: str
    prim_path: str
    pos_m: tuple[float, float, float]
    total: float
    per_source: tuple[SourceContribution, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        payload = {
            "t": float(self.t),
            "sensor": self.sensor,
            "prim_path": self.prim_path,
            "pos_m": [float(v) for v in self.pos_m],
            "total": float(self.total),
            "per_source": [item.to_dict() for item in self.per_source],
        }
        payload["sources"] = payload["per_source"]
        return payload
