# SOrders 第二轮整改报告

> **方向指南**：`C:\Users\Optimistic\Desktop\ppdd.md`（已归档 `docs/ARCHITECTURE_RECTIFICATION_R2.md`，19122 字节）
> **生成**：2026-09-26 ｜ **分支** p ｜ **代码改动区间** `93865c0`（第一轮报告）… `fb88459`（本报告自己的提交在 `fb88459` 之后，不计入改动量）
> **口径**：这份报告里的每一个数字，都是当场跑出来的命令打印出来的，不是回忆、不是估算。每条都附了产生它的命令。

---

## 0. 读之前先知道三件事

**① 判据是唯一的裁判。** 这一轮的「做完了」不是我说的，是命令说的。每条里程碑下面都写了它的判据脚本，你可以随时重跑。

**② 每条判据自己也被反向验证过。** 做法是：往代码或文档里**注入一种具体的破坏** → 判据必须当场报红 → 还原 → 必须全绿。
这轮 9 个新判据一共跑了 **80 种注入**，全部成立。只绿不红的判据等于没有判据 —— 这是第一轮反复栽跟头换来的规矩。

**③ 一个必须先说清的前提**：跑完反向验证之后，**本机后端必须重启**，否则 `_check_all.py` 里那条「本机后端跑的是旧代码」会红
（反向验证逐个注入再还原，会把文件的 mtime 全部刷新）。这份报告的 **112/112 是重启后端之后重新跑的**。

---

## 1. 结论与总账

指南给的 **6 个里程碑（R2-01 ~ R2-06）全部落地**，加上贯穿层里能做的 3 条（Capability / 钱的依赖方向 / AI 与后端同源）。

改动量（**去掉机器生成的契约快照**）：

| 范围 | 文件 | 增 | 删 |
| --- | --- | --- | --- |
| 全部（含 3 份契约快照） | 97 | +86787 | −896 |
| **实际改动量**（不含快照） | **94** | **+9066** | **−896** |
| 　其中 `backend/app`（业务代码） | 27 | +1765 | −805 |
| 　其中 `_tools`（判据与工具） | 56 | +4715 | −41 |
| 　其中 `docs` | 9 | +2569 | −42 |

命令：`git diff --numstat 93865c0 fb88459`（那 3 份快照共 +77721 行，是机器生成的契约证据，不算人的改动量）

**核心数字一览**（每条都能单独重跑）

| 事项 | 数字 | 产生它的命令 |
| --- | --- | --- |
| 全量静态检查 | **112/112** | `python _tools/qa/_check_all.py` |
| 后端用例 | **1015 passed**（122.94s） | `cd backend; python -m pytest -q` |
| 新增判据 / 反向验证 | 9 份 / 9 份（80 种注入全部成立） | `python _tools/qa/_reverse_verify_*.py` |
| 领域边界 | 15 域 / 47 张表有主 / 57 命令 / 31 跨域读边 / 18 事件 | `_check_domain_boundaries.py` |
| 订单命令 | 9 条 / 7 处 CAS / **API 直写状态 0 处** | `_check_order_commands.py` |
| 跨域事务 | 10 条 / 调用图 882 函数 1689 边 / 契约转发 32 处 | `_check_business_transactions.py` |
| 钱依赖图 | 212 模块 / 1077 依赖 / 12 钱模块 / **例外 0 条** | `_check_money_dependency.py` |
| 发件箱幂等 | 18 事件 / 聚合根 17+1 / 带幂等键 16 处 | `_check_outbox_idempotency.py` |
| 报表只读 | 11 文件 / 39 函数 / **例外 0 条** | `_check_report_boundary.py` |
| 多实例 | 10 道门（**已过 6 / 没做 4**）/ 核 20 串代码形状 | `_check_multi_instance_readiness.py` |
| 全链路 trace | 6 段 / 32 列 / 只读 | `_check_traceability.py` |
| 能力注册表 | 26 条 / **有执行点 26 条 / 仅声明 0 条** | `_check_capability_registry.py` |
| 体内角色门槛棘轮 | 35 处（上限 36） | `_check_inline_role_gates.py` |
| 迁移版本 | 7 | `cd backend; python -m app.migrations status` |
| 提交 | 18 个（`ae87211` … `fb88459`） | `git log --oneline 93865c0..fb88459` |

---

## 2. R2-01 领域边界地图

### 指南要什么（§一）

> 不要再从文件夹划分模块。直接从**业务事实所有权**划分。
> 对每个 Domain 写四件事：Owns / Commands / Reads / Events。
> 这里不要急着设计类名。你现在最缺的是**业务边界事实**，不是更多代码抽象。

### 我改了什么

