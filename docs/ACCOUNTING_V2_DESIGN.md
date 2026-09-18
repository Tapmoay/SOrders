# 公司级账本方案 V2（探讨稿 · REV5 定稿）

> ## ⚠️ 状态更新（2026-09-14 核实）：本方案**已经实现**，本文只剩历史价值
>
> 原标题与状态行写的是"**未实现**""**零代码改动**"——**这两个说法现在都是错的**。
> 核实结果（按 P0 交付项逐项对代码）：
>
> | P0 项 | 落点 |
> |---|---|
> | 资金流水 | `backend/app/models/cash_flow.py`、`backend/app/api/v1/cash_flows.py` |
> | 开销 | `backend/app/models/expense.py`、`backend/app/api/v1/expenses.py` |
> | 司机账单 / 结算 | `backend/app/models/driver_bill.py`、`driver_settlement.py`、`backend/app/api/v1/driver_bills.py`、`driver_settlements.py` |
> | 客户收款 | `backend/app/models/shipper_receipt.py` |
> | 车辆台账 | `backend/app/models/vehicle.py`、`backend/app/api/v1/vehicles.py` |
> | 核心实现 | `backend/app/services/accounting_service.py`（413 行，"唯一写入点"）、`backend/app/schemas/accounting_v2.py`（215 行） |
>
> **要了解账本现状，请看 [PROJECT_MAP/08_CODE_LOCATOR.md](PROJECT_MAP/08_CODE_LOCATOR.md) 与 [PROJECT_MAP/03_BACKEND_DETAILS.md](PROJECT_MAP/03_BACKEND_DETAILS.md)，不要读本文。**
> 本文保留下来只为一件事：**当时的取舍理由**（D1-D8 决策、为什么这么分表）——那是代码里读不出来的信息。
>
> ⚠️ 教训：**"未实现"这类状态断言最容易腐烂**——写的时候是真的，实现之后就变成假的，
> 而没有任何机制会提醒你。凡在文档里写"尚未/暂不/待定/未实现"，都要注明**截止日期 + 如何核实**。

> 目标：让公司老板在系统里能算清「这个月赚了多少、谁欠我钱、司机成本多少、一天/一月营业额多少」，且所有数字可溯源到订单/司机/开销；并为报税、对账、报表导出预留能力。
> 状态（**原始记录，已过期，见上方状态更新**）：设计探讨稿，仅本文件，零代码改动。数据现状为 SQLite 开发库审计结果（2026-09-03）。
> REV5：老板已拍板 D1-D8（§9 全部落定）+ 新增「司机完成订单可选录入货损」（§4.12），为提交实现的定稿版本。前四轮只读审查（P0×4→P0×1→P1×2→通过）结论沿用。

---

## 0. 业务背景（老板口述，2026-09-03；决策已拍板）

- 公司 = 商品批发商，客户分两类：**代理商**（注册用户 `is_member=1`）与**散客**（无账号，下单留临时名称/电话）。
- 客户结款方式：现场结账 / 挂账（**散客也可挂账**，需电话档案；长期合作客户周期性结款）。
- 客户付款（D1 已拍板）：**货款金额内含配送费**（不另收配送费，无需拆分配送费字段）。
- 公司自有司机分两类：
  - **派送司机**（把货送出去）—— 固定工资，按月结算（`users.billing_mode=SALARY`，月薪 `users.salary`）。
  - **挂车司机**（把货拉进来）—— 按单计费，一单一口价（`billing_mode=PIECE`，`orders.freight_fee`）。
  - **司机结算（D3 已拍板）**：**统一按月结算**——固定工资按当月应发、挂车按当月送达单运费合计，各出一张月结算单。
- 货损（D7 已拍板）：**公司自担**（货损=公司损失，记货损开销；客户照常全额付款），**司机端完成订单时可选录入货损数量**，系统自动记账。
- 老板要的核心问题：
  1. 我这个月大概赚了多少钱？（营业额 − 成本 = 利润）
  2. 谁欠我多少钱？（每客户应收余额 + 账龄；**逐单核销**）
  3. 司机成本多少？——挂车按单合计、固定工资合计，以及**加油费/维修费等其他开销**。
  4. 一天/一月营业额多少？
  5. 一切数字可溯源到订单/客户/司机。

---

## 1. 现状审计结论（数据层面）

### 1.1 已有能力（无需重建）

| 能力 | 位置 | 说明 |
|---|---|---|
| 商品成本价 | `products.cost_price` NUMERIC(14,4)，Android 商品管理已有录入（选填，留空按 0） | 注释用途=毛利率 |
| 固定工资档案 | `users.salary`，司机管理已有录入/展示 | 仅档案值 |
| 挂车按单价 | `orders.freight_fee` + `billing_mode` | 已有 |
| 营业额报表 | `GET /reports/turnover`（日/周/月：金额/单数/运费+小时序列） | 已有（按 delivered_at 口径） |
| 货主账本 | `ledgers`（商品行应收明细，source=ORDER/MANUAL）+ `GET /ledger/accounts`（按客户聚合） | 已有 |
| 货主账本导出 | `ledger_export_jobs`（async excel/pdf + 通知下载） | 已有，仅货主侧 |
| 司机绩效 | `GET /stats/driver-performance` | 已有（时效维度，非金额结算） |
| 挂账单位 | `arrears_units`（目录表，无发生额） | 已有目录 |
| 库存/价格 | `products.stock`、`price_rules`（批发商专属价） | 已有 |

### 1.2 缺口（按严重度）

