package com.tapmoay.sorders.ai

import com.tapmoay.sorders.data.repo.AppRepository
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.putJsonObject
import java.time.LocalDate
import java.time.format.DateTimeParseException

/**
 * 「读列表」的**计划**：把模型给的一把扁平参数，算成一次具体请求（路径 + 已过滤的查询参数）。
 *
 * 为什么把"算"和"发"分开：[plan] 是纯函数，可以**不联网、不起 Retrofit** 直接单测。
 * 而这里恰恰是最容易错的地方——参数名、别名、日期补齐、编号解析，任何一处算错，
 * 用户看到的就是"查不到"，而模型会据此编出一个错误结论。
 */
object AiReadPlanner {

    /** 模型可以填的扁平参数（工具 schema 与这里必须一致）。 */
    const val A_NAME = "name"
    const val A_Q = "q"
    const val A_FROM = "from"
    const val A_TO = "to"
    const val A_STATUS = "status"
    const val A_LIMIT = "limit"
    const val A_EXTRA = "extra"

    /** 需要按名字解析成编号的筛选条件。 */
    data class NameNeed(val param: String, val kind: IdKind, val name: String)

    /** 编号的语义（决定用什么接口把名字换成编号）。 */
    enum class IdKind { SHIPPER, DRIVER, USER, CUSTOMER, PRODUCT, PARTY, ORDER, UNKNOWN }

    data class Plan(
        val action: ReadAction,
        val query: LinkedHashMap<String, String>,
        /** 模型给了、但**这个接口不接受**的筛选条件。必须如实告诉模型，不能悄悄丢掉。 */
        val ignored: List<String>,
        /** 自动补上的必填参数（如必需的日期区间），会写进结果里让模型照实说明。 */
        val assumed: LinkedHashMap<String, String>,
        val nameNeed: NameNeed?,
        val limit: Int,
    )

    sealed interface Result {
        data class Ok(val plan: Plan) : Result
        /** 人话错误，直接还给模型让它自己改。 */
        data class Bad(val message: String) : Result
    }

