package com.tapmoay.sorders.ui.home

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGesturesAfterLongPress
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.boundsInRoot
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.zIndex
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.WorkbenchOrder
import com.tapmoay.sorders.core.WorkbenchOrderStore
import com.tapmoay.sorders.ui.common.HintOnce
import com.tapmoay.sorders.ui.common.RoleBadge
import com.tapmoay.sorders.ui.nav.ModuleEntry
import com.tapmoay.sorders.ui.nav.Role

/**
 * 工作台：**图标网格**（像手机桌面，每个图标=一个功能）。
 *
 * ## 2026-09-20 用户要求的第二版外观：**去掉卡片**
 * 原话：「以前是**没有卡片的**，就是底部卡片是没有样式的」。
 * 所以那一层 `Surface`（白底 + 大圆角 + 内边距）整个拿掉了，图标直接铺在页面背景上。
 * 这同时解决了另一个问题：卡片里的网格四周有一圈"留白墙"，17 个图标被挤成小小一堆。
 *
 * ## 图标可以**长按拖动**（用户：「可以随意拖动，就像那个桌面图标一样」）
 * · 长按 300ms 之后进入拖动（`detectDragGesturesAfterLongPress`）—— 与桌面图标同一个手势；
 * · 拖过别人的位置就**就地交换**（不是拖到空白处再落）；
 * · 松手时把顺序存到本机（[WorkbenchOrderStore]，**按角色分开存**）。
 * 顺序的算法与"名单变了怎么套回去"在 `core/WorkbenchOrder.kt`（纯逻辑 + 单测）。
 *
 * ⚠️ **只有一张卡片都不该有**：曾经短暂做过"派单端两张卡片"（第二张装账本那 8 件事），
 * 当天就被用户推翻，那 8 件事改成了一个「账本管理」入口页（报表中心那种形式），
 * 已经收进 [Modules.dispatcherEntries] 里的一格。
 * ⛔ 别再往这里加第二张卡片：网格能装下的东西，分成两张只会让用户在两块区域之间来回找。
 */
@Composable
fun WorkbenchScreen(
    container: AppContainer,
    role: Role,
    entries: List<ModuleEntry>,
    onOpen: (String) -> Unit,
) {
    // 顺序：本机按角色存（换角色不串味，见 WorkbenchOrder 的注释）。
    // ⚠️ 拖动过程中**只改内存**（`savedKeys`），松手才落盘 ——
    //    拖一次要经过十几个格子，每换一次写一次盘就是十几次文件写。
    // ⚠️ `ordered` 是**推出来的**（savedKeys + 当前入口清单），不是另一份状态：
    //    两份状态各自更新，升级后加了新入口时就会出现"网格里少了一格而谁都不报错"。
    val store = remember { WorkbenchOrderStore(container.appContext) }
    var savedKeys by remember(role.key) { mutableStateOf(store.order(role.key)) }
    val ordered = remember(entries, savedKeys) {
        WorkbenchOrder.apply(entries, savedKeys) { it.route }
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item { WelcomeBar(role) }
        item {
            HintOnce(
                container.hintPrefs,
                "workbench.drag",
                "长按图标可以拖动排序",
                modifier = Modifier.padding(start = 4.dp),
            )
        }
        item {
            EntryGrid(
                entries = ordered,
                onOpen = onOpen,
                onMove = { next -> savedKeys = WorkbenchOrder.keys(next) { it.route } },
                onDrop = { store.save(role.key, savedKeys) },
            )
        }
    }
}

/** 欢迎条（原来固定在网格上面；现在它是列表的第一项，滚动时会跟着走） */
@Composable
private fun WelcomeBar(role: Role) {
    Surface(color = MaterialTheme.colorScheme.primaryContainer, shape = MaterialTheme.shapes.large) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(20.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(
                    "工作台",
                    style = MaterialTheme.typography.titleLarge,
                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    when (role) {
                        Role.SHIPPER -> "货主端 · 订单与账本"
                        Role.DRIVER -> "司机端 · 任务与送达"
                        Role.DISPATCHER -> "派单端 · 全量管理"
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.75f),
                )
            }
            RoleBadge(role.key)
        }
    }
}

/** 一屏 4 列（与改造前的工作台同一列数：图标大小、字距都不用重新适应） */
private const val GRID_COLUMNS = 4

/**
 * 4 列图标网格（**工作台上唯一的版式**），支持长按拖动排序。
 *
 * ⛔ 图标格只有 [WorkbenchTile] 一份实现 —— 抄一遍的话，两处迟早长得不一样
 *    （同一个 App 里两种图标大小）。
 * ⛔ 末行**补空位**（不满 4 个也要占满 4 列）：不补的话最后一行的图标会被拉宽，
 *    与上面的格子对不齐（看着像排错了）。
 *
 * ## 拖动是怎么算的（两个坑都踩过）
 * ① **手指位置用绝对坐标，不用位移增量**：图标一旦跟别人换了位置，它的**布局位置**就变了，
 *    而"位移增量"是相对**原来那一格**的 —— 换一次位置图标就会跳开手指（越拖越偏）。
 *    所以这里存的是 `dragPos`（手指在根坐标里的位置），画的时候现算
 *    `dragPos − 这一格现在的中心`，换位置之后自动就对了；
 * ② **`pointerInput` 的 key 只能是 `entry.route`**：把 `entries` 也放进 key 的话，
 *    换一次位置 key 就变、手势被**取消重建** —— 表现是"拖动一格就断"（第一版就是这样）。
 *    列表从 `rememberUpdatedState` 里读最新的一份。
 */
