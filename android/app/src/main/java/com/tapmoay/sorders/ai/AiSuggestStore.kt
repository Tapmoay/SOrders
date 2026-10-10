package com.tapmoay.sorders.ai

import android.content.Context
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * 一个角色在「推荐问题」这件事上的**本机记忆**。
 *
 * @param first 用户在设置里自己编辑过的**首次预设**；`null` = 从没编辑过（用 [AiSuggests] 的默认）
 * @param pinned 他**固定**住的问题（顺序有意义，摆在最前）
 * @param taps 每个问题被点过几次（问题原文 → 次数），用来排「常用」
 */
@Serializable
data class AiSuggestSaved(
    val first: List<String>? = null,
    val pinned: List<String> = emptyList(),
    val taps: Map<String, Int> = emptyMap(),
)

object AiSuggestCodec {

    /** 首次预设最多几条（再多空状态就滚起来了，反而看不清）。 */
    const val MAX_FIRST = 8

    /** 最多固定几条。 */
    const val MAX_PINNED = 8

    /** 最多记多少个问题的次数（防 prefs 无限长）。 */
    const val MAX_TAPS = 60

    /** 单条问题最多存这么多字（与 [AiHabits.MAX_QUESTION_CHARS] 同口径）。 */
    const val MAX_QUESTION_CHARS = 60

    private val json = Json {
        ignoreUnknownKeys = true
        encodeDefaults = true
    }

    fun encode(v: AiSuggestSaved): String = json.encodeToString(AiSuggestSaved.serializer(), v)

    /** 坏数据一律退回空（这份数据丢了只是少一点个性化，绝不能让聊天页崩）。 */
    fun decode(text: String?): AiSuggestSaved {
        if (text.isNullOrBlank()) return AiSuggestSaved()
        return try {
            json.decodeFromString(AiSuggestSaved.serializer(), text)
        } catch (e: Exception) {
            AiSuggestSaved()
        }
    }

    /**
     * 洗一条用户输入的问题：去空白、去换行、截断。
     *
     * 空串 ⇒ 返回 `null`，调用方据此**丢弃**（一条空的预设摆在那儿，点了什么都不发生）。
     */
    fun clean(raw: String?): String? {
        // 换行 / 制表 / 全角空格一律压成一个半角空格：预设是一行一颗按钮，
        // 换行会把按钮撑高、连着的空白会撑出一条缝。⚠️ `\s` 在 Java 里只认 ASCII，
        // 全角空格 `\u3000` 要自己列进去。
        val s = raw?.replace(WHITESPACE, " ")?.trim().orEmpty()
        return s.take(MAX_QUESTION_CHARS).ifEmpty { null }
    }

    private val WHITESPACE = Regex("[\\s\\u3000]+")

    /** 洗一整张列表：逐条 [clean]、去重、限量。 */
    fun cleanList(raw: List<String>?, limit: Int): List<String> =
        (raw ?: emptyList()).mapNotNull { clean(it) }.distinct().take(limit)

    /** 记一次点击（返回新的计数表）。 */
    fun tap(taps: Map<String, Int>, question: String): Map<String, Int> {
        val q = clean(question) ?: return taps
        val next = taps.toMutableMap()
        next[q] = (next[q] ?: 0) + 1
        // 超量时**先丢次数最少的**（常问的那几个必须留住，它们正是"常用"区的来源）
        if (next.size > MAX_TAPS) {
            val keep = next.entries.sortedByDescending { it.value }.take(MAX_TAPS)
            return keep.associate { it.key to it.value }
        }
        return next
    }
}

/**
 * 「推荐问题」的本地存储（首次预设 / 固定 / 点击计数）。
 *
 * 存 `SharedPreferences`，与 [AiHabitStore] 同一套口径：
 * - **按用户分区**（prefs 名带 [AiScope] 后缀）——否则换账号会看到上一个人的固定问题；
 * - 只写 App 私有 prefs，**不上传服务器**；
 * - 读写失败**静默忽略**，绝不挡住聊天页。
 */
class AiSuggestStore(
    context: Context,
    scope: String = "",
) {

    private val prefs = context.applicationContext.getSharedPreferences(PREFS_NAME + scope, Context.MODE_PRIVATE)

    /** 读一个角色的记忆（坏数据 → 空）。 */
    fun load(who: AiSuggestWho): AiSuggestSaved =
        AiSuggestCodec.decode(prefs.getString(key(who), null))

    private fun save(who: AiSuggestWho, v: AiSuggestSaved) {
        try {
            prefs.edit().putString(key(who), AiSuggestCodec.encode(v)).apply()
        } catch (e: Exception) {
            // 存不下不影响功能
        }
    }

    /** 用户编辑过的首次预设；`null` = 用默认那套。 */
    fun customFirst(who: AiSuggestWho): List<String>? = load(who).first

    /**
     * 写入首次预设。
     *
     * @param list `null` 或洗完之后为空 ⇒ **删掉这条记录**（回到默认），
     *   而不是存一个空列表——存空列表会让空状态一条问题都没有，那是"白屏"级的坏。
     */
    fun setCustomFirst(who: AiSuggestWho, list: List<String>?) {
        val cleaned = AiSuggestCodec.cleanList(list, AiSuggestCodec.MAX_FIRST).ifEmpty { null }
        save(who, load(who).copy(first = cleaned))
    }

    fun pinned(who: AiSuggestWho): List<String> = load(who).pinned

    fun setPinned(who: AiSuggestWho, list: List<String>) {
        save(who, load(who).copy(pinned = AiSuggestCodec.cleanList(list, AiSuggestCodec.MAX_PINNED)))
    }

    /** 固定/取消固定一条（聊天页那颗图钉用它）。 */
    fun togglePin(who: AiSuggestWho, question: String): Boolean {
        val q = AiSuggestCodec.clean(question) ?: return false
        val cur = pinned(who)
        val now = if (q in cur) cur - q else (cur + q).take(AiSuggestCodec.MAX_PINNED)
        save(who, load(who).copy(pinned = now))
        return q in now
    }

    fun taps(who: AiSuggestWho): Map<String, Int> = load(who).taps

    /** 记一次"他点了这条推荐问题"。 */
    fun recordTap(who: AiSuggestWho, question: String) {
        val cur = load(who)
        save(who, cur.copy(taps = AiSuggestCodec.tap(cur.taps, question)))
    }

    /** 清掉这个角色的全部推荐记忆（设置页「恢复默认」一起清）。 */
    fun clear(who: AiSuggestWho) {
        prefs.edit().remove(key(who)).apply()
    }

    private fun key(who: AiSuggestWho): String = KEY_PREFIX + who.key

    companion object {
        private const val PREFS_NAME = "sorders_ai_suggest"
        private const val KEY_PREFIX = "who_"
    }
}
