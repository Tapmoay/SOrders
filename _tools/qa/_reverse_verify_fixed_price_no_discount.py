# -*- coding: utf-8 -*-
"""CHG-0109 / FEAT-0016 反向验证：把「商品固价」逐条弄坏，判据必须变红；末尾逐字节还原。"""
import hashlib
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
BATCH = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductBatchScreen.kt"
WRITE = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWrite.kt"
MASTER = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteMasterData.kt"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai/AiWriteTest.kt"
CHECK = ROOT / "_tools/qa/_check_fixed_price_no_discount.py"

FILES = [BATCH, WRITE, MASTER, TEST]
ORIG = {p: p.read_bytes() for p in FILES}

MUTATIONS = [
    (BATCH, "① 批量页改成改上下架（不再改 no_discount）",
     "updateProduct(p.id, ProductUpdateRequest(noDiscount = fixed))",
     "updateProduct(p.id, ProductUpdateRequest(isActive = fixed))"),
    (BATCH, "② 批量页把「固价（不打折）」入口拿掉",
     'ActionChip("固价（不打折）", vm.acting)', 'ActionChip("固价占位", vm.acting)'),
    (BATCH, "③ 批量页文案不再说「价格照旧可以改」",
     "价格照旧可以改", "价格会一起被冻住"),
    (WRITE, "④ AI 动作常量删掉",
     'const val PRODUCTS_SET_NO_DISCOUNT = "products.set_no_discount"',
     'const val PRODUCTS_SET_NO_DISCOUNT_X = "products.set_no_discount"'),
    (MASTER, "⑤ AI 参数名改掉（不再是 no_discount）",
     'boolField("no_discount", "固价还是不固价"', 'boolField("fixed_price", "固价还是不固价"'),
    (MASTER, "⑥ AI 卡片混进「价格锁死」这种错说法",
     "⛔ 它的价格照旧可以改 —— 这条不是「价格不能变」。",
     "⛔ 设成固价后它的价格就锁死了 —— 这条不是「价格不能变」。"),
    (TEST, "⑦ 动作数棘轮退回 175",
     "AiWrites.ALL.size <= 176", "AiWrites.ALL.size <= 175"),
]


def run_check():
    p = subprocess.run([sys.executable, "-X", "utf8", str(CHECK)], cwd=str(ROOT),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode


def restore():
    for p, b in ORIG.items():
        p.write_bytes(b)


red = 0
problems = []
for path, name, old, new in MUTATIONS:
    src = path.read_bytes().decode("utf-8")   # ⛔ 不用 read_text：它会把 CRLF 统一成 LF，锚点就对不上
    if src.count(old) != 1:
        problems.append("%s：锚点出现 %d 次（应为 1）" % (name, src.count(old)))
        continue
    src = src.replace(old, new, 1)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(src)
    if run_check() == 0:
        problems.append("%s：判据**没有**变红" % name)
    else:
        red += 1
        print("  ✔ %s → 判据变红" % name)
    restore()

same = all(hashlib.sha256(p.read_bytes()).hexdigest() == hashlib.sha256(b).hexdigest() for p, b in ORIG.items())
print()
print("注入 %d 条，变红 %d 条；还原后逐字节一致：%s" % (len(MUTATIONS), red, same))
if problems:
    print("❌ 有问题：")
    for p in problems:
        print("   -", p)
    sys.exit(1)
if red != len(MUTATIONS) or not same:
    print("❌ 没做到「每条注入都红 + 逐字节还原」")
    sys.exit(1)
print("✅ %d/%d 都红了，且文件逐字节还原。" % (red, len(MUTATIONS)))
