from __future__ import annotations

from typing import Any

from pxr import Usd, UsdGeom, UsdPhysics


def open_stage(usd_path: str, app, warmup_frames: int = 60):
    import omni.usd

    omni.usd.get_context().open_stage(str(usd_path))
    for _ in range(int(warmup_frames)):
        app.update()


def get_stage():
    import omni.usd

    return omni.usd.get_context().get_stage()


def get_custom(prim, key: str, default=None):
    cd = prim.GetCustomData() or {}
    return cd.get(key, default)


def set_custom(prim, **kv):
    cd = dict(prim.GetCustomData() or {})
    cd.update(kv)
    prim.SetCustomData(cd)


def scan_prims_by_custom_flag(stage, root_path: str, key: str, value: Any):
    root = stage.GetPrimAtPath(root_path)
    if not root or not root.IsValid():
        return []

    out = []
    for prim in Usd.PrimRange(root):
        if not prim.IsValid():
            continue
        cd = prim.GetCustomData() or {}
        if cd.get(key, None) == value:
            out.append(prim)
    return out


def ensure_probe(stage, path: str, radius: float, height: float):
    prim = stage.GetPrimAtPath(path)
    if prim and prim.IsValid():
        return prim

    cyl = UsdGeom.Cylinder.Define(stage, path)
    cyl.CreateRadiusAttr(float(radius))
    cyl.CreateHeightAttr(float(height))
    return cyl.GetPrim()


def set_xform_translate(stage, prim, pos_xyz):
    xf = UsdGeom.Xformable(prim)
    ops = xf.GetOrderedXformOps()
    t_op = None
    for op in ops:
        if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
            t_op = op
            break
    if t_op is None:
        t_op = xf.AddTranslateOp()
    t_op.Set((float(pos_xyz[0]), float(pos_xyz[1]), float(pos_xyz[2])))


def get_world_translation(prim):
    x = UsdGeom.Xformable(prim)
    if not x:
        return (0.0, 0.0, 0.0)
    m = x.ComputeLocalToWorldTransform(0)
    p = m.ExtractTranslation()
    return (float(p[0]), float(p[1]), float(p[2]))


def infer_material_from_name(name: str, mu_map: dict, alias: dict | None = None) -> str | None:
    alias = alias or {}
    toks = name.split("_")
    for t in reversed(toks):
        if t.isdigit():
            continue
        t = alias.get(t, t)
        if t in mu_map:
            return t
    return None


def ensure_physics_scene(stage, scene_path="/World/physicsScene"):
    from pxr import Sdf

    prim = stage.GetPrimAtPath(scene_path)
    if prim and prim.IsValid() and prim.GetTypeName() == "PhysicsScene":
        return scene_path

    UsdPhysics.Scene.Define(stage, Sdf.Path(scene_path))
    return scene_path


def ensure_obstacle_mesh_colliders(stage, obstacle_root_paths, approximation="mesh", verbose=False):
    try:
        from pxr import PhysxSchema
    except Exception:
        PhysxSchema = None

    mesh_count = 0
    applied = 0

    def apply_to_mesh(mesh_prim):
        nonlocal applied
        if not mesh_prim.HasAPI(UsdPhysics.CollisionAPI):
            UsdPhysics.CollisionAPI.Apply(mesh_prim)
            applied += 1

        if PhysxSchema is not None:
            try:
                col = PhysxSchema.PhysxCollisionAPI.Apply(mesh_prim)

                attr = col.GetCollisionEnabledAttr()
                if not attr:
                    attr = col.CreateCollisionEnabledAttr()
                attr.Set(True)

                appr = col.GetApproximationAttr()
                if not appr:
                    appr = col.CreateApproximationAttr()
                appr.Set(str(approximation))
            except Exception:
                pass

    for root_path in obstacle_root_paths:
        root = stage.GetPrimAtPath(root_path)
        if not root or not root.IsValid():
            continue

        for prim in Usd.PrimRange(root):
            if not prim.IsValid():
                continue
            if prim.IsA(UsdGeom.Mesh):
                mesh_count += 1
                apply_to_mesh(prim)

    if verbose:
        print(f"[physics] meshes_under_obstacles={mesh_count} colliders_applied={applied} approx={approximation}")
    return mesh_count, applied


def warmup_physics(app, stage, steps=30, play=True):
    try:
        import omni.physx

        iface = omni.physx.get_physx_interface()
        if hasattr(iface, "force_load_physics_from_usd"):
            iface.force_load_physics_from_usd()
    except Exception:
        pass

    if play:
        try:
            import omni.timeline

            omni.timeline.get_timeline_interface().play()
        except Exception:
            pass

    for _ in range(int(steps)):
        app.update()
