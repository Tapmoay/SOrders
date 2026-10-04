# 报表中心 · 资产负债表 / 库存与应付 —— 后端只读接口盘点

> 盘点范围：`backend/app/api/v1/` 下 8 个文件 + 相关 models / schemas，外加与本次需求最相关的 `reports.py` 与 `services/`。**只读盘点，未改任何生产代码。** 行号以当前 HEAD 为准。

---

## 0. 三个必答问题（先看这个）

### 0.1 这个系统有没有「库存」概念？—— **有流水 + 有结存列，但没有期初/期末快照，也没有库存金额**

| 要素 | 有没有 | 在哪 |
|---|---|---|
| 库存流水（入库/出库） | ✅ 有 | `inventory_movements`（`backend/app/models/inventory.py:11`），`change` 正数入库、负数出库 |
| 结存数量 | ✅ 有（**只有"现在"这一个数**） | `products.stock`（`backend/app/models/product.py:16`），由库存流水加减维护，商品编辑接口**改不了它** |
| 流水来源 | ✅ 三档 | `InventoryMovement.source` = `MANUAL`（手工出入库）/ `ORDER`（订单预占·实扣·回冲）/ `PURCHASE`（采购入库） |
| 预占/实扣/回冲 | ✅ 三态 | `InventoryMovement.status` = `RESERVED`（派送预占）/ `COMMITTED`（送达实扣）/ `RELEASED`（撤销回冲） |
| **期初 / 期末库存** | ❌ **没有** | 全仓 grep「期初\|期末\|结存」只命中 `services/cost_basis.py:20` 与 `services/cost_basis.py:50` 两句注释。**没有任何库存快照表**，期末库存只能靠流水回推 |
| **库存金额 / 存货科目** | ❌ **没有** | 没有任何端点算出"库存值多少钱"。`reports.py` 七个报表 + 导出里也**一个库存金额都没有**（最接近的是成本覆盖表里的一列 `stock`，见 §3.4） |
| 成本口径 | 部分 | `products.cost_price`（最新进货价，被 `record_cost` 改写）+ `product_cost_history` 区间表；**加权平均只在服务层内部算，没有端点** |
| 单位换算 | ✅ 有，但**只换数量不换钱** | `unit_conversions`（`backend/app/models/unit_conversion.py:9`），一跳、无链式 |

**一句话**：库存是「流水 + 一个实时结存列」，**没有会计意义上的存货台账**（没有期初、没有期末、没有金额、没有盘点）。

### 0.2 有没有「供应商应付」余额？—— **有，而且是全仓口径最干净的一块（时点账）**

- 应付单：`supplier_payables`（`backend/app/models/supplier.py:37`），字段 `amount Numeric(12,2)` + `doc_date Date` + `category`（自由字符串，默认"货款"）。
- 付款：**不在供应商表里**，而是 `cash_flows` 的一行（`direction=out` / `biz_type=PAYMENT_SUPPLIER` / `party_type='supplier'` / `party_id=供应商` / `doc_id=应付单`）。
- **欠款唯一口径**：`Σ(活着的应付单) − Σ(活着的付款流水)`，实现**只有一处** `services/supplier_service.py:103`（`balance_of`），`supplier_service.py:98`（`unpaid_of`）是它的单张包装；判据 `_tools/qa/_check_supplier_payables.py` 会拦"端点里出现 paid 参与的加减"。
- **已经能直接拿到余额**：`GET /suppliers` 出参就带 `payable_total / paid_total / unpaid_total / open_payables`（`backend/app/schemas/supplier.py`）。
- ⚠️ **是时点账、且没有 as_of 参数**：`unpaid_total` 是"此刻还欠多少"，**不能**传一个历史日期问"那天欠多少"。要期初/期末必须自己按 `doc_date` / `flow_date` 回推，而 `cash_flows` **没有历史余额快照**（和客户欠款报表同一个限制，见 `services/reports/balance_query.py:42-44` 那段口径说明）。
- ⚠️ **供应商账期字段不存在**：`suppliers` 与 `supplier_payables` 都**没有** `due_date` / `credit_days` / 账期任何字段。能算的只有**实际账期** = `付款流水.flow_date − 应付单.doc_date`（或采购单 `doc_date`），**不是约定账期**。

### 0.3 采购单价从哪来？—— **四级来源，但"加权平均"只活在报表服务内部，没有端点**

| 级 | 数据 | 位置 | 什么时候有值 |
|---|---|---|---|
| ① **采购单明细价**（最可靠的一手数据） | `purchase_order_items.unit_cost Numeric(14,4)`（必须 > 0） | `backend/app/models/purchase.py:65`；schema 校验见 `backend/app/schemas/purchase.py` 的 `PurchaseItemIn` | 每建一张采购单就有 |
| ② **入库流水价** | `inventory_movements.unit_cost Numeric(14,4)` nullable | `backend/app/models/inventory.py:11` | **只有手工入库且填了成本价才有**；2026-09-19 才真的落库，老数据一条都没有 |
| ③ **商品最新进货价** | `products.cost_price Numeric(14,4)` | `backend/app/models/product.py:16` | 被 `services/cost_history.record_cost` 更新；**只是"最新"一个数，不是均价** |
| ④ **成本价时间轴** | `product_cost_history`（`effective_from` / `effective_to` 半开区间 / `source` = CREATE·PURCHASE·MANUAL·BACKFILL） | `backend/app/models/product.py:69` | 通过 `GET /products/cost-history` 可读 |
| **加权平均进货价**（用户 2026-09-19 要求的毛利口径） | —— | ⛔ **只在 `services/cost_basis.py:67`（`_weighted_avg`），没有任何端点暴露** | 三级兜底：期间均价 → 累计均价 → 下单快照（`services/cost_basis.py:96-117` 的 `CostBasis.of`） |

- ⚠️ **采购单明细不存金额**：`purchase_order_items` 只有 `quantity` + `unit_cost`，金额是**现算**的（`services/supplier_service.py::total_of`）；单头也**不存合计**。
- ⚠️ 毛利用的成本是 `cost_basis`（均价三级），**货损金额**仍走 `ledgers.cost_price_snapshot`（`services/cost_basis.py:32-34` 明确写了为什么不能改）。

