package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.ui.theme.DangerRed
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.ui.theme.ProductPurple
import com.tapmoay.sorders.util.formatDateTime
import com.tapmoay.sorders.util.formatMoney
import com.tapmoay.sorders.util.moneyToDouble
import com.tapmoay.sorders.util.resolveStaticUrl

/**
 * 收货人 / 下单人这一行怎么显示（卡片与详情**共用这一份**）。
 *
 * 规则：`张三（13800000002）`；名字与电话缺一个就只显示有的那个；两个都没有 → `null`
 * （调用方据此**不画那一行** —— 老单本来就没记过名字，画一条「收货人：-」是空的）。
 */
internal fun contactWho(name: String?, phone: String?): String? {
    val n = name.orEmpty().trim()
    val p = phone.orEmpty().trim()
    return when {
        n.isNotEmpty() && p.isNotEmpty() -> "$n（$p）"
        n.isNotEmpty() -> n
        p.isNotEmpty() -> p
        else -> null
    }
}

/**
 * **下单人就是货主**吗？是的话「货主」那一行就不画（卡片与详情共用这一份判据）。
 *
 * 用户原话（2026-09-20）：「那个下单人和货主是一样的，**不需要重新说一遍**啊，
 * 毕竟 3 个人嘛，比较麻烦。所以**你只要出现下单人就可以了**」。
 *
 * 一单上本来有三方：货主（这单是谁的）、收货人（到现场接货的）、下单人（谁下的单）。
 * 货主自己下单时后两者可能就是同一个人 —— 那时卡片上会连着出现
 * 「下单人：永盛食品」和「货主：永盛食品」两行一模一样的字，用户得逐字比对才能确认
 * 这是同一个人，而"看起来像两个人"正是他要避免的。
 *
 * ⚠️ 判据只有名字（出参里没有货主的电话），所以：
 *  · 两边去空格、忽略大小写之后**完全相等**才算同一个人（「永盛食品」vs「永盛 食品」算同一个）；
 *  · 有一边是空的 → **不算**（老单没记过下单人，不能因此把货主那行也抹掉）。
 */
internal fun ordererIsShipper(bossName: String?, shipperName: String?): Boolean {
    fun norm(s: String?) = s.orEmpty().filterNot { it.isWhitespace() }.lowercase()
    val b = norm(bossName)
    val s = norm(shipperName)
    return b.isNotEmpty() && b == s
}

/** tinted 圆底图标（iOS 风格：12% 语义色圆底 + 同色图标，精致不裸奔） */
@Composable
fun TintedIcon(
    icon: ImageVector,
    tint: Color,
    size: Dp = 16.dp,
    container: Dp = 28.dp,
    contentDescription: String? = null,
) {
    Box(
        modifier = Modifier
            .size(container)
            .clip(CircleShape)
            .background(tint.copy(alpha = 0.12f)),
        contentAlignment = Alignment.Center,
    ) {
        Icon(icon, contentDescription = contentDescription, tint = tint, modifier = Modifier.size(size))
    }
}

/**
 * 订单卡片（iOS 分组卡片风格：白底圆角16 + 极轻阴影，无边框；信息仍走三通道）
 * 一眼定位四要素：状态（彩色徽章）/ 地点（蓝 tinted 圆底图标）/ 商品（紫 tinted 圆底图标）/ 金额（橙色加粗）。
 */
