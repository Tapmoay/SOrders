"""商品照片要能自由框选裁切（CHG-0072 / 台账 L-33）。

## 用户要的（2026-10-07，ref m01347 四句逐字）
①「裁切是**自由的**，是可以自己**选择框选**的，就是我们普通的手机裁切的功能嘛」；
②「可以加一个上传前的**摆正**；**压缩**就不需要了 —— 压缩是我们**自动给它压缩**的」；
③「对于**以前的老图就算了，不需要加个重新裁切的入口**」；
④「就是它上张图片点进去，它**可以重新裁切、也可以选择不裁切**……对那个裁切好的图片进行重新裁切」。

## 这一条为什么必须有机器的判据
全是「没报错但也没发生」的毛病：
- **顺序可以反**：直接拿 BitmapFactory 解出来的原始位图去裁 —— 编译通过、裁也裁了，只有
  **竖拍**照片（EXIF ROTATE_90/270）裁出来是横的（用户在框里选的是一个方向，存下来是另一个）；
- **「不裁切」可以绕过流水线**（原图原样交出去）：看着更"尊重用户"，实际把"自动压缩"这条
  口径丢了（m01347 ②：摆正与压缩是恒做的），4MB 的巨图就这么上行；
- **位图流水线可以再抄第三份**：这个仓库已经栽过一次 —— util/Watermark.kt 原来自己养着
  rotateByExif / scaleDown，谁再抄一份，JPEG 质量与长边上限迟早走散；
- **相册那一步可以又变回「选完直接 vm.pickImage」**：裁切页就永远打不开，而一切都还编译得过；
- **「老图不批量重裁」可以顺手做成一个列表批量入口**：用户明确说不要（m01347 ③）。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
缺的那一层是**顺序**与**出口语义**：
「先摆正再裁」是运行期数据流顺序 —— 类型上 Bitmap 就是 Bitmap，先裁后摆正一样编译得过；
「不裁切 ＝ 仍然摆正 + 压缩」是同一个函数两条分支的**等价性**，类型系统看不见；
「相册选完必须先进裁切页」是导航约定（回调里改成直接交 VM 只会少一行代码）；
而框选手势的几何（角优先于边、最小边粘住不翻面、放大不越界、焦点不动、像素换算取整）是
**连续量的边界**，手指验不了 ⇒ 几何抽成零 android import 的 ui/common/ImageCropGeometry.kt，
由 JVM 单测逐条钉（照 ui/common/ImageSwipe.kt 那个样板）。
所以判据只能钉在源码结构、常量与**唯一性**上：全库几处解码 / 几处读 EXIF / 几处裁切页 /
几个入口，以及那几个出口分别走哪条路。
反向破坏用例见 _reverse_verify_image_crop.py。

## 判据（每条都能被反向验证弄红）
1. 位图流水线全库只有一份（util/ImageOps.kt）：BitmapFactory.decodeFile( 与 ExifInterface( 全仓
   只在那里出现，MAX_EDGE = 2560 / JPEG_QUALITY = 85 只有一处，**摆正在缩之前**；
   util/Watermark.kt 改成调它，自己不再养旋转与缩放；
2. 几何是纯函数（零 android.* / androidx.* import）：铺满居中、夹取按轴分开、缩放夹在 1x-4x、
   捏合焦点不动、命中角优先于边、拖到最小边粘住不翻面、平移贴边停、像素换算四舍五入且至少 1 像素；
3. 裁切页（全仓只有一处 ImageCropDialog）：三个出口（取消 / 不裁切 / 完成）、**不裁切也走同一条
   流水线**（output(null)）、一个 pointerInput 同时管捏合与拖动、位图自己回收、
   **不用 Canvas(**（全库只许图表那个文件用；遮罩 / 白框 / 手柄都是 Box 拼的）；
4. 接线：相册选完**先进裁切页**（回调里不再直接 pickImage，交回 VM 只有「完成」那一处）、
   编辑页那颗 168dp 仍点图＝重新选图、「裁切」是**单张**入口（老图没有批量入口）、
   上传时机与调用形态一个字没改（仍是 vm.uploadIfPicked）；
5. 单测（几何那 22 条）＋ 变更单九节 ＋ 登记簿整行 ＋ 工作声明 ＋ 反验脚本 ＋ 防静默空转。

用法：python _tools/qa/_check_image_crop.py
"""
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
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders"