| # | 缺口 | 影响 |
|---|---|---|
| G1 | **商品成本无快照**：`order_products`/`ledgers` 没有 `cost_price` 快照列；商品成本一改，历史订单成本追溯失真 | 毛利率/利润不可信 |
| G2 | **无实收流水**：货主付了钱没记录（`orders.paid` 形同虚设，24 单仅 1 单 true）；挂账无发生额/结清/账龄 | 「谁欠我钱」算不出，无法催收对账 |
| G3 | **无司机结算单**：挂车运费只有「应结」聚合，无「已结/未结/何时发」；固定工资无「某月应发/实发」 | 司机成本只是理论值，不是资金事实 |
| G4 | **无开销管理**：加油费/维修费/过路费等无表无 UI | 总成本缺一大块，利润错误 |
| G5 | **无利润报表**：营业额、商品成本、司机成本、开销不汇合 | 老板的 3 问一答不出来 |
| G6 | **无公司级导出**：导出只有货主账本；报表/司机账/开销无导出 | 报税、对账、外部核对不可行 |
| G7 | **无税账**：发票/税率/税额全零（需求文档也未提起） | 报税需手工另算 |
| G8 | **口径说明不足**：`/reports/turnover` 按 `delivered_at` 且 freight_fee 单列（不进营业额金额）；ORDER 账本行 `entry_date` 实等于 `delivered_at.date()`（一致），仅 **MANUAL 手记行 `entry_date` 为自填**可能不一致。D1 已定：货款含配送费，无独立配送费口径 | 同一天的不同来源数字可能对不上（口径无文档可依） |
| G9 | **散客无唯一键**：散客只以 `temp_shipper_name` 文本分组（现状库订单层已有重名：'刷新' 出现 3 次；ledgers 层 2 次），无法安全挂收款/发票/信用 | 散客账串户，收款/欠款不可信 |
| G10 | **账务操作无审计**：`operation_logs` 覆盖订单，但手记账/删账/改账未必留痕 | 对账时无法回答「这笔账谁改的」 |
| G11 | **异常单/货损/退货只冲司机不冲客户**：送达即入 `ledgers`，`is_exception` 单照记应收；driver_bills 有作废规则，客户侧无对应红冲 | 毛利/客户欠款失真 |
| G12 | **父子拆单无账务规则**：现库存在 `parent_order_id` 拆分订单（2 组，parent=11/18），拆单后应收/运费归属未定义 | 营业额/成本可能漏记或重复 |

---

## 2. 设计原则

1. **单源事实**：每笔钱的「发生」只有一个写入点，其他都是聚合；改动即留痕。
2. **双向明细账**：公司是坐标原点——对客户是应收，对司机是应付；订单送达同时生成两条腿。
3. **快照优先**：所有参与报表的金额（售价、成本）在发生时快照，防后续改价污染历史。
4. **口径单一**：经营报表统一按「送达时间 `delivered_at`」记账口径（资金/结算单按实际发生时间），两套时间分别展示、不混用。
5. **渐进可落地**：P0 数据补齐 → P1 报表 → P2 导出 → P3 税账，每阶段独立可用，不等待全量；**每个阶段内不引用未创建的表格**（P0 不得引用 P3 的表）。
6. **复用现状**：ledgers/订单/商品成本价/营业额报表基础不动，只做加列+新表+新接口，不做大迁移。

---

## 3. 账本模型（目标结构）

```
                    ┌──────────────────────── 报表层（纯聚合）────────────────────────┐
                    │ 经营利润 │ 客户欠款 │ 司机成本 │ 商品毛利 │ 开销汇总 │ 税汇    │
                    └───────────────▲─────────────────────────▲─────────────────────┘
                                    │                         │
   ┌──────────── 明细账（发生额）────────────┐   ┌───── 资金账（收付）─────┐
   │ ① ledgers   客户应收明细(商品行+成本快照) │   │ ③ cash_flows 资金流水    │
   │   含红冲行(负金额, source=REFUND/ADJUST) │   │   RECEIPT收款/PAYMENT付款 │
   │ ② driver_bills 司机应付明细(订单行)      │   │   EXPENSE开销/工资/退款   │
   │   （挂车按单+固定工资月薪统一表，按月结）  │   │   调账/预收/借支          │
   └────────────────┬──────────────────────┘   └──────────┬──────────────┘
                                    │                    │
         ┌──────────▼──────────┐            ┌────────────▼───────────┐
         │ 业务事实：orders/    │            │ 单据：shipper_receipts │
         │ order_products      │            │      driver_settlements│
         │ 送达→生成两支明细    │            │      expenses(含货损)   │
         │ 异常/拆单→联动红冲   │            └────────────────────────┘
         └─────────────────────┘
```

