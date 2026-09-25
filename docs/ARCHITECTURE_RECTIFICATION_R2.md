SOrders 第二轮整改的核心目标

我建议把第二轮定名为：

SOrders 架构第二阶段：从“强约束模块化单体”进入“显式业务边界架构”。

核心思想只有一句：

第一轮解决的是“不要乱”；第二轮解决的是“为什么天然不会乱”。

现在你的系统已经有了很多很强的护栏，但最需要继续解决的是：

                    当前
                     │
        ┌────────────┼─────────────┐
        ↓            ↓             ↓
   Order / Money   Inventory    Settlement
        │            │             │
        └───────┬────┴─────────────┘
                ↓
           大量业务协作
                ↓
         API / Service / AI

原始架构报告明确指出，api/v1 仍然是厚层：约 13,724 行，orders.py 约 2,055 行，reports.py 约 822 行；领域服务虽然已经很多，但还不是所有业务规则的唯一真相层。

所以第二轮真正要处理的，不是“文件太大”，而是：

谁拥有规则？谁有权改变状态？谁能写数据？谁只能读取？谁产生事件？谁消费事件？

一、第二轮先不要改代码：先建立“领域地图”

这是我最建议你做的第一件事。

1. 建立 DOMAIN_BOUNDARIES.md

不要再从文件夹划分模块。

直接从业务事实所有权划分。

先定义：

Order Domain
Money / Accounting Domain
Inventory Domain
Settlement Domain
Return Domain
Notification Domain
Reporting Domain
Identity / Authorization Domain
AI Integration

然后对每个 Domain 写四件事情：

Domain
├── Owns       谁拥有这些数据/规则
├── Commands   谁可以改变它
├── Reads      谁可以读取它
└── Events     它会产生什么事实

例如：

Order Domain

Owns:
- order.status
- order assignment
- order lifecycle

Commands:
- CreateOrder
- AssignOrder
- AcceptOrder
- CompleteOrder
- CancelOrder
- RecallOrder

Reads:
- product snapshot
- address
- driver summary

Events:
- OrderCreated
- DriverAssigned
- OrderAccepted
- OrderCompleted

这里不要急着设计类名。

你现在最缺的是“业务边界事实”，不是更多代码抽象。

二、第二轮第一个真正的重构目标：Order Domain

为什么先动订单？

因为你的整个系统天然围绕订单展开，订单又连接钱、司机、退货、库存、通知、报表。

而当前 orders.py 本身就是后端最大的文件之一：25 个端点、2055 行。

但：

不要第一步就把 orders.py 拆成十个文件。

那只是物理拆分。

你第一步应该建立：

Route
 ↓
Command
 ↓
Order Application Logic
 ↓
Order Domain Rule
 ↓
Persistence

例如：

POST /orders/{id}/assign
        ↓
AssignOrderCommand
        ↓
assign_order(...)
        ↓
OrderFlow.transition(...)
        ↓
DB

这样 Route 负责：

HTTP
认证
参数
响应

而不再负责：

“现在这个订单到底能不能派？”
“派完后应该修改哪些状态？”
“会不会影响计费？”
三、订单状态必须成为真正的“唯一写入口”

这是第二轮最重要的一个架构改造。

现在订单状态机已经是核心冻结机制，而原报告中也明确发现状态赋值并非完全单一入口。

第二轮要达到：

任何入口
API / AI / Job / Admin
        ↓
Command
        ↓
OrderFlow
        ↓
Validate
        ↓
Transition
        ↓
State Change

以后禁止出现：

order.status = ...

散落在业务代码里。

唯一允许：

order_flow.transition(order, ...)

或者等价的唯一业务入口。

但注意一个非常重要的事情：

不要为了“唯一入口”而建立一个巨大万能函数。

错误：

transition(order, action, context, anything...)

最后又变成超级函数。

更合理的是显式命令：

assign()
accept()
complete()
cancel()
recall()
return()

让每一种状态转换拥有清晰的前置条件和结果。

四、第二轮不是“拆 Service”，而是建立 Application / Domain 边界

你现在已经有大量 service，例如：

order_flow
order_money
driver_pay
accounting_service
order_return
message_center

这很好。

所以不要为了架构漂亮突然建立：

repository/
factory/
manager/
adapter/
facade/
handler/

一大堆抽象。

只做一个必要区分：

Application Layer
=
“这个业务动作如何组织起来？”

