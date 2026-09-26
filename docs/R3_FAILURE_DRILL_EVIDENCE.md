# 生产故障演练证据（R3-06 · C 段）

> **这份文档是什么**：第三轮指南 §十九（R3-06）的五个故障演练，**2026-09-26 在生产机上真跑过**的原始记录。
> 方案在 `docs/R3_FAILURE_DRILL.md`；这里放的是**跑出来的东西**。
>
> **结论：4 ✅ / 1 ❌ —— 而且那个 ❌ 是演练抓到的真缺陷，不是「没跑」**。
> 每条的**逐字原始输出**在 `_tools/ops/drill_records/<case>-<UTC>.json`（进仓库，一跑一份，⛔ 不覆盖历史）。

## 零、怎么复现

```
python _tools/ops/_drill.py --selftest                      # 护栏自检（12/12；不连生产）
python _tools/ops/_drill.py --verify                        # CI 侧核记录：六阶段齐 + 必须信号在（⛔ 不连生产）
python _tools/ops/_drill.py --verify worker-crash           # 核单条
python _tools/ops/_drill.py --case worker-crash             # 只打印要做什么（⛔ 默认不动手）
python _tools/ops/_drill.py --case worker-crash --target prod --go --i-know-prod   # 真跑（三个信号缺一不可）
```

六阶段：**X0 前置 → X1 取基线 → X2 注入 → X3 观察期望信号 → X4 恢复 → X5 核业务状态**。
⛔ 只证「服务起来了」不算过：X5 拿 X1 的基线**逐项比对**（orders / ledgers / users / products / tables / schema_versions）。

## 一、前置（X0，五条共用）

| 项 | 值 |
|---|---|
| 演练前备份 | `/opt/sorders-backup/pre_release/20260926T150728Z`（db 531,251 B / uploads 105,962,426 B；清单 `_tools/backup/manifests/20260926T150738Z-pre_release.json`）|
| 备份里的行数 | orders=2403 ledgers=4648 users=60 products=37 tables=48 |
| 生产代码 | `b3dad61bbdfae6a3b64a5d0be2d75d20641213a7` |
| 拓扑 | `sorders-api-a.service`(127.0.0.1:8111) + `sorders-api-b.service`(127.0.0.1:8112)，各 `--workers 1` |
| 演练前状态 | 两个 unit active、`/health` 200/200、经 nginx 的入口 401（有活上游）、磁盘 31% |
| 「怎么停」 | 每条都写进记录：脚本自带收尾（trap/wait/删临时目录）；判读不了就地停；回滚点是上面那份备份 |

## 二、五条的结果

### Drill A · worker-crash ✅ 通过（5/5 信号）

| | |
|---|---|
| **注入** | `systemctl kill -s KILL sorders-api-a`（整个 cgroup 一起 SIGKILL） |
| **观察** | 50 次采样 × 0.5 s：被杀的 A = `10 activating / 40 active`；**B 全程 50/50 = `200`**；**经 nginx 的入口 50/50 = `401`（一次 5xx 都没有）** |
| **监督确实管用** | `NRestarts 0 → 1`；第一次采样看到 A=active 是第 11 次 ⇒ **恢复 5.5 秒**（对上 `RestartSec=5`）|
| **X5** | 业务行逐项一致；两个 unit 都 active；8111/8112 都 200 |
| ⛔ **证不了** | 杀的是**两个独立 unit 里的一个**（生产不是「一个 systemd 里 2 个 worker」，两者形态不同）；不证跨主机；不证真实 Android 客户端在被杀瞬间的体感（只量 HTTP 码）|

**这一条的要点**：`proxy_next_upstream` 把「连不上 A」当场重试到 B ⇒ **客户端在整段窗口里一个错误码都没看到**。

### Drill B · redis-down ✅ 通过（5/5 信号）

| | |
|---|---|
| **注入** | `systemctl stop redis`（脚本用 trap 保证一定起回来）|
| **基线** | `redis=active`、`PING=PONG`、`pubsub channels = socketio`、`/health redis:"ok"` |
| **停机期间** | `PING = Connection refused`；`/health` 两个实例都变成 `"redis":"error"`（**如实报出来了**）|
| **业务照常** | 登录拿到 155 字符 token；`/users/me` 200、读订单 200、读账本 200、**写一条消息也 200 且行真的在库里**（id 41732）|
| **恢复** | `redis=active`、`PONG`、`channels=socketio` 全都回来了；探针消息当场删掉（204）|
| **X5** | 业务行逐项一致 |
| ⛔ **证不了** | 只证「不可用」，⛔ 不证「Redis 慢」；不证 App 端界面上「推送晚到」的体感 |

