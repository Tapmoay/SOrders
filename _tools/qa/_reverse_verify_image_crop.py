"""反向验证：把 CHG-0072（台账 L-33 商品照片自由框选裁切）的红线逐条弄坏，看它们**真的会红**。

为什么这块必须反向验证：这条线几乎全是「没报错但也没发生」的毛病 ——
  · 先裁后摆正（编译通过、裁也裁了，只有**竖拍**照片裁出来是横的）；
  · 「不裁切」偷偷变成「原图原样交出去」（摆正与自动压缩一起丢了，4MB 巨图就这么上行）；
  · 位图流水线被抄第二份（JPEG 质量与长边上限迟早和送达照那条路走散）；
  · 相册选完直接交 VM（裁切页永远打不开，而一切都编译得过）；
  · 「老图不批量重裁」被顺手做成一个列表入口（用户 m01347 ③ 明确不要）。
判据里还有一半是「扫全仓 / 数出现次数」（解码只有一处、裁切页只有一处、几何签名只有一份），
清单如果不验证，就可能因为「目录扫不到 / 集合是空的」而永远绿。所以每一条都要有对应的破坏用例。

用法：python _tools/qa/_reverse_verify_image_crop.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_image_crop.py"

AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders"

OPS = AND / "util/ImageOps.kt"
WATERMARK = AND / "util/Watermark.kt"
ATTACH = AND / "ai/AiAttachmentLoader.kt"
GEO = AND / "ui/common/ImageCropGeometry.kt"
DIALOG = AND / "ui/common/ImageCropDialog.kt"
FORM = AND / "ui/dispatcher/ProductFormScreen.kt"
FORM_VM = AND / "ui/dispatcher/ProductFormViewModel.kt"
GEO_TEST = TEST / "ui/common/ImageCropGeometryTest.kt"

CHG_DOC = ROOT / "docs/changes/CHG-0072.md"
REGISTRY = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "顺序反了：拿没摆正的原始解码件去缩（竖拍照片会横过来）",
        OPS,
        "        val oriented = decodeOriented(path)\n        val scaled = scaleDown(oriented, maxEdge)",
        "        val oriented = BitmapFactory.decodeFile(path) ?: throw IllegalStateException(\"图片读取失败\")\n        val scaled = scaleDown(oriented, maxEdge)",
        "顺序要紧",
    ),
    (
        "「不裁切」变成原图原样交出去（摆正与压缩一起丢了）",
        OPS,
        "        val cropped = if (rect == null) scaled else crop(scaled, rect)",
        "        val cropped = if (rect == null) decodeOriented(srcPath) else crop(scaled, rect)",
        "不裁切",
    ),
    (
        "解码被抄第二份：AI 附件加载器自己解一张（摆正就漏了）",
        ATTACH,
        "        return android.graphics.Bitmap.createScaledBitmap(",
        "        return android.graphics.BitmapFactory.decodeFile(",
        "全仓 BitmapFactory.decodeFile(",
    ),
    (
        "Watermark 又自己养一份旋转与缩放下限",
        WATERMARK,
        "    private const val MAX_EDGE = ImageOps.MAX_EDGE",
        "    private const val MAX_EDGE = 2560\n\n    @Suppress(\"unused\")\n    private fun legacyOrientation(path: String): Int =\n        ExifInterface(path).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)",
        "Watermark 不再自己养一份 EXIF 旋转",
    ),
    (
        "长边上限被改（商品照与送达照从此走散）",
        OPS,
        "    const val MAX_EDGE = 2560",
        "    const val MAX_EDGE = 4096",
        "长边上限只有一处",
    ),
    (
        "几何层塞进 android import（JVM 单测跑不起来）",
        GEO,
        "import kotlin.math.roundToInt",
        "import android.graphics.Rect\nimport kotlin.math.roundToInt",
        "几何文件不许 import android",
    ),
    (
        "最小框缩到捏不住（44dp 手指宽变 8dp）",
        GEO,
        "internal const val CROP_MIN_SIDE_DP = 48f",
        "internal const val CROP_MIN_SIDE_DP = 8f",
        "每边最小框",
    ),
    (
        "命中顺序改成边优先（角上那一小块变成拖边）",
        GEO,
        "    if (nearLeft && nearTop) return CropHandle.TOP_LEFT\n    if (nearRight && nearTop) return CropHandle.TOP_RIGHT\n    if (nearLeft && nearBottom) return CropHandle.BOTTOM_LEFT\n    if (nearRight && nearBottom) return CropHandle.BOTTOM_RIGHT\n    if (nearTop && insideX) return CropHandle.TOP",
        "    if (nearTop && insideX) return CropHandle.TOP\n    if (nearLeft && nearTop) return CropHandle.TOP_LEFT\n    if (nearRight && nearTop) return CropHandle.TOP_RIGHT\n    if (nearLeft && nearBottom) return CropHandle.BOTTOM_LEFT\n    if (nearRight && nearBottom) return CropHandle.BOTTOM_RIGHT",
        "角优先于边",
    ),
    (
        "拖到最小边还继续缩（框会翻面）",
        GEO,
        "    val leftMax = box.right - minSide",
        "    val leftMax = box.right",
        "拖到最小边就粘住",
    ),
    (
        "像素换算不再保证 1 像素（亚像素框会存出空图）",
        GEO,
        "    val r = right.coerceIn(l + 1, imageW)",
        "    val r = right.coerceIn(l, imageW)",
        "夹回图内且至少 1 像素",
    ),
    (
        "位图回收把正在画的那张也收掉（真机一进弹层就崩）",
        DIALOG,
        "        val owned = bitmap\n        onDispose { owned?.recycle() }",
        "        onDispose { bitmap?.recycle() }",
        "值先抓进局部变量",
    ),
    (
        "裁切页自己解码（＝先裁后摆正，EXIF 方向又丢了）",
        DIALOG,
        "runCatching { ImageOps.loadOriented(sourcePath) }.getOrNull()",
        "runCatching { BitmapFactory.decodeFile(sourcePath) }.getOrNull()",
        "裁切页不许自己 BitmapFactory",
    ),
    (
        "「不裁切」这颗按钮被拿掉（m01347 ④ 只剩一半）",
        DIALOG,
        "                    if (allowNoCrop) {",
        "                    if (false) {",
        "「不裁切」只在 allowNoCrop",
    ),
    (
        "「不裁切」改成把源文件直接交出去（绕过流水线）",
        DIALOG,
        "                        TextButton(onClick = { output(null) }, enabled = !saving) {",
        "                        TextButton(onClick = { onCropped(File(sourcePath)) }, enabled = !saving) {",
        "「不裁切」走的就是 output(null)",
    ),
    (
        "裁切页自己画（踩 Canvas 红线，全库只许图表那个文件）",
        DIALOG,
        "        Surface(color = Color.Black, modifier = Modifier.fillMaxSize()) {",
        "        Canvas(Modifier.fillMaxSize()) { }\n        Surface(color = Color.Black, modifier = Modifier.fillMaxSize()) {",
        "弹层里不用 Canvas",
    ),
    (
        "裁切页被复制第二份",
        DIALOG,
        "internal fun ImageCropDialog(",
        "internal fun ImageCropDialogLegacy(",
        "全仓只有一处 internal fun ImageCropDialog(",
    ),
    (
        "相册选完直接交 VM（裁切页永远打不开）",
        FORM,
        "                cropPath = f.absolutePath",
        "                vm.pickImage(f.absolutePath)",
        "选完图先攒成 cropPath",
    ),
    (
        "裁切页根本没挂上（cropPath 攒了也不显示）",
        FORM,
        "    val cropping = cropPath",
        "    val cropping: String? = null",
        "裁切页挂在 Scaffold 之外",
    ),
    (
        "老图长出批量重裁入口（用户 m01347 ③ 明确不要）",
        FORM,
        "                TextButton(onClick = onCrop) { Text(\"裁切\") }",
        "                TextButton(onClick = onCrop) { Text(\"裁切\") }\n                TextButton(onClick = {}) { Text(\"重裁全部\") }",
        "老图没有批量重裁入口",
    ),
    (
        "编辑页那颗 168dp 变成看大图（m01532 的口径被推翻）",
        FORM,
        "        onPick = { pickImage.launch(\"image/*\") },",
        "        onPick = { productImageClickable(\"x\") },",
        "点图＝重新选图",
    ),
    (
        "上传时机变了：传的是表单里那个路径，不是裁过的那个",
        FORM_VM,
        "                uploadIfPicked(created.id, localImage)",
        "                uploadIfPicked(created.id, path)",
        "上传时机与调用形态一个字没改",
    ),
    (
        "VM 不再吃本地草稿（对裁过的图再裁时会去下服务端那张旧的）",
        FORM_VM,
        "        if (local != null && File(local).exists()) return local",
        "        if (false) return local",
        "本地草稿优先",
    ),
    (
        "取图又新建一个 OkHttpClient（连接池与 DNS 覆写都绕过了）",
        FORM_VM,
        "                NetworkDns.okHttp.newCall(Request.Builder().url(url).get().build()).execute().use { resp ->",
        "                OkHttpClient().newCall(Request.Builder().url(url).get().build()).execute().use { resp ->",
        "不新建 OkHttpClient",
    ),
    (
        "取下来的临时图不再带 product_src_ 前缀（清缓存时认不出来）",
        FORM_VM,
        "            val f = File(container.appContext.cacheDir, \"product_src_\" + System.currentTimeMillis() + \".jpg\")",
        "            val f = File(container.appContext.cacheDir, \"src_\" + System.currentTimeMillis() + \".jpg\")",
        "product_src_",
    ),
    (
        "单测那条「角优先于边」被改名（边界没人钉了）",
        GEO_TEST,
        "    fun `角比边优先`() {",
        "    fun `命中优先级`() {",
        "单测钉住：角比边优先",
    ),
    (
        "变更单少一节（⑨ 关闭 被改名）",
        CHG_DOC,
        "## ⑨ 关闭",
        "## ⑨ 收尾",
        "## ⑨ 关闭",
    ),
    (
        "登记簿那一行的链接被拆（对账找不到文件）",
        REGISTRY,
        "[CHG-0072.md](CHG-0072.md)",
        "[CHG-0072 裁切](CHG-0072.md)",
        "登记簿里有 CHG-0072 那一行",
    ),
    (
        "工作声明那一行被改名（认领段对不上变更单）",
        CLAIM,
        "**CHG-0072 上传的商品照片能自由框选裁切",
        "**CHG-0072：上传的商品照片能自由框选裁切",
        "工作声明里有 CHG-0072",
    ),
]


def read_src(p: Path):
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> bytes:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    out = data.encode("utf-8")
    p.write_bytes(out)
    return out


def restore_src(p: Path, text: str, crlf: bool) -> None:
    # 还原**当场核对**：写回后重新读回来逐字节比，对不上就非零退出。
    # ⛔ 「写了还原」不是证明；重新读回来的字节 == 刚写出去的字节 才是。
    wrote = write_src(p, text, crlf)
    if p.read_bytes() != wrote:
        print("⛔ 还原后与快照不一致（注入污染了源码树）：" + str(p))
        raise SystemExit(2)


def run_check():
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def verdict(expect: str):
    code, out = run_check()
    fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
    hit = code != 0 and any(expect in ln for ln in fails)
    detail = "实际红 " + str(len(fails)) + " 条"
    if not hit:
        detail += "：" + str([f.strip()[:70] for f in fails[:2]])
    return hit, detail


def main() -> int:
    bad = 0
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线没过\n" + out[-1200:])
        return 1
    print("✅ 前提：源码完好时这条红线是绿的")

    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print("  [SKIP] " + label + " —— 原文出现 " + str(src.count(old)) + " 次，无法唯一替换")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            hit, detail = verdict(expect)
        finally:
            restore_src(path, src, crlf)
        tag = "OK" if hit else "MISS"
        print("  [" + tag + "] " + label + " → " + detail)
        if not hit:
            bad += 1

    code, out = run_check()
    ok = code == 0
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + 1
    print()
    if bad:
        print("❌ " + str(bad) + "/" + str(total) + " 条不成立（红线对它们不敏感）")
        return 1
    print("✅ " + str(total) + "/" + str(total) + " 全部成立：每条注入都让红线点出了那一条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
