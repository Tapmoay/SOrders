#!/usr/bin/env python
"""反向验证：把 FEAT-0024（AI 贴图写对象）一件一件弄坏，_check_ai_image_actions.py 必须当场报红。

为什么非得有它：这一族**坏起来全是安静的** —— 把某个 handler 的注册删掉（动作在清单里、
点下去没人接）、把「没图就拒绝」那句删掉（会发出一张没有图的空卡）、让 parseMode 开始猜
「追加还是替换」（两者后果不一样：前者旧的还在）、把多图那一档语义改掉、payload 里不再钉
图片字节（用户点确认时传的可能是另一张）……**没有一条会报错**。

⚠️ 注入点选在**判据真正读的地方**（那几行代码本身或它所在的文件），不是"看起来相关"的地方。
每条注入跑完都**逐字节还原**，末尾再核对一遍。

R4-BOUNDARY-JUSTIFICATION: 这份脚本只改**图片类写动作这一族的实现**（Kotlin 的处理器注册、
图片工具对象、数据源的三档读法、覆盖率脚本的理由表、单测），不碰后端契约、订单/账本字段、
权限模型、数据库结构。它验证的判据本身也在同一层（"这一族有没有越过边界自己造图"）；
把这条边界下沉成接口参数治不了它要防的病（病在"模型手里根本没有字节"这件事上）。

用法：python _tools/qa/_reverse_verify_ai_image_actions.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_ai_image_actions.py"

AI = "android/app/src/main/java/com/tapmoay/sorders/ai"
WRITE_REL = AI + "/AiWrite.kt"
IMG_REL = AI + "/AiWriteImage.kt"
SVC_REL = AI + "/AiWriteService.kt"
DS_REL = AI + "/AiWriteDataSource.kt"
COV_REL = "_tools/ai/_write_coverage.py"
TEST_REL = "android/app/src/test/java/com/tapmoay/sorders/ai/AiWriteImageTest.kt"


def kill(s: str, old: str, n: int = 1) -> str:
    """删掉 old。找不到就当场抛 —— 静默跳过等于这条注入根本不存在。"""
    if s.count(old) < n:
        raise AssertionError("注入锚点找不到：" + old[:80])
    return s.replace(old, "", n)


def guess_mode(s: str) -> str:
    """把 parseMode 里的「认不出就返回 null」改成「认不出就当追加」—— 这就是"猜"。"""
    i = s.index("fun parseMode(")
    j = s.index("else -> null", i)
    return s[:j] + "else -> true" + s[j + len("else -> null"):]


CASES = [
    (
        "把地点图那个 handler 的注册删掉（动作在清单里，点下去没人接）",
        SVC_REL,
        lambda s: kill(s, "ImageWriteHandler(AiWrites.LOCATION_IMAGE, AiWriteImage.Kind.LOCATION, ds, store),\n"),
        "没注册 AiWrites.LOCATION_IMAGE",
    ),
    (
        "把「请先在聊天框里贴一张图」那句删掉（用户不知道该干什么）",
        IMG_REL,
        lambda s: s.replace("请先在聊天框里贴一张图", "请先贴一张图"),
        "pickOrReject 不再拒绝",
    ),
    (
        "让 parseMode 开始猜「追加还是替换」（旧的还在 vs 旧的被摘掉，后果不一样）",
        IMG_REL,
        guess_mode,
        "开始猜「追加还是替换」了",
    ),
    (
        "把多图字段的「[] = 清空」那一档改掉（用户清不空，或者一改就清空）",
        DS_REL,
        lambda s: s.replace("JsonNull -> emptyList()", "JsonNull -> null", 1),
        "「[] = 清空」那一档不见了",
    ),
    (
        "把「模型给不出文件」那条化石理由塞回 EXCLUDED（老前提已经不成立了）",
        COV_REL,
        lambda s: s.replace(
            "EXCLUDED: dict[tuple[str, str], str] = {",
            'EXCLUDED: dict[tuple[str, str], str] = {\n'
            '    ("POST", "products/{}/image"): "上传类：要一个文件，模型给不出文件（v3.7 永久排除）",',
            1,
        ),
        "留着就是化石",
    ),
    (
        "payload 里不再钉图片字节（用户点确认时传的可能是另一张图）",
        IMG_REL,
        lambda s: s.replace("KEY_IMAGE_DATA", "KEY_IMAGE_BYTES"),
        "payload 里不再钉图片字节",
    ),
    (
        "把商品图那条动作 id 改掉（AI 清单里那一行指向一个不存在的动作）",
        WRITE_REL,
        lambda s: s.replace('const val PRODUCTS_IMAGE = "products.image"', 'const val PRODUCTS_IMAGE = "products.picture"', 1),
        "动作 id 不再是 products.image",
    ),
    (
        "把图片那一族的单测全注释掉（这一族再没有测试钉着）",
        TEST_REL,
        lambda s: s.replace("@Test", "// @Test"),
        "个 @Test（下限",
    ),
]


def run_check() -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    print("== 0. 前提：源码完好时判据必须是绿的 ==")
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时判据就是红的 —— 先修绿再谈反向验证。")
        print(out[-3000:])
        return 2
    print("✅ 判据在完好源码上全绿")

    originals: dict[str, bytes] = {}
    ok = 0
    print("\n== 注入 %d 条：每条都必须让判据当场变红 ==" % len(CASES))
    try:
        for i, (label, rel, mutate, expect) in enumerate(CASES, 1):
            path = ROOT / rel
            original = originals.setdefault(rel, path.read_bytes())
            crlf = b"\r\n" in original
            text = original.decode("utf-8")
            mutated = mutate(text)
            if mutated == text:
                print("❌ [%d/%d] %s：注入没有改变任何字节（等于没注入）" % (i, len(CASES), label))
                return 1
            data = mutated.encode("utf-8")
            if crlf:
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            path.write_bytes(data)
            try:
                code2, out2 = run_check()
                hit = code2 != 0 and expect in out2
                print(("✅" if hit else "❌") + " [%d/%d] %s —— %s"
                      % (i, len(CASES), label,
                         "判据变红，且命中了那句话" if hit
                         else "判据没红 / 没命中那句话（exit=%d）" % code2))
                if not hit:
                    print(out2[-2500:])
                    return 1
                ok += 1
            finally:
                path.write_bytes(original)
    finally:
        for rel, original in originals.items():
            path = ROOT / rel
            if path.read_bytes() != original:
                path.write_bytes(original)
                print("⚠️  %s 没有逐字节还原，已强制还原" % rel)

    dirty = [rel for rel, original in originals.items() if (ROOT / rel).read_bytes() != original]
    print("\n逐字节还原核对：改了 %d 个文件，脏 = %d" % (len(originals), len(dirty)))
    if dirty or ok != len(CASES):
        print("❌ 反向验证不完整（通过 %d/%d）" % (ok, len(CASES)))
        return 1
    print("✅ 反向验证通过：%d/%d 条注入全部被抓，且源码逐字节还原。" % (ok, len(CASES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
