package com.tapmoay.sorders.ui.ai

import androidx.compose.runtime.*

import com.tapmoay.sorders.ai.AiEndpointRules
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.ai.AiContainer
import com.tapmoay.sorders.ai.AiContext
import com.tapmoay.sorders.ai.AiKeyStore
import com.tapmoay.sorders.ai.AiMemories
import com.tapmoay.sorders.ai.AiMemoryItem
import com.tapmoay.sorders.ai.AiProvider
import com.tapmoay.sorders.ai.AiProviders
import com.tapmoay.sorders.ai.AiReadCatalog
import com.tapmoay.sorders.ai.AiReads
import com.tapmoay.sorders.ai.AiTools
import com.tapmoay.sorders.ai.ChatMessage
import com.tapmoay.sorders.ai.ChatResult
import com.tapmoay.sorders.ai.LlmClient
import com.tapmoay.sorders.ai.LlmConfig
import com.tapmoay.sorders.ai.ModelListResult
import com.tapmoay.sorders.ai.ThinkingLevel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** 设置页里的一个工具开关。 */
data class AiToolToggle(
    val name: String,
    val title: String,
    val hint: String,
    val enabled: Boolean,
    /**
     * 查询类 / 操作类（见 [AiTools.Group]）。
     *
     * 为什么设置页要按它分栏：`preview_write` 一上，同一列开关里就同时躺着"只看"和"会改"两类。
     * 混排的话，用户扫一眼**根本分不出哪个会动数据**——而这一栏恰恰是他最需要一眼看明白的地方。
     */
    val group: AiTools.Group = AiTools.Group.QUERY,
)

/** 设置页里的一个「可读模块」开关（`read_data` 工具的二级开关）。 */
data class AiReadModuleToggle(
    val module: String,
    val title: String,
    val hint: String,
    val enabled: Boolean,
)

/**
 * AI 助手设置页的状态。写法照抄项目现有 VM（`mutableStateOf` + viewModelScope，无 Hilt）。
 *
 * 不在这里做 temperature：保持简单，[com.tapmoay.sorders.ai.LlmClient] 固定 0（要的是可复现，不是创意）。
 */
class AiSettingsViewModel(private val ai: AiContainer) : ViewModel() {

    // ---- 表单草稿 ----
    var baseUrl by mutableStateOf(AiKeyStore.DEFAULT_BASE_URL)
    var model by mutableStateOf(AiKeyStore.DEFAULT_MODEL)

    /**
     * 思考强度：关 / 低 / 中 / 高（见 [ThinkingLevel]）。
     * 默认值与取舍理由见 [AiKeyStore.DEFAULT_THINKING_LEVEL]；老版本的布尔开关会在读取时自动迁移。
     */
    var thinkingLevel by mutableStateOf(AiKeyStore.DEFAULT_THINKING_LEVEL)

    /**
     * 上下文窗口（token）。**只读**：由 [AiKeyStore.windowFor] 按模型算出，
     * 到 [AiContext.COMPACT_AT]（40%）自动压缩。界面上不给用户选（见 [relearnWindow]）。
     */
    var contextWindow by mutableStateOf(AiContext.FALLBACK_WINDOW)
        private set

    /** 明文只在内存里；落盘时走 Keystore 加密。UI 默认掩码显示。 */
    var apiKeyInput by mutableStateOf("")

    /** 是否允许「按你的使用习惯优化回答」（本机统计，默认开）。 */
    var habitEnabled by mutableStateOf(true)
        private set

    /** 已学到的习惯的人话摘要（设置页展示"它到底学了什么"）。 */
    var habitSummary by mutableStateOf<String?>(null)
        private set

    /** ⚠️ 不能叫 setHabitEnabled —— Kotlin 会为 `var habitEnabled` 生成同名 setter，JVM 签名冲突。 */
    fun updateHabitEnabled(on: Boolean) {
        ai.habits.setEnabled(on)
        habitEnabled = on
        habitSummary = habitSummaryText()
    }

    /** 清除已学到的习惯（用户随时可以反悔）。 */
    fun clearHabits() {
        ai.habits.clear()
        habitSummary = habitSummaryText()
        actionResult = "已清除使用习惯记录"
    }

