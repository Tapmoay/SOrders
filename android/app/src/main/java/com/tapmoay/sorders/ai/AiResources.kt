package com.tapmoay.sorders.ai

import com.tapmoay.sorders.data.remote.api.PriceRuleDto
import com.tapmoay.sorders.data.remote.api.UnitConversionDto
import com.tapmoay.sorders.data.remote.dto.AddressDto
import com.tapmoay.sorders.data.remote.dto.ArrearsUnitDto
import com.tapmoay.sorders.data.remote.dto.ContactCategoryDto
import com.tapmoay.sorders.data.remote.dto.ContactDto
import com.tapmoay.sorders.data.remote.dto.RouteCategoryDto
import com.tapmoay.sorders.data.remote.dto.DriverBillingRuleDto
import com.tapmoay.sorders.data.remote.dto.FreightTemplateDto
import com.tapmoay.sorders.data.remote.dto.InvoiceDto
import com.tapmoay.sorders.data.remote.dto.LedgerEntryDto
import com.tapmoay.sorders.data.remote.dto.LocationDto
import com.tapmoay.sorders.data.remote.dto.NotificationDto
import com.tapmoay.sorders.data.remote.dto.PlaceDto
import com.tapmoay.sorders.data.remote.dto.PurchaseOrderDto
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.data.remote.dto.OrderProductRow
import com.tapmoay.sorders.data.remote.dto.OrderTemplateDto
import com.tapmoay.sorders.data.remote.dto.ProductCategoryDto
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.data.remote.dto.ProductVisibilityDto
import com.tapmoay.sorders.data.remote.dto.SupplierDto
import com.tapmoay.sorders.data.remote.dto.SupplierPayableDto
import com.tapmoay.sorders.data.remote.dto.SupplierPaymentDto
import com.tapmoay.sorders.data.remote.dto.UserDto
import com.tapmoay.sorders.data.remote.dto.VehicleDto
import com.tapmoay.sorders.ui.order.discountLineIds
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * 一个资源**怎么写撤回**：表的全部内容（v3.27）。
 *
 * ## 这个文件是「哪些动作能撤回、走哪条路」的唯一答案
 * 撤回的实现只有一处（[AiRevert]），但"哪些动作挂在哪个资源下""这个资源怎么读回现场"
 * 是**数据**，不是逻辑——所以它们全部摊在这一个文件里，一眼能看完。
 * 加一个新动作时要做的事只有一件：**把它写进它所属资源的 [AiResource.actions]**。
 * 忘了也不会静默——`_tools/ai/_show_undo_status.py` 与红线 §20 会点名报错。
 *
 * ## 键名一律用 **payload 键名**，不是 DTO 字段名
 * 因为撤回是"把旧值塞回同一条写路径"，而那条路径读的是 payload 键。
 * 两套名字混着用就会出现"快照读到了、撤回时取不到"——那种错不会报错，
 * 只会让撤回卡点下去什么都没发生。所以 [AiRevertRead] 里的每个键
 * 都必须是某个动作 payload 里真实存在的键（单测逐个核对）。
 *
 * ## 一处容易看漏的地方：同一个字段在网络上有两个键名
 * 订单的"内部备注"在 `orders.update` 里叫 `internal_notes`，在 `orders.assign` 里叫
 * `internal_note`（历史原因，两个动作各自读自己的键）。所以快照里**两个都放**：
 * 少放一个，那条撤回就会静默地丢一项。
 */
internal object AiResources {

    // ============================================================ 主数据

    private val ADDRESS = AiResource(
        key = "address",
        cn = "地址",
        idKey = "address_id",
        readKeys = setOf(
            "receiver_name", "phone", "detail_address", "origin_address", "remark",
            GEO_LAT, GEO_LNG,
        ),
        labels = mapOf(
            "receiver_name" to "收货人",
            "phone" to "电话",
            "detail_address" to "终点地址",
            "origin_address" to "起点地址",
            "remark" to "备注",
            // 经纬度是**静默键**（不占卡片一行），但照样要有中文名：
            // 读不回来时那行警告会落到 `stuck` 里，那时候卡片上不能出现 `address_lat` 这种裸键。
            GEO_LAT to "纬度",
            GEO_LNG to "经度",
        ),
        // 坐标跟着地址文字走：改了地址文字，坐标必须一起回退，否则司机会被带去旧地址。
        // 但它不该单独占一行（用户核对的是地址文字）。
        silent = setOf(GEO_LAT, GEO_LNG),
        actions = listOf(
            update(AiWrites.ADDRESS_UPDATE),
            delete(AiWrites.ADDRESS_DELETE),
            paired(AiWrites.ADDRESS_RESTORE, AiInverse(AiWrites.ADDRESS_DELETE, mapOf("address_id" to AiRevert.ID)), idKey = "target_id"),
        ),
        read = { ds, id -> ds.snapshot("address", id) },
        restore = AiInverse(AiWrites.ADDRESS_RESTORE, mapOf("target_id" to AiRevert.ID)),
    )

    private val LOCATION = AiResource(
        key = "location",
        cn = "地点",
        idKey = "location_id",
        readKeys = setOf(
            "name", "detail_address", "remark", "category", GEO_LAT, GEO_LNG,
            // 地点绑定的收货联系人（2026-09-24）：**必须读回来**，否则 AI 改一次地点名，
            // 撤回卡手里没有旧值 → 绑定的联系人回不去（而 `updateLocation` 是整体替换语义）。
            "contact_name", "contact_phone",
        ),
        labels = mapOf(
            "name" to "地点名", "detail_address" to "地址", "remark" to "备注",
            "category" to "分组",
            "contact_name" to "收货联系人", "contact_phone" to "收货电话",
            GEO_LAT to "纬度", GEO_LNG to "经度",
        ),
        silent = setOf(GEO_LAT, GEO_LNG),
        actions = listOf(
            update(AiWrites.LOCATION_UPDATE),
            delete(AiWrites.LOCATION_DELETE),
            paired(AiWrites.LOCATION_RESTORE, AiInverse(AiWrites.LOCATION_DELETE, mapOf("location_id" to AiRevert.ID)), idKey = "target_id"),
        ),
        read = { ds, id -> ds.snapshot("location", id) },
        restore = AiInverse(AiWrites.LOCATION_RESTORE, mapOf("target_id" to AiRevert.ID)),
    )

    /**
     * 共享地点（**全库共用**那一张表里的点）。
     *
     * 与 [LOCATION] 刻意分成两份资源：那个是"**我自己**的地点库"（按人分区、软删、有恢复），
     * 这个是"**所有人共用**的选点表"（物理删除、没有回收站）。合成一份的后果是撤回表会
     * 以为它们都能"恢复"——而共享库那边根本没有恢复接口。
     *
     * 只有 `place.update` 挂在这里（改名字/地址可以照原样写回）；
     * `place.delete` 与 `place.demote` 是**撤不回来**的，理由写在 [AiRevert] 里。
     */
    private val PLACE = AiResource(
        key = "place",
        cn = "共享地点",
        idKey = "place_id",
        readKeys = setOf("name", "detail_address"),
        labels = mapOf("name" to "名称", "detail_address" to "地址"),
        actions = listOf(
            update(AiWrites.PLACE_UPDATE),
            // 删除是**软删**（用户 2026-09-19：「这些所有功能的删（撤）销操作就是软删」），
            // 所以这里能挂 `delete(...)`：撤回 = 走 `restore` 那一头把同一条原样放回来。
            delete(AiWrites.PLACE_DELETE),
            paired(
                AiWrites.PLACE_RESTORE,
                AiInverse(AiWrites.PLACE_DELETE, mapOf("place_id" to AiRevert.ID)),
                idKey = "target_id",
            ),
        ),
        read = { ds, id -> ds.snapshot("place", id) },
        restore = AiInverse(AiWrites.PLACE_RESTORE, mapOf("target_id" to AiRevert.ID)),
    )

    private val CONTACT = AiResource(
        key = "contact",
        cn = "联系人",
        idKey = "contact_id",
        readKeys = setOf("display_name", "phone"),
        labels = mapOf("display_name" to "姓名", "phone" to "手机号"),
        actions = listOf(
            update(AiWrites.CONTACT_UPDATE),
            delete(AiWrites.CONTACT_DELETE),
            paired(AiWrites.CONTACT_RESTORE, AiInverse(AiWrites.CONTACT_DELETE, mapOf("contact_id" to AiRevert.ID)), idKey = "target_id"),
        ),
        read = { ds, id -> ds.snapshot("contact", id) },
        restore = AiInverse(AiWrites.CONTACT_RESTORE, mapOf("target_id" to AiRevert.ID)),
    )

    private val ARREARS_UNIT = AiResource(
        key = "arrears_unit",
        cn = "挂账单位",
        idKey = "unit_id",
        readKeys = setOf("name", "phone", "remark", "credit_limit"),
        labels = mapOf(
            "name" to "单位名",
            "phone" to "电话",
            "remark" to "备注",
            // 中文名不是凑数：撤回读不到它时，卡上那句警告要用它（裸英文键等于没告诉用户）。
            "credit_limit" to "额度上限",
        ),
        moneyKeys = setOf("credit_limit"),
        // ⚠️ 额度**能被清空**（后端把 "不限额" 存成 null，而 `ArrearsUnitEditRequest.creditLimit`
        // 只有 JsonNull 才发得出去）：不在这里点名，"原来是不限额 → 撤回回不限额"就会被写成
        // 一句假话「这个接口清不掉它——撤回时它会保持现在的值」。
        nullableWritable = setOf("credit_limit"),
        actions = listOf(
            update(AiWrites.ARREARS_UNIT_UPDATE),
            // 设额度（2026-10-08 CHG-0087）：与"改单位资料"走**同一个** PATCH，但 payload 只带
            // unit_id + credit_limit，所以撤回就是通用那条路（把这一个键写回旧值），不用额外声明。
            update(AiWrites.ARREARS_UNIT_SET_CREDIT_LIMIT),
            delete(AiWrites.ARREARS_UNIT_DELETE),
            paired(AiWrites.ARREARS_UNIT_RESTORE, AiInverse(AiWrites.ARREARS_UNIT_DELETE, mapOf("unit_id" to AiRevert.ID)), idKey = "target_id"),
        ),
        read = { ds, id -> ds.snapshot("arrears_unit", id) },
        restore = AiInverse(AiWrites.ARREARS_UNIT_RESTORE, mapOf("target_id" to AiRevert.ID)),
    )

