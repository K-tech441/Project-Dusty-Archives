# 书配置 schema（v1）

> **定位**：书配置是一份**纯数据**——"这本书有多少节、每节对应各版本的哪几页"。
> 它不规定实现方式：JSON / YAML / 表格 / CSV 都行，工具只是按这个结构消费它。
> 设计目标就一个：**把页码对应关系结构化，让机器能机械核对**；填数据本身是人的活
>（人拿着两本书的目录，几分钟就能填完；让 AI 去猜页码反而是更差的方案）。

---

## 1. 它解决什么

后面的每一层都要回答"这节在书的哪几页"：

- 转录：要读 md 页 `p####.md`（#### = **英文 PDF 页号**）；
- 原子化：`loc`/`book_ref` 写"印刷页 p.113"，要能换算出 md 页；
- 抽查：人翻书核对时看的是**印刷页**，工具要能定位到对应 PDF/扫描页；
- 多版本：中译本是另一套页码（另一个 PDF、另一套印刷页）。

这些换算规则集中在一处 = 书配置。它**只存原始数据**（人能从书上读到的页码），
不存派生值（md 页区间、PDF 页区间由偏移算出；生成物是页码索引，不是配置的一部分）。

---

## 2. 最小结构（真实例子：Munkres 2e）

下方是实例工程的实际数据（照抄可跑）。注意两种源各有自己的偏移：

```json
{
  "schema": "book-config/v1",
  "book_id": "munkres-2e",
  "title": "Topology, 2nd edition / 拓扑学（原书第2版）",
  "edition": "2nd",
  "languages": ["en", "zh"],

  "sources": {
    "en": {
      "path": "book/munkres_en.pdf",
      "kind": "pdf_text",
      "printed_to_pdf": 2,
      "md_dir": "book/md",
      "md_pattern": "p{page:04d}.md",
      "md_page": "pdf"
    },
    "zh": {
      "path": "book/munkres_zh_scan.pdf",
      "kind": "pdf_scan",
      "printed_to_pdf": 11
    }
  },
  "default_source": "en",

  "chapters": [
    { "number": 2, "title_en": "Topological Spaces and Continuous Functions",
      "title_zh": "拓扑空间和连续函数" }
  ],

  "sections": [
    { "number": 12, "chapter": 2, "title_en": "Topological Spaces",
      "title_zh": "拓扑空间", "ranges": { "en_printed": [75, 78], "zh_printed": [58, 59] } },
    { "number": 13, "chapter": 2, "title_en": "Basis for a Topology",
      "title_zh": "拓扑的基", "ranges": { "en_printed": [78, 84], "zh_printed": [60, 63] } },
    { "number": 14, "chapter": 2, "title_en": "The Order Topology",
      "title_zh": "序拓扑", "ranges": { "en_printed": [84, 86], "zh_printed": [64, 65] } },
    { "number": 15, "chapter": 2, "title_en": "The Product Topology on X×Y",
      "title_zh": "X×Y上的积拓扑", "ranges": { "en_printed": [86, 88], "zh_printed": [66, 67] } },
    { "number": 16, "chapter": 2, "title_en": "The Subspace Topology",
      "title_zh": "子空间拓扑", "ranges": { "en_printed": [88, 92], "zh_printed": [68, 70] } },
    { "number": 17, "chapter": 2, "title_en": "Closed Sets and Limit Points",
      "title_zh": "闭集与极限点", "ranges": { "en_printed": [92, 102], "zh_printed": [71, 77] } },
    { "number": 18, "chapter": 2, "title_en": "Continuous Functions",
      "title_zh": "连续函数", "ranges": { "en_printed": [102, 112], "zh_printed": [78, 85] } },
    { "number": 19, "chapter": 2, "title_en": "The Product Topology",
      "title_zh": "积拓扑", "ranges": { "en_printed": [112, 118], "zh_printed": [86, 90] } }
  ],

  "boundary_policy": {
    "shared_pages": true,
    "heading_page_must_be_in_range": true
  },
  "extensions": {}
}
```

由它机械派生的东西（**不写进配置**）：

```
en_pdf  = en_printed + printed_to_pdf(2)      → §12: 77–80，§19: 114–120
md 页   = en_pdf（md_page = "pdf"）            → §12: p0077–p0080
zh_pdf  = zh_printed + printed_to_pdf(11)      → §12: 69–70
```

### 2.1 两种等价填法（实现现状：本实例用的是「提取式」）

上面的 `ranges` 是**人填式**：人从目录抄每节的印刷页范围。另一种是**提取式**：
PDF 有文字层时，页码范围可以由程序从**页眉/页脚**机械提取，人只提供提取参数。
两种填法的产物相同——都是生成物 `index.json` 里的「每节五坐标范围」，
判据也只看生成物。本实例实际用的是提取式：

