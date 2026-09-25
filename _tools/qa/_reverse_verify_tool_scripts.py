#!/usr/bin/env python3
"""反向验证 `_tools/qa/_check_tool_scripts.py` 的两条判据都真的有牙。

## 六种破坏（前五种必须当场红，第六种必须**保持绿**）
| # | 注入 | 期望 |
| --- | --- | --- |
| ① | 把一个工具的根目录改回**写死的检出路径** | 红：「写死了本仓库的检出目录」 |
| ② | 换**另一个**工具、换一种写法重复 ① | 红：同上（证明判据不是只锚了一个文件） |
| ③ | 写死**别人家目录**（`C:/Users/<名字>/...`） | 红：「写死了别人家目录」 |
| ④ | 把一个工具改成**语法错**（括号不闭合） | 红：「解析不了」 |
| ⑤ | 把扫描下限调到不可能的数 | 红：「判据可能扫错目录」（反空转下限本身要有效） |
| ⑥ | **只在注释里**写死路径（反面教材） | ⛔ **必须保持绿** |

⑥ 是这一份里最要紧的一条：它证明判据读的是 **AST 里的字符串常量**，而不是整份文本 ——
否则「⛔ 不许写死 `D:/...`」这种劝告本身就会把检查判红，而那正是仓库里到处都是的写法。

⚠️ 与仓库里其它 `_reverse_verify_*.py` 同一套纪律：按**字节**备份/还原、跑完逐文件核对、
⛔ 全程不碰 `git checkout --`。

用法：python _tools/qa/_reverse_verify_tool_scripts.py
      python _tools/qa/_reverse_verify_tool_scripts.py --list
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_tool_scripts.py"

#: 「必须保持绿」的哨兵值（只有 ⑥ 用）。
KEEP_GREEN = "<保持绿>"

# ⛔ 这些"坏写法"必须**拼出来**，不能在源码里出现字面路径 —— 两个理由：
#    ① 字面写 `D:\AProjects...` 会触发 Python 的转义警告（\A / \U 不是合法转义）；
#    ② 更要紧的是：**本文件自己就在 `_tools/` 里**，写一个字面路径就会被 `_check_tool_scripts.py`
#       当场判红（实测抓到过一次）。判据是对的 —— 夹具是"要被注入的文本"，不是"本工具依赖的路径"，
#       所以它必须是拼出来的，而不是躺在源码里的常量。
BS = chr(92)


def _win(*parts: str) -> str:
    """把 Windows 路径的分段用反斜杠接起来（**不在源码里出现字面路径**）。"""
    return BS.join(parts)


BAD_ROOT = 'ROOT = Path(r"' + _win("D:", "AProjects", "ASDH", "orders") + '")'
REAL_ROOT = "ROOT = Path(__file__).resolve().parents[2]"
BAD_BAK = ('BAK = Path(r"'
           + _win("C:", "Users", "Optimistic", "AppData", "Local", "Temp", "_noth_backup.kt") + '")')
ADB_LINE = 'ADB = r"' + _win("D:", "APPS", "sdk", "platform-tools", "adb.exe") + '"'
ADB_OPEN = 'ADB = (r"' + _win("D:", "APPS", "sdk", "platform-tools", "adb.exe") + '"'

CASES: list[tuple[str, str, str, str, str]] = [
    (
        "① 根目录改回写死的检出路径（原始缺陷的形状）",
        "_tools/ai/_verify_ast.py",
        "ROOT = repo_root()   # ⛔ 不许写死本机路径：CI 在 /home/runner/... 上跑，写死 = 那个检查在外面永远不生效",
        BAD_ROOT,
        "写死了本仓库的检出目录",
    ),
    (
        "② 另一个工具、另一种写法（`Path(__file__).parents[2]` → 写死）",
        "_tools/qa/_reverse_verify_loop_e2e.py",
        REAL_ROOT,
        BAD_ROOT,
        "写死了本仓库的检出目录",
    ),
    (
        "③ 写死别人家目录（备份文件落到某一个人的 Temp）",
        "_tools/ai/_reverse_verify_multi_request.py",
        'BAK = Path(tempfile.gettempdir()) / "_noth_backup.kt"',
        BAD_BAK,
        "写死了别人家目录",
    ),
    (
        "④ 工具改成语法错（括号不闭合）—— 这种坏法整个工具跑不起来",
        "_tools/qa/_screensize.py",
        ADB_LINE,
        ADB_OPEN,
        "解析不了",
    ),
    (
        "⑤ 扫描下限调到不可能的数（反空转下限自己有没有牙）",
        "_tools/qa/_check_tool_scripts.py",
        "MIN_FILES = 200",
        "MIN_FILES = 999999",
        "扫错目录",
    ),
    (
        "⑥ **只在注释里**写死路径（反面教材）—— 判据必须保持绿",
        "_tools/qa/_screensize.py",
        ADB_LINE,
        '# ⛔ 反面教材：这里曾经写死过 ' + BAD_ROOT + " + chr(10) + " + ADB_LINE,
        KEEP_GREEN,
    ),
]

CRLF = chr(13) + chr(10)


class Sandbox:
    """按**字节**记账的注入沙箱：每次注入前先还原上一轮，跑完再逐字节核对。"""

    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}

    def apply(self, rel: str, old: str, new: str) -> None:
        p = ROOT / rel
        if not p.exists():
            raise ValueError("找不到 " + rel)
        self.saved.setdefault(p, p.read_bytes())
        raw = p.read_bytes()
        crlf = CRLF.encode("utf-8") in raw
        text = raw.decode("utf-8")
        if old not in text:
            # 第二轮 R2-05：报表源码搬进了 `services/reports/` —— **锚点跟着搬家走**。
            # 判据读的是「并集」（`_airepo.reports_source`），注入器也必须打在那份含原文的文件上，
            # 否则沙箱找不到原文 → [SKIP] → 而 SKIP 在本仓库是**计为不成立**的。
            # ⛔ 不逐条改锚点、也不改目标路径：以后报表再搬一次，这里自动跟上。
            import sys as _sys
            from pathlib import Path as _P
            _sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "ai"))
            from _airepo import reports_files as _rf
            for _c in _rf():
                _t = _c.read_text(encoding="utf-8", errors="replace")
                if _t.count(old) == 1:
                    p = _c
                    raw = p.read_bytes()
                    text = raw.decode("utf-8")
                    if CRLF.encode("utf-8") in raw:
                        text = text.replace(CRLF, chr(10))
                    self.saved.setdefault(p, raw)
                    break
        if crlf:
            text = text.replace(CRLF, chr(10))
        if text.count(old) != 1:
            raise ValueError(rel + " 里锚点出现 " + str(text.count(old)) + " 次（要恰好一次）")
        text = text.replace(old, new, 1)
        p.write_bytes((text.replace(chr(10), CRLF) if crlf else text).encode("utf-8"))

    def restore(self) -> None:
        for p, raw in self.saved.items():
            p.write_bytes(raw)

    def dirty(self) -> list[str]:
        return [str(p.relative_to(ROOT)) for p, raw in self.saved.items() if p.read_bytes() != raw]


def run_check() -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(CHECK), "--check"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(ROOT))
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, (name, rel, _o, _n, want) in enumerate(CASES, 1):
            print(f"{i}. {name}\n      {rel}   ← 期望：{want}")
        return 0

    bad = 0
    sb = Sandbox()
    lock_reverse_verify()
    try:
        code, out = run_check()
        if code != 0:
            print("❌ 前提不成立：源码完好时这条红线就没过")
            print(out[-1500:])
            return 1
        last = [ln for ln in out.splitlines() if ln.strip()][-1]
        print("✅ 前提：源码完好时红线是绿的 —— " + last.strip())
        for label, rel, old, new, want in CASES:
            sb.restore()
            try:
                sb.apply(rel, old, new)
                code, out = run_check()
            except ValueError as exc:
                print("  [SKIP] " + label + " —— " + str(exc))
                bad += 1
                continue
            finally:
                sb.restore()
            if want == KEEP_GREEN:
                if code == 0:
                    print("  [OK] " + label + " → 红线**保持绿**（判据读的是 AST，不是整份文本）")
                else:
                    bad += 1
                    print("  [MISS] " + label + " → 判成了红：注释里的反面教材不该让检查红")
                    for ln in [x.strip() for x in out.splitlines() if x.strip().startswith(("❌", "⛔"))][:5]:
                        print("       检查实际报的：" + ln)
                continue
            hit = code != 0 and want in out
            if hit:
                print("  [OK] " + label + " → 红线报红并命中「" + want + "」")
            else:
                bad += 1
                why = "红线居然还是绿的" if code == 0 else "退出了，但没报出「" + want + "」"
                print("  [MISS] " + label + " → " + why)
                for ln in [x.strip() for x in out.splitlines() if x.strip().startswith(("❌", "⛔"))][:5]:
                    print("       检查实际报的：" + ln)
        sb.restore()
        code, out = run_check()
        ok = code == 0
        print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
        bad += 0 if ok else 1
    finally:
        sb.restore()
        unlock_reverse_verify()

    dirty = sb.dirty()
    if dirty:
        bad += 1
        print("⛔ 跑完没逐字节还原：" + "、".join(dirty))
    total = len(CASES) + 1
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立")
        return 1
    print(f"✅ {total}/{total} 全部成立：写死路径 / 语法错 / 空转下限都会红，注释里的反面教材不会")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())