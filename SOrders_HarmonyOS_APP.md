# SOrders 派单送货系统 — 鸿蒙 APP 开发指南

本文档为 **HarmonyOS（鸿蒙）** 移动端开发提供后端 API 对接参考，基于 `IMPLEMENTATION_SUMMARY.md` 的业务逻辑与接口设计，适配鸿蒙原生的 **ArkTS / ArkUI** 开发范式。

---

## 1. 架构概览

| 层级 | 选型 | 说明 |
|------|------|------|
| 后端 | FastAPI + SQLAlchemy + JWT | 已有完整 REST API，详见本文档接口章节 |
| 实时 | Socket.IO (WebSocket) | 后端已实现，支持连接鉴权、离线同步、实时事件 |
| 持久化 | MySQL / SQLite + Redis | 后端已部署，APP 无需关心 |
| 前端（APP） | **HarmonyOS ArkTS** + **ArkUI** | 本文档聚焦内容 |

**通信模式**：
- HTTP REST：所有 CRUD 操作（登录、订单、账本、消息等）
- WebSocket：实时推送（订单状态变更、消息通知）

---

## 2. 角色与页面

鸿蒙 APP 通过 **角色切换** 或 **多入口** 支持三端：

| 角色 | 功能模块 | 对应后端 API 前缀 |
|------|----------|-------------------|
| 货主 | 首页、订单列表、创建订单、订单详情、常用地址、账本 | `/shipper`、`/orders` |
| 司机 | 未完成订单、已完成订单、订单详情、送达操作 | `/orders`、`/driver` |
| 派单员 | 待派送工作台、已送达、代下单、订单详情、数据看板、价格管理、账本 | `/orders`、`/stats`、`/price-rules` |

**路由设计建议**：
```
/login              - 登录/注册
/shipper/home       - 货主首页
/shipper/orders     - 订单列表
/shipper/create     - 创建订单
/shipper/ledger     - 货主账本
/driver/home       - 司机首页（待完成/已完成 Tab）
/dispatcher/home   - 派单员首页（派单/送达 Tab）
/dispatcher/dashboard - 数据看板
/dispatcher/prices  - 价格管理
/dispatcher/ledger  - 货主账本管理
/message           - 消息中心（全局）
```

---

## 3. API 接口清单

以下为各模块核心接口，完整 Swagger 文档访问后端 `/docs`。

### 3.1 认证

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/auth/login` | POST | 登录，返回 JWT `access_token` |
| `/api/v1/auth/register` | POST | 注册， 注册成功后同样返回 Token |
| `/api/v1/auth/sms-code` | POST | 获取短信验证码（开发环境返回内存码） |

**请求体**：
```json
{
  "phone": "13800000001",
  "password": "pass12345"
}
```

**响应**：
```json
{
  "access_token": "eyJhbGciOiJIUzI1...",
  "token_type": "bearer",
  "role": "dispatcher"
}
```

### 3.2 用户

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/users/me` | GET | 获取当前用户信息（含角色） |
| `/api/v1/users` | GET | 用户列表（派单员可用） |
| `/api/v1/users/{user_id}/role-swap` | POST | 货主/司机角色互换（派单员授权操作） |

### 3.3 订单

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/orders` | GET | 订单列表，支持筛选 `status`、`shipper_id`、`driver_id` |
| `/api/v1/orders` | POST | 创建订单（货主） |
| `/api/v1/orders/{id}` | GET | 订单详情 |
| `/api/v1/orders/{id}` | PATCH | 订单基本信息修改 |
| `/api/v1/orders/{id}/assign` | POST | 派单（派单员→司机） |
| `/api/v1/orders/{id}/batch-assign` | POST | 批量派单 |
| `/api/v1/orders/{id}/accept` | POST | 司机接单 |
| `/api/v1/orders/{id}/complete` | POST | 司机完成配送（含多图上传） |
| `/api/v1/orders/{id}/recall` | POST | 派单员撤回已派单订单 |
| `/api/v1/orders/{id}/cancel` | POST | 货主撤销待派单订单 |
| `/api/v1/orders/{id}/append-note` | POST | 司机追加备注/照片（支持离线队列） |

**订单状态流转**：
```
PENDING_DISPATCH（待派单）→ ACCEPTED（已接单）→ DELIVERED（已送达）
PENDING_DISPATCH → CANCELLED（已撤销，货主可操作）
ACCEPTED → RECALLED（已撤回，派单员可操作）
```

### 3.4 商品与价格

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/products` | GET | 商品主数据列表 |
| `/api/v1/price-rules` | GET | 价格规则（默认价、货主特殊价） |
| `/api/v1/price-rules` | POST/PATCH | 价格规则管理（派单员） |

