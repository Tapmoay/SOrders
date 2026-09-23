package com.tapmoay.sorders.ai

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.util.UUID
import java.util.concurrent.atomic.AtomicLong

/**
 * 写操作的**风险档位**。
 *
 * ### 为什么必须分级，而不是"写操作一律弹确认"
 * 两个原因，缺一条都不成立：
 * 1. **摩擦也是成本**。给「把消息标成已读」也弹一次确认，用户会学会无脑点确认——
 *    那个习惯一旦养成，真正危险的确认（派单、收款、撤销）也就失效了。
 *    档位让"值得打断用户的"只剩下真正值得的那几种。
 * 2. **它是一条可被检查的规则**。`AiWriteRisk.LOW.needsConfirm == false` 是**代码里的常量**，
 *    不是"我们记得要小心"。红线检查会断言：只有 LOW 允许自动执行，且 LOW 的动作清单是显式枚举的。
 *
 * ### 三档的判据（判据是"后果"，不是"操作类型"）
 * - [LOW]：**不产生业务记录**，只改变"你自己看得见"的东西（已读标记等）。改错了也没有第三方受影响。
 * - [MEDIUM]：**产生一条业务记录**（账目/流水/支出）。这是一条真数据，会影响报表，
 *   但**事后能在页面上找到并改掉或删掉**——所以它需要确认，但不需要恐吓。
 * - [HIGH]：**动钱、动别人的活、或撤不回来**（派单、送达、收款、撤销、删除）。
 *   需要确认，且卡片要明确写出"影响谁"。
 *
 * ⚠️ **新增动作时先定档位再写代码**：如果拿不准，就往上取一档（MEDIUM 而不是 LOW）。
 * 取高的代价是多一次点击，取低的代价是用户被改了他不知道的数据。
 */
enum class AiWriteRisk(
    /** 卡片角标上的字。 */
    val label: String,
    /** true = 模型自己调不动，必须由用户在界面上点确认（见 [AiWritePreviewStore]）。 */
    val needsConfirm: Boolean,
    /** 卡片上的一句话说明"这事的后果是什么"。 */
    val blurb: String,
) {
    LOW("低", false, "不留业务记录"),
    MEDIUM("中", true, "会写进系统，事后可以在对应页面上改或删"),
    HIGH("高", true, "影响别人或撤不回来"),
    ;

    companion object {
        /** 允许**不经用户确认**就直接执行的那一档。**只有 LOW。** */
        val AUTO_EXECUTABLE: AiWriteRisk = LOW
    }
}

/** 参数类型。只用来生成给模型看的说明，不参与校验（校验在 [AiWriteService] 里按动作逐条做）。 */
enum class AiWriteParamKind(val cn: String) {
    TEXT("文本"),
    NUMBER("数字"),
    DATE("日期"),
    ENUM("枚举"),
}

/**
 * 一个写动作的一个参数。
 *
 * 这里的 `cn` 是**给模型看的中文名**（"油费/维修"这种），不是给用户看的——
 * 用户看的是卡片摘要，由 [AiWriteAction] 的 `summary` 渲染。
 */
data class AiWriteParam(
    val name: String,
    val cn: String,
    val required: Boolean = false,
    val kind: AiWriteParamKind = AiWriteParamKind.TEXT,
    val hint: String = "",
    val enumValues: List<String> = emptyList(),
)

/**
 * AI 能服务的角色。**司机端不开放**（他的需求最小，以后只做"查订单价格"）。
 *
 * 权限阶梯：**派单员 > 货主 > 司机**。这不是我们自己定的，是后端 `ROLE_PERMISSIONS`
 * 已经定好的事实——AI 只是照着它裁剪，不是另立一套：
 *
 * | 角色 | 后端权限点 |
 * | --- | --- |
 * | dispatcher | 18 个（含 order:dispatch / product:manage / user:manage / price_rule:manage …） |
 * | shipper | 6 个：order:create、order:cancel_shipper、order:read_own、ledger:read_own、notification:read、order:delete_cancelled |
 * | driver | 5 个：order:complete_driver、order:internal_note、order:read_assigned、order:upload_delivery、notification:read |
 *
 * ⚠️ 裁剪必须发生在**服务层**，不能只靠界面隐藏：界面藏起来的动作，模型仍然能从提示词里
 * 知道它存在；更糟的是它可以被越权调用。所以 AiWriteService.preview 会再查一次角色。
 */
enum class AiRole(val key: String, val cn: String) {
    DISPATCHER("dispatcher", "派单员"),
    SHIPPER("shipper", "货主"),
    ;

    companion object {
        fun fromKey(key: String?): AiRole? =
            entries.firstOrNull { it.key.equals(key?.trim(), ignoreCase = true) }
    }
}
/**
 * 一个**业务写动作**（不是一次调用）。
 *
 * ### 它和工具的关系
 * 工具只有两个入口：`preview_write`（申请）和界面上的确认按钮（执行）。
 * 一个动作**不是**一个工具——否则 20 个动作就是 20 个工具，每个都要单独开关、
 * 单独写描述，而且模型会把"动作选择"和"参数填写"混在一起出错。
 * 这里用 [AiReadCatalog] 同一套办法：**一个受白名单约束的通道 + 编译期定死的动作清单**。
 *
 * @param id 模型要原样照抄的标识（`模块.动作`）。
 * @param title 中文短名，卡片标题与设置页用。
 * @param risk 见 [AiWriteRisk]。**它决定要不要用户确认，模型无法影响这个判断。**
 * @param blurb 给模型看的一句话：这个动作干什么。
 * @param params 参数清单，用来生成给模型的说明并做必填校验。
 */
data class AiWriteAction(
    val id: String,
    val title: String,
    val risk: AiWriteRisk,
    /** 中文域（"订单"/"商品"/"账号"…）。只用于把清单分组，让模型和文档都看得清。 */
    val group: String,
    val blurb: String,
    val params: List<AiWriteParam>,
    /**
     * 非 null = 这是一个**通用 CRUD 动作**，由 [CrudWriteHandler] 按这份规格执行。
     * null = 由手写处理器执行（那些需要特殊状态核对或多步解析的动作）。
     *
     * 分成两条路不是妥协，是分工：订单动作要"先查单、核对状态、再弹卡"，
     * 这一类逻辑每个都不一样，手写更清楚；而"改个商品名""加个联系人"这种，
     * 26 个动作各写一遍校验和 payload 拼装，只会让"漏了一个上限"变成必然。
     */
    val crud: CrudSpec? = null,
    /**
     * true = **只给撤回用**，不进模型的动作清单（v3.26）。
     *
     * 为什么要有这个标记：被软删的记录已经从名册里消失了，模型按名字根本解析不到它
     * ——"恢复一条你看不见的记录"是个说不通的需求。但撤回路径拿着的是**确定的编号**，
     * 不需要解析名字，所以这些动作必须存在，只是不该出现在模型面前。
     *
     * 少了这个标记的后果很具体：模型清单里会多出 7 个"能看见但一定失败"的动作，
     * 而红线早就把"能看见但用不了"列为最坏的一类 bug。
     */
    val undoOnly: Boolean = false,
    /**
     * true = **只有批发商货主**（`users.is_member=1`）能用。
     *
     * 2026-09-20 用户第七轮：「AI 也会分成 2 个：一个是普通货主、一个是批发商货主的 AI……
     * 他不能越权，批发商没有的功能 AI 也做不到；普通货主**手机做不到的事情，AI 也做不到**」。
     * 核销那三个动作就是这一类的全部：手机上只有批发商那本账上有「核销」按钮，
     * 普通货主那一页连这一段都不画 —— 所以普通货主的 AI **连清单里都不该出现它**。
     *
     * ⚠️ 与"发卡时再拦"不是一回事：只在 `prepare` 里问一句 `isMemberShipper()`，
     *    普通货主仍然会**看见**这三个动作（工具说明里写着、模型会照它解释），
     *    只是点下去必然失败。能力清单本身分叉，才是用户说的"两个 AI"。
     *
     * ⛔ 同一个标记顺带把**派单员**挡住：这三个动作打的是货主自己那一本账
     *    （后端 `shipper_ledger.py` 是 `require_roles(SHIPPER)`），派单员本来就不该有。
     *    （原来 `forRole(DISPATCHER) = ALL` 把它一起给了派单员 —— 一类"能看见但一定失败"的卡。）
     */
    val memberOnly: Boolean = false,
    /**
     * 非 null = 这个动作**只属于这几个角色**（`null` = 老口径：谁都按 [AiWrites.forRole] 的规则拿）。
     *
     * ### 为什么 `memberOnly` 不够，还需要它（2026-09-21 退货申请这一轮踩到的）
     * `forRole(DISPATCHER) = ALL.filter { !it.memberOnly }` —— 派单员拿的是**全表减会员专属**。
     * 于是"申请退货""撤回退货申请"这两个**本该只有货主**的动作落进了派单员清单：
     * 后端 `submit()` 会以「这不是你的订单」拒绝（`order.shipper_id != current.id`），
     * 也就是**派单员看到两张点下去必然失败的卡** —— 本仓库明确列为最坏的一类 bug。
     *
     * ⛔ 别把它做成"再写一条 `dispatcherOnly` 布尔"：那一维迟早要变成第三、第四个角色
     *    （司机端已经在做），而 `Set<AiRole>` 加角色时不用改判据。
     *
     * ⚠️ 两个方向的过滤都要走它（见 [forRole]）：只顺手过滤一边，
     *    另一边就会多出"能看见但一定失败"的动作 —— 而那正是这个字段要治的病。
     */
    val roles: Set<AiRole>? = null,
)

/**
 * 一次**待确认**的写操作。
 *
 * ### 三个不变量（每一条都是踩过坑的结论，改代码前先读完）
 * 1. **[token] 由 App 生成，模型永远看不到它**。模型只能通过 `preview_write` *申请*，
 *    真正执行只能由界面上的按钮触发。
 *    ——Operit 的反面教材：它用 `!invocation.rawText.contains("deny_tool")` 判断权限，
 *    权限决定建立在**模型可控的文本**上，模型改一句话就绕过去了。
 *    这里的 token 从不进入任何提示词、不进工具返回值，模型没有可乘之机。
 * 2. **[payload] 在预览时就拼好了，用户确认后原样发出**。
 *    不是"确认时再按参数重算一遍"——那样"用户看到的"和"真正写进去的"是两条路径，
 *    迟早会分叉（而且分叉的那天不会有任何报错）。
 * 3. **[summary]/[detailLines] 和 [payload] 由同一份已解析参数渲染**。
 *    所以卡片上写的名字，就是后端真正收到的那条记录。
 *
 * @param payload 真正发给后端的请求体。**里面含内部编号，绝不可回给模型**。
 * @param expiresAtMs 过期时刻。过期后 [AiWritePreviewStore.take] 拿不到它。
 */
data class AiPendingWrite(
    val token: String,
    val actionId: String,
    val title: String,
    val risk: AiWriteRisk,
    /** 卡片正文一行：如「支出：油费 300.00 元」。 */
    val summary: String,
    /** 卡片明细：日期、对象、备注等，逐行一个「标签：值」。 */
    val detailLines: List<String>,
    /**
     * 处理器自己写的那几行（**不含**暂存区统一追加的最后一行：撤回 / 撤不回来）。
     *
     * ### 为什么要把它们分开（2026-09-21 批量那一轮）
     * 卡片最后那一行是由 [AiWritePreviewStore.offer] 按**动作**算出来的（[AiWrites.undoLineOf]
     * 或 [AiRevert.undoCardLine]）。批量层要把每一条的明细复制到那张汇总卡上，
     * 照抄 [detailLines] 就会把"会出现撤回"复制 N 遍 —— 而那句话对批量是**假的**
     * （批量不挂撤回，见 [AiWrites.BATCH_UNDO_NOTE]）。
     * 界面上仍然是 `detailLines`（一个字没变），这里只是**多留一份没被追加过的**。
     */
    val bodyLines: List<String> = detailLines,
    val payload: JsonObject,
    val createdAtMs: Long,
    val expiresAtMs: Long,
) {
    // ⛔ 这里**删掉过**两个方法（2026-09-21 精简轮）：`expired(now)` 与 `secondsLeft(now)` ——
    //    全仓搜只有它们自己的声明（界面从来没有按"还剩几秒"画过东西；过期与否由
    //    `AiWritePreviewStore.take()` 在数据层保证，那才是唯一权威）。
    //    ⚠️ 顺带修掉一处"界面上的有效期是假话"：卡片那句有效期原来照抄
    //    `AiWritePreviewStore.DEFAULT_TTL_MS`（store 的**默认值**），而 store 的 TTL 是可配置的
    //    （单测就传过别的值）→ 一旦有人配了别的 TTL，卡片上那句"5 分钟内有效"就是假的，
    //    而用户是拿它当真的看的。现在界面按**这张卡自己的窗口**（`expiresAtMs - createdAtMs`）算。
    //    要恢复倒计时的话：在这儿加回 `secondsLeft`，界面按它画（记得它要随时间刷新）。
}

/**
 * 待确认写操作的**暂存区**（内存，进程内）。
 *
 * ### 为什么是内存而不是落盘
 * 一次待确认的写操作寿命只有几分钟，跨进程重启还留着它反而危险：
 * 用户昨晚点了"记一笔 5 万"，今天打开 App 卡片还在，容易误点。
 * 重启即失效是**期望行为**，不是缺陷。
 *
 * ### 一次性
 * [take] 会**同时取走并删除**。这是"确认按钮只能生效一次"的实现——
 * 不依赖界面禁用按钮（界面禁用会被"连点两下"或状态竞争绕过），而是数据层保证。
 */
