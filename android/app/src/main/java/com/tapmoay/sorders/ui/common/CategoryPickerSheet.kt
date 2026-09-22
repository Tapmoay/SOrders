package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp

/** 选择页里的一项：名字 + 一句副标题（如「3 个商品」）。 */
data class CategoryChoice(val name: String, val subtitle: String = "")

/**
 * 「请选择××分组」——**从名册里单选一个**（2026-09-21 商品管理改版第 1 期，P7）。
 *
 * ## 抄的是**布局**（用户 2026-09-21 给的参考图里那一页）
 * 搜索框在最上、右上角一个「新建分组」、下面一列**单选**、底部一对「取消 / 确定」。
 * ⛔ 参考图里那个「全选」是**多选**场景用的，我们这里是单选，**不抄**。
 *
 * ## 为什么单选也必须走这一页（而不是继续用下拉）
 * 商品编辑页原来是 `ExposedDropdownMenuBox` 的下拉，而**分类是要长期维护的名册**：
 * 用户在挑分类的过程中十有八九会发现"少一个分类" —— 下拉里没法新建，
 * 他只能退出去、去分类管理页建好、再回来重选一遍（而这一退，表单里的东西就没了）。
 * 这一页把**新建**放在手边（[onCreate]），也正是参考图那个按钮存在的理由。
 *
 * @param choices 名册（顺序就是展示顺序）
 * @param current 当前值（`""` = 未分类）
 * @param allowNone 是否提供「未分类」那一项（给不给"清空分类"这条路）
 * @param onCreate 非空时右上角画「新建分组」，回调拿到用户输入的名字（**建完由调用方重新选中**）
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CategoryPickerSheet(
    title: String,
    choices: List<CategoryChoice>,
    current: String,
    onPick: (String) -> Unit,
    onDismiss: () -> Unit,
    allowNone: Boolean = true,
    noneLabel: String = "未分类",
    onCreate: ((String) -> Unit)? = null,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    // 草稿态：点一行只是**选中**，点「确定」才回传（与参考图同一套交互）
    var picked by remember(current) { mutableStateOf(current.trim()) }
    var keyword by remember { mutableStateOf("") }
    var creating by remember { mutableStateOf(false) }

    val rows = remember(choices) {
        buildList {
            if (allowNone) add(CategoryChoice(name = "", subtitle = "不归到任何分组"))
            addAll(choices)
        }
    }
    val shown = remember(rows, keyword) {
        val k = keyword.trim()
        if (k.isEmpty()) rows
        else rows.filter { it.name.contains(k, ignoreCase = true) || (it.name.isEmpty() && noneLabel.contains(k)) }
    }

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
        Column(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp)
                .padding(bottom = 24.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    title,
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.weight(1f),
                )
                if (onCreate != null) {
                    TextButton(onClick = { creating = true }) {
                        Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(4.dp))
                        Text("新建分组")
                    }
                }
            }
            Spacer(Modifier.height(6.dp))

            SoTextField(
                value = keyword,
                onValueChange = { keyword = it },
                placeholder = "搜索分组名称",
            )
            Spacer(Modifier.height(10.dp))

            if (shown.isEmpty()) {
                // ⚠️ 空态文案：**必须常显**（不走 `Hint`）—— 搜不到时这一屏就只剩这两句，
                //    被总开关藏掉之后页面一片空白，连"是不是真没有"都看不出来。
                Text(
                    "没有匹配「${keyword.trim()}」的分组",
                    style = MaterialTheme.typography.bodyMedium,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    "分组在「商品管理 → 分类管理」里维护；也可以在右上角直接新建一个。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                LazyColumn(Modifier.heightIn(max = 380.dp)) {
                    // ⚠️ key 直接用名字（空串 = 「未分类」那一行，它本来就是一个合法且唯一的 key）。
                    //    第一版写的是 `ifEmpty { "__none__" }` —— 那是**下划线**，
                    //    `_check_ai_guardrails.py` 会把它当成界面文案里的 Markdown 记号（界面上会显示字面量），
                    //    它只看文本不看上下文，所以这里换成不会误伤、也不会有歧义的写法。
                    items(shown, key = { it.name }) { c ->
                        val on = c.name == picked
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .clickable { picked = c.name }
                                .padding(vertical = 8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            RadioButton(selected = on, onClick = { picked = c.name })
                            Spacer(Modifier.width(4.dp))
                            Column(Modifier.weight(1f)) {
                                Text(
                                    c.name.ifEmpty { noneLabel },
                                    style = MaterialTheme.typography.bodyLarge,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                                if (c.subtitle.isNotBlank()) {
                                    Text(
                                        c.subtitle,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                            }
                        }
                    }
                }
            }

            Spacer(Modifier.height(18.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedButton(
                    onClick = onDismiss,
                    modifier = Modifier.weight(1f).height(48.dp),
                ) { Text("取消") }
                Button(
                    onClick = { onPick(picked) },
                    modifier = Modifier.weight(1.4f).height(48.dp),
                ) { Text("确定") }
            }
        }
    }

    if (creating && onCreate != null) {
        CategoryNameDialog(
            title = "新建分组",
            initial = keyword.trim(),
            hint = "建好之后自动选中它，不用退出去再选一遍。顺序到「分类管理」里排。",
            onConfirm = { name -> creating = false; onCreate(name) },
            onDismiss = { creating = false },
        )
    }
}

/**
 * 「给分组起个名字」的小弹窗 —— **名册页（新建/改名）与选择页（就地新建）共用这一份**。
 *
 * ⚠️ 它原来是商品管理页里一个 private 的 `NewCategoryDialog`，注释写着"不共用：
 * 重复的是一个 12 行的输入框，而抽公共组件要给它加三个用不上的参数 —— 不值"。
 * 现在**第三个调用点出现了**（选择页里就地新建），"不值"的前提就没了。
 *
 * ⚠️ `ui/dispatcher/ProductCategoriesScreen.kt` 里还留着一个 **private 的同名弹窗**
 * （那一页自己的新建/改名用）。它**遮蔽**着这一个（同文件声明优先于星号导入），所以两边
 * 暂时各用各的；P1（把四个名册页收成一个组件）落地时**把它删掉、改用这一个**。
 */
@Composable
fun CategoryNameDialog(
    title: String,
    initial: String,
    onConfirm: (String) -> Unit,
    onDismiss: () -> Unit,
    hint: String? = null,
    busy: Boolean = false,
    confirmText: String = "确定",
) {
    var name by remember(initial) { mutableStateOf(initial) }
    AlertDialog(
        onDismissRequest = { if (!busy) onDismiss() },
        title = { Text(title) },
        text = {
            Column {
                SoTextField(
                    value = name,
                    // 与名册页同一个上限（后端 `product_categories.name` 是 String(32)，而界面上
                    // 8 个字早就够表达"饮料/粮油/日化"这一类名字了）
                    onValueChange = { name = it.take(8) },
                    placeholder = "分组名，如 饮料 / 粮油 / 日化",
                )
                if (hint != null) {
                    Spacer(Modifier.height(8.dp))
                    Hint(
                        hint,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        },
        confirmButton = {
            TextButton(enabled = !busy && name.isNotBlank(), onClick = { onConfirm(name) }) {
                Text(if (busy) "提交中…" else confirmText)
            }
        },
        dismissButton = { TextButton(enabled = !busy, onClick = onDismiss) { Text("取消") } },
    )
}