| 产物 | 说明 |
| --- | --- |
| `docs/DOMAIN_BOUNDARIES.md`（306 行 / 28900 字节） | 15 个域的 Owns / Commands / Reads / Events，写成 ```domain 围栏块（给人读，也给判据读） |
| `_tools/qa/_domain_map.py`（新增） | 共享解析器：域块、真实表名、真实事件名、清单拆分、命令形状 |
| `_tools/qa/_check_domain_boundaries.py`（276 行） | 判据，10 组 |
| `_tools/qa/_reverse_verify_domain_boundaries.py`（223 行） | 反向验证，13 种破坏 |

**15 个域**（指南点名 9 个，我按业务事实拆成 15 个）：

`identity` 身份与授权 ／ `party` 往来单位档案 ／ `catalogue` 商品目录与定价 ／ `order` 订单 ／
`money` 钱与账本 ／ `inventory` 库存 ／ `settlement` 结算 ／ `return` 退货 ／ `notification` 消息 ／
`freight` 运费模板与车辆 ／ `place` 地点库 ／ `audit` 审计 ／ `platform` 平台设施 ／ `ai` AI 集成 ／ `reporting` 报表

比指南多出来的 6 个（party / catalogue / freight / place / audit / platform）不是我加戏：
这 6 条「谁拥有这条事实」在代码里本来就有明确主人，硬塞进那 9 个域会让「47 张表每张恰好一个主人」这条判据说不清。

### 怎么改的

判据不读「文档自己说自己」，而是**拿文档里的名字去源码里找**：

```text
每一个表名   → 去 models/ 里找这张 SQLAlchemy 表真实存在吗
每一条命令   → 去代码里找这个形状真的存在吗
每一个事件名 → 去 core/outbox.py 的登记表里找它真的会被入队吗
每一条读边   → 必须是**跨域**的，且目标域真的存在
```

### 为什么这么改

这张表要解决的问题是：以前问「订单状态谁说了算」，答案散在四五处，而且**任何一处改错都不会报错**。
现在它是一个可以被机器核对的事实。

### 依据

```text
$ python _tools/qa/_check_domain_boundaries.py
领域边界：15 个域 / 47/47 张表有主 / 57 条命令 / 31 条跨域读边 / 18/18 个事件有主
  ✅ 10 组判据全部通过：每张表恰好一个拥有者、命令与事件都在代码里对得上、读边是跨域的且指对了域、空值的例外都留了解释。

$ python _tools/qa/_reverse_verify_domain_boundaries.py
  ✅ 13/13 全部成立：孤儿表 / 双主表 / 假表名 / 假命令 / 假事件 / 无主事件 / 自读边 /
     错域读边 / 敷衍理由 / 逃逸的纯消费者 / 坏掉的围栏 都会被抓到
```

提交：`ae87211`（+1996 行，5 个文件）

---

## 3. R2-02 订单命令 / 状态边界

### 指南要什么（§二 / §三）

> Route → Command → Order Application Logic → Order Domain Rule → Persistence
> **不要第一步就把 orders.py 拆成十个文件。那只是物理拆分。**
> 订单状态必须成为真正的唯一写入口；
> ⛔ 不要为了唯一入口而建立一个巨大万能函数（`transition(order, action, context, anything...)`）。

### 我改了什么

| 产物 | 说明 |
| --- | --- |
| `backend/app/commands/order.py`（275 行，新增） | `create_order` / `update_order` / `resolve_exception`；统一的 `CommandError(detail, status_code=400)` |
| `backend/app/commands/registry.py`（149 行，新增） | **9 条命令的声明表**：名字 / 域 / 实现位置 / 权限 / 前置状态 / 目标状态 / 事件 / 跨域副作用 / 为什么它是一条独立命令 |
| `backend/app/api/v1/orders_lifecycle.py` | 瘦成纯 HTTP：**+18 / −224**，现在 202 行（改前 408 行） |
| `_tools/qa/_check_order_commands.py`（296 行，新增） | 判据，10 组 |
| `_tools/qa/_reverse_verify_order_commands.py`（234 行，新增） | 反向验证，14 种破坏 |

9 条命令（从注册表打出来的原始输出）：

```text
order.create   ()                            -> PENDING_DISPATCH  ORDER_CREATE
order.assign   (PENDING_DISPATCH)            -> DISPATCHED        ORDER_DISPATCH
order.accept   (DISPATCHED)                  -> ACCEPTED          ORDER_COMPLETE_DRIVER
order.complete (ACCEPTED)                    -> DELIVERED         ORDER_COMPLETE_DRIVER
order.cancel   (PENDING_DISPATCH,DISPATCHED) -> CANCELLED         ORDER_CANCEL_SHIPPER/DISPATCHER
order.recall   (DISPATCHED,ACCEPTED)         -> PENDING_DISPATCH  ORDER_RECALL
order.split    (PENDING_DISPATCH)            -> CANCELLED         ORDER_EDIT
order.return   (DELIVERED)                   -> RETURNED          ORDER_RETURN
order.edit     (PENDING_DISPATCH,DISPATCHED,ACCEPTED) ->（不改状态）ORDER_EDIT
```

### 怎么改的（这一块最关键的设计）

指南点了名要 assign / accept / complete / cancel / recall 这些**显式命令**，也点了名**不许**做万能 transition。
我的做法是：**命令的「说法」和「实现」分开**。

```text
registry.py 声明：这条命令叫什么、从什么状态到什么状态、要什么权限、会发什么事件
                ↓ 判据逐条对账
order_flow.py 实现：状态机本身（7 处条件 UPDATE / CAS），一行没搬
```

判据做的是**对账**，不是读声明：它去 `services/order_flow.py` 里把 7 处条件 UPDATE 抠出来，
逐条与声明表比 —— 多一条、少一条、前置状态写错、目标状态写错、事件写错、跨域副作用写错，**全都报红**。

### 为什么这么改（一个刻意的取舍）

**没有**把 `order_flow` 的 assign/accept/complete 再包一层函数。理由：

1. `order_flow.py` **就是**那个「Domain Rule」层，它已经是状态机的唯一实现（第一轮定案：写前取锁 + 原子占位）；
2. 再包一层只是把同样的代码搬个地方，指南自己也反对为了唯一入口造一个万能函数；
3. 真正缺的不是那一层函数，而是**「这条命令的前置状态是什么」原来只写在函数体注释里** —— 注释会腐烂，表不会。

所以：**create / edit / resolve 这三条真的搬进了 `commands/`（它们是应用逻辑，不是状态机）**，
其余 6 条状态命令的「说法」进表、实现留在原地并被判据钉死。这是取舍，不是遗漏 —— 见 §9 第 4 条。

### 依据

```text
$ python _tools/qa/_check_order_commands.py
订单命令：9 条命令 / order_flow 里 7 处条件 UPDATE / 6 个构造期目标状态 / API 层直写状态 0 处
  ✅ 10 组判据全部通过：声明与代码逐条对得上（跃迁 / 构造期状态 / 权限 / 事件 / 跨域副作用），
     且 API 层一处都没有直接写订单状态。

