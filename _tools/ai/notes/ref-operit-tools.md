# Operit 工具（Tool）体系考古

> 用途：为 SOrders「垂直工具型 Agent」做机制参考。
> 基线：`D:\AProjects\ASDH\_refs\Operit`，HEAD `b2c7610`。行号为实测（`ToolRegistration`=2745 行、`ToolResultDataClasses`=2729 行）。
> 路径前缀统一省略 `app\src\main\java\com\ai\assistance\operit\`。

---

## 0. 先说结论：哪里别学 Operit

这份报告最重要的价值不是"抄什么"，而是**"哪些坑不要踩"**。Operit 的工具体系有三个明确的弱点，正好是垂直 Agent 必须补的：

| 弱点 | Operit 现状 | SOrders 现状 |
|---|---|---|
| **无最大工具轮数** | `api\chat\` 全目录**没有** `maxIterations`/`MAX_TOOL_ROUNDS`/`roundCount`。循环是递归的，只有三条终止路径：模型不再调工具、token 超阈值、外部取消 | ✅ **已有** `AiAgentLoop.DEFAULT_MAX_STEPS = 8` |
| **参数校验默认恒真** | `ToolExecutor.validateParameters` 默认 `ToolValidationResult(valid=true)`（`AIToolHandler.kt:488-490`）——原生工具**默认没有类型/必填校验**，只能各 executor 自己手写 | ✅ **已有** `ToolArgException` + 逐工具显式校验 |
| **契约拆成 7 处手写** | 注册表(`ToolRegistration`) 与提示词表(`SystemToolPrompts`) 是**两处手写**，名字拼错无编译错误 → 项目里存在一份 200 行的「改工具参数必改 8 处清单」（`docs\doc-src\architecture\DEFAULT_TOOLS_ARCH.md:25-201`） | ⚠️ 3 处（见 §5），**要收敛** |

> **结论**：在"Agent 循环纪律"和"参数校验"这两件事上，**SOrders 比 Operit 做得好**。别因为 Operit 工具多就默认它更成熟。

---

## 1. 工具定义契约（拆成四份，互不交叉校验）

**没有单一"工具定义类"**：

| 维度 | 数据结构 | 位置 |
|---|---|---|
| 运行时调用载体 | `AITool(name, parameters: List<ToolParameter>, description)`；`ToolParameter(name, value: String)`——**值一律字符串** | `data\model\AITool.kt:8-16` |
| 返回载体 | `ToolResult(toolName, success, result: ToolResultData, error: String?)`；`ToolValidationResult(valid, errorMessage)` | `data\model\AITool.kt:29-37` |
| 给模型的 schema | `ToolPrompt(name, description, parameters: String /*旧*/, parametersStructured: List<ToolParameterSchema>?, details, notes)`；`ToolParameterSchema(name, type, description, required, default)` | `data\model\ToolPrompt.kt:6-24` |
| 执行入口 | `interface ToolExecutor { invoke(AITool): ToolResult; invokeAndStream(AITool): Flow<ToolResult>; validateParameters(AITool): ToolValidationResult }` | `core\tools\AIToolHandler.kt:479-491` |

**第 4 份契约**：`registerTool(name, descriptionGenerator: ((AITool) -> String)?, executor)`（`AIToolHandler.kt:179`）——`descriptionGenerator` **不是给模型的**，而是**权限弹窗的人话描述**，注入 `ToolPermissionSystem.operationDescriptionRegistry`（`ui\permissions\ToolPermissionSystem.kt:123,185`）。

**`ToolResultDataClasses.kt` 结果类型**（2729 行，sealed 基类 `:17`，`toJson()` 用 `classDiscriminator="__type"` `:20-27`）——按能力域一族一个 ResultData，全部 `@Serializable`：

| 族 | 类型 |
|---|---|
| 基础标量 | `Boolean/String/Int/Binary/Sleep`（`:32-47,:206-224`） |
| 文件系统 | `DirectoryListing/FileContent/BinaryFileContent/FilePartContent/FileExists/FileInfo/FileOperation/FileApplyResult(含 diff)/FindFiles/GrepResult`（`:411-598,:1141-1170,:1659`） |
| 网络 | `HttpResponse/HttpStreamEvent/VisitWeb/Connection`（`:600-658,:1048,:400`） |
| 系统与应用 | `SystemSetting/AppOperation/AppList/AppUsageTime/Notification/Location/Bluetooth*`（`:661-903,:1247-1312`） |
| UI 自动化 | `SimplifiedUINode/UIPageResult/UIActionResult/CombinedOperationResult/ComputerPageInfoNode/ComputerDesktopActionResult`（`:905-1004,:1314-1370`） |
| 终端与沙箱 | `ADB/TerminalCommand/TerminalStreamEvent/HiddenTerminalCommand/TerminalSession*/Sandbox*/EnvironmentVariable*/McpRestartWithLogs/ScriptExecutionTrace`（`:50-205,:249-329,:1613-1656`） |
| 媒体与计算 | `MusicPlayback/Calculation/Date/FFmpeg`（`:331-397,:1172-1245`） |
| 记忆 | `MemoryQuery/MemoryLink/MemoryLinkQuery`（`:1373,:2276-2320`） |
| 工作流 | `Workflow/WorkflowList/WorkflowDetail`（`:1792-1980`） |
| 对话与 Agent | `Chat*/CharacterCard*/ModelConfig*/FunctionModel*/Speech*/MessageSend*`（`:1982-2256,:2322-2711`） |

---

## 2. 注册与发现

- **一张巨型注册表，且只有一个**：`ToolRegistration.kt:36 registerAllTools(handler, context)` —— 一个 2745 行函数，**~185 次** `handler.registerTool(...)` 顺序登记（首个 `:269 execute_shell`，末个 `:2733 ffmpeg_convert`）。
- 由 `AIToolHandler.registerDefaultTools()`（`:211-218`，AtomicBoolean + 双重检查锁）**一次性、幂等、懒触发**（首次取执行器时 `:306-313` 补注册）；存储是 `ConcurrentHashMap<String, ToolExecutor>`（`:45`），**扁平，无分组、无元数据**。
- **分组只存在于"提示词层"**：`SystemToolPromptCategory`（`ToolPrompt.kt:74`）= categoryName/header/tools/footer；与注册表**靠 name 字符串弱耦合**。
- **启用/禁用是两层，且不影响注册**：
  - 全局开关 `ApiPreferences.enableToolsFlow` + 每工具可见性 `toolPromptVisibilityFlow`（DataStore JSON `Map<String,Boolean>`）+ 顺序 `toolPromptOrderFlow`；裁剪在 `SystemToolPrompts.applyToolVisibility/applyToolOrder`（`:662-677,:648-660`）
  - 角色卡白名单（见 §7）
  - **工具始终全部注册在 handler 里**，只是不进模型可见列表
- **同工具名 × 多权限实现（值得借鉴的设计）**：`ToolGetter.kt:13` 按 `AndroidPermissionLevel{STANDARD, ACCESSIBILITY, DEBUGGER, ADMIN, ROOT}`（`system\AndroidPermissionLevel.kt:11-16`）返回不同实现——即 **1 个工具名 × 至多 5 套执行实现**，对应 `defaultTool/` 的 standard|root|admin|debugger|accessbility 五个子目录。
- **`ToolPackage.kt` 不是注册中心**，而是「包」的数据模型 + 包工具执行器：`ToolPackage(name, description, tools, states, env, isBuiltIn, enabledByDefault, displayName, category, author, version)`（`:301-337`）、`PackageTool(name, description, parameters, script, advice)`（`:352-358`）、`ToolPackageState(id, condition, inheritTools, excludeTools, tools)`（`:340-346`）。它内部**没有 registerTool**，注册由 `PackageManager.kt:3387-3403` 完成。`PackageToolExecutor.validateParameters` 真正做 required 检查（`:459-470`）。

---

## 3. 执行链路

`EnhancedAIService` → `enhance\ToolExecutionManager` → `core\tools\AIToolHandler`：

1. **是否给原生工具表**：`EnhancedAIService.kt:2914-2916` `if (!config.enableToolCall) return null`；`:2939-2969` 组装；`:2976-2997` 追加 `package_proxy`
2. **原生 tool_calls → XML**：`llmprovider\StructuredToolCallBridge.kt:520-566`
3. **解析**：`ToolExecutionManager.extractToolInvocations`（`:307-351`）—— `StreamXmlPlugin` 切块 → `ChatMarkupRegex.toolCallPattern` 取 name/body → `toolParamPattern` 取参数 → `unescapeXml`（处理 CDATA + 实体）→ `ToolInvocation`。另有 `detectAndRepairTruncatedToolRound` 修复未闭合调用，修不好则本轮工具**全部作废**
4. **执行 `executeInvocations`（`:505-688`）——五道闸门顺序**：
   ① 暴露模式拦截（`:540-553`）→ ② 角色卡白名单（`:556-576`）→ ③ Hook 拦截 + 权限检查（`:578-615`）→ 包上下文注入（`:617-631`）→ ④ **并行/串行分组**（`:633-643`，12 个只读工具走 `async`：list_files/read_file*/file_exists/find_files/file_info/grep_code/calculate/ffmpeg_info/visit_web/download_file）→ ⑤ 按原顺序重排（`:680`）
5. **单次执行**：`executeAndEmitTool`（`:693-766`）→ `getToolExecutorOrActivate`（`AIToolHandler.kt:303-359`，可按 `pkg:tool` **自动激活包/MCP**）→ `executeToolSafely`（`:389-420`，先 `validateParameters`，再 `invokeAndStream`，异常转 error ToolResult）
6. **`AIToolHandler` 的角色 = 薄路由器 + 生命周期钩子总线**：不管权限、不做 schema 校验；只做工具表（register/unregister/get）、`executeTool`/`executeToolAndStream`、以及 **7 个 hook 事件**（`AIToolHook.kt:16-36`：requested/intercept/permissionChecked/started/result/error/finished）。拦截可 Block；**钩子抛异常也按 Block 处理**（`:107-109`）。

---

## 4. 工具分类全景（≈185 原生 + 31 个内置 JS 包）

| 能力域 | 工具（同族合并） | 作用 |
|---|---|---|
| 元/激活 | use_package、package_proxy、search、proxy | 激活包；代理调用；CLI 模式下隐藏目录检索/代理执行 |
| 文件系统 | list_files、read_file(_part/_full/_binary)、write_file(_binary)、delete_file、create_file、edit_file、**apply_file**、file_exists、move_file、copy_file、make_directory、find_files、file_info、zip_files、unzip_files、open_file、share_file、grep_code、**grep_context**、download_file | 增删改查/分片/二进制/模糊替换/压缩/系统打开分享/正则与**语义**检索/下载 |
| Shell·终端 | execute_shell、create/close_terminal_session、execute_in_terminal_session(_streaming)、execute_hidden_terminal_command、input_in_terminal_session、get_terminal_session_screen、close_all_virtual_displays | 一次性/会话式/隐藏式终端，读会话屏幕 |
| UI 自动化 | get_page_info、click_element、tap、long_press、swipe、set_input_text、press_key、capture_screenshot、**run_ui_subagent** | 无障碍节点树、坐标/ref 点击、手势、派生子 Agent 跑 UI 任务 |
| 网络·浏览器 | visit_web、http_request、multipart_request、manage_cookies + **22 个 `browser_*`** | 轻量提取 + 完整 Playwright 风格会话浏览器（ref 定位、可跑 JS） |
| 应用·系统 | device_info、get/modify_system_setting、install/uninstall/list_installed_apps、start/stop_app、get_notifications、get_app_usage_time、get_device_location、toast、send_notification、execute_intent、send_broadcast、trigger_tasker_event、sleep | 设备/系统/应用/通知/定位/Intent/广播/Tasker |
| 蓝牙 | 19 个（经典 BR/EDR + BLE GATT 读写订阅） | IoT 场景 |
| 媒体 | music_play(_queue)/pause/resume/stop/seek/set_volume/status、ffmpeg_execute/info/convert | 播放控制 + 任意 FFmpeg |
| 记忆库 | query_memory、get_memory_by_title、create/update/delete/move_memory、link_memories、query_memory_links、update/delete_memory_link、update_user_profile、update_user_preferences | **写入能力也以工具形式暴露**（12 个） |
| 工作流 | get_all/get/create/update/patch/enable/disable/delete/trigger_workflow | CRUD + 差异更新 + 触发 |
| 对话·Agent | start/stop_chat_service、create_new_chat、list_chats、find_chat、agent_status、switch_chat、update_chat_title、delete_chat、**send_message_to_ai(_streaming)**、call_chat_model、list/get_character_cards、get_chat_messages(_range) | 自建/切换会话、**向其他会话发消息**、读历史 |
| 模型与角色卡配置 | list/create/update/delete_model_config、test_model_config_connection、list/get/set_function_model_config、list_character_cards_settings、get/create/update/delete_character_card、set/clear_active_character_card、import/export_character_card_to_tavern_json | **AI 可自我改写模型配置与角色卡** |
| 语音服务 | get/set_speech_services_config、test_tts_playback | TTS/STT 配置读写与试听 |
| 沙箱·环境变量 | read/write_environment_variable、list_sandbox_packages、set_sandbox_package_enabled、execute_sandbox_script_direct | 环境变量、沙箱包开关、跑沙箱脚本 |
| MCP | restart_mcp_with_logs | 重启 MCP 并回传日志 |
| 计算 | calculate | 表达式求值 |
| **内置 JS 包（31 个）** | 12306、automatic_ui_*、browser、code_runner、crossref、daily_life、duckduckgo、extended_chat/file_tools/http_tools/memory_tools、ffmpeg、file_converter、github、google_search、minimax/nanobanana/openai/qwen/siliconflow/xai/zhipu_draw、operit_editor、super_admin、system_tools、tavily、time、various_search、workflow、zhipu_search | **能力覆盖的大头在 JS 包而非 Kotlin**（`app/src/main/assets/packages/*.js`） |

UI 实现侧：`defaultTool\standard\`(22 文件，主实现) / `accessbility|admin|root|debugger\`(各 4，同工具名的 5 套权限实现) / `websession\browser\`(9) + `websession\userscript\`(~20)。

---

## 5. 工具的"描述"怎么给模型

- **手写、且是两套表**：
  - `core\config\SystemToolPrompts.kt`（~960 行）= **AI 默认可见的 4 个分类** `basicTools / fileSystemTools / httpTools / memoryTools`（`:42,:88,:388,:427`）+ 中文版
  - `core\config\SystemToolPromptsInternal.kt`（5992 行）= **13 个"内部/拓展"分类**（Internal Tools、Extended Memory/HTTP/File、Tasker、Workflow、Chat、Internal File/UI/System、Software Settings、FFmpeg…）+ 中文版
  - 语义差别：**"AI 分类" = 模型默认能看到；"内部/拓展" = 默认不可见**（供 `use_package`/CLI 隐藏目录/工作流用）。文件切开只是为了 6000 行不撑爆单个文件，**无语义强制**
- **描述与 function-calling schema 同源，靠"生成"而非"校验"**：`ToolPrompt.parametersStructured` 是唯一真源——
  - 文本提示词由 `ToolPrompt.toString()`（`ToolPrompt.kt:29-67`）渲染
  - 原生 schema 由各 Provider 生成：`OpenAIProvider.buildToolDefinitions:1325` + `buildSchemaFromStructured:1355-1382`；`ClaudeProvider:434-484`（`input_schema`，空 required 时**不带**该字段）；`GeminiProvider:504-524`（`function_declarations`）；`StructuredToolCallBridge.kt:469`
  - **因此两侧必然一致**
- ⚠️ **但注册表(`ToolRegistration`)与提示词表是两处手写**，工具名拼错**不会有编译错误**——这正是那份 200 行「改工具参数必改 8 处清单」存在的原因（含 `JsTools.kt`、`examples/types/*.d.ts`、assets 产物、文档）
- 运行时唯一动态层：`PromptHookRegistry.dispatchToolPromptComposeHooks`，可增删 `ToolPrompt`（ToolPkg 用）

---

## 6. 工具暴露模式与降级

- `ToolExposureMode { FULL, CLI }`（`core\tools\climode\CliToolModeSupport.kt:19-35`）；`resolve(providerType)`：**LMSTUDIO / OLLAMA / OPENAI_LOCAL / MNN / LLAMA_CPP → CLI，其余 FULL**
- **CLI 只给 2 个工具**：`search`（只在隐藏目录里检索）+ `proxy`（用 tool_name + params 代理执行）（`:70 PUBLIC_TOOL_NAMES`、`buildCliPublicToolPrompts:84-166`、提示词 `buildCliModePrompt:168-195` 明文写"不要直接调用隐藏工具，先 search 再 proxy"）
- **为什么这么设计**：小模型的 function-calling 不可靠，185 个 schema 既超窗又降低选择准确率；改成**两级检索式调用**，用一次额外往返换上下文体积与选择准确率，并且完全绕开 provider 的 `tools` 字段（`SystemPromptConfig.kt:387,404` 在 CLI 下清空 availableTools；`:424-429` 用 CLI 提示词替换整个 `TOOL_USAGE_GUIDELINES_SECTION`）
- **代价**：`ToolExecutionManager.kt:211-251` 会在 FULL 模式下**拒绝** `search`/`proxy`，在 CLI 模式下**拒绝**其它一切工具
- **其它按条件裁剪的地方**：
  1. **按模型能力**——`getAIAllCategoriesEn(hasBackendImageRecognition, chatModelHasDirectImage, hasBackendAudio/VideoRecognition, chatModelHasDirectAudio/Video, safBookmarkNames)` 动态过滤 `read_file` 的参数并改写描述（`:511-537`）
  2. **按模型配置**——`enableTools`/`enableToolCall`
  3. **按角色卡**——`CharacterCardToolAccessResolver.resolve()` + `retainAll`
  4. **按包状态**——`ToolPackageState.condition` 由 `condition\ConditionEvaluator.kt:8` 求值，capabilities 快照含 `platform.*`、`ui.virtual_display`、`android.permission_level`、`android.shizuku_available`…；激活/刷新时取第一个成立的 state（**不是每次调用**）

---

## 7. 工具权限

- `PermissionLevel { ALLOW, ASK, FORBID }`（`ui\permissions\ToolPermissionSystem.kt:34-50`；`fromString` 兼容旧值 `CAUTION→ASK`，未知→ASK）
- 结果类型 `ToolPermissionCheckResult{GRANTED, DENIED, OVERLAY_PERMISSION_REQUIRED, CONFIRMATION_TIMEOUT}`；弹窗返回 `PermissionRequestResult{ALLOW, DENY, ALWAYS_ALLOW}`
- **存储**：DataStore `tool_permissions`；全局键 `master_switch`（默认 **ASK**），单工具键 `tool_permission_<toolName>`。**优先级 `overrideLevel ?: masterSwitch`**（`:196-200`）。`ALWAYS_ALLOW` 落盘为单工具 ALLOW 例外；`clearToolPermission` 删例外回落全局
- **检查位置**：链路第 ③ 步、**在参数校验与 invoke 之前**。`AIToolHandler.executeTool/executeToolAndStream` **自身不查权限**（约 60 处 UI/内部直调绕过）——即**权限只约束"模型发起的调用"**
- **ASK 挂起/恢复**：`requestPermission:212-263` → `withTimeoutOrNull(60_000)` 包 `suspendCancellableCoroutine`，continuation 存 `currentPermissionCallback`；主线程 `PermissionRequestOverlay.show`（**WindowManager 悬浮窗**，`TYPE_APPLICATION_OVERLAY`）→ 点击后恢复 continuation，`executeInvocations` 从 `:588` 继续；超时→`CONFIRMATION_TIMEOUT`，无悬浮窗权限→`OVERLAY_PERMISSION_REQUIRED` 并跳系统授权

### ⚠️ 两个偏差（对 SOrders 是重要的反面教材）

1. **权限可被模型绕过**：`ToolExecutionManager.kt:459`
   ```kotlin
   hasPromptForPermission = !invocation.rawText.contains("deny_tool")
   ```
   → 模型只要在调用原文里带上 `deny_tool` 就**跳过权限检查**并记为 granted（`:488-493`）。
   **教训：权限判定绝不能建立在"模型可控的文本"上。** 这正是 SOrders §2.5 两段式设计要避免的——token 由 App 生成、服务端校验，不经过模型。
2. `ToolRegistration.kt:240-256` 对 `package_proxy` 的目标工具用 `runBlocking` 再查一次权限（代理链需要）。

---

## 8. 扩展机制：四者定位

**共同汇聚点**：全部最终走 `AIToolHandler.registerTool`（`:179`），命名空间统一 `<package|pluginId>:<tool>`。

| | 入注册表路径 | 作者要产出 | 定位 |
|---|---|---|---|
| **ToolPkg** | `PackageManager.registerPackageTools:3387-3404` | `.toolpkg`(ZIP)：manifest + `packages/x.js` 顶部 `/* METADATA {name,description,env[],tools[{name,description,parameters[]}]} */` + `exports.fn` | **完整插件容器**：可带资源、WASM、Compose DSL UI、20+ 种宿主 hook |
| **JS 脚本** | 与 ToolPkg **共用** registerPackageTools | 单文件 `.js` + 顶部 METADATA + `exports.fn` | **一个文件即可加工具**的极简形态 |
| **MCP** | `data\mcp\MCPRepository.kt:1201-1262` | 标准 mcpServers JSON（command/args/env 或 endpoint/type=stdio\|streamable_http\|sse） | **复用外部进程/远程协议与生态**，不写 Kotlin |
| **Skill** | **不注册工具** | `Download/Operit/skills/<name>/SKILL.md`（frontmatter name/description） | **零注册成本的提示词注入**：`SkillManager.getSkillSystemPrompt()` 返回全文 + 目录树，靠 `use_package` 激活后让 AI 用通用工具自己干 |

**最小步骤（ToolPkg / 单文件 JS）**：① 写 METADATA（含 `tools[]` 与 parameters）；② 导出 `exports.fn`（内部用 `toolCall(name, params)` 或 `Tools.*` 命名空间）；③ 放入 `app/src/main/assets/packages/`（内置）或设备 `Android/data/<appId>/files/packages/`（导入）；④ 启用包并 `use_package`；⑤ 之后即可被 `<pkg>:<tool>` 调用。
**`advice: true` 的工具只进提示词、不注册真实执行器**（`PackageManager.kt:3389`）。

---

## 9. 结果如何回灌给模型

- **序列化**：`ToolResult.result.toString()`（`ToolResultData` 强制实现 `toString()`）→ `ConversationMarkupManager.formatToolResultForMessage`：
  - 成功 `<tool_result_XXXX name="…" status="success"><content>…</content></tool_result_XXXX>`
  - 失败 `status="error"` + `<content><error>error+detail</error></content>`
- **标签名随机**：`ChatMarkupRegex.generateRandomToolResultTagName()`（`SecureRandom` 4 位）——**防模型伪造工具结果**。解析侧接受 `tool_result(_[A-Za-z0-9_]+)?`
- **截断（有上限）**：`ToolExecutionLimits.kt:8` `MAX_SINGLE_TOOL_RESULT_MESSAGE_CHARS = MAX_FILE_READ_BYTES * 2 = 64_000` 字符/条（另有 `MAX_FILE_READ_BYTES=32_000`、`DEFAULT_FILE_READ_PART_LINES=200`、`MAX_TEXT_RESULT_LENGTH=5_000` 用于 MCP 超长落盘）。实现先算空壳长度再截断，后缀 `"\n[工具结果过长，已截断]"`。**批次本身不限长**（每个工具调用必须保留结果槽）
- **变成消息**：`buildToolResultMessage(results)` → `processToolResults` 追加 `PromptTurn(kind = TOOL_RESULT)` → `startAssistantResponseRound` → 再次 `sendMessage`
- **失败表达统一为** `ToolResult(success=false, result=StringResultData(""), error=…)`：工具不存在、参数校验失败、Hook 拦截、权限拒绝、角色卡拒绝、暴露模式拒绝、执行异常——**都是同构的 error 文本回灌，不会中断对话**

---

## 10. 给垂直 Agent 的 5 条可迁移结论

1. **契约要收敛成一处**。Operit 把 schema / 注册 / 实现 / JS wrapper / 类型声明 / 文档 / 产物拆成 7 处手写，代价是一份 200 行人工 checklist。垂直 Agent 应让 **schema 与注册同源生成**。
2. **注册表扁平 + 分组只在提示词层**最省事，但失去"按组启停"能力（Operit 靠两级可见性 map 补偿）。
3. **同工具名 × 多权限实现**（`ToolGetter`）是 Android 场景独有的优雅解法——"**按环境能力选择实现**"这个思路值得借鉴。
4. **CLI 降级**（search + proxy 两工具）是给弱模型的有效兜底，代价是拒绝一切其它工具。只服务强模型的垂直 Agent 可跳过。
5. **默认恒真的参数校验 + 无最大轮数**是这套设计最需要补的两块——**而这两块 SOrders 已经有了**。