    fun plan(actionKey: String, args: JsonObject, today: LocalDate): Result {
        val action = AiReadCatalog.find(actionKey)
            ?: return Result.Bad(
                "没有名为「$actionKey」的查询。可用的清单见本工具说明里的 action 取值，请照抄其中一个。",
            )
        val declared = action.params.associateBy { it.name }
        val query = LinkedHashMap<String, String>()
        val ignored = mutableListOf<String>()
        val assumed = LinkedHashMap<String, String>()

        fun str(key: String): String? =
            (args[key] as? JsonPrimitive)?.takeIf { it.isString }?.content?.trim()?.takeIf { it.isNotEmpty() }

        // ---- 通用关键词 ----
        str(A_Q)?.let { v ->
            val p = firstDeclared(declared, "q", "keyword", "search")
            if (p != null) query[p] = v else ignored += A_Q
        }

        // ---- 日期区间（各端点命名不统一：date_from / from；month 类只认到月）----
        val fromParam = firstDeclared(declared, "date_from", "from", "start_date")
        val toParam = firstDeclared(declared, "date_to", "to", "end_date")
        str(A_FROM)?.let { v ->
            when {
                fromParam != null -> query[fromParam] = v
                declared.containsKey("month") -> query["month"] = v.take(7)
                else -> ignored += A_FROM
            }
        }
        str(A_TO)?.let { v ->
            if (toParam != null) query[toParam] = v else if (!declared.containsKey("month")) ignored += A_TO
        }

        // ---- 状态 ----
        str(A_STATUS)?.let { v ->
            val p = firstDeclared(declared, "status", "state")
            if (p == null) {
                ignored += A_STATUS
            } else {
                val spec = declared[p]
                // ⚠️ 枚举取值必须**当场校验**（2026-09-19 审计）：目录里一直躺着 `enum`，但从没被用过。
                //    后果是模型顺着工具说明传 `status=PAID`（说明里举的例子，而 PAID 根本不是订单状态）
                //    → 后端 422 → `humanError` 把它翻成"该后端接口还没提供" → **模型告诉用户"这个功能没上线"**，
                //    而功能明明在、后端也已经给出了一句可照着改的中文。用户彻底放弃这条路。
                //    现在：取值不合法就在**计划阶段**回一句带合法取值的话，模型一次就能改对。
                val picked = spec?.enum?.firstOrNull { it.equals(v.trim(), ignoreCase = true) }
                when {
                    spec == null || spec.enum.isEmpty() -> query[p] = v
                    picked != null -> query[p] = picked      // 归一成后端认的那个大小写
                    else -> return Result.Bad(
                        "「$A_STATUS=$v」不是这个查询允许的取值。允许的有：" +
                            "${spec.enum.joinToString(" / ")}。" +
                            "请从里面挑一个（大小写不敏感）；如果用户没说要按状态筛，就别填这个参数。",
                    )
                }
            }
        }

        // ---- 额外筛选（JSON，键必须是这个接口声明的参数）----
        str(A_EXTRA)?.let { raw ->
            val obj = try {
                AiJson.parseObjectLenient(raw)
            } catch (e: Exception) {
                null
            }
            if (obj == null) {
                ignored += "$A_EXTRA（不是合法 JSON 对象）"
            } else {
                obj.forEach { (k, v) ->
                    val p = declared[k]
                    val text = (v as? JsonPrimitive)?.contentOrNullSafe()
                    when {
                        p == null -> ignored += k
                        // ⚠️ 编号类参数走 extra 是**硬错误**，不是"忽略"：
                        // 忽略的话这次查询会**不带这个筛选条件**照样跑，模型很容易把
                        // "全部商品/全部流水"当成"这个商品的"报给用户——那是最坏的一类错答案。
                        // 报错能让它改用 name（App 侧解析编号），一次就改对。
                        p.isId -> return Result.Bad(
                            "「$k」是编号类筛选条件，你不能填编号。请改用 $A_NAME 传**名字**" +
                                "（例如 $A_NAME=城东水果批发 / $A_NAME=金龙鱼调和油），工具会自己处理。",
                        )
                        text != null -> query[k] = text
                    }
                }
            }
        }

        // ---- 名字 → 编号（编号绝不经过模型的手）----
        var nameNeed: NameNeed? = null
        str(A_NAME)?.let { nm ->
            val idParams = action.params.filter { it.isId }
            when {
                idParams.size == 1 -> {
                    nameNeed = NameNeed(idParams[0].name, kindOf(idParams[0].name), nm)
                }
                idParams.isEmpty() -> {
                    // 这个接口没有编号类条件：名字就当成关键词/名称类参数用
                    val p = firstDeclared(declared, "q", "keyword", "temp_shipper_name", "product_name", "name")
                    if (p != null) query[p] = nm else ignored += "$A_NAME（这个查询不支持按名字筛选）"
                }
                else -> return Result.Bad(
                    "「${action.action}」有好几个编号类筛选条件（${idParams.joinToString("、") { it.name }}），" +
                        "没法只凭一个名字判断你要筛哪个。请用 $A_EXTRA 明确指定，或换成按关键词/日期的查询。",
                )
            }
        }

        // ---- 必填参数补齐：不补的话后端 422，用户只看到一句"参数不正确" ----
        action.params.filter { it.required }.forEach { p ->
            if (query.containsKey(p.name)) return@forEach
            val d = defaultFor(p, today) ?: return@forEach
            query[p.name] = d
            assumed[p.name] = d
        }

        val limit = ((args[A_LIMIT] as? JsonPrimitive)?.content?.toIntOrNull() ?: AiTools.DEFAULT_ROWS)
            .coerceIn(1, AiTools.MAX_ROWS)

        // ---- 把行数上限**传给后端**（2026-09-17 补）----
        // 不传的话后端按自己的默认截：`GET /users` 是 `limit=100`，
        // 于是"全部货主"永远拿不到 100 以上，而我们这边再怎么调大上限都没用。
        // 传下去是安全的：声明了 limit 的接口上限都比我们大（users le=500、cash-flows le=1000、
        // operation-logs le=1000、inventory le=500、orders le=5000），不会撞 422。
        //
        // ⚠️ 传的是 **limit + 1**（2026-09-19 审计抓到的真缺陷）：
        //    如果原样传 limit，后端会自己截到 limit 并返回**裸数组**（没有 total），
        //    于是下面 `rows.size > capped.size` 永远为假 → `truncated` 不置位 →
        //    模型把 200 条当成全量，答"共 200 单"（本机真量 790、生产更多，**没有任何告警**）。
        //    多要一行是"是否还有更多"的唯一可靠探针：后端多回一行 → 截断判据成立 → 如实告知。
        //    上限安全：我方 MAX_ROWS=200，+1 后 201 仍低于所有端点的 le。
        if (declared.containsKey(A_LIMIT)) query[A_LIMIT] = (limit + 1).toString()

        return Result.Ok(Plan(action, query, ignored, assumed, nameNeed, limit))
    }

