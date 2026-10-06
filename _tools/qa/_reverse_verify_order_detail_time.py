"""反向验证 _tools/qa/_check_order_detail_time.py（详情页「创建于」带年份、流转记录不带）。

## 为什么必须做

这一条守的是同一次里**两个相反的要求**，而两个函数的签名完全同形（(String?, ZoneId) -> String）：

- 「创建于」退回不带年份那一档 → 又只剩「09-19 18:09」，正是用户点名的那句；
- pattern 里把 yyyy 去掉 → 函数在、名字对、调用点也对，**只有年份没有出来**；
- 流转记录顺手换成带年份 → 用户明确说了不要；
- 有人「为了统一」改 TimeRow 本体 → 改一处，流转记录全变；
- 详情页自己拼一份带年份的 → 时区换算没了（真机时间错 8 小时）；
- 别的页面（账本 / 退货列表）也顺手用上 → 用户没说的页面被改了。

这六种改法**都能编译、都能跑、界面都「看着正常」**，只有逐行比对源码才看得出来。
所以逐条**注入真缺陷**，每条都必须让判据报红；跑完按字节还原并再验一次绿。

⚠️ 注入锚点优先用 re: 形式（判据文件里的缩进会随风变，写死空格数的锚点迟早腐烂）。

用法：python _tools/qa/_reverse_verify_order_detail_time.py [--list]
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
CHECK = ROOT / "_tools" / "qa" / "_check_order_detail_time.py"
MAIN = "android/app/src/main/java/com/tapmoay/sorders/"
UTIL = MAIN + "util/TimeFmt.kt"
DETAIL = MAIN + "ui/order/OrderDetailScreen.kt"
LEDGER = MAIN + "ui/dispatcher/LedgerPersonScreen.kt"
TEST = "android/app/src/test/java/com/tapmoay/sorders/util/TimeFmtTest.kt"
CHG = "docs/changes/CHG-0066.md"

#: (说明, 文件, 原文（re: 前缀 = 正则锚点）, 替换成, 期望被抓到的判据标签**前缀**)
INJECTIONS: list[tuple[str, str, str, str, str]] = [
    (
        "① 「创建于」退回不带年份那一档（用户点名的那句当场复发）",
        DETAIL,
        chr(34) + "创建于 " + chr(34) + " + formatDateTimeFull(order.createdAt),",
        chr(34) + "创建于 " + chr(34) + " + formatDateTime(order.createdAt),",
        "「创建于」用的是带年份那一档",
    ),
    (
        "② pattern 里的 yyyy 被去掉（函数在、名字对、调用点也对，年份就是没出来）",
        UTIL,
        'DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")',
        'DateTimeFormatter.ofPattern("MM-dd HH:mm")',
        "pattern 就是 yyyy-MM-dd HH:mm",
    ),
    (
        "③ 退货申请的「申请时间」退回不带年份那一档",
        DETAIL,
        chr(34) + "申请时间 " + chr(34) + " + formatDateTimeFull(req.createdAt),",
        chr(34) + "申请时间 " + chr(34) + " + formatDateTime(req.createdAt),",
        "退货申请那两个时刻也带年份",
    ),
    (
        "④ 退货申请的「办理时间」退回不带年份那一档（只改一处也算）",
        DETAIL,
        "val at = formatDateTimeFull(req.handledAt)",
        "val at = formatDateTime(req.handledAt)",
        "退货申请那两个时刻也带年份",
    ),
    (
        "⑤ 流转记录那几条被顺手换成带年份那一档（用户明说不要）",
        DETAIL,
        'TimeRow("下单", order.createdAt)',
        'TimeRow("下单", formatDateTimeFull(order.createdAt))',
        "那一块里没有一处带年份那一档",
    ),
    (
        "⑥ 有人把带年份那一档又抄了一份（两处定义：判据从此只钉住其中一份）",
        UTIL,
        r"re:fun formatDateTimeFull\(",
        'fun formatDateTimeFull(iso: String?, zone: ZoneId = ZoneId.systemDefault()): String = ""' + chr(10) + "fun formatDateTimeFull(",
        "带年份那一档全仓恰一处定义",
    ),
    (
        "⑦ 带 zone 参数被删掉（判据/单测再也没法显式传时区，换台机器就红绿翻转）",
        UTIL,
        "fun formatDateTimeFull(iso: String?, zone: ZoneId = ZoneId.systemDefault()): String {",
        "fun formatDateTimeFull(iso: String?): String {",
        "签名逐字",
    ),
    (
        "⑧ TimeRow 本体改成带年份（一处改完流转记录全变，详情页一处 formatDateTimeFull 都没多）",
        DETAIL,
        "formatDateTime(iso)",
        "formatDateTimeFull(iso)",
        "TimeRow 本体仍走不带年份那一档",
    ),
    (
        "⑨ 单测里带年份那条断言被删（两档并排的那句不在了）",
        TEST,
        'assertEquals("2026-09-19 18:09", formatDateTimeFull("2026-09-19T10:09:36.713251", shanghai))',
        'assertEquals("2026-09-19 18:09", formatDateTime("2026-09-19T10:09:36.713251", shanghai))',
        "单测里并排钉住了两档",
    ),
    (
        "⑩ 别的页面（账本）也顺手用上它（用户没说的页面被改了）",
        LEDGER,
        r"re:package com\.tapmoay\.sorders\.ui\.dispatcher",
        "package com.tapmoay.sorders.ui.dispatcher" + chr(10) + chr(10)
        + "private fun injectedElsewhere(iso: String) = formatDateTimeFull(iso)",
        "调用点清单对得上",
    ),
    (
        "⑪ CHG-0066.md 里的台账编号被改成别的（文档与台账对不上号）",
        CHG,
        "L-45",
        "L-44",
        "CHG-0066.md 写了「L-45」",
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
            print(f"{i:>2}. {name}" + chr(10) + f"      {rel}   ← 期望被「{want}」抓到")
        return 0

    if refuse_if_injecting("订单详情时间反向验证"):
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
            eol = chr(13) + chr(10) if chr(13) + chr(10) in text else chr(10)
            if eol != chr(10):
                old = old.replace(chr(10), eol)
                new = new.replace(chr(10), eol)
            pat = old[3:] if old.startswith("re:") else re.escape(old)
            injected, n = re.subn(pat, new, text, count=1)
            if n != 1:
                problems.append(f"{name}：锚点没命中（{rel} 里的 {old[:50]!r}）")
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

    print(chr(10) + "=" * 60)
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
