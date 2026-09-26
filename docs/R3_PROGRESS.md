# R3 第三轮整改进度与退出条件台账

> **规则**：这份文件是「已完成」三个字的唯一出处。⛔ **没达到退出条件的里程碑就是没完成**，
> 不许用「已经差不多了」（指南 L1003）。
> **代码基线**：`d4be6f4` ｜ **指南**：`docs/ARCHITECTURE_RECTIFICATION_R3.md`
> **事实优先**：每一行的 `复现：` 后面必须是真能跑的命令；跑不通就是 ❌，不许写 ✅。

---

## 最终验收矩阵

12 项能力 × 5 个层次。⛔ 一行的意义是**这一格被证明过**，不是「代码里有」。
`—` = 这一轮不适用；`❌` = 还没证明。

| 能力 | 代码 | CI | Staging | Production | Failure Drill |
| --- | --- | --- | --- | --- | --- |
| Migration | ✅ | ✅ | ❌ | ❌ | ❌ |
| Order Command | ✅ | ✅ | ❌ | ❌ | ❌ |
| Money | ✅ | ✅ | ❌ | ❌ | ❌ |
| Capability API | ✅ | ✅ | ❌ | ❌ | ❌ |
| Capability AI | ✅ | ✅ | ❌ | ❌ | ❌ |
| Capability UI | ❌ | ❌ | ❌ | ❌ | ❌ |
| Capability Audit | ❌ | ❌ | ❌ | ❌ | ❌ |
| Outbox | ✅ | ✅ | ❌ | ❌ | ❌ |
| Scheduler | ❌ | ❌ | ❌ | ❌ | ❌ |
| Upload | ❌ | ❌ | ❌ | ❌ | ❌ |
| Socket multi-instance | ❌ | ❌ | ❌ | ❌ | ❌ |
| Trace | ✅ | ✅ | ❌ | ❌ | ❌ |

**读表须知**

- `代码 ✅` 的意思是：有判据在每次全量检查里核它，且现在全绿（`python _tools/qa/_check_all.py` → 113/113 之后是 113）。
- `CI ✅` 的依据是：这条判据确实在 `_check_all.py` 里，而 CI 的 Gate 在 `7cc2f7a` 整轮 success。
  ⚠️ `7cc2f7a` **之后**的提交，CI 还没确认过 —— 所以这一列的 ✅ 有保质期，重新跑一次 CI 才算数。
- `Staging` 一列全是 ❌，因为**这个项目没有 staging 环境**。这一列留着是为了让「生产没验过」这件事一直可见。
- `Migration` 的 `代码 ❌` 说的是 **R3-01 要解决的那件事**（import 时执行 DDL），不是「迁移不存在」。

## 三层完成度矩阵（指南 §二十五 原则三）

| 四根主梁 | Code Ready | CI Proven | Runtime Proven |
| --- | --- | --- | --- |
| Migration 不再有隐式副作用 | ✅（R3-01） | ❌ | ✅ 本机真进程真库（生产 ❌，R3-05） |
| Capability 四端同源 | ❌（UI/Audit 待做） | ❌ | ❌ |
| 两个实例真的同时跑过 | ❌ | ❌ | ❌ |
| 生产真的跑过 + 故障演练 | ❌ | ❌ | ❌ |

---

## R3-00 Baseline（本轮起点）

- ✅ 指南已归档：`docs/ARCHITECTURE_RECTIFICATION_R3.md`（SHA256 `193AB545…5297`，1219 行）—— 复现：`Get-FileHash docs\ARCHITECTURE_RECTIFICATION_R3.md`
- ✅ 禁做清单已机器化：`docs/R3_CONSTRAINTS.md`（27 条，19 条棘轮 + 8 条阶段）—— 复现：`python _tools/qa/_check_r3_constraints.py`
- ✅ 基线数字已冻结：静态检查 112/112、后端用例 1015 passed —— 复现：`python _tools/qa/_check_all.py`
- ✅ 契约快照已在库：`_tools/qa/_api_snapshots/r2-02-before.json`（233 条路由）—— 复现：`python _tools/qa/_api_contract_snapshot.py --list`

## R3-01 Migration Lifecycle（最高优先级）

退出条件（指南 L222-232 原文十条）：

改了什么：

1. `app/database.py` **摘掉 import 时的 `bootstrap_schema(engine)`** —— 现在它只有 engine / session；
2. `app/core/schema_bootstrap.py` 拆成两个角色：`apply_runtime_self_heal`（幂等自愈）与
   `prepare_schema`（**迁移的唯一入口**：自愈 → 版本化迁移）；旧名 `bootstrap_schema` 保留为「只自愈」；
3. `app/main.py` 启动**不迁移**：只 `schema_ready()` 只读核对，没准备好就拒绝启动（逃生开关不变）；
4. `app/migrations/_runner.py` 新增 `schema_ready()` —— ⛔ 它**不建表**（所以不能调 `applied_versions`）；
5. 测试自己显式建库（`conftest`：`create_all` + `run_migrations`），不再依赖 import 副作用；
6. 新增判据 `_tools/qa/_check_import_purity.py`（真库 + 子进程核对）+ 反向验证 7/7；
7. 新增 `_tools/ops/_migration_tests.py`（--fresh / --old / --concurrent / --fail-fast）。

**跑这一块时抓到的两个真缺陷**（都不是测试写错了）：

- 并发迁移测试当场红了：第二个进程不是「等待」，而是撞 `table already exists` **直接失败退出**。
  根因是「import fcntl 失败就往下跑」——**Windows 上这把跨进程锁等于没有**。
  修法：抽出 `app/core/file_lock.py`（POSIX 用 flock、Windows 用 msvcrt.locking），两条路径共用。
  ⛔ 期间踩到第二个坑：锁文件用 `'w+'` 打开会**截断**，而 Windows 的文件锁是强制的 →
  第二个进程在 `flush()` 上直接 `PermissionError`（还是「不等待」）。改成 append 打开才对。
- 自愈与迁移各自拿各自的锁，中间有一个窗口（放锁之后、拿锁之前）——另一个进程正好在里面跑自愈，
  两边的 DDL 撞在一起。修法：`prepare_schema` 用**同一把锁**罩住两段，`FileLock` 支持同进程重入。

退出条件（指南 L222-232 原文十条）：

