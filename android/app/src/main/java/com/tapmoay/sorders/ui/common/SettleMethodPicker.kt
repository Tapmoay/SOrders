package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.dp

/** 收款方式的四个选项 —— **收款单唯一的取值来源**（后端 `shipper_receipt.method` 的取值集）。
 *
 * 顺序与文案是用户看得见的东西：⛔ 不许各页自己排一遍（账本单张核销 / 批量核销 / 订单详情核销
 * 三处必须逐字一致）。
 */
val SETTLE_METHODS: List<Pair<String, String>> = listOf(
    "cash" to "现金",
    "transfer" to "转账",
    "wechat" to "微信",
    "arrears_settle" to "挂账结清",
)

/**
 * 收款方式那几个胶囊 —— **所有核销门共用这一份**（2026-10-07，CHG-0069）。
 *
 * 为什么要提到 `ui/common/`：这一份原来住在 `ui/dispatcher/LedgerPersonScreen.kt`（私有），
 * 那份注释写得很具体 ——「各写一份的后果很具体：单张核销加了"挂账结清"、批量核销没加，用户按批量
 * 收的时候就选不到这个方式，只能当"现金"收进去（报表上那笔钱的性质直接变了）」。
 * 订单详情底部那颗「核销」是**第三个**消费方，所以它必须吃同一份，⛔ 不许再抄。
 *
 * @param selected 当前选中的取值（`cash` / `transfer` / `wechat` / `arrears_settle`）
 * @param onSelect 用户点了某一颗（由调用方决定写回哪儿：账本页写进 VM，订单详情写进本页状态）
 */
@Composable
fun SettleMethodPicker(selected: String, onSelect: (String) -> Unit) {
    Text("收款方式", style = MaterialTheme.typography.titleSmall)
    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        SETTLE_METHODS.forEach { (v, l) ->
            FilterChip(
                selected = selected == v,
                onClick = { onSelect(v) },
                label = { Text(l, maxLines = 1) },
            )
        }
    }
}
