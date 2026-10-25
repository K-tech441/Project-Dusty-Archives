/**
 * @local/dsh-pipeline-core — 通用形式化管线核心（CommonJS，同步 apply）
 *
 * 把「与书无关」的那一半做进 DSH：
 *
 *   1. systemPrompt 段：通用流程契约（判据清单 / 五步 / LSP 内循环 / 协作 / 收口）
 *      + 本书 pack 的【项目补充】。每一步模型调用都注入，避免随上下文压缩被稀释。
 *   2. 工具 pipeline_gate(section)：一次调用跑完收口三连
 *      （指针校验 → 四判据含判重 → 双向覆盖审计），返回结构化 verdict + 下一步。
 *   3. 工具 pipeline_doctor()：本书 profile 校验 + 判据引擎体检。
 *
 * ★ 书相关的一切都从 book profile 读（knowledge/book-profile.json）：书 id/标题、
 *   仓库、清单目录、基底、图、术语表、文档、CLI 模块名、原子必填字段、环境变量。
 *   本文件里不许出现书名、书路径；换书 = 换 profile，core 不动。
 * ★ 判据不在本插件实现。判据的唯一实现是仓库里的判据引擎（python -m <cli.module> check）。
 *   本插件只做【注入 + 聚合】。
 * ★ apply 必须同步；parameters / output.schema 用标准 JSON Schema（object 根）。
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { execFile } = require('node:child_process');

// 注入契约的版本号：pipeline_doctor 会把它打出来 —— 改完契约必须重启 DSH，
// 重启后看到「core 契约 vN」与文件头一致才算真的加载了新契约（契约在插件加载时固化）。
const CORE_CONTRACT_VERSION = 'v6';

const PROFILE_SCHEMA_RE = /^book-profile\/v(\d+)$/;
const PROFILE_MAJOR = 1;

// core 固定最小集：book pack 只能往 atoms.required_fields 里**加**，不能减掉这些。
const MIN_ATOM_FIELDS = ['id', 'kind', 'quote', 'loc', 'lean'];

const DEFAULTS = {
  enabled: true,
  profile: '', // ★ 必填：book profile 路径（见 docrepo docs/plugin-api.md §3）
  python: 'D:/dsh-uv/tools/lean-lsp-mcp/Scripts/python.exe',
  pylibs: 'D:/pylibs',
  injectContract: true,
  promptOrder: 880,
  gateTimeoutMs: 900000,
};

/** 通用契约（与书无关）。本书特有的东西一律进 pack 的 contract_extras。 */
const CORE_BODY = [
  '■ 判据（只有判据引擎一处实现；插件/文档/grep 都不是判据）',
  '① build ② 无 sorry、axioms ⊆ {propext, Classical.choice, Quot.sound} ③a 禁提基底概念',
  '③a′ A 层引用在基底范围内 ③b 判重（基底 + 自库）③c quote 逐字 ④ module 卫生。',
  '缺判据就扩展判据引擎的 check；不要用临时脚本或人眼代替，也不要只写在文档里。',
  '',
  '■ 每节五步',
  '⓪ pipeline_doctor 全绿再开工',
  '① 取本节页码（只读页码索引，禁止翻书/凭记忆）② 建本节清单（单一事实源 sectionNN.json）',
  '③ 读英文转录逐条填 item：quote 直接抄 md 原文；填一条就 quote-check，坏一条立刻改',
  '④ 写 Lean：新模块用模板生成头；无 sorry；只 import 基底与本库',
  '⑤ 刷新指针 → 四判据（含判重，回填 verdict）→ 收口审计 → 入序表标 done',
  '（§具体命令、路径、基线规程见【项目补充】指向的权威文档；本段只定纪律）',
  '',
  '■ 写证明：内循环是交互式 LSP（诊断只是其中一环，不是全部）',
  '· 写/改一步之前先确认目标（goal / term_goal）；不要盲改后靠编译试错。',
  '· 试 tactic 用 multi_attempt（一次给多个方案，读回各自 goal 状态）；找引理名先',
  '  local_search / leansearch；查签名/文档用 hover_info。',
  '· 每次改完确认 0 error / 0 warning；`lake env lean` 只在 LSP 不可用时兜底（说明理由），',
  '  `lake build` 只段末/收口。',
  '· 汇报证据必须四类分开计数：diagnostics×N / goal×N / multi_attempt×N / search×N；',
  '  只报 diagnostics（把 LSP 当编译器用）= 没达到要求，要说明为什么 goal/multi_attempt 用不上。',
  '· 工具缺失或报错 → 立刻停下报告，不要换一种方式硬扛。',
  '· 不写 set_option 压 linter；声明引用一律全限定名 + 模块解析。',
  '',
  '■ 测量与查证纪律（从实际失效处提炼，仍然有效）',
  '· 测量只产出「我看到了什么」，不产出「所以该怎么设计」；裁定属于 Lead / 学员。',
  '· 零命中是带权证据：报「没有」时必须同时报覆盖率（怎么穷举、怎么交叉验证过），',
  '  覆盖率未知的零命中只能标「未核」。',
  '· 从一个数字跳到结论之前，先查那个机制本身；判据靠「数据源保证了什么」，不靠「名字像什么」。',
  '· 凡写「大概是 / 应该 / 我记得」，落盘前必须变成「原文是」；不确定就标「未核」。',
  '· 同一概念常有多编码（谓词 / 结构 / 一般框架）⟹ 命中可能是「有，但形状和期望不同」，不是「没有」。',
  '· 书的特殊情形，库里可能只有一般情形（先问「它是不是被推广了」，不要直接判缺席）。',
  '· 99% 与 100% 是质的区别；可接受的近似必须显式声明为近似。',
  '· 「数学等价」≠「程序同一个」：判同一用 rfl / defeq，等价是另一个命题。',
  '· 认错要具体（哪一步、依据什么、改成什么），不写自评段落、不累计错误次数。',
  '',
  '■ 协作（agent team / subagent / section worker）',
  '· R 只读侦察 → 汇报（含任务书事实校正）→ 等批准。',
  '· W 以【原子】为工作单位，一次只做一个：写该原子的 Lean 声明 → 填清单 item（quote/label/',
  '  statement/names）→ quote-check → LSP 诊断干净 → 下一个原子。分块/报段只是汇报节奏，',
  '  不是写作单位；大原子（多子句定理）可拆 1–2 步，但清单 item 仍按原子登记。',
  '· 遇到问题立刻停（debug 策略：现象 · 根因猜测 · 已试过 · 需要决定），不要硬扛第二次。',
  '· 写作用域：worker 只写自己的内容模块 + 本节清单；入序表 / 探针 / 聚合文件 / 图 / 术语表 / git 归 Lead。',
  '· 基底可改，但必须走【项目补充】里的基底变更规程并跑全量回归，Lead 复核后才算。',
  '· 发现问题 ⟹ 立刻维护管线：判据 / 工具修复 / 文档规则三选一，写进同一次改动，删掉被作废的旧规则。',
  '· 完工 = pipeline_gate(n) ok + pipeline_doctor 全绿；不 ok 不许标完成。',
].join('\n');

