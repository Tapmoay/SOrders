# -*- coding: utf-8 -*-
"""BUG-0036（TB-14）反向验证：把修复逐条弄坏，判据必须变红；末尾逐字节还原。"""
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "backend/app/services/reports/balance_query.py"
CHECK = ROOT / "_tools/finance/_check_rolling_receipt_prepaid.py"

original = SRC.read_bytes()
orig_sha = hashlib.sha256(original).hexdigest()
text = original.decode("utf-8")
EOL = "\r\n" if "\r\n" in text else "\n"


def _eol(s: str) -> str:
    return s.replace("\n", EOL)


APPLY = (
    "    for key, credit in _rolling_credit_map(db, as_of).items():\n"
    "        g = groups.get(key)\n"
    "        if g is None:\n"
    "            continue\n"
    '        g["prepaid"] += credit\n'
    '        g["balance"] -= credit\n'
)

MUTATIONS = [
    ("① 整块冲减拿掉（TB-14 复发）", APPLY, ""),
    ("② 不排除已撤销的收款", "            ShipperReceipt.is_deleted.is_(False),\n", ""),
    ("③ 不按报表日截断", "            ShipperReceipt.received_at <= as_of,\n", ""),
    ("④ 认成逐单核销（rolling 之外的钱也冲）",
     "ShipperReceipt.settle_mode == ReceiptSettleMode.ROLLING",
     "ShipperReceipt.settle_mode == ReceiptSettleMode.ITEMIZED"),
    ("⑤ 只加预收、不减欠款（恒等式会破）", '        g["balance"] -= credit\n', ""),
    ("⑥ 没有欠款行的债务人也凭空造一行",
     "        g = groups.get(key)\n        if g is None:\n            continue\n",
     "        g = groups.get(key)\n        if g is None:\n            g = _new_group(key[0], key[1], {}, {}, {})\n            groups[key] = g\n"),
    ("⑦ 不 import ShipperReceipt", "from app.models import ArrearsUnit, Customer, Ledger, Order, ShipperReceipt, User\n",
     "from app.models import ArrearsUnit, Customer, Ledger, Order, User\n"),
]


def run_check():
    p = subprocess.run([sys.executable, "-X", "utf8", str(CHECK)], cwd=str(ROOT),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


red = 0
problems = []
for name, old, new in MUTATIONS:
    old, new = _eol(old), _eol(new)
    if text.count(old) != 1:
        problems.append("%s：锚点出现 %d 次（应为 1）" % (name, text.count(old)))
        continue
    SRC.write_bytes(text.replace(old, new, 1).encode("utf-8"))
    code, _ = run_check()
    if code == 0:
        problems.append("%s：判据**没有**变红" % name)
    else:
        red += 1
        print("  ✔ %s → 判据变红" % name)
    SRC.write_bytes(original)

restored = hashlib.sha256(SRC.read_bytes()).hexdigest()
print()
print("注入 %d 条，变红 %d 条" % (len(MUTATIONS), red))
print("还原后 sha256 与运行前一致：", restored == orig_sha)
if problems:
    print("❌ 有问题：")
    for p in problems:
        print("   -", p)
    sys.exit(1)
if red != len(MUTATIONS) or restored != orig_sha:
    print("❌ 没做到「每条注入都红 + 逐字节还原」")
    sys.exit(1)
print("✅ %d/%d 都红了，且文件逐字节还原。" % (red, len(MUTATIONS)))
