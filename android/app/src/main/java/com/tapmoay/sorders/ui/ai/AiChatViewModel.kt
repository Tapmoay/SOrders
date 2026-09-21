package com.tapmoay.sorders.ui.ai

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.ai.AiAnswerSanitizer
import com.tapmoay.sorders.ai.AiAttachment
import com.tapmoay.sorders.ai.AiAttachmentLoader
import com.tapmoay.sorders.ai.AiContainer
import com.tapmoay.sorders.ai.AiVision
import com.tapmoay.sorders.ai.AiContext
import com.tapmoay.sorders.ai.AiConversations
import com.tapmoay.sorders.ai.AiEvent
import com.tapmoay.sorders.ai.AiHabits
import com.tapmoay.sorders.ai.AiPendingWrite
import com.tapmoay.sorders.ai.AiRunResult
import com.tapmoay.sorders.ai.AiTools
import com.tapmoay.sorders.ai.AiWriteOutcome
import com.tapmoay.sorders.ai.ChatMessage
import com.tapmoay.sorders.ai.LlmConfig
import com.tapmoay.sorders.ai.StoredAttachment
import com.tapmoay.sorders.ai.StoredConversation
import com.tapmoay.sorders.ai.StoredMessage
import com.tapmoay.sorders.ai.ThinkingLevel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/**
 * 对话角色。注意：本包内自有一个 Role，与 `com.tapmoay.sorders.ui.nav.Role`
 * （货主/司机/派单员）同名但无关，两边都不要互相 import。
 */
enum class Role { USER, ASSISTANT }

/** 气泡上那个附件 chip 要显示的东西（文件名 + "200 行 × 5 列" + 后端的实话）。 */
data class AttachmentChip(
    val filename: String,
    val summary: String,
    val warnings: List<String> = emptyList(),
)

/** 聊天页上可见的一条消息（工具痕迹挂在所属助手消息上，不单独成气泡） */
data class UiMessage(
    val role: Role,
    val text: String,
    val toolTrace: List<String> = emptyList(),
    val isError: Boolean = false,
    /** 模型的思考过程（开启思考模式时才有）。界面**默认折叠**——它是过程不是结论。 */
    val reasoning: String = "",
    /** 这条消息的时间（epoch 毫秒）。气泡下方显示 `HH:mm`。 */
    val at: Long = 0L,
    /** 这条答复消耗的 token（多轮工具调用累加）；用户消息恒为 0、服务端不报用量时也为 0。 */
    val tokens: Int = 0,
    /**
     * 这条「已完成」消息上那个**撤回**按钮（v3.26）。null = 没有可撤回的东西。
     *
     * 只有**真的写成功了**才会有它（写失败没东西可撤），而且它指向 App 内存里的一份
     * 撤回方案——App 重启或超过 30 分钟就失效，那时点它会得到一句实话，而不是假装撤了。
     */
    val undoToken: String? = null,
    /** 撤回按钮上的字（"撤回：删除地址 张三 测试路 1 号"）。 */
    val undoLabel: String? = null,
    /** 这条用户消息挂着的附件（气泡上的 chip）。 */
    val attachments: List<AttachmentChip> = emptyList(),
    /**
     * 这条用户消息**真正发给模型的那段话**（附件全文在里面）。
     *
     * 为什么界面消息上也要留它：下一轮提问时要用它重建历史（见 `historyForModel`）——
     * 不留的话，用户第二句问"表里第三行那个多少钱"时，模型已经看不到表了。
     * 空 = 这条消息没有附件（普通消息一分钱额外开销都不加）。
     */
    val attachmentBlock: String = "",
)

/** 抽屉里一行历史对话（把「显示格式」算好再给界面，界面不做日期和 token 的字符串拼接）。 */
data class ConversationSummary(
    val id: String,
    val title: String,
    val timeLabel: String,
    val tokens: Int,
    val tokenLabel: String,
    val isBranch: Boolean,
    val messageCount: Int,
)

/**
 * 派单员 AI 助手的聊天页状态机。
 *
 * 做四件事：
 * 1. 把用户输入交给 [AiContainer.agentLoop]，把 [AiEvent] 翻译成人话痕迹；
 * 2. 维护**对话列表**（历史 / 切换 / 新建 / 删除 / 从某句分叉）；
 * 3. 把对话落到本地文件（[AiContainer.conversations]），让历史能跨会话留存；
 * 4. 任何异常都转成页面可见的错误，绝不让 App 崩。
 *
 * ### 两条状态，各管一件事（别把它们合并）
 * - [messages]（`List<UiMessage>`）是**界面状态**：流式文本、工具痕迹都在往它上面长，
 *   而且 LazyColumn 拿它当 key 用——所以它必须是一个**稳定的列表实例**，
 *   不能在每次重组时重新 map 出来（否则每帧 key 都变，列表会重建、滚动会跳）。
 * - [conv]（`StoredConversation`）是**盘上状态**：只在明确的时间点（发了消息、跑完了、
 *   切换了对话）由 [messages] 同步过去。两边故意不共用对象，换来的是界面更新不被存盘逻辑拖累。
 */
class AiChatViewModel(private val ai: AiContainer) : ViewModel() {

    /**
     * 「上下文超长」时最多自动缩窗口重试几次。
     *
     * 为什么是 2：窗口是按模型名猜的，最坏的现实情况是"猜的 128k、真实 32k"（4 倍），
     * 折半两次刚好落到位（128→64→32）。再多就是拿用户的时间去换一个本该由推断表解决的事。
     */
    private val MAX_OVERFLOW_SHRINKS = 2

    var messages by mutableStateOf<List<UiMessage>>(emptyList())
        private set

    /** 输入框内容（屏幕可直接读写） */
    var input by mutableStateOf("")

    /**
     * 已经挂上、但**还没发出去**的附件（发送成功后清空）。
     *
     * 上限 [AiAttachment.MAX_FILES] 个：这是"用户自己的文件"，不是系统数据，
     * 多挂几个不会更准，只会把上下文撑爆。
     */
    var attachments by mutableStateOf<List<AiAttachment>>(emptyList())
        private set

    /** 正在上传/解析（界面据此禁用发送键，显示"正在读文件…"）。 */
    var attaching by mutableStateOf(false)
        private set

    /** 挂附件失败的一句话（界面用 Snackbar 提示后置回 null）。 */
    var attachError by mutableStateOf<String?>(null)

    /**
     * 编辑一条**带附件**的旧消息时，把那份附件正文先接过来。
     *
     * 为什么需要：附件正文来自服务端解析，手机上没有副本；编辑重发时如果不带上它，
     * 用户会得到一条"内容一样但没有附件"的消息，而模型对表里每一行的记忆就此断掉。
     * 用户在编辑时**重新选了文件**，就以新选的为准（旧的那份不再自动带）。
     */
    private var editCarryBlock: String? = null
    private var editCarryChips: List<AttachmentChip> = emptyList()

    var sending by mutableStateOf(false)
        private set

    /** 最近一次失败原因（屏幕用 Snackbar 提示后置回 null） */
    var error by mutableStateOf<String?>(null)

    var configured by mutableStateOf(ai.ready())
        private set

