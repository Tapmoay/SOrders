package com.tapmoay.sorders.ui.theme

import androidx.compose.ui.graphics.Color

// 品牌种子色：明快物流蓝（参考日式街边招牌：饱和、明亮、高对比、不刺眼）
val SeedBlue = Color(0xFF1E6FFF)
val SeedBlueDark = Color(0xFF90CAF9)

// ===== 模块语义色（一色一功能：老人可快速定位；均为亮色高对比）=====
//
// ⚠️ 2026-10-09 CHG-0091：这里的**主操作色**由「亮蓝」换成「深绿」。
//    用户原话（ref m01501 / m01927）：「整体的颜色……**从蓝色变成绿色**，像微信那样子」
//    「颜色的话就选**深绿色**……因为太亮了不好，因为我们的**核心要求是低饱和**」。
//    换的是**身份色**（主操作 / 派单作业 / 信息），不是把每一处蓝都涂绿：
//    报表里那些"这一段卖出去的货"之类跟着走，是因为它们**本来就是主操作色**。
val ThemeGreen = 0xFF00A870L       // 主操作 / 派单作业 / 信息：低饱和深绿（原 NavBlue #1E6FFF）
// ⚠️ 旧名保留成**同一个值的别名**：全仓 16 处引用（`ui/nav/Modules.kt` 的底部 Tab、
//    `ui/dispatcher/` 那一批页面里的编辑动作等）不改调用点，语义也没变——它指的一直是"主操作色"。
//    将来若真要拆开（例如"编辑"该有自己的色），再一处一处换掉，别在这一轮顺手改行为。
//
//    ⛔ 这段注释里**不许出现斜杠紧跟星号**（那种写法会让 `_tools/qa` 的 `strip_comments()`
//    误以为块注释开始了，一路吃到下一个块注释结尾 —— 实测把本文件第 18~110 行整片吃掉，
//    `_check_ledger_cash.py` 当场找不到 92/93 行的收支色）。写目录名时**不要带通配符**。
val NavBlue = ThemeGreen
val MgrGreen = 0xFF00B578L         // 司机管理 / 已完成：青绿
val ProgressYellow = 0xFFFFB300L   // 进行中：黄
val ShipperTeal = 0xFF00A2C7L      // 货主管理：湖蓝
val MemberGold = 0xFFF5A623L       // 批发商（高级货主）：财富金
val ProductPurple = 0xFF8455E6L    // 商品管理：紫
val InventoryTeal = 0xFF00A8A8L    // 库存管理：深青
val MoneyOrange = 0xFFFF9500L      // 账本 / 收款：金橙
val ArrearsTangerine = 0xFFFF6B2CL // 挂账单位（欠款警示）：橙红
val ReportIndigo = 0xFF6950F5L     // 报表中心：靛蓝紫
val MessageRed = 0xFFFF4D4FL       // 消息 / 通知：红

// ===== 账户管理的棕（2026-10-05，CHG-0023 从工作台宫格提上来）=====
//
// 「账户管理」这一格在工作台宫格里一直是棕 `#8D6E63`，但它**一直是个裸字面量**（`ui/nav/Modules.kt`
// 那一行）—— 于是这一页的其余地方只能去借隔壁模块的色：分类胶囊、卡头圈底图标、右下角 FAB
// 原来清一色是 `ShipperTeal`（规范 §2 里那是「地址与联系人」的湖蓝）。规范 §4.3 那句
// 「⛔ **不许用别的功能的颜色**」说的就是这件事。
//
// ⚠️ `ui/nav/Modules.kt` 那一行**故意留着裸字面量**，不换成这个 token：判据
// `_tools/qa/_check_ledger_dashboard.py` 直接按 `color = 0xFF……L` 扫宫格色来算「同屏不许撞色」，
// 换成 token 那一格就扫不到了，`BAND_EXEMPT` 里 `#8D6E63` 的豁免也会跟着落空。
// 两处同值由 `_tools/qa/_check_roster_cards.py` 当场对账 —— 只改一处一定判红。
//
// [OnAccountBrown] 是**站在这块棕上的字**：纯白对它 ≈ 4.6:1（过 AA 的 4.5:1），深字只有
// ≈ 4.5:1 而且显脏，所以 FAB 用白字 —— 与 [OnDriverLime] / [OnArrearsTangerine] 是同一件事。
val AccountBrown = 0xFF8D6E63L     // 账户管理：棕（统一建号：账号 + 密码 + 角色）
val OnAccountBrown = 0xFFFFFFFFL   // 棕底上的字（右下角 FAB）

