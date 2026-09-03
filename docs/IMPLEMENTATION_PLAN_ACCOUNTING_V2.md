# 账本 V2 改造实施方案（P0 第一交付批 · 待用户批准后开工）

> 依据：docs/ACCOUNTING_V2_DESIGN.md（REV5 定稿，第 5 轮只读审查通过）。
> 范围：**P0 数据补齐 + 司机货损录入 + 车辆台账 + 客户收款（逐单）**。
> 前置：git 基线已提交（commit 6e3a594，146 文件），本方案所有改动均可从此基线回滚。
> 原则：只做「增删改查」，**不触碰既有业务逻辑**（明确清单见 §0.2）。

---

## 0. 总则

### 0.1 设计风格约定（沿用现有）
- 语义色（Modules.kt 14 色互异体系）、SegmentedStatusTabs 独立块导航、圆角卡片+灰字次要信息、金额固定两位小数右对齐（formatMoney）、TintedIcon 25dp 语义色图标、ListTile 式行组件。
- 后端：FastAPI 路由风格（router.py 挂载）、schemas pydantic、services 层、operation_logs 审计、BackgroundTasks 异步（导出）。

### 0.2 不碰清单（改造红线 — 触碰即违规）
| 逻辑 | 原因 |
|---|---|
| 派单流程（DispatcherPoolViewModel/pool 接口/派单弹窗/batchAssign） | 只在其派单弹窗**加一个可选项**（如需），不改派单核心状态 |
| 订单状态机（PENDING→ACCEPTED→DELIVERED→CANCELLED 流转/order_flow.py） | 仅送达分支加账务钩子（挂钩子≠改流程） |
| 地址与联系人（Address/Contacts/Locations 三表+UI） | 与账本无关 |
| 消息中心（notifications/push_events） | 只复用（仿 ledger 导出推送），不改现有推送链路 |
| 库存流水（inventory_movements 及 UI） | 商品成本价读 products.cost_price，不改库存 |
| 司机绩效统计（stats_service.driver_performance） | 金额结算走新表，不动时效统计 |
| 既有货主账本页/导出 task（ledger.py 现有接口） | 保持兼容（§10.5 约定），不删不改旧接口 |

---

## 1. 后端改造点（P0）

### 1.1 新表（models + schema_bootstrap 自动建表）
| 表 | 文件 | 要点 |
|---|---|---|
| customers | models/customer.py | kind/user_id/name/phone(部分唯一)/is_member/arrears_unit_id；uq_customers_tmp_phone WHERE kind='tmp' AND phone IS NOT NULL；uq_customers_registered WHERE kind='registered' |
| driver_bills | models/driver_bill.py | 见 REV5 §4.3；month 必填；status OPEN/SETTLED/CANCELLED |
| cash_flows | models/cash_flow.py | 见 §4.4；direction IN/OUT + party_type + channel + biz_type 枚举 |
| shipper_receipts | models/shipper_receipt.py | 见 §4.5；order_ids JSON 必填（itemized 默认） |
| driver_settlements | models/driver_settlement.py | 见 §4.6；DRAFT→CONFIRMED→PAID→CANCELLED |
| expenses | models/expense.py | 见 §4.7；无 invoice_id（P3 再加） |
| vehicles | models/vehicle.py | 见 §4.8（D6 已拍板） |

### 1.2 既有表加列（schema_bootstrap.py 手写 ALTER 块 + Base.metadata 模型同步）
1. order_products: cost_price_snapshot NUMERIC(14,4) DEFAULT 0；**damage_quantity INTEGER DEFAULT 0**（CHECK>=0 实现期由服务层强校验 ≤quantity）
2. ledgers: cost_price_snapshot NUMERIC(14,4)；customer_id INTEGER
3. orders: damage_note TEXT（司机完成时可选填）
4. ledger_export_jobs: kind VARCHAR(16) DEFAULT 'ledger'（P2 导入泛化，本批先加列）
- 注：**不新增 orders.customer_delivery_fee**（D1 已定含配送费）。

