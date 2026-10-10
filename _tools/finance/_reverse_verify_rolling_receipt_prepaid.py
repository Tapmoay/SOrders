# -*- coding: utf-8 -*-
"""BUG-0036（TB-14）反向验证：把修复逐条弄坏，判据必须变红；末尾逐字节还原。"""
import hashlib
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "backend/app/services/receipt_credit.py"
BQ = ROOT / "backend/app/services/reports/balance_query.py"
CHECK = ROOT / "_tools/finance/_check_rolling_receipt_prepaid.py"

svc_orig = SERVICE.read_bytes()
bq_orig = BQ.read_bytes()
EOL_S = "\r\n" if "\r\n" in svc_orig.decode("utf-8") else "\n"
EOL_B = "\r\n" if "\r\n" in bq_orig.decode("utf-8") else "\n"


def _e(s: str, eol: str) -> str:
    return s.replace("\n", eol)


APPLY = (
    "    for key, credit in rolling_receipt_credit_map(db, as_of).items():\n"
    "        g = groups.get(key)\n"
    "        if g is None:\n"
    "            continue\n"
    '        g["prepaid"] += credit\n'
    '        g["balance"] -= credit\n'
)

MUTATIONS = [
    (SERVICE, "① 归集函数整块删掉", _e("def rolling_receipt_credit_map(", EOL_S), None),
    (BQ, "② 整块冲减拿掉（TB-14 复发）", _e(APPLY, EOL_B), ""),
    (SERVICE, "③ 不排除已撤销的收款", _e("            ShipperReceipt.is_deleted.is_(False),\n", EOL_S), ""),
    (SERVICE, "④ 不按报表日截断", _e("            ShipperReceipt.received_at <= as_of,\n", EOL_S), ""),
    (SERVICE, "⑤ 认成逐单核销",
     "ShipperReceipt.settle_mode == ReceiptSettleMode.ROLLING",
     "ShipperReceipt.settle_mode == ReceiptSettleMode.ITEMIZED"),
    (BQ, "⑥ 只加预收、不减欠款（恒等式会破）", _e('        g["balance"] -= credit\n', EOL_B), ""),
    (BQ, "⑦ 报表层又把钱自己 sum 了一遍",
     _e('    for key, credit in rolling_receipt_credit_map(db, as_of).items():', EOL_B),
     _e('    _dup = db.execute(select(func.sum(ShipperReceipt.amount))).scalar()\n'
        '    for key, credit in rolling_receipt_credit_map(db, as_of).items():', EOL_B)),
]


def run_check():
    p = subprocess.run([sys.executable, "-X", "utf8", str(CHECK)], cwd=str(ROOT),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def restore():
    SERVICE.write_bytes(svc_orig)
    BQ.write_bytes(bq_orig)


red = 0
problems = []
for path, name, old, new in MUTATIONS:
    src = path.read_bytes().decode("utf-8")   # ⛔ 不用 read_text：它会把 CRLF 统一成 LF，锚点就对不上了
    if src.count(old) != 1:
        problems.append("%s：锚点出现 %d 次（应为 1）" % (name, src.count(old)))
        continue
    if new is None:
        idx = src.index(old)
        src = src[:idx] + src[idx + len(old):]
    else:
        src = src.replace(old, new, 1)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(src)
    code, _ = run_check()
    if code == 0:
        problems.append("%s：判据**没有**变红" % name)
    else:
        red += 1
        print("  ✔ %s → 判据变红" % name)
    restore()

ok_sha = (hashlib.sha256(SERVICE.read_bytes()).hexdigest() == hashlib.sha256(svc_orig).hexdigest()
          and hashlib.sha256(BQ.read_bytes()).hexdigest() == hashlib.sha256(bq_orig).hexdigest())
print()
print("注入 %d 条，变红 %d 条" % (len(MUTATIONS), red))
print("还原后两文件逐字节一致：", ok_sha)
if problems:
    print("❌ 有问题：")
    for p in problems:
        print("   -", p)
    sys.exit(1)
if red != len(MUTATIONS) or not ok_sha:
    print("❌ 没做到「每条注入都红 + 逐字节还原」")
    sys.exit(1)
print("✅ %d/%d 都红了，且文件逐字节还原。" % (red, len(MUTATIONS)))
