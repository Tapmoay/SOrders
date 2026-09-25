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
     * 当前登录用户 id。AI 的**四份**本机数据按它分区（对话/习惯/记忆 + 凭据，见 [AiScope]）。
     *
     * **读不到就落到 `_anon` 分区，绝不回落到"公共区"**——回落正是那个跨账号串数据的 bug。
     */
    private val userIdKey: () -> Long? = { null },
) {
    private val appContext: Context = context.applicationContext

    /** 解析出来的角色；认不出就当没有（[AiWrites.forRole] 会返回空清单）。 */
    private fun role(): AiRole? = AiRole.fromKey(roleKey())

    /**
     * **他是不是批发商货主**（`users.is_member=1`）—— 两个货主 AI 的唯一分叉点。
     *
     * ### 为什么要缓存在容器上（而不是每次现问）
     * [AiWrites.forRole] / [AiReads.forRole] 是**同步**的（工具清单、enum、卡片摘要都在同步代码里
     * 现算），而 `GET /users/me` 是网络调用。所以：容器持有一个可变值，由聊天页在**每次提问前**
     * 调 [refreshMembership] 刷一次。
     *
     * ### 初值与失败都按 `false`（fail-closed）
     * `false` = 按**普通货主**给能力：批发商会少掉"核销/撤销/恢复"三条（他会立刻发现，
     * 说一句"怎么不能核销了"），而反过来多给是**不会有人发现**的（那正是本仓库最怕的一类）。
     * 失败时**保留上一次的值**：一次网络抖动不该把已经确认过的批发商悄悄降级。
     */
    var memberShipper: Boolean = false
        private set

    /**
     * 问一次"我是不是批发商货主"。**只对货主有意义**（派单员/司机不动这个值）。
     *
     * 调用点：聊天页每次提问前（`AiChatViewModel.run`），以及货主打开 AI 页时。
     * 非货主直接返回 —— 免得给派单员也留一个会变的 member 标志（那份清单里根本没有 member 动作）。
     */
    suspend fun refreshMembership() {
        if (role() != AiRole.SHIPPER) return
        memberShipper = try {
            repo.me().isMember
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            memberShipper // 问不到就沿用上一次；首次仍为 false（按普通货主，fail-closed）
        }
    }

    /** 当前角色 + 是不是批发商货主（工具清单/提示词/执行门都按它算，见 [AiActor]）。 */
    val currentActor: AiActor? get() = AiActor.of(role(), memberShipper)

    /**
     * 当前角色（界面据此调整文案与示例问题）。
     *
     * ⚠️ **凡是"算能力清单"的地方都不要用它，用 [currentActor]** ——
     * 只看角色的后果是普通货主也会看到批发商那一组动作（两个货主的手机界面不一样）。
     * 它留着是给"只关心是不是派单员/货主"的文案判断用的（如聊天页的示例问题）。
     */
    val currentRole: AiRole? get() = currentActor?.role

    /** 本机数据的分区后缀（按用户）。 */
    private fun scope(): String = AiScope.suffix(userIdKey())

    /**
     * 四个本机 store **按分区重建**（第四个是凭据，见 [keyStore]）。
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
    private var keyStoreRef: AiKeyStore? = null

    @Synchronized
    private fun ensureScoped() {
        val s = scope()
        if (builtScope == s && convStore != null) return
        builtScope = s
        convStore = AiConversationStore(appContext, s)
        habitStore = AiHabitStore(appContext, s)
        memStore = AiMemoryStore(appContext, s)
        keyStoreRef = AiKeyStore(appContext, s)
    }

    /**
     * Keystore 加密存储：API Key、Base URL、模型名、工具开关。
     *
     * 它**也必须按分区重建**（与另外三个 store 同理，见 [ensureScoped]）：原来这里是
     * lazy 只传 appContext 建的（凭据是四份数据里唯一没分区的），
     * 于是同机换账号后新登录的人读到的还是上一个人的 **明文 LLM Key**（2026-09-19 审计 P0-6）。
     */
    val keyStore: AiKeyStore get() { ensureScoped(); return keyStoreRef!! }

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
            //
            // locationProvider 是给**「当前位置」句柄**用的（2026-09-21）：用户说"送到我现在的位置"时，
            // 模型只写那四个字，真实地址与精确坐标由这一条取一次定位换上（详见 AiLocation）。
            RepoWriteDataSource(
                repo,
                selfId = { userIdKey() },
                context = appContext,
                locationProvider = { locationProvider },
            ),
            writes,
            // ⚠️ 两个 provider 缺一不可：角色决定"能不能"，member 决定"这一本账有没有"
            //    （见 AiActor 的注释：核销那三条只给批发商货主）。
            actorProvider = { currentActor },
            // 成本那两扇门唯一的开关（**按角色给默认值**：派单员默认开，见 `defaultCostVisible`）
            allowCost = { keyStore.costVisible(role()) },
        )
    }

    /**
     * 「手机当前在哪」的**唯一装配点**（AI 读定位 `location.current` ＋ 地址类动作的「当前位置」句柄）。
     *
     * 为什么在容器里建：读能力（`AiTools`/`AiReadService`）与写能力（`RepoWriteDataSource`）
     * 必须是**同一个**提供者 —— 两处各建一个的话，同一次提问里"读到的位置"和"写进去的位置"
     * 可能是两次不同的定位，而界面上完全看不出来（卡片上印的还是读到的那个地址）。
     *
     * `lazy`：它内部的高德客户端按需才建，用户不碰"当前位置"就一个 SDK 客户端都不起。
     */
    private val locationProvider: AiLocationProvider by lazy {
        AiLocation.AmapCurrentLocationProvider(appContext)
    }

    /** 6 个只读工具 + 2 个操作工具（记住 / 改数据）；两层开关都实时读 Keystore，设置页一改立刻生效。 */
    val tools: AiToolset by lazy {
        AiTools(
            repo = repo,
            // ⚠️ 必须把**角色**传进去：默认值是按角色给的（派单员全开，
            //    其余角色除写工具外全开）——见 `AiKeyStore.defaultEnabledTools`。
            enabledNames = { keyStore.enabledTools(role()) },
            readModules = { keyStore.enabledReadModules() },
            allowCostProvider = { keyStore.costVisible(role()) },
            rememberFact = { subject, fact -> rememberFact(subject, fact) },
            roleProvider = { role() },
            // 两维都要传：普通货主与批发商货主的工具说明/enum 不一样（见 AiActor）。
            memberProvider = { memberShipper },
            // 本机能力（`location.current`）：与写侧**同一个**定位提供者，见上面那条注释。
            locationProvider = { locationProvider },
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
    /**
     * 报告 §15 ② 的 `AI_calls`：聊天页跑完一轮之后调它。
     *
     * ⚠️ 次数从 `AiRunResult.steps` 来 —— 那是**循环里真实发生的模型调用次数**
     *    （工具循环一轮可能调多次），比「用户问了几句」准确。
     * ⛔ 只在这一处上报：散在多处会让同一个数被记两遍。
     */
    suspend fun reportAiCalls(calls: Int) {
        repo.reportAiCalls(calls)
    }

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

    /**
     * **测试账号的默认模型服务**：用户自己没配过 key 时，向服务端要一份来用。
     *
     * ### 用户为什么要它（2026-09-21 原话）
     * 「只要是测试账号默认就跑，我们那个 api key」——测试号每次换手机/模拟器/清数据
     * 都要手填一次 key，太麻烦；白名单（`1380000000X`）的账号应当开箱可用。
     *
     * ### 三条规矩（每一条都有它的理由）
     * 1. **只在用户自己没配过 key 时才用**（[AiKeyStore.hasKey] 为 false）：配过就永远用自己的 ——
     *    否则"用户填了 key 却仍然发到公司的账号上"是最坏的一种行为（他的 key 白填、而账单走公司）。
     * 2. **拿不到就当没有**（403 非测试号 / 404 服务端没配 / 网络不通）：静默返回 false，
     *    **不弹错**——这不是用户操作引发的失败，他的 AI 仍然可以在设置页里自己配。
     * 3. **不写日志、不显示 key 本身**：只把"正在用测试账号默认 Key"这个事实告诉界面。
     *
     * @return true = 这一次真的取到并写进去了（调用方据此刷新"已配置"状态）
     */
    suspend fun ensureDefaultKey(): Boolean {
        if (keyStore.hasKey()) return false
        val d = try {
            repo.aiDefault()
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            return false // 403/404/断网都走这里：没有默认可用，不是错误
        }
        val key = d.apiKey.trim()
        if (key.isEmpty()) return false
        if (!keyStore.saveApiKey(key)) return false
        // ⚠️ 顺序不能反：`saveApiKey` 内部会把"默认 key"标记清掉（用户自己保存的语义），
        //    所以这里必须**在它之后**再置 true。
        keyStore.markUsingDefaultKey(true)
        // Base URL / 模型名只在服务端给了非空值时才覆盖（留空 = 沿用 App 自己的缺省，
        // 也就是 `AiKeyStore.DEFAULT_BASE_URL` / `DEFAULT_MODEL`，两边本来就是同一套值）。
        val cfg = currentConfig()
        if (d.baseUrl.isNotBlank() || d.model.isNotBlank()) {
            keyStore.saveConfig(
                cfg.copy(
                    baseUrl = d.baseUrl.ifBlank { cfg.baseUrl },
                    model = d.model.ifBlank { cfg.model },
                ),
            )
        }
        return true
    }
}
