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
        ModuleEntry("商品管理", Routes.PRODUCTS, Icons.Default.Inventory2, color = 0xFF9570E0L),                     // 柔紫 · 商品（工作台专用，见下面的说明）
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
        // 本项目"同屏不许撞色"的判据是 ≥60）。
        //
        // ⚠️ 2026-09-19 这两个色**换过一次**（用户看真机后点名）：
        //    「计费规则和运费模板，感觉颜色有点深啊。尤其是运费模板，他那个是**深蓝**颜色，
        //      在整个工作台里是**非常的抢眼**」。
        //    第一版给的是 深靛 #283593（亮度 58%）与 橄榄 #9E9D24（亮度 62%）——
        //    在整个工作台（其余 14 格亮度普遍 78% 以上）里，这两格明显"沉下去"，而且
        //    深色底 + 白图标在浅色网格里最扎眼，正好和"一色一功能、整体克制"要的效果相反。
        //    现在按标准的色带（S 70-90%、B 78-95%）在**同一色相**上提亮：
        //  · 运费模板 = 雾蓝 #5F7FBF（**刻意压低饱和与亮度**：S 50 / B 75，
        //    比标准的色带（S 70-90、B 78-95）更低一档 —— 见下面那段"为什么破例"）
        //  · 计费规则 = 亮黄绿 #8EC714（亮度 62%→78%，最小距离 **76**，与「司机管理」的黄绿同族）
        //    计费规则跑过 `_archive/_pick_module_colors.py`（在 HSB 空间里搜"带内 + 与其余 14 色
        //    距离 ≥66"的解），运费模板的雾蓝是按下面那条人工约束定的（机器只负责验距离：68）。
        //
        // ⚠️⚠️ 运费模板这个蓝**换过两次**，第二次是**故意不守色带**的：
        //    第一版 #283593（深靛，亮度 58%）用户说"有点深"；
        //    第二版按标准提亮到 #162DDB（亮度 86%）用户说"**更显眼了，而且亮度比较高**"，
        //    并给了那个我漏掉的关键观察 ——「他周围基本上要么就是淡的、要么就是暖色调，
        //    **一个冷色调在这里显得太显眼了**」。
        //    也就是说：**问题不在这一格本身，而在它左右的邻居**（左边账本=橙、右边计费规则=黄绿、
        //    上面批发商=金），一个满饱和的纯冷蓝夹在中间，是整屏对比最强的地方。
        //    所以这一格改成低饱和的雾蓝，让它**退到后面去**。
        //    ⛔ 这条不是"标准可以随便破"：色带管的是"主色该多亮多艳"，而这里要的是
        //    "16 格里最不该抢眼的那一格"，两条目标冲突时**以用户的眼睛为准**（他也确实是对的）。
        //
        // ⚠️⚠️ 同一手法**又用了 4 次**（用户 2026-09-19 第二轮）：「将商品管理、报表中心、
        //    挂账单位、消息中心都做相同的处理啊，现在这 4 个看起来比较鲜艳」。
        //    这 4 格原来是全屏饱和度/亮度最高的一批（S63-83 / B90-100），压完：
        //      商品管理 #8455E6 → #9570E0（S50/B88）· 报表中心 #6950F5 → #614AE0（B88）
        //      挂账单位 #FF6B2C → #D96B3D（S72/B85）· 消息中心 #FF4D4F → #B53638（B71）
        //    同样按 `_archive/_pick_module_colors2.py` 搜（色相不动、与其余 15 格距离 ≥62）。
        //
        // ⛔ **只改工作台这一格，不动全局那几个语义色**（`MessageRed` / `ArrearsTangerine` /
        //    `ProductPurple` / `ReportIndigo`）：它们在别处担的是**功能语义**——
        //    消息红要做角标（角标**必须**跳出来）、挂账要警示、报表页签要区分。
        //    把全局色一起压暗 = "为了工作台好看，顺手把全 App 的通知角标也弄哑"。
        ModuleEntry("运费模板", Routes.FREIGHT_TEMPLATES, Icons.Default.Receipt, color = 0xFF5F7FBFL),                 // 雾蓝 · 订单运费的价目表
        ModuleEntry("计费规则", Routes.DRIVER_BILLING_RULES, Icons.Default.RequestQuote, color = 0xFF8EC714L),           // 亮黄绿 · 司机怎么算钱
        ModuleEntry("司机运费结算", Routes.FREIGHT_SETTLEMENT, Icons.Default.Payments, color = 0xFFFF8A65L),            // 珊瑚橙 · 运费结算
        ModuleEntry("挂账单位", Routes.ARREARS_UNITS, Icons.Default.Business, color = 0xFFD96B3DL),                  // 柔砖橙 · 挂账警示（工作台专用）
        // 报表中心直达营业额报表界面（顶部 4 页签：营业/商品/司机/异常，可切换）
        ModuleEntry(
            label = "报表中心",
            route = Routes.REPORT_HOME,
            icon = Icons.Default.BarChart,
            color = 0xFF614AE0L,   // 柔靛紫（工作台专用一档，比全局的 ReportIndigo 暗一档）
        ),
        ModuleEntry("消息中心", Routes.MESSAGES, Icons.Default.Notifications, color = 0xFFB53638L),
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
        ModuleEntry("消息中心", Routes.MESSAGES, Icons.Default.Notifications, color = 0xFFB53638L),
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