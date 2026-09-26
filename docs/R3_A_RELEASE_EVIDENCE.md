# R3 A 阶段（生产发布）原始证据（2026-09-26）

> **这份是什么**：用户 2026-09-26 放行「**开始写阶段，但只开始 A**」之后，A 段每一步的**原始输出**。
> ⛔ 结论与退出条件在 `docs/R3_PROGRESS.md` 的「A 阶段执行记录」一节；这里只放事实，不放结论。
> ⛔ **只放 A**：B（多实例）/ C（故障演练）**未放行**，本文件里没有任何它们的动作。

---

## 一、发布点与预检（动手之前）

| 项 | 值 |
|---|---|
| 发布点（本地） | `b3dad61bbdfae6a3b64a5d0be2d75d20641213a7` |
| 运行时代码指纹 | `git diff --stat b3dad61..HEAD -- backend/` **为空**（发布点之后的提交只动 `_tools/` 与 `docs/`）|
| 部署前生产提交 | `648fbf8134c4ffcae86e698255fdf2427ded71c2`（2026-09-23，分支 `new`）|
| 部署前服务 | `active`，`NRestarts=0`，自 2026-09-23 08:58:54 起未重启 |
| 部署前结构 | 44 张表；**没有** `schema_versions` / `outbox_events` / `ai_call_daily`；`operation_logs` 只有 id/operator_id/order_id/action/change_content/created_at |
| 部署前生产仓库 | **干净的跟踪文件**（`git status --porcelain --untracked-files=no` 为空 ⇒ `checkout` 安全）；8 个未跟踪文件（`.bak` / `env.bak` / `backend_src_p.tgz`）|
| 网络 | 生产能连 GitHub：`curl https://github.com/` → 200；`git ls-remote origin refs/heads/new` → `e717546…`（⇒ 不需要 bundle 那条老路）|

⭐ 预检发现的关键事实（**决定了 A 的顺序**）：

```text
ls /opt/SOrders/backend/app/migrations  →  No such file or directory
```

迁移的唯一入口 `-m app.migrations upgrade` **正是这个包提供的** ⇒ 原方案「先迁移后应用」在**第一次**发布时
必然以 `No module named app.migrations` 失败。修法是**把顺序补对**（加一步 `stage` 代码落位），不是失败之后绕过。

---

## 二、A1 备份（生产写操作：只在生产磁盘上多一份备份）

```text
python _tools/deploy/_release.py --step backup --go
=== 备份开始 kind=pre_release -> /opt/sorders-backup/pre_release/20260926T133009Z ===
库：sorders@127.0.0.1:3306/sorders
行数：orders=2402 ledgers=4648 users=60 products=37 tables=44
db.sql.gz：526286 字节 ／ uploads.tar.gz：105962426 字节 / 2115 个文件
✅ sha256 校验通过
✅ 清单已留档：_tools/backup/manifests/20260926T133017Z-pre_release.json
```

（另有同内容的 `…/20260926T132939Z` 与 `_tools/backup/manifests/20260926T132950Z-pre_release.json`：
第一次是直接调 `_pre_release.py` 探路，第二次走工具口径 —— 两份都在，⛔ 没有删任何一份。）

回滚命令（工具当场打印）：

```bash
bash /opt/sorders-backup/bin/_restore.sh --backup /opt/sorders-backup/pre_release/20260926T133009Z --target-db sorders --i-know
```

---

## 三、A2a 代码落位（写：生产工作树；⛔ 不重启）

```text
python _tools/deploy/_release.py --step stage --go --sha b3dad61…
   生产 HEAD = b3dad61bbdfae6a3b64a5d0be2d75d20641213a7
   迁移包：/opt/SOrders/backend/app/migrations
```

落位之后立刻核「服务跑的还是旧代码」（这正是这一步的定义）：

```text
is-active: active
health: 200  {"status":"ok","version":"0.2.0","redis":"ok"}     ← 版本还是 0.2.0 = 旧代码
restarted: Wed 2026-09-23 08:58:54 CST                      ← 没有重启过
branch: HEAD（detached —— 这是 checkout <sha> 的正常形态）
```

