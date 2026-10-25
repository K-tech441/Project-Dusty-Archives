# -*- coding: utf-8 -*-
"""书的页码索引：小节 ↔ 页码（参数化；换书只改 knowledge/books/<id>.json）。

## 为什么有它

「读」的环节依赖页码定位，而页码是**版本相关**的：中译本 / 英文本 / PDF 偏移 /
章节扉页没有页眉 / OCR 丢数字 / 图的页 ≠ 正文提到的页。
把定位结果**落盘成索引**，查询只读索引；不让每个 agent 重新算，也不依赖写死的偏移常数。

## 三层

```
config   knowledge/books/<id>.json        书的结构参数（源、页码提取规则、md 命名）
index    knowledge/books/<id>/index.json  生成物：每页 pdf↔印刷、每节五坐标范围
查询     section_book(n) · locate_anchor(text) · build(id)
```

## 坐标系统一约定

```
pdf_page      PDF 的第几页（1 起）
printed       书上印刷页码（页眉/页脚那个数字）
md            book_md/p####.md 的 ####（= PDF 页号，由 config.md_page_source 声明）
```
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

from kl import config

TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = config.REPO


# ---------------------------------------------------------------- 基础

def _pymupdf():
    """取 PyMuPDF；找不到时试 KL_PYLIBS（默认 D:/pylibs）。返回 None 表示不可用。"""
    try:
        import pymupdf  # type: ignore
        return pymupdf
    except Exception:
        pass
    libs = os.environ.get("KL_PYLIBS", "D:/pylibs")
    if libs and os.path.isdir(libs) and libs not in sys.path:
        sys.path.insert(0, libs)
        try:
            import pymupdf  # type: ignore
            return pymupdf
        except Exception:
            return None
    return None


def book_id(book: str | None = None) -> str:
    return book or config.BOOK_ID


def config_path(book: str | None = None) -> str:
    return config.book_config_path(book)


def index_path(book: str | None = None) -> str:
    return config.book_index_path(book)


def load_config(book: str | None = None) -> dict[str, Any]:
    p = config_path(book)
    if not os.path.isfile(p):
        raise FileNotFoundError(
            f"书配置不存在：{p}\n（换书：复制一份 knowledge/books/<id>.json 改 sources/patterns）")
    return json.load(open(p, encoding="utf-8"))


def load_index(book: str | None = None) -> dict[str, Any] | None:
    p = index_path(book)
    if not os.path.isfile(p):
        return None
    return json.load(open(p, encoding="utf-8"))


def _src(cfg: dict[str, Any], which: str) -> dict[str, Any]:
    return (cfg.get("sources") or {}).get(which) or {}


def _resolve(src: dict[str, Any], env_key: str, path_key: str) -> str:
    """env 优先；其次 path（相对 repo 根）。"""
    env = src.get(env_key) or ""
    if env and os.environ.get(env):
        return os.environ[env]
    p = src.get(path_key) or ""
    if p and not os.path.isabs(p):
        p = os.path.join(REPO_ROOT, p)
    return p


# ---------------------------------------------------------------- 页眉/页脚里的印刷页码

def detect_printed(lines: list[str], cfg: dict[str, Any]) -> int | None:
    """从页眉/页脚取出印刷页码；取不到返回 None。

    只认「整行」形态（避免正文里的数字）：配置里的 patterns 按顺序试。
    """
    fol = cfg.get("folio") or {}
    pats = [re.compile(p) for p in fol.get("patterns") or []]
    head = int(fol.get("head_lines", 3))
    foot = int(fol.get("foot_lines", 2))

    def scan(candidates: list[str]) -> int | None:
        for line in candidates:
            s = line.strip()
            if not s or len(s) > 80:
                continue
            for pat in pats:
                m = pat.search(s)
                if m:
                    try:
                        v = int(m.group(1))
                    except Exception:
                        continue
                    if 0 <= v <= 3000:
                        return v
        return None

    v = scan(lines[:head])
    if v is not None:
        return v
    return scan(lines[-foot:][::-1]) if foot else None


def detect_section(lines: list[str], cfg: dict[str, Any]) -> tuple[int | None, str]:
    """取「小节号 + 小节名」。取不到返回 (None, )。

    页眉里的 `§n` 最可靠；章扉页/节首页的标题可能落在正文前几行 ⟹ 兜底扫**整页**的锚定标题。
    偶数页页眉只有章名（无 §）⟹ 该页的节号由「节起始页」推出（见 build）。
    ★ 2026-10-25 修：兜底原来只扫前 25 行，命中不了「上一节正文较长、标题被压到页中下部」的
    边界页（§16 的 Definition 页：PDF 页 90 的 `§16` 标题在第 31 行）⟹ §16 起点被推到下一页，
    边界页整页丢失。现在扫整页，但只认「整行以 § 开头且带小节名」这种排版标题（长度上限 80）。
    """
    secs = cfg.get("sections") or {}
    pats = [re.compile(p) for p in secs.get("patterns") or []]
    for line in lines[:4]:
        t = line.strip()
        for pat in pats:
            m = pat.search(t)
            if m:
                try:
                    n = int(m.group(1))
                except Exception:
                    continue
                name = t
                if re.fullmatch(r"§\s*\d{1,2}", t) and len(lines) > 1:
                    idx = lines.index(line)
                    if idx + 1 < len(lines):
                        name = lines[idx + 1].strip()
                return n, name
    for i, line in enumerate(lines):
        t = line.strip()
        if len(t) > 80:
            continue
        m = re.fullmatch(r"§\s*(\d{1,2})", t)
        if m:
            nm = lines[i + 1].strip() if i + 1 < len(lines) else t
            return int(m.group(1)), nm[:80]
        m = re.search(r"§\s*(\d{1,2})\s+[A-Z]", t)
        if m:
            nm = t
            if i + 1 < len(lines) and not re.search(r"[a-z]$", nm):
                nm = (nm + " " + lines[i + 1].strip())[:80]
            return int(m.group(1)), nm
    return None, ""


def _heading_index(lines: list[str], section: int, cfg: dict[str, Any]) -> int | None:
    """页内节标题所在的行号（与 detect_section 同一套模式）；找不到返回 None。

    ★ 2026-10-25：窗口从前 25 行改为**整页**（同 detect_section 的修理：边界页标题可能在页中下部）。
    """
    secs = cfg.get("sections") or {}
    pats = [re.compile(p) for p in secs.get("patterns") or []]
    for i, line in enumerate(lines):
        t = line.strip()
        if len(t) > 80 :
            continue
        if re.fullmatch(rf"§\s*{int(section)}", t) or \
           re.search(rf"§\s*{int(section)}\s+[A-Z]", t):
            return i
        for pat in pats:
            m = pat.search(t)
            if m:
                try:
                    if int(m.group(1)) == int(section):
                        return i
                except Exception:
                    pass
    return None


# ---------------------------------------------------------------- 中译本的目录（book/index.json）

def _zh_sections(cfg: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """从中译本目录读出每节的印刷页/PDF 页（中译本是扫描件，无文字层 ⟹ 只能靠目录）。"""
    src = _src(cfg, "zh")
    p = _resolve(src, "index_env", "index_path")
    if not p or not os.path.isfile(p):
        return {}
    d = json.load(open(p, encoding="utf-8"))
    out: dict[int, dict[str, Any]] = {}
    for part in d.get("parts") or []:
        for chap in part.get("chapters") or []:
            for sec in chap.get("sections") or []:
                try:
                    n = int(sec.get("number"))
                except Exception:
                    continue
                out[n] = {
                    "number": n,
                    "zh_name": sec.get("name") or "",
                    "zh_printed": [sec.get("printed_start"), sec.get("printed_end")],
                    "zh_pdf": [sec.get("pdf_start"), sec.get("pdf_end")],
                    "zh_chapter": chap.get("name") or "",
                }
    return out


def _offset_votes(pairs: list[tuple[int, int]]) -> dict[str, Any]:
    """pairs = [(larger, smaller)]，返回众数偏移与异常点。"""
    votes: dict[int, int] = {}
    for a, b in pairs:
        if a is None or b is None:
            continue
        votes[a - b] = votes.get(a - b, 0) + 1
    if not votes:
        return {"offset": None, "votes": {}, "anomalies": []}
    mode = max(votes.items(), key=lambda kv: (kv[1], -abs(kv[0])))[0]
    anomalies = [(a, b) for a, b in pairs if a is not None and b is not None and a - b != mode]
    return {"offset": mode, "votes": dict(sorted(votes.items())),
            "anomalies": anomalies[:40], "anomaly_count": len(anomalies)}


# ---------------------------------------------------------------- 建成索引

def build(book: str | None = None) -> dict[str, Any]:
    """扫书的源，生成 knowledge/books/<id>/index.json。需要英文 PDF（PyMuPDF）。"""
    cfg = load_config(book)
    bid = book_id(book)
    warnings: list[str] = []

    zh = _zh_sections(cfg)
    if not zh:
        warnings.append("中译本目录缺失（书配置 sources.zh 未指向有效的 book/index.json）")

    en_src = _src(cfg, "en")
    pdf = _resolve(en_src, "pdf_env", "pdf_path")
    md_dir = _resolve(en_src, "md_env", "md_path")

    pages: dict[int, int] = {}          # pdf_page -> printed
    page_section: dict[int, int] = {}   # pdf_page -> section
    sec_names: dict[int, str] = {}
    start_lines: dict[int, list[str]] = {}   # section -> 起始页的文本行（判共享边界页用）
    src_kind = "none"

    if pdf and os.path.isfile(pdf):
        mupdf = _pymupdf()
        if mupdf is None:
            return {"ok": False, "error": "book-build 需要 PyMuPDF：设 KL_PYLIBS 或 pip install",
                    "code": "NO_PYMUPDF"}
        doc = mupdf.open(pdf)
        src_kind = "pdf_text"
        for i in range(doc.page_count):
            text = doc[i].get_text()
            lines = [x for x in text.splitlines() if x.strip()]
            pr = detect_printed(lines, cfg)
            if pr is not None:
                pages[i + 1] = pr
            sec, name = detect_section(lines, cfg)
            if sec is not None:
                page_section[i + 1] = sec
                sec_names.setdefault(sec, name)
                start_lines.setdefault(sec, lines)
        doc.close()
    elif md_dir and os.path.isdir(md_dir):
        src_kind = "md"
        pat = re.compile((en_src.get("md_name_pattern") or r"^p(\d{4})\.md$"))
        for fn in sorted(os.listdir(md_dir)):
            m = pat.match(fn)
            if not m:
                continue
            page = int(m.group(1))
            lines = [x for x in open(os.path.join(md_dir, fn), encoding="utf-8")
                     .read().splitlines() if x.strip()]
            pr = detect_printed(lines, cfg)
            if pr is not None:
                pages[page] = pr
            sec, name = detect_section(lines, cfg)
            if sec is not None:
                page_section[page] = sec
                sec_names.setdefault(sec, name)
                start_lines.setdefault(sec, lines)
        warnings.append("没有英文 PDF（只用了 md 转录）：页码覆盖低，置信度见 detection")
    else:
        warnings.append("英文源缺失（ebooks.en 的 PDF / MD 都没找到）")

    if src_kind == "none" and not zh:
        return {"ok": False, "error": "没有任何书源可用（中译目录 / 英文 PDF / md 转录都没找到）；"
                                     "未写索引（避免覆盖旧索引）。检查 KL_BOOK_* 环境变量或 "
                                     "knowledge/books/<id>.json", "code": "NO_SOURCES"}

    # 偏移（英文 PDF/md 页 − 印刷页）；先去掉离群点（章扉页残留页码、章号 '2' 之类）
    raw_off = _offset_votes(sorted(pages.items()))
    mode = raw_off.get("offset")
    dropped: list[tuple[int, int]] = []
    if mode is not None:
        kept: dict[int, int] = {}
        for q, p in pages.items():
            if abs((q - p) - mode) <= 1:
                kept[q] = p
            else:
                dropped.append((q, p))
        pages = kept
    en_off = _offset_votes(sorted(pages.items()))
    off = en_off.get("offset")

    # 每节的英文页范围：起点 = 第一个页眉/标题里出现 §n 的页；终点 = 下一节起点 − 1；
    # 但若下一节起始页的标题之前还有正文 ⟹ 该页是【共享边界页】，当前节也要包含它
    # （2026-10-25 修：§14 的开射线/子基内容在 §15 标题页上，旧规则把这页整页切掉了）。
    starts: dict[int, int] = {}
    for p, sec in sorted(page_section.items()):
        starts.setdefault(sec, p)
    en_ranges: dict[int, dict[str, Any]] = {}
    if starts:
        last_page = max(pages) if pages else max(page_section)
        order = sorted(starts.items())
        for i, (sec, start) in enumerate(order):
            end = order[i + 1][1] - 1 if i + 1 < len(order) else last_page
            if i + 1 < len(order):
                nsec, nstart = order[i + 1]
                lines = start_lines.get(nsec) or []
                hi = _heading_index(lines, nsec, cfg) if lines else None
                if hi is not None and any(x.strip() for x in lines[1:hi]):
                    end = max(end, nstart)
            if end < start:
                end = start
            span = end - start + 1
            hit = len([p for p in range(start, end + 1) if page_section.get(p) == sec])
            en_ranges[sec] = {
                "en_pdf": [start, end],
                "md": [start, end],
                "en_printed": [_printed_at(start, pages, off), _printed_at(end, pages, off)],
                "en_name": sec_names.get(sec, ""),
                "detected_pages": hit,
                "page_detection": round(hit / max(1, span), 2),
            }

    # 合并：以中译本目录的节号为准（它是权威的节清单）
    sections: dict[str, Any] = {}
    for n in sorted(zh):
        ent = dict(zh[n])
        en = en_ranges.get(n)
        if en:
            ent.update(en)
        else:
            warnings.append(f"§{n}: 没检测到英文页范围（英文源缺该节 / 页眉不可读）")
        conf = {}
        if en:
            span = en["en_pdf"][1] - en["en_pdf"][0] + 1
            conf["page_detection"] = round(en["detected_pages"] / max(1, span), 2)
        ent["confidence"] = conf
        sections[str(n)] = ent

    # 图题（图号 → 实际所在页）。figures 依赖 ranges，放在合并后算。
    figures = scan_figures(cfg, pages, off, en_ranges, book)

    idx = {
        "book": bid,
        "title": cfg.get("title") or "",
        "built_at": _now(),
        "sources": {
            "zh_index": _rel(src_zh(cfg, "index_path")),
            "en_pdf": _rel(pdf),
            "en_md": _rel(md_dir),
            "kind": src_kind,
            "abs_zh_index": src_zh(cfg, "index_path"),
            "abs_en_pdf": pdf,
            "abs_en_md": md_dir,
        },
        "offsets": {
            "en_pdf_minus_printed": off,
            "en_votes": en_off.get("votes"),
            "en_anomalies": en_off.get("anomaly_count", 0),
            "en_dropped_pages": dropped[:40],
            "en_dropped_count": len(dropped),
        },
        "pages": {str(k): v for k, v in sorted(pages.items())},
        "page_section": {str(k): v for k, v in sorted(page_section.items())},
        "sections": sections,
        "figures": figures,
        "warnings": warnings,
    }
    out = index_path(book)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return {"ok": True, "written_to": out, "kind": src_kind,
            "offset": off, "pages_detected": len(pages), "sections": len(sections),
            "warnings": warnings}


def _printed_at(pdf_page: int, pages: dict[int, int], off: int | None) -> int | None:
    if pdf_page in pages:
        return pages[pdf_page]
    if off is None:
        return None
    return pdf_page - off


def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _rel(p: str) -> str:
    if not p:
        return ""
    try:
        r = os.path.relpath(p, REPO_ROOT)
        return r.replace("\\", "/")
    except Exception:
        return p


def src_zh(cfg: dict[str, Any], key: str) -> str:
    return _resolve(_src(cfg, "zh"), "index_env", key)




def _md_files(cfg: dict[str, Any], book: str | None = None) -> list[tuple[int, str]]:
    """md 转录文件 → [(pdf_page, path)]。文件名 p#### = PDF 页（config.md_page_source 已声明）。"""
    en_src = _src(cfg, "en")
    md_dir = _resolve(en_src, "md_env", "md_path")
    if not (md_dir and os.path.isdir(md_dir)):
        md_dir = ((load_index(book) or {}).get("sources") or {}).get("abs_en_md") or ""
    if not (md_dir and os.path.isdir(md_dir)):
        return []
    pat = re.compile((en_src.get("md_name_pattern") or r"^p(\d{4})\.md$"))
    out: list[tuple[int, str]] = []
    for fn in sorted(os.listdir(md_dir)):
        m = pat.match(fn)
        if m:
            out.append((int(m.group(1)), os.path.join(md_dir, fn)))
    return out


