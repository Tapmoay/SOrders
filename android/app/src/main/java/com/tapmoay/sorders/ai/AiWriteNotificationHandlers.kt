package com.tapmoay.sorders.ai

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * 消息域的写动作（发消息 / 价格变更通知 / 标记已读 / 改内容 / 删消息）。
 *
 * ### 两个方向，风险完全不同
 * - **发出去**的（`send` / `price_change`）：会**推给别人**，发出去收不回来 → HIGH。
 *   卡片必须把标题与正文**原文摊开**，因为那就是对方会看到的东西。
 * - **动自己的**（`mark_read` / `update` / `delete`）：不影响别人，但都要先"找到那几条"。
 *   找错的后果是把别的消息误改/误删 → 一律上卡片核对，不自动执行。
 *   （对比：`notifications.read_all` 是 LOW、自动执行——因为它**不用挑**，一个动作覆盖全部，
 *   没有"选错了范围"这种失败模式。这条区别就是这个域的风险判据。）
 *
 * ### 定位
 * 消息没有名字，靠**标题/正文里的关键词**找，范围限定在**当前登录账号**最近收到的若干条
 * （`GET /notifications?limit=`，一次最多 50 条，客户端再筛）。对不上或对上多条一律拒绝列候选。
 */
abstract class NotificationWriteHandler(
    protected val ds: AiWriteDataSource,
    protected val store: AiWritePreviewStore,
) : AiWriteHandler {

    protected fun card(summary: String, details: List<String>, payload: JsonObject): AiWriteOutcome =
        AiWriteOutcome.NeedConfirm(
            store.offer(
                actionId = actionId,
                title = AiWrites.titleOf(actionId),
                risk = AiWrites.byId(actionId)!!.risk,
                summary = summary,
                detailLines = details,
                payload = payload,
            ),
        )

    /**
     * 按关键词找消息。
     *
     * `allowMultiple` = 允许一次命中多条（标记已读/删除时是"这几条一起办"），
     * 不给的话就必须**唯一命中**（改内容时只能改一条）。
     */
    protected suspend fun findNotifications(keyword: String, allowMultiple: Boolean): List<AiNotificationRef> {
        val all = ds.myNotifications(AiWrites.NOTIFICATION_PROBE)
        if (all.isEmpty()) {
            throw AiWriteArgException("你最近没有收到消息，没什么可操作的。请如实告诉用户。")
        }
        val key = AiWriteArgs.norm(keyword)
        val pool = all.filter { AiWriteArgs.norm(it.title).contains(key) || AiWriteArgs.norm(it.content).contains(key) }
        return when {
            pool.isEmpty() -> throw AiWriteArgException(
                "最近 ${all.size} 条消息里没有含「$keyword」的。最近这些是：\n" +
                    all.take(AiWriteArgs.MAX_CANDIDATES).joinToString("\n") { "· " + it.label() },
                candidates = all.take(AiWriteArgs.MAX_CANDIDATES).map { it.label() },
            )

            allowMultiple -> pool

            pool.size == 1 -> pool

            else -> throw AiWriteArgException(
                "「$keyword」对上了 ${pool.size} 条消息，改错一条就改到别的消息上了。" +
                    "请让用户说得更具体一点：\n" +
                    pool.take(AiWriteArgs.MAX_CANDIDATES).joinToString("\n") { "· " + it.label() },
                candidates = pool.take(AiWriteArgs.MAX_CANDIDATES).map { it.label() },
            )
        }
    }
}

// ============================================================== 发消息给某人

/**
 * 给某个账号发一条站内消息。
 *
 * 为什么收件人姓名要**严格唯一**：发出去就推送了，撤回不了。
 * "发给老王"而系统里有两个老王时，猜错的代价是**另一个人收到一条莫名其妙的消息**。
 */
class SendNotificationHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : NotificationWriteHandler(ds, store) {

    override val actionId = AiWrites.NOTIFICATIONS_SEND

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val to = AiWriteArgs.required(params, "to", "发给谁？把收件人姓名（或手机号）告诉我。")
        val who = AiWriteArgs.strict(to, ds.users(to), "账号")
        val title = AiWriteArgs.text(AiWriteArgs.required(params, "title", "消息标题是什么？"), "标题", max = 60)
        val content = AiWriteArgs.text(AiWriteArgs.required(params, "content", "消息正文是什么？"), "正文", max = 300)
        val important = AiWriteArgs.parseBool(params, "important") ?: false

