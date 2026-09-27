# SOrders 项目地图（索引）

> **给下一个完全不知情的 AI 的快速上手入口**。读完本索引 + 按需翻对应文档，即可对项目形成全景认知。
> 本目录与 2026-09-04 时的代码状态对齐（分支 `p`，最近 commit `fffd66c`）。
>
> ⚠️ **新鲜度提醒**：`01~07` 对齐的是 2026-09-04；此后代码持续演进（工作区有大量未提交改动）。
> 若发现文档与实际代码不符，**以代码为准**，并顺手修正文档——**过期地图比没有地图更糟**，
> 因为读文档的 agent 会直接相信结论而不再核实。
> `08_CODE_LOCATOR.md` 与 `DOMAIN_MODEL.md` 较新（**2026-09-19** 审计期间更新过）。

---

## 📂 文档导航

| 文档 | 内容 | 什么时候看 |
|---|---|---|
| [01_ARCHITECTURE.md](01_ARCHITECTURE.md) | 三端架构（后端/旧H5前端/Android）、技术栈、数据流、启动方式、目录全景 | 一开始必读 |
| [02_BACKEND_API.md](02_BACKEND_API.md) | 后端接口**速览**（核心模块逐条 + 其余按模块概述，讲业务作用与参数），Socket.IO 事件。⚠️ **要逐端点清单查 08A** | 改后端/联调必读 |
| [03_BACKEND_DETAILS.md](03_BACKEND_DETAILS.md) | 后端代码结构（app/ 分层）、数据模型、关键服务、权限体系、导出/异步任务 | 深入后端时读 |
| [04_ANDROID_MAP.md](04_ANDROID_MAP.md) | Android 端页面/ViewModel/导航/工具类全景、构建命令、网络层、真实设备连接 | 改 Android 必读 |
| [05_TESTING.md](05_TESTING.md) | 测试手册：模拟器/账号/测试数据/常用命令/自动化工具/已知坑 | 任何验证/测试前必读 |
| [06_DESIGN_SYSTEM.md](06_DESIGN_SYSTEM.md) | UI 设计与语义色体系（一色一功能）、组件风格、用户偏好 | 改 UI 必读 |
| [07_END_TO_END_FLOW.md](07_END_TO_END_FLOW.md) | 三端互通端到端流程：下单→派单→接单→送达→入账的完整链路、消息事件表、各角色职责、状态机 | 理解业务流转必读 |
| [**08_CODE_LOCATOR.md**](08_CODE_LOCATOR.md) | **代码定位表：需求 → 该改哪几个文件**（后端 + Android 分组，含危险区、跨层配方与"找不到文件"误区）。**按业务域跳读，别通读** | **接手任何"改某功能"的需求，第一站就是这里** |
| [**08A_ENDPOINT_INDEX.md**](08A_ENDPOINT_INDEX.md) | **端点索引（机器生成，勿手改）**：全部 URL → handler → 精确行号 → 授权列；含权限点反查、重复路由/公开端点的风险清单。**先 grep，别通读** | 问"**这个 URL 落在哪个函数 / 谁能调**"时查它 |
| [**../BASELINE.md**](../BASELINE.md) | **真实世界基线（机器生成，勿手改）**：本地 + 生产的实测数字（端点/表/用例/检查数、库行数、磁盘、证书、备份数），以及与评审报告成文时的逐项对照、机器判定的漂移清单 | 想知道"**现在到底是什么样**"时；重构前后的对照基准 |
| [**../RECTIFICATION_PLAN.md**](../RECTIFICATION_PLAN.md) | **架构整改执行表**：分阶段（基线→备份恢复→迁移版本化→CI→API 搬迁→硬边界…）的做什么 / 改不改业务逻辑 / 状态 / 证据 | 接着做整改时**先读这一页**，别从报告原文重新推一遍 |
| [**../ARCHITECTURE_RECTIFICATION.md**](../ARCHITECTURE_RECTIFICATION.md) | 外部评审报告**原文存档**（逐字，不改一字）。⚠️ 里面的数字是成文当时的快照，实测以 BASELINE 为准 | 想知道"报告当初到底怎么说的" |
| [**09_DEV_ONLY_INDEX.md**](09_DEV_ONLY_INDEX.md) | **开发期专用信息索引**：AI key / 本地测试账号 / 凭据文件 / 测试数据 —— 各自在哪、**上线前按表删或换**。⚠️ 只写"有什么、在哪"，**不写密钥值**（仓库是公开的） | 交付/上线前，或"某把 key 放哪了"时查它 |
| [**../DEVELOPMENT_SPEC.md**](../DEVELOPMENT_SPEC.md) | **开发规范 v1.0（⛔ 开工前必读）**：四种 ID（FEAT / CHG / BUG / GOV）、开工六问、Must Change / Must Not Change、边界五问、Blast Radius L0–L3、四件事测试、证据格式、DoD、关闭六格。每条规则都标注了**本仓库落点**与**有没有机器判据** | **动手之前**；判据 `python _tools/qa/_check_dev_spec.py` |
| [**../changes/README.md**](../changes/README.md) | **开发事项登记簿**：一个事项 = 一个文件 = 一个 ID（目录即台账，没有第二份手写清单） | 立项 / 找自己的事项号时 |
| [../changes/_TEMPLATE.md](../changes/_TEMPLATE.md) | 事项定义模板（F0）：六问 / 边界 / 行为契约 / 数据契约 / CHG 专章 / 测试 / 证据 / 关闭六格 | 开新事项时**复制它** |

