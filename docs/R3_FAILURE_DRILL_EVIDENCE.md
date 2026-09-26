# 生产故障演练证据（R3-06 · C 段）

> **这份文档是什么**：第三轮指南 §十九（R3-06）的五个故障演练，**2026-09-26 在生产机上真跑过**的原始记录。
> 方案在 `docs/R3_FAILURE_DRILL.md`；这里放的是**跑出来的东西**。
>
> **结论：5 ✅ / 0 ❌** —— 五个演练全部通过，各自六阶段（X0 前置 → X1 基线 → X2 注入 → X3 观察 → X4 恢复 → X5 核业务状态）。
> ⚠️ 第一轮跑出来是 **4 ✅ / 1 ❌**：Drill C 抓到了一条真缺陷（发件箱把「投递失败」记成「已发送」）。
> 修复之后**重跑**才有现在这个 5/5 —— 这条链（演练 → 缺陷 → 修复 → 重跑）本身就是这一节要留的证据。
>
> 每条的**逐字原始输出**在 `_tools/ops/drill_records/<case>-<UTC>.json`（进仓库，一跑一份，⛔ 不覆盖历史）。

## 零、怎么复现

```
python _tools/ops/_drill.py --selftest                      # 护栏自检（12/12；不连生产）
python _tools/ops/_drill.py --verify                        # CI 侧核记录：六阶段齐 + 必须信号在（⛔ 不连生产）
python _tools/ops/_drill.py --verify worker-crash           # 核单条
python _tools/ops/_drill.py --case worker-crash             # 只打印要做什么（⛔ 默认不动手）
python _tools/ops/_drill.py --case worker-crash --target prod --go --i-know-prod   # 真跑（三个信号缺一不可）
```

⛔ 只证「服务起来了」不算过：X5 拿 X1 的基线**逐项比对**（orders / ledgers / users / products / tables / schema_versions）。

## 一、前置（X0，五条共用）

| 项 | 值 |
|---|---|
| 演练前备份 | `/opt/sorders-backup/pre_release/20260926T150728Z`（db 531,251 B / uploads 105,962,426 B；清单 `_tools/backup/manifests/20260926T150738Z-pre_release.json`）|
| 备份里的行数 | orders=2403 ledgers=4648 users=60 products=37 tables=48 |
| 生产代码 | A/B/D/E 四条跑在 `b3dad61`（A 段发布版）；**C 与 B 的重跑跑在 `bb67156`**（修复版，2026-09-26 发布，滚动重启两个 unit）|
| 拓扑 | `sorders-api-a.service`(127.0.0.1:8111) + `sorders-api-b.service`(127.0.0.1:8112)，各 `--workers 1` |
| 演练前状态 | 两个 unit active、`/health` 200/200、经 nginx 的入口 401（有活上游）、磁盘 31% |
| 「怎么停」 | 每条都写进记录：脚本自带收尾（trap/wait/删临时目录）；判读不了就地停；回滚点是上面那份备份 |

⛔ **读记录时要看 `PROD_SHA`**：`X0` 那一段里有一行 `PROD_SHA=…`，它说明这一条是对着哪一版代码跑的。
修复只动了 `core/socket_io.py` 的投递边界（+ 两条契约用例），所以 A / D / E 三条**没有重跑**，
B 因为直接压在 socket 那条路上**重跑了**（结果仍然是 ✅，且判据换成了更有意义的那条）。

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

### Drill B · redis-down ✅ 通过（5/5 信号）—— 修复后重跑过

| | |
|---|---|
| **注入** | `systemctl stop redis`（脚本用 trap 保证一定起回来）|
| **停机期间** | `PING = Connection refused`；`/health` 两个实例都变成 `redis:error`（**如实报出来了**）|
| **业务照常** | 登录拿到 155 字符 token；`/users/me` 200、读订单 200、读账本 200、**写一条消息也 200 且行真的在库里**（id 41736）|
| **投递自己回来** | 停 Redis 期间写的那条事件，恢复后由消费者自己补投：`R_PROBE_EVENT = sent attempts=1`；`PING=PONG` |
| **X5** | 业务行逐项一致 |
| ⛔ **证不了** | 只证「不可用」，⛔ 不证「Redis 慢」；不证 App 端界面上「推送晚到」的体感 |

⚠️ **演练方案里那条前提已经过期，本条已按新事实重写**：方案原文说「生产 Redis 没人用（keyspace 空）」，
B 段之后那是**错的** —— Socket.IO 的跨实例总线就是它（`pubsub channels` 里的 `socketio` 就是判据）。

