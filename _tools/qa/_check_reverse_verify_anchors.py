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

### 2026-09-24 第 35 轮补的那一半：**「锚点找不到」有两种，修法相反**

那次实测代价：一份反向验证被**硬中断**（工具调用被取消 → 进程树被杀），
`AiRevert.kt` 里留下了**注入的 bug**（`顺序**整份**`）。这条检查当时报的是
「1 条注入原文找不到了」，而这句话的**默认修法**是「去脚本里把锚点改成现在的写法」——
照着做就等于**把注入的 bug 永久钉进源码**，那条反向验证从此恒绿（比锚点腐烂严重得多）。

所以现在把两种成因分开判：

| 现象 | 判定 | 修法 |
| --- | --- | --- |
| 原文找不到，**替换串也不在** | 锚点腐烂（源码改了写法） | 去脚本里更新锚点（只改锚点，不动判据） |
| 原文找不到，而**替换串正躺在目标文件里** | **注入残留**（上一次反向验证没还原） | `--restore` 按注入串换回原文；⛔ **绝不要去改锚点** |

判据是注入的"另一半"：每条注入都声明了「原文 → 替换成」，替换串只可能来自注入本身。

### 2026-10-03 补的第二支：**不写成元组的注入表**（r4_all 那次整份被打断）

`_reverse_verify_r4_all.py` 这类脚本把注入写成 `sb.replace(路径, "原文", "替换成")` —— 一条
元组都没有，所以上面那支抽取**一条都看不见**（报告里那一行是「0 条」，而 0 条看起来是正常的）。
代价：它的一条锚点（`    money: Money`）在 `pricing.py` 里出现了 2 次，`Sandbox.replace` 的
唯一性守卫直接断言失败，**整份脚本被打断** —— 全量反向验证 77 分钟里这一份白跑，
剩下的用例一条都没跑，报告里只留一句「非零退出」。

所以现在两支一起抽（两支共用同一套成因判断 `judge_missing()`），并且多一条下限：

| 下限 | 盯的是什么 | 实测（2026-10-03） |
| --- | --- | --- |
| `MIN_SCRIPTS` | `GLOBS` 还扫得到脚本 | 153 |
| `MIN_SCRIPTS_WITH_TABLE` | **注入表认得出的脚本数**（抽不出来 = 安静地少查） | 128 |
| `MIN_CASES` | 核对到的锚点总数 | 1423 |
| `MIN_WITH_NEW` | 拿得到「替换成」的锚点数（注入残留那一半判据靠它） | 1240 |

唯一性只在**自己断言了唯一**的助手上要求（`strict_helper_names()`：函数体里有
`count(...) == 1`）：`Sandbox.replace` 会要求；同一个类里的 `Sandbox.sub` 是故意的「全换」
语义、**不要求** —— 按整份脚本判严格，会给那几条 `sub` 注入报假红。

### 2026-10-04 补的第三支：**说明书里的条数也要对账**（CHG-0021）

`_check_*.py` 的模块 docstring 常写「配套：python `_reverse_verify_x.py`（N 种破坏方式全被抓）」。
那个 N **原来谁都不管**：加注入的人不会回头改这句话，于是它安静地烂成**第二份真相**——
看起来是"这条红线被 N 种破坏证明过"，其实那个 N 早在几次补注入之后就过期了。
2026-10-04 实测 **8 处声明里 6 处是错的**：`_check_order_list_ui.py` 写 8（真实 28）、
`_check_sheet_form_pages.py` 写 23（真实 28）、`_check_adaptive_layout.py` 写 8（真实 12）、
`_check_list_order.py` 写 9（真实 13）、`_check_map_picker.py` 写 5（真实 7）、
`_check_profile_page.py` 写 12（真实 16）。

口径：N 必须等于那份脚本**破坏方式表的条数**（`INJECTIONS` / `CASES` 列表的元素个数 ——
也就是脚本自己打印的那个分母）。声明里若还写了 `a/b`，要求 `a == b` 且分母等于表长
（或表长 +1：`_reverse_verify_money_display.py` / `_reverse_verify_time_base.py`
把「还原复检」也算作一种）。⛔ 只对账条数，不评价措辞。

