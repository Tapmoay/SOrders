# 报表 / 经营数据 —— 后端数据面盘点

> 盘点范围：`backend/app/api/v1/reports.py`（9 个端点）+ 它依赖的口径实现 + 相邻的 `/stats/*`（7 个端点）。
> 全部结论都带 `文件路径:行号`；**代码里没有的东西一律写「未在代码中找到」**，不臆造字段。
> 本次只读源码，未改任何文件。

---

## 0. 先记住三条全局口径（读任何一张表之前）

### 0.1 哪些单进报表：「送达口径」
所有营业 / 商品 / 成本 / 毛利 / 欠款类数字，唯一的取数入口是
`backend/app/services/reports/loader.py::load_delivered`（L37-63），条件三条（L50-58）：

| 条件 | 含义 | 源码 |
|---|---|---|
| `Order.status == DELIVERED` | **只算已送达**；未送达（待派/派单中/已接单）一分钱不进 | `loader.py:50-52` |
| `Order.delivered_at.isnot(None)` | 必须有送达时刻（分桶/窗口都用它） | `loader.py:53` |
| `Order.deleted_at.is_(None)` | **隔离区（软删）的单不算**（注释原话：否则「删掉一张错单报表一分不减」） | `loader.py:58` |

分桶按**业务当地日**（`business_date(o.delivered_at)`，`turnover_query.py:64`）；SQL 预过滤由 `delivered_span_sql`（`loader.py:19-34`）把当地日闭区间翻成 UTC 半开区间。

### 0.2 钱只有一份算法：`order_money.py:24-29`
| 名字 | 公式 | 源码 |
|---|---|---|
| total | Σ 商品行 `line_total`（当时卖了多少，**不随退货变**） | `order_money.py:24` |
| returned | Σ ｜`ledgers.source=RETURN` 的 total｜ | `order_money.py:25` |
| **receivable（应收）** | total − returned ← **营业额的分子就是它** | `order_money.py:26` |
| settled（已收） | Σ 挂本单的 IN 现金流水；**现场收现金（paid=true 且无流水）按 total 计** | `order_money.py:27` |
| refunded（已退） | Σ OUT 流水且 `biz_type == REFUND_CUSTOMER`（⛔ 货损 `EXPENSE_LOSS` 也挂 order_id，不算退款） | `order_money.py:28` |
| **arrears（还欠）** | receivable − settled + refunded（< 0 = 预收） | `order_money.py:29` |

恒等式（L30）：`receivable == (settled − refunded) + arrears` —— 「应收 = 净已收 + 欠款」。
⇒ **未收款不会让营业额变小**：钱没收到，营业额照样是应收，差额进「挂账未收」。

### 0.3 成本只有一份算法（毛利用加权均价、货损仍用下单快照）
`backend/app/services/cost_basis.py`（L17-21）三级口径：

| 级别 | 何时用 | 怎么算 |
|---|---|---|
| ① 期间均价 `PERIOD` | 本期有带价入库 | Σ(本期入库数量×进货价) ÷ Σ(数量) |
| ② 累计均价 `CUMULATIVE` | 本期没进货、但截至期末进过货 | 累计口径同上 |
| ③ 下单快照 `SNAPSHOT` | 从来没按带价入过库 | 用订单行的 `cost_price_snapshot` |

⚠️ **一个商品在同一张报表里只用一级**（`cost_basis.py:27-30`），所以每张表都要报 `cost_avg_lines` / `cost_snapshot_lines` 两段行数。
⛔ **货损金额不走这套**，仍用 `cost_price_snapshot × 货损件数`（`cost_basis.py:32-34`、`turnover_query.py:121-122`）——货损送达时已按快照入账。
判定「没记过进货价」的清单是另一件事：只看入库流水 `change > 0 且 unit_cost is not None`（`cost_coverage_query.py:61-87`）。

### 0.4 两句补充
- **司机应得 ≠ 订单运费**：报表里的「配送成本 / 司机应得」一律走 `driver_pay.pay_for_order(o).total`（`turnover_query.py:81`、`schemas/reports.py:23-28` 注释；旧实现读 `orders.freight_fee`，实测同一天 47870.00 vs 24770.00 虚高 93%）。
- **窗口只有一个入口**：`_span(mode, anchor, date_from, date_to)`（`services/reports/_common.py:56-80`）——给了 `date_from`+`date_to` 就用它，否则退回 `mode`+`anchor`；只给一头直接 400「date_from 与 date_to 必须同时给」（L71-72）。
  `mode=day` → 当天；`week` → 本周一起 7 天；`month` → 本月 1 日到**本月最后一天**（`_common.py:16-31`）。

### 0.5 谁能看：报表只有派单员一个角色
| 端点族 | 权限点 | 谁有 | 源码 |
|---|---|---|---|
| `/reports/*`（9 个） | `Permission.ORDER_DISPATCH`（"order:dispatch"） | 只有 `dispatcher` | `reports.py:64,79,94,113,133,157,176,188,213`；`rbac.py:42,93` |
| `/stats/*`（7 个）+ 异常处理写入口 | `Permission.STATS_READ`（"stats:read"） | 只有 `dispatcher` | `stats.py:36,56,69,81,97,113,124`；`exception_resolution.py:45`；`rbac.py:58,106` |

- 权限语义（`rbac.py:139-166`）：`ORDER_DISPATCH: ("all", "派单是全局动作…")`（L149）、`STATS_READ: ("all", "报表是全店口径…没有「只看自己那份」的版本")`（L165）。
- `dispatcher` 在 `BYPASS_ROLES` 里一律放行（`rbac.py:175-182`），所以派单员=老板/经营者。
  ⇒ **货主端与司机端在这条线上一个端点都调不到**（货主只有 ORDER_READ_OWN / LEDGER_READ_OWN 等，`rbac.py:62-85`）。
- 报表端点的「明细钻取」目标端点大多另有权限（例如账本是 `LEDGER_READ_ALL`、开销是 `DispatcherUser`、库存流水是 `PRODUCT_MANAGE`）——见每节的「明细钻取入口」。

---

## 1. 一页总览表（`reports.py` 的 9 个端点）