⚠️ **判据本身也改过一次（如实记）**：第一轮的信号是「恢复后 `pubsub channels` 里要有 `socketio`」，
第二轮重跑时它红了 —— 查下去发现是**判据写错了**：python-socketio 的 Redis 监听器是**惰性启动**的
（`async_server.py:675` 在**第一次 Engine.IO 连接**时才调 `manager.initialize()`，源码核对过），
所以一个**从没被客户端连过**的实例本来就不会订阅总线 —— 而那时也确实没有要投递的对象。
改成现在这条：**投递这条路**必须自己回来（那条事件必须补投成 `sent`）。这条是真的、可判的。

### Drill C · event-delay ✅ 通过（7/7 信号）—— **修复后重跑，第一轮是不通过的**

| | |
|---|---|
| **目的** | 发件箱的消费者处理不了时，**业务**是否仍然正确、「最终一致」有没有被误当成「同步一致」|
| **注入** | `systemctl stop redis` —— 让投递真的失败。⚠️ 为什么不用「把消费者线程停住」：本拓扑里消费者与 API **同进程**，停掉消费者必然停掉业务，没法只停一半（这本身是一条结论）|
| **业务写入成功** | 停 Redis 期间写的探针消息拿到 id 41734，行真的在库里（`C_ROW_IN_DB=1`）|
| **失败被看见了** | `sent_before_failure=0` ／ `pending_after_failure=1` ／ `attempts_after_failure=2` ／ `last_error` 长度 219（就是下面那句）|
| **恢复后补投成功** | `sent_after_recovery=1` ／ `duplicate_count=0` ／ `pending=0` ／ `failed=0` ／ `C_PROBE_EVENT_AFTER = sent attempts=2 sent_at=2026-09-26 15:50:03` |
| **X5** | 业务行逐项一致（发件箱行数以记录为准：那是演练自己写的）|

**那条 `last_error` 的原文**（它是修复真正生效的现场证据 —— 我们的异常文本落在了生产库的行里）：

```text
RuntimeError: Socket.IO 跨实例投递失败：redis.publish 没有成功返回
（上游 AsyncRedisManager 把失败吞成了一条日志）—— 发件箱必须按**投递失败**处理，⛔ 不许当成已发送。
```

### Drill D · lock-contention ✅ 通过（6/6 信号）—— **并抓到发现 1**

| | |
|---|---|
| **注入** | 一条独立连接先拿住服务端命名锁 `sorders_migrations` 15 秒；然后两个迁移进程同时开跑。第二个进程换 `TMPDIR` ⇒ 它与第一个**各有一把本机 flock**，把「两台主机各自一把」那个条件还原出来 |
| **锁常量** | `_runner.py:78 DB_LOCK_NAME = "sorders_migrations"` / `:79 DB_LOCK_TIMEOUT_S = 60`（从代码里读的，不靠记）|
| **等，不是撞** | T+6s 时 **A=alive、B=alive**（都在等），`IS_USED_LOCK=2157`（锁确实被 holder 那条连接拿着）|
| **最后都成功** | `A_RC=0 / B_RC=0`；第 2、3 轮也都 `0/0`；两边各自打出「拿到迁移锁 sorders_migrations（超时 60s）」|
| **记账没坏** | `VERSIONS_SUMMARY=8/8`（1..8 每个版本恰好一行）、`ALREADY_EXISTS=0`、`IS_FREE_LOCK=1` |
| **X5** | 业务行逐项一致 |
| ⛔ **证不了** | 两个进程在**同一台机器**上（跨主机那一半靠换 TMPDIR 还原条件）；不证两台物理主机之间的时钟/网络差异 |

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

## 三、演练抓到的两条

### 发现 1 · 自愈 bootstrap 的 DDL 没有服务端互斥（Drill D 抓到）—— ⚠️ **本轮记录，未修**

**现象**（3 轮并发里 3 轮都出现，每轮 1~2 处；`COLLIDE_TOTAL=4`）：

