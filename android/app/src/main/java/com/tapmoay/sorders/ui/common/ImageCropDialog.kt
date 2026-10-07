package com.tapmoay.sorders.ui.common

import android.graphics.Bitmap
import android.graphics.Rect
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.calculateCentroid
import androidx.compose.foundation.gestures.calculatePan
import androidx.compose.foundation.gestures.calculateZoom
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Button
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.positionChanged
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.tapmoay.sorders.util.ImageOps
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import kotlin.math.roundToInt

/** 裁切层里那几种颜色只有一处：遮罩压暗、框与手柄的白。 */
private val CROP_MASK = Color.Black.copy(alpha = 0.6f)
private val CROP_WHITE = Color.White

/**
 * # 商品照片的自由框选裁切（CHG-0072 / 台账 L-33）
 *
 * 用户口径（m01347）：「裁切是**自由的**，是可以自己**选择框选**的，就是我们普通的手机裁切的功能嘛」
 * ⇒ 就是相册那种：框可以拖角、拖边、整个挪，图可以双指缩放平移。**不是**固定比例模板。
 *
 * 三个出口：
 * - **取消** —— 什么都不做（调用方保持原样）；
 * - **不裁切** —— 就这张原图，但仍然**摆正 + 压缩**（m01347：「压缩是我们自动给它压缩的」），
 *   走的是同一条 [ImageOps] 流水线，只是不裁那一刀；[allowNoCrop] 为假时这颗不给（编辑态重裁）；
 * - **完成** —— 把框里的那部分裁出来。
 *
 * 两个"要输出"的出口都写进调用方给的 [outFile]（覆盖写），再回调 [onCropped]；
 * 框没量到 / 位图读不出来时不会输出半张废图（分别是退化成不裁切、与停在错误提示上）。
 *
 * ⛔ 这里不画自定义图形（遮罩、白框、手柄全是普通 Box 拼的）：全库只许图表那一个文件用 Canvas。
 */
