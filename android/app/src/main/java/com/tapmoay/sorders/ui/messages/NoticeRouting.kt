package com.tapmoay.sorders.ui.messages

import com.tapmoay.sorders.ui.nav.Role
import com.tapmoay.sorders.ui.nav.Routes
import kotlinx.serialization.json.JsonElement

/**
 * 「点这条通知该去哪一页」——**唯一一处**按 `type` 路由的地方（纯函数：不碰 Compose、不碰网络）。
 *
 * ## 为什么要有这个文件（用户 2026-09-21 的原话）
 * 「到消息中心哦。其实本来就要做到直达的」——以前点一条「退货申请待处理」只会把消息标成已读，
 * 派单员还得自己从工作台摸到「退货申请」那一页，再在一串申请里找是哪一张；
 * 货主收到「已办理/被驳回/已关闭」也一样，只能自己去翻。
 * 现在点它就直接落在对应那一页、并**定位到那一张**（`?focus=<申请单号>`）。
 *
 * ## 三个 `type` 各自的角色**是后端定的，客户端不许自己发明**
 * 见 `backend/app/services/message_center.py` 的三个发布函数与 `_return_request_payload`：
 *  · `order.return_request`          → 只发给**全体派单员**（货主提交时）
 *  · `order.return_request.done`     → 只发给**那一个货主**（派单员办理完）
 *  · `order.return_request.rejected` → 只发给**那一个货主**（派单员驳回）
 *  · `order.return_request.closed`   → 只发给**那一个货主**（派单员在订单管理里直接退了货，
 *    那张申请被自动关闭；2026-09-21 新加的那一条规则）
 *
 * ⚠️ **为什么必须再按角色判一次**，而不是"看 type 就跳"：
 *   派单员的消息列表是**全局视图**（后端对派单员不带 `recipient_id` 查询时不加收件人过滤，
 *   见 `notifications.py` 那段与 `MessagesViewModel` 的注释），所以一个派单员的列表里**混着
 *   发给货主的消息**。照着 `type` 跳的话，他点一条 `.done` 就会被送到货主那一页 ——
 *   而那一页的接口要 `ORDER_RETURN_REQUEST` 权限（他只有 `ORDER_RETURN`）→ 必然 403。
 *   「点了必然失败」的入口是本仓库明令禁止的，所以角色对不上时**退回老行为**（有单号就开订单详情）。
 *
 * ⚠️ 角色一律用**登录时缓存的 key 原文**比较，⛔ 不经过 `Role.fromKey`：
 *   那个函数对认不出的 key 会**回落成 SHIPPER**（`Role.fromKey("") == SHIPPER`），
 *   于是"还没恢复出会话"的那一瞬间会被当成货主，把人送进货主那一页。
 *
 * @param roleKey 当前登录角色的 key（`shipper` / `dispatcher` / …），null = 还不知道
 * @param type 通知类型（后端写的那个值，见上表）
 * @param payload 通知载荷（`request_id` / `order_id` / `order_no` / `items` …）
 * @return 要导航到的**整条路由**；null = 这条通知不走这套直达（调用方按老规矩处理）
 */
fun noticeReturnRoute(
    roleKey: String?,
    type: String,
    payload: Map<String, JsonElement>?,
): String? {
    val requestId = payload
        ?.get(KEY_REQUEST_ID)
        ?.toString()
        ?.toLongOrNull()
        // ⛔ payload 里没有 request_id 就不能"跳过去再说"：那一页有几十上百条申请，
        //    落到列表顶部等于没直达，用户还得自己找 —— 不如照旧开订单详情。
        ?: return null
    if (requestId <= 0L) return null

    return when {
        // 派单员收到"有人申请退货" → 派单端的「退货申请」待办页（唯一能真的退货的那一页）
        roleKey == Role.DISPATCHER.key && type == TYPE_TO_DISPATCHERS ->
            Routes.dispatcherReturnRequests(requestId)

        // 货主收到"办完了 / 被驳回 / 被自动关闭" → 货主端的「我的退货申请」
        roleKey == Role.SHIPPER.key && type in TYPES_TO_SHIPPER ->
            Routes.shipperReturnRequests(requestId)

        else -> null
    }
}

/** 载荷里那张申请单的编号键（与后端 `_return_request_payload` 里的键名一致，别改）。 */
const val KEY_REQUEST_ID = "request_id"

/** 货主提交 → 全体派单员。 */
const val TYPE_TO_DISPATCHERS = "order.return_request"

/** 派单员办理 → 那一个货主。 */
const val TYPE_DONE = "order.return_request.done"

/** 派单员驳回 → 那一个货主（理由在 payload.reason 里，页面上显示）。 */
const val TYPE_REJECTED = "order.return_request.rejected"

/** 派单员在订单管理里直接退了货 → 申请被自动关闭（2026-09-21 用户拍板那条规则）。 */
const val TYPE_CLOSED = "order.return_request.closed"

/** 三种"回到申请人手里"的结果 —— **`CLOSED` 必须在里面**（它是这次新加的，漏了就只能停在消息详情）。 */
val TYPES_TO_SHIPPER = setOf(TYPE_DONE, TYPE_REJECTED, TYPE_CLOSED)