        return card(
            summary = "发消息给 ${who!!.label}：$title",
            details = buildList {
                add("收件人：${who.label}")
                add("标题：$title")
                add("正文：$content")
                // ⛔ 这句原来写「对方会收到语音播报」——**这是一句不会发生的事**
                //    （2026-09-19 审计 R14-11）：全仓库 grep `speech_important`/`speechImportant`，
                //    安卓侧只有 DTO 声明与这里的写入，**没有一处读取**；唯一的消费方是旧网页端。
                //    于是派单员按卡片承诺以为司机手机把这句话喊出来了，实际司机很可能没看手机。
                //    「承诺一件不会发生的事」正是本项目明令禁止的形状，所以改成如实说明。
                if (important) add("标为重要：只会打上「重要」标记（新版 App 不会因此播语音，仍是普通提醒）")
                add("———— 发出去之后 ————————")
                add("对方会立刻收到一条推送（收不回来）")
            },
            payload = buildJsonObject {
                put("recipient_id", who.id)
                put("title", title)
                put("content", content)
                put("important", important.toString())
            },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.sendNotification(
            recipientId = payload.reqLong("recipient_id"),
            title = payload.req("title"),
            content = payload.req("content"),
            important = payload.str("important")?.toBooleanStrictOrNull() ?: false,
        )
    }
}

// ============================================================== 价格变更通知

/**
 * 价格变更通知（后端按模板拼标题正文）。
 *
 * ⚠️ 后端要求带 `product_id`，所以商品名**必须能在商品库里找到**——
 * 找不到就拒绝，而不是让用户填一个"通知发不出去"的空转。
 */
class PriceChangeNotifyHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : NotificationWriteHandler(ds, store) {

    override val actionId = AiWrites.NOTIFICATIONS_PRICE_CHANGE

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val name = AiWriteArgs.required(params, "product", "是哪个商品调价了？把商品名告诉我。")
        val product = ds.productPrices().firstOrNull {
            it.name.trim().equals(name.trim(), ignoreCase = true)
        } ?: throw AiWriteArgException(
            "商品库里没有叫「$name」的商品。价格通知必须带商品编号，所以这个名字得能在商品库里对上。" +
                "请让用户确认商品名（可以先用查询工具列一下商品）。",
        )

        val to = AiWriteArgs.required(params, "to", "通知哪些货主？可以说「全部批发商」，也可以说名字。")
        val shippers: List<AiName> = if (AiWriteArgs.norm(to).contains("全部") || AiWriteArgs.norm(to).contains("所有")) {
            val all = ds.members()
            if (all.isEmpty()) throw AiWriteArgException("现在一个批发商账号都没有，没法通知。")
            all
        } else {
            to.split(',', '，', '、', ' ').map { it.trim() }.filter { it.isNotEmpty() }.map { one ->
                AiWriteArgs.strict(one, ds.searchShippers(one, 20), "货主")
                    ?: throw AiWriteArgException("找不到货主「$one」。")
            }
        }

        val newPrice = AiWriteArgs.parseMoney(
            AiWriteArgs.required(params, "new_price", "新价格是多少？"),
            "new_price",
            mustPositive = false,
        )
        val oldPrice = AiWriteArgs.str(params, "old_price")?.let {
            AiWriteArgs.parseMoney(it, "old_price", mustPositive = false)
        }
        val priceType = AiWriteArgs.str(params, "price_type")?.trim()?.lowercase()?.takeIf { it.isNotEmpty() }
            ?.also {
                if (it !in setOf("default", "special")) {
                    throw AiWriteArgException("「哪种价」只认 default（默认价）或 special（专属价），你说的「$it」不在里面。")
                }
            } ?: "default"

