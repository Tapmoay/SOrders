package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.UserDto
import com.tapmoay.sorders.data.remote.dto.VehicleDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.DriverLime
import kotlinx.coroutines.launch
import com.tapmoay.sorders.ui.theme.InventoryTeal
import com.tapmoay.sorders.ui.theme.MemberGold
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.ui.theme.NavBlue
import com.tapmoay.sorders.ui.theme.OnDriverLime
import com.tapmoay.sorders.ui.theme.Success
import com.tapmoay.sorders.ui.theme.WarningAmber
import com.tapmoay.sorders.util.formatMoney
import com.tapmoay.sorders.ui.common.Hint

/**
 * 账号管理（司机 / 货主 / 批发商三池共用一个界面）。
 *
 * ## v3.44 的改动：司机池多了一条"车辆"线
 * 用户原话是「给司机管理做一个合理且美观的界面布局」，落点其实是**信息缺了一整块**：
 * 一个司机卡片上原本看不到「他开哪辆车」，而"哪辆车归谁"恰恰是派单时第一个要看的东西。
 * 现在司机卡片上多一行**车辆行**（点一下就配车/换车/解绑），顶部多一条**车队摘要**
 * （共几人、几个已配车、几个没配），列表多一个**搜索框**。
 *
 * ## v3.45：搜索框升级成"三个池都有 + 服务端搜"（用户 2026-09-19）
 * 用户原话：「还有其他的比如说，**司机管理**啊**账户管理**啊。这些也要添加搜索键。
 * 然后这个搜索键可以根据他们的**名称**还有**电话号码**以及**电话号码的后 4 位**进行搜索」。
 * 改了三件事：
 * 1. **货主池 / 批发商池也有搜索框了**（以前只有司机池有，另两个池只能靠滚）；
 * 2. 搜索改成**服务端** `?q=`（以前是过滤"手里这一页"，最多 500 条 —— 第 501 个人
 *    在客户端根本不存在，而"搜不到"会被读成"没有这个账号"→ 再建一个 → 撞唯一约束）；
 * 3. 手机号**后 4 位**能搜（子串匹配天然命中，规则唯一实现在 `core/UserSearch.kt`
 *    与 `app/core/user_search.py`）。
 * ⚠️ **车牌不再参与这个搜索框**：它只在"已列出的这一页"里匹配（同样有这个上限问题），
 *    而车牌优先的入口本来就是右上角的「车辆」→ 车辆管理页（那一页有专门的「搜车牌」）。
 *
 * ## 三个"丑"的具体来源（这一轮逐条改掉）
 * 1. **没有头像块**：所有卡片都是"几行字"，扫一眼分不出谁是谁。
 *    现在左侧一个**姓氏圆底**（颜色按池分：司机黄绿 / 货主蓝 / 批发商金），
 *    与顶部的角色徽章同色系。
 * 2. **操作按钮挤成一行**：`设为批发商 / 转货主 / 停用` 三个文字键平铺，
 *    误触率高（"停用"和"转货主"挨着）。当时改成"危险的那个靠右 + 中间留弹性空位"，
 *    **2026-10-03 的 CHG-0019 又推翻了一次** —— 见下面 v3.46 那一节（现在整行走圈底图标）。
 * 3. **行尾只有一个铅笔**：看不出"点整张卡"能不能编辑。现在整卡可点；
 *    那个裸 18dp 铅笔也在 CHG-0019 里换成了圈底的「编辑」动作。
 *
 * ## v3.46（CHG-0019）：卡片动作按规范 §4.2c 重画
 * 用户 2026-10-03 的原话是「前端页面要重做按照我们的设计规范进行写」。规范 §4.2c 给卡片动作定死两件事：
 * **形态**一律是「12% 语义色圆底 + 同色图标」（`ui/common/Components.kt::CardActionIcon`），
 * **位置**是「危险 / 异常放最左、编辑放最右（惯用手是右手）」。这一屏原来两样都不对：
 * 卡头一个**裸 18dp 铅笔**（用户原话「这个不行」），卡底三个 `TextButton` 平铺。
 *
 * 现在卡头只剩「定价」这个业务入口，四个动作都在卡底那一行，从左到右：
 * 停用·启用（提醒色 / 成功色，**最左**，只留圈底图标 —— 这一行最多要塞四个动作，
 * 而行宽 347dp，「设为批发商」这种五字标签一个就 112dp，四个带字的一行装不下；
 * 危险的那个又恰恰最不该是个好按的带字大键）→ 设为 / 取消批发商（批发商金）
 * → 转司机 / 转货主（转到哪个池就用那个池的模块色）→ `Spacer(weight(1f))` →
 * 编辑（`NavBlue`，**最右**）。
 *
 * ⛔ 别把这一行退回 `TextButton`：三个池之间差一层语义就点错人，圈底图标 + 字是这一页的最低要求；
 *    也别再往卡头塞第二个动作键 —— 卡头是「这个人是谁」，卡底才是「拿他能做什么」。
 * * ## 一个刻意的边界
 * **改车辆（车牌/车型/停用/谁没配车）不在这一屏做**，它在「车辆管理」页——
 * 这一屏只做"给这个人配哪辆车"（司机视角）。两个视角改的是同一条接口，
 * 但混在一屏会让"这辆车现在归谁"和"这个人现在开哪辆"两件事互相打架。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun UsersManageScreen(
    container: AppContainer,
    pool: UserPool,
    onBack: () -> Unit,
    onOpenPricing: (UserDto) -> Unit = {},
    onOpenVehicles: () -> Unit = {},
) {
    val vm: UsersManageViewModel = appViewModel { UsersManageViewModel(container, pool) }
    val snackbar = remember { SnackbarHostState() }

    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })

    // ---- 左栏分类（2026-10-05）----
    //
    // 用户原话：「还有我们的账户管理司机管理货主管理批发商管理。车辆管理……在这个位置也加个分类，
    // 默认是显示，全部，同样也是左边侧边栏，然后左边侧边栏同样也是可以新增分类的，
    // 那个左边侧分栏的底下，凡是跟地点是同样的」。
    //
    // ⚠️ 司机 / 货主 / 批发商三池是**同一个界面**（`UserPool`），所以这一份抽屉一次喂三页；
    //    分类名册也是同一份（`user_categories`，挂在 `users.category` 上）—— 账户管理页那一格也一样。
    //
    // 形态照「地址与联系人」：**抽屉**（⛔ 不是商品管理那种常驻左栏 —— 用户 2026-09-19 的裁定是
    // 「右边的卡片的信息被挤压了不是很好看」）。抽屉底部那格「管理分类」进分类管理面板。
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
                    accent = poolModuleColor(pool),
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
    // 顶栏那颗分类胶囊（用户画的那个红框位置：标题右边那一格 —— 默认「全部」）。
    // 落位（用户 2026-10-05）：「其他的所有的按钮也是按照这样子的形式放在右边…
    // 如果右边有东西的话，则就保持原样。如果右边是空的话，则就放在右边」——
    // 司机池有「车辆」、批发商池有「批量调价」，这两个保持原样、胶囊仍贴着标题；
    // 货主池顶栏右边空着，胶囊就贴到右侧、右缘与下面的卡片对齐
    // （`actions` 自带 4dp 右边距 + 这里补 12dp = 卡片的 16dp 内边距）。
    val chipBesideTitle = pool == UserPool.MEMBERS || vm.isDriverPool
    val chip: @Composable (Modifier) -> Unit = { m ->
        CategoryTriggerChip(
            current = railNameOf(vm.railKey),
            // 这一池的**模块色**：司机=黄绿 / 货主=深青 / 批发商=金（§4.3 一色一功能）。
            // 原来三个池共用货主管理的深青 —— 批发商那一页的胶囊和工作台那一格对不上。
            accent = poolModuleColor(pool),
            onClick = { scope.launch { drawer.open() } },
            modifier = m,
        )
    }
    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(pool.title)
                        if (chipBesideTitle) {
                            Spacer(Modifier.width(8.dp))
                            chip(Modifier)
                        }
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    if (!chipBesideTitle) chip(Modifier.padding(end = 12.dp))
                    if (pool == UserPool.MEMBERS) {
                        TextButton(onClick = { vm.openBatch() }) {
                            Icon(Icons.Default.Edit, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(4.dp))
                            Text("批量调价", style = MaterialTheme.typography.titleSmall)
                        }
                    }
                    // 司机池：直接跳车辆管理（"谁还没配车"要连着车队一起看才对得上）
                    if (vm.isDriverPool) {
                        TextButton(onClick = onOpenVehicles) {
                            Icon(Icons.Default.LocalShipping, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(4.dp))
                            Text("车辆", style = MaterialTheme.typography.titleSmall)
                        }
                    }
                },
            )
        },
        floatingActionButton = {
            // 右下角这颗是「新增一个（司机 / 货主 / 批发商）」：染**这一池的模块色**，不是主题蓝
            // —— §4.3「染模块语义色…不是默认主题蓝，一色一功能」。用 Extended（带字）不用裸 FAB：
            // 光看一颗「＋」猜不出是"新增"还是"筛选"，老人友好这条线上带字更清楚。
            ExtendedFloatingActionButton(
                onClick = { vm.openCreate() },
                containerColor = poolModuleColor(pool),
                contentColor = poolOnColor(pool),
                icon = { Icon(Icons.Default.Add, contentDescription = null) },
                text = { Text("新增" + pool.title.removeSuffix("管理")) },
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
                vm.users.isEmpty() -> EmptyView(
                    when (pool) {
                        UserPool.MEMBERS -> "暂无批发商，可在「货主管理」中升级为批发商"
                        UserPool.SHIPPERS -> "暂无货主账号"
                        UserPool.DRIVERS -> "暂无司机账号"
                    },
                    Modifier.align(Alignment.Center),
                )
                else -> LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    if (vm.isDriverPool) {
                        item { DriverFleetSummary(vm) }
                    }
                    // 搜索框 —— **三个池都有**，而且都走**服务端** `?q=`。
                    // 用户 2026-09-19：「还有其他的比如说，司机管理啊账户管理啊，这些也要添加搜索键。
                    // 然后这个搜索键可以根据他们的**名称**还有**电话号码**以及**电话号码的后 4 位**进行搜索」。
                    // ⛔ 以前只有司机池有这一行，而且它过滤的是"手里这一页"（≤500 条）：
                    //    货主/批发商池连搜索框都没有，而"列表里没有"最容易被读成"没有这个账号"。
                    item {
                        SearchField(value = vm.query, onValueChange = { vm.onQueryChange(it) })
                    }
                    if (vm.isSearching) {
                        // 搜索打的是服务端，所以这时候"搜不到"是一句**结论**（不是"这一页里没有"）
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
                                    // ⛔ 本页三处空态都别加固定高度（吃过 140dp 的亏）：EmptyView 肚子里的账是
                                    //    「上下各 48dp 内边距 + 56dp 图标 + 12dp + 文案」，固定高度 140 只留 44dp
                                    //    的内容盒，Column 把超出的额度从后面的孩子身上扣光 → 文案被量成 0 高、
                                    //    屏幕上只剩图标（2026-10-03 真机复测抓到）。
                                    Modifier.fillMaxWidth(),
                                )
                            }
                        }
                    } else if (vm.truncated) {
                        // 名册被服务端截断时**说出来**（判据是响应头 `X-Truncated`，见 UsersManageViewModel）。
                        // ⚠️ 这一句**必须**指向服务端搜索：以前这里写的是"上面的搜索也只在已列出的账号里找"，
                        //    因为那时搜索是本地过滤 —— 那句话现在已经**不成立**了，留着比没有更糟。
                        item {
                            TruncationNote(
                                vm.pageLimit,
                                "用上面的搜索框找人 —— 那是服务端按姓名/手机号搜的全量结果，" +
                                    "不受这一页限制；直接往下翻找不到不等于没有这个账号，先别急着新建",
                            )
                        }
                    }
                    if (!vm.isSearching && vm.shown.isEmpty()) {
                        item {
                            EmptyView("没有匹配「${vm.query}」的账号", Modifier.fillMaxWidth())
                        }
                    }
                    // 这一类下真的一个账号都没有时**说出来**（不说的话用户看到一个空页面）
                    if (vm.railKey.isNotBlank() && vm.shownInRail.isEmpty()) {
                        item {
                            EmptyView(
                                "「" + railNameOf(vm.railKey) + "」这一类下还没有账号 —— " +
                                    "在卡片上编辑、或左栏换一格",
                                Modifier.fillMaxWidth(),
                            )
                        }
                    }
                    items(vm.shownInRail, key = { it.id }) { u ->
                        UserManageCard(
                            u = u,
                            pool = pool,
                            vehicles = if (vm.isDriverPool) vm.vehiclesOf(u.id) else emptyList(),
                            onEdit = { vm.openEdit(u) },
                            onBindVehicle = { vm.openVehiclePicker(u) },
                            onToggleActive = { vm.toggleActive(u) },
                            onToggleMember = { vm.toggleMember(u) },
                            onSwapRole = { vm.swapRole(u) },
                            onOpenPricing = { onOpenPricing(u) },
                        )
                    }
                    item { Spacer(Modifier.height(72.dp)) }
                }
            }
        }
        }
    }
    }

    // 配车弹层（司机视角：给他挑一辆车；选「不绑车」= 解绑）
    vm.vehiclePickerFor?.let { u ->
        VehiclePickerSheet(
            driverName = u.fullName.ifBlank { u.phone },
            vehicles = vm.vehicles,
            currentIds = vm.vehiclesOf(u.id).map { it.id }.toSet(),
            driverNameOf = { id -> vm.driverNameOf(id) },
            busy = vm.binding,
            onPick = { vid -> vm.pickVehicle(vid) },
            onDismiss = { if (!vm.binding) vm.vehiclePickerFor = null },
        )
    }

    // ---- 新增/编辑账号：**底部抽屉 + 白卡分组**（2026-10-03 · CHG-0018）----
    //
    // 用户原话：「为什么你每次设计前端页面怎么都那么难看啊……我们不是有一套完整的呃设计规范吗？」
    // 原来这里是 `AlertDialog` + 一摞裸 `OutlinedTextField`，同时违反三条：
    // 1. 规范「表单带选择器时用单独一页，不要塞进 AlertDialog」—— 这里有车型、计费规则两个选择器
    //    再加一张商品可见范围清单，弹窗装不下，只能靠一个自带 scroll 的 `Column` 硬顶
    //    （旧代码自己写着「字段叠起来在小屏上会把「保存」顶出屏幕」）；
    // 2. 规范 §5.0「分组一律白卡」：字段一律用 `ui/common/FormRows.kt` 里的共用行；
    // 3. 「校验/保存失败画在表单里」—— 旧代码把失败写进**页面级** `vm.error`，而那句话画在
    //    **弹窗背后**（页面主体），用户看到的是"点「保存」没有任何反应"，关掉之后整页还被
    //    `ErrorView` 顶掉。现在失败走 `vm.formError` → `FormErrorLine`，就画在「保存」正上方。
    if (vm.showSheet) {
        val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
        ModalBottomSheet(onDismissRequest = { vm.closeSheet() }, sheetState = sheetState) {
            // 「商品可见范围」是**这个抽屉里的第二层**（点那一格进去，见 ProductVisibilityLayer）。
            // ⚠️ 它必须在这里就分叉，**不能**塞进下面那个 Column：那个 Column 是 verticalScroll 的，
            // 里面再放一个 LazyColumn（带左栏的清单）会被量成无限高，跑起来直接崩。
            var showVisibilityLayer by remember { mutableStateOf(false) }
            if (showVisibilityLayer) {
                ProductVisibilityLayer(vm = vm, accent = poolAccent(pool), onBack = { showVisibilityLayer = false })
            } else {
            // 下面这一段的缩进没跟着调整：里面两百行，Kotlin 不看缩进，重排只会把 diff 弄脏
            Column(
                Modifier
                    .fillMaxWidth()
                    .fillMaxHeight()
                    .padding(horizontal = 16.dp)
                    .imePadding()
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        if (vm.editing == null) "新增" + pool.title.removeSuffix("管理") else "编辑账号",
                        style = MaterialTheme.typography.titleLarge,
                        modifier = Modifier.weight(1f),
                    )
                    SheetCloseButton(onClick = { vm.closeSheet() })
                }

                // ① 账号：登录用的三样。手机号就是登录账号，所以按手机号规则来 ——
                //    规则唯一实现在 core/InputRules.kt（这一处原来什么过滤都没有，
                //    同一个 App 里的「账户管理」页却有 —— 两页两个口径）。
                FormGroup(icon = Icons.Default.Person, title = "账号", tint = poolAccent(pool)) {
                    FormInputRow(
                        label = "手机号（登录账号）",
                        value = vm.draftPhone,
                        onValueChange = { vm.draftPhone = InputRules.mobileInput(it) },
                        placeholder = "11 位手机号",
                        required = true,
                        keyboardType = KeyboardType.Phone,
                        icon = Icons.Default.Phone,
                        iconTint = poolAccent(pool),
                    )
                    FormInputRow(
                        label = "姓名",
                        value = vm.draftName,
                        onValueChange = { vm.draftName = it },
                        placeholder = "选填",
                        icon = Icons.Default.Badge,
                        iconTint = poolAccent(pool),
                    )
                    FormInputRow(
                        label = if (vm.editing == null) "初始密码" else "重置密码",
                        value = vm.draftPassword,
                        onValueChange = { vm.draftPassword = it },
                        // 新建时必填（save() 卡 6 位长度），编辑时留空就是不改
                        placeholder = if (vm.editing == null) "至少 6 位" else "留空就不改",
                        required = vm.editing == null,
                        icon = Icons.Default.Lock,
                        iconTint = poolAccent(pool),
                    )
                }

                // ② 车辆与计费（只有司机池有这两项）
                if (pool == UserPool.DRIVERS) {
                    var vtExpanded by remember { mutableStateOf(false) }
                    var ruleExpanded by remember { mutableStateOf(false) }
                    val attached = vm.rules.firstOrNull { it.id == vm.draftRuleId }
                    FormGroup(
                        icon = Icons.Default.LocalShipping,
                        title = "车辆与计费",
                        tint = Color(DriverLime),
                    ) {
                        // 车辆类型：大车 / 挂车。⚠️ 这里原来会顺手把「计费方式」改成 PIECE/SALARY，
                        // 那是老口径的副作用，现在没有那个字段了（他怎么算钱只看规则）。
                        ExposedDropdownMenuBox(expanded = vtExpanded, onExpandedChange = { vtExpanded = it }) {
                            FormPickRow(
                                label = "车辆类型",
                                value = driverKindLabel(vm.draftVehicleType),
                                placeholder = "请选择",
                                icon = Icons.Default.LocalShipping,
                                iconTint = Color(DriverLime),
                                onClick = { vtExpanded = true },
                                modifier = Modifier.menuAnchor(),
                            )
                            ExposedDropdownMenu(expanded = vtExpanded, onDismissRequest = { vtExpanded = false }) {
                                listOf("large" to "大车司机", "trailer" to "挂车司机").forEach { (k, label) ->
                                    DropdownMenuItem(text = { Text(label) }, onClick = {
                                        vm.draftVehicleType = k
                                        vtExpanded = false
                                    })
                                }
                            }
                        }

                        // ---- 计费规则：**他怎么算钱只有这一个入口**（2026-09-21）----
                        //
                        // 用户原话：「司机管理他现在有固定工资和按单计费，但是后面又加了一个计费规则，
                        // 其实**计费规则就已经包括他们上面的这个**」。
                        // 一份规则里本来就有「固定工资」＋「每单/每件/按这一单的钱/提成」，所以
                        // 账号上再放「固定工资」「计费方式」两个框就是同一个数两处写：改哪一处都可能
                        // **不生效**（挂了规则时老字段被完全忽略），而界面上两边都不报错。
                        // 于是那两个框**删掉**，这里只留规则；没挂规则时如实说出兜底口径。
                        ExposedDropdownMenuBox(expanded = ruleExpanded, onExpandedChange = { ruleExpanded = it }) {
                            FormPickRow(
                                label = "计费规则（他怎么算钱就看这一项）",
                                value = attached?.name ?: "还没挂规则",
                                placeholder = "请选择",
                                icon = Icons.Default.Payments,
                                iconTint = Color(DriverLime),
                                onClick = { ruleExpanded = true },
                                modifier = Modifier.menuAnchor(),
                            )
                            ExposedDropdownMenu(expanded = ruleExpanded, onDismissRequest = { ruleExpanded = false }) {
                                DropdownMenuItem(
                                    text = { Text("不挂规则") },
                                    onClick = { vm.draftRuleId = null; ruleExpanded = false },
                                )
                                vm.rules.forEach { r ->
                                    DropdownMenuItem(
                                        // 一句话说明由**后端**给（和服务端算钱的口径同源），界面不自己拼
                                        text = {
                                            Column {
                                                Text(r.name)
                                                Text(
                                                    r.summary,
                                                    style = MaterialTheme.typography.bodySmall,
                                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                                )
                                            }
                                        },
                                        onClick = { vm.draftRuleId = r.id; ruleExpanded = false },
                                    )
                                }
                            }
                        }
                        // ⛔ 这一句**刻意用 Text 而不是 Hint**：它的前半句是数据（他挂的是哪份规则、
                        //    那份规则怎么算钱由后端给），也就是「关掉提示还得看得见」的东西 ——
                        //    `_check_hints.py` 第 2 组会盯着这件事（Hint 里全是数据/警告就报红）。
                        Text(
                            if (attached != null) {
                                "他以后按「${attached.name}」算钱：" + attached.summary +
                                    "（固定工资、每单/每件、提成都在这一份规则里，账号上不再单独填）"
                            } else {
                                "没挂规则 → 按车型的老口径兜底（" +
                                    driverKindLabel(vm.draftVehicleType) + "）。" +
                                    "要给他固定工资/计件/提成，请到工作台「计费规则」建一份再挂上 —— " +
                                    "否则他这一趟可能一分钱都算不出来。"
                            },
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        // 车辆绑定**不在这个抽屉里**：它是另一条写路径（POST /vehicles/{id}/driver），
                        // 单独一个弹层更好报错（后端会因为"这不是司机账号"而拒绝，那句话要原样给用户看）。
                        if (vm.editing != null) {
                            Hint(
                                "配车请在卡片上的「配车 / 换车」里改 —— 一辆车同时只能归一个司机，" +
                                    "绑错了那边会明确告诉你是谁名下的。",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }

                // ③ 商品可见范围（白名单）：只对货主/批发商有意义。
                // 用户 2026-09-18：「派单员可以指定他只只能看到哪些商品」——
                // 入口就放在**这个人的编辑页**里（和"给谁什么权限"是同一件事，
                // 单开一页会让人对不上号）。
                if (vm.editing != null && vm.visibilityApplies) {
                    FormGroup(
                        icon = Icons.Default.Visibility,
                        title = "商品可见范围",
                        tint = poolAccent(pool),
                    ) {
                        // 这里只报"现在是什么样"，真正的勾选在第二层（分类 × 商品的一张清单）。
                        // 为什么不在抽屉里直接摊开：见 ProductVisibilityLayer 的 KDoc。
                        FormPickRow(
                            label = "可见范围",
                            value = visibilitySummary(vm),
                            placeholder = "去设置",
                            icon = Icons.Default.Visibility,
                            iconTint = poolAccent(pool),
                            onClick = { showVisibilityLayer = true },
                        )
                        Hint(
                            "按分类给：以后新建到这个分类的商品会自动也给他看。某个商品不想给，" +
                                "就在清单里单独关掉它。",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }

                // 分类（左栏分组，2026-10-05）：四个名册页**共用同一份名册**（`user_categories`），
                // 所以这里改一格，账户 / 司机 / 货主 / 批发商四页的左栏一起变。
                FormGroup(icon = Icons.Default.Folder, title = "分类", tint = poolAccent(pool)) {
                    CategoryPickRow(
                        vm = catVm,
                        selected = vm.draftCategory,
                        onPick = { vm.draftCategory = it },
                        hint = "只影响左栏怎么分组；四个名册页（账户 / 司机 / 货主 / 批发商）共用这一份分类。",
                    )
                }

                FormErrorLine(vm.formError)
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(
                        onClick = { vm.closeSheet() },
                        enabled = !vm.acting,
                        modifier = Modifier.weight(1f).height(48.dp),
                    ) { Text("取消") }
                    Button(
                        onClick = { vm.save() },
                        enabled = !vm.acting,
                        colors = ButtonDefaults.buttonColors(
                            // 主键用本池的语义色（司机=深橄榄 / 货主=深蓝 / 批发商=深金）—— 这三个色
                            // 本来就是"圆底用它 16% 透明、字用它本身"的深色，白字压得住（对比度 ≥ 7:1）
                            containerColor = poolAccent(pool),
                            contentColor = Color.White,
                        ),
                        modifier = Modifier.weight(1f).height(48.dp),
                    ) { Text(if (vm.acting) "保存中…" else "保存") }
                }
                Spacer(Modifier.height(24.dp))
            }
            }
        }
    }
    // 商品维度批量调价抽屉（批发商管理页：同一商品可同时修改多个批发商专属价）
    if (vm.showBatch) {
        BatchPriceSheet(
            products = vm.products,
            members = vm.users,
            lockedShipperId = null,
            acting = vm.acting,
            onExecute = { sids, pids, m, v -> vm.batchPrice(sids, pids, m, v) { vm.showBatch = false } },
            onDismiss = { vm.showBatch = false },
        )
    }
}

/**
 * 车型 → 司机的**计费口径**中文。
 *
 * ⚠️ 这一处原来把 `small` 写成了「大车司机」（`"small" -> "大车司机"; "large" -> "大车司机"`），
 * 于是小车司机在列表上和大车司机长得一模一样 —— 而车型决定他的计费口径，
 * 看错了就会在"为什么他的账单是这个数"上白查半天。名单只有这一处，卡片和弹窗共用。
 */
