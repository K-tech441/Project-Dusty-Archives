# -*- coding: utf-8 -*-
"""kl_mcp —— 把流水线暴露成 MCP 工具（LLM 用：一次调用 → 结构化 JSON）。

## 与 mpipe 的工具对照

```
去掉  mpipe_prompt   提示词模板没被用到（§12 试运行）
去掉  mpipe_trace    超时 + 历史残留
改名  mpipe_sections → kl_sections（并给缺口）
新增  kl_next        入序表拓扑序的下一个可写节（§12 之后「下一步写哪」不再靠问人）
新增  kl_book        页码五栏自动定位（§12 里页码口径混过三次）
新增  kl_audit       清单 ↔ 声明双向覆盖 + 必填字段（防漏登记/幽灵条目）
新增  kl_figure      图机械解码（§12 最贵的一课）
保留  kl_status / kl_check / kl_decls(并入 audit)
```

## 判据只在 kl_check 一处实现

不要用 grep / 临时脚本代替它 —— 四判据全在里面，且返回的是结构化 verdict。

运行：`<python> -m kl.mcp`（由 dsh-mcp-client 拉起）
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Annotated

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from mcp.server.mcpserver import MCPServer  # noqa: E402
from pydantic import Field  # noqa: E402

from kl import checks, config, figures  # noqa: E402
from kl.model import (Book, Section, base_table_path, inventory_path,  # noqa: E402
                      load_json, order_table_path, pipeline_dir)

REPO_ROOT = checks.REPO_ROOT

# 判据写入的【来源戳】（2026-10-25 幽灵事件：11:32:46 有一次 `check 13 --update` 无法归因
# —— 会话日志不存工具参数、CLI/MCP/哪个会话都分不清）。CLI 入口把 ORIGIN 改成 "cli"，
# 其余（MCP 工具 / pipeline_gate 走的也是 CLI）保持 "mcp"；verdict.by 记录它 + 会话 id / cwd / pid。
ORIGIN = "mcp"


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _lean_root(section: Section | None = None) -> str:
    if section is not None and section.project_root:
        return section.project_root
    return os.environ.get("KL_LEAN_ROOT", checks.DEFAULT_LEAN_ROOT)


def _load(section: int) -> Section:
    p = inventory_path(REPO_ROOT, section)
    if not os.path.exists(p):
        raise FileNotFoundError(f"清单不存在：{p}（先 kl_init {section}）")
    return Section.load(p)


def _rel_to_mod(rel: str) -> str:
    return rel.replace("\\", "/").removesuffix(".lean").replace("/", ".")


def _forbidden() -> list[str]:
    d = load_json(base_table_path(REPO_ROOT), {}) or {}
    return list(d.get("forbidden_so_far") or [])


mcp = MCPServer(
    name="kl Pipeline v4",
    version="4.0.0",
    instructions=(
        "形式化管线（知识层）v4。每节单一事实源是清单目录下的 sectionNN.json（位置见 kl config）。"
        "顺序：kl_book 定位 → kl_init 建清单 → 读英文 md 填条目 → 写 Lean → kl_check 跑四判据 → kl_audit 收口。"
        "四判据只有 kl_check 一处实现（build / sorry+axioms / ③a 提及禁止清单 / ③b 判重[基底+自库]）；"
        "不要自己写 grep 或临时脚本代替。图一律先 kl_figure 机械解码，不要靠眼睛读扫描件。"
    ),
)


# ---------------------------------------------------------------- 索引/进度

@mcp.tool()
def kl_sections() -> str:
    """List section inventories on disk with status counts and gaps (JSON).

    Returns [{section, title, items, coverage, status_counts, has_lean}].
    """
    d = pipeline_dir(REPO_ROOT)
    out = []
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if not (fn.startswith("section") and fn.endswith(".json")):
                continue
            try:
                sec = Section.load(os.path.join(d, fn))
            except Exception as e:  # noqa: BLE001
                out.append({"file": fn, "error": f"{type(e).__name__}: {e}"})
                continue
            done, total = sec.coverage()
            out.append({
                "section": sec.section, "title": sec.title,
                "items": total, "coverage": f"{done}/{total}",
                "status_counts": {k: v for k, v in sec.by_status().items() if v},
                "files": sec.files(),
                "checked_at": (sec.verdict or {}).get("at", ""),
            })
    return _dump(out)


@mcp.tool()
def kl_next() -> str:
    """按入序表算「下一个该写的节」：depends 全部 done 的 todo 项所在的最早一节。

    Returns JSON: {next_sections:[...], blocked:[{section, waits_for}], order_table:path}.
    """
    order = load_json(order_table_path(REPO_ROOT), {}) or {}
    base = {b.get("id"): b for b in order.get("base", [])}
    content = order.get("content", [])
    status = {c.get("id"): str(c.get("status") or "todo") for c in content}
    done = {k for k, v in status.items() if v and v != "todo"}

    def ok_dep(dep: str) -> bool:
        return dep in done or dep in base

    ready, blocked = [], []
    for c in content:
        if status.get(c.get("id")) not in (None, "todo"):
            continue
        waits = [d for d in (c.get("depends") or []) if not ok_dep(d)]
        row = {"id": c.get("id"), "name": c.get("name"),
               "book_ref": c.get("book_ref"), "depends": c.get("depends") or []}
        if waits:
            blocked.append({**row, "waits_for": waits})
        else:
            ready.append(row)
    # 同一节只报一次，取节号最小的
    next_sections = []
    for r in sorted(ready, key=lambda x: int(x.get("book_ref") or 999)):
        if r["book_ref"] not in next_sections:
            next_sections.append(r["book_ref"])
    return _dump({
        "next_sections": next_sections[:4],
        "ready_items": ready[:12],
        "blocked": blocked[:12],
        "order_table": order_table_path(REPO_ROOT),
    })


@mcp.tool()
def kl_status(
    section: Annotated[int, Field(description="节号，例如 12")],
) -> str:
    """One section's progress + gaps (missing quote/identity_decl/names, files, verdict age)."""
    sec = _load(section)
    root = _lean_root(sec)
    gaps = []
    for it in sec.items:
        for p in it.problems():
            gaps.append(f"{it.id}: {p}")
    book_gap = [f"book.{k}" for k in sec.book.missing()]
    files = [{"file": f, "exists": os.path.exists(os.path.join(root, f))}
             for f in sec.files()]
    done, total = sec.coverage()
    return _dump({
        "section": sec.section, "title": sec.title,
        "lean_project": root,
        "inventory": inventory_path(REPO_ROOT, section),
        "book": sec.book.to_dict(),
        "status_counts": {k: v for k, v in sec.by_status().items() if v},
        "coverage": f"{done}/{total}",
        "files": files,
        "gaps": gaps[:30],
        "book_gaps": book_gap,
        "verdict": sec.verdict,
        "items": [{"id": it.id, "kind": it.kind, "book_ref": it.book_ref,
                   "status": it.lean.status, "names": it.lean.names}
                  for it in sec.items],
    })