    /**
     * 单位换算（一车 = 8 方，2026-09-24）。
     *
     * `idKey = "conversion_id"`：AI 的改/删动作按**那行等式**找到这一条
     * （换算没有别的自然名字），编号从这里进 payload。
     * `readKeys` 必须与 [AiRevertRead.unitConversion] 写出去的键**逐字相同** ——
     * 少一个键的后果是"撤回读到了、写回去时取不到"，而那种错不报错。
     */
    private val UNIT_CONVERSION = AiResource(
        key = "unit_conversion",
        cn = "单位换算",
        idKey = "conversion_id",
        readKeys = setOf("from_unit", "to_unit", "factor", "remark"),
        labels = mapOf(
            "from_unit" to "从这个单位", "to_unit" to "换算成",
            "factor" to "换算率", "remark" to "备注",
        ),
        actions = listOf(
            update(AiWrites.UNIT_CONVERSION_UPDATE),
            delete(AiWrites.UNIT_CONVERSION_DELETE),
            paired(
                AiWrites.UNIT_CONVERSION_RESTORE,
                AiInverse(AiWrites.UNIT_CONVERSION_DELETE, mapOf("conversion_id" to AiRevert.ID)),
                idKey = "target_id",
            ),
        ),
        read = { ds, id -> ds.snapshot("unit_conversion", id) },
        restore = AiInverse(AiWrites.UNIT_CONVERSION_RESTORE, mapOf("target_id" to AiRevert.ID)),
    )

    private val FREIGHT_TEMPLATE = AiResource(
        key = "freight_template",
        cn = "运费模板",
        idKey = "template_id",
        readKeys = setOf("from_place", "to_place", "fee", "remark"),
        labels = mapOf("from_place" to "起点", "to_place" to "终点", "fee" to "运费", "remark" to "备注"),
        moneyKeys = setOf("fee"),
        actions = listOf(
            update(AiWrites.FREIGHT_TEMPLATE_UPDATE),
            delete(AiWrites.FREIGHT_TEMPLATE_DELETE),
            paired(AiWrites.FREIGHT_TEMPLATE_RESTORE, AiInverse(AiWrites.FREIGHT_TEMPLATE_DELETE, mapOf("template_id" to AiRevert.ID)), idKey = "target_id"),
        ),
        read = { ds, id -> ds.snapshot("freight_template", id) },
        restore = AiInverse(AiWrites.FREIGHT_TEMPLATE_RESTORE, mapOf("target_id" to AiRevert.ID)),
    )

    /**
     * 司机计费规则（v3.36）。
     *
     * 撤回怎么成立：改参数是"字段值变了"，由框架按写之前的现场 patch 回去；
     * 删除是伪装删除，走 `/{id}/restore`。
     * **挂载不在这里**——它改的是司机（另一个资源），而且"挂回哪一份"只有用户知道，
     * 所以它走 `AiRevert` 的 UNDO_NONE，在卡片上就写明撤不回来。
     */
    private val DRIVER_RULE = AiResource(
        key = "driver_rule",
        cn = "计费规则",
        idKey = "rule_id",
        readKeys = setOf(
            "name", "salary", "piece_amount", "piece_unit", "commission_base", "commission_rate", "remark",
            // 抽成范围也要读得回来：`driver_rule.update` 会写 `commission_products`，
            // 读不回来的话"撤回这次改动"会**静默丢掉范围**（改之前只抽 2 个商品，撤回来变成全抽）。
            "commission_products",
        ),
        labels = mapOf(
            "name" to "规则名",
            "salary" to "固定工资",
            "piece_amount" to "每单金额",
            "piece_unit" to "计件单位",
            "commission_base" to "提成基数",
            "commission_rate" to "提成比例",
            "commission_products" to "抽成商品",
            "remark" to "备注",
        ),
        moneyKeys = setOf("salary", "piece_amount", "commission_rate"),
        actions = listOf(
            update(AiWrites.DRIVER_RULE_UPDATE),
            delete(AiWrites.DRIVER_RULE_DELETE),
            paired(
                AiWrites.DRIVER_RULE_RESTORE,
                AiInverse(AiWrites.DRIVER_RULE_DELETE, mapOf("rule_id" to AiRevert.ID)),
                idKey = "target_id",
            ),
        ),
        read = { ds, id -> ds.snapshot("driver_rule", id) },
        restore = AiInverse(AiWrites.DRIVER_RULE_RESTORE, mapOf("target_id" to AiRevert.ID)),
    )

    // ============================================================ 商品 / 定价 / 库存
    private val PRODUCT = AiResource(
        key = "product",
        cn = "商品",
        idKey = "product_id",
        readKeys = setOf(
            "name", "default_unit_price", "unit", "low_stock_alert", "active",
        ),
        labels = mapOf(
            "name" to "商品名",
            "default_unit_price" to "默认单价",
            "unit" to "单位",
            "low_stock_alert" to "库存报警阈值",
            "active" to "是否在售",
        ),
        actions = listOf(
            update(
                AiWrites.PRODUCTS_UPDATE,
                // ⛔ 成本价**撤回不回去**，这里是明说，不是漏了。
                //    撤回方案要读"改之前是多少"，而成本价**刻意不进 readKeys**：
                //    撤回卡的文案是模型生成的上下文的一部分，成本只在用户自己打开
                //    「允许 AI 查看成本与毛利」之后才该出现在那条路上 —— 撤回卡不在那条路上。
                //    所以声明 drop，并把这件事**写在卡上**：用户点确认前就知道
                //    "撤回只回名称/单价/单位/阈值，成本价不回"，而不是撤完以为全回去了。
                drop = setOf("cost_price"),
                note = "撤回只把名称、默认单价、单位、报警阈值改回去；成本价不跟着撤回" +
                    "（撤回读不到旧成本价）。要改成本价请到商品管理的编辑里改一次。",
            ),
            // 上下架：payload 里的键叫 `active`（后端字段是 is_active），快照按 payload 键给。
            update(AiWrites.PRODUCTS_SET_ACTIVE),
            delete(AiWrites.PRODUCTS_DELETE),
            // 库存调整的撤回**不是**把库存改回去，而是再记一条反向流水。
            // 为什么：库存是流水累加出来的，"改回去"会让流水和库存对不上。
            update(
                AiWrites.INVENTORY_ADJUST,
                negate = setOf("change"),
                // `unit_cost` 同理：反向那条流水不带进货价（成本走"哪批货多少钱"的语义，
                // 一条"撤回流水"没有对应的货）。商品成本价也**不会**被撤回改回去 —— 见卡上那句。
                drop = setOf("note", "unit_cost"),
                // ⚠️ 旧原因**不搬**，但不能就这么空着（v3.45，真机 E2E 抓到的空原因流水）：
                //    真机上那条反向流水的 note 是 `''`——"入库 +5（原因：真机校验B）"下面
                //    躺着一条 "-5（原因：无）"，过几天谁也说不清那 5 件是怎么少的。
                //    旧那句说的是"上一次为什么入库"，搬到反向流水上会被读成"这一次为什么出库"，
                //    所以补一句说得清这一次是什么的字（卡片上照实写出来给用户看）。
                dropWrite = mapOf("note" to "撤回：刚才那次库存调整（由撤回入口发起）"),
                note = "库存按「相反方向再记一条流水」来撤回（原来那条留着——库存变动本来就该留痕）；" +
                    "进货价与商品成本价不跟着撤回。",
            ),
            paired(AiWrites.PRODUCTS_RESTORE, AiInverse(AiWrites.PRODUCTS_DELETE, mapOf("product_id" to AiRevert.ID)), idKey = "target_id"),
        ),
        read = { ds, id -> ds.snapshot("product", id) },
        restore = AiInverse(AiWrites.PRODUCTS_RESTORE, mapOf("target_id" to AiRevert.ID)),
    )

    private val PRICE_RULE = AiResource(
        key = "price_rule",
        cn = "批发商专属价",
        idKey = "rule_id",
        readKeys = setOf("shipper_id", "product_id", "special_unit_price"),
        labels = mapOf("special_unit_price" to "专属单价"),
        silent = setOf("shipper_id", "product_id"),
        moneyKeys = setOf("special_unit_price"),
        actions = listOf(
            update(AiWrites.PRICE_RULES_UPDATE),
            // 专属价的删除**没有** `/{id}/restore` 端点，但后端在 `POST /price-rules`
            // 收到同一个（批发商 + 商品）时会**复活原来那一行**（v3.26 实测过）。
            // 所以它的恢复动作就是"再设一次同样的价"——参数从写之前的现场搬。
            delete(AiWrites.PRICE_RULES_DELETE),
        ),
        read = { ds, id -> ds.snapshot("price_rule", id) },
        restore = AiInverse(
            AiWrites.PRICE_RULES_SET,
            mapOf(
                "shipper_id" to "shipper_id",
                "product_id" to "product_id",
                "special_unit_price" to "special_unit_price",
            ),
            lines = listOf("专属价在库里是软删（行还在），这一下会「把原来那一行复活」，不是新建一条"),
        ),
    )

    // ==================================================== 商品分类名册 / 车辆 / 可见范围（v3.43）

    /**
     * 商品分类名册。
     *
     * ### 删除的撤回为什么是「按原名重建」而不是 `/{id}/restore`
     * 名册没有软删（后端 `delete_category` 就是 `db.delete(row)`），所以没有恢复端点。
     * 但"重建一格"在语义上是完整的：**名字和位置都能照原样写回去**，而删除的前提
     * 本来就是"没有商品挂在它下面"（后端会拦），所以不会有商品因为重建而失去归属。
     * 代价只有一个：**新的那一行编号和原来不一样**——[restoreLines] 就是为这件事写的，
     * 不能让框架那两句"行还在、逐字段照搬"的默认文案留在卡上（那对这张表是假话）。
     */
    private val PRODUCT_CATEGORY = AiResource(
        key = "product_category",
        cn = "商品分类",
        idKey = "category_id",
        readKeys = setOf("name", "sort_order"),
        labels = mapOf("name" to "分类名", "sort_order" to "顺序（第几位）"),
        actions = listOf(
            update(AiWrites.PRODUCT_CATEGORY_UPDATE),
            delete(AiWrites.PRODUCT_CATEGORY_DELETE),
        ),
        read = { ds, id -> ds.snapshot("product_category", id) },
        restore = AiInverse(
            AiWrites.PRODUCT_CATEGORY_CREATE,
            mapOf("name" to "name", "sort_order" to "sort_order"),
            lines = listOf("名字和位置都照删之前那一行写回去（这一步走的就是「新建商品分类」那个动作）"),
        ),
        restoreLines = listOf(
            "按原来的名字和位置重建一格：分类名册没有回收站，删掉的那一行是真没了",
            "⚠️ 重建出来的是新的一行，编号和原来不一样（挂在它下面的商品不受影响——能删就说明本来没有商品挂着）",
        ),
    )

