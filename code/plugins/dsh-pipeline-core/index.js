/**
 * @local/dsh-pipeline-core — 稳定入口（ESM）
 *
 * 逻辑全在 lib/impl.cjs。原因：Node 按 URL 缓存 ESM，改 index.js 需要重启才能生效；
 * 而 CJS 的 require 缓存可以显式删掉 —— 于是「改实现 ⟹ 开关一次插件」即可生效。
 *
 * ★ apply 必须同步：Cordis 的 effect 只在 apply 的同步执行期间挂到 fiber 上；
 *   跨过 await 注册的 effect 不归插件所有，卸载时释放不掉，工具会变孤儿。
 */

import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)

const IMPL = './lib/impl.cjs'

export const name = 'pipeline-core'
export const inject = ['tools', 'systemPrompt']

export function apply(ctx, config) {
  let resolved = null
  try {
    resolved = require.resolve(IMPL)
  } catch {
    resolved = null
  }
  if (resolved) delete require.cache[resolved]
  return require(IMPL).apply(ctx, config || {})
}
