# -*- coding: utf-8 -*-
"""运行期配置（A3）：book profile + 环境变量 → 引擎的唯一配置来源。

## 为什么有它

A3 之前，引擎把「这本书」写死在代码里：`MunkresLean`（库名）、`munkres-2e`（书 id）、
`knowledge/pipeline`（清单目录）。换书就变成改代码 —— 那等于没有一般化。
现在配置从两处来：

```
KL_PROFILE = <book-profile.json>        ← 插件 / MCP bundle 启动时给（字段见 docrepo
                                           docs/plugin-api.md §3）
KL_* 环境变量                            ← 显式覆盖（优先级最高）
仓库布局约定 + 探测                       ← 没有 profile 时的回退（保持旧行为）
```

优先级：**环境变量 > profile > 布局约定/探测**。

★ 没有 `KL_PROFILE` 且没有 `KL_LEAN_LIB` 时，行为与引入本文件前**完全一致**：
  仓库根由 tools/kl 的位置推出，库名由 `lakefile.toml` 的 `[[lean_lib]] name` 或唯一
  的根级 `.lean` 文件探测，书 id 由 `knowledge/books/` 下唯一的 json 探测。
"""

from __future__ import annotations

import json
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_FILE_REPO = os.path.dirname(os.path.dirname(_HERE))  # tools/kl/ → 仓库根

_RAW_PROFILE = (os.environ.get("KL_PROFILE") or "").strip()
PROFILE_PATH = os.path.abspath(_RAW_PROFILE) if _RAW_PROFILE else ""
PROFILE_ERROR = ""


def _read_profile(path: str) -> dict:
    """读 profile 并按 docrepo plugin-api.md §3 的路径约定解析。"""
    with open(path, encoding="utf-8-sig") as fh:
        raw = json.load(fh)
    if not isinstance(raw, dict):
        raise ValueError("根必须是对象")
    d = os.path.dirname(path)
    paths = raw.get("paths") or {}
    lean = raw.get("lean") or {}
    judge = raw.get("judge") or {}

    def _abs(p: str) -> str:
        p = str(p or "")
        if not p:
            return ""
        return os.path.normpath(p if os.path.isabs(p) else os.path.join(d, p))

    repo = _abs(paths.get("repo") or ".")

    def _in_repo(p: str) -> str:
        p = str(p or "")
        if not p:
            return ""
        return os.path.normpath(p if os.path.isabs(p) else os.path.join(repo, p))

    lib = str(lean.get("lib") or "")
    return {
        "file": path,
        "repo": repo,
        "book_id": str(raw.get("book_id") or ""),
        "title": str(raw.get("title") or ""),
        "lean_lib": lib,
        "lean_namespace": str(lean.get("namespace") or ""),
        "strip_prefixes": [str(x) for x in (lean.get("strip_prefixes") or []) if str(x)],
        "aggregate": os.path.join(repo, lib + ".lean") if lib else "",
        "book_config": _in_repo(raw.get("book_config")),
        "inventory": _in_repo(paths.get("inventory") or "knowledge/pipeline"),
        "order_table": _in_repo(paths.get("order_table")),
        "base_lean": _in_repo(paths.get("base_lean")),
        "graph": _in_repo(paths.get("graph")),
        "glossary": _in_repo(paths.get("glossary")),
        "md": _in_repo(paths.get("md")),
        "base_candidate": _in_repo(judge.get("base_candidate")),
        "base_table": _in_repo(judge.get("forbidden_list")),
        "env": {str(k): str(v) for k, v in (raw.get("env") or {}).items()},
    }


if PROFILE_PATH:
    try:
        PROFILE = _read_profile(PROFILE_PATH)
    except Exception as exc:  # noqa: BLE001 —— 配置错必须响亮，不能静默退化
        PROFILE = None
        PROFILE_ERROR = f"KL_PROFILE 读不了（{PROFILE_PATH}）：{exc}"
        raise RuntimeError(PROFILE_ERROR) from exc
else:
    PROFILE = None


# ---------------------------------------------------------------- 探测（无 profile 时）

