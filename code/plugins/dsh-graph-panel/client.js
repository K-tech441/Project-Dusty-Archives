/* @local/dsh-graph-panel — 客户端半：知识图谱面板。
 *
 * 两种视图：
 *   atom（默认）—— graph.json 的 atom_graph：**一个节点 = 书上的一个原子**（§12–§16 共 70 个），
 *                 边 = 原子间提及（A/B/I/R 层折叠取并集），指向基底的边只计 ext_edges。
 *   decl        —— 声明级细节图（391 节点 / 1749 边），排查实现用。
 *
 * 交互：滚轮缩放（以光标为中心）、拖动平移、搜索高亮、按模块过滤（声明视图）、点节点看详情。
 * 不 import 任何 Harness Client 包；配色用中性字面量 + currentColor，避免主题 token 改名风险。
 */
window.__ModuleLoader__.load({
  id: '@local/dsh-graph-panel',
  factory(require) {
    const React = require('react')
    const h = React.createElement
    const { useState, useEffect, useMemo, useRef } = React

    const ROUTE = '/plugins/graph-panel/graph.json'
    const LAYER_COLOR = { A: '#e08a3c', B: '#2f9e8f', AB: '#c25bd0', I: '#7d9b4a', R: '#c05252' }
    const STATUS_COLOR = { verified: '#2f6df6', partial: '#c29a2e', todo: '#9aa0aa', pending: '#9aa0aa' }
    const CLASS_COLOR = { ours: '#2f6df6', generated: '#9b59d0', mathlib: '#8a8a8a', gray: '#9aa0aa' }
    const BORDER = '1px solid rgba(128,128,128,0.28)'
    const MUTED = 'rgba(128,128,128,0.9)'
    const DX = 150
    const DY = 108

    function useSize(ref) {
      const [size, setSize] = useState({ w: 800, h: 520 })
      useEffect(() => {
        const el = ref.current
        if (!el) return undefined
        const update = () => setSize({ w: Math.max(320, el.clientWidth), h: Math.max(320, el.clientHeight) })
        update()
        if (typeof ResizeObserver === 'function') {
          const ro = new ResizeObserver(update)
          ro.observe(el)
          return () => ro.disconnect()
        }
        window.addEventListener('resize', update)
        return () => window.removeEventListener('resize', update)
      }, [ref])
      return size
    }

    function makeLayout(nodes, tiers) {
      const names = Object.keys(nodes || {})
      const byTier = new Map()
      for (const name of names) {
        const t = typeof tiers[name] === 'number' ? tiers[name] : 0
        if (!byTier.has(t)) byTier.set(t, [])
        byTier.get(t).push(name)
      }
      const tierKeys = [...byTier.keys()].sort((a, b) => a - b)
      const pos = new Map()
      let maxX = 0
      for (const t of tierKeys) {
        byTier.get(t).sort().forEach((name, i) => {
          pos.set(name, { x: i * DX, y: t * DY })
          if (i * DX > maxX) maxX = i * DX
        })
      }
      const maxY = (tierKeys.length ? tierKeys[tierKeys.length - 1] : 0) * DY
      return { pos, maxX, maxY, tierKeys }
    }

    function GraphPanel() {
      const hostRef = useRef(null)
      const svgRef = useRef(null)
      const dragRef = useRef(null)
      const size = useSize(hostRef)

      const [state, setState] = useState({ phase: 'loading', data: null, error: '' })
      const [mode, setMode] = useState('atom')
      const [moduleFilter, setModuleFilter] = useState('')
      const [query, setQuery] = useState('')
      const [selected, setSelected] = useState(null)
      const [view, setView] = useState({ k: 1, x: 20, y: 20 })

      const load = () => {
        setState({ phase: 'loading', data: null, error: '' })
        fetch(ROUTE, { cache: 'no-store' })
          .then((r) => {
            if (!r.ok) throw new Error('HTTP ' + r.status)
            return r.json()
          })
          .then((data) => setState({ phase: 'ready', data, error: '' }))
          .catch((error) => setState({ phase: 'error', data: null, error: String((error && error.message) || error) }))
      }
      useEffect(load, [])

      const data = state.data
      const hasAtoms = !!(data && data.atom_graph && data.atom_graph.nodes)
      const effectiveMode = hasAtoms ? mode : 'decl'
      const graph = effectiveMode === 'atom' ? data.atom_graph : data
      const nodes = (graph && graph.nodes) || {}
      const edges = (graph && graph.edges) || []
      const tiers = (graph && graph.tiers) || {}
      const layout = useMemo(() => (graph ? makeLayout(nodes, tiers) : null), [graph])

      const adjacency = useMemo(() => {
        const adj = new Map()
        for (const e of edges) {
          if (!adj.has(e.src)) adj.set(e.src, [])
          if (!adj.has(e.dst)) adj.set(e.dst, [])
          adj.get(e.src).push(e.dst)
          adj.get(e.dst).push(e.src)
        }
        return adj
      }, [edges])

      const modules = useMemo(() => {
        if (!data || !data.nodes) return []
        const set = new Set()
        for (const n of Object.values(data.nodes)) if (n.module) set.add(n.module)
        return [...set].sort()
      }, [data])

      // 每切换视图/尺寸就重新适配（fit 只写 view，不进依赖，避免循环）
      useEffect(() => {
        if (!layout) return
        const k = Math.max(0.1, Math.min((size.w - 40) / (layout.maxX + 240), (size.h - 40) / (layout.maxY + 240), 1.15))
        setView({ k, x: 24, y: 24 })
        setSelected(null)
      }, [layout, size.w, size.h])

      // 滚轮：原来挂在 useEffect(..., []) 上，那时 <svg> 还没渲染 ⟹ 监听从未挂上（用户实测坏）。
      // 现在依赖 [graph]（视图切换后 svg 已存在），用 passive:false 才能 preventDefault。
      useEffect(() => {
        const el = svgRef.current
        if (!el) return undefined
        const onWheel = (event) => {
          event.preventDefault()
          const rect = el.getBoundingClientRect()
          const mx = event.clientX - rect.left
          const my = event.clientY - rect.top
          setView((v) => {
            const factor = Math.exp(-event.deltaY * 0.0015)
            const k = Math.min(6, Math.max(0.1, v.k * factor))
            const ratio = k / v.k
            return { k, x: mx - (mx - v.x) * ratio, y: my - (my - v.y) * ratio }
          })
        }
        el.addEventListener('wheel', onWheel, { passive: false })
        return () => el.removeEventListener('wheel', onWheel)
      }, [graph])

      const nodeMeta = (name) => {
        const node = nodes[name] || {}
        if (effectiveMode === 'atom') {
          return {
            title: node.label || node.id || name,
            sub: node.primary || '',
            color: STATUS_COLOR[node.status] || CLASS_COLOR.ours,
            radius: 5,
            text: node.label || node.id || name,
          }
        }
        return {
          title: name,
          sub: node.module || '',
          color: node.generated ? CLASS_COLOR.generated : (CLASS_COLOR[node.class] || CLASS_COLOR.gray),
          radius: node.class === 'ours' ? 3.4 : 2.4,
          text: name,
        }
      }

      const visible = (name) => {
        if (effectiveMode === 'atom') return true
        if (!moduleFilter) return true
        const node = nodes[name]
        return !!node && node.module === moduleFilter
      }

      const matches = useMemo(() => {
        const q = query.trim().toLowerCase()
        if (!q) return new Set()
        const out = new Set()
        for (const name of Object.keys(nodes)) {
          const meta = nodes[name] || {}
          const hay = (name + ' ' + (meta.label || '') + ' ' + (meta.primary || '') + ' ' + (meta.module || '')).toLowerCase()
          if (hay.includes(q)) out.add(name)
        }
        return out
      }, [query, nodes, effectiveMode])

      const neighbors = useMemo(() => (selected ? new Set(adjacency.get(selected) || []) : new Set()), [selected, adjacency])

      const startDrag = (event) => {
        dragRef.current = { sx: event.clientX, sy: event.clientY, ox: view.x, oy: view.y }
        event.preventDefault()
      }
      const onMove = (event) => {
        const d = dragRef.current
        if (!d) return
        setView((v) => ({ k: v.k, x: d.ox + event.clientX - d.sx, y: d.oy + event.clientY - d.sy }))
      }
      const endDrag = () => { dragRef.current = null }

      const toolbarStyle = { display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', fontSize: 13 }
      const controlStyle = {
        padding: '4px 8px', border: BORDER, borderRadius: 6, background: 'transparent',
        color: 'inherit', fontSize: 13, cursor: 'pointer',
      }
      const cardStyle = { border: BORDER, borderRadius: 8, padding: '8px 10px', fontSize: 12.5, lineHeight: 1.6 }
      const stats = graph && graph.stats ? graph.stats : null

      const summary = (() => {
        if (!stats) return state.phase === 'loading' ? '加载中…' : ''
        if (effectiveMode === 'atom') {
          const a = stats.atoms || {}
          return '原子 ' + a.total + '（verified ' + (a.verified || 0) + '）· 原子边 ' + (stats.edges ? stats.edges.total : 0) + ' · 基底边 ' + (stats.ext_edges || 0)
        }
        return '声明 ' + stats.nodes.total + '（ours ' + stats.nodes.ours + ' / mathlib ' + (stats.nodes.mathlib || 0) + '）· 边 ' + stats.edges.total
      })()

      const nodeCircle = (name) => {
        const p = layout.pos.get(name)
        const meta = nodeMeta(name)
        const isSel = name === selected
        const isNeighbor = neighbors.has(name)
        const isMatch = matches.has(name)
        const dim = selected ? (!isSel && !isNeighbor) : false
        return h('circle', {
          key: 'n:' + name,
          cx: p.x, cy: p.y,
          r: isSel ? meta.radius + 2 : (isMatch ? meta.radius + 1.2 : meta.radius),
          fill: meta.color,
          opacity: dim ? 0.18 : 1,
          stroke: isSel ? '#111' : (isMatch ? '#d4a017' : 'none'),
          strokeWidth: isSel ? 1.4 : 1.2,
          style: { cursor: 'pointer' },
          onClick: () => setSelected(isSel ? null : name),
        }, h('title', null, meta.title + (meta.sub ? '\n' + meta.sub : '')))
      }

      const edgeLine = (event) => {
        const p1 = layout.pos.get(event.src)
        const p2 = layout.pos.get(event.dst)
        if (!p1 || !p2) return null
        const layer = event.layers || 'B'
        const connected = selected && (event.src === selected || event.dst === selected)
        return h('line', {
          key: 'e:' + event.src + '>' + event.dst + ':' + layer,
          x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y,
          stroke: LAYER_COLOR[layer] || '#999',
          strokeWidth: connected ? 1.5 : 0.7,
          opacity: selected ? (connected ? 0.95 : 0.05) : 0.38,
        })
      }

      const labelOverlay = () => {
        const names = new Set()
        if (effectiveMode === 'atom') {
          for (const name of Object.keys(nodes)) names.add(name)
        }
        if (selected) {
          names.add(selected)
          for (const n of neighbors) names.add(n)
        }
        for (const name of matches) names.add(name)
        const out = []
        for (const name of names) {
          if (!layout.pos.has(name)) continue
          const p = layout.pos.get(name)
          out.push(h('text', {
            key: 'l:' + name,
            x: p.x * view.k + view.x + (effectiveMode === 'atom' ? 7 : 7),
            y: p.y * view.k + view.y + 3,
            fontSize: effectiveMode === 'atom' ? 11 : 10.5,
            fill: 'currentColor',
            opacity: 0.88,
            pointerEvents: 'none',
          }, nodeMeta(name).text))
        }
        return out
      }

      const detail = (() => {
        if (!selected || !graph) return null
        const node = nodes[selected] || {}
        const adj = adjacency.get(selected) || []
        if (effectiveMode === 'atom') {
          const ext = (graph.ext_edges || {})[selected] || 0
          return h('aside', { style: Object.assign({}, cardStyle, { width: 300, flex: '0 0 300px', overflow: 'auto' }) },
            h('div', { style: { fontWeight: 600, marginBottom: 4 } }, (node.label || selected) + '  (' + selected + ')'),
            h('div', { style: { color: MUTED } }, '类型：' + (node.kind || '?') + ' · 状态：' + (node.status || '?') + ' · 级次 ' + (tiers[selected] != null ? tiers[selected] : '?')),
            h('div', { style: { color: MUTED, marginTop: 2 } }, '书：' + (node.book_ref || '?')),
            node.primary ? h('div', { style: { marginTop: 4, wordBreak: 'break-all' } }, 'primary：' + node.primary) : null,
            h('div', { style: { color: MUTED, marginTop: 2 } }, '指向基底的边：' + ext),
            h('div', { style: { marginTop: 8, marginBottom: 4, fontWeight: 600 } }, '同层邻居 ' + adj.length),
            h('div', { style: { display: 'flex', flexDirection: 'column', gap: 2, maxHeight: '42%', overflow: 'auto' } },
              adj.slice(0, 400).map((n) => h('button', {
                key: 'nb:' + n,
                onClick: () => setSelected(n),
                style: { textAlign: 'left', background: 'transparent', border: 'none', color: 'inherit', cursor: 'pointer', padding: '1px 0', fontSize: 12, opacity: 0.85 },
                title: n,
              }, (nodes[n] && (nodes[n].label || nodes[n].id)) || n))),
            node.statement ? h('div', { style: { color: MUTED, marginTop: 8 } }, node.statement) : null,
          )
        }
        return h('aside', { style: Object.assign({}, cardStyle, { width: 300, flex: '0 0 300px', overflow: 'auto' }) },
          h('div', { style: { fontWeight: 600, marginBottom: 4, wordBreak: 'break-all' } }, selected),
          h('div', { style: { color: MUTED } }, '模块：' + (node.module || '?')),
          h('div', { style: { color: MUTED } }, '类别：' + (node.class || '?') + (node.generated ? '（生成）' : '') + ' · tier ' + (tiers[selected] != null ? tiers[selected] : '?')),
          h('div', { style: { marginTop: 8, marginBottom: 4, fontWeight: 600 } }, '邻居 ' + adj.length),
          h('div', { style: { display: 'flex', flexDirection: 'column', gap: 2, maxHeight: '60%', overflow: 'auto' } },
            adj.slice(0, 400).map((n) => h('button', {
              key: 'nb:' + n,
              onClick: () => setSelected(n),
              style: { textAlign: 'left', background: 'transparent', border: 'none', color: 'inherit', cursor: 'pointer', padding: '1px 0', fontSize: 12, opacity: 0.85 },
              title: n,
            }, n))),
        )
      })()

      const tabStyle = (active) => ({
        padding: '4px 10px', borderRadius: 6, cursor: 'pointer', fontSize: 13,
        border: BORDER, background: active ? 'rgba(47,109,246,0.14)' : 'transparent',
        fontWeight: active ? 600 : 400,
      })

      return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 10, height: 'calc(100vh - 210px)', minHeight: 460 } },
        h('div', { style: { display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' } },
          h('h2', { style: { margin: 0, fontSize: 18 } }, '知识图谱'),
          h('span', { style: { color: MUTED, fontSize: 12.5 } }, 'Munkres 形式化库 · 原子视图 = 一个节点一个原子；声明视图 = Lean 声明细节')),
        h('div', { style: toolbarStyle },
          h('button', { style: tabStyle(effectiveMode === 'atom'), onClick: () => setMode('atom'), disabled: !hasAtoms, title: hasAtoms ? '' : 'graph.json 里没有 atom_graph（重跑 kl graph --json）' }, '原子视图'),
          h('button', { style: tabStyle(effectiveMode === 'decl'), onClick: () => setMode('decl') }, '声明视图'),
          effectiveMode === 'decl' ? h('select', {
            value: moduleFilter,
            onChange: (e) => setModuleFilter(e.target.value),
            style: Object.assign({}, controlStyle, { cursor: 'pointer' }),
            title: '按模块过滤',
          },
            h('option', { value: '' }, '全部模块'),
            modules.map((m) => h('option', { key: m, value: m }, m))) : null,
          h('input', {
            value: query,
            onChange: (e) => setQuery(e.target.value),
            placeholder: effectiveMode === 'atom' ? '搜索原子标签 / primary' : '搜索声明名 / 模块名',
            style: Object.assign({}, controlStyle, { cursor: 'text', minWidth: 200 }),
          }),
          h('button', { style: controlStyle, onClick: load }, '刷新'),
          h('span', { style: { color: MUTED } }, summary),
          matches.size ? h('span', { style: { color: '#b8860b' } }, '命中 ' + matches.size) : null,
        ),
        state.phase === 'error'
          ? h('div', { style: cardStyle }, '加载失败：' + state.error + '（路由 ' + ROUTE + '；检查 bundle config 的 repoRoot / graphRel）')
          : h('div', { style: { display: 'flex', gap: 10, flex: 1, minHeight: 0 } },
            h('div', {
              ref: hostRef,
              style: { flex: 1, minWidth: 0, border: BORDER, borderRadius: 8, overflow: 'hidden', position: 'relative', background: 'rgba(127,127,127,0.04)' },
            },
              graph && layout
                ? h('svg', {
                  ref: svgRef,
                  width: size.w,
                  height: size.h,
                  style: { display: 'block', cursor: dragRef.current ? 'grabbing' : 'grab', userSelect: 'none' },
                  onMouseDown: startDrag,
                  onMouseMove: onMove,
                  onMouseUp: endDrag,
                  onMouseLeave: endDrag,
                },
                  h('g', { transform: 'translate(' + view.x + ',' + view.y + ') scale(' + view.k + ')' },
                    edges.map((e) => visible(e.src) && visible(e.dst) ? edgeLine(e) : null),
                    [...layout.pos.keys()].filter(visible).map(nodeCircle)),
                  h('g', null, labelOverlay()))
                : h('div', { style: { padding: 16, color: MUTED, fontSize: 13 } }, state.phase === 'loading' ? '加载图数据…' : '没有数据'),
            ),
            detail,
          ),
        h('div', { style: { display: 'flex', gap: 14, flexWrap: 'wrap', color: MUTED, fontSize: 12 } },
          h('span', null, '边：'),
          Object.entries(LAYER_COLOR).map(([k, v]) => h('span', { key: 'l:' + k, style: { display: 'inline-flex', alignItems: 'center', gap: 4 } },
            h('i', { style: { display: 'inline-block', width: 12, height: 2, background: v } }), k)),
          effectiveMode === 'atom' ? h('span', { style: { marginLeft: 8 } }, '节点色 = 原子状态（蓝 verified / 黄 partial / 灰 others）') : null,
        ),
      )
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