| 报表 | 端点 | 一句话用途 | 主要看的人 | 关键指标个数 |
|---|---|---|---|---|
| 营业纵览 | `GET /api/v1/reports/turnover` | 这一段做了多少营业额、收回来多少、还欠多少、撤了多少单 | 老板、财务 | **15 个标量 + 2 个数组**（曲线 series、挂账单位 TOP5） |
| 商品经营 | `GET /api/v1/reports/products` | 这一段哪些商品卖了多少、赚不赚、损耗多少 | 老板、采购/库管 | **10 个标量 + 逐商品 8 个数字** |
| 经营利润 | `GET /api/v1/reports/profit` | 这一段到底赚了多少（四块钱摊在一张表上） | 老板、会计 | **25 个标量 + 3 个数组** |
| 车辆成本 | `GET /api/v1/reports/vehicle-cost` | 每一台车这一段花了多少钱（⛔ 没有收入） | 老板、车队管理 | **8 个标量 + 逐车 10 个数字** |
| 成本覆盖 | `GET /api/v1/reports/cost-coverage` | 这一段的收入里有多少「算得出成本」，哪些商品从没记过进货价 | 老板（看数据可不可信）、采购 | **8 个标量 + 逐商品 3 个数字** |
| 税账 | `GET /api/v1/reports/tax-summary` | 这一段该交多少增值税（销项 − 进项） | 会计、老板 | **15 个标量 + 逐票 8 个数字** |
| 挂账单位欠款 | `GET /api/v1/reports/arrears-summary` | 哪个挂账单位还欠多少、欠了几笔 | 财务、老板 | **每行 2 个数字**（count / amount） |
| 客户欠款 / 应收账龄 | `GET /api/v1/reports/customer-balances` | 一行一个债务人：还欠多少、欠了多久、额度够不够 | 财务、老板 | **逐行 12 个数字（含 4 个账龄桶）+ 总 8 个** |
| 报表导出 | `GET /api/v1/reports/export` | 把上面这些（+ 司机/客户/资金/审计）导成一张 Excel | 老板、会计 | 11 个 kind，见 §11 |

**相邻但不在 `reports.py` 里的 7 个端点**（`/stats/*`，仪表盘会用到；见 §10）：司机绩效、异常单、货主绩效、商品下钻、货主活跃度、货主商品图、统计导出。

---

## 2. 营业纵览 `GET /api/v1/reports/turnover`

- **端点**：`reports.py:64-76` ｜权限 `Permission.ORDER_DISPATCH` ｜出参 `TurnoverReportOut`（`schemas/reports.py:19-57`）
- **入参**：`mode`（day|week|month，默认 `day`，L68）、`date`（别名 `anchor`，必填，L69）、`date_from`、`date_to`（L70-71）；实现 `services/reports/turnover_query.py::build_turnover`（L24-201）
- **用途一句话**：这一段**已送达**的单做了多少营业额、收回来多少、还欠多少、撤了多少单，外加当天的曲线。
- **口径前提**：全部只算已送达 + 非软删（§0.1）；窗口内的单按**送达当地日**分桶（`turnover_query.py:64`）。

| 字段 | 中文名 | 口径 | 类型 |
|---|---|---|---|
| `total_amount` | 营业额（应收） | 区间；Σ `order_money.receivable`；**含未收款、不含未送达** | 钱 |
| `total_orders` | 完成单量 | 区间；窗口内已送达单数 | 数量 |
| `total_freight` | 司机应得（配送成本） | 区间；Σ `driver_pay.pay_for_order(o).total`，**只对有按单应付的单**（`turnover_query.py:81`）；⛔ 不是 Σ `orders.freight_fee`，工资制司机不在这里 | 钱 |
| `avg_order` | 单均价 | 区间；`total_amount / total_orders`，**先量化两位**（`turnover_query.py:159`） | 钱 |
| `series[]` | 曲线 | 区间；**`start == end` 时按小时 24 桶**，跨天按天（`turnover_query.py:145-155`）；每点 label/amount/orders（`schemas/reports.py:7-11`） | 钱+数量 |
| `cost_total` | 商品成本合计 | 区间；只累加**参与毛利**的行（`turnover_query.py:103-114`），口径见 §0.3 | 钱 |
| `cost_covered_amount` | 参与毛利的收入 | 区间；只收有成本那批行的 `line_receivable`（`turnover_query.py:107-110`）——毛利的两侧必须是同一批行 | 钱 |
| `total_lines` | 商品行总数（覆盖率分母） | 区间；净数量 > 0 的行（`turnover_query.py:95-97`） | 数量 |
| `cost_covered_lines` | 参与毛利的行数（分子） | 区间 | 数量 |
| `cost_avg_lines` | 走加权均价的行数 | 区间；①②级（`cost_basis.py:49-51`） | 数量 |
| `cost_snapshot_lines` | 退回下单快照的行数 | 区间；③级 | 数量 |
| `damage_qty` | 货损件数 | 区间 | 数量 |
| `damage_amount` | 货损金额 | 区间；Σ(成本快照 × 货损件数)，**故意不跟毛利改均价**（`turnover_query.py:121-122`） | 钱 |
| `collected` | 已收（净） | 区间；Σ `mm.settled − mm.refunded`（`turnover_query.py:134`），**含挂账结清** | 钱 |
| `arrears_total` | 挂账未收 | 区间；Σ `mm.arrears`（≠0 才累加，`turnover_query.py:135-138`）；与 `collected` 之和恒等于营业额 | 钱 |
| `cancelled_orders` | 撤销单量 | 区间；`status=CANCELLED` 且 `cancelled_at` 落在**业务当地日**区间（`turnover_query.py:160-178`）、排软删 | 数量 |
| `arrears_units[]` | 挂账单位 TOP5 | 区间；按金额降序取前 5（`turnover_query.py:197-200`） | 钱 |
| `period_label` | 期间标签 | 文本（`_span_label`：`9-18` / `2026-09月` / `9-1~9-20`） | 时间 |

- **明细钻取入口**：`GET /orders?delivered_from=&delivered_to=`（`orders_query.py:91-96`，缺省 limit 300，L97）；挂账单位逐笔 → `GET /reports/customer-balances?include_orders=true` 或 `GET /ledger/accounts?kind=shipper|member`（`ledger.py:189-195`）。
- **看的人与时机**（归纳，代码里没有这个字段）：老板每天开 App 第一眼；财务对账时看 `collected`/`arrears_total`。
- **归类**：**每天必看**（金额/单量/已收/欠款/撤销）。成本与覆盖率属于每周或月末看。

---

## 3. 商品经营 `GET /api/v1/reports/products`

