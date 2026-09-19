# Operit AI 对话引擎运行时机制（代码考古）

> 用途：为 SOrders「AI 功能」做**运行时机制**参考——一次对话怎么跑、上下文怎么裁、工具怎么调、多厂商怎么抹平。
> 代码基线：`D:\AProjects\ASDH\_refs\Operit`，HEAD `b2c7610`（sparse-checkout：`docs/`、`app/src/main/java/`、`app/src/main/res/values/`）。
> 行号基于该检出，仓库演进后会漂移。

## 1. 一次对话的完整生命周期

分层：UI ViewModel → `ChatServiceCore`（门面）→ `MessageCoordination`（总结/角色卡/群聊）→ `MessageProcessing`（构造消息+附件）→ `EnhancedAIService`（**主循环**）→ `AIService` Provider（协议）。

调用链：

1. `ChatViewModel.kt:1460 sendUserMessage()`（UI 触发）
2. → `ChatServiceCore.kt:252 sendUserMessage()` → `:263` 委托
3. → `MessageCoordinationDelegate.kt:327` → `:518 sendMessageInternal()`
   - `:681-707` 先判「是否需要总结」，命中则 `launchAsyncSummaryForSend:1747` **异步压缩历史、不阻塞发送**
   - `:623-670` 解析角色卡绑定的**模型/记忆空间覆盖**
   - 群聊走 `:784 orchestrateGroupConversation`，失败回退 `:582` 普通发送
4. → `MessageProcessingDelegate.kt:681` → `AIMessageManager.buildUserMessageContent:776`（拼附件/引用/直连多模态）→ 构造 `SendMessageOptions` → `EnhancedAIService.sendMessage`
5. → `EnhancedAIService.kt:903 sendMessage(options)`（主循环，`:964` 用 `stream { }` 惰性包裹）
   - `:1000 prepareConversationHistory` → `:1048 getAvailableToolsForFunction` → `:1061/:1085` PromptFinalize Hook → `:1111 estimatePreparedRequestWindow` → `:1122 Provider.sendMessage`
   - `:1181 responseStream.collect{}` 逐块收流 → `roundManager.appendChunk` → `:1219 emit(content)` 推 UI
6. → `:1712 processStreamCompletion`；有工具调用则 `:2072 handleToolInvocation`，否则 `:2011 finalizeAssistantResponse`（置 `isConversationActive=false`、`InputProcessingState.Completed`、**`MemoryAutoSaveCandidateRepository.enqueue` 入队记忆自动保存**）

核心运行时对象：`MessageExecutionContext`（`:426-435`）、`ModelExecutionSnapshot`（`:415`，ServiceLease + ModelConfigData + modelParameters）。

## 2. 上下文拼装与压缩

### 2.1 系统提示词来源
`ConversationService.prepareConversationHistory:447`。历史无 SYSTEM turn 时（`:506`）组装，叠加顺序（`:604-618`）：

1. avatar mood 规则
2. 主系统提示 `SystemPromptConfig.getSystemPromptWithCustomPrompts:573`
3. proxy 角色卡 `<assistant_role>`
4. waifu 规则
5. `<user_profile source="memory-space/{id}/user.md">` ← **记忆空间的用户资料文档**

最后 `:622 replacePromptPlaceholders` 替换 `{{AI_NAME}}` 等占位符并插到 index 0。

历史处理（`:636-656`）：ASSISTANT 用 `NativeXmlSplitter` 拆工具块 → `processChatMessageWithTools:718`；TOOL_RESULT 走 `normalizeToolResultMarkupForModel:691`。

### 2.2 压缩算法 = **摘要锚点截断**（关键设计）
- `AIMessageManager.getMemoryFromMessages:1331`：`indexOfLast { sender=="summary" }`（`:1339`），**只保留该摘要之后的消息**。上下文 = 最后一条摘要 + 其后全部消息。
- 触发 `shouldGenerateSummary:1281`，两条件 **OR**：
  - token 率 ≥ `summaryTokenThreshold`（默认 0.70；`maxTokens = effectiveContextLength * 1024`）
  - 自上次摘要起 user 消息数 ≥ `summaryMessageCountThreshold`（默认 16）