```json
// knowledge/books/<id>.json —— 提取参数（不是页码本身）
{
  "sources": {
    "en": {
      "kind": "pdf_text",
      "pdf_env": "KL_BOOK_PDF", "md_env": "KL_BOOK_MD",
      "md_name_pattern": "^p(\\d{4})\\.md$", "md_page_source": "pdf_page"
    },
    "zh": { "kind": "scanned_pdf_index", "index_env": "KL_BOOK_INDEX" }
  },
  "folio": {
    "head_lines": 3, "foot_lines": 2,
    "patterns": ["^(\\d{1,3})\\s+[A-Z§]", "\\s(\\d{1,3})\\s*$", "^(\\d{1,3})$"]
  },
  "sections": { "patterns": ["^§\\s*(\\d{1,2})\\s+[A-Z]", "^§\\s*(\\d{1,2})\\b"] }
}
```

| 填法 | 适用 | 谁给出范围 | 校验 |
|---|---|---|---|
| 人填式（§2） | 扫描件 / 无文字层 / 无 PDF | 人抄目录的印刷页范围 | V1–V9（尤其 V5 标题页在范围内） |
| 提取式（本节） | 有文字层的 PDF（本实例） | `book-build` 从页眉机械提取 | 提取器自检 + V5 的等价检查（doctor「页码索引」项：节标题页必须在 md 范围内） |

`book-build` 的输出（查询唯一入口）：

```
knowledge/books/<id>/index.json
  sources / offsets        每源偏移（分段：如本实例前附页偏移 4、正文 2）
  pages                    pdf ↔ 印刷 每页对照
  page_section             每页所属节（OCR 噪声下仅供参考，不作判据）
  sections                 每节五坐标范围：en_printed / en_pdf / md / zh_printed / zh_pdf
  figures                  图号 → 页（图题行整行匹配）
```

> 为什么把"人填"写成 §2 的主形态、实现却用提取式：`ranges` 是**schema**（通用、可手填、
> 无依赖）；提取是**工具**（有文字层时更少人工错误）。schema 不规定实现方式（§6）。
> 约定不变：**配置只存原始数据/提取参数，区间是生成物**。

### 2.5 特殊情况：章号 ≠ 页序（必须支持）

书是物理装订的：**章/节的数字标签与它们在书里出现的先后顺序不一定一致**。
已知实例：某英文书的**第 13、14 章在装订顺序上是对换的**（14 章页面排在 13 章之前）。
因此 schema 的顺序规则是硬的：

- `chapters[]` 与 `sections[]` 都**按物理页序排列**（按 `default_source` 的起始 PDF 页升序）；
- `number` 只是标签，**不要求单调递增**；想"按章号查看"由工具排序，不依赖数组顺序；
- **禁止实现假设"编号递增 ⟹ 页码递增"**——这是最容易写错的隐含假设。

示意（14 章先出现、13 章后出现：数字不单调，物理序正确）：

```json
"chapters": [
  { "number": 14, "title_en": "...", "ranges": { "en_printed": [78, 84] } },
  { "number": 13, "title_en": "...", "ranges": { "en_printed": [84, 90] } }
]
```

同类特殊情况还有：附录/补遗（`number` 可用字符串 `"A"`）、多卷本（卷内页码重排）、
前言用罗马页码（页码映射可在 `extensions` 里分段描述）。这些都**不影响**主结构，
只要求"按物理顺序登记 + 数字仅作标签"。

---

## 3. 字段表