internal fun driverKindLabel(vehicleType: String?): String = when (vehicleType) {
    "trailer" -> "挂车司机"
    "small" -> "小车司机"
    "large" -> "大车司机"
    else -> "未设置车型"
}

/** 司机车队摘要：把"谁还没配车"摆在最上面（这是派单时最容易踩空的一件事）。 */
@Composable
private fun DriverFleetSummary(vm: UsersManageViewModel) {
    val boundDrivers = vm.users.count { u -> vm.vehiclesOf(u.id).isNotEmpty() }
    val unbound = vm.users.size - boundDrivers
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TintedIcon(Icons.Default.Groups, Color(DriverLime), size = 20.dp, container = 38.dp)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text("司机团队", style = MaterialTheme.typography.titleMedium)
                Text(
                    "共 " + vm.users.size + " 人 · 已配车 " + boundDrivers + " · 未配车 " + unbound +
                        " · 车队共 " + vm.vehicles.size + " 辆",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        if (unbound > 0) {
            Spacer(Modifier.height(8.dp))
            Text(
                "有 " + unbound + " 位司机还没配车 —— 点卡片上的「配车」就能绑，" +
                    "也可以点右上角「车辆」去管整支车队。",
                style = MaterialTheme.typography.bodySmall,
                color = Color(MoneyOrange),
            )
        }
    }
}

