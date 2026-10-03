package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.AccountBrown
import com.tapmoay.sorders.ui.theme.MessageRed
import com.tapmoay.sorders.ui.common.Hint

/**
 * **账号分类**管理面板（2026-10-05）。
 *
 * 形态照 `ui/dispatcher/PlaceCategoriesScreen.kt::PlaceCategoriesPanel` —— 它是
 * **同一个抽屉里的第二层**（点抽屉底部那格「管理分类」→ 内容换成这一块 + 一个返回），
 * 不是新开一页：用户 2026-09-19 对整页的第一版裁定是「切换的时候突然会闪一下…
 * 干脆就不要弹一个界面，**它 2 个抽屉**」。
 *
 * ⛔ 抽屉（`CategoryDrawerSheet`）那几格**不显示条数**；条数只在这个面板里出现
 * —— 删之前要让人看见「这一类下还挂着几个账号」。
 */
/**
 * @param accent 这一份名册**宿主页的模块色**（规范 §2 / §4.3「一色一功能」）：面板里的顺序
 *   箭头、重命名弹窗里那句条数都用它 —— 原来写死成 `ShipperTeal`（地址页的湖蓝），而这一页
 *   是账户管理的棕、车辆那一页是车辆管理的黄绿。
 */
@Composable
fun UserCategoriesPanel(
    vm: UserCategoriesViewModel,
    onBack: () -> Unit,
    accent: Color = Color(AccountBrown),
) {
    RosterPanel(
        vm = vm,
        title = "账号分类",
        accent = accent,
        backLabel = "返回名册",
        newPlaceholder = "新分类名（如：自有车 / 外请车 / 长期合作）",
        hint = "全店一份：账户 / 司机 / 货主 / 批发商四个名册页的左栏都用这一份，顺序就是左栏的顺序。",
        emptyText = "还没有分类。不建也能用：四个名册页的左栏只有「全部」一格，账号照样都在。",
        countUnit = "个账号",
        renameHint = "改名会把挂在这个分类下的账号一起改过去（回收站里的也一样，不会掉回未分类）。",
        countLine = "现在有 %d 个账号挂在这一类下。",
        deleteNote = "（后端不允许删还有账号挂着的分类，真要删请先把它们改到别的分类）",
        onBack = onBack,
    )
}

/** **车辆分类**管理面板（2026-10-05，车辆管理页左栏那一列）。 */
@Composable
fun VehicleCategoriesPanel(
    vm: VehicleCategoriesViewModel,
    onBack: () -> Unit,
    accent: Color = VehicleAccent,
) {
    RosterPanel(
        vm = vm,
        title = "车辆分类",
        accent = accent,
        backLabel = "返回车辆",
        newPlaceholder = "新分类名（如：自有车队 / 外调车 / 挂靠）",
        hint = "全店一份：车辆管理页的左栏用这一份，顺序就是左栏的顺序。" +
            "⛔ 分类只是分组，不参与任何计费（车型与车身型式是另外两件事）。",
        emptyText = "还没有分类。不建也能用：车辆管理页的左栏只有「全部」一格，车照样都在。",
        countUnit = "辆车",
        renameHint = "改名会把挂在这个分类下的车辆一起改过去（停用的车也一样，不会掉回未分类）。",
        countLine = "现在有 %d 辆车挂在这一类下。",
        deleteNote = "（后端不允许删还有车挂着的分类，真要删请先把它们改到别的分类）",
        onBack = onBack,
    )
}

