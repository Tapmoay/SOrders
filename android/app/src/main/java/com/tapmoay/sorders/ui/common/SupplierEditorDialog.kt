package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.Notes
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Place
import androidx.compose.material.icons.filled.Storefront
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
import com.tapmoay.sorders.data.remote.dto.SupplierDto
import com.tapmoay.sorders.ui.theme.CashOut

/** 建 / 改档案：**表单行走共用那一套**（`ui/common/FormRows.kt`）。
 *
 * ⚠️ 这里是**共用行、不是 `OutlinedTextField`**：设计规范 §5.0 把「分组一律白卡 + 输入用无边框行」
 *    定成了全局规范（用户 2026-09-22：「把他们改进这种**白色的卡片样式**……**所有都要这样子去改**」），
 *    判据 `_tools/qa/_check_form_panel_style.py` 盯着"全库描边输入框总数只许减不许增"。
 *    对话框本身就是那张"卡"，所以行**不再外面再套一层 SectionCard**（框套框正是用户要消灭的东西）。
 *
 * ## 为什么住在 `ui/common/` 而不是供应商页（2026-10-07，CHG-0068 / 台账 L-40）
 * 用户原话：「**没有建供应商的话他可以在这里直接选择新建供应商**，省得又跑到那边去」——
 * 「这里」＝**采购单的选供应商弹层**与**进项票的选供应商弹层**两处。既然两处都要就地新建，
 * 弹窗就只能有一份实现：抄第二份出来的那天，两个页面就会开始各自漂移（这正是本单要避免的）。
 * ⛔ 谁都不许再在本文件之外写第三份「建供应商」表单。
 *
 * @param initial 非空 = 改资料（字段带出原值）；null = 新建
 * @param minimal 就地新建用的最小形态：**只问名称 ＋ 电话**（其余字段留空，
 *   地址/备注以后到「供应商 / 厂商」页补）—— 用户 2026-10-07 拍板的四问之一。
 *   非 minimal（供应商页那两处）＝全字段，形态与以前逐字一致。
 */
@Composable
fun SupplierEditorDialog(
    initial: SupplierDto?,
    onDismiss: () -> Unit,
    onSave: (name: String, contact: String, phone: String, address: String, remark: String) -> Unit,
    minimal: Boolean = false,
) {
    var name by remember { mutableStateOf(initial?.name.orEmpty()) }
    var contact by remember { mutableStateOf(initial?.contactName.orEmpty()) }
    var phone by remember { mutableStateOf(initial?.phone.orEmpty()) }
    var address by remember { mutableStateOf(initial?.address.orEmpty()) }
    var remark by remember { mutableStateOf(initial?.remark.orEmpty()) }

    CardAlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Text(
                when {
                    minimal -> "新建供应商"
                    initial == null -> "新增供应商 / 厂商"
                    else -> "改资料"
                },
            )
        },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                FormInputRow(
                    label = "名称", value = name, onValueChange = { name = it },
                    placeholder = "如 永盛食品有限公司", required = true,
                    icon = Icons.Default.Storefront, iconTint = Color(CashOut),
                )
                if (!minimal) {
                    FormInputRow(
                        label = "联系人", value = contact, onValueChange = { contact = it },
                        placeholder = "对方的联系人",
                        icon = Icons.Default.Person, iconTint = Color(CashOut),
                    )
                }
                FormInputRow(
                    // 电话只让数字进来（规则唯一实现在 core/InputRules.kt）。后端那一侧要求
                    // 7~12 位数字 —— 前端在这一步就把汉字/字母挡在外面，别让用户敲完才吃一个 422。
                    label = "电话", value = phone, onValueChange = { phone = InputRules.phoneInput(it) },
                    placeholder = "7~12 位数字，座机写 07521234567",
                    keyboardType = KeyboardType.Phone,
                    icon = Icons.Default.Call, iconTint = Color(CashOut),
                )
                if (!minimal) {
                    FormTextAreaRow(
                        label = "地址", value = address, onValueChange = { address = it },
                        placeholder = "对方的地址（可选）", minLines = 2,
                        icon = Icons.Default.Place, iconTint = Color(CashOut),
                    )
                    FormInputRow(
                        label = "备注", value = remark, onValueChange = { remark = it },
                        placeholder = "一句话（可选）",
                        icon = Icons.Default.Notes, iconTint = Color(CashOut),
                    )
                } else {
                    Spacer(Modifier.height(4.dp))
                    // 口径 ③：新建完要有**一句**提示（两处弹层共用这一份，不各写一遍）。
                    Hint(
                        text = "地址、备注以后可以在「供应商 / 厂商」页补",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        },
        confirmButton = {
            TextButton(
                enabled = name.isNotBlank(),
                onClick = { onSave(name.trim(), contact.trim(), phone.trim(), address.trim(), remark.trim()) },
            ) { Text(if (minimal) "建好并选中" else "保存") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}