- ✅ 退出条件 1/10：`import app.database` 不执行 DDL —— 复现：`python _tools/qa/_check_import_purity.py`
- ✅ 退出条件 2/10：application startup 不执行 migration（只 `schema_ready` 核对）—— 复现：`python _tools/qa/_check_import_purity.py`
- ✅ 退出条件 3/10：migration 有唯一入口（`prepare_schema` ← `python -m app.migrations upgrade`）—— 复现：`python _tools/qa/_check_migrations.py`
- ✅ 退出条件 4/10：migration version 正确（版本 7，7 条全部记账）—— 复现：`cd backend; python -m app.migrations status`
- ✅ 退出条件 5/10：空库迁移通过（48 张表 / 版本 7 / 启动核对通过）—— 复现：`python _tools/ops/_migration_tests.py --fresh`
- ✅ 退出条件 6/10：旧库迁移通过（无迁移记录的老库 → 版本 7，结构一行没丢）—— 复现：`python _tools/ops/_migration_tests.py --old`
- ✅ 退出条件 7/10：两个进程同时迁移 → 都成功、每个版本恰好一行 —— 复现：`python _tools/ops/_migration_tests.py --concurrent`
  ⚠️ 本机是 Windows + SQLite，证的是**本机互斥**；跨主机那一段是 MySQL `GET_LOCK`，要到 R3-03 在生产库上真跑一次才算数
- ✅ 退出条件 8/10：迁移失败 → 不记账、不半残（失败版本没进版本表，1..7 都在）—— 复现：`python _tools/ops/_migration_tests.py --fail-fast`
- ✅ 退出条件 9/10：后端用例全绿（**条数以 `pytest -q` 自己打印的为准**）—— 复现：`cd backend; python -m pytest -q`
- ✅ 退出条件 10/10：全量静态检查全绿（**脚本数/逐条耗时/总耗时都以它自己打印的为准**）—— 复现：`python _tools/qa/_check_all.py`

**三层完成度**：Code Ready ✅ ｜ CI Proven ❌（还没推）｜ Runtime Proven ✅（本机真进程真库；**生产**仍未验证）

## R3-02 Capability → UI / Audit

R3-02a（已做，提交见下）：把「能力」变成**可生成的唯一真源**，并补齐两张此前不存在的真源表。

1. `backend/app/core/role_capabilities.py`（新）：**角色能力** —— 没有权限点、但仍被角色门护着的事实
   （地址与联系人 / 地点库 / 单位换算 / 货主自己的账 / 车辆）。每条带 `gate=文件:行号`，判据去核那一行真有角色门。
2. `backend/app/core/capability_audit_coverage.py`（新）：**能力 ↔ 审计动作码的覆盖**（不是一一映射）。
   覆盖 91 个动作码 + 1 条例外（`AI_UNDO`）+ 3 条豁免（写能力但没有动作码，各写了为什么）。
3. `_tools/ai/_gen_capability_snapshot.py`（新）→ 三份产物：
   `docs/CAPABILITY_SNAPSHOT.json`、`android/.../core/Capabilities.kt`（带 `SOURCE_HASH`）、`docs/CAPABILITY_AUDIT_COVERAGE.md`。
4. `_tools/qa/_check_capability_unification.py`（新，5 组）+ 反向验证 8/8。

**为什么选「生成快照」而不是 `/me/capabilities` 接口**（指南说这一步要按 App 架构验证）：这个 App 已经在用
生成快照这条路（`_gen_ai_read_catalog.py` → `AiReadCatalog.kt`）。再开一条运行时通道等于给同一个问题造第二套机制，
而且按钮显隐会依赖一次网络往返。见生成器文档里的三条理由。

退出条件：

- ✅ 26/26 capabilities 有执行点 —— 复现：`python _tools/qa/_check_capability_registry.py`
- ✅ API 使用 Capability（第二轮已完成）—— 复现：`python _tools/qa/_check_capability_registry.py`
- ✅ AI 使用同一 Capability（第二轮已完成，走 `rbac.ROLE_PERMISSIONS`）—— 复现：`python _tools/ai/_check_role_parity.py`
- ✅ Audit action 能证明 write capability 的留痕覆盖（91 个动作码有着落 / 非双射 / 棘轮只减不增）—— 复现：`python _tools/qa/_check_capability_unification.py`
- ✅ 任意 capability 改动能够使相关生成物 / 检查立即变化 —— 复现：`python _tools/ai/_gen_capability_snapshot.py --check`（反向验证第 ① 条就是改一句话让它红）
- ✅ 不存在第二份**静态** Capability 真相（安卓**代码**里没有权限词表；生成物带 source hash，判据逐字比）—— 复现：`python _tools/qa/_check_capability_unification.py`
- ✅ **UI 不再自行定义角色能力** —— 复现：`python _tools/qa/_check_capability_unification.py`（第 6 组）
  + `android/gradlew` 不存在，用 `_agent/gradle/gradle-8.9/bin/gradle.bat :app:testPhoneDebugUnitTest --tests '*ModulesEntryTest*'`

  R3-02b 做的事：`ui/nav/Modules.kt` 里 `entriesFor(role)` 原来是 `when (role) { … -> 写死的那张表 }`；
  现在多了两张声明表 —— `ENTRY_CAPABILITY`（**入口 → 能力**，32 条映射，覆盖 34 个去重后的入口路由 ——
  有几个入口两端都有）与 `ENTRY_NO_CAPABILITY`（2 条，各写了理由：
  AI 助手入口本身不是业务动作；司机的「我的账本」端点是 `get_current_user` + 体内按人过滤，没有可问的名字），
  `entriesFor` 改成 `.filter { canSee(role, it) }`，而 `canSee` 只问生成物 `Capabilities.can(role.key, cap)`。

  **行为等价**由单测钉住（`ModulesEntryTest` 15 个用例全过，其中两个是这一轮加的）：
  「工作台入口是按能力筛出来的，今天三个角色一个都没被筛掉」逐条比对 `entriesFor(role)` 与改动前的清单；
  「每个入口都有着落」核例外表。⛔ 它同时是回归闸门：以后谁把某个能力从某个角色身上拿走，这条会红。

  **判据能看到什么、看不到什么**（写在判据里，防止被当成更强的保证）：
  能核「每个入口都有下落 / 没有多余键 / 键是生成物里真实存在的能力 / 筛选真的走了 `Capabilities.can`」；
  ⛔ **核不了**「这一格挂的能力**选得对不对**」—— 那要按 入口→屏幕→repo→端点→权限 四跳解析，本轮没做。
  选得对不对由上面那条行为等价断言兜底（挂错了货主会少一格，当场红）。
  ⚠️ 派单端的 24 格**现在筛不出差别**（派单员在 `BYPASS_ROLES` 里）—— 那 24 条能力标注是为
  「以后出现非绕过角色」准备的，今天证明不了对错，如实写在 `Modules.kt` 的注释里。

  ⚠️ **已知未做（不属指南七条退出条件，记在这里不藏着）**：`ai/AiWrite.kt` 的 `SHIPPER_ACTIONS`
  （13+ 项动作白名单）**仍是手写的**。它不是授权真相的副本（`_tools/ai/_check_role_parity.py` 逐条核过
  AI(role) ⊆ BACKEND(role)），但「货主的 AI 能用哪些动作」这件事目前由人写而不是由能力表推。
  要推的话得给每个动作声明能力并重做那条判据的推导链 —— 那会让它的「缺能力」半边失效（AI 由后端推出来
  就不再可能缺），需要先想清楚换来的那半边（「声明的能力必须与动作真打的端点一致」）够不够抵。

