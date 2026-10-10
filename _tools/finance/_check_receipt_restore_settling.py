# -*- coding: utf-8 -*-
"""BUG-0033（测试台账 TB-12）：恢复一笔收款时，**只翻撤销那一步翻过的订单**。

判据（静态锚点 + 行为）：
  1. 恢复分支必须先拿「撤销时翻过的名单」（_cancel_rolled_orders），再按名单决定翻不翻 paid；
  2. 名单来自审计 RECEIPT_CANCEL 的 payload.orders_rolled_back，且按 receipt_id 精确匹配；
  3. 找不到名单时返回空集（宁可让用户再收一次，也不要"欠着钱却显示已收"）；
  4. 三个单测钉着：部分核销撤销→恢复仍欠着、全额核销回到已收、撤销期间被别人收清的由门③拦。

用法：
  python _tools/finance/_check_receipt_restore_settling.py             # 主工作树
  python _tools/finance/_check_receipt_restore_settling.py <另一棵树>   # 跑「改前必红」
"""
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
SRC = ROOT / "backend/app/api/v1/ledger.py"
TEST = ROOT / "backend/tests/test_receipt_partial_restore.py"

PASS = 0
FAIL = []


def ok(cond, msg):
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(msg)


raw = SRC.read_text(encoding="utf-8", errors="replace") if SRC.is_file() else ""
text = "\n".join(l for l in raw.splitlines() if not l.strip().startswith("#"))

ok(SRC.is_file(), "找不到 backend/app/api/v1/ledger.py")
ok(re.search(r"(?m)^import json$", text) is not None, "ledger.py 没有 import json（名单是 JSON 里的字段）")

# ① 名单函数
m = re.search(r"def _cancel_rolled_orders\(.*?(?=\n@router|\ndef |\Z)", text, re.S)
helper = m.group(0) if m else ""
ok(bool(helper), "找不到 _cancel_rolled_orders（恢复无从知道撤销翻过哪几张单）")
ok("OperationAction.RECEIPT_CANCEL.value" in helper, "名单不是从 RECEIPT_CANCEL 的审计里取的")
ok("change_content.like(" in helper, "没有按 change_content 过滤（会全表扫审计）")
ok('"receipt_id": %d,' in helper or "receipt_id" in helper, "没有按 receipt_id 精确匹配")
ok('payload.get("receipt_id") != receipt_id' in helper, "取到别的收款单的名单也会用（没复核 receipt_id）")
ok('payload.get("orders_rolled_back")' in helper, "没读 orders_rolled_back")
ok("return set()" in helper, "找不到名单时没有安全兜底（必须返回空集，不许默认全翻）")

# ② 恢复分支按名单翻
m2 = re.search(r"def restore_receipt_endpoint\(.*?(?=\n@router|\ndef |\Z)", text, re.S)
restore = m2.group(0) if m2 else ""
ok(bool(restore), "找不到 restore_receipt_endpoint")
ok(re.search(r"rolled = _cancel_rolled_orders\(db, r\.id\)", restore) is not None,
   "恢复时没有先取「撤销翻过的名单」")
guard = re.search(r"if oid not in rolled:\s*\n\s*continue\s*\n\s*o = orders\[oid\]\s*\n\s*o\.paid = True", restore)
ok(guard is not None, "翻 paid 的那两行前面没有「只翻名单里的订单」这道闸（TB-12 会复发）")
ok(restore.count("o.paid = True") == 1, "翻 paid 的地方不唯一（有一处是无条件的？）")
# 结构性：paid=True 必须排在 rolled 之后
i_rolled = restore.find("rolled = _cancel_rolled_orders")
i_paid = restore.find("o.paid = True")
ok(i_rolled >= 0 and i_paid > i_rolled, "paid=True 出现在取名单之前（那就是无条件翻）")

# ③ 单测
ok(TEST.is_file(), "缺 backend/tests/test_receipt_partial_restore.py")
t = TEST.read_text(encoding="utf-8", errors="replace") if TEST.is_file() else ""
for name, why in (
    ("test_partial_receipt_restore_does_not_mark_the_order_paid", "缺「部分核销撤销→恢复仍欠着」的用例"),
    ("test_full_receipt_restore_still_marks_the_order_paid", "缺「全额核销恢复回已收」的回归用例"),
    ("test_restore_leaves_alone_orders_the_cancel_never_touched", "缺「撤销期间被别人收清 → 门③拦住」的用例"),
):
    ok(name in t, why)

print("PASS =", PASS)
if FAIL:
    print("❌ 以下锚点不成立：")
    for f in FAIL:
        print("   -", f)
    sys.exit(1)
print("✅ 全部 %d 项通过：恢复收款只翻「撤销那一步翻过」的订单，部分核销的单不会被误标已收款（BUG-0033 / TB-12）。" % PASS)