- **端点**：`reports.py:79-91` ｜权限 `ORDER_DISPATCH` ｜出参 `ProductReportOut`（`schemas/reports.py:78-95`）｜实现 `services/reports/product_query.py::build_products`（L21-106）
- **入参**：同营业纵览（mode / date / date_from / date_to）
- **用途一句话**：这一段哪些商品卖了多少、金额多少、成本多少、损耗多少（按商品名快照分组，`product_query.py:46`）。
- **口径**：数量与金额一律按**净额**（减掉已退数量/金额，`product_query.py:56-59`），与 `build_turnover` 逐行同源。

| 字段 | 中文名 | 口径 | 类型 |
|---|---|---|---|
| `total_qty` | 总销量 | 区间；净数量合计 | 数量 |
| `total_amount` | 总金额（应收） | 区间 | 钱 |
| `cost_total` | 商品成本合计 | 区间；只算参与毛利的行 | 钱 |
| `damage_qty` / `damage_amount` | 货损件数 / 金额 | 区间；金额用成本快照 | 数量/钱 |
| `total_lines` / `cost_covered_lines` | 行数 / 参与毛利的行数 | 区间 | 数量 |
| `cost_covered_amount` | 参与毛利的收入 | 区间 | 钱 |
| `cost_avg_lines` / `cost_snapshot_lines` | 两段成本口径的行数 | 区间 | 数量 |
| `items[]` | 逐商品 | 每项：`product_name` / `qty` / `amount` / `order_count` / `cost`（L66）/ `damage_qty` / `damage_amount` / `covered_amount`（L73）/ `covered_lines`（L75）；按金额降序（`product_query.py:91`） | 钱+数量 |

⚠️ `covered_amount` 不可省：缺它毛利会虚高（`schemas/reports.py:73` 注释实测 305.50−260=45.50 正确 vs 页面 587.50−260=327.50，**虚高 7.2 倍**）。
- **明细钻取入口**：`GET /stats/product-drilldown?product_name=&date_from=&date_to=`（`stats.py:64-74`，权限 `STATS_READ`）；成本来源 → `GET /inventory/movements?product_id=&date_from=&date_to=`（`inventory.py:25-37`，权限 `PRODUCT_MANAGE`）。
- **看的人与时机**（归纳）：老板看「哪些货走得动」，采购/库管看货损。
- **归类**：**偶尔才查**（但货损高时是当天的异常线索）。

---

## 4. 经营利润 `GET /api/v1/reports/profit`

- **端点**：`reports.py:94-110` ｜权限 `ORDER_DISPATCH` ｜出参 `ProfitReportOut`（`schemas/reports.py:113-184`）｜实现 `services/reports/profit_query.py::build_profit`（L69-153）
- **docstring 原话**（`reports.py:103-106`）：「把已经算得出来的四块钱（营业额 / 商品成本 / 司机应得 / 开销）按同一个窗口汇合。**只读——不新增事实**」。
- **四块钱的来源映射**（`profit_query.py:1-31`）：营业收入←`turnover.total_amount`；商品成本←`turnover.cost_total`；配送成本←`turnover.total_freight`；期间费用←`expenses` 按 `exp_date`；税金及附加←分类名带「税」（`tax_query.is_tax_category`）；应交增值税←`tax_service.sum_taxes`；车辆折旧←`services/vehicle_depreciation.py`。

**两条核心公式**（`profit_query.py:119-120`）：

    gross_profit     = revenue_covered − cost_total
    operating_profit = gross_profit − delivery_cost − operating_expense_total − depreciation_total − tax_total

| 字段 | 中文名 | 口径 | 类型 |
|---|---|---|---|
| `revenue_total` | 营业收入 | 区间；= 营业纵览 `total_amount` | 钱 |
| `revenue_covered` | 参与毛利的收入 | 区间 | 钱 |
| `revenue_uncovered` | 算不出成本的收入 | 区间；= total − covered，**单列不进毛利** | 钱 |
| `cost_total` | 商品成本 | 区间 | 钱 |
| `gross_profit` | 毛利 | 区间；covered − cost | 钱 |
| `total_lines` / `covered_lines` / `cost_avg_lines` / `cost_snapshot_lines` | 行数四件套 | 区间；口径可核查性 | 数量 |
| `delivery_cost` | 配送成本（司机应得） | 区间；⛔ **不含固定工资制司机的工资**（`schemas/reports.py:149`）→ 营业利润会偏高（`profit_query.py:52-66` 的 `_NOTES` 里如实写着） | 钱 |
| `operating_expense_total` | 期间费用合计 | 区间；`Expense.exp_date` 落窗口按分类聚合（`profit_query.py:82-86`）⛔ 不用 `cash_flows.flow_date`；`expenses` 表无软删列（`profit_query.py:81`） | 钱 |
| `operating_expenses[]` | 期间费用分解 | 每项 `{category, amount}`，金额降序（`profit_query.py:92`）；**已含货损开销**，⛔ 不再单独扣 `damage_amount` | 钱 |
| `depreciation_total` | 车辆折旧 | 区间；按自然月摊到窗口每一天（`vehicle_depreciation.py:14-17`） | 钱 |
| `depreciation_monthly_total` | 月折旧额合计 | ⛔ **不是窗口金额**，是"每月多少" | 钱 |
| `depreciation_vehicle_count` | 参与计提的车数 | 区间 | 数量 |
| `depreciation_uncovered_count` / `depreciation_uncovered[]` | 折旧未覆盖车数 / 名单 | 每项 `{vehicle_id, plate_no, reasons}`，原因三种：「没录购置价」/「没录购置日期」/「没录使用年限」（`vehicle_depreciation.py:56-58`） | 数量 |
| `tax_total` | 税金及附加 | 区间；= 期间费用里分类名带「税」的那部分（`tax_query.py:36,48-50`）⛔ 已在 `operating_expenses` 里，**不重复扣** | 钱 |
| `vat_output` / `vat_input` / `vat_payable` | 销项税 / 进项税 / 应交增值税 | 区间；= `tax_service.sum_taxes` 的 `output.tax_amount / input.tax_amount / 差额`（`tax_service.py:732-739`）；⛔ 增值税是价外税，**不进 `operating_profit`** | 钱 |
| `tax_expenses[]` | 税金及附加分解 | `{category, amount}`；Σ = `tax_total` | 钱 |
| `operating_profit` | 营业利润 | 区间；见上面公式 | 钱 |
| `collected` / `arrears_total` | 已收 / 挂账未收 | 区间；与营业纵览同源 | 钱 |
| `cancelled_orders` | 撤销单量 | 区间 | 数量 |
| `damage_qty` / `damage_amount` | 货损 | 区间 | 数量/钱 |
| `notes[]` | 口径说明 | 后端生成的口径文字（`profit_query.py:52-66`） | 文本 |