用法：
  python _tools/qa/_check_reverse_verify_anchors.py [--verbose]
  python _tools/qa/_check_reverse_verify_anchors.py --restore   # 还原注入残留（会先备份）
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import refuse_if_injecting  # noqa: E402

REPO = Path(__file__).resolve().parents[2]

#: 扫哪个目录、按什么前缀认脚本（**自己算**，不手写清单）。
GLOBS = ("_tools/*/_reverse_verify_*.py",)

#: 调度器没有注入表。
EXCLUDE_NAMES = {"_reverse_verify_all.py"}

#: 兜底下限：低于它就说明「抽取逻辑本身失效了」，必须先报错，
#: 而不是安静地什么都查不到（本项目栽过 5 次的形状）。
#: 2026-10-03 实测 153 / 1423，按 ~5% 余量定；改动抽取逻辑后要跟着复核。
MIN_SCRIPTS = 145
MIN_CASES = 1350

#: 「注入表**认得出**的脚本数」下限（5 元组形状 ∪ 注入助手调用形状）。
#: 为什么要有它：一份脚本的注入表抽不出来时，报告里那一行显示的是 **0 条**，
#: 而 0 条**看起来是正常的** —— 这个仓库栽过 5 次的形状就是「安静地少查」。
#: 2026-10-03 加：`_reverse_verify_r4_all.py` 就是这么藏了一条腐烂的锚点。
MIN_SCRIPTS_WITH_TABLE = 122   # 实测 128（2026-10-03）

#: 能拿到「替换成」那一格的锚点数下限（第 35 轮加的判据要用它）——2026-10-03 实测 1240 条，
#: 抽不出来时就会有一条"注入残留永远判不出来"的检查悄悄变成绿的，所以要有下限。
MIN_WITH_NEW = 1180

#: 「配套说明书」里的条数（2026-10-04 · CHG-0021 补的第三支）：`_check_*.py` 的模块 docstring
#: 常写「配套：python <rv>.py（N 种破坏方式全被抓）」，而这个 N **原来没有任何判据在管** ——
#: 加注入的人不会回头改这句，于是它安静地烂成**第二份真相**。实测 8 处声明里 6 处是错的
#: （`_check_order_list_ui.py` 写 8、真实 28；`_check_sheet_form_pages.py` 写 23、真实 28）。
#: 口径：N 必须等于那份脚本**破坏方式表的条数**（`INJECTIONS` / `CASES` 的元素个数，
#: 也就是它自己打印的那个分母）。⛔ 只对账条数，不评价措辞。
CHECK_GLOBS = ("_tools/*/_check_*.py",)

#: 声明的两种写法都要认：
#:   `配套：python _tools/qa/_reverse_verify_<名字>.py（8 种破坏方式全被抓）`
#:   `配套反向验证：`python _tools/qa/_reverse_verify_<名字>.py`（4 种破坏 5/5）。`
#: ⚠️ 这一节自己也是 `_check_*.py`（会扫到自己）：注释里的例子必须写成 `<名字>`，
#:    否则它会去认 `_reverse_verify_x.py` 这份不存在的脚本（第一版就踩了）。
#: ⚠️ 数字外面常带 `**`（`（**29** 种破坏方式…）`），所以 `**` 要允许出现在数字与「种破坏」之间。
RE_CLAIM = re.compile(r"(_tools/[^\s`）)]*_reverse_verify_[a-z0-9_]+\.py)[^\n]{0,40}?(\d+)\s*\**\s*种破坏")
RE_CLAIM_FRAC = re.compile(r"种破坏[^\n]{0,4}?(\d+)\s*/\s*(\d+)")

#: 声明指的那张表叫什么（脚本自己打印分母时用的就是这两个名字）。
CASE_TABLES = ("INJECTIONS", "CASES")

#: 核对得动的声明条数下限（低于它 = 抽取失效，必须先报错，别安静地什么都没查）。实测 8。
MIN_CLAIMS = 8