_CAPTION = re.compile(r"^\s*Figure\s+(\d+\.\d+)\s*\.?\s*$", re.I)


def scan_figures(cfg: dict[str, Any], pages: dict[int, int], off: int | None,
                 ranges: dict[int, dict[str, Any]],
                 book: str | None = None) -> dict[str, Any]:
    """扫 md 的图题行：图号 → 实际所在页（md 页 = PDF 页）。"""
    figs: dict[str, Any] = {}
    for pdf_page, path in _md_files(cfg, book):
        try:
            lines = open(path, encoding="utf-8").read().splitlines()
        except Exception:
            continue
        for line in lines:
            m = _CAPTION.match(line)
            if not m:
                continue
            fid = m.group(1)
            printed = _printed_at(pdf_page, pages, off)
            sec = None
            for sn, ent in ranges.items():
                rng = ent.get("en_pdf") or [None, None]
                if rng[0] is not None and rng[0] <= pdf_page <= rng[1]:
                    sec = sn
                    break
            figs.setdefault(fid, {
                "id": fid, "pdf": pdf_page, "md": pdf_page, "printed": printed,
                "section": sec,
            })
    return dict(sorted(figs.items(),
                       key=lambda kv: (int(kv[1]["pdf"]))))


# ---------------------------------------------------------------- 查询