        return card(
            summary = "发价格变更通知：${product.name} → ${AiWriteArgs.money(newPrice)} 元（${shippers.size} 个货主）",
            details = buildList {
                add("商品：${product.name}")
                add("价格：${oldPrice?.let { AiWriteArgs.money(it) } ?: "—"} → ${AiWriteArgs.money(newPrice)} 元")
                add("价格类型：${if (priceType == "default") "默认价" else "专属价"}")
                add("———— 通知这些人 ————")
                shippers.take(10).forEach { add("· ${it.label}") }
                if (shippers.size > 10) add("…… 还有 ${shippers.size - 10} 个")
                add("标题与正文由系统按模板生成（「商品价格调整：${product.name}」）")
                add("这 ${shippers.size} 个人都会收到推送，收不回来")
            },
            payload = buildJsonObject {
                put("product_id", product.id)
                put("product_name", product.name)
                put("price_type", priceType)
                put("new_price", newPrice.toPlainString())
                oldPrice?.let { put("old_price", it.toPlainString()) }
                put("shipper_ids", shippers.joinToString(",") { it.id.toString() })
            },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.notifyPriceChange(
            shipperIds = payload.req("shipper_ids").split(",").mapNotNull { it.trim().toLongOrNull() },
            productId = payload.reqLong("product_id"),
            productName = payload.req("product_name"),
            priceType = payload.req("price_type"),
            newPrice = payload.req("new_price"),
            oldPrice = payload.str("old_price"),
        )
    }
}

// ============================================================== 标记已读

class MarkNotificationsReadHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : NotificationWriteHandler(ds, store) {

    override val actionId = AiWrites.NOTIFICATIONS_MARK_READ

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val keyword = AiWriteArgs.required(params, "keyword", "哪几条消息？把里面最独特的几个字告诉我。")
        val hits = findNotifications(keyword, allowMultiple = true).filter { !it.read }
        if (hits.isEmpty()) {
            throw AiWriteArgException(
                "含「$keyword」的消息都已经读过了，不用再标。请如实告诉用户。",
            )
        }
        return card(
            summary = "标记已读：${hits.size} 条消息",
            details = buildList {
                hits.take(10).forEach { add("· ${it.label()}") }
                if (hits.size > 10) add("…… 还有 ${hits.size - 10} 条")
                add("（只是把未读改成已读，消息本身不动）")
            },
            payload = buildJsonObject { put("ids", hits.joinToString(",") { it.id.toString() }) },
        )
    }

    /** 逐条结果（[commitNote] 取走即清空）——见下面 commit 里的说明。 */
    private var pendingNote: String? = null

    override fun commitNote(): String? = pendingNote.also { pendingNote = null }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        // ⚠️ 这是"一次确认 → N 个请求"的动作，必须**逐条**汇报结果（2026-09-19 审计）。
        //    原来是一个 `forEach { ds.markNotificationRead(it) }`：中间任何一条失败
        //    （例如那条消息在两次点击之间被另一台设备删掉 → 404）都会让异常冒泡到服务层，
        //    用户看到的是**整体失败**——而实际上前面几条**已经标成已读了**。
        //    与它对称的另一个病（"已完成"盖住失败行）在批量调价里也犯过，那里的解法是 `commitNote`，
        //    这里照同一套写：全成功就说全成功，有失败就把**第几条、为什么**如实列出来。
        val ids = payload.req("ids").split(",").mapNotNull { it.trim().toLongOrNull() }
        val failed = mutableListOf<String>()
        var done = 0
        ids.forEachIndexed { i, id ->
            try {
                ds.markNotificationRead(id)
                done += 1
            } catch (e: Exception) {
                failed += "第 ${i + 1} 条：${e.message ?: e.javaClass.simpleName}"
            }
        }
        pendingNote = when {
            failed.isEmpty() -> "已标记 $done 条（全部成功）"
            done == 0 -> "这 ${ids.size} 条「一条都没标上」：${failed.joinToString("；")}"
            else -> "成功 $done 条、失败 ${failed.size} 条（${failed.joinToString("；")}）。" +
                "失败的多半是那条消息已被别处删除，请刷新后看看还剩哪些未读。"
        }
        if (done == 0 && failed.isNotEmpty()) {
            // 一条都没成功 = 这次动作**没有产生任何效果**：必须让它以失败结束，
            // 否则用户看到的是"已完成"，而实际上什么都没变。
            throw IllegalStateException(pendingNote)
        }
    }
}

