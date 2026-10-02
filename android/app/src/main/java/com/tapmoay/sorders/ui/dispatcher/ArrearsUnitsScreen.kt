package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.ArrearsUnitDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.ArrearsTangerine
import com.tapmoay.sorders.ui.theme.MessageRed
import com.tapmoay.sorders.ui.theme.NavBlue
import com.tapmoay.sorders.ui.theme.OnArrearsTangerine

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ArrearsUnitsScreen(
    container: AppContainer,
    onBack: () -> Unit,
) {
    val vm: ArrearsUnitsViewModel = appViewModel { ArrearsUnitsViewModel(container) }
    val snackbar = remember { SnackbarHostState() }

    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = { Text("挂账单位") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
        floatingActionButton = {
            FloatingActionButton(onClick = { vm.openCreate() }) {
                Icon(Icons.Default.Add, contentDescription = "新增挂账单位")
            }
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                vm.loading -> LoadingBox()
                vm.loadError != null -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })
                // ⚠️ `vm.recentlyDeleted == null` 这个条件是**为了让撤回行活着**：删掉最后一条时
                //    列表会空，若直接走空状态，那句「已删除…+撤销」就跟着没了 —— 而"手边要有撤回"
                //    恰恰是删空的时候最需要。空的时候就让下面的 LazyColumn 只画那一行。
                vm.units.isEmpty() && vm.recentlyDeleted == null ->
                    EmptyView("暂无挂账单位，点击右下角新增", Modifier.align(Alignment.Center))
                else -> LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    // 撤回（规范 §4.11：删除一律软删 + **手边**要有撤回）：刚删掉的那一条
                    // 就画在列表头顶上，不用去别处找。后端是真能救回来的（restore 会把名字
                    // 从 xxx_del{id} 改回去），所以这里写「已删除…+撤销」而不是「已通知管理员」。
                    vm.recentlyDeleted?.let { rd ->
                        item(key = "undo") {
                            // ⛔ 这一层 Column 不能省：LazyColumn 的 item 里没有 ColumnScope，
                            //    而 AddressScreen 那段原文是直接写在 Column 里的。
                            Column {
                                Row(
                                    verticalAlignment = Alignment.CenterVertically,
                                    modifier = Modifier.fillMaxWidth().padding(start = 4.dp, end = 4.dp),
                                ) {
                                    Text(
                                        "已删除「" + rd.name + "」",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                        modifier = Modifier.weight(1f),
                                    )
                                    TextButton(onClick = { vm.undoDelete() }, enabled = !vm.acting) {
                                        Text("撤销")
                                    }
                                }
                                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                            }
                        }
                    }
                    items(vm.units, key = { it.id }) { u ->
                        UnitCard(
                            u = u,
                            onEdit = { vm.openEdit(u) },
                            onDelete = { vm.delete(u) },
                        )
                    }
                    item { Spacer(Modifier.height(72.dp)) }
                }
            }
        }
    }

    // 新增 / 编辑抽屉（2026-10-04）。原来是居中 AlertDialog —— 规范 :1266 把这条路堵死了：
    // 「他不要使用弹窗啊，使用底部抽屉，并且底部抽屉是拉到最上面」，字段一多居中弹窗就变成"小框里滚"。
    if (vm.showSheet) {
        val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
        ModalBottomSheet(onDismissRequest = { vm.closeSheet() }, sheetState = sheetState) {
            Column(
                Modifier
                    .fillMaxWidth()
                    .fillMaxHeight()
                    .padding(horizontal = 16.dp)
                    .imePadding()
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        if (vm.editing == null) "新增挂账单位" else "编辑挂账单位",
                        style = MaterialTheme.typography.titleLarge,
                        modifier = Modifier.weight(1f),
                    )
                    SheetCloseButton(onClick = { vm.closeSheet() })
                }
                // 白卡分组 + 共用行（每个输入**自己也是一张小卡**，就是规范里那句
                //「每个选择就相当于一个、每个输入相当于卡片」）。⛔ 卡里不许出现描边输入框。
                FormGroup(Icons.Default.Business, "挂账单位", Color(ArrearsTangerine)) {
                    FormInputRow(
                        "单位名称",
                        vm.draftName,
                        { vm.draftName = it },
                        required = true,
                        placeholder = "如 兴盛蔬菜",
                        icon = Icons.Default.Business,
                        iconTint = Color(ArrearsTangerine),
                    )
                    FormInputRow(
                        // 标签里必须带「电话」两个字 —— 输入规则判据按标签认这格是什么。
                        "联系电话",
                        vm.draftPhone,
                        // 电话只让数字进来（规则唯一实现在 core/InputRules.kt）
                        { vm.draftPhone = InputRules.phoneInput(it) },
                        keyboardType = KeyboardType.Phone,
                        placeholder = "选填",
                        icon = Icons.Default.Phone,
                        iconTint = Color(ArrearsTangerine),
                    )
                    FormInputRow(
                        "备注",
                        vm.draftRemark,
                        { vm.draftRemark = it },
                        placeholder = "选填 · 如结算方式",
                        icon = Icons.Default.Notes,
                        iconTint = Color(ArrearsTangerine),
                    )
                }
                // 表单的错**画在抽屉里**（规范 :469-478）：页面级那个 error 一写就把整页
                // 变成"列表全没了"，正是用户 2026-09-21 骂的那个坑。
                FormErrorLine(vm.formError)
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(
                        onClick = { vm.closeSheet() },
                        enabled = !vm.acting,
                        modifier = Modifier.weight(1f).height(48.dp),
                    ) { Text("取消") }
                    Button(
                        onClick = { vm.save() },
                        enabled = !vm.acting,
                        // 本页的色是橙红（规范 §2 模块色表）。白字压在这上面只有 2.84:1（不过 AA），
                        // 所以往 Color.kt 加了深棕 OnArrearsTangerine ≈ 6.2:1 —— 跟黄绿那对同一个路子。
                        colors = ButtonDefaults.buttonColors(
                            containerColor = Color(ArrearsTangerine),
                            contentColor = Color(OnArrearsTangerine),
                        ),
                        modifier = Modifier.weight(1f).height(48.dp),
                    ) { Text("保存") }
                }
                Spacer(Modifier.height(24.dp))
            }
        }
    }
}

