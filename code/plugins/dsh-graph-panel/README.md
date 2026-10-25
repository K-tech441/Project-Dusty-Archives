# dsh-graph-panel

在 Harness Web UI 的**设置面板**里查看形式化库的四层声明图 / 原子图。

## 打开方式

侧栏齿轮（设置）→ 左侧「**知识图谱**」（Settings → 知识图谱）。
数据每次打开/刷新时从宿主读取，永远是最新的 `graph.json`（路径由 book profile 给出）。

## 功能

- **滚轮缩放**（以光标为中心）、**拖动平移**、**重置视图**
- **搜索** 声明名 / 模块名：命中节点描金边并在图上标名
- **按模块过滤**（Base / Section12…19 / mathlib …）
- **点节点**：高亮它的所有边与邻居，右侧显示模块、类别、tier、邻居列表（可点邻居跳转）
- **图例**：节点按 class 上色（ours / generated / mathlib / gray），边按层上色（A/B/I/R）
- 统计行：节点数（ours / mathlib）与边数

## 结构

```
index.js        宿主半：注册 /plugins/graph-panel/graph.json；图路径 = profile.paths.graph（no-store）
client.js       客户端半：window.__ModuleLoader__ + settings.section 槽位，原生 SVG 渲染
cordis.patch.yml 插入 graph-panel 行（config: profile / routePath）
```

## 配置（A3）

```yaml
- id: graph-panel
  config:
    profile: D:/some-repo/knowledge/book-profile.json   # 与 pipeline-core / mcp-kl 同一份
    routePath: /plugins/graph-panel/graph.json
```

- `profile` 缺省时退回旧行为：`repoRoot` + `graphRel` 两条显式配置。
- 宿主每次请求重新解析 profile（换书改 profile 不用重启；改 profile 路径本身要重启）。
- profile 字段见 docrepo `docs/plugin-api.md` §3。

## 依赖

- 宿主半只用 `webServer` 服务；客户端半只用模块表提供的 React。
- 数据文件由 `python -m kl.cli graph --json <图路径>` 生成（每节收口后跑一次）。
- 不缓存：改完图后点面板里的「刷新」或重新打开设置即可。

## 安装

```
plugin_manager action=install_bundle target=D:\deepseek工作区\dsh-bundles\dsh-graph-panel
```

安装后**刷新页面**（Ctrl+R）客户端 bundle 才会加载；设置面板里应多出「知识图谱」页。
