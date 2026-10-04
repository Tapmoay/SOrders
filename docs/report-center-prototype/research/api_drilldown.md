# 接口盘点 · 报表中心下钻链路（只读）

- **仓库**：`D:/AProjects/ASDH/orders`（SOrders 派单送货管理系统）· 分支 `p` · 盘点日 2026-10-05（Asia/Shanghai）
- **方法**：纯源码阅读（`backend/app/api/v1/` + `services/` + `schemas/`），未连生产库、未改任何生产代码。行号 = 本仓库当前工作区实际行号（⚠️ 与 `docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md` 的行号会差 1 左右，索引记的是 `def` 行）。
- **任务范围文件**：orders.py / orders_query.py / orders_common.py / orders_lifecycle.py / orders_delivery.py / orders_assignment.py / orders_payment.py / order_products.py / driver_bills.py / driver_settlements.py / driver_billing_rules.py / freight_settlement.py / cash_flows.py / invoices.py / expenses.py / operation_logs.py / services/stats_service.py。
  **顺带盘了**（下钻链路缺了它们就断链）：api/v1/stats.py、api/v1/reports.py、api/v1/ledger.py、api/v1/shipper_ledger.py、api/v1/arrears.py、schemas/order.py、schemas/accounting_v2.py、schemas/ledger.py、schemas/reports.py、services/order_response.py、services/accounting_service.py、models/enums.py。

## 0. 五句结论（先看这个）