#: 有些脚本把"替换"包成自己的小助手（`sub("原文", "替换成")`）——这一格也要认。
HELPER_NAMES = {"sub", "substitute", "replace", "mutate", "inject", "swap"}

#: 「这个助手要求锚点**唯一**吗」的判据 = 助手自己的函数体里断言了「原文出现次数 == 1」。
#: ⚠️ 2026-10-03 加这一格之前，这类脚本的注入表**一条都抽不出来**（它们不是 5 元组形状），
#: 于是它们的锚点腐烂**永远不会被这条元检查看到**；实测代价见 MIN_SCRIPTS_WITH_TABLE 上面那段。
UNIQUE_GUARD_RE = re.compile(r"count\([^)]*\)\s*(?:==|!=|>=|<=|<|>)\s*1")

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
    (
        "_reverse_verify_driver_tab_highlight.py",
        "司机端新增一个按 vm.tab 算高亮的页面（清单自己算 → 必须点名它）",
    ): "同 `_reverse_verify_driver_money.py` 的那一条（BUG-0014 判据 4「清单自己算 → 必须点名新页面」）："
       "这条注入**故意新建一个文件**（`_LeakTabScreen.kt`，跑完删掉）来试那条判据 ——"
       "「目标文件不存在」正是它一开始的状态，不是锚点腐烂。",
    (
        "_reverse_verify_image_preview.py",
        "订单侧又抄了一份大图预览（扫全仓的那条判据必须点名它）",
    ): "同上面两条（CHG-0044 判据 1「全仓只有一处 fun ImagePreviewDialog(」）："
       "这条注入**故意新建一个文件**（`ui/common/_LeakPreviewScreen.kt`，跑完删掉）来试那条判据 ——"
       "「目标文件不存在」正是它一开始的状态，不是锚点腐烂。",
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

@dataclass
class Leftover:
    """一处**注入残留**：原文不在、而替换串在目标文件里（上一次反向验证被硬中断留下的）。"""

    script: Path
    label: str
    target: Path
    old: str
    new: str
    lineno: int
    hits: int


def restore_leftover(it: Leftover) -> tuple[bool, str]:
    """把一处注入残留按「替换串 → 原文」换回去。返回 (是否成功, 说明)。

    ⛔ 只在**替换串在文件里恰好出现一次**时才动手（宁可拒绝也不猜）：出现多次时分不清哪一处
    是注入留下的，猜错就把用户真写的内容改掉了。改之前先把原文件按字节备份到临时目录。
    """
    if it.hits != 1:
        return False, (
            f"替换串在文件里出现 {it.hits} 次，分不清哪一处是注入留下的 —— 没改任何东西，"
            "请人工看 `git diff <文件>`"
        )
    raw = it.target.read_bytes()
    crlf = b"\r\n" in raw
    plain = raw.decode("utf-8").replace("\r\n", "\n")
    if plain.count(it.new) != 1:
        return False, "替换串在按行尾归一后的文本里对不上，放弃（没改任何东西）"
    bak_dir = Path(tempfile.gettempdir()) / "dsh_rv_restore_backup"
    bak_dir.mkdir(parents=True, exist_ok=True)
    bak = bak_dir / (it.target.name + ".before-restore")
    bak.write_bytes(raw)
    fixed = plain.replace(it.new, it.old, 1)
    it.target.write_bytes((fixed.replace("\n", "\r\n") if crlf else fixed).encode("utf-8"))
    return True, f"已按注入串换回原文（原文件备份：{bak}）"


def count_in(text: str, old: str) -> int:
    """按各脚本读源码的实际口径数一遍（它们普遍把 CRLF 统一成 \\n 再数）。"""
    if not old:
        return 0
    n = text.replace("\r\n", "\n").count(old)
    if n:
        return n
    return text.count(old)


def line_of(text: str, needle: str) -> int:
    """`needle` 在文件里的行号（1 基）——报"注入残留"时要说清在哪儿。"""
    plain = text.replace("\r\n", "\n")
    i = plain.find(needle)
    if i < 0:
        return 0
    return plain[:i].count("\n") + 1


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