// ===== 车辆台账（司机管理）的黄绿（2026-10-04，CHG-0016 从 VehicleManageScreen.kt 提上来）=====
//
// 规范 §2 的模块色表里「司机管理」那一格一直是黄绿 #CDDC39，但**常量列写的是「-」** ——
// 于是要它的地方只能手写 Color(0xFFCDDC39)：车辆管理页 2 处、司机管理页 2 处，加上
// 黄绿底上那行字用的深橄榄 2 处，同一个概念在三个文件里手写了两遍以上。
// 「一个概念一个色」要成立，前提是这个色**有个名字** —— 否则改色时总会漏掉一处
// （CHG-0014 的起点 / 终点是同一个问题：那次也是把值从使用处提上来）。
//
// [OnDriverLime] 是**站在这块黄绿上的字**：黄绿很亮，白字在上面只有 1.4:1（读不出来），
// 所以 FAB 的文字与选中的车型用的都是这个深橄榄（对黄绿 ≈ 8:1）。
val DriverLime = 0xFFCDDC39L       // 司机管理 / 车辆台账：黄绿
val OnDriverLime = 0xFF3A3F00L     // 黄绿底上的字（FAB 文字 / 选中的车型）

// ===== 挂账单位橙红底上那行字（2026-10-04，CHG-0020）=====
//
// 挂账单位页的保存键与分组图标用的是本模块的语义色 [ArrearsTangerine]（#FF6B2C）。
// 白字压在这块橙红上只有 **2.84:1** —— 连 AA 的 4.5:1 都不到，小字根本读不出来
// （跟 [OnDriverLime] 是同一个病：**亮底就得配深字**，深棕约 6.2:1）。
val OnArrearsTangerine = 0xFF2B1200L // 橙红底上的字（保存键）

// ===== 线路语义色：起点 / 终点（2026-10-03，CHG-0014 从 ui/common/RouteRail.kt 提上来）=====
//
// 「从 A 到 B」那一竖条（ui/common/RouteRail.kt）是全库唯一一处，它用的两个色原先**只在那一个
// 文件里私有**，于是同一张卡上的表单分组只能各自再挑一个近似色：卡片上的起点圆点是 #00BCD4，
// 抽屉里「起点」那一组却是 InventoryTeal #00A8A8 —— 同一个概念两个色，用户 2026-09-20 点名过
// 「一个概念一个色」。现在提成公有 token，卡片与表单引用同一份，改一处两边一起变。
//
// ⚠️ 这两个值**接着已有色用、不新造色**（与 CashIn = MgrGreen 同一条路子）：
//   · #00BCD4 与「库存管理」模块格同值；#F5A623 与 MemberGold（批发商）同值。
//     模块语义色那条「14 色互异」管的是**模块宫格**里的那 14 格；起点圆点 / 终点定位针
//     与宫格格子不会同屏出现，所以复用值不冲突。
// ⛔ 别把这两个 token 借去别处（「进行中」「提醒」之类）：它们只表示**一条线路的起点 / 终点**。
val OriginTeal = 0xFF00BCD4L       // 一条线路的「起点」：卡片圆点 + 起点分组
val DestOrange = 0xFFF5A623L       // 一条线路的「终点」：卡片定位针 + 终点分组

