package com.tapmoay.sorders.ai

import android.content.Context
import java.io.File

/**
 * 长期事实记忆的**文件存储**（`filesDir/ai_memory.json`）。
 *
 * ### 为什么用文件而不是 [AiHabitStore] 那样的 SharedPreferences
 * [AiHabitStore] 的注释写着：习惯"是**随时可丢**的派生数据——丢了只是少一点个性化"。
 * 记忆不是：**那是用户特意教的**。两者的可靠性要求不同，所以走 [AiConversationStore]
 * 已经验证过的那套（原子写 + 坏文件留证）而不是 prefs。
 *
 * ### 四条沿用下来的做法（每一条都对应一次真实事故）
 * 1. **App 私有目录**：记忆里有客户名和结算习惯，写到 `/sdcard` 等于公开；
 * 2. **先写 `.tmp` 再 `renameTo`**：写到一半被杀（低电、闪退）不会留下半截 JSON；
 * 3. **坏文件改名留证**（`*.bad-<时间戳>`）而不是删掉或覆盖——用户教的东西，留着才有可能救回来；
 * 4. **任何异常都不抛**：记忆存不下不该让聊天功能挂掉。
 *
 * ### 隐私边界（硬约束，与对话历史/使用习惯一致）
 * **只写 App 私有目录，绝不上传服务器、不做跨设备同步。**
 * 这一点已经在界面上对用户承诺过（AI 设置页原文：
 * "Key 只保存在你这台手机上（系统级加密），不会上传到服务器"），
 * 记忆与聊天记录同样适用。
 *
 * ⚠️ 本类的方法是**阻塞 IO**：调用方负责放到 `Dispatchers.IO` 上（见 `AiSettingsViewModel` / `AiChatViewModel`）。
 */
class AiMemoryStore(
    context: Context,
    /** 用户分区后缀（见 [AiScope]）。默认空只给单测用；生产由 [AiContainer] 传。 */
    scope: String = "",
) {

    /** 分区后的文件名（按用户，见 [AiScope]）。 */
    private val fileName = AiScope.fileName(FILE_NAME, scope)
    private val file = File(context.applicationContext.filesDir, fileName)
    private val tmp = File(context.applicationContext.filesDir, "$fileName.tmp")

    init {
        // 没有分区的旧文件**不能**归给现在登录的人（我们不知道它是谁的），挪进隔离区
        AiScope.quarantineLegacy(context.applicationContext.filesDir, FILE_NAME)
    }

    /** 与 [AiConversationStore] 同样的"防覆盖"标记：读盘之前不写全量。 */
    private var everLoaded = false

    /** 读全部记忆。文件不存在 / 读失败 / 解析失败都返回空列表（**不抛异常**）。 */
    fun load(): List<AiMemoryItem> {
        everLoaded = true
        if (!file.exists()) return emptyList()
        val text = try {
            file.readText()
        } catch (e: Exception) {
            return emptyList()
        }
        val list = AiMemories.decode(text)
        // 有内容却解析不出任何条目 = 文件坏了；留证而不是让它被下一次写盘覆盖
        if (list.isEmpty() && text.isNotBlank()) quarantine()
        return list
    }

    /** 只读盘、不改 [everLoaded]、不做隔离（供 [save] 的合并兜底使用）。 */
    private fun readSilently(): List<AiMemoryItem> = try {
        if (file.exists()) AiMemories.decode(file.readText()) else emptyList()
    } catch (e: Exception) {
        emptyList()
    }

    /**
     * 全量覆盖写。**任何异常都不抛**。
     *
     * ⚠️ 与 [AiConversationStore.save] 同样：**在"从未读过盘"时退化成合并而不是覆盖**。
     * 因为此时调用方手上的列表不可能是全量（它还没看过盘上有什么），直接覆盖等于删掉
     * 用户之前教过的全部记忆——这个分支只可能出现在启动后极短的时间窗内，
     * 代价是多读一次文件，换来的是"打开就教它一句"不会抹掉旧记忆。
     */
    fun save(list: List<AiMemoryItem>): Boolean = try {
        val effective = if (everLoaded) list else mergeById(readSilently(), list)
        val payload = AiMemories.encode(effective)
        tmp.writeText(payload)
        if (!tmp.renameTo(file)) {
            file.writeText(payload)
            tmp.delete()
        }
        true
    } catch (e: Exception) {
        tmp.delete()
        false
    }

    /** 按 id 合并（盘上已有的 + 手上新增的，同 id 以手上的为准）。 */
    private fun mergeById(disk: List<AiMemoryItem>, mine: List<AiMemoryItem>): List<AiMemoryItem> {
        if (disk.isEmpty()) return mine
        if (mine.isEmpty()) return disk
        val mineIds = mine.map { it.id }.toSet()
        return disk.filterNot { it.id in mineIds } + mine
    }

    /** 清空（删除文件）。 */
    fun clear(): Boolean = try {
        everLoaded = true
        tmp.delete()
        !file.exists() || file.delete()
    } catch (e: Exception) {
        false
    }

    /** 当前占用字节数（设置页显示用）。 */
    fun sizeBytes(): Long = try {
        if (file.exists()) file.length() else 0L
    } catch (e: Exception) {
        0L
    }

    /** 把坏文件改名留证；改不动就删（否则每次启动都会重复报错）。 */
    private fun quarantine() {
        try {
            val bad = File(file.parentFile, "$fileName.bad-${System.currentTimeMillis()}")
            if (!file.renameTo(bad)) file.delete()
        } catch (e: Exception) {
            // 留证失败不影响主流程
        }
    }

    companion object {
        const val FILE_NAME = "ai_memory.json"
    }
}
