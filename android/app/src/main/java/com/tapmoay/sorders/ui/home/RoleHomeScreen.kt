package com.tapmoay.sorders.ui.home

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.NotificationsOff
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.tapmoay.sorders.core.AlertService
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.DeviceLocation
import com.tapmoay.sorders.core.NotifyPermission
import com.tapmoay.sorders.core.SunLocation
import com.tapmoay.sorders.ui.messages.MessagesScreen
import com.tapmoay.sorders.ui.common.CardAlertDialog
import com.tapmoay.sorders.ui.common.LoadingBox
import com.tapmoay.sorders.ui.nav.AiNavButton
import com.tapmoay.sorders.ui.nav.Modules
import com.tapmoay.sorders.ui.nav.NotchedBarShape
import com.tapmoay.sorders.ui.nav.Role
import com.tapmoay.sorders.ui.dispatcher.DispatcherPoolScreen
import com.tapmoay.sorders.ui.driver.DriverOrdersScreen
import com.tapmoay.sorders.ui.nav.Routes
import com.tapmoay.sorders.ui.profile.ProfileScreen
import com.tapmoay.sorders.ui.theme.ThemeMode
import com.tapmoay.sorders.ui.theme.aiBrandBrush
import kotlinx.coroutines.launch

/**
 * 角色主界面：底部导航（工作台 / 消息 / 我的）。
 * Tab 由 Modules.bottomTabs 配置驱动，加 Tab 只改配置。
 */
