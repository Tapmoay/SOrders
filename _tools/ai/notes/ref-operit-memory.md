# Operit 长期记忆系统全解

> 用途：为 SOrders「AI 功能」做**记忆机制**参考——记忆怎么存、怎么检索打分、怎么由 AI 决定写什么、怎么写回。
> 代码基线：`D:\AProjects\ASDH\_refs\Operit`，HEAD `b2c7610`。行号基于该检出。
> 设计说明文档：`docs/doc-src/architecture/memory_candidate_scoring_formula.md`、`docs/doc-src/package-dev/memory.md`。

## 0. 一句话总览

记忆 = **三步机制**：① 本地检索找候选（打分排序取前 15）→ ② 交给模型做结构化决策（新增/更新/合并/连线）→ ③ 按**固定顺序**写回记忆库。
旧「问题库」工具仍在，但只是兼容层。

**关键定位**：记忆是**图谱化**的（节点=Memory，边=MemoryLink），不是向量数据库式的扁平片段集合。向量只是打分的一个分量。

## 1. 数据模型（ObjectBox）

`data/model/Memory.kt`：

| 实体 | 关键字段 | 说明 |
|---|---|---|
| `Memory` | `uuid` / `title` / `content` / `contentType` | 核心记忆单元；`title` 是检索主键 |
| | `source`（默认 `unknown`）/ `credibility`（0.5）/ `importance`（0.5） | 元数据；**importance 直接进打分公式** |
| | `folderPath`（@Index，null=未分类） | 文件夹分类，如 `工作/项目A` |
| | `embedding`（EmbeddingConverter） | 向量嵌入，可空 |
| | `createdAt` / `updatedAt` / `lastAccessedAt` | 时间戳 |
| | `documentPath` / `isDocumentNode` / `chunkIndexFilePath` | 文档型记忆（外部文档分片） |
| | `tags`(ToMany) / `properties`(ToMany) / `links`(ToMany) / `backlinks`(Backlink) / `documentChunks`(Backlink) | 关系 |
| `MemoryTag` | `name` + 自关联 `parent` | **支持层级**的标签 |
| `MemoryLink` | `type`（默认 `related`）/ `weight`（1.0）/ `description` | 边；`source`→`target` |
| `MemoryProperty` | 任意 `key`/`value` | 灵活扩展元数据 |
| `DocumentChunk` | 文档分片 | 长文档按块存，可按 chunkIndex/chunkRange 读 |

**链接强度常量**（`MemoryRepository.kt:59-65`）：`STRONG_LINK=1.0`、`MEDIUM_LINK=0.7`、`WEAK_LINK=0.3`。

## 2. 记忆空间（MemorySpace）= 隔离的记忆库

`data/model/MemorySpace.kt`：
```kotlin
data class MemorySpace(
    val id: String,                          // 同时是 ObjectBox 数据库名
    val name: String,
    val profileAutoUpdateEnabled: Boolean = true,
    val profileAutoUpdateLocked: Boolean = false
)
```
- **每个记忆空间一个独立 ObjectBox 库** + 独立 SharedPreferences（`memory_search_settings_$profileId`）+ 独立向量索引（`memory_hnsw_${profileKey}_*.idx`）。
- 角色卡可绑定独立记忆空间 → 多角色隔离。
- **`user.md` 资料文档**：每个记忆空间有一份 Markdown 用户资料，由 `MemorySpaceProfileDocumentRepository` 管理，可**自动更新**（见 §5）。它会作为 `<user_profile>` 注入系统提示（见 `ref-operit-ai-engine.md` §2.1）。

## 3. 检索打分（第一步）

### 3.1 总分公式
```
S(m) = S_kw(m) + S_tag(m) + S_rev(m) + S_sem_norm(m) + S_graph(m)
```

**核心是 RRF（Reciprocal Rank Fusion）**，常量 `SEARCH_RRF_K = 60.0`（`MemoryRepository.kt:67`）：
```
computeRrfBaseScore(rank) = 1.0 / (60.0 + rank)
```

