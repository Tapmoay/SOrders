# 领域边界地图（DOMAIN_BOUNDARIES）

> **第二轮整改 R2-01 的产物**。依据：用户 2026-09-25 交来的方向指南（原文存档
> [ARCHITECTURE_RECTIFICATION_R2.md](ARCHITECTURE_RECTIFICATION_R2.md)）第一节「第二轮先不要改代码：先建立领域地图」。
>
> 施工纪律（指南 §17.1）：**边界优先于文件** —— 不问「这个文件该拆成几个」，先问「这条规则属于谁」。

---

## 0. 这一页解决什么

指南把第二轮的起点定义成一句话：

> 谁拥有规则？谁有权改变状态？谁能写数据？谁只能读取？谁产生事件？谁消费事件？

第一轮（[ARCHITECTURE_RECTIFICATION.md](ARCHITECTURE_RECTIFICATION.md) 阶段 0–13）解决的是「**不要乱**」：
红线、反向验证、端到端常闸、唯一实现、核心区冻结。
第二轮解决的是「**为什么天然不会乱**」—— 靠边界，而不是靠更多规则去围堵。

所以这一页**不是文件夹划分**。`api/` / `services/` / `models/` 是技术分层；
领域边界是**业务事实的所有权**：同一个事实（订单状态、一笔钱、一次结算、一个库存数）必须有一个明确的拥有者，
别的域只能**通过它的命令去改**、只能**读**。

⛔ 这一页**不产出类**：不建 `Repository` / `Manager` / `Factory` / `Adapter` / `Facade` / `Handler`。
指南 §17.7 在这里明确踩了刹车：「抽象的成本本身也是复杂度」。

---

## 1. 怎么读（机器契约）

这一页的主体是下面 15 个 `domain` 块。它们是**声明**，判据
[`_tools/qa/_check_domain_boundaries.py`](../_tools/qa/_check_domain_boundaries.py) 逐条核对它们与代码是否对得上。

```text
name: <英文短名，唯一>
中文名: <给人看的名字>
为什么是它自己的域: <一句话：为什么这些事实归它，而不是并进邻居>
owns: <表名，逗号分隔；可以写 - 表示它不拥有任何表>
commands: <backend/app 相对路径:函数名，逗号分隔；可以写 ->
无命令的理由: <commands 为 - 时必填>
reads: <表名@拥有它的域名，逗号分隔>   ← 只登记跨域读边
events: <事件类型字面量，逗号分隔；可以写 ->
pure_consumer: yes|no                 ← 只有 yes 才允许 owns 为空
```

### 八条铁律（判据钉着的就是这八条）

1. **每张表恰好一个拥有者**。47 张表（`__tablename__` 全量）一个不落：既不许多头，也不许孤儿。
   这是整张地图最贵的一条 —— 一张表有两个「主人」，就等于同一个事实有两处口径。
2. `owns` 里的表名必须是真的（在 `backend/app/models/**` 里找得到）。
3. 每个**命令**必须真的存在：模块文件在、函数名在里面。⛔ 不许写「计划中」的符号。
4. 每个命令**恰好归一个域**。
5. `reads` 只登记**跨域**读边：表必须真的存在、**不属于本域**，且冒号后面那个域名确实拥有这张表。
6. `events` 必须是**代码里真的在产生**的事件类型（扫 `outbox.enqueue(db, "…")` 的字面量）；
   反过来，代码里产生的每一个事件类型也必须**恰好被一个域认领** —— 不然就是没人负责的事实。
7. `owns` 为空只允许 `pure_consumer: yes`（报表域就是这种：事实消费者，不是生产者）。
8. `commands` 为空必须写 `无命令的理由`（≥12 字）—— 例外要留解释，这是第一轮就定下的口径。

### 怎么加一个新域

按上面格式追加一个块 → 在 §2 的规则里说明它在依赖图里的位置 → 跑判据。
判据会拒绝：把已有的表挪走（另一个域当场变孤儿）、写不存在的命令、编一个还没实现的事件类型。

---

