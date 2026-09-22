"""静态审计：**每一份反向验证脚本的注入锚点还找得到吗**。

### 为什么要有这一条（2026-09-23 实测代价）

`_tools/*/_reverse_verify_*.py` 那 96 份脚本，靠「把源码里某一段原文换成 bug → 跑检查 →
确认它红在预期的那一条 → 还原」来证明红线**真的有牙**。它们的共同前提是：
**那段原文还在**（原文没了就替换不动，这一条注入静默失效）。

源码一改写法（换缩进、把一行拆成多行、加个具名参数），`src.count(old)` 就从 1 变 0，
脚本会打印 `[SKIP] … 无法唯一替换` 并把这一条计为不达标 —— **脚本本身是对的**
（本项目铁律：「永远红的检查 = 没有检查」，同理「静默跳过的注入 = 没有注入」）。

真正的问题是**它多久才被发现一次**：

- 全量反向验证 `_reverse_verify_all.py` 跑一遍要 **50 分钟以上**，不可能每个改动都跑；
- 平时用的 `--changed` 是按「注入目标涉及本次改动文件」挑子集 —— 一个**没人动过的**文件的
  陈旧锚点永远不会被挑中，于是一直躺在那里。

2026-09-23 实测抓到一例：`_reverse_verify_notify.py` 里「共用行组件把 onClick 收下就丢」那条，
锚的是 `ProfileRow.kt` 里的
`.then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)` ——
2026-09-22 用户要求「点一下不要那个水波纹」，这一行改成了多行 + `indication = null` 的写法。
**红线那一侧当时跟着改了锚点**（`_check_notify_guardrails.py` 有注释），
**反向验证这一侧没改** → 45 条注入里有 1 条从此恒为 SKIP。

### 这一条检查做什么

不跑任何注入（那是 50 分钟），只做**静态核对**：把 96 份脚本 AST 解析一遍，抽出它们声明的
「(目标文件, 被替换的原文)」，逐个确认**原文在那个文件里还找得到**。96 份一两秒扫完，
于是它可以进 `_check_all.py` 的常跑组 —— 锚点一腐烂**当天就报红**，不用等下次有人跑全量。

判据是「**还找得到**」（`count >= 1`），不是「恰好一次」：这 96 份脚本的替换语义有四种写法
（`count(old) != 1` 拒绝 / `src.replace(old, new)` 全换 / `replace(old, new, 1)` 只换第一处 /
`re.subn(..., count=1)`），**要求恰好一次会在那几种"全换也算数"的脚本上误报**。
0 次则是**任何**一种语义都跑不动的 —— 那才是要报的。

⚠️ 它**不替代**反向验证：锚点还在 ≠ 那条注入真能让检查变红（判据写错、期望文案对不上都测不出来）。
这条只负责「**别让注入悄悄失效**」，两件事互补。

用法：python _tools/qa/_check_reverse_verify_anchors.py [--verbose]
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

REPO = Path(__file__).resolve().parents[2]

#: 扫哪个目录、按什么前缀认脚本（**自己算**，不手写清单）。
GLOBS = ("_tools/*/_reverse_verify_*.py",)

#: 调度器没有注入表。
EXCLUDE_NAMES = {"_reverse_verify_all.py"}

#: 兜底下限：低于它就说明「抽取逻辑本身失效了」，必须先报错，
#: 而不是安静地什么都查不到（本项目栽过 5 次的形状）。
MIN_SCRIPTS = 90
MIN_CASES = 850

#: 有些脚本把"替换"包成自己的小助手（`sub("原文", "替换成")`）——这一格也要认。
HELPER_NAMES = {"sub", "substitute", "replace", "mutate", "inject", "swap"}

#: 算"源码文件"的后缀 —— 目标路径解析出这些东西但文件不存在 = 被改名/搬走了。
SRC_SUFFIXES = {
    ".py", ".kt", ".kts", ".java", ".md", ".json", ".txt", ".yaml", ".yml",
    ".toml", ".cfg", ".ini", ".sql", ".gradle", ".xml", ".sh", ".env", ".csv",
}

#: 允许「锚点找不到」的书面理由（键 = (脚本名, 标签)）。⛔ 不是"修不动就放行"，
#: 每条都要写清它为什么**必然**找不到。
ALLOW: dict[tuple[str, str], str] = {
    (
        "_reverse_verify_driver_money.py",
        "司机端新增一个画金额的页面（清单自己算 → 必须点名它）",
    ): "这条注入**故意新建一个文件**（`_LeakScreen.kt`，跑完删掉）来试「清单自己算」那条判据，"
       "所以「目标文件不存在」正是它一开始的状态，不是锚点腐烂。",
}


def iter_scripts() -> list[Path]:
    out: list[Path] = []
    for g in GLOBS:
        out.extend(REPO.glob(g))
    return sorted(p for p in out if p.name not in EXCLUDE_NAMES)


# ---------------------------------------------------------------- 路径表达式求值

def _chain(node: ast.AST) -> tuple[str | None, int | None]:
    """把 `Path(__file__).resolve().parent` / `...parents[2]` 折成 (base, index)。

    ⚠️ `parents[2]` 是 **Subscript**（`Call(...).parents` 再下标），不是 `Call(attr="parents")`
    —— 第一版漏了这一点，`ROOT` 解析不出来，96 份脚本里有 80 份的注入表直接是空的
    （幸好留了条数下限，否则会变成一条"永远绿"的检查）。
    """
    idx: int | None = None
    cur = node
    while True:
        if isinstance(cur, ast.Subscript):
            if isinstance(cur.value, ast.Attribute) and cur.value.attr == "parents":
                if isinstance(cur.slice, ast.Constant) and isinstance(cur.slice.value, int):
                    idx = cur.slice.value
                cur = cur.value.value
                continue
            return None, None
        if isinstance(cur, ast.Call):
            fn = cur.func
            if isinstance(fn, ast.Name) and fn.id == "Path":
                if cur.args and isinstance(cur.args[0], ast.Name) and cur.args[0].id == "__file__":
                    # ⚠️ `idx is None` 的语义是「**这个文件本身**」（还没取过 parent）——
                    #    绝不能兜成 `parents[0]`：`.parent` 在 Python AST 里是 **Attribute**
                    #    （由 `resolve` 那一支再加一层），这里再兜一次就会多剥一层目录，
                    #    于是 `HERE` 从 `_tools/ai` 变成 `_tools`、96 条锚点全被报成"目标文件不存在"。
                    return ("script_file", idx)
                if cur.args and isinstance(cur.args[0], ast.Constant) and isinstance(cur.args[0].value, str):
                    return ("literal", cur.args[0].value)  # type: ignore[return-value]
                return None, None
            if isinstance(fn, ast.Attribute):
                if fn.attr == "resolve":
                    cur = fn.value
                    continue
            return None, None
        return None, None


def _chain_result(node: ast.AST, script: Path) -> Path | None:
    base, idx = _chain(node)
    if base == "script_file":
        if idx is None:
            return script  # `Path(__file__).resolve()` 就是脚本自己
        # ⚠️ `Path(f).parents[0]` 就是 `Path(f).parent` —— 两者同一套下标，
        #    第一版按 `parents[idx - 1]` 算，于是所有写 `parents[2]` 的脚本
        #    ROOT 全落到 `_tools/` 上、注入表一条都抽不出来（51 份脚本静默变成 0 条）。
        return script.parents[idx]
    if base == "literal":
        return REPO / str(idx)
    return None


def resolve(node: ast.AST, script: Path, consts: dict[str, ast.AST], seen: set[str]) -> Path | None:
    """把路径表达式折成绝对路径；认不出来回 None（**不当错误**，只是少查一条）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        p = node.value.replace("\\", "/")
        cand = REPO / p
        if cand.exists():
            return cand
        cand2 = script.parent / p
        return cand2 if cand2.exists() else cand
    if isinstance(node, ast.Name):
        if node.id in seen or node.id not in consts:
            return None
        return resolve(consts[node.id], script, consts, seen | {node.id})
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = resolve(node.left, script, consts, seen)
        if left is None:
            return None
        right = node.right
        if isinstance(right, ast.Constant) and isinstance(right.value, str):
            return left / right.value.replace("\\", "/")
        if isinstance(right, ast.Name) and right.id in consts:
            r = resolve(right, script, consts, seen | {right.id})
            return (left / r.name) if r is not None else None
        return None
    if isinstance(node, ast.Call):
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id in {"repo_root", "root"}:
            return REPO
        if isinstance(fn, ast.Attribute) and fn.attr == "joinpath":
            base = resolve(fn.value, script, consts, seen)
            if base is None:
                return None
            for a in node.args:
                if isinstance(a, ast.Constant):
                    base = base / str(a.value).replace("\\", "/")
            return base
        return _chain_result(node, script)
    if isinstance(node, ast.Subscript):
        # `Path(__file__).resolve().parents[2]` 整条是 **Subscript**（不是 Call）——
        # 漏了这一支，所有写 `parents[N]` 的脚本 ROOT 都解析成 None，
        # 51 份脚本的注入表一条都抽不出来（而"抽不出来"看起来是绿的：没有锚点可核对）。
        return _chain_result(node, script)
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        # `HERE.parent.parent` 这种**纯属性链**（不是 `Path(...).parent` 调用）：
        # 漏了它，`ROOT = HERE.parent.parent` 那一类脚本的注入表同样是空的。
        base = resolve(node.value, script, consts, seen)
        return base.parent if base is not None else None
    return None


