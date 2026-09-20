package com.tapmoay.sorders.ui.nav

import android.widget.Toast
import androidx.compose.runtime.Composable
import kotlinx.coroutines.flow.drop
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.tapmoay.sorders.ai.AiContainer
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.Session
import com.tapmoay.sorders.ui.ai.AiChatScreen
import com.tapmoay.sorders.ui.ai.AiSettingsScreen
import com.tapmoay.sorders.ui.common.PlaceholderScreen
import com.tapmoay.sorders.ui.dispatcher.ExpensesScreen
import com.tapmoay.sorders.ui.dispatcher.ReceiptsScreen
import com.tapmoay.sorders.ui.dispatcher.SettlementsScreen
import com.tapmoay.sorders.ui.dispatcher.VehicleManageScreen
import com.tapmoay.sorders.ui.dispatcher.ArrearsUnitsScreen
import com.tapmoay.sorders.ui.dispatcher.DispatcherLedgerScreen
import com.tapmoay.sorders.ui.dispatcher.LedgerHomeScreen
import com.tapmoay.sorders.ui.dispatcher.FreightSettlementScreen
import com.tapmoay.sorders.ui.dispatcher.FreightTemplatesScreen
import com.tapmoay.sorders.ui.dispatcher.DriverBillingRulesScreen
import com.tapmoay.sorders.ui.driver.DriverFreightScreen
import com.tapmoay.sorders.ui.dispatcher.DispatcherOrdersScreen
import com.tapmoay.sorders.ui.dispatcher.DispatcherPoolScreen
import com.tapmoay.sorders.ui.dispatcher.InventoryScreen
import com.tapmoay.sorders.ui.dispatcher.ProductCategoriesScreen
import com.tapmoay.sorders.ui.dispatcher.ProductsScreen
import com.tapmoay.sorders.ui.dispatcher.UserPool
import com.tapmoay.sorders.ui.dispatcher.ReportDriverScreen
import com.tapmoay.sorders.ui.dispatcher.ReportExceptionScreen
import com.tapmoay.sorders.ui.dispatcher.ReportProductScreen
import com.tapmoay.sorders.ui.dispatcher.ReportCenterScreen
import com.tapmoay.sorders.ui.dispatcher.ReportHomeScreen
import com.tapmoay.sorders.ui.dispatcher.PriceAxis
import com.tapmoay.sorders.ui.dispatcher.PriceMatrixScreen
import com.tapmoay.sorders.ui.dispatcher.AccountManageScreen
import com.tapmoay.sorders.ui.dispatcher.UsersManageScreen
import com.tapmoay.sorders.ui.driver.DriverOrdersScreen
import com.tapmoay.sorders.ui.home.ModuleListScreen
import com.tapmoay.sorders.ui.home.RoleHomeScreen
import com.tapmoay.sorders.ui.login.LoginScreen
import com.tapmoay.sorders.ui.login.LoginScreen
import com.tapmoay.sorders.ui.messages.MessagesScreen
import com.tapmoay.sorders.ui.order.OrderDetailScreen
import com.tapmoay.sorders.ui.profile.AlertSettingsScreen
import com.tapmoay.sorders.ui.profile.ProfileScreen
import com.tapmoay.sorders.ui.shipper.AddressScreen
import com.tapmoay.sorders.ui.shipper.OrderCreateScreen
import com.tapmoay.sorders.ui.shipper.ShipperLedgerScreen
import com.tapmoay.sorders.ui.shipper.ShipperOrdersScreen