# ---------------------------------------------------------------- 建清单

@mcp.tool()
def kl_book(
    section: Annotated[int, Field(description="节号，例如 12 或 13")],
    write: Annotated[bool, Field(
        description="是否把定位结果写回清单的 book 五栏（默认 false，只报不改）")] = False,
) -> str:
    """一节的五坐标页码（读 `knowledge/books/<id>/index.json`；由 `book-build` 生成）。

    索引里同时带：中译印刷/PDF（来自中译本目录）· 英文印刷/PDF（页眉机械提取，偏移是【算出来的】）
    · md 页（p####.md 的 #### = 英文 PDF 页）。换书改 `knowledge/books/<id>.json`。
    """
    loc = checks.locate(section)
    # 准备写回的五栏
    if "en_md" in loc:
        loc["md"] = loc.pop("en_md")
    if write:
        sec = _load(section)
        b = sec.book
        b.zh_printed = loc.get("zh_printed")
        b.zh_pdf = loc.get("zh_pdf")
        b.en_printed = loc.get("en_printed")
        b.en_pdf = loc.get("en_pdf")
        b.md = loc.get("md")
        sec.extra.pop("book_pages", None)
        sec.save(inventory_path(REPO_ROOT, section))
        loc["written_to"] = inventory_path(REPO_ROOT, section)
    return _dump(loc)


