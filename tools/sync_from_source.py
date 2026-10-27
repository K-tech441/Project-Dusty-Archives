# -*- coding: utf-8 -*-
"""把「库/插件源」里的可运行代码同步到本发布仓，并做**机械漂移检查**。

背景：本仓库的 `code/` 是源工程（D:\\munkres-formal 与 dsh-bundles）的可运行拷贝。
拷贝靠人手同步 ⟹ 会漏（2026-10-27 实测：`契约补充.md` 漏了 `kl view` 与图重算说明）。
本脚本把「哪些文件是逐字节拷贝」写成规则，跑一遍就知道有没有漂移。

用法（在发布仓根目录）：

```powershell
python tools/sync_from_source.py           # 只检查（有漂移 exit 1）
python tools/sync_from_source.py --write   # 把源文件覆盖到本仓（同步）
python tools/sync_from_source.py --list    # 打印规则表
```

路径来源（换机器只改环境变量，不改代码）：

```
KL_SOURCE_REPO  库工程根（默认 D:\\munkres-formal）
KL_BUNDLES      DSH 插件源目录（默认 D:\\deepseek工作区\\dsh-bundles）
```

规则两类：
- `exact`  整棵树/整文件逐字节拷贝（源里多出的文件也算漂移：说明新文件没同步）
- `subset` 只保证【本仓已有的文件】与源一致（源里未纳入发布仓的文件忽略）
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DOC = os.path.dirname(HERE)  # 发布仓根
SRC = os.environ.get("KL_SOURCE_REPO") or r"D:\munkres-formal"
BUNDLES = os.environ.get("KL_BUNDLES") or os.path.join(
    os.path.dirname(DOC), "dsh-bundles")

SKIP_DIRS = {"__pycache__", "node_modules", ".git", ".lake"}

# (mode, 源相对/绝对路径, 目标相对路径)；以 "/" 结尾表示目录树
RULES: list[tuple[str, str, str]] = [
    ("exact", os.path.join(SRC, "tools", "kl"), "code/engine/kl"),
    ("exact", os.path.join(SRC, "tools", "lean-probes"), "code/engine/lean-probes"),
    ("exact", os.path.join(SRC, "tools", "lean-ilean-prune.py"),
     "code/engine/lean-ilean-prune.py"),
    ("exact", os.path.join(SRC, "knowledge", "book-profile.json"),
     "code/examples/munkres-2e/book-profile.json"),
    ("exact", os.path.join(SRC, "knowledge", "books", "munkres-2e.json"),
     "code/examples/munkres-2e/books/munkres-2e.json"),
    ("exact", os.path.join(SRC, "docs", "契约补充.md"),
     "code/examples/munkres-2e/契约补充.md"),
]
for _plug in sorted(os.listdir(BUNDLES)) if os.path.isdir(BUNDLES) else []:
    _src = os.path.join(BUNDLES, _plug)
    # 只同步「插件目录」：跳过 .git / node_modules 等，且必须带 package.json
    if _plug.startswith(".") or not os.path.isdir(_src):
        continue
    if not os.path.isfile(os.path.join(_src, "package.json")):
        continue
    RULES.append(("subset", _src, "code/plugins/" + _plug))


def _norm_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read().replace(b"\r\n", b"\n")


def _sha(path: str) -> str:
    return hashlib.sha256(_norm_bytes(path)).hexdigest()


def _tree(root: str) -> dict[str, str]:
    """相对路径 -> 绝对路径（跳过缓存/依赖目录）。"""
    out: dict[str, str] = {}
    if os.path.isfile(root):
        out[""] = root
        return out
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for f in sorted(files):
            p = os.path.join(base, f)
            out[os.path.relpath(p, root).replace("\\", "/")] = p
    return out


def check(write: bool = False) -> int:
    drift: list[str] = []
    total = 0
    for mode, src, rel_dst in RULES:
        dst = os.path.join(DOC, rel_dst.replace("/", os.sep))
        if not os.path.exists(src):
            drift.append(f"[缺源] {src}（检查 KL_SOURCE_REPO / KL_BUNDLES）")
            continue
        # ---- 单文件规则
        if os.path.isfile(src):
            total += 1
            if not os.path.isfile(dst):
                drift.append(f"[未同步] {rel_dst}")
                if write:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
            elif _sha(src) != _sha(dst):
                drift.append(f"[漂移]   {rel_dst}")
                if write:
                    shutil.copy2(src, dst)
            continue
        # ---- 目录规则
        src_files = _tree(src)
        dst_files = _tree(dst) if os.path.exists(dst) else {}
        for rel, sp in sorted(src_files.items()):
            dp = os.path.join(dst, rel.replace("/", os.sep))
            total += 1
            if not os.path.isfile(dp):
                if mode == "exact":
                    drift.append(f"[未同步] {rel_dst}/{rel}")
                    if write:
                        os.makedirs(os.path.dirname(dp), exist_ok=True)
                        shutil.copy2(sp, dp)
                continue
            if _sha(sp) != _sha(dp):
                drift.append(f"[漂移]   {rel_dst}/{rel}")
                if write:
                    shutil.copy2(sp, dp)
        if mode == "exact":
            for rel in sorted(dst_files.keys()):
                if not os.path.isfile(os.path.join(src, rel.replace("/", os.sep))):
                    drift.append(f"[多出]   {rel_dst}/{rel}（源里没有，需人工判断）")
    print(f"检查 {len(RULES)} 条规则 / {total} 个源文件：", end="")
    if not drift:
        print("全部一致 ✓")
        return 0
    print(f"{len(drift)} 处不一致")
    for d in drift:
        print("  ", d)
    if write:
        print("已按 --write 覆盖；请 git diff 复核后提交")
        return 0
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="源工程 → 发布仓的机械同步/漂移检查")
    ap.add_argument("--write", action="store_true", help="把源文件覆盖到本仓")
    ap.add_argument("--list", action="store_true", help="只打印规则表")
    args = ap.parse_args()
    if args.list:
        for mode, src, rel in RULES:
            print(f"{mode:6s} {src}  ->  {rel}")
        return 0
    return check(write=args.write)


if __name__ == "__main__":
    sys.exit(main())
