# SOrders 架构整改报告（原文存档）

> **本文件是外部评审报告的逐字存档**（2026-09-24 由用户提供），sha256 `1838dd55ac79660873dd74d71347ee2527b8de3157f47e93b6a19221a5f2c8c2`，
> 保存时不改一字（行数 1466 / 25224 字节，与来源一致）。
>
> **它是一份建议，不是事实源**：里面的数字（227 端点 / 45 表 / 92 红线 / 1697 行 schema_bootstrap …）
> 是报告成文当时的快照，**已经与实际漂移**。核过的实测值见 [BASELINE.md](BASELINE.md)。
>
> 落地进度与逐条对照见 [RECTIFICATION_PLAN.md](RECTIFICATION_PLAN.md)（阶段 / 做什么 / 状态 / 提交）。

---

可以。既然你现在问的是“**这份实际架构到底应该怎么修**”，我建议不要把它当成一张待重画的架构图，而是把它当成一个**正在运行的系统进行分阶段改造**。

而且有一个很重要的前提：

> **不要推倒重写。**
>
> 这份报告已经证明，SOrders 其实有一套相当强的正确性防线：六态订单、钱的单一口径、UTC 时间口径、软删恢复、AI 写入闸门，以及静态红线 + 反向验证 + 单测 + 库内不变式四层验收。真正的问题是，这些能力很多还停留在“约定、冻结、检查器”层面，而没有全部变成代码结构本身的约束。 

所以你的改造目标不是“换成更高级的技术”，而是：

> **把现在靠人记、靠脚本查、靠文件冻结维持的安全性，逐步变成架构本身天然保证的安全性。**

---

# 一、先建立一张真正的改造路线图

我建议整个项目按这个顺序走：

```text
阶段 0
建立基线 / 补齐真实生产事实
        ↓
阶段 1
先消除“出事了救不回来”的风险
        ↓
阶段 2
把迁移、CI、发布变成自动化基础设施
        ↓
阶段 3
瘦身 API 层，建立真正的业务入口
        ↓
阶段 4
把状态 / 钱 / 权限变成硬边界
        ↓
阶段 5
建立可靠事件与查询体系
        ↓
阶段 6
补齐客户端 / AI / 文档的一致性
        ↓
阶段 7
最后再做监控、扩容、多实例
```

**这个顺序非常重要。**

千万不要：

```text
现在 → 重写后端
现在 → 上微服务
现在 → 换数据库
现在 → 上 Kafka
现在 → Kubernetes
```

因为那会同时改变几十个变量，而你现在已经有 227 个端点、45 张表、41 个 service 文件、以及大量核心冻结规则。

---

# 二、阶段 0：先建立“真实世界基线”

这是你现在第一件应该做的事情。

报告明确存在 10 个信息缺口，包括：

* 生产 systemd 实际配置
* MySQL 实际版本
* nginx 实际加载配置
* CI 是否真的从不跑 `p`
* Redis 生产配置
* H5 是否还有人在用
* AI 读权限实测结果
* 当前 92 个红线 / 108 个反向验证是否全绿
* LLM 调用的细节等。

所以第一阶段不要改代码。

### 先做一个 `BASELINE.md`

固定记录：

```text
Git commit:
Branch:

Backend tests:
Static checks:
Reverse verification:
Android unit tests:
Frontend build:

Production:
- nginx config hash
- MySQL version
- Redis config
- systemd unit
- disk usage
- DB size
- upload size
- certificate expiry

Current endpoint count:
Current table count:
Current Android module count:
```

再保存一份：

```text
before/
```

作为“改造前快照”。

### 注意

你这个仓库现在还有**另一个 AI 会话的未提交改动**，报告明确说明当前工作区存在两个未提交文件。

所以以后所有结构性改造之前：

> **先处理并明确这些工作区改动属于谁、是否保留。**

否则你会出现一种非常麻烦的情况：

```text
你以为这是你的重构结果
其实是两个 AI 会话混合结果
```

---

# 三、阶段 1：先把“灾难不可恢复”问题消掉

