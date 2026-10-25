/-
Copyright (c) 2026 tutor. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.
Authors: tutor
-/
import Mathlib

/-!
# ContentSupport —— 从「内容层的整组声明」反向传播，得到**基底范围候选**

## 为什么这样做

mathlib 的 **import 图是自连通的**（经 hub，几乎所有模块互相可达）⟹ 模块级闭包 = 整个库，
不能用来定基底边界。但**声明级语义**（一个声明的类型里提到谁）不是这样：从内容层的
声明组出发沿类型引用反向传播，得到的是一个窄得多的支撑集 = 基底候选。

## 口径（2026-10-24 学员）

- 支撑集里**用不到的**东西是**静默的** ⟹ 过近似是安全的，不需要逐条裁决。
- 所以种子取「内容层的整组声明」而不是几个根名（class 的根类型不含字段，单点种子会枯竭）。

## 运行（必须在一个能 `import Mathlib` 的工程里；本库自身缺 Batteries.olean）

```
cd D:\lean\munkres_lean
lake env lean D:\munkres-formal\tools\lean-probes\ContentSupport.lean
```

输入：`<repo>/.probe/seeds_content.json`（声明名数组）
输出：`<repo>/.probe/base_candidate.json`（基底候选 = visited − content 种子；内容层自身不是基底，不扣除会导致 ③a′ 误判）
-/

open Lean Elab Command

namespace ContentSupport

/-- 声明级邻居：类型（陈述层）里提到的所有常量。 -/
def typeRefs (env : Environment) (n : Name) : Array Name :=
  match env.find? n with
  | none => #[]
  | some ci => ci.type.getUsedConstants

partial def closure (env : Environment) (todo : List Name) (seen : NameSet) (acc : Array Name) :
    Array Name × NameSet :=
  match todo with
  | [] => (acc, seen)
  | n :: rest =>
    if seen.contains n then
      closure env rest seen acc
    else
      let refs := typeRefs env n
      closure env (refs.toList ++ rest) (seen.insert n) (acc.push n)

/-- 名字是否值得保留（去掉内部辅助名）。 -/
def keepName (n : Name) : Bool :=
  let s := n.toString
  !s.startsWith "_private" && !s.startsWith "_aux" && !s.contains "__"

def seedsPath : String := "D:\\munkres-formal\\.probe\\seeds_content.json"
def outPath : String := "D:\\munkres-formal\\.probe\\base_candidate.json"

end ContentSupport

run_cmd do
  let s ← liftIO <| IO.FS.readFile ContentSupport.seedsPath
  let j ← match Json.parse s with
    | .ok j => pure j
    | .error e => throwError "seeds json parse error: {e}"
  let arr ← match j.getArr? with
    | .ok a => pure a
    | .error e => throwError "seeds not array: {e}"
  let seeds : List Name := arr.toList.filterMap (fun x =>
    match x.getStr? with
    | .ok s => some s.toName
    | .error _ => none)
  logInfo m!"content seeds: {seeds.length}"
  let seedSet : NameSet := seeds.foldl (fun acc n => acc.insert n) {}
  let env ← getEnv
  let (acc, _seen) := ContentSupport.closure env seeds {} #[]
  let visited := acc.filter ContentSupport.keepName |>.toList
  -- ★ 基底候选 = visited − content 种子（内容层自身不是基底；不扣除会导致 ③a′ 把内容当基底）
  let base := visited.filter (fun n => !seedSet.contains n)
  let body := String.intercalate "," (base.map fun n => "\"" ++ n.toString ++ "\"")
  liftIO <| IO.FS.writeFile ContentSupport.outPath ("[" ++ body ++ "]")
  logInfo m!"visited: {visited.length} · content seeds: {seeds.length} · base candidate: {base.length}"