**三层完成度**：Code Ready ✅ ｜ CI Proven ❌（还没推）｜ Runtime Proven ✅（本机两个 flavor 的 Gradle 单测都跑过；**真机界面未验**）

## R3-03 Multi-instance Runtime（硬门槛）

工具：`python _tools/ops/_dual_instance.py --all`（真起两个 uvicorn :8111/:8112，共用一个库 + 一个上传目录）。
原始输出记在 `docs/R3_RUNTIME_EVIDENCE.md`；架构决策记在 `docs/R3_DECISIONS.md`。

- ✅ 两个实例同时运行（都接请求；**A 登录的 token 到 B 上也认**）—— 复现：`python _tools/ops/_dual_instance.py --all`（下面三条共用这一次运行）
- ✅ migration 只执行一次 —— 复现：`python _tools/ops/_migration_tests.py --concurrent`（R3-01 的用例，两个进程同时 upgrade）
- ✅ scheduler 只执行一次（启动即跑的那轮治理：**真跑 1 次 / 跳过 1 次**）—— 复现：`python _tools/ops/_dual_instance.py --all`
- ✅ upload 一致（A 传的图 B 取得到，**字节一致**）—— 复现：`python _tools/ops/_dual_instance.py --all`
- ✅ 杀掉 A 之后 B 继续服务（`/health` 200 + 登录读自己 200）—— 复现：`python _tools/ops/_dual_instance.py --all`
- ✅ 上传资产的运行模型已决策（**本机文件系统资产**；多实例＝同机多进程/同一挂载点；对象存储留 R4）—— 复现：`python _tools/qa/_check_r3_constraints.py`（`upload_decision_record` 探针）
- ❌ **Socket.IO 跨实例推送未验** —— 复现：`python _tools/ops/_dual_instance.py --socket`（它会如实打印「没验」）
  ⛔ 本机**没有 Redis**，Socket.IO 的跨进程适配器起不来，这一格**没有验**，不假装通过。
  要验需要有 Redis 的环境。⛔ 有一条**不能走**的路：借生产的 Redis —— 那会把测试实例的推送混进
  生产客户端的同一个 channel（除非用不同的 Redis DB 序号，而那就等于在生产机上起临时实例）。
  三条候选路径写在下面「卡在哪儿」一节。
- ❌ **nginx upstream + 失败摘除未验** —— 复现：`python _tools/qa/_check_multi_instance_readiness.py`
  （那道门的 `status` 仍是 `not-done`）。本机没有 nginx；它要动生产 nginx，属 R3-05（且要用户许可）。

### 卡在哪儿（需要你拍板，不必现在答）

这两个 ❌ 都卡在**环境**，不是卡在代码：

1. **装一个本机 Redis**（Windows 上可用 Memurai 或 tporadowski 的 redis 移植版）→ 就能在本机把 socket 那一格验掉；
   代价是动本机环境（多一个常驻服务）。
2. **在生产机上起一对隔离的临时实例**（不同端口 + SQLite + 独立的 Redis DB 序号）→ 能验 socket 与 nginx；
   代价是动生产机 —— 按禁做 #13/#14，这件事要你明确点头。
3. **留到 R3-05**：那时本来就要在生产上做 RC 与验收，socket/nginx 两格并进去一起验。
   代价是 R3-03 一直挂着一个 ❌（本轮就选了这条，因为它不需要额外许可）。

### 这一轮顺带修掉/发现的三件事（细节在 `docs/R3_RUNTIME_EVIDENCE.md`）

1. `GOVERNANCE_MARKER_PATH` 写死 `/tmp` → Windows 上标记**永远写不进去也读不到**（不报错）；
2. `_single_runner` 在 Windows 上是**空操作**（`import fcntl` 失败就放行）—— 与 R3-01 的迁移锁同一个毛病；
3. 我自己第一版的判据是错的：按「日志里出现几次『治理完成』」数，而那行**无条件打**，
   跳过时打的是 `{'skipped_same_day': 1}` → 「两个都跳过」被读成「两个都跑了」。现在按**返回的字典**判。

**三层完成度**：Code Ready ✅ ｜ CI Proven ❌（还没推）｜ Runtime Proven **部分**（本机同机双进程 4/5 个实验过；跨机器与 socket/nginx 未验）

## R3-04 Observability

指南 §R3-04-C 的原话：「第三步只做 structured logs + request_id + command_id + event_id + 关键 metrics。」
**本轮就做到这一步**：不上 Prometheus/Grafana/Jaeger/Loki/OTel/ELK（禁做 #12，`no_observability_stack` 探针盯着）。

- ✅ request_id 贯穿（第二轮已完成）—— 复现：`python _tools/qa/_check_traceability.py`
- ✅ **command_id 与 request_id / event_id 分成三个概念** —— 复现：`cd backend; python -m pytest tests/test_r3_trace_ids.py -q`（3 个用例）
  三个 id 各是什么、为什么不能合成一个：`backend/app/core/command_id.py` 的文件头写了；
  一句话：**一次请求可以跑多条命令**（批量派单 `batch-assign` 一次请求 → N 条 `order.assign`），
  **一条命令又可以产生多条事件**（`order.create` → `orders.created` + `orders.pending_pool_changed`）。
  三个用例分别钉住这三件事：ids 都非空且两两不等 / 一次批量请求 N 个 command_id 共用一个 request_id /
  一条命令入队 ≥2 条事件（各自的 event id 不同）。
- ✅ 业务指标（订单/命令/事件/通知/迁移/调度）—— 复现：`cd backend; python -c "import sys; sys.path.insert(0,'.'); from app.database import SessionLocal; from app.core.metrics import snapshot, NOT_TRACKED; print(len(snapshot(SessionLocal())), len(NOT_TRACKED))"`
  → `17 7`：**17 条现算指标 + 7 条「算不出来但写清了为什么」**（本轮新增 4 条：`sorders_commands_today`
  （按新加的 `command_id` 去重）、`sorders_notifications_created_today`、`sorders_outbox_retried_today`、
  `sorders_last_migration_duration_ms`）。
  ⛔ **指南点名的 12 个里，有 7 个落进了 NOT_TRACKED**，每条都写了「为什么算不出来 + 它该长在哪」：
  订单接单数（表上没有 `accepted_at` 列）、命令失败数（失败不写审计）、通知去重数（唯一索引冲突不记账）、
  迁移失败数（失败**故意**不写版本表）、调度选主/跳过（只在日志与标记文件里）、请求时延（要直方图，
  现算的均值会误导）。这符合本模块的规矩：**宁可空着并说明，也不要给一个看起来正常的假数**。
