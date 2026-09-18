# 02 后端 API 接口地图

<!-- ref-prefix: android/app/src/main/java/com/tapmoay/sorders/ -->
<!-- 本文末尾提到 Android 类时省略了包根；此行供 check_refs.py 解析（后端路径不受影响）。 -->

> **本文是「按模块的接口速览」**：核心模块（认证/订单/报表/统计/账本/用户）逐条列出，其余模块（`§7`、`§9`）用 `CRUD`、`GET/POST` 这种**概述式**写法。
> ⚠️ **所以它并不是"逐端点完整清单"**（此前表头如此自称，不准确）。完整清单在
> [`08A_ENDPOINT_INDEX.md`](08A_ENDPOINT_INDEX.md)——机器生成，每个 URL 的精确方法、handler、行号、授权都有，且不会漏、不会漂。
>
> **分工**：本文讲「这个接口是干什么的」（业务语义、参数、副作用——需要人判断）；
> 08A 讲「路径 → handler → 行号 → 谁能调」（纯机械事实）。**冲突时以 08A 为准**——本文的权限描述是手写的，已发现过错漏。
>
> 所有路径前缀：`/api/v1`（见 `app/config.py` `api_v1_prefix`）。鉴权：`Authorization: Bearer <token>`（JWT 24h = `access_token_expires` 60×24 分钟）。
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

> ⚠️ **没有自助注册**：`POST /auth/register` 与 `POST /auth/sms/send` 已于 2026-09-18 按用户要求**整体删除**（App 里早就没有注册入口，接口却一直公开，本地还会明文回显验证码）。建账号只剩派单员 `POST /users`；旧版客户端调这两条路径会拿到 404。
>
> ⚠️ **校验失败的响应体是中文**（2026-09-18 起）：状态码仍是 422，但 `detail` 从 Pydantic 的英文结构体换成了一句能照着改的中文（如「备注：最多 4000 个字（现在 9000 个）」），原始数组保留在 `errors` 里。实现见 `app/core/validation_errors.py`。

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
| DELETE | /orders/{id} | **软删除**（进隔离区 30 天，非物理删除）。货主：本人**已送达/已撤销/异常**单；派单员：任意状态。⚠️ **同一路径有两个 `DELETE`**（`orders.py` L326 / L546），FastAPI 先注册者胜 → **L326 生效、L546 永不可达** |
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
| POST | /orders/{id}/complete | 完成（payment=cash\|arrears\|null） |
| POST | /orders/{id}/cancel | 撤销 |
| POST | /orders/{id}/pay | 收款结清（挂账→已收） |
| POST | /orders/{id}/charge | 挂账转移（指定挂账单位） |
| POST | /orders/{id}/recall | 召回 |
| POST | /orders/{id}/restore | **从隔离区恢复**（仅派单员；软删后 30 天内可恢复） |

## 4. 报表 /reports（报表中心）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /reports/turnover?mode=day\|week\|month&date=YYYY-MM-DD | 营业纵览：total_amount/orders/avg/freight + cost_total/链路覆盖率 total_lines+cost_covered_lines + damage_qty/damage_amount + collected/arrears_total + cancelled_orders + arrears_units TOP5 + series |
| GET | /reports/products?mode&date | 商品经营：total_qty/total_amount + cost_total/覆盖率 + damage + items[cost/damage] |
| GET | /reports/arrears-summary?date_from&date_to | 挂账未收按单位聚合（name/count/amount） |
| GET | /reports/export?kind=turnover\|products\|drivers\|customers\|finance\|audit&mode&date[&date_from&date_to] | 导出 xlsx（StreamingResponse；文件名 kind-report-<date>.xlsx） |

> 注意：turnover/products 的聚合逻辑在 `reports.py` 的 `build_turnover()/build_products()`（接口与导出复用）。

## 5. 统计 /stats

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /stats/shipper-product-chart?date_from&date_to&granularity=month\|year&metric=quantity\|amount | 货主商品图 |
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
| GET | /ledger/accounts?date_from&date_to&kind=shipper\|member | 货主账/批发商账聚合（笔数/总额） |
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
- **/vehicles**：CRUD + `POST /{id}/driver`（绑/解绑司机：`driver_id` 缺省或 null 都 = 解绑）
- **/arrears-units**：CRUD
- **/inventory**：GET /movements、POST /movements、GET /summary
- **/customers**：GET/POST + POST /merge
- **/notifications**：unread-count、列表、price-notify、read-all、**batch-delete（ids 或 all）**、{id} 读改删、{id}/read
- **/operation-logs**：GET（limit/skip）、GET {id}