@Composable
fun OrderCard(
    order: OrderDto,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    showDriver: Boolean = false,
    showShipper: Boolean = false,
    driverMode: Boolean = false,
    highlight: Boolean = false,
    /**
     * 卡片底部动作行的**左半边**：反向 / 警示类动作（撤回派单、撤销订单、退货、异常标记…）。
     *
     * 用户 2026-09-22 定的规范（原话）：「假如像我们派单员**编辑**的话，一定是在**右边**的…
     * 包括以后的那个只要涉及到**编辑**和其他的比如说**删除**等等，**编辑一定在右边**
     * （因为我们的**惯用手是右手**，我们好编辑），但是比如说**相反的操作，就在左边**」；
     * 「**异常**的话，就放置在**左边**而且**是最左边**」。
     * → 结论：**左＝反向/警示，右＝[extra]＝编辑类**。别把这两个位置的含义改了。
     *
     * 默认空 = 与以前**一模一样**（原来只有 [extra] 一个槽，行为不变），所以其它调用点
     * （司机端任务列表等）一行都不用改。
     */
    leading: @Composable RowScope.() -> Unit = {},
    extra: @Composable RowScope.() -> Unit = {},
) {
    val total = order.orderProducts.sumOf { moneyToDouble(it.lineTotal) }
    val totalQty = order.orderProducts.sumOf { it.quantity }
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        shape = MaterialTheme.shapes.medium,
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 0.dp,
        shadowElevation = 2.dp,
    ) {
        Column(Modifier.padding(16.dp)) {
            // 行1：单号（加粗）+ 状态徽章（彩色）。
            // 单号是 21 位的长串：窄屏 / 系统大字号下它和徽章挤不进同一行时，**宁可让单号独占一行、
            // 徽章右对齐到下一行**，也不许把单号折成「…31271」+「78」那种吊一个尾巴的样子
            // （更不许缩小字号、不许截断 —— 规则与官方出处见 `Adaptive.kt`）。
            val numberStyle = (if (highlight) MaterialTheme.typography.titleMedium else MaterialTheme.typography.titleSmall)
                .copy(fontWeight = FontWeight.Bold)
            val orderNumber = "#" + order.orderNo
            BoxWithConstraints(Modifier.fillMaxWidth()) {
                val onOneLine =
                    rememberTextWidth(orderNumber, numberStyle) + orderStatusChipWidth(order.status) <= maxWidth
                if (onOneLine) {
                    // 放得下 = 与以前**逐像素相同**（单号吃剩余宽度、徽章贴右）
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            orderNumber,
                            style = numberStyle,
                            color = MaterialTheme.colorScheme.onSurface,
                            modifier = Modifier.weight(1f),
                        )
                        OrderStatusChip(order.status)
                    }
                } else {
                    Column {
                        Text(orderNumber, style = numberStyle, color = MaterialTheme.colorScheme.onSurface)
                        Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterEnd) {
                            OrderStatusChip(order.status)
                        }
                    }
                }
            }
            Spacer(Modifier.height(10.dp))

            // 行2：地点（蓝 tinted 图标 + 深色地址）+ 地址参考图
            Row(verticalAlignment = Alignment.CenterVertically) {
                TintedIcon(Icons.Default.Place, Color(0xFF1E6FFF), size = 15.dp)
                Spacer(Modifier.width(8.dp))
                Text(
                    order.addressDetail.ifBlank { "未填写收货地址" },
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (order.addressDetail.isBlank()) MaterialTheme.colorScheme.onSurfaceVariant
                    else MaterialTheme.colorScheme.onSurface,
                    fontWeight = if (order.addressDetail.isBlank()) FontWeight.Normal else FontWeight.Medium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                if (!order.addressImageUrl.isNullOrBlank()) {
                    Spacer(Modifier.width(8.dp))
                    AsyncImage(
                        model = resolveStaticUrl(order.addressImageUrl),
                        contentDescription = "地址参考图",
                        contentScale = ContentScale.Crop,
                        modifier = Modifier
                            .size(44.dp)
                            .clip(MaterialTheme.shapes.small),
                    )
                }
            }

            // 收货人与下单人（2026-09-20 用户要求：「卡片的信息要显示一个是收货人是谁、
            // 一个是下单人是谁，电话号码都显示出来」）。与下面「司机」「货主」两行同一形状，
            // 靠**标签**区分是谁；两者都没有的那一行不画（老单没记过名字）。
            listOf(
                "收货人" to contactWho(order.contactDongjiaName, order.contactDongjiaPhone),
                "下单人" to contactWho(order.contactBossName, order.contactBossPhone),
            ).forEach { (label, who) ->
                if (who != null) {
                    Spacer(Modifier.height(8.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        TintedIcon(Icons.Default.Person, MaterialTheme.colorScheme.tertiary, size = 14.dp, container = 26.dp)
                        Spacer(Modifier.width(8.dp))
                        Text(
                            label + "：" + who,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }

            if (showDriver && !order.driverName.isNullOrBlank()) {
                Spacer(Modifier.height(8.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TintedIcon(Icons.Default.Person, MaterialTheme.colorScheme.tertiary, size = 14.dp, container = 26.dp)
                    Spacer(Modifier.width(8.dp))
                    Text(
                        "司机：" + order.driverName + (order.driverPhone?.let { "（" + it + "）" } ?: ""),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            if (showShipper && !ordererIsShipper(order.contactBossName, order.shipperName ?: order.tempShipperName)) {
                val who = order.shipperName ?: order.tempShipperName
                if (!who.isNullOrBlank()) {
                    Spacer(Modifier.height(8.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        TintedIcon(Icons.Default.Person, MaterialTheme.colorScheme.tertiary, size = 14.dp, container = 26.dp)
                        Spacer(Modifier.width(8.dp))
                        Text("货主：" + who, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }

            Spacer(Modifier.height(10.dp))
            HorizontalDivider(color = MaterialTheme.colorScheme.surfaceVariant)
            Spacer(Modifier.height(10.dp))

            // 行4：商品摘要（紫 tinted 图标）
            Row(verticalAlignment = Alignment.Top) {
                TintedIcon(Icons.Default.Inventory2, Color(ProductPurple), size = 15.dp)
                Spacer(Modifier.width(8.dp))
                Column(Modifier.weight(1f)) {
                    order.orderProducts.take(3).forEachIndexed { idx, op ->
                        // 多商品时行与行之间加一条**虚线**：名字在左、数量在右，两行紧挨着排，
                        // "×3 / ×4"很容易被看成同一行的（用户 2026-09-20：「多个商品……
                        // 中间做虚线横杠稍微做一个区分，省的看错位」）。
                        if (idx > 0) DashedLine()
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                op.productNameSnapshot,
                                style = MaterialTheme.typography.bodyLarge,
                                color = MaterialTheme.colorScheme.onSurface,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.weight(1f),
                            )
                            Text(
                                "×" + op.quantity,
                                style = MaterialTheme.typography.titleMedium,
                                fontWeight = FontWeight.Bold,
                                color = Color(ProductPurple),
                            )
                        }
                    }
                    if (order.orderProducts.isEmpty() && order.deliveryDescription.isNotBlank()) {
                        Text(
                            order.deliveryDescription,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurface,
                            maxLines = 2,
                        )
                    }
                }
            }

            Spacer(Modifier.height(10.dp))

            // 行5：件数/时间 + 金额（橙色加粗，钱=橙）。⚠️ 司机端这一行**只有件数与时间**（没有金额）。
            Row(verticalAlignment = Alignment.CenterVertically) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.weight(1f),
                ) {
                    Text(
                        "共 ",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        totalQty.toString(),
                        style = if (highlight) MaterialTheme.typography.titleLarge else MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        color = if (highlight) Color(DangerRed) else Color(ProductPurple),
                    )
                    Text(
                        " 件 · " + formatDateTime(order.createdAt),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                // 司机端订单卡片**一律不画金额**（2026-09-21 用户定案，原话：「干脆以后就这样子搞，
                //   所有的司机都不显示金钱是多少」）：
                //   原来自定义是「固定工资司机零金额；按单计费(PIECE)司机显示已定价的运费」，
                //   现在**连按单计费那一档也去掉** —— 运费 / 工资 / 货款一概不出现。
                //   司机想知道这一单他拿多少，只在「我的账单」（`ui/driver/DriverFreightScreen`）里看；
                //   而那一页算的是**这一单司机应得多少**（`driver_pay` 一份口径），两处不会各说一个数。
                //   ⛔ 别在这里"顺手加回来"：判据在 `_tools/qa/_check_driver_money.py`（有反向验证）。
                if (!driverMode) {
                    Text(
                        "¥" + formatMoney(total.toString()),
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        color = Color(MoneyOrange),
                    )
                }
            }
            // 底部动作行：**左＝反向/警示，右＝编辑**（位置的含义见上面 leading / extra 的说明）。
            // 两栏都留着：只给 extra 时与以前完全一样（leading 默认空）。
            Row(
                modifier = Modifier.fillMaxWidth().padding(top = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                leading()
                Spacer(Modifier.weight(1f))
                extra()
            }
        }
    }
}

/**
 * 商品行之间的**虚线**横杠（用户 2026-09-20 点名）。
 *
 * 为什么不用 [HorizontalDivider]：它只会画实线，而这里的语义是"同一组的相邻两项"——
 * 实线看起来像"分组到此结束"，虚线才是"接着下一项"。
 *
 * 为什么不用 `Canvas` 自己画：本仓库有一条红线「**自己画的图只许在 Charts.kt**」
 * （`_tools/qa/_check_ledger_dashboard.py`，白名单只有 `Charts.kt` 与 `util/Watermark.kt`）。
 * 这里用一串小方块拼出来（段数按可用宽度算），既守规矩也不依赖 `PathEffect`。
 */
@Composable
private fun DashedLine(modifier: Modifier = Modifier) {
    val lineColor = MaterialTheme.colorScheme.outlineVariant
    BoxWithConstraints(modifier.fillMaxWidth().height(9.dp)) {
        val dash = 5.dp
        val gap = 4.dp
        val count = ((maxWidth + gap) / (dash + gap)).toInt().coerceAtLeast(1)
        Row(
            Modifier.fillMaxSize(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(gap),
        ) {
            repeat(count) {
                Box(Modifier.width(dash).height(1.dp).background(lineColor))
            }
        }
    }
}