- 执行：`ConversationService.generateSummaryFromPromptTurns:114`，用 **`FunctionType.SUMMARY` 的独立模型配置**（`:136-140`），提示词 `FunctionalPrompts.buildSummarySystemPrompt:209`。
- 落位：`ChatHistoryDelegate.findProperSummaryPosition`（最后一条 AI 消息之后）→ `addSummaryMessage`。

> **设计要点**：摘要是会话里的一类**特殊消息**（`sender == "summary"`），滚动增量、整体替换（新摘要完全取代旧摘要），而不是外挂的独立存储。

### 2.3 超限处理
无硬截断兜底。工具结果回灌后重估 token（`EnhancedAIService:2302`），超阈值 `:2310-2322` → `handleTokenLimitExceeded:1611` 强制总结并中断本轮。

### 2.4 「窗口规划」是另一条独立通道
`library/ChatMemoryWindowPlanner.kt:16-21` 按 8–48 条（默认 32）切窗，`ChatMemoryRebuildManager:93` 逐窗调 `MemoryLibrary.saveMemoryWindowNow` 抽长期记忆 —— 这是**记忆库离线重建**，与在线上下文压缩**互不相干**。

## 3. 工具调用循环（Agent Loop）

### 3.1 最关键的设计决策：原生 tool_calls 一律反向编译成 XML
**所有 Provider 的原生 `tool_calls` 都被转成 XML 标记，主循环只存在一套 XML 解析器。**

- `StructuredToolCallBridge.kt:525-566`：`{"tool_calls":[{function:{name,arguments}}]}` → `<随机tag name="x"><param name="k">v</param></随机tag>`
  - tag 名**随机生成**（`generateRandomToolTagName`）防止模型自造标签
  - 无 JSON 时退化 `<param name="_raw_arguments">`（`:555`）
- 解析：`ToolExecutionManager.extractToolInvocations:307`（流式 XML 分块 + 正则）

### 3.2 循环体与终止
`processStreamCompletion:1712` → `:1837 enhanceToolDetection`（XML 流式修复）→ `:1838 detectAndRepairTruncatedToolRound`（未闭合工具块：补齐后缀 `:1502`，或整轮作废 + 注入 warning `:1919`）→ `:1956 handleToolInvocation` → `executeInvocations:505` → `processToolResults:2191` → `:2248` 包成 TOOL_RESULT turn 追加历史 → `:2269 startAssistantResponseRound` → `:2336` 再请求 → 回到 `processStreamCompletion:2458`。

**终止条件**：该轮不再产出工具调用 → `:1985 finalizeAssistantResponse`。
另两条提前退出：token 超阈值、内容为空/纯思考（`:1749`/`:1771`，后者也回灌告警继续生成）。
> ⚠️ **未发现显式轮数上限**（无 `maxRounds`/迭代计数常量），疑似依赖 token 阈值 + 取消 + 模型自行收口。**未验证**。

### 3.3 并行 / 重试 / 错误回灌
- **并行**：`executeInvocations:634-643` 白名单 `parallelizableToolNames`（12 个：list_files / read_file / read_file_part / read_file_full / file_exists / find_files / file_info / grep_code / calculate / ffmpeg_info / visit_web / download_file）用 `async` 并发，其余串行（`:649-677`），结果按原顺序重排（`:680`）。
- **重试**：`LlmRetryPolicy.kt:4-12`，`MAX_RETRY_ATTEMPTS=5`，指数退避 1s→16s。重试前用 savepoint/rollback **撤回已流出的半截内容**（`OpenAIProvider:3245-3247` + `TextStreamRevisionTracker`）。
- **错误回灌**：工具失败不抛给用户，转成 `ToolResult(success=false, error=…)` 文本进历史让模型自纠。

