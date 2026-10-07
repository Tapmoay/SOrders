package com.tapmoay.sorders.ui.common

import kotlin.math.roundToInt

/**
 * # 裁切框的几何（**纯函数，零 Android / 零 Compose import**）
 *
 * 商品照片的自由框选裁切（CHG-0072 / 台账 L-33）里，真正容易错的是"手指在这一像素上，
 * 该改哪条边"这类换算：缩放够不够、框出没出图、拖到边界会不会翻面。
 * 手势与位图那一层在 JVM 单测里验不了（要真机 / Robolectric），所以按 [ImageSwipe.kt] 的老办法
 * 把**能算的东西全拆到这里**：只有坐标与四则运算，能在普通 JUnit 里逐条钉住。
 * 于是 [ImageCropDialog] 里只剩"画出来 + 把手势喂给这些函数"。
 *
 * ## 两套坐标，别混
 * - **视口坐标**（ViewRect / ViewTransform）：跟屏幕像素走，随图片缩放而变化。
 * - **位图像素坐标**（PixelRect）：跟真正那张位图走，存下来的是它。
 *   [cropToPixels] 是唯一的换算点 —— 只有它知道"图上那一点"对应"位图里的哪个像素"。
 */
internal data class ViewRect(val left: Float, val top: Float, val right: Float, val bottom: Float) {
    val width: Float get() = right - left
    val height: Float get() = bottom - top
    val centerX: Float get() = (left + right) / 2f
    val centerY: Float get() = (top + bottom) / 2f
}

/**
 * 图片当前在视口里怎么摆：[width] / [height] 是**显示尺寸**（已含缩放），
 * [offsetX] / [offsetY] 是左上角相对视口左上角的偏移（可负 = 图比视口大）。
 *
 * ⚠️ 没有单独的"缩放比例"字段：比例 = [width] 除以位图宽。图片宽高比在任何缩放下都不变，
 * 所以"最小能缩到多少"（fit）也能从这里反推出来，见 [fitWidthFor]。
 */
internal data class ViewTransform(
    val width: Float,
    val height: Float,
    val offsetX: Float,
    val offsetY: Float,
) {
    val aspect: Float get() = if (height <= 0f) 1f else width / height
}

/** 裁切框对应的位图像素矩形（右 / 下是**开区间**，即 right-left = 宽）。 */
internal data class PixelRect(val left: Int, val top: Int, val right: Int, val bottom: Int)

/** 手指落在裁切框的哪一块上（八块 + 框内 + 框外）。 */
internal enum class CropHandle {
    TOP_LEFT, TOP_RIGHT, BOTTOM_LEFT, BOTTOM_RIGHT,
    TOP, BOTTOM, LEFT, RIGHT,
    INSIDE, NONE,
}

/** 裁切框最小边长（dp）：比这还小的框手指捏不住，也存不出一张有意义的图。 */
internal const val CROP_MIN_SIDE_DP = 48f

/** 放大上限（相对"刚好铺满"的倍数）：再大就只能看见几个像素，没有意义。 */
internal const val CROP_MAX_ZOOM = 4f

/** 手柄热区半径（dp）：手指比光标粗，取 28dp ≈ 指尖宽度的一半多一点。 */
internal const val CROP_HANDLE_SLOP_DP = 28f

/** 刚打开时裁切框相对图片内缩的比例（每边 6%）：让人一眼看出"这是个可以拖的框"。 */
internal const val CROP_INITIAL_INSET_FRACTION = 0.06f

/** 图片按"刚好铺满"摆放时该有多宽（长边顶到视口，另一边居中）。 */
internal fun fitWidthFor(aspect: Float, viewW: Float, viewH: Float): Float {
    if (aspect <= 0f || viewW <= 0f || viewH <= 0f) return 0f
    val widthIfHeightBound = viewH * aspect
    return if (widthIfHeightBound <= viewW) widthIfHeightBound else viewW
}