    /**
     * 本次提问的 token 消耗不再单独存一份：它就在**最后那条助手消息的 [UiMessage.tokens]** 上，
     * 界面直接读那一条即可。多存一份必然出现"两个数不一致"的问题。
     */

    /** 当前对话的累计用量（气泡下沿那行小字用） */
    var totalTokens by mutableStateOf(0)
        private set

    /** 历史对话（抽屉列表），按更新时间倒序 */
    var history by mutableStateOf<List<ConversationSummary>>(emptyList())
        private set

    /** 当前对话 id（抽屉里高亮哪一行） */
    var activeId by mutableStateOf("")
        private set

    /** 每次「新对话 / 切换对话 / 分叉」自增，界面据此收起键盘并滚动到位 */
    var switchTick by mutableStateOf(0)
        private set

    /** 当前对话是不是从别的对话分叉来的（界面上给一句提示，避免用户以为消息丢了） */
    var activeIsBranch by mutableStateOf(false)
        private set

    // ---------------------------------------------------------- 顶栏胶囊（模型 / 思考强度）

    /** 当前用的模型名（顶栏直接显示，点一下就能换）。 */
    var currentModel by mutableStateOf(ai.currentConfig().model)
        private set

    /** 当前思考强度（顶栏显示，点一下就能换）。 */
    var thinkingLevel by mutableStateOf(ai.currentConfig().thinkingLevel)
        private set

    /** 上下文窗口（token）。 */
    var contextWindow by mutableStateOf(ai.currentConfig().contextWindow)
        private set

    /**
     * 当前上下文用了多少 token。
     *
     * **来源是服务端回报的 `prompt_tokens`**（每次调用都白给），不是本地估算——
     * 本地估偏 20% 会让"到 40% 自动压缩"变成随机事件（见 [com.tapmoay.sorders.ai.AiContext]）。
     * 只有压缩之后、下一次调用之前才短暂用估算值兜一下。
     *
     * ⚠️ 这个数**只用于内部判断，界面上不显示**（用户明确说过不要看"已用多少"）。
     */
    var contextUsed by mutableStateOf(0)
        private set

    /** 可切换的模型候选（上次「拉取模型列表」的结果，已持久化）。 */
    var modelCandidates by mutableStateOf<List<String>>(emptyList())
        private set

    /** 正在压缩上下文（界面给个"正在整理上下文…"的提示，否则用户会觉得卡住）。 */
    var compacting by mutableStateOf(false)
        private set

    /** 最近一次压缩的说明（压缩成功后提示用户一声，避免他以为对话被删了）。 */
    var compactNotice by mutableStateOf<String?>(null)

    /**
     * 正在编辑哪一条**用户消息**（-1 = 不在编辑态）。
     *
     * 为什么要有它：用户明确说「不要有『重问』这个选项，因为再充一遍也没有意义，
     * 应该改成编辑——我这条消息发错了，可以编辑然后点重新发送，他就会撤回上面那个回答，
     * 然后就像重新搞一遍一样」。
     *
     * 所以语义是**改写历史**（不是分叉）：发送时把这条及其之后的全部内容撤掉再重跑。
     * 与「分支」的分工：分支是**另存一份**继续问（原来的对话还在历史里），编辑是**就地重来**。
     */
    var editingIndex by mutableStateOf(-1)
        private set

    // ------------------------------------------------------- 待确认的写操作

    /**
     * 等着用户点确认的写操作（通常 0 或 1 张卡）。
     *
     * ### 它是"AI 改数据"这件事的**唯一闸门**
     * 模型调用 `preview_write` 只会走到 [com.tapmoay.sorders.ai.AiWritePreviewStore.offer]，
     * 把一张卡塞进这里。真正写库的那一步在 [confirmWrite]，而它**只能由界面上的按钮触发**——
     * 模型的调用路径里根本没有这个函数（见 [com.tapmoay.sorders.ai.AiWritePreviewStore] 的不变量 1）。
     */
    var pendingWrites by mutableStateOf<List<AiPendingWrite>>(emptyList())
        private set

    /** 正在执行的那个 token（按钮转圈、防连点）；null = 没有在执行。 */
    var writeBusy by mutableStateOf<String?>(null)
        private set

    /** 把暂存区里的待确认同步到界面（每次工具跑完、每轮循环结束时都刷一次）。 */
    private fun refreshPendingWrites() {
        pendingWrites = ai.writes.list()
    }

    /**
     * 用户点了「确认」→ **这里才是真正写业务数据的地方**。
     *
     * [AiWriteService.execute] 里的 `take` 是取走并删除，所以这个函数被连点两次时，
     * 第二次一定拿不到卡（返回"已经执行过或已过期"），不会写两遍。
     */
    fun confirmWrite(token: String) {
        if (writeBusy != null) return
        writeBusy = token
        viewModelScope.launch {
            val outcome = try {
                ai.writeService.execute(token)
            } catch (ce: CancellationException) {
                throw ce
            } catch (e: Exception) {
                AiWriteOutcome.Rejected(friendlyError(e))
            }
            writeBusy = null
            refreshPendingWrites()
            when (outcome) {
                is AiWriteOutcome.Done -> appendLocal(
                    "✅ " + outcome.message,
                    undoToken = outcome.undoToken,
                    undoLabel = outcome.undoLabel,
                )
                is AiWriteOutcome.Rejected -> appendLocal("⚠️ 没写成：" + outcome.reason, isError = true)
                // execute 不该返回 NeedConfirm；真出现了就把它摆回卡片上，别静默吞掉
                is AiWriteOutcome.NeedConfirm -> refreshPendingWrites()
            }
        }
    }

    /** 用户点了「取消」：把卡从暂存区删掉，一句话交代清楚，不留悬念。 */
    fun cancelWrite(token: String) {
        val p = pendingWrites.firstOrNull { it.token == token }
        ai.writes.cancel(token)
        refreshPendingWrites()
        if (p != null) appendLocal("已取消：" + p.summary)
    }

    /**
     * 往对话里补一条**本机生成**的助手消息（写操作的结果）。
     *
     * ### 为什么不重新问一次模型来"解说"这个结果
     * 1. 结果本身就是一句确定的话，模型只能把它复述一遍，多花一次钱、还多一次编错的机会；
     * 2. 写操作的结果必须**原样**呈现——"已写好"和"没写成"之间没有解释空间。
     *
     * 落成 assistant 是刻意的：下一轮提问时它会作为历史带上去（见 [historyForModel]），
     * 模型因此知道"上一件事办成了"，不会重复申请。
     */
    private fun appendLocal(
        text: String,
        isError: Boolean = false,
        undoToken: String? = null,
        undoLabel: String? = null,
    ) {
        messages = messages + UiMessage(
            Role.ASSISTANT,
            text,
            isError = isError,
            at = System.currentTimeMillis(),
            undoToken = undoToken,
            undoLabel = undoLabel,
        )
        persist()
    }

