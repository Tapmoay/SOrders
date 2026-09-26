"""反向验证 `_tools/qa/_check_paid_actions.py`（已收款的动作，界面 / AI 不许再给一次）。

## 为什么必须做

这条判据守的事**坏了不会有任何报错**：界面把按钮放回去（只判 `!acting`）、
AI 处理器少判一句前置条件 —— 两者都能编译、都能跑，症状只在用户点下去的那一刻出现：
一句红字「这张单已经收过款了，不能改回挂账」，或者更糟——一张写着"将挂账到 X"的确认卡。
后端那一半当时（2026-09-19 R14-2）只修了自己，界面与 AI 两侧的缺口留到了真机才被发现。

所以逐条注入真缺陷，每条都必须让判据报红；跑完逐字节还原并再验一次绿。

用法：python _tools/qa/_reverse_verify_paid_actions.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_paid_actions.py"
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
ORDERS = ROOT / "backend/app/api/v1/orders_payment.py"   # 2026-09-24 阶段 4：pay/charge 搬去了这里
MODEL = ANDROID / "core/OrderStatusModel.kt"
SCREEN = ANDROID / "ui/order/OrderDetailScreen.kt"
HANDLERS = ANDROID / "ai/AiWriteOrderHandlers.kt"
AIWRITE = ANDROID / "ai/AiWrite.kt"
SERVICE = ANDROID / "ai/AiWriteDataSource.kt"

CASES: list[tuple[str, Path, object]] = [
    (
        "界面把判据摘掉、回到只判 `!acting`（真机实测抓到的那个写法）",
        SCREEN,
        lambda s: s.replace(
            "                            enabled = !acting &&\n"
            "                                OrderStatusModel.canChargeToArrears(order.paid, order.settledAmount),",
            "                            enabled = !acting,",
            1,
        ),
    ),
    (
        "AI 处理器不再做前置核对（会弹一张注定失败的确认卡）",
        HANDLERS,
        lambda s: s.replace(
            "        if (!OrderStatusModel.canChargeToArrears(order.paid, order.settledAmount)) {",
            "        if (false) {",
            1,
        ),
    ),
    (
        "客户端判据改成永远允许（`paid` 那一半被删）",
        MODEL,
        lambda s: s.replace(
            "        !paid && (settledAmount?.toDoubleOrNull() ?: 0.0) <= 0.0",
            "        (settledAmount?.toDoubleOrNull() ?: 0.0) <= 0.0",
            1,
        ),
    ),
    (
        "后端不再拒（防化石那一半失效）",
        ORDERS,
        lambda s: s.replace(
            '    _reject_if_already_collected(db, order, "改回挂账")',
            "    pass",
            1,
        ),
    ),
    (
        "`AiOrderRef` 少带 `settledAmount`（判据读到默认值 = 永远允许）",
        AIWRITE,
        lambda s: s.replace(
            '    val settledAmount: String = "0",',
            '    val settledAmountX: String = "0",',
            1,
        ),
    ),
    (
        "两处构造点只填一处（另一条路上的 AI 永远以为没收过款）",
        SERVICE,
        lambda s: s.replace("                paid = d.paid,\n", "", 1),
    ),
]


def run(path: Path) -> int:
    p = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    return p.returncode


def main() -> int:
    before = {str(p): p.read_text(encoding="utf-8") for _, p, _ in CASES}
    if run(CHECK) != 0:
        print("❌ 前提不成立：源码完好时这条判据就没过（先让它变绿）")
        return 1
    print("✅ 前提：源码完好时判据是绿的")

    fails: list[str] = []
    for label, path, mutate in CASES:
        original_bytes = path.read_bytes()
        original = original_bytes.decode("utf-8").replace(chr(13) + chr(10), chr(10))
        mutated = mutate(original)
        if mutated == original:
            fails.append(f"{label}：注入没生效（替换串过期了，请更新本脚本）")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            code = run(CHECK)
        finally:
            path.write_bytes(original_bytes)
        if code != 0:
            print(f"✅ 注入「{label}」→ 报红")
        else:
            fails.append(f"{label}：注入之后没有报红 —— 这条判据是空转的")

    for k, v in before.items():
        if Path(k).read_text(encoding="utf-8") != v:
            fails.append(f"收尾没还原：{k}")
    if run(CHECK) != 0:
        fails.append("还原之后判据仍然红（有文件没被改回来）")

    if fails:
        print("\n❌ 反向验证没通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ {len(CASES)}/{len(CASES)} 种破坏方式全部被抓到，且源码已还原。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
