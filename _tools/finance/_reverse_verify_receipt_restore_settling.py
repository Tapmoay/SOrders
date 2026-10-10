# -*- coding: utf-8 -*-
"""BUG-0033（TB-12）反向验证：把修复逐条弄坏，判据必须变红；末尾逐字节还原。"""
import hashlib
import subprocess
import sys

# 判据/反验会打 ✅/❌ —— GBK 控制台下必须自己把 stdout 钉成 UTF-8（_check_tool_scripts.py）。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "backend/app/api/v1/ledger.py"
CHECK = ROOT / "_tools/finance/_check_receipt_restore_settling.py"

original = SRC.read_bytes()
orig_sha = hashlib.sha256(original).hexdigest()
text = original.decode("utf-8")

# ⚠️ 这里只用 \n 写；真正的换行由下面的 _eol() 对齐到文件自己的换行（本文件在库里是 CRLF）
GUARD = "            if oid not in rolled:\n                continue\n"

MUTATIONS = [
    ("① 拿掉「只翻名单里的订单」这道闸（TB-12 复发）", GUARD, ""),
    ("② 闸门写成永假（等于没有）", "            if oid not in rolled:", "            if False and oid not in rolled:"),
    ("③ 名单不按 RECEIPT_CANCEL 取（改成取恢复那一笔）",
     "OperationAction.RECEIPT_CANCEL.value", "OperationAction.RECEIPT_RESTORE.value"),
    ("④ 名单不按 receipt_id 复核（拿到别人的名单也用）",
     '        if payload.get("receipt_id") != receipt_id:\n            continue\n', ""),
    ("⑤ 找不到名单时默认「全翻」", "    return set()\n", "    return {int(x) for x in (payload.get(\"orders_rolled_back\") or [])}\n"),
    ("⑥ 恢复时不取名单，直接把订单全当成翻过的",
     "rolled = _cancel_rolled_orders(db, r.id)", "rolled = set(order_ids)"),
    ("⑦ 去掉 import json", "import json\n", ""),
]


EOL = "\r\n" if "\r\n" in text else "\n"


def _eol(s: str) -> str:
    """把注入片段里的换行对齐到文件自己的换行（本文件在库里是 CRLF）。"""
    return s.replace("\n", EOL)


def run_check(extra=None):
    p = subprocess.run([sys.executable, "-X", "utf8", str(CHECK)] + (extra or []),
                       cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
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