| 分量 | 公式 | 代码 |
|---|---|---|
| 关键词命中 | `RRF(rank) × importance × keywordWeight × 覆盖率增益` | `:1351-1366` |
| 标签命中 | 同上，用 `tagWeight` | `:1379-1394` |
| 反向包含 | `RRF(rank) × importance × keywordWeight` | `:1404-1413` |
| 语义 | `(RRF(rank) × √importance + sim × semanticWeight) × normFactor` | `computeSemanticWeightedScore:260-271` |
| 图谱传播 | `S(seed) × edgeWeight × W_edge + 0.03 × W_edge` | `:1476-1507` |

**覆盖率增益**（`SEARCH_KEYWORD_COVERAGE_BONUS = 0.6`）：
```
computeKeywordCoverageMultiplier = 1.0 + 0.6 × (命中片段数 / 总片段数)
```
**语义长度归一**：`normFactor = 1.0 / √(关键词数)` —— 避免「关键词多就天然高分」。

### 3.2 检索五阶段（`runSearchMemoriesWithDebug:1183-1596`）
1. **范围过滤**：folderPath（含「未分类」语义）+ 时间范围（createdAtStart/End）
2. **分词**：`|` 或空格切分 → `expandKeywordToken` 用 **Jieba 分词**扩召回 → 去重、按长度降序、**上限 32 个 token**
   - 支持通配：`error*timeout`；`query == "*"` 返回全部
   - 关键词阶段**直接在数据库做「标题包含片段」查询**（`queryTitleCandidatesByFragments:686`），不把全库拉进内存
3. **四路召回**：关键词(标题) → 标签 → 反向包含（查询文本包含记忆标题） → 语义（HNSW 索引，按关键词逐个 embedding）
4. **图谱传播**：取当前 **Top 10** 作为种子，沿 `links` + `backlinks` 双向传播，边权越高传得越多
5. **阈值过滤 + 排序**：`SEARCH_RELEVANCE_THRESHOLD = 0.025`，降序返回

### 3.3 打分模式与权重（可配）
`MemoryScoreMode`：`BALANCED` / `KEYWORD_FIRST` / `SEMANTIC_FIRST`，通过乘数调节（`resolveSearchWeights:229-233`）：

| 模式 | 关键词× | 语义× | 边× |
|---|---|---|---|
| BALANCED | 1.0 | 1.0 | 1.0 |
| KEYWORD_FIRST | 1.3 | 0.8 | 0.9 |
| SEMANTIC_FIRST | 0.8 | 1.3 | 1.1 |

默认权重：`keywordWeight=10.0`、`tagWeight=0.0`、`vectorWeight=≥0`、`edgeWeight=0.4`。
> ⚠️ `tagWeight` 与 `vectorWeight` 默认 **0**，即默认**关闭**标签与向量召回，纯关键词 + 反向包含 + 图谱。

### 3.4 调试能力
`MemorySearchDebugInfo` 记录全链路：`keywords` / `lexicalTokens` / 各阶段有效权重 / `keywordMatchesCount` / `semanticMatchesCount` / `graphEdgesTraversed` / `scoredCount` / `passedThresholdCount` / 每条候选的**分项得分**（keyword/tag/reverse/semantic/edge/total + passedThreshold）。
→ UI 里有「检索模拟」对话框可看这个。**这是很好的可观测性设计。**
> 注：`deduplicateBySemantics()` 在 `:1591` 被**注释掉**了（死代码）。

## 4. AI 如何决定「记什么」（第二步）

