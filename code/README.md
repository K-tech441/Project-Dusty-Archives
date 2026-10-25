# 参考实现（`code/`）

这是「故纸堆」管线的**可运行参考实现**：判据引擎（Python）+ DSH 插件（JS）+ 一个真实实例的
配置样本。方案本身（为什么这么设计）在 [`../docs/`](../docs/)。

> 它是**参考实现**，不是开箱即用的产品：路径、解释器、Lean 工程都是按一个真实实例
> （Munkres《Topology》2e，§12–§19）校准的。换书 = 写一份 book pack + 改几行机器级配置
> （见 [docs/new-book.md](../docs/new-book.md) §8 与 [docs/plugin-api.md](../docs/plugin-api.md) §3）。

## 目录

```
engine/                 判据引擎（Python；判据的唯一实现）
  kl/                   MCP server + CLI + 判据 + 图 + 页码索引 + 术语表
  lean-probes/          Lean 侧探针（A/B 签名范围、I/R 结构边）
  lean-ilean-prune.py   mathlib .ilean 剪枝（LSP 内存优化，可选）
plugins/                DSH 插件（5 个）
  dsh-pipeline-core/    通用 core：流程契约注入 + pipeline_gate / pipeline_doctor
  dsh-mcp-kl/           知识层 MCP（kl_* 工具）
  dsh-mcp-lean/         Lean LSP MCP
  dsh-mcp-mathlib/      mathlib 本地索引 MCP
  dsh-graph-panel/      设置面板「知识图谱」
examples/munkres-2e/    实例 pack 样本：book-profile.json + 契约补充 + 书配置
```

## 依赖

| 层 | 需要 |
|---|---|
| 引擎 | Python ≥ 3.11；`mcp`（MCP server）；`pymupdf`（`figure` / `book-build`）；`pillow`（`viz`） |
| 插件 | Node ≥ 20 + DSH（提供 agent / 插件 / MCP 宿主） |
| 形式化 | Lean 4 + mathlib（实例工程自带 lakefile；引擎只调 `lake build` / `lean`） |

## 安装（要点）

1. 把 `plugins/` 里的 5 个目录接进你的 DSH profile（`plugin_manager` 安装，或 profile
   `package.json` 里加 `link:` 依赖 + bundles 列表），重启 DSH；
2. 实例仓库里写 `knowledge/book-profile.json`（字段见
   [docs/plugin-api.md](../docs/plugin-api.md) §3），从 `examples/munkres-2e/` 复制作起点；
3. 改各 MCP 面的**机器级配置**（python 解释器 / `PYTHONPATH` / Lean 项目路径 / mathlib 索引），
   可直接抄 `examples/munkres-2e/cordis.patch.yml`；
4. 重启 DSH；`pipeline_doctor` 两段全绿 = 安装成功。

## 验收（三条命令）

```bash
python -m kl.cli config    # 打印解析后的 书 id / 库名 / 清单目录 / 图 / 术语表 / 页码索引
python -m kl.cli doctor    # 体检：profile 路径 + 引擎产物（聚合/探针/.ilean/图/判重记录）
python -m kl.cli graph     # 四层边图 + 15 条机械断言
python -m kl.cli view      # 生成自包含的交互式原子图 HTML（交付物，可在预览侧栏打开）
```

## 版本口径

- core 契约 **v6**（`pipeline_doctor` 首行打印；契约在插件加载时固化，改完必须重启 DSH）
- `kl` 引擎 **v4.0.0**；pack schema `book-profile/v1`；书配置 `book-config/v1`
- 判据语义固定不可配（[docs/plugin-api.md](../docs/plugin-api.md) §4.1）；book pack 只能
  配参数、加只读扩展，**不能关判据**

## 不在这里的东西

- 教材 PDF / OCR 转录 / 实例 Lean 源码：属于具体实例的物料，不随本仓库分发（版权与体量）。
- 旧的两个「Munkres 专用」插件（`dsh-munkres-pipeline` / `dsh-munkres-prompt`）：内容已分别
  并入 `dsh-pipeline-core` 与实例 pack 的 `契约补充.md`，不再单独发布。

License: [MIT](../LICENSE)（文档与代码同）。