    /**
     * 地点分组名册（**按人分区**：每个人管自己地址库左栏那一列）。
     *
     * 与商品分类那份是同一套做法（改名级联、删的前提是"没有地点挂着"、
     * 撤回是按原名重建一格因此**编号会变**），差别只有"这是我自己那一份"。
     */
    private val PLACE_CATEGORY = AiResource(
        key = "place_category",
        cn = "地点分组",
        idKey = "category_id",
        readKeys = setOf("name", "sort_order"),
        labels = mapOf("name" to "分组名", "sort_order" to "顺序（第几位）"),
        actions = listOf(
            update(AiWrites.PLACE_CATEGORY_UPDATE),
            delete(AiWrites.PLACE_CATEGORY_DELETE),
        ),
        read = { ds, id -> ds.snapshot("place_category", id) },
        restore = AiInverse(
            AiWrites.PLACE_CATEGORY_CREATE,
            mapOf("name" to "name", "sort_order" to "sort_order"),
            lines = listOf("名字和位置都照删之前那一行写回去（这一步走的就是「新建地点分组」那个动作）"),
        ),
        restoreLines = listOf(
            "按原来的名字和位置重建一格：分组名册没有回收站，删掉的那一行是真没了",
            "⚠️ 重建出来的是新的一行，编号和原来不一样（挂在它下面的地点不受影响——能删就说明本来没有地点挂着）",
            "⚠️ 只影响你自己的地址库",
        ),
    )

    /**
     * 联系人分类名册（**按人分区**：每个人管自己联系人列表左栏那一列，FEAT-0007）。
     *
     * 与地点分组那份是同一套做法（改名级联、删的前提是"没有联系人挂着"、
     * 撤回是按原名重建一格因此**编号会变**），差别只有级联目标和"这是我自己那一份"。
     */
    private val CONTACT_CATEGORY = AiResource(
        key = "contact_category",
        cn = "联系人分类",
        idKey = "category_id",
        readKeys = setOf("name", "sort_order"),
        labels = mapOf("name" to "分类名", "sort_order" to "顺序（第几位）"),
        actions = listOf(
            update(AiWrites.CONTACT_CATEGORY_UPDATE),
            delete(AiWrites.CONTACT_CATEGORY_DELETE),
        ),
        read = { ds, id -> ds.snapshot("contact_category", id) },
        restore = AiInverse(
            AiWrites.CONTACT_CATEGORY_CREATE,
            mapOf("name" to "name", "sort_order" to "sort_order"),
            lines = listOf("名字和位置都照删之前那一行写回去（这一步走的就是「新建联系人分类」那个动作）"),
        ),
        restoreLines = listOf(
            "按原来的名字和位置重建一格：分类名册没有回收站，删掉的那一行是真没了",
            "⚠️ 重建出来的是新的一行，编号和原来不一样（挂在它下面的联系人不受影响——能删就说明本来没有人挂着）",
            "⚠️ 只影响你自己的联系人列表",
        ),
    )

    /**
     * 线路分类名册（**按人分区**：每个人管自己「地址与联系人 → 路线」那个分类抽屉，FEAT-0009）。
     *
     * 与联系人分类那份是同一套做法（改名级联、删的前提是"没有线路挂着"、
     * 撤回是按原名重建一格因此**编号会变**），差别只有级联目标（改的是
     * `shipper_addresses.category`）与这一份名册是这一批**从零补上**的。
     */
    private val ROUTE_CATEGORY = AiResource(
        key = "route_category",
        cn = "线路分类",
        idKey = "category_id",
        readKeys = setOf("name", "sort_order"),
        labels = mapOf("name" to "分类名", "sort_order" to "顺序（第几位）"),
        actions = listOf(
            update(AiWrites.ROUTE_CATEGORY_UPDATE),
            delete(AiWrites.ROUTE_CATEGORY_DELETE),
        ),
        read = { ds, id -> ds.snapshot("route_category", id) },
        restore = AiInverse(
            AiWrites.ROUTE_CATEGORY_CREATE,
            mapOf("name" to "name", "sort_order" to "sort_order"),
            lines = listOf("名字和位置都照删之前那一行写回去（这一步走的就是「新建线路分类」那个动作）"),
        ),
        restoreLines = listOf(
            "按原来的名字和位置重建一格：分类名册没有回收站，删掉的那一行是真没了",
            "⚠️ 重建出来的是新的一行，编号和原来不一样（挂在它下面的线路不受影响——能删就说明本来没有线路挂着）",
            "⚠️ 只影响你自己的常用线路",
        ),
    )

    // ============================ 另外三张配置名册（2026-09-23 补齐 AI 能力覆盖）============
    //
    // 三张都**只有派单员**（后端那几组端点都是派单员权限），都与商品分类同一套做法：
    // 名册没有软删（后端 `delete_category` 就是 `db.delete(row)`），所以删除的撤回是
    // **按原名重建一格**（名字和位置都能照原样写回去，能删就说明本来没有东西挂着）。
    // ⚠️ 代价只有一个、必须写在卡上：**新的那一行编号和原来不一样**。

    /** 开销分类名册。改名的撤回会把 `link_kind`（卡片突出哪一项）一起写回去。 */
    private val EXPENSE_CATEGORY = AiResource(
        key = "expense_category",
        cn = "开销分类",
        idKey = "category_id",
        readKeys = setOf("name", "sort_order", "link_kind"),
        labels = mapOf(
            "name" to "分类名",
            "sort_order" to "顺序（第几位）",
            "link_kind" to "卡片上突出哪一项",
        ),
        actions = listOf(
            update(AiWrites.EXPENSE_CATEGORY_UPDATE),
            delete(AiWrites.EXPENSE_CATEGORY_DELETE),
        ),
        read = { ds, id -> ds.snapshot("expense_category", id) },
        restore = AiInverse(
            AiWrites.EXPENSE_CATEGORY_CREATE,
            mapOf("name" to "name", "sort_order" to "sort_order", "link_kind" to "link_kind"),
            lines = listOf("名字、位置和「突出哪一项」都照删之前那一行写回去（走的还是「新建开销分类」那个动作）"),
        ),
        restoreLines = listOf(
            "按原来的名字和位置重建一格：开销分类名册没有回收站，删掉的那一行是真没了",
            "⚠️ 重建出来的是新的一行，编号和原来不一样（能删就说明本来没有开销挂在它下面）",
        ),
    )

    /** 运费分类名册（「哪几类货」那张配置表）。 */
    private val FREIGHT_CATEGORY = AiResource(
        key = "freight_category",
        cn = "运费分类",
        idKey = "category_id",
        readKeys = setOf("name", "sort_order"),
        labels = mapOf("name" to "分类名", "sort_order" to "顺序（第几位）"),
        actions = listOf(
            update(AiWrites.FREIGHT_CATEGORY_UPDATE),
            delete(AiWrites.FREIGHT_CATEGORY_DELETE),
        ),
        read = { ds, id -> ds.snapshot("freight_category", id) },
        restore = AiInverse(
            AiWrites.FREIGHT_CATEGORY_CREATE,
            mapOf("name" to "name", "sort_order" to "sort_order"),
            lines = listOf("名字和位置都照删之前那一行写回去（走的还是「新建运费分类」那个动作）"),
        ),
        restoreLines = listOf(
            "按原来的名字和位置重建一格：运费分类名册没有回收站，删掉的那一行是真没了",
            "⚠️ 重建出来的是新的一行，编号和原来不一样（能删就说明本来没有价目/规则挂着）",
        ),
    )

    /** 预订单分类名册。 */
    private val ORDER_TEMPLATE_CATEGORY = AiResource(
        key = "order_template_category",
        cn = "预订单分类",
        idKey = "category_id",
        readKeys = setOf("name", "sort_order"),
        labels = mapOf("name" to "分类名", "sort_order" to "顺序（第几位）"),
        actions = listOf(
            update(AiWrites.ORDER_TEMPLATE_CATEGORY_UPDATE),
            delete(AiWrites.ORDER_TEMPLATE_CATEGORY_DELETE),
        ),
        read = { ds, id -> ds.snapshot("order_template_category", id) },
        restore = AiInverse(
            AiWrites.ORDER_TEMPLATE_CATEGORY_CREATE,
            mapOf("name" to "name", "sort_order" to "sort_order"),
            lines = listOf("名字和位置都照删之前那一行写回去（走的还是「新建预订单分类」那个动作）"),
        ),
        restoreLines = listOf(
            "按原来的名字和位置重建一格：预订单分类名册没有回收站，删掉的那一行是真没了",
            "⚠️ 重建出来的是新的一行，编号和原来不一样（能删就说明本来没有预设单挂着）",
        ),
    )

    /**
     * 账号分类名册（**全店一份**，2026-10-05 FEAT-0010；账户/司机/货主/批发商四个名册页共用）。
     *
     * 与上面那几张分类名册同一套（改名级联、删的前提是"没有账号挂着"、
     * 撤回是按原名重建一格因此**编号会变**），差别只有一处：它**不是"你自己那一份"**。
     */
    private val USER_CATEGORY = AiResource(
        key = "user_category",
        cn = "账号分类",
        idKey = "category_id",
        readKeys = setOf("name", "sort_order"),
        labels = mapOf("name" to "分类名", "sort_order" to "顺序（第几位）"),
        actions = listOf(
            update(AiWrites.USER_CATEGORY_UPDATE),
            delete(AiWrites.USER_CATEGORY_DELETE),
        ),
        read = { ds, id -> ds.snapshot("user_category", id) },
        restore = AiInverse(
            AiWrites.USER_CATEGORY_CREATE,
            mapOf("name" to "name", "sort_order" to "sort_order"),
            lines = listOf("名字和位置都照删之前那一行写回去（这一步走的就是「新建账号分类」那个动作）"),
        ),
        restoreLines = listOf(
            "按原来的名字和位置重建一格：分类名册没有回收站，删掉的那一行是真的没了",
            "⚠️ 重建出来的是新的一行，编号和原来不一样（能删就说明本来没有账号挂着）",
            "⚠️ 这份名册全店一份：重建出来的这一格，所有人看到的「账户管理」左栏都跟着变",
        ),
    )

