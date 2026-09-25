package com.tapmoay.sorders.ui.nav

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.Capabilities
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
import com.tapmoay.sorders.ui.theme.UnitConvRose

/**
 * 工作台图标入口：**一格 = 一个页面**（`route` 即导航路由）。
 * 新增功能：在这里加一条 ModuleEntry + 在 NavGraph 注册对应路由即可。
 * color = 模块语义色（老人友好：一色一功能，工作台/列表页按色快速定位）。
 * gradient 非空 = 这块图标用**品牌渐变**而不是单色（目前只有 AI 用：Google AI 的
 *   蓝→紫→粉，见 theme/AiBrand.kt）。用渐变而不是单色是刻意的：AI 不是一个"业务模块"，
 *   它是**另一种用法**（说一句话，而不是点进某个功能），外观上就该和其余方块不是一类。
 *
 * ⛔ 2026-09-20 **删掉了「分组（二级列表页）」那套机制**（`children` 字段 + `findGroup` +
 *    `Routes.MODULE_GROUP` 路由 + `ModuleListScreen`）：三端 `children` 全为空，
 *    那条路由**没有任何入口点得到**，等于一条永远走不到的死路 —— 而它还带着
 *    "工作台支持分组"这个假印象（下一个接手的人会照它去加 `children`，然后发现没人会导航过去）。
 *    真要再分组时按当时的版式写一遍，比留一套猜不到口径的半成品便宜。
 */
