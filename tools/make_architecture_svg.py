# -*- coding: utf-8 -*-
"""生成 Project Dusty Archives 的总架构图（SVG，零依赖）。

用法：python tools/make_architecture_svg.py
产物：docs/assets/architecture.svg

设计目标：一张图能同时回答三件事
  1) 数据从 PDF 流到面板经过哪些层、每层产出什么文件；
  2) agent 编排与质量门禁是横切的，不属于任何单一层；
  3) 哪些接口/区域**尚未描述清楚**（红色虚线框 G1–G5），便于补齐文档。

图例：矩形=产物(artifact) · 圆角=过程(process) · 菱形/橙色=门禁(gate)
      实线=数据流 · 虚线=派生/重算 · 红虚线框=文档缺口
"""
import os

W, H = 1780, 1340
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "docs", "assets", "architecture.svg")

# 配色
C_ART = ("#eef3fb", "#4a6fa5")     # artifact
C_PROC = ("#eaf6ec", "#3f7f4f")    # process
C_GATE = ("#fdf1e3", "#b07a2a")    # gate
C_SRC = ("#f6eef6", "#7a4a7a")     # external source
C_RAIL = ("#f4f4f4", "#777777")    # cross-cutting rail
C_GAP = ("#fff0f0", "#cc3333")     # documentation gap
C_INK = "#222222"
C_EDGE = "#555555"
C_DASH = "#888888"


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def text(x, y, s, size=13, weight="normal", anchor="middle", fill=C_INK):
    return ('<text x="%d" y="%d" font-size="%d" font-weight="%s" '
            'text-anchor="%s" fill="%s" font-family="Segoe UI, Microsoft YaHei, sans-serif">%s</text>'
            % (x, y, size, weight, anchor, fill, esc(s)))


def box(x, y, w, h, title, lines=None, kind=C_ART, dashed=False):
    fill, stroke = kind
    dash = ' stroke-dasharray="6,4"' if dashed else ""
    out = ['<rect x="%d" y="%d" width="%d" height="%d" rx="8" fill="%s" stroke="%s" '
           'stroke-width="1.6"%s/>' % (x, y, w, h, fill, stroke, dash)]
    cx = x + w // 2
    ty = y + 22 if lines else y + h // 2 + 5
    out.append(text(cx, ty, title, 13, "bold"))
    for i, ln in enumerate(lines or []):
        out.append(text(cx, ty + 18 * (i + 1), ln, 11.5, "normal", fill="#444444"))
    return "\n".join(out)


def arrow(x1, y1, x2, y2, dashed=False, label=None, lx=None, ly=None):
    dash = ' stroke-dasharray="7,5"' if dashed else ""
    out = ['<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="1.8"%s '
           'marker-end="url(#ah)"/>' % (x1, y1, x2, y2, C_EDGE if not dashed else C_DASH, dash)]
    if label:
        lx = lx if lx is not None else (x1 + x2) // 2
        ly = ly if ly is not None else (y1 + y2) // 2 - 6
        out.append(text(lx, ly, label, 11, "normal", fill="#666666"))
    return "\n".join(out)