    /**
     * 车辆分类名册（**全店一份**，2026-10-05 FEAT-0010）。
     *
     * ⚠️ 与车辆上的「车型 / 车体」（vehicle_type、body_type）是**两件不同的事**，
     * 这条名册只管"左栏分成哪几格"，也不参与计费。撤回语义与账号分类一字不差。
     */
    private val VEHICLE_CATEGORY = AiResource(
        key = "vehicle_category",
        cn = "车辆分类",
        idKey = "category_id",
        readKeys = setOf("name", "sort_order"),
        labels = mapOf("name" to "分类名", "sort_order" to "顺序（第几位）"),
        actions = listOf(
            update(AiWrites.VEHICLE_CATEGORY_UPDATE),
            delete(AiWrites.VEHICLE_CATEGORY_DELETE),
        ),
        read = { ds, id -> ds.snapshot("vehicle_category", id) },
        restore = AiInverse(
            AiWrites.VEHICLE_CATEGORY_CREATE,
            mapOf("name" to "name", "sort_order" to "sort_order"),
            lines = listOf("名字和位置都照删之前那一行写回去（这一步走的就是「新建车辆分类」那个动作）"),
        ),
        restoreLines = listOf(
            "按原来的名字和位置重建一格：分类名册没有回收站，删掉的那一行是真的没了",
            "⚠️ 重建出来的是新的一行，编号和原来不一样（能删就说明本来没有车挂着）",
            "⚠️ 这份名册全店一份：重建出来的这一格，所有人看到的「车辆管理」左栏都跟着变",
        ),
    )

    /** 车辆（改车牌/车型/启用标记；换司机是另一个动作）。 */
    private val VEHICLE = AiResource(
        key = "vehicle",
        cn = "车辆",
        idKey = "vehicle_id",
        readKeys = setOf("plate_no", "vehicle_type", "driver_id", "active"),
        labels = mapOf(
            "plate_no" to "车牌号",
            "vehicle_type" to "车型",
            "driver_id" to "关联司机",
            "active" to "是否启用",
        ),
        // ⚠️ driver_id 是**静默键**：它是内部编号，"司机：5 → 撤回到 3"用户核对不了
        //    （和地址的经纬度同一种处理：跟着写回，但不单独占一行）。
        silent = setOf("driver_id"),
        // …但它**写得回 null**（v3.44）：解绑是一个真实的取值，而"写回 null"以前是做不到的
        // （后端 `if driver_id is not None` 会把空值忽略掉）。不声明这一条的话，
        // 撤回"原来没绑司机"的那一次会得到一句**假话**：「这一项原来就是空的，而这个接口清不掉它」。
        nullableWritable = setOf("driver_id"),
        actions = listOf(
            update(AiWrites.VEHICLE_UPDATE),
            // 「换/解绑司机」的撤回 = **同一个动作把旧司机写回去**（[update] 那种，走 patchPlan）。
            //
            // ⚠️⚠️ 这里原来写的是 `paired(自己, AiInverse(自己, …))`，那是**错的**（真机 E2E 抓到）：
            //    `AiRevert.pairedPlan` 的第一行就是 `if (inverse.actionId == entry.id) return null`
            //    ——"逆操作是自己"根本不成立，撤回方案**永远造不出来**；而 `canRevert()` 照样返回 true，
            //    于是卡片敢印「会出现『撤回』」，执行完却只回一句"这次没能挂上撤回"。
            //    全库 16 处 `paired` 只有那一处是自逆（其余都是派单↔撤回派单这种两个不同动作）。
            //    正确的形状是 `update`：payload 里有什么键，就把这些键写回旧值——
            //    前提是 payload **一定带上 driver_id**（解绑时是 null），见 `CrudSpec.alwaysIncludeTargets`。
            update(AiWrites.VEHICLE_SET_DRIVER),
        ),
        read = { ds, id -> ds.snapshot("vehicle", id) },
    )

    /**
     * 商品可见范围（白名单）。
     *
     * 撤回就是"把开关和白名单整份写回写之前的样子"——它天然可逆（后端 PUT 是整份替换），
     * 所以这里不需要任何特殊形状。
     *
     * ⚠️ 四个明细键都是**静默键**：`product_ids`/`hidden_product_ids` 是内部编号，
     *    "商品白名单：[12, 15] → 撤回到 [12, 13, 15]"这种东西摆在卡上等于没写（用户根本不认编号）；
     *    分类那两个虽然是人话，但一张撤回卡上连列四串名字会把它淹掉。
     *    它们照样整份写回去，只是不占一行；要改哪几样，**正向那张卡上是一个一个列了名字的**。
     *
     * ⚠️ 2026-10-06（CHG-0062）：可见范围有了"按分类给 / 单独关掉"这两维，读回键也从 2 个变 5 个。
     *    少声明一个的后果不是"卡上少一行"，而是**撤回时那个键根本没写回去**（撤回看起来成功了），
     *    单测那条"labels + silent 必须正好等于 readKeys"就是为这件事钉的。
     */
    private val PRODUCT_VISIBILITY = AiResource(
        key = "product_visibility",
        cn = "商品可见范围",
        idKey = "user_id",
        readKeys = setOf(
            "scope", "product_ids", "category_names", "hidden_product_ids", "hidden_category_names",
        ),
        labels = mapOf(
            "scope" to "可见范围（all=全部商品 / custom=只给勾选的）",
            "product_ids" to "勾选的商品",
            "category_names" to "勾选的分类",
            "hidden_product_ids" to "单独关掉的商品",
            "hidden_category_names" to "整类关掉的分类",
        ),
        silent = setOf(
            "product_ids", "category_names", "hidden_product_ids", "hidden_category_names",
        ),
        actions = listOf(update(AiWrites.USER_PRODUCT_VISIBILITY)),
        read = { ds, id -> ds.snapshot("product_visibility", id) },
    )

    // ============================================================ 账号

    private val USER = AiResource(
        key = "user",
        cn = "账号",
        idKey = "user_id",
        readKeys = setOf(
            "full_name", "phone", "active", "member", "billing_mode", "vehicle_type", "salary",
        ),
        labels = mapOf(
            "full_name" to "姓名",
            "phone" to "手机号",
            "active" to "启用状态",
            "member" to "是否批发商",
            "billing_mode" to "司机计费方式",
            "vehicle_type" to "车型",
            "salary" to "固定工资",
        ),
        actions = listOf(
            update(AiWrites.USERS_UPDATE_PROFILE),
            update(AiWrites.USERS_SET_BILLING),
            update(AiWrites.USERS_SET_ACTIVE),
            update(AiWrites.USERS_SET_MEMBER),
            switcher(AiWrites.USERS_SWAP_ROLE, "把货主 ↔ 司机再对调一次，就回到原来的角色"),
            delete(AiWrites.USERS_DELETE),
            paired(AiWrites.USERS_RESTORE, AiInverse(AiWrites.USERS_DELETE, mapOf("user_id" to AiRevert.ID)), idKey = "target_id"),
        ),
        read = { ds, id -> ds.snapshot("user", id) },
        // ⚠️ 密码**不在**这里：它只存哈希，读不回来也写不回去。
        //    `users.set_password` 因此不在这个资源的动作清单里，走 UNDO_NONE 的那条理由。
        restore = AiInverse(AiWrites.USERS_RESTORE, mapOf("target_id" to AiRevert.ID)),
    )

    // ============================================================ 订单

    private val ORDER = AiResource(
        key = "order",
        cn = "订单",
        idKey = "order_id",
        readKeys = setOf(
            "freight_fee", "delivery_description", "address_detail", "contact_dongjia_phone",
            "contact_boss_phone", "contact_dongjia_name", "contact_boss_name",
            "remark", "internal_notes",
            // 下面这些是**成对动作**要用的键（不是"改一个字段"，而是"再做另一件事"的原料）
            "internal_note", "driver_id", "collect_cash", "reason", "expected_before",
            // 逐单覆盖值（v3.37）：撤回派单后"照原样再派一次"必须把它们一起搬回去，
            // 否则反悔之后这一单的钱悄悄变回规则里的默认值。
            "driver_piece_amount", "driver_commission_rate",
            GEO_LAT, GEO_LNG,
            // 让价那四个键（2026-10-08 CHG-0087）：**只有「取消让价」的撤回用得上**——
            // 它要把刚取消掉的那套让价整份打回去，参数只能从写之前的现场搬
            //（那个方向没有"以后再重新说一次"的余地：用户点的是撤回，不是重新让价）。
            "discount_kind", "discount_value", "discount_line_ids", "discount_reason",
        ),
        labels = mapOf(
            "freight_fee" to "司机运费",
            "driver_piece_amount" to "这一单单独定的司机金额",
            "driver_commission_rate" to "这一单单独定的提成比例",
            "delivery_description" to "送货说明",
            "address_detail" to "送达地址",
            "contact_dongjia_phone" to "收货人电话",
            "contact_boss_phone" to "下单人电话",
            "contact_dongjia_name" to "收货人名称",
            "contact_boss_name" to "下单人名称",
            "remark" to "备注",
            "internal_notes" to "内部备注",
            // 让价四键：撤回时读不到就得不带（见下面 paired 里那条说明），
            // 那一行警告必须说人话，所以四个键都给中文名。
            "discount_kind" to "让价方式",
            "discount_value" to "让价数值",
            "discount_line_ids" to "让价范围",
            "discount_reason" to "让价理由",
            // 静默键也要有中文名：读不回来时它会以警告行的形式出现在卡上（见 ADDRESS 的同名处理）。
            GEO_LAT to "纬度",
            GEO_LNG to "经度",
        ),
        moneyKeys = setOf("freight_fee", "driver_piece_amount"),
        silent = setOf(
            "internal_note", "driver_id", "collect_cash", "reason", "expected_before",
            "driver_piece_amount", "driver_commission_rate",
            GEO_LAT, GEO_LNG,
        ),
        actions = listOf(
            update(AiWrites.ORDERS_FREIGHT),
            update(AiWrites.ORDERS_UPDATE),
            // 补联系信息（2026-10-08 CHG-0085）：货主那一扇门，只动四个联系字段，**终态单也允许**。
            // 撤回走通用的「payload 改了哪几个键、就撤回哪几个键」（四个联系字段都在 readKeys / labels 里）。
            update(AiWrites.ORDERS_UPDATE_CONTACT),
            // 派单 ↔ 撤回派单：撤回不是"把司机栏清空"这一个字段，而是走撤回动作本身
            //（它会退回待派单、清司机栏、推送给原司机）。v3.26 这段是手写的，现在只是声明。
            paired(
                AiWrites.ORDERS_ASSIGN,
                AiInverse(
                    AiWrites.ORDERS_RECALL,
                    mapOf("order_id" to AiRevert.ID, "reason" to "=撤回：刚才那次派单勾错了（由撤回入口发起）"),
                    lines = listOf(
                        "把这单退回「待派单」，司机栏清空，可以重新派给别人",
                        "原司机会收到一条撤回推送",
                        "派单时填的运费、收取现金会一起清掉",
                    ),
                ),
            ),
            // 撤回派单的撤回 = 按写之前的现场**再派一次**（司机、运费、收款方式都是原样）。
            paired(
                AiWrites.ORDERS_RECALL,
                AiInverse(
                    AiWrites.ORDERS_ASSIGN,
                    mapOf(
                        "order_id" to AiRevert.ID,
                        "driver_id" to "driver_id",
                        "internal_note" to "internal_note",
                        "freight_fee" to "freight_fee",
                        "collect_cash" to "collect_cash",
                        // 逐单覆盖也要照原样搬回来，否则"撤回→反悔→再派"之后
                        // 这一单的钱会悄悄变回规则里的默认值（账单上少的那笔没人发现）
                        "driver_piece_amount" to "driver_piece_amount",
                        "driver_commission_rate" to "driver_commission_rate",
                    ),
                    lines = listOf("按刚才撤回时记下的司机、运费、收款方式，「重新派一次」"),
                ),
            ),
            // 标记异常 ↔ 解除异常：两个动作互为逆操作。
            paired(
                AiWrites.ORDERS_MARK_EXCEPTION,
                AiInverse(
                    AiWrites.ORDERS_RESOLVE_EXCEPTION,
                    mapOf("order_id" to AiRevert.ID, "note" to "=撤回：刚才那次异常标记（由撤回入口发起）"),
                    lines = listOf("把异常标记解除，这一单回到正常状态"),
                ),
            ),
            paired(
                AiWrites.ORDERS_RESOLVE_EXCEPTION,
                AiInverse(
                    AiWrites.ORDERS_MARK_EXCEPTION,
                    mapOf(
                        "order_id" to AiRevert.ID,
                        "reason" to "reason",
                        "expected_before" to "expected_before",
                    ),
                    lines = listOf("按刚才解除时记下的原因和预计送达时间，「重新标记为异常」"),
                ),
            ),
            // 取消让价 ↔ 让价（2026-10-08 CHG-0087）：两件事互为反面，但**只有一个方向有撤回按钮**。
            // 「给这一单让价」没有（第一次让价时旧值全是空的 —— 撤回拼不出任何一项，按钮根本不会出现，
            // 而卡片最后一行是静态的、照样会承诺一个按钮；理由写在 AiRevert.undoNoneTable 里）；
            // 「取消让价」有：它把刚取消掉的那套让价整份打回去，四个参数全部从写之前的现场搬。
            paired(
                AiWrites.ORDERS_DISCOUNT_CLEAR,
                AiInverse(
                    AiWrites.ORDERS_DISCOUNT,
                    mapOf(
                        "order_id" to AiRevert.ID,
                        "discount_kind" to "discount_kind",
                        "discount_value" to "discount_value",
                        "discount_line_ids" to "discount_line_ids",
                        "discount_reason" to "discount_reason",
                    ),
                    lines = listOf(
                        "把刚才取消掉的那套让价整份打回去：方式、数值、范围、理由都是取消之前的样子",
                        "后台按当时的快照精确还原每一行的金额（和手工重新让价是同一条路，也一样留痕）",
                    ),
                ),
                idKey = "order_id",
            ),
            delete(AiWrites.ORDERS_SOFT_DELETE),
            paired(
                AiWrites.ORDERS_RESTORE,
                AiInverse(AiWrites.ORDERS_SOFT_DELETE, mapOf("order_id" to AiRevert.ID)),
                idKey = "order_id",
            ),
        ),
        read = { ds, id -> ds.snapshot("order", id) },
        restore = AiInverse(AiWrites.ORDERS_RESTORE, mapOf("order_id" to AiRevert.ID)),
    )

