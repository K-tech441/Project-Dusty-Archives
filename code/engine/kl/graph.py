# -*- coding: utf-8 -*-
"""四层边图导出 + 断言。

## 数据源（全部机械，全部源码侧）

```
.ilean           声明集合 + 人写提及（源码里人写的那一层）
.probe/decl_sig_ranges.json   签名的源码范围（parse-only 导出）⟹ A/B 切分
.probe/struct_edges.json      olean 结构字段 ⟹ I/R 层
```

**不用 olean 的 `ci.type` / `ci.value?` 取 A/B**：那是 elaborate 后的项，
混着实例展开、notation 展开、tactic 细节、自动生成的 `_proof_N`（实测量级差 7 倍）。

## 口径（唯一事实源：docs/工程基准.md）

```
节点   = 声明（.ilean 的 decls）+ 被提及到的声明（references）
边     = 提及，四层：A=signature · B=value · I=induct→ctor · R=rec→all
分类   ours（本库声明）· generated（本库模块里的生成声明：投影/mk/rec/…）
       mathlib（基底层）· gray（Init/Std/Lean）
亮节点 = ours（内容层）；级次只在亮节点之间算（灰/生成节点 = 0，边被商掉）
```

## 断言（`assertions()`，每次导出都跑）

```
freshness    探针产物 mtime 晚于最新源文件 / 最新 .ilean（源码改了没重跑探针 = 静默错分）
coverage     签名范围覆盖的模块 == 聚合文件模块数；条数 == 声明数
ghosts       每个模块都有源文件（不能从 .lake 枚举到已删模块）
conservation A+B−A∩B = 提及边数；I+R = 结构边数；总边 = 两者之并
boundary     0 个 usage 起点恰好等于 sigStop
comments     0 个 usage 落在注释里（字节级扫描；字符索引与 UTF-8 字节不可混用）
tiers        亮节点子图无环；每条亮→亮边的级次严格下降
```
"""

from __future__ import annotations

import io
import json
import os
import re
from collections import Counter, defaultdict
from typing import Any

from kl import checks, config

# ---------------------------------------------------------------- .ilean

_BLOCK = re.compile(r"/-.*?-/", re.S)


def ilean_path(module: str, dirs: list[str]) -> str | None:
    rel = module.replace(".", os.sep) + ".ilean"
    for d in dirs:
        p = os.path.join(d, rel)
        if os.path.isfile(p):
            return p
    return None


def load_ilean(module: str, dirs: list[str]) -> dict[str, Any]:
    p = ilean_path(module, dirs)
    if p is None:
        raise FileNotFoundError(f"找不到 .ilean：{module}（先 lake build）")
    with io.open(p, encoding="utf-8") as f:
        return json.load(f)


def _ref_name(key: str) -> tuple[str, str]:
    """references 的 key 是 compress 过的 JSON：{"c":{"m":模块,"n":名字}}。"""
    inner = json.loads(key)
    for tag, (mk, nk) in (("c", ("m", "n")), ("f", ("m", "i"))):
        if tag in inner and isinstance(inner[tag], dict):
            d = inner[tag]
            return d.get(mk, "?"), d.get(nk, "?")
    raise ValueError(f"未知的 RefIdent tag：{key!r}")


def declared_of(module: str, dirs: list[str]) -> dict[str, list[int]]:
    """模块的声明 → .ilean 给的 (起始行, 起始列, …)（LSP 0-based）。"""
    d = load_ilean(module, dirs)
    return dict(d.get("decls") or {})


def references_of(module: str, dirs: list[str]) -> dict[str, dict[str, Any]]:
    """模块 → {常量全名: {module: 定义所在模块, usages: [(l1,c1,l2,c2,host)]}}。

    只含【人显式写下】的引用：`usages` 是 4 或 5 元组，4 元 = 引用本身是声明（无宿主）。
    """
    d = load_ilean(module, dirs)
    out: dict[str, dict[str, Any]] = {}
    for key, val in (d.get("references") or {}).items():
        defmod, name = _ref_name(key)
        usages = [tuple(u) for u in (val.get("usages") or []) if len(u) == 5]
        out[name] = {"module": defmod, "usages": usages}
    return out


