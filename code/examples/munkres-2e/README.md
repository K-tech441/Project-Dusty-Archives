# 示例 pack：Munkres《Topology》2e（§12–§20）

这是实例工程的**真实配置样本**（跑通了 9 节 / 146 原子）。复制它作为新书的起点。

| 文件 | 是什么 |
|---|---|
| `book-profile.json` | 实例描述（`book-profile/v1`）：core 插件、判据引擎、MCP 面共认的**唯一契约**。字段定义见 [docs/plugin-api.md](../../../docs/plugin-api.md) §3 |
| `契约补充.md` | 本书特有的**补充契约**：注入系统提示，接在 core 通用契约之后（章节特例、命令差异、基底变更规程、工作基准） |
| `books/munkres-2e.json` | 书配置（`book-config/v1` 的提取式填法）：页码提取参数；`kl book-build` 据此生成页码索引 |
| `cordis.patch.yml` | 把 5 个 bundle 的 config 一次写好的片段，**改路径即可抄** |

> `book-profile.json` 里的 `env` 与 `paths.md` 指向**库外资源**（英文 PDF / md 转录 / 中译
> 目录索引）。这类路径按机器配置；换机器只改这里，不改代码。文件本身不在本仓库分发。

## 换一本书要改的四处

1. `book-profile.json`：`book_id` / `title` / `paths`（repo、清单目录、基底、图、术语表）/
   `lean.lib` + `lean.namespace` / `env`；
2. `books/<id>.json`（或按 [docs/book-config.md](../../../docs/book-config.md) §2 人填 `ranges`）；
3. `契约补充.md`：本书特例（如"13/14 章装订对换"），**不要重复 core 通用规则**；
4. `cordis.patch.yml`：4 处机器路径 + 1 处 profile 路径。

改完重启 DSH，跑 `pipeline_doctor` 应两段全绿；再跑 `python -m kl.cli config` 核对解析结果。

## 为什么这份样本值得抄

- 它是**真的在跑**的配置，不是示意：判据、门禁、图、页码索引、术语表都由它驱动；
- 它演示了三个容易写错的地方：
  1. `paths.repo` 是**相对 profile 文件**的路径，其余 `paths.*` 相对仓库根；
  2. 书的章节顺序按**物理页序**（这本英文书 13/14 章装订对换，节号只是标签）；
  3. md 转录的 `p####.md` 中 `####` = **英文 PDF 页号**，不是印刷页。
