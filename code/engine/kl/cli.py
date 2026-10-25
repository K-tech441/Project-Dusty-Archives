# -*- coding: utf-8 -*-
"""kl 命令行薄壳（人用 / 批处理）。与 MCP 工具同一个实现，只是打印 JSON。

★ 核心逻辑在 `kl.mcp`，所以本文件需要**同一个解释器**（装了 `mcp` 库的那个；
  图解码还需要 `pymupdf`）。也可以用 `KL_PYTHON` 记录在文档里。

用法：
    python -m kl.cli doctor              # 管线体检（开工前先跑）
    python -m kl.cli sections
    python -m kl.cli next
    python -m kl.cli status 12
    python -m kl.cli book-build             # 建/刷新页码索引（需要英文 PDF + PyMuPDF）
    python -m kl.cli book 13 [--write]      # 读索引：一节的五坐标页码
    python -m kl.cli book-locate "Lemma 13.4"   # 条目级定位：任意引文 → 页码
    python -m kl.cli init 13 [--force]
    python -m kl.cli check 12 [--update] [--with-dup]
    python -m kl.cli quote-check 12 [--json]  # ③c 独立入口：逐条 quote ✓/✗（填一验一）
    python -m kl.cli audit 12
    python -m kl.cli link 13 [--check]
    python -m kl.cli glossary build|check|show   # 术语→原子/Lean 指针（长程记忆）
    python -m kl.cli figure 78 [--dpi 300]
    python -m kl.cli sync-root
    python -m kl.cli probes          # 生成探针的模块表（.probe/modules.json）
"""

from __future__ import annotations

import argparse
import json
import sys

