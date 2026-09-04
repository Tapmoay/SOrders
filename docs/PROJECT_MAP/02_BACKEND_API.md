# 02 后端 API 接口地图

> 所有路径前缀：`/api/v1`（见 `app/config.py` `api_v1_prefix`）。鉴权：`Authorization: Bearer <token>`（JWT 24h）。
> 文件位置：`backend/app/api/v1/<模块>.py`。

## 汇总速查

| 模块 | 前缀 | 文件 | 说明 |
|---|---|---|---|
| 认证 | /auth | auth.py | 登录/注册/短信 |
| 用户 | /users | users.py | 用户管理/角色/司机-货主互转 |
| 订单 | /orders | orders.py | 订单全生命周期（核心） |
| 订单明细 | /order-products | order_products.py | 订单行 CRUD |
| 商品 | /products | products.py | 商品 CRUD+图片 |
| 批发价 | /price-rules | price_rules.py | 批发商专属价/批量调价 |
| 报表 | /reports | reports.py | 营业/商品/客户/资金/审计 + 导出 |
| 统计 | /stats | stats.py | 司机绩效/异常/货主图/导出 |
| 账本 | /ledger | ledger.py | 订单账/账户汇总/收款/导出任务 |
| 挂账 | /arrears-units | arrears.py | 挂账单位 |
| 库存 | /inventory | inventory.py | 出入库流水/汇总 |
| 通知 | /notifications | notifications.py | 消息中心/价格通知 |
| 操作日志 | /operation-logs | operation_logs.py | 敏感操作审计 |
| 货主侧 | /shipper | shipper.py | 地址/联系人/地点/图片 |
| 客户 | /customers | customers.py | 客户档案（注册/散客） |
| 司机应付 | /driver-bills | driver_bills.py | 账单生成（PIECE/SALARY） |
| 司机结算 | /driver-settlements | driver_settlements.py | 结算单（DRAFT→CONFIRMED→PAID） |
| 运费结算 | /freight-settlement | freight_settlement.py | 按司机聚合送达单运费 |
| 运费模板 | /freight-templates | freight_templates.py | 线路模板 |
| 开销 | /expenses | expenses.py | 开销单（8 分类） |
| 资金流水 | /cash-flows | cash_flows.py | 总账收付流水 |
| 车辆 | /vehicles | vehicles.py | 车辆台账 |
| 健康检查 | /health（无前缀） | main.py | status/version/redis |

---

## 1. 认证 /auth

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /auth/login | 手机号+密码→{access_token, ...} |
| POST | /auth/token | 同上（别名） |
| POST | /auth/sms/send | 发送验证码（本地 sms_reveal_code=true 时响应回显明文） |
| POST | /auth/register | 注册→token |

## 2. 用户 /users

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /users/me | 当前用户信息 |
| GET | /users | 用户列表（可按 role 筛选；Driver 含 billing_mode） |
| POST | /users | 创建用户（角色/车型/billing_mode/salary/is_member） |
| GET | /users/{id} | 用户详情 |
| PATCH | /users/{id} | 编辑（换角色会互转司机/货主：swap） |
| POST | /users/{id}/swap-shipper-driver | 司机↔货主互换 |
| DELETE | /users/{id} | 删除 |

## 3. 订单 /orders（核心，权限最细）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /orders | 订单列表（角色过滤：货主只看自己/司机只看自己/派单员看全部） |
| GET | /orders/pending-dispatch-count | 待派单数（工作台徽标） |
| POST | /orders/batch-assign | 批量派单 |
| GET | /orders/{id} | 订单详情（含 order_products/账单状态） |
| DELETE | /orders/{id} | 删除（已撤销订单） |
| POST | /orders | 创建订单（多商品行；代理下单传 temp_shipper_name） |
| PATCH | /orders/{id} | 编辑（货主/派单员各自字段集） |
| PATCH | /orders/{id}/exception | 标记异常 |
| POST | /orders/{id}/address-image | 上传地址参考图 |
| POST | /orders/{id}/delivery-photos | 司机送达拍照 |
| POST | /orders/{id}/complete-with-upload | 拍照+完成（司机） |
| POST | /orders/{id}/driver-ack | 司机接单 |
| POST | /orders/{id}/driver-note | 司机备注 |
| POST | /orders/{id}/assign | 指派司机（运费/计费快照/collect_cash） |
| POST | /orders/{id}/split | 拆分子订单 |
| POST | /orders/{id}/freight | 修改司机运费 |
| POST | /orders/{id}/complete | 完成（payment=cash|arrears|null） |
| POST | /orders/{id}/cancel | 撤销 |
| POST | /orders/{id}/pay | 收款结清（挂账→已收） |
| POST | /orders/{id}/charge | 挂账转移（指定挂账单位） |
| POST | /orders/{id}/recall | 召回 |

## 4. 报表 /reports（报表中心）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /reports/turnover?mode=day|week|month&date=YYYY-MM-DD | 营业纵览：total_amount/orders/avg/freight + cost_total/链路覆盖率 total_lines+cost_covered_lines + damage_qty/damage_amount + collected/arrears_total + cancelled_orders + arrears_units TOP5 + series |
| GET | /reports/products?mode&date | 商品经营：total_qty/total_amount + cost_total/覆盖率 + damage + items[cost/damage] |
| GET | /reports/arrears-summary?date_from&date_to | 挂账未收按单位聚合（name/count/amount） |
| GET | /reports/export?kind=turnover|products|drivers|customers|finance|audit&mode&date[&date_from&date_to] | 导出 xlsx（StreamingResponse；文件名 kind-report-<date>.xlsx） |