Domain
=
“这个业务动作在什么条件下合法？”

Infrastructure
=
“数据和外部系统怎么实现？”

例如：

CompleteOrder

Application:
1. 校验身份
2. 获取订单
3. 调 OrderDomain
4. 保存
5. 产生事件

Domain:
- 当前状态是否允许完成？
- 是否满足送达条件？
- 司机是不是被指派者？

这样以后 AI 也可以调用同一个 Application Command。

五、第二轮第二大目标：把钱契约从“统一入口”升级成“统一依赖方向”

这一轮的钱已经整改得非常好。

现在消费方统一从：

money_contract

获取钱相关符号，而且 PENDING 已经清零。

所以不要继续为了形式去建立三个 Calculator 类。

这点报告自己的判断是合理的：当前选择的是“数据表 + 惰性契约转出”，而不是空壳类。

第二轮真正要做的是：

Reports ───────┐
Ledger ────────┤
Settlement ────┤
AI ────────────┤
Order ─────────┤
                ↓
          money_contract
                ↓
          Money implementation

而不是：

A → money_contract → B
B → accounting → C
C → order_money → A

也就是说：

第二轮要验证的是依赖图，而不是继续增加钱的接口。

建议做一张：

MONEY_DEPENDENCY_GRAPH.md

并明确：

允许依赖
禁止依赖
单向依赖
六、第三大目标：把 Order / Money / Inventory / Settlement 之间的关系说清楚

这个系统真正复杂的地方，不是订单本身，而是：

订单完成
      ↓
钱
      ↓
司机结算
      ↓
库存
      ↓
退货
      ↓
报表

所以你应该建立一个：

BUSINESS_TRANSACTION_MAP.md

例如：

CompleteOrder
 ├─ Order → DELIVERED
 ├─ Ledger → create
 ├─ DriverPay → snapshot / bill
 ├─ Inventory → deduct
 └─ Event → OrderCompleted

每一项写清楚：

谁负责？
什么时候发生？
是否同一个 DB transaction？
失败怎么办？
重复执行怎么办？

这一步很重要。

因为它会把现在散落在 service 中的“隐式协作”变成显式业务契约。

七、第四大目标：建立可靠 Event Boundary，而不是马上上 MQ

你目前已经有：

message_center
push_events
Socket.IO

而系统当前没有真正的消息队列，事件通知更多还是跟随业务流程产生。

第二轮我建议加入：

Outbox Pattern（事务发件箱）

但不要直接 Kafka。

先做：

MySQL Transaction
 ├─ 修改业务数据
 └─ 写 outbox_event
          ↓
       Worker
          ↓
   ┌──────┼───────┐
   ↓      ↓       ↓
 Socket  Notify  Stats

这样：

订单成功
但通知服务挂了

不会导致：

业务成功
事件永远消失
Event 的四个注意事项

每个事件必须明确：

event_id
event_type
aggregate_id
created_at
payload
status
retry_count

另外一定要支持：

幂等消费（Idempotent Consumer）

因为以后：

事件发两次

不能导致：

记两次账
发两次结算
退两次库存
八、第五大目标：Reports 必须从业务写模型里退出来

原始报告特别指出：

reports.py 不只是路由，它自己实现了大量聚合。

这是第二轮必须处理的。

以后应该：

HTTP
 ↓
Report Query
 ↓
Read-only Query Service
 ↓
DB

不要：

Report
 ↓
偷偷调用订单写逻辑
 ↓
再修改一些业务状态

报表是：

事实消费者，而不是事实生产者。

九、不要马上上复杂 Read Model，先做 Query Boundary

你可以先简单一点：

services/reports/
    turnover_query.py
    product_query.py
    arrears_query.py

它们只能：

SELECT
JOIN
GROUP BY

不能：

UPDATE
INSERT
DELETE
状态变更

等真正发现：

查询很慢
聚合非常复杂
实时统计成本很高

再考虑：

Read Model
Materialized View
缓存

不要为了“架构先进”提前建。

十、权限第二轮：不要追求 36 → 0

这点必须保留第一轮报告里的判断。

目前还有 36 处体内门槛，但报告已经说明，其中一部分本来就是依赖请求数据才能判断，无法自然搬到函数签名。

所以目标不是：

36 → 0

而是：

36
↓
每一条都有原因
↓
每一条都有模型
↓
每一条可审计
↓
能结构化就结构化
↓
不能结构化就保留