@Composable
private fun UnitCard(
    u: ArrearsUnitDto,
    onEdit: () -> Unit,
    onDelete: () -> Unit,
) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            // 本页的语义色是橙红（`ArrearsTangerine`，规范 §2 的模块色表；工作台那一格也是它）。
            // 原来用的是 M3 默认的 primaryContainer 蓝 —— 那是"这个 App 的主色"，不是"这一块的颜色"。
            TintedIcon(Icons.Default.Business, Color(ArrearsTangerine), size = 20.dp, container = 38.dp)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(u.name, style = MaterialTheme.typography.titleSmall)
                if (u.phone.isNotBlank()) {
                    Text(u.phone, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if (u.remark.isNotBlank()) {
                    Text(u.remark, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
                }
            }
        }
        Spacer(Modifier.height(8.dp))
        // 卡片动作（规范 §4.2c / :237）：**编辑一定在最右**（惯用手是右手）、**相反/警示类在最左**，
        // 形态一律是共用件 `CardActionIcon`（12% 语义色圆底 + 同色图标 + 文字）。
        // ⛔ 别退回卡头那把 18dp 的裸铅笔 / 裸垃圾桶 —— 用户 2026-09-22 的原话是「这个不行」。
        Row(verticalAlignment = Alignment.CenterVertically) {
            CardActionIcon(
                Icons.Default.Delete, "删除", Color(MessageRed), onDelete,
                label = "删除", size = 15.dp, container = 30.dp,
            )
            Spacer(Modifier.weight(1f))
            CardActionIcon(
                Icons.Default.Edit, "编辑", Color(NavBlue), onEdit,
                label = "编辑", size = 15.dp, container = 30.dp,
            )
        }
    }
}