## 2. 四条边界规则（机器判不了，但改代码的人必须守）

### 规则 1：跨域只能「调命令」或「读」，不能自己写别人的表

订单送达要生成司机账单、要入账本、要扣库存 —— 这三件事**都不是订单域做的**，
是订单域**调**了钱域 / 结算域 / 库存域的命令。
判据看不出「谁写的」（都在同一个 `Session`、同一个事务里），所以这条靠**命令归属**守：
一个写函数归谁，就看它写谁的表。

### 规则 2：事务只有一个边界 —— `Route → Command → commit` 的那一次 commit

跨域协作全部发生在**同一个数据库事务**里（这是现状，也是对的）。谁负责 commit、失败了怎么办、
重复执行怎么办 —— 逐条写在 [BUSINESS_TRANSACTION_MAP.md](BUSINESS_TRANSACTION_MAP.md)（R2-03）。

### 规则 3：钱只能单向流动（消费方 → 钱契约，绝不反向）

依赖方向见 [MONEY_DEPENDENCY_GRAPH.md](MONEY_DEPENDENCY_GRAPH.md)（R2-03）。一句话：
**报表 / 账本 / 结算 / AI / 订单 都依赖钱；钱不依赖它们任何一个。**

### 规则 4：报表域只读

报表是**事实消费者，不是事实生产者**（指南 §八）。它一条写语句都不许有 ——
落实与判据见 R2-05（`backend/app/services/reports/` 只读边界）。

---

## 3. 域清单

（下面的块是**声明**；每块后面的散文是「为什么」与「本域目前真实的洞」。）

### 3.1 identity —— 身份与授权域

```domain
name: identity
中文名: 身份与授权域
为什么是它自己的域: 账号、角色、令牌版本是「谁」这件事的唯一事实源；权限判据只认库里的角色，所以这一域的写入点必须少而显眼。
owns: users, usage_counters
commands: services.auth_service:issue_token, services.auth_service:bump_token_version, services.auth_service:revoke_tokens_and_sockets, services.login_guard:note_failure, services.login_guard:note_success, services.usage_service:record_usage
reads: -
events: -
pure_consumer: no
```

**为什么 `usage_counters` 在这里**：它按 `(user_id, kind, target_id)` 计数，是「这个人」的属性 —— 换到别的域都会变成一张需要反查用户的外键表。

**被谁读**：几乎所有域。所以它是这张地图最底层的域，⛔ 它不许反过来读任何业务表（`reads: -` 不是偷懒，是声明）。

**本域真实的洞**：用户 / 角色的增删改仍然内联在 `api/v1/users.py` 里。这里只登记**已经存在**的写函数，没有假装已经收敛。

### 3.2 party —— 往来单位档案域

```domain
name: party
中文名: 往来单位档案域
为什么是它自己的域: 货主 / 批发商 / 散客 / 供应商 / 挂账单位是「跟谁打交道」的档案：它们不属于订单（订单只是引用），也不属于钱（钱只是记在它们名下）。
owns: customers, suppliers, arrears_units, shipper_addresses, shipper_contacts, shipper_locations
commands: services.supplier_service:soft_delete_supplier, services.supplier_service:restore_supplier, services.supplier_service:soft_delete_payable, services.supplier_service:restore_payable, services.shipper_contact_service:upsert_boss_contact
reads: users@identity
events: -
pure_consumer: no
```

**⛔ 与钱域的边界**：这一域拥有**档案**（名字 / 电话 / 地址 / 联系人），钱域拥有**金额** —— `supplier_payables` 在钱域，因为它是「欠了多少钱」这个事实，不是「这个供应商是谁」。

**地址为什么不在订单域**：订单只是**引用**一个地址；地址本身可复用（地址库 / 地点库 / 常用线路），而且货主换地址时，历史订单上的地址不该跟着变。

**本域真实的洞**：客户 / 地址 / 联系人的增删改内联在 `api/v1/customers.py`、`api/v1/shipper.py` 里。

### 3.3 catalogue —— 商品目录与定价域