# ---------------------------------------------------------------- 探针产物

def load_sig_ranges(path: str) -> dict[str, Any]:
    """{模块: {(cmdStartLine, cmdStartCol): (sigStart, sigStop)}}。"""
    if not os.path.isfile(path):
        return {"modules": [], "by_module": {}, "raw": None}
    with io.open(path, encoding="utf-8") as f:
        doc = json.load(f)
    by_mod: dict[str, dict[tuple[int, int], tuple[dict, dict]]] = defaultdict(dict)
    for e in doc.get("decls") or []:
        cs, ss, se = e["cmdStart"], e["sigStart"], e["sigStop"]
        by_mod[e["module"]][(int(cs["line"]), int(cs["col"]))] = (ss, se)
    return {"modules": sorted(by_mod), "by_module": dict(by_mod),
            "files": doc.get("files"), "count": len(doc.get("decls") or []),
            "mtime": os.path.getmtime(path), "raw": doc}


def load_struct_edges(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        return {"edges": [], "inductives": 0, "recursors": 0, "mtime": 0.0, "ran": False}
    with io.open(path, encoding="utf-8") as f:
        doc = json.load(f)
    return {"edges": [dict(e) for e in doc.get("struct_edges") or []],
            "inductives": int(doc.get("inductives") or 0),
            "recursors": int(doc.get("recursors") or 0),
            "our_constants": int(doc.get("our_constants") or 0),
            "mtime": os.path.getmtime(path), "ran": True}


# ---------------------------------------------------------------- 模块与源文件

_IMPORT = re.compile(r"^public import (\w+(?:\.\w+)*)", re.M)


def modules_from_aggregate(root: str, lib: str = config.LIB) -> list[str]:
    agg = os.path.join(root, lib + ".lean")
    if not os.path.isfile(agg):
        raise FileNotFoundError(f"聚合文件不存在：{agg}")
    with io.open(agg, encoding="utf-8") as f:
        text = f.read()
    mods = [m.group(1) for m in _IMPORT.finditer(text)]
    return [m for m in mods if m.split(".")[0] == lib]


def source_file(root: str, module: str, lib: str = config.LIB) -> str:
    parts = module.split(".")
    return os.path.join(root, lib, *parts[1:]) + ".lean"


# ---------------------------------------------------------------- 签名范围对齐

def _in_sig(l: int, c: int, sig: tuple[dict, dict]) -> bool:
    ss, se = sig
    p = (l, c)
    return (int(ss["line"]), int(ss["col"])) <= p < (int(se["line"]), int(se["col"]))


def _sig_of(decls: dict[str, list[int]], sigs: dict[tuple[int, int], Any],
            host: str) -> tuple[dict, dict] | None:
    """用 cmdStart 的 (行,列) 与 .ilean 的 decls 对齐 → 该声明的 sig 范围。"""
    a = decls.get(host)
    if not a or len(a) < 2:
        return None
    return sigs.get((int(a[0]), int(a[1])))


# ---------------------------------------------------------------- 分类

def class_of_module(module: str, lib: str) -> str:
    if not module or module == "?":
        return "unknown"
    if module.split(".")[0] == lib:
        return "ours"
    if module.startswith("Mathlib"):
        return "mathlib"
    return "gray"


# ---------------------------------------------------------------- 构图

def build(root: str | None = None, lib: str = config.LIB,
          probe_dir: str | None = None, modules: list[str] | None = None,
          ilean_dirs: list[str] | None = None) -> dict[str, Any]:
    root = root or checks.DEFAULT_LEAN_ROOT
    probe = probe_dir or checks.PROBE_DIR
    dirs = ilean_dirs or checks.ilean_dirs()
    mods = modules or modules_from_aggregate(root, lib)
    sig = load_sig_ranges(os.path.join(probe, "decl_sig_ranges.json"))
    struct = load_struct_edges(os.path.join(probe, "struct_edges.json"))

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    # ① 本库声明 = 节点（.ilean decls + 源码扫描补集：ilean 会漏记「不提及任何常量」的声明）
    decls_of: dict[str, dict[str, list[int]]] = {}
    for m in mods:
        decls_of[m] = declared_of(m, dirs)
        for name, pos in checks._source_decls(root, m).items():
            decls_of[m].setdefault(name, [pos["line"], pos["col"]])
        for name in decls_of[m]:
            nodes[name] = {"class": "ours", "module": m, "generated": False}

    # ② A/B 层边（人写提及按签名位置切分）
    mention_pairs: set[tuple[str, str]] = set()
    for m in mods:
        sigs = sig["by_module"].get(m) or {}
        for name, info in references_of(m, dirs).items():
            cls = class_of_module(str(info["module"]), lib)
            nodes.setdefault(name, {"class": cls, "module": info["module"],
                                    "generated": cls == "ours"})
            for (l1, c1, _l2, _c2, host) in info["usages"]:
                if host == name:
                    continue                       # 自环不算
                if host not in decls_of.get(m, {}):
                    continue                       # 宿主必须是我们声明的节点
                s = _sig_of(decls_of[m], sigs, host)
                layer = "A" if (s is not None and _in_sig(l1, c1, s)) else "B"
                mention_pairs.add((host, name))
                edges.append({"src": host, "dst": name, "layer": layer,
                              "dst_class": cls})

    # ③ I/R 层边（结构字段；★ 不按「src 是否本库声明」过滤 —— rec 是生成声明）
    raw_struct = 0
    for e in struct["edges"]:
        src, dst, layer = e.get("src"), e.get("dst"), e.get("layer")
        if not src or not dst or layer not in ("I", "R"):
            continue
        raw_struct += 1
        nodes.setdefault(src, {"class": "ours", "module": None,
                               "generated": src not in nodes})
        nodes.setdefault(dst, {"class": "ours", "module": None,
                               "generated": dst not in nodes})
        edges.append({"src": src, "dst": dst, "layer": layer, "dst_class": "ours"})

    # 自己的模块里、但不在 decls 里的 ours 节点 = 生成声明（投影/mk/rec/…）
    declared = set()
    for d in decls_of.values():
        declared |= set(d)
    for n, v in nodes.items():
        if v["class"] == "ours" and n not in declared:
            v["generated"] = True

    # 去重（同一条边可能命中多层）
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for e in edges:
        k = (e["src"], e["dst"])
        if k in merged:
            merged[k]["layers"].add(e["layer"])
        else:
            merged[k] = {"src": e["src"], "dst": e["dst"],
                         "layers": {e["layer"]}, "dst_class": e["dst_class"]}
    edge_list = [{"src": v["src"], "dst": v["dst"],
                  "layers": "".join(sorted(v["layers"])),
                  "dst_class": v["dst_class"]} for v in merged.values()]
    edge_list.sort(key=lambda e: (e["src"], e["dst"]))

    g = {"root": root, "lib": lib, "modules": mods,
         "nodes": nodes, "edges": edge_list,
         "raw_mention_edges": len(mention_pairs),
         "sig": {"modules": sig["modules"], "count": sig.get("count", 0),
                 "mtime": sig.get("mtime", 0.0)},
         "struct": {"inductives": struct["inductives"], "recursors": struct["recursors"],
                    "edges": len(struct["edges"]), "mtime": struct["mtime"],
                    "ran": struct["ran"]},
         "raw_struct_edges": raw_struct,
         "decls": decls_of}
    g["tiers"] = tiers(g)
    g["stats"] = stats(g)
    return g


# ---------------------------------------------------------------- 级次

def tiers(g: dict[str, Any]) -> dict[str, int]:
    """亮节点（ours，不含生成声明）之间的最长路径；出边全在亮集外者为 0。"""
    nodes = g["nodes"]
    bright = {n for n, v in nodes.items() if v["class"] == "ours" and not v.get("generated")}
    adj: dict[str, list[str]] = defaultdict(list)
    for e in g["edges"]:
        if e["src"] in bright and e["dst"] in bright:
            adj[e["src"]].append(e["dst"])
    t: dict[str, int] = {}
    state: dict[str, int] = {}          # 1 = 在栈上，2 = 已完成

    def visit(u: str) -> int:
        st = state.get(u)
        if st == 2:
            return t[u]
        if st == 1:                      # 环：按 0 处理并继续（断言里会报）
            return 0
        state[u] = 1
        best = 0
        for v in adj.get(u, []):
            best = max(best, visit(v) + 1)
        state[u] = 2
        t[u] = best
        return best

    for n in bright:
        visit(n)
    return t


# ---------------------------------------------------------------- 统计

def stats(g: dict[str, Any]) -> dict[str, Any]:
    nodes, edges, t = g["nodes"], g["edges"], g["tiers"]
    cls = Counter(v["class"] for v in nodes.values())
    gen = sum(1 for v in nodes.values() if v.get("generated"))
    layers = Counter(e["layers"] for e in edges)
    dst = Counter(e["dst_class"] for e in edges)
    abl = Counter()
    for e in edges:
        for ch in e["layers"]:
            abl[f"{ch}/{e['dst_class']}"] += 1
    tdist = Counter(t.values())
    bright = [n for n, v in nodes.items() if v["class"] == "ours" and not v.get("generated")]
    a_total = sum(1 for e in edges if "A" in e["layers"])
    a_ours = sum(1 for e in edges if "A" in e["layers"] and e["dst_class"] == "ours")
    b_total = sum(1 for e in edges if "B" in e["layers"])
    b_ours = sum(1 for e in edges if "B" in e["layers"] and e["dst_class"] == "ours")
    return {
        "nodes": {"total": len(nodes), "ours": cls["ours"], "generated": gen,
                  "mathlib": cls["mathlib"], "gray": cls["gray"],
                  "bright": len(bright)},
        "edges": {"total": len(edges), "layers": dict(sorted(layers.items())),
                  "by_dst": dict(sorted(dst.items())),
                  "by_layer_dst": dict(sorted(abl.items()))},
        "content_self_sufficiency": {
            "A": (a_ours / a_total) if a_total else None, "A_counts": [a_ours, a_total],
            "B": (b_ours / b_total) if b_total else None, "B_counts": [b_ours, b_total],
            "note": "★ 这不是「纯度」。它只说明签名/值里的提及有多少落在内容层（其余落在基底）。"
                    "纯度的机械判据是判据③a（禁止清单零提及），不是这个比值。"},
        "tiers": {"distribution": dict(sorted(tdist.items())),
                  "max": max(t.values()) if t else 0},
    }


# ---------------------------------------------------------------- 断言

def _comment_columns(path: str) -> list[list[tuple[int, int]]]:
    """每行的注释字节列区间（字节级：.ilean 的列是 UTF-8 字节偏移）。"""
    with open(path, "rb") as f:
        data = f.read()
    lines = data.split(b"\n")
    out: list[list[tuple[int, int]]] = [[] for _ in lines]
    in_block = False
    for i, line in enumerate(lines):
        j, n = 0, len(line)
        while j < n:
            if in_block:
                k = line.find(b"-/", j)
                if k < 0:
                    out[i].append((j, n))
                    j = n
                else:
                    out[i].append((j, k + 2))
                    j = k + 2
                    in_block = False
            else:
                k1 = line.find(b"--", j)
                k2 = line.find(b"/-", j)
                cands = [(k, t) for k, t in ((k1, b"--"), (k2, b"/-")) if k >= 0]
                if not cands:
                    break
                k, t = min(cands)
                if t == b"--":
                    out[i].append((k, n))
                    break
                out[i].append((k, k + 2))
                j = k + 2
                in_block = True
    return out


def assertions(g: dict[str, Any], probe_dir: str | None = None,
               root: str | None = None) -> list[dict[str, Any]]:
    probe = probe_dir or checks.PROBE_DIR
    root = root or g["root"]
    lib = g["lib"]
    res: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: Any) -> None:
        res.append({"assert": name, "ok": bool(ok), "detail": detail})

    # freshness
    src_files = [source_file(root, m, lib) for m in g["modules"]]
    src_mtimes = [os.path.getmtime(p) for p in src_files if os.path.isfile(p)]
    newest_src = max(src_mtimes) if src_mtimes else 0.0
    ileans = []
    for m in g["modules"]:
        p = ilean_path(m, checks.ilean_dirs())
        if p:
            ileans.append(os.path.getmtime(p))
    newest_ilean = max(ileans) if ileans else 0.0
    base = max(newest_src, newest_ilean)
    add("freshness.sig", g["sig"]["mtime"] >= base,
        {"sig_mtime": g["sig"]["mtime"], "newest_src": newest_src,
         "newest_ilean": newest_ilean})
    add("freshness.struct", (not g["struct"]["ran"]) or g["struct"]["mtime"] >= base,
        {"struct_mtime": g["struct"]["mtime"], "newest_src": newest_src,
         "newest_ilean": newest_ilean})

    # coverage / ghosts
    agg = modules_from_aggregate(root, lib)
    # 只有【有声明】的模块才会在探针输出里出现（Base 只有 imports ⟹ 无条目是正常的）
    mods_with_decls = [m for m in g["modules"] if g["decls"].get(m)]
    add("coverage.modules",
        sorted(g["sig"]["modules"]) == sorted(mods_with_decls)
        and set(g["sig"]["modules"]) <= set(agg),
        {"sig_modules": g["sig"]["modules"],
         "modules_with_decls": mods_with_decls, "aggregate": agg})
    n_decl = sum(len(d) for d in g["decls"].values())
    add("coverage.sig_entries", g["sig"]["count"] == n_decl,
        {"DECLS_WITH_SIG": g["sig"]["count"], "declarations": n_decl})
    missing = [m for m in g["modules"] if not os.path.isfile(source_file(root, m, lib))]
    add("ghosts.modules", not missing, {"no_source": missing})

    # conservation
    total = len(g["edges"])
    a_only = sum(1 for e in g["edges"] if e["layers"] == "A")
    b_only = sum(1 for e in g["edges"] if e["layers"] == "B")
    ab = sum(1 for e in g["edges"] if set(e["layers"]) == {"A", "B"})
    mention_edges = sum(1 for e in g["edges"] if set(e["layers"]) & {"A", "B"})
    struct_in_graph = sum(1 for e in g["edges"] if set(e["layers"]) & {"I", "R"})
    a_has, b_has = a_only + ab, b_only + ab
    add("conservation.A_B", a_has + b_has - ab == mention_edges,
        {"A_only": a_only, "B_only": b_only, "A∩B": ab,
         "A含": a_has, "B含": b_has, "mention_edges": mention_edges})
    add("conservation.mentions_vs_ilean", mention_edges == g["raw_mention_edges"],
        {"mention_edges": mention_edges, "raw_mention_pairs": g["raw_mention_edges"]})
    add("conservation.I_R", struct_in_graph == g["raw_struct_edges"],
        {"struct_edges_in_probe": g["raw_struct_edges"],
         "struct_edges_in_graph": struct_in_graph})
    add("conservation.total", total == mention_edges + struct_in_graph,
        {"total": total, "mention": mention_edges, "struct": struct_in_graph})

    # precision: boundary & comments
    boundary = 0
    in_comment = 0
    checked = 0
    for m in g["modules"]:
        src = source_file(root, m, lib)
        cols = _comment_columns(src) if os.path.isfile(src) else []
        for _name, info in references_of(m, checks.ilean_dirs()).items():
            for (l1, c1, _l2, _c2, _host) in info["usages"]:
                checked += 1
                if 0 <= l1 < len(cols):
                    for (a, b) in cols[l1]:
                        if a <= c1 < b:
                            in_comment += 1
                            break
    # 边界：usage 起点恰好等于某个 sigStop 的条数（边界歧义）
    sig_doc = load_sig_ranges(os.path.join(probe, "decl_sig_ranges.json"))
    stops = {(m, int(se["line"]), int(se["col"]))
             for m, d in sig_doc["by_module"].items() for _k, (_ss, se) in d.items()}
    for m in g["modules"]:
        for _name, info in references_of(m, checks.ilean_dirs()).items():
            for (l1, c1, _l2, _c2, _host) in info["usages"]:
                if (m, l1, c1) in stops:
                    boundary += 1
    add("precision.boundary", boundary == 0, {"usages_at_sigStop": boundary})
    add("precision.comments", in_comment == 0,
        {"usages_in_comments": in_comment, "usages_checked": checked})

    # tiers
    bright = {n for n, v in g["nodes"].items()
              if v["class"] == "ours" and not v.get("generated")}
    viol = [{"src": e["src"], "dst": e["dst"]}
            for e in g["edges"]
            if e["src"] in bright and e["dst"] in bright
            and g["tiers"].get(e["src"], 0) <= g["tiers"].get(e["dst"], 0)]
    add("tiers.monotone", not viol, {"violations": viol[:10]})

    # 原子图（声明 → 书的原子商图）：折叠不丢边 + verified 原子必有 primary + 边有层。
    # 这段以前只在 viz.py 里用；2026-10-25 起 graph.json 也导出原子图（前端主视图 = 原子视图），
    # 断言因此并入 kl graph（否则导出物没有判据保护）。
    try:
        atoms = load_atoms(config.pipeline_dir(root))
        if atoms["items"]:
            res.extend(atom_assertions(atom_graph(g, atoms), g, atoms))
    except Exception as exc:  # 清单缺失不该让整张图的断言崩
        add("atom.fold", False, {"error": str(exc)})
    return res


