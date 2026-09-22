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
import com.tapmoay.sorders.ui.dispatcher.ExpenseCategoriesScreen
import com.tapmoay.sorders.ui.dispatcher.ExpenseCreateScreen
import com.tapmoay.sorders.ui.dispatcher.ExpensesScreen
import com.tapmoay.sorders.ui.dispatcher.ReceiptsScreen
import com.tapmoay.sorders.ui.dispatcher.SettlementsScreen
import com.tapmoay.sorders.ui.dispatcher.VehicleManageScreen
import com.tapmoay.sorders.ui.dispatcher.ArrearsUnitsScreen
import com.tapmoay.sorders.ui.dispatcher.DispatcherLedgerScreen
import com.tapmoay.sorders.ui.dispatcher.LedgerCreateScreen
import com.tapmoay.sorders.ui.dispatcher.LedgerHomeScreen
import com.tapmoay.sorders.ui.dispatcher.LedgerCashScreen
import com.tapmoay.sorders.ui.dispatcher.LedgerCashDetailScreen
import com.tapmoay.sorders.ui.dispatcher.OrderTemplatesScreen
// 供应商 / 厂商档案 + 一个供应商的账（2026-09-22）
import com.tapmoay.sorders.ui.dispatcher.SupplierDetailScreen
import com.tapmoay.sorders.ui.dispatcher.SuppliersScreen
import com.tapmoay.sorders.ui.dispatcher.FreightSettlementScreen
import com.tapmoay.sorders.ui.dispatcher.FreightCategoriesScreen
import com.tapmoay.sorders.ui.dispatcher.UnpricedOrdersScreen
import com.tapmoay.sorders.ui.dispatcher.FreightTemplatesScreen
import com.tapmoay.sorders.ui.dispatcher.DriverBillingRulesScreen
import com.tapmoay.sorders.ui.driver.DriverFreightScreen
import com.tapmoay.sorders.ui.dispatcher.DispatcherOrdersScreen
import com.tapmoay.sorders.ui.dispatcher.DispatcherReturnRequestsScreen
import com.tapmoay.sorders.ui.dispatcher.InventoryScreen
import com.tapmoay.sorders.ui.dispatcher.ProductBatchScreen
import com.tapmoay.sorders.ui.dispatcher.ProductSortScreen
import com.tapmoay.sorders.ui.dispatcher.ProductCategoriesScreen
import com.tapmoay.sorders.ui.dispatcher.ProductFormScreen
import com.tapmoay.sorders.ui.dispatcher.ProductsScreen
import com.tapmoay.sorders.ui.dispatcher.UserPool
import com.tapmoay.sorders.ui.dispatcher.ReportCenterScreen
import com.tapmoay.sorders.ui.dispatcher.ReportHomeScreen
import com.tapmoay.sorders.ui.dispatcher.PriceAxis
import com.tapmoay.sorders.ui.dispatcher.PriceMatrixScreen
import com.tapmoay.sorders.ui.dispatcher.AccountManageScreen
import com.tapmoay.sorders.ui.dispatcher.UsersManageScreen
import com.tapmoay.sorders.ui.driver.DriverOrdersScreen
import com.tapmoay.sorders.ui.home.RoleHomeScreen
import com.tapmoay.sorders.ui.login.LoginScreen
import com.tapmoay.sorders.ui.login.LoginScreen
import com.tapmoay.sorders.ui.messages.MessagesScreen
import com.tapmoay.sorders.ui.order.OrderDetailScreen
import com.tapmoay.sorders.ui.profile.AlertSettingsScreen
import com.tapmoay.sorders.ui.profile.BasicSettingsScreen
import com.tapmoay.sorders.ui.shipper.AddressScreen
import com.tapmoay.sorders.ui.shipper.OrderCreateScreen
import com.tapmoay.sorders.ui.shipper.ShipperLedgerScreen
import com.tapmoay.sorders.ui.shipper.ShipperOrdersScreen
import com.tapmoay.sorders.ui.shipper.ShipperReturnRequestsScreen

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
        composable(Routes.ALERT_SETTINGS) {
            AlertSettingsScreen(
                container = container,
                onBack = { navController.popBackStack() },
            )
        }
        // 基础设置（「我的」第二层）：随日落 / 夜间模式 / 提示
        composable(Routes.BASIC_SETTINGS) {
            BasicSettingsScreen(
                container = container,
                onBack = { navController.popBackStack() },
            )
        }
        composable(Routes.MESSAGES) {
            MessagesScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onOpenOrder = { id -> navController.navigate(Routes.orderDetail(id)) },
                // 退货申请类通知**直达那一页并定位那一条**（2026-09-21 用户要求：
                // 「到消息中心哦。其实本来就要做到直达的」）。路由由消息页按
                // 「type + 当前角色」在一处算好（`ui/messages/NoticeRouting.kt`），
                // 这里只负责导航 —— 与「账本管理入口页」的 `onOpen` 同一个写法。
                onOpenReturnRequest = { route -> navController.navigate(route) },
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
        // 代理下单页支持 `?template=` —— 从「预订单」页点「用这张下单」进来时，
        // 商品与数量（以及货主/地址/收货人/备注）按那张预设单预填；**参数仍然可改**。
        // ⚠️ 默认 0 = 没有预设单（普通进法），老入口一行都不用改。
        composable(
            route = Routes.DISPATCH_ORDER_CREATE + "?template={template}",
            arguments = listOf(navArgument("template") { type = NavType.LongType; defaultValue = 0L }),
        ) { entry ->
            OrderCreateScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onCreated = { navController.popBackStack() },
                proxyMode = true,
                prefillTemplateId = entry.arguments?.getLong("template") ?: 0L,
            )
        }
        // 「预订单」管理页（2026-09-22 用户要求「专门去管理预设的订单」）。
        // ⛔ 这一页**不生成订单**：它只把参数带进上面的下单页。
        composable(Routes.DISPATCH_ORDER_TEMPLATES) {
            OrderTemplatesScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onPlaceOrder = { t ->
                    navController.navigate(Routes.DISPATCH_ORDER_CREATE + "?template=" + t.id)
                },
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
        // 「我的退货申请」（2026-09-21）：货主在订单上提的申请在这里看进展、可以撤回。
        // ⛔ 货主只能申请 —— 真正退货在下面派单端那条路由上。
        //
        // `?focus={focusId}`（2026-09-21 追加）：从消息中心点「退货已办理/被驳回/已关闭」
        // 那条站内信进来时带的是**哪一张申请**。参数有默认值 → 不带 focus 的老入口
        // （工作台网格那一格走 `Routes.SHIPPER_RETURN_REQUESTS` 本身）照旧能用，不要另建路由。
        composable(
            route = Routes.SHIPPER_RETURN_REQUESTS + "?focus={focusId}",
            arguments = listOf(navArgument("focusId") { type = NavType.LongType; defaultValue = 0L }),
        ) { entry ->
            ShipperReturnRequestsScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onOpenOrder = { id -> navController.navigate(Routes.orderDetail(id)) },
                focusRequestId = entry.arguments?.getLong("focusId") ?: 0L,
            )
        }
        composable(Routes.DRIVER_ORDERS) {
            DriverOrdersScreen(
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
        // 「退货申请」待办页（2026-09-21）：★ 在这一页点「办理退货」才是**真的退货** ——
        // 库存、账本、退款、订单状态都在那一刻才变（货主那边只是提了一张申请）。
        //
        // `?focus={focusId}`（2026-09-21 追加）：点消息中心里「退货申请待处理」那条通知
        // 直接落在这里并定位到那一张（payload 的 `request_id`）。不带 focus 的入口
        // （工作台那一格）照旧走 `Routes.DISPATCH_RETURN_REQUESTS` 本身。
        composable(
            route = Routes.DISPATCH_RETURN_REQUESTS + "?focus={focusId}",
            arguments = listOf(navArgument("focusId") { type = NavType.LongType; defaultValue = 0L }),
        ) { entry ->
            DispatcherReturnRequestsScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onOpenOrder = { id -> navController.navigate(Routes.orderDetail(id)) },
                focusRequestId = entry.arguments?.getLong("focusId") ?: 0L,
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
                // 新增（null）/ 编辑某一个：**单独一页**，存好之后回退，
                // 列表页的 `LaunchedEffect(Unit)` 会重新拉一次，所以刚存的立刻看得到。
                onOpenForm = { pid -> navController.navigate(Routes.productForm(pid)) },
                // 底栏第三格「批量操作」（2026-09-21，用户点名要的三格之一）
                onOpenBatch = { navController.navigate(Routes.PRODUCT_BATCH) },
                // 顶栏右上角「排序」→ 商品排序页（用户：「那个排序你没加啊」）
                onOpenSort = { navController.navigate(Routes.PRODUCT_SORT) },
            )
        }
        composable(Routes.PRODUCT_BATCH) {
            ProductBatchScreen(container = container, onBack = { navController.popBackStack() })
        }
        composable(Routes.PRODUCT_SORT) {
            ProductSortScreen(container = container, onBack = { navController.popBackStack() })
        }
        // 新增 / 编辑商品：一条路由两个用法（`?productId=` 缺省 = 新增）。
        // ⚠️ 与「账本 4 类账」同一个套路：**同一页的两个档位就一条路由**，不要建两个页面。
        composable(
            route = Routes.PRODUCT_FORM + "?productId={productId}",
            arguments = listOf(navArgument("productId") { type = NavType.LongType; defaultValue = 0L }),
        ) { entry ->
            val pid = entry.arguments?.getLong("productId") ?: 0L
            ProductFormScreen(
                container = container,
                productId = if (pid > 0L) pid else null,
                onBack = { navController.popBackStack() },
                // 「各批发商价格」现在是编辑页里的一行（原来在商品卡的 ⋮ 菜单里，
                // 用户 2026-09-21 要求把 ⋮ 的功能搬进编辑页）
                onOpenPricing = { id -> navController.navigate(Routes.priceByProduct(id)) },
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
        // ⛔ 页内**没有**切换档位的入口了（用户 2026-09-20：「最上面的 4 个去掉，那是老的导航栏」），
        //    所以这个参数就是"这一页是哪一本账"，进来之后不再变。
        // ⛔ 这里**没有** `onOpenSettlements` 了：司机结算单不再挂在司机账页面里（用户：
        //    「那个结算，这个也直接去掉」），它从工作台那一格（`Routes.FREIGHT_SETTLEMENT`）进。
        composable(
            route = Routes.DISPATCH_LEDGER + "?tab={tab}",
            arguments = listOf(navArgument("tab") { type = NavType.IntType; defaultValue = 0 }),
        ) { entry ->
            DispatcherLedgerScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onOpenOrder = { id -> navController.navigate(Routes.orderDetail(id)) },
                initialTab = entry.arguments?.getInt("tab") ?: 0,
                // 「记一笔账」= 单独一页（选商品要走商品库那一份 UI，弹窗里套不下）；
                // 存好之后回退，账本页自己会重新拉一次（见 DispatcherLedgerScreen 的 LaunchedEffect）
                onCreateEntry = { navController.navigate(Routes.LEDGER_CREATE) },
            )
        }
        composable(Routes.LEDGER_CREATE) {
            LedgerCreateScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onSaved = { navController.popBackStack() },
            )
        }
        composable(Routes.DISPATCH_RECEIPTS) { ReceiptsScreen(container = container, onBack = { navController.popBackStack() }) }
        composable(Routes.DISPATCH_SETTLEMENTS) { SettlementsScreen(container = container, onBack = { navController.popBackStack() }) }
        // 「收支」（2026-09-22）：账本管理入口页那一格 —— 收入按来源、支出按去路各一路一行。
        // 「开销管理」从这一页的支出卡底部进（它不再与这一页并列占一格）。
        composable(Routes.DISPATCH_CASH) {
            LedgerCashScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onOpenDetail = { direction, biz, from, to ->
                    navController.navigate(
                        Routes.DISPATCH_CASH_DETAIL +
                            "?direction=" + direction + "&biz=" + biz +
                            "&from=" + from.orEmpty() + "&to=" + to.orEmpty(),
                    )
                },
                onOpenExpenses = { navController.navigate(Routes.DISPATCH_EXPENSES) },
                onOpenSuppliers = { navController.navigate(Routes.DISPATCH_SUPPLIERS) },
            )
        }
        // 「供应商 / 厂商」档案页（2026-09-22）：账本管理入口页那一格 +「收支」页支出卡底部。
        // 拍板口径是"跟客户一个量级的档案"：可挂账、可查还欠多少、可分次付款。
        composable(Routes.DISPATCH_SUPPLIERS) {
            SuppliersScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onOpenDetail = { id -> navController.navigate(Routes.supplierDetail(id)) },
            )
        }
        // 一个供应商的账（编号走查询参数，见 `Routes.DISPATCH_SUPPLIER_DETAIL`）。
        composable(
            route = Routes.DISPATCH_SUPPLIER_DETAIL + "?supplierId={supplierId}",
            arguments = listOf(navArgument("supplierId") { type = NavType.LongType; defaultValue = 0L }),
        ) { entry ->
            val id = entry.arguments?.getLong("supplierId") ?: 0L
            if (id > 0) {
                SupplierDetailScreen(
                    container = container,
                    supplierId = id,
                    onBack = { navController.popBackStack() },
                )
            }
        }
        // 某一类流水的明细。窗口四个参数都由总览页带过来（⛔ 不在这里再挑一次时间）。
        composable(
            route = Routes.DISPATCH_CASH_DETAIL + "?direction={direction}&biz={biz}&from={from}&to={to}",
            arguments = listOf(
                navArgument("direction") { type = NavType.StringType; defaultValue = "out" },
                navArgument("biz") { type = NavType.StringType; defaultValue = "" },
                navArgument("from") { type = NavType.StringType; defaultValue = "" },
                navArgument("to") { type = NavType.StringType; defaultValue = "" },
            ),
        ) { entry ->
            LedgerCashDetailScreen(
                container = container,
                direction = entry.arguments?.getString("direction") ?: "out",
                bizType = entry.arguments?.getString("biz").orEmpty(),
                // 空串 = 「全部」那一档（查询参数传不了 null，所以两边都认这一条）
                dateFrom = entry.arguments?.getString("from").orEmpty().ifBlank { null },
                dateTo = entry.arguments?.getString("to").orEmpty().ifBlank { null },
                onBack = { navController.popBackStack() },
                onOpenOrder = { id -> navController.navigate(Routes.orderDetail(id)) },
            )
        }
        // 开销管理（2026-09-20 重写）：分类栏 + 时间药丸 + 卡片；底部两个按钮各去一页。
        composable(Routes.DISPATCH_EXPENSES) {
            ExpensesScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onOpenOrder = { id -> navController.navigate(Routes.orderDetail(id)) },
                onCreate = { navController.navigate(Routes.EXPENSE_CREATE) },
                onManageCategories = { navController.navigate(Routes.EXPENSE_CATEGORIES) },
            )
        }
        // 新增开销 = 单独一页；存好之后**回退**到开销页（列表页在 onResume 之外不会自己刷新，
        // 所以回来那一下要靠它自己重新拉一次 —— 见 ExpensesScreen 的 LaunchedEffect 说明）
        composable(Routes.EXPENSE_CREATE) {
            ExpenseCreateScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onSaved = { navController.popBackStack() },
            )
        }
        composable(Routes.EXPENSE_CATEGORIES) {
            ExpenseCategoriesScreen(container = container, onBack = { navController.popBackStack() })
        }
        composable(Routes.DISPATCH_VEHICLES) { VehicleManageScreen(container = container, onBack = { navController.popBackStack() }) }
        composable(Routes.FREIGHT_TEMPLATES) {
            FreightTemplatesScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onManageCategories = { navController.navigate(Routes.FREIGHT_CATEGORIES) },
                onOpenUnpriced = { navController.navigate(Routes.FREIGHT_UNPRICED) },
            )
        }
        composable(Routes.FREIGHT_CATEGORIES) {
            FreightCategoriesScreen(container = container, onBack = { navController.popBackStack() })
        }
        composable(Routes.FREIGHT_UNPRICED) {
            UnpricedOrdersScreen(
                container = container,
                onBack = { navController.popBackStack() },
                onOpenOrder = { id -> navController.navigate(Routes.orderDetail(id)) },
            )
        }
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
        // ⛔ 2026-09-20 删掉了 `moduleGroup/{groupKey}` 这条路由（连同 `Modules.findGroup`
        //    与 `ModuleListScreen`）：三端都没有任何一格带 `children`，所以**没有任何入口
        //    导航得到这里** —— 一条走不到的路由留着，只会让下一个人以为工作台支持分组。
    }
}