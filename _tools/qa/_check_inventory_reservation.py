"""红线：库存预占的判据必须看**订单状态**，不许拿流水当"派过单没有"（2026-09-19 审计，K1 的漏口）。

## 由来
`_resync_stock_if_assigned`（`api/v1/order_products.py`）负责"订单行改了之后把预占补齐"，
它原来的判据是"这张单有没有 RESERVED 流水"：

```python
has = db.scalars(select(InventoryMovement.id).where(... status == "RESERVED").limit(1)).first()
if has is None:
    return 0        # ← 以为"没派过单"，其实是"派过，只是那一行解析不出商品"
```

而 `auto_stock_out` 是**逐行**写的：行的商品解析不出来（手输商品名 / 商品库里有多个同名）时
**那一行一条流水都没有**（设计如此）。于是这条链一路静默：

1. 手输商品名下单 → 派单（这一行没有预占）
2. 派单员把该行改成库里的商品（界面允许，货还没发）
3. 老判据查到 0 条 RESERVED → `return 0` → **预占永远补不回来**
4. 送达时 `auto_stock_commit` 只遍历 RESERVED → 那一件货**一件都不扣**

本机只读复核：在途未删订单里"有商品编号却零预占"的 (单,商品) 对 **21** 个，
`GET /inventory/summary` 的「在途占用」与在途订单行有 **9** 个商品对不上（合计至少 72 件），
`note='订单行变更后重算预占'` 的流水**一行都没有**。

## 判据（清单自己算）
1. `_resync_stock_if_assigned` 的函数体里必须**判订单状态**（`order.dispatched_at is None`），
   且**不许再出现对 `InventoryMovement` 的查询**（那就是"拿流水当状态"）；
2. 重算之前必须**锁订单行**（`with_for_update`）：`resync_reservations` 是"算目标值 → 与现有
   流水对账 → 补差额"，两个并发的行编辑会各写同一个差额 → 预占翻倍 → 送达**多扣**；
3. `resync_reservations` 必须存在，且被 **≥3** 处调用（新增行 / 改行 / 删行三条路径）；
4. 反空转：`order_products.py` 里的写端点数量与调用点数量都要达标。

用法：python _tools/qa/_check_inventory_reservation.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_single_source import code_only  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ORDER_PRODUCTS = ROOT / "backend/app/api/v1/order_products.py"
INVENTORY_SVC = ROOT / "backend/app/services/inventory_service.py"


def func_body(src: str, name: str) -> str:
    """取一个顶层函数的函数体（从 `def name(` 到下一个顶层 `def `/`@router` 之前）。"""
    m = re.search(rf"^def {re.escape(name)}\(", src, re.M)
    if not m:
        return ""
    rest = src[m.end():]
    nxt = re.search(r"^(?:def |@router|class )", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def main() -> int:
    fails: list[str] = []
    for p in (ORDER_PRODUCTS, INVENTORY_SVC):
        if not p.exists():
            print(f"❌ 找不到 {p}（改名/移动了？判据要跟着改）")
            return 1

    src = code_only(ORDER_PRODUCTS.read_text(encoding="utf-8"))
    svc = code_only(INVENTORY_SVC.read_text(encoding="utf-8"))
    body = func_body(src, "_resync_stock_if_assigned")
    print(f"_resync_stock_if_assigned 函数体 {len(body)} 字符")

    # ---- ① 判据必须是订单状态，不是流水 ----
    if not body:
        fails.append("`_resync_stock_if_assigned` 不见了（判据要跟着改，不许静默跳过）")
    else:
        ok_state = "order.dispatched_at is None" in body
        print(f"   · 判订单状态（`order.dispatched_at is None`）：{'✅' if ok_state else '❌'}")
        if not ok_state:
            fails.append(
                "`_resync_stock_if_assigned` 没有判订单状态（`order.dispatched_at is None`）——"
                "判据一旦回到『有没有 RESERVED 流水』，手输商品名的单就永远补不上预占"
            )
        if "InventoryMovement" in body:
            fails.append(
                "`_resync_stock_if_assigned` 里又出现 `InventoryMovement`（拿流水当『派过单没有』的判据）——"
                "解析不出商品的那一行本来就没有流水，这会把预占永久漏掉"
            )

    # ---- ② 重算前锁订单行 ----
    if body and "with_for_update" not in body:
        fails.append(
            "`_resync_stock_if_assigned` 重算预占前没有锁订单行（`with_for_update`）——"
            "两个并发的行编辑会各写同一个差额 → 预占翻倍 → 送达多扣"
        )
    print(f"   · 重算前锁订单行：{'✅' if 'with_for_update' in body else '❌'}")

    # ---- ③ resync_reservations 存在且被多处调用 ----
    if "def resync_reservations(" not in svc:
        fails.append("`inventory_service.resync_reservations` 不见了（预占对账的唯一实现没了）")
    calls = len(re.findall(r"_resync_stock_if_assigned\(", src)) - 1  # 减去定义那一处
    print(f"   · `_resync_stock_if_assigned` 调用点 {calls} 处")
    if calls < 3:
        fails.append(
            f"`_resync_stock_if_assigned` 只有 {calls} 个调用点（<3）——"
            "加行/改行/删行三条路径里至少有一条不再重算预占，判据可能在空转"
        )
    write_routes = len(re.findall(r"@router\.(?:post|patch|put|delete)\(", src))
    print(f"   · order_products.py 写端点 {write_routes} 个")
    if write_routes < 3:
        fails.append(f"order_products.py 只认出 {write_routes} 个写端点（<3）——判据可能已空转")

    if fails:
        print("\n❌ 预占判据被改坏：")
        for f in fails:
            print("   - " + f)
        return 1
    print("\n✅ 预占按订单状态判断、重算前锁行，三条路径都接线。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