// ===== 收支（账本管理「收支」页，2026-09-22）=====
//
// 一组"钱进来 / 钱出去"的语义色，两个值都**接着已有的功能色用**，不新造色：
//   · 收入 = `MgrGreen`（青绿）：本项目的青绿本来就表示"进账 / 已完成"这一档；
//   · 支出 = `#1565C0`：它就是原「开销管理」那一格的蓝 —— 账本管理入口页把「开销管理」
//     并进「收支」时，支出这一组**继续用它**，用户认得的那个色不换。
//
// 两者 RGB 欧氏距离 ≈110（≥60），同屏并排不会撞色。
val CashIn = MgrGreen              // 收入（进账）
val CashOut = 0xFF1565C0L          // 支出（出账）= 原「开销管理」蓝

/**
 * 商品卡上「改价」快捷入口的颜色：**低饱和绿**。
 *
 * 用户 2026-09-19：「你商品页面那个改价的那个图标颜色呀，不要用紫色，用绿色，
 * 是那种**低饱和的绿色**」。
 *
 * 为什么它不复用模块色（原来用的是商品管理的紫 `ProductPurple`）：
 * 商品管理页上现在有**两处**紫 —— 底部导航栏的「商品新增/分类管理」和卡片上的「改价」，
 * 同屏两处紫会让人以为它们是同一类动作。改价是一个**具体动作**，不是"这个模块"，
 * 所以它单独有一个颜色。
 *
 * ⚠️ 为什么强调**低饱和**：已有的绿都是高饱和的功能色 ——
 * `MgrGreen #00B578`（司机管理/已完成）与 `Success #00A56E`（成功）饱和度都是 100%，
 * 那是"状态"的语言。这个按钮不是状态，压低到 ≈27% 才不会跟它们混成一家。
 * 与上面两个绿的 RGB 欧氏距离 92 / 94，都过了本项目"同屏不许撞色"的 ≥60 判据。
 */
val QuickPriceGreen = 0xFF5B9E74L  // 商品卡「改价」：低饱和绿（S≈27%）

/**
 * 单位换算（一车 = 8 方，2026-09-24 用户要求）：**洋红紫**。
 *
 * 为什么是这个色：单位换算与「商品管理」是同一族的（都关于"这件货怎么计量"），
 * 所以取紫家族的另一档 —— 与 `ProductPurple #8455E6` 的 RGB 欧氏距离 **75**、
 * 与 `ReportIndigo #6950F5` 距离 **95**、与 AI 的 `AiPurple #9B72CB` 距离 **80**，
 * 都过了本项目"同屏不许撞色"的 ≥60 判据（`ModulesEntryTest` 会当场算）。
 */
val UnitConvRose = 0xFF9C27B0L     // 单位换算：洋红紫
// ===== AI 助手：Google AI 智能体（Gemini）配色 =====
//
// 用户 2026-09-15 的要求："颜色改成谷歌的 AI 智能体的配色方法，它里面的颜色也要按这个方法配色"。
// 所以 AI 不用自己的语义色了，直接沿用 Google 的品牌做法：
//
//   · 三段品牌渐变：蓝 #4285F4 → 紫 #9B72CB → 粉 #D96570
//     （来源：Gemini 网页端问候语那段"渐显"文本，逆向出来的 10 段渐变用的就是这三个
//      品牌色 + 白色段做动画；见 blog.sebastiano.dev 的 Compose 复刻分析）
//   · 图标形态 = **渐变圆角块 + 白色四角星**（Google 的 AI 图标就长这样）
//   · 单色强调（按钮/链接/选中态）取渐变起点那个 Google 蓝 #4285F4
//
// 好处除了"看起来像 AI"，还顺手解决了原来的问题：渐变和 App 里任何一个**单色**语义色
// 都不可能撞（货主工作台里并排的方块里不会再出现两块一样的蓝）。
val AiBlue = 0xFF4285F4L           // Google 蓝（渐变起点；强调色）
val AiPurple = 0xFF9B72CBL         // Google 紫（渐变中段）
val AiPink = 0xFFD96570L           // Google 粉（渐变终点）

val SuccessGreen = 0xFF00B578L     // 成功 / 正常
val WarningAmber = 0xFFFF9F1CL     // 提醒 / 待处理
val DangerRed = 0xFFFF5252L        // 危险 / 异常
val InfoBlue = ThemeGreen          // 信息（原 #1E6FFF：跟着主操作色一起换）

