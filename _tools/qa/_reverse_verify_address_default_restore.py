# -*- coding: utf-8 -*-
"""BUG-0032（TA-14）反向验证：把修复逐条弄坏，判据必须变红；末尾逐字节还原。"""
import hashlib
import subprocess
import sys

# 判据/反验会打 ✅/❌ —— GBK 控制台下必须自己把 stdout 钉成 UTF-8（_check_tool_scripts.py）。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "backend/app/api/v1/shipper.py"
CHECK = ROOT / "_tools/qa/_check_address_default_restore.py"

original = SRC.read_bytes()
orig_sha = hashlib.sha256(original).hexdigest()
text = original.decode("utf-8")

COUNT_BLOCK = (
    "    others_default = db.scalar(\n"
    "        select(func.count())\n"
)

MUTATIONS = [
    ("① 删掉「查别人有没有当默认」整块（无条件设回默认）",
     COUNT_BLOCK + "        .select_from(ShipperAddress)\n        .where(\n"
     "            ShipperAddress.shipper_id == current.id,\n"
     "            ShipperAddress.is_deleted.is_(False),\n"
     "            ShipperAddress.is_default.is_(True),\n"
     "            ShipperAddress.id != a.id,\n"
     "        )\n    )\n    if not others_default:\n        a.is_default = True\n",
     "    a.is_default = True\n"),
    ("② 改成「只要别人也不是默认之外的任何情况都设回」——去掉条件",
     "    if not others_default:\n        a.is_default = True\n",
     "    if True:\n        a.is_default = True\n"),
    ("③ 查询不排除自己（id != a.id 去掉）",
     "            ShipperAddress.id != a.id,\n", ""),
    ("④ 查询不排除回收站里的地址",
     "            ShipperAddress.is_deleted.is_(False),\n", ""),
    ("⑤ 删除时不再清默认标记（R11-F4 老洞回来）",
     "    a.is_default = False\n", ""),
    ("⑥ 不再 import func（查询会直接炸）",
     "from sqlalchemy import func, select", "from sqlalchemy import select"),
]


def run_check():
    p = subprocess.run([sys.executable, "-X", "utf8", str(CHECK)], cwd=str(ROOT),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


red = 0
problems = []
for name, old, new in MUTATIONS:
    if text.count(old) != 1:
        problems.append("%s：锚点在源码里出现 %d 次（应为 1）" % (name, text.count(old)))
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