---

## 1. 六项指标可用性矩阵

| 指标 | 能否算 | 用哪个端点 / 字段 | 时点 or 区间 | 主要坑 |
|---|---|---|---|---|
| **库存数量** | ✅ 能（当前时点） | `GET /inventory/summary`（`inventory.py:182`，字段 `stock`）；或 `GET /products` 的 `stock` | **时点**（此刻） | 无 as_of 参数，**问不了历史某天的库存**；summary 无 response_model（裸 dict）；只含 `is_active=true 且 is_deleted=false` 的商品 |
| **期初 / 期末库存** | ⚠️ 只能回推 | `GET /inventory/movements`（`inventory.py:25`）按 `product_id` + `date_from/date_to` 取流水，自己累加 | 流水本身是**区间**查询 | ① 默认 limit=100、上限 500，越界靠 X-Truncated 头（**会静默截断**）② 日期是**业务当地日**，created_at 是 UTC naive，必须过 business_range_utc（`inventory.py:56-61`）③ 回推起点必须有"某个时点的库存"作锚，系统里只有"现在" |
| **库存金额** | ❌ **没有现成端点**，只能自己乘 | `stock × cost_price`（自算） | 时点 | cost_price = **最新进货价**，不是加权平均 → 库存被按最新价估值（进货价一涨，库存金额整体跳变）；cost_price 可为 `None`（从没进过货）；真实均价要复刻 `cost_basis._weighted_avg` |
| **采购总额** | ✅ 能 | `GET /purchase-orders`（`purchase_orders.py:153`）的 `total` 字段；schema 见 `backend/app/schemas/purchase.py` 的 `PurchaseOrderBrief` | **区间**（date_from/date_to 落在 doc_date） | ① 默认 limit=100、上限 500 ② 默认**不含回收站**（include_deleted=False）③ 默认排序 doc_date desc, id desc ④ 出参金额是**字符串两位小数** ⑤ 列表端点**不返回明细**（要明细逐单 GET /purchase-orders/{id}） |
| **应付账款** | ✅ 能（总额 / 分供应商 / 分单） | `GET /suppliers`（`suppliers.py:137`）的 `unpaid_total`；`GET /supplier-payables`（`suppliers.py:268`）的 `paid/unpaid` | **时点** | ① **没有 as_of**，算不出期初/期末 ② GET /supplier-payables **无分页参数**（全量返回）③ 三个端点都要 LEDGER_EDIT（只有派单员） |
| **供应商账期** | ⚠️ 只能算"实际账期" | `supplier_payables.doc_date` 与 `GET /supplier-payments`（`suppliers.py:406`）的 `pay_date` 相减 | 区间（自算） | **系统里没有"约定账期"这个字段**（供应商档案与应付单都没有 due_date / 账期天数）；GET /supplier-payments **无分页**、默认 flow_date desc, id desc |

---

## 2. 逐文件盘点

### 2.1 `backend/app/api/v1/inventory.py`（236 行，prefix=`/inventory`）

权限：**三个端点全部 require_permission(Permission.PRODUCT_MANAGE)**（`inventory.py:29`、`inventory.py:69`、`inventory.py:185`）= 只有派单员（`backend/app/core/rbac.py:96`）。

| 方法 + 完整路径 | 参数 | 返回 schema 关键字段 |
|---|---|---|
| `GET /api/v1/inventory/movements`（`inventory.py:25`） | `product_id: int?`、`limit: int = 100`（ge=1, le=500）、`offset: int = 0`、`date_from` / `date_to`（"YYYY-MM-DD"，含当天） | `list[MovementOut]`：id, product_id, change, note, operator_id, created_at, source="MANUAL", order_id, order_no, status="COMMITTED", unit_cost（`backend/app/schemas/inventory.py`） |
| `POST /api/v1/inventory/movements`（`inventory.py:65`） | body `MovementCreate`：product_id, change (ge=-1_000_000, le=1_000_000), note(≤256), unit_cost: Decimal｜None (ge=0) | `MovementOut`，201 |
| `GET /api/v1/inventory/summary`（`inventory.py:182`） | `below_alert: bool = False` | ⚠️ **list[dict]，没有 response_model**：product_id, product_name, stock, unit, low_stock_alert, reserved, category |

**① 能算什么**：库存数量（summary 的 stock，时点）；出入库明细（movements，区间）；reserved（在途占用量）。
**② 时点/区间**：summary = **时点**；movements = **区间**（date_from/date_to，按 created_at 换算后的业务当地日）。
**③ 坑**：

- 日期过滤走 `core.business_time.business_range_utc`（`inventory.py:56-61`）：**只给一侧时，另一侧用来补区间，但只加被请求的那一侧**——即 date_from 单独给 = 从那天到现在；date_to 单独给 = 从最早到那天。
- limit 上限 500、默认 100，靠 `finish_page` 写 `X-Result-Limit` / `X-Truncated` 响应头——裸数组加不了元数据，**客户端不读头就会静默少算库存**。
- 手工出入库校验（`inventory.py:89-94`）：change == 0 → 400「变动数量不能为 0」；**出库（change<0）带 unit_cost → 400**「进货价只在入库时填；出库不用填成本价」。
- 库存加减与"不许负数"判据在**同一条 SQL**：`UPDATE products SET stock = stock + :change WHERE id = :id AND stock + :change >= 0`（`inventory.py:99-106`）；rowcount≠1 时再查库如实报「库存不足…」(400) 或「库存刚刚被别的操作改过…请刷新后重试」(409)。
- 入库带 unit_cost 时三件事**同一事务**：写 `InventoryMovement.unit_cost` → `services.cost_history.record_cost(..., source=SOURCE_PURCHASE, movement_id=row.id)` 改 products.cost_price + 写 product_cost_history → 写 `OperationAction.INVENTORY_ADJUST` 审计日志（含 stock_after、cost_before/cost_after）。
- summary 只取 `is_active=True **且** is_deleted=False`，按 (Product.stock, Product.id) 升序（低库存在前）；reserved = join orders 后 `source="ORDER" and status="RESERVED" and Order.deleted_at is None` 的 `Σ｜change｜`（`inventory.py:210-220`）→ **在途占用量，不是可用量**（可用量 = stock − reserved，得客户端自己减）。
- ⛔ **没有"盘点"端点**，也没有"调整到某个数量"的语义——只能记一笔差额流水。

