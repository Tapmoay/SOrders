package com.tapmoay.sorders.ai

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull

/**
 * 基础资料动作：地址与联系人、地点、挂账单位、运费模板、车辆、客户。
 *
 * 这一批几乎全是标准 CRUD，所以整批走声明式（[CrudSpec]/[CrudWriteHandler]），
 * 动作定义里只剩"查谁 / 收什么 / 摘要怎么写 / 调哪个接口"。
 *
 * ### 档位为什么普遍是 MEDIUM
 * 它们改的是**主数据**（谁、在哪、多少钱起送），不是某一张单的结果：
 * - 不产生业务流水，也不推送通知给别人；
 * - 唯一会立刻生效的地方是**下一次下单/派单时**，而那之前用户有机会发现；
 * - 都改得回来。
 *
 * 例外：**删除类**统一是 MEDIUM 而不是更低——删掉一条地址之后，
 * 正在用它的订单不受影响（快照），但用户下次下单就选不到了，需要他自己知道这件事。
 * 卡片上会写明这一点。
 */
internal object AiWriteBasicData {

    val ALL: List<AiWriteAction> = listOf(

        // ------------------------------------------------------ 地址 / 线路
        crud(
            id = AiWrites.ADDRESS_CREATE,
            title = "新增地址/线路",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_ADDRESS,
            blurb = "新增一条常用地址（收货人 + 终点地址）。下单时可以直接选它，不用再手打。",
            fields = listOf(
                textField("receiver", "收货人", "必填，如「张三」", required = true, maxChars = 32)
                    .copy(key = "receiver_name"),
                textField("phone", "电话", "收货人电话", maxChars = 20),
                textField("address", "终点地址", "必填，如「XX 路 65 号」", required = true, maxChars = 200)
                    .copy(key = "detail_address"),
                textField("origin", "起点地址", "可选。这是一条线路时才有起点", maxChars = 200)
                    .copy(key = "origin_address"),
                AiFieldSpec("default", "设为默认", AiFieldType.BOOL, "true=以后下单默认选这条"),
                textField("remark", "备注", "可选", maxChars = 200),
            ),
            headline = { c -> "新增地址：${c.str("receiver_name")} ${c.str("detail_address")}" },
            details = { c ->
                listOfNotNull(
                    "收货人：${c.str("receiver_name")}",
                    c.str("phone")?.let { "电话：$it" },
                    "终点：${c.str("detail_address")}",
                    c.str("origin_address")?.let { "起点：$it" },
                    if (c.bool("default") == true) "设为默认地址" else null,
                    c.str("remark")?.let { "备注：$it" },
                )
            },
            geocodeFrom = "detail_address",
        ) { ds, p -> ds.createAddress(p) },

        crud(
            id = AiWrites.ADDRESS_UPDATE,
            title = "改地址/线路",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_ADDRESS,
            blurb = "改一条已有地址。**只填要改的那几项。**",
            targets = listOf(targetAddress()),
            fields = listOf(
                textField("receiver", "新收货人", "不改就不填", maxChars = 32).copy(key = "receiver_name"),
                textField("phone", "新电话", "不改就不填", maxChars = 20),
                // ⚠️ 参数名**不能叫 `address`**：那是目标参数的键（"用哪条地址去搜"）。
                // 撞名之后目标解析和字段校验会读同一个键 → **拿搜索词当新地址写进去**。
                // 这个 bug 是单测抓到的（见 AiWriteTest.改地址只发改的那几项）。
                textField("detail", "新终点地址", "不改就不填", maxChars = 200).copy(key = "detail_address"),
                textField("origin", "新起点地址", "不改就不填", maxChars = 200).copy(key = "origin_address"),
                textField("remark", "新备注", "不改就不填", maxChars = 200),
            ),
            headline = { c -> "改地址：${c.ref("address")?.label}" },
            details = { c ->
                listOfNotNull(
                    c.line("receiver_name", "收货人改成"),
                    c.line("phone", "电话改成"),
                    c.line("detail_address", "终点改成"),
                    c.line("origin_address", "起点改成"),
                    c.line("remark", "备注改成"),
                )
            },
            geocodeFrom = "detail_address",
            // 改地址：定位不到就拒绝。PATCH 传 null 清不掉旧坐标，留着会把司机带去**旧地址**
            geocodeRequired = true,
        ) { ds, p ->
            ds.updateAddress(p.reqLong("address_id"), p.pick(ADDRESS_KEYS))
        },

        crud(
            id = AiWrites.ADDRESS_DELETE,
            title = "删除地址",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_ADDRESS,
            blurb = "删掉一条常用地址。**已经用它下过的单不受影响**，但以后下单选不到它了。"
                + "（删错了可以撤回，见卡片最后一行）",
            targets = listOf(targetAddress()),
            headline = { c -> "删除地址：${c.ref("address")?.label}" },
            details = {
                listOf(
                    "地址：${it.ref("address")?.label}",
                    "已经用这条地址下过的单不受影响（单上有快照）",
                    "但以后下单时就选不到它了",
                )
            },
        ) { ds, p -> ds.deleteAddress(p.reqLong("address_id")) },

        crud(
            id = AiWrites.ADDRESS_SET_DEFAULT,
            title = "设为默认地址",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_ADDRESS,
            blurb = "把某条地址设成默认。以后下单时**默认选中的就是它**。",
            targets = listOf(targetAddress()),
            headline = { c -> "设为默认地址：${c.ref("address")?.label}" },
            details = {
                listOf(
                    "地址：${it.ref("address")?.label}",
                    "以后下单会默认选中这一条",
                    "原来的默认地址会被取消（地址不会被删）",
                )
            },
        ) { ds, p -> ds.setDefaultAddress(p.reqLong("address_id")) },

        // ---------------------------------------------------------- 联系人
        crud(
            id = AiWrites.CONTACT_UPSERT,
            title = "记一个联系人",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_ADDRESS,
            blurb = "按手机号记一个联系人。**同一个手机号已经有了就更新他的名字**，不会重复。",
            fields = listOf(
                textField("phone", "手机号", "必填", required = true, maxChars = 20),
                textField("name", "姓名", "必填，如「张三」", required = true, maxChars = 32)
                    .copy(key = "display_name"),
            ),
            headline = { c -> "记联系人：${c.str("display_name")} ${c.str("phone")}" },
            details = { c ->
                listOf(
                    "姓名：${c.str("display_name")}",
                    "手机号：${c.str("phone")}",
                    "同一个手机号已经有了的话，这条会更新他原来的名字而不是新增一条",
                )
            },
        ) { ds, p -> ds.createContact(p) },

        crud(
            id = AiWrites.CONTACT_UPDATE,
            title = "改联系人",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_ADDRESS,
            blurb = "改一个联系人的姓名或手机号。",
            targets = listOf(targetContact()),
            fields = listOf(
                textField("name", "新姓名", "不改就不填", maxChars = 32).copy(key = "display_name"),
                textField("phone", "新手机号", "改成别人用过的手机号会报错（联系人不能重号）", maxChars = 20),
            ),
            headline = { c -> "改联系人：${c.ref("contact")?.label}" },
            details = { c -> listOfNotNull(c.line("display_name", "姓名改成"), c.line("phone", "手机号改成")) },
        ) { ds, p ->
            ds.updateContact(p.reqLong("contact_id"), p.pick(CONTACT_KEYS))
        },

        crud(
            id = AiWrites.CONTACT_DELETE,
            title = "删除联系人",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_ADDRESS,
            blurb = "删掉一个常用联系人。"
                + "（删错了可以撤回）",
            targets = listOf(targetContact()),
            headline = { c -> "删除联系人：${c.ref("contact")?.label}" },
            details = { listOf("联系人：${it.ref("contact")?.label}", "已下过的单不受影响") },
        ) { ds, p -> ds.deleteContact(p.reqLong("contact_id")) },

        // ------------------------------------------------------------ 地点
        crud(
            id = AiWrites.LOCATION_CREATE,
            title = "新增地点",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_ADDRESS,
            blurb = "新增一个地点（纯地址，不含人）。地点可以自由组合成线路的起点/终点。",
            fields = listOf(
                textField("name", "地点名", "必填，如「东仓库」", required = true, maxChars = 64),
                textField("address", "详细地址", "必填", required = true, maxChars = 200)
                    .copy(key = "detail_address"),
                textField("remark", "备注", "可选", maxChars = 200),
            ),
            headline = { c -> "新增地点：${c.str("name")}" },
            details = { c ->
                listOf("地点名：${c.str("name")}", "地址：${c.str("detail_address")}") +
                    listOfNotNull(c.str("remark")?.let { "备注：$it" })
            },
            geocodeFrom = "detail_address",
        ) { ds, p -> ds.createLocation(p) },

        crud(
            id = AiWrites.LOCATION_UPDATE,
            title = "改地点",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_ADDRESS,
            blurb = "改一个地点的名字或地址。",
            targets = listOf(targetLocation()),
            fields = listOf(
                textField("name", "新地点名", "不改就不填", maxChars = 64),
                textField("address", "新地址", "不改就不填", maxChars = 200).copy(key = "detail_address"),
                textField("remark", "新备注", "不改就不填", maxChars = 200),
                // 「把这个地点归到那一类」（用户 2026-09-19 点名的例子）。
                // ⚠️ 名字必须**已经在自己那一份分组名册里**（先读 place_categories.list_categories）——
                //    对不上会被拒绝并给出候选，**不会**顺手新建一个（那样一个错别字就多出一格分组）。
                //    要新建分组：先 place_category.create，再回来归。
                textField(
                    "category", "归到哪个分组",
                    "不改就不填。必须是你**已有**的分组名之一；要建新分组请先 place_category.create",
                    maxChars = 32,
                ),
            ),
            headline = { c -> "改地点：${c.ref("location")?.label}" },
            details = { c ->
                listOfNotNull(
                    c.line("name", "地点名改成"),
                    c.line("detail_address", "地址改成"),
                    c.line("remark", "备注改成"),
                    c.line("category", "归到分组"),
                )
            },
            geocodeFrom = "detail_address",
            geocodeRequired = true,
        ) { ds, p ->
            ds.updateLocation(p.reqLong("location_id"), p.pick(LOCATION_KEYS))
        },

        crud(
            id = AiWrites.LOCATION_DELETE,
            title = "删除地点",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_ADDRESS,
            blurb = "删掉一个地点。**已经把它当起点/终点的线路不受影响**（线路上是快照）。"
                + "（删错了可以撤回）",
            targets = listOf(targetLocation()),
            headline = { c -> "删除地点：${c.ref("location")?.label}" },
            details = {
                listOf(
                    "地点：${it.ref("location")?.label}",
                    "已经用它拼好的线路不受影响",
                    "以后拼线路时选不到它了",
                )
            },
        ) { ds, p -> ds.deleteLocation(p.reqLong("location_id")) },

        // -------------------------------------------------------- 挂账单位
        crud(
            id = AiWrites.ARREARS_UNIT_CREATE,
            title = "新增挂账单位",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_LEDGER,
            blurb = "新增一个挂账单位（可以先把货款挂在他名下、以后再结）。",
            fields = listOf(
                textField("name", "单位名", "必填", required = true, maxChars = 128),
                textField("phone", "电话", "可选", maxChars = 20),
                textField("remark", "备注", "可选", maxChars = 200),
            ),
            headline = { c -> "新增挂账单位：${c.str("name")}" },
            details = { c ->
                listOf("单位名：${c.str("name")}") +
                    listOfNotNull(c.str("phone")?.let { "电话：$it" }, c.str("remark")?.let { "备注：$it" })
            },
        ) { ds, p -> ds.createArrearsUnit(p) },

        crud(
            id = AiWrites.ARREARS_UNIT_UPDATE,
            title = "改挂账单位",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_LEDGER,
            blurb = "改挂账单位的名称、电话或备注。",
            targets = listOf(targetArrearsUnit()),
            fields = listOf(
                textField("name", "新单位名", "不改就不填", maxChars = 128),
                textField("phone", "新电话", "不改就不填", maxChars = 20),
                textField("remark", "新备注", "不改就不填", maxChars = 200),
            ),
            headline = { c -> "改挂账单位：${c.ref("unit")?.label}" },
            details = { c -> listOfNotNull(c.line("name", "单位名改成"), c.line("phone", "电话改成"), c.line("remark", "备注改成")) },
        ) { ds, p ->
            ds.updateArrearsUnit(p.reqLong("unit_id"), p.pick(UNIT_KEYS))
        },

        crud(
            id = AiWrites.ARREARS_UNIT_DELETE,
            title = "删除挂账单位",
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_LEDGER,
            blurb = "删掉一个挂账单位。已经挂在他名下的欠款会失去归属——先确认没有未结清的账。"
                + "（删错了可以撤回）",
            targets = listOf(targetArrearsUnit()),
            headline = { c -> "删除挂账单位：${c.ref("unit")?.label}" },
            details = {
                listOf(
                    "单位：${it.ref("unit")?.label}",
                    "已经挂在他名下的欠款会失去归属——先确认没有未结清的账再删",
                    "删掉之后撤不回来",
                )
            },
        ) { ds, p -> ds.deleteArrearsUnit(p.reqLong("unit_id")) },

        // -------------------------------------------------------- 运费模板
        crud(
            id = AiWrites.FREIGHT_TEMPLATE_CREATE,
            title = "新增运费模板",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_ORDER,
            blurb = "新增一条运费参考价（起点→终点 / 车型 / 价格），派单时用来填司机运费。",
            fields = listOf(
                textField("name", "模板名", "必填，如「市区→城东」", required = true, maxChars = 64),
                textField("from", "起点", "可选", maxChars = 64).copy(key = "from_place"),
                textField("to", "终点", "可选", maxChars = 64).copy(key = "to_place"),
                enumField(
                    "vehicle", "车型", "可选",
                    listOf("small", "large", "trailer"),
                    aliases = mapOf("小货" to "small", "小货车" to "small", "大货" to "large", "大货车" to "large", "挂车" to "trailer"),
                    key = "vehicle_type",
                ).copy(required = false),
                moneyField("fee", "运费（元）", "必填，只传数字", required = true),
                textField("remark", "备注", "可选", maxChars = 200),
            ),
            headline = { c -> "新增运费模板：${c.str("name")}" },
            details = { c ->
                listOfNotNull(
                    c.line("from_place", "起点"),
                    c.line("to_place", "终点"),
                    c.str("vehicle_type")?.let { "车型：${vehicleCn(it)}" },
                    "运费：${c.str("fee")} 元",
                )
            },
        ) { ds, p -> ds.createFreightTemplate(p) },

        crud(
            id = AiWrites.FREIGHT_TEMPLATE_UPDATE,
            title = "改运费模板",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_ORDER,
            blurb = "改一条运费参考价。**只影响以后派单时的参考值**，已经派出去的单不受影响。",
            targets = listOf(targetFreightTemplate()),
            fields = listOf(
                textField("from", "新起点", "不改就不填", maxChars = 64).copy(key = "from_place"),
                textField("to", "新终点", "不改就不填", maxChars = 64).copy(key = "to_place"),
                moneyField("fee", "新运费（元）", "只传数字", positive = false),
                textField("remark", "新备注", "不改就不填", maxChars = 200),
            ),
            headline = { c -> "改运费模板：${c.ref("template")?.label}" },
            details = { c ->
                listOfNotNull(
                    c.line("from_place", "起点改成"),
                    c.line("to_place", "终点改成"),
                    c.str("fee")?.let { "运费改成：$it 元" },
                    "只影响以后派单时的参考值",
                )
            },
        ) { ds, p ->
            ds.updateFreightTemplate(p.reqLong("template_id"), p.pick(TEMPLATE_KEYS))
        },

        crud(
            id = AiWrites.FREIGHT_TEMPLATE_DELETE,
            title = "删除运费模板",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_ORDER,
            blurb = "删掉一条运费参考价。已经派出去的单不受影响。"
                + "（删错了可以撤回）",
            targets = listOf(targetFreightTemplate()),
            headline = { c -> "删除运费模板：${c.ref("template")?.label}" },
            details = { listOf("模板：${it.ref("template")?.label}", "已经派出去的单不受影响") },
        ) { ds, p -> ds.deleteFreightTemplate(p.reqLong("template_id")) },

        // -------------------------------------------------------- 商品分类名册
        //
        // 用户 2026-09-18 原话：「在给 ai 的功能开放创建商品分组、管理商品分组的排序」。
        // 名册只决定**下单页左侧那一列怎么分组、什么顺序**；商品的归属是 `products.category`
        // 这个字符串，所以只有**改名**会波及商品（后端在同一个事务里级联改），
        // 卡片上因此必须写出"这个分类下有 N 个商品"（[targetProductCategory] 的 note）。
        crud(
            id = AiWrites.PRODUCT_CATEGORY_CREATE,
            title = "新建商品分类",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_CATEGORY,
            blurb = "在商品分类名册里加一格（下单页左侧那一列就是它）。" +
                "它只决定「怎么分组、什么顺序」，不改任何商品的分类——" +
                "商品挂到哪一类是建/改商品时选的那个分类名。",
            fields = listOf(
                textField("name", "分类名", "必填，如「水果」「冻品」", required = true, maxChars = 32),
                positionField("position", "排在第几位", "可选：从 1 数，1 = 排到最前面；不填就排在最后"),
            ),
            headline = { c -> "新建商品分类：${c.str("name")}" },
            details = { c ->
                listOfNotNull(
                    "分类名：${c.str("name")}",
                    c.str("position")?.let { "顺序：排到第 $it 位（1 = 最前面）" } ?: "顺序：排在最后",
                    "只加一格分组，不改任何商品的分类",
                )
            },
        ) { ds, p -> ds.createProductCategory(p) },

        crud(
            id = AiWrites.PRODUCT_CATEGORY_UPDATE,
            title = "改商品分类",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_CATEGORY,
            blurb = "改一个商品分类的名字，或者把它排到别的位置。只填要改的那一项。" +
                "改名会级联：挂在这一类下的商品，分类名会跟着一起改（后端在同一个事务里做）。",
            targets = listOf(targetProductCategory()),
            fields = listOf(
                textField("name", "新分类名", "不改就不填", maxChars = 32),
                positionField("position", "排到第几位", "不改就不填：从 1 数，1 = 最前面"),
            ),
            headline = { c -> "改商品分类：${c.ref("category")?.label}" },
            details = { c ->
                listOfNotNull(
                    "分类：${c.ref("category")?.label}",
                    c.ref("category")?.note?.let {
                        "⚠️ 这个分类下有 $it——改名会把这些商品的分类一起改过去（后端同一个事务）"
                    },
                    c.str("name")?.let { "名字改成：$it" },
                    c.str("position")?.let { "顺序改成：排到第 $it 位（1 = 最前面）" },
                    "顺序只改这一个分类的值：和别的分类撞上时按编号先后排，" +
                        "要让整份顺序干净，用「重排商品分类」一次提交整份",
                )
            },
        ) { ds, p -> ds.updateProductCategory(p.reqLong("category_id"), p.pick(CATEGORY_KEYS)) },

        crud(
            id = AiWrites.PRODUCT_CATEGORY_DELETE,
            title = "删除商品分类",
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_CATEGORY,
            blurb = "从分类名册里删掉一格。还有商品挂在这个分类下时后端会拒绝，并告诉你还有几个" +
                "——先把那些商品改成别的分类（或给这一格改个名）再删。" +
                "分类名册没有回收站，删掉就是真删（撤回是按原名重建一格，编号会不一样）。",
            targets = listOf(targetProductCategory()),
            headline = { c -> "删除商品分类：${c.ref("category")?.label}" },
            details = { c ->
                listOfNotNull(
                    "分类：${c.ref("category")?.label}",
                    c.ref("category")?.note?.let { "这个分类下有 $it" },
                    "还有商品挂在它下面时后端会拒绝，并告诉你有几个：先把那些商品改成别的分类（或给这一格改个名）",
                    "它只是下单页左边的一格分组，删掉不影响已经下过的单（单上是商品快照）",
                )
            },
        ) { ds, p -> ds.deleteProductCategory(p.reqLong("category_id")) },

        // -------------------------------------------------------- 地点分组名册（按人分区）
        //
        // 用户 2026-09-19 原话：「**添加分类**和**给地点归为到哪一类**，AI 是要有这个能力的。
        // 比如说，用户说『我将这个地点归到那一类当中』，AI 是可以操作的」。
        //
        // ⚠️ 与商品分类**最大的不同：这是"我自己那一份"**。所以每张卡上都要写明这一点，
        //    而数据源（`placeCategories()` / `repo.placeCategories()`）读的就是当前登录人那一份 ——
        //    越权在数据源上就不可能，不需要在这一层再判一次。
        crud(
            id = AiWrites.PLACE_CATEGORY_CREATE,
            title = "新建地点分组",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_PLACE_CATEGORY,
            blurb = "在**你自己的**地点分组名册里加一格（下单页地址库左栏就是它）。" +
                "它只决定「怎么分组、什么顺序」，不改任何地点的归属——" +
                "地点归到哪一组是在「改地点」里选的那个分组名。",
            fields = listOf(
                textField("name", "分组名", "必填，如「常送小区」「工地」", required = true, maxChars = 32),
                positionField("position", "排在第几位", "可选：从 1 数，1 = 排到最前面；不填就排在最后"),
            ),
            headline = { c -> "新建地点分组：${c.str("name")}" },
            details = { c ->
                listOfNotNull(
                    "分组名：${c.str("name")}",
                    c.str("position")?.let { "顺序：排到第 $it 位（1 = 最前面）" } ?: "顺序：排在最后",
                    "只加一格分组，不改任何地点的归属",
                    "⚠️ 只影响你自己的地址库（每个人管自己那一份，别人看不到）",
                )
            },
        ) { ds, p -> ds.createPlaceCategory(p) },

        crud(
            id = AiWrites.PLACE_CATEGORY_UPDATE,
            title = "改地点分组",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_PLACE_CATEGORY,
            blurb = "改一个**你自己的**地点分组的名字，或者把它排到别的位置。只填要改的那一项。" +
                "改名会级联：挂在它下面的地点会跟着改成新名字（后端在同一个事务里做）。",
            targets = listOf(targetPlaceCategory()),
            fields = listOf(
                textField("name", "新分组名", "不改就不填", maxChars = 32),
                positionField("position", "排到第几位", "不改就不填：从 1 数，1 = 最前面"),
            ),
            headline = { c -> "改地点分组：${c.ref("category")?.label}" },
            details = { c ->
                listOfNotNull(
                    "分组：${c.ref("category")?.label}",
                    c.ref("category")?.note?.let {
                        "⚠️ 这个分组下有 $it——改名会把这些地点的分组一起改过去（后端同一个事务）"
                    },
                    c.str("name")?.let { "名字改成：$it" },
                    c.str("position")?.let { "顺序改成：排到第 $it 位（1 = 最前面）" },
                    "⚠️ 只影响你自己的地址库",
                )
            },
        ) { ds, p -> ds.updatePlaceCategory(p.reqLong("category_id"), p.pick(PLACE_CATEGORY_KEYS)) },

        crud(
            id = AiWrites.PLACE_CATEGORY_DELETE,
            title = "删除地点分组",
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_PLACE_CATEGORY,
            blurb = "从**你自己的**地点分组名册里删掉一格。还有地点挂在这个分组下时后端会拒绝，" +
                "并告诉你还有几个——先把那些地点改成别的分组（或给这一格改个名）再删。" +
                "名册没有回收站，删掉就是真删（撤回是按原名重建一格，编号会不一样）。",
            targets = listOf(targetPlaceCategory()),
            headline = { c -> "删除地点分组：${c.ref("category")?.label}" },
            details = { c ->
                listOfNotNull(
                    "分组：${c.ref("category")?.label}",
                    c.ref("category")?.note?.let { "这个分组下有 $it" },
                    "还有地点挂在它下面时后端会拒绝，并告诉你有几个：先把那些地点改成别的分组",
                    "⚠️ 只影响你自己的地址库；地点本身一个都不会被删",
                )
            },
        ) { ds, p -> ds.deletePlaceCategory(p.reqLong("category_id")) },

        // ------------------------------------------------------------ 车辆
        crud(
            id = AiWrites.VEHICLE_CREATE,
            title = "新增车辆",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_USER,
            blurb = "登记一辆车（车牌 + 车型，可选绑定司机）。登记之后记支出、算油耗才能选到它。",
            targets = listOf(targetDriverOptional()),
            fields = listOf(
                textField("plate", "车牌号", "必填，如「豫A12345」", required = true, maxChars = 20)
                    .copy(key = "plate_no"),
                enumField(
                    "vehicle", "车型", "必填",
                    listOf("small", "large", "trailer"),
                    aliases = mapOf("小货" to "small", "小货车" to "small", "大货" to "large", "大货车" to "large", "挂车" to "trailer"),
                    key = "vehicle_type",
                ),
            ),
            headline = { c -> "新增车辆：${c.str("plate_no")}" },
            details = { c ->
                listOf(
                    "车牌：${c.str("plate_no")}",
                    "车型：${vehicleCn(c.str("vehicle_type"))}",
                ) + listOfNotNull(c.ref("driver")?.let { "绑定司机：${it.label}" })
            },
        ) { ds, p -> ds.createVehicle(p) },

        // 老缺口：`vehicle.create` 一直有，改车辆信息却一直没动作（用户 2026-09-18 点名要补）。
        // 档位 MEDIUM：改的是主数据、可逆；但车牌/车型会出现在支出与油耗的选择里，
        // 车辆列表上也会显示，所以卡片逐字段写「改前 → 改后」。
        //
        // ⚠️ v3.44：**司机不再从这里改**，挪到下面独立的 `vehicle.set_driver`。
        //    原因是"解绑"：这条动作的 commit 走的是 `VehicleUpdateRequest`，
        //    而安卓的 JSON 配置会把 `null` 整个键丢掉 → **解绑在这条路上做不到**。
        //    把它留在两个动作里，等于给模型两条都叫"换司机"的路，其中一条缺一半能力。
        crud(
            id = AiWrites.VEHICLE_UPDATE,
            title = "改车辆",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_USER,
            blurb = "改一辆车的车牌号、车型，或者把它停用/启用。只填要改的那几项。" +
                "车牌和车型会出现在记支出/算油耗选车的地方，车辆列表上也看得见。" +
                "⚠️ 换司机、解绑司机**不在这里**，用「车辆换司机」那个动作。",
            targets = listOf(targetVehicle()),
            fields = listOf(
                textField("plate", "新车牌号", "不改就不填，如「豫A12345」", maxChars = 16)
                    .copy(key = "plate_no"),
                // ⚠️ 参数名**不能叫 `vehicle`**：那是目标参数的键（"改哪一辆车"）。
                //    撞名之后两者读同一个键——用户说「豫A12345 换成大货车」时，
                //    模型只能填一个 `vehicle`，于是要么找不到车、要么车型没改，而且不会报错。
                //    （这一条是靠"模型能填的参数名"推出来的，不是靠红线：红线的重名检查
                //    只认 `enumField("x"` 这种单行写法，多行调用它看不见。）
                enumField(
                    "vehicle_type", "新车型", "不改就不填",
                    listOf("small", "large", "trailer"),
                    aliases = mapOf(
                        "小货" to "small", "小货车" to "small",
                        "大货" to "large", "大货车" to "large",
                        "挂车" to "trailer",
                    ),
                    key = "vehicle_type",
                ).copy(required = false),
                boolField("active", "是否启用", "不改就不填。true=启用，false=停用（车辆列表上会标「停用」）"),
            ),
            headline = { c -> "改车辆：${c.ref("vehicle")?.label}" },
            details = { c ->
                listOfNotNull(
                    "车辆：${c.ref("vehicle")?.label}",
                    c.str("plate_no")?.let { "车牌改成：$it" },
                    c.str("vehicle_type")?.let { "车型改成：${vehicleCn(it)}" },
                    c.bool("active")?.let { if (it) "改成：启用" else "改成：停用（车辆列表里会出现「停用」标记）" },
                    "车牌/车型会出现在记支出、算油耗选车的地方",
                )
            },
        ) { ds, p -> ds.updateVehicle(p.reqLong("vehicle_id"), p.pick(VEHICLE_KEYS)) },

        // ------------------------------------------------------ 车辆换/解绑司机（v3.44）
        //
        // 用户 2026-09-18：「司机的车辆绑定，App 端做不到」——AI 这边原来也只有"换成另一个人"，
        // **解绑做不到**（后端把空值忽略掉了）。现在后端给了专用入口，
        // 于是这一步三件事都能做：绑、换、解绑。
        //
        // 档位 MEDIUM：改的是主数据、随时能改回来，而且**必须留痕**（后端写 VEHICLE_DRIVER_SET）。
        // 卡片上要写清"现在归谁"——只说"解绑 A12345 的司机"，用户看不出被拿掉的是谁。
        crud(
            id = AiWrites.VEHICLE_SET_DRIVER,
            title = "车辆换司机",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_USER,
            blurb = "把这辆车绑给某个司机，或者**解绑**（司机那一项不填 = 解绑）。" +
                "一辆车同时只能归一个司机：绑给别人时，原来那位名下就没有这辆车了。",
            // 司机**不是必填**：不填就是解绑。空卡检查由 `allowTargetOnly` 放行——
            // 只点名车辆 = "把这辆车上的司机拿掉"，那是完整的一句需求。
            targets = listOf(targetVehicle(), targetDriverChangeable()),
            allowTargetOnly = true,
            // ⚠️ 解绑时也要把 `driver_id` 写进 payload（值为 null）：
            //    撤回是**按 payload 里有哪些键**去写回旧值的，少一个键那张卡的「撤回」就永远挂不上
            //    （真机 E2E 抓到的就是这个）。详见 [CrudSpec.alwaysIncludeTargets]。
            alwaysIncludeTargets = setOf("driver"),
            headline = { c ->
                if (c.ref("driver") == null) "解绑司机：${c.ref("vehicle")?.label}"
                else "给 ${c.ref("vehicle")?.label} 配司机"
            },
            details = { c ->
                listOfNotNull(
                    "车辆：${c.ref("vehicle")?.label}",
                    // 「现在归谁」必须写：否则"解绑"这张卡上不出现任何人的名字。
                    // ⚠️ 前缀只加一次：名册给的 note 是**纯值**（`Driver` / `没有司机`），
                    //    "现在：" 这种给人看的措辞归卡片管——两边各加一次会印出「现在：现在：Driver」（真机抓到过）。
                    c.ref("vehicle")?.note?.let { "现在：$it" },
                    if (c.ref("driver") == null) {
                        "改成：不绑司机（这辆车暂时不归任何人，派单时仍然能选到它）"
                    } else {
                        "改成：${c.ref("driver")?.label}"
                    },
                    // ⚠️ **不要在这里再加一句"误操作了不要紧…"**：框架会在每张卡末尾统一印一句
                    //    （`AiRevert` 的「卡片最后一行」），两处都写就会在真机上印出两条几乎一样的提醒
                    //    ——真机 E2E 报告里点出来的（可见噪声，用户会以为系统在重复强调什么）。
                )
            },
        ) { ds, p -> ds.setVehicleDriver(p.reqLong("vehicle_id"), p["driver_id"]?.jsonPrimitive?.longOrNull) },

        // ------------------------------------------------------------ 客户
        crud(
            id = AiWrites.CUSTOMER_CREATE,
            title = "新增客户",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_LEDGER,
            blurb = "新增一个客户（收款、对账用的对象）。只是一个**档案名字**，不建登录账号。",
            fields = listOf(
                textField("name", "客户名", "必填", required = true, maxChars = 128),
                textField("phone", "电话", "可选；同号会被沿用，见卡片说明", maxChars = 20),
                // ⚠️ 这里原来有一个「是不是批发商」的开关，写的是 `Customer.is_member` ——
                //    而那一列**全后端没有任何地方读**（会员/批发商身份的真实判据是
                //    `User.is_member`：`price_rules` / `users` / `ledger` / `reports` 读的都是它）。
                //    于是"类型：批发商（高级货主）"是一句**做不到的承诺**：建档完价格体系一点没变。
                //    2026-09-19 审计：去掉这个假能力，改成如实说明去哪改。
            ),
            headline = { c -> "新增客户：${c.str("name")}" },
            details = { c ->
                listOfNotNull(
                    "客户名：${c.str("name")}",
                    c.str("phone")?.let { "电话：$it" },
                    "同一个手机号已经有客户时「会沿用那一条」（不会新建、也不会改名字）——" +
                        "如果这是另一个人，请换一个手机号",
                    "批发商（高级货主）身份在「账号」上：需要的话请改那个账号的类型，建档时改不了",
                )
            },
        ) { ds, p -> ds.createCustomer(p) },

        // -------------------------------------------------------- 司机计费规则（v3.36）
        //
        // 这一组是"让 AI 帮我们配计费规则、并挂到司机身上"（用户 2026-09-18 的要求）。
        // 规则的三件（固定工资 / 每单固定 / 提成）与 `backend/app/services/driver_pay.py` 一一对应，
        // 卡片上的措辞也和后端 `PayRule.describe()` 保持一致（用户会拿两边对账）。
        crud(
            id = AiWrites.DRIVER_RULE_CREATE,
            title = "新增司机计费规则",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_USER,
            blurb = "新建一份可以重复用的计费规则：固定工资、每单（每车）多少钱、按运费或商品金额抽几成，" +
                "三件可以任意组合。建好之后还要挂给司机才会生效。",
            fields = listOf(
                textField("name", "规则名称", "必填，起个能认出来的名字（如「挂车计件」「大车固定工资+运费提成」）",
                    required = true, maxChars = 64),
                enumField(
                    "vehicle", "适用车型", "可选：不填=通用（什么车都能挂）",
                    listOf("small", "large", "trailer"),
                    aliases = mapOf("小货" to "small", "小货车" to "small", "大货" to "large",
                        "大货车" to "large", "普通车" to "large", "挂车" to "trailer"),
                    key = "vehicle_type",
                ).copy(required = false),
                moneyField("salary", "固定工资（元/月）", "没有固定工资就不填", positive = false),
                moneyField("piece", "每单金额（元）", "「跑一趟多少钱」那种按单/按车给的钱；没有就不填", positive = false)
                    .copy(key = "piece_amount"),
                enumField(
                    "piece_unit", "计件方式", "默认每单固定数；「拿这一单的钱」是按派单时定的价",
                    listOf("order", "order_price", "item"),
                    aliases = mapOf(
                        "每单" to "order", "每车" to "order", "一趟" to "order",
                        "订单固定价" to "order_price", "按单定价" to "order_price",
                        "拿这一单的钱" to "order_price", "按派单价" to "order_price",
                        "每件" to "item",
                    ),
                ).copy(required = false),
                enumField(
                    "base", "提成基数", "不提成就不填",
                    listOf("freight", "goods"),
                    aliases = mapOf("运费" to "freight", "运货的运费" to "freight",
                        "商品" to "goods", "商品金额" to "goods", "货款" to "goods"),
                    key = "commission_base",
                ).copy(required = false),
                moneyField("rate", "提成比例（%）", "填 5 就是抽 5%；没有提成就不填", positive = false)
                    .copy(key = "commission_rate"),
                textField(
                    "commission_products", "抽成商品",
                    "只对哪些商品抽成（按商品金额抽成时才有意义）；多个用、隔开；不填=所有商品",
                    maxChars = 400,
                ),
                textField("remark", "备注", "可选", maxChars = 200),
            ),
            headline = { c -> "新增计费规则：${c.str("name")}" },
            details = { c ->
                listOfNotNull(
                    "规则名：${c.str("name")}",
                    c.str("vehicle_type")?.let { "适用车型：${vehicleCn(it)}" },
                    c.str("salary")?.let { "固定工资：$it 元/月" },
                    pieceLine(c),
                    c.str("commission_rate")?.let { "提成：${commissionBaseCn(c.str("base"))}的 $it%" },
                    c.str("commission_products")?.let { "只对这几个商品抽成：$it" },
                    c.str("remark")?.let { "备注：$it" },
                    "⚠️ 这份规则建好还不生效：要挂给司机才算数（可以让我接着挂）",
                )
            },
        ) { ds, p -> ds.createDriverRule(p) },

        crud(
            id = AiWrites.DRIVER_RULE_UPDATE,
            title = "改司机计费规则",
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_USER,
            blurb = "改一份计费规则的参数。只管以后派的单：已经派出去的单用的是派单当时的规则快照，" +
                "所以改它不会让历史账单变数——但所有挂着这份规则的司机以后都按新参数算钱。",
            targets = listOf(targetDriverRule()),
            fields = listOf(
                textField("name", "新名称", "不改就不填", maxChars = 64),
                moneyField("salary", "新固定工资（元/月）", "不改就不填", positive = false),
                moneyField("piece", "新每单金额（元）", "不改就不填", positive = false).copy(key = "piece_amount"),
                moneyField("rate", "新提成比例（%）", "不改就不填", positive = false).copy(key = "commission_rate"),
                textField(
                    "commission_products", "新抽成商品",
                    "改成只对这些商品抽成；多个用、隔开；想取消范围就填「全部」",
                    maxChars = 400,
                ),
                textField("remark", "新备注", "不改就不填", maxChars = 200),
            ),
            headline = { c -> "改计费规则：${c.ref("rule")?.label}" },
            details = { c ->
                listOfNotNull(
                    "规则：${c.ref("rule")?.label}",
                    c.str("name")?.let { "名称改成：$it" },
                    c.str("salary")?.let { "固定工资改成：$it 元/月" },
                    c.str("piece_amount")?.let { "每单金额改成：$it 元" },
                    c.str("commission_rate")?.let { "提成比例改成：$it%" },
                    c.str("remark")?.let { "备注改成：$it" },
                    "⚠️ 挂着这份规则的司机，以后都按新参数算钱；已经派出去的单不变",
                )
            },
        ) { ds, p -> ds.updateDriverRule(p.reqLong("rule_id"), p.pick(DRIVER_RULE_KEYS)) },

        crud(
            id = AiWrites.DRIVER_RULE_DELETE,
            title = "删除司机计费规则",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_USER,
            blurb = "删掉一份用不到的计费规则。还有司机挂着它就会被拦下来（先给他们换掉或解挂），" +
                "删错了可以撤回。",
            targets = listOf(targetDriverRule()),
            headline = { c -> "删除计费规则：${c.ref("rule")?.label}" },
            details = { listOf("规则：${it.ref("rule")?.label}", "还挂着司机的规则删不掉（系统会拦下来）") },
        ) { ds, p -> ds.deleteDriverRule(p.reqLong("rule_id")) },

        crud(
            id = AiWrites.DRIVER_RULE_ATTACH,
            title = "给司机挂计费规则",
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_USER,
            blurb = "把一份计费规则挂到某个司机身上，或者不带规则名=解挂（他退回原来的算法）。" +
                "挂上之后他以后接的每一单都按这份规则算钱。",
            targets = listOf(
                targetUser("司机", role = "driver"),
                // 不带规则名 = 解挂。**允许"查不到"**在这种语义下正好用得上：
                // 用户说「把张三的计费规则取消」，模型就没东西可填。
                targetDriverRule(required = false),
            ),
            headline = { c ->
                val rule = c.ref("rule")?.label
                if (rule.isNullOrBlank()) "解除计费规则：${c.ref("user")?.label}" else "挂计费规则：${c.ref("user")?.label} → $rule"
            },
            details = { c ->
                val rule = c.ref("rule")?.label
                listOfNotNull(
                    "司机：${c.ref("user")?.label}",
                    if (rule.isNullOrBlank())
                        "改成：解除计费规则，他回到原来的算法（挂车=计件拿该单运费，其余=固定工资）"
                    else "改成：按「$rule」算钱",
                    "⚠️ 只管以后：已经派出去的单用的还是派单当时的规则",
                )
            },
        ) { ds, p ->
            // payload 就是第二个参数的本身（`JsonObject`），不是 `p.payload`
            ds.attachDriverRule(p.reqLong("user_id"), p["rule_id"]?.jsonPrimitive?.longOrNull)
        },

        // ------------------------------------------------- 撤回用的恢复动作
        //
        // ⛔ 这一组 **模型看不到**（[AiWriteAction.undoOnly]）：被软删的记录已经从名册里
        //    消失，模型按名字根本解析不到它——"恢复一条你看不见的记录"是个说不通的需求。
        //    但撤回路径拿着的是**确定的编号**，所以这些动作必须存在，只是不进模型清单。
        //
        // 每个**删除类动作**都指向这里的一个 id，但那件事不再写在这一层：
        // 撤回的接线全在 [AiResources]（每个资源声明一次 `restore`）。
        // 红线 §20 会逐个核对"指过去的那一头真的存在"，避免出现一个点下去报 404 的撤回按钮。
        restoreAction("地址", AiWrites.ADDRESS_RESTORE, AiWrites.G_ADDRESS) { ds, id ->
            ds.restoreAddress(id)
        },
        restoreAction("地点", AiWrites.LOCATION_RESTORE, AiWrites.G_ADDRESS) { ds, id ->
            ds.restoreLocation(id)
        },
        restoreAction("联系人", AiWrites.CONTACT_RESTORE, AiWrites.G_ADDRESS) { ds, id ->
            ds.restoreContact(id)
        },
        restoreAction("挂账单位", AiWrites.ARREARS_UNIT_RESTORE, AiWrites.G_LEDGER) { ds, id ->
            ds.restoreArrearsUnit(id)
        },
        restoreAction("运费模板", AiWrites.FREIGHT_TEMPLATE_RESTORE, AiWrites.G_ORDER) { ds, id ->
            ds.restoreFreightTemplate(id)
        },
        restoreAction("计费规则", AiWrites.DRIVER_RULE_RESTORE, AiWrites.G_USER) { ds, id ->
            ds.restoreDriverRule(id)
        },
    )

