# SOrders 鸿蒙（HarmonyOS NEXT）原生应用开发指引

本文档与根目录 [IMPLEMENTATION_SUMMARY.md](./IMPLEMENTATION_SUMMARY.md) **配套使用**：后者描述当前仓库 **Web 前端 + 后端** 的实现与领域约定；本文档在 **不改动业务规则** 的前提下，给出在 **鸿蒙原生应用（推荐 API 12+ / HarmonyOS NEXT，ArkTS + ArkUI）** 中复刻三端能力时的 **架构映射、接口约定与实现要点**，便于在 Cursor / DevEco 中分模块落地。

---

## 1. 文档关系与前提

| 项目 | 说明 |
|------|------|
| 业务与状态机 | 以 [docs/DOMAIN_MODEL.md](docs/DOMAIN_MODEL.md)、[IMPLEMENTATION_SUMMARY.md](./IMPLEMENTATION_SUMMARY.md) 为准 |
| 后端契约 | 现有 **FastAPI** 服务：`/api/v1` REST + **`/socket.io`**（Socket.IO 协议） |
| 鸿蒙端目标 | 独立 ArkTS 工程（可与本仓库同目录 monorepo，或另建仓库）；**复用同一后端**，不重复实现服务端逻辑 |

**约束**：鸿蒙端须自行实现 HTTP 客户端、Socket.IO 客户端、本地持久化与 UI；后端字段名、订单状态枚举、`realtime.type` 与 Web 端保持一致，便于联调。

---

## 2. 后端与网络契约（鸿蒙端必须对齐）

### 2.1 REST

- **基址**：与 Web 相同，指向 `.../api/v1`（生产环境 HTTPS；开发可用局域网 IP）。
- **认证**：请求头 `Authorization: Bearer <access_token>`；登录接口返回的 token 持久化到鸿蒙首选项或安全存储。
- **401**：清除本地会话并跳转登录页（与 Web axios 拦截器行为一致）。

### 2.2 Socket.IO（实时）

- **路径**：`/socket.io`（与 `main.py` 中 `socketio_path` 一致）。
- **连接鉴权**：`auth: { token, lastNotificationId }`（字段名与现有 Web `useSocketRealtime.ts` 对齐）。
- **事件**（客户端订阅）：
  - `sync`：增量通知 + 未读数
  - `notification`：单条消息
  - `unread_count`：未读数
  - `realtime`：轻量业务事件（`type` + `order_id` 等）

典型 `realtime.type` 见 [IMPLEMENTATION_SUMMARY.md](./IMPLEMENTATION_SUMMARY.md) 第 3.4 节；鸿蒙端应按 **货主 / 司机 / 派单员** 分别刷新订单列表或账本，逻辑同 Web 的 `bumpDriverOrdersRefresh` / `bumpShipperOrdersRefresh` 语义。

**实现提示**：优先使用与 Socket.IO 协议兼容的客户端库（或评估 `@ohos/net.socket` + 自行解析 Engine.IO 的复杂度）；若短期仅 HTTP，可用 **轮询未读 + 列表下拉刷新** 降级，但司机新单与撤回体验会弱于长连接。

### 2.3 静态资源与上传

- 送达照等资源 URL 形如 `/static/uploads/...`；鸿蒙端需拼 **完整 origin** 展示图片；**multipart 上传** 与后端 `orders` 中文件校验（类型、大小）一致。

---

## 3. 三端信息架构 → 鸿蒙页面/路由映射

与 Web 路由一一对应，建议使用 **Navigation** + **Tabs**（底部）组合：

| 角色 | Web 路径（参考） | 鸿蒙建议 |
|------|------------------|----------|
| 公共 | `/login` | 登录 / 注册（可分页或 Tab） |
| 货主 | `/shipper`、`/shipper/orders`、创建、详情、地址、账本 | `Shipper` 模块内子页面栈 |
| 司机 | `/driver/open`、`/driver/completed`、详情 | 底部双 Tab + 详情页 |
| 派单员 | `pending`、`completed`、代下单、详情、dashboard、prices、ledger | 底部多 Tab + 各子页 |

**角色隔离**：本地保存 `role`，路由守卫在进入模块前校验；与 Web `router.beforeEach` 行为一致（角色不匹配回各自首页）。

---

## 4. 技术映射：Web 实现 → 鸿蒙常见选型

| Web（当前仓库） | 鸿蒙（HarmonyOS NEXT / ArkTS）建议 |
|-----------------|-------------------------------------|
| Vue 3 + 组件 | ArkUI 声明式 UI（`@Component` / `struct`） |
| Pinia | `AppStorage` / `PersistentStorage` + `@Observed` / `class` 状态类，或轻量自研 Store |
| axios | `@ohos.net.http` 封装单例；统一 baseURL、拦截器、错误码处理 |
| Vant NavBar / Tabbar | `Navigation` Title、`Tabs` / `TabContent`、自定义顶栏配色 |
| `@tanstack/vue-virtual` | `LazyForEach` + `List` 子项高度估算；大数据量再考虑自定义虚拟列表 |
| Vant Lazyload | `Image` 懒加载、`LazyForEach` |
| ECharts | **Harmony 图表**（`@ohos/harmony-charts` 等，以当前 SDK 文档为准）或 Web 组件嵌入（权衡包体与维护） |
| `socket.io-client` | Socket.IO 兼容客户端，或 WebSocket 降级方案（见 2.2） |
| `localStorage` | `preferences` 或分布式键值（按隐私与安全要求选择） |
| IndexedDB 离线队列 | **关系型数据库 RDB** 或 **键值型 KV** 存队列项（blob 路径用文件沙箱路径 + 元数据表） |
| `SpeechSynthesis` | **文本转语音 TTS** API（系统能力），在「重要消息」时播报 |
| 高德 H5 / JS API | **高德鸿蒙 SDK** 或 **鸿蒙地图服务**；导航可用 **系统地图 URI** 或高德 URI Scheme（需查阅最新平台文档与权限） |
| Canvas 水印 | **Canvas** 或 **PixelMap** 处理后再上传，算法逻辑可移植自 `frontend/src/utils/watermark.ts` |

