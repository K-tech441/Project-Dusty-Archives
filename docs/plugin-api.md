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

| 目标包 | 职责 | 来源（当前实现） |
|---|---|---|
| `pipeline-core` | 注入流程契约；`pipeline_gate` / `pipeline_doctor`；加载并校验 book profile；CLI 桥 | `dsh-munkres-pipeline`（去掉 Munkres 文案/路径硬编码） |
| `pipeline-book-<id>` | 书配置 + 原子口径 + 基参数 + 领域判据扩展 + 渲染配置 + 项目文案 | 当前仓库里的 `knowledge/`、`基底.json`、`glossary`、`docs` 相关部分 |
| `mcp-pipeline` | 通用 MCP：清单/判据/图/页码查询（原 `kl` 工具面） | `dsh-mcp-kl` / `tools/kl` |
| `mcp-lean` | Lean LSP 工具面（项目路径可配） | `dsh-mcp-lean` |
| `mcp-mathlib` | 本地 mathlib 检索索引 | `dsh-mcp-mathlib` |
| `graph-panel` | 图渲染（读 `graph.json` + 渲染配置） | `dsh-graph-panel` |
| （可选）`compact-control` | 上下文压缩控制（与书无关） | `dsh-compact-control` |
| （独立族）`class-*` | 教学/授课插件（不属于本管线主链） | `dsh-munkres-class` |

一个 **book pack** 就是一个目录（可独立发版/复用），至少包含：

```
book-profile.json      # 实例描述（见 §3）
judge/ext/*.py|*.js    # 领域判据扩展（可选，见 §5）
contract-extras.md     # 项目补充规则（可选，见 §6）
render.json            # 图渲染配置（可选）
```

---

## 3. BookProfile：core 与 book 之间的唯一契约

core 只认这一份文件；其余路径、名字、口径都由它给出。

```jsonc
{
  "schema": "book-profile/v1",
  "book_id": "munkres-2e",
  "book_config": "knowledge/book.json",        // 书配置（book-config/v1，见 book-config.md）

  "paths": {
    "repo": ".",                                // 仓库根（相对 profile 或绝对）
    "md": "book/md",                            // 转录目录
    "inventory": "knowledge/pipeline",          // sectionNN.json / 入序表 / 基底.json
    "base_lean": "MunkresLean/Base.lean",       // 基底唯一入口
    "graph": "knowledge/pipeline/graph.json",
    "glossary": "knowledge/glossary.json"
  },
  "lean": {
    "lib": "MunkresLean",                       // 聚合文件 = <lib>.lean
    "toolchain_file": "lean-toolchain"
  },
  "atoms": {
    "kinds": ["definition", "theorem", "example", "proposition"],
    "example_policy": "numbered_only",           // 哪些例子开原子
    "partial_policy": "witness_required",        // partial 必须带 witness
    "required_fields": ["id", "kind", "quote", "loc", "lean"]
  },
  "judge": {
    "base_candidate": "knowledge/pipeline/base_candidate.json",
    "forbidden_list": "knowledge/pipeline/基底.json",
    "scope_extras": "knowledge/pipeline/基底.json#scope_extras",
    "extensions": ["judge/ext/*.py"]             // 追加式，不可关闭 core 判据
  },
  "render": { "default_view": "atom", "language": "zh" },
  "contract_extras": "contract-extras.md"
}
```

**core 的校验**（profile 加载即查，失败 = 拒绝启动，不静默降级）：

- `schema` 必须是它支持的 major 版本；
- `paths.*` 必须存在（repo/md/inventory/base_lean/graph/glossary）；
- `lean.lib` 与聚合文件存在；`toolchain_file` 存在；
- `atoms.required_fields` 至少包含固定最小集（见 §4 不可变清单）；
- `judge.*` 指向的文件存在；extensions 能加载；
- 未知键**允许**（前向兼容），但 core 必须忽略而不是猜测。

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

- core 提供**通用契约**（判据/五步/LSP/协作/停止条件）——与书无关；
- book pack 可提供 `contract-extras.md`，注入时附在 core 文本后面，标题固定为
  **【项目补充】**；
- 冲突规则：**core 优先**（书本补充不得与其矛盾；出现冲突视为 book pack 的 bug）；
- 补充文本的用途：本书特有的术语约定、章节组织、已知例外（如"本书 13/14 章装订对换，
  按物理页序"），而不是重复通用规则。

---

## 7. 数据契约与版本兼容

core 消费的生成物（`sectionNN.json` / 探针 / `graph.json` / verdict）**schema 稳定**：

- 每个文件带 `schema` 版本；core 只接受同 major 版本，跨 major 拒绝并给迁移提示；
- `extensions`/未知键一律保留并忽略（book pack 不许把私有数据塞进必填字段）；
- 数据契约细节见 `architecture.md §4`。

---

## 8. 迁移路径（从现状到拆分）

| 步 | 动作 | 验收 |
|---|---|---|
| A1 | 把 `dsh-munkres-pipeline` 的 Munkres 文案/路径改成从 profile 读 | 现有实例用 profile 能跑出**相同**的 gate/doctor 输出 |
| A2 | 建 `book pack: munkres-2e`（book config / 基底参数 / glossary seed / render 配置 / 文案） | core 里 grep 不到 "Munkres"/中文书名/`knowledge/pipeline` 等硬编码 |
| A3 | 通用化 `mcp-pipeline`（`kl` → pipeline，路径从 profile 取） | 全部 kl 工具在 munkres pack 下通过 |
| A4 | 第二本书试点（最小：一节即可） | 只写 book pack + 填数据，core 零改动跑通 |

**负向测试**（必须通过才算一般化成功）：

- 缺 `book-profile.json` 字段 ⟹ 拒绝启动（不默认猜测）；
- extension 抛异常 ⟹ gate 红；
- 试图"关闭核心判据"⟹ 无 API 可实现；
- profile 指向不存在的路径 ⟹ doctor 红，且错误信息指出具体字段。

---

## 9. 明确不做的事（边界）

- **不支持一个实例同时挂多本书**（G3：跨书原子同一性判定不可计算）——一个 profile 一本书；
- 不把 core 做成"配置万能的引擎"：核心判据语义不可配，否则"同样的 gate 在不同书里含义不同"；
- 不为 book pack 提供写权限（pack 是数据 + 只读扩展；写由 agent 通过管线工具进行）。