$ python _tools/qa/_reverse_verify_order_commands.py
  ✅ 14/14 全部成立：跃迁多一条/少一条/前置写错、假实现、假权限点、假事件、本域副作用、
     API 层回写状态、敷衍理由 都会被抓到
```

**契约零差异的机器证明**（指南 §十九 退出条件里「原有 API 契约不变」那一条）：
改造前后各拍一张契约快照（233 条路由 + OpenAPI + 影子表），逐字段比：

```text
== r2-02-before vs r2-02-after
   route count: 233 233 | same path+method set: True | openapi equal: True
   changed routes: 0
```
**0 条变化** —— 不是「差不多」，是逐字段相同。

### 指南给的 7 条退出条件，逐条对

| 退出条件（指南 §十九） | 状态 | 依据 |
| --- | --- | --- |
| 所有订单状态变化都有唯一入口 | ✅ | 9 条命令 / 7 处 CAS 全部被声明覆盖 |
| API 不直接改变 order.status | ✅ | 判据第 9 组：API 层直写状态 **0 处** |
| AI 走同一 Command | ✅ | AI 写动作走**同一批 HTTP 端点**（`_tools/ai/_write_coverage.py` 的三跳链路把它们钉在端点上），端点现在只做「翻译 + 调命令」 |
| 原有 API 契约不变 | ✅ | 233 条路由 0 条变化，OpenAPI 相等 |
| 原有 1015 tests 全绿 | ✅ | `1015 passed in 122.94s` |
| E2E 全绿 | ⚠️ | CI 在 `7cc2f7a` 整轮 success（含 E2E）；最终提交的 CI **还没看**（见 §14） |
| 反向验证能抓住绕过路径 | ✅ | 14/14，含「API 层回写状态」这一条 |

提交：`a7b7453`

---

## 4. R2-03 跨域事务地图 + 钱的依赖方向

### 指南要什么（§五 / §六）

> 第二轮真正要做的是**验证依赖图**，而不是继续增加钱的接口。
> 把 Order / Money / Inventory / Settlement 之间的关系说清楚：谁负责 / 何时发生 / 是否同一事务 / 失败怎么办 / 重复执行怎么办。

### 我改了什么

| 产物 | 说明 |
| --- | --- |
| `docs/BUSINESS_TRANSACTION_MAP.md`（368 行） | **10 条跨域事务**，每条写六件事：入口 / 参与者 / 是否同一事务 / 提交点 / 失败怎么办 / 重复执行怎么办 |
| `docs/MONEY_DEPENDENCY_GRAPH.md`（86 行） | 钱的模块分层与依赖方向（口径层 / 落库层 / 契约层） |
| `_tools/qa/_check_business_transactions.py`（317 行） | 判据，5 组；AST 调用图 |
| `_tools/qa/_check_money_dependency.py`（283 行） | 判据，11 组；AST 导入图 |
| 两个对应的反向验证脚本 | 10 / 9 种破坏 |
| `backend/app/services/expense_category_service.py`（新增，53 行） | **修一个真缺陷**：`api/v1/expense_categories.py` 里 service 反向 import api |

### 怎么改的（两张图都不是散文）

这是这一块最重要的一点：**两张文档里的每一条断言，都由判据钉在真实的调用图/导入图上**。

```text
事务地图：AST 建调用图（882 个函数 / 1689 条边），解开 32 处「经由钱契约转发」的调用；
          对每条事务核对：声明的参与者在入口的调用链里真的被调到吗？提交点真的只有一个吗？
          声明的守卫机制（锁 / CAS / 唯一索引）在代码里找得到吗？

钱依赖图：AST 建导入图（212 个模块 / 1077 条依赖）；
          钱的口径层只准认 models/core 与同层；落库层不准碰 HTTP 与报表；
          契约层只准转出钱模块；**任何模块都不准反向 import 路由**。
```

### 为什么这么改

钱如果有**第二处实现**，两边都不报错，但数字不一样 —— 而发现它的时候通常已经算错了很多单。
第一轮已经建了「钱只有一处实现」（`money_contract`）；这一轮补的是**方向**：
光有唯一实现不够，还要保证依赖只从「业务」指向「钱」，不能倒过来。

### 依据

```text
$ python _tools/qa/_check_business_transactions.py
跨域事务：10 条 / 调用图 882 个函数 1689 条边 / 经由钱契约转发的调用 32 处
  ✅ 5 组判据全部通过：每条事务的参与者都在入口的调用链里真的被调到、提交点只有一个、
     声明的守卫机制在代码里找得到、失败与重复执行都写了。

$ python _tools/qa/_check_money_dependency.py
钱依赖图：212 个模块 / 1077 条内部依赖 / 钱模块 12 个 / 例外 0 条
  ✅ 11 组判据全部通过：钱的口径层只认 models/core 与同层、落库层不碰 HTTP 与报表、
     契约只转出钱模块、没有任何人反向 import 路由。