    // -------------------------------------------------------------- 小工具

    private fun targetArrearsUnit() = AiTargetSpec(
        param = "unit", cn = "挂账单位", key = "unit_id",
        hint = "挂账单位的名字",
        lookup = { ds, _ -> ds.arrearsUnits() },
    )

    private fun targetFreightTemplate() = AiTargetSpec(
        param = "template", cn = "运费模板", key = "template_id",
        hint = "模板名（如「市区→城东」）",
        lookup = { ds, _ -> ds.freightTemplates() },
    )

    /**
     * 商品分类（按**名字**找）。
     *
     * `note` 带的是"这个分类下有几个在用的商品"——改名会级联改掉它们，
     * 所以这个数字必须在卡片上（用户唯一能判断"改名会不会波及一片商品"的依据）。
     */
    private fun targetProductCategory() = AiTargetSpec(
        param = "category", cn = "商品分类", key = "category_id",
        hint = "分类名（下单页左边那一列的格子名，如「水果」）",
        lookup = { ds, _ -> ds.productCategories() },
    )

    /**
     * 地点分组（按**名字**找，**只在自己那一份名册里找**）。
     *
     * `note` 带的是"这一组下有几个地点"——改名/删除会波及它们，
     * 那个数字是用户判断影响面的唯一依据。
     */
    private fun targetPlaceCategory() = AiTargetSpec(
        param = "category", cn = "地点分组", key = "category_id",
        hint = "分组名（地址库左栏那一列的格子名，如「常送小区」）",
        lookup = { ds, _ -> ds.placeCategories() },
    )

