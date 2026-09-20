"""红线：**`init { }` 调用链里会写到的 Compose 状态，必须声明在 `init` 之前**。

## 为什么要有这一条（它是崩出来的，不是想出来的）
Kotlin 的属性初始化与 `init` 块**按书写顺序**执行。所以

    init { load() }          // ← 先跑
    ...
    var costVisible by mutableStateOf(false)   // ← 后初始化（此刻委托字段还是 null）

会让 `load()` 里那一句 `costVisible = …` 抛
`Attempt to invoke interface method 'void MutableState.setValue(Object)' on a null object reference`
—— **打开「AI 助手 → 设置」必崩**（2026-09-20 真机抓到的）。

同一个坑这个项目踩过**不止一次**：`AiSettingsViewModel` 的注释里已经写着
「必须声明在 `init { load() }` 之前」（`readModules` 那次），后来加的 `costVisible`
又写到了文件后半段 —— 说明**靠注释提醒是靠不住的**，得有机器拦。

## 判据（只抓"真的会被 init 写到"的，不做一刀切）
1. 找出文件里的 `init { … }` 块，取出里面被调用的函数名；
2. **沿着调用链往下跟**（这些函数自己再调用的函数也算，最多 4 层）——收集
   **赋值语句左边的属性名**（`x = …`）；
3. 这些属性里，**声明位置在 `init` 块之后**的 → 报错。

⚠️ 为什么不用"init 之后不许出现任何 `by mutableStateOf`"这种一刀切：
   实测全项目有 6 个文件命中，而其中多数是**无害**的（例如 `showNavPicker`
   只在用户点按钮时才写，init 根本不碰它）——那种红线会立刻变成"永远红"，
   而永远红的检查等于没有检查。所以这里只钉**能被 init 写到**的那一批。

📌 2026-09-20 补的两个盲区（都是**又崩了一次**之后才发现的）：
   · 原来只跟 `foo()` 这种**无参**调用 —— 账本 VM 的 `init { applyPreset(档位) }`
     带实参，判据当场放行，而真机上打开那一页就是必崩；
   · 原来只看 init **直接**调用的那一个函数体 —— 中间隔一层（`init → applyPreset → applyRange`）
     就漏。现在两件都跟（`CALL` 只要求"名字后面有左括号"，并沿链下钻 4 层）。
   反向验证里专门有这两条注入：`_tools/qa/_reverse_verify_vm_init_order.py`。

用法：python _tools/qa/_check_vm_state_before_init.py [--check]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

#: 扫到的 `.kt` 文件数下限（路径写错/正则失效时先喊，而不是安静地什么都不查）
MIN_FILES = 60
#: 至少要能认出这么多"有 init 块的 ViewModel 文件"（否则说明切块逻辑坏了）
MIN_VMS = 8

INIT = re.compile(r"^\s*init\s*\{", re.M)
#: ⚠️ 只要"名字后面有左括号"就算一次调用（**带不带实参都跟**）：
#:   原来写成 `\b(\w+)\s*\(\s*\)`，于是 `applyPreset(档位)` 这种带参数的调用被漏掉，
#:   而账本 VM 正是这么写的 —— 判据放行了，真机上打开那一页必崩（2026-09-20）。
CALL = re.compile(r"\b(\w+)\s*\(")
#: 调用链跟几层（init → f → g → h 够用了；再深说明这个 init 该拆了）
MAX_DEPTH = 4
#: 赋值左边：行首（允许缩进）的裸属性名 + `=`（排除 == / >= / <= / != / +=）
ASSIGN = re.compile(r"^\s{4,}(\w+)\s*=(?!=)", re.M)
#: **类成员**声明：缩进正好 4 个空格（本仓库的 Kotlin 风格：类体 4、函数体 8+）。
#:
#: ⚠️ 2026-09-20 修的一个误报（它把这条红线推到了"永远红"的边缘）：
#:    原来这里允许任意缩进，于是**函数里的局部变量**（`        val q = returnQty[id] ?: 0`）
#:    也被当成"属性声明"。而同一个名字很可能在别处作为**具名实参**出现
#:    （`orders(q = search.trim()…)`，那行恰好也满足 [ASSIGN] 的"行首 4+ 空格 + 名字 + ="）——
#:    两者一配，就报出一个**根本不存在的属性**在 init 之后声明。
#:    判据必须锚"类成员"这个位置，不然任何一个局部变量都可能撞出一次假红。
DECL = re.compile(
    r"^    (?:@\w+\s+)*(?:private\s+|internal\s+|protected\s+)?(?:var|val)\s+(\w+)\b", re.M
)
#: 解析出来的类成员声明数下限（DECL 收紧之后，先确认没有把真属性一起漏掉）
MIN_DECLS = 300


def block_after(src: str, start: int) -> str:
    """从 `{`（start 指向它）开始，按花括号配平取出块内容。"""
    depth = 0
    for i in range(start, len(src)):
        c = src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[start + 1 : i]
    return src[start + 1 :]


def fun_body(src: str, name: str) -> str | None:
    """取本文件里 `fun name(...)` 的函数体（按花括号配平）。"""
    m = re.search(r"^\s*(?:private\s+|internal\s+|override\s+)*fun\s+" + name + r"\s*\(", src, re.M)
    if not m:
        return None
    brace = src.find("{", m.end())
    if brace < 0:
        return None
    return block_after(src, brace)


def writes_reachable(src: str, entry: str, depth: int = MAX_DEPTH, seen: set[str] | None = None) -> set[str]:
    """从 [entry] 这个函数出发，收集它（以及它调用到的本文件函数）里被赋值的属性名。

    只认**本文件里真的存在**的 `fun entry(` —— 所以 `if (` / `when (` / `launch {` 这类
    同形写法会自然落空（找不到对应函数就返回空集），不会造成误报。
    """
    seen = seen if seen is not None else set()
    if entry in seen or depth <= 0:
        return set()
    seen.add(entry)
    body = fun_body(src, entry)
    if body is None:
        return set()
    out = set(ASSIGN.findall(body))
    for nxt in CALL.findall(body):
        out |= writes_reachable(src, nxt, depth - 1, seen)
    return out


def check_file(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8", errors="ignore")
    out: list[str] = []
    for m in INIT.finditer(src):
        brace = src.find("{", m.start())
        body = block_after(src, brace)
        called = {c for c in CALL.findall(body)}
        if not called:
            continue
        written: set[str] = set()
        for fn in called:
            written |= writes_reachable(src, fn)
        if not written:
            continue
        # 声明位置：属性名 → 首次声明处的偏移
        decl_at: dict[str, int] = {}
        for d in DECL.finditer(src):
            decl_at.setdefault(d.group(1), d.start())
        for prop in sorted(written):
            at = decl_at.get(prop)
            if at is not None and at > m.start():
                out.append(f"{prop}（{fn} 里写的）")
    return out


def main() -> int:
    files = sorted(APP.rglob("*.kt"))
    vms = [f for f in files if f.name.endswith("ViewModel.kt") or "ViewModels.kt" in f.name]
    problems: list[tuple[str, list[str]]] = []
    decls = 0
    for f in files:
        decls += len(DECL.findall(f.read_text(encoding="utf-8", errors="ignore")))
        bad = check_file(f)
        if bad:
            problems.append((f.relative_to(APP).as_posix(), sorted(set(bad))))

    print(f"扫到 .kt {len(files)} 个，其中 ViewModel 文件 {len(vms)} 个；类成员声明 {decls} 个")
    print(f"状态声明在 init 之后、且会被 init 调用链写到的：{len(problems)} 个文件")

    fails: list[str] = []
    if len(files) < MIN_FILES:
        fails.append(f"扫到的 .kt 太少（{len(files)} < {MIN_FILES}）：路径或 glob 坏了")
    if len(vms) < MIN_VMS:
        fails.append(f"认出的 ViewModel 文件太少（{len(vms)} < {MIN_VMS}）：切块逻辑可能坏了")
    if decls < MIN_DECLS:
        fails.append(
            f"解析到的类成员声明太少（{decls} < {MIN_DECLS}）：DECL 的缩进判据可能把真属性漏掉了"
        )
    for name, props in problems:
        fails.append(f"{name}：{'、'.join(props)} 声明在 init 之后 → 打开这一页会 NPE")
        print(f"  ❌ {name}: {'、'.join(props)}")

    if fails:
        print("\n❌ 不通过：")
        for x in fails:
            print("   - " + x)
        print(
            "\n修法：把这些状态**移到 `init { }` 之前**（与同类状态放一起），"
            "不要在 init 里少写一行 —— 那是「打开就崩」，而崩掉的是整页。"
        )
        return 1
    print("✅ 没有「init 会写到、却声明在它之后」的状态。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