$ 反向验证：10/10 与 9/9 全部成立
```
**「例外 0 条」值得单独说一句**：这不是「没有例外规则」，而是这条判据当初就是**为了消灭例外而写的** ——
第一版它在 `expense_categories.py` 上抓到了那个反向 import，于是正确的修法是**改依赖方向**（拆出 service），
而不是往例外表里记一条。这就是指南 §十六 说的「先改边界，再加检查器」。

提交：`01da3fb`

---

## 5. R2-04 发件箱幂等 + 事件字段齐全

### 指南要什么（§七）

> 建议加入 **Outbox Pattern（事务发件箱）**，但**不要直接 Kafka**。
> 每个事件必须明确：event_id / event_type / aggregate_id / created_at / payload / status / retry_count。
> 另外一定要支持**幂等消费** —— 因为以后事件发两次，不能导致记两次账、发两次结算、退两次库存。

### 我改了什么

| 产物 | 说明 |
| --- | --- |
| `backend/app/migrations/006_notification_idem_key.py`（新增） | 通知表加 `idem_key` 列 + **唯一索引** `uq_notifications_idem_key` |
| `backend/app/migrations/007_outbox_aggregate_id.py`（新增） | 发件箱加 `aggregate_id` 列 |
| `backend/app/services/message_center.py` | `create_message(..., idem_key=...)`：**预查 + SAVEPOINT + IntegrityError 回查**；16 个调用点全部带上键 |
| `backend/app/core/outbox.py` | 聚合根映射 **17 条** + 显式例外 **1 条**（`orders.pending_pool_changed`：这是一个**全局信号**，没有聚合根） |
| `_tools/qa/_check_outbox_idempotency.py`（202 行） | 判据，9 组 |
| `_tools/qa/_reverse_verify_outbox_idempotency.py`（201 行） | 反向验证，9 种破坏 |

### 怎么改的（一个真缺陷被这条判据抓出来）

先看现状：**18 种事件里，有 13 种重投会多发一条站内信** —— 因为它们既没有幂等键，也没有任何去重。
这正是指南说的「事件发两次 → 用户收到两条一样的消息」。

修法是**两层**，缺一层都不成立：

```text
第一层（写入侧）：create_message 先按 idem_key 查一次 —— 查到就直接返回那条，不再插
第二层（数据库侧）：万一两个进程同时查不到、同时要插 —— 唯一索引兜底，
                    插失败的那个 catch IntegrityError，回查一次拿到对方插的那条
```
为什么不只做第一层：预查与插入之间永远有一个窗口，**没有任何应用层代码能关掉它**，只有唯一索引能。
为什么不只做第二层：每次重投都撞一次唯一索引，会把 SAVEPOINT 回滚当常规路径走，日志与连接都受影响。

聚合根（`aggregate_id`）的意义：同一个订单的多次事件要能看出来是**同一件事的进展**，而不是三件独立的事。
所以它从**一张声明的映射表**取，而不是各个调用点自己拼字符串 —— 自己拼的话，同一次派单的两个事件很可能得到两个不同的键。

### 依据

```text
$ python _tools/qa/_check_outbox_idempotency.py
发件箱幂等：18 种事件 / 聚合根映射 17 条 + 例外 1 条 / create_message 带键 16 处
  ✅ 9 组判据全部通过：聚合根从一张声明的映射表取、站内信靠唯一索引幂等、
     每个由事件驱动的 publish 都带幂等键。

$ python _tools/qa/_reverse_verify_outbox_idempotency.py
  ✅ 9/9 全部成立：漏登记 / 假 payload 键 / 删唯一索引 / 不写聚合根 / 漏幂等键 /
     不做插入前查 / 敷衍例外 / 扫描空转 都会被抓到
```

提交：`8e72810`

---

## 6. R2-05 报表从写模型退出

### 指南要什么（§八 / §九）

> 报表是：**事实消费者，而不是事实生产者**。
> 不要：Report → 偷偷调用订单写逻辑 → 再修改一些业务状态。
> 你可以先简单一点：`services/reports/turnover_query.py` / `product_query.py` / `arrears_query.py`，
> 它们只能 SELECT / JOIN / GROUP BY，不能 UPDATE / INSERT / DELETE / 状态变更。
> **不要为了「架构先进」提前建** Read Model / Materialized View / 缓存。

### 上半场（提交 `14b3231`）：把报表层里唯一那处**业务写**搬走

| 改动 | 数字 |
| --- | --- |
| `backend/app/api/v1/stats.py` | **+1 / −50**（那 50 行里有业务写） |
| `backend/app/api/v1/exception_resolution.py`（新增） | +54 |
| `backend/app/commands/order.py` | +48（新增 `resolve_exception` 命令） |

具体是什么：`POST /stats/exception-orders/{order_id}/resolve` 原来住在 `api/v1/stats.py` 里，**在报表模块里直接改订单状态**。
现在它搬到 `exception_resolution.py`，**URL 一个字没变**，行为改成委托 `commands.order.resolve_exception`。

契约证据（这是「搬迁」与「改功能」的差别所在）：

```text
== r2-02-after vs r2-05-after
   route count: 233 233 | same path+method set: True | openapi equal: True
   changed routes: 1
      ('POST',) /api/v1/stats/exception-orders/{order_id}/resolve fields: ['module']
