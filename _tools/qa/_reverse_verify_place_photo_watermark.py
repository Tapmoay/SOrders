# -*- coding: utf-8 -*-
"""反向验证「照片水印（补拍那张多一行）」这条红线**真的会红**（2026-10-06，台账 L-22 / CHG-0061）。

## 为什么这条要反向验证
它的判据是「某个零件必须还在、某个字面量只许有一份、某条路不许带标签」，
这类判据有三种典型失效方式：

1. **判据变成空转**：判据清单指向一个不存在的文件（WMTEXT 指向 WatermarkTextGone.kt）
   之后，它会安静地全绿 —— 整个 Kt 文件读成空串，几条「不许出现」的检查反而更容易过。
2. **只认名字不认形状**：名字还在、语义已经不对。比如 lines() 里那行 tag 分支被删
   （两张照片又长得一模一样）、地点截断被去掉、markBitmap 顺手把调用方的位图回收了
   （系统相机回调给的位图，回收它 = 后面谁用谁崩）—— 常量与函数名一个都没少。
3. **口径被单方面改掉**：送达照那条路被加上补拍标识（**每一单都成了事后补录**，
   比少一行更糟）、相册那条路上传原图（水印画在没人传的副本上）、
   相机那条路退回「先落盘一张无水印 jpg」、地点兜底被界面自己抄第二份 ——
   这几种都是「看起来功能还在」，只有分别注入才知道判据认不认。

⚠️ 快照/还原按**字节**做，跑完逐字节核对（本项目栽过「注入把 bug 留在源码里」）。

R4-BOUNDARY-JUSTIFICATION: 本脚本只读写工作区里的 9 个文件（注入后按字节还原），
不编译、不跑 UI、不连后端 —— 它证明的是「这条红线自己不会说谎」，不是水印本身好不好看。

用法：python _tools/qa/_reverse_verify_place_photo_watermark.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_place_photo_watermark.py"
CHECK_REL = "_tools/qa/_check_place_photo_watermark.py"

AND = "android/app/src/main/java/com/tapmoay/sorders/"
WMTEXT = AND + "util/WatermarkText.kt"
WATERMARK = AND + "util/Watermark.kt"
SCREEN = AND + "ui/order/OrderDetailScreen.kt"
WMTEXT_TEST = "android/app/src/test/java/com/tapmoay/sorders/util/WatermarkTextTest.kt"
DOC = "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
CHG_DOC = "docs/changes/CHG-0061.md"
CHG_REG = "docs/changes/README.md"
CHG_CLAIM = "docs/AI_WORK_CLAIM.md"

#: (说明, 相对路径, 替换函数, 期望在输出里出现的关键词 —— 空串 = 只要非零退出)
CASES: list[tuple[str, str, object, str]] = [
    (
        "① 补拍标识被改字数（两张照片又一样了 —— 这正是用户要的东西）",
        WMTEXT,
        lambda s: s.replace('    const val MAKEUP_TAG = "补拍 · 事后补录"', '    const val MAKEUP_TAG = "补录"', 1),
        "补拍标识的文案",
    ),
    (
        "② lines() 里那行 tag 分支被删（当场拍的和补拍的画出来一模一样）",
        WMTEXT,
        lambda s: s.replace("        if (!tag.isNullOrBlank()) out += tag\n", "", 1),
        "第三行只在 tag 非空白时加",
    ),
    (
        "③ 地点截断被去掉（一张长地址把水印铺满整张图）",
        WMTEXT,
        lambda s: s.replace("locationText.take(LOCATION_MAX)", "locationText", 1),
        "两行是底",
    ),
    (
        "④ 地点上限被改大十倍（判据卡的是词边界，600 不许蒙混过关）",
        WMTEXT,
        lambda s: s.replace("const val LOCATION_MAX = 60", "const val LOCATION_MAX = 600", 1),
        "地点上限",
    ),
    (
        "⑤ 纯函数偷偷 import 了 android.*（JVM 单测从此跑不起来）",
        WMTEXT,
        lambda s: s.replace("object WatermarkText {", "import android.graphics.Color\n\nobject WatermarkText {", 1),
        "纯的",
    ),
    (
        "⑥ 图形那层又自己拼行（文案又冒出第二个出处）",
        WATERMARK,
        lambda s: s.replace(
            "        val lines = WatermarkText.lines(time, locationText, tag)",
            '        val lines = listOf(time, locationText.take(60).ifBlank { "送达地点" })',
            1,
        ),
        "不再自己拼行",
    ),
    (
        "⑦ markBitmap 把调用方的位图回收了（系统相机回调给的位图，回收它 = 谁用谁崩）",
        WATERMARK,
        lambda s: s.replace("        if (scaled !== src) scaled.recycle()", "        src.recycle()", 1),
        "不回收调用方的位图",
    ),
    (
        "⑧ 送达照那条路被加上补拍标识（**每一单都成了事后补录**，比少一行更糟）",
        SCREEN,
        lambda s: s.replace(
            "Watermark.process(File(rawPath), out, wmText)",
            "Watermark.process(File(rawPath), out, wmText, WatermarkText.MAKEUP_TAG)",
            1,
        ),
        "送达照",
    ),
    (
        "⑨ 相册那条路上传的是原图（水印画在一份没人传的副本上）",
        SCREEN,
        lambda s: s.replace("vm.uploadPlacePhoto(marked)", "vm.uploadPlacePhoto(f)", 1),
        "不是原图",
    ),
    (
        "⑩ 相机那条路退回「先落盘一张无水印 jpg」（画的是这张、传的是那张）",
        SCREEN,
        lambda s: s.replace(
            "Watermark.markBitmap(bmp, f, watermarkText(), WatermarkText.MAKEUP_TAG)",
            "f.outputStream().use { bmp.compress(Bitmap.CompressFormat.JPEG, 88, it) }",
            1,
        ),
        "先落盘一张无水印",
    ),
    (
        "⑪ 界面自己抄了一份地点兜底（口径分叉：以后改一处、漏一处）",
        SCREEN,
        lambda s: s.replace("WatermarkText.LOCATION_FALLBACK", '"送达地点"', 1),
        "也只在一个文件里",
    ),
    (
        "⑫ 单测里那条文案断言被掏空（谁把水印文案改了都没人说话）",
        WMTEXT_TEST,
        lambda s: s.replace(
            'assertEquals("补拍 · 事后补录", WatermarkText.MAKEUP_TAG)', "assertEquals(true, true)", 1
        ),
        "把文案钉死",
    ),
    (
        "⑬ 单测把「补拍三行」改成两行（测试自己把需求改小了）",
        WMTEXT_TEST,
        # ⚠️ 这里**不能**限次数：单测里钉「三行」的断言有两处，只换第一处的话判据照样绿
        #    （第一跑就是 [MISS] —— 反向验证自己先把「注入太弱」暴露了出来）
        lambda s: s.replace("assertEquals(3, ls.size)", "assertEquals(2, ls.size)"),
        "补拍那张三行",
    ),
    (
        "⑭ 判据清单指向不存在的文件（红线变成空转）",
        CHECK_REL,
        lambda s: s.replace(
            'WMTEXT = AND / "util/WatermarkText.kt"',
            'WMTEXT = AND / "util/WatermarkTextGone.kt"',
            1,
        ),
        "纯的",
    ),
    (
        "⑮ 反向验证脚本自己不见了（新红线没配反向验证）",
        CHECK_REL,
        lambda s: s.replace(
            'REVERSE = "_tools/qa/_reverse_verify_place_photo_watermark.py"',
            'REVERSE = "_tools/qa/_reverse_verify_place_photo_watermark_gone.py"',
            1,
        ),
        "反向验证",
    ),
    (
        "⑯ 设计规范那一段被改名（下一个人会以为补拍那张也该长两行）",
        DOC,
        lambda s: s.replace("### 4.26", "### 4.27", 1),
        "设计规范里记着这条",
    ),
    (
        "⑰ CHG 文档少一节（收口文档烂掉了没人说话）",
        CHG_DOC,
        lambda s: s.replace("## ⑨ 关闭", "## 九 关闭", 1),
        "文档九节齐全",
    ),
    (
        "⑱ 登记簿那一行被改掉（别人不知道这个 ID 用掉了）",
        CHG_REG,
        lambda s: s.replace("| \u0060CHG-0061\u0060 | CHG |", "| \u0060CHG-0062\u0060 | CHG |", 1),
        "登记簿",
    ),
    (
        "⑲ 工作声明里那条被改名（这条活干完了却查不到）",
        CHG_CLAIM,
        lambda s: s.replace("CHG-0061", "CHG-0063", 1),
        "工作声明",
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({rel for _l, rel, _m, _e in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}

    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        # 按行尾归一后再替换（Windows 上 Kotlin 文件可能是 CRLF），写回时按原样还原
        crlf = b"\r\n" in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            out_txt = mutated.replace("\r\n", "\n")
            if crlf:
                out_txt = out_txt.replace("\n", "\r\n")
            path.write_bytes(out_txt.encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        hit = code != 0 and (not expect or expect in out)
        if hit:
            print(f"  [OK] {label} → 报红")
        else:
            fails.append(f"{label}：注入之后没有按预期报红（退出码 {code}，期望关键词「{expect}」）")
            print(f"  [MISS] {label} → 仍然全绿")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
