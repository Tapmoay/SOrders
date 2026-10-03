package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.UserDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.*
import kotlinx.coroutines.launch

/**
 * **状态档**的下标色（与 `AccountManageViewModel.ACCOUNT_STATUS_TABS` 一一对应）：
 * 全部 · 蓝、在用 · 绿、已停用 · 橙、已删除 · 红。
 *
 * 取的全是**本页卡片动作已经在用的那几个语义色**（`ui/theme/Color.kt` 的常量，不另调一份新的）：
 * 绿 = 「启用」（在册可用）、橙 = 「停用」（暂停，还能启用回来）、红 = 「删除」（不可逆那一档）。
 * ⛔ 与 `ACCOUNT_STATUS_TABS` 一样**只能往后加档** —— 这一份是**按下标取色**的，
 *    插在中间会把后面每一格的颜色顶掉，而且没有一处会报错（只会看到"已删除"变灰）。
 */
private val ACCOUNT_STATUS_COLORS = listOf(
    Color(NavBlue),      // 0 全部
    Color(MgrGreen),     // 1 在用
    Color(MoneyOrange),  // 2 已停用
    Color(MessageRed),   // 3 已删除
)

/**
 * # 账户管理（派单员统一建号：账号 + 密码 + 角色）
 *
 * ## 这一页 2026-09-22 改了什么、为什么
 * 用户原话：「那你**更改一下账户管理的卡片样式**按照要求进行更改，同时他那个**新增的那个弹窗**也就
 * **底部抽屉**呃也采用**不要使用那个线框**而是**用卡片的形式**」。
 *
 * 改动落在两处：
 * 1. **列表卡**：原来是「两行文字 + 一排四个字按钮」，现在按全库正在统一的那套卡片语言重排 ——
 *    姓名 + 角色徽章 + 状态徽章在**同一行**（用户 2026-09-21 对「我的」页的原话：
 *    「不要做两排…就跟那个版本号一样」）、手机号另起一行（**长按可复制**，与订单号同一个手势）、
 *    底部动作行**左＝相反/警示、右＝编辑**（用户 2026-09-22：「编辑一定在右边…因为我们的惯用手是
 *    右手…相反的操作就在左边」）。
 * 2. **新增/编辑抽屉**：`OutlinedTextField` 三个描边框全部去掉，换成
 *    `ui/common/FormRows.kt` 的无边框行 + `SectionCard` 白卡分组（规范见
 *    `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md` §5.0「分组一律白卡」，判据 `_check_form_panel_style.py`）。
 *
 * ⛔ 抽屉**底色**不在这一页改：那是 `ui/theme/Color.kt::SheetSurface` 一处说了算的
 *    （M3 的 `ModalBottomSheet` 容器默认读 `surfaceContainerLow`，19 个抽屉一起动）。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AccountManageScreen(
    container: AppContainer,
    onBack: () -> Unit,
) {
    val vm: AccountManageViewModel = appViewModel { AccountManageViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    val ctx = LocalContext.current

    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })

    // ---- 左栏分类（2026-10-05）----
    //
    // 用户原话：「还有我们的账户管理司机管理货主管理批发商管理。车辆管理……在这个位置也加个分类，
    // 默认是显示，全部，同样也是左边侧边栏，然后左边侧边栏同样也是可以新增分类的，
    // 那个左边侧分栏的底下，凡是跟地点是同样的」。
    //
    // 形态照「地址与联系人」：**抽屉**（⛔ 不是商品管理那种常驻左栏 —— 用户 2026-09-19 对那一种的
    // 裁定是「右边的卡片的信息被挤压了不是很好看」）。抽屉底部那格「管理分类」进分类管理面板。
    val drawer = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    val catVm: UserCategoriesViewModel = appViewModel { UserCategoriesViewModel(container) }
    var managingCategory by remember { mutableStateOf(false) }

    ModalNavigationDrawer(
        drawerState = drawer,
        drawerContent = {
            ModalDrawerSheet(modifier = Modifier.width(CategoryDrawerWidth)) {
                CategoryDrawerSheet(
                    title = "账号分类",
                    // ⛔ 一格都不显示条数（用户 2026-09-19：「那个分组下面不要显示有多少条啊，
                    //    这是多余信息」）—— 条数只在「管理分类」那个面板里出现。
                    items = listOf(CategoryDrawerItem("", "全部")) +
                        catVm.rows.map { CategoryDrawerItem("c|" + it.name, it.name) },
                    selectedKey = vm.railKey,
                    accent = Color(AccountBrown),
                    manageLabel = "管理分类",
                    onPick = { key ->
                        vm.railKey = key
                        scope.launch { drawer.close() }
                    },
                    onManage = {
                        managingCategory = true
                        scope.launch { drawer.close() }
                    },
                )
            }
        },
    ) {
    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = { Text("账户管理") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    // 用户画的那个红框位置：标题右边那一格 —— 默认「全部」。
                    // 落位（用户 2026-10-05）：顶栏右边**空着**的页面，胶囊贴到右侧，
                    // 右缘与下面的卡片对齐 —— `actions` 自带 4dp 右边距，这里再补 12dp
                    // = 卡片的 16dp 内边距。⛔ 右边已经有按钮的页面保持原样、继续贴着标题
                    // （用户原话：「如果右边有东西的话，则就保持原样」—— 见司机 / 批发商那两池）。
                    CategoryTriggerChip(
                        current = railNameOf(vm.railKey),
                        // 账户管理的**模块色**（棕）= 工作台那一格的颜色，不再借地址页的湖蓝。
                        accent = Color(AccountBrown),
                        onClick = { scope.launch { drawer.open() } },
                        modifier = Modifier.padding(end = 12.dp),
                    )
                },
                // 与其余派单端页面同一个口径（顶栏跟页面底色走，不单独刷一块白）
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
            )
        },
        floatingActionButton = {
            // 右下角这颗是「新增一个账号」：染**账户管理的棕**（§4.3「染模块语义色…不是默认
            // 主题蓝，一色一功能」）。原来是一颗裸 FAB、默认主题蓝，连这一页别处的色都对不上。
            // 用 Extended（带字）与车辆管理页同形 —— 光看一颗「＋」猜不出是"新增"还是"筛选"。
            ExtendedFloatingActionButton(
                onClick = { vm.openCreate() },
                containerColor = Color(AccountBrown),
                contentColor = Color(OnAccountBrown),
                icon = { Icon(Icons.Default.Add, contentDescription = null) },
                text = { Text("新增账号") },
            )
        },
    ) { padding ->
        if (managingCategory) {
            // 分类管理在**同一屏的第二层**（不新开路由）：照「地址与联系人」的
            // `CategoryManagePanel` 先例 —— 真机上新开一页会「抽屉先收起再弹整页、中间闪一下」。
            // 返回时名册与账号列表都刷一遍（分类名可能刚改过）。
            Box(Modifier.fillMaxSize().padding(padding)) {
                UserCategoriesPanel(
                    vm = catVm,
                    onBack = {
                        managingCategory = false
                        catVm.load()
                        vm.loadCategories()
                    },
                )
            }
        } else {
        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                vm.loading -> LoadingBox()
                vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                vm.users.isEmpty() -> EmptyView("暂无账户，点右下角 + 创建", Modifier.align(Alignment.Center))
                else -> Column(Modifier.fillMaxSize()) {
                    // ---- 状态档：全部 / 在用 / 已停用 / 已删除（2026-10-03 · E2E 报告 P2）----
                    // 真机上这一页原来**只有分类那一个口径**：一屏接一屏全是历史停用/删掉的
                    // 探针账号，而"找一个正在用的账号"没有任何筛选可点（只能先知道名字去搜）。
                    // 落位照 `ui/shipper/AddressScreen.kt:219-250` 的先例：档位行**常驻在搜索框上面**。
                    // ⛔ 不许把它塞进 LazyColumn 当一个 item —— 那样滚到第 30 张卡想换一档还得
                    //    先滚回顶上（这一页一屏就是 500 条，等于"这个筛选不存在"）。
                    SegmentedStatusTabs(
                        labels = ACCOUNT_STATUS_TABS,
                        colors = ACCOUNT_STATUS_COLORS,
                        selected = vm.statusTab,
                        onSelect = { vm.statusTab = it },
                    )
                    LazyColumn(
                        // `weight(1f)`：档位行占它该占的高度，剩下的全给列表 ——
                        // 外层从 `Box` 换成 `Column` 之后必须给权重，否则列表高度会是 0。
                        Modifier.weight(1f),
                        // 左右 16dp 与档位行对齐（`SegmentedStatusTabs` 自带横向 16dp）；
                        // 上边距**留 0**：那 4/8dp 的呼吸由档位行自己带，这里再叠一层会让
                        // "档位行 → 搜索框"的间距比"搜索框 → 卡片"大一倍。
                        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 0.dp, bottom = 16.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        // 搜索框（用户 2026-09-19：「账户管理…也要添加搜索键」，按**名称 / 手机号 /
                        // 手机号后 4 位**搜）。走**服务端** `?q=` —— 这一页列的是全部角色的账号、
                        // 一页最多 500 条，本地过滤会让第 501 个账号"不存在"。
                        item {
                            SearchField(value = vm.query, onValueChange = { vm.onQueryChange(it) })
                        }
                        if (vm.isSearching) {
                            if (vm.hitsTruncated) {
                                item {
                                    TruncationNote(
                                        vm.hitsLimit,
                                        "匹配到的账号不止这些 —— 把关键词写细一点（姓名多打一个字，或手机号多打几位）",
                                    )
                                }
                            }
                            if (vm.shown.isEmpty()) {
                                item {
                                    EmptyView(
                                        "服务端按姓名/手机号搜过，没有「" + vm.query.trim() + "」这个账号",
                                        // ⛔ 别给这处空态加固定高度（吃过 140dp 的亏）：EmptyView 肚子里的账是
                                        //    「上下各 48dp 内边距 + 56dp 图标 + 12dp 间隔 + 文案」，140 - 96 = 44dp
                                        //    的内容盒连图标都装不下，Column 会把超出的额度从后面的孩子身上扣光，
                                        //    文案被量成 0 高 —— 屏幕上只剩一个图标（2026-10-03 真机复测抓到）。
                                        Modifier.fillMaxWidth(),
                                    )
                                }
                            }
                        } else if (vm.truncated) {
                            // 被服务端截断时**说出来**（判据是响应头 `X-Truncated`，见 AccountManageViewModel）。
                            // 这一页尤其要说：右下角就是「新建账户」，而"列表里没有"最容易被读成
                            // "这个账号不存在"→ 再建一个 → 撞手机号唯一约束。
                            item {
                                TruncationNote(
                                    vm.pageLimit,
                                    "用上面的搜索框找 —— 那是服务端按姓名/手机号搜的全量结果，" +
                                        "不受这一页限制；直接往下翻找不到不等于没有这个账号，先别急着新建",
                                )
                            }
                        }
                        // 空名单**说出来**：不说的话用户看到的是"搜索框下面一片空白"，
                        // 会以为账号被筛没了 / 被删光了。
                        //
                        // ⚠️ 两种空法各有各的原因，**只出其中一句**：判据是"把状态那一档摘掉之后
                        //    还剩不剩东西" —— 剩 = 是**档位**筛空的（默认停在「在用」，而刚停用/
                        //    刚删掉的那个账号正在「已停用」「已删除」两档里）；不剩 = 左栏那一类
                        //    本身就没有账号。两句同时冒出来会互相打架（一句说"这一类没有"、
                        //    一句说"换一档"）。
                        // ⛔ 也别合并成一句笼统的"没有账号"：用户要的正是"为什么没有"。
                        val railShown = inRail(vm.shown, vm.railKey) { it.category }
                        if (vm.shownInRail.isEmpty() && railShown.isNotEmpty()) {
                            item {
                                EmptyView(
                                    "「" + ACCOUNT_STATUS_TABS[vm.statusTab] + "」这一档下没有账号 —— " +
                                        "上面换一档看看",
                                    Modifier.fillMaxWidth(),
                                )
                            }
                        }
                        if (vm.railKey.isNotBlank() && railShown.isEmpty()) {
                            item {
                                EmptyView(
                                    "「" + railNameOf(vm.railKey) + "」这一类下还没有账号 —— " +
                                        "在卡片上编辑、或左栏换一格",
                                    Modifier.fillMaxWidth(),
                                )
                            }
                        }
                        items(vm.shownInRail, key = { it.id }) { u ->
                            AccountCard(
                                u = u,
                                onEdit = { vm.openEdit(u) },
                                onToggle = { vm.toggleActive(u) },
                                onDelete = { vm.deleting = u },
                                onRestore = { vm.restore(u) },
                            )
                        }
                        item { Spacer(Modifier.height(72.dp)) }
                    }
                }
            }
        }
        }
    }
    }

    // 删除确认
    vm.deleting?.let { target ->
        AlertDialog(
            onDismissRequest = { vm.dismissDelete() },
            title = { Text("删除账户") },
            text = {
                // ⚠️ 号码走 `rosterPhoneOf`（2026-10-03 · E2E 报告 P1）：「恢复时撞号」那种账号
                //    是**活的**（`isActive=true`，所以这个确认框照样会弹），而它的 `phone`
                //    仍然带着 `_del{id}` 后缀 —— 直接把 `target.phone` 端上来就是乱码。
                val shownPhone = rosterPhoneOf(target) ?: ROSTER_PHONE_TAKEN
                Text(
                    "确认删除「" + (target.fullName.ifBlank { shownPhone }) + " / " + shownPhone +
                        "」？删除后该账号不可登录，且手机号可重新建号。"
                )
            },
            confirmButton = {
                TextButton(
                    onClick = { vm.confirmDelete() },
                    enabled = !vm.deletingBusy,
                ) {
                    if (vm.deletingBusy) {
                        CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                    } else {
                        Text("删除", color = Color(MessageRed))
                    }
                }
            },
            dismissButton = {
                TextButton(onClick = { vm.dismissDelete() }) { Text("取消") }
            },
        )
    }

    if (vm.showSheet) {
        ModalBottomSheet(
            onDismissRequest = { vm.showSheet = false },
            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
            // ⛔ 这里**故意不传** containerColor：抽屉的底色由 theme 一处决定
            //    （`Color.kt::SheetSurface`，M3 的默认链就是读它）。
            //    在这一页传一个自己的颜色，就成了"19 个抽屉各说各的"的起点。
        ) {
            AccountFormSheet(
                vm = vm,
                catVm = catVm,
                snackbar = snackbar,
                copyText = { s -> copyTextToClipboard(ctx, "账号密码", s) },
            )
        }
    }
}

/**
 * 一张账号卡。
 *
 * 三行、各司其职（**位置本身有含义，别随手挪**）：
 * | 行 | 内容 | 为什么这么放 |
 * |---|---|---|
 * | 1 | 姓名（撑满）+ 角色徽章 + 状态徽章 | 短状态与标题**同一行**，用户 2026-09-21：「不要做两排」 |
 * | 2 | 手机号（**长按复制**） | 与订单号同一个手势（用户 2026-09-19：「长按订单号是可以复制的」） |
 * | 3 | 左：删除 / 停用启用（回收站账号是「恢复」） · 右：编辑 | 用户 2026-09-22：「编辑一定在右边（惯用手是右手）…相反的操作就在左边」 |
 *
 * ⚠️ 第 3 行的左栏**按 `u.isDeleted` 分两套**（2026-10-03 · E2E 报告 P1/P2）：
 *    回收站账号只给「恢复」—— 对它按「启用」后端直接 400（`users.py:294-301`：
 *    「这个账号在回收站里…请用「恢复」把它放回来」），再点一次「删除」也是 400
 *    （`users.py:445-446`「这个账号已经删过了」）。⛔ 界面上不该出现按不动的按钮。
 */