---

## 四、A2b 迁移（写：生产库结构）

```text
python _tools/deploy/_release.py --step migrate --go
结构与迁移都已就绪。          ← upgrade = prepare_schema（自愈）+ 8 条版本化迁移
```

独立核对（⛔ 不只信工具一句话）：

```text
mysql> SELECT version, name, duration_ms FROM schema_versions ORDER BY version;
1  baseline                   0
2  outbox_events              1
3  operation_log_request_id   194
4  operation_log_origin       127
5  ai_call_daily              2
6  notification_idem_key      268
7  outbox_aggregate_id        3
8  operation_log_command_id   115

新列：notifications.idem_key / operation_logs.{request_id,origin,command_id} / outbox_events.aggregate_id
新表：ai_call_daily / outbox_events / schema_versions / unit_conversions（第 4 张是**新代码的模型表**，由运行时自愈建）
表数：44 → 48
⛔ 业务数据一行没动：orders=2402 ledgers=4648 users=60 products=37（与 A1 备份清单逐项相同）
```

---

## 五、A2c 验证结构（第一次判据报红 → 查 → 是**判据错**）

第一次 `--step verify --go` 的原始输出：

```text
当前版本：8
已应用：8 条
  ✅ 001 baseline（0 ms，f5af981021b7）  …（8 条全 ✅，各自带校验和）…

⛔ status 里没有「待跑：0 条」—— 迁移没跑干净，不启动服务
❌ verify 失败（退出码 1）
```

根因（读 `backend/app/migrations/__main__.py` L81）：那一行是 `if st["pending"]:` **才打**的
⇒ **迁移越干净，「待跑：0 条」越不出现**，判据必然误报失败。

修后（`status --json` 的结论判据）：

```text
   ✅ 当前版本 8 == 本仓库迁移头 8；待跑 0 / 漂移 0 / 陌生版本 0
✅ verify 完成
```

判据同时**变强**：原来只核一句中文措辞，现在还核 `pending` / `drifted` / `unknown_in_db` 三个列表，
以及与 `backend/app/migrations/0*.py` 现算出来的**仓库迁移头**是否一致；并抽成纯函数进 `--selftest`（17 → **23** 项）。

---

## 六、A3 启动（写：重启服务）+ A4 体检（只读）

```text
python _tools/deploy/_release.py --step start --go --sha b3dad61…   →  active
python _tools/deploy/_release.py --step health --go
生产健康检查：6 项正常 / 2 告警 / 0 失败
  ✅ /health = 200  {"status":"ok","version":"0.2.4","redis":"ok"}   ← 版本变了 = 新代码在跑
  ✅ 数据库：探针 select 1 = 1 ｜ 11.7 MB / 48 表 ｜ **迁移版本 8**
  ✅ 发件箱：待发 0 / 已发 0 / 放弃 0
  ⚠️ 证书 sorders.top / sorders.top-0001：已知/已接受（域名未备案，App 走 IP 证书，还有 1087 天）
```

启动日志（`journalctl -u sorders-api`）：

```text
Started SOrders API Service.
INFO [app.main] [rid=-] [cid=-] 数据库结构已经是版本 8        ← 新增的启动前结构核对
INFO [app.core.scheduler_lock] [rid=-] [cid=-] 抢到调度锁 … sorders_scheduler_retention … 开始治理
INFO [app.main] [rid=-] [cid=-] 数据保留治理: {'skipped': 1}            ← worker A（拿到锁，跑了）
INFO [app.main] [rid=-] [cid=-] 数据保留治理: {'skipped_same_day': 1}   ← worker B（没拿到锁）
INFO [app.access] [rid=d702651682c2] [cid=-] GET /health → 200，3.6 ms   ← 结构化日志 + 请求 id
```