    /**
     * 用户点了「撤回」→ 把撤回方案**变成一张普通的确认卡**。
     *
     * ### 为什么撤回也要再点一次确认
     * 因为整套设计只有一条写入口：造卡 → 点确认 → `execute` → `commit`。
     * 撤回如果能自己写库，那条路上就没有角色门、没有风险档、也没有一次性 token。
     * 两次点击换"撤回和别的事一样安全"，这笔账是划算的——**撤回本身也可能点错**。
     */
    fun undoWrite(undoToken: String) {
        if (writeBusy != null) return
        writeBusy = undoToken
        viewModelScope.launch {
            val outcome = try {
                ai.writeService.offerUndo(undoToken)
            } catch (ce: CancellationException) {
                throw ce
            } catch (e: Exception) {
                AiWriteOutcome.Rejected(friendlyError(e))
            }
            writeBusy = null
            refreshPendingWrites()
            when (outcome) {
                is AiWriteOutcome.NeedConfirm -> appendLocal(
                    "↩️ 撤回申请已经放上去了：" + outcome.pending.summary + "。点下面的确认就恢复。",
                )
                is AiWriteOutcome.Rejected -> appendLocal("⚠️ 撤回没成：" + outcome.reason, isError = true)
                is AiWriteOutcome.Done -> appendLocal("↩️ " + outcome.message)
            }
        }
    }

    /** 进入编辑：把那条消息的文字装回输入框，界面据此显示"发送后会撤掉原来的回答"。 */
    fun beginEdit(index: Int) {
        val m = messages.getOrNull(index) ?: return
        if (m.role != Role.USER) return
        editingIndex = index
        input = m.text
        // 这条消息带着附件 → 把附件也接过来（见 editCarryBlock 的注释）
        editCarryBlock = m.attachmentBlock.takeIf { it.isNotBlank() }
        editCarryChips = m.attachments
        // 复用"切对话"的滚动/收键盘机制：让输入框露出来并聚焦
        switchTick++
    }

    /** 放弃编辑：输入框清空，不改动任何消息。 */
    fun cancelEdit() {
        editingIndex = -1
        input = ""
        editCarryBlock = null
        editCarryChips = emptyList()
    }

    /**
     * 编辑态落刀：撤掉被编辑的那条**以及它之后的全部内容**（含模型回答）。
     *
     * 三个连带项必须一起改，否则数字会和内容对不上：
     * - `totalTokens` 按剩下的消息重算（撤掉的部分不再出现在这段对话里）；
     * - 若被撤掉的范围里包含**已经压缩成摘要**的部分，摘要必须一起清掉
     *   （那种情况下摘要描述的是"已经被删掉的内容"，留着它会污染后面的每一次回答）；
     * - `contextUsed` 归零，让下一次调用用服务端回报的真实 `prompt_tokens` 重新算。
     */
    private fun applyPendingEdit() {
        val idx = editingIndex
        if (idx < 0) return
        editingIndex = -1
        if (idx >= messages.size) return
        messages = messages.take(idx)
        totalTokens = messages.sumOf { it.tokens }
        if (idx <= conv.compactedUpTo) {
            conv = conv.copy(summary = "", compactedUpTo = 0)
            contextUsed = 0
        }
    }

    /**
     * 顶栏芯片要显示的一行字：平时 `deepseek-flash · 中`，忙时换成状态。
     *
     * 为什么忙时占掉芯片位置：顶栏的副标题已经去掉（用户要求），而"正在查询/正在整理"是**必须**让用户
     * 知道的状态——不能让他以为卡住了。同一个位置换文案，既不新增一行也不会有布局跳动。
     */
    val modelChipLabel: String
        get() = when {
            // ⚠️ `sending` 必须排在 `compacting` **前面**：v3.34 起压缩改成回答落地后**后台**跑，
            //    它可能正跑着用户就问了下一句——那时芯片该说「查询中」（他真正在等的事），
            //    而不是「整理上下文」（那是后台的事，说它会让人以为自己的问题在排队）。
            sending -> "查询中…"
            compacting -> "整理上下文…"
            else -> "$currentModel · ${thinkingLevel.label}"
        }

    /** 刷新模型候选项（打开切换面板时调）。 */
    fun refreshModelOptions() {
        modelCandidates = ai.keyStore.modelCandidates()
    }

    /**
     * 换模型：**立刻生效并落盘**，不等用户再点保存。
     *
     * 为什么不等保存：这是在聊天页顶栏换的，用户的心智是"我换完就用"。
     * 让他换完还得跑一趟设置页点保存，是最容易被骂的那种交互。
     *
     * 顺带**重算上下文窗口并清掉上一轮的用量**：窗口是"跟模型走"的能力值，
     * 换了模型还用旧的会两头错——用大了报超长，用小了白白提前压缩。
     */
    fun switchModel(name: String) {
        val m = name.trim()
        if (m.isEmpty() || m == currentModel) return
        val w = ai.keyStore.windowFor(m)
        ai.keyStore.saveConfig(ai.currentConfig().copy(model = m, contextWindow = w))
        currentModel = m
        contextWindow = w
        contextUsed = 0
    }

    /** 换思考强度（同样立刻生效）。 */
    fun switchThinkingLevel(level: ThinkingLevel) {
        if (level == thinkingLevel) return
        ai.keyStore.saveConfig(ai.currentConfig().copy(thinkingLevel = level))
        thinkingLevel = level
    }

    /** 从设置页返回后，把可能改过的模型/强度/窗口同步过来。 */
    fun refreshConfig() {
        val cfg = ai.currentConfig()
        val w = ai.keyStore.windowFor(cfg.model)
        currentModel = cfg.model
        thinkingLevel = cfg.thinkingLevel
        contextWindow = w
        modelCandidates = ai.keyStore.modelCandidates()
        configured = ai.ready()
    }

    /** 盘上状态：当前对话 */
    private var conv: StoredConversation = AiConversations.blank()

    /** 盘上状态：全部对话（含当前这条） */
    private var all: List<StoredConversation> = emptyList()

    private var job: Job? = null

    /** 协程代次：取消/清空后，旧协程的 finally 不再改动新状态 */
    private var generation = 0

    /** 本轮已累计的 token（多轮工具调用会多次上报，逐次累加） */
    private var runTokens = 0

    /**
     * 本轮**送进去的**上下文大小 = 本轮所有调用里最大的 `prompt_tokens`。
     *
     * 取最大而不是最后一次：一次提问里可能有好几轮工具调用，上下文是**递增**的，
     * 最大值才是"这次真正占了多少"，用它判断"到没到 60%"才不会漏。
     */
    private var runContextTokens = 0

    /**
     * 是否已经把盘上的历史读进来了。
     *
     * **这个标记是一次真实丢历史事故的修复**：`all` 是异步读进来的，读进来之前它是空列表；
     * 而 [send] 第一件事就是 [persist]，[persist] 又按 `all` 重算整个列表 ——
     * 于是"打开 AI 页面后马上提问"会把盘上原有对话**覆盖成只有当前这一段**（实测丢过 3 段）。
     * 所以读盘完成之前，一律只更新当前对话的内存状态、**不动 [all]、不落盘**。
     */
    private var loaded = false
    /** 读盘完成前发生过落盘请求（读完后要补一次）。 */
    private var pendingSave = false

    // ------------------------------------------------------------ 存盘
    // 单线程串行 + 序号去重：并发写盘会让「旧快照盖掉新快照」，历史就丢了。
    private val saveMutex = Mutex()
    private var saveSeq = 0

