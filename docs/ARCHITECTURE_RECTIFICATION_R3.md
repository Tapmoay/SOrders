SOrders 第三轮整改方案
从“结构正确”进入“运行时正确”

第二轮已经把大量问题变成了可执行的结构契约：15 个域、57 条命令、10 条跨域事务、18 个事件、26 条 Capability，订单 API 直写状态已经为 0，报表已经退出写模型，Outbox 已具备幂等，Trace 也已经建立。

所以第三轮不要再继续大规模重构业务代码。

这一轮应该解决的是：

这些边界在真实进程、真实数据库、真实客户端、真实多实例、真实生产环境中，是否仍然成立？

你的第二轮报告已经把剩余问题非常清楚地指出来了：

Migration 仍然在 import app.database 时执行；
Capability 还没有进入 Android UI 和 Audit；
多实例还有 4 道门没闭合；
最终代码还没有部署到生产；
requirements.txt 是否锁版本尚未决定。

因此我建议把第三轮正式定成：

R3：Runtime Integrity & Production Readiness

运行时完整性与生产就绪整改

一、第三轮的总体结构

我建议不要再按“发现一个问题修一个问题”的方式推进，而是固定成 7 个里程碑：

R3-01  Migration Lifecycle
        ↓
R3-02  Capability → UI / Audit
        ↓
R3-03  Multi-Instance Runtime
        ↓
R3-04  Runtime Observability
        ↓
R3-05  Production Deployment
        ↓
R3-06  Production Verification
        ↓
R3-07  Meta-System Hardening

其中依赖关系是：

R3-01
  ↓
R3-03
  ↓
R3-05
  ↓
R3-06

而：

R3-02
R3-04
R3-07

可以部分并行。

二、R3-01：彻底解决 Migration Lifecycle

这是第三轮最高优先级。

第二轮报告已经明确确认：

backend/app/database.py
        ↓
import 时
        ↓
bootstrap_schema(engine)
        ↓
DDL

也就是说，不只是“启动时迁移”，而是：

import database 就可能修改数据库。

报告甚至在制作只读 Trace 工具时真实撞到了这个问题。

这必须在第三轮解决。

R3-01-A：建立明确生命周期

最终目标：

Build
  ↓
Deploy artifact
  ↓
Migration Job
  ↓
Migration Success
  ↓
Application Start

禁止：

import
  ↓
DDL

也禁止：

application startup
  ↓
偷偷迁移

第二轮报告本身已经把这个目标明确写成：

deploy → migration job → success → application start。

R3-01-B：拆分两个职责

原来的：

bootstrap_schema

应该拆成概念上的：

Migration Engine
+
Database Runtime
Database Runtime

只负责：

engine
session
connection
transaction
Migration Engine

只负责：

migration version
migration ordering
migration locking
migration execution
migration status
R3-01-C：建立 Import Purity 判据

新增一个非常重要的架构契约：

import app.database

不能产生：

CREATE
ALTER
DROP
INSERT
UPDATE
DELETE

任何副作用。

这个判据最好做成真正的反向验证：

注入一个 import
→ 检查数据库 schema version
→ 必须完全不变

这是第三轮第一个非常值得拥有的 Checker。

因为它不是“多一个红线”，而是在守一个极重要的架构不变量：

Import 不得产生持久化副作用。

R3-01-D：部署层明确执行 Migration

最终：

deploy.sh
 ├── acquire deployment lock
 ├── migration status
 ├── migration upgrade
 ├── verify
 └── start service

而 systemd：

sorders-api.service

只负责：

启动已经准备好的应用

而不是：

负责准备数据库
R3-01-E：必须做三个测试
测试 1：Migration Fresh DB
空数据库
↓
migration
↓
current version
↓
启动
测试 2：Migration Old DB
version N
↓
migration
↓
version N+1
测试 3：双实例同时 migration
Instance A ─┐
            ├─ migration
Instance B ─┘

只能一个实际执行。

另一个应该：

