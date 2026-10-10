package com.tapmoay.sorders.ui.theme

import androidx.compose.ui.graphics.Color

// 品牌种子色：明快物流蓝（参考日式街边招牌：饱和、明亮、高对比、不刺眼）
val SeedBlue = Color(0xFF006DFF)
val SeedBlueDark = Color(0xFF67CDFF)

// ===== 模块语义色（一色一功能：老人可快速定位；均为亮色高对比）=====
//
// ⚠️ 2026-10-09 CHG-0091：这里的**主操作色**由「亮蓝」换成「深绿」。
//    用户原话（ref m01501 / m01927）：「整体的颜色……**从蓝色变成绿色**，像微信那样子」
//    「颜色的话就选**深绿色**……因为太亮了不好，因为我们的**核心要求是低饱和**」。
//    换的是**身份色**（主操作 / 派单作业 / 信息），不是把每一处蓝都涂绿：
//    报表里那些"这一段卖出去的货"之类跟着走，是因为它们**本来就是主操作色**。
// ⚠️ 2026-10-09 CHG-0101（台账 L-64）：**整套换成用户画的那套低饱和色**。
//    用户连发三张图（m02471 订单卡 / m02472 工作台宫格 / m02473 整体配色方案），
//    逐字（m02474）：「按照它的配色方案进行一下修改以及我给你的那个照片」，
//    又补一句（m02545）：「这是新任务吼也就是改我途中给你发的那些样式」，
//    中途还专门叮嘱（m02683）：「继续继续，但**我不希望整体太过于灰**啊」。
//    所以本单取色的两条底线是：① 照着参考图走；② 饱和度的地板是 **≥30%**（不能压成灰）。
//    ⛔ 改的是这些 token 的**数值**，名字、别名关系、语义分工一个都没动。
val ThemeGreen = 0xFF006C43         // 主操作 / 派单作业 / 信息：深红棕（用户图一「确认接单」#8B4A4A）
// ⚠️ 旧名保留成**同一个值的别名**：全仓 16 处引用（`ui/nav/Modules.kt` 的底部 Tab、
//    `ui/dispatcher/` 那一批页面里的编辑动作等）不改调用点，语义也没变——它指的一直是"主操作色"。
//    将来若真要拆开（例如"编辑"该有自己的色），再一处一处换掉，别在这一轮顺手改行为。
//
//    ⛔ 这段注释里**不许出现斜杠紧跟星号**（那种写法会让 `_tools/qa` 的 `strip_comments()`
//    误以为块注释开始了，一路吃到下一个块注释结尾 —— 实测把本文件第 18~110 行整片吃掉，
//    `_check_ledger_cash.py` 当场找不到 92/93 行的收支色）。写目录名时**不要带通配符**。
val NavBlue = ThemeGreen
val MgrGreen = 0xFF00AC6E          // 下单 / 代理下单：草绿（CHG-0102 起按 H 档算：L*61.8 C*41.2 h150.2）
val ProgressYellow = 0xFF91871D    // 进行中 / 订单管理：橄榄金（CHG-0102：L*54.2 C*37.4 h98.3）
val ShipperTeal = 0xFF00A4CE       // 地址与联系人：晴蓝（CHG-0102：L*61.8 C*28.0 h239.8）
val MemberGold = 0xFFC48C1D        // 批发商（高级货主）：金棕（CHG-0102：L*61.8 C*42.9 h78.3）
val ProductPurple = 0xFFA980F1     // 商品管理：薰衣草紫（CHG-0102：L*61.8 C*44.0 h314.0）
val InventoryTeal = 0xFF009481     // 货主管理：松绿（CHG-0102：L*54.2 C*28.0 h179.8）
val MoneyOrange = 0xFFBC7730       // 账本 / 收款：焦糖（CHG-0102：L*54.2 C*44.0 h53.6）
val ArrearsTangerine = 0xFFCE5C2C  // 挂账单位（欠款警示）：陶土红（CHG-0102：L*53.0 C*44.0 h33.6）
val ReportIndigo = 0xFF7B70DE      // 报表中心：蓝紫（CHG-0102：L*53.0 C*44.0 h299.8）
val MessageRed = 0xFFE07B80        // 消息 / 通知：玫瑰红（CHG-0102：L*63.0 C*40.7 h20.4；仍是最跳的一格）

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
// ⚠️ 2026-10-09 CHG-0101：值跟着整套换（用户图二「账户管理」量测 #968C86 的深一档）。
//    仍与 `ui/nav/Modules.kt` 那一行的裸字面量**同值**（判据 `_check_roster_cards.py` 对账）。
val AccountBrown = 0xFFAC7217      // 账户管理：赭石（CHG-0102：L*53.0 C*39.2 h73.6；⛔ 不再是灰棕）
val OnAccountBrown = 0xFFFFFFFFL   // 棕底上的字（右下角 FAB）

