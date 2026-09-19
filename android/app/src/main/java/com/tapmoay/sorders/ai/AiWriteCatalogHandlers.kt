package com.tapmoay.sorders.ai

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put

/**
 * 商品目录域的两个**手写**处理器：重排分类名册、设置商品可见范围。
 *
 * ### 为什么这两个不能走声明式（[CrudSpec]）
 * 声明式的形状是「一条已有的记录 + 几个字段」，而这两个动作的形状都不是：
 * - `product_category.reorder` 的输入是**一整份顺序**（名册里每个分类都要出现一次），
 *   而"谁被漏了"这句人话只能在处理器里写（后端也是整份校验，少一个就 400）；
 * - `user.product_visibility` 的输入是**一串商品名**（勾选白名单），
 *   声明式的目标解析一次只认一个名字，而且"custom 但一个都没勾"必须**在弹卡之前**就拒绝
 *   （后端会拒，但那时候用户已经点过确认了）。
 *
 * ### 两条共同规矩（和其它处理器一样）
 * 1. [AiWriteHandler.prepare] 里**不写后端**——查的都是名册（只读）；
 * 2. 卡片上写的和 payload 里发的是**同一份已解析数据**，所以不会分叉。
 */

/**
 * 重排商品分类（整份顺序一次提交）。
 *
 * ### 为什么卡上要把新顺序整个列出来
 * "顺序已调整"这句话没有任何信息量：用户核对的正是**谁排在谁前面**。
 * 所以卡片上既写改前那份、也逐行列改后那份（连"这一类下有几个商品"一起给）。
 */
class ReorderProductCategoriesHandler(
    private val ds: AiWriteDataSource,
    private val store: AiWritePreviewStore,
) : AiWriteHandler {

    override val actionId = AiWrites.PRODUCT_CATEGORY_REORDER

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val raw = AiWriteArgs.required(
            params, "order",
            "整份顺序：把名册里的分类名**一个不漏**地按想要的先后写全（用「、」隔开）",
        )
        val pool = ds.productCategories()
        if (pool.isEmpty()) {
            throw AiWriteArgException("商品分类名册还是空的，先把要用的分类建出来再排顺序。")
        }
        val current = pool.joinToString("、") { it.label }

        // 逐个严格对上：对不上、对上多个，都由 [AiWriteArgs.strict] 抛出去（并给候选名字）。
        val picked = ArrayList<AiName>(pool.size)
        for (name in splitNames(raw)) {
            val hit = AiWriteArgs.strict(name, pool, "商品分类")
                ?: throw AiWriteArgException("分类「$name」没对上，请核对名字。")
            if (picked.any { it.id == hit.id }) {
                throw AiWriteArgException(
                    "顺序里「${hit.label}」出现了两次。每个分类只能出现一次，请重新排一遍。",
                )
            }
            picked += hit
        }
        // ⚠️ 后端要求**整份**顺序。少了就整份拒绝（不是"没提到的保持原序"），
        //    所以这里也要在弹卡之前挡住，并把少了哪几个说清楚——让模型能一次改对。
        val missing = pool.filter { p -> picked.none { it.id == p.id } }
        if (missing.isNotEmpty()) {
            throw AiWriteArgException(
                "这份顺序里少了 ${missing.size} 个分类：${missing.joinToString("、") { it.label }}。" +
                    "后端要求一次提交**完整**的顺序（少一个都整份拒绝），" +
                    "请把名册里的分类一个不漏地按顺序写全（当前名册：$current）。",
            )
        }

        return AiWriteOutcome.NeedConfirm(
            store.offer(
                actionId = actionId,
                title = AiWrites.titleOf(actionId),
                risk = AiWrites.byId(actionId)!!.risk,
                summary = "重排商品分类：${picked.size} 个分类",
                detailLines = buildList {
                    add("改前的顺序：$current")
                    add("改后的顺序（下单页左侧从上到下就是这个顺序）：")
                    picked.forEachIndexed { i, n ->
                        val count = n.note?.let { "（$it）" }.orEmpty()
                        add("${i + 1}. ${n.label}$count")
                    }
                    add("只改显示顺序：一件商品挂在哪个分类下都不动")
                },
                payload = buildJsonObject {
                    put("category_ids", JsonArray(picked.map { JsonPrimitive(it.id) }))
                },
            ),
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        val ids = (payload["category_ids"] as? JsonArray).orEmpty()
            .mapNotNull { (it as? JsonPrimitive)?.contentOrNull?.toLongOrNull() }
        ds.reorderProductCategories(ids)
    }
}