# ---------------------------------------------------------------- 原子图（书的图）

def load_atoms(pipeline_dir: str) -> dict[str, Any]:
    """清单 → {items: {id: meta}, by_decl: {声明: 原子 id}}。

    归属是 1:1 的：每条声明只出现在一个原子的 primary / derived / witness 里
    （由 `kl_audit` 的 mapping 断言保证）。
    """
    import glob
    items: dict[str, dict[str, Any]] = {}
    by_decl: dict[str, str] = {}
    kind_of: dict[str, str] = {}
    for p in sorted(glob.glob(os.path.join(pipeline_dir, "section*.json"))):
        try:
            with io.open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        for it in d.get("items") or []:
            lean = it.get("lean") or {}
            iid = str(it.get("id"))
            items[iid] = {"id": iid, "kind": it.get("kind", ""),
                          "status": lean.get("status", ""),
                          "book_ref": it.get("book_ref", ""),
                          "label": it.get("label", ""),
                          "statement": it.get("statement", ""),
                          "primary": lean.get("primary") or "",
                          "decls": []}
            n = lean.get("primary") or ""
            if n:
                by_decl[n] = iid
                kind_of[n] = "primary"
                items[iid]["decls"].append(n)
            for e in lean.get("derived") or []:
                if e.get("name"):
                    by_decl[e["name"]] = iid
                    kind_of[e["name"]] = "derived"
                    items[iid]["decls"].append(e["name"])
            for w in lean.get("witness") or []:
                if w.get("name"):
                    by_decl[w["name"]] = iid
                    kind_of[w["name"]] = "witness"
                    items[iid]["decls"].append(w["name"])
    return {"items": items, "by_decl": by_decl, "kind_of": kind_of}