    /**
     * 把学到的习惯摊开给用户看。
     *
     * 为什么一定要显示：这是一个**会改变模型默认行为**的功能，
     * 用户有权知道"它到底记住我什么"。只给一个开关不给内容，等于让他闭眼授权。
     */
    private fun habitSummaryText(): String? {
        val h = ai.habits.load()
        if (h.runs <= 0) return "还没有记录（问过几次之后才会开始统计）。"
        val tools = h.toolCounts.entries.sortedByDescending { it.value }.take(3)
            .joinToString("、") { "${AiTools.titleOf(it.key)} ${it.value} 次" }
        val period = h.periodCounts.entries.maxByOrNull { it.value }?.let { "最常用时间范围：${it.key}" }
        return buildString {
            append("已记录 ${h.runs} 次对话")
            if (tools.isNotEmpty()) append("；常用查询：").append(tools)
            if (period != null) append("；").append(period)
            append("。全部只存在这台手机上。")
        }
    }

    /** 是否明文显示 API Key。 */
    var showKey by mutableStateOf(false)

    /**
     * 当前 Base URL 是否**已知不接受「思考模式」参数**（豆包/千问等第三方兼容端点常见）。
     * 为 true 时界面要解释清楚"已自动跳过它"，否则用户会以为开关坏了。
     */
    var thinkingUnsupported by mutableStateOf(false)
        private set

    /** 当前地址命中的厂商预设（null = 自定义地址）。 */
    fun currentProvider(): AiProvider? = AiProviders.match(baseUrl)

    /**
     * 当前模型的窗口是不是**实测**出来的（撞过超长后自动调小并记住）。
     *
     * 界面据此说清"这个数是怎么来的"：猜的和实测的是两件事，
     * 用户看不到用量数字，至少要知道这个数靠不靠得住。
     */
    var learnedWindow by mutableStateOf(false)
        private set

    /** 用户手改 Base URL：顺带刷新能力状态（改到另一个厂商，结论可能完全不同）。 */
    fun onBaseUrlChange(v: String) {
        baseUrl = v
        thinkingUnsupported = ai.keyStore.thinkingUnsupported(v)
    }

    /**
     * 点一个厂商预设。
     *
     * **刻意把模型名清空并立刻去拉候选**：换厂商后原来那个模型名一定不可用，
     * 留着它用户点保存就会 400，而且会以为是 App 的问题。
     * 不猜模型名是刻意的——猜错了比空着更糟（空着至少会提示"请填写模型名"）。
     */
    fun applyPreset(p: AiProvider) {
        baseUrl = p.baseUrl
        model = ""
        availableModels = emptyList()
        thinkingUnsupported = ai.keyStore.thinkingUnsupported(p.baseUrl)
        fetchModels()
    }

    /** 重新检测能力：清掉记忆，下次提问时重新探一次（换地址后想恢复思考模式时用）。 */
    fun recheckThinkingSupport() {
        ai.keyStore.clearThinkingUnsupported(baseUrl)
        thinkingUnsupported = false
        actionResult = "已清除该地址的能力记忆，下次提问会重新检测"
    }

    /**
     * 忘掉这个模型「实际装不下」的实测结论，回到按模型名推断。
     *
     * 为什么需要一个按钮而不是全靠自动：换到同名但更长窗口的新模型时，
     * 上次学到的偏小值会一直压着它。给一个一键回到"按名字重新估"的出口，
     * 但**不给用户填数字**——用户口径是不要让他选，不是不要让他修。
     */
    fun relearnWindow() {
        val m = model.trim().ifEmpty { ai.currentConfig().model }
        ai.keyStore.forgetWindow(m)
        contextWindow = ai.keyStore.windowFor(m)
        learnedWindow = ai.keyStore.learnedWindow(m) != null
        actionResult = "已按模型名重新识别上下文大小（${AiContext.windowLabel(contextWindow)}）"
    }

    // ---- 状态 ----
    var hasStoredKey by mutableStateOf(false)
    var testing by mutableStateOf(false)
    var testMessage by mutableStateOf<String?>(null)
    var testOk by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var actionResult by mutableStateOf<String?>(null)
    var showClearConfirm by mutableStateOf(false)

