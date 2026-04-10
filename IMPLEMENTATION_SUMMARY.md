# SOrders 派单送货系统 — 功能实现与设计综合说明

本文档基于当前仓库**已实现代码**与 [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md)、[docs/DOMAIN_MODEL.md](docs/DOMAIN_MODEL.md)、[docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) 对齐整理，概括后端业务逻辑、前端交互与视觉风格，便于维护与二次开发。

---

## 1. 技术栈与运行形态

| 层级 | 选型 |
|------|------|
| 后端 | Python **FastAPI**，SQLAlchemy ORM，JWT 认证 |
| 实时 | **python-socketio**（AsyncServer）与 FastAPI 组合为 ASGI；连接时 JWT 鉴权，按用户 ID 进房间推送 |
| 持久化 | SQLite（开发默认，见 `backend` 配置）；Redis 健康检查在 `/health` 中体现 |
| 前端 | **Vue 3** + **TypeScript** + **Vite 5** + **Pinia** + **Vue Router** |
| UI | **Vant 4**（移动端优先组件库）；**@tanstack/vue-virtual** 虚拟列表；**ECharts** 看板图表 |
| HTTP | **axios** 统一 `baseURL`（`VITE_API_BASE_URL` 归一化到含 `/api/v1`） |
| 实时客户端 | **socket.io-client**（WebSocket + 轮询降级、自动重连） |

静态资源：`uploads/delivery`（送达照）、`uploads/exports`、`uploads/products` 等由 FastAPI `StaticFiles` 挂载在 `/static/uploads`。

---

## 2. 后端功能模块（按路由）

| 模块 | 前缀/标签 | 职责摘要 |
|------|-----------|----------|
| `auth` | `/auth` | JSON 登录、OAuth2 表单兼容、短信验证码（开发内存码）、注册后发 Token |
| `users` | `/users` | 当前用户信息与列表；派单员权限下 **货主/司机角色互换** 等管理接口 |
| `shipper` | `/shipper` | 货主侧：常用地址、老板联系人等与订单相关的附属数据 |
| `orders` | `/orders` | 订单 CRUD、列表筛选与搜索、派单/批量派单、撤回、撤销、司机完成（含多图上传）、内部备注等 |
| `order_products` | `/order-products` | 订单行（商品行）在派单员侧的编辑与同步 |
| `products` | `/products` | 商品主数据 |
| `price_rules` | `/price-rules` | 默认价与货主特殊价；变更后可触发通知策略 |
| `ledger` | `/ledger` | 货主账本查询、编辑、补录；与订单明细双向同步逻辑；异步导出任务 |
| `notifications` | `/notifications` | 消息中心列表、已读、未读数 |
| `operation_logs` | `/operation-logs` | 派单员操作审计查询 |
| `stats` | `/stats` | 派单员数据看板：货主维度图表、活跃度、商品下钻、司机绩效、**统计导出流** |

跨模块核心服务：

- **`order_flow`**：`assign_driver`、`complete_delivery`、`cancel_pending`、`recall_dispatch`；完成配送后调用 **`ledger_sync.sync_ledger_from_delivered_order`**；撤回时 **`order_snapshot_for_log`** 写入操作日志。
- **`ledger_sync`**：送达自动生成/更新 `ORDER` 来源账本行（按 `order_product_id` 幂等）；账本改订单行时 **`sync_order_product_from_ledger`**（手工行除外）。
- **`message_center` + `push_events`**：业务事件落库 `Notification` 后 **`emit_notification` / `emit_realtime`** 推 Socket.IO。
- **`cancelled_order_retention`**：后台 lifespan 定时任务清理过期已撤销订单。
- **`ledger_export` / `ledger_export_worker`**、**`stats_export`**：异步生成文件并配合消息或下载约定（与 INTEGRATIONS 文档一致）。

---

## 3. 领域逻辑要点

### 3.1 订单状态（与 DOMAIN_MODEL 一致）

实现枚举与文档一致：`PENDING_DISPATCH`（派单中）→ `ACCEPTED`（已接单）→ `DELIVERED`（已送达）；`CANCELLED`（已撤销）为终态。  
`order_flow` 中校验非法迁移（例如仅待派单可派单/按规则撤销；仅已接单可完成或撤回）。