def strict_helper_names(src: str, tree: ast.Module) -> set[str]:
    """哪些**助手名**要求锚点唯一（它自己的函数体里断言了「原文出现次数 == 1」）。

    ⚠️ 判据必须落到**助手名**上，不能落到「整份脚本」上：`_reverse_verify_r4_all.py` 的
    `Sandbox.replace` 有唯一性守卫，而同一个类里的 `Sandbox.sub` 是**故意的「全换」语义**
    （`sub(..., "ROUND_HALF_UP", ...)` 就是要一次改掉两处）。
    按整份脚本判严格，会给那 5 条 `sub` 注入报 5 条**假红** —— 这条检查是要天天跑的，
    误报比漏报更伤。
    """
    out: set[str] = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or fn.name not in HELPER_NAMES:
            continue
        seg = ast.get_source_segment(src, fn) or ""
        if UNIQUE_GUARD_RE.search(seg):
            out.add(fn.name)
            continue
        # ⚠️ 间接写法也要认：`n = text.count(old)` 之后 `if n != 1:`（这个仓库的写法）。
        #    判据是「这个助手**自己断言了唯一**」，不认它写成一行还是两行 ——
        #    只认一行的话，把 assert 改成"先赋值再判"就会让这一格静默失效。
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign):
                continue
            val = node.value
            if not (
                isinstance(val, ast.Call)
                and isinstance(val.func, ast.Attribute)
                and val.func.attr == "count"
            ):
                continue
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(
                re.search(r"\b" + re.escape(nm) + r"\s*(?:==|!=|>=|<=|<|>)=?\s*1\b", seg)
                for nm in names
            ):
                out.add(fn.name)
                break
    return out


def judge_missing(
    script: Path, label: str, target: Path, text: str, old: str, new: str, uses_regex: bool
) -> tuple[str, object]:
    """原文在目标文件里**找不到**时判成因，返回 (种类, 说明)：

    ("ok", "")             正则锚点其实还命中（不是腐烂，别报）
    ("leftover", Leftover) 原文没了、而**替换串在** = 上一次注入没还原
    ("moved", "")          报表源码搬到了别的文件里，并集里找得到（不是腐烂）
    ("rot", 文案)          锚点腐烂（去更新锚点）

    ⚠️ 2026-10-03 把这段从元组那一支**抽出来共用**：新增的「注入助手调用」那一支也要判成因，
    而两处必须**一模一样** —— 分叉出去的那一份迟早会漏掉「注入残留」这一支，
    它的修法与锚点腐烂**正好相反**（照着「更新锚点」改 = 把注入的 bug 永久钉进源码）。
    """
    if uses_regex and regex_hit(text, old):
        return "ok", ""
    # ⛔ 原文没了，而**替换串在**：这不是锚点腐烂，是上一次注入没还原。
    #    两者的修法相反（一个要改锚点、一个绝不能改锚点），所以必须分开报。
    hits = count_in(text, new) if (new and new.strip()) else 0
    if hits:
        return "leftover", Leftover(
            script=script,
            label=label,
            target=target,
            old=old,
            new=new,
            lineno=line_of(text, new),
            hits=hits,
        )
    # 第二轮 R2-05：报表源码搬进了 `services/reports/` —— 注入器已经**按并集**找那一份
    # 含原文的文件（26 份走 Sandbox.apply 的回退、6 份走各自的 mutate 回退），
    # 所以这里也要按同一张清单判：并集里找得到就不算「锚点失效」。
    # ⛔ 否则这条元检查会把「搬家」判成「腐烂」，逼人去逐条改路径常量 —— 那正是要避免的。
    try:
        from _airepo import reports_files  # noqa: PLC0415

        for _c in reports_files():
            if _c == target:
                continue
            _t = _c.read_text(encoding="utf-8", errors="replace")
            if count_in(_t, old) >= 1 or (uses_regex and regex_hit(_t, old)):
                return "moved", ""
    except Exception:  # noqa: BLE001 —— 判据自己不该因为读不到包而崩
        pass
    return "rot", "原文找不到（" + preview(old) + "）"