这是优先级最高的一层。

报告里 R1、R2 都是**极高风险**：

```text
R1：
schema_bootstrap.py
1697 行
启动即执行 DDL
没有 migration version table

R2：
没有真正脚本化的 backup / rollback
恢复没有实战演练
```



---

## 1. 先建立真正的数据库备份系统

至少形成：

```text
backup/
├── db/
│   ├── daily/
│   ├── weekly/
│   └── pre_release/
├── uploads/
└── metadata/
```

每次生产发布：

```text
Pre-release
   ↓
DB backup
   ↓
Uploads backup
   ↓
Git commit/tag
   ↓
Deploy
```

而不是：

```text
deploy
  ↓
出问题
  ↓
“好像以前有个 mysqldump”
```

报告原有建议就是把 `mysqldump + 代码 tar + 一键回滚` 脚本化，并进行一次真实恢复演练。

### 最重要的注意事项

**恢复演练必须真的做。**

不是：

```text
脚本 exit 0
```

而是：

```text
创建测试数据库
→ 恢复
→ 启动
→ 跑关键 API
→ 验证订单 / 钱 / 状态
→ 删除测试库
```

---

# 四、阶段 2：先解决你整个系统里最大的基础设施问题——Schema Migration

这是我认为**整个架构改造的第一核心任务**。

现在：

```text
app.database
   ↓
schema_bootstrap
   ↓
启动
   ↓
ALTER TABLE
```

而 `schema_bootstrap.py` 已经达到 1697 行，并且它实际上承担了迁移职责。

风险就是：

```text
应用启动
    =
数据库迁移
    =
服务可用性
```

报告的历史事故也正是这里发生过启动崩溃循环。

---

## 不要直接“一把梭哈 Alembic”

我建议分三步。

### Step 1：先给现有 bootstrap 加“版本表”

例如概念上：

```text
schema_versions

version
applied_at
checksum
description
```

然后变成：

```text
启动
 ↓
检查 schema version
 ↓
已经执行？
 ├─ 是 → 跳过
 └─ 否 → 执行 migration
```

这样至少解决：

```text
不知道数据库现在是什么状态
```

---

### Step 2：把每次 schema 修改变成独立 migration

不要继续：

```text
schema_bootstrap.py
  1697 行
  永远继续加
```

而是：

```text
migrations/
├── 001_initial.py
├── 002_add_order_x.py
├── 003_add_return_y.py
├── 004_add_index_z.py
└── ...
```

---

### Step 3：最后再决定是否完整迁移 Alembic

报告本身给出的中期建议也是：

> 给 `schema_bootstrap` 加迁移版本表，或引入 Alembic，但保留“启动即自愈”的兜底。

我更建议：

```text
Migration = 正式变更机制
Bootstrap = 小型运行时自愈机制
```

而不是继续让 bootstrap 同时负责两个角色。

---

# 五、阶段 3：修 CI，不然所有架构改造都没有自动护栏

现在你的质量体系非常强：

```text
92 checks
108 reverse verification
820 backend tests
1126 Android tests
```

但 CI 并没有把它们真正接管：

* CI 只挂 `main/develop`
* 不跑 92 个红线
* 不跑 Android 单测
* 不构建 APK
* 不构建前端。

这其实是非常大的浪费。

你已经造好了“检测器”，只是没有接到自动生产线上。

---

## CI 最终应该变成：

```text
Pull Request
     ↓
┌─────────────────────┐
│ Fast Gate < 30 sec  │
├─────────────────────┤
│ syntax              │
│ changed checks      │
│ endpoint freshness  │
│ core freeze         │
└─────────────────────┘
     ↓
┌─────────────────────┐
│ Normal Gate         │
├─────────────────────┤
│ backend tests       │
│ android unit tests  │
│ frontend build      │
│ API contract        │
└─────────────────────┘
     ↓
┌─────────────────────┐
│ Slow / Nightly      │
├─────────────────────┤
│ reverse verify      │
│ fuzz                │
│ production probes   │
└─────────────────────┘
```