// ---------------------------------------------------------------- 小工具

const isStr = (v) => typeof v === 'string' && v.trim() !== '';

const txt = (s) => [{ type: 'text', text: String(s == null ? '' : s) }];

function params(properties, required) {
  const out = { type: 'object', properties: properties || {} };
  if (required && required.length) out.required = required.slice();
  out.additionalProperties = false;
  return out;
}

function tail(s, n) {
  const t = String(s == null ? '' : s).trim();
  if (t.length <= n) return t;
  return '…' + t.slice(t.length - n);
}

function stripBom(s) {
  return s.charCodeAt(0) === 0xfeff ? s.slice(1) : s;
}

function summarize(prefix, problems, unregistered, ghosts) {
  const bits = [];
  if (prefix) bits.push(prefix);
  const ps = Array.isArray(problems) ? problems : [];
  if (ps.length) bits.push(ps.slice(0, 6).join('；') + (ps.length > 6 ? ' …（共 ' + ps.length + ' 条）' : ''));
  if (unregistered) bits.push('未登记声明 ' + unregistered + ' 条');
  if (ghosts) bits.push('幽灵名 ' + ghosts + ' 条');
  return bits.filter(Boolean).join(' · ') || '未通过（没有细节）';
}

// ---------------------------------------------------------------- book profile