> 注意：turnover/products 的聚合逻辑在 `reports.py` 的 `build_turnover()/build_products()`（接口与导出复用）。

## 5. 统计 /stats

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /stats/shipper-product-chart?date_from&date_to&granularity=month|year&metric=quantity|amount | 货主商品图 |
| GET | /stats/shipper-activity?shipper_id&date_from&date_to | 货主活跃度（单量/总额/客单价/TOP商品） |
| GET | /stats/product-drilldown?product_name&date_from&date_to | 单商品订单明细 |
| GET | /stats/driver-performance?date_from&date_to | 司机绩效（completed/on_time_rate/photo_upload_rate/**billing_mode/freight_owed**） |
| GET | /stats/exception-orders?date_from&date_to | 异常订单列表 |
| POST | /stats/exception-orders/{id}/resolve | 标记解决（note） |
| POST | /stats/export | 看板 Excel 导出（body: date_from/date_to/include_*） |

## 6. 账本 /ledger

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /ledger/entries?shipper_id&temp_shipper_name&from&to | 订单账流水 |
| GET | /ledger/accounts?date_from&date_to&kind=shipper|member | 货主账/批发商账聚合（笔数/总额） |
| GET | /ledger/temp-shipper-names | 临时货主名列表 |
| POST | /ledger/sync-from-delivered-orders | 从已送达单补账本（幂等） |
| POST | /ledger/entries | 手动记账 |
| GET | /ledger/entries/{id} | 条目详情 |
| PATCH | /ledger/entries/{id} | 编辑（自动行仅备注） |
| DELETE | /ledger/entries/{id} | 删除 |
| POST | /ledger/export-jobs | 创建导出任务（异步：ledger_export_worker） |
| GET | /ledger/export-jobs/{job_id} | 查任务（下载文件） |
| POST | /ledger/receipts | 创建收款单 |
| GET | /ledger/receipts | 收款单列表 |

## 7. 商品与批发价

**/products**：GET 列表 / POST / GET {id} / PATCH / POST {id}/image / DELETE
**/price-rules**：GET 列表（shipper 角色只能读自己的）/ POST / GET {id} / PATCH {id} / DELETE {id} / POST /batch（多批发商×多商品批量调价）

## 8. 货主侧 /shipper（地址/联系人/地点）

- /addresses（GET/POST/GET{id}/PATCH/DELETE/{id}/set-default）——常用线路（联系人+地点）
- /contacts（GET/POST/PATCH/DELETE）
- /locations（GET 列表/POST/PATCH/DELETE + POST /locations/image 图片上传）
- 权限：ShipperOrDispatcher（双角色）

## 9. 资金/司机/车辆/通知/日志

- **/cash-flows**：GET（direction/biz_type/party_type/date_from/date_to/limit）
- **/expenses**：GET（category/driver_id/date_from/date_to）/ POST
- **/driver-bills**：GET / POST /generate（month+bill_type=PIECE|SALARY）
- **/driver-settlements**：GET / POST（空 amount=自动汇总）/ PATCH {id}（confirm|pay|cancel）
- **/freight-settlement**：GET（month=YYYY-MM 或 from/to；按司机聚合 count/total/orders）
- **/freight-templates**：CRUD
- **/vehicles**：CRUD
- **/arrears-units**：CRUD
- **/inventory**：GET /movements、POST /movements、GET /summary
- **/customers**：GET/POST + POST /merge
- **/notifications**：unread-count、列表、price-notify、read-all、{id} 读改删、{id}/read
- **/operation-logs**：GET（limit/skip）、GET {id}
- **/cash-flows** 等均仅派单员

---

## 10. Socket.IO 实时事件（/socket.io）

- 客户端：`socketManager.connect(token)`；房间按角色（`role_dispatchers` 等）
- 事件：`order.assigned` / `order.revoked` / `dispatcher.pending_pool_changed`（待派单刷新） 等
- 后端推送：`app/services/push_events.py` + `app/core/ws_hub.py`（Redis 广播，可选）
- Android 监听：`core/RealtimeHub.kt`

## 11. 权限速查（require_permission）

| 权限 | 谁有 |
|---|---|
| ORDER_DISPATCH（派单/报表） | 派单员 |
| ORDER_CREATE / READ_OWN / CANCEL_SHIPPER | 货主 |
| ORDER_READ_ASSIGNED / COMPLETE_DRIVER / UPLOAD_DELIVERY | 司机 |
| LEDGER_READ_ALL / LEDGER_EDIT | 派单员 |
| PRODUCT_MANAGE / PRICE_RULE_MANAGE / USER_MANAGE / STATS_READ / OPERATION_LOG_READ | 派单员 |
| NOTIFICATION_READ / NOTIFICATION_MANAGE | 全员可读，管理=派单员 |

> 实现：`require_permission` 在 `deps.py`（派单员直接放行）；角色校验另有 `user_role_key()` 归一化（兼容枚举名/大小写）。