- ✅ 全链路诊断接口（人可读）—— 复现：`cd backend; python ..\_tools\ops\_trace_order.py --latest`
  → 一条命令打完整条链：**命令 `command_id` 与请求 `request_id` 并排**、事件带上自己的 `事件#id`、账本、司机账单、通知。
  ⚠️ 老数据（R3-04 之前）的审计行 `command_id` 是 `-`：那时还没有这一列 —— 那是事实，不是缺陷。
- ✅ 没有引入大型观测平台 —— 复现：`python _tools/qa/_check_r3_constraints.py`（`no_observability_stack` 探针）

**三层完成度**：Code Ready ✅ ｜ CI Proven ❌（还没推）｜ Runtime Proven ✅（本机真库真请求：3 个用例跑在真实接口上）

## R3-05 Production Release

- ❌ Release Candidate 记录齐全（SHA / 迁移版本 / 各端版本 / 依赖锁 / 配置校验和）—— 复现：`docs/RELEASE_CANDIDATE.md`
- ❌ 备份 —— 复现：`python _tools/backup/_pre_release.py --note "R3"`
- ❌ 迁移（先迁移后应用）—— 复现：`python _tools/deploy/_release.py --step migrate`
- ❌ 启动新后端 —— 复现：`python _tools/deploy/_release.py --step start`
- ❌ health —— 复现：`python _tools/ops/_health_check.py`
- ❌ 只读烟测 —— 复现：`python _tools/ops/_prod_smoke.py --readonly`
- ❌ trace 一单 —— 复现：`python _tools/ops/_trace_order.py <订单号>`
- ❌ 回滚 / 前向修复方案已写 —— 复现：`docs/RELEASE_CANDIDATE.md`

## R3-06 Failure Drill

- ❌ Drill A：杀掉一个 worker，是否恢复 —— 复现：`python _tools/ops/_drill.py --case worker-crash`
- ❌ Drill B：Redis 不可用，业务还能不能工作 —— 复现：`python _tools/ops/_drill.py --case redis-down`
- ❌ Drill C：事件消费延迟，业务数据是否仍然正确 —— 复现：`python _tools/ops/_drill.py --case event-delay`
- ❌ Drill D：迁移锁竞争，第二实例是否正常等待 —— 复现：`python _tools/ops/_drill.py --case lock-contention`
- ❌ Drill E：磁盘将满，能否被发现 —— 复现：`python _tools/ops/_drill.py --case disk-full`

## R3-07 Meta-System Hardening

指南 §二十一 的四条 + §二十二 的依赖决策。**a / b / c 三条已落地**，只剩 §二十二 的依赖决策（要用户拍板）。

- ✅ 判据不许静默空转（本轮 `_check_r3_constraints.py` 自带反空转下限）—— 复现：`python _tools/qa/_check_r3_constraints.py`
- ✅ **生成物新鲜度**（R3-07a）—— 复现：`python _tools/qa/_check_generated_freshness.py`
  真源表在 `_airepo.GENERATED_ARTIFACTS`（**生成器与判据读同一份**，不各写一遍），四个产物各自声明
  `source_hash`：`docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md`、`docs/ai/ai_read_catalog.json`、
  `docs/CAPABILITY_SNAPSHOT.json`（+ `source_commit` + `generated_at`）、`docs/PROJECT_MAP/09A_HINT_CATALOG.md`。
  判据自己重算指纹（**不信任产物里那串**）+ 跑每个生成器的 `--check` + 核提交/时刻是否真实；
  反向验证 7/7（改真源没重跑 / 手改指纹 / 抹掉指纹 / glob 空转 / 编造提交 / 清单被掏空）。
  ⚠️ `generated_at` 每次生成都会变，所以能力快照的 `--check` 会把它**归一化掉**再比对 ——
  真正回答「哪一版代码」的是 `source_hash`。这句话写进了生成器与判据两边。
  ⛔ **2026-09-26 修（本机一天被它绊倒两次之后）**：`_airepo.source_fingerprint` 原来把**原始字节**
  直接进哈希，而本仓库 `core.autocrlf=true` —— 同一个提交，Windows 检出是 CRLF、CI（Linux）检出是 LF，
  于是**同一个代码库在两台机器上指纹不一样**：本机全绿、**CI 上会红**。触发它的三件小事都真的发生过：
  `git checkout -- <file>` 还原两个被写坏的文件、反向验证的注入+还原碰到 CRLF 文件、以及一次批量改法。
  已改成**哈希前把 `\r\n` 归一成 `\n`**（内容没变 ⇒ 指纹不变；内容变了 ⇒ 照样算得出来），
  四份产物按新口径重新生成（只动 `source_hash` 一行 + 能力快照的 `generated_at`），反向验证仍 7/7。
  ⛔ 顺带说清一件事：这条判据报红时的提示原来只有「源码变了而产物没重跑」，在**换行漂移**的情况下
  那句话是**误导**（内容一个字没变）。口径归一之后，它才真的只表示「内容变了」。