@mcp.tool()
def kl_init(
    section: Annotated[int, Field(description="节号，例如 13")],
    force: Annotated[bool, Field(description="清单已存在时是否覆盖（默认 false）")] = False,
) -> str:
    """Create an empty section inventory: book pages (auto-located) + 入序表 里该节的内容项.

    Then fill items from the English transcription (quote 必须逐字).
    """
    path = inventory_path(REPO_ROOT, section)
    if os.path.exists(path) and not force:
        return _dump({"ok": False, "error": f"清单已存在：{path}（force=true 覆盖）"})
    loc = checks.locate(section)
    # section_book() 的键是 "md"（en_md 是历史键）；此前只读 en_md，导致经 MCP kl_init 建的清单
    # book.md 恒为 null（2026-10-25 发现）。
    md = loc.get("md") or loc.get("en_md")
    book = Book(zh_printed=loc.get("zh_printed"), zh_pdf=loc.get("zh_pdf"),
                en_printed=loc.get("en_printed"), en_pdf=loc.get("en_pdf"), md=md)
    order = load_json(order_table_path(REPO_ROOT), {}) or {}
    pending = [c for c in order.get("content", [])
               if str(c.get("book_ref")) == str(section)]
    sec = Section(section=section, title=str(loc.get("zh_name") or ""), book=book)
    sec.extra["order_items"] = pending
    sec.save(path)
    return _dump({
        "ok": True, "inventory": path,
        "book": book.to_dict(), "book_summary": book.summary(),
        "order_items": pending,
        "next": "读英文 md（book.md 那几页）→ 逐条填 item（quote 逐字）；写完 kl_check 四判据",
    })


@mcp.tool()
def kl_book_locate(
    anchor: Annotated[str, Field(description="要定位的文字：如 'Lemma 13.4'、'Figure 12.1' 或一句引文")],
    limit: Annotated[int, Field(description="最多返回几条命中（默认 20）")] = 20,
) -> str:
    """条目级页码定位：在英文转录里搜文字，返回 md/pdf 页 + 印刷页 + 所属节 + 中译范围。

    用于回答「Definition 13.1 在书哪一页」「Figure 12.1 在哪」这类问题。
    ★ 命中分 caption（整行就是该文字：图题/条目名 ⟹ 实际所在页）/ heading（行首为该文字）
      / ref（正文引用）；图号另有索引 figures 直查（图题扫描结果，最可靠）。
    中译本是扫描件 ⟹ 中译只给到【节级范围】（精确项级定位要 OCR，见 docs/试运行反馈.md）。
    """
    return _dump(checks.locate_anchor(anchor, limit=limit))


# ---------------------------------------------------------------- 四判据

