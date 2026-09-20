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
 * ⚠️ 这四条**和 [AiConversationStore] 完全一样**，所以 2026-09-21 收进了 [AiJsonStore] **一处**
 *    （原来两份各写了一遍约 120 行）。本类只剩「存哪个文件、怎么编解码、按 id 怎么合并」，
 *    而那四条行为也因此第一次有了 JVM 单测（`AiJsonStoreTest`）。
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

    private val store = AiJsonStore(
        file = File(context.applicationContext.filesDir, AiScope.fileName(FILE_NAME, scope)),
        encode = AiMemories::encode,
        decode = AiMemories::decode,
        merge = { disk, mine -> mergeById(disk, mine) },
    )

    init {
        // 没有分区的旧文件**不能**归给现在登录的人（我们不知道它是谁的），挪进隔离区
        AiScope.quarantineLegacy(context.applicationContext.filesDir, FILE_NAME)
    }

    /** 读全部记忆。文件不存在 / 读失败 / 解析失败都返回空列表（**不抛异常**）。 */
    fun load(): List<AiMemoryItem> = store.load()

    /**
     * 全量覆盖写。**任何异常都不抛**。
     *
     * ⚠️ 与 [AiConversationStore.save] 同样：**在"从未读过盘"时退化成合并而不是覆盖**。
     * 因为此时调用方手上的列表不可能是全量（它还没看过盘上有什么），直接覆盖等于删掉
     * 用户之前教过的全部记忆——这个分支只可能出现在启动后极短的时间窗内，
     * 代价是多读一次文件，换来的是"打开就教它一句"不会抹掉旧记忆。兜底实现在 [AiJsonStore.save]。
     */
    fun save(list: List<AiMemoryItem>): Boolean = store.save(list)

    /** 按 id 合并（盘上已有的 + 手上新增的，同 id 以手上的为准）。 */
    private fun mergeById(disk: List<AiMemoryItem>, mine: List<AiMemoryItem>): List<AiMemoryItem> {
        if (disk.isEmpty()) return mine
        if (mine.isEmpty()) return disk
        val mineIds = mine.map { it.id }.toSet()
        return disk.filterNot { it.id in mineIds } + mine
    }

    /** 清空（删除文件）。 */
    fun clear(): Boolean = store.clear()

    /** 当前占用字节数（设置页显示用）。 */
    fun sizeBytes(): Long = store.sizeBytes()

    companion object {
        const val FILE_NAME = "ai_memory.json"
    }
}