### 2.2 `backend/app/api/v1/purchase_orders.py`（276 行，prefix=`/purchase-orders`）

权限：**写**（建/改/删/恢复）= `Writer = require_permission(Permission.PRODUCT_MANAGE)`（`purchase_orders.py:57`）；**读**（列表/详情）= `Reader = require_permission(Permission.ORDER_DISPATCH)`（`purchase_orders.py:59`）。两个权限点派单员都有（`backend/app/core/rbac.py:86-108`）。

| 方法 + 完整路径 | 参数 | 返回 schema 关键字段 |
|---|---|---|
| `GET /api/v1/purchase-orders`（`purchase_orders.py:153`） | supplier_id、date_from / date_to（走 `core.date_window.date_window`，收字符串返回 date）、include_deleted=False、limit=100（ge=1, le=500）、offset | `list[PurchaseOrderBrief]`（**不带明细**）：id, supplier_id, supplier_name, doc_date, remark, item_count, total: str, payable_id, payable_paid: str, payable_unpaid: str, is_deleted, created_at |
| `GET /api/v1/purchase-orders/{order_id}`（`purchase_orders.py:189`） | — | `PurchaseOrderOut` = Brief + operator_id / updated_at / items；`PurchaseItemOut{id, product_id, product_name, unit, quantity, unit_cost: str, amount: str, is_void, movement_id}` |
| `POST /api/v1/purchase-orders`（`purchase_orders.py:200`） | `PurchaseOrderCreate{supplier_id, doc_date, remark, items(min_length=1，同商品只许一行)}` | `PurchaseOrderOut`，201 |
| `PATCH /api/v1/purchase-orders/{order_id}`（`purchase_orders.py:223`） | `PurchaseOrderUpdate`：supplier_id / doc_date / remark、items（**整个替换**；未出现的行 = 撤掉并标 is_void；items=None = 只改单头，[] = 撤掉所有行） | `PurchaseOrderOut` |
| `DELETE /api/v1/purchase-orders/{order_id}`（`purchase_orders.py:249`） | — | 204 软删：**逐行冲回库存 + 删掉生成的应付单**；已经付过钱的应付单**删不掉**（如实拒绝） |
| `POST /api/v1/purchase-orders/{order_id}/restore`（`purchase_orders.py:264`） | — | 重新入库 + 恢复应付；库存不够如实报错，⛔ **不把库存压成负** |

**① 能算什么**：**采购总额**（total，按 doc_date 落区间）；采购明细与单价（unit_cost）；每张采购单**对应的应付已付/未付**（payable_paid / payable_unpaid）→ **应付账款可以按采购口径看**。
**② 时点/区间**：列表 = **区间**（doc_date 闭区间）；单张单的 payable_paid/unpaid = **时点**。
**③ 坑**：

- 默认排序 `doc_date desc, id desc`；默认**不含回收站**（`is_deleted.is_(False)`）。
- limit 默认 100、上限 500 → 汇总采购总额必须翻页或改口径（**端点没有"合计"字段**，total 是**每张单**的合计）。
- 金额出参一律**字符串两位小数**：`_money(v) = str(q2(Decimal(v or 0)))`（`purchase_orders.py:64-69`）；`api/v1/suppliers.py:57-59` 的 _money 是**全仓唯一允许写出参格式化的地方**（判据 `_tools/qa/_check_money_display.py` 只放行这几处）。
- **减法只有一处**：`_payable_amounts`（`purchase_orders.py:87`）调 `supplier_service.unpaid_of`（`supplier_service.py:98`）；合计 = `psvc.total_of(order.items)` **现算**（明细不存金额）。
- 写端点统一 `_write`（`purchase_orders.py:72`）保护：服务层抛中文 400/409 时显式 db.rollback()（防半成品改动被下一次别的请求 commit 带进库）。
- doc_date 是**业务当地日期（Date 列）**，⛔ **不套** business_range_utc。

### 2.3 `backend/app/api/v1/suppliers.py`（542 行，router **无 prefix**，tags=["suppliers"]）

权限：**全部 15 个端点同一权限** `Dispatcher = require_permission(Permission.LEDGER_EDIT)`（`suppliers.py:54`）= 只有派单员——**这些端点能动钱**（付款写 cash_flows）。

