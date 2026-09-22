package com.tapmoay.sorders.ui.profile

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.DarkMode
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material.icons.filled.WbSunny
import androidx.compose.material.icons.filled.WbTwilight
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.SunClock
import com.tapmoay.sorders.core.SunLocation
import com.tapmoay.sorders.ui.common.DangerConfirmDialog
import com.tapmoay.sorders.ui.common.Hint
import com.tapmoay.sorders.ui.common.OneShotSnackbar
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.ui.theme.ProductPurple
import com.tapmoay.sorders.ui.theme.ThemeMode
import com.tapmoay.sorders.ui.theme.WarningAmber
import kotlinx.coroutines.launch

/**
 * 「基础设置」——「我的」页的**第二层**（用户 2026-09-21 定案）。
 *
 * ## 为什么要分这一层
 * 用户原话：「我们的**按钮太多了**，哪些是**不怎么重要**的，我们就放到基础设置当中」。
 * 搬进来的这三项都是**纯显示偏好**：改错了不影响钱、不影响状态、不影响别人，
 * 最坏结果就是"看着不习惯，再改回来"。留在第一层的则相反 ——
 * 消息提醒（来单会不会响）、我的账本（司机的钱）、关于与更新（装新版）、退出登录。
 *
 * ## 这里的东西一个字都没改
 * 三个开关的读写与判据与它们原来在 `ProfileScreen` 里**完全一致**（连同那两段解释：
 * 「随日落」那一行同一个字符串既是说明也是状态、靠 `autoBySun` 分 `Hint`/`Text`；
 * 「提示」那一格受总开关控制的口径见 `docs/HINT_STYLE.md` §5）。
 * 这一轮只换了**摆放位置**，⛔ 不动任何判定逻辑。
 *
 * ⛔ 参考图里的「语言设置 / 账号信息 / 结算账户」三项我们**没有做**，理由分别是：
 * 没有第二语言；账号就在「我的」头部写着（进去再看一遍是白走一步）；我们没有"收银结算账户"
 * 这个概念（钱走账本与运费结算，都各自有入口）。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BasicSettingsScreen(
    container: AppContainer,
    onBack: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    // 重置计数的确认框 + 结果回执（回执用 Snackbar 一次性弹，见文件末尾的 OneShotSnackbar）
    var showResetConfirm by remember { mutableStateOf(false) }
    var resetMessage by remember { mutableStateOf<String?>(null) }
    val snackbar = remember { SnackbarHostState() }
    // 根节点用 Box：内容一列，Snackbar 浮在最下面（重置结果要靠它说一句话）
    Box(Modifier.fillMaxSize()) {
    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text("基础设置") },
            navigationIcon = {
                IconButton(onClick = onBack) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                }
            },
        )
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp),
        ) {
            Spacer(Modifier.height(4.dp))
            // 一张白卡装三行（与「我的」页同一套卡片观感：大圆角、无分隔线）
            Surface(
                shape = MaterialTheme.shapes.medium,
                color = MaterialTheme.colorScheme.surface,
                shadowElevation = 1.dp,
            ) {
                Column {
                    // 「随日落自动切换」：同一行按状态分渲染 —— 自动关着时这句话是**说明**
                    // （走 `Hint`，受提示总开关控制）；自动开着时同一行是**当前状态**
                    // （「现在夜间 · 22:30 自动转白天 · 按定位」）→ 必须留 `Text`，
                    // 关掉提示不该把"现在是什么状态"关掉。两句话都来自 `SunClock.summary`。
                    ProfileRow(
                        icon = Icons.Default.WbTwilight,
                        tint = Color(MoneyOrange),
                        title = "随日落自动切换",
                        subtitle = {
                            val line = SunClock.summary(
                                ThemeMode.autoBySun,
                                SunClock.stateHere(),
                                located = SunLocation.hasFix(),
                            )
                            if (ThemeMode.autoBySun) Text(line) else Hint(line)
                        },
                        trailing = {
                            Switch(
                                checked = ThemeMode.autoBySun,
                                onCheckedChange = { ThemeMode.setAuto(context, it) },
                            )
                        },
                        onClick = { ThemeMode.setAuto(context, !ThemeMode.autoBySun) },
                        showChevron = false,
                    )
                    ProfileRow(
                        icon = if (ThemeMode.isDark) Icons.Default.DarkMode else Icons.Default.WbSunny,
                        tint = Color(ProductPurple),
                        title = if (ThemeMode.isDark) "夜间模式" else "白天模式",
                        subtitle = { if (ThemeMode.autoBySun) Text("已交给自动切换") },
                        trailing = {
                            // 走 ThemeMode.set（负责落盘）；自动模式下这个开关禁用
                            Switch(
                                checked = ThemeMode.isDark,
                                onCheckedChange = { ThemeMode.set(context, it) },
                                enabled = !ThemeMode.autoBySun,
                            )
                        },
                        onClick = if (ThemeMode.autoBySun) null else {
                            { ThemeMode.set(context, !ThemeMode.isDark) }
                        },
                        showChevron = false,
                    )
                    // ⚠️ 「提示」那一格**不在这里**：2026-09-21 当天先按「不重要的搬进基础设置」
                    //    搬了进来，用户看图后又要求**搬回「我的」第一层**（原话：「基础设置有个要
                    //    移出来，叫做提示提醒，那个不能放在里面」）。所以这一页只剩**两个**开关，
                    //    提示那一格在 `ui/profile/ProfileScreen.kt` 的第一层。
                    //
                    // ---- 重置计数（用户 2026-09-22：「在我的基础设置里加一个**重置计数**」）----
                    // 清掉的是「常用度」（"我用过它几次"）—— 那正是列表排序的第一依据
                    // （见 `services/usage_service.py`）。清完之后，联系人/线路/地点/商品…
                    // 全部回到**按创建顺序**排。
                    // ⛔ 两个边界（都写进确认框里说给用户听）：
                    //    ① 只清**我自己**的（后端接口没有"清别人"的口子）；
                    //    ② **清了不能还原**（这张表是派生统计，不做软删）—— 所以必须先确认。
                    ProfileRow(
                        icon = Icons.Default.RestartAlt,
                        // 用语义色里的"提醒/待处理"黄：它既不是危险（不是删业务数据），
                        // 也不是日常开关（清掉就回不来了），黄是这一档最合适的语言。
                        tint = Color(WarningAmber),
                        title = "重置计数",
                        // 这一句是**后果**（清掉会怎样），按 `docs/HINT_STYLE.md` §2 属"警告类"
                        // → 走 `Text`（永不隐藏）：把后果藏进「提示」开关里，用户就可能
                        // 在不知情的情况下点下去。
                        subtitle = {
                            Text(
                                "清掉「用得越多越靠前」的记录，列表回到按创建顺序",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        },
                        onClick = { showResetConfirm = true },
                    )
                }
            }
            Spacer(Modifier.height(16.dp))
        }
    }

    // 重置计数：先确认再清（用户 2026-09-22 要的入口）。
    // 为什么必须确认：这张表是**派生统计**、清了不还原（不做软删），
    // 而且用户清完的第一反应会是"我的列表怎么乱了" —— 那句话得在**点之前**看到。
    if (showResetConfirm) {
        DangerConfirmDialog(
            title = "确认重置计数？",
            message = "清掉的是「常用度」——之后联系人、线路、地点、商品这些列表都会回到" +
                "「先创建的在前」。只清你自己的，不影响别人；但清掉之后没法还原。",
            confirmText = "重置",
            onConfirm = {
                showResetConfirm = false
                scope.launch {
                    resetMessage = try {
                        val n = container.repo.resetUsage()
                        if (n > 0) {
                            "已重置：清掉 $n 条常用记录，列表回到按创建顺序"
                        } else {
                            // 0 条也要如实说：不然用户会以为"点了没反应"
                            "本来就没有常用记录（列表一直是按创建顺序）"
                        }
                    } catch (e: Exception) {
                        "重置失败：" + (e.message ?: "网络或服务端出错，稍后再试")
                    }
                }
            },
            onDismiss = { showResetConfirm = false },
        )
    }
    OneShotSnackbar(snackbar, resetMessage) { resetMessage = null }
    SnackbarHost(snackbar, Modifier.align(Alignment.BottomCenter))
    }
}
