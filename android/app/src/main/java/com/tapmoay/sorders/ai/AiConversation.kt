package com.tapmoay.sorders.ai

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.util.Locale
import java.util.UUID

// ============================================================================
//  存盘模型（字段名就是 JSON 里的键名，改名 = 改变盘格式，老数据会读不出来）
// ============================================================================

/** 存盘的一条消息。与界面上的 `UiMessage` 一一对应，但**不带任何 Compose 依赖**（为了能在纯 JVM 里测）。 */
@Serializable
data class StoredMessage(
    /** `"user"` 或 `"assistant"`（存字符串而不是 enum，保证将来加角色时老文件仍能读）。 */
    val role: String,
    val text: String = "",
    /** 思考过程（开思考模式时才有）。 */
    val reasoning: String = "",
    /** 工具痕迹那几行（「🔧 正在查：库存报警」），保留是为了回看时知道它查过什么。 */
    val toolTrace: List<String> = emptyList(),
    val isError: Boolean = false,
    /** epoch 毫秒 */
    val at: Long = 0L,
    /** 这条答复消耗的 token（多轮工具调用会累加）。 */
    val tokens: Int = 0,
    /**
     * 这条用户消息上挂着的**附件**（v3.32）：界面上那个 chip 要显示的东西
     * （文件名 + "200 行 × 5 列" + 后端给的实话）。
     *
     * 只存展示用的摘要：一张表的完整内容在 [attachmentBlock] 里，界面不需要它。
     */
    val attachments: List<StoredAttachment> = emptyList(),
    /**
     * **真正发给模型的那段话**（用户那句话 + 附件全文的 TSV）。
     *
     * 为什么必须存下来（而不是每次由 [attachments] 重新拼）：附件全文是**服务端读出来**的，
     * 手机上没有副本——不存的话下一轮提问时模型就"忘了"这张表长什么样，
     * 用户会看到"你刚不是说看过我的表吗"。
     *
     * 代价是对话文件会变大（一个附件最多约 12k 字符）。这是划算的：
     * 存的是一份文本，换的是"这个对话在任何时候都能接着聊"。
     */
    val attachmentBlock: String = "",
) {
    val isUser: Boolean get() = role == ROLE_USER

    companion object {
        const val ROLE_USER = "user"
        const val ROLE_ASSISTANT = "assistant"
    }
}

/** 存盘的一条附件摘要（界面 chip 用）。 */
@Serializable
data class StoredAttachment(
    val filename: String = "",
    val summary: String = "",
    val warnings: List<String> = emptyList(),
)

/**
 * 一个对话。
 *
 * 分支关系用 [parentId] + [branchAt] 记录：本条对话的前 [branchAt]+1 条消息是从 [parentId]
 * 那个对话复制来的。**只记血缘，不共享存储**——这样删掉父对话不会把子对话掏空，
 * 代价是分支会多占一点空间（对话本身很小，这个交换划算）。
 */
@Serializable
data class StoredConversation(
    val id: String,
    val createdAt: Long,
    val updatedAt: Long,
    /** 空 = 还没起名字（标题由第一条用户消息实时算出来，见 [AiConversations.titleOf]）。 */
    val messages: List<StoredMessage> = emptyList(),
    /** 累计消耗 token；界面上的「用量」就是它。 */
    val totalTokens: Int = 0,
    val parentId: String? = null,
    val branchAt: Int = -1,
    /**
     * 最近一次调用时服务端回报的 `prompt_tokens`——**这就是"当前上下文用了多少"的真值**
     * （见 [AiContext]：不自己数 token，用服务端白给的数）。
     */
    val contextTokens: Int = 0,
    /** 早前对话的摘要（到窗口 60% 时由 [AiCompactor] 生成）。空 = 还没压缩过。 */
    val summary: String = "",
    /** 摘要覆盖到 [messages] 的哪一条为止（不含）。0 = 没有压缩过。 */
    val compactedUpTo: Int = 0,
) {
    val isEmpty: Boolean get() = messages.isEmpty()
    val isBranch: Boolean get() = !parentId.isNullOrBlank()
}

/** 整个文件的外壳。带 version 是为了将来能迁移（现在固定 1）。 */
@Serializable
data class ConversationFile(
    val version: Int = AiConversations.FORMAT_VERSION,
    val conversations: List<StoredConversation> = emptyList(),
)

