from __future__ import annotations

from pathlib import Path


# Shared workspace-level helpers so scripts do not hardcode world names or config paths.
def workspace_root() -> Path:
    return Path(__file__).resolve().parents[2]


# Resolve a path relative to the workspace root unless it is already absolute.
def resolve_workspace_path(path: str | Path) -> Path:
    value = Path(path).expanduser()
    if not value.is_absolute():
        value = (workspace_root() / value).resolve()
    else:
        value = value.resolve()
    return value


# Keep the default world name in a data file instead of scattering it through code.
def current_world_name_path() -> Path:
    return workspace_root() / 'config' / 'current_world_name.txt'


# Load the current world name from config/current_world_name.txt.
def load_current_world_name() -> str:
    path = current_world_name_path()
    if not path.exists():
        raise FileNotFoundError(f'current world file not found: {path}')

    value = path.read_text(encoding='utf-8').strip()
    if not value:
        raise RuntimeError(f'current world file is empty: {path}')
    return value


# Use the explicit world if provided, otherwise fall back to the workspace default.
def resolve_selected_world(world_name: str | None = None) -> str:
    value = str(world_name or load_current_world_name()).strip()
    if not value:
        raise RuntimeError('selected world name is empty')
    return value


# Workspace-level per-world config lives under config/<world_name>/...
def workspace_config_root() -> Path:
    return workspace_root() / 'config'


# Resolve the selected workspace world directory.
def workspace_world_dir(world_name: str | None = None) -> Path:
    return workspace_config_root() / resolve_selected_world(world_name)


# Resolve a file under config/<world_name>/...
def workspace_world_file(*parts: str, world_name: str | None = None) -> Path:
    return workspace_world_dir(world_name).joinpath(*parts)


# Radiation config root may be relative in scripts, so normalize it once here.
def resolve_cfg_root(cfg_root: str | Path) -> Path:
    return resolve_workspace_path(cfg_root)


def _load_toml(path: Path) -> dict:
    import tomllib

    return tomllib.loads(path.read_text(encoding='utf-8'))


# Read the selected world's world.toml file.
def load_world_config(cfg_root: str | Path, world_name: str | None = None) -> dict:
    cfg_root_path = resolve_cfg_root(cfg_root)
    selected_world = resolve_selected_world(world_name)
    config_path = cfg_root_path / 'worlds' / selected_world / 'world.toml'
    if not config_path.exists():
        raise FileNotFoundError(f'world config not found: {config_path}')

    return _load_toml(config_path)


# Read worlds/<world>/sensors.toml if present.
def load_world_sensors_config(cfg_root: str | Path, world_name: str | None = None) -> dict:
    cfg_root_path = resolve_cfg_root(cfg_root)
    selected_world = resolve_selected_world(world_name)
    sensors_path = cfg_root_path / 'worlds' / selected_world / 'sensors.toml'
    if not sensors_path.exists():
        raise FileNotFoundError(f'sensors config not found: {sensors_path}')
    return _load_toml(sensors_path)


# Monitor color thresholds are configured per-world inside worlds/<world>/sensors.toml.
def load_monitor_threshold(
    cfg_root: str | Path = 'extensions/radiation.simulator/config',
    world_name: str | None = None,
    *,
    default: float = 100.0,
) -> float:
    try:
        data = load_world_sensors_config(cfg_root, world_name)
    except Exception:
        return float(default)

    monitor_cfg = data.get('monitor', {}) or {}
    value = monitor_cfg.get('threshold', default)
    try:
        return float(value)
    except Exception:
        return float(default)


# World USD assets live under assets/world by default.
def world_assets_root() -> Path:
    return workspace_root() / 'assets' / 'world'


# Resolve the USD path from worlds/<world>/world.toml.
# Absolute paths are respected, while relative values are interpreted
# relative to assets/world first so world.toml can simply store a filename.
def resolve_world_usd(cfg_root: str | Path, world_name: str | None = None) -> Path:
    data = load_world_config(cfg_root, world_name=world_name)
    world_cfg = data.get('world', {}) or {}
    usd = str(world_cfg.get('usd', '')).strip()
    if not usd:
        raise RuntimeError('world.toml is missing [world].usd')

    value = Path(usd).expanduser()
    if value.is_absolute():
        return value.resolve()

    candidates = [
        (world_assets_root() / value).resolve(),
        (workspace_root() / value).resolve(),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    return candidates[0]
