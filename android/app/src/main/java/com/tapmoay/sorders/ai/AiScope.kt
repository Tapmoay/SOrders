package com.tapmoay.sorders.ai

import java.io.File

/**
 * 「这份数据属于谁」——AI 在本机存的三份东西（对话历史、使用习惯、长期记忆）**必须按用户分区**。
 *
 * ### 为什么必须有这个文件（v3.13 真机实测抓到的）
 * 原来这三个 store 都用固定文件名（`ai_conversations.json` / `ai_memory.json` /
 * `sorders_ai_habit`）。**同一台手机上换账号，下一个人能读到上一个人的全部聊天内容**：
 * 实测在货主端登录后，AI 页面显示的是派单员那一整段对话（"帮我记一笔停车费 300 元"之类）。
 *
 * 这和项目的硬红线直接冲突：那条红线是「聊天记录/习惯/记忆只存在用户手机上」——
 * "只存在手机上"是**必要条件**，而「同机换账号不串」才是用户真正在意的那个性质。
 * 派单员把手机递给货主看一眼，货主就能翻完派单员问过的所有事。
 *
 * ⚠️ **这个坑值得单独一个文件的原因**：它不是任何一条既有红线的违例——
 * 当时 281 条检查全过，因为**没有一条在问"这份数据属于谁"**。
 *
 * ### 分区规则
 * - 登录着 → `_u<userId>`；
 * - 读不到用户（未登录/异常）→ `_anon`。**绝不回落到"公共区"**：
 *   回落就意味着"读不到身份时大家共用一份"，而那正是要修的那个 bug。
 */
internal object AiScope {

    /** 未登录/读不到身份时的分区名。 */
    const val ANON = "_anon"

    /** 当前用户的分区后缀。 */
    fun suffix(userId: Long?): String =
        if (userId != null && userId > 0L) "_u$userId" else ANON

    /** 分区后的文件名：`ai_memory.json` + `_u2` → `ai_memory_u2.json`。 */
    fun fileName(base: String, scope: String): String =
        if (scope.isEmpty()) base else base.removeSuffix(".json") + scope + ".json"

    /**
     * 把**没有分区的旧文件**挪进隔离区。
     *
     * ### 为什么是隔离而不是"归给当前登录的人"
     * 旧文件是在分区功能之前写的，**我们无从知道它属于谁**。
     * 把它归给"现在登录的这个账号"看起来方便，但那正好是这个 bug 本身——
     * 「谁先登录谁继承前任的全部聊天记录」。
     *
     * 所以把它改名成 `<名字>.legacy-<时间戳>` 留着（不删，可人工找回），
     * 然后从空白开始。**宁可丢一份历史，也不要把它交给一个可能不是它主人的人。**
     */
    fun quarantineLegacy(dir: File, base: String): Boolean {
        val legacy = File(dir, base)
        if (!legacy.exists()) return false
        val target = File(dir, "$base.legacy-${System.currentTimeMillis()}")
        return try {
            legacy.renameTo(target)
        } catch (e: Exception) {
            // 挪不动也不能让 App 起不来；下次启动会再试
            false
        }
    }
}
