package com.tapmoay.sorders.ai

import android.content.Context
import java.io.File

/**
 * 对话历史的**文件存储**（唯一的 Android 依赖就是 `filesDir`）。
 *
 * ### 存在哪、为什么
 * `context.filesDir/ai_conversations.json` —— App 私有目录：
 * - 其他 App 无 root 读不到；不会被备份到相册/下载目录；卸载即随 App 一起消失；
 * - **刻意不用外部存储**：聊天里有金额和客户名，写到 `/sdcard` 等于公开。
 *
 * ### 写盘策略：先写临时文件再改名
 * 直接往目标文件写，一旦写到一半被杀（低电、闪退），文件就是半截 JSON —— 整段历史全丢。
 * 所以先写 `*.tmp` 再 `renameTo` 覆盖：改名在同一文件系统上是原子操作，
 * **要么是旧的完整文件，要么是新的完整文件**，不存在半截状态。
 *
 * ### 坏文件不静默覆盖
 * 解析失败时把原文件改名成 `*.bad-<时间戳>` 留证，而不是直接删掉或覆盖。
 * 用户的历史可能是被别的版本写坏的，留着才有可能救回来（也方便我排障）。
 *
 * ⚠️ 本类的方法是**阻塞 IO**：调用方负责放到 `Dispatchers.IO` 上（见 `AiChatViewModel`）。
 */
class AiConversationStore(
    context: Context,
    /**
     * 用户分区后缀（见 [AiScope]）。**默认空 = 不分区的老行为**，
     * 只给单测用；生产一律由 [AiContainer] 传当前登录用户的分区。
     */
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

    /**
     * 是否**已经读过一次盘**。
     *
     * 这个标记只为一件事存在：[save] 的"防覆盖"兜底（见那里的注释）。
     * 它守的是一次真实的丢历史事故：ViewModel 的对话列表是异步读进来的，
     * 读进来之前调一次保存，就会把盘上原来的对话全部覆盖掉。
     */
    private var everLoaded = false

    /** 读全部对话。文件不存在 / 读失败 / 解析失败都返回空列表（**不抛异常**）。 */
    fun load(): List<StoredConversation> {
        everLoaded = true
        if (!file.exists()) return emptyList()
        val text = try {
            file.readText()
        } catch (e: Exception) {
            return emptyList()
        }
        val list = AiConversations.decode(text)
        // 有内容却解析不出任何对话 = 文件坏了；留证而不是让它被下一次写盘覆盖
        if (list.isEmpty() && text.isNotBlank()) quarantine()
        return list
    }

    /** 只读盘、不改 [everLoaded]、不做隔离（供 [save] 的合并兜底使用）。 */
    private fun readSilently(): List<StoredConversation> = try {
        if (file.exists()) AiConversations.decode(file.readText()) else emptyList()
    } catch (e: Exception) {
        emptyList()
    }

    /**
     * 全量覆盖写。**任何异常都不抛**（历史存不下不该让聊天功能挂掉）。
     *
     * ⚠️ **在"从未读过盘"时会退化成合并而不是覆盖**：此时调用方手上的列表不可能是全量
     * （它还没看过盘上有什么），直接覆盖等于删数据。这个分支只可能出现在启动后极短的时间窗内，
     * 代价是那一次多读一次文件，换来的是"打开就提问"不会抹掉历史。
     */
    fun save(list: List<StoredConversation>): Boolean = try {
        val effective = if (everLoaded) list else AiConversations.mergeById(readSilently(), list)
        val payload = AiConversations.encode(effective)
        tmp.writeText(payload)
        if (!tmp.renameTo(file)) {
            // 改名失败（极少数文件系统）→ 退回直接写；此时会短暂失去原子性，但总比不存好
            file.writeText(payload)
            tmp.delete()
        }
        true
    } catch (e: Exception) {
        tmp.delete()
        false
    }

    /** 清空（删除文件）。 */
    fun clear(): Boolean = try {
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
        const val FILE_NAME = "ai_conversations.json"
    }
}
