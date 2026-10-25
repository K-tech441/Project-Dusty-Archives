# dsh-graph-panel

**原子图数据服务**（宿主半）：把 `graph.json` 与查看器静态页通过宿主路由暴露出来。
图本身的**正式交付**不在这里 —— 走引擎的 `kl view` 生成的单文件 HTML，在 Harness 预览侧栏打开。

## 为什么撤掉设置面板入口

设置面板的画布尺寸太小，看这种分层图不合适；Harness 的默认做法是**预览侧栏看交付物**，
而交付物是自包含 HTML（内联 force-graph + 图数据，file:// 下可交互、无 CORS）。

## 保留的路由

| 路由 | 内容 |
|---|---|
| `/plugins/graph-panel/graph.json` | 图数据（路径由 book profile 解析，`no-store`） |
| `/plugins/graph-panel/viewer.html` | 查看器静态页（同一个 UI 的在线版，调试/分享用） |
| `/plugins/graph-panel/force-graph.min.js` | vendored 依赖（MIT，173 KB） |

## 交付物（推荐）

```bash
python -m kl.cli view          # → knowledge/pipeline/graph-view.html（~286 KB，自包含）
```

生成后在文件卡上点开即进入预览侧栏；也可以直接双击用浏览器打开。

## 结构

```
index.js               宿主半：三条静态路由（graph.json / viewer.html / force-graph.min.js）
viewer/index.html      查看器（在线版；神经网络式分层 + 悬停语义详情 + 有向边动效）
viewer/force-graph.min.js
cordis.patch.yml       插入 graph-panel 行（config: profile / routePath）
```

## 配置

```yaml
- id: graph-panel
  name: '@local/dsh-graph-panel'
  config:
    enabled: true
    profile: D:/your-instance/knowledge/book-profile.json   # 与 pipeline-core / mcp-kl 同一份
    routePath: /plugins/graph-panel/graph.json
```

`profile` 缺省时可退回旧行为（`repoRoot` + `graphRel`）。profile 字段见 docrepo `docs/plugin-api.md` §3。
