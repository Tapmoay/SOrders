package com.tapmoay.sorders.ui.profile

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.AccountBalanceWallet
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Lightbulb
import androidx.compose.material.icons.filled.NotificationsActive
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Update
import androidx.compose.material.icons.filled.VolumeUp
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.NewOrderAlert
import com.tapmoay.sorders.ui.common.DangerConfirmDialog
import com.tapmoay.sorders.ui.common.ErrorView
import com.tapmoay.sorders.ui.common.Hint
import com.tapmoay.sorders.ui.common.LightStatusBarIcons
import com.tapmoay.sorders.ui.common.LoadingBox
import com.tapmoay.sorders.ui.common.appViewModel
import com.tapmoay.sorders.ui.nav.Role
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.ui.theme.ProfileHeaderBottom

/**
 * 「我的」——**三端共用**一页（货主 / 派单员 / 司机都从底部 Tab 进）。
 *
 * ## 这一版为什么长这样（用户 2026-09-21 给的参考图）
 * 用户原话：「把我的按到他的这个样式进行修改，布局是抄他的…**尤其（参考）他那个背景
 * 以及那个卡片的样式**」。所以照抄的是**骨架**：
 *
 * ```
 * ┌ 深墨蓝头部（画到状态栏下面，带极淡同心弧纹；高度调过，见 ProfileHeader 的注释）
 * │   头像 + 角色徽章 + 姓名 / 账号
 * ├ 一整块白色大圆角卡片（顶部 24dp 圆角，盖住头部下沿）＝ 参考图的「卡片样式」
 * │   行 = 语义色圆角图标 + 标题 + 右侧当前值 + `>`   ← 行与行之间**不画分隔线**
 * └
 * ```
 *
 * ⛔ **内容不照抄**（用户明确说了「不要完全的照抄」）：参考图的「语言设置 / 账号信息 /
 * 结算账户」我们三样都没有（没有第二语言；账号就在头部写着；我们没有"收银结算账户"这个概念）。
 * 它第二行那个下拉选择器（「先结账后用餐 ▾」）我们**没有对应字段**，所以那一行改成了
 * 司机自己的计费规则（纯展示、不给假的可点感）。
 *
 * ## 第一层就这六行（用户 2026-09-21 逐条过过）
 * | 行 | 为什么在这里 |
 * |---|---|
 * | 我的账本 | 只对"有按单的钱要对"的司机显示（条件见下面那段注释，一字未改） |
 * | 消息提醒 | 来单会不会响 —— 司机/派单员最要紧的一件事 |
 * | **提示** | 解释句总开关。⚠️ 当天**先**搬进「基础设置」，用户看图后**又要求搬回这里** |
 * | 基础设置 | 第二层（随日落 / 夜间模式） |
 * | 关于与更新 | 点一下＝检查更新（原来的「关于与更新」+「检查更新」两行合一） |
 * | 退出登录 | 与其它行同形；点一下**先弹确认框**（防误碰） |
 *
 * ⛔ **「消息中心」那一行删掉了**（用户 2026-09-21：「已经在导航栏里有一个消息中心了，
 * 这属于重复设计」）。不丢信息：底部导航的消息 Tab 上**本来就有未读角标**
 * （`RoleHomeScreen` 的 `BadgedBox`）——所以这里连未读数都不再需要自己拉一份。
 *
 * ## 三个"看着是小事、其实是事故"的点
 * 1. **头部铺到状态栏下面** → 必须配 [LightStatusBarIcons]：浅色模式下主题把状态栏图标
 *    设成深色，压在深墨蓝上**一个都看不见**（时间/电量/信号全消失，且不报错）。
 * 2. **头部固定、只有列表滚**。为什么不让头部一起滚：滚走之后状态栏又变回浅色底，
 *    而图标还是白的 → 同样是"看不见"。固定头部让"状态栏下面是深色"始终成立。
 *    ⚠️ 列表必须**能滚**：2026-09-21 真机抓到过不可滚的 `Column` 把「退出登录」顶出屏幕
 *    且**够不着**（表现是"退不了登录"，还不是崩溃）—— 见 `docs/AI_WORK_CLAIM.md`。
 * 3. **每一行都套了 [RowMotion]**（落位 + 跟随，越往下越明显）：用户要"有点反应、别太呆板"。
 *    它只动画面、不动布局（见那个文件的注释），所以点击区域不受影响。
 */