### 3.5 账本

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/ledger` | GET | 账本列表，筛选 `shipper_id`、`date_range` |
| `/api/v1/ledger` | POST | 手工记账（派单员） |
| `/api/v1/ledger/{id}` | PATCH | 账本编辑 |
| `/api/v1/ledger/export` | POST | 账本导出（异步，返回文件URL） |

### 3.6 消息中心

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/notifications` | GET | 消息列表，分页 |
| `/api/v1/notifications/{id}/read` | POST | 标记已读 |
| `/api/v1/notifications/unread-count` | GET | 未读数 |

### 3.7 统计看板

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/stats/dashboard` | GET | 派单员数据看板（图表数据） |
| `/api/v1/stats/export` | POST | 统计导出（异步） |

### 3.8 操作日志

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/operation-logs` | GET | 派单员操作审计查询 |

---

## 4. WebSocket 实时对接

### 4.1 连接方式

后端 Socket.IO 路径：`/socket.io/`

**连接参数**（Query）：
- `token`：JWT 令牌
- `lastNotificationId`：上次最新通知 ID（用于离线增量同步）

**鸿蒙实现建议**：使用 `WebSocket` 原生 API 或第三方库，URL 示例：
```
ws://{API_HOST}/socket.io/?token={JWT}&lastNotificationId=0
```

### 4.2 事件类型

| 事件名 | 方向 | 说明 |
|--------|------|------|
| `connect` | → | 连接成功，服务端返回 `sync`（离线增量） |
| `notification` | ← | 新通知推送 |
| `unread_count` | ← | 未读数变更 |
| `realtime` | ← | 轻量实时事件，包含 `type` 与 `order_id` |

**realtime.type 枚举**：
| type | 说明 |
|------|------|
| `order.assigned` | 订单已派单 |
| `order.accepted` | 司机已接单 |
| `order.dispatched` | 订单已发出 |
| `order.revoked` | 订单已撤回 |
| `order.recalled` | 订单被撤回 |
| `order.cancelled` | 订单已取消 |
| `order.delivered` | 订单已送达 |
| `order.driver_ack` | 司机确认 |
| `ledger.updated` | 账本更新 |

### 4.3 离线同步逻辑

1. APP 首次连接时，服务端根据 `lastNotificationId` 推送 `sync`（增量通知数组）
2. 后续实时事件增量推送
3. APP 需维护本地 `lastNotificationId`，每次连接时传递

---

## 5. 鸿蒙开发技术要点

### 5.1 网络请求封装

建议封装统一的网络服务类：

```typescript
// HttpService.ets
import { axios } from '@ohos/axios';

interface ApiResponse<T> {
  data: T;
  status: number;
}

class HttpService {
  private baseURL: string = 'http://{API_HOST}/api/v1';
  private token: string = '';

  setToken(token: string) {
    this.token = token;
  }

  async get<T>(path: string, params?: object): Promise<T> {
    const response = await axios.get<ApiResponse<T>>(`${this.baseURL}${path}`, {
      headers: { Authorization: `Bearer ${this.token}` },
      params
    });
    return response.data.data;
  }

  async post<T>(path: string, data?: object): Promise<T> {
    const response = await axios.post<ApiResponse<T>>(`${this.baseURL}${path}`, data, {
      headers: { Authorization: `Bearer ${this.token}` }
    });
    return response.data.data;
  }

  async uploadFile(path: string, filePath: string, extraData?: object): Promise<T> {
    const formData = new FormData();
    formData.append('file', filePath);
    // 追加其他字段...
    const response = await axios.post<ApiResponse<T>>(`${this.baseURL}${path}`, formData, {
      headers: {
        Authorization: `Bearer ${this.token}`,
        'Content-Type': 'multipart/form-data'
      }
    });
    return response.data.data;
  }
}

export default new HttpService();
```

### 5.2 WebSocket 管理

```typescript
// WebSocketManager.ets
import socket from '@ohos/socket';

class WebSocketManager {
  private socket: socket.socket = null;
  private token: string = '';
  private lastNotificationId: number = 0;
  private callbacks: Map<string, Function> = new Map();

  connect(token: string, lastNotificationId: number = 0) {
    this.token = token;
    this.lastNotificationId = lastNotificationId;
    
    socket.constructSocket().then((sock) => {
      this.socket = sock;
      this.socket.on('message', (data) => {
        this.handleMessage(data);
      });
      const url = `ws://{API_HOST}/socket.io/?token=${token}&lastNotificationId=${lastNotificationId}`;
      this.socket.connect(url);
    });
  }

  private handleMessage(data: socket.SocketMessage) {
    // 解析 JSON，根据 event 类型分发
    // 调用注册的 callbacks
  }

  on(event: string, callback: Function) {
    this.callbacks.set(event, callback);
  }

  close() {
    if (this.socket) {
      this.socket.close();
    }
  }
}