### 1.3 新接口（新文件挂 router.py）
| 接口 | 文件 | 说明 |
|---|---|---|
| POST/GET /customers、POST /customers/merge(占位P1) | api/v1/customers.py | 客户档案（散客按名+电话匹配，registered 懒创建） |
| GET /driver-bills、POST /driver-bills/generate | api/v1/driver_bills.py | 应付明细；generate 幂等（SALARY 月薪单/PIECE 补单） |
| POST/GET /driver-settlements、PATCH /driver-settlements/{id} | api/v1/driver_settlements.py | 结算单状态机，事务+原子 WHERE status='OPEN' |
| POST/GET /expenses | api/v1/expenses.py | 开销单（自动生成 cash_flows） |
| GET /cash-flows | api/v1/cash_flows.py | 资金流水查询 |
| POST/GET /ledger/receipts | 扩展 ledger.py | 收款单+逐单核销（标记 orders.paid=1） |
| GET /reports/pnl（P1 本批先出接口骨架? 否——P1 下一批） | — | 本批不做，留 P1 |

### 1.4 既有接口扩展（只加参数不改逻辑）
| 接口 | 改动 |
|---|---|
| orders.py complete / complete-with-upload | OrderCompleteBody 增加 damage_items: [{order_product_id, quantity}] + damage_note；送达钩子里：damage_qty>0 → ①expenses LOSS（cost×qty, driver/order 关联）②ledgers 专用红冲行（amount=0, cost_price_snapshot=-cost×qty）③写 orders.damage_note/order_products.damage_quantity。**订单状态流转代码不动，仅在其后追加账务钩子函数** |
| orders.py 派单（assign/batch-assign） | **不动**（collect_cash 已有；无新派单参数） |
| ledger.py /accounts | 只加 customer_id 关联（聚合键优先 customers.id，NULL 兜底名称）——旧返回兼容 |

### 1.5 服务层
- services/ledger_sync.py：送达同步时写 cost_price_snapshot（order_products/ledgers）+ 生成 driver_bills（PIECE）。
- services/accounting_service.py（新）：统一钩子——送达→两支明细；收款→逐单核销+paid；结算单确认/付款；货损→LOSS+红冲行。**所有账务写入集中此文件**（单源事实）。
- services/expense_flow.py（新）：expenses 保存→cash_flows 联动。

### 1.6 回填脚本
- scripts/backfill_cost_snapshots.py：跑一次，order_products/ledgers 按 products.cost_price 回填（仅 product_id 存在的行；无 product_id 标 0+提示）。

---

## 2. Android 改造点（P0）

### 2.1 司机端：完成订单弹层加「货损（选填）」区
- OrderDetailScreen.kt：DeliverySheet 与直接完成块**下方新增**「货损（选填）」区块——列出本单商品行（名称+数量），每行一个数量输入框（Int，默认 0，≤quantity）+ 订单备注输入框。
- OrderDetailViewModel.kt：damageItems 状态（Map<orderProductId,Int>）+ damageNote；completeDelivery/completeDirect 传 damage_items/damage_note。
- Dtos.kt/Apis.kt/repo：OrderCompleteBody 加字段；completeOrderWithUpload(@Part damage_items JSON + damage_note)。
- 样式：沿用现有弹层卡片+OutlinedTextField+语义色（货损=FF6B2C 橙红/警示）；仅「可选项」，不填=现有行为完全不变。

### 2.2 派单员端：账本管理模块加功能入口（新增）
- DispatcherLedgerScreen.kt 加 4 个子入口（顶部按钮行或新页签，按现有 LedgerTabBar 风格）：
  1. **客户收款**（新增按钮）：收款单页（select 客户（含散客名+电话）/金额/方式 cash|transfer|wechat|arrears_settle/关联订单逐单勾选/日期）→ POST /ledger/receipts。列表：收款记录（按客户/日期）。
  2. **司机结算**（新增按钮）：结算单页（选司机/月/类型 PIECE|SALARY→显示当月 OPEN bill 摘要/金额/confirm/pay 两步按钮）。
  3. **开销管理**（新增按钮）：开销表单（分类 FUEL|REPAIR|TOLL|PARKING|FINE|INSURANCE|LOSS|OTHER 下拉/金额/日期/司机/车辆/订单/备注）+ 列表（分类汇总）。
  4. **车辆台账**（新增按钮）：车辆列表（车牌/车型/挂靠司机/状态）+ 新增/编辑表单。