function resolveConfig(raw) {
  const c = raw && typeof raw === 'object' ? raw : {};
  const out = Object.assign({}, DEFAULTS);
  for (const k of Object.keys(DEFAULTS)) {
    if (c[k] !== undefined && c[k] !== null) out[k] = c[k];
  }
  const extra = Object.keys(c).filter((k) => !(k in DEFAULTS));
  if (extra.length > 0) {
    console.warn('[pipeline-core] unknown config keys ignored: ' + extra.join(', '));
  }
  return out;
}

/**
 * 结构校验（不看路径是否存在 —— 存在性交给 doctor：profile 合法但资源没下载完的
 * 仓库也要能启动、能被体检报红）。失败即 throw。
 */
function validateProfile(raw, where) {
  const die = (msg) => {
    throw new Error('profile 校验失败（' + where + '）：' + msg);
  };
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) die('根必须是对象');

  const m = PROFILE_SCHEMA_RE.exec(String(raw.schema || ''));
  if (!m) die('schema 缺失或格式错（应为 "book-profile/v1"）');
  if (Number(m[1]) !== PROFILE_MAJOR) die('schema 主版本 v' + m[1] + ' 不受支持（core 只接受 v' + PROFILE_MAJOR + '）');

  if (!isStr(raw.book_id)) die('book_id 缺失');
  if (!isStr(raw.book_config)) die('book_config 缺失（书配置路径）');

  const paths = raw.paths;
  if (!paths || typeof paths !== 'object' || Array.isArray(paths)) die('paths 缺失');
  for (const k of ['repo', 'inventory', 'base_lean', 'graph', 'glossary']) {
    if (!isStr(paths[k])) die('paths.' + k + ' 缺失');
  }

  const lean = raw.lean;
  if (!lean || typeof lean !== 'object') die('lean 缺失');
  if (!isStr(lean.lib)) die('lean.lib 缺失（内容库名 = 聚合文件名）');
  if (!isStr(lean.toolchain_file)) die('lean.toolchain_file 缺失');

  const atoms = raw.atoms;
  if (!atoms || typeof atoms !== 'object') die('atoms 缺失');
  if (!Array.isArray(atoms.required_fields)) die('atoms.required_fields 缺失（数组）');
  const missing = MIN_ATOM_FIELDS.filter((f) => atoms.required_fields.indexOf(f) < 0);
  if (missing.length) die('atoms.required_fields 少了 core 固定最小集：' + missing.join(', ') + '（只能加不能减）');

  const judge = raw.judge;
  if (!judge || typeof judge !== 'object') die('judge 缺失');
  for (const k of ['base_candidate', 'forbidden_list']) {
    if (!isStr(judge[k])) die('judge.' + k + ' 缺失');
  }
  if (judge.extensions !== undefined && !Array.isArray(judge.extensions)) die('judge.extensions 必须是数组');
  if (raw.env !== undefined && (typeof raw.env !== 'object' || raw.env === null || Array.isArray(raw.env))) {
    die('env 必须是对象（环境变量表）');
  }
  return raw;
}