---

## 5. UI/UX：复刻 IMPLEMENTATION_SUMMARY 中的设计系统

以下数值与 Web `theme-tokens.css` / `MainLayout.vue` **保持一致**，便于三端视觉统一。

### 5.1 颜色与层级

| 用途 | 色值 |
|------|------|
| 主色（按钮、Tab 激活、链接） | `#1677ff` |
| 页面背景 | `#f5f7fa` |
| 卡片/顶栏区域背景 | `#ffffff` |
| 主文案 | `#1f2937` |
| 次要文案 | `#4b5563` |
| 辅助文案 | `#9ca3af` |
| 边框 | `#e5e7eb` |

### 5.2 布局与组件

- **圆角**：卡片/按钮约 **10–12vp**。
- **正文字号**：基准约 **16fp**，行高约 **1.5**。
- **货主顶栏**：**品牌蓝底 + 白字**（与 Web 货主 `van-nav-bar` 一致）。
- **司机 / 派单员顶栏**：**白底 + 深色标题**，右侧消息图标 + 未读角标 + 退出。
- **状态标签**：低饱和描边 + 浅底（成功/警告/危险语义色与 Web Plain Tag 同方向）。
- **动效**：点击态透明度或背景微变；系统开启「减少动态效果」时减弱动画（对齐 Web `prefers-reduced-motion` 意图）。

### 5.3 交互逻辑（与 Web 对齐）

- 登录后按 **role** 进入货主首页 / 司机未完成 / 派单员工作台。
- 消息中心：全局入口；Socket 推送后合并列表并更新未读；`speech_important` 可走 TTS。
- 订单列表：收到 `realtime` 后触发刷新，减少仅依赖手动下拉。
- 错误文案：可对后端英文 `detail` 做中文映射（可复用 Web `LoginView` 中映射表思想）。

---

## 6. 模块级实现要点

### 6.1 认证与个人信息

- 登录成功后保存 `access_token`、`user_id`、`role`；启动时请求 **与 Web `fetchMe` 等价接口** 校验 token 与角色，避免本地缓存与服务器不一致。

### 6.2 订单（货主 / 司机 / 派单员）

- 列表筛选、搜索、Tab 状态与后端查询参数对齐（见 `orders` API 与 Web `api/orders.ts`）。
- 派单员：批量派单、撤回填原因、全局搜索 —— 请求体字段与 Web 保持一致。
- 司机：完成订单至少一张照片；先水印再上传；弱网用 **本地队列** 持久化，恢复网络后顺序重试。

### 6.3 账本与价格

- 货主账本筛选、导出：导出为异步任务时，通过 **消息中心** 或轮询任务状态获取下载链接（与 [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) 一致）。
- 派单员改账本行：触发与订单行同步规则以后端为准（`ledger_sync`）。

### 6.4 消息中心

- REST：`notifications` 列表与已读；Socket：增量与未读数。
- 未读角标与 `lastNotificationId` 同步策略与 Web `messageCenter` store 对齐。

### 6.5 数据看板（派单员）

- 调用 `stats` 下各 GET 接口；图表维度与 Web `DispatcherDashboard` 一致；导出走统计导出接口（流式或文件 URL 依后端实现）。

---

## 7. 权限、安全与上架注意

- **网络权限**：`ohos.permission.INTERNET`；若 cleartext 仅开发环境使用，生产必须 HTTPS。
- **相册 / 相机**：上传送达照所需权限声明与向用户说明用途。
- **定位**：若水印或导航使用 GPS，声明定位权限并遵循最小必要原则。
- **Token 存储**：敏感信息避免明文写入普通 preferences；可使用安全控件或加密存储方案（以官方安全指南为准）。

---

## 8. 与本仓库的协作方式建议

| 方式 | 说明 |
|------|------|
| 接口联调 | 后端固定启动于可局域网访问地址；鸿蒙真机/模拟器配置同一网段与 `api` baseURL |
| 契约同步 | OpenAPI（若后续生成）或对照 `backend/app/api/v1` 与 `frontend/src/api/*.ts` |
| 设计对齐 | 以本文第 5 节 + `frontend/src/styles/theme-tokens.css` 为单一样式来源 |

---

## 9. 参考索引

| 内容 | 位置 |
|------|------|
| 全功能与 Web 实现总结 | [IMPLEMENTATION_SUMMARY.md](./IMPLEMENTATION_SUMMARY.md) |
| 领域状态机与权限 | [docs/DOMAIN_MODEL.md](docs/DOMAIN_MODEL.md) |
| 高德、导出、WS 约定 | [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) |
| 后端路由汇总 | `backend/app/api/v1/router.py` |
| Socket 连接与事件 | `backend/app/core/socket_io.py`、`frontend/src/composables/useSocketRealtime.ts` |

---

*说明：鸿蒙 SDK 与三方库版本迭代较快，具体 API 名称以 DevEco 当前文档为准；本文侧重 **业务对齐与映射**，避免绑定易过期的类名。*
