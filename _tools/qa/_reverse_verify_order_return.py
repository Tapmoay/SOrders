"""反向验证 `_check_order_return.py`（退货 + 按商品核销的红线）。

## 为什么这一份必须有
这两件事都在动**钱**，而它们的错法全都"看起来正常"：
账上少一截、库存多一批、客户多收一笔 —— 界面上没有任何红字，只有月底对账才发现。
所以每一条判据都要证明它**真的拦得住**：注入一个坏写法 → 红线必须报红。

## 注入点怎么选（规矩：挑「旧检查不看的地方」）
- 不是把常量改掉（那种一眼可见），而是把**语义**换掉：
  `total=-line_amount` → `total=line_amount`（退货变成又卖一次）、
  `min(returned_now, already_refundable)` → 只有第一个上限（倒贴）、
  `if part > m.arrears` → `if False`（超额核销）……
- 客户端注入放在**别处不看**的判据上（上限公式、状态门、徽章中文名）。

用法：python _tools/qa/_reverse_verify_order_return.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_order_return.py"
RET = ROOT / "backend/app/services/order_return.py"
ACCT = ROOT / "backend/app/services/accounting_service.py"
ENUMS = ROOT / "backend/app/models/enums.py"
BOOTSTRAP = ROOT / "backend/app/core/schema_bootstrap.py"
ORDERS_API = ROOT / "backend/app/api/v1/orders.py"
STATUS_MODEL = ROOT / "android/app/src/main/java/com/tapmoay/sorders/core/OrderStatusModel.kt"
COMPONENTS = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/common/Components.kt"
STATS = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/LedgerPersonStats.kt"
RETURN_RULES = ROOT / "android/app/src/main/java/com/tapmoay/sorders/core/ReturnRules.kt"
VM_ORDERS = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DispatcherOrdersViewModel.kt"
#: 账本展开行用的状态中文名（2026-09-21 补上「已退货」那一档；注入点钉在这儿）
PEEK = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/common/OrderPeek.kt"


def sub(old: str, new: str, count: int = 1):
    def apply(src: str) -> str:
        if old not in src:
            raise LookupError(f"替换串过期了：{old[:60]!r}")
        return src.replace(old, new, count)

    return apply


CASES: list[tuple[str, Path, object]] = [
    # ---- 账本红冲 ----
    ("红冲行金额写成正数（退了货反而又多一笔营业额）", RET, sub("total=-line_amount", "total=line_amount")),
    ("红冲行挂了 REFUND（与货损那一行撞唯一约束）", RET, sub("source=LedgerSource.RETURN", "source=LedgerSource.REFUND")),
    (
        "本次退货金额改回「按行取两位再求和」（四位单价下与账本红冲差一分，退现比账上多付）",
        RET,
        sub("        returned_raw += line_amount", "        returned_raw += _q2(line_amount)"),
    ),
    (
        "红冲行绕开调用方传进来的金额、自己再算一遍（两边各算一遍＝差一分的土壤）",
        RET,
        sub(
            "_reversal_row(db, order, op, qty, line_amount, entry_date,",
            "_reversal_row(db, order, op, qty, _line_amount(op, qty), entry_date,",
        ),
    ),
    (
        "红冲行改回读改写（并发两次退货丢掉一次）",
        RET,
        sub("quantity=Ledger.quantity - qty", "quantity=row.quantity - qty"),
    ),
    (
        "已退数量改回读改写（同一行能被退超量）",
        RET,
        sub(
            "values(returned_quantity=OrderProduct.returned_quantity + qty)",
            "values(returned_quantity=int(op.returned_quantity or 0) + qty)",
        ),
    ),
    ("退货不回补库存（库存永久少一批货）", RET, sub("restocked = restock_returned(db, order, lines, operator_id)", "restocked = 0")),
    # ---- 退现 ----
    (
        "退现只留「不超过这次退的货值」这一条上限（客户只付过 300 却退 400 = 倒贴）",
        RET,
        sub("return _q2(min(returned_now, already_refundable))", "return _q2(returned_now)"),
    ),
    ("退货时把 paid 改回 False（钱确实进来过，抹掉标记＝能再收一次）", RET, sub("order.returned_at = _now()", "order.paid = False\n    order.returned_at = _now()")),
    ("货损那几件也能退（同一批货既算损失又算回库）", RET, sub("- int(op.damage_quantity or 0) - int(op.returned_quantity or 0)", "- int(op.returned_quantity or 0)")),
    ("退货不留痕（审计里查不出谁退的）", RET, sub("action=OperationAction.ORDER_RETURN", "action=OperationAction.ORDER_UPDATE")),
    ("端点取单不加锁（两个退货请求各自算通过）", ORDERS_API, sub(".where(Order.id == order_id)\n        .with_for_update()", ".where(Order.id == order_id)")),
    # ---- 按商品核销 ----
    (
        "按商品核销不校验行归属（拿 A 单的行核销 B 单的额度）",
        ACCT,
        sub("if op.order_id not in locked:", "if False:"),
    ),
    ("核销金额超过欠款也放行（欠款变负数）", ACCT, sub("if part > m.arrears:", "if False:")),
    (
        "整单核销又按「应收」算（部分核销过的单再也收不动；金额凑巧对上就是多收）",
        ACCT,
        sub("else m.arrears\n", "else m.receivable\n"),
    ),
    (
        "部分核销也翻 paid（这张单从「挂账未收」名单里消失，而它还欠一半）",
        ACCT,
        sub(
            "settling = [oid for oid in order_ids if per_order[oid] >= money[oid].arrears]",
            "settling = list(order_ids)",
        ),
    ),
    (
        "并发下的欠款判定改回普通读（REPEATABLE READ 快照让两个请求都读到旧值）",
        ACCT,        sub("money_map(db, list(locked.values()), lock=True)", "money_map(db, list(locked.values()))"),
    ),
    ("已退货的单又能收款（货款已经红冲掉了）", ACCT, sub("if (o.status or \"\").upper() == OrderStatus.RETURNED.value:", "if False:")),
    # ---- 枚举 / 迁移 ----
    ("MySQL 的 orders.status 枚举不再补 RETURNED（生产一退货就 500）", BOOTSTRAP, sub("'DELIVERED','CANCELLED','RETURNED'", "'DELIVERED','CANCELLED'")),
    ("审计动作码 ORDER_RETURN 被删（App 侧的中文名表也对不上了）", ENUMS, sub('ORDER_RETURN = "ORDER_RETURN"', 'ORDER_RETURN_X = "ORDER_RETURN"')),
    # ---- 客户端 ----
    ("客户端退货状态门放宽到已退货（对退过的单再点退货）", STATUS_MODEL, sub('val RETURNABLE: Set<String> = setOf("DELIVERED")', 'val RETURNABLE: Set<String> = setOf("DELIVERED", "RETURNED")')),
    ("状态徽章删掉「已退货」分支（界面直接印原始码 RETURNED）", COMPONENTS, sub('"RETURNED" -> {', '"RETURNED_X" -> {')),
    # 2026-09-21 补：账本展开行用的那份状态中文名原来少「已退货」一档（同样是直接印原始码）
    ("账本展开行的「已退货」那一档被删（OrderPeek 里直接印原始码）", PEEK, sub('    "RETURNED" -> "已退货"', '    "RETURNED_X" -> "已退货"')),
    (
        "客户端上限不减已退数量（界面让填 3、后端只认 2）",
        RETURN_RULES,
        sub("quantity - damageQuantity - returnedQuantity", "quantity - damageQuantity"),
    ),
    (
        "客户端上限又抄出一份（三个消费点各写一遍，迟早分叉）",
        VM_ORDERS,
        sub("ReturnRules.maxReturnable(\n            line.quantity,", "(line.quantity - line.damageQuantity\n            - line.returnedQuantity).coerceAtLeast(0)\n        ReturnRules.maxReturnable(\n            line.quantity,"),
    ),
    (
        "分摊的余数不落在最后一行（各商品未收加起来不等于订单欠款）",
        STATS,
        sub("i == lines.lastIndex -> arrears - allocated", "i == -1 -> arrears - allocated"),
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
        print(f"❌ 前提不成立：源码完好时红线就没过\n{out[-1500:]}")
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    fails: list[str] = []
    #: 每个被碰过的文件的**运行前原文**：跑完要逐字节比回去（注入脚本最危险的错法
    #: 就是"某条路径还原失败"，那会把一个坏文件留在仓库里，而后面所有检查都不作数）。
    originals: dict[Path, str] = {}
    for label, path, mutate in CASES:
        if path not in originals:
            originals[path] = path.read_text(encoding="utf-8")
        original = originals[path]
        try:
            mutated = mutate(original)  # type: ignore[operator]
        except LookupError as e:
            fails.append(f"{label}：{e}")
            continue
        if mutated == original:
            fails.append(f"{label}：注入没生效（替换串过期了，请更新本脚本）")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            code, out = run_check()
        finally:
            path.write_text(original, encoding="utf-8", newline="")
        if code == 0:
            fails.append(f"{label}：注入后红线**没有**报红 —— 这条判据是空转的")
        else:
            print(f"✅ 注入「{label}」→ 红线报红")

    # 还原检查：每个被碰过的文件必须与运行前**逐字节一致**
    dirty = [p for p, src in originals.items() if p.read_text(encoding="utf-8") != src]
    if dirty:
        fails.append(
            "还原失败（仓库里留着被注入过的坏文件，后面所有检查都不作数）："
            + "、".join(str(p.relative_to(ROOT)) for p in dirty)
        )
    else:
        print(f"✅ 还原检查：{len(originals)} 个被碰过的文件与运行前逐字节一致")

    if fails:
        print("\n❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ {len(CASES)} 条注入全部证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