@Composable
private fun UserManageCard(
    u: UserDto,
    pool: UserPool,
    vehicles: List<VehicleDto>,
    onEdit: () -> Unit,
    onBindVehicle: () -> Unit,
    onToggleActive: () -> Unit,
    onToggleMember: () -> Unit,
    onSwapRole: () -> Unit,
    onOpenPricing: () -> Unit,
) {
    val accent = poolAccent(pool)
    SectionCard(Modifier.clickable { onEdit() }) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            // 姓氏圆底：扫一眼就能分人（原来整列都是同样的字，认人靠读）
            Box(
                Modifier.size(40.dp).clip(CircleShape).background(accent.copy(alpha = 0.16f)),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    u.fullName.ifBlank { u.phone }.take(1),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    color = accent,
                )
            }
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        u.fullName.ifBlank { u.username },
                        // 16sp 加粗：名册卡的「名称」是同一号字（账户卡 16sp / 车辆卡车牌 titleMedium）
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                    )
                    Spacer(Modifier.width(8.dp))
                    if (u.isMember) {
                        Surface(color = Color(0xFFFFF1C6), shape = MaterialTheme.shapes.small) {
                            Text(
                                "批发商",
                                style = MaterialTheme.typography.labelMedium,
                                color = Color(0xFF7A5900),
                                modifier = Modifier.padding(horizontal = 6.dp, vertical = 1.dp),
                            )
                        }
                    }
                    if (!u.isActive) {
                        Spacer(Modifier.width(6.dp))
                        Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = MaterialTheme.shapes.small) {
                            Text(
                                "已停用",
                                style = MaterialTheme.typography.labelMedium,
                                modifier = Modifier.padding(horizontal = 6.dp, vertical = 1.dp),
                            )
                        }
                    }
                }
                Spacer(Modifier.height(4.dp))
                // 电话走共用件（青绿 Phone 图标 + 前景色号码 + 长按复制），全库一个样。
                // ⚠️ 传的是**账号**、不是 `u.phone`（2026-10-03 · E2E 报告 P1）：软删账号落库的号码
                //    是 `13923111638_del62` 这种内部值。`RosterPhoneRowOf` 会把「号已让给新账号」
                //    画成一句灰字说明，而不是把内部后缀端到卡上（账户页同一处已改）。
                RosterPhoneRowOf(u)
                if (pool == UserPool.DRIVERS) {
                    Spacer(Modifier.height(6.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        MiniChip(driverKindLabel(u.vehicleType), Color(NavBlue))
                        Spacer(Modifier.width(6.dp))
                        // 计费口径优先显示**后端算好的那句话**（和账单同源）：
                        // 界面自己拼一句"按单 X 元"必然和账单口径分叉。
                        val pay = u.paySummary.ifBlank {
                            when {
                                !u.driverRuleName.isNullOrBlank() -> u.driverRuleName
                                u.salary != null && u.salary != "0" -> "月工资 ¥" + formatMoney(u.salary)
                                else -> ""
                            }
                        }
                        if (pay.isNotBlank()) MiniChip(pay, Color(MoneyOrange))
                    }
                }
            }
            // 「定价」是批发商池的业务入口，留在卡头 —— 它不是通用卡片动作，不该混进下面那一行。
            if (pool == UserPool.MEMBERS) {
                Button(onClick = onOpenPricing, contentPadding = PaddingValues(horizontal = 12.dp)) {
                    Text("定价")
                }
            }
        }

        // ---- 车辆行（只有司机池）：他开哪辆车 ----
        if (pool == UserPool.DRIVERS) {
            Spacer(Modifier.height(10.dp))
            val plates = vehicles.joinToString("、") { it.plateNo }
            Row(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp))
                    .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f))
                    .clickable { onBindVehicle() }
                    .padding(horizontal = 12.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    Icons.Default.LocalShipping,
                    contentDescription = null,
                    tint = if (plates.isEmpty()) MaterialTheme.colorScheme.onSurfaceVariant else Color(DriverLime),
                    modifier = Modifier.size(18.dp),
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    if (plates.isEmpty()) "未配车" else plates,
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (plates.isEmpty()) MaterialTheme.colorScheme.onSurfaceVariant
                    else MaterialTheme.colorScheme.onSurface,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    if (plates.isEmpty()) "配车" else "换车 / 解绑",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.primary,
                )
            }
        }

        Spacer(Modifier.height(8.dp))
        // ---- 卡片动作（规范 §4.2c）：形态一律"12% 语义色圈底 + 同色图标"，
        //      位置是"危险最左、编辑最右"（惯用手是右手）。原来这里是三个文字键平铺 + 卡头一个
        //      裸 18dp 铅笔（用户原话「这个不行」），现在整行都是 CardActionIcon。
        //
        //      ⛔ 「停用 / 启用」只留圈底图标、不配字：这一行最多要塞**四个**动作，
        //      而行宽只有 347dp（411dp 屏 − 列表 32 − 卡片 32），「设为批发商」这种五字标签
        //      一个就占 112dp，四个带字的一行装不下。危险的那一个又恰恰最不该是个好按的带字大键
        //      —— 收成圈底图标，位置（最左）与色（提醒 / 成功）已经把它说清楚了。
        //      别的动作都给字：三个池之间差一层语义就点错人。
        Row(verticalAlignment = Alignment.CenterVertically) {
            CardActionIcon(
                icon = if (u.isActive) Icons.Default.Pause else Icons.Default.PlayArrow,
                contentDescription = if (u.isActive) "停用" else "启用",
                tint = if (u.isActive) Color(WarningAmber) else Success,
                onClick = onToggleActive,
                size = 15.dp,
                container = 30.dp,
            )
            if (pool == UserPool.SHIPPERS || pool == UserPool.MEMBERS) {
                Spacer(Modifier.width(10.dp))
                CardActionIcon(
                    icon = if (u.isMember) Icons.Default.Stars else Icons.Default.StarOutline,
                    contentDescription = if (u.isMember) "取消批发商" else "设为批发商",
                    // 批发商金：这个动作改的是"他在哪个池"，色跟那个池走。
                    tint = Color(MemberGold),
                    onClick = onToggleMember,
                    label = if (u.isMember) "取消批发商" else "设为批发商",
                    size = 15.dp,
                    container = 30.dp,
                )
            }
            Spacer(Modifier.width(10.dp))
            CardActionIcon(
                icon = Icons.Default.SwapHoriz,
                contentDescription = if (u.role == "shipper") "转司机" else "转货主",
                // 转到哪个池，就用那个池的模块色（司机黄绿 / 货主深青）。
                tint = if (u.role == "shipper") Color(DriverLime) else Color(InventoryTeal),
                onClick = onSwapRole,
                label = if (u.role == "shipper") "转司机" else "转货主",
                size = 15.dp,
                container = 30.dp,
            )
            // 编辑固定在最右：与车辆页、地址页同一套手势语。
            Spacer(Modifier.weight(1f))
            CardActionIcon(
                icon = Icons.Default.Edit,
                contentDescription = "编辑",
                tint = Color(NavBlue),
                onClick = onEdit,
                label = "编辑",
                size = 15.dp,
                container = 30.dp,
            )
        }
    }
}