/**
 * 重排**地点分组**（整份顺序一次提交）—— 与商品分类那份是同一套规矩。
 *
 * 用户 2026-09-19 要求 AI 也能碰地点分组（「添加分类和给地点归为到哪一类，AI 是要有这个能力的」），
 * 而"顺序"是这个功能的一半（另一半是归属），所以一起给。
 *
 * ⚠️ 与商品分类**唯一的差别**：名册是**按人分区**的 —— 读到的、能排的都只是当前登录人自己那一份。
 * 卡片上必须写明这一点，否则用户会以为自己在给"全店的分组"排序。
 */
class ReorderPlaceCategoriesHandler(
    private val ds: AiWriteDataSource,
    private val store: AiWritePreviewStore,
) : AiWriteHandler {

    override val actionId = AiWrites.PLACE_CATEGORY_REORDER

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val raw = AiWriteArgs.required(
            params, "order",
            "整份顺序：把你自己的地点分组名**一个不漏**地按想要的先后写全（用「、」隔开）",
        )
        val pool = ds.placeCategories()
        if (pool.isEmpty()) {
            throw AiWriteArgException("你还没有地点分组，先用「新建地点分组」建出来再排顺序。")
        }
        val current = pool.joinToString("、") { it.label }

        val picked = ArrayList<AiName>(pool.size)
        for (name in splitNames(raw)) {
            val hit = AiWriteArgs.strict(name, pool, "地点分组")
                ?: throw AiWriteArgException("分组「$name」没对上，请核对名字。")
            if (picked.any { it.id == hit.id }) {
                throw AiWriteArgException(
                    "顺序里「${hit.label}」出现了两次。每个分组只能出现一次，请重新排一遍。",
                )
            }
            picked += hit
        }
        val missing = pool.filter { p -> picked.none { it.id == p.id } }
        if (missing.isNotEmpty()) {
            throw AiWriteArgException(
                "这份顺序里少了 ${missing.size} 个分组：${missing.joinToString("、") { it.label }}。" +
                    "后端要求一次提交**完整**的顺序（少一个都整份拒绝），" +
                    "请把名册里的分组一个不漏地按顺序写全（当前名册：$current）。",
            )
        }

        return AiWriteOutcome.NeedConfirm(
            store.offer(
                actionId = actionId,
                title = AiWrites.titleOf(actionId),
                risk = AiWrites.byId(actionId)!!.risk,
                summary = "重排地点分组：${picked.size} 个分组",
                detailLines = buildList {
                    add("⚠️ 只影响你自己的地址库（每个人管自己那一份）")
                    add("改前的顺序：$current")
                    add("改后的顺序（地址库左栏从上到下就是这个顺序）：")
                    picked.forEachIndexed { i, n ->
                        val count = n.note?.let { "（$it）" }.orEmpty()
                        add("${i + 1}. ${n.label}$count")
                    }
                    add("只改显示顺序：一个地点归在哪一组都不动")
                },
                payload = buildJsonObject {
                    put("category_ids", JsonArray(picked.map { JsonPrimitive(it.id) }))
                },
            ),
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        val ids = (payload["category_ids"] as? JsonArray).orEmpty()
            .mapNotNull { (it as? JsonPrimitive)?.contentOrNull?.toLongOrNull() }
        ds.reorderPlaceCategories(ids)
    }
}