    /** 地点分组进 payload 的键（改分组时只传点名的那几个）。 */
    private val PLACE_CATEGORY_KEYS = setOf("name", "sort_order")

    /** 车辆（按**车牌**找；车牌号忽略大小写与分隔符）。 */
    private fun targetVehicle() = AiTargetSpec(
        param = "vehicle", cn = "车辆", key = "vehicle_id",
        hint = "要改哪一辆车：车牌号（如「豫A12345」）",
        code = true,
        lookup = { ds, _ -> ds.vehicles() },
    )

    /**
     * 改车辆时的关联司机：**不填 = 不动**，填了就必须对上人（`allowMissing = false`）。
     *
     * ### 为什么和 [targetDriverOptional]（新增车辆用的那个）不是同一个
     * 新增车辆时"司机查不到"的后果很轻：这辆车先不绑任何人，卡片上那一行直接不出现。
     * 改车辆时同一个行为就变成了**静默丢参数**：用户说「把豫A12345 挂到张三名下」，
     * 而系统里没有"张三"这个司机时，车牌照改、司机纹丝不动，卡片上也不写——
     * 用户很难发现"换司机没生效"。所以这一条严格：对不上就拒绝，并给出候选名字。
     */
    private fun targetDriverChangeable() = AiTargetSpec(
        param = "driver", cn = "司机", key = "driver_id",
        hint = "把车挂给哪个司机（不改就不填）",
        required = false, allowMissing = false,
        lookup = { ds, _ -> ds.drivers() },
    )