    private val ORDER_LINE = AiResource(
        key = "order_line",
        cn = "订单商品行",
        idKey = "line_id",
        readKeys = setOf("order_id", "product", "product_name", "quantity", "unit_price"),
        labels = mapOf("product_name" to "商品", "quantity" to "数量", "unit_price" to "单价"),
        silent = setOf("order_id", "product"),
        moneyKeys = setOf("unit_price"),
        actions = listOf(
            update(AiWrites.ORDERS_UPDATE_LINE),
            // 商品行是**硬删**（后端没有恢复端点），但"再加一行同样的商品"就够了：
            // 商品名、数量、单价都在写之前的现场里。新行的编号和原来不一样，卡片上写清楚。
            paired(
                AiWrites.ORDERS_DELETE_LINE,
                AiInverse(
                    AiWrites.ORDERS_ADD_LINE,
                    mapOf(
                        "order_id" to "order_id",
                        "product" to "product",
                        "quantity" to "quantity",
                        "unit_price" to "unit_price",
                    ),
                    lines = listOf(
                        "把这一行「重新加回去」（商品名、数量、单价照原样）",
                        "⚠️ 新行的编号和原来那一行不一样：原来的行是硬删，恢复不了",
                        "订单金额会跟着变回去",
                    ),
                ),
            ),
        ),
        read = { ds, id -> ds.snapshot("order_line", id) },
    )

    /**
     * 货主**自己那一本账**上的核销记录（批发商给下游货主核销，2026-09-20）。
     *
     * 只有**撤销 ↔ 恢复**这一对在这里：
     * · 撤销 = 软删（后端 `DELETE` 只打标记），所以撤回就是"把它放回来"；
     * · **核销本身（`my_ledger.settle`）不在这里**：它写的是**新的一条**，
     *   编号在写之前不存在，所以挂不上"撤回"按钮——那条理由逐句写在
     *   `AiRevert` 的 `UNDO_NONE` 里（并告诉用户该说什么话把它撤掉）。
     */
    private val SHIPPER_SETTLEMENT = AiResource(
        key = "shipper_settlement",
        cn = "核销记录",
        idKey = "target_id",
        readKeys = setOf("settlement_id"),
        labels = mapOf("settlement_id" to "核销记录"),
        silent = setOf("settlement_id"),
        actions = listOf(
            paired(
                AiWrites.MY_LEDGER_REVOKE,
                AiInverse(
                    AiWrites.MY_LEDGER_RESTORE,
                    mapOf("target_id" to AiRevert.ID),
                    lines = listOf(
                        "把刚撤掉的那一笔核销放回来（后台是伪删除：行还在，逐字段照搬）",
                        "放回来之后这一单重新算成「已收」，金额、商品、收款方式都和撤掉之前一样",
                        "这只动你自己那一本账，公司那边的账不受影响",
                    ),
                ),
                idKey = "settlement_id",
            ),
        ),
        // 成对动作的撤回**不需要读现场**（参数只有主键，`AiRevert.plan` 里那道判据会跳过读），
        // 而这一条被撤掉之后本来就躺在回收站里、按常规列表读不到——所以这里如实返回 null。
        read = { _, _ -> null },
    )

    // ============================================================ 账本 / 消息

    private val LEDGER_ENTRY = AiResource(
        key = "ledger_entry",
        cn = "账本流水",
        idKey = "entry_id",
        readKeys = setOf("total", "quantity", "unit_price", "entry_date", "product_name", "note"),
        labels = mapOf(
            "total" to "金额",
            "quantity" to "数量",
            "unit_price" to "单价",
            "entry_date" to "日期",
            "product_name" to "商品",
            "note" to "备注",
        ),
        moneyKeys = setOf("total", "unit_price"),
        actions = listOf(
            update(
                AiWrites.LEDGER_UPDATE_ENTRY,
                note = "⚠️ 如果这一行是从订单来的（来源=订单），撤回会「同时把订单上的商品行也改回去」" +
                    "——两者本来就是同一笔账的两面",
            ),
        ),
        read = { ds, id -> ds.snapshot("ledger_entry", id) },
    )

    private val NOTIFICATION = AiResource(
        key = "notification",
        cn = "消息",
        idKey = "notification_id",
        readKeys = setOf("title", "content"),
        labels = mapOf("title" to "标题", "content" to "正文"),
        actions = listOf(update(AiWrites.NOTIFICATIONS_UPDATE)),
        read = { ds, id -> ds.snapshot("notification", id) },
    )

    /**
     * 预订单 / 订单模板（2026-09-22 用户要求）。
     *
     * 它为什么需要撤回：预设单**会变成真订单** —— 一张被人改过的预设单会让以后每一次
     * 「一键下单」都按改后的参数生成，而界面上完全看不出来。所以"改错了要能一键改回来"。
     *
     * ⚠️ `create` 不在这张表里（与全项目其他资源同形）：**新建的撤回 = 删掉它**，
     *    由 [AiRevert] 的默认路径处理，不需要在这里声明。
     */
    private val ORDER_TEMPLATE = AiResource(
        key = "order_template",
        cn = "预设单",
        idKey = "template_id",
        readKeys = setOf("name", "shipper_id", "address", "freight_fee", "remark"),
        labels = mapOf(
            "name" to "预设单名",
            "shipper_id" to "货主",
            "address" to "送货地址",
            "freight_fee" to "预设运费",
            "remark" to "备注",
        ),
        moneyKeys = setOf("freight_fee"),
        actions = listOf(
            update(AiWrites.ORDER_TEMPLATE_UPDATE),
            delete(AiWrites.ORDER_TEMPLATE_DELETE),
            paired(
                AiWrites.ORDER_TEMPLATE_RESTORE,
                AiInverse(AiWrites.ORDER_TEMPLATE_DELETE, mapOf("template_id" to AiRevert.ID)),
                idKey = "target_id",
            ),
        ),
        read = { ds, id -> ds.snapshot("order_template", id) },
        restore = AiInverse(AiWrites.ORDER_TEMPLATE_RESTORE, mapOf("target_id" to AiRevert.ID)),
    )

    /**
     * 供应商 / 厂商档案（2026-09-22 用户要求「给供应商付尾款」，拍板口径是"跟客户一个量级的档案"）。
     *
     * 撤回怎么成立：改资料是"字段值变了"（框架按写之前的现场 patch 回去）；
     * 删除是伪装删除，走 `/{id}/restore`。
     */
    private val SUPPLIER = AiResource(
        key = "supplier",
        cn = "供应商",
        idKey = "supplier_id",
        readKeys = setOf("name", "contact_name", "phone", "address", "remark"),
        labels = mapOf(
            "name" to "名称",
            "contact_name" to "联系人",
            "phone" to "电话",
            "address" to "地址",
            "remark" to "备注",
        ),
        actions = listOf(
            update(AiWrites.SUPPLIER_UPDATE),
            delete(AiWrites.SUPPLIER_DELETE),
            paired(
                AiWrites.SUPPLIER_RESTORE,
                AiInverse(AiWrites.SUPPLIER_DELETE, mapOf("supplier_id" to AiRevert.ID)),
                idKey = "target_id",
            ),
        ),
        read = { ds, id -> ds.snapshot("supplier", id) },
        restore = AiInverse(AiWrites.SUPPLIER_RESTORE, mapOf("target_id" to AiRevert.ID)),
    )