export default new WebSocketManager();
```

### 5.3 数据存储

- **轻量数据**：使用 `Preferences` 存储 token、userId、角色、lastNotificationId
- **离线队列**：使用 `Rdb`（关系型数据库）或 `Storage` 存储待上传的图片、备注、重试次数，联网后上传

### 5.4 地图（高德）

鸿蒙可通过 **高德定位 SDK** 或 **WebView** 加载高德地图：

1. **WebView 方案**：嵌入高德 JS API，适合选点、导航
2. **Native SDK**：使用高德 HarmonyOS SDK，获取定位、地址逆解析

后端 API `/api/v1/shipper/addresses` 管理常用地址，APP 端可缓存减少请求。

### 5.5 图片水印

送达拍照时，APP 本地生成水印（时间+地点），后端 `/api/v1/orders/{id}/complete` 接受多文件上传。

```typescript
// WatermarkUtil.ets - 简要示例
function addWatermark(imagePath: string, watermarkText: string): string {
  // 使用 ImageKit 或 canvas 将文字绘制到图片上
  // 返回带水印的图片路径
  return watermarkedPath;
}
```

### 5.6 状态管理

使用 **AppStorage** 或 **Riverpod** 风格的全局状态：

```typescript
// Store.ets
import relationalStore from '@ohos.data.relationalStore';

class AuthStore {
  token: string = AppStorage.get<string>('token') || '';
  role: string = AppStorage.get<string>('role') || '';
  userId: number = AppStorage.get<number>('userId') || 0;

  setAuth(token: string, role: string, userId: number) {
    this.token = token;
    this.role = role;
    this.userId = userId;
    AppStorage.set<string>('token', token);
    AppStorage.set<string>('role', role);
    AppStorage.set<number>('userId', userId);
  }

  clearAuth() {
    this.token = '';
    this.role = '';
    this.userId = 0;
    AppStorage.delete('token');
    AppStorage.delete('role');
    AppStorage.delete('userId');
  }
}

export default new AuthStore();
```

---

## 6. 核心业务流程（APP 侧）

### 6.1 货主下单

1. 填写起始地、目的地、联系人、商品明细
2. 调用 `POST /api/v1/orders`
3. 创建成功后跳转到订单详情

### 6.2 派单员派单

1. 在待派单列表选择订单
2. 选择司机（从用户列表获取 `role=driver`）
3. 调用 `POST /api/v1/orders/{id}/assign`
4. Socket 推送 `realtime: order.assigned` 给对应司机

### 6.3 司机完成配送

1. 到达目的地，拍照（可加水印）
2. 调用 `POST /api/v1/orders/{id}/complete`，上传图片
3. 后端自动生成账本记录（ledger 来源 `ORDER`）

### 6.4 消息处理

1. 连接时获取 `sync` 增量通知
2. 实时接收 `notification` 事件
3. 重要消息（如新订单）可调用 `speech` 播报

---

## 7. 权限与 RBAC

后端 RBAC 定义于 `backend/app/core/rbac.py`：

| 角色 | 权限 |
|------|------|
| 货主 | 查看/创建订单、查看账本、管理常用地址、查看自己的订单 |
| 司机 | 查看已接订单、完成配送、查看已完成订单 |
| 派单员 | 全部订单、派单/撤回、编辑商品/价格、账本管理、数据看板、操作日志 |

APP 端需根据当前用户 role 动态渲染菜单与功能入口。

---

## 8. 开发环境配置

| 变量 | 说明 |
|------|------|
| `API_BASE_URL` | 后端 API 地址，如 `http://192.168.1.100:8000/api/v1` |
| `WS_URL` | WebSocket 地址，如 `ws://192.168.1.100:8000` |
| `AMAP_KEY` | 高德地图 Key（可选） |

---

## 9. 相关文件索引

| 说明 | 路径 |
|------|------|
| 后端 API 路由 | `backend/app/api/v1/router.py` |
| 后端订单服务 | `backend/app/services/order_flow.py` |
| 后端 RBAC | `backend/app/core/rbac.py` |
| 后端 Socket.IO | `backend/app/core/socket_io.py` |
| 本文档对应 Web 版 | `IMPLEMENTATION_SUMMARY.md` |

---

*文档生成说明：基于仓库当前后端实现编写，供鸿蒙 APP 开发参考；后续 API 变更请同步更新。*