    // ---- 「拉取模型列表」状态（拉取失败只是这个便利功能不可用，模型名照样能手输）----
    /** 从 `GET {baseUrl}/models` 拿到的候选模型名；空 = 还没有可用候选。 */
    var availableModels by mutableStateOf<List<String>>(emptyList())
    var fetchingModels by mutableStateOf(false)

    /** 拉取失败的人话提示（由 [LlmClient.listModels] 给出，已含「可手动输入」的退路）。 */
    var modelsError by mutableStateOf<String?>(null)

    val tools = mutableStateListOf<AiToolToggle>()

    /**
     * 通用读工具允许的模块（`read_data` 能查哪些模块的列表）。
     *
     * ⚠️ **必须声明在 `init { load() }` 之前**：Kotlin 的属性初始化与 init 块按**书写顺序**执行，
     * 写在 init 之后的话 `load()` 里会读到还没初始化的 `readModules`（null）→
     * `clear()` 直接 NPE 崩在打开设置页的那一刻（真机实测踩过，见 §16.4）。
     */
    val readModules = mutableStateListOf<AiReadModuleToggle>()

    // ---------------------------------------------------- 长期记忆
    // ⚠️ 这几个同样必须声明在 `init { load() }` **之前**——理由见上面 readModules 的注释。

    /** 长期记忆总开关（默认开）。 */
    var memoryEnabled by mutableStateOf(true)
        private set

    /**
     * 用户教给助手的事实，**逐条摊开在设置页上**。
     *
     * 这不是"顺便展示一下"：它是一个**会改变模型默认行为**的功能，
     * 用户必须能看见它记住了什么、能改、能删。只给一个总开关不给内容，
     * 等于让他闭眼授权——这条纪律与使用习惯那一块完全一致（见 [habitSummaryText]）。
     */
    val memories = mutableStateListOf<AiMemoryItem>()

    /** 正在编辑的那条（null = 没有在编辑）。 */
    var editingMemoryId by mutableStateOf<String?>(null)
        private set

    /** 编辑框里的内容。 */
    var editingFact by mutableStateOf("")
        private set

    /**
     * 「允许 AI 查看成本与毛利」（**默认关**）。
     *
     * 成本价一旦进模型上下文，它就出现在聊天记录里、可能被截图外发 ——
     * 所以这是用户的**数据外发决定**，升级不替他做。
     * 打开之后 AI 才能读成本/毛利、查成本价历史、改成本价、记进货价。
     *
     * ⚠️ **必须声明在 `init { load() }` 之前**（理由见上面 `readModules` 的注释）：
     *    这条是 2026-09-20 真机验证时**崩出来的**——`load()` 里要写 `costVisible`，
     *    而它当时写在本文件后半段（init 之后）→ 委托字段还是 null →
     *    `MutableState.setValue on a null object reference`，
     *    **打开「AI 助手 → 设置」必崩**（连聊天页那个齿轮都进不去，
     *    于是"打开 AI 写能力"这条路整条被堵死）。同一个坑这个文件里已经踩过两次。
     */
    var costVisible by mutableStateOf(false)

    init {
        load()
    }

    fun load() {
        val cfg = ai.currentConfig()
        baseUrl = cfg.baseUrl
        model = cfg.model
        thinkingLevel = cfg.thinkingLevel
        contextWindow = cfg.contextWindow
        learnedWindow = ai.keyStore.learnedWindow(cfg.model) != null
        thinkingUnsupported = ai.keyStore.thinkingUnsupported(cfg.baseUrl)
        habitEnabled = ai.habits.enabled()
        habitSummary = habitSummaryText()
        memoryEnabled = ai.keyStore.memoryEnabled()
        costVisible = ai.keyStore.costVisible()
        loadMemories()
        apiKeyInput = ai.keyStore.apiKey().orEmpty()
        hasStoredKey = apiKeyInput.isNotBlank()
        // 默认值按角色给（派单员全开）——设置页必须与 `AiContainer.tools` 用**同一个判据**，
        // 否则会出现"开关显示关着、其实能用"（或反过来）。
        val enabled = ai.keyStore.enabledTools(ai.currentRole)
        tools.clear()
        // 按角色裁：货主不该看到"库存预警/司机跑车统计"这种他永远用不上的开关
        // （打开了也不生效 = "看起来有、其实没有"）。
        AiTools.settingsItems(ai.currentRole).forEach { t ->
            tools.add(AiToolToggle(t.name, t.title, t.hint, t.name in enabled, t.group))
        }
        loadReadModules()
    }

