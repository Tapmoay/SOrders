# R4 Core / Extension Boundary Map（核心 / 扩展边界图）

> **R4-01 的产物**。依据：用户 2026-09-27 交来的方向指南
> [ARCHITECTURE_RECTIFICATION_R4.md](ARCHITECTURE_RECTIFICATION_R4.md)（§3「R4 第一件事不是写代码，而是划边界」、§4 四条判定规则）。
> ⛔ 指南 §3 同时踩了刹车：**不要看到 15 个领域就开始"给 15 个领域全部做成模块"**。
> 这一页的作用正是**阻止那件事** —— 先把每样东西定在哪一档，再谈动谁。
>
> **这一页不改一行代码**（指南 §34：「R4-01 … 不改代码」）。

---

## 0. 一句话

> **核心负责定义「什么是真的」，扩展负责定义「怎么做」。**
> 核心不可插拔，边缘能力可插拔。

⛔ 而核心**也不能被写成一串 `if`**：
`if unit == "kg" … elif unit == "jin" … elif pricing == "cold_chain" …` —— 那不是稳定，是把变化藏进核心。
所以核心固定的是**语义与契约**，不是每一种可能的实现。

---

## 1. 四档是什么（指南 §3 / §4）

| 档 | 意思 | 判据 |
| --- | --- | --- |
| `CORE` | 定义**系统事实**：订单最终状态 / 账本最终金额 / 谁是谁 / 谁有没有权限 / 事务成不成功 / 事件可不可靠投递 | 四问里有任一为"是"就**先判 Core** |
| `EXTENSION_POINT` | 一个**稳定契约**：同一件事可以换多种实现 | 会出现多个实现；且它只改变"规则实现"，不改变事实 |
| `EXTENSION_IMPL` | 契约的**一个具体实现**，或一个**自足的功能模块** | 增加 / 替换 / 删除它，核心**不需要改** |
| `INFRASTRUCTURE` | 机制与适配器：数据库、Redis、HTTP、文件系统、客户端、工具链 | 它不表达任何业务事实，只保证事实**送得到 / 存得住** |

### 四条判定规则（指南 §4，逐条可执行）

1. **它是否定义系统事实？** → 是 ⇒ Core
2. **它变化时，系统核心语义是否应该改变？** → 是 ⇒ Core；只改变规则实现 ⇒ Extension
3. **这个能力消失以后，核心业务还能不能成立？**（Order / Money / Auth / Ledger 仍然成立）→ 是 ⇒ Extension
4. **插件是否应该能够决定核心事实？** → 只要答案是"是"，**先判 Core**

### ⭐ 这一页最贵的一条线（指南 §6）

> **"计算"可以扩展，"事实"不能扩展。**

| | 档 |
| --- | --- |
| 运费计算器 | `EXTENSION_POINT` |
| 司机结算公式 | `EXTENSION_POINT` |
| Ledger | `CORE` |
| Money 类型 / 舍入口径 | `CORE` |
| 账务最终落账 | `CORE` |
| 单位换算率怎么算 | `EXTENSION_IMPL` |
| 「这个数量是多少」这件事本身（Quantity 的语义） | `CORE` |

---

## 2. 怎么读（机器契约）

