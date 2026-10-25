import MunkresLean

/-!
# 结构边（I / R 层）导出器

**输出：`knowledge/schema/_lean_probe/struct_edges.json`**（不要手改，每次跑都覆盖）

## 为什么这一段必须在 Lean 里算，不能用 Python 解析文本

```
InductiveVal.ctors : List Name        ← 类型安全的字段
RecursorVal.all    : List Name        ← 类型安全的字段
```

如果把它们先写成 TSV 再让 Python 切 tab / 正则匹配，那每一环都可能静默出错：
列数变了、名字里带制表符、层标串拼错…… 而**在 Lean 里它们是结构字段，编译器保证形状**。

⟹ **计算放 Lean，Python 只读 JSON。JSON 用 `Lean.Json` 构造，不手写转义。**

## 为什么 I/R 不能用 .ilean

`.ilean` 的 `decls` 只含【源码里显式写的】声明名：
```
Init.Prelude 的 decls 有 Prod，但 Prod.mk / Prod.rec / Prod.fst 【都不在】
```
⟹ 构造子 / 递归子 / 投影是【自动生成】的，不在源码里 ⟹ `.ilean` 的 references 里也没有。

⟹ 它们只能从 olean 的**结构字段**取（本文件做的事）。
★ 而那两个字段【本来就干净】—— 它们不是 elaborate 出来的 term。

## 口径

```
筛     名字以 `Munkres` 开头的声明（本工程的命名空间）
I 层   inductInfo → 它的每个 ctor         → {"src": 类型, "dst": 构造子, "layer": "I"}
R 层   recInfo    → 它的每个 all 成员     → {"src": 递归子, "dst": 成员, "layer": "R"}
★ 不产生任何顶层声明（全部逻辑在 run_cmd 的 do 块内）
-/

open Lean

run_cmd do
  let env ← getEnv
  let tc ← IO.FS.readFile "D:\\munkres-formal\\lean-toolchain"
  IO.println s!"# TOOLCHAIN {tc}"

  let isOurs (n : Name) : Bool := n.toString.startsWith "Munkres"

  let ours ← env.constants.foldM (init := #[]) fun acc n ci => do
    if isOurs n then pure (acc.push (n, ci)) else pure acc
  IO.println s!"# OUR_CONSTANTS {ours.size}"

  -- 逐条抽 I / R，直接构造 Json（不手写转义）
  let mut inds : Nat := 0
  let mut recs : Nat := 0
  let mut nodes : Array Json := #[]
  for (n, ci) in ours do
    match ci with
    | .inductInfo val =>
      inds := inds + 1
      for c in val.ctors do
        nodes := nodes.push <| Json.mkObj
          [("src", Json.str n.toString), ("dst", Json.str c.toString), ("layer", Json.str "I")]
    | .recInfo val =>
      recs := recs + 1
      for c in val.all do
        nodes := nodes.push <| Json.mkObj
          [("src", Json.str n.toString), ("dst", Json.str c.toString), ("layer", Json.str "R")]
    | _ => pure ()

  IO.println s!"# INDUCTIVES {inds}"
  IO.println s!"# RECURSORS {recs}"
  IO.println s!"# STRUCT_EDGES {nodes.size}"

  let doc : Json := Json.mkObj
    [ ("toolchain",    Json.str tc)
    , ("our_constants", Json.num (JsonNumber.fromNat ours.size))
    , ("inductives",   Json.num (JsonNumber.fromNat inds))
    , ("recursors",    Json.num (JsonNumber.fromNat recs))
    , ("struct_edges", Json.arr nodes)
    ]

  let outDir : String := "D:\\munkres-formal\\.probe\\"
  IO.FS.writeFile (outDir ++ "struct_edges.json") doc.pretty
  IO.println s!"# WROTE {outDir}struct_edges.json"
  IO.println "# DONE"
