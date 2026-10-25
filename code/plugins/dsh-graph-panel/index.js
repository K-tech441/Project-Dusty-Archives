/**
 * @local/dsh-graph-panel — 宿主半：把图的 JSON 通过 HTTP 暴露给前端。
 *
 * 为什么不把图数据编进 client bundle：图每节都会重算（kl graph），读文件才能总是新的。
 * 路由固定为 /plugins/graph-panel/graph.json，客户端半用同一个常量。
 *
 * ★ A3（2026-10-25）：图的位置由 **book profile** 给出（`config.profile`）——
 *   与 pipeline-core / mcp-kl 用同一份 profile，换书只换这一行，不再各存一份路径。
 *   没有 profile 时退回 `repoRoot + graphRel` 两条显式配置（旧行为，兼容用）。
 */
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const name = 'graph-panel'
export const inject = ['webServer']

const HERE = path.dirname(fileURLToPath(import.meta.url))
const VIEWER_DIR = path.join(HERE, 'viewer')

// 前端查看器（viewer/）与它的依赖库都是本插件自带的静态文件，由宿主路由提供：
//   /plugins/graph-panel/viewer.html            画布查看器（force-graph，神经网络式分层）
//   /plugins/graph-panel/force-graph.min.js     vendored 的 force-graph UMD
const STATIC_ROUTES = {
  '/plugins/graph-panel/viewer.html': { file: 'index.html', type: 'text/html; charset=utf-8' },
  '/plugins/graph-panel/force-graph.min.js': { file: 'force-graph.min.js', type: 'application/javascript; charset=utf-8' },
}

const DEFAULTS = {
  enabled: true,
  profile: '', // book-profile.json 路径（推荐；字段见 docrepo docs/plugin-api.md §3）
  repoRoot: '', // 无 profile 时的回退：仓库根
  graphRel: '', // 无 profile 时的回退：图相对仓库根的路径
  routePath: '/plugins/graph-panel/graph.json',
}

function resolveConfig(raw) {
  const c = raw && typeof raw === 'object' ? raw : {}
  const out = Object.assign({}, DEFAULTS)
  for (const k of Object.keys(DEFAULTS)) {
    if (c[k] !== undefined && c[k] !== null) out[k] = c[k]
  }
  const extra = Object.keys(c).filter((k) => !(k in DEFAULTS))
  if (extra.length > 0) console.warn('[graph-panel] unknown config keys ignored: ' + extra.join(', '))
  return out
}

function stripBom(s) {
  return s.charCodeAt(0) === 0xfeff ? s.slice(1) : s
}

/** 图文件的绝对路径：优先 profile，其次 repoRoot + graphRel。 */
async function graphFile(config) {
  if (config.profile) {
    const profilePath = path.resolve(String(config.profile))
    const raw = JSON.parse(stripBom(await fs.readFile(profilePath, 'utf8')))
    const dir = path.dirname(profilePath)
    const repoRel = (raw.paths && raw.paths.repo) || '.'
    const repo = path.isAbsolute(repoRel) ? repoRel : path.resolve(dir, repoRel)
    const rel = (raw.paths && raw.paths.graph) || 'knowledge/pipeline/graph.json'
    return path.isAbsolute(rel) ? rel : path.resolve(repo, rel)
  }
  if (config.repoRoot) {
    return path.join(config.repoRoot, config.graphRel || 'knowledge/pipeline/graph.json')
  }
  throw new Error('graph-panel: 需要 config.profile（推荐）或 config.repoRoot')
}

export function apply(ctx, rawConfig) {
  const config = resolveConfig(rawConfig)
  if (!config.enabled) return

  // ---- 静态文件：查看器页面 + vendored 库
  for (const [route, spec] of Object.entries(STATIC_ROUTES)) {
    ctx.effect(() => ctx.webServer.register({
      kind: 'exact',
      path: route,
      async handler(req, res) {
        if (req.method !== 'GET' && req.method !== 'HEAD') {
          res.statusCode = 405
          res.setHeader('content-type', 'text/plain; charset=utf-8')
          res.end('method not allowed')
          return
        }
        try {
          const body = await fs.readFile(path.join(VIEWER_DIR, spec.file))
          res.statusCode = 200
          res.setHeader('content-type', spec.type)
          res.setHeader('cache-control', 'no-store')
          res.end(req.method === 'HEAD' ? undefined : body)
        } catch (error) {
          res.statusCode = 404
          res.setHeader('content-type', 'text/plain; charset=utf-8')
          res.end('missing viewer asset: ' + spec.file + ' (' + String(error && error.message || error) + ')')
        }
      },
    }))
  }

  ctx.effect(() => ctx.webServer.register({
    kind: 'exact',
    path: config.routePath,
    async handler(req, res) {
      if (req.method !== 'GET' && req.method !== 'HEAD') {
        res.statusCode = 405
        res.setHeader('content-type', 'text/plain; charset=utf-8')
        res.end('method not allowed')
        return
      }
      let file = ''
      try {
        file = await graphFile(config) // 每次请求重新解析（改 profile 不用重启）
        const text = await fs.readFile(file, 'utf8')
        res.statusCode = 200
        res.setHeader('content-type', 'application/json; charset=utf-8')
        res.setHeader('cache-control', 'no-store')
        res.end(req.method === 'HEAD' ? undefined : text)
      } catch (error) {
        res.statusCode = 404
        res.setHeader('content-type', 'application/json; charset=utf-8')
        res.end(JSON.stringify({ error: String((error && error.message) || error), file }))
      }
    },
  }))
}
