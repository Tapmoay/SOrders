package com.tapmoay.sorders.ui.nav

import android.widget.Toast
import androidx.compose.runtime.Composable
import kotlinx.coroutines.flow.drop
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.Session
import com.tapmoay.sorders.ui.common.PlaceholderScreen
import com.tapmoay.sorders.ui.dispatcher.ExpensesScreen
import com.tapmoay.sorders.ui.dispatcher.ReceiptsScreen
import com.tapmoay.sorders.ui.dispatcher.SettlementsScreen
import com.tapmoay.sorders.ui.dispatcher.VehiclesScreen
import com.tapmoay.sorders.ui.dispatcher.ArrearsUnitsScreen
import com.tapmoay.sorders.ui.dispatcher.DispatcherLedgerScreen
import com.tapmoay.sorders.ui.dispatcher.FreightSettlementScreen
import com.tapmoay.sorders.ui.dispatcher.FreightTemplatesScreen
import com.tapmoay.sorders.ui.driver.DriverFreightScreen
import com.tapmoay.sorders.ui.dispatcher.DispatcherOrdersScreen
import com.tapmoay.sorders.ui.dispatcher.DispatcherPoolScreen
import com.tapmoay.sorders.ui.dispatcher.InventoryScreen
import com.tapmoay.sorders.ui.dispatcher.ProductsScreen
import com.tapmoay.sorders.ui.dispatcher.UserPool
import com.tapmoay.sorders.ui.dispatcher.ReportDriverScreen
import com.tapmoay.sorders.ui.dispatcher.ReportExceptionScreen
import com.tapmoay.sorders.ui.dispatcher.ReportProductScreen
import com.tapmoay.sorders.ui.dispatcher.ReportCenterScreen
import com.tapmoay.sorders.ui.dispatcher.ReportHomeScreen
import com.tapmoay.sorders.ui.dispatcher.WholesalePricingScreen
import com.tapmoay.sorders.ui.dispatcher.UsersManageScreen
import com.tapmoay.sorders.ui.driver.DriverOrdersScreen
import com.tapmoay.sorders.ui.home.ModuleListScreen
import com.tapmoay.sorders.ui.home.RoleHomeScreen
import com.tapmoay.sorders.ui.login.LoginScreen
import com.tapmoay.sorders.ui.login.RegisterScreen
import com.tapmoay.sorders.ui.messages.MessagesScreen
import com.tapmoay.sorders.ui.order.OrderDetailScreen
import com.tapmoay.sorders.ui.profile.ProfileScreen
import com.tapmoay.sorders.ui.shipper.AddressScreen
import com.tapmoay.sorders.ui.shipper.OrderCreateScreen
import com.tapmoay.sorders.ui.shipper.ShipperLedgerScreen
import com.tapmoay.sorders.ui.shipper.ShipperOrdersScreen

@Composable
fun AppRoot(container: AppContainer, initialSession: Session?) {
    val navController = rememberNavController()
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
            if (route == Routes.LOGIN || route == Routes.REGISTER || route == null) {
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

    NavHost(
        navController = navController,
        startDestination = if (loggedIn) Routes.HOME else Routes.LOGIN,
    ) {
        composable(Routes.LOGIN) {
            LoginScreen(
                container = container,
                onLoginSuccess = { _ -> /* sessionFlow 触发自动导航 */ },
                onGoRegister = { navController.navigate(Routes.REGISTER) },
            )
        }
        composable(Routes.REGISTER) {
            RegisterScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onRegisterSuccess = { _ -> /* sessionFlow 触发自动导航 */ },
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
        composable(Routes.DISPATCH_DRIVERS) {
            UsersManageScreen(container, UserPool.DRIVERS, onBack = { navController.popBackStack() })
        }
        composable(Routes.SHIPPERS_MANAGE) {
            UsersManageScreen(container, UserPool.SHIPPERS, onBack = { navController.popBackStack() })
        }
        composable(Routes.PRODUCTS) {
            ProductsScreen(container = container, onBack = { navController.popBackStack() })
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
                    navController.navigate(Routes.wholesalePricing(u.id))
                },
            )
        }
        composable(
            route = Routes.WHOLESALE_PRICING,
            arguments = listOf(navArgument("shipperId") { type = NavType.LongType }),
        ) { entry ->
            val sid = entry.arguments?.getLong("shipperId") ?: 0L
            WholesalePricingScreen(
                container = container,
                shipperId = sid,
                onBack = { navController.popBackStack() },
            )
        }
        composable(Routes.DISPATCH_LEDGER) {
            DispatcherLedgerScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onOpenOrder = { id -> navController.navigate(Routes.orderDetail(id)) },
                onOpenReceipts = { navController.navigate(Routes.DISPATCH_RECEIPTS) },
                onOpenSettlements = { navController.navigate(Routes.DISPATCH_SETTLEMENTS) },
                onOpenExpenses = { navController.navigate(Routes.DISPATCH_EXPENSES) },
                onOpenVehicles = { navController.navigate(Routes.DISPATCH_VEHICLES) },
            )
        }
        composable(Routes.DISPATCH_RECEIPTS) { ReceiptsScreen(container = container, onBack = { navController.popBackStack() }) }
        composable(Routes.DISPATCH_SETTLEMENTS) { SettlementsScreen(container = container, onBack = { navController.popBackStack() }) }
        composable(Routes.DISPATCH_EXPENSES) { ExpensesScreen(container = container, onBack = { navController.popBackStack() }) }
        composable(Routes.DISPATCH_VEHICLES) { VehiclesScreen(container = container, onBack = { navController.popBackStack() }) }
        composable(Routes.FREIGHT_TEMPLATES) { FreightTemplatesScreen(container = container, onBack = { navController.popBackStack() }) }
        composable(Routes.FREIGHT_SETTLEMENT) { FreightSettlementScreen(container = container, onBack = { navController.popBackStack() }) }
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
        composable(Routes.REPORT_EXCEPTION) { ReportCenterScreen(container = container, onBack = { navController.popBackStack() }, initialTab = 3) }
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