// ===== 车辆台账（司机管理）的黄绿（2026-10-04，CHG-0016 从 VehicleManageScreen.kt 提上来）=====
//
// 规范 §2 的模块色表里「司机管理」那一格一直是黄绿 #CDDC39，但**常量列写的是「-」** ——
// 于是要它的地方只能手写 Color(0xFFC0E100)：车辆管理页 2 处、司机管理页 2 处，加上
// 黄绿底上那行字用的深橄榄 2 处，同一个概念在三个文件里手写了两遍以上。
// 「一个概念一个色」要成立，前提是这个色**有个名字** —— 否则改色时总会漏掉一处
// （CHG-0014 的起点 / 终点是同一个问题：那次也是把值从使用处提上来）。
//
// [OnDriverLime] 是**站在这块黄绿上的字**：黄绿很亮，白字在上面只有 1.4:1（读不出来），
// 所以 FAB 的文字与选中的车型用的都是这个深橄榄（对黄绿 ≈ 8:1）。
val DriverLime = 0xFF798502L       // 司机管理 / 车辆台账：橄榄绿（CHG-0102：L*53.0 C*40.5 h118.3）
val OnDriverLime = 0xFF303900L     // 橄榄底上的字（FAB 文字 / 选中的车型）

// ===== 挂账单位橙红底上那行字（2026-10-04，CHG-0020）=====
//
// 挂账单位页的保存键与分组图标用的是本模块的语义色 [ArrearsTangerine]（#FF6B2C）。
// 白字压在这块橙红上只有 **2.84:1** —— 连 AA 的 4.5:1 都不到，小字根本读不出来
// （跟 [OnDriverLime] 是同一个病：**亮底就得配深字**，深棕约 6.2:1）。
// ⚠️ 2026-10-09 CHG-0101：砖红 `ArrearsTangerine` 换成了 #BE5F4A（浅底），白字压它 ≈ 4.0:1
//    仍差一点点，所以字用**暖白** #FFF3EE（≈ 3.9:1 但字号是按钮级大字号，且这是"警示"不是正文）。
val OnArrearsTangerine = 0xFFFFF3EEL // 砖红底上的字（保存键）

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
val OriginTeal = 0xFF49AABAL       // 一条线路的「起点」：雾青（用户图二「车辆管理」#87B7B9 一族）
val DestOrange = 0xFFC48C1D        // 一条线路的「终点」：金棕（与 MemberGold 同值，同 CHG-0014 的做法）

// ===== 收支（账本管理「收支」页，2026-09-22）=====
//
// 一组"钱进来 / 钱出去"的语义色，两个值都**接着已有的功能色用**，不新造色：
//   · 收入 = `MgrGreen`（青绿）：本项目的青绿本来就表示"进账 / 已完成"这一档；
//   · 支出 = `#1565C0`：它就是原「开销管理」那一格的蓝 —— 账本管理入口页把「开销管理」
//     并进「收支」时，支出这一组**继续用它**，用户认得的那个色不换。
//
// 两者 RGB 欧氏距离 ≈110（≥60），同屏并排不会撞色。
val CashIn = MgrGreen              // 收入（进账）
val CashOut = 0xFF62729DL          // 支出（出账）= 原「开销管理」蓝，CHG-0101 换成雾蓝

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
val QuickPriceGreen = 0xFF588F64L  // 商品卡「改价」：低饱和绿（S≈27%；CHG-0101 换成雾绿）

/**
 * 单位换算（一车 = 8 方，2026-09-24 用户要求）：**洋红紫**。
 *
 * 为什么是这个色：单位换算与「商品管理」是同一族的（都关于"这件货怎么计量"），
 * 所以取紫家族的另一档 —— 与 `ProductPurple #8455E6` 的 RGB 欧氏距离 **75**、
 * 与 `ReportIndigo #6950F5` 距离 **95**、与 AI 的 `AiPurple #9B72CB` 距离 **80**，
 * 都过了本项目"同屏不许撞色"的 ≥60 判据（`ModulesEntryTest` 会当场算）。
 */
val UnitConvRose = 0xFF9C6BA3L     // 单位换算：雾紫（CHG-0101 跟着商品紫一起换）
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

