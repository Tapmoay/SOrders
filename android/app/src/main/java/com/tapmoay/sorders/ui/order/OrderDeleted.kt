package com.tapmoay.sorders.ui.order

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

/**
 * 「这张单被派单员删进回收站了」——说人话的那一屏（测试台账 TA-06 → BUG-0027）。
 *
 * 病灶（真机实测，2026-10-10）：派单员把一张**在途**单删进回收站之后，司机端那张旧卡片
 * 还留在列表里、还能点开；点开走 `GET /orders/{id}`，后端回 404，于是司机看到的是
 * 一句「订单不存在」+ 一个「重试」按钮 —— 单子明明刚才还在，重试一百次也回不来，
 * 而且没人告诉他是谁把它弄没了。
 *
 * ⛔ 不动后端那 404：`_get_order_scoped` 用 404 而不是 403 是**故意的**（否则能从状态码
 *    差异反推「有一张我看不到的已删除单」）。所以文案在两边各钉一半：
 *    后端把 detail 换成 [HINTS] 里的两句人话（只有当事人看得见），客户端认得出它、
 *    换成「已被派单员删除 + 返回」的这一屏。
 *
 * ⛔ 也不许把别的错误认成它：把「网络连接失败」说成「订单被删了」比不说还坏 ——
 *    司机会以为活没了（[isDeletedNotice] 只认后端那两句原文）。
 */
object OrderDeleted {

    /**
     * 后端软删 404 的两种 detail（`backend/app/api/v1/orders_common.py` 的 `DELETED_ORDER_NOTICES`）。
     * 两句的分工：在途单（DISPATCHED/ACCEPTED）说「已被派单员删除」，其余说「已被删除」。
     * ⚠️ 后端改文案时这里要同步 —— [OrderDeletedTest] 按字面量钉着这句话。
     */
    val HINTS: List<String> = listOf(
        "订单已被删除，如需找回请联系派单员从回收站恢复。",
        "订单已被派单员删除，如需找回请联系派单员从回收站恢复。",
    )

    /** 这条错误消息是不是「被派单员删了」。只认真子串，不做模糊匹配（宁可不说，不许误说）。 */
    fun isDeletedNotice(message: String?): Boolean {
        if (message.isNullOrEmpty()) return false
        return HINTS.any { message.contains(it) }
    }
}

/**
 * 已删除单的详情页替代内容：一句人话 + 一条出路。
 *
 * 为什么不用 [com.tapmoay.sorders.ui.common.ErrorView]：它那个按钮是「重试」——对这张单
 * 重试是**永远不会成功**的动作（回收站里的单不会因为多刷一次就回来），按下去只会让人
 * 以为是自己网络的问题。这里给的是「返回」（回到列表，那张卡已经不在里面了）。
 */
@Composable
fun OrderDeletedPanel(message: String, onBack: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxWidth().padding(vertical = 32.dp, horizontal = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Icon(
            Icons.Default.Delete,
            contentDescription = null,
            modifier = Modifier.size(56.dp),
            tint = MaterialTheme.colorScheme.outline,
        )
        Spacer(Modifier.height(12.dp))
        Text(
            "这笔订单已被派单员删除",
            style = MaterialTheme.typography.titleMedium,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(8.dp))
        Text(
            message,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(16.dp))
        OutlinedButton(onClick = onBack) { Text("返回") }
    }
}
