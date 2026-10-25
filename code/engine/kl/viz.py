# -*- coding: utf-8 -*-
"""2D 可视化：把四层边图导出成 PNG / SVG / 自包含 HTML。

## 布局

```
纵轴 = 级次（亮节点之间的最长路径；0 在最下，越大越"基础"）
横轴 = 层内顺序（重心排序，尽量少交叉）
右侧 = 生成声明带（字段投影 / mk / rec …：是节点，但不属内容层，也没有 item 认领）
底部 = 基底带（mathlib + Init/Std：只标条数——它们被规范不变性商掉）
```

**颜色 = 认领它的清单条目（item）**。一条 declaration 可以被多条 item 认领
（节点粒度 ≠ 书的原子粒度；例如「拓扑」与「拓扑空间」都认领 `Topology`）——
这种点画成实心 + 黑圈。

边按层上色：A=签名（蓝）· B=值（浅灰）· I=induct→ctor（橙）· R=rec→all（绿）。

## 依赖

只依赖 PIL（PNG）；SVG / HTML 是纯文本。运行用**任何**有 PIL 的 Python：

    set PYTHONPATH=<repo>/tools
    python tools/kl/viz.py --png knowledge/pipeline/graph.png --html knowledge/pipeline/graph.html

数据源：现成的 `graph.json`（`--graph`），或现场 `kl.graph.build()`；
item 归属读 `knowledge/pipeline/sectionNN.json`（`--items-dir`）。
"""

from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kl import config, graph as G  # noqa: E402

PREFIX_STRIP = config.STRIP_PREFIXES
GEN_STRIP = (config.NAMESPACE + ".",)
LAYER_COLOR = {"A": "#2563eb", "B": "#d1d5db", "I": "#f59e0b", "R": "#10b981"}
ITEM_COLORS = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2",
               "#c026d3", "#65a30d", "#d97706", "#4f46e5", "#0d9488", "#be123c",
               "#7c3aed", "#a16207", "#1d4ed8", "#b45309"]
_CJK_FONTS = ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
              "C:/Windows/Fonts/simsun.ttc", "C:/Windows/Fonts/msyhbd.ttc")


def short(name: str) -> str:
    for p in PREFIX_STRIP:
        if name.startswith(p):
            return name[len(p):]
    return name


def short_gen(name: str) -> str:
    for p in GEN_STRIP:
        if name.startswith(p):
            return name[len(p):]
    return name


def _edge_color(layers: str) -> str:
    for ch in ("R", "I", "A", "B"):
        if ch in layers:
            return LAYER_COLOR[ch]
    return LAYER_COLOR["B"]


# ---------------------------------------------------------------- item 归属