    /**
     * 应付单（**欠这个供应商的一笔钱**）。
     *
     * ⚠️ 撤回一张"新建的应付单"= 删掉它（框架的默认路径，不在这张表里声明）；
     * 撤回一次"改动"= 把事由/金额/日期写回旧值。
     * 撤回一次"删除"= `/{id}/restore` 放回来。
     */
    private val SUPPLIER_PAYABLE = AiResource(
        key = "supplier_payable",
        cn = "应付款",
        idKey = "payable_id",
        readKeys = setOf("title", "category", "amount", "doc_date", "remark"),
        labels = mapOf(
            "title" to "这笔账是什么",
            "category" to "用途分类",
            "amount" to "应付总额",
            "doc_date" to "单据日期",
            "remark" to "备注",
        ),
        moneyKeys = setOf("amount"),
        actions = listOf(
            update(AiWrites.SUPPLIER_PAYABLE_UPDATE),
            delete(AiWrites.SUPPLIER_PAYABLE_DELETE),
            paired(
                AiWrites.SUPPLIER_PAYABLE_RESTORE,
                AiInverse(AiWrites.SUPPLIER_PAYABLE_DELETE, mapOf("payable_id" to AiRevert.ID)),
                idKey = "target_id",
            ),
        ),
        read = { ds, id -> ds.snapshot("supplier_payable", id) },
        restore = AiInverse(AiWrites.SUPPLIER_PAYABLE_RESTORE, mapOf("target_id" to AiRevert.ID)),
    )

    /**
     * 一笔付款（就是 `cash_flows` 里 `PAYMENT_SUPPLIER` 的那一行）。
     *
     * ### 只有"撤销 ↔ 恢复"这一对，**付款本身不在这里**
     * 付款（`supplier_payment.pay`）写的是**新的一行流水**，编号在写之前不存在 ——
     * 挂不上"撤回"按钮。它的撤回走另一条已经存在的路：**撤销付款**（`cancel`），
     * 那是"把这笔钱收回来"，卡片上写着这件事（见 `AiWriteSuppliers` 的 blurb）。
     * 这一条与 `SHIPPER_SETTLEMENT` 是同一个形状（撤销/恢复成对，正向不挂撤回）。
     *
     * ### 为什么"撤销付款"的撤回是"恢复"而不是"再付一次"
     * 撤销是**软删那一行流水**（用户定的硬规矩：删除一律软删 + 必须有恢复路径），
     * 所以放回来要走 `/{id}/restore`。⛔ 不许"再付一笔同样的钱" ——
     * 那会写出**第二行**流水，而第一行还躺在回收站里：账上从此有两笔钱，
     * 一笔真的、一笔是假的，谁也不敢删。
     */
    /**
     * 一张采购单（CHG-0074 / 台账 L-42）。
     *
     * ### 为什么只有三个读回键
     * 因为 AI 那条「改采购单」的动作**只改单头三样**（供应商 / 单据日期 / 备注）：
     * 行与钱一律不动。撤回就是把这三次写回旧值，所以快照只需要这三样。
     * ⛔ 数量与进价故意不在这里：后端的换行是**整份替换**语义，改一行等于重写整张单，
     * 而"重写一张已经进过货的单"会连带改库存与成本价 —— 那不是撤回，是另一次建单。
     *
     * ### 为什么 remark 声明成可写回的空值
     * 快照里空备注会写成 JsonNull，而这条 PATCH **收得下空串**（kotlinx 的 explicitNulls = false
     * 只丢 null，空串照发）⇒ 撤回时能把备注清回"没有"。不声明的话，
     * AiRevert.patchPlan 会按"空值写不回去"的老规矩在卡上写一句**假话**。
     */
    private val PURCHASE_ORDER = AiResource(
        key = "purchase_order",
        cn = "采购单",
        idKey = "order_id",
        readKeys = setOf("supplier_id", "doc_date", "remark"),
        labels = mapOf(
            "supplier_id" to "供应商",
            "doc_date" to "单据日期",
            "remark" to "备注",
        ),
        nullableWritable = setOf("remark"),
        actions = listOf(
            update(AiWrites.PURCHASE_ORDERS_UPDATE),
            delete(AiWrites.PURCHASE_ORDERS_DELETE),
            paired(
                AiWrites.PURCHASE_ORDERS_RESTORE,
                AiInverse(AiWrites.PURCHASE_ORDERS_DELETE, mapOf("order_id" to AiRevert.ID)),
                idKey = "target_id",
            ),
        ),
        read = { ds, id -> ds.snapshot("purchase_order", id) },
        restore = AiInverse(AiWrites.PURCHASE_ORDERS_RESTORE, mapOf("target_id" to AiRevert.ID)),
    )
    private val SUPPLIER_PAYMENT = AiResource(
        key = "supplier_payment",
        cn = "付款记录",
        idKey = "payment_id",
        readKeys = setOf("amount", "pay_date", "channel", "remark"),
        labels = mapOf(
            "amount" to "付款金额",
            "pay_date" to "付款日期",
            "channel" to "付款方式",
            "remark" to "备注",
        ),
        moneyKeys = setOf("amount"),
        actions = listOf(
            paired(
                AiWrites.SUPPLIER_PAYMENT_CANCEL,
                AiInverse(
                    AiWrites.SUPPLIER_PAYMENT_RESTORE,
                    mapOf("target_id" to AiRevert.ID),
                    lines = listOf(
                        "把刚撤掉的那一笔付款放回来（后台是伪装删除：流水行还在，逐字段照搬）",
                        "放回来之后「还欠他多少」会重新减掉这一笔，账本「收支」里也重新算上它",
                        "两边一起变，不会出现「欠款说没付、收支说付了」",
                    ),
                ),
                idKey = "flow_id",
            ),
        ),
        // 成对动作的撤回**不需要读现场**（参数只有主键，`AiRevert.plan` 里那道判据会跳过读），
        // 而这一条被撤掉之后本来就躺在回收站里、按常规列表读不到 —— 所以如实返回 null。
        read = { _, _ -> null },
    )

    /**
     * 下游价（2026-10-08 CHG-0084）。
     *
     * 派单员给他的专属价是 [PRICE_RULE]，这本是**他给下游客户**的价 —— 两层价，别混。
     *
     * 只有「删 / 放回来」成对：改价那条（`shipper_price.set`）是 upsert（有就改、没有就建），
     * 写之前不确定该撤到哪一条，所以它**不进本资源**，改走 [AiRevert] 里 UNDO_NONE 的显式文案。
     * 删价那条被撤掉之后，后台是伪装删除（行还在），恢复就是逐字段照搬那一行。
     */
    private val SHIPPER_PRICE = AiResource(
        key = "shipper_price",
        cn = "下游价",
        idKey = "price_id",
        readKeys = setOf("product_id", "contact_id", "unit_price"),
        labels = mapOf(
            "product_id" to "商品",
            "contact_id" to "下游联系人",
            "unit_price" to "单价",
        ),
        moneyKeys = setOf("unit_price"),
        actions = listOf(
            delete(AiWrites.SHIPPER_PRICE_DELETE),
            paired(
                AiWrites.SHIPPER_PRICE_RESTORE,
                AiInverse(AiWrites.SHIPPER_PRICE_DELETE, mapOf("target_id" to AiRevert.ID)),
                idKey = "target_id",
            ),
        ),
        // 成对动作的撤回**不需要读现场**（参数只有主键，`AiRevert.plan` 里那道判据会跳过读），
        // 而这一条被删掉之后给下游定价的名册里就查不到它了 —— 所以如实返回 null。
        read = { _, _ -> null },
        restore = AiInverse(AiWrites.SHIPPER_PRICE_RESTORE, mapOf("target_id" to AiRevert.ID)),
        restoreLines = listOf(
            "把刚才删掉的那一条价放回来（后台是伪装删除：行还在，逐字段照搬）",
            "放回来之后编号、商品、给谁、单价都和删掉之前一模一样",
        ),
    )

    /**
     * 一张发票（2026-10-08 CHG-0086）。
     *
     * ### 为什么只有六个读回键
     * 因为 AI 那条「改发票」的动作**只改这六样**（票号 / 开票日期 / 合计 / 税率 / 税额 / 备注）：
     * 单头这六样就是撤回要写回的全部东西，多读一个键反而会让人以为它也能撤。
     * ⛔ 方向、对方（供应商 / 客户）、挂的采购单**故意不在这里**：那几样在库里是
     * 结构和归属（改方向等于换一张票），AI 那条改票动作根本递不上去 ⇒ 也不该假装能撤回。
     *
     * ### 为什么 invoice_no 与 note 声明成可写回的空值
     * 这张票的票号**允许为空**（月结代开：先登记、后补号）。后端的 PATCH 对空号是
     * 明确收下的（tax_service.py 里空号 = 把号清掉、重新变成"待补号"），备注同理
     * （空串 = 清空备注）⇒ 撤回时能把票号 / 备注清回"没有"。
     * 不声明的话，AiRevert.patchPlan 会按"空值写不回去"的老规矩在卡上写一句**假话**。
     *
     * ### 为什么 tax_rate / tax_amount 空着写 JsonNull、却**不**声明可写回
     * 在后端，显式传 null 确实能把税率清掉——但 App 这条路（InvoiceUpdateRequest
     * 的 explicitNulls = false）**发不出显式 null**，只能"不提这一项"。所以撤回一张
     * **未税票**时，卡上那句「这一项原来就是空的，而这个接口清不掉它」是实话。
     *
     * ### 新建 / 开具 / 作废为什么不在这里
     * 新建那张票在写之前**根本没有编号**（撤不了），开具与作废**没有逆操作**
     * （票一直留在台账里、占着号）——三条都在 [AiRevert] 的 UNDO_NONE 里逐条写明后果。
     *
     * ### 软删与恢复
     * 删除是伪装删除（票行还在），恢复就是逐字段照搬那一行 ⇒ 用默认那两句文案即可。
     */
    private val INVOICE = AiResource(
        key = "invoice",
        cn = "发票",
        idKey = "invoice_id",
        readKeys = setOf("invoice_no", "invoice_date", "amount", "tax_rate", "tax_amount", "note"),
        labels = mapOf(
            "invoice_no" to "票号",
            "invoice_date" to "开票日期",
            "amount" to "价税合计",
            "tax_rate" to "税率",
            "tax_amount" to "税额",
            "note" to "备注",
        ),
        moneyKeys = setOf("amount", "tax_amount", "tax_rate"),
        nullableWritable = setOf("invoice_no", "note"),
        actions = listOf(
            update(AiWrites.INVOICES_UPDATE),
            delete(AiWrites.INVOICES_DELETE),
            paired(
                AiWrites.INVOICES_RESTORE,
                AiInverse(AiWrites.INVOICES_DELETE, mapOf("invoice_id" to AiRevert.ID)),
                idKey = "target_id",
            ),
        ),
        read = { ds, id -> ds.snapshot("invoice", id) },
        restore = AiInverse(AiWrites.INVOICES_RESTORE, mapOf("target_id" to AiRevert.ID)),
        // 默认那两句说的是"恢复之后编号、图片、坐标、备注都和删掉之前一模一样"——
        // 票没有图片也没有坐标，照搬上去就是没说人话，所以换成这张表自己的两句（六样字段全在）。
        restoreLines = listOf(
            "把刚才撤掉的那张票放回来（后台是伪装删除：票那一行还在，逐字段照搬）",
            "放回来之后票号、开票日期、价税合计、税率、税额、备注都和撤掉之前一模一样",
        ),
    )
    /** 全部资源。红线与单测按它逐个核对（键是否齐全、动作是否都有归属）。 */
    val TABLE: List<AiResource> = listOf(
        ADDRESS, LOCATION, CONTACT, ARREARS_UNIT, UNIT_CONVERSION, FREIGHT_TEMPLATE, DRIVER_RULE,
        PRODUCT, PRICE_RULE, PRODUCT_CATEGORY, PLACE_CATEGORY, CONTACT_CATEGORY, ROUTE_CATEGORY, VEHICLE, PRODUCT_VISIBILITY, USER,
        PLACE,
        ORDER, ORDER_LINE, LEDGER_ENTRY, NOTIFICATION,
        SHIPPER_SETTLEMENT,
        ORDER_TEMPLATE,
        // 供应商 / 厂商 + 应付款 + 付款（2026-09-22）
        SUPPLIER, SUPPLIER_PAYABLE, SUPPLIER_PAYMENT, PURCHASE_ORDER,
        // 另外三张配置名册（2026-09-23：AI 能建/改名/排序/删，所以撤回也要有归属）
        EXPENSE_CATEGORY, FREIGHT_CATEGORY, ORDER_TEMPLATE_CATEGORY,
        // 两张**全店**名册（2026-10-05 FEAT-0010：账号分类 / 车辆分类）
        USER_CATEGORY, VEHICLE_CATEGORY,
        // 下游价（2026-10-08 CHG-0084）：只有「删 / 放回来」成对，改价那条走 UNDO_NONE
        SHIPPER_PRICE,
        // 发票台账（2026-10-08 CHG-0086）：改 / 删 / 恢复三条挂在这，建·开具·作废走 UNDO_NONE
        INVOICE,
    )
}