    private fun firstDeclared(declared: Map<String, ReadParam>, vararg names: String): String? =
        names.firstOrNull { declared.containsKey(it) }

    /** 编号参数的语义（决定用什么接口把名字解析成编号）。 */
    fun kindOf(param: String): IdKind = when (param) {
        "shipper_id" -> IdKind.SHIPPER
        "driver_id" -> IdKind.DRIVER
        "operator_id", "user_id" -> IdKind.USER
        "customer_id" -> IdKind.CUSTOMER
        "product_id" -> IdKind.PRODUCT
        "party_id" -> IdKind.PARTY
        "order_id" -> IdKind.ORDER
        else -> IdKind.UNKNOWN
    }

    /**
     * 必填参数的默认值。**只给"没有合理默认就无法调用"的参数补**，
     * 可选参数一律不补——补了会**悄悄改变语义**（例如给「所有订单」补上本月区间，
     * 用户拿到的就不是他要的全部了）。
     */
    fun defaultFor(p: ReadParam, today: LocalDate): String? = when (p.name) {
        "date_from" -> today.withDayOfMonth(1).toString()
        "date_to" -> today.toString()
        "date" -> today.toString()
        "month" -> today.toString().take(7)
        "mode" -> p.enum.firstOrNull() ?: "day"
        "limit" -> AiTools.DEFAULT_ROWS.toString()
        else -> p.enum.firstOrNull()
    }

    /** 只接受合法日期，避免把「上周」这种词直接发给后端。 */
    fun parseDateOrNull(s: String?): LocalDate? = try {
        s?.let { LocalDate.parse(it.trim()) }
    } catch (e: DateTimeParseException) {
        null
    }
}

private fun JsonPrimitive.contentOrNullSafe(): String? =
    if (this is kotlinx.serialization.json.JsonNull) null else content.trim().takeIf { it.isNotEmpty() }

/** JSON 解析的小工具（宽松：允许模型多包一层引号或带前后空白）。 */
internal object AiJson {
    /** 自带一个 Json 实例，**不碰 `ApiClient.json`**：这样这个文件在纯 JVM 单测里也能直接用。 */
    private val JSON = kotlinx.serialization.json.Json {
        ignoreUnknownKeys = true
        isLenient = true
    }

    fun parseObjectLenient(raw: String): JsonObject? {
        val t = raw.trim().removeSurrounding("\"").replace("\\\"", "\"")
        return JSON.parseToJsonElement(t) as? JsonObject
    }
}