// ============================================================================
//  纯逻辑：标题 / 分支 / 复制 / 时间 / 用量 / 上限
// ============================================================================

/**
 * 对话历史的**纯函数**部分（无 Android、无文件 IO），所以能直接在 JVM 单测里跑。
 * 文件读写在 [AiConversationStore]。
 *
 * ### 为什么历史要落盘（推翻了上一版的决定）
 * 上一版刻意不持久化，理由是「对话含经营数据，不留盘更安全」。用户用下来明确了需求：
 * **要能翻历史、要能复制、要能从某一句分叉**——这三件事全都要持久化才成立。
 * 所以改成落盘，但把风险控制在这几点上：
 * 1. 只写 App 私有目录（`filesDir`，其他 App 无 root 读不到），不写外部存储、不上传服务器；
 * 2. **有硬上限**（[MAX_CONVERSATIONS] / [MAX_MESSAGES_PER_CONVERSATION] / [MAX_TEXT_LENGTH]），
 *    不会无限膨胀把手机塞满；
 * 3. 用户可单条删除、可整体清空（设置页与抽屉都有入口）。
 */
object AiConversations {

    /** 盘上格式版本。 */
    const val FORMAT_VERSION = 1

    /** 最多留多少个对话（按更新时间留最新的一批）。 */
    const val MAX_CONVERSATIONS = 50

    /** 单个对话最多留多少条消息（超出丢最早的）。 */
    const val MAX_MESSAGES_PER_CONVERSATION = 200

    /** 单条消息文本上限（一条消息长到几万字一定是异常，截断比崩了强）。 */
    const val MAX_TEXT_LENGTH = 8000

    /**
     * 单条消息**附件正文**的上限。
     *
     * 比 [AiAttachment.MAX_PROMPT_CHARS]（单个附件的预算）宽松一倍：一条消息可以挂 3 个附件，
     * 按"一个附件的预算"卡会把合法的多附件消息砍掉一半。这里的数字只防"盘上文件失控"，
     * 不承担"控制模型上下文"的职责——那是 [AiContext] 的活。
     */
    const val MAX_ATTACHMENT_BLOCK = 36000

    /** 抽屉里标题的最大字数。 */
    private const val TITLE_MAX = 16

    private val json = Json {
        ignoreUnknownKeys = true   // 旧版本多写的字段不该让整份文件读不出来
        encodeDefaults = true
        explicitNulls = false
    }

    /** 新对话 id。用 UUID 而不是自增：将来多设备/多入口都不会撞。 */
    fun newId(): String = UUID.randomUUID().toString()

    /** 一个全新的空对话。 */
    fun blank(id: String = newId(), now: Long = System.currentTimeMillis()): StoredConversation =
        StoredConversation(id = id, createdAt = now, updatedAt = now)

    /**
     * 标题 = 第一条**用户**消息的前 [TITLE_MAX] 字。没有用户消息时返回「新对话」。
     * 不用模型生成标题：多一次调用 = 多花用户的钱，而第一句话本身就已经足够说明。
     *
     * ⚠️ 只发了附件、一个字都没打的对话（附件那条路上完全合法）也要有标题：
     * 否则抽屉里会出现一行「新对话」，用户认不出那是哪一次。
     * 这时用附件名当标题——它比任何自动生成的概述都更接近用户心里那句话。
     */
    fun titleOf(conv: StoredConversation): String {
        val first = conv.messages.firstOrNull { it.isUser && it.text.isNotBlank() }
            ?: conv.messages.firstOrNull { it.text.isNotBlank() }
        val line = first?.text?.replace('\n', ' ')?.trim().orEmpty()
        if (line.isNotBlank()) {
            return if (line.length <= TITLE_MAX) line else line.take(TITLE_MAX) + "…"
        }
        // 只发了附件、一个字都没打：用附件名当标题（它比任何自动生成的概述都更接近
        // 用户心里那句话）。没有这一步，抽屉里会出现一行「新对话」，认不出是哪一次。
        val file = conv.messages.firstOrNull { it.attachments.isNotEmpty() }
            ?.attachments?.first()?.filename.orEmpty()
        if (file.isNotBlank()) {
            val t = "📄 $file"
            return if (t.length <= TITLE_MAX) t else t.take(TITLE_MAX) + "…"
        }
        return NEW_CHAT_TITLE
    }

    const val NEW_CHAT_TITLE = "新对话"

