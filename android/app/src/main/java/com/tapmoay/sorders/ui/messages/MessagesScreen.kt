package com.tapmoay.sorders.ui.messages

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.NotificationDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.util.formatDateTime

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MessagesScreen(
    container: AppContainer,
    onBack: () -> Unit,
    /**
     * 点一条**能查的消息**的去处 —— 传的是**整条路由**（`?focus=<商品号>` 已经拼好）。
     *
     * 为什么由这一页决定去哪一页：该去哪一页由 **type + 当前角色 + payload** 三样共同决定，
     * 而这三样都在这一页手里（`ui/messages/MessageGrading.kt` 的 `noticeRoute`，纯函数、
     * 一处判断；退货申请那半条线仍在 `NoticeRouting.noticeReturnRoute` 里，`noticeRoute`
     * 第一句就调它，⛔ 没有第二份实现）。让三个调用方各自再写一遍"哪种消息去哪个端"，
     * 就是同一套路由的第二、三份实现 —— 改了这边忘了那边的那一天，表现是
     * "点了通知去了错误的那一页、或者 403"。
     *
     * ⛔ 算不出来时（type 不认识 / 角色对不上 / payload 里缺那个键）**不调这个回调** = 不跳，
     *    绝不瞎跳。默认空实现 = 老调用方/预览不会因此崩。
     */
    onOpenRoute: (String) -> Unit = {},
    /** true = 作为底部导航内容内嵌（隐藏返回矢头/双重 inset） */
    embedded: Boolean = false,
) {
    val vm: MessagesViewModel = appViewModel { MessagesViewModel(container) }
    val unread by container.realtimeHub.unreadCount.collectAsState()
    val snackbar = remember { SnackbarHostState() }

    // 当前角色的 key（同步缓存，登录/登出时由 TokenStore 维护）。
    // ⚠️ 读**原文**而不是 `Role.fromKey(...)`：那个函数对空串会回落成 SHIPPER，
    //    于是"会话还没恢复"的那一瞬间会被当成货主（`NoticeRouting.kt` 头部解释了后果）。
    val roleKey = container.tokenStore.cachedRole()

    // 删除确认对话框：null=不弹；emptyList=清空确认
    var pendingBatchDelete by remember { mutableStateOf<List<Long>?>(null) }

    // 每次进入这一页都重新拉一次列表。
    // 为什么必须有：这个页面是底栏的一个 Tab，ViewModel 挂在 Activity 上**不会随切页销毁**，
    // 而 init 里的 load() 只跑一次 —— 以前从这里切出去再回来，看到的是很久以前的那份快照
    // （别人在别的设备上发的消息、或者别处改动过的已读状态都看不到）。
    LaunchedEffect(Unit) { vm.load(silent = vm.messages.isNotEmpty()) }

    // 一次性提示（成功/失败都用它说人话）。
    // ⚠️ 必须走 `OneShotSnackbar`：它在**显示之前**就把 `notice` 置空。
    //    以前是 `showSnackbar(it)` 之后才置空，而 showSnackbar 会挂起几秒 ——
    //    用户在这几秒里切到别的 Tab，协程被取消，置空那一行永远不执行，
    //    切回来时 `notice` 还在，于是**提示条又冒出来一次**（2026-09-18 用户报的）。
    OneShotSnackbar(snackbar, vm.notice, onConsumed = { vm.notice = null })

    Box(Modifier.fillMaxSize()) {
    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = {
                Text(if (vm.selectionMode) ("已选 " + vm.selectedIds.size + " 条") else "消息中心")
            },
            windowInsets = if (embedded) WindowInsets(0, 0, 0, 0) else TopAppBarDefaults.windowInsets,
            navigationIcon = {
                when {
                    vm.selectionMode -> IconButton(onClick = { vm.exitSelection() }) {
                        Icon(Icons.Default.Close, contentDescription = "取消多选")
                    }
                    !embedded -> IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                }
            },
            actions = {
                if (vm.selectionMode) {
                    TextButton(
                        enabled = vm.selectedIds.isNotEmpty() && !vm.busy,
                        onClick = { pendingBatchDelete = vm.selectedIds.toList() },
                    ) {
                        Text("删除(" + vm.selectedIds.size + ")", color = MaterialTheme.colorScheme.error)
                    }
                } else {
                    // ⚠️ **常显，不许因为没有未读就把它藏起来**（2026-09-20 用户第二次报同一件事：
                    //    「消息中心没有全部已读的功能了……其他 2 个都有」——实测司机端 8 条消息全已读，
                    //    按钮按老条件被隐藏；派单员那边有 12 条未读，所以看得到）。
                    //    2026-09-17 那次报的也是这件事，当时的修法（补 `listUnread` 判据）只放宽了
                    //    触发条件，没解决"看起来没有"：只要恰好没有未读，功能就又"消失"一次。
                    //    现在改成一直画出来，没有未读时**置灰** —— 灰 = 现在没什么可标的，而不是没这功能。
                    //    `unread` 是全局计数（`realtimeHub.unreadCount`，靠 socket 推送与
                    //    `syncUnreadFromApi` 维护），`listUnread` 是列表里这些消息的未读数；
                    //    「全部已读」真正作用的对象是列表里这些消息，两个都算上才不会误灰。
                    val listUnread = vm.messages.count { it.readAt == null }
                    TextButton(
                        enabled = !vm.busy && (unread > 0 || listUnread > 0),
                        onClick = { vm.markAllRead() },
                    ) { Text("全部已读") }
                    if (vm.messages.isNotEmpty()) {
                        TextButton(
                            enabled = !vm.busy,
                            onClick = { pendingBatchDelete = emptyList() },
                        ) {
                            Text("清空", color = MaterialTheme.colorScheme.error)
                        }
                    }
                    IconButton(enabled = !vm.busy, onClick = { vm.load(silent = true) }) {
                        Icon(Icons.Default.Refresh, contentDescription = "刷新")
                    }
                }
            },
        )
        when {
            vm.loading -> LoadingBox()
            vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
            vm.messages.isEmpty() -> EmptyView("暂无消息")
            else -> LazyColumn(
                Modifier.fillMaxSize(),
                contentPadding = PaddingValues(12.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                items(vm.messages, key = { it.id }) { m ->
                    // 这一条点进去能去哪一页（整条路由，`?focus=` 已经拼好）。
                    // null = 认不出来 / 角色对不上 / payload 里缺那个键 ⇒ **不跳**。
                    // ⚠️ 卡片上那颗「查看… ›」与点击跳转用的是**同一个** route —— 不是各算一遍。
                    val route = noticeRoute(roleKey, m.type, m.payload)
                    MessageCard(
                        m = m,
                        route = route,
                        selectionMode = vm.selectionMode,
                        selected = m.id in vm.selectedIds,
                        onClick = {
                            if (vm.selectionMode) {
                                vm.toggleSelect(m.id)
                            } else {
                                vm.markRead(m)
                                // 能查的消息 → **直达那一页**（2026-09-21 用户要求：「到消息中心哦。
                                // 其实本来就要做到直达的」；2026-10-11 FEAT-0019 把它扩到
                                // 库存 / 收款 / 应付 / 发票 / 价格 / 账号）。路由整条由
                                // `MessageGrading.noticeRoute` 一处算好（type + 当前角色 + payload）。
                                // ⛔ 算不出来时 route 就是 null = **不跳**：以前这里还有一条
                                //    「有 order_id 就开订单详情」的兜底，于是"库存预警点进去开了一张
                                //    订单"这种瞎跳；现在那条兜底只留给**认不出的 type**
                                //    （见 noticeRoute 的 SYSTEM 那一支）。
                                route?.let { onOpenRoute(it) }
                            }
                        },
                        onLongClick = { if (!vm.selectionMode) vm.enterSelection(m.id) },
                        onDelete = { vm.delete(m) },
                    )
                }
                // 「加载更多」：服务端说了还有更早的消息（响应头 X-Truncated）才显示。
                // R14-8（2026-09-19 审计）：这条接口原来没有分页、也不回报截断，
                // 于是第 201 条以前的旧消息在 App 里一个入口都没有。
                if (vm.hasMore) {
                    item(key = "load-more") {
                        Box(Modifier.fillMaxWidth().padding(vertical = 10.dp), contentAlignment = Alignment.Center) {
                            if (vm.loadingMore) {
                                CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                            } else {
                                TextButton(onClick = { vm.loadMore() }) { Text("加载更早的消息") }
                            }
                        }
                    }
                }
            }
        }
    }

        SnackbarHost(
            hostState = snackbar,
            modifier = Modifier.align(Alignment.BottomCenter),
        )
    }

    // 批量删除确认
    val batchIds = pendingBatchDelete
    if (batchIds != null) {
        CardAlertDialog(
            tone = DialogTone.DANGER,
            onDismissRequest = { pendingBatchDelete = null },
            title = { Text(if (batchIds.isEmpty()) "清空全部消息" else "删除消息") },
            text = {
                Text(
                    // 文案写清"清空的是谁的消息"：这条界线以前是含糊的——
                    // 派单员的列表里混着别人的消息，而清空只清自己的。
                    // ⚠️ Text 不渲染 Markdown，别在这里写星号。
                    if (batchIds.isEmpty()) "将删除发给当前账户的全部消息（当前 ${vm.messages.size} 条），删除后不可恢复。确定清空吗？"
                    else ("确定删除选中的 " + batchIds.size + " 条消息吗？删除后不可恢复。")
                )
            },
            confirmButton = {
                TextButton(
                    enabled = !vm.busy,
                    onClick = {
                        pendingBatchDelete = null
                        if (batchIds.isEmpty()) vm.clearAll() else vm.deleteSelected()
                    },
                ) {
                    Text("删除", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { pendingBatchDelete = null }) { Text("取消") }
            },
        )
    }
}

