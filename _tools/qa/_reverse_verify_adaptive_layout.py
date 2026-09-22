"""反向验证：`_tools/qa/_check_adaptive_layout.py` 那些判据**真的抓得住**吗（2026-09-22）。

手法与仓库里其它 `_reverse_verify_*.py` 同一套：**按字节备份 → 注入 → 跑红线（期望非零退出且命中
指定判据）→ 按字节还原 → 校验 sha256**。⛔ 全程不碰 `git checkout --`（那会在真有改动时抹掉工作）。

遵守注入锁的规矩（`_tools/ai/_airepo.py`）：
· `lock_reverse_verify` —— 上锁期间并发的**检查**会拒绝出结论（源码故意脏着，结论不可信）；
· `refuse_if_injecting` —— 别人的反向验证正在跑时，本脚本也拒绝开跑。

⚠️ 每个注入点都选在**"看起来更省事"的那条路**上 —— 也就是下一个人（或下一个 AI）最可能真去走的那条：
   ① 把共用规则改个名/搬走；② 给档位条加截断兜底；③ 干脆去掉滑动退路；④ 滑动支上也挂 weight；
   ⑤ 单号宽度改成"猜一个常数"；⑥ 单号行退回"永远一行 + 省略号"；
   ⑦ 开销卡又去掉 weight；⑧ 徽章内边距改了却忘了改常数；
   ⑨⑩ 悄悄按屏宽缩放 / 让入口网格在窄屏掉到 1 列。

用法：
    python _tools/qa/_reverse_verify_adaptive_layout.py          # 全部跑
    python _tools/qa/_reverse_verify_adaptive_layout.py --list   # 只列注入点
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import (  # noqa: E402
    lock_reverse_verify,
    refuse_if_injecting,
    unlock_reverse_verify,
)

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_adaptive_layout.py"
UI = "android/app/src/main/java/com/tapmoay/sorders/ui/"
ADAPTIVE = UI + "common/Adaptive.kt"
TABS = UI + "common/SegmentedStatusTabs.kt"
CARD = UI + "common/OrderCard.kt"
COMPONENTS = UI + "common/Components.kt"
ENTRY_GRID = UI + "common/EntryGrid.kt"
EXPENSES = UI + "dispatcher/ExpensesScreen.kt"

#: (说明, 文件, 原文, 替换成, 期望出现在失败清单里的关键字)
INJECTIONS: list[tuple[str, str, str, str, str]] = [
    (
        "① 把共用规则改名（「只有一个地方量宽度」这件事就不成立了）",
        ADAPTIVE,
        "fun rememberTextWidth(text: String, style: TextStyle): Dp {",
        "fun measureWidthSomewhereElse(text: String, style: TextStyle): Dp {",
        "Adaptive.kt 导出 `rememberTextWidth`",
    ),
    (
        "② 给档位标签加「截断兜底」（省事，但「已接单」会变成「已接…」）",
        TABS,
        "                maxLines = 1,\n",
        "                maxLines = 1,\n                overflow = TextOverflow.Ellipsis,\n",
        "⛔ 标签里没有 `TextOverflow.Ellipsis`",
    ),
    (
        "③ 去掉滑动退路（放不下时又回到「被剪掉」，连提示都没有）",
        TABS,
        "            modifier = if (fits) Modifier.fillMaxWidth()\n"
        "            else Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),\n",
        "            modifier = Modifier.fillMaxWidth(),\n",
        "有 `horizontalScroll`（放不下时的退路）",
    ),
    (
        "④ 滑动支上也挂 weight（与无限宽约束打架，滑动会静默失效）",
        TABS,
        "                    modifier = if (fits) Modifier.weight(1f) else Modifier,\n",
        "                    modifier = Modifier.weight(1f),\n",
        "`weight` 只挂在「放得下」那一支",
    ),
    (
        "④b 等宽那一支也给文字加内边距（我在 411dp 上真踩过：六个档位全被切掉最后一个字）",
        TABS,
        "                    pad = if (fits) 0.dp else TAB_H_PADDING,\n",
        "                    pad = TAB_H_PADDING,\n",
        "等宽那一支的文字**不加内边距**",
    ),
    (
        "⑤ 单号宽度改成猜一个常数（换个系统字号就算错）",
        CARD,
        "                    rememberTextWidth(orderNumber, numberStyle) + orderStatusChipWidth(order.status) <= maxWidth",
        "                    200.dp + orderStatusChipWidth(order.status) <= maxWidth",
        "用 `rememberTextWidth(orderNumber, numberStyle)` 实测单号",
    ),
    (
        "⑥ 单号行退回「永远一行 + 省略号」（21 位单号截断后认不出是哪一单）",
        CARD,
        "                    Column {\n"
        "                        Text(orderNumber, style = numberStyle, color = MaterialTheme.colorScheme.onSurface)\n",
        "                    Column {\n"
        "                        Text(\n"
        "                            orderNumber,\n"
        "                            style = numberStyle,\n"
        "                            maxLines = 1,\n"
        "                            overflow = TextOverflow.Ellipsis,\n"
        "                            color = MaterialTheme.colorScheme.onSurface,\n"
        "                        )\n",
        "⛔ 单号没有 `Ellipsis`",
    ),
    (
        "⑦ 开销卡又去掉 weight（长单号把日期挤成四行，两边都不报错）",
        EXPENSES,
        "                    modifier = Modifier.weight(1f),\n",
        "",
        "没有新增（存量",
    ),
    (
        "⑧ 徽章内边距改了、常数没跟着改（宽度判定从此算错）",
        COMPONENTS,
        "            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),\n",
        "            modifier = Modifier.padding(horizontal = 6.dp, vertical = 4.dp),\n",
        "ORDER_CHIP_CHROME_DP =",
    ),
    (
        "⑨ 悄悄按屏宽缩放（多一处 screenWidthDp —— 从这条缝里溜进来的都是这类）",
        ENTRY_GRID,
        "    val columns = maxOf(2, LocalConfiguration.current.screenWidthDp / 160)\n",
        "    val columns = maxOf(2, LocalConfiguration.current.screenWidthDp / 160)\n"
        "    val probeW = LocalConfiguration.current.screenWidthDp\n",
        "`screenWidthDp` 只用在数格子上",
    ),
    (
        "⑩ 入口网格换成 GridCells.Adaptive（窄屏会掉到 1 列 = 小屏样式变了）",
        ENTRY_GRID,
        "        columns = GridCells.Fixed(columns),\n",
        "        columns = GridCells.Adaptive(150.dp),\n",
        "⛔ 没用 `GridCells.Adaptive`",
    ),
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_check() -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, (name, rel, _o, _n, want) in enumerate(INJECTIONS, 1):
            print(f"{i:>2}. {name}\n      {rel}   ← 期望被「{want}」抓到")
        return 0

    if refuse_if_injecting("自适应布局反向验证"):
        return 1

    print("先确认干净状态下是绿的：", end=" ")
    rc, _ = run_check()
    if rc != 0:
        print("❌ 现在就是红的，先修好再跑反向验证")
        return 1
    print("✅ 绿")

    lock_reverse_verify()
    caught = 0
    problems: list[str] = []
    try:
        for i, (name, rel, old, new, want) in enumerate(INJECTIONS, 1):
            path = ROOT / rel
            if not path.exists():
                problems.append(f"{name}：找不到 {rel}")
                print(f"\n[{i}] {name}\n  ❌ 找不到 {rel}")
                continue
            orig = path.read_bytes()
            orig_sha = sha(path)
            text = orig.decode("utf-8")
            eol = "\r\n" if "\r\n" in text else "\n"
            if eol != "\n":
                old = old.replace("\n", eol)
                new = new.replace("\n", eol)
            pat = old[3:] if old.startswith("re:") else re.escape(old)
            injected, n = re.subn(pat, new, text, count=1)
            if n != 1:
                problems.append(f"{name}：锚点没命中（{rel} 里的 {old[:40]!r}）")
                print(f"\n[{i}] {name}\n  ❌ 锚点没命中，跳过（注入点腐烂了）")
                continue
            inj_bytes = injected.encode("utf-8")
            path.write_bytes(inj_bytes)
            try:
                rc, out = run_check()
            finally:
                now = path.read_bytes()
                if now != inj_bytes:
                    print(f"\n[{i}] {name}\n  🛑 有别的东西改了 {rel} —— **拒绝还原**，请人工处理！")
                    return 2
                path.write_bytes(orig)
            if sha(path) != orig_sha:
                print(f"\n[{i}] {name}\n  🛑 {rel} 还原后哈希对不上，停手")
                return 2

            hit = f"[!!]   {want}" in out
            if rc != 0 and hit:
                caught += 1
                print(f"\n[{i}] {name}\n  ✅ 被抓到（红线非零退出，命中「{want}」）")
            else:
                why = "红线居然还是绿的" if rc == 0 else f"退出了，但输出里没有「[!!]   {want}」"
                problems.append(f"{name}：{why}")
                print(f"\n[{i}] {name}\n  ❌ {why}")
    finally:
        unlock_reverse_verify()

    print("\n" + "=" * 60)
    print(f"{caught}/{len(INJECTIONS)} 种破坏方式被抓住")
    if problems:
        print("❌ 有漏网的：")
        for p in problems:
            print("   -", p)
        return 1
    print("✅ 全部注入都被抓住，且每个文件都按字节还原")
    return 0


if __name__ == "__main__":
    sys.exit(main())
