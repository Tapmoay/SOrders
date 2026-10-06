"""反向验证：把 CHG-0044 与 CHG-0070（台账 L-37 横滑翻页 / 商品图）的红线逐条弄坏，看它们**真的会红**。

为什么这块必须反向验证：这一条全是"没报错但也没发生"的毛病 ——
把 .pointerInput { detectTapGestures } 换回 .clickable { onDismiss() } 编译通过、点一下也确实能关，
只有在**拖动/双指缩放中途抬手**时才"图被关了"；把 Q 以下那条保存分支删掉，
Q+ 机器上一切正常，只有 Android 8/9 用户看到"保存失败"；再抄一份大图预览，谁都发现不了。
判据里还有一半是"扫全仓"（只有一处 ImagePreviewDialog），清单如果不验证，
就可能因为"目录扫不到"而永远绿。所以每一条都要有对应的破坏用例。

用法：python _tools/qa/_reverse_verify_image_preview.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_image_preview.py"

AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
PREVIEW = AND / "ui/common/ImagePreview.kt"
EXPORT = AND / "util/ExportUtil.kt"
DETAIL = AND / "ui/order/OrderDetailScreen.kt"
PUBLIC_DIR = AND / "ui/common"
# ---- CHG-0070（台账 L-37）：横滑翻页 / 商品图点图看大图 ----
SWIPE = AND / "ui/common/ImageSwipe.kt"
PRODUCTS = AND / "ui/dispatcher/ProductsScreen.kt"
FORM = AND / "ui/dispatcher/ProductFormScreen.kt"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    # ---- 1. 只有一份预览 ----
    (
        "详情页又自己拼一个匿名 Dialog 弹层（全库唯一那一份的约定破功）",
        DETAIL,
        "    preview.Show()\n",
        "    Dialog(onDismissRequest = { }) { AsyncImage(model = null, contentDescription = null) }\n",
        "不再自己拼一个匿名 Dialog 弹层",
    ),
    (
        "详情页自己拿回一份 previewUrl 状态（不走 openPhoto）",
        DETAIL,
        "                onPhotoClick = openPhoto,",
        "                onPhotoClick = { previewUrl = it },",
        "onPhotoClick 走 openPhoto",
    ),
    # ---- 2. 缩放 ----
    (
        "把双指缩放摘掉（只剩「点开看」）",
        PREVIEW,
        "                        detectTransformGestures { _, pan, zoom, _ ->",
        "                        detectDragGestures { _, _ ->",
        "双指缩放：detectTransformGestures",
    ),
    (
        "倍数不再夹在上下限之间（能捏成 0.2x / 40x）",
        PREVIEW,
        "val next = (scale * zoom).coerceIn(MIN_SCALE, MAX_SCALE)",
        "val next = scale * zoom",
        "倍数被夹在上下限之间",
    ),
    (
        "把 MIN_SCALE 改成 0.5f（回不到「整张图刚好放进屏幕」）",
        PREVIEW,
        "private const val MIN_SCALE = 1f",
        "private const val MIN_SCALE = 0.5f",
        "MIN_SCALE 就是 1f",
    ),
    (
        "把 MAX_SCALE 压到 1f（放大不了，等于没有缩放）",
        PREVIEW,
        "private const val MAX_SCALE = 5f",
        "private const val MAX_SCALE = 1f",
        "MAX_SCALE 在 2x-20x 之间",
    ),
    (
        "双击倍数顶到上限之外（双击直接把图糊成马赛克）",
        PREVIEW,
        "private const val DOUBLE_TAP_SCALE = 2.5f",
        "private const val DOUBLE_TAP_SCALE = 9f",
        "MIN < 双击倍数 <= MAX",
    ),
    (
        "双击改成「一直放到最大」（不再 1x <-> 2.5x 来回切）",
        PREVIEW,
        "                                scale = DOUBLE_TAP_SCALE",
        "                                scale = MAX_SCALE",
        "双击 1x <-> 2.5x",
    ),
    (
        "翻页不把缩放归位（第二张继承上一张的倍数与位移）",
        PREVIEW,
        "    var scale by remember(index) { mutableStateOf(MIN_SCALE) }",
        "    var scale by remember { mutableStateOf(MIN_SCALE) }",
        "翻页时缩放归位（remember(index)）",
    ),
    (
        "位移也不归位（翻页后图还是歪的）",
        PREVIEW,
        "    var offset by remember(index) { mutableStateOf(Offset.Zero) }",
        "    var offset by remember { mutableStateOf(Offset.Zero) }",
        "位移也归位",
    ),
    (
        "缩放不落到 graphicsLayer（改成不生效的那种写法）",
        PREVIEW,
        "                        scaleX = scale",
        "                        scaleX = 1f",
        "缩放落到 graphicsLayer",
    ),
    # ---- 3. 点任意处关闭 vs 拖动 ----
    (
        "把关闭改回 .clickable（拖动/双指缩放中途抬手就把预览关了）",
        PREVIEW,
        "                .onSizeChanged { box = it }\n",
        "                .onSizeChanged { box = it }\n                .clickable { onDismiss() }\n",
        "根 Box 不再用 .clickable 关预览",
    ),
    (
        "单击手势也交给「拖动」那一套（不再分得清单击还是拖动）",
        PREVIEW,
        "detectTapGestures(",
        "detectDragGestures(",
        "改用 detectTapGestures",
    ),
    (
        "放大后单击直接关闭（想回 1x 看全图，结果把预览关了）",
        PREVIEW,
        "                        onTap = {\n"
        "                            // 1× 时单击＝关闭（老行为一个字没变）；放大后单击＝先回到 1×，\n"
        '                            // 再点一次才关 —— 放大看细节时那一下点击，人想要的是"看全图"。\n'
        "                            if (scale > MIN_SCALE) {\n"
        "                                scale = MIN_SCALE\n"
        "                                offset = Offset.Zero\n"
        "                            } else {\n"
        "                                onDismiss()\n"
        "                            }\n"
        "                        },\n",
        "                        onTap = { onDismiss() },\n",
        "放大后单击＝先回到 1x",
    ),
    (
        "拖动边界算错（图能被拖出屏幕，怎么都拖不回来）",
        PREVIEW,
        "    val maxX = box.width * (scale - 1f) / 2f",
        "    val maxX = box.width",
        "拖动有边界：clampPan",
    ),
    (
        "1x 时图不跟手（横滑没有任何反馈，用户以为滑不动）",
        PREVIEW,
        "                                if (abs(pan.x) > abs(pan.y)) swipe += pan.x\n"
        "                                offset = Offset(swipe.coerceIn(-box.width.toFloat(), box.width.toFloat()), 0f)",
        "                                offset = Offset.Zero",
        "1x 档",
    ),
    # ---- 4. 保存到相册 ----
    (
        "本地 File 也给画下载按钮（「下载」一张本来就在手机里的图）",
        PREVIEW,
        "    val currentPath = models.getOrNull(index) as? String",
        "    val currentPath = models.getOrNull(index)?.toString()",
        "只认服务端路径",
    ),
    (
        "条件放开成永远画（同上，换成另一种写法）",
        PREVIEW,
        "                if (currentPath != null) {",
        "                if (true) {",
        "按钮只在有服务端路径时才画",
    ),
    (
        "自己 new 一个 OkHttpClient（绕开共享连接池与超时）",
        PREVIEW,
        "NetworkDns.okHttp.newCall(",
        "okhttp3.OkHttpClient().newCall(",
        "复用共享 OkHttpClient",
    ),
    (
        "取字节回到主线程（网络在主线程 = 卡界面 / NetworkOnMainThread）",
        PREVIEW,
        "val bytes = withContext(Dispatchers.IO) { downloadBytes(full) }",
        "val bytes = downloadBytes(full)",
        "取字节在 IO 线程",
    ),
    (
        "落盘不切 IO（写相册在主线程）",
        PREVIEW,
        "val saved = bytes?.let {\n                                        withContext(Dispatchers.IO) {",
        "val saved = bytes?.let {\n                                        run {",
        "落盘也在 IO 线程",
    ),
    (
        "保存中不禁止重复点（连点几次存好几张）",
        PREVIEW,
        "                        enabled = !saving,",
        "                        enabled = true,",
        "保存中防重复点",
    ),
    (
        "保存成功不说存到哪（用户不知道去哪儿找）",
        PREVIEW,
        "if (saved != null) " + chr(34) + "已保存到相册：" + chr(34) + " + saved.substringAfterLast('/')",
        chr(34) + "已保存到相册" + chr(34),
        "成功有反馈（带文件名）",
    ),
    (
        "失败只说「失败」（不说是不是网络，用户没法自救）",
        PREVIEW,
        'else "保存失败，请检查网络后重试",',
        'else "保存失败",',
        "失败有反馈（说清是网络）",
    ),
    (
        "不拼全地址就直接下载（相对路径 → 拿不到图）",
        PREVIEW,
        "                            val full = resolveStaticUrl(currentPath)",
        "                            val full = currentPath",
        "先过 resolveStaticUrl 拼全地址",
    ),
    (
        "删掉底部那句手势提示（缩放变成没人知道的隐藏功能）",
        PREVIEW,
        '                "双指缩放 / 双击放大 / 左右滑动翻页",',
        '                "",',
        "手势是藏起来的",
    ),
    # ---- 5. util/ExportUtil.kt 两条系统分支 ----
    (
        "Q 以下那条分支写错目录（Android 8/9 存到下载目录去）",
        EXPORT,
        "getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES)",
        "getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)",
        "Q 以下直接写公开目录",
    ),
    (
        "Q 以下写完不喊媒体扫描（相册要等下次开机才看见）",
        EXPORT,
        '            MediaScannerConnection.scanFile(context, arrayOf(file.absolutePath), arrayOf("image/jpeg"), null)\n',
        "",
        "Q 以下写完喊媒体扫描",
    ),
    (
        "Q+ 不把 IS_PENDING 收尾（相册里可能是一张写了一半的图）",
        EXPORT,
        "            values.put(MediaStore.Images.Media.IS_PENDING, 0)",
        "            values.put(MediaStore.Images.Media.IS_PENDING, 1)",
        "Q+ 写完才让别人看见",
    ),
    (
        "图片的 MIME 写成 png（后缀 jpg 内容 png，相册认不出）",
        EXPORT,
        'put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg")',
        'put(MediaStore.Images.Media.MIME_TYPE, "image/png")',
        "Q+ 的 MIME 是 image/jpeg",
    ),
    (
        "图片直接落在 Pictures 根目录（几百张图糊在一起）",
        EXPORT,
        'put(MediaStore.Images.Media.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/SOrders")',
        "put(MediaStore.Images.Media.RELATIVE_PATH, Environment.DIRECTORY_PICTURES)",
        "Q+ 落 Pictures/SOrders",
    ),
    (
        "顺手把既有 saveExportFile 的目录也改了（报表落点被动）",
        EXPORT,
        'put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/SOrders报表")',
        'put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/SOrders")',
        "既有 saveExportFile 的目录没被顺手改掉",
    ),
    (
        "把落盘函数签名收掉 context（存不进相册）",
        EXPORT,
        "fun saveImageToGallery(context: Context, bytes: ByteArray, fileName: String): String?",
        "fun saveImageToGallery(bytes: ByteArray, fileName: String): String?",
        "有 saveImageToGallery(context, bytes, fileName)",
    ),
    # ---- 6. 详情页的收口 ----
    (
        "详情页不再回两组里认领（点送达照片也只能看这一张）",
        DETAIL,
        "        val group = when {\n"
        "            delivery.contains(url) -> delivery\n"
        "            place.contains(url) -> place\n"
        "            else -> listOf(url)\n"
        "        }\n",
        "        val group = listOf(url)\n",
        "回两组里认领",
    ),
    (
        "点了照片却打开「只看这一张」（丢掉了同组翻页）",
        DETAIL,
        "        preview.openStaticPaths(group, group.indexOf(url))",
        "        preview.openStaticPaths(listOf(url), 0)",
        "认领到的落点：openStaticPaths(group, indexOf)",
    ),
    (
        "接上了状态却忘了画出弹层（点了没反应）",
        DETAIL,
        "    preview.Show()\n",
        "",
        "页面末尾画出弹层 preview.Show()",
    ),
    (
        "openStaticPaths 不剔空白（点空格子 = 一张黑图，还占着翻页位）",
        PREVIEW,
        "        val usable = paths.withIndex().filter { it.value.isNotBlank() }",
        "        val usable = paths.withIndex()",
        "openStaticPaths 剔掉空白路径",
    ),
    (
        "黑底改成白底（浅色照片糊在背景里）",
        PREVIEW,
        ".background(Color.Black.copy(alpha = 0.96f))",
        ".background(Color.White)",
        "预览弹层仍是黑底",
    ),
    (
        "单张也画左右箭头与计数（0/1 那种没意义的控件）",
        PREVIEW,
        "            if (models.size > 1) {",
        "            if (true) {",
        "多张时才有左右箭头与计数",
    ),
    (
        "把 2/3 计数删掉（一串照片看不出看到第几张）",
        PREVIEW,
        '                    "${index + 1} / ${models.size}",',
        '                    "${index + 1}",',
        "计数文案仍在",
    ),
    # ---- 7. 看大图横滑翻页，箭头到头即停（CHG-0070 / 台账 L-37）----
    (
        "把横滑翻页摘掉（只剩两个箭头按钮，回到用户抱怨的那个状态）",
        PREVIEW,
        "                        val step = swipePageStep(\n"
        "                            accumX = swipe,\n"
        "                            boxWidth = box.width,\n"
        "                            atFirst = index <= 0,\n"
        "                            atLast = index >= models.lastIndex,\n"
        "                        )",
        "                        val step = 0",
        "预览页真的用了这个纯函数",
    ),
    (
        "放大后也当翻页用（分档没了：放大时图不跟手，一拖就翻页）",
        PREVIEW,
        "                            if (next <= MIN_SCALE) {",
        "                            if (true) {",
        "1x 档",
    ),
    (
        "箭头又改回环绕（到头绕回去，用户明确说过不要）",
        PREVIEW,
        "                        onClick = { index -= 1 },",
        "                        onClick = { index = (index - 1 + models.size) % models.size },",
        "环绕写法",
    ),
    (
        "首张也画左箭头（那颗点了没反应的按钮）",
        PREVIEW,
        "                if (index > 0) {",
        "                if (models.size > 1) {",
        "首张不画左箭头",
    ),
    (
        "到头即停的守卫删掉（第一张往右直接绕到最后一张）",
        SWIPE,
        "        if (atFirst) 0 else -1",
        "        -1",
        "到头即停",
    ),
    (
        "商品图上不给热区（用户点商品图没反应）",
        PRODUCTS,
        "                    modifier = Modifier.productImageClickable(p.imageUrl) { p.imageUrl?.let(onShowImage) },",
        "                    modifier = Modifier,",
        "商品管理列表",
    ),
    (
        "商品编辑页也改成点图看大图（用户说过那一页是重新选图）",
        FORM,
        "                .clickable(onClick = onPick),",
        "                .clickable(onClick = onPick)\n                .productImageClickable(\"x\") { },",
        "编辑页那颗大图不动",
    ),
]

#: 需要**新建文件**的注入（判据 1 的"全仓只有一处"是扫目录算出来的，得证明它真的会数到新文件）
CREATIONS = [
    (
        "订单侧又抄了一份大图预览（扫全仓的那条判据必须点名它）",
        PUBLIC_DIR / "_LeakPreviewScreen.kt",
        "package com.tapmoay.sorders.ui.common\n\n"
        "@Composable\n"
        "fun ImagePreviewDialog(models: List<Any>, startIndex: Int = 0, onDismiss: () -> Unit) {\n"
        "    if (models.isEmpty()) return\n"
        "}\n",
        "全仓只有一处 fun ImagePreviewDialog(",
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
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


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def verdict(expect: str) -> tuple[bool, str]:
    code, out = run_check()
    fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
    hit = code != 0 and any(expect in ln for ln in fails)
    return hit, f"实际红 {len(fails)} 条" + ("" if hit else f"：{[f.strip()[:70] for f in fails[:2]]}")


def main() -> int:
    bad = 0
    code, out = run_check()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时这条红线没过\n{out[-1200:]}")
        return 1
    print("✅ 前提：源码完好时这条红线是绿的")

    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print(f"  [SKIP] {label} —— 原文出现 {src.count(old)} 次，无法唯一替换")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            hit, detail = verdict(expect)
        finally:
            restore_src(path, src, crlf)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    for label, path, content, expect in CREATIONS:
        if path.exists():
            print(f"  [SKIP] {label} —— 路径已存在：{path.name}")
            bad += 1
            continue
        path.write_bytes(content.encode("utf-8"))
        try:
            hit, detail = verdict(expect)
        finally:
            path.unlink(missing_ok=True)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    code, out = run_check()
    ok = code == 0
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + len(CREATIONS) + 1
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立（红线对它们不敏感）")
        return 1
    print(f"✅ {total}/{total} 全部成立：每条注入都让红线点出了那一条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