### 4.1 触发链路（自动保存）
1. 每轮 AI 回复结束 → `EnhancedAIService.finalizeAssistantResponse:2039-2063`：`if (enableMemoryAutoUpdate && !isSubTask && content.isNotBlank())` → `MemoryAutoSaveCandidateRepository.enqueue(chatId, timestamp)`
2. `MemoryAutoSaveCandidate`（`data/model/`）状态机：`pending` / `processing` / `failed`，带 `attemptCount` / `lastError`；来源两类：`reply_finalized_auto`（自动）/ `selected_user_message`（用户手动选中消息）
3. `MemoryAutoSaveScheduler`（轮询器，`api/chat/library/`）：
   - `LOOP_TICK_MS = 60s`，**默认间隔 5 分钟**（可配 1–30）
   - `MIN_TOTAL_CANDIDATES_TO_EXTRACT = 5` ← **候选不足 5 条就不提取，继续累计**
   - `MAX_MESSAGES_PER_BATCH = 48`、`MAX_CANDIDATES_PER_RUN_PER_CHAT = 20`
   - 按 `chatId` 分组，按时间排序，**分两批处理**（用户选中批次 / 自动批次），成功后删除候选，失败 `markFailed`
   - 用 **`FunctionType.MEMORY` 的独立模型配置**（`EnhancedAIService.getAIServiceForFunction(context, FunctionType.MEMORY)`）← 可配便宜模型

> 批处理阈值 5 条 + 5 分钟间隔，是为了**把多次琐碎对话攒成一批再交给模型**，省 token 且记忆质量更高。

### 4.2 提取前的本地预筛（**Hybrid Strategy: Local rough search + LLM final decision**）
`MemoryLibrary.generateAnalysis:556-677`：
1. 构造「问题中心」检索串 `buildCandidateSearchQuery:679`：`核心问题文本 + 精简解决方案(180字) + 最近 12 条消息(1200字)`，刻意剥离历史与工具回显噪声
2. 本地检索 → **`.take(15)`** 作为候选
3. `findAndDescribeDuplicates` —— **主动找出候选之间的重复并指示模型合并**
4. 拼装 system prompt：重复提示 + 现有记忆（标题+150字） + 现有文件夹列表 + 记忆空间资料文档 + **用户自定义提取规则**
5. 走 `FunctionType.MEMORY` 模型，流式收集 → `parseAnalysisResult`

### 4.3 提取提示词骨架（`FunctionalPrompts.buildKnowledgeGraphExtractionPrompt:1047`）
结构（英文版 `:1118-1199`，中文版 `:1201+`）：

1. **选入门槛（先执行）**
   - 只存**用户特定的可复用知识**：稳定偏好、约束、已确认决策、重复犯的错、项目事实、反复出现的世界观设定
   - **不存**常识/公开定义（"什么是 TypeScript"）
   - **不存**未来/推测项：下一步建议、TODO、试探性计划
   - 没有长期价值 → 返回 `{}`
2. **提取策略**
   - 提供的现有记忆**是检索提示不是证据**；只有对话明确确立同一主体+事实才 update/merge/link
   - **优先 `update`/`merge` 而非 `new`**；`new` 仅限真正新颖的概念（**最多 5 条**）
   - 语义重复判定：同 actor + 同 action + 同 outcome = 重复
   - 若现有记忆已覆盖本轮大部分事实 → 不要造平行 `new`
   - 现有记忆**可被直接操作**（即使本轮无 `new`）
3. **标题与内容写法**
   - `main` 标题**事件优先，而非定义优先**
   - 好标题：`[领域] 事件：动作 + 结果` / `实体：名称（角色/类型）`
   - 坏标题：`What is X`、`Definition of X`、百科式标题
   - 内容只写**已发生的事实和当前确认状态**，不写未来动作
4. **链接规则**
   - 只有对话证据明确支持才建边；**弱共现不建边**；不确定就不建
   - 推荐关系类型：事件流 `FOLLOWS`/`CORRECTS`/`UPDATES`；参与/场景 `INVOLVES`/`HAPPENS_AT`；世界观 `PART_OF`/`ALLIED_WITH`/`OPPOSES`
   - 输出前**必须两两检查所有涉及标题之间的关系**
