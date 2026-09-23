package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PersonAddAlt
import androidx.compose.material.icons.filled.Phone
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.core.UserSearch
import com.tapmoay.sorders.data.remote.dto.ContactDto

/**
 * 「选择联系人」—— 全 App **唯一一份**挑联系人的弹层。
 *
 * ## 为什么要有它（用户 2026-09-24）
 * > 「给户主也加一个在选择下单的时候**可以选择联系人**，就**不用每次要手动填入了**。」
 *
 * 在那之前，收货人名称/电话只能**手打**：同一个老王，这次打"王老板"、下次打"老王"、
 * 再下次手机号少一位 —— 而订单卡片上是照着这两个字段拨号的（打不通只能再问一遍）。
 * 「地址与联系人」里明明有一份联系人名册，下单页却够不着它。
 *
 * ## 三个调用点共用这一份
 * | 谁 | 挑完干什么 |
 * |---|---|
 * | 下单页「收货人」那两栏 | [ContactFillMode.PICKED] 整对替换（挑的是"这个人"） |
 * | 下单页「选联系人」入口 | 同上 |
 * | 「地址与联系人」的线路表单 | 快照姓名+电话（与它原来的 `selectContact` 同一件事） |
 *
 * ⛔ **搜索走 `core/UserSearch`**（姓名 / 手机号，后 4 位也命中）—— 不在这里再写一遍 `contains`。
 * 地址与联系人页的「联系人」段用的就是它，两处必须是同一个判据：
 * 否则同一个人在下单页搜得到、在地址页搜不到。
 *
 * @param contacts 当前登录人的联系人名册（按登录人隔离；调用方负责取数）
 * @param onPick 点某一行 → 回传这位联系人（弹层由调用方关掉）
 * @param onCreate 非空时底部出现「新建联系人」：**就地建一个**（下单时最常见的场景 ——
 *   第一次给这个人送货，打完电话顺手存下来，下次就不用再打了）。参数是 (姓名, 电话)。
 * @param creating 正在提交新建（按钮转圈/禁用；重复点会建出两条同号记录）
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ContactPickerSheet(
    contacts: List<ContactDto>,
    onPick: (ContactDto) -> Unit,
    onDismiss: () -> Unit,
    loading: Boolean = false,
    error: String? = null,
    onRetry: () -> Unit = {},
    onCreate: ((String, String) -> Unit)? = null,
    creating: Boolean = false,
    createError: String? = null,
    title: String = "选择联系人",
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var keyword by remember { mutableStateOf("") }
    var showCreate by remember { mutableStateOf(false) }
    val kw = keyword.trim()
    val shown = remember(contacts, kw) {
        if (kw.isBlank()) contacts else contacts.filter { UserSearch.matches(kw, it.displayName, it.phone) }
    }

    if (showCreate && onCreate != null) {
        CreateContactDialog(
            creating = creating,
            // ⛔ 「新建失败」那句话画在**这个对话框里**（`createError`），不是拿去替掉右边的列表 ——
            //    列表本身好好的，把它换成一句报错，用户会以为"联系人全没了"。
            error = createError,
            onSave = { name, phone -> onCreate(name, phone) },
            onDismiss = { showCreate = false },
        )
    }

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
        Column(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp)
                .padding(bottom = 24.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                SheetCloseButton(onClick = onDismiss)
            }
            Spacer(Modifier.height(8.dp))

            SoTextField(
                value = keyword,
                onValueChange = { keyword = it },
                placeholder = "搜索姓名或手机号",
            )
            Spacer(Modifier.height(12.dp))

            when {
                loading -> LoadingBox(Modifier.fillMaxWidth().height(140.dp))
                error != null -> ErrorView(error, onRetry = onRetry, Modifier.fillMaxWidth().height(140.dp))
                contacts.isEmpty() -> {
                    // ⚠️ 空态文案**常显**（不走 `Hint`）：这一屏只剩它，
                    //    藏了之后用户看到的是**一片空白**，"还没建过联系人"与"加载失败"就分不出来了。
                    Text("还没有联系人", style = MaterialTheme.typography.bodyMedium)
                    Spacer(Modifier.height(4.dp))
                    Text(
                        "在「地址与联系人 → 联系人」里加过人之后，这里就能直接挑。" +
                            if (onCreate != null) "也可以点下面的「新建联系人」。"
                            else "",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                shown.isEmpty() -> Text("没有匹配「$kw」的联系人", style = MaterialTheme.typography.bodyMedium)
                else -> LazyColumn(Modifier.fillMaxWidth().heightIn(max = 320.dp)) {
                    items(shown, key = { it.id }) { c ->
                        ContactRow(c) { onPick(c) }
                    }
                }
            }

            if (onCreate != null) {
                Spacer(Modifier.height(14.dp))
                OutlinedButton(
                    onClick = { showCreate = true },
                    enabled = !creating,
                    modifier = Modifier.fillMaxWidth().height(48.dp),
                ) {
                    Icon(Icons.Default.PersonAddAlt, null, Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp))
                    Text("新建联系人")
                }
            }
        }
    }
}

/** 名册里的一行：姓名（没写名字就说"未命名"，不编一个名字出来）+ 电话。 */
@Composable
private fun ContactRow(c: ContactDto, onClick: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(
                // ⛔ 不编名字：名册允许只存一个号码（`display_name` 缺省为空串），
                //    编一个"联系人"出来会让人以为名册里真有个叫"联系人"的人。
                c.displayName.trim().ifBlank { "未命名" },
                style = MaterialTheme.typography.bodyLarge,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                // 显式占满这一列：`maxLines = 1 + Ellipsis` 却不给宽度的文本会去**吃**兄弟的宽度
                // （判据 `_check_adaptive_layout.py` §5 的存量基线只许减不许增）。
                modifier = Modifier.fillMaxWidth(),
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.Phone, null, Modifier.size(13.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.width(4.dp))
                Text(c.phone, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        Text("选择", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
    }
}

/**
 * 就地新建一个联系人（姓名 + 电话）。
 *
 * 电话规则**唯一实现在 `core/InputRules.kt`**（与下单页那两个电话输入框同一条）：
 * 汉字/字母/符号在输入层就被丢掉，长度也一起管 —— 这里不另写一套。
 */
@Composable
private fun CreateContactDialog(
    creating: Boolean,
    error: String?,
    onSave: (String, String) -> Unit,
    onDismiss: () -> Unit,
) {
    var name by remember { mutableStateOf("") }
    var phone by remember { mutableStateOf("") }
    // 电话规则**唯一实现在 `core/InputRules.kt`**（与「地址与联系人」那个联系人表单、
    // 以及后端 `ContactCreate.phone` 同一条）：这里不另写一遍"长度 ≥7 就算过"——
    // 那一版曾经让 `222`、`12345` 这种打不通的号进了生产库。
    val phoneError = InputRules.phoneError(phone.trim(), required = true)
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("新建联系人") },
        text = {
            Column {
                SoTextField(value = name, onValueChange = { name = it }, placeholder = "姓名（选填）")
                Spacer(Modifier.height(10.dp))
                SoTextField(
                    value = phone,
                    onValueChange = { phone = InputRules.phoneInput(it) },
                    placeholder = "手机号（必填）",
                    keyboardType = KeyboardType.Phone,
                )
                Spacer(Modifier.height(8.dp))
                Text(
                    // 后端那句中文（例如同号重复的 409）优先于本地规则：它是**最终判据**，
                    // 本地规则只是"还没发请求就先说一句"。
                    error ?: phoneError
                    ?: "存下来之后，这个人会在「地址与联系人」和这里的列表里出现，以后下单直接挑。",
                    style = MaterialTheme.typography.bodySmall,
                    color = if (error != null || phoneError != null) MaterialTheme.colorScheme.error
                    else MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
        confirmButton = {
            TextButton(onClick = { onSave(name.trim(), phone.trim()) }, enabled = phoneError == null && !creating) {
                Text(if (creating) "保存中…" else "保存")
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}
