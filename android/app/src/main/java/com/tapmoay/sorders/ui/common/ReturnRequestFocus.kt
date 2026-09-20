package com.tapmoay.sorders.ui.common

import com.tapmoay.sorders.data.remote.dto.ReturnRequestDto

/** [focusReturnRequestFirst] 的结果：排好序的列表 + **有没有真的找到**那一条。 */
data class FocusedReturnRequests(
    val items: List<ReturnRequestDto>,
    /** true = 这条申请**确实在这份列表里**（已经排到第一位）；false = 没找到，列表原样返回。 */
    val found: Boolean,
)

/**
 * 定位失败时列表上方那一行说明的**唯一一份文案**（货主端与派单端共用）。
 *
 * ⛔ 两页各写一遍的后果不是"多几个字"：改了一处另一处就分叉，而这句话是用户
 *    "点开通知却没看到那一条"时唯一的解释。⛔ 文案里不许出现 Markdown 星号
 *    （`Text` 不渲染 Markdown，会原样显示）。
 */
const val RETURN_REQUEST_FOCUS_MISS = "没找到那条退货申请（可能已经被处理掉了），下面是全部。"

/**
 * 把「从消息中心点进来的那一张申请」排到列表**最前面**（两个退货申请页共用这一份）。
 *
 * ## 为什么是"排到最前"而不是"过滤成只剩它一条"
 * 用户点通知的意图是"看这一条"，但看完往往顺手要看旁边的（同一张单的另一条申请、
 * 或者同一天提的别的单）。只显示一条等于把列表弄没了，还得让他返回再进一次。
 * 排到最前 + 打一枚标记，两件事同时成立：**一眼看到它**，且列表还是完整的。
 *
 * ## 为什么找不到时必须**如实返回 found = false**
 * 找不到有三种正常原因：申请被处理掉之后又不在这一档、列表被截断（后端一次最多 200 条）、
 * 或者这条消息本来就不是这个账户的（派单员的消息列表是全局视图）。
 * ⛔ 这三种情况下**不许**白屏、也不许假装定位到了 —— 调用方拿 found=false 在列表上方
 * 加一行说明，列表照常显示（"没找到那条申请（可能已经被处理掉了），下面是全部"）。
 *
 * @param focusRequestId 要定位的申请单号（<= 0 = 不定位，原样返回）
 */
fun focusReturnRequestFirst(
    items: List<ReturnRequestDto>,
    focusRequestId: Long,
): FocusedReturnRequests {
    if (focusRequestId <= 0L) return FocusedReturnRequests(items, found = false)
    val hit = items.firstOrNull { it.id == focusRequestId }
        ?: return FocusedReturnRequests(items, found = false)
    return FocusedReturnRequests(
        items = listOf(hit) + items.filter { it.id != focusRequestId },
        found = true,
    )
}