/** 把 profile 里的路径解析成绝对路径。约定：paths.repo 相对 profile 文件；其余相对仓库根。 */
function normalizeProfile(raw, file) {
  const dir = path.dirname(file);
  const repo = path.resolve(dir, String(raw.paths.repo));
  const fromRepo = (p) => (isStr(p) ? (path.isAbsolute(p) ? path.normalize(p) : path.resolve(repo, p)) : '');
  const atoms = raw.atoms || {};
  const judge = raw.judge || {};
  const docs = raw.docs && typeof raw.docs === 'object' ? raw.docs : {};
  const docsAbs = {};
  for (const k of Object.keys(docs)) if (isStr(docs[k])) docsAbs[k] = fromRepo(docs[k]);
  return {
    file,
    dir,
    schema: raw.schema,
    bookId: raw.book_id,
    title: isStr(raw.title) ? raw.title : raw.book_id,
    bookConfig: fromRepo(raw.book_config),
    repo,
    paths: {
      md: fromRepo(raw.paths.md),
      inventory: fromRepo(raw.paths.inventory),
      orderTable: fromRepo(raw.paths.order_table),
      baseLean: fromRepo(raw.paths.base_lean),
      graph: fromRepo(raw.paths.graph),
      glossary: fromRepo(raw.paths.glossary),
    },
    docs: docsAbs,
    lean: {
      lib: raw.lean.lib,
      toolchainFile: fromRepo(raw.lean.toolchain_file),
      aggregate: path.join(repo, raw.lean.lib + '.lean'),
      buildSystem: isStr(raw.lean.build_system) ? raw.lean.build_system : 'lake',
    },
    cli: { module: isStr(raw.cli && raw.cli.module) ? raw.cli.module : 'kl.cli' },
    atoms: {
      kinds: Array.isArray(atoms.kinds) ? atoms.kinds.slice() : [],
      examplePolicy: isStr(atoms.example_policy) ? atoms.example_policy : '',
      partialPolicy: isStr(atoms.partial_policy) ? atoms.partial_policy : '',
      requiredFields: atoms.required_fields.slice(),
    },
    judge: {
      baseCandidate: fromRepo(judge.base_candidate),
      forbiddenList: fromRepo(judge.forbidden_list),
      scopeExtras: isStr(judge.scope_extras) ? judge.scope_extras : '',
      extensions: Array.isArray(judge.extensions) ? judge.extensions.map(fromRepo) : [],
    },
    env: Object.assign({}, raw.env || {}),
    contractExtras: isStr(raw.contract_extras) ? fromRepo(raw.contract_extras) : '',
    render: raw.render && typeof raw.render === 'object' ? raw.render : {},
  };
}

/** 读 + 校验 + 归一。任何失败都带字段名 throw（拒绝启动，不静默降级）。 */
function loadProfile(file) {
  const abs = path.resolve(String(file || ''));
  let text;
  try {
    text = stripBom(fs.readFileSync(abs, 'utf8'));
  } catch (e) {
    throw new Error('读 profile 失败（' + abs + '）：' + (e && e.message ? e.message : String(e)));
  }
  let raw;
  try {
    raw = JSON.parse(text);
  } catch (e) {
    throw new Error('profile 不是合法 JSON（' + abs + '）：' + (e && e.message ? e.message : String(e)));
  }
  validateProfile(raw, abs);
  return normalizeProfile(raw, abs);
}

/** 路径存在性检查（doctor 用；不 throw）。 */
function profileChecks(profile) {
  const out = [];
  const add = (key, p, kind) => {
    if (!isStr(p)) return;
    const ok = kind === 'dir' ? fs.existsSync(p) && fs.statSync(p).isDirectory() : fs.existsSync(p) && fs.statSync(p).isFile();
    out.push({ key, path: p, ok, kind });
  };
  add('paths.repo', profile.repo, 'dir');
  add('paths.inventory', profile.paths.inventory, 'dir');
  add('paths.md', profile.paths.md, 'dir');
  add('paths.order_table', profile.paths.orderTable, 'file');
  add('paths.base_lean', profile.paths.baseLean, 'file');
  add('paths.graph', profile.paths.graph, 'file');
  add('paths.glossary', profile.paths.glossary, 'file');
  add('book_config', profile.bookConfig, 'file');
  for (const k of Object.keys(profile.docs)) add('docs.' + k, profile.docs[k], 'file');
  add('lean.toolchain_file', profile.lean.toolchainFile, 'file');
  add('lean.aggregate', profile.lean.aggregate, 'file');
  add('judge.base_candidate', profile.judge.baseCandidate, 'file');
  add('judge.forbidden_list', profile.judge.forbiddenList, 'file');
  add('contract_extras', profile.contractExtras, 'file');
  for (const ext of profile.judge.extensions) add('judge.extensions', ext, 'file');
  return out;
}