@mcp.tool()
def kl_check(
    section: Annotated[int, Field(description="节号，例如 12")],
    update: Annotated[bool, Field(
        description="是否回填 verdict 与 status（默认 false，只报不改）")] = False,
    with_dup: Annotated[bool, Field(
        description="是否跑 ③b 判重（基底+自库；实测 ≈11 s）。★ 必须与 update=true 同一次调用，"
                    "否则判重结果不落盘（跑过等于没跑）")] = False,
) -> str:
    """Run the four mechanical criteria and return one structured verdict.

    ① lake build · ② no sorry + axioms ⊆ {propext, Classical.choice, Quot.sound}
    ③a 我们的模块不得提及 基底.json.forbidden_so_far 里的 mathlib 名字
    ③b 判重（收口必跑）：import 只含 Base + 本库 ⟹ 范围 = 基底 + 自库（不对 mathlib 内容层）
    """
    sec = _load(section)
    root = _lean_root(sec)
    if not os.path.isdir(root):
        raise FileNotFoundError(f"Lean 工程根不存在：{root}")

    sync = checks.sync_root(root, sec.lean_lib or config.LIB)
    bres = checks.build(root)

    lib_dir = os.path.join(root, sec.lean_lib or config.LIB)
    sorries = []
    for fn in sorted(os.listdir(lib_dir)) if os.path.isdir(lib_dir) else []:
        if fn.endswith(".lean"):
            sorries.append(checks.count_sorries(os.path.join(lib_dir, fn)))
    sorries_total = sum(s["total"] for s in sorries)

    names: list[str] = []
    file_of: dict[str, str] = {}
    for it in sec.items:
        for n in it.lean.names:
            if n not in file_of:
                names.append(n)
                file_of[n] = it.lean.file

    axioms = None
    by_file: dict[str, list[str]] = {}
    for n in names:
        rel = file_of.get(n) or ""
        if rel:
            by_file.setdefault(rel, []).append(n)
    if by_file:
        merged: dict[str, list[str]] = {}
        unknown: list[str] = []
        for rel, ns in by_file.items():
            # ★ 用全限定名（不做短名映射：短名会撞）
            r = checks.check_axioms(root, rel, ns)
            merged.update(r.get("deps") or {})
            unknown.extend(r.get("unknown") or [])
        bad = {n: ax for n, ax in merged.items()
               if any(a not in checks.STANDARD_AXIOMS for a in ax)}
        axioms = {"checked": len(merged), "unknown": unknown, "bad": bad}

    modules = [_rel_to_mod(f) for f in sec.files()]
    forbidden = checks.forbidden_hits(modules, _forbidden()) if modules else []

    dup_report = None
    if with_dup:
        dup_report = checks.dup(root, [config.LIB + ".Base"] + modules)

    ok, problems = checks.summarize(bres, sorries, axioms, forbidden, dup_report)
    hygiene = checks.module_hygiene(root, sec.lean_lib or config.LIB)
    if not hygiene["ok"]:
        ok = False
        problems.extend("module 卫生: " + p for p in hygiene["problems"])
    scope = checks.base_scope(root, sec.lean_lib or config.LIB)
    if not scope.get("ok", False):
        ok = False
        if scope.get("error"):
            problems.append("③a′ 判不了：" + scope["error"])
        for v in scope.get("violations") or []:
            hint = ""
            if v["name"].startswith("Set."):
                hint = "（A 层可绕开：Set.range 成员用 ⟨x, rfl⟩、双重补集用 ext x; simp，"
                hint += "便利引理留在证明层不检查）"
            problems.append("③a′ 超出基底范围: " + v["name"]
                            + "（被 " + "、".join(v["used_by"]) + " 提及）" + hint)

    # ③c quote：清单里的英文 quote 必须在书的英文转录页里逐字（规范化后）找到。
    # 2026-10-25 补：此前「quote 逐字」只有人工信用，没有机械判据。
    quotes = checks.quote_check(sec)
    if not quotes.get("ok", True):
        ok = False
        problems.append("③c quote 与英文转录不符：" + "；".join(quotes.get("problems", [])[:3]))

    verdict = {
        "at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "by": {"origin": ORIGIN,
               "session": os.environ.get("DSH_SESSION_ID", ""),
               "cwd": os.getcwd(),
               "pid": os.getpid(),
               "ppid": os.getppid(),
               "argv": sys.argv},
        "ok": ok,
        "build": {"ok": bres.ok, "seconds": round(bres.seconds, 1),
                  "tail": "" if bres.ok else bres.tail},
        "sorries": {"total": sorries_total,
                    "files": {os.path.basename(s["file"]): s["total"] for s in sorries}},
        "axioms": axioms,
        "forbidden": forbidden[:40],
        "quotes": quotes,
        "dup": ({k: dup_report.get(k) for k in ("ran", "ok", "total", "seconds", "error", "ours")
                 if k in dup_report} if dup_report is not None else None),
        "problems": problems,
        "module_hygiene": hygiene,
        "base_scope": scope,
    }
    if update:
        sec.verdict = verdict
        sec.updated_at = verdict["at"]
        if ok:
            for it in sec.items:
                if it.lean.file and it.lean.status in ("pending", "skeleton"):
                    it.lean.status = "verified"
        sec.save(inventory_path(REPO_ROOT, section))
        verdict["written_to"] = inventory_path(REPO_ROOT, section)
    verdict["aggregate_changed"] = bool(sync.get("changed"))
    return _dump(verdict)