等待
↓
发现已经完成
↓
继续启动
R3-01 的退出条件
✅ import app.database 不执行 DDL
✅ application startup 不执行 migration
✅ migration 有唯一入口
✅ migration version 正确
✅ migration 单实例通过
✅ 双实例并发 migration 通过
✅ migration 失败不会启动半残服务
✅ 当前 7 → 新版本迁移成功
✅ 现有 1015 tests 全绿
✅ 112 checks 全绿
三、R3-02：Capability Registry 真正完成“四端同源”

第二轮目前已经做到：

Capability
 ├── API ✅
 └── AI ✅

但：

 ├── UI ❌
 └── Audit ❌

报告已经明确列为欠账。

这一轮应该正式完成。

四、R3-02-A：Android UI 不再自己判断权限

现在类似：

if (role == Dispatcher) {
    showButton()
}

应该逐步转成：

Capability
    ↓
User Capability Set
    ↓
UI

例如：

order:assign

UI 只问：

capability.can("order:assign")

而不是：

role == dispatcher
R3-02-B：不要把 Capability Registry 直接复制到 Android

非常重要。

不要：

Backend capabilities.py
        ↓
复制
        ↓
Android Capability.kt

然后两边人工同步。

应该：

Backend Source of Truth
        ↓
Machine-readable artifact
        ↓
Android generated snapshot

或者由 API 在登录/会话初始化时提供：

/me/capabilities

但具体选择需要根据你当前的 App 架构验证，不能仅凭这份报告断言哪一个更适合。

核心原则只有一个：

Android 不能再拥有第二份独立 Capability 真相。

五、R3-02-C：Audit 同样接入 Capability

现在已经有：

Capability.kind

分：

read
write

但还没有和：

OperationAction

建立机器对账。

因此建立：

Capability
      ↓
Action Vocabulary
      ↓
OperationAction

然后检查：

write capability
→ 必须对应 audit action

但这里一定注意：

不要假设“一个 capability = 一个 audit action”。

有些业务动作可能：

一个 capability
→ 多个具体 audit events

所以你真正需要定义的是：

Capability
    ↓
Audit Coverage

而不是简单一一映射。

六、R3-02-D：最后做“四端一致性”

最终希望：

                  Capability
                      │
         ┌────────────┼────────────┐
         ↓            ↓            ↓
        API           AI           UI
         │
         ↓
       Audit

然后机器可以回答：

dispatcher 是否拥有 order:assign？

答案应该在：

API
AI
UI
Audit

四个地方一致。

R3-02 退出条件
✅ 26/26 capabilities 有执行点
✅ API 使用 Capability
✅ AI 使用同一 Capability
✅ UI 不再自行定义角色能力
✅ Audit action 可以证明 write capability 的留痕覆盖
✅ 任意 capability 改动能够使相关生成物 / 检查立即变化
✅ 不存在第二份静态 Capability 真相
七、R3-03：真正完成 Multi-instance Runtime

第二轮有：

10 道门
6 ✅
4 ❌

剩下：

启动期自愈
上传目录共享
定时任务选主
nginx upstream + failure removal

第三轮这里不能只继续写文档。

必须真正跑起来。

八、R3-03-A：解决 Upload Shared Storage

现在两个实例：

A → /opt/SOrders/uploads
B → /opt/SOrders/uploads

如果这是两个独立磁盘：

用户上传到 A
↓
B 看不到

所以必须明确一种运行模型：

Shared Filesystem

或者：

Object Storage

但是第二轮报告的第一轮背景里明确说过对象存储目前并未真正接入，所以这里不能直接假设你会用 OSS。

因此这一项必须先做架构决策：

图片和导出文件未来究竟是不是本地文件系统资产。

不要边开发边决定。

九、R3-03-B：Scheduler Leader Election

现在单实例的时候：

每日任务
   ↓
一个进程

两实例之后：

A → 每日清理
B → 每日清理

就可能执行两次。

所以建立：

Scheduler
    ↓
Leader Lock

最简单可以先使用 DB advisory lock，因为你已经有 MySQL GET_LOCK 的基础。

但是注意：

Migration Lock 和 Scheduler Lock 不是同一个锁。

必须不同名字、不同生命周期。

例如：

sorders:migration
sorders:scheduler:retention
sorders:scheduler:xxx
十、R3-03-C：Nginx upstream

最终：