@Composable
fun RoleHomeScreen(
    container: AppContainer,
    onNavigate: (String) -> Unit,
) {
    val session by container.tokenStore.sessionFlow.collectAsState(initial = null)

    // 登录后基础权限引导：定位 / 通知 / 相机 / 存储（按系统版本动态组装，缺失才请求）
    val permContext = LocalContext.current
    // 系统定位兜底（只喂日落）：高德拿不到坐标时用，见 core/DeviceLocation.kt 的说明
    val scope = rememberCoroutineScope()
    fun warmUpLocation() {
        if (!container.locationManager.requestSingle()) {
            // 连发起都没成功（SDK 起不来/权限被拒）→ 直接走系统定位，别等一个永远不会来的回调
            scope.launch { if (DeviceLocation.requestSingle(permContext) != null) ThemeMode.refreshAuto(permContext) }
        }
    }
    // ⭐ 通知权限的**硬提示**（台账 L-26 第⑤条 / CHG-0056）：手机上不让发通知时，进首页主动拦一次、
    //    把用户领到那个开关去 —— 而不是像从前那样"静默降级"（用户原话 m01132：
    //    「这个一定要有的这个权限，我们**如果权限不足的话，我们就给他开**」；
    //    漏通知的后果他点得很明白：「**账会乱掉**的，绝对是不允许的」）。
    var showNotifyGuide by rememberSaveable { mutableStateOf(false) }

    // 判一次"要不要拦"。**只在系统那轮权限弹窗走完之后调**：用户刚点过"允许"就不该再拦
    // （areNotificationsEnabled() 有一拍延迟，所以这一轮拿到的授予结果也当"开着"看）；
    // 没给（或他早就在系统设置里关过）才轮到我们这张。
    fun guideNotifyPermission(grantedNow: Boolean) {
        val ok = grantedNow || NotifyPermission.enabled(permContext)
        if (NotifyPermission.shouldPrompt(ok, NotifyPermission.promptedThisLaunch)) {
            NotifyPermission.markPrompted()
            showNotifyGuide = true
        }
    }

    val permLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { grants ->
        // 定位权限授予（或已授予）→ 预热定位：地图选点打开即跳当前位置，无需等待
        val locOk = grants[Manifest.permission.ACCESS_FINE_LOCATION] == true ||
                grants[Manifest.permission.ACCESS_COARSE_LOCATION] == true
        if (locOk) warmUpLocation()
        guideNotifyPermission(grants[Manifest.permission.POST_NOTIFICATIONS] == true)
    }
    LaunchedEffect(Unit) {
        val perms = buildList {
            add(Manifest.permission.ACCESS_FINE_LOCATION)
            add(Manifest.permission.ACCESS_COARSE_LOCATION)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                add(Manifest.permission.POST_NOTIFICATIONS)
                add(Manifest.permission.READ_MEDIA_IMAGES)
            } else {
                add(Manifest.permission.READ_EXTERNAL_STORAGE)
            }
            // ⛔ 这里原来还 add 了 CAMERA：本 App 不调相机 API（拍照全走系统相机 App 的
            //    ACTION_IMAGE_CAPTURE），声明了它反而会让"拒绝授权后再拍照"直接崩溃
            //    （2026-09-19 报告 P1-9）——声明已从清单删除，这里也不许再要。 
        }.filter {
            ContextCompat.checkSelfPermission(permContext, it) != PackageManager.PERMISSION_GRANTED
        }
        if (perms.isNotEmpty()) {
            permLauncher.launch(perms.toTypedArray())
        } else {
            // 权限齐全：直接预热定位（地图选点秒定位）
            warmUpLocation()
            // 没有要申请的了（含 API 33 以下：那一档根本没有 POST_NOTIFICATIONS）：
            // 这时候还没权限就只可能是**用户在系统设置里关掉的**，系统弹窗不会再出现 ——
            // 只能靠我们这张硬提示把他领过去。
            guideNotifyPermission(false)
        }
    }

    // 定位到手就重算一次外观（刚启动时还没有坐标，先按估算走）
    LaunchedEffect(container) {
        container.locationManager.locations.collect {
            if (SunLocation.update(it.lat, it.lng)) {
                ThemeMode.refreshAuto(permContext)
            } else {
                // 高德这一路失败了（Key 没绑签名 / 没服务 / 网络不通）：退到系统定位。
                // 日落只需要经纬度，不该被高德的鉴权卡住——"一直显示时区估算"就是这里的静默失败。
                if (DeviceLocation.requestSingle(permContext) != null) ThemeMode.refreshAuto(permContext)
            }
        }
    }

    // 会话未就绪时先加载（sessionFlow 为冷流，回退到本页时可能短暂为 null，
    // 若此刻按角色算 Tab 数量会变少，selectedTab 越界崩溃——故 null 时整页等待）
    if (session == null) {
        Box(Modifier.fillMaxSize()) { LoadingBox() }
        return
    }
    val role = Role.fromKey(session?.role ?: "")
    val tabs = Modules.bottomTabs(role)
    var selectedTab by rememberSaveable { mutableIntStateOf(0) }
    val tabIdx = selectedTab.coerceIn(0, tabs.lastIndex)
    val unread by container.realtimeHub.unreadCount.collectAsState()

    // 后台接收新单（前台服务）：进主界面时对齐一次。
    // 为什么放在这里而不是 Application.onCreate：Android 12+ **只允许 App 可见时**
    // 启动前台服务，主界面出现是"可见"的确定时机（Application 里起会被系统直接拒）。
    LaunchedEffect(role) {
        AlertService.sync(permContext, role)
    }

    // AI 助手入口 = 底部导航正中间的凸起圆钮，**仅派单端**。
    //
    // 为什么不放工作台网格里（派单端）：它是"随时按一下问一句"的入口，混在"进哪个模块"
    // 的网格里既慢一步，也容易被当成又一个管理页面；而且派单端 4 个 Tab + 圆钮 = 5 个槽位，
    // 圆钮正好落在导航栏正中，视觉上成立。
    //
    // 为什么货主端改成工作台图标（`Modules.shipperEntries` 第一格）：
    // 货主端只有 3 个 Tab（工作台/消息/我的），插一个占位后圆钮落在 1/4 处——偏左、
    // 不对称，看着像排错了（用户 2026-09-15 反馈）。所以那边走网格图标，颜色用 AiBlue。
    //
    // 权限阶梯：**派单员 > 货主 > 司机**。
    // - 派单员：全集（后端 18 个权限点）；
    // - 货主：只有他工作台里有的那几件（下单、撤自己的单、常用联系人/地址库、查账本）。
    //   动作白名单在 `AiWrites.SHIPPER_ACTIONS` 里；**执行侧由 AiWriteService 再挡一次**，
    //   界面这道只是"不给你看"，不是安全边界；
    // - 司机：**不开放**。他的需求最小（只是"查订单价格"），而且那是以后的事——
    //   现在给他入口只会让他面对一堆点不动的功能。
    val showAiButton = role == Role.DISPATCHER
    val aiSlot = tabs.size / 2 // 4 个 Tab 时 = 2，正好落在中间

    // ⚠️ 2026-10-09 CHG-0091：这里**曾经**铺过一层"深绿往下渐到白"（`TopGreenFade`），
    //    当天就被用户撤掉了（ref m02715 逐字）：「算了，算了，那个背景的渐变，就去掉吧……
    //    就是白色的默认色」。所以现在**不铺任何东西**，Scaffold 用它自己的页面底色
    //    （M3 默认 containerColor = colorScheme.background = #FBFBFA 近白）。
    //    ⛔ 别再往这一层加背景：主界面是 4 个 Tab 共用的最外层，在这里画一笔
    //    等于给「派单池 / 工作台 / 消息 / 我的」四页同时换底。
    Scaffold(
        bottomBar = {
            // 顶部留出 AiNavButton.Protrude 的内边距：给凸起的那部分腾地方，
            // 否则圆钮超出 Box 边界可能被裁掉上半截。
            Box(Modifier.padding(top = if (showAiButton) AiNavButton.Protrude else 0.dp)) {
                // 导航条底色自己画（带凹口），所以 M3 NavigationBar 的容器必须是透明的。
                // 参照图（用户给的星巴克截图）里，圆钮不是压在一根平直的上沿上，
                // 而是**坐在导航栏凹进去的半圆缺口里**——见 ui/nav/NotchedNavBar.kt。
                //
                // 用 matchParentSize 而不是写死高度：背景的尺寸跟着 NavigationBar 走，
                // M3 以后改栏高也不会对不上（写死 80.dp 就会留一条缝或盖住半行字）。
                // 声明在前 = 画在 NavigationBar 下面（Box 按声明顺序绘制）。
                val barShape = remember { NotchedBarShape() }
                if (showAiButton) {
                    Box(
                        Modifier
                            .matchParentSize()
                            .shadow(8.dp, barShape)
                            .background(MaterialTheme.colorScheme.surface, barShape),
                    )
                }
                NavigationBar(
                    containerColor = if (showAiButton) {
                        androidx.compose.ui.graphics.Color.Transparent
                    } else {
                        NavigationBarDefaults.containerColor
                    },
                ) {
                    tabs.forEachIndexed { i, tab ->
                        // 中间插一个空占位项：5 个槽等宽，圆钮才会落在这条导航栏的正中
                        if (showAiButton && i == aiSlot) {
                            NavigationBarItem(selected = false, onClick = {}, enabled = false, icon = {})
                        }
                        NavigationBarItem(
                            selected = tabIdx == i,
                            onClick = { selectedTab = i },
                            icon = {
                                if (tab.content == "messages" && unread > 0) {
                                    BadgedBox(
                                        badge = {
                                            Badge { Text(if (unread > 99) "99+" else unread.toString()) }
                                        },
                                    ) {
                                        Icon(tab.icon, contentDescription = tab.label)
                                    }
                                } else {
                                    Icon(tab.icon, contentDescription = tab.label)
                                }
                            },
                            label = { Text(tab.label) },
                            colors = NavigationBarItemDefaults.colors(
                                selectedIconColor = androidx.compose.ui.graphics.Color(tab.color),
                                selectedTextColor = androidx.compose.ui.graphics.Color(tab.color),
                                indicatorColor = androidx.compose.ui.graphics.Color(tab.color).copy(alpha = 0.14f),
                                unselectedIconColor = MaterialTheme.colorScheme.onSurfaceVariant,
                                unselectedTextColor = MaterialTheme.colorScheme.onSurfaceVariant,
                            ),
                        )
                    }
                }
                if (showAiButton) {
                    Surface(
                        onClick = { onNavigate(Routes.AI_CHAT) },
                        modifier = Modifier
                            .align(Alignment.TopCenter)
                            .offset(y = -AiNavButton.Protrude)
                            .size(AiNavButton.Size),
                        shape = CircleShape,
                        // 底色交给里面的渐变（Surface 只吃单色），阴影仍由 Surface 出
                        color = androidx.compose.ui.graphics.Color.Transparent,
                        shadowElevation = 8.dp,
                    ) {
                        Box(
                            modifier = Modifier
                                .fillMaxSize()
                                .background(aiBrandBrush(), CircleShape),
                            contentAlignment = Alignment.Center,
                        ) {
                            Icon(
                                Icons.Default.AutoAwesome,
                                contentDescription = "AI 助手",
                                tint = androidx.compose.ui.graphics.Color.White,
                                modifier = Modifier.size(AiNavButton.IconSize),
                            )
                        }
                    }
                }
            }
        },
    ) { padding ->
        // ⚠️ 「我的」这一 Tab 的深色头部要**画到状态栏下面**（用户 2026-09-21 给的参考图那种
        //    "深色顶"，见 `ui/profile/ProfileHeader.kt`），所以它**不吃** Scaffold 的**顶部** inset
        //    —— 改由 `ProfileHeader` 自己吃（`WindowInsets.statusBars`，只让内容让开、背景铺上去）。
        //    不这么做的话头部会被顶下来，上面留一条页面底色的浅灰带，「深色顶」的观感就没了。
        //    ⛔ 其余 Tab **一行都不变**（照旧吃完整 padding），它们的 AppBar 依赖这个顶部 inset。
        val contentPad = if (tabs[tabIdx].content == "profile") {
            PaddingValues(
                start = padding.calculateStartPadding(LocalLayoutDirection.current),
                top = 0.dp,
                end = padding.calculateEndPadding(LocalLayoutDirection.current),
                bottom = padding.calculateBottomPadding(),
            )
        } else {
            padding
        }
        Box(Modifier.fillMaxSize().padding(contentPad)) {
            when (tabs[tabIdx].content) {
                "dispatch" -> DispatcherPoolScreen(
                    container = container,
                    onBack = {},
                    onOpenOrder = { id -> onNavigate(Routes.orderDetail(id)) },
                    embedded = true,
                )
                "workbench" -> WorkbenchScreen(
                    container = container,
                    role = role,
                    entries = Modules.entriesFor(role),
                    onOpen = onNavigate,
                )
                "messages" -> MessagesScreen(
                    container = container,
                    onBack = {},
                    // 能查的消息点进去**直达那一页**（2026-09-21 用户要求：「到消息中心哦。其实本来
                    // 就要做到直达的」；2026-10-11 FEAT-0019 扩到库存 / 收款 / 应付 / 发票 / 价格 /
                    // 账号）。路由由消息页一处算好（type + 当前角色 + payload），这里只把
                    // onNavigate 交出去；算不出来时消息页不跳。
                    onOpenRoute = onNavigate,
                    embedded = true,
                )
                "driverOpen", "driverDone" -> DriverOrdersScreen(
                    container = container,
                    onBack = {},
                    onOpenOrder = { id -> onNavigate(Routes.orderDetail(id)) },
                    tabIndex = if (tabs[tabIdx].content == "driverOpen") 0 else 1,
                    embedded = true,
                )
                else -> ProfileScreen(
                    container = container,
                    onBack = {},
                    onOpenFreight = { onNavigate(Routes.DRIVER_FREIGHT) },
                    onOpenAlerts = { onNavigate(Routes.ALERT_SETTINGS) },
                    onOpenBasicSettings = { onNavigate(Routes.BASIC_SETTINGS) },
                    embedded = true,
                )
            }
        }
    }

    // 通知权限没开 → 硬提示。文案与「我的 → 消息提醒」那张卡片同一个口径（说清"不做会怎样"），
    // 这里只是把它拦在**进门的门口**：不进设置页的用户从前一辈子看不到那句提醒。
    // 样式走共用件 CardAlertDialog（白卡那套弹窗语言的唯一落点），图标用语义色橙。
    if (showNotifyGuide) {
        CardAlertDialog(
            onDismissRequest = { showNotifyGuide = false },
            icon = {
                Icon(
                    Icons.Default.NotificationsOff,
                    contentDescription = null,
                    tint = Color(0xFFBC7730),
                )
            },
            title = { Text("手机上还没允许发通知") },
            text = {
                // ⚠️ 与「我的 → 消息提醒」那张卡片**逐字相同**的那句（两个入口一个口径）。
                Text("不开这个权限，派单来了手机上不会弹任何东西——只有打开 App 才看得到。")
            },
            confirmButton = {
                TextButton(onClick = {
                    showNotifyGuide = false
                    NotifyPermission.openSettings(permContext)
                }) { Text("去开启") }
            },
            dismissButton = {
                TextButton(onClick = { showNotifyGuide = false }) { Text("以后再说") }
            },
        )
    }
}