也就是：

例外不是失败；没有解释的例外才是失败。

十一、权限下一步应该成为整个系统的 Capability Model

你现在已经完成：

resource
action
scope
BYPASS_ROLES
signature dependency

那么第二轮可以进一步做：

Capability Registry
        │
   ┌────┼─────┬──────┐
   ↓    ↓     ↓      ↓
 API   AI    UI    Audit

例如：

order:assign
scope=all
roles=dispatcher

然后：

API
→ Depends

AI
→ capability available

Android
→ 是否显示按钮

Audit
→ action vocabulary

这样 AI 就不会成为自己的权限系统。

十二、AI 第二轮不要优先做“更多能力”，要做“更统一”

第一轮已经把：

AI_calls
AI_write_confirmed

变成真实指标，也把 Android E2E 接入 CI。

第二轮不要急着继续扩 AI 工具数量。

先保证：

AI
 ↓
Capability
 ↓
Command
 ↓
Domain

而不是：

AI
 ↓
调用某个 service
 ↓
service 自己猜权限

以后 AI 做：

“把订单 10086 派给张三。”

应该和人点击：

“派给张三”

走同一个 Command。

这才是正确的 AI 架构。

十三、第六大目标：把数据库 Migration 从“能迁移”推进到“可演进”

第一轮现在已经加上 DB 级锁，并准备好了多实例前置；但报告明确还有 5 个条件没有闭合，也明确没有切多实例。

第二轮这里不要继续堆锁。

应该验证：

Migration
├── version
├── ordering
├── idempotency
├── rollback / forward-fix policy
├── multi-instance coordination
└── production verification

尤其是：

Migration 应该和应用启动生命周期彻底解耦。

目标：

deploy
 ↓
migration job
 ↓
success
 ↓
application start

而不是：

application starts
 ↓
偷偷迁库
 ↓
顺便祈祷成功
十四、第二轮要正式完成 Multi-instance Readiness

报告已经给你列出了 5 道门：

① MySQL
② 每实例启动自愈
③ uploads 共享
④ 定时任务选主
⑤ nginx upstream

我建议做成：

MULTI_INSTANCE_READINESS.md

但进一步把它变成：

check_multi_instance_readiness.py

不过注意：

检查器只作为验收工具，不是解决方案。

最终必须是真的：

Instance A
Instance B

同时运行，然后验证：

migration 不冲突
scheduler 不重复
upload 一致
socket 正常
DB 正常
request 正常
十五、第二轮必须补一个东西：真正的 Observability

第一轮已经证明了：

“Green”有可能不是真的 Green。

现在 E2E 已经解决了一层。

但是生产仍然需要知道：

这一个请求发生了什么？

所以新增：

Request ID
HTTP Request
 ↓
request_id
 ↓
service
 ↓
DB / Event / Audit
Business Correlation ID

订单流程最好能串：

Order #10086
 ↓
request
 ↓
command
 ↓
state change
 ↓
ledger
 ↓
driver bill
 ↓
event
 ↓
notification

这样你遇到：

“为什么这笔订单的钱不对？”

可以直接查完整链路。

十六、第二轮的“检查器思想”也必须改变

这一轮最容易犯的错误就是：

有问题
 ↓
再加 20 个 check

目前已经是：

103 / 103

我建议以后采用一个非常严格的原则：

新增一个 Checker，必须先证明 Checker 所在问题无法通过架构边界消除。

例如：

问题：
所有钱都必须从 money_contract 导入

优先：

改变 import architecture

再：

check

而不是反过来：

所有人继续乱 import
+
_checker_money_contract
十七、第二轮真正应该遵循的 8 个思想

这是我最希望你记住的部分。

1. 边界优先于文件

不要问：

“这个文件应该拆成几个文件？”

先问：

“这个规则到底属于谁？”

2. Source of Truth（事实源）必须唯一

一个事实：

订单状态
钱
权限
价格
司机应得

必须有一个明确拥有者。

不能：

代码 A 一份
AI 一份
文档一份
检查器一份
3. 规则应该被“调用”，而不是被“复制”

错误：

A:
if status == ...

B:
if status == ...

C:
if status == ...

正确：

A → OrderDomain
B → OrderDomain
C → OrderDomain
4. 先定义不变量，再写代码

例如：

Invariant:
DELIVERED 订单不能再次 ACCEPTED

