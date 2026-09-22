"""红线：**死代码**（没被用到的 import / 没被调用的私有声明）。

## 为什么值得一条常驻检查
用户 2026-09-20：「程序非常卡，清理像死代码和无用的逻辑」。
死代码的代价不是"多几行"，而是**它会被人当成活的**：
- 一个没人调用的 `private fun` 会被下一个人照着抄（本项目刚删掉的
  `AccountEntryLines` 就是"改两层账本之后永远走不到"的那一类）；
- 一条没人导航得到的路由会让人以为功能还在；
- 没用的 import 会让"这个文件负责什么"变得模糊（读代码的人要逐个确认它是不是还在用）。

## 两条判据（都只看**同一文件**内的用法，跨文件引用不参与）
1. **显式 import**：简单名必须在文件正文里出现一次以上
   （`import a.b.*` 通配不查；[IMPLICIT] 那几个是**委托/运算符**必需的，编译器按语法用它们）；
2. **private 声明**（`private fun/val/var/class/object`）：名字在本文件里至少出现两次
   （一次是声明）。⛔ 只查 `private`：`internal` 的可能是给同 module 别的文件用的，
   拿本文件计数会误报（第一版就是这么误报了十几个）。

## 反空转
- 扫到的文件数、解析出的 import 数、private 声明数都有下限；
- 反向验证 `_reverse_verify_dead_code.py` 注入"加一个没用的 import / 加一个没人调的私有函数"
  必须报红，并且证明 [IMPLICIT] 白名单里的名字加进来**不会**被误报。

用法：python _tools/qa/_check_dead_code.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

#: 这些 import **不是**"名字出现在正文里"才算用：编译器按语法用（委托 `by`、运算符重载、
#: 解构、`invoke`）。写进去是为了不让判据误报 —— 每一条都要有"为什么"。
IMPLICIT = {
    "getValue", "setValue", "provideDelegate",       # `var x by ...` 的三个操作符
    "component1", "component2", "component3", "component4", "component5",  # 解构
    "invoke", "plus", "minus", "times", "div", "rem", "unaryMinus", "compareTo",
    "contains", "get", "set", "rangeTo", "iterator",
}

#: ⚠️ **看起来没用、但删了编译不过**的 import —— 逐条写清理由，**按文件**登记
#: （⛔ 不做全局豁免：那会把别处真正没用的同名 import 一起盖住）。
#:
#: 2026-09-22 实测（两次构建对照）：`ui/dispatcher/AccountManageScreen.kt` 删掉
#: `androidx.compose.foundation.clickable` 之后，同一文件里
#: `Modifier.combinedClickable(...)` 那一行**当场编译不过**：
#: `e: … AccountManageScreen.kt:270:37 Unresolved reference 'clickable'`；
#: 加回去 → `BUILD SUCCESSFUL`。那个文件里**一处 `.clickable(` 调用都没有** ——
#: 也就是说 `combinedClickable` 的重载解析需要 `clickable` 留在作用域里，
#: 而这条判据"简单名必须在正文里出现"看不出这件事（典型的假阳性）。
NEEDED_DESPITE_UNUSED: dict[str, set[str]] = {
    "ui/dispatcher/AccountManageScreen.kt": {"androidx.compose.foundation.clickable"},
}

#: 扫到的规模下限（路径写错/解析失效时先喊，而不是安静地什么都查不到）
MIN_FILES = 100
MIN_IMPORTS = 800
MIN_PRIVATE = 200

IMPORT = re.compile(r"^import\s+([\w.]+)(\.\*)?\s*$", re.M)
#: ⚠️ `private fun RowScope.foo(` 这种**扩展函数**：函数名是 `foo`，不是接收者 `RowScope`。
#:    第一版直接取 `fun` 后面第一个标识符，于是把 `RowScope` 当成"没人调用的私有声明"报了出来
#:    （反向验证的"白名单/判据不许误报"那一条正是为这类自咬准备的）。
PRIVATE_FUN = re.compile(r"^\s*private\s+(?:suspend\s+)?fun\s+[^(=]*?([A-Za-z_]\w*)\s*\(", re.M)
PRIVATE_PROP = re.compile(
    r"^\s*private\s+(?:val|var|class|object|data class)\s+([A-Za-z_]\w*)", re.M
)


def strip_comments(src: str) -> str:
    """去掉注释（**保住行号**、**不碰字符串里的内容**）。

    ⛔ 为什么不能图省事写成两行 `re.sub`（第一版就是，然后它自己骗了自己）：
       先按 `/*…*/` 非贪婪替换时，**行注释里出现的 `/*`** 会和几百行之后的 `*/` 配成一对，
       中间那一大段**真代码**被整段吃掉 —— 于是 `ProductCategoriesScreen` 里明明调用着的
       `CategoryRow(` 被报成"没人调用"，而这类误报会让整条红线变成噪音（没人再信它）。
       这里用一个小状态机：注释内容丢掉，字符串原样保留，换行照抄（行号不漂）。
    """
    out: list[str] = []
    i, n = 0, len(src)
    state: str | None = None  # None / '"' / "'" / '"""' / '//' / '/*'
    while i < n:
        c = src[i]
        three = src[i : i + 3]
        two = src[i : i + 2]
        if state is None:
            if three == '"""':
                state, i = '"""', i + 3
                out.append(three)
                continue
            if two == "//":
                state, i = "//", i + 2
                continue
            if two == "/*":
                state, i = "/*", i + 2
                continue
            if c in "\"'":
                state = c
            out.append(c)
            i += 1
            continue
        if state == "//":
            if c == "\n":
                state = None
                out.append(c)
            i += 1
            continue
        if state == "/*":
            if two == "*/":
                state, i = None, i + 2
                continue
            if c == "\n":
                out.append(c)  # 保行号
            i += 1
            continue
        if state == '"""':
            if three == '"""':
                state, i = None, i + 3
                out.append(three)
                continue
            out.append(c)
            i += 1
            continue
        # 单行字符串
        if c == "\\":
            out.append(src[i : i + 2])
            i += 2
            continue
        if c == state:
            state = None
        out.append(c)
        i += 1
    return "".join(out)


