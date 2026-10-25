# -*- coding: utf-8 -*-
"""kl —— 形式化管线（知识层）v4：从书页到可检查 Lean 库与可视图。

设计来自 2026-10-24 的 §12 试运行（278 行 Lean + 12 条清单，烧掉 27.4M token 换来的教训）。
与旧管线 `mpipe`（历史残留）的差别，一条一行：

```
① 页码结构化      book = {zh:{printed,pdf}, en:{printed,pdf}, md}，不再是一行自由字符串
                  （§12 里页码口径混过三次：中译印刷页 / 英文印刷页 / PDF 页 / md 转录页）
② 判据③ 换范围    判重 = 【基底 + 自库内部】；不再对 mathlib 内容层判重（hub 出局）
③ 新增 ③a         我们的模块【提及】了禁止清单里的 mathlib 名字 ⟹ 直接失败（.ilean references）
④ 新增 audit      清单 ↔ Lean 声明的【双向】覆盖 + 必填字段空值检查（防漏登记/幽灵条目）
⑤ 新增 figure     图解码固化（矢量：SVG 子路径 + 点在多边形内）—— §12 最贵的一课
⑥ 判据结果入档    verdict 由机器写进清单（何时跑的、build 秒数、sorry/axioms/③a 结论）
⑦ 去掉 prompt     提示词模板没被用到；去掉 trace（超时且历史残留）
```

模块分工（与 mpipe 相同的三层，但判据只有一处实现）：

    config.py   运行期配置（KL_PROFILE → 书 id / 库名 / 路径；唯一配置来源）
    model.py    清单 schema 3（容忍未知键 ⟹ 加字段不会把旧清单读挂）
    checks.py   四判据 + audit + 书目定位（唯一实现）
    figures.py  图的渲染与机械解码
    mcp.py      MCP 薄壳（LLM 用：一次调用 → 结构化 JSON）
    cli.py      命令行薄壳（人用 / 批处理）

★ 为什么是 MCP：CLI 要拼命令、起进程、解析 stdout；而「边查边改」要的是
  一次调用 → 结构化结果 → 判断 → 下一次调用。MCP 正是这个形状（旧管线已验证）。
"""

__version__ = "4.0.0"
