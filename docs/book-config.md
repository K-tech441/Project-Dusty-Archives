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

  "sections": [
    { "number": 12, "title_en": "Topological Spaces",           "title_zh": "拓扑空间",
      "ranges": { "en_printed": [75, 78],  "zh_printed": [58, 59] } },
    { "number": 13, "title_en": "Basis for a Topology",         "title_zh": "拓扑的基",
      "ranges": { "en_printed": [78, 84],  "zh_printed": [60, 63] } },
    { "number": 14, "title_en": "The Order Topology",           "title_zh": "序拓扑",
      "ranges": { "en_printed": [84, 86],  "zh_printed": [64, 65] } },
    { "number": 15, "title_en": "The Product Topology on X×Y",  "title_zh": "X×Y上的积拓扑",
      "ranges": { "en_printed": [86, 88],  "zh_printed": [66, 67] } },
    { "number": 16, "title_en": "The Subspace Topology",        "title_zh": "子空间拓扑",
      "ranges": { "en_printed": [88, 92],  "zh_printed": [68, 70] } },
    { "number": 17, "title_en": "Closed Sets and Limit Points", "title_zh": "闭集与极限点",
      "ranges": { "en_printed": [92, 102], "zh_printed": [71, 77] } },
    { "number": 18, "title_en": "Continuous Functions",         "title_zh": "连续函数",
      "ranges": { "en_printed": [102, 112], "zh_printed": [78, 85] } },
    { "number": 19, "title_en": "The Product Topology",         "title_zh": "积拓扑",
      "ranges": { "en_printed": [112, 118], "zh_printed": [86, 90] } }
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
| `sections[]` | array | ✓ | 每节一条；按 `number` 升序 |
| `sections[].number` | int | ✓ | 节号 |
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
| V1 | `schema`/`book_id`/`title` 存在；`sections` 非空且按 `number` 严格升序 | 配置不完整 |
| V2 | 每个源有 `path`；`kind` 合法；若给 `md_dir`，目录存在 | 路径/类型错 |
| V3 | 每节至少一个源的 `ranges`；`起 ≤ 止`；落在该源已知页数内 | 数据填错 |
| V4 | 同源相邻两节的区间不重叠；除 `shared_pages=true` 时允许共享**一个**边界页 | 页码范围错 |
| V5 | `heading_page_must_be_in_range`：在该源 md/PDF 文本里能找到节标题，且其页 ∈ 本节范围 | **边界页归属错**（最常见的坑） |
| V6 | md 源：范围内每个 `p####.md` 文件存在 | 转录缺失 |
| V7 | 未知键不报错（前向兼容）；`extensions` 原样保留 | 实现更新/迁移 |

> V5 是这套 schema 存在的主要理由：页码数据人填得对，但"节边界到底包含哪一页"最容易错，
> 而它是可以机械查的——标题在哪页、页范围有没有把它包住。

---

## 5. 人怎么填（换书时）

1. 拿**英文原书**和（可选）**中译本**，各翻到目录；
2. 每一节抄两件事：该节在英文原书的**印刷页范围**、在中译本的**印刷页范围**；
3. 抄两个偏移：英文"印刷页→PDF 页 = +2"、中译"印刷页→PDF 页 = +11"（从两本书各抽 2–3 页验证）；
4. 填进 `sections[]` 与 `sources{}`，跑 V1–V6 校验；
5. 校验过 ⟹ 生成页码索引 ⟹ 之后所有页码引用只从索引取。

**不要做的事**：不要用 AI 猜页码范围（人查目录比 AI 可靠得多）；不要把派生区间写回配置；
不要为了"看起来齐"去改书上的页码。

---

## 6. 实现自由

- 序列化格式自由：JSON / YAML / CSV（一行一节）；只要映射到上面的结构即可；
- 多个源、额外语言版本：加 `sources` 键、给每节加对应 `ranges` 即可，无需改 schema；
- 只做英文单源时：删掉 `zh` 源与对应 `ranges`，其余不变；
- 工具消费方（生成页码索引、`book` 查询、`book-locate`）只需要 schema 里的数据，
  **不需要知道**书配置是怎么编辑/存储的。