```
**233 条路由里只有 1 条变了，而且变的是「它由哪个模块承载」** —— URL / 方法 / 依赖 / 响应模型 / OpenAPI 全部没变。
这正是「纯搬迁」应有的样子。

### 下半场（提交 `6e45241`）：把聚合搬进 `services/reports/`

| 文件 | 行数 |
| --- | --- |
| `services/reports/__init__.py` | 8 |
| `services/reports/_common.py` | 104 |
| `services/reports/loader.py` | 63 |
| `services/reports/turnover_query.py` | 202 |
| `services/reports/product_query.py` | 121 |
| `services/reports/arrears_query.py` | 70 |
| `services/reports_service.py` | **503 → 25**（只剩名字的 shim，`+24 / −499`） |

配套两处**必须跟着改**的地方：

1. `services/money_contract.py` 里 `FIGURES` 的消费方路径指向新文件。
   ⚠️ 这里被抓到一次：给 `driver_pay` 多列了 `product_query` / `arrears_query`，`_check_money_contract.py` 当场报红 ——
   它的结论是**「假消费方比漏写更糟」**（漏写最多是没检查到，假消费方等于告诉人「这里在用这个数」，而它其实没用）。
2. 两个后端用例（`test_audit_round12_guards.py` / `test_audit_round2_guards.py`）改成读**并集**。

### 为什么这一块折腾了 5 轮（这一轮最值得记住的教训）

业务代码本身搬得很快。折腾的是**判据与注入锚点**：它们写死了旧路径 `services/reports_service.py`。
于是出现一个陷阱：搬完代码 → 判据说「找不到这个形状」→ 报红；如果这时候去改判据的路径，
就等于**一边搬东西一边把尺子改短**，搬完时判据已经不知道在看什么了。

这轮定下来的规矩是：**先让判据读并集，再搬代码**。顺序反了就不只是麻烦，是判据会静默失效。
具体做法：给 `_tools/ai/_airepo.py` 加 `reports_files()` / `reports_source()`（**glob 出来的并集**），
26 个注入沙箱 + 4 个三元组 harness + 锚点元检查本身都学会「目标文件里找不到时，去并集里找含它的那一份」；
然后才搬代码。

### 依据

```text
$ python _tools/qa/_check_report_boundary.py
报表只读边界：11 个文件 / 39 个函数 / 例外 0 条
  ✅ 3 组判据全部通过：报表层零写动词、不 import 写服务、路由体不写业务对象。

$ python _tools/qa/_reverse_verify_report_boundary.py
  ✅ 7/7 全部成立：报表层回写业务状态 / 落库 / 依赖写服务 / 清单缺文件 / 例外化石 / 清单空转 都会被抓到
```

提交：`14b3231`（上半）、`6e45241`（下半）

---

## 7. R2-06 多实例就绪 + 全链路 trace

### 指南要什么（§十四 / §十五）

> 把它进一步变成 `check_multi_instance_readiness.py`。不过注意：**检查器只作为验收工具，不是解决方案**。
> 最终必须是真的：两个实例同时运行，然后验证 migration 不冲突 / scheduler 不重复 / upload 一致 / socket 正常 / DB 正常 / request 正常。
> 生产仍然需要知道：**这一个请求发生了什么？** —— Request ID + Business Correlation ID，把订单→请求→命令→状态→账本→司机账单→事件→通知串起来。

### 上半场（`1128402`）：把「就绪度」变成机器契约

`docs/MULTI_INSTANCE_READINESS.md`（120 行）里 10 道门，**每一道门都是一个可判定块**：

```text
name: <稳定标识>
status: done | not-done
evidence: <backend 相对路径>        ← status=done 必填
must_contain: <字符串清单>          ← status=done 必填
为什么还没做 / 什么时候做            ← status=not-done 必填（各 ≥12 字）
```

关键设计：**判据会拿 `evidence` 指到的源码去核对 `must_contain` 那几串东西真的在不在** ——
「文档说做了、代码里没有」当场报红。这正是第一轮反复栽的那一类（文档与事实走散）。

10 道门的结果：

| # | 门 | 状态 |
| --- | --- | --- |
| 1 | 迁移版本化 | ✅ |
| 2 | 并发 / **跨主机**迁移协调 | ✅ 本轮补（`GET_LOCK` 命名锁） |
| 3 | 可靠事件（事务发件箱） | ✅ |
| 4 | 可观测性（Request ID 贯穿） | ✅ |
| 5 | 备份与恢复 | ✅ |
| 6 | Socket.IO 跨进程 | ✅ |
| 7 | **启动期自愈（跨主机）** | ⛔ 没做 |
| 8 | **上传目录共享** | ⛔ 没做 |
| 9 | **定时任务选主** | ⛔ 没做 |
| 10 | **nginx upstream + 失败摘除** | ⛔ 没做 |

第 2 道门是本轮补的，也是最值钱的一条。原来只有 `/tmp/sorders_migrations.lock`（`flock`），
**它只在同一台机器上有效** —— 多实例部署时 A、B 两台各拿自己的 `/tmp` 锁**都会成功**，
同一条迁移被执行两遍，DDL 半途撞车，而且版本表互相覆盖（谁后写谁赢，先跑完的那条等于没记账）。
现在在拿到本机 flock **之后**再向数据库要一把命名锁（`GET_LOCK("sorders_migrations")`，超时 60s）。
⛔ 锁的顺序是固定的（先本机、后服务端），反着写会和 `--workers 2` 死锁 —— 判据钉着这个顺序。

### 下半场（`9ffbc9d`）：一条命令查完一条订单的一生

`_tools/ops/_trace_order.py`（172 行，**只读**）—— 给一个订单号，按顺序打出：

```text
订单 → 命令 / request_id → 账本流水 → 司机账单 → 事件 → 通知        （6 段链路 / 32 个列）
```

判据 `_check_traceability.py` 核三件事：每一段链路的表与列**在模型里真的存在**、工具**真的查了它们**、**全程只读**。

⚠️ 写这个工具时踩到一个坑，值得单独记：**`app.database` 一被 import 就会执行 `bootstrap_schema`（建表 DDL）**。
也就是说，一个排障脚本只要随手 import 它，就会**在别人的库上跑建表**。判据现在专门钉着这一条。

### 依据

```text
$ python _tools/qa/_check_multi_instance_readiness.py
多实例就绪：10 道门（已过 6 / 没做 4） / done 的门核了 20 串代码形状
  ✅ 3 组判据全部通过：每道门都有状态，「已过」的拿去源码里核过形状，「没做」的都写清了为什么与什么时候做。

$ python _tools/qa/_check_traceability.py
订单全链路 trace：6 段链路 / 32 个列 / 只读
  ✅ 3 组判据全部通过：每一段链路的表与列都在模型里、工具真的查了它们、而且全程只读。