报告已经明确建议把 92 个检查分成“秒级必跑”和“分钟级慢跑”。

这是非常值得你做的。

---

# 六、阶段 4：开始真正处理架构本体——API 层过厚

现在：

```text
api/v1 = 13,724 行
services = 9,837 行
```

最大的：

```text
orders.py = 2055 行
25 endpoints
50 functions
```

并且 reports 的聚合逻辑也直接写在 API 层。

这个问题不要通过“重写订单模块”解决。

### 正确办法：纯搬迁。

例如：

```text
orders.py

        ↓

orders/
├── create.py
├── assign.py
├── complete.py
├── payment.py
├── query.py
└── return.py
```

但是：

```text
URL 不变
Request 不变
Response 不变
权限不变
状态机不变
数据库不变
```

只改变代码组织。

这正是报告建议的：

```text
orders_assign.py
orders_complete.py
orders_payment.py
orders_query.py
```

然后统一由 `router.py` 挂载。

### 这一步的绝对注意事项

> **不要边搬边优化业务逻辑。**

一定严格遵守：

```text
Refactor A
↓
验证
↓
Refactor B
↓
验证
```

不要：

```text
拆 orders.py
+ 改状态机
+ 改权限
+ 改 schema
+ 改 SQL
```

这样一旦出错，你根本不知道是哪一层导致的。

---

# 七、阶段 5：把“领域真相”从文件冻结升级为代码边界

这是整个项目**最核心的一次架构升级**。

目前你已经有：

```text
order_money.py
driver_pay.py
order_return.py
accounting_service.py
shipper_settle.py
```

而且明确要求核心冻结。

这套方法很好。

但它的问题是：

> “不要碰它”不是架构。

所以你的下一步应该是：

```text
以前：

谁想用就 import 文件
       ↓
靠 freeze 保证


以后：

Domain Contract
       ↓
接口
       ↓
唯一实现
       ↓
所有消费方依赖接口
```

例如：

```text
OrderMoneyCalculator
DriverPayCalculator
SettlementService
```

让：

```text
reports
ledger
driver settlement
AI
API
```

都依赖同一个契约。

报告长期建议本身也是这么写的：把“钱的单一实现”从**文件约定**升级成**显式接口边界**。

---

# 八、阶段 6：状态机必须变成“唯一写入口”

这一点我建议你特别注意。

现在六态订单是非常重要的核心：

```text
PENDING_DISPATCH
DISPATCHED
ACCEPTED
DELIVERED
CANCELLED
RETURNED
```

而报告明确把订单状态机列为必须保留的核心。

但目前状态修改并非绝对单入口。

所以你的目标应该是：

```text
任何地方
   ↓
Command
   ↓
OrderFlow
   ↓
State Transition
```

例如：

```text
AssignOrder()
AcceptOrder()
CompleteOrder()
CancelOrder()
RecallOrder()
ReturnOrder()
```

而不是让某个 API handler：

```python
order.status = ...
```

直接改变状态。

---

## 最终应该形成这种结构

```text
HTTP
Socket
AI
Job
Admin
    ↓
Command
    ↓
Application Service
    ↓
OrderFlow
    ↓
validate transition
    ↓
mutate state
    ↓
emit event
```

这样未来你增加一个：

```text
AI 完成订单
```

也不会出现：

```text
AI 有自己的状态逻辑
API 又有自己的状态逻辑
```

---

# 九、阶段 7：权限系统也要从“很多判断”变成统一模型

现在权限有：

```text
RBAC
+
require_permission
+
require_roles
+
函数内部判断
+
行级过滤
```

而且还有：

```text
26 permissions
5 个无端点引用
dispatcher 恒通过
```



所以你下一步不是增加更多权限。

恰恰相反：

> **先把授权机制统一。**

目标：

```text
User
 ↓
Role
 ↓
Permission
 ↓
Action
 ↓
Resource
 ↓
Scope
```

例如：

```text
orders.assign

role:
dispatcher

resource:
Order

scope:
all pending orders
```