---

## ⚡ 60 秒速览

- **这是什么**：派单送货系统（SOrders）。角色 = 货主（下单）→ 派单员（派单/运营/报表）→ 司机（接单送货/收款）
- **三端**：`backend/`（FastAPI + Socket.IO，同进程）｜`frontend/`（Vue3 旧 H5，已边缘化）｜`android/`（Kotlin + Compose 主客户端）
- **开发环境**：Windows 本机 + SQLite（`backend/sorders.db`）+ uvicorn:8000 + 3 台 Android 模拟器（5554 派单员 / 5556 货主 / 5558 司机）
- **关键路径**：
  - 后端启动：`cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`
  - Android 构建：`dev-build.ps1`（模拟器包，跑 `:app:assembleEmuDebug`）；真机包 `:app:assemblePhoneDebug`
  - 健康检查：`GET http://127.0.0.1:8000/health`
- **测试账号**：`13800000001/13800000002/13800000003`，密码均 **`123321`**（派单员/货主/司机）。
  ⚠️ 2026-09-19 实测更正：本索引原来写的 `pass12345` **是错的**（那是单测里新建账号用的密码，不是预置账号的）。
- **当前分支**：`p`（长期功能分支）；版本 0.2.0

## 🔑 最重要的事（防止踩坑）

1. **模拟器必须走 10.0.2.2 访问本机后端**，真机才用局域网 IP（`ApiEndpoint.kt` 已自动处理，模拟器检测自动切换）。
2. **电脑 IP 会变**：重启后真机连接的 local.properties 的 `api_base_url` 需要同步更新。
3. **后端 .py 改动必须重启 uvicorn** 才生效。
4. **高德地图 SDK 9.8.3 在 Android 16 arm64 上 onDestroy 必然崩溃**——地图对象做成单例永不销毁。
5. **Android 11+ 包可见性**：`resolveActivity()` 对未声明包返回 null，导航直拉 App 要用 `setPackage`。
6. **报表毛利口径**：仅按有 `cost_price_snapshot` 的订单行计算，前端必须带覆盖率说明，否则毛利虚高。
7. **文件修改必须先用 read 读过**（沙箱策略）；工具只能经由 `run_code` 调 `tools.xxx()` 间接使用。

## 🧪 快速自检清单（新 AI 接手先跑一遍）

1. `GET /health` → ok
2. 登录 13800000001 → 拿 token
3. `GET /api/v1/reports/turnover?mode=day&date=2026-09-03` → 有数据
4. adb devices → 3 台模拟器在线
5. 模拟器打开 App → 派单员工作台 14 模块可见
6. `adb shell am force-stop com.tapmoay.sorders` 后可重启并保留登录态

---

## 🔍 审计与交接（2026-09-19，**未提交的大改动都在这里**）

