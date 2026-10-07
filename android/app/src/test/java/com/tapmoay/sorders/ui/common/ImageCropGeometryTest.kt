package com.tapmoay.sorders.ui.common

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 裁切框几何（CHG-0072 / 台账 L-33）——**纯 JUnit**，没有 Robolectric、没有 Compose。
 *
 * 这一层之所以能被单测，就是因为它一行 Android 都没有（见文件头 KDoc）：
 * 手势、位图、弹层那三样留在 [ImageCropDialog] 里靠真机验收，换算与夹取全钉在这里。
 */
class ImageCropGeometryTest {

    private val eps = 0.01f

    private fun assertRect(expected: ViewRect, actual: ViewRect, tag: String = "") {
        assertEquals(tag + " left", expected.left, actual.left, eps)
        assertEquals(tag + " top", expected.top, actual.top, eps)
        assertEquals(tag + " right", expected.right, actual.right, eps)
        assertEquals(tag + " bottom", expected.bottom, actual.bottom, eps)
    }

    // ---------- fitTransform：刚好铺满、居中 ----------

    @Test
    fun `横图按宽度铺满、上下居中`() {
        val t = fitTransform(2000, 1000, 1000f, 1000f)
        assertEquals(1000f, t.width, eps)
        assertEquals(500f, t.height, eps)
        assertEquals(0f, t.offsetX, eps)
        assertEquals(250f, t.offsetY, eps)
    }

    @Test
    fun `竖图按高度铺满、左右居中`() {
        val t = fitTransform(1000, 2000, 1000f, 1000f)
        assertEquals(500f, t.width, eps)
        assertEquals(1000f, t.height, eps)
        assertEquals(250f, t.offsetX, eps)
        assertEquals(0f, t.offsetY, eps)
    }

    @Test
    fun `视口还没量到时不炸`() {
        val t = fitTransform(1000, 1000, 0f, 0f)
        assertEquals(0f, t.width, eps)
        assertNull(cropToPixels(ViewRect(0f, 0f, 1f, 1f), t, 1000, 1000))
    }

    // ---------- clampTransform：不许比 fit 小 / 不许超过 4 倍 / 必须盖住视口 ----------

    @Test
    fun `缩得比铺满还小会被拉回铺满`() {
        val fit = fitTransform(2000, 1000, 1000f, 1000f)
        val shrunk = zoomTransform(fit, 500f, 500f, 0.3f, 1000f, 1000f)
        assertEquals(fit.width, shrunk.width, eps)
        assertEquals(fit.height, shrunk.height, eps)
    }

    @Test
    fun `放得超过四倍会被截在四倍`() {
        val fit = fitTransform(2000, 1000, 1000f, 1000f)
        val zoomed = zoomTransform(fit, 500f, 500f, 50f, 1000f, 1000f)
        assertEquals(fit.width * CROP_MAX_ZOOM, zoomed.width, eps)
    }

    @Test
    fun `图片永远盖住视口（拖不出白边）`() {
        val fit = fitTransform(2000, 1000, 1000f, 1000f)
        val right = clampTransform(fit.copy(offsetX = 100f, offsetY = 100f), 1000f, 1000f)
        assertEquals(0f, right.offsetX, eps)
        // 横图在方视口里上下本来就有留白（图高 500 < 视口 1000）：这条轴没有自由度，只能居中
        assertEquals(250f, right.offsetY, eps)
        val left = clampTransform(fit.copy(offsetX = -9999f, offsetY = -9999f), 1000f, 1000f)
        assertEquals(1000f - left.width, left.offsetX, eps)
        assertEquals(250f, left.offsetY, eps)
    }

    @Test
    fun `捏合时手指按住的那一点不动`() {
        // 用**方图铺方视口**：放大之后两个轴都真的可以挪，焦点不动才验得出来
        // （横图放大后上下那条轴被"必须盖住视口"钉死，焦点在纵轴上动不了）
        val fit = fitTransform(1000, 1000, 1000f, 1000f)
        val focusX = 300f
        val focusY = 400f
        // 焦点在图上的相对位置（0..1）
        val beforeX = (focusX - fit.offsetX) / fit.width
        val beforeY = (focusY - fit.offsetY) / fit.height
        val zoomed = zoomTransform(fit, focusX, focusY, 2f, 1000f, 1000f)
        assertEquals(beforeX, (focusX - zoomed.offsetX) / zoomed.width, 0.001f)
        assertEquals(beforeY, (focusY - zoomed.offsetY) / zoomed.height, 0.001f)
    }