- ✅ **反向验证必须完整还原**（R3-07b）—— 复现：`python _tools/qa/_check_reverse_verify_restore.py`
  新增判据把「还原契约」抽出来逐份核（143 份），分**两级**、各有只增不减的棘轮：
  · **L1 快照 + 还原**：**141/143**（字节级 `read_bytes`+`write_bytes`，或文本级 `read_text`+`write_text(newline=)`，
    或 `open(..., newline=)`）—— 下限 135；
  · **L2 跑完**逐字节比对**证明一模一样**：**106/143** —— 下限 106。⛔ **剩下的 37 份才是缺口**：
    它们是「按原文写回、但没比对」，**声称**还原了，谁也没证明。
  ⛔ **2026-09-26 修了两件事，都要记清楚（不是「缺口改小了」）**：
    ① 原判据**自己读窄了** —— 只认变量名（`dirty(` / `== raw` / `!= original`），认不出
    `dirty = [rel for rel in touched if (ROOT/rel).read_bytes() != originals[rel]]` 这种写法，
    于是 **14 份明明已经逐字节证明了的脚本被记成「没证明」**（旧账面写「72/141，差 69 份」，
    真实是 88，差 55）。这就是本仓库的老账「判据读得比事实窄 ⇒ 缺口是假的」，与「判据被文字误伤」同源。
    ② 又给 **18 份**补上「还原**当场核对**」（还原后立刻 `read_text() != original` 就记账）：
    第一批 6 份 `geocode` / `card_claim` / `ctx_budget` / `cost_history` / `image_refs` / `billing`；
    第二批 12 份 `local_reads` / `read_caps` / `sun_theme` / `undo` / `catalog_and_scope` /
    `concurrency_guards` / `cost_basis` / `input_guards` / `place_and_picker` / `product_guards` /
    `report_guards` / `soft_delete`。**18 份各自跑过一遍，全部退出 0**（证明没污染源码树）→
    L2 88 → **106**，棘轮跟着抬到 106。
    ③ ⛔ **又抓到一个更隐蔽的：换行符会漂**（2026-09-26 实测事故）—— 一整轮 `_check_all.py` 从绿变红，
    期间唯一动过 `backend/app/**` 或 `android/app/src/main/**` 的是那 12 份反向验证的**注入 + 还原**；
    `git status` 干净，但 `09A_HINT_CATALOG.md` 的 `source_hash`（对这两个 glob 取**原始字节**哈希）
    与现算对不上 ⇒ **有文件的字节被改了，而 git 看不见**（实测 90 份文件的 CRLF/LF 差异被 autocrlf 归一）。
    机制：快照用**不带** `newline=` 的 `read_text()`（通用换行解码，CRLF 在内存里已经变成 LF）＋
    还原用 `write_text(..., newline="")`（不翻译、原样写回）⇒ **一个 CRLF 文件还原后成了 LF**。
    ⛔ 连 L2 的「文本级证明」都看不出来：`read_text() != original` 两边都被归一成 LF，恒等。
    修法：**两边都带 `newline=""`**（对 UTF-8 文件与字节级等价）。判据新加一格
    **L3「换行符会漂的脚本」= 34 份（上限 34，只减不增）**；当轮先把生成物重新生成（只动 `source_hash` 一行）
    让门变绿，⛔ 不删这一格、也不放宽指纹口径 —— 它正是「反向验证不许把工作区改坏」里最难看见的那一半。
    ④ **L3 这一格本轮收紧了一次口径 + 修了 12 处**（⛔ 记清楚，不然下次看不懂数字是怎么变的）：
    · 口径 v1 太宽（文件里同时有裸 `read_text(` 与 `write_text(` 就算）→ 把**只读来比对、不写回**的
    脚本也算成风险，**虚报 11 份**；口径 v2 = 「**读来的文本会被写回去**」（`名 = …read_text(不带 newline=)`
    且那个名字进了 `write_text` / `write_bytes` 的实参）。判据读宽了与读窄了同样糟，这条也写进了判据注释。
    · 本轮把 **12 处**改成**字节级**（快照 `read_bytes()` + 还原 `write_bytes()`，我加的核对行也一并改成字节比较）：
    `card_claim` / `ctx_budget` / `geocode` / `image_refs` / `cost_history` / `soft_delete` / `read_caps` /
    `export_cells` / `product_guards` / `user_search` / `order_purge_fk`（它有两处：`original` 与 `init_src`）。
    **每一份都跑过一遍，全部退出 0**。
    · 本轮第二批又把 **16 处**改成字节级（billing / local_reads / sun_theme / undo / catalog_and_scope /
    concurrency_guards / cost_basis / enum_drift / freight_settlement_ui / input_guards / migrations /
    paid_actions / report_guards / report_window / shipper_settle_ceiling / single_source），逐份跑过全绿，
    于是 **L3 22 → 6 份**：剩下 6 份形状各不相同（`coverage_input` / `multi_request` / `fuzz_safety` /
    `core_freeze` / `loop_e2e` / `place_and_picker`），要逐份看代码再改。
    · ⛔ 两个自己踩的坑（都跟换行符同源，记下来免得再踩）：① 第一版批量改法用 `$` 匹配行尾，
    **CRLF 文件一条都没匹配上**（行尾还留着一个 `\r`），16 份被静默跳过 —— 是看『SKIP』名单才发现的，
    它自己不报错；② 往 CRLF 文件里**插一行 LF** 会造出混合行尾（比原来更糟），所以插入的新行必须
    跟随原文件的换行符。
    ⑤ ⛔ **本轮还抓到一个真正的破坏性缺陷**（就是这一格存在的理由）：`_reverse_verify_report_guards.py`
    的「锚点跟着搬家走」分支里写着 `path, original = _c, _t` —— **字节快照没跟着搬**。后果：还原把
    `services/reports_service.py`（1176B 的壳）的字节**写进了** `reports/turnover_query.py` 与
    `reports/product_query.py`（整份覆盖，`git status` 只看得出「改过」，看不出是哪一步干的）。
    ⛔ 而它自己那句「还原后与快照不一致就记账」拿的是**同一份错字节** ⇒ 恒等、**静默通过** ——
    这正是「判据盯的是错的那一头」的样子（与我这轮修的 L2 口径同源）。
    处置：① 4 份同类脚本（`cost_basis` / `report_guards` / `report_window` / `single_source`）改成**分别赋值**
    ＋**同时重取 `original_bytes`**，并加一条**注入前的不变量**「快照必须属于要改的那个文件」；
    ② 判据新增一条**代码形状红线**：凡出现 `path, original = _c, _t` 一律红（防复发）；
    ③ 4 份重跑 → 全绿（29/29、19 条、5 条、8/8），跑完 `git status backend/` 干净。
    ⑥ **另一类「看着跑过了」**：`_reverse_verify_shipper_settle_ceiling.py` 不 import `_airepo`、自己也没设
    stdout，在 GBK 控制台下**打第一个 ✅ 就崩**（EXIT=1、4 秒）——一条都没验却像个跑过的样子。
    同类还扫出 `_probe_return_request.py`（实测跑到第 187 行打「退款 ¥…」时崩，前面的探针结果全白跑）。
    处置：两份都补 `reconfigure`；`_check_tool_scripts.py` 新增一条判据「会打 ✅/❌ 就必须能把它们打出来」
    （⛔ 第一版只看本文件 → **虚报 5 份**：它们靠 `from _check_pagination_wiring import …` 间接拿到
    `_airepo` 的编码设置；改成**跟着 import 走**（深度 ≤ 3）之后只剩 1 份真犯规，已修）。
    ⑦ **一条没解决的**（如实记着）：`_reverse_verify_enum_drift.py` 里「生成器把可空性写死」那条注入
    **打不动判据**（注入后不报红）—— 下一轮查是注入锚点过期，还是判据真缺这一条规则。
    ⑧ ⭐ **补上「外部证明」这一层**（指南 §二十一 ② 的原话：before snapshot = after restore snapshot）：
    上面 L1/L2/L3 都是**每份脚本自己写的**核对，而自己写的核对可能**盯错一头**（⑤ 就是），
    所以 `_reverse_verify_all.py` 现在**每跑完一份就逐字节比对「现场 vs 开跑前的快照」**：
    · 不一致 → 打印**是哪一份**、**哪些文件**，当场按快照写回（不让坏代码传染给下一份），并**计为不达标**；
    · 现场多出来的文件同样计为不达标（只报告不删 —— 用户底线是「不要删了就搞不回来了」）；
    · 快照范围 5 个目录 → **17 个**（原来只盯 `_tools/ai`，而注入目标早就散到 `_tools/qa`、`_tools/notify`；
    有些反向验证还会**原地改检查脚本再改回来**）。
    反例实测（临时探针故意写脏一个文件且 `exit 0`，验完已删）：
    `❌ _reverse_verify_zz_drift_probe.py（0.2s）` → 「⛔ 跑完**没把工作区还原干净**（1 个文件，已按快照写回）：
    backend/app/services/reports/turnover_query.py」，运行器 exit 1，且那个文件逐字节回到 HEAD ✓；
    真实脚本上跑（`--only _reverse_verify_dep_declaration`）→ 全绿。
    ⑨ 顺带修掉 2 处**永远会 `TypeError` 的兜底调用**：`restore_snapshot(snapshot_dir())` —— 那个函数从来没有参数
    （只在「自检失败」分支里才会走到，所以从没暴露过），已改成 `restore_snapshot()`。
    ⑩ ⭐ **L2 又补 10 份（106 → 117）**：`read_src`/`write_src` 那一族（39 份共用同一对助手）本轮先改 10 份 ——
    还原调用改成 `restore_src`：**写回后重新读回来逐字节比**，对不上立刻非零退出。10 份逐份跑过：
    **8 份全绿**（coverage 6/6、field_keys 5/5、price_table 7/7、prepare_no_write 8/8、report_priority 7/7、
    card_markdown 15/15、check_blindspots 11/11、read_roles 9/9）。
    ⛔ 另外 2 份的失败**与本轮改动无关、是早就烂了的注入锚点**（已用 `git show HEAD:` 的原版跑过、同样失败）：
    `_reverse_verify_write_roles.py` 3 条 `[SKIP] 注入没生效`、`_reverse_verify_doc_refs.py` 1 条 ——
    下一轮补替换串（那是「注入没生效」，不是「还原没证明」，所以 L2 计数照样算）。
    ⑪ **全量一遍的实测成本**（这一轮试过）：143 份 × 平均 67 秒 ≈ **2.7 小时**（前 7 份 470 秒）—— 跑的时候
    整个工作区不能动，所以本轮改成**分域/分批**跑。⛔ 中途停掉按文档处置：杀进程 → `_recover_injections.py`
    还原现场 → 清注入锁（本轮真做过一次：还原了 1 个被注入的文件、`git status` 回到干净）。
    ⑫ **L2 再补 19 份（117 → 136）**：`read_src`/`write_src` 那一族剩下的 19 份一次改完（同一套改法：
    `write_src` 返回写出的字节 ＋ `restore_src` 写回后 `p.read_bytes() != wrote` 逐字节核对），
    **19 份逐份跑过、全部退出 0**（notify 45/45、ledger_dashboard 33/33、contact_names 26/26、order_templates 26/26、
    product_card 26/26、shipper_ledger_stats 25/25、supplier_payables 25/25、nav 25/25、order_driver_call 24/24、
    freight_pricing 23/23、driver_money 19/19、ledger_manual_entry 19/19、workbench_header 18/18、expense_page 17/17、
    ledger_cash 17/17、answer_style 14/14、ai_default_key 12/12、ai_entry 9/9、form_panel 8/8）。
    ⛔ 这一族共 39 份，还剩 **10 份形状不同**（还原调用不是 `finally: write_src(...)`）：`ai_declarative_crud` /
    `ai_dto_defaults` / `counter_updates` / `inventory_reservation` / `permission_points` / `return_request` /
    `round17` / `round18` / `round19` / `round20` —— 要逐份看代码。
    ⑬ **补掉 4 条烂掉的注入锚点**（都是「源码改了、替换串没跟着改」→ 静默 `[SKIP]`，而 SKIP 计为不成立）：
    `_reverse_verify_write_roles.py` 的 3 条 —— ① 判据改收 `AiActor?`（`val role = actor?.role ?: return emptyList()`）、
    ② 货主那一支从一行变四行（多了 roles/memberOnly 两层条件）、③ `AiRolePrompt.brief(...)` 的首参由 `tools.role` 改成
    `tools.actor`；外加一条**期望词过期**（判据那句改成「货主确实按白名单 + member 过滤」）。修完 **15/15 全绿**。
    ⚠️ `_reverse_verify_doc_refs.py` 还剩 **1 条**（「红线脚本印不出任何小节号」）：判据确实红了（退出码 1），
    但脚本期望的那句文案没出现在输出里 —— 下一轮让它在 `[MISS]` 时把判据输出打出来再定位。
    ⑭ ⭐ **改动自己的连锁反应被静态审计当场抓住**：给 `write_src` 加「返回写出的字节」之后，
    `_reverse_verify_reverse_verify_restore.py` 的 ② 号注入（锚点原文写的是 `path.write_bytes(data.encode("utf-8"))`）
    **变成恒 SKIP** —— `_check_reverse_verify_anchors.py`（静态解析注入表）在 `_check_all.py` 里当场报红、
    并点名「哪一份脚本 / 哪条注入 / 哪个目标文件 / 原文找不到」。锚点已改成现在的写法，审计回到
    「1289 条注入原文全部还在」。⛔ 这正是「改一处要想到它的下游」的机器化版本：判据先喊，不用等到有人跑那份 RV。
    ⑮ **L3（换行符会漂）收到 0，L2 到 140/143**：4 份真的会漂的（`coverage_input` / `fuzz_safety` /
    `loop_e2e` / `place_and_picker`）改成「快照 `read_bytes` + 还原 `write_bytes` + 还原后逐字节核对」；
    另给 `multi_request`（还原本来就是 `shutil.copy2`）与 `core_freeze`（还原本来就是 `write_bytes`）补上核对那一句。
    逐份跑过、全绿（coverage_input 1/1、loop_e2e 3 种、fuzz_safety 四道轨、place_and_picker 23/23、
    multi_request、core_freeze 9/9）。
    ⛔ **L3 的口径本轮又收了一次**（这是第三次收紧）：原来「文件里同时有裸 `read_text(` 与 `write_text(`」就算风险，
    现在要求**还原路径本身不是字节级**（没有 `write_bytes(` / `shutil.copy`）—— `multi_request` 与 `core_freeze` 的
    注入确实写 LF，但还原是**字节复制**，文件最终一模一样；judged 读宽了同样是错。
    剩 L2 **3 份**：`ai_batch` / `invariants` / `root_clean`（最后一份在例外表里：它注入的是临时探针、自己删掉）。
    ⑯ ⛔ **本轮又踩到「单独跑一份反向验证没有兜底」**：改 `place_and_picker` 的中途它 `NameError` 崩在还原**之前**，
    把 `android/.../ProductPicker.kt` 的注入留在树里（`git status` 就一行 ` M`）—— 它**自己那句还原核对根本没跑到**，
    而外部证明层（`_reverse_verify_all.py` 的逐份快照比对）只在**批跑**时才兜。已按 `git diff` 认出来源、
    `git checkout --` 还原，红线恢复（1282 项全通过）。教训：**单独跑一份 RV 之前先想好兜底**（批跑有快照，单跑没有）。
    ⑰ **L2 收口到 142/143**：最后两份补上「还原后逐字节核对」（`ai_batch` 的 `Sandbox.restore` 逐份比、
    `fuzz/_invariants` 的 `INV.write_bytes(orig)` 之后比），逐份跑过全绿。⛔ 剩下那 1 份是 `_reverse_verify_root_clean.py`：
    它在例外表里（注入的是**临时探针文件**、自己删掉，没有「还原源码」这回事）⇒ **L1 141/143、L2 142/143、L3 0
    就是这套契约的理论上限**：凡是「会改源码」的那 141 份，都既有字节级快照/还原、又有逐字节证明。
    ⑱ **`_reverse_verify_doc_refs.py` 最后那 1 条用例修好了**（期望词过期）：注入「让红线脚本印不出小节号」之后，
    判据**确实会红**（退出码 1），但报的是「❌ 对不上的引用 18 个」，不是脚本期望的「没能从红线脚本里读出小节号」——
    两句话证明同一件事（**判据不会静默空转**），期望词按**实际行为**改，⛔ 不为了句子好看去改判据。
    顺手把它的失败诊断从「只印最后 3 行」改成「印所有带 ❌ 的行」：原来那 3 行常常是**别的**检查的 OK 行，
    本轮就为这一点多花了一轮才发现真实原因。
    ⑲ 下一件（也是 R3-07b 转 ✅ 的最后一块证据）：**全量跑一遍** `_reverse_verify_all.py`（实测 ≈2.7 小时，要分批），
    拿「143 份里没有任何一份把工作区改坏」的机器证明 —— 判据就是 runner 每份跑完的那次逐字节比对。
    · 当前 **L3 = 0（上限 0）**；**L2 = 142/143**（剩 1 份＝例外）。
    ⑳ ⭐ **最后一块证据：全量跑一遍（2026-09-26 第一次真做）**——按域跑完 **142/142 份**：
    `ai` 34/34 达标、`qa` 104 份（93 达标）、`fuzz` 2、`deploy` 1、`baseline` 1；
    ⛔ **漂移告警 0 条**（runner 每跑完一份就逐字节比对现场与快照，「现场多了这些文件」也是 0），跑完 `git status` **干净**。
    指南 §二十一 ② 那句话现在是**机器证明**的：142 份里没有任何一份把工作区改坏 —— 且这一层**不依赖任何脚本的自述**
    （它自己写的那句核对可能盯错一头，本轮修过两次这种）。反例对照：临时探针故意写脏一个文件且 `exit 0` →
    runner 当场点名 + 按快照写回 + 计为不达标（验完已删）。