/** 每个池一种强调色（与工作台里该模块的语义色同族；圆底用它 16% 透明、字用它本身）。 */
private fun poolAccent(pool: UserPool): Color = when (pool) {
    UserPool.DRIVERS -> Color(0xFF5A6B00)    // 司机黄绿（与「司机管理」同族）
    UserPool.SHIPPERS -> Color(0xFF0A3168)   // 货主蓝
    UserPool.MEMBERS -> Color(0xFF7A5900)    // 批发商金（与卡上的「批发商」徽章同色）
}

/**
 * **这一池的模块色** = 工作台里那一格的语义色（规范 §2 / §4.3「染模块语义色…一色一功能」）。
 *
 * ⛔ 与上面的 [poolAccent] 是**两件事，别合并**：那个是「姓氏圆底 / 角色字」用的**深色**
 * （浅底上要够黑才看得清，判据 `_check_users_ui.py` 钉着那三个值一个字不许动）；这个是
 * 「分类胶囊 / 右下角 FAB」用的**模块色**，要与工作台那一格对得上 ——
 * 用户 2026-10-05 说「你并没有按照我们的设计规范进行设计」，指的就是这里原来借了
 * 货主管理的深青 `InventoryTeal`：批发商那一页的胶囊和工作台那一格（金）对不上。
 */