    @Test
    fun `平移整张图也盖住视口`() {
        val fit = fitTransform(1000, 2000, 1000f, 1000f)
        // 竖图在方视口里左右有留白：这条轴没有自由度，怎么拖都回到居中
        val moved = panTransform(fit, 400f, 0f, 1000f, 1000f)
        assertEquals(250f, moved.offsetX, eps)
    }

    @Test
    fun `可见图区域只算图本身（不含上下留白）`() {
        val fit = fitTransform(2000, 1000, 1000f, 1000f)
        assertRect(ViewRect(0f, 250f, 1000f, 750f), visibleImageRect(fit, 1000f, 1000f))
    }

    // ---------- 初始框 / 夹取 ----------

    @Test
    fun `初始框每边内缩百分之六`() {
        val box = initialCropBox(ViewRect(0f, 0f, 1000f, 1000f), 48f)
        assertRect(ViewRect(60f, 60f, 940f, 940f), box)
    }

    @Test
    fun `图比最小框还小时初始框就等于图`() {
        val visible = ViewRect(0f, 0f, 40f, 40f)
        assertRect(visible, initialCropBox(visible, 48f))
    }

    @Test
    fun `框跑到图外会被整体拉回来（尺寸不变）`() {
        val bounds = ViewRect(0f, 0f, 1000f, 1000f)
        // 右下越界 → 往左上挪回去，框还是 600×600（手机裁切的手感：拖到边上就停，不会越拖越小）
        assertRect(ViewRect(400f, 400f, 1000f, 1000f), clampCropBox(ViewRect(600f, 600f, 1200f, 1200f), bounds, 48f))
        // 左上越界 → 贴回 0，框还是 500×500
        assertRect(ViewRect(0f, 0f, 500f, 500f), clampCropBox(ViewRect(-100f, -100f, 400f, 400f), bounds, 48f))
        // 框比图还大 → 才贴着 bounds 缩（这是唯一的"缩小"情形）
        assertRect(bounds, clampCropBox(ViewRect(-50f, -50f, 1200f, 1200f), bounds, 48f))
    }

    // ---------- 命中与拖动 ----------

    @Test
    fun `角比边优先`() {
        val box = ViewRect(100f, 100f, 500f, 500f)
        assertEquals(CropHandle.TOP_LEFT, hitCropHandle(box, 100f, 100f, 28f))
        assertEquals(CropHandle.TOP_RIGHT, hitCropHandle(box, 500f, 100f, 28f))
        assertEquals(CropHandle.BOTTOM_LEFT, hitCropHandle(box, 100f, 500f, 28f))
        assertEquals(CropHandle.BOTTOM_RIGHT, hitCropHandle(box, 500f, 500f, 28f))
    }

    @Test
    fun `四条边的中点各认各的`() {
        val box = ViewRect(100f, 100f, 500f, 500f)
        assertEquals(CropHandle.TOP, hitCropHandle(box, 300f, 100f, 28f))
        assertEquals(CropHandle.BOTTOM, hitCropHandle(box, 300f, 500f, 28f))
        assertEquals(CropHandle.LEFT, hitCropHandle(box, 100f, 300f, 28f))
        assertEquals(CropHandle.RIGHT, hitCropHandle(box, 500f, 300f, 28f))
    }

    @Test
    fun `框内是移动、框外谁也不管`() {
        val box = ViewRect(100f, 100f, 500f, 500f)
        assertEquals(CropHandle.INSIDE, hitCropHandle(box, 300f, 300f, 28f))
        assertEquals(CropHandle.NONE, hitCropHandle(box, 700f, 700f, 28f))
    }