/** 两份名册共用的面板（差别只有几处文案与单位）。 */
@Composable
private fun RosterPanel(
    vm: RosterViewModel,
    title: String,
    backLabel: String,
    accent: Color,
    newPlaceholder: String,
    hint: String,
    emptyText: String,
    countUnit: String,
    renameHint: String,
    countLine: String,
    deleteNote: String,
    onBack: () -> Unit,
) {
    Column(Modifier.fillMaxWidth()) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 20.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(title, style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
            TextButton(onClick = onBack) {
                Icon(
                    Icons.AutoMirrored.Filled.ArrowBack,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                )
                Spacer(Modifier.width(4.dp))
                Text(backLabel)
            }
        }
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            SoTextField(
                value = vm.draftName,
                onValueChange = { vm.draftName = it },
                placeholder = newPlaceholder,
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.width(8.dp))
            PrimaryActionButton(
                text = if (vm.acting) "…" else "新建",
                onClick = { vm.create() },
                enabled = !vm.acting && vm.draftName.isNotBlank(),
            )
        }
        Hint(
            hint,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 20.dp),
        )
        Spacer(Modifier.height(8.dp))
        when {
            vm.loading && vm.rows.isEmpty() -> LoadingBox(Modifier.fillMaxWidth().height(160.dp))
            vm.loadError != null -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })
            vm.rows.isEmpty() -> Text(
                emptyText,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 18.dp),
            )
            else -> LazyColumn(
                Modifier.fillMaxWidth().weight(1f, fill = false).heightIn(max = 460.dp),
                contentPadding = PaddingValues(horizontal = 20.dp, vertical = 4.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                itemsIndexed(vm.rows, key = { _, r -> r.id }) { idx, r ->
                    RosterRowCard(
                        row = r,
                        unit = countUnit,
                        first = idx == 0,
                        last = idx == vm.rows.lastIndex,
                        onUp = { vm.move(idx, -1) },
                        onDown = { vm.move(idx, +1) },
                        onRename = { vm.openRename(r) },
                        onDelete = { vm.deleting = r },
                        accent = accent,
                    )
                }
            }
        }
        // 刚删掉的那一格：名册是硬删（没有回收站），所以给一个**当场能按回来**的撤销 ——
        // 按原来的名字与位置重建一格（编号会变，但成员不受影响：还挂着东西的分类后端不让删）。
        vm.undoRow?.let { gone ->
            // 撤销条也是**纯白卡**：这一层整个装在左侧抽屉里，抽屉的面是 `SheetSurface` 那层灰，
            // 规范 §5.0 明写「抽屉里装的卡片必须是纯白」（原话的理由：白的面上再放白卡，对比就没了）。
            // 原来用的 `surfaceContainerHigh` 比抽屉的面还深，看着像抽屉里嵌了一块更灰的板。
            SectionCard(Modifier.padding(horizontal = 20.dp, vertical = 6.dp)) {
                Row(
                    Modifier.fillMaxWidth().padding(start = 12.dp, end = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        "已删除「" + gone.name + "」",
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.weight(1f),
                    )
                    TextButton(onClick = { vm.undoDelete() }, enabled = !vm.acting) { Text("撤销") }
                }
            }
        }
        vm.error?.let {
            Text(
                it,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp),
            )
        }
    }

    vm.renaming?.let { target ->
        AlertDialog(
            onDismissRequest = { vm.renaming = null },
            title = { Text("重命名分类") },
            text = {
                Column {
                    SoTextField(vm.renameText, { vm.renameText = it }, placeholder = "分类名")
                    Spacer(Modifier.height(6.dp))
                    Text(
                        renameHint,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    if (target.count > 0) {
                        Spacer(Modifier.height(4.dp))
                        Text(
                            countLine.format(target.count),
                            style = MaterialTheme.typography.bodySmall,
                            color = accent,
                        )
                    }
                }
            },
            confirmButton = { TextButton(onClick = { vm.rename() }, enabled = !vm.acting) { Text("保存") } },
            dismissButton = { TextButton(onClick = { vm.renaming = null }) { Text("取消") } },
        )
    }

    vm.deleting?.let { target ->
        DangerConfirmDialog(
            title = "删除分类？",
            message = "「" + target.name + "」会从左栏消失。挂在这一类下的不会被动。" + deleteNote,
            confirmText = "删除",
            onConfirm = { vm.confirmDelete() },
            onDismiss = { vm.deleting = null },
        )
    }
}

