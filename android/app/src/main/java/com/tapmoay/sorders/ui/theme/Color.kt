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

/**
 * 图表配色（扇形图那些块、将来的构成图）。
 *
 * ⚠️ 这张表的存在理由不是"好看"，是**相邻的块必须一眼分得开**：扇形图里两块颜色接近，
 *    图例就成了唯一的判据，而"看图"这件事就白做了。所以选色的硬判据是
 *    **两两 RGB 欧氏距离 ≥ 60**（与工作台图标同一条判据，单测 `ChartPaletteTest` 钉着）。
 * ⚠️ 色相顺序也扫过一遍：第一块是账本橙（钱）、接着蓝/绿/紫/红/湖蓝/棕，
 *    同色系（橙-金、绿-青、青-灰青）**刻意没有排在一起**。
 */
val ChartPalette = listOf(
    MoneyOrange,        // #FF9500 账本橙
    0xFF1E6FFFL,        // #1E6FFF 蓝
    MgrGreen,           // #00B578 绿
    ProductPurple,      // #8455E6 紫
    MessageRed,         // #FF4D4F 红
    ShipperTeal,        // #00A2C7 湖蓝
    0xFF8D6E63L,        // #8D6E63 棕（第七块之后的兜底色）
)

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