// ===== 商品行（2026-10-09 CHG-0091：绿主题）=====
//
// 用户口径（ref m01501 / m01927）：「底下有个**颜色比较深的**……让这个信息比较重要，
// 能一眼看得出来」「商品名称**不留紫色**」「**低饱和**」。
//
// ⚠️ 2026-10-09 当天还立过一条"页面顶上一段深绿→白渐变"，同一天被用户撤掉
//    （ref m02715：「那个背景的渐变，就去掉吧……就是白色的默认色」）⇒ 那个起色 token
//    （`PageGradientGreen = 0xFF0B6644L`）**已经删掉**，页面背景不留绿。
//
// ⛔ 这一组**只给商品行用**，不要借去别的语义位置。
// ⚠️ 必须跟上面那批一样用 `0x…L` 这种字面量（不是 `Color(0x…)`）：
//    本仓库的语义色 token 统一是"裸 ARGB 值"（`Long`），用色的地方自己写 `Color(token)`。
//    写成 `Color(0x…)` 会让这一组变成**另一种类型**，同一条 `Row` 里混用就编译不过
//    （`TintedIcon(…, Color(ThemeGreen))` 与 `TintedIcon(…, ProductPurple)` 才是同一种）。
// 深一档：数量块的底。压白字 ≈ 5.2:1（对 #00A870 更差，只有 2.9:1）⇒ **只许大色块 / 大字号**，
// 小字不要往这两种绿上放（要用就再压深一档，别直接刷白字上去）。
val ThemeGreenDeep = 0xFF0E7A50L
val ProductRowTint = 0xFFE6F7EEL      // 商品行：极浅绿底（比白卡浅一点点的"绿系白"）
val OnProductRowTint = 0xFF10331FL    // 浅绿底上的品名（近黑的墨绿，对比 ≈ 13:1）

// AI 回答正文里的「重要信息」用色（台账 L-24 / CHG-0060）。
// ⛔ 只借上面这四个语义色，**一个新色都不造**。颜色由界面按类别确定性地地上
// 见 ai/AiAnswerTone.kt。模型自己在回答里写不出颜色，这也正是"同类信息必须统一"的保证。
// 四档从重到轻：
// 危险 → 钱 → 提醒 → 正常；一次回答最多出现两种（规则写在那边的类注释里）。
val AiToneDanger = DangerRed       // 危险 / 异常（最重）
val AiToneMoney = MoneyOrange      // 账本信息（钱）
val AiToneWarn = WarningAmber      // 提醒 / 待处理
val AiToneOk = SuccessGreen        // 成功 / 正常