// ============================================================== 改消息内容

class UpdateNotificationHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : NotificationWriteHandler(ds, store) {

    override val actionId = AiWrites.NOTIFICATIONS_UPDATE

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val keyword = AiWriteArgs.required(params, "keyword", "要改哪一条消息？把里面最独特的几个字告诉我。")
        val target = findNotifications(keyword, allowMultiple = false).single()
        val newTitle = AiWriteArgs.str(params, "new_title")?.trim()?.takeIf { it.isNotEmpty() }
            ?.let { AiWriteArgs.text(it, "标题", max = 60) }
        val newContent = AiWriteArgs.str(params, "new_content")?.trim()?.takeIf { it.isNotEmpty() }
            ?.let { AiWriteArgs.text(it, "正文", max = 300) }
        if (newTitle == null && newContent == null) {
            throw AiWriteArgException("你还没说要改成什么。可以改标题、正文。请让用户说清楚。")
        }

        return card(
            summary = "改消息：${target.title.ifBlank { target.label() }}",
            details = buildList {
                add("这条消息：")
                add("· 标题：${target.title.ifBlank { "（空）" }}")
                add("· 正文：${target.content.take(60)}")
                add("———— 改成 ————")
                if (newTitle != null) add("标题：${target.title.ifBlank { "（空）" }} → $newTitle")
                if (newContent != null) add("正文：→ $newContent")
                add("只改你自己这边的消息，对方不会收到新的推送")
            },
            payload = buildJsonObject {
                put("notification_id", target.id)
                newTitle?.let { put("title", it) }
                newContent?.let { put("content", it) }
            },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.updateNotification(payload.reqLong("notification_id"), payload.str("title"), payload.str("content"))
    }
}

// ============================================================== 删消息

/**
 * 删消息：按关键词删几条，或清空全部。
 *
 * ⚠️ `all=true` 是这一域最危险的一步（一次清空）。所以：
 * 1. 它**必须由用户明说**（模型不许自己推出来）；
 * 2. 卡片上要写清**会删掉多少条**——数字是他最后一道防线。
 */
class DeleteNotificationsHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : NotificationWriteHandler(ds, store) {

    override val actionId = AiWrites.NOTIFICATIONS_DELETE

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val all = AiWriteArgs.parseBool(params, "all") ?: false
        val keyword = AiWriteArgs.str(params, "keyword")?.trim()?.takeIf { it.isNotEmpty() }

        if (all && keyword != null) {
            throw AiWriteArgException("「全部清空」和「按关键词删」只能选一个。请让用户说清楚要哪种。")
        }
        if (!all && keyword == null) {
            throw AiWriteArgException(
                "你还没说要删哪些消息。要么给一个关键词（删含它的几条），" +
                    "要么让用户明确说「全部清空」。",
            )
        }

        if (all) {
            val mine = ds.myNotifications(AiWrites.NOTIFICATION_PROBE)
            return card(
                summary = "清空全部消息（${mine.size} 条）",
                details = buildList {
                    add("这会删掉你自己的全部 ${mine.size} 条消息")
                    mine.take(5).forEach { add("· ${it.label()}") }
                    if (mine.size > 5) add("…… 还有 ${mine.size - 5} 条")
                    add("删了就没了（收不回来）")
                },
                payload = buildJsonObject { put("all", "true") },
            )
        }

        val hits = findNotifications(keyword!!, allowMultiple = true)
        return card(
            summary = "删消息：${hits.size} 条（含「$keyword」）",
            details = buildList {
                hits.take(10).forEach { add("· ${it.label()}") }
                if (hits.size > 10) add("…… 还有 ${hits.size - 10} 条")
                add("删了就没了（收不回来）")
            },
            payload = buildJsonObject { put("ids", hits.joinToString(",") { it.id.toString() }) },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        val ids = payload.str("ids")?.split(",")?.mapNotNull { it.trim().toLongOrNull() }.orEmpty()
        ds.deleteNotifications(ids, all = payload.str("all")?.toBooleanStrictOrNull() ?: false)
    }
}
