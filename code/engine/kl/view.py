# -*- coding: utf-8 -*-
"""`kl view`：把 graph.json 渲染成一个**自包含**的交互式 HTML（交付物）。

为什么是"自包含"：
- 用户在 Harness 侧边栏预览交付物 / 双击打开时，file:// 下 fetch 常被 CORS 拦；
- 内联 force-graph 与数据（~300 KB）后，单个 HTML 文件即可离线交互（悬停/搜索/图层过滤）。

模板：`tools/kl/graph_view.html`（占位符 `__FORCE_GRAPH__` / `__GRAPH_DATA__`）；
依赖：`tools/kl/vendor/force-graph.min.js`（vendored，MIT）。
"""
from __future__ import annotations

import json
import os

from kl import config

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "graph_view.html")
VENDOR = os.path.join(HERE, "vendor", "force-graph.min.js")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def payload(graph_path: str | None = None) -> dict:
    path = graph_path or config.GRAPH
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    keep = {
        "meta": doc.get("meta"),
        "stats": doc.get("stats"),
        "atom_graph": doc.get("atom_graph") or {},
    }
    if not keep["atom_graph"]:
        raise ValueError(f"{path} 里没有 atom_graph：先跑 kl graph --json <path>")
    return keep


def render(out: str | None = None, graph_path: str | None = None) -> dict:
    """生成单文件 HTML；默认写到 graph.json 同目录的 graph-view.html。"""
    if not os.path.isfile(TEMPLATE):
        return {"ok": False, "error": f"缺模板：{TEMPLATE}"}
    if not os.path.isfile(VENDOR):
        return {"ok": False, "error": f"缺 vendored force-graph：{VENDOR}"}
    try:
        data = payload(graph_path)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"读图数据失败：{exc}"}

    tpl = _read(TEMPLATE)
    fg = _read(VENDOR)
    # 防止 JSON 里的 `</script` 提前闭合（数据里几乎不会有，但保险）
    data_js = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = tpl.replace("__FORCE_GRAPH__", fg).replace("__GRAPH_DATA__", data_js)

    target = out or os.path.join(os.path.dirname(graph_path or config.GRAPH), "graph-view.html")
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(html)
    return {
        "ok": True,
        "written": target,
        "bytes": len(html.encode("utf-8")),
        "atoms": len(data["atom_graph"].get("nodes") or {}),
        "edges": len(data["atom_graph"].get("edges") or []),
        "note": "双击打开，或在 Harness 里作为交付物预览（自包含，无外部依赖）",
    }