    init {
        viewModelScope.launch {
            // ⚡ 测试账号的默认模型服务（2026-09-21）：用户自己没配过 key 时向服务端要一份。
            //    ⚠️ 必须放在**画这一屏之前**：`configured` 决定界面显示"去设置"还是聊天框，
            //    晚一步就会出现"进 AI 页先看到『去设置』、过一秒又变成能聊天"的闪动。
            if (ai.ensureDefaultKey()) configured = ai.ready()
            val fromDisk = withContext(Dispatchers.IO) { ai.conversations.load() }
            all = fromDisk
            // 恢复最近一次对话：用户重新进来说「刚才那个问题」是常态，不该看到一片空白
            val newest = fromDisk.firstOrNull()
            conv = newest ?: AiConversations.blank()
            messages = newest?.messages.orEmpty().map { it.toUi() }
            activeId = conv.id
            activeIsBranch = conv.isBranch
            totalTokens = conv.totalTokens
            contextUsed = conv.contextTokens
            publishHistory()
            switchTick++
            // 读盘期间发生过的提问/切换：现在补落一次，把这段对话真正写进历史
            loaded = true
            if (pendingSave) {
                pendingSave = false
                persist()
            }
        }
    }

    /**
     * 把当前 [messages] 同步进 [conv] 并异步落盘。
     *
     * ⚠️ **读盘完成前不落盘**（[loaded]）：见 [loaded] 的注释——那是丢历史的根因。
     */
    private fun persist() {
        val now = System.currentTimeMillis()
        val stored = messages.map { it.toStored() }
        if (!loaded) {
            // 只更新当前对话的内存状态；all 和文件都要等读盘完成后再动
            conv = if (stored.isEmpty()) {
                conv.copy(messages = emptyList(), totalTokens = 0, updatedAt = now)
            } else {
                AiConversations.cap(conv.copy(messages = stored, updatedAt = now))
            }
            totalTokens = conv.totalTokens
            pendingSave = true
            return
        }
        if (stored.isEmpty()) {
            // 对话被清空 → 从历史里摘掉，而不是留一个点进去什么都没有的空壳
            conv = conv.copy(messages = emptyList(), totalTokens = 0, updatedAt = now)
            all = all.filter { it.id != conv.id }
        } else {
            conv = AiConversations.cap(
                conv.copy(
                    messages = stored,
                    updatedAt = now,
                    // 上下文用量与摘要一起落盘：不存的话重启后胶囊显示 0%，
                    // 于是第一次提问会在"已经 80% 满了"的情况下不压缩、直接超窗口报错。
                    contextTokens = contextUsed,
                ),
            )
            all = AiConversations.capAll(all.filter { it.id != conv.id } + conv)
        }
        totalTokens = conv.totalTokens
        publishHistory()
        saveAsync(all)
    }

    private fun saveAsync(snapshot: List<StoredConversation>) {
        val mine = ++saveSeq
        viewModelScope.launch {
            withContext(Dispatchers.IO) {
                saveMutex.withLock {
                    // 已经有更新的快照排在后面 → 这次写盘没有意义，跳过（省一次 IO）
                    if (mine == saveSeq) ai.conversations.save(snapshot)
                }
            }
        }
    }

    private fun publishHistory() {
        val now = System.currentTimeMillis()
        history = AiConversations.capAll(all)
            .filter { it.messages.isNotEmpty() }
            .map { c ->
                ConversationSummary(
                    id = c.id,
                    title = AiConversations.titleOf(c),
                    timeLabel = AiConversations.timeLabel(c.updatedAt, now),
                    tokens = c.totalTokens,
                    tokenLabel = AiConversations.tokenLabel(c.totalTokens),
                    isBranch = c.isBranch,
                    messageCount = c.messages.size,
                )
            }
        activeId = conv.id
        activeIsBranch = conv.isBranch
    }

    /**
     * 从设置页返回后重新确认是否已填 key。
     * 刻意不做成"每次重组都算一遍"：ready() 要解密读 KeyStore，逐帧调用会拖慢输入。
     */
    fun refreshConfigured() {
        configured = ai.ready()
    }

    // ------------------------------------------------------------ 发送

    /**
     * 挂一个文件（用户在系统文件选择器里选完之后调）。
     *
     * 流程：本地先拦一道（扩展名/大小）→ 上传给服务端读成文本 → 变成 [attachments] 里的一项。
     * 全程不抛异常：失败只写 [attachError]（界面用 Snackbar 说人话）。
     *
     * @param onNeedSettings 未配置 key 时调用（聊天页据此跳到设置页）——没配 key 就没有 AI，
     *   也就没有必要把用户的文件传上去。
     */
    fun attach(context: android.content.Context, uri: android.net.Uri, onNeedSettings: () -> Unit) {
        if (attaching) return
        if (!ai.ready()) {
            configured = false
            onNeedSettings()
            return
        }
        if (attachments.size >= AiAttachment.MAX_FILES) {
            attachError = "一次最多挂 ${AiAttachment.MAX_FILES} 个文件。先发出去，或者去掉一个再挂。"
            return
        }
        attaching = true
        attachError = null
        viewModelScope.launch {
            try {
                val picked = withContext(Dispatchers.IO) {
                    AiAttachmentLoader.read(context, uri)
                }
                val att = ai.attachmentService.load(picked.filename, picked.mime, picked.bytes)
                if (att.tables.isEmpty()) {
                    attachError = "这个文件里没有读到任何一行内容。"
                } else {
                    attachments = attachments + att
                }
            } catch (ce: CancellationException) {
                throw ce
            } catch (e: AiAttachmentLoader.AttachmentException) {
                attachError = e.message
            } catch (e: Exception) {
                attachError = friendlyError(e)
            } finally {
                attaching = false
            }
        }
    }

    fun removeAttachment(index: Int) {
        if (index !in attachments.indices) return
        attachments = attachments.filterIndexed { i, _ -> i != index }
    }

    /**
     * 按**来源**摘掉一张图（附件面板里取消勾选时调）。
     *
     * 为什么不复用 [removeAttachment]：那个收的是下标，而面板里点的是"屏幕上那张照片"——
     * 它和下标的对应关系会随后面的挂载/删除漂移（挂第二张时下标就变了）。
     * 来源字符串是唯一不会漂的键。
     */
    fun removeAttachmentByUri(uri: android.net.Uri) {
        val key = uri.toString()
        attachments = attachments.filterNot { it.sourceUri == key }
    }

    /** 这张图是不是已经挂上了（面板据此画勾，避免重复挂同一张）。 */
    fun isAttached(uri: android.net.Uri): Boolean = attachments.any { it.sourceUri == uri.toString() }

    fun clearAttachments() {
        attachments = emptyList()
    }