5. **示例清单**（17 条正反例，如「常识问答→`{}`」「用户犯错并被纠正→存成 `main` 事件」「已存事件的重述→用 update/merge」）
6. **严格 JSON 输出协议**
   ```jsonc
   {
     "main":   null | {"title","content","tags":[],"folder_path"},
     "new":    [{"title","content","tags":[],"folder_path","alias_for":null}],
     "update": [{"title","content","reason","credibility":null,"importance":null}],
     "merge":  [{"source_titles":["A","B"],"title","content","tags":[],"folder_path","reason"}],
     "links":  [{"source","target","type":"UPPER_SNAKE_CASE","description","weight":0.0}],
     "profile_markdown": null | "完整替换 Markdown"
   }
   ```
   - 除 `{}` 外**必须包含全部键**；每项必须是**具名对象，禁止位置数组**
   - `credibility`/`importance`/`weight` 是 0.0–1.0 数字

**用户自定义规则**（`memory_extraction_custom_rules`）可细化领域/入库重点/文件夹/标签/写法，但**选入门槛、证据要求、JSON 协议不可覆盖**。

## 5. 写回记忆库（第三步）—— 顺序固定

`MemoryLibrary.saveMemory:313-551`，在 `mutex.withLock` 内：

**前置清洗**：
- 剥 `removeThinkingContent` / `stripGeminiThoughtSignatureMeta` / `pruneToolResultContent`（**工具输出与推理过程是执行痕迹，不是持久事实**）
- 用户消息先删 `<memory>...</memory>` 段
- 取最后一条 user 消息作为 `query`（无则跳过）

**资料文档更新**（先做）：`analysis.profileMarkdown` → `MemorySpaceProfileDocumentRepository.saveAutomatic`（**保留已有有效内容，返回完整替换文档**）

**空结果早退**：`main==null && new/update/merge/links 全空 && profileMarkdown==null` → 判定无需记忆，跳过写入

**写回顺序**：
1. **merge**（先合并，减少重复冲突）：`mergeMemories(sourceTitles, newTitle, newContent, newTags, folderPath)`
2. **update**：`findMemoryByTitle(titleToUpdate)` → `updateMemory(...)`（**目前不改标题**）
3. **main**：同名则更新内容，否则新建 `Memory(importance=0.8f, credibility=1.0f, folderPath)` + 逐个 `addTagToMemory`
4. **new entities**：
   - 若 `alias_for` 非空 → **LLM 识别为别名**，先查刚创建的 `createdMemories`，再查库；找到就**复用旧节点**（LLM 驱动的去重）
   - 找不到别名原主 → 降级为新实体
   - 否则新建 `Memory(source="memory_analysis", ...)`
   - `createdMemories[entity.title] = memory` —— 保证指向别名的链接能解析到规范节点
5. **links**（最后建边）：source/target 先在 `createdMemories` 找，再查库；**两端都找到才建边**，否则告警跳过

> 顺序的意义：先合并→再更新→再建主体与实体→最后连线，**每一步都建立在前一步已收敛的节点集上**，最小化重复与悬挂边。

**自动分类**（独立异步流程）：`autoCategorizeMemories` → `buildMemoryAutoCategorizePrompt` → 把「未分类记忆」补上文件夹路径。**只影响组织方式，不改变「该不该入库」这个决定。**

## 6. 手动重建（历史补建）

`docs/TODO/windowed_memory_rebuild_20260813/`：
- 入口：设置 → 聊天记录管理 → 选一个或多个会话 + 指定窗口大小 → 顺序重建
- `ChatMemoryWindowPlanner.plan:16-74`：窗口 **8–48 条（默认 32）**，以 user 轮为界切窗；群聊回复多于窗口时，**把触发该轮的 user 消息作为下一窗口的上下文重复带上**，保证每个请求有界且每条回复都不丢
- `ChatMemoryRebuildManager` 逐窗复用同一套「图谱提取 + 去重 + 合并 + 资料更新」逻辑
- **`summary` 消息不参与记忆提取**；单窗失败继续其余窗口并累计失败数；支持取消
- 验收要求：`new`/`update`/`merge`/`links` **不依赖 `main` 节点存在**

## 7. 配置面（记忆库设置）

`MemorySearchSettingsPreferences`（**按 profileId 隔离**）+ UI `dialogs/MemorySearchSettingsDialog.kt`（5 组）：