@Composable
internal fun ImageCropDialog(
    sourcePath: String,
    outFile: File,
    allowNoCrop: Boolean = true,
    onCancel: () -> Unit,
    onCropped: (File) -> Unit,
) {
    var bitmap by remember(sourcePath) { mutableStateOf<Bitmap?>(null) }
    var error by remember(sourcePath) { mutableStateOf<String?>(null) }
    var saving by remember(sourcePath) { mutableStateOf(false) }
    var viewport by remember(sourcePath) { mutableStateOf(IntSize.Zero) }
    var transform by remember(sourcePath) { mutableStateOf(ViewTransform(0f, 0f, 0f, 0f)) }
    var cropBox by remember(sourcePath) { mutableStateOf<ViewRect?>(null) }

    val density = LocalDensity.current
    val minSide = with(density) { CROP_MIN_SIDE_DP.dp.toPx() }
    val slop = with(density) { CROP_HANDLE_SLOP_DP.dp.toPx() }
    val scope = rememberCoroutineScope()

    // 解码走 IO 线程：原图可能几十兆，主线程解码会卡住整屏
    LaunchedEffect(sourcePath) {
        val loaded = withContext(Dispatchers.IO) {
            runCatching { ImageOps.loadOriented(sourcePath) }.getOrNull()
        }
        if (loaded == null) error = "图片读取失败，请重试" else bitmap = loaded
    }
    // 位图归本弹层所有：换图 / 走的时候回收（裁出来的是另一份拷贝，不受影响）
    // ⚠️ 必须先把值抓进局部变量再交给 onDispose：直接在 onDispose 里读 `bitmap`，读到的是**那一刻**的
    //    状态 —— 而 key 变化恰恰就是"刚把新图解出来"的时候，于是刚解出来的那张当场被回收，
    //    下一帧画它的时候就是 `Canvas: trying to use a recycled bitmap`（真机 emulator-5554 实测：
    //    选完图弹层刚出现就崩，日志里 BitmapPainter.onDraw → BaseCanvas.throwIfCannotDraw）。
    DisposableEffect(bitmap) {
        val owned = bitmap
        onDispose { owned?.recycle() }
    }
    // 量到视口 + 图也解出来了，才摆第一次：按"刚好铺满"居中，框内缩一圈
    LaunchedEffect(bitmap, viewport) {
        val bmp = bitmap ?: return@LaunchedEffect
        if (viewport.width <= 0 || viewport.height <= 0) return@LaunchedEffect
        if (cropBox != null) return@LaunchedEffect
        val fitted = fitTransform(bmp.width, bmp.height, viewport.width.toFloat(), viewport.height.toFloat())
        transform = fitted
        cropBox = initialCropBox(
            visibleImageRect(fitted, viewport.width.toFloat(), viewport.height.toFloat()),
            minSide,
        )
    }

    // 两个出口共用：crop = null 表示"不裁切，只摆正 + 压缩"
    fun output(pixels: PixelRect?) {
        val bmp = bitmap
        if (bmp == null || saving) return
        saving = true
        scope.launch {
            val ok = withContext(Dispatchers.IO) {
                runCatching {
                    val cut = if (pixels == null) bmp else ImageOps.crop(
                        bmp,
                        Rect(pixels.left, pixels.top, pixels.right, pixels.bottom),
                    )
                    ImageOps.saveJpeg(cut, outFile)
                    if (cut !== bmp) cut.recycle()
                }.isSuccess
            }
            saving = false
            if (ok) onCropped(outFile) else error = "保存失败，请重试"
        }
    }

    Dialog(onDismissRequest = onCancel, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(color = Color.Black, modifier = Modifier.fillMaxSize()) {
            Column(Modifier.fillMaxSize()) {
                Hint(
                    text = "拖动边框圈出要保留的部分，双指可放大缩小",
                    color = CROP_WHITE.copy(alpha = 0.85f),
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
                )
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f)
                        .onSizeChanged { viewport = it }
                        .pointerInput(bitmap, viewport) {
                            val w = viewport.width.toFloat()
                            val h = viewport.height.toFloat()
                            if (bitmap == null || w <= 0f || h <= 0f) return@pointerInput
                            val bounds = ViewRect(0f, 0f, w, h)
                            awaitEachGesture {
                                val down = awaitFirstDown(requireUnconsumed = false)
                                // 按下那一刻定"这次手势在干嘛"：捏住手柄 / 拖框 / 拖图
                                val grabbed = cropBox?.let { hitCropHandle(it, down.position.x, down.position.y, slop) }
                                    ?: CropHandle.NONE
                                var pointerCount = 1
                                while (true) {
                                    val event = awaitPointerEvent()
                                    pointerCount = event.changes.count { it.pressed }
                                    if (pointerCount == 0) break
                                    if (pointerCount >= 2) {
                                        // 双指：捏合缩放 + 平移图（焦点是两指中心，捏哪儿放大哪儿）
                                        val zoom = event.calculateZoom()
                                        val pan = event.calculatePan()
                                        val centroid = event.calculateCentroid(useCurrent = true)
                                        var moved = transform
                                        if (zoom != 1f) {
                                            moved = zoomTransform(moved, centroid.x, centroid.y, zoom, w, h)
                                        }
                                        if (pan.x != 0f || pan.y != 0f) {
                                            moved = panTransform(moved, pan.x, pan.y, w, h)
                                        }
                                        transform = moved
                                        event.changes.forEach { if (it.positionChanged()) it.consume() }
                                    } else {
                                        val change = event.changes.firstOrNull { it.pressed } ?: break
                                        val dx = change.position.x - change.previousPosition.x
                                        val dy = change.position.y - change.previousPosition.y
                                        when (grabbed) {
                                            CropHandle.INSIDE, CropHandle.TOP, CropHandle.BOTTOM,
                                            CropHandle.LEFT, CropHandle.RIGHT, CropHandle.TOP_LEFT,
                                            CropHandle.TOP_RIGHT, CropHandle.BOTTOM_LEFT,
                                            CropHandle.BOTTOM_RIGHT,
                                            -> cropBox = cropBox?.let {
                                                dragCropHandle(it, grabbed, dx, dy, bounds, minSide)
                                            }
                                            else -> transform = panTransform(transform, dx, dy, w, h)
                                        }
                                        change.consume()
                                    }
                                }
                            }
                        },
                ) {
                    val bmp = bitmap
                    val box = cropBox
                    val t = transform
                    if (bmp != null && box != null && t.width > 0f) {
                        val d = density
                        Image(
                            bitmap = bmp.asImageBitmap(),
                            contentDescription = "待裁切的商品照片",
                            contentScale = ContentScale.FillBounds,
                            modifier = Modifier
                                .offset { IntOffset(t.offsetX.roundToInt(), t.offsetY.roundToInt()) }
                                .size(with(d) { t.width.toDp() }, with(d) { t.height.toDp() }),
                        )
                        // 框外压暗：上 / 下 / 左 / 右四块（框内保持原亮度，一眼看出留下的是哪一块）
                        MaskRect(0f, 0f, viewport.width.toFloat(), box.top)
                        MaskRect(0f, box.bottom, viewport.width.toFloat(), viewport.height.toFloat())
                        MaskRect(0f, box.top, box.left, box.bottom)
                        MaskRect(box.right, box.top, viewport.width.toFloat(), box.bottom)
                        // 白框
                        Box(
                            Modifier
                                .offset { IntOffset(box.left.roundToInt(), box.top.roundToInt()) }
                                .size(
                                    with(d) { box.width.toDp() },
                                    with(d) { box.height.toDp() },
                                )
                                .border(2.dp, CROP_WHITE),
                        )
                        // 四角手柄 + 四边中点短棒（都是给眼睛看的，热区由 hitCropHandle 的 slop 管）
                        HandleDot(box.left, box.top, 22.dp)
                        HandleDot(box.right, box.top, 22.dp)
                        HandleDot(box.left, box.bottom, 22.dp)
                        HandleDot(box.right, box.bottom, 22.dp)
                        HandleBar(box.centerX, box.top, 40.dp, 3.dp)
                        HandleBar(box.centerX, box.bottom, 40.dp, 3.dp)
                        HandleBar(box.left, box.centerY, 3.dp, 40.dp)
                        HandleBar(box.right, box.centerY, 3.dp, 40.dp)
                    } else if (error == null) {
                        Text("载入中…", color = CROP_WHITE, modifier = Modifier.align(Alignment.Center))
                    }
                }
                error?.let {
                    Text(
                        text = it,
                        color = Color(0xFFFF6B6B),
                        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
                    )
                }
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    TextButton(onClick = onCancel, enabled = !saving) {
                        Text("取消", color = CROP_WHITE)
                    }
                    if (allowNoCrop) {
                        TextButton(onClick = { output(null) }, enabled = !saving) {
                            Text("不裁切", color = CROP_WHITE)
                        }
                    }
                    Spacer(Modifier.weight(1f))
                    Button(
                        onClick = {
                            val bmp = bitmap
                            val box = cropBox
                            output(
                                if (bmp == null || box == null) null
                                else cropToPixels(box, transform, bmp.width, bmp.height),
                            )
                        },
                        enabled = !saving && bitmap != null,
                    ) {
                        Text("完成")
                    }
                }
            }
        }
    }
}