/** 图片按"刚好铺满"摆放（等比、居中）。视口还没量到（0）时返回零尺寸的摆放。 */
internal fun fitTransform(imageW: Int, imageH: Int, viewW: Float, viewH: Float): ViewTransform {
    if (imageW <= 0 || imageH <= 0 || viewW <= 0f || viewH <= 0f) {
        return ViewTransform(0f, 0f, 0f, 0f)
    }
    val width = fitWidthFor(imageW.toFloat() / imageH, viewW, viewH)
    val height = width * imageH / imageW
    return ViewTransform(width, height, (viewW - width) / 2f, (viewH - height) / 2f)
}

/**
 * 把摆放夹回合法范围：**不能比 fit 还小**（小了图周围就露白，裁出来会带黑边），
 * 也不能比 fit 的 [CROP_MAX_ZOOM] 倍还大；同时图必须一直盖住整个视口
 * （偏移只许在 viewW - width 与 0 之间 —— 不然视口边上会露出背景）。
 */
internal fun clampTransform(t: ViewTransform, viewW: Float, viewH: Float): ViewTransform {
    if (t.width <= 0f || t.height <= 0f || viewW <= 0f || viewH <= 0f) return t
    val fitWidth = fitWidthFor(t.aspect, viewW, viewH)
    val minWidth = fitWidth
    val maxWidth = fitWidth * CROP_MAX_ZOOM
    val width = t.width.coerceIn(minWidth, maxWidth)
    val height = t.height * (width / t.width)
    // ⚠️ 两个轴分开算：图比视口大的那条轴才有"可拖的范围"（lo = 视口 - 图，hi = 0）；
    //    图比视口小的那条轴（等比铺满时必然有一条）没有自由度，只能居中 —— 直接 coerceIn 会因为
    //    lo > hi 抛 IllegalArgumentException。
    val offsetX = if (width >= viewW) t.offsetX.coerceIn(viewW - width, 0f) else (viewW - width) / 2f
    val offsetY = if (height >= viewH) t.offsetY.coerceIn(viewH - height, 0f) else (viewH - height) / 2f
    return ViewTransform(width, height, offsetX, offsetY)
}

/** 以 ([focusX], [focusY]) 为不动点缩放 [zoom] 倍（双指捏合：捏哪儿放大哪儿）。 */
internal fun zoomTransform(
    t: ViewTransform,
    focusX: Float,
    focusY: Float,
    zoom: Float,
    viewW: Float,
    viewH: Float,
): ViewTransform {
    if (t.width <= 0f || t.height <= 0f || zoom <= 0f) return t
    val target = clampTransform(
        t.copy(width = t.width * zoom, height = t.height * zoom),
        viewW,
        viewH,
    )
    // 实际缩放比例可能与手势给的不同（被上下限夹过），按实际比例重算偏移，焦点才真的不动
    val applied = target.width / t.width
    return clampTransform(
        ViewTransform(
            target.width,
            target.height,
            focusX - (focusX - t.offsetX) * applied,
            focusY - (focusY - t.offsetY) * applied,
        ),
        viewW,
        viewH,
    )
}

/** 单指在图上拖：整张图平移（裁切框不动）。 */
internal fun panTransform(t: ViewTransform, dx: Float, dy: Float, viewW: Float, viewH: Float): ViewTransform =
    clampTransform(t.copy(offsetX = t.offsetX + dx, offsetY = t.offsetY + dy), viewW, viewH)

/** 图片当前真正落在视口里的那一块（视口比图小的时候用得上）。 */
internal fun visibleImageRect(t: ViewTransform, viewW: Float, viewH: Float): ViewRect {
    val left = t.offsetX.coerceIn(0f, viewW)
    val top = t.offsetY.coerceIn(0f, viewH)
    val right = (t.offsetX + t.width).coerceIn(left, viewW)
    val bottom = (t.offsetY + t.height).coerceIn(top, viewH)
    return ViewRect(left, top, right, bottom)
}