def atom_graph(g: dict[str, Any], atoms: dict[str, Any]) -> dict[str, Any]:
    """把声明图商成【书的原子图】：节点 = 原子，边 = 声明间提及经原子归属折叠。

    - 端点都归属到原子的边 ⟹ 原子边（层取并集；同原子自环丢弃）
    - 指向基底/生成声明的边 ⟹ 记为该原子的「外部边」计数（不进图）
    """
    by_decl = atoms["by_decl"]
    kind_of = atoms.get("kind_of") or {}
    nodes: dict[str, dict[str, Any]] = {}
    for iid, meta in atoms["items"].items():
        nodes[iid] = {"class": "ours", "generated": False, "id": iid,
                      "kind": meta["kind"], "status": meta["status"],
                      "book_ref": meta["book_ref"], "primary": meta["primary"],
                      "label": meta.get("label", ""),
                      "statement": meta.get("statement", ""),
                      "decls": meta["decls"]}
    ext: Counter = Counter()
    merged: dict[tuple[str, str], set[str]] = {}
    for e in g["edges"]:
        a = by_decl.get(e["src"])
        b = by_decl.get(e["dst"])
        if a is None:
            continue
        # ★ 书的图只用【陈述层】的声明发边：primary（原子本身）+ witness（部分见证）
        #   派生声明（bridge/aux/alias）是仪器 ⟹ 不发边（否则会造出书上没有的边，
        #   例如公理桥 IsOpen.empty 会把「拓扑」和「开集」连上两次）
        if kind_of.get(e["src"]) == "derived":
            continue
        if b is None:
            ext[a] += 1
            continue
        if a == b:
            continue
        merged.setdefault((a, b), set()).update(e["layers"])
    edges = [{"src": a, "dst": b, "layers": "".join(sorted(ls)),
              "dst_class": "atom"} for (a, b), ls in merged.items()]
    edges.sort(key=lambda e: (e["src"], e["dst"]))
    ag = {"nodes": nodes, "edges": edges, "ext_edges": dict(ext),
          "decl_graph": g}
    ag["tiers"] = tiers(ag)
    lyr = Counter(e["layers"] for e in edges)
    st = Counter(v["status"] for v in nodes.values())
    ag["stats"] = {
        "atoms": {"total": len(nodes), "verified": st["verified"],
                  "partial": st["partial"], "todo": st["todo"],
                  "with_decls": sum(1 for v in nodes.values() if v["decls"])},
        "edges": {"total": len(edges), "layers": dict(sorted(lyr.items()))},
        "ext_edges": sum(ext.values()),
        "tiers": {"max": max(ag["tiers"].values()) if ag["tiers"] else 0,
                  "distribution": dict(sorted(Counter(ag["tiers"].values()).items()))},
    }
    return ag


