package com.tapmoay.sorders.ai

/**
 * 「思考强度」。取代了原来的布尔开关（开/关）。
 *
 * ### 它发两个字段，不是一个
 * - 关 → `thinking:{"type":"disabled"}`，且**不发** `reasoning_effort`
 * - 低/中/高 → `thinking:{"type":"enabled"}` + `reasoning_effort: low|medium|high`
 *
 * ### ⚠️ 必须诚实告诉用户的一件事
 * **`reasoning_effort` 在部分端点上是被静默忽略的**（返回 200，但思考量和 low/high 没关系）。
 * 这是本项目**实测过**的结论（见 `docs/AI_ASSISTANT_PLAN_V3.md` §6.5）：
 * 同一个问题传 `reasoning_effort: low` 和 `high`，返回的思考内容没有可观察差别。
 * 所以界面上的措辞是「思考强度（部分模型不支持分级）」，**不承诺"选高就一定想得更久"**。
 * 能确定的只有一件事：**关 = 真的关**（实测 `reasoning_content` 消失、completion_tokens 24→6）。
 *
 * 为什么不干脆做成"检测到不支持就不显示"：检测不了——静默忽略不会报错，
 * 唯一的判据是"思考内容有没有变化"，那需要跑两次对比，代价太大。
 * 所以选择"如实标注 + 让用户自己选"。
 */
enum class ThinkingLevel(
    val key: String,
    val label: String,
    val hint: String,
    /** 发给端点的 `reasoning_effort` 取值；关 = null（不发这个字段）。 */
    val effort: String?,
) {
    OFF("off", "关", "直接答，最快最省", null),
    LOW("low", "低", "略想一下", "low"),
    MEDIUM("medium", "中", "常规，默认", "medium"),
    HIGH("high", "高", "尽量想全（更慢更贵）", "high"),
    ;

    /** 是否要开启思考（= 下发 `thinking:{"type":"enabled"}`）。 */
    val enabled: Boolean get() = this != OFF

    companion object {
        /**
         * 默认「中」。
         *
         * 为什么不再默认"开（无分级）"：原来布尔开关没有程度之分，默认开等于默认最高投入；
         * 现在有了分级，默认应该落在中间——**要准的可以调高，嫌贵的可以调低**，
         * 而不是替所有人选一个极端。
         */
        val DEFAULT = MEDIUM

        /** 从存储里读回来；认不出来就用默认（老版本存的是布尔，见 [migrate]）。 */
        fun fromKey(key: String?): ThinkingLevel =
            entries.firstOrNull { it.key == key } ?: DEFAULT

        /**
         * 老数据迁移：v3.3 之前存的是布尔 `thinking`（true=开 / false=关）。
         * `true` 映射到 [MEDIUM]（旧版"开"没有程度，取中间最接近"照旧"）。
         */
        fun migrate(legacyThinking: Boolean?): ThinkingLevel = when (legacyThinking) {
            null -> DEFAULT
            true -> MEDIUM
            false -> OFF
        }
    }
}
