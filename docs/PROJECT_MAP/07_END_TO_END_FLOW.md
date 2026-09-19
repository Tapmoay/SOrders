# 07 三端互通端到端流程（货主 ⇄ 派单员 ⇄ 司机）

<!-- ref-prefix: android/app/src/main/java/com/tapmoay/sorders/ -->
<!-- 本文的 Kotlin 路径省略了包根；此行供 check_refs.py 解析（后端路径不受影响）。 -->

> 本文回答「一条订单从下单到送货再到入账，三端各自看到什么、怎么收到消息、谁能做什么」。
> 与工程地图（01-06）配合使用：本文讲**业务流转**，02 讲**接口**，05 讲**怎么测**。
> 数据事实均从代码核实（`orders.py / message_center.py / push_events.py / stats_service.py / ledger 相关`）。

## 0. 全局消息互通机制（先懂这个）

**消息 = 双通道**（后端在订单每个状态变更时同时做两件事）：
1. **Socket.IO 实时推送**（进 App 立即刷新，客户端 `core/RealtimeHub.kt` 收事件后调 repo 重拉列表）
2. **站内消息中心落库**（`notifications` 表，离线也能在消息中心看到；Socket 断线重连后靠列表兜底）

| 事件 type | 触发点 | 发给谁 |
|---|---|---|
| `dispatcher.pending_pool` | 新订单/撤销/召回 | 所有在线派单员（刷新待派单池角标） |
| `new_order`(落库) + pool | 货主下单成功 | 派单员（消息中心+角标） |
| `order.assigned` | 派单员指派司机 | **司机**（我的任务出现新单） |
| `order.dispatched` | 同上 | **货主**（订单状态=已派单） |
| `order.driver_ack` | 司机点击接单 | 货主（已接单）+ 派单员（刷新列表） |
| `order.freight.updated` | 派单员改运费 | 司机 |
| `order.revoked` | 派单员召回（换司机） | 原司机（订单被撤走） |
| `order.recalled` | 派单员撤回改单 | 货主 |
| `order.delivered` | 司机完成送达 | 货主 + 司机（自己） |
| `order.delivered`(broadcast) | 同上 | 派单员（刷新列表/报表） |
| `order.cancelled` | 撤销 | 货主（+司机/派单员广播） |
| `ledger.updated` | 订单入账本 | 相关货主（账本页刷新） |
| `order.delivered_driver` | 完成 | 司机（自己单子终态） |

> 推送实现入口：`app/services/push_events.py`（每个 `push_*` 函数）→ `message_center.py`（publish_*/broadcast_*）；订单接口用 `background_tasks` 异步触发，不阻塞响应。

---

## 1. 货主：下单 → 到派单员

### 1.1 货主下单（货主端 `ui/shipper/OrderCreateScreen.kt`）
1. 打开「下单」→ 选商品（有批发商特价 `price_rules` 时显示**特价=唯一应用价**，否则默认价；商品名称紫色/单价橙色/数量蓝色）
2. 每商品填数量（弹小窗：商品名标题 + 数量步进 + 取消/确定）
3. 选地址：可从「地点库/常用线路」选（起点A可选、终点B必填，带图可多图）或地图选点（高德）
4. 填联系人 / 电话 / 备注 → 提交 `POST /orders`
5. 货主「我的订单」出现该单，状态 **PENDING_DISPATCH（派单中）**

### 1.2 消息如何到派单员
下单成功 → 后端 `background_tasks` 触发：
- `push_new_order_to_dispatchers`（消息中心落库：新订单通知）
- `push_dispatcher_pending_pool_changed`（Socket 广播 `dispatcher.pending_pool`）

派单员端表现为：**待派单池角标刷新 + 消息中心一条"新订单"**（在线即时，离线下次登录在消息中心看到）。

### 1.3 派单员待派单池
- 入口：工作台「派单作业」→ 待派单池（或底部 Tab「派单作业」）
- 列表：PENDING_DISPATCH 订单卡（单号/地址/货主/商品行/金额/时间）
- 卡片操作：**派单**（指派司机）或 **撤销**

---

## 2. 派单员：派单流程

### 2.1 指派司机（`POST /orders/{id}/assign`）
1. 点「派单」→ 选司机（在线/全部）→ 选车辆 → 填**运费**（按单计费 PIECE 时显示；SALARY 司机运费自动生成月薪账单时不需要）
2. 可选勾选「**收取现金**」（`collect_cash=true`：司机完成界面出现"收取现金/挂账"两按钮；false=送达自动挂账）
3. 提交 → 订单状态 **DISPATCHED**（已派单未接）→ 快照 `driver_billing_mode_snapshot`

### 2.2 消息
- 司机：`order.assigned` → 我的任务「进行中」出现新单
- 货主：`order.dispatched` → 我的订单状态=已派单