def _detect_lib(repo: str) -> str:
    """从 lakefile.toml 的 `[[lean_lib]] name = "…"` 探测库名；否则唯一根级 .lean。"""
    lake = os.path.join(repo, "lakefile.toml")
    if os.path.isfile(lake):
        try:
            with open(lake, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            text = ""
        found = re.findall(r'\[\[lean_lib\]\][^\[]*?name\s*=\s*"([^"]+)"', text, re.S)
        if found:
            return found[0]
    try:
        cands = [f[:-5] for f in sorted(os.listdir(repo))
                 if f.endswith(".lean") and os.path.isfile(os.path.join(repo, f))
                 and f[:-5] not in ("Lakefile", "lakefile")]
    except OSError:
        cands = []
    return cands[0] if len(cands) == 1 else ""


def _detect_book_id(books_dir: str) -> str:
    try:
        stems = [f[:-5] for f in sorted(os.listdir(books_dir))
                 if f.endswith(".json") and os.path.isfile(os.path.join(books_dir, f))]
    except OSError:
        return ""
    return stems[0] if len(stems) == 1 else ""


# ---------------------------------------------------------------- 常量

REPO = os.path.abspath((PROFILE or {}).get("repo") or _FILE_REPO)
LEAN_ROOT = os.path.abspath(os.environ.get("KL_LEAN_ROOT") or REPO)
LIB = (os.environ.get("KL_LEAN_LIB")
       or (PROFILE or {}).get("lean_lib")
       or _detect_lib(LEAN_ROOT)
       or "Main")
NAMESPACE = (os.environ.get("KL_LEAN_NAMESPACE")
             or (PROFILE or {}).get("lean_namespace")
             or (LIB[:-4] if LIB.endswith("Lean") else LIB))

PIPELINE_DIR = ((PROFILE or {}).get("inventory")
                or os.path.join(REPO, "knowledge", "pipeline"))
ORDER_TABLE = ((PROFILE or {}).get("order_table")
               or os.path.join(PIPELINE_DIR, "入序表.json"))
BASE_TABLE = ((PROFILE or {}).get("base_table")
              or os.path.join(PIPELINE_DIR, "基底.json"))
BASE_CANDIDATE = ((PROFILE or {}).get("base_candidate")
                  or os.path.join(PIPELINE_DIR, "base_candidate.json"))
GRAPH = ((PROFILE or {}).get("graph") or os.path.join(PIPELINE_DIR, "graph.json"))
GLOSSARY = ((PROFILE or {}).get("glossary")
            or os.path.join(REPO, "knowledge", "glossary.json"))
BOOKS_DIR = (os.path.dirname((PROFILE or {}).get("book_config") or "")
             or os.path.join(REPO, "knowledge", "books"))
BOOK_ID = (os.environ.get("KL_BOOK_ID")
           or (PROFILE or {}).get("book_id")
           or _detect_book_id(BOOKS_DIR))
BOOK_CONFIG = ((PROFILE or {}).get("book_config")
               or (os.path.join(BOOKS_DIR, BOOK_ID + ".json") if BOOK_ID else ""))
BOOK_INDEX = (os.path.join(os.path.dirname(BOOK_CONFIG), BOOK_ID, "index.json")
              if BOOK_CONFIG and BOOK_ID else "")
MD_DIR = (PROFILE or {}).get("md") or os.environ.get("KL_BOOK_MD") or ""
PROBE_DIR = os.environ.get("KL_PROBE_DIR") or os.path.join(REPO, ".probe")
AGGREGATE = os.path.join(LEAN_ROOT, LIB + ".lean")
STRIP_PREFIXES = tuple((PROFILE or {}).get("strip_prefixes") or (NAMESPACE + ".",))

# 把推导结果回填环境变量：下游（bookindex 等）仍按 KL_* 读取，只有一个来源。
_ENV_DEFAULTS: dict[str, str] = {
    "KL_LEAN_ROOT": LEAN_ROOT,
    "KL_LEAN_LIB": LIB,
    "KL_LEAN_NAMESPACE": NAMESPACE,
    "KL_PROBE_DIR": PROBE_DIR,
    "KL_BOOK_ID": BOOK_ID,
}
_ENV_DEFAULTS.update({k: v for k, v in ((PROFILE or {}).get("env") or {}).items() if v})
for _k, _v in _ENV_DEFAULTS.items():
    if _v:
        os.environ.setdefault(_k, str(_v))


# ---------------------------------------------------------------- 路径辅助

def _same(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _pipeline_rel() -> str:
    """清单目录相对仓库根的路径（profile 自定义布局时也成立）。"""
    if PROFILE and (PROFILE.get("inventory") or ""):
        try:
            return os.path.relpath(PIPELINE_DIR, REPO)
        except ValueError:
            return "knowledge/pipeline"
    return os.path.join("knowledge", "pipeline")


PIPELINE_REL = _pipeline_rel()


def pipeline_dir(root: str | None = None) -> str:
    """`<root>/<清单目录>`；root 缺省或就是本仓库时用 profile 解析出的绝对路径。"""
    if not root:
        return PIPELINE_DIR
    root = os.path.abspath(root)
    if _same(root, REPO):
        return PIPELINE_DIR
    return os.path.normpath(os.path.join(root, PIPELINE_REL))


def aggregate(root: str | None = None) -> str:
    root = os.path.abspath(root or LEAN_ROOT)
    return os.path.join(root, LIB + ".lean")


def glossary_path(root: str | None = None) -> str:
    if not root:
        return GLOSSARY
    root = os.path.abspath(root)
    if _same(root, REPO):
        return GLOSSARY
    return os.path.join(root, "knowledge", "glossary.json")


def book_config_path(book: str | None = None) -> str:
    if book and PROFILE and book != PROFILE.get("book_id"):
        return os.path.join(BOOKS_DIR, book + ".json")
    return BOOK_CONFIG or os.path.join(BOOKS_DIR, (book or BOOK_ID) + ".json")


def book_index_path(book: str | None = None) -> str:
    cfg = book_config_path(book)
    bid = book or BOOK_ID
    return os.path.join(os.path.dirname(cfg), bid, "index.json") if bid else ""


def rel(path: str, base: str | None = None) -> str:
    try:
        return os.path.relpath(path, base or REPO).replace("\\", "/")
    except ValueError:
        return path


def summary() -> dict:
    """一处汇总（`kl config` / doctor 用）：当前解析出来的全部配置。"""
    return {
        "profile": PROFILE_PATH or "(未设置 KL_PROFILE：按仓库布局约定运行)",
        "profile_error": PROFILE_ERROR,
        "book_id": BOOK_ID,
        "repo": REPO,
        "lean_root": LEAN_ROOT,
        "lib": LIB,
        "namespace": NAMESPACE,
        "aggregate": AGGREGATE,
        "pipeline_dir": PIPELINE_DIR,
        "order_table": ORDER_TABLE,
        "base_table": BASE_TABLE,
        "base_candidate": BASE_CANDIDATE,
        "graph": GRAPH,
        "glossary": GLOSSARY,
        "book_config": BOOK_CONFIG,
        "book_index": BOOK_INDEX,
        "md": MD_DIR,
        "probe_dir": PROBE_DIR,
    }
