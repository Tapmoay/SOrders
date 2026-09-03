package com.tapmoay.sorders.ui.home

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.ui.messages.MessagesScreen
import com.tapmoay.sorders.ui.common.LoadingBox
import com.tapmoay.sorders.ui.nav.Modules
import com.tapmoay.sorders.ui.nav.Role
import com.tapmoay.sorders.ui.dispatcher.DispatcherPoolScreen
import com.tapmoay.sorders.ui.driver.DriverOrdersScreen
import com.tapmoay.sorders.ui.nav.Routes
import com.tapmoay.sorders.ui.profile.ProfileScreen

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
    val permLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { grants ->
        // 定位权限授予（或已授予）→ 预热定位：地图选点打开即跳当前位置，无需等待
        val locOk = grants[Manifest.permission.ACCESS_FINE_LOCATION] == true ||
                grants[Manifest.permission.ACCESS_COARSE_LOCATION] == true
        if (locOk) container.locationManager.requestSingle()
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
            add(Manifest.permission.CAMERA)
        }.filter {
            ContextCompat.checkSelfPermission(permContext, it) != PackageManager.PERMISSION_GRANTED
        }
        if (perms.isNotEmpty()) {
            permLauncher.launch(perms.toTypedArray())
        } else {
            // 权限齐全：直接预热定位（地图选点秒定位）
            container.locationManager.requestSingle()
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

    Scaffold(
        bottomBar = {
            NavigationBar {
                tabs.forEachIndexed { i, tab ->
                    NavigationBarItem(
                        selected = tabIdx == i,
                        onClick = { selectedTab = i },
                        icon = {
                            if (tab.content == "messages" && unread > 0) {
                                BadgedBox(
                                    badge = {
                                        Badge { Text(if (unread > 99) "99+" else unread.toString()) }
                                    }
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
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
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
                    onOpenOrder = { id -> onNavigate(Routes.orderDetail(id)) },
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
                    onOpenMessages = {
                        val msgIdx = tabs.indexOfFirst { it.content == "messages" }
                        if (msgIdx >= 0) selectedTab = msgIdx else onNavigate(Routes.MESSAGES)
                    },
                    onOpenFreight = { onNavigate(Routes.DRIVER_FREIGHT) },
                    embedded = true,
                )
            }
        }
    }
}
