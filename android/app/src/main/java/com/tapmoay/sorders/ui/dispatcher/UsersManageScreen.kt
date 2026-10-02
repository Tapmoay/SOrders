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
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.data.remote.dto.UserDto
import com.tapmoay.sorders.data.remote.dto.VehicleDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.DriverLime
import com.tapmoay.sorders.ui.theme.InventoryTeal
import com.tapmoay.sorders.ui.theme.MemberGold
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.ui.theme.NavBlue
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

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = { Text(pool.title) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
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
            FloatingActionButton(onClick = { vm.openCreate() }) {
                Icon(Icons.Default.Add, contentDescription = "新增" + pool.title.removeSuffix("管理"))
            }
        },
    ) { padding ->
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
                                    Modifier.fillMaxWidth().height(140.dp),
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
                            EmptyView("没有匹配「${vm.query}」的账号", Modifier.fillMaxWidth().height(140.dp))
                        }
                    }
                    items(vm.shown, key = { it.id }) { u ->
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
                        ProductVisibilityBlock(
                            scope = vm.draftScope,
                            onScope = { vm.setScope(it) },
                            products = vm.products,
                            selected = vm.draftVisible,
                            onToggle = { vm.toggleVisible(it) },
                            onAll = { vm.selectAllVisible() },
                            onNone = { vm.clearVisible() },
                            loading = vm.visibilityLoading,
                        )
                    }
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
                        style = MaterialTheme.typography.titleSmall,
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
                Text(
                    u.phone,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
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
 * **商品可见范围**（白名单）：勾了的才给他看。
 *
 * ## 为什么默认是「全部商品」
 * 这个开关一旦默认成"只给勾选的"，**所有老账号上线那一刻选品页就全空了** ——
 * 而真正的原因藏在一条数据库迁移里，界面上只表现为"商品全没了"。
 * 所以默认不限制，要限制必须由人明确点。
 *
 * ## 为什么"只给勾选的"却一个都没勾时要拦住
 * 那等于让他什么都看不到。用户想这么干的时候，正确路径是先把范围切过去、再逐个勾，
 * 而不是交一份空的上来 —— 交空的只说明他还没勾（或者是误操作），不是他的本意。
 */
@Composable
private fun ProductVisibilityBlock(
    scope: String,
    onScope: (String) -> Unit,
    products: List<ProductDto>,
    selected: Set<Long>,
    onToggle: (Long) -> Unit,
    onAll: () -> Unit,
    onNone: () -> Unit,
    loading: Boolean,
) {
    Column {
        // 标题不在这里：白卡分组（FormGroup）已经把「商品可见范围」画在卡外了，
        // 这里再写一遍就是同一个标题两处画（2026-10-03 · CHG-0018 从 AlertDialog 搬进抽屉时删的）。
        Hint(
            "决定他在「选择商品」里能看到哪些商品。默认不限制。",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ScopeChip("全部商品", scope != "custom") { onScope("all") }
            ScopeChip("只给勾选的", scope == "custom") { onScope("custom") }
        }
        if (scope == "custom") {
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    if (selected.isEmpty()) "还没勾任何商品 —— 这样他打开选品页会是空的"
                    else "已勾 ${selected.size} / ${products.size} 个商品",
                    style = MaterialTheme.typography.bodySmall,
                    color = if (selected.isEmpty()) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.weight(1f),
                )
                TextButton(onClick = onAll) { Text("全选") }
                TextButton(onClick = onNone) { Text("全不选") }
            }
            if (loading) {
                LoadingBox(Modifier.height(80.dp))
            } else {
                // 固定高度内滚动：商品多了这一段**自己滚**，不把抽屉撑到没边 ——
                // 下面还有「取消 / 保存」，货主名下几十个商品时不能让保存键滚出屏幕。
                Column(Modifier.heightIn(max = 220.dp).verticalScroll(rememberScrollState())) {
                    products.forEach { p ->
                        Row(
                            Modifier.fillMaxWidth().clickable { onToggle(p.id) }.padding(vertical = 4.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Checkbox(checked = p.id in selected, onCheckedChange = { onToggle(p.id) })
                            Column(Modifier.weight(1f)) {
                                Text(p.name, style = MaterialTheme.typography.bodyMedium, maxLines = 1)
                                Text(
                                    "¥" + formatMoney(p.defaultUnitPrice) + " / " + p.unit.ifBlank { "件" } +
                                        if (p.isActive) "" else " · 已下架",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
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
