# -*- coding: utf-8 -*-
"""BUG-0036（测试台账 TB-14）：未指定订单的收款（滚动收款）要冲减客户欠款、冲掉的部分进「预收」。

判据（静态锚点 + 行为）：
  1. 归集函数 rolling_receipt_credit_map 在 **service**（app/services/receipt_credit.py）里，
     只认**未撤销、截止报表日**的 rolling 收款，认不出来的散客不猜；
  2. 报表层（services/reports/balance_query.py）只**调用**它 —— ⛔ 不许自己 func.sum
     （钱不在别处再算一遍，_tools/qa/_check_customer_balances.py 钉着这一条）；
  3. 冲减只落在**已经有欠款行**的债务人身上，且 prepaid += credit / balance -= credit 成对出现；
  4. 两个单测钉着：收 124 → 欠款少 124、预收多 124；撤销 → 原样回去；别的债务人的行不动。

用法：
  python _tools/finance/_check_rolling_receipt_prepaid.py             # 主工作树
  python _tools/finance/_check_rolling_receipt_prepaid.py <另一棵树>   # 跑「改前必红」
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
SERVICE = ROOT / "backend/app/services/receipt_credit.py"
BQ = ROOT / "backend/app/services/reports/balance_query.py"
TEST = ROOT / "backend/tests/test_rolling_receipt_prepaid.py"

PASS = 0
FAIL = []


def ok(cond, msg):
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(msg)


def stripped(p: Path) -> str:
    raw = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
    return "\n".join(l for l in raw.splitlines() if not l.strip().startswith("#"))


svc = stripped(SERVICE)
bq = stripped(BQ)

ok(SERVICE.is_file(), "缺 backend/app/services/receipt_credit.py（归集该在 service 里）")
ok("def rolling_receipt_credit_map(" in svc, "service 里没有 rolling_receipt_credit_map")
ok("ShipperReceipt.settle_mode == ReceiptSettleMode.ROLLING" in svc, "没有只认 rolling 收款")
ok("ShipperReceipt.is_deleted.is_(False)" in svc, "没有排除已撤销的收款（撤销了还在冲账）")
ok("ShipperReceipt.received_at <= as_of" in svc, "没有按报表日截断（未来的收款会冲今天的账）")
ok('("unit", str(c.arrears_unit_id))' in svc, "没有把收款归到挂账单位（与 _debtor_of 口径不一致）")
ok('("shipper", str(c.user_id))' in svc, "没有把收款归到货主账号")
ok(svc.count("continue") >= 2, "认不出来的收款没有跳过（会猜一个债务人出来）")

ok(BQ.is_file(), "找不到 backend/app/services/reports/balance_query.py")
ok("from app.services.receipt_credit import rolling_receipt_credit_map" in bq,
   "报表层没有从 service 取归集结果")
ok("rolling_receipt_credit_map(db, as_of)" in bq, "出报表时没有调用归集函数")
ok("func.sum(" not in bq, "报表层又自己 func.sum 了一遍钱（_check_customer_balances.py 会红）")
ok('g["prepaid"] += credit' in bq and 'g["balance"] -= credit' in bq,
   "没有成对冲减（prepaid += / balance -=）")
ok(re.search(r"if g is None:\s*\n\s*continue", bq) is not None,
   "没有跳过「没有欠款行」的债务人（会凭空多出一行）")
i_apply = bq.find("rolling_receipt_credit_map(db, as_of)")
i_out = bq.find("out_rows = [")
ok(i_apply >= 0 and i_out > i_apply, "冲减发生在出报表之后（等于没冲）")
ok("未指定订单的收款" in bq, "notes 里没写这条口径（用户看不到钱去哪了）")

ok(TEST.is_file(), "缺 backend/tests/test_rolling_receipt_prepaid.py")
t = TEST.read_text(encoding="utf-8", errors="replace") if TEST.is_file() else ""
ok("test_rolling_receipt_offsets_arrears_and_shows_as_prepaid" in t, "缺「收款 → 冲减 + 预收」的用例")
ok("test_rolling_receipt_never_moves_another_debtors_row" in t, "缺「不许动别人那一行」的用例")

print("PASS =", PASS)
if FAIL:
    print("❌ 以下锚点不成立：")
    for f in FAIL:
        print("   -", f)
    sys.exit(1)
print("✅ 全部 %d 项通过：滚动收款在 service 里按债务人归集，报表层只调用并冲减欠款/增加预收（BUG-0036 / TB-14）。" % PASS)
