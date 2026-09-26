# 生产只读验收清单（R3-05-C · PRODUCTION_ACCEPTANCE）

> **这份文档是什么**：第三轮指南 §十八（R3-05-C）要求建立一份生产验收清单，至少验证
> `/health` / 登录 / 查订单 / 查账 / 查司机账单 / 查通知 / **trace 一单** / Capability /
> **迁移**版本 / Redis / DB / uploads。指南同时写明：「**第一阶段不要直接拿生产做完整写操作测试。先 Read-only，
> 再有限写操作**」——所以这份清单**按权限分成两段**，⛔ 混在一起就会变成「借验收之名做写测试」。
>
> **状态（2026-09-26）**：只读那一段**已经跑过**（结果见下表「今天的状态」）；
> 需要写权限的那一段**一条都没跑**（等发布许可，与 `docs/RELEASE_CANDIDATE.md` 的第 7 步是同一件事）。

---

## 一、这段怎么跑

```bash
python _tools/ops/_prod_smoke.py --readonly            # 一次跑完「只读」列里的全部项，退出码 0/1/2
python _tools/ops/_health_check.py                      # 四个阈值（服务/证书/磁盘/数据库+发件箱）
```

退出码口径（⛔ 与 `_health_check.py` **不同**，别混）：
- `_prod_smoke.py`：**0** = 现状健康**且**与这一版代码一致（发布后应当是它）；**1** = 现状健康但与这一版代码不一致；**2** = 现状本身有问题。
- `_health_check.py`：**0** 全绿 / **1** 有告警 / **2** 有失败。

---

## 二、验收项（12 项，逐条给了命令与判据）

| # | 项 | 权限 | 命令 | 通过的判据 | 今天的状态（2026-09-26） |
|---|---|---|---|---|---|
| 1 | 服务健康 `/health` | 只读 | `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health` | 200 | ✅ 200（`{"status":"ok","version":"0.2.0","redis":"ok"}`） |
| 2 | 登录 | **写**（登录会写审计/最近登录） | `POST /api/v1/auth/login`（App 或 curl） | 拿到 token；错误口令被拒 | ⛔ 未跑（要写权限） |
| 3 | 查订单 | 写（要 token） | `GET /api/v1/orders?limit=5` | 200；单号/状态与库一致 | ⛔ 未跑 |
| 4 | 查账（账本流水） | 写（要 token） | `GET /api/v1/ledger/entries?from=&to=` | 200；金额与 `cash_flows` 对得上 | ⛔ 未跑 |
| 5 | 查司机账单 | 写（要 token） | `GET /api/v1/freight-settlement?from=&to=` | 200；与 `driver_bills` 合计一致 | ⛔ 未跑 |
| 6 | 查通知 | 写（要 token） | `GET /api/v1/notifications` | 200；条数与库一致 | ⛔ 未跑 |
| 7 | **trace 一单** | 只读 | `python _tools/ops/_trace_order.py <订单号>`（**本轮还跑不了**：生产代码里没有 `request_id`/`command_id` 列） | 一条命令打完整条链（命令/事件/账本/账单/通知） | ⛔ 生产缺列 → 发布后才可能通过；只读 SQL 已核：`operation_logs` 4463 行、最近一单 SO202609222864904837 有 5 行审计 |
| 8 | Capability（能力表） | 只读（静态产物） | `python _tools/qa/_check_capability_registry.py`（本机）＋发布后核 App 侧入口 | 26 条能力各有执行点；App 看不到多余入口 | ✅ 本机（判据）；⛔ 生产端未验 |
| 9 | **迁移**版本 | 只读 | `cd /opt/SOrders/backend && .venv/bin/python -m app.migrations status` | 「当前版本：8 / 待跑：0 条」 | ⛔ 生产**没有** `schema_versions` 表（还没上这一版代码） |
| 10 | Redis | 只读 | `redis-cli -h 127.0.0.1 -p 6379 ping` | `PONG` | ✅ PONG（6.2.20）；⚠️ keyspace 空、无口令（既知） |
| 11 | DB | 只读 | `mysql -N -B -e "select 1"` ＋ 表数/体积 | 可达；44 张表；⚠️ `time_zone` 待发布后复核 | ✅ 可达（44 张表 / 11.6 MB） |
| 12 | uploads | 只读 | `du -sh <uploads>` ＋ 文件计数（`find` 配 `wc -l`） | 文件数与体积可读 | ✅ 2115 个文件 / 187M（⛔ **可写性没验**：写探测会往生产放垃圾文件） |

---

## 三、写那一段的纪律（等发布许可）

1. ⛔ **不用生产做「完整写操作测试」**：只做**有限写**——建 1 张测试单、派 1 次、撤 1 次；
2. 每一步都**留痕**：操作前后的行数、单号、金额（用 `_trace_order.py` 或只读 SQL 取证）；
3. 测试数据**当场撤掉**（撤销而不是删除，因为删除是软删、也要留痕）；
4. 任何一条不符合判据 → 停手，按 `docs/RELEASE_CANDIDATE.md` §五 处置。

---

## 四、⛔ 这份清单证不了什么

- ⛔ 它**不证**「业务正确」：只读项只证「接口活着、数与库一致」；
- ⛔ 它**不替代** `docs/R3_FAILURE_DRILL.md`（故障演练是另一份）；
- ⛔ 今天这份清单里**只有只读那一段有结果**，写那一段一行都没有 —— 别把「清单写好了」读成「验收过了」。
