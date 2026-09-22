package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.Sell
import androidx.compose.material.icons.filled.ShoppingCart
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.util.formatMoney
import com.tapmoay.sorders.util.resolveStaticUrl

/**
 * # 商品"长什么样"的**唯一一套零件**
 *
 * 2026-09-21 商品管理改版第 1 期（P2）。起因是用户给了一批 POS 商品管理的截图并说：
 * > 「他其实**复用了很多的组件**……比如说他那个**选择商品**的组件，包括**展示商品**那个组件也是……」
 *
 * 我们这边恰好相反：**同一件商品在外观上有 3 份实现**——
 * 管理列表里的卡（`ProductsScreen::ProductCard`）、选品页里的行（`ProductPicker::ProductRow`）、
 * 库存页里的卡（`InventoryScreen::StockCard`），而"商品名用什么色""库存什么颜色算该处理"
 * 这些小判据还各自散着（`"#1565C0"` 那个兜底值全库有 **5 份**）。
 *
 * ## 唯一一处决定"商品上显示什么、什么顺序"
 * [productFacts] 是**事实的构造器**：它定"显示哪两个数字、谁在前"。
 * 现在全库渲染商品的 **5 个页面**都从它取事实、用 [ProductLine] 排版：
 *
 * | 页面 | 形态 | 事实 |
 * |---|---|---|
 * | 商品管理（卡） | [ProductLine] `dense = false` | 售价 + 库存 |
 * | 批量操作（行） | [ProductLine] + 左侧勾选框 | 售价 + 库存 |
 * | 商品排序（行） | [ProductLine] + 右侧 ↑/拖动柄 | 售价 + 库存 |
 * | 选品页（行） | [ProductLine] + 右侧 ＋ | 只有售价（⛔ 货主也看这一页，**不许**露库存） |
 * | 库存页（卡） | 自己的外壳（那页的 DTO 没有图/名称色/售价） | 只有库存 |
 *
 * ⚠️ **2026-09-21 第二轮**：用户看完第 1 期之后要求「**全部做深**…其他地方你也得改，
 * 最好是采用（通）用的继承，**上次你改一个地方，它就其他跟着改了**」。
 * 所以原来那段"刻意不抽通用卡"的说法**被推翻了** —— 现在是
 * **零件 + 事实构造器共用、外壳各自组装**：
 *
 * | 零件 | 管什么 |
 * |---|---|
 * | [productFacts] | **显示哪几个数字、什么顺序**（售价 → 库存，顺序钉在这里） |
 * | [ProductFact] / [ProductFacts] | 一条事实怎么画（图标 + 标签 + 值，**一个一行**） |
 * | [ProductLine] | 商品行/卡的主体（前置槽 + 缩略图 + 名称/角标 + 事实 + 后置槽） |
 * | [ProductThumb] | 缩略图：有图用图、没图用名称色兜底 |
 * | [productNameColor] / [productStockColor] | 两条**判据**（名字色、库存该用什么色） |
 *
 * ⛔ **仍然刻意不抽的**（抽了会更糟，不是懒得抽）：
 * · **外壳**（`SectionCard` / 选品页那个描边 Surface / 排序页的拖动壳）—— 各页容器真的不同，
 *   包一层只会多一个转发参数、少一分可读性；
 * · **每个页面显示哪几条事实** —— 这是**业务口径**不是版式：选品页要给货主看（不能露库存）、
 *   库存页手里根本没有售价。所以事实由调用方从 [productFacts] 里**挑**，而不是由零件替它决定；
 * · **名称的字号/行数**收在一个 `dense` 开关里（卡 = `titleMedium`/2 行、行 = `bodyLarge`/1 行），
 *   不开放成两个参数 —— 开放出去就等于"每页都能长一点"，那正是这一轮要消灭的东西。
 *
 * ⛔ **顺手加字段是这一条最容易犯的错**
 * 设计规范 §4.1 是用户拍过板的：**卡片上只有两个数字**（售价 + 库存）、
 * **一个一行**、**成本不在卡上**（"成本价是要在编辑里面才会有"）、**分类不在卡上**
 * （"既然已经在左边显示了分类，那右边的商品就不需要显示分类了"）。
 * 抽零件是把这几条**固化**，不是重开讨论 —— 想加数字之前先读 §4.1。
 */