@Composable
private fun AccountCard(
    u: UserDto,
    onEdit: () -> Unit,
    onToggle: () -> Unit,
    onDelete: () -> Unit,
    // 回收站账号的"放回来"（`POST /users/{id}/restore`）。
    onRestore: () -> Unit,
) {
    SectionCard {
        // ---- 行1：姓名 + 角色 + 状态（同一行）----
        // 名称行/电话行走 `ui/common/RosterCard.kt` 的两个共用零件：本页模块色的圈底人形图标 +
        // 16sp 加粗姓名、青绿 Phone 图标 + 前景色号码（用户 2026-10-05：「名称和电话号码…要有
        // 对应的语义色和图标。让信息明确」）—— ⛔ 别再在各页各写一份字号和颜色。
        RosterNameRow(
            // 姓名空时回落到号码 —— ⛔ 这里也走 `rosterPhoneOf`（P1）：
            // `u.phone` 可能是 `13923111638_del62`，端到标题上比端在电话行还显眼。
            name = u.fullName.ifBlank { rosterPhoneOf(u) ?: ROSTER_PHONE_TAKEN },
            icon = Icons.Default.Person,
            accent = Color(AccountBrown),
        ) {
            val (bg, fg) = labelColors(u)
            Surface(color = bg, shape = MaterialTheme.shapes.small) {
                Text(
                    AccountRoleKind.labelOf(u),
                    color = fg,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Medium,
                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                )
            }
            // 停用/删除都是**异常状态**，只在它成立时出现 —— 每张卡都挂一个"正常"徽章，
            // 真正要看的那一个反而沉进背景里了。
            //
            // ⚠️ 两者**互斥且分色**（2026-10-03 · E2E 报告 P2）：删号会把 `is_active` 也置 false，
            //    所以"回收站里的账号"同时也满足 `!isActive` —— 只判 `!isActive` 的话，
            //    一屏回收站账号全都写着「已停用」，用户根本看不出它们是**号码已经释放**的那种
            //    （那种只能「恢复」，不能「启用」）。判据只认后端算好的 `u.isDeleted`
            //    （`users.py::_in_recycle_bin`），界面不自己拿 `phone.contains("_del")` 猜。
            if (u.isDeleted) {
                Spacer(Modifier.width(6.dp))
                Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = MaterialTheme.shapes.small) {
                    Text(
                        "已删除",
                        // 底色与「已停用」同一格灰（都表示"这个人不在岗"），字色分开：
                        // 红 = 不可逆那一档，与本页「删除」按钮同色；橙留给「已停用」（还能启用回来）。
                        color = Color(MessageRed),
                        fontSize = 12.sp,
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                    )
                }
            } else if (!u.isActive) {
                Spacer(Modifier.width(6.dp))
                Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = MaterialTheme.shapes.small) {
                    Text(
                        "已停用",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        fontSize = 12.sp,
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                    )
                }
            }
        }
        Spacer(Modifier.height(6.dp))

        // ---- 行2：手机号（长按复制也搬进共用件了，见 RosterCard.kt）----
        // ⚠️ 传**账号**而不是 `u.phone`（2026-10-03 · E2E 报告 P1）：软删账号落库的号码是
        //    `13923111638_del62` 这种内部值，直接端上来就是乱码。`RosterPhoneRowOf` 按后端的
        //    `phone_display` 画号；号码已经让给新账号时画「号码已让给新账号」（不静默留白）。
        RosterPhoneRowOf(u)
        Spacer(Modifier.height(4.dp))

        // ---- 行3：动作行（左＝相反/警示 · 右＝编辑）----
        // ⚠️ 这个控件**不是这一页自己的**：`ui/common/Components.kt::CardActionIcon`（传 label
        //    就是"圈底图标 + 文字"、不传就是卡片上那个纯图标）。原来这一页自己养了一个
        //    `AccountAction`，与订单卡那个 `CardActionIcon` 是同一件事的两份实现 ——
        //    圆底画法本来就共用 `TintedIcon`，差别只在有没有那行字，2026-09-22 收成一个可选参数。
        //    ⛔ 别再在这一页（或任何页）新建一个"圈底动作"控件：位置规范（左/右）与形态（圈底）
        //    都该只有一处实现，否则下一次改样式必然漏掉其中一页。
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            // ⚠️ 左栏**分两套**（2026-10-03 · E2E 报告 P1/P2）：回收站账号只给「恢复」——
            //    对它按「启用」后端 400（`users.py:294-301`），再点「删除」也是 400
            //    （同文件 :445-446「这个账号已经删过了」）。两个按钮在这里都只会吃一句报错，
            //    ⛔ 界面上不该出现按不动的按钮。判据只认后端算好的 `u.isDeleted`（界面不猜：
            //    `_in_recycle_bin` 除了后缀还看 `is_active`，"恢复时撞号"那种账号已经在用了）。
            // ⚠️ 判据 `_check_sheet_form_pages.py` 钉着「动作行里**第一个** AccountAction 是删除」
            //    （相反/警示在最左）—— 所以回收站那一支必须写在**后面**：把它写在前面，
            //    第一次出现的动作就成了「恢复」，那条判据立刻变红。
            if (!u.isDeleted) {
                // 左栏：先删除（最不可逆的那个）再停用/启用
                AccountAction("删除", Icons.Default.DeleteOutline, Color(MessageRed), onDelete)
                AccountAction(
                    if (u.isActive) "停用" else "启用",
                    if (u.isActive) Icons.Default.Pause else Icons.Default.PlayArrow,
                    if (u.isActive) Color(MoneyOrange) else Color(MgrGreen),
                    onToggle,
                )
            } else {
                // 回收站账号：左栏只给「恢复」，它与「删除」互斥（见上面那一段）
                AccountAction("恢复", Icons.Default.RestoreFromTrash, Color(MgrGreen), onRestore)
            }
            Spacer(Modifier.weight(1f))
            // 右栏：编辑（惯用手那一侧）—— 回收站账号也留着这一颗：后端 `update_user`
            // **不拦**它（只有「启用」那一支拦），先把姓名/角色改对了再恢复是正常动作。
            AccountAction("编辑", Icons.Default.Edit, Color(NavBlue), onEdit)
        }
    }
}

