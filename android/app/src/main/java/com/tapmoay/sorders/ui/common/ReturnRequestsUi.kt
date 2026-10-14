package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.data.remote.dto.ReturnRequestDto
import com.tapmoay.sorders.data.remote.dto.ReturnRequestLineDto
import com.tapmoay.sorders.ui.theme.DangerRed

/**
 * 退货申请两端（派单员待办 / 货主我的申请）**页面上**共用的三小块（2026-09-21 精简轮）。
 *
 * 上一轮把两端的 **ViewModel** 收成了一个内核；这一轮收**页面上的重复**：
 * 档位标签、定位提示那一行、以及行首那一段（"消息里点进来的这一条"徽章 + 订单号 + 状态）。
 * 三段都是**逐字抄的两遍**，而它们各自都有"必须两端一致"的理由：
 * · 定位徽章是用户"点通知进来后确认就是这一条"的唯一依据；
 * · 待处理那一档的张数必须挂在**同一档**上（两页的档位顺序相反，按下标写很容易标错档）；
 * · 定位失败的说明必须两端同形（文案本身只有一处：[RETURN_REQUEST_FOCUS_MISS]）。
 */

/**
 * 档位标签：**待处理那一档**带上张数（后端给的 `pending_count`）。
 *
 * ⚠️ 判据是档位的 **key**（`"pending"`）而不是下标：两页的档位顺序**相反**
 * （派单员是「全部 / 待处理」，货主是「待处理 / 全部」），按下标写就是"抄了对方那一行才标对"。
 * ⛔ 张数为 0 时不加 —— 否则用户看到「待处理 0」还得点进去确认一次。
 */
fun returnTabLabels(tabs: List<ReturnTab>, pendingCount: Int): List<String> =
    tabs.map { t ->
        if (t.key == "pending" && pendingCount > 0) "${t.label} $pendingCount" else t.label
    }

/**
 * 定位**没找到**时的一行说明（列表照常显示全部）。
 *
 * ⛔ 不写成错误页/白屏：那会让用户以为这一页坏了，而事实只是"这条申请不在这份列表里"。
 */
@Composable
fun ReturnRequestsFocusNotice(notice: String?) {
    if (notice == null) return
    Text(
        notice,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
    )
}

/**
 * 退货申请这条线的**模块色**（珊瑚）—— 与 `ui/nav/Modules.kt` 里「退货申请」那个格子同一支色。
 * 两端共用这一份：各写一份 hex 的话，改了一处另一处就悄悄分叉了。
 */
val ReturnRequestAccent = Color(0xFFE0785E)

/**
 * 行首那一段：**定位徽章**（可选）+ 模块图标 + 订单号 + 状态徽章。两端的行都从这里往下接各自的内容。
 *
 * 徽章写明"为什么它在最前面"——用户点完通知落进来时，一眼要能确认"就是这一条"，
 * 而不是自己在几十行里找。⚠️ 文案里不许出现 Markdown 星号（`Text` 不渲染，会原样显示）。
 * 圆底图标是这条线的身份（模块色）；订单号是这一行的**主标题**（加粗、比下面的说明重一档）。
 */
@Composable
fun ReturnRequestsHeading(req: ReturnRequestDto, focused: Boolean) {
    if (focused) {
        Surface(
            color = MaterialTheme.colorScheme.primary,
            shape = RoundedCornerShape(50),
        ) {
            Text(
                "消息里点进来的这一条",
                color = MaterialTheme.colorScheme.onPrimary,
                style = MaterialTheme.typography.labelSmall,
                modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
            )
        }
        Spacer(Modifier.height(8.dp))
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        TintedIcon(Icons.Default.AssignmentReturn, ReturnRequestAccent, size = 15.dp, container = 30.dp)
        Spacer(Modifier.width(8.dp))
        Text(
            "订单 #" + req.orderNo,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Bold,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f),
        )
        // 中文名**只用后端给的那一个**（`statusLabel`）：这一页不写状态映射，
        // 否则后端加了新状态，界面上就直接印原始码。
        ReturnRequestStatusChip(status = req.status, label = req.statusLabel)
    }
}

/**
 * 一行「圆底图标 ＋ 灰标签 ＋ 值」—— 申请人 / 申请时间 / 办理人都走它（两端同形）。
 *
 * 抽出来有两个理由：两端的行必须**长得一样**；以及**标签与值要分层** ——
 * 标签是小灰字、值是正文，扫一眼先看到值，需要时才去读标签。
 */
@Composable
fun ReturnRequestMetaRow(
    icon: ImageVector,
    label: String,
    value: String,
    /** 圆底图标那一支色：人员走人员色、时间走信息色（一色一功能，跨端同色）。 */
    tint: Color,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.fillMaxWidth().padding(vertical = 1.dp),
    ) {
        TintedIcon(icon, tint, size = 13.dp, container = 22.dp)
        Spacer(Modifier.width(8.dp))
        Text(
            label,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.width(6.dp))
        Text(
            value,
            style = MaterialTheme.typography.bodyMedium,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f),
        )
    }
}

