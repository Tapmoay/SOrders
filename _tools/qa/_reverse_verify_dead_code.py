"""反向验证 `_check_dead_code.py`（死代码红线）。

## 为什么这条红线也要反向验证（它自己就咬过一次）
第一版用两个 `re.sub` 去注释，而**行注释里出现的 `/*`** 会和几百行之后的 `*/` 配成一对：
中间一大段真代码被吃掉，于是 `ProductCategoriesScreen` 里明明调用着的 `CategoryRow(`
被报成"没人调用"。**误报会让整条红线变成噪音**（没人再信它），所以这里除了"该红的要红"，
还有三条"**不该红的必须绿**"的负例：

1. 加一个没用的 import → 必须红；
2. 加一个没人调用的 `private fun` → 必须红；
3. 加一个**有人调用**的 `private fun` → 必须绿（证明它不是"见 private 就报"）；
4. 在真实调用前面插一句含 `/*` 的行注释 → 必须绿（证明注释剥离没吃掉代码）；
5. 判据自己的下限被抬到不可能满足 → 必须红（证明"空转自检"是活的）。

用法：python _tools/qa/_reverse_verify_dead_code.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_dead_code.py"
SRC = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
TARGET = SRC / "ui/dispatcher/LedgerHomeScreen.kt"
SELF = CHECK


def append(text: str):
    def apply(src: str) -> str:
        return src + text

    return apply


def sub(old: str, new: str, count: int = 1):
    def apply(src: str) -> str:
        if old not in src:
            raise LookupError(f"替换串过期了：{old[:60]!r}")
        return src.replace(old, new, count)

    return apply


CASES: list[tuple[str, Path, object, bool]] = [
    # (说明, 文件, 注入, 期望是否报红)
    (
        "加一条没被用到的 import（最常见的那一类死代码）",
        TARGET,
        append("\nimport androidx.compose.ui.unit.sp\n"),
        True,
    ),
    (
        "加一个没人调用的私有函数（下一个人会照着抄）",
        TARGET,
        append("\nprivate fun nobodyCallsThis() = Unit\n"),
        True,
    ),
    (
        "加一个**有人调用**的私有函数 → 不该报（它不是「见 private 就报」）",
        TARGET,
        append("\nprivate fun calledRightAway() = Unit\n\nval probeUse = calledRightAway()\n"),
        False,
    ),
    (
        "真实调用前面插一句含 `/*` 的行注释 → 不该报（注释剥离没有吃掉代码）",
        TARGET,
        sub(
            "fun LedgerHomeScreen(",
            "// 顺手一提：这个文件以前有个 /* 忘了闭合的注释\nfun LedgerHomeScreen(",
        ),
        False,
    ),
    (
        "判据自己的文件数下限被抬到不可能满足 → 必须报（空转自检是活的）",
        SELF,
        sub("MIN_FILES = 100", "MIN_FILES = 100000"),
        True,
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    code, out = run_check()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时红线就没过\n{out[-1200:]}")
        return 1
    print("✅ 前提：源码完好时红线是绿的（没有死代码）")

    originals: dict[Path, str] = {}
    fails: list[str] = []
    for label, path, mutate, want_red in CASES:
        if path not in originals:
            originals[path] = path.read_text(encoding="utf-8")
        original = originals[path]
        try:
            mutated = mutate(original)  # type: ignore[operator]
        except LookupError as e:
            fails.append(f"{label}：{e}")
            continue
        if mutated == original:
            fails.append(f"{label}：注入没生效（替换串过期了）")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            code, out = run_check()
        finally:
            path.write_text(original, encoding="utf-8", newline="")
        went_red = code != 0
        if went_red == want_red:
            print(f"✅ 注入「{label}」→ {'报红' if want_red else '保持绿'}（符合预期）")
        else:
            fails.append(
                f"{label}：期望{'报红' if want_red else '保持绿'}，实际{'报红' if went_red else '绿'}"
                f" —— 判据在这一格上是{'空转' if want_red else '误报'}"
            )

    dirty = [p for p, s in originals.items() if p.read_text(encoding="utf-8") != s]
    if dirty:
        fails.append("还原失败：" + "、".join(str(p.relative_to(ROOT)) for p in dirty))
    else:
        print(f"✅ 还原检查：{len(originals)} 个被碰过的文件与运行前逐字节一致")

    if fails:
        print("\n❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ {len(CASES)} 条注入全部符合预期（该红的红、不该红的没红）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