// Light
//
// ⚠️ 2026-10-09 CHG-0091：这里原来是一整套**蓝**（Primary #1E6FFF / PrimaryContainer #D9E8FF /
//    OnPrimaryContainer #0A3168）。用户要求"整体基调从蓝变绿"后换成绿家族，但**只换色相、不动结构**：
//    Primary 仍是"主操作按钮底"、PrimaryContainer 仍是"浅底 + 深字"那一对（工作台顶部那条读的就是它）。
//    对比度：白字压在 #00A870 上 ≈ 2.9:1（不到 AA 的 4.5）⇒ 它只当**大色块 / 大字号**的底
//    （主按钮、整条顶栏），小字用 [OnPrimaryContainer] 那种深绿（对浅绿底 ≈ 8:1）。
val Primary = Color(0xFF00A870)
val OnPrimary = Color(0xFFFFFFFF)
val PrimaryContainer = Color(0xFFD6F2E4)
val OnPrimaryContainer = Color(0xFF0B4A32)
val SecondaryContainer = Color(0xFFD2F2E3)
val OnSecondaryContainer = Color(0xFF0B3D2E)
val Tertiary = Color(0xFFF57F17)
val ErrorLight = Color(0xFFFF4D4F)
val ErrorContainerLight = Color(0xFFFFECEC)
// ── 暖白家族（台账 L-19 · CHG-0063，2026-10-06）──────────────────────────────
// 用户口径（ref m00481）：「我们的整体背景基调，颜色太过于灰蓝了不好看。我更偏向于
// 稍微偏白一点啊，整体的基调。」随后选定方向：**偏白**（亮、且不偏蓝），不是灰蓝。
//
// ⚠️ 2026-10-09 CHG-0091 改过一次（绿主题）：用户要「背景加一个由深绿往下到白色……
//    大概到 1/3 的位置就全白了」。**页面底那一层因此改成近白的中性色**
//    （原来 #F8F7F4 的暖白在纯白渐变下会露出一条暖色带），其余三层同步提亮——
//    ⛔ **分层与"不偏蓝"这两条口径没变**：R ≥ B、白卡仍是最亮那层、四层仍严格递减。
//    为什么是"中性"而不是原来那种"暖"：页面底现在**大面积被渐变盖住**，
//    剩下露出来的地方大半是"白卡与白卡之间的缝"，那里要的是**不抢色**（中性），
//    而"偏暖"这个诉求由卡片自己（白卡 + 阴影）与顶栏那条绿来承担。
// 这四层是**页面底与它周围那几层**（顶栏读的就是 BackgroundLight），一起往白走；
// 越往下越深一档，白卡（SurfaceLight）仍是最亮的那一层，分层不许塌。
// ⛔ 底部抽屉与侧面抽屉**不在此列**（用户 ref m09782：「底部抽屉啊，侧面抽屉啊，
//    那些都不要搞啊别搞反了嘞」）：它们读的是 SheetSurface，那个值一个字都不许动。
// ⛔ 描边（OutlineLight / OutlineVariantLight）与暗色那一套也都不在此列。
// 判据：_tools/qa/_check_warm_surface_palette.py（R >= B、分层递减、抽屉层没动都在里面）。
val BackgroundLight = Color(0xFFFBFBFA)
val OnBackgroundLight = Color(0xFF17181C)
val SurfaceLight = Color(0xFFFFFFFF)
val OnSurfaceLight = Color(0xFF17181C)
val SurfaceVariantLight = Color(0xFFF3F2EF)
val OnSurfaceVariantLight = Color(0xFF3B404A)
val SurfaceContainerLow = Color(0xFFEDEFF4)  // 死值：亮色下被 Theme.kt 换成 SheetSurface（抽屉的面）
val SurfaceContainer = Color(0xFFEFEEEB)
val SurfaceContainerHigh = Color(0xFFE9E7E3)

/**
 * **底部抽屉的面** —— 全 App 所有 `ModalBottomSheet` 的底色（2026-09-22）。
 *
 * ## 为什么要单独给它一个 token
 * 用户的原话是：「为什么**每次**底部抽屉弹出来那个颜色都是**灰蓝灰蓝**的？不要啊。
 * 改成底部灰（色）没关系，**卡片一定要是白色的** —— 这样子就产生一个对比，让人知道。」
 *
 * ⚠️ 它原来**根本没有被谁指定过**：M3 的 `ModalBottomSheet` 容器默认色是
 * `BottomSheetDefaults.ContainerColor` → `SheetBottomTokens.DockedContainerColor`
 * → `ColorSchemeKeyTokens.SurfaceContainerLow`（反编译 material3 **1.3.2** 的 `classes.jar`
 * 的常量池看到的，`javap -c` 打出来的就是这条链）。
 * 也就是说：**`Theme.kt` 里那一行 `surfaceContainerLow = SheetSurface` 就是全 App
 * 19 个底部抽屉的底色**，而它当时的值 `#EDEFF4` 的 B 通道比 R 高 7 ——
 * 冷暖上一眼就能看出偏蓝，正是用户说的"灰蓝"。
 *
 * ## 为什么是"中性灰"而不是白
 * 抽屉里的东西是**白色卡片**（`SectionCard` / 表单分组）。抽屉自己再刷成白的，
 * 白卡就糊在白的面上、一点都不"跳"，用户要的"对比，让人知道"就没了。
 * 所以这里取**纯中性**（R=G=B，冷暖不偏）+ **比白低一档**：卡是纯白、面是这层灰，两层才分得开。
 * ⛔ 别再往这个值里加蓝（哪怕 2~3 个点）：那正是这一轮被用户点名的那件事，
 * 判据 `_tools/qa/_check_sheet_form_pages.py` 会当场报红（它直接比 B 与 R）。
 *
 * ## 为什么暗色不动
 * 暗色下抽屉读的是 `SurfaceContainerLowDark = #1A1B20`，本来就是"深灰"，
 * 没有用户说的那个"灰蓝"观感；而且亮暗两套的**分层方向是相反的**
 * （亮＝白卡浮在灰上，暗＝亮一点的灰浮在黑上），照搬一个值会把暗色的分层弄没。
 */
