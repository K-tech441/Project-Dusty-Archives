#!/usr/bin/env python3
"""Prune / restore mathlib `.ilean` files outside our import closure.

Why: the Lean 4.35 language-server watchdog unconditionally loads every `.ilean`
found on the `LEAN_PATH` (Lean/Server/Watchdog.lean: `startLoadingReferences`).
Mathlib contributes ~8.6k `.ilean` / ~277 MB => ~830 MB of server RSS. Only the
modules in the import closure of `MunkresLean/Base.lean` are ever needed by our
project; the rest can be moved aside (same volume, reversible) so the LSP does not
load them. Building the project is unaffected: `lake build` only touches modules in
that closure (verified: moving an out-of-closure `.ilean` leaves `lake build` a no-op).

Keep set = Base closure ∪ tool roots. Tool roots are mathlib modules that our own
tooling compiles into the build dir (the ③b duplicate-decl probe imports
`Mathlib.Tactic.DuplicateDecls`); they are extracted mechanically from the probe
source in `tools/kl/checks.py`, so adding a probe import never desyncs this tool.

Usage
    python tools/lean-ilean-prune.py status
    python tools/lean-ilean-prune.py prune
    python tools/lean-ilean-prune.py restore

Environment
    KL_LEAN_ROOT       repo root (default: parent of this script's directory)
    KL_MATHLIB_DIR     mathlib package dir (default: <root>/.lake/packages/mathlib)
    KL_ILEAN_ARCHIVE   archive dir (default: D:/lean/mathlib-ilean-archive)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("KL_LEAN_ROOT") or os.path.dirname(HERE)
MATHLIB = os.environ.get("KL_MATHLIB_DIR") or os.path.join(ROOT, ".lake", "packages", "mathlib")
BUILD = os.path.join(MATHLIB, ".lake", "build", "lib", "lean")
ARCHIVE = os.environ.get("KL_ILEAN_ARCHIVE") or r"D:\lean\mathlib-ilean-archive"
MANIFEST = os.path.join(ARCHIVE, "manifest.json")
BASE_LEAN = os.path.join(ROOT, "MunkresLean", "Base.lean")
IMPORT_RE = re.compile(r"^\s*(?:public\s+)?import\s+(Mathlib\.[A-Za-z0-9_.']+)", re.MULTILINE)
# 工具根（2026-10-25 修复）：③b 判重的探针会被真实编译，其 import 的 mathlib 模块
# （如 `Mathlib.Tactic.DuplicateDecls`）会在构建目录里产生 .ilean。它不属于内容层依赖，
# 但**必须**算进「构建目录应保留」的集合：否则 doctor 的「ilean 剪枝」永远报多一个，
# 而 prune 把它移走后、下次判重再生成（来回漂）。只取根模块本身——它的依赖 olean 已在，
# 缺 .ilean 不影响编译（.ilean 只是 LSP 的引用索引）。
TOOL_SRC = os.path.join(ROOT, "tools", "kl", "checks.py")
TOOL_IMPORT_RE = re.compile(r"(?<![A-Za-z0-9_.'])import\s+(Mathlib\.[A-Za-z0-9_.']+)")


def module_of(rel: str) -> str:
    return rel.replace(os.sep, ".").removesuffix(".ilean")


def path_of(mod: str) -> str:
    return mod.replace(".", os.sep) + ".ilean"


def iter_ileans(base: str):
    for dirpath, _dirs, files in os.walk(base):
        for f in files:
            if f.endswith(".ilean"):
                yield os.path.relpath(os.path.join(dirpath, f), base)


def build_index() -> dict[str, str]:
    """module -> absolute ilean path, from BUILD and ARCHIVE."""
    index: dict[str, str] = {}
    for base in (ARCHIVE, BUILD):
        if not os.path.isdir(base):
            continue
        for rel in iter_ileans(base):
            index[module_of(rel)] = os.path.join(base, rel)
    return index


def direct_imports(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return []
    out = []
    for it in data.get("directImports") or []:
        if isinstance(it, list) and it:
            out.append(it[0])
        elif isinstance(it, str):
            out.append(it)
    return out


def seeds() -> list[str]:
    text = open(BASE_LEAN, encoding="utf-8").read()
    return sorted(set(IMPORT_RE.findall(text)))


def closure(index: dict[str, str]) -> set[str]:
    seen: set[str] = set()
    stack = [s for s in seeds() if s in index]
    while stack:
        m = stack.pop()
        if m in seen or m not in index:
            continue
        seen.add(m)
        for im in direct_imports(index[m]):
            if im not in seen:
                stack.append(im)
    return seen


def tool_roots() -> list[str]:
    """工具侧编译进构建目录的 mathlib 根模块（从 checks.py 的探针源码机械提取）。"""
    try:
        text = open(TOOL_SRC, encoding="utf-8").read()
    except OSError:
        return []
    return sorted(set(TOOL_IMPORT_RE.findall(text)))


def keep_set(index: dict[str, str], current: set[str] | None = None) -> set[str]:
    """构建目录里必须保留 `.ilean` 的模块 = Base 闭包 ∪ 在场的工具根。

    工具根只「若在场则保留」：它们不是内容层依赖（缺 .ilean 不影响编译），
    但一旦被工具编译出来就不该被删 —— 删了下次判重会再生成，来回漂。
    """
    keep = closure(index)
    roots = set(tool_roots())
    if current is not None:
        roots &= current
    return keep | roots


def load_manifest() -> dict:
    if os.path.isfile(MANIFEST):
        try:
            return json.load(open(MANIFEST, encoding="utf-8"))
        except Exception:
            pass
    return {"pruned": [], "closure": [], "at": ""}


def save_manifest(doc: dict) -> None:
    os.makedirs(ARCHIVE, exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)


def status() -> int:
    current = {module_of(r) for r in iter_ileans(BUILD)}
    archived = {module_of(r) for r in iter_ileans(ARCHIVE)}
    index = build_index()
    base_cl = closure(index)
    tools = set(tool_roots())
    cl = keep_set(index, current)
    kept = len(current & cl)
    missing = sorted(base_cl - current)
    extra = sorted(current - cl)
    print(f"archive: {ARCHIVE}")
    print(f"mathlib .ilean in build dir : {len(current)}")
    print(f"mathlib .ilean in archive   : {len(archived)}")
    print(f"Base closure               : {len(base_cl)}")
    print(f"tool roots                 : {len(tools)} {sorted(tools)}")
    print(f"keep set (closure ∪ tools) : {len(cl)}")
    print(f"closure kept in build dir   : {kept}  (missing: {len(missing)})")
    if missing:
        print(f"  missing: {missing[:10]}")
    if extra:
        print(f"  extra  : {extra[:10]}")
    pruned = bool(archived)
    print(f"state: {'PRUNED' if pruned else 'FULL'}")
    return 0 if not missing and not extra else 1


def prune() -> int:
    index = build_index()
    current = [r for r in iter_ileans(BUILD)]
    cl = keep_set(index, {module_of(r) for r in current})
    moved = 0
    for rel in current:
        if module_of(rel) in cl:
            continue
        src = os.path.join(BUILD, rel)
        dst = os.path.join(ARCHIVE, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(dst):
            os.remove(dst)
        shutil.move(src, dst)
        moved += 1
    doc = load_manifest()
    doc["pruned"] = sorted(set(doc.get("pruned", [])) | {r for r in current if module_of(r) not in cl})
    doc["closure"] = sorted(cl)
    doc["at"] = __import__("datetime").datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    save_manifest(doc)
    print(f"pruned {moved} .ilean files -> {ARCHIVE}")
    print(f"closure kept: {len(cl)}")
    return 0


def restore() -> int:
    moved = 0
    for rel in list(iter_ileans(ARCHIVE)):
        src = os.path.join(ARCHIVE, rel)
        dst = os.path.join(BUILD, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        moved += 1
    if os.path.isfile(MANIFEST):
        os.remove(MANIFEST)
    # clean empty dirs under archive
    for dirpath, dirs, files in os.walk(ARCHIVE, topdown=False):
        if not dirs and not files:
            try:
                os.rmdir(dirpath)
            except OSError:
                pass
    print(f"restored {moved} .ilean files")
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "status"
    if cmd == "status":
        return status()
    if cmd == "prune":
        return prune()
    if cmd == "restore":
        return restore()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