    /**
     * 「排在第几位」（从 1 数）。
     *
     * ⚠️ 进 payload 的键叫 `sort_order`，是后端那套**从 0 数**的绝对位置
     * （`reorder` 写的也是它：`ids[0]` = 0）。`- 1` 的换算只在数据源那一层做一次，
     * 卡片上和用户说的是"第几位"，两边不会分叉。
     */
    private fun positionField(name: String, cn: String, hint: String) =
        AiFieldSpec(name, cn, AiFieldType.COUNT, hint, key = "sort_order")
    /**
     * 计费规则（按**名字**找，用户和 AI 都用名字说事）。
     *
     * `required = false`：不带规则名 = 「把这人的计费规则取消」——这是**解挂**，
     * 不是"查不到"。写成必填的话，用户说"取消张三的计费规则"会得到一句
     * "没找到规则「」"，而他其实是要求解挂，两个结果完全不同。
     */
    private fun targetDriverRule(required: Boolean = true) = AiTargetSpec(
        param = "rule", cn = "计费规则", key = "rule_id",
        hint = "计费规则的名字（如「挂车计件」）；不带就是解除他的计费规则",
        required = required,
        lookup = { ds, _ -> ds.driverRules() },
    )

    /** 计费规则进 payload 的键（**改规则时只传点名的那几个**，见 §20 的部分更新语义）。 */
    private val DRIVER_RULE_KEYS = setOf(
        "name", "salary", "piece_amount", "piece_unit", "commission_base", "commission_rate",
        "commission_products", "remark",
    )

