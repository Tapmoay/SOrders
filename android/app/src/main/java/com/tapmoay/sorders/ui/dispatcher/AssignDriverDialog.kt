package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.core.UserSearch
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.util.formatMoney
import kotlinx.coroutines.launch

/**
 * 派单抽屉（选司机）—— 一处实现，两个入口共用：待派单池的「派单」/「批量派单」与
 * 订单详情底部的「派单」（P12：派单员点开待派单的单，底部只有 现场支付 / 挂账 /
 * 拆分订单 / 删除订单，想派单还得回池子里把这张单再找一遍 —— 那不是入口）。
 *
 * ⛔ 为什么不各写一份：派单是同一个动作（选司机 + 运费 / 收现金 / 备注，
 *    成功后 PENDING_DISPATCH → 派单中）。两套界面一定会走散，而走散的表现是
 *    「同一个司机在这一页能派、在那一页报错」—— 那时用户不知道信哪一页。
 *
 * ## P8 在这一份里怎么修的
 * · 档位原来是「大车司机 / 挂车司机」两档，而大车那一档把小车司机也吞了进来
 *   （过滤条件写的是 vehicleType != trailer）。司机分三种 —— 小车 / 大车 / 挂车
 *   （docs/plan-driver-freight.md:6-9）⇒ 按三种分档，且只显示真的有人 的档位
 *   （空档点进去一片空白，而「这档没人」与「还没拉到司机」在界面上长得一样）；
 * · 司机标签原来只跟档位走（写死大车司机/挂车司机）：选中王强（小车司机）
 *   后标签还写「大车司机」⇒ 现在标签跟选中的人走，车型标签复用
 *   UsersManageScreen.kt::driverKindLabel（全 App 唯一一份，别在这里另写）。
 *
 * ## 2026-10-05（CHG-0038）用户第二轮：这个框「有点丑」
 * · 「不要搞弹窗了，直接也搞个底部抽屉吧」+「拉的比较上面一点**拉高一点**」——
 *   居中 AlertDialog 换成 `ModalBottomSheet`（拉到屏高，与 2026-10-04 挂账单位那一个同形）；
 * · 「颜色不要改。这种淡蓝色啊，改成那种淡白色吧，像那种纸质书的感觉」—— 抹掉两处淡蓝：
 *   选中档位的 `primary.copy(alpha = 0.14f)` 与未选中档位的 `surfaceVariant`(#ECEFF5)。
 *   ⛔ 抽屉底色**不在这里传**：全 App 19 个抽屉的底由 Color.kt 的 `SheetSurface` 一处说了算
 *   （`_tools/qa/_check_sheet_form_pages.py` 盯着这条）；
 * · 「选择司机列表的时候搞一个左侧抽屉吧…他直接拉起分类，像商品那样拉起一些分类列表」——
 *   选司机那一行点开 = 左侧抽屉（左栏车型档位 + 右栏这一档的司机名单，名字/手机号可搜）；
 * · 「像什么这一单决定多少钱提成多少这个不要管，我们以后直接在那个订单里去给他订了」——
 *   删掉「这一单单独定（这一单的钱 ¥ / 提成 %）」整块。
 *   ⚠️ 删的只是**界面**：VM 里的 assignPieceAmount / assignCommissionRate 与后端参数都还在。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AssignDriverDialog(
    vm: DispatcherPoolViewModel,
    /** 派单成功之后回调（订单详情页用它刷新自己那一份；待派单池不需要）。 */
    onAssigned: () -> Unit = {},
) {
    // 运费模板子弹窗的开关属于「这一次派单」，所以跟着本组件走（原来是池子页的局部状态）
    var templatePick by remember { mutableStateOf(false) }

    // 派单抽屉（单选/批量共用）
    if (vm.showAssignDialog) {
        // ⚠️ 档位是车型分组（判据就是 vehicle_type）。三种车各一档，三种之外（没设过车型的
        // 账号）单独一档 —— ⛔ 不能让他们无处可派。
        val kindOrder = listOf("small", "large", "trailer")
        val kinds = kindOrder.filter { k -> vm.drivers.any { (it.vehicleType ?: "") == k } } +
            if (vm.drivers.any { (it.vehicleType ?: "") !in kindOrder }) listOf("") else emptyList()
        var pickState by remember { mutableStateOf<String?>(null) }
        // 默认落在第一个真的有人 的档位（都没有时按大车组，与老行为一致）
        val pick = pickState?.takeIf { k -> kinds.contains(k) } ?: kinds.firstOrNull() ?: "large"
        var driverQuery by remember { mutableStateOf("") }
        val driverDrawer = rememberDrawerState(DrawerValue.Closed)
        val scope = rememberCoroutineScope()
        val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
        val picked = vm.selectedDriver

        // ⛔ 底色不许在这里传（见文件头 2026-10-05 那段）：全 App 抽屉的底一处说了算。
        ModalBottomSheet(
            onDismissRequest = { vm.showAssignDialog = false },
            sheetState = sheetState,
        ) {
            Box(Modifier.fillMaxSize()) {
                ModalNavigationDrawer(
                    drawerState = driverDrawer,
                    // 抽屉只在点「选择司机」那一行时开：表单里的横向手势很容易误开一整层
                    gesturesEnabled = false,
                    drawerContent = {
                        ModalDrawerSheet {
                            Row(Modifier.fillMaxSize()) {
                                // 左栏 = 车型档位（用户：「他直接拉起分类，像商品那样拉起一些分类列表」）。
                                // 走共用件 MasterRail（分类/司机/地址来源三处是同一份）。
                                MasterRail(
                                    items = kinds.map { k ->
                                        RailItem(key = k, label = driverKindLabel(k.ifBlank { null }))
                                    },
                                    selectedKey = pick,
                                    onSelect = { k ->
                                        pickState = k
                                        driverQuery = ""
                                        // 切档顺带选中这一档第一位：原有行为，本轮保留
                                        vm.selectedDriverId = vm.drivers
                                            .firstOrNull { (it.vehicleType ?: "") == k }?.id
                                    },
                                    modifier = Modifier.width(104.dp).fillMaxHeight(),
                                )
                                Box(Modifier.weight(1f)) {
                                    // 名单：这一档的人，再按搜索词收一遍（匹配规则走 core/UserSearch，
                                    // 与其它名册页同一条：名字 / 手机号）
                                    PersonDrawer(
                                        title = "选择司机",
                                        options = vm.drivers.filter { (it.vehicleType ?: "") == pick }
                                            .filter { d ->
                                                UserSearch.matches(driverQuery, d.fullName, d.phone)
                                            }
                                            .map { d ->
                                                PersonOption(
                                                    key = d.id.toString(),
                                                    title = d.fullName.ifBlank { d.username },
                                                    subtitle = d.phone,
                                                )
                                            },
                                        selectedKey = vm.selectedDriverId?.toString(),
                                        query = driverQuery,
                                        onQueryChange = { driverQuery = it },
                                        onPick = { key ->
                                            vm.selectedDriverId = key?.toLongOrNull()
                                            scope.launch { driverDrawer.close() }
                                        },
                                        emptyText = if (driverQuery.isBlank()) "这一档还没有司机"
                                        else UserSearch.noMatchText(driverQuery) + "司机",
                                    )
                                }
                            }
                        }
                    },
                ) {
                    Column(
                        Modifier
                            .fillMaxWidth()
                            // 用户要的「拉高一点」：抽屉占到屏高（与挂账单位那个抽屉同一档）
                            .fillMaxHeight()
                            .imePadding()
                            .verticalScroll(rememberScrollState())
                            .padding(horizontal = 16.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                if (vm.selectionMode) "批量派单（" + vm.selectedIds.size + " 单）" else "派单",
                                style = MaterialTheme.typography.titleLarge,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.weight(1f),
                            )
                            SheetCloseButton(onClick = { vm.showAssignDialog = false })
                        }
                        if (vm.drivers.isEmpty()) {
                            Text(
                                "暂无可用司机账号，请先在「司机管理」中添加",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.error,
                            )
                        } else {
                            // 选司机：一行白卡入口，点开 = 左边那层抽屉（老形态是描边输入框 + 下拉，
                            // 司机一多就得在一条竖列里翻 —— 用户：「不然司机多了就不好搞」）。
                            // 白卡压在抽屉的浅灰面上，就是用户要的「纸质书」那种层次。
                            PersonTriggerRow(
                                icon = kindIcon(picked?.vehicleType ?: pick),
                                color = MaterialTheme.colorScheme.primary,
                                // P8：标签跟着选中的人走（他是什么车型就写什么）；一位都没选时才写档位名
                                label = driverKindLabel(vm.selectedDriver?.vehicleType ?: pick.ifBlank { null }),
                                value = if (picked != null) (picked.fullName.ifBlank { picked.username }) + " " + picked.phone else "请选择司机",
                                onOpen = { scope.launch { driverDrawer.open() } },
                            )
                        }
                        if (!vm.selectionMode && vm.isPieceDriver(vm.selectedDriver)) {
                            // 白卡分组 + 共用行（规范 §5.0：分组一律白卡，卡里每一行自己再是一张
                            // 浅色内嵌卡）。⛔ 卡里不许出现描边输入框。
                            FormGroup(Icons.Default.Payments, "运费", MaterialTheme.colorScheme.primary) {
                                FormInputRow(
                                    "一车运费 ¥（可后补）",
                                    vm.assignFreight,
                                    // 金额规则唯一实现在 core/InputRules.kt
                                    { vm.assignFreight = InputRules.moneyInput(it) },
                                    keyboardType = KeyboardType.Decimal,
                                    icon = Icons.Default.Payments,
                                    iconTint = MaterialTheme.colorScheme.primary,
                                )
                                // 模板入口原来挂在输入框右边（框边一颗小字按钮）—— 卡片式布局里
                                // 放不下「框边挂按钮」，改成组里一行可点的选择行。
                                FormRow(
                                    label = "运费模板",
                                    icon = Icons.Default.Bookmarks,
                                    iconTint = MaterialTheme.colorScheme.primary,
                                    onClick = { templatePick = true },
                                ) {
                                    Text(
                                        "去套用",
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = MaterialTheme.colorScheme.primary,
                                    )
                                }
                            }
                        }
                        // 「这一单单独定（这一单的钱 ¥ / 提成 %）」整块 2026-10-05 删掉：
                        // 用户「像什么这一单决定多少钱提成多少这个不要管，我们以后直接在那个
                        // 订单里去给他订了」。⛔ 只删界面 —— VM 字段与后端参数没动。
                        FormGroup(
                            Icons.Default.AccountBalanceWallet,
                            "司机收款",
                            MaterialTheme.colorScheme.primary,
                        ) {
                            FormSwitchRow(
                                label = "收取现金",
                                checked = vm.assignCollectCash,
                                onCheckedChange = { vm.assignCollectCash = it },
                                icon = Icons.Default.Payments,
                                iconTint = MaterialTheme.colorScheme.primary,
                            )
                        }
                        // 这一句是给「收取现金」那句开关的说明（留在白卡外、紧贴卡下方）
                        Text(
                            "勾选后司机送达时可选择「收现金」或「挂账」；不勾选则送达自动挂账",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(start = 6.dp),
                        )
                        FormGroup(Icons.Default.Notes, "内部备注", MaterialTheme.colorScheme.primary) {
                            FormTextAreaRow(
                                "内部备注（可选，与司机可见）",
                                vm.assignNote,
                                { vm.assignNote = it },
                                minLines = 2,
                                icon = Icons.Default.Notes,
                                iconTint = MaterialTheme.colorScheme.primary,
                            )
                        }
                        // P8 附带（与 BUG-0003 同源）：这个框以前从不渲染 vm.error —— 没选司机就点
                        // 「确认派单」，那句「请选择司机」界面上没人看得见（用户侧＝点了没反应）。
                        // 规范 §4.8：表单的错画在表单里，位置在提交按钮上方。
                        FormErrorLine(vm.error)
                        Row(
                            Modifier.fillMaxWidth().padding(top = 2.dp),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            OutlinedButton(
                                onClick = { vm.showAssignDialog = false },
                                enabled = !vm.acting,
                                modifier = Modifier.weight(1f).height(48.dp),
                            ) { Text("取消") }
                            Button(
                                onClick = { vm.confirmAssign(onAssigned) },
                                enabled = !vm.acting,
                                modifier = Modifier.weight(1f).height(48.dp),
                            ) { Text(if (vm.acting) "派单中…" else "确认派单") }
                        }
                        Spacer(Modifier.height(24.dp))
                    }
                }
            }
        }
    }
    // 运费模板选择（本轮没动：仍是子弹窗，入口在运费那一组里）
    if (templatePick) {
        CardAlertDialog(
            onDismissRequest = { templatePick = false },
            title = { Text("选择运费模板") },
            text = {
                Column(Modifier.heightIn(max = 320.dp)) {
                    if (vm.templates.isEmpty()) {
                        Text(
                            "暂无模板，请先在「订单模板」中维护",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    } else {
                        vm.templates.forEach { t ->
                            Row(
                                Modifier.fillMaxWidth().clickable {
                                    vm.applyTemplate(t)
                                    templatePick = false
                                }.padding(vertical = 6.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Column(Modifier.weight(1f)) {
                                    Text(t.name, style = MaterialTheme.typography.bodyMedium, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold)
                                    Text(
                                        t.fromPlace + " → " + t.toPlace +
                                            (t.vehicleType?.let { v -> when (v) {
                                                "small" -> " · 小车"; "large" -> " · 大车"; "trailer" -> " · 挂车"; else -> "" } } ?: ""),
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                                Text(
                                    "¥" + formatMoney(t.fee),
                                    style = MaterialTheme.typography.titleSmall,
                                    fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                                    color = androidx.compose.ui.graphics.Color(0xFFBC7730),
                                )
                            }
                            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                        }
                    }
                }
            },
            confirmButton = { TextButton(onClick = { templatePick = false }) { Text("关闭") } },
        )
    }
}

/** 车型图标（空串 = 没设过车型的账号：用最中性的那个人形，别猜成某一种车）。 */
private fun kindIcon(kind: String): ImageVector = when (kind) {
    "small" -> Icons.Default.DirectionsCar
    "large" -> Icons.Default.LocalShipping
    "trailer" -> Icons.Default.AirportShuttle
    else -> Icons.Default.Person
}