| 方法 + 完整路径 | 参数 | 返回 schema 关键字段 |
|---|---|---|
| `GET /api/v1/suppliers`（`suppliers.py:137`） | include_deleted=False | `list[SupplierOut]`：id, name, contact_name, phone, address, remark, **payable_total / paid_total / unpaid_total: str, open_payables: int**, created_at |
| `POST /api/v1/suppliers`（`suppliers.py:158`） | `SupplierCreate` | 201；重名 400「已经有一个供应商叫「X」了…」（`uq_suppliers_name`） |
| `GET /api/v1/suppliers/{supplier_id}`（`suppliers.py:184`） | — | `SupplierOut`；**会记一次 usage**（need_alive=False） |
| `PATCH /api/v1/suppliers/{supplier_id}`（`suppliers.py:196`） | `SupplierUpdate`（部分更新） | `SupplierOut` |
| `DELETE /api/v1/suppliers/{supplier_id}`（`suppliers.py:234`） | — | 204 软删 |
| `POST /api/v1/suppliers/{supplier_id}/restore`（`suppliers.py:250`） | — | `SupplierOut` |
| `GET /api/v1/supplier-payables`（`suppliers.py:268`） | supplier_id、include_deleted=False、**only_open=False（只看未结清）** | `list[SupplierPayableOut]`：id, supplier_id, supplier_name, title, category, amount: str, doc_date, remark, **paid: str, unpaid: str, payment_count: int**, created_at；排序 doc_date desc, id desc |
| `POST /api/v1/suppliers/{supplier_id}/payables`（`suppliers.py:288`） | `SupplierPayableCreate`；body.supplier_id 必须等于路径（否则 400）；title 非空；category 默认"货款" | 201；**这一步不动钱** |
| `PATCH /api/v1/supplier-payables/{payable_id}`（`suppliers.py:320`） | `SupplierPayableUpdate` | **采购单生成的应付单改不了**（`psvc.guard_supplier_payable`）；**金额不许改到小于已付**（400「这张单已经付了 X…先撤销多付的那一笔」） |
| `DELETE /api/v1/supplier-payables/{payable_id}`（`suppliers.py:368`） | — | 204 软删；同样被 guard 拦 |
| `POST /api/v1/supplier-payables/{payable_id}/restore`（`suppliers.py:388`） | — | `SupplierPayableOut` |
| `GET /api/v1/supplier-payments`（`suppliers.py:406`） | supplier_id、payable_id、date_from / date_to: date、include_deleted=False | `list[SupplierPaymentOut]`：id, supplier_id, supplier_name, **payable_id（必填，不允许"没有单据的付款"）**, payable_title, amount: str, pay_date, channel, remark, created_at；排序 flow_date desc, id desc |
| `POST /api/v1/supplier-payables/{payable_id}/payments`（`suppliers.py:443`） | `SupplierPaymentCreate{amount>0, pay_date, channel pattern "^(cash｜transfer｜wechat｜bank)$", remark}` | 201；分次付款 = 同一应付单多行流水 |
| `DELETE /api/v1/supplier-payments/{flow_id}`（`suppliers.py:468`） | — | 204 **软删那一行资金流水**（不写反向的钱）；已撤销再撤 → 400 |
| `POST /api/v1/supplier-payments/{flow_id}/restore`（`suppliers.py:493`） | — | 三道门：①真在回收站 ②应付单还活着 ③供应商还活着 |

**① 能算什么**：**应付账款**（unpaid_total / 单张 unpaid）；已付、付款次数、付款流水（→ **实际账期**）；应付按供应商/按单/按 category 分组。
**② 时点/区间**：unpaid_total / paid / unpaid = **时点**（此刻）；GET /supplier-payments 的 date_from/date_to = **区间**。
**③ 坑**：

- **GET /supplier-payables 与 GET /supplier-payments 都没有分页参数**（全量返回）；GET /suppliers 也没有分页。
- 日期反序走 `ensure_date_order` → 400。
- `_get_payment_or_404`（`suppliers.py:533`）判据**必须带 party_type + biz_type**，否则会取到司机结算/开销的流水。
- 付款备注藏在 `cash_flows.note`，格式 `标题（第 N 次付款）· 备注`，出参按 `·` 之后取回（`suppliers.py:102-104`）。
- `SUPPLIER_PAYABLE_CATEGORIES = ("货款","设备采购","运费","尾款","其他")` 只是**建议值**，不是枚举（`backend/app/schemas/supplier.py`）。
- 全仓纪律：**凡从 cash_flows 取数都必须带 is_deleted.is_(False)**（红线 `_tools/qa/_check_supplier_payables.py` 扫全 backend）。

### 2.4 `backend/app/api/v1/products.py`（466 行，prefix=`/products`）

| 方法 + 完整路径 | 权限依赖 | 参数 | 返回 schema 关键字段 |
|---|---|---|---|
| `GET /api/v1/products`（`products.py:81`） | `require_permission(Permission.ORDER_CREATE)`（`products.py:88`） | include_inactive=False（**只有 DISPATCHER/SHIPPER 传才生效**） | `list[ProductOut]`：id, name, name_color, default_unit_price: Decimal, **cost_price: Decimal｜None**（非派单员为 null，不是 0）, is_active, image_url, **stock: int**, unit, category, low_stock_alert, sort_order |
| `POST /api/v1/products`（`products.py:130`） | PRODUCT_MANAGE（`products.py:133`） | `ProductCreate` | 建商品时 cost_price 走 record_cost；分类自动补名册 ensure_category |
| `GET /api/v1/products/cost-history`（`products.py:186`） | PRODUCT_MANAGE（`products.py:190`） | product_id?、limit=200（ge=1, le=500） | `list[ProductCostHistoryOut]`：id, cost_price, effective_from, effective_to, source, movement_id（⛔ 不下发 operator_id） |
| `GET /api/v1/products/{product_id}`（`products.py:225`） | **仅登录 CurrentUser**（`products.py:227`） | — | `ProductOut`；软删/白名单外 → 404「未找到对应记录」；cost_price 按角色裁剪 |
| `PATCH /api/v1/products/{product_id}`（`products.py:243`） | PRODUCT_MANAGE（`products.py:247`） | `ProductUpdate`（部分更新） | cost_price 单独处理走 record_cost；逐字段记 PRODUCT_UPDATE 日志 |
| `POST /api/v1/products/{product_id}/image`（`products.py:296`） | PRODUCT_MANAGE（`products.py:300`） | UploadFile | 最大 4MB（`MAX_IMAGE_BYTES`） |
| `DELETE /api/v1/products/{product_id}`（`products.py:349`） | PRODUCT_MANAGE（`products.py:352`） | — | 204 **软删 + 强制 is_active=False**；把 was_active 记进审计日志 |
| `POST /api/v1/products/{product_id}/restore`（`products.py:426`） | PRODUCT_MANAGE（`products.py:429`） | — | **恢复=还原，不顺手重新上架**：is_active 从最近 500 条 PRODUCT_DELETE 日志里读回，读不到 = 保持下架（fail-closed） |

**① 能算什么**：商品主数据（stock 数量、cost_price 最新进货价 → **库存金额的乘数因子**）；成本价时间轴（cost-history，可回推历史某天的成本价 → **唯一能拿到历史成本价的端点**）。
**② 时点/区间**：stock / cost_price = **时点**；cost-history = **区间表**（effective_from/effective_to 半开区间）。
**③ 坑**：

