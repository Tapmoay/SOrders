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
1. 找出文件里的 `init { … }` 块，取出里面被调用的函数名（`load()` / `refresh()` …）；
2. 找出这些函数在本文件里的函数体，收集 **赋值语句左边的属性名**（`x = …`）；
3. 这些属性里，**声明位置在 `init` 块之后**的 → 报错。

⚠️ 为什么不用"init 之后不许出现任何 `by mutableStateOf`"这种一刀切：
   实测全项目有 6 个文件命中，而其中多数是**无害**的（例如 `showNavPicker`
   只在用户点按钮时才写，init 根本不碰它）——那种红线会立刻变成"永远红"，
   而永远红的检查等于没有检查。所以这里只钉**能被 init 写到**的那一批。

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
CALL = re.compile(r"\b(\w+)\s*\(\s*\)")
#: 赋值左边：行首（允许缩进）的裸属性名 + `=`（排除 == / >= / <= / != / +=）
ASSIGN = re.compile(r"^\s{4,}(\w+)\s*=(?!=)", re.M)
DECL = re.compile(r"^\s*(?:@\w+\s+)*(?:private\s+|internal\s+)?(?:var|val)\s+(\w+)\b", re.M)


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
            fb = fun_body(src, fn)
            if fb is None:
                continue
            written |= set(ASSIGN.findall(fb))
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
    for f in files:
        bad = check_file(f)
        if bad:
            problems.append((f.relative_to(APP).as_posix(), sorted(set(bad))))

    print(f"扫到 .kt {len(files)} 个，其中 ViewModel 文件 {len(vms)} 个")
    print(f"状态声明在 init 之后、且会被 init 调用链写到的：{len(problems)} 个文件")

    fails: list[str] = []
    if len(files) < MIN_FILES:
        fails.append(f"扫到的 .kt 太少（{len(files)} < {MIN_FILES}）：路径或 glob 坏了")
    if len(vms) < MIN_VMS:
        fails.append(f"认出的 ViewModel 文件太少（{len(vms)} < {MIN_VMS}）：切块逻辑可能坏了")
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