class AiWritePreviewStore(
    private val ttlMs: Long = DEFAULT_TTL_MS,
    private val maxPending: Int = MAX_PENDING,
    private val now: () -> Long = { System.currentTimeMillis() },
    private val newToken: () -> String = ::randomToken,
) {
    private val lock = Any()
    private val items = ArrayList<AiPendingWrite>(2)

    /** 登记一次待确认，返回它（含 token）。超过 [maxPending] 时丢**最旧**的。 */
    fun offer(
        actionId: String,
        title: String,
        risk: AiWriteRisk,
        summary: String,
        detailLines: List<String>,
        payload: JsonObject,
        /**
         * true = **这一张卡是「撤回」卡**。
         *
         * 为什么要传这个：卡片最后一行由这里统一按 `actionId` 拼，而撤回走的是**另一个**写动作
         * （删专属价 → 撤回走"设专属价"）。不区分的话，撤回卡上会印着被撤回动作的那句
         * 「⚠️ 这一步撤不回来」，和标题「撤回：…」互相打架（真机 E2E 抓到的原样）。
         */
        isUndo: Boolean = false,
        /**
         * true = **这一张卡是「批量」卡**（`AiWriteBatch.kt`，一次改多条）。
         *
         * 为什么最后一行要单独说：批量**不挂撤回**（一批 N 条要 N 份撤回快照，一张卡放不下），
         * 而按 `actionId` 拼出来的那一行会印「执行后会出现一个「撤回」按钮」——
         * 用户点完确认发现没有按钮，而卡片答应过有。
         */
        batch: Boolean = false,
    ): AiPendingWrite {
        synchronized(lock) {
            pruneLocked()

            // ---- 去重：同一件事申请两次，只留一张卡 ----
            // 为什么必须在数据层做，而不是靠提示词里写"别调两次"：
            // 模型重复调用是常态（某轮把工具调用重发一遍），而两张一样的卡会带来一条
            // **真实的重复写入路径**——用户先点了第一张，再看到第二张，很自然地又点一次。
            // 参数完全一样（actionId + payload 全等）时复用同一张卡，用户最多只能确认一次。
            items.firstOrNull { it.actionId == actionId && it.payload == payload }?.let { return it }

            val at = now()
            val lastLine = when {
                batch -> AiWrites.BATCH_UNDO_NOTE
                isUndo -> AiRevert.undoCardLine(actionId)
                else -> AiWrites.undoLineOf(actionId)
            }
            val p = AiPendingWrite(
                token = newToken(),
                actionId = actionId,
                title = title,
                risk = risk,
                summary = summary,
                detailLines = detailLines + listOfNotNull(lastLine),
                bodyLines = detailLines,
                payload = payload,
                createdAtMs = at,
                expiresAtMs = at + ttlMs,
            )
            items += p
            while (items.size > maxPending) items.removeAt(0)
            return p
        }
    }

    /**
     * 造一张确认卡：**卡片标题与风险档位只在这一处取**（`AiWrites` 是唯一的动作登记表）。
     *
     * ### 为什么要有这个方法（2026-09-21 精简轮）
     * 这句 `NeedConfirm(offer(actionId, title = AiWrites.titleOf(actionId), risk = AiWrites.byId(actionId)!!.risk, …))`
     * 原来在 **17 处**各写了一遍：5 个处理器里逐字相同的 `card(...)` 包装 + 12 处内联
     * `store.offer(...)`。17 份实现里任何一处写歪（标题不再来自登记表、风险档位手填、
     * 忘了传 summary）都不会报错 —— 而卡片上的标题与"要不要二次确认"正是用户唯一看得见的东西。
     *
     * ⚠️ 参数名与数据类字段一致（`AiPendingWrite.detailLines`）：叫 `details` 会让
     *    `_check_ai_guardrails.py` 里「`details = ` 的声明都定位到了」那条判据把**调用点的具名实参**
     *    也数成一次声明（分母变大 → 误报），所以这里刻意不叫 `details`。
     *
     * [title] / [risk] 留了口子（默认仍从登记表取）：声明式 CRUD 与「撤回」那条路手里已经有一个
     * `AiWriteAction` 对象，把它们传进来就与改动前一字不差。
     *
     * ⚠️ 返回的是**暂存区里的那张卡**（[AiPendingWrite]，与 [offer] 同型），不是 [AiWriteOutcome]：
     *    调用点外面本来就包着 `return AiWriteOutcome.NeedConfirm(...)`，多包一层编译不过
     *    （实测 13 处 `Argument type mismatch: actual type is 'AiWriteOutcome'`）。
     */
    fun card(
        actionId: String,
        summary: String,
        detailLines: List<String>,
        payload: JsonObject,
        title: String = AiWrites.titleOf(actionId),
        risk: AiWriteRisk = AiWrites.byId(actionId)!!.risk,
        isUndo: Boolean = false,
        batch: Boolean = false,
    ): AiPendingWrite = offer(
        actionId = actionId,
        title = title,
        risk = risk,
        summary = summary,
        detailLines = detailLines,
        payload = payload,
        isUndo = isUndo,
        batch = batch,
    )

    /** 当前所有未过期的待确认（界面按这个渲染卡片，最新的在最后）。 */
    fun list(): List<AiPendingWrite> = synchronized(lock) {
        pruneLocked()
        items.toList()
    }

    /** **取走并删除**。返回 null = token 不存在 / 已用过 / 已过期。 */
    fun take(token: String): AiPendingWrite? = synchronized(lock) {
        pruneLocked()
        val i = items.indexOfFirst { it.token == token }
        if (i < 0) null else items.removeAt(i)
    }

    /** 用户点了取消。返回是否真的取消掉了一个（false = 已经没了）。 */
    fun cancel(token: String): Boolean = synchronized(lock) {
        val i = items.indexOfFirst { it.token == token }
        if (i < 0) false else { items.removeAt(i); true }
    }

    /** 换对话/新建对话时必须调它：否则上一个对话的卡片会跟着飘到新对话里。 */
    fun clear() {
        synchronized(lock) { items.clear() }
    }

    private fun pruneLocked() {
        val t = now()
        items.removeAll { t > it.expiresAtMs }
    }

    companion object {
        /** 待确认有效期：5 分钟。够用户看完摘要、也短到不会变成一个"遗留的按钮"。 */
        const val DEFAULT_TTL_MS: Long = 5 * 60 * 1000L

        /** 最多同时挂几张卡片。超过就丢最旧的（正常一次只会有一张）。 */
        const val MAX_PENDING: Int = 4

        private val seq = AtomicLong(0)

        /** 令牌：进程内唯一即可（它从不离开本机、也不进提示词）。 */
        private fun randomToken(): String =
            UUID.randomUUID().toString().replace("-", "").take(16) + "-" + seq.incrementAndGet()
    }
}

/**
 * `preview_write` 申请一次写操作的结果。
 *
 * 三种可能，**互斥且完备**：直接做完了 / 等用户点确认 / 做不了（含歧义）。
 */
sealed interface AiWriteOutcome {
    /** 已经真的写完了。只有 [AiWriteRisk.LOW] 的动作会走到这里。 */
    data class Done(
        val actionId: String,
        val title: String,
        val message: String,
        /**
         * 这次写操作**还能不能撤回**（见 [AiUndoPlan]）。
         *
         * null = 这个动作撤不回来——但用户不是事后才知道：**预览卡片上早就写明了**
         * （理由在 [AiWrites.undoNoneOf]，卡片渲染时拼进明细行）。
         * 顺序很重要：先知道"撤不回来"，再决定点不点确认。
         */
        val undoToken: String? = null,
        /** 撤回按钮上那行字（"撤回：删除地址 张三 测试路 1 号"）。 */
        val undoLabel: String? = null,
    ) : AiWriteOutcome

    /** 已登记，**等用户在界面上点确认**。模型收到的只是"已把确认卡给用户了"。 */
    data class NeedConfirm(val pending: AiPendingWrite) : AiWriteOutcome

    /**
     * 没做，而且不该重试。
     *
     * @param candidates 名字对上了多个时的**候选名字**（绝不是编号），让模型去问用户是哪一个。
     */
    data class Rejected(val reason: String, val candidates: List<String> = emptyList()) : AiWriteOutcome
}

/**
 * 商品的**价格现状**（批量调价要在预览时算出 before→after，所以需要默认价）。
 *
 * 为什么不能复用 [AiName]：批量调价是全 App 唯一一个"我要先把结果算给你看"的动作，
 * 而算结果需要的是**价格**这个数字，不是名字——名字只用于展示。
 */
data class AiPriceProduct(val id: Long, val name: String, val defaultPrice: String)

/** 一条已有的批发商专属价（原始三列，批量调价用它 join 出当前生效价）。 */
data class AiPriceRuleRow(val shipperId: Long, val productId: Long, val price: String)

/**
 * 一张应付单的**钱现状**（2026-09-22，供应商付款要在预览时算出"付完还差多少"）。
 *
 * 为什么不能复用 [AiName]：付款是全 App 第二个"我要先把结果算给你看"的动作
 * （第一个是批量调价，见 [AiPriceProduct]），而算结果需要的是**金额**，名字只用于展示。
 *
 * ⚠️ 四个金额都是**后端算好的字符串**（口径只有一处：`backend/app/services/supplier_service.py`）。
 *    客户端一个减法都不做 —— 那会变成第二个口径。
 * ⚠️ 必须是 `public`：它是 `AiWriteDataSource`（public 接口）的返回类型，
 *    `internal` 会让接口暴露一个更窄的类型，Kotlin 直接编译不过。
 */
data class AiSupplierPayable(
    val id: Long,
    /** 挂在哪一个供应商名下（付款那条路要"在这一个供应商名下"找单据）。 */
    val supplierId: Long,
    val title: String,
    val amount: String,
    val paid: String,
    val unpaid: String,
    val paymentCount: Int,
)
/** 名册里的一条：**有编号，也有名字**。名字是唯一允许离开 App 的那一半。 */
data class AiName(
    val id: Long,
    val label: String,
    /**
     * 名册自带的**一句话补充**（可选，只用于展示，不参与名字匹配）。
     *
     * 今天只有司机用得上：派单卡片要写出"这个司机现在按什么算钱"
     * （`pay_summary_for` 生成的那句话）。写操作也必须有它——逐单定额/定比例
     * 只有在他挂着规则时才生效，卡片上看不见规则就等于让用户盲点。
     */
    val note: String? = null,
    /**
     * **只用于匹配、不上卡片**的别名（v3.44，真机实测补的）。
     *
     * ### 为什么需要它
     * 用户的说法是「把货主 13800000002 的商品可见范围改成…」，模型照着说了一遍手机号，
     * 拿到的是「**系统里没有匹配「13800000002」的货主/批发商**」——**这个人明明在系统里**
     * （`GET /users?q=13800000002` 一条不差地返回了他）。
     * 根因：名册是**按手机号搜出来的**（`searchShippers(query)` 打的就是 `?q=`），
     * 而匹配只看 `label`（姓名）——搜得到、认不出，报错话术却说"没这个人"。
     * 而 `targetUser` 的提示词写的就是「姓名（或手机号）」：**提示词承诺了、代码没做**。
     *
     * 为什么不干脆把手机号拼进 `label`（联系人就是那么干的）：
     * `label` 会**原样上确认卡**，而卡片上要写的是"改的是谁"。
     * 「张三 13800000002」在联系人卡片上还行（地址簿本来就这么显示），
     * 但在"给谁改计费规则""给谁开商品白名单"这种卡上是噪音。
     *
     * ⚠️ 别名**只参与匹配，绝不进 `label`、也不进任何出参**：
     * 只有用户自己说出来的那部分才该出现在卡上。
     */
    val aliases: List<String> = emptyList(),
)

/**
 * 某个货主/批发商**当前的**商品可见范围。
 *
 * 为什么单开一个类型而不是两个值糊在一起：卡片上要同时说清**模式**和**白名单**，
 * 而 `scope=all` 时白名单是空的、`scope=custom` 时白名单可能空（历史脏数据）——
 * "全部商品"和"一个都没勾"在后端是**两件完全不同的事**（前者不受限，后者什么都看不到），
 * 混成一个布尔量就会把后者显示成前者，而那是这套能力里最危险的一种错。
 */
data class AiVisibility(val scope: String, val productIds: List<Long>) {
    /** 模式的中文（卡片上不许出现 `custom` 这种码）。 */
    fun scopeLabel(): String = if (scope.equals("custom", ignoreCase = true)) "只给勾选的" else "全部商品（不限制）"
}

/**
 * 一张订单的**卡片视图**。
 *
 * ### 为什么订单要单独一个类型，而不是也用 [AiName]
 * 因为"是不是这一单"是用户在确认卡上唯一真正要判断的事，而它需要**好几条信息**才能判断：
 * 光看单号他记不住，光看货主他又分不清是哪一批货。所以卡片视图里必须同时有
 * 单号 + 货主 + 状态 + 地址 + 金额，用户扫一眼就能说"对，就是这单"或者"不对"。
 */
data class AiOrderRef(
    val id: Long,
    val orderNo: String,
    val shipper: String,
    /**
     * 后端**原始状态码**（`PENDING_DISPATCH` / `DISPATCHED` / …）。
     *
     * ⚠️ 状态门（`requireStatus`）只认它。原来这里存的是**中文状态**，
     * 于是每个动作的状态门写成 `setOf("待派单", "派单中")` —— 中文只是**显示名**，
     * 谁把 `statusLabel` 的措辞改一下（那看起来是纯文案改动），
     * 12 处状态门的含义就跟着一起变了，而且**不会有任何测试或编译错误**。
     * 现在门用状态码（可与后端枚举逐值对账），中文只出现在卡片文案里。
     */
    val status: String,
    val address: String,
    /** 当前的司机（没派单时为 null）。撤回/改运费时卡片要显示"本来是谁"。 */
    val driverLabel: String? = null,
    /** 订单金额（商品合计）。 */
    val amount: String = "0.00",
    /** 是否勾了「收取现金」——派单和收款时这是个关键信息。 */
    val collectCash: Boolean = false,
    /**
     * 这单当前是不是「异常」。
     *
     * 为什么要带上它：**异常是个标记，不是状态**（`is_exception` 与 status 并存）。
     * 卡片上不写这一项，用户就没法判断"标记异常"是不是重复操作、"解除异常"是不是白点一下——
     * 而这两个动作恰恰都是围绕这个标记转的。
     */
    val isException: Boolean = false,
    /**
     * 这单**已经有导航坐标**了吗（"补导航"动作的前置条件）。
     *
     * 为什么要带上它：后端对已有坐标的单**一律 400**（错坐标比没坐标更危险），
     * 而"点了确认才报错"就是白弹一张卡 —— 与状态门同一个道理，前置条件要在 [prepare] 里先核对。
     */
    val hasNav: Boolean = false,
    /**
     * 这单的货主编号（`null` = 临时货主，或者老后端没下发这个字段）。
     *
     * 为什么卡片视图要带上它（2026-09-22）：**报价必须绑这个货主的价**（专属价优先、否则商品默认价），
     * 而"加一行商品"这条路原来只拿得到一个货主**名字** —— 名字既认不出重名，
     * 也查不出他谈好的专属价，于是那一行只能退回商品库的默认价（真缺陷，见 [AiPriceBasis]）。
     *
     * ⚠️ 加新字段一律**追加在最后**（这个类在测试里有十几处**位置参数**调用：
     *    插在中间会把后面的字段整体顶掉一位，其中形状恰好相同的那几处**编译得过**、
     *    而 status 与 address 悄悄换了位置）。要读它请用名字。
     */
    val shipperId: Long? = null,
    /**
     * 这单**收过款吗**（后端 `order.paid`）。
     *
     * 为什么卡片要带它（2026-09-23 真机实测抓到）：`orders.charge`（挂账）动的是"钱收没收到"，
     * 而**已收款的单不许改回挂账**（后端 `_reject_if_already_collected` 直接 400）。
     * 前置条件必须在 [AiWriteHandler.prepare] 里先核对 —— 否则用户在卡片上点确认，
     * 看到的是一句红字「这张单已经收过款了，不能改回挂账」，而卡片本身写着"将挂账到 X"。
     * 判据与界面那一半**共用** `OrderStatusModel.canChargeToArrears`（一处实现、两处消费）。
     */
    val paid: Boolean = false,
    /** 已收金额（与 `OrderDto.settledAmount` 同一口径）——`paid` 之外的**物证**。 */
    val settledAmount: String = "0",
) {
    /** 卡片上显示的中文状态（由 [status] 推出来，不再单独存一份）。 */
    val statusCn: String get() = statusLabel(status)

    /** 卡片和候选名单里显示的一行字。**只有名字和状态，没有编号。** */
    fun label(): String = buildString {
        append(orderNo.ifBlank { "订单" })
        if (shipper.isNotBlank()) append("（").append(shipper)
        if (statusCn.isNotBlank()) append("·").append(statusCn)
        append("）")
    }

    companion object {
        /** 后端状态码 → 中文。卡片上写的是中文，用户才看得懂"这单现在能不能撤"。 */
        fun statusLabel(raw: String?): String = when (raw?.uppercase()) {
            "PENDING_DISPATCH" -> "待派单"
            "DISPATCHED" -> "派单中"
            "ACCEPTED" -> "已接单"
            "DELIVERED" -> "已送达"
            "CANCELLED" -> "已撤销"
            "RETURNED" -> "已退货"
            null, "" -> ""
            else -> raw
        }
    }
}

/**
 * 退货时的一行商品（后端 `services/order_return.py::max_returnable` 的客户端镜像）。
 *
 * ⚠️ 三个字段与后端逐一对齐（`quantity` / `damage_quantity` / `returned_quantity`），
 * 上限算在 [maxReturnable] **一处** —— 卡片文案、参数校验、请求体三处都用它。
 * 各算一遍的后果很具体：界面让填 3、后端只认 2，而用户不知道该信谁。
 */
data class AiReturnableLine(
    val id: Long,
    val name: String,
    val quantity: Int,
    val returned: Int,
    val damaged: Int,
    /** 单价（元/单位）。成本价不在出参里（那是成本字段，不进模型上下文）。 */
    val unitPrice: String,
) {
    /** 还能退几件 = 数量 − 货损 − 已退。规则只有一份（`core/ReturnRules`，与后端同源）。 */
    val maxReturnable: Int
        get() = com.tapmoay.sorders.core.ReturnRules.maxReturnable(quantity, damaged, returned)

    /** 卡片上那一行（把三个数都摆出来，用户才知道为什么只能退这么多）。 */
    fun label(): String = buildString {
        append(name)
        append("（下单 ").append(quantity)
        if (damaged > 0) append("、货损 ").append(damaged)
        if (returned > 0) append("、已退 ").append(returned)
        append("；还能退 ").append(maxReturnable).append("）")
    }
}

/**
 * 账本流水的引用（改/删时要先"找到那一条"）。
 *
 * ### 为什么账本是全套动作里最难定位的一类
 * 订单有**单号**（用户嘴上会说），账号有**姓名/手机号**，商品有**名字**——
 * 账本流水什么都没有：它就是"某天、某个货主、某个摘要、某个金额"的一行。
 * 而 AI 拿不到任何编号（第一条硬规矩），所以只能靠**人说的特征**去对：
 * 摘要关键词 + 日期 + 金额，三者组合出唯一一条才敢动手。
 *
 * 对不上或对上多条 → 一律拒绝并列候选，**绝不许挑一条像的**：
 * 账本是钱，改错一行不会立刻被发现（要等对账那天）。
 */
data class AiLedgerRef(
    val id: Long,
    val date: String,
    /** 摘要/商品名（`product_name`）。 */
    val product: String,
    val total: String,
    val shipper: String,
    /** `manual` / `order` / 其它来源。**`order` 意味着改它会回写订单明细**。 */
    val source: String,
    val note: String = "",
    /** 来自订单时带上单号（卡片据此提醒"这一行跟订单连着"）。 */
    val orderNo: String? = null,
) {
    /** 候选名单里的一行。**只有人能看懂的东西，没有编号。** */
    fun label(): String = buildString {
        append(date.ifBlank { "（无日期）" }).append(" ")
        append(product.ifBlank { "（无摘要）" })
        if (shipper.isNotBlank()) append("｜").append(shipper)
        append("｜").append(total).append(" 元")
        if (orderNo != null) append("（来自订单 ").append(orderNo).append("）")
    }

    companion object {
        /**
         * 来源码 → 中文（卡片上要写人话）。
         *
         * ⚠️ 映射本体在 `core/LedgerSourceLabel.kt`（**唯一一份实现**）：派单员账本的扇形图
         *    图例也用同一份。这里再写一遍 `when` 的话，同一类账会在两张界面上叫两个名字。
         */
        fun sourceLabel(raw: String): String = com.tapmoay.sorders.core.ledgerSourceLabel(raw)
    }
}

