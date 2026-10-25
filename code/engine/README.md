# engine — 判据引擎（`kl`）

**判据的唯一实现**：所有「真」只在这里判定——build / 无 sorry 与公理白名单 / 基底禁提 /
陈述层基底范围 / 判重 / quote 逐字 / module 卫生。插件与 MCP 只是壳，grep 与临时脚本不是判据。

## 模块

| 文件 | 作用 |
|---|---|
| `config.py` | 运行期配置（`KL_PROFILE` → 书 id / 库名 / 命名空间 / 清单目录 / 图 / 页码索引 / 库外资源）；`kl config` 打印结果 |
| `model.py` | 清单 schema 3（每节 `sectionNN.json`；未知键保留，加字段不会读挂旧清单） |
| `checks.py` | 判据 + 收口审计 + 体检（doctor）+ 指针 + 基底范围 + 模块卫生 |
| `bookindex.py` | 书配置 → 页码索引（每节五坐标：中译印/PDF、英文印/PDF、md 页） |
| `figures.py` | PDF 页渲染 + 矢量图机械解码（不靠眼睛读扫描件） |
| `graph.py` | 图：声明层四层边（A/B/I/R）+ 按清单折叠的原子图 + 15 条断言 |
| `glossary.py` | 术语表（术语 → 章节/原子/Lean/清单指针，长程记忆） |
| `mcp.py` | MCP server（`kl_*` 工具） |
| `cli.py` | 命令行（与 MCP 同一实现，打印 JSON） |
| `viz.py` | 2D 图导出（PNG / SVG / HTML） |

`lean-probes/` 是 Lean 侧探针：`DeclSigRanges.lean`（A/B 签名范围）、`StructEdges.lean`
（I/R 结构边）、`ContentSupport.lean`（基底候选生成）。图的四层边全部由它们提供数据。

## 放置位置

两种放法都行：

- **按布局约定**：把 `kl/` 放进实例仓库的 `tools/kl/`（`lean-probes/` 放 `tools/lean-probes/`），
  仓库根由引擎文件位置自动推出，不需要 `KL_PROFILE`；
- **放在任意位置**：设 `KL_PROFILE=<实例仓库>/knowledge/book-profile.json`，仓库与所有路径
  都由 profile 解析——本仓库的 `code/engine/` 就是这种放法（不依赖自身位置）。

## 安装与运行

```bash
pip install mcp pymupdf pillow        # 按用途裁剪：mcp=MCP server；pymupdf=figure/book-build；pillow=viz
export PYTHONPATH=<实例仓库>/tools    # kl 包所在目录；Windows 用分号分隔
export KL_PROFILE=<实例仓库>/knowledge/book-profile.json

python -m kl.cli config               # 先确认配置解析对了（排障第一站）
python -m kl.cli doctor               # 14 项体检
python -m kl.cli sections             # 有哪些节的清单
python -m kl.cli check 19 --with-dup  # 四判据 + 判重（不 --update 就只报不改）
python -m kl.cli graph                # 图 + 断言
```

CLI 子命令：`sections · doctor · config · stats · next · status · book · book-build ·
book-locate · init · check · quote-check · audit · link · figure · graph · sync-root ·
probes · fix-headers · new-module · glossary`（`python -m kl.cli <cmd> --help`）。

## 配置优先级

`环境变量 > KL_PROFILE（book-profile.json）> 仓库布局约定/探测`。

没有 `KL_PROFILE` 时按布局约定运行：仓库根由 `tools/kl` 的位置推出，库名从
`lakefile.toml` 的 `[[lean_lib]] name` 探测，书 id 从 `knowledge/books/` 唯一一本探测，
清单目录默认 `knowledge/pipeline`。也就是说：**旧实例不写 profile 也能跑，一般化是可选的**。

## 测试台

`plugins/dsh-pipeline-core/test/check.mjs` 是一个离线测试台：profile 结构校验的正/负向用例、
apply 同步性、契约拼装（core 无书名硬编码）、以及真跑一次 `pipeline_gate` / `pipeline_doctor`
（跑完用 git 恢复被刷新的 verdict 与聚合文件）。

```bash
KL_PROFILE=<你的 profile> KL_TEST_SECTION=<某个已完成节> node plugins/dsh-pipeline-core/test/check.mjs
```
