package com.tapmoay.sorders.ui.ai

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.AiOperationDto
import com.tapmoay.sorders.ui.common.AppTopBar
import com.tapmoay.sorders.ui.common.EmptyView
import com.tapmoay.sorders.ui.common.ErrorView
import com.tapmoay.sorders.ui.common.Hint
import com.tapmoay.sorders.ui.common.LoadingBox
import com.tapmoay.sorders.ui.common.SectionCard
import com.tapmoay.sorders.ui.common.SegmentedPicker
import com.tapmoay.sorders.ui.common.TruncationNote
import com.tapmoay.sorders.ui.common.appViewModel
import com.tapmoay.sorders.ui.theme.AiBlue
import com.tapmoay.sorders.ui.theme.Success
import com.tapmoay.sorders.ui.theme.SuccessDark
import com.tapmoay.sorders.ui.theme.ThemeMode

/**
 * 「AI 操作流水」页（台账 L-52 / CHG-0082）—— **管理端**的一页。
 *
 * 用户 2026-10-08（m26776）要的是：AI 代用户执行的每个动作都要留痕，
 * 「谁 / 何时 / 哪个动作 / 成没成」管理端能查。这一页就是那本账的界面。
 *
 * ## 三个刻意的取舍
 * 1. **只读查询也在这一页里**（动作名那一列写「未标动作（只读查询）」）：审计问的是
 *    "AI 用我的身份看过/动过什么"，把只读的滤掉，用户就答不上"它有没有翻过别人的账"。
 * 2. **「加载更早的」是真翻页**（后端 `skip` 游标）：这本账的价值全在"能往前翻到那一次"，
 *    所以不像别的列表页那样只说一句"被截断了"（见 `TruncationNote` 的注释）。
 * 3. **失败原因原样显示后端给的那句话**：界面自己编一句"操作失败"会把 403（越权）、
 *    400（参数不对）、500（后端炸了）三件完全不同的事化成同一句，用户就没法照着改。
 *
 * ⛔ 这一页**不是**权限闸：能看的只有派单员，靠的是后端的 `OPERATION_LOG_READ`（其他人 403）。
 *    入口在设置页里按角色渲染，只是别让货主点进一个必然 403 的页面。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AiOperationsScreen(
    container: AppContainer,
    onBack: () -> Unit,
) {
    val vm: AiOperationsViewModel = appViewModel { AiOperationsViewModel(container) }
    LaunchedEffect(Unit) { vm.load() }

    Scaffold(
        topBar = {
            AppTopBar(
                title = "AI 操作流水",
                subtitle = "AI 用你的身份动过的每一次请求",
                onBack = onBack,
                subtitleTrailing = {
                    IconButton(onClick = { vm.load() }, enabled = !vm.loading) {
                        Icon(Icons.Default.Refresh, contentDescription = "刷新", tint = Color(AiBlue))
                    }
                },
            )
        },
    ) { padding ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            SegmentedPicker(
                labels = listOf("全部", "只看失败"),
                selected = if (vm.onlyFailed) 1 else 0,
                onSelect = { i -> vm.applyOnlyFailed(i == 1) },
                accent = Color(AiBlue),
                modifier = Modifier.padding(horizontal = 16.dp),
            )
            Hint(
                "改数据的动作写动作名；查询只记端点。做没做成都会记一行，后端的原因也留着。",
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                fontSize = 13.sp,
            )

            when {
                // 第一页还没回来：整页转圈。⛔ 不要画成"空列表 + 转圈"——那看起来就是"没有记录"。
                vm.loading && vm.rows.isEmpty() -> LoadingBox(Modifier.weight(1f))
                vm.error != null && vm.rows.isEmpty() -> ErrorView(
                    message = vm.error!!,
                    onRetry = { vm.load() },
                    modifier = Modifier.weight(1f),
                )
                vm.rows.isEmpty() -> EmptyView(
                    text = if (vm.onlyFailed) "没有失败的记录" else "还没有 AI 操作记录",
                    modifier = Modifier.weight(1f),
                )
                else -> LazyColumn(
                    modifier = Modifier.weight(1f),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    items(vm.rows, key = { it.id }) { row -> AiOperationCard(row) }
                    item {
                        // ⛔ 只在**被截断**（后端还有更早的没给回来）时才说这句话：全都取回之后
                        //    再说一句"只显示了最近 N 条"，用户会以为还有没取到的（而其实已经到底了）。
                        if (vm.truncated) {
                            TruncationNote(
                                limit = vm.limit,
                                // 这一页没有日期筛选与搜索框（流水只在服务端按时间倒序分页），
                                // 所以按仓库的口径老实说"可能不全"，并点名页面上真有的那个入口。
                                howToSeeMore = "这份流水可能不全 —— 接着点下面的「加载更早的」能一直往前翻",
                                modifier = Modifier.padding(bottom = 8.dp),
                            )
                        }
                        if (vm.canLoadMore) {
                            OutlinedButton(
                                onClick = { vm.loadMore() },
                                enabled = !vm.loadingMore,
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Text(if (vm.loadingMore) "正在加载…" else "加载更早的")
                            }
                        }
                    }
                }
            }
        }
    }
}

/** 一行流水：结果徽章 + 动作名 + 谁/何时/多久 + 端点 +（失败时）原因 + 请求号。 */
@Composable
private fun AiOperationCard(row: AiOperationDto) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            ResultBadge(row)
            Spacer(Modifier.width(8.dp))
            Text(
                AiOperationRows.actionLabel(row),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Spacer(Modifier.height(6.dp))
        // 「谁 · 什么时候 · 多久」—— 审计第一眼要看的三个字段（与报表中心审计块同一句话法）。
        Text(
            AiOperationRows.whoLabel(row) + " · " + AiOperationRows.whenLabel(row) +
                " · " + AiOperationRows.durationLabel(row.durationMs),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            AiOperationRows.endpointLabel(row),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            // 长端点（带查询串）只吃自己这一行的宽度，不去挤后面的兄弟（同「ExpensesScreen」那一处）。
            modifier = Modifier.fillMaxWidth(),
        )
        if (!row.ok) {
            Spacer(Modifier.height(6.dp))
            Text(
                AiOperationRows.errorLabel(row),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.error,
            )
        }
        // 请求号：这一页唯一能拿去服务器日志里对着找的东西（只有排障时才要，所以放最小号灰字）。
        row.requestId?.takeIf { it.isNotBlank() }?.let {
            Spacer(Modifier.height(4.dp))
            Text(
                "请求号 " + it,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

/** 成功绿 / 失败红（浅色底 + 深色字；暗色模式换一套，判据是 `ThemeMode.isDark`，同 `ReturnRequestChip`）。 */
@Composable
private fun ResultBadge(row: AiOperationDto) {
    val dark = ThemeMode.isDark
    val bg = if (row.ok) (if (dark) Color(0xFF0E3A28) else Color(0xFFD9F0DA))
    else (if (dark) Color(0xFF44201F) else Color(0xFFFFE1E1))
    val fg = if (row.ok) (if (dark) SuccessDark else Success)
    else (if (dark) Color(0xFFFFB4AB) else Color(0xFF9C2B2B))
    Surface(color = bg, shape = RoundedCornerShape(50)) {
        Text(
            AiOperationRows.resultLabel(row),
            color = fg,
            style = MaterialTheme.typography.labelMedium,
            fontWeight = FontWeight.Medium,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
        )
    }
}