/**
 * 「要退哪些商品」那一块：形状沿用订单卡的**甲案商品胶囊**，配色换成**退货语义色**
 * （errorContainer 浅红底 ＋ [DangerRed] 图标与数量块）—— 退货不是下单，不与商品卡撞绿。
 *
 * 申请单上真正要看清的就是"哪几样、各几件" —— 一行一个商品比一串「甲×2、乙×1」好扫得多。
 * `lines` 为空（老申请单没带明细）时退回 `summary` 那一行字：一个字都不能少。
 */
@Composable
fun ReturnRequestLinesBlock(lines: List<ReturnRequestLineDto>, summary: String) {
    if (lines.isEmpty()) {
        Text(summary, style = MaterialTheme.typography.bodyMedium)
        return
    }
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        lines.forEach { line ->
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth()
                    .clip(MaterialTheme.shapes.medium)
                    .background(MaterialTheme.colorScheme.errorContainer)
                    .padding(horizontal = 8.dp, vertical = 6.dp),
            ) {
                TintedIcon(Icons.Default.Inventory2, Color(DangerRed), size = 13.dp, container = 22.dp)
                Spacer(Modifier.width(8.dp))
                Text(
                    line.productName.ifBlank { "—" },
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onErrorContainer,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(6.dp))
                Text(
                    "×" + line.quantity,
                    style = MaterialTheme.typography.labelLarge,
                    fontWeight = FontWeight.Bold,
                    color = Color.White,
                    maxLines = 1,
                    modifier = Modifier
                        .clip(MaterialTheme.shapes.small)
                        .background(Color(DangerRed))
                        .padding(horizontal = 8.dp, vertical = 3.dp),
                )
            }
        }
    }
}

/** 申请备注：属于**上下文**，走弱化容器 —— 不抢商品那几行的视线。 */
@Composable
fun ReturnRequestNoteBlock(text: String, label: String = "申请备注") {
    Row(
        verticalAlignment = Alignment.Top,
        modifier = Modifier.fillMaxWidth()
            .clip(MaterialTheme.shapes.medium)
            .background(MaterialTheme.colorScheme.surfaceContainerHigh)
            .padding(horizontal = 10.dp, vertical = 8.dp),
    ) {
        Icon(
            Icons.Default.Notes,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(15.dp),
        )
        Spacer(Modifier.width(8.dp))
        Text(
            label + "：" + text,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.weight(1f),
        )
    }
}

/** 驳回理由：**否决**语义（红底红字）—— 这是货主唯一能拿到的答复，必须显眼。 */
@Composable
fun ReturnRequestReasonBlock(text: String, label: String = "驳回理由") {
    Row(
        verticalAlignment = Alignment.Top,
        modifier = Modifier.fillMaxWidth()
            .clip(MaterialTheme.shapes.medium)
            .background(MaterialTheme.colorScheme.error.copy(alpha = 0.10f))
            .padding(horizontal = 10.dp, vertical = 8.dp),
    ) {
        Icon(
            Icons.Default.ErrorOutline,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.error,
            modifier = Modifier.size(15.dp),
        )
        Spacer(Modifier.width(8.dp))
        Text(
            label + "：" + text,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.error,
            modifier = Modifier.weight(1f),
        )
    }
}


/**
 * **改这张退货申请**的弹层（2026-10-15 CHG-0130）—— 派单端与货主端**同一个实现**。
 *
 * 用户口径：「退货是可以改的…主要改的是退货的商品…商品种类、商品数量，派单员可以更改，
 * 货主和批发商他们也是可以进行更改的」「改完之后只会重新发个信息给派单员说此退货订单发生了改动」。
 *
 * 为什么两端必须共用这一份（而不是各画各的）：
 *  · 填数量那一块本来就是共用的（[OrderReturnLines]），这里只是给它套上同一个弹层；
 *  · 「改的是明细、不动钱不动货」这句话是**用户对钱的预期**，两端说法必须一模一样；
 *  · 「只发一条通知」也必须在按下确认**之前**就说出来（[amendNoticeLine]）。
 *
 * ⛔ 弹层里没有"备注/订单号/状态"这些入口：改的就只有商品明细 ——
 *    多一个可改字段，就多一处"改完钱对不上"的地方。
 */
