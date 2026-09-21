package com.tapmoay.sorders.ai

import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.putJsonArray

/**
 * **批量捷径**：一次调用改多条 —— 一张卡列全部行、确认一次、逐条如实汇报。
 *
 * ### 用户为什么要它（2026-09-21 原话）
 * 「给 AI 搞一个捷径：他既可以**批量操作**一些功能和数据，又可以对**单个**进行调整…
 * 如果他只能单个调整，他就要一个一个去调方法，这样也费 token。」
 * 追问后拍板：**不设条数上限**（范围由用户自己定）、**一张卡列全部行、确认一次**。
 *
 * ### 为什么是一个**装饰器**（而不是在每个处理器里加批量分支）
 * 用户同一天定的另一条准则：「**核心逻辑不要乱动**，其他的以插件的形式 ——
 * **能调方法调方法、能继承就继承、能调 API 就调 API**」（见 `docs/CORE_AND_EXTENSION.md`）。
 * 批量正好是"外面再包一层"：`prepare` 逐条调用**既有处理器**，`commit` 逐条调用**既有处理器**。
 * 50 多个处理器**一行都不用改**，而以后新加的动作自动就有批量。
 *
 * ### 一次调用、一张卡（用户选的形态）
 * - 模型：`preview_write(action=…, params={ "items": [ {…}, {…} ] })`；
 * - App：逐条跑 `prepare`（校验 + 名字→编号 + 算改动），**任何一条不合法就整批不发**，
 *   错误里带**第几条**（核对 20 行时看不出少了哪一行，是这个项目最怕的一类反馈）；
 * - 卡片：首行写「批量X：N 条」，然后逐条列出（见 [rowLines]）；
 * - 确认一次 → 逐条 `commit`，逐条 try/catch，结果用 [commitNote] 如实汇报
 *   （"已完成"盖住失败行是最坏的反馈，见 `AiWriteHandler.commitNote` 的 KDoc）。
 *
 * ### 四条不变量（改这个文件之前先读完）
 * 1. **批量永远要确认**：自动执行档（[AiWriteRisk.AUTO_EXECUTABLE]）的动作**拒绝**批量。
 *    不只是"信任"——那些处理器在 `prepare` 里就已经写完了（消息全标已读），
 *    放它进批量＝在**预览阶段**就写库，而预览阶段根本不该写任何东西。
 * 2. **不挂撤回**：撤回方案是"这条记录改前长什么样"，一批 N 条要 N 份快照，一张卡上放不下。
 *    所以卡片最后一行如实写明（[AiWrites.BATCH_UNDO_NOTE]），不留"点了确认发现什么都撤不了"。
 * 3. **内层登记的单条卡要取走**：逐条 `prepare` 时，每个处理器都会按既有契约在暂存区登记一张卡
 *    （`store.offer`）。那些卡用户永远看不到（token 不在任何界面上），但会挤掉真正待确认的卡
 *    （暂存区是有限长的）。⛔ 只取**这一次新产生**的：`offer` 会按"动作 + payload"去重，
 *    命中时返回的是**用户手里那张**，删掉它就等于把用户的卡偷走了。
 * 4. **逐条汇报，不吞失败**：任何一条抛异常都要记下来并写进 [commitNote]；
 *    [CancellationException] 原样抛出（用户主动中止不是"失败"，吞掉它会让上层以为写完了）。
 *
 * ### 代价（如实写在这里，不藏着）
 * 逐条 `prepare` 会**逐条查名册**（每个处理器自己那几次网络往返），所以上百条的批在**预览阶段**
 * 就是几分钟 —— 换来的是"用户只点一次确认"。因此**范围特别大**时应该优先用本来就有"全量语义"的
 * 动作（`price_rules.batch` 的「留空 = 全部」一次请求做完），批量是给"用户点名的那一批"用的。
 */