- 这些入口放「账本管理」首页——保持现有四账页签不动，新增入口行（不放页签内，避免改坏）。

### 2.3 派单员端：商品管理（不动成本价，仅加校验提示）
- ProductsScreen.kt：**不加改动**（成本价已有）；仅提示文案已有「用于报表毛利率」。

### 2.4 新模块路由
- NavGraph.kt：新增 composable（CUSTOMER_RECEIPTS / DRIVER_SETTLEMENTS / EXPENSES / VEHICLES），从账本管理入口导航，返回栈正常。

### 2.5 不碰的 Android 逻辑
- DispatcherPoolViewModel/派单流程、订单状态 tab、地址三列表、消息中心、库存页、司机任务页（除完成弹层加区）、我的账本（司机端模板页——P0 不动，P1 再展示未结）。

---

## 3. 数据与验证

### 3.1 迁移顺序（后端重启一次完成）
1. schema_bootstrap ALTER 块（4 张既有表加列）→ Base.metadata.create_all（7 张新表）；
2. 跑 backfill 脚本（成本快照+散客 customers 迁移：按 temp_shipper_name 归并+电话尽力提取）；
3. 重启 uvicorn（无 --reload，必须重启）。

### 3.2 验证路径（5554 派单员 / 5558 司机）
- [ ] 5558 订单完成弹层可见「货损（选填）」区 → 填 1 件货损 → 送达成功；
- [ ] 5554 账本管理→开销管理：出现该货损 EXPENSE_LOSS（金额=成本×数量，挂司机/订单）；
- [ ] 5554 账本管理→客户收款：对散客（名+电话）新建收款单→逐单勾选→保存 → 订单 paid=1、客户欠款减少；
- [ ] 5554 账本管理→司机结算：9 月 PIECE 结算单（草稿→确认→付款）→ driver_bills 变 SETTLED、cash_flows 有 PAYMENT_DRIVER；
- [ ] 5554 车辆台账：新增车牌+挂靠司机；
- [ ] 回归：派单→接单→送达（不填货损）全流程与改前行为一致；账本四账页签正常。

### 3.3 回滚
- 任何一步出问题：git revert 6e3a594..HEAD 或 reset --hard 6e3a594（后端重启即可，新增列/表无数据依赖回滚风险低；SQLite 加列回滚=删列脚本，本批不提供，建议以 baseline 恢复库文件备份：backend/sorders.db 先复制一份）。

---

## 4. 交付批次拆分（本批=P0；P1/P2/P3 下一批）

| 批 | 内容 | 验收 |
|---|---|---|
| **本批 P0** | §1+§2 全部（表/接口/钩子/回填/Android 4 入口+货损区） | §3.2 验证清单全绿 + 回归通过 |
| P1 | 报表（pnl/customer-balances/driver-cost/gross-margin）+ 客户合并 + 报表中心「经营利润」入口 + RECEIPT_PREPAID/ADVANCE | 老板 3 问可答 |
| P2 | 导出泛化 + freight-settlement 下线切换 | 报税对账可导出 |
| P3 | invoices 税账（税率档启用时定） | 税汇 |

---

## 5. 风险注记
1. complete-with-upload 是 multipart：damage_items 需转 JSON 字符串 Part。
2. SQLite 部分唯一索引（WHERE phone IS NOT NULL）OK；MySQL 生产同样支持。
3. 服务层强校验：damage_qty>0 时必须 cost_price_snapshot>0（=0 提示：货损金额为 0，是否确认）；damage_qty≤quantity 硬拦。
4. 司机完成弹层现有「拍照送达」与「直接完成」两入口都要加货损区，勿遗漏其一。
5. driver_bills 生成：送达钩子幂等（order_id+bill_type 唯一复用），防止补单重复。