from kl import checks, config, mcp


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kl", description="自然语言数学 → 可检查 Lean 库 + 可视图")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sections")
    sub.add_parser("config")
    sub.add_parser("doctor")
    sub.add_parser("stats")
    sub.add_parser("next")
    sub.add_parser("sync-root")
    sub.add_parser("probes")
    sub.add_parser("fix-headers")

    p = sub.add_parser("new-module")
    p.add_argument("name", help=f"模块名（写到 {config.LIB}/<name>.lean）")

    p = sub.add_parser("status")
    p.add_argument("section", type=int)

    p = sub.add_parser("book")
    p.add_argument("section", type=int)
    p.add_argument("--write", action="store_true")

    sub.add_parser("book-build")

    p = sub.add_parser("book-locate")
    p.add_argument("anchor", help="要定位的文字（如 'Lemma 13.4' 或一句引文）")
    p.add_argument("--limit", type=int, default=20)

    p = sub.add_parser("init")
    p.add_argument("section", type=int)
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("check")
    p.add_argument("section", type=int)
    p.add_argument("--update", action="store_true")
    p.add_argument("--with-dup", action="store_true")

    # 填一验一：③c 的独立入口（不用整节 check；清单填一条 quote 就能立即验）
    p = sub.add_parser("quote-check")
    p.add_argument("section", type=int)
    p.add_argument("--json", action="store_true", help="打印完整 JSON（含 per-item 结果）")

    p = sub.add_parser("audit")
    p.add_argument("section", type=int)

    p = sub.add_parser("link")
    p.add_argument("section", type=int)
    p.add_argument("--check", action="store_true",
                   help="只校验指针（不写回）")

    p = sub.add_parser("figure")
    p.add_argument("page", type=int)
    p.add_argument("--dpi", type=int, default=200)

    p = sub.add_parser("graph")
    p.add_argument("--json", default="", help="导出整图 JSON 的路径（空 = 不导出）")

    p = sub.add_parser("glossary")
    p.add_argument("action", nargs="?", default="show",
                   choices=["build", "check", "show"],
                   help="build=从清单重建/check=校验指针/show=摘要")

    args = ap.parse_args(argv)
    if args.cmd == "sections":
        print(mcp.kl_sections())
    elif args.cmd == "config":
        print(json.dumps(config.summary(), ensure_ascii=False, indent=2))
    elif args.cmd == "doctor":
        print(json.dumps(checks.doctor(checks.DEFAULT_LEAN_ROOT),
                         ensure_ascii=False, indent=2))
    elif args.cmd == "stats":
        print(mcp.kl_stats())
    elif args.cmd == "next":
        print(mcp.kl_next())
    elif args.cmd == "sync-root":
        print(json.dumps(checks.sync_root(checks.DEFAULT_LEAN_ROOT),
                         ensure_ascii=False, indent=2))
    elif args.cmd == "probes":
        rep = checks.build_module_manifest(checks.DEFAULT_LEAN_ROOT)
        if rep.get("ok"):
            rep["next"] = [
                "lake build",
                "lake env lean tools/lean-probes/DeclSigRanges.lean",
                "lake env lean tools/lean-probes/StructEdges.lean",
            ]
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    elif args.cmd == "fix-headers":
        print(json.dumps(checks.fix_module_headers(checks.DEFAULT_LEAN_ROOT),
                         ensure_ascii=False, indent=2))
    elif args.cmd == "new-module":
        print(json.dumps(checks.new_module(checks.DEFAULT_LEAN_ROOT, args.name),
                         ensure_ascii=False, indent=2))
    elif args.cmd == "status":
        print(mcp.kl_status(args.section))
    elif args.cmd == "book":
        print(mcp.kl_book(args.section, write=args.write))
    elif args.cmd == "book-build":
        from kl import bookindex
        print(json.dumps(bookindex.build(), ensure_ascii=False, indent=2))
    elif args.cmd == "book-locate":
        from kl import bookindex
        print(json.dumps(bookindex.locate_anchor(args.anchor, limit=args.limit),
                         ensure_ascii=False, indent=2))
    elif args.cmd == "init":
        print(mcp.kl_init(args.section, force=args.force))
    elif args.cmd == "check":
        mcp.ORIGIN = "cli"  # verdict.by.origin：区分 CLI / MCP 工具（pipeline_gate 也走 CLI）
        print(mcp.kl_check(args.section, update=args.update, with_dup=args.with_dup))
    elif args.cmd == "quote-check":
        sec = mcp._load(args.section)
        rep = checks.quote_check(sec)
        if args.json:
            print(json.dumps(rep, ensure_ascii=False, indent=2))
        else:
            pages = rep.get("pages")
            rng = ("md p%d–p%d" % (pages[0], pages[-1])) if pages else "?"
            head = "§%s quote-check：%s/%s 命中（%s）" % (
                args.section, rep.get("matched", 0), rep.get("checked", 0), rng)
            if rep.get("skipped"):
                head += " · " + str(rep["skipped"])
            print(head)
            for rec in rep.get("items") or []:
                mark = "✓" if rec.get("ok") else "✗"
                extra = "（%d 段）" % rec["segments"] if rec.get("segments", 0) > 1 else ""
                print("  %s %s%s%s" % (mark, rec.get("id"), extra,
                                       "" if rec.get("ok") else "  " + rec.get("problem", "")))
            if rep.get("problems"):
                print("问题：" + "；".join(rep["problems"][:4]))
    elif args.cmd == "audit":
        print(mcp.kl_audit(args.section))
    elif args.cmd == "link":
        print(mcp.kl_link(args.section, check=args.check))
    elif args.cmd == "glossary":
        from kl import glossary as G
        if args.action == "build":
            print(json.dumps(G.build(checks.DEFAULT_LEAN_ROOT), ensure_ascii=False, indent=2))
        elif args.action == "check":
            print(json.dumps(G.check(checks.DEFAULT_LEAN_ROOT), ensure_ascii=False, indent=2))
        else:
            print(json.dumps(G.show(checks.DEFAULT_LEAN_ROOT), ensure_ascii=False, indent=2))
    elif args.cmd == "figure":
        print(mcp.kl_figure(args.page, dpi=args.dpi))
    elif args.cmd == "graph":
        from kl import graph as G
        g = G.build()
        asserts = G.assertions(g)
        doc = {"ok": all(a["ok"] for a in asserts),
               "stats": g["stats"], "assertions": asserts}
        if args.json:
            doc["exported"] = G.export(g, args.json)
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:  # pragma: no cover
        print("unknown command", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