- ❌ **反向验证的注入锚点不许腐烂**（R3-07b2，**全量跑一遍才暴露出来**）—— 复现：`python _tools/ai/_reverse_verify_all.py --only qa/`
  上面那次全量跑的另一半收获：`qa` 域 **11 份脚本现在是恒真的**（注入没生效或打不动判据 ⇒ 那条红线没有东西在守它）。
  名单（下一轮逐份补锚点/期望词）：`ai_declarative_crud`（2 条 `[SKIP]`）、`audit_coverage`（1 条打不动判据）、
  `category_roster`、`contact_binding`、`import_purity`、`inline_role_gates`、`list_order`、`money_contract`、
  `permission_points`、`r3_constraints`、`round17`。
  ⛔ 这一条**不是**「还原」问题（漂移 0 条已经证明），是「**注入还在不在**」问题 —— 两件事分开记，谁也不许替谁背书。
  ⏳ 进度（2026-09-26）：**已修 3 份** —— ① `import_purity`：`try:` + `if not inspect(engine).has_table(VERSION_TABLE):`
  这一对在 `_runner.py` 里出现**两次**（`applied_versions()` 与 `schema_ready()`），要求恰好一次的注入恒 SKIP ⇒
  锚点往下多带一行（`schema_ready` 独有的那句中文报错）就唯一了 → **7/7**；② `ai_declarative_crud`：两条锚点随实现
  从 `AiWriteService.kt` 搬进了 `AiWriteDataSource.kt` ⇒ **只改目标文件、锚点原文一字不改** → **5/5**；
  ③ `contact_binding`：同上（⑩ 那条搬到 `AiWriteDataSource.kt`）→ **18/18**。**还剩 8 份**（`audit_coverage` /
  `category_roster` / `inline_role_gates`（3 条）/ `list_order` / `money_contract` / `permission_points` /
  `r3_constraints` / `round17`）—— 其中 `list_order` / `money_contract` 的失败原因还没看清（日志里没有 `[SKIP]`/`[MISS]` 行）。
  ⏳ 再修 2 份（累计 **5/11**）：④ `money_contract`：它的 `Sandbox.apply()` 里**粘着同一段跑不起来的兜底代码**
  （引用未定义的 `old`）—— 第一次注入就 `NameError` 崩掉，表现只是「这份反向验证不达标」，实际**一条注入都没做**；
  与 `_reverse_verify_live_doc_counts.py` 里那段是同一份复制粘贴的残留，已删 → **5/5**。
  ⑤ `list_order`：⑨ 号注入报「红线居然还是绿的」—— 查下去发现 VM 里 `pickedAddressId = null` + `pickedLocationId = null`
  这一对出现**两次**（预设单回填 / 地图选点），而**判据只要求「存在」**⇒ 删掉地图那一处它照样绿。
  ⛔ 这是「**判据比它自己的名字弱**」——本仓库反复栽的那一类。处置：反向验证改成带上下文的 `re:` 正则锚点
  （只命中 `applyPicked()` 里那一对，applier 本来就支持 `re:` 前缀），判据同步收紧成「必须在 `applyPicked()` 里」→
  判据 55 项仍全过、反向验证 13/13 全红。**还剩 6 份**。
  · 另外核一件事：**没有任何一份**在代码里真的执行 `git checkout`（⛔ 用 AST 看**调用实参**，
    不用正则搜文本 —— 反向验证脚本自己就把 `["git","checkout",…]` 当字符串数据写着，
    正则会把它们全判红，那是本仓库栽过的「判据被文字误伤」）。
  · 例外 2 条，都写了理由与退出条件：`_reverse_verify_all.py`（批处理调度器，自己不注入）、
    `_reverse_verify_root_clean.py`（它注入的是临时探针文件、自己删掉，不还原源码）。
  反向验证 6/6（真跑 git checkout / 没有还原 / 少比对 / 例外没理由 / 扫描下限 / L2 棘轮）。
  ⚠️ 它的 ③ 号注入原来把 `MIN_L2 = 70` **写死在锚点里** —— 2026-09-26 棘轮一抬到 88，那条当场变 `[SKIP]`
  （SKIP 在本仓库**计为不成立**）。已改成**从判据源码现取**当前值（`_live_anchor`），以后抬棘轮不会再撞。
  ⚠️ 剩下的 37 份**不是一轮能补完的**（每份形状不同，要逐份改 + 逐份跑），棘轮会盯着它只增不减。
  ⚠️ 补法有两档：① 有统一锚点（`finally:` + `path.write_text(original, …)`）的直接插一行核对（已用掉 12 份）；
     ② 其余的形状各不相同（多文件、`shutil.copy2`、快照字典…），要逐份看代码再改。