- **明细账（发生额，业务事实）**：订单送达即生成「客户应收（商品行×成本快照）」+「司机应付（每单 freight_fee 或分摊月薪）」——回答「该收/该付多少」。**客户侧冲销（退货/货损/异常让利）以负金额红冲行入 ledgers**（source=REFUND/ADJUST），不删原行、不改原行金额（可溯源）。
- **资金账（收付，资金事实）**：实际收款/付款/开销 → cash_flows，回答「实收/实付多少」。
- **单据（凭证）**：收款单、司机结算单、开销单（含货损单），账目可核销、可导出、可审计。
- **余额公式（统一定义，所有报表共用；全部显式限定 party_type）**：
  - 客户欠款 = Σ(ledgers 应收行, 含负向红冲) − Σ(cash_flows **IN**, `party_type='customer'`) + Σ(cash_flows **OUT**, `party_type='customer'` 且 `biz_type='REFUND_CUSTOMER'`)。验算：应收80 − 收款100 + 退款20 = 0 ✓
  - **司机未结（公司仍欠司机）= Σ(全部未作废 driver_bills，即 status∈{OPEN,SETTLED}) − Σ(cash_flows **OUT**, `party_type='driver'`) + Σ(cash_flows **IN**, `party_type='driver'` 且 `biz_type='REFUND_DRIVER'`)**，即「应付总额 − 已付总额 + 公司收回」（**不得用 Σ(OPEN)**——SETTLED 仅表示纳入结算单、≠已付款，PAID 才产生 OUT；用 Σ(OPEN) 与 −Σ(OUT) 会双重抵消）。
  - 「待结算」视图 = Σ(driver_bills status=OPEN)（仅用于生成结算单的候选清单，**不是**欠款余额）。
  - 渠道资金余额（P1 现金盘点/对账）= Σ(cash_flows IN) − Σ(cash_flows OUT)，按 `channel` 分组。
  - **客户侧冲销正交规则**：冲销由两类**正交**事件组成，**可同时发生、不互相排斥**（统一公式结构天然不双计）——
    ① **退/减应收**（退货、货损客户拒付、少收、坏账）：一律在 `ledgers` 记负向红冲行（售价口径，负成本快照按货物去向决定），**无论货款是否已收**；
    ② **现金退款**（退回已收货款、多收退回）：记 `REFUND_CUSTOMER` cash_flows（OUT），**不动 ledgers**。
    验算 A（全额退货 + 全额退现）：应收 80 − 红冲 80 = 0；已收 80、退现 80；欠款 = 0 − 80 + 80 = 0 ✓（货退钱退两清）。
    验算 B（商品保留、多收退回 20）：应收 80 − 红冲 0 = 80；已收 100、退现 20；欠款 = 80 − 100 + 20 = 0 ✓。
    销售红冲两种形态（区分「货物去向」）：
      - **货退回/拒收**：红冲售价 + 负成本快照（COGS 同步冲回，货物回流库存/盘亏）；
      - **货保留但少收/坏账/让利**：红冲售价（减应收/营收），**保留 COGS**（货已被客户拿走，成本照记）；
      两者都只走 ledgers 红冲（与现金退款正交），区别仅在于红冲行是否带负成本快照。

---

## 4. 数据模型设计（DDL 草案）

### 4.1 快照补列（ALTER，2 表 × 1 列 = 2 条）

```sql
-- 商品成本快照（毛利按「当时成本」算；cost_total = cost_price_snapshot × quantity 现算，不冗余存储）
ALTER TABLE order_products ADD COLUMN cost_price_snapshot NUMERIC(14,4) DEFAULT 0;
ALTER TABLE ledgers ADD COLUMN cost_price_snapshot NUMERIC(14,4) DEFAULT 0;
-- 下单/送达同步时从 products.cost_price 写入（product_id 存在时）；存量回填脚本只处理有 product_id 且商品仍存在的行，
-- 无 product_id 或商品已删的行保持 0 并标注「历史成本缺失」。
```

### 4.2 新表：customers（客户主数据，解决 G9 散客唯一键）

```sql
CREATE TABLE customers (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  kind          VARCHAR(12) NOT NULL DEFAULT 'tmp',
                -- 'registered' 注册用户(货主/代理商) | 'tmp' 散客
  user_id       INTEGER,                    -- registered → users.id（不复制用户数据）
  name          VARCHAR(128) NOT NULL,
  phone         VARCHAR(32),                -- tmp 时尽量填（散客唯一键=电话；散客可挂账的前提），可为空
  is_member     BOOLEAN DEFAULT 0,          -- 冗余 users.is_member 便于聚合
  arrears_unit_id INTEGER,                  -- 可选：挂账单位（信用分组）
  created_at    DATETIME, updated_at DATETIME
);
CREATE UNIQUE INDEX uq_customers_tmp_phone ON customers(phone) WHERE kind='tmp' AND phone IS NOT NULL;  -- 空电话不参与唯一
CREATE UNIQUE INDEX uq_customers_registered ON customers(user_id) WHERE kind='registered';             -- 注册用户唯一
-- 规则：
--   registered：users 创建时同步建档案（或在首个订单/收款时懒创建）；user_id 唯一。
--   tmp：收款/下单时按「名称+电话」匹配，不存在则创建；电话为空时仍可建档，但**不可挂账**（只能现金即时结），
--        收款/欠款界面按「名称」人工选择确认（防串户）。
-- 历史迁移（ledgers 无 phone 列，无法按电话归并）：
--   ① registered：ledgers.shipper_id 直接关联 users，同步建档案；
--   ② tmp：按 temp_shipper_name 归并创建，phone 从 orders.contact_boss_phone（优先，散客多留老板电话）→
--      orders.contact_dongjia_phone 尽力提取，提取不到=空；
--   ③ 无电话 tmp 客户：收款/欠款界面人工选择确认；重名者 P1 提供「客户合并」接口人工去重（operation_logs 留痕）；
--   ④ tmp → registered 升级（散客注册成用户）：更新 user_id + kind='registered'，id 不变，历史流水继续挂靠，不迁移。
--   ⑤ ledgers.customer_id 由迁移脚本写入；无法确定的可保持 NULL（欠款视图按名称兜底聚合，P1 合并后重挂）。
```

### 4.3 新表：driver_bills（司机应付明细，挂车+固定工资统一，按月结算）