@mcp.tool()
def kl_link(
    section: Annotated[int, Field(description="节号，例如 12")],
    check: Annotated[bool, Field(description="只校验指针，不写回")] = False,
) -> str:
    """Fill/refresh the **Lean pointers** of every atom (向 Lean 的指).

    指针 = 全限定名 + 模块 + 起始位置（.ilean 的 decls）+ 签名文本哈希（探针）。
    ★ 清单引用声明一律用全限定名 + 模块解析，不做短名匹配（短名会撞，撞了静默错）。
    流程：lake build → 重跑两个探针 → kl_link（填指针）→ kl_audit（校验）。
    """
    sec = _load(section)
    root = _lean_root(sec)
    if check:
        rep = {"ok": not checks.verify_pointers(sec, root),
               "problems": checks.verify_pointers(sec, root),
               "checked": sum(len(a.lean.pointers) for a in sec.items)}
    else:
        # 聚合文件缺本节模块时给出明确下一步（2026-10-25 §16 复盘：worker 收口时遇到过
        # 「模块不在聚合 ⟹ probes/探针看不到它」的硬等待；这里把它变成一条机械提示）
        lib = sec.lean_lib or config.LIB
        agg_mods = checks.aggregate_modules(root, lib)
        want: list[str] = []
        for f in sec.files():
            rel = str(f).replace("\\", "/")
            if rel.endswith(".lean"):
                want.append(rel[:-5].replace("/", "."))
        # 聚合文件不存在（agg_mods 为空）时也提示先 sync-root：否则探针/图看不到本节
        missing = [m for m in want if m not in agg_mods]
        rep = checks.link_pointers(sec, root)
        filled = int(rep.get("filled") or 0)
        with_sig = int(rep.get("with_sig") or 0)
        if rep.get("ok", True) and filled > 0 and with_sig < filled:
            # ★ 静默半成功是最危险的形态：没签名范围 ⟹ 指针不完整，必须报失败
            rep["ok"] = False
            rep.setdefault("problems", []).append(
                f"签名范围缺失：{filled - with_sig}/{filled} 条拿不到签名哈希 "
                "⟹ 先 kl probes（重生成模块表）+ lake build + 两个探针，再 kl link")
            rep["next"] = ["python -m kl.cli probes", "lake build",
                           "lake env lean tools/lean-probes/DeclSigRanges.lean",
                           "lake env lean tools/lean-probes/StructEdges.lean"]
        if missing:
            rep["ok"] = False
            rep.setdefault("problems", []).append(
                "模块不在聚合文件（先 kl sync-root，否则探针/图看不到它）：" + "、".join(missing))
            rep["next"] = ["python -m kl.cli sync-root", "lake build"]
        sec.save(inventory_path(REPO_ROOT, section))
        rep["written_to"] = inventory_path(REPO_ROOT, section)
    rep["lean_project"] = root
    return _dump(rep)


