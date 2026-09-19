package com.tapmoay.sorders.ai

/**
 * 这个模型**能不能看图**。
 *
 * ### 一张"能力表"帮不上忙，所以这里只做**三件事**
 * 接口不返回这个能力（`GET /models` 只给名字），而模型名的命名毫无统一规律。
 * 更麻烦的是：**同一个名字的模型在不同时间可能是不同能力**——
 * 用户实测（2026-09-17）新版 `deepseek-flash` 已经能看图，而按厂商前缀一刀切
 * 会把一个明明能用的模型永久判死（用户的原话是「最新的 deepseek flash 是多模态的」）。
 *
 * 所以这里的策略是：
 * 1. **认识的说死**：[KNOWN_VISION] 里的名字直接判能看；
 * 2. **明显不是对话模型的拦住**（embedding / rerank / 语音）——这些传图一定失败，
 *    拦下来能省用户一次白试；
 * 3. **其余一律放行**（[Support.UNKNOWN]），并且**不弹任何警告**：
 *    用户比我们更清楚自己用的是哪个模型，让他试就是了。
 *    万一真的不收图，[LlmClient] 会**自动去掉图重试**一次，然后在回答里如实说明
 *    （见 `ChatResult.Success.imagesDropped`）——那才是真正可靠的那道保险，
 *    比一个猜出来的能力表可靠得多。
 */
internal object AiVision {

    enum class Support {
        /** 名字在已知的视觉模型名单里。 */
        YES,

        /** 确定不是对话模型（embedding / rerank / 语音合成），传图必然失败。 */
        NO,

        /** 认不出来：**放行**（不警告），出问题由运行时兜底。 */
        UNKNOWN,
    }

    /** 已知能吃图的名字片段（各家视觉模型命名差异很大，只能收特征词）。 */
    private val KNOWN_VISION = listOf(
        "vl",            // qwen-vl / qwen2-vl / qwen2.5-vl / internvl
        "vision",        // doubao-1.5-vision / gpt-4-vision
        "4v",            // glm-4v
        "gpt-4o", "gpt-4.1", "gpt-5",
        "gemini",
        "claude-3", "claude-4", "claude-sonnet", "claude-opus",
        "step-1v", "step-1o",
        "pixtral",
    )

    /**
     * 确定**不是对话模型**的片段。
     *
     * ⚠️ 这里刻意**不按厂商前缀判**（曾经把 `deepseek` 整个判成看不了图，是错的——
     * 用户实测新版 deepseek-flash 支持图片）。只收"从名字就能确定它不聊天"的那几类。
     */
    private val NOT_CHAT_MODELS = listOf(
        "embedding", "embed-", "-embed",
        "rerank",
        "whisper", "tts", "asr", "-audio",
    )

    fun support(model: String?): Support {
        val m = model?.trim()?.lowercase().orEmpty()
        if (m.isEmpty()) return Support.UNKNOWN
        if (NOT_CHAT_MODELS.any { m.contains(it) }) return Support.NO
        if (KNOWN_VISION.any { m.contains(it) }) return Support.YES
        return Support.UNKNOWN
    }

    /**
     * 界面上一句话。**只有确定不行时才说**（[Support.NO]）——
     * UNKNOWN 不提示：用户知道自己用的是哪个模型，多余的警告只是噪音。
     */
    fun hint(model: String?): String? = when (support(model)) {
        Support.NO ->
            "「${model.orEmpty()}」不是对话模型（看名字像是向量/语音模型），它收不了图片。" +
                "请到设置页换一个对话模型。"
        else -> null
    }

    /** 这一轮提问能不能带图。false 时界面应当**拦住**并显示 [hint]。 */
    fun canSendImages(model: String?): Boolean = support(model) != Support.NO

    /** 一次最多几张图。多了既贵又容易让模型顾此失彼。 */
    const val MAX_IMAGES = 3
}