/**
 * 把「水果、冻品 干货」拆成名字列表（模型多半会用「、」，但逗号/斜杠/空格也常见）。
 *
 * 分隔符**只管拆**：拆出来的每一段都要在名册里唯一命中，否则整条命令被拒绝
 * （宁可让模型重说一遍，也不要"少排了一类"这种看不出来的结果）。
 */
internal fun splitNames(raw: String): List<String> =
    raw.split('、', '，', ',', '/', '／', ';', '；', '\n', '\r', '\t', ' ')
        .map { it.trim() }
        .filter { it.isNotEmpty() }

/**
 * 设置某个货主/批发商的**商品可见范围**（白名单）。HIGH 档：它本质是授权。
 *
 * ### 卡片上必须写清的四件事（少一件用户就没法核对）
 * 1. 改的是**谁**（姓名 + 是不是批发商）；
 * 2. 现在是**什么模式**（全部商品 / 只给勾选的）——他可能已经设过一次了；
 * 3. 改成什么模式（改回「全部商品」时还要写明：**旧白名单会被清掉**）；
 * 4. `custom` 时**把商品名一个一个列出来**——只写"N 个"用户核对不了（他不知道是哪 N 个）。
 *
 * ### 为什么 `custom` 但一个都没勾要在弹卡之前拒绝
 * 后端也会拒（"那样他打开选品页会是空的"），但那时候用户已经点过一次确认了。
 * 这两条（空白名单、商品名对不上）都属于"用户以为配好了、其实没有"，一律前置。
 */
