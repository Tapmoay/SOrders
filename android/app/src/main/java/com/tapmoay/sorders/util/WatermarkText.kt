package com.tapmoay.sorders.util

/**
 * 水印上到底画哪几行 —— **纯函数**（不碰任何 android.* 的图形对象，JVM 单测直接钉）。
 *
 * 台账 L-22（用户原话）：「如果有些信息是补上去的照片的话，会有一些水印……
 * 那个水印就是会显示时间，然后这个照片是被人补过的，就是说是补过的照片就可以了」。
 *
 * 于是两种照片、两套行数：
 * - **当场拍的**（送达照，OrderDetailScreen 的「拍照送达」）：两行 —— 时间 + 地点，一个字都没变；
 * - **事后补上来的**（详情页的「位置图片」：相册选 / 系统相机拍）：三行 —— 第三行是 [MAKEUP_TAG]。
 *
 * ⛔ 为什么文案与行数非要从这里出：绘制水印的 [Watermark.drawWatermark] 要真 Bitmap、真 Canvas，
 *    单测里跑不了；而「补拍那张到底多写了什么字」正是这件事的**唯一交付物**。
 *    把文案抽到这个纯函数里，测试才有东西可钉；界面上任何一处自己拼字面量都会让判据
 *    （_tools/qa/_check_place_photo_watermark.py）变红。
 */
object WatermarkText {

    /** 补拍标识（补拍那张的第三行）—— 事后补上来的照片专用。 */
    const val MAKEUP_TAG = "补拍 · 事后补录"

    /** 地点取不到时的兜底（与「拍照送达」同一条口径）。 */
    const val LOCATION_FALLBACK = "送达地点"

    /** 地点最多画这么多个字（再长就画不下了）。 */
    const val LOCATION_MAX = 60

    /**
     * 水印的每一行，从上到下。
     *
     * @param time 拍摄 / 补拍的时刻（形如 2026-10-06 12:30:00）—— 由调用方给，纯函数不读时钟。
     * @param locationText 地点；空或全空白 → [LOCATION_FALLBACK]。
     * @param tag 补拍标识；null 或空白 = 当场拍的（只有两行）。
     */
    fun lines(time: String, locationText: String, tag: String? = null): List<String> {
        val out = mutableListOf(time, locationText.take(LOCATION_MAX).ifBlank { LOCATION_FALLBACK })
        if (!tag.isNullOrBlank()) out += tag
        return out
    }
}