| 字段 | 类型 | 必填 | 含义 / 约束 |
|---|---|---|---|
| `schema` | string | ✓ | 固定 `"book-config/v1"`；迁移用 |
| `book_id` | string | ✓ | 目录命名/实例 id；一个实例一个 id |
| `title` / `edition` | string | title ✓ | 只给人看，工具不解析 |
| `languages` | string[] | | 有哪几种语言的版本 |
| `sources` | object | ✓ | 至少一个源；键 = 源 id（`en`/`zh`/…） |
| `sources.<id>.path` | string | ✓ | PDF 路径（相对配置文件或绝对路径） |
| `sources.<id>.kind` | enum | ✓ | `pdf_text` / `pdf_scan` / `md_dir` |
| `sources.<id>.printed_to_pdf` | int | ✓* | 印刷页 → PDF 页偏移；*或改用逐节显式 `ranges` |
| `sources.<id>.md_dir` / `md_pattern` / `md_page` | string | | 该源的转录产物位置；`md_page` ∈ `{pdf, printed}` |
| `default_source` | string | | md 的页码基准源；缺省 = 唯一源 |
| `chapters[]` | array | | 可选；**按物理页序**；章号仅标签（可不单调） |
| `chapters[].number` | int \| string | ✓ | 章号（附录可用 `"A"`）；唯一 |
| `chapters[].title_en` / `title_zh` | string | | 给人看的标题 |
| `chapters[].ranges` | object | | 可选；章页码范围；若给，节范围必须落在章内 |
| `sections[]` | array | ✓ | 每节一条；**按物理页序**（不是按 `number` 升序） |
| `sections[].number` | int \| string | ✓ | 节号（标签，可不单调：§14 可排在 §13 前）；唯一 |
| `sections[].chapter` | int \| string | | 所属章（引用 `chapters[].number`；可选） |
| `sections[].title_en` / `title_zh` | string | | 给人看的标题（可选，便于人查） |
| `sections[].ranges` | object | ✓ | 键 = `<源id>_printed` 或 `<源id>_pdf`；值 = `[起, 止]`（**闭区间**，含两端） |
| `boundary_policy.shared_pages` | bool | | 相邻节是否允许共享边界页（实测常见：节末页 = 下节首页所在页） |
| `boundary_policy.heading_page_must_be_in_range` | bool | | 节标题所在页必须落在本节范围内（最有效的边界检查） |
| `extensions` | object | | 实现自由放扩展数据；工具应忽略未知键 |

**不放进配置的东西**（保持"数据纯"）：OCR 模型/版本、提示词、工具命令、md 生成时间、
页码索引（那是生成物）、任何派生区间。

---

## 4. 机械校验清单（建议实现，不限定实现方式）

| # | 校验 | 失败含义 |
|---|---|---|
| V1 | `schema`/`book_id`/`title` 存在；`sections` 非空且**按物理页序**（起始 PDF 页升序，不是按 `number` 升序）；`chapters`/`sections` 的 `number` 各自唯一 | 配置不完整/顺序错 |
| V2 | 每个源有 `path`；`kind` 合法；若给 `md_dir`，目录存在 | 路径/类型错 |
| V3 | 每节至少一个源的 `ranges`；`起 ≤ 止`；落在该源已知页数内 | 数据填错 |
| V4 | 同源相邻两节的区间不重叠；除 `shared_pages=true` 时允许共享**一个**边界页 | 页码范围错 |
| V5 | `heading_page_must_be_in_range`：在该源 md/PDF 文本里能找到节标题，且其页 ∈ 本节范围 | **边界页归属错**（最常见的坑） |
| V6 | md 源：范围内每个 `p####.md` 文件存在 | 转录缺失 |
| V7 | 未知键不报错（前向兼容）；`extensions` 原样保留 | 实现更新/迁移 |
| V8 | **章/节号与页序不一致不报错**（如 14 章排在 13 章前）：按物理序分配范围；数字乱序是允许的 | 误报（实现假设编号单调） |
| V9 | `sections[].chapter` 必须存在于 `chapters[]`；若章给了 `ranges`，节范围必须落在章范围内 | 层级/范围错 |

> V1/V8 是这套 schema 的"防错核心"：**顺序 = 物理页序，数字 = 标签**。
> V5 是它存在的主要理由：页码数据人填得对，但"节边界到底包含哪一页"最容易错，
> 而它是可以机械查的——标题在哪页、页范围有没有把它包住。

---

## 5. 人怎么填（换书时）

1. 拿**英文原书**和（可选）**中译本**，各翻到目录；
2. 先按**物理装订顺序**列章（数字照抄；若章号与页序不一致，如英文书 13/14 章对换，
   就按页序排、数字照原样写）；
3. 每一节抄两件事：该节在英文原书的**印刷页范围**、在中译本的**印刷页范围**；
   节也按物理页序排（同样不要求节号递增）；
4. 抄两个偏移：英文"印刷页→PDF 页 = +2"、中译"印刷页→PDF 页 = +11"（从两本书各抽 2–3 页验证）；
5. 填进 `chapters[]`/`sections[]` 与 `sources{}`，跑 V1–V9 校验；
6. 校验过 ⟹ 生成页码索引 ⟹ 之后所有页码引用只从索引取。

**不要做的事**：不要用 AI 猜页码范围（人查目录比 AI 可靠得多）；不要把派生区间写回配置；
不要为了"看起来齐"去改书上的页码。

---

## 6. 实现自由

- 序列化格式自由：JSON / YAML / CSV（一行一节）；只要映射到上面的结构即可；
- 多个源、额外语言版本：加 `sources` 键、给每节加对应 `ranges` 即可，无需改 schema；
- 只做英文单源时：删掉 `zh` 源与对应 `ranges`，其余不变；
- 工具消费方（生成页码索引、`book` 查询、`book-locate`）只需要 schema 里的数据，
  **不需要知道**书配置是怎么编辑/存储的。