### 2.3 派单员还能做什么（订单管理）
| 动作 | 接口 | 说明 |
|---|---|---|
| 批量派单 | POST /orders/batch-assign | 多单一次派 |
| 改运费 | POST /orders/{id}/freight → `order.freight.updated` 推给司机 | |
| 撤回/换司机 | POST /orders/{id}/recall → 原司机 `order.revoked` + 货主 `order.recalled`；单子回待派单池 | |
| 拆分订单 | POST /orders/{id}/split | 大单拆多单再分别派 |
| 撤销订单 | POST /orders/{id}/cancel（限 PENDING/DISPATCHED，司机未接单时） | |
| 标记异常/查看图片 | PATCH /orders/{id}/exception | |
| 代理下单 | POST /orders（temp_shipper_name 无账号货主） | |

---

## 3. 司机：接单 → 送达 → 收款

### 3.1 接单
- 司机端「进行中」任务列表（Socket `order.assigned` 即时出现）
- 点开订单详情 → 「接单」`POST /orders/{id}/driver-ack` → 状态 **ACCEPTED**
- 消息：货主 `order.driver_ack`（已接单）+ 派单员 `driver_ack` 广播

### 3.2 司机遇到并处理的问题（订单详情操作）
| 场景 | 司机动作 | 说明 |
|---|---|---|
| 找不到/地址不清 | —（联系派单员，无自助能力） | 地址图片 `address-image` 供查看 |
| 出发前备注 | `driver-note` | 备注给派单员看 |
| 约定超时前送不出 | 无操作，系统自动标异常 | 派单员处理 |
| 送达 | 「完成」→ 拍照（`complete-with-upload`）或直接完成（`complete`） | |
| 货损 | 完成界面填**货损数量 + 备注**（`damage_items/damage_note`） | 后端记 `damage_quantity`（报表货损金额=成本快照×数量） |
| 收款 | 勾选过「收取现金」则显示：**收取现金(cash, paid)** / **挂账(arrears, 未付)**；没勾选 → 自动挂账 | 挂账会关联挂账单位（`arrears_unit_name`） |
| 司机备注 | `driver_remark`（顺带写） | |

### 3.3 完成瞬间发生的事（`POST /orders/{id}/complete`）
1. 订单 → **DELIVERED**，记 `delivered_at`
2. 收款处理 `_apply_complete_payment`（见上表）
3. 后台触发：
   - 货主 `order.delivered` + 派单员广播 `order.delivered`
   - **`ledger.updated` → 货主账本自动入账**（`ledger_sync` 幂等，把订单行写进货主账本 ORDER 源）
   - 司机运费进入正所在月的计价明细（PIECE 时）或月薪账单（SALARY）
   - 报表数据可查（营业/商品/司机/资金）

---

## 4. 货主：账本与地址联系人管理

### 4.1 我的账本（货主端 `ui/shipper/ShipperLedgerScreen.kt`）
- 数据源：`GET /ledger/entries`（按登录人 shipper_id 过滤；**订单自动同步 ORDER 源 + 派单员手动记账 MANUAL 源**）
- 明细行：日期/商品/数量/单价/金额/来源（自动/手动）；关联订单的可点进订单详情
- 货主只能看自己的账；批发商（is_member）另有专属价账目
- 记账深度在**派单员**侧（账本管理四大账：订单账/司机账/货主账/批发商账 + 收款单/开销/结算/车辆工具页）

### 4.2 地址与联系人（货主端 `ui/shipper/AddressScreen.kt`，三列表结构）
| 列表 | 内容 | 用途 |
|---|---|---|
| 常用线路 | 联系人 + 起点 + 终点（快照，含图片） | 下单一键选 |
| 联系人 | 姓名/电话（重复电话 409） | 下单填联系人 |
| 地点 | 纯地点（可图） | 线路起点/终点选择 |

- 下单时地址选择器从这三表选；上传图片走 `POST /shipper/locations/image`
- 派单员「地址与联系人」模块复用同一套接口（ShipperOrDispatcher 双角色），**代理下单**时共享
- 权限隔离：全部按登录用户 id 归属（字段名 shipper_id 实为 owner）

---

## 5. 司机：对订单的处理全景

### 5.1 司机端页面
- **进行中**（DISPATCHED+ACCEPTED）：接单/出发/备注/完成入口
- **已完成**：历史 + 每单运费（PIECE 显示/待定价；SALARY 只显示月薪不显示按单运费）
- **我的账本**（`DriverFreightScreen.kt`）：按月运费汇总（`/freight-settlement`，只回自己）