```domain
name: catalogue
中文名: 商品目录与定价域
为什么是它自己的域: 商品、分类、单位换算、专属价、成本历史是「卖什么、卖多少钱」的事实源；订单只在下单那一刻快照它们，之后谁的变更都不许回头改历史单。
owns: products, product_categories, price_rules, product_cost_history, unit_conversions, user_product_visibility
commands: services.cost_history:record_cost
reads: users@identity
events: -
pure_consumer: no
```

**⛔ 成本是快照不是引用**：下单时把 `cost_price` 定格进 `order_products.cost_price_snapshot`，所以「毛利」这件事的原料来自**下单那一刻的目录域**，不是订单域自己算的。

**可见性白名单为什么在这里**：`user_product_visibility` 的语义是「这一件商品给不给这个人看」，判据是商品目录的一部分（`products.py::visible_product_ids` 一处实现）；挪到权限域会变成「权限表里存商品编号」。

**本域真实的洞**：商品 / 定价 / 单位换算的增删改内联在 `api/v1/products.py`、`api/v1/price_rules.py`、`api/v1/unit_conversions.py` 里；只有成本历史有应用层函数。

### 3.4 order —— 订单域

```domain
name: order
中文名: 订单域
为什么是它自己的域: 订单状态、派单归属、订单生命周期是这套系统围绕的中心事实；它连接钱、司机、退货、库存、通知、报表，但**不拥有**其中任何一个。
owns: orders, order_products, order_templates, order_template_categories
commands: commands.order:create_order, commands.order:update_order, services.order_flow:assign_driver, services.order_flow:accept_order, services.order_flow:complete_delivery, services.order_flow:cancel_pending, services.order_flow:recall_dispatch, services.order_flow:mark_returned, services.order_flow:split_order
reads: users@identity, products@catalogue, shipper_addresses@party, driver_billing_rules@settlement
events: orders.assigned, orders.created, orders.delivered, orders.cancelled, orders.recalled, orders.revoked, orders.edited, orders.driver_acked, orders.freight_updated, orders.pending_pool_changed, orders.navigation_filled
pure_consumer: no
```

**这是第二轮第一个真正要重构的域**（指南 §二）。它的命令是唯一被 R2-02 提升成**显式 Command** 的一批，因为「这一单到底能不能派 / 派完要改哪些状态 / 会不会影响计费」现在散在路由里。

**状态只有一个写入口**（第一轮阶段 5 §8 已收口，本轮把它升级成**声明**）：`order.status` 的每一次变化都在 `services/order_flow.py` 里，且都是**条件 UPDATE（CAS）**。

**✅ R2-02 把这个缺口补上了**：原来下单时 `Order(status=PENDING_DISPATCH, …)` 是在**路由里构造对象**写进去的
（`api/v1/orders_lifecycle.py`）—— 按 `\.status\s*=` 这条判据扫是**扫不到它的**。现在 `create_order` / `update_order`
的应用逻辑搬进了 [`app/commands/order.py`](../../backend/app/commands/order.py)，路由只剩 HTTP；
命令登记在上面 `commands:` 那一行里，判据 [`_check_order_commands.py`](../_tools/qa/_check_order_commands.py)
会核对「**API 层一处都没有直接写订单状态**」（反向验证里专门有一条把状态写回路由，看它会不会红）。

**命令的完整形状在 [`backend/app/commands/registry.py`](../../backend/app/commands/registry.py)**：每条命令的
「前置状态 → 目标状态 / 需要的权限点 / 会发出的事件 / 会写的别的域的表」都写在那里，
并且与 `order_flow.py` 里的**条件 UPDATE 逐条对账** —— 声明与代码不一致就报红。
本域的 `commands:` 一行是**归属**（谁拥有它），registry 是**形状**（它允许什么）；两处都要有，判据也会核对两处互相指得到。

**`reads` 里为什么有 `driver_billing_rules`**：派单时必须把司机当次的计费规则**快照**进订单（`orders.driver_rule_snapshot`），否则规则后来被改，历史单的钱会跟着变。