OPS = AND / "util/ImageOps.kt"
WATERMARK = AND / "util/Watermark.kt"
GEO = AND / "ui/common/ImageCropGeometry.kt"
DIALOG = AND / "ui/common/ImageCropDialog.kt"
FORM = AND / "ui/dispatcher/ProductFormScreen.kt"
FORM_VM = AND / "ui/dispatcher/ProductFormViewModel.kt"
GEO_TEST = TEST / "ui/common/ImageCropGeometryTest.kt"

CHG_ID = "CHG-0072"
CHG_DOC = ROOT / "docs/changes/CHG-0072.md"
REGISTRY = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = "_tools/qa/_reverse_verify_image_crop.py"

#: 九节标题逐字（光数圈码会被正文里的圈码蒙混过去）
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

#: 扫到的 .kt 数下限（防目录改名/搬走之后「一个文件都没扫到」也算过）
MIN_KT = 100

#: 必须真的数到这几个文件（少一个就说明目录结构变了，判据要跟着改）
REQUIRED_FILES = [OPS, WATERMARK, GEO, DIALOG, FORM, FORM_VM, GEO_TEST]

#: 几何那层的对外形状（判据按**整条签名**数，改参数就是改契约）
GEO_SIGNATURES = (
    "internal fun fitWidthFor(aspect: Float, viewW: Float, viewH: Float): Float",
    "internal fun fitTransform(imageW: Int, imageH: Int, viewW: Float, viewH: Float): ViewTransform",
    "internal fun clampTransform(t: ViewTransform, viewW: Float, viewH: Float): ViewTransform",
    "internal fun panTransform(t: ViewTransform, dx: Float, dy: Float, viewW: Float, viewH: Float): ViewTransform",
    "internal fun visibleImageRect(t: ViewTransform, viewW: Float, viewH: Float): ViewRect",
    "internal fun initialCropBox(visible: ViewRect, minSide: Float): ViewRect",
    "internal fun clampCropBox(box: ViewRect, bounds: ViewRect, minSide: Float): ViewRect",
    "internal fun hitCropHandle(box: ViewRect, x: Float, y: Float, slop: Float): CropHandle",
    "internal fun dragCropHandle(",
    "internal fun moveCropBox(box: ViewRect, dx: Float, dy: Float, bounds: ViewRect): ViewRect",
    "internal fun cropToPixels(",
)

#: 单测必须钉住的几条边界（名字就是契约的一部分：改语义必须连名字一起改）
GEO_TEST_CASES = (
    "横图按宽度铺满、上下居中",
    "竖图按高度铺满、左右居中",
    "视口还没量到时不炸",
    "放得超过四倍会被截在四倍",
    "捏合时手指按住的那一点不动",
    "可见图区域只算图本身（不含上下留白）",
    "初始框每边内缩百分之六",
    "框跑到图外会被整体拉回来（尺寸不变）",
    "角比边优先",
    "四条边的中点各认各的",
    "拖角动两条边、拖边只动一条边",
    "框顶到最小边就粘住、不翻面",
    "框里拖动是整块平移、贴边就停",
    "像素换算用四舍五入并夹回图内",
    "框小到亚像素也至少裁一像素",
    "空框与没量到都不裁",
)