def section_book(section: int, book: str | None = None) -> dict[str, Any]:
    """一节的五坐标范围（只读索引；索引缺了给明确提示）。"""
    idx = load_index(book)
    if idx is None:
        return {"section": section, "missing": ["index"],
                "note": f"先建索引：python -m kl.cli book-build（book={book_id(book)}）"}
    ent = (idx.get("sections") or {}).get(str(int(section)))
    offs = idx.get("offsets") or {}
    out: dict[str, Any] = {
        "section": int(section), "source": "index", "built_at": idx.get("built_at"),
        "offset": {k: offs.get(k) for k in
                   ("en_pdf_minus_printed", "en_anomalies", "en_dropped_count")},
    }
    if not ent:
        out["missing"] = ["sections"]
        out["note"] = "索引里没有这一节（换书/节号超界？）"
        return out
    for k in ("zh_printed", "zh_pdf", "en_printed", "en_pdf", "md", "zh_name", "en_name",
              "zh_chapter", "confidence"):
        if k in ent:
            out[k] = ent[k]
    out["missing"] = [k for k in ("zh_printed", "zh_pdf", "en_printed", "en_pdf", "md")
                      if k not in out or out.get(k) in (None, [None, None])]
    return out


def _normalize(s: str) -> str:
    rep = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl",
           "\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"',
           "\u2013": "-", "\u2014": "-", "~": "~"}
    for k, v in rep.items():
        s = s.replace(k, v)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def locate_anchor(anchor: str, book: str | None = None, limit: int = 20) -> dict[str, Any]:
    """在英文转录里搜文字（Definition / Lemma / Figure / 任意引文）→ 页码。

    ★ 命中分两类：
      caption —— 整行只有该文字（图题行：`Figure 12.1`）⟹ 该页就是图/条目**实际所在页**
      ref     —— 文字出现在句子中（正文引用）⟹ 只说明「这一页提到了它」
    图号直接查索引里的 figures（图题扫描的结果），比字符串命中更可靠。
    """
    cfg = load_config(book)
    idx = load_index(book)
    needle = _normalize(anchor)
    hits: list[dict[str, Any]] = []

    en_src = _src(cfg, "en")
    md_dir = _resolve(en_src, "md_env", "md_path")
    if not (md_dir and os.path.isdir(md_dir)):
        md_dir = ((idx or {}).get("sources") or {}).get("abs_en_md") or ""
    if md_dir and os.path.isdir(md_dir) and needle:
        pat = re.compile((en_src.get("md_name_pattern") or r"^p(\d{4})\.md$"))
        for fn in sorted(os.listdir(md_dir)):
            m = pat.match(fn)
            if not m:
                continue
            page = int(m.group(1))
            text = open(os.path.join(md_dir, fn), encoding="utf-8").read()
            norm = _normalize(text)
            i = norm.find(needle)
            if i < 0:
                continue
            # caption = 整行只有该文字（图题行）；heading = 该行以该文字开头（条目名，如 Lemma 13.4.）
            cap_line, head_line = "", ""
            for line in text.splitlines():
                ln = _normalize(line)
                if ln.rstrip(".") == needle.rstrip("."):
                    cap_line = line.strip()
                    break
                if ln.startswith(needle) and not head_line:
                    head_line = line.strip()
            kind = "caption" if cap_line else ("heading" if head_line else "ref")
            hits.append({"md": page, "pdf": page, "count": norm.count(needle),
                         "kind": kind, "line": cap_line or head_line,
                         "context": norm[max(0, i - 60):i + len(needle) + 60]})
            if len(hits) >= limit:
                break
    # 补：pdf/印刷/所属节/中译范围
    for h in hits:
        h.update(_enrich(h["pdf"], idx))
    order = {"caption": 0, "heading": 1, "ref": 2}
    hits.sort(key=lambda h: (order.get(h.get("kind"), 3), h.get("printed") or 10**9))
    # 图号：索引里的 figures 最可靠
    fig = None
    fid = anchor.strip().removeprefix("Figure").strip().removeprefix("figure").strip().rstrip(".")
    if idx:
        fig = (idx.get("figures") or {}).get(fid)
        if fig:
            ent = idx["sections"].get(str(fig.get("section") or ""))
            fig = dict(fig)
            if ent:
                fig["zh_printed"] = ent.get("zh_printed")
    return {"anchor": anchor, "hits": hits[:limit], "total": len(hits),
            "figure": fig,
            "note": "caption = 整行就是该文字（图题行 ⟹ 实际所在页）；ref = 正文引用（只说明这页提到它）。"
                    "printed 用索引的 PDF→印刷 映射；中译是扫描件 ⟹ 只到节级。"}


