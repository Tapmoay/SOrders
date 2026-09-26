# 生产故障演练方案（R3-06 · FAILURE DRILL）

> **这份文档是什么**：第三轮指南 §十九（R3-06）要求「不只验证正常时能不能跑，还要验证**故障时能不能恢复**」，
> 并给了五个演练：A 杀掉一个 worker / B Redis 不可用 / C 事件消费者延迟（event consumer delayed）/
> D 迁移锁竞争（migration lock contention）/ E 磁盘将满（disk nearing full）。
> 指南自己的话是：「**这些是基于当前架构提出的运行演练方案，不代表报告已经做过这些测试。**」
>
> **状态（2026-09-26 更新）**：✅ **方案已写**，且 **C 段之后五个演练全部在生产机上真跑过**
> （六阶段 X0–X5；逐字输出在 `_tools/ops/drill_records/*.json`，汇总在 `docs/R3_FAILURE_DRILL_EVIDENCE.md`）。
> 结果 **5 ✅ / 0 ❌**。⚠️ 但第一轮是 **4 ✅ / 1 ❌**：**Drill C 抓到了真缺陷**（发件箱把「投递失败」记成了「已发送」），
> **修完之后重跑**才变成 5/5 —— 这条链（演练 → 缺陷 → 修复 → 重跑）本身就是证据，详见
> `docs/R3_FAILURE_DRILL_EVIDENCE.md` §三·发现 2。Drill D 另抓到一条**跨主机**的结构缺陷（发现 1），
> 用户 2026-09-26 拍板**本轮只记录不修**（它是「跨主机 enable blocker」，混在一起修＝偷偷扩大 R3 范围）。
> 下面每一格的「今天的状态」栏已按实测结果重写。

---

## 一、两条纪律（先说清楚，免得演练变成事故）

1. ⛔ **先备份、后演练**：任何会动到生产库/服务的演练，前面必须先跑 `python _tools/backup/_pre_release.py --note "R3-06 演练前"`；
2. ⛔ **演练要有「怎么停」**：每条演练都写了自己的**终止条件**与**恢复动作**；判读不了（看不出算不算过）就地停下，
   如实写「没验成」，**不许**把「没出事」当成「通过」（本项目的老账：永远绿的检查＝没有检查）。

---

## 二、五个演练

### Drill A · killer worker：杀掉一个 worker 是否恢复（worker）

| | |
|---|---|
| **目的** | 后端是 `systemd` 里 `--workers 2` 起的两个 uvicorn worker：杀掉一个，服务是否仍可用、`Restart=always` 是否把它拉起来、有没有请求被吞 |
| **命令** | 本机预演：`python _tools/ops/_drill.py --case worker-crash --go`（它调 `_dual_instance.py --kill`）；⛔ 生产那一格本工具**不代跑**（只打印过程）：`python _tools/ops/_drill.py --case worker-crash --target prod --go --i-know-prod` |
| **手动等价** | `pgrep -f 'uvicorn app.main'` 找出 pid → `kill -9 <pid>` → 盯 `journalctl -u sorders-api -f` → 再打 `/health` 与一次登录 |
| **期望信号** | ① 另一路请求**不中断**（`/health` 连续 200）；② systemd 在 `RestartSec` 内把 worker 补回来；③ 被杀的 worker 上**在飞的请求**会有失败（这是事实，要如实记下有几条） |
| **判读** | 只要 ① 成立（服务没整体中断）就算过；③ 的失败条数是**已知代价**，写进记录 |
| **实测（2026-09-26）** | ✅ **生产跑过**（`worker-crash-20260926T151826Z.json`，5/5 信号）：SIGKILL 掉 `sorders-api-a` 之后 50 次采样 × 0.5s —— 另一实例 **50/50 = 200**、**经 nginx 的入口 50/50 = 401（一次 5xx 都没有）**、NRestarts 0→1、**恢复 5.5 秒**。⚠️ 与本机预演形态不同：生产是**两个独立 unit**（不是一个 systemd 里 2 个 worker）|

### Drill B · Redis 不可用，业务还能不能工作（redis）