### 5.2 司机需要处理的"问题"清单
1. 接不接单（接单 = accept；不接无明确拒绝动作，派单员可召回换人）
2. 运费是否已知（PIECE：派单员改运费会 `order.freight.updated` 推送；待定价=未填）
3. 送达+拍照（强制/可选看前端流程）
4. 收款分流（现金 vs 挂账）——由 `collect_cash` 决定 UI 形态
5. 货损申报（数量+备注）
6. 超时风险：系统自动标异常，司机无自助"申请延期"，只能通过 driver-note 或联系派单员

---

## 6. 派单员：需要处理的问题全景

| 场景 | 处理 |
|---|---|
| 新订单进来 | 待派单池角标/消息 → 派单 |
| 司机超时未送/待派超时 | **自动异常**（`auto_exception_reason`：待派>4h="待派超时"；已派超预计时间="超时未送"；送达超预计="逾期送达"；撤销单也标异常）→ 报表「异常与审计」列表 → 点「解决」填说明（`resolve`） |
| 司机不合适 | 召回 → 换司机再派 |
| 运费没定 | 补运费（freight） |
| 货主没账号 | 代理下单（temp_shipper_name） |
| 账务 | 账本管理：订单账编辑备注/手动记账/收款单/开销单/司机结算单/车辆 |
| 挂账 | 挂账单位管理；收款（`/orders/{id}/pay` 结清）或转账（`/orders/{id}/charge` 换单位） |
| 经营分析 | 报表中心 6 报表 + 导出 Excel |
| 司机结算 | 月结：`driver-bills/generate` → `driver-settlements` confirm→pay；报表可见待结运费（PIECE） |
| 审计 | 操作日志（`operation-logs`）：谁改了什么 |

---

## 7. 状态机全景（每条订单的一生）

```
[货主下单] PENDING_DISPATCH ──派单──▶ DISPATCHED ──司机接单──▶ ACCEPTED ──送达──▶ DELIVERED
      │  │                          │                            │
      │  └──撤销(货主/派单员)──▶ CANCELLED                        ├─超时自动异常→派单员标记解决
      └──召回(召回后回 PENDING_DISPATCH)                       ▲
      [代理下单 temp_shipper_name 同流程]                        └─ 完成时: cash|arrears + 货损 + 照片
```

- DELIVERED 后：`ledger` 入账（货主账）→ `cash_flows`（收款/挂账）→ 司机账单/结算 → 报表
- 异常：`is_exception` 字段，规则见 §6；`exception_resolved_at` 非空=已解决

## 8. 三端页面 ⇄ 接口 ⇄ 事件 对照（测试用）

| 业务 | 端/页面 | 接口 | 收到的事件 |
|---|---|---|---|
| 下单 | 货主 OrderCreate | POST /orders | —（货主自己刷列表） |
| 待派单刷新 | 派单员 DispatcherPool | GET /orders | dispatcher.pending_pool |
| 指派 | 派单员 Assign | POST /orders/{id}/assign | 司机 order.assigned / 货主 order.dispatched |
| 接单 | 司机 DriverOrders | POST driver-ack | 货主 order.driver_ack / 派单员广播 |
| 送达 | 司机 Detail | POST complete(\-with-upload) | 货主 order.delivered / 派单员广播 / 货主 ledger.updated |
| 收款 | 司机 Detail | 完成时 payment=cash\|arrears | —（后端落 cash_flows/挂账） |
| 改运费 | 派单员 Freight | POST freight | 司机 order.freight.updated |
| 召回 | 派单员 Recall | POST recall | 原司机 order.revoked / 货主 order.recalled |
| 撤销 | 货主/派单员 | POST cancel | 货主 order.cancelled（+司机/派单员广播） |
| 账本刷新 | 货主 ShipperLedger | GET /ledger/entries | ledger.updated |
| 报表 | 派单员 ReportCenter | GET /reports/* | —（手动/切时间刷新） |

---

## 9. 测试这本书的正确姿势（针对三端互通）

1. **起点**：5556 货主下单 → 看 5554 派单员**待派单池角标是否即时 +1**（Socket 验证）
2. **派单**：5554 指派给 5558 司机 → 5558 **进行中即时出现** + 5556 状态变已派单
3. **接单**：5558 接单 → 5556 显示已接单（driver_ack 到达）
4. **完成**：5558 完成（选现金/挂账/货损/拍照）→ 5556 状态已送达 + **我的账本多一条**（ledger.updated）
5. **异常**：人为把订单 expected_deliver_before 改到过去 → 5554 报表「异常与审计」出现，点解决
6. **召回**：5554 召回 → 5558 单子消失（revoked）→ 回待派单池
7. **断网重连**：杀掉后端 → 操作 → 起后端 → 各端重连后列表/角标是否正确（消息中心兜底）
8. **权限**：货主访问自己账本；司机只看到自己；派单员看全部；越权应 403