@Composable
private fun EntryGrid(
    entries: List<ModuleEntry>,
    onOpen: (String) -> Unit,
    onMove: (List<ModuleEntry>) -> Unit,
    onDrop: () -> Unit,
) {
    val bounds = remember { mutableStateMapOf<String, Rect>() }
    var dragRoute by remember { mutableStateOf<String?>(null) }
    var dragPos by remember { mutableStateOf(Offset.Zero) }
    val latest by rememberUpdatedState(entries)

    Column(Modifier.fillMaxWidth()) {
        entries.chunked(GRID_COLUMNS).forEachIndexed { rowIndex, row ->
            if (rowIndex > 0) Spacer(Modifier.height(20.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                row.forEach { entry ->
                    WorkbenchTile(
                        entry = entry,
                        onOpen = onOpen,
                        modifier = Modifier
                            .weight(1f)
                            .zIndex(if (dragRoute == entry.route) 1f else 0f)
                            .graphicsLayer {
                                // ⚠️ **不拖的时候先返回**：下面那两行会读 `bounds`（一个 SnapshotStateMap），
                                //    17 个格子每帧各读一次、每次布局写完又要重新求值 —— 白白让整屏
                                //    在每一帧都参与状态依赖。只在被拖的那一格读，其余 16 格零成本。
                                if (dragRoute != entry.route) return@graphicsLayer
                                val b = bounds[entry.route] ?: return@graphicsLayer
                                translationX = dragPos.x - b.center.x
                                translationY = dragPos.y - b.center.y
                                scaleX = 1.08f
                                scaleY = 1.08f
                            }
                            .onGloballyPositioned { bounds[entry.route] = it.boundsInRoot() }
                            .pointerInput(entry.route) {
                                detectDragGesturesAfterLongPress(
                                    onDragStart = {
                                        dragRoute = entry.route
                                        dragPos = bounds[entry.route]?.center ?: Offset.Zero
                                    },
                                    onDragEnd = {
                                        dragRoute = null
                                        onDrop()
                                    },
                                    // ⚠️ **取消也要落盘**：拖动过程中顺序已经真的改了（`onMove` 一路在改状态），
                                    //    这时如果只是"把手势状态清掉、不存"，用户会看到新顺序、下次进来又变回去
                                    //    —— 那正是最难解释的一类"我明明拖过"。
                                    //    什么时候会走到这里：系统把手势抢走（来电、通知栏下拉、
                                    //    被父级滚动容器接管）。
                                    onDragCancel = {
                                        dragRoute = null
                                        onDrop()
                                    },
                                    onDrag = { change, delta ->
                                        change.consume()
                                        dragPos += delta
                                        // 手指现在压在哪一格上 → 和它交换位置
                                        val list = latest
                                        val from = list.indexOfFirst { it.route == entry.route }
                                        val to = list.indexOfFirst { bounds[it.route]?.contains(dragPos) == true }
                                        if (from >= 0 && to >= 0 && to != from) {
                                            onMove(WorkbenchOrder.move(list, from, to))
                                        }
                                    },
                                )
                            },
                    )
                }
                repeat(GRID_COLUMNS - row.size) { Spacer(Modifier.weight(1f)) }
            }
        }
    }
}

/** 一个图标格（图标 + 名字）。 */
@Composable
private fun WorkbenchTile(entry: ModuleEntry, onOpen: (String) -> Unit, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier.clickable { onOpen(entry.route) },
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        // 有 gradient 的入口（目前只有 AI）用品牌渐变，其余用单色语义色。
        // 渐变必须走 background(brush) —— Surface 的 color 只吃单色，想用画刷就得自己铺一层底。
        if (entry.gradient.isEmpty()) {
            Surface(
                color = androidx.compose.ui.graphics.Color(entry.color),
                shape = MaterialTheme.shapes.large,
            ) {
                Icon(
                    entry.icon,
                    contentDescription = entry.label,
                    tint = androidx.compose.ui.graphics.Color.White,
                    modifier = Modifier.padding(13.dp).size(32.dp),
                )
            }
        } else {
            Box(
                modifier = Modifier
                    .background(
                        brush = Brush.linearGradient(entry.gradient.map { androidx.compose.ui.graphics.Color(it) }),
                        shape = MaterialTheme.shapes.large,
                    )
                    .padding(13.dp),
            ) {
                Icon(
                    entry.icon,
                    contentDescription = entry.label,
                    tint = androidx.compose.ui.graphics.Color.White,
                    modifier = Modifier.size(32.dp),
                )
            }
        }
        Spacer(Modifier.height(8.dp))
        Text(
            entry.label,
            style = MaterialTheme.typography.labelMedium,
            textAlign = TextAlign.Center,
            maxLines = 1,
        )
    }
}