```sql
CREATE TABLE driver_bills (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  driver_id     INTEGER NOT NULL,           -- users.id (role=DRIVER)
  bill_type     VARCHAR(8) NOT NULL,        -- 'PIECE' 按单计费 | 'SALARY' 按月薪
  order_id      INTEGER,                    -- PIECE 时必填，SALARY 可为空（月薪单）
  month         VARCHAR(7) NOT NULL,        -- 'YYYY-MM' 归属月（D3：统计/结算统一按月）
  amount        NUMERIC(12,2) NOT NULL,     -- PIECE=freight_fee 快照；SALARY=当月应发工资
  status        VARCHAR(12) NOT NULL DEFAULT 'OPEN',
                -- OPEN 待结 | SETTLED 已结（结算单 CONFIRMED 时锁定） | CANCELLED 作废
  settled_doc_id INTEGER,                   -- 关联 driver_settlements.id（CONFIRMED 时写）
  note          TEXT,
  created_at    DATETIME, updated_at DATETIME
);
-- 生成规则（服务层，唯一写入点，全部幂等）：
--   ① 订单送达且 driver_billing_mode_snapshot='PIECE' 且 freight_fee 非空 → 生成/复用 PIECE 单（month=送达月）；
--   ② 每月 1 日(或手工触发)对每个薪资司机(SALARY)生成当月 SALARY 单(amount=users.salary, month=当月)；
--   ③ 订单撤销/CANCELLED（送达前）→ 对应 PIECE 单 status=CANCELLED；
--   ④ SALARY 司机若存在 freight_fee 脏数据(现开发库 1 单) → 生成规则按 billing_mode 严格区分：
--      SALARY 绝不生成 PIECE 单；脏单不进 driver_bills（旧接口展示不受影响，见 §10.5）。
--   ⑤ 送达后异常单：司机侧已生成的运费单不自动作废（运费按公司决议处理，追回/减免走 ADJUST）。
-- 归属：PIECE 按 order.delivered_at 月；SALARY 按 month（PnL 规则见 §6）。
```

### 4.4 新表：cash_flows（资金流水总账）

```sql
CREATE TABLE cash_flows (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  flow_date     DATE NOT NULL,              -- 实际发生日（收款/付款/开销日）
  direction     VARCHAR(3) NOT NULL,        -- 'IN' 收进 | 'OUT' 付出
  amount        NUMERIC(12,2) NOT NULL,
  party_type    VARCHAR(8) NOT NULL,        -- 'customer' | 'driver' | 'supplier' | 'expense' | 'other'
  party_id      INTEGER,                    -- 客户= customers.id / 司机= users.id / 开销单= expenses.id
  party_name    VARCHAR(128),               -- 冗余名称（散客名可空）
  channel       VARCHAR(16) NOT NULL DEFAULT 'cash',
                -- cash 现金 | wechat 微信 | alipay 支付宝 | bank 银行 | arrears 挂账核销（P1 现金盘点/对账用）
  biz_type      VARCHAR(20) NOT NULL,       -- 见枚举表
  order_id      INTEGER,                    -- 可溯源到订单
  doc_id        INTEGER,                    -- 关联单据 id（收款单/结算单/开销单/发票）
  note          TEXT,
  operator_id   INTEGER,                    -- 经办人（审计）
  created_at    DATETIME, updated_at DATETIME
);
-- biz_type 枚举：
--   RECEIPT_CASH / RECEIPT_TRANSFER / RECEIPT_ARREARS  客户收款（IN）
--   RECEIPT_PREPAID  客户预收/超收（IN；余额可为负=预收，P1）
--   PAYMENT_DRIVER   司机运费结算付款（OUT，按月）
--   PAYMENT_SALARY   固定工资发放（OUT，按月）
--   PAYMENT_DRIVER_ADVANCE 司机借支/预支（OUT；结算可抵扣，P1）
--   PAYMENT_SUPPLIER 供应商进货付款（OUT；P1，供应商=商品进货往来）
--   PAYMENT_TAX      税缴纳（OUT；P3）
--   EXPENSE_FUEL / EXPENSE_REPAIR / EXPENSE_TOLL / EXPENSE_PARKING / EXPENSE_FINE /
--   EXPENSE_INSURANCE / EXPENSE_LOSS 货损赔偿 / EXPENSE_OTHER  开销（OUT）
--   REFUND_CUSTOMER  客户现金退款（退已收货款，OUT；= 负向实收，余额公式显式计入；与 ledgers 红冲正交，见 §3）
--   REFUND_DRIVER    公司向司机收回多付款（IN，party_type=driver；= 负向实付）
--   ADJUST           手工调账（IN/OUT 均可，必须挂经办+备注，无单据不入账）
```

### 4.5 新表：shipper_receipts（客户收款单，凭证，逐单核销）

```sql
CREATE TABLE shipper_receipts (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id   INTEGER NOT NULL,           -- → customers.id（所有收款必须有客户档案，含散客）
  amount        NUMERIC(12,2) NOT NULL,
  method        VARCHAR(16) NOT NULL,       -- cash | transfer | wechat | arrears_settle
  received_at   DATE NOT NULL,
  order_ids     TEXT NOT NULL,              -- JSON 数组：**逐单核销（D2 已拍板）**，绑定具体订单，必填
  settle_mode   VARCHAR(12) NOT NULL DEFAULT 'itemized',
                -- 'itemized' 逐单核销（默认，老板拍板） | 'rolling' 滚动余额（保留为可选场景，非默认）
  arrears_unit_id INTEGER,                  -- 可选：核销时所属挂账单位（对账/账龄按收款单口径）
  invoiced      BOOLEAN DEFAULT 0,          -- 是否已开票（衔接税账）
  note          TEXT, operator_id INTEGER,
  created_at    DATETIME, updated_at DATETIME
);
-- 核销规则（itemized）：收款单绑定订单列表 → 逐单生成 RECEIPT 流水 + 标记 orders.paid=1；
--   全部绑定订单「应收合计 ≤ amount」校验；差额=超收 → 自动生成 RECEIPT_PREPAID 或要求拆分（P1 支持）。
-- rolling（可选）：冲抵该客户应收余额（欠款表=余额+账龄，不逐单）。
```