⚠️ **演练方案里那条前提已经过期，本条已按新事实重写**：方案原文说「生产 Redis 没人用（keyspace 空）」，
B 段之后那是**错的** —— Socket.IO 的跨实例总线就是它（`pubsub channels` 里的 `socketio` 就是判据）。

### Drill D · lock-contention ✅ 通过（6/6 信号）—— **并抓到发现 1**

| | |
|---|---|
| **注入** | 一条独立连接先拿住服务端命名锁 `sorders_migrations` 15 秒；然后两个迁移进程同时开跑。第二个进程换 `TMPDIR` ⇒ 它与第一个**各有一把本机 flock**，把「两台主机各自一把」那个条件还原出来 |
| **锁常量** | `_runner.py:78 DB_LOCK_NAME = "sorders_migrations"` / `:79 DB_LOCK_TIMEOUT_S = 60`（从代码里读的，不靠记）|
| **等，不是撞** | T+6s 时 **A=alive、B=alive**（都在等），`IS_USED_LOCK=2157`（锁确实被 holder 那条连接拿着）|
| **最后都成功** | `A_RC=0 / B_RC=0`；第 2、3 轮也都是 `0/0`；两边各自打出「拿到迁移锁 sorders_migrations（超时 60s）」|
| **记账没坏** | `VERSIONS_SUMMARY=8/8`（1..8 每个版本恰好一行）、`ALREADY_EXISTS=0`、`IS_FREE_LOCK=1` |
| **X5** | 业务行逐项一致 |
| ⛔ **证不了** | 两个进程在**同一台机器**上（跨主机那一半靠换 TMPDIR 还原条件）；不证两台物理主机之间的时钟/网络差异 |

### Drill C · event-delay ❌ **不通过（5/6）—— 抓到了发现 2（真缺陷）**

| | |
|---|---|
| **目的** | 发件箱的消费者处理不了时，**业务**是否仍然正确、「最终一致」有没有被误当成「同步一致」|
| **注入** | `systemctl stop redis` —— 让投递真的失败。⚠️ 为什么不用「把消费者线程停住」：本拓扑里消费者与 API **同进程**，停掉消费者必然停掉业务，没法只停一半（这本身是一条结论）|
| **✅ 业务写入成功** | 停 Redis 期间写的探针消息拿到 id 41731，行真的在库里（`C_ROW_IN_DB=1`）|
| **❌ 投递失败没被发件箱看见** | 那条事件被记成 **`sent attempts=0 sent_at=2026-09-26 15:17:50`**，而同一时刻应用日志里是 **16 条** `Cannot publish to redis... retrying / giving up` |
| **✅ 追平 / 不重复 / 净零** | `pending=0`、`failed=0`、`aggregate_id` 命中 1 行、探针消息删干净（204 ⇒ `C_ROW_GONE=0`）|
| **X5** | 业务行逐项一致（发件箱行数以记录为准：13 → 15 → 17，那是演练自己写的）|

**这一条为什么算 ❌**：演练要证的 ② 是「pending 堆起来但**不丢**」。实测是**没堆起来** ——
事件被当成发成功，重试/退避/`failed`+`last_error` **一条都没触发**。详见下面的发现 2。

### Drill E · disk-full ✅ 通过（6/6 信号）

| | |
|---|---|
| **注入** | `fallocate` 一个占位文件把 `/` 顶过 85%（`E_NEED_KB=23868566`）|
| **实测档位** | 31% → **92%**（34G / 40G，剩 **3.3G**）→ 删掉后回到 **31%** |
| **被发现** | 把 cron 那一行命令**原样**跑一遍：**退出码 1**；⚠️ 磁盘那一行真的落进 `/var/log/sorders-health.log`（`E_LOG_DISK_LINES=1`）|
| **没把库撑坏** | 磁盘最紧张的当口，MySQL 照常读出 `2403` |
| **X5** | 业务行逐项一致 |
| ⚠️ **口径说明** | 计划推到 ~87%，实测到 **92%**（`df -k` 的 used 与 `df -h` 取整之间的差）。⛔ 仍然**刻意没撞 95%** 那条失败线 —— 那要把在跑的 MySQL 所在盘压到只剩 ~1.5G，判为不可接受的风险 |
| ⛔ **证不了** | 不证「有人被叫醒」：告警落到**日志文件**，**没有**邮件/IM 推送通道 —— 这是**发现的缺口**，如实记下，不粉饰 |

## 三、演练抓到的两条（⛔ 本轮只记录，未改代码 —— 核心区冻结中）

### 发现 1 · 自愈 bootstrap 的 DDL 没有服务端互斥（Drill D 抓到）

**现象**（3 轮并发里 3 轮都出现，每轮 1~2 处；`COLLIDE_TOTAL=4`）：

