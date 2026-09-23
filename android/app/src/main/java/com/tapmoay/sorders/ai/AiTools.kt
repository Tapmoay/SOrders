package com.tapmoay.sorders.ai

import com.tapmoay.sorders.core.ApiClient
import com.tapmoay.sorders.data.repo.AppRepository
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.add
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.putJsonObject
import java.time.LocalDate
import java.time.format.DateTimeParseException
import kotlin.math.round

/**
 * 工具集合抽象。
 *
 * 抽成 interface 是为了让 [AiAgentLoop] 可以注入假工具集做纯逻辑单测；
 * 生产实现只有一个：[AiTools]。
 */
interface AiToolset {
    /** 全部工具名（含被用户关闭的），顺序固定。 */
    val allToolNames: List<String>

    /** 当前启用、要喂给模型的工具定义。 */
    val specs: List<ToolSpec>

    /**
     * 当前登录角色 + **他是不是批发商货主**（见 [AiActor]）。
     *
     * ⚠️ 为什么工具集要看第二维（2026-09-20 用户第七轮）：货主有两个 —— 普通货主与批发商货主，
     * 手机上「我的账本」那一段就不一样（批发商多一本自己的账：给下游货主核销/撤销/恢复）。
     * 工具**说明**和**enum** 都按它裁：裁少了用户办不成事，裁多了会看见一张点了必然失败的卡。
     * null = 还没认出来（fail-closed：身份段只说"没认出你的角色"）。
     */
    val actor: AiActor?

    /** 用户在设置里打开的只读模块（提示词里的读能力清单要与工具说明同源）。 */
    val enabledReadModules: Set<String>

    /**
     * 用户是否允许把**成本 / 毛利**给模型看（`AiKeyStore::costVisible`，**派单员默认开**、其余角色默认关）。
     *
     * 提示词里"成本这块你能不能看"那句话**必须跟着它变**：写死成"你没有权限"是错的 ——
     * 用户打开开关之后模型还照旧说没权限，他会以为开关坏了（"操作与逻辑不匹配"）。
     */
    val allowCost: Boolean

    /**
     * 执行工具。**任何失败都必须返回 `{"error":"人话"}` 字符串，绝不抛异常**
     * （抛出去会打断整个 agent 循环）；唯一允许抛出的是 [CancellationException]。
     */
    suspend fun execute(name: String, argumentsJson: String): String

    /** 结果的简短摘要，供聊天页展示「工具跑完了，拿到什么」。默认取前若干字。 */
    fun summarize(name: String, resultJson: String): String = resultJson.take(160)
}

/**
 * 派单员 AI 的 5 个**只读**工具。
 *
 * ### 安全红线
 * 1. 只有读接口，没有任何写操作（不下单、不派单、不改价、不删数据）。
 * 2. 返回给模型的内容**必须剔除成本字段**（`cost_price` / `cost_total` / `cost_covered_lines` /
 *    商品报表里的 `cost`，以及能反推出成本的 `profit` / `margin`）——见 [isHiddenField]。
 *    只读不等于可以泄露成本价：模型输出会显示在聊天页、也可能被截图外发。
 * 3. 返回给模型的内容**必须剔除内部主键**（`id` / `*_id`）——用户看不懂也用不上，
 *    而模型拿到就会写进回答（实测会附「（user_id 122）」）。同见 [isHiddenField]。
 * 3. 永远限制条数（默认 20，上限 50），只保留必要字段，避免把整个列表塞进上下文烧 token。
 *
 * ### 关于「参数/端点还没上线」
 * `search_shipper`（`GET /users?q=`）、`inventory_alerts`（`GET /inventory/summary?below_alert=`）、
 * `shipper_performance`（`GET /stats/shipper-performance`）这三个依赖后端同步新增的能力。
 * 一旦后端返回 404/422，工具统一返回「该能力暂不可用」，让模型如实告诉用户，而不是崩掉。
 *
 * @param repo 复用 App 已有的 Retrofit 客户端（由调用方从 AppContainer 取），**不自己 new Retrofit**。
 * @param enabledNames 用户开关的工具名集合（默认全开）。
 */
