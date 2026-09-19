"""反向验证「一个数只有一处算法」这条红线**真的会红**（2026-09-19 第十三轮）。

## 为什么这条特别需要反向验证
它的四条判据都是"**某处不许出现某种写法**"，而这一类判据最容易**看起来在查、其实什么都没查**：
- 扫描规则写错（正则不匹配实际写法）→ 恒绿；
- 剥离注释/文档字符串没做 → 被自己的文档骗红（或反过来，把真代码当注释剥掉）；
- 清单白名单写得太宽 → 整类文件被放行。

所以每条判据都注入一次"把算法拿回来"的破坏，证明它会红。

用法：python _tools/qa/_reverse_verify_single_source.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_single_source.py"

CASES: list[tuple[str, str, object]] = [
    (
        "报表又自己算日期（`delivered_at.date()` 回到分桶里）",
        "backend/app/api/v1/reports.py",
        lambda s: s.replace(
            "        ds = business_date(o.delivered_at)\n        if ds is None or ds < start or ds > end:\n            continue\n",
            "        ds = o.delivered_at.date()\n        if ds < start or ds > end:\n            continue\n",
            1,
        ),
    ),
    (
        "日报小时桶又用 UTC 小时",
        "backend/app/api/v1/reports.py",
        lambda s: s.replace(
            "        h = business_local(o.delivered_at).hour",
            "        h = o.delivered_at.hour",
            1,
        ),
    ),
    (
        "撤销数又用 `func.date(` 筛",
        "backend/app/api/v1/reports.py",
        lambda s: s.replace(
            "            Order.cancelled_at >= c_start,",
            "            func.date(Order.cancelled_at) >= start,",
            1,
        ),
    ),
    (
        "导出金额又写成 `str(...)`（Excel 求和加不到）",
        "backend/app/api/v1/reports.py",
        lambda s: s.replace('"挂账未收", _money(data["arrears_total"])', '"挂账未收", str(data["arrears_total"])', 1),
    ),
    (
        "司机绩效导出又自己算准时率",
        "backend/app/api/v1/reports.py",
        lambda s: s.replace(
            "            for row in driver_performance(db, s, e):",
            "            ot_valid = [1 for x in [] if x]\n            for row in driver_performance(db, s, e):",
            1,
        ),
    ),
    (
        "司机绩效导出不再走那个唯一实现",
        "backend/app/api/v1/reports.py",
        lambda s: s.replace(
            "            from app.services.stats_service import driver_performance\n",
            "",
            1,
        ),
    ),
    (
        "运费结算页不再走 driver_pay（自己拿订单运费当应得）",
        "backend/app/api/v1/freight_settlement.py",
        lambda s: s.replace(
            "        pay = pay_for_order(o)",
            "        pay = type('P', (), {'total': o.freight_fee or 0})()",
            1,
        ),
    ),
    (
        "「自己算日期」的白名单被放宽（顺手加一行）",
        "_tools/qa/_check_single_source.py",
        lambda s: s.replace(
            '    "services/ledger_export.py": "导出行的 entry_date 直接来自账本列（已经是业务日）",',
            '    "services/ledger_export.py": "导出行的 entry_date 直接来自账本列（已经是业务日）",\n'
            '    "api/v1/reports.py": "注入：假装这里有理由",\n'
            '    "api/v1/orders.py": "注入：假装这里有理由",',
            1,
        ),
    ),
    # ---- ①b 裸写「现在」（R14-9）----
    (
        "消息列表的 days 又用进程本地时间（`datetime.now()`，少给 8 小时）",
        "backend/app/api/v1/notifications.py",
        lambda s: s.replace(
            "    cutoff = utc_now_naive() - timedelta(days=days)",
            "    cutoff = datetime.now() - timedelta(days=days)",
            1,
        ),
    ),
    (
        "软删除时间又写本地时间（30 天隔离期早 8 小时到期）",
        "backend/app/api/v1/products.py",
        lambda s: s.replace(".deleted_at = utc_now_naive()", ".deleted_at = datetime.now()", 1),
    ),
    (
        "订单兜底日期又用服务器本地日（`date.today()`）",
        "backend/app/services/order_flow.py",
        lambda s: s.replace("    return d or business_today()", "    return d or date.today()", 1),
    ),
    (
        "单号日期又用 UTC 日期（凌晨下的单印成昨天）",
        "backend/app/services/auth_service.py",
        lambda s: s.replace(
            'return f"SO{business_today():%Y%m%d}{secrets.randbelow(10**10):010d}"',
            'return f"SO{datetime.utcnow():%Y%m%d}{secrets.randbelow(10**10):010d}"',
            1,
        ),
    ),
    (
        "第 5 个文件也裸写本地时间（证明判据扫的是全仓，不是那 4 个已知文件）",
        "backend/app/api/v1/arrears.py",
        lambda s: s.replace(".deleted_at = utc_now_naive()", ".deleted_at = datetime.now()", 1),
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
        print(out[-1200:])
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    for label, rel, mutate in CASES:
        path = ROOT / rel
        original = path.read_text(encoding="utf-8")
        mutated = mutate(original)
        if mutated == original:
            # 白名单那条注入：如果清单里已经没有这行，说明判据结构变了
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            code, out = run_check()
        finally:
            path.write_text(original, encoding="utf-8", newline="")
        if code != 0:
            print(f"  [OK] {label} → 红线报红")
        else:
            fails.append(f"{label}：注入之后红线**仍然全绿**（判据没牙）")
            print(f"  [MISS] {label} → 仍然全绿")

    # 收尾：源码必须逐字节还原
    dirty = []
    for _label, rel, _m in CASES:
        path = ROOT / rel
        if "（注入" in path.read_text(encoding="utf-8"):
            dirty.append(rel)
    if dirty:
        fails.append("跑完没还原：" + "、".join(dirty))
    else:
        print("✅ 还原检查：被碰过的文件都不含注入痕迹")

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
