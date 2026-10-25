# plugins — DSH 插件

5 个 DSH bundle。它们只做三件事：把**流程契约**注入系统提示、把引擎接成 **MCP 工具**、
把图渲染进**设置面板**。**判据不在插件里**（唯一实现在 `../engine/kl/checks.py`）。

| bundle | 作用 | 关键配置 |
|---|---|---|
| `dsh-pipeline-core` | 通用 core：注入 core 契约 + 【项目补充】；工具 `pipeline_gate` / `pipeline_doctor` | `profile`（book-profile.json 路径） |
| `dsh-mcp-kl` | 知识层 MCP（`kl_*` 工具） | `python` / `PYTHONPATH` / `KL_PROFILE` / `KL_PYLIBS` |
| `dsh-mcp-lean` | Lean LSP MCP（goal / 诊断 / multi_attempt / 搜索） | `--lean-project-path`（= `profile.paths.repo`） |
| `dsh-mcp-mathlib` | 本地 mathlib 索引 MCP（430k 声明，SQLite+FTS5） | `args` 里的索引 server 路径 |
| `dsh-graph-panel` | 原子图**数据服务**：`/plugins/graph-panel/graph.json` + 查看器静态页。看图走 `kl view` 生成的自包含 HTML（预览侧栏）—— 设置面板画布太小，不适合 | `profile`（图路径 = `profile.paths.graph`） |

## 安装（DSH profile）

1. 把目录加进 profile：`package.json` 的 `dsh.profile.bundles` 列表 + `dependencies` 里
   `"@local/dsh-xxx": "link:<绝对路径>"`（或 `plugin_manager action=install_bundle`）；
2. 复制 `../examples/munkres-2e/cordis.patch.yml` 的 config 片段，把路径换成你的实例仓库；
3. 重启 DSH（插件契约与 MCP server 环境都在进程启动时固化）。

## 三条硬约束（都踩过坑，见各 bundle README）

- `apply` 必须**同步**：Cordis 的 effect 只在 apply 的同步执行期间挂到 fiber 上，
  跨 `await` 注册的 effect 卸载时释放不掉，工具会变孤儿；
- 工具参数与输出用**标准 JSON Schema**（object 根）；
- **契约在插件加载时固化**：改完契约/实现必须重启；`pipeline_doctor` 首行打印
  `core 契约 vN`，与 `lib/impl.cjs` 的 `CORE_CONTRACT_VERSION` 一致才算加载成功。

## 书相关的东西不写在插件里

A3 之后，书 id / 库名 / 清单目录 / 图 / 术语表 / 页码索引都从 **book profile** 解析；
插件配置里只剩机器级路径（python、`PYTHONPATH`、Lean 项目、mathlib 索引）。
换书时插件代码一行不改 —— 这是「换一本书」的验收标准。
