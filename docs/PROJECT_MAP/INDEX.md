# SOrders 项目地图（索引）

> **给下一个完全不知情的 AI 的快速上手入口**。读完本索引 + 按需翻对应文档，即可对项目形成全景认知。
> 本目录与 2026-09-04 时的代码状态对齐（分支 `p`，最近 commit `fffd66c`）。

---

## 📂 文档导航

| 文档 | 内容 | 什么时候看 |
|---|---|---|
| [01_ARCHITECTURE.md](01_ARCHITECTURE.md) | 三端架构（后端/旧H5前端/Android）、技术栈、数据流、启动方式、目录全景 | 一开始必读 |
| [02_BACKEND_API.md](02_BACKEND_API.md) | 全部 REST 接口清单（按模块分组 + 路径/方法/权限/作用），Socket.IO 事件 | 改后端/联调必读 |
| [03_BACKEND_DETAILS.md](03_BACKEND_DETAILS.md) | 后端代码结构（app/ 分层）、数据模型、关键服务、权限体系、导出/异步任务 | 深入后端时读 |
| [04_ANDROID_MAP.md](04_ANDROID_MAP.md) | Android 端页面/ViewModel/导航/工具类全景、构建命令、网络层、真实设备连接 | 改 Android 必读 |
| [05_TESTING.md](05_TESTING.md) | 测试手册：模拟器/账号/测试数据/常用命令/自动化工具/已知坑 | 任何验证/测试前必读 |
| [06_DESIGN_SYSTEM.md](06_DESIGN_SYSTEM.md) | UI 设计与语义色体系（一色一功能）、组件风格、用户偏好 | 改 UI 必读 |
| [07_END_TO_END_FLOW.md](07_END_TO_END_FLOW.md) | 三端互通端到端流程：下单→派单→接单→送达→入账的完整链路、消息事件表、各角色职责、状态机 | 理解业务流转必读 |

---

## ⚡ 60 秒速览

- **这是什么**：派单送货系统（SOrders）。角色 = 货主（下单）→ 派单员（派单/运营/报表）→ 司机（接单送货/收款）
- **三端**：`backend/`（FastAPI + Socket.IO，同进程）｜`frontend/`（Vue3 旧 H5，已边缘化）｜`android/`（Kotlin + Compose 主客户端）
- **开发环境**：Windows 本机 + SQLite（`backend/sorders.db`）+ uvicorn:8000 + 3 台 Android 模拟器（5554 派单员 / 5556 货主 / 5558 司机）
- **关键路径**：
  - 后端启动：`cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`
  - Android 构建：`dev-build.ps1`（或 gradle `:app:assembleDebug`）
  - 健康检查：`GET http://127.0.0.1:8000/health`
- **测试账号**：`13800000001/13800000002/13800000003`，密码均 `pass12345`（派单员/货主/司机）
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

## 📅 最近演进（git log 主线）

- `fffd66c` 报表中心增强：6 入口 + 导出 Excel + 商品信息分层
- `5eb65c9` 报表中心重构：参考图样式入口页 + 四聚合报表
- `04fa161` ApiEndpoint 模拟器自动 10.0.2.2（修复电脑 IP 变更导致全端超时）
- …（更早见 git log）

## 🗂️ 参考文档（仓库既有）

- `docs/PROJECT_OVERVIEW.md` / `DOMAIN_MODEL.md` / `INTEGRATIONS.md` —— 业务与集成约定（AGENTS.md 指定必读）
- `docs/ACCOUNTING_V2_DESIGN.md` —— 账本 V2 设计
- `requirements.md` —— 需求原文
- `AGENTS.md` / `~/.dsh/AGENTS.md` —— 协作协议（四象限）与仓库约定