工作区当前有大量未提交改动，其中**很大一部分来自一轮全系统漏洞审计**（第十七～二十轮）。
接手前先看这一节，否则你会把"审计改过的代码"当成现状的偶然。

| 文档 | 内容 | 什么时候看 |
|---|---|---|
| [**../../_archive/audit/HANDOVER.md**](../../_archive/audit/HANDOVER.md) | **交接文档**：①我改了哪些代码、为什么；②我知道但**没改**的（等拍板的产品决策 + 已确认排在后面的缺陷）；③我**没探查**的范围（性能/生产库/压测/无障碍/部分页面…） | **接手这个仓库的第一份该读的审计文档** |
| [../../_archive/audit/FINDINGS.md](../../_archive/audit/FINDINGS.md) | **逐轮审计台账**（第一～十九轮）：每轮的缺陷、证据（`文件:行号`）、修法、反向验证结果；文末有 **`## 待拍板` 15 条产品决策**与 P0/P1/P2 分类表 | 想知道"某条缺陷当初怎么定的"时查它 |
| [DOMAIN_MODEL.md](../DOMAIN_MODEL.md) §1 | 订单状态机（**五态** + 「每档允许什么动作」表，逐条注明后端出处） | 改任何跟订单状态有关的东西前必读 |

**验收入口（一条命令）**：

```powershell
python _tools/qa/_check_all.py            # 静态红线（清单自动发现；条数以它自己打印的为准）
python _tools/ai/_reverse_verify_all.py   # 反向验证（证明红线真的会红；份数以它自己打印的为准，2026-09-19 实测 49 份）
cd backend;  python -m pytest -q          # 397 passed
cd android;  & $gradle :app:testEmuDebugUnitTest   # 733 passed
cd frontend; npm install; npm run build   # vue-tsc + vite（H5 本轮才第一次能跑）
```

> ⚠️ 两条纪律：**跑反向验证时不要改源码**（它按开跑前快照写回）；跑完它 `_check_backend_fresh.py`
> 必然报红（还原刷新了 mtime），按提示重启本机 uvicorn 即可。被中断时用
> `python _tools/ai/_recover_injections.py` 还原现场。

---

## 📅 最近演进（git log 主线）

- `fffd66c` 报表中心增强：6 入口 + 导出 Excel + 商品信息分层
- `5eb65c9` 报表中心重构：参考图样式入口页 + 四聚合报表
- `04fa161` ApiEndpoint 模拟器自动 10.0.2.2（修复电脑 IP 变更导致全端超时）
- …（更早见 git log）

## 🗂️ 参考文档与归档（仓库既有）

**当前有效**：

- [PROJECT_OVERVIEW.md](../PROJECT_OVERVIEW.md) — 三端职责、主流程、技术栈
- [DOMAIN_MODEL.md](../DOMAIN_MODEL.md) — 订单状态机、权限矩阵、派单员审计字段
- [INTEGRATIONS.md](../INTEGRATIONS.md) — 高德、导出、WebSocket/消息队列、消息中心、离线队列
- [requirements.md](../../requirements.md) — 需求原文
- [AGENTS.md](../../AGENTS.md) — 仓库约定与协作协议（四象限协议见 `~/.dsh/AGENTS.md`）

**历史归档 —— 记载决策过程，不是现状，别当参考读**：

> ⚠️ 这些文档**写于实现之前**，其中的"待实现/未实现/计划中"**大概率已经过期**。
> 它们的唯一价值是**当时的取舍理由**（代码里读不出来）；要了解现状请查 `08` / `08A` / `03`。
> 保留而不删除，是因为决策理由丢了就找不回来；但**读之前先假设它的状态描述是错的**。

