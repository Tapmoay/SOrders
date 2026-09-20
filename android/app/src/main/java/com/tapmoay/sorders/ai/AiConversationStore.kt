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
 * ### 写盘策略（原子写 / 坏文件留证 / 防覆盖）现在只有一处
 * 那四条策略收在 [AiJsonStore]（2026-09-21 精简轮）：本类原来和 [AiMemoryStore] **各写了一遍
 * 同样的约 120 行**，而它们守的是同一批数据丢失事故（写一半被杀、没读过盘就覆盖、坏文件被盖掉）。
 * 现在这里只剩「存哪个文件、怎么编解码、按 id 怎么合并」。
 * 附带的好处：`AiJsonStore` 不带 Android 依赖，于是那四条行为**第一次有了单测**（`AiJsonStoreTest`）——
 * 原来它们需要 `Context`，JVM 单测碰不到。
 *
 * ### 按用户分区
 * 文件名带分区后缀（见 [AiScope]），否则同一台手机换账号会读到上一个人的全部聊天内容。
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

    private val store = AiJsonStore(
        file = File(context.applicationContext.filesDir, AiScope.fileName(FILE_NAME, scope)),
        encode = AiConversations::encode,
        decode = AiConversations::decode,
        merge = AiConversations::mergeById,
    )

    init {
        // 没有分区的旧文件**不能**归给现在登录的人（我们不知道它是谁的），挪进隔离区
        AiScope.quarantineLegacy(context.applicationContext.filesDir, FILE_NAME)
    }

    /** 读全部对话。文件不存在 / 读失败 / 解析失败都返回空列表（**不抛异常**）。 */
    fun load(): List<StoredConversation> = store.load()

    /**
     * 全量覆盖写。**任何异常都不抛**（历史存不下不该让聊天功能挂掉）。
     *
     * ⚠️ 「还没读过盘时退化成合并」这条兜底在 [AiJsonStore.save] 里（一处），
     *    它守的是"打开就提问"不会抹掉历史那件事。
     */
    fun save(list: List<StoredConversation>): Boolean = store.save(list)

    /** 清空（删除文件）。 */
    fun clear(): Boolean = store.clear()

    /** 当前占用字节数（设置页显示用）。 */
    fun sizeBytes(): Long = store.sizeBytes()

    companion object {
        const val FILE_NAME = "ai_conversations.json"
    }
}