function readExtras(profile) {
  if (!profile.contractExtras) return { ok: true, text: '' };
  try {
    const text = stripBom(fs.readFileSync(profile.contractExtras, 'utf8')).trim();
    return { ok: true, text };
  } catch (e) {
    return { ok: false, text: '', error: '项目补充读不到（' + profile.contractExtras + '）：' + (e && e.message ? e.message : String(e)) };
  }
}

function relToRepo(profile, p) {
  if (!p) return '';
  const rel = path.relative(profile.repo, p);
  return (rel && !rel.startsWith('..') && !path.isAbsolute(rel) ? rel : p).split(path.sep).join('/');
}

/** core 通用契约 + 【项目补充】 = 实际注入的文本。 */
function buildContract(profile, extras) {
  const lines = [
    '【形式化管线 · 流程契约 core ' + CORE_CONTRACT_VERSION + '】' +
      profile.title + '（' + profile.bookId + '）· 仓库 ' + profile.repo,
    '本段每次模型调用都注入，不必逐条重读；细节以【项目补充】列出的权威文档为准，' +
      '规则冲突时以文档 + 判据引擎（python -m ' + profile.cli.module + '）为准。',
    '',
  ];
  lines.push(CORE_BODY);
  if (extras.ok && extras.text) {
    lines.push('', '【项目补充】' + relToRepo(profile, profile.contractExtras));
    lines.push(extras.text);
  } else if (!extras.ok) {
    lines.push('', '【项目补充】缺失 —— ' + extras.error + '（先修 profile / 文件，再开工）');
  }
  return lines.join('\n');
}

// ---------------------------------------------------------------- 判据引擎桥

function cliEnv(config, profile) {
  const parts = [path.join(profile.repo, 'tools')];
  if (config.pylibs) parts.push(config.pylibs);
  const env = Object.assign({}, process.env, {
    PYTHONIOENCODING: 'utf-8',
    PYTHONPATH: parts.join(';'),
    KL_LEAN_ROOT: profile.repo,
    // ★ A3：判据引擎按 KL_PROFILE 解析书数据（书 id / 库名 / 清单目录 / 图 / 术语表 /
    //   页码索引）—— 插件的 CLI 与 MCP server 走同一份 profile，不各存一份路径。
    KL_PROFILE: profile.file,
  });
  if (config.pylibs) env.KL_PYLIBS = config.pylibs;
  if (!env.KL_BOOK_ID) env.KL_BOOK_ID = profile.bookId;
  for (const k of Object.keys(profile.env)) {
    if (profile.env[k] !== undefined && profile.env[k] !== null) env[k] = String(profile.env[k]);
  }
  return env;
}

function runCli(config, profile, args) {
  return new Promise((resolve) => {
    execFile(
      config.python,
      ['-m', profile.cli.module].concat(args),
      {
        cwd: profile.repo,
        env: cliEnv(config, profile),
        timeout: config.gateTimeoutMs,
        windowsHide: true,
        maxBuffer: 64 * 1024 * 1024,
      },
      (error, stdout, stderr) => {
        let parsed = null;
        try {
          parsed = JSON.parse(String(stdout));
        } catch {
          parsed = null;
        }
        resolve({ error: error || null, stdout: String(stdout || ''), stderr: String(stderr || ''), parsed });
      },
    );
  });
}

function cliHint(config, profile, args) {
  return config.python + ' -m ' + profile.cli.module + ' ' + args.join(' ');
}

// ---------------------------------------------------------------- 门禁 / 体检