### 3.5 money —— 钱与账本域

```domain
name: money
中文名: 钱与账本域
为什么是它自己的域: 一笔钱只允许有一个数：应收 / 已收 / 欠款 / 红冲 / 支出 / 付款。钱域是这些事实的拥有者，其余域只能读它、或调它的命令。
owns: ledgers, cash_flows, shipper_receipts, expenses, expense_categories, shipper_settlements, shipper_settlement_lines, supplier_payables
commands: services.accounting_service:create_receipt, services.accounting_service:create_expense, services.accounting_service:post_delivery_accounting, services.ledger_sync:sync_ledger_from_delivered_order, services.ledger_sync:sync_order_product_from_ledger, services.supplier_service:pay_supplier
reads: orders@order, users@identity, arrears_units@party, products@catalogue
events: ledger.updated
pure_consumer: no
```

**依赖方向是这一域最重要的事**（指南 §五）：报表 / 账本页 / 结算 / AI / 订单**都**依赖钱契约，钱绝不依赖它们 —— 判据跑的是**模块导入图**，见 [MONEY_DEPENDENCY_GRAPH.md](MONEY_DEPENDENCY_GRAPH.md)。

**`cash_flows` 是所有实际收付的唯一写入点**（模型 docstring 原话）：供应商付款、开销、收款都在它里面 —— 所以「支出」再造一张表就是同一笔钱记两处。

**`supplier_payables` 在钱域而不在档案域**：它是金额事实（欠多少），档案域那边只有「这个供应商是谁」。

**三本账的分工**：`ledgers` 是账本流水，`shipper_receipts` 是收款记录，`shipper_settlements` 是货主核销；口径与上限各自只有一处实现（`services/shipper_settle.py`、`services/accounting_service.py`）。

### 3.6 inventory —— 库存域

```domain
name: inventory
中文名: 库存域
为什么是它自己的域: 库存流水是「货动了没有」的账；它由订单的派单 / 送达 / 撤销 / 退货触发，但库存数本身只由这一域写。
owns: inventory_movements
commands: services.inventory_service:auto_stock_out, services.inventory_service:auto_stock_commit, services.inventory_service:auto_stock_release, services.inventory_service:restock_room, services.inventory_service:restock_returned, services.warehouse:auto_warehouse_inbound
reads: orders@order, products@catalogue
events: -
pure_consumer: no
```

**预占 / 提交 / 释放是三件事，各有各的名**：派单预占（`auto_stock_out`）、送达提交（`auto_stock_commit`）、撤销 / 撤回释放（`auto_stock_release`）—— 名字分开是为了让「哪一步没做」看得出来。

**⛔ 订单域不许直接写库存流水**：送达那条链路调的是这一域的命令。

**到仓入库是独立的一条线**（用户 2026-09-19 拍板）：它不撤销预占、也不改扣减，判据在 `services/warehouse.py` 一处。

**本域真实的洞**：手工出入库（`api/v1/inventory.py`）仍然内联在路由里。

### 3.7 settlement —— 结算域

```domain
name: settlement
中文名: 结算域
为什么是它自己的域: 「这个司机这一趟该拿多少」「这个月的结算单确认了没有」是独立的一组事实：它引用订单与钱，但不等于它们。
owns: driver_bills, driver_settlements, driver_billing_rules, driver_billing_rule_categories, driver_billing_rule_templates
commands: services.accounting_service:generate_piece_bill, services.accounting_service:resync_open_piece_bill, services.accounting_service:confirm_settlement, services.accounting_service:pay_settlement, services.accounting_service:cancel_settlement
reads: orders@order, users@identity
events: -
pure_consumer: no
```

**「司机这单拿多少」只有一处实现**（`services/driver_pay.py`，v3.36 定案）：账单 / 结算页 / 绩效 / 报表四个消费点谁也不许自己抄 `freight_fee`。

**规则必须快照**：派单时把规则定格进订单（`orders.driver_rule_snapshot`），账单另存 `rule_id / rule_name / piece_amount / commission_amount` —— 账单要能**独立复核**「按什么算的」。