def audit_script(
    script: Path, seen_keys: set[tuple[str, str]] | None = None
) -> tuple[list[tuple[str, Path, list[str]]], int, list[Leftover], int]:
    """返回 (锚点腐烂列表, 核对的原文条数, 注入残留列表, 能拿到替换串的条数)。

    问题 = (标签, 目标文件, 说明列表)；注入残留 = Leftover。
    """
    src = script.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:  # pragma: no cover
        return [("<整份脚本>", script, [f"AST 解析失败：{e}"])], 0, [], 0
    uses_regex = "re.subn(" in src or re.search(r"\bre\.sub\(", src) is not None

    consts = collect_consts(tree)
    problems: list[tuple[str, Path, list[str]]] = []
    leftovers: list[Leftover] = []
    checked = 0
    with_new = 0
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

        pairs = pairs_in(node.elts[2], consts)
        # ⚠️ 第 35 轮补：最常见的形状是 **5 元组** `(说明, 路径, 原文, 替换成, 期望)`
        #    ——「替换成」在 `elts[3]`，而 `pairs_in(elts[2])` 只给得出原文。
        #    少了这一格，「注入残留」就一条都判不出来（实测：只认 elts[2] 时 1160 条里
        #    只有 515 条拿得到替换串；补上 elts[3] 后 1018 条）。**只补空着的那一半**，
        #    lambda 形状自带的替换串不许被覆盖。
        nxt = const_string(node.elts[3], consts) if len(node.elts) >= 4 else None
        if nxt and nxt.strip():
            pairs = [(a, b or nxt) for a, b in pairs]
        olds = [a for a, _ in pairs]
        if not olds:
            continue
        if seen_keys is not None:
            seen_keys.add((script.name, label))
        with_new += sum(1 for _a, b in pairs if b and b.strip())

        if not target.exists():
            checked += len(olds)
            if (script.name, label) not in ALLOW:
                problems.append((label, target, ["目标文件不存在（被改名/搬走了？）"]))
            continue
        text = target.read_text(encoding="utf-8", errors="replace")
        bad: list[str] = []
        for old, new in pairs:
            checked += 1
            # 有些脚本用 `re:` 前缀显式标出"这一格是正则"（替换串按正则匹配）。
            if old.startswith("re:"):
                if regex_hit(text, old[3:]):
                    continue
                bad.append(f"正则找不到（{preview(old[3:])}）")
                continue
            if count_in(text, old) >= 1:
                continue
            # ⚠️ 2026-10-03：成因判断抽成 judge_missing 共用（下面「注入助手调用」那一支走的是
            #    同一个函数）。两条支路必须一模一样 —— 分叉出去的那一份迟早会漏掉「注入残留」
            #    这一支，而它的修法与锚点腐烂**正好相反**（改错方向 = 把注入的 bug 钉进源码）。
            kind, why = judge_missing(script, label, target, text, old, new, uses_regex)
            if kind == "leftover":
                leftovers.append(why)  # type: ignore[arg-type]
                continue
            if kind in ("ok", "moved"):
                continue
            bad.append(str(why))
        if bad and (script.name, label) not in ALLOW:
            problems.append((label, target, bad))

    # ------------------------------------------------------------ 第二支：函数式注入表
    # `sb.replace(路径 / "x.py", "原文", "替换成")` 这种**不写成元组**的注入表，上面那一支
    # 一条都抽不出来 ⇒ 它们的锚点腐烂**永远不会被这条元检查看到**（报告里那一行是「0 条」，
    # 而 0 条看起来是正常的）。2026-10-03 实测代价：`_reverse_verify_r4_all.py` 的一条锚点在
    # 源码里出现了 2 次，全量反向验证跑到它时被唯一性守卫**整份打断** —— 那一份白跑，
    # 剩下的用例一条都没跑，报告里只留一句「非零退出」。
    strict = strict_helper_names(src, tree)
    texts: dict[Path, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        name = node.func.attr
        if name not in HELPER_NAMES or len(node.args) < 2:
            continue
        h_target = resolve(node.args[0], script, consts, set())
        # ⛔ 必须要求它**是一个真实存在的文件**：`text.replace("a", "b")` 这类字符串方法也会
        #    走到这里（实测还撞上过 `Path("D:/")` 这种目录，直接把判据跑崩）。
        #    宁可少查，不许误报 —— 这条检查是要天天跑的。
        if h_target is None or not h_target.is_file():
            continue
        h_old = const_string(node.args[1], consts)
        if not h_old or not h_old.strip() or h_old.startswith("re:"):
            continue
        h_new = const_string(node.args[2], consts) if len(node.args) >= 3 else ""
        h_label = "注入助手调用 " + name + "()（脚本第 " + str(node.lineno) + " 行）"
        checked += 1
        if h_new and h_new.strip():
            with_new += 1
        if seen_keys is not None:
            seen_keys.add((script.name, h_label))
        h_text = texts.get(h_target)
        if h_text is None:
            h_text = texts[h_target] = h_target.read_text(encoding="utf-8", errors="replace")
        h_hits = count_in(h_text, h_old)
        if h_hits >= 1:
            # 唯一性：**只有自己断言了唯一**的助手才要求恰好一次（见 strict_helper_names）。
            # ⛔ 不能按整份脚本判严格：同一个 Sandbox 里的 sub() 是故意的「全换」语义。
            if name in strict and h_hits != 1:
                where = "、".join(
                    str(i)
                    for i, ln in enumerate(h_text.replace("\r\n", "\n").splitlines(), 1)
                    if h_old in ln
                )
                if (script.name, h_label) not in ALLOW:
                    problems.append((
                        h_label,
                        h_target,
                        [
                            "这段原文出现 " + str(h_hits) + " 次"
                            + ("（第 " + where + " 行）" if where else "")
                            + "，而 " + name + "() 要求它唯一 —— 它会在调用点直接抛错/断言，把**整份脚本"
                            "打断**（后面的用例一条都不跑，报告里只留一句「非零退出」）。"
                            "单行锚点要带上紧邻的上下文行，或改用 sub() 的「全换」语义。",
                        ],
                    ))
            continue
        h_kind, h_why = judge_missing(script, h_label, h_target, h_text, h_old, h_new, uses_regex)
        if h_kind == "leftover":
            leftovers.append(h_why)  # type: ignore[arg-type]
            continue
        if h_kind in ("ok", "moved"):
            continue
        if (script.name, h_label) not in ALLOW:
            problems.append((h_label, h_target, [str(h_why)]))

    return problems, checked, leftovers, with_new


def case_table_len(path: Path) -> int | None:
    """脚本里那张「破坏方式」表的条数（`INJECTIONS` / `CASES` 列表的元素个数）。

    ⚠️ 为什么不数源码里的 `^    ("`：表有 4 元组 / 5 元组 / 多行 / 跨行拼接几种写法，
    文本计数会漏；而 AST 数 `len(elts)` 与脚本自己打印的那个分母是同一个数。
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names, value = [node.target.id], node.value
        else:
            continue
        if not any(n in CASE_TABLES for n in names):
            continue
        if isinstance(value, (ast.List, ast.Tuple)):
            return len(value.elts)
    return None


def iter_claims() -> list[tuple[Path, int, Path, int, tuple[int, int] | None]]:
    """扫 `_check_*.py` 里「配套：…（N 种破坏方式）」的声明。

    返回 (声明所在的脚本, 行号, 配套的反向验证脚本, 声明的 N, 写了 `a/b` 就一并给出)。
    """
    out: list[tuple[Path, int, Path, int, tuple[int, int] | None]] = []
    for g in CHECK_GLOBS:
        for path in sorted(REPO.glob(g)):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                m = RE_CLAIM.search(line)
                if not m:
                    continue
                fm = RE_CLAIM_FRAC.search(line)
                frac = (int(fm.group(1)), int(fm.group(2))) if fm else None
                out.append((path, i, REPO / Path(m.group(1)), int(m.group(2)), frac))
    return out


def preview(s: str, n: int = 60) -> str:
    one = " ".join(s.split())
    return one[:n] + ("…" if len(one) > n else "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="（兼容 _check_all 的调用约定；失败一律非零退出）")
    ap.add_argument("--verbose", action="store_true", help="逐份列出核对了多少条原文")
    ap.add_argument(
        "--restore",
        action="store_true",
        help="把「注入残留」按注入串换回原文（只动恰好出现一次的；改前按字节备份到 %%TEMP%%）",
    )
    args = ap.parse_args()

    scripts = iter_scripts()
    total = 0
    n_scripts_with_table = 0
    all_problems: list[tuple[Path, str, Path, list[str]]] = []
    all_leftovers: list[Leftover] = []
    per: list[tuple[Path, int, int]] = []
    seen_keys: set[tuple[str, str]] = set()
    with_new = 0
    for s in scripts:
        problems, n, leftovers, wn = audit_script(s, seen_keys)
        total += n
        with_new += wn
        if n:
            n_scripts_with_table += 1
        per.append((s, n, len(problems) + len(leftovers)))
        for label, target, why in problems:
            all_problems.append((s, label, target, why))
        all_leftovers.extend(leftovers)

    print(f"扫到 {len(scripts)} 份反向验证脚本（自己算），核对了 {total} 条注入原文"
          f"（其中 {with_new} 条同时拿得到「替换成」那一格，用来判注入残留）。")
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
    if with_new < MIN_WITH_NEW:
        print(
            f"❌ 只有 {with_new} 条锚点拿得到「替换成」那一格（少于 {MIN_WITH_NEW}）："
            "**注入残留这一半判据等于没在跑**（它靠替换串认人）。先修抽取，再信这条检查。"
        )
        fail = True
    if n_scripts_with_table < MIN_SCRIPTS_WITH_TABLE:
        print(
            f"❌ 只有 {n_scripts_with_table} 份脚本的注入表认得出（少于 {MIN_SCRIPTS_WITH_TABLE}）："
            "抽不出来的那几份**一条都不会被查**，而报告里显示的是「0 条」—— 看起来正常，"
            "所以必须由这条下限来喊。2026-10-03 加：`_reverse_verify_r4_all.py` 就是这样藏了一条"
            "腐烂的锚点，直到全量反向验证被它**整份打断**才暴露。两种形状都要认："
            "5 元组 `(说明, 路径, 原文, 替换成, 期望)`，以及 `sb.replace(路径, 原文, 替换成)` 这类注入助手调用。"
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

    # 「配套说明书」里的条数（2026-10-04 · CHG-0021）：`_check_*.py` 常写
    # 「配套：python <rv>.py（N 种破坏方式全被抓）」—— 这个 N **原来没有任何判据在管**，
    # 实测 8 处里 6 处是错的（最离谱的一处写 8、真实 28）。加注入的人不会回头改这句，
    # 它就这样安静地烂成第二份真相；这里拿「脚本自己那张表的条数」跟它对账。
    claims = iter_claims()
    claim_problems: list[str] = []
    n_checked_claims = 0
    for c_file, c_line, rv_file, claimed, frac in claims:
        rel_c = c_file.relative_to(REPO)
        rel_rv = rv_file.relative_to(REPO) if rv_file.is_relative_to(REPO) else rv_file
        if not rv_file.exists():
            claim_problems.append(f"{rel_c}:{c_line} 指着一份不存在的配套脚本：{rel_rv}")
            continue
        n = case_table_len(rv_file)
        if n is None:
            continue  # 表不是列表字面量（抽不出来）—— 不猜，跳过
        n_checked_claims += 1
        if claimed != n:
            claim_problems.append(
                f"{rel_c}:{c_line} 写着「{claimed} 种破坏方式」，而 {rel_rv} 的表里是 {n} 条"
            )
        if frac is not None and not (frac[0] == frac[1] and 0 <= frac[1] - n <= 1):
            claim_problems.append(
                f"{rel_c}:{c_line} 写着「{frac[0]}/{frac[1]}」，而 {rel_rv} 的表里是 {n} 条"
                "（分母要么等于表长，要么等于表长 +1 —— 有的脚本把「还原复检」也算一种）"
            )
    print(
        f"顺带核对了 {len(claims)} 处「配套：…（N 种破坏方式）」说明书条数"
        f"（{n_checked_claims} 处拿得到对照表）。"
    )
    if n_checked_claims < MIN_CLAIMS:
        print(
            f"❌ 只有 {n_checked_claims} 处说明书条数核对得动（少于 {MIN_CLAIMS}）："
            "抽取失效了，先修这个 —— 别让这一节安静地什么都没查。"
        )
        fail = True
    if claim_problems:
        print(f"\n❌ {len(claim_problems)} 处「配套说明书」的条数与脚本对不上（它是一份会安静过期的第二真相）：")
        for p in claim_problems:
            print(f"  · {p}")
        print("修法：把 `_check_*.py` 模块 docstring 里那个数字改成脚本里真实的表长（**只改数字，不动判据**）。")
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
        print(
            "      ⛔ 说「要求它唯一」的那几条**不是腐烂**，是锚点写得太短（同一段原文在源码里出现了多次）："
            "带上紧邻的上下文行让它唯一，或改用 sub() 的「全换」语义。"
        )
        fail = True

    if all_leftovers:
        # ⚠️ **同一处注入会被多条声明指到**（实测：OrderCreateScreen.kt 那一行电话过滤，
        #    有 3 份反向验证脚本各声明了一条同名注入）—— 按 (目标文件, 注入串, 原文) 去重，
        #    否则第二、三条会去改一处**刚刚已经修好**的地方，报出莫名其妙的"对不上"。
        grouped: dict[tuple[Path, str, str], list[Leftover]] = {}
        for it in all_leftovers:
            grouped.setdefault((it.target, it.new, it.old), []).append(it)
        uniq = [v[0] for v in grouped.values()]
        print(
            f"\n⛔ {len(uniq)} 处**注入残留**（不是锚点腐烂；共 {len(all_leftovers)} 条注入声明指向它们）："
            " 原文找不到，而那条注入的**替换串正躺在目标文件里** ——"
            "这是**上一次反向验证被硬中断**（工具调用被取消 / Ctrl+C / 进程被杀）留下的，"
            "也就是**一个真的 bug 现在就在源码里**。"
        )
        for it in uniq:
            rel = it.target.relative_to(REPO) if it.target.is_relative_to(REPO) else it.target
            n = len(grouped[(it.target, it.new, it.old)])
            print(f"  · {rel}:{it.lineno}" + (f"（{n} 条注入声明指向这里）" if n > 1 else ""))
            print(f"      注入串：{preview(it.new)}")
            print(f"      来自：{it.script.relative_to(REPO)} ｜ 标签：{it.label}")
            print(f"      该处原文应为：{preview(it.old)}")
        print(
            "\n⛔ **不要去改锚点**：照那句「更新锚点」做 = 把注入的 bug 永久钉进源码，"
            "这条反向验证从此恒绿（比锚点腐烂严重得多）。\n"
            "  修法：python _tools/qa/_check_reverse_verify_anchors.py --restore"
        )
        fail = True
        if args.restore and not refuse_if_injecting("锚点检查（--restore）"):
            # ⚠️ 反向验证正在跑时，"替换串在文件里"是**正常的注入状态**，不能当残留还原。
            fixed_ok = 0
            for it in uniq:
                ok, why = restore_leftover(it)
                print(f"  {'✅' if ok else '⛔'} {it.target.name}:{it.lineno} —— {why}")
                fixed_ok += 1 if ok else 0
            if fixed_ok == len(uniq):
                print(
                    f"\n✅ {fixed_ok} 处注入残留已按字节还原，请重跑这条检查确认全绿。"
                    "\n（本次仍以**非零**退出：刚才源码树确实是脏的 —— 修好了不等于没发生过；"
                    "重跑一次变绿才代表可以继续。）"
                )
            else:
                print(f"\n❌ {len(uniq) - fixed_ok} 处没能自动还原（见上面的理由），请人工处理。")
    elif args.restore:
        print("\n（--restore：没有发现注入残留，什么都没改。）")

    if not fail:
        print(f"✅ {total} 条注入原文全部还在（{n_scripts_with_table}/{len(scripts)} 份脚本的注入表都认得出）。")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
