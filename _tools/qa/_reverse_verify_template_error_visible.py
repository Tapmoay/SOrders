# -*- coding: utf-8 -*-
"""BUG-0031（TA-07）反向验证：把修复逐条弄坏，判据必须变红；末尾逐字节还原。"""
import hashlib, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/OrderTemplateFormScreen.kt"
CHECK = ROOT / "_tools/qa/_check_template_error_visible.py"

original = SRC.read_bytes()
orig_sha = hashlib.sha256(original).hexdigest()
text = original.decode("utf-8")

MUTATIONS = [
    ("① 删掉底栏那行红字", "                    FormErrorLine(vm.error)\n", ""),
    ("② 把底栏红字挪到保存键之后",
     "                    FormErrorLine(vm.error)\n                    Row(",
     "                    Row("),
    ("③ 去掉 state = listState", "                state = listState,\n", ""),
    ("④ 去掉 rememberLazyListState()", "    val listState = rememberLazyListState()\n", ""),
    ("⑤ 去掉 LaunchedEffect(vm.error) 整块",
     "    LaunchedEffect(vm.error) {\n        if (vm.error != null) {\n            val last = listState.layoutInfo.totalItemsCount - 1\n            if (last >= 0) listState.animateScrollToItem(last)\n        }\n    }\n", ""),
    ("⑥ 滚到第 0 行而不是末尾", "animateScrollToItem(last)", "animateScrollToItem(0)"),
    ("⑦ 末尾下标算错（不减 1）", "totalItemsCount - 1", "totalItemsCount"),
    ("⑧ 删掉列表末尾那行同款提示", "                item { FormErrorLine(vm.error) }\n", ""),
]

def run_check():
    p = subprocess.run([sys.executable, "-X", "utf8", str(CHECK)], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")

red = 0
problems = []
for name, old, new in MUTATIONS:
    if text.count(old) != 1:
        problems.append("%s：锚点在源码里出现 %d 次（应为 1）" % (name, text.count(old)))
        continue
    SRC.write_bytes(text.replace(old, new, 1).encode("utf-8"))
    code, out = run_check()
    if code == 0:
        problems.append("%s：判据**没有**变红（注入没被发现）" % name)
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