    // ---------------------------------------------------- 长期记忆的操作

    /** 读盘（阻塞 IO → 放 IO 线程；读失败就是空列表，不让设置页崩）。 */
    private fun loadMemories() {
        viewModelScope.launch {
            val items = withContext(Dispatchers.IO) { ai.memories.load() }
            memories.clear()
            memories.addAll(items)
        }
    }

    /** 开/关长期记忆。关掉后既不注入、也不允许 `remember` 写进去。 */
    fun updateMemoryEnabled(on: Boolean) {
        ai.keyStore.setMemoryEnabled(on)
        memoryEnabled = on
    }

    fun updateCostVisible(on: Boolean) {
        ai.keyStore.setCostVisible(on)
        costVisible = on
    }

    /** 清空全部记忆前的二次确认（与清除 API Key 同一套：危险操作必须确认）。 */
    var showClearMemoriesConfirm by mutableStateOf(false)

    fun askClearMemories() {
        showClearMemoriesConfirm = true
    }

    fun confirmClearMemories() {
        showClearMemoriesConfirm = false
        clearMemories()
    }

    fun beginEditMemory(item: AiMemoryItem) {
        editingMemoryId = item.id
        editingFact = item.fact
    }

    fun cancelEditMemory() {
        editingMemoryId = null
        editingFact = ""
    }

    fun onEditingFactChange(v: String) {
        editingFact = v
    }

    /** 保存对某条记忆的修改。 */
    fun saveEditedMemory() {
        val id = editingMemoryId ?: return
        val fact = editingFact.trim()
        if (fact.isEmpty()) {
            actionResult = "内容不能为空"
            return
        }
        viewModelScope.launch {
            val ok = withContext(Dispatchers.IO) {
                val next = AiMemories.updateFact(ai.memories.load(), id, fact)
                ai.memories.save(next)
            }
            cancelEditMemory()
            loadMemories()
            actionResult = if (ok) "已修改" else "修改没能存下来"
        }
    }

    /** 删掉一条。 */
    fun deleteMemory(id: String) {
        viewModelScope.launch {
            val ok = withContext(Dispatchers.IO) {
                val next = AiMemories.remove(ai.memories.load(), id)
                ai.memories.save(next)
            }
            if (editingMemoryId == id) cancelEditMemory()
            loadMemories()
            actionResult = if (ok) "已删除" else "删除没能存下来"
        }
    }

    /** 清空全部记忆（用户随时可以反悔）。 */
    fun clearMemories() {
        viewModelScope.launch {
            val ok = withContext(Dispatchers.IO) { ai.memories.clear() }
            cancelEditMemory()
            loadMemories()
            actionResult = if (ok) "已清空全部记忆" else "清空没能完成"
        }
    }

