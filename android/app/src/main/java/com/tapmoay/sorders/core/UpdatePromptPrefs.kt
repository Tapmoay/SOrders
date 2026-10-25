package com.tapmoay.sorders.core

import android.content.Context

/**
 * 「有新版本」**启动提示**的记忆（CHG-0137）。
 *
 * 用户 2026-10-26 的规矩（他选了"同一版只弹一次"）：
 * > 第一次打开 App 时弹一句"有新版本了，是否更新"；**同一个版本只弹一次**，
 * > 点「稍后」也算弹过 —— 要更新自己去「我的 → 关于与更新」。
 *
 * ⛔ 为什么不每次启动都弹：更新是**用户的选择**，不是必须做的事；每次冷启动都拦一道，
 *    用久了会变成"看到就点稍后"的肌肉记忆，最后新版永远装不上，还闹人。
 * ⚠️ 记住的是 **versionCode**（不是版本名）：安卓判新旧、version.json 里的 versionCode
 *    都是构建号；拿版本名记，同一个 0.2.23 重发一个包就不会再提示了。
 *
 * ⚠️ 用 SharedPreferences 而不是 DataStore：这里只有一个 int，且**冷启动要同步读**
 *    （异步读会先闪一下再判断，弹窗会迟到）。项目里 AlertPrefs 也是这么选的。
 */
class UpdatePromptPrefs(context: Context) {

    private val sp = context.applicationContext
        .getSharedPreferences("update_prompt", Context.MODE_PRIVATE)

    /** 最近一次**已经提示过**的构建号（0 = 从来没有提示过）。 */
    var lastPromptedCode: Int
        get() = sp.getInt(KEY_LAST_PROMPTED, 0)
        private set(value) {
            sp.edit().putInt(KEY_LAST_PROMPTED, value).apply()
        }

    /**
     * 这一版还该不该弹。
     *
     * ⚠️ 两个条件缺一不可：versionCode 必须有效（> 0，否则"没版本号"会被当成"没提示过"，
     *    于是老数据每次启动都弹），且**与上次提示过的不是同一个**。
     */
    fun shouldPrompt(versionCode: Int): Boolean =
        versionCode > 0 && versionCode != lastPromptedCode

    /** 记下"这一版提示过了"（点**稍后**与点**下载并更新**都要记）。 */
    fun markPrompted(versionCode: Int) {
        if (versionCode > 0) lastPromptedCode = versionCode
    }

    private companion object {
        const val KEY_LAST_PROMPTED = "last_prompted_code"
    }
}
