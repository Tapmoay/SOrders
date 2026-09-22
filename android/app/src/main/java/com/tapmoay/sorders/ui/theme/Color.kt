package com.tapmoay.sorders.ui.theme

import androidx.compose.ui.graphics.Color

// 品牌种子色：明快物流蓝（参考日式街边招牌：饱和、明亮、高对比、不刺眼）
val SeedBlue = Color(0xFF1E6FFF)
val SeedBlueDark = Color(0xFF90CAF9)

// ===== 模块语义色（一色一功能：老人可快速定位；均为亮色高对比）=====
val NavBlue = 0xFF1E6FFFL          // 派单作业 / 主操作：亮蓝
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
val InfoBlue = 0xFF1E6FFFL         // 信息

// Light
val Primary = Color(0xFF1E6FFF)
val OnPrimary = Color(0xFFFFFFFF)
val PrimaryContainer = Color(0xFFD9E8FF)
val OnPrimaryContainer = Color(0xFF0A3168)
val SecondaryContainer = Color(0xFFD2F2E3)
val OnSecondaryContainer = Color(0xFF0B3D2E)
val Tertiary = Color(0xFFF57F17)
val ErrorLight = Color(0xFFFF4D4F)
val ErrorContainerLight = Color(0xFFFFECEC)
val BackgroundLight = Color(0xFFF2F3F7)
val OnBackgroundLight = Color(0xFF17181C)
val SurfaceLight = Color(0xFFFFFFFF)
val OnSurfaceLight = Color(0xFF17181C)
val SurfaceVariantLight = Color(0xFFECEFF5)
val OnSurfaceVariantLight = Color(0xFF3B404A)
val SurfaceContainerLow = Color(0xFFEDEFF4)
val SurfaceContainer = Color(0xFFE6E9F0)
val SurfaceContainerHigh = Color(0xFFDDE1EA)

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
 * 亮色下能分层是因为「白卡 + 灰底」（#FFFFFF on #F2F3F7）；
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