/** 框外的一块压暗（四块拼出"框外变暗、框内原样"的效果）。 */
@Composable
private fun MaskRect(left: Float, top: Float, right: Float, bottom: Float) {
    val w = right - left
    val h = bottom - top
    if (w <= 0f || h <= 0f) return
    val d = LocalDensity.current
    Box(
        Modifier
            .offset { IntOffset(left.roundToInt(), top.roundToInt()) }
            .size(with(d) { w.toDp() }, with(d) { h.toDp() })
            .background(CROP_MASK),
    )
}

/** 四角的手柄（圆点）。 */
@Composable
private fun HandleDot(cx: Float, cy: Float, size: Dp) {
    val d = LocalDensity.current
    val px = with(d) { size.toPx() }
    Box(
        Modifier
            .offset { IntOffset((cx - px / 2f).roundToInt(), (cy - px / 2f).roundToInt()) }
            .size(size)
            .clip(CircleShape)
            .background(CROP_WHITE),
    )
}

/** 四边中点的短棒（横边用横棒，竖边用竖棒）。 */
@Composable
private fun HandleBar(cx: Float, cy: Float, w: Dp, h: Dp) {
    val d = LocalDensity.current
    val px = with(d) { w.toPx() }
    val py = with(d) { h.toPx() }
    Box(
        Modifier
            .offset { IntOffset((cx - px / 2f).roundToInt(), (cy - py / 2f).roundToInt()) }
            .size(w, h)
            .background(CROP_WHITE),
    )
}