```text
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

⛔ **为什么不顺手修**（用户 2026-09-26 拍板）：这是**尚未启用的跨主机拓扑**暴露出来的结构缺陷，
而 R3 实际证明的范围就是同机双实例。混在一起修＝偷偷把 R3 范围扩大到跨主机。
⇒ 定为 **「跨主机 enable blocker」**：等真要上多主机时**先关掉它**（判据就是上面那两条报错必须消失）。
`docs/MULTI_INSTANCE_READINESS.md` 的 `bootstrap-self-heal` 那一格记着它。

### 发现 2 · 发件箱把「投递失败」记成了「已发送」（Drill C 抓到）—— ✅ **本轮已修 + 重跑**

**第一轮的现象**：Redis 停着的时候做的那次业务写入，它的事件被记成 `sent / attempts=0`，
而同一时刻应用日志里是 16 条 `ERROR [socketio.server] Cannot publish to redis... giving up`。

**根因**：**python-socketio 的 Redis manager 把 publish 失败自己吞了** ——
`AsyncRedisManager._publish` 两次发布都失败时只打一条日志就 `return None`（异常不上抛），
于是 `sio.emit` **永远成功返回**，`main.py::_outbox_deliver` 看到的是「成功」。

**这为什么是 P1**：它正是 outbox 模块开头点名要治的病（原话：「那条推送就没了 ——
数据库里一切正常，所以**没人会发现**」）—— 边界治住了业务事务与事件，却在**最外层的 emit** 上漏了回来。
后果：跨实例那条推送**永久丢掉且没有任何地方记着**（站内信的行还在 ⇒ 伤的是**实时性**，不是数据）。

**修法**（用户 2026-09-26 拍板：⛔ **不许**用「发之前先探一次 Redis 可达」—— 那是 TOCTOU，
探完到发之间它照样能挂，只能降概率、证明不了 publish 成功）：

```text
契约改成：outbox 只有在「底层投递原语确认成功返回」之后，才能把事件推进 sent。

  pending → _outbox_deliver → socket emit / redis.publish
                              ├── 成功返回 → sent
                              └── 失败     → 保持 pending → retry / backoff → 最终 failed
```

- `backend/app/core/socket_io.py` 新增 `_StrictRedisManager`：**只把上游 `_publish` 的「失败返回值」翻成异常**
  （仍然调 `super()._publish()`，⛔ 没有重写发布逻辑）；
- 唯一被容忍的地方是 `connect` 里那条**发给连接自己**的 `sync` 广播 —— 它本地已经投递完了，
  ⛔ 不能因为 Redis 一抖就让新连接建不起来；
- `main.py::_outbox_deliver` **一个字没改**：错误传播一通，它原来的 `_deliver_batch` 就已经按失败处理了
  （少改一处、少一个爆炸半径）；
- 两条契约用例把语义钉死：`test_publish_failure_is_not_swallowed`（原语要抛）、
  `test_publish_failure_keeps_the_event_pending`（抛了之后事件真的留在 pending + attempts + last_error）。
  反向对照：直接把死端口喂给**上游**的 `_publish`，实测返回值是 `None`（吞掉）—— 这一层是承重的，不是装饰。

**修完重跑的结果**：见上面 Drill C 那张表（7/7，`last_error` 里躺着我们那句异常原文）。

## 四、那条「未定」已经查清了（⛔ 不是缺陷）

第一轮记录里有一条未定：`R_NUMSUB=socketio 1`（两个实例里只有一个订阅着跨实例总线）。
第二轮重跑时两个实例**都没订阅**（`numsub=0`、`channels` 为空）⇒ 顺着查下去，答案在源码里：

```text
socketio/async_server.py:671-675
  async def _handle_eio_connect(self, eio_sid, environ):
      if not self.manager_initialized:
          self.manager_initialized = True
          self.manager.initialize()      # ← Redis 监听器在这里才启动
```

⇒ **监听器是随第一次 Engine.IO 连接惰性启动的**：一个从没被客户端连过的实例本来就不会订阅总线，
而那时也确实**没有要投递的对象**。所以 `numsub/channels` **不是**「总线坏没坏」的判据，
只是观察值 —— 已在 `_drill.py` 的 `known_limits` 里写清楚，判据换成了「投递那条路自己回来」。

## 五、⛔ 这批演练证不了什么

- ⛔ **不证跨主机**：五条全部是**同一台机器**上的两个 unit。跨主机多实例仍未验
  （`docs/MULTI_INSTANCE_READINESS.md` 里还挂着 3 格未做，其中 `bootstrap-self-heal` 就是发现 1）；
- ⛔ **不证钱那条路**：演练没有送达、没有收款 ⇒ `ledgers`/`driver_bills` 一个字节没动；
- ⛔ **不证真实 Android 客户端**：所有观察都是 HTTP 码与库里的行，没有真机在故障窗口里的体感；
- ⛔ **不证 Redis 慢**（只证不可用）、**不证 >95% 那一档**（刻意没撞，理由见 Drill E）、
  ⛔ **不证「告警真的有人收到」**（只证它落进了日志文件）；
- ⛔ **不证演练自身可重复**：每条都是当场跑一次的记录；重复的办法是 `--case <case> --target prod --go --i-know-prod`，
  但**故障注入**那一步的结果会随环境变（Drill D 的发现 1 就有竞态）；
- ⛔ **不证发件箱的「尝试次数」语义**：`attempts` 数的是**底层投递被拒了几次**（不是 deliver 被调用几次），
  这一点由 `test_publish_failure_keeps_the_event_pending` 钉住；要做「真正的尝试次数」得再加一列，超出本轮范围。