    /** 重新累计用量（分支/复制后必须重算，否则会把父对话的用量也算进来）。 */
    fun recount(conv: StoredConversation): StoredConversation =
        conv.copy(totalTokens = conv.messages.sumOf { it.tokens })

    /**
     * 从第 [upToIndex] 条消息（含）分叉出一个新对话。
     *
     * 语义对齐主流 AI 软件：**你改主意的那一刻之前的上下文照旧，之后重新问**。
     * 所以复制 `messages[0..upToIndex]`，并记下血缘。
     *
     * @param upToIndex 越界时自动夹到合法范围（界面传进来的下标不该让崩溃发生）。
     */
    fun branch(
        conv: StoredConversation,
        upToIndex: Int,
        newId: String = newId(),
        now: Long = System.currentTimeMillis(),
    ): StoredConversation {
        val end = upToIndex.coerceIn(-1, conv.messages.lastIndex)
        val kept = if (end < 0) emptyList() else conv.messages.take(end + 1)
        return recount(
            StoredConversation(
                id = newId,
                createdAt = now,
                updatedAt = now,
                messages = kept,
                parentId = conv.id,
                branchAt = end,
            ),
        ).let { cap(it) }
    }

    /** 整段复制成一个新对话（不断血缘，就是一份副本）。 */
    fun duplicate(
        conv: StoredConversation,
        newId: String = newId(),
        now: Long = System.currentTimeMillis(),
    ): StoredConversation = recount(
        StoredConversation(
            id = newId,
            createdAt = now,
            updatedAt = now,
            messages = conv.messages,
        ),
    ).let { cap(it) }

    /** 追加一条消息并更新时间/用量。 */
    fun append(conv: StoredConversation, msg: StoredMessage, now: Long = System.currentTimeMillis()): StoredConversation =
        cap(conv.copy(messages = conv.messages + msg, updatedAt = now))

    /** 就地替换某条消息（流式/工具痕迹增长时用）。 */
    fun replaceAt(conv: StoredConversation, index: Int, msg: StoredMessage, now: Long = System.currentTimeMillis()): StoredConversation {
        if (index !in conv.messages.indices) return conv
        val list = conv.messages.toMutableList().also { it[index] = msg }
        return cap(conv.copy(messages = list, updatedAt = now))
    }

    /** 执行上限：截断文本、丢最早的消息、重算用量。 */
    fun cap(conv: StoredConversation): StoredConversation {
        val trimmed = conv.messages
            .map { m ->
                var out = m
                if (out.text.length > MAX_TEXT_LENGTH) {
                    out = out.copy(text = out.text.take(MAX_TEXT_LENGTH) + "\n…（过长已截断）")
                }
                // 附件正文同样要有上限：它挂在**用户消息**上，一条就是十几 k 字符，
                // 不封顶的话"发了三个附件的对话"光这一项就能把盘上的文件撑到几百 k。
                // 上限比单个附件自己的预算宽松一倍（预算是按"一个附件"定的，一条消息可有多个）。
                if (out.attachmentBlock.length > MAX_ATTACHMENT_BLOCK) {
                    out = out.copy(
                        attachmentBlock = out.attachmentBlock.take(MAX_ATTACHMENT_BLOCK) +
                            "\n…（附件内容过长，已截断：后面几行没有存下来）",
                    )
                }
                out
            }
            .let { if (it.size <= MAX_MESSAGES_PER_CONVERSATION) it else it.takeLast(MAX_MESSAGES_PER_CONVERSATION) }
        return recount(conv.copy(messages = trimmed))
    }

    /** 列表级上限：按更新时间留最新 [MAX_CONVERSATIONS] 个，并逐个 [cap]。 */
    fun capAll(list: List<StoredConversation>): List<StoredConversation> =
        list.sortedByDescending { it.updatedAt }.take(MAX_CONVERSATIONS).map { cap(it) }