### 3.2 权限（RBAC）

`app/core/rbac.py` 定义 `Permission` 与 `ROLE_PERMISSIONS`：货主、司机、派单员三角色权限集合；接口通过 `require_permission` 与 `CurrentUser` 组合校验。派单员具备订单全量、派单、撤回、编辑、商品/价格、账本、统计、操作日志等能力。

### 3.3 审计

`operation_log_service` 与订单接口中的 `write_log` 记录派单、完成、撤销、撤回等；撤回派单携带 **订单快照**（商品行、地址、联系人、司机等）于 `change_payload`。

### 3.4 消息与实时

- 连接 **Socket.IO** 时携带 `token` 与 `lastNotificationId`；服务端下发 **`sync`**（离线增量通知）、**`notification`**、**`unread_count`**、**`realtime`**（轻量事件，仅 type + order_id 等）。
- 典型 `realtime.type`：`order.assigned`、`order.revoked`、`order.cancelled`、`order.delivered`、`order.dispatched`、`order.recalled`、`ledger.updated`、`order.driver_ack` 等（以后端 `message_center` 为准）。

---

## 4. 前端结构

### 4.1 路由与角色隔离

- **公共**：`/login`（登录/注册 Tab）、404。
- **货主** `/shipper`：首页、订单列表、创建、详情、常用地址、账本。
- **司机** `/driver`：未完成/已完成 Tab + 订单详情（复用货主详情组件路径）。
- **派单员** `/dispatcher`：待派送工作台、已送达、代下单、订单详情、数据看板、价格管理、货主账本。

`router.beforeEach`：未登录跳转登录并带 `redirect`；**角色与路由 `meta.role` 不匹配则回各自首页**。

### 4.2 布局与全局行为（`MainLayout.vue`）

- 顶栏：**Vant NavBar**，标题来自当前匹配路由 `meta.title`；左侧返回由 `hideBack` 控制；右侧 **消息铃铛（Badge 未读数）** + **退出**。
- **货主路径**（`/shipper`）：顶栏 **品牌蓝底白字**（`--van-primary-color`）；其下可显示 **`ShipperPriceNoticeBar`**（价格相关提醒，可打开消息中心）。
- **司机 / 派单员**：顶栏 **白底**，强调文字与边框色，与货主端区分。
- 底部 **Tabbar**：司机（未完成/已完成）、派单员（派单/送达/看板/价格/账本）；`safe-area` 与占位 padding 适配刘海屏。
- `onMounted` 调用 **`fetchMe`** 与后端同步角色，避免本地 token 与账号角色不一致导致 403。

### 4.3 状态与 API

- **Pinia**：`auth`（token、role、user id）、`messageCenter`（消息列表、未读数、lastNotificationId）。
- **axios**：请求夹带 `Authorization: Bearer`；401 清本地会话并跳转登录；`FormData` 时移除 `Content-Type` 以便浏览器带 boundary。

### 4.4 实时与列表刷新

- **`useSocketRealtime`**（布局层启用）：监听 Socket 事件，合并消息、更新未读；对 **`realtime`** 按角色调用 **`bumpDriverOrdersRefresh` / `bumpShipperOrdersRefresh`**（独立模块中的“刷新信号”），驱动订单列表重新拉取。
- **语音**：消息带 `speech_important` 时使用 **`SpeechSynthesis`** 播报（司机新单、重要通知等场景）。

### 4.5 订单与表单体验

- **虚拟列表**：`VirtualScrollList.vue` 基于 `@tanstack/vue-virtual`，用于长列表性能（与 PROJECT_OVERVIEW 中非功能要求一致）。
- **图片**：Vant **Lazyload** 全局注册。
- **订单草稿**：`orderDraftSync`、`constants/orderDraft` 等与本地草稿/同步相关工具。
- **高德**：`AmapPicker.vue`、`amapNav.ts` 用于选点与导航 URI（依赖环境变量 `VITE_AMAP_KEY` 等，见 INTEGRATIONS）。
- **送达水印**：`watermark.ts` 在客户端绘制时间/地点类信息再上传。
- **离线队列**：`offlineDeliveryQueue.ts` 使用 **IndexedDB** 存储待上传 blob、备注、重试次数；联网后按序上传并与后端 `appendDriverNote`、完成接口配合。