- ✅ **报告事实核对**（R3-07c）—— 复现：`python _tools/qa/_check_report_facts.py`
  台账里每条 ✅ 后面那句 `复现：` 现在**真的会被跑一遍**（去重后 23 条命令：19 条真跑 / 4 条跳过，8 路并发、
  每条 180 秒超时）：非零退出就是「文档说了假话」。六组判据：✅ 条数下限（扫描坏了先喊）／每条 ✅ 必须带命令／
  命令必须退出 0／真跑条数下限（判据空转就红）／SKIP 表**不许有化石**且每条要写「什么时候删掉这一条」／
  ⭐ 行里写的**期望值**（`→ ` + 反引号）必须在命令**现在的输出**里，而**跳过的那几条不许写期望值**。
  写它当天就抓到两批真缺陷：① 三条过期 ✅（`_migration_tests.py --fresh/--old/--concurrent` 因为脚本里
  `LATEST = 7` 写死、迁移 008 之后必失败）；② 本文件里两个**没人核的数字**（`1015 passed` / `114/114` ——
  两条命令都在 SKIP 表里，谁也跑不出那个数）→ 已改成「以命令自己打印的为准」。
  反向验证 **9/9**（7 条注入各自报红：命令必失败 / 指向不存在的脚本 / 抹掉某条的复现命令 / 台账被掏空 /
  SKIP 变化石 / 给跳过的命令写期望值 / 写一个假的期望值；+ 负面对照（重复的命令去重后仍算通过）
  + 还原后逐字节一致）。
  ⛔ **写它的当天就踩了自己的雷**（2026-09-26 实测）：台账本条 ✅ 的复现命令**就是它自己** ⇒
  「检查跑检查」→ 40 分钟里长出 **400 多个 python 进程**（每一代隔 7~8 秒生一个，`_check_all.py` 被拖到 171 秒）。
  修法三层，缺一层都会复发：① **环境变量守卫**（子命令带 `SORDERS_REPORT_FACTS_DEPTH`，下一代一启动就报错退出）；
  ② 自己那条命令进 SKIP 表（写明为什么 + 什么时候删掉这一条）；③ 一条**结构性判据** ——
  台账里凡是要跑起本脚本的命令，必须在 SKIP 表里显式登记，否则红。
  教训与「永远红的检查＝没有检查」同源：**判据的爆炸半径，本身也是判据要管的东西**。
  ⛔ 它证不了什么：只证「那条命令现在退出 0」+「写的期望值现在还打得出」，
  **不证**「那句中文描述得准确」——话有没有说过头，机器判不了，那是人读报告时要盯的。
  ⚠️ 期望值那条判据**当前核了 0 条**（台账里没人写期望值）：它有没有牙由反向验证的 ⑥⑦⑧ 三条证，
  ⛔ 别把它当成「已经在替你核数」。