def _enrich(pdf_page: int, idx: dict[str, Any] | None) -> dict[str, Any]:
    if not idx:
        return {}
    pages = {int(k): v for k, v in (idx.get("pages") or {}).items()}
    off = (idx.get("offsets") or {}).get("en_pdf_minus_printed")
    printed = pages.get(pdf_page, (pdf_page - off) if off else None)
    sec = None
    for s, ent in (idx.get("sections") or {}).items():
        rng = ent.get("en_pdf")
        if rng and rng[0] is not None and rng[0] <= pdf_page <= rng[1]:
            sec = s
            break
    out: dict[str, Any] = {"printed": printed, "section": sec}
    if sec:
        ent = idx["sections"][sec]
        out["zh_printed"] = ent.get("zh_printed")
        out["en_section"] = ent.get("en_printed")
    return out


def summary(book: str | None = None) -> dict[str, Any]:
    idx = load_index(book)
    if idx is None:
        return {"ok": False, "note": "索引不存在；先 book-build"}
    secs = idx.get("sections") or {}
    missing = [s for s, e in secs.items() if not e.get("en_pdf")]
    return {"ok": True, "built_at": idx.get("built_at"),
            "sources": idx.get("sources"), "offsets": idx.get("offsets"),
            "sections": len(secs), "missing_en": missing,
            "warnings": idx.get("warnings")}