$ 反向验证：6/6 与 6/6 全部成立
```

提交：`1128402`（上半）、`9ffbc9d`（下半）

---

## 8. 贯穿层：Capability Registry（权限成为能力）

### 指南要什么（§十一 / §十二）

> 第二轮可以进一步做：Capability Registry → API / AI / UI / Audit。
> 例如 `order:assign`、`scope=all`、`roles=dispatcher`，然后 API → Depends、AI → capability available、
> Android → 是否显示按钮、Audit → action vocabulary。**这样 AI 就不会成为自己的权限系统。**
> 权限第二轮：**不要追求 36 → 0** —— 例外不是失败，没有解释的例外才是失败。

### 我改了什么

`backend/app/core/capabilities.py`（新增，约 272 行）：**26 条能力**，每条写六件事：

```text
permission  权限点（与 Permission 枚举一一对应）
what        这条能力到底允许什么（给人看的一句话）
scope       数据范围 + scope_why（为什么是这一档）
roles       哪些角色有它（⛔ 不含 dispatcher 的**绕过** —— 那条在 rbac.BYPASS_ROLES 里单独声明）
kind        read / write（审计口径按它分）
```

判据 `_check_capability_registry.py`（6 组）+ 反向验证 6/6。

### 怎么改的（这一条判据最值钱的地方）

**「执行点是机器算出来的，不是声明出来的。」**

```text
每条能力 → 去 backend/app/api/** 里找 require_permission(Permission.X) /
           require_any_permission / 体内的 role_has_permission(..., Permission.X)
找不到执行点的 → 必须写进 DECLARED_ONLY 例外表（带理由 + 「什么时候删掉这一条」）
```

结果：**26 条能力 / 有执行点 26 条 / 仅声明 0 条**。
也就是说，没有任何一条能力是「写了个漂亮的声明、其实没有人执行它」。
这正是指南 §十七 第 2 条说的 —— Source of Truth 不能「代码一份、AI 一份、文档一份、检查器一份」。

### 依据

```text
$ python _tools/qa/_check_capability_registry.py
能力注册表：26 条能力 / 有执行点 26 条 / 仅声明 0 条
  ✅ 6 组判据全部通过：能力表与 Permission / SCOPES / ROLE_PERMISSIONS 三方一致，…

$ python _tools/qa/_reverse_verify_capability_registry.py
  ✅ 6/6 全部成立：漏声明 / scope 走散 / 角色走散 / 例外化石 / 注册表被掏空 都会被抓到
```

顺带：体内角色门槛棘轮从 **36 收敛到 35 处**（`_check_inline_role_gates.py`）。
指南说的「不要追求 36 → 0」，我的理解是**每降一处都必须是因为结构变了，而不是因为把门槛挪了个地方**。

提交：`7cc2f7a`

---

## 9. 我没有改的（7 件，逐条写清为什么 + 什么时候做）

### 9.1 Migration 与应用启动没有解耦（指南 §十三）

指南要的是：`deploy → migration job → success → application start`，而不是 `application starts → 偷偷迁库 → 顺便祈祷成功`。

**现状**：`backend/app/database.py:99` 是 `bootstrap_schema(engine)`，在**模块导入时**执行。
也就是说，只要进程起来了，它就已经在建表了。

**为什么没做**：改它要动的是**启动路径**（核心区），而且真正要做对必须同时有「部署脚本里先跑一遍迁移」这一步；
现在的生产是 systemd + `uvicorn --workers 2`，没有独立的部署阶段。在**还没上多实例**的时候，
把迁移从启动里拆出去只会把一个已经能跑的东西拆成两个会失败的东西。

**什么时候做**：与 §7 里那 4 道门同一批（切多实例之前）。

### 9.2 UI / 审计两端还没接到 Capability 上（指南 §十一 的四端同源）

做到的是 **API + AI** 两端：

- API：26 条能力全部去 `api/**` 里核过执行点；
- AI：读能力的角色裁剪走 `rbac.ROLE_PERMISSIONS`，而它与能力表由判据双向钉住。

**没做的两端**：

- **UI**：安卓侧某个按钮显不显示，仍然是各页自己的角色判断，**不是读能力表**；
- **Audit**：`models/enums.OperationAction` 的动作码与 `kind=write` 的能力**还没有对照判据**
  （现有的只是「每个动作码有中文名」那条）。

**为什么没做**：这两端要动客户端与审计口径，属于「改功能」而不是「改结构」；这一轮先把**能证明的**那两端钉死。
这两条已经在 `capabilities.py` 的模块文档里写成显式的**欠账**（见 §11）。

### 9.3 没有真的起两个实例跑一遍（指南 §十四 的原话是「最终必须是真的」）

做的是：文档 + 判据 + 跨主机迁移锁。**没有**开两台机器验证 migration 不冲突 / scheduler 不重复 / upload 一致。
**为什么没做**：其中 4 道门（启动期自愈 / 共享上传 / 定时任务选主 / nginx upstream）没闭合，
现在起两个实例只会制造「看起来验证过了」的假象。指南自己也排了顺序：**迁移 → 事件 → 可观测 → 备份 → 才轮到多实例**（前 5 条现已全部 ✅）。

### 9.4 `order_flow` 的 6 条状态命令没有再包一层 Command

见 §3 的「刻意的取舍」。补充一句**怎么证明这不是遗漏**：`registry.py` 里每一条命令都写了 `why` 字段
（「为什么它是一条独立命令，而不是别的命令的一个分支」），判据会检查它不能被敷衍（缩成两个字会报红）。

### 9.5 我这轮加了 9 个检查器 —— 与指南 §十六「不要再加检查器」有张力

指南的原话：**「新增一个 Checker，必须先证明 Checker 所在问题无法通过架构边界消除。」**

我的账要算清楚：这 9 个判据里，**有 6 个本身就是「把架构边界写成可执行契约」**（领域边界 / 命令声明 / 事务地图 /
钱依赖方向 / 报表只读 / 能力表）——它们不是「又加了一条 red line」，而是**边界的定义本身**：没有它们，
「谁拥有这个事实」就只是一句文档。

**另外 3 个我要如实承认更接近「额外的检查」**：多实例就绪、全链路 trace、以及发件箱幂等里的一部分。
其中多实例那条是**指南自己点名要的**（§十四 原话就是 `check_multi_instance_readiness.py`）；
另外两条我的理由不足够硬 —— 如果你认为该砍，砍它们不会影响前 6 条。

### 9.6 没有部署到生产

与第一轮相同：**等你拍板**。生产现在跑的仍是旧代码。

### 9.7 `backend/requirements.txt` 是否锁版本 —— 你一直没答复，我没有擅自动

---

## 10. 过程中发现的其他问题

这些**不在这轮整改范围内**，但都是真实存在、而且值得你知道的。

### 10.1 判据层自己的两个 bug（在 `_tools/ai/_airepo.py` 里）

**① 两个 `def reports_source`。** 同一个模块里定义了两次，**后定义的静默覆盖了前定义的** ——
也就是说「让判据读报表源码的并集」这件事**从来没有生效过**，而所有判据都显示全绿。
这类 bug 的可怕之处在于：它让一整类检查变成空转，而**没有任何地方会报错**。（提交 `a2548d2`）

**② `reports_files()` 的路径口径写错了**：它相对的是 `backend/app`，我按仓库根拼的。
（提交 `42a28ba`）

### 10.2 `app.database` 导入即建表

`backend/app/database.py:99` 的 `bootstrap_schema(engine)` 在 import 时执行。任何工具只要 import 它，
就会在**当前配置指向的库上**跑那 1600 行 DDL。写 trace 工具时才发现（见 §7）。

这条与 9.1 是同一个根因的两个面：一个说「启动即迁移」，一个说「import 即迁移」。

### 10.3 18 种事件里 13 种重投会多发一条站内信

这是 R2-04 的判据抓到的**真缺陷**，已修（见 §5）。

### 10.4 FastAPI 用路由函数的 docstring 当 OpenAPI 的 description

我在 R2-05a 里给搬过去的端点写了 docstring，`_api_contract_snapshot.py` **当场把契约打红**。
结论：**路由函数的注释是契约的一部分**，改它会改 API 文档。说明被移到了模块文档里。

### 10.5 `_reverse_verify_round12.py` 的还原不完整

它的收尾还原没有把快照里的文件全部写回（20 个文件）。这类问题的后果是**一次注入没还原干净，
后续所有结论都建立在坏代码上**。已加固（最后一遍「把快照字节写回去」），现在 30/30 通过、20 个文件逐字节一致。

### 10.6 指南引用的行数是**旧的**，而且有一处已经过时到不成立

指南 §开篇说：「api/v1 仍然是厚层：约 13,724 行，orders.py 约 2,055 行，reports.py 约 822 行」。

实测（本轮开始时）：

```text
api/v1 合计   10814 行   （指南说 13724）
orders.py        23 行   （指南说 2055 —— 它早在第一轮就被拆完了）
reports.py      332 行   （指南说 822）
```

原因很清楚：**指南在引用第一轮报告的旧数字**。所以这轮的优先级是我按**实测**重排的，不是照抄指南顺序。
（这条本身也说明为什么本项目的规矩是「会变的数字一律不手写、一律指向生成物」。）

### 10.7 `_check_audit_coverage.py` 当场抓到两处「写端点没有留痕」

R2-05a 把端点搬到 `exception_resolution.py` 之后，这个判据立刻报「写端点但没有审计日志」。
（修法是补上留痕，而不是往豁免表里加一行。）

### 10.8 钱契约里的「假消费方」

`money_contract.FIGURES` 里给 `driver_pay` 多列了两个查询模块，`_check_money_contract.py` 报红，
结论是「**假消费方比漏写更糟**」—— 漏写最多是没检查到，假消费方等于告诉人「这里在用这个数」。

---

## 11. 我核过、并且发现**自己**说过头的地方

这一类问题**判据抓不到** —— 判据抓的是代码形状，不是文档语气。所以它只能靠人在写报告时逐句核自己的产物。
这轮核出来一处，已经改掉（提交 `fb88459`）：

**`backend/app/core/capabilities.py` 的模块文档有两句话说过了头：**

| 原话 | 事实 |
| --- | --- |
| 「`rbac.py` 的 `ROLE_PERMISSIONS` 与 `SCOPES` 都由它**派生** —— 不再有第二份可以改歪的副本」 | ⛔ 不成立。`rbac.py:61` 与 `rbac.py:139` 仍然是**手写的那一份**，`capabilities.py` 里没有任何 builder。真实现状是「一份声明 + 一份被钉住的镜像」，由判据做**双向一致**核对 —— 而**判据自己的文档就是这么写的**，两个文件的说法此前互相打架 |
| 「UI：安卓侧显示不显示一个按钮，判据是「这个角色有没有这条能力」」等三行 | ⛔ UI 与审计两条是**欠账不是事实**（见 9.2）。已改成显式的 ⛔ 本轮没做，并写明四端同源只做到 API + AI |

改动只有注释，**零行为变化**；契约快照不受影响；改完 `_check_all.py` 112/112。

为什么值得单独列一节：这正是本项目栽过最多次的那一类 —— **「文档说做了、代码里没有」**。
区别只在于这次说过头的是我自己的产物，而不是别人写的文档。

---

## 12. 复现命令总表

```text
# ① 全量静态检查（112 个脚本）
python _tools/qa/_check_all.py                    # → ✅ 112/112

# ② 后端全量用例
cd backend; python -m pytest -q                   # → 1015 passed

# ③ 本轮新增的 9 个判据（各自单独跑）
python _tools/qa/_check_domain_boundaries.py      # 15 域 / 47 表 / 57 命令 / 31 读边 / 18 事件
python _tools/qa/_check_order_commands.py         # 9 命令 / 7 CAS / API 直写 0 处
python _tools/qa/_check_business_transactions.py  # 10 事务 / 882 函数 1689 边
python _tools/qa/_check_money_dependency.py       # 212 模块 / 1077 依赖 / 例外 0
python _tools/qa/_check_outbox_idempotency.py     # 18 事件 / 聚合根 17+1 / 带键 16 处
python _tools/qa/_check_report_boundary.py        # 11 文件 / 39 函数 / 例外 0
python _tools/qa/_check_multi_instance_readiness.py # 10 道门（6/4）
python _tools/qa/_check_traceability.py           # 6 段 / 32 列 / 只读
python _tools/qa/_check_capability_registry.py    # 26 条 / 执行点 26 / 仅声明 0

# ④ 对应的 9 份反向验证（注入 → 报红 → 还原 → 全绿）
python _tools/qa/_reverse_verify_domain_boundaries.py        # 13/13
python _tools/qa/_reverse_verify_order_commands.py           # 14/14
python _tools/qa/_reverse_verify_business_transactions.py    # 10/10
python _tools/qa/_reverse_verify_money_dependency.py         #  9/9
python _tools/qa/_reverse_verify_outbox_idempotency.py       #  9/9
python _tools/qa/_reverse_verify_report_boundary.py          #  7/7
python _tools/qa/_reverse_verify_multi_instance_readiness.py #  6/6
python _tools/qa/_reverse_verify_traceability.py             #  6/6
python _tools/qa/_reverse_verify_capability_registry.py      #  6/6

# ⑤ 排障用：一条命令查完一张订单的一生
python _tools/ops/_trace_order.py <订单号或单号>

# ⑥ 契约等价性（搬迁的机器证明）
python _tools/qa/_api_contract_snapshot.py --diff r2-02-before r2-02-after

# ⑦ 迁移版本
cd backend; python -m app.migrations status        # → 当前版本：7
```

⚠️ 跑完 ④ 之后**记得重启本机后端**，否则 `_check_all.py` 会红在「本机后端跑的是旧代码」那一条上。

---

## 13. 提交账本（18 个，按时间顺序）

| 提交 | 内容 |
| --- | --- |
| `ae87211` | R2-01 领域边界地图 |
| `a7b7453` | R2-02 订单命令层 + 声明表 |
| `01da3fb` | R2-03 跨域事务地图 + 钱的依赖方向（顺带修 service→api 反向 import） |
| `8e72810` | R2-04 发件箱幂等 + 事件字段 |
| `14b3231` | R2-05 上半：报表层唯一那处业务写搬回订单域 |
| `1128402` | R2-06 上半：多实例就绪度变成机器契约 |
| `9ffbc9d` | R2-06 下半：订单全链路 trace |
| `7cc2f7a` | 贯穿层：Capability Registry |
| `00a0a4f` | 收尾：验收页重跑全绿并确认 CI 整轮绿 |
| `d6beace` | R2-05 下半①：给报表源码加**并集读取器**（先让判据读并集，再搬代码） |
| `42a28ba` | 并集读取器路径口径修正 |
| `a2548d2` | **修一个真 bug**：`_airepo` 里两个 `def reports_source` 静默覆盖 |
| `da2b1f5` | 反向验证沙箱加并集回退（26 份） |
| `bd322e3` | 交接：剩下 6 份 harness 形状不同的反向验证 |
| `7fbf6bd` | 反向验证并集回退（第 2 批：4 份三元组 harness + 锚点元检查） |
| `7e3e0c8` | 交接：只差 round12 的收尾还原 |
| `6e45241` | R2-05 下半：报表聚合搬进 `services/reports/` |
| `fb88459` | 收尾：`capabilities.py` 的模块文档说了过头话 —— 改成事实 |

中间那几个「交接」提交（`bd322e3` / `7e3e0c8`）是**卡住时的现场记录**：写清试过什么、为什么回退、下一步精确清单。
它们不是过程噪音 —— 最后搬进 `services/reports/` 时，靠的就是这份清单。

---

## 14. 需要你拍板 / 你知道就行的

1. **最终提交的 CI 我还没看。** 推送触发了 CI，但按你的意思先写了这份报告。
   上一次整轮确认是 `7cc2f7a`（8 个 job 全 success，含安卓 E2E；中途 E2E 红过一次，原因是模拟器 ANR 而不是回归，重跑后全绿）。
2. **要不要把 §9.5 里那 3 个「额外的检查」砍掉？**（多实例就绪 / 全链路 trace / 发件箱幂等里的一部分）
   砍它们不影响前 6 条判据。
3. **§9.2 的 UI / 审计两端**要不要排进下一轮？（做完才叫真正的「AI 不会成为自己的权限系统」）
4. **§9.1 的迁移解耦**要不要现在就做？（我的建议是：与多实例那 4 道门一起做，现在做是拆一个能跑的东西）
5. **生产部署**：仍等你拍板。生产跑的还是旧代码，4 道多实例的门也没闭合。
6. **`backend/requirements.txt` 要不要锁版本**：你一直没答复。

---

最后一句，是这轮最实在的收获，也写在 `docs/AI_WORK_CLAIM.md` 里留给下一个人：

> **先让判据读并集，再搬代码。**
>
> 顺序反了不会立刻报错 —— 它会让你一边搬东西一边把尺子改短，搬完时判据已经不知道在看什么了。
> 这轮在 `services/reports/` 上折腾了 5 个提交，全部是因为这一条。