| | |
|---|---|
| **目的** | 生产 Redis 现在**没有被业务用到**（keyspace 空），所以这一格真正要问的是：**断掉它，会不会有任何一条链路受影响** |
| **命令** | 本机真跑（本机没有 Redis ⇒ 现场就是它）：`python _tools/ops/_drill.py --case redis-down --go`；⛔ 生产：`systemctl stop redis` → 打 /health 与几笔真实业务 → **必须放回** `systemctl start redis` |
| **期望信号** | `/health` 里的 `redis` 字段变红但**接口仍可用**；下单/派单/账本读写全部正常（因为它们不经过 Redis） |
| **判读** | 「业务不受影响」＝过；**如果反而挂了**，说明有隐藏依赖 —— 那是一个真缺陷，要当场记下来 |
| **实测（2026-09-26）** | ✅ **生产跑过**（修复后重跑：`redis-down-20260926T155127Z.json`，5/5 信号）：停 Redis 期间 `/health` 如实变成 `redis:error`，而登录 / 读订单 / 读账本 / **写一条消息**全 200；恢复后消费者**自己**把那条事件补投成 `sent attempts=1`。⚠️ **方案里「Redis 没人用」这条前提已过期** —— B 段之后跨实例总线就是它。⚠️ 判据也修过一次：原来拿 `pubsub channels` 当判据，查源码发现监听器是**随第一次 Engine.IO 连接惰性启动**的（`async_server.py:675`）⇒ 改成「投递那条路必须自己回来」 |

### Drill C · event 消费者延迟，业务数据是否仍然正确（event）

| | |
|---|---|
| **目的** | 发件箱（`outbox_events`）的消费者变慢/停住时，**业务本身**（订单、账本）是否仍然正确 —— 即「最终一致」有没有被误当成「同步一致」 |
| **命令** | 本机真跑（发件箱语义：入队→堆积→追平→不重复）：`python _tools/ops/_drill.py --case event-delay --go`；⛔ 生产要等发布之后（生产现在**没有** `outbox_events` 表） |
| **期望信号** | ① 业务写入**照常成功**（发件箱是**先落库后投递**）；② `outbox_events` 里 `pending` 堆起来但**不丢**；③ 消费者恢复后**追平**，且没有重复投递（`event_id` 幂等） |
| **判读** | ①②③ 都成立才算过；⛔ 只看①就下结论＝把「业务没报错」当成「数据一致」 |
| **实测（2026-09-26）** | ✅ **修复后重跑通过**（`event-delay-20260926T154938Z.json`，7/7 信号）。⚠️ **第一轮是不通过的**（5/6）：停 Redis 期间写的那条事件被记成 `sent attempts=0`，而日志里 16 条 `Cannot publish to redis... giving up` —— python-socketio 把 publish 失败吞了。修复（`_StrictRedisManager`：publish 没成功返回就抛）之后重跑：`sent_before_failure=0` / `pending_after_failure=1` / `attempts=2` / `last_error` 219 字符 / `sent_after_recovery=1` / `duplicate_count=0`。⚠️ 生产**已经有** `outbox_events`（A 段带上去了），方案里「没有这张表」那句已过期 |

### Drill D · migration lock 竞争，第二实例是否正常等待（lock）

| | |
|---|---|
| **目的** | 两个实例同时执行迁移时，第二个是**等待**还是**撞车失败**（这正是 R3-01 抓到过的真缺陷：Windows 上那把锁曾经等于没有） |
| **命令** | 本机真跑：`python _tools/ops/_drill.py --case lock-contention --go`（调 `_migration_tests.py --concurrent`）；⛔ 生产上只能靠「发布时两个实例同时启动」来验，本工具不代跑 |
| **期望信号** | 两个进程最终**都成功**；每个版本在 `schema_versions` 里**恰好一行**；没有 `table already exists` |
| **判读** | 「等」＝过，「撞」＝缺陷。⚠️ 生产库是 MySQL：跨主机互斥走的是 `GET_LOCK`，与 SQLite 上的本机 flock **不是同一条路** |
| **实测（2026-09-26）** | ✅ **生产跑过**（`lock-contention-20260926T151551Z.json`，6/6 信号）：先占住 `sorders_migrations` 15 秒、再让两个迁移进程同时跑（各持一把本机 flock ＝ 还原「两台主机各自一把」）—— T+6s 两个都在**等**、三轮都 0/0、版本表 8/8 各一行、无重复记账。⚠️ **同一次演练抓到发现 1**（自愈 bootstrap 的 DDL 没有服务端互斥），见证据文档 §三·发现 1 |

### Drill E · disk 将满，能否被发现（disk）

