# -*- coding: utf-8 -*-
"""商品「固价（不参与打折）」的两个入口：批量操作页 + AI 动作（CHG-0109 / FEAT-0016）。

用户 2026-10-10 报的缺口（逐字）：
  「商品管理呃为什么没有一个叫做涉批量设置里面没有批量估价……要么有那个估价的功能嘛，就是不参与打折」
  「还有 ai 那边也要有这样子的作用……他可以直接接管这个操作」
第二句里他把它叫「固价」（固定价）—— 那和系统里的规范词「不参与打折」是**同一件事**
（products.no_discount）。所以这个判据同时钉两件事：

1. 两个入口都在，而且**都走既有的** PATCH /products/{id}：⛔ 不新增端点、⛔ 不碰任何价格字段；
2. 两处文案说的都是**实现里那一条语义**（订单打折时跳过它；价格照旧可以改；不回溯），
   ⛔ 不许出现「价格锁死 / 不能改价」这种错说法 —— 那会让用户以为改不了价。

R4-BOUNDARY-JUSTIFICATION: 这条只能靠机器判据，扩展点与边界都解决不了它 ——
「不参与打折」的语义在**三个地方各写了一遍**（后端算法 services/order_discount.py、
两个客户端入口的文案），而它们之间**没有任何编译器能对的约束**：后端改语义不会让 App 编译失败，
文案写错也不会让任何测试变红 —— 而错误文案在这里是**有金融后果**的（用户以为价格被锁死，
于是不敢改价；或者以为折扣会照打，于是少收了钱）。所以必须有一条判据把
「入口存在 + 都走既有端点 + 文案与算法一致」这三件事同时钉住。

用法：
  python _tools/qa/_check_fixed_price_no_discount.py              # 主工作树
  python _tools/qa/_check_fixed_price_no_discount.py <另一棵树>    # 跑「改前必红」
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
BATCH = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductBatchScreen.kt"
WRITE = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWrite.kt"
MASTER = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteMasterData.kt"
RES = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiResources.kt"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai/AiWriteTest.kt"
API = ROOT / "backend/app/api/v1/products.py"
ALGO = ROOT / "backend/app/services/order_discount.py"

PASS = 0
FAIL = []


def ok(cond, msg):
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(msg)


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


batch, write, master, res, test, api, algo = (read(p) for p in (BATCH, WRITE, MASTER, RES, TEST, API, ALGO))


def no_comments(s: str) -> str:
    """去掉注释行 —— ⛔ 的规矩本身就是用注释写下来的（"不许写成『价格锁死』"），
    所以"找错说法"这类**反面**锚点只能在**真正的文案**上找，不能把注释也算进去。
    """
    out = []
    for line in s.splitlines():
        t = line.strip()
        if t.startswith("//") or t.startswith("*") or t.startswith("/*"):
            continue
        out.append(line)
    return "\n".join(out)


batch_text = no_comments(batch)
master_text = no_comments(master)

# ---------- 1. 后端：语义只有一条，而且没被这次改动动过 ----------
ok(ALGO.is_file(), "缺 backend/app/services/order_discount.py（折扣算法）")
ok("no_discount" in algo, "算法里没有 no_discount（那这个开关是空的）")
ok("no_discount if False else" not in algo, "占位")

# ---------- 2. 批量操作页 ----------
ok(BATCH.is_file(), "缺 ProductBatchScreen.kt")
ok("fun setNoDiscount(fixed: Boolean)" in batch, "批量页没有 setNoDiscount(...) 这个动作")
ok("updateProduct(p.id, ProductUpdateRequest(noDiscount = fixed))" in batch,
   "批量页没有走既有的 updateProduct + ProductUpdateRequest(noDiscount = …)")
ok('ActionChip("固价（不打折）"' in batch and 'ActionChip("恢复打折"' in batch,
   "批量页缺少「固价（不打折）」/「恢复打折」两个入口")
ok("confirmingFixed" in batch and "AlertDialog(" in batch, "批量页没有二次确认弹层")
ok("价格照旧可以改" in batch, "批量页没写「价格照旧可以改」—— 用户会以为改不了价")
ok("不回溯" in batch, "批量页没写「已经打过的折不回溯」")
ok("锁死" not in batch_text and "不能改价" not in batch_text,
   "批量页的**文案**里出现了「价格锁死/不能改价」这种错说法")
ok("batch-no-discount" not in batch and "no-discount" not in batch,
   "批量页自己造了一个新端点（这个功能走既有 PATCH /products/{id}）")
ok("批量固价（不参与打折）/ 恢复打折" in batch, "页面 docstring 的动作表里没补这一行")

# ---------- 3. AI 动作 ----------
ok('const val PRODUCTS_SET_NO_DISCOUNT = "products.set_no_discount"' in write,
   "AiWrite.kt 里没有 products.set_no_discount 常量")
ok("update(AiWrites.PRODUCTS_SET_NO_DISCOUNT)" in res, "AiResources.kt 没登记这个动作（撤回/快照拿不到）")
ok("id = AiWrites.PRODUCTS_SET_NO_DISCOUNT" in master, "AiWriteMasterData.kt 里没有这个动作的规格")
ok('boolField("no_discount"' in master, "动作参数不叫 no_discount")
ok('put("no_discount", p.bool("no_discount")' in master, "handler 没把 no_discount 写进 payload")
ok('title = "商品固价（不参与打折）"' in master, "动作标题没带上规范词「不参与打折」")
ok("固价" in master and "不参与打折" in master, "文案里没有把用户口语「固价」与规范词对上")
ok("价格照旧可以改" in master, "AI 卡片没写「价格照旧可以改」")
ok("不回溯" in master, "AI 卡片没写「已经打过的折不回溯」")
ok("锁死" not in master_text and "不能改价" not in master_text,
   "AI 卡片的**文案**里出现了「价格锁死/不能改价」这种错说法")
ok("ds.updateProduct(" in master and 'put("is_active"' not in master.split("PRODUCTS_SET_NO_DISCOUNT")[1][:900],
   "固价动作的 handler 里混进了别的字段（只该改 no_discount）")

# ---------- 4. 单测与棘轮 ----------
ok("固价只改 no_discount 且卡片说清" in test, "缺「固价只改 no_discount」的单测")
ok('AiWrites.PRODUCTS_SET_NO_DISCOUNT' in test, "单测没真的调这个动作")
ok("<= 176" in test, "动作数棘轮没跟着抬（新加 1 个动作要留下日期与理由）")
ok("FEAT-0016" in test, "棘轮注释里没写这次加动作的编号")

print("PASS =", PASS)
if FAIL:
    print("❌ 以下锚点不成立：")
    for f in FAIL:
        print("   -", f)
    sys.exit(1)
print("✅ 全部 %d 项通过：商品固价（不参与打折）在批量操作页与 AI 动作两处都能做，"
      "两处都走既有 PATCH /products/{id}，文案与算法语义一致（CHG-0109 / FEAT-0016）。" % PASS)
