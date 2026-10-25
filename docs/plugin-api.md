# 插件一般化接口（G4 规范）

> **目标**：把现在"Munkres 专用"的实现，拆成**通用核心（core）+ 书实例包（book pack）**。
> 本文只定**边界与契约**（谁负责什么、哪些可配、哪些不许动），不定具体语言/框架/文件格式。
> 判据的语义由 core 固定；书相关的数据与领域检查由 book pack 提供。

---

## 1. 为什么需要这一层

现状：整套东西能跑，但名字、路径、文案、判据参数都长在"Munkres 这一本书"上。
换一本书（G5 场景里说的"换书手册"）要改插件代码，而不是换一份数据。
一般化后应满足：**装一个 core + 一个 book pack = 一条新管线**，核心代码不动。

因此先划一条硬边界：

```
core    = 不因书而变的东西：判据引擎、门禁流程、agent 协议、数据契约、工具接入
book    = 因书而变的东西：书配置、原子口径、基底参数、领域检查、渲染配置、文案
```

判断标准一句话：**如果删掉这本书换另一本，它会不会变？会变的必须进 book pack。**

---

## 2. 包拆分

| 目标包 | 职责 | 来源（当前实现） | 状态 |
|---|---|---|---|
| `pipeline-core` | 注入流程契约；`pipeline_gate` / `pipeline_doctor`；加载并校验 book profile；CLI 桥 | `@local/dsh-pipeline-core`（由 `dsh-munkres-pipeline` 一般化而来） | ✅ A1/A2 |
| `pipeline-book-<id>` | 书配置 + 原子口径 + 基参数 + 领域判据扩展 + 渲染配置 + 项目文案 | 实例仓库：`knowledge/book-profile.json` + `docs/契约补充.md` | ✅ A2 |
| `mcp-pipeline` | 通用 MCP：清单/判据/图/页码查询（原 `kl` 工具面；引擎按 `KL_PROFILE` 读 profile） | `dsh-mcp-kl` / `tools/kl` | ✅ A3（工具名仍为 `kl_*`，见下） |
| `mcp-lean` | Lean LSP 工具面（项目路径可配） | `dsh-mcp-lean` | ✅ 显式一行 `--lean-project-path = profile.paths.repo` |
| `mcp-mathlib` | 本地 mathlib 检索索引（工具级，与书无关） | `dsh-mcp-mathlib` | ✅ 与书解耦；换机器改路径 |
| `graph-panel` | 图渲染（读 `graph.json` + 渲染配置） | `dsh-graph-panel` | ✅ A3（`config.profile` → 图路径） |
| （可选）`compact-control` | 上下文压缩控制（与书无关） | `dsh-compact-control` | 可复用 |
| （独立族）`class-*` | 教学/授课插件（不属于本管线主链） | `dsh-munkres-class` | 与书绑定（不入主链） |
| （可选）`compact-control` | 上下文压缩控制（与书无关） | `dsh-compact-control` | 可复用 |
| （独立族）`class-*` | 教学/授课插件（不属于本管线主链） | `dsh-munkres-class` | 与书绑定（不入主链） |

一个 **book pack** 就是一个目录（可独立发版/复用），至少包含：

```
book-profile.json      # 实例描述（见 §3）
judge/ext/*.py|*.js    # 领域判据扩展（可选，见 §5）
contract-extras.md     # 项目补充规则（可选，见 §6）
render.json            # 图渲染配置（可选）
```

> **实现现状（A1–A3 已落地）**：Munkres 实例的 pack 直接住在实例仓库里（一个仓库 = 一个实例）：
> `knowledge/book-profile.json`（profile）+ `docs/契约补充.md`（补充契约）。
> pack 不需要是独立 npm 包 —— core / 引擎 / 各 MCP 面都只按路径读它。
>
> **工具名保留 `kl_*`（有意不做 `pipeline_*` 改名）**：改名要同步注入契约、仓库全部文档与
> 使用习惯，收益只是字面好看。文档口径：**`kl` = 知识层工具（knowledge layer）**，
> 换书不影响工具名；将来若真做多实现并存，再在 core 层加别名。

---

## 3. BookProfile：core 与 book 之间的唯一契约

core 只认这一份文件；其余路径、名字、口径都由它给出。

