from __future__ import annotations

import tomllib
from pathlib import Path

from .usd_helpers import infer_material_from_name, set_custom


def _load_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def get_extension_root() -> Path:
    return Path(__file__).resolve().parents[3]


def get_default_config_root() -> Path:
    return (get_extension_root() / "config").resolve()


def resolve_config_root(cfg_root: str | Path | None = None) -> Path:
    if cfg_root in (None, ""):
        return get_default_config_root().resolve()

    path = Path(cfg_root).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    else:
        path = path.resolve()
    return path


def _extract_sources_list(cfg: dict) -> list[dict]:
    root = cfg.get("sources", cfg.get("source", {}))
    if isinstance(root, list):
        return root
    if isinstance(root, dict):
        for k in ("sources", "list", "items", "manual"):
            v = root.get(k)
            if isinstance(v, list):
                return v
        if "path" in root:
            return [root]
    return []


def _extract_sources_points(cfg: dict) -> tuple[list[dict], dict]:
    root = cfg.get("sources", cfg.get("source", {}))
    if not isinstance(root, dict):
        return [], {}
    pts = root.get("points", [])
    if isinstance(pts, list):
        return pts, root
    return [], root


def apply_radiation_customdata(stage, cfg_root: str | Path | None, world: str) -> dict:
    cfg_root_path = resolve_config_root(cfg_root)
    base_dir = cfg_root_path / "base"
    world_dir = cfg_root_path / "worlds" / world

    materials_cfg = _load_toml(base_dir / "materials.toml")
    obstacles_cfg = _load_toml(world_dir / "obstacles.toml")
    sources_cfg = _load_toml(world_dir / "sources.toml")

    mu_map = (materials_cfg.get("materials", {}) or {}).get("mu", {}) or {}
    alias = (materials_cfg.get("materials", {}) or {}).get("alias", {}) or {}

    auto = (obstacles_cfg.get("obstacles", {}) or {}).get("auto", {}) or {}
    root_path = auto.get("root", "/World")
    prefix = auto.get("name_prefix", "")
    use_suffix = bool(auto.get("material_from_name_suffix", False))
    overrides = (obstacles_cfg.get("obstacles", {}) or {}).get("override", []) or []

    from pxr import Gf, Usd, UsdGeom

    root = stage.GetPrimAtPath(root_path)

    obstacles_applied = 0
    if root and root.IsValid():
        for prim in Usd.PrimRange(root):
            if not prim.IsValid():
                continue
            name = prim.GetName()
            if prefix and (not name.startswith(prefix)):
                continue

            mat = None
            if use_suffix and "_" in name:
                cand = name.rsplit("_", 1)[1]
                cand = alias.get(cand, cand)
                if cand in mu_map:
                    mat = cand

            if mat is None:
                mat = infer_material_from_name(name, mu_map, alias)

            mu = mu_map.get(mat, None)
            if (mat is None) or (mu is None):
                continue

            set_custom(
                prim,
                **{
                    "radiation:is_obstacle": True,
                    "radiation:material": str(mat),
                    "radiation:mu": float(mu),
                },
            )
            obstacles_applied += 1

    for override in overrides:
        path = override.get("path")
        mat = override.get("material")
        if not path or not mat:
            continue
        prim = stage.GetPrimAtPath(path)
        if not prim or not prim.IsValid():
            continue
        mat = alias.get(mat, mat)
        mu = mu_map.get(mat, None)
        if mu is None:
            continue
        custom_data = {
            "radiation:is_obstacle": True,
            "radiation:material": str(mat),
            "radiation:mu": float(mu),
        }
        thickness_mode = override.get("thickness_mode")
        if thickness_mode not in (None, ""):
            custom_data["radiation:thickness_mode"] = str(thickness_mode)
        set_custom(prim, **custom_data)

    points_list, src_root = _extract_sources_points(sources_cfg)

    default_intensity = float((src_root or {}).get("default_intensity", 0.0) or 0.0)
    default_radius = float((src_root or {}).get("default_radius", 0.1) or 0.1)

    create_point_prims = bool((src_root or {}).get("create_point_prims", True))
    point_parent = str((src_root or {}).get("point_prim_parent", "/World/RadiationSources"))
    marker_radius = float((src_root or {}).get("point_marker_radius", 0.05) or 0.05)
    marker_visible = bool((src_root or {}).get("point_marker_visible", False))

    def _sanitize_name(name: str) -> str:
        name = (name or "").strip().replace("/", "_").replace(" ", "_")
        return name or "radiation_source"

    def _ensure_xform(path: str):
        prim = stage.GetPrimAtPath(path)
        if prim and prim.IsValid():
            return prim
        return UsdGeom.Xform.Define(stage, path).GetPrim()

    def _set_translate(xform_prim, pos_xyz):
        xf = UsdGeom.Xformable(xform_prim)
        ops = xf.GetOrderedXformOps()
        t_op = None
        for op in ops:
            if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
                t_op = op
                break
        if t_op is None:
            t_op = xf.AddTranslateOp()
        t_op.Set(Gf.Vec3d(float(pos_xyz[0]), float(pos_xyz[1]), float(pos_xyz[2])))

    def _set_visibility(prim, visible: bool):
        imageable = UsdGeom.Imageable(prim)
        if visible:
            imageable.MakeVisible()
        else:
            imageable.MakeInvisible()

    sources_applied = 0
    if points_list and create_point_prims:
        if point_parent and point_parent != "/":
            _ensure_xform(point_parent)

        for idx, source in enumerate(points_list):
            name = _sanitize_name(str(source.get("name", f"radiation_source_{idx}")))
            pos = source.get("pos", None)
            if not (isinstance(pos, (list, tuple)) and len(pos) == 3):
                continue

            intensity = float(source.get("intensity", default_intensity) or 0.0)
            radius = float(source.get("radius", default_radius) or default_radius)
            enabled = bool(source.get("enabled", True))

            host_obstacle = source.get("host_obstacle", None)
            if host_obstacle is not None:
                host_obstacle = str(host_obstacle)

            src_path = f"{point_parent}/{name}"
            src_prim = _ensure_xform(src_path)
            _set_translate(src_prim, pos)

            geom_path = f"{src_path}/Geom"
            sphere = UsdGeom.Sphere.Define(stage, geom_path)
            sphere.CreateRadiusAttr(float(marker_radius))
            _set_visibility(src_prim, bool(marker_visible))

            custom_data = {
                "radiation:is_source": True,
                "radiation:intensity": float(intensity),
                "radiation:radius": float(radius),
                "radiation:enabled": bool(enabled),
            }
            if host_obstacle:
                custom_data["radiation:host_obstacle"] = host_obstacle

            set_custom(src_prim, **custom_data)
            sources_applied += 1

    for source in _extract_sources_list(sources_cfg):
        path = source.get("path")
        if not path:
            continue
        prim = stage.GetPrimAtPath(path)
        if not prim or not prim.IsValid():
            continue

        intensity = float(source.get("intensity", 0.0))
        radius = float(source.get("radius", 0.1))
        enabled = bool(source.get("enabled", True))

        set_custom(
            prim,
            **{
                "radiation:is_source": True,
                "radiation:intensity": float(intensity),
                "radiation:radius": float(radius),
                "radiation:enabled": bool(enabled),
            },
        )
        sources_applied += 1

    return {
        "obstacles_applied": obstacles_applied,
        "sources_applied": sources_applied,
        "cfg_root": str(cfg_root_path),
    }