/**
 * 「写之前的现场」怎么从后端读回来的对象里取出来。
 *
 * ### 为什么单独一份纯函数
 * 因为它必须能**在 JVM 单测里跑**：安卓运行时拉不起来，而"快照的键是不是覆盖了
 * 各动作会写的键"这件事**必须被机器核对**——漏一个键的表现是"撤回时那一项静默不变"，
 * 是这一整块功能里最难被发现的一种错。DTO 是纯 kotlinx-serialization 数据类，
 * 所以这些函数不碰安卓，单测直接喂一个构造出来的 DTO 就能断言键的集合。
 *
 * ### 键名一律是 **payload 键名**
 * 不是 DTO 字段名（`defaultUnitPrice` → `default_unit_price`；
 * `productNameSnapshot` → 订单行有两套 payload 键 `product` 和 `product_name`）。
 */
internal object AiRevertRead {

    /**
     * 写一个可空的文本字段。
     *
     * ⚠️ 不能写成 `put(k, v ?: JsonNull)`：那样表达式的类型会退化成 `Any`
     * （String 和 JsonNull 的公共父类），而 `buildJsonObject` 没有接受 `Any` 的重载
     * ——编译期就报 "actual type is 'Any', but 'JsonElement' was expected"。
     * **`null` 在快照里要留一个位置**："这一项原来是空的"和"读不到这一项"不一样，
     * 前者撤回时只能如实说"这个接口清不掉它"，后者是"这次撤回不会带上它"。
     */
    private fun kotlinx.serialization.json.JsonObjectBuilder.text(k: String, v: String?) {
        put(k, v?.let { JsonPrimitive(it) } ?: JsonNull)
    }

    fun address(d: AddressDto): JsonObject = buildJsonObject {
        put("receiver_name", d.receiverName)
        put("phone", d.phone)
        put("detail_address", d.detailAddress)
        text("origin_address", d.originAddress)
        put("remark", d.remark)
        text(GEO_LAT, d.addressLat)
        text(GEO_LNG, d.addressLng)
    }

    fun location(d: LocationDto): JsonObject = buildJsonObject {
        put("name", d.name)
        put("detail_address", d.detailAddress)
        put("remark", d.remark)
        // 地点绑定的收货联系人（2026-09-24）：进快照，撤回时才能把旧值写回去
        put("contact_name", d.contactName)
        put("contact_phone", d.contactPhone)
        text(GEO_LAT, d.addressLat)
        text(GEO_LNG, d.addressLng)
    }

    fun contact(d: ContactDto): JsonObject = buildJsonObject {
        put("display_name", d.displayName)
        put("phone", d.phone)
    }

    /**
     * 共享地点（全库共用那张表）的可撤回字段。
     *
     * ⚠️ **只有名字和地址**：坐标不进 payload 是有意的 —— 撤回是把这份快照**原样写回**，
     * 而"改共享地点"这个动作本身就不接受坐标（见 `AiWrite.kt` 里那一组动作的注释）。
     * 把坐标读进来只会让撤回卡上多出两行用户改不动、也看不懂的数。
     */
    fun place(d: PlaceDto): JsonObject = buildJsonObject {
        put("name", d.name)
        put("detail_address", d.detailAddress)
    }

    fun arrearsUnit(d: ArrearsUnitDto): JsonObject = buildJsonObject {
        put("name", d.name)
        put("phone", d.phone)
        put("remark", d.remark)
        // 额度（2026-10-08 CHG-0087）：撤回「设额度」要把这一个键写回旧值。
        // ⚠️ null 必须**留一个位置**（JsonNull = 不限额，不是"没读这一项"）：只有 JsonNull
        // 才会让撤回走 `nullableWritable` 那条路，把额度真的清回"不限额"。
        text("credit_limit", d.creditLimit)
    }

    /**
     * 单位换算的可撤回字段（2026-09-24：一车 = 8 方）。
     *
     * ⚠️ 四个键**一个都不能少**，而且键名必须是 payload 键（不是 DTO 的驼峰名）：
     * 撤回是"把这份快照原样写回同一条写路径"，键名写错的表现是**撤回卡点了没反应**
     * （`updateUnitConversion` 里 `fields.str("from_unit")` 取到 null = 不改这一项）。
     */
    fun unitConversion(d: UnitConversionDto): JsonObject = buildJsonObject {
        put("from_unit", d.fromUnit)
        put("to_unit", d.toUnit)
        put("factor", d.factor)
        put("remark", d.remark)
    }

    fun freightTemplate(d: FreightTemplateDto): JsonObject = buildJsonObject {
        put("from_place", d.fromPlace)
        put("to_place", d.toPlace)
        put("fee", d.fee)
        put("remark", d.remark)
    }

    /**
     * 预设单的现场（2026-09-22）。
     *
     * ⚠️ 两个"空值"要小心处理：
     * · **货主为空时不写这个键** —— 撤回是"把旧值塞回同一条写路径"，而 `explicitNulls=false`
     *   会把 null 丢掉；写一个空键反而会让撤回什么都没做。
     *   （"原本就没货主"与"改完变成没货主"两种情况都不需要写回：前者不用改，后者由界面上那次
     *    编辑直接完成，撤回要还原的是**改之前**那一份。）
     * · **运费为空时同样不写** —— 同一条理由；空值在更新请求里发不出去。
     */
    fun orderTemplate(d: OrderTemplateDto): JsonObject = buildJsonObject {
        put("name", d.name)
        d.shipperId?.let { put("shipper_id", it) }
        put("address", d.address)
        d.freightFee?.let { put("freight_fee", it) }
        put("remark", d.remark)
    }

    /**
     * 供应商档案的现场（2026-09-22）。
     *
     * 五个键全是**可写回**的（后端 PATCH 收得下空串），所以不需要 `nullableWritable`
     * 那种申明 —— "原来就是空的"与"改成空的"都写空串，语义一致。
     */
    fun supplier(d: SupplierDto): JsonObject = buildJsonObject {
        put("name", d.name)
        put("contact_name", d.contactName)
        put("phone", d.phone)
        put("address", d.address)
        put("remark", d.remark)
    }

    /**
     * 应付单的现场。
     *
     * ⚠️ `amount` 写回的是**应付总额**（不是"还差"）：撤回一次"改金额"要还原的是
     * 改之前那个总额。而"还差多少"是算出来的、不是存下来的，写回去也没有意义。
     * ⚠️ 后端会拦住"金额改到比已付还小"：真出现这种情况，撤回那一步会如实报错
     * （而不是静默改成一个错的数）。
     */
    /**
     * 一张采购单的**单头三样**（撤回就写回这三样）。
     *
     * ⚠️ 空备注写成 JsonNull 而不是空串：资源上声明了 nullableWritable = setOf("remark")，
     *    于是 AiRevert.patchPlan 会把"原来的备注是空的"当成**能清回去**（这条 PATCH 收得下空串），
     *    而不是按老规矩在撤回卡上写一句"写不回空值"的假话。
     */
    fun purchaseOrder(d: PurchaseOrderDto): JsonObject = buildJsonObject {
        put("supplier_id", d.supplierId)
        put("doc_date", d.docDate)
        put("remark", if (d.remark.isBlank()) JsonNull else JsonPrimitive(d.remark))
    }

    /**
     * 一张发票的**六样可改字段**（撤回就写回这六样，键名与 payload 一一对应）。
     *
     * ⚠️ 空票号与空备注都写成 JsonNull 而不是空串：资源上声明了
     *    nullableWritable = setOf("invoice_no", "note")，于是 AiRevert.patchPlan 会把
     *    "原来就没有票号 / 备注"当成**能清回去**（这条 PATCH 收得下空号与空串），
     *    而不是按老规矩在撤回卡上写一句"写不回空值"的假话。
     * ⚠️ 税率 / 税额空着也写 JsonNull，但资源**没有**把它们声明成可写回——
     *    后端的 InvoiceUpdate 收得下显式 null，而 App 这条路发不出显式 null。
     */
    fun invoice(d: InvoiceDto): JsonObject = buildJsonObject {
        put("invoice_no", if (d.invoiceNo.isBlank()) JsonNull else JsonPrimitive(d.invoiceNo))
        put("invoice_date", d.invoiceDate)
        put("amount", d.amount)
        put("tax_rate", d.taxRate?.let { JsonPrimitive(it) } ?: JsonNull)
        put("tax_amount", d.taxAmount?.let { JsonPrimitive(it) } ?: JsonNull)
        put("note", if (d.note.isBlank()) JsonNull else JsonPrimitive(d.note))
    }