/**
 * 商品名 / 缩略图的颜色（`#RRGGBB`）。
 *
 * 坏值（`null` / 空 / **解析不出来的串**）一律退回物流蓝 —— **不许抛异常**：
 * 这一版之前有 4 处是 `Color(android.graphics.Color.parseColor(raw ?: "#1565C0"))`，
 * 而 `parseColor` 遇到库里一条脏数据（历史手工改库写进去的 `"深蓝"`、少一位的 `"#12345"`）
 * 会**直接抛**，表现是"整个商品列表崩了"，而原因藏在某一件商品的一个字段里。
 *
 * ⚠️ **`"blue"` 不是坏值**：`parseColor` 认得 `red/green/blue/black/white…` 这些**颜色名**，
 * 它会把它解析成纯蓝。写这条注释时差点拿它当"脏数据"的例子 —— 是写单测时发现的
 * （JVM 单测里那个方法是 Android 框架桩、一律抛，所以这个区别在单测里看不出来）。
 *
 * ⚠️ **别为它写"断言颜色"的单测**：本工程开了 `unitTests.isReturnDefaultValues = true`，
 * `android.graphics.Color.parseColor` 在 JVM 单测里是一根**返回 0 的桩**
 * —— 好值和坏值都得到透明色，"坏值会抛""兜底是物流蓝"两件事在单测里都测不出来。
 * 那两条的防线是**真机截图** + 反向验证 `_reverse_verify_product_card.py`。
 *
 * ⚠️ **全库只此一处**：再写一遍就等于再留一个会崩的入口（红线
 * `_tools/qa/_check_product_card_single_source.py` 盯着）。
 */
fun productNameColor(raw: String?): Color = try {
    Color(android.graphics.Color.parseColor(raw ?: DEFAULT_PRODUCT_NAME_COLOR))
} catch (_: Exception) {
    FallbackNameColor
}

/** 商品名颜色的兜底值（与后端/老数据一致：物流蓝 `#1565C0`）。 */
const val DEFAULT_PRODUCT_NAME_COLOR = "#1565C0"

/** [DEFAULT_PRODUCT_NAME_COLOR] 的 `Color` 形态（`const` 里不能调 `toInt()`，所以单列一个）。 */
private val FallbackNameColor = Color(0xFF1565C0)

// 库存那三个颜色：**判据的配色跟着判据走**（放在这里，别散回各页面）。
// 「库存管理」的模块语义色是蓝青 #00BCD4（与 `Modules.kt` 里那一格同色：跨端同功能同色）。
private val StockOutRed = Color(0xFFE53935)
private val StockLowYellow = Color(0xFFFFB300)
private val StockOkCyan = Color(0xFF00BCD4)

/**
 * 库存这个数字用什么颜色 —— **它不是装饰，是"这一行要你处理"的信号**
 * （派单员扫列表时靠它决定先看哪几个）。
 *
 * | 情况 | 颜色 | 含义 |
 * |---|---|---|
 * | `stock <= 0` | 红 `#E53935` | 断货 |
 * | `lowStockAlert > 0 && stock <= lowStockAlert` | 黄 `#FFB300` | 到报警线了 |
 * | 其余 | 蓝青 `#00BCD4` | 正常（库存管理的模块色） |
 *
 * ⚠️ `lowStockAlert == 0` 表示**不报警**（不是"阈值是 0"）—— 所以第 2 条必须带
 * `lowStockAlert > 0` 这个前置条件，否则每件库存为 0 的商品都会被判成"到报警线了"。
 */
fun productStockColor(stock: Int, lowStockAlert: Int): Color = when {
    stock <= 0 -> StockOutRed
    lowStockAlert > 0 && stock <= lowStockAlert -> StockLowYellow
    else -> StockOkCyan
}

/** 一行"事实"：图标 + 标签 + 值（[color] 是**这个值**的颜色，不是标签的颜色）。 */
data class ProductFact(
    val icon: ImageVector,
    val label: String,
    val value: String,
    val color: Color,
)

/**
 * 「售价」那一行 —— **钱的格式化只有这一处**（`¥` + 两位小数 + `/单位`）。
 *
 * 单位走 [unitOrDefault]（空 → 「件」），所以调用方**不要**再自己 `ifBlank { "件" }`：
 * 各写一份的话，同一件商品在两个页面上会显示成「¥25.00/件」和「¥25.00/」（少了单位的那个
 * 看起来像被截断了，而它其实是漏了兜底）。
 */