### 4.6 新表：driver_settlements（司机结算单，凭证，按月）

```sql
CREATE TABLE driver_settlements (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  driver_id     INTEGER NOT NULL,
  settle_type   VARCHAR(8) NOT NULL,        -- 'PIECE' 运费结算 | 'SALARY' 工资发放
  month         VARCHAR(7) NOT NULL,        -- 结算月（D3：统一按月结）
  period_from   DATE, period_to DATE,       -- 冗余保存该月范围（可查）
  amount        NUMERIC(12,2) NOT NULL,     -- 创建时=Σ 该月 driver_bills(OPEN)；确认前可手工改
  status        VARCHAR(12) NOT NULL DEFAULT 'DRAFT',
                -- DRAFT 草稿（可改/可弃）→ CONFIRMED 确认（锁定 bills=SETTLED）→ PAID 已付款（生成 PAYMENT 流水）→ CANCELLED
  order_ids     TEXT,                       -- JSON：被结算的 driver_bills.order_id 列表（溯源）
  paid_at       DATETIME, method VARCHAR(16), operator_id INTEGER,
  note          TEXT,
  created_at    DATETIME, updated_at DATETIME
);
-- 状态机动作（每步写 operation_logs）：
--   CREATE → DRAFT：不动 driver_bills；
--   CONFIRM → 事务内 UPDATE driver_bills SET status='SETTLED', settled_doc_id=… WHERE id IN (…) AND status='OPEN'
--              （原子判定；失败=该单已被其他结算单占用，禁止重复结算）；校验 amount == Σ(所辖 bills)（人工微调输出差异注记）；
--   PAY → 生成 PAYMENT_DRIVER/PAYMENT_SALARY 流水（cash_flows，按 channel/method），写 paid_at；校验已付累计不超 amount；
--   CANCEL（仅 CONFIRMED 之前）→ 还原 driver_bills=OPEN；PAID 后取消=反向 ADJUST 留痕（不做物理删除）。
```

### 4.7 新表：expenses（开销单，凭证）

```sql
CREATE TABLE expenses (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  exp_date      DATE NOT NULL,
  category      VARCHAR(16) NOT NULL,       -- FUEL 加油 | REPAIR 维修 | TOLL 过路 | PARKING 停车 | FINE 罚款 |
                                            -- INSURANCE 保险 | LOSS 货损赔偿 | OTHER
  amount        NUMERIC(12,2) NOT NULL,
  driver_id     INTEGER,                    -- 可选：挂到司机（货损自动挂送达司机）
  vehicle_id    INTEGER,                    -- 可选：挂到车辆（P0 建车辆表后启用，见 §4.8）
  order_id      INTEGER,                    -- 可选：挂到订单（该单产生的过路费/货损）
  note          TEXT, operator_id INTEGER,
  created_at    DATETIME, updated_at DATETIME
  -- 注意：无 invoice_id 列（P3 建 invoices 时 ALTER 增加），P0 不引用未创建表。
);
-- 保存后自动生成 cash_flows：EXPENSE_*（OUT）。
-- LOSS 口径（公司自担，D7 已拍板）：
--   **货损（客户照常全额付款）→ 记 EXPENSE_LOSS（金额=成本价×货损数量），同时用专用红冲行（amount=0、负成本快照）
--   从 COGS 冲回等量成本**——净额=全额成本（COGS−冲回+LOSS），不双计且报表可单独看到「货损 XX」；
--   **客户拒付/少收/退货（含货损客户不赔）→ 走 ledgers 红冲：售价红冲（营收减）+ 负成本快照（COGS 同步冲减），不记 EXPENSE_LOSS**；
--   两条按「客户是否全额付款」二选一执行（同一批货损不得两条都记）。
-- 溯源：任何一笔开销可点开看「谁经手、哪辆车、哪张单」；进项发票 P3 关联。
```

### 4.8 新表：vehicles（车辆台账，D6 已拍板：建）

```sql
CREATE TABLE vehicles (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  plate_no      VARCHAR(16) NOT NULL,       -- 车牌
  vehicle_type  VARCHAR(16),                -- trailer 挂车 / small 小货车…
  driver_id     INTEGER,                    -- 挂靠司机
  is_active     BOOLEAN DEFAULT 1,
  created_at    DATETIME, updated_at DATETIME
);
-- 用途：挂车按车记钱的口径、油费维修按车归属、「单司机总成本=按单运费+其车开销」被支撑；P0 建表。
```

### 4.9 新表：invoices（发票登记，P3 建表启用；D5 税率暂定，启用时定档）