private fun poolModuleColor(pool: UserPool): Color = when (pool) {
    UserPool.DRIVERS -> Color(DriverLime)      // 司机管理：黄绿
    UserPool.SHIPPERS -> Color(InventoryTeal)  // 货主管理：深青
    UserPool.MEMBERS -> Color(MemberGold)      // 批发商管理：金
}

/**
 * 压在 [poolModuleColor] 上的字色（右下角那颗 Extended FAB 的字与图标）。
 *
 * 三个模块色的亮度差得很远，白字不是处处能用：黄绿 `#CDDC39` 上白字只有 1.4:1，
 * 所以司机池配深橄榄 [OnDriverLime]（≈8:1）；深青 `#00A8A8` 上白字 2.9:1、金 `#F5A623`
 * 上白字 2.0:1，**都过不了 AA 的 4.5:1**，所以货主池配深青 `#00312F`（≈4.7:1）、
 * 批发商池配深金棕 `#3A2A00`（≈6.9:1）。
 *
 * ⛔ 别顺手改成一律 `Color.White`：那三个值不是审美，是白字真看不清。
 */
private fun poolOnColor(pool: UserPool): Color = when (pool) {
    UserPool.DRIVERS -> Color(OnDriverLime)
    UserPool.SHIPPERS -> Color(0xFF00312F)
    UserPool.MEMBERS -> Color(0xFF3A2A00)
}

