# 多实例 / HA 就绪度（报告 §16）

> **这一页不是「现在就去上多实例」**，它回答的是报告 §16 那个问题：
> 「什么时候才考虑多实例？」—— 报告的答案是**先满足一串前置条件**，因为
> 「单实例」本身不是问题，**「单实例 + 没有迁移协调」**才是。
>
> 所以本页只做两件事：① 逐条核对那串前置条件现在到哪一步（带证据）；
> ② 把「真要做时报什么关」写清楚，免得下次有人直接开三台机器。

## 现状（2026-09-25 实测）

```text
生产：systemd `sorders-api.service`，`uvicorn --workers 2`（= **同机多进程**，不是多实例）
库  ：MySQL 8.0（宿主机服务，监听 3306；安全组只放行 80/22，外网不通）
Redis：127.0.0.1:6379（生产 .env 里 `SOCKET_REDIS_URL` **有配置**，本轮实测）
```

⚠️ 注意 `--workers 2` 本身就已经是**并发的迁移场景**（两个进程同时启动、同时想跑迁移）——
这不是"以后才要操心的事"，它今天就在跑。

## 机器契约（判据逐条核这几条 —— `_tools/qa/_check_multi_instance_readiness.py`）

上面两张表是给人读的；下面这些块是给**判据**读的。⛔ 两处说法必须一致：
判据会拿 `evidence` 指到的源码去核对 `must_contain` 那几串东西**真的在不在** ——
**「文档说做了、代码里没有」当场报红**（这正是第一轮反复栽的那一类：文档与事实走散）。

```text
name: <稳定标识>
中文名: <给人看的名字>
status: done | not-done
evidence: <backend 相对路径，逗号分隔>      ← status=done 必填
must_contain: <字符串，逗号分隔>            ← status=done 必填：这些必须出现在上面那些文件里
为什么还没做: <一句话>                      ← status=not-done 必填（≥12 字）
什么时候做: <一句话>                        ← status=not-done 必填（≥12 字）；例外要写清什么时候收回
```

⛔ 反空转：门数 <10 或 `must_contain` 条目 <12 条，判据先喊（扫描坏了不许安静地绿）。

⚠️ 第 ① 条「库必须是 MySQL」是**部署前提**，它的代码侧证据并进了 `migration-cross-host` 那道门
（跨主机锁只在 MySQL 上有分支，SQLite 下如实不做、只记一行日志）。

```gate
name: migration-versioning
中文名: 迁移版本化
status: done
evidence: backend/app/migrations/_runner.py, backend/app/migrations/__main__.py
must_contain: schema_versions, VERSION_TABLE, choices=["status", "upgrade"]
```

```gate
name: migration-cross-host
中文名: 并发 / 跨主机迁移协调
status: done
evidence: backend/app/migrations/_runner.py
must_contain: DB_LOCK_NAME, GET_LOCK, RELEASE_LOCK, with _lock(), _db_lock(engine)
```

```gate
name: reliable-events
中文名: 可靠事件（事务发件箱）
status: done
evidence: backend/app/core/outbox.py, backend/app/models/outbox.py, backend/app/core/metrics.py
must_contain: def enqueue(, def claim(, MAX_ATTEMPTS, aggregate_id, sorders_outbox_pending, sorders_outbox_failed
```

```gate
name: observability
中文名: 可观测性（Request ID 贯穿）
status: done
evidence: backend/app/core/request_id.py, backend/app/models/operation_log.py, backend/app/migrations/003_operation_log_request_id.py
must_contain: def get_request_id, request_id
```

```gate
name: backup-recovery
中文名: 备份与恢复
status: done
evidence: _tools/backup/_backup.sh, _tools/backup/_drill.sh
must_contain: UPLOADS_DIR, mysqldump
```

```gate
name: socket-cross-process
中文名: Socket.IO 跨进程
status: done
evidence: backend/app/core/socket_io.py, backend/app/config.py
must_contain: socket_redis_url
```

```gate
name: bootstrap-self-heal
中文名: 启动期自愈（跨主机）
status: not-done
为什么还没做: schema_bootstrap 只有本机 flock（/tmp/sorders_bootstrap.lock），多实例同时跑那 1600 行 DDL 仍有风险
什么时候做: 切多实例之前 —— 要么把它纳入同一把服务端锁，要么加一个「只让一个实例跑自愈」的开关
```

```gate
name: shared-uploads
中文名: 上传目录共享
status: not-done
为什么还没做: 上传目录是写死的相对路径 Path("uploads")，落在各机器的本机磁盘上（生产 /opt/SOrders/backend/uploads）
什么时候做: 切多实例之前 —— 换对象存储或共享盘；那之前先\u628a路径提成配置项（现在连配置项都没有）
```