    /**
     * 挂一张**图片**（相册/拍照选完之后调）。
     *
     * 与挂表格的区别：图片**不经服务端**，压缩成 data URL 后直接作为多模态内容发给模型。
     * 所以这里要拦两件事：
     * 1. 当前模型看不看得懂图（[AiVision]）——看不懂就**当场拦住并说清怎么办**，
     *    而不是让它带图去撞 400，或者更糟：端点收了图但看不见，模型对着空气编；
     * 2. 张数上限（[AiVision.MAX_IMAGES]）——多了既贵又会让模型顾此失彼。
     */
    fun attachImage(context: android.content.Context, uri: android.net.Uri, onNeedSettings: () -> Unit) {
        if (attaching) return
        if (!ai.ready()) {
            configured = false
            onNeedSettings()
            return
        }
        val model = currentModel
        if (!AiVision.canSendImages(model)) {
            attachError = AiVision.hint(model)
            return
        }
        if (attachments.size >= AiAttachment.MAX_FILES) {
            attachError = "一次最多挂 ${AiAttachment.MAX_FILES} 个附件。先发出去，或者去掉一个再挂。"
            return
        }
        if (attachments.count { it.isImage } >= AiVision.MAX_IMAGES) {
            attachError = "一次最多传 ${AiVision.MAX_IMAGES} 张图片。"
            return
        }
        attaching = true
        attachError = null
        viewModelScope.launch {
            try {
                val dataUrl = withContext(Dispatchers.IO) { AiAttachmentLoader.readImage(context, uri) }
                val kb = (dataUrl.length * 3 / 4) / 1024
                val name = AiAttachmentLoader.displayName(context, uri).ifBlank { "图片" }
                attachments = attachments + AiAttachment(
                    filename = name,
                    kind = "image",
                    tables = emptyList(),
                    warnings = emptyList(),
                    imageDataUrl = dataUrl,
                    imageMeta = "约 ${kb}KB（已压缩到长边 1280，够看清）",
                    // 记来源：附件面板里那排"最近照片"要靠它对账（取消勾选时摘哪一张）
                    sourceUri = uri.toString(),
                )
            } catch (ce: CancellationException) {
                throw ce
            } catch (e: AiAttachmentLoader.AttachmentException) {
                attachError = e.message
            } catch (e: Exception) {
                attachError = friendlyError(e)
            } finally {
                attaching = false
            }
        }
    }

    /**
     * 发送一条消息。
     * @param onNeedSettings 未配置 key 时调用（聊天页据此跳到设置页）
     */
    fun send(onNeedSettings: () -> Unit) {
        val text = input.trim()
        val files = attachments
        // 只挂文件、一个字都没打也算一次提问（附件那边会把"先看看这是什么"这层意思补上）
        if ((text.isEmpty() && files.isEmpty()) || sending) return
        if (!ai.ready()) {
            configured = false
            onNeedSettings()
            return
        }
        configured = true
        error = null
        runTokens = 0
        runContextTokens = 0

        val now = System.currentTimeMillis()

        // 编辑态：先把它带过来的附件接住，再动消息列表（applyPendingEdit 会把后面的都撤掉）
        val carryBlock = editCarryBlock
        val carryChips = editCarryChips
        editCarryBlock = null
        editCarryChips = emptyList()

        // 真正发给模型的那段话：用户那句话 + 附件全文（没有附件时**原样**是用户那句话）。
        // 图片不在这里——它是**单独的多模态内容**（见下面的 images），
        // 所以 [modelText] 里只有一句"这张图已经发给你了"，**不含 base64**：
        // 那段 base64 会被写进对话历史，几百 KB 一次足以把对话文件撑爆。
        val modelText = if (files.isNotEmpty()) AiAttachment.augment(text, files) else carryBlock ?: text
        val images = AiAttachment.imagesOf(files)
        val chips = if (files.isNotEmpty()) {
            files.map { AttachmentChip(it.title(), it.summary(), it.warnings) }
        } else {
            carryChips
        }

        // ⚠️ 编辑态要先落刀再追加：撤掉被编辑的那条**以及它之后的全部内容**（含模型回答），
        // 然后这条改过的消息就是新一轮的提问。顺序反了会把旧回答留在列表里，出现"两个回答"。
        applyPendingEdit()
        input = ""
        attachments = emptyList()
        messages = messages + UiMessage(
            Role.USER,
            text,
            at = now,
            attachments = chips,
            // 没有附件就不存 block：普通消息在盘上**不多一个字节**
            attachmentBlock = modelText.takeIf { files.isNotEmpty() || carryBlock != null }.orEmpty(),
        )
        val holder = messages.size // 占位助手消息的下标：先插空气泡，事件往里长
        messages = messages + UiMessage(Role.ASSISTANT, "", at = now)
        sending = true
        // 提问一落进列表就先存一次：App 被杀也不会丢掉用户刚问的问题
        persist()
        val myGen = ++generation

        job = viewModelScope.launch {
            // AiAgentLoop 在调用方调度器上跑事件回调（见其类注释），
            // 所以从 viewModelScope 进来时这里就在 Main 线程，可以直接写 Compose state。
            val streamed = StringBuilder()
            try {
                // ---- 发送前第 0 步：**问清"是不是批发商货主"**（2026-09-20 用户第七轮）----
                // 工具清单、enum、身份段里那份"你实际能干的事"都是按 (角色 + member) 现算的
                // （见 AiActor）。这一问必须发生在 `agentLoop.run` **之前**：
                // 它是同步读 [AiContainer.memberShipper] 的，晚一步模型拿到的就是上一轮的清单。
                // 失败不影响提问（容器里保留了上一次的值，首次仍是 false = 按普通货主，fail-closed）。
                ai.refreshMembership()

                // ---- 发送前：两道闸，顺序不能反（v3.34）----
                // ① 固定预算（主闸）：先降级、再丢弃，**与模型窗口无关**，纯计算不联网
                //    —— 它替代了"窗口 40% 才压缩"那个实际永不触发的旧触发点
                // ② 窗口硬裁（兜底）：预算收完还装不下（窗口被收缩得很小）时从最早的开始丢
                var cfg = ai.currentConfig()
                val systemExtra = prepareSystemExtra(text)
                var history = shrunkHistory(cfg.contextWindow)

                var result = ai.agentLoop.run(
                    userText = modelText,
                    history = history,
                    systemExtra = systemExtra,
                    images = images,
                    onEvent = { ev -> onAiEvent(holder, streamed, ev) },
                )

                // ---- 撞到「上下文超长」→ 自动改窗口重试（最多 2 次）----
                // 为什么必须有这一步：窗口是**按模型名猜的**（接口不返回这个数，用户又不愿意选），
                // 猜大了唯一的补救就是这一次真实报错。没有它，"不给用户选择"就变成"用户被卡死"。
                // 代价极低：超长的响应是 400，不产生生成费用。
                var shrinks = 0
                while (result is AiRunResult.Failure && result.contextOverflow && shrinks < MAX_OVERFLOW_SHRINKS) {
                    shrinks++
                    // 优先用端点自己报的上限；没有就按实证值收缩，再没有才折半
                    val fixed = AiContext.shrinkOnOverflow(
                        cfg.contextWindow,
                        runContextTokens,
                        result.contextLimit,
                    )
                    ai.keyStore.rememberWindow(cfg.model, fixed)
                    contextWindow = fixed
                    cfg = ai.currentConfig()
                    history = shrunkHistory(fixed)
                    // 重试前把这一轮的痕迹清空：超长可能发生在第 2、3 轮工具调用之后，
                    // 不清的话气泡里会出现两遍「正在查…/返回 N 条」，看起来像查了两次。
                    streamed.clear()
                    updateAt(holder) { m -> m.copy(text = "", toolTrace = emptyList(), reasoning = "") }
                    result = ai.agentLoop.run(
                        userText = modelText,
                        history = history,
                        systemExtra = systemExtra,
                        images = images,
                        onEvent = { ev -> onAiEvent(holder, streamed, ev) },
                    )
                }

                when (result) {
                    is AiRunResult.Success -> {
                        // Success.text 为权威文本；核心层只推流不汇总时退回累积的 delta
                        var finalText = result.text.ifBlank { streamed.toString() }
                        if (result.imagesDropped) {
                            // 图**没能发出去**：这句话必须放在回答最前面。
                            // 不说的话，用户会以为"AI 看过我的照片了"——而它其实一个字都没看到，
                            // 那段回答很可能是答非所问（甚至像"你没有发图片给我"）。
                            finalText = "⚠️ 这张图没能发出去（当前模型/端点不收图片输入），" +
                                "下面是「只按文字」回答的；要传图请到设置页换一个能看图的模型。\n\n" + finalText
                        }
                        updateAt(holder) {
                            it.copy(text = finalText.ifBlank { "（模型没有返回内容）" }, tokens = runTokens)
                        }
                        if (runTokens == 0) {
                            result.usage?.totalTokens?.takeIf { it > 0 }?.let {
                                updateAt(holder) { m -> m.copy(tokens = it) }
                            }
                        }
                    }
                    is AiRunResult.Failure -> {
                        val msg = if (result.contextOverflow) {
                            // 缩过窗口还是装不下：此时必须给出下一步，而不是让用户对着报错发呆
                            "${result.userMessage}（自动缩小到 ${AiContext.windowLabel(contextWindow)} 重试仍超长）"
                        } else {
                            result.userMessage
                        }
                        appendError(holder, msg)
                    }
                }
                // ---- 该收口了就去收，但**不挡这一轮**（见 [scheduleCompaction] 的注释）----
                // 判据用**收口前**的完整历史：被 fitToBudget 降级/丢掉的那部分，正是摘要要接住的。
                // 窗口百分比那条降级为兜底——窗口特别小的模型仍然要防超长。
                if (AiContext.overBudget(historyForModel()) ||
                    AiContext.shouldCompact(contextUsed, cfg.contextWindow)
                ) {
                    scheduleCompaction(cfg, myGen)
                }
                observeHabits(text, result)
            } catch (ce: CancellationException) {
                // 用户点了「停止」：保留已产生的消息，不算错误
                markStopped(holder, streamed.toString())
                throw ce
            } catch (e: Exception) {
                // 网络/解析/未知异常一律兜住，转成页面可见的错误
                appendError(holder, friendlyError(e))
            } finally {
                if (generation == myGen) {
                    sending = false
                    job = null
                    // 一轮跑完再兜一次：模型可能在最后一轮才申请（或者刚才那次刷新被并发盖掉了）
                    refreshPendingWrites()
                    // 上下文用量取本轮**最大**的 prompt_tokens：它就是这次真正送进去的量
                    if (runContextTokens > 0) contextUsed = runContextTokens
                    // ---- 窗口猜小了也要能长大 ----
                    // 成功发出去了一个贴着"我们自己设的上限"的量级 → 说明拦住我们的是自己的闸门，
                    // 不是模型的极限。按证据翻倍并记住（翻过头下次会收到 400，而 400 里写着真实上限）。
                    // 没有这一步，认不出的模型会**永远**停在保守的 128k 上、白压一半上下文。
                    AiContext.growOnEvidence(contextWindow, runContextTokens)?.let { bigger ->
                        ai.keyStore.rememberWindow(currentModel, bigger)
                        contextWindow = bigger
                    }
                    // 一轮跑完才落盘：中间的流式更新没必要写文件
                    persist()
                }
            }
        }
    }

