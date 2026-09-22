package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp

/**
 * **选人**那一套零件的唯一实现：页面上那一行入口 + 里面那个侧边抽屉。
 *
 * ## 为什么放在这里（两个页面用的是同一个形态）
 *
 * 用户 2026-09-20 对**账本页**定的形态：
 * > 选择人物我们用那种**侧边栏抽屉**，可以在那里寻找人物，点击人物就可以了。
 *
 * 2026-09-22 他又把这套形态点名搬到**司机运费结算**：
 * > 那个司机他那个**不要按照这样子的商品的管理**啊……我们直接换那个**类似于货主的账本管理**
 * > 的那种形式，是那个**左侧的抽屉栏**在那里选择人物，**也可以在那里搜索**，
 * > 然后选择之后，我们就可以**直接看对应的那个司机那个结账**。
 *
 * 同一个形态两个页面各写一份，就是本项目反复交过学费的那一类：
 * 改一处漏一处（抽屉里加了"停用"标记，另一个页面没有），而**两边都不报错**。
 * 所以这两件东西只有一份定义，两个页面都调它：
 *
 * | 谁 | 页面 | 抽屉里装的是 |
 * |---|---|---|
 * | 账本页 | `ui/dispatcher/DispatcherLedgerScreen.kt` | 司机账 / 货主账 / 批发商账的人（带"全部"那一行） |
 * | 运费结算 | `ui/dispatcher/FreightSettlementScreen.kt` | 这个月有结算的司机（带"全部"那一行） |
 *
 * ## 三条规矩（都是用户点过名的，别在本文件里放松）
 *
 * 1. **选人一律走抽屉，不许退回"一排 chip"**：人一多，"在一条横着滑的 chip 里找"
 *    比看账本身还花时间（用户原话：「假如司机多的话，那我要选该怎么去选呢？」）。
 * 2. **搜索框在抽屉里**：抽屉里能搜（姓名 / 手机号 / 后 4 位）、能滚，选完自动关上。
 *    搜索实现是 `core/UserSearch`（本文件只调 [SearchField]，匹配口径一个字都不写）。
 * 3. **这一行不写金额**：金额在它下面那些行上（同一份信息写两处，就一定会"两边对不上"）。
 *    抽屉里的名单可以带副标题（运费结算就是「手机号 · ¥860 · 21 单」），因为那里**就是**挑人的地方。
 */

/**
 * 抽屉里的一行（[PersonDrawer] 的数据形状）。
 *
 * [subtitle] 是"同名不同人"唯一的分辨依据（两个「张老板」在真机上就是两行一样的名字），
 * 所以调用方**尽量**把手机号放进去；没有号的要说清"为什么没有"。
 */
data class PersonOption(
    val key: String,
    val title: String,
    val subtitle: String = "",
)

/**
 * 人员那一行：**页面上唯一一个"选人"的入口**（点开侧边抽屉）。
 *
 * ⚠️ 这一行**不写金额**（金额在下面的行上）—— 同一份信息写两处，就一定会"两边对不上"。
 *
 * @param label 左边那个小标题（「人员」/「司机」）
 * @param value 当前是谁：没有选中时说清"全部有几个人"（「全部（3 位司机）」），
 *   选了人就说名字 —— 抽屉关掉之后，这一行是页面上唯一写着"现在在看谁"的地方。
 */
@Composable
fun PersonTriggerRow(
    icon: ImageVector,
    color: Color,
    label: String,
    value: String,
    onOpen: () -> Unit,
) {
    Surface(
        onClick = onOpen,
        color = MaterialTheme.colorScheme.surface,
        shape = MaterialTheme.shapes.medium,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
    ) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TintedIcon(icon, color, size = 16.dp, container = 32.dp)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    label,
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    value,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Spacer(Modifier.width(8.dp))
            Text("选择", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
            Icon(
                Icons.Default.ChevronRight,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
            )
        }
    }
}

/**
 * 侧边抽屉的内容：**搜索框 + 名单**（[allLabel] 非空时第一行永远是「全部」）。
 *
 * 「全部」放在最上面而不是藏起来：默认状态就是它，用户看完某个人要回到"所有人在这一段的账"
 * 时得有个明确的地方点。
 *
 * @param selectedKey 当前选中的人；`null` = 选中的是「全部」
 * @param onPick 选人回调；**`null` = 选了「全部」**（两边都只走这一条路，不许各写一个入口）
 * @param emptyText 搜不到人时那句话（用 `UserSearch.noMatchText(query)` 拼，别自己写）
 */
@Composable
fun PersonDrawer(
    title: String,
    options: List<PersonOption>,
    selectedKey: String?,
    query: String,
    onQueryChange: (String) -> Unit,
    onPick: (String?) -> Unit,
    emptyText: String,
    allLabel: String? = null,
    allSubtitle: String = "",
) {
    Column(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        Spacer(Modifier.height(20.dp))
        Text(
            title,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
        )
        Spacer(Modifier.height(10.dp))
        SearchField(value = query, onValueChange = onQueryChange)
        Spacer(Modifier.height(8.dp))
        LazyColumn(Modifier.weight(1f)) {
            if (allLabel != null) {
                item(key = "all") {
                    DrawerPersonRow(
                        title = allLabel,
                        subtitle = allSubtitle,
                        selected = selectedKey == null,
                        onClick = { onPick(null) },
                    )
                }
            }
            if (options.isEmpty()) {
                item {
                    Text(
                        emptyText,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(vertical = 16.dp),
                    )
                }
            } else {
                items(options, key = { it.key }) { o ->
                    DrawerPersonRow(
                        title = o.title,
                        subtitle = o.subtitle,
                        selected = selectedKey == o.key,
                        onClick = { onPick(o.key) },
                    )
                }
            }
        }
        Spacer(Modifier.height(12.dp))
    }
}

/** 抽屉里的一行（选中那行打勾 + 加粗）。 */
@Composable
private fun DrawerPersonRow(title: String, subtitle: String, selected: Boolean, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Column(Modifier.weight(1f)) {
            Text(
                title,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            if (subtitle.isNotBlank()) {
                Text(
                    subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                )
            }
        }
        // ⚠️ 打勾只画在**选中**那一行上：抽屉里同时亮着两行时，用户不知道自己到底在看谁
        if (selected) {
            Icon(Icons.Default.Check, contentDescription = "当前选中", tint = MaterialTheme.colorScheme.primary)
        }
    }
}
