# Operit（开源 Android AI Agent App）UI 架构与 AI 配置界面分析

> 用途：为 SOrders「AI 功能」做 UI/信息架构参考。重点在**设置界面与记忆界面的 IA**，非视觉细节。
> 代码基线：`D:\AProjects\ASDH\_refs\Operit`（sparse-checkout，含 `docs/`、`app/src/main/java/`、`app/src/main/res/values/`）。

## 1. 整体导航骨架

**结论**：没有 NavHost。顶层是自研「Screen 栈 + 侧滑 Drawer」：`OperitApp` → `AppContent`（`ui/main/components/AppContent.kt` 的 `AppContent()`）按 `currentScreen` 做 Crossfade + 屏幕缓存切换 `Screen.Content()`；抽屉外壳分机型：`ui/main/layout/PhoneLayout.kt`（手机，左滑抽屉，自算 offset/scrim/waterGlass 玻璃态）与 `TabletLayout.kt`（平板，展开 `DrawerContent` / 收起 `CollapsedDrawerContent` 图标栏）。路由 ID 由 `Screen` 子类名转 snake_case 生成（`ScreenRouteRegistry.routeIdForClass/nativeRouteIdForTypeName`）。

- `Screen` sealed class：`ui/main/screens/OperitScreens.kt:100`，字段 `navItem/titleRes/keepAlive/usesRouteViewModelStore`，方法 `Content(navController, navigateTo, onGoBack, ...)`；约 70 个页面：AiChat、AssistantConfig、MemoryBase、Packages、Toolbox、Settings、Workflow、ModelConfig、**ModelConfigOnboarding**、FunctionalConfig、ModelPromptsSettings、ThemeSettings、ChatHistorySettings、ChatBackupSettings、SpeechServicesSettings、TokenUsageStatistics、ContextSummarySettings、MnnModelDownload、PersonaCardGeneration、WaifuModeSettings、ExternalHttpChatSettings、ToolPkgComposeDsl（插件页）等。
- 单一登记表 `hostEntryDefinitions`（`ui/main/screens/ScreenRouteRegistry.kt:110`）：`surface`（MAIN_SIDEBAR_AI / MAIN_SIDEBAR_TOOLS / MAIN_SIDEBAR_SYSTEM / TOOLBOX / hidden）+ `order`；`ui/main/navigation/AppRouteCatalog.kt` 合并插件（toolpkg）贡献的路由与侧栏入口。

**Drawer 菜单**（`ui/main/components/DrawerContent.kt:123 DrawerContent` → `NewSidebarTopContent`）：
1. 顶部品牌卡 `SidebarInfoCard`（品牌名 + 网络状态胶囊）
2. 3 个快捷卡 `SidebarQuickActionCard`：包管理（启用数徽标）、权限（Shizuku/无障碍授权状态徽标）、工作流（数量）
3. 分组「AI 功能」(`nav_group_ai_features`)：AI 对话 / 助手配置 / 记忆库（order 10/20/30）
4. 分组「工具」(`nav_group_tools`)：包管理 / 权限授予 / 工作流
5. 分组「插件」(`nav_group_plugins`)：插件注册的侧栏入口
6. 底部固定 3 格 `DrawerBottomShortcutRow`：关于 / 使用手册 / 设置

## 2. 设置界面（AI 配置核心）完整结构

**结论**：设置 =「一屏总目录（8 组，卡片式）」+ 14 个二级子页；模型配置是独立二级页，内部再分 7 张卡片。总目录 `ui/features/settings/screens/SettingsScreen.kt` 的 `SettingsScreen()`，用两个本地组件：`SettingsSection`（图标+primary 色分组标题+Card 容器）、`CompactSettingsItem`（图标/标题/副标题/ChevronRight）。

### 2.1 总目录分组 → 配置项

- **账号** `settings_section_account`
  - GitHub 账号（登录/登出，`GitHubLoginDialog`）
- **个性化** `settings_section_personalization`
  - 用户偏好 `UserPreferencesSettingsScreen` / 语言 `LanguageSettingsScreen` / 主题外观 `ThemeSettingsScreen` / 全局显示 `GlobalDisplaySettingsScreen` / 布局调整 `LayoutAdjustmentSettingsScreen`
- **AI 模型配置** `settings_section_ai_model`
  - 模型与参数配置 → `ModelConfigScreen`（核心）
  - 功能模型配置 → `FunctionalConfigScreen`
  - 语音服务 → `SpeechServicesSettingsScreen`