fun productPriceFact(price: String, unit: String?): ProductFact = ProductFact(
    icon = Icons.Default.Sell,
    label = "售价",
    value = "¥" + formatMoney(price) + "/" + unitOrDefault(unit),
    color = Color(MoneyOrange),
)

/** 「库存」那一行：值 = 数量 + 单位，颜色 = [productStockColor]（状态色）。 */
fun productStockFact(stock: Int, lowStockAlert: Int, unit: String?): ProductFact = ProductFact(
    icon = Icons.Default.Inventory2,
    label = "库存",
    value = "$stock " + unitOrDefault(unit),
    color = productStockColor(stock, lowStockAlert),
)

/**
 * 「占用」那一行 —— **已被订单锁住、还没出库**的数量（库存页专有的一条事实）。
 *
 * 它跟"库存"是两件事，所以是**另一行**而不是跟在数字后面：
 * 派单员要能一眼分清"我这儿还有 30"和"其中 5 个已经许给别人了"。
 * 颜色是挂账橙红（`#FF6B2C`，与「挂账单位」模块同色）—— 那不是"要你处理"的红，
 * 是"这笔货已经名花有主"的标记，不能跟断货的红撞在一起。
 */
fun productReservedFact(reserved: Int, unit: String?): ProductFact = ProductFact(
    icon = Icons.Default.ShoppingCart,
    label = "占用",
    value = "-$reserved " + unitOrDefault(unit),
    color = ReservedOrange,
)

/** 占用数量的颜色（挂账单位模块色 `#FF6B2C`）。 */
private val ReservedOrange = Color(0xFFFF6B2C)

/**
 * 库存状态角标的**文案**（`null` = 这个状态不出角标）。
 *
 * ⚠️ 判据与 [productStockColor] **必须是同一套**：两处各写一遍的话，
 * 会出现"数字是黄的（到报警线了）却挂着红色的『缺货』"这种自相矛盾的卡片。
 * 所以这里和颜色判据并排放，改一个必须看一眼另一个。
 */
fun productStockBadgeText(stock: Int, lowStockAlert: Int): String? = when {
    stock <= 0 -> "缺货"
    lowStockAlert > 0 && stock <= lowStockAlert -> "低库存"
    else -> null
}

/**
 * 库存状态角标（缺货 / 低库存）—— 正常时不占位置。
 *
 * ⚠️ 「低库存」的**字**用的是更深的琥珀 `#8A6100`，不是那个黄色本身：
 * 黄字压在浅黄底上（11sp）几乎读不出来，"角标看不见"比"没有角标"更糟。
 * 数字那边仍然是 `#FFB300`（粗体、字号更大）—— 两者**不是**不一致，
 * 是同一个语义色在小字号下必须压深一档。
 */
@Composable
fun ProductStockBadge(stock: Int, lowStockAlert: Int) {
    val text = productStockBadgeText(stock, lowStockAlert) ?: return
    val (fg, bg) = when {
        stock <= 0 -> StockOutRed to Color(0xFFFFE8E8)
        else -> LowStockInk to Color(0xFFFFF3D0)
    }
    Surface(color = bg, shape = MaterialTheme.shapes.small) {
        Text(
            text,
            style = MaterialTheme.typography.labelMedium,
            color = fg,
            modifier = Modifier.padding(horizontal = 6.dp, vertical = 1.dp),
        )
    }
}

/** 「低库存」角标的字色（深一档的琥珀，见 [ProductStockBadge] 的说明）。 */
private val LowStockInk = Color(0xFF8A6100)

/**
 * **一件商品上要显示的那两条事实** —— 顺序钉在这里：**售价在前、库存在后**。
 *
 * 用户 2026-09-21（第二轮）看完第 1 期之后的原话：
 * > 「你还是把**库存**给移到**现在的那个售价的下面**啊，这样子**美观一点**」
 *
 * 所以这一条不只是"少写一行"：**"库存紧跟在售价下面"这件事就定义在这三行里**。
 * 五个页面全都调它，下次再调顺序（或者再加一个数字）**只改这一处**，其余跟着变
 * —— 用户要的「上次你改一个地方，它就其他跟着改了」。
 *
 * ⚠️ 想只显示其中一条的页面（选品页要给货主看、**不能露库存**）就用
 * [productPriceFact] / [productStockFact] 单独取 —— **不要**在这一页里手拼字符串，
 * 那正是这一轮消灭掉的东西（[R3] 红线盯着）。
 */