/**
 * 订单里**一行商品**的引用（改/删商品行时要先"找到那一行"）。
 *
 * 定位方式与账本同源：行本身没有名字，靠**商品名**在**这一张订单内**对——
 * 比账本容易，因为范围已经收窄到一张单，同名单品出现两次的概率低得多。
 */
data class AiOrderLine(
    val id: Long,
    val product: String,
    val quantity: Int,
    val unitPrice: String,
    val lineTotal: String,
) {
    fun label(): String = "$product × $quantity（${AiWriteArgs.moneyText(unitPrice)} 元/件，合计 ${AiWriteArgs.moneyText(lineTotal)} 元）"
}

/**
 * 一条站内消息的引用（标记已读 / 改内容 / 删掉时要先"找到那一条"）。
 *
 * 定位与账本同源：消息也没有名字，靠**标题/正文里的关键词**去找。
 * 区别是消息**一定属于当前登录的人**（拿不到别人的），而且一次只捞最近若干条。
 */
data class AiNotificationRef(
    val id: Long,
    val title: String,
    val content: String,
    val createdAt: String,
    val read: Boolean,
) {
    fun label(): String = buildString {
        append(title.ifBlank { content.take(20) })
        if (createdAt.isNotBlank()) append("（").append(createdAt.take(16).replace('T', ' ')).append("）")
        append(if (read) "·已读" else "·未读")
    }
}

/**
 * 一张**司机账单**（`driver_bills` 的一行：某司机某月的运费单或工资单）。
 *
 * ### 为什么账单要带这么多字段
 * "生成账单"这个动作的卡片全部价值在于**用户能不能核对范围**：他会盯着
 * "这个月、这个司机、这个金额"三件事看。所以账单视图里必须同时有月份、类型、
 * 金额、状态，以及（运费单才有）关联的订单号——少任何一项，用户就只能盲点确认。
 */
data class AiDriverBill(
    val id: Long,
    /**
     * 账单属于哪个司机。
     *
     * ⚠️ **必须按编号对齐，不能按姓名对齐**：司机名册是几十上百人的中文姓名，
     * 重名完全可能（"张伟""李强"这种），而"这几位该月已经建过工资单了"这种判断
     * 一旦按名字比，两个同名司机会被当成同一个人 —— 于是一个人的工资单**永远不会被生成**，
     * 而且悄无声息。编号只在本机用（不进模型上下文），拿它对齐没有任何代价。
     */
    val driverId: Long,
    val driverLabel: String,
    val billType: String,
    val month: String,
    val amount: String,
    val status: String,
    val orderNo: String? = null,
) {
    fun typeLabel(): String = if (billType.equals("salary", ignoreCase = true)) "工资单" else "运费单"

    fun statusLabel(): String = when (status.lowercase()) {
        "open" -> "待结算"
        "settled" -> "已结算"
        "cancelled" -> "已作废"
        else -> status
    }

    fun label(): String = buildString {
        append(typeLabel()).append(" ").append(amount).append(" 元（").append(statusLabel()).append("）")
        if (orderNo != null) append("｜订单 ").append(orderNo)
    }
}

/**
 * 一张**司机结算单**的引用（确认 / 付款 / 作废之前要先"找到那一张"）。
 *
 * ### 结算单和账本流水是同一类难题：**它没有名字**
 * 它由「司机 + 月份 + 计费方式」三者唯一确定，所以定位靠这三个条件，
 * 再按**动作要求的状态**收窄（确认/作废只能对草稿，付款只能对已确认）。
 * 收窄后仍不唯一 → 一律拒绝并列候选，绝不挑一张像的：结算单连着钱和账单锁定。
 */
data class AiSettlementRef(
    val id: Long,
    /** 见 [AiDriverBill.driverId]：对齐一律按编号，不按姓名。 */
    val driverId: Long,
    val driverLabel: String,
    val settleType: String,
    val month: String,
    val amount: String,
    val status: String,
    /** 绑定的订单张数（运费单才有意义；工资单是 0）。 */
    val orderCount: Int,
    val note: String = "",
) {
    fun typeLabel(): String = if (settleType.equals("salary", ignoreCase = true)) "工资单" else "运费单"

    fun statusLabel(): String = when (status.lowercase()) {
        "draft" -> "草稿"
        "confirmed" -> "已确认"
        "paid" -> "已付款"
        "cancelled" -> "已作废"
        else -> status
    }

    fun label(): String = buildString {
        append(driverLabel).append("｜").append(month).append(" ").append(typeLabel())
        append("｜").append(amount).append(" 元｜").append(statusLabel())
    }
}

/**
 * 一位**工资制司机**的画像（生成工资单之前要能算出"会建几张、合计多少"）。
 *
 * 为什么要单独一个类型而不是用 [AiName]：工资单的金额来自 `users.salary`，
 * 而卡片上最该给用户看的就是**这个数**——月薪单生成错了，司机那边是要按它领钱的。
 */
data class AiSalaryDriver(val id: Long, val label: String, val salary: String)

/**
 * 某司机某月的**应结运费**（按"已送达且计价"的订单聚合，来自 `GET /freight-settlement`）。
 *
 * ### 为什么生成运费单需要它
 * "补账单"是一个**范围动作**：用户真正想确认的是"这次会补进去多少钱"。
 * 而账单表里查不到"还没生成的单"，只有运费结算（按订单聚合）知道**应结多少**——
 * 两者相减才是这次会补的金额。没有这个数，卡片上就只剩一句"会补一些账单"，
 * 那种卡片还不如不弹。
 */
data class AiDriverFreight(
    val driverId: Long,
    val driverLabel: String,
    val count: Int,
    val total: String,
)

/**
 * 一个写动作的**完整实现**：校验 → 解析名字 → 造 payload → 渲染摘要 → （确认后）落库。
 *
 * ### 拆成接口的理由（不是为了好看）
 * 动作会从 3 个长到几十个（后端一共 76 个写接口）。全塞在一个 `when` 里的话，
 * 那个文件半年后没人敢改——而它恰恰是**最不能改错**的文件。
 * 按领域一个文件（账目/订单/…），每个动作一个类，改哪个动作就只碰哪一段。
 *
 * ### 两条不许破的规矩
 * 1. **[prepare] 里绝对不许写后端。** 它只负责"把将要发生的事说清楚"。
 *    一旦有人在这里调了 `assignOrder`，确认卡就变成了一张"事后通知"。
 * 2. **[commit] 只接受 [prepare] 造出来的 payload**，不许再读一遍用户/模型的输入。
 *    否则"用户看到的"和"真正写进去的"就成了两条路径，迟早分叉且不会报错。
 */
interface AiWriteHandler {
    /** 实现哪个动作。必须能在 [AiWrites.byId] 里找到（红线会断言两边一一对应）。 */
    val actionId: String

    /** 校验 + 解析 + 造卡。LOW 档动作可以在这里直接执行完并返回 [AiWriteOutcome.Done]。 */
    suspend fun prepare(params: JsonObject): AiWriteOutcome

    /** 用户点了确认 → 真正落库。**唯一会改动业务数据的地方。** */
    suspend fun commit(payload: JsonObject, idempotencyKey: String)

    /**
     * 执行完之后要**补一句**的话（默认没有）。
     *
     * ### 为什么需要这么个东西
     * 用户看到的执行结果是"已完成：<卡片摘要>"，而那张摘要是在**预览时**写好的——
     * 那时还不知道会发生什么。绝大多数动作"一件事一个结果"，摘要就是结果，够用。
     * 但**批量动作**（按表格调价：一行一个请求）会出现「10 行成功、2 行失败」，
     * 只回一句"已完成"等于**把失败的那两行藏起来**——用户会以为 20 行全成了。
     *
     * 所以：批量动作在 [commit] 里把逐行结果攒下来，这里交给服务层拼进最终答复。
     * **取走即清空**（一次性），避免下一次执行读到上一次的残留。
     */
    fun commitNote(): String? = null
}

// ============================================================ 声明式 CRUD 层
//
// v3.9：用户口径是「**整个 App 的所有功能它都能做**」——商品改价、批发商定价、账号与
// 司机收费规则、库存、地址与联系人……后端一共 72 个写接口。
// 这个量级下，每个动作手写一个处理器是不行的：26 个动作各写一遍"必填校验 + 金额上限 +
// payload 拼装"，结果一定是**有一个忘了上限**，而那个就是记错钱的那个。
//
// 所以把"操作一个既有实体的某个字段"这一类动作收敛成**一份规格**：
// 声明"先查谁 / 收哪些字段 / 摘要怎么写 / 调哪个接口"，校验和拼装由 [CrudWriteHandler] 统一做。
//
// ⚠️ **摘要仍然是每个动作手写的**（`headline`/`details`）——那是唯一不能抽象的部分：
// 用户能不能核对，全看那一句话写得清不清楚。

/** 字段类型。决定用哪条校验规则（**每条规则只有一份实现**，见 [AiWriteArgs]）。 */
enum class AiFieldType(val cn: String) {
    TEXT("文本"),
    /** 金额：走 [AiWriteArgs.parseMoney]（带 100 万上限，防"多打了三个零"）。 */
    MONEY("金额"),
    /** 整数：走 [AiWriteArgs.parseQuantity]（≥1 且带上限）。 */
    COUNT("数量"),
    /** 可以填 0 或负数的整数（如库存变动量）。 */
    DELTA("增减量"),
    /**
     * **非负整数**（0 合法、不许负数）：库存报警阈值、初始库存这类"绝对值"。
     *
     * ⚠️ 为什么不能拿 [DELTA] 凑（2026-09-19 审计）：DELTA 的语义是"增减量"，
     * 它**拒 0 且允许负数** —— 而这两条正好与阈值相反：卡片上写着"填 0 = 不报警"，
     * 模型照做会被拒（错误文还在讲"不会改变库存、只会留下一条没意义的流水"，文不对题），
     * 而填了负数后端 `ge=0` 会 422。类型必须有自己的名字，判据才能钉住它。
     */
    NON_NEGATIVE("非负整数"),
    DATE("日期"),
    BOOL("是/否"),
    ENUM("枚举"),
}

/**
 * 一个**先要解析成编号**的目标实体（商品、货主、司机、地址…）。
 *
 * @param param 模型传的参数名（如 `product`）
 * @param key 进 payload 的键名（如 `product_id`）——**编号只到这里为止**，不进卡片
 * @param lookup 怎么拿到名册。**不缓存**：名册随时会变，缓存久了就会"查不到刚加的车"
 */
data class AiTargetSpec(
    val param: String,
    val cn: String,
    val key: String,
    val hint: String,
    val required: Boolean = true,
    /** 单号/车牌语义（忽略大小写与分隔符）。 */
    val code: Boolean = false,
    /**
     * 允许"查不到"（返回 null，由摘要写明"按临时/新建处理"）。
     * **默认 false**：查不到就拒绝。丢一个参数比报错危险得多（见方案 §20.4）。
     */
    val allowMissing: Boolean = false,
    val lookup: suspend (AiWriteDataSource, String) -> List<AiName>,
)

/** 一个直接进 payload 的字段。 */
data class AiFieldSpec(
    val name: String,
    val cn: String,
    val type: AiFieldType,
    val hint: String,
    val required: Boolean = false,
    /** 金额/数量是否必须 > 0（false 时允许 0）。 */
    val positive: Boolean = true,
    val maxChars: Int = 200,
    val enumValues: List<String> = emptyList(),
    /** 中文别名 → 枚举值。模型多半会用中文说（"计件"），只认英文等于逼它猜。 */
    val aliases: Map<String, String> = emptyMap(),
    /** 进 payload 的键名；默认与参数名相同。 */
    val key: String = name,
    /**
     * **凭据类字段**（密码）：值会进 payload，但**绝不允许出现在卡片上**。
     *
     * 为什么做成规格里的一等标志而不是"记得别写"：卡片文案是手写的，
     * 而"顺手把填的值都列出来"是写摘要时最自然的冲动。有了这个标志，
     * 单测可以对所有动作统一断言"secret 字段的值不出现在卡片上、且卡片上写明了已设置"，
     * 而不是指望每个写摘要的人都记得。
     */
    val secret: Boolean = false,
)

/**
 * 校验 + 解析之后交到摘要手里的东西。
 *
 * [payload] 和 [refs]/[values] **同源**：摘要读的就是即将发出去的那份数据，
 * 所以"卡片上写的"和"真正写进去的"不可能分叉。
 *
 * ### 为什么 [values] 同时按「参数名」和「payload 键名」索引
 * 因为一个字段有两个名字：模型传的是 `price`（参数名），后端收的是 `special_unit_price`
 * （键名）。而写摘要的人**没法可靠地记住该用哪一个**——v3.9 真机实测就踩了这一个：
 * 摘要读 `c.str("default_unit_price")`，而 `values` 是按参数名 `price` 存的，
 * 于是**整行明细从卡片上消失了**，只剩一个光秃秃的标题。
 *
 * 两个名字都认，这类错误就不可能再发生；而"两个都不是"的情况由红线 §2g-5 静态拦住。
 */
class AiWriteCard(
    val refs: Map<String, AiName?>,
    /** 按「参数名」存的原始值（payload 里用的是键名，见 [payload]）。 */
    rawValues: Map<String, JsonElement>,
    /** 参数名 → payload 键名。用来让同一个字段的两个名字都能查到值。 */
    keyOf: Map<String, String>,
    val payload: JsonObject,
) {
    private val values: Map<String, JsonElement> = buildMap {
        putAll(rawValues)
        // 同一个值同时挂在「参数名」和「键名」下（两个名字不同时才补第二条）
        rawValues.forEach { (name, v) -> keyOf[name]?.let { if (it != name) put(it, v) } }
    }

    /** 解析出来的实体（可能为 null = allowMissing 且没命中）。 */
    fun ref(param: String): AiName? = refs[param]

    fun str(name: String): String? = (values[name] as? JsonPrimitive)?.contentOrNull

    fun int(name: String): Int? = str(name)?.toIntOrNull()

    fun bool(name: String): Boolean? = str(name)?.toBooleanStrictOrNull()

    fun has(name: String): Boolean = values.containsKey(name)

    /** 「标签：值」一行；没填就返回 null（调用方自己决定要不要写"没填"）。 */
    fun line(name: String, cn: String): String? = str(name)?.let { "$cn：$it" }
}

/**
 * 一个通用 CRUD 动作的完整规格（**静态**，不依赖数据源）。
 *
 * `headline` 是卡片标题那一行，`details` 是下面的明细。
 * 两个都拿得到 [AiWriteCard]，所以可以按实际填了什么来决定写哪几行
 * ——这正是"摘要要能核对"的关键：没填的东西也要看得见（写明"没填"），
 * 而不是从卡片上消失、让用户以为它不存在。
 */
data class CrudSpec(
    val targets: List<AiTargetSpec> = emptyList(),
    val fields: List<AiFieldSpec> = emptyList(),
    val headline: (AiWriteCard) -> String,
    val details: (AiWriteCard) -> List<String>,
    val commit: suspend (AiWriteDataSource, JsonObject) -> Unit,
    /**
     * 要拿**哪一个字段的文本**去高德换坐标，填 payload 键名（如 `detail_address`）。
     *
     * 只有"存下来是为了以后在地图上用"的动作才填它：地址、地点。
     * 不填 = 不定位（商品、账号、账本那些跟地图无关的动作）。
     */
    val geocodeFrom: String? = null,
    /**
     * true = **改了地址文字却定位不到坐标时直接拒绝**（连卡都不弹）。
     *
     * 为什么"改"比"新建"严：后端 PATCH 用的是 `if body.address_lat is not None` 语义，
     * **传 null 清不掉旧坐标**。于是"改了地址但没定位到"会留下**上一条地址的坐标**——
     * 司机点导航会被带到**旧地址**去，而且没有任何提示。
     * 新建没这个问题（新行本来就没有坐标），所以新建只提示、不拦。
     */
    val geocodeRequired: Boolean = false,
    /**
     * true = **改动可以只落在一个目标参数上**（没有字段也没关系）。
     *
     * 默认 false：一张"字段全空"的卡只会让用户困惑——他点了确认，然后什么都没发生，
     * 而他会以为系统坏了（所以 [CrudWriteHandler] 会直接拒绝）。
     *
     * 什么时候必须开：有一类改动的**内容本身就是一个关联对象**，而不是自己的某个字段。
     * 具体到 `vehicle.update`：「把豫A12345 挂到张三名下」——司机是**目标参数**（要按姓名
     * 解析成编号），字段（车牌/车型/启用）全是空的。不开这个口子的话，用户说得清清楚楚，
     * 拿到的却是一句"你没有说要改哪一项"。
     */
    val allowTargetOnly: Boolean = false,
    /**
     * **即使解析不出来也要写进 payload 的目标参数**（值写成 JSON `null`）。
     *
     * 默认行为是"目标为空就**不放**这个键"（部分更新语义：没点名就不动它）。
     * 但有一类动作的"空"本身**就是一个取值**：`vehicle.set_driver` 的"解绑"就是
     * "司机那一项不填"。这时少放一个键会连带坏掉**撤回**——
     * `AiRevert.patchPlan` 是**按 payload 里有哪些键**去写回旧值的，
     * payload 里没有 `driver_id`，撤回就无从下手，那张卡上的「撤回」永远挂不上
     * （真机 E2E 抓到的正是这个：卡片敢印"会出现撤回"，执行完只回一句"没能挂上"）。
     *
     * 与 [allowTargetOnly] 的关系：那个管"空字段的卡要不要拒绝"，这个管"空的目标要不要进 payload"。
     * 需要解绑能力的动作两个都要开。
     */
    val alwaysIncludeTargets: Set<String> = emptySet(),
)