/**
 * 这一页的动作 = 共用控件 `CardActionIcon` 的**带文字**形态（一行参数，不再自己画一遍）。
 *
 * 文字不是装饰：这一页的用户是**派单员**（要一眼看清按下去会发生什么），
 * 只留一个图标会逼人靠猜 —— 这与订单卡那边正好相反（那边用户点名要"一个图标"），
 * 所以共用控件把"有没有文字"做成可选参数，而不是各自实现一遍。
 */
@Composable
private fun AccountAction(
    label: String,
    icon: ImageVector,
    tint: Color,
    onClick: () -> Unit,
) = CardActionIcon(
    icon = icon,
    contentDescription = label,
    tint = tint,
    onClick = onClick,
    label = label,
    size = 15.dp,
    container = 30.dp,
)

/**
 * 新增 / 编辑账户的抽屉。
 *
 * ## 为什么整屏一个描边输入框都没有
 * 用户 2026-09-22：「不要使用那个**线框**，而是用**卡片**的形式」。
 * 原来的三件套是"描边框 + 浮动 label + 每字段一句灰字"（三层框叠在一起，同一轮里被否掉的
 * 「新增商品」「新增线路」都是这个病）；现在换成**白卡分组 + 无边框行**，
 * "值即占位符"的形态本身就不需要那么多解释句（零件在 `ui/common/FormRows.kt`）。
 *
 * ## 角色为什么从 chips 改成下拉
 * `FilterChip` **未选中时是带描边的**（正是用户说的"线框"），而且它会把整页的
 * "标签在左、值在右"节奏打断。设计规范 §5 的口径也是"下拉一律 `ExposedDropdownMenuBox`
 * 点选回填，不要用 chips 替代下拉"，与「新增线路」那一页的分组选择器同一个形态。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AccountFormSheet(
    vm: AccountManageViewModel,
    // 左栏分类名册（2026-10-05）：分类那一格是下拉，候选来自它。
    catVm: UserCategoriesViewModel,
    snackbar: SnackbarHostState,
    copyText: (String) -> Unit,
) {
    val scope = rememberCoroutineScope()
    val isEdit = vm.editing != null
    val role = AccountRoleKind.fromKey(vm.draftRoleKey)
    var roleExpanded by remember { mutableStateOf(false) }

    Column(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
            .imePadding()
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Column {
            Text(
                if (isEdit) "编辑账户" else "新增账户",
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
            )
            Hint(
                if (isEdit) "修改后保存即可；密码留空表示不修改"
                else "创建后账号密码自动复制，直接发给对方即可登录",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                fontSize = 13.sp,
            )
        }

        // ---- 白卡 1：账号本身 ----
        SectionCard {
            FormInputRow(
                label = "姓名",
                value = vm.draftName,
                onValueChange = { vm.draftName = it; vm.nameError = null },
                required = true,
                placeholder = "如：张三",
            )
            FormInputRow(
                label = "手机号",
                value = vm.draftPhone,
                // 规则唯一实现在 core/InputRules.kt（过滤写在调用点上，这样
                // "这个框走的是哪条规则"在同一行就能看见，`_check_input_rules.py` 也是这么认的）
                onValueChange = { v -> vm.draftPhone = InputRules.mobileInput(v); vm.phoneError = null },
                required = true,
                placeholder = "11 位手机号（登录账号）",
                keyboardType = KeyboardType.Phone,
            )
            AccountSecretRow(
                label = "密码",
                value = vm.draftPassword,
                onValueChange = { vm.draftPassword = it; vm.passwordError = null },
                placeholder = if (isEdit) "留空表示不修改" else "至少 6 位",
                required = !isEdit,
            )
        }

        // ---- 白卡 2：角色（必选）----
        SectionCard {
            ExposedDropdownMenuBox(expanded = roleExpanded, onExpandedChange = { roleExpanded = it }) {
                FormPickRow(
                    label = "角色",
                    value = role.label,
                    placeholder = "请选择",
                    required = true,
                    onClick = { roleExpanded = true },
                    modifier = Modifier.menuAnchor(),
                )
                ExposedDropdownMenu(expanded = roleExpanded, onDismissRequest = { roleExpanded = false }) {
                    AccountRoleKind.entries.forEach { kind ->
                        DropdownMenuItem(
                            text = {
                                Text(
                                    if (kind.key == vm.draftRoleKey) kind.label + "　✓" else kind.label,
                                    maxLines = 1,
                                )
                            },
                            onClick = { vm.draftRoleKey = kind.key; roleExpanded = false },
                        )
                    }
                }
            }
        }

        // ---- 白卡 3：分类（左栏分组，2026-10-05）----
        // 下拉（⛔ 不是再套一层弹层 —— 这一屏本身就在底部抽屉里，两层 modal 叠着是
        // `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md` §4.14 点名禁止的形态）。
        SectionCard {
            CategoryPickRow(
                vm = catVm,
                selected = vm.draftCategory,
                onPick = { vm.draftCategory = it },
                hint = "只影响左栏怎么分组；四个名册页（账户 / 司机 / 货主 / 批发商）共用这一份分类。",
            )
        }

        // 校验/保存失败的那句话画在**抽屉里面**（见 FormErrorLine 的注释：
        // 写进页面级错误会让"保存被拦下"变成"整页列表全没了"）
        FormErrorLine(vm.formError)

        // 保存按钮（点击时触发校验；未过 → 抽屉里出红字，不会提交）
        Button(
            onClick = {
                vm.save { msg ->
                    copyText(msg)
                    scope.launch { snackbar.showSnackbar("已保存：$msg") }
                }
            },
            enabled = !vm.acting,
            modifier = Modifier.fillMaxWidth().height(50.dp),
        ) {
            if (vm.acting) CircularProgressIndicator(Modifier.size(22.dp), color = Color.White, strokeWidth = 2.dp)
            else Text("保存", fontSize = 16.sp)
        }
        Spacer(Modifier.height(12.dp))
    }
}

/**
 * 密码那一行：与 [FormInputRow] **同一个形态**（标签在左、值在右、整行可点），
 * 只多一件事 —— 值要打码。
 *
 * ⚠️ 为什么没往 `ui/common/FormRows.kt` 里加一个 `visualTransformation` 参数：
 * 那个文件**另一个会话此刻正在改**（他们刚往里面加了 `FormActionRow` / `FormTextAreaRow`）。
 * 为了一个参数去动别人手上正在写的文件，风险大于这二十行的收益。
 * 形态本身仍然是共用的（底下就是 [FormRow]），所以不会长出第二种长相；
 * 等有**第三处**要密码行时再提上去，那时和那一轮的人对齐。
 */
