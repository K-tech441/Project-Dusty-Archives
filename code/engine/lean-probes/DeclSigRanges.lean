import MunkresLean
open Lean

/-!
# 声明签名的源码范围导出器（parse-only，**零 elaboration**）

**输出：`knowledge/schema/_lean_probe/decl_sig_ranges.json`**

## 这一环解决什么

四层边里，I / R 已经能干净取（结构字段），但 A / B 还差一步：

```
.ilean 的每条 usage 自带源码位置 (l1,c1,l2,c2)
⟹ 只要知道「声明的【类型部分】在源码的哪个 range」：
     usage 位置 ∈ type range  ⟹  A 层（签名里的提及）
     否则                      ⟹  B 层（证明里的提及）
```

**⟹ 本文件就是产出那个 range。**

## 为什么必须 parse-only

A / B 的整个痛点就是「不要被 elaboration 干扰」。这里若走 elaboration，
就会把 tactic 展开产物写进环境 —— 与目的相悖。

`Lean.Parser.parseHeader` / `parseCommand` 是**只解析不做 elaboration** 的官方入口
（Lean 的 module system 自己用的就是这一套）。

## 为什么取 `declSig` 的 range

`Lean/Parser/Command.lean`：

    /-- `declSig` matches the signature of a declaration with required type:
        a list of binders and then `: type` -/
    def declSig := leading_parser
      many (ppSpace >> (Term.binderIdent <|> Term.bracketedBinder)) >> Term.typeSpec

⟹ `declSig` 精确对应「绑定器 + `: 类型`」，即人写的类型部分。
  `declVal`（`:= ...` / `where ...`）才是值 / 证明部分。

★ 本文件不产生任何顶层声明。
-/

private def OUT_DIR : String := "D:\\munkres-formal\\.probe\\"
private def SRC_DIR : String := "D:\\munkres-formal\\MunkresLean\\"
/-- 模块表 —— 由 Python 侧从库根聚合文件 `MunkresLean.lean` 生成（格式 [[模块, 文件名], …]）。

★ 规则：**模块表必须从聚合文件生成，不能在这里硬编码。**
  硬编码的模块表在库结构变化后会静默过期：少覆盖的模块没有 sig range ⟹
  它们的 A 层提及被误归到 B 层，而且不报错。
  生成命令：`python -m kl.cli probes`（见 tools/kl）。 -/
private def MANIFEST : String :=
  "D:\\munkres-formal\\.probe\\modules.json"

/-- 递归找第一个 kind 匹配的子节点。 -/
partial def findKind (stx : Syntax) (k : SyntaxNodeKind) : Option Syntax :=
  if stx.isOfKind k then some stx
  else stx.getArgs.findSome? fun a => findKind a k


/-- 从 declId 节点里取声明的短名：递归找第一个 ident 子节点。
    ★ 直接对 declId 节点调 .getId 会得到 [anonymous]（当前版本实测）。 -/
partial def declShortName (stx : Syntax) : Option String :=
  if stx.isIdent then some stx.getId.toString
  else stx.getArgs.findSome? declShortName

/-- 字节偏移 → LSP 位置（行, 列，0-based）。用于与 .ilean 的位置直接对齐。 -/
def toPos (fm : FileMap) (p : String.Pos.Raw) : Json :=
  let pos := fm.toPosition p
  -- ★ 行号要 -1：FileMap.toPosition 给 1-based，而 .ilean 的 usages/decls
  --   用的是 LSP 的 0-based 行号。实测逐条比对：ilean 49 ↔ toPosition 50。
  Json.mkObj [("line", Json.num (JsonNumber.fromNat (pos.line - 1))),
              ("col",  Json.num (JsonNumber.fromNat pos.column))]

run_cmd do
  let env ← getEnv
  let tc ← IO.FS.readFile "D:\\munkres-formal\\lean-toolchain"
  IO.println s!"# TOOLCHAIN {tc}"

  -- 模块表从生成好的清单读（见 MANIFEST 的注释：硬编码会过期）
  let mj ← IO.FS.readFile MANIFEST
  let files : Array (String × String) :=
    match Json.parse mj with
    | .ok (.arr a) =>
      a.filterMap fun e =>
        match e with
        | .arr #[Json.str m, Json.str f] => some (m, f)
        | _ => none
    | _ => #[]
  IO.println s!"# MODULES {files.size}"

  let mut entries : Array Json := #[]
  let mut cmdCount := 0
  let mut sigCount := 0
  let mut filesWithErr := 0

  for (mod, fn) in files do
    let path := SRC_DIR ++ fn
    let content ← IO.FS.readFile path
    let inputCtx : Parser.InputContext := Parser.mkInputContext content path
    let (_, mps0, hdrMsgs) ← Parser.parseHeader inputCtx
    let pmctx : Parser.ParserModuleContext := { env := env, options := {} }
    let mut mps := mps0
    let mut msgs : MessageLog := hdrMsgs
    let mut done := false
    while !done do
      let (stx, mps', msgs') := Parser.parseCommand inputCtx pmctx mps msgs
      mps := mps'
      msgs := msgs'
      cmdCount := cmdCount + 1
      if Parser.isTerminalCommand stx then
        done := true
      else
        -- ★ 签名节点有两种（官方语法，Lean/Parser/Command.lean:128/149）：
        --   `declSig`    （类型必须写）← theorem / instance / opaque / axiom
        --   `optDeclSig` （类型可省）  ← def / abbrev / class / structure / inductive / ctor / example
        -- 只认 `declSig` 会把所有 def/abbrev/class 漏掉（本节 25 条声明只会认出 13 条）。
        let sig? := (findKind stx ``Parser.Command.declSig).orElse
          (fun _ => findKind stx ``Parser.Command.optDeclSig)
        if let some sig := sig? then
          sigCount := sigCount + 1
          let idName :=
            match findKind stx ``Parser.Command.declId with
            | some id => (declShortName id).getD "?"
            | none => "?"
          -- 签名（声明器 + 类型）的范围 → LSP 行列（与 .ilean 的 usages 直接对齐）
          let fm := inputCtx.fileMap
          let sigStart := (sig.getPos?).getD 0
          let sigStop  := (sig.getTailPos?).getD 0
          -- 整个 command 的起点，供 Python 侧与 .ilean 的 decls 对齐
          let cmdStart := (stx.getPos?).getD 0
          entries := entries.push <| Json.mkObj
            [ ("module",   Json.str mod)
            , ("name",     Json.str idName)
            , ("sigStart", toPos fm sigStart)
            , ("sigStop",  toPos fm sigStop)
            , ("cmdStart", toPos fm cmdStart)
            ]
    if msgs.hasErrors then
      filesWithErr := filesWithErr + 1
      IO.println s!"# WARN {mod} 有 parse 错误（仍输出已解析部分）"
      for m in msgs.toList.take 5 do
        IO.println s!"#   line {m.pos.line + 1}"

  IO.println s!"# FILES {files.size}"
  IO.println s!"# COMMANDS {cmdCount}"
  IO.println s!"# DECLS_WITH_SIG {sigCount}"
  IO.println s!"# FILES_WITH_ERR {filesWithErr}"

  let doc : Json := Json.mkObj
    [ ("toolchain", Json.str tc)
    , ("files",     Json.num (JsonNumber.fromNat files.size))
    , ("decls",     Json.arr entries)
    ]
  IO.FS.writeFile (OUT_DIR ++ "decl_sig_ranges.json") doc.pretty
  IO.println s!"# WROTE {OUT_DIR}decl_sig_ranges.json"
  IO.println "# DONE"
