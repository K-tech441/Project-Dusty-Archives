# -*- coding: utf-8 -*-
"""kl 判据与检查（唯一实现）。

## 判据清单 / 意图 / 数据源 / 「不抓什么」：见 `docs/工程基准.md` §4（唯一事实源）

本文件只实现，不定义语义。8 个子判定（编号是历史遗留，按名字读）：

```
① build · ② sorry · ② axioms · ③a 提及禁止清单 · ③a′ 陈述层基底范围
③b 判重 · ③c 引文可溯源 · ④ module 卫生
```

## 实现侧不变量（改代码时必须守住）

- ③a 读 `.ilean` 的 references（解析后的常量全名 + 定义模块），不做源码字符串匹配：
  禁止清单里的名字（`IsOpen` / `closure` …）我们自己也用（自造的），字符串匹配分不清
  「我们的」和「外部的」。判定 = 短名 ∈ 禁止清单 且 定义模块不在本库 ⟹ 命中。
- ③b 的判重探针只 import `<lib>.Base` + 本节模块 ⟹ 判定环境 = Base 的 import 闭包 + 本节；
  这就是「不对 mathlib 内容层判重」的实现方式（是机制，不是约定）。
- ③c 两侧（md 与 quote）走同一个 `_norm_prose`；事实源是转录 md，不是 PDF 排版源。
- 判不了必须进 problems，或在返回值里显式 `skipped` 留痕；不要把「没跑」当「通过」。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

from kl import config
from kl.model import LeanPointer

STANDARD_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}

# ---------------------------------------------------------------- 路径（本库自包含；外部资源可选）

# tools/kl/checks.py → 上两级 = 库根
_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = config.REPO

# Lean 工程：默认就是库根（lakefile.toml 在库根）。可用 KL_LEAN_ROOT 指到别处。
DEFAULT_LEAN_ROOT = config.LEAN_ROOT
# 探针产物目录（不入库）；旧工程在 knowledge/schema/_lean_probe，这里统一放到 .probe/
PROBE_DIR = config.PROBE_DIR


def ilean_dirs() -> list[str]:
    """`.ilean` 的搜索根：本工程 · mathlib 包 · Lean 核心库。

    可用 `KL_ILEAN_DIRS`（用 os.pathsep 分隔）整体覆盖。
    """
    env = os.environ.get("KL_ILEAN_DIRS")
    if env:
        return [p for p in env.split(os.pathsep) if p]
    lean = DEFAULT_LEAN_ROOT
    cand = [
        os.path.join(lean, ".lake", "build", "lib", "lean"),
        os.path.join(lean, ".lake", "packages", "mathlib", ".lake", "build", "lib", "lean"),
        # Lean 核心库的 .ilean 在 toolchain 的 lib/lean 下（Init / Std 的名字靠它索引）
        os.environ.get("KL_TOOLCHAIN_LIB", ""),
    ]
    tc = os.environ.get("KL_LEAN_TOOLCHAIN", "leanprover--lean4---v4.35.0")
    cand.append(os.path.join(os.path.expanduser("~"), ".elan", "toolchains", tc, "lib", "lean"))
    cand.append(os.path.join(r"D:\lean\elan\toolchains", tc, "lib", "lean"))
    return [d for d in cand if d and os.path.isdir(d)]


# ---------------------------------------------------------------- 书（外部资源，可选）

# 本库不含书：扫描件 / 页码索引 / 转录 md 全是【外部资源】，用环境变量指过去。
#   KL_BOOK_PDF    英文原书 PDF（用于 kl_book 的英文页定位 + kl_figure 的图解码）
#   KL_BOOK_INDEX  中译本页码索引 book/index.json（section → 印刷页 / PDF 页）
#   KL_BOOK_MD     英文转录目录（p####.md，每页一份；用于定位 §n 起始页）
# 三者缺一不影响判据：只会让 kl_book / kl_figure 返回「缺外部资源」。
BOOK_PDF = os.environ.get("KL_BOOK_PDF", "")
BOOK_INDEX = os.environ.get("KL_BOOK_INDEX", "")
BOOK_MD = os.environ.get("KL_BOOK_MD", "")

# 英文 PDF 与印刷页的偏移（实例书已核；来源见 book config / 页码索引）
# 页码映射已迁到 bookindex（knowledge/books/<id>/index.json）；这里不再保留偏移常量。


# ---------------------------------------------------------------- 源码级

# Lean 4 的注释形式：/- ... -/（可嵌套）、-- 到行尾
_BLOCK_COMMENT = re.compile(r"/-.*?-/", re.S)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_SORRY = re.compile(r"\bsorry\b")
_DECL = re.compile(
    r"^\s*(?:@\[[^\]]*\]\s*)*(?:(?:public|private|protected|noncomputable|unsafe|partial)\s+)*"
    r"(theorem|lemma|def|instance|abbrev|opaque|class|structure|inductive)"
    r"\s+([A-Za-z_][A-Za-z0-9_'.]*)",
    re.M,
)
_NS_OPEN = re.compile(r"^namespace\s+([A-Za-z_][A-Za-z0-9_'.]*)")
_SECTION_OPEN = re.compile(r"^section(?:\s+[A-Za-z_][A-Za-z0-9_']*)?\s*$")
_SCOPE_END = re.compile(r"^end(?:\s+[A-Za-z_][A-Za-z0-9_']*)?\s*$")


def strip_comments(src: str) -> str:
    """去掉 Lean 注释，但保持行号（替换成等量换行）。"""

    def blank(m: re.Match[str]) -> str:
        return "\n" * m.group(0).count("\n")

    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub(blank, src))


def count_sorries(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    code = strip_comments(raw)
    raw_lines = raw.splitlines()
    hits = []
    for i, ln in enumerate(code.splitlines(), start=1):
        if _SORRY.search(ln):
            hits.append({"line": i,
                         "text": raw_lines[i - 1].strip() if i - 1 < len(raw_lines) else ""})
    return {"file": path, "total": len(hits), "hits": hits[:10]}


def list_declarations(path: str) -> list[tuple[str, str]]:
    """(kind, 全限定名)。跟踪 namespace / section / end 栈。"""
    with open(path, encoding="utf-8") as f:
        code = strip_comments(f.read())
    out: list[tuple[str, str]] = []
    ns: list[str] = []
    marks: list[str] = []
    for line in code.splitlines():
        s = line.strip()
        m = _NS_OPEN.match(s)
        if m:
            ns.append(m.group(1))
            marks.append("ns")
            continue
        if _SECTION_OPEN.match(s):
            marks.append("sec")
            continue
        if _SCOPE_END.match(s):
            if marks and marks.pop() == "ns" and ns:
                ns.pop()
            continue
        d = _DECL.match(line)
        if d:
            out.append((d.group(1), ".".join(ns + [d.group(2)]) if ns else d.group(2)))
    return out


# ---------------------------------------------------------------- 调度级

@dataclass
class BuildResult:
    ok: bool
    exit_code: int
    seconds: float
    log: str

    @property
    def tail(self) -> str:
        """只留人要看的那几行：滤掉 LEAN_PATH / trace 这种一次几十 KB 的噪声。"""
        keep = []
        for x in self.log.splitlines():
            s = x.strip()
            if not s:
                continue
            if "LEAN_PATH=" in s or s.startswith("trace:") or s.startswith("Some required targets"):
                continue
            keep.append(s)
        return "\n".join(keep[-12:])[:1800]


def build(project_root: str, target: str | None = None, timeout: int = 1800) -> BuildResult:
    cmd = ["lake", "build"] + ([target] if target else [])
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return BuildResult(p.returncode == 0, p.returncode, time.time() - t0,
                           (p.stdout or "") + (p.stderr or ""))
    except subprocess.TimeoutExpired as e:
        return BuildResult(False, -1, time.time() - t0, f"timeout after {timeout}s\n{e}")
    except FileNotFoundError:
        return BuildResult(False, -2, time.time() - t0,
                           "lake 未找到：确认 elan/lake 在 PATH 里")


_AXIOM_PROBE = """module