    /**
     * 拉取可用模型列表（`GET {baseUrl}/models`）。
     *
     * 用**当前填在输入框里的** Base URL + API Key（不是已保存的那份）——
     * 用户往往是「先填地址和 key，再点拉列表，选好模型名，最后才保存」，顺序反了就得来回跑两趟。
     *
     * 全程不抛异常：失败只在 [modelsError] 里给人话提示，**不清空用户已填的模型名、不崩溃**。
     * 成功后把候选填进 [availableModels] 供页面点选。
     */
    fun fetchModels() {
        val url = baseUrl.trim()
        val key = apiKeyInput.trim()
        when {
            AiEndpointRules.error(url) != null -> { modelsError = AiEndpointRules.error(url)!!; return }
            key.isEmpty() -> { modelsError = "请先填写 API Key，再拉取模型列表"; return }
        }
        fetchingModels = true
        modelsError = null
        viewModelScope.launch {
            try {
                when (val r = LlmClient.listModels(url, key)) {
                    is ModelListResult.Success -> {
                        availableModels = r.models
                        modelsError = null
                        // 存一份给聊天页顶栏的模型切换用（那边不该为了换个模型再拉一次）
                        ai.keyStore.saveModelCandidates(r.models)
                    }
                    is ModelListResult.Failure -> {
                        availableModels = emptyList()
                        modelsError = r.userMessage
                    }
                }
            } catch (e: Exception) {
                // listModels 已保证不抛（取消除外）；这里再兜一层，页面绝不能因此卡在「拉取中」
                availableModels = emptyList()
                modelsError = "拉取模型列表出错：" + (e.message ?: e.javaClass.simpleName) +
                    "；可以直接手动输入模型名"
            } finally {
                fetchingModels = false
            }
        }
    }

    /** 点选候选模型：只填进输入框（还要用户自己点保存，避免误触改配置）。 */
    fun pickModel(name: String) {
        model = name.trim()
        // 顺手把"这个模型该用多大上下文"也算出来显示，用户才知道换模型意味着什么
        val m = model
        if (m.isNotEmpty()) {
            contextWindow = ai.keyStore.windowFor(m)
            learnedWindow = ai.keyStore.learnedWindow(m) != null
        }
    }

    /** 收起候选列表（把「拉取结果」这块 UI 关掉，但不清 modelsError，用户重试时还能看到）。 */
    fun clearModelCandidates() {
        availableModels = emptyList()
    }

    fun toggleTool(name: String, on: Boolean) {
        val i = tools.indexOfFirst { it.name == name }
        if (i < 0) return
        tools[i] = tools[i].copy(enabled = on)
        ai.keyStore.saveEnabledTools(tools.filter { it.enabled }.map { it.name }.toSet())
    }

    /** 通用读工具允许的模块（`read_data` 能查哪些模块的列表）。 */
    fun toggleReadModule(module: String, on: Boolean) {
        val i = readModules.indexOfFirst { it.module == module }
        if (i < 0) return
        readModules[i] = readModules[i].copy(enabled = on)
        ai.keyStore.saveEnabledReadModules(readModules.filter { it.enabled }.map { it.module }.toSet())
    }

    private fun loadReadModules() {
        val on = ai.keyStore.enabledReadModules()
        readModules.clear()
        // ⚠️ 只列**这个角色真能读的**模块（v3.34e 修的一处角色缺口）。
        //    原来遍历的是 `AiReadCatalog.modules()` —— 全表 21 个，不看角色。
        //    后果：货主打开设置页会看到「库存管理」「账号」「操作日志」这些他根本读不到的开关，
        //    拨过去**不会报错、也没有效果**（读侧的门在 `AiReads.allows`），
        //    等于界面替他承诺了一个做不到的能力——用户试一次就不知道该信哪一个了。
        //    同一页的工具开关一直是按角色裁的（`AiTools.settingsItems(ai.currentRole)`），
        //    只有这一块漏了；`AiRolePrompt.settingsSummary` 又是裁过的，所以顶上的能力摘要
        //    和下面的列表会对不上（摘要说 12 类、列表列 21 个）。
        val mine = AiReads.forRole(ai.currentRole, AiReadCatalog.modules().toSet())
            .map { it.action.substringBefore('.') }
            .toSet()
        AiReadCatalog.modules().filter { it in mine }.forEach { m ->
            // 说明用「这个模块下有哪些表」，比写一句笼统的话有用得多
            val hint = AiReadCatalog.actionsOf(m).joinToString("；") { it.cn.substringBefore("（") }
            readModules.add(
                AiReadModuleToggle(
                    module = m,
                    title = AiReadCatalog.MODULE_CN[m] ?: m,
                    hint = hint,
                    enabled = m in on,
                ),
            )
        }
    }