/** 收口三连。按顺序全跑（不提前 return），便于一次看全问题。 */
async function gate(config, profile, section) {
  const specs = [
    {
      key: 'link-check',
      label: '指针校验（link --check：全限定名 + 模块 + 位置 + 签名哈希）',
      args: ['link', String(section), '--check'],
      next: '先 build → 刷新模块表/探针 → link ' + section + '（刷新指针），再重跑门禁',
    },
    {
      key: 'check',
      label: '四判据 + ③b 判重（check --with-dup --update）',
      args: ['check', String(section), '--with-dup', '--update'],
      next: '按 check.problems 修 Lean 或清单；③b 失败看 dup.ours 的重复组原文（删自己那条、改用基底引理）',
    },
    {
      key: 'audit',
      label: '收口（audit：清单↔声明双向覆盖 + 必填 + 指针 + 页码）',
      args: ['audit', String(section)],
      next: '按 unregistered_decls / ghost_names / problems 回填清单或改名；改完重跑 link 再门禁',
    },
  ];

  const steps = [];
  const problems = [];
  const nextSteps = [];

  for (const spec of specs) {
    const r = await runCli(config, profile, spec.args);
    const p = r.parsed;
    let ok = false;
    let detail = '';

    if (!p) {
      const why = r.error ? String(r.error.message || r.error) : '没有返回 JSON';
      detail = '判据引擎没跑通：' + (tail(r.stderr, 700) || why);
      nextSteps.push('检查插件 config 的 python / pylibs / profile.paths.repo；直接复跑：' + cliHint(config, profile, spec.args));
    } else {
      ok = typeof p.ok === 'boolean' ? p.ok : !r.error;
      if (spec.key === 'link-check') {
        detail = ok
          ? 'checked ' + (p.checked != null ? p.checked : '?') + ' 条指针'
          : summarize(p.checked != null ? 'checked ' + p.checked + ' 条指针' : '', p.problems);
      } else if (spec.key === 'check') {
        const b = p.build || {};
        const ax = p.axioms || {};
        detail = ok
          ? 'build ' + (b.seconds != null ? b.seconds : '?') + 's · axioms ' + (ax.checked != null ? ax.checked : '?') + ' 条'
          : summarize('build ' + (b.seconds != null ? b.seconds : '?') + 's', p.problems);
      } else {
        const m = p.mapping || {};
        detail = ok
          ? 'items ' + p.items + ' · coverage ' + p.coverage + ' · mapping ' + m.identity_total + '/' + m.declarations_in_file
          : summarize('items ' + p.items + ' · coverage ' + p.coverage, p.problems,
            (p.unregistered_decls || []).length, (p.ghost_names || []).length);
      }
      if (!ok) {
        problems.push(spec.key + ': ' + detail);
        nextSteps.push(spec.next);
      }
    }
    steps.push({ key: spec.key, label: spec.label, ok, detail });
  }

  const ok = steps.every((s) => s.ok);
  if (ok) {
    nextSteps.push('门禁全过。若源码动过：build → 探针 → 重算图数据；然后 pipeline_doctor 全绿再提交');
  }

  const lines = ['管线门禁 §' + section + ' · ' + profile.bookId + ' · core 契约 ' + CORE_CONTRACT_VERSION, ''];
  for (const s of steps) {
    lines.push((s.ok ? '✓' : '✗') + ' ' + s.key.padEnd(11) + s.label);
    if (s.detail) lines.push('    ' + s.detail);
  }
  if (problems.length) {
    lines.push('', '未过项：');
    for (const p of problems) lines.push('  · ' + p);
  }
  if (nextSteps.length) {
    lines.push('', '下一步：');
    for (const n of nextSteps) lines.push('  · ' + n);
  }
  return { ok, section, steps, problems, next: nextSteps, report: lines.join('\n') };
}