- `GET /products` **没有任何分页参数（全量）**；排序 = is_active desc → `CASE(sort_order==0 → 1 else 0)` → sort_order asc → usage 常用度（`products.py:91-94`）。
- 过滤 is_deleted=False + 白名单 visible_product_ids（None=不限；**空集=什么都不给看**）。
- ⚠️ **已知缺陷（记忆 2026-09-21）**：`GET /products` **恒过滤 is_deleted=false**，而 `POST /products/{id}/restore` 在 App 里**一个入口都没有**（只有 AI 撤回卡在用）→ 违反"界面上要有手边的撤销入口"。
- cost_price 裁剪在 `product_out(p, role_key)`（`products.py:58-78`）：**只有 product:manage 拿到真实成本价，其余角色 null**（2026-09-19 审计 R12-H1）。→ **做库存金额必须用派单员账号**。
- `ProductOut` **没有 is_deleted、没有 created_at、没有成本时间轴**。
- `GET /products/cost-history` **必须声明在 /{product_id} 之前**（`products.py:186` vs `products.py:225`），否则 "cost-history" 转 int 报 422；它**不按 products.is_deleted 过滤**；排序 effective_from desc, id desc。

### 2.5 `backend/app/api/v1/ledger.py`（854 行，prefix=`/ledger`）

权限三档：读流水/账户 = `require_any_permission(LEDGER_READ_OWN, LEDGER_READ_ALL)`（`ledger.py:138`、:191、:260、:379）；写账/同步/导出 = `require_permission(LEDGER_EDIT)`（:293、:310、:401、:505）；**收款与导出任务/下载 = 仅 CurrentUser + 函数体内判角色**（:552、:680、:698、:739、:817）——与 RBAC 矩阵无关，端点索引读不出来。

| 方法 + 完整路径 | 参数 | 返回 / 备注 |
|---|---|---|
| `GET /api/v1/ledger/entries`（`ledger.py:136`） | shipper_id、temp_shipper_name（二选一，同时给 400）、date_from / date_to（"YYYY-MM-DD"）、**limit: int｜None（ge=1, le=5000，缺省 1000）**、offset | `list[LedgerOut]`：id, shipper_id, temp_shipper_name, shipper_name, entry_date: date, product_name, quantity, **unit_price: Decimal, total: Decimal**, order_id, order_product_id, product_id, order_no, order_delivery_description, source, note, created_at；排序 entry_date desc, id desc；货主强制只看自己；其它角色 403 |
| `GET /api/v1/ledger/accounts`（`ledger.py:189`） | date_from / date_to、kind（`^(shipper｜member)$`，默认 shipper） | `list[LedgerAccountOut]`：id, temp_name, name, phone, is_active, count, total: Decimal；**仅派单员** |
| `GET /api/v1/ledger/temp-shipper-names`（`ledger.py:258`） | — | `list[str]` |
| `POST /api/v1/ledger/sync-from-delivered-orders`（`ledger.py:288`） | body（shipper_id 与 temp_shipper_name 互斥） | `{"orders_synced": n, "shippers_notified": n}`；幂等（唯一键 (order_product_id, source)） |
| `POST /api/v1/ledger/entries`（`ledger.py:305`） | `LedgerCreate` | 201；**手工记账 source 只允许 MANUAL**；order_id 恒写 None |
| `GET /api/v1/ledger/entries/{entry_id}`（`ledger.py:376`） | — | 货主只能看自己那行，否则 403 |
| `PATCH /api/v1/ledger/entries/{entry_id}`（`ledger.py:395`） | `LedgerUpdate`（部分更新） | 可改仅 source ∈ {MANUAL, ORDER}；**已送达/已撤销/已退货的单 → 400**；不许改 order_id；写 LEDGER_UPDATE 日志 |
| `DELETE /api/v1/ledger/entries/{entry_id}`（`ledger.py:500`） | — | 204 **物理删除**（db.delete(row)，非软删） |
| `POST /api/v1/ledger/export-jobs`（`ledger.py:543`） | `LedgerExportJobCreate` | 三道闸：同时只 1 个 / 24h ≤ EXPORT_DAILY_QUOTA=20 / 单次 ≤ MAX_EXPORT_ROWS=20_000 笔；**PDF 一律 400**（只有 Excel） |
| `GET /api/v1/ledger/export-jobs/{job_id}`（`ledger.py:676`） | — | 归属闸 _ensure_export_job_visible（`ledger.py:48`） |
| `GET /api/v1/ledger/export-jobs/{job_id}/download`（`ledger.py:694`） | — | FileResponse |
| `POST /api/v1/ledger/receipts`（`ledger.py:734`） | `ShipperReceiptCreate` | **仅派单员**；写 shipper_receipts + cash_flows + 翻 orders.paid；返回 `ShipperReceiptOut` |
| `GET /api/v1/ledger/receipts`（`ledger.py:814`） | customer_id、date_from、date_to | **仅派单员**；**无分页**；排序 received_at desc, id desc |

**① 能算什么**：营业额/应收（total 逐行）；`ledgers.cost_price_snapshot`（**出库成本快照**，COGS 的原始数据）；收款（receipts → 应收已收）；按货主/按批发商的余额与笔数。**不直接给应付、不给库存金额。**
**② 时点/区间**：entries / accounts / receipts = **区间**；accounts 的 total 是"这个区间内的合计"，**不是时点余额**。
**③ 坑**：

- 日期窗口唯一实现 `_apply_date_window`（`ledger.py:71-88`）：对 `Ledger.entry_date`（**Date 列**）做**闭区间**；⛔ 不许换成 `deps.parse_date_range`（返回 datetime 会把闭区间变半开）。
- 可见性唯一口径 `visible_ledger_select()`（`services/ledger_scope.py`）：**排除回收站订单的账**（`ledger.py:150-154` 注释：否则账本与营业额差一张已删单的钱，本机 2026-09 差 ¥4,600）。**做资产负债表取"应收"时必须用同一句。**
- 默认 limit=1000、上限 5000，截断靠 X-Result-Limit / X-Truncated 头；实测 85,474 行 → **27.75 秒 / 29.12MB**。
- `GET /ledger/accounts` 与 `GET /ledger/receipts` **无分页（全量）**。
- `DELETE /ledger/entries/{id}` 是**物理删除**（唯一一处不软删的账）。