### 3.4 权限拦截 = 4 层漏斗（`executeInvocations` 严格顺序）
1. **工具暴露模式**（`:539-553`）：`ToolExposureMode`；本地模型（OLLAMA/LMSTUDIO/MNN/LLAMA_CPP/OPENAI_LOCAL）降级 CLI 模式，只给 search/proxy 两个工具
2. **角色卡工具白名单**（`:555-576`，`CharacterCardToolAccessResolver`）
3. **Hook 拦截**（`:585` `AIToolHandler.checkToolInterception` → `AIToolHookDecision.Allow/Block`）
4. **权限系统** `checkToolPermission:430`：可弹 UI 询问；含 `deny_tool` 则跳过询问直接放行

> 用户侧可见的三档（允许 / 每次询问 / 禁止）× 两层（全局默认 + 单工具例外）见 `docs/doc-src/feature-protocol/tool_permissions.md`。

## 4. 多模型 Provider 适配层

- **唯一接口** `AIService.kt:12-104`：`sendMessage(...): Stream<String>`（**无论 stream 真假都返回 Stream**）、`calculateInputTokens`、`inputTokenCount/cachedInputTokenCount/outputTokenCount`、`cancelStreaming/release`。
- **工厂与装饰** `AIServiceFactory.kt:260+`，装饰顺序：
  1. `TokenTrackingAIService`（`:275`，仅拿到 provider 真实 usage 才记账）
  2. JS 插件注册的 Provider（`:287 ToolPkgAiProviderRegistry` → `ToolPkgJsAiProviderService`）← **扩展点**
  3. `when (providerType)` 大 switch（`:317-696`）
  另有 `RateLimitedAIService`（滑动窗口限流）与 `MultiServiceManager`（按 `FunctionType` 缓存实例 + `ServiceLease` 引用计数）。
- **密钥策略**：`useMultipleApiKeys` 时用 `MultiApiKeyProvider`（ROUND_ROBIN / RANDOM），否则 `SingleApiKeyProvider`（`AIServiceFactory.kt:303-307`）。
- **协议差异全在 Provider 内部消化，主循环完全看不见**：
  - OpenAI Chat：`OpenAIProvider`（3144 行）`processStreamingResponse:3107` 读 `data:` 行、`[DONE]` 收尾
  - OpenAI Responses：`convertMessagesToResponsesInput:423` 把 messages 转 `input` 数组；工具结果用 `function_call_output`
  - Anthropic：`ClaudeProvider` system 提为顶层 system blocks + `cache_control:ephemeral`；工具用 `tool_use`/`tool_result`
  - Gemini：`GeminiProvider` 用 `functionCall`/`functionResponse` part，额外承载 thought signature
  - 中文/兼容厂商（BAIDU、XUNFEI、ZHIPU、BAICHUAN、MINIMAX 等 11 个）**直接复用 `OpenAIProvider`**（`AIServiceFactory.kt:510-534`）
- **流式**：自研 `Stream` 抽象（`util/stream`，`stream { }` builder + `StreamCollector` + `MutableSharedStream`）；Provider 内用 OkHttp 阻塞 `readLine()` 解 SSE 再 `emit`。`TextStreamRevisionTracker` 提供 savepoint/rollback 支撑「撤回重试」。
- **厂商枚举**：`data/model/ModelConfigData.kt` 的 `ApiProviderType`，共 **39 个**。

## 5. 提示词工程骨架

