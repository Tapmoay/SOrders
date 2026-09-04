package com.tapmoay.sorders.ui.nav

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.ui.graphics.vector.ImageVector
import com.tapmoay.sorders.ui.theme.ArrearsTangerine
import com.tapmoay.sorders.ui.theme.InventoryTeal
import com.tapmoay.sorders.ui.theme.MemberGold
import com.tapmoay.sorders.ui.theme.MessageRed
import com.tapmoay.sorders.ui.theme.MgrGreen
import com.tapmoay.sorders.ui.theme.ProgressYellow
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.ui.theme.NavBlue
import com.tapmoay.sorders.ui.theme.ProductPurple
import com.tapmoay.sorders.ui.theme.ReportIndigo
import com.tapmoay.sorders.ui.theme.ShipperTeal

/**
 * 工作台图标入口。children 非空 = 分组（点击进入二级列表页），
 * 为空 = 直达页面（route 即导航路由）。
 * 新增功能：在这里加一条 ModuleEntry + 在 NavGraph 注册对应路由即可。
 * color = 模块语义色（老人友好：一色一功能，工作台/列表页按色快速定位）。
 */
data class ModuleEntry(
    val label: String,
    val route: String,
    val icon: ImageVector,
    val children: List<ModuleEntry> = emptyList(),
    val color: Long = NavBlue,
)

/** 底部导航 Tab（可配置：未来加 Tab 只改这里；color = 选中态语义色） */
data class BottomTab(
    val label: String,
    val icon: ImageVector,
    val content: String, // 内容标识：dispatch / workbench / messages / profile
    val color: Long = NavBlue,
)

object Modules {

    // ===== 派单员工作台 =====
    val dispatcherEntries: List<ModuleEntry> = listOf(
        ModuleEntry(
            label = "派单作业",
            route = Routes.MODULE_GROUP + "/dispatch",
            icon = Icons.Default.PendingActions,
            color = NavBlue, // 蓝 · 派单主操作
            children = listOf(
                ModuleEntry("待派单池", Routes.DISPATCH_POOL, Icons.Default.PendingActions),
                ModuleEntry("全部订单", Routes.DISPATCH_ORDERS, Icons.Default.ListAlt),
                ModuleEntry("订单模板", Routes.FREIGHT_TEMPLATES, Icons.Default.Receipt, color = MoneyOrange),
            ),
        ),
        ModuleEntry("代理下单", Routes.DISPATCH_ORDER_CREATE, Icons.Default.AddCircleOutline, color = MgrGreen),       // 绿 · 下单（与货主端下单同色）
        ModuleEntry("地址与联系人", Routes.ADDRESSES, Icons.Default.Place, color = ShipperTeal),                        // 湖蓝 · 地址
        ModuleEntry("订单管理", Routes.DISPATCH_ORDERS, Icons.Default.ReceiptLong, color = ProgressYellow),            // 黄 · 订单流转
        ModuleEntry("司机管理", Routes.DISPATCH_DRIVERS, Icons.Default.Groups, color = 0xFFCDDC39L),                    // 黄绿 · 司机团队
        ModuleEntry("货主管理", Routes.SHIPPERS_MANAGE, Icons.Default.PeopleAlt, color = InventoryTeal),                // 深青 · 货主
        ModuleEntry("批发商管理", Routes.MEMBERS, Icons.Default.Badge, color = MemberGold),                             // 金 · 批发
        ModuleEntry("商品管理", Routes.PRODUCTS, Icons.Default.Inventory2, color = ProductPurple),                      // 紫 · 商品
        ModuleEntry("库存管理", Routes.INVENTORY, Icons.Default.Warehouse, color = 0xFF00BCD4L),                        // 蓝青 · 库存仓储
        ModuleEntry("账本管理", Routes.DISPATCH_LEDGER, Icons.Default.AccountBalanceWallet, color = MoneyOrange),       // 橙 · 账本
        ModuleEntry("司机运费结算", Routes.FREIGHT_SETTLEMENT, Icons.Default.Payments, color = 0xFFFF8A65L),            // 珊瑚橙 · 运费结算
        ModuleEntry("挂账单位", Routes.ARREARS_UNITS, Icons.Default.Business, color = ArrearsTangerine),                 // 橙红 · 挂账警示
        // 报表中心直达营业额报表界面（顶部 4 页签：营业/商品/司机/异常，可切换）
        ModuleEntry(
            label = "报表中心",
            route = Routes.REPORT_HOME,
            icon = Icons.Default.BarChart,
            color = ReportIndigo,
        ),
        ModuleEntry("消息中心", Routes.MESSAGES, Icons.Default.Notifications, color = MessageRed),
    )

    // ===== 货主工作台 =====
    val shipperEntries: List<ModuleEntry> = listOf(
        ModuleEntry("我的订单", Routes.SHIPPER_ORDERS, Icons.Default.ListAlt),
        ModuleEntry("下单", Routes.ORDER_CREATE, Icons.Default.AddCircleOutline, color = MgrGreen),
        ModuleEntry("地址与联系人", Routes.ADDRESSES, Icons.Default.Place, color = ShipperTeal),
        ModuleEntry("我的账本", Routes.SHIPPER_LEDGER, Icons.Default.AccountBalanceWallet, color = MoneyOrange),
        ModuleEntry("消息中心", Routes.MESSAGES, Icons.Default.Notifications, color = MessageRed),
    )

    // ===== 司机工作台（信息入口少：我的任务，消息在右上角） =====
    val driverEntries: List<ModuleEntry> = listOf(
        ModuleEntry("我的任务", Routes.DRIVER_ORDERS, Icons.Default.LocalShipping, color = MgrGreen),
        ModuleEntry("我的账本", Routes.DRIVER_FREIGHT, Icons.Default.AccountBalanceWallet, color = MoneyOrange),
    )

    fun entriesFor(role: Role): List<ModuleEntry> = when (role) {
        Role.DISPATCHER -> dispatcherEntries
        Role.SHIPPER -> shipperEntries
        Role.DRIVER -> driverEntries
    }

    /** 按路由查找分组（二级列表页用） */
    fun findGroup(route: String): ModuleEntry? = dispatcherEntries
        .firstOrNull { it.route == route }

    /** 底部导航：派单端（派单作业/工作台/消息/我的），其他端（工作台/消息/我的）。加 Tab 只改这里 */
    fun bottomTabs(role: Role): List<BottomTab> = when (role) {
        Role.DISPATCHER -> listOf(
            BottomTab("派单作业", Icons.Default.PendingActions, "dispatch", color = NavBlue),
            BottomTab("工作台", Icons.Default.Apps, "workbench", color = ReportIndigo),
            BottomTab("消息", Icons.Default.Notifications, "messages", color = MessageRed),
            BottomTab("我的", Icons.Default.AccountCircle, "profile", color = ShipperTeal),
        )
        Role.DRIVER -> listOf(
            BottomTab("进行中", Icons.Default.LocalShipping, "driverOpen", color = ProgressYellow),
            BottomTab("已完成", Icons.Default.CheckCircle, "driverDone", color = MgrGreen),
            BottomTab("消息", Icons.Default.Notifications, "messages", color = MessageRed),
            BottomTab("我的", Icons.Default.AccountCircle, "profile", color = ShipperTeal),
        )
        else -> listOf(
            BottomTab("工作台", Icons.Default.Apps, "workbench", color = NavBlue),
            BottomTab("消息", Icons.Default.Notifications, "messages", color = MessageRed),
            BottomTab("我的", Icons.Default.AccountCircle, "profile", color = ShipperTeal),
        )
    }
}