// ===== AI 聊天页的强调色：一个像微信的绿（台账 L-66 · CHG-0104，2026-10-10）=====
//
// 用户口径（ref m04856，逐字）：「你别帮我那个 a i 对话框改的颜色改其他颜色了，它的主颜色
// 还是绿色……它就像微信一样。为什么要绿色呢？因为我希望让使用……跟微信一样亲切啊，
// 因为我们微信是大家经常用的」。**绿值由我们定**（用户：「要你的方案进行」）。
//
// ## 为什么要自己一个 token、而不是把 `ThemeGreen` 改回绿
// `ThemeGreen`（= `Primary` / `NavBlue` / `InfoBlue`，现在是 #8B4A4A 红棕）是**全 App 的主操作色**，
// 是用户 2026-10-09 亲手画在图上的。CHG-0101 把它从绿换成红棕之后，AI 页的
// `AiAccent = Color(ThemeGreen)`（ai/AiChatScreen.kt）**跟着变成了红棕** —— 用户要的是
// "AI 这一片是绿的"，不是"整个 App 回到绿"。所以这里给 AI 页**自己的绿**，主操作色一个字不动。
//
// ## 为什么是两个：绿在 sRGB 里做不到"又亮又能压白字"
// 这是本单唯一一个绕不过去的约束，量过（`_tmp/chg0104_green.py`）：
// 绿色的亮度权重是 0.7152（0.2126 / **0.7152** / 0.0722），同一个 L* 下绿色的相对亮度远高于红紫，
// 于是 CHG-0102 定的工作台明度带 **L* ∈ [53, 63]** 与「白字 ≥ 4.5:1」**不可能同时成立**：
//   · h=150°、C*=38 时 L*=53 → 白字 4.05:1 ❌；L*=50 → 4.46 ❌；L*=48 → 4.84 ✅
// 连微信自己都没管这条：品牌绿 #07C160 的 L*=68.8、白字只有 **2.38:1**。
// ⇒ 照仓库既有的「强调色 ＋ 深一档」两件套拆开（`AiChatScreen.kt` 发送键那边的注释本来就写着
//   "三颗图标是入口、发送键是主行动，深一档正好分主次"）。
//
// ## 取值
// · `AiChatGreen`（强调色，h=**149.9°** —— 微信品牌绿是 148.8°，几乎同色相）：
//   只用于**图标 tint / 浅底 / 选中 / 描边 / 块引 / 空态 / 发送键失效态**。
//   ⛔ **不承载白字**：白字压上去只有 4.03:1（对页面底 #F7F6F3 是 3.73:1），不到 AA 的 4.5。
//   当"图形"用是够的（非文本对比度 AA 只要 3:1）。
// · `AiChatGreenDeep`（实心底，白字 **5.59:1** ✅ 过 AA）：用于**实心按钮 ＋ 白字**那四处，
//   见 ai/AiChatScreen.kt 的「新对话 / 去设置」与 ai/AiSettingsScreen.kt 的「保存」，
//   以及聊天页那颗**发送键**（它原来读 `ThemeGreenDeep`，CHG-0101 之后是红棕）。
//   两档的明度差 9.1 个 L*，与旧的 #8B4A4A → #6E3636（差 9.4）同构。
// ⚠️ 与上面三段品牌渐变（`AiBlue` / `AiPurple` / `AiPink`）**互不相干**：渐变是 AI 的身份标识，
//   用户从没让动过，`aiBrandBrush` 也刻意没改。这两档只替换"单色强调"那一层。
// 判据：_tools/qa/_check_ai_chat_green.py ＋ android/app/src/test/.../ui/theme/AiChatGreenTest.kt。
val AiChatGreen = 0xFF4B8C5EL       // AI 聊天页强调色：图标 / 浅底 / 选中 / 描边（白字 4.03:1，别压字）
val AiChatGreenDeep = 0xFF3D734DL   // AI 聊天页实心底：按钮 + 白字（5.59:1，过 AA）

val SuccessGreen = 0xFF00AC6E      // 成功 / 正常（与 MgrGreen 同值，CHG-0102）
val WarningAmber = 0xFFE19B51      // 提醒 / 待处理（= 用户图三「提醒 / 重要」#C8A56A）
val DangerRed = 0xFFCD4A3C         // 危险 / 异常（2026-10-09 CHG-0101：原来的 #FF5252 太亮，压成砖红）
val InfoBlue = ThemeGreen          // 信息（原 #1E6FFF：跟着主操作色一起换）