function doctor(config, profilePath) {
  const lines = [];
  const checks = [];
  const next = [];

  // profile 读+校验（每次都从磁盘重读：改 profile 不用重启 DSH —— 冻结的只是契约文本）
  let profile = null;
  let loadError = '';
  try {
    profile = loadProfile(profilePath);
  } catch (e) {
    loadError = e && e.message ? e.message : String(e);
  }
  lines.push('管线体检 · core 契约 ' + CORE_CONTRACT_VERSION +
    (profile ? ' · book ' + profile.bookId : '') + ' · profile ' + profilePath, '');

  if (!profile) {
    lines.push('✗ profile —— ' + loadError);
    checks.push('profile: ' + loadError);
    next.push('修 ' + profilePath + '（字段见 docrepo docs/plugin-api.md §3）；core 只认 book profile，不猜默认值');
    return { ok: false, checks, next, report: lines.concat(['', '有未过项 —— 先修再开工。']).join('\n') };
  }

  const pc = profileChecks(profile);
  const bad = pc.filter((c) => !c.ok);
  lines.push('[1/2] 书 profile（' + relToRepo(profile, profile.file) + '）');
  for (const c of pc) {
    lines.push((c.ok ? '✓' : '✗') + ' ' + c.key + ' — ' + (c.path || '(未配置)'));
    checks.push('profile · ' + c.key + (c.ok ? ': ok' : ': 不存在 ' + c.path));
  }
  if (bad.length) {
    next.push('建/修上面 ✗ 的路径（profile 字段名已列出）；库外资源见【项目补充】的资源文档');
  }

  // 判据引擎体检
  lines.push('', '[2/2] 判据引擎（python -m ' + profile.cli.module + ' doctor）');
  return runCli(config, profile, ['doctor']).then((r) => {
    if (!r.parsed) {
      const why = r.error ? String(r.error.message || r.error) : '没有返回 JSON';
      lines.push('✗ 体检没跑通：' + (tail(r.stderr, 800) || why));
      checks.push('engine: 没跑通');
      next.push('检查插件 config 的 python / pylibs；或直接：' + cliHint(config, profile, ['doctor']));
    } else {
      for (const c of r.parsed.checks || []) {
        lines.push((c.ok ? '✓' : '✗') + ' ' + c.check + (c.detail ? ' — ' + c.detail : ''));
        checks.push(c.check + (c.ok ? ': ok' : ': ' + (c.detail || '失败')));
      }
      for (const n of r.parsed.next || []) next.push(n);
      if (!r.parsed.ok && !(r.parsed.next || []).length) next.push('按上面 ✗ 的检查项修（坑要先变成体检项）');
    }
    const ok = bad.length === 0 && !!(r.parsed && r.parsed.ok);
    if (next.length) {
      lines.push('', '下一步：');
      for (const n of next) lines.push('  · ' + n);
    }
    lines.push('', ok ? '全绿。' : '有未过项 —— 先修再开工。');
    return { ok, checks, next, report: lines.join('\n') };
  });
}

// ---------------------------------------------------------------- 插件入口