data class ModuleEntry(
    val label: String,
    val route: String,
    val icon: ImageVector,
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
    //    分组那套机制本身也已删除（见 [ModuleEntry] 的注释：三端 children 全空 = 死路）。
    val dispatcherEntries: List<ModuleEntry> = listOf(
        ModuleEntry("代理下单", Routes.DISPATCH_ORDER_CREATE, Icons.Default.AddCircleOutline, color = MgrGreen),       // 绿 · 下单（与货主端下单同色）
        // 「预订单」（2026-09-22 用户要求「专门去管理预设的订单」）：预设好的订单 ——
        // 点「用这张下单」把商品与数量带进下单页。它**不生成订单**，所以与「代理下单」是两格。
        // 颜色取靛蓝：与网格里已有的十几个语义色两两距离 ≥60（判据在同名单测里）。
        ModuleEntry("预订单", Routes.DISPATCH_ORDER_TEMPLATES, Icons.Default.BookmarkAdded, color = 0xFF3949ABL),
        ModuleEntry("地址与联系人", Routes.ADDRESSES, Icons.Default.Place, color = ShipperTeal),                        // 湖蓝 · 地址
        ModuleEntry("订单管理", Routes.DISPATCH_ORDERS, Icons.Default.ReceiptLong, color = ProgressYellow),            // 黄 · 订单流转
        // 退货申请（2026-09-21）：货主（含批发商）在订单上**只能申请**，**这里才是实际执行** ——
        // 点了「办理退货」那一刻库存、账本、退款、订单状态才变（用户原话：「批发商只是一个申请，
        // 派单员才是实际性的操作」）。所以它紧挨着「订单管理」：同一件事的两头。
        ModuleEntry("退货申请", Routes.DISPATCH_RETURN_REQUESTS, Icons.Default.AssignmentReturn, color = 0xFFB3492FL),  // 棕橙 · 退货这条线
        ModuleEntry("账户管理", Routes.ACCOUNTS, Icons.Default.AccountBox, color = 0xFF8D6E63L),                     // 棕 · 统一建号（账号+密码+角色）
        ModuleEntry("司机管理", Routes.DISPATCH_DRIVERS, Icons.Default.Groups, color = 0xFFCDDC39L),                    // 黄绿 · 司机团队
        ModuleEntry("货主管理", Routes.SHIPPERS_MANAGE, Icons.Default.PeopleAlt, color = InventoryTeal),                // 深青 · 货主
        ModuleEntry("批发商管理", Routes.MEMBERS, Icons.Default.Badge, color = MemberGold),                             // 金 · 批发
        ModuleEntry("商品管理", Routes.PRODUCTS, Icons.Default.Inventory2, color = ProductPurple),                      // 紫 · 商品（还原成原来的色）
        ModuleEntry("库存管理", Routes.INVENTORY, Icons.Default.Warehouse, color = 0xFF00BCD4L),                        // 蓝青 · 库存仓储
        // 单位换算（2026-09-24 用户要求：「一车是等于 8 方」）。
        // 紧挨着商品/库存两格：它管的是"这件货怎么计量"，与那两块是同一族的事。
        // ⚠️ 用户点名要的按钮在「请选择单位」页里（派单员从商品编辑才到得了），
        //    所以另开这一格 —— 货主也要能自己设（他原话：「我们的货主和派单员，他可以自动的设置单位」）。
        ModuleEntry("单位换算", Routes.UNIT_CONVERSIONS, Icons.Default.SwapHoriz, color = UnitConvRose),                // 洋红紫 · 一车=8方
        // 「账本管理」**回到工作台网格**（用户 2026-09-20 第二轮：那张卡片被推翻，工作台改回原来的样式）。
        // 这一格点进去是**入口页**（`LedgerHomeScreen`，报表中心那种形式），里面 6 件事：
        // 司机账（已并入司机结算）/ 订单账 / 货主账 / 批发商账 / 客户收款 / 开销管理。
        // 颜色沿用「账本 = 橙」这条跨端同色约定（与货主端「我的账本」同色）。
        ModuleEntry("账本管理", Routes.LEDGER_HOME, Icons.Default.AccountBalanceWallet, color = MoneyOrange),           // 橙 · 账本（跨端同色）
        // ⛔ 这里**没有**「开销管理」那一格：它并进上面「账本管理」里了（用户点名要合并）。
        ModuleEntry("车辆管理", Routes.DISPATCH_VEHICLES, Icons.Default.DirectionsCar, color = 0xFF48F0F0L),            // 亮青 · 车与车况（用户：「车辆管理直接放在桌面上」）
        // ⛔ 这里**没有**「账本管理」那一格：它连同它下面那 8 件事一起搬到了工作台的
        //    第二张卡片里（`dispatcherLedgerEntries`，用户 2026-09-20 点名）。留着这一格
        //    就等于同一个东西有两个入口，而且这一格点进去只是"账本页的默认档位"——
        //    用户真正要找的是下面 8 件里的**那一件**。
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
        //    那 4 格原来是全屏饱和度/亮度最高的一批（S63-83 / B90-100）。
        //    ⚠️ 其中**商品管理**压对了（#8455E6 → #9570E0，兑白方向）；
        //    **报表/挂账/消息三格压错了**（往下压亮度），2026-09-20 按上面那段纠回"兑白"。
        //
        // ⛔ **只改工作台这一格，不动全局那几个语义色**（`MessageRed` / `ArrearsTangerine` /
        //    `ProductPurple` / `ReportIndigo`）：它们在别处担的是**功能语义**——
        //    消息红要做角标（角标**必须**跳出来）、挂账要警示、报表页签要区分。
        //    把全局色一起压暗 = "为了工作台好看，顺手把全 App 的通知角标也弄哑"。
        //
        // ⚠️⚠️ 这几格**来回改了三轮**，把口径记在这儿，别再折腾了（用户 2026-09-20 最后一句）：
        //    「挂账单位和报表中心**又太淡了，就是太灰了**。你要看一下，其他的比如说代理下单啊、
        //      地址与联系人、账户管理、货主管理，他们的**明度、鲜艳程度是要差不多一样的，
        //      只是色相的不同**」。
        //    ⛔ 结论：**工作台 16 格的标准就是"跟邻居一样实、一样亮，只差色相"** ——
        //      · 往下压亮度 ❌（会出全屏唯一的深色，比原来还跳）；
        //      · 往白里兑 ❌（变灰，"太淡了"，就是这一轮被否的）；
        //      · 唯一对的：**保持原来那一档的饱和与亮度**（S 74-100 / B 66-100 这个家族带），
        //        只有色相不同。所以挂账单位、报表中心、消息中心**全部还原成原来的颜色**
        //        （`ArrearsTangerine` / `ReportIndigo` / `MessageRed`）。
        //    ⚠️ 唯一**刻意**留在家族带外面的还是「运费模板」的雾蓝 #5F7FBF ——
        //      它两次被点名"太显眼"（深靛太沉、亮靛太跳），用户明确要它"退到后面去"，
        //      这一格的目标跟"跟邻居一样"相反，是**单独一条**规则（见上面那段）。
        ModuleEntry("运费模板", Routes.FREIGHT_TEMPLATES, Icons.Default.Receipt, color = 0xFF5F7FBFL),                 // 雾蓝 · 订单运费的价目表
        ModuleEntry("计费规则", Routes.DRIVER_BILLING_RULES, Icons.Default.RequestQuote, color = 0xFF8EC714L),           // 亮黄绿 · 司机怎么算钱
        ModuleEntry("司机运费结算", Routes.FREIGHT_SETTLEMENT, Icons.Default.Payments, color = 0xFFFF8A65L),            // 珊瑚橙 · 运费结算
        ModuleEntry("挂账单位", Routes.ARREARS_UNITS, Icons.Default.Business, color = ArrearsTangerine),                 // 橙红 · 挂账警示（= 原来的色，家族里就是这一档）
        // 报表中心直达营业额报表界面（顶部 4 页签：营业/商品/司机/异常，可切换）
        ModuleEntry(
            label = "报表中心",
            route = Routes.REPORT_HOME,
            icon = Icons.Default.BarChart,
            color = ReportIndigo,  // 靛紫 · 报表（= 原来的色）
        ),
        ModuleEntry("消息中心", Routes.MESSAGES, Icons.Default.Notifications, color = MessageRed),
        // ⚠️ AI 助手**不在这里**：它的入口是底部导航正中间那个凸起的圆钮（见 RoleHomeScreen）。
        // 放两处会让人以为是两个功能；它现在是"随时按一下"的入口，不该混在"进哪个模块"的网格里。
        // 例外见 shipperEntries：货主端只有 3 个 Tab，圆钮落不到正中，那边才改成网格图标。
    )

    /**
     * 「账本管理」入口页（`LedgerHomeScreen`）里的 **6 格**（用户 2026-09-20 第二轮定稿）。
     *
     * 原话：「首先，我们将**司机的账和司机结算这 2 个东西合并成一个**；然后订单账本，
     * 再加上货主账本以及批发商账，还有客户收款以及开销管理，**合并成一个形式，就叫做账本管理**，
     * 这个账本管理**类似于报表中心的形式**；然后车辆台账属于车辆管理，车辆管理直接放在桌面上」。
     *
     * 与上一版（工作台那张 8 格卡片）的差别，一条一条对着看：
     * · **司机结算不再单独占一格** —— 入口页里没有它（用户点名「合并成一个」）；而账本页里
     *   **也不再挂入口**（2026-09-20 第四轮：「那个结算，这个也直接去掉」）—— 它从工作台
     *   那一格 `Routes.FREIGHT_SETTLEMENT` 进。
     * · **开销管理并进来**（原来它在卡片里是第 7 格，现在在这里）。
     * · **车辆台账搬去工作台**，改叫「车辆管理」（用户：「车辆台账就是车辆管理嘛」）。
     *
     * 4 类账 = **同一页的四个档位**（`Routes.dispatcherLedger(tab)`）——
     * ⛔ 别给它们各建一个页面：同一套数据四份实现，改一处漏三处。
     * ⛔ 也别在那一页里再加一条档位导航：用户 2026-09-20 明确否掉了（「最上面的 4 个去掉，
     *   那是老的导航栏」）—— 格子点进去是哪一类，那一页就是哪一类。
     */
    val ledgerHomeEntries: List<ModuleEntry> = listOf(
        // ---- 4 类账（同一页的 4 个档位）----
        ModuleEntry("订单账", Routes.dispatcherLedger(0), Icons.Default.AccountBalanceWallet, color = MoneyOrange),     // 橙 · 账本本体
        ModuleEntry("司机账", Routes.dispatcherLedger(1), Icons.Default.LocalShipping, color = 0xFF2E7D32L),           // 深绿 · 司机该拿多少（结算走工作台那一格）
        ModuleEntry("货主账", Routes.dispatcherLedger(2), Icons.Default.PeopleAlt, color = 0xFF00695CL),               // 深青 · 货主欠多少
        ModuleEntry("批发商账", Routes.dispatcherLedger(3), Icons.Default.Storefront, color = 0xFFB8860BL),             // 暗金 · 批发账户
        // ---- 2 个工具（各自有页面）----
        ModuleEntry("客户收款", Routes.DISPATCH_RECEIPTS, Icons.Default.Payments, color = 0xFF512DA8L),                 // 深紫
        // 「收支」（2026-09-22 用户要求）：**收入按来源、支出按去路**各一路一行。
        // ⚠️ 它顶掉的是原来那一格「开销管理」—— 这不是"删了一个模块"，是用户点名要的**整合**：
        //    「我记得好像有个开销管理吧，干脆把我们两个**整合在一起**」。
        //    开销管理**照旧进得去**（`Routes.DISPATCH_EXPENSES` 还注册着、开销分类管理也在），
        //    入口挪到了「收支 → 支出」那张卡的底部 —— 谁要把它加回这一页，先看这条注释。
        //    颜色沿用它的蓝（0xFF1565C0）：账本管理里"支出"这一块用户认的就是这个色。
        ModuleEntry("收支", Routes.DISPATCH_CASH, Icons.Default.SwapHoriz, color = 0xFF1565C0L),                     // 蓝
        // 「供应商 / 应付款」（2026-09-22 用户要求）：支出那一块的另一半 ——
        // 收支页是**日记账**（一笔一笔的流水），这一格是**往来账**（欠谁多少、分几次付清）。
        // ⚠️ 两个入口都通（这里一格 + 收支页支出卡底部一条），因为用户说的就是
        //    "支出主要是给某个供应商付尾款"——他既可能从"账本管理"直接找，也可能从"支出"里找。
        // 图标用 Factory（厂商/供应商就是它）——⛔ 别用 Storefront：那一格「批发商账」已经在用，
        //    判据 `_check_ledger_dashboard.py` 会当场报红（"6 个图标互不相同"实测 7 种）。
        // 颜色：**深玫红 0xFFAD1457**。与这一页已有的 5 个色最近距离 125（判据要求 ≥60）——
        //    原来试的深靛蓝 0xFF283593 与「客户收款」的紫只差 47，肉眼分不出（当场报红）。
        ModuleEntry("供应商/应付", Routes.DISPATCH_SUPPLIERS, Icons.Default.Factory, color = 0xFFAD1457L),          // 深玫红
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
        // 退货申请（2026-09-21）：货主在「我的订单」里对**已送达**的单提出申请，进展在这一页看
        // （待派单员处理 / 已办理 / 已驳回，能撤回）。⛔ 货主只能申请，真正退货在派单端。
        // ⚠️ 位置是**唯一可选的那一格**：本文件的两条单测钉着「消息中心」必须在第 4 格
        //    （`shipperEntries[4]`）、「AI 助手」必须在最后一格 —— 所以插在消息中心与 AI 之间。
        ModuleEntry("退货申请", Routes.SHIPPER_RETURN_REQUESTS, Icons.Default.AssignmentReturn, color = 0xFFB3492FL),
        // 单位换算（2026-09-24）：**货主自己也能设**（用户原话：「我们的**货主**和派单员，
        // 他可以自动的设置单位，比如说一车等于 8 方」）—— 派单员那一侧还有第二个入口
        // （商品编辑 →「请选择单位」页里的「添加单位换算」按钮），这里这一格是两端都有的。
        // ⚠️ 必须插在「退货申请」与「AI 助手」之间：本文件的两条单测钉着
        //    `shipperEntries[4]` 是消息中心、AI 必须是最后一格。
        ModuleEntry("单位换算", Routes.UNIT_CONVERSIONS, Icons.Default.SwapHoriz, color = UnitConvRose),
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

    /** 这个角色能不能看见这一格：**问能力表，不问角色**（R3-02-A）。 */
    private fun canSee(role: Role, entry: ModuleEntry): Boolean {
        val cap = ENTRY_CAPABILITY[entry.route]
            ?: return ENTRY_NO_CAPABILITY.containsKey(entry.route)
        return Capabilities.can(role.key, cap)
    }

    /** 工作台网格：**按能力筛**（不再是 `when (role) -> 写死的那张表`）。 */
    fun entriesFor(role: Role): List<ModuleEntry> = when (role) {
        Role.DISPATCHER -> dispatcherEntries
        Role.SHIPPER -> shipperEntries
        Role.DRIVER -> driverEntries
    }.filter { canSee(role, it) }

    /**
     * 入口 → 它要的**能力**（R3-02：界面不再自己判断角色）。
     *
     * ⛔ 键是 `Routes.x` 的**原文**（含带参数的 `dispatcherLedger(0)`），值与能力表里的键逐字相同。
     * ⛔ 这张表**不是**第二份权限真相：能力键由后端生成（`core/Capabilities.kt`，带 source hash），
     *    这里只声明「这一格对应哪件事」——那是我方界面的事实，不是后端的授权事实。
     * 判据 `_tools/qa/_check_capability_unification.py` 核三件事：每个入口都有着落、没有多余键、
     * 键必须是生成物里真实存在的能力。
     *
     * ⚠️ 位置放在 `entriesFor` **之后**不是随手放的：`_check_ai_guardrails.py` 按
     *    `block_between("val driverEntries", "fun entriesFor(")` 取「司机端那一段」并断言里面
     *    **没有** `Routes.AI_CHAT`；这两张表里有 AI 那一格，塞在 driverEntries 与 entriesFor 之间
     *    会被它读成「司机端工作台多了个 AI 入口」（判据是对的，是位置放错了）。
     */
    val ENTRY_CAPABILITY: Map<String, String> = mapOf(
        // ---- 派单端工作台（派单员在 BYPASS_ROLES 里，所以这些格一律可见；写出来是为了让
        //      「这一格是什么事」与「谁能做这件事」对上，将来出现非绕过角色时它才真的会筛）----
        Routes.DISPATCH_ORDER_CREATE to "order:create",
        Routes.DISPATCH_ORDER_TEMPLATES to "order:edit",
        Routes.ADDRESSES to "address:manage",
        Routes.DISPATCH_ORDERS to "order:read_all",
        Routes.DISPATCH_RETURN_REQUESTS to "order:return",
        Routes.ACCOUNTS to "user:manage",
        Routes.DISPATCH_DRIVERS to "user:manage",
        Routes.SHIPPERS_MANAGE to "user:manage",
        Routes.MEMBERS to "user:manage",
        Routes.PRODUCTS to "product:manage",
        Routes.INVENTORY to "product:manage",
        Routes.UNIT_CONVERSIONS to "unit_conversion:manage",
        Routes.LEDGER_HOME to "ledger:edit",
        Routes.DISPATCH_VEHICLES to "vehicle:manage",
        Routes.FREIGHT_TEMPLATES to "order:dispatch",
        Routes.DRIVER_BILLING_RULES to "order:dispatch",
        Routes.FREIGHT_SETTLEMENT to "ledger:edit",
        Routes.ARREARS_UNITS to "ledger:edit",
        Routes.REPORT_HOME to "stats:read",
        Routes.MESSAGES to "notification:read",
        // ---- 账本管理入口页那 7 格 ----
        Routes.dispatcherLedger(0) to "ledger:read_all",
        Routes.dispatcherLedger(1) to "ledger:read_all",
        Routes.dispatcherLedger(2) to "ledger:read_all",
        Routes.dispatcherLedger(3) to "ledger:read_all",
        Routes.DISPATCH_RECEIPTS to "ledger:edit",
        Routes.DISPATCH_CASH to "ledger:edit",
        Routes.DISPATCH_SUPPLIERS to "ledger:edit",
        // ---- 货主端（这里才是真的在筛：货主没有跳过能力表这回事）----
        Routes.SHIPPER_ORDERS to "order:read_own",
        Routes.ORDER_CREATE to "order:create",
        Routes.SHIPPER_LEDGER to "ledger:read_own",
        Routes.SHIPPER_RETURN_REQUESTS to "order:return_request",
        // ---- 司机端 ----
        Routes.DRIVER_ORDERS to "order:read_assigned",
    )

    /**
     * 没有能力的入口 → **为什么**。⛔ 不许图省事往这里塞（每一条都是一次例外）。
     */
    val ENTRY_NO_CAPABILITY: Map<String, String> = mapOf(
        // AI 助手本身不是某个业务动作：它里面**能做什么**由 `AiWrites` 按同一张能力表裁剪，
        // 入口这一格只是「换一种用法」。给它编一个能力只会凭空多出一条谁也执行不到的名字。
        Routes.AI_CHAT to "入口本身不是业务动作（里面的动作由 AiWrites 按能力裁剪）",
        // 司机的「我的账本」：`GET /freight-settlement` 是 `get_current_user` + 体内按人过滤，
        // **没有权限点也没有角色门** —— 没有可问的名字。要给司机一个能力名，得先把那个端点
        // 接成权限点（那是改后端授权，属于体内门槛棘轮那一条线）。
        Routes.DRIVER_FREIGHT to "端点按登录人过滤，没有可问的能力名（见注释）",
    )

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