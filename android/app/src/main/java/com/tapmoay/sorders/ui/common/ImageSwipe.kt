package com.tapmoay.sorders.ui.common

import kotlin.math.abs

/**
 * # 看大图时「横向滑动翻页」的判据 —— 纯函数，零 Compose 依赖
 *
 * 用户 2026-10-07（台账 L-37）：「我想看**下一张照片就是左右滑动不行，非要按按钮**。
 * 这个不要，**左右滑动这样更方便**，就是真实的（相册）操作」；同一条里还定了两条边界：
 * 「**不要不要不要循环**啊，就是**可以有滑到底**的」—— 到头即停，不环绕。
 *
 * ## 为什么单独成文件
 * 这一条的手势那一层（[ImagePreviewDialog]）里同时住着四件事：单击关闭、双击放大、双指缩放、
 * 放大后拖动。混在一起的"手指逻辑"在 JVM 单测里**验不了**（要真手指）。把"这一次横滑够不够
 * 翻一页、往哪翻、到头了没有"拆成这里的一个纯函数之后，阈值、第一张往右、最后一张往左、
 * 只有一张、还没量到宽 —— 这些边界都能逐条钉死（见 `ImageSwipeTest`）。
 *
 * ## 口径
 * - 位移要过**整宽的 18%** 才算"想翻页"（低于它 = 手抖 / 只是想挪一下，回正不翻）；
 * - 向左拖（`accumX < 0`）＝下一张，向右拖＝上一张；
 * - **到头即停**：第一张往右、最后一张往左都返回 0（⛔ 不环绕）；
 * - 宽度还没量到（`boxWidth <= 0`）时不翻 —— 宁可不动，也不要"翻到一张没人要的图"。
 */
internal const val SWIPE_PAGE_FRACTION = 0.18f

/**
 * 松手时定夺：这一次横向拖动要不要翻页、往哪翻。
 *
 * @param accumX   这一次横滑**累积**的横向位移（px，向右为正；放大后只有"贴边还继续拖"的那一截进得来）
 * @param boxWidth 预览区宽度（px；还没量到时传 0）
 * @param atFirst  当前是不是第一张
 * @param atLast   当前是不是最后一张
 * @return `0` = 不翻页（图回正）；`+1` = 下一张；`-1` = 上一张
 */
internal fun swipePageStep(accumX: Float, boxWidth: Int, atFirst: Boolean, atLast: Boolean): Int {
    if (boxWidth <= 0 || accumX.isNaN()) return 0
    if (abs(accumX) < boxWidth * SWIPE_PAGE_FRACTION) return 0
    return if (accumX < 0f) {
        if (atLast) 0 else 1
    } else {
        if (atFirst) 0 else -1
    }
}
