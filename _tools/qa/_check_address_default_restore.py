# -*- coding: utf-8 -*-
"""BUG-0032（测试台账 TA-14）：常用地址恢复时要**把默认标记还回来**（但不抢别人的）。

判据（静态锚点 + 行为）：
  1. restore_address 里必须查「这段期间有没有别人当上默认」；
  2. 查出来是 0 才把它设回默认（不抢别人后来的选择）；
  3. 删除时**仍然**把 is_default 清掉（R11-F4：默认标记不能留在看不见的行上）；
  4. 三件事都要有单测钉着（backend/tests/test_address_default_restore.py 的核心用例）。

R4-BOUNDARY-JUSTIFICATION: 这一单加的是**一个新的扩展点**（恢复路径上的一个默认标记回填），
核心区只碰一个既有端点内的纯追加分支（restore_address 里多查一次；delete_address 的清理保持原样），
地址归属、隔离语义、接口形状一条都没改。边界解决不了 —— 病是「软删时清掉的标记没人还回来」，
而正解的另一半是**时间语义**：只有这段期间没人当上默认才设回去（否则就抢了别人后来的选择）。
「别人当没当默认」是运行时状态，不是类型属性；写成 service 层的通用规则又会把「谁先谁后」藏起来，
所以只能靠一条机器判据把五个条件（计数 / is_default / is_deleted / id != 自己 / shipper_id 隔离）
连同三个单测一起钉在 restore_address 那一段里。

用法：
  python _tools/qa/_check_address_default_restore.py             # 查主工作树
  python _tools/qa/_check_address_default_restore.py <另一棵树>   # 用来跑「改前必红」
"""
import re
import subprocess
import sys

# 判据/反验会打 ✅/❌ —— GBK 控制台下必须自己把 stdout 钉成 UTF-8（_check_tool_scripts.py）。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
SRC = ROOT / "backend/app/api/v1/shipper.py"
TEST = ROOT / "backend/tests/test_address_default_restore.py"

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

ok(SRC.is_file(), "找不到 backend/app/api/v1/shipper.py")
ok(re.search(r"from sqlalchemy import .*\bfunc\b", text) is not None, "没有 import func")

# 只取 restore_address 这一段
m = re.search(r"def restore_address\(.*?(?=\n@router|\ndef |\Z)", text, re.S)
body = m.group(0) if m else ""
ok(bool(body), "找不到 restore_address")

m_del = re.search(r"def delete_address\(.*?(?=\n@router|\ndef |\Z)", text, re.S)
body_del = m_del.group(0) if m_del else ""

# ① 恢复时查「别人有没有当默认」
ok("others_default" in body, "restore_address 里没有查「别人是不是已经当了默认」")
ok("func.count()" in body, "没有用 func.count() 数别人的默认地址")
ok("ShipperAddress.is_default.is_(True)" in body, "查询没有按 is_default 过滤")
ok("ShipperAddress.is_deleted.is_(False)" in body, "查询没有排除回收站里的地址")
ok("ShipperAddress.id != a.id" in body, "查询没有排除自己（会被自己的旧标记骗到）")
ok("ShipperAddress.shipper_id == current.id" in body, "查询没有按当前用户隔离（会看到别人的地址）")

# ② 只有「没人当默认」才设回去
ok(re.search(r"if not others_default:\s*\n\s*a\.is_default = True", body) is not None,
   "不是「没人当默认才设回默认」——写成无条件设回会抢用户后来的选择")
ok(body.count("a.is_default = True") == 1, "设默认的分支不唯一")

# ③ 删除时仍要清掉默认标记（老不变量）
ok(re.search(r"a\.is_default = False", body_del) is not None,
   "delete_address 不再清 is_default（R11-F4：默认标记会留在看不见的行上）")

# ④ 单测钉着
ok(TEST.is_file(), "缺 backend/tests/test_address_default_restore.py")
t = TEST.read_text(encoding="utf-8", errors="replace") if TEST.is_file() else ""
ok("test_restore_puts_default_back_when_nobody_claimed_it" in t, "缺「没人当默认 → 还回来」的用例")
ok("test_restore_does_not_steal_someone_elses_default" in t, "缺「别人当了默认 → 不抢」的用例")
ok("test_deleted_address_never_keeps_the_default_flag" in t, "缺「删除时必须清默认标记」的用例")

print("PASS =", PASS)
if FAIL:
    print("❌ 以下锚点不成立：")
    for f in FAIL:
        print("   -", f)
    sys.exit(1)
print("✅ 全部 %d 项通过：恢复常用地址时，没人当默认就把默认还回来、有人当了就不抢，删除时仍然清标记（BUG-0032 / TA-14）。" % PASS)
