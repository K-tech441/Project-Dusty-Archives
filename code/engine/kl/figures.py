# -*- coding: utf-8 -*-
"""kl 图/页工具：**机械解码**矢量图，而不是靠眼睛抄。

## 为什么（2026-10-24 §12 的教训）

书上的图（例：图 12.1 九格 / 图 12.2 两族）只有图、没有文字。早期先靠眼睛读扫描件，
再靠眼睛读英文页 —— 两轮都可能读错，而且贵（一张图一次调用）。
真正的做法是**算**：PDF 里每个 blob 是一条真实矢量路径，点是填充小方块，
用点在多边形内测试就能无歧义地得出「每个 blob 含哪几个点」。

## 两个必须踩过的坑

1. **别数位图**：`page.get_images()` 只数 `/Subtype /Image`（位图）。
   矢量图是内容流的路径算子，**不产生 Image 对象** ⟹ 只数位图会误判「这一页没有图」。
   判据是 `get_drawings()` / SVG 的子路径数。
2. **别用 `get_drawings()` 解图**：它把**多个子路径合并**成一条 path（丢子路径边界），
   解不出「每个圈是哪个开集」。用 `get_svg_image()`：SVG 里每个子路径是独立的 "M … Z"。
   另外 SVG 有全局变换 `matrix(1,0,0,-1,14.4,777.6)`（y 翻转），必须应用后才能和文字坐标比。

## 依赖

需要 `pymupdf`。它装在 **`D:/pylibs`**（2026-10-24，abI3 wheel，不占 C 盘），
所以 MCP 的 bundle 配置把 `D:/pylibs` 也放进了 `PYTHONPATH`；
命令行跑时同样要 `PYTHONPATH=<repo>/tools;<pymupdf 目录>`。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

FLATTEN = 32          # 贝塞尔折线化段数
DOT_MAX = 4.5         # 「点」的方块边长上限（pt）


def _pymupdf():
    try:
        import pymupdf  # noqa: PLC0415
    except ImportError as e:  # noqa: BLE001
        raise RuntimeError(
            "缺 pymupdf。用 MCP 工具（venv 里有），或命令前设 PYTHONPATH=D:\\pylibs"
        ) from e
    return pymupdf


# ---------------------------------------------------------------- 页级统计

def page_stats(pdf_path: str, page_no: int) -> dict[str, Any]:
    """位图数 / 矢量路径数 —— 用来自证「这一页到底有没有图」。"""
    pymupdf = _pymupdf()
    doc = pymupdf.open(pdf_path)
    page = doc[page_no - 1]
    return {"pdf": pdf_path, "page": page_no,
            "images": len(page.get_images(full=True)),
            "drawings": len(page.get_drawings())}


def render_page(pdf_path: str, page_no: int, out_png: str,
                dpi: int = 200, clip: list[float] | None = None) -> dict[str, Any]:
    """渲染一页（可只渲一块）。clip = [x0,y0,x1,y1] 比例坐标 0~1。"""
    pymupdf = _pymupdf()
    doc = pymupdf.open(pdf_path)
    page = doc[page_no - 1]
    r = page.rect
    rect = None
    if clip:
        x0, y0, x1, y1 = clip
        rect = pymupdf.Rect(r.x0 + x0 * r.width, r.y0 + y0 * r.height,
                            r.x0 + x1 * r.width, r.y0 + y1 * r.height)
    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, clip=rect)
    pix.save(out_png)
    return {"pdf": pdf_path, "page": page_no, "out": out_png,
            "size": [pix.width, pix.height], "dpi": dpi,
            "drawings": len(page.get_drawings()),
            "images": len(page.get_images(full=True))}


# ---------------------------------------------------------------- SVG 解析

def parse_svg_paths(svg: str) -> list[list[tuple[float, float]]]:
    """SVG → 每个 M…Z 子路径一个折线点列。"""
    out: list[list[tuple[float, float]]] = []
    for m in re.finditer(r"<path\b([^>]*)>", svg):
        dm = re.search(r'\bd="([^"]*)"', m.group(1))
        if not dm:
            continue
        tokens = re.findall(r"[MLCZmlczHVhv]|-?\d+\.?\d*(?:[eE]-?\d+)?", dm.group(1))
        poly: list[tuple[float, float]] = []
        cur = (0.0, 0.0)
        j = 0

        def num(k: int) -> float:
            return float(tokens[k])

        while j < len(tokens):
            t = tokens[j]
            if t == "M":
                if poly:
                    out.append(poly)
                cur = (num(j + 1), num(j + 2))
                poly = [cur]
                j += 3
                while j + 1 < len(tokens) and tokens[j] not in "MLCZHVmlczhv":
                    cur = (num(j), num(j + 1))
                    poly.append(cur)
                    j += 2
            elif t == "L":
                j += 1
                while j + 1 < len(tokens) and tokens[j] not in "MLCZHVmlczhv":
                    cur = (num(j), num(j + 1))
                    poly.append(cur)
                    j += 2
            elif t == "H":
                j += 1
                while j < len(tokens) and tokens[j] not in "MLCZHVmlczhv":
                    cur = (num(j), cur[1])
                    poly.append(cur)
                    j += 1
            elif t == "V":
                j += 1
                while j < len(tokens) and tokens[j] not in "MLCZHVmlczhv":
                    cur = (cur[0], num(j))
                    poly.append(cur)
                    j += 1
            elif t == "C":
                j += 1
                while j + 5 < len(tokens) and tokens[j] not in "MLCZHVmlczhv":
                    p1 = (num(j), num(j + 1))
                    p2 = (num(j + 2), num(j + 3))
                    p3 = (num(j + 4), num(j + 5))
                    for k in range(1, FLATTEN + 1):
                        s = k / FLATTEN
                        ms = 1 - s
                        poly.append((
                            ms**3 * cur[0] + 3 * ms**2 * s * p1[0] + 3 * ms * s**2 * p2[0] + s**3 * p3[0],
                            ms**3 * cur[1] + 3 * ms**2 * s * p1[1] + 3 * ms * s**2 * p2[1] + s**3 * p3[1],
                        ))
                    cur = p3
                    j += 6
            elif t in "Zz":
                j += 1
            else:
                j += 1
        if poly:
            out.append(poly)
    return out


def _bbox(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _inside(poly, pt) -> bool:
    """奇偶规则点内测试。"""
    x, y = pt
    n, hit = len(poly), False
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xin:
                hit = not hit
    return hit


def _cluster(vals: list[float], gap: float) -> list[list[int]]:
    idx = sorted(range(len(vals)), key=lambda i: vals[i])
    groups = [[idx[0]]]
    for a, b in zip(idx, idx[1:]):
        if vals[b] - vals[a] > gap:
            groups.append([b])
        else:
            groups[-1].append(b)
    return groups


# ---------------------------------------------------------------- 解码

def decode_page(pdf_path: str, page_no: int, out_json: str | None = None) -> dict[str, Any]:
    """把一页图上的【格子 → 开集族】解出来。

    返回 cells: [{index, labels, open_sets}]，其中 open_sets 是「除 ∅ 外」的开集，
    每个开集用所含点的字母集合表示（如 ["a","b"]）。外圈（整页最大的 blob）= X。
    """
    pymupdf = _pymupdf()
    doc = pymupdf.open(pdf_path)
    page = doc[page_no - 1]
    svg = page.get_svg_image()

    polys = parse_svg_paths(svg)
    tf = re.search(r'transform="matrix\(([-\d.,eE ]+)\)"', svg)
    if tf:
        a, b, c, d, e, f = (float(v) for v in tf.group(1).split(","))
        polys = [[(a * x + c * y + e, b * x + d * y + f) for x, y in p] for p in polys]

    dots, blobs = [], []
    for poly in polys:
        if len(poly) < 3:
            continue
        x0, y0, x1, y1 = _bbox(poly)
        if (x1 - x0) <= DOT_MAX and (y1 - y0) <= DOT_MAX:
            dots.append(((x0 + x1) / 2, (y0 + y1) / 2))
        else:
            blobs.append((poly, (x0, y0, x1, y1)))

    cells = []
    if dots:
        rows = _cluster([d[1] for d in dots], 20)
        for rg in rows:
            sub = [dots[i] for i in rg]
            for cg in _cluster([d[0] for d in sub], 25):
                pts = sorted((sub[i] for i in cg), key=lambda p: p[0])
                cells.append([(p, "abc"[k] if k < 3 else f"?{k}") for k, p in enumerate(pts)])

    # 去重（fill+stroke 常给出同一 bbox 两条子路径）
    seen, uniq = set(), []
    for poly, (x0, y0, x1, y1) in blobs:
        key = (round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1))
        if key in seen:
            continue
        seen.add(key)
        uniq.append((poly, (x0, y0, x1, y1)))

    out_cells = []
    for ci, cell in enumerate(cells):
        xs = [p[0] for p, _ in cell]
        ys = [p[1] for p, _ in cell]
        fam = []
        for poly, r in uniq:
            if r[2] < min(xs) - 25 or r[0] > max(xs) + 25:
                continue
            if r[3] < min(ys) - 25 or r[1] > max(ys) + 25:
                continue
            ins = tuple(t for p, t in cell if _inside(poly, p))
            if ins:
                fam.append(list(ins))
        fam = sorted({tuple(x) for x in fam}, key=lambda s: (len(s), s))
        out_cells.append({
            "index": ci,
            "labels": "".join(t for _, t in cell),
            "open_sets": ["".join(s) if len(s) < 3 else "abc" for s in fam],
        })

    result = {
        "pdf": pdf_path, "page": page_no,
        "images": len(page.get_images(full=True)),
        "drawings": len(page.get_drawings()),
        "subpaths": len(polys), "dots": len(dots), "blobs": len(uniq),
        "cells": out_cells,
        "note": ("open_sets 里每一项是除 ∅ 以外的开集；空串表示 X（外圈）；"
                 "字母是 PDF 里的 a/b/c 标签位置落的"),
    }
    if out_json:
        os.makedirs(os.path.dirname(os.path.abspath(out_json)), exist_ok=True)
        with open(out_json, "w", encoding="utf-8", newline="\n") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
            f.write("\n")
    return result