nginx
  │
  ├── instance A
  └── instance B

要求至少验证：

A 挂了
↓
B 仍可服务

B 挂了
↓
A 仍可服务

同时测试：

REST
Socket.IO
静态资源
上传

尤其是 Socket.IO。

因为报告里已经明确指出，多 worker / 多实例推送必须正确使用 Redis 适配。

十一、R3-03-D：真正做“双实例实验”

这是第三轮的硬门槛。

不要：

“代码看起来支持双实例”

要：

Instance A
Instance B

真正同时启动。

然后跑：

实验 1
A 接请求
B 接请求
实验 2
A 建连接
B 发送事件
实验 3
A 执行 migration
B 同时启动
实验 4
A 获得 scheduler lock
B 尝试获得
实验 5
A 上传
B 查询
实验 6
杀掉 A

然后：

B

必须继续工作。

十二、R3-04：把 Trace 从“排障工具”升级成 Runtime Observability

你现在已经有：

订单
→ 命令 / request_id
→ 账本
→ 司机账单
→ 事件
→ 通知

这是非常好的基础。

第三轮不要丢掉 _trace_order.py。

而是把它变成：

人类可读的最终诊断接口。

R3-04-A：定义 Trace ID 层次

建议至少明确三个概念：

request_id
command_id
event_id

它们不要混成一个。

例如：

request_id
    ↓
command_id
    ↓
OrderCompleted
    ↓
event_id

一个 HTTP 请求可以触发：

多个 command
多个 event

所以不能假设：

1 request = 1 event
十三、R3-04-B：给关键业务指标增加 Metrics

现在你已经有 AI 的两个指标，所以第三轮可以把指标体系扩展到真正的业务链路。

至少建议：

orders_created
orders_assigned
orders_accepted
orders_delivered

commands_success
commands_failed

events_published
events_retried
events_dead

notifications_created
notifications_deduplicated

migration_duration
migration_failure

scheduler_acquired
scheduler_skipped

request_latency

这些是方案建议，不是第二轮报告中已经存在的事实。

所以实施时需要结合项目真实运行数据决定哪些真正有价值。

十四、R3-04-C：不要一开始上大型 Observability 平台

这点非常重要。

你第三轮不是：

Prometheus
Grafana
Jaeger
Loki
OpenTelemetry
ELK

全家桶一起上。

第一步只做：

structured logs
+
request_id
+
command_id
+
event_id
+
关键 metrics

先让：

“发生了什么”能回答。

之后再决定是否值得接完整平台。

十五、R3-05：生产部署成为真正的整改对象

这一项是第三轮最终的“现实考试”。

第二轮报告明确写着：

生产现在跑的仍然是旧代码。

因此前面的：

112/112
1015 passed
E2E
Domain
Outbox
Capability

都还是：

工程环境证据。

第三轮必须把它变成：

生产环境证据。

十六、R3-05-A：先建立 Release Candidate

不要直接：

main → production

先生成：

R3 Release Candidate

记录：

Git SHA
DB migration version
Android version
Backend version
Frontend version
requirements lock
config checksum

并做：

artifact checksum
十七、R3-05-B：生产发布采用“先迁移、后应用”

目标：

Production

1. backup
2. migration
3. verify
4. start new backend
5. health
6. readonly smoke
7. business smoke

而不是：

restart systemd
↓
hope

这正是本轮 Migration 解耦最终需要落地的生命周期。

十八、R3-05-C：生产只读验收

你已经有：

_trace_order

和生产只读体检体系。

第三轮应该建立一份：

PRODUCTION_ACCEPTANCE.md

至少验证：

/health
登录
查订单
查账
查司机账单
查通知
Trace 一单
Capability
Migration version
Redis
DB
uploads

注意：

第一阶段不要直接拿生产做完整写操作测试。

先：

Read-only

再有限写操作。

十九、R3-06：建立真正的 Production Failure Drill

这是我很建议你在第三轮加入的内容。

不是只验证：

“正常时能不能跑。”

还要验证：

“故障时能不能恢复。”

例如：

Drill A
Kill worker

是否恢复？

Drill B
Redis unavailable

业务还能不能工作？

Drill C
Event consumer delayed

