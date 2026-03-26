# scripts/drive/pose.py
from __future__ import annotations

import math
from typing import Tuple


def _get_stage():
    import omni.usd
    return omni.usd.get_context().get_stage()


def get_world_xyz_yaw(prim_path: str) -> Tuple[float, float, float, float]:
    """
    prim의 world (x, y, z) + yaw(rad)
    roll/pitch는 무시하고 yaw만 계산.
    """
    from pxr import UsdGeom, Usd

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        return (float("nan"), float("nan"), float("nan"), 0.0)

    xf = UsdGeom.Xformable(prim)
    m = xf.ComputeLocalToWorldTransform(Usd.TimeCode.Default())

    p = m.ExtractTranslation()
    rot = m.ExtractRotationMatrix()

    # x축 방향 벡터로 yaw 계산
    x_axis = rot.GetRow(0)  # (r00, r01, r02)
    yaw = math.atan2(float(x_axis[1]), float(x_axis[0]))

    return (float(p[0]), float(p[1]), float(p[2]), float(yaw))
