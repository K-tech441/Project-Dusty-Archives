# -*- coding: utf-8 -*-
"""术语表（glossary）：长程任务的「术语 → 之前工作内容」指针索引。

为什么需要它（2026-10-25 学员提出）：整个工程会跨很多节、很多会话完成，后来的 agent
拿到的是全新上下文。只靠 `sectionNN.json` 逐个翻，成本高且容易漏。术语表把
「书上术语 / 清单 label」映射到：章节 · 原子 id · Lean 全限定名与模块 · 清单文件 · 文档，
并用 doctor 的一项检查保证指针不漂。

文件：`knowledge/glossary.json`（单一事实源）。`build` 从各节清单**自动生成** atom 条目
（label → primary 声明），保留手写的 `concepts` 段（跨节术语，例如「标准拓扑」）。
`check` 校验：清单/原子存在、Lean 声明存在、已完成的原子都被覆盖。

用法：
    python -m kl.cli glossary build     # 从 section*.json 重建 atom/sections，保留 concepts
    python -m kl.cli glossary check     # 指针 + 覆盖校验（doctor 也跑这一项）
    python -m kl.cli glossary show     # 摘要（给 agent 快速看）
"""
from __future__ import annotations

import glob
import json
import os

from kl import config, model

GLOSSARY_REL = os.path.join("knowledge", "glossary.json")


def glossary_path(root: str) -> str:
    return config.glossary_path(root)