/**
 * 「读任意列表」的通用工具实现（工具名 `read_data`）。
 *
 * ### 为什么是"一个通用工具 + 白名单"而不是 36 个工具
 * 36 个工具定义会塞满每一次请求（每个都要名字、说明、参数 schema），而模型的选工具准确率
 * 会随工具数下降。做成一个工具 + `action` 枚举，规格是常量级，白名单也更好守。
 *
 * ### 这个类绝不做的三件事（本项目的红线）
 * 1. **不接受任意 URL**：路径只能从 [AiReadCatalog]（编译期生成的 36 条）里查出来；
 * 2. **不把编号给模型**：需要编号的筛选条件一律按**名字**在 App 侧解析（见 [resolveId]），
 *    返回体再过 [AiRowShaper] 剔一遍 `id` / `*_id`；
 * 3. **不悄悄改变语义**：模型给的筛选条件后端不认、或我们替它补了必填项，都要写进结果里。
 */
class AiReadService(
    private val repo: AppRepository,
    /**
     * 用户允许 AI 读的模块集合（设置页的开关，每次执行时现读）。
     *
     * 做成**回调**而不是构造时快照：设置页一改，下一次提问立刻生效，不用重启 App。
     */
    private val enabledModules: () -> Set<String> = { AiReadCatalog.modules().toSet() },
    /**
     * 允许把成本 / 毛利给模型看吗（设置页那个开关，默认**关**）。
     *
     * 与 [AiTools.allowCost] 同源（都读 `AiKeyStore::costVisible`）：读工具与通用读表
     * **两条路都要过同一道门** —— 只给一条路开口，另一条就成了绕过开关的后门。
     */
    private val allowCost: () -> Boolean = { false },
    /**
     * 当前登录角色（**读侧的门**，见 [AiReads]）。
     *
     * 默认给 null = 认不出角色就一张表都不给（fail-closed）。这里刻意**不**默认成派单员：
     * 让"忘了传角色"变成"读不到任何表"这种一眼能看出来的症状，而不是悄悄按派单员的权限跑。
     */
    private val roleProvider: () -> AiRole? = { null },
) {

    /**
     * @return 直接能喂给模型的 JSON 字符串（失败时是 `{"error":"人话"}`）。
     */
    suspend fun read(actionKey: String, args: JsonObject, today: LocalDate = LocalDate.now()): String {
        val action = AiReadCatalog.find(actionKey)
            ?: return err(
                "没有名为「$actionKey」的查询。请照抄工具说明里列出的 action 取值。",
            )
        val role = roleProvider()
        if (!AiReads.allows(role, action.action, enabledModules())) {
            // 这道门是给**说错话**兜底的：工具说明里已经按角色裁过清单，但模型可能凭上一轮
            // 的记忆写一个它这个角色查不了的 action。
            //
            // ⚠️ 措辞要**短**（用户原话：「涉及权限不够的话，不用说那么多，直接返回权限不够」）。
            //    这里以前是"「X」这个角色不能查（当前角色：shipper）。请如实告诉用户他这一步要去
            //    App 里做，不要换个写法再试"——模型会照着这段解释一大通，用户看到的是一篇作文。
            //    现在只给一句结论；后半句是给模型的**动作指令**，不是让他念的台词。
            return err("权限不够。告诉用户这个查不了，让他自己去 App 里对应的页面做；换个写法也一样不行。")
        }
        val module = action.action.substringBefore('.')
        if (module !in enabledModules()) {
            return err("这类数据被用户在设置里关掉了。一句话告诉用户，不要编造数据。")
        }

        val plan = when (val r = AiReadPlanner.plan(actionKey, args, today)) {
            is AiReadPlanner.Result.Bad -> return err(r.message)
            is AiReadPlanner.Result.Ok -> r.plan
        }

        // ---- 名字 → 编号：编号只在这一次 HTTP 里用一下，**不进结果、不进模型上下文** ----
        plan.nameNeed?.let { need ->
            // ⚠️ 解析失败**不许直接报错**（2026-09-19 审计）：这个接口同时声明了编号参数与 `q`
            //    （`orders.list_orders` 有 `shipper_id` 也有 `q`），而模型的 `name` 里既可能是人名、
            //    也可能是**单号**（工具说明里"订单号"就是明写的例子）。原来的行为是：
            //    货主问「帮我查 SO2026… 到哪了」→ 模型把单号填进 name → 拿它去调**只有派单员能调**
            //    的 `/users` → 403 → 工具把 403 翻成"权限不够" → 用户被告知自己看不了自己的单。
            //    现在：解析不出来（或无权解析）就**退化成关键词**（如果这个接口支持 q），
            //    并在 `assumed_filters` 里如实说明"按关键词匹配"；接口不支持关键词才报错。
            val id = runCatching { resolveId(need) }.getOrNull()
            val kw = plan.action.params
                .firstOrNull { it.name == AiReadPlanner.A_Q || it.name == "keyword" }
                ?.name
            if (id != null) {
                plan.query[need.param] = id.toString()
            } else if (kw != null) {
                plan.query[kw] = need.name
                plan.assumed[kw] = need.name
            } else {
                return err(
                    "没找到叫「${need.name}」的记录（${kindLabel(need.kind)}）。" +
                        "请先用找货主/查列表的工具确认准确名字，或改用关键词 ${AiReadPlanner.A_Q} 查。",
                )
            }
        }

        val path = plan.action.path.removePrefix("/api/v1/")
        val root = repo.rawGet(path, plan.query)

        return buildJsonObject {
            put("action", plan.action.action)
            put("what", plan.action.cn)
            putJsonObject("filters_used") { plan.query.forEach { (k, v) -> put(k, v) } }
            if (plan.ignored.isNotEmpty()) {
                putJsonArray("ignored_filters") { plan.ignored.forEach { add(JsonPrimitive(it)) } }
                put(
                    "ignored_note",
                    "上面这些筛选条件这个接口不支持，本次没有生效。如果结论依赖它们，请换个查询或如实说明。",
                )
            }
            if (plan.assumed.isNotEmpty()) {
                putJsonObject("assumed_filters") { plan.assumed.forEach { (k, v) -> put(k, v) } }
                put("assumed_note", "这些是必填项、你没给，工具按默认值补的。回答里请说明你按什么范围统计的。")
            }

            val rows = AiRowShaper.rowsOf(root)
            if (rows.isEmpty()) {
                // 不是列表（"还有几单"这类聚合值）：把对象本身抹平后给它
                val scalar = AiRowShaper.scalarView(root)
                if (scalar != null && scalar.isNotEmpty()) {
                    put("value", scalar)
                } else {
                    put("count", 0)
                    put("items", buildJsonArray { })
                }
                return@buildJsonObject
            }
            // 列表旁边那些**标量字段**必须一起给：后端常把 `total`（符合条件的总数）放在包装对象上，
            // 而我们只取数组的话它就被丢了。实测后果：用户问"这个月多少单"，
            // 模型只能看到被截断的 50 行、只能回答"只看了前 50 条，不敢给总数"——
            // 而总数其实一直在响应里，是我们把它扔了。
            AiRowShaper.scalarView(root)?.takeIf { it.isNotEmpty() }?.let { put("response_fields", it) }

            // ⚠️ 这里原来是 `rows.take(plan.limit)` ——**后端已经把全量给了，我们只喂前 limit 行**。
            //    实测后果（2026-09-17 用户报「名单没有拉全没拉够」）：库里 97 个货主，
            //    后端返回 97 行，模型只看到 20 行，还被告知"被截断了"，于是它只能答
            //    「只看了前 20 个，剩下的要接着看跟我说一声」——**而用户根本没法"接着看"**。
            val capped = rows.take(plan.limit)
            put("count", capped.size)
            put("total_returned_by_backend", rows.size)
            if (rows.size > capped.size) {
                put("truncated", true)
                put(
                    "truncated_note",
                    "这次只返回了前 ${capped.size} 条，后端一共给了 ${rows.size} 条。" +
                        "**不要把 ${capped.size} 条当成全部**：要么用更大的 limit 重查一次，要么如实说明覆盖范围。" +
                        "⛔ 不要让用户「说一声继续」——他自己取不了。",
                )
            }
            putJsonArray("items") {
                capped.forEach { add(AiRowShaper.shape(it, allowCost())) }
            }
        }.toString()
    }

    // ------------------------------------------------------------------ 内部

    private fun kindLabel(kind: AiReadPlanner.IdKind): String = when (kind) {
        AiReadPlanner.IdKind.SHIPPER -> "货主"
        AiReadPlanner.IdKind.DRIVER -> "司机"
        AiReadPlanner.IdKind.USER -> "账号"
        AiReadPlanner.IdKind.CUSTOMER -> "客户"
        AiReadPlanner.IdKind.PRODUCT -> "商品"
        AiReadPlanner.IdKind.PARTY -> "往来单位"
        AiReadPlanner.IdKind.ORDER -> "订单号"
        AiReadPlanner.IdKind.UNKNOWN -> "记录"
    }

    /**
     * 名字 → 编号。**只在这一个函数里，编号才短暂存在**，用完即弃。
     *
     * 为什么必须支持它：像「城东水果批发的账本」「金龙鱼调和油的库存流水」这类问题，
     * 后端接口只认编号。没有这一步，AI 就只能回答"我读不了"——而用户要的是结果。
     * 反过来，把编号给模型让它自己填，等于把"回答里不出现编号"这条红线交给运气。
     */
    private suspend fun resolveId(need: AiReadPlanner.NameNeed): Long? {
        val kw = need.name.lowercase()
        return when (need.kind) {
            AiReadPlanner.IdKind.SHIPPER,
            AiReadPlanner.IdKind.DRIVER,
            AiReadPlanner.IdKind.USER,
            AiReadPlanner.IdKind.PARTY,
            -> {
                val users = repo.searchUsers(need.name, limit = 50)
                val role = when (need.kind) {
                    AiReadPlanner.IdKind.SHIPPER -> "shipper"
                    AiReadPlanner.IdKind.DRIVER -> "driver"
                    else -> null
                }
                // ⚠️ 括号不能省：`a ?: b?.id` 会解析成 `a ?: (b?.id)`，
                // 那整个表达式的类型就变成 Any?（列表 或 Long），编译期直接报类型不匹配。
                (
                    users
                        .filter { role == null || it.role == role }
                        .firstOrNull { u ->
                            u.fullName.lowercase() == kw || u.username.lowercase() == kw || u.phone == need.name
                        }
                        ?: users.filter { role == null || it.role == role }
                            .firstOrNull { u ->
                                u.fullName.lowercase().contains(kw) || u.username.lowercase().contains(kw)
                            }
                    )?.id
            }
            AiReadPlanner.IdKind.CUSTOMER -> {
                val list = repo.customers(kind = null, q = need.name)
                (list.firstOrNull { it.name.lowercase() == kw }
                    ?: list.firstOrNull { it.name.lowercase().contains(kw) })?.id
            }
            AiReadPlanner.IdKind.PRODUCT -> {
                val list = repo.products(includeInactive = true)
                (list.firstOrNull { it.name.lowercase() == kw }
                    ?: list.firstOrNull { it.name.lowercase().contains(kw) })?.id
            }
            AiReadPlanner.IdKind.ORDER -> {
                // 订单号是**用户看得见**的编号（和内部主键不是一回事），所以可以按它反查
                val list = repo.orders(q = need.name)
                (list.firstOrNull { it.orderNo.equals(need.name, ignoreCase = true) }
                    ?: list.firstOrNull { it.orderNo.contains(need.name, ignoreCase = true) })?.id
            }
            AiReadPlanner.IdKind.UNKNOWN -> null
        }
    }

    private fun err(message: String): String =
        buildJsonObject { put("error", message) }.toString()
}