> ⚠️ **这一组并非"均仅派单员"**（此处曾如此误写）；也**不是"都只要登录"**（我一度这样过度纠正过）。
> 以 08A 的授权列为准，实际分三类：
>
> | 类别 | 端点 |
> |---|---|
> | **函数体内硬门槛 → 仅派单员**（签名只要登录，体里 `role != DISPATCHER → 403`） | `/cash-flows`、`/expenses`(GET+POST)、`/vehicles`(四个)、`/customers`(三个)、`/driver-bills/generate`、`/driver-settlements` 的 POST/PATCH |
> | **体内有角色判断、但不是纯门槛** → 08A 标为「体内含角色判断（需读源码）」 | 例如 `GET /orders` 只在传 `deleted_only`/`include_deleted` 时才要求派单员；`/driver-bills`、`/freight-settlement` 的 GET 还要区分"司机只看自己" |
> | **`require_permission` 硬校验** | `/arrears-units`(LEDGER_EDIT)、`/freight-templates`(ORDER_DISPATCH)、`/inventory`(PRODUCT_MANAGE)、`/operation-logs`(OPERATION_LOG_READ)、`/notifications` 的 price-notify 与建单(NOTIFICATION_MANAGE) |
>
> **逐端点授权查 [`08A_ENDPOINT_INDEX.md`](08A_ENDPOINT_INDEX.md)**——上表只是归纳，**每个端点的签名与函数体都可能不同**，别按模块猜。
>
> 📌 08A 授权列里的三种"体内"标记含义不同，别混：
> - `体内仅允许:X` = 函数体里**明确拒绝**了非 X 的角色 → **可靠结论**；
> - `体内含角色判断（需读源码）` = 检测到角色分支但**无法可靠归纳**（可能是条件性限制，也可能是行级过滤）→ **必须点进源码**；
> - `体内权限:X` = 权限点写在函数体里，而非签名里。

---

## 10. Socket.IO 实时事件（/socket.io）

- 客户端：`socketManager.connect(token)`；房间按角色（`role_dispatchers` 等）
- 事件：`order.assigned` / `order.revoked` / `dispatcher.pending_pool_changed`（待派单刷新） 等
- 后端推送：`app/services/push_events.py`（事件封装）→ `message_center.py`（收件人/文案/未读数）→ `message_push.py` → `socket_io.py`
  ⚠️ `app/core/ws_hub.py` 是**死代码**（全仓零引用），此前本文件把它写成"Redis 广播，可选"——**别照它改**。
  ⚠️ Redis 也不是 `redis_client.py` 在广播：多 worker 的连接共享由 **`app/core/socket_io.py` L23-L32 自建** `socketio.AsyncRedisManager(settings.socket_redis_url)`（URL 为空则退回单进程内存）。
  `app/redis_client.py` 只有一个用途——给 `/health` 提供 `redis_ok()`。
- Android 监听：`core/RealtimeHub.kt`

## 11. 权限速查（`require_permission` / `rbac.py`）

**全部 24 个权限点的归属**（逐条核对 `app/core/rbac.py` `ROLE_PERMISSIONS`，此前本表不完整且有错）：

| 权限点 | 声明拥有的角色 |
|---|---|
| ORDER_CREATE | 货主、派单员 |
| ORDER_READ_OWN | 货主 |
| ORDER_READ_ASSIGNED | 司机 |
| ORDER_READ_ALL | 派单员 |
| ORDER_CANCEL_SHIPPER | 货主 |
| ORDER_CANCEL_DISPATCHER | 派单员 |
| ORDER_DELETE_CANCELLED | 货主、派单员 |
| ORDER_DISPATCH | 派单员 |
| ORDER_RECALL | 派单员 |
| ORDER_EDIT | 派单员 |
| ORDER_COMPLETE_DRIVER | 司机 |
| ORDER_INTERNAL_NOTE | 司机、派单员 |
| ORDER_UPLOAD_DELIVERY | 司机 |
| PRODUCT_MANAGE | 派单员 |
| PRICE_RULE_MANAGE | 派单员 |
| LEDGER_READ_OWN | 货主 |
| LEDGER_READ_ALL | 派单员 |
| LEDGER_EDIT | 派单员 |
| NOTIFICATION_READ | 货主、司机、派单员（全员） |
| NOTIFICATION_MANAGE | 派单员 |
| OPERATION_LOG_READ | 派单员 |
| USER_MANAGE | 派单员 |
| ORDER_PRODUCT_EDIT | 派单员 |
| STATS_READ | 派单员 |

> **🔴 上表不等于"端点准入范围"**。三条必须知道：
> 1. **派单员对 `require_permission` 一律放行**（`rbac.py` L109-L117 开头就 return True），**不看权限点**。所以"ORDER_DISPATCH 只有派单员"这句在端点层面是废话——派单员对**所有**权限点都通过。
> 2. **24 个权限点里只有 19 个被端点引用**：16 个走签名 `Depends(require_permission(...))`（共 78 个端点），
>    另有 3 个（`ORDER_DELETE_CANCELLED`、`ORDER_CANCEL_SHIPPER`、`ORDER_CANCEL_DISPATCHER`）**只写在函数体里的条件判断中**（如货主删单时额外要求 `ORDER_DELETE_CANCELLED`）。
>    剩下 **5 个（`ORDER_READ_OWN`、`ORDER_READ_ASSIGNED`、`LEDGER_READ_OWN`、`LEDGER_READ_ALL`、`NOTIFICATION_READ`）声明了但没有任何端点引用**——改它们不影响任何行为，也不会报错。
> 3. **155 个端点里只有 78 个挂了 `require_permission`**，其余靠签名里的 `CurrentUser`（仅登录）+ 函数体内角色判断。
>    **逐端点授权看 [`08A_ENDPOINT_INDEX.md`](08A_ENDPOINT_INDEX.md)**（「权限点反查」段含每个权限点影响哪些端点、哪些是体内判断），不要从本表反推。
>
> 实现：`require_permission` / `require_roles` 在 `app/deps.py`；角色归一化用 `user_role_key()`（兼容枚举名/大小写不一致的旧库）。