**7 条恒等式**（`schemas/reports.py:116-127`，构造上保证，可用于自检）：① `revenue_total` = 营业纵览 `total_amount` ② `revenue_covered + revenue_uncovered = revenue_total` ③ 毛利式 ④ 营业利润式 ⑤ `delivery_cost` = 营业纵览 `total_freight` ⑥ Σ `operating_expenses[].amount` = 区间 `expenses` 合计 ⑦ `vat_payable` = 销项 − 进项 且 Σ `tax_expenses[].amount` = `tax_total`。

- **明细钻取入口**：费用分类 → `GET /expenses?category=&date_from=&date_to=`（`expenses.py:20-28`，权限 `DispatcherUser`；⚠️ **没有 `vehicle_id` 过滤参数**，只能是分类/司机/日期）；折旧 → `GET /vehicles`（`vehicles.py:281`，台账四格）；收入/成本 → `GET /reports/turnover` / `GET /reports/products`；税 → `GET /invoices`。
- **看的人与时机**（归纳）：老板月末/月初必看；会计做账时看。
- **归类**：**偶尔才查**（月度），但 `operating_profit` 与 `collected/arrears_total` 是仪表盘首页候选。

---

## 5. 车辆成本 `GET /api/v1/reports/vehicle-cost`

- **端点**：`reports.py:113-130`（**mode 默认 `month`**，L117）｜权限 `ORDER_DISPATCH` ｜出参 `VehicleCostReportOut`（`schemas/reports.py:222-247`）｜实现 `services/reports/vehicle_cost_query.py::build_vehicle_cost`（L100-172）
- **用途一句话**：每一台车这一段「折旧 + 这台车的开销 + 挂在这台车上的司机配送成本」花了多少（docstring `reports.py:122-126`：「⛔ 本表没有收入」；原因见 `schemas/reports.py:190-191`：订单上只有司机，没有「这一单是哪台车拉的」这个事实）。
- **两条可复算恒等式**（`vehicle_cost_query.py:1-22`）：逐车 `total_cost == depreciation + expense_total + delivery_cost`；`totals.total_cost == Σ per_vehicle[*].total_cost`。

| 字段 | 中文名 | 口径 | 类型 |
|---|---|---|---|
| `vehicle_count` / `covered_count` / `uncovered_count` | 车数 / 折旧算得出的 / 算不出的 | 区间 | 数量 |
| `depreciation_total` | 折旧合计 | 区间；只有覆盖到的车计入 | 钱 |
| `depreciation_monthly_total` | 月折旧额合计 | ⛔ 不是窗口金额 | 钱 |
| `expense_total` | 车辆开销合计 | 区间；`expenses.vehicle_id` 落这台车的开销 | 钱 |
| `delivery_cost_total` | 配送成本合计 | 区间；挂在这台车的司机在窗口内的按单应付（`pay_for_order`） | 钱 |
| `total_cost` | 车辆成本合计 | 区间；= 上三者之和 | 钱 |
| `per_vehicle[]` | 逐车 | vehicle_id / plate_no / is_active / driver_id / driver_name / `depreciation_covered`（L200）/ `depreciation_uncovered_reasons`（L201）/ purchase_price / purchase_date / useful_life_years / `residual_rate`（台账原值，留空=None，L206）/ `residual_rate_effective`（实际计提用，留空=0，L208）/ `monthly_depreciation`（**算不出来是 None 不是 0**；0 = 已提足，L210）/ depreciation / `expenses[]`（分类明细）/ expense_total / delivery_cost / total_cost（L131-151） | 钱为主 |
| `notes[]` | 口径说明 | 5 条（`vehicle_cost_query.py:47-53`） | 文本 |

- **折旧的算法与边界**（`vehicle_depreciation.py`）：月折旧 = 购置价 ×(1−残值率)÷(使用年限×12)，ROUND_HALF_UP 到分（L14-17）；提足之后 = 0 且**不算未覆盖**（L21-30）；残值率留空=0%（四格里唯一留空有意义的一格）；停用的车照提；**折旧额永不落库**（纯函数）。
- **明细钻取入口**：`GET /expenses?date_from=&date_to=`（按分类看；⚠️ 不支持按车过滤）；车辆台账 → `GET /vehicles`（`vehicles.py:281`）。
- **看的人与时机**（归纳）：老板月末看每台车赚不赚（要另外心算收入）；车队管理看维修/油耗。
- **归类**：**偶尔才查**（月度/季度）。

---

## 6. 成本覆盖 `GET /api/v1/reports/cost-coverage`

- **端点**：`reports.py:133-151`（mode 默认 `month`，L137）｜权限 `ORDER_DISPATCH` ｜出参 `CostCoverageReportOut`（`schemas/reports.py:262-288`）｜实现 `services/reports/cost_coverage_query.py::build_cost_coverage`（L90-119）
- **用途一句话**：这一段的收入里有多少「算得出成本」（口径=**只搬运不重算**，`cost_coverage_query.py:1-35`）；⚠️ 两件事不要混：「没记过进货价的商品」清单（按商品，`_never_priced` L61-87）≠「算不出成本的收入」（按订单行）。

| 字段 | 中文名 | 口径 | 类型 |
|---|---|---|---|
| `revenue_total` | 收入合计 | 区间；= 营业纵览 `total_amount` | 钱 |
| `revenue_covered` / `revenue_uncovered` | 算得出成本 / 算不出成本的收入 | 区间 | 钱 |
| `total_lines` / `covered_lines` | 行数 / 覆盖行数 | 区间 | 数量 |
| `cost_avg_lines` / `cost_snapshot_lines` | 两段口径的行数 | 区间 | 数量 |
| `missing_purchase_price_count` | 从没记过进货价的商品数 | 按商品台账判（与窗口无关） | 数量 |
| `missing_purchase_price[]` | 这些商品 | 每项 `{product_id, name, unit, stock, cost_price, is_active}`；`cost_price` 是**台账最近一次记过的进货价**，⛔ 不是报表算成本用的加权均价（`schemas/reports.py:258`） | 钱+数量 |
| `notes[]` | 口径说明 | 4 条（`cost_coverage_query.py:53-58`） | 文本 |

- **明细钻取入口**：`GET /inventory/movements?product_id=`（`inventory.py:25-37`，权限 `PRODUCT_MANAGE`）；收入侧 → `GET /reports/products`。
- **看的人与时机**（归纳）：老板判断「报表里的毛利可不可信」；采购去补进货价。
- **归类**：**偶尔才查**（发现毛利异常时）。