而不是：

```python
if user.role == "dispatcher":
```

散落在 20 个文件。

---

# 十、阶段 8：建立真正可靠的事件边界

这部分是我基于你这份架构继续往前推的一步。

现在：

```text
业务操作
 ↓
数据库
 ↓
background task
 ↓
Socket.IO
```

而你之后业务越来越多：

```text
订单完成
 ↓
账本
 ↓
司机账单
 ↓
报表
 ↓
通知
 ↓
AI memory
```

这时候我建议引入一个概念：

# Outbox Pattern（事务发件箱）

不急着上 Kafka。

可以仍然保持：

```text
MySQL
+
FastAPI
+
Redis
```

但：

```text
事务
 ├─ 修改订单
 └─ 写 event_outbox
        ↓
     worker
        ↓
   推送 / 通知 / 统计
```

这样不会发生：

```text
数据库成功
↓
后台任务恰好挂了
↓
事件永远丢失
```

而且这与你当前“不做 MQ”的产品约束并不冲突。

你现在完全可以先：

```text
DB Outbox
+
Background Worker
```

而不是马上上 Kafka。

---

# 十一、阶段 9：客户端也要逐渐从“大文件”中拆出来

Android 目前几个文件已经很大：

```text
AiWriteService.kt 3040
AiWrite.kt 2548
AiWriteTest.kt 5796
Dtos.kt 2065
Apis.kt 1605
OrderCreateScreen.kt 1505
```

报告把它列为 R17。

我的建议不是“为了整洁而拆”。

只有当文件存在：

```text
多个职责
多个修改者
多个生命周期
多个测试边界
```

才拆。

比如：

```text
AiWriteService
    ↓
├── AiWritePreview
├── AiWriteExecutor
├── AiWriteConfirmation
├── AiWriteBatch
└── AiWriteAudit
```

而不是简单：

```text
3000 行
→
6 个 500 行文件
```

文件变小不等于架构变好。

---

# 十二、阶段 10：AI 暂时不要急着“服务端化”，先做一致性

报告当前的 AI 模型其实很明确：

```text
Android Agent
 ↓
LLM
 ↓
后端 API
```

AI 写操作还有：

```text
preview_write
 ↓
确认卡
 ↓
AiWriteService.execute
```

这个闸门应该保留。

当前真正的问题不是：

> “AI 为什么不在服务器？”

而是：

> **AI 能看到/能做什么，和后端真正允许什么，必须来自同一套事实。**

现在已经存在：

```text
AI catalog
≠
实际后端权限
```

的对账需求。报告建议把 `_probe_read_roles.py` 纳入 CI。 

所以先做：

```text
Backend Permission
        ↓
生成 AI capability catalog
        ↓
AI
```

而不要：

```text
Backend 一套权限
AI 一套权限
两边人工同步
```

---

# 十三、阶段 11：文档系统必须从“手写知识库”转成“事实生成系统”

你现在的文档已经非常庞大：

```text
docs/ 502 files
PROJECT_MAP
AI catalog
endpoint index
domain model
AI_WORK_CLAIM
...
```

但是已经出现实际漂移：

```text
文档 36
代码 56

文档 70%
代码 80%

文档 155 endpoints
代码 227
```



所以以后任何“会变化的数字”都不要手写。

错误：

```markdown
系统现在有 227 个 API
```

正确：

```text
生成器 → endpoint-index.json
文档引用生成物
```

也就是说：

```text
Code
 ↓
Generator
 ↓
Machine-readable artifact
 ↓
Docs
AI Catalog
QA
```

**代码才是事实源。**

这一点报告也已经明确提出。

---

# 十四、阶段 12：再补测试，而不是盲目增加测试数量

你现在最大的测试问题不是：

> 测试少。

反而已经有：

```text
820 backend tests
1126 Android tests
```



真正缺的是：

### Android Integration Test

至少补：

```text
登录
 ↓
导航
 ↓
下单
```

这三条主链。

报告也是这么建议的。

前端则不要含糊。

只有两个选项：

