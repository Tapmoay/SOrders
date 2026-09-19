package com.tapmoay.sorders.ai

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.math.BigDecimal
import java.math.RoundingMode
import java.time.LocalDate
import java.time.format.DateTimeParseException

/**
 * 参数不合法 → 被 [AiWriteService] 转成 [AiWriteOutcome.Rejected] 还给模型。
 *
 * @param candidates 名字对上了多个时的候选**名字**（绝不是编号）。会被原样搬到工具返回值的
 *   `candidates` 数组里，让模型照着去问用户。
 */
class AiWriteArgException(
    message: String,
    val candidates: List<String> = emptyList(),
) : Exception(message)

/**
 * 写操作的参数校验与**名字 → 编号**解析（所有动作共用）。
 *
 * ### 为什么这些必须是共享的一份
 * "金额上限""严格解析""日期格式"这些东西，一旦每个动作各写一遍，就一定会有一个动作
 * 忘了上限、或者猜了一个模糊匹配。**漏的那个就是把账记错的那个**，而且它不会报错。
 * 所以规则只有一处，新加动作时只允许选"用哪条"，不允许自己再写一条。
 */
object AiWriteArgs {

    /** 金额上限：100 万元。超过就当成"多打了零"，强制模型回去核对。 */
    val MAX_AMOUNT: BigDecimal = BigDecimal("1000000")

    const val MAX_QUANTITY = 100_000

    /** 备注/事由类文本的长度上限。 */
    const val MAX_TEXT_CHARS = 200

    /** 一次最多回几个候选（太多了模型会挑，太少了用户得重说）。 */
    const val MAX_CANDIDATES = 5

    // ------------------------------------------------------------------ 取值

    fun str(args: JsonObject, key: String): String? =
        (args[key] as? JsonPrimitive)?.contentOrNull?.trim()?.takeIf { it.isNotEmpty() }

    /** 必填字符串；缺了就抛（缺哪一条会写在错误里，模型据此去问用户）。 */
    fun required(args: JsonObject, key: String, cn: String): String =
        str(args, key) ?: throw AiWriteArgException("缺少 $key：$cn")

    /** 布尔参数：收 true/false、也收「是/否」「要/不要」。返回 null = 没填。 */
    fun parseBool(args: JsonObject, key: String): Boolean? {
        val raw = str(args, key)?.lowercase() ?: return null
        return when (raw) {
            "true", "1", "yes", "y", "是", "要", "收", "收现金" -> true
            "false", "0", "no", "n", "否", "不要", "不", "挂账" -> false
            else -> throw AiWriteArgException("$key 只能是 true/false（收到「$raw」）。")
        }
    }

    // ------------------------------------------------------------------ 校验

    /**
     * 金额解析。**比后端更严**，因为这里的输入是模型生成的文本。
     *
     * 容忍「300」「300.5」「1,200.50」「300元」「300块」；
     * 拒绝：非数字、负数、0（当 [mustPositive]）、以及**超过 [MAX_AMOUNT] 的数**。
     * 最后一条专防"多打了三个零"：模型把 300 写成 300000 时，用户扫一眼摘要很难发现，
     * 而在参数层直接拦掉，模型会拿到一句明确的错误并回去跟用户核对。
     */
    fun parseMoney(raw: String?, field: String, mustPositive: Boolean): BigDecimal {
        if (raw.isNullOrBlank()) throw AiWriteArgException("缺少 $field：金额是多少？")
        val cleaned = raw.trim()
            .replace(",", "").replace("，", "")
            .removeSuffix("元").removeSuffix("块").removeSuffix("人民币")
            .removePrefix("¥").removePrefix("￥").trim()
        val v = try {
            BigDecimal(cleaned)
        } catch (e: NumberFormatException) {
            throw AiWriteArgException("$field「$raw」不是数字。只传数字，不要带单位或文字。")
        }
        if (v.signum() < 0) throw AiWriteArgException("$field 不能是负数（收到 $raw）。")
        if (mustPositive && v.signum() == 0) throw AiWriteArgException("$field 必须大于 0（收到 $raw）。")
        if (v > MAX_AMOUNT) {
            throw AiWriteArgException(
                "$field 是 ${v.toPlainString()}，超过 ${MAX_AMOUNT.toPlainString()} 的上限。" +
                    "这个数看着像多打了几个零——先跟用户核对，不要直接记。",
            )
        }
        return v.setScale(2, RoundingMode.HALF_UP)
    }

    fun money(v: BigDecimal): String = v.setScale(2, RoundingMode.HALF_UP).toPlainString()

    fun parseQuantity(raw: String): Int {
        val v = raw.trim().removeSuffix("件").removeSuffix("个").trim().toIntOrNull()
            ?: throw AiWriteArgException("quantity「$raw」不是整数。")
        if (v < 1) throw AiWriteArgException("quantity 必须 ≥ 1（收到 $raw）。")
        if (v > MAX_QUANTITY) throw AiWriteArgException("quantity 是 $v，超过 $MAX_QUANTITY 的上限，请先核对。")
        return v
    }

    fun parseDate(raw: String?, field: String): LocalDate? {
        if (raw.isNullOrBlank()) return null
        return try {
            LocalDate.parse(raw.trim())
        } catch (e: DateTimeParseException) {
            throw AiWriteArgException("$field 必须是 YYYY-MM-DD（如 2026-09-15），收到「$raw」。")
        }
    }