```jsonc
{
  "schema": "book-profile/v1",
  "book_id": "munkres-2e",
  "title": "Topology, 2nd edition (Munkres) / 拓扑学（原书第2版）",
  "book_config": "knowledge/books/munkres-2e.json",   // 书配置（book-config/v1，见 book-config.md）

  "paths": {
    "repo": "..",                                       // 仓库根：相对 profile 文件所在目录
    "md": "D:/…/book_md",                               // 转录目录（库外资源可用绝对路径）
    "inventory": "knowledge/pipeline",                  // sectionNN.json / 入序表 / 基底.json
    "order_table": "knowledge/pipeline/入序表.json",     // 跨节写序
    "base_lean": "MunkresLean/Base.lean",               // 基底唯一入口
    "graph": "knowledge/pipeline/graph.json",
    "glossary": "knowledge/glossary.json"
  },
  "docs": {                                             // 权威文档指针（进注入契约的引用）
    "pipeline": "docs/管线.md",
    "baseline": "docs/工程基准.md",
    "resources": "docs/资源与数据源.md"
  },
  "lean": {
    "lib": "MunkresLean",                               // 内容库名；聚合文件 = <lib>.lean
    "namespace": "Munkres",                             // Lean 命名空间前缀（判重 marker 等）
    "strip_prefixes": ["Munkres.Topology.", "Munkres."],// 图/面板显示时剥掉的前缀（可选）
    "toolchain_file": "lean-toolchain",
    "build_system": "lake"
  },
  "cli": { "module": "kl.cli" },                        // 判据引擎模块：python -m <module>
  "atoms": {
    "kinds": ["definition", "theorem", "lemma", "example"],
    "example_policy": "numbered_only",                  // 哪些例子开原子
    "partial_policy": "witness_required",               // partial 必须带 witness
    "required_fields": ["id", "kind", "quote", "loc", "lean"]
  },
  "judge": {
    "base_candidate": "knowledge/pipeline/base_candidate.json",
    "forbidden_list": "knowledge/pipeline/基底.json",
    "scope_extras": "knowledge/pipeline/基底.json#scope_extras",
    "extensions": []                                    // 追加式，不可关闭 core 判据
  },
  "env": {                                              // 子进程环境（库外资源、书 id）
    "KL_BOOK_ID": "munkres-2e",
    "KL_BOOK_INDEX": "D:/…/book/index.json",
    "KL_BOOK_MD": "D:/…/book_md",
    "KL_BOOK_PDF": "D:/…/munkres.pdf"
  },
  "render": { "default_view": "atom", "language": "zh" },
  "contract_extras": "docs/契约补充.md"
}
```

**路径解析约定**（实现里硬性如此，避免"相对谁"的歧义）：

```
paths.repo          相对 profile 文件所在目录（或绝对路径）
其余所有相对路径     相对 paths.repo（= 仓库根）
绝对路径            原样使用（库外资源：PDF / 转录 / 中文版目录索引）
```

**core 的校验分两档**（负向测试覆盖）：

| 档 | 时机 | 失败表现 |
|---|---|---|
| 结构校验 | plugin 加载时（`apply`） | **拒绝启动**：缺 `schema` / 主版本不符 / 缺 `book_id`、`paths.*`、`lean.lib`、`atom` 必填最小集…，错误里带具体字段名 |
| 资源存在性 | `pipeline_doctor` | **体检红**：`✗ paths.graph — <路径>`，指出字段名与路径；插件照常启动（资源没下完的仓库也要能体检） |

- `atoms.required_fields` 至少包含固定最小集 `id / kind / quote / loc / lean`（只能加不能减）；
- 未知键**允许**（前向兼容），但 core 必须忽略而不是猜测。

### 3.1 配置只有一个来源（引擎侧，A3 实测口径）

引擎（判据实现，如 `tools/kl`）不经过 DSH 插件也可能被直接调用（CLI / 批处理 / MCP），
所以它自己也要读 profile。做法是**一个环境变量 + 一个解析模块**：

```
KL_PROFILE = <book-profile.json>
   ↓ tools/kl/config.py（唯一解析点）
book_id / lib / namespace / repo / 清单目录 / 基底 / 图 / 术语表 / 页码索引 / 库外资源
   ↓ 并 setdefault 回填
KL_BOOK_ID / KL_BOOK_PDF / KL_BOOK_MD / KL_BOOK_INDEX / KL_LEAN_ROOT / KL_LEAN_LIB / ...
```

优先级：**环境变量 > profile > 仓库布局约定/探测**。没有 `KL_PROFILE` 时按布局约定运行
（库名从 `lakefile.toml` 的 `lean_lib` 探测、书 id 从 `knowledge/books/` 唯一一本探测、
仓库根由引擎文件位置推出）——即旧行为不受影响，一般化是可选的。