// ---------------------------------------------------------------------------
// 卡片：未读才有的"分级样式"（FEAT-0019，用户 2026-10-11 口径 + 已过目的样本与样式表）
// ---------------------------------------------------------------------------

/**
 * 未读卡片最左边那一条的**几何**（照用户已过目的样本 `_tmp/palette_demo/messages.html`）：
 * 6px 宽、方角（圆角 3px —— 样本原文 `width:6px; border-radius:3px`）、上下各留 10px、左缩进 8px。
 *
 * ⛔ **只有未读才画**：用户的铁律是「只有未读才有这个样式，已读所有消息一个样」—— 已读的卡片
 *    没有竖条、没有彩标、高亮也一并去掉，整条灰调。改这里之前先看那句。
 */
/**
 * 未读卡片的**阴影**（用户 2026-10-11 口径：「未读的时候会有阴影，读了就不会有」——用来做"体积感"，
 * 取代原来那层"没读就有一层灰"的灰尘遮罩）。⛔ 别改回"未读用更深的底色"：用户已经否掉那种做法，
 * 理由是"现在已经有颜色做区别了，有颜色=没读、没颜色=已读"。
 */
private val MESSAGE_CARD_SHADOW = 3.dp

private val MESSAGE_BAR_WIDTH = 6.dp
private val MESSAGE_BAR_SHAPE = RoundedCornerShape(3.dp)
private val MESSAGE_BAR_INSET_START = 8.dp
private val MESSAGE_BAR_INSET_VERTICAL = 10.dp

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun MessageCard(
    m: NotificationDto,
    /** 点这张卡去哪儿（null = 不跳、也不画「查看… ›」）。由列表那一处在 `noticeRoute` 算好。 */
    route: String?,
    selectionMode: Boolean,
    selected: Boolean,
    onClick: () -> Unit,
    onLongClick: () -> Unit,
    onDelete: () -> Unit,
) {
    val unread = m.readAt == null
    val family = familyOf(m.type)
    val risk = riskOf(m.severity)
    // 已读：**一个重点色都不上**（连被点名的词也不再加粗）—— 用户：「已读：无竖条、无彩标、
    // 高亮也一并去掉，整条灰调」。
    val words = if (unread) emphasisWords(m.payload) else emptyList()
    val titleColor = if (unread) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurfaceVariant
    val bodyColor = if (unread) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.outline
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .combinedClickable(onClick = onClick, onLongClick = onLongClick),
        shape = MaterialTheme.shapes.medium,
        // 2026-10-11（用户口径，逐字）：「以前是因为没有搞颜色，所以会搞一个——如果他没有读的话会有一层灰，
        //    就是一层的灰尘遮罩……现在我们已经有了颜色做了区别，**所以不需要搞这个灰尘了**：
        //    有颜色就表示还没有读、没有颜色就表示已经读了。另外为了方便做一个区别，**在那卡片上加一层阴影**，
        //    就是未读的时候会有阴影、读了就不会有 —— 体积感。」
        // ⇒ 未读**不再**用更深的容器色（那层"灰"），改成「同一个底色 + 一层阴影」；
        //    已读照旧：无竖条、无彩标、无高亮、**无阴影**，整条灰调。
        color = when {
            selected -> MaterialTheme.colorScheme.primaryContainer
            else -> MaterialTheme.colorScheme.surface
        },
        tonalElevation = 0.dp,
        shadowElevation = if (unread) MESSAGE_CARD_SHADOW else 0.dp,
        border = if (selected) BorderStroke(1.dp, MaterialTheme.colorScheme.primary) else null,
    ) {
        // 竖条要与内容**一样高**，所以这一行按内容的最小固有高度排（这样下面 fillMaxHeight 才有意义）
        Row(
            Modifier.fillMaxWidth().height(IntrinsicSize.Min),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (unread) {
                Spacer(
                    Modifier
                        .padding(
                            start = MESSAGE_BAR_INSET_START,
                            top = MESSAGE_BAR_INSET_VERTICAL,
                            bottom = MESSAGE_BAR_INSET_VERTICAL,
                        )
                        .width(MESSAGE_BAR_WIDTH)
                        .fillMaxHeight()
                        .background(Color(family.color), MESSAGE_BAR_SHAPE),
                )
            }
            if (selectionMode) {
                Spacer(Modifier.width(6.dp))
                Checkbox(checked = selected, onCheckedChange = { onClick() })
                Spacer(Modifier.width(4.dp))
            }
            Column(
                Modifier
                    .weight(1f)
                    .padding(
                        start = if (unread || selectionMode) 13.dp else 14.dp,
                        end = 13.dp,
                        top = 11.dp,
                        bottom = 11.dp,
                    ),
            ) {
                // ① 标签行：未读＝类型小标签（同色浅底深字）+ 右侧时间；已读＝一个灰「已读」
                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (unread) {
                        MessageFamilyChip(label = messageLabel(m.type, m.payload), color = family.color)
                    } else {
                        Text(
                            "已读",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.outline,
                        )
                    }
                    Spacer(Modifier.weight(1f))
                    Text(
                        formatDateTime(m.createdAt),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.outline,
                    )
                }
                Spacer(Modifier.height(6.dp))
                // ② 标题与正文：只有 `payload["emphasis"]` 里被**业务点名**的词与数字上色，
                //    其余一律正常深色（用户：「全是重点就是没有重点」）。
                EmphasisText(
                    text = m.title.ifBlank { "系统通知" },
                    words = words,
                    risk = risk,
                    style = MaterialTheme.typography.titleSmall,
                    color = titleColor,
                    maxLines = 2,
                    weight = FontWeight.SemiBold,
                )
                if (m.content.isNotBlank()) {
                    Spacer(Modifier.height(3.dp))
                    EmphasisText(
                        text = m.content,
                        words = words,
                        risk = risk,
                        style = MaterialTheme.typography.bodyMedium,
                        color = bodyColor,
                        maxLines = 3,
                    )
                }
                // ③ 链接：**只有未读、且真的能跳**才画（画了却点了没反应，比不画更糟）。
                val action = noticeActionLabel(m.type)
                if (unread && action != null && route != null) {
                    Spacer(Modifier.height(7.dp))
                    Text(
                        action + " ›",
                        style = MaterialTheme.typography.labelMedium,
                        color = Color(family.color),
                        fontWeight = FontWeight.SemiBold,
                    )
                }
            }
            if (!selectionMode) {
                IconButton(onClick = onDelete) {
                    Icon(
                        Icons.Default.Delete,
                        contentDescription = "删除",
                        modifier = Modifier.size(18.dp),
                        tint = MaterialTheme.colorScheme.outline,
                    )
                }
            }
        }
    }
}