function apply(ctx, rawConfig) {
  const config = resolveConfig(rawConfig);
  if (!config.enabled) return;

  const profilePath = config.profile ? path.resolve(String(config.profile)) : '';
  if (!profilePath) {
    throw new Error('[pipeline-core] config.profile 未设置：core 只认 book profile（docrepo docs/plugin-api.md §3）');
  }
  // profile 结构错 ⟹ 拒绝启动（不静默降级）；路径缺失只让 doctor 红，不挡启动。
  const profile = loadProfile(profilePath);
  const extras = readExtras(profile);
  const contract = buildContract(profile, extras);

  console.log('[pipeline-core] core 契约 ' + CORE_CONTRACT_VERSION + ' · book ' + profile.bookId +
    ' · profile ' + profilePath + (extras.ok ? '' : ' · 【项目补充】缺失'));

  // ---------------------------------------------------------------- 系统提示
  if (config.injectContract) {
    const prompt = typeof ctx.get === 'function' ? ctx.get('systemPrompt') : null;
    if (prompt && typeof prompt.section === 'function') {
      ctx.effect(() => prompt.section({
        name: 'pipeline-core-contract',
        order: config.promptOrder,
        text: contract,
      }));
    } else if (prompt && typeof prompt.context === 'function') {
      ctx.effect(() => prompt.context({
        name: 'pipeline-core-contract',
        order: config.promptOrder,
        text: contract,
      }));
    } else {
      console.warn('[pipeline-core] systemPrompt 服务不可用；流程契约未注入');
    }
  }

  // ---------------------------------------------------------------- 工具
  ctx.effect(() => ctx.tools.register({
    name: 'pipeline_gate',
    description: [
      '形式化管线收口门禁：一次调用依次跑 指针校验 → 四判据（含 ③b 判重，回填 verdict）→ 收口审计，',
      '返回结构化 verdict + 下一步。判据不在本插件实现，调用的就是仓库判据引擎（python -m <cli.module>）的同一实现。',
      '在把某节标为完成之前必须调用它；ok=false 时按 next 修，不许跳过。',
    ].join(''),
    parameters: params({
      section: { type: 'integer', description: '节号，例如 13' },
    }, ['section']),
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          ok: { type: 'boolean' },
          section: { type: 'integer' },
          steps: { type: 'array', items: { type: 'string' } },
          problems: { type: 'array', items: { type: 'string' } },
          next: { type: 'array', items: { type: 'string' } },
          report: { type: 'string' },
        },
        required: ['ok', 'section', 'steps', 'problems', 'next', 'report'],
      },
      render: (_args, value) => txt(value.report),
    },
    presentCall: (args) => ({ card: 'generic', title: '管线门禁 §' + (args && args.section), kind: 'other' }),
    async execute(args) {
      const section = Number(args && args.section);
      if (!Number.isInteger(section) || section <= 0) throw new Error('section 必须是正整数节号');
      let p;
      try {
        p = loadProfile(profilePath);
      } catch (e) {
        const msg = e && e.message ? e.message : String(e);
        return {
          ok: false, section, steps: [], problems: ['profile: ' + msg],
          next: ['修 profile（' + profilePath + '）；字段见 docrepo docs/plugin-api.md §3'],
          report: '管线门禁 §' + section + ' · profile 不可用\n\n' + msg,
        };
      }
      const r = await gate(config, p, section);
      return {
        ok: r.ok,
        section: r.section,
        steps: r.steps.map((s) => (s.ok ? '✓ ' : '✗ ') + s.key + ' — ' + s.detail),
        problems: r.problems,
        next: r.next,
        report: r.report,
      };
    },
  }));

  // ★ 为什么还要一个 CLI 版 doctor：判据引擎的 MCP 工具表在 server 启动时固定，
  //   改了 mcp 实现后运行中的 server 仍是旧代码、工具缺失且不报错。本工具走 CLI，与工具表无关。
  ctx.effect(() => ctx.tools.register({
    name: 'pipeline_doctor',
    description: [
      '管线体检：先校验本书 profile（字段 + 路径存在性），再跑判据引擎 doctor',
      '（聚合 / 探针 / .ilean 同步 / 页码索引 / 基底候选 / module 卫生 / 图数据新鲜度）。',
      '开工前先跑；有未过项按 next 修。走 CLI，不依赖 MCP 工具表。',
    ].join(''),
    parameters: params({}),
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          ok: { type: 'boolean' },
          checks: { type: 'array', items: { type: 'string' } },
          next: { type: 'array', items: { type: 'string' } },
          report: { type: 'string' },
        },
        required: ['ok', 'checks', 'next', 'report'],
      },
      render: (_args, value) => txt(value.report),
    },
    presentCall: () => ({ card: 'generic', title: '管线体检', kind: 'other' }),
    async execute() {
      return doctor(config, profilePath);
    },
  }));
}

module.exports = {
  apply,
  DEFAULTS,
  CORE_CONTRACT_VERSION,
  CORE_BODY,
  MIN_ATOM_FIELDS,
  validateProfile,
  normalizeProfile,
  loadProfile,
  profileChecks,
  buildContract,
};
