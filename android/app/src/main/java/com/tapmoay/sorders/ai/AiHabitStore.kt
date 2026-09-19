package com.tapmoay.sorders.ai

import android.content.Context

/**
 * 「使用习惯」的本地存储（含开关）。
 *
 * 存 `SharedPreferences` 而不是文件：数据很小（几个计数 + 最近 20 条问题），
 * 而且它是**随时可丢**的派生数据——丢了只是少一点个性化，不影响任何功能。
 * 所以读写失败一律静默忽略，绝不让它挡住聊天。
 *
 * ⚠️ 隐私边界（和对话历史一致）：只写 App 私有 prefs，**不写外部存储、不上传服务器**。
 */
class AiHabitStore(
    context: Context,
    /**
     * 用户分区后缀（见 [AiScope]）。
     *
     * 做法是**换一个 prefs 名**（而不是在里面加一层 key）：旧的无分区 prefs 自然就没人读了，
     * 等于天然隔离区——不需要额外的迁移代码，也不会误把旧数据归给新登录的人。
     */
    scope: String = "",
) {

    private val prefs = context.applicationContext.getSharedPreferences(PREFS_NAME + scope, Context.MODE_PRIVATE)

    /** 读取（坏数据 → 空习惯）。 */
    fun load(): AiHabit = AiHabits.decode(prefs.getString(KEY_HABIT, null))

    /** 写入（失败静默）。 */
    fun save(habit: AiHabit) {
        try {
            prefs.edit().putString(KEY_HABIT, AiHabits.encode(habit)).apply()
        } catch (e: Exception) {
            // 习惯存不下不影响功能
        }
    }

    /**
     * 是否允许「按你的使用习惯优化回答」。**默认开**。
     *
     * 默认开是因为它全程在本机、只影响"用户没说清时的默认口径"，收益直接；
     * 但必须给一个关掉的开关——有人就是不喜欢被"猜"。
     */
    fun enabled(): Boolean = prefs.getBoolean(KEY_ENABLED, true)

    fun setEnabled(on: Boolean) {
        prefs.edit().putBoolean(KEY_ENABLED, on).apply()
    }

    /** 清空已学到的习惯（设置页「清除习惯记录」）。 */
    fun clear() {
        prefs.edit().remove(KEY_HABIT).apply()
    }

    companion object {
        private const val PREFS_NAME = "sorders_ai_habit"
        private const val KEY_HABIT = "habit"
        private const val KEY_ENABLED = "enabled"
    }
}