- **提示词配置** `settings_prompt_section`
  - 角色卡编辑 `ModelPromptsSettingsScreen` / 人设卡生成 `PersonaCardGenerationScreen` / Waifu 模式 `WaifuModeSettingsScreen`
- **上下文与总结** → `ContextSummarySettingsScreen`
- **数据和权限** `settings_data_permissions`
  - 工具权限 `ToolPermissionSettingsScreen` / 数据备份 `ChatBackupSettingsScreen` / 聊天记录管理 `ChatHistorySettingsScreen` / Token 用量统计 `TokenUsageStatistics`
- **隐私与数据清理** → 清除 Cookie（`CookiePrivacyManager.clearAllCookies`）
- **外部调用** → 外部 HTTP 对话 `ExternalHttpChatSettingsScreen`

### 2.2 模型配置页 `ModelConfigScreen`（=最重要的一页）

`ui/features/settings/screens/ModelConfigScreen.kt:166 ModelConfigScreen(entryMode)`，LazyColumn 自上而下 7 个 item：

1. **「选择模型配置」卡（多配置档案）**：下拉列出 `ModelConfigManager.configListFlow`（默认 `DEFAULT_CONFIG_ID="default"`）；新建/重命名/删除（`showAddConfigDialog`/`showRenameConfigDialog`）；**连接测试**按钮 → `ModelConfigConnectionTester.run` → `ConnectionTestItem` 五项（CHAT / TOOL_CALL / IMAGE / AUDIO / VIDEO）× 三态（PASSED / UNVERIFIED / FAILED）；进入页面默认选中「对话功能」当前绑定档案（`FunctionalConfigManager.getConfigIdForFunction(FunctionType.CHAT)`）。
2. **API 设置**（`sections/ModelApiSettingsSection.kt:132 ModelApiSettingsSection`，`SettingsSectionHeader(Api, api_settings)`）
   - API 提供商：`SettingsSelectorRow` + `ApiProviderDialog`（40+ 家：OpenAI/Anthropic/Google/百度/阿里/讯飞/智谱/DeepSeek/Moonshot/Mistral/SiliconFlow/OpenRouter/Ollama/LM Studio/MNN/llama.cpp/NVIDIA/PPInfra…），弹窗分两组 `provider_section_generic_compatible`（通用兼容）/ `provider_section_proprietary`（专有供应商）+ 搜索
   - API 端点：`SettingsTextField`（Uri 键盘、自动去空格换行）；`selectableEndpointOptions` 下拉预设；「实际请求 URL」提示 `actual_request_url` + 补全规则 `endpoint_completion_hint`；Codex 供应商端点固定只读
   - API 密钥：`SettingsTextField` + `ApiKeyVisualTransformation`
   - 模型名称：可手填，或一键「获取模型列表」（`get_models_list`，搜索 + 多选，`models_displayed`/`models_selected_suffix`）
   - 能力开关：直接处理图片/音频/视频、Codex 直连媒体处理、Codex 联网搜索、Google 搜索、DeepSeek 联网搜索、Claude 1h 提示缓存、**启用工具调用**
   - 分支块：Codex → `CodexAuthSettingsBlock`（登录态/套餐/5 小时与 7 天配额胶囊 `CodexQuotaCapsule`/退出）；MNN → `MnnSettingsBlock`（模型下载、前向类型、线程数）；llama.cpp → `LlamaSettingsBlock`（线程数、上下文、GPU 层数）
3. **上下文与总结**（`ModelConfigScreen.kt:2117 ContextSummarySettingsSection`，两张折叠卡）：上下文设置（上下文长度、最大上下文长度）+ 总结设置（启用总结、总结阈值、按消息条数触发、条数阈值）
4. **思考配置**（`ModelConfigScreen.kt:1087 ThinkingConfigurationsSection`）：「按规则顺序匹配思考参数，首条命中生效」；规则 = 匹配条件 + 思考动作/选项，可增删、上下移（`thinking_config_rule_move_up/down`）、预览 `ThinkingRulePreviewCard`、`ThinkingRuleEditor` 编辑
5. **模型参数设置**（`sections/ModelParametersSection.kt:46`）：ScrollableTabRow 四页签 —— 生成参数（最大生成 Token 数）、创造性参数（温度/Top-P/Top-K）、重复控制参数（presence/frequency/repetition penalty）、自定义参数；核心语义：**每个参数有独立启用开关，关闭则不出现在 API 请求里**（`parameters_description`），底部 `TemperatureRecommendationRow` 给推荐值；`AddCustomParameterDialog` 字段 = 名称 / API 名 / 描述 / 类型（INT|FLOAT|STRING|BOOLEAN|OBJECT）/ 默认值 / 最小值 / 最大值 / 分类
6. **自定义请求头**（`ModelConfigScreen.kt:1914 CustomHeadersSettingsSection`）：键值对增删 + 预设（Android 浏览器 / 桌面 Win / 中文 / 英文 / 移动网关 / 美区）+ 已配置数量
7. **高级设置**（`sections/AdvancedSettingsSection.kt:50 AdvancedSettingsSection`）
   - 请求队列控制（可折叠）：每分钟请求上限、最大并发请求
   - **API 密钥池**：`use_api_key_pool` 开关（"启用后可管理多个 API 密钥，系统将自动轮换使用"）+ `ApiKeyItem` 列表（编辑/删除）+ 添加 / 批量导入 / 导出 / 清空 + **批量连通性测试**（进度、暂停/继续、清除标记）；配套 `ApiKeyPoolAvailabilityTester`