业务数据是否仍然正确？

Drill D
Migration lock contention

第二实例是否正常等待？

Drill E
Disk nearing full

是否能够发现？

这些是基于当前架构提出的运行演练方案，不代表报告已经做过这些测试。

二十、R3-07：最后一项不是业务架构，而是“整改系统自身”

这一项其实是从你第二轮报告里长出来的。

你已经真实发现：

reports_source 重复定义
↓
静默覆盖

又发现：

reports_files 路径口径错误

又发现：

reverse verify 还原不完整

又发现：

capabilities 文档说过头

所以第三轮应该建立：

Meta-System Integrity

也就是：

整改系统必须证明自己不会欺骗你。

二十一、Meta-System 要检查什么？
1. Checker 不允许静默空转

例如：

目标文件不存在

不能：

found = []
→ 0 个问题
→ success

必须：

ERROR:
target discovery returned empty

这类防线尤其值得保留，因为第二轮已经真实遇到“检查器自己失效”的情况。

2. Reverse Verify 必须保证完整恢复

最终应该机器证明：

before snapshot
=
after restore snapshot

不是：

看起来差不多

第二轮已经把某个 restore 问题加强到 30/30，并做到 20 个文件逐字节一致。

第三轮把它上升为正式基础设施规则。

3. Generated Artifact Freshness

例如：

Endpoint Index
AI Catalog
Capability Snapshot
Acceptance Report

必须有：

source hash
generated_at
source commit

这样才能回答：

“这个文档究竟对应哪一版代码？”

二十二、第三轮关于 Requirements Lock：不要让它变成“顺手就锁了”

报告明确写着：

backend/requirements.txt 是否锁版本仍然没有决定。

第三轮要做的不是：

直接全锁

而应该先做一个：

Dependency Reproducibility Decision

检查：

目前开区间
↓
当前实际安装版本
↓
CI 实际版本
↓
生产实际版本
↓
是否一致

然后才决定：

严格 pin

还是：

major/minor bounded

这需要你根据项目的升级策略拍板。

二十三、第三轮完整执行顺序

我会建议你严格按这个顺序：

R3-00  Baseline
   ↓
R3-01  Migration Lifecycle
   ↓
R3-02  Capability UI / Audit
   ↓
R3-03  Multi-instance
   ↓
R3-04  Observability
   ↓
R3-05  Production RC
   ↓
R3-06  Production rollout
   ↓
R3-07  Failure drill
   ↓
R3-08  Meta-system hardening

注意我故意把：

R3-08

放在生产之后。

因为你现在需要验证：

整改体系保护的是实际系统，而不是保护一份漂亮的整改报告。

二十四、每个阶段都必须用“退出条件”结束

这是第三轮和之前最大的不同。

例如 R3-01：

✅ import database 无副作用
✅ migration 显式执行
✅ startup 不迁移
✅ 7 → current migration
✅ old DB migration
✅ empty DB migration
✅ concurrent migration

R3-02：

✅ API Capability
✅ AI Capability
✅ Android UI Capability
✅ Audit Capability
✅ 无第二份权限真相

R3-03：

✅ 两实例同时运行
✅ migration 只执行一次
✅ scheduler 只执行一次
✅ upload 一致
✅ Socket 正常
✅ A 挂 B 继续
✅ B 挂 A 继续

R3-05：

✅ backup
✅ migration
✅ deploy
✅ health
✅ read-only smoke
✅ trace
✅ rollback / forward-fix plan

没有达到退出条件：

里程碑就是没完成。

不要用“已经差不多了”。

二十五、第三轮最重要的施工原则
原则一：这轮不再以“代码量”为成果

第二轮你们已经产生：

94 actual files
+9066 lines

其中 _tools 占 4715 行。

第三轮不要再追求：

“这轮又改了几千行。”

恰恰相反：

第三轮应该尽可能少改业务代码，多改运行时边界和验证方式。

原则二：能通过边界解决，就不要增加 Checker

保持第二轮自己提出的原则：

先改边界，再加检查器。

第三轮尤其如此。

原则三：任何“已完成”必须分成三层

以后报告统一写：

Code Ready
CI Proven
Runtime Proven