/**
 * **商品可见范围**第二层：分类 × 商品的一张清单，勾上的才给他看（2026-10-06 · CHG-0062）。
 *
 * ## 为什么是"抽屉里的第二层"而不是抽屉里那一段
 * 清单带左栏（分类）＋逐行三态勾选，抽屉里原来那段固定 220dp 滚动区装不下；而且清单本身要能滚
 * （`LazyColumn` 塞进 `verticalScroll` 里会被量成无限高，直接崩）。所以它是**同一个抽屉里的第二层**：
 * 顶栏一条返回箭头 ＋ 整屏清单 —— 与地址页「管理分类」同一套写法（`ui/shipper/AddressScreen.kt`）。
 *
 * ## 为什么默认是「全部商品」
 * 这个开关一旦默认成"只给勾选的"，**所有老账号上线那一刻选品页就全空了** ——
 * 而真正的原因藏在一条数据库迁移里，界面上只表现为"商品全没了"。
 * 所以默认不限制，要限制必须由人明确点。
 *
 * ## 为什么"配完一个商品都看不到"要拦住
 * 那等于让他什么都看不到。用户想这么干的时候，正确路径是先把范围切过去、再逐个勾，
 * 而不是交一份空的上来 —— 交空的只说明他还没勾（或者是误操作），不是他的本意。
 * 注意判据是"他到底能看见几个"，不是"勾了几个"：只勾分类、一件单品都不勾是完全合法的。
 *
 * ## 关掉一行与关掉一类的区别（这一层最容易看错的一处）
 * 「不给看」记的是**排除**，而且排除**优先于**授权：
 *  - 关一个商品 ⇒ 单品排除（他在别的分类/单选里怎么配都压不过它）；
 *  - custom 档关一个分类 ⇒ 撤掉整类授权（这一类整类不给）；
 *  - all 档关一个分类 ⇒ 分类排除（**以后**新建到这个分类的商品也自动看不见 —— 只逐件关的话，
 *    明天新加的商品又会冒出来，"这一类不给"就不是他的本意了）。
 * 被整类关掉的那些行**从列表里藏掉会更糟**：用户会以为那个商品不存在。这里留着、写清原因，
 * 但把勾选禁掉（`rowLocked`）—— 点了没反应比点不了更让人困惑。
 */
