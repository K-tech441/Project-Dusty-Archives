/**
 * 离线测试台 —— 完全不接触 DSH 进程（只有最后两步真跑判据引擎）。
 *
 * 用法：
 *   $node='C:\Users\Lenovo\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe'
 *   & $node test/check.mjs
 *
 * 检查项：
 *   1. profile 结构校验：正例通过；缺字段/错 schema/减原子最小集 都拒绝（带字段名）；
 *      未知键允许（前向兼容）
 *   2. 真 profile 能加载，路径检查全绿
 *   3. 契约拼装：core 文本无书名/书路径硬编码；【项目补充】接在后面
 *   4. apply 同步、系统提示段注册一次、两个工具、schema 合法、卸载可回收
 *   5. 缺少 / 非法 profile ⟹ 拒绝启动
 *   6. 真跑 pipeline_gate(19) 与 pipeline_doctor（有副作用，测试后还原干净文件）
 */
import { createRequire } from 'node:module'
import assert from 'node:assert'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { execFileSync } from 'node:child_process'

const require = createRequire(import.meta.url)
const impl = require('../lib/impl.cjs')

// 实例工程路径（可用环境变量覆盖：KL_PROFILE / KL_REPO / KL_TEST_SECTION）
const PROFILE = process.env.KL_PROFILE || 'D:/munkres-formal/knowledge/book-profile.json'
const REPO = process.env.KL_REPO || path.dirname(path.dirname(PROFILE))
const SECTION = Number(process.env.KL_TEST_SECTION || 19)

// ---------------------------------------------------------------- 1. profile 校验
const good = {
  schema: 'book-profile/v1',
  book_id: 'demo-book',
  title: 'Demo',
  book_config: 'knowledge/book.json',
  paths: {
    repo: '.',
    md: 'book/md',
    inventory: 'knowledge/pipeline',
    order_table: 'knowledge/pipeline/order.json',
    base_lean: 'Src/Base.lean',
    graph: 'knowledge/pipeline/graph.json',
    glossary: 'knowledge/glossary.json',
  },
  lean: { lib: 'Src', toolchain_file: 'lean-toolchain' },
  atoms: { required_fields: ['id', 'kind', 'quote', 'loc', 'lean'] },
  judge: { base_candidate: 'knowledge/pipeline/base_candidate.json', forbidden_list: 'knowledge/pipeline/base.json' },
}
const clone = () => JSON.parse(JSON.stringify(good))

assert.doesNotThrow(() => impl.validateProfile(clone(), 'mem'), '正例应通过')
assert.doesNotThrow(() => { const p = clone(); p.unknown_future_key = { x: 1 }; impl.validateProfile(p, 'mem') },
  '未知键允许（前向兼容），不能报错')

assert.throws(() => impl.validateProfile(Object.assign(clone(), { schema: 'book-profile/v2' }), 'mem'),
  /主版本 v2 不受支持/, '不支持的主版本必须拒绝')
assert.throws(() => impl.validateProfile(Object.assign(clone(), { schema: 'nope' }), 'mem'), /schema/, '缺 schema 必须拒绝')
assert.throws(() => { const p = clone(); delete p.book_id; impl.validateProfile(p, 'mem') }, /book_id/, '缺 book_id 必须拒绝')
assert.throws(() => { const p = clone(); delete p.paths.inventory; impl.validateProfile(p, 'mem') },
  /paths\.inventory/, '缺 paths.inventory 必须拒绝，且错误里要指出字段名')
assert.throws(() => { const p = clone(); p.atoms.required_fields = ['id', 'kind']; impl.validateProfile(p, 'mem') },
  /固定最小集/, '原子必填字段只能加不能减')
assert.throws(() => { const p = clone(); delete p.judge; impl.validateProfile(p, 'mem') }, /judge/, '缺 judge 必须拒绝')

