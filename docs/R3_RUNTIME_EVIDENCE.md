# R3 运行时证据（双实例实验的原始结果）

> 指南 §R3-03-D：「不要『代码看起来支持双实例』。要 Instance A / Instance B 真正同时启动。」
> 这份文件记的是**当场跑出来的**结果，以及**这个环境证不了什么**。

复现：`python _tools/ops/_dual_instance.py --all`

> **实验键**（判据 `_check_r3_constraints.py` 按这几个词核本文件，它们与 `_dual_instance.py` 的 case 名一一对应）：
> `migration` / `scheduler` / `upload` / `socket` / `kill`。
> 其中 `migration`（两个实例同时迁移）由 R3-01 的 `python _tools/ops/_migration_tests.py --concurrent` 覆盖，
> 本工具不再重复造一遍；其余四个都在下面这张表里。

## 环境（决定了能证到哪一步）

| 项 | 本机 | 生产 |
| --- | --- | --- |
| 库 | SQLite（文件） | MySQL 8.0 |
| Redis | **没有** | 127.0.0.1:6379 |
| nginx | **没有** | 80/443/8080 |
| 实例 | 同机两个进程（:8111 / :8112） | `uvicorn --workers 2`（同机多进程） |

## 实验与结果

| # | 实验 | 结果 | 原始证据 |
| --- | --- | --- | --- |
| 1 | 两个实例都接请求；A 登录的 token 到 B 上认不认 | ✅ | `A /health=200  B /health=200  A 登录=ok  B 用 A 的 token 读 /users/me=200` |
| 2 | 启动即跑的那轮数据治理**只跑一次**（选主） | ✅ | `真跑 1 次 / 跳过 1 次`（两个实例各打一行结果行，恰好一行不含 `skipped`）|
| 3 | A 上传的图，B 取得到 | ✅ | `A 上传=200  url=/static/uploads/locations/<hex>.jpg  B 取=200  字节一致=True` |
| 4 | 杀掉 A 之后 B 继续服务 | ✅ | `A 已杀；B /health=200  B 登录+读自己=200` |
| 5 | Socket.IO 跨实例（A 建连接 / B 发事件） | ⛔ **未验** | 本机没有 Redis，跨进程适配器起不来 —— 如实报未验，不假装通过 |

## ⛔ 这份证据**证不了**的东西（写在前面，免得被当成更强的保证）

1. **跨机器**只跑一次：迁移锁与调度锁的跨主机那一半是 MySQL `GET_LOCK`，SQLite 上**如实不做**。
   这里证到的只是「同机两个进程」；跨机器要到多实例环境上再跑一次。
2. **Socket.IO 跨实例推送**：没有 Redis，完全没验（实验 5）。它恰恰是指南 §R3-03-C 特别点名的那个。
3. **nginx upstream 与失败摘除**：需要 nginx，本机没有 —— 属 R3-05 的活。
4. 实验 2 的「跳过」有两条路（拿不到选主权 / 今天已经跑过），本工具只断言**真跑恰好 1 次**；
   至于是哪条路，日志里看得出来（`本轮跳过` vs `{'skipped_same_day': 1}`）。

## 跑这一块时修掉/发现的三件事

1. **`GOVERNANCE_MARKER_PATH` 写死 `/tmp`**：Windows 上会解析成当前盘的 `\tmp`（通常不存在）→
   标记永远写不进去、也永远读不到 → 表现是「每天 N 次治理」而且**不报错**。改成 `tempfile.gettempdir()`。
2. **`_single_runner` 在 Windows 上是空操作**（`import fcntl` 失败就 `yield True`）—— 与 R3-01 修掉的
   迁移锁同一个毛病（那次的表现是并发迁移撞 `table already exists`）。现在两层：本机 `FileLock`
   （Windows 上也是真锁）+ 跨主机 `GET_LOCK('sorders:scheduler:retention')`。
3. **判据本身第一版是错的**：我按「日志里出现几次『治理完成』」数，而那行是**无条件打的** ——
   跳过时打的是 `{'skipped_same_day': 1}`，于是「两个都跳过」被读成「两个都跑了」。
   现在按**返回的字典**判（含 `skipped` 的不算真跑）。这条正是本仓库的老账：判据被别处满足。

