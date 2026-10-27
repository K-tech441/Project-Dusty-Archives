# @local/dsh-pipeline-core

DSH 插件：**通用形式化管线核心**。把「与书无关」的那一半做进 DSH，
书相关的一切交给 **book profile**（一份 JSON）。

```
core   = 流程契约注入 + profile 加载/校验 + pipeline_gate + pipeline_doctor + CLI 桥
book   = book-profile.json（书 id/标题、仓库、数据路径、文档、CLI 模块、原子字段、环境变量）
        + contract_extras.md（本项目补充规则）
        + judge/ext（领域判据扩展，可选）
```

> 为什么这样切：判断标准一句话 —— **删掉这本书换另一本，它会不会变？会变的必须进 book pack。**
> 规范见 docrepo `docs/plugin-api.md`（G4）。

## 装了它得到什么

1. **系统提示段**（每次模型调用都注入，order=880）：
   - `core 契约 v7`：判据集（8 个子判定，只有判据引擎一处实现；意图/数据源/「不抓什么」见
     **判据引擎所在仓库**的 `docs/工程基准.md` §4）、每节五步、写证明的 LSP 内循环、
     协作与写作用域、debug 停止规则、收口标准 —— 全部与书无关；
   - 紧接着是【项目补充】：profile 里 `contract_extras` 指向的 markdown（本书的仓库/路径/
     本书特例/命令差异）。
2. **`pipeline_gate(section)`**：一次调用跑完收口三连：
   `link --check`（指针）→ `check --with-dup --update`（判据集 + ③b 判重，verdict 落盘）
   → `audit`（清单↔声明双向覆盖 + 必填 + 页码）。返回结构 verdict + next。
3. **`pipeline_doctor()`**：先校验 profile（字段 + 路径存在性，✗ 会指出字段名），
   再跑判据引擎的 doctor（聚合/探针/.ilean 同步/页码索引/基底候选/module 卫生/图数据）。

★ **判据不在本插件实现**：判据唯一实现是仓库的判据引擎（`python -m <cli.module> check`）。
本插件只做注入 + 聚合，任何判据逻辑都不许在这里重写。

## config

```yaml
- insert:
    - id: pipeline-core
      name: '@local/dsh-pipeline-core'
      config:
        enabled: true
        profile: D:/some-repo/knowledge/book-profile.json   # ★ 必填：这本书的实例描述
        python: D:/dsh-uv/tools/lean-lsp-mcp/Scripts/python.exe
        pylibs: D:/pylibs
        injectContract: true
        promptOrder: 880
        gateTimeoutMs: 900000
```

- `profile` 缺 → **拒绝启动**（不猜默认值）；
- profile 结构错 → 拒绝启动，错误里带字段名；
- profile 合法但路径缺失 → 仍启动，`pipeline_doctor` 报红并指出字段（资源没下完的仓库也要能体检）。

## book profile（最小形状）

```jsonc
{
  "schema": "book-profile/v1",
  "book_id": "some-book",
  "title": "…",
  "book_config": "knowledge/books/some-book.json",
  "paths": {
    "repo": "..",                       // 相对 profile 文件；其余路径相对仓库根
    "md": "…",                          // 转录目录（库外资源可用绝对路径）
    "inventory": "knowledge/pipeline",
    "order_table": "knowledge/pipeline/入序表.json",
    "base_lean": "Src/Base.lean",
    "graph": "knowledge/pipeline/graph.json",
    "glossary": "knowledge/glossary.json"
  },
  "docs": { "pipeline": "docs/管线.md", "baseline": "docs/工程基准.md" },
  "lean": { "lib": "Src", "toolchain_file": "lean-toolchain", "build_system": "lake" },
  "cli": { "module": "kl.cli" },        // 判据引擎模块（core 用 python -m 调它）
  "atoms": {
    "kinds": ["definition", "theorem", "lemma", "example"],
    "required_fields": ["id", "kind", "quote", "loc", "lean"]   // ⚠ 只能加不能减
  },
  "judge": {
    "base_candidate": "knowledge/pipeline/base_candidate.json",
    "forbidden_list": "knowledge/pipeline/基底.json",
    "scope_extras": "…",
    "extensions": []
  },
  "env": { "KL_BOOK_ID": "some-book" },  // 子进程环境（库外资源路径等）
  "contract_extras": "docs/契约补充.md",
  "render": { "default_view": "atom", "language": "zh" }
}
```

**路径解析约定**：`paths.repo` 相对 profile 文件所在目录；其余所有相对路径相对仓库根；
绝对路径原样使用（库外资源）。**未知键允许**（前向兼容，core 忽略而不猜）。

## 离线测试

```powershell
$node='C:\Users\Lenovo\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe'
& $node test/check.mjs
```

覆盖：profile 结构校验（正/负向）· 路径检查 · 契约拼装（core 无书名硬编码）·
apply 同步性与消费面 · 卸载可回收 · 真实跑一次 `pipeline_gate(确认节)` 与 `pipeline_doctor`
（真跑有副作用：会刷新 verdict 与聚合文件，测试前记录 git 状态、测试后还原干净文件）。

## 与旧插件的关系

`@local/dsh-munkres-pipeline` 是「Munkres 专用」版本（契约里写死书名/仓库路径）。
本插件是它的一般化替代：**同一套工具名与行为**，但书的信息全部来自 profile。
切换方式：装本插件 + 禁用旧插件 + 重启 DSH（工具名相同，不能同时启用）。

改契约文本后必须重启 DSH：`pipeline_doctor` 首行会打印 `core 契约 vN`，
与 `lib/impl.cjs` 的 `CORE_CONTRACT_VERSION` 一致才算加载成功。