```sql
-- P3 阶段创建（P0-P2 不建此表）。
CREATE TABLE invoices (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  direction     VARCHAR(5) NOT NULL,        -- 'OUT' 销项（开给客户）| 'IN' 进项（供应商/加油维修）
  party_type    VARCHAR(8),                 -- 销项=customer；进项=supplier/expense
  party_id      INTEGER, party_name VARCHAR(128),
  invoice_no    VARCHAR(64),
  invoice_date  DATE,
  amount        NUMERIC(12,2) NOT NULL,     -- 价税合计
  tax_rate      NUMERIC(5,2),               -- 13/9/6/3/1/0；NULL=未税（不参与税汇）；多税率档可配（D5 暂定，启用时定）
  tax_amount    NUMERIC(12,2),              -- tax_rate 非空时 = amount − amount/(1+tax_rate)；tax_rate 为空时=NULL；允许手工覆盖
  order_id      INTEGER, receipt_id INTEGER, expense_id INTEGER,  -- 溯源关联（P3 给 expenses 补 invoice_id 列）
  status        VARCHAR(10) DEFAULT 'REGISTERED',
                -- REGISTERED 登记 | ISSUED 已开具 | VOIDED 作废/冲红（保留行占位）
  note TEXT, operator_id INTEGER,
  created_at    DATETIME, updated_at DATETIME
);
-- 未税/含税口径：建议在「商品级」定义（products 加 is_tax_inclusive/tax_rate，P3 决策），
-- 发票登记沿用商品口径，避免发票级每张手工选。小规模纳税人 3%/1% 通过税率档表达。
-- P3 报税汇总：某期间 Σ(销项 tax_amount) − Σ(进项 tax_amount)，按税率分组。
```

### 4.10 账务审计（G10）

- 所有写账接口（收款/结算/开销/手调/发票）写 `operation_logs`（已有表，action 新增 `ledger_receipt`/`ledger_settlement`/`ledger_expense`/`ledger_adjust` 等），记录操作前/后快照 + 经办人 + 时间。
- `ledgers` 手改/删除同样留痕；客户合并操作也留痕。

### 4.11 现有表微调

```sql
-- ledger_export_jobs 泛化导出（P2）：
ALTER TABLE ledger_export_jobs ADD COLUMN kind VARCHAR(16) DEFAULT 'ledger';  -- ledger/driver_bills/cash_flows/pnl/…
-- 注：shipper_id 改为可空（公司级导出无货主）；format VARCHAR(5) 扩为 VARCHAR(16)（csv/xlsx/pdf/ods）。
-- ledgers 挂客户档案（G9）：
ALTER TABLE ledgers ADD COLUMN customer_id INTEGER;  -- → customers.id；迁移见 §4.2；无法确定可保持 NULL（按名称兜底）
-- /ledger/accounts 迁移（P1）：聚合键从 temp_shipper_name 字符串切到 customers.id（customer_id 为 NULL 的历史行按名称归组并提示人工处理）。
-- 【D1 已拍板：货款含配送费，不新增 orders.customer_delivery_fee 列；若将来拆配送费再加。】
```

### 4.12 司机完成订单 · 货损录入（REV5 新增，D7 落地）

```sql
-- 商品行级货损数量（司机送达时可选填；成本=该行 cost_price_snapshot，精确记账）
ALTER TABLE order_products ADD COLUMN damage_quantity INTEGER DEFAULT 0;
-- 订单级货损说明（选填）
ALTER TABLE orders ADD COLUMN damage_note TEXT;
```
- **司机端（Android 完成订单弹层）**：「货损（选填）」区——列出本单商品行（名称/数量），每行可选填货损数量 + 订单级备注输入框；不填=无货损（现有流程不变）。
- **接口**：`OrderCompleteBody` / complete-with-upload 增加 `damage_items: [{order_product_id, quantity}]` + `damage_note: str|None`。
- **送达账务联动（D7 公司自担）**：对每个 `damage_quantity>0` 的订单商品行：
  ① 生成 `expenses`（category=LOSS，amount=cost_price_snapshot×damage_qty，driver_id=送达司机，order_id=本单）；
  ② 生成 `ledgers` 专用红冲行（amount=0、cost_price_snapshot=−cost×damage_qty）→ **COGS 冲回等量成本**；
  ③ 客户欠款/营业额**零影响**（客户照常全额付款）；利润净减少 = 货损成本。
  验算：单行销量 10×成本 8、货损 3 → COGS 80 冲回 24 + LOSS 24 = 净成本仍 80，利润 = 收入 − 80 −（其他）＝含货损成本 ✓。
- **限制**：damage_quantity ≤ 该行 quantity；送达后货损补录/纠错走异常处理（P1）。

---

## 5. 接口设计（草案）

| 接口 | 说明 |
|---|---|
| `POST /ledger/receipts` | 客户收款单（customers.id，**itemized 逐单核销默认**），生成 cash_flows+标记订单 paid=1 |
| `GET /ledger/receipts` | 收款记录列表（按客户/日期/方式） |
| `POST /customers` / `GET /customers` | 客户档案（散客按电话唯一；registered 懒创建） |
| `POST /customers/merge` | 客户合并/去重（P1，operation_logs 留痕） |
| `POST /driver-bills/generate` | 手工触发：SALARY 司机生成当月月薪单 / PIECE 补单（送达自动生成则幂等） |
| `GET /driver-bills` | 司机应付明细（按司机/类型/状态/月份） |
| `POST /driver-settlements` | 创建月结算单（DRAFT），CONFIRM/PAY/CANCEL 状态机 |
| `PATCH /driver-settlements/{id}` | confirm / pay / cancel（见 4.6 状态机） |
| `POST /expenses` / `GET /expenses` | 开销单增查（按分类/司机/日期）；货损由送达流程自动生成 |
| `GET /cash-flows` | 资金流水（按方向/类型/客户/司机/日期/channel），分页 |
| `GET /reports/pnl?from&to` | **经营利润**：营业额（含配送费货款）、商品成本、司机成本、开销（含货损）、经营利润、单数（核心） |
| `GET /reports/customer-balances` | 客户欠款：每客户应收余额（含预收为负）+ 账龄桶；支持 group_by=arrears_unit；逐单核销可展开订单明细 |
| `GET /reports/driver-cost` | 司机成本明细（每人：PIECE 合计/工资/车开销） |
| `GET /reports/gross-margin?from&to` | 商品毛利（Σ(售价−成本快照)×数量），按商品分组 |
| `GET /reports/tax-summary?from&to` | 税汇（P3）：销项/进项/税额按税率分组 |
| `GET /exports/{kind}?from&to` | 导出任务（泛化 ledger_export_jobs kind），复用异步+通知 |