    /**
     * 按 id 合并两份列表：**同 id 以 [incoming] 为准**，[onDisk] 里独有的原样保留。
     *
     * ### 它防的是一次真实的**数据丢失**
     * [AiChatViewModel] 的 `all`（全部对话）是**异步**从盘上读进来的。读过之前它是空列表，
     * 而 `send()` 一进来就会落盘一次——那一刻若按空列表重算，**写下去的就是"只有当前这一段"**，
     * 用户之前所有对话当场消失。实测丢过一次（3 段对话只剩 1 段）。
     *
     * 所以存储层再加一道：**在"从未读过盘"这个前提下**保存时，改覆盖为合并。
     * 之所以在这个前提下合并是安全的：调用方还没见过盘上的内容，**不可能表达"删除某一段"的意图**，
     * 所以不存在"把用户删掉的对话又复活"的风险。
     */
    fun mergeById(
        onDisk: List<StoredConversation>,
        incoming: List<StoredConversation>,
    ): List<StoredConversation> {
        val byId = LinkedHashMap<String, StoredConversation>(onDisk.size + incoming.size)
        onDisk.forEach { byId[it.id] = it }
        incoming.forEach { byId[it.id] = it }
        return capAll(byId.values.toList())
    }

    /** 盘上文件的字节预算（见 [fitToBudget]）。 */
    const val MAX_FILE_BYTES = 2 * 1024 * 1024

    /**
     * 按**字节预算**裁剪：条数与字数都合规，也可能因为消息很长而超出预算
     * （50 × 200 × 4000 字最坏情况有几十 MB），所以再加一道总量闸。
     *
     * 策略：按更新时间从新到旧装，装不下的**整条丢弃**（丢最旧的）；
     * 万一**最新的这一条自己就超预算**，就把它最前面的消息一条条丢掉，直到装得下
     * ——绝不出现「为了省空间把用户当前这段对话整个删掉」。
     */
    fun fitToBudget(
        list: List<StoredConversation>,
        maxBytes: Int = MAX_FILE_BYTES,
    ): List<StoredConversation> {
        val capped = capAll(list)
        if (capped.isEmpty()) return capped
        val sizes = capped.map { encodedSize(it) }

        var total = 0
        val keep = ArrayList<StoredConversation>(capped.size)
        for (i in capped.indices) {
            // 最新的一条无论多大都先留下（下面再单独瘦身），否则用户当前这段对话会被整个丢掉
            if (keep.isNotEmpty() && total + sizes[i] > maxBytes) break
            total += sizes[i]
            keep += capped[i]
        }

        // 只留下一条却还是超标 → 从**最早的消息**开始丢，直到装得下
        if (keep.size == 1 && total > maxBytes) {
            var solo = keep[0]
            while (solo.messages.size > 1 && encodedSize(solo) > maxBytes) {
                solo = solo.copy(messages = solo.messages.drop(1))
            }
            return listOf(recount(solo))
        }
        return keep
    }

    /** 单条对话序列化后的 UTF-8 字节数（估算总占用用）。 */
    private fun encodedSize(conv: StoredConversation): Int =
        json.encodeToString(StoredConversation.serializer(), conv).toByteArray(Charsets.UTF_8).size

    // ------------------------------------------------------------------ 复制成文本

    /**
     * 整段对话转成可粘贴的纯文本（「复制全文」用）。
     *
     * 刻意**不带思考过程和工具痕迹**：用户复制出去是要发给别人看的，过程信息只会添乱。
     * 带头部（标题 + 时间 + 用量）是因为粘贴到聊天软件里必须能看出「这是哪一段、什么时候的」。
     */
    fun toPlainText(
        conv: StoredConversation,
        zone: ZoneId = ZoneId.systemDefault(),
    ): String {
        // 用量**现算**而不是读 conv.totalTokens：存下来的那个字段有可能落后于消息列表
        // （比如老版本写的文件、或某次改完忘了重算），复制出去的数字必须是自洽的。
        val tokens = recount(conv).totalTokens
        val head = buildString {
            append("【AI 助手对话】").append(titleOf(conv))
            append("\n时间：").append(dateTimeLabel(conv.createdAt, zone))
            if (tokens > 0) append("　用量：").append(tokenLabel(tokens))
            if (conv.isBranch) append("\n（由历史对话分叉而来）")
            append("\n")
        }
        val body = conv.messages
            .filter { it.text.isNotBlank() }
            .joinToString("\n\n") { m ->
                (if (m.isUser) "【我】" else "【助手】") + "\n" + m.text.trim()
            }
        return if (body.isBlank()) head else head + "\n" + body
    }

    // ------------------------------------------------------------------ 时间 / 用量显示