/** 刚打开时的裁切框：在可见图范围内每边内缩 [CROP_INITIAL_INSET_FRACTION]。 */
internal fun initialCropBox(visible: ViewRect, minSide: Float): ViewRect {
    if (visible.width <= 0f || visible.height <= 0f) return visible
    val insetX = visible.width * CROP_INITIAL_INSET_FRACTION
    val insetY = visible.height * CROP_INITIAL_INSET_FRACTION
    val box = ViewRect(
        visible.left + insetX,
        visible.top + insetY,
        visible.right - insetX,
        visible.bottom - insetY,
    )
    return clampCropBox(box, visible, minSide)
}

/**
 * 把裁切框夹进 [bounds]：先整体挪进来，还是太大就贴着 bounds 缩，
 * 最后保证每边不小于 [minSide]（bounds 本来就比 minSide 窄时以 bounds 为准，不再撑出去）。
 */
internal fun clampCropBox(box: ViewRect, bounds: ViewRect, minSide: Float): ViewRect {
    if (bounds.width <= 0f || bounds.height <= 0f) return bounds
    val maxW = bounds.width
    val maxH = bounds.height
    var width = box.width.coerceIn(minOf(minSide, maxW), maxW)
    var height = box.height.coerceIn(minOf(minSide, maxH), maxH)
    var left = box.left
    var top = box.top
    // 先按"原地不动"夹一次，再按尺寸把越界的那一侧拉回来
    if (left + width > bounds.right) left = bounds.right - width
    if (top + height > bounds.bottom) top = bounds.bottom - height
    left = left.coerceIn(bounds.left, maxOf(bounds.left, bounds.right - width))
    top = top.coerceIn(bounds.top, maxOf(bounds.top, bounds.bottom - height))
    width = width.coerceAtMost(bounds.right - left)
    height = height.coerceAtMost(bounds.bottom - top)
    return ViewRect(left, top, left + width, top + height)
}

/** 手指 ([x], [y]) 落在哪一块上：**角优先于边**（角上那一小块既算角也算边，角更常用）。 */
internal fun hitCropHandle(box: ViewRect, x: Float, y: Float, slop: Float): CropHandle {
    val nearLeft = x >= box.left - slop && x <= box.left + slop
    val nearRight = x >= box.right - slop && x <= box.right + slop
    val nearTop = y >= box.top - slop && y <= box.top + slop
    val nearBottom = y >= box.bottom - slop && y <= box.bottom + slop
    val insideX = x >= box.left - slop && x <= box.right + slop
    val insideY = y >= box.top - slop && y <= box.bottom + slop

    if (nearLeft && nearTop) return CropHandle.TOP_LEFT
    if (nearRight && nearTop) return CropHandle.TOP_RIGHT
    if (nearLeft && nearBottom) return CropHandle.BOTTOM_LEFT
    if (nearRight && nearBottom) return CropHandle.BOTTOM_RIGHT
    if (nearTop && insideX) return CropHandle.TOP
    if (nearBottom && insideX) return CropHandle.BOTTOM
    if (nearLeft && insideY) return CropHandle.LEFT
    if (nearRight && insideY) return CropHandle.RIGHT
    if (x >= box.left && x <= box.right && y >= box.top && y <= box.bottom) return CropHandle.INSIDE
    return CropHandle.NONE
}

/**
 * 拖某一块：[handle] 决定动哪条边（角 = 两条边一起动），[dx] / [dy] 是这次手势的位移。
 *
 * 两条规矩：
 * 1. **只动被拖的那条边**（拖左边不改右边，框才跟手）；
 * 2. 顶到 [minSide] 就**粘住**，⛔ 不翻面（用户拖过头时框会停住，而不是突然镜像 —— 后者会让人
 *    以为自己拖错了方向）。
 * 夹的时候下限先算成 max(bounds 那一侧, 反向边 ± minSide)，保证 coerceIn 的 lo ≤ hi（否则会抛异常）。
 */