def _rel(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace("\\", "/")


def _module_of_file(rel: str) -> str:
    p = rel.replace("\\", "/")
    if p.endswith(".lean"):
        p = p[:-5]
    return p.replace("/", ".")


def _sections(root: str):
    """[(Section, path)]，按 section 号排序；只认 sectionNN.json。"""
    out = []
    for p in glob.glob(os.path.join(config.pipeline_dir(root), "section[0-9][0-9].json")):
        try:
            sec = model.Section.load(p)
        except Exception:
            continue
        if sec.section:
            out.append((sec, p))
    out.sort(key=lambda t: t[0].section)
    return out


def _load(root: str) -> dict:
    p = glossary_path(root)
    if os.path.isfile(p):
        try:
            doc = json.load(open(p, encoding="utf-8"))
            if isinstance(doc, dict):
                return doc
        except Exception:
            pass
    return {"schema": 1, "concepts": []}


def build(root: str) -> dict:
    """从清单重建 sections/atoms；保留手写 concepts。"""
    old = _load(root)
    sections: dict[str, dict] = {}
    atoms: list[dict] = []
    for sec, path in _sections(root):
        rel = _rel(root, path)
        module_file = ""
        for it in sec.items:
            if it.lean.file:
                module_file = it.lean.file
                break
        if not module_file:
            module_file = f"{config.LIB}/Section{sec.section:02d}.lean"
        module = _module_of_file(module_file)
        counts = {"verified": 0, "partial": 0, "other": 0}
        for it in sec.items:
            st = it.lean.status or "pending"
            if st == "verified":
                counts["verified"] += 1
            elif st == "partial":
                counts["partial"] += 1
            else:
                counts["other"] += 1
        sections[str(sec.section)] = {
            "title": sec.title,
            "inventory": rel,
            "module": module_file,
            "book": sec.book.to_dict(),
            "atoms": len(sec.items),
            "verified": counts["verified"],
            "partial": counts["partial"],
            "other": counts["other"],
        }
        for it in sec.items:
            primary = it.lean.primary or (it.decl_names()[0] if it.decl_names() else "")
            entry = {
                "id": it.id,
                "term": it.label or it.id,
                "kind": it.kind,
                "section": sec.section,
                "status": it.lean.status or "pending",
                "primary": primary,
                "module": module,
                "inventory": rel,
                "pointers": {
                    "atom": it.id,
                    "lean": [primary] if primary else [],
                },
            }
            atoms.append(entry)
    doc = {
        "schema": 1,
        "updated_at": __import__("datetime").datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "note": "术语 → 章节/原子/Lean/清单 指针。build 自动生成 sections/atoms；concepts 手写保留。",
        "sections": sections,
        "atoms": atoms,
        "concepts": old.get("concepts", []),
    }
    p = glossary_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    return {"ok": True, "path": _rel(root, p), "sections": len(sections),
            "atoms": len(atoms), "concepts": len(doc["concepts"])}


def _declared(root: str):
    from kl import checks  # 延迟导入：checks 会 import glossary（doctor 用），避免环
    return checks.decl_index(root, config.LIB)


def check(root: str, declared: dict | None = None) -> dict:
    """校验术语表指针与覆盖；doctor 的一项检查。"""
    p = glossary_path(root)
    if not os.path.isfile(p):
        return {"ok": False, "detail": "缺 knowledge/glossary.json：跑 kl glossary build",
                "problems": ["missing"]}
    doc = _load(root)
    by_section = {str(sec.section): sec for sec, _ in _sections(root)}
    problems: list[str] = []
    if declared is None:
        declared = _declared(root)
    # 1) sections 段与清单一致
    for num, rec in (doc.get("sections") or {}).items():
        sec = by_section.get(num)
        if sec is None:
            problems.append(f"sections[{num}]: 清单不存在")
            continue
        if rec.get("atoms") != len(sec.items):
            problems.append(f"sections[{num}]: atoms={rec.get('atoms')} 但清单 {len(sec.items)}（跑 build）")
    # 2) atom 条目指针
    seen: set[tuple[int, str]] = set()
    ids_by_section: dict[str, set[str]] = {}
    for num, sec in by_section.items():
        ids_by_section[num] = {it.id for it in sec.items}
    for e in doc.get("atoms") or []:
        secn = str(e.get("section"))
        aid = str(e.get("id") or e.get("pointers", {}).get("atom") or "")
        if secn not in ids_by_section:
            problems.append(f"atom {aid}: 节 {secn} 没有清单")
            continue
        if aid not in ids_by_section[secn]:
            problems.append(f"atom {aid}: 清单 section{secn} 里没有这个原子")
            continue
        seen.add((int(secn), aid))
        primary = e.get("primary") or ""
        if e.get("status") in ("verified", "partial", "proven") and not primary:
            problems.append(f"atom {aid}: status={e.get('status')} 缺 primary")
        if primary and primary not in declared:
            problems.append(f"atom {aid}: Lean 里找不到 {primary}")
        module = e.get("module") or ""
        if module and primary and primary in declared:
            want = declared[primary].get("module")
            if want and want != module:
                problems.append(f"atom {aid}: 模块过期 {module} → {want}（跑 build）")
    # 3) 覆盖：已完成原子必须都有条目
    for num, sec in by_section.items():
        for it in sec.items:
            if it.lean.status in ("verified", "partial", "proven") and (int(num), it.id) not in seen:
                problems.append(f"atom {it.id}: 已完成但术语表未覆盖（跑 build）")
    # 4) 手写 concepts 指针
    for c in doc.get("concepts") or []:
        term = c.get("term", "?")
        for aid in c.get("atoms") or []:
            num = str(c.get("section"))
            if num in ids_by_section and str(aid) not in ids_by_section[num]:
                problems.append(f"concept {term}: 原子 {aid} 不在 section{num}")
        for name in c.get("lean") or []:
            if name not in declared:
                problems.append(f"concept {term}: Lean 里找不到 {name}")
    # 5) concepts 非空（2026-10-25 学员抓到的坑）：文档让新 agent 第一步 `glossary show`；
    #    空 concepts 时入口什么都看不到 —— 而 doctor 仍报 ok，比"没表"更糟（假绿）。
    if not (doc.get("concepts") or []):
        problems.append("concepts 为空（glossary show 看不到任何术语；手工登记跨节术语）")
    n_atoms = len(doc.get("atoms") or [])
    detail = "ok" if not problems else "；".join(problems[:4])
    if not problems:
        detail = f"ok（{len(doc.get('sections') or {})} 节 / {n_atoms} 原子 / {len(doc.get('concepts') or [])} 概念）"
    return {"ok": not problems, "detail": detail, "problems": problems}


def show(root: str) -> dict:
    doc = _load(root)
    # ★ 2026-10-25：原来的 show 只给「节/原子计数 + concepts 名字」，concepts 为空时
    #   新 agent 的接手入口看不到任何术语（假绿）。现在把 atoms 的 术语→primary 也列出来。
    terms = []
    for e in doc.get("atoms") or []:
        line = (f"§{e.get('section')} {e.get('id')} {e.get('term') or e.get('id')} → "
                f"{e.get('primary') or '—'}")
        if e.get("status") not in (None, "verified"):
            line += f" [{e.get('status')}]"
        terms.append(line)
    return {
        "path": _rel(root, glossary_path(root)),
        "updated_at": doc.get("updated_at", ""),
        "sections": {k: {"title": v.get("title"), "atoms": v.get("atoms"),
                         "verified": v.get("verified"), "module": v.get("module")}
                     for k, v in sorted((doc.get("sections") or {}).items())},
        "concepts": doc.get("concepts") or [],
        "terms": terms,
        "atoms": len(doc.get("atoms") or []),
    }