**排障命令**：`python -m kl.cli config` 打印解析后的全部路径（profile / 书 id / 库名 /
清单目录 / 图 / 术语表 / 页码索引）。要断言"换书只换 pack"，先看这一条输出。

**剩下的显式配置（有意不塞进 profile）**：

| 配置 | 为什么留在外面 |
|---|---|
| python 解释器 / `PYTHONPATH` | 机器级路径（引擎装在哪），与书无关 |
| `--lean-project-path`（Lean LSP） | 外部 exe 只吃命令行参数；加 wrapper 维护成本 > 收益（= `paths.repo`，一行） |
| mathlib 索引 DB | 工具级服务，所有书共用 |

---

## 4. 判据：哪些必须固定、哪些可配、哪些可加

这是 G4 的核心问题，答案分三类：

### 4.1 必须固定（core 拥有，不可关闭、不可替换语义）

| 判据 | 固定原因 |
|---|---|
| ① build | 定义"能编译"，是全部形式化的前提 |
| ② sorry / 公理白名单 | 定义"证完了"，不能由书决定 |
| ③a 基底概念禁提 | 定义"自造内容不被 mathlib 实现顶替" |
| ③a′ 陈述层基底范围 | 定义"借用了什么"，见 Q6 |
| ③b 判重 | 定义"不重证"，范围 = 基底 + 自库 |
| ③c quote 逐字 | 定义"清单 ↔ 转录一致" |
| ④ module 卫生 | 定义"库边界" |

**结构上的保证**：core 的判据不是插件注册进来的，book pack 无法移除/覆盖；
book pack 想改与判据相关的**参数**，只能改 §4.2 允许的参数文件（这些文件本身被 core 校验）。

### 4.2 可配参数（book pack 提供数据，core 消费）

| 参数 | 位置 | 说明 |
|---|---|---|
| 基底候选 | `judge.base_candidate` | 由内容层反向传播生成；换书自动重算 |
| 禁提清单 / scope_extras | `judge.forbidden_list` | 本书要自造哪些概念、额外允许哪些 |
| quote 页面范围 | 由 book config 派生 | 判据本身不变，范围来自书配置 |
| 判重目标名 | `lean.lib` | 只影响范围参数，不改判重语义 |
| 模块卫生根/聚合名 | `lean.lib` | 同上 |
| 原子必填字段 | `atoms.required_fields` | 只能**加**，不能减掉固定最小集 |

### 4.3 可扩展（book pack 追加，只加不删）

- 领域判据扩展：书/领域特有的一致性检查（例：图号引用、跨节编号、译文一致性）；
- 扩展必须：只读、确定性、带命名空间 id、失败时给出 `problems[]`；
- 扩展抛异常 = **门禁红**（不是忽略）：避免"扩展坏了看起来全绿"。

---

## 5. 领域判据扩展接口

```text
check(ctx) -> { ok: bool, problems: [string], details?: object }

ctx = {
  profile:  BookProfile            # §3
  section:  int                    # 当前节
  inventory: object                # sectionNN.json 的解析结果
  config:   object                 # book_config 的解析结果
  read(path) -> string             # 只读访问 repo 内文件
  run(cmd, args) -> object         # 受限子进程（可选；core 可拒绝）
}
```

约束（core 强制执行）：

1. **只加不删**：扩展不能声明"关闭某条核心判据"；没有这种 API；
2. **只读**：除临时目录外不得改 repo；违反 = 扩展失败；
3. **幂等**：同一输入多次运行结果一致；
4. **命名空间**：扩展 id 形如 `book.munkres2e.figure_ref`，输出问题里带 id；
5. **超时**：core 给每次扩展设定上限；超时 = 红。

---

## 6. 流程契约注入：core 文本 + book 补充

- core 提供**通用契约**（判据/五步/LSP/协作/停止条件/测量纪律）——与书无关；
- book pack 可提供 `contract-extras.md`，注入时附在 core 文本后面，标题固定为
  **【项目补充】**；
- 冲突规则：**core 优先**（书本补充不得与其矛盾；出现冲突视为 book pack 的 bug）；
- 补充文本的用途：本书特有的术语约定、章节组织、已知例外（如"本书 13/14 章装订对换，
  按物理页序"）、项目基准（book / mathlib）、权威文档指针，而不是重复通用规则。