/** 一行分类：名字 + 挂着几个 + 上移 / 下移 / 改名 / 删。 */
@Composable
private fun RosterRowCard(
    row: RosterRow,
    unit: String,
    first: Boolean,
    last: Boolean,
    accent: Color,
    onUp: () -> Unit,
    onDown: () -> Unit,
    onRename: () -> Unit,
    onDelete: () -> Unit,
) {
    SectionCard {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            Column(Modifier.weight(1f)) {
                Text(row.name, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold, maxLines = 1)
                Text(
                    row.count.toString() + " " + unit,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            // 四颗动作图标走共用件 `CardActionIcon`（规范 §4.2c：卡片上的**图标**动作一律做成
            // 圈底图标）。原来这里是四枚裸 `IconButton` 里塞一个 18dp 图标 —— 规范里被用户当场
            // 点名「这个不行」的正是那个形态：在信息很满的卡片上它太轻，手指也不好找。
            //
            // ⛔ 这四颗**不带字**（不传 `label`）：一行要挤下四颗，带字会把这一行撑爆；
            //    四颗各自的 `contentDescription` 仍然说清是"上移 / 下移 / 重命名 / 删除"。
            CardActionIcon(
                icon = Icons.Default.KeyboardArrowUp,
                contentDescription = "上移",
                tint = if (first) MaterialTheme.colorScheme.outlineVariant else accent,
                onClick = onUp,
                enabled = !first,
                size = 15.dp,
                container = 30.dp,
            )
            CardActionIcon(
                icon = Icons.Default.KeyboardArrowDown,
                contentDescription = "下移",
                tint = if (last) MaterialTheme.colorScheme.outlineVariant else accent,
                onClick = onDown,
                enabled = !last,
                size = 15.dp,
                container = 30.dp,
            )
            CardActionIcon(
                icon = Icons.Default.Edit,
                contentDescription = "重命名",
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                onClick = onRename,
                size = 15.dp,
                container = 30.dp,
            )
            CardActionIcon(
                icon = Icons.Default.DeleteOutline,
                contentDescription = "删除",
                tint = Color(MessageRed),
                onClick = onDelete,
                size = 15.dp,
                container = 30.dp,
            )
        }
    }
}

/**
 * 表单里选分类的那一行（账户 / 司机 / 货主 / 批发商 / 车辆的新建与编辑共用）。
 *
 * ⛔ **不是**再开一层弹层：这一行本身就在底部抽屉里，抽屉里再套一个 ModalBottomSheet
 * 就是「两层 modal 窗口叠着」—— 规范 `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md` §4.14 点名的那件事。
 * 形态与「地址与联系人」表单里的分类选择器一致：下拉 + 「未分类」+ 名册每一格 + 末尾「＋ 新建分类…」。
 *
 * 名字与顺序都由名册给，**界面不许自己排**（左栏什么顺序，这里就是什么顺序）。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CategoryPickRow(
    vm: RosterViewModel,
    selected: String,
    onPick: (String) -> Unit,
    label: String = "分类",
    hint: String = "只影响左栏怎么分组；不选就是未分类。",
) {
    var expanded by remember { mutableStateOf(false) }
    var creating by remember { mutableStateOf(false) }
    var newName by remember { mutableStateOf("") }
    ExposedDropdownMenuBox(expanded = expanded, onExpandedChange = { expanded = it }) {
        FormPickRow(
            label = label,
            value = selected.ifBlank { "未分类" },
            placeholder = "未分类",
            onClick = { expanded = true },
            modifier = Modifier.menuAnchor(),
        )
        ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            DropdownMenuItem(
                text = { Text(if (selected.isBlank()) "未分类　✓" else "未分类", maxLines = 1) },
                onClick = { onPick(""); expanded = false },
            )
            vm.rows.forEach { r ->
                DropdownMenuItem(
                    text = { Text(if (r.name == selected) r.name + "　✓" else r.name, maxLines = 1) },
                    onClick = { onPick(r.name); expanded = false },
                )
            }
            DropdownMenuItem(
                text = { Text("＋ 新建分类…", maxLines = 1) },
                onClick = { expanded = false; newName = ""; creating = true },
            )
        }
    }

    if (creating) {
        AlertDialog(
            onDismissRequest = { creating = false },
            title = { Text("新建分类") },
            text = {
                Column {
                    SoTextField(newName, { newName = it }, placeholder = "分类名，如：自有车 / 外请车")
                    Spacer(Modifier.height(6.dp))
                    Hint("建好后会自动选中它。顺序到左栏底部的「管理分类」里排。")
                    Spacer(Modifier.height(4.dp))
                    Text(
                        hint,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    vm.error?.let {
                        Spacer(Modifier.height(4.dp))
                        Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
                    }
                }
            },
            confirmButton = {
                TextButton(
                    onClick = { vm.createThen(newName) { onPick(it) }; creating = false },
                    enabled = newName.isNotBlank() && !vm.acting,
                ) { Text("新建") }
            },
            dismissButton = { TextButton(onClick = { creating = false }) { Text("取消") } },
        )
    }
}

/** 左栏那一格（`c|分类名`）→ 分类名；「全部」→ 空串。 */
fun railNameOf(key: String): String = if (key.startsWith("c|")) key.removePrefix("c|") else ""

/** 按左栏那一格过滤（空串 = 全部）。名册与列表都在手上 —— 本地过一遍，不往返后端。 */
fun <T> inRail(rows: List<T>, key: String, nameOf: (T) -> String): List<T> {
    val name = railNameOf(key)
    return if (name.isBlank()) rows else rows.filter { nameOf(it) == name }
}
