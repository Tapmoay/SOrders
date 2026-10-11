"""红线：AI **贴图写对象**（FEAT-0024，2026-10-11）—— 图由 App 钉进卡，不是模型编出来的。

R4-BOUNDARY-JUSTIFICATION:
  允许变的是「谁有权把一张**已经贴进聊天**的图挂到对象上」（新增三条写动作：
  products.image / location.image / address.image），它们是 **Extension**；
  不许变的是两条核心约定：
  · **上传的文件来自用户这一轮贴的图**（AiImageInbox），模型只说「用第几张」——
    模型给不出字节，所以它永远不该也不能够自己造一张图；
  · **多图字段的三档语义**（缺省=不改 / [] =清空 / 非空=整体替换）与**撤回锚**
    （payload 里带着那个键的旧值，旧 URL 一直在服务器上，撤回只是把旧值写回去）。
  两件坏起来都静默：模型凭空挑一张图，卡片上看不出；旧值没钉进 payload，撤回按钮点了没反应。

## 判据
1. 三条动作声明 + 入总表 + 三个 handler 注册；
2. 没贴图就拒绝（不许发一张没有图的空卡）；多张没点名 → 列候选；序号越界 → 说清有几张；
3. 追加/替换**问不清就拒绝**（parseMode 的 else 必须是 null，不许猜）；
4. 多图三档语义在数据源那一层仍然成立；
5. 卡片写清「给谁 / 第几张 / 替换还是追加」；
6. `_tools/ai/_write_coverage.py` 的 EXCLUDED 里，商品图与地点图两条**已经开出**（不再是不做），
   而且**没有任何**理由还留着「模型给不出文件」那句化石话；
7. 单测清单自己算（数 @Test），低于下限就报错。

用法：python _tools/qa/_check_ai_image_actions.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_single_source import code_only  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
AND_TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai"
COVERAGE = ROOT / "_tools/ai/_write_coverage.py"

MIN_KT_TESTS = 10

FAILS: list[str] = []
CHECKS = 0


def ok(cond: bool, msg: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        FAILS.append(msg)


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def kt_code(src: str) -> str:
    out: list[str] = []
    in_block = False
    for ln in src.splitlines():
        s = ln.strip()
        if in_block:
            if "*/" in s:
                in_block = False
            continue
        if s.startswith("/*"):
            if "*/" not in s:
                in_block = True
            continue
        if s.startswith("//"):
            continue
        out.append(ln)
    return "\n".join(out)


def main() -> int:
    aw = kt_code(read(AND / "ai/AiWrite.kt"))
    img = kt_code(read(AND / "ai/AiWriteImage.kt"))
    handler = kt_code(read(AND / "ai/AiWriteImageHandlers.kt"))
    svc = kt_code(read(AND / "ai/AiWriteService.kt"))
    ds = kt_code(read(AND / "ai/AiWriteDataSource.kt"))
    cov = code_only(read(COVERAGE))

    # ---- ① 三条动作 ----
    for name, api in (("PRODUCTS_IMAGE", "products.image"),
                      ("LOCATION_IMAGE", "location.image"),
                      ("ADDRESS_IMAGE", "address.image")):
        ok('const val ' + name in aw, "AiWrite.kt 少了动作常量 " + name)
        ok('"' + api + '"' in aw, "动作 id 不再是 " + api)
    ok("AiWriteImage.ACTIONS" in aw, "AiWrite.kt 的动作总表没并进 AiWriteImage.ACTIONS")
    for name in ("AiWrites.PRODUCTS_IMAGE", "AiWrites.LOCATION_IMAGE", "AiWrites.ADDRESS_IMAGE"):
        ok("ImageWriteHandler(" + name in svc, "AiWriteService.kt 没注册 " + name + " 的处理器")

    # ---- ② 防呆：没图就拒绝 / 多张要候选 / 越界说清 ----
    ok("聊天里没有图片" in img and "请先在聊天框里贴一张图" in img,
       "pickOrReject 不再拒绝「这次没有图」（会发出一张没有图的空卡）")
    ok("不要自己挑一张" in img, "多张图没点名时不再要求模型去问用户，而是自己挑一张")
    ok("candidates" in handler or "e.candidates" in img or "labels," in img,
       "多张图 / 越界时不再把候选带出去")
    ok("没有第 " in img, "点了一个不存在的序号时不再如实说现在有几张")

    # ---- ③ 追加还是替换：问不清就拒绝 ----
    seg = img.split("fun parseMode(", 1)[-1].split("fun ", 1)[0]
    ok("else -> null" in seg, "parseMode 开始猜「追加还是替换」了（两者后果不一样：前者旧的还在）")
    ok("缺少 mode" in handler, "处理器不再要求把追加/替换问清")

    # ---- ④ 多图三档语义 ----
    ok("null -> null" in ds, "数据源里「缺省 = 不改」那一档不见了")
    ok("JsonNull -> emptyList()" in ds, "数据源里「[] = 清空」那一档不见了")
    ok("urlsOf(" in ds, "数据源不再用 AiWriteImage.urlsOf 读多图字段（会出现第二套解析）")

    # ---- ⑤ 卡片写清给谁 / 第几张 / 替换还是追加 ----
    ok("cardFor(" in img, "不再由一处同时产出摘要/明细/payload（卡片可能与写下去的不是同一条）")
    ok("KEY_IMAGE_DATA" in img, "payload 里不再钉图片字节（用户点确认时可能传的是另一张）")
    ok("currentText(" in img, "卡片上不再说「原来是哪几张」")
    ok("kind.cn" in img and "kind.imageCn" in img, "卡片不再写清是给谁的哪种图")

    # ---- ⑥ EXCLUDED 表：化石必须清干净 ----
    ok("EXCLUDED" in cov, "覆盖率脚本里找不到 EXCLUDED 表（判据会空转）")
    for dead in ('("POST", "products/{}/image")', '("POST", "shipper/locations/image")'):
        ok(dead not in cov, "EXCLUDED 里还留着 " + dead + " —— 这两条已经开出 AI 动作了，留着就是化石")
    ok("模型给不出文件" not in cov, "EXCLUDED 里还留着「模型给不出文件」那句老前提（2026-10-11 已被推翻）")
    for keep in ('("POST", "orders/{}/address-image")', '("POST", "orders/{}/delivery-photos")'):
        ok(keep in cov, "上传类里 " + keep + " 那条「不做」理由被误删了（它仍要有一条写下来的理由）")

    # ---- ⑦ 单测清单自己算 ----
    tsrc = read(AND_TEST / "AiWriteImageTest.kt")
    n = len(re.findall(r"^\s*@Test", tsrc, re.M))
    ok(n >= MIN_KT_TESTS, "AiWriteImageTest 只有 " + str(n) + " 个 @Test（下限 " + str(MIN_KT_TESTS) + "）")
    ok("pickOrReject_withoutImage" in tsrc, "单测里没有「没贴图就拒绝」那一条")
    ok("imagesAfter_" in tsrc, "单测里没有追加/替换的语义对账")

    ok(CHECKS >= 25, "断言只有 " + str(CHECKS) + " 条（下限 25）")

    if FAILS:
        print("❌ AI 贴图写对象被破坏：")
        for f in FAILS:
            print("   - " + f)
        return 1
    print("✅ AI 贴图写对象（FEAT-0024）：" + str(CHECKS) + " 条断言全过 —— "
          "三条动作在位、" + str(n) + " 例单测、没图就拒绝、追加/替换不猜、EXCLUDED 里没有化石。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
