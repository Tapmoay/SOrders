package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.ui.common.AppTopBar
import com.tapmoay.sorders.ui.common.EntryCard
import com.tapmoay.sorders.ui.common.EntryCardGrid
import com.tapmoay.sorders.ui.nav.Modules

/**
 * 「账本管理」入口页：**和报表中心一样的版式**（用户 2026-09-20 第二次改口）。
 *
 * ## 这一页是怎么来的（两轮改口的原话，别再折腾）
 *
 * 第一轮他要的是"工作台第二张卡片、里面 8 个图标"：「干脆就在工作台里做 2 个卡片…就叫账本管理，
 * 然后将账本管理的所有的 8 个模块全部拆成类似于工作台现在的一个图标的形式，放在一个卡片」。
 * 做完他看了真机，**推翻了**：
 *
 * > 派单员的那个工作台全部改一下，**改回原来的样式**……首先，我们将司机的账和司机结算这 2 个
 * > 东西**合并成一个**；然后订单账本，再加上货主账本以及批发商账，还有客户收款以及开销管理，
 * > **合并成一个形式，就叫做账本管理**，这个账本管理**类似于报表中心的形式**；
 * > 然后车辆台账属于车辆管理，车辆管理直接放在桌面上就行了。
 *
 * 所以现在：**工作台回到单网格**（`WorkbenchScreen` 只有一张卡片），这一页是那 6 件事的入口，
 * 版式与报表中心**共用** `EntryCardGrid`（抄一份的话两页迟早长得不一样）。
 *
 * ⚠️ 6 件事的清单唯一来源是 [Modules.ledgerHomeEntries] —— 这里不许再写一份。
 * ⚠️ **「司机结算」不单独占一格**：它并进「司机账」那一格里（在那类账的页面上有入口），
 *    这是用户点名要的"合并成一个"。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LedgerHomeScreen(container: AppContainer, onBack: () -> Unit, onOpen: (String) -> Unit) {
    Scaffold(
        topBar = { AppTopBar(title = "账本管理", onBack = onBack) },
    ) { pad ->
        EntryCardGrid(
            entries = Modules.ledgerHomeEntries.map {
                EntryCard(key = it.route, label = it.label, icon = it.icon, color = Color(it.color))
            },
            onOpen = { onOpen(it.key) },
            modifier = Modifier.padding(pad),
        )
    }
}