- ❌ 依赖可复现性决策（开区间 vs pin，三处版本是否一致）—— 产物已是 `docs/DEPENDENCY_DECISION.md`，**决策待用户拍板**
  **前半（证据 + 判据）已就位**：① 三处版本摆齐（声明 / 本机 / CI；**生产那一格空着** —— 要 R3-05 上机器 `pip freeze`）；
  ② 机器判据 `python _tools/qa/_check_dep_declaration.py`（24 条声明逐条对**本机实际装的版本**，不成立的必须
  登记 + 写「什么时候删掉这一条」+ 棘轮只减不增（=1）+ 防化石），反向验证 6/6；
  ③ 实测抓到一处真不一致：`cryptography` 声明 `>=42,<44`、本机是 **48.0.0**（高 5 个大版本），
  上限来自 `f20b93a`「初始提交 v0.01」（2026-04-09），仓库里找不到理由 —— 已登记为例外，⛔ 不自己改。
  **要用户拍板的三件事**写在 `docs/DEPENDENCY_DECISION.md` §五（往哪边对齐 / 要不要 lock / 允不允许上生产只读 `pip freeze`）。

- ✅ **活文档不许写「会变的数字」：耗时也归这一族**（R3-07e）—— 复现：`python _tools/qa/_check_live_doc_counts.py --check`
  `AGENTS.md`（每个新会话都会读的那一页）写着「约一分钟」，实测 **171 秒**；而那个数只会随脚本数继续涨
  → 数字删掉，改由 `_check_all.py` **自己打**（「跑完 N 个检查，总耗时 X 秒。」）；
  判据新增一族：**凡提到 `_check_all.py` 的行里不许出现耗时数字**（写的时候是真的、之后必然过期）。
  反向验证 **11/11**（9 条注入各自报红，含这一族；+ 负面对照 + 还原后逐字节一致）。
  ⛔ 顺手抓到两件真缺陷：① 台账里两个**没人核的数字**（`1015 passed` / `114/114`，两条命令都在 SKIP 表里，
  谁也跑不出那个数）→ 改成「以命令自己打印的为准」；
  ② `_reverse_verify_live_doc_counts.py` 的沙箱里粘着一段**必然 `NameError`** 的兜底代码
  （引用未定义的 `old`、还在 `@staticmethod` 里用 `self`）—— 也就是说**这份反向验证从第二轮那次编辑起就没跑通过**，
  而外面没有任何东西发现它（形状是对的：`_check_reverse_verify_restore.py` 只判「有没有按字节还原」，
  不判「跑不跑得起来」）。已删掉那段，并把这个坑写进脚本自己的说明。

---

## 维护规则

1. 每完成一条退出条件，把 `❌` 换成对应符号并补上**产生它的命令**；
2. ⛔ **没跑过命令不许写 ✅** —— 这条由 `_check_r3_constraints.py` 的 `exit_condition_ledger` 探针核形状，
   由人核事实（形状对不代表事实对，所以每条都必须能跑）；
3. 里程碑做完时，把「最终验收矩阵」对应行按**实际证明到的层次**改符号，⛔ 不许只改代码那一格。
4. 行里想写**会变的数字**时只有两条路：要么写成 `→ ` + 反引号包住的**期望值**（`_check_report_facts.py`
   会拿它去命令的输出里找，找不到就红），要么干脆别写、改成「以它自己打印的为准」。
   ⛔ **跳过的命令不许写期望值** —— 没人跑它，那个数就没人数（2026-09-26 实测抓到两处）。