// ===== 商品行（2026-10-09 CHG-0091：绿主题）=====
//
// 用户口径（ref m01501 / m01927）：「底下有个**颜色比较深的**……让这个信息比较重要，
// 能一眼看得出来」「商品名称**不留紫色**」「**低饱和**」。
//
// ⚠️ 2026-10-09 当天还立过一条"页面顶上一段深绿→白渐变"，同一天被用户撤掉
//    （ref m02715：「那个背景的渐变，就去掉吧……就是白色的默认色」）⇒ 那个起色 token
//    （`PageGradientGreen = 0xFF006A3AL`）**已经删掉**，页面背景不留绿。
//
// ⛔ 这一组**只给商品行用**，不要借去别的语义位置。
// ⚠️ 必须跟上面那批一样用 `0x…L` 这种字面量（不是 `Color(0x…)`）：
//    本仓库的语义色 token 统一是"裸 ARGB 值"（`Long`），用色的地方自己写 `Color(token)`。
//    写成 `Color(0x…)` 会让这一组变成**另一种类型**，同一条 `Row` 里混用就编译不过
//    （`TintedIcon(…, Color(ThemeGreen))` 与 `TintedIcon(…, ProductPurple)` 才是同一种）。
// 深一档：数量块的底。压白字 ≈ 5.2:1（对 #00A870 更差，只有 2.9:1）⇒ **只许大色块 / 大字号**，
// 小字不要往这两种绿上放（要用就再压深一档，别直接刷白字上去）。
val ThemeGreenDeep = 0xFF00532EL   // CHG-0101：红棕的深一档（原来是绿的 #0E7A50）
val ProductRowTint = 0xFFDBE8E1L      // 商品行：极浅红棕底（用户图三「商品订单」#B5726B 兑白）
val OnProductRowTint = 0xFF12301EL    // 浅红棕底上的品名（近黑的暖棕，对比 ≈ 13:1）

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
// ⚠️ 2026-10-09 CHG-0101：四件套跟着主操作色换（原来是绿 #00A870 / #D6F2E4 / #0B4A32）。
//    白字压在 #8B4A4A 上 ≈ 6.6:1（**过 AA 的 4.5:1** —— 比原来那个绿还好，绿只有 2.9:1）。
val Primary = Color(0xFF006C43)
val OnPrimary = Color(0xFFFFFFFF)
val PrimaryContainer = Color(0xFFDBE8E1)
val OnPrimaryContainer = Color(0xFF0E3021)
val SecondaryContainer = Color(0xFFE2E4E3)
val OnSecondaryContainer = Color(0xFF004128)
val Tertiary = Color(0xFFBC7730)
val ErrorLight = Color(0xFFCD4A3C)
val ErrorContainerLight = Color(0xFFFDE2E2)
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
val BackgroundLight = Color(0xFFF7F6F3)
val OnBackgroundLight = Color(0xFF2B2724)
val SurfaceLight = Color(0xFFFFFFFF)
val OnSurfaceLight = Color(0xFF2B2724)
val SurfaceVariantLight = Color(0xFFF1EFEA)
val OnSurfaceVariantLight = Color(0xFF434549)
val SurfaceContainerLow = Color(0xFFEAE7E1)  // 死值：亮色下被 Theme.kt 换成 SheetSurface（抽屉的面）
val SurfaceContainer = Color(0xFFEFECE6)
val SurfaceContainerHigh = Color(0xFFE4E0D9)

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

val OutlineLight = Color(0xFF838383)
val OutlineVariantLight = Color(0xFFD0D0D0)
val Success = Color(0xFF00AC6E)          // 成功（与 SuccessGreen 同值，CHG-0102）

// Dark
val PrimaryDark = Color(0xFF96C8FF)
val OnPrimaryDark = Color(0xFF002F7E)
val PrimaryContainerDark = Color(0xFF0046B2)
val OnPrimaryContainerDark = Color(0xFFCFE3FF)
val SecondaryContainerDark = Color(0xFF3C4660)
val OnSecondaryContainerDark = Color(0xFFD8E3FF)
val TertiaryDark = Color(0xFF00E0EC)
val ErrorDark = Color(0xFFFFAA9F)
val ErrorContainerDark = Color(0xFFAE0000)
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
val SuccessDark = Color(0xFF5FCD6C)

// ===== 「我的」页头部：深墨蓝（用户 2026-09-21 给的参考图的「背景」）=====
//
// 参考图那种「深色顶 + 白色大圆角卡」的观感，取**同一族**的深墨蓝：顶部更深、往下略提亮，
// 下端接我们自己的 NavBlue 家族（不是照抄它的黑灰，也不是我们平时的亮蓝）。
//
// ⚠️ 两个模式**共用同一组值**（头部在暗色下不跟着变浅）—— 但下端必须**比暗色页面底
//    `BackgroundDark #0E1014` 亮**，否则暗色模式下头部和页面糊成一片，
//    与 2026-09-18 那次「卡片和背景同色、信息丢失」是同一类事故。
val ProfileHeaderTop = Color(0xFF0C1A33)
val ProfileHeaderBottom = Color(0xFF10305D)