@Composable
fun ReturnRequestAmendDialog(vm: ReturnRequestsViewModel) {
    val req = vm.amendTarget ?: return
    CardAlertDialog(
        tone = DialogTone.WARN,
        onDismissRequest = { if (!vm.acting) vm.cancelAmend() },
        // 单号另起一行、小一号（走查 P4：标题那 24sp 一行塞不下 20 个字符）。
        title = { DialogTitle("改这张退货申请", req.orderNo) },
        text = {
            Column {
                // 「现在是 → 改后」：把改动**对照着**给他看（改的只有商品与件数这一件事）。
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.fillMaxWidth()
                        .clip(MaterialTheme.shapes.medium)
                        .background(MaterialTheme.colorScheme.surfaceContainerHigh)
                        .padding(horizontal = 10.dp, vertical = 8.dp),
                ) {
                    Icon(
                        Icons.Default.SwapHoriz,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(15.dp),
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(
                        "现在是：" + vm.amendBeforeSummary.ifBlank { "（没填明细）" },
                        style = MaterialTheme.typography.bodyMedium,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f),
                    )
                }
                Spacer(Modifier.height(6.dp))
                // 用户对"改"最担心的是钱会不会跟着动 —— 这一行必须在按确认之前说清。
                // ⚠️ 这一段是**钱与账的口径**（不动账本 / 那一刻才变）⇒ 永远看得见，
                //    ⛔ 不许挂到提示总开关上（_check_hints.py 第 2 组：判成数据/状态却走 Hint 会红）。
                Row(
                    verticalAlignment = Alignment.Top,
                    modifier = Modifier.fillMaxWidth()
                        .clip(MaterialTheme.shapes.medium)
                        .background(ReturnRequestAccent.copy(alpha = 0.12f))
                        .padding(horizontal = 10.dp, vertical = 8.dp),
                ) {
                    Icon(
                        Icons.Default.Info,
                        contentDescription = null,
                        tint = ReturnRequestAccent,
                        modifier = Modifier.size(15.dp),
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(
                        "改的只是商品明细（哪几样、各几件）：不动库存、不动账本、不影响退款。" +
                            "钱和货仍然在派单员点了「办理退货」那一刻才变。",
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.weight(1f),
                    )
                }
                Spacer(Modifier.height(4.dp))
                // 通知对象那句 + 一句教法（改完不锁死：确认之前随时还能再改一次）。
                // 这两句既不是数据也不是状态，属于「可以收起来的说明」⇒ 走统一提示入口。
                // ⚠️ 第一段字面量必须**紧跟在统一入口那一行后面**：它前面出现「+」时盘点器会把这句
                //    当成「拿运行时值拼出来的」，判成数据 ⇒ _check_hints.py 第 2 组会报
                //    「这次调用里一段解释句都没有」。
                Hint(
                    "改完想再调整，确认之前随时都能改，不用重新申请。" +
                        amendNoticeLine(vm.amendActorRole),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(8.dp))
                if (vm.amendLoading) {
                    Text("正在读这一单的商品…", style = MaterialTheme.typography.bodyMedium)
                } else {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        TextButton(onClick = { vm.amendFillAll() }) {
                            Icon(Icons.Default.DoneAll, contentDescription = null, modifier = Modifier.size(15.dp))
                            Spacer(Modifier.width(4.dp))
                            Text("能退的都填满")
                        }
                        Spacer(Modifier.width(4.dp))
                        TextButton(onClick = { vm.amendClearAll() }) {
                            Icon(Icons.Default.Clear, contentDescription = null, modifier = Modifier.size(15.dp))
                            Spacer(Modifier.width(4.dp))
                            Text("全清零")
                        }
                    }
                    // 逐行填数量：与「申请退货」「派单员退货」**同一个块**（上限规则也只有一份）。
                    OrderReturnLines(
                        lines = vm.amendLines,
                        returnQty = vm.amendQty,
                        maxReturnable = { amendMaxReturnable(it) },
                        onSetQty = { id, qty -> vm.setAmendQty(id, qty) },
                    )
                    Spacer(Modifier.height(8.dp))
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.fillMaxWidth()
                            .clip(MaterialTheme.shapes.medium)
                            .background(MaterialTheme.colorScheme.errorContainer)
                            .padding(horizontal = 10.dp, vertical = 8.dp),
                    ) {
                        Icon(
                            Icons.Default.Done,
                            contentDescription = null,
                            tint = Color(DangerRed),
                            modifier = Modifier.size(15.dp),
                        )
                        Spacer(Modifier.width(8.dp))
                        Text(
                            "改后：" + amendPickedSummary(vm.amendLines, vm.amendQty).ifBlank { "（一行都没留）" },
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.onErrorContainer,
                            modifier = Modifier.weight(1f),
                        )
                    }
                }
                // 失败原因画在弹层里（页面上会被这层弹窗盖住 = "点了没反应"）：
                // 终态拒绝 / 越界 / 超上限都是后端给的中文，原样显示。
                FormErrorLine(vm.amendFormError)
            }
        },
        confirmButton = {
            TextButton(
                onClick = { vm.confirmAmend() },
                // 一行商品都没读回来（比如单子已经没有任何可退的行）时不给点：
                // 那时底下那行说明已经写清了为什么。全清零是可点的 —— 点了会告诉他"至少要留一行"。
                enabled = !vm.acting && !vm.amendLoading && vm.amendLines.isNotEmpty(),
                colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.primary),
            ) { Text(if (vm.acting) "改着呢…" else "确认改动") }
        },
        dismissButton = {
            TextButton(onClick = { vm.cancelAmend() }, enabled = !vm.acting) { Text("取消") }
        },
    )
}