| 文件 | 行数 | 职责 |
|---|---|---|
| `core/config/SystemPromptConfig.kt` | 712 | **组装器**。骨架模板 `SYSTEM_PROMPT_TEMPLATE:163-176`，6 个占位块 |
| `core/config/SystemToolPrompts.kt` | 975 | **内置工具目录**。分类化 `SystemToolPromptCategory`（basic/fileSystem/http/memory，中英各一套），按「模型能否直连看图/听音/看视频 + 是否有后端识别服务」**动态裁剪** |
| `core/config/SystemToolPromptsInternal.kt` | 5984 | **内部工具精写文档表**。仅 2 个顶层值（`internalToolCategoriesEn:9` / `Cn:3001`），**几乎 100% 是纯提示词数据**，无控制逻辑 |
| `core/config/FunctionalPrompts.kt` | 1176 | **非对话功能提示词**。摘要、文件绑定合并、记忆自动归类、知识图谱提取 |

**系统提示骨架（6 块）**：
```
BEGIN_SELF_INTRODUCTION_SECTION   ← 可被用户自定义文案替换（applyCustomPrompts:223）
WORKSPACE_GUIDELINES_SECTION
TOOL_USAGE_GUIDELINES_SECTION
PACKAGE_SYSTEM_GUIDELINES_SECTION
ACTIVE_PACKAGES_SECTION
AVAILABLE_TOOLS_SECTION           ← 含 memory 工具（query_memory / get_memory_by_title）
```
> **注意：主系统提示里没有「记忆注入」段。** 记忆只在 AVAILABLE_TOOLS 里以**两个只读工具**出现；写入靠异步图谱提取（见 `ref-operit-memory.md`）。

**摘要固定 4 段**：核心任务状态 / 互动情节与设定 / 对话历程与概要 / 关键信息与上下文（段标题可覆盖，`resolveSummarySections:166`）。

**子任务专用精简模板** `SUBTASK_AGENT_PROMPT_TEMPLATE:198`：无记忆、无人格、禁止等待用户输入、**必须给结论而非原始数据**。

**共性**：中英双份、数据驱动、可被插件覆盖；工具描述与 function-calling schema 同源。

## 6. Hook / 插件扩展点

三套注册表在 `core/chat/hooks/`，共同模式：`CopyOnWriteArrayList` + `@Synchronized register/unregister` + 逐个 `runCatching`（单 Hook 异常不影响主流程）+ 增量覆盖合并（`null` = 不改，`PromptHookRegistry.kt:256-276`）。

- **`PromptHookRegistry.kt`**（277 行）：7 个接口。生命周期挂载点按序：
  `before_prepare_history` / `after_prepare_history` → `before_compose_system_prompt` / `compose_system_prompt_sections` / `after_compose_system_prompt` → `before_finalize_prompt` / `before_send_to_model`
  **特殊设计**：token 估算路径只跑 estimate 版 Hook，故意 bypass 提示词/工具 Hook，保证「估算无副作用」。
- **`SummaryHookRegistry.kt`**（99 行）：唯一 `SummaryGenerateHook`，两个 stage。
- **`ChatRuntimeHookRegistry.kt`**（80 行）：仅 `STATE_CHANGED` 一个事件，**纯观察者、不可改写**。
- **更粗一层**：`MessageProcessingPluginRegistry.kt`（53 行）—— 可**整体接管**一次发消息（返回自己的 `Stream<String>` + cancel controller）。

> **只有 JS 工具包（ToolPkg）能注册 Hook**：`JsEngine.kt:1859/1904/1939`；原生 Kotlin 侧未发现内置实现（**未验证**，可能在未检出的 `app/src/main/assets`）。

## 7. 未验证项（重要）
1. 工具循环是否有隐式轮数上限 —— 未发现常量，**未验证**有无更外层限制。
2. 原生 Kotlin 侧 Hook 实现 —— 仅搜到 JS 桥注册入口，assets 未检出。
3. `SystemToolPromptsInternal` 5984 行只抽读头部与结构，工具条目全集未逐条核对。
4. 行号基于 HEAD `b2c7610`。

## 8. 最易踩坑的隐式契约
> **「XML 标记是工具调用的唯一真相」** —— 接入新厂商时必须复用 `StructuredToolCallBridge.toXmlToolMarkup` 把原生 `tool_calls` 转成 XML，否则主循环不认。这是全项目耦合最紧的一点。
