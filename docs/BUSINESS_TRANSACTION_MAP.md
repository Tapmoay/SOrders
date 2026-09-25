# 跨域事务地图（BUSINESS_TRANSACTION_MAP）

> **第二轮整改 R2-03 的产物**。依据：方向指南（[ARCHITECTURE_RECTIFICATION_R2.md](ARCHITECTURE_RECTIFICATION_R2.md)）
> 第六节「把 Order / Money / Inventory / Settlement 之间的关系说清楚」。
>
> 它回答的是**一笔业务事务到底发生了什么**：谁负责？什么时候发生？是否同一个 DB transaction？
> 失败怎么办？重复执行怎么办？

---

## 0. 为什么要有这一页

指南的原话：

> 这一步很重要。因为它会把现在散落在 service 中的「**隐式协作**」变成**显式业务契约**。

举例来说，「送达」这一下按下去，实际发生的是：

```text
  CompleteOrder
   ├─ Order      → DELIVERED        （条件 UPDATE，唯一写入口）
   ├─ Ledger     → 入账             （钱域）
   ├─ Inventory  → 提交预占         （库存域）
   ├─ Warehouse  → 到仓入库         （库存域，独立的一条线）
   ├─ DriverPay  → 生成应付账单     （结算域）
   ├─ Audit      → 写操作日志       （审计域）
   └─ Event      → orders.delivered / ledger.updated（平台域，与业务同一个事务）
```

这张图**以前只存在于读过那 200 行的人的脑子里**。

---

## 1. 怎么读（机器契约）

主体是下面 10 个 `txn` 块。判据
[`_tools/qa/_check_business_transactions.py`](../_tools/qa/_check_business_transactions.py) 逐条核对它们**与真实调用图**：

```text
name: <稳定标识>
中文名: <给人看的名字>
entry: <入口，backend/app 相对的点分模块:函数>      ← 业务事务的边界：从哪个端点开始
participants: <参与者的 模块:函数，逗号分隔>        ← ⭐ 必须都能从入口沿调用链走到
same_db: yes|no                                   ← 是否同一个数据库事务
guards: <守卫机制词表里的名字，逗号分隔>
failure: <失败了会怎样>
repeat: <重复执行会怎样>
why: <一句话：为什么它是**一条**事务，而不是两条>
```

### 四条铁律

1. **入口与参与者都必须真实存在**（'`模块:函数`' 对得上源码里的 `def`）；
2. ⭐ **可达性**：每个参与者都必须能从入口沿调用链走到 —— 这条把地图钉在**真实调用图**上（AST，跨文件）；
   写一个`看起来应该有`的参与者，判据当场报红。
3. ⭐ **同一事务**：声明 `same_db: yes` 的事务，入口那个模块里必须有 `db.commit()`（谁提交的要说得出来）；
4. ⭐ **守卫机制**词表 → 代码形状：`row_lock` → `lock_order_row(` 或 `with_for_update(`；
   `cas` → 条件 UPDATE；`outbox_same_txn` → `enqueue(`；`soft_delete` → `is_deleted` / `deleted_at`。
   声明了守卫却在**入口可达的那些函数体**里找不到那个形状 → 报红
   （**守卫是`写在地图上的承诺`，不是形容词**）。
   ⚠️ 表级约束（唯一索引）**不在词表里**：它不在任何函数体里，判据做不到的事就不假装做得到 ——
   那类保证写在散文里（例：`driver_bills` 上同一张单只能有一条应付明细）。

⛔ 反空转：事务条数、解析出的函数数（≥400）、调用边数（≥800）都要达标 ——
调用图解析坏了（例如全被解析成空）时判据要先喊，而不是安静地全绿。

---

## 2. 事务清单

### 2.1 订单域的七条

#### 下单（货主自己下单 / 派单员代理下单）