### 4.6 派单员专用交互

- **全局搜索、批量派单、撤回原因**：在 `DispatcherPending.vue` 等与 `orders` API 联动。
- **数据看板**：`DispatcherDashboard.vue` + `stats` API + ECharts。
- **价格与账本**：`DispatcherPrices.vue`、`DispatcherLedger.vue`、`LedgerEntryTable.vue` 等与 `price_rules`、`ledger` 联动。
- **开发/运维辅助**：`DispatcherRoleSwapDialog.vue` 用于在授权下交换货主与司机角色（依赖 `users` API），便于联调。

### 4.7 共用展示组件

- **`OrderDetail.vue` / `OrderDetailBody.vue` / `OrderDetailPopup.vue`**：三端复用订单详情展示与弹层。
- **`MessageCenterPopup.vue`**：消息列表、已读等。

---

## 5. 前端设计风格与交互小结

### 5.1 视觉（`theme-tokens.css` + 布局样式）

- **主色**：克制 **品牌蓝 `#1677ff`**，用于主按钮、链接、Tab 激活、底栏选中，与 Vant 变量 `--van-primary-color` 统一。
- **背景**：页面灰底 `#f5f7fa`，卡片/顶栏区域白底 `#ffffff`，减少纯白刺眼。
- **文字层级**：主 `#1f2937`、次 `#4b5563`、辅助 `#9ca3af`；边框 `#e5e7eb`。
- **圆角**：中等统一（约 10–12px），组件风格一致。
- **字号**：正文基准 **16px**，行高 1.5，偏移动端可读性。
- **状态标签**：Plain Tag 使用 **低饱和描边 + 浅色底**（success/warning/danger 等），避免高饱和“彩虹按钮墙”。
- **动效**：按钮与可点单元 **`opacity` / 背景色短过渡**；支持 **`prefers-reduced-motion: reduce`** 关闭过渡。
- **角色区分**：货主顶栏 **深色品牌条**；司机/派单员 **浅色顶栏**，同一套 Token 下保持层级清晰、不混用两套强风格。

### 5.2 交互逻辑

- **导航**：顶部返回 + 底部 Tab（司机/派单员）+ 路由元信息标题；登录后按角色进入不同首页。
- **消息**：全局铃铛入口；Socket 推送与轮询互补；重要消息语音播报（浏览器能力允许时）。
- **错误提示**：登录页等对后端 **英文 detail** 做中文映射；网络错误提示检查后端与 Vite 代理（开发环境）。
- **实时刷新列表**：减少手动下拉依赖，通过 `realtime` 事件 bump 刷新，保证派单/撤回/送达与列表一致。

---

## 6. 与需求文档的对应关系（简表）

| 需求维度 | 实现要点 |
|----------|----------|
| 三端 Web + 移动优先 | Vant + 响应式布局 + Tabbar/NavBar |
| 订单全流程 | `order_flow` + `orders` API + 各端页面 |
| 派单/批量/撤回/审计 | 批量与撤回接口 + `operation_logs` + 快照 |
| 账本与订单一致 | `ledger_sync` 双向同步 + 送达记账 |
| 消息中心 | `notifications` + Socket `notification`/`sync` |
| 导出 | 账本/统计异步导出服务与静态文件挂载 |
| 高德/水印/离线 | 前端 Amap、水印工具、IndexedDB 队列 |
| 性能 | 虚拟列表、Lazyload、路由 `import()` 懒加载 |

---

## 7. 相关文件索引（便于跳转）

| 说明 | 路径 |
|------|------|
| API 总路由 | `backend/app/api/v1/router.py` |
| ASGI 入口 | `backend/app/main.py` |
| Socket.IO | `backend/app/core/socket_io.py` |
| 订单状态流转 | `backend/app/services/order_flow.py` |
| 前端路由 | `frontend/src/router/index.ts` |
| 主布局与实时 | `frontend/src/layouts/MainLayout.vue`、`frontend/src/composables/useSocketRealtime.ts` |
| 主题 Token | `frontend/src/styles/theme-tokens.css` |

---

*文档生成说明：描述对应仓库当前实现；若后续接口或页面有增减，请同步更新本节与 `docs/` 下领域文档。*
