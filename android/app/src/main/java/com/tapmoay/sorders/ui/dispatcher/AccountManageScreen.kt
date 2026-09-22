package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
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
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

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
                // 与其余派单端页面同一个口径（顶栏跟页面底色走，不单独刷一块白）
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
            )
        },
        floatingActionButton = {
            FloatingActionButton(onClick = { vm.openCreate() }) {
                Icon(Icons.Default.Add, contentDescription = "新增账户")
            }
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                vm.loading -> LoadingBox()
                vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                vm.users.isEmpty() -> EmptyView("暂无账户，点右下角 + 创建", Modifier.align(Alignment.Center))
                else -> LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
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
                                    Modifier.fillMaxWidth().height(140.dp),
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
                    items(vm.shown, key = { it.id }) { u ->
                        AccountCard(
                            u = u,
                            onEdit = { vm.openEdit(u) },
                            onToggle = { vm.toggleActive(u) },
                            onDelete = { vm.deleting = u },
                        )
                    }
                    item { Spacer(Modifier.height(72.dp)) }
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
                Text(
                    "确认删除「" + (target.fullName.ifBlank { target.phone }) + " / " + target.phone +
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
 * | 3 | 左：删除 / 停用启用 · 右：编辑 | 用户 2026-09-22：「编辑一定在右边（惯用手是右手）…相反的操作就在左边」 |
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun AccountCard(
    u: UserDto,
    onEdit: () -> Unit,
    onToggle: () -> Unit,
    onDelete: () -> Unit,
) {
    val ctx = LocalContext.current
    // 「已复制」回执：与订单详情同一套写法（`copyTextToClipboard` 在 API 33+ 自己会弹系统浮层，
    // 那时它返回 false，这条就不画 —— 两条提示叠在一起反而看不清复制了什么）
    var copied by remember { mutableStateOf(false) }
    LaunchedEffect(copied) {
        if (copied) {
            delay(2000)
            copied = false
        }
    }

    SectionCard {
        // ---- 行1：姓名 + 角色 + 状态（同一行）----
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(
                u.fullName.ifBlank { u.phone },
                fontWeight = FontWeight.Bold,
                fontSize = 16.sp,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.width(8.dp))
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
            // 停用是**异常状态**，只在它成立时出现 —— 每张卡都挂一个"正常"徽章，
            // 真正要看的那一个反而沉进背景里了。
            if (!u.isActive) {
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

        // ---- 行2：手机号（长按复制）----
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                u.phone,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                fontSize = 15.sp,
                modifier = Modifier.combinedClickable(
                    onClick = {},
                    onLongClickLabel = "复制手机号",
                    onLongClick = {
                        if (copyTextToClipboard(ctx, "手机号", u.phone)) copied = true
                    },
                ),
            )
            if (copied) {
                Spacer(Modifier.width(8.dp))
                Text("已复制", fontSize = 12.sp, color = MaterialTheme.colorScheme.primary)
            }
        }
        Spacer(Modifier.height(4.dp))

        // ---- 行3：动作行（左＝相反/警示 · 右＝编辑）----
        // ⚠️ 这个控件**不是这一页自己的**：`ui/common/Components.kt::CardActionIcon`（传 label
        //    就是"圈底图标 + 文字"、不传就是卡片上那个纯图标）。原来这一页自己养了一个
        //    `AccountAction`，与订单卡那个 `CardActionIcon` 是同一件事的两份实现 ——
        //    圆底画法本来就共用 `TintedIcon`，差别只在有没有那行字，2026-09-22 收成一个可选参数。
        //    ⛔ 别再在这一页（或任何页）新建一个"圈底动作"控件：位置规范（左/右）与形态（圈底）
        //    都该只有一处实现，否则下一次改样式必然漏掉其中一页。
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            // 左栏：先删除（最不可逆的那个）再停用/启用
            AccountAction("删除", Icons.Default.DeleteOutline, Color(MessageRed), onDelete)
            AccountAction(
                if (u.isActive) "停用" else "启用",
                if (u.isActive) Icons.Default.Pause else Icons.Default.PlayArrow,
                if (u.isActive) Color(MoneyOrange) else Color(MgrGreen),
                onToggle,
            )
            Spacer(Modifier.weight(1f))
            // 右栏：编辑（惯用手那一侧）
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