例如：

Migration
✅ Code Ready
✅ CI Proven
❌ Production Proven

这样绝对不会再把：

“代码支持”

误写成：

“生产已经支持”。

原则四：不再允许“文档语义超过代码事实”

第二轮已经发生过一次：

文档说 UI / Audit 已接 Capability
实际上没有

所以第三轮报告必须遵守：

Fact first, wording second.

甚至可以把报告生成流程固定成：

machine output
↓
human explanation
↓
final report

而不是反过来。

原则五：第三轮必须真正做“故障”

第二轮最漂亮的经验是：

先让“没跑”变成红，问题才会暴露。

第三轮把这条思想再推进：

先主动制造故障，才能证明系统真的能恢复。

所以：

kill
timeout
duplicate
concurrent
network failure
database lock
worker crash

都应该成为正式测试对象。

二十六、第三轮最终验收矩阵

我建议你最后生成一张类似：

能力	代码	CI	Staging	Production	Failure Drill
Migration	✅	✅	✅	✅	✅
Order Command	✅	✅	✅	✅	✅
Money	✅	✅	✅	✅	✅
Capability API	✅	✅	✅	✅	✅
Capability AI	✅	✅	✅	✅	✅
Capability UI	✅	✅	✅	✅	✅
Capability Audit	✅	✅	✅	✅	✅
Outbox	✅	✅	✅	✅	✅
Scheduler	✅	✅	✅	✅	✅
Upload	✅	✅	✅	✅	✅
Socket multi-instance	✅	✅	✅	✅	✅
Trace	✅	✅	✅	✅	✅

这张表非常有价值。

因为它会强迫你区分：

“代码里有”

和：

“真实运行里成立”
二十七、第三轮结束后，SOrders 才会进入第四个阶段

如果 R3 真正完成，那么整个项目会变成：

第一轮
防止乱
↓
第二轮
定义谁负责什么
↓
第三轮
证明运行时真的成立
↓
第四轮
性能 / 容量 / 演进

第四轮才适合开始讨论：

读模型
缓存
容量规划
数据库扩展
对象存储
高可用
弹性扩容
更复杂的异步

而不是现在提前做。

最终我给你一个第三轮“总任务树”
SOrders R3
│
├── R3-01 Migration Lifecycle
│   ├── remove import-time DDL
│   ├── explicit migration job
│   ├── migration verification
│   └── concurrent migration test
│
├── R3-02 Capability Unification
│   ├── Backend ✅
│   ├── AI ✅
│   ├── Android UI
│   └── Audit
│
├── R3-03 Multi-Instance Runtime
│   ├── shared uploads
│   ├── scheduler leader
│   ├── nginx upstream
│   ├── socket
│   └── real dual-instance test
│
├── R3-04 Observability
│   ├── request_id
│   ├── command_id
│   ├── event_id
│   ├── business metrics
│   └── runtime trace
│
├── R3-05 Production Release
│   ├── release candidate
│   ├── backup
│   ├── migration
│   ├── deploy
│   └── smoke test
│
├── R3-06 Failure Drill
│   ├── worker crash
│   ├── Redis failure
│   ├── duplicate event
│   ├── migration contention
│   └── instance failure
│
└── R3-07 Meta-System Integrity
    ├── checker non-empty discovery
    ├── reverse-verify restoration
    ├── generated artifact freshness
    ├── report fact checking
    └── dependency reproducibility
第三轮最核心的一句话

第二轮是在问：“架构上有没有定义清楚？”

第三轮是在问：“真实世界一运行，它还成立吗？”

而你现在已经非常适合做这个跃迁了：第二轮的 15 域、57 命令、18 事件、26 Capability、Outbox、Trace 已经提供了足够明确的结构基础。

所以第三轮不要再追求“更多抽象”，而要追求“更多真实证据”。

尤其是这四件事，我会把它们视为 R3 的四根主梁：

Migration 不再有隐式副作用
Capability 真正四端同源
两个实例真的同时跑过
生产真的跑过并经历过故障演练

这四件事闭合以后，你的 SOrders 才真正从“架构上已经设计好了”进入“这个架构已经被运行事实证明过”的阶段。