/** 未读卡片上的类型小标签：同色浅底 + 同色深字（样本原文 `background:<色>1f` / `color:<色>`）。 */
@Composable
private fun MessageFamilyChip(label: String, color: Long) {
    Surface(
        color = Color(color).copy(alpha = 0.12f),
        shape = RoundedCornerShape(6.dp),
    ) {
        Text(
            label,
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.SemiBold,
            color = Color(color),
            modifier = Modifier.padding(horizontal = 7.dp, vertical = 2.dp),
        )
    }
}

/**
 * 只有**被点名的片段**上色加粗的正文；其余文字原样（正常深色）。
 *
 * 风险色由 `emphasisColor(risk)` **一处**给：danger = 红、warn = 橙、info = 不上风险色
 * （只加粗 —— 样本里「收款 320.00 元」的重点数字就是常规深色加粗）。
 * `words` 为空 / 词在正文里找不到 = 那一段原样，⛔ 绝不退化成整行上色。
 */
@Composable
private fun EmphasisText(
    text: String,
    words: List<String>,
    risk: MessageRisk,
    style: TextStyle,
    color: Color,
    maxLines: Int,
    weight: FontWeight? = null,
) {
    val accent = emphasisColor(risk)
    val annotated = buildAnnotatedString {
        splitByEmphasis(text, words).forEach { span ->
            if (!span.emphasized) {
                append(span.text)
            } else {
                withStyle(
                    SpanStyle(
                        color = accent?.let { Color(it) } ?: color,
                        fontWeight = FontWeight.Bold,
                    )
                ) { append(span.text) }
            }
        }
    }
    Text(annotated, style = style, color = color, maxLines = maxLines, fontWeight = weight)
}