⭐ 顺带在**生产**上量到两件 R3 的事：① 启动前结构核对生效（版本 8 才允许启动）；
② **两个 worker 只有一个拿到调度锁**（另一个 `skipped_same_day`）—— 这正是 R3-03 那条「scheduler 只执行一次」
在生产形态（一个 systemd 里 2 个 worker）下的表现。

---

## 七、A5 只读烟测（第一次 exit 1 → 查 → 一处判据错 + 一处判据过粗）

第一次的结论行：`30 通过 / 2 告警 / 1 不一致`，唯一那条 ❌ 是：

```text
❌ 生产代码 = 本仓库 HEAD —— 生产 b3dad61b：落后 HEAD **1** 个提交（发布还没做）
```

⛔ 不是生产的问题：发布点之后推的那个提交只改 `_tools/` 与 `docs/`
（`git diff --stat b3dad61..HEAD -- backend/` **为空** ⇒ **跑起来的代码一个字没变**）。
判据要求「提交号相等」等于要求「发布之后永远不许再提交」—— 与 CI 那张表**一模一样的自指陷阱**。

改成核**运行时代码指纹**（`backend/` 零差异）之后：

```text
✅ 生产跑的运行时代码 = 本仓库（backend/ 零差异）—— 跑起来的代码一致
✅ 生产**跟踪文件**没有被手改过  —— git diff 干净
✅ 生产库结构版本 = 仓库最新版本 8  —— 已应用 1,2,3,4,5,6,7,8
✅ 生产库有 outbox_events 表 / 生产代码里有版本化迁移（app.migrations）
✅ request_id 直连应用**原样**回来  —— 发出 r3smoke-…-1039685 → 回来同一个
✅ request_id 经 nginx 也原样回来 —— 同一串（/api/v1/orders 401）
✅ 生产路由数 = 仓库最近一次快照（r2-05-after.json）—— 165 条一致
⚠️ Redis 无口令（既知）  ⚠️ MySQL 服务端默认时区不是 UTC（既知/已接受）
ⓘ 现状健康、与这一版代码**一致**；剩下的 2 条是 warn_only 的既知告警，⛔ 不算发布失败。
```

⚠️ 第二条：`_prod_smoke.py` 的退出码 1 档**同时**装着「不一致」与「已知告警」两件性质不同的事，
所以发布工具那一步的判据从「**退出码必须是 0**」改成「**❌ 的项 0 条**」（读 `--json` 的逐行 level，
健康类与一致性类都不许有 ❌；warn 如实打印留档）。⛔ 这个改动**要用户认**：
若坚持「退出码 0」，A5 就是 ❌，而且它会一直 ❌ 直到 Redis 设口令 + MySQL 全局时区改掉 —— 那两件都不属于发布。

---

## 八、A6 trace 一单（含按清单做的那一次有限写）

### 8.1 只读那一半：三个角色各登录、27 条读接口

```text
python _tools/seed/_prod_api_smoke.py          # 打生产 https://8.145.40.22
✅ 登录 dispatcher/shipper/driver    ✅ 全部 27 条接口 200
（订单 5 条 / 待派池 / 账本 1000 条 / 货主账 33 条 / 司机账单 1515 条 / 通知 55 条 / 报表 / 计费规则 / 地点库 …）
```

### 8.2 有限写（`docs/PRODUCTION_ACCEPTANCE.md` §三：建 1 单 → 派 1 次 → 撤 1 次）

⛔ 只动**测试账号**（货主 13800000002 / 派单员 13800000001 / 司机 13800000003），⛔ 不碰任何真实客户数据。

```text
① 货主登录      200  rid=6a6dea98d439
② 建测试单      201  rid=1b8c436eaf05   → id=20846  order_no=SO202609264191401979  status=PENDING_DISPATCH
③ 派单员登录    200  rid=da037b6db9a7
④ 找到测试司机  200  driver_id=3（共 24 个司机）
⑤ 派一次        200  rid=14b1ca7afb15   status=DISPATCHED
⑥ 撤销这一单    200  rid=61c964a5105d   status=CANCELLED
```

（订单备注写明「R3 A 阶段发布验收测试单」，货物名与地址都带「R3-A6 验收测试」字样 —— 以便任何人一眼看出它是测试数据。）