val SheetSurface = Color(0xFFF0F0F0)

val OutlineLight = Color(0xFF7A7F8C)
val OutlineVariantLight = Color(0xFFCFD4E0)
val Success = Color(0xFF00A56E)          // 成功绿（亮）

// Dark
val PrimaryDark = Color(0xFFAAC7FF)
val OnPrimaryDark = Color(0xFF002F65)
val PrimaryContainerDark = Color(0xFF0F4690)
val OnPrimaryContainerDark = Color(0xFFD6E3FF)
val SecondaryContainerDark = Color(0xFF404658)
val OnSecondaryContainerDark = Color(0xFFDCE3F8)
val TertiaryDark = Color(0xFF4DD9E0)
val ErrorDark = Color(0xFFFFB4AB)
val ErrorContainerDark = Color(0xFF93000A)
val BackgroundDark = Color(0xFF0E1014)
val OnBackgroundDark = Color(0xFFE2E2E9)
/**
 * 暗色下的「卡片面」。
 *
 * ⚠️ 这里**必须比 [BackgroundDark] 亮一档**。原来两者都是 `#111318`，
 * 而全 App 的卡片（`SectionCard`）用的就是 `surface` —— 于是暗色下
 * **卡片和背景是同一个颜色**，完全没有分层：卡片看不出边界、分组看不出分界，
 * 用户 2026-09-18 的原话是「有些卡片都不是很明显，信息丢失，感觉不是很好」。
 *
 * 亮色下能分层是因为「白卡 + 底色」（#FFFFFF on `BackgroundLight`；台账 L-19 起是暖白 #F8F7F4）；
 * 暗色下必须反过来用「亮一点的灰 + 更黑的黑」，这是暗色主题唯一能做分层的方向。
 * 顺带一提：`shadowElevation` 在暗色下基本看不见，所以分层只能靠**色差**，
 * 不能再指望阴影（见 `SectionCard` 里补的那条暗色描边）。
 */
val SurfaceDark = Color(0xFF1B1D23)
val OnSurfaceDark = Color(0xFFE2E2E9)
val SurfaceVariantDark = Color(0xFF44464F)
val OnSurfaceVariantDark = Color(0xFFCCCDD7)
val SurfaceContainerLowDark = Color(0xFF1A1B20)
val SurfaceContainerDark = Color(0xFF1E1F25)
val SurfaceContainerHighDark = Color(0xFF292A31)
val OutlineDark = Color(0xFF8E9099)
val OutlineVariantDark = Color(0xFF44464F)
val SuccessDark = Color(0xFF81C784)

// ===== 「我的」页头部：深墨蓝（用户 2026-09-21 给的参考图的「背景」）=====
//
// 参考图那种「深色顶 + 白色大圆角卡」的观感，取**同一族**的深墨蓝：顶部更深、往下略提亮，
// 下端接我们自己的 NavBlue 家族（不是照抄它的黑灰，也不是我们平时的亮蓝）。
//
// ⚠️ 两个模式**共用同一组值**（头部在暗色下不跟着变浅）—— 但下端必须**比暗色页面底
//    `BackgroundDark #0E1014` 亮**，否则暗色模式下头部和页面糊成一片，
//    与 2026-09-18 那次「卡片和背景同色、信息丢失」是同一类事故。
val ProfileHeaderTop = Color(0xFF131A2B)
val ProfileHeaderBottom = Color(0xFF22304F)