@mcp.tool()
def kl_audit(
    section: Annotated[int, Field(description="节号，例如 12")],
) -> str:
    """Closing gate: 清单 ↔ Lean 声明双向覆盖 + 必填字段 + 页码五栏 + 声明清单.

    unregistered_decls = 文件里有、清单没登记（图里会丢节点）；
    ghost_names = 清单有、文件没有（改名/删了没回填）。
    ★ 声明一律用全限定名 + 模块解析（不做短名匹配）；每个引用必须有 Lean 指针。
    """
    sec = _load(section)
    root = _lean_root(sec)
    rep = checks.audit(sec, root)
    rep["lean_project"] = root
    rep["inventory"] = inventory_path(REPO_ROOT, section)
    rep["book"] = sec.book.to_dict()
    rep["book_summary"] = sec.book.summary()
    rep["declarations"] = [
        {"file": f, "decls": [fq for _k, fq in
                              checks.list_declarations(os.path.join(root, f))]}
        for f in sec.files() if os.path.exists(os.path.join(root, f))
    ]
    return _dump(rep)


@mcp.tool()
def kl_doctor() -> str:
    """管线体检（开工前先跑）：聚合/探针/.ilean/页码索引/基底候选/模块卫生 是否新鲜自洽。

    设计原则：**发现问题 ⟹ 立刻维护管线**（把坑变成这里的一项检查，或判据，或文档规则）。
    """
    return _dump(checks.doctor(checks.DEFAULT_LEAN_ROOT))


@mcp.tool()
def kl_stats() -> str:
    """一处汇总：原子 / 声明 / 图计数（文档引用它，避免手填漂移）。

    首次团队测试暴露：README 与工程基准里的实测数靠手工同步，发现者无权改、必漂。
    这里给出唯一汇总，并附 markdown 表格片段，文档直接引用输出。
    """
    d = pipeline_dir(REPO_ROOT)
    declared = checks.decl_index(checks.DEFAULT_LEAN_ROOT, config.LIB)
    rows: list[dict[str, Any]] = []
    tot = {k: 0 for k in ("atoms", "verified", "partial", "todo",
                          "declarations", "primaries", "derived", "witnesses")}
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not (fn.startswith("section") and fn.endswith(".json")):
            continue
        try:
            sec = Section.load(os.path.join(d, fn))
        except Exception as e:  # noqa: BLE001
            rows.append({"file": fn, "error": f"{type(e).__name__}: {e}"})
            continue
        own = {checks._mod_of_file(f) for f in sec.files() if f}
        decls = [n for n, info in declared.items()
                 if not own or info["module"] in own]
        prim = sum(1 for it in sec.items if it.lean.primary)
        der = sum(len(it.lean.derived) for it in sec.items)
        wit = sum(len(it.lean.witness) for it in sec.items)
        st = {k: v for k, v in sec.by_status().items() if v}
        cov = sec.coverage()
        rows.append({"section": sec.section, "title": sec.title,
                     "atoms": len(sec.items), "coverage": f"{cov[0]}/{cov[1]}",
                     "status_counts": st, "declarations": len(decls),
                     "primaries": prim, "derived": der, "witnesses": wit})
        tot["atoms"] += len(sec.items)
        tot["verified"] += st.get("verified", 0)
        tot["partial"] += st.get("partial", 0)
        tot["todo"] += st.get("todo", 0)
        tot["declarations"] += len(decls)
        tot["primaries"] += prim
        tot["derived"] += der
        tot["witnesses"] += wit

    g = load_json(os.path.join(d, "graph.json"), {}) or {}
    graph = None
    if g:
        st = g.get("stats") or {}
        graph = {"nodes": len(g.get("nodes") or {}),
                 "edges": len(g.get("edges") or []),
                 "tiers": st.get("tiers"),
                 "content_self_sufficiency": st.get("content_self_sufficiency")}

    md = ["| 节 | 原子 | verified | 声明 |", "|---|---|---|---|"]
    for r in rows:
        if "error" in r:
            continue
        md.append(f"| §{r['section']} | {r['atoms']} | "
                  f"{r['status_counts'].get('verified', 0)} | {r['declarations']} |")
    md.append(f"| **合计** | **{tot['atoms']}** | **{tot['verified']}** | "
              f"**{tot['declarations']}** |")
    return _dump({"ok": True, "sections": rows, "totals": tot, "graph": graph,
                  "markdown": "\n".join(md),
                  "note": "文档计数一律引用本输出，不要手填；图计数来自 graph.json"})