def read(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def code(p: Path) -> str:
    return strip_comments(read(p))


def subs(text: str, needle: str) -> int:
    """子串出现次数（故意用纯字符串：锚点里全是 ( ) . ? 这类正则元字符）。"""
    return text.count(needle)


def first(text: str, needle: str) -> int:
    """needle 首次出现的位置（取不到返回一个很大的数 —— 让「谁在前」的比较判红）。"""
    i = text.find(needle)
    return i if i >= 0 else 10 ** 9


def fn_body(src: str, sig: str) -> str:
    """sig 那个函数/代码块的函数体（按大括号配对，不是按行猜）。"""
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

    def present(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is not None, f"没找到 {pattern!r}")

    def absent(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is None, f"命中：{m.group(0)!r}" if m else "")


def main() -> int:
    if refuse_if_injecting("商品照片裁切判据"):
        return 0
    c = Checker()
    ops = code(OPS)
    wm = code(WATERMARK)
    geo = code(GEO)
    dlg = code(DIALOG)
    form = code(FORM)
    vm = code(FORM_VM)

    print("== 1. 位图流水线全库只有一份（读 → 摆正 → 缩 → 裁 → JPEG）==")
    kts = sorted(AND.rglob("*.kt"))
    c.ok(f"扫到 {len(kts)} 个 .kt（>={MIN_KT}，防目录被搬走时空转）", len(kts) >= MIN_KT, f"实际 {len(kts)}")
    for needle, why in (
        ("BitmapFactory.decodeFile(", "解码只有流水线那一处（别处自己解一张，摆正就漏了）"),
        ("ExifInterface(", "读 EXIF 方向只有流水线那一处"),
    ):
        owners = sorted(p.relative_to(AND).as_posix() for p in kts if needle in code(p))
        c.ok(
            f"全仓 {needle} 只出现在 util/ImageOps.kt（{why}）",
            owners == ["util/ImageOps.kt"],
            "；".join(owners) or "一处都没有",
        )
    c.ok("ImageOps 是 object（不是给谁去 new 一份的）", "object ImageOps {" in ops)
    c.present("长边上限只有一处：MAX_EDGE = 2560", ops, r"const val MAX_EDGE = 2560")
    c.present("输出质量只有一处：JPEG_QUALITY = 85", ops, r"const val JPEG_QUALITY = 85")
    c.present("saveJpeg 用的是那个常量（不是又一个写死的 85）", ops, r"Bitmap\.CompressFormat\.JPEG, quality, fos")
    load = fn_body(ops, "fun loadOriented(")
    c.ok(f"loadOriented 摘得出来（{len(load)} 字，防抽取失效变成永远绿的检查）", len(load) >= 60, f"实际 {len(load)} 字")
    c.ok(
        "顺序要紧：先按 EXIF 摆正、再缩（⛔ 不能反过来）",
        first(load, "decodeOriented(path)") < first(load, "scaleDown(oriented, maxEdge)"),
    )
    c.present("摆正读不到 EXIF 就原样返回（不抛）", ops, r"ExifInterface.TAG_ORIENTATION,[\s\S]{0,80}?ORIENTATION_NORMAL")
    crop2file = fn_body(ops, "fun cropToFile(")
    c.ok(f"cropToFile 摘得出来（{len(crop2file)} 字）", len(crop2file) >= 120, f"实际 {len(crop2file)} 字")
    c.ok(
        "「不裁切」（rect == null）也照样走摆正 + 压缩（m01347 ②）",
        "if (rect == null) scaled else crop(scaled, rect)" in crop2file,
    )
    c.ok("自己造的中间件自己回收（不回收调用方传进来的位图）", "if (cropped !== scaled) scaled.recycle()" in crop2file)
    cropb = fn_body(ops, "fun crop(")
    c.ok(f"crop 摘得出来（{len(cropb)} 字）", len(cropb) >= 80, f"实际 {len(cropb)} 字")
    c.ok("裁的矩形自动夹回图内（框越界/亚像素不会抛）", subs(cropb, "coerceIn(") >= 4, f"实际 {subs(cropb, 'coerceIn(')} 处")
    c.present("Watermark 那条路改成问 ImageOps 要流水线", wm, r"ImageOps\.loadOriented\(srcFile\.absolutePath, MAX_EDGE\)")
    c.absent("⛔ Watermark 不再自己养一份 EXIF 旋转", wm, r"ExifInterface")
    c.absent("⛔ Watermark 不再自己养一份缩放", wm, r"Bitmap\.createScaledBitmap")
    c.ok(
        "Watermark 的 MAX_EDGE 指向 ImageOps.MAX_EDGE（不是第二个 2560）",
        "private const val MAX_EDGE = ImageOps.MAX_EDGE" in wm,
    )
    c.ok(
        "磁盘 / 内存位图两条出口都走 ImageOps.saveJpeg（同一个质量）",
        subs(wm, "ImageOps.saveJpeg(") == 2,
        f"实际 {subs(wm, 'ImageOps.saveJpeg(')} 处",
    )

    print("\n== 2. 自由框选的几何是纯函数（零 android / compose import）==")
    c.absent("几何文件不许 import android.*（JVM 单测里会 not mocked）", geo, r"(?m)^import android\.")
    c.absent("也不许 import androidx.*（保持纯函数可测）", geo, r"(?m)^import androidx\.")
    c.present("每边最小框：CROP_MIN_SIDE_DP = 48f", geo, r"CROP_MIN_SIDE_DP = 48f")
    c.present("最大放大倍数：CROP_MAX_ZOOM = 4f", geo, r"CROP_MAX_ZOOM = 4f")
    c.present("手柄热区：CROP_HANDLE_SLOP_DP = 28f", geo, r"CROP_HANDLE_SLOP_DP = 28f")
    c.present("初始框内缩比例：CROP_INITIAL_INSET_FRACTION = 0.06f", geo, r"CROP_INITIAL_INSET_FRACTION = 0\.06f")
    for sig in GEO_SIGNATURES:
        name = sig.split("(")[0].replace("internal fun ", "")
        c.ok(f"几何入口在且只有一份：{name}", subs(geo, sig) == 1, f"实际 {subs(geo, sig)} 处")
    clamp = fn_body(geo, "fun clampTransform(")
    c.ok(
        "夹取按轴分开（等比铺满时本来就有一条轴比视口小，硬 coerce 会抛 IllegalArgumentException）",
        "if (width >= viewW)" in clamp and "else (viewW - width) / 2f" in clamp,
    )
    zoom = fn_body(geo, "fun zoomTransform(")
    c.ok("捏合时手指按住的那一点不动（按实际生效的比例重算偏移）", "val applied = target.width / t.width" in zoom)
    hit = fn_body(geo, "fun hitCropHandle(")
    order = [m.group(0) for m in re.finditer(r"CropHandle\.[A-Z_]+", hit)]
    c.ok(
        "角优先于边（四个角整组排在四条边前面）",
        order[:4]
        == [
            "CropHandle.TOP_LEFT",
            "CropHandle.TOP_RIGHT",
            "CropHandle.BOTTOM_LEFT",
            "CropHandle.BOTTOM_RIGHT",
        ],
        "；".join(order[:6]) or "一个都没扫到",
    )
    drag = fn_body(geo, "fun dragCropHandle(")
    c.ok(f"dragCropHandle 摘得出来（{len(drag)} 字）", len(drag) >= 200, f"实际 {len(drag)} 字")
    c.ok("四个方向夹取前都先用 maxOf 兜住下限（保证 coerceIn 的 lo <= hi，不会抛）",
         subs(drag, "maxOf(") >= 4, f"实际 {subs(drag, 'maxOf(')} 处")
    c.ok(
        "拖到最小边就粘住（上限 = 反向边让出 minSide），⛔ 不翻面",
        "val leftMax = box.right - minSide" in drag and "val bottomMin = box.top + minSide" in drag,
    )
    c.ok("只动被拖的那条边（拖左边不改右边，框才跟手）",
         "if (movesLeft) left =" in drag and "if (movesBottom) bottom =" in drag)
    px = fn_body(geo, "fun cropToPixels(")
    c.ok("像素换算用四舍五入（不是截断）", ".roundToInt()" in px and ".toInt()" not in px)
    c.ok("夹回图内且至少 1 像素（亚像素框也裁得出一张 1x1，不会存空图）",
         "coerceIn(l + 1, imageW)" in px and "coerceIn(tp + 1, imageH)" in px)
    c.ok("框空 / 图没量到 / 尺寸非法一律返回 null（调用方据此走「不裁切」）",
         subs(px, "return null") >= 3, f"实际 {subs(px, 'return null')} 处")

    print("\n== 3. 裁切页：三个出口，一个手势识别器 ==")
    impls = sorted(p.relative_to(AND).as_posix() for p in kts if "internal fun ImageCropDialog(" in code(p))
    c.ok("全仓只有一处 internal fun ImageCropDialog(", impls == ["ui/common/ImageCropDialog.kt"], "；".join(impls) or "一处都没有")
    c.present(
        "签名逐字（源文件 / 输出文件 / 给不给「不裁切」/ 两个回调）",
        dlg,
        r"internal fun ImageCropDialog\(\n    sourcePath: String,\n    outFile: File,\n    allowNoCrop: Boolean = true,\n    onCancel: \(\) -> Unit,\n    onCropped: \(File\) -> Unit,\n\)",
    )
    c.present("读图就走流水线（摆正 + 缩放都在 loadOriented 里）", dlg, r"runCatching \{ ImageOps\.loadOriented\(sourcePath\) \}")
    c.absent("⛔ 裁切页不许自己 BitmapFactory 解码（那就成了先裁后摆正）", dlg, r"BitmapFactory")
    c.present("一个 pointerInput 同时管捏合与拖动（⛔ 不叠 detectTransformGestures）", dlg, r"\.pointerInput\(bitmap, viewport\)")
    c.present(
        "手势循环：awaitEachGesture + 第一下不要求未被消费",
        dlg,
        r"awaitEachGesture \{[\s\S]{0,200}?awaitFirstDown\(requireUnconsumed = false\)",
    )
    c.present("双指 = 缩放", dlg, r"val zoom = event\.calculateZoom\(\)")
    c.present("双指 = 平移（焦点取两指中心）", dlg, r"event\.calculateCentroid\(useCurrent = true\)")
    out = fn_body(dlg, "fun output(")
    c.ok(f"出口函数摘得出来（{len(out)} 字）", len(out) >= 150, f"实际 {len(out)} 字")
    c.ok("出口是同一条流水线：crop（可选）→ saveJpeg", "ImageOps.crop(" in out and "ImageOps.saveJpeg(cut, outFile)" in out)
    c.ok("「不裁切」走的就是 output(null)（= 不裁那一刀，摆正与压缩照做）",
         "TextButton(onClick = { output(null) }, enabled = !saving)" in dlg)
    c.ok("「不裁切」只在 allowNoCrop 时给（编辑态重裁不给它）", "if (allowNoCrop) {" in dlg)
    c.present("「取消」什么都不写（直接回调 onCancel）", dlg, r"TextButton\(onClick = onCancel, enabled = !saving\)")
    # ⚠️ 值必须先抓进局部变量：onDispose 里直接读 \`bitmap\` 读到的是"那一刻"的状态，而 key 变化正是
    #    刚把新图解出来的时刻 —— 会把正在画的那张回收掉（真机崩过一次：recycled bitmap）。
    c.ok(
        "位图归弹层所有：换图 / 走的时候回收（值先抓进局部变量，别回收正在画的那张）",
        "DisposableEffect(bitmap) {" in dlg
        and "val owned = bitmap" in dlg
        and "onDispose { owned?.recycle() }" in dlg
        and "onDispose { bitmap?.recycle() }" not in dlg,
    )
    c.absent("⛔ 弹层里不用 Canvas(（全库只许图表那一个文件用；遮罩/白框/手柄都是 Box 拼的）", dlg, r"Canvas\(")
    c.present("框外压暗：四块遮罩里最上面那块逐字（上边那条）", dlg, r"MaskRect\(0f, 0f, viewport\.width\.toFloat\(\), box\.top\)")
    c.ok("白框与手柄都在（四角 + 四边中点）", subs(dlg, "HandleDot(") == 5 and subs(dlg, "HandleBar(") == 5,
         f"HandleDot {subs(dlg, 'HandleDot(')} / HandleBar {subs(dlg, 'HandleBar(')}")
    c.ok("提示句在（第一次进来得知道怎么动）", "拖动边框圈出要保留的部分" in dlg)
    for fn_name in ("fitTransform(", "initialCropBox(", "visibleImageRect(", "zoomTransform(", "panTransform(",
                    "hitCropHandle(", "dragCropHandle(", "cropToPixels("):
        c.ok(f"几何那份真的用上了：{fn_name.rstrip('(')}", fn_name in dlg)
    c.ok("框内拖动＝整块平移（由 dragCropHandle 转给 moveCropBox，⛔ 不另写一份夹取）",
         "if (handle == CropHandle.INSIDE) return moveCropBox(box, dx, dy, bounds)" in drag)

    print("\n== 4. 接线：选完图先进裁切页，老图只有单张入口 ==")
    c.present(
        "相册入口仍是 GetContent + image/*（_check_product_card_single_source.py 逐字认这行）",
        form,
        r"pickImage\.launch\(\"image/\*\"\)",
    )
    c.ok("选完图先攒成 cropPath（→ 打开裁切页），⛔ 不再直接 pickImage", "cropPath = f.absolutePath" in form)
    c.ok(
        "交回 VM 只有一处，且在裁切页「完成」的回调里（只有摆正/裁过的图才上传）",
        subs(form, "vm.pickImage(f.absolutePath)") == 1
        and "onCropped = { f -> cropPath = null; vm.pickImage(f.absolutePath) }" in form,
        f"实际 {subs(form, 'vm.pickImage(f.absolutePath)')} 处",
    )
    c.ok(
        "裁切页挂在 Scaffold 之外（整屏一层）、且在单位选择弹层之前",
        first(form, "val cropping = cropPath") < first(form, "if (showUnitPicker)"),
    )
    c.present("「裁切」那颗按钮：对现在这张图再框一次", form, r"TextButton\(onClick = onCrop\) \{ Text\(\"裁切\"\) \}")
    c.ok("只有有图时才给「裁切」（空图没什么可裁）", "if (localPath != null || remoteUrl != null) {" in form)
    c.present(
        "商品图块签名多一个 onCrop",
        form,
        r"private fun ProductImageBlock\(\n    localPath: String\?,\n    remoteUrl: String\?,\n    onPick: \(\) -> Unit,\n    onCrop: \(\) -> Unit,",
    )
    c.absent("⛔ 编辑页那颗 168dp 仍是「点图＝重新选图」（不许变成看大图）", form, r"productImageClickable\(")
    c.ok(
        "上传时机与调用形态一个字没改（仍是保存时由 VM 传 localImage，App 侧没有第二条上传路径）",
        subs(vm, "uploadIfPicked(") == 3
        and "private suspend fun uploadIfPicked(id: Long, path: String?) {" in vm
        and "uploadIfPicked(created.id, localImage)" in vm
        and "uploadIfPicked(productId, localImage)" in vm
        and subs(form, "uploadIfPicked") == 0,
        f"VM {subs(vm, 'uploadIfPicked(')} 处 / 表单页 {subs(form, 'uploadIfPicked')} 处",
    )
    c.absent("⛔ 老图没有批量重裁入口（这一页不许出现列表式的重裁动作）", form, r"重裁全部|批量裁切")
    c.present("VM：要一张能给位图流水线读到的本地图", vm, r"suspend fun imageForCrop\(\): String\?")
    c.present("本地草稿优先（对裁好的图再裁一遍，m01347 ④）", vm, r"if \(local != null && File\(local\)\.exists\(\)\) return local")
    c.present("服务端那张走 resolveStaticUrl", vm, r"val url = resolveStaticUrl\(currentImageUrl\) \?: return null")
    c.ok("⛔ 不新建 OkHttpClient（走共享那份 NetworkDns.okHttp）",
         "NetworkDns.okHttp.newCall(" in vm and all("OkHttpClient(" not in code(p) for p in kts))
    c.ok(
        "下到的那张进 cacheDir，文件名带 product_src_ 前缀（好认、好清）",
        'File(container.appContext.cacheDir, "product_src_" + System.currentTimeMillis() + ".jpg")' in vm,
    )
    c.ok("拿不到图返回 null，由调用方给一句提示（不抛）", "catch (_: Exception) {" in vm and "?: return null" in vm)
    c.ok("先看本地草稿、再谈下载（顺序不能反）", first(vm, "if (local != null") < first(vm, "NetworkDns.okHttp.newCall("))
    c.ok("抓图与落盘都在 IO 线程（不卡主线程）", subs(vm, "withContext(Dispatchers.IO)") >= 2,
         f"实际 {subs(vm, 'withContext(Dispatchers.IO)')} 处")

    print("\n== 5. 单测 / 文档 / 反验 / 防静默空转 ==")
    tests = read(GEO_TEST)
    c.ok(f"几何单测在：{GEO_TEST.relative_to(ROOT).as_posix()}", GEO_TEST.exists())
    c.ok(f"单测条数 >= 18（实际 {tests.count('@Test')}）", tests.count("@Test") >= 18)
    c.absent("单测里不许 import android.*（纯 JVM，跑得起来才有意义）", strip_comments(tests), r"(?m)^import android\.")
    for case in GEO_TEST_CASES:
        c.ok(f"单测钉住：{case}", case in tests)
    doc = read(CHG_DOC)
    c.ok(f"变更单在：docs/changes/{CHG_ID}.md", CHG_DOC.exists())
    for sec in CHG_SECTIONS:
        c.ok(f"变更单有这一节：{sec}", sec in doc)
    c.ok("变更单引着用户原话的两个 ref（m01280 提需求 / m01347 定口径）",
         "m01280" in doc and "m01347" in doc)
    c.ok(f"登记簿里有 {CHG_ID} 那一行（整行，不是一个链接里的字样）",
         f"[{CHG_ID}.md]({CHG_ID}.md)" in read(REGISTRY))
    c.ok(f"工作声明里有 {CHG_ID} 这一段", f"**{CHG_ID} " in read(CLAIM))
    c.ok(f"反向验证脚本在：{REVERSE}", (ROOT / REVERSE).exists())
    c.present("这条判据自己写在变更单的判据段里", doc, r"_check_image_crop\.py")
    missing = [p.relative_to(ROOT).as_posix() for p in REQUIRED_FILES if not p.exists()]
    c.ok(f"{len(REQUIRED_FILES)} 个关键文件都在", not missing, "；".join(missing))

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项不通过：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