```txn
name: CreateOrder
中文名: 下单（货主自己下单 / 派单员代理下单）
entry: api.v1.orders_lifecycle:create_order
participants: commands.order:create_order, services.place_service:remember_order_address, services.usage_service:record_usage, services.operation_log_service:write_log, core.outbox:enqueue
same_db: yes
guards: outbox_same_txn
failure: 命令层抛 CommandError（默认 400 + 一句人话）→ 路由翻成 HTTPException → 事务整体回滚：订单、地点、常用度计数、事件一条都不落
repeat: 每次下单都是一张新单（order_no 由服务端生成），没有「重复执行」语义；客户端重试会多出一张单，靠收货人核对后在回收站软删
why: 它是唯一一条**从零开始**的事务：不依赖任何前置状态，但要同时落下订单、地点、常用度与两条事件 —— 拆成两条事务就必然出现「单落了、事件没发」
```

**它是 R2-02 搬出来的那一条**：应用逻辑现在住 `app/commands/order.py`，路由只剩 HTTP。

⛔ 初始状态 `PENDING_DISPATCH` 写在**命令层**（不再是路由里构造对象）—— 判据 `_check_order_commands.py` 钉着`api/**` 一处都不许有。

#### 派单（把待派单派给某位司机）

```txn
name: AssignOrder
中文名: 派单（把待派单派给某位司机）
entry: api.v1.orders_assignment:assign_order
participants: services.order_flow:assign_driver, core.outbox:enqueue
same_db: yes
guards: cas, row_lock, outbox_same_txn
failure: assign_driver 抛 ValueError（状态不对 / 隔离区 / 司机停用 / 覆盖值不生效）→ 路由回滚成 4xx，订单一个字段都没动
repeat: **刻意不去重**（不传 dedupe_key）：派单是「再派一次就该再响一次」；但状态那一格是 CAS，改到 0 行的人直接出局 —— 重复提交不会派给两个人
why: 「改状态」与「通知司机」必须同生共死：状态没改成功就不该响，改了就必须响（发件箱与业务同一个事务）
```

**计费规则快照就在这一步**：派单时把 `driver_rule_snapshot` 定格进订单 —— 规则后来被改，已经派出去的单的钱不能跟着变。

**唯一的派单写入点**也是唯一的一道闸：它校 `is_active`（AI 的司机名册没有过滤，只有这里有）。

#### 司机接单

```txn
name: AcceptOrder
中文名: 司机接单
entry: api.v1.orders_delivery:driver_ack_view
participants: services.order_flow:accept_order, core.outbox:enqueue
same_db: yes
guards: cas, outbox_same_txn
failure: 状态不是「已派单」/ 不是派给这个人 → ValueError → 400；CAS 抢先则报「刚刚被改过，请刷新」
repeat: 司机手滑点两下是**最常见**的重复：第二次 CAS 改到 0 行 → 直接拒绝，不会把已撤销的单覆盖回 ACCEPTED
why: 接单只改状态（没有钱、没有库存），但它与派单员的撤销/撤回是并发的 —— 所以它必须是一条走 CAS 的命令，而不是一个赋值
```

**为什么它单独成命令**：它是唯一一条**由司机本人**发起、且要求「必须是派给我的那一张」的跃迁。

#### 送达（副作用最多的一条）

```txn
name: CompleteOrder
中文名: 送达（副作用最多的一条）
entry: api.v1.orders_delivery:complete_order
participants: services.order_flow:complete_delivery, services.ledger_sync:sync_ledger_from_delivered_order, services.inventory_service:auto_stock_commit, services.warehouse:auto_warehouse_inbound, services.accounting_service:post_delivery_accounting, services.operation_log_service:write_log, core.outbox:enqueue
same_db: yes
guards: cas, row_lock, outbox_same_txn
failure: 抛 ValueError（照片不合规 / 非本单司机 / 状态不对）→ 400 且**一处副作用都不留**；账务钩子返回的警告逐条写进操作日志（不许静默吞）
repeat: CAS 改到 0 行 → 拒绝。⚠️ 这一条**必须**是 CAS：SQLite 不认 FOR UPDATE，本地两个并发 complete 实测生成过**两条 60 元的司机账单**
why: 五件事（状态 / 账本 / 库存 / 到仓入库 / 司机应付）必须同一个事务：任何一件单独成功，钱与货就对不上了
```

**顺序有讲究**：货损录入必须在`auto_warehouse_inbound`**之前** —— 入库那条线要读 `op.damage_quantity` 才能扣掉坏掉的那几件（原来排在后面，入库永远看不到货损、库存虚增）。