| 文档 | 性质 | 核实过的现状 |
|---|---|---|
| [ACCOUNTING_V2_DESIGN.md](../ACCOUNTING_V2_DESIGN.md) | 账本 V2 设计定稿（D1-D8 决策） | ⚠️ **原文写"未实现"，实际已实现**——见该文件顶部状态更新 |
| [IMPLEMENTATION_PLAN_ACCOUNTING_V2.md](../IMPLEMENTATION_PLAN_ACCOUNTING_V2.md) | 账本 V2 P0 实施方案 | 同上，代码已落地（`accounting_service.py` 等） |
| [plan-driver-freight.md](../plan-driver-freight.md) | 司机分类计费 · 业务计划 | 已实现（`driver_billing_mode` 快照链路） |
| [implementation-driver-freight.md](../implementation-driver-freight.md) | 司机分类计费 · 落地方案 | 已实现 |
| [review-implementation-driver-freight.md](../review-implementation-driver-freight.md) | 对上述方案的逐条评审 | 评审意见已采纳并落地 |
| [UI_DESIGN_AGENT_BRIEF.md](../UI_DESIGN_AGENT_BRIEF.md) | UI 设计性格说明书 | 已被 [06_DESIGN_SYSTEM.md](06_DESIGN_SYSTEM.md) 取代 → **读 06，别读它** |

**本目录下的历史报告**（按时间倒序，多为一次性验证记录）：

| 文档 | 性质 |
|---|---|
| [102_OFFLINE_DATA_ARCHIVE_DESIGN.md](102_OFFLINE_DATA_ARCHIVE_DESIGN.md) | 离线数据归档设计 |
| [101_MULTI_ROLE_120_USERS_REPORT.md](101_MULTI_ROLE_120_USERS_REPORT.md) | 120 用户多角色压测 + 数据清理记录 |
| [100_SERVER_DEPLOY_TEST_REPORT.md](100_SERVER_DEPLOY_TEST_REPORT.md) | 服务器部署验证报告 |
| [99_STRESS_TEST_REPORT.md](99_STRESS_TEST_REPORT.md) | 压测报告 |

---

## 打包、发布与应用内更新

**要让用户拿到一个新版本时读这份**。开发现状：生产上跑的是 **debug 构建**（用公共 debug keystore 签名）。

| 文档 | 性质 | 什么时候看 |
|---|---|---|
| [**../APP_UPDATE_AND_RELEASE.md**](../APP_UPDATE_AND_RELEASE.md) | **打包 / 推送 / 应用内更新全链路**：ABI 分流（74.5→47.4MB）、versionCode 一套量纲、`publish_apk.py` 的版本号闸门、FileProvider 根目录与「安装未知应用」两道闸、模拟器实测记录、待决策项（release 签名 / 只留 arm64 / 提高 EIP 带宽） | 发版、改 `build.gradle.kts`、改更新流程前必读 |
| `../_tools/deploy/` | 工具：`publish_apk.py`（推生产）、`_check_update_flow.py`（31 项红线）、`_stage_local_update.py`（模拟器造假更新）、`_fix_nginx_static.py`（nginx 直出 `/static/uploads/`） | 执行发版 / 排查更新问题时 |

---

## AI 助手（派单员端）

派单员端内置的「AI 助手」——**用户自带 LLM key，agent 循环跑在手机上，工具调用本公司后端**。第一阶段**只读**（不注册任何写工具）。入口是**底部导航正中间那个凸起的圆形按钮**（不在工作台网格里）。

| 文档 | 性质 | 什么时候看 |
|---|---|---|
| [**../AI_ASSISTANT_PLAN_V3.md**](../AI_ASSISTANT_PLAN_V3.md) | **当前方案（v3.4）**：定位、四个缺口端点、6 个工具面、安全与机制、实施顺序；**§13 对话历史/分支/去编号/造数、§14 界面与多厂商、§15 模型栏/思考强度/上下文预算（窗口自动推断+自愈）/使用习惯、§16 模型栏进顶栏 + 读所有列表（36 张表的通用读工具）、§17 消息「编辑」取代「重问」+ 目录两处缺口**；含 **16 条自我纠正记录**与三轮独立审查的裁决 | 改 AI 助手前必读 |
| [../AI_ASSISTANT_PLAN.md](../AI_ASSISTANT_PLAN.md) | ⚠️ **历史版本（v2）**，**不是当前方案**。保留原因：它记录了判据错误、证据链误用、"表单预填"被推翻等完整案例（"读 schema 就下结论"的反面教材） | 只在追溯决策过程时读 |
| [../ai/kb_skeleton.md](../ai/kb_skeleton.md) | **机器生成的端点清单骨架**（`_tools/ai/_gen_ai_toolmap.py` 产出）。⚠️ **不是给用户的"大白话文档"**——它缺"UI 入口路径"列，对零基础用户无用；文件头已写明这一点 | 做「用户话术 → UI 入口」映射时的底稿 |
| [../ai/ai-gap-vs-operit.md](../ai/ai-gap-vs-operit.md) | **与 Operit 的差距对照 + 优化清单**（真缺口 / 可优化 / 已领先三分类）。基线是**本仓** `ai/` 目录，所以留在 `docs/`，不是外部笔记 | 规划 AI 下一批改动、判断"还差什么"时读 |
| [../../_tools/ai/notes/README.md](../../_tools/ai/notes/README.md) | **外部参考笔记的入口**（更早的能力规划 + 对 Operit 仓库的 4 份代码考古）。⚠️ 引用的是**另一个仓库**的路径，本仓校验不到，所以放在 `_tools/ai/notes/` 而不是 `docs/` | 只在追溯"某个机制当初为什么这么设计"时读 |