1. **订单列表只认这四种筛法**：状态 / 搜索词 `q` / 货主（`shipper_id` 或 `temp_shipper_name`）/ 日期区间（`date_from,date_to` 下单日、`delivered_from,delivered_to` 送达日）。**没有 `driver_id`、`product_id`、`vehicle_id` 查询参数**（orders_query.py:76-99）；司机只能靠角色作用域"自己看自己"，派单员想按司机取单只能用 `q=<司机姓名/手机号>` 模糊搜（司机姓名+手机号在搜索覆盖列里，orders_query.py:113-181）。
2. **订单详情 = GET /api/v1/orders/{order_id} → OrderOut**：**含商品行**（`order_products[]`，行上有 `damage_quantity` 货损件数、`returned_quantity` 已退件数）、**含钱**（`goods_amount/settled_amount/refunded_amount/arrears_amount`）、**含付款方式**（`payment_method`、`paid`、`arrears_unit_id/name`）、**含货损备注** `damage_note`；**不含**收款单列表、**不含**现金流水列表（那两类要另开接口）。
3. **司机侧三段各有各的接口、都能点到订单**：运费 GET /freight-settlement（`groups[].orders[].order_id`）、账单 GET /driver-bills（`order_id`+`order_no`）、结算 GET /driver-settlements（`order_ids[]`+`bill_ids[]`）。**客户侧**：GET /ledger/entries（`LedgerOut.order_id/order_no`）、GET /ledger/receipts（`order_ids[]`）、GET /shipper-ledger/settlements?order_id=（核销与单一一对应）、GET /reports/customer-balances?include_orders=true（逐单明细带 `order_id/order_no`）。
4. **三类支出/收入记录点回原单据的字段**：现金流水 `CashFlowOut.order_id` + `CashFlowOut.doc_id`（`doc_id` 指向收款单/开销单/结算单/应付款，随 `biz_type` 变）；开销 `ExpenseOut.order_id`+`order_no`（还能点 `driver_id`/`vehicle_id`）；**发票没有 `order_id`** —— 只有 `purchase_order_ids[]`（采购单）与 `ledger_ids[]`（账本行），要到订单得经账本行那一跳。
5. **报表中心各汇总卡的"下一层"极不均衡**：/reports/* 9 个端点里**只有 customer-balances&include_orders=true 自带逐单明细**；products 只是逐商品聚合、turnover 只是逐时段的四个总数。按商品到订单的唯一现成路径是 GET /stats/product-drilldown（返回订单行 + 订单 id）；按司机/按货主到订单要先落在绩效接口上再拿 id 去查订单。

---

## 1. 逐文件端点清单

### 1.1 backend/app/api/v1/orders.py —— 装配层，**0 个端点**

30 行纯文档 + `router = APIRouter(prefix="/orders", tags=["orders"])`。原 2056 行的 25 个端点被拆成 7 个平级模块（orders_query/assignment/delivery/media/payment/lifecycle/return）+ orders_common 助手；每个模块**自己声明 router**（AST 工具靠这一行算前缀）。router.py 仍挂着这个空 router（无害）。

### 1.2 backend/app/api/v1/orders_common.py —— 共享底座，**0 个端点**

| 位置 | 名称 | 作用 |
| --- | --- | --- |
| orders_common.py:57 | `_get_order_scoped(order_id, current, db) -> Order` | 详情/写操作的读侧唯一门。不存在或已软删且非派单员 → 404「订单不存在」；货主非本人 → 403「无权访问」；司机非本人单 → 403；**认不出的角色一律 403**（fail-closed） |
| orders_common.py:82 | `_order_not_deleted_or_404(order)` | 写路径挡隔离区单，统一用 404（不用 403：状态码差异会泄露"存在一张你看不到的已删除单"） |
| orders_common.py:35 | `_save_delivery_uploads(order_id, files)` | 送达照片落盘 `/static/uploads/delivery/<order_id>/<uuid>.<ext>`，最多 20 张、限 8MB（`MAX_DELIVERY_PHOTO_BYTES`）、content-type 白名单 |

### 1.3 backend/app/api/v1/orders_query.py —— 列表 / 待派计数 / 详情

| 方法 + 路径 | 参数 | 权限 | 关键返回 | 位置 |
| --- | --- | --- | --- | --- |
| `GET /api/v1/orders` | `status`(枚举)、`q`(模糊)、`shipper_id`、`temp_shipper_name`、`unpriced`(bool)、`date_from`/`date_to`(下单日，含当天)、`delivered_from`/`delivered_to`(送达日，含当天)、`limit`(**ge=1 le=5000，缺省 300**)、`include_deleted`、`deleted_only` | `require_any_permission(ORDER_READ_OWN, ORDER_READ_ASSIGNED, ORDER_READ_ALL)` + 体内角色作用域（货主=自己 / 司机=自己 / 派单员=全量，其余 403） | `list[OrderOut]` **裸数组**；截断走响应头 `X-Result-Limit`+`X-Truncated: 1` | orders_query.py:76-253（参数 :81-99；两条查询构造路径 :113-181 派单员+搜索 / :183-253 其余角色） |
| `GET /api/v1/orders/pending-dispatch-count` | 无 | 同上三选一 + **体内硬判仅派单员**（否则 403「仅派单员可查询」） | `{"count": int}`（PENDING_DISPATCH 且未软删） | orders_query.py:256-269 |
| `GET /api/v1/orders/{order_id}` | 路径参数 | 同上三选一（orders_query.py:273）→ `_get_order_scoped` 再收窄 | `OrderOut`（见 §2.2） | orders_query.py:272-275（`enrich_order_out` 在 services/order_response.py:94） |

补充事实：

- **没有 `offset`/`page`**：翻页只能"改窗口/改 limit"，`X-Truncated: 1` 只告诉你"还有更多"，**不给总数**。
- 日期窗口口径：`date_from/date_to` 按**下单时间 created_at**、经 `business_range_utc` 换算（业务当地日，含当天）；`delivered_from/delivered_to` 按**送达日当地日**（`_apply_delivered_window`，:49-73）。
- `unpriced=true` = 已派司机 且 `freight_fee` 为空 且 状态不在（待派单/已撤销）。
- 路由顺序有讲究：静态路径 pending-dispatch-count 必须在 /{order_id} 之前。
- ⚠️ docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md 把 `GET /orders/{order_id}` 标成「**公开**」，那是索引生成器没认出来 —— 源码里权限依赖确实在（orders_query.py:273）。**以源码为准。**

### 1.4 backend/app/api/v1/orders_lifecycle.py —— 创建/编辑/异常/恢复/删除

| 方法 + 路径 | 参数(body) | 权限 | 说明 / 位置 |
| --- | --- | --- | --- |
| `DELETE /api/v1/orders/{order_id}`（204） | — | `require_roles(SHIPPER, DISPATCHER)` + 体内：货主必须 `status==CANCELLED` 且有 ORDER_DELETE_CANCELLED；派单员任意状态 | **软删进隔离区 30 天**；已在隔离区再删 → 400；写 ORDER_DELETE 日志；orders_lifecycle.py:39-100 |
| `POST /api/v1/orders`（201） | `OrderCreate` | ORDER_CREATE | 委托 commands/order.py；初始 PENDING_DISPATCH；返回 `OrderOut`；:103-119 |
| `PATCH /api/v1/orders/{order_id}` | `OrderUpdate` | ORDER_EDIT | 部分更新；:122-134 |
| `PATCH /api/v1/orders/{order_id}/exception` | `OrderExceptionBody`(is_exception/exception_reason/exception_resolution/expected_deliver_before) | ORDER_EDIT | 重新登记异常会清 `exception_resolved_at`；写 ORDER_EXCEPTION；:137-175 |
| `POST /api/v1/orders/{order_id}/restore` | — | 仅派单员（DispatcherUser） | 单必须在隔离区（否则 404「订单不在隔离区」）；写 ORDER_RESTORE；:178-202 |

### 1.5 backend/app/api/v1/orders_payment.py —— 现场收款 / 挂账（2 端点 + 4 个私有助手）

| 方法 + 路径 | 参数 | 权限 | 说明 / 位置 |
| --- | --- | --- | --- |
| `POST /api/v1/orders/{order_id}/pay` | — | ORDER_EDIT | 先 `lock_order_row` 再判 → `_reject_if_already_collected` → 写 `payment_method="cash"`、`paid=True`、清 arrears 指向。**这一路不写收款单、不写现金流水**（只改标记）；:206-254 |
| `POST /api/v1/orders/{order_id}/charge` | `OrderChargeBody`(arrears_unit_id 或 arrears_unit_name，给名字时 `find_or_create_unit` 自动建) | ORDER_EDIT | 写 `payment_method="arrears"`、`paid=False`；已收款不许改回挂账；:257-297 |
| 助手 | — | — | `_already_collected`(:29，判据=paid 或"指向本单的 direction=in 且未软删的 CashFlow")；`_apply_complete_payment`(:52)；`_payment_scoped_order`(:153，已撤销/已退货 400)；`_reject_if_already_collected`(:167，文案写明"系统目前没有撤销收款的入口") |

### 1.6 backend/app/api/v1/orders_delivery.py —— 送达 / 接单 / 备注 / 导航 / 撤销

| 方法 + 路径 | 参数 | 权限 | 说明 / 位置 |
| --- | --- | --- | --- |
| `POST /orders/{order_id}/complete-with-upload` | multipart：files(必填多图)、driver_remark、payment(cash 或 arrears)、damage_items(JSON 字符串 `[{order_product_id, quantity}]`)、damage_note | ORDER_COMPLETE_DRIVER | 三道门（归属/状态 ACCEPTED/有文件）在**落盘之前**判；outbox orders.delivered + ledger.updated；:44-95 |
| `POST /orders/{order_id}/driver-ack` | — | 仅登录 + **仅司机本人** | 司机接单状态跃迁；outbox orders.driver_acked；:98-122 |
| `POST /orders/{order_id}/driver-note` | `{note}` | ORDER_INTERNAL_NOTE + 体内 派单员或司机 | 追加 `internal_notes` 累计文本（前缀 `[司机 MM-DD HH:MM]`）；先锁再追加；:125-161 |
| `POST /orders/{order_id}/navigation` | `OrderNavigationBody`(lat/lng/name/detail_address) | 仅登录 + 派单员或司机 | **只补不改**（已有坐标 400）；写 places 共享地点库 + shipper_locations；写 ORDER_NAVIGATION_FILL；:164-290 |
| `POST /orders/{order_id}/complete` | `OrderCompleteBody`(delivery_photo_urls、driver_remark、damage_items、damage_note、payment) | ORDER_COMPLETE_DRIVER | 与上传版同一业务；outbox 同上；:311-340 |
| `POST /orders/{order_id}/cancel` | `{reason}` | 货主(本人+ORDER_CANCEL_SHIPPER) 或 派单员(ORDER_CANCEL_DISPATCHER+挡已收款) | 仅 待派单/已派单 可撤销；隔离区单 404；:343-397 |
| 助手 `_parse_damage_items` | — | — | 货损解析成 `[{order_product_id, quantity}]` —— **货损挂在订单商品行上**（不是订单上）；:293 |

### 1.7 backend/app/api/v1/orders_assignment.py —— 派单 / 定价 / 拆单 / 运费 / 撤回

| 方法 + 路径 | 参数(body) | 权限 | 说明 / 位置 |
| --- | --- | --- | --- |
| `POST /orders/batch-assign` | `OrderBatchAssignBody`(driver_id、order_ids、internal_note、collect_cash) | ORDER_DISPATCH | **逐单成功/失败**：返回 `results: [{order_id, success, detail}]`；:71-112 |
| `POST /orders/{order_id}/price-freight` | `OrderFreightPriceBody`(freight_fee、category_id、save_template、price_name、template_name) | ORDER_DISPATCH | 手动定价；唯一写入口 `order_money.record_freight_decision(source=FREIGHT_SOURCE_MANUAL)`；已送达补价会 `resync_open_piece_bill`；:115-301 |
| `POST /orders/{order_id}/assign` | `OrderAssignBody`(driver_id、internal_note、freight_fee、collect_cash、driver_piece_amount、driver_commission_rate) | ORDER_DISPATCH | 记规则快照；**freight_fee=None 即不改（不清空）**；outbox orders.assigned + pending_pool_changed；:304-376 |
| `POST /orders/{order_id}/split` | `OrderSplitBody`(parts 比例) | ORDER_DISPATCH | 返回 `list[OrderOut]` 子单；:379-402 |
| `POST /orders/{order_id}/freight` | `OrderFreightBody`(freight_fee，可 null 清空回待定) | ORDER_DISPATCH | 已送达/已撤销/已退货 400 锁定；写 ORDER_FREIGHT(before/after)；:405-461 |
| `POST /orders/{order_id}/recall` | `OrderRecallBody`(reason) | ORDER_RECALL | outbox orders.revoked(司机)/orders.recalled(货主)；:464-494 |

### 1.8 backend/app/api/v1/order_products.py —— 订单商品行（prefix=/order-products）

| 方法 + 路径 | 参数 | 权限 | 关键返回 / 位置 |
| --- | --- | --- | --- |
| `GET /api/v1/order-products` | **order_id(必填)** | ORDER_READ_ALL | `list[OrderProductOut]`，**带行 id**（定位/改/删必须走这里；下单用的 OrderProductLine 没有 id）；:160-170 |
| `POST /api/v1/order-products`（201） | `OrderProductCreate`(order_id、product_id、product_name_snapshot、quantity、unit_price、line_total、unit) | ORDER_PRODUCT_EDIT | 成本快照 `cost_price_snapshot` 在此定格；写 ORDER_LINE_ADD + 预占重算；:173-226 |
| `GET /api/v1/order-products/{line_id}` | — | ORDER_READ_ALL | `OrderProductOut`；:229-234 |
| `PATCH /api/v1/order-products/{line_id}` | `OrderProductUpdate` | ORDER_PRODUCT_EDIT | `line_total` 按 单价×数量 重算；写 ORDER_LINE_UPDATE；:237-290 |
| `DELETE /api/v1/order-products/{line_id}`（204） | — | ORDER_PRODUCT_EDIT | 写 ORDER_LINE_DELETE + 释放预占；:293-320 |
| 可编辑门 | `LINE_EDITABLE_STATUSES`(待派单/派单中/已接单) | — | `_locked_editable_order` 先锁再判 + 原子占位 UPDATE，rowcount≠1 → 400「这张单刚刚被改过」；:83-87、:90-157 |

### 1.9 backend/app/api/v1/driver_bills.py —— 司机应付明细（prefix=/driver-bills）

| 方法 + 路径 | 参数 | 权限 | 关键返回 / 位置 |
| --- | --- | --- | --- |
| `GET /api/v1/driver-bills` | `driver_id`、`month`(^\d{4}-\d{2}$)、`status`、`bill_type`、`include_deleted`（缺省过滤掉"订单已进回收站"的账单：`or_(order_id IS NULL, Order.deleted_at IS NULL)`）。**无日期区间、无分页**（全量返回） | 仅登录 + 体内：派单员看全部，司机强制 `driver_id=current.id`，其余 403「仅派单员/司机可查看」 | `list[DriverBillOut]`（手工拼）：id、driver_id、bill_type、**order_id**、month、amount、status、**settled_doc_id**、note、driver_name、**order_no**、rule_id、rule_name、piece_amount、commission_amount → **可一路点到订单**；:38-126 |
| `POST /api/v1/driver-bills/generate` | `DriverBillGenerateBody`(bill_type=SALARY\|PIECE、month、driver_id?) | 仅派单员 | SALARY=按月薪司机幂等生成月薪单（行锁 `with_for_update`）；PIECE=该月已送达/运费非空/未软删/`per_order_pay_filter()` 的单补单，金额走 `pay_for_order`（规则+快照）；写 DRIVER_BILL_GENERATE 汇总日志；返回 `list[DriverBillOut]`；:129-289 |

月份口径 `_bill_month` = 业务当地月（business_local）。

### 1.10 backend/app/api/v1/driver_settlements.py —— 司机结算单（prefix=/driver-settlements）

状态机 DRAFT→CONFIRMED→PAID→CANCELLED；`_must_dispatcher`（:22-24）非派单员 403「仅派单员可操作」。

| 方法 + 路径 | 参数 | 权限 | 关键返回 / 位置 |
| --- | --- | --- | --- |
| `GET /api/v1/driver-settlements` | `driver_id`、`month`(^\d{4}-\d{2}$)、`status`。**无日期区间、无分页**（order_by month desc, id desc） | 仅登录 + 体内（司机强制 driver_id=自己；其余非派单员 403「仅派单员/司机可查看」） | `list[DriverSettlementOut]`：id、driver_id、settle_type、month、period_from、period_to、amount、status、**order_ids**、**bill_ids**、adjustment、paid_at、method、operator_id、note、driver_name、created_at → **order_ids 可点订单**；:27-77 |
| `POST /api/v1/driver-settlements` | `DriverSettlementCreate`(driver_id、settle_type=PIECE\|SALARY、month、amount 可空=按范围 OPEN 明细汇总、note) | 仅派单员 | 委托 `accounting_service.create_settlement`；先 flush 拿 id 再写 SETTLEMENT_CREATE 日志（含 bill_count）；:80-121 |
| `PATCH /api/v1/driver-settlements/{settlement_id}` | `SettlementActionBody`(action ^(confirm\|pay\|cancel)$、method ^(cash\|transfer\|wechat\|bank)$、paid_at) | 仅派单员 | 分别调 confirm/pay/cancel_settlement；写 SETTLEMENT_STATUS 日志；:124-177 |

### 1.11 backend/app/api/v1/driver_billing_rules.py —— 司机计费规则（prefix=/driver-billing-rules，558 行）

模块头声明：**金额算法一行都不在本文件**（全在 `services/driver_pay.py`）；挂载**只有一条写路径** `POST /driver-billing-rules/attach`。

| 方法 + 路径 | 参数 | 权限 | 关键点 / 位置 |
| --- | --- | --- | --- |
| `GET /api/v1/driver-billing-rules` | `vehicle_type`、`deleted_only` | ORDER_DISPATCH | 排序走 `usage_service.with_popularity`（常用度→先创建在前）；出参含 id/name/vehicle_type/salary/piece_amount/piece_unit/commission_base/commission_rate/piece_mode/template_ids/template_briefs/categories/commission_product_ids/commission_product_names/remark/summary/attached_count/is_deleted；:280-296 |
| `POST /api/v1/driver-billing-rules`（201） | `DriverBillingRuleCreate` | ORDER_DISPATCH | `_check_products/_check_categories/_check_templates` + `validate_rule_params`（中文 400）；**同名 409「已经有一份叫「X」的规则了（名字要能唯一认出它）」**；写 DRIVER_RULE_UPSERT(op=create)；:299-342 |
| `PUT /api/v1/driver-billing-rules/{rule_id}` | 部分更新（exclude_unset；空 patch 400「没有要改的内容」） | ORDER_DISPATCH | 回收站里的规则 400「这份规则在回收站里，先恢复再改」；改名重名 409；**改规则不动历史账单**（派单时已快照进订单）；:345-421 |
| `DELETE /api/v1/driver-billing-rules/{rule_id}`（204） | — | ORDER_DISPATCH | **还挂着司机就不许删**：400「还有 N 个账号挂着这份规则，先给他们换掉或解挂再删」；软删；:424-453 |
| `POST /api/v1/driver-billing-rules/{rule_id}/restore` | — | ORDER_DISPATCH | 没删过 400「这份规则没有被删除，不需要恢复」；名字被占 409；:456-480 |
| `POST /api/v1/driver-billing-rules/attach` | `AttachRuleBody`(driver_id、rule_id；**rule_id=null = 解挂**，返回 null) | **Permission.USER_MANAGE** | 三条拦截：目标不是司机 400「计费规则只能挂给司机账号」、规则在回收站 400、**车型对不上** 400（中文写明规则限什么车型、司机是什么车型）；写 DRIVER_RULE_ATTACH(op=attach/detach、before/after、fallback=snapshot_mode(driver))；:483-558 |

### 1.12 backend/app/api/v1/freight_settlement.py —— 司机运费结算（prefix=/freight-settlement）

| 方法 + 路径 | 参数 | 权限 | 关键返回 / 位置 |
| --- | --- | --- | --- |
| `GET /api/v1/freight-settlement` | 三选一（否则 400「需提供 month 或 from/to 范围」）：`month`(YYYY-MM，`_month_range` :20-33)；或 `from`(alias from_) + `to`(ISO 时间，含起不含止)；**from>to 当场 400「开始日期不能晚于结束日期」**（:55-56，否则空列表会被读成"确实不用付"）。**无 limit/offset**（全量，order_by delivered_at desc） | **无 require_permission**，只 `Depends(get_current_user)`；体内按角色收窄（司机只回自己，其余非派单员 403「仅派单员或司机可查看」） | `{"month": month, "groups": [...]}`；每个 group = {driver_id, driver_name, driver_phone（dialable_phone 唯一口径）, driver_active, count, total, **orders: [...]**}，orders 每项含 **order_id / order_no** / delivered_at / freight_fee / pay_total / pay_piece / pay_commission / delivery_description / address_detail → **可一路点到订单**；groups 按 -total 排序；:36-142（:121-134） |

口径：status==DELIVERED、delivered_at 在窗口、deleted_at IS NULL、`per_order_pay_filter()`（计件司机；判据唯一在 driver_pay）。窗口是**当地墙上时间 → to_utc_naive 换算**（:64-65，否则东八区当地 00:00~08:00 送达的单整段漏掉）。金额走 `pay_for_order(o)`（与账单/绩效同一函数，:118）；注释写明 freight_fee 是"货主那头的价"，**不再等于司机应得**。

### 1.13 backend/app/api/v1/cash_flows.py —— 资金流水总账（prefix=/cash-flows）

全部端点权限 = **DispatcherUser**（仅派单员；全公司经营数据）。共用筛选 `_scoped_stmt`（:21-51）：**恒过滤 `CashFlow.is_deleted.is_(False)`**（已撤销的流水一律不出现）；direction（`func.lower` 大小写不敏感）、biz_type、party_type、party_id、flow_date 日期窗口（走 `core.date_window.date_window`，格式错/顺序反均 400）。

| 方法 + 路径 | 参数 | 关键返回 / 位置 |
| --- | --- | --- |
| `GET /api/v1/cash-flows` | direction / biz_type / party_type / party_id / date_from / date_to / `limit`(默认 200，**ge=1 le=1000**) | `list[CashFlowOut]`；order_by flow_date desc, id desc；多取一行交给 finish_page 写 X-Truncated；:54-73 |
| `GET /api/v1/cash-flows/summary` | 同参数（除 limit） | SQL 侧 SUM 出 income/expense/net/count 四个**字符串**金额。存在理由（:89-93，注释实测）：客户端拉一页自己求和会少算——同窗口默认 limit 只拿 200 条/流入 ¥18,842，limit=1000 拿 273 条/流入 ¥48,905.50，**页面少算 62%**，还会和 Excel 导出（SQL 侧全窗口求和）对不上；:76-117 |
| `GET /api/v1/cash-flows/breakdown` | 只有 date_from/date_to | 按 (direction, biz_type) 分组求和 → {income:[{biz_type, amount, count}], expense:[…], income_total, expense_total, net, count}，每桶按金额降序；biz_type 给的是**枚举名**（中文由客户端 ReportFinance.bizLabel 翻）；NULL/空串照样占一行；只有 `lower(direction)=="in"` 算收入，其余（含历史脏值）归支出；:120-186 |

### 1.14 backend/app/api/v1/operation_logs.py —— 操作日志（prefix=/operation-logs）

| 方法 + 路径 | 参数 | 权限 | 关键返回 / 位置 |
| --- | --- | --- | --- |
| `GET /api/v1/operation-logs` | `order_id`、`operator_id`、`skip`(ge=0)、`limit`(默认 200，**ge=1 le=1000**) | `require_permission(Permission.OPERATION_LOG_READ)` | order_by id desc + offset(skip) + limit+1 判截断（finish_page）；注释：`?limit=-5` 在 SQLite 是不限量（实测返回全表 986 行减 5）、生产 MySQL 直接 500；:30-56 |
| `GET /api/v1/operation-logs/{log_id}` | — | 同上 | 不行 404「未找到对应记录」；:59-68 |
| 出参 `OperationLogOut` | — | — | `_out`（:16-27）补两个"用户看得懂"的字段：`operator_name`（姓名优先、没有用手机号）、`order_no`（join 订单表）；其余字段见 schemas/operation_log.py |

### 1.15 backend/app/api/v1/invoices.py —— 发票台账（prefix=/invoices，FEAT-0014 税账）

权限**不新建权限点**：写（登记/改/开具/作废/删/恢复）= `require_permission(Permission.LEDGER_EDIT)`（:56）；读（列表/详情）= `Permission.ORDER_DISPATCH`（:58）。状态机 REGISTERED→ISSUED→VOIDED；**只有 REGISTERED 能改**。`_money`（:61-65）金额出参一律两位小数字符串。

| 方法 + 路径 | 参数 | 关键点 / 位置 |
| --- | --- | --- |
| `GET /api/v1/invoices` | `direction`(^(OUTPUT\|INPUT)$)、`status`(alias status_)、`date_from`/`date_to`（开票日期，走 core.date_window）、`supplier_id`、`customer_id`、`keyword`（票号模糊）、`include_deleted`(默认 false)、`limit`(默认 100，**ge=1 le=500**)、`offset`(ge=0) | ⚠️ **本仓库唯一同时有 limit+offset 的列表端点**；:117-156 |
| `GET /api/v1/invoices/{invoice_id}` | — | 回收站里的也照给；:159-166 |
| `POST /api/v1/invoices`（201） | `InvoiceCreate`(direction、invoice_no、invoice_date、amount、tax_rate、tax_amount、supplier_id、customer_id、**purchase_order_ids**、**ledger_ids**、note) | ⚠️ 进项票必须挂 ≥1 张采购单；销项票挂账本条目（0..N），挂了的客户必须一致（`tax_service._check_links`）；:169-196 |
| `PATCH /api/v1/invoices/{invoice_id}` | 部分更新 | 只改已登记的票；:199-214 |
| `POST /api/v1/invoices/{invoice_id}/issue` | — | 推 ISSUED，重复推进被拦；:217-226 |
| `POST /api/v1/invoices/{invoice_id}/void` | — | 作废/冲红：不进税汇但仍留台账；:229-241 |
| `DELETE /api/v1/invoices/{invoice_id}`（204） | — | 软删进回收站；:244-252 |
| `POST /api/v1/invoices/{invoice_id}/restore` | — | 恢复；票号被占 409（不悄悄改号）；:255-267 |

出参 InvoiceBrief（`_out` :82-103）：id、direction、invoice_no、invoice_date、amount、tax_rate、tax_amount、status、supplier_id、supplier_name、customer_id、customer_name、note、counts_in_tax、**purchase_order_ids**、**ledger_ids**、is_deleted、created_at。→ **发票不直接挂 orders**，只挂采购单与账本条目。

### 1.16 backend/app/api/v1/expenses.py —— 开销单（prefix=/expenses，权限均 DispatcherUser）

| 方法 + 路径 | 参数 | 关键返回 / 位置 |
| --- | --- | --- |
| `GET /api/v1/expenses` | `category`（自由字符串名册）、`driver_id`、`date_from`/`date_to`（exp_date 列，走 core.date_window，顺序反 400）。**无 limit/offset、无 vehicle_id 参数、无 order_id 参数**（全量） | `list[ExpenseOut]`：id、exp_date、category、amount、**driver_id**、**vehicle_id**、**order_id**、note、operator_id、driver_name、vehicle_name、link_kind（分类名册带的"卡片突出哪一项"：vehicle/driver/order/none）、**order_no**、created_at → **开销可点回订单**，也可点回司机/车辆；order_by exp_date desc, id desc；:20-76 |
| `POST /api/v1/expenses` | `ExpenseCreate`(exp_date、category ≤32 字自动补进名册、amount>0、driver_id?、vehicle_id?、order_id?、note) | 委托 `accounting_service.create_expense`；**开销＝钱出去了（还会写一条 cash_flows OUT）**；写 EXPENSE_CREATE 日志（order_id=e.order_id）；:79-112 |

### 1.17 backend/app/services/stats_service.py —— 看板/绩效/异常聚合（被 api/v1/stats.py 调用）

- 窗口助手：`load_delivered_orders`（:52-70，status=DELIVERED 且 **order_date** 在区间）；`load_orders_by_delivered_at`（:73-96，按 **delivered_at** + business_range_utc，司机绩效用）；两者都排除软删。
- `_end_of_order_date`（:18-29）：下单日**当地日末**（business_day_start_utc(od+1day)）；实测准时率 82.3%（UTC 日末）vs 30.9%（当地日末），差 183 单。`_on_time_delivered`(:32-38)、`_delivery_seconds`(:41-44)、`_has_photos`(:47-49)。
- `TOP_PRODUCTS = 12`（:108 模块级常量；曲线只画前 12 名，导出侧读它并如实写进文件）。
- `shipper_product_chart(db, date_from, date_to, granularity, metric)`（:111-159）：按 (期间, product_name_snapshot) 累加 quantity 或 amount，取前 12 名 → (periods, series)。
- `shipper_activity(db, shipper_id, …)`（:162-221）：shipper_id/shipper_name/order_count/delivered_count/total_spent/avg_order_value/orders_per_week/top_products（前 8，含 product_name/count/amount）。
- **`product_drilldown(db, product_name, date_from, date_to)`（:224-254）：按商品名下钻到订单行**，每条 = {**id（订单 id）**, order_no, order_date, status, shipper_name, product_name, quantity, line_total}。← **「按商品筛订单」唯一现成路径**（订单行粒度；仅 status=DELIVERED 且 order_date 在窗口）。
- `driver_performance`（:257-331）：按 driver_id 聚合 = {driver_id, driver_name, completed_count, on_time_rate, avg_delivery_seconds, photo_upload_rate, **billing_mode**（snapshot_mode(du).upper()）, **freight_owed**（PIECE 或有过按单应付时 = Σ pay_for_order(单) − 该司机 PAID 结算单金额合计，下限 0；否则 null）}，按 completed_count 降序。
- `shipper_performance`（:334-372）：按 shipper_id 聚合，无账号货主按 temp_shipper_name 归组（"临时货主"）= {shipper_id, shipper_name, order_count, total_amount(Σ line_total)}，按 order_count 降序。
- `auto_exception_reason(o, now)`（:375-395）：已解决（exception_resolved_at 非空）不再复现；CANCELLED→"已撤销/撤回订单"；PENDING_DISPATCH 超 4 小时→"待派超时（超过4小时未派单）"；DISPATCHED/ACCEPTED 且 expected_deliver_before<now→"超时未送（超过预计送达时间）"；DELIVERED 且 delivered_at>expected_deliver_before→"逾期送达（超过预计送达时间）"。
- `exception_orders`（:397-475）：is_exception=True 的单 + 自动判定命中的单（去重），每条含 id/order_no/order_date/status/shipper_name/driver_name/exception_reason/exception_resolution/expected_deliver_before/delivered_at/exception_resolved_at；按 order_date 窗口、软删排除、按 id 降序。

### 1.18 backend/app/api/v1/stats.py —— 看板端点（prefix=/stats，7 个端点，133 行）

除 /export 外权限全部 `require_permission(Permission.STATS_READ)`，且窗口一律 `ensure_date_order(date_from, date_to)`（顺序反 400）。

| 装饰器行 | 端点 | 参数 | 返回 |
| --- | --- | --- | --- |
| :30-48 | `GET /stats/shipper-product-chart` | date_from（必填，含起）、date_to（必填，含止）、granularity(month\|year，默认 month)、metric(quantity\|amount，默认 quantity) | ShipperProductChartOut{granularity, metric, categories, series} |
| :51-61 | `GET /stats/shipper-activity` | shipper_id(必填)、date_from、date_to | ShipperActivityOut |
| :64-74 | **`GET /stats/product-drilldown`** | **product_name(必填，min_length=1)**、date_from、date_to | `list[DrilldownOrderItem]`（含订单 **id/order_no** → 可直接点进订单详情） |
| :77-90 | `GET /stats/driver-performance` | date_from、date_to | DriverPerformanceOut{period_label, drivers:[DriverPerformanceRow]} |
| :93-106 | `GET /stats/shipper-performance` | date_from、date_to | ShipperPerformanceOut{period_label, shippers} |
| :109-118 | `GET /stats/exception-orders` | date_from、date_to | `list[ExceptionOrderItem]`（含 id/order_no） |
| :121-133 | `POST /stats/export` | body StatsExportBody | StreamingResponse xlsx（`stats-<from>-<to>.xlsx`） |

### 1.19 backend/app/api/v1/reports.py —— 报表中心（prefix=/reports，681 行）

头部（:1-41）从 `services/reports_service` 大量 re-export：`_window/_label/_span_label/_span/_range_dates/delivered_span_sql/load_delivered/build_turnover/build_products/build_profit/_cost_basis_note/build_arrears_summary/_money/build_vehicle_cost/build_cost_coverage/build_tax_summary/build_customer_balances`。

| 装饰器行 | 端点 | 参数 | 返回（下一层维度） |
| --- | --- | --- | --- |
| :64-76 | `GET /reports/turnover` | mode/date/date_from/date_to | TurnoverReportOut（**series 逐时段**，无逐单） |
| :79-91 | `GET /reports/products` | 同上 | ProductReportOut（**逐商品聚合，无订单标识**） |
| :94-110 | `GET /reports/profit` | 同上 | ProfitReportOut（营业额/商品成本/司机应得/开销四格 + 明细桶，只读汇合） |
| :113-130 | `GET /reports/vehicle-cost` | 同上（默认 month） | VehicleCostReportOut（每台车的折旧+该车开销+挂靠司机配送成本；**⛔ 没有收入**——订单上只有司机没有车辆） |
| :133-151 | `GET /reports/cost-coverage` | 同上 | CostCoverageReportOut（多少收入因"没有进货价"算不出成本，**missing_purchase_price[] 是商品**） |
| :157-174 | `GET /reports/tax-summary` | 同上 | TaxSummaryOut（销项/进项/增值税；唯一实现 `tax_service.sum_taxes`；无税率的票单列 untaxed_*） |
| :176-186 | `GET /reports/arrears-summary` | **只有 date_from、date_to（都必填）** | `list[dict]`（build_arrears_summary：按挂账单位/未分配分桶，含 count/amount） |
| :188-210 | `GET /reports/customer-balances` | 同统一形状 + `include_orders`(默认 false，**true = 每一行带逐单明细**) | CustomerBalancesOut；as_of = min(窗口末, 今天)（**时点账**）→ **这就是"客户欠款下钻到订单"的口子** |
| :213-234 | `GET /reports/export` | `kind` pattern ^(turnover\|products\|drivers\|customers\|finance\|audit\|profit\|vehicle-cost\|cost-coverage\|tax-summary\|customer-balances)$ + mode/date/date_from/date_to | xlsx StreamingResponse（文件名日期段=真实取数区间） |

### 1.20 客户账本三件套（顺带盘，下钻必需）

- **`GET /api/v1/ledger/entries`**（ledger.py:136-186）：货主欠款/流水主表，`LedgerOut` 带 `order_id`+`order_no`+`order_product_id` → **逐行可点订单**；支持 shipper_id/temp_shipper_name + 日期 + limit(≤5000)/offset。
- **`POST /api/v1/ledger/receipts` / `GET /api/v1/ledger/receipts`**（:734/:814）：收款单；出参 `ShipperReceiptOut` 带 **order_ids[]**（逐单核销）与 settle_mode；GET 只能按 customer_id + 日期查。
- **`GET /api/v1/shipper-ledger/settlements?order_id=`**（shipper_ledger.py:327-369）：**按订单号精确反查这张单的核销记录**（客户自己那本账，ShipperOnly）。
- **`GET /api/v1/freight-settlement`**（司机的钱）、**`GET /api/v1/driver-bills?driver_id=`**（应付明细，带 order_id）、**`GET /api/v1/driver-settlements?driver_id=`**（结算单，带 order_ids/bill_ids）。
- 挂账单位名册 **`/api/v1/arrears-units`**（arrears.py:28/47/137/204/273，权限全 LEDGER_EDIT）；车辆→司机挂载 **`POST /api/v1/vehicles/{vehicle_id}/driver`**（vehicles.py:423）。

---

## 2. 四个必答问题

### ① 有没有「按司机 / 按货主 / 按商品 / 按车辆」筛订单的列表接口？

**订单列表只有一个：`GET /api/v1/orders`（orders_query.py:76-253），它只认四种筛法。**

| 想按什么筛 | 能不能 | 参数名 / 替代路径 |
| --- | --- | --- |
| **货主（客户）** | ✅ 直接支持 | `shipper_id`(int)；无账号货主用 `temp_shipper_name`（**两者互斥**：给了 temp_shipper_name 就强制 `shipper_id IS NULL`，orders_query.py:81-99） |
| **司机** | ❌ 没有 `driver_id` 参数 | ①司机本人调 `GET /orders` 由角色作用域自动只看自己（:189-201）；②派单员用 `q=<司机姓名或手机号>`（搜索覆盖列含司机 full_name/phone，:113-181）；③要"按司机成组"取订单只有 `GET /freight-settlement`（司机→订单带 order_id）；④`GET /driver-bills?driver_id=` 给应付明细（带 order_id，但只覆盖计件/月薪应付的单）；⑤`GET /stats/driver-performance` **只有聚合数字，没有订单 id** |
| **商品** | ❌ 没有 `product_id` 参数 | 唯一现成路径 `GET /stats/product-drilldown?product_name=&date_from=&date_to=`（stats_service.py:224-254 → 订单行 + **订单 id**，但只覆盖 status=DELIVERED 且下单日在窗口）；次选 `GET /ledger/entries` 按商品名逐行看货款（行带 order_id） |
| **车辆** | ❌ 没有 `vehicle_id` 参数（**订单表根本没有车辆字段**） | 只能反向走：`POST /vehicles/{id}/driver` 得到"这台车挂哪个司机"→ 再用司机路径；`GET /expenses?driver_id=` 的开销也带 order_id |

**日期区间**：有，两条互不干扰的窗口 —— `date_from`/`date_to`（按**下单时间** created_at，业务当地日、含当天）与 `delivered_from`/`delivered_to`（按**送达日**当地日、含当天，账本口径）。

**分页**：`GET /orders` 只有 `limit`（**ge=1、le=5000**，缺省 `DEFAULT_LIST_LIMIT=300`，:97/:109-110），**没有 offset/page**；返回裸数组，截断信息在响应头 `X-Result-Limit` 与 `X-Truncated: 1`（只告诉你"还有更多"，**不给总数**）。→ 真分页只能靠时间窗切段。

**仓库里真正带 offset 的列表端点**（做深下钻时优先用它们）：`GET /ledger/entries`（limit≤5000 + offset）、`GET /invoices`（limit≤500 + offset）、`GET /shipper-ledger/settlements`（limit≤2000 + offset）、`GET /operation-logs`（skip + limit≤1000）。
**完全不分页（全量返回）的**：`GET /driver-bills`、`GET /driver-settlements`、`GET /freight-settlement`、`GET /expenses`、`GET /ledger/receipts`、`GET /reports/arrears-summary`。

### ② 单张订单的详情接口是哪个、返回什么？

`GET /api/v1/orders/{order_id}`（orders_query.py:272-275）→ **`OrderOut`**（schemas/order.py:169-251，装配在 services/order_response.py:94-163）。权限 `require_any_permission(ORDER_READ_OWN, ORDER_READ_ASSIGNED, ORDER_READ_ALL)`（:273）+ `_get_order_scoped` 按角色收窄（orders_common.py:57）。

| 你要的 | 有没有 | 字段 |
| --- | --- | --- |
| **商品行** | ✅ | `order_products: list[OrderProductOut]`（id、product_id、product_name_snapshot、quantity、unit、unit_price、line_total、**damage_quantity**、**returned_quantity**） |
| **收款 / 挂账** | ✅（标记级） | `payment_method`("cash"/"arrears")、`paid`、`arrears_unit_id`/`arrears_unit_name`；钱：`goods_amount`、`settled_amount`、`refunded_amount`、`arrears_amount`、`returned_amount`（恒等式 goods_amount − returned_amount == (settled_amount − refunded_amount) + arrears_amount，:248-249）。**不含收款单/核销明细** → 要另开 `GET /shipper-ledger/settlements?order_id=` 或 `GET /ledger/receipts?customer_id=` |
| **货损** | ✅ | 行上 `damage_quantity`（件数）+ 单上 `damage_note`（备注）；**没有单独的货损单**（货损在送达时按 `damage_items[{order_product_id, quantity}]` 落库，并生成一条 `EXPENSE_LOSS` 现金流水） |
| **付款方式** | ✅ | `payment_method`、`paid`；派单时是否收现金 `collect_cash`；司机侧运费可见性 `freight_visible` |
| **运费 / 司机应得** | ⚠️ 部分 | `freight_fee`（货主那头的价）+ `driver_billing_mode`/`driver_piece_amount`/`driver_commission_rate`；**"这个司机这单到底拿多少"必须调 driver_pay.pay_for_order**——订单详情里的 freight_fee 不等于司机应得 |
| **成本 / 毛利** | ❌ | `cost_price_snapshot` **不在任何出参里**（OrderProductOut 不含它）→ 订单级毛利只能看 `GET /reports/products` 与 `/reports/cost-coverage` |
| **角色差异** | ⚠️ | 同一个端点三种角色三种形状：SHIPPER → `hide_driver_pay` + `internal_notes=""`；DRIVER → 每行 `unit_price/line_total=None`、`goods_amount=None`、四个客户金额字段=Decimal("0")；DISPATCHER → `freight_visible=True`（order_response.py:142-163） |

### ③ 司机运费 / 司机账单结算 / 客户挂账对账各自走哪个接口，能不能一路点到订单？

| 环节 | 接口 | 能不能点到订单 |
| --- | --- | --- |
| **司机运费**（该给谁多少） | `GET /api/v1/freight-settlement?month=` 或 `?from=&to=`（freight_settlement.py:36-142） | ✅ `groups[].orders[].order_id` + `order_no`（还有 pay_total/pay_piece/pay_commission） |
| **司机账单（应付明细）** | `GET /api/v1/driver-bills?driver_id=&month=&status=&bill_type=`（driver_bills.py:38-126） | ✅ `DriverBillOut.order_id` + `order_no` + `settled_doc_id`；生成走 `POST /driver-bills/generate` |
| **司机结算单** | `GET /api/v1/driver-settlements?driver_id=&month=&status=`（driver_settlements.py:27-77） | ✅ `order_ids[]`（订单 id 数组）+ `bill_ids[]`（driver_bills.id）；确认/付款/作废走 `PATCH /driver-settlements/{id}` 的 action=confirm\|pay\|cancel |
| **客户挂账/欠款（聚合）** | `GET /api/v1/ledger/accounts?kind=shipper|member&date_from=&date_to=`（ledger.py:189）；`GET /api/v1/reports/arrears-summary?date_from=&date_to=`（reports.py:176） | ⚠️ 只有金额/笔数（arrears-summary 还按挂账单位分桶）**没有 order_id** |
| **客户挂账（逐单）** | `GET /api/v1/reports/customer-balances?…&include_orders=true`（reports.py:188-210） | ✅ 每行 `orders[].order_id` + `order_no`（含 receivable/collected/arrears/账龄 bucket/days） |
| **客户账本流水** | `GET /api/v1/ledger/entries?shipper_id=&date_from=&date_to=&limit=&offset=`（ledger.py:136-186） | ✅ `LedgerOut.order_id` + `order_no` + `order_product_id`（逐行可点） |
| **客户核销/收款** | `POST /api/v1/ledger/receipts`（逐单核销 itemized / 滚动 rolling）；`GET /ledger/receipts?customer_id=&date_from=&date_to=`；客户自看 `GET /shipper-ledger/settlements?order_id=` | ✅ 收款出参 `order_ids[]`；`GET /shipper-ledger/settlements?order_id=` 是**按订单反查核销记录**的唯一口子 |

一句话：**司机侧三段（运费→账单→结算）都能一路点到订单；客户侧聚合卡（accounts / arrears-summary）只能到"挂账单位/货主"这一层，要订单必须换 customer-balances?include_orders=true 或 ledger/entries。**

### ④ 现金流水、发票、费用这三类记录能不能点回原单据（字段名）？

| 类别 | 回原单据的字段 | 细节 |
| --- | --- | --- |
| **现金流水** | **`CashFlowOut.order_id`**（订单）+ **`CashFlowOut.doc_id`**（**源单**） | `CashFlowOut`（schemas/accounting_v2.py:266-281）：id、flow_date、direction、amount、party_type、party_id、party_name、channel、biz_type、order_id、doc_id、note、operator_id、created_at。⚠️ `doc_id` **没有类型字段**，指向哪张表由 `biz_type` 决定：收款单→`receipt.id`；货损/手工开销→`expenses.id`；司机结算打款→`driver_settlements.id`；供应商付款→`supplier_payables.id`（accounting_service.py:300-320 / :528-567 / :775-793 / :870-885，supplier_service.py:224）。滚动收款的流水 `order_id=None`（不绑单）；`GET /cash-flows` **没有 order_id 查询参数**，只能按 party_type/party_id + 日期筛完再看行上的 order_id |
| **费用（开销单）** | **`ExpenseOut.order_id`** + `order_no`（还能 `driver_id`/`vehicle_id`） | 每次建开销会**同时写一条 cash_flows OUT**（accounting_service.py:870-885），所以同一笔钱在 `/expenses` 与 `/cash-flows` 各有一条、靠 `doc_id=expenses.id` 对上 |
| **发票** | ❌ **没有 order_id** | 只有 **`purchase_order_ids[]`**（进项票必挂采购单）与 **`ledger_ids[]`**（销项票挂账本条目）。要回到订单得经"账本行"那一跳：`ledger_ids → LedgerOut.order_id` |

---

## 3. 下钻链路表（汇总指标 → 接口 → 下一层维度 → 再往下能不能到订单）

| # | 汇总指标（报表中心卡） | 用哪个接口 | 下一层能拿到的维度 | 再往下能到订单吗 |
| --- | --- | --- | --- | --- |
| 1 | 营业额 / 单量 / 均价 | `GET /reports/turnover`（reports.py:64） | `series[]` 逐时段的 amount/orders/freight | ❌ 只有时段，没有订单 |
| 2 | 营业额 · 按时段曲线 | 同上 `series` | label + amount + orders + freight | ❌ |
| 3 | 司机应得（配送成本） | `GET /reports/turnover.total_freight` / `/reports/profit.delivery_cost` | 只有一个总数（= Σ driver_pay.pay_for_order） | ❌ → 换 #9/#10 |
| 4 | 商品销售排行 | `GET /reports/products`（reports.py:79） | `items[]` 逐商品（qty/amount/order_count/cost/damage_qty） | ❌ **没订单标识** → 必须换 #6 |
| 5 | 商品曲线（前 12 名） | `GET /stats/shipper-product-chart`（stats.py:30） | categories + series（按期间×商品名） | ❌ |
| 6 | **单商品 → 订单行** | `GET /stats/product-drilldown?product_name=&date_from=&date_to=`（stats.py:64） | 订单行：order_no/order_date/status/shipper_name/quantity/line_total | ✅ **带订单 id**（仅 DELIVERED + 下单日在窗口） |
| 7 | 毛利 / 成本覆盖率 | `GET /reports/profit` / `GET /reports/cost-coverage`（reports.py:94/:133） | 成本桶 + `missing_purchase_price[]`（商品级） | ❌ |
| 8 | 车辆成本 | `GET /reports/vehicle-cost`（reports.py:113） | `per_vehicle[]`（折旧/该车开销/挂靠司机配送成本） | ❌ **订单上没有车辆**（表里正数写死这一点） |
| 9 | 司机绩效（完成数/准时率/照片率） | `GET /stats/driver-performance`（stats.py:77） | `drivers[]` = driver_id + billing_mode + freight_owed | ⚠️ 有 driver_id 但要再查 —— 而 #1 类列表**没有 driver_id 参数**，只能 `q=司机姓名/手机号` |
| 10 | **司机运费（该给谁多少）** | `GET /freight-settlement?month=` 或 `?from=&to=`（freight_settlement.py:36） | `groups[]` 按司机：count/total + `orders[]` | ✅ `orders[].order_id` + order_no + pay_total |
| 11 | 司机账单（应付明细） | `GET /driver-bills?driver_id=&month=&status=&bill_type=`（driver_bills.py:38） | 账单行：bill_type/month/amount/status | ✅ `order_id`+`order_no`+`settled_doc_id` |
| 12 | 司机结算单 | `GET /driver-settlements?driver_id=&month=`（driver_settlements.py:27） | 结算单：settle_type/period/amount/status/method | ✅ `order_ids[]` + `bill_ids[]` |
| 13 | 货主业绩排行 | `GET /stats/shipper-performance`（stats.py:93） | `shippers[]`（shipper_id/order_count/total_amount） | ⚠️ 有 shipper_id → 用 `GET /orders?shipper_id=` 即可到订单 ✅ |
| 14 | 货主活跃度 | `GET /stats/shipper-activity?shipper_id=`（stats.py:51） | 订单数/送达数/总花费 + `top_products`（前 8） | ❌ 聚合（要订单改走 #13 的路径） |
| 15 | 挂账未收汇总（按挂账单位） | `GET /reports/arrears-summary?date_from=&date_to=`（reports.py:176） | 桶：name（挂账单位/未分配）+ count + amount | ❌ → 换 #16 |
| 16 | **客户欠款（逐单）** | `GET /reports/customer-balances?…&include_orders=true`（reports.py:188） | 行：shipper/temp/unit + balance/prepaid/账龄桶；`orders[]` 逐单 | ✅ `orders[].order_id` + order_no + receivable/collected/arrears/bucket |
| 17 | 客户账本流水 | `GET /ledger/entries?shipper_id=&date_from=&date_to=`（ledger.py:136） | 逐行：entry_date/product_name/quantity/total/source | ✅ `order_id`+`order_no`+`order_product_id` |
| 18 | 客户收款/核销 | `GET /ledger/receipts?customer_id=&date_from=&date_to=`（ledger.py:814）；客户自看 `GET /shipper-ledger/settlements?order_id=`（shipper_ledger.py:327） | 收款单：amount/method/received_at/settle_mode/`order_ids[]` | ✅（逐单核销绑订单；滚动的没 order_ids） |
| 19 | 现金流收支 | `GET /cash-flows` / `/summary` / `/breakdown`（cash_flows.py:54/:76/:120） | 流水行（biz_type/party/channel）或按 biz_type 桶 | ✅ 行上有 `order_id`（滚动收款行为 None）+ `doc_id` 回源单 |
| 20 | 开销 | `GET /expenses?category=&driver_id=&date_from=&date_to=`（expenses.py:20） | 逐笔：exp_date/category/amount/link_kind | ✅ `order_id`+`order_no`（也可 driver_id/vehicle_id） |
| 21 | 税（销项/进项/增值税） | `GET /reports/tax-summary`（reports.py:157） | 税额桶 + untaxed_* + 发票数 | ❌ → 走 #22 |
| 22 | 发票台账 | `GET /invoices?direction=&status=&date_from=&date_to=`（invoices.py:117） | 票行：invoice_no/amount/tax/status | ❌ 无 order_id；经 `ledger_ids[] → LedgerOut.order_id` 才能回订单 |
| 23 | 异常与审计 | `GET /stats/exception-orders`（stats.py:109）+ `GET /operation-logs?order_id=&operator_id=&skip=&limit=`（operation_logs.py:30） | 异常单（reason/resolution/expected_deliver_before）；日志行（action/change_content） | ✅ 异常项带 id/order_no；日志按 order_id 筛、出参带 order_no |
| 24 | 待派积压 | `GET /orders/pending-dispatch-count`（orders_query.py:256）+ `GET /orders?status=PENDING_DISPATCH&limit=` | 计数；待派单列表 | ✅ 列表本身就是订单 |
| 25 | 订单详情（下钻终点） | `GET /orders/{order_id}`（orders_query.py:272） | OrderOut：商品行/钱/付款方式/货损/照片/异常 | — 终点 |
| 26 | 订单商品行改单 | `GET /order-products?order_id=`（order_products.py:160） | 行（带行 id、damage_quantity、returned_quantity） | ✅ 行→订单 |

---

## 4. 缺口与坑（做下钻之前必须知道的 14 条）

1. **按司机/商品/车辆筛订单一律没有参数**（orders_query.py:81-99）。派单员想按司机取单只能用 `q=` 模糊搜（同名司机会串）。这是"从司机绩效下钻到订单"最主要的断点。
2. **`GET /orders` 没有 offset/page**，只有 `limit≤5000`（缺省 300）+ 响应头 `X-Truncated`/`X-Result-Limit`，**没有总数**。深下钻要自己用日期窗切段。
3. **`GET /orders` 的过滤条件写了两遍**（派单员+搜索词路径 :113-181 与其余角色路径 :183-253），历史上漏写过（date_from/unpriced 各一份）。**新增任何筛选参数必须两处同时加**，否则"某角色能筛、另一角色筛不动"。
4. **索引文档不可信**：`docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md` 把 `GET /orders/{order_id}` 标成「公开」，源码里权限依赖是有的（orders_query.py:273）。**以源码为准**；行号也会差 1 左右。
5. **报表聚合卡大多不带订单标识**（turnover 只有时段、products 只有商品、profit 只有桶、vehicle-cost 只有车）→ 任何"点一下看订单"都要另开接口，且不一定存在。
6. **vehicle-cost 永远没有收入**：订单表只有司机、没有车辆（schemas/reports.py:222-247 docstring 钉着）→ "按车算毛利"在本数据模型里做不到。
7. **订单详情不含收款/核销/流水明细**；`cost_price_snapshot` 也不在任何出参里 → 订单级成本/毛利只能看 `/reports/products`。
8. **"司机这单拿多少"只有 `services/driver_pay.py::pay_for_order` 一处**。`orders.freight_fee` 是货主那头的价；`/reports/turnover.total_freight` 是 `pay_for_order` 之和（注释实测 47,870.00 vs Σ freight_fee 24,770.00）。下钻时**别拿 freight_fee 当司机应得**。
9. **收款口径**：`POST /ledger/receipts` 的 `settle_mode` 只有 `itemized`（默认，必须绑订单且金额 **等于** 订单 line_total 合计）与 `rolling`（不绑单）。**现金流水是逐单生成的，滚动收款不写现金流水**（钱只在 `shipper_receipts`）→ "按现金流对账"会漏掉滚动收款。
10. **`CashFlowOut.doc_id` 是无类型的源单 id**，指向哪张表由 `biz_type` 决定（receipt/expense/driver_settlement/supplier_payable），前端跳转必须先查 `biz_type` 再决定跳哪。
11. **挂账的判据只有 `paid` 一条**（`build_arrears_summary` 刻意不再加 `payment_method=="arrears"`，否则两个"挂账未收"永久分叉：实测 63,006.00 vs 62,920.50 / 7 张单）；软删单不算欠款（差 ¥500）；`/ledger/entries` 走 `visible_ledger_select()` 排除隔离区订单（差 ¥4,600）。
12. **客户端自己求和会少算**：`/cash-flows` 默认只回 200 条（注释实测同窗口流入 ¥18,842 vs limit=1000 的 ¥48,905.50，**少算 62%**）→ 汇总必须用 `/cash-flows/summary` 或 `/breakdown`。同理 `GET /orders` 的 `limit` 默认 300 会把"某段时间的全部订单"悄悄截断。
13. **时间窗口口径有三种**：`/stats/*` 多数按 **order_date（下单日）**、`/stats/driver-performance` 按 **delivered_at**、`/reports/*` 按 **delivered（送达日）**；`/freight-settlement` 必须做当地时区换算（否则东八区 00:00~08:00 送达的单整段漏掉）。同一张报表混用会差 183 单（准时率 82.3% vs 30.9%）。
14. **完全不分页的端点**（`/driver-bills`、`/driver-settlements`、`/freight-settlement`、`/expenses`、`/ledger/receipts`、`/reports/arrears-summary`）在数据涨起来后会把页面拖死——下钻设计时优先选带 limit/offset 的接口，或先加窗口。

---

## 5. 建议的下钻实现（三级，每级都用现成接口）

1. **一级·汇总**：`GET /reports/*`（营业额/商品/毛利/车辆/税）+ `GET /cash-flows/summary|breakdown`（钱的收支）——注意这一级基本只有数字，**要下钻必须换接口**。
2. **二级·分组**：按要看的维度选 —— 商品 → `GET /stats/product-drilldown`；司机 → `GET /freight-settlement` 或 `GET /driver-bills?driver_id=`；客户 → `GET /reports/customer-balances?include_orders=true` 或 `GET /ledger/entries?shipper_id=`；挂账单位 → `GET /reports/arrears-summary`（这里还得再跳一步）；异常 → `GET /stats/exception-orders`。
3. **三级·订单**：`GET /orders/{order_id}`（详情）；要商品行定位/改单再 `GET /order-products?order_id=`；要这一单的收款记录 `GET /shipper-ledger/settlements?order_id=`；要这一单的流水 `GET /cash-flows`（按 party + 日期筛后看行上的 order_id）。

**唯一的真实缺口**：一级汇总卡（除 customer-balances 与 arrears 系列）**没有任何 order_id 出口**；若产品要求"任意汇总数字都能点到订单"，需要后端补三个查询参数：`GET /orders` 加 `driver_id`、加 `product_id`（或直接给定单行下钻端点）、以及把汇总接口带上可下钻的 id（★ 这是需要后端改动的地方，本轮只读盘点未改）。

---

### 附：盘点方法与复现

- 全部结论来自源码阅读，行号为本仓库工作区实际行号；关键交叉验证点：`docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md`（机器生成的端点索引）、`backend/app/models/enums.py`、`backend/app/services/driver_pay.py`（金额唯一实现）、`backend/app/services/accounting_service.py`（现金流水的每一条写入口）。
- 本文件与同目录 `backend_surface.md`、`android_ui_surface.md`（其他子代理产出）互补：本文件管"接口能不能下钻"，后者管"后端/安卓现状"。