fun productFacts(price: String, unit: String?, stock: Int, lowStockAlert: Int): List<ProductFact> =
    listOf(
        productPriceFact(price, unit),
        productStockFact(stock, lowStockAlert, unit),
    )

/**
 * 把 [facts] 一行一个竖着画出来。
 *
 * ⚠️ **为什么固定"一个一行"**（用户 2026-09-19）：原来是 `FlowRow` 流式排，
 * `成本 ¥0.00` 短的时候"库存"被挤到同一行、长的时候又自己换行，
 * 于是**每张卡长得都不一样**（列表看起来是毛的）。固定一行一个之后，
 * 数字还**在竖直方向对齐成一列** —— 扫一列价 比扫一片流式文本快得多。
 *
 * ⚠️ **这里不带外边距**：与名称之间留多少空由 [ProductLine] 决定
 * （卡 6dp、行 2dp）。写在这里的话，紧凑行会被这个 6dp 顶高、
 * 而"卡和行各留多少"就变成了两个地方各改一次。
 */
@Composable
fun ProductFacts(facts: List<ProductFact>, modifier: Modifier = Modifier) {
    Column(
        modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(3.dp),
    ) {
        facts.forEach { row(it) }
    }
}

@Composable
private fun row(f: ProductFact) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(f.icon, contentDescription = null, tint = f.color, modifier = Modifier.size(13.dp))
        Spacer(Modifier.width(3.dp))
        Text(f.label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.width(3.dp))
        Text(
            f.value,
            style = MaterialTheme.typography.labelMedium,
            fontWeight = FontWeight.Bold,
            color = f.color,
            maxLines = 1,
        )
    }
}

/**
 * 商品缩略图：**有图用图、没图用"名称色 + 图标"兜底**。
 *
 * [solid] 是两页**真实存在**的两种观感，不是给好写留的口子：
 * - `false`（管理列表）：浅灰底 + **名称色图标** —— 一屏几十行，安静一点才不会盖住数字；
 * - `true`（选品页）：**名称色实底 + 白图标** —— 那一页是"挑东西"，色块帮着扫。
 *
 * ⚠️ 图标尺寸按 [size] 的 46% 算（52dp 的块 → 24dp、56dp → 26dp）：
 * 这两个数原来是在两处各自写死的 24 与 26，取同一个比例之后两者差不到 0.2dp
 * —— **这是有意的归一**，不是把某一边改小了。
 *
 * ⚠️ 圆角**不收成一个数**：管理页原来用的是 `MaterialTheme.shapes.medium`（16dp）、
 * 选品页是写死的 12dp。两页本来就不同，所以它是个参数（[shape]）而不是"统一成 12"——
 * 顺手统一圆角 = 顺手改了别人拍过板的观感。
 */
@Composable
fun ProductThumb(
    imageUrl: String?,
    nameColor: String?,
    size: Dp,
    modifier: Modifier = Modifier,
    solid: Boolean = false,
    shape: Shape = RoundedCornerShape(12.dp),
) {
    val color = remember(nameColor) { productNameColor(nameColor) }
    Box(
        modifier
            .size(size)
            .clip(shape)
            .background(if (solid) color else MaterialTheme.colorScheme.surfaceVariant),
        contentAlignment = Alignment.Center,
    ) {
        if (!imageUrl.isNullOrBlank()) {
            AsyncImage(
                model = resolveStaticUrl(imageUrl),
                contentDescription = null,
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize(),
            )
        } else {
            Icon(
                Icons.Default.Inventory2,
                contentDescription = null,
                tint = if (solid) Color.White else color,
                modifier = Modifier.size(size * 0.46f),
            )
        }
    }
}

