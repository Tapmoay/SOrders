package com.tapmoay.sorders.ai

import kotlinx.serialization.json.JsonObject

/**
 * 英文键 → 中文标签（**只用在 AI 读回答这一处**）。
 *
 * ### 为什么要做（用户 m00812）
 * 「可以啊可以啊……其实**也不需要做的很复杂**，因为它只是**一个信息、重要信息的展示**而已，
 * 也就是**在应用到 AI 的时候才会有，它只展示信息**。」
 *
 * 模型的回答里出现 `shipper_name` 这种词，用户看不懂；让它自己翻译一遍，既慢又不稳
 * （同一份数据这次叫「货主」、下次叫「发货方」，用户会以为说的是两种人）。所以标签由这张
 * **确定性**的表给。顺带还省 token：`shipper_name` 12 个字符 vs「货主」2 个。
 *
 * ### ⛔ 一个中文标签只能对应一个英文键
 * [apply] 走的是 `mapKeys`：两个英文键撞成同一个中文标签时，**后一个会把前一个吃掉**
 * （一行数据里少一个字段，比露出英文糟得多）。所以"标签两两不同"是有单测钉着的硬规矩。
 *
 * ### 认不出来的键**原样透传**
 * 宁可露出英文，也不要猜一个错的中文——猜错比看不懂更糟：模型会照着错标签编业务含义。
 * 所以这张表**只增不猜**，加一个键之前先确认真有那个键。
 *
 * ⛔ 卡片、页面不经过这里（那是给人看的 UI，各有各的文案）；这里只影响喂给模型的数据。
 */
internal object AiFieldLabels {

    internal val LABELS = mapOf(
        // 订单
        "order_no" to "订单号", "status" to "状态", "type" to "类型", "source" to "来源",
        "created_at" to "创建时间", "updated_at" to "更新时间", "delivered_at" to "送达时间",
        "remark" to "备注", "note" to "说明",
        // 人 / 地点
        "shipper_name" to "货主", "temp_shipper_name" to "临时货主", "customer_name" to "客户",
        "driver_name" to "司机", "driver_phone" to "司机电话", "phone" to "电话", "address" to "地址",
        // 商品 / 数量 / 钱
        "product_name" to "商品", "name" to "名称", "quantity" to "数量", "unit_name" to "单位",
        "price" to "单价", "amount" to "金额", "goods_amount" to "货款",
        "total_amount" to "合计金额", "total" to "合计", "count" to "条数",
        // 账
        "arrears" to "欠款", "paid" to "已付", "unpaid" to "未付", "payable" to "应付",
        "receivable" to "应收",
        // 库存
        "stock" to "库存", "ideal_stock" to "应有库存",
        // 其它
        "plate_no" to "车牌", "date" to "日期", "category" to "分类",
    )

    /** 认不出来就原样返回。 */
    fun of(key: String): String = LABELS[key] ?: key

    /** 一行数据整体换标签（顺序不变；两边不会撞成同一个标签）。 */
    fun apply(row: JsonObject): JsonObject = JsonObject(row.mapKeys { (k, _) -> of(k) })
}
