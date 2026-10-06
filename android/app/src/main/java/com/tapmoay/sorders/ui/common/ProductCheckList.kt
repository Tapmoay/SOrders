package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TriStateCheckbox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.state.ToggleableState
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.data.remote.dto.ProductDto

/**
 * **勾选商品**的那一屏 —— 全库唯一一份「搜索 + 左分类栏 + 勾选行 + 全选这一类」。
 *
 * ## 为什么会有这个零件（用户原话，2026-10-06）
 * 「他这个**直接是调用商品的分类列表**、调用**商品的页面**。我们可以直接点击选择分类，
 * 可以**单独勾选某个商品**，也可以**全部勾选**，然后也可以**单独关闭某个商品**……
 * 这样子我们就可以**代码的复用**了……在写任何代码的时候，能复用就复用，
 * 能复用就不要自己写……**这个理念是最高级**。」
 *
 * 「批量操作」页原来自己拼了一整套（搜索框 + CategoryRail + LazyColumn + “全选这一类”），
 * 商品可见范围要的是同一套动作。各写一份的结果就是：用户在一个页面勾得顺手、
 * 在另一个页面勾不动（连全选都没有），而两边其实是同一件事。
 *
 * | 页面 | checkedIds 的含义 | 勾一行 = | 勾这一类的头 = |
 * |---|---|---|---|
 * | 批量操作 | 这批动作要作用的商品 | 选中 | 选中这一类里看得见的 |
 * | 商品可见范围 | **他看得见的商品** | 给他看 / 不给他看 | 整类给 / 整类不给 |
 *
 * ⚠️ 两个页面的**语义不同、动作相同**，所以差别全部落在回调里（onToggleProduct /
 * onToggleCategory），零件自己不认识“可见范围”这三个字。
 *
 * ## 分类头为什么是**三态**
 * 「全选这一类」原来是个两态 Checkbox（点一下全勾、再点一下全清），
 * 而“这一类里勾了一半”这件事在界面上**看不出来** —— 用户以为这一类是关着的，
 * 点一下才发现是“从半勾变全勾”。三态（全选 / 半选 / 未选）是从 checkedIds 算出来的，
 * 不需要调用方多传一个状态。
 *
 * ⚠️ 点分类头时回调必须带 targetOn：**三态变两态的那一下必须是明确的**
 * （半选 → 点 → 全选），不能写成“取反” —— 取反在半选时没有定义。
 *
 * ## 搜索词是**受控**的
 * 调用方拿着 keyword（可见范围第二层要把“搜过什么”留在自己的状态里，
 * 返回上一层再进来不该被清掉），零件只负责画输入框与清除按钮。
 *
 * @param products 全部候选商品（**不是**筛过的那一批；筛选在零件里做）
 * @param checkedIds 勾中的商品 id（批量操作=已选，可见范围=看得见）
 * @param onToggleProduct 点一行（勾选框或整行都算）
 * @param onToggleCategory 点分类头：分类名（可能是 ALL_CATEGORY）、点完之后这一类**该不该全勾**、
 *   以及“这一类当前看得见的那几个 id”（调用方拿它做差集，不用自己再筛一遍）
 * @param rowNote 每行下面那行小字（返回 null 就不占位置）——可见范围用来说「已单独关掉」，
 *   ⛔ 不许用它在列表里**藏掉**商品：关掉的商品必须还在列表里、还能被勾回来
 * @param rowLocked 这一行的勾选**禁掉**（`true`＝点不动）。可见范围里"这一类被整类关掉"的行用它：
 *   那种行点一下不会变（排除压在授权上头），与其让用户点一个没反应的框，不如禁掉 ＋ 用 @param rowNote
 *   写清"要单独放开先把这一类打开"。⛔ 不许拿它去藏行（藏起来的商品＝用户以为不存在）
 */