**代码入口**：Android 端位于 `android/app/src/main/java/com/tapmoay/sorders/` 下的 ai/（agent 循环 `AiAgentLoop.kt`、5 个只读工具 `AiTools.kt`、答复渲染解析 `AiMarkdown.kt`、厂商预设 `AiProviders.kt`）与 ui/ai/（`AiChatScreen.kt`、`AiRichText.kt`、`AiSettingsScreen.kt`）；底部导航中央圆钮在 `android/app/src/main/java/com/tapmoay/sorders/ui/home/RoleHomeScreen.kt`；工具与路由的行级指引见 [08_CODE_LOCATOR.md](08_CODE_LOCATOR.md) 的「AI 助手」行。

---

## 📚 全量文档目录（2026-09-27 补）

> **为什么有这一节**：`python backend/scripts/check_reachability.py` 实测报出
> **39 份孤儿文档** —— 从 `AGENTS.md` 出发**图遍历走不到**它们。
> 后果不是"没人读"，而是**"对新会话等于不存在"**：写的人做完就走了，
> 下一个会话从入口冷启动，磁盘上的东西对它是一片空白。
> ⛔ 按 §"可达性"的纪律：**找不到**和**知道它不该读**是两回事 ——
> 历史归档**也要链过来**，只是要注明状态。

### A · 开发流程与治理（**当前有效**）

| 文档 | 内容 | 什么时候看 |
| --- | --- | --- |
| [**../DEVELOPMENT_SPEC.md**](../DEVELOPMENT_SPEC.md) | **开发规范 v1.0**：一个事项从立项到关闭的全流程 | **动手之前** |
| [../changes/README.md](../changes/README.md) | 事项登记簿（四种 ID） | 立项时 |
| [../changes/_TEMPLATE.md](../changes/_TEMPLATE.md) | F0 模板 | 开新事项时 |
| [../changes/GOV-0001.md](../changes/GOV-0001.md) | 第一个事项：把规范写进仓库并接线 | 想知道"这套规矩怎么来的" |

### B · 架构边界（**当前事实**，判据机器可核）

| 文档 | 内容 | 什么时候看 |
| --- | --- | --- |
| [../R4_CORE_EXTENSION_MAP.md](../R4_CORE_EXTENSION_MAP.md) | **核心 / 扩展边界图**：47 张表归属、扩展点、事件、五问判定表、15 个施工禁区各自落在哪条判据 | 判 Core 还是 Extension 时 |
| [../R4_CONTRACTS.md](../R4_CONTRACTS.md) | **四类扩展契约**：UnitConversionContract v1 / PricingContract v1→v2（输入 / 输出 / 错误 / 不变量 / 兼容 / 生命周期） | 写扩展实现时 |
| [../R4_EXTENSIONS.md](../R4_EXTENSIONS.md) | **扩展区**：manifest 字段、注册表、`EXT_*` 配置、模块依赖图、⛔ 扩展不许做的事 | 加一个扩展时 |
| [../DOMAIN_BOUNDARIES.md](../DOMAIN_BOUNDARIES.md) | **领域边界地图**（R2-01 产物） | 问"这块归谁"时 |
| [../BUSINESS_TRANSACTION_MAP.md](../BUSINESS_TRANSACTION_MAP.md) | **跨域事务地图**（R2-03 产物）：Order / Money / Inventory / Settlement 之间谁跟谁必须一起动 | 一个功能要同时碰多个域时 |
| [../MONEY_DEPENDENCY_GRAPH.md](../MONEY_DEPENDENCY_GRAPH.md) | **钱的依赖图**：钱契约的统一依赖方向 | 改钱相关代码时 |