**到仓入库是独立的一条线**（用户 2026-09-19 拍板）：它不撤销预占、也不改扣减 —— 两个决策各算各的。

#### 撤销（把还没发生的单作废）

```txn
name: CancelOrder
中文名: 撤销（把还没发生的单作废）
entry: api.v1.orders_delivery:cancel_order
participants: services.order_flow:cancel_pending, services.inventory_service:auto_stock_release, services.operation_log_service:write_log, core.outbox:enqueue
same_db: yes
guards: cas, outbox_same_txn
failure: 状态不在（待派单 / 已派单）→ ValueError → 400；CAS 抢先则报「刚刚被别的操作改过」
repeat: CAS 改到 0 行 → 拒绝。撤销 × 接单并发时，无条件赋值会把已撤销的单覆盖回 ACCEPTED，而预占已经释放 → **单子复活但库存永远不扣**
why: 「作废 + 释放预占 + 通知」必须同一事务：只作废不释放会让库存永远被占着，只释放不作废会让单子还在池子里
```

**它不动钱**（这正是与退货的差别）：撤销把还没发生的单作废，账本上本来就什么都没有。

#### 撤回派单（把单从司机手里收回来再派给别人）

```txn
name: RecallOrder
中文名: 撤回派单（把单从司机手里收回来再派给别人）
entry: api.v1.orders_assignment:recall_order
participants: services.order_flow:recall_dispatch, services.inventory_service:auto_stock_release, services.operation_log_service:write_log, core.outbox:enqueue
same_db: yes
guards: cas, outbox_same_txn
failure: 状态不在（已派单 / 已接单）→ ValueError → 400；撤回 × 送达并发时 CAS 改到 0 行 → 拒绝（否则**同一张单能被再派一次、库存与货损各记两次**）
repeat: CAS 改到 0 行 → 拒绝；撤回后回到待派池，可以再派给另一个人（这是它的语义，不是重复执行）
why: 撤回要同时做三件事：清司机、清逐单覆盖值、释放预占 —— 漏掉逐单覆盖值的后果是**下一任司机按上一任的数字拿钱**
```

**操作日志里带派单前快照**（`order_snapshot_for_log`）：撤回之后单子回到待派池，出问题时只能靠那份快照还原当时的样子。

#### 拆单（一条命令产生 N 张子单）

```txn
name: SplitOrder
中文名: 拆单（一条命令产生 N 张子单）
entry: api.v1.orders_assignment:split_order_endpoint
participants: services.order_flow:split_order, services.inventory_service:auto_stock_release, services.operation_log_service:write_log, core.outbox:enqueue
same_db: yes
guards: cas, outbox_same_txn
failure: 比例非法 / 订单无明细 → ValueError → 400；父单 CAS 抢不到 → 409「刚刚被别的操作改过，请刷新」
repeat: 父单的 CAS 就是它的幂等闸：抢不到的人在建子单**之前**就出局（原来靠子单 order_no 的唯一约束兜底，报出来的是「重名了、换一个」）
why: 父单作废 + N 张子单落地 + 全部事件必须同一事务：中途失败会留下一批`有子单没父单`的孤儿
```

**子单要带走成本与单位快照**：不带成本快照子单毛利按 0 算（虚高），不带单位快照司机照着「件」数「箱」的货。

#### 退货执行（派单员按下「真的退」）

```txn
name: ReturnOrder
中文名: 退货执行（派单员按下「真的退」）
entry: api.v1.orders_return:return_order_endpoint
participants: services.order_return:return_order, services.inventory_service:restock_returned, services.operation_log_service:write_log, core.outbox:enqueue
same_db: yes
guards: cas, outbox_same_txn
failure: 超退 / 状态不对 → OrderReturnError → 400；整单退完那一步的 CAS 抢不到 → 「刚刚被别的操作改过」
repeat: **逐行封顶**（max_returnable）+ 账本红冲行有唯一约束；整单退完的状态跃迁走 CAS —— 两次点「退货」不会红冲两次
why: 红冲营收 + 回补库存 + 可能退现 + 订单转「已退货」是本系统里**唯一双向**的一笔事务，拆开就等于允许`钱退了货没回`这种中间态
```