| | |
|---|---|
| **目的** | 磁盘快满时**有没有人被叫醒**（报告的原话：出现过「证书过期两个月无人发现」） |
| **命令** | 本机**部分**真跑（只证阈值判得对）：`python _tools/ops/_drill.py --case disk-full --go`；⛔ 生产：造占位大文件把使用率推到 90%+ → 跑 `_tools/ops/_health_check.py` → 看退出码 |
| **期望信号** | `_health_check.py` 在 >85% 时给**告警**、>95% 时给**失败**（退出码 1 / 2），并且 cron 那一边真的会发出动静 |
| **判读** | 「能被发现」才过；⛔ 「阈值写在代码里」不算 —— 要看到**这一次真的报了** |
| **实测（2026-09-26）** | ✅ **生产跑过**（`disk-full-20260926T151953Z.json`，6/6 信号）：`fallocate` 把 `/` 从 31% 顶到 **92%**（剩 3.3G）—— cron 那一行命令**退出码 1**、磁盘告警**真的落进** `/var/log/sorders-health.log`；MySQL 照常读出 2403；删掉后回 31%。⛔ 仍然证不了「有人被叫醒」：告警只进**日志文件**，没有邮件/IM 通道 —— 这是**发现的缺口** |

---

## 二·补 工具与**本机预演**（2026-09-26 实测）

工具：`python _tools/ops/_drill.py` —— 护栏写在代码里（⛔ 不给 `--go` 一律只打印；⛔ `--target prod` 要
`--go` + `--i-know-prod` 三个信号，缺一个就拒绝；生产演练它**只打印过程、不代跑**），并有自检：

```
python _tools/ops/_drill.py --selftest        # 护栏自检 12/12（7 个用例 + 5 个「没有 --go 只能是 plan」）
python _tools/ops/_drill.py --all-local --go  # 五个演练的**本机部分**依次真跑（⚠️ 要几分钟）
```

**本机预演实测（2026-09-26，`--all-local --go` → 5/5 通过）**：

| 演练 | 本机跑的是什么 | 结果 | ⛔ 它证不了什么 |
|---|---|---|---|
| worker-crash | `_dual_instance.py --kill`：两个真实例，杀掉 A，B 继续服务 | ✅ B `/health`=200、登录读自己=200 | 生产是**一个 systemd 里两个 worker**，形态不同 |
| redis-down | 本机**根本没有 Redis**（`redis_ok()` = `{'redis': 'unavailable'}`）+ 订单流/账本同步用例 | ✅ 10 passed | 生产停 Redis 后业务是否照常 —— 未验 |
| event-delay | 临时库：入队 3 条 → pending=3 → 抽干 → pending=0、收到 3 条 → 再抽一次 sent=0 | ✅ 先落库后投递 / 追平 / 不重复 | 「业务数据在延迟期间仍然正确」由 R3-04 用例与本机全量用例证；生产没有 `outbox_events` 表 |
| lock-contention | `_migration_tests.py --concurrent`：两个进程同时迁移 | ✅ 两个进程都退出 0、版本表 1..8 各一行、无重复记账 | 本机是 SQLite（本机锁）；生产是 MySQL `GET_LOCK`（跨主机）—— 那条路**从未在生产上真跑过** |
| disk-full | 读 `_health_check.py` 的阈值常量逐档断言（50→ok / 85→warn / 90→warn / 95→fail / 99→fail） | ✅ 阈值判得对 | ⛔ **「报警链路真的有人收到」本机证不了** |

⭐ **2026-09-26 C 段之后，这一节记录的「本机预演」已经被生产实测取代** —— 五条都在生产上真跑过（4 条 + 1 条修复后重跑通过），
逐字原始输出在 `_tools/ops/drill_records/*.json`，汇总与「证不了什么」见 `docs/R3_FAILURE_DRILL_EVIDENCE.md`。
⛔ 本机预演那一列仍然只证明「本机那一半跑得通」，**不许**拿它顶生产那一格。
## 三、跑完之后要落地什么（⛔ 别只留一句「演练过了」）

1. 每条演练记：**命令 / 原始输出 / 算不算过 / 已知代价 / 发现了什么**；
2. 台账 `docs/R3_PROGRESS.md` 的 R3-06 五行**逐条**改 ✅（⛔ 一条都不许合并写）；
3. 演练里发现的真缺陷按禁做 #2 单独提交（带 R3-0x 号），⛔ 不混在演练记录里；
4. 演练**要能重复**：手动敲过的命令回头补进 `_tools/ops/_drill.py`（已写好）—— 工具里那五格「本机预演」就是这么固化下来的。

---

## 四、⛔ 这份方案证不了什么

- ⛔ **一个演练都没跑**：这里写的是**计划**（指南的原话也是「演练方案」）——台账那五条**仍然是 ❌**；
- ⛔ `_tools/ops/_drill.py` **存在，但它证不了生产那一格**：它把**本机预演**固化成一条命令（`--all-local --go`，五个演练 5/5 通过），生产演练它**只打印过程**（`--target prod` 要三个信号，且明确不代跑）——因为停服务 / 断 Redis / 塞磁盘都会影响线上；
- ⛔ 它不替代 `docs/PRODUCTION_ACCEPTANCE.md`（那是正常路径的验收）。