def check_file(p: Path) -> list[str]:
    raw = p.read_text(encoding="utf-8", errors="ignore")
    code = strip_comments(raw)
    body = "\n".join(l for l in code.split("\n") if not l.startswith("import "))
    out: list[str] = []

    for m in IMPORT.finditer(code):
        if m.group(2):          # `import a.b.*` 通配：不查（查不出"用了哪个"）
            continue
        full = m.group(1)
        name = full.split(".")[-1]
        if name in IMPLICIT:
            continue
        if full in NEEDED_DESPITE_UNUSED.get(p.relative_to(SRC).as_posix(), set()):
            continue
        if not re.search(r"\b" + re.escape(name) + r"\b", body):
            out.append(f"没被用到的 import：{full}")

    for m in list(PRIVATE_FUN.finditer(code)) + list(PRIVATE_PROP.finditer(code)):
        name = m.group(1)
        if len(re.findall(r"\b" + re.escape(name) + r"\b", code)) <= 1:
            line = code[: m.start()].count("\n") + 1
            out.append(f"没人调用的私有声明（{p.name}:{line}）：{name}")

    return out


def main() -> int:
    files = sorted(SRC.rglob("*.kt"))
    if len(files) < MIN_FILES:
        print(f"❌ 只扫到 {len(files)} 个 .kt（<{MIN_FILES}）：路径或 glob 坏了，停。")
        return 1

    problems: list[tuple[str, list[str]]] = []
    n_imports = 0
    n_private = 0
    for p in files:
        code = strip_comments(p.read_text(encoding="utf-8", errors="ignore"))
        n_imports += len([m for m in IMPORT.finditer(code) if not m.group(2)])
        n_private += len(PRIVATE_FUN.findall(code)) + len(PRIVATE_PROP.findall(code))
        bad = check_file(p)
        if bad:
            problems.append((p.relative_to(SRC).as_posix(), bad))

    print(f"扫到 .kt {len(files)} 个；显式 import {n_imports} 条；private 声明 {n_private} 处")
    fails: list[str] = []
    if n_imports < MIN_IMPORTS:
        fails.append(f"解析到的 import 太少（{n_imports} < {MIN_IMPORTS}）：IMPORT 正则可能失效")
    if n_private < MIN_PRIVATE:
        fails.append(f"解析到的 private 声明太少（{n_private} < {MIN_PRIVATE}）：PRIVATE_DECL 可能失效")

    total = 0
    for name, items in problems:
        total += len(items)
        print(f"  ❌ {name}")
        for it in items:
            print(f"       · {it}")
    if total:
        fails.append(f"{total} 处死代码（没用的 import / 没人调用的私有声明）—— 删掉或接上")

    print("\n" + "=" * 60)
    if fails:
        print(f"❌ {len(fails)} 项不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ 没有死代码：{n_imports} 条 import 与 {n_private} 处私有声明都在用。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