---

## 6. 报表口径定义（统一口径，防 G8）

| 指标 | 定义 | 时点 |
|---|---|---|
| 营业额 | Σ 订单商品 `line_total`（货主应付货款；**D1 已定：含配送费**，不再单列）− Σ 客户红冲（ledgers 负行，售价口径） | 送达日 `delivered_at` |
| 商品成本(COGS) | Σ(`order_products.cost_price_snapshot` × quantity) + Σ(红冲行负成本快照)；公司自担货损时 COGS 先冲回等量成本、再以 EXPENSE_LOSS 单独记账（净额=全额成本，不双计，见 §4.7/§4.12） | 送达日 |
| 司机成本 | Σ `driver_bills`（PIECE 已结+未结均算发生额；SALARY 按归属月） | PIECE=送达日；SALARY=所属月 |
| 其他开销 | Σ `expenses`（含 LOSS 货损） | `exp_date` |
| **经营利润** | 营业额 − 商品成本 − 司机成本 − 其他开销 | 合计 |
| 商品毛利 | Σ(单价 − cost_price_snapshot) × 数量，按商品分组；毛利率 = 毛利/售价 | 送达日 |
| 客户欠款 | Σ(ledgers 应收行+负向红冲) − Σ(cash_flows IN, party_type=customer) + Σ(cash_flows OUT 且 biz_type=REFUND_CUSTOMER, party_type=customer)；<0=预收。**红冲与现金退款正交**（验算见 §3） | 即日（账龄锚点=应收行 entry_date） |
| 司机未结 | Σ(**全部未作废** driver_bills) − Σ(cash_flows OUT, party_type=driver) + Σ(cash_flows IN, party_type=driver 且 biz_type=REFUND_DRIVER)；待结算视图另用 Σ(OPEN) | 即日 |

**账龄定义**：桶 = 0-30 / 31-60 / 61-90 / >90 天；锚点 = 各应收行 `entry_date` → 今天；红冲行单独不计账龄（冲减发生额）。

**SALARY 月中归属**：PnL 查询 `from/to` 按「SALARY 单归属月整体落入期间（month ∈ [from月, to月]）」计入，不做日分摊；PIECE/商品成本按送达日落在区间内计入。报表中 SALARY 单独一行展示，避免与按日数据混淆。

> **挂账单位聚合**：客户欠款报表支持按 `arrears_unit_id` 分组视图（group_by 参数）。分组键口径：默认按 **customers.arrears_unit_id**（客户当前所属单位，跨期一致性好、支持重挂）；**shipper_receipts.arrears_unit_id** 是收款单核销时的单位快照（对账/账龄按收款单口径），两者用途不同，接口参数分别标注。
> **口径说明**：`/reports/turnover` 改叫「营业概览」，与 PnL 同口径（delivered_at）；ORDER 账本行 `entry_date` = `delivered_at.date()` 与报表一致，仅 MANUAL 手记行按自填日期（账本导出按 entry_date 不变，报表按 delivered_at，两者在文档中说明差异）。

---

## 7. 分阶段路线图（REV5：D6/D7 落地）

| 阶段 | 内容 | 独立价值 |
|---|---|---|
| **P0 数据补齐** | 快照列(order_products/ledgers cost_price_snapshot)+回填脚本；customers 客户主数据（registered 关联 + tmp 按名归并，无电话靠人工确认；散客有电话才能挂账）+迁移；driver_bills+生成规则（**按月**）；expenses（不含 invoice_id）；shipper_receipts（**itemized 默认**）；cash_flows；vehicles 车辆台账；**司机完成订单货损录入**（§4.12：damage 列+完成弹层+送达账务联动）；异常单客户侧冲销规则；拆单独立计账规则 | 老板马上能录开销、收账款（逐单）、按人看应付；散客不串户；货损自动入账 |
| **P1 报表** | /reports/pnl、customer-balances（含按挂账单位分组）、driver-cost、gross-margin；账龄桶；客户合并/去重接口；预收处理(RECEIPT_PREPAID)；司机借支(ADVANCE)+结算抵扣；库存盘亏金额化(expenses LOSS)；现金盘点(cash_flows.channel)；Android 报表中心加「经营利润」入口 | 3 问全部可答 |
| **P2 导出** | ledger_export_jobs 泛化 kind（shipper_id 可空/format 加长）；报表导出 excel/pdf；司机账单/结算单导出；旧 freight-settlement 下线（司机端切新接口） | 报税、对账、外部核对 |
| **P3 税账** | invoices 建表+登记/开具/作废冲红（**税率档启用时定**，D5）；expenses 补 invoice_id；tax-summary；供应商进货与进项发票关联 | 进销项税汇 |
| **P4（可选）** | 银行流水导入对账、客户信用额度、账龄催收提醒、税缴纳流水 | 精细化 |

---

## 8. 复用现状的清单（避免重复建设）