**⚠️ 名字的坑**：`driver_billing_rule*` 归**结算域**，但订单域要在派单时**读**它（见 order 的 reads 边）—— 这正是「读边要显式登记」的价值。

**本域真实的洞**：`api/v1/driver_billing_rules.py`（459 行）与 `api/v1/freight_templates.py`（416 行）的写逻辑内联在路由里。

### 3.8 return —— 退货域

```domain
name: return
中文名: 退货域
为什么是它自己的域: 退货申请与退货执行是两条不同的链路（货主只能申请、派单员才能执行），它们有自己的状态，是这个系统里唯一双向的业务。
owns: order_return_requests, order_return_request_lines
commands: services.order_return:return_order, services.order_return_request:submit, services.order_return_request:withdraw, services.order_return_request:reject, services.order_return_request:fulfill, services.order_return_request:close_by_direct_return
reads: orders@order, users@identity, products@catalogue
events: returns.requested, returns.rejected, returns.request_closed, returns.done
pure_consumer: no
```

**两个权限点是刻意的**（`ORDER_RETURN_REQUEST` vs `ORDER_RETURN`）：货主按下的是「申请」（不碰账本、不碰库存、不改订单状态），派单员按下的是「真的退」（红冲营收、回补库存、可能退现）。合成一个，货主按一下就能改自己的应收和公司库存。

**直连退货会自动关闭那张申请**（`close_by_direct_return`）：否则同一批货会有两条「已经退了」的记录。

**它跨三个域**：读订单域的单、调钱域的红冲、调库存域的回补 —— 是这张地图里跨域边最多的一条链路，所以 R2-03 的《跨域事务地图》第一个写它。

### 3.9 notification —— 消息域

```domain
name: notification
中文名: 消息域
为什么是它自己的域: 站内信是用户看得见的事实（谁在什么时候收到了什么），它与「推送」不是一回事：推送是投递方式，站内信是数据。
owns: notifications
commands: services.message_center:create_message
reads: users@identity
events: notifications.created, notifications.unread_changed
pure_consumer: no
```

**⛔ 消息不能因为搬了投递方式而变慢**：站内信是持久数据，所以发件箱有一条**快速通道**（`outbox.drain`）在响应之后立刻投一次，worker 每 2 秒扫一遍作兜底 —— 理由写在 `core/outbox.py::drain` 的 docstring 里（13 条既有用例当时当场红）。

**收件人过滤的口径**：派单员不带 `recipient_id` 查消息时**不加收件人过滤**（消息中心全局视图），但「动某一条」（标记已读 / 删除）只允许动自己的，别人的一律 404。

**本域真实的洞**：群发 / 价格通知（`api/v1/notifications.py`）的编排逻辑内联在路由里。

### 3.10 freight —— 运费模板与车辆域

```domain
name: freight
中文名: 运费模板与车辆域
为什么是它自己的域: 运费模板 / 分类 / 车辆是「怎么定价、用哪台车」的主数据；它们被订单引用，但不随订单变化。
owns: freight_categories, freight_templates, freight_template_drivers, freight_template_categories, vehicles
commands: -
无命令的理由: 这一域的增删改**全部内联在** api/v1/freight_templates.py、api/v1/freight_categories.py、api/v1/vehicles.py 的路由里，还没有应用层函数 —— 如实登记，不假装已经有。
reads: users@identity
events: -
pure_consumer: no
```

**为什么单独一个域**：模板 / 分类 / 车辆三张表是一套（模板按分类分组、模板可绑司机、订单按模板报价），并进目录域会让「卖什么」和「怎么运」混成一张表。

**它是 order 的一条隐式依赖**：订单的运费来自模板（`services/freight_pricing.py::quote_for`，只读）—— 但那条边没有经 `driver_billing_rules` 那样登记在 order 的 reads 里，因为它是**下单时**的取值，不是一个跨域调用。

### 3.11 place —— 地点库域

