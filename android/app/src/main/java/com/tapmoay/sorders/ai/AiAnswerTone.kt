package com.tapmoay.sorders.ai

/**
 * 回答里一条「重要信息」的类别 —— **颜色由界面按它上**，见 [AiAnswerTone]。
 *
 * ⚠️ 这个枚举**不能是 internal**：[AiMarkdown.Span] 是公开的数据类，它的构造参数类型只能是公开的
 * （编译器会直接拒：'public' function exposes its 'internal' parameter type）。判定逻辑仍然在
 * [AiAnswerTone] 里、是 internal —— 外面拿得到类型，但拿不到"哪句话算什么色"的规则。
 */
enum class AnswerTone { MONEY, DANGER, WARN, OK }

/**
 * 「重要的信息用特殊的样式」——**颜色由界面按类别自动上，不靠模型写标记**（台账 L-24）。
 *
 * ### 用户原话（2026-10-05 m00779）
 * - 「这重要的信息用特殊样式这些样式都可以选择。而如果**信息越重要越要用特殊的颜色**进行搞。」
 * - 「我们这个样式**不能随便乱搞** —— 比如说联系人的话，可能就使用统一的样式，
 *    什么数字、账本信息，我们都属于统一的样式。」
 * - 「这关于特定的表格模板暂时也不需要搞。」「其实我们不给模板的话，其实 AI 做得更好。」
 *
 * ### 为什么是确定性检测，而不是教模型一套标记语法
 * 用户点名的红线是**「同类信息必须统一」**。让模型自己挑样式，同一句话今天红、明天橙，
 * 就谈不上统一；而且新语法要写进提示词（**每轮都重发**），模型还会把没闭合的标记漏给用户。
 * 所以分工是：
 * - **加粗**（`**…**`）＝模型唯一的表达手段，提示词让它圈出最多 3 处重点；
 * - **颜色**＝界面按类别确定性地上，模型不需要知道，也写不出来。
 * 检测表是**封闭**的（两个词表 + 一条正则），纯 Kotlin、可在 JVM 里穷举。
 *
 * ### 四条硬约束（判据与反向验证都钉着）
 * 1. **一次回答最多 2 种颜色**（[MAX_KINDS]）——三种以上就是花，不是重点。
 * 2. **最多 12 处**（[MAX_TONED]）——整篇都在染色等于没染。
 * 3. **只给短片段上色**（[MAX_CHARS]）——长句里出现「逾期」不代表这句话是个状态值。
 * 4. **带句读的片段不上色**（[CLAUSE_MARKS]）——有逗号/句号就是在说一件事，不是在给一个值。
 *
 * 优先级＝危险 → 钱 → 提醒 → 正常（越重要越先命中，也正好是色阶从重到轻的顺序）。
 * ⚠️ 表格**不参与**：`AiRichText` 的既有裁定是表格画在中性白卡上，不跟随气泡、也不染色。
 */
internal object AiAnswerTone {

    /** 能上色的片段最长多少个字符。超过就是「一整句话」，交给加粗去表达。 */
    const val MAX_CHARS: Int = 16

    /** 一条回答里最多染多少处。 */
    const val MAX_TONED: Int = 12

    /** 一条回答里最多出现几种颜色。 */
    const val MAX_KINDS: Int = 2

    // ⚠️ 这条必须排在最前面：先判「不是坏消息」，否则「无异常」会被当成异常染红。
    private val NOT_DANGER = listOf("无异常", "没有异常", "无风险", "已恢复")

    private val DANGER = listOf(
        "逾期", "超期", "驳回", "失败", "异常", "已撤销", "超时", "风险", "亏损",
        "欠款", "未通过", "错误",
    )

    private val WARN = listOf(
        "待处理", "待确认", "待派单", "待收货", "待结算", "未派单", "未送达", "未完成",
        "未结清", "未收款", "提醒", "注意", "即将", "挂账", "临期", "缺货", "不足",
    )

    private val OK = listOf(
        "已送达", "已完成", "已通过", "已结清", "已收款", "已签收", "已入库", "已确认",
        "正常", "成功",
    )

    /** 钱的两种写法：符号在前的「¥1,280」与单位在后的「1280 元」。 */
    private val MONEY = Regex("[¥￥]\\s*-?\\d|\\d[\\d,]*(?:\\.\\d+)?\\s*(?:元|块钱|块)")

    /** 一句里带这些标点就是在叙述（不是「一个值」）——整句跟着变色正是要避免的那种花。 */
    private val CLAUSE_MARKS = listOf('，', '。', '；', '、', '！', '？', ';', '!', '?')

    /** 这个片段该用哪种颜色；返回 null ＝ 不上色（大多数片段都是 null）。 */
    fun toneOf(text: String): AnswerTone? {
        val t = text.trim()
        if (t.isEmpty() || t.length > MAX_CHARS) return null
        if (CLAUSE_MARKS.any { it in t }) return null
        if (NOT_DANGER.any { t.contains(it) }) return AnswerTone.OK
        if (DANGER.any { t.contains(it) }) return AnswerTone.DANGER
        if (MONEY.containsMatchIn(t)) return AnswerTone.MONEY
        if (WARN.any { t.contains(it) }) return AnswerTone.WARN
        if (OK.any { t.contains(it) }) return AnswerTone.OK
        return null
    }

    /**
     * 给一整条回答上色：**按阅读顺序先到先得**（所以结果与输入顺序一一对应，可复现）。
     *
     * 表格原样返回；[MAX_TONED] 与 [MAX_KINDS] 用完之后的片段一律保持无色。
     */
    fun apply(blocks: List<AiMarkdown.Block>): List<AiMarkdown.Block> {
        val kinds = LinkedHashSet<AnswerTone>()
        var toned = 0
        val out = ArrayList<AiMarkdown.Block>(blocks.size)
        for (b in blocks) {
            if (b !is AiMarkdown.Block.Line) {
                out += b
                continue
            }
            val spans = ArrayList<AiMarkdown.Span>(b.spans.size)
            for (s in b.spans) {
                val t = if (toned >= MAX_TONED) null else toneOf(s.text)
                if (t != null && (t in kinds || kinds.size < MAX_KINDS)) {
                    kinds += t
                    toned++
                    spans += s.copy(tone = t)
                } else {
                    spans += s
                }
            }
            out += b.copy(spans = spans)
        }
        return out
    }
}