@Composable
internal fun ProductCheckList(
    products: List<ProductDto>,
    checkedIds: Set<Long>,
    onToggleProduct: (Long) -> Unit,
    onToggleCategory: (name: String, targetOn: Boolean, ids: List<Long>) -> Unit,
    keyword: String,
    onKeywordChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    categoryOrder: List<String> = emptyList(),
    loading: Boolean = false,
    error: String? = null,
    onRetry: (() -> Unit)? = null,
    searchPlaceholder: String = "搜索商品名称",
    emptyText: String = "暂无商品",
    railWidth: Dp = 92.dp,
    rowNote: ((ProductDto) -> String?)? = null,
    rowLocked: ((ProductDto) -> Boolean)? = null,
) {
    val cats = remember(products, categoryOrder) { categoryTabs(products, categoryOrder) }
    var category by remember { mutableStateOf(ALL_CATEGORY) }
    // 分类会随商品增减变化（名册里删掉一类、最后一件事商品被下架）：选中那档没了就回「全部」
    LaunchedEffect(cats) { if (category !in cats) category = ALL_CATEGORY }

    val kw = keyword.trim()
    val visible = remember(products, category, kw) {
        products
            .filter { category == ALL_CATEGORY || categoryOf(it) == category }
            .filter { kw.isEmpty() || it.name.contains(kw, ignoreCase = true) }
    }

    Column(modifier) {
        OutlinedTextField(
            value = keyword,
            onValueChange = onKeywordChange,
            placeholder = { Text(searchPlaceholder, style = MaterialTheme.typography.bodySmall) },
            leadingIcon = { Icon(Icons.Default.Search, contentDescription = null, modifier = Modifier.size(20.dp)) },
            trailingIcon = {
                if (keyword.isNotEmpty()) {
                    IconButton(onClick = { onKeywordChange("") }) {
                        Icon(Icons.Default.Close, contentDescription = "清空搜索", modifier = Modifier.size(18.dp))
                    }
                }
            },
            singleLine = true,
            textStyle = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
        )

        when {
            loading -> LoadingBox()
            error != null -> ErrorView(error, onRetry = onRetry)
            products.isEmpty() -> EmptyView(emptyText)
            else -> Row(Modifier.weight(1f)) {
                CategoryRail(
                    tabs = cats,
                    selected = category,
                    onSelect = { category = it },
                    modifier = Modifier.width(railWidth).fillMaxHeight(),
                )
                Box(Modifier.weight(1f).fillMaxHeight()) {
                    if (visible.isEmpty()) {
                        EmptyView(
                            if (kw.isNotEmpty()) "没有名称含「" + kw + "」的商品" else "「" + category + "」下暂无商品",
                            Modifier.align(Alignment.Center),
                        )
                    } else {
                        LazyColumn(
                            Modifier.fillMaxSize(),
                            contentPadding = PaddingValues(start = 8.dp, end = 10.dp, top = 6.dp, bottom = 12.dp),
                            verticalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            item {
                                val state = triStateOf(visible, checkedIds)
                                CategoryCheckHead(
                                    state = state,
                                    label = if (category == ALL_CATEGORY) {
                                        "全选筛选出的 " + visible.size + " 个"
                                    } else {
                                        "全选这一类（" + visible.size + "）"
                                    },
                                    // 半选与未选都朝「全勾」走（三态变两态时“取反”没有定义）
                                    onClick = { onToggleCategory(category, state != ToggleableState.On, visible.map { it.id }) },
                                )
                            }
                            items(visible, key = { it.id }) { p ->
                                val on = p.id in checkedIds
                                val locked = rowLocked?.invoke(p) == true
                                // ⛔ 行外观全部来自 ui/common/ProductCardKit.kt：勾选框是**前置槽**、
                                //    图是**缩略图槽**、售价与库存来自 productFacts()。
                                ProductLine(
                                    name = p.name,
                                    nameColor = p.nameColor,
                                    facts = productFacts(p.defaultUnitPrice, p.unit, p.stock, p.lowStockAlert),
                                    dense = true,
                                    modifier = Modifier
                                        .clickable(enabled = !locked) { onToggleProduct(p.id) }
                                        .padding(vertical = 4.dp),
                                    leading = {
                                        Checkbox(
                                            checked = on,
                                            onCheckedChange = { onToggleProduct(p.id) },
                                            enabled = !locked,
                                        )
                                    },
                                    thumb = {
                                        ProductThumb(imageUrl = p.imageUrl, nameColor = p.nameColor, size = 40.dp)
                                    },
                                    badge = if (p.isActive) null else ({ ProductSoldOutBadge() }),
                                )
                                rowNote?.invoke(p)?.let { note ->
                                    Text(
                                        note,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        modifier = Modifier.padding(start = 40.dp, bottom = 2.dp),
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

/** 这一类“看得见的那几个”里勾了几个 —— 全勾 / 一个没勾 / 勾了一半。 */
private fun triStateOf(visible: List<ProductDto>, checkedIds: Set<Long>): ToggleableState {
    val n = visible.count { it.id in checkedIds }
    return when {
        n == 0 -> ToggleableState.Off
        n == visible.size -> ToggleableState.On
        else -> ToggleableState.Indeterminate
    }
}

/** 「全选这一类（N）」那一行 —— 三态勾选框 + 一句话。 */
@Composable
private fun CategoryCheckHead(state: ToggleableState, label: String, onClick: () -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        TriStateCheckbox(state = state, onClick = onClick)
        Text(label, style = MaterialTheme.typography.bodyMedium)
    }
}