/**
 * 声明式动作的**参数清单**：先目标实体（名字 → 编号），再普通字段。
 *
 * ### 为什么必须只有一份实现
 * `AiWriteMasterData` 与 `AiWriteBasicData` 各有一个 `crud(...)` 工厂，原来各自抄了一遍
 * 这段推导 + [AiFieldType] → [AiWriteParamKind] 的映射。它的产物**会贴给模型看**
 * （[AiWrites.describeForModel] 里那句 `${p.kind.cn}`，例如「fee=运费（元）（必填，数字）」）——
 * 两份走散之后，同一种字段类型在两组动作里就是**两种说法**，模型按一处写、另一处不认，
 * 而**两边都不报错**（表现只是"参数传得不对"）。所以推导与映射都收在这里，工厂只调它。
 *
 * ⚠️ 目标的类型恒为 [AiWriteParamKind.TEXT]：模型给的是**名字**（"红富士苹果"），
 * 编号由 App 自己解析（见 [AiTargetSpec]）——写成 NUMBER 会让它直接吐一个编号过来。
 */
internal fun crudParams(
    targets: List<AiTargetSpec>,
    fields: List<AiFieldSpec>,
): List<AiWriteParam> =
    targets.map { AiWriteParam(it.param, it.cn, it.required, AiWriteParamKind.TEXT, it.hint) } +
        fields.map { AiWriteParam(it.name, it.cn, it.required, it.paramKind(), it.hint, it.enumValues) }

/**
 * [AiFieldType] → **给模型看的**参数类型。
 *
 * 刻意是粗的那一种（金额/数量/增减量/非负整数都只是"数字"）：细规则由 [AiWriteArgs]
 * 按字段类型逐条校验（金额有 100 万上限、数量 ≥1、增减量允许负数…），
 * 这里只负责让模型知道"这一格该填数字还是一段文字还是日期"。
 *
 * ⛔ 只有这一份（见 [crudParams]）：单测 `AiWriteParamsTest` 把 8 个字段类型逐个钉住，
 * 红线 `_tools/ai/_check_ai_write_params.py` 钉住"全库只有一处映射 + 工厂都走 [crudParams]"。
 */
internal fun AiFieldSpec.paramKind(): AiWriteParamKind = when (type) {
    AiFieldType.TEXT -> AiWriteParamKind.TEXT
    AiFieldType.MONEY, AiFieldType.COUNT, AiFieldType.DELTA, AiFieldType.NON_NEGATIVE ->
        AiWriteParamKind.NUMBER
    AiFieldType.DATE -> AiWriteParamKind.DATE
    AiFieldType.BOOL -> AiWriteParamKind.TEXT
    AiFieldType.ENUM -> AiWriteParamKind.ENUM
}

/** 地理编码结果的 payload 键（[CrudSpec.geocodeFrom] 换出来的坐标写在这两个键上）。 */
internal const val GEO_LAT = "address_lat"
internal const val GEO_LNG = "address_lng"

/**
 * 地址类参数**给模型的一句提示**：用户说的是"我现在在的地方"时，就填 [AiLocation.HERE] 那四个字。
 *
 * ### 为什么必须写在参数说明里
 * 模型看不到 [CrudSpec.geocodeFrom]、也看不到 [AiLocation] —— 它只照参数说明写字。
 * 不写这句，用户说「送到**我现在的位置**」时它只能编一个地址（或者说一句"我做不到"），
 * 而这个能力明明已经在（2026-09-21 用户：「这个权限给它开啊」）。
 *
 * ⛔ **只有真的会解析这个句柄的参数才许带这句话**：带了却没解析的动作，会把字面量
 *    「当前位置」写进地址库 —— 不报错，而司机导航到一个叫"当前位置"的地方。
 *    判据钉在 `_check_ai_guardrails.py`（说了能填句柄的动作必须有 `geocodeFrom`）。
 */
internal val HERE_HINT = "；要用户**现在所在的地方**就填「${AiLocation.HERE}」四个字（别自己编地址）"

/**
 * 写动作注册表（**编译期定死**，模型只能在这些里选）。
 *
 * ### 准入条件（三条全中才能加进来）
 * 1. 对应一个**真实的后端接口**，且 Android 侧已有 DTO/仓库方法（不为了 AI 新造接口）；
 * 2. 能写出一句**人类看得懂的摘要**——写不出就别加，用户没法核对的东西不许让 AI 写；
 * 3. 参数里**只接受名字**，内部编号一律由 App 自己解析。
 *
 * ### 覆盖范围（用户口径：**整个 App 的功能它都能做**）
 * 后端 72 个写接口（去掉登录/注册）。分批铺，每批都必须过"卡片能不能核对"这一关。
 * **唯一永久排除的两类**：
 * - **登录/注册**：AI 不该碰凭据，跟风险分级无关；
 * - **上传类**（`/orders/{id}/address-image`、`/delivery-photos`、`/products/{id}/image`）：
 *   它们要一个文件，而模型给不出文件。
 */
object AiWrites {

    // ------------------------------------------------------------- 动作 id

    const val NOTIFICATIONS_READ_ALL = "notifications.read_all"
    const val EXPENSES_CREATE = "expenses.create"
    const val LEDGER_CREATE_ENTRY = "ledger.create_entry"

    // ---- 订单 ----
    const val ORDERS_ASSIGN = "orders.assign"
    const val ORDERS_RECALL = "orders.recall"
    const val ORDERS_CANCEL = "orders.cancel"
    const val ORDERS_RETURN = "orders.return"
    const val ORDERS_CREATE = "orders.create"
    const val ORDERS_FREIGHT = "orders.freight"
    const val ORDERS_PAY = "orders.pay"
    const val ORDERS_CHARGE = "orders.charge"

    // ---- 订单（第二批：改单 / 异常 / 拆单 / 批量派单）----
    const val ORDERS_UPDATE = "orders.update"
    const val ORDERS_MARK_EXCEPTION = "orders.mark_exception"
    const val ORDERS_RESOLVE_EXCEPTION = "orders.resolve_exception"
    const val ORDERS_SPLIT = "orders.split"
    const val ORDERS_BATCH_ASSIGN = "orders.batch_assign"

    // ---- 订单（第三批：商品行增改删、软删与恢复）----
    const val ORDERS_ADD_LINE = "orders.add_line"
    const val ORDERS_UPDATE_LINE = "orders.update_line"
    const val ORDERS_DELETE_LINE = "orders.delete_line"
    const val ORDERS_SOFT_DELETE = "orders.soft_delete"
    const val ORDERS_RESTORE = "orders.restore"

    // ---- 订单（第四批：补导航 = 引用共享地点库里已有的坐标）----
    const val ORDERS_FILL_NAV = "orders.fill_nav"

    // ---- 退货申请（第五批，2026-09-21 用户要求）----
    //
    // 用户原话：「批发商**只是一个申请**，派单员才是实际性的操作。派单员进行完了之后，
    // 整个才进行库存才会发生一个改变和变动」＋「同时**货主的 AI 可以代替货主进行申请退货**」。
    //
    // ⛔ 与 [ORDERS_RETURN] 是**两件事、两个人**：
    //    · `return_request.apply` / `.withdraw` —— **货主**（写一张申请单，什么都不动）；
    //    · `return_request.reject` / `.fulfill` —— **派单员**（后者才真的退：账本/库存/退现/状态）。
    //    合成一个动作的后果是把用户刚定下来的那条线抹掉：货主按一下就能改自己的应收和公司库存。
    const val RETURN_REQUEST_APPLY = "return_request.apply"
    const val RETURN_REQUEST_WITHDRAW = "return_request.withdraw"
    const val RETURN_REQUEST_REJECT = "return_request.reject"
    const val RETURN_REQUEST_FULFILL = "return_request.fulfill"

    // ---- 账本（改/删流水、客户收款、补进账本）----
    const val LEDGER_UPDATE_ENTRY = "ledger.update_entry"
    const val LEDGER_DELETE_ENTRY = "ledger.delete_entry"
    const val LEDGER_CREATE_RECEIPT = "ledger.create_receipt"
    const val LEDGER_SYNC_DELIVERED = "ledger.sync_delivered"

    // ---- 货主**自己那一本账**（批发商给下游货主核销，2026-09-20）----
    //
    // ⛔ 与上面那四个 `ledger.*` 是**两本账**：那四个写的是**公司账**
    //    （`customers` / `cash_flows` / `orders.paid` / `ledgers`，只有派单员能写）；
    //    这三个写的是"我自己向我的货主收钱"，后端落在 `shipper_settlements`，
    //    一个字节都不碰公司账。用户原话：「这个核销只对他来说……他自己管自己的」。
    const val MY_LEDGER_SETTLE = "my_ledger.settle"
    const val MY_LEDGER_REVOKE = "my_ledger.revoke"
    //: 撤回专用（`undoOnly`）：撤销之后要能放回来，模型看不到它。
    const val MY_LEDGER_RESTORE = "my_ledger.restore"

    // ---- 司机账单与结算（月末收口：生成账单 → 生成结算单 → 确认 → 付款）----
    const val SETTLEMENTS_GENERATE_BILLS = "settlements.generate_bills"
    const val SETTLEMENTS_CREATE = "settlements.create"
    const val SETTLEMENTS_CONFIRM = "settlements.confirm"
    const val SETTLEMENTS_PAY = "settlements.pay"
    const val SETTLEMENTS_CANCEL = "settlements.cancel"

    // ---- 消息（发消息 / 价格变更通知 / 标记已读 / 改内容 / 删消息）----
    const val NOTIFICATIONS_SEND = "notifications.send"
    const val NOTIFICATIONS_PRICE_CHANGE = "notifications.price_change"
    const val NOTIFICATIONS_MARK_READ = "notifications.mark_read"
    const val NOTIFICATIONS_UPDATE = "notifications.update"
    const val NOTIFICATIONS_DELETE = "notifications.delete"

    // ---- 撤回用的动作（模型看不到，只由界面上那个「撤回」按钮走）----
    // 它们**不进**模型的动作清单（`undoOnly`），因为模型没有任何理由去"恢复一条它看不见的记录"：
    // 被软删的行已经从名册里消失了，按名字根本解析不到。它们是给撤回路径用的：
    // 撤回拿着的是**确定的编号**，不需要解析名字。
    const val ADDRESS_RESTORE = "address.restore"
    const val LOCATION_RESTORE = "location.restore"
    const val CONTACT_RESTORE = "contact.restore"
    const val ARREARS_UNIT_RESTORE = "arrears_unit.restore"
    const val FREIGHT_TEMPLATE_RESTORE = "freight_template.restore"
    const val PRODUCTS_RESTORE = "products.restore"
    const val USERS_RESTORE = "users.restore"

    // ---- 商品 / 定价 / 库存 ----
    const val PRODUCTS_CREATE = "products.create"
    const val PRODUCTS_UPDATE = "products.update"
    const val PRODUCTS_SET_ACTIVE = "products.set_active"
    const val PRODUCTS_DELETE = "products.delete"
    /** 用户给一张表、要按它一次建多个商品（v3.32）。见 [ApplyProductTableHandler]。 */
    const val PRODUCTS_APPLY_TABLE = "products.apply_table"
    const val PRICE_RULES_SET = "price_rules.set"
    const val PRICE_RULES_UPDATE = "price_rules.update"
    const val PRICE_RULES_DELETE = "price_rules.delete"
    const val INVENTORY_ADJUST = "inventory.adjust"
    const val PRICE_RULES_BATCH = "price_rules.batch"
    /** 用户贴一张表格、每行一套规则（第四种用法）。见 [ApplyPriceTableHandler]。 */
    const val PRICE_RULES_APPLY_TABLE = "price_rules.apply_table"

    // ---- 账号与收费规则 ----
    const val USERS_CREATE = "users.create"
    const val USERS_UPDATE_PROFILE = "users.update_profile"
    const val USERS_SET_BILLING = "users.set_billing"
    const val USERS_SET_ACTIVE = "users.set_active"
    const val USERS_SET_MEMBER = "users.set_member"
    const val USERS_SWAP_ROLE = "users.swap_role"
    const val USERS_SET_PASSWORD = "users.set_password"
    const val USERS_DELETE = "users.delete"

    // ---- 司机计费规则（v3.36）----
    //
    // 用户 2026-09-18 原话：「这个计费规则呀，ai 是可以根据用户的需求帮他配置的……
    // 甚至 ai 可以帮我们去挂上计费规则，比如给这个司机挂上这个我们刚刚配置好的规则」。
    // 所以这一组里**挂载**（attach）和建规则一样是一等动作，不是"顺手加的"。
    const val DRIVER_RULE_CREATE = "driver_rule.create"
    const val DRIVER_RULE_UPDATE = "driver_rule.update"
    const val DRIVER_RULE_DELETE = "driver_rule.delete"
    const val DRIVER_RULE_ATTACH = "driver_rule.attach"
    const val DRIVER_RULE_RESTORE = "driver_rule.restore"

    // ---- 地址与联系人 / 基础资料 ----
    const val ADDRESS_CREATE = "address.create"
    const val ADDRESS_UPDATE = "address.update"
    const val ADDRESS_DELETE = "address.delete"
    const val ADDRESS_SET_DEFAULT = "address.set_default"
    const val CONTACT_UPSERT = "contact.upsert"
    const val CONTACT_UPDATE = "contact.update"
    const val CONTACT_DELETE = "contact.delete"
    const val LOCATION_CREATE = "location.create"
    const val LOCATION_UPDATE = "location.update"
    const val LOCATION_DELETE = "location.delete"
    const val ARREARS_UNIT_CREATE = "arrears_unit.create"
    const val ARREARS_UNIT_UPDATE = "arrears_unit.update"
    const val ARREARS_UNIT_DELETE = "arrears_unit.delete"
    // 预订单 / 订单模板（2026-09-22 用户要求「AI 直接创建预定单」）。
    // 「一键下单」不是这里面的动作：它是界面动作（读预设单 → 走已有的 `orders.create`）。
    const val ORDER_TEMPLATE_CREATE = "order_templates.create"
    const val ORDER_TEMPLATE_UPDATE = "order_templates.update"
    const val ORDER_TEMPLATE_DELETE = "order_templates.delete"
    const val ORDER_TEMPLATE_RESTORE = "order_templates.restore"
    const val FREIGHT_TEMPLATE_CREATE = "freight_template.create"
    const val FREIGHT_TEMPLATE_UPDATE = "freight_template.update"
    const val FREIGHT_TEMPLATE_DELETE = "freight_template.delete"

    // ---- 供应商 / 厂商档案 + 应付款（2026-09-22 用户要求，账本管理「支出」那一块）----
    //
    // 用户原话：「支出主要是**给某个供应商或者说是厂商支付尾款**……**购买一个装备或者说是设备**……
    // 比如说类似**邮费**啊」；拍板口径：**跟客户一个量级的档案**（可挂账、可查还欠多少、可分次付款）。
    //
    // 十一个动作分三条线（档案 / 应付单 / 付款），每条线各有 `restore`（撤回路径专用）。
    // ⛔ 三条线**不合**成一个大动作：它们的对象、风险、卡片要核对的东西都不一样 ——
    //    「改档案电话」和「把钱付出去」并成一个动作，风险只能取最高档，
    //    用户会很快学会无视那张红牌（`AiWriteRisk` 那一节的理由）。
    const val SUPPLIER_CREATE = "supplier.create"
    const val SUPPLIER_UPDATE = "supplier.update"
    const val SUPPLIER_DELETE = "supplier.delete"
    const val SUPPLIER_RESTORE = "supplier.restore"
    const val SUPPLIER_PAYABLE_CREATE = "supplier_payable.create"
    const val SUPPLIER_PAYABLE_UPDATE = "supplier_payable.update"
    const val SUPPLIER_PAYABLE_DELETE = "supplier_payable.delete"
    const val SUPPLIER_PAYABLE_RESTORE = "supplier_payable.restore"
    //: **真正把钱写出去**的那一个（HIGH）：会写一行资金流水，账本「收支」立刻看得到。
    const val SUPPLIER_PAYMENT_PAY = "supplier_payment.pay"
    //: **撤销一笔付款**（软删那一行流水，可恢复）。⛔ 不复用 pay：方向相反的两个结论，
    //: 审计页上必须一眼分得出"这笔钱付出去了"和"这笔钱其实不算"。
    const val SUPPLIER_PAYMENT_CANCEL = "supplier_payment.cancel"
    const val SUPPLIER_PAYMENT_RESTORE = "supplier_payment.restore"
    const val VEHICLE_CREATE = "vehicle.create"
    const val VEHICLE_UPDATE = "vehicle.update"

