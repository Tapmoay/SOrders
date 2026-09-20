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
| [**09_DEV_ONLY_INDEX.md**](09_DEV_ONLY_INDEX.md) | **开发期专用信息索引**：AI key / 本地测试账号 / 凭据文件 / 测试数据 —— 各自在哪、**上线前按表删或换**。⚠️ 只写"有什么、在哪"，**不写密钥值**（仓库是公开的） | 交付/上线前，或"某把 key 放哪了"时查它 |

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