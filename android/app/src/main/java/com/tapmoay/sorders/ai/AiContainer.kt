package com.tapmoay.sorders.ai

import android.content.Context
import com.tapmoay.sorders.data.repo.AppRepository
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * AI 助手的组装入口（手写 DI，与 [com.tapmoay.sorders.core.AppContainer] 同风格）。
 *
 * ### 为什么单独一个容器、不改 AppContainer
 * `core/AppContainer.kt` 是多人共用的热点文件，往里塞东西容易冲突。
 * 这里只做「把零件拼起来」这一件事，聊天页和设置页都从这里取。
 *
 * ### 依赖方向
 * [AppRepository] **由调用方传进来**（从 AppContainer 拿 `repo`），
 * 本容器**不自己创建** ApiClient / 不自己 new Retrofit —— 保证 AI 工具走的
 * 就是 App 登录态那一套客户端（带 token、带统一的异常转换）。
 *
 * 用法：
 * ```
 * // 在能拿到 AppContainer 的地方（如 MainActivity / NavGraph）
 * val ai = AiContainer(context, container.repo)   // 建议自己缓存成单例，不要每帧新建
 * AiSettingsScreen(ai = ai, onBack = { ... })
 * ```
 */
class AiContainer(
    context: Context,
    private val repo: AppRepository,
    /**
     * 当前登录角色（`dispatcher` / `shipper` / `driver`）。
     *
     * **默认给派单员**是刻意的：万一调用方忘了传，宁可少给能力（货主少了几个动作会立刻
     * 被发现），也不能多给（给货主开了派单权限，不会有人发现）。
     */
    private val roleKey: () -> String? = { "dispatcher" },
    /**
     * 当前登录用户 id。AI 的三份本机数据按它分区（见 [AiScope]）。
     *
     * **读不到就落到 `_anon` 分区，绝不回落到"公共区"**——回落正是那个跨账号串数据的 bug。
     */
    private val userIdKey: () -> Long? = { null },
) {
    private val appContext: Context = context.applicationContext

    /** 解析出来的角色；认不出就当没有（[AiWrites.forRole] 会返回空清单）。 */
    private fun role(): AiRole? = AiRole.fromKey(roleKey())

    /** 当前角色（界面据此调整文案与示例问题；权限门槛在 [writeService] 那一层）。 */
    val currentRole: AiRole? get() = role()

    /** 本机数据的分区后缀（按用户）。 */
    private fun scope(): String = AiScope.suffix(userIdKey())

    /**
     * 三个本机 store **按分区重建**。
     *
     * ⚠️ 为什么不能用 `by lazy`：lazy 会把 store 连同**首次访问时的分区**一起缓存住。
     * 这个容器是 `remember { AiContainer(...) }`（一次会话只建一次），
     * 所以换了账号之后 lazy 仍然返回上一个人的 store——**等于没修**。
     * 实测正是这么踩的：先写成 lazy，写完才发现"换账号还是能看到前面的对话"。
     */
    private var builtScope: String? = null
    private var convStore: AiConversationStore? = null
    private var habitStore: AiHabitStore? = null
    private var memStore: AiMemoryStore? = null

    @Synchronized
    private fun ensureScoped() {
        val s = scope()
        if (builtScope == s && convStore != null) return
        builtScope = s
        convStore = AiConversationStore(appContext, s)
        habitStore = AiHabitStore(appContext, s)
        memStore = AiMemoryStore(appContext, s)
    }

    /** Keystore 加密存储：API Key、Base URL、模型名、工具开关。 */
    val keyStore: AiKeyStore by lazy { AiKeyStore(appContext) }

    /**
     * LLM 直连客户端（独立 OkHttp 实例，无日志拦截器）。
     *
     * 两组能力回调把「这个地址认不认某个自选字段」接到 Keystore 上：
     * 这样豆包/千问这类不认 `thinking` 或 `stream_options` 的端点
     * **第一次自动降级、之后不再多发**（见 [LlmClient.completeStreaming]）。
     * 两组必须都接上：只接一组的话，另一组每次提问都要白打一次注定 400 的请求。
     */
    val llmClient: LlmTransport by lazy {
        LlmClient(
            thinkingUnsupported = { keyStore.thinkingUnsupported(it) },
            onThinkingUnsupported = { keyStore.markThinkingUnsupported(it) },
            streamOptionsUnsupported = { keyStore.streamOptionsUnsupported(it) },
            onStreamOptionsUnsupported = { keyStore.markStreamOptionsUnsupported(it) },
        )
    }

    /**
     * 待确认的写操作（内存暂存区）。
     *
     * 聊天页和 [writeService] 看的必须是**同一个**：聊天页从它读卡片、点确认时把 token
     * 交给 `writeService.execute`，而 `execute` 会把它 take 走（一次性）。
     * 两边各持一个实例的话，"确认"永远找不到那张卡。
     */
    val writes: AiWritePreviewStore by lazy { AiWritePreviewStore() }

    /**
     * 附件装载：把用户从手机里选的表格传上去读成文本（AI 助手的「挂载文件」）。
     *
     * 它的位置在容器里（而不是聊天页里）是为了**只有一处知道怎么读用户的文件**——
     * 服务端不保存文件、扩展名白名单、行数上限这些都只在这里和后端两处对齐。
     */
    val attachmentService: AiAttachmentService by lazy { AiAttachmentService(repo) }

    /**
     * 写操作执行器：校验 → 名字换编号 → 造确认卡 → （用户确认后）落库。
     * 唯一能真正写业务数据的地方，入口只有两个：模型的 `preview_write`（只申请）与
     * 聊天页的确认按钮（真执行）。
     */
    val writeService: AiWriteService by lazy {
        AiWriteService(
            // appContext 是给**高德地理编码**用的：AI 建的地址/地点/订单要自己换坐标，
            // 否则司机端的「高德导航」只会打开高德首页（详见 AiGeocode）。
            RepoWriteDataSource(repo, selfId = { userIdKey() }, context = appContext),
            writes,
            roleProvider = { role() },
        )
    }

    /** 6 个只读工具 + 2 个操作工具（记住 / 改数据）；两层开关都实时读 Keystore，设置页一改立刻生效。 */
    val tools: AiToolset by lazy {
        AiTools(
            repo = repo,
            enabledNames = { keyStore.enabledTools() },
            readModules = { keyStore.enabledReadModules() },
            rememberFact = { subject, fact -> rememberFact(subject, fact) },
            roleProvider = { role() },
            requestWrite = { actionId, params -> writeService.preview(actionId, params) },
        )
    }

    /** agent 循环：配置每次 run 时现读，保证用户改完 key 不用重启 App。 */
    val agentLoop: AiAgentLoop by lazy {
        AiAgentLoop(
            transport = llmClient,
            tools = tools,
            configProvider = { keyStore.config() ?: keyStore.defaultConfig() },
        )
    }

    /**
     * 对话历史（本地私有目录的 JSON 文件）。
     * 「翻历史 / 复制全文 / 从某句分叉」三件事全靠它——所以它必须是**跨页面、跨会话**的单例，
     * 不能在聊天页里 new（否则切走再回来就是一份空历史）。
     */
    val conversations: AiConversationStore get() { ensureScoped(); return convStore!! }

    /** 使用习惯（本机统计，含开关）。 */
    val habits: AiHabitStore get() { ensureScoped(); return habitStore!! }

    /**
     * 长期事实记忆（本机文件，逐条可查看/编辑/删除）。
     *
     * 与 [conversations]、[habits] 同一条隐私边界：**只写 App 私有目录，不上传、不跨设备同步**。
     */
    val memories: AiMemoryStore get() { ensureScoped(); return memStore!! }

    /**
     * 挑出与这次提问相关的记忆，拼成要注入提示词的那几行。
     *
     * 关掉开关、或没有相关记忆 → 返回 null（什么都不加）。
     * 读盘放 IO：它是文件 IO，而调用点在 viewModelScope（Main）。
     */
    suspend fun memoryHint(question: String): String? {
        if (!keyStore.memoryEnabled()) return null
        return try {
            val items = withContext(Dispatchers.IO) { memories.load() }
            AiMemories.promptHint(AiMemories.relevant(items, question))
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            null // 记忆读不出来不该挡住提问
        }
    }

    /**
     * 「记住」工具的落点：把一条事实写进本机记忆。
     *
     * @return 给模型和用户看的一句话；**null = 没写成功**（开关关了 / 落盘失败），
     *   由工具层转成 `{"error": …}` 让模型**如实说"没记住"**，而不是假装记住了。
     */
    suspend fun rememberFact(subject: String, fact: String): String? {
        if (!keyStore.memoryEnabled()) return null
        return try {
            val next = withContext(Dispatchers.IO) {
                val merged = AiMemories.upsert(memories.load(), subject, fact)
                if (memories.save(merged)) merged else null
            } ?: return null
            val subjectLabel = if (subject == AiMemories.SUBJECT_GLOBAL) "全局偏好" else subject
            "已记住（$subjectLabel）：$fact。可在「AI 助手设置 → 记忆」里查看或删除——共 ${next.size} 条。"
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            null
        }
    }

    /**
     * 上下文压缩器：到窗口 60% 时把较早的对话压成摘要（见 [AiContext]/[AiCompactor]）。
     * 复用同一个传输层，所以它也会享受"端点不认 thinking 就自动降级"那套。
     */
    val compactor: AiCompactor by lazy { AiCompactor(llmClient) }

    /**
     * 计算当前对话该往 system prompt 里追加什么（使用习惯 + 早前对话摘要）。
     *
     * 单独抽成一个函数而不是塞在 ViewModel 里：它是**纯拼装**，
     * 而"什么情况下才注入"（样本够不够、开关开没开）是需要能单独看清楚的决策。
     */
    /**
     * 计算当前对话该往 system prompt 里追加什么：**早前对话摘要 + 长期记忆 + 使用习惯**。
     *
     * 单独抽成一个函数而不是塞在 ViewModel 里：它是**纯拼装**，
     * 而"什么情况下才注入"（样本够不够、开关开没开、有没有相关记忆）是需要能单独看清楚的决策。
     *
     * ### 顺序不是随意的（越靠前的越"硬"）
     * 1. **摘要**——这次对话早前发生过什么，是事实；
     * 2. **长期记忆**——用户之前教过的事实，也是事实（但可能过期，所以文案里写了"以本次为准"）；
     * 3. **使用习惯**——只是"用户没说清时的默认口径"，最软，所以放最后，
     *    这样它不会盖过上面两层（它的自带约束也写着"只在没说清时用"）。
     */
    fun systemExtra(memoryHint: String?, habitHint: String?, summary: String?): String? {
        val parts = buildList {
            if (!summary.isNullOrBlank()) add(AiCompactor.SUMMARY_TITLE + "\n" + summary.trim())
            if (!memoryHint.isNullOrBlank()) add(memoryHint.trim())
            if (!habitHint.isNullOrBlank()) add(habitHint.trim())
        }
        return parts.takeIf { it.isNotEmpty() }?.joinToString("\n\n")
    }

    /** 当前有效配置（设置页初始化用；没保存过则返回默认值 + 已存的 key）。 */
    fun currentConfig(): LlmConfig = keyStore.config() ?: keyStore.defaultConfig()

    /** AI 功能是否已可用（有 key 才算）。 */
    fun ready(): Boolean = keyStore.hasKey()
}
