package com.tapmoay.sorders.ui.common

/**
 * 「选人」弹层左边那一列的**分组规则**（CHG-0128）—— 全 App 唯一一份，纯函数、可单测。
 *
 * ## 用户要的是什么（2026-10-15 口述逐字）
 * > 「像**选地点库那样**（左分类、右对应项）」
 *
 * 动机（同一段口述）：
 * > 「联系人**一多起来**…找起来**非常麻烦**」
 *
 * 也就是：「选择收货地址」那份弹层（`ui/shipper/OrderCreateScreen.kt::AddressPickerSheet`）
 * 左栏那一列分类，要长到「选人」的地方 —— 代理下单「为谁下单」选货主、下单页/地址页选联系人。
 *
 * 同一天他还说过一句定语（决定了这次怎么做）：
 * > 「我们好像**已经有了对应的代码**啊，具体是哪些功能实现了这个我忘记了」
 *
 * 所以这次**一份新算法都没有**：分组、兜底、"全部"那一格全部照用商品/库存/预设单/选商品弹层
 * 已经在用的那一套（`ui/common/ProductPicker.kt::categoryTabsOf`）。
 *
 * ## ⛔ 分组算法不在这里（这里只做"把一列人的分类名翻出来"）
 * 「左栏有哪些格、什么顺序、未分类排哪」**唯一实现在 `ProductPicker.kt::categoryTabsOf`**
 * （`ALL_CATEGORY`「全部」/ `NO_CATEGORY`「未分类」两个常量也在那里）。
 * 在这里再写第二份的后果是「商品那边未分类排最后、选人这边跑到中间」——
 * 而且没人会同时开两个页面看出来。
 *
 * 那一份替我们兜住的三件事（选人这里一条都不用重写）：
 * 1. **没分类的人归「未分类」，永远排在最末** —— ⛔ 不许藏起来
 *    （藏起来的表现是"名册里没有这个人"→ 用户再建一个 → 同一个人两本账）；
 * 2. 一屋子人都没分类时，左栏**只剩「全部」**（不逼用户先补分类才能挑到人）；
 * 3. 名册里没有的老分类名也照样出一格（后端 `category` 是自由文本）。
 *
 * ## 关键词过滤不在这里
 * 搜索的唯一实现是 `core/UserSearch`（姓名 / 手机号 / 后 4 位）。分类与搜索是**两个维度**，
 * 交叉筛：这里只回答"这个人属不属于这一类"，"他叫不叫这个名字"由调用方问 `UserSearch`。
 */

/** 左栏那一列：`["全部", <有人的分类…>, "未分类"?]`（顺序与兜底见文件头）。 */
internal fun <T> groupTabsOf(items: List<T>, categoryOf: (T) -> String?): List<String> =
    categoryTabsOf(items.map(categoryOf))

/** 选中左栏的某一格之后，右边到底显示谁（「全部」＝ 不筛，其余按分类名比）。 */
internal fun <T> inGroup(items: List<T>, group: String, categoryOf: (T) -> String?): List<T> =
    if (group == ALL_CATEGORY) items else items.filter { categoryNameOf(categoryOf(it)) == group }