@Composable
fun ProfileScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenFreight: () -> Unit = {},
    /** 消息提醒设置（语音提醒/念几遍/关掉 App 也收单） */
    onOpenAlerts: () -> Unit = {},
    /** 基础设置（随日落 / 白天夜间 —— 纯显示偏好的第二层） */
    onOpenBasicSettings: () -> Unit = {},
    /** true = 作为底部导航内容内嵌（隐藏返回矢头/双重 inset） */
    embedded: Boolean = false,
) {
    val vm: ProfileViewModel = appViewModel { ProfileViewModel(container) }
    // 每次进这一页**静默重拉**一次资料：「我的账本」那一格的显示条件（`pays_per_order`）
    // 会被派单员改规则改掉（固定工资 ↔ 工资+抽成 ↔ 按单计费），不重拉就得**杀进程重启**
    // 才看得见 —— 2026-09-20 实测：挂了提成规则之后切 Tab 没反应、重启才出现，用户会以为"没生效"。
    LaunchedEffect(Unit) { vm.loadMe(silent = true) }
    val context = LocalContext.current
    // 「退出登录」**不直接退**：先弹一个确认框（防误碰）。用户 2026-09-21 原话：
    // 「他那个退出登录不是点一下就直接退出，为了防止误碰，会弹出一个框，四周圆角并且是长方形的，
    //  然后问是否确认，就是一个确认退出和一个取消」—— 那个框复用全 App 那一个危险操作弹层
    // （`ui/common/Components.kt::DangerConfirmDialog`，M3 弹窗本身就是四周圆角长方形），
    // ⛔ 不再自己拼一个 AlertDialog（两份写法迟早长得不一样）。
    var confirmLogout by remember { mutableStateOf(false) }
    // 列表滚动（内容长时能滚；2026-09-21 真机：不可滚会把「退出登录」顶出屏幕够不着）
    val listScroll = rememberScrollState()
    // **果冻**：整列跟着手指走、松手弹回（用户 2026-09-21 第二次反馈要的就是这个）。
    // ⚠️ 它挂在**手势**上（`nestedScroll`），不是挂在滚动位置上 —— 第一版挂在滚动位置上，
    //    于是在"列表装得下、根本滚不动"的机器上**一点反应都没有**（用户实测：「我刚滑了一下没有反应」）。
    val jelly = rememberJellyState()
    // ⛔ 没有这一行的话：浅色模式下主题把状态栏图标设成**深色**，而这一页的头部是深墨蓝、
    //    还铺到了状态栏下面 —— 时间/电量/信号会**一个都看不见**，且不报错（只有截图缩略看得见）。
    LightStatusBarIcons()
    // ⛔ 这里原来持了一份本地镜像（`remember { mutableStateOf(prefs.alwaysOn) }`），理由是
    // "SharedPreferences 不是可观察状态"。2026-09-21 那条理由不成立了：总开关是
    // **Compose 可观察状态**（`core/HintPrefs.kt::visible`），各页面直接读它就订阅上了。
    // 再镜像一份＝两处各有一个数，而用户看到的必须是同一个（见 docs/HINT_STYLE.md §5）。

    Column(
        Modifier
            .fillMaxSize()
            // 整页底色 = 头部**下端**那个颜色：白卡的 24dp 圆角缺口露出来的就是它，
            // 换成页面背景色（浅灰）会在头部下沿切出两个浅色小三角。
            .background(ProfileHeaderBottom),
    ) {
        // 头部**不滚**（见类文档第 2 点）；资料还在路上时照常画，值显示 `—`
        ProfileHeader(
            user = vm.user,
            onBack = if (embedded) null else onBack,
        )
        Surface(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth(),
            shape = RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp),
            color = MaterialTheme.colorScheme.surface,
        ) {
            when {
                vm.loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { LoadingBox() }
                vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.loadMe() })
                else -> Column(
                    Modifier
                        .fillMaxSize()
                        // ⚠️ **顺序不能反**：`nestedScroll` 必须写在 `verticalScroll` **之前**
                        //    （Modifier 链里靠前的在外层）。写成 `.verticalScroll(..).nestedScroll(..)`
                        //    等于把连接挂在滚动节点的**子级**上 —— 它一个事件都收不到，
                        //    表现就是"按住滑动、整列纹丝不动"（2026-09-21 实测：按住拖 1000px，
                        //    量像素发现每一行都还在原位）。⚠️ 这一条已钉进红线，别改回去。
                        .nestedScroll(jelly.connection)
                        .verticalScroll(listScroll)
                        .padding(horizontal = 6.dp),
                ) {
                    Spacer(Modifier.height(6.dp))

                    // ---- 司机「我的账本」（其余角色的账本在工作台入口）----
                    // ⚠️ 判据是**他有没有按单的钱要对**，不是"他是不是司机"：
                    //    ① 一直拿固定工资、从来没按单跑过的司机**没有这一格**
                    //      （用户 2026-09-20 明确要求：「拿固定工资的司机不需要「我的账本」，所以他是没有的」）；
                    //    ② **当前按单计费**（`pays_per_order`）或**固定工资 + 抽成**的司机**有** —— 他每单都有钱要对；
                    //    ③ ⚠️ 2026-09-21 真机补上的一档：**被改成固定工资、但账上已经有按单账单**的司机
                    //      也要有（`has_per_order_earnings`）。prod 实测那位司机正是这种：当前规则是
                    //      「月薪司机 · 固定 6500」，可账上躺着 92 笔按单账单 ¥2024（本月 21 单 ¥462）
                    //      —— 只按 ② 判的话这一格消失，而**订单卡片已经一个金额都不画了**，
                    //      那笔钱在 App 里就彻底看不见（`GET /freight-settlement` 其实一条不少地返回）。
                    //    两个字段都来自后端（判据在 `services/driver_pay`，与账单同源），
                    //    界面不许自己按规则/车型猜；派单员一改规则，这里跟着变。
                    //    老后端没有第三个字段时退回 ①② 的旧判据（`null` 不当成 true）。
                    if (vm.user?.role == "driver" &&
                        (vm.user?.paysPerOrder == true || vm.user?.hasPerOrderEarnings == true)
                    ) {
                        RowMotion(0, jelly) {
                            ProfileRow(
                                icon = Icons.Default.AccountBalanceWallet,
                                tint = Color(MoneyOrange),
                                title = "我的账本",
                                trailing = {
                                    Text(
                                        "按单计费明细",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                },
                                onClick = onOpenFreight,
                            )
                        }
                    }

                    // ---- 消息提醒：把「来单了会不会喊、喊几遍、关掉 App 还收不收」摆在明面上 ----
                    // 右侧直接写当前状态——不写的话，用户只能进去看一遍才知道现在是开是关。
                    RowMotion(1, jelly) {
                        ProfileRow(
                            icon = if (NewOrderAlert.hasVoice(Role.fromKey(container.tokenStore.cachedRole() ?: ""))) {
                                Icons.Default.VolumeUp
                            } else {
                                Icons.Default.NotificationsActive
                            },
                            tint = Color(0xFF1E6FFF),
                            title = "消息提醒",
                            // 副标题按角色说：**货主**没有语音，对他写「语音播报」就是承诺一件不会发生的事
                            // （司机与派单员各有一句，见 NewOrderAlert.voiceKind）。
                            // ✅ 2026-09-21 起它走 `Hint`（受「提示」总开关控制）：这一句是在**说明这一格
                            // 管什么**（按角色选一句、静态），属解释句；用户当时正是把它红框圈出来要归开关的。
                            subtitle = {
                                Hint(
                                    if (NewOrderAlert.hasVoice(Role.fromKey(container.tokenStore.cachedRole() ?: ""))) {
                                        "语音播报 / 后台接收新单"
                                    } else {
                                        "通知栏提醒 / 后台接收新单"
                                    }
                                )
                            },
                            trailing = {
                                Text(
                                    alertSummary(container),
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            },
                            onClick = onOpenAlerts,
                        )
                    }

                    // ---- 提示：App 里**所有解释性说明**的**一个总开关**（用户 2026-09-21 定案）----
                    // ⚠️ 位置定过两次：先在第一层 → 当天按「不重要的搬进基础设置」搬进子页
                    //    → **当天用户看图后又要求搬回第一层**（原话：「基础设置有个要移出来，
                    //    叫做提示提醒，那个不能放在里面」）。⛔ 别再随手塞回子页。
                    // 标题只留「提示」两个字；副标题说清现在是**开还是关**（不进去也知道）。
                    // ⛔ 关掉它**只关解释句**（`ui/common/Hints.kt::Hint`）：金额、数量、状态回执、
                    // 警告与空态文案一律照旧显示（`docs/HINT_STYLE.md` §2）。
                    RowMotion(2, jelly) {
                        ProfileRow(
                            icon = Icons.Default.Lightbulb,
                            tint = Color(0xFF00A2C8),
                            title = "提示",
                            // ⚠️ 状态文字**放在右边、和标题同一行**（用户 2026-09-21 第二次反馈：
                            //    「那个不显示说明能不能放在提示的后面，就不要做两排，跟着一个线一个杠」
                            //    —— 短状态跟版本号一样靠右，**只有详细说明才另起一行**）。
                            trailing = {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text(
                                        if (container.hintPrefs.visible) "显示所有说明" else "不显示说明",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                    Spacer(Modifier.width(8.dp))
                                    Switch(
                                        checked = container.hintPrefs.visible,
                                        onCheckedChange = { container.hintPrefs.setByUser(it) },
                                    )
                                }
                            },
                            onClick = { container.hintPrefs.setByUser(!container.hintPrefs.visible) },
                            showChevron = false,
                        )
                    }

                    // ---- 基础设置（第二层）：剩下的纯显示偏好 ----
                    RowMotion(3, jelly) {
                        ProfileRow(
                            icon = Icons.Default.Settings,
                            // 灰色而不是语义色：它是**分组容器**，不是某个功能模块 ——
                            // 借用任何一个模块色都会让人以为"这是那个功能"。
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                            title = "基础设置",
                            // 里面装了什么**放在右边同一行**（用户 2026-09-21 第二次反馈：
                            // 「包括那个基础设置它下面那个说明也改成放右边，就跟那个版本号一样」）。
                            // 这一行是**内容清单**（不是解释句）→ 走 `Text`（永不隐藏），
                            // 与「我的账本」那一行的「按单计费明细」同一类。
                            // ⛔ 别顺手把它改成走开关的那种写法：红线有一条钉着
                            //    "一次解释入口调用里至少得有一段解释句"，塞进去会当场报红 ——
                            //    那条判据要防的正是"把标签当提示藏起来"。
                            // ⚠️ 写注释时**不要**写出「Hint + 左括号」那三个字符：盘点脚本
                            //    （`_hint_inventory.py`）是按括号配对切调用点的，注释里一个不配平的
                            //    左括号会被当成一个真调用，把**后面**那一行的文案算到它头上 ——
                            //    2026-09-21 实测：这一条注释让红线报出"有一处 Hint 调用里没有解释句"，
                            //    而代码本身是对的（那一轮的白查）。
                            trailing = {
                                Text(
                                    "外观 · 夜间模式",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            },
                            onClick = onOpenBasicSettings,
                        )
                    }

                    // ---- 关于与更新：原「关于与更新」(只显示版本) + 「检查更新」两行**合一** ----
                    // 用户 2026-09-21 的对应关系是「关于我们**就是**我们的那个版本更新」，
                    // 所以这一行点一下**直接检查更新**，不再中间夹一层"关于页"。
                    // 右侧显示当前版本：用户想知道"我装的是哪一版"不必点进去。
                    RowMotion(4, jelly) {
                        ProfileRow(
                            icon = if (vm.updateState == "downloading") Icons.Default.Download else Icons.Default.Update,
                            tint = Color(0xFF00B578),
                            title = when (vm.updateState) {
                                "checking" -> "正在检查更新…"
                                "downloading" -> "正在下载更新 " + vm.downloadProgress + "%"
                                "installing" -> "等待安装新版…"
                                "needInstallPermission" -> "还差一步：允许安装应用"
                                else -> "关于与更新"
                            },
                            // 下载中补第二行：速度 / 已下多少 / 还剩多久。
                            // 只说「正在下载 87%」的话，用户无法判断是"快好了"还是"卡住了"——
                            // 「下载非常慢」这种反馈正是因为屏幕上没有任何可以判断的数字。
                            subtitle = {
                                val extra = when {
                                    vm.updateState == "downloading" && vm.downloadDetail.isNotBlank() -> vm.downloadDetail
                                    vm.updateState == "installing" -> "安装包已下好：请在系统弹出的界面点「安装」"
                                    vm.updateState == "needInstallPermission" -> "安卓要求先允许本应用安装应用，点这里处理"
                                    else -> null
                                }
                                if (extra != null) {
                                    Text(
                                        extra,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                            },
                            trailing = {
                                if (vm.updateState == "downloading") {
                                    LinearProgressIndicator(
                                        progress = { vm.downloadProgress / 100f },
                                        modifier = Modifier
                                            .width(90.dp)
                                            .height(8.dp),
                                        color = Color(0xFF00B578),
                                    )
                                } else {
                                    Text(
                                        "v" + vm.currentVersion,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                            },
                            // 正在检查/下载时**整行不再可点**：传 null 而不是空 lambda（那样会有按压反馈却什么都不做）
                            onClick = if (vm.updateState == "checking" || vm.updateState == "downloading") {
                                null
                            } else {
                                { vm.checkUpdate() }
                            },
                            showChevron = vm.updateState != "downloading",
                        )
                    }

                    Spacer(Modifier.height(10.dp))
                    // ---- 退出登录：与上面几行**同一种形态**（语义色圆底图标 + 文字），
                    // 点一下**先弹确认框**（防误碰），确认了才真退。
                    // 用户 2026-09-21 两句话定了这一格：先说「不要放到中间，做成跟其他形式一样——
                    // 一色加图标然后加文字」，随后补上「不是点一下就直接退出，为了防止误碰要弹框，
                    // 一个确认退出一个取消」。
                    // ⛔ 没有 `>` 箭头：这一行是**动作**不是"进下一页"（箭头会承诺一个不存在的页面）。
                    RowMotion(5, jelly) {
                        ProfileRow(
                            icon = Icons.AutoMirrored.Filled.Logout,
                            tint = MaterialTheme.colorScheme.error,
                            title = "退出登录",
                            titleColor = MaterialTheme.colorScheme.error,
                            onClick = { confirmLogout = true },
                            showChevron = false,
                        )
                    }
                    Spacer(Modifier.height(16.dp))
                }
            }
        }
    }

    // 退出登录确认（防误碰）：点标题那一行**只弹框**，这里才是真正退出的地方。
    // 说明为什么不会丢东西——退出只清这台手机的登录态与常驻服务，服务器上的订单/账本一条不动，
    // 不写清楚的话用户不敢点（这是一个"看着危险、其实不危险"的动作）。
    if (confirmLogout) {
        DangerConfirmDialog(
            title = "确认退出登录？",
            message = "退出后要重新输入账号和密码才能进来。订单、账本这些数据都在服务器上，不会丢。",
            confirmText = "确认退出",
            onConfirm = {
                confirmLogout = false
                vm.logout { }
            },
            onDismiss = { confirmLogout = false },
        )
    }

    // 有新版 → 确认弹窗
    if (vm.updateState == "confirm" && vm.latest != null) {
        AlertDialog(
            onDismissRequest = { vm.updateState = "idle" },
            // ⚠️ **两行都要带构建号**（2026-09-23 用户报障：只显示 `0.2.3` 时，
            //    「发现新版本 v0.2.3」与「当前版本：v0.2.3 · 2026092204」看着一模一样，
            //    他读成"让我重装当前版本"）。判新旧本来就是 `versionCode`，就把它显示出来。
            //    口径只有一处：`UpdateProgress.versionLabel`（有单测）。
            title = {
                Text("发现新版本 v" + UpdateProgress.versionLabel(vm.latest?.version, vm.latest?.versionCode))
            },
            text = {
                Column {
                    Text("当前版本：v" + vm.currentVersion)
                    Spacer(Modifier.height(6.dp))
                    val note = vm.latest?.note.orEmpty()
                    if (note.isNotBlank()) Text(note, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.height(10.dp))
                    Text("是否立即下载并安装更新？", style = MaterialTheme.typography.titleSmall)
                }
            },
            confirmButton = {
                TextButton(onClick = { vm.downloadAndInstall(context) }) { Text("下载并更新") }
            },
            dismissButton = {
                TextButton(onClick = { vm.updateState = "idle" }) { Text("取消") }
            },
        )
    }

    // 系统不让装 APK → 先把用户领到开关那里。
    // 不这么做的话，用户点完「下载并更新」看到的是系统弹的一句英文
    // "…isn't allowed to install unknown apps from this source"，
    // 绝大多数人的下一步是点 Cancel，然后得出结论「下载完了但没更新」。
    if (vm.updateState == "needInstallPermission") {
        AlertDialog(
            onDismissRequest = { vm.updateState = "idle" },
            title = { Text("还差一步：允许安装应用") },
            text = {
                Column {
                    Text("安卓要求先允许「SOrders 派单送货」安装应用，否则系统会把安装界面直接拦下来。")
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "点「去设置」打开开关，返回后再点一次「检查更新」就行——安装包不用重新下载。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            },
            confirmButton = {
                TextButton(onClick = { vm.openInstallPermissionSettings(context) }) { Text("去设置") }
            },
            dismissButton = {
                TextButton(onClick = { vm.updateState = "idle" }) { Text("取消") }
            },
        )
    }

    // 结果提示
    if (vm.updateState == "latest" && vm.updateMessage != null) {
        AlertDialog(
            onDismissRequest = { vm.updateState = "idle"; vm.updateMessage = null },
            title = { Text("检查更新") },
            text = { Text(vm.updateMessage.orEmpty()) },
            confirmButton = {
                TextButton(onClick = { vm.updateState = "idle"; vm.updateMessage = null }) { Text("知道了") }
            },
        )
    }
}

/**
 * 「消息提醒」这一行右侧的状态摘要。
 *
 * 为什么要写出来：用户对自己手机的行为没有可靠的记忆，
 * 而这一项直接决定"派单来了会不会响"。写成一句话，用户不用进去看就知道现在是什么状态；
 * 判定（含"按角色说不同的话"）在纯函数 [NewOrderAlert.summary] 里，有单测。
 */
private fun alertSummary(container: AppContainer): String {
    val prefs = container.alertPrefs
    val role = Role.fromKey(container.tokenStore.cachedRole() ?: "")
    return NewOrderAlert.summary(
        role = role,
        notificationsAllowed = container.notifyCenter.canPost(),
        voiceEnabled = prefs.voiceEnabled,
        repeat = prefs.repeatTimes,
        background = prefs.backgroundEnabled(role),
    )
}
