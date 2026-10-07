"""点开大图那一下：双指缩放 + 保存到相册，而且**全库只有一份预览**（CHG-0044 / 台账 L-03）。

## 用户报的现象（2026-10-06，台账 L-03）
「点一下确实放大了，但要**支持双指/双手独立缩放**（有时候拍得比较远，要放大才能看清），
**并且图片要支持下载**」。

## 机制（这一条为什么不是"顺手加两个按钮"）
1. 订单详情页 2026-10-06 之前**自己写了一份**大图弹层（OrderDetailScreen.kt 里的
   Dialog + AsyncImage），只有"点开、再点关闭" —— 与 ui/common/ImagePreview.kt 里
   那句 ⛔「全库唯一一处，不要在每个页面各写一个」直接冲突。后果是可数的：
   地址页与下单页点开的预览能左右翻页，详情页点开的不能。
2. 全仓**零**手势缩放（detectTransformGestures 在改动前 0 命中）：照片是 72dp 的缩略图
   拍下来的，拍得远的门牌 / 单号在"刚好铺满屏幕"的倍数下仍然看不清。
3. 全仓**没有**保存图片的实现：util/ExportUtil.kt 那份 saveExportFile 的目录
   （Downloads/SOrders报表）与 MIME（xlsx）当时都是写死的（CHG-0078 v3.34 才把这两个值
   提成常量 EXPORT_SUBDIR / MIME_XLSX，**落点与 MIME 一个字没变**），
   所以另写了 saveImageToGallery（落 Pictures/SOrders / image/jpeg）。

## 为什么这条必须有机器的判据
这一条**全是"没报错但也没发生"的毛病**：
- 谁都可以再写第三份预览（编译器非常乐意）；
- 谁都可以把 .pointerInput { detectTapGestures } 换回 .clickable { onDismiss() } ——
  编译通过、点一下也确实能关，只有在**拖动 / 双指缩放的中途抬手**时才会"图被关了"；
- 保存图片可以只写 Q+ 那一条分支（Build.VERSION.SDK_INT 是运行期分支，
  编译器不会因为少写了 else 就说一个字），而本 App **minSdk 26** ⇒ Android 8/9 上
  就是"保存失败"；
- 保存按钮可以顺手画在本地 File 那一张上（它本来就在这台手机里，"下载"它没有意义）。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
缺的那一层是**手势的运行时语义**与**"唯一一份"这个约定**：
「这一串指针事件是"单击关闭"还是"拖动 / 双指缩放"」由运行期的位移与速度决定 ——
类型系统、Lint 与编译器都看不见手指；.clickable 与 detectTapGestures 在类型上完全等价，
前者甚至更短更"直观"（这也是当初为什么会写成那样）。
同理，"预览全库只有一份"是**结构约定**：ImagePreviewDialog 是个普通 @Composable，
任何页面都能再写一个同名的、或者在本地拼一个 Dialog + AsyncImage，编译器不会有意见。
运行期分支（Q+ / Q 以下）同理：少写一条分支只会在**特定系统版本**上静默失败。
所以判据只能钉在源码结构与常量上：能不能回到 1×、有没有两条系统分支、
点空白与拖动是不是同一套手势、以及**全仓是不是只有一处**在做这件事。
反向破坏用例见 _reverse_verify_image_preview.py
（改回 clickable / 去掉缩放 / 去掉 Q 以下分支 / 抄一份新的预览页 … + 还原后逐字节比对）。
静默空转保护：MIN_KT = 100 与"必须数到那 5 个关键文件"（目录被搬走就红，不许"扫了 0 个也全绿"）。

## 判据（每条都能被反向验证弄红）
1. 全仓**只有一处** fun ImagePreviewDialog(，且三个页面都用 rememberImagePreview()；
   详情页代码里**没有**自写的 Dialog( 弹层（AlertDialog 不算）；
2. 缩放做进那一份里：detectTransformGestures、graphicsLayer、coerceIn(MIN_SCALE, MAX_SCALE)，
   且 MIN_SCALE == 1f（必须能回到原图）、MIN < DOUBLE_TAP <= MAX；翻页时归位（remember(index)）；
3. 「点任意处关闭」不再用 .clickable（拖动中途抬手不会再把预览关掉）；
   放大时单击＝先回 1×，只有 1× 时才 onDismiss()；拖动有边界（clampPan）；
4. 保存到相册：只给服务端那张图（as? String）画按钮，走 resolveStaticUrl + 共享
   NetworkDns.okHttp（**不许**新建 OkHttpClient()）+ IO 线程 + 成败各有 Toast；
5. util/ExportUtil.kt：saveImageToGallery 有 Q+（MediaStore / image/jpeg /
   Pictures/SOrders / IS_PENDING 两步）与 Q 以下（公开目录 + MediaScannerConnection.scanFile）
   两条分支；**没有动** saveExportFile 的目录与 MIME；
6. 详情页把两处调用收口到唯一那一份：onPhotoClick = openPhoto、preview.openStaticPaths(...)、
   preview.Show()；PlacePhotoStrip / DeliveryPhotosSection 的签名没动（只换弹层，不换调用形态）；
7. 看大图能左右滑动翻页（CHG-0070 / 台账 L-37）：阈值是个纯函数（ui/common/ImageSwipe.kt，
   横滑超过宽度 18% 才翻、到头即停、没量到宽度不翻），预览页在**抬手之后**（根 Box 上那个
   只看不吃的 Initial 观察者）才定夺，1× 时横滑是"翻页的预备动作"、放大后才是平移
   （贴到边界继续拖也算待翻页 ⇒ 不存在"放大后滑不动"）；两颗箭头到头即停、首/末张不画，
   源码里**不许**再有 % models.size 那种环绕写法；
8. 商品图只加「点图看大图」（CHG-0070 / 台账 L-37）：热区规则只有一处
   （Modifier.productImageClickable，空图不给热区），三处调用点各只传这一张
   （⇒ 没有箭头 / 计数 / 翻页）；商品**编辑页**那颗 168dp 不动（它点下去是「重新选图」）。

用法：python _tools/qa/_check_image_preview.py
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
PREVIEW = AND / "ui/common/ImagePreview.kt"
EXPORT = AND / "util/ExportUtil.kt"
DETAIL = AND / "ui/order/OrderDetailScreen.kt"
ADDRESS = AND / "ui/shipper/AddressScreen.kt"
CREATE = AND / "ui/shipper/OrderCreateScreen.kt"

# ---- CHG-0070（台账 L-37）：看大图能左右滑动翻页 / 商品图点图看大图 ----
SWIPE = AND / "ui/common/ImageSwipe.kt"
SWIPE_TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/common/ImageSwipeTest.kt"
CARDKIT = AND / "ui/common/ProductCardKit.kt"
PRODUCTS = AND / "ui/dispatcher/ProductsScreen.kt"
PICKER = AND / "ui/common/ProductPicker.kt"
CHECKLIST = AND / "ui/common/ProductCheckList.kt"
FORM = AND / "ui/dispatcher/ProductFormScreen.kt"

#: 全仓至少要有这么多 .kt（防"目录被搬走 → 一个都没扫到 → 全绿"）。
MIN_KT = 100

#: 必须真的数到这几个文件（少一个就说明目录结构变了，判据要跟着改）。
REQUIRED_FILES = [PREVIEW, EXPORT, DETAIL, ADDRESS, CREATE]

#: CHG-0070 新增 / 改动的关键文件（少一个也要红）
REQUIRED_FILES_0070 = [SWIPE, SWIPE_TEST, CARDKIT, PRODUCTS, PICKER, CHECKLIST, FORM]


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


def code_only(t: str) -> str:
    """去掉块注释与行注释（保留换行数，好让行号还对得上）。

    为什么要这样：这些文件里有大段**说明"从前错在哪"**的注释（Dialog(onDismissRequest… 那种），
    判据要抓的是**代码里**还有没有人这么写。
    """
    t = re.sub(r"/\*[\s\S]*?\*/", lambda m: chr(10) * m.group(0).count(chr(10)), t)
    return re.sub(r"//[^\n]*", "", t)


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（被改名/搬走了？这条判据要跟着改）")
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def float_const(t: str, name: str) -> float | None:
    m = re.search(rf"private const val {name} = ([\d.]+)f", t)
    return float(m.group(1)) if m else None


def line_of(t: str, needle: str) -> int:
    i = t.find(needle)
    return 0 if i < 0 else t[:i].count(chr(10)) + 1


def main() -> int:
    c = Checker()
    preview = read(PREVIEW)
    export = read(EXPORT)
    detail = read(DETAIL)
    address = read(ADDRESS)
    create = read(CREATE)
    pv = code_only(preview)
    ex = code_only(export)
    dt = code_only(detail)

    print("== 1. 大图预览全库只有一份，三个页面都在用它 ==")
    kts = sorted(AND.rglob("*.kt"))
    c.ok(f"扫到 {len(kts)} 个 .kt（>={MIN_KT}，防目录被搬走时空转）", len(kts) >= MIN_KT, f"实际 {len(kts)}")
    impls = []
    for p in kts:
        t = code_only(read(p))
        for m in re.finditer(r"fun ImagePreviewDialog\(", t):
            impls.append(f"{p.relative_to(AND).as_posix()}:{t[:m.start()].count(chr(10)) + 1}")
    c.ok("全仓只有一处 fun ImagePreviewDialog(", len(impls) == 1, "；".join(impls))
    for label, txt in (("订单详情页", detail), ("地址页", address), ("下单页", create)):
        c.present(f"{label}用 rememberImagePreview()", txt, r"= rememberImagePreview\(\)")
    c.absent("详情页不再自己拼一个匿名 Dialog 弹层（AmapPickerDialog 那种有名字的对话框不算）",
             dt, r"(?<![\w.])Dialog\(")
    c.absent("详情页不再有 previewUrl 那份本地状态", dt, r"\bpreviewUrl\b")

    print("\n== 2. 缩放手势做进那一份里（双指 / 双击 / 归位）==")
    c.present("双指缩放：detectTransformGestures", pv, r"detectTransformGestures \{ _, pan, zoom, _ ->")
    c.present("缩放落到 graphicsLayer（不重排布局）", pv, r"\.graphicsLayer \{[\s\S]{0,200}?scaleX = scale")
    c.present("倍数被夹在上下限之间", pv, r"\(scale \* zoom\)\.coerceIn\(MIN_SCALE, MAX_SCALE\)")
    mn = float_const(preview, "MIN_SCALE")
    mx = float_const(preview, "MAX_SCALE")
    db = float_const(preview, "DOUBLE_TAP_SCALE")
    c.ok("MIN_SCALE 就是 1f（能回到「整张图刚好放进屏幕」）", mn == 1.0, f"实际 {mn}")
    c.ok("MAX_SCALE 在 2x-20x 之间（够看清门牌号）", mx is not None and 2.0 <= mx <= 20.0, f"实际 {mx}")
    c.ok("MIN < 双击倍数 <= MAX（双击不会一下顶到上限）",
         mn is not None and mx is not None and db is not None and mn < db <= mx,
         f"MIN={mn} / DOUBLE_TAP={db} / MAX={mx}")
    c.present("双击 1x <-> 2.5x（不是「双击就一直放到最大」）",
              pv, r"onDoubleTap = \{[\s\S]{0,260}?scale = DOUBLE_TAP_SCALE")
    c.present("翻页时缩放归位（remember(index)）",
              pv, r"var scale by remember\(index\) \{ mutableStateOf\(MIN_SCALE\) \}")
    c.present("位移也归位", pv, r"var offset by remember\(index\) \{ mutableStateOf\(Offset\.Zero\) \}")

    print("\n== 3. 「点任意处关闭」不再跟拖动打架 ==")
    c.absent("根 Box 不再用 .clickable 关预览（拖动中途抬手会把图关掉）", pv, r"\.clickable\b")
    c.present("改用 detectTapGestures（手势自己分得清单击还是拖动）", pv, r"detectTapGestures\(")
    # ⚠️ 这两条必须**只认 onTap 那一段**：onDoubleTap 里也有一段一模一样的
    #    \`if (scale > MIN_SCALE) { scale = MIN_SCALE; offset = Offset.Zero }\` ——
    #    不把它俩分开，"双击那段还在"就会被当成"单击那段也还在"（反向验证抓到过这一条）。
    # ⚠️ 必须用「第一个 }，」收口，不能用「换行 + }，」收口：注入成单行
    #    \`onTap = { onDismiss() },\` 时，"换行 + }，"要一路找到 onDoubleTap 的收尾，
    #    于是双击那段的 \`if (scale > MIN_SCALE) { scale = MIN_SCALE … } else {\` 也被算进单击里
    #    → 两条都假绿（反向验证抓到过这一条）。
    m_tap = re.search(r"onTap = \{([\s\S]{0,600}?)\},", pv)
    tap = m_tap.group(1) if m_tap else ""
    c.ok("找得到 onTap 的处理体（单击到底干了什么）", bool(tap), "没匹配到 onTap = { … },")
    c.ok("1x 时单击＝关闭（老行为没变）", "onDismiss()" in tap and "else" in tap,
         "onTap 体：" + tap.strip()[:90])
    c.ok("放大后单击＝先回到 1x（不是直接关掉）",
         "if (scale > MIN_SCALE)" in tap and "scale = MIN_SCALE" in tap,
         "onTap 体：" + tap.strip()[:90])
    c.present("拖动有边界：clampPan((n-1)/2 x 边长)", pv, r"box\.width \* \(scale - 1f\) / 2f")
    # ⚠️ 2026-10-07（CHG-0070）这一行改成了**分档**：1× 时横滑是"翻页的预备动作"
    #    （图跟着手指横移，松手由根 Box 上那个观察者定夺翻不翻），放大后才是 clampPan 平移
    #    （贴到边界继续往外拖，多出来的那一截也算待翻页 ⇒ 不会"放大后滑不动"）。
    c.present("1x 档：横滑让图跟着手指走（位移就是这一次的待翻页量）",
              pv, r"if \(next <= MIN_SCALE\) \{[\s\S]{0,240}?swipe \+= pan\.x[\s\S]{0,120}?offset = Offset\(swipe\.coerceIn\(")
    c.present("放大档：照旧 clampPan 平移，只有贴到边界才把多出来的算进待翻页",
              pv, r"val moved = clampPan\(offset \+ pan, next, box\)[\s\S]{0,200}?swipe \+= \(offset \+ pan\)\.x - moved\.x")

    print("\n== 4. 保存到相册（只给服务端的图、走共享 client、成败各有反馈）==")
    c.present("只认服务端路径（本地 File 不给下载按钮）",
              pv, r"val currentPath = models\.getOrNull\(index\) as\? String")
    c.present("按钮只在有服务端路径时才画", pv, r"if \(currentPath != null\) \{\s*\n\s*IconButton\(")
    c.present("先过 resolveStaticUrl 拼全地址", pv, r"val full = resolveStaticUrl\(currentPath\)")
    c.present("复用共享 OkHttpClient（不新建连接池）", pv, r"NetworkDns\.okHttp\.newCall\(")
    c.absent("没有自己 new 一个 OkHttpClient", pv, r"OkHttpClient\(\)")
    c.present("取字节在 IO 线程", pv, r"withContext\(Dispatchers\.IO\) \{ downloadBytes\(full\) \}")
    # ⚠️ 必须紧邻：放宽到"200 字符之内出现过"的话，上面那句取字节的 withContext
    #    就能把它蒙过去（反向验证抓到过这一条）。
    c.present("落盘也在 IO 线程", pv, r"withContext\(Dispatchers\.IO\) \{\s*\n\s*saveImageToGallery\(")
    c.present("成功有反馈（带文件名）", pv, r'"已保存到相册：" \+ saved\.substringAfterLast')
    c.present("失败有反馈（说清是网络）", pv, r'"保存失败，请检查网络后重试"')
    c.present("保存中防重复点（按钮禁用 + 转圈）",
              pv, r"enabled = !saving,[\s\S]{0,1400}?CircularProgressIndicator\(")
    c.present("手势是藏起来的：底部写了一句用法（含左右滑动翻页）",
              preview, r'"双指缩放 / 双击放大 / 左右滑动翻页"')

    print("\n== 5. util/ExportUtil.kt：两条系统分支，且没动既有那个函数 ==")
    c.present("有 saveImageToGallery(context, bytes, fileName): String?",
              ex, r"fun saveImageToGallery\(context: Context, bytes: ByteArray, fileName: String\): String\?")
    c.present("Q+ 走 MediaStore.Images", ex, r"MediaStore\.Images\.Media\.EXTERNAL_CONTENT_URI")
    c.present("Q+ 的 MIME 是 image/jpeg", ex, r'put\(MediaStore\.Images\.Media\.MIME_TYPE, "image/jpeg"\)')
    c.present("Q+ 落 Pictures/SOrders",
              ex, r'put\(MediaStore\.Images\.Media\.RELATIVE_PATH, Environment\.DIRECTORY_PICTURES \+ "/SOrders"\)')
    c.present("Q+ 写完才让别人看见（IS_PENDING 1 -> 0）",
              ex, r"put\(MediaStore\.Images\.Media\.IS_PENDING, 1\)[\s\S]{0,700}?put\(MediaStore\.Images\.Media\.IS_PENDING, 0\)")
    c.present("Q 以下直接写公开目录", ex, r"getExternalStoragePublicDirectory\(Environment\.DIRECTORY_PICTURES\)")
    c.present("Q 以下写完喊媒体扫描（否则相册要等下次开机才看见）",
              ex, r"MediaScannerConnection\.scanFile\(context,")
    c.present("异常一律返回 null（不把失败抛到界面上）", ex, r"catch \(e: Exception\) \{\s*\n\s*null")
    # ⚠️ CHG-0078（v3.34）把这两个写死值提成了常量（ExportedFile 要把 Uri 带回来），
    #    落点与 MIME 一个字没变 —— 所以这里改成"常量值 + 用法"两段一起钉：
    #    常量值被改、或用法被绕过（直接内联另一个目录 / 另一串 MIME），两种都会红。
    c.present("既有 saveExportFile 的目录没被顺手改掉（仍是 Downloads/SOrders报表）",
              ex, r'private const val EXPORT_SUBDIR = "SOrders报表"[\s\S]{0,4000}?'
                  r'Environment\.DIRECTORY_DOWNLOADS \+ "/" \+ EXPORT_SUBDIR')
    c.present("既有 saveExportFile 的 MIME 也没动（仍是 xlsx）",
              ex, r'private const val MIME_XLSX = "application/vnd\.openxmlformats-officedocument\.spreadsheetml\.sheet"'
                  r'[\s\S]{0,4000}?put\(MediaStore\.Downloads\.MIME_TYPE, MIME_XLSX\)')

    print("\n== 6. 详情页：两处调用收口到唯一那一份，并且能在本组里翻页 ==")
    c.present("onPhotoClick 走 openPhoto（不再是 previewUrl = it）", dt, r"onPhotoClick = openPhoto,")
    c.present("回两组里认领（送达照片 / 位置参考图）",
              dt, r"delivery\.contains\(url\) -> delivery\s*\n\s*place\.contains\(url\) -> place\s*\n\s*else -> listOf\(url\)")
    c.present("认领到的落点：openStaticPaths(group, indexOf)",
              dt, r"preview\.openStaticPaths\(group, group\.indexOf\(url\)\)")
    c.present("页面末尾画出弹层 preview.Show()", dt, r"preview\.Show\(\)")
    c.present("PlacePhotoStrip 的回调签名没动（只换弹层，不换调用形态）", dt, r"onPreview: \(String\) -> Unit")
    c.present("DeliveryPhotosSection 的签名也没动",
              dt, r"private fun DeliveryPhotosSection\(urls: List<String>, onPhotoClick: \(String\) -> Unit\)")
    c.present("缩略图仍然照旧回调 onPhotoClick(url)", dt, r"\.clickable \{ onPhotoClick\(url\) \}")
    c.present("openStaticPaths 剔掉空白路径（点空格子不会是一张黑图）",
              pv, r"paths\.withIndex\(\)\.filter \{ it\.value\.isNotBlank\(\) \}")
    c.present("openStaticPaths 内部过 resolveStaticUrl（拼法只有一处）",
              pv, r"fun openStaticPaths\(paths: List<String>, at: Int\) \{[\s\S]{0,500}?resolveStaticUrl\(it\.value\)")
    c.present("预览弹层仍是黑底（照片自己的颜色是主角）", pv, r"Color\.Black\.copy\(alpha = 0\.96f\)")
    c.present("多张时才有左右箭头与计数", pv, r"if \(models\.size > 1\) \{")
    c.present("计数文案仍在（index + 1 / size）", preview, r'"\$\{index \+ 1\} / \$\{models\.size\}"')

    print("\n== 7. 看大图能左右滑动翻页，箭头到头即停（CHG-0070 / 台账 L-37）==")
    # 用户 m01438：「…但是如果我想看下一张照片就是左右滑动不行，非要按按钮。这个不要，
    #   左右滑动这样更方便，就是真实的（相册）操作」；m01486：「不要不要不要循环啊，
    #   就是可以有滑到底的」；m01517：「首章和末章的箭头就是俺藏起来吧」。
    # 阈值单独成一个纯函数（ui/common/ImageSwipe.kt，零 Compose import）：手指验不了，
    # 但"这一次横滑够不够翻一页 / 到头该不该停"能验。
    sw = code_only(read(SWIPE))
    c.present("翻页阈值是个纯函数（JVM 单测能钉边界）",
              sw, r"internal fun swipePageStep\(accumX: Float, boxWidth: Int, atFirst: Boolean, atLast: Boolean\): Int")
    c.present("阈值只有一个数：横滑超过宽度的 18% 才算翻页",
              sw, r"internal const val SWIPE_PAGE_FRACTION = 0\.18f")
    c.present("还没量到宽度 / NaN 一律不翻（布局完之前那一帧）",
              sw, r"if \(boxWidth <= 0 \|\| accumX\.isNaN\(\)\) return 0")
    c.present("往左拖＝下一张、往右拖＝上一张",
              sw, r"return if \(accumX < 0f\) \{[\s\S]{0,80}?if \(atLast\) 0 else 1[\s\S]{0,80}?if \(atFirst\) 0 else -1")
    c.present("到头即停：第一张往右 / 最后一张往左都是 0", sw, r"if \(atFirst\) 0 else -1")
    c.present("预览页真的用了这个纯函数（不是白写一份）",
              pv, r"swipePageStep\([\s\S]{0,160}?accumX = swipe,[\s\S]{0,80}?boxWidth = box\.width,")
    c.present("抬手之后才定夺翻不翻（detectTransformGestures 没有抬手回调）",
              pv, r"awaitEachGesture \{[\s\S]{0,400}?awaitFirstDown\(requireUnconsumed = false\)")
    c.present("那个观察者只走 Initial 通道看", pv, r"awaitPointerEvent\(PointerEventPass\.Initial\)")
    c.absent("观察者一次都不消费（一消费就是「放大后滑不动」）", pv, r"\.consume\(\)")
    c.present("翻页沿用既有的 remember(index) 归位（没有第二套缩放 / 位移状态）",
              pv, r"val step = swipePageStep\([\s\S]{0,600}?index = \(index \+ step\)\.coerceIn\(0, models\.lastIndex\)")
    c.present("翻到头不绕回去：首张不画左箭头", pv, r"if \(index > 0\) \{[\s\S]{0,400}?KeyboardArrowLeft")
    c.present("翻到头不绕回去：末张不画右箭头", pv, r"if \(index < models\.lastIndex\) \{[\s\S]{0,400}?KeyboardArrowRight")
    c.absent("源码里不再有「翻到头绕回去」的环绕写法", pv, r"% models\.size")
    c.present("箭头本身留着（用户要留，只是到头即停）",
              pv, r'contentDescription = "上一张"[\s\S]{0,500}?contentDescription = "下一张"')
    c.present("翻页提示写进底部那句用法里", preview, r"左右滑动翻页")
    test_src = read(SWIPE_TEST)
    c.ok("纯函数有 JVM 单测钉边界（阈值 / 到头即停 / 单张 / 没量到宽度）",
         test_src.count("@Test") >= 8, f"实际 {test_src.count('@Test')} 条")

    print("\n== 8. 商品图只加「点图看大图」（CHG-0070 / 台账 L-37；不加左右滑动）==")
    # 用户 m01517：「商品图点击商品图，他就能查看详情嘛」；m01532：「商品的编辑页面
    #   是重新选图的，它不是查看图片的」⇒ 编辑页那颗 168dp 一个字不动。
    kit = code_only(read(CARDKIT))
    products = code_only(read(PRODUCTS))
    picker = code_only(read(PICKER))
    checklist = code_only(read(CHECKLIST))
    form = code_only(read(FORM))
    c.present("「有没有图、能不能点」这条规则只有一处",
              kit, r"fun Modifier\.productImageClickable\(url: String\?, onClick: \(\) -> Unit\): Modifier")
    c.present("没图就不给热区（点开只有一张黑图）",
              kit, r"if \(url\.isNullOrBlank\(\)\) this else this\.clickable\(onClick = onClick\)")
    m_thumb = re.search(r"fun ProductThumb\([\s\S]*?\n\}\n", kit)
    thumb_body = m_thumb.group(0) if m_thumb else ""
    c.ok("缩略图零件自己仍不带 clickable（能不能点由调用点定）",
         bool(thumb_body) and ".clickable" not in thumb_body, thumb_body.strip()[:80])
    for label, txt, fname in (
        ("商品管理列表（88dp 卡）", products, "ProductsScreen.kt"),
        ("选品行（下单页 / 地址页共用那一份）", picker, "ProductPicker.kt"),
        ("勾选行（批量操作）", checklist, "ProductCheckList.kt"),
    ):
        n_hit = txt.count("productImageClickable(")
        c.ok(f"{label}的商品图能点开看大图", n_hit == 1, f"{fname} 里 {n_hit} 处")
        n_one = len(re.findall(r"openStaticPaths\(listOf(?:NotNull)?\(", txt))
        c.ok(f"{label}只传这一张（单张 ⇒ 没有箭头 / 计数 / 翻页）", n_one == 1, f"{fname} 里 {n_one} 处")
    c.absent("商品编辑页那颗大图不动（它点下去是「重新选图」）", form, r"productImageClickable\(")

    print("\n== 9. 防静默空转 ==")
    missing = [str(p.relative_to(ROOT)) for p in REQUIRED_FILES if not p.exists()]
    c.ok(f"{len(REQUIRED_FILES)} 个关键文件都在", not missing, "；".join(missing))
    missing2 = [str(p.relative_to(ROOT)) for p in REQUIRED_FILES_0070 if not p.exists()]
    c.ok(f"CHG-0070 的 {len(REQUIRED_FILES_0070)} 个关键文件也没少", not missing2, "；".join(missing2))
    i_decl = line_of(dt, "val preview = rememberImagePreview()")
    i_show = line_of(dt, "preview.Show()")
    n_show = dt.count("preview.Show()")
    c.ok("弹层只画一次，且画在预览状态声明之后", n_show == 1 and i_show > i_decl > 0,
         f"声明@{i_decl} / Show@{i_show} / 画了 {n_show} 次")

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