**它是跨域边最多的一条**：读订单域的单、调钱域的红冲、调库存域的回补 —— 指南 §六 点名的那种`隐式协作`，在这里被写成了显式的参与者清单。

**直连退货会自动关闭那张申请**（`close_by_direct_return`）：否则同一批货会有两条「已经退了」的记录。

### 2.2 钱域的两条

#### 收款 / 核销（账本里记一笔收到的钱）

```txn
name: ReceivePayment
中文名: 收款 / 核销（账本里记一笔收到的钱）
entry: api.v1.ledger:create_receipt_endpoint
participants: services.accounting_service:create_receipt, core.outbox:enqueue
same_db: yes
guards: outbox_same_txn
failure: 逐单核销金额与所选订单合计不等 / 订单不属于该客户 → 400，一行流水都不写
repeat: 逐单核销必须绑订单且金额与 line_total 合计**相等**；滚动收款不绑订单 —— 两条路径的判据不同，重复提交会多一条收款记录（靠人工冲销）
why: 「钱记成」与「通知货主/司机」必须同一事务：钱没记成就绝不通知；钱记成了就一定会发（发件箱与业务同一个事务）
```

*

*

⛔

 

不

绑

订

单

时

绝

不

能

发

默

认

的

 

`

i

t

e

m

i

z

e

d

`

*

*

（

后

端

会

 

4

0

0

「

逐

单

核

销

需

绑

定

订

单

」

）

—

—

 

这

是

客

户

端

最

容

易

踩

的

一

脚

。

*

*

现

金

流

水

是

逐

单

生

成

的

*

*

：

滚

动

收

款

不

写

现

金

流

水

，

钱

只

在

 

`

s

h

i

p

p

e

r

_

r

e

c

e

i

p

t

s

`

 

里

。

#### 司机结算单的确认 / 付款 / 作废

```txn
name: PaySettlement
中文名: 司机结算单的确认 / 付款 / 作废
entry: api.v1.driver_settlements:settlement_action
participants: services.accounting_service:confirm_settlement, services.accounting_service:pay_settlement, services.accounting_service:cancel_settlement
same_db: yes
guards: cas
failure: 金额与明细合计不等 / 状态不对 → 400；CAS 抢不到 → 拒绝（两个人在同一天确认同一张结算单）
repeat: 三个动作各是一条条件 UPDATE（`WHERE status = 期望值`）：改到 0 行就出局 —— 重复点「付款」不会付两次
why: 确认 / 付款 / 作废**分三个动作**而不是一个：风险档位不同（确认与付款撤不回来是 HIGH，作废只动草稿是 MEDIUM），合成一个只能取最高档、用户会学会无视红牌
```

**账单侧还有一道唯一索引**：`driver_bills` 上同一张单只能有一条应付明细 —— 与这里的 CAS 是两道独立的闸。

---

## 3. 这一页**没有**解决的事

| 没做的 | 为什么 | 什么时候该做 |
|---|---|---|
| 只登记了 10 条事务（订单域 8 条 + 钱域 2 条） | 商品 / 客户 / 地址 / 供应商那些是**单域**动作（只写一个域的表），不是跨域事务 | 出现跨域协作时再补 —— 判据会要求补上的那条也**可达** |
| 「失败怎么办」是散文，不是机器判据 | 判据只能证明「参与者可达 / 有守卫 / 有提交点」；具体失败语义要人读 | 真出事时按这一页反查，把那次事故写成一条新判据 |
| 没有画时序图 | 一张会腐烂的图比没有图更糟（本仓库在过期地图上栽过） | 需要给别人讲的时候现画，别提交 |

---

## 4. 判据

```text
python _tools/qa/_check_business_transactions.py              # 十条事务与真实调用图对账
python _tools/qa/_check_business_transactions.py --show AssignOrder   # 打印某条的**真实可达集合**（排障用）
python _tools/qa/_reverse_verify_business_transactions.py     # 反向验证
```

调用的可达性用的是 **AST 调用图**（跨文件、跨模块，含 `from app.core import outbox; outbox.enqueue()` 这种属性调用）——
也就是说：**地图上写的每一个参与者，代码里都必须真的被调到**。