internal fun dragCropHandle(
    box: ViewRect,
    handle: CropHandle,
    dx: Float,
    dy: Float,
    bounds: ViewRect,
    minSide: Float,
): ViewRect {
    if (handle == CropHandle.NONE) return box
    if (handle == CropHandle.INSIDE) return moveCropBox(box, dx, dy, bounds)

    val leftMax = box.right - minSide
    val rightMin = box.left + minSide
    val topMax = box.bottom - minSide
    val bottomMin = box.top + minSide

    val movesLeft = handle == CropHandle.LEFT || handle == CropHandle.TOP_LEFT || handle == CropHandle.BOTTOM_LEFT
    val movesRight = handle == CropHandle.RIGHT || handle == CropHandle.TOP_RIGHT || handle == CropHandle.BOTTOM_RIGHT
    val movesTop = handle == CropHandle.TOP || handle == CropHandle.TOP_LEFT || handle == CropHandle.TOP_RIGHT
    val movesBottom = handle == CropHandle.BOTTOM || handle == CropHandle.BOTTOM_LEFT || handle == CropHandle.BOTTOM_RIGHT

    var left = box.left
    var top = box.top
    var right = box.right
    var bottom = box.bottom

    // 上限 = 反向边让出 minSide（再被 bounds 兜住下限，保证 lo ≤ hi，coerceIn 不会抛）
    if (movesLeft) left = (box.left + dx).coerceIn(bounds.left, maxOf(bounds.left, leftMax))
    if (movesRight) right = (box.right + dx).coerceIn(minOf(bounds.right, maxOf(bounds.left, rightMin)), bounds.right)
    if (movesTop) top = (box.top + dy).coerceIn(bounds.top, maxOf(bounds.top, topMax))
    if (movesBottom) bottom = (box.bottom + dy).coerceIn(minOf(bounds.bottom, maxOf(bounds.top, bottomMin)), bounds.bottom)

    return ViewRect(left, top, right, bottom)
}

/** 框内单指拖：整个框平移，⛔ 不越出 [bounds]（贴边就停住，而不是缩一半）。 */
internal fun moveCropBox(box: ViewRect, dx: Float, dy: Float, bounds: ViewRect): ViewRect {
    var left = box.left + dx
    var top = box.top + dy
    if (left + box.width > bounds.right) left = bounds.right - box.width
    if (top + box.height > bounds.bottom) top = bounds.bottom - box.height
    left = left.coerceIn(bounds.left, maxOf(bounds.left, bounds.right - box.width))
    top = top.coerceIn(bounds.top, maxOf(bounds.top, bounds.bottom - box.height))
    return ViewRect(left, top, left + box.width, top + box.height)
}

/**
 * 唯一一处"视口 → 位图像素"的换算：框选的那一块对应位图里哪几个像素。
 *
 * 取整用四舍五入（边界上差半像素肉眼看不出来，但**至少要 1 像素**：框小到亚像素时，
 * 裁一张 1×1 也总比崩掉或存出空图好）。框为空 / 图还没量到 / 位图尺寸非法时返回 null
 * （调用方据此走"不裁切"）。
 */
internal fun cropToPixels(
    box: ViewRect,
    t: ViewTransform,
    imageW: Int,
    imageH: Int,
): PixelRect? {
    if (imageW <= 0 || imageH <= 0) return null
    if (t.width <= 0f || t.height <= 0f) return null
    if (box.width <= 0f || box.height <= 0f) return null
    val scaleX = imageW / t.width
    val scaleY = imageH / t.height
    val left = ((box.left - t.offsetX) * scaleX).roundToInt()
    val top = ((box.top - t.offsetY) * scaleY).roundToInt()
    val right = ((box.right - t.offsetX) * scaleX).roundToInt()
    val bottom = ((box.bottom - t.offsetY) * scaleY).roundToInt()
    val l = left.coerceIn(0, imageW - 1)
    val tp = top.coerceIn(0, imageH - 1)
    val r = right.coerceIn(l + 1, imageW)
    val b = bottom.coerceIn(tp + 1, imageH)
    return PixelRect(l, tp, r, b)
}