# ---------------------------------------------------------------- 图

@mcp.tool()
def kl_figure(
    page: Annotated[int, Field(description="英文 PDF 页码（用 kl_book / kl_book_locate 取页码，别自己算偏移）")],
    dpi: Annotated[int, Field(description="渲染 PNG 的 dpi（默认 200）")] = 200,
    pdf: Annotated[str, Field(description="PDF 路径（默认英文原书）")] = "",
    decode: Annotated[bool, Field(description="是否做机械解码（默认 true）")] = True,
) -> str:
    """Render one PDF page and **mechanically decode** any figure on it (cells → open-set families).

    Never count raster images to decide whether a page has a figure: vector figures produce
    zero /Image objects. Use `drawings` >= 1. Output JSON + PNG path under knowledge/pipeline/figures/.

    PDF 是【外部资源】：用 `pdf=` 传路径，或设环境变量 `KL_BOOK_PDF`。本库不含书。
    """
    pdf_path = pdf or checks.BOOK_PDF
    if not pdf_path or not os.path.isfile(pdf_path):
        return _dump({"error": "没有可用 PDF：传 pdf= 或设 KL_BOOK_PDF（本库不含书，这是外部资源）",
                      "pdf": pdf_path})
    out_dir = os.path.join(pipeline_dir(REPO_ROOT), "figures")
    stats = figures.page_stats(pdf_path, page)
    res = {"stats": stats, "out_dir": out_dir}
    png = os.path.join(out_dir, f"en_p{page:04d}.png")
    try:
        res["render"] = figures.render_page(pdf_path, page, png, dpi=dpi)
    except Exception as e:  # noqa: BLE001
        res["render"] = {"error": f"{type(e).__name__}: {e}"}
    if decode and stats["drawings"] > 0:
        try:
            res["decoded"] = figures.decode_page(
                pdf_path, page, out_json=os.path.join(out_dir, f"decoded_p{page:04d}.json"))
        except Exception as e:  # noqa: BLE001
            res["decoded"] = {"error": f"{type(e).__name__}: {e}"}
    return _dump(res)


# ---------------------------------------------------------------- 图

@mcp.tool()
def kl_graph(
    export: Annotated[str, Field(
        description="把整图导出成 JSON 的路径（空 = 不导出；建议 knowledge/pipeline/graph.json）")] = "",
) -> str:
    """Build the four-layer edge graph (.ilean + probes) and run all built-in assertions.

    节点 = 声明 + 被提及的声明；边 = 提及，四层 A/B/I/R；亮节点 = 本库内容层。
    assertions: freshness / coverage / ghosts / conservation / boundary / comments / tiers。
    数据源全部源码侧；★ 每次源码改动后必须 lake build + 重跑两个探针，否则会静默错分。
    """
    from kl import graph as G  # 延迟 import：只有用到图时才需要
    g = G.build()
    asserts = G.assertions(g)
    doc = {"ok": all(a["ok"] for a in asserts),
           "modules": g["modules"],
           "sig_count": g["sig"]["count"],
           "struct": g["struct"],
           "stats": g["stats"],
           "assertions": asserts}
    if export:
        doc["exported"] = G.export(g, export)
    return _dump(doc)


if __name__ == "__main__":
    mcp.run()
