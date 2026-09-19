package com.tapmoay.sorders.ui.nav

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.ui.theme.ArrearsTangerine
import com.tapmoay.sorders.ui.theme.AiBlue
import com.tapmoay.sorders.ui.theme.AiPink
import com.tapmoay.sorders.ui.theme.AiPurple
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
 * gradient 非空 = 这块图标用**品牌渐变**而不是单色（目前只有 AI 用：Google AI 的
 *   蓝→紫→粉，见 theme/AiBrand.kt）。用渐变而不是单色是刻意的：AI 不是一个"业务模块"，
 *   它是**另一种用法**（说一句话，而不是点进某个功能），外观上就该和其余方块不是一类。
 */
data class ModuleEntry(
    val label: String,
    val route: String,
    val icon: ImageVector,
    val children: List<ModuleEntry> = emptyList(),
    val color: Long = NavBlue,
    val gradient: List<Long> = emptyList(),
)

/** 底部导航 Tab（可配置：未来加 Tab 只改这里；color = 选中态语义色） */
data class BottomTab(
    val label: String,
    val icon: ImageVector,
    val content: String, // 内容标识：dispatch / workbench / messages / profile
    val color: Long = NavBlue,
)

/**
 * 底部导航正中间那个**凸起的圆形 AI 入口**的尺寸（见 RoleHomeScreen）。
 *
 * 单独抽成常量是因为它有两个必须相等的数值：给凸起留出的顶部内边距、圆钮的向上偏移量。
 * 两处写死两个数字，改一个忘一个，圆钮就会**被裁掉一半**（低于留白）或**浮空**（大于留白）。
 */
object AiNavButton {
    /** 圆钮直径。比导航栏的图标大一圈，才能"凸出来"得自然。 */
    val Size = 58.dp

    /**
     * 凸出导航栏上沿的高度。同时用作给凸起预留的顶部内边距，两者必须一致。
     *
     * 16dp → 12dp（用户 2026-09-17 反馈「把那个原先按钮稍微向下移一点」）：
     * 圆钮往上露得越少、坐得越低，和凹口一起看才像"嵌在栏里"而不是"飘在栏上"。
     */
    val Protrude = 12.dp

    /** 图标大小。 */
    val IconSize = 27.dp
}

object Modules {