```domain
name: place
中文名: 地点库域
为什么是它自己的域: 「我的地点 / 常用线路 / 地点分类」是用户自己攒的位置资产，按登录人隔离；地址档案（货主填的收货地址）是另一回事，所以在 party 域。
owns: places, place_user_usage, place_categories
commands: services.place_service:upsert_place, services.place_service:note_place_use, services.place_service:share_location, services.place_service:delete_place, services.place_service:demote_place, services.place_service:remember_order_address, services.place_service:attach_order_photo, services.place_service:apply_place_update
reads: users@identity, orders@order
events: -
pure_consumer: no
```

**`place_user_usage` 是历史遗迹**：它已经被通用版的 `usage_counters` 取代（旧表数据由 `core/schema_bootstrap.py` 搬进新表，搬完旧表保留为备份、**不再读写**）。它在这里登记的唯一理由是：**它还占着一张表，规则 1 要求每张表都有主人**。

**⛔ 别两边各写一份**：同一个动作记两处计数必然对不上，这是 `usage.py` 那段 docstring 的原话。

### 3.12 audit —— 审计域

```domain
name: audit
中文名: 审计域
为什么是它自己的域: 操作日志是「谁在什么时候对哪张单做了什么」的事实；它是只增不改的，任何域都可以往里写一条，但格式与落库只有一处实现。
owns: operation_logs
commands: services.operation_log_service:write_log
reads: users@identity
events: -
pure_consumer: no
```

**它是全项目唯一一个「所有域都能调」的写命令**：这正是它单独成域的理由 —— 若挂在订单域下，钱 / 权限 / 结算的审计行就要「跨域调订单域」，那会把依赖方向搞乱。

**动作码的词汇表在 `models/enums.py::OperationAction`**（全项目共用的取值），而审计页的中文名在 Android 的 `ReportCenter.kt::actionLabel` —— 两边对不上时判据 `_tools/ai/_check_action_labels.py` 会红。

**它是「订单全链路可追溯」的最后一跳**：`operation_logs.request_id` 把一条 HTTP 请求与它产生的审计行串起来（R2-06 的观测性）。

### 3.13 platform —— 平台设施域

```domain
name: platform
中文名: 平台设施域
为什么是它自己的域: 事务发件箱与导出任务是「机制」不是「业务」：它们不表达任何业务事实，只保证事实**送得到**。单独成域是为了让别的域不必知道投递是怎么做的。
owns: outbox_events, ledger_export_jobs
commands: core.outbox:enqueue, core.outbox:mark_sent, core.outbox:mark_failed
reads: -
events: -
pure_consumer: no
```

**`enqueue` 在这里、而不在任何业务域**：入队与业务写同一个事务，但「事件怎么发出去、失败怎么退避」是所有域共用的机制。

**`ledger_export_jobs` 是导出任务**（异步产物），放这里而不是钱域，是因为钱域只用它、不管它怎么落盘。

**多实例就绪的关键一处**：worker 的取数与标记（`claim` / `mark_sent` / `mark_failed`）必须在多实例下不重复派发 —— 见 R2-06。

### 3.14 ai —— AI 集成域

```domain
name: ai
中文名: AI 集成域
为什么是它自己的域: AI 的调用量计数是一条独立的业务事实（今天问了多少次、确认了多少次写），它与任何一个业务域都不重合。
owns: ai_call_daily
commands: -
无命令的理由: AI 侧没有自己的写路径 —— 它调用的就是人点的那条 REST 端点（见 R2-02 的「同一条命令」判据），所以这一域只登记计数，不登记业务命令。
reads: users@identity
events: -
pure_consumer: no
```

**⛔ 这一域刻意很小**：指南 §十二 明确「AI 第二轮不要优先做更多能力，要做更统一」。AI 不该长出自己的权限系统、自己的写路径。

**两个指标**：`sorders_ai_calls_today` 与 `sorders_ai_write_confirmed_today`（`core/metrics.py`），来源是 App 上报 + `operation_logs.origin` 那一维。

### 3.15 reporting —— 报表域