internal class BatchWriteHandler(
    private val action: AiWriteAction,
    private val inner: AiWriteHandler,
    private val store: AiWritePreviewStore,
) : AiWriteHandler {

    override val actionId: String get() = inner.actionId

    /** [commitNote] 的内容：取走即清空（与接口约定一致，避免下一次执行读到上一次的残留）。 */
    private var note: String? = null

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val raw = params[BATCH_ITEMS] ?: return inner.prepare(params)
        val items = raw as? JsonArray
            ?: throw AiWriteArgException("`items` 要是一个数组，形如 [{…},{…}]（每一条一个参数对象）。")
        if (items.isEmpty()) {
            throw AiWriteArgException("`items` 是空的 —— 这一批一条都没有。请把每一要改的东西写成数组里的一项。")
        }
        // ---- 不变量 1：自动执行档不许走批量 ----
        if (action.risk == AiWriteRisk.AUTO_EXECUTABLE) {
            throw AiWriteArgException(
                "「${action.title}」本来就不需要确认（一次全量生效），不能再套一层批量。" +
                    "直接调它一次就行。",
            )
        }

        val known = store.list().mapTo(HashSet()) { it.token }
        val rows = ArrayList<AiPendingWrite>(items.size)
        try {
            items.forEachIndexed { i, el ->
                val item = el as? JsonObject
                    ?: throw AiWriteArgException("`items` 第 ${i + 1} 项不是参数对象（每一项都要写成 {…}）。")
                // ⚠️ 处理器按契约是**抛** `AiWriteArgException` 的（`AiWriteService.preview` 负责
                //    把它翻成给模型的一句话）。批量这一层必须自己接住，把"第几条"补上——
                //    否则用户看到的是「系统里没有匹配「X」的商品」，而不知道那是 20 条里的哪一条。
                val out = try {
                    inner.prepare(item)
                } catch (e: CancellationException) {
                    throw e
                } catch (e: AiWriteArgException) {
                    throw AiWriteArgException("第 ${i + 1} 条：${e.message ?: "参数不正确。"}", e.candidates)
                }
                rows += row(i, out)
            }
        } finally {
            // 不变量 3：把这一次新登记的内层单条卡取走（见 KDoc）。
            store.list().filter { it.token !in known }.forEach { store.take(it.token) }
        }

        val card = store.card(
            actionId = action.id,
            title = action.title,
            risk = action.risk,
            summary = "批量${action.title}：${rows.size} 条",
            detailLines = detailLines(rows),
            payload = buildJsonObject {
                putJsonArray(BATCH_PAYLOAD) { rows.forEach { add(it.payload) } }
            },
            batch = true,
        )
        return AiWriteOutcome.NeedConfirm(card)
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        val items = payload[BATCH_PAYLOAD] as? JsonArray
            ?: run {
                // 单条：原样交给内层，一个字都不变 —— 但**内层那句 commitNote 要原样带出去**。
                // ⚠️ 吞掉它的后果非常具体：`commitNote` 是"按表格调价"那种动作报
                //    「10 行成功、2 行失败」用的，装饰器不转发就等于**把失败行又盖住了**
                //    （那正是这个机制当初要治的病）。两条既有单测当场抓到了这个漏转发。
                inner.commit(payload, idempotencyKey)
                note = inner.commitNote()
                return
            }
        var ok = 0
        val failed = ArrayList<String>()
        val subNotes = ArrayList<String>()
        items.forEachIndexed { i, el ->
            val item = el as? JsonObject
            if (item == null) {
                failed += "#${i + 1} 这条数据不完整（不是参数对象）"
                return@forEachIndexed
            }
            try {
                // 每条一个幂等键：后端将来实现幂等时才知道"这是同一批里的第 i 条"。
                inner.commit(item, "$idempotencyKey-$i")
                ok++
                inner.commitNote()?.takeIf { it.isNotBlank() }?.let { subNotes += "第 ${i + 1} 条：$it" }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                failed += "#${i + 1} " + brief(e)
            }
        }
        note = buildString {
            append("这一批 ${items.size} 条：成功 $ok 条")
            if (failed.isEmpty()) {
                append("，全部成功。")
            } else {
                append("，失败 ${failed.size} 条 —— ").append(failed.joinToString("；"))
                append("。失败的那几条没有写进去，要重来就告诉我。")
            }
            if (subNotes.isNotEmpty()) append("\n").append(subNotes.joinToString("\n"))
        }
    }

    override fun commitNote(): String? = note.also { note = null }

    // ------------------------------------------------------------------ 内部

    /** 一条 `prepare` 的三种结果 → 卡片行 / 整批中止。 */
    private fun row(i: Int, out: AiWriteOutcome): AiPendingWrite = when (out) {
        is AiWriteOutcome.NeedConfirm -> out.pending
        is AiWriteOutcome.Rejected ->
            throw AiWriteArgException("第 ${i + 1} 条：${out.reason}", out.candidates)
        // 走到这里说明那个动作在预览阶段就写完了（不该发生：不变量 1 已经挡在前面）。
        // 一旦发生，**如实说**：整批中止，而且已经生效的那一条要讲清楚。
        is AiWriteOutcome.Done -> throw AiWriteArgException(
            "第 ${i + 1} 条在预览阶段就直接生效了（这个动作不需要确认），整批停在这里。" +
                "请告诉用户：这一条已经生效，其余没动；剩下的请一次说一条。",
        )
    }

    /**
     * 卡片信息区：**每一条都在**（用户选的就是这个形态）。
     *
     * - 条数 ≤ [VERBOSE_MAX]：每条一个小节标题 + 该条的摘要与明细 —— 逐条都能核对；
     * - 条数很多：每条压成一行（摘要 · 明细…），开头写清总条数 ——
     *   否则 200 条 × 3 行＝600 行，用户根本翻不到底，反而**不会去核对**了。
     *
     * ⚠️ 用的是 [AiPendingWrite.bodyLines]（处理器自己写的那几行），**不是** `detailLines`：
     *    后者末尾还有暂存区统一追加的那一行（「撤不回来」「会出现撤回」），
     *    照抄会把它复制 N 遍，而"批量不挂撤回"这件事由本卡最后一行单独说明。
     */
    private fun detailLines(rows: List<AiPendingWrite>): List<String> =
        if (rows.size <= VERBOSE_MAX) {
            rows.flatMapIndexed { i, r -> listOf("———— 第 ${i + 1} 条 ————", r.summary) + r.bodyLines }
        } else {
            listOf("———— 共 ${rows.size} 条（每条压成一行；点确认就按这个清单逐条执行）————") +
                rows.mapIndexed { i, r -> "${i + 1}. " + (listOf(r.summary) + r.bodyLines).joinToString(" · ") }
        }

    /** 异常 → 一行能看懂的话（后端的 4xx 说明通常在 `message` 里）。 */
    private fun brief(e: Exception): String {
        val m = e.message?.trim().orEmpty().replace('\n', ' ')
        return (if (m.isEmpty()) e.javaClass.simpleName else m).take(80)
    }

    companion object {
        /**
         * 批量参数的键名（模型传的那个）。**保留字**：任何写动作都不许再声明同名参数
         * （红线 `_check_ai_guardrails.py` 会断言）—— 否则那个动作的参数会被批量层当成一批。
         */
        const val BATCH_ITEMS = "items"

        /**
         * 批量 payload 的键（App 内部）。
         *
         * ⚠️ 刻意与 [BATCH_ITEMS] **不同名**，而且带下划线前缀：payload 是处理器自己拼的，
         * 而 `orders.return` 与退货申请那两个动作的 payload 里**已经有一个 `items`**
         * （那是"退货明细"）。用同名键的话，一次普通的退货会被 [isBatchPayload] 认成批量，
         * 然后按"一批 payload"去逐条提交 —— 两边都不会报错，只会把那一单退错。
         */
        const val BATCH_PAYLOAD = "_batch"

        /** 超过这个条数就不再逐条展开（每条压成一行），见 [detailLines]。 */
        const val VERBOSE_MAX = 20
    }
}

/**
 * 这个 payload 是**一批**吗（`commit` 走批量那条路）。
 *
 * 单条动作的 payload 永远不会带 [_batch] 这个键，所以判据是可靠的；
 * 而"哪些动作能批量"这个问题**在预览阶段**已经由 [BatchWriteHandler.prepare] 决定了，
 * 执行阶段只需要认出自己造的那张卡。
 */
internal fun isBatchPayload(payload: JsonObject): Boolean = payload[BatchWriteHandler.BATCH_PAYLOAD] is JsonArray