> **实现现状（A1/A2）**：注入文本 = `core 契约 v6` 头行 + 通用正文 + `【项目补充】` 全文。
> core 契约版本号在 `pipeline_doctor` 首行打印；**改完契约必须重启 DSH**（契约在插件加载时
> 固化，与工具表同理）。
> 旧的独立「工作判据注入」插件已并入本机制：其中**通用**的测量/查证纪律进 core 正文，
> **本书**的工作基准（以原书为准、B 层边留在书内…）进 `契约补充.md`；插件本身停用。

---

## 7. 数据契约与版本兼容

core 消费的生成物（`sectionNN.json` / 探针 / `graph.json` / verdict）**schema 稳定**：

- 每个文件带 `schema` 版本；core 只接受同 major 版本，跨 major 拒绝并给迁移提示；
- `extensions`/未知键一律保留并忽略（book pack 不许把私有数据塞进必填字段）；
- 数据契约细节见 `architecture.md §4`。

---

## 8. 迁移路径（从现状到拆分）

| 步 | 动作 | 验收 | 状态 |
|---|---|---|---|
| A1 | 把 `dsh-munkres-pipeline` 的 Munkres 文案/路径改成从 profile 读 | 现有实例用 profile 能跑出**相同**的 gate/doctor 输出 | ✅ 2026-10-25 |
| A2 | 建 `book pack: munkres-2e`（profile / 契约补充 / 基底参数 / 渲染配置） | core 里 grep 不到 "Munkres"/中文书名/`knowledge/pipeline` 等硬编码 | ✅ 2026-10-25 |
| A3 | 通用化 `mcp-pipeline`（`kl` → pipeline，路径从 profile 取） | 全部 kl 工具在 munkres pack 下通过 | ✅ 2026-10-25（工具名保留 `kl_*`，见 §2） |
| A4 | 第二本书试点（最小：一节即可） | 只写 book pack + 填数据，core 零改动跑通 | 待做 |

**负向测试**（必须通过才算一般化成功）——A1/A2 的离线测试台已覆盖：

- 缺 `book-profile.json` 字段 ⟹ 拒绝启动（不默认猜测）；✅ `test/check.mjs` 覆盖
- profile 指向不存在的路径 ⟹ doctor 红，且错误信息指出具体字段名；✅ 覆盖
- 不认识的主版本 / 减掉原子必填最小集 ⟹ 拒绝启动；✅ 覆盖
- 未知键允许（前向兼容，core 忽略而不猜）；✅ 覆盖
- extension 抛异常 ⟹ gate 红；试图"关闭核心判据"⟹ 无 API 可实现（未实现包不测）。

**A1/A2 的验收证据**（同一份 core + 实例 profile）：

```
$ node test/check.mjs
✓ link-check  checked 70 条指针
✓ check       build 2.4s · axioms 70 条
✓ audit       items 13 · coverage 13/13 · mapping 70/70
--- doctor ---
[1/2] 书 profile（knowledge/book-profile.json）: 16 项路径全 ✓
[2/2] 判据引擎（python -m kl.cli doctor）: 13 项全 ✓
OK: pipeline-core 离线测试通过
```

`pipeline_gate(§19)` / `pipeline_doctor` 的输出与旧 Munkres 专用插件一致（工具名、步骤、
`steps/problems/next/report` 结构都不变，只是 report 头行多了书 id 与 core 契约版本）。

**A3 的验收证据**（引擎与 MCP 面均已 profile 驱动；`tools/kl` 里 60 处书硬编码已替换）：

```
kl config                    两种模式（无 / 有 KL_PROFILE）解析出相同路径
kl doctor                    无 profile 14 项全绿；有 profile 14 项全绿
kl check 19 --with-dup       ok，dup 397
kl audit 19 / link --check / quote-check 19    13/13 · 70 条 · 13/13
kl graph                     15 条断言全过；viz 渲染 131 原子 / 367 边正常
dsh-mcp-kl 配置              python / PYTHONPATH / KL_PROFILE / KL_PYLIBS（书数据不再写死）
dsh-graph-panel 配置         只留 profile（离线：profile 模式 200、回退模式 200、缺配置 404 带错）
```

---

## 9. 明确不做的事（边界）

- **不支持一个实例同时挂多本书**（G3：跨书原子同一性判定不可计算）——一个 profile 一本书；
- 不把 core 做成"配置万能的引擎"：核心判据语义不可配，否则"同样的 gate 在不同书里含义不同"；
- 不为 book pack 提供写权限（pack 是数据 + 只读扩展；写由 agent 通过管线工具进行）。
