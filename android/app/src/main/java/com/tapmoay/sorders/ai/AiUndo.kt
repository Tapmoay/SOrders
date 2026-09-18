package com.tapmoay.sorders.ai

import kotlinx.serialization.json.JsonObject

/**
 * 一次 AI 写操作的**撤回方案**。
 *
 * ### 为什么"撤回"不直接执行，而是再弹一张卡
 * 因为整套设计只有一条写入口：[AiWritePreviewStore.offer] 造卡 → 用户在界面上点确认 →
 * [AiWriteService.execute] → `handler.commit`。撤回如果能自己写库，就等于**开了第二条写入口**，
 * 那条路上没有角色门、没有风险档、也没有"一次性 token"——
 * 而这一整块功能最不能出的错，就是"某个入口能不问用户就改数据"。
 *
 * 所以撤回被表达成**另一个已有的写动作 + 一份已经拼好的 payload**：
 * 卡片照弹、用户照点、`commit` 照走。代价是撤回要两次点击（撤回 → 确认），
 * 换来的是"撤回这条路和别的事一样安全"。
 *
 * ### 为什么 payload 里是编号而不是名字
 * 模型给的是名字（它只认识名字），而撤回发生在**用户已经看过结果之后**：
 * 那时被删的那条可能已经不在了，再按名字去解析会解析不到（或者解析到同名的另一条）。
 * 撤回的快照是 App 自己在写之前抓的，它拿着的是**确定的编号**，所以直接用编号。
 * 这不是"把编号给模型"——payload 从来不出 App（见 [AiPendingWrite.payload]）。
 */
data class AiUndoPlan(
    /** 撤回要走的动作（例如删地址 → [AiWrites.ADDRESS_CREATE]）。 */
    val actionId: String,
    /** 卡片标题那一行（"撤回：把地址加回来"）。 */
    val summary: String,
    /** 卡片明细：撤回会具体做什么 + 恢复不了的部分。 */
    val detailLines: List<String>,
    /** 已经拼好的 payload（编号形式），确认后原样发给 [AiWriteHandler.commit]。 */
    val payload: JsonObject,
    /** 聊天里那个撤回按钮上的字（"撤回：删除地址 张三 测试路 1 号"）。 */
    val label: String,
    /**
     * 点撤回的**那一刻**再读一次现状，返回要补在卡片上的几行（v3.27）。
     *
     * ### 为什么需要它
     * 撤回卡上的"改回 X"是拿**几十分钟前**抓的快照写的。中间这段时间里，
     * 这条记录完全可能被用户自己、被同事、被另一个入口改过。用户点一下撤回，
     * 会把后来那些改动**一起抹掉**——而他完全不知道。
     *
     * 所以弹卡之前再读一次：现在是别的值就写一行警告（"司机运费 现在是 500.00
     * （撤回会写成 300.00）"），让用户在**点确认之前**看见。
     *
     * null = 这个方案没法再读（例如"再做一次"型，或者拿不到主键）。
     */
    val probe: (suspend () -> List<String>)? = null,
)

/**
 * 撤回方案的暂存区（App 本地内存，**不上传、不落盘**）。
 *
 * 三个不变量，和 [AiWritePreviewStore] 一致（那一套已经被真机验证过）：
 * 1. **取走即删除**：一个撤回 token 只能用一次，连点两下不会撤两次；
 * 2. **会过期**：默认 30 分钟。过期之后按钮还在（消息是持久的），但点了会得到
 *    「撤回入口已过期」——**如实说**，而不是假装撤了；
 * 3. **有条数上限**：最多留 [MAX_ENTRIES] 条，超了丢最旧的（只影响"还能不能撤"，
 *    不影响已经写进去的数据）。
 */
class AiUndoStore(
    private val ttlMs: Long = DEFAULT_TTL_MS,
    private val clock: () -> Long = { System.currentTimeMillis() },
) {

    private data class Entry(val plan: AiUndoPlan, val at: Long)

    private val items = LinkedHashMap<String, Entry>()

    /** 收下一个撤回方案，返回它的 token（给聊天页那个按钮用）。 */
    fun offer(plan: AiUndoPlan): String {
        purgeExpired()
        while (items.size >= MAX_ENTRIES) {
            val oldest = items.keys.firstOrNull() ?: break
            items.remove(oldest)
        }
        val token = randomToken()
        items[token] = Entry(plan, clock())
        return token
    }

    /** 取走并删除。null = 没有这条 / 已经用过 / 已过期 / App 重启过（内存没了）。 */
    fun take(token: String): AiUndoPlan? {
        val e = items.remove(token) ?: return null
        return if (clock() - e.at > ttlMs) null else e.plan
    }

    /** 现在还有几条可撤回（设置页/排障用；界面不做展示）。 */
    fun size(): Int {
        purgeExpired()
        return items.size
    }

    private fun purgeExpired() {
        val now = clock()
        items.entries.removeAll { now - it.value.at > ttlMs }
    }

    companion object {
        /**
         * 撤回窗口。30 分钟是"够用"和"别太久"之间取的：
         * 用户发现做错了通常在几分钟内（看一眼列表/对一下账）；
         * 窗口太长的话，一条几小时前的消息上挂着「撤回」按钮反而是个陷阱。
         */
        const val DEFAULT_TTL_MS: Long = 30 * 60 * 1000L

        /** 最多同时留 8 条撤回入口。 */
        const val MAX_ENTRIES: Int = 8

        private val ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"

        private fun randomToken(): String =
            (1..16).map { ALPHABET.random() }.joinToString("")
    }
}