    // ---- 车辆换/解绑司机（v3.44：用户要「司机的车辆绑定」这件事 AI 也得会）----
    //
    // 为什么单独一个动作、而不是继续用 `vehicle.update` 里的那个司机参数：
    // 用户 2026-09-18 报的缺口里有一半是**解绑**（"把 A12345 从张三名下拿掉"）。
    // 解绑在后端原来是**没有表达方式**的（`if body.driver_id is not None` 会把空值忽略掉），
    // 现在多了专用接口 `POST /vehicles/{id}/driver`（缺省/null = 解绑）。
    // 把它做成独立动作，是为了让"绑"和"解绑"**各自有一张说得清楚的卡**：
    // 同一个动作里既换人又解绑，卡片上会出现"要绑的人没填"和"要解绑"长得一样的歧义。
    const val VEHICLE_SET_DRIVER = "vehicle.set_driver"

    const val CUSTOMER_CREATE = "customer.create"

    // ---- 商品分类名册（v3.43：用户要「AI 能建商品分组、管分组的排序」）----
    //
    // 用户 2026-09-18 原话：「在给 ai 的功能开放创建商品分组、管理商品分组的排序」。
    // 这一组只动「下单页左侧那一列怎么分组、什么顺序」，一条商品的归属都不改——
    // 唯一会波及商品的是**改名**（后端在同一个事务里把挂在这一类下的商品一起改名），
    // 所以改名那张卡上必须写出"这个分类下有 N 个商品"。
    const val PRODUCT_CATEGORY_CREATE = "product_category.create"
    const val PRODUCT_CATEGORY_UPDATE = "product_category.update"
    const val PRODUCT_CATEGORY_DELETE = "product_category.delete"
    const val PRODUCT_CATEGORY_REORDER = "product_category.reorder"

    // ---- 地点分组名册（2026-09-19：用户要求 AI 也能建分组、也能把地点归到某一组）----
    //
    // 用户原话：「**添加分类**和**给地点归为到哪一类**，AI 是要有这个能力的。比如说，
    // 用户说『我将这个地点归到那一类当中』，AI 是可以操作的」。
    //
    // ⚠️ 与商品分类**最大的不同：这是按人分区的**（每个人管自己地址库左栏那一列）。
    //    所以卡片上要说清"改的是**你自己**的分组"，而且**不许**出现别人的分组名 ——
    //    数据源 `ds.placeCategories()` 读的就是当前登录人那一份，越权在数据源上就不可能。
    const val PLACE_CATEGORY_CREATE = "place_category.create"
    const val PLACE_CATEGORY_UPDATE = "place_category.update"
    const val PLACE_CATEGORY_DELETE = "place_category.delete"
    const val PLACE_CATEGORY_REORDER = "place_category.reorder"

    // ---- 另外三张**配置名册**：开销分类 / 运费分类 / 预订单分类（2026-09-23 补齐 AI 能力覆盖）
    //
    // 这三张名册原来在 `_write_coverage.py` 里挂着「不做」的理由（"分类名册是界面配置，
    // 用户在分类管理页上调"）。2026-09-23 复核时按用户那条硬规矩收回：
    // **「人能操作、AI 就要能操作」**（用户 2026-09-22 原话：「所有的操作，主要是人能操作的
    // 他都可以操作」）—— 界面上分类管理页能做的四件事（建/改名/排序/删），AI 都要有。
    //
    // ⚠️ 三条**必须写在卡片上**的后果（这也是当初那条"不做"理由真正担心的东西）：
    //   ① **改名会级联**：开销分类改名 → 挂在这一类下的开销记录跟着改名；
    //      预订单分类改名 → 挂着的预设单跟着改名（后端同一个事务里做）。
    //      所以改名的卡上必须写出"这一类下有 N 笔开销 / N 张预设单"。
    //   ② **删之前要看挂着多少**：三张名册在后端都会拒绝"还有东西挂着"的删除，
    //      并把数量写在报错里 —— 卡片上要先把那个数摆出来（别让用户点完确认才吃一个错）。
    //   ③ **排序是整份提交**（名册里每一格都要出现一次，少一个后端整份拒绝），
    //      所以"重排"是手写动作，卡片要把改前改后两份顺序都列出来。
    // ⚠️ 三组都**只有派单员**（后端这几个端点全是派单员权限）；不进 [SHIPPER_ACTIONS]
    //    就是默认不给货主（fail-closed）。
    const val EXPENSE_CATEGORY_CREATE = "expense_category.create"
    const val EXPENSE_CATEGORY_UPDATE = "expense_category.update"
    const val EXPENSE_CATEGORY_DELETE = "expense_category.delete"
    const val EXPENSE_CATEGORY_REORDER = "expense_category.reorder"
    const val FREIGHT_CATEGORY_CREATE = "freight_category.create"
    const val FREIGHT_CATEGORY_UPDATE = "freight_category.update"
    const val FREIGHT_CATEGORY_DELETE = "freight_category.delete"
    const val FREIGHT_CATEGORY_REORDER = "freight_category.reorder"
    const val ORDER_TEMPLATE_CATEGORY_CREATE = "order_template_category.create"
    const val ORDER_TEMPLATE_CATEGORY_UPDATE = "order_template_category.update"
    const val ORDER_TEMPLATE_CATEGORY_DELETE = "order_template_category.delete"
    const val ORDER_TEMPLATE_CATEGORY_REORDER = "order_template_category.reorder"

    // ---- 共享地点库的管理（2026-09-19：用户要求 AI 也要会这一套）----
    //
    // 用户原话：「再给派单端的 AI 去增加这些功能，比如说**更改共享地址的名称**，
    // 或者说更改地址的名称，它这些都要有；还有**撤销某个共享地址**、将某个共享地址
    // **降为一个普通的**…或者说**直接删除**某个共享地址都可以」。
    //
    // ⚠️ 与「地点」（`location.*`）是**两张表**，卡片上不能混：
    //    `location.*` 动的是**你自己**的地点库（按人分区）；
    //    这一组动的是**全库共用**的那一张（改一条，所有人的选点列表都跟着变）。
    // ⛔ **坐标一律不给**：共享库里的坐标是"某个位置是哪儿"的事实，模型编一个会把司机带错地方
    //    （`POST /places` 就是因为这条被永久排除在 AI 之外的）。"设为共享地址"这个动作
    //    的输入是**一个地点编号**，坐标从那一条上抄——模型全程碰不到经纬度。
    // ⚠️ 这一组**只有派单员**：不进 [SHIPPER_ACTIONS] 就是默认不给货主（fail-closed）。
    const val PLACE_UPDATE = "place.update"
    const val PLACE_DELETE = "place.delete"
    const val PLACE_DEMOTE = "place.demote"
    const val PLACE_PUBLISH = "place.publish"
    //: 从回收站把共享地点放回来。**只给撤回用**（`undoOnly`）：被删的记录在名册里解析不到，
    //: 模型按名字根本找不到它 —— 但撤回路径拿着确定的编号，所以这条必须存在。
    const val PLACE_RESTORE = "place.restore"

    // ---- 商品可见范围（白名单）----
    //
    // 用户 2026-09-18 原话：「甚至也可以直接叫 ai 操作（指定某个批发商/货主只能看到哪些商品）」。
    // 它本质是**授权**，所以是 HIGH：改错了，那个货主打开选品页会少东西（或什么都看不到）。
    const val USER_PRODUCT_VISIBILITY = "user.product_visibility"

    /** 域标签：清单与文档按它分组。 */
    const val G_ORDER = "订单"
    /**
     * 退货申请（货主申请 → 派单员办理）。
     *
     * 单独一个域而不是并进 [G_ORDER]：它在界面上是**两个人的两件事**——
     * 货主那一栏是"我提的申请"，派单员那一栏是"待我办的申请"；
     * 并进「订单」之后，两边会在同一个域里看到对方才该用的动作
     * （货主看到"办理退货申请"、派单员看到"申请退货"，都是点了必然失败的卡）。
     */
    const val G_RETURN_REQUEST = "退货申请"
    const val G_LEDGER = "账目"
    /**
     * 供应商 / 厂商与应付款（2026-09-22）。
     *
     * 单独一个域而不是并进 [G_LEDGER]：`G_LEDGER` 是**日记账**（一笔一笔的收支流水：
     * 记支出、客户收款、账本记一笔…），而这一域是**往来账**（欠谁多少、分几次付清）。
     * 用户在设置页上是照着"我要干的那件事"找动作的，"付供应商尾款"不该混在
     * "记一笔油费"中间 —— 那两件事的记录对象、核对方式、后果都不一样。
     */
    const val G_SUPPLIER = "供应商/应付款"
    /**
     * 货主自己那一本账（批发商给下游货主核销）。
     *
     * 单独一个域而不是并进 [G_LEDGER]：`G_LEDGER` 是**公司账**（派单员写的），
     * 两本账混在一个域里，界面上会出现"同一个域里一半能动、一半必然 403"——
     * 而按域分组的设置页与 AI 工具清单都是照域给的。
     */
    const val G_MY_LEDGER = "我的账本"
    const val G_MSG = "消息"
    const val G_PRODUCT = "商品"
    const val G_CATEGORY = "商品分类"
    /** 地点分组（**按人分区**：每个人管自己地址库左栏那一列）。 */
    const val G_PLACE_CATEGORY = "地点分组"
    /** 开销分类名册（决定「这笔钱算哪一类」，改名会级联改掉挂着的开销）。 */
    const val G_EXPENSE_CATEGORY = "开销分类"
    /** 运费分类名册（决定「这类货走哪条价目」）。 */
    const val G_FREIGHT_CATEGORY = "运费分类"
    /** 预订单分类名册（决定「我这几张常用的单分成哪几类」）。 */
    const val G_ORDER_TEMPLATE_CATEGORY = "预订单分类"
    /** 共享地点（**全库共用**那一张表：改一条，所有人的选点列表都跟着变）。 */
    const val G_PLACE = "共享地点"
    const val G_PRICE = "批发商定价"
    const val G_STOCK = "库存"
    const val G_USER = "账号与收费规则"
    const val G_ADDRESS = "地址与联系人"

    // ------------------------------------------------------------- 枚举别名

    /**
     * 支出分类：中英双向。
     *
     * 为什么要别名：用户用中文说「记一笔油费」，模型很自然地会传 `油费` 而不是 `fuel`。
     * 只认英文会让模型去猜（然后就猜错），只认中文又和 [AiReadCatalog] 里读回来的英文对不上。
     * 两边都收，归一成后端要的 code，**既不猜也不报错**。
     */
    val EXPENSE_CATEGORIES: Map<String, String> = linkedMapOf(
        "fuel" to "油费",
        "repair" to "维修",
        "toll" to "过路费",
        "parking" to "停车费",
        "fine" to "罚款",
        "insurance" to "保险",
        "loss" to "货损",
        "other" to "其他",
    )

    // ------------------------------------------------------------- 动作清单

    /** 顺序 = 设置页里的显示顺序（手写的在前，声明式的在后）。 */
    val ALL: List<AiWriteAction>
        get() = MANUAL + AiWriteMasterData.ALL + AiWriteBasicData.ALL +
            AiWritePricing.ACTIONS + AiWriteSettlements.ACTIONS +
            AiWriteShipperLedger.ACTIONS + AiWriteReturnRequest.ACTIONS +
            // 预订单 / 订单模板（2026-09-22 用户要求「AI 直接创建预定单」）
            AiWriteOrderTemplates.ACTIONS +
            // 供应商 / 厂商档案 + 应付款（2026-09-22 用户要求「给供应商付尾款」）
            AiWriteSuppliers.ACTIONS

