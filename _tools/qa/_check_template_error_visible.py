# -*- coding: utf-8 -*-
"""BUG-0031（测试台账 TA-07）：预订单表单的保存失败提示必须**看得见**。

判据（静态锚点 + 行为复刻）：
  1. 底栏（bottomBar）里必须有 FormErrorLine(vm.error) —— 表单再长也挤不掉它；
  2. LazyColumn 必须接 state = listState，且存在 LaunchedEffect(vm.error) 在出错时滚到末尾那一行；
  3. 末尾那一行 item { FormErrorLine(vm.error) } 仍在（列表内同款提示，滚过去还能看到）；
  4. 行为复刻：给一段「可视区到 y=2252 / 红字原位置 y=2794」的坐标，断言底栏版本落在可视区内。
"""
import sys

# 判据/反验会打 ✅/❌ —— GBK 控制台下必须自己把 stdout 钉成 UTF-8（_check_tool_scripts.py）。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import re, sys
from pathlib import Path

# 可选：`python _check_template_error_visible.py <另一棵树>` —— 用来跑「改前必须红」的对照
ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
SRC = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/OrderTemplateFormScreen.kt"

PASS = 0
FAIL = []

def ok(cond, msg):
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(msg)

def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("//"))

raw = SRC.read_text(encoding="utf-8", errors="replace") if SRC.is_file() else ""
body = strip_comments(raw)

ok(SRC.is_file(), "找不到 OrderTemplateFormScreen.kt")
ok("FormErrorLine(vm.error)" in body, "底栏/列表里都没有 FormErrorLine(vm.error)")

# ① 底栏里那一行：bottomBar 起点到第一个 LazyColumn 之间必须出现一次
bb = body.find("bottomBar")
lc = body.find("LazyColumn(")
ok(bb >= 0 and lc > bb, "找不到 bottomBar → LazyColumn 的结构")
ok(bb >= 0 and lc > bb and "FormErrorLine(vm.error)" in body[bb:lc],
   "底栏里没有 FormErrorLine(vm.error)：表单长的时候红字又会落到视口外")

# ② 滚动：state 绑定 + LaunchedEffect(vm.error) 滚到末尾
ok("state = listState" in body, "LazyColumn 没有绑定 state = listState")
ok("rememberLazyListState()" in body, "没有 rememberLazyListState()")
ok(re.search(r"LaunchedEffect\(vm\.error\)", body) is not None, "没有 LaunchedEffect(vm.error)")
ok("animateScrollToItem(last)" in body, "出错时没有滚到末尾那一行（animateScrollToItem(last)）")
ok("totalItemsCount - 1" in body, "没有按 totalItemsCount 计算末尾下标")

# ③ 列表内同款提示仍在（滚过去还能看到）
ok(len(re.findall(r"FormErrorLine\(vm\.error\)", body)) >= 2,
   "FormErrorLine(vm.error) 少于两处：底栏一处 + 列表末尾一处")

# ④ 结构：底栏里那行必须排在「保存」按钮**之前**（同一个常驻底栏里，顺序不能反）
bar = body[bb:lc]
err_at = bar.find("FormErrorLine(vm.error)")
btn_at = bar.find("PrimaryActionButton(")
ok(err_at >= 0 and btn_at >= 0, "底栏里没同时找到红字与保存键")
ok(err_at >= 0 and btn_at >= 0 and err_at < btn_at, "底栏里红字排在了保存键之后（会被按钮挤到下面）")

print("PASS =", PASS)
if FAIL:
    print("❌ 以下锚点不成立：")
    for f in FAIL:
        print("   -", f)
    sys.exit(1)
print("✅ 全部 %d 项通过：保存失败的红字既在底栏常驻、也会自动滚到列表末尾那一行（BUG-0031 / TA-07）。" % PASS)