// ---------------------------------------------------------------- 2. 真 profile
const profile = impl.loadProfile(PROFILE)
assert.strictEqual(profile.schema, 'book-profile/v1')
assert.ok(profile.repo.replace(/\\/g, '/') === 'D:/munkres-formal', 'paths.repo 相对 profile 文件解析')
assert.ok(profile.bookId.length > 0)
assert.ok(profile.paths.inventory.endsWith('knowledge\\pipeline') || profile.paths.inventory.endsWith('knowledge/pipeline'))
assert.ok(profile.contractExtras, 'profile 应声明 contract_extras')
const pc = impl.profileChecks(profile)
const badPaths = pc.filter((c) => !c.ok)
assert.deepStrictEqual(badPaths.map((c) => c.key), [], '本书 profile 的路径都应存在（缺了就是数据/资源问题）')

// ---------------------------------------------------------------- 3. 契约拼装
const extras = { ok: true, text: '# 项目补充\n本书特例：13/14 章对换' }
const contract = impl.buildContract(profile, extras)
assert.ok(contract.startsWith('【形式化管线 · 流程契约 core ' + impl.CORE_CONTRACT_VERSION + '】'), '首行 = 契约版本头')
assert.ok(contract.includes('【项目补充】'), '要把 project extras 接在后面')
assert.ok(contract.includes('13/14 章对换'), 'extras 内容要原样进契约')
assert.ok(contract.includes(profile.bookId), '契约头要带本书 book_id（来自 profile，不是 core 硬编码）')

// core 自身（不含注入数据）不许出现书名/书路径 —— 一般化的验收条件
for (const word of ['Munkres', 'munkres', 'knowledge/pipeline', 'MunkresLean']) {
  assert.ok(!impl.CORE_BODY.includes(word), 'core 契约正文不得出现 "' + word + '"（应进 book pack）')
  const src = fs.readFileSync(new URL('../lib/impl.cjs', import.meta.url), 'utf8')
  // 允许出现的是注释里的通用说法；这里断言源码里没有「具体书」的硬编码
  if (word === 'knowledge/pipeline') {
    assert.ok(!src.includes(word), 'impl.cjs 不得硬编码清单路径 "knowledge/pipeline"')
  } else if (word === 'Munkres' || word === 'munkres') {
    assert.ok(!src.includes(word), 'impl.cjs 不得硬编码书名 "' + word + '"')
  }
}

// ---------------------------------------------------------------- 4. apply + 假 ctx
const disposers = []
const promptSections = []
const tools = []
const fake = {
  effect(fn) {
    const d = fn()
    if (typeof d === 'function') disposers.push(d)
    return d
  },
  get(name) {
    return name === 'systemPrompt' ? fake.systemPrompt : null
  },
  systemPrompt: {
    section(spec) { promptSections.push(spec); return () => {} },
    context(spec) { promptSections.push(spec); return () => {} },
  },
  tools: { register(spec) { tools.push(spec); return () => {} } },
}

const ret = impl.apply(fake, { profile: PROFILE })
assert.strictEqual(ret, undefined, 'apply 必须是同步的（不能返回 Promise）')
assert.strictEqual(promptSections.length, 1, '应注册且只注册一个系统提示段')
assert.strictEqual(promptSections[0].name, 'pipeline-core-contract')
assert.ok(promptSections[0].text.includes('【项目补充】'), '注入的契约要带项目补充')
assert.ok(promptSections[0].text.includes(profile.bookId), '注入的契约要带本书 book_id')
assert.strictEqual(tools.length, 2, '应注册两个工具（pipeline_gate / pipeline_doctor）')

const gateSpec = tools.find((t) => t.name === 'pipeline_gate')
const docSpec = tools.find((t) => t.name === 'pipeline_doctor')
assert.ok(gateSpec && docSpec, '缺工具：pipeline_gate / pipeline_doctor')
assert.deepStrictEqual(gateSpec.parameters, {
  type: 'object',
  properties: { section: { type: 'integer', description: '节号，例如 13' } },
  required: ['section'],
  additionalProperties: false,
})
assert.deepStrictEqual(gateSpec.output.schema.required, ['ok', 'section', 'steps', 'problems', 'next', 'report'])
assert.strictEqual(typeof gateSpec.output.render, 'function')
assert.deepStrictEqual(gateSpec.output.render({ section: 13 }, { report: 'hello', ok: true }),
  [{ type: 'text', text: 'hello' }])