    @Test
    fun `拖角动两条边、拖边只动一条边`() {
        val box = ViewRect(100f, 100f, 500f, 500f)
        val bounds = ViewRect(0f, 0f, 1000f, 1000f)
        val byCorner = dragCropHandle(box, CropHandle.TOP_LEFT, -20f, -30f, bounds, 48f)
        assertRect(ViewRect(80f, 70f, 500f, 500f), byCorner)
        val byLeft = dragCropHandle(box, CropHandle.LEFT, -20f, -30f, bounds, 48f)
        assertRect(ViewRect(80f, 100f, 500f, 500f), byLeft)
        val byRight = dragCropHandle(box, CropHandle.RIGHT, 20f, 30f, bounds, 48f)
        assertRect(ViewRect(100f, 100f, 520f, 500f), byRight)
    }

    @Test
    fun `框顶到最小边就粘住、不翻面`() {
        val box = ViewRect(100f, 100f, 500f, 500f)
        val bounds = ViewRect(0f, 0f, 1000f, 1000f)
        // 左边往右猛拖：最多拖到 right - minSide（452），不会越过右边
        val squeezed = dragCropHandle(box, CropHandle.LEFT, 9999f, 0f, bounds, 48f)
        assertEquals(500f - 48f, squeezed.left, eps)
        assertEquals(500f, squeezed.right, eps)
        assertTrue(squeezed.width >= 48f - eps)
    }

    @Test
    fun `拖动时框不出图`() {
        val box = ViewRect(100f, 100f, 500f, 500f)
        val bounds = ViewRect(0f, 0f, 1000f, 1000f)
        assertEquals(0f, dragCropHandle(box, CropHandle.LEFT, -9999f, 0f, bounds, 48f).left, eps)
        assertEquals(1000f, dragCropHandle(box, CropHandle.RIGHT, 9999f, 0f, bounds, 48f).right, eps)
        assertEquals(0f, dragCropHandle(box, CropHandle.TOP, 0f, -9999f, bounds, 48f).top, eps)
        assertEquals(1000f, dragCropHandle(box, CropHandle.BOTTOM, 0f, 9999f, bounds, 48f).bottom, eps)
    }

    @Test
    fun `框里拖动是整块平移、贴边就停`() {
        val box = ViewRect(100f, 100f, 500f, 500f)
        val bounds = ViewRect(0f, 0f, 1000f, 1000f)
        val moved = moveCropBox(box, 50f, -20f, bounds)
        assertRect(ViewRect(150f, 80f, 550f, 480f), moved)
        val stuck = moveCropBox(box, 9999f, 9999f, bounds)
        assertRect(ViewRect(600f, 600f, 1000f, 1000f), stuck)
        assertEquals(box.width, stuck.width, eps)
    }

    // ---------- 框 → 位图像素 ----------

    @Test
    fun `像素换算用四舍五入并夹回图内`() {
        // 1000x2000 的图铺在 500x1000 的视口里 = 正好 1:2
        val t = fitTransform(1000, 2000, 500f, 1000f)
        val px = cropToPixels(ViewRect(100.4f, 200f, 300.6f, 600f), t, 1000, 2000)!!
        assertEquals(201, px.left)
        assertEquals(400, px.top)
        assertEquals(601, px.right)
        assertEquals(1200, px.bottom)
        val clamped = cropToPixels(ViewRect(-50f, -50f, 100f, 100f), t, 1000, 2000)!!
        assertEquals(0, clamped.left)
        assertEquals(0, clamped.top)
        assertEquals(200, clamped.right)
        assertEquals(200, clamped.bottom)
    }

    @Test
    fun `框小到亚像素也至少裁一像素`() {
        val t = fitTransform(1000, 2000, 500f, 1000f)
        val px = cropToPixels(ViewRect(250f, 500f, 250.1f, 500.1f), t, 1000, 2000)!!
        assertEquals(1, px.right - px.left)
        assertEquals(1, px.bottom - px.top)
    }

    @Test
    fun `空框与没量到都不裁`() {
        val t = fitTransform(1000, 2000, 500f, 1000f)
        assertNull(cropToPixels(ViewRect(100f, 100f, 100f, 100f), t, 1000, 2000))
        assertNull(cropToPixels(ViewRect(0f, 0f, 100f, 100f), t, 0, 0))
    }
}
