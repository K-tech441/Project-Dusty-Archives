# dsh-graph-panel

在 Harness Web UI 的**设置面板**里查看「故纸堆」的原子图（也支持声明图数据源）。

## 打开方式

侧栏齿轮（设置）→ 左侧「**知识图谱**」。数据每次打开/刷新时从宿主读取，永远是最新的
`graph.json`（路径由 book profile 给出）。

## 界面

**神经网络式分层**：一列 = 一层依赖深度（L0 基础 → L7 派生），列内节点等距、按列内数量收拢；
每个节点 = 书上的一个原子（定义 / 定理 / 引理 / 例子）。

- **悬停 / 点击原子** → 右侧详情：中文陈述、书中位置、Lean 全限定名、verified/partial、出入边列表（可点跳转）
- **有向边**：箭头 + 沿边流动的粒子表达方向（存在 → 依赖）；选中节点时只流动它自己的边
- **搜索**（`/` 聚焦，Esc 清除）、**A/B 层过滤**（陈述层 / 证明层）、**只看选中邻居**
- 滚轮缩放、拖动平移、点击固定

## 结构

```
index.js               宿主半：静态路由（viewer.html / force-graph.min.js）+ graph.json（no-store）
client.js              客户端半：settings.section 槽位里嵌入 viewer 页面（iframe，自包含）
viewer/index.html      查看器本体（canvas + force-graph；神经网络式分层布局）
viewer/force-graph.min.js  vendored 的 force-graph UMD（173 KB，无外部 CDN 依赖）
cordis.patch.yml       插入 graph-panel 行（config: profile / routePath）
```

为什么用 iframe：查看器零依赖宿主的 React 与主题 token，单页自包含；单独在浏览器打开
`/plugins/graph-panel/viewer.html` 也是同一套界面。改版式不动插件契约。

## 配置

```yaml
- id: graph-panel
  name: '@local/dsh-graph-panel'
  config:
    enabled: true
    profile: D:/your-instance/knowledge/book-profile.json   # 与 pipeline-core / mcp-kl 同一份
    routePath: /plugins/graph-panel/graph.json
```

- `profile` 缺省时可退回旧行为（`repoRoot` + `graphRel`）。
- 宿主每次请求重新解析 profile（换书改 profile 不用重启；改 profile 路径本身要重启）。
- profile 字段见 docrepo `docs/plugin-api.md` §3。

## 界面可调项（`viewer/index.html` 里几个常量）

| 常量 | 含义 |
|---|---|
| `COL_W` | 层间距（越大越疏） |
| `GAP` | 列内行距上限（越大列越长） |
| `r = (5.0 + …)` | 节点基准半径 |
| `linkDirectionalParticleSpeed` | 粒子速度（当前 0.0014；越小越慢） |

改完刷新页面即可（查看器是静态页，不走前端构建）。

## 安装

```
plugin_manager action=install_bundle target=D:\deepseek工作区\dsh-bundles\dsh-graph-panel
```

安装后**刷新页面**（Ctrl+R）客户端 bundle 才会加载；设置面板里会出现「知识图谱」。