    // ===== 派单员工作台 =====
    //
    // ⛔ **工作台里不再有「派单作业」那个分组图标**（用户 2026-09-19：「将 pai 工作台里的派单
    //    那个图标给去掉」）。它原来是个分组，点进去是「待派单池 / 全部订单 / 订单模板 / 计费规则」——
    //    去掉是对的：**待派单池本来就是底部导航第一个 Tab**（同一个页面两个入口），
    //    「全部订单」与下面那个「订单管理」图标**指向同一条路由**（同一页两个入口）。
    //    剩下两个不是"订单"的东西（运费模板 / 计费规则）已经按用户要求**提成独立图标**了，
    //    所以这个分组现在一个独占的子项都没有 —— 留着只会让人多点一次。
    //
    // ⚠️ 分组的**机制**还在（`ModuleEntry.children` + `Routes.MODULE_GROUP` +
    //    `WorkbenchScreen.kt::ModuleListScreen`）：它是工作台的通用能力，删掉的话下次要加分组
    //    得再写一遍。但**本轮之后没有任何一个网格用它**（三端 children 全为空）——
    //    别以为它是活的。
    val dispatcherEntries: List<ModuleEntry> = listOf(
        ModuleEntry("代理下单", Routes.DISPATCH_ORDER_CREATE, Icons.Default.AddCircleOutline, color = MgrGreen),       // 绿 · 下单（与货主端下单同色）
        ModuleEntry("地址与联系人", Routes.ADDRESSES, Icons.Default.Place, color = ShipperTeal),                        // 湖蓝 · 地址
        ModuleEntry("订单管理", Routes.DISPATCH_ORDERS, Icons.Default.ReceiptLong, color = ProgressYellow),            // 黄 · 订单流转
        ModuleEntry("账户管理", Routes.ACCOUNTS, Icons.Default.AccountBox, color = 0xFF8D6E63L),                     // 棕 · 统一建号（账号+密码+角色）
        ModuleEntry("司机管理", Routes.DISPATCH_DRIVERS, Icons.Default.Groups, color = 0xFFCDDC39L),                    // 黄绿 · 司机团队
        ModuleEntry("货主管理", Routes.SHIPPERS_MANAGE, Icons.Default.PeopleAlt, color = InventoryTeal),                // 深青 · 货主
        ModuleEntry("批发商管理", Routes.MEMBERS, Icons.Default.Badge, color = MemberGold),                             // 金 · 批发
        ModuleEntry("商品管理", Routes.PRODUCTS, Icons.Default.Inventory2, color = ProductPurple),                      // 紫 · 商品
        ModuleEntry("库存管理", Routes.INVENTORY, Icons.Default.Warehouse, color = 0xFF00BCD4L),                        // 蓝青 · 库存仓储
        ModuleEntry("账本管理", Routes.DISPATCH_LEDGER, Icons.Default.AccountBalanceWallet, color = MoneyOrange),       // 橙 · 账本
        // 「运费模板」「计费规则」原来挂在「派单作业」分组下，用户 2026-09-19 要求提成**两个独立图标**
        // （「去掉这个将里面的计费模板和计费规则，给移出来做一个 2 个单独的图标放在工作台里面」）。
        // 位置紧挨着「账本管理 / 司机运费结算」这一串**钱的入口**：它们回答的正是"这钱按什么算"。
        //
        // 名字：用户口述是「计费模板」，但**没有照抄** —— 它和旁边的「计费规则」只差一个字，
        // 并排摆两个几乎同名的图标，用户每次都得想一下点哪个（那正是"反人性"）。
        // 这一页自己的弹窗与字段本来就叫「新建运费模板」「一车价格」，所以取**运费模板**：
        // 两者含义本来就不同（一个是**订单运费**的价目表，一个是**司机拿多少**的规则）。
        //
        // 颜色：两个都是新色，都不是随手挑的（与工作台所有已有色的 RGB 欧氏距离最小值，
        // 本项目"同屏不许撞色"的判据是 ≥60）：
        //  · 运费模板 = 深靛 #283593（最小距离 **121**，与报表的亮靛 #6950F5 同族但深浅分明）
        //  · 计费规则 = 橄榄 #9E9D24（最小距离 **80**，与「司机管理」的黄绿同族 ——
        //    它们都指"司机这块"，同族不同深浅）
        ModuleEntry("运费模板", Routes.FREIGHT_TEMPLATES, Icons.Default.Receipt, color = 0xFF283593L),                 // 深靛 · 订单运费的价目表
        ModuleEntry("计费规则", Routes.DRIVER_BILLING_RULES, Icons.Default.RequestQuote, color = 0xFF9E9D24L),           // 橄榄 · 司机怎么算钱
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
        // ⚠️ AI 助手**不在这里**：它的入口是底部导航正中间那个凸起的圆钮（见 RoleHomeScreen）。
        // 放两处会让人以为是两个功能；它现在是"随时按一下"的入口，不该混在"进哪个模块"的网格里。
        // 例外见 shipperEntries：货主端只有 3 个 Tab，圆钮落不到正中，那边才改成网格图标。
    )

    // ===== 货主工作台 =====
    val shipperEntries: List<ModuleEntry> = listOf(
        // 「我的订单」从默认蓝改成订单黄：它和「下单」是一件事的两头（下单→看单），
        // 黄也**更合规矩**——派单端「订单管理」就是黄，跨端同功能同色
        // （下单绿 / 账本橙 / 消息红 / 地址湖蓝 / 订单黄）。
        ModuleEntry("我的订单", Routes.SHIPPER_ORDERS, Icons.Default.ListAlt, color = ProgressYellow),
        ModuleEntry("下单", Routes.ORDER_CREATE, Icons.Default.AddCircleOutline, color = MgrGreen),
        ModuleEntry("地址与联系人", Routes.ADDRESSES, Icons.Default.Place, color = ShipperTeal),
        ModuleEntry("我的账本", Routes.SHIPPER_LEDGER, Icons.Default.AccountBalanceWallet, color = MoneyOrange),
        ModuleEntry("消息中心", Routes.MESSAGES, Icons.Default.Notifications, color = MessageRed),
        // AI 助手放**最后一格**（用户 2026-09-15 明确要求：不要第一个）。
        // 理由站得住：这一排前 5 格是"货主日常办的事"（看单/下单/地址/账本/消息），
        // 顺序本身就是在教他怎么用；AI 是"这些事都能用嘴说"的另一条路，垫底不抢主流程，
        // 又因为它是唯一的**渐变色块**，真需要它的新用户一眼还是能找到。
        //
        // 为什么货主的 AI 在工作台网格里、派单员的在底部导航正中：
        // 货主底部只有 3 个 Tab，凸起圆钮只能落在 1/4 处（偏左的第二个槽位），不对称、
        // 看着像排错了；派单端 4 Tab + 圆钮 = 5 槽正中，保持不动。
        ModuleEntry(
            label = "AI 助手",
            route = Routes.AI_CHAT,
            icon = Icons.Default.AutoAwesome,
            color = AiBlue,
            gradient = listOf(AiBlue, AiPurple, AiPink), // Google AI 三段品牌渐变
        ),
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