    fun supplierPayable(d: SupplierPayableDto): JsonObject = buildJsonObject {
        put("title", d.title)
        put("category", d.category)
        put("amount", d.amount)
        put("doc_date", d.docDate)
        put("remark", d.remark)
    }

    /**
     * 一笔付款的现场。
     *
     * ⚠️ 这三个键**只用于展示**：付款记录的撤回是**成对动作**（撤销 ↔ 恢复），
     * 参数只有主键，`AiRevert.plan` 会跳过"读现场"那一步（见 `SUPPLIER_PAYMENT` 的说明）。
     * 那为什么还要有它？因为**红线会逐个资源对账**："这条资源有没有读法" ——
     * 没有读法的资源在撤回链第二步会退化成"撤不回来"，所以它必须真的读得回来。
     */
    fun supplierPayment(d: SupplierPaymentDto): JsonObject = buildJsonObject {
        put("amount", d.amount)
        put("pay_date", d.payDate)
        put("channel", d.channel)
        put("remark", d.remark)
    }

    fun driverRule(d: DriverBillingRuleDto): JsonObject = buildJsonObject {
        put("name", d.name)
        put("salary", d.salary)
        put("piece_amount", d.pieceAmount)
        put("piece_unit", d.pieceUnit)
        put("commission_base", d.commissionBase)
        put("commission_rate", d.commissionRate)
        // ⚠️ 名单字段的形状必须和**写**的时候一样（写法是"名字、名字"）：
        //    撤回是把这里的值原样写回 payload，给编号列表的话会当成商品名去匹配 → 查不到 → 撤回失败。
        //    空范围就是空串，而 `resolveProductIds("")` 的语义正好是"取消范围"。
        put("commission_products", d.commissionProductNames.joinToString("、"))
        put("remark", d.remark)
    }

    fun product(d: ProductDto): JsonObject = buildJsonObject {
        put("name", d.name)
        put("default_unit_price", d.defaultUnitPrice)
        put("unit", d.unit)
        put("low_stock_alert", JsonPrimitive(d.lowStockAlert))
        // 动作里这个键叫 `active`（模型给的参数名），后端字段是 is_active
        put("active", JsonPrimitive(d.isActive))
    }

    fun priceRule(d: PriceRuleDto): JsonObject = buildJsonObject {
        put("shipper_id", JsonPrimitive(d.shipperId))
        put("product_id", JsonPrimitive(d.productId))
        put("special_unit_price", d.specialUnitPrice)
    }

    /**
     * 商品分类名册里的一格。
     *
     * ⚠️ `sort_order` 这里是**从 1 数**的位置，不是后端的 `sort_order` 列值——
     * 「撤回」是把这份快照里的值**原样写回 payload**，而 payload 里那个键的口径
     * 就是"排在第几位"（`- 1` 的换算在数据源那一层做一次）。
     * 两边口径不一致的话，撤回会把这一类排到差一位的地方，而且不会报错。
     */
    fun productCategory(d: ProductCategoryDto): JsonObject = buildJsonObject {
        put("name", d.name)
        put("sort_order", JsonPrimitive(d.sortOrder + 1))
    }

    /** 地点分组（与商品分类**同一个口径**：卡片上的"第几位"从 1 数，进 payload 的 `sort_order` 从 0 数）。 */
    fun placeCategory(d: com.tapmoay.sorders.data.remote.dto.PlaceCategoryDto): JsonObject = buildJsonObject {
        put("name", d.name)
        put("sort_order", JsonPrimitive(d.sortOrder + 1))
    }

    /** 联系人分类（与地点分组**同一个口径**：卡片上的"第几位"从 1 数，进 payload 的 `sort_order` 从 0 数）。 */
    fun contactCategory(d: ContactCategoryDto): JsonObject = buildJsonObject {
        put("name", d.name)
        put("sort_order", JsonPrimitive(d.sortOrder + 1))
    }

    /** 线路分类（与地点分组 / 联系人分类**同一个口径**：卡片上的"第几位"从 1 数，进 payload 的 `sort_order` 从 0 数）。 */
    fun routeCategory(d: RouteCategoryDto): JsonObject = buildJsonObject {
        put("name", d.name)
        put("sort_order", JsonPrimitive(d.sortOrder + 1))
    }

    /** 账号分类（与上面几张**同一个口径**：卡片上的"第几位"从 1 数，进 payload 的 `sort_order` 从 0 数）。 */
    fun userCategory(d: com.tapmoay.sorders.data.remote.dto.UserCategoryDto): JsonObject = buildJsonObject {
        put("name", d.name)
        put("sort_order", JsonPrimitive(d.sortOrder + 1))
    }

    /** 车辆分类（同口径）。 */
    fun vehicleCategory(d: com.tapmoay.sorders.data.remote.dto.VehicleCategoryDto): JsonObject = buildJsonObject {
        put("name", d.name)
        put("sort_order", JsonPrimitive(d.sortOrder + 1))
    }

    /**
     * 开销分类（另外三张配置名册之一，2026-09-23）。
     *
     * ⚠️ 这里多一个 `link_kind`：它是这个分类**唯一**的"非名字"属性（卡片上突出显示哪一项），
     * 撤回时要一起写回去 —— 漏了它，撤回之后的分类名字对了、突出项却留在改后的样子，
     * 而那种差异在名册页上要逐行点开才看得出来。
     */
    fun expenseCategory(d: com.tapmoay.sorders.data.remote.dto.ExpenseCategoryDto): JsonObject =
        buildJsonObject {
            put("name", d.name)
            put("sort_order", JsonPrimitive(d.sortOrder + 1))
            put("link_kind", d.linkKind)
        }

    /** 运费分类（同一口径：卡片"第几位"从 1 数）。 */
    fun freightCategory(d: com.tapmoay.sorders.data.remote.dto.FreightCategoryDto): JsonObject =
        buildJsonObject {
            put("name", d.name)
            put("sort_order", JsonPrimitive(d.sortOrder + 1))
        }

    /** 预订单分类（同一口径）。 */
    fun orderTemplateCategory(
        d: com.tapmoay.sorders.data.remote.dto.OrderTemplateCategoryDto,
    ): JsonObject = buildJsonObject {
        put("name", d.name)
        put("sort_order", JsonPrimitive(d.sortOrder + 1))
    }

    fun vehicle(d: VehicleDto): JsonObject = buildJsonObject {
        put("plate_no", d.plateNo)
        put("vehicle_type", d.vehicleType)
        // 没绑司机时是 JsonNull（**不是**省略）：撤回时它会变成一行
        // "这一项原来就是空的，而这个接口清不掉它"——如实说，而不是假装写回去了。
        put("driver_id", d.driverId?.let { JsonPrimitive(it) } ?: JsonNull)
        put("active", JsonPrimitive(d.isActive))
    }

    // 五个键一次写全：撤回拿这份快照**整份写回**，少一个键就是撤回时把那一维清空
    // （分类那一维尤其致命：授权项没了，那个货主的选品页会凭空少一批商品）。
    fun productVisibility(d: ProductVisibilityDto): JsonObject = buildJsonObject {
        put("scope", d.scope)
        put("product_ids", JsonArray(d.productIds.map { JsonPrimitive(it) }))
        put("category_names", JsonArray(d.categoryNames.map { JsonPrimitive(it) }))
        put("hidden_product_ids", JsonArray(d.hiddenProductIds.map { JsonPrimitive(it) }))
        put("hidden_category_names", JsonArray(d.hiddenCategoryNames.map { JsonPrimitive(it) }))
    }

    fun user(d: UserDto): JsonObject = buildJsonObject {
        put("full_name", d.fullName)
        put("phone", d.phone)
        put("active", JsonPrimitive(d.isActive))
        put("member", JsonPrimitive(d.isMember))
        text("billing_mode", d.billingMode)
        text("vehicle_type", d.vehicleType)
        text("salary", d.salary)
    }

    fun order(d: OrderDto): JsonObject = buildJsonObject {
        text("freight_fee", d.freightFee)
        put("delivery_description", d.deliveryDescription)
        put("address_detail", d.addressDetail)
        put("contact_dongjia_phone", d.contactDongjiaPhone)
        put("contact_boss_phone", d.contactBossPhone)
        put("contact_dongjia_name", d.contactDongjiaName)
        put("contact_boss_name", d.contactBossName)
        put("remark", d.remark)
        put("internal_notes", d.internalNotes)
        // ⚠️ 同一个字段在 assign 里叫 internal_note（另一套键名，见这个文件的说明）
        put("internal_note", d.internalNotes)
        put("driver_id", d.driverId?.let { JsonPrimitive(it) } ?: JsonNull)
        put("collect_cash", JsonPrimitive(d.collectCash))
        text("driver_piece_amount", d.driverPieceAmount)
        text("driver_commission_rate", d.driverCommissionRate)
        put("reason", d.exceptionReason)
        text("expected_before", d.expectedDeliverBefore)
        text(GEO_LAT, d.addressLat)
        text(GEO_LNG, d.addressLng)
        // 让价四键（2026-10-08 CHG-0087）：**只给「取消让价」的撤回用**——它要把取消之前
        // 那一套让价整份打回去（方式/数值/范围/理由），而按"撤回＝写回旧值"的通用规则，
        // 旧值只能从这里来。
        // 范围按 AiWriteMoney 的 payload 口径写成 "全部" 或 "12,15"：那一头
        // `discountLineIdsOf` 不认别的写法，而且**缺席就报错**（宁可让用户重说一遍，
        // 也不把范围悄悄放大成整单）。空集 = 老数据没有逐行快照 ⇒ 整单，
        // 与 `discountLineIds` 的说明、后端 `plan_discount` 的退路一致。
        text("discount_kind", d.discountKind)
        text("discount_value", d.discountValue)
        put(
            "discount_line_ids",
            JsonPrimitive(discountLineIds(d).let { if (it.isEmpty()) "全部" else it.sorted().joinToString(",") }),
        )
        text("discount_reason", d.discountReason)
    }

    fun orderLine(d: OrderProductRow): JsonObject = buildJsonObject {
        put("order_id", JsonPrimitive(d.orderId))
        put("product", d.productNameSnapshot)
        put("product_name", d.productNameSnapshot)
        put("quantity", JsonPrimitive(d.quantity))
        put("unit_price", d.unitPrice)
    }

    fun ledgerEntry(d: LedgerEntryDto): JsonObject = buildJsonObject {
        put("total", d.total)
        put("quantity", JsonPrimitive(d.quantity))
        put("unit_price", d.unitPrice)
        put("entry_date", d.entryDate)
        put("product_name", d.productName)
        put("note", d.note)
    }

    fun notification(d: NotificationDto): JsonObject = buildJsonObject {
        put("title", d.title)
        put("content", d.content)
    }

}