### 2.6 `backend/app/api/v1/shipper_ledger.py`（633 行，prefix=`/shipper-ledger`）

权限：**四个端点全部 ShipperOnly = require_roles(UserRole.SHIPPER)**（`shipper_ledger.py:67`），且**写端点**还要求 users.is_member（`_require_member`，`shipper_ledger.py:77-91`，函数体内判）。**司机/派单员一律 403。**

| 方法 + 完整路径 | 参数 | 返回 / 备注 |
|---|---|---|
| `GET /api/v1/shipper-ledger/summary`（`shipper_ledger.py:213`） | delivered_from / delivered_to（含当天，按**订单送达日**当地日）、customer_name、customer_phone | `ShipperLedgerSummaryOut{orders, cleared_orders, payable, paid, unpaid, receivable, received, unreceived, settlements, is_member}`；**统计无 limit（全量）** |
| `GET /api/v1/shipper-ledger/settlements`（`shipper_ledger.py:327`） | order_id、delivered_from / delivered_to、include_deleted=False、**limit（ge=1, le=2000，缺省 500）**、offset | `list[ShipperSettlementOut]`（含 lines）；排序 id desc |
| `POST /api/v1/shipper-ledger/settlements`（`shipper_ledger.py:372`） | `ShipperSettlementCreate{order_id, lines?, method, note, source}` | 201；整单或按商品行；金额服务端算；超收 400；并发两道防线（lock_order_row + over_settled_lines） |
| `DELETE /api/v1/shipper-ledger/settlements/{id}`（`shipper_ledger.py:508`） | — | 204 **软删**（条件 UPDATE WHERE is_deleted=0） |
| `POST /api/v1/shipper-ledger/settlements/{id}/restore`（`shipper_ledger.py:557`） | — | 恢复前**必须重算上限**，超了 400 |

**① 能算什么**：批发商视角的**应收 / 已收 / 未收**（payable/paid/unpaid/receivable/received/unreceived）；它是**下游对账**，不是公司口径。
**② 时点/区间**：**区间**（按 Order.delivered_at 落 delivered_from/to）。
**③ 坑**：

- ⛔ 这本账**不写 cash_flows、不翻 orders.paid**（与 POST /ledger/receipts 完全不相干）→ 唯一痕迹是 operation_logs。**资产负债表取"应收"不能混用这两套。**
- payable 口径 = `Σ order_money.receivable`（= Σ行金额 − 已退；**不含运费**——运费是公司付给司机的钱）。
- 时间窗口过 business_range_utc（`shipper_ledger.py:258-260`、:362-364，半开区间）。
- 归属人键 = 名字 + 电话（contact_dongjia_name → contact_boss_name → ""）；`UNSET_CUSTOMER = "未指定货主"`。

### 2.7 `backend/app/api/v1/product_categories.py`（228 行，prefix=`/product-categories`）

| 方法 + 完整路径 | 权限依赖 | 参数 | 返回 |
|---|---|---|---|
| `GET /api/v1/product-categories`（`product_categories.py:82`） | CurrentUser（**任何登录角色**，`product_categories.py:83`） | — | `list[ProductCategoryOut]{id, name, sort_order, product_count}`，排序 sort_order, id |
| `POST /api/v1/product-categories`（`product_categories.py:92`） | PRODUCT_MANAGE（:95） | `ProductCategoryCreate{name≤MAX_SHORT_NAME, sort_order?}` | 201；重名 409；**MAX_CATEGORIES = 200** |
| `PATCH /api/v1/product-categories/{category_id}`（`product_categories.py:122`） | PRODUCT_MANAGE（:126） | 改名 | **级联改 products.category（含软删商品）**；重名 409 |
| `POST /api/v1/product-categories/reorder`（`product_categories.py:166`） | PRODUCT_MANAGE（:169） | `Reorder{ids min_length=1 max_length=200}` | **必须整份提交**（覆盖全部现存分类），否则拒绝 |
| `DELETE /api/v1/product-categories/{category_id}`（`product_categories.py:196`） | PRODUCT_MANAGE（:199） | — | **还有商品挂着就 400**「还有 N 个商品挂在这个分类下…」 |

**① 能算什么**：给库存报表做**分类维度**（product_count 只数 is_deleted=False 的商品，一次 _counts 查询）。
**② 时点/区间**：时点。
**③ 坑**：分类是**字符串列**（products.category String(32)，空串 = 未分类），不是外键——改名靠**级联 UPDATE**，所以历史单据上印的分类名会跟着变。

### 2.8 `backend/app/api/v1/unit_conversions.py`（268 行，prefix=`/unit-conversions`）

权限：`UnitOwner = require_roles(UserRole.SHIPPER, UserRole.DISPATCHER)`（`unit_conversions.py:44`）——**货主和派单员**都能读写，司机被挡。

| 方法 + 完整路径 | 参数 | 返回 / 备注 |
|---|---|---|
| `GET /api/v1/unit-conversions`（`unit_conversions.py:61`） | deleted_only=False | `list[UnitConversionOut]{id, from_unit, to_unit, factor: Decimal（Pydantic v2 序列化成字符串）, remark, created_at, deleted_at}`；活着的按 from_unit, id 排，回收站按 deleted_at desc, id desc |
| `POST /api/v1/unit-conversions`（`unit_conversions.py:79`） | `UnitConversionCreate{from_unit≤MAX_UNIT_LEN, to_unit, factor: Decimal, remark}` | 四条判据在 `services/unit_conversion.py`（非空/不同名/>0/一个源单位只能一条/反向对不许并存）；**被软删过的同一条会被放回来并改率**（op="restore_by_create"） |
| `PATCH /api/v1/unit-conversions/{conversion_id}`（`unit_conversions.py:156`） | `UnitConversionUpdate` | — |
| `DELETE /api/v1/unit-conversions/{conversion_id}`（`unit_conversions.py:211`） | — | 204 软删 |
| `POST /api/v1/unit-conversions/{conversion_id}/restore`（`unit_conversions.py:234`） | — | 恢复要**重过冲突判据** |