```text
继续维护
→ 纳入 CI + 最小测试

或者

正式归档
→ 从“活系统”身份剥离
```

不要继续保持：

```text
旧系统
但又像新系统
```

报告本身也明确把这项留给产品决定。

---

# 十五、阶段 13：最后再做可观测性

这个阶段很容易被工程师忽略。

现在：

```text
无监控
无告警
无 trace
日志治理也不完整
```

甚至出现过证书过期两个月无人发现的问题。

所以先不要上什么复杂的 observability platform。

只做三个东西：

### ① Request ID

```text
HTTP
 ↓
request_id
 ↓
service
 ↓
DB/log
 ↓
operation_log
```

### ② 业务指标

至少：

```text
orders_created
orders_assigned
orders_delivered
orders_cancelled

ledger_entries
driver_settlements

push_success
push_failure

AI_calls
AI_write_confirmed
```

### ③ 外部监控

```text
/health
certificate expiry
disk
database
```

报告长期建议也明确提出 request trace id。

---

# 十六、什么时候才考虑多实例 / HA？

**现在不要急。**

你现在真正的问题是：

```text
单实例
```

但更本质的问题是：

```text
单实例 + 没有迁移协调
```

因为一旦变成：

```text
Instance A
Instance B
Instance C
```

如果三个一起：

```text
schema_bootstrap()
```

你会得到新的灾难。

所以正确顺序：

```text
Migration versioning
      ↓
Reliable events
      ↓
Observability
      ↓
Backup / recovery
      ↓
再做 multi-instance
```

报告本身也把“多实例 + LB + Redis socket + 托管 MySQL”放在长期，并特别指出必须先解决 `schema_bootstrap` 的启动期 DDL 问题。

---

# 十七、把所有工作压缩成一个实际执行表

| 阶段 | 做什么                            | 是否改业务逻辑 |
| -- | ------------------------------ | ------: |
| 0  | 建立基线、补真实生产信息                   |       否 |
| 1  | 备份 / 恢复演练 / 监控 / 版本统一          |      极少 |
| 2  | Schema migration 版本化           |       否 |
| 3  | CI 正式接管现有检查体系                  |       否 |
| 4  | `orders.py` / `reports.py` 纯搬迁 |       否 |
| 5  | 状态 / 钱 / 权限建立硬入口               |    是，局部 |
| 6  | Outbox / 可靠事件                  |    是，局部 |
| 7  | Android / AI / H5 边界整理         |      少量 |
| 8  | 文档事实源自动化                       |       否 |
| 9  | Android integration tests      |       否 |
| 10 | trace / metrics / alert        |       否 |
| 11 | 多实例 / HA                       |     架构级 |

---

# 十八、最重要的“施工纪律”

这个比具体技术更重要。

## 规则 1：一次只动一个维度

错误：

```text
拆 orders.py
+
改 state machine
+
换 migration
```

正确：

```text
拆 orders.py
→ 全绿
→ commit

迁移系统
→ 全绿
→ commit

状态机
→ 全绿
→ commit
```

---

## 规则 2：核心区绝不边重构边重设计

这些当前必须保持：

```text
money
state machine
time
soft delete
AI write gate
```

报告也明确把它们列为必须保留的核心机制。

---

## 规则 3：每次重构都必须做“等价性验证”

例如拆 `orders.py`：

```text
旧端点集合
=
新端点集合

旧 request
=
新 request

旧 response
=
新 response

旧 permission
=
新 permission
```

不是：

> “我看代码差不多。”

而是机器证明。

---

## 规则 4：先迁移，再删除旧路径

例如：

```text
Old
  ↓
New
  ↓
Dual verification
  ↓
切换
  ↓
观察
  ↓
Delete old
```

不要：

```text
重写
→ 删除
→ 祈祷
```

---

## 规则 5：任何自动化工具都必须自己可验证

你现在已有非常好的经验：

```text
check
+
reverse verify
```

以后继续保持。

尤其是：

```text
AI catalog
Endpoint generator
Migration tool
Permission generator
```