public import {imports}

/-! 自动生成：公理检查探针。由 kl.checks 写入，跑完即删。 -/

{checks}
"""


def check_axioms(project_root: str, file_rel: str, names: list[str],
                 timeout: int = 900) -> dict[str, Any]:
    """写一个临时模块跑 #print axioms，解析输出。"""
    if not names:
        return {"ok": True, "checked": 0, "unknown": [], "bad": {}, "deps": {}}
    mod = file_rel.replace("\\", "/").removesuffix(".lean").replace("/", ".")
    probe_rel = os.path.join(os.path.dirname(file_rel), "KlAxiomProbe.lean")
    probe_abs = os.path.join(project_root, probe_rel)
    probe_mod = probe_rel.replace("\\", "/").removesuffix(".lean").replace("/", ".")
    body = _AXIOM_PROBE.format(
        imports=mod,
        checks="\n".join(f"#print axioms {n}" for n in names))
    os.makedirs(os.path.dirname(probe_abs), exist_ok=True)
    with open(probe_abs, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    try:
        res = build(project_root, probe_mod, timeout=timeout)
    finally:
        try:
            os.remove(probe_abs)
        except OSError:
            pass

    pat = re.compile(r"'([^']+)' depends on axioms: \[([^\]]*)\]")
    pat_none = re.compile(r"'([^']+)' does not depend on any axioms")
    parsed: dict[str, list[str]] = {}
    for m in pat.finditer(res.log):
        parsed[m.group(1)] = [x.strip() for x in m.group(2).split(",") if x.strip()]
    for m in pat_none.finditer(res.log):
        parsed.setdefault(m.group(1), [])

    deps: dict[str, list[str]] = {}
    unknown: list[str] = []
    for n in names:
        if n in parsed:
            deps[n] = parsed[n]
        else:
            unknown.append(n)   # ★ 不做短名兜底：短名撞了会静默把别人的公理算进来
    bad = {n: ax for n, ax in deps.items()
           if any(a not in STANDARD_AXIOMS for a in ax)}
    return {
        "ok": bool(deps) and not bad and not unknown,
        "checked": len(deps),
        "unknown": unknown,
        "bad": bad,
        "deps": deps,
        "note": "" if deps else "一条也没解析出公理依赖（判不了）",
    }


# ---------------------------------------------------------------- ③a 提及

def ilean_path(module: str) -> str | None:
    rel = module.replace(".", os.sep) + ".ilean"
    for d in ilean_dirs():
        p = os.path.join(d, rel)
        if os.path.isfile(p):
            return p
    return None


def _ref_name(key: str) -> tuple[str, str]:
    """references 的 key 是 compress 过的 JSON：{"c":{"m":模块,"n":名字}}"""
    inner = json.loads(key)
    for tag, (mk, nk) in (("c", ("m", "n")), ("f", ("m", "i"))):
        if tag in inner and isinstance(inner[tag], dict):
            d = inner[tag]
            return d.get(mk, "?"), d.get(nk, "?")
    raise ValueError(f"未知的 RefIdent tag：{key!r}")


def references_of(module: str) -> dict[str, dict[str, Any]]:
    """模块 → {常量名: {module, usages}}。只含人显式写下的引用。"""
    p = ilean_path(module)
    if p is None:
        raise FileNotFoundError(f"找不到 .ilean：{module}")
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    out: dict[str, dict[str, Any]] = {}
    for key, val in (d.get("references") or {}).items():
        defmod, name = _ref_name(key)
        usages = [u for u in (val.get("usages") or []) if len(u) == 5]
        out[name] = {"module": defmod, "usages": len(usages)}
    return out


def forbidden_hits(modules: list[str], forbidden: list[str],
                   own_prefix: str = config.LIB) -> list[dict[str, Any]]:
    """③a：我们的模块里，提及了禁止清单中的 mathlib 常量。"""
    bad = set(forbidden)
    hits: list[dict[str, Any]] = []
    for mod in modules:
        try:
            refs = references_of(mod)
        except FileNotFoundError:
            hits.append({"module": mod, "error": "找不到 .ilean（先 build 一次）"})
            continue
        for name, info in refs.items():
            short = name.rsplit(".", 1)[-1]
            if short in bad and not info["module"].startswith(own_prefix):
                hits.append({"module": mod, "name": name,
                             "defined_in": info["module"],
                             "usages": info["usages"]})
    return hits


# ---------------------------------------------------------------- ③b 判重

_DUP_PROBE = """import Mathlib.Tactic.DuplicateDecls
{imports}

/-! 自动生成：判重探针。由 kl.checks 写入，跑完即删。

★ 必须做成【独立模块】再 import：`lintDuplicateDeclarations` 只遍历导入的常量
  （`Environment.constants.map₁`），当前模块新写的声明在 `map₂`，工具看不见。
-/

open Lean Mathlib.Tactic.DuplicateDecls

-- 判重需要遍历整个导入环境；心跳上限提到无限（编译器 linter 要求注释说明）。
set_option maxHeartbeats 0 in
run_meta do
  let t0 ← IO.monoMsNow
  let msg ← lintDuplicateDeclarations .{target}
  let t1 ← IO.monoMsNow
  logInfo m!"##ELAPSED_MS {{t1 - t0}}"
  logInfo msg
"""

_DUP_TOTAL = re.compile(r"Number of duplicates:\s*(\d+)")
_DUP_ELAPSED = re.compile(r"##ELAPSED_MS\s*(\d+)")


def dup(project_root: str, imports: list[str], target: str = "theorems",
        marker: str = config.NAMESPACE, timeout: int = 1200) -> dict[str, Any]:
    """跑一次官方判重，挑出提到 `marker` 的重复组。

    ★ 范围（新口径）：imports 只给基底 `<lib>.Base` + 我们自己的模块
      ⟹ 判的是「基底 + 自库内部」，不是 mathlib 内容层。
    ★ 代价：全量 mathlib 环境约 4 分钟、峰值约 8 GB，必须独占跑。
    """
    if not imports:
        return {"ran": False, "ok": False, "error": "没有给 imports（判不了）"}
    try:
        _DUP_PROBE.format(imports="", target="theorems")
    except (KeyError, IndexError, ValueError) as e:
        return {"ran": False, "ok": False,
                "error": f"DUP_PROBE 模板格式化失败（{e}）；Lean 的 {{…}} 要写成 {{{{…}}}}"}
    probe_rel = config.LIB + "/KlDupProbe.lean"
    probe_abs = os.path.join(project_root, probe_rel.replace("/", os.sep))
    probe_mod = probe_rel.replace("/", ".").removesuffix(".lean")
    body = _DUP_PROBE.format(imports="\n".join("import " + m for m in imports), target=target)
    os.makedirs(os.path.dirname(probe_abs), exist_ok=True)
    with open(probe_abs, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    try:
        res = build(project_root, probe_mod, timeout=timeout)
    finally:
        try:
            os.remove(probe_abs)
        except OSError:
            pass

    log = res.log
    m_total = _DUP_TOTAL.search(log)
    m_el = _DUP_ELAPSED.search(log)
    if m_total is None:
        return {"ran": False, "ok": False, "error": "判重没有产出（判不了）",
                "log": log[-2000:]}
    ours: list[str] = []
    cur: list[str] = []
    hit = False
    marker_re = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(marker) + r"\.")
    for line in log.splitlines():
        if line.startswith(("warning:", "trace:", "info:", "error:")):
            continue
        if line.startswith("-- "):
            if hit:
                ours.extend(cur)
            cur, hit = [line], False
            continue
        if not cur:
            continue
        cur.append(line)
        if marker_re.search(line):
            hit = True
    if hit:
        ours.extend(cur)
    return {"ran": True, "ok": not ours, "total": int(m_total.group(1)),
            "seconds": int(m_el.group(1)) / 1000 if m_el else 0.0,
            "ours": ours[:40]}


# ---------------------------------------------------------------- 同步根

_ROOT_TEMPLATE = """module

{imports}

/-! 自动生成（`kl sync-root`）：扫描 `{lib}/` 下全部 .lean，重写库根聚合文件。
不要手改。 -/
"""


def sync_root(project_root: str, lib: str = config.LIB, check_only: bool = False) -> dict[str, Any]:
    lib_dir = os.path.join(project_root, lib)
    root_file = os.path.join(project_root, lib + ".lean")
    if not os.path.isdir(lib_dir):
        return {"ok": False, "error": f"库目录不存在: {lib_dir}"}
    mods = [f"{lib}.{fn[:-5]}" for fn in sorted(os.listdir(lib_dir))
            if fn.endswith(".lean") and os.path.isfile(os.path.join(lib_dir, fn))]
    if not mods:
        return {"ok": False, "error": f"{lib_dir} 下没有 .lean 文件"}
    content = _ROOT_TEMPLATE.format(
        lib=lib, imports="\n".join(f"public import {m}" for m in mods))
    old = ""
    if os.path.exists(root_file):
        with open(root_file, encoding="utf-8") as f:
            old = f.read()
    changed = old != content
    if changed and not check_only:
        with open(root_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
    return {"ok": True, "root_file": root_file, "modules": mods, "changed": changed}


def build_module_manifest(project_root: str, probe_dir: str | None = None) -> dict[str, Any]:
    """从库根聚合文件生成探针要用的模块表 `modules.json`（[[模块, 文件名], …]）。

    ★ 为什么必须从聚合文件生成：硬编码的模块表会在库结构变化后**静默过期**
      （少覆盖的模块没有签名范围 ⟹ 它们的 A 层提及被误归到 B 层，不报错）。
    """
    root = project_root or DEFAULT_LEAN_ROOT
    out_dir = probe_dir or PROBE_DIR
    agg = config.aggregate(root)
    if not os.path.isfile(agg):
        return {"ok": False, "error": f"聚合文件不存在：{agg}（先 kl sync-root / lake build）"}
    with open(agg, encoding="utf-8") as f:
        text = f.read()
    mods: list[list[str]] = []
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("public import "):
            continue
        full = s[len("public import "):].strip()
        parts = full.split(".")
        if len(parts) < 2:
            continue
        mods.append([full, os.path.join(*parts[1:]) + ".lean"])
    if not mods:
        return {"ok": False, "error": "聚合文件里没有 `public import` 行"}
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "modules.json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(mods, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return {"ok": True, "path": path, "modules": [m[0] for m in mods]}


# ---------------------------------------------------------------- 书目定位

def locate(section: int) -> dict[str, Any]:
    """一节的页码五栏 —— 从【页码索引】读，不现场计算。

    索引由 `python -m kl.cli book-build` 生成（扫书源、机械提取页眉页码与小节号）；
    换书只改 `knowledge/books/<id>.json`。见 tools/kl/bookindex.py 的文档。
    """
    from kl import bookindex
    return bookindex.section_book(section)


def locate_anchor(anchor: str, limit: int = 20) -> dict[str, Any]:
    """在一章的英文转录里搜一段文字（Definition / Lemma / Figure / 任意引文）→ 页码。"""
    from kl import bookindex
    return bookindex.locate_anchor(anchor, limit=limit)


# ---------------------------------------------------------------- 模块卫生（module system）
#  Lean 4.35 的 module 模式里，`public section` 只暴露【名字】；【定义体】默认受保护
#  （importer 不能展开，见 Lean/AddDecl.lean 的 forceExpose 与 Lean/Meta/Check.lean 的提示）。
#  我们的库要求「下游可展开上游定义体」⟹ 内容文件统一 `@[expose] public section`。

def module_hygiene(lean_root: str, lib: str = config.LIB) -> dict[str, Any]:
    """每个内容模块：有 `module` 头；有声明时必须有 `@[expose] public section`。"""
    files: list[dict[str, Any]] = []
    problems: list[str] = []
    for m in aggregate_modules(lean_root, lib):
        p = module_source(lean_root, m)
        if not os.path.isfile(p):
            problems.append(f"{m}: 源文件不存在（{p}）")
            continue
        text = open(p, encoding="utf-8").read()
        decls = list_declarations(p)
        rec = {
            "module": m,
            "file": os.path.relpath(p, lean_root).replace("\\", "/"),
            "declarations": len(decls),
            "has_module": re.search(r"(?m)^module\s*$", text) is not None,
            "has_public_section": re.search(r"(?m)^\s*(?:@\[expose\]\s+)?public section\s*$", text) is not None,
            "has_expose": re.search(r"(?m)^\s*@\[expose\]\s+public section\s*$",
                                    text) is not None,
        }
        files.append(rec)
        if decls and not rec["has_module"]:
            problems.append(f"{m}: 有声明但没有 `module` 头")
        if decls and not rec["has_expose"]:
            problems.append(f"{m}: 有声明但没有 `@[expose] public section`"
                            "（下游无法展开定义体）")
    return {"ok": not problems, "files": files, "problems": problems}


def fix_module_headers(lean_root: str, lib: str = config.LIB) -> dict[str, Any]:
    """机械填充：把 `public section` 行补成 `@[expose] public section`（幂等）。"""
    changed: list[str] = []
    for m in aggregate_modules(lean_root, lib):
        p = module_source(lean_root, m)
        if not os.path.isfile(p):
            continue
        text = open(p, encoding="utf-8").read()
        new = re.sub(r"(?m)^(\s*)public section\s*$",
                     r"\1@[expose] public section", text)
        if new != text:
            open(p, "w", encoding="utf-8", newline="\n").write(new)
            changed.append(m)
    return {"ok": True, "changed": changed}


# ---------------------------------------------------------------- Lean 指针
#  清单用【全限定名 + 模块 + 位置 + 签名哈希】指向 Lean 声明（不做短名匹配）。
#  名字撞短名会静默错（A.foo / B.foo），所以后端一律用全限定名 + 模块解析。

def aggregate_modules(lean_root: str, lib: str = config.LIB) -> list[str]:
    """库根聚合文件 import 的模块（模块表的唯一事实源）。"""
    agg = os.path.join(lean_root, lib + ".lean")
    if not os.path.isfile(agg):
        return []
    with open(agg, encoding="utf-8") as f:
        text = f.read()
    mods = [m.group(1) for m in
            re.finditer(r"^public import (\w+(?:\.\w+)*)", text, re.M)]
    return [m for m in mods if m.split(".")[0] == lib]


def module_source(lean_root: str, module: str) -> str:
    return os.path.join(lean_root, *module.split(".")) + ".lean"


def ilean_decls(module: str) -> dict[str, dict[str, int]]:
    """模块的声明表：全限定名 → {line, col}（.ilean 是权威数据源）。"""
    p = ilean_path(module)
    if p is None:
        return {}
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    out: dict[str, dict[str, int]] = {}
    for name, a in (d.get("decls") or {}).items():
        if isinstance(a, (list, tuple)) and len(a) >= 2:
            out[str(name)] = {"line": int(a[0]), "col": int(a[1])}
    return out


_DECL_HEAD_RE = re.compile(
    r"^(?:@\[[^\]]*\]\s*)*"
    r"(?:(?:private|protected|noncomputable|nonrec|partial|unsafe|scoped|local)\s+)*"
    r"(theorem|lemma|def|abbrev|opaque|instance|structure|class|inductive)\s+"
    r"([A-Za-z_][\w'!?]*)")
_NS_OPEN_RE = re.compile(r"^namespace\s+(\S+)\s*$")
_NS_END_RE = re.compile(r"^end\s+(\S+)\s*$")


def _source_decls(lean_root: str, module: str) -> dict[str, dict[str, int]]:
    """源码扫描的声明表（补 .ilean 的漏记）。

    实测（2026-10-25 §19）：`abbrev JTuple := J → X`、`def projArb := fun x => x β`
    这类「类型/值不提及任何常量」的声明在 `.ilean` 里没有条目，kl_link/kl_audit 会误报 ghost。
    `.ilean` 仍是主数据源；这里只作补集（decl_index 里 setdefault），位置取关键字所在行。
    命名空间用 `namespace X … end X` 栈跟踪；无名 `end` 视为 section 结束，不弹栈（本库约定
    namespace 一律 `end 名字`）。
    """
    src = module_source(lean_root, module)
    if not os.path.isfile(src):
        return {}
    out: dict[str, dict[str, int]] = {}
    ns: list[str] = []
    with open(src, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            s = line.rstrip()
            m = _NS_OPEN_RE.match(s)
            if m:
                ns.append(m.group(1))
                continue
            m = _NS_END_RE.match(s)
            if m:
                if ns and ns[-1] == m.group(1):
                    ns.pop()
                continue
            m = _DECL_HEAD_RE.match(s)
            if not m:
                continue
            name = m.group(2)
            full = ".".join(ns + [name]) if ns else name
            # 位置与 .ilean/probe 一致：LSP 0-based 行号（probe 的 cmdStart 也是 0-based）
            out.setdefault(full, {"line": lineno - 1, "col": 0})
    return out


def decl_index(lean_root: str, lib: str = config.LIB) -> dict[str, dict[str, Any]]:
    """全库声明索引：全限定名 → {module, line, col}。

    数据源 = `.ilean`（权威）+ 源码扫描补集（见 `_source_decls`）。
    """
    idx: dict[str, dict[str, Any]] = {}
    for m in aggregate_modules(lean_root, lib):
        decls = ilean_decls(m)
        for name, pos in _source_decls(lean_root, m).items():
            decls.setdefault(name, pos)
        for name, pos in decls.items():
            idx[name] = {"module": m, **pos}
    return idx


def _sig_sha_index(lean_root: str) -> dict[tuple[str, int, int], str]:
    """(module, cmdLine, cmdCol) → 签名文本（绑定器 + 类型）的 sha256 前 16 位。

    签名范围来自 `.probe/decl_sig_ranges.json`；用 cmdStart 对齐 `.ilean` 的 decls。
    """
    p = os.path.join(PROBE_DIR, "decl_sig_ranges.json")
    if not os.path.isfile(p):
        return {}
    with open(p, encoding="utf-8") as f:
        doc = json.load(f)
    out: dict[tuple[str, int, int], str] = {}
    for e in doc.get("decls") or []:
        mod = e.get("module")
        cs, ss, se = e.get("cmdStart"), e.get("sigStart"), e.get("sigStop")
        if not (mod and cs and ss and se):
            continue
        src = module_source(lean_root, mod)
        if not os.path.isfile(src):
            continue
        with open(src, "rb") as f:
            data = f.read().split(b"\n")
        l1, c1 = int(ss["line"]), int(ss["col"])
        l2, c2 = int(se["line"]), int(se["col"])
        try:
            if l1 == l2:
                chunk = data[l1][c1:c2]
            else:
                chunk = b"\n".join([data[l1][c1:]] + data[l1 + 1:l2] + [data[l2][:c2]])
        except IndexError:
            continue
        out[(str(mod), int(cs["line"]), int(cs["col"]))] = \
            hashlib.sha256(chunk).hexdigest()[:16]
        # 幂等补键：按短名也能取到（`.ilean` 漏记的声明无法用 cmdStart 定位，
        # 位置由源码扫描给，行号可能差 1（doc comment 属于 command 起点），用名字兜底）
        nm = e.get("name")
        if nm:
            out[("name", str(mod), str(nm))] = \
                hashlib.sha256(chunk).hexdigest()[:16]
    return out


def link_pointers(section, lean_root: str) -> dict[str, Any]:
    """给清单里每条声明引用填指针（写回 section 的 atom.lean.pointers）。"""
    idx = decl_index(lean_root, section.lean_lib)
    shas = _sig_sha_index(lean_root)
    problems: list[str] = []
    filled = 0
    for atom in section.items:
        ptrs: dict[str, LeanPointer] = {}
        for n in atom.decl_names():
            info = idx.get(n)
            if info is None:
                problems.append(f"{atom.id}: 清单有 {n}，Lean 里找不到（先 lake build）")
                continue
            key = (info["module"], int(info["line"]), int(info["col"]))
            sha = shas.get(key) or shas.get(
                ("name", info["module"], n.rsplit(".", 1)[-1]), "")
            ptrs[n] = LeanPointer(name=n, module=info["module"],
                                  line=int(info["line"]), col=int(info["col"]),
                                  sig_sha256=sha)
            filled += 1
        atom.lean.pointers = ptrs
    return {"ok": not problems, "filled": filled, "problems": problems,
            "with_sig": sum(1 for a in section.items
                            for p in a.lean.pointers.values() if p.sig_sha256)}


def verify_pointers(section, lean_root: str,
                    idx: dict[str, dict[str, Any]] | None = None,
                    shas: dict[tuple[str, int, int], str] | None = None) -> list[str]:
    """逐个校验指针：模块里有该声明 · 位置一致 · 签名哈希一致。

    idx / shas 可传入（audit 已经算过一次，别重复读文件）。
    """
    idx = decl_index(lean_root, section.lean_lib) if idx is None else idx
    shas = _sig_sha_index(lean_root) if shas is None else shas
    problems: list[str] = []
    for atom in section.items:
        names = set(atom.decl_names())
        for n in sorted(atom.lean.pointers):
            if n not in names:
                problems.append(f"{atom.id}: 多余指针（{n} 已不被引用）")
        for n in atom.decl_names():
            ptr = atom.lean.pointers.get(n)
            if ptr is None:
                problems.append(f"{atom.id}: {n} 缺指针（跑 kl link）")
                continue
            info = idx.get(n)
            if info is None:
                problems.append(f"{atom.id}: 指针失效 —— Lean 里没有 {n}")
                continue
            if ptr.module and ptr.module != info["module"]:
                problems.append(f"{atom.id}: {n} 的模块过期（{ptr.module} → "
                                f"{info['module']}，跑 kl link）")
            if ptr.line != int(info["line"]) or ptr.col != int(info["col"]):
                problems.append(f"{atom.id}: {n} 的位置过期（源码改过，跑 kl link）")
            cur = shas.get((info["module"], int(info["line"]), int(info["col"]))) or \
                shas.get(("name", info["module"], n.rsplit(".", 1)[-1]))
            if cur is None:
                problems.append(f"{atom.id}: {n} 没有签名范围（重跑 DeclSigRanges）")
            elif not ptr.sig_sha256:
                problems.append(f"{atom.id}: {n} 缺签名哈希（跑 kl link）")
            elif cur != ptr.sig_sha256:
                problems.append(f"{atom.id}: {n} 的签名变了（跑 kl link）")
    return problems




_MODULE_TEMPLATE = """\
/-
Copyright (c) 2026 tutor. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.
Authors: tutor
-/
module

public import {lib}.Base

@[expose] public section

/-!
# {name}

（正文；口径见 docs/工程基准.md，流程见 docs/管线.md。写完后跑 kl sync-root。）
-/
"""


def new_module(lean_root: str, name: str, lib: str = config.LIB,
               force: bool = False) -> dict[str, Any]:
    """生成一个新内容模块的模板（module / public import Base / @[expose] public section）。"""
    path = os.path.join(lean_root, lib, name + ".lean")
    if os.path.exists(path) and not force:
        return {"ok": False, "error": f"已存在：{path}（要覆盖传 force）"}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(_MODULE_TEMPLATE.format(name=name, lib=lib))
    return {"ok": True, "written": path,
            "next": ["kl sync-root", "lake build"]}


def base_scope(lean_root: str | None = None, lib: str = config.LIB) -> dict[str, Any]:
    """③a′：**陈述层**引用的基底范围检查。

    允许集 = `knowledge/pipeline/base_candidate.json`（从内容层反向传播得到、已扣内容种子）
              ∪ `基底.json.scope_extras`（人工补登记的基底事实，如 √）
              ∪ core 原语（Init/Std/Lean/Batteries 命名空间）。
    A 层（签名里的提及）落在允许集外 ⟹ 报「超出基底范围」。

    B 层豁免：证明项是仪器（tactic 展开物、基底内部引理都在这里）。

    ★ 三个「基底」物件的分工（可及边界 / 许可集 / 登记表）见 `docs/工程基准.md` §1.1：
      本条读的是**许可集**（声明级、反向传播生成），不是 `Base.lean` 的 import 闭包（模块级、物理可及）。
    """
    from kl import graph as G  # 延迟导入（graph 反过来 import checks）

    root = lean_root or DEFAULT_LEAN_ROOT
    cand_path = config.BASE_CANDIDATE
    reg_path = config.BASE_TABLE
    if not os.path.isfile(cand_path):
        return {"ok": False, "error": f"缺 {cand_path}（先跑 ContentSupport.lean 生成）",
                "violations": []}
    base = set(json.load(open(cand_path, encoding="utf-8")))
    reg = json.load(open(reg_path, encoding="utf-8")) if os.path.isfile(reg_path) else {}
    extras = set(reg.get("scope_extras") or [])
    allowed = base | extras
    CORE = ("Init", "Std", "Lean", "Batteries")

    g = G.build(root=root, lib=lib)
    nodes, edges = g["nodes"], g["edges"]
    violations: dict[str, list[str]] = {}
    checked = 0
    for e in edges:
        if "A" not in e.get("layers", ""):
            continue
        src = nodes.get(e["src"])
        if not src or src.get("class") != "ours":
            continue
        if e.get("dst_class") == "ours":
            continue
        nm = e["dst"]
        if nm.split(".")[0] in CORE:
            continue
        checked += 1
        if nm not in allowed:
            violations.setdefault(nm, []).append(e["src"])
    return {
        "ok": not violations,
        "base_size": len(base), "extras": sorted(extras), "checked_a_refs": checked,
        "violations": [{"name": k, "used_by": v[:3]} for k, v in sorted(violations.items())],
        "note": "允许集 = base_candidate ∪ scope_extras；A 层检查，B 层豁免（仪器）",
    }



def doctor(lean_root: str | None = None, lib: str = config.LIB) -> dict[str, Any]:
    """管线体检（开工前先跑）：产物新鲜度 + 自洽性。

    设计原则（学员诊断 2026-10-24）：**发现问题 ⟹ 立刻维护管线**。
    每次踩坑都要落成「机械判据 / 工具修复 / 文档规则」之一，而不是只修当下那一处。
    本命令就是"管线有没有跟着修"的体检入口。
    """
    root = lean_root or DEFAULT_LEAN_ROOT
    probe = PROBE_DIR
    rows: list[dict[str, Any]] = []
    nexts: list[str] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        rows.append({"check": name, "ok": bool(ok), "detail": detail})

    # profile（A3）：书实例配置；没有 KL_PROFILE 时按仓库布局约定（旧行为）
    add("profile（KL_PROFILE）", True,
        config.PROFILE_PATH if config.PROFILE_PATH else "未设置（按仓库布局约定运行）")

    lib_dir = os.path.join(root, lib)
    mods = aggregate_modules(root, lib)
    agg = os.path.join(root, lib + ".lean")
    agg_text = open(agg, encoding="utf-8").read() if os.path.isfile(agg) else ""
    dir_mods = sorted(f"{lib}.{f[:-5]}" for f in os.listdir(lib_dir)
                      if f.endswith(".lean")) if os.path.isdir(lib_dir) else []
    missing = [f"public import {m}" for m in dir_mods if f"public import {m}" not in agg_text]
    add("聚合文件", not missing, "ok" if not missing else "缺 " + "；".join(missing[:4]))
    if missing:
        nexts.append("python -m kl.cli sync-root")

    src_paths = [module_source(root, m) for m in mods]
    src_paths = [p for p in src_paths if os.path.isfile(p)]
    newest = max([os.path.getmtime(p) for p in src_paths] + [os.path.getmtime(agg)
                  if os.path.isfile(agg) else 0])
    pm = os.path.join(probe, "modules.json")
    add("探针模块表", os.path.isfile(pm) and os.path.getmtime(pm) >= newest,
        "ok" if os.path.isfile(pm) and os.path.getmtime(pm) >= newest
        else "陈旧/缺失：先 kl probes（改模块后必须重生成）")
    if not (os.path.isfile(pm) and os.path.getmtime(pm) >= newest):
        nexts.append("python -m kl.cli probes")
    for f in ("decl_sig_ranges.json", "struct_edges.json"):
        p = os.path.join(probe, f)
        ok = os.path.isfile(p) and os.path.getmtime(p) >= newest
        add(f"探针 {f}", ok,
            "ok" if ok else "陈旧/缺失：kl probes → lake build → 两个探针")
        if not ok:
            nexts.append(f"lake env lean tools/lean-probes/"
                         + ("DeclSigRanges.lean" if "decl" in f else "StructEdges.lean"))

    # 图数据新鲜度（2026-10-24 首次团队测试暴露：gate+doctor 全绿但 graph.json 缺新节点，
    #  AGENTS §8 要求「动过源码 ⟹ 重算图」，却没有任何判据会报陈旧）
    gpath = config.GRAPH
    g_inputs = [os.path.getmtime(p) for p in
                [os.path.join(probe, f) for f in
                 ("modules.json", "decl_sig_ranges.json", "struct_edges.json")]
                if os.path.isfile(p)]
    g_newest = max([newest] + g_inputs)
    g_ok = os.path.isfile(gpath) and os.path.getmtime(gpath) >= g_newest
    add("图数据", g_ok, "ok" if g_ok
        else "陈旧/缺失：源码或探针比 graph.json 新 ⟹ 重算图并重渲染")
    if not g_ok:
        nexts.append("python -m kl.cli graph --json " + config.rel(config.GRAPH)
                     + "（再 python tools/kl/viz.py 重渲染）")

    # .ilean 与源码一致（改源码没 build ⟹ 后端读到旧声明表）
    declared = decl_index(root, lib)
    stale = []
    for m in mods:
        srcp = module_source(root, m)
        if not os.path.isfile(srcp):
            continue
        from_src = {fq for _k, fq in list_declarations(srcp)}
        from_ilean = {fq for fq, info in declared.items() if info["module"] == m}
        if from_src != from_ilean:
            stale.append(f"{m}: 源 {len(from_src)} / .ilean {len(from_ilean)}")
    add(".ilean 同步", not stale, "ok" if not stale else "；".join(stale[:3]))
    if stale:
        nexts.append("lake build")

    # 页码索引（2026-10-25 增强）：不只验存在，还验「每节标题页都落在该节的 md 范围内」。
    # 旧版只验文件在不在 ⟹ 节首边界页被静默切掉也报绿（§16 的 Definition 页：偶数页页眉无节号，
    # detect_section 旧实现只扫前 25 行，命中不了被压到页中下部的 §N 标题 ⟹ 该页归上一节、
    # ★ 判据用【md 转录里锚定的 §N 标题页】而不是 page_section 计数：
    #   page_section 在扫描件/OCR 噪声下会把习题页/正文引用误判成节页，计数对比会假红；
    #   而我们真正要的保证是「节标题页在 ③c quote 的搜索范围内」。
    idx = config.BOOK_INDEX
    idx_ok = os.path.isfile(idx)
    idx_detail = "ok" if idx_ok else "缺 " + config.rel(config.BOOK_INDEX) + "：book-build"
    if idx_ok:
        try:
            _idx = json.load(open(idx, encoding="utf-8"))
            _md_dir = ((_idx.get("sources") or {}).get("abs_en_md") or "")
            _heads: dict[int, int] = {}
            _scanned = 0
            if _md_dir and os.path.isdir(_md_dir):
                for _fn in sorted(os.listdir(_md_dir)):
                    _m = re.match(r"^p(\d{4})\.md$", _fn)
                    if not _m:
                        continue
                    _page = int(_m.group(1))
                    _scanned += 1
                    try:
                        _text = open(os.path.join(_md_dir, _fn), encoding="utf-8").read()
                    except Exception:
                        continue
                    for _line in _text.splitlines():
                        _hm = re.match(r"^§\s*(\d{1,2})\s+[A-Z]", _line.strip())
                        if _hm:
                            _heads.setdefault(int(_hm.group(1)), _page)
                            break
            if _scanned == 0:
                idx_detail = "ok（md 转录不可用，标题页一致性未检）"
            else:
                _bad = []
                for _sn, _ent in (_idx.get("sections") or {}).items():
                    try:
                        _n = int(_sn)
                    except Exception:
                        continue
                    _hp = _heads.get(_n)
                    _rng = _ent.get("md") or []
                    if _hp is None or not _rng or _rng[0] is None:
                        continue
                    if not (_rng[0] <= _hp <= _rng[1]):
                        _bad.append(f"§{_sn}: 标题在 md {_hp}，范围 {_rng[0]}–{_rng[1]}")
                if _bad:
                    idx_ok = False
                    idx_detail = "节标题页不在范围内（重建索引）：" + "；".join(_bad[:4])
        except Exception as exc:
            idx_ok = False
            idx_detail = f"读页码索引失败：{exc}"
    add("页码索引", idx_ok, idx_detail)
    if not idx_ok:
        nexts.append("python -m kl.cli book-build（需要 KL_BOOK_INDEX / KL_BOOK_PDF / KL_BOOK_MD）")

    # 基底候选
    cand = config.BASE_CANDIDATE
    ncand = 0
    if os.path.isfile(cand):
        import json as _json
        ncand = len(_json.load(open(cand, encoding="utf-8")))
    add("基底候选", os.path.isfile(cand) and ncand > 0,
        f"ok（{ncand} 条）" if ncand else "缺：跑 ContentSupport.lean（mathlib 工程）")
    if not ncand:
        nexts.append("lake env lean tools/lean-probes/ContentSupport.lean（在 mathlib 工程）")

    hyg = module_hygiene(root, lib)
    add("module 卫生", hyg["ok"], "ok" if hyg["ok"] else "；".join(hyg["problems"][:3]))
    if not hyg["ok"]:
        nexts.append("python -m kl.cli fix-headers")

    # 术语表（2026-10-25）：长程任务里后来 agent 的入口 —— 术语→原子/Lean/清单指针。
    # 没有这项检查时，术语表会静默漂移（改名/删声明/加节后不更新）。
    from kl import glossary as _glossary
    gl = _glossary.check(root, declared=declared)
    add("术语表", gl["ok"], gl["detail"])
    if not gl["ok"]:
        nexts.append("python -m kl.cli glossary build")

    # ilean 剪枝状态（2026-10-25 内存治理）：mathlib 保留集之外的 .ilean 已移到归档目录。
    # ★ 判据用**剪枝工具的实时结果**，不读 manifest 快照：③b 判重会编译工具根模块
    #   （Mathlib.Tactic.DuplicateDecls），其 .ilean 在跑完判重后重新出现 ⟹ 拿旧快照比计数
    #   会一直报「多一个」。保留集 = Base 闭包 ∪ 在场的工具根（单一事实源在剪枝工具里）。
    archive = os.environ.get("KL_ILEAN_ARCHIVE") or r"D:\lean\mathlib-ilean-archive"
    tool_py = os.path.join(root, "tools", "lean-ilean-prune.py")
    if os.path.isdir(archive) and os.path.isfile(tool_py):
        try:
            import importlib.util as _ilu
            _spec = _ilu.spec_from_file_location("kl_ilean_prune", tool_py)
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            if not os.path.isdir(_mod.BUILD):
                add("ilean 剪枝", True, "mathlib 构建目录不存在（未构建过）")
            else:
                _cur = {_mod.module_of(r) for r in _mod.iter_ileans(_mod.BUILD)}
                _idx = _mod.build_index()
                _keep = _mod.keep_set(_idx, _cur)
                _base = _mod.closure(_idx)
                _missing = sorted(_base - _cur)
                _extra = sorted(_cur - _keep)
                ok_prune = not _missing and not _extra
                add("ilean 剪枝", ok_prune,
                    f"PRUNED（保留集 {len(_keep)} 全在位）" if ok_prune
                    else f"状态不一致：缺 {_missing[:3]} 多 {_extra[:3]}；"
                         f"跑 python tools/lean-ilean-prune.py status/prune")
                if not ok_prune:
                    nexts.append("python tools/lean-ilean-prune.py prune")
        except Exception as exc:  # 归档损坏不该让整个 doctor 崩
            add("ilean 剪枝", False, f"跑剪枝工具失败：{exc}")
    else:
        add("ilean 剪枝", True, "未剪枝（FULL）")

    # 入序表状态（2026-10-25 §15 收口时发现）：内容项的 status 没人更新 —— §14 写完
    # c.orderTop 仍是 todo ⟹ kl_next 一直把它当待办。检查双向一致：节 verdict ok ⟺ status=done:*。
    # ★ 2026-10-25 补：五步文档里 `kl_check(n)` 不带 `--update` ⟹ verdict 可能缺失/陈旧；
    #   这里兜底：verdict 缺了就按「清单里所有原子都 verified」判定，避免按文档走的 worker 误红。
    def _inventory_ok(sec: dict) -> bool:
        v = sec.get("verdict") or {}
        if v:
            return bool(v.get("ok"))
        items = sec.get("items") or []
        return bool(items) and all(
            (it.get("lean") or {}).get("status") == "verified" for it in items)

    order_path = config.ORDER_TABLE
    if os.path.isfile(order_path):
        try:
            order = json.load(open(order_path, encoding="utf-8"))
            bad = []
            for it in order.get("content") or []:
                ref = str(it.get("book_ref") or "")
                if not ref.isdigit():
                    continue
                inv = os.path.join(config.pipeline_dir(root), f"section{ref}.json")
                done = str(it.get("status") or "").startswith("done")
                ok_sec = False
                if os.path.isfile(inv):
                    try:
                        ok_sec = _inventory_ok(json.load(open(inv, encoding="utf-8")))
                    except Exception:
                        ok_sec = False
                if ok_sec and not done:
                    bad.append(f"{it.get('id')}(§{ref}) 已完成但 status={it.get('status')}")
                if done and not ok_sec:
                    bad.append(f"{it.get('id')}(§{ref}) status={it.get('status')} 但该节未完成")
            add("入序表状态", not bad, "ok" if not bad else "；".join(bad[:4]))
            if bad:
                nexts.append("更新 " + config.rel(config.ORDER_TABLE) + " 的 status（done:SectionN）")
        except Exception as exc:
            add("入序表状态", False, f"读入序表失败：{exc}")

    # ③b 判重记录（2026-10-25 修）：判重结果只在「同一次 --with-dup --update」时落盘 ——
    # 先 --update 再 --with-dup 会让 verdict.dup 为空（跑过等于没跑，§15 踩到）。
    # 已完成的节必须留下 ③b 记录；实测 11 s（不是文档旧写的 1–4 分钟）。
    dup_bad: list[str] = []
    sec_dir = config.pipeline_dir(root)
    if os.path.isdir(sec_dir):
        for fn in sorted(os.listdir(sec_dir)):
            if not (fn.startswith("section") and fn.endswith(".json")):
                continue
            try:
                sec = json.load(open(os.path.join(sec_dir, fn), encoding="utf-8"))
            except Exception:
                continue
            if not _inventory_ok(sec):
                continue
            d = (sec.get("verdict") or {}).get("dup") or {}
            if not (d.get("ran") and d.get("ok")):
                dup_bad.append("§" + fn[len("section"):-len(".json")])
    add("③b 判重记录", not dup_bad,
        "ok" if not dup_bad
        else "缺 ③b 记录：" + "、".join(dup_bad[:6]) + "（跑 kl check <n> --with-dup --update）")
    if dup_bad:
        nexts.append("对上面的节跑 python -m kl.cli check <n> --with-dup --update（一次跑完才落盘）")

    return {"ok": all(r["ok"] for r in rows), "checks": rows,
            "next": nexts,
            "note": "发现新坑 ⟹ 立刻把它变成这里的检查项（或判据/文档规则），再继续"}


# ---------------------------------------------------------------- ③c quote 逐字校验
#
# 2026-10-25 补：此前「quote 必须逐字」只有契约文字，没有机械判据 ⟹ 任何"看起来像书"的
# 英文都能通过 kl_check。
# ★ md 转录是【刻意保留 LaTeX 形式】的（agent 可以直接从中读出语义，这是 OCR 的设计目标，
#   不是缺陷）。所以 quote 字段存的是排版归一化后的可读英文；判据对 md 和 quote 两边做
#   同一套排版规范化（LaTeX 记号 / unicode 数学字符 / 引号 / 空白 / 大小写），再要求 quote
#   是页面文本的连续子串。md 文件本身不做任何改写。

_QUOTE_UNICODE = {
    "ℬ": "B", "ℝ": "R", "ℤ": "Z", "ℕ": "N", "ℚ": "Q", "ℂ": "C",
    "≤": "<=", "≥": ">=", "×": "x", "→": "->", "↔": "<->", "∈": " in ",
    "⊆": " subset ", "⊂": " subset ", "⊇": " superset ", "⊃": " superset ",
    "∪": " union ", "∩": " inter ", "∅": " emptyset ", "ℓ": "ell", "ℵ": "aleph",
    "“": '"', "”": '"', "‘": "'", "’": "'", "—": "-", "–": "-", "−": "-",
    "₊": "+", "₋": "-", "∞": "infty",
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
    "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
}

_QUOTE_MATH = [
    (re.compile(r"\\(?:mathcal|mathbb|mathrm|mathbf|mathsf)\{([^{}]*)\}"), r"\1"),
    (re.compile(r"\\text\{([^{}]*)\}"), r"\1"),
    (re.compile(r"\\leq\b|\\le\b"), "<="),
    (re.compile(r"\\geq\b|\\ge\b"), ">="),
    (re.compile(r"\\mid\b"), "|"),
    (re.compile(r"\\times\b"), "x"),
    (re.compile(r"\\infty\b"), "infty"),
    (re.compile(r"\\ldots\b|\\dots\b"), "..."),
    (re.compile(r"\\varnothing\b|\\emptyset\b"), " emptyset "),
    (re.compile(r"\\in\b"), " in "),
    (re.compile(r"\\cup\b"), " union "),
    (re.compile(r"\\cap\b"), " inter "),
    (re.compile(r"\\subseteq\b|\\subset\b"), " subset "),
    (re.compile(r"\\supseteq\b|\\supset\b"), " superset "),
    (re.compile(r"\\neq\b|\\ne\b"), "!="),
    (re.compile(r"\\setminus\b"), "-"),
    (re.compile(r"\\(?:left|right)\b"), ""),
    (re.compile(r"\\[A-Za-z]+\b"), lambda m: m.group(0)[1:]),  # 其余 \word → word
]


def _norm_prose(s: str) -> str:
    """书文/quote 的排版规范化：LaTeX 记号、unicode 数学字符、Markdown 粗体、引号、空白、大小写。

    ★ md 是刻意保留 LaTeX 的转录（agent 可直接读语义）；这里只做【比较用】的归一化，
      md 文件本身不改。最后把空白全部去掉，避免 `x<a` vs `x < a`、花括号/下标排版差异。
    """
    for a, b in _QUOTE_UNICODE.items():
        s = s.replace(a, b)
    s = s.replace("\\{", "{").replace("\\}", "}")
    s = s.replace("$", "").replace("**", "").replace("*", "").replace("`", "")
    for pat, rep in _QUOTE_MATH:
        s = pat.sub(rep, s)
    s = s.replace("{", "").replace("}", "").replace("_", "")
    s = re.sub(r"\s+", "", s)
    # 只比较字母数字流：标点/排版差异（句点 vs 逗号、破折号、引号）不算改动；
    # 这也让“用省略号删节”的短引在分段后仍可严格校验。
    s = re.sub(r"[^a-z0-9]+", "", s.lower())
    return s


def quote_check(section) -> dict[str, Any]:
    """③c：清单里的 quote 必须能在书的英文转录页里（规范化后）逐字找到。"""
    from kl import bookindex  # 延迟 import：checks 被 bookindex 反向依赖时避免环

    pages = getattr(section.book, "md", None)
    if not pages:
        return {"ok": False, "checked": 0,
                "problems": ["清单缺 book.md（先 `kl book <n> --write` 回填/page 索引）"]}
    try:
        start, end = int(pages[0]), int(pages[-1])
    except Exception:
        return {"ok": False, "checked": 0, "problems": [f"book.md 非法：{pages}"]}
    cfg = bookindex.load_config(None)
    en = bookindex._src(cfg, "en")
    md_dir = bookindex._resolve(en, "md_env", "md_path")
    if not (md_dir and os.path.isdir(md_dir)):
        # 没有环境变量时的兜底：book-build 写进索引的绝对路径
        _idx = bookindex.load_index(None) or {}
        md_dir = ((_idx.get("sources") or {}).get("abs_en_md") or "")
    if not (md_dir and os.path.isdir(md_dir)):
        return {"ok": True, "skipped": "book_md 不可用（无 KL_BOOK_MD / 索引里也没有 abs_en_md）",
                "checked": 0}
    chunks: list[str] = []
    for p in range(start, end + 1):
        f = os.path.join(md_dir, f"p{p:04d}.md")
        if os.path.isfile(f):
            chunks.append(open(f, encoding="utf-8").read())
    blob = _norm_prose("\n".join(chunks))
    problems: list[str] = []
    items: list[dict[str, Any]] = []
    matched = 0
    elided = 0
    _ellipsis = re.compile(r"\s*(?:\.\.\.|…|⋯)\s*")
    for it in section.items:
        q = (it.quote or "").strip()
        if not q:
            problems.append(f"{it.id}: quote 为空")
            items.append({"id": it.id, "ok": False, "segments": 0,
                          "problem": "quote 为空"})
            continue
        # 允许用省略号删节（现有清单里就有 “…” 的短引）：每一段必须按顺序在页面里逐字出现。
        segs = [s for s in _ellipsis.split(q) if s.strip()]
        if len(segs) > 1:
            elided += 1
        pos = 0
        ok_any = True
        for seg in segs:
            ns = _norm_prose(seg)
            if not ns:
                continue
            j = blob.find(ns, pos)
            if j < 0:
                ok_any = False
                break
            pos = j + len(ns)
        rec = {"id": it.id, "ok": bool(ok_any and segs), "segments": len(segs),
               "problem": ""}
        if ok_any and segs:
            matched += 1
        else:
            msg = f"{it.id}: 在 md p{start}–p{end} 找不到该 quote（规范化后）"
            problems.append(msg)
            rec["problem"] = msg
        items.append(rec)
    return {"ok": not problems, "checked": len(section.items), "matched": matched,
            "elided": elided, "pages": [start, end], "problems": problems,
            "items": items}


# ---------------------------------------------------------------- audit


def _mod_of_file(rel: str) -> str:
    """`<lib>/Section13.lean` → `<lib>.Section13`。"""
    p = rel.replace("\\", "/")
    if p.endswith(".lean"):
        p = p[:-5]
    return p.replace("/", ".")


def audit(section, lean_root: str) -> dict[str, Any]:
    """清单 ↔ Lean 声明的双向覆盖 + 必填字段 + 清单自洽。"""
    problems: list[str] = []
    unregistered: list[dict[str, str]] = []
    ghosts: list[str] = []

    for it in section.items:
        problems.extend(f"{it.id}: {p}" for p in it.problems())
    if len({it.id for it in section.items}) != len(section.items):
        problems.append("id 有重复")

    # ★ 权威数据源 = .ilean（全限定名 + 位置），不做短名匹配（短名会撞）
    declared = decl_index(lean_root, section.lean_lib)
    # ★ 多节库：本节只对自己文件里的声明负责（别的节的文件不是「未登记」）
    own_files = [f for f in section.files() if f]
    own_modules = {_mod_of_file(f) for f in own_files}
    owned = {fq for fq, info in declared.items()
             if not own_modules or info["module"] in own_modules}
    registered = set(section.names())
    for fq in sorted(owned):
        if fq not in registered:
            unregistered.append({"module": declared[fq]["module"], "decl": fq})
    for n in section.names():
        if n not in owned:
            ghosts.append(n)

    # 源文件 ↔ .ilean 一致性：源码改过但没 build ⟹ 后端会读到旧声明表
    by_mod: dict[str, set[str]] = {}
    for fq, info in declared.items():
        by_mod.setdefault(info["module"], set()).add(fq)
    stale: list[str] = []
    for m in aggregate_modules(lean_root, section.lean_lib):
        src = module_source(lean_root, m)
        if not os.path.isfile(src):
            continue
        from_src = {fq for _k, fq in list_declarations(src)}
        from_ilean = by_mod.get(m, set())
        if from_src != from_ilean:
            stale.append(f"{m}: 源 {len(from_src)} 条 / .ilean {len(from_ilean)} 条"
                         f"（差 {sorted(from_src ^ from_ilean)[:4]}）")
    if stale:
        problems.append("源文件与 .ilean 不同步（先 lake build）：" + "；".join(stale))

    for k in section.book.missing():
        problems.append(f"book.{k} 缺（用 kl_book 定位后补上）")
    if "book_pages" in section.extra:
        problems.append("旧式 book_pages 字段 —— 建议迁移到 book 五栏")

    # ── 1:1 归属检查：书的原子（item）↔ Lean 声明 ─────────────────────
    #   verified 原子   恰好一条 primary（1:1 的那条）
    #   partial 原子    0 条 primary + 若干 witness（书上断言只形式化了一部分）
    #   todo 原子       0 条声明
    #   非原子声明      derived（bridge / aux / alias），挂在它来源的原子下
    ids = {it.id for it in section.items}
    claims: dict[str, list[str]] = {}
    primaries: list[tuple[str, str]] = []
    derived: list[dict[str, Any]] = []
    witnesses: list[dict[str, Any]] = []
    for it in section.items:
        lean = it.lean
        prim = lean.primary
        share = str(lean.extra.get("shares_decl_with") or "")
        if prim:
            primaries.append((it.id, prim))
            claims.setdefault(prim, []).append(it.id)
        if share:
            if share not in ids:
                problems.append(f"{it.id}: shares_decl_with 指向不存在的 id {share!r}")
            if not it.identity_decl:
                problems.append(f"{it.id}: shares_decl_with 必须配 identity_decl")
        for d in lean.derived:
            if not isinstance(d, dict) or not d.get("name"):
                problems.append(f"{it.id}: derived 条目缺 name")
                continue
            if d.get("kind") not in ("bridge", "aux", "alias", "generalization"):
                problems.append(f"{it.id}: derived {d['name']} 的 kind 非法"
                                f"（只许 bridge/aux/alias/generalization）")
            derived.append({"item": it.id, "name": d["name"],
                            "kind": d.get("kind"), "why": d.get("why", "")})
            claims.setdefault(d["name"], []).append(it.id)
        for w in lean.witness:
            if not isinstance(w, dict) or not w.get("name"):
                problems.append(f"{it.id}: witness 条目缺 name")
                continue
            witnesses.append({"item": it.id, "name": w["name"], "why": w.get("why", "")})
            claims.setdefault(w["name"], []).append(it.id)

    # 每条声明只能被一个 item 认领（多对多 ⟹ item 粒度没拆到原子）
    dup_claim = {n: a for n, a in claims.items() if len(a) > 1}
    if dup_claim:
        problems.append(f"{len(dup_claim)} 条声明被多条 item 认领 ⟹ item 没拆到原子粒度")

    by_decl: dict[str, tuple[str, str]] = {}
    for iid, n in primaries:
        if n in by_decl:
            problems.append(f"{n} 被多个原子登记为 primary")
        by_decl[n] = ("primary", iid)
    for d in derived:
        if d["name"] in by_decl:
            problems.append(f"{d['name']} 被重复登记")
        by_decl[d["name"]] = ("derived", d["item"])
    for w in witnesses:
        if w["name"] in by_decl:
            problems.append(f"{w['name']} 被重复登记")
        by_decl[w["name"]] = ("witness", w["item"])
    unclassified = sorted(owned - set(by_decl))
    not_in_file = sorted(set(by_decl) - owned)

    problems.extend(verify_pointers(section, lean_root, declared,
                                     _sig_sha_index(lean_root)))

    atoms_by_status: dict[str, int] = {}
    for it in section.items:
        atoms_by_status[it.lean.status] = atoms_by_status.get(it.lean.status, 0) + 1

    ok = not problems and not unregistered and not ghosts
    return {
        "section": section.section,
        "ok": ok,
        "items": len(section.items),
        "atoms": atoms_by_status,
        "coverage": f"{section.coverage()[0]}/{section.coverage()[1]}",
        "problems": problems,
        "unregistered_decls": unregistered,
        "ghost_names": ghosts,
        "note_unregistered": "文件里有、清单里没登记 ⟹ 图里会丢节点（或它是生成声明）",
        "note_ghosts": "清单里有、文件里没有 ⟹ 幽灵条目（改名/删除后没回填）",
        "mapping": {
            "primaries": len(primaries),
            "derived": len(derived),
            "witnesses": len(witnesses),
            "declarations_in_file": len(owned),
            "identity_total": len(primaries) + len(derived) + len(witnesses),
            "unclassified": unclassified,
            "not_in_file": not_in_file,
            "dup_claim": dup_claim,
            "pointers": sum(len(a.lean.pointers) for a in section.items),
        },
        "claims": claims,
        "note_mapping": "1:1 规则：verified 原子 ↔ 一条 primary；partial 原子只挂 witness；"
                        "bridge/aux/alias 走 derived；生成声明（投影/mk/rec）不登记。",
    }


def summarize(build_res: BuildResult, sorries: list[dict[str, Any]],
              axioms: dict[str, Any] | None,
              forbidden: list[dict[str, Any]] | None = None,
              dup_report: dict[str, Any] | None = None) -> tuple[bool, list[str]]:
    problems: list[str] = []
    if not build_res.ok:
        problems.append(f"① build 失败（exit {build_res.exit_code}）")
    total_sorry = sum(s["total"] for s in sorries)
    if total_sorry:
        problems.append(f"② sorry {total_sorry} 处")
    if axioms is not None:
        if axioms.get("unknown"):
            problems.append(f"② {len(axioms['unknown'])} 条查不到公理依赖（判不了）")
        if axioms.get("bad"):
            problems.append(f"② {len(axioms['bad'])} 条依赖非标准公理")
    if forbidden:
        problems.append(f"③a 提及禁止清单 {len(forbidden)} 处")
    if dup_report is not None and not dup_report.get("ok"):
        if not dup_report.get("ran"):
            problems.append("③b 判重没跑成（判不了）")
        else:
            problems.append(f"③b 落进 {len(dup_report.get('ours') or [])} 行重复组")
    return (not problems), problems