再设计：

transition()

而不是：

先写 transition
再想“应该允许什么”
5. Refactor（重构）必须保持行为等价

每一次：

代码结构变化

必须尽量保证：

API 不变
DB 不变
业务语义不变
权限不变
用户体验不变

先完成：

结构迁移

再做：

行为修改
6. 一个真正的系统，要允许“失败”

第一轮 E2E 的巨大价值就是：

“没跑”终于不再被当成“通过”。

报告对此有非常明确的经验总结。

第二轮也要保持：

未知
≠
成功

跳过
≠
通过

无证据
≠
安全
7. 不要追求所有东西都抽象

这是第二轮非常重要的刹车。

不要因为看到：

Service

就建立：

ServiceInterface
ServiceFactory
ServiceManager
ServiceAdapter
Repository
RepositoryFactory

你的项目现在已经很复杂。

抽象的成本本身也是复杂度。

只有存在：

重复变化
多个实现
清晰边界
独立测试价值

才值得抽象。

8. 每完成一块，都必须“证明自己没有破坏以前的东西”

形成固定循环：

修改
 ↓
局部验证
 ↓
全量静态检查
 ↓
反向验证
 ↓
单测
 ↓
E2E
 ↓
必要时生产只读验证
 ↓
Commit

这会比：

连续改 30 个文件
最后一起跑

安全得多。

十八、我建议你把第二轮拆成 6 个里程碑
R2-01
Domain Boundary Map
        ↓
R2-02
Order Command / State Boundary
        ↓
R2-03
Cross-domain Transaction Map
        ↓
R2-04
Outbox / Event Boundary
        ↓
R2-05
Read Model / Report Boundary
        ↓
R2-06
Multi-instance + Observability

而：

Permission
AI
Money
CI

作为贯穿层，而不是再单独做成一堆孤立整改。

十九、每个里程碑必须有“退出条件”

这是你第二轮最需要新增的工作方式。

例如 R2-02 Order Boundary 不应该以：

“代码拆完了。”

作为完成。

而应该：

✅ 所有订单状态变化都有唯一入口
✅ API 不直接改变 order.status
✅ AI 走同一 Command
✅ 原有 API 契约不变
✅ 原有 1015 tests 全绿
✅ E2E 全绿
✅ 反向验证能抓住绕过路径

这样才叫完成。

二十、最终你要得到的不是一张更漂亮的架构图

而是这样一个系统：

                         User
                          │
                    Role / Capability
                          │
                          ↓
                       Command
                          │
            ┌─────────────┼──────────────┐
            ↓             ↓              ↓
         Order          Money         Inventory
         Domain         Domain         Domain
            │             │              │
            └─────────────┼──────────────┘
                          ↓
                     Transaction
                          │
                ┌─────────┴─────────┐
                ↓                   ↓
               DB                Outbox
                                    │
                      ┌─────────────┼─────────────┐
                      ↓             ↓             ↓
                    Notify        Stats          AI

同时：

          Source of Truth
                 ↓
           Machine Contract
                 ↓
      ┌──────────┼──────────┐
      ↓          ↓          ↓
     API        AI          UI

这才是你第二轮整改最终应该追求的形态。

最后给你一个很重要的“总施工纪律”

以后你看到任何架构问题，先连续问自己五个问题：

1. 这是一个具体 bug，
   还是一个边界问题？

2. 如果是边界问题，
   谁应该拥有这个事实？

3. 能不能通过改变依赖方向解决，
   而不是增加一个检查器？

4. 能不能让错误结构在代码层直接无法表达？

5. 怎样证明这次整改真的完成，
   而不是“看起来完成”？

这五个问题会帮你避免重新陷入第一轮最容易出现的路径：

发现问题
 ↓
写检查器
 ↓
发现新问题
 ↓
再写检查器
 ↓
检查器越来越多
 ↓
系统还是靠人为理解维持

第一轮已经把 “纪律” 建起来了：当前有 103/103 静态检查、完整 E2E 常闸以及反向验证体系。

第二轮要做的是把“纪律”进一步沉淀成“结构”。

所以我给你定义的第二轮核心任务不是：

“继续整改 20 个问题。”

而是：

“让 SOrders 从一个需要很多规则来保护的系统，逐渐变成一个边界本身就能保护自己的系统。”

这会是这份项目下一阶段最关键的架构跃迁。