**① 能算什么**：把库存数量从"件"换成"箱"之类的**数量**换算；**钱一个字节都不跟着换算**（`backend/app/models/unit_conversion.py:9`）。
**② 时点/区间**：时点。
**③ 坑**：**刻意不加 (from_unit, to_unit) 唯一约束**；**只做一跳、不做链式**；factor Numeric(14,4)；FACTOR_MAX 由 schema 导出。

---

## 3. 相邻但不在清单内、却直接决定本次需求的信息

### 3.1 `backend/app/api/v1/reports.py`（prefix=`/reports`，**全部 require_permission(Permission.ORDER_DISPATCH)**）

| 端点 | 行号 | 参数 | 关键出参 |
|---|---|---|---|
| `GET /api/v1/reports/turnover` | `reports.py:64` | mode(day/week/month)、date(别名 anchor，**必填**)、date_from/date_to（成对给，优先于 mode+anchor） | 营业额、cost_total、cost_covered_amount、cost_covered_lines/total_lines、damage_qty/damage_amount、collected、arrears_total、total_freight |
| `GET /api/v1/reports/products` | `reports.py:79` | 同上 | 逐商品：cost_total / damage_qty / damage_amount |
| `GET /api/v1/reports/profit` | `reports.py:94` | 同上 | **经营利润表**：营业额 / 商品成本 / 配送成本 / 期间费用 / 税金及附加 / 应交增值税 / 车辆折旧；四格**构造上等于** turnover 的同名数（`services/reports/profit_query.py:8-14`） |
| `GET /api/v1/reports/vehicle-cost` | `reports.py:113` | 同上（默认 mode=month） | 每车折旧/开销/配送成本，**⛔ 没有收入列**（订单上没有"哪台车拉的"这个事实） |
| `GET /api/v1/reports/cost-coverage` | `reports.py:133` | 同上 | 收入覆盖率 + missing_purchase_price（**从来没带价进过货的商品**，含 stock 与 cost_price） |
| `GET /api/v1/reports/tax-summary` | `reports.py:157` | 同上 | 销项/进项税额、应交增值税 |
| `GET /api/v1/reports/arrears-summary` | `reports.py:176` | date_from、date_to（**都必填**） | `list[dict]`：按欠款人聚合的 {name, count, amount} |
| `GET /api/v1/reports/customer-balances` | `reports.py:188` | mode/anchor/date_from/date_to + include_orders=False | **客户欠款（应收账龄）**：as_of、rows（每债务人 balance / prepaid / buckets(0_30/31_60/61_90/over_90) / oldest_days / credit_used / credit_available / over_limit）、totals |
| `GET /api/v1/reports/export` | `reports.py:213` | kind（turnover｜products｜drivers｜customers｜finance｜audit｜profit｜vehicle-cost｜cost-coverage｜tax-summary｜customer-balances）、mode、anchor、date_from/date_to | 内存流 xlsx |

- ⛔ **build_customer_balances 是时点账**（`services/reports/balance_query.py:120-125`）：`as_of = min(窗口末, 今天)`，**窗口起点不参与余额**；口径说明写在 `balance_query.py:33-45`（⛔ **收款流水没有历史快照**，所以问不了"当时那一刻的账"）。**这是"应收"这一格唯一可用的时点口径，负债侧的对称物（供应商应付）恰恰没有这样的端点。**
- `kind=finance`（`reports.py:585`）导的是**资金收支**（cash_flows 流入/流出/净额 + 开销分类），**不是资产负债表**。
- 报表包只允许 SELECT/JOIN/GROUP BY（AST 判据 `_tools/qa/_check_report_boundary.py`，文件清单由 glob 自动收）。
- ⚠️ 窗口解析共用一个 `_span(mode, anchor, date_from, date_to)`，**date 参数永远必填**（哪怕给了 date_from/date_to）。

### 3.2 成本口径的唯一实现：`backend/app/services/cost_basis.py`

- `_weighted_avg(db, until, period)`（`cost_basis.py:67`）：只认 `change > 0 AND unit_cost IS NOT NULL`，按商品算 `Σ(数量×进货价)/Σ数量`，量化到 0.0001（`_Q`，`cost_basis.py:58`）。
- `CostBasis.of(product_id, snapshot)`（`cost_basis.py:107`）：三级 → ① PERIOD 期间均价 ② CUMULATIVE 累计均价 ③ SNAPSHOT 下单快照。
- ⚠️ **一个商品在一个报表里只用一级**；两段行数都要报出去（cost_avg_lines / cost_snapshot_lines），否则用户以为整份毛利都是平均口径（`cost_basis.py:27-30`）。
- **库存金额如果要"平均成本"，就得复用这里的 _weighted_avg，⛔ 不要另写一份**（`cost_basis.py:99-100`：「不要在别处再写一份"取成本"的逻辑」）。

### 3.3 供应商应付的唯一实现：`backend/app/services/supplier_service.py`

- `_paid_filter(*extra)`（`supplier_service.py:52`）：party_type='supplier' + lower(direction)='out' + biz_type='PAYMENT_SUPPLIER' + **is_deleted.is_(False)**（注释：这一句是这个模块最不能省的一行）。
- `payable_paid`（:68，按 doc_id）/ `payable_payment_count`（:74）/ `supplier_totals`（:80，**应付按 supplier_id、已付按 party_id**——这样"某张单被删了"不会让已付总额凭空少一块）。
- `unpaid_of`（:98）/ `balance_of`（:103）：**全项目唯一那个减法**。

### 3.4 与"库存金额"最接近的现有产物

`kind=cost-coverage` 的 missing_purchase_price（`reports.py:377-382`）：**商品名 / 单位 / 库存 / 记着的成本价**（"没有进过货"时印中文）。它是**唯一**在报表里同时出现 stock 与 cost_price 的地方，但只列"从来没带价进过货的商品"，**不是库存金额表**。

---

## 4. 坑清单（跨文件汇总，按后果排序）

