package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.UserSearch
import com.tapmoay.sorders.data.remote.dto.UserDto

/**
 * **代理下单：为谁下单**（选货主 / 填临时货主）—— 底部抽屉，**全 App 一份**。
 *
 * ## 为什么从弹窗改成抽屉（CHG-0007，用户 2026-09-28）
 * 用户原话：「派单员的选择货主为什么还是一个弹窗啊，干的太丑，改成**下拉选项下拉抽屉**啊，
 * 就是**底部抽屉**」。
 * 而且它本来就和这一页其它选择器（地址库 / 联系人 / 选商品）不是一家人 —— 那三个都是
 * `ModalBottomSheet`，只有它是 `AlertDialog`：**同一个页面上两种选择容器**，本身就是不一致。
 *
 * ## 为什么抽成公共件而不是写死在那一页
 * "选一个货主"在别处也有（账本「记一笔账」要选货主 / 填未注册的临时货主），
 * 口径必须一样：**能搜（姓名 / 手机号 / 后 4 位）、选中即关、临时货主与已注册二选一**。
 * ⛔ 各写一份的后果与「同一件事三个答案」那一类完全一样：在这页搜得到、在那页搜不到。
 *
 * @param selectedId 已选中的已注册货主（null = 没选或选的是临时货主）
 * @param tempName 临时货主（未注册）的名字；非空即表示"这一单是为他下的"
 * @param onPick 选中一位**已注册**货主（实现方负责清掉临时货主名字）
 * @param onPickTemp 填了一个**未注册**的临时货主名字（实现方负责清掉 shipperId）
 * @param title 抽屉标题（默认"为谁下单"；转货那一处传"转给谁"）
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ShipperPickerSheet(
    shippers: List<UserDto>,
    selectedId: Long?,
    tempName: String?,
    onPick: (Long) -> Unit,
    onPickTemp: (String) -> Unit,
    onDismiss: () -> Unit,
    /**
     * 抽屉标题。默认是"为谁下单"（下单页与记一笔账都这么叫）。
     *
     * ⚠️ 转货（CHG-0042）借这个抽屉选**收下这批货的**货主 —— 那件事不叫"下单"，
     * 标题照旧会把派单员看糊涂，所以留一个可传的标题，而不在这一页再抄一份选人抽屉。
     */
    title: String = "为谁下单",
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var keyword by remember { mutableStateOf("") }
    val kw = keyword.trim()
    // 搜索规则走**唯一实现**（`core/UserSearch`）：姓名 / 手机号 / **手机号后 4 位**。
    // ⛔ 与后端 `?q=`、名册页、司机候选那几处同一个口径 —— 别再就地写一遍。
    val shown = remember(shippers, kw) {
        if (kw.isBlank()) shippers
        else UserSearch.filter(shippers, kw, { it.fullName.ifBlank { it.username } }, { it.phone })
    }
    val shownTop = shown.take(100)

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
        Column(
            Modifier.fillMaxWidth().padding(horizontal = 20.dp).padding(bottom = 24.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    title,
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.weight(1f),
                )
                SheetCloseButton(onClick = onDismiss)
            }
            Spacer(Modifier.height(8.dp))
            // 临时货主（未注册）：填了它就是"这一单算他的" —— 与选中已注册货主**二选一**。
            Text("临时货主（未注册）", style = MaterialTheme.typography.labelLarge)
            Spacer(Modifier.height(4.dp))
            SoTextField(
                value = tempName ?: "",
                onValueChange = { onPickTemp(it) },
                placeholder = "直接填名字，例如「王老板」",
            )
            Hint(
                "填了就走临时货主：不建账号、不挂在他名下；名字要留在账上，所以要写清是谁。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(14.dp))
            Text("已注册货主", style = MaterialTheme.typography.labelLarge)
            Spacer(Modifier.height(6.dp))
            SoTextField(
                value = keyword,
                onValueChange = { keyword = it },
                placeholder = UserSearch.HINT,
            )
            Spacer(Modifier.height(6.dp))
            Column(Modifier.fillMaxWidth().heightIn(max = 420.dp).verticalScroll(rememberScrollState())) {
                if (shippers.isEmpty()) {
                    Text(
                        "暂无货主",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(vertical = 12.dp),
                    )
                } else if (shownTop.isEmpty()) {
                    Text(
                        "没有匹配「" + kw + "」的货主。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(vertical = 12.dp),
                    )
                }
                shownTop.forEach { s ->
                    val picked = selectedId != null && selectedId == s.id
                    Row(
                        Modifier.fillMaxWidth()
                            .clickable { onPick(s.id) }
                            .padding(horizontal = 8.dp, vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(
                                s.fullName.ifBlank { s.username },
                                style = MaterialTheme.typography.bodyLarge,
                                color = MaterialTheme.colorScheme.onSurface,
                            )
                            Text(
                                s.phone.ifBlank { "（没填手机号）" },
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        if (picked) {
                            Icon(
                                Icons.Default.Check,
                                contentDescription = "已选中",
                                tint = MaterialTheme.colorScheme.primary,
                                modifier = Modifier.size(18.dp),
                            )
                        }
                    }
                }
                // ⛔ 「还有 N 位没显示」必须说出来：静默截断会让用户以为"名册里没有这个人"，
                //    然后去填一个临时货主 —— 同一个人两本账（与名册搜索那条纪律同源）。
                if (shown.size > shownTop.size) {
                    Text(
                        "还有 " + (shown.size - shownTop.size) + " 位没显示 —— 输入姓名或手机号缩小范围。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(vertical = 8.dp),
                    )
                }
            }
        }
    }
}