---

## 7. 税账 `GET /api/v1/reports/tax-summary`

- **端点**：`reports.py:157-174`（mode 默认 `month`，L161）｜权限 `ORDER_DISPATCH` ｜出参 `TaxSummaryOut`（`schemas/invoice.py:124`）｜实现 `services/reports/tax_query.py::build_tax_summary`（L67-116）+ `tax_service.sum_taxes`（L679-739）
- **三条不许动口径**（`tax_query.py:1-19`）：增值税价外税不进 `operating_profit`；窗口按 `invoices.invoice_date`（⛔ 不按 `created_at`，补录上月的票落回上月）；汇总唯一实现 `tax_service.sum_taxes`。
- **单票判据唯一一处**：`counts_in_tax`（`tax_service.py:100-106`）：软删→不算；`VOIDED`→不算；否则 `tax_rate is not None` 才算。
- **税额唯一算法**：`tax_of_amount = amount − amount/(1+rate/100)`（`tax_service.py:75-86`）；默认税率 `DEFAULT_TAX_RATE = 3.00`%（小规模一档，`tax_service.py:52`）。

| 字段 | 中文名 | 口径 | 类型 |
|---|---|---|---|
| `output` / `input` | 销项 / 进项 | 区间（按开票日）；各含 `{count, amount, net_amount, tax_amount, untaxed_count, untaxed_amount}`（`tax_service.py:668-676`） | 钱+数量 |
| `vat_payable` | 应交增值税 | 区间；`output.tax_amount − input.tax_amount`（`tax_service.py:732-739`） | 钱 |
| `voided_count` | 作废票数 | 区间；**只计数不进金额** | 数量 |
| `by_rate[]` | 按税率分桶 | 按 (direction, tax_rate) 分桶，排序：销项在前、税率从高到低（`tax_service.py:738`） | 钱 |
| `invoices[]` | 逐票 | id / direction / invoice_no / invoice_date / amount / tax_rate / tax_amount / net_amount / status / party_name / `counts_in_tax`（`tax_query.py:85-99`） | 钱+时间 |
| `default_tax_rate` | 默认税率 | 3.00（一票一改） | 比率 |
| `mode/anchor/date_from/date_to/label` | 窗口回显 | 时间 | 时间 |
| `notes[]` | 口径说明 | 4 条（`tax_query.py:39-45`） | 文本 |

- **明细钻取入口**：`GET /invoices?direction=&status=&date_from=&date_to=`（`invoices.py:117-131`；**读**用 `Permission.ORDER_DISPATCH`，见 `invoices.py:17-22,58`——写用 `LEDGER_EDIT`）。
- **看的人与时机**（归纳）：会计每月申报前；老板看「这个月要交多少税」。
- **归类**：**偶尔才查**（月度），但 `vat_payable` 有资格上月度仪表盘。

---

## 8. 挂账单位欠款 `GET /api/v1/reports/arrears-summary`

- **端点**：`reports.py:176-186` ｜权限 `ORDER_DISPATCH` ｜⚠️ **没有 `response_model`，直接返回 `list[dict]`**；入参 `date_from` / `date_to` **两个都必填**（L180-181），L183 走 `ensure_date_order`；实现 `services/reports/arrears_query.py::build_arrears_summary`（L22-70）
- **用途一句话**：这一段的已送达单里，**还没收到钱**的按挂账单位汇总，谁欠最多排最前。

| 字段 | 中文名 | 口径 | 类型 |
|---|---|---|---|
| `name` | 挂账单位 | `o.arrears_unit_name.strip()`，空 → 「未分配挂账单位」（`arrears_query.py:66`） | 文本 |
| `count` | 欠款笔数 | 区间；已送达 + `paid is False` | 数量 |
| `amount` | 欠款金额 | 区间；Σ `order_money.money_map(...).arrears`（`arrears_query.py:56,69`）；`arrears == 0` 的单整条跳过（L62-65）；按金额降序 | 钱 |

- **判据**：`DELIVERED + delivered_at 非空 + deleted_at is None + Order.paid is False`（`arrears_query.py:45-49`）。⚠️ L33-44 的注释记着两次真实偏差：「少一条软删过滤 → 同页两个挂账未收，实测差 ¥500」「多一条 `payment_method=='arrears'` 判据 → 63,006.00 vs 62,920.50，差 ¥85.50 / 7 张单」。
- **明细钻取入口**：`GET /reports/customer-balances?include_orders=true`（同一批钱，多了账龄与逐单）；`GET /ledger/accounts?kind=shipper|member`（`ledger.py:189-195`）；收款入口 `POST /ledger/receipts`（`ledger.py:734`）。
- **看的人与时机**（归纳）：财务每天/每周催款；老板看「谁欠着」。
- **归类**：**每天必看**（钱）。

---

## 9. 客户欠款 / 应收账龄 `GET /api/v1/reports/customer-balances`

- **端点**：`reports.py:188-210`（mode 默认 `month`，L192；`include_orders: bool = Query(False)` L196）｜权限 `ORDER_DISPATCH` ｜出参 `CustomerBalancesOut`（`schemas/reports.py:362-380`）｜实现 `services/reports/balance_query.py::build_customer_balances`（L120-231）
- ⚠️ **这是唯一一张「时点账」**：`as_of = min(窗口末, 今天)`（`reports.py:207`、docstring L198-205）；**窗口起点不参与余额**，只定 `as_of` 上界。`_NOTES`（`balance_query.py:33-45`）里那句最要紧：把报表日往前调 ≠ 「当时那一刻的账」，因为收款流水没有历史快照（= 「那些天之前送达的单到今天还欠多少」）。
- **用途一句话**：一行一个债务人：还欠多少、欠了多久（四桶账龄）、额度够不够。