@Composable
private fun AccountSecretRow(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    required: Boolean = false,
) {
    val focus = remember { FocusRequester() }
    FormRow(label = label, required = required, onClick = { focus.requestFocus() }) {
        Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterEnd) {
            if (value.isEmpty()) {
                Text(
                    placeholder,
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            BasicTextField(
                value = value,
                onValueChange = onValueChange,
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                textStyle = LocalTextStyle.current.merge(
                    MaterialTheme.typography.bodyLarge.copy(
                        color = MaterialTheme.colorScheme.onSurface,
                        textAlign = TextAlign.End,
                    ),
                ),
                cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
                modifier = Modifier.fillMaxWidth().focusRequester(focus),
            )
        }
    }
}

/** 角色标签配色：浅底 + 深字（与其他页面包章风格一致） */
private fun labelColors(u: UserDto): Pair<Color, Color> = when {
    u.role == "dispatcher" -> Color(0xFFDBE9FF) to Color(0xFF0A4DAF)
    u.role == "driver" && u.vehicleType == "trailer" -> Color(0xFFFFE0B2) to Color(0xFFE65100)
    u.role == "driver" && u.vehicleType == "large" -> Color(0xFFF0F4C3) to Color(0xFF827717)
    u.role == "driver" && u.vehicleType == "small" -> Color(0xFFE0F7FA) to Color(0xFF006064)
    u.role == "driver" -> Color(0xFFF0F4C3) to Color(0xFF827717)
    u.isMember -> Color(0xFFFFF1C6) to Color(0xFF7A5900)
    else -> Color(0xFFD6F3FA) to Color(0xFF005A78)
}