### C · 依赖、就绪与验收口径

| 文档 | 内容 | 什么时候看 |
| --- | --- | --- |
| [../DEPENDENCY_DECISION.md](../DEPENDENCY_DECISION.md) | **依赖可复现性：证据与待拍板**（开区间 vs pin、三处版本是否一致）⚠️ 其中"待拍板"项以该文件当前状态为准 | 动依赖 / 版本时 |
| [../MULTI_INSTANCE_READINESS.md](../MULTI_INSTANCE_READINESS.md) | **多实例 / HA 就绪度**：什么时候才考虑多实例，前置条件是什么 | 讨论扩容 / 多实例时 |
| [../PRODUCTION_ACCEPTANCE.md](../PRODUCTION_ACCEPTANCE.md) | **生产只读验收清单**（R3-05-C）：/health、登录、查订单、查账、司机账单、通知、trace、Capability | 上线前逐条核 |
| [../CAPABILITY_AUDIT_COVERAGE.md](../CAPABILITY_AUDIT_COVERAGE.md) | **能力 ↔ 审计覆盖**（⚠️ **机器生成，勿手改**：`python _tools/ai/_gen_capability_snapshot.py`） | 核"某个能力有没有审计"时 |

### D · 计价链路（**当前生产在跑的就是这条**）

| 文档 | 内容 | 什么时候看 |
| --- | --- | --- |
| [../R4_PRICING_PROVENANCE.md](../R4_PRICING_PROVENANCE.md) | **计价事实审计**：一个订单最终用的"计价规则版本"留在哪 | 改计价 / 排查某个金额"凭什么"时 |
| [../R4_GOLDEN_SET.md](../R4_GOLDEN_SET.md) | **计价回归语料集**：从真实订单抽的脱敏样本 | 改计价算法前 |
| [../R4_SHADOW.md](../R4_SHADOW.md) | **Shadow 对照**：真实订单、只读、⛔ 不写 Ledger | 想证明"新算法没有漂移"时 |
| [../R4_CANARY_WINDOW.md](../R4_CANARY_WINDOW.md) | **Canary 观察窗口（预注册）**：九条判据 + 四个常量。⚠️ 窗口 = Natural Observation，**上线后才激活**；本文件是**改之前**写的 | 动 Canary / 观察口径时 |

### E · 整改台账与报告（**历史** —— "为什么这么做"在这里，但别当现状读）

> ⚠️ 这些文档写于各轮整改**当中**。它们的**结论**仍然有效，但**状态描述**要打折扣：
> 现在的接口/表/数字以 `08` / `08A` / `03` / `BASELINE.md` 与代码为准。