def load_item_claims(pipeline_dir: str) -> dict[str, list[str]]:
    """声明全名 → 认领它的原子 item id（1:1：primary / derived / witness 三选一）。"""
    claims: dict[str, list[str]] = defaultdict(list)
    for p in sorted(glob.glob(os.path.join(pipeline_dir, "section*.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        for it in d.get("items") or []:
            lean = it.get("lean") or {}
            names: list[str] = []
            if lean.get("primary"):
                names.append(lean["primary"])
            for e in lean.get("derived") or []:
                if e.get("name"):
                    names.append(e["name"])
            for w in lean.get("witness") or []:
                if w.get("name"):
                    names.append(w["name"])
            for n in names:
                claims[n].append(str(it.get("id")))
    return dict(claims)


def item_color_map(claims: dict[str, list[str]]) -> dict[str, str]:
    ids: list[str] = []
    for ids_ in claims.values():
        for i in ids_:
            if i not in ids:
                ids.append(i)
    ids.sort()
    return {i: ITEM_COLORS[k % len(ITEM_COLORS)] for k, i in enumerate(ids)}


# ---------------------------------------------------------------- 布局

def layout(g: dict) -> dict:
    nodes = g["nodes"]
    bright = [n for n, v in nodes.items() if v["class"] == "ours" and not v.get("generated")]
    gen = [n for n, v in nodes.items() if v.get("generated")]
    tiers = g["tiers"]
    by_layer: dict[int, list[str]] = defaultdict(list)
    for n in bright:
        by_layer[tiers.get(n, 0)].append(n)
    max_layer = max(by_layer) if by_layer else 0

    order = {n: i for L in by_layer.values() for i, n in enumerate(L)}
    up = defaultdict(list)
    for e in g["edges"]:
        if e["src"] in order and e["dst"] in order:
            up[e["src"]].append(e["dst"])
    for _ in range(3):
        for L in sorted(by_layer):
            if L == 0:
                continue

            def bary(n: str) -> float:
                xs = [order[d] for d in up[n] if d in order and tiers.get(d, -1) < L]
                return (sum(xs) / len(xs)) if xs else float(order[n])

            by_layer[L].sort(key=bary)
            for i, n in enumerate(by_layer[L]):
                order[n] = i

    pos: dict[str, tuple[float, float]] = {}
    for L, lst in by_layer.items():
        for i, n in enumerate(lst):
            pos[n] = (float(i), float(L))
    width = max((len(v) for v in by_layer.values()), default=1)
    indeg = Counter(e["dst"] for e in g["edges"])
    gen.sort(key=lambda n: -indeg[n])
    n_gen = max(1, len(gen))
    for i, n in enumerate(gen):
        ylay = (max_layer * (n_gen - 1 - i) / (n_gen - 1)) if n_gen > 1 else max_layer / 2
        pos[n] = (width + 0.9, ylay)
    base_edges = sum(1 for e in g["edges"] if e["dst_class"] in ("mathlib", "gray"))
    return {"pos": pos, "bright": bright, "generated": gen, "by_layer": dict(by_layer),
            "width": width, "max_layer": max_layer, "base_edges": base_edges,
            "indeg": dict(indeg)}


# ---------------------------------------------------------------- PNG

def _font(path: str, size: int, cjk: bool):
    from PIL import ImageFont
    cands = (_CJK_FONTS if cjk else ("C:/Windows/Fonts/consola.ttf",) + _CJK_FONTS)
    for p in cands:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_png(g: dict, path: str, scale: int = 2,
               claims: dict[str, list[str]] | None = None,
               title: str | None = None,
               labels: dict[str, str] | None = None) -> str:
    from PIL import Image, ImageDraw

    claims = claims or {}
    icol = item_color_map(claims)
    lay = layout(g)
    pos, W, max_layer = lay["pos"], lay["width"], lay["max_layer"]
    CW, CH = 132 * scale, 116 * scale
    ML, MR, MB, MT = 96 * scale, 70 * scale, 128 * scale, 132 * scale
    width = int(ML + MR + (W + 2.4) * CW)
    height = int(MT + MB + (max_layer + 1) * CH)
    img = Image.new("RGB", (width, height), "white")
    dr = ImageDraw.Draw(img)
    f_small, f_tiny = _font("", 9, True), _font("", 8, True)
    f_title, f_node = _font("", 15, True), _font("", 10, True)

    def xy(name: str) -> tuple[float, float]:
        x, yl = pos[name]
        return (ML + x * CW + CW / 2, MT + (max_layer - yl) * CH + CH / 2)

    base_y = MT + (max_layer + 1) * CH - 18 * scale
    for e in g["edges"]:
        s, d = e["src"], e["dst"]
        if s not in pos:
            continue
        x1, y1 = xy(s)
        col = _edge_color(e["layers"])
        if d in pos:
            x2, y2 = xy(d)
            w = 2 * scale if ("A" in e["layers"] or "I" in e["layers"] or "R" in e["layers"]) else scale
            dr.line([x1, y1, x2, y2], fill=col, width=w)

    for name in lay["bright"]:
        x, y = xy(name)
        r = 11 * scale
        ids = claims.get(name) or []
        fill = icol.get(ids[0], "#1d4ed8") if ids else "#9ca3af"
        outline = "#111827" if len(ids) > 1 else fill
        dr.ellipse([x - r, y - r, x + r, y + r], fill=fill, outline=outline,
                   width=(2 * scale if len(ids) > 1 else 1))
        dr.text([x + r + 3 * scale, y - 6 * scale],
                (labels or {}).get(name) or short(name), fill="#111827", font=f_node)
    for name in lay["generated"]:
        x, y = xy(name)
        r = 7 * scale
        _ids = claims.get(name) or []
        _fill = icol.get(_ids[0], "#d97706") if _ids else "#d97706"
        dr.rectangle([x - r, y - r, x + r, y + r], fill=_fill, outline="#92400e")
        dr.text([x + r + 3 * scale, y - 5 * scale],
                (labels or {}).get(name) or short_gen(name), fill="#92400e",
                font=f_tiny)

    for L in range(max_layer + 1):
        y = MT + (max_layer - L) * CH + CH / 2
        dr.text([12 * scale, y - 8 * scale], f"级次 {L}", fill="#6b7280", font=f_small)
        dr.line([ML - 10 * scale, y, ML - 6 * scale, y], fill="#e5e7eb")

    dr.line([ML, base_y, width - MR, base_y], fill="#e5e7eb", width=scale)
    dr.text([ML, base_y + 8 * scale],
            f"基底（mathlib + Init/Std）：{lay['base_edges']} 条边 —— 只画桩，规范不变性会商掉",
            fill="#6b7280", font=f_small)
    dr.text([ML + (W + 0.55) * CW, MT - 26 * scale], "生成声明", fill="#92400e", font=f_small)

    st = g["stats"]
    lyr = st["edges"]["layers"]
    dr.text([ML, 14 * scale],
            title or "四层边图 · 节点 = 声明签名层 · 颜色 = 认领它的清单条目",
            fill="#111827", font=f_title)
    dr.text([ML, 42 * scale],
            f"亮节点 {st['nodes']['bright']} · 生成 {st['nodes']['generated']} · 边 {st['edges']['total']}"
            f" = A {lyr.get('A', 0)} · A∩B {lyr.get('AB', 0)} · B {lyr.get('B', 0)}"
            f" · I {lyr.get('I', 0)} · R {lyr.get('R', 0)} · 级次 max {st['tiers']['max']}",
            fill="#374151", font=f_small)
    x0, y0 = ML, 62 * scale
    for k, (iid, col) in enumerate(sorted(icol.items())):
        cx = x0 + (k % 8) * 108 * scale
        cy = y0 + (k // 8) * 18 * scale
        dr.ellipse([cx, cy, cx + 9 * scale, cy + 9 * scale], fill=col)
        dr.text([cx + 12 * scale, cy - 2 * scale], iid, fill="#374151", font=f_tiny)
    lx = x0 + 8 * 108 * scale
    for lab, col in (("A 签名", LAYER_COLOR["A"]), ("B 值", LAYER_COLOR["B"]),
                     ("I", LAYER_COLOR["I"]), ("R", LAYER_COLOR["R"])):
        dr.line([lx, 66 * scale, lx + 22 * scale, 66 * scale], fill=col, width=2 * scale)
        dr.text([lx + 25 * scale, 60 * scale], lab, fill="#374151", font=f_tiny)
        lx += 26 * scale

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    img.save(path)
    return path


# ---------------------------------------------------------------- SVG

def _svg_body(g: dict, lay: dict, claims: dict[str, list[str]] | None = None,
              cell=(150, 116), pad=(96, 60, 130, 108),
              title: str | None = None,
              labels: dict[str, str] | None = None,
              tips: dict[str, str] | None = None) -> tuple[str, int, int]:
    claims = claims or {}
    icol = item_color_map(claims)
    pos, W, max_layer = lay["pos"], lay["width"], lay["max_layer"]
    ML, MR, MB, MT = pad
    width = int(ML + MR + (W + 2.4) * cell[0])
    height = int(MT + MB + (max_layer + 1) * cell[1])

    def xy(name):
        x, yl = pos[name]
        return (ML + x * cell[0] + cell[0] / 2, MT + (max_layer - yl) * cell[1] + cell[1] / 2)

    base_y = MT + (max_layer + 1) * cell[1] - 14
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="0 0 {width} {height}" font-family="Consolas,Menlo,monospace">',
           f'<rect width="{width}" height="{height}" fill="white"/>']
    for e in g["edges"]:
        s, d = e["src"], e["dst"]
        if s not in pos:
            continue
        x1, y1 = xy(s)
        col = _edge_color(e["layers"])
        if d in pos:
            x2, y2 = xy(d)
            w = 2 if ("A" in e["layers"] or "I" in e["layers"] or "R" in e["layers"]) else 1
            dash = ' stroke-dasharray="5 5"' if e["layers"] == "B" else ""
            out.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                       f'stroke="{col}" stroke-width="{w}"{dash}/>')
    for name in lay["bright"]:
        x, y = xy(name)
        ids = claims.get(name) or []
        fill = icol.get(ids[0], "#1d4ed8") if ids else "#9ca3af"
        stroke = "#111827" if len(ids) > 1 else fill
        out.append(f'<g class="n" data-name="{(tips or {}).get(name, name)}">'
                   f'<circle cx="{x:.1f}" cy="{y:.1f}" r="10" fill="{fill}" '
                   f'stroke="{stroke}" stroke-width="{2 if len(ids) > 1 else 1}"/>'
                   f'<text x="{x + 14:.1f}" y="{y + 4:.1f}" font-size="11" fill="#111827">'
                   f'{(labels or {}).get(name) or short(name)}</text></g>')
    for name in lay["generated"]:
        x, y = xy(name)
        out.append(f'<g class="n" data-name="{(tips or {}).get(name, name)}">'
                   f'<rect x="{x - 6:.1f}" y="{y - 6:.1f}" width="12" height="12" fill="#d97706"/>'
                   f'<text x="{x + 11:.1f}" y="{y + 4:.1f}" font-size="10" fill="#92400e">'
                   f'{(labels or {}).get(name) or short_gen(name)}</text></g>')
    for L in range(max_layer + 1):
        y = MT + (max_layer - L) * cell[1] + cell[1] / 2
        out.append(f'<text x="10" y="{y + 4:.1f}" font-size="11" fill="#6b7280">级次 {L}</text>')
    out.append(f'<line x1="{ML}" y1="{base_y}" x2="{width - MR}" y2="{base_y}" stroke="#e5e7eb"/>')
    out.append(f'<text x="{ML}" y="{base_y + 16}" font-size="10" fill="#6b7280">'
               f'基底（mathlib + Init/Std）：{lay["base_edges"]} 条边 · 只画桩</text>')
    out.append(f'<text x="{ML + (W + 0.55) * cell[0]:.0f}" y="{MT - 8}" font-size="10" '
               f'fill="#92400e">生成声明</text>')
    st = g["stats"]
    lyr = st["edges"]["layers"]
    out.append(f'<text x="{ML}" y="24" font-size="15" fill="#111827">'
               f'{title or "四层边图"} · 亮 {st["nodes"]["bright"]} · 生成 {st["nodes"]["generated"]} · '
               f'边 {st["edges"]["total"]} · 级次 max {st["tiers"]["max"]}</text>')
    out.append(f'<text x="{ML}" y="42" font-size="11" fill="#374151">'
               f'A {lyr.get("A", 0)} · A∩B {lyr.get("AB", 0)} · B {lyr.get("B", 0)} · '
               f'I {lyr.get("I", 0)} · R {lyr.get("R", 0)} · 颜色 = 清单条目（实心黑圈 = 被多条认领）'
               f'</text>')
    x0, y0 = ML, 62
    for k, (iid, col) in enumerate(sorted(icol.items())):
        cx = x0 + (k % 8) * 108
        cy = y0 + (k // 8) * 18
        out.append(f'<circle cx="{cx + 4}" cy="{cy + 4}" r="5" fill="{col}"/>')
        out.append(f'<text x="{cx + 14}" y="{cy + 8}" font-size="10" fill="#374151">{iid}</text>')
    out.append("</svg>")
    return "\n".join(out), width, height


def render_svg(g: dict, path: str, claims: dict[str, list[str]] | None = None,
               title: str | None = None, labels: dict[str, str] | None = None,
               tips: dict[str, str] | None = None) -> str:
    svg, _w, _h = _svg_body(g, layout(g), claims, title=title, labels=labels, tips=tips)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(svg + "\n")
    return path


# ---------------------------------------------------------------- HTML

_HTML = """<!doctype html>
<html lang="zh"><meta charset="utf-8">
<title>四层边图</title>
<style>
 body{margin:0;background:#f8fafc;font:13px/1.5 Consolas,monospace;color:#111827}
 #bar{position:fixed;top:0;left:0;right:0;padding:6px 12px;background:#fff;
      border-bottom:1px solid #e5e7eb;z-index:9}
 #wrap{position:absolute;top:37px;left:0;right:0;bottom:0;overflow:hidden;cursor:grab}
 svg{transform-origin:0 0}
 .n{cursor:pointer}
 #tip{position:fixed;background:#111827;color:#fff;padding:4px 8px;border-radius:4px;
      font-size:12px;display:none;z-index:99;pointer-events:none}
</style>
<div id="bar">四层边图 · 滚轮缩放 · 拖动平移 · 悬停看节点全名（颜色 = 清单条目）</div>
<div id="wrap"><!--SVG--></div>
<div id="tip"></div>
<script>
const wrap=document.getElementById('wrap'),svg=wrap.querySelector('svg'),tip=document.getElementById('tip');
let k=1,tx=0,ty=0,drag=null;
function apply(){svg.style.transform=`translate(${tx}px,${ty}px) scale(${k})`}
wrap.addEventListener('wheel',e=>{e.preventDefault();
  const f=e.deltaY<0?1.12:1/1.12,mx=e.clientX,my=e.clientY-37;
  tx=mx-(mx-tx)*f;ty=my-(my-ty)*f;k*=f;apply();},{passive:false});
wrap.addEventListener('mousedown',e=>{drag=[e.clientX-tx,e.clientY-ty];wrap.style.cursor='grabbing'});
window.addEventListener('mousemove',e=>{if(drag){tx=e.clientX-drag[0];ty=e.clientY-drag[1];apply()}});
window.addEventListener('mouseup',()=>{drag=null;wrap.style.cursor='grab'});
svg.querySelectorAll('[data-name]').forEach(el=>{
  el.addEventListener('mousemove',e=>{tip.style.display='block';tip.textContent=el.dataset.name;
    tip.style.left=(e.clientX+12)+'px';tip.style.top=(e.clientY+12)+'px'});
  el.addEventListener('mouseleave',()=>{tip.style.display='none'});
});
apply();
</script></html>
"""


def render_html(g: dict, path: str, claims: dict[str, list[str]] | None = None,
                title: str | None = None, labels: dict[str, str] | None = None,
                tips: dict[str, str] | None = None) -> str:
    svg, _w, _h = _svg_body(g, layout(g), claims, title=title, labels=labels, tips=tips)
    html = _HTML.replace("<!--SVG-->", svg)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    return path


# ---------------------------------------------------------------- 原子视图（书的图）

STATUS_COLOR = {"verified": "#1d4ed8", "partial": "#f59e0b", "todo": "#9ca3af"}


def atom_view(g: dict, atoms: dict) -> tuple[dict, dict, str, str, dict, dict]:
    """把原子图包装成渲染器认的形状：todo 原子进「尚未落地」带。

    返回 (view, claims, title, sub, labels, tips)：
      labels = 图上写的简写标签（清单的 label）
      tips   = 悬停全文（id · label —— statement）
    """
    ag = G.atom_graph(g, atoms)
    nodes = {}
    labels: dict[str, str] = {}
    tips: dict[str, str] = {}
    for iid, v in ag["nodes"].items():
        nodes[iid] = {"class": "ours", "generated": v["status"] == "todo",
                      "status": v["status"], "kind": v["kind"],
                      "book_ref": v["book_ref"], "primary": v["primary"],
                      "label": v.get("label", ""), "statement": v.get("statement", "")}
        labels[iid] = v.get("label") or iid
        stmt = v.get("statement") or ""
        tips[iid] = f"{iid} · {labels[iid]}" + (f" —— {stmt}" if stmt else "")
    st = ag["stats"]
    view = {
        "nodes": nodes, "edges": ag["edges"], "tiers": ag["tiers"],
        "stats": {"nodes": {"bright": st["atoms"]["total"] - st["atoms"]["todo"],
                            "generated": st["atoms"]["todo"]},
                  "edges": {"total": st["edges"]["total"],
                            "layers": st["edges"]["layers"]},
                  "tiers": {"max": st["tiers"]["max"]}},
    }
    # 颜色按状态（同一个「id」= 状态 ⟹ item_color_map 给出每种状态一色）
    claims = {iid: [v["status"]] for iid, v in nodes.items()}
    ok = st["atoms"]["verified"]
    sub = (f"原子 {st['atoms']['total']}：verified {ok} · partial {st['atoms']['partial']}"
           f" · todo {st['atoms']['todo']} · 原子边 {st['edges']['total']}"
           f" · 外部边（→基底/生成）{st['ext_edges']}")
    return (view, claims, "书的原子图 · 节点 = 一个原子（一个定义 / 一条命题）", sub,
            labels, tips)


# ---------------------------------------------------------------- CLI

def load_any(graph_json: str = "") -> dict:
    if graph_json and os.path.isfile(graph_json):
        with open(graph_json, encoding="utf-8") as f:
            d = json.load(f)
        return {"nodes": d["nodes"], "edges": d["edges"], "tiers": d["tiers"],
                "stats": d["stats"], "modules": d["meta"]["modules"],
                "root": d["meta"]["root"], "lib": d["meta"]["lib"],
                "sig": d["meta"]["sig"], "struct": d["meta"]["struct"]}
    return G.build()


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="viz", description="四层边图的 2D 导出")
    ap.add_argument("--png", default=os.path.join(config.PIPELINE_DIR, "graph.png"))
    ap.add_argument("--svg", default="")
    ap.add_argument("--html", default="")
    ap.add_argument("--graph", default="", help="用现成的 graph.json（空 = 现场 build）")
    ap.add_argument("--items-dir", default=config.PIPELINE_DIR,
                    help="清单目录（原子 ↔ 声明 1:1 归属）")
    ap.add_argument("--mode", choices=("atom", "decl"), default="atom",
                    help="atom = 书的原子图（默认）；decl = 声明层图（实现细节）")
    a = ap.parse_args(argv)
    g = load_any(a.graph)
    if a.mode == "atom":
        atoms = G.load_atoms(a.items_dir)
        view, claims, title, sub, labels, tips = atom_view(g, atoms)
        print(f"# {title}\n# {sub}", file=sys.stderr)
        print(render_png(view, a.png, claims=claims, title=title, labels=labels))
        if a.svg:
            print(render_svg(view, a.svg, claims=claims, title=title,
                             labels=labels, tips=tips))
        if a.html:
            print(render_html(view, a.html, claims=claims, title=title,
                              labels=labels, tips=tips))
        return 0
    claims = load_item_claims(a.items_dir) if os.path.isdir(a.items_dir) else {}
    if claims:
        all_ids = {i for ids in claims.values() for i in ids}
        bright = sum(1 for n, v in g["nodes"].items()
                     if v["class"] == "ours" and not v.get("generated"))
        claimed = sum(1 for n, v in g["nodes"].items()
                      if v["class"] == "ours" and not v.get("generated") and n in claims)
        multi = sum(1 for n, ids in claims.items() if len(ids) > 1)
        print(f"# 声明图：{len(all_ids)} 个原子 · 内容层节点被认领 {claimed}/{bright}"
              f" · 被多条认领的节点 {multi}", file=sys.stderr)
    print(render_png(g, a.png, claims=claims))
    if a.svg:
        print(render_svg(g, a.svg, claims=claims))
    if a.html:
        print(render_html(g, a.html, claims=claims))
    return 0


if __name__ == "__main__":
    sys.exit(main())