| 字段 | 中文名 | 口径 | 类型 |
|---|---|---|---|
| `as_of` | 账截止日 | **时点**；= min(窗口末, 今天) | 时间 |
| `rows[].kind` | 债务人凭证类型 | 四种：`unit`（挂账单位）/ `unit_name`（单位已删只有名字快照）/ `shipper`（货主账号）/ `temp`（临时货主名）/ `unknown`（没填货主）——是对订单集合的**划分**（互斥不漏，`balance_query.py:78-96`） | 文本 |
| `rows[].balance` | 还欠多少 | 时点；**= Σ `buckets` − `prepaid`**（⛔ 不是 Σ 桶）；< 0 表示预收（`schemas/reports.py:330`） | 钱 |
| `rows[].prepaid` | 预收（负数部分） | 时点；**不进桶**（`balance_query.py:188-190`） | 钱 |
| `rows[].buckets` | 账龄四桶 | 时点；key 顺序固定 `0_30/31_60/61_90/over_90`（`balance_query.py:24`，界面⛔ 不自己排） | 钱 |
| `rows[].oldest_days` | 最老一笔欠了几天 | 时点；`max((as_of − anchor).days, 0)`（`balance_query.py:180-181`） | 时间 |
| `rows[].order_count` | 欠款单数 | 时点 | 数量 |
| `rows[].limit` | 额度 | **只有 `unit` 行才有**；`None` = 不限额（⛔ 不是 0，`schemas/reports.py:338`） | 钱 |
| `rows[].credit_used` | 已用额度 | = `max(balance, 0)`（`schemas/reports.py:340`） | 钱 |
| `rows[].credit_available` | 可用额度 | `limit − credit_used`（limit None→None） | 钱 |
| `rows[].over_limit` | 超限标记 | **只是提示，⛔ 不拦任何操作**（`schemas/reports.py:344`） | 布尔 |
| `rows[].orders[]` | 逐单（仅 `include_orders=true`） | order_id / order_no / delivered_on / shipper_name / receivable / `collected`（**净收 = 已收 − 已退**）/ arrears / `anchor`（账龄锚点 = 最早一笔正账本行日期，没有就用送达那天）/ days / bucket（`schemas/reports.py:290-308`） | 钱+时间 |
| `totals` | 合计 | balance / prepaid / buckets / debtor_count / order_count / over_limit_count / `no_unit_balance`（没挂账单位的欠款，L358）/ `no_unit_count`（L359） | 钱+数量 |
| `bucket_keys` | 桶顺序 | 固定四键（`schemas/reports.py:377`） | 文本 |
| `notes[]` | 口径说明 | 6 条（`balance_query.py:33-45`） | 文本 |

- **恒等式**（`schemas/reports.py:367-369`）：逐行 `balance == Σbuckets − prepaid`；`totals.balance == Σ rows[].balance`；`credit_available == limit − credit_used`。
- **账龄锚点**：只取 `min(Ledger.entry_date)`，`source ∈ (ORDER, MANUAL)`（`balance_query.py:59-75`）；红冲只减金额、不改起点；无账本行按送达日；下界真的是 1970-01-01（`EARLIEST`，L28）。
- **明细钻取入口**：`include_orders=true` 自带逐单；账本流水 → `GET /ledger/entries?date_from=&date_to=`（`ledger.py:136-145`，权限 `LEDGER_READ_OWN|LEDGER_READ_ALL`，L138）。
- **看的人与时机**（归纳）：财务每周/每天盯账龄与超限；老板看总额与最老的账。
- **归类**：**每天必看**（钱+风险），但四桶账龄看月度趋势。

---

## 10. 相邻数据面：`/stats/*`（7 个端点，不属 `reports.py` 但仪表盘要用）

文件 `backend/app/api/v1/stats.py`（133 行），全部 `require_permission(Permission.STATS_READ)`、全部先 `ensure_date_order`：

| 端点 | 行 | 入参 | 出参 / 用途 |
|---|---|---|---|
| `GET /stats/shipper-product-chart` | L30-48 | date_from/date_to 必填、`granularity ∈ {month,year}` 默认 month、`metric ∈ {quantity,amount}` 默认 quantity | `ShipperProductChartOut`：货主 × 商品维度的图表 |
| `GET /stats/shipper-activity` | L51-61 | shipper_id + 日期 | `ShipperActivityOut` |
| `GET /stats/product-drilldown` | L64-74 | `product_name`(min_length=1) + 日期 | `list[DrilldownOrderItem]`：**商品报表的逐单下钻** |
| `GET /stats/driver-performance` | L77-90 | 日期 | `DriverPerformanceOut{period_label, drivers[]}` |
| `GET /stats/shipper-performance` | L93-106 | 日期 | `ShipperPerformanceOut` |
| `GET /stats/exception-orders` | L109-118 | 日期 | `list[ExceptionOrderItem]`：**异常单**（与导出 `kind=audit` 同源） |
| `POST /stats/export` | L121-133 | `StatsExportBody` | xlsx，文件名 `stats-<from>-<to>.xlsx` |

另有写入口 `POST /stats/exception-orders/{order_id}/resolve`（`api/v1/exception_resolution.py:41-45`，同 `STATS_READ`）——报表中心「异常与审计」里点「处理」走的就是它（安卓侧注释：`AiWriteOrderHandlers.kt:1036`）。

### 10.1 司机绩效 `stats_service.driver_performance`（L257-331）——`/stats/driver-performance` 与导出 `kind=drivers` 同一实现
| 字段 | 中文名 | 口径 | 类型 |
|---|---|---|---|
| `completed_count` | 完成单量 | 区间；按 `delivered_at` 取已送达（L262） | 数量 |
| `on_time_rate` | 准时率 | 区间；**无有效样本 = `None`**（L275） | 比率 |
| `avg_delivery_seconds` | 平均送达耗时（秒） | 区间；`None` = 无样本 | 时间 |
| `photo_upload_rate` | 拍照上传率 | 区间 | 比率 |
| `billing_mode` | 计费方式 | 唯一实现 `driver_pay.snapshot_mode`（L296）；L284-295 注释记着旧 bug：先读 `users.billing_mode` → 「绩效说工资制、结算页照列应得」 | 枚举 |
| `freight_owed` | 待结运费 | 区间；**只算 `has_per_order_pay` 的单**：Σ `pay_for_order(ode).total` − 该司机 PAID 结算单合计，取 max(…,0)（L304-316）；工资制且无计件单 → `None` | 钱 |
| `driver_name` | 司机名 | full_name → phone → id（L271）；按单量降序（L330） | 文本 |

### 10.2 异常单 `stats_service.exception_orders`（L397-475）
两段并集：① `is_exception=True` 且 `order_date` 在区间、`deleted_at is None`（L402-411）；② `is_exception=False` 但 `auto_exception_reason` 命中（L437-473）。
自动异常判据（`auto_exception_reason` L375-395）：已解决不再复现；`CANCELLED` → 「已撤销/撤回订单」；`PENDING_DISPATCH` 超 4 小时 → 「待派超时（超过4小时未派单）」；`DISPATCHED/ACCEPTED` 超 `expected_deliver_before` → 「超时未送（超过预计送达时间）」；`DELIVERED` 且 `delivered_at > expected` → 「逾期送达（超过预计送达时间）」。
逐行字段（L421-435 / L459-472）：id / order_no / order_date / status / shipper_name / driver_name / exception_reason / exception_resolution / expected_deliver_before / delivered_at / exception_resolved_at；合并后按 id 降序。