class ProductVisibilityHandler(
    private val ds: AiWriteDataSource,
    private val store: AiWritePreviewStore,
) : AiWriteHandler {

    override val actionId = AiWrites.USER_PRODUCT_VISIBILITY

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val userRaw = AiWriteArgs.required(params, "user", "这是给谁设？写货主/批发商的姓名")
        // 只找货主：后端对非货主直接 400（"商品可见范围只对货主/批发商有意义"），
        // 而且派单员/司机根本不该被这条白名单限制。
        val user = AiWriteArgs.strict(
            userRaw,
            ds.searchShippers(userRaw, SHIPPER_PROBE_LIMIT),
            "货主/批发商",
        ) ?: throw AiWriteArgException(
            "系统里没有匹配「$userRaw」的货主/批发商。请让用户确认名字，" +
                "或者先去「货主管理」把人建好——这条设置只对货主/批发商有意义。",
        )

        val scope = resolveScope(
            AiWriteArgs.required(params, "scope", "是「全部商品」还是「只给勾选的」？只能是 all 或 custom"),
        )
        val productsRaw = AiWriteArgs.str(params, "products")

        // 现在是什么样（卡片上要写"改前"——否则用户不知道自己是第一次设还是改过）
        val before = ds.productVisibility(user.id)

        // 商品名 → 编号。**只对 custom 解析**：scope=all 时白名单会被整份清空，
        // 那时候再解析一遍商品名只是让一句本来无害的话变成"查不到就拒绝"。
        val picked = ArrayList<AiName>()
        if (scope == "custom") {
            if (productsRaw.isNullOrBlank()) {
                throw AiWriteArgException(
                    "选了「只给勾选的商品」却一个商品名都没给 —— 那样他打开选品页会是空的。" +
                        "请让用户点名要给他看的商品（至少一个），或者改成「全部商品」。",
                )
            }
            val pool = ds.products()
            for (name in splitNames(productsRaw)) {
                val hit = AiWriteArgs.strict(name, pool, "商品")
                    ?: throw AiWriteArgException("商品「$name」没对上，请核对名字。")
                if (picked.none { it.id == hit.id }) picked += hit
            }
            if (picked.isEmpty()) {
                throw AiWriteArgException(
                    "一个商品名都没解析出来 —— 那样他打开选品页会是空的。请让用户点名商品，或者传 scope=all。",
                )
            }
        }

        // 商品编号 → 名字（现在那份白名单里可能有已经下架/删掉的编号，如实写出来）
        val nameOf: Map<Long, String> = if (before.productIds.isEmpty()) {
            emptyMap()
        } else {
            ds.products().associate { it.id to it.label }
        }

        return AiWriteOutcome.NeedConfirm(
            store.offer(
                actionId = actionId,
                title = AiWrites.titleOf(actionId),
                risk = AiWrites.byId(actionId)!!.risk,
                summary = "商品可见范围：${user.label} → " + if (scope == "custom") {
                    "只给勾选的 ${picked.size} 个商品"
                } else {
                    "全部商品（不限制）"
                },
                detailLines = buildList {
                    add("对象：${user.label}" + (user.note?.let { "（$it）" } ?: ""))
                    add("现在：${describe(before.scope, before.productIds, nameOf)}")
                    if (scope == "custom") {
                        add("改成：只给勾选的 ${picked.size} 个商品")
                        // ⚠️ 必须把名字一个不漏地列出来：只写"N 个"，用户核对不了是哪几个。
                        picked.forEachIndexed { i, p -> add("　${i + 1}. ${p.label}") }
                        add("他打开选品页、下单时，没勾的商品一处都看不到（列表和接口一起挡）")
                    } else {
                        add("改成：全部商品（不限制）——整个商品库他都能看到、都能下单")
                        if (before.productIds.isNotEmpty()) {
                            add("⚠️ 现在勾着的那 ${before.productIds.size} 个会被清掉：以后要再限制，得重新勾一遍")
                        }
                    }
                    if (scope == "all" && !productsRaw.isNullOrBlank()) {
                        add("（你提到的商品名不会写进去：范围是「全部商品」，本来就不需要白名单）")
                    }
                },
                payload = buildJsonObject {
                    put("user_id", user.id)
                    put("scope", scope)
                    put(
                        "product_ids",
                        JsonArray(if (scope == "custom") picked.map { JsonPrimitive(it.id) } else emptyList()),
                    )
                },
            ),
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        val ids = (payload["product_ids"] as? JsonArray).orEmpty()
            .mapNotNull { (it as? JsonPrimitive)?.contentOrNull?.toLongOrNull() }
        ds.setProductVisibility(payload.reqLong("user_id"), payload.req("scope"), ids)
    }

    /** 范围归一：收 `all` / `custom`，也收用户嘴里的「全部商品」「只给勾选的」。 */
    private fun resolveScope(raw: String): String {
        val v = raw.trim().lowercase()
        return when {
            v in setOf("all", "全部", "全部商品", "所有商品", "不限", "不限制", "放开") -> "all"
            v in setOf("custom", "只给勾选的", "勾选的", "指定", "指定商品", "白名单", "部分") -> "custom"
            else -> throw AiWriteArgException(
                "scope「$raw」不是有效取值。只能是 all（全部商品）或 custom（只给勾选的）。",
            )
        }
    }

    /** 「现在是什么样」那一行：模式 + （只给勾选时）把商品名列出来。 */
    private fun describe(scope: String, ids: List<Long>, nameOf: Map<Long, String>): String {
        if (!scope.equals("custom", ignoreCase = true)) return "全部商品（不限制）"
        if (ids.isEmpty()) return "只给勾选的，但白名单是空的（他选品页什么都看不到）"
        // 查不到名字的那个编号**不写编号**：卡片上出现 "编号 123" 用户也不知道那是谁，
        // 只会怀疑是不是改错了地方（和"静默键不许上卡"是同一条理由）。
        val names = ids.joinToString("、") { nameOf[it] ?: "（一个已经不在商品库里的商品）" }
        return "只给勾选的 ${ids.size} 个商品：$names"
    }

    private companion object {
        /** 查货主名册时一次拉多少条（和账本记一笔那边同一个口径）。 */
        const val SHIPPER_PROBE_LIMIT = 20
    }
}