def rail(x, y, w, h, title, items):
    fill, stroke = C_RAIL
    out = ['<rect x="%d" y="%d" width="%d" height="%d" rx="10" fill="%s" stroke="%s" '
           'stroke-width="1.2"/>' % (x, y, w, h, fill, stroke)]
    out.append(text(x + w // 2, y + 24, title, 13, "bold", fill="#555555"))
    for i, it in enumerate(items):
        out.append(text(x + 12, y + 52 + 19 * i, it, 11.5, "normal", anchor="start", fill="#555555"))
    return "\n".join(out)


def svg():
    o = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">' % (W, H, W, H),
         '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
         'orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="%s"/></marker></defs>' % C_EDGE,
         '<rect width="100%" height="100%" fill="white"/>',
         text(W // 2, 40, "Project Dusty Archives（项目：故纸堆）· 总架构", 22, "bold"),
         text(W // 2, 64, "PDF 教材 → 逐页转录 → 原子清单 → Lean 库（指针）→ 判据 → 图 → 面板", 13, "normal", fill="#666666")]

    # ---------------- 左侧：agent 编排横切
    o.append(rail(18, 100, 232, 860, "L7 Agent 编排（横切）", [
        "Lead：裁决 / 写作用域 / 提交",
        "worker：一节一模块",
        "  R 侦察 → 停 → 批准",
        "  W 一次一个原子",
        "  收口三步",
        "契约注入（每次调用）",
        "任务书（只写本节特例）",
        "工具证据（四类计数）",
        "停止条件（卡即停）",
        "LSP 工具面：",
        "  goal / multi_attempt",
        "  search / diagnostics",
        "MCP：kl / lean / mathlib",
        "本地 mathlib 索引 430k",
    ]))

    # ---------------- 右侧：质量与回归横切
    o.append(rail(1530, 100, 232, 860, "L8 质量与回归（横切）", [
        "pipeline_doctor（开工）",
        "  13 项体检 / 全绿才开工",
        "pipeline_gate（收口）",
        "  指针 / 判据 / 双向覆盖",
        "新鲜度链：",
        "  源码→olean/ilean",
        "  →探针→图",
        "基底变更规程 + 全量回归",
        "verdict 来源记录",
        "  origin/session/pid/argv",
        "生成物 vs 手工物分离",
        "git 提交纪律",
        "回归矩阵（待建 G5）",
    ]))

    # ---------------- 主区 x: 278..1500
    X0, X1 = 278, 1500

    # 行 1：输入
    y = 100
    o.append(box(X0, y, 190, 74, "PDF 教材", ["扫描件 / 文字层", "页码：印刷页↔PDF页"], C_SRC))
    o.append(box(X0 + 220, y, 190, 74, "书配置", ["PDF 路径 / 页码偏移", "章节边界 / 语言"], C_SRC))
    o.append(box(X0 + 440, y, 200, 74, "页码索引", ["book-index", "机械生成, 只读"], C_ART))
    o.append(box(X0 + 680, y, 250, 74, "G1 书配置 schema", ["字段/校验/多书共存放哪", "（文档未定）"], C_GAP, dashed=True))
    o.append(arrow(X0 + 190, y + 37, X0 + 218, y + 37))
    o.append(arrow(X0 + 410, y + 37, X0 + 438, y + 37, label="偏移"))
    o.append(arrow(X0 + 540, y + 74, X0 + 540, y + 110, label=""))

    # 行 2：转录
    y = 210
    o.append(box(X0 + 250, y, 240, 90, "VLM-OCR 转录", ["逐页：p####.md", "保留 LaTeX / 图 / 脚注"], C_PROC))
    o.append(box(X0 + 520, y, 210, 90, "逐页 Markdown", ["文件名 = PDF 页号", "★ 页码对齐的锚"], C_ART))
    o.append(box(X0 + 760, y, 230, 90, "G2 OCR 可复现性", ["模型版本/提示词/重跑", "抽检记录（文档未定）"], C_GAP, dashed=True))
    o.append(arrow(X0 + 190 + 30, y - 46, X0 + 250 + 30, y - 10, label="PDF 页"))
    o.append(arrow(X0 + 490, y + 45, X0 + 518, y + 45))
    o.append(arrow(X0 + 730, y + 45, X0 + 758, y + 45, dashed=True, label="校验"))

    # 行 3：原子化
    y = 350
    o.append(box(X0 + 20, y, 380, 120, "原子清单 sectionNN.json  ★ 单一事实源", [
        "原子 = 定义 / 定理 / 编号例子",
        "quote 逐字 · statement 中文 · loc",
        "identity_decl · carrier_deps",
        "lean: names / pointers / status",
    ], C_ART))
    o.append(box(X0 + 430, y, 230, 120, "入序表", ["章节依赖 / 状态", "done:SectionN"], C_ART))
    o.append(box(X0 + 690, y, 290, 96, "原子口径（书级配置）", ["哪些元素开原子", "partial 条件 / 例子规则"], C_SRC))
    o.append(box(X0 + 20, y + 132, 380, 84, "术语表", ["术语 → 原子 → 声明", "跨节检索（派生视图）"], C_ART))
    o.append(arrow(X0 + 400, y + 60, X0 + 428, y + 60))
    o.append(arrow(X0 + 428, y + 110, X0 + 402, y + 110, dashed=True, label="派生"))

    # 行 4：形式化
    y = 620
    o.append(box(X0 + 20, y, 210, 110, "基底", ["Base.lean（唯一 mathlib 入口）", "基底清单 / A 层范围"], C_ART))
    o.append(box(X0 + 260, y, 280, 110, "内容模块 SectionNN.lean", ["一节一模块", "声明 + 证明（B 层自由）"], C_ART))
    o.append(box(X0 + 570, y, 210, 110, "指针", ["module + 位置 + 签名哈希", "不复制源码"], C_ART))
    o.append(box(X0 + 810, y, 190, 110, "LSP 工具面", ["goal / multi_attempt", "search / diagnostics"], C_PROC))
    o.append(arrow(X0 + 230, y + 55, X0 + 258, y + 55, label="public import"))
    o.append(arrow(X0 + 540, y + 55, X0 + 568, y + 55, label="登记"))
    o.append(arrow(X0 + 780, y + 55, X0 + 808, y + 55, dashed=True, label="迭代"))

    # 行 5：判据
    y = 800
    o.append(box(X0 + 20, y, 360, 120, "判据检查器（唯一实现）", [
        "① build  ② sorry + 公理白名单",
        "③a 基底禁提  ③a′ A 层范围",
        "③b 判重  ③c quote 逐字  ④ 模块卫生",
    ], C_GATE))
    o.append(box(X0 + 420, y, 210, 120, "探针", ["ilean 位置索引", "签名哈希 / 结构边"], C_PROC))
    o.append(box(X0 + 670, y, 230, 120, "verdict", ["绿色/红色 + 原因", "来源记录（谁跑的）"], C_ART))
    o.append(arrow(X0 + 380, y + 60, X0 + 418, y + 60, dashed=True, label="读清单"))
    o.append(arrow(X0 + 630, y + 60, X0 + 668, y + 60))
    o.append(arrow(X0 + 400, y - 70, X0 + 400, y - 8, label="编译产物 / 探针输入"))

    # 行 6：图
    y = 990
    o.append(box(X0 + 20, y, 300, 118, "声明图", ["节点 = 声明（签名层）", "边 = A/B/I/R 四层", "基底为灰节点"], C_ART))
    o.append(box(X0 + 360, y, 280, 118, "原子图", ["一原子一节点", "输入：清单 + 声明图折叠"], C_ART))
    o.append(box(X0 + 680, y, 240, 118, "断言", ["覆盖 / 幻影 / 守恒", "级次 / 折叠（机械）"], C_GATE))
    o.append(arrow(X0 + 320, y + 59, X0 + 358, y + 59, label="折叠"))
    o.append(arrow(X0 + 640, y + 59, X0 + 678, y + 59, label="每次导出"))

    # 行 7：呈现
    y = 1170
    o.append(box(X0 + 360, y, 280, 90, "Web 面板", ["缩放 / 拖拽 / 搜索", "声明视图 ⇄ 原子视图"], C_PROC))
    o.append(box(X0 + 680, y, 240, 90, "导出 / 报告", ["graph.json / 统计", "术语表 / 进度"], C_ART))
    o.append(arrow(X0 + 500, y - 62, X0 + 500, y - 8))
    o.append(box(X0 + 950, y, 250, 90, "G4 插件一般化接口", ["pipeline-core / book 拆分", "（文档未定）"], C_GAP, dashed=True))

    # 缺口 G3 / G5
    o.append(box(X0 + 1000, 350, 220, 96, "G3 多书共存布局", ["目录/命名/跨书引用", "（文档未定）"], C_GAP, dashed=True))
    o.append(box(X0 + 1200, 990, 200, 118, "G5 评估指标", ["覆盖率/verified 比例", "人工干预/成本", "（文档未定）"], C_GAP, dashed=True))

    # 图例
    y = 1310
    o.append(text(X0 + 20, y, "图例：矩形=产物 · 圆角=过程 · 橙色=门禁 · 紫=外部输入 · 实线=数据流 · 虚线=派生/重算 · 红虚线框=文档缺口", 12, "normal", anchor="start", fill="#666666"))
    o.append("</svg>")
    return "\n".join(x for x in o if x)


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(svg())
    print("wrote", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()