    /** 计件那一行（「拿这一单的钱」和"每单 X 元"说法完全不同，不能混成一句）。 */
    private fun pieceLine(c: AiWriteCard): String? {
        val unit = c.str("piece_unit")
        if (unit == "order_price") return "计件：拿这一单的钱（派单时定的价）"
        return c.str("piece_amount")?.let { "每${if (unit == "item") "件" else "单"}：$it 元" }
    }

    /** 提成基数的中文（卡片上必须写清"抽的是哪笔钱"）。 */
    private fun commissionBaseCn(raw: String?): String = when (raw) {
        "freight" -> "运费"
        "goods" -> "商品金额"
        else -> "（未指定基数）"
    }

    /** 车辆可选绑定司机；**允许查不到**（那就不绑，而不是拒绝整条登记）。 */
    private fun targetDriverOptional() = AiTargetSpec(
        param = "driver", cn = "司机", key = "driver_id",
        hint = "可选，绑定的司机姓名",
        required = false, allowMissing = true,
        lookup = { ds, _ -> ds.drivers() },
    )

    private fun vehicleCn(raw: String?): String = when (raw) {
        "small" -> "小货车"
        "large" -> "大货车"
        "trailer" -> "挂车"
        else -> "（未知车型）"
    }

    // ⚠️ 坐标（GEO_LAT/GEO_LNG）也必须在这里：它是 prepare 里查高德换出来的**派生物**，
    // 不在 ADDRESS_KEYS 里就会被 `pick` 悄悄丢掉——症状是"地址存进去了、导航还是没有目的地"，
    // 而且不会报任何错（单测 `改地址定位到了就把新坐标一起写进去` 就是钉这个的）。
    private val ADDRESS_KEYS = setOf(
        "receiver_name", "phone", "detail_address", "origin_address", "remark", GEO_LAT, GEO_LNG,
    )
    private val CONTACT_KEYS = setOf("display_name", "phone")
    private val LOCATION_KEYS = setOf("name", "detail_address", "remark", "category", GEO_LAT, GEO_LNG)
    private val UNIT_KEYS = setOf("name", "phone", "remark")
    private val TEMPLATE_KEYS = setOf("from_place", "to_place", "fee", "remark")
    /** 分类的部分更新体（`sort_order` 在这里是**从 1 数**的位置，换算见 [positionField]）。 */
    private val CATEGORY_KEYS = setOf("name", "sort_order")
    /** 车辆的部分更新体（键名与 `VehicleUpdateRequest` 的 wire 名一致）。 */
    /**
     * 「改车辆」进 payload 的键。
     *
     * ⚠️ 这里原来还有 `driver_id` —— 是 v3.44 把"换/解绑司机"挪到独立动作
     * （`vehicle.set_driver`）之后**留下的化石**：字段规格里已经没有这个键了，
     * 实现里也明确写着 `driverId = null, // 司机不从这里走`。
     * 它在运行时不会生效（`pick` 只挑字段真产出的键），但"声明与实现走散"这件事本身有代价：
     * 下一个人看到键集合里有它，会以为这条路能改司机。
     * 判据 `_tools/qa/_check_ai_declarative_crud.py` 逐处对账 pick 键与实现（就是它抓到的这条）。
     */
    private val VEHICLE_KEYS = setOf("plate_no", "vehicle_type", "active")