1. **默认 limit 会静默截断**：`GET /inventory/movements`（100/500）、`GET /purchase-orders`（100/500）、`GET /ledger/entries`（1000/5000）、`GET /shipper-ledger/settlements`（500/2000）——都靠 X-Truncated 响应头提示，**不读头就会少算钱/少算库存**。
2. **完全无分页的端点**（一次全量进内存）：GET /supplier-payables、GET /supplier-payments、GET /suppliers、GET /ledger/accounts、GET /ledger/receipts、GET /products、GET /inventory/summary、GET /shipper-ledger/summary、GET /reports/arrears-summary、GET /reports/customer-balances。
3. **日期口径两套，用错会差 8 小时**：Date 列（ledgers.entry_date、purchase_orders.doc_date、supplier_payables.doc_date、cash_flows.flow_date）= 业务当地日，直接闭区间比较；DateTime 列（inventory_movements.created_at、Order.delivered_at、orders.created_at）= UTC naive，必须过 core.business_time 的 business_range_utc / business_date / local_stamp。
4. **金额出参是字符串**（"1234.50"）：_money 只在 `api/v1/suppliers.py:57` 与 `api/v1/purchase_orders.py:64` 两处；ProductOut.default_unit_price / cost_price 反倒是 Decimal，UnitConversionOut.factor 同理——**加总前一律先 Decimal(str)**。
5. **软删三处判据**：列表过滤 + 合并判据 + restore。GET /suppliers、GET /supplier-payables、GET /purchase-orders、GET /unit-conversions 都有 include_deleted / deleted_only；**GET /products 恒排除软删且没有 deleted_only**。
6. **cash_flows 必须带 is_deleted.is_(False)**，否则撤销过的付款照样算"已付"（`supplier_service.py:55-57`）。
7. **账本与报表必须用同一句可见性**（visible_ledger_select()，排除回收站订单的账），否则差一张已删单的钱（`ledger.py:150-154`）。
8. **成本价按角色裁剪**：非派单员读到的 cost_price 是 null（`products.py:58-78`）→ 库存金额报表必须派单员。
9. **权限点与实际判据会分叉**：LEDGER_READ_OWN / LEDGER_READ_ALL / ORDER_READ_OWN / ORDER_READ_ASSIGNED / NOTIFICATION_READ 只是声明，读侧真实判据是端点体内内联的 user_role_key(current)（`backend/app/core/rbac.py:9-19`）；改矩阵**不会**改行为。
10. **GET /inventory/summary 没有 response_model**（裸 list[dict]）→ 字段漂移不会被 Pydantic 拦住，也没有 openapi 契约。
11. **商品编辑接口改不了 stock**（ProductCreate.stock 只在创建时生效；ProductUpdate 不收）——库存只能走出入库流水。

---

## 5. 缺什么（做「资产负债表 / 库存与应付」要新增的东西）

| 缺口 | 现状 | 影响 |
|---|---|---|
| **库存金额 / 存货科目** | 完全没有端点；只有 stock 与 cost_price 两个因子 | 要新增只读服务（建议放 services/reports/，复用 cost_basis._weighted_avg），不能各页自己乘 |
| **期初 / 期末库存（数量与金额）** | 无快照表、无 as_of 参数 | 只能「当前 stock ± 区间流水」回推；且**回推用的成本价**也要能回到历史（product_cost_history 是唯一可用的历史成本来源） |
| **供应商应付的时点端点** | unpaid_total 只有"此刻"；对称物 /reports/customer-balances 有 as_of | 负债侧要出「期初/期末」必须新增带 as_of 的只读查询（supplier_payables.doc_date + cash_flows.flow_date 回推，并写明"付款流水没有历史快照"） |
| **供应商账期字段** | suppliers / supplier_payables 都没有 due_date / 账期天数 | 「账期」只能报**实际账期**（付款日 − 单据日）；要"约定账期"得加列（属 DB 迁移 → 核心区） |
| **应付的汇总视角** | 现有端点都是"逐供应商 / 逐单" | 没有"应付合计"一个数（要客户端加总 unpaid_total，注意 GET /suppliers 无分页） |
| **资产负债的"资产"侧** | 应收有 customer-balances（时点）、资金有 kind=finance（区间流水） | 没有现金/银行**余额**概念（cash_flows 只记流水，没有账户与期初余额）——真正的资产负债表需要先有"账户 + 期初余额"这两件事 |
| **成本价出参** | 加权平均只在 cost_basis 内部 | 若库存金额用均价，必须新增端点或扩展现有报表出参，且要报"哪一级"（period/cumulative/snapshot） |

---

## 6. 端点索引（本次盘点覆盖的 50 个端点速查）

```text
inventory.py            3   GET/POST /inventory/movements, GET /inventory/summary
purchase_orders.py      6   GET/POST /purchase-orders, GET/PATCH/DELETE /purchase-orders/{id}, POST /{id}/restore
suppliers.py           15   /suppliers CRUD+restore(6), /supplier-payables 增删改查+restore(5),
                            /suppliers/{id}/payables(1), /supplier-payables/{id}/payments(1),
                            /supplier-payments GET+DELETE+restore(3)
products.py             8   GET/POST /products, GET /cost-history, GET/PATCH/DELETE /{id},
                            POST /{id}/image, POST /{id}/restore
ledger.py              13   GET /entries, /accounts, /temp-shipper-names, POST /sync-from-delivered-orders,
                            POST/PATCH/DELETE /entries(3), export-jobs(3), receipts(2), GET /entries/{id}
shipper_ledger.py       5   GET /summary, GET/POST /settlements, DELETE+POST restore /settlements/{id}
product_categories.py   5   GET/POST /product-categories, PATCH/DELETE /{id}, POST /reorder
unit_conversions.py     5   GET/POST /unit-conversions, PATCH/DELETE /{id}, POST /{id}/restore
```

> 权限点定义：`backend/app/core/rbac.py:6`（Permission）、`backend/app/core/rbac.py:61`（ROLE_PERMISSIONS）；已知分叉见 `backend/app/core/rbac.py:9-19`。

*本文件为只读盘点的产物；所有行号对应当前工作区 HEAD。*
