# scripts/drive/diff_drive.py
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


def acquire_dynamic_control():
    from omni.isaac.dynamic_control import _dynamic_control
    return _dynamic_control.acquire_dynamic_control_interface()


def _get_articulation(dc, base_link_path: str):
    # base_link로 실패하면 parent로 재시도
    try:
        return dc.get_articulation(base_link_path)
    except Exception:
        parent = "/".join(base_link_path.split("/")[:-1])
        return dc.get_articulation(parent)


def _get_dof_name(dc, dof) -> str:
    try:
        return dc.get_dof_name(dof)
    except Exception:
        try:
            return dc.get_dof_info(dof).name
        except Exception:
            return ""


def _get_articulation_dofs(dc, art):
    dofs = []
    try:
        n = dc.get_articulation_dof_count(art)
        for i in range(n):
            dofs.append(dc.get_articulation_dof(art, i))
    except Exception:
        pass
    return dofs


def _pick_wheel_dofs(dc, art):
    dofs = _get_articulation_dofs(dc, art)
    named = [(d, _get_dof_name(dc, d)) for d in dofs]

    wheels = [(d, n) for (d, n) in named if ("wheel" in n.lower())]
    left = [(d, n) for (d, n) in wheels if ("left" in n.lower())]
    right = [(d, n) for (d, n) in wheels if ("right" in n.lower())]
    return left, right, wheels


def diff_to_wheel_omega(v_mps: float, w_rps: float, wheel_radius: float, wheel_base: float) -> Tuple[float, float]:
    # v,w -> (omega_L, omega_R)
    vL = v_mps - 0.5 * wheel_base * w_rps
    vR = v_mps + 0.5 * wheel_base * w_rps
    return (vL / wheel_radius, vR / wheel_radius)


@dataclass
class WheelController:
    base_link: str
    left_dofs: List[Tuple[int, str]]
    right_dofs: List[Tuple[int, str]]

    @classmethod
    def from_base_link(cls, dc, base_link_path: str) -> "WheelController":
        art = _get_articulation(dc, base_link_path)
        try:
            dc.wake_up_articulation(art)
        except Exception:
            pass

        left, right, wheels = _pick_wheel_dofs(dc, art)

        if not left or not right:
            # wheels는 있는데 left/right 분류가 깨지면 제어가 애매해짐 → 바로 알리기
            names = [n for _, n in wheels]
            raise RuntimeError(
                f"Wheel DOFs not resolved (left/right) for base_link={base_link_path}. "
                f"Found wheels={names}"
            )

        return cls(base_link=base_link_path, left_dofs=left, right_dofs=right)

    def command_omega(self, dc, omega_left: float, omega_right: float):
        for d, _ in self.left_dofs:
            try:
                dc.set_dof_velocity_target(d, float(omega_left))
            except Exception:
                pass
        for d, _ in self.right_dofs:
            try:
                dc.set_dof_velocity_target(d, float(omega_right))
            except Exception:
                pass

    def command_vw(self, dc, v: float, w: float, wheel_radius: float, wheel_base: float):
        oL, oR = diff_to_wheel_omega(v, w, wheel_radius, wheel_base)
        self.command_omega(dc, oL, oR)
