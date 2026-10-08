package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
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
import com.tapmoay.sorders.ui.theme.OnProductRowTint
import com.tapmoay.sorders.ui.theme.ProductPurple
import com.tapmoay.sorders.ui.theme.ProductRowTint
import com.tapmoay.sorders.ui.theme.ThemeGreen
import com.tapmoay.sorders.ui.theme.ThemeGreenDeep
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
    /**
     * 卡片**最底下**那一整行：留给"这一张单现在要做的那一件事"（整宽主行动）。
     *
     * 为什么另开一个槽而不是复用 [extra]（2026-10-08，CHG-0081）：用户要的是司机在**列表上**
     * 直接接单（原话：「直接在订单卡片里面的最底下…按钮…直接在那里点击确认」）——
     * 那是一屏里最该被一眼看到、最好按到的一颗，所以它**整宽、独占一行**；
     * 而 [extra] 是右对齐的图标动作（编辑类），塞不下也压不住这个分量。
     *
     * ⚠️ 两种"主行动"别混：商品卡那种"底部一排三个等宽大按钮"是**并列**的多动作
     * （`06_DESIGN_SYSTEM.md §4.2`）；这里只有一个动作，所以是一条整宽按钮
     * （与 §4.2c 的左右分区也不冲突 —— 那两个槽管的是**图标动作**的位置）。
     *
     * 默认空 = **不画这一行**，其它调用点（派单员待派池 / 订单管理 / 我的订单）逐像素不变。
     */
    bottomAction: @Composable ColumnScope.() -> Unit = {},
) {
    val total = order.orderProducts.sumOf { moneyToDouble(it.lineTotal) }
    val totalQty = order.orderProducts.sumOf { it.quantity }
    // 单位换算（一车 = 8 方）：**全 App 一份**（`UnitConv`），四张列表共用这一张卡片。
    // 没设过换算时它是空表 → 显示与原样**逐字相同**（"还没拉到"也不会少显示什么）。
    val conversions by UnitConv.rows.collectAsState()
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
            // 行1：地点（蓝 tinted 图标 + 深色地址）+ **状态徽章** + 地址参考图。
            //
            // 历史（两步，别只看一半）：
            //  · CHG-0002（2026-09-27）用户要求「**普通订单卡是不要显示订单号**」→ 原来那一行
            //    只剩一个右对齐的徽章，于是**顶上等于空了一行**（约 40dp 只放一个小胶囊）。
            //  · CHG-0003（2026-09-28）用户：「整个布局就不是很好，现在就是看起来**上面是空的**啊，
            //    就是不美观」→ 徽章**不再独占一行**，并到地点那一行的右端（地址参考图之前）。
            //
            // ⛔ 单号**不许回到卡片上**（它只在订单详情页 `OrderDetailScreen.kt`）——
            //    判据 `_tools/qa/_check_adaptive_layout.py` §3 两个方向都判：长回来了红、详情里没了也红。
            // ⛔ 徽章的**配色 / 文案 / 右对齐**位置含义一个字没动（`OrderStatusChip` 本体重构都没碰）。
            // ⛔ 这一改动**三端同时生效**（货主 / 派单员 / 司机共用一个 `OrderCard`）。
            //
            // ⚠️ 顺序是**地点 → 徽章 → 图**，并且地点那一格带 `weight(1f)` + Ellipsis：
            //    地址再长也是它先省略，**徽章始终完整可读**（状态是扫一眼就要看到的信息，
            //    地址可以点进详情看）。
            Row(verticalAlignment = Alignment.CenterVertically) {
                TintedIcon(Icons.Default.Place, Color(ThemeGreen), size = 15.dp)
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
                // 状态徽章：地点之后、地址参考图之前（CHG-0003）
                Spacer(Modifier.width(8.dp))
                OrderStatusChip(order.status)
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

            // 行4：商品摘要（**圆角胶囊行**：绿 tinted 图标 + 深色品名 + 深绿数量块）
            //
            // ⚠️ 2026-10-09 CHG-0091 换的皮（用户定稿「**甲方案**」，ref m01927）。改前是
            //    「紫底方块图标 + 紫字品名 + 右侧紫字数量」，一行挨一行、中间拿虚线分隔；
            //    用户要的是照他给的那张表单图（称呼/电话/备注/分类）的样式：
            //    **每一个商品都是一块圆角浅绿胶囊**，右侧数量压成**深绿圆角块 + 白字**
            //    （原话：「底部有个**颜色比较深的**……让这个信息比较重要，能一眼看得出来」
            //     「如果是多个商品的话，他就是**多个样式**」）。
            //    ⇒ 多商品时**不再需要虚线**：一块一块自己就分得开，块间距承担了原先那份
            //      "别把两行看串"的活（块间距 = 上面 `spacedBy(6.dp)`，⛔ 别拿它调排版）。
            //      原来那条 `DashedLine` 因此**没人调用了** —— 按仓库的红线
            //      （`_check_dead_code.py`：没人调用的私有声明要删）**已经删掉**。
            //      删它时把它的两条结论搬到这里，免得下一个人重新踩：
            //      ① 分隔线**不要用 `HorizontalDivider`** —— 它只会画实线，实线的语义是
            //         "分组到此结束"，而这里是"同一组的相邻两项"；
            //      ② **不要自己上 `Canvas` 画** —— 本仓有一条红线「自己画的图只许在
            //         `Charts.kt`」（`_check_ledger_dashboard.py`，白名单只有 `Charts.kt`
            //         与 `util/Watermark.kt`）。真要画虚线，就用一串小方块拼
            //         （段数按可用宽度算，见 git 历史里的 `DashedLine`）。
            //      ③ 多商品之间**只靠块间距**：这是用户 2026-10-09 亲自定的（甲案），
            //         ⛔ 别再加回任何分隔线。
            // ⛔ 品名**不留紫**（用户定稿原话：「商品名称**不留紫色**」）——改深墨绿 [OnProductRowTint]。
            // ⛔ 数量那一格的**拼法与单位一个字没动**（`qtyWithUnitConverted`），只换它穿的衣服。
            // ⛔ 这一层**不许带 `Modifier.weight(1f)`**（2026-10-09 真机抓到的回归，见 CHG-0091 ⑧）：
            //    改前这一块套在 `Row(verticalAlignment = Alignment.Top)` 里，`weight(1f)` 是**横向**权重
            //    （占满宽度）；甲案把外面那层 Row 去掉之后，它成了页面级
            //    `Column(Modifier.padding(16.dp))`（第 153 行）的**直接子节点** —— 在 ColumnScope 里
            //    `weight(1f)` 是**纵向**权重，而外层高度是 wrap content ⇒ 这一块拿到 **0 高**，
            //    整块商品区一个像素都不画（真机现象：`共 16 筐` 照常显示、两个商品名一个都不见）。
            //    这一层要的只是「占满宽度」，而下面每一行自己就带 `.fillMaxWidth()`，不需要在这里再要宽度。
            Column(
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                order.orderProducts.take(3).forEach { op ->
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(MaterialTheme.shapes.medium)
                            .background(Color(ProductRowTint))
                            .padding(horizontal = 8.dp, vertical = 6.dp),
                    ) {
                        TintedIcon(Icons.Default.Inventory2, Color(ThemeGreen), size = 13.dp, container = 22.dp)
                        Spacer(Modifier.width(8.dp))
                        Text(
                            op.productNameSnapshot,
                            style = MaterialTheme.typography.bodyLarge,
                            fontWeight = FontWeight.SemiBold,
                            color = Color(OnProductRowTint),
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f),
                        )
                        Spacer(Modifier.width(6.dp))
                        Text(
                            // 数量后面**要带单位**（用户 2026-09-22：「商品后面的数字没有单位啊……
                            // 这是要有单位的」）。单位是下单那一刻定格的（`unit_snapshot`），
                            // 老单没填过就只给数字 —— 拼法只有一处：`Units.kt::qtyWithUnit`。
                            //
                            // 2026-09-24 起再带**换算**：设过「1 车 = 8 方」时这一格写
                            // 「×10 车 ≈ 80 方」（用户：「我下的十车，会有 2 个数据」）。
                            // 换算表是**全库共用的一份**（`UnitConv`），四个列表页共用这一张卡片。
                            "×" + qtyWithUnitConverted(op.quantity, op.unit, conversions),
                            style = MaterialTheme.typography.labelLarge,
                            fontWeight = FontWeight.Bold,
                            color = Color.White,
                            maxLines = 1,
                            modifier = Modifier
                                .clip(MaterialTheme.shapes.small)
                                .background(Color(ThemeGreenDeep))
                                .padding(horizontal = 8.dp, vertical = 3.dp),
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
                        // 合计后面那个单位：全单同一个单位时才敢写它（「共 6 桶」），
                        // 混装（6 桶 + 3 箱）本来就没有共同单位 → 退回口语的「件」。
                        // 判据只有一处：`Units.kt::sharedUnitOf`。
                        " " + (sharedUnitOf(order.orderProducts.map { it.unit }) ?: DEFAULT_UNIT) +
                            " · " + formatDateTime(order.createdAt),
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
            // 卡片**最底下**那一整行：留给"这一张单现在要做的那件事"（整宽主行动）。
            // 默认不画 → 其它列表（派单员待派池 / 订单管理 / 我的订单）与以前**逐像素一样**。
            bottomAction()
        }
    }
}

