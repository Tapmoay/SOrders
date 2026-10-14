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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.UserSearch
import com.tapmoay.sorders.data.remote.dto.UserDto
import com.tapmoay.sorders.ui.theme.InventoryTeal

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
 * ## 左分类 + 右列表 + 可搜（CHG-0128，用户 2026-10-15 逐字）
 * > 「像**选地点库那样**（左分类、右对应项）」
 *
 * 版式照「选择收货地址」那一份（`ui/shipper/OrderCreateScreen.kt::AddressPickerSheet`，
 * 用户点名的就是它）：搜索框横跨整页在左栏**上面**，下面 [MasterRail] 左栏 + 右列表；
 * ⚠️ 左栏一格都**不带「N 条」**（用户 2026-09-19：「那个分组下面不要显示有多少条啊，这是多余信息」）。
 *
 * ### ⚠️ 这一格选的是**账号**，不是 `shipper_contacts` 那张名册
 * 订单上的 `shipper_id` 指向 `users.id`，所以这一栏只可能是「已注册的货主**账号**」
 * （左栏分的是账号自己的分类 `UserDto.category`，名册在 `user_categories`——
 * 与「货主管理」那一页左栏同一份数据、同一个口径）。
 * 用户口中的"已建好的联系人"在这一格**语义上**就是这些账号；有名有姓没账号的收货人
 * （`shipper_contacts`）属于**同一页的「收货人」那一栏**，它走的是 [ContactPickerSheet]
 * （分类来自 `contact_categories`）。两者混用会写出一个后端不认的 `shipper_id` —— 刻意不混。
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
    // 左栏那一列（CHG-0128）：分组算法只有一份 —— PersonGroups.kt 转发 categoryTabsOf。
    // ⛔ 不在这里自己分组：「未分类」（没填分类的账号）永远排最后、名册外的老分类照样出一格，
    //    都在那一份里；一个都不许藏（藏起来的表现是"这个货主不存在"→ 用户去填临时货主 →
    //    同一个人两本账，账本上对不上）。
    val groups = remember(shippers) { groupTabsOf(shippers) { it.category } }
    var group by remember { mutableStateOf(ALL_CATEGORY) }
    // ⚠️ 选中的那一类被改名/删掉之后（名册一变），右栏按老名字一条都筛不到 ——
    //    看起来像"这一类是空的"。名册一变就核对一次选中项。
    LaunchedEffect(groups) { if (group !in groups) group = ALL_CATEGORY }
    // 分类与搜索是**两个维度**，交叉筛（切分类不清空搜索词）。
    val visible = remember(shown, group) { inGroup(shown, group) { it.category } }
    val visibleTop = visible.take(100)

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
        Column(
            Modifier.fillMaxWidth().fillMaxHeight(0.92f).padding(bottom = 12.dp),
        ) {
            Row(
                Modifier.padding(horizontal = 20.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
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
            // ⚠️ 它整块画在左栏**上面**：临时货主没有账号、也就没有分类，
            //    塞进任何一类都会把"这个人是谁"说错。
            Column(Modifier.padding(horizontal = 20.dp)) {
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
            }
            Spacer(Modifier.height(14.dp))
            Text("已注册货主", style = MaterialTheme.typography.labelLarge, modifier = Modifier.padding(horizontal = 20.dp))
            Spacer(Modifier.height(6.dp))
            // 搜索框横跨整页（在左栏**上面**）：左栏是"分在哪一类"、搜索是"那个人在哪"，
            // 两个维度；放进左栏会被压成半宽，而且左栏为空时它跟着消失。
            Box(Modifier.fillMaxWidth().padding(horizontal = 20.dp)) {
                SoTextField(
                    value = keyword,
                    onValueChange = { keyword = it },
                    placeholder = UserSearch.HINT,
                )
                if (keyword.isNotBlank()) {
                    TextButton(
                        onClick = { keyword = "" },
                        modifier = Modifier.align(Alignment.CenterEnd),
                    ) { Text("清除") }
                }
            }
            Spacer(Modifier.height(6.dp))
            Row(Modifier.fillMaxWidth().weight(1f)) {
                MasterRail(
                    items = groups.map { RailItem(key = it, label = it) },
                    selectedKey = group,
                    // 强调色 = **货主管理松绿**（规范 §2 一色一功能「货主管理」那一格）：
                    // 这一格选的就是货主账号，与「货主管理」那一页同一色。
                    accent = Color(InventoryTeal),
                    onSelect = { group = it },
                    modifier = Modifier.width(112.dp).fillMaxHeight(),
                )
                Column(
                    Modifier.weight(1f).fillMaxHeight().padding(horizontal = 12.dp)
                        .verticalScroll(rememberScrollState()),
                ) {
                    if (shippers.isEmpty()) {
                        Text(
                            "暂无货主",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(vertical = 12.dp),
                        )
                    } else if (visible.isEmpty()) {
                        // 搜索命中了、只是**不在这一类里**：说清是"这一类里没有"，
                        // 否则用户会以为整个名册都没有这个货主，转头去填一个临时货主（两本账）。
                        Text(
                            if (kw.isBlank()) "「" + group + "」里还没有货主。"
                            else "没有匹配「" + kw + "」的货主。",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(vertical = 12.dp),
                        )
                    }
                    visibleTop.forEach { s ->
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
                    if (visible.size > visibleTop.size) {
                        Text(
                            "还有 " + (visible.size - visibleTop.size) + " 位没显示 —— 输入姓名或手机号缩小范围。",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(vertical = 8.dp),
                        )
                    }
                }
            }
        }
    }
}