def atom_assertions(ag: dict[str, Any], g: dict[str, Any],
                    atoms: dict[str, Any]) -> list[dict[str, Any]]:
    """原子图的断言：折叠没丢东西 + 归属一致。"""
    res: list[dict[str, Any]] = []
    by_decl = atoms["by_decl"]
    content_edges = sum(1 for e in g["edges"]
                        if e["src"] in by_decl and e["dst"] in by_decl)
    res.append({"assert": "atom.fold", "ok": len(ag["edges"]) <= content_edges,
                "detail": {"atom_edges": len(ag["edges"]),
                           "decl_content_edges": content_edges}})
    bad = [v["id"] for v in ag["nodes"].values()
           if v["status"] == "verified" and not v["primary"]]
    res.append({"assert": "atom.verified_primary", "ok": not bad, "detail": {"bad": bad}})
    empty = [e for e in ag["edges"] if not e["layers"]]
    res.append({"assert": "atom.edge_layers", "ok": not empty,
                "detail": {"empty": len(empty)}})
    return res


# ---------------------------------------------------------------- 导出

def export(g: dict[str, Any], path: str) -> str:
    # 相对路径一律按【仓库根】解析（2026-10-25 坑：MCP server 的 cwd 不是仓库根，相对路径会
    # 静默写到 profile 目录，仓库 graph.json 不变 ⟹ doctor 报图数据陈旧）。
    if not os.path.isabs(path):
        path = os.path.join(str(g.get("root") or "."), path)
    # 原子图（声明 → 原子商图）：前端主视图是「一个节点一个原子」，声明图只是切回去的细节层。
    atom_doc = None
    try:
        atoms = load_atoms(config.pipeline_dir(str(g["root"])))
        if atoms["items"]:
            ag = atom_graph(g, atoms)
            atom_doc = {"nodes": ag["nodes"], "edges": ag["edges"],
                        "tiers": ag["tiers"], "stats": ag["stats"],
                        "ext_edges": ag.get("ext_edges") or {}}
    except Exception:
        atom_doc = None
    doc = {
        "meta": {"root": g["root"], "lib": g["lib"], "modules": g["modules"],
                 "sig": g["sig"], "struct": g["struct"],
                 "atom_view": "atom_graph = 声明图按清单折叠到书的原子（1 节点 = 1 原子）；"
                              "顶层 nodes/edges 是声明级细节图"},
        "stats": g["stats"],
        "nodes": g["nodes"],
        "edges": g["edges"],
        "tiers": g["tiers"],
    }
    if atom_doc is not None:
        doc["atom_graph"] = atom_doc
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return path