assert.deepStrictEqual(docSpec.parameters, { type: 'object', properties: {}, additionalProperties: false })
assert.deepStrictEqual(docSpec.output.schema.required, ['ok', 'checks', 'next', 'report'])

// ---------------------------------------------------------------- 5. 拒绝启动
assert.throws(() => impl.apply(fake, { profile: '' }), /config\.profile 未设置/, '缺 profile 必须拒绝启动')
assert.throws(() => impl.apply(fake, { profile: 'D:/no/such/book-profile.json' }), /读 profile 失败/, '不存在的 profile 必须拒绝启动')
const tmp = path.join(os.tmpdir(), 'dsh-pipeline-core-bad-profile.json')
fs.writeFileSync(tmp, JSON.stringify({ schema: 'book-profile/v1', book_id: 'x' }), 'utf8')
assert.throws(() => impl.apply(fake, { profile: tmp }), /profile 校验失败/, '结构错的 profile 必须拒绝启动')
fs.unlinkSync(tmp)

// ---------------------------------------------------------------- 6. 真跑（有副作用 → 跑完还原）
// 会动的两个文件：本节清单（verdict 快照）与聚合文件（sync-root 重写）。路径从 profile 推。
const rel = (p) => path.relative(REPO, p).split(path.sep).join('/')
const TOUCHED = [
  rel(path.join(profile.paths.inventory, 'section' + String(SECTION).padStart(2, '0') + '.json')),
  rel(profile.lean.aggregate),
]
const git = (args) => execFileSync('git', ['-C', REPO, ...args], { encoding: 'utf8' }).trim()
const dirtyBefore = {}
for (const f of TOUCHED) dirtyBefore[f] = git(['status', '--porcelain', '--', f]) !== ''

const out = await gateSpec.execute({ section: SECTION })
for (const f of TOUCHED) {
  const dirtyAfter = git(['status', '--porcelain', '--', f]) !== ''
  if (!dirtyBefore[f] && dirtyAfter) {
    git(['checkout', '--', f])
    console.log('# 已恢复 ' + f + '（测试真跑 gate 会刷新 verdict，测试后还原）')
  }
}
assert.strictEqual(typeof out.ok, 'boolean')
assert.strictEqual(out.section, SECTION)
assert.strictEqual(out.steps.length, 3, '门禁三步都要跑')
assert.ok(Array.isArray(out.problems), 'problems 必须是数组')
assert.ok(out.report.includes('管线门禁 §' + SECTION), 'report 要带头行')
assert.ok(out.report.includes('core 契约 ' + impl.CORE_CONTRACT_VERSION), 'report 要带契约版本')
assert.ok(out.report.includes(profile.bookId), 'report 要带书 id（证明来自 profile）')

const doc = await docSpec.execute({})
assert.strictEqual(typeof doc.ok, 'boolean')
assert.ok(doc.checks.length >= 8, '体检应至少 8 项（profile 若干 + 引擎若干）')
assert.ok(doc.checks.some((c) => c.startsWith('profile · ')), '体检要含 profile 检查项')
assert.ok(doc.report.includes('书 profile'), '体检报告要分两段（profile / 引擎）')
assert.ok(doc.report.includes('core 契约 ' + impl.CORE_CONTRACT_VERSION), '体检报告要打印 core 契约版本')

// ---------------------------------------------------------------- 7. 回收
for (const d of disposers) assert.strictEqual(typeof d, 'function', '每个 effect 都要返回 disposer')

console.log('\n--- gate(§' + SECTION + ') ---')
console.log(out.report)
console.log('\n--- doctor ---')
console.log(doc.report)
console.log('\nOK: pipeline-core 离线测试通过')