```domain
name: reporting
中文名: 报表域
为什么是它自己的域: 报表不拥有任何事实 —— 它把别的域的既成事实**读**出来做聚合。所以它是一个纯消费者，这个「什么都不拥有」本身就是它的边界。
owns: -
commands: -
无命令的理由: 报表是事实消费者，不是事实生产者（指南 §八）：它只允许 SELECT / JOIN / GROUP BY，一条写语句都不许有。一个「报表命令」这个概念本身就是错的。
reads: orders@order, order_products@order, ledgers@money, cash_flows@money, shipper_settlements@money, products@catalogue, users@identity, driver_bills@settlement
events: -
pure_consumer: yes
```

**这是这一轮唯一一个「owns 为空」的域**：判据规则 7 允许它，前提是 `pure_consumer: yes`。

**它的读边最宽（8 条），一条写边都没有** —— 这就是指南 §九 说的「先做 Query Boundary，不要马上上复杂 Read Model」。

**R2-05 会把它钉成结构**：`backend/app/services/reports/` 下的模块在 **AST 层面**不许出现任何写动词，也不许 `import` 任何写服务。

---

## 4. 域之间的形状（定性，不重复上面的数据）

```text
                    identity（谁）
                        ↑ 被所有域读
                        │
   party ──────┐        │        ┌────── catalogue
  （跟谁）      │        │        │      （卖什么）
                ↓        │        ↓
              ┌───────── order ─────────┐
              │    （订单：中心事实）    │
              │         │               │
      reads → │         │ commands      │ ← events
              ↓         ↓               ↓
        settlement    money          freight / place
        （司机拿多少） （一笔钱一个数）
              ↑         ↑
              └─ inventory ─┘        return（两条链路）
                        │
                        ↓
              notification / audit / platform
                        │
                        ↓
                   reporting（只读，什么都不拥有）
```

**读这张图的三条**：

1. **箭头向下 = 被依赖**。`identity` 在最上，`reporting` 在最下 —— 这与「谁读谁」的方向一致：
   报表读所有人，没有人读报表。
2. **`order` 的箭头最多**，但它的**出边全是 commands**（调别人的命令），没有一条是「自己写别人的表」。
3. **`money` 与 `settlement` 之间没有边**：钱域不知道「司机拿多少」，结算域不知道「这一笔钱记在哪本账」——
   这正是 `money_contract` 存在的理由：钱侧把符号**转出**，结算侧按契约取，谁也不 import 谁的内部。

---

## 5. 这一页**没有**解决的事（如实列着）

| 没做的 | 为什么 | 什么时候该做 |
|---|---|---|
| 除订单域以外，其它域的写逻辑仍然内联在路由里 | 指南 §二 明确「**不要第一步就把 orders.py 拆成十个文件**」，第二轮的第一个重构目标**只有订单域** | 订单域的命令层跑稳一轮之后，按同样的形状逐个域收 |
| `freight` 域一条命令都没有 | 如实登记了理由（见 3.10）—— 不发明不存在的函数来凑数 | 与上一条同时 |
| 「跨域写」在机器上判不出来 | 所有域共用一个 `Session` 与一个事务，静态看不出「谁写的」 | 若将来出现跨进程的域（真的上 MQ），那时才需要 |
| 读边只登记了跨域**表**读，没有登记「读了对方的哪个字段」 | 粒度再细会变成第二份 schema，维护成本大于收益 | 出现「读错了字段」的真实事故时再细化 |

---

## 6. 判据

```text
python _tools/qa/_check_domain_boundaries.py          # 八条铁律
python _tools/qa/_reverse_verify_domain_boundaries.py # 反向验证（把每条铁律弄坏一次，看它会不会红）
```

判据**自己算**的部分（不是从这一页抄的）：表清单来自 `backend/app/models/**` 的 `__tablename__`；
命令是否存在来自源码里的 `def`；事件类型来自 `outbox.enqueue(...)` 的字符串字面量。
所以这一页过期了会当场报红，而不是安静地骗人。