    /**
     * 交给模型前把历史收进预算（**唯一入口**，两处调用都走它）。
     *
     * 顺序不能反：
     * 1. [AiContext.fitToBudget] —— 主闸，固定预算、与窗口无关，先降级再丢弃；
     * 2. [AiContext.trimToFit] —— 兜底闸，按窗口的 90% 硬裁（窗口被收缩到很小时才起作用）。
     */
    private fun shrunkHistory(window: Int): List<ChatMessage> =
        AiContext.trimToFit("", AiContext.fitToBudget(historyForModel()), window)

    /**
     * 后台把较早的对话压成摘要（**不再挡用户这一轮**）。
     *
     * ### 为什么从"发送前同步做"改成后台（v3.34）
     * 触发点从「窗口 40%」换成固定预算 [AiContext.HISTORY_BUDGET_TOKENS] 之后，
     * 压缩从"几乎不发生"变成"每隔几轮发生一次"。还同步做的话，用户每隔几轮就要白等一次模型调用
     * ——那就把"省上下文"做成了"变卡"。
     *
     * ### 为什么后台做不会让这一轮答错
     * 被压掉的那部分**这一轮本来就没发出去**（[shrunkHistory] 已经先降级、再丢弃），
     * 摘要的作用是让它在**下一轮**重新变得可用。所以最坏情况是
     * "刚跨过预算的那一轮少带一点上下文"，而不是"信息永久消失"。
     * 另外 [AiContext.fitToBudget] 是纯计算、[AiCompactor] 失败也只降级不抛，
     * 所以摘要这条路断了照样能接着问。
     */
    private fun scheduleCompaction(cfg: LlmConfig, myGen: Int) {
        if (compacting) return                                   // 已经有一次在跑，别叠
        val snapshot = historyForModel()
        // 本来就没什么可压的（`compact` 内部也是这个判据）：别再白跑一次网络
        if (snapshot.size <= AiContext.KEEP_RECENT_MESSAGES + 1) return
        compacting = true
        viewModelScope.launch {
            try {
                val r = ai.compactor.compact(cfg, snapshot) ?: return@launch
                // 跑的过程中用户可能已经编辑/切换/新建对话了 —— 这份摘要描述的是"另一段对话"，
                // 落进去会污染后面每一次回答（与 applyPendingEdit 里清摘要同一个理由）
                if (generation != myGen) return@launch
                conv = conv.copy(
                    summary = r.summary,
                    compactedUpTo = (messages.size - AiContext.KEEP_RECENT_MESSAGES).coerceAtLeast(0),
                )
                // 措辞刻意**不带百分比**：用户明确说过不要看"用了多少"这种数
                compactNotice = if (r.degraded) {
                    "对话较长，已省略较早的内容（本次未能生成摘要）"
                } else {
                    "已把较早的对话压成摘要，接着问就行（原对话仍在「历史」里）"
                }
                persist()
            } catch (ce: CancellationException) {
                throw ce
            } catch (e: Exception) {
                // 摘要失败不阻塞任何事：下一轮还是 fitToBudget 兜着
            } finally {
                compacting = false
            }
        }
    }