    /** 与 [AiWriteMasterData] 里的同名工厂是同一份写法（见那里的注释）。 */
    private fun crud(
        id: String,
        title: String,
        risk: AiWriteRisk,
        group: String,
        blurb: String,
        targets: List<AiTargetSpec> = emptyList(),
        fields: List<AiFieldSpec> = emptyList(),
        // ⚠️ 这两个必须排在 `commit` **前面**：调用方写的是尾随 lambda
        // （`crud(...) { ds, p -> ... }`），Kotlin 只把它绑给**最后一个**参数。
        // 排在 commit 后面时，那个 lambda 会被塞给 `geocodeRequired`（Boolean）→ 编译不过。
        geocodeFrom: String? = null,
        geocodeRequired: Boolean = false,
        /** true = 改动可以只落在一个目标参数上（见 [CrudSpec.allowTargetOnly]）。 */
        allowTargetOnly: Boolean = false,
        /** 即使解析不出来也要进 payload 的目标参数（写 null）——"不填"本身是一个取值时用它。 */
        alwaysIncludeTargets: Set<String> = emptySet(),
        /** true = 只给撤回用，不进模型的动作清单。 */
        undoOnly: Boolean = false,
        headline: (AiWriteCard) -> String,
        details: (AiWriteCard) -> List<String>,
        commit: suspend (AiWriteDataSource, JsonObject) -> Unit,
    ): AiWriteAction = AiWriteAction(
        id = id,
        title = title,
        risk = risk,
        group = group,
        blurb = blurb,
        params = targets.map {
            AiWriteParam(it.param, it.cn, it.required, AiWriteParamKind.TEXT, it.hint)
        } + fields.map {
            AiWriteParam(it.name, it.cn, it.required, it.paramKind(), it.hint, it.enumValues)
        },
        crud = CrudSpec(
            targets, fields, headline, details, commit, geocodeFrom, geocodeRequired, allowTargetOnly,
            alwaysIncludeTargets,
        ),
        undoOnly = undoOnly,
    )