下面每一个 ```capability 围栏是一行**声明**，判据
[`_tools/qa/_check_core_extension_boundary.py`](../_tools/qa/_check_core_extension_boundary.py) 逐条核对它与代码是否对得上：

```text
id:          <英文短名，唯一>
中文名:      <给人看的名字>
class:       CORE | EXTENSION_POINT | EXTENSION_IMPL | INFRASTRUCTURE
domain:      <DOMAIN_BOUNDARIES.md 里的 15 个域名之一，或 ->（跨域/设施）
owns:        <表名，逗号分隔；- = 不拥有任何表>
contract:    <它对外承诺的契约名；CORE 也可以有契约（如 Money）；- = 无>
why:         <为什么是这一档，一句话，≥20 字>
impl:        <真实存在的实现站点 文件::符号 或 文件路径；- = 尚未实现>
pending:     yes|no（yes 时必须同时写 pending_reason）
```

### 五条铁律（判据钉着的就是这五条）

1. **47 张表恰好一个归属**（`__tablename__` 全量）：既不许多头，也不许孤儿 —— 与
   [DOMAIN_BOUNDARIES.md](DOMAIN_BOUNDARIES.md) 铁律 1 同源，但**多问一句"它属于核心还是扩展"**。
2. **18 个事件类型恰好一个归属**，且都必须被声明成 **事实通知**（§28）—— 见 §5。
3. **`class: CORE` 的条目不许把具体实现写进 `impl` 当依赖**：`impl` 只登记"这个事实在哪儿被定义"，
   ⛔ 不是"核心依赖了哪个扩展"（那正是 §13 单向性要防的）。
4. **`class: EXTENSION_POINT` 必须写 `contract`**（没有契约的"扩展点"只是一个愿望）。
5. **`pending: yes` 必须写 `pending_reason`**（≥20 字）。⛔ 不许用 pending 躲判定。

### 怎么加一条

按上面格式追加一个块 → 跑 `python _tools/qa/_check_core_extension_boundary.py`。
判据会拒绝：把已经在别处的表再认领一次、写不存在的实现站点、把 CORE 写成 EXTENSION_IMPL 却没有理由。

---

## 3. 核心（CORE）

### 3.1 订单与生命周期

```capability
id: order.lifecycle
中文名: 订单生命周期
class: CORE
domain: order
owns: orders, order_products, order_templates, order_template_categories
contract: OrderLifecycleContract v1
why: 它定义「订单最终是什么状态」—— 什么叫派单/接单/送达/取消、状态迁移合不合法，全是系统事实（判定规则 1）
impl: services/order_flow.py
pending: no
```

**为什么不能扩展**：状态机一旦可替换，"这一单到底成了没有"就有两个答案，
而**钱、库存、账单全挂在那个答案上**。指南 §5 把 `Order Lifecycle` 列在 Core 候选第一位。

**⛔ 状态只有一个写入口**：`order.status` 的每一次变化都在 `services/order_flow.py` 里、且都是条件 UPDATE（CAS）。
判据 `_check_order_commands.py` 核对「API 层一处都没有直接写订单状态」。

```capability
id: order.command_semantics
中文名: 命令语义（前置状态 → 目标状态）
class: CORE
domain: order
owns: -
contract: CommandRegistry
why: 每条命令的「前置状态 → 目标状态 / 需要哪个权限点 / 会发什么事件 / 会写哪些别的域的表」就是事务语义本身（判定规则 1）
impl: commands/registry.py
pending: no
```

```capability
id: order.return
中文名: 退货（红冲 + 回补）
class: CORE
domain: return
owns: order_return_requests, order_return_request_lines
contract: -
why: 退货会改应收、回补库存、可能退现 —— 「同一笔钱不许出现两个数」这条不变量直接压在它身上（判定规则 1）
impl: services/order_return.py, services/order_return_request.py
pending: no
```

### 3.2 钱与账本

```capability
id: money.ledger
中文名: 账本事实（一笔钱只有一个数）
class: CORE
domain: money
owns: ledgers, cash_flows, shipper_receipts, shipper_settlements, shipper_settlement_lines, supplier_payables, expenses, expense_categories
contract: MoneyContract
why: 应收 / 已收 / 欠款 / 红冲 / 支出 / 付款是**最终事实**；指南 §6 明确 Ledger 与账务最终落账都不可扩展（判定规则 1）
impl: services/accounting_service.py, services/ledger_sync.py, services/shipper_settle.py
pending: no
```

```capability
id: money.arithmetic
中文名: Money 类型与舍入口径
class: CORE
domain: money
owns: -
contract: MoneyContract
why: 金额怎么表示、怎么舍入，决定了同一个数在四个界面是不是同一个数；它是"事实的表示"，不是"规则"（判定规则 1）
impl: services/money_contract.py, services/money_text.py, services/order_money.py
pending: no
```

```capability
id: settlement.truth
中文名: 结算事实（账单与结算单）
class: CORE
domain: settlement
owns: driver_bills, driver_settlements
contract: -
why: 「这一单司机应得多少」落成账单之后就是事实；⛔ 可扩展的是**算它的公式**，不是这张账单（指南 §6 明确划的线）
impl: services/accounting_service.py, services/driver_pay.py
pending: no
```

### 3.3 身份、授权与审计

```capability
id: identity
中文名: 身份（谁是谁）
class: CORE
domain: identity
owns: users, usage_counters
contract: -
why: 账号、角色、令牌版本是「谁」这件事的唯一事实源；权限判据只认库里的角色（判定规则 1）
impl: services/auth_service.py, services/usage_service.py
pending: no
```

```capability
id: authorization.capability
中文名: 能力注册表（谁能干什么）
class: CORE
domain: identity
owns: -
contract: CapabilityRegistry
why: 一条能力必须先有**真正的执行点**才算数；扩展只能**声明**能力，判定权必须在核心（判定规则 4）
impl: core/capabilities.py, core/rbac.py, core/role_capabilities.py
pending: no
```

```capability
id: authorization.deps
中文名: 鉴权依赖（require_roles / 当前用户）
class: CORE
domain: -
owns: -
contract: -
why: 漏一处就是越权；指南 §27 明确「认证、权限、核心安全策略不能被 Extension 自己定义成另一套体系」
impl: deps.py
pending: no
```

```capability
id: audit.operation_log
中文名: 核心审计（谁在什么时候对什么做了什么）
class: CORE
domain: audit
owns: operation_logs
contract: -
why: 只增不改的事实，全项目所有域都能往里写一条，但格式与落库只有一处实现（判定规则 1）
impl: services/operation_log_service.py
pending: no
```

### 3.4 事务、持久化与运行时

```capability
id: transaction.boundary
中文名: 事务边界（Route → Command → 那一次 commit）
class: CORE
domain: -
owns: -
contract: -
why: 一笔事务是不是成功、失败怎么回滚、重复执行怎么办，是"事实成不成立"的判据（判定规则 1）
impl: docs/BUSINESS_TRANSACTION_MAP.md
pending: no
```

```capability
id: persistence.invariants
中文名: 线上库结构变更（迁移的唯一入口）
class: CORE
domain: -
owns: -
contract: -
why: 动一下就会让**历史数据变样**；它是核心持久化不变量的唯一执行点，扩展不许自己建表（判定规则 1 + 规则 4）
impl: core/schema_bootstrap.py
pending: no
```

```capability
id: outbox.reliability
中文名: 可靠投递（发件箱 + 投递原语）
class: CORE
domain: platform
owns: outbox_events
contract: OutboxDeliveryContract
why: 「一个事件是否可靠投递」是指南点名的 Core 判据之一；投递原语说谎，整条 outbox 边界就是假的（判定规则 1）
impl: core/outbox.py, core/socket_io.py
pending: no
```

> ⚠️ **`core/socket_io.py` 为什么在这一档、而且不许因为"想做插件化"被拆出去**：
> R3-06 生产故障演练 Drill C 用**原始输出**证明过它位于可靠投递边界 —— 停 Redis 时
> 一条真实业务写入的发件箱事件被记成 `sent attempts=0`，而日志里有 16 条
> `Cannot publish to redis... giving up`。修法与证据链见
> [R3_FAILURE_DRILL_EVIDENCE.md](R3_FAILURE_DRILL_EVIDENCE.md) §三·发现 2。

```capability
id: security
中文名: 安全边界（口令 / JWT / 令牌版本）
class: CORE
domain: identity
owns: -
contract: -
why: 改错的后果是"谁都能当派单员"，而这类错误在界面上完全看不出来（判定规则 1）
impl: core/security.py, services/auth_service.py, services/login_guard.py
pending: no
```

```capability
id: business_time
中文名: 业务时区（库里 UTC naive、界面 +8）
class: CORE
domain: -
owns: -
contract: -
why: 差 8 小时就是错账；指南 §5 把 Business Time 列在 Core 候选里（判定规则 1）
impl: core/business_time.py
pending: no
```

```capability
id: runtime.composition
中文名: 应用装配与运行时（进程入口 / 配置 / 生命周期）
class: CORE
domain: -
owns: -
contract: -
why: 谁在什么时候被装进进程、配置从哪来，决定了"这个系统现在到底是什么"（判定规则 1）
impl: main.py, config.py
pending: no
```

### 3.5 主数据（卖什么 / 跟谁打交道 / 用什么运）

```capability
id: catalogue.products
中文名: 商品目录与成本基线
class: CORE
domain: catalogue
owns: products, product_categories, product_cost_history, user_product_visibility
contract: -
why: 「卖什么」「这件商品给不给这个人看」是事实源；下单那一刻要把它快照进订单，之后谁的变更都不许回头改历史单（判定规则 1）
impl: api/v1/products.py, services/cost_history.py
pending: no
```

**⛔ 成本是快照不是引用**：下单时把 `cost_price` 定格进 `order_products.cost_price_snapshot` ——
所以"毛利"这件事的原料来自**下单那一刻的目录域**，不是订单域自己算的。
**为什么 `user_product_visibility` 在这里**：它的语义是"这一件商品给不给这个人看"，是目录的一部分
（`products.py::visible_product_ids` 一处实现）；挪到权限域会变成"权限表里存商品编号"。

```capability
id: party.master
中文名: 往来单位档案（货主 / 批发商 / 散客 / 供应商 / 挂账单位 / 地址 / 联系人）
class: CORE
domain: party
owns: customers, suppliers, arrears_units, shipper_addresses, shipper_contacts, shipper_locations
contract: -
why: 订单必须知道「跟谁」、钱必须记在某个名下；删掉它订单根本建不起来（判定规则 3 反问：核心业务不再成立）
impl: api/v1/customers.py, services/supplier_service.py, services/shipper_contact_service.py
pending: no
```

> ⚠️ **这一档是"人判的"，如实说明**：指南 §6 的 Extension 候选里没有它，而它对订单是**硬依赖**。
> ⛔ 与钱域的边界不变：这一域拥有**档案**（名字 / 电话 / 地址），钱域拥有**金额**。

```capability
id: freight.vehicle_registry
中文名: 车辆档案
class: CORE
domain: freight
owns: vehicles
contract: -
why: 「有哪些车、车牌是什么」是引用型主数据（订单与司机都引它），不是"怎么算钱"的规则（判定规则 2：它变的是档案，不是算法）
impl: api/v1/vehicles.py
pending: no
```

### 3.6 库存、消息与 AI 计数

```capability
id: inventory.movement
中文名: 库存流水（货动了没有）
class: CORE
domain: inventory
owns: inventory_movements
contract: -
why: 「不能超卖」是一条核心持久化不变量，而库存流水是它唯一的执行点；⛔ 订单域不许直接写它（判定规则 1）
impl: services/inventory_service.py, services/warehouse.py
pending: no
```

```capability
id: notification.data
中文名: 站内信数据（谁在什么时候收到了什么）
class: CORE
domain: notification
owns: notifications
contract: -
why: 站内信是**用户看得见的事实**；投递方式（怎么送出去）才是扩展点，两者必须分开（判定规则 1 vs 规则 2）
impl: services/message_center.py
pending: no
```

```capability
id: ai.call_accounting
中文名: AI 调用计数（今天问了几次、确认了几次写）
class: CORE
domain: ai
owns: ai_call_daily
contract: -
why: 它是一条独立的业务事实（用量与审计），与任何业务域都不重合；⛔ 可扩展的是**模型供应商**，不是这个计数（判定规则 1）
impl: api/v1/ai_telemetry.py, core/metrics.py
pending: no
```

```capability
id: ai.write_gate
中文名: AI 写闸门（preview → 确认卡 → execute 的唯一写入口）
class: CORE
domain: ai
owns: -
contract: -
why: 指南 §27 的原则（Extension 能声明能力，判定权在核心）在 AI 侧的形态就是这道闸门：模型只能**申请**（判定规则 4）
impl: android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteService.kt
pending: no
```

```capability
id: reporting.read_model
中文名: 报表口径（只读聚合）
class: CORE
domain: reporting
owns: -
contract: -
why: 「营业额 / 毛利 / 司机绩效怎么算」的口径必须只有一处，否则两个界面两个数而两边都不报错；⛔ 可扩展的是**渲染成什么格式**（判定规则 1 vs 规则 2）
impl: services/reports/, services/reports_service.py, services/stats_service.py
pending: no
```

---

## 4. 扩展点与扩展实现（EXTENSION POINT / EXTENSION IMPL）

> ⭐ 记住那条线：**"计算"可以扩展，"事实"不能扩展。**
> 下面每一个 `EXTENSION_POINT` 都**必须**有一个契约（铁律 4）；
> 每一个 `EXTENSION_IMPL` 都必须做到「增加 / 替换 / 删除它，核心不需要改」。

### 4.1 扩展点（契约）

```capability
id: unit.conversion
中文名: 单位换算（一车 = 8 方）
class: EXTENSION_POINT
domain: catalogue
owns: -
contract: UnitConversionContract v1
why: 它只改变「换算率怎么算」，不改变「这个数量是多少」这件事实；换一种单位体系不该动核心（判定规则 2 后半）
impl: services/unit_conversion.py
pending: no
```

```capability
id: pricing.freight
中文名: 运费计算（这一单该收多少）
class: EXTENSION_POINT
domain: freight
owns: -
contract: PricingContract v1
why: 指南 §6 点名「运费计算器 ✅ Extension」；它产出的必须是核心的 Money，而不是插件自己的对象
impl: services/freight_pricing.py
pending: no
```

```capability
id: pricing.driver_billing
中文名: 司机计费规则（这一趟司机拿多少）
class: EXTENSION_POINT
domain: settlement
owns: -
contract: PricingContract v1
why: 指南 §6 点名「司机结算公式 ✅ 可以扩展」；规则可换，落成的那张账单不可换（见 settlement.truth）
impl: services/driver_pay.py
pending: no
```

```capability
id: pricing.price_rules
中文名: 批发商专属价
class: EXTENSION_POINT
domain: catalogue
owns: -
contract: PricingContract v1
why: 「这一个人买这一件商品多少钱」是定价规则的一种实现，与基础运费同属 PricingContract（判定规则 2 后半）
impl: api/v1/price_rules.py
pending: no
```

```capability
id: pricing.tax
中文名: 税费计算
class: EXTENSION_POINT
domain: money
owns: -
contract: PricingContract v1
why: 指南 §6 把 Tax Calculation 列为 Extension 候选；它只改变"算多少"，不改变"钱记在哪本账"
impl: -
pending: yes
pending_reason: 当前系统**没有**税费这一项业务（用户未提出），所以这里只登记扩展点的位置，不假造实现；等真出现第二种税率再判断
```

```capability
id: pricing.promotion
中文名: 促销 / 折扣规则
class: EXTENSION_POINT
domain: money
owns: -
contract: PricingContract v1
why: 指南 §6 把 Promotion / Discount Rules 列为 Extension 候选；与税费同理，只改变金额怎么来
impl: -
pending: yes
pending_reason: 当前系统**没有**促销业务；指南 §32 的原话是「真正模糊的地方：先不要抽象，等第二个实现出现再判断」，所以只留位置
```

```capability
id: report.render
中文名: 报表渲染（同一份事实渲染成不同形态）
class: EXTENSION_POINT
domain: reporting
owns: -
contract: ReportRenderContract v1
why: 指南 §11「核心定义 Report Data，扩展负责怎么渲染 / 怎么导出 / 怎么排版」—— 渲染可换，口径不可换
impl: services/stats_export.py
pending: no
```

```capability
id: export.data
中文名: 数据导出（把事实导出成文件）
class: EXTENSION_POINT
domain: platform
owns: -
contract: ExportContract v1
why: 指南 §6 把 Import / Export 列为 Extension 候选，§11 说明它天生是外围能力：导出失败了，订单与账本照样成立
impl: services/ledger_export_worker.py, services/ledger_export_paths.py
pending: no
```

```capability
id: notification.provider
中文名: 通知投递渠道
class: EXTENSION_POINT
domain: notification
owns: -
contract: NotificationDeliveryContract v1
why: 指南 §10 的 Provider 形态：核心不该知道用了哪种推送；站内信（事实）与投递（方式）必须分开
impl: services/message_push.py, core/socket_io.py
pending: no
```

```capability
id: ai.provider
中文名: AI 模型供应商
class: EXTENSION_POINT
domain: ai
owns: -
contract: AiProviderContract v1
why: 指南 §10 点名 AI Provider；核心不该知道 OpenAI / Qwen 这些实现细节
impl: android/app/src/main/java/com/tapmoay/sorders/ai/
pending: no
```

```capability
id: integration.maps
中文名: 第三方地图（高德）
class: EXTENSION_POINT
domain: place
owns: -
contract: ExternalIntegrationContract v1
why: 指南 §10 的 External Integration Provider；地图挂了，下单与派单照样能走（只是不能自动算距离）
impl: core/transport.py, api/v1/places.py
pending: no
```

```capability
id: search.ranking
中文名: 搜索 / 排序
class: EXTENSION_POINT
domain: -
owns: -
contract: SearchRankingContract v1
why: 指南 §6 把 Search / Ranking Provider 列为 Extension 候选；当前只有"按人搜索一条规则"（core/user_search.py），还没有第二种排序口径
impl: core/user_search.py
pending: yes
pending_reason: 目前**只有一种**搜索实现，指南 §18 明确「先证明这个契约真的会被多个实现使用，再为它设计长期版本兼容」——所以只登记位置
```

### 4.2 扩展实现（具体实现 / 自足功能模块）

```capability
id: unit.conversion.table
中文名: 表驱动的用户自建换算（现有实现）
class: EXTENSION_IMPL
domain: catalogue
owns: unit_conversions
contract: UnitConversionContract v1
why: 它是 UnitConversionContract 的**第一个实现**：换算率由用户自己填、存在自己的表里；⛔ 不做链式换算（写死在实现里，不是核心的事）
impl: services/unit_conversion.py, api/v1/unit_conversions.py
pending: no
```

```capability
id: pricing.freight.template
中文名: 运费模板匹配（价目 → 规则 → 司机）
class: EXTENSION_IMPL
domain: freight
owns: freight_categories, freight_templates, freight_template_drivers, freight_template_categories
contract: PricingContract v1
why: 它是 PricingContract 的**第一个实现**：按路线 + 分类 + 司机匹配出一条价目；同一档匹配到多条就**不猜**，返回候选让人挑
impl: services/freight_pricing.py
pending: no
```

```capability
id: pricing.driver_rule.standard
中文名: 司机计费规则（工资 / 计件 / 提成三件可组合）
class: EXTENSION_IMPL
domain: settlement
owns: driver_billing_rules, driver_billing_rule_categories, driver_billing_rule_templates
contract: PricingContract v1
why: 它是"司机这单拿多少"的**第一个实现**；规则在派单那一刻**快照**进订单，所以规则后来被改不会回头改历史单的钱
impl: services/driver_pay.py
pending: no
```

```capability
id: pricing.price_rule.special
中文名: 批发商专属价
class: EXTENSION_IMPL
domain: catalogue
owns: price_rules
contract: PricingContract v1
why: 它是 PricingContract 在"按人定价"这一维上的实现；与运费模板实现并列，替换其一不影响另一
impl: api/v1/price_rules.py
pending: no
```

```capability
id: export.ledger.xlsx
中文名: 账本导出（异步任务 + xlsx 产物）
class: EXTENSION_IMPL
domain: money
owns: ledger_export_jobs
contract: ExportContract v1
why: 它是 ExportContract 的实现，**拥有自己的运营数据**（导出任务表）；⛔ 它只读账本、不写账本（账本事实仍归 money.ledger）
impl: services/ledger_export.py, services/ledger_export_worker.py
pending: no
```

```capability
id: notification.provider.socket
中文名: 站内推送（Socket.IO 实时总线）
class: EXTENSION_IMPL
domain: notification
owns: -
contract: NotificationDeliveryContract v1
why: 它是投递渠道的**第一个实现**；⛔ 它不拥有站内信数据（那是 notification.data），也不许改投递以外的东西
impl: services/push_events.py, core/outbox.py
pending: no
```

```capability
id: place.library
中文名: 地点库（我的地点 / 常用线路 / 地点分类）
class: EXTENSION_IMPL
domain: place
owns: places, place_user_usage, place_categories
contract: -
why: 它是**自足功能模块**：删掉它订单照样能下（只是要手填地址）、钱与账本完全不受影响（判定规则 3）
impl: services/place_service.py, api/v1/places.py
pending: no
```

```capability
id: integration.maps.amap
中文名: 高德地图适配（地理编码 / 逆地理 / 路线）
class: EXTENSION_IMPL
domain: place
owns: -
contract: ExternalIntegrationContract v1
why: 它是 ExternalIntegrationContract 的具体适配器；⛔ 核心不认识"高德"这两个字（§13 单向性），只认识契约
impl: core/transport.py
pending: no
```

---

## 5. 事件（指南 §28：**Event 是事实通知，不是隐藏调用**）

指南把 Event 列为"很容易让模块化走向蜘蛛网"的东西，并给了两条规矩：

> **Event 适合**：「事情已经发生了。」
> **Command 适合**：「请做这件事。」
> 如果它是**必需业务流程**，用 `Command` 通常比 `Event` 更合适。

### 5.1 这一页的判据

⭐ **本项目 18 个事件类型，全部是"事实通知"** —— 依据不是我说了算，而是
**核心业务流程一条都不走事件**：状态迁移走 `commands/registry.py` 里那条
`Route → Command → 那一次 commit`（见 §3.4 `transaction.boundary`），事件只由
`core/outbox.py` 投递出去做**推送**（`main.py::_outbox_deliver` 的派发表逐条登记）。

所以可判定的形态是：**把事件的消费端整个拿掉，订单 / 钱 / 权限 / 账本的事实一个都不许变。**
这条不是散文 —— 它是 R4-03 的一条**反向破坏用例**（关掉 outbox 消费者，重跑业务链路对账）。

### 5.2 事件清单（机器可核：与 `outbox.enqueue(...)` 的字符串字面量逐条对账）

| 事件类型 | 产生者（能力 id） | 它是什么事实 | 消费点 | 删掉消费点会改变核心事实吗 |
| --- | --- | --- | --- | --- |
| `orders.created` | `order.lifecycle` | 订单已经建好了 | `main.py::_outbox_deliver` → 待派池推送 | ❌ 不会（订单行已在库里） |
| `orders.assigned` | `order.lifecycle` | 这一单已经派给某个司机了 | 同上 → 司机端响铃 / 列表刷新 | ❌ 不会 |
| `orders.delivered` | `order.lifecycle` | 货已经送到了 | 同上 | ❌ 不会（账单/账本在同一次事务里已经写好） |
| `orders.cancelled` | `order.lifecycle` | 这一单已撤销 | 同上 | ❌ 不会 |
| `orders.recalled` | `order.lifecycle` | 派单被撤回了 | 同上 | ❌ 不会 |
| `orders.revoked` | `order.lifecycle` | 司机接单被撤销 | 同上 | ❌ 不会 |
| `orders.edited` | `order.lifecycle` | 订单内容被改过 | 同上 | ❌ 不会 |
| `orders.driver_acked` | `order.lifecycle` | 司机已经看到这一单了 | 同上 | ❌ 不会 |
| `orders.freight_updated` | `order.lifecycle` | 运费被改过 | 同上 | ❌ 不会 |
| `orders.pending_pool_changed` | `order.lifecycle` | 待派池的构成变了 | 同上 → 派单员列表刷新 | ❌ 不会 |
| `orders.navigation_filled` | `order.lifecycle` | 导航地址已经补上了 | 同上 | ❌ 不会 |
| `returns.requested` | `order.return` | 有人提了退货申请 | 同上 → 派单员消息 | ❌ 不会（申请行已在库里） |
| `returns.rejected` | `order.return` | 退货申请被驳回 | 同上 | ❌ 不会 |
| `returns.request_closed` | `order.return` | 那张申请被直连退货自动关掉了 | 同上 | ❌ 不会 |
| `returns.done` | `order.return` | 货真的退掉了（钱已红冲、库存已回补） | 同上 | ❌ 不会 |
| `ledger.updated` | `money.ledger` | 账本有新的流水了 | 同上 → 账本页刷新 | ❌ 不会 |
| `notifications.created` | `notification.data` | 有一条新的站内信 | 同上 → 收件人红点 | ❌ 不会（站内信是**数据**，已经在库里） |
| `notifications.unread_changed` | `notification.data` | 未读数变了 | 同上 | ❌ 不会 |

> ⚠️ **最后一列全是 ❌ 是本页最想钉住的一件事**：它意味着 **18 个事件没有一个在偷偷承担业务流程**。
> 若将来有人把"送达之后要生成账单"改成"监听 `orders.delivered` 再生成账单"，
> 这一列会变成 ✅，那时它就该被改回 **Command**（指南 §28 的原话）。

### 5.3 ⛔ 三条禁令

1. **⛔ 不许用 Event 完成核心业务步骤**（"钱在事件里落账"是最坏的一种）；
2. **⛔ 不许一个事件有 15 个模块在监听、而其中 8 个是核心必需** —— 那说明它们是 Command；
3. **⛔ 新增事件类型必须同时在本表登记归属**（判据会拿 `outbox.enqueue` 的字面量对账，
   代码里产生了却没人认领 = 报红）。

---

## 6. 基础设施（INFRASTRUCTURE）

> 这一档的东西**不表达任何业务事实**，只保证事实**送得到 / 存得住**。
> 判据：换掉它（换成另一种数据库、另一种消息通道）不该改变任何一条业务语义。

```capability
id: infra.database
中文名: 关系库与 ORM
class: INFRASTRUCTURE
domain: -
owns: -
contract: -
why: 它只负责"事实存在哪"；换一种库不该改变任何业务语义（生产 MySQL 8 / 本机 SQLite 已是两种实现）
impl: database.py, models/
pending: no
```

```capability
id: infra.redis
中文名: Redis（Socket.IO 跨实例总线）
class: INFRASTRUCTURE
domain: platform
owns: -
contract: -
why: 它是**投递的通道**，不是投递的承诺；Redis 停掉时业务读写照样成立，只有跨实例实时推送断开（R3-06 Drill B 实测）
impl: redis_client.py, core/socket_io.py
pending: no
```

```capability
id: infra.http_server
中文名: HTTP 服务与编排（uvicorn / nginx / systemd）
class: INFRASTRUCTURE
domain: -
owns: -
contract: -
why: 进程怎么起、请求怎么进来，属于部署形态；同机双实例与单实例对业务语义没有影响（R3-05/R3-06 实测）
impl: _tools/deploy/_release.py
pending: no
```

```capability
id: infra.filesystem
中文名: 本机文件系统资产（uploads / exports）
class: INFRASTRUCTURE
domain: -
owns: -
contract: -
why: 上传资产是**本机文件系统资产而不是对象存储**（R3-03-A 的架构决策，见 docs/R3_DECISIONS.md）；换存储不该动业务
impl: config.py::uploads_root, services/image_archive.py
pending: no
```

```capability
id: infra.client
中文名: 客户端表现层（Android）
class: INFRASTRUCTURE
domain: -
owns: -
contract: -
why: 它只把事实画出来；⛔ 但两个例外归 CORE：订单出参口径（order_response）与 AI 写闸门（ai.write_gate）
impl: android/app/src/main/java/com/tapmoay/sorders/
pending: no
```

```capability
id: infra.toolchain
中文名: 判据工具链（静态检查 / 反向验证 / 演练）
class: INFRASTRUCTURE
domain: -
owns: -
contract: -
why: 它保证"结论有依据"，本身不生产业务事实；R4 指南 §30 要求它**不要继续膨胀**（只做五个架构检查器）
impl: _tools/qa/, _tools/ai/, _tools/ops/
pending: no
```

```capability
id: infra.backup
中文名: 备份与恢复
class: INFRASTRUCTURE
domain: -
owns: -
contract: -
why: 它保证事实**丢不了**，不改变事实是什么；恢复默认不碰生产库（`_restore.sh` 不带 `--i-know` 只恢复进 sorders_drill_*）
impl: _tools/backup/
pending: no
```

---

## 7. 以后每碰到一个新功能，只问这五个问题（指南 §32）

| # | 问题 | 答"是"的含义 |
| --- | --- | --- |
| ① | 它是否**定义核心事实**？ | Core 候选 |
| ② | 它是否**改变核心不变量**？ | Core 候选 |
| ③ | 它是否**必须永久存在**？ | Core 候选 |
| ④ | 它是否可能**出现多个实现**？ | Extension 候选 |
| ⑤ | **删除它后 Core 是否仍然成立**？ | Extension 候选 |

- ①/②/③ 有任一为"是" ⇒ **Core 候选**
- ④/⑤ 为"是"、且 ①②③ 全为"否" ⇒ **Extension 候选**
- ⭐ **真正模糊的地方：先不要抽象。等第二个实现出现，再重新判断。**
  （本页三个 `pending: yes` 的条目就是这么留下来的 —— 它们**有位置、没有实现**。）

---

## 8. 指南列的 15 个施工禁区，各自落在哪个判据上（§31）

⛔ 这一节的意义：指南说"这里我给你直接列成施工禁区"，但**散文里的"禁止"靠记性守不住**
（第二轮就栽过一次）。所以每条禁令都指到一个**机器判据**或明确写"这条只能人判"。

| # | 禁区 | 落点 |
| --- | --- | --- |
| 1 | 为了模块化拆核心 | `_check_core_extension_boundary.py`：CORE 条目的实现站点必须仍在核心路径；核心区清单不许被掏空 |
| 2 | 万能 Plugin Base（`Plugin.execute()`） | `_check_extension_contracts.py`：⛔ 不许出现万能的基类/单一接口，契约必须按能力类型分开 |
| 3 | Core 反向依赖 Extension | `_check_extension_dependencies.py`：核心区文件里不许出现具体扩展的名字 |
| 4 | Extension 直接改 Core 表 | `_check_data_ownership.py`：扩展不许对核心拥有的表发写语句 |
| 5 | Extension 直接写 Ledger | `_check_data_ownership.py`（同一条的高危形态，单独一条用例） |
| 6 | 为了"通用"提前抽象 | `_check_extension_contracts.py`：`EXTENSION_POINT` 必须要么有 ≥2 个实现、要么写 `pending_reason` |
| 7 | 过早做动态加载 / 热插拔 | `_check_extension_manifest.py`：⛔ 不许 `importlib` 动态加载扩展、不许运行期上传代码 |
| 8 | 配置散落 | `_check_extension_manifest.py`：扩展的环境变量必须由 manifest 声明，且一律 `EXT_*` 前缀 |
| 9 | 删除模块导致历史无法解释 | `_check_data_ownership.py`：钱/审计/订单历史必须有**快照**，不许依赖扩展现算 |
| 10 | 事件变成隐形 RPC | `_check_core_extension_boundary.py`：§5.2 最后一列必须全是 ❌（核心事实不依赖事件消费者） |
| 11 | 权限被插件私有化 | `_check_extension_manifest.py`：扩展声明 capability，判据核对它用的是核心的 `require_*`，不是自己一套 |
| 12 | Extension 专属字段进入 Core Model | `_check_core_extension_boundary.py`：核心模型里不许出现扩展专属列（由扩展 manifest 的字段名反查） |
| 13 | 为了兼容保留 10 代接口 | `_check_extension_contracts.py`：同一契约的版本数设上限，且每代必须**有真实存在的实现** |
| 14 | 模块数量本身成为 KPI | ⚠️ **这条只能人判**：本页**不设**"模块数 ≥ N"这种目标 —— 写在这里，免得下一轮有人加一个 |
| 15 | 把"能拆"误认为"值得拆" | ⚠️ **这条只能人判**：判据只能核"拆了之后依赖有没有更多"，判断"值不值得"是人的事 |

---

## 9. 这一页**没有**解决的事（如实列着）

| 没做的 | 为什么 | 什么时候该做 |
| --- | --- | --- |
| `pricing.tax` / `pricing.promotion` / `search.ranking` 只有位置、没有实现 | 指南 §18：「先证明这个契约真的会被多个实现使用，再为它设计长期版本兼容」；§32：「真正模糊的地方先不要抽象」 | 真出现第二种税率 / 出现促销业务 / 出现第二种排序口径时 |
| `party.master` 与 `freight.vehicle_registry` 判成 CORE 是**人判的** | 指南 §6 的 Extension 候选清单里没有它们，而它们对订单是硬依赖（规则 3 反问：核心业务不再成立） | 若将来这两块真的出现"多套实现"（如多套客户档案体系），回来重判 |
| `place.library` 判成 `EXTENSION_IMPL` 而不是 `CORE` | 删掉它订单照样能下（只是要手填地址）、钱与账本完全不受影响（判定规则 3） | 若地点库变成下单的**必经**路径（例如强制从地点库选），它就该回到 Core —— 那时这一行要改 |
| 本页只登记**跨域表归属**，没有登记"谁读了对方的哪个字段" | 粒度再细会变成第二份 schema（与 DOMAIN_BOUNDARIES.md §5 同一条理由） | 出现"读错了字段"的真实事故时再细化 |
| "核心不能被插件替换"这句话**没有**运行期判据 | 它是设计约束，不是运行时可观测的性质 | R4-04/R4-05 的 Add / Replace 演练**间接**证明它（核心修改数 = 0） |

---

## 10. 判据

```text
python _tools/qa/_check_core_extension_boundary.py            # 五条铁律 + Unclassified = 0
python _tools/qa/_reverse_verify_r4_all.py                    # 反向破坏用例（把每条铁律弄坏一次，看它会不会红）
```

判据**自己算**的部分（不是从这一页抄的）：

- 表清单来自 `backend/app/models/**` 的 `__tablename__`（当前 47 张）；
- 事件类型来自源码里 `outbox.enqueue(...)` 的字符串字面量（当前 18 个）；
- `impl` 里的 `文件::符号` 会被拿去源码里核对**真的存在**；
- 扩展实现声明的字段名会拿去核心模型里反查（禁区 12）。

所以这一页过期了会当场报红，而不是安静地骗人。


```
```

```
```