    /**
     * 发送前决定往 system prompt 里追加什么：**长期记忆 + 使用习惯 + 早前对话摘要**。
     *
     * ⚠️ v3.34 起这里**不再做压缩**（原来在 40% 窗口时同步压）。
     * 现在压缩在 [scheduleCompaction] 里、回答落地后后台跑，摘要从**下一轮**开始生效。
     * 所以这个函数变成一个纯拼装函数，不再需要 cfg / 代号参数。
     *
     * @param question 本次提问原文——长期记忆要**按提问里出现的实体名**来挑（见 [AiMemories.relevant]），
     *   所以它必须在这里拿到，不能等拼提示词的时候再找。
     */
    private suspend fun prepareSystemExtra(question: String): String? {
        // ---- 长期记忆（本机；只挑和这次提问相关的，关掉开关就完全不用）----
        val memoryHint = ai.memoryHint(question)

        // ---- 使用习惯（本机统计；关掉开关就完全不用）----
        val habitHint = if (ai.habits.enabled()) {
            AiHabits.promptHint(ai.habits.load(), ai.agentLoop::toolDisplayName)
        } else {
            null
        }

        // ---- 早前对话摘要：可能来自上一轮的后台压缩，没有就是 null ----
        val summary = conv.summary.takeIf { it.isNotBlank() }
        return ai.systemExtra(memoryHint, habitHint, summary)
    }

    /** 记下本轮的用户问题与工具调用（本机统计，供下次注入"使用习惯"）。 */
    private suspend fun observeHabits(question: String, result: AiRunResult) {
        if (!ai.habits.enabled()) return
        try {
            val calls = when (result) {
                is AiRunResult.Success -> result.toolCalls
                is AiRunResult.Failure -> result.toolCalls
            }
            withContext(Dispatchers.IO) {
                ai.habits.save(AiHabits.observe(ai.habits.load(), calls, question))
            }
        } catch (e: Exception) {
            // 习惯统计失败不影响任何功能
        }
    }

    /** 取消进行中的循环，已产生的消息保留 */
    fun stop() {
        job?.cancel()
        job = null
        generation++ // 让被取消协程的 finally 不再动状态
        sending = false
        persist()
    }

    // ------------------------------------------------------------ 对话管理

    /** 新开一个对话（旧的自动进历史，不会丢）。 */
    fun newChat() {
        stopRunning()
        persist()
        conv = AiConversations.blank()
        messages = emptyList()
        error = null
        totalTokens = 0
        runTokens = 0
        editingIndex = -1
        // 换对话必须把上下文用量一起换掉：漏了它，胶囊会显示上一段对话的占用，
        // 于是新对话第一句话就可能被误判成"已到 40%"而触发压缩
        contextUsed = 0
        compactNotice = null
        publishHistory()
        switchTick++
    }

    /** 切到某个历史对话。 */
    fun openConversation(id: String) {
        if (id == conv.id) return
        val target = all.firstOrNull { it.id == id } ?: return
        stopRunning()
        persist()
        conv = target
        messages = target.messages.map { it.toUi() }
        error = null
        totalTokens = target.totalTokens
        runTokens = 0
        // 换对话时编辑态必须清掉：留着它，下一次发送会去"撤掉"另一段对话里的消息
        editingIndex = -1
        contextUsed = target.contextTokens
        compactNotice = null
        publishHistory()
        switchTick++
    }

    /** 删除某个历史对话。删的若是当前对话，自动落到剩下最新的一条（没有就开新的）。 */
    fun deleteConversation(id: String) {
        val wasActive = id == conv.id
        if (wasActive) stopRunning()
        all = all.filter { it.id != id }
        saveAsync(all)
        if (wasActive) {
            val next = all.firstOrNull()
            conv = next ?: AiConversations.blank()
            messages = next?.messages.orEmpty().map { it.toUi() }
            totalTokens = conv.totalTokens
            runTokens = 0
            contextUsed = conv.contextTokens
        }
        publishHistory()
        switchTick++
    }

    /**
     * 从当前对话的第 [index] 条消息处分叉：之前的内容原样带过去，之后重新问。
     *
     * 这是「我不想从头再解释一遍，但上面那句我问错了」的解法：
     * 不改动原对话（原件留着当参照），而是开一条新的。
     */
    fun branchFromMessage(index: Int) {
        stopRunning()
        persist()
        if (conv.messages.isEmpty()) return
        val branched = AiConversations.branch(conv, index)
        all = AiConversations.capAll(all + branched)
        conv = branched
        messages = branched.messages.map { it.toUi() }
        error = null
        totalTokens = branched.totalTokens
        runTokens = 0
        editingIndex = -1
        contextUsed = branched.contextTokens
        compactNotice = null
        publishHistory()
        saveAsync(all)
        switchTick++
    }

    /** 把整段对话复制成一条新对话（原件不动）。 */
    fun duplicateConversation(id: String) {
        val src = all.firstOrNull { it.id == id } ?: return
        if (src.messages.isEmpty()) return
        stopRunning()
        persist()
        val copy = AiConversations.duplicate(src)
        all = AiConversations.capAll(all + copy)
        conv = copy
        messages = copy.messages.map { it.toUi() }
        error = null
        totalTokens = copy.totalTokens
        runTokens = 0
        contextUsed = copy.contextTokens
        compactNotice = null
        publishHistory()
        saveAsync(all)
        switchTick++
    }

    /** 清空当前对话的内容（对话本身也一并从历史里摘掉——空壳没有意义）。 */
    fun clear() {
        stopRunning()
        messages = emptyList()
        error = null
        runTokens = 0
        contextUsed = 0
        conv = conv.copy(summary = "", compactedUpTo = 0)
        persist()
        switchTick++
    }

    /** 取某条对话的纯文本（供界面复制到剪贴板）。 */
    fun plainTextOf(id: String? = null): String {
        val target = if (id == null || id == conv.id) conv else all.firstOrNull { it.id == id }
        return target?.let { AiConversations.toPlainText(it) }.orEmpty()
    }

    /** 取单条消息的纯文本（长按某条消息「复制这条」）。 */
    fun plainTextAt(index: Int): String = messages.getOrNull(index)?.text.orEmpty()

    /** 停掉正在跑的循环（切对话前必须调，否则旧回答会长到新对话里）。 */
    private fun stopRunning() {
        if (job != null) {
            job?.cancel()
            job = null
        }
        generation++
        sending = false
        // ⚠️ 换对话必须把待确认的写操作一起清掉。留着它的后果不是"多一张卡"：
        // 用户在对话 A 里让 AI 记一笔支出、没确认就去开了对话 B，几轮之后看到那张卡，
        // 上下文完全不同了，他却会以为那是 B 里刚说的 —— 点了确认就记了一笔他没在想的账。
        ai.writes.clear()
        pendingWrites = emptyList()
    }

    // ---------------- 事件 → 人话痕迹 ----------------

