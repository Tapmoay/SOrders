# -*- coding: utf-8 -*-
"""照片水印：**当场拍的两行、事后补的三行**（2026-10-06，台账 L-22 / CHG-0061）。

## 用户原话
> 「如果有些信息是**补上去的照片**的话，会有一些水印……那个水印就是会显示时间，
>   然后这个照片是**被人补过的**，就是说是补过的照片就可以了。」（m00542）

## 为什么这件事必须有机器的判据
「补过的那张要看得出来是补过的」落地形态就是**水印多一行字** —— 没有编译期约束、
没有后端字段、没有接口契约：少画那一行，App 照跑、照片照传、单子照完，
只有**留痕**失真（事后从相册挑一张传上来，与当场拍的看起来一模一样）。
而这条链路上有三种典型的「悄悄退化」，全都没人会当场发现：
- 补拍标识的文案被改掉 / lines() 的 tag 分支被删 ⇒ 两张照片又长得一样；
- 送达照那条路被顺手加上标识 ⇒ **每一单都变成"事后补录"**（反向失真，比少一行更糟）；
- 相册那条路把**原图**传上去（水印画在一份没人传的副本上）⇒ 界面上传的还是没水印的图。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界解决不了**。水印是**客户端拍照那一刻**画在像素上的：
后端从头到尾只收到一个 JPEG（uploadOrderAddressImage），文件里没有任何「补拍」字段，
数据库也不该为一行字水印加一列。所以判据只能守客户端这一侧的三件跨文件口径 ——
**文案只有一份**（android/.../util/WatermarkText.kt）、**地点口径只有一处**
（android/.../ui/order/OrderDetailScreen.kt 的 watermarkText()）、
**三条路各画各的、互不串味**（送达照两行 / 两条补图路三行）。任意一件丢了，这次的需求就只做了一半。

用法：
    python _tools/qa/_check_place_photo_watermark.py
    python _tools/qa/_check_place_photo_watermark.py --list
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))

from _airepo import refuse_if_injecting  # noqa: E402
from _check_product_card_single_source import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
TESTDIR = ROOT / "android/app/src/test/java/com/tapmoay/sorders"

WMTEXT = AND / "util/WatermarkText.kt"
WATERMARK = AND / "util/Watermark.kt"
SCREEN = AND / "ui/order/OrderDetailScreen.kt"
VM = AND / "ui/order/OrderDetailViewModel.kt"
WMTEXT_TEST = TESTDIR / "util/WatermarkTextTest.kt"

DOC = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"

REVERSE = "_tools/qa/_reverse_verify_place_photo_watermark.py"

#: 本刀的立项与收口（判据自己盯住它 —— 文档烂掉了没人说话）
CHG_ID = "CHG-0061"
CHG_DOC = ROOT / "docs/changes/CHG-0061.md"
REGISTRY = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"

#: 九节标题逐字（光数圈码会被正文里的「①」蒙混过去）
CHG_SECTIONS = (
    "## ① 六问",
    "## ② Must Change / Must Not Change",
    "## ③ Boundary",
    "## ④ Behavior Contract",
    "## ⑤ Data Contract",
    "## ⑥ CHG 专章",
    "## ⑦ 测试",
    "## ⑧ 证据",
    "## ⑨ 关闭",
)

#: 补拍标识的文案（用户没定用词，是我们自决的 —— 改字必须是有意的）
MAKEUP = "补拍 · 事后补录"

#: 地点取不到时的兜底（与「拍照送达」同一条口径）
FALLBACK = "送达地点"

#: 扫到的界面文件数下限（防目录改名/搬走之后「一个文件都没扫到」也算过）
MIN_UI_FILES = 100


def read(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def code(p: Path) -> str:
    return strip_comments(read(p))


def subs(text: str, needle: str) -> int:
    """子串出现次数。

    ⚠️ 这里**故意用纯字符串**而不是正则：锚点里全是 ( ) . ? 这类正则元字符
    （如 Watermark.process(File(rawPath), out, wmText)），当正则用会静默匹配到别的东西。
    """
    return text.count(needle)


def first(text: str, needle: str) -> int:
    """needle 首次出现的位置（取不到返回一个很大的数 —— 让"谁在前"的比较判红）。"""
    i = text.find(needle)
    return i if i >= 0 else 10 ** 9


def after(text: str, needle: str, span: int) -> str:
    i = text.find(needle)
    return text[i : i + span] if i >= 0 else ""


def fn_body(src: str, sig: str) -> str:
    """sig 那个函数/代码块的**函数体**（按大括号配对，不是按行猜）。"""
    i = src.find(sig)
    if i < 0:
        return ""
    b = src.find("{", i)
    if b < 0:
        return ""
    depth = 0
    for j in range(b, len(src)):
        ch = src[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[b : j + 1]
    return ""


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print(f"  [OK]   {label}")
        else:
            self.fails.append(label + (f" —— {detail}" if detail else ""))
            print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))

    def report(self, title: str) -> int:
        print()
        print(f"===== {title} =====")
        print(f"  通过 {self.passes} 项，失败 {len(self.fails)} 项")
        for f in self.fails:
            print(f"    - {f}")
        return 1 if self.fails else 0


def main() -> int:
    if refuse_if_injecting("照片水印（补拍标识）检查"):
        return 1

    c = Checker()
    print("照片水印「当场拍的两行、事后补的三行」：2026-10-06（台账 L-22 / CHG-0061）")

    ui_files = list(AND.rglob("*.kt"))
    c.ok(
        f"扫到的界面文件数 ≥ {MIN_UI_FILES}（防目录搬走 → 判据空转）",
        len(ui_files) >= MIN_UI_FILES,
        f"实际 {len(ui_files)}",
    )

    wmtext = code(WMTEXT)
    wm = code(WATERMARK)
    screen = code(SCREEN)
    vm = code(VM)
    doc = read(DOC)

    # ---- 1. 文案与行数只有一份出处 ----
    c.ok(
        "WatermarkText.kt 在，而且是**纯的**（一个 android.* 都不 import ⇒ JVM 单测跑得起来）",
        bool(wmtext) and "import android" not in wmtext,
        f"读不到 {WMTEXT.name}，或者它 import 了 android.*",
    )
    c.ok(
        f"补拍标识的文案就这一处（MAKEUP_TAG = \"{MAKEUP}\"）",
        f'const val MAKEUP_TAG = "{MAKEUP}"' in wmtext,
        after(wmtext, "MAKEUP_TAG", 60).strip(),
    )
    c.ok(
        "地点兜底也在同一个文件（界面各处不许自己再抄一份）",
        f'const val LOCATION_FALLBACK = "{FALLBACK}"' in wmtext,
    )
    c.ok(
        "地点上限仍是 60 个字",
        # ⚠️ 必须卡词边界：子串匹配会让 "600" 照样绿
        bool(re.search(r"const val LOCATION_MAX = 60\b", wmtext)),
        after(wmtext, "const val LOCATION_MAX", 40).strip(),
    )
    c.ok(
        "lines() 的签名：tag 可选、默认 null（既有那条调用一个字都不用改）",
        bool(re.search(r"fun lines\(time: String, locationText: String, tag: String\? = null\): List<String>", wmtext)),
    )
    body = fn_body(wmtext, "fun lines(")
    c.ok(
        f"lines() 摘得出来（{len(body)} 字，防抽取失效变成一条永远绿的检查）",
        len(body) >= 80,
        f"实际 {len(body)} 字",
    )
    c.ok(
        "两行是底：时间 + 地点（地点空 / 全空白 → 兜底）",
        "mutableListOf(time, locationText.take(LOCATION_MAX).ifBlank { LOCATION_FALLBACK })" in body,
    )
    c.ok(
        "第三行只在 tag 非空白时加（补拍那张才有；当场拍的不许被标成补拍）",
        "if (!tag.isNullOrBlank()) out += tag" in body,
    )
    c.ok(
        "第三行**追加在最后**（不是插在中间 —— 绘制顺序就是列表顺序）",
        first(body, "out += tag") > first(body, "mutableListOf("),
    )
    owners = sorted(p.name for p in AND.rglob("*.kt") if MAKEUP in code(p))
    c.ok(
        f"整个客户端里写这个文案的只有它一个（实际：{'、'.join(owners) or '一个都没有'}）",
        owners == ["WatermarkText.kt"],
    )
    tag_owners = sorted(p.name for p in AND.rglob("*.kt") if "补拍" in code(p))
    c.ok(
        f"「补拍」两个字在代码里也只出现在这里（别处一律走 MAKEUP_TAG 常量）：{'、'.join(tag_owners) or '无'}",
        tag_owners == ["WatermarkText.kt"],
    )
    fb_owners = sorted(p.name for p in AND.rglob("*.kt") if FALLBACK in code(p))
    c.ok(
        f"「{FALLBACK}」也只在一个文件里（界面各处不再自己写兜底）：{'、'.join(fb_owners) or '无'}",
        fb_owners == ["WatermarkText.kt"],
    )

    # ---- 2. 图形层只管「怎么画」，不再管「画哪几行」 ----
    c.ok(
        "Watermark.kt 不再自己拼行（没有 listOf(time… 了）",
        "listOf(time" not in wm,
    )
    c.ok(
        "画图那层改成问 WatermarkText 要行",
        "WatermarkText.lines(time, locationText, tag)" in wm,
    )
    pbody = fn_body(wm, "fun process(")
    c.ok(
        "老链路一个字没改坏：摆正 → 缩放（两步在 ImageOps）→ 画 → JPEG 85（在 ImageOps.saveJpeg）",
        "ImageOps.loadOriented(srcFile.absolutePath, MAX_EDGE)" in pbody
        and "drawWatermark(scaled, locationText, tag)" in pbody
        and "ImageOps.saveJpeg(marked, outFile)" in pbody,
    )
    c.ok("内存位图那条路（markBitmap）在", "fun markBitmap(" in wm)
    mbody = fn_body(wm, "fun markBitmap(")
    c.ok(
        "markBitmap 用的是同一套画法与同一个压缩质量（相机那条路不必先落盘再读回来）",
        "ImageOps.scaleDown(src, MAX_EDGE)" in mbody
        and "drawWatermark(scaled, locationText, tag)" in mbody
        and "ImageOps.saveJpeg(marked, outFile)" in mbody,
    )
    c.ok(
        "⛔ markBitmap 不回收调用方的位图（那是系统相机回调给的）",
        "if (scaled !== src) scaled.recycle()" in mbody and "src.recycle()" not in mbody,
    )

    # ---- 3. 三条路各画各的（同一件事的三个入口，串味最难发现）----
    wbody = fn_body(screen, "fun watermarkText(): String")
    c.ok(f"地点口径只有一处：OrderDetailScreen 的 watermarkText()（{len(wbody)} 字）", len(wbody) >= 80)
    c.ok(
        "口径逐字还是那条老路：逆地理 → 订单地址 → 兜底",
        "GeoResolver.resolveSync(context, loc.lat, loc.lng)" in wbody
        and "order?.addressDetail ?: WatermarkText.LOCATION_FALLBACK" in wbody,
    )
    c.ok(
        "三条路都调它（一处定义 + 三处调用）",
        subs(screen, "watermarkText()") >= 4,
        f"实际 {subs(screen, 'watermarkText()')} 处",
    )
    c.ok(
        "送达照那条路**逐字未变**（仍是 Watermark.process(File(rawPath), out, wmText)）",
        "Watermark.process(File(rawPath), out, wmText)" in screen,
    )
    c.ok(
        "⛔ 送达照那条路**没有**补拍标识（当场拍的绝不带标签 —— 否则每一单都成了补录）",
        "Watermark.process(File(rawPath), out, wmText," not in screen,
    )
    album = fn_body(screen, "val placePhotoPicker = rememberLauncherForActivityResult(")
    c.ok(f"相册补图那段摘得出来（{len(album)} 字）", len(album) >= 200, f"实际 {len(album)} 字")
    c.ok(
        "相册那条路：先画水印（带补拍标识）再上传",
        "Watermark.process(f, marked, watermarkText(), WatermarkText.MAKEUP_TAG)" in album,
    )
    c.ok(
        "⛔ 相册那条路上传的是**打过水印的那个文件**（不是原图 —— 否则水印画在没人传的副本上）",
        "vm.uploadPlacePhoto(marked)" in album and "uploadPlacePhoto(f)" not in album,
    )
    c.ok("相册那条路挪到了 IO 线程（压图不卡主线程）", "Dispatchers.IO" in album)
    cam = fn_body(screen, "val placePhotoCamera = rememberLauncherForActivityResult(")
    c.ok(f"相机补图那段摘得出来（{len(cam)} 字）", len(cam) >= 150, f"实际 {len(cam)} 字")
    c.ok(
        "相机那条路：内存位图直接画（带补拍标识）",
        "Watermark.markBitmap(bmp, f, watermarkText(), WatermarkText.MAKEUP_TAG)" in cam,
    )
    c.ok(
        "⛔ 相机那条路不再「先落盘一张无水印的 jpg」（否则画的是这张、传的是那张）",
        "Bitmap.CompressFormat.JPEG, 88" not in cam and "uploadPlacePhoto(f)" in cam,
    )
    c.ok("相机那条路也在 IO 线程上", "Dispatchers.IO" in cam)
    c.ok(
        "上行接口一个字没改（后端不用动：仍是 uploadPlacePhoto(File)）",
        "fun uploadPlacePhoto(file: java.io.File)" in vm,
    )

    # ---- 4. 单测（图形对象测不了，所以把「画哪几行」钉在纯函数上）----
    t = read(WMTEXT_TEST)
    c.ok("单测在：android/app/src/test/.../util/WatermarkTextTest.kt", bool(t))
    c.ok(
        "单测把文案钉死（改字必须连测试一起改）",
        f'assertEquals("{MAKEUP}", WatermarkText.MAKEUP_TAG)' in t,
    )
    c.ok(
        "单测钉住「当场拍的只有两行」（送达照那条链路的行为不变）",
        'WatermarkText.lines("2026-10-06 12:30:00", "杭州市余杭区仓前街道 1 号")' in t,
    )
    c.ok(
        "单测钉住「补拍那张三行，且标识在最后一行」",
        "assertEquals(3, ls.size)" in t and "WatermarkText.MAKEUP_TAG, ls.last()" in t,
    )
    c.ok(
        "单测钉住兜底与截断（空 → 兜底；超长 → 60 字）",
        f'"{FALLBACK}"' in t and '"长".repeat(60)' in t,
    )
    c.ok(
        "单测钉住「空 tag 等于没传」（空白不许被误判成补拍）",
        'WatermarkText.lines("2026-10-06 12:30:00", "某地", "")' in t,
    )

    # ---- 5. 设计规范 + 反向验证 ----
    c.ok(
        "设计规范里记着这条（否则下一个人会以为补拍那张也该长两行）",
        "### 4.26" in doc and MAKEUP in doc and "WatermarkText" in doc,
        "06_DESIGN_SYSTEM.md 里没记这条",
    )
    c.ok(
        "这条红线配了反向验证脚本",
        (ROOT / REVERSE).exists(),
        f"找不到 {REVERSE}",
    )

    # ---- 6. 接线：CHG 文档 / 登记簿 / 工作声明 ----
    chg = read(CHG_DOC)
    c.ok(
        "CHG 文档在，且标题就是这一条（文件名 → 正文 ID 一致）",
        bool(chg) and f"{CHG_ID} ·" in chg.splitlines()[0],
        f"找不到 {CHG_DOC.name}，或者第一行标题里没有 {CHG_ID}",
    )
    c.ok(
        f"文档九节齐全（docs/changes/{CHG_DOC.name}）",
        all(s in chg for s in CHG_SECTIONS),
        "文档缺节（_check_dev_spec.py 也会红）",
    )
    c.ok(
        f"登记簿里有 {CHG_ID} 这一行（整行，不是一个链接里的字样）",
        bool(re.search(r"^\|\s*[\x60]?" + CHG_ID + r"[\x60]?\s*\|", read(REGISTRY), re.M)),
        "没登记（别人不知道这个 ID 用掉了）",
    )
    # ⚠️ 这里卡的是「一整条条目标题」，不是「文件里出现过这个字样」：
    #   实现提交那段自己就会写 \`docs/changes/CHG-0061.md\` —— 只要标题被改名、别处还留着字样，
    #   用 \`CHG_ID in read(CLAIM)\` 这种写法照样绿（反向验证 ⑲ 就是照这个打的）。
    c.ok(
        f"工作声明里有 {CHG_ID} 这一条（一整条条目标题，不是别处的字样）",
        bool(re.search(r"^### .*" + CHG_ID + r"\b", read(CLAIM), re.M)),
        f"AI_WORK_CLAIM.md 里没有以 {CHG_ID} 为条目的那一行",
    )

    if "--list" in sys.argv:
        print()
        print("  == 它到底在查什么 ==")
        print("     · 文案/兜底/上限只有一份：util/WatermarkText.kt（纯函数，不 import android.*）")
        print("     · lines()：两行是底（时间 + 地点，空则兜底、超长截到 60），第三行只在 tag 非空白时追加到最后")
        print("     · 「补拍」、「补拍 · 事后补录」、「送达地点」三个字面量在整个客户端只出现在那一个文件里")
        print("     · 图形层只负责画：process 仍是 EXIF → 缩放 → 画 → JPEG 85；新增 markBitmap（内存位图，不回收 src）")
        print("     · 地点口径只有一处：OrderDetailScreen 的 watermarkText()，三条路都调它")
        print("     · 送达照那条路逐字未变且**不带**标识；相册那条路先画后传（传的是打过水印的那个文件）")
        print("     · 相机那条路不再先落盘无水印 jpg；两条补图路都在 Dispatchers.IO 上压图")
        print("     · 单测钉住两行/三行/文案/兜底/截断/空 tag；设计规范 §4.26 记着这条；反向验证脚本在")
        print(f"     · 接线：{CHG_DOC.name} 九节齐全 / 登记簿里一整行 / 工作声明里有这一条")

    return c.report("照片水印「当场拍的两行、事后补的三行」")


if __name__ == "__main__":
    sys.exit(main())