@Composable
private fun ProductVisibilityLayer(
    vm: UsersManageViewModel,
    accent: Color,
    onBack: () -> Unit,
) {
    // 先算一次"现在到底看得见几个"，下面三处都用它（每行都算一遍 = 每帧扫全表）
    val seen = vm.visibleProductIds()
    val hiddenCats = vm.draftHiddenCategories
    Column(
        Modifier
            .fillMaxSize()
            .padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
            }
            Text("商品可见范围", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ScopeChip("全部商品", vm.draftScope != "custom") { vm.setScope("all") }
            ScopeChip("只给勾选的", vm.draftScope == "custom") { vm.setScope("custom") }
        }
        Text(
            if (vm.draftScope == "custom") {
                "已授权 ${vm.draftAllowCategories.size} 个分类 · 另加 ${vm.draftVisible.size} 个单品" +
                    " · 实际可见 ${seen.size} 个"
            } else {
                "全部商品 · 实际可见 ${seen.size} 个"
            } + if (hiddenCats.isEmpty() && vm.draftHidden.isEmpty()) "" else
                " · 已关掉 ${vm.draftHidden.size + hiddenCats.size} 项",
            style = MaterialTheme.typography.bodySmall,
            color = if (seen.isEmpty()) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
        )
        ProductCheckList(
            products = vm.products,
            checkedIds = seen,
            onToggleProduct = { id -> vm.products.firstOrNull { it.id == id }?.let { vm.toggleVisibleProduct(it) } },
            onToggleCategory = { name, targetOn, ids -> vm.toggleVisibleCategory(name, targetOn, ids) },
            keyword = vm.visibilityQuery,
            onKeywordChange = { vm.visibilityQuery = it },
            modifier = Modifier.weight(1f),
            loading = vm.visibilityLoading,
            emptyText = "商品库里还没有商品",
            searchPlaceholder = "搜索商品名称",
            // 被整类关掉的行勾不了：点一个"怎么点都不会变"的勾选框比点不了更让人困惑。
            // 要单独放开某一件，先把这一类打开（分类头那一格）。
            rowLocked = { p -> categoryOf(p) in hiddenCats },
            rowNote = { p ->
                when {
                    categoryOf(p) in hiddenCats -> "这一类已整类关掉 —— 要单独放开，先把这一类打开"
                    p.id in vm.draftHidden -> "已单独关掉"
                    vm.draftScope == "custom" && categoryOf(p) !in vm.draftAllowCategories &&
                        p.id !in vm.draftVisible -> "这一类的商品没授权给他（勾上＝单独加这一件）"
                    else -> null
                }
            },
        )
        // 这句不是「提示」而是这一层的口径说明：它随时都要看得见（Hint 会被用户关掉、
        // 首轮之后默认不显示），所以走 Text 而不是 Hint（判据 _tools/qa/_check_hints.py 管这个）。
        Text(
            "改这里只是改草稿：回到上一层按「保存」才会写进去。",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(12.dp))
    }
}

/** 可见范围那一格的汇总：档位 ＋ 授权/排除的量 ＋ **实际可见几个**（最有用的一个数）。 */
private fun visibilitySummary(vm: UsersManageViewModel): String {
    val off = vm.draftHidden.size + vm.draftHiddenCategories.size
    val who = if (vm.draftScope == "custom") {
        "只给勾选的（${vm.draftAllowCategories.size} 个分类 ＋ ${vm.draftVisible.size} 个单品）"
    } else {
        "全部商品"
    }
    return "$who · 实际可见 ${vm.visibleProductIds().size} 个" + if (off > 0) " · 已关掉 $off 项" else ""
}

@Composable
private fun ScopeChip(text: String, selected: Boolean, onClick: () -> Unit) {
    Surface(
        shape = MaterialTheme.shapes.small,
        color = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceVariant,
        border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        modifier = Modifier.clickable { onClick() },
    ) {
        Text(
            text,
            style = MaterialTheme.typography.bodyMedium,
            color = if (selected) Color.White else MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
        )
    }
}
