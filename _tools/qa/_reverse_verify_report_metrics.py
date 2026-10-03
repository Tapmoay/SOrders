# -*- coding: utf-8 -*-
"""反向验证「报表 / 账本口径」这条红线**真的会红**（CHG-0026 / P20·P25·P26·P32）。

## 为什么这条要反向验证
它的判据大多是「某个老标签必须 0 处 / 某句话必须挂在 Text( 上 / 某个分支必须排在前面」，
这类判据有三种典型失效方式，每一种都单独证明一次会红：

1. **判据变成空转**：新标签被改回老标签、分母被换回同一个、零件被改名之后，
   判据必须报红（老标签那一条**0 处也红**，不只是"新标签在不在"）。
2. **顺序型判据最容易假绿**：退货那一支只要排到 remaining > 0L 后面，
   退货单就永远不会命中它 —— 文案还在文件里，扫"有没有这句话"照样绿。
3. **常显与可藏分不清**：口径句只要落回 Hint（提示开关默认关着），
   页面上就一个字都没有 —— 而"这句话在不在源码里"永远是绿的。

另外几条打的是"抄一份"与判据自己：两个分母被写成一个、方向括号被去掉、
分类器的复核表被删掉，以及**判据自己的 REVERSE 常量被改名**（自指用例）。

⚠️ 快照 / 还原按**字节**做，跑完逐字节核对（本项目栽过"注入把 bug 留在源码里"）。

用法：python _tools/qa/_reverse_verify_report_metrics.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_report_metrics.py"
CHECK_REL = "_tools/qa/_check_report_metrics.py"

#: Windows 上 Kotlin 文件可能是 CRLF：按字节快照、归一后再替换、写回时按原样还原
#: （⛔ 不要写反斜杠转义，用字节常量拼；本项目在这个坑上栽过两次）
CR = bytes((13,))
LF = bytes((10,))
CRLF = CR + LF

REPORT = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt"
LEDGER = "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/ShipperLedgerScreen.kt"
HINTS_REL = "_tools/qa/_hint_inventory.py"

#: (说明, 相对路径, 替换函数, 期望在输出里出现的关键词 —— 空串 = 只要非零退出)
CASES: list[tuple[str, str, object, str]] = [
    (
        "① 报表中心：待处理异常又缩回一句合并标签（30 天窗口与本期挤回同一张卡）",
        REPORT,
        lambda s: s.replace(
            'StatRow("近 30 天（与本页时间无关）"',
            'StatRow("待处理异常（近 30 天）"',
            1,
        ),
        "老的合并标签",
    ),
    (
        "② 报表中心：户均订货额被改回「客单价」（分母是客户数，读作每单均价）",
        REPORT,
        lambda s: s.replace('StatRow("户均订货额"', 'StatRow("客单价"', 1),
        "客单价",
    ),
    (
        "③ 报表中心：两行的分母写成同一个（又变成同一个数算两遍）",
        REPORT,
        lambda s: s.replace(
            "money((totalAmount / totalCount).toString())",
            "money((totalAmount / all.size).toString())",
            1,
        ),
        "分母",
    ),
    (
        "④ 报表中心：待处理异常不再挂在自己的小节卡里（塞回本期卡那一堆数字中间）",
        REPORT,
        lambda s: s.replace(
            """                SectionCard {
                    Text("待处理异常""",
            """                Box {
                    Text("待处理异常""",
            1,
        ),
        "小节卡",
    ),
    (
        "⑤ 我的账本：方向括号被去掉（两个数一样大时又看不出谁欠谁）",
        LEDGER,
        lambda s: s.replace('"支出 · 我该付的（欠公司）"', '"支出 · 我该付的"', 1),
        "裸标签",
    ),
    (
        "⑥ 我的账本：口径句落回 Hint（提示开关默认关着 → 页面上一个字都没有）",
        LEDGER,
        lambda s: s.replace(
            """Text(
                "同一批货的两头""",
            """Hint(
                "同一批货的两头""",
            1,
        ),
        "常显",
    ),
    (
        "⑦ 我的账本：退货那一支排到 remaining > 0L 后面（永远不会命中退货单）",
        LEDGER,
        lambda s: s.replace(
            """                        o.status == "RETURNED" -> "已退货 · 账已冲平"
                        remaining > 0L -> "未核销 ¥" + formatMoney(centsToMoney(remaining))
""",
            """                        remaining > 0L -> "未核销 ¥" + formatMoney(centsToMoney(remaining))
                        o.status == "RETURNED" -> "已退货 · 账已冲平"
""",
            1,
        ),
        "之前",
    ),
    (
        "⑧ 我的账本：退货那一支被删掉（回到 remaining == 0 就写已核销）",
        LEDGER,
        lambda s: s.replace(
            """                    when {
                        o.status == "RETURNED" -> "已退货 · 账已冲平"
                        remaining > 0L -> "未核销 ¥" + formatMoney(centsToMoney(remaining))
                        else -> "已核销"
                    },""",
            """                    if (remaining > 0) "未核销 ¥" + formatMoney(centsToMoney(remaining)) else "已核销",
""",
            1,
        ),
        "两选一",
    ),
    (
        "⑨ 分类器的复核表被删掉（那句口径说明下次重生成会被算成可藏的解释句）",
        HINTS_REL,
        lambda s: s.replace('"同一批货的两头"', '"GONE-P25"', 1),
        "分类器复核表",
    ),
    (
        "⑩ 判据自己的 REVERSE 常量被改名（防它指向一个不存在的脚本还照样绿）",
        CHECK_REL,
        lambda s: s.replace(
            'REVERSE = "_tools/qa/_reverse_verify_report_metrics.py"',
            'REVERSE = "_tools/qa/_reverse_verify_report_metrics_gone.py"',
            1,
        ),
        "反向验证",
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时红线是绿的（判据自己 23 项 / 口径齐全）")

    touched = sorted({rel for _l, rel, _m, _e in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}

    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        crlf = CRLF in original_bytes
        plain = original_bytes.decode("utf-8").replace(CRLF.decode(), LF.decode())
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            out_txt = mutated
            if crlf:
                out_txt = out_txt.replace(LF.decode(), CRLF.decode())
            path.write_bytes(out_txt.encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        hit = code != 0 and (not expect or expect in out)
        if hit:
            print(f"  [OK] {label} → 报红")
        else:
            fails.append(f"{label}：注入之后没有按预期报红（退出码 {code}，期望关键词「{expect}」）")
            print(f"  [MISS] {label} → 仍然全绿")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
