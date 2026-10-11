# -*- coding: utf-8 -*-
"""判据：账号分类必须**按身份自动推导**，不许再有人工挑分类的第二条路。

R4-BOUNDARY-JUSTIFICATION: 这条判据守的是"分类是身份的投影"这条业务口径 —— 它不允许出现
第二个决定分类的地方（用户案例：分类写着"批发商"、身份却是货主，于是在批发商管理里被筛出来）。
它只读源码文本，不需要数据库、不依赖运行时。
"""
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ⚠️ 根目录必须从 __file__ 推：写死检出位置的话，本机跑得通、CI 上那个路径不存在 →
#    这个判据会变成恒 SKIP（_tools/qa/_check_tool_scripts.py 专门盯这一条）。
R = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
fails = []


def read(rel):
    with io.open(os.path.join(R, rel), encoding="utf-8", newline="") as f:
        return f.read()


svc = read(os.path.join("backend", "app", "services", "user_category.py"))
users = read(os.path.join("backend", "app", "api", "v1", "users.py"))

# ① 唯一实现存在，且六个分类名都在
for name in ("派单员", "货主", "批发商", "小车司机", "大车司机", "挂车司机"):
    if name not in svc:
        fails.append("auto_category 里缺分类名：" + name)
if "def auto_category(" not in svc:
    fails.append("没有 auto_category 这一个唯一实现")

# ② 建号与更新都走它（两处都要出现调用）
calls = len(re.findall(r"auto_category\(", users))
if calls < 2:
    fails.append("users.py 里 auto_category 的调用点少于 2 处（建号 + 更新都要）: %d" % calls)

# ③ ⛔ 不许再出现"把 body.category 直接写库"的老写法
if re.search(r"category\s*=\s*\(body\.category", users):
    fails.append("users.py 里还在用 body.category 直接当分类写库（人工挑分类的第二条路）")
if re.search(r"u\.category\s*=\s*\(body\.category", users):
    fails.append("users.py 更新路径里还在手工写 u.category")

# ④ 车型三档映射与 App 侧的老口径一致（认不出当大车）
if "DRIVER_LARGE_CATEGORY" not in svc or "DRIVER_TRAILER_CATEGORY" not in svc:
    fails.append("车型三档常量不全")

# ⑤ 回填脚本在（老数据要能一次纠正）
if not os.path.exists(os.path.join(R, "_tools", "ops", "_fix_user_categories.py")):
    fails.append("没有一次性回填脚本 _tools/ops/_fix_user_categories.py")

print("== 账号分类自动推导判据 ==")
if fails:
    for f in fails:
        print("  ❌ " + f)
    print("FAIL = %d" % len(fails))
    raise SystemExit(1)
print("  ✅ 唯一实现 + 建号/更新两处调用 + 没有人工写库的第二条路 + 回填脚本在位")
print("PASS = 5")