/* @local/dsh-graph-panel — 客户端半：知识图谱面板。
 *
 * 2026-10-25 换掉旧的 SVG 简陋版：面板本身不再画图，而是嵌入宿主路由提供的查看器页面
 *   /plugins/graph-panel/viewer.html
 * 查看器是「神经网络式分层的原子图」：
 *   - 列 = 依赖深度 L0 → L7，列内节点等距（列 = 书里概念的基础程度）；
 *   - hover / 点击原子 → 右侧显示该原子的自然语义内容（中文陈述 / 书中位置 / Lean 全限定名 / 出入边）；
 *   - 有向边：箭头 + 沿边流动的粒子（选中节点时只流动它自己的边），方向 = 存在 → 依赖；
 *   - 数据来自 graph.json 的 atom_graph（节点自带 statement/label/book_ref/primary/decls）。
 *
 * 为什么用 iframe：查看器零依赖宿主 React/主题，单页自包含（force-graph + canvas），
 * 改版式不动插件契约；同一个 URL 在浏览器里单独打开也是同一套 UI。
 */
window.__ModuleLoader__.load({
  id: '@local/dsh-graph-panel',
  factory(require) {
    const React = require('react')
    const h = React.createElement
    const VIEWER = '/plugins/graph-panel/viewer.html'

    function GraphPanel() {
      return h('div', {
        style: {
          height: 'calc(100vh - 210px)',
          minHeight: 520,
          borderRadius: 10,
          overflow: 'hidden',
          border: '1px solid rgba(128,128,128,0.28)',
          background: '#05070b',
        },
      }, h('iframe', {
        src: VIEWER,
        title: '故纸堆 · 原子图',
        style: { width: '100%', height: '100%', border: 'none', display: 'block', background: '#05070b' },
      }))
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        ctx.slots.inject('settings.section', () => ctx.slots.register({
          name: 'settings.section',
          id: 'graph-panel',
          order: 25,
          label: '知识图谱',
        }, GraphPanel))
      },
    }
  },
})
