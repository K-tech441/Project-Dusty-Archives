# -*- coding: utf-8 -*-
"""kl 清单模型（schema 3）。

## 为什么容忍未知键

2026-10-21 旧管线加 `proof_source` / `proof_configs` 两个字段时没同步改 dataclass，
`from_dict` 直接 `TypeError` ⟹ 整条管线瘫痪而没人发现（`selftest` 就是那次之后加的）。
schema 3 反过来做：**未知键一律保留在 `extra` 里，原样写回**。
⟹ 加字段不再能弄挂旧清单；字段漂移由 `audit` 报「清单里有、模型里没有」而不是崩。

## 页码四栏

§12 试运行里页码口径混过三次（中译印刷页 58 / 英文印刷页 73 / 英文 PDF 77 / md p0077），
所以 book 拆成四栏 + md 转录页一栏，全部用 [start, end] 闭区间。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from kl import config
from typing import Any

SCHEMA = 3
# partial = 书上断言只被部分形式化（有 witness）；todo = 未形式化（还没有声明）
STATUSES = ("pending", "skeleton", "proven", "verified", "partial", "todo", "blocked")
KINDS = ("definition", "theorem", "lemma", "example", "exercise", "remark")

_BOOK_KEYS = ("zh_printed", "zh_pdf", "en_printed", "en_pdf", "md")


# ---------------------------------------------------------------- 路径

def pipeline_dir(root: str) -> str:
    return config.pipeline_dir(root)


def inventory_path(root: str, section: int) -> str:
    return os.path.join(pipeline_dir(root), f"section{int(section):02d}.json")


def order_table_path(root: str) -> str:
    return os.path.join(pipeline_dir(root), "入序表.json")


def base_table_path(root: str) -> str:
    return os.path.join(pipeline_dir(root), "基底.json")


def _as_range(v: Any) -> list[int] | None:
    if v is None:
        return None
    if isinstance(v, int):
        return [v, v]
    if isinstance(v, (list, tuple)) and v:
        try:
            ints = [int(x) for x in v]
        except (TypeError, ValueError):
            return None
        if len(ints) == 1:
            return [ints[0], ints[0]]
        return [ints[0], ints[-1]]
    return None


# ---------------------------------------------------------------- Book

@dataclass
class Book:
    """一节的页码四栏 + 英文转录页。每栏 [start, end] 闭区间。"""

    zh_printed: list[int] | None = None
    zh_pdf: list[int] | None = None
    en_printed: list[int] | None = None
    en_pdf: list[int] | None = None
    md: list[int] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Any) -> "Book":
        if not isinstance(d, dict):
            return cls()
        kw = {k: _as_range(d.get(k)) for k in _BOOK_KEYS}
        return cls(extra={k: v for k, v in d.items() if k not in _BOOK_KEYS}, **kw)

    def to_dict(self) -> dict[str, Any]:
        out = {k: getattr(self, k) for k in _BOOK_KEYS}
        out.update(self.extra)
        return out

    def missing(self) -> list[str]:
        return [k for k in _BOOK_KEYS if getattr(self, k) is None]

    def summary(self) -> str:
        def r(x: list[int] | None) -> str:
            return "—" if not x else (f"{x[0]}" if x[0] == x[1] else f"{x[0]}–{x[1]}")

        return (f"中译 印刷 p.{r(self.zh_printed)} / PDF p.{r(self.zh_pdf)} · "
                f"英文 印刷 p.{r(self.en_printed)} / PDF p.{r(self.en_pdf)} · "
                f"转录 md p.{r(self.md)}")


# ---------------------------------------------------------------- 指针

@dataclass
class LeanPointer:
    """指向 Lean 里的一条声明（原子的「Lean 部分」的最小单位）。

    `name` 是全限定名；`module` 是定义所在模块；`line`/`col` 是声明的起始位置
    （来自 `.ilean` 的 decls，0-based）；`sig_sha256` 是**签名文本**（绑定器 + 类型）的哈希
    —— 用来发现「名字还在、陈述变了」。

    ★ 为什么不用短名匹配：短名会撞（`A.foo` / `B.foo`），撞了就静默错。
      全限定名 + 模块 ⟹ 唯一；位置 + 哈希 ⟹ 可校验。
    """

    name: str = ""
    module: str = ""
    line: int = -1
    col: int = -1
    sig_sha256: str = ""

    @classmethod
    def from_dict(cls, name: str, d: Any) -> "LeanPointer":
        if not isinstance(d, dict):
            return cls(name=name)
        pos = d.get("pos") or [-1, -1]
        try:
            line, col = int(pos[0]), int(pos[1])
        except (TypeError, ValueError, IndexError):
            line, col = -1, -1
        return cls(name=name, module=str(d.get("module") or ""),
                   line=line, col=col, sig_sha256=str(d.get("sig_sha256") or ""))

    def to_dict(self) -> dict[str, Any]:
        return {"module": self.module, "pos": [self.line, self.col],
                "sig_sha256": self.sig_sha256}


# ---------------------------------------------------------------- LeanRef

def _str_list(v: Any) -> list[str]:
    if not v:
        return []
    if isinstance(v, str):
        return [v]
    return [str(x) for x in v]


_LEAN_KEYS = ("file", "names", "status", "note",
              "primary", "derived", "witness", "pointers")


@dataclass
class LeanRef:
    """原子的 Lean 部分：状态 + 主声明 + 派生/见证 + **指针**。

    primary / derived / witness 都是「声明引用」；pointers 把它们变成可校验的指针。
    """

    file: str = ""
    names: list[str] = field(default_factory=list)
    status: str = "pending"
    note: str = ""
    primary: str = ""
    derived: list[dict[str, Any]] = field(default_factory=list)
    witness: list[dict[str, Any]] = field(default_factory=list)
    pointers: dict[str, LeanPointer] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Any) -> "LeanRef":
        if not isinstance(d, dict):
            return cls()
        st = str(d.get("status") or "pending")
        if st not in STATUSES:
            st = "pending"
        ptrs = d.get("pointers") or {}
        return cls(
            file=str(d.get("file") or ""),
            names=_str_list(d.get("names")),
            status=st,
            note=str(d.get("note") or ""),
            primary=str(d.get("primary") or ""),
            derived=[x for x in (d.get("derived") or []) if isinstance(x, dict)],
            witness=[x for x in (d.get("witness") or []) if isinstance(x, dict)],
            pointers={str(k): LeanPointer.from_dict(str(k), v)
                      for k, v in ptrs.items()} if isinstance(ptrs, dict) else {},
            extra={k: v for k, v in d.items() if k not in _LEAN_KEYS},
        )

    def to_dict(self) -> dict[str, Any]:
        out = {"file": self.file, "names": list(self.names),
               "status": self.status, "note": self.note,
               "primary": self.primary,
               "derived": [dict(x) for x in self.derived],
               "witness": [dict(x) for x in self.witness],
               "pointers": {n: p.to_dict() for n, p in self.pointers.items()}}
        out.update(self.extra)
        return out


# ---------------------------------------------------------------- 原子

_ITEM_KEYS = ("id", "kind", "book_ref", "quote", "loc", "lean", "notes",
              "proof_source", "proof_configs", "identity_decl", "carrier_deps",
              "label", "statement")


@dataclass
class Atom:
    """书的**原子** —— 抽象数据类型。

    ```
    书侧   id · kind · book_ref · quote · loc · label · statement
    Lean 侧 lean: LeanRef —— status · primary · derived · witness · pointers
    ```

    ★ `pointers`（dict[名字, LeanPointer]）就是「向 Lean 的指」：
      全限定名 + 模块 + 位置 + 签名哈希。由 `kl link` 填、`kl audit` 校验。
      没有指针时，清单只是一个「名字字符串列表」—— 名字撞了就静默错。
    """

    id: str = ""
    kind: str = ""
    book_ref: str = ""
    quote: str = ""
    loc: str = ""
    label: str = ""
    statement: str = ""
    lean: LeanRef = field(default_factory=LeanRef)
    notes: str = ""
    proof_source: str = ""
    proof_configs: list[dict[str, Any]] = field(default_factory=list)
    identity_decl: str = ""
    carrier_deps: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def decl_names(self) -> list[str]:
        """这条原子引用的全部 Lean 声明（primary + derived + witness）。"""
        out: list[str] = []
        if self.lean.primary:
            out.append(self.lean.primary)
        for d in self.lean.derived:
            if d.get("name"):
                out.append(str(d["name"]))
        for w in self.lean.witness:
            if w.get("name"):
                out.append(str(w["name"]))
        return out

    @classmethod
    def from_dict(cls, d: Any) -> "Atom":
        if not isinstance(d, dict):
            raise ValueError(f"atom 不是对象：{d!r}")
        kind = str(d.get("kind") or "")
        return cls(
            id=str(d.get("id") or ""),
            kind=kind if kind in KINDS else kind,   # 非法 kind 留给 audit 报，不吞掉
            book_ref=str(d.get("book_ref") or ""),
            quote=str(d.get("quote") or ""),
            loc=str(d.get("loc") or ""),
            label=str(d.get("label") or ""),
            statement=str(d.get("statement") or ""),
            lean=LeanRef.from_dict(d.get("lean")),
            notes=str(d.get("notes") or ""),
            proof_source=str(d.get("proof_source") or ""),
            proof_configs=list(d.get("proof_configs") or []),
            identity_decl=str(d.get("identity_decl") or ""),
            carrier_deps=_str_list(d.get("carrier_deps")),
            extra={k: v for k, v in d.items() if k not in _ITEM_KEYS},
        )

    def to_dict(self) -> dict[str, Any]:
        out = {
            "id": self.id, "kind": self.kind, "book_ref": self.book_ref,
            "quote": self.quote, "loc": self.loc,
            "label": self.label, "statement": self.statement,
            "lean": self.lean.to_dict(),
            "notes": self.notes, "proof_source": self.proof_source,
            "proof_configs": list(self.proof_configs),
            "identity_decl": self.identity_decl,
            "carrier_deps": list(self.carrier_deps),
        }
        out.update(self.extra)
        return out

    def problems(self) -> list[str]:
        """必填字段检查（audit 用）。"""
        out: list[str] = []
        if not self.id:
            out.append("id 为空")
        if self.kind and self.kind not in KINDS:
            out.append(f"非法 kind={self.kind!r}")
        if not self.book_ref:
            out.append("book_ref 为空（书上哪一条？）")
        if not self.quote.strip():
            out.append("quote 为空（必须逐字抄书上原文）")
        if not self.loc:
            out.append("loc 为空（书页）")
        if not self.label.strip():
            out.append("label 为空（图上的简写标签）")
        if not self.statement.strip():
            out.append("statement 为空（完整的自然语言陈述）")
        if not self.lean.file:
            out.append("lean.file 为空")
        # 1:1 规则：verified/partial 必须有声明；todo 允许还没有声明
        if not self.lean.names and self.lean.status != "todo":
            out.append("lean.names 为空（对应哪些声明？）")
        if self.lean.status == "verified" and not self.lean.primary:
            out.append("verified 原子缺 lean.primary（1:1 的那一条声明）")
        if self.lean.status in ("partial", "todo") and self.lean.primary:
            out.append(f"{self.lean.status} 原子不该有 lean.primary（只有 witness）")
        if self.lean.status not in STATUSES:
            out.append(f"非法 status={self.lean.status!r}")
        # ★ 向 Lean 的指针：每个引用的声明都必须有指针（kl link 填）
        for n in self.decl_names():
            if n not in self.lean.pointers:
                out.append(f"缺 {n} 的 Lean 指针（跑 kl link）")
        return out


# 兼容别名：原子以前叫 Item（清单里的条目）
Item = Atom


# ---------------------------------------------------------------- Section

_SECTION_KEYS = ("schema", "section", "title", "book", "book_pages", "lean_lib",
                 "project_root", "items", "verdict", "updated_at")


@dataclass
class Section:
    """一节的全部条目 + 最近一次判据结果。"""

    section: int = 0
    title: str = ""
    book: Book = field(default_factory=Book)
    lean_lib: str = config.LIB
    project_root: str = ""
    items: list[Item] = field(default_factory=list)
    verdict: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    schema: int = SCHEMA

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Section":
        items = [Item.from_dict(x) for x in (d.get("items") or [])]
        return cls(
            schema=int(d.get("schema") or 0),
            section=int(d.get("section") or 0),
            title=str(d.get("title") or ""),
            book=Book.from_dict(d.get("book")),
            lean_lib=str(d.get("lean_lib") or config.LIB),
            project_root=str(d.get("project_root") or ""),
            items=items,
            verdict=dict(d.get("verdict") or {}),
            updated_at=str(d.get("updated_at") or ""),
            extra={k: v for k, v in d.items() if k not in _SECTION_KEYS},
        )

    def to_dict(self) -> dict[str, Any]:
        out = {
            "schema": SCHEMA,
            "section": self.section,
            "title": self.title,
            "book": self.book.to_dict(),
            "lean_lib": self.lean_lib,
            "project_root": self.project_root,
            "items": [it.to_dict() for it in self.items],
            "verdict": self.verdict,
            "updated_at": self.updated_at,
        }
        out.update(self.extra)
        return out

    # ---- 统计 ----

    def by_status(self) -> dict[str, int]:
        out = {s: 0 for s in STATUSES}
        for it in self.items:
            out[it.lean.status] = out.get(it.lean.status, 0) + 1
        return out

    def coverage(self) -> tuple[int, int]:
        done = sum(1 for it in self.items
                   if it.lean.status in ("proven", "verified"))
        return done, len(self.items)

    def files(self) -> list[str]:
        return sorted({it.lean.file for it in self.items if it.lean.file})

    def names(self) -> list[str]:
        out: list[str] = []
        for it in self.items:
            for n in it.lean.names:
                if n not in out:
                    out.append(n)
        return out

    # ---- IO ----

    @classmethod
    def load(cls, path: str) -> "Section":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)


# ---------------------------------------------------------------- 其他表

def load_json(path: str, default: Any = None) -> Any:
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)