    /** 手写处理器的动作清单（订单 / 账目 / 消息）。 */
    private val MANUAL: List<AiWriteAction> = listOf(
        AiWriteAction(
            id = NOTIFICATIONS_READ_ALL,
            title = "消息全部标为已读",
            risk = AiWriteRisk.LOW,
            group = G_MSG,
            blurb = "把当前账号的消息中心里**所有未读消息**标成已读。只改你自己的已读标记，不删任何消息。",
            params = emptyList(),
        ),
        AiWriteAction(
            id = EXPENSES_CREATE,
            title = "记一笔支出",
            risk = AiWriteRisk.MEDIUM,
            group = G_LEDGER,
            blurb = "新增一条支出记录（油费、维修、过路费、停车费、罚款、保险、货损、其他），" +
                "会进财务报表的支出统计。可选关联到某个司机或某辆车。",
            params = listOf(
                AiWriteParam(
                    "category", "支出类别", required = true, kind = AiWriteParamKind.ENUM,
                    hint = "必填", enumValues = EXPENSE_CATEGORIES.keys.toList(),
                ),
                AiWriteParam(
                    "amount", "金额（元）", required = true, kind = AiWriteParamKind.NUMBER,
                    hint = "必填，必须大于 0。只传数字，不要带「元」字",
                ),
                AiWriteParam(
                    "exp_date", "发生日期", kind = AiWriteParamKind.DATE,
                    hint = "YYYY-MM-DD；不填默认今天",
                ),
                AiWriteParam(
                    "driver", "司机姓名", hint = "可选。**只传姓名**，编号由系统自己找",
                ),
                AiWriteParam(
                    "vehicle", "车牌号", hint = "可选。如 豫A12345；**只传车牌**，不要传车辆编号",
                ),
                AiWriteParam("note", "备注", hint = "可选，一句话"),
            ),
        ),
        AiWriteAction(
            id = LEDGER_CREATE_ENTRY,
            title = "账本记一笔",
            risk = AiWriteRisk.MEDIUM,
            group = G_LEDGER,
            blurb = "在订单账里新增一条流水（记某个货主/客户买了什么、多少数量、什么单价）。" +
                "这是货主对账的依据，填错会影响对账。",
            params = listOf(
                AiWriteParam(
                    "shipper", "货主/客户名", required = true,
                    hint = "必填。写用户平时叫的名字；系统里没有这个名字时会按「临时客户」记，摘要里会写明",
                ),
                AiWriteParam("product", "商品", required = true, hint = "必填，如「红富士苹果」"),
                AiWriteParam(
                    "quantity", "数量", kind = AiWriteParamKind.NUMBER,
                    hint = "整数，不填默认 1",
                ),
                AiWriteParam(
                    "unit_price", "单价（元）", kind = AiWriteParamKind.NUMBER,
                    hint = "可选，只传数字。**不填就按这个货主的价算**（专属价优先、否则商品默认价）——" +
                        "用户没报过价就别自己填；填了但与他的价不一样，卡片会把两个数都写出来",
                ),
                AiWriteParam(
                    "entry_date", "发生日期", kind = AiWriteParamKind.DATE,
                    hint = "YYYY-MM-DD；不填默认今天",
                ),
                AiWriteParam("note", "备注", hint = "可选，一句话"),
            ),
        ),

        // ------------------------------------------------------------ 订单域
        // 这一批全是 HIGH 档：它们**影响别人**（司机会收到推送、货主会看到状态变化）、
        // 或者**撤不回来**（撤销之后是终态）。所以卡片上必须写清楚"这一单是哪个单、
        // 影响谁"，让用户能核对——那是他唯一能拦住一次错操作的机会。
        AiWriteAction(
            id = ORDERS_ASSIGN,
            title = "派单",
            risk = AiWriteRisk.HIGH,
            group = G_ORDER,
            blurb = "把一张**待派单**的订单派给某个司机。派完这单状态变「派单中」，司机会立刻收到推送。",
            params = listOf(
                AiWriteParam(
                    "order", "订单", required = true, kind = AiWriteParamKind.TEXT,
                    hint = "必填。订单号（如 SOTEST2026091100230）；不确定就先查一下",
                ),
                AiWriteParam(
                    "driver", "司机姓名", required = true,
                    hint = "必填。**只传姓名**，编号由系统自己找；用户没说派给谁就先问他，不要替他挑",
                ),
                AiWriteParam(
                    "freight", "司机运费（元）", kind = AiWriteParamKind.NUMBER,
                    hint = "可选。只传数字；不填则保持待定（派单员可事后在页面上补录）",
                ),
                AiWriteParam(
                    "piece_amount", "这一单单独定的司机金额（元）", kind = AiWriteParamKind.NUMBER,
                    hint = "可选。用户说「这一单给他 300」这类**逐单的钱**时用它（每单不固定、由派单员定）。" +
                        "只在这个司机挂着计费规则时生效——卡片上会写出他的规则，看不到规则就先问用户",
                ),
                AiWriteParam(
                    "commission_rate", "这一单单独定的提成比例（%）", kind = AiWriteParamKind.NUMBER,
                    hint = "可选。用户说「这一单按 8% 抽」时用它。**基数仍按司机规则**（按运费或按商品金额）；" +
                        "规则里没有提成项时后端会拒绝，先读一下 driver_billing_rules.list_rules 确认再传",
                ),
                AiWriteParam(
                    "collect_cash", "是否收取现金", kind = AiWriteParamKind.ENUM,
                    hint = "可选，true/false。勾了的话司机送达时要现场收钱",
                    enumValues = listOf("true", "false"),
                ),
                AiWriteParam("note", "给司机的备注", hint = "可选，一句话（司机能看到）"),
            ),
        ),
        AiWriteAction(
            id = ORDERS_RECALL,
            title = "撤回派单",
            risk = AiWriteRisk.HIGH,
            group = G_ORDER,
            blurb = "把**已经派出去**的订单收回来（回到「待派单」），可以重新派给别人。" +
                "原司机会收到一条撤回推送。已接单的也能撤。",
            params = listOf(
                AiWriteParam("order", "订单", required = true, hint = "必填，订单号"),
                AiWriteParam(
                    "reason", "撤回原因", required = true,
                    hint = "必填。会**推送给原司机**，所以要写清楚（如「车辆临时故障，改派他人」）",
                ),
            ),
        ),
        AiWriteAction(
            id = ORDERS_CANCEL,
            title = "撤销订单",
            risk = AiWriteRisk.HIGH,
            group = G_ORDER,
            blurb = "把订单撤销掉。**只有「待派单」和「已派单（司机未接单）」两种状态能撤**；" +
                "撤销后是终态，撤销同时会自动把占用恢复。",
            params = listOf(
                AiWriteParam("order", "订单", required = true, hint = "必填，订单号"),
            ),
        ),
        AiWriteAction(
            id = ORDERS_RETURN,
            title = "订单退货",
            risk = AiWriteRisk.HIGH,
            group = G_ORDER,
            blurb = "**已送达**的单，客户把货退回来。可以整单退，也可以只退其中几个商品（用 lines 点名）。" +
                "一次会动四样：账本红冲（营业额减）、库存回补、这单如果已经收过钱就**自动记一笔退款**、" +
                "整单退完这单变成「已退货」。**货损的那几件不能退**（那部分已经计过损失）。",
            params = listOf(
                AiWriteParam("order", "订单", required = true, hint = "必填，订单号"),
                AiWriteParam(
                    "lines", "退哪些商品", kind = AiWriteParamKind.TEXT,
                    hint = "**留空 = 整单退货**。只退一部分时传数组：" +
                        "[{\"product\":\"红富士苹果\",\"quantity\":2}]（product 传商品名，quantity 只传数字）",
                ),
                AiWriteParam("note", "退货备注", hint = "可选，一句话（会写进这笔退货的审计记录）"),
            ),
        ),
        AiWriteAction(
            id = ORDERS_CREATE,
            title = "创建订单",
            risk = AiWriteRisk.HIGH,
            group = G_ORDER,
            blurb = "替某个货主新建一张订单（派单员代理下单）。新单是「待派单」状态，货主和系统都会看到。",
            params = listOf(
                AiWriteParam(
                    "shipper", "货主名", required = true,
                    hint = "必填。写用户平时叫的名字；系统里没有这个名字时会按「临时货主」记，摘要里会写明",
                ),
                AiWriteParam(
                    "lines", "商品明细", required = true, kind = AiWriteParamKind.TEXT,
                    hint = "必填，**数组**：[{\"product\":\"红富士苹果\",\"quantity\":3,\"unit_price\":5.5}, ...]" +
                        "（最多 10 行；product 传商品名，quantity 和 unit_price 只传数字）。" +
                        "unit_price **可以不填**：不填就按**这个货主的价**算（他跟你有专属价就用专属价，" +
                        "否则商品默认价）—— 用户没报过价就别自己填，" +
                        "填了但与他的价不一样，卡片会把两个数都写出来让你回去核对。",
                ),
                AiWriteParam(
                    "address", "送货地址",
                    hint = "可选。用户说了就填；没说就留空（他能在页面上补）" + HERE_HINT,
                ),
                AiWriteParam("date", "下单日期", kind = AiWriteParamKind.DATE, hint = "YYYY-MM-DD；不填默认今天"),
                AiWriteParam("name_dongjia", "收货人名称", hint = "可选。到现场接货的人叫什么"),
                AiWriteParam("phone_dongjia", "收货人电话", hint = "可选"),
                AiWriteParam("name_boss", "下单人名称", hint = "可选。下这一单的人叫什么"),
                AiWriteParam("phone_boss", "下单人电话", hint = "可选"),
                AiWriteParam("remark", "备注", hint = "可选，一句话"),
            ),
        ),
        AiWriteAction(
            id = ORDERS_FREIGHT,
            title = "改司机运费",
            risk = AiWriteRisk.MEDIUM,
            group = G_ORDER,
            blurb = "补录或修改这张单的司机运费。**已送达/已撤销的单不能改**。",
            params = listOf(
                AiWriteParam("order", "订单", required = true, hint = "必填，订单号"),
                AiWriteParam(
                    "freight", "司机运费（元）", required = true, kind = AiWriteParamKind.NUMBER,
                    hint = "必填。只传数字，0 表示这单不收运费",
                ),
            ),
        ),
        AiWriteAction(
            id = ORDERS_PAY,
            title = "现场收款确认",
            risk = AiWriteRisk.HIGH,
            group = G_ORDER,
            blurb = "把这单记成「已收现金」（货到付款）。会清掉原来挂的账。**已撤销的单不能收款。**",
            params = listOf(
                AiWriteParam("order", "订单", required = true, hint = "必填，订单号"),
            ),
        ),
        AiWriteAction(
            id = ORDERS_CHARGE,
            title = "挂账到单位",
            risk = AiWriteRisk.HIGH,
            group = G_ORDER,
            blurb = "把这单的货款挂到某个**挂账单位**名下（改成未收、欠款记在那个单位头上）。",
            params = listOf(
                AiWriteParam("order", "订单", required = true, hint = "必填，订单号"),
                AiWriteParam(
                    "unit", "挂账单位名", required = true,
                    hint = "必填。**只传名字**，系统自己找；找不到就让用户确认，不要猜",
                ),
            ),
        ),

        // ------------------------------------------- 订单域·第二批（改单 / 异常 / 拆单 / 批量派单）
        //
        // 档位不是按"操作类型"给的，是按**后果的形状**：
        //   · 改单 MEDIUM——它只改这单自己的资料，不改状态、不推送给别人；
        //     但它改的是"司机照着跑的信息"，所以卡片必须逐字段写「改前 → 改后」。
        //   · 标记异常 MEDIUM——加一枚给别人看的标记，可逆（能解除），不推送。
        //   · 解除异常 MEDIUM——去掉标记，同样可逆、不推送。
        //   · 拆单 HIGH——**新建**若干子单并撤销原单，撤销是终态，错了只能重建。
        //   · 批量派单 HIGH——一次动多张单，范围错一张用户看不出来（多派一趟车）。
        AiWriteAction(
            id = ORDERS_UPDATE,
            title = "改单",
            risk = AiWriteRisk.MEDIUM,
            group = G_ORDER,
            blurb = "改一张**还没送达**的订单的资料：送达说明、送货地址、收货人、下单人、备注、内部备注。" +
                "只改你点名的那几项，其余原样。已送达/已撤销的单不能改。",
            params = listOf(
                AiWriteParam(
                    "order", "订单", required = true, kind = AiWriteParamKind.TEXT,
                    hint = "必填，订单号；不确定就先查一下",
                ),
                AiWriteParam("delivery", "送达说明", hint = "可选。送给客户/司机看的说明"),
                AiWriteParam("address", "送货地址", hint = "可选。改完司机会按新地址跑" + HERE_HINT),
                AiWriteParam("dongjia_name", "收货人名称", hint = "可选。到现场接货的人叫什么"),
                AiWriteParam("dongjia_phone", "收货人电话", hint = "可选。收货方联系人电话"),
                AiWriteParam("boss_name", "下单人名称", hint = "可选。下这一单的人叫什么"),
                AiWriteParam("boss_phone", "下单人电话", hint = "可选。下单方电话"),
                AiWriteParam("remark", "备注", hint = "可选"),
                AiWriteParam("internal_note", "内部备注", hint = "可选。只有内部能看"),
            ),
        ),
        AiWriteAction(
            id = ORDERS_MARK_EXCEPTION,
            title = "标记异常",
            risk = AiWriteRisk.MEDIUM,
            group = G_ORDER,
            blurb = "给一张订单打上**异常标记**（会出现在报表中心的异常清单里）。" +
                "货物状态、司机、金额都不变；标错了可以「解除异常」。",
            params = listOf(
                AiWriteParam("order", "订单", required = true, hint = "必填，订单号"),
                AiWriteParam(
                    "reason", "异常原因", required = true,
                    hint = "必填。一句话，会显示在异常清单里（别人靠它判断当时怎么了）",
                ),
                AiWriteParam(
                    "expected_before", "预计送达时间", kind = AiWriteParamKind.TEXT,
                    hint = "可选。例如 2026-09-16 18:00",
                ),
            ),
        ),
        AiWriteAction(
            id = ORDERS_RESOLVE_EXCEPTION,
            title = "解除异常",
            risk = AiWriteRisk.MEDIUM,
            group = G_ORDER,
            blurb = "把订单上的**异常标记清掉**（并记下是怎么解决的）。" +
                "和报表中心「异常与审计」里那个按钮是同一条路。只有当前确实是异常的单才需要做。",
            params = listOf(
                AiWriteParam("order", "订单", required = true, hint = "必填，订单号"),
                AiWriteParam(
                    "note", "解决说明", required = true,
                    hint = "必填。一句话说清怎么处理的，以后回查靠它",
                ),
            ),
        ),
        AiWriteAction(
            id = ORDERS_SPLIT,
            title = "拆单",
            risk = AiWriteRisk.HIGH,
            group = G_ORDER,
            blurb = "把一张**待派单**按比例拆成几张子单（商品数量按比例分，余数归第 1 单）。" +
                "**原单会变成已撤销留痕，撤不回来**；子单都是待派单，之后要分别派车。",
            params = listOf(
                AiWriteParam("order", "订单", required = true, hint = "必填，订单号"),
                AiWriteParam(
                    "parts", "拆分比例", required = true, kind = AiWriteParamKind.TEXT,
                    hint = "必填。写成 5,3,2 表示三等份按 5:3:2 分；至少两份，**不要替用户默认平均分**",
                ),
            ),
        ),
        AiWriteAction(
            id = ORDERS_BATCH_ASSIGN,
            title = "批量派单",
            risk = AiWriteRisk.HIGH,
            group = G_ORDER,
            blurb = "把**多张待派单**一次派给同一个司机，司机会一次收到多条派单。" +
                "至少两张，最多 $MAX_BATCH_ASSIGN 张；其中任何一张状态不对就整批不做。",
            params = listOf(
                AiWriteParam(
                    "orders", "订单号（多个）", required = true, kind = AiWriteParamKind.TEXT,
                    hint = "必填。多个订单号用逗号或空格分开；**要用户明确列出是哪几张**",
                ),
                AiWriteParam(
                    "driver", "司机姓名", required = true,
                    hint = "必填。**只传姓名**；用户没说派给谁就先问他",
                ),
                AiWriteParam(
                    "collect_cash", "是否收取现金", kind = AiWriteParamKind.ENUM,
                    hint = "可选，true/false。不填则按各单原本的设置",
                    enumValues = listOf("true", "false"),
                ),
                AiWriteParam("note", "给司机的备注", hint = "可选，一句话（司机能看到）"),
            ),
        ),

        // ------------------------------------------------------------ 账本域（第二批）
        //
        // 定位方式与其它域完全不同：账本流水**没有天然的名字或编号**（订单有单号、账号有姓名、
        // 商品有商品名），它就是"某天 + 某货主 + 某摘要 + 某金额"的一行。
        // 所以这四个动作都要"靠人说的特征去对"，对不上或对上多条一律拒绝列候选。
        AiWriteAction(
            id = LEDGER_UPDATE_ENTRY,
            title = "改账本流水",
            risk = AiWriteRisk.HIGH,
            group = G_LEDGER,
            blurb = "改账本里的一行流水（金额 / 数量 / 单价 / 日期 / 摘要 / 备注）。" +
                "⚠️ 如果这一行是**订单自动入账**的，改商品与金额会同时**回写那张订单的商品明细**。",
            params = listOf(
                AiWriteParam("shipper", "货主名", hint = "可选。这行记在哪个货主名下（用户提了才填）"),
                AiWriteParam(
                    "product", "摘要关键词", required = true, kind = AiWriteParamKind.TEXT,
                    hint = "必填。用户在说哪一行？把摘要/商品名里最独特的那几个字传进来",
                ),
                AiWriteParam(
                    "date", "这行的日期", kind = AiWriteParamKind.DATE,
                    hint = "可选 YYYY-MM-DD。用户说了是哪天的就填，能少歧义",
                ),
                AiWriteParam(
                    "amount", "这行现在的金额", kind = AiWriteParamKind.NUMBER,
                    hint = "可选。用户说「那条 320 的」就填 320，用来跟别的行区分开",
                ),
                AiWriteParam("new_amount", "改成多少（合计）", kind = AiWriteParamKind.NUMBER, hint = "可选"),
                AiWriteParam("new_quantity", "改成几件", kind = AiWriteParamKind.NUMBER, hint = "可选"),
                AiWriteParam("new_unit_price", "改成单价", kind = AiWriteParamKind.NUMBER, hint = "可选"),
                AiWriteParam("new_date", "改到哪一天", kind = AiWriteParamKind.DATE, hint = "可选 YYYY-MM-DD"),
                AiWriteParam("new_product", "摘要改成", hint = "可选"),
                AiWriteParam("note", "备注改成", hint = "可选"),
            ),
        ),
        AiWriteAction(
            id = LEDGER_DELETE_ENTRY,
            title = "删账本流水",
            risk = AiWriteRisk.HIGH,
            group = G_LEDGER,
            blurb = "删掉账本里的一行流水。**删了就没了**，只能重新记一笔；" +
                "如果这行是订单入账来的，**订单明细不会跟着回滚**（要改订单请用「改单」或订单商品行）。",
            params = listOf(
                AiWriteParam("shipper", "货主名", hint = "可选。这行记在哪个货主名下"),
                AiWriteParam(
                    "product", "摘要关键词", required = true, kind = AiWriteParamKind.TEXT,
                    hint = "必填。要删的是哪一行（摘要/商品名里最独特的几个字）",
                ),
                AiWriteParam("date", "这行的日期", kind = AiWriteParamKind.DATE, hint = "可选 YYYY-MM-DD"),
                AiWriteParam(
                    "amount", "这行现在的金额", kind = AiWriteParamKind.NUMBER,
                    hint = "可选。用来跟别的行区分",
                ),
            ),
        ),
        AiWriteAction(
            id = LEDGER_CREATE_RECEIPT,
            title = "记客户收款",
            risk = AiWriteRisk.HIGH,
            group = G_LEDGER,
            blurb = "记一笔**客户付款**（客户给了多少钱），可以指定这笔钱核销哪几张订单——" +
                "指定的订单会被标记成**已收**。不指定订单就是一笔暂未核销的收款。",
            params = listOf(
                AiWriteParam(
                    "customer", "客户名", required = true,
                    hint = "必填。**只传名字**，编号由系统自己找；找不到就让用户确认，不要猜",
                ),
                AiWriteParam("amount", "收款金额（元）", required = true, kind = AiWriteParamKind.NUMBER, hint = "必填，只传数字"),
                AiWriteParam(
                    "method", "收款方式", kind = AiWriteParamKind.ENUM,
                    hint = "可选，默认现金",
                    enumValues = listOf("cash", "transfer", "wechat", "arrears_settle"),
                ),
                AiWriteParam("date", "收款日期", kind = AiWriteParamKind.DATE, hint = "可选 YYYY-MM-DD，不填默认今天"),
                AiWriteParam(
                    "orders", "核销哪几张单", kind = AiWriteParamKind.TEXT,
                    hint = "可选。订单号，多个用逗号分开；**用户没说就别猜**（不填＝这笔钱先不核销到单上）",
                ),
                AiWriteParam("note", "备注", hint = "可选，一句话"),
            ),
        ),
        AiWriteAction(
            id = LEDGER_SYNC_DELIVERED,
            title = "补进账本",
            risk = AiWriteRisk.MEDIUM,
            group = G_LEDGER,
            blurb = "把**已送达但还没进账本**的订单补进去（幂等：重复跑不会重复入账）。" +
                "不填货主就是对全部货主补一遍。给某位货主补账时会推送一条账本更新通知。",
            params = listOf(
                AiWriteParam(
                    "shipper", "只补这个货主", hint = "可选。不填＝全部货主各补一遍",
                ),
            ),
        ),

        // ------------------------------- 订单域·第三批（商品行 / 回收站）
        //
        // 商品行三个动作是"改单"的细化：改单改的是地址电话备注，改商品行改的是**货本身**。
        // 后端的状态门一样（待派单/派单中/已接单可编辑），而且**行改了订单金额就跟着变**，
        // 所以卡片要把"这单金额从多少变成多少"算给用户看。
        AiWriteAction(
            id = ORDERS_ADD_LINE,
            title = "加一行商品",
            risk = AiWriteRisk.MEDIUM,
            group = G_ORDER,
            blurb = "给订单加一行商品（货主临时又加了两件）。**订单金额会跟着变**。" +
                "只有「待派单/派单中/已接单」的单能改明细。",
            params = listOf(
                AiWriteParam("order", "订单", required = true, hint = "必填，订单号"),
                AiWriteParam(
                    "product", "商品名", required = true, kind = AiWriteParamKind.TEXT,
                    hint = "必填。写商品名就行（可以是货主口头说的名字，不必是商品库里的）",
                ),
                AiWriteParam("quantity", "几件", required = true, kind = AiWriteParamKind.NUMBER, hint = "必填，整数"),
                AiWriteParam(
                    "unit_price", "单价（元）", kind = AiWriteParamKind.NUMBER,
                    hint = "可选。不填就按**这个订单货主的价**算（他跟你有专属价就用专属价，否则商品库默认价）；" +
                        "填了要以用户说的为准 —— 但与他的价不一样时卡片会把两个数都写出来",
                ),
            ),
        ),
        AiWriteAction(
            id = ORDERS_UPDATE_LINE,
            title = "改一行商品",
            risk = AiWriteRisk.MEDIUM,
            group = G_ORDER,
            blurb = "改订单里某一行商品的数量 / 单价 / 名称。**订单金额会跟着变**。" +
                "要改的是哪一行，按商品名对；对不上或对上多行要问清楚，不要自己挑。",
            params = listOf(
                AiWriteParam("order", "订单", required = true, hint = "必填，订单号"),
                AiWriteParam(
                    "product", "要改哪一行", required = true, kind = AiWriteParamKind.TEXT,
                    hint = "必填。这一行的商品名（用户怎么说就怎么传）",
                ),
                AiWriteParam("quantity", "改成几件", kind = AiWriteParamKind.NUMBER, hint = "可选，整数"),
                AiWriteParam("unit_price", "改成单价", kind = AiWriteParamKind.NUMBER, hint = "可选"),
                AiWriteParam("new_product", "商品名改成", hint = "可选"),
            ),
        ),
        AiWriteAction(
            id = ORDERS_DELETE_LINE,
            title = "删一行商品",
            risk = AiWriteRisk.HIGH,
            group = G_ORDER,
            blurb = "删掉订单里的一行商品（货主说这货不要了）。**订单金额会跟着变**，删了就没了" +
                "（要恢复只能重新加一行）。只有「待派单/派单中/已接单」的单能改明细。",
            params = listOf(
                AiWriteParam("order", "订单", required = true, hint = "必填，订单号"),
                AiWriteParam(
                    "product", "要删哪一行", required = true, kind = AiWriteParamKind.TEXT,
                    hint = "必填。这一行的商品名",
                ),
            ),
        ),
        AiWriteAction(
            id = ORDERS_SOFT_DELETE,
            title = "移入回收站",
            risk = AiWriteRisk.HIGH,
            group = G_ORDER,
            blurb = "把订单**移进回收站**（隔离区）：用户列表里立刻看不到它，**30 天内可以恢复**，" +
                "到期系统会物理清理。派单员可对任意状态的单做这件事；" +
                "**货主（含批发商）只能删「已撤销」的单** —— 已送达的单是已经发生过的一趟生意" +
                "（账本、司机账单挂在它上面），AI 不替货主删它，要删请他自己在订单详情页操作。",
            params = listOf(
                AiWriteParam("order", "订单", required = true, hint = "必填，订单号；不确定就先查一下"),
            ),
        ),
        // ------------------------------------------- 订单域·第四批（补地点，2026-09-20）
        //
        // 用户原话：「同时派单员其实也可以对这些地点…叫 AI 补上地点，也可以叫 AI 补上照片」。
        //
        // ⛔ **模型全程碰不到经纬度**：它只说"用共享地点库里的哪一个"（[AiWriteParam] 里
        //    那一个名字），坐标由 App 从库里取出来（`AiWriteArgs.strict` 解析 → 库里那一条的
        //    lat/lng）。所以「模型给不出坐标」这条老约束**没有被推翻**，而是绕开了：
        //    以前这个端点被列在 `_write_coverage` 的"坐标类：永久不做"里，就是因为
        //    "让模型传经纬度"这件事本身是错的；现在传的是**库里的编号**。
        //    红线钉着这一条：`_check_ai_guardrails.py` 的「补导航只能引用已有的坐标」。
        //
        // 档位 MEDIUM：它只补这单的坐标（并顺手进地点库），不改状态、不推送；
        // 但**写进去就撤不回来**（没有"取消导航"这个端点），所以卡片必须把
        // "用的是哪个点、坐标是多少"写在脸上 —— 用户核对的是这两个数，不是那句话。
        AiWriteAction(
            id = ORDERS_FILL_NAV,
            title = "补导航信息",
            risk = AiWriteRisk.MEDIUM,
            group = G_ORDER,
            blurb = "给一张**还没有坐标**的单补上导航信息：从**共享地点库**里挑一个已有的地点，" +
                "把它的坐标写到这单上。会同时进这单、货主的地点库、全库共享地点库。" +
                "已经有了坐标的单一律拒绝（不覆盖）。",
            params = listOf(
                AiWriteParam("order", "订单", required = true, hint = "必填，订单号；不确定就先查一下"),
                AiWriteParam(
                    "place", "用哪个地点", required = true,
                    hint = "必填。**共享地点库里已有的地点名**（不是地址、不要自己编坐标）——" +
                        "库里没有这个位置就让用户自己在地图上标，不要猜",
                ),
                AiWriteParam("name", "地点名", hint = "可选。写进地点库时用的名字；不填就用库里那个名字"),
            ),
        ),
        AiWriteAction(
            id = ORDERS_RESTORE,
            title = "从回收站恢复",
            risk = AiWriteRisk.MEDIUM,
            group = G_ORDER,
            blurb = "把回收站（隔离区）里的订单恢复回来（**仅派单员**）。" +
                "只能恢复已经被软删的单；没删过的单不需要恢复。",
            params = listOf(
                AiWriteParam(
                    "order", "订单", required = true,
                    hint = "必填，订单号。**这一单必须在回收站里**，普通单号是查不到的",
                ),
            ),
        ),

        // ------------------------------------------------------------ 消息域
        //
        // 这一批里"发"的两个是 HIGH：**消息会推给别人**，发出去收不回来。
        // 而"标记已读 / 改内容 / 删"只动**自己**的消息，但都要先把"是哪几条"找对——
        // 找错的后果不是数据错，是**把别的消息误删/误改**，所以一律上卡片。
        AiWriteAction(
            id = NOTIFICATIONS_SEND,
            title = "发消息给某人",
            risk = AiWriteRisk.HIGH,
            group = G_MSG,
            blurb = "给某个账号（货主/司机/内勤）发一条站内消息，**对方会收到推送**。" +
                "标题与正文都由你说，所以卡片会把两行都摊开给用户核对。",
            params = listOf(
                AiWriteParam(
                    "to", "收件人", required = true,
                    hint = "必填。**只传姓名**（或手机号），编号由系统自己找；找不到就让用户确认，不要猜",
                ),
                AiWriteParam("title", "标题", required = true, hint = "必填，一句话标题"),
                AiWriteParam("content", "正文", required = true, hint = "必填，要说的事"),
                AiWriteParam(
                    // ⛔ 标题原来写「重要（语音播报）」——**模型会照着这句向用户承诺**，
                    //    而新版 App 从不读 `speech_important`（只有旧网页端读），
                    //    所以那是一句"不会发生的事"（2026-09-19 审计 R14-11）。
                    //    参数名里不许再出现"播报"这类承诺，只描述它真的做什么。
                    "important", "重要标记", kind = AiWriteParamKind.ENUM,
                    hint = "可选，true/false。默认 false；只有真的急事才填 true。" +
                        "**这只是打一个「重要」标记，新版 App 不会因此播语音**，不要向用户承诺语音提醒",
                    enumValues = listOf("true", "false"),
                ),
            ),
        ),
        AiWriteAction(
            id = NOTIFICATIONS_PRICE_CHANGE,
            title = "发价格变更通知",
            risk = AiWriteRisk.HIGH,
            group = G_MSG,
            blurb = "把**某个商品调价**这件事通知给货主（一次可以通知多个）。" +
                "标题与正文由**后端按模板自己拼**（「商品价格调整：X」＋「旧价 → 新价」），" +
                "所以这里只传结构化数据，不要自己编价格通知的措辞。",
            params = listOf(
                AiWriteParam(
                    "product", "商品名", required = true,
                    hint = "必填。**商品名要能在商品库里找到**（价格通知里带商品编号，找不到就没法发）",
                ),
                AiWriteParam(
                    "to", "通知谁", required = true, kind = AiWriteParamKind.TEXT,
                    hint = "必填。可以写「全部批发商」，也可以写一个/多个批发商姓名（逗号分开）",
                ),
                AiWriteParam("new_price", "新价格", required = true, kind = AiWriteParamKind.NUMBER, hint = "必填"),
                AiWriteParam(
                    "old_price", "原价", kind = AiWriteParamKind.NUMBER,
                    hint = "可选。填了正文里会写「旧价 → 新价」，不填就是「— → 新价」",
                ),
                AiWriteParam(
                    "price_type", "哪种价", kind = AiWriteParamKind.ENUM,
                    hint = "可选。改了商品默认价填 default；改了某个批发商的专属价填 special",
                    enumValues = listOf("default", "special"),
                ),
            ),
        ),
        AiWriteAction(
            id = NOTIFICATIONS_MARK_READ,
            title = "标记消息已读",
            risk = AiWriteRisk.MEDIUM,
            group = G_MSG,
            blurb = "把**某几条**消息标成已读（按标题/正文里的关键词找）。" +
                "要全部已读请用「消息全部已读」，那个不需要挑。",
            params = listOf(
                AiWriteParam(
                    "keyword", "关键词", required = true, kind = AiWriteParamKind.TEXT,
                    hint = "必填。哪几条消息？把标题或正文里最独特的几个字传进来",
                ),
            ),
        ),
        AiWriteAction(
            id = NOTIFICATIONS_UPDATE,
            title = "改消息内容",
            risk = AiWriteRisk.MEDIUM,
            group = G_MSG,
            blurb = "改一条**自己收到的**消息的标题/正文（改错了不影响别人，也不会重新推送）。" +
                "按关键词找到那一条，对不上或对上多条会问清楚。",
            params = listOf(
                AiWriteParam(
                    "keyword", "关键词", required = true, kind = AiWriteParamKind.TEXT,
                    hint = "必填。要改哪一条消息",
                ),
                AiWriteParam("new_title", "标题改成", hint = "可选"),
                AiWriteParam("new_content", "正文改成", hint = "可选"),
            ),
        ),
        AiWriteAction(
            id = NOTIFICATIONS_DELETE,
            title = "删消息",
            risk = AiWriteRisk.HIGH,
            group = G_MSG,
            blurb = "删掉消息：按关键词删**某几条**，或者 `all=true` **清空自己的全部消息**。" +
                "删了就没了；只影响当前登录账号的消息。",
            params = listOf(
                AiWriteParam(
                    "keyword", "关键词", kind = AiWriteParamKind.TEXT,
                    hint = "可选。删哪几条？与 all 二选一",
                ),
                AiWriteParam(
                    "all", "全部清空", kind = AiWriteParamKind.ENUM,
                    hint = "可选，true/false。true = 清空自己的全部消息（**很危险，要用户明说**）",
                    enumValues = listOf("true", "false"),
                ),
            ),
        ),

        // ------------------------------------------ 商品分类名册（整份重排）
        //
        // 为什么"重排"是**手写**动作而不是声明式：它的输入是**一整份顺序**（名册里每个分类
        // 都要出现，且只出现一次），而声明式的规格一次只处理"一条已有记录"。
        // 后端也要求整份提交（少一个就 400），所以"缺了谁"这句人话只能在这一层写。
        AiWriteAction(
            id = PRODUCT_CATEGORY_REORDER,
            title = "重排商品分类",
            risk = AiWriteRisk.MEDIUM,
            group = G_CATEGORY,
            blurb = "把商品分类在**下单页左侧那一列**里的先后顺序一次换掉。" +
                "**必须给全**：名册里的分类一个都不能漏（后端少一个就整份拒绝），" +
                "顺序就按你写的先后。它只改显示顺序，一件商品的分类都不动。",
            params = listOf(
                AiWriteParam(
                    "order", "整份顺序", required = true, kind = AiWriteParamKind.TEXT,
                    hint = "必填。按想要的先后顺序**写全所有分类名**，用「、」或逗号隔开" +
                        "（如「水果、冻品、干货」）。先读一次 product_categories.list_categories " +
                        "拿到当前名册，一个都不要漏；漏了会被拒绝并告诉你少了哪几个",
                ),
            ),
        ),

        // ------------------------------------------ 地点分组（整份重排）
        //
        // 与商品分类的"重排"同形（手写而**不是**声明式：输入是一整份顺序，
        // 声明式的规格一次只处理"一条已有记录"；后端也要求整份提交，少一个就 400）。
        AiWriteAction(
            id = PLACE_CATEGORY_REORDER,
            title = "重排地点分组",
            risk = AiWriteRisk.MEDIUM,
            group = G_PLACE_CATEGORY,
            blurb = "把你**自己的**地点分组在地址库左栏里的先后顺序一次换掉。" +
                "**必须给全**：名册里的分组一个都不能漏（后端少一个就整份拒绝）。" +
                "它只改显示顺序，一个地点归在哪一组都不动。",
            params = listOf(
                AiWriteParam(
                    "order", "整份顺序", required = true, kind = AiWriteParamKind.TEXT,
                    hint = "必填。按想要的先后顺序**写全所有分组名**，用「、」或逗号隔开" +
                        "（如「常送小区、工地」）。先读一次 place_categories.list_categories " +
                        "拿到当前名册，一个都不要漏；漏了会被拒绝并告诉你少了哪几个",
                ),
            ),
        ),

        // ------------------------------------------ 开销 / 运费 / 预订单分类（整份重排）
        //
        // 与上面两张名册的"重排"同形（手写而**不是**声明式：输入是一整份顺序，后端少一个就 400）。
        // 三张都**只有派单员**（后端那几个端点都是派单员权限）。
        AiWriteAction(
            id = EXPENSE_CATEGORY_REORDER,
            title = "重排开销分类",
            risk = AiWriteRisk.MEDIUM,
            group = G_EXPENSE_CATEGORY,
            blurb = "把开销分类在「开销管理」左栏里的先后顺序一次换掉。" +
                "**必须给全**：名册里的分类一个都不能漏（后端少一个就整份拒绝）。" +
                "它只改显示顺序，一笔开销算哪一类都不动。",
            params = listOf(
                AiWriteParam(
                    "order", "整份顺序", required = true, kind = AiWriteParamKind.TEXT,
                    hint = "必填。按想要的先后顺序**写全所有分类名**，用「、」或逗号隔开" +
                        "（如「油费、维修、过路费」）。先读一次 expense_categories.list_expense_categories " +
                        "拿到当前名册，一个都不要漏；漏了会被拒绝并告诉你少了哪几个",
                ),
            ),
        ),
        AiWriteAction(
            id = FREIGHT_CATEGORY_REORDER,
            title = "重排运费分类",
            risk = AiWriteRisk.MEDIUM,
            group = G_FREIGHT_CATEGORY,
            blurb = "把运费分类（「哪几类货」那张配置表）的先后顺序一次换掉。" +
                "**必须给全**：名册里的分类一个都不能漏（后端少一个就整份拒绝）。" +
                "它只改显示顺序，一条价目/计费规则挂在哪一类都不动。",
            params = listOf(
                AiWriteParam(
                    "order", "整份顺序", required = true, kind = AiWriteParamKind.TEXT,
                    hint = "必填。按想要的先后顺序**写全所有分类名**，用「、」或逗号隔开。" +
                        "先读一次 freight_categories.list_freight_categories 拿到当前名册，" +
                        "一个都不要漏；漏了会被拒绝并告诉你少了哪几个",
                ),
            ),
        ),
        AiWriteAction(
            id = ORDER_TEMPLATE_CATEGORY_REORDER,
            title = "重排预订单分类",
            risk = AiWriteRisk.MEDIUM,
            group = G_ORDER_TEMPLATE_CATEGORY,
            blurb = "把预订单分类在「预订单」页左栏里的先后顺序一次换掉。" +
                "**必须给全**：名册里的分类一个都不能漏（后端少一个就整份拒绝）。" +
                "它只改显示顺序，一张预设单归在哪一类都不动。",
            params = listOf(
                AiWriteParam(
                    "order", "整份顺序", required = true, kind = AiWriteParamKind.TEXT,
                    hint = "必填。按想要的先后顺序**写全所有分类名**，用「、」或逗号隔开。" +
                        "先读一次 order_template_categories.list_order_template_categories " +
                        "拿到当前名册，一个都不要漏；漏了会被拒绝并告诉你少了哪几个",
                ),
            ),
        ),

        // ------------------------------------------ 商品可见范围（白名单）
        AiWriteAction(
            id = USER_PRODUCT_VISIBILITY,
            title = "设置商品可见范围",
            risk = AiWriteRisk.HIGH,
            group = G_USER,
            blurb = "指定某个货主/批发商在选品页和下单一共能看见哪些商品：" +
                "要么「全部商品」（不限制），要么「只给勾选的」并点名那几个。" +
                "**这本质是授权**——改成「只给勾选的」之后，没勾的商品他从列表到下单都碰不到。",
            params = listOf(
                AiWriteParam(
                    "user", "货主/批发商", required = true, kind = AiWriteParamKind.TEXT,
                    hint = "必填。**只传姓名**，编号由系统自己找；对不上或对上多个会问清楚，不要自己挑",
                ),
                AiWriteParam(
                    "scope", "可见范围", required = true, kind = AiWriteParamKind.ENUM,
                    hint = "必填。all=全部商品（不限制）/ custom=只给勾选的",
                    enumValues = listOf("all", "custom"),
                ),
                AiWriteParam(
                    "products", "勾选的商品", kind = AiWriteParamKind.TEXT,
                    hint = "scope=custom 时必填：只给他看的商品名，多个用「、」隔开。" +
                        "一个都不勾会被拒绝（那样他打开选品页是空的）；想放开就传 scope=all",
                ),
            ),
        ),
    )

