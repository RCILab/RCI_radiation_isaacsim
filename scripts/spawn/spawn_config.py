from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterator, Optional, Tuple, List

from runtime.workspace_config import resolve_selected_world, workspace_root, workspace_world_file


DEFAULT_SPAWN_Z: float = 0.15
DEFAULT_SPAWN_ROOT = workspace_root() / 'config'


# If no world is specified explicitly, use config/current_world_name.txt.
def resolve_spawn_world(world: str | None = None) -> str:
    return resolve_selected_world(world)


# Default spawn CSV path for the selected world.
def default_spawn_csv(world: str | None = None) -> Path:
    return workspace_world_file('spawn', 'jackal_spawns.csv', world_name=resolve_spawn_world(world))


# Resolve an override CSV path or fall back to the selected world's default CSV.
def resolve_spawn_csv(csv_path: str | Path | None = None, *, world: str | None = None) -> Path:
    path = Path(csv_path).expanduser() if csv_path else default_spawn_csv(world)
    if not path.is_absolute():
        path = (workspace_root() / path).resolve()
    else:
        path = path.resolve()
    return path


# Read x,y,yaw_deg rows from CSV and return them as numeric tuples.
def load_spawn_poses(
    csv_path: str | Path | None = None,
    *,
    world: str | None = None,
) -> List[Tuple[float, float, float]]:
    path = resolve_spawn_csv(csv_path, world=world)
    if not path.exists():
        raise FileNotFoundError(f'spawn csv not found: {path}')

    with path.open('r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])
        required = {'x', 'y', 'yaw_deg'}
        missing = sorted(required - fields)
        if missing:
            raise RuntimeError(f'spawn csv missing columns {missing}: {path}')

        poses: List[Tuple[float, float, float]] = []
        for row in reader:
            if not row:
                continue
            x = (row.get('x') or '').strip()
            y = (row.get('y') or '').strip()
            yaw = (row.get('yaw_deg') or '').strip()
            if not any((x, y, yaw)):
                continue
            poses.append((float(x), float(y), float(yaw)))

    if not poses:
        raise RuntimeError(f'spawn csv is empty: {path}')
    return poses


def _resolve_spawn_count(requested_num: Optional[int], poses: List[Tuple[float, float, float]]) -> int:
    if requested_num is None or requested_num <= 0:
        return len(poses)
    return requested_num


# Yield (x, y, z, yaw_deg) transforms for the requested robot count.
def iter_spawn_transforms(
    requested_num: Optional[int],
    *,
    csv_path: str | Path | None = None,
    world: str | None = None,
    spawn_z: float = DEFAULT_SPAWN_Z,
) -> Iterator[Tuple[float, float, float, float]]:
    poses = load_spawn_poses(csv_path, world=world)
    n = _resolve_spawn_count(requested_num, poses)
    last = poses[-1]

    for i in range(n):
        x, y, yaw = poses[i] if i < len(poses) else last
        yield (float(x), float(y), float(spawn_z), float(yaw))