    /**
     * 列表里那一行时间：今天 `14:32`、昨天 `昨天 09:12`、今年 `9月3日`、更早 `2025年12月1日`。
     *
     * 格式化一律锁 [Locale.US]：`%d`/`%f` 在部分语言环境下会输出阿拉伯-印度数字或逗号小数点
     * （德语是 `1,5`），那会让界面出现用户看不懂的时间。
     */
    fun timeLabel(at: Long, now: Long = System.currentTimeMillis(), zone: ZoneId = ZoneId.systemDefault()): String {
        if (at <= 0L) return ""
        val t = instant(at, zone)
        val d = t.toLocalDate()
        val today = instant(now, zone).toLocalDate()
        val hm = String.format(Locale.US, "%02d:%02d", t.hour, t.minute)
        return when {
            d == today -> hm
            d == today.minusDays(1) -> "昨天 $hm"
            d.year == today.year -> "${d.monthValue}月${d.dayOfMonth}日"
            else -> "${d.year}年${d.monthValue}月${d.dayOfMonth}日"
        }
    }

    /** 完整时间戳（复制全文的头部用）。 */
    fun dateTimeLabel(at: Long, zone: ZoneId = ZoneId.systemDefault()): String {
        if (at <= 0L) return ""
        val t = instant(at, zone)
        return String.format(
            Locale.US, "%04d-%02d-%02d %02d:%02d",
            t.year, t.monthValue, t.dayOfMonth, t.hour, t.minute,
        )
    }

    /**
     * 消息气泡下面的小字时间：同一天只给 `HH:mm`，跨天补上日期。
     *
     * [today] 之所以做成参数而不是内部 `LocalDate.now()`：这样单测能固定"今天"，
     * 否则这个函数只能在半夜前后测（那种测试比没有还糟）。
     */
    fun clockLabel(
        at: Long,
        zone: ZoneId = ZoneId.systemDefault(),
        today: LocalDate = LocalDate.now(zone),
    ): String {
        if (at <= 0L) return ""
        val t = instant(at, zone)
        val d = t.toLocalDate()
        val hm = String.format(Locale.US, "%02d:%02d", t.hour, t.minute)
        return if (d == today) hm else "${d.monthValue}月${d.dayOfMonth}日 $hm"
    }

    /** 用量显示：小于 1000 给整数，超过给 `1.2k`（老人友好：不出现一长串数字）。 */
    fun tokenLabel(tokens: Int): String = when {
        tokens <= 0 -> "0 tokens"
        tokens < 1000 -> "$tokens tokens"
        else -> String.format(Locale.US, "%.1fk tokens", tokens / 1000.0)
    }

    private fun instant(at: Long, zone: ZoneId) = Instant.ofEpochMilli(at).atZone(zone)

    // ------------------------------------------------------------------ 编解码

    /**
     * 序列化成盘上文本。
     *
     * **落盘前一定过 [fitToBudget]**：这是"手机存储不会被聊天记录撑爆"的唯一保证，
     * 不要为了省一点 CPU 改成 `capAll`。
     */
    fun encode(list: List<StoredConversation>): String =
        json.encodeToString(ConversationFile.serializer(), ConversationFile(conversations = fitToBudget(list)))

    /**
     * 解析盘上文本。**任何问题都不抛异常**，读不出来就返回空列表
     * （调用方 [AiConversationStore] 会把坏文件改名留证，而不是直接覆盖掉）。
     */
    fun decode(text: String): List<StoredConversation> {
        if (text.isBlank()) return emptyList()
        return try {
            json.decodeFromString(ConversationFile.serializer(), text)
                .conversations
                .filter { it.id.isNotBlank() }
                .let { capAll(it) }
        } catch (e: Exception) {
            emptyList()
        }
    }

    /** 把界面上的历史消息转成存盘格式（供 ViewModel 调用，避免两边各写一套字段映射）。 */
    fun message(
        isUser: Boolean,
        text: String,
        reasoning: String = "",
        toolTrace: List<String> = emptyList(),
        isError: Boolean = false,
        at: Long = System.currentTimeMillis(),
        tokens: Int = 0,
        attachments: List<StoredAttachment> = emptyList(),
        attachmentBlock: String = "",
    ): StoredMessage = StoredMessage(
        role = if (isUser) StoredMessage.ROLE_USER else StoredMessage.ROLE_ASSISTANT,
        text = text,
        reasoning = reasoning,
        toolTrace = toolTrace,
        isError = isError,
        at = at,
        tokens = tokens,
        attachments = attachments,
        attachmentBlock = attachmentBlock,
    )
}