---

## 11. 报表导出 `GET /api/v1/reports/export`

- **端点**：`reports.py:213-681` ｜权限 `ORDER_DISPATCH` ｜返回 `StreamingResponse(xlsx)`（L677-681）
- **通用入参**：`kind`（白名单正则，L217）、`mode`（L218）、`date`（L219）、`date_from`（L220，注释：finance/customers 可用）、`date_to`（L221）；窗口 `s, e = _span(mode, d, date_from, date_to)`（L242），文件名 `{kind}-report-{range_label}.xlsx`（L676，range_label 单日只写日期，L243）。

**11 个 kind 白名单**（L217）：`turnover | products | drivers | customers | finance | audit | profit | vehicle-cost | cost-coverage | tax-summary | customer-balances`

| kind | sheet 名 | 代码位置 | 导出什么 |
|---|---|---|---|
| `turnover` | 营业纵览 | L253-277 | 营业纵览的数字 + 曲线 |
| `profit` | 经营利润 | L278-321 | 利润表（注释 L280：口径见 `profit_query.py`，一个原始金额都不自己算） |
| `vehicle-cost` | 车辆成本 | L322-356 | 车辆成本（注释 L324 同上） |
| `cost-coverage` | 成本覆盖 | L357-386 | 成本覆盖 + 没记过进货价的商品清单（注释 L359 同上） |
| `tax-summary` | 税账 | L387-417 | 税账（销项/进项/应交） |
| `customer-balances` | 客户欠款 | L418-470 | 客户欠款；`as_of = min(e, business_today())`（L422）、**强制 `include_orders=True`** |
| `products` | 商品经营 | L471-489 | 商品报表逐商品 |
| `drivers` | 司机绩效 | L492-529 | **复用 `stats_service.driver_performance(db, s, e)`**（L505）；列：司机 / 完成单量 / 准时率 / 拍照率 / 平均送达分钟 / 计费方式 / 待结运费；工资制司机的待结列印文字「**工资制**」（L527） |
| `customers` | 客户经营 | L530-584 | 账本流水按货主/临时货主/批发商三类聚合笔数与总额（`visible_ledger_select()` + `Ledger.entry_date` 下推，L548-554）；按 `users.is_member` 分「批发商」；末尾「挂账未收 TOP」调 `build_arrears_summary`（L583） |
| `finance` | 资金收支 | L585-618 | `CashFlow` 按 `flow_date` 落窗口、非软删（L588-598）；按 `direction` 分 in/out 求 income/expense/净额（L600-601）；另按 `Expense.exp_date` 聚合分类（L613-618） |
| `audit` | 异常与审计 | L619-672 | `stats_service.exception_orders`（L624；列：订单号/货主/司机/异常原因/处理结果/解决时间，解决时间 `local_stamp(..., "%Y-%m-%d %H:%M")` L636）+ **敏感操作日志**（`business_range_utc(s,e)` 过滤 `OperationLog`，L644-653，**limit 200** L651，超出有截断说明 L654-658，时间列 `local_stamp(log.created_at)` L669） |

- **金额写法**：导出里的钱一律写**数字**（不是文本），`_money` 显式 `ROUND_HALF_UP` 到分（`_common.py:89-104`），避免「导出与页面差 1 分」。
- **两处需要人工对齐**：`services/ledger_export.py:72` 与 `services/stats_export.py:68` 的注释都要求**列名/列序/单位与 `/reports/export?kind=drivers` 对得上**；⚠️ 其中「**七个 kind**」的说法是改成本口径**之前**的旧文案，现在白名单是 11 个（以 `reports.py:217` 为准）。

---

## 12. 每天必看 vs 偶尔才查（本文的归纳，代码里没有这个区分）

> ⚠️ 「未在代码中找到」任何「每天必看 / 仪表盘」字样的后端定义——这一节是按用途与口径**归纳**的，属于产品判断，不是既有字段。

### 每天必看（当天经营结果 / 异常 / 待办 / 钱）
| 指标 | 来源 | 为什么是每天 |
|---|---|---|
| 营业额 `total_amount` | `/reports/turnover` | 当天做了多少生意 |
| 完成单量 `total_orders` | 同上 | 生意的体量 |
| 已收 `collected` / 挂账未收 `arrears_total` | 同上 | 钱收回来没有 |
| 挂账单位欠款 `arrears_units[]` | 同上（TOP5） | 今天该催谁 |
| 撤销单量 `cancelled_orders` | 同上 | 当天的异常信号 |
| 货损 `damage_qty/damage_amount` | 同上 / 商品报表 | 当天赔了多少 |
| 异常单清单 | `/stats/exception-orders`（`stats.py:109-118`） | 待办：待派超时/超时未送/逾期送达 |
| 客户欠款（含超限） | `/reports/customer-balances` | 谁欠着、欠多久、额度爆没爆 |
| 司机待结运费 | `/stats/driver-performance[].freight_owed` | 该付司机的钱 |

### 偶尔才查（逐单 / 逐客户 / 逐司机 / 台账）
| 明细 | 来源 | 什么时候查 |
|---|---|---|
| 商品经营逐商品 | `/reports/products` | 每周/月末看走货 |
| 商品逐单下钻 | `/stats/product-drilldown` | 某个商品对不上数时 |
| 经营利润全表 | `/reports/profit` | 月度结账 |
| 车辆成本逐车 | `/reports/vehicle-cost` | 月度/季度 |
| 成本覆盖 + 没记过进货价的商品 | `/reports/cost-coverage` | 毛利不可信时 |
| 税账逐票 | `/reports/tax-summary` + `/invoices` | 申报期 |
| 账龄四桶趋势 | `/reports/customer-balances` | 周/月 |
| 司机绩效逐司机 | `/stats/driver-performance` | 结算时 |
| 货主绩效 / 活跃度 | `/stats/shipper-performance` / `shipper-activity` | 维护大客户时 |
| 资金收支明细 | 导出 `kind=finance` + `/cash-flows` | 对账 |
| 操作日志（审计） | 导出 `kind=audit`（limit 200）+ `/operation-logs` | 查「谁改了这个价」 |
| 库存流水 | `/inventory/movements` | 查成本来源 |

---

## 13. 仪表盘候选指标 Top 15