    private fun onAiEvent(holder: Int, streamed: StringBuilder, ev: AiEvent) {
        when (ev) {
            is AiEvent.ToolStarted -> updateAt(holder) { m ->
                m.copy(toolTrace = m.toolTrace + startedLine(ev))
            }
            is AiEvent.ToolFinished -> {
                updateAt(holder) { m -> m.copy(toolTrace = m.toolTrace + finishedLine(ev)) }
                // 申请写操作的工具一跑完就把确认卡摆出来——不要等整轮结束，
                // 那时候模型还在生成"请确认"那句话，卡片早一点出现，读起来才顺。
                if (ev.name == AiTools.PREVIEW_WRITE) refreshPendingWrites()
            }
            is AiEvent.TextDelta -> {
                // 流式下这个事件会**连续触发**，每次带一小段增量，默认语义是追加。
                // replace = true 表示这批内容取代已有正文，有两种来源：
                //   ① 净化器发现先前吐出去的半截里含编号短语（短语跨了分片边界）；
                //   ② 最终答复落定，用净化后的权威文本盖掉过程里累积的预览。
                // ⚠️ 必须连 streamed 一起重置：用户点「停止」时用的是 streamed 的内容
                // （见 catch CancellationException 里的 markStopped），只改 UI 不改它，
                // 会把"过程预览 + 最终答复"两段拼起来存进历史。
                if (ev.replace) streamed.setLength(0)
                streamed.append(ev.text)
                val t = streamed.toString()
                updateAt(holder) { m -> m.copy(text = t) }
            }
            is AiEvent.Reasoning -> {
                // 多轮工具调用时每轮都可能带思考，逐轮追加（用分隔线区分轮次，便于排障）
                updateAt(holder) { m ->
                    val merged = if (m.reasoning.isBlank()) ev.text else m.reasoning + "\n\n———\n\n" + ev.text
                    m.copy(reasoning = merged)
                }
            }
            is AiEvent.Usage -> {
                runTokens += ev.tokens
                // 上下文用量：取本轮最大的 prompt_tokens（真正的"这次送进去多少"）
                if (ev.promptTokens > runContextTokens) runContextTokens = ev.promptTokens
                // 用量挂到这一条答复上（抽屉里的「用量」也是由它累加出来的）
                updateAt(holder) { m -> m.copy(tokens = runTokens) }
            }
            // 刻意不写 else：核心层若新增事件类型，这里立刻编译不过，避免悄悄漏掉一种痕迹
        }
    }

    /** 「🔧 正在查：库存报警」 */
    private fun startedLine(ev: AiEvent.ToolStarted): String {
        val args = ev.argsSummary.trim().replace('\n', ' ')
        val suffix = if (args.isEmpty()) "" else "（" + clip(args, 24) + "）"
        return "🔧 正在查：" + toolLabel(ev.name) + suffix
    }

    /** 「✓ 库存报警 → 3 个商品到红线」/「✗ 库存报警 → 未登录」 */
    private fun finishedLine(ev: AiEvent.ToolFinished): String {
        val mark = if (ev.ok) "✓" else "✗"
        val label = toolLabel(ev.name)
        val summary = ev.summary.trim().replace('\n', ' ')
        return when {
            summary.isEmpty() && ev.ok -> "$mark $label 完成"
            summary.isEmpty() -> "$mark $label 失败"
            else -> "$mark $label → " + clip(summary, 60)
        }
    }

    /** 工具内部名 → 中文名：直接用核心层那一份，避免两边各写一套 */
    private fun toolLabel(raw: String): String = ai.agentLoop.toolDisplayName(raw)

    // ---------------- 消息列表小工具 ----------------

    private fun updateAt(index: Int, transform: (UiMessage) -> UiMessage) {
        if (index !in messages.indices) return
        messages = messages.mapIndexed { i, m -> if (i == index) transform(m) else m }
    }

    /**
     * Failure / 异常统一走这里：占位气泡还没产出任何内容时直接把它变成错误气泡，
     * 已经查到东西时另起一条，避免把痕迹冲掉。
     */
    private fun appendError(holder: Int, raw: String) {
        // 错误气泡也是用户可见文本，同样不许带控制字符（见 AiAnswerSanitizer.stripControl）
        val msg = AiAnswerSanitizer.stripControl(raw).trim().ifBlank { "请求失败，请稍后重试" }
        error = msg
        val cur = messages.getOrNull(holder)
        messages = if (cur != null && cur.text.isBlank() && cur.toolTrace.isEmpty()) {
            messages.mapIndexed { i, m ->
                if (i == holder) UiMessage(Role.ASSISTANT, msg, isError = true, at = m.at) else m
            }
        } else {
            messages + UiMessage(Role.ASSISTANT, msg, isError = true, at = System.currentTimeMillis())
        }
    }

    private fun markStopped(holder: Int, streamed: String) {
        updateAt(holder) { m ->
            val t = if (m.text.isNotBlank()) m.text else streamed
            // 气泡还是空的（还没等到文本）才补一句，避免留下空气泡
            if (t.isBlank() && m.toolTrace.isEmpty()) m.copy(text = "（已停止）") else m.copy(text = t)
        }
    }

    private fun friendlyError(e: Exception): String {
        val raw = e.message?.trim().orEmpty()
        return if (raw.isEmpty()) "请求失败，请检查网络后重试" else "请求失败：" + clip(raw, 120)
    }

    /**
     * 交给核心层的历史。
     *
     * ### 与上一版最大的区别：**不再固定只带最近 10 条**
     * 用户明确要求「默认使用最大的上下文」。所以这里把**整段对话**都带上，
     * 由窗口预算去管边界：到 60% 自动压缩（[prepareSystemExtra]），
     * 压缩失败还有 90% 的硬裁（[AiContext.trimToFit]）。
     *
     * 已经压缩过的话，只带 [StoredConversation.compactedUpTo] 之后的消息——
     * 更早的部分已经在 [StoredConversation.summary] 里了，重复带上等于白花钱。
     *
     * 口径与 `AiAgentLoop.sanitizeHistory` 一致：只留 user / 纯文本 assistant，
     * 跳过错误气泡（工具往返由循环内部重新查，带进来反而会被 sanitize 丢掉）。
     */
    private fun historyForModel(): List<ChatMessage> =
        messages
            .drop(conv.compactedUpTo.coerceAtLeast(0))
            // 只挂附件、没打字的消息也要进历史（text 为空但 attachmentBlock 有内容）——
            // 过滤条件漏了它，模型就会在下一轮"忘记"用户刚传的那张表。
            .filter { !it.isError && (it.text.isNotBlank() || it.attachmentBlock.isNotBlank()) }
            .map {
                if (it.role == Role.USER) {
                    ChatMessage.user(it.attachmentBlock.ifBlank { it.text })
                } else {
                    ChatMessage.assistant(it.text)
                }
            }

    // ---------------- 界面 ↔ 盘上 的字段映射（只此一处，别在别处再写一遍） ----------------

    private fun UiMessage.toStored(): StoredMessage = AiConversations.message(
        isUser = role == Role.USER,
        text = text,
        reasoning = reasoning,
        toolTrace = toolTrace,
        isError = isError,
        at = at,
        tokens = tokens,
        attachments = attachments.map { StoredAttachment(it.filename, it.summary, it.warnings) },
        attachmentBlock = attachmentBlock,
    )

    private fun StoredMessage.toUi(): UiMessage = UiMessage(
        role = if (isUser) Role.USER else Role.ASSISTANT,
        text = text,
        toolTrace = toolTrace,
        isError = isError,
        reasoning = reasoning,
        at = at,
        tokens = tokens,
        attachments = attachments.map { AttachmentChip(it.filename, it.summary, it.warnings) },
        attachmentBlock = attachmentBlock,
    )

    private companion object {
        /** 截断（不切断代理对，避免半个 emoji 变乱码） */
        fun clip(s: String, max: Int): String {
            if (s.length <= max) return s
            var end = max
            if (Character.isHighSurrogate(s[end - 1])) end -= 1
            return s.substring(0, end) + "…"
        }
    }
}