    /**
     * 一次最多拆几单 / 一次最多批量派几张。
     *
     * 为什么要有上限：这两个动作的输入是"用户口述的一串"，而它们的后果是**批量**的。
     * 一句"今天所有单都派给老王"如果不设上限，可能在用户完全没意识到数量时动几十单。
     * 上限不是技术限制，是**让用户有机会核对数量**：超了就让他分批，或者去页面上用批量派单。
     */
    // ⚠️ 必须与**后端**的上限一致（2026-09-19 审计）：`backend/app/schemas/order.py` 的
    //    `parts: list[int] = Field(..., min_length=2, max_length=5)` —— 服务层只再查下限，
    //    上限（5）只有 Pydantic 那一道。原来这里是 6，于是"按 1:1:1:1:1:1 拆 6 单"能一路弹到
    //    确认卡（卡片还算好了每单折算金额），点确认必吃 422「parts：最多 5 项」。
    //    确认卡承诺了后端做不到的事，比直接拒绝糟：用户已经核过一遍数了。
    const val MAX_SPLIT_PARTS: Int = 5
    const val MAX_BATCH_ASSIGN: Int = 10

    /**
     * 一笔收款最多核销多少张订单。
     *
     * 与批量派单同理：输入是"用户口述的一串"，不设上限就可能在他没意识到数量时
     * 把一张收款单挂到几十张单上（那些单会全被标成已收）。
     */
    const val MAX_RECEIPT_ORDERS: Int = 20