排序依据：① 是否「每天必看」（当天结果/异常/钱）② 是否是别的数的入口 ③ 口径是否已经有唯一实现（现成可用、不会各算一套）。

| # | 指标 | 字段 / 来源 | 类型 | 为什么值得上首页 |
|---|---|---|---|---|
| 1 | 今日营业额（应收） | `turnover.total_amount`（`turnover_query.py:68-71`） | 钱 | 一句话回答「今天做了多少生意」，且口径唯一（`order_money.receivable`），不需要再解释 |
| 2 | 已收（净） | `turnover.collected`（`turnover_query.py:134`） | 钱 | 「钱回来了没有」与营业额是两件事；现场收现金也算得准（`order_money.py:27` 与 L32-38 的两个坑） |
| 3 | 挂账未收 | `turnover.arrears_total`（`turnover_query.py:135-138`） | 钱 | 与已收之和恒等于营业额（`order_money.py:30`），每天要盯的正是「没回来的那一半」 |
| 4 | 今日完成单量 | `turnover.total_orders`（`turnover_query.py:182`） | 数量 | 体量基线；没有它，金额波动无法判断是涨价还是少做 |
| 5 | 营业利润 | `profit.operating_profit`（`profit_query.py:120`） | 钱 | 老板真正关心的那一格；四块钱全部取既有唯一实现，口径有 7 条恒等式兜底 |
| 6 | 毛利 | `profit.gross_profit`（`profit_query.py:119`） | 钱 | 营业利润受折旧/费用干扰，毛利更能看出「卖货本身赚不赚」；两侧同批行（`revenue_covered − cost_total`）才不失真 |
| 7 | 商品成本 | `profit.cost_total`（`cost_basis.py` 三级口径） | 钱 | 毛利的另一半；加权均价上线后这个数才有意义，值得单独显示以便核对 |
| 8 | 配送成本（司机应得） | `profit.delivery_cost` = `turnover.total_freight`（`turnover_query.py:81`） | 钱 | 第二大成本项；⛔ 不含工资制司机（`schemas/reports.py:149`），首页显示能逼着把口径写清楚 |
| 9 | 期间费用 | `profit.operating_expense_total`（`profit_query.py:82-86`） | 钱 | 「今天花出去多少」（含货损开销），是老板能立刻采取行动的一格 |
| 10 | 车辆折旧 | `profit.depreciation_total`（`vehicle_depreciation.py:14-17`） | 钱 | 2026-10-04 起才有数据源，属于「一直被忽略的真实成本」；首页显示能顺带暴露「没录购置信息」的车 |
| 11 | 应交增值税 | `profit.vat_payable`（`tax_service.py:732-739`） | 钱 | 「这个月要交多少税」是老板的固定问题；走 `sum_taxes` 唯一实现，与税账页永远一致 |
| 12 | 司机待结运费 | `stats/driver-performance[].freight_owed`（`stats_service.py:304-316`） | 钱 | 欠司机的钱（应付侧）；只算有按单应付的单，工资制显示「工资制」而不是 0 |
| 13 | 异常单数（含类型） | `/stats/exception-orders` 长度 + `auto_exception_reason`（`stats_service.py:375-395`） | 数量 | 首页唯一真正的「待办入口」：待派超时/超时未送/逾期送达都能点进去处理 |
| 14 | 撤销单量 | `turnover.cancelled_orders`（`turnover_query.py:160-178`） | 数量 | 当天经营异常的早期信号；口径已修过两次（当地日 + 排软删），不是毛数 |
| 15 | 货损（件数 + 金额） | `turnover.damage_qty/damage_amount`（`turnover_query.py:121-122`） | 数量/钱 | 直接漏钱的一格，且金额用成本快照（与入账一致），可以放心对上账本 |

**候补（第 16-19，理由足够但不强）**：成本覆盖率 `cost_covered_amount / revenue_total`（`cost_coverage_query.py`）——它决定第 6/7 项可不可信；欠款最多的挂账单位 `arrears_units[0]`；超限客户数 `totals.over_limit_count`（`schemas/reports.py:354`）；准时率 `on_time_rate`（`stats_service.py:275`，无样本必须是 `None` 而不是 0）。

---

## 14. 未在代码中找到 / 边界与坑（诚实清单）

1. **「每天必看 / 仪表盘」没有任何后端定义** —— §12 与 §13 是归纳，不是既有字段。
2. `/reports/arrears-summary` **没有 `response_model`**（`reports.py:176-186`），出参形状只在 `arrears_query.py:67` 的字典里；改它不会有 schema 层报错。
3. `/reports/export` 的 `date_from/date_to` 注释写着「finance/customers 可用」（L220），但 `_span` 对**所有** kind 都生效（L242）——以代码为准。
4. `services/sheet_text.py:5` 与 `ledger_export.py:72` 说的「七个 kind」是旧文案，现值 11 个（`reports.py:217`）。
5. **`GET /expenses` 没有 `vehicle_id` 参数**（`expenses.py:24-27` 只有 category/driver_id/date_from/date_to）→ 车辆成本表的「这台车的开销」在明细侧**无法按车过滤**（只能按分类/司机/日期捞）。
6. `/reports/*` 与 `/stats/*` 用的是**两个不同权限点**（`ORDER_DISPATCH` vs `STATS_READ`），虽然当前都是「只有派单员」；未来若拆分只读角色，这两族会**分别**变化。
7. 权限矩阵里 `STATS_READ` 的 Scope 写的是 `all`（`rbac.py:165`），即没有「只看自己那份」的版本——货主端的任何「经营数据」需求都不能靠这两个点满足。
8. 报表层是**只读**，由 `_tools/qa/_check_report_boundary.py` 在 AST 层禁写；文件清单**自己算**（声明的文件 + `services/reports/**` 全部 .py，`_check_report_boundary.py:20,46-50,92-94`）。
9. 钱的求和**不许在别处重写**：禁改名单含 `api/v1/reports.py`、`services/reports/{turnover,product,arrears}_query.py`（`services/money_contract.py:74-78,110`，判据 `_tools/qa/_check_money_contract.py`）。
10. `services/reports_service.py` 是**纯 re-export 壳**（34 行，docstring L1-7：「本文件里一行实现都没有」），别在它里面找口径。
11. 车辆成本表的「未覆盖」三原因顺序固定（`vehicle_depreciation.py:56-58`），利润表的 `depreciation_uncovered[].reasons` 也按这个顺序（`schemas/reports.py:104-110`）——界面不要自己排。