### 2.3 功能模型配置 `FunctionalConfigScreen`（第二重要）

`ui/features/settings/screens/FunctionalConfigScreen.kt:53`，卡片 `FunctionConfigCard`：每个 AI 功能独立绑定「配置档案 + 模型」——展示当前配置名 + 模型名、单独测试连接、展开后先选配置再选模型（多模型 + `functional_config_model_count`）；页首「管理全部模型配置」跳 `ModelConfig`，页尾「全部恢复默认」。`FunctionType` 共 12 项（`strings.xml`）：对话功能 / 上下文总结 / AI 总结标题 / 记忆更新 / 文件绑定处理 / UI 控制器 / 翻译 / Grep 检索 / 群组规划 / 图像识别 / 音频识别 / 视频识别，每项配 `function_desc_*` 说明+选型建议（如"文件绑定建议用快速的廉价模型"）。持久化用 `FunctionalConfigManager.getConfigIdForFunction/setConfigForFunction`。

> 与 SOrders 的差异提示：Operit **没有为设置页写 ViewModel**，状态直接来自 `ModelConfigManager`/`FunctionalConfigManager`（DataStore）+ 页面内 `remember`，保存由 `ModelConfigAutoSaveSupport`/`saveCoordinator` 自动刷盘（`Lifecycle.ON_STOP` 兜底）。你们若沿用 MVVM，可保留 ViewModel，但"编辑即自动保存 + 离开页兜底 flush"这一交互值得抄。

## 3. 启动配置流程（首次引导）

- **`ui/features/startup/` 不是新手引导**：`PluginLoadingScreen.kt:102` 是启动时加载 ToolPkg/Node 插件引擎的进度页（`PluginStatusItem` 逐插件状态、`CollapsedLoadingIndicator` 可拖拽收起、跳过按钮、nodejs/bridge 缺失提示），与模型配置无关。
- **真正的首次配置在聊天页内联**：`ui/features/chat/screens/AIChatScreen.kt` 中 `showConfig` 为真时渲染 `ConfigurationScreen`（`chat/screens/ConfigurationScreen.kt`，222 行）——极简"填一个 API Key 就能用"的快速配置（`onSaveApiKey` → `saveDeepSeekConfiguration`），并提供「自定义」入口跳完整配置：`onNavigateToModelConfig`（AIChatScreen.kt:912）→ `Screen.ModelConfigOnboarding`（OperitScreens.kt:834）以 `entryMode = CHAT_ONBOARDING` **复用同一套 `ModelConfigScreen`**。
- **onboarding 模式的差异**（`ModelConfigScreen.kt:260`）：注册 `RegisterRouteBackGuard` 拦截返回键 —— 先 `saveCoordinator.flushAll`，再用 `ChatConfigReadiness.evaluate` 校验（provider 缺失/不可用、端点非法、模型未填、Codex 未登录、API Key 缺失/非法），通过后写入 `FunctionalConfigManager.setConfigForFunction(FunctionType.CHAT, configId, modelIndex)` 并 `EnhancedAIService.refreshServiceForFunction`，失败则留在本页 + Snackbar 报错。
- 引导显隐依据是 `ChatViewModel.isConfigured`（`chat/viewmodel/ChatViewModel.kt:206`），而**不是**会话级布尔（`docs/TODO/api_key_onboarding/1_QuickConfiguration.md`：Key 需做规范化与半角可打印校验，自定义入口做成全宽描边按钮）。
- 可迁移点：**「快速配置（只填 Key）+ 完整配置（向导式校验）」双入口，引导状态由真实配置推导，而不是"看过就不再提示"**。

## 4. 记忆界面（`ui/features/memory/`）