def const_string(node: ast.AST, consts: dict[str, ast.AST], seen: frozenset[str] = frozenset()) -> str | None:
    """把一格折成字符串（含相邻字面量拼接、`"a" + "b"`、Name 引用、`re.escape(x)`）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in seen or node.id not in consts:
            return None
        return const_string(consts[node.id], consts, seen | {node.id})
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a = const_string(node.left, consts, seen)
        b = const_string(node.right, consts, seen)
        return None if a is None or b is None else a + b
    if isinstance(node, ast.Call):
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr in {"escape", "quote"} and node.args:
            return const_string(node.args[0], consts, seen)
    if isinstance(node, ast.JoinedStr):
        out = ""
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                out += v.value
            else:
                return None
        return out
    return None


def collect_consts(tree: ast.Module) -> dict[str, ast.AST]:
    out: dict[str, ast.AST] = {}
    for st in ast.walk(tree):
        if isinstance(st, ast.Assign):
            for t in st.targets:
                if isinstance(t, ast.Name):
                    out.setdefault(t.id, st.value)
        elif isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name) and st.value is not None:
            out.setdefault(st.target.id, st.value)
    return out


# ---------------------------------------------------------------- 从一格抽出「被替换的原文」

def pairs_in(node: ast.AST, consts: dict[str, ast.AST], depth: int = 0) -> list[tuple[str, str]]:
    """从一格（常量 / Name / lambda / 调用 / 列表）里抽出所有 (被替换的原文, 替换成) 对。

    四种写法都要认（这就是 96 份脚本的实际形状）：
      · `"原文"`（配对的"替换成"在下一格）
      · `lambda s: s.replace("原文", "新文", 1)`
      · `lambda s: re.subn(re.escape("原文"), "新文", s, count=1)[0]`
      · `[("原文", "新文"), …]`（一次注入多处）
    """
    if depth > 3:
        return []
    if isinstance(node, ast.Name):
        if node.id not in consts:
            return []
        return pairs_in(consts[node.id], consts, depth + 1)
    s = const_string(node, consts)
    if s is not None:
        return [(s, "")]
    if isinstance(node, (ast.Lambda, ast.FunctionDef)):
        return _pairs_from_calls(node, consts, depth)
    if isinstance(node, ast.Call):
        # 有些脚本把"替换"包成自己的小助手：`sub("原文", "替换成")`（order_return 那份就是）。
        if isinstance(node.func, ast.Name) and node.func.id in HELPER_NAMES and len(node.args) >= 2:
            a = const_string(node.args[0], consts)
            b = const_string(node.args[1], consts)
            if a:
                return [(a, b or "")]
        got = _pairs_from_calls(node, consts, depth)
        return got or []
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        out: list[tuple[str, str]] = []
        for el in node.elts:
            if isinstance(el, ast.Tuple) and len(el.elts) >= 2:
                a = const_string(el.elts[0], consts)
                b = const_string(el.elts[1], consts)
                if a:
                    out.append((a, b or ""))
            else:
                out.extend(pairs_in(el, consts, depth + 1))
        return out
    return []


def _pairs_from_calls(node: ast.AST, consts: dict[str, ast.AST], depth: int) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call) or not isinstance(sub.func, ast.Attribute):
            continue
        name = sub.func.attr
        if name in {"replace", "subn", "sub"} and len(sub.args) >= 2:
            a = const_string(sub.args[0], consts)
            b = const_string(sub.args[1], consts)
            if a is not None and a:
                out.append((a, b or ""))
    return out


# ---------------------------------------------------------------- 核对

def count_in(text: str, old: str) -> int:
    """按各脚本读源码的实际口径数一遍（它们普遍把 CRLF 统一成 \\n 再数）。"""
    if not old:
        return 0
    n = text.replace("\r\n", "\n").count(old)
    if n:
        return n
    return text.count(old)


def regex_hit(text: str, old: str) -> bool:
    """有些脚本用 `re.subn(…)` 注入，那一格是**正则**：按正则再试一次。

    ⚠️ 要连 `re.S` 一起试：`_reverse_verify_vm_init_order.py` 那条锚点跨行、靠 `flags=re.S`
    才能匹配 —— 只按默认 flags 判会把一条**好好的**注入报成失效（误报比漏报更伤，
    这条检查是要天天跑的）。
    """
    for flags in (0, re.S, re.M, re.S | re.M):
        try:
            if re.search(old, text, flags) is not None:
                return True
        except re.error:
            return False
    return False


def audit_script(
    script: Path, seen_keys: set[tuple[str, str]] | None = None
) -> tuple[list[tuple[str, Path, list[str]]], int]:
    """返回 (问题列表, 本脚本核对的"原文"条数)。问题 = (标签, 目标文件, 说明列表)。"""
    src = script.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:  # pragma: no cover
        return [("<整份脚本>", script, [f"AST 解析失败：{e}"])], 0
    uses_regex = "re.subn(" in src or re.search(r"\bre\.sub\(", src) is not None

    consts = collect_consts(tree)
    problems: list[tuple[str, Path, list[str]]] = []
    checked = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Tuple) or not (3 <= len(node.elts) <= 7):
            continue
        label = const_string(node.elts[0], consts)
        if label is None or not label.strip() or len(label) > 200:
            continue
        target = resolve(node.elts[1], script, consts, set())
        if target is None:
            continue
        if not target.exists() and target.suffix.lower() not in SRC_SUFFIXES:
            continue  # 认错了格（比如这一格本来就不是路径）——宁可少查，不许误报

        # ⚠️ 3 元组 `(说明, 路径, 期望关键词)` 的第三格是**期望文案**（那一类注入是
        #    "把文件搬走/改名"，根本不替换文本）—— 当成锚点会报两条假红（实测踩过）。
        if len(node.elts) == 3 and isinstance(node.elts[2], ast.Constant):
            continue

        olds: list[str] = []
        for a, _ in pairs_in(node.elts[2], consts):
            olds.append(a)
        if not olds:
            continue
        if seen_keys is not None:
            seen_keys.add((script.name, label))

        if not target.exists():
            checked += len(olds)
            if (script.name, label) not in ALLOW:
                problems.append((label, target, ["目标文件不存在（被改名/搬走了？）"]))
            continue
        text = target.read_text(encoding="utf-8", errors="replace")
        bad: list[str] = []
        for old in olds:
            checked += 1
            # 有些脚本用 `re:` 前缀显式标出"这一格是正则"（替换串按正则匹配）。
            if old.startswith("re:"):
                if regex_hit(text, old[3:]):
                    continue
                bad.append(f"正则找不到（{preview(old[3:])}）")
                continue
            if count_in(text, old) >= 1:
                continue
            if uses_regex and regex_hit(text, old):
                continue
            bad.append(f"原文找不到（{preview(old)}）")
        if bad and (script.name, label) not in ALLOW:
            problems.append((label, target, bad))
    return problems, checked


def preview(s: str, n: int = 60) -> str:
    one = " ".join(s.split())
    return one[:n] + ("…" if len(one) > n else "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="（兼容 _check_all 的调用约定；失败一律非零退出）")
    ap.add_argument("--verbose", action="store_true", help="逐份列出核对了多少条原文")
    args = ap.parse_args()

    scripts = iter_scripts()
    total = 0
    n_scripts_with_table = 0
    all_problems: list[tuple[Path, str, Path, list[str]]] = []
    per: list[tuple[Path, int, int]] = []
    seen_keys: set[tuple[str, str]] = set()
    for s in scripts:
        problems, n = audit_script(s, seen_keys)
        total += n
        if n:
            n_scripts_with_table += 1
        per.append((s, n, len(problems)))
        for label, target, why in problems:
            all_problems.append((s, label, target, why))

    print(f"扫到 {len(scripts)} 份反向验证脚本（自己算），核对了 {total} 条注入原文。")
    if args.verbose:
        for s, n, bad in sorted(per, key=lambda x: x[1]):
            print(f"  {'❌' if bad else '  '} {s.relative_to(REPO)}  {n} 条" + (f"，{bad} 处失效" if bad else ""))

    fail = False
    if len(scripts) < MIN_SCRIPTS:
        print(f"❌ 只扫到 {len(scripts)} 份脚本（少于 {MIN_SCRIPTS}）：抽取逻辑失效了，先修这个。")
        fail = True
    if total < MIN_CASES:
        print(
            f"❌ 只核对到 {total} 条原文（少于 {MIN_CASES}）："
            "AST 抽取认不出这些脚本的写法了 —— **抽取失效比锚点腐烂更危险**（那会变成一条永远绿的检查）。"
        )
        fail = True

    # ⚠️ 化石防御：ALLOW 里的键必须还是真存在的（脚本名, 标签）——
    #    写过理由的那条注入被删掉/改名之后，理由会**永远留在表里**，
    #    看起来"这条已经处理过了"，其实它早就不存在了（本项目在覆盖率那张 EXCLUDED 表上栽过）。
    fossils = sorted(k for k in ALLOW if k not in seen_keys)
    if fossils:
        print(f"\n❌ 允许表里有 {len(fossils)} 条化石（脚本/标签已经不存在了，理由该删）：")
        for name, label in fossils:
            print(f"  · {name} ｜ {label}")
        fail = True

    if all_problems:
        print(f"\n❌ {len(all_problems)} 条注入的锚点已经失效（这些反向验证现在是恒 SKIP 的）：")
        for s, label, target, why in all_problems:
            rel = target.relative_to(REPO) if target.is_relative_to(REPO) else target
            print(f"  · {s.relative_to(REPO)}")
            print(f"      标签：{label}")
            print(f"      目标：{rel}")
            for w in why:
                print(f"      问题：{w}")
        print("\n修法：去那份脚本里把「被替换的原文」改成目标文件里现在真实的写法（**只改锚点，不动判据**）。")
        fail = True

    if not fail:
        print(f"✅ {total} 条注入原文全部还在（{n_scripts_with_table}/{len(scripts)} 份脚本的注入表都认得出）。")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