    /**
     * 校验草稿并落盘。key 走 Keystore 加密，config 存 URL + 模型名 + 思考开关。
     *
     * ⚠️ thinking 必须一起存：它不在 key 里、也不在 URL 里，漏存 = 用户下次打开 App
     * 开关自己弹回默认值（最典型的是「昨晚关了省钱，今早又变回开」）。
     */
    fun save() {
        error = null
        val url = baseUrl.trim()
        val m = model.trim()
        when {
            AiEndpointRules.error(url) != null -> { error = AiEndpointRules.error(url)!!; return }
            m.isEmpty() -> { error = "请填写模型名，例如 " + AiKeyStore.DEFAULT_MODEL; return }
        }
        ai.keyStore.saveConfig(LlmConfig(url, "", m, thinkingLevel, ai.keyStore.windowFor(m)))

        val key = apiKeyInput.trim()
        if (key.isEmpty()) {
            // 用户把 key 清空了 → 等同于清除（不再保留旧 key）
            ai.keyStore.clearApiKey()
            hasStoredKey = false
            actionResult = "已保存（未设置 API Key，AI 还不能用）"
            return
        }
        if (!ai.keyStore.saveApiKey(key)) {
            error = "系统加密存储不可用，API Key 未保存（请检查系统 Keystore 是否正常）"
            return
        }
        hasStoredKey = true
        actionResult = "已保存"
    }

    /**
     * 测试连接：发一句最短的「你好」。
     * **必须能区分「key 错」和「网络不通」**——这两类错误直接展示 [ChatResult.Failure.userMessage]，
     * LlmClient 已经把它们翻译成人话了（401=key 无效、超时/连接失败=网络问题）。
     *
     * 顺带验证思考开关：按用户**当前**开关状态发一次，并对照响应里有没有 `reasoning_content`——
     * 「开了却没思考内容」「关了却还有思考内容」都会在结果里点出来（实测有端点会静默忽略该参数，
     * 不点破的话用户只会觉得「开关没用」）。
     */
    fun testConnection() {
        val url = baseUrl.trim()
        val m = model.trim()
        val key = apiKeyInput.trim()
        when {
            AiEndpointRules.error(url) != null ->
                { testOk = false; testMessage = AiEndpointRules.error(url)!!; return }
            m.isEmpty() -> { testOk = false; testMessage = "请先填写模型名"; return }
            key.isEmpty() -> { testOk = false; testMessage = "请先填写 API Key"; return }
        }
        testing = true
        testMessage = null
        viewModelScope.launch {
            try {
                // 不带工具：只验证 key/地址/模型名是否可用，最小化 token 消耗
                val r = ai.llmClient.complete(
                    LlmConfig(url, key, m, thinkingLevel, ai.keyStore.windowFor(m)),
                    listOf(ChatMessage.user("你好")),
                    emptyList(),
                )
                when (r) {
                    is ChatResult.Success -> {
                        testOk = true
                        val reply = r.message.content.orEmpty().replace('\n', ' ').trim().take(40)
                        val reasoning = r.message.reasoningContent.orEmpty().trim()
                        val thinkNote = when {
                            thinkingLevel.enabled && reasoning.isNotEmpty() -> "（思考已开启，模型确实返回了思考内容）"
                            thinkingLevel.enabled -> "（注意：没收到思考内容，该模型可能不支持思考开关）"
                            reasoning.isNotEmpty() -> "（注意：已关闭思考，但仍返回了思考内容）"
                            else -> ""
                        }
                        testMessage = "连接成功：$m 已回复" +
                            (if (reply.isBlank()) "（无文字内容）" else "「$reply」") + thinkNote
                    }
                    is ChatResult.Failure -> {
                        testOk = false
                        testMessage = r.userMessage +
                            if (r.raw.isNullOrBlank()) "" else "\n技术细节：" + r.raw
                    }
                }
            } catch (e: Exception) {
                testOk = false
                testMessage = "测试出错：" + (e.message ?: e.javaClass.simpleName)
            } finally {
                testing = false
            }
        }
    }

    fun askClearKey() { showClearConfirm = true }

    fun confirmClearKey() {
        ai.keyStore.clearApiKey()
        apiKeyInput = ""
        hasStoredKey = false
        showClearConfirm = false
        testMessage = null
        actionResult = "API Key 已清除"
    }
}
