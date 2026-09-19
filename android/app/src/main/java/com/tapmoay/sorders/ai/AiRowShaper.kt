package com.tapmoay.sorders.ai

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/**
 * 「后端返回的 JSON → 能喂给模型的 JSON」的唯一一道加工工序。
 *
 * ### 为什么单独抽出来
 * 这两条规矩是**本项目的红线**，而它们必须对**每一个**工具生效：
 * 1. **不许出现内部编号**（`id` / `*_id`）——用户看不懂，模型拿到就会写进回答（实测会附「（user_id 122）」）；
 * 2. **不许出现成本/毛利**（`cost*` / `profit` / `margin`）——只读不等于可以泄露成本价，
 *    回答会显示在聊天页、也可能被截图外发。
 *
 * 以前它们藏在 `AiTools` 的私有方法里。一旦新增一个工具（比如"读所有列表"的通用工具），
 * 就得把这段逻辑抄一遍——**抄的那份迟早会漏一个字段**，而漏的那次就是编号泄露到用户面前。
 * 所以改成：加工只有这一处，谁读后端数据谁都得过它。
 */
object AiRowShaper {

    /** 名字缺失时的中性称呼（**绝不回落成编号**）。 */
    const val UNNAMED = "未命名"

    /** `货主#122` / `司机 12` 这类「名称里嵌编号」的形状。 */
    private val HASH_ID_NAME = Regex("""^(货主|司机|客户|用户|临时货主|客户单位)\s*#?\s*\d+$""")

    /** 各端点里「名字」字段的键名（用于统一过 [safeName]）。 */
    private val NAME_KEYS = listOf(
        "name", "shipper_name", "driver_name", "customer_name", "temp_shipper_name",
        "full_name", "username", "party_name", "operator_name", "unit_name", "product_name",
    )

    /**
     * 宽松取出「行数组」时要**优先**试的键名（后端各端点的包装键不统一）。
     *
     * ⚠️ 这张表只是"优先顺序"，**不再是判据**（2026-09-19 审计抓到的真缺陷）：
     *    原来 [rowsOf] 只认这几个键，于是 `{"drivers": [...]}`（司机绩效 179 行）、
     *    `{"groups": [...]}`（运费结算 175 组）这类响应**整包认不出** → 掉进
     *    `AiReadService` 的 `rows.isEmpty()` 分支退化成 `drivers_count: 179`，
     *    模型拿到的是"有 179 个司机"而不是那 179 行，**而且没有任何标志说明数据被丢了**
     *    （连 `truncated` 都不置位）——用户问"哪个司机跑得最多"只能得到"查不到"。
     *    这已经是本项目第 6 次栽在"清单是手写的"上，所以判据改成机器认：
     *    先按这张表取（保证稳定），取不到就取响应里**第一个对象数组**。
     */
    private val ROW_ARRAY_KEYS = listOf("shippers", "items", "rows", "data", "list", "results", "records")

    /**
     * 这个字段能不能给模型看。**两类都要拦**：
     * 1. **内部主键**（`id` / `*_id`）：AI 的所有工具参数里都没有"编号"这一项（要编号的筛选条件一律按名字解析），
     *    所以编号对模型是纯粹的多余信息。**从源头不给，才是"回答里不可能出现编号"的唯一可靠保证**——
     *    靠提示词叮嘱是会漏的。
     * 2. **成本 / 毛利**：`cost*` / `profit` / `margin`，以及中文的成本/毛利。
     *    ⚠️ 这一类**可以由用户主动放开**（[allowCost]），见下面的说明。
     *
     * @param allowCost 用户是否打开了「允许 AI 查看成本与毛利」（`AiKeyStore::costVisible`，**默认关**）。
     *   ⛔ 默认必须是 `false`：成本价一旦进模型上下文，它就出现在聊天记录里、可能被截图外发 ——
     *   那是**用户的数据外发决定**，不该由一次 App 升级替他做。
     *   放开之后 AI 才能回答"这个商品成本多少 / 这个月毛利多少 / 这货成本怎么变的"，
     *   也才能申请改成本价与录进货价（那是用户 2026-09-19 明确要求的）。
     */
    fun isHiddenField(key: String, allowCost: Boolean = false): Boolean {
        val k = key.lowercase()
        if (k == "id" || k.endsWith("_id")) return true
        if (allowCost) return false
        return k.contains("cost") || k.contains("profit") || k.contains("margin") ||
            key.contains("成本") || key.contains("毛利")
    }