@Composable
fun AppRoot(container: AppContainer, initialSession: Session?) {
    val navController = rememberNavController()
    // AI 助手容器：一次会话只建一次，聊天页与设置页共用同一个实例（成员都是 lazy，构造本身很便宜）
    // ⚠️ 角色从 **cachedRole()（同步）** 读，而不是从 session（Compose 状态）读：
    // AiContainer 里的工具清单与权限判断都是同步路径，拿不到挂起函数。
    // cachedRole 由 TokenStore 在登录/登出时同步维护，两者不会不一致。
    val ai = remember { AiContainer(container.appContext, container.repo, roleKey = { container.tokenStore.cachedRole() }, userIdKey = { container.tokenStore.cachedUserId() }) }
    val session by container.tokenStore.sessionFlow.collectAsState(initial = initialSession)
    val loggedIn = session != null

    // 登录态变化时自动切换页面栈
    LaunchedEffect(loggedIn) {
        val route = navController.currentDestination?.route
        if (!loggedIn) {
            if (route != Routes.LOGIN) {
                navController.navigate(Routes.LOGIN) {
                    popUpTo(0) { inclusive = true }
                }
            }
        } else {
            if (route == Routes.LOGIN || route == null) {
                navController.navigate(Routes.HOME) {
                    popUpTo(0) { inclusive = true }
                }
            }
        }
    }

    // 登录失效时 Toast 提示（302 由 sessionFlow 自动回登录页）
    LaunchedEffect(Unit) {
        container.sessionExpiredTick.drop(1).collect {
            Toast.makeText(container.appContext, "登录已失效，请重新登录", Toast.LENGTH_LONG).show()
        }
    }

    // 点通知进来带的单号 → 直达订单详情。
    // 不做这一步的话，司机听到「来单了」点开通知，落到的是首页，
    // 还得自己在列表里翻出那一单——最要紧的那几秒就浪费在这里了。
    val pendingOrderId by container.pendingOrderId.collectAsState()
    LaunchedEffect(pendingOrderId, loggedIn) {
        val id = pendingOrderId
        if (id != null && id > 0 && loggedIn) {
            container.pendingOrderId.value = null
            // 记一条日志：这条链路（点通知 → 直达那一单）真机上曾经整条不生效而**没有任何表现**，
            // 没有日志就只能靠"再点一次看看"猜
            android.util.Log.i(
                com.tapmoay.sorders.core.NewOrderPlayer.TAG,
                "通知单号 $id → 跳转订单详情",
            )
            navController.navigate(Routes.orderDetail(id))
        }
    }

    NavHost(
        navController = navController,
        startDestination = if (loggedIn) Routes.HOME else Routes.LOGIN,
    ) {
        composable(Routes.LOGIN) {
            LoginScreen(
                container = container,
                onLoginSuccess = { _ -> /* sessionFlow 触发自动导航 */ },
            )
        }
        composable(Routes.HOME) {
            RoleHomeScreen(
                container = container,
                onNavigate = { r -> navController.navigate(r) },
            )
        }
        composable(Routes.PROFILE) {
            ProfileScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onOpenMessages = { navController.navigate(Routes.MESSAGES) },
                onOpenFreight = { navController.navigate(Routes.DRIVER_FREIGHT) },
                onOpenAlerts = { navController.navigate(Routes.ALERT_SETTINGS) },
            )
        }
        composable(Routes.ALERT_SETTINGS) {
            AlertSettingsScreen(
                container = container,
                onBack = { navController.popBackStack() },
            )
        }
        composable(Routes.MESSAGES) {
            MessagesScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onOpenOrder = { id -> navController.navigate(Routes.orderDetail(id)) },
            )
        }
        composable(Routes.SHIPPER_ORDERS) {
            ShipperOrdersScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onOpenOrder = { id -> navController.navigate(Routes.orderDetail(id)) },
                onCreateOrder = { navController.navigate(Routes.ORDER_CREATE) },
            )
        }
        composable(Routes.ORDER_CREATE) {
            OrderCreateScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onCreated = { navController.popBackStack() },
            )
        }
        composable(Routes.DISPATCH_ORDER_CREATE) {
            OrderCreateScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onCreated = { navController.popBackStack() },
                proxyMode = true,
            )
        }
        composable(
            route = Routes.ORDER_DETAIL,
            arguments = listOf(navArgument("orderId") { type = NavType.LongType }),
        ) { entry ->
            val id = entry.arguments?.getLong("orderId") ?: 0L
            OrderDetailScreen(
                container = container,
                orderId = id,
                onBack = { navController.popBackStack() },
            )
        }
        composable(Routes.ADDRESSES) {
            AddressScreen(container = container, onBack = { navController.popBackStack() })
        }
        composable(Routes.SHIPPER_LEDGER) {
            ShipperLedgerScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onOpenOrder = { id -> navController.navigate(Routes.orderDetail(id)) },
            )
        }
        composable(Routes.DRIVER_ORDERS) {
            DriverOrdersScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onOpenOrder = { id -> navController.navigate(Routes.orderDetail(id)) },
            )
        }
        composable(Routes.DISPATCH_POOL) {
            DispatcherPoolScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onOpenOrder = { id -> navController.navigate(Routes.orderDetail(id)) },
            )
        }
        composable(Routes.DISPATCH_ORDERS) {
            DispatcherOrdersScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onOpenOrder = { id -> navController.navigate(Routes.orderDetail(id)) },
            )
        }
        composable(Routes.ACCOUNTS) {
            AccountManageScreen(container = container, onBack = { navController.popBackStack() })
        }
        composable(Routes.DISPATCH_DRIVERS) {
            UsersManageScreen(
                container,
                UserPool.DRIVERS,
                onBack = { navController.popBackStack() },
                // 司机与车辆的绑定就发生在这一屏（卡片上的「配车」），
                // 但整支车队的管理（改车牌/停用/谁还没绑车）在车辆管理页——
                // 两个入口指向同一个接口，只是视角不同（"张三开哪辆" vs "这辆归谁"）。
                onOpenVehicles = { navController.navigate(Routes.DISPATCH_VEHICLES) },
            )
        }
        composable(Routes.SHIPPERS_MANAGE) {
            UsersManageScreen(container, UserPool.SHIPPERS, onBack = { navController.popBackStack() })
        }
        composable(Routes.PRODUCTS) {
            ProductsScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onOpenCategories = { navController.navigate(Routes.PRODUCT_CATEGORIES) },
                // 「这个商品卖给每家批发商多少钱」——价格矩阵的另一个方向（2026-09-19 新增）
                onOpenPricing = { pid -> navController.navigate(Routes.priceByProduct(pid)) },
            )
        }
        composable(Routes.PRODUCT_CATEGORIES) {
            ProductCategoriesScreen(container = container, onBack = { navController.popBackStack() })
        }
        composable(Routes.INVENTORY) {
            InventoryScreen(container = container, onBack = { navController.popBackStack() })
        }
        composable(Routes.ARREARS_UNITS) {
            ArrearsUnitsScreen(container = container, onBack = { navController.popBackStack() })
        }
        composable(Routes.MEMBERS) {
            UsersManageScreen(
                container,
                UserPool.MEMBERS,
                onBack = { navController.popBackStack() },
                onOpenPricing = { u ->
                    navController.navigate(Routes.priceByShipper(u.id))
                },
            )
        }
        // 价格矩阵的两个方向（同一页实现，见 PriceMatrixScreen 的注释）
        composable(
            route = Routes.PRICE_BY_SHIPPER,
            arguments = listOf(navArgument("shipperId") { type = NavType.LongType }),
        ) { entry ->
            PriceMatrixScreen(
                container = container,
                axis = PriceAxis.BY_SHIPPER,
                focusId = entry.arguments?.getLong("shipperId") ?: 0L,
                onBack = { navController.popBackStack() },
            )
        }
        composable(
            route = Routes.PRICE_BY_PRODUCT,
            arguments = listOf(navArgument("productId") { type = NavType.LongType }),
        ) { entry ->
            PriceMatrixScreen(
                container = container,
                axis = PriceAxis.BY_PRODUCT,
                focusId = entry.arguments?.getLong("productId") ?: 0L,
                onBack = { navController.popBackStack() },
            )
        }
        // 「账本管理」**入口页**（工作台网格上那一格）：报表中心那种形式，里面 6 件事。
        // 它是入口，不是账本页本身 —— 账本页在下面那条 `?tab=` 的路由上（只管看账）。
        composable(Routes.LEDGER_HOME) {
            LedgerHomeScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onOpen = { route -> navController.navigate(route) },
            )
        }
        // 账本页支持 `?tab=` 直达某一类账（账本管理入口页里的 4 格用它）。
        // 4 类账是**同一页的四个档位**，所以这里一条路由带一个参数就够了，不要建四个页面。
        composable(
            route = Routes.DISPATCH_LEDGER + "?tab={tab}",
            arguments = listOf(navArgument("tab") { type = NavType.IntType; defaultValue = 0 }),
        ) { entry ->
            DispatcherLedgerScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onOpenOrder = { id -> navController.navigate(Routes.orderDetail(id)) },
                // 司机账那一档里的「司机结算单」入口（用户 2026-09-20：司机账与司机结算**合并成一个**）
                onOpenSettlements = { navController.navigate(Routes.DISPATCH_SETTLEMENTS) },
                initialTab = entry.arguments?.getInt("tab") ?: 0,
            )
        }
        composable(Routes.DISPATCH_RECEIPTS) { ReceiptsScreen(container = container, onBack = { navController.popBackStack() }) }
        composable(Routes.DISPATCH_SETTLEMENTS) { SettlementsScreen(container = container, onBack = { navController.popBackStack() }) }
        composable(Routes.DISPATCH_EXPENSES) { ExpensesScreen(container = container, onBack = { navController.popBackStack() }) }
        composable(Routes.DISPATCH_VEHICLES) { VehicleManageScreen(container = container, onBack = { navController.popBackStack() }) }
        composable(Routes.FREIGHT_TEMPLATES) { FreightTemplatesScreen(container = container, onBack = { navController.popBackStack() }) }
        composable(Routes.DRIVER_BILLING_RULES) { DriverBillingRulesScreen(container = container, onBack = { navController.popBackStack() }) }
        composable(Routes.FREIGHT_SETTLEMENT) {
            FreightSettlementScreen(
                container = container,
                onBack = { navController.popBackStack() },
                // 明细行点开的是**这一单的原始订单**（与司机端「我的账本」同一处落点）
                onOpenOrder = { id -> navController.navigate(Routes.orderDetail(id)) },
            )
        }
        composable(Routes.DRIVER_FREIGHT) {
            DriverFreightScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onOpenOrder = { id -> navController.navigate(Routes.orderDetail(id)) },
            )
        }
        composable(Routes.REPORT_HOME) {
            ReportHomeScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onOpen = { tab ->
                    when (tab) {
                        0 -> navController.navigate(Routes.REPORT_TURNOVER)
                        1 -> navController.navigate(Routes.REPORT_PRODUCT)
                        2 -> navController.navigate(Routes.REPORT_DRIVER)
                        3 -> navController.navigate(Routes.REPORT_CUSTOMER)
                        4 -> navController.navigate(Routes.REPORT_FINANCE)
                        else -> navController.navigate(Routes.REPORT_EXCEPTION)
                    }
                },
            )
        }
        composable(Routes.REPORT_TURNOVER) { ReportCenterScreen(container = container, onBack = { navController.popBackStack() }, initialTab = 0) }
        composable(Routes.REPORT_PRODUCT) { ReportCenterScreen(container = container, onBack = { navController.popBackStack() }, initialTab = 1) }
        composable(Routes.REPORT_DRIVER) { ReportCenterScreen(container = container, onBack = { navController.popBackStack() }, initialTab = 2) }
        composable(Routes.REPORT_CUSTOMER) { ReportCenterScreen(container = container, onBack = { navController.popBackStack() }, initialTab = 3) }
        composable(Routes.REPORT_FINANCE) { ReportCenterScreen(container = container, onBack = { navController.popBackStack() }, initialTab = 4) }
        composable(Routes.REPORT_EXCEPTION) { ReportCenterScreen(container = container, onBack = { navController.popBackStack() }, initialTab = 5) }
        composable(Routes.AI_CHAT) {
            AiChatScreen(
                ai = ai,
                onBack = { navController.popBackStack() },
                onOpenSettings = { navController.navigate(Routes.AI_SETTINGS) },
            )
        }
        composable(Routes.AI_SETTINGS) {
            AiSettingsScreen(
                ai = ai,
                onBack = { navController.popBackStack() },
            )
        }
        composable(
            route = Routes.MODULE_GROUP + "/{groupKey}",
            arguments = listOf(navArgument("groupKey") { type = NavType.StringType }),
        ) { entry ->
            val key = entry.arguments?.getString("groupKey") ?: ""
            val group = Modules.findGroup(Routes.MODULE_GROUP + "/" + key)
            if (group != null) {
                ModuleListScreen(
                    title = group.label,
                    entries = group.children,
                    onBack = { navController.popBackStack() },
                    onOpen = { r -> navController.navigate(r) },
                )
            }
        }
    }
}