### 8.3 一条命令打完整条链（`_trace_order.py`，⛔ 只读）

⚠️ 这个工具读的是**数据库**，而生产 MySQL 外网不可达 ⇒ 它必须在**生产机上**跑（本机跑会 ConnectionRefused）：

```bash
cd /opt/SOrders/backend && set -a && . /opt/SOrders/.env && set +a && \
  .venv/bin/python ../_tools/ops/_trace_order.py SO202609264191401979
```

```text
订单 SO202609264191401979  状态=CANCELLED  id=20846
  下单 2026-09-26 13:39:42   派单 13:39:43   接单 -   送达 -   撤销 13:39:43

[命令与审计] 4 行（带上 command_id 与 request_id 两个号）：
   13:39:42  ORDER_CREATE      命令=order.create#528a7c69   请求=1b8c436eaf05   来源=human
   13:39:42  PLACE_AUTO_ADDED  命令=order.create#528a7c69   请求=1b8c436eaf05   来源=human
   13:39:43  ORDER_DISPATCH    命令=order.assign#1b9da010   请求=14b1ca7afb15   来源=human
   13:39:43  ORDER_CANCEL      命令=-                      请求=61c964a5105d   来源=human
[账本] 0 行     [司机账单] 0 行
[事件] 3 行（按 aggregate_id）
   事件#2  orders.created    sent  重试=0
   事件#3  orders.assigned   sent  重试=0
   事件#5  orders.cancelled  sent  重试=0
[通知] 8 条（本单相关）  order.created / order.assigned / order.dispatched / order.cancelled …
```

⭐ **闭环的那一处**：三个 `请求=` 就是 App/客户端在响应头 `X-Request-ID` 里拿到的那三个串
（`1b8c436eaf05` / `14b1ca7afb15` / `61c964a5105d`）—— 「客户端看到的号」与「审计行记的号」是同一个。

⭐ `ORDER_CANCEL` 的 `命令=-` **不是缺陷**：迁移 008 的文件头写着「**不走命令层的路径**本来就没有 command_id」，
而本轮命令层只覆盖 `order.create` / `order.assign`（`app/commands/order.py` + `orders_assignment.py`）。
⛔ 这一条如实记着，属 R3-04 的**已知边界**，留给后面决定要不要把撤销也纳入命令层。

### 8.4 库端对账（只读 SQL）

```text
operation_logs：共 4467 行 ｜ 带 request_id 4 行 ｜ 带 command_id 3 行 ｜ origin='human' 4467 行
本单 4 行：ORDER_CREATE / PLACE_AUTO_ADDED / ORDER_DISPATCH / ORDER_CANCEL（顺序、id 与 trace 输出一致）
outbox_events：6 行，全部 status=sent、attempts=0
orders：2402 → 2403（+1 = 这张测试单，现为 CANCELLED / cancelled_at=2026-09-26 13:39:43）
ledgers：4648 → 4648（⛔ 一分钱都没动）
operation_logs：4463 → 4467（+4，就是上面那 4 行）
```

---

## 九、⛔ 这份证据**证不了**什么

- ⛔ **不证业务正确**：只证「新版在生产上跑起来了、写路径留下了可追的痕迹」；
  **钱那条路没有被验过**（测试单没收款、没送达 ⇒ `ledgers` / `driver_bills` 都是 0 行）；
- ⛔ **不证多实例**：生产仍是「一个 systemd 里 2 个 worker」，nginx 仍是单后端 `proxy_pass`（**无 upstream**）；
- ⛔ **不证故障演练**：五个演练一条没跑（C 段未放行）；
- ⛔ **不证 uploads 可写**：没做写探测（会往生产放垃圾文件）；
- ⛔ **不证回滚可用**：备份存在且校验通过，但**没有真的恢复过一次**（那要写操作，属另一次许可）；
- ⛔ **不证 App 端**：`_prod_api_smoke.py` 打的是接口；真机界面这一轮没连生产验过。