    /**
     * 后端在货主/司机**没有名字**时会退化成 `货主#122`，司机甚至直接拿 id 当名字
     * （见 `stats_service` 的 `du.full_name or du.phone or str(did)`）——那也是编号，得换掉。
     *
     * 判据刻意收窄：**只认「纯数字且很短」和「货主#数字」两种形状**。
     * 不能把「全是数字」一律当编号——后端拿手机号兜底当名字是常见情况（11 位），
     * 手机号对用户是有用信息，误杀反而更糟。
     */
    fun safeName(raw: String?): String {
        val s = raw?.trim().orEmpty()
        if (s.isEmpty()) return UNNAMED
        if (s.length <= 6 && s.all { it.isDigit() }) return UNNAMED
        if (HASH_ID_NAME.matches(s)) return UNNAMED
        return s
    }

    /** 递归剔除不该给模型的字段（判据见 [isHiddenField]）。 */
    fun stripSensitive(el: JsonElement, allowCost: Boolean = false): JsonElement = when (el) {
        is JsonObject -> JsonObject(
            el.entries.filter { !isHiddenField(it.key, allowCost) }
                .associate { it.key to stripSensitive(it.value, allowCost) },
        )
        is JsonArray -> JsonArray(el.map { stripSensitive(it, allowCost) })
        else -> el
    }

    /** 逐行抹平：保留顶层标量；嵌套对象展开一层（键名冲突时以先到者为准）；数组只记条数。 */
    fun flatten(row: JsonObject, allowCost: Boolean = false): JsonObject = JsonObject(
        buildMap {
            row.forEach { (k, v) ->
                if (isHiddenField(k, allowCost)) return@forEach
                when (v) {
                    is JsonPrimitive -> if (v !is JsonNull) put(k, v)
                    is JsonObject -> v.forEach { (k2, v2) ->
                        if (!isHiddenField(k2, allowCost) && v2 is JsonPrimitive && v2 !is JsonNull) put(k2, v2)
                    }
                    is JsonArray -> put(k + "_count", JsonPrimitive(v.size))
                }
            }
        },
    )

    /** 先剔除不该给模型的字段（成本 + 内部编号）再抹平（类型上保证结果仍是对象）。 */
    fun stripAndFlatten(row: JsonObject, allowCost: Boolean = false): JsonObject =
        flatten((stripSensitive(row, allowCost) as? JsonObject) ?: row, allowCost)

    /** 把行里「名字」类字段统一过一遍 [safeName]（各端点里名字的键名不统一，所以给一组）。 */
    fun normalizeNames(row: JsonObject): JsonObject = JsonObject(
        row.mapValues { (k, v) ->
            if (k in NAME_KEYS && v is JsonPrimitive && v !is JsonNull) {
                JsonPrimitive(safeName(v.contentOrNull))
            } else {
                v
            }
        },
    )

    /** 一行完整加工：剔字段 → 抹平 → 名字兜底。所有工具都该走这个。 */
    fun shape(row: JsonObject, allowCost: Boolean = false): JsonObject =
        normalizeNames(stripAndFlatten(row, allowCost))

    /**
     * 宽松取出「行数组」：裸数组；对象则先试已知包装键，**再退到"第一个对象数组"**。
     *
     * 第二条兜底是关键：它让"后端换了个包装键"（`drivers` / `groups` / `categories`…）
     * 不再变成"模型一行都拿不到"。判据只看形状（元素是对象），不看名字。
     */
    fun rowsOf(root: JsonElement): List<JsonObject> = when (root) {
        is JsonArray -> root.filterIsInstance<JsonObject>()
        is JsonObject -> (knownRows(root) ?: firstObjectArray(root)).orEmpty()
        else -> emptyList()
    }

    private fun knownRows(root: JsonObject): List<JsonObject>? =
        ROW_ARRAY_KEYS.firstNotNullOfOrNull { k ->
            (root[k] as? JsonArray)?.filterIsInstance<JsonObject>()?.takeIf { it.isNotEmpty() }
        }

    private fun firstObjectArray(root: JsonObject): List<JsonObject>? =
        root.values.filterIsInstance<JsonArray>()
            .firstNotNullOfOrNull { arr ->
                val objs = arr.filterIsInstance<JsonObject>()
                // 只有"确实装着对象"的数组才算行数组：全空数组、纯标量数组都不算
                // （否则 `{"categories": ["水果","蔬菜"]}` 会被当成两行空数据）。
                objs.takeIf { it.isNotEmpty() && it.size == arr.size }
            }

    /**
     * 这个响应里是不是**根本没有列表**（只有一个聚合对象，如"待派单还有几单"、
     * "某货主的商品分布"）。这时不该硬套行数组，而应把这个对象本身抹平后返回。
     */
    fun scalarView(root: JsonElement): JsonObject? {
        val obj = root as? JsonObject ?: return null
        return stripAndFlatten(obj).takeIf { it.isNotEmpty() }
    }
}