**结论**：不是列表，是**图谱为主 + 文件夹抽屉 + 一堆对话框**。

- `MemoryScreen.kt:135 MemoryScreen()`：顶部 `MemorySearchBar`(:89，搜索框 + 搜索设置按钮 + 文件夹抽屉按钮)；主体**常驻** `GraphVisualizer`（不因 loading 重建）；右下 4 个 FAB —— 新建记忆 / 导入文档（`OpenDocument`：text/* 与 pdf/doc/docx，文本直读、二进制走 `read_file_full` 工具）/ 连线模式 / 框选模式（框选时多出红色"确认删除"FAB）
- `graph/GraphVisualizer.kt:212 GraphVisualizer`：Canvas 力导向布局，**按 folder 聚类成环形簇**（`buildClusterLayoutInfo`、`clusterRingRadius`），支持缩放/平移/拖节点/框选（`isBoxSelectionMode`+`selectionRect`）/连线（`linkingNodeIds`）/点节点点边；节点配色用 `NodePalette` 跟随明暗主题；增量布局避免全图抖动；数据模型 `graph/model/GraphModels.kt`（Graph{Node(id,label,color,metadata), Edge(id,sourceId,targetId,label,weight,isCrossFolderLink)}）
- `MemoryAppBar.kt:49 MemoryAppBar`：搜索框 + 搜索设置 + **记忆空间（profile）下拉**（多记忆库切换）
- `FolderNavigator.kt:104`：左侧滑出抽屉 = `ProfileSelector`（记忆空间列表，切换即 `setActiveMemorySpace`）+ 文件夹树（`FolderItem` 展开/折叠、新建/重命名/删除/刷新 + 各自确认对话框）
- 对话框族：`EditMemoryDialog`（字段：标题 / 内容 / 来源 / 可信度 credibility / 重要度 importance / 文件夹 / 标签 TagsEditor）、`MemoryInfoDialog`、`EdgeInfoDialog`、`LinkMemoryDialog`、`BatchDeleteConfirmDialog`（`dialogs/MemoryDialogs.kt`）、`DocumentViewDialog`（长文档按 chunk 分片编辑 + 文内搜索）
- **记忆检索配置**（`dialogs/MemorySearchSettingsDialog.kt:54`，很好的 IA 样例）5 组：
  1. 搜索权重：关键词 / 标签 / 向量 / 边 四个滑块
  2. 自动保存：间隔分钟 + 记忆抽取自定义规则
  3. 云端嵌入：启用开关 / endpoint / api key / model（含空白、协议、多 URL 校验）
  4. 维度用量：记忆与 chunk 的向量维度摘要 + 重建索引（分阶段进度：preparing→memory_embedding→chunk_embedding→memory_index→chunk_index→done）
  5. 调试工具：检索模拟（`MemorySearchSimulationDialog`）
- 状态：`viewmodel/MemoryViewModel.kt`（909 行）+ `MemoryViewModelFactory(context, profileId)`，单一 `uiState` + Toast 消息通道

## 5. 聊天界面骨架（只提炼）

- 层级：`AIChatScreen.kt`(1981) → `ChatScreenContent.kt:96`(1242) → `ChatHeader`（历史抽屉/悬浮窗/角色选择器）+ `ChatArea.kt:198 ChatArea` + 输入区 + `ScrollToBottomButton` + `ChatScrollNavigator`（消息定位器）
- 消息列表：`ChatArea` 用自研 `RecyclerLazyColumn`（`components/lazy/` 一整套）实现，带消息锚点、显示窗口分页（`hasOlderDisplayWindow`/`onShowLatestDisplayWindow`）；`MessageItem`(:612) 按 `ChatStyle` 分发 **CURSOR / BUBBLE 两套皮肤**（`CursorStyleChatMessage`、`BubbleAiMessageComposable`/`BubbleUserMessageComposable`）
- **工具调用展示**：AI 消息按 XML 式标签渲染（`part/CustomXmlRenderer.kt`、`part/ThinkToolsXmlNodeGrouper.kt`）→ 折叠「思考」块 + 工具调用块；`part/ToolDisplayComponents.kt` 的 `CompactToolDisplay`/`DetailedToolDisplay` 显示"工具名 + 调用参数 + 参数字节数"，`part/ToolResultDisplay.kt` 显示结果；另有 `FileDiffDisplay`、`ParamVisualizer`、`StatusCardHtmlDocument`、`XmlCanvasBlockComponents`（把 canvas 块渲染成卡片）。`MessageFooterBar` 承载复制/重新生成/切变体/回滚/朗读/分支/收藏
- 输入区：`components/style/input/agent/AgentChatInputSection.kt:163`（另有 classic 版 `ClassicChatInputSection.kt`）——模型选择器 `AgentModelSelectorPopup`、思考设置 `AgentThinkingSettingsItem`、最大上下文 `AgentMaxContextSettingItem`、记忆选择 `AgentMemorySelectorItem`、工具权限 `AgentToolsPermissionGroupItem`+`AgentPermissionSegmentedControl`、行为/插件开关组、全屏输入、发送/停止；配套 `PendingMessageQueuePanel`（待发队列）
- 附件入口：`AttachmentSelector.kt:88 AttachmentSelectorPanel` 九宫格 = 相册 / 拍照 / 记忆库 / 文件 / 屏幕内容 / 通知 / 位置 / 包(插件)；已选附件用 `AttachmentChip` + `AttachmentPreview`，附件查看 `attachments/AttachmentViewerDialog`

## 6. 设计系统（`ui/theme/`、`ui/common/`、`ui/components/`）

- 主题：`theme/Theme.kt:94 OperitTheme`；`theme/Color.kt` 只有 Material 默认 Purple 三色（说明**主色不是固定的**）；真正生效的是一套**偏好快照驱动的可定制主题**：`theme/ThemePreferenceLocals.kt LocalThemePreferenceSnapshot`（系统主题/明暗/自定义主副色/背景图或视频/模糊/状态栏颜色与透明/自定义字体…）→ `ThemeColorSchemeResolver` 产出 colorScheme；`LiquidGlass.kt`/`WaterGlass.kt` 提供"液态玻璃/水玻璃"modifier（抽屉、快捷卡、气泡都在用），`AppBackgroundLayer.kt` 是背景层
- 统一组件（**这就是他们的"设计系统"核心**）：
  - 设置类组件集中在 `settings/sections/ModelApiSettingsSection.kt` 内以 `internal` 导出复用：`SettingsSectionHeader`（图标+标题+副标题）、`SettingsInfoBanner`（tertiaryContainer 提示条）、`SettingsTextField`（标题+副标题+输入的整块 Surface，圆角 10dp，底色 surfaceVariant α0.35，可选 unitText/onClick/trailingContent）、`SettingsSwitchRow`、`SettingsSelectorRow`（点击弹选择器）；`memory/dialogs/MemorySearchSettingsDialog.kt` 里也自带同名 `SettingsSection` + `SliderSettingItem`
  - 页面骨架统一 `ui/components/CustomScaffold.kt`（`Scaffold` + `contentWindowInsets = WindowInsets(0,0,0,0)`，inset 自己管）；卡片惯例 = `RoundedCornerShape(12.dp)` + `CardDefaults.cardElevation(1.dp)` + `BorderStroke(0.7.dp, outlineVariant.α0.5)`
  - `ui/common/` 是**能力层**不是视觉层：markdown 渲染族（`StreamMarkdownRenderer`/`EnhancedCodeBlock`/`EnhancedTableBlock`/`MarkdownImageRenderer`）、`displays/`（`MarkdownTextComposable`/`LatexCache`/`UIAutomationProgressOverlay`）、`composedsl/`（插件用 Compose DSL 渲染页面）、`icons/ProviderLogoLoader`（提供商 Logo 远程加载）、`NavItem.kt`、`RememberLocal.kt`
- **命名/文案规律（对你们最有用）**：分组标题 = 名词短语 + 图标；配置项 = 标题 + 一行副标题说明取舍；开关必带 `_desc` 副文案；危险动作为独立分组（隐私与数据清理）；每引入一个"高级能力"（多套配置档案 / 密钥池 / 自定义参数 / 思考规则）都遵循「默认关闭 + 一行解释 + 单独卡内管理」。

## 7. 给 SOrders「AI 功能」的三条 IA 建议

1. 设置总目录保持"一屏分组卡片"，AI 相关只占 1~2 组；点进二级页再展开参数，避免总目录被模型参数淹没。
2. AI 配置二级页固定分层：**配置档案（可多套）→ 供应商/端点/Key/模型 → 能力开关 → 上下文与总结 → 高级（限流 + 密钥池）**；「连接测试」放在页首可见处，并按能力分项给结果（对话/工具调用/图片…），不要只给一个"成功/失败"。
3. 若做业务知识库/记忆功能，采用"图谱 + 文件夹抽屉 + 详情弹窗"三件套，检索参数单独弹窗（权重 / 自动保存 / 云端嵌入 / 维度用量 / 调试模拟）——比纯列表更适合需要可追溯的业务数据。