    /**
     * 月份解析：收 `2026-09`、`2026-9`、`2026/9`、`2026年9月`，一律归一成**后端要的 `YYYY-MM`**。
     *
     * ### 为什么必须归一而不是"原样转发"
     * 每个月度接口（账单/结算/报表）的月份参数格式都不同：司机账单是 `pattern=r"^\d{4}-\d{2}$"`
     * （**两位月份**，`2026-9` 会被后端 422 拒掉）。模型从用户那句"九月"写出来的东西
     * 有可能是 `2026-9`、`9月`、甚至 `202609`——在这里归一，比让用户在确认卡上
     * 看到一个 422 要好；而且**卡片上写的月份就是真正发出去的月份**（同一个字符串）。
     *
     * 不给默认值：月份默认成"这个月"是最危险的一种默认——月末和月初的用户
     * 想要的根本不是同一个月，而账单**生成之后没有删除入口**。
     */
    fun parseMonth(raw: String?, field: String): String {
        if (raw.isNullOrBlank()) {
            throw AiWriteArgException("缺少 $field：是哪一个月？（YYYY-MM，例如 2026-09）")
        }
        val s = raw.trim()
            .replace("年", "-").replace("月", "")
            .replace("/", "-").replace(".", "-")
            .replace("月份", "").replace("份", "")
        val parts = s.split('-').filter { it.isNotBlank() }
        val y = parts.getOrNull(0)?.toIntOrNull()
        val m = parts.getOrNull(1)?.toIntOrNull()
        if (y == null || m == null || parts.size != 2 || y !in 2000..2100 || m !in 1..12) {
            throw AiWriteArgException(
                "$field「$raw」看不懂。请给一个年月（YYYY-MM，例如 2026-09）；" +
                    "**不要自己猜是哪个月**，不确定就问用户。",
            )
        }
        return "%04d-%02d".format(y, m)
    }

    /** 截断超长文本；**超了要报错而不是默默截断**——用户看到的摘要必须是他说的那句。 */
    fun text(raw: String?, field: String, max: Int = MAX_TEXT_CHARS): String {
        val t = raw?.trim().orEmpty()
        if (t.length > max) throw AiWriteArgException("$field 太长了（上限 $max 字），压成一句话。")
        return t
    }

    // --------------------------------------------------- 名字 → 编号（严格）

    /** 归一化名字：去空白 + 小写。只用于比较，不用于展示。 */
    fun norm(s: String): String =
        s.trim().replace(" ", "").replace("　", "").replace("\t", "").lowercase()

    /** 归一化车牌/单号：去空白与分隔符 + 大写。`sotest-2026 0911` 与 `SOTEST20260911` 视为同一个。 */
    fun normCode(s: String): String =
        s.trim().replace(" ", "").replace("　", "").replace("-", "").replace("·", "").uppercase()

    /**
     * **严格解析：只有唯一命中才返回。**
     *
     * ### 两轮匹配（顺序不能反）
     * 先找**完全相等**的（归一后），有就不再往下看；没有再退到"包含"。
     * 少了第一轮，"王建国"会同时命中"王建国"和"王建国明"——
     * 用户明明说得清清楚楚，却被要求消歧义。
     *
     * @param allowMissing false = 查不到就抛（默认）。**只有货主允许 true**
     *   （后端本来就有 `temp_shipper_name`，"来收一趟货、没建过档"是真实业务）。
     * @param code true = 车牌/单号语义（忽略大小写与分隔符）
     *
     * ### 别名也算命中（v3.44，真机实测补的）
     * 手机号是**搜得到、以前认不出**的那一类：名册是按 `?q=` 搜出来的，
     * 而匹配只看 `label`（姓名）——用户说「把货主 13800000002 的…」会拿到
     * 「系统里没有匹配…」，而人明明在系统里。所以 [AiName.aliases] 与 `label`
     * 一起参与**两轮**匹配：说全了手机号能像说全姓名一样精确命中，
     * 说一半则退到包含匹配（命中多人时照旧要求消歧义）。
     */
    fun strict(
        query: String,
        pool: List<AiName>,
        kind: String,
        code: Boolean = false,
        allowMissing: Boolean = false,
    ): AiName? {
        val q = if (code) normCode(query) else norm(query)
        if (q.isEmpty()) return null

        fun key(s: String) = if (code) normCode(s) else norm(s)
        fun keys(n: AiName) = listOf(n.label) + n.aliases

        val exact = pool.filter { n -> keys(n).any { key(it) == q } }
        val hits = if (exact.isNotEmpty()) exact else pool.filter { n -> keys(n).any { key(it).contains(q) } }

        return when {
            hits.isEmpty() -> {
                if (allowMissing) return null
                throw AiWriteArgException(
                    "系统里没有匹配「$query」的$kind。请让用户确认准确的名字" +
                        if (code) "（单号/车牌要写全）。" else "，或者先去对应页面把$kind 建好。",
                )
            }

            hits.size == 1 -> hits.first()

            else -> throw AiWriteArgException(
                "「$query」对上了多个$kind：${hits.take(MAX_CANDIDATES).joinToString("、") { it.label }}。" +
                    "请让用户说清楚是哪一个，**不要自己挑一个**。",
                candidates = hits.take(MAX_CANDIDATES).map { it.label },
            )
        }
    }
}