    private fun AiFieldSpec.paramKind(): AiWriteParamKind = when (type) {
        AiFieldType.TEXT -> AiWriteParamKind.TEXT
        AiFieldType.MONEY, AiFieldType.COUNT, AiFieldType.DELTA, AiFieldType.NON_NEGATIVE ->
        AiWriteParamKind.NUMBER
        AiFieldType.DATE -> AiWriteParamKind.DATE
        AiFieldType.BOOL -> AiWriteParamKind.TEXT
        AiFieldType.ENUM -> AiWriteParamKind.ENUM
    }
}

/**
 * 「排在第几位」（**从 1 数**，卡片上就是这么写的）→ 后端 `sort_order`（**从 0 数**）。
 *
 * ### 为什么要单独一个纯函数
 * 声明式那条路只能**原样搬值**（字段值直接进 payload），所以换算只可能发生在数据源那一层；
 * 而数据源在单测里是被替身换掉的（替身是**边界**，不该重写业务换算）。
 * 于是这里留一个能被断言钉住的纯函数：`positionToSortOrder(1) == 0`——
 * "差一位"这种错不会报错，只会让分类排错地方，所以它必须有一条测试。
 *
 * ⚠️ 两个方向必须同源：写下去的用这个函数，读回来的用 [AiRevertRead.productCategory]
 * 的 `sortOrder + 1`（撤回是把快照**原样写回 payload**，两边口径不一致就会差一位）。
 */
internal fun positionToSortOrder(position: Int): Int = position - 1
