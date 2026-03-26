#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_jackal_scoped_assets.py

목표:
  - jackal_base.usd  -> jackal_base_scoped.usd
  - jackal_physics.usd -> jackal_physics_scoped.usd  (필요 시 /visuals 등의 루트 prim을 만들어 노출)
  - jackal_scoped.usda wrapper 생성

중요:
  - SimulationApp(Kit) 부팅은 main()에서 단 1회만.
  - make_* 함수 내부에서는 SimulationApp을 만들거나 닫지 않는다.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Optional, Iterable, Tuple


# Kit / pxr bootstrap (ONLY ONCE)
def _is_kit_running() -> bool:
    """이미 Kit 안에서 돌고 있는지(확실하진 않지만) 최대한 안전하게 판별."""
    try:
        import omni.kit.app  # type: ignore
        return omni.kit.app.get_app() is not None
    except Exception:
        return False


def _try_import_pxr() -> bool:
    try:
        import pxr  # noqa: F401
        return True
    except Exception:
        return False


def bootstrap_kit_once(headless: bool = True):
    """
    pxr가 바로 import 되면 Kit 부팅 없이 진행.
    pxr import 실패하면 SimulationApp으로 Kit 1회 부팅 후 진행.
    반환: app 또는 None
    """
    if _try_import_pxr():
        return None

    if _is_kit_running():
        # Kit 안에서 이미 돌고 있는데 pxr import가 실패했다면 환경이 꼬인 것.
        # 그래도 여기서 SimulationApp을 새로 띄우면 더 꼬일 수 있어서 예외.
        raise RuntimeError("Kit is running but pxr import failed. Environment seems inconsistent.")

    try:
        from isaacsim import SimulationApp  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "pxr import failed, and could not import isaacsim.SimulationApp.\n"
            "You need to run with Isaac Sim kit python, or ensure Isaac Sim python packages are available.\n"
            f"Original error: {e}"
        )

    app = SimulationApp({"headless": bool(headless)})
    # 부팅 후 pxr import 재시도
    if not _try_import_pxr():
        try:
            app.close()
        except Exception:
            pass
        raise RuntimeError("SimulationApp started, but pxr import still failed.")
    return app


def require_pxr():
    """bootstrap 이후에만 호출."""
    from pxr import Usd, Sdf, UsdGeom  # type: ignore
    return Usd, Sdf, UsdGeom