class AiTools(
    private val repo: AppRepository,
    private val enabledNames: () -> Set<String> = { AiKeyStore.DEFAULT_ENABLED_TOOLS },
    /** 通用读工具的开关（按模块，见 [AiReadCatalog]）。默认全开。 */
    private val readModules: () -> Set<String> = { AiReadCatalog.modules().toSet() },
    /**
     * **允许把成本 / 毛利给模型看吗**（设置页那个开关，默认**关**）。
     *
     * 用户 2026-09-19：「只要是我们改过、比如说新加了一些功能，AI 它都要具备操纵这些功能的能力」。
     * 而"成本"这一块**本来是拦死的**（v3.7 定的红线：成本价一旦进模型上下文，
     * 它就出现在聊天记录里、可能被截图外发）。两个要求都成立，所以做成**用户自己的开关**：
     *
     * - **默认值按角色**（2026-09-20 用户改的口径：「对那个默认也要开起来」）：派单员默认开、其余角色默认关；
     * - 打开之后 AI 才能读成本/毛利、查成本价历史、申请改成本价与录进货价。
     *
     * 做成 `() -> Boolean` 而不是 `Boolean`：设置页一改立刻生效（与 [readModules] 同一手法）。
     */
    private val allowCostProvider: () -> Boolean = { false },
    /**
     * 「记住」工具的实现：把一条事实写进**本机**长期记忆。
     *
     * 做成回调而不是直接依赖 [AiMemoryStore]，有两个原因：
     * 1. 这个工具是**唯一不碰后端**的写操作，把"写哪儿"交给装配层，
     *    工具层就无法自作主张去改别的东西；
     * 2. `AiTools` 的单测可以塞一个假实现，不必拉起 Android 的文件系统。
     *
     * @return 给模型/用户看的一句话；**null = 写入没成功**（功能被用户关了，或落盘失败）。
     */
    private val rememberFact: suspend (subject: String, fact: String) -> String? = { _, _ -> null },
    /**
     * 当前登录角色：决定**动作清单**里给模型看哪些（执行侧的门在 AiWriteService 里）。
     *
     * ⚠️ 默认值是 `null`（**fail-closed**，2026-09-23 改）——原来是 `{ AiRole.DISPATCHER }`。
     *    那是个 fail-**open** 的默认：谁新加一个装配点（或写个忘了传 provider 的构造），
     *    拿到的是**权限最大的那个角色的清单**，而且不会有任何报错。
     *    认不出角色应该是"什么都别给"（与 `AiReadCatalog` 那条口径、以及旁边
     *    [memberProvider] 的 `false` 默认值同一条纪律），不是"按派单员给"。
     *    生产装配点 `AiContainer` 一直是显式传的，所以这个默认值只影响"忘了传"的情况 ——
     *    而那正是它该挡的情况。
     */
    private val roleProvider: () -> AiRole? = { null },
    /**
     * **他是不是批发商货主**（`users.is_member=1`）。
     *
     * 与 [roleProvider] 成对出现、缺一不可：只看角色的后果是普通货主的工具说明里
     * 也印着「核销」那一组（模型会照着它跟用户解释一件他做不了的事）。
     *
     * ⚠️ 默认 `false` 是**故意**的（fail-closed）：认不出就按普通货主给能力 ——
     *    少给会立刻被发现（批发主会问"怎么不能核销了"），多给不会有人发现。
     *    真正的实现在 `AiContainer`（发货主之前先问一次 `users/me`）。
     */
    private val memberProvider: () -> Boolean = { false },
    /**
     * **本机能力**的定位提供者（`read_data` 的 `location.current`，见 [AiLocalReads]）。
     *
     * 与 [memberProvider] 同样是回调：定位权限随时可能被系统撤掉，每次执行时现读。
     * 默认 `null` = 这个环境没有定位能力（单测），效果是**如实说读不到**，不是编一个地址。
     */
    private val locationProvider: () -> AiLocationProvider? = { null },
    /**
     * 「写操作」的落点：**申请**执行一个会改动业务数据的操作（见 [AiWriteService]）。
     *
     * 注意签名里没有"确认"这个参数——**模型无法确认自己的申请**。它调用这个回调只会
     * 拿到 [AiWriteOutcome.NeedConfirm]，真正执行只能由界面上的按钮触发
     * （见 [AiWritePreviewStore] 的不变量 1）。
     *
     * 默认实现直接拒绝：没接线时宁可"不能写"，也不能悄悄放行。
     *
     * ⚠️ 这段说明原来**挂错了参数**（2026-09-21 精简轮）：它写在 `roleProvider` 头上，
     *    读代码的人会以为"角色决定模型能不能确认自己的申请"——注释挂错位置和写错内容一样会骗人。
     */
    private val requestWrite: suspend (String, JsonObject) -> AiWriteOutcome =
        { _, _ -> AiWriteOutcome.Rejected("写操作功能当前不可用。") },
) : AiToolset {

    /** 通用「读列表」服务（`read_data` 工具的实现，见 [AiReadService]）。 */
    private val reader: AiReadService by lazy {
        AiReadService(repo, readModules, allowCostProvider, { actor() }, locationProvider)
    }

    /**
     * 工具分组：设置页按这个分两栏渲染（见 [AiTools.Companion.settingsItems]）。
     *
     * ### 为什么必须分（这不是排版问题）
     * `preview_write` 一上，同一列开关里就同时躺着"只看"和"会改"两类。
     * 混排的话用户扫一眼**根本分不出哪个会动数据**——而这一栏恰恰是他最该一眼看明白的地方。
     * 分栏之后，"操作类"那一栏的说明色用警示色、并且旁边必须写明"AI 只会生成确认卡"。
     */
    enum class Group(val label: String, val hint: String) {
        QUERY("查询类", "只读，不会改动任何数据"),
        OPERATE("操作类", "会改动数据，请逐条看清楚再打开"),
    }

    override val allToolNames: List<String> = ALL

    /** 角色 + 是不是批发商货主（[AiActor]）—— 工具清单与说明都按它现算。 */
    private fun actor(): AiActor? = AiActor.of(roleProvider(), memberProvider())

    override val actor: AiActor? get() = actor()

    override val enabledReadModules: Set<String> get() = readModules()
    override val allowCost: Boolean get() = allowCostProvider()

    override val specs: List<ToolSpec>
        get() {
            val on = enabledNames()
            val actor = actor()
            // preview_write 的说明里嵌着**动作清单**，而清单按角色+member 裁剪——
            // 所以它不能走静态的 SCHEMAS（那份表在 companion 里，看不到实例状态）。
            //
            // ⚠️ 还要过 `ROLE_TOOLS[role]`：**工具本身也按角色裁**（v3.28）。
            //    只裁说明不裁工具的话，货主照样能调 `driver_performance` / `export_sheet`，
            //    然后拿一个后端 403 回来——用户看到的还是"我明明有这功能"。
            val mine = ROLE_TOOLS[actor?.role] ?: emptySet()
            return ALL.filter { it in on && it in mine }.map {
                when (it) {
                    PREVIEW_WRITE -> previewWriteSpec(actor)
                    READ_DATA -> readDataSpec(actor)
                    else -> specOf(it)
                }
            }
        }

    /**
     * `read_data` 的工具定义（**动态**：说明里的表清单按角色裁剪，见 [AiReads]）。
     *
     * 和 `preview_write` 同样的道理：静态 `SCHEMAS` 建在 companion 里，看不到实例上的角色，
     * 而"哪些表这个角色能读"是从后端授权推导出来的、每个角色都不一样。
     *
     * ⚠️ 参数部分（name/q/from/to/status/limit/extra）**只在这里有一份**（2026-09-21 精简轮）：
     *    静态表 [SCHEMAS] 里原来还抄着一份 43 行的同样定义，而 `specs` 从来到不了
     *    `specOf(READ_DATA)` —— 那份**一个读者都没有**，已删掉（红线盯着它不许回来）。
     *    原文那句"与静态那份一致"正是留着两份的原因：**以为它还在用**。
     */
    private fun readDataSpec(actor: AiActor?): ToolSpec {
        val actions = AiReads.forRole(actor, readModules())
        return ToolSpec(
            type = "function",
            function = FunctionSpec(
                name = READ_DATA,
                description = AiTools.DESCRIPTIONS.getValue(READ_DATA),
                parameters = buildJsonObject {
                    put("type", "object")
                    putJsonObject("properties") {
                        putJsonObject("action") {
                            put("type", "string")
                            put("description",
                                "要查哪张表，从下面清单里**原样照抄**一个（格式 模块.动作）：\n" +
                                    AiReads.describeForModel(actor, readModules()))
                            putJsonArray("enum") { actions.forEach { add(JsonPrimitive(it.action)) } }
                        }
                        putJsonObject("name") {
                            put("type", "string")
                            put("description", "要筛的具体**名字**（货主名/司机名/商品名/客户名/订单号）。" +
                                "例如「城东水果批发的账本」传 name=城东水果批发。" +
                                "注意：只传名字，**不要**传任何编号。")
                        }
                        putJsonObject("q") {
                            put("type", "string")
                            put("description", "通用关键词（这个接口支持 q 时生效），可搜名字/单号/手机号片段")
                        }
                        putJsonObject("from") {
                            put("type", "string")
                            put("description", "起始日期 YYYY-MM-DD（接口用 date_from/from/month 时都会自动对上）")
                        }
                        putJsonObject("to") {
                            put("type", "string")
                            put("description", "结束日期 YYYY-MM-DD")
                        }
                        putJsonObject("status") {
                            put("type", "string")
                            // ⚠️ 这里**不许举例子**（2026-09-19 审计）：原来写「如 PENDING_DISPATCH /
                            //    DELIVERED / PAID」，而 PAID 根本不是订单状态（它是账单状态）——
                            //    模型照着抄 → 422 → 被翻成"这个功能没上线"，用户彻底放弃这条路。
                            //    合法取值由 App 侧按接口自己的 enum 校验（不合法会回一句带合法值的提示）。
                            put(
                                "description",
                                "状态筛选（接口支持 status 时生效）。**取值必须用该接口自己的枚举**：" +
                                    "订单是 PENDING_DISPATCH / DISPATCHED / ACCEPTED / DELIVERED / " +
                                    "CANCELLED / RETURNED；" +
                                    "账单是 open / settled；结算单是 draft / confirmed / paid / cancelled。" +
                                    "不确定或用户没提，就**不要填**这个参数——填错会被后端拒掉。",
                            )
                        }
                        putJsonObject("limit") {
                            put("type", "integer")
                            put("description", "最多返回几条，默认 $DEFAULT_ROWS，上限 $MAX_ROWS。" +
                                "⚠️ 用户要「全部/所有/名单」时必须**一次设够**（例如 $MAX_ROWS），" +
                                "不要只给一部分再让他「说一声继续」——他自己取不了，只能再问一遍")
                        }
                        putJsonObject("extra") {
                            put("type", "string")
                            put("description", "其它筛选条件的 JSON 字符串，键名必须是该接口声明的参数" +
                                "（例如 {\"kind\":\"member\"} 或 {\"below_alert\":true}）。不确定就别填。")
                        }
                    }
                    putJsonArray("required") { add(JsonPrimitive("action")) }
                },
            ),
        )
    }

    /**
     * `preview_write` 的工具定义（**动态**：说明里的动作清单按角色裁剪）。
     *
     * ### 为什么要单独一个方法
     * 它的 `description` 里嵌着整份动作清单，而那份清单对货主和派单员是不同的。
     * 静态的 `SCHEMAS` 建在 companion object 里，**看不到实例上的角色**，
     * 所以这个工具只能在这里现拼。schema 的其它部分（参数名、类型）与静态那份保持一致。
     */
    private fun previewWriteSpec(actor: AiActor?): ToolSpec {
        // ⚠️ 必须用 forModel：orRole 里还包含撤回专用的恢复动作（undoOnly），
                //    它们不进模型清单——被软删的记录已经不在名册里，模型按名字一定解析不到，
                //    放进清单就是能看见但一定失败（红线把这一类列为最坏 bug）。
                val actions = AiWrites.forModel(actor)
        return ToolSpec(
            type = "function",
            function = FunctionSpec(
                name = PREVIEW_WRITE,
                description = AiTools.DESCRIPTION_PREVIEW_WRITE,
                parameters = buildJsonObject {
                    put("type", "object")
                    putJsonObject("properties") {
                        putJsonObject("action") {
                            put("type", "string")
                            put("description",
                                "要做的操作，从下面清单里**原样照抄**一个（格式 模块.动作）：\n" +
                                    AiWrites.describeForModel(actor))
                            putJsonArray("enum") { actions.forEach { add(JsonPrimitive(it.id)) } }
                        }
                        putJsonObject("params") {
                            put("type", "object")
                            put("description", PARAMS_HINT)
                        }
                    }
                    putJsonArray("required") { add(JsonPrimitive("action")) }
                },
            ),
        )
    }

    // ------------------------------------------------------------------ 执行

    override suspend fun execute(name: String, argumentsJson: String): String {
        if (name !in ALL) return err("没有名为「$name」的工具，可用工具：${ALL.joinToString("、")}。")
        if (name !in enabledNames()) return err("工具「${titleOf(name)}」被用户关闭了，现在不能使用，请换一个角度提问。")

        val args = parseArgs(argumentsJson) ?: return err("工具参数不是合法 JSON，请重新生成参数。")

        return try {
            when (name) {
                SEARCH_SHIPPER -> searchShipper(args)
                INVENTORY_ALERTS -> inventoryAlerts(args)
                DRIVER_PERFORMANCE -> driverPerformance(args)
                SHIPPER_PERFORMANCE -> shipperPerformance(args)
                EXPORT_SHEET -> exportSheet(args)
                READ_DATA -> reader.read(str(args, "action").orEmpty(), args)
                REMEMBER -> remember(args)
                PREVIEW_WRITE -> previewWrite(args)
                else -> err("工具「$name」暂未实现。")
            }
        } catch (e: CancellationException) {
            throw e // 取消必须穿透，否则聊天页取消不了
        } catch (e: ToolArgException) {
            err(e.message ?: "参数不正确")
        } catch (e: Exception) {
            err(humanError(e, name))
        }
    }

    override fun summarize(name: String, resultJson: String): String {
        val o = resultJson.asJsonObjectOrNull() ?: return resultJson.take(120)
        (o["error"] as? JsonPrimitive)?.contentOrNull?.let { return "失败：" + it.take(100) }
        // ⚠️ 必须排在 message 之前：这类结果是"已交给用户确认"，**不是"做完了"**。
        // 少了这一条，痕迹会显示成「✓ 写操作 → 完成」，用户会以为已经写进去了。
        (o["status"] as? JsonPrimitive)?.contentOrNull?.let {
            if (it == CARD_OFFERED_STATUS) {
                val s = (o["summary"] as? JsonPrimitive)?.contentOrNull.orEmpty()
                return "已生成确认卡，等用户点确认：" + s.take(80)
            }
        }
        (o["message"] as? JsonPrimitive)?.contentOrNull?.let { return it.take(100) }
        val count = (o["count"] as? JsonPrimitive)?.contentOrNull
        if (count != null) return "返回 " + count + " 条"
        return "完成"
    }

    // ------------------------------------------------------- 工具 1：找货主

    private suspend fun searchShipper(args: JsonObject): String {
        val query = str(args, "query")
            ?: throw ToolArgException("缺少 query：请给出货主姓名或手机号（可以只写其中一段）。")

        // limit 给大一点再本地过滤，避免后端只搜出司机导致货主为空
        val users = repo.searchUsers(query, limit = (rowCap(args) * 4).coerceAtMost(200))

        val kw = query.lowercase()
        val shippers = users
            .filter { it.role == "shipper" }
            .filter { u ->
                // 后端若忽略了 q（老版本），这里本地再过滤一次，确保「搜不到就是真搜不到」
                u.phone.contains(query) ||
                    u.fullName.lowercase().contains(kw) ||
                    u.username.lowercase().contains(kw)
            }
            .take(rowCap(args))

        return buildJsonObject {
            put("query", query)
            put("count", shippers.size)
            putJsonArray("items") {
                shippers.forEach { u ->
                    add(
                        buildJsonObject {
                            put("name", safeName(u.fullName.ifBlank { u.username }))
                            put("phone", u.phone)
                            // 批发商 = 高级货主，价格体系不同，模型需要知道
                            put("is_member", u.isMember)
                            put("is_active", u.isActive)
                        },
                    )
                }
            }
            if (shippers.isEmpty()) {
                put("note", "没有匹配的货主。可能原因：姓名/手机号片段写错，或该货主不在当前账号可见范围内。")
            }
        }.toString()
    }

    // ------------------------------------------------------- 工具 2：库存报警

    private suspend fun inventoryAlerts(args: JsonObject): String {
        val rows = repo.inventoryBelowAlert().take(rowCap(args))
        return buildJsonObject {
            put("count", rows.size)
            put("definition", "报警 = 商品设置了报警阈值（low_stock_alert>0）且当前库存 ≤ 阈值")
            putJsonArray("items") {
                rows.forEach { p ->
                    add(
                        buildJsonObject {
                            put("product_name", p.productName)
                            put("stock", p.stock)
                            put("unit", p.unit)
                            put("low_stock_alert", p.lowStockAlert)
                            put("reserved_in_transit", p.reserved)
                        },
                    )
                }
            }
            if (rows.isEmpty()) put("note", "当前没有触发报警的商品。")
        }.toString()
    }

    // ------------------------------------------- 工具 3：司机跑货 / 待结运费

    private suspend fun driverPerformance(args: JsonObject): String {
        val (from, to, swapped) = resolvePeriod(args)
        val dto = repo.driverPerformance(from.toString(), to.toString())
        val rows = dto.drivers.take(rowCap(args))
        return buildJsonObject {
            put("period", "$from ~ $to")
            if (swapped) put("note", "你给的 date_from 晚于 date_to，已自动交换。")
            put("count", rows.size)
            putJsonArray("items") {
                rows.forEach { d ->
                    add(
                        buildJsonObject {
                            put("driver_name", safeName(d.driverName))
                            put("completed_orders", d.completedCount)
                            // 后端给的是 0~1 的比例，这里换算成百分数，减少模型算错概率
                            d.onTimeRate?.let { put("on_time_rate_percent", round1(it * 100)) }
                            d.avgDeliverySeconds?.let { put("avg_delivery_minutes", round1(it / 60.0)) }
                            put("photo_upload_percent", round1(d.photoUploadRate * 100))
                            put("billing_mode", billingLabel(d.billingMode))
                            d.freightOwed?.let { put("freight_owed_yuan", it) }
                        },
                    )
                }
            }
            if (rows.isEmpty()) put("note", "该时间段没有已送达的司机记录。")
        }.toString()
    }

    // ----------------------------------------------- 工具 4：货主下单排行

    /**
     * 该端点由后端同步新增，出参形状未冻结，所以这里**宽松解析**：
     * 接受「裸数组」或「对象里某字段是数组」，逐行抹平并剔除成本字段。
     */
    private suspend fun shipperPerformance(args: JsonObject): String {
        val (from, to, swapped) = resolvePeriod(args)
        val root = repo.shipperPerformance(from.toString(), to.toString())
        val rows = rowsOf(root).take(rowCap(args))
        val periodLabel = (root as? JsonObject)?.get("period_label")?.let { (it as? JsonPrimitive)?.contentOrNull }
        return buildJsonObject {
            put("period", periodLabel?.takeIf { it.isNotBlank() } ?: "$from ~ $to")
            if (swapped) put("note", "你给的 date_from 晚于 date_to，已自动交换。")
            put("count", rows.size)
            putJsonArray("items") { rows.forEach { add(normalizeNames(stripAndFlatten(it))) } }
            if (rows.isEmpty()) put("note", "该时间段没有货主下单记录。")
        }.toString()
    }

    // ------------------------------------------------------- 工具 5：导出表

    /**
     * 导出 Excel。**第一版不下载文件**：只把请求打到后端（真正生成 xlsx），
     * 立刻关掉响应流（[okhttp3.ResponseBody.close]），让用户自己去报表中心查看/下载。
     * 这样做的原因：聊天页没有文件保存/分享的 UI，硬下到缓存目录只会变成垃圾文件。
     */
    private suspend fun exportSheet(args: JsonObject): String {
        val kind = str(args, "kind")
            ?: throw ToolArgException("缺少 kind：要导出哪种表（turnover=营业/products=商品/drivers=司机/customers=客户/finance=财务/audit=异常审计）。")
        if (kind !in EXPORT_KINDS) {
            throw ToolArgException("kind 只能是 ${EXPORT_KINDS.joinToString("/")}，收到的是「$kind」。")
        }
        val mode = (str(args, "mode") ?: "day").lowercase()
        if (mode !in EXPORT_MODES) {
            throw ToolArgException("mode 只能是 ${EXPORT_MODES.joinToString("/")}，收到的是「$mode」。")
        }
        val anchor = dateArg(args, "date") ?: LocalDate.now()
        val from = dateArg(args, "date_from")
        val to = dateArg(args, "date_to")

        // 注意：后端 reports.py 的查询参数名是 date（形参别名 anchor），不是 anchor
        val body = repo.exportReport(
            kind = kind,
            mode = mode,
            date = anchor.toString(),
            dateFrom = from?.toString(),
            dateTo = to?.toString(),
        )
        body.close() // 不下载：把体积留给报表页自己按需下载

        return buildJsonObject {
            put("ok", true)
            put("message", "已生成，请到「报表中心」查看/下载。")
            put("kind", kind)
            put("mode", mode)
            put("date", anchor.toString())
            if (from != null && to != null) put("date_range", "$from ~ $to")
        }.toString()
    }

    // ------------------------------------------------------- 工具 7：记住

    /**
     * 把用户明确要求记住的一条事实存进**本机**记忆。
     *
     * ### 它是本工具集里唯一"写"的操作，而它写的东西不碰后端
     * 前 6 个工具全是只读查询。这一个会落盘，但落的是 App 私有目录里的一份 JSON
     * （见 [AiMemoryStore]）：
     * - **不改任何业务数据**（不下单、不派单、不改价）；
     * - **不出这台手机**（与聊天记录、使用习惯同一条隐私边界）；
     * - **用户随时能看见、能改、能删**（设置页「AI 助手 → 记忆」）。
     *
     * 所以它没有走"写操作"该有的确认流程（那套是给改业务数据准备的，见方案 §2.5），
     * 但它的**调用条件被卡得很死**——见 `DESCRIPTIONS[REMEMBER]`：
     * 只在用户明确说"记住…"时才许调用。
     */
    private suspend fun remember(args: JsonObject): String {
        val subject = str(args, "subject")
            ?: throw ToolArgException(
                "缺少 subject：这条记忆是**关于谁**的？填货主名/司机名/商品名，" +
                    "或者「${AiMemories.SUBJECT_GLOBAL}」（表示是对你回答方式的偏好）。",
            )
        val fact = str(args, "fact")
            ?: throw ToolArgException("缺少 fact：要记住的**具体内容**是什么？用一句话说清楚。")

        if (subject.length > AiMemories.MAX_SUBJECT_CHARS) {
            throw ToolArgException("subject 太长了（上限 ${AiMemories.MAX_SUBJECT_CHARS} 字），填一个名字就够了。")
        }
        if (fact.length > AiMemories.MAX_FACT_CHARS) {
            throw ToolArgException(
                "fact 太长了（上限 ${AiMemories.MAX_FACT_CHARS} 字）。压缩成一句话，只留以后用得上的那部分。",
            )
        }

        val message = rememberFact(subject, fact)
            ?: return err("记忆功能被用户在设置里关掉了（或者这次没能存下来）。请如实告诉用户，不要假装记住了。")

        return buildJsonObject {
            put("ok", true)
            put("subject", subject)
            put("message", message)
        }.toString()
    }

    // ------------------------------------------------- 工具 8：申请写操作

    /**
     * **申请**执行一个写操作。返回值一定是三种之一，见 [AiWriteOutcome]。
     *
     * ### 这个函数里最重要的一件事：**它没有"执行"这个分支**
     * 它只做三件事：把参数转给 [AiWriteService.preview]，把结果翻成 JSON 还给模型，
     * 以及在 `NeedConfirm` 时告诉模型"**卡已经给用户了，你什么都还没做成**"。
     * 真正写库的那一步在 [AiWriteService.execute]，它的唯一调用方是聊天页的确认按钮
     * ——**从模型出发的调用路径根本到不了那里**。这不是"我们约定了不越权"，
     * 是"越权的路不存在"。Operit 的 `deny_tool` 那类字符串判权限之所以危险，
     * 就是因为它把这条路留着、只在路口贴了张纸。
     */
    private suspend fun previewWrite(args: JsonObject): String {
        val actionId = str(args, "action")
            ?: throw ToolArgException(
                "缺少 action：要做哪个操作？可选：" + AiWrites.ids.joinToString("、") + "。",
            )
        val params = (args["params"] as? JsonObject) ?: JsonObject(emptyMap())

        return when (val out = requestWrite(actionId, params)) {
            is AiWriteOutcome.Done -> buildJsonObject {
                put("ok", true)
                put("status", "done")
                put("message", out.message)
            }.toString()

            is AiWriteOutcome.NeedConfirm -> buildJsonObject {
                put("ok", true)
                put("status", CARD_OFFERED_STATUS)
                put("summary", out.pending.summary)
                put("note",
                    "确认卡已经显示在用户的聊天页上了（内容以卡片为准）。**你现在什么都还没写成**：" +
                        "① 不要跟用户说「已经记好了」，要说「确认卡发给你了，点确认就写好」；" +
                        "② 不要再调用一次本工具——重复申请会让用户看到两张一样的卡；" +
                        "③ 用户点完确认之后，界面上会自己出现结果，不需要你补一句。",
                )
            }.toString()

            is AiWriteOutcome.Rejected -> buildJsonObject {
                put("error", out.reason)
                if (out.candidates.isNotEmpty()) {
                    putJsonArray("candidates") { out.candidates.forEach { add(JsonPrimitive(it)) } }
                }
            }.toString()
        }
    }

    // ----------------------------------------------------------- 公共小工具

    /** 行数上限：默认 20，允许模型用 limit 调整，硬上限 [MAX_ROWS]。 */
    private fun rowCap(args: JsonObject): Int =
        (intArg(args, "limit") ?: DEFAULT_ROWS).coerceIn(1, MAX_ROWS)

    /** 解析时间段；缺省 = 最近 7 天。返回值第三项 = 是否发生过起止交换。 */
    private fun resolvePeriod(args: JsonObject): Triple<LocalDate, LocalDate, Boolean> {
        val today = LocalDate.now()
        val from = dateArg(args, "date_from")
        val to = dateArg(args, "date_to")
        return when {
            from != null && to != null ->
                if (from.isAfter(to)) Triple(to, from, true) else Triple(from, to, false)
            from != null -> Triple(from, if (from.isAfter(today)) from else today, false)
            to != null -> Triple(to, to, false)
            else -> Triple(today.minusDays(6), today, false)
        }
    }

    /** 日期参数：缺省返回 null；**写了但格式不对直接报错**（否则后端 422/500 会很难懂）。 */
    private fun dateArg(args: JsonObject, key: String): LocalDate? {
        val raw = str(args, key) ?: return null
        return try {
            LocalDate.parse(raw)
        } catch (e: DateTimeParseException) {
            throw ToolArgException("$key 必须是 YYYY-MM-DD 格式（例如 2026-09-01），收到的是「$raw」。")
        }
    }

    private fun str(args: JsonObject, key: String): String? =
        (args[key] as? JsonPrimitive)?.contentOrNull?.trim()?.takeIf { it.isNotEmpty() }

    private fun intArg(args: JsonObject, key: String): Int? = str(args, key)?.toIntOrNull()

    /** 工具参数 JSON：容忍 ```json 围栏；返回 null 表示无法解析。 */
    private fun parseArgs(raw: String): JsonObject? {
        var s = raw.trim()
        if (s.isEmpty()) return JsonObject(emptyMap())
        if (s.startsWith("```")) {
            s = s.removePrefix("```json").removePrefix("```").removeSuffix("```").trim()
        }
        return try {
            ApiClient.json.parseToJsonElement(s) as? JsonObject
        } catch (e: Exception) {
            null
        }
    }

    private fun err(message: String): String =
        buildJsonObject { put("error", message) }.toString()

    private fun round1(v: Double): Double = round(v * 10.0) / 10.0

    private fun billingLabel(raw: String?): String = when (raw?.uppercase()) {
        "PIECE" -> "计件"
        "SALARY" -> "固定工资"
        null, "" -> "未设置"
        else -> raw
    }

    /**
     * 把任意异常转成人话。区分「能力没上线」「没权限」「登录过期」「网络不通」四类，
     * 让模型能如实解释，而不是瞎编一个结果。
     */
    private fun humanError(e: Throwable, toolName: String): String {
        if (e is SerializationException) return "服务返回的数据格式无法解析（$toolName）。"
        val ax = ApiClient.toApiException(e)
        return when (ax.code) {
            // ⚠️ 422 必须与 404/405 分开（2026-09-19 审计）：422 = **参数不对**（后端会给一句中文，
            //    写明哪个字段、允许什么值），而 404/405 才是"接口不存在"。
            //    原来三者合成一句"该能力暂不可用（接口还没提供）"，于是模型把"参数写错"
            //    讲成"这个功能没上线"——用户听到的是假话，而且永远不会再试第二次。
            422 -> "参数没通过后端的校验：" + (ax.message ?: "请按接口允许的取值改一个再试") +
                "。这不是功能缺失，请**照着这句话改参数重试一次**；改不动就如实告诉用户参数不受支持。"
            404, 405 -> "该能力暂不可用（$toolName 依赖的后端接口还没提供）。请把这个情况如实告诉用户。"
            // ⚠️ 权限类**只说一句**（用户原话：「权限不够的话不用说那么多，直接返回权限不够」）。
            //    这里以前是"当前登录账号没有权限查看这项数据。"——模型会绕着这句解释半天，
            //    用户看到的是一篇作文。现在给一句结论 + 两条"别做"的指令。
            403 -> "权限不够。一句话告诉用户这项他看不了；不要解释机制、不要复述这句话、不要给替代方案。"
            401 -> "登录已过期，请让用户重新登录后再试。"
            400 -> "参数后端不接受：" + (ax.message ?: "请调整参数")
            -2 -> "连接后端超时，请检查网络后重试。"
            -3 -> "网络连接失败，请检查网络后重试。"
            else -> "查询失败：" + (ax.message ?: e.javaClass.simpleName)
        }
    }

    /**
     * 下面这一组加工工序**已经搬到 [AiRowShaper]**（单一出处）。
     * 留这几个私有转发只是为了不改动原有调用点；**不要在这里重新实现一遍**——
     * 一旦有两份"剔字段"的实现，漏的那个就是把编号/成本泄露给用户的那个。
     */
    private fun stripAndFlatten(row: JsonObject): JsonObject =
        AiRowShaper.stripAndFlatten(row, allowCostProvider())

    private fun safeName(raw: String?): String = AiRowShaper.safeName(raw)

    private fun normalizeNames(row: JsonObject): JsonObject = AiRowShaper.normalizeNames(row)

    private fun rowsOf(root: JsonElement): List<JsonObject> = AiRowShaper.rowsOf(root)

    private fun isHiddenField(key: String): Boolean = AiRowShaper.isHiddenField(key, allowCostProvider())

    private fun String.asJsonObjectOrNull(): JsonObject? = try {
        ApiClient.json.parseToJsonElement(this) as? JsonObject
    } catch (e: Exception) {
        null
    }

    companion object {
        const val SEARCH_SHIPPER = "search_shipper"
        const val INVENTORY_ALERTS = "inventory_alerts"
        const val DRIVER_PERFORMANCE = "driver_performance"
        const val SHIPPER_PERFORMANCE = "shipper_performance"
        const val EXPORT_SHEET = "export_sheet"

        /**
         * 通用「读列表」工具：把系统里**所有只读列表**都开放给 AI（36 个端点，见 [AiReadCatalog]）。
         *
         * 为什么最后加的是它：前面 5 个工具是"某个问题的专用路径"，覆盖不了用户随口问的
         * 「账号列表里有哪些批发商」「操作日志里今天谁改了订单」这类问题。与其一个个补工具，
         * 不如给一条**受白名单约束的通用通道**——模型只在编译期定死的 36 条里选。
         */
        const val READ_DATA = "read_data"

        /**
         * 「记住」：把用户明确要求记住的一条事实，存进**本机**长期记忆。
         *
         * ### 为什么它是唯一一个"写"工具，以及为什么这不违背"首阶段纯只读"
         * 首阶段红线的原话是「**物理上无写能力**」，防的是"AI 改了业务数据"（下单/派单/改价/删除）。
         * 这一个不碰后端一个字节——它写的是 App 私有目录里的 `ai_memory.json`，
         * 而且那份内容**用户能在设置页逐条看见、改、删**。
         *
         * 换句话说：它改的是"AI 自己的笔记本"，不是"你家的账本"。
         * 这条区分写在 `_check_ai_guardrails.py` 的 §2 里，改工具集时那条断言会一起红。
         */
        const val REMEMBER = "remember"

        /**
         * 「写操作」：**申请**执行一个会改动业务数据的操作（记支出、账本记一笔、消息标已读）。
         *
         * ### 它和 [REMEMBER] 的区别（这是本工具集里最重要的两句话）
         * - `remember` 改的是"**AI 自己的笔记本**"：写本机私有目录、用户能逐条看见改删、不出手机。
         * - `preview_write` 改的是"**你家的账本**"：真的会进后端、进报表、被别的同事看到。
         *
         * 所以它**不是**一个能自己完成的工具：调用它只产生一张确认卡，
         * 必须由**用户在界面上点确认**才会落库（见 [AiWriteService] / [AiWritePreviewStore]）。
         * 模型的调用路径里**没有**"执行"这一步——不是靠约定，是那条路不存在。
         *
         * 默认**关闭**（见 [AiKeyStore.OPT_IN_TOOLS]）：老用户升级后不会突然多出一个能改数据的工具，
         * 想用的人自己去设置页打开。这是这套功能唯一一次"故意增加摩擦"的地方，且只增加一次。
         */
        const val PREVIEW_WRITE = "preview_write"

        /**
         * `preview_write` 成功申请到一张卡时，返回里的 `status` 值。
         *
         * **为什么它是一个常量而不是两处字面量**：这个值有两个读者——
         * ① [summarize]（决定工具痕迹显示"等用户确认"还是"完成"）；
         * ② [AiAgentLoop]（数这一轮到底发出去几张卡，用来拦"说了卡却没有卡"，见 [AiCardClaim]）。
         * 任何一处写错字面量，对应那条保证就**静默失效**（不报错、只是不再生效），
         * 所以只允许有一份定义。
         */
        const val CARD_OFFERED_STATUS = "awaiting_user_confirmation"

        /** 顺序 = 设置页里的显示顺序（查询在前、操作在后）。 */
        val ALL = listOf(
            SEARCH_SHIPPER,
            INVENTORY_ALERTS,
            DRIVER_PERFORMANCE,
            SHIPPER_PERFORMANCE,
            READ_DATA,
            EXPORT_SHEET,
            REMEMBER,
            PREVIEW_WRITE,
        )

        /**
         * 工具分组：设置页按这个分两栏渲染。
         *
         * 为什么必须分：`preview_write` 一上，工具列表里就同时存在"只看"和"会改"两类。
         * 混在一起排，用户扫一眼开关列表根本分不出哪个会动数据——而这一栏恰恰是
         * 他最需要一眼看明白的地方。
         */
        private val GROUPS: Map<String, Group> = mapOf(
            SEARCH_SHIPPER to Group.QUERY,
            INVENTORY_ALERTS to Group.QUERY,
            DRIVER_PERFORMANCE to Group.QUERY,
            SHIPPER_PERFORMANCE to Group.QUERY,
            READ_DATA to Group.QUERY,
            EXPORT_SHEET to Group.QUERY,
            REMEMBER to Group.OPERATE,
            PREVIEW_WRITE to Group.OPERATE,
        )

        fun groupOf(name: String): Group = GROUPS[name] ?: Group.QUERY

        /**
         * **每个角色能用的工具**（白名单，只此一处）。
         *
         * ### 为什么必须有（v3.28 真机实测）
         * 这一层原来**没有按角色裁**：`read_data`/`preview_write` 的说明是按角色生成的，
         * 但四个"专门工具"（找人/库存预警/司机跑车统计/货主统计）和"出表格"是静态的，
         * **谁登录都能看到**。后果很具体——货主问"你能做什么"，它照着工具清单念，
         * 于是把「库存预警」「司机绩效」说成自己能做；被追问时它真去调了，后端 403，
         * 它只能回一句"没有权限"。用户的原话是「你那个系统提示词没写好、没有分开」，
         * 但根子在这层：**提示词只是照着工具清单说话**。
         *
         * 判据和写侧白名单同一条：漏标 = 少给一个工具（还能补），
         * 反过来（默认全给）一旦漏标就是**越权**——所以这里也是白名单 + fail-closed。
         */
        val ROLE_TOOLS: Map<AiRole, Set<String>> = mapOf(
            // 管理员：全部
            AiRole.DISPATCHER to ALL.toSet(),
            // 货主：只留他能用的。四个专门工具和"出表格"都是派单员视角
            // （`search_shipper`=找人、`inventory_alerts`=库存预警、`driver_performance`=司机跑车统计、
            //  `shipper_performance`=货主统计、`export_sheet`=报表中心导出，后端全是 STATS_READ/派单员权限）。
            AiRole.SHIPPER to setOf(READ_DATA, REMEMBER, PREVIEW_WRITE),
        )

        /** 这个角色能用的工具名。**认不出角色 = 一个都不给**（fail-closed）。 */
        fun toolsFor(role: AiRole?): List<String> {
            val allowed = ROLE_TOOLS[role] ?: return emptyList()
            return ALL.filter { it in allowed }
        }

        /** 模型不给 `limit` 时的条数。**问"多少单/前几名"这类默认够用**，用户要"全部"时它自己会调大。 */
        const val DEFAULT_ROWS = 20

        /**
         * 一次最多给模型几行。
         *
         * ⚠️ **原来写的是 50，那是个真 bug**（2026-09-17 用户实机发现：「他很多名单没有拉全没拉够」）。
         * 库里实际有 97 个货主、62 个司机、161 个账号、38 个商品——50 的上限意味着
         * **"列出全部货主"这件事在物理上做不到**，模型只能答"只看了前 50 个"。
         *
         * 更糟的是当时的实现**把后端已经返回的行直接丢掉**（`rows.take(limit)`）：
         * 后端明明给了 97 行，我们只喂 20 行给模型，还告诉它"被截断了"。
         *
         * 200 是按"主数据名单"的规模定的（人/商品/客户/地址这几类），
         * 实测最大的账号表 161 行也在内。订单/流水这类会到几百上千行的，
         * 本来也不该整张铺给用户看——那时宁可如实说覆盖范围。
         */
        const val MAX_ROWS = 200

        /** 名字缺失时的中性称呼（绝不回落成编号）。见 [AiRowShaper]。 */
        const val UNNAMED = AiRowShaper.UNNAMED

        private val EXPORT_KINDS = listOf("turnover", "products", "drivers", "customers", "finance", "audit")
        private val EXPORT_MODES = listOf("day", "week", "month")

        /** 设置页用的中文短名。 */
        private val TITLES = mapOf(
            SEARCH_SHIPPER to "查货主",
            INVENTORY_ALERTS to "库存报警",
            DRIVER_PERFORMANCE to "司机跑货统计",
            SHIPPER_PERFORMANCE to "货主下单排行",
            READ_DATA to "读所有列表",
            EXPORT_SHEET to "导出报表",
            REMEMBER to "记住一件事",
            PREVIEW_WRITE to "改数据（需你确认）",
        )

        /** 设置页用的一句话说明（比喂给模型的 description 短）。 */
        private val HINTS = mapOf(
            SEARCH_SHIPPER to "按姓名或手机号找货主，返回姓名、手机号、是否批发商",
            INVENTORY_ALERTS to "列出库存已达报警阈值的商品",
            DRIVER_PERFORMANCE to "某时间段司机完成单量、准时率、待结运费",
            SHIPPER_PERFORMANCE to "某时间段货主下单量与金额排行",
            READ_DATA to "系统里所有只读列表（账号、商品、报表、账本、日志…），按模块可在下面逐项开关",
            EXPORT_SHEET to "生成营业/商品/司机/客户/财务/审计 Excel",
            REMEMBER to "你说「记住…」时，把这句话存到本机，以后提问自动带上（可在下面查看和删除）",
            // ⚠️ 设置页这两行是用普通 Text() 渲染的，**不解析 Markdown**。
            // 写 `**加粗**` 只会在屏幕上显示成一堆星号（v3.7 真机实测踩过）。
            // 要点醒目就换措辞（用「」把关键词框出来），不要用 Markdown 记号。
            PREVIEW_WRITE to "记支出、账本记一笔、消息标已读。AI 只会生成一张确认卡，必须你点确认才真的写",
        )

        /**
         * `preview_write` 的工具说明与参数说明。
         *
         * 抽成常量是因为这个工具的 spec 是**现拼的**（说明里的动作清单按角色裁剪，
         * 见 `AiTools.previewWriteSpec`），不能再从静态 `SCHEMAS` 里取。
         * 但文案只能有一份——两份一定会漂移，而漂移的表现是"模型按旧说明传参、代码说不认识"。
         */
        val DESCRIPTION_PREVIEW_WRITE: String get() = DESCRIPTIONS.getValue(PREVIEW_WRITE)

        val PARAMS_HINT: String =
            "这个操作的参数。键名必须**逐字**照抄上面清单里该操作的参数名" +
                "（例如要 exp_date，写成 date 就会报错）。值一般是字符串或数字。\n" +
                "⛔ 参数里**只许出现名字**（司机姓名、车牌号、货主名、商品名、挂账单位名），" +
                "绝不要传任何编号——编号你也拿不到，系统会自己按名字去找。\n" +
                "⚠️ 数组只在这两处出现：`orders.create` 的 `lines`（下单的商品明细）与 " +
                "`orders.return` 的 `lines`（退货明细），" +
                "形如 [{\"product\":\"红富士苹果\",\"quantity\":3,\"unit_price\":5.5}]（最多 10 行）。\n" +
                "⛔ 这两个 `lines` **必须真的是数组**，不许把明细拼成一段文字（写成字符串会被拒绝，" +
                "而退货那处历史上会被静默当成「整单退货」）。\n" +
                "⚠️ 操作订单的动作（`order` 参数）要传**完整订单号**（形如 SOTEST2026091100230）；" +
                "不确定是哪一单就先查询，不要凭印象编一个单号。\n" +
                "⚡ **一次改多条（批量捷径）**：用户一次说了要改/要建好几条时（**范围由他定，没有条数上限**），" +
                "**不要一条一条地调用同一个操作** —— 把这个操作只调一次，`items` 传一个数组：" +
                "params={\"items\":[{\"product\":\"甲\",\"price\":10},{\"product\":\"乙\",\"price\":20}]}。" +
                "数组里每一项的键名与这个操作的参数名**完全一样**；系统会把它们合成**一张卡**列给用户，" +
                "他确认一次就全部执行（逐条汇报哪几条成了、哪几条没成）。\n" +
                "  · 一次调用只放**同一个操作**；不同操作各发一次。\n" +
                "  · 用户说的范围大（「把所有商品的售价改成 10 元」）时，" +
                "**先把名册完整查一遍**再发，按查到的清单逐条写，不要自己估一个条数；" +
                "总数要在回复里说清楚（卡片上也会逐条列出）。\n" +
                "  · 只有一条时直接用普通参数，不要套 `items`。"
        fun titleOf(name: String): String = TITLES[name] ?: name
        fun hintOf(name: String): String = HINTS[name] ?: ""

        /**
         * 设置页渲染用：一个工具一条（带分组，见 [Group]）。
         *
         * 设置页的工具开关清单。**也要按角色裁**：
         * 给货主列一个"库存预警"开关，他打开了却永远不生效——
         * 那就是"看起来有、其实没有"，和工具层没裁是同一个 bug 的另一半。
         *
         * ⚠️ `preview_write` 那句说明**必须算出来**，不能写死动作名：写死的版本
         * （「记支出、账本记一笔、消息标已读」）在派单员这边早就不是事实了——
         * v3.21 之后他能申请的动作有七十多个、覆盖十来个域，而设置页还只列着三个。
         * 这类"能力声明过期"的后果和提示词写歪一样：用户以为它不会，就不去用。
         */
        fun settingsItems(actor: AiActor? = AiActor.byRole(AiRole.DISPATCHER)): List<ToolSetting> =
            toolsFor(actor?.role).map { name ->
                ToolSetting(
                    name = name,
                    title = titleOf(name),
                    hint = if (name == PREVIEW_WRITE) previewWriteHint(actor) else hintOf(name),
                    group = groupOf(name),
                )
            }

        /** 一句话说清"它能申请哪些改动"，域名单从动作表算（和提示词同源）。 */
        private fun previewWriteHint(actor: AiActor?): String {
            val groups = AiWrites.forModel(actor).map { it.group }.distinct()
            val what = if (groups.isEmpty()) {
                "当前角色没有任何可申请的改动"
            } else {
                "可申请：" + groups.joinToString("、")
            }
            return "$what。AI 只会生成一张确认卡，必须你点确认才真的写"
        }

        private fun specOf(name: String): ToolSpec = ToolSpec(
            type = "function",
            function = FunctionSpec(
                name = name,
                description = DESCRIPTIONS.getValue(name),
                parameters = schemas().getValue(name),
            ),
        )

        private fun schemas(): Map<String, JsonObject> = SCHEMAS

        private val SCHEMAS: Map<String, JsonObject> by lazy {
            mapOf(
                SEARCH_SHIPPER to buildJsonObject {
                    put("type", "object")
                    putJsonObject("properties") {
                        putJsonObject("query") {
                            put("type", "string")
                            put("description", "货主姓名或手机号，可以只写其中一段（如「张」「1380000」）")
                        }
                    }
                    putJsonArray("required") { add(JsonPrimitive("query")) }
                },
                INVENTORY_ALERTS to buildJsonObject {
                    put("type", "object")
                    putJsonObject("properties") {
                        putJsonObject("limit") {
                            put("type", "integer")
                            put("description", "最多返回几条，默认 $DEFAULT_ROWS，上限 $MAX_ROWS。" +
                                "⚠️ 用户要「全部/所有/名单」时必须**一次设够**（例如 $MAX_ROWS），" +
                                "不要只给一部分再让他「说一声继续」——他自己取不了，只能再问一遍")
                        }
                    }
                    putJsonArray("required") { }
                },
                DRIVER_PERFORMANCE to buildJsonObject {
                    put("type", "object")
                    putJsonObject("properties") {
                        putJsonObject("date_from") {
                            put("type", "string")
                            put("description", "起始日期 YYYY-MM-DD；不填默认最近 7 天")
                        }
                        putJsonObject("date_to") {
                            put("type", "string")
                            put("description", "结束日期 YYYY-MM-DD；不填默认今天")
                        }
                        putJsonObject("limit") {
                            put("type", "integer")
                            put("description", "最多返回几个司机，默认 $DEFAULT_ROWS，上限 $MAX_ROWS")
                        }
                    }
                    putJsonArray("required") { }
                },
                SHIPPER_PERFORMANCE to buildJsonObject {
                    put("type", "object")
                    putJsonObject("properties") {
                        putJsonObject("date_from") {
                            put("type", "string")
                            put("description", "起始日期 YYYY-MM-DD；不填默认最近 7 天")
                        }
                        putJsonObject("date_to") {
                            put("type", "string")
                            put("description", "结束日期 YYYY-MM-DD；不填默认今天")
                        }
                        putJsonObject("limit") {
                            put("type", "integer")
                            put("description", "最多返回几个货主，默认 $DEFAULT_ROWS，上限 $MAX_ROWS")
                        }
                    }
                    putJsonArray("required") { }
                },
                EXPORT_SHEET to buildJsonObject {
                    put("type", "object")
                    putJsonObject("properties") {
                        putJsonObject("kind") {
                            put("type", "string")
                            put("description", "导出哪张表：turnover=营业纵览，products=商品经营，drivers=司机绩效，customers=客户经营，finance=财务，audit=异常审计")
                            putJsonArray("enum") { EXPORT_KINDS.forEach { add(JsonPrimitive(it)) } }
                        }
                        putJsonObject("mode") {
                            put("type", "string")
                            put("description", "统计粒度：day=按日，week=按周，month=按月（默认 day）")
                            putJsonArray("enum") { EXPORT_MODES.forEach { add(JsonPrimitive(it)) } }
                        }
                        putJsonObject("date") {
                            put("type", "string")
                            put("description", "锚点日期 YYYY-MM-DD（决定导出哪一个统计周期）；不填默认今天")
                        }
                        putJsonObject("date_from") {
                            put("type", "string")
                            put("description", "起止日期 YYYY-MM-DD（drivers/customers/finance/audit 四类可用，优先于 mode+date）")
                        }
                        putJsonObject("date_to") {
                            put("type", "string")
                            put("description", "结束日期 YYYY-MM-DD，与 date_from 配对使用")
                        }
                    }
                    putJsonArray("required") { add(JsonPrimitive("kind")) }
                },
                // ⛔ `read_data` **刻意不在这张表里**（2026-09-21 删掉了这一份）。
                //    它的 action 清单按角色裁（见 [AiTools.readDataSpec]），而这张静态表在
                //    companion 里**看不到实例上的角色** —— `specs` 里 `READ_DATA` 也从来不落到
                //    `specOf` 上，于是这份 43 行的定义**一个读者都没有**。
                //    留着它的唯一效果是：改参数时多一个"看起来也该改"的地方
                //    （`readDataSpec` 那句注释当年就写着"参数部分与静态那份一致"）。
                //    红线 `_check_ai_guardrails.py` 盯着它不许回来。
                REMEMBER to buildJsonObject {
                    put("type", "object")
                    putJsonObject("properties") {
                        putJsonObject("subject") {
                            put("type", "string")
                            put("description", "这条记忆**关于谁**：货主名 / 司机名 / 商品名（用用户平时叫的名字），" +
                                "或者「${AiMemories.SUBJECT_GLOBAL}」（表示这是对**你回答方式**的偏好，比如「回答简短点」）")
                        }
                        putJsonObject("fact") {
                            put("type", "string")
                            put("description", "要记住的**那一句话**（上限 ${AiMemories.MAX_FACT_CHARS} 字）。" +
                                "只写以后还用得上的稳定信息；**不要写金额、单量、订单号**这类每次都能查到的结果。")
                        }
                    }
                    putJsonArray("required") {
                        add(JsonPrimitive("subject"))
                        add(JsonPrimitive("fact"))
                    }
                },
            )
        }

        private val DESCRIPTIONS = mapOf(
            SEARCH_SHIPPER to
                "按姓名或手机号查找货主，返回姓名、手机号、是否批发商（高级货主）、账号是否启用。\n" +
                "什么时候用：用户提到某个货主（人名/手机号）而你需要确认这位货主是谁、电话是多少。\n" +
                "只返回 role=shipper 的账号，批发商（高级货主）也在其中，用 is_member 区分。\n" +
                "注意：必须给一段姓名或手机号片段，不能空查；返回值里没有账号编号，你也不要提到编号。",
            INVENTORY_ALERTS to
                "列出库存已经到达报警阈值的商品（阈值>0 且 库存≤阈值），含当前库存、单位、阈值、在途占用量。\n" +
                "什么时候用：用户问「哪些货快没了」「需要补货的商品」「库存够不够」。\n" +
                "不含成本价，也不含任何金额。",
            DRIVER_PERFORMANCE to
                "按时间段统计每个司机的跑货情况：完成单量、准时率、平均送达时长、拍照上传率、计费方式（件/工资）、待结运费。\n" +
                "什么时候用：用户问「这周谁跑得最多」「司机准时率」「还欠司机多少运费」。\n" +
                "记得把日期换算成 YYYY-MM-DD 再传（例如「上周」= 上周一到上周日）。",
            SHIPPER_PERFORMANCE to
                "按时间段统计各货主的下单量与金额排行。\n" +
                "什么时候用：用户问「哪个货主下单最多」「货主排行」「客户贡献」。\n" +
                "只返回汇总排行，不含成本与毛利。",
            READ_DATA to
                "【通用读列表】读取系统里任意一张只读列表或查询（订单、商品、库存、账目、" +
                "人员与账号、报表与统计、消息与日志、地址与联系人……）。\n" +
                "⛔ **有哪些、分别读得到什么，一律以 action 参数的说明为准** —— 那份清单由代码" +
                "**按你的角色**生成，永远和实际情况一致（这里不再抄一份：抄的那份曾经写着「共 36 张」，" +
                "而实际上派单员 53 张、货主 16 张，且抄的表名里有一半货主根本读不到）。\n" +
                "什么时候用：用户问的事情在 action 清单里，而你没有更专用的工具时。\n" +
                "使用要点：\n" +
                "1. action 必须从清单里**原样照抄**（写成 模块.动作）；\n" +
                "2. 要筛具体的人/商品，用 name 传**名字**（如 name=城东水果批发）；" +
                "**绝不要**传编号，你也拿不到编号；\n" +
                "3. 时间范围用 from / to（YYYY-MM-DD）；接口只支持按月时会自动对上月份；\n" +
                "4. 返回里如果出现 ignored_filters 或 assumed_filters，说明有的条件没生效、" +
                "有的是工具替你补的默认值——**回答里必须说明你实际按什么范围统计**；\n" +
                "5. 返回值里没有账号编号、也没有成本与毛利，你也不要试图去猜。",
            EXPORT_SHEET to
                "把报表导出成 Excel 文件（在后端生成）。\n" +
                "什么时候用：用户明确说「导出」「下载表格」「给我一份 Excel」。\n" +
                "说明：本工具只触发导出并告知用户去「报表中心」查看/下载，不返回表格内容；" +
                "如果用户只是要看数字，请改用其它查询工具，不要用本工具。",
            REMEMBER to
                "把用户**明确要求你记住**的一条事实，存进本机长期记忆（下次提问会自动带上）。\n" +
                "什么时候用：**只在用户明确说了**「记住…」「以后都…」「下次别忘了…」这类话时调用。\n" +
                "⛔ **严禁自己判断「这条看起来有用」就调用**——用户没让你记，你记了就是擅自改变你以后的行为。\n" +
                "⛔ **严禁把金额、单量、订单号、库存数**这类查得到的结果存进去——每次都能查到，存了只会过期。\n" +
                "✅ 该存的是**稳定的、问不到的**：习惯怎么结算、平时怎么称呼、偏爱哪种规格、" +
                "某个地址导航会错要走旁边、对回答方式的偏好（这类 subject 填「${AiMemories.SUBJECT_GLOBAL}」）。\n" +
                "一次只存**一条**事实；同一件事一次说完，不要拆成多次调用。\n" +
                "存完要如实告诉用户存了什么，以及他可以在「AI 助手设置 → 记忆」里查看或删掉。",
            PREVIEW_WRITE to
                "【改数据】申请执行一个会**改动业务数据**的操作。" +
                "**能做哪些、怎么分组、每个动作要什么参数，全部以 action 参数的说明为准**" +
                "——那份清单由代码**按你的角色**生成，永远和实际情况一致。\n" +
                "（这里**不再抄一份域清单**：抄的那份列了七个域，而其中五个货主一个动作都没有，" +
                "于是货主问「你能改什么」会被告知能改库存与账号。）\n" +
                "清单里没有的操作就是做不了；有几类**永远**不会有：登录/注册、要上传文件的" +
                "（送达照片/商品图片/地址图片）、司机端专属动作（确认接单、完成送达）。\n" +
                "⛔ **这不是一个能自己做完的工具。** 调用它只是**把一张确认卡显示给用户**，" +
                "必须等用户在聊天页上点「确认」才会真正写进系统。\n" +
                "所以，调用前先问自己三件事：\n" +
                "1. 用户**明确要求**做这件事了吗？——没要求就不要调。\n" +
                "2. 必填参数**都是用户说过的**吗？没说的先问，**不要猜、不要替他填默认值**。" +
                "尤其这几样：派给谁、操作哪一单、下什么货、多少钱、挂到哪个单位。" +
                "猜错的后果不是一条错数据——是**一个司机白跑一趟、或者钱记到了别人头上**。\n" +
                "3. 涉及某个货主/司机/商品/订单时，你确认过它存在吗？不确定就先用查询工具查一遍。\n" +
                "调用之后的说法：\n" +
                "✅「确认卡发给你了，点一下「确认」就生效」\n" +
                "⛔「已经派好了」「已经撤了」——**你还没有**，写没写取决于用户点不点。\n" +
                "其它要点：\n" +
                "- 一次只申请一件事；同一件事**不要连续调用两次**，用户会看到两张一样的卡。\n" +
                "- 返回 error 时照实告诉用户哪里不对。如果返回里带 candidates（名字对上了好几个人/好几单），" +
                "就问他到底是哪一个，**绝对不要自己挑一个**。\n" +
                "- 参数里只传**名字**（司机姓名、车牌号、货主名、商品名、挂账单位名）；" +
                "传编号既没用也不会被接受。\n" +
                "- 钱要如实：金额只传数字，别自作主张四舍五入、别把「大概 300」写成 300 却不说。",
        )
    }
}

/** 设置页渲染一个工具开关需要的四样东西。 */
data class ToolSetting(
    val name: String,
    val title: String,
    val hint: String,
    /** 查询类 / 操作类，见 [AiTools.Group]。设置页按它分栏。 */
    val group: AiTools.Group = AiTools.Group.QUERY,
)

/** 工具参数不合法（缺字段 / 格式错）——会被转成 {"error": "..."} 还给模型，让它自己改。 */
private class ToolArgException(message: String) : Exception(message)