```gate
name: scheduled-jobs-single-leader
中文名: 定时任务选主
status: not-done
为什么还没做: data_retention 每日循环只有本机 flock + 标记文件；备份与体检是各机器自己的 cron —— 跨主机没有任何去重
什么时候做: 切多实例之前 —— 选主（Redis/DB 锁）或把定时任务外置成一处跑
```

```gate
name: nginx-upstream
中文名: nginx 上游多台 + 健康检查摘除
status: not-done
为什么还没做: 仓库里的生成模板只有单台（proxy_pass http://127.0.0.1:8000），且没有任何 max_fails / proxy_next_upstream / health_check
什么时候做: 切多实例之前 —— 配 upstream 多台 + 失败摘除；那要动生产 nginx，属于用户拍板
```

## 前置条件逐条核对（报告的排序：迁移 → 事件 → 可观测 → 备份 → 才轮到多实例）

| # | 前置条件 | 状态 | 证据 |
| --- | --- | --- | --- |
| 1 | Migration versioning | ✅ | `schema_versions` + `migrations/001~003`；`python -m app.migrations status` 报版本 3 |
| 2 | **并发 / 跨主机**迁移协调 | ✅ **本轮补** | `_runner.py` 除了本机 flock，还拿一把服务端命名锁 `GET_LOCK("sorders_migrations")`（超时 60s）—— 见下节 |
| 3 | Reliable events | ✅ | 事务发件箱：入队同事务 / 失败可重试 / worker 兜底；`/metrics` 暴露 `outbox_pending`、`outbox_failed` |
| 4 | Observability | ✅ | `request_id` 贯穿 HTTP → service → `operation_logs`；`/metrics` 11 个业务指标；生产 cron 跑 `_health_check.py`（服务/证书/磁盘/**备份年龄**/发件箱） |
| 5 | Backup / recovery | ✅ | 脚本化 + **真的演练过**（建库→恢复→启动→打接口→核对行数与不变式→自清） |
| 6 | Socket.IO 跨进程 | ✅（生产已配） | 生产 `.env` 有 `SOCKET_REDIS_URL` —— 没有它，两个 worker 的推送会**丢一半**（本机开发没配，日志里每次启动都会提示） |

## 本轮补的那一条：跨主机迁移锁

**为什么原来的锁不够**：`/tmp/sorders_migrations.lock` 是 `flock`，只在**同一台机器**上有效。
多实例部署时 A、B 两台机器各拿自己的 `/tmp` 锁**都会成功**，于是同一条迁移被同时执行两遍 ——
DDL 半途撞车，而且版本表会互相覆盖（谁后写谁赢，先跑完的那条等于没记账）。

**现在**：迁移在拿到本机 flock **之后**，再向数据库要一把命名锁：

```text
本机 flock（同机多进程）  →  MySQL GET_LOCK("sorders_migrations")（跨主机）  →  跑迁移
                                                                              ↓
                                                                      RELEASE_LOCK
```

⛔ **锁的顺序是固定的**（先本机、后服务端）：反着写会和 `--workers 2` 死锁，判据钉着这个顺序。
⚠️ `GET_LOCK` 是**连接级**的，所以拿锁的那条连接必须**抱着**活到迁移跑完（不能 execute 完就还回池里）。
⚠️ SQLite 下**如实不做**跨主机锁（它本来就不可能多主机共享），只记一行日志 —— 算不出真值就不假装有。

## 真要做多实例时，还差这几关（逐条写清，别到时候现找）

1. **库必须是 MySQL**。SQLite 没有跨主机锁也没有共享能力 —— 这一页的 ①–⑥ 里，第 2 条只在 MySQL 上成立。
2. **`schema_bootstrap` 的启动期自愈仍是每个实例都会跑的**。它是幂等的，但多实例**同时**跑那 1600 行 DDL
   仍有风险（本机靠一把独立 flock 兜着，那把锁同样只在本机有效）。
   → 要么把 bootstrap 也纳入同一把服务端锁，要么只让一个实例跑自愈（`SORDERS_SKIP_MIGRATIONS` 旁边再加一个开关）。
3. **上传目录要共享**（当前是各机器的本机磁盘 `/opt/SOrders/backend/uploads`）→ 对象存储或共享盘。
4. **定时任务会各跑一遍**：`data_retention` 每日循环、备份 cron、`_health_check` cron —— 要去重（选主或外置）。
5. **nginx 上游要配多台** + 健康检查摘除。

## 结论

报告列的四个前置条件**都已就绪**，Socket 适配器生产也已配 —— 也就是说「**可以做**」，
但上面那 5 关里有 3 关（共享上传、定时任务去重、nginx/选主）**要动生产**，
属于**用户拍板**的范围，不是仓库里能自己完成的。

⛔ 所以本页的结论停在「前置条件已清 + 剩下的关在这里」，**没有**去改生产。