| 文档 | 内容 |
| --- | --- |
| [../R4_PROGRESS.md](../R4_PROGRESS.md) | R4 第四轮台账（条目最全，"已完成"三个字的唯一出处） |
| [../R4_CONTROLLED_VALIDATION.md](../R4_CONTROLLED_VALIDATION.md) | R4-49 受控生产验证的方案与覆盖账 |
| [../R4_FINAL_REVIEW.md](../R4_FINAL_REVIEW.md) | R4 收尾七问与裁决（含 Natural Observation 推迟到上线后的记录） |
| [../R4_EVIDENCE_INDEX.md](../R4_EVIDENCE_INDEX.md) | **一页证据索引**：结论 → 真实文件 → 能重跑的入口（照着这个格式写新证据） |
| [../R4_BASELINE.md](../R4_BASELINE.md) | R4 期间采的真实世界基线快照（当前基线见 [../BASELINE.md](../BASELINE.md)） |
| [../R3_PROGRESS.md](../R3_PROGRESS.md) | R3 第三轮台账与退出条件 |
| [../R3_CONSTRAINTS.md](../R3_CONSTRAINTS.md) | R3 要点与**禁做清单**（机器可核对） |
| [../R3_DECISIONS.md](../R3_DECISIONS.md) | R3 架构决策记录（先决策、再开发） |
| [../RECTIFICATION_REPORT_R3.md](../RECTIFICATION_REPORT_R3.md) | R3 完整报告（唯一权威是台账） |
| [../RECTIFICATION_REPORT_R2.md](../RECTIFICATION_REPORT_R2.md) | R2 完整报告 |
| [../RECTIFICATION_REPORT.md](../RECTIFICATION_REPORT.md) | 2026-09-25 那一轮的变更报告（**快照，不是活文档**） |
| [../RELEASE_CANDIDATE.md](../RELEASE_CANDIDATE.md) | R3 发布候选记录（Git SHA / migration / 版本号） |
| [../ARCHITECTURE_RECTIFICATION_R2.md](../ARCHITECTURE_RECTIFICATION_R2.md) | R2 **方向指南原文存档**（逐字） |
| [../ARCHITECTURE_RECTIFICATION_R3.md](../ARCHITECTURE_RECTIFICATION_R3.md) | R3 方向指南原文存档（逐字） |
| [../ARCHITECTURE_RECTIFICATION_R4.md](../ARCHITECTURE_RECTIFICATION_R4.md) | R4 方向指南原文存档（逐字） |

### F · 原始证据（**只放事实，不放结论**）

> ⛔ 读这一组的心法：**结论在上面 E 组的台账里**；这里放的是**跑出来的原始输出**。
> 别把这里的片段当结论引用 —— 结论要回到它对应的台账条目。

| 文档 | 内容 |
| --- | --- |
| [../R3_PROD_READONLY_EVIDENCE.md](../R3_PROD_READONLY_EVIDENCE.md) | 生产**只读**核对证据（版本 / 依赖 / migration / DB / Redis / nginx / uploads / trace） |
| [../R3_A_RELEASE_EVIDENCE.md](../R3_A_RELEASE_EVIDENCE.md) | R3 A 段（生产发布）逐步原始输出 |
| [../R3_B_MULTIINSTANCE_EVIDENCE.md](../R3_B_MULTIINSTANCE_EVIDENCE.md) | R3 B 段（多实例运行时）逐步原始输出 |
| [../R3_RUNTIME_EVIDENCE.md](../R3_RUNTIME_EVIDENCE.md) | 双实例实验的当场结果，以及**这个环境证不了什么** |
| [../R3_RESTORE_VERIFICATION.md](../R3_RESTORE_VERIFICATION.md) | 备份隔离恢复验证（恢复出来的库真的能用吗） |
| [../R3_FAILURE_DRILL.md](../R3_FAILURE_DRILL.md) | 生产故障演练**方案**（五个演练） |
| [../R3_FAILURE_DRILL_EVIDENCE.md](../R3_FAILURE_DRILL_EVIDENCE.md) | 生产故障演练**证据**（真跑过的原始记录，含抓到 P1 的那次） |

### G · 界面与提示

| 文档 | 内容 |
| --- | --- |
| [../HINT_STYLE.md](../HINT_STYLE.md) | 界面「提示与说明」书写规范（三端通用） |
| [09A_HINT_CATALOG.md](09A_HINT_CATALOG.md) | 界面提示与说明**目录**（⚠️ **机器生成，勿手改**：`python _tools/qa/_hint_inventory.py --md`） |

### H · 方案与设计稿（**未拍板 / 待执行**）

| 文档 | 内容 |
| --- | --- |
| [../plan-product-management.md](../plan-product-management.md) | 商品管理改版方案（3 期，第 1 期零后端零数据库）。⚠️ **状态以该文件顶部为准** |

> **验收**：`python backend/scripts/check_reachability.py` 必须报 **孤儿 0 份**。
> 新写一份文档却忘了接到这里 → 它会红。这就是"找不到"和"知道它不该读"的区别被机器守住的地方。