- 商品成本价录入（ProductsScreen 已有）✅
- 司机工资档案（UsersManageScreen 已有）✅
- 挂车按单 freight_fee（订单/派单已有）✅
- 营业额报表图表（ReportCenter 营业 tab 已有，仅改名+对齐口径）✅
- 货主账本+手动记账+accounts 聚合（已有）✅——accounts 聚合扩展成含实收/红冲的余额（挂 customers）
- 导出任务框架（ledger_export_jobs 异步+通知）✅——泛化 kind 即可
- 物料/库存/价格（不动）✅
- 父子拆单（已核实存在）：子单各自独立计应收/运费（parent 不重复计），P0 生成规则按子单独立；主单作废时子单账务跟随其订单状态。

---

## 9. 已拍板决策（老板 2026-09-03 确认）

| # | 决策 | 落定内容 | 影响 |
|---|---|---|---|
| D1 | 货主付款**含配送费** | 不新增 `customer_delivery_fee`；营业额=货款（含配送）；司机运费=成本 | 利润公式无重复计算 |
| D2 | 客户收款**逐单核销** | shipper_receipts.settle_mode 默认 itemized，order_ids 必填，绑定订单标记 paid | 欠款可展开到订单明细 |
| D3 | 司机**统一按月结算** | 挂车与固定工资均按月出结算单（month 归属） | 结算单粒度=月 |
| D4 | 固定工资发放流程**暂定** | 默认「月初生成 DRAFT → CONFIRM → PAID」，可再调 | 工资单流水 |
| D5 | 税率**暂定** | 发票支持多税率档，启用 P3 时再定档 | 发票登记能力边界 |
| D6 | **建车辆台账** | vehicles 表纳入 P0 | 开销按车归属 |
| D7 | 货损**公司自担** | 记 EXPENSE_LOSS（成本口径）+ COGS 等量冲回；**司机完成订单可选录入货损**（§4.12） | 货损自动入账、利润真实 |
| D8 | **散客可挂账** | 有电话档案的散客可挂账；无电话只能现金结 | 散客账完整性 |

---

## 10. 风险与注意事项

1. **存量数据回填**：现有订单无成本快照 → 用当前 `products.cost_price` 回填是近似（无法还原当年真实成本），报表中标注「历史订单成本为当前价近似值」；无 product_id/已删商品行保持 0 并标注缺失；从上线后新单开始精确。
2. **结算单并发**：同批 driver_bills 被两个结算单占用 → CONFIRM 用事务 + `WHERE status='OPEN'` 原子判定，禁止重复结算。
3. **金额精度**：全部 Decimal(12,2)/NUMERIC(14,4)，后端聚合一律 Decimal，禁止 float（现状报表有 float 隐患，P1 顺手修）。
4. **测试数据**：开发库现有 12 DELIVERED/7 CANCELLED/5 ACCEPTED + 2 组父子拆单 + 散客重名（orders 层 '刷新'×3 / ledgers 层 ×2），P0 验证需造「挂车结算/固定工资/开销/收款(逐单)/散客收款/货损」各 1-2 条演示数据。
5. **旧接口兼容声明**：`freight-settlement` **保持现状实现不变**（继续运行时聚合，兼容已部署司机端），P2 时才切换新接口并下线；`/ledger/entries`、`/reports/turnover` 全程保留；新表不触碰既有查询路径。SALARY 脏单（freight_fee>0）只影响旧接口展示，不影响 driver_bills 生成。
6. **异常单**：`is_exception` 单送达时正常入账（业务已发生），异常处理决议（退货/货损/少收/赔偿）通过红冲+开销联动实现，不在送达时预扣；司机送达后货损补录/纠错走异常处理（P1）。

---

## 11. 修订点索引

- **REV1**：P0-1 退款/余额自洽；P0-2 散客唯一键；P0-3 异常/货损客户侧红冲；P0-4 expenses 不引用未建表；结算单状态机；旧接口兼容声明；挂账单位打通；毛利/利润改名；PAYMENT_SUPPLIER；party_type 收窄；cash_flows.channel；分类补 PARKING/FINE/LOSS；tax_rate 空值；导出泛化字段；invoices 状态枚举；账龄桶；月中归属；拆单规则；G8 事实修正。
- **REV2**：①司机未结公式修正（Σ全部未作废 bills − Σ(OUT) + Σ(IN refund)，弃用 Σ(OPEN)）；②客户侧冲销规则；③历史散客迁移修正（按名归并+人工确认+合并接口 P1+tmp→registered 升级路径；部分唯一索引 phone IS NOT NULL + user_id 唯一）；④LOSS 口径+COGS 冲减；⑤挂账单位报表落点；⑥结算单一致性校验；⑦/ledger/accounts 迁移细节；⑧车辆表延后注记。
- **REV3**：①客户侧冲销正交规则（退货一律红冲、已收退款记 OUT，验算 A/B，废止「互斥」）；②货损 COGS 双计修复（客户拒付→红冲不记 LOSS；公司自担→LOSS+COGS 等量冲回）；③散客电话提取优先级 contact_boss_phone；④挂账单位分组键口径。
- **REV4**：①销售红冲两种形态（货退回/拒收→冲 COGS；货保留但少收/坏账/让利→保留 COGS）；②REFUND_CUSTOMER 注释改「客户现金退款」。
- **REV5（定稿）**：①D1-D8 全部拍板落定（§9，含 D1 含配送费→不建 customer_delivery_fee、D2 逐单核销默认、D3 统一按月、D6 vehicles 入 P0、D7 公司自担、D8 散客可挂账）；②**司机完成订单货损录入**（§4.12：order_products.damage_quantity+orders.damage_note + 完成弹层 + 送达账务联动 LOSS+COGS 冲回，客户/营业额零影响）；③§6 营业额口径删配送费项；④§4.5 settle_mode 默认 itemized；⑤§4.3/4.6 month 必填（按月）。