# Small utilities
def atomic_write_text(dst: Path, text: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=dst.name + ".", dir=str(dst.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, dst)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def safe_remove(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def ensure_overwrite_ok(path: Path, force: bool) -> None:
    if path.exists():
        if not force:
            raise FileExistsError(f"Output exists (use --force): {path}")
        safe_remove(path)


def relpath_for_usd(from_file: Path, target_file: Path) -> str:
    """USD 레이어에서 쓰기 좋은 상대 경로 문자열."""
    return os.path.relpath(str(target_file), start=str(from_file.parent)).replace("\\", "/")


# Core: base_scoped
def make_base_scoped(src_base: Path, dst_base: Path, *, force: bool = False) -> None:
    """
    base 파일은 prim 구조를 함부로 바꾸면 참조 경로가 깨질 수 있어서
    "대부분은 그대로 복사 + 내부에서 physics 파일명을 scoped로 치환" 정도만 수행.

    - jackal_physics.usd 를 jackal_physics_scoped.usd 로 문자열 치환
    """
    _, Sdf, _ = require_pxr()

    ensure_overwrite_ok(dst_base, force=force)

    layer = Sdf.Layer.FindOrOpen(str(src_base))
    if layer is None:
        raise FileNotFoundError(f"Could not open USD layer: {src_base}")

    text = layer.ExportToString()

    # 보수적으로 파일명만 치환 (경로 포함 형태도 같이 커버)
    text2 = re.sub(r"jackal_physics\.usd\b", "jackal_physics_scoped.usd", text)

    atomic_write_text(dst_base, text2)


# Core: physics_scoped
def _find_best_named_prim(stage, name: str, prefer_child: Optional[str] = None):
    """
    stage 내에서 prim.GetName()==name 인 후보들을 찾고,
    prefer_child가 있으면 그 자식 prim을 가진 후보를 우선.
    """
    candidates = []
    for prim in stage.Traverse():
        try:
            if prim.GetName() == name:
                candidates.append(prim)
        except Exception:
            continue

    if not candidates:
        return None

    if prefer_child:
        for p in candidates:
            try:
                if p.GetChild(prefer_child).IsValid():
                    return p
            except Exception:
                pass

    # 가장 얕은(경로 세그먼트 적은) prim을 우선
    def depth(p) -> int:
        return str(p.GetPath()).count("/")

    candidates.sort(key=depth)
    return candidates[0]


def make_physics_scoped(
    src_phys: Path,
    dst_phys: Path,
    *,
    base_scoped_name: str = "jackal_base_scoped.usd",
    force: bool = False,
) -> None:
    """
    physics 파일은 "참조가 기대하는 루트 prim(/visuals/...)"이 없어서 깨지는 경우가 많아서,
    아래 중 가능한 걸 수행:

    1) src_phys에 이미 /visuals 가 있으면: "복사 + base 파일명 scoped 치환"만
    2) /visuals 가 없으면: src_phys 내부에서 이름이 'visuals'인 prim을 찾아
       새 stage의 /visuals 에 그 prim subtree를 reference로 노출

    + jackal_base.usd -> base_scoped_name 로 문자열 치환
    """
    Usd, Sdf, UsdGeom = require_pxr()

    ensure_overwrite_ok(dst_phys, force=force)

    src_stage = Usd.Stage.Open(str(src_phys))
    if src_stage is None:
        raise FileNotFoundError(f"Could not open USD stage: {src_phys}")

    # 먼저 텍스트 레벨로 base 파일명만 scoped로 치환해둔 복사본을 만들지,
    # 아니면 새 stage를 만들지 결정.
    has_root_visuals = src_stage.GetPrimAtPath("/visuals").IsValid()

    if has_root_visuals:
        # "그대로 복사 + base 파일명 치환"
        src_layer = Sdf.Layer.FindOrOpen(str(src_phys))
        if src_layer is None:
            raise FileNotFoundError(f"Could not open USD layer: {src_phys}")

        text = src_layer.ExportToString()
        text2 = re.sub(r"jackal_base\.usd\b", base_scoped_name, text)
        atomic_write_text(dst_phys, text2)
        return

    # /visuals 가 없다면: 새 stage를 만들고, 적당한 visuals prim을 찾아 reference로 매핑
    visuals_prim = _find_best_named_prim(src_stage, "visuals", prefer_child="imu_link")
    if visuals_prim is None:
        # 그래도 못 찾으면 그냥 복사 + base 치환만 하고 끝냄(최소한 파일은 만들어짐)
        src_layer = Sdf.Layer.FindOrOpen(str(src_phys))
        if src_layer is None:
            raise FileNotFoundError(f"Could not open USD layer: {src_phys}")

        text = src_layer.ExportToString()
        text2 = re.sub(r"jackal_base\.usd\b", base_scoped_name, text)
        atomic_write_text(dst_phys, text2)
        return

    # 새 stage 작성
    out_stage = Usd.Stage.CreateNew(str(dst_phys))
    if out_stage is None:
        raise RuntimeError(f"Could not create new USD stage: {dst_phys}")

    # 메타데이터 일부 보존(가능한 범위)
    try:
        out_stage.SetMetadata("metersPerUnit", src_stage.GetMetadata("metersPerUnit"))
    except Exception:
        pass
    try:
        out_stage.SetMetadata("upAxis", src_stage.GetMetadata("upAxis"))
    except Exception:
        pass

    # /visuals 루트 prim 생성
    visuals_root = UsdGeom.Xform.Define(out_stage, "/visuals").GetPrim()

    # src_phys 의 visuals_prim subtree를 /visuals 로 reference
    ref_path = str(visuals_prim.GetPath())  # e.g. "/SomeScope/visuals"
    visuals_root.GetReferences().AddReference(
        assetPath=str(src_phys),
        primPath=Sdf.Path(ref_path),
    )

    # 혹시 같이 필요한 루트들이 있으면 추가 매핑(있을 때만)
    # 예: collisions/materials 등. (없으면 그냥 스킵)
    extra_names: Iterable[Tuple[str, Optional[str]]] = [
        ("collisions", None),
        ("collision", None),
        ("materials", None),
    ]
    used = {"visuals"}

    for name, prefer in extra_names:
        if name in used:
            continue
        p = _find_best_named_prim(src_stage, name, prefer_child=prefer)
        if p is None:
            continue
        used.add(name)
        root = UsdGeom.Xform.Define(out_stage, f"/{name}").GetPrim()
        root.GetReferences().AddReference(assetPath=str(src_phys), primPath=Sdf.Path(str(p.GetPath())))

    out_stage.GetRootLayer().Save()

    # 저장된 파일 텍스트를 다시 열어 base 파일명 치환까지 수행(보수적으로)
    out_layer = Sdf.Layer.FindOrOpen(str(dst_phys))
    if out_layer is None:
        raise RuntimeError(f"Created physics_scoped but could not reopen: {dst_phys}")

    text = out_layer.ExportToString()
    text2 = re.sub(r"jackal_base\.usd\b", base_scoped_name, text)
    atomic_write_text(dst_phys, text2)


# Core: wrapper
def write_wrapper(dst_wrapper: Path, *, base_scoped_rel: str, physics_scoped_rel: str, force: bool = False) -> None:
    """
    wrapper(usda)는 subLayers로 base_scoped + physics_scoped를 얹는 단순 구성.
    defaultPrim은 base_scoped에서 읽어오려고 시도(실패하면 생략).
    """
    Usd, _, _ = require_pxr()

    ensure_overwrite_ok(dst_wrapper, force=force)

    # base_scoped의 defaultPrim 이름 읽기(가능하면)
    default_prim_name: Optional[str] = None
    try:
        base_stage = Usd.Stage.Open(str(dst_wrapper.parent / base_scoped_rel))
        if base_stage:
            dp = base_stage.GetDefaultPrim()
            if dp and dp.IsValid():
                default_prim_name = dp.GetName()
    except Exception:
        default_prim_name = None

    # usda wrapper 작성
    header_lines = ["#usda 1.0"]
    meta_lines = ["("]
    if default_prim_name:
        meta_lines.append(f'    defaultPrim = "{default_prim_name}"')
    meta_lines.append("    subLayers = [")
    meta_lines.append(f"        @{base_scoped_rel}@,")
    meta_lines.append(f"        @{physics_scoped_rel}@,")
    meta_lines.append("    ]")
    meta_lines.append(")")
    content = "\n".join(header_lines + meta_lines) + "\n"

    atomic_write_text(dst_wrapper, content)


# CLI / main
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="overwrite outputs if exist")
    p.add_argument("--headless", action="store_true", default=True, help="start SimulationApp headless (default)")
    p.add_argument("--gui", action="store_true", help="start SimulationApp with window (overrides --headless)")

    # inputs (defaults: repo 기준 상대경로)
    p.add_argument(
        "--base",
        type=str,
        default="assets/jackal/jackal/configuration/jackal_base.usd",
        help="input base usd",
    )
    p.add_argument(
        "--phys",
        type=str,
        default="assets/jackal/jackal/configuration/jackal_physics.usd",
        help="input physics usd",
    )

    # outputs
    p.add_argument(
        "--out-base",
        type=str,
        default="assets/jackal/jackal/configuration/jackal_base_scoped.usd",
        help="output base_scoped usd",
    )
    p.add_argument(
        "--out-phys",
        type=str,
        default="assets/jackal/jackal/configuration/jackal_physics_scoped.usd",
        help="output physics_scoped usd",
    )
    p.add_argument(
        "--out-wrap",
        type=str,
        default="assets/jackal/jackal/jackal_scoped.usda",
        help="output wrapper usda",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    src_base = Path(args.base).resolve()
    src_phys = Path(args.phys).resolve()
    dst_base = Path(args.out_base).resolve()
    dst_phys = Path(args.out_phys).resolve()
    dst_wrap = Path(args.out_wrap).resolve()

    if not src_base.exists():
        raise FileNotFoundError(f"[in ] base not found: {src_base}")
    if not src_phys.exists():
        raise FileNotFoundError(f"[in ] phys not found: {src_phys}")

    print(f"[in ] {src_base}")
    print(f"[in ] {src_phys}")
    print(f"[out] {dst_base}")
    print(f"[out] {dst_phys}")
    print(f"[out] {dst_wrap}")


    # SimulationApp ONLY ONCE HERE

    headless = True
    if args.gui:
        headless = False
    elif args.headless:
        headless = True

    app = bootstrap_kit_once(headless=headless)

    try:
        # 1) base_scoped
        make_base_scoped(src_base, dst_base, force=args.force)
        print(f"[ok ] base_scoped(export): {dst_base} ({dst_base.stat().st_size} bytes)")

        # 2) physics_scoped
        make_physics_scoped(
            src_phys,
            dst_phys,
            base_scoped_name=Path(dst_base).name,
            force=args.force,
        )
        if dst_phys.exists():
            print(f"[ok ] physics_scoped(export): {dst_phys} ({dst_phys.stat().st_size} bytes)")
        else:
            print(f"[WARN] physics_scoped was not created: {dst_phys}")

        # 3) wrapper
        base_rel = relpath_for_usd(dst_wrap, dst_base)
        phys_rel = relpath_for_usd(dst_wrap, dst_phys)
        write_wrapper(dst_wrap, base_scoped_rel=base_rel, physics_scoped_rel=phys_rel, force=args.force)
        print(f"[ok ] wrapper(write): {dst_wrap} ({dst_wrap.stat().st_size} bytes)")

        return 0

    finally:
        # main()에서만 close
        if app is not None:
            try:
                app.close()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise
