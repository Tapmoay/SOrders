"""红线：**已收款的动作，界面 / AI 卡片不许再给一次**（2026-09-23 第 14 轮，真机实测抓到）。

## 由来（后端那一半修了、界面那一半没修）

后端 `orders.charge_order` → `_reject_if_already_collected(db, order, "改回挂账")`：
**已经收过款的单不许改回挂账** —— 收款侧唯一的防重判据就是 `paid`，把它改回 False
等于给这张单**重新开了一次收款窗口**（收款单与收款流水都还在），再核销一次就是
"资金流入 2×、营业额 1×"（2026-09-19 审计 R14-2）。

⚠️ 那次只修了后端，**界面与 AI 两侧的缺口一直留着**：
- `OrderDetailScreen` 的「挂账」按钮只判 `!acting` → 在**已收现金**的单上一直可点，
  点下去必然 400（后端自己的文档里就写着这句话）；
- `ChargeOrderHandler.prepare` 只判了状态 → 会弹一张**注定失败**的确认卡。

2026-09-23 用真机走「派单(收现金) → 挂账 → 司机收现金送达」时抓到的：
送达后订单显示「已收款」，而「挂账」按钮**仍然是亮的**，与后端判据和 UI 状态自相矛盾。

## 判据（四处一起对账，缺一处就是"点了必然失败"或"能绕过去"）

1. **后端仍然拒**：`orders.py` 里 `charge_order` 必须调用 `_reject_if_already_collected`
   （防化石：哪天有人把这句删了，判据先喊）；
2. **判据只有一份**：客户端 `OrderStatusModel.canChargeToArrears(paid, settledAmount)` 存在，
   且它的判据与后端同一套（`paid` 标记 **或** 已收金额 > 0 的物证）；
3. **界面用它**：`OrderDetailScreen` 的「挂账」按钮 `enabled` 里出现这个函数名，
   ⛔ 不许只写 `!acting`（那正是被修掉的那个写法）；
4. **AI 用它**：`ChargeOrderHandler.prepare` 里出现这个函数名（前置条件先核对，别弹注定失败的卡）。

用法：python _tools/qa/_check_paid_actions.py
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ORDERS = ROOT / "backend/app/api/v1/orders.py"
MODEL = ROOT / "android/app/src/main/java/com/tapmoay/sorders/core/OrderStatusModel.kt"
SCREEN = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailScreen.kt"
AI_HANDLERS = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteOrderHandlers.kt"

PREDICATE = "canChargeToArrears"

fails: list[str] = []
passes = 0


def ok(label: str, cond: bool, detail: str = "") -> None:
    global passes
    if cond:
        passes += 1
        print(f"  [OK]   {label}")
    else:
        fails.append(label + (f" —— {detail}" if detail else ""))
        print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的判据要跟着改，不许静默跳过）")
    return io.open(p, encoding="utf-8", errors="replace").read()


def main() -> int:
    orders = read(BACKEND_ORDERS) + read(BACKEND_ORDERS.parent / "orders_payment.py")   # charge/pay 在 2026-09-24 阶段 4 搬去了那边
    model = read(MODEL)
    screen = read(SCREEN)
    handlers = read(AI_HANDLERS)

    print("① 后端仍然拒「已收款 → 挂账」（防化石）")
    charge = orders[orders.find("def charge_order("):]
    charge = charge[:charge.find("\n@router", 10)] if "\n@router" in charge[10:] else charge
    ok("`charge_order` 里调了 `_reject_if_already_collected`",
       "_reject_if_already_collected(db, order, " in charge)
    ok("那个判据的实现还在（`paid` 标记 **或** 进账物证）",
       "def _already_collected(" in orders and "CashFlow" in orders)

    print("\n② 客户端判据只有一份")
    ok(f"`OrderStatusModel.{PREDICATE}(` 存在", f"fun {PREDICATE}(" in model)
    body = model[model.find(f"fun {PREDICATE}("):]
    body = body[:body.find("\n    }") + 6] if "\n    }" in body else body
    ok("判据同时认「标记」与「物证」：`paid` 且 `settledAmount > 0` 之否定",
       "!paid" in body and "settledAmount" in body, body[:200])
    ok("注释里点了后端那个函数名（下一个人能顺着查）",
       "_reject_if_already_collected" in model)

    print("\n③ 界面：挂账按钮必须走这个判据")
    # 取「挂账」那个 Button 的 enabled 表达式（到 onClick 之前的最近一个 Button）
    idx = screen.find('Text("挂账")')
    ok("找得到「挂账」按钮", idx > 0)
    window = screen[max(0, idx - 900):idx]
    ok(f"它的 `enabled` 里出现 `{PREDICATE}(`", f"{PREDICATE}(" in window,
       "又回到只判 `!acting` 的写法 = 已收款的单上按钮可点、点了必然 400")
    ok("它读的是 `order.paid` 与 `order.settledAmount`（不是别的字段）",
       "order.paid" in window and "order.settledAmount" in window, window[-260:])

    print("\n④ AI：挂账处理器必须走这个判据（别弹注定失败的卡）")
    charge_handler = handlers[handlers.find("class ChargeOrderHandler("):]
    charge_handler = charge_handler[:charge_handler.find("\nclass ", 10)] if "\nclass " in charge_handler[10:] else charge_handler
    ok(f"`ChargeOrderHandler.prepare` 里出现 `{PREDICATE}(`", f"{PREDICATE}(" in charge_handler)
    ok("它用的字段是 `order.paid` / `order.settledAmount`",
       "order.paid" in charge_handler and "order.settledAmount" in charge_handler)

    print("\n⑤ `AiOrderRef` 真的带了这两个字段（否则上面那句读的是默认值 = 永远允许）")
    aiwrite = read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWrite.kt")
    ref = aiwrite[aiwrite.find("data class AiOrderRef("):]
    ref = ref[:ref.find("\n) {") + 4] if "\n) {" in ref else ref
    ok("`AiOrderRef` 有 `paid`", re.search(r"\bval paid: Boolean", ref) is not None)
    ok("`AiOrderRef` 有 `settledAmount`", re.search(r"\bval settledAmount: String", ref) is not None)
    service = read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteService.kt")
    n = len(re.findall(r"paid = d\.paid,", service))
    ok(f"两处构造点都填了它（实际 {n} 处 ≥ 2）", n >= 2, "少填一处 → 那条路上的 AI 永远以为没收过款")

    print("\n" + "=" * 60)
    if fails:
        print(f"❌ {len(fails)} 项不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {passes} 项通过：「已收款 → 挂账」在后端被拒、在界面与 AI 两侧都被前置挡住，"
          f"判据共用 {PREDICATE}（一处实现、三处消费）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