    /**
     * 软删的订单在回收站里保留多少天（与后端 `data_retention` 的清理周期一致）。
     *
     * 为什么写进 UI 文案：用户按下"移入回收站"时最需要知道的就是**能不能找回来**。
     * 数字写在这里而不是页面上，是为了它和卡片上的那句话只有一个来源。
     */
    const val RECYCLE_DAYS: Int = 30

    /** 一次捞多少条自己的消息来"找那几条"（后端这个接口只有 limit，没有关键词过滤）。 */
    const val NOTIFICATION_PROBE: Int = 50

    /**
     * **货主能用的动作**（白名单，只此一处）。
     *
     * 为什么用"白名单"而不是给每个动作标角色：50 个动作里货主只能用 13 个，
     * 逐个标注的话**漏标一个就等于多给他一个权限**，而这一处一眼就能看全、能审计。
     *
     * 这 13 个是照着后端 `ROLE_PERMISSIONS['shipper']` + `shipper.py` 的角色门定的：
     * - `orders.create`（order:create）、`orders.cancel`（order:cancel_shipper）；
     * - 地址/联系人/地点（`require_roles(SHIPPER, DISPATCHER)`，走角色门不是权限点）；
     * - `notifications.read_all`（notification:read）。
     *
     * ⛔ **不在里面的，货主一律不能用**——包括 `ledger.create_entry`：
     * 货主对账本只有 `ledger:read_own`（**只读**），记流水要 LEDGER_EDIT，那是派单员的。
     */
    val SHIPPER_ACTIONS: Set<String> = setOf(
        ORDERS_CREATE,
        ORDERS_CANCEL,
        ADDRESS_CREATE,
        ADDRESS_UPDATE,
        ADDRESS_DELETE,
        ADDRESS_SET_DEFAULT,
        CONTACT_UPSERT,
        CONTACT_UPDATE,
        CONTACT_DELETE,
        LOCATION_CREATE,
        LOCATION_UPDATE,
        LOCATION_DELETE,
        // 地点分组（2026-09-19）：它是**按人分区**的 —— 货主管的是自己地址库左栏那一列，
        // 与「地点增删改」是同一件事的另一半（新建地点时要选归到哪一组）。
        // 商品分类则**不在这里**：那是全店一份（派单员维护、所有人下单看到同一列）。
        PLACE_CATEGORY_CREATE,
        PLACE_CATEGORY_UPDATE,
        PLACE_CATEGORY_DELETE,
        PLACE_CATEGORY_REORDER,
        NOTIFICATIONS_READ_ALL,
        // 消息：**只看得到自己那些**（后端 `batch-delete` / `{id}/read` 都是"仅登录 + 只动自己的"，
        // 动别人的直接 404）。手机上消息页三端共用 —— 单条已读、删除、清空货主都能点，
        // 所以助手也要能做（用户 2026-09-20：「他手机做不到的事情，助手也做不到」，
        // 反过来同样成立：手机能做到的，助手也要能做）。
        NOTIFICATIONS_MARK_READ,
        NOTIFICATIONS_DELETE,
        // 自己那张单：**移入回收站**（软删，与订单详情页那个「删除订单」按钮同一条路）。
        // ⚠️ 只放**终态**（已送达/已撤销）—— 判据在 `SoftDeleteOrderHandler` 里，
        //    与 `OrderStatusModel.SHIPPER_DELETABLE` / 后端 `delete_cancelled_order` 三处同源。
        // ⚠️ 恢复**不给**货主：`POST /orders/{id}/restore` 是「体内仅允许：派单员」，
        //    货主端连回收站都没有 —— 卡上会如实写"要请派单员恢复"。
        ORDERS_SOFT_DELETE,
        // 软删之后的**恢复**（撤回路径专用 `undoOnly`，模型看不到）。
        // ⚠️ 这三条原来漏在白名单外，后果很具体：`allows()` 是 preview 与**撤回**
        //    两条路共用的门 —— 货主删掉一条地址之后，点自己那张卡上的「撤回」
        //    会被自己的权限门挡掉，而记录就躺在回收站里（用户 2026-09-19 定的硬规矩：
        //    "所有删除一律软删 + **必须有恢复路径**"）。
        ADDRESS_RESTORE,
        CONTACT_RESTORE,
        LOCATION_RESTORE,
        // 货主自己那一本账（2026-09-20 用户要求：「他的助手也要具备这些功能 ——
        // 帮他核销、帮他管理账本、还有帮他撤回核销」）。
        // ⚠️ 三条都要在这里：`allows()` 是 preview 与 execute **两条路共用的门**，
        //    漏掉后两条的话撤回按钮点下去会被自己的权限门挡掉。
        // ⚠️ 它们同时标了 `memberOnly = true`（**只有批发商货主**）：
        //    普通货主手机上没有这一段，所以他的 AI 连清单里都不该有（见 [AiWriteAction.memberOnly]）。
        MY_LEDGER_SETTLE,
        MY_LEDGER_REVOKE,
        MY_LEDGER_RESTORE,
        // 退货申请（2026-09-21 用户要求：「同时**货主的 AI 可以代替货主进行申请退货**」）。
        // ⚠️ **两条都要**：`apply` 是他要的能力，`withdraw` 是"提错了怎么办"的答案 ——
        //    数量是锁死的，所以"改数量"的唯一路径就是撤回重提；
        //    只给 apply 会让货主提错之后彻底没有退路（手机上有撤回按钮，助手却没有）。
        // ⛔ 派单员那两条（reject / fulfill）**不进这里**：货主点它们是必然失败，
        //    而"能看见但用不了"是本仓库明确列出的最坏一类 bug。
        RETURN_REQUEST_APPLY,
        RETURN_REQUEST_WITHDRAW,
    )

    /**
     * 这个角色（+ 是不是批发商货主）能用哪些动作。**默认只给派单员**（fail-closed）。
     *
     * 三条过滤，缺一条就是一类"能看见但一定失败"的卡：
     * 1. [AiWriteAction.roles] 非空的动作只给它点名的角色（退货申请那种"两个角色各有一半"的域）；
     * 2. 货主走 [SHIPPER_ACTIONS] 白名单（新加的动作不进白名单 = 货主拿不到）；
     * 3. `memberOnly` 的动作只给**批发商货主**，派单员与普通货主都拿不到
     *    （派单员拿不到是因为那本账后端只认货主角色）。
     */
    fun forRole(actor: AiActor?): List<AiWriteAction> {
        val role = actor?.role ?: return emptyList()
        val member = actor.memberShipper
        return when (role) {
            AiRole.DISPATCHER -> ALL.filter {
                (it.roles == null || role in it.roles) && !it.memberOnly
            }
            AiRole.SHIPPER -> ALL.filter {
                (it.roles == null || role in it.roles) &&
                    it.id in SHIPPER_ACTIONS && (!it.memberOnly || member)
            }
        }
    }

    fun allows(actor: AiActor?, id: String): Boolean = forRole(actor).any { it.id == id }

    /**
     * **模型**能看到/能调的动作（= [forRole] 去掉 `undoOnly` 那些）。
     *
     * 为什么要单独一个函数，而不是在 `forRole` 里直接过滤掉：
     * 撤回路径也要过权限门（[allows]），而它调的正是 `undoOnly` 那些动作。
     * 两个用途对"哪些动作算数"的答案不一样，所以必须是两个函数——
     * 合成一个的话，要么撤回被自己的权限门挡掉，要么恢复动作漏进模型清单。
     */
    fun forModel(actor: AiActor?): List<AiWriteAction> = forRole(actor).filter { !it.undoOnly }

    fun byId(id: String): AiWriteAction? = ALL.firstOrNull { it.id == id }

    fun titleOf(id: String): String = byId(id)?.title ?: id

    // ==================================================== 撤回（v3.27：统一模块）

    /**
     * 「误操作了怎么办」**全部由 [AiRevert] 回答**，这里只是转个手。
     *
     * ### 为什么不再把清单留在这一层
     * v3.26 时这里有一张 `UNDO_NONE` 表、一个 `CREATE_LIKE` 兜底、一个手写的
     * `UNDO_CAPABLE` 集合，而"能撤回"的实现在另外三个文件里（声明式规格的 `undoAction`、
     * 两个手写处理器的 `prepareUndo`）。**清单和实现散在四处**，多一个动作就要四处都记得改。
     * 现在撤回只有一个地方（[AiRevert] + [AiResources]）：一张"资源 → 动作"的表，
     * 加上每条真正撤不回来的理由。
     *
     * 保留这三个名字（而不是让调用方直接找 [AiRevert]）是因为它们的调用点很固定：
     * 卡片渲染（[undoLineOf]）、红线检查与设置页（[UNDO_CAPABLE]/[undoNoneOf]）。
     */

    /** 这个动作撤不回来时的理由；null = 它有撤回实现（或压根不需要撤）。 */
    fun undoNoneOf(id: String): String? = AiRevert.blockedReason(id)

    /** 这个动作能不能一键撤回（卡片最后一行按它写）。 */
    fun undoCapableOf(id: String): Boolean = AiRevert.canRevert(id)

    /** 卡片最后一行：「这一步误操作了怎么办」。 */
    fun undoLineOf(id: String): String? = AiRevert.cardLine(id)

    /**
     * **批量卡**的最后一行（`AiWriteBatch.kt` 的卡专用）。
     *
     * 为什么不能沿用 [undoLineOf]：那一行会印「执行后会出现一个「撤回」按钮」，
     * 而批量不挂撤回 —— 一批 N 条要 N 份"改前长什么样"的快照，一张卡上放不下。
     * 照抄的后果是**卡片答应了一件做不到的事**（用户点完确认去找那个按钮）。
     *
     * ⚠️ 这句是给用户看的（Done 消息与卡片都直接渲染成 Text，不走 Markdown），
     *    所以不带星号、不换行。红线 `_check_ai_guardrails.py` 有判据钉着它。
     */
    const val BATCH_UNDO_NOTE: String =
        "⚠️ 这一批是一次改多条，不提供一键「撤回」。要退回去就跟我说，我按上面列的每一条逐条改回来。"

    /** 全部能一键撤回的动作 id（红线、文档、设置页都看这一份）。 */
    val UNDO_CAPABLE: Set<String> get() = AiRevert.CAPABLE

    /** 全部动作 id（给红线检查与设置页看）。 */
    val ids: List<String> get() = ALL.map { it.id }

    /** 允许**自动执行**（不经用户确认）的动作。**红线检查断言它只含 LOW 档。** */
    val autoExecutable: List<String> get() = ALL.filter { it.risk == AiWriteRisk.AUTO_EXECUTABLE }.map { it.id }

    /**
     * 渲染成"给模型看的动作清单"，直接拼进 `preview_write` 的 description。
     *
     * 格式刻意做成一行一个动作 + 参数键名写全：模型的错误几乎都出在**参数键名拼错**
     * （写 `date` 而实际要 `exp_date`），把键名摆在它眼前比在 schema 里绕一圈更有效。
     *
     * **按域分组**：动作到 10 个以上时，一长条平铺的清单会让模型选错域
     * （把"派单"的参数填进"账本"里）。分组之后它至少先落在正确的域上。
     *
     * ⚠️ 必须用 `forModel`（2026-09-19 审计）：这段文本是**贴给模型看的**，而 `forRole` 里
     *    还包含 8 个 `undoOnly` 的"撤回专用恢复动作"。原来这里用的是 `forRole`，于是
     *    `preview_write` 的说明里逐条印着 `products.restore（…）：撤回路径专用，模型看不到它`，
     *    而同一个参数的 `enum` 用的是 `forModel`（不含它们）—— 说明与 enum **自相矛盾**。
     *    模型照说明"原样照抄"一个 restore → `AiWrites.allows`（用 forRole）放行 →
     *    处理器拿 `target_id` 去匹配一个写死为空的名册 → 报「系统里没有匹配「12」的商品」。
     *    用户真实存在的需求（从回收站恢复）就这样被答成"没这条记录"。
     */
    fun describeForModel(actor: AiActor? = AiActor.byRole(AiRole.DISPATCHER)): String =
        forModel(actor).groupBy { it.group }.entries.joinToString("\n") { (group, actions) ->
            "【$group】\n" + actions.joinToString("\n") { a ->
                buildString {
                    append("- ").append(a.id).append("（").append(a.title).append("）：").append(a.blurb)
                    if (a.params.isNotEmpty()) {
                        append("\n  参数：")
                        append(
                            a.params.joinToString("，") { p ->
                                val flag = if (p.required) "必填" else "可选"
                                val en = if (p.enumValues.isEmpty()) "" else "，取值 ${p.enumValues.joinToString("/")}"
                                "${p.name}=${p.cn}（$flag，${p.kind.cn}$en）"
                            },
                        )
                    }
                }
            }
        }

    /** 全部域标签（文档/设置页按它分组）。 */
    val groups: List<String> get() = ALL.map { it.group }.distinct()

    /** 模型可传的动作 id 列表，用于在描述里给出精确的 enum。 */
    val idList: List<String> get() = ids
}