任何“自动生成真相”的工具，都必须拥有：

```text
输入
→ 输出
→ 自检
→ 反向验证
```

---

# 十九、最后给你一张“真正应该达到的最终架构”

不是微服务，而是：

```text
                         Clients
              ┌──────────┼──────────┐
              │          │          │
           Shipper    Dispatcher   Driver
              │          │          │
              └──────────┼──────────┘
                         ↓
                  Application Layer
                         │
      ┌──────────────────┼──────────────────┐
      ↓                  ↓                  ↓
   Order API          Money API         Inventory API
      │                  │                  │
      └──────────────────┼──────────────────┘
                         ↓
                    Domain Layer
                         │
       ┌─────────────────┼─────────────────┐
       ↓                 ↓                 ↓
   Order Domain      Money Domain      Settlement
       │                 │                 │
       └─────────────────┼─────────────────┘
                         ↓
                  Transaction Boundary
                         │
                  ┌──────┴──────┐
                  ↓             ↓
                MySQL        Outbox
                                │
                    ┌───────────┼───────────┐
                    ↓           ↓           ↓
                 Notify       Stats        AI
                    │
                  Socket
```

然后再外围：

```text
                   ┌─────────────┐
                   │    CI/CD    │
                   └──────┬──────┘
                          ↓
                 Static + Tests + E2E
                          ↓
                    Deployment
                          ↓
             Monitoring + Backup + Trace
```

这里最关键的是：

> **客户端不是业务真相。API 也不是业务真相。AI 也不是业务真相。**
>
> **Domain + Database invariants 才是真正的业务真相。**

客户端、AI、报表、通知，都只是消费者或者执行入口。

---

# 二十、如果现在就开始，我建议你的实际顺序

按照你当前这个仓库状态，我会这样排：

### 第 1 周

```text
① 处理当前未提交 AI 会话改动
② 保存 baseline
③ 核对生产真实配置
④ 做 DB + uploads 备份
⑤ 做一次恢复演练
⑥ 证书 / uptime / disk 最小监控
⑦ CI 挂 p/new
```

### 第 2 周

```text
⑧ 版本号统一
⑨ nginx exports deny
⑩ _check_all timeout
⑪ AI_WORK_CLAIM 归档
⑫ 重新跑全量红线
```

这部分基本都是低风险，而且报告已经明确列在 1–2 周路线里。

### 第 1–2 个月

```text
⑬ schema migration versioning
⑭ orders.py 拆分
⑮ reports.py 下沉
⑯ permission model 收敛
⑰ status mutation 单入口
⑱ money contract
⑲ Android integration tests
⑳ 文档事实源自动生成
```

这些对应报告的中期结构性改善。

### 之后

```text
㉑ Outbox / reliable events
㉒ Trace ID
㉓ 业务 metrics
㉔ AI/backend permission 自动对账 CI
㉕ 只读聚合 / 报表优化
㉖ 多实例 / HA
```

长期才考虑这些。

---

## 最后，我特别想提醒你一个容易走偏的地方

你这个项目现在已经有 **“复杂系统工程师最容易掉进去的陷阱”**：

> **发现系统有问题 → 再增加一个工具来检查问题。**

于是：

```text
问题
 ↓
加 check
 ↓
又发现问题
 ↓
再加 reverse verify
 ↓
又发现问题
 ↓
再加文档
 ↓
再加 generator
```

你现在已经有 `_tools/` 325 个 Python 文件、92 个红线、108 个反向验证，而且文档、生成器、检查器之间已经开始发生漂移。 

所以你的下一阶段原则应该从：

> **“发现问题 → 再加一个检查器”**

慢慢变成：

> **“发现问题 → 改变架构，使这种问题以后结构上就不容易发生。”**

这才是真正的架构升级。

而你当前最值得动手的第一处，我会选 **`schema_bootstrap` + 备份恢复 + CI**，而不是订单业务本身。因为这三件事先解决之后，你后面每一次结构重构都会安全很多。报告自身也把迁移、恢复、CI列在最高优先级风险中。
