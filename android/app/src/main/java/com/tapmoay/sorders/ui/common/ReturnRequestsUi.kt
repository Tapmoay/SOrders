package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.data.remote.dto.ReturnRequestDto

/**
 * 退货申请两端（派单员待办 / 货主我的申请）**页面上**共用的三小块（2026-09-21 精简轮）。
 *
 * 上一轮把两端的 **ViewModel** 收成了一个内核；这一轮收**页面上的重复**：
 * 档位标签、定位提示那一行、以及行首那一段（"消息里点进来的这一条"徽章 + 订单号 + 状态）。
 * 三段都是**逐字抄的两遍**，而它们各自都有"必须两端一致"的理由：
 * · 定位徽章是用户"点通知进来后确认就是这一条"的唯一依据；
 * · 待处理那一档的张数必须挂在**同一档**上（两页的档位顺序相反，按下标写很容易标错档）；
 * · 定位失败的说明必须两端同形（文案本身只有一处：[RETURN_REQUEST_FOCUS_MISS]）。
 */

/**
 * 档位标签：**待处理那一档**带上张数（后端给的 `pending_count`）。
 *
 * ⚠️ 判据是档位的 **key**（`"pending"`）而不是下标：两页的档位顺序**相反**
 * （派单员是「全部 / 待处理」，货主是「待处理 / 全部」），按下标写就是"抄了对方那一行才标对"。
 * ⛔ 张数为 0 时不加 —— 否则用户看到「待处理 0」还得点进去确认一次。
 */
fun returnTabLabels(tabs: List<ReturnTab>, pendingCount: Int): List<String> =
    tabs.map { t ->
        if (t.key == "pending" && pendingCount > 0) "${t.label} $pendingCount" else t.label
    }

/**
 * 定位**没找到**时的一行说明（列表照常显示全部）。
 *
 * ⛔ 不写成错误页/白屏：那会让用户以为这一页坏了，而事实只是"这条申请不在这份列表里"。
 */
@Composable
fun ReturnRequestsFocusNotice(notice: String?) {
    if (notice == null) return
    Text(
        notice,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
    )
}

/**
 * 行首那一段：**定位徽章**（可选）+ 订单号 + 状态徽章。两端的行都从这里往下接各自的内容。
 *
 * 徽章写明"为什么它在最前面"——用户点完通知落进来时，一眼要能确认"就是这一条"，
 * 而不是自己在几十行里找。⚠️ 文案里不许出现 Markdown 星号（`Text` 不渲染，会原样显示）。
 */
@Composable
fun ReturnRequestsHeading(req: ReturnRequestDto, focused: Boolean) {
    if (focused) {
        Surface(
            color = MaterialTheme.colorScheme.primary,
            shape = RoundedCornerShape(50),
        ) {
            Text(
                "消息里点进来的这一条",
                color = MaterialTheme.colorScheme.onPrimary,
                style = MaterialTheme.typography.labelSmall,
                modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
            )
        }
        Spacer(Modifier.height(8.dp))
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(
            "订单 #" + req.orderNo,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.weight(1f),
        )
        // 中文名**只用后端给的那一个**（`statusLabel`）：这一页不写状态映射，
        // 否则后端加了新状态，界面上就直接印原始码。
        ReturnRequestStatusChip(status = req.status, label = req.statusLabel)
    }
}