```
orders.shipper_id 可空迁移跳过: (pymysql.err.OperationalError) (1213, 'Deadlock found when trying to get lock;
    try restarting transaction')  [SQL: ALTER TABLE orders MODIFY COLUMN shipper_id INT NULL]
ledgers.entry_date 索引创建跳过: (pymysql.err.OperationalError) (1684, "Table 'sorders'.'ledgers' was skipped
    since its definition is being modified by concurrent DDL statement")
```

**根因**（读代码确认）：`backend/app/core/schema_bootstrap.py:232` 的 `prepare_schema` 只拿着
`with FileLock(BOOTSTRAP_LOCK_FILE)` —— 那是 `/tmp/sorders_bootstrap.lock`，一把**本机** flock；
服务端那把 `GET_LOCK` 是在**之后**的 `run_migrations`（同文件 240 行）里才拿的。
⇒ **自愈那一段 DDL 跨主机没有互斥**。

**后果**：两台主机（各自 `/tmp`）同时起实例时，两边会真的同时跑自愈 DDL —— 轻则一条 DDL 被**静默跳过**，
重则 1213 死锁。

**⚠️ 今天生产中招了吗**：**没有**。生产是**同一台机器上的两个 unit**，共享 `/tmp` ⇒ 共享那把 flock。
本条的注入是**换 TMPDIR** 把跨主机条件还原出来的。

**与既有台账对得上**：`docs/MULTI_INSTANCE_READINESS.md` 的 `bootstrap-self-heal` 那一格本来就写着
**未做**；这一轮第一次给了它**原始输出**。修法方向：自愈那一段也拿同一把服务端命名锁。

### 发现 2 · 发件箱把「投递失败」记成了「已发送」（Drill C 抓到）

**现象**：Redis 停着的时候做的那次业务写入，它的事件被记成 `sent / attempts=0`，
而同一时刻应用日志里是 16 条：

```
2026-09-26 23:17:5x ERROR [socketio.server] Cannot publish to redis... retrying
2026-09-26 23:17:5x ERROR [socketio.server] Cannot publish to redis... giving up
```

**根因**：**python-socketio 的 Redis manager 把 publish 失败自己吞了** —— 记日志、**不抛异常**。
于是 `main.py::_outbox_deliver` 看到的是「成功」，`outbox.mark_sent` 照常落库。

**这正是 outbox 模块开头点名要治的病**（原话：「那条推送就没了 —— 数据库里一切正常，所以**没人会发现**」）：
边界治住了业务事务与事件，却在**最外层的 emit** 上漏了回来。

**后果（有界但真实）**：跨实例那条推送**永久丢掉**，而且**没有任何地方记着**（`pending`/`failed`/`last_error`
全是干净的）。站内信的行还在（客户端重连会重新拉），所以伤的是**实时性**，不是数据。

**修法方向**（⛔ 属核心区，本轮冻结，只记不做）：在 `core/socket_io.py` 的 emit 原语上
「发之前先探一次 Redis 可达 / 发之后确认 manager 没在重试」，不可达就**抛**，
让发件箱按它自己的语义重试。**判据**：Redis 停着时事件必须留在 `pending`。

## 四、还有一条**未定**（如实记，不记成缺陷）

Drill B 的记录里 `R_NUMSUB=socketio 1` —— 两个实例里**只有一个**订阅着跨实例总线
（实测订着的是 `sorders-api-b`）。事后单独查：**重启 A + 逼它 emit 一次之后仍然是 1**。

更可能的解释是 python-socketio 的 Redis 监听器**惰性启动**（本实例上还没有客户端连接时不订阅 ——
没有本地客户端，也就没有要投递的对象）。但本次**没有**真的量到「客户端连到 A 时 A 会不会开始订阅」，
⇒ 如实记成**未定**。⛔ 不许把它写成「跨实例推送坏了一半」—— 那是没有证据的结论。

## 五、⛔ 这批演练证不了什么

- ⛔ **不证跨主机**：五条全部是**同一台机器**上的两个 unit。跨主机多实例仍未验
  （`docs/MULTI_INSTANCE_READINESS.md` 里还挂着 3 格未做）；
- ⛔ **不证钱那条路**：演练没有送达、没有收款 ⇒ `ledgers`/`driver_bills` 一个字节没动；
- ⛔ **不证真实 Android 客户端**：所有观察都是 HTTP 码与库里的行，没有真机在故障窗口里的体感；
- ⛔ **不证 Redis 慢**（只证不可用）、**不证 >95% 那一档**（刻意没撞，理由见 Drill E）、
  ⛔ **不证「告警真的有人收到」**（只证它落进了日志文件）；
- ⛔ **不证演练自身可重复**：每条都是当场跑一次的记录；重复的办法是 `--case <case> --target prod --go --i-know-prod`，
  但**故障注入**那一步的结果会随环境变（Drill D 的发现 1 就有竞态）。