/**
 * **一件商品长什么样** —— 全库唯一的那个"行主体"。
 *
 * 版式钉死成一条：`[前置槽] · [缩略图槽] · [名称 + 角标 / 事实若干行] · [后置槽]`。
 * 用户 2026-09-21（第二轮）：「像我们这样子的形式——比如说右边是分类、它是个条的，
 * 那个商品啊，它其实是**有点区别的**…你也**全部做深**吧…**其他地方你也得改**，
 * 最好是采用（通）用的继承，**上次你改一个地方，它就其他跟着改了**。」
 *
 * ## 谁在用（五个页面全部走它）
 * | 页面 | 前置槽 | 缩略图槽 | 后置槽 | 事实 |
 * |---|---|---|---|---|
 * | 商品管理（卡） | — | [ProductThumb] 88dp | — | [productFacts] |
 * | 批量操作（行） | 勾选框 | [ProductThumb] 40dp | — | [productFacts] |
 * | 商品排序（行） | 序号 | — | ↑置顶 + 拖动柄 | [productFacts] |
 * | 选品页（行） | — | [ProductThumb] 56dp `solid` | ＋按钮 | 只有售价（**货主也看这一页**） |
 *
 * ## 为什么是"槽"而不是一堆尺寸参数
 * 缩略图做成**槽**（[thumb]）之后，各页传的是**它自己的那颗** [ProductThumb]
 * （大小 / 圆角 / 实底虚底本来就该各页自己定），零件里因此**没有** `thumbSize` 这类
 * "传进去只为转手一次"的参数。前置/后置同理（勾选框、序号、＋、↑、拖动柄）。
 *
 * ## [dense] 只切"两种形态"，不是"给好写留的口子"
 * `false` = 列表大卡：名称 `titleMedium` 最多 2 行、与事实之间 6dp、整行顶端对齐；
 * `true` = 紧凑行：名称 `bodyLarge` 1 行、间隔 2dp、垂直居中。
 * 它**只有两个取值**（没有第三档），所以"卡片长得不一样"这件事最多只发生在两处。
 *
 * ## [bodyModifier] 为什么存在
 * 排序页要把**长按拖动**挂在"名称 + 事实"那一列上（挂整行的话，
 * 右边那个「↑ 置顶」按钮就点不到了）。它是这一列的修饰符，不是第二个外壳。
 */
@Composable
fun ProductLine(
    name: String,
    nameColor: String?,
    facts: List<ProductFact>,
    modifier: Modifier = Modifier,
    leading: (@Composable () -> Unit)? = null,
    thumb: (@Composable () -> Unit)? = null,
    badge: (@Composable () -> Unit)? = null,
    trailing: (@Composable () -> Unit)? = null,
    bodyModifier: Modifier = Modifier,
    dense: Boolean = false,
) {
    Row(
        modifier.fillMaxWidth(),
        verticalAlignment = if (dense) Alignment.CenterVertically else Alignment.Top,
    ) {
        if (leading != null) {
            leading()
            Spacer(Modifier.width(if (dense) 6.dp else 10.dp))
        }
        if (thumb != null) {
            thumb()
            Spacer(Modifier.width(if (dense) 10.dp else 12.dp))
        }
        Column(bodyModifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    name,
                    style = if (dense) MaterialTheme.typography.bodyLarge else MaterialTheme.typography.titleMedium,
                    // 名称色判据只有一处（`productNameColor`）：坏值退回物流蓝而**不抛异常**
                    color = productNameColor(nameColor),
                    fontWeight = if (dense) FontWeight.SemiBold else FontWeight.Normal,
                    maxLines = if (dense) 1 else 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false),
                )
                if (badge != null) {
                    Spacer(Modifier.width(6.dp))
                    badge()
                }
            }
            if (facts.isNotEmpty()) {
                Spacer(Modifier.height(if (dense) 2.dp else 6.dp))
                ProductFacts(facts)
            }
        }
        if (trailing != null) {
            Spacer(Modifier.width(if (dense) 8.dp else 10.dp))
            trailing()
        }
    }
}

/**
 * 「**已沽清**」角标 —— 全库唯一一处（管理卡 / 批量操作行 / 选品行都用它）。
 *
 * 用户 2026-09-21：「还有一个**沽清，也就是下架**」—— 在他嘴里这两件事是**同一件**
 * （都是 `products.is_active = false`）。所以文案只留一个「已沽清」，
 * 原来选品页那个红色的「已下架」也换成它：同一个状态在两页写两个词、两种颜色，
 * 用户会以为是两件事（而且那一页的红色和"余额不足"的红撞在一起）。
 *
 * ⛔ **故意不给参数**：一旦能传文案，下一页就会传「售罄」「下架」「缺货」，
 * 又变成"同一个状态三种说法"。
 */
@Composable
fun ProductSoldOutBadge() {
    Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = MaterialTheme.shapes.small) {
        Text(
            "已沽清",
            style = MaterialTheme.typography.labelMedium,
            modifier = Modifier.padding(horizontal = 6.dp, vertical = 1.dp),
        )
    }
}
