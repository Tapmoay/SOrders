package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.ui.theme.CashOut

/**
 * 就地**建一份客户档案**（顺带把这张单的货主账号关联上去）—— 只问名称 ＋ 电话。
 *
 * ## 为什么需要它（2026-10-07，CHG-0069 / 台账 L-44 口径 ④）
 * 核销认的是**客户档案**（后端 `accounting_service.create_receipt` 拿 `order.shipper_id` 去比
 * `customer.user_id`），挂账单位与客户档案之间**没有直连** —— 于是"挂账 → 就地核销"会撞上
 * 「订单 X 无客户归属（临时货主收款需先关联客户档案）」这条 400（`accounting_service.py:405-406`）。
 * 用户口径：**在弹窗里就地建 / 关联**，与 L-40「就地新建供应商」同一族。
 *
 * ⚠️ 带 `user_id` 再建一次就是**关联**：后端 `customers.create_customer` 见到该 user 已有档案会
 *    把旧的那条原样返回（`backend/app/api/v1/customers.py:63-66`）—— 所以这里不需要先查一遍，
 *    ⛔ 也不许各页自己写第二份「建客户」表单（`ui/common/` 只此一份）。
 *
 * ⚠️ 表单行走**共用那一套**（`ui/common/FormRows.kt` 的无边框行）：设计规范 §5.0 把
 *    「分组一律白卡 + 输入用无边框行」定成全局规范，判据 `_tools/qa/_check_form_panel_style.py`
 *    盯着"全库描边输入框总数只许减不许增"。对话框本身就是那张卡，所以行外面**不再套 SectionCard**。
 *
 * @param initialName 预填的名字（一般带出这张单的货主名，用户改一下就能用）
 * @param initialPhone 预填的电话（一般留空 —— ⛔ 不许从别处猜）
 * @param busy 正在建（按钮转「处理中…」并锁住，防连点建出两条）
 */
@Composable
fun CustomerEditorDialog(
    initialName: String,
    initialPhone: String = "",
    busy: Boolean = false,
    onDismiss: () -> Unit,
    onSave: (name: String, phone: String) -> Unit,
) {
    var name by remember { mutableStateOf(initialName) }
    var phone by remember { mutableStateOf(initialPhone) }

    CardAlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("建客户档案") },
        text = {
            Column {
                Text(
                    "核销要记在客户档案上 —— 这位货主还没有档案，建一份并关联上，这笔账才收得回来。",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(8.dp))
                FormInputRow(
                    label = "名称", value = name, onValueChange = { name = it },
                    placeholder = "如 张老板（用货主自己的名字最好认）", required = true,
                    icon = Icons.Default.Person, iconTint = Color(CashOut),
                )
                FormInputRow(
                    // 电话只让数字进来（规则唯一实现在 core/InputRules.kt）。
                    label = "电话", value = phone, onValueChange = { phone = InputRules.phoneInput(it) },
                    placeholder = "7~12 位数字（可选）",
                    keyboardType = KeyboardType.Phone,
                    icon = Icons.Default.Call, iconTint = Color(CashOut),
                )
                Spacer(Modifier.height(4.dp))
                Hint(
                    text = "档案先记这两样；地址、授信以后到「货主管理」那一页补",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
        confirmButton = {
            TextButton(
                enabled = !busy && name.isNotBlank(),
                onClick = { onSave(name.trim(), phone.trim()) },
            ) { Text(if (busy) "处理中…" else "建好并核销") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}