| 组 | 配置项 | 默认 |
|---|---|---|
| **搜索权重** | 打分模式；关键词/标签/向量/边 四滑块 | BALANCED；10 / 0 / 0 / 0.4 |
| **自动保存** | 自动保存间隔（1–30 分钟）；**记忆提取附加规则**（自由文本） | 5 分钟；空 |
| **云端嵌入** | 开关 / endpoint / apiKey / model | 关闭 |
| **维度用量** | 向量维度摘要 + 重建索引（分阶段进度） | — |
| **调试工具** | 检索模拟（看 `MemorySearchDebugInfo`） | — |

**记忆空间管理**：`MemorySpace` 的 `profileAutoUpdateEnabled` / `profileAutoUpdateLocked` 控制资料文档是否自动更新。

## 8. AI 在对话中如何使用记忆

- **主系统提示里没有记忆注入段**。记忆只在 `AVAILABLE_TOOLS` 里以**两个只读工具**出现（`SystemToolPrompts.kt:427-455`）：
  - `query_memory`（含 `threshold` 参数，默认 0）
  - `get_memory_by_title`
  - 工具说明末尾附注：*「记忆库和用户人格资料可能在当前回复结束后自动更新；如需立即管理记忆或更新用户偏好，请直接使用相应工具。」*
- **写入不由对话模型决定** —— 由异步图谱提取负责（§4）。对话模型只能读。
- **脚本侧有完整 CRUD**：`Tools.Memory.*`（`memory.d.ts`）—— query / getByTitle / create / update / deleteMemory / move / link / queryLinks / updateLink / deleteLink。
  - `query()` 支持 **`snapshotId` 分页去重**：复用同一 snapshotId 的多次查询会自动排除已返回过的记忆，返回 `excludedBySnapshotCount`。**这是很实用的分页设计。**
- **对话历史的摘要与记忆是两套独立机制**（见 `ref-operit-ai-engine.md` §2.2）。

## 9. 可迁移的设计点（对 SOrders 的参考）

| # | 设计点 | 为什么值得借鉴 |
|---|---|---|
| 1 | **「本地粗筛 + LLM 终判」混合** | 不给模型全库，只给 top-15 候选；token 可控且召回由本地保证 |
| 2 | **固定顺序写回**（merge→update→main→new→links） | 天然抑制重复与悬挂边，比「模型说啥写啥」稳得多 |
| 3 | **`update`/`merge` 优先于 `new`** 写进提示词 | 直接对抗「记忆库越用越膨胀」 |
| 4 | **别名（alias_for）去重** | 让 LLM 显式指出「这是同一个东西」，比字符串相似度可靠 |
| 5 | **图谱传播打分** | 命中一个节点能带出其关联记忆，适合「订单↔货主↔司机」这类天然有关系的业务数据 |
| 6 | **记忆空间隔离** | 多角色/多租户场景直接复用 |
| 7 | **独立的 MEMORY 功能模型** | 记忆提取用便宜模型，对话用强模型，成本可控 |
| 8 | **批处理阈值（≥5 条才提取）** | 摊薄模型调用成本，且让提取有足够上下文 |
| 9 | **全链路打分调试信息** | 检索效果不好时能定位是哪个分量出问题 |
| 10 | **snapshotId 分页去重** | 多次查询不重复返回，适合「先看 5 条，不够再取」 |
| 11 | **记忆是图谱（节点+边），不是扁平片段** | 业务知识天然是关系型的 |
| 12 | **快照去噪**：工具输出/推理过程不入记忆 | 避免把执行痕迹当持久事实 |

## 10. 未验证项
1. `deduplicateBySemantics` 被注释掉的原因与是否计划恢复。
2. HNSW 向量索引的实现细节（`util/vector/VectorIndexManager`）未细读。
3. 云端嵌入服务的具体 provider 兼容性。
4. `MemoryQueryToolExecutor`（1275 行）只看了接口层，参数校验与快照逻辑未逐行核对。
5. 行号基于 HEAD `b2c7610`。
