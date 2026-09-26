"""反向验证：把这几轮的修复逐个"摘掉"，确认跨域 E2E 会红（否则那条测试是摆设）。

做法与仓库里其它 `_reverse_verify_*.py` 一致：改一处 → 跑目标测试 → 必须失败 → 还原。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# ⛔ 不许写死本机路径：CI 在 /home/runner/... 上跑，写死会让这 3 条注入**恒 SKIP**
#    （2026-09-25 CI 实测抓到：锚点检查报「目标文件不存在（被改名/搬走了？）」3 条，
#     而在本机因为那个目录真的存在，永远看不出来 —— 一份"死掉的反向验证"比没有更糟）。
ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
TARGET = "tests/test_full_loop_regression.py"

CASES: list[tuple[str, Path, str, str, int]] = [
    (
        # ⚠️ 必须换**全部**调用点（加/改/删行三处）：只换第一个时"改行"那条路径仍会重算，
        #    测试照样绿 —— 第一版就是这么写的，反向验证当场把它抓出来了。
        "库存预占不再随订单行重算（送达按旧流水扣库）",
        BACKEND / "app/api/v1/order_products.py",
        "    _resync_stock_if_assigned(db, order, current.id)",
        "    pass  # 注入：不重算预占",
        -1,
    ),
    (
        "账单不再按规则算、改回抄运费（司机钱算错）",
        BACKEND / "app/services/accounting_service.py",
        "    pay = pay_for_order(order)",
        "    pay = type('P', (), {'total': (order.freight_fee or 0), 'piece': 0, 'commission': 0})()  # 注入",
        1,
    ),
    (
        # 付款的 CAS 挡的是**并发**双付，而顺序双付本来就被"仅已确认可付款"挡住 ——
        # 所以 E2E（顺序执行）**测不出**它，硬写成 E2E 用例只会得到一条永远绿的假断言。
        # 它的正式判据是 `tests/test_money_audit_trail.py` 里"同一张结算单不能付两次"+
        # 原子性断言；这里换成 E2E 真能发现的破坏：
        "结算动作不再写操作日志（审计页查不到谁付的款）",
        BACKEND / "app/api/v1/driver_settlements.py",
        "        action=OperationAction.SETTLEMENT_STATUS,",
        "        action=OperationAction.ORDER_UPDATE,  # 注入：换成无关动作码",
        1,
    ),
]


def run() -> int:
    p = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", TARGET],
        cwd=str(BACKEND), capture_output=True, text=True,
    )
    return p.returncode


fails: list[str] = []
code = run()
if code != 0:
    print(f"❌ 前提不成立：源码完好时 {TARGET} 就没过")
    sys.exit(1)
print("✅ 前提：源码完好时 E2E 是绿的")

for label, path, old, new, count in CASES:
    src_bytes = path.read_bytes()
    src = src_bytes.decode("utf-8").replace(chr(13) + chr(10), chr(10))
    if old not in src:
        fails.append(f"{label}：注入锚点没找到（替换串过期了）")
        continue
    try:
        mutated = src.replace(old, new) if count < 0 else src.replace(old, new, 1)
        path.write_text(mutated, encoding="utf-8", newline="")
        code = run()
    finally:
        path.write_bytes(src_bytes)
    if path.read_bytes() != src_bytes:
        fails.append(f"{label}：还原后与快照不一致（注入污染了源码树）")
    if code == 0:
        fails.append(f"{label}：摘掉修复后 E2E **仍然通过** —— 这条测试是摆设")
    else:
        print(f"✅ 摘掉「{label}」→ E2E 报红")

if fails:
    print("\n❌ 反向验证不通过：")
    for f in fails:
        print("   -", f)
    sys.exit(1)
print(f"\n✅ {len(CASES)} 种破坏方式都证明跨域 E2E 真的在检查。")
