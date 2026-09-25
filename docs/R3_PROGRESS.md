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
- ✅ 退出条件 9/10：现有 1015 tests 全绿 —— 复现：`cd backend; python -m pytest -q` → `1015 passed`
- ✅ 退出条件 10/10：全量静态检查全绿 —— 复现：`python _tools/qa/_check_all.py` → `114/114`

**三层完成度**：Code Ready ✅ ｜ CI Proven ❌（还没推）｜ Runtime Proven ✅（本机真进程真库；**生产**仍未验证）

## R3-02 Capability → UI / Audit

- ❌ 26/26 capabilities 有执行点 —— 复现：`python _tools/qa/_check_capability_registry.py`
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

- ❌ 两个实例同时运行 —— 复现：`python _tools/ops/_dual_instance.py --up`
- ❌ migration 只执行一次 —— 复现：`python _tools/ops/_dual_instance.py --case migration`
- ❌ scheduler 只执行一次 —— 复现：`python _tools/ops/_dual_instance.py --case scheduler`
- ❌ upload 一致（A 传 B 查得到）—— 复现：`python _tools/ops/_dual_instance.py --case upload`
- ❌ Socket.IO 跨实例推送正常 —— 复现：`python _tools/ops/_dual_instance.py --case socket`
- ❌ 杀掉 A 之后 B 继续服务 —— 复现：`python _tools/ops/_dual_instance.py --case kill-a`
- ❌ 上传资产的运行模型已决策（共享盘 or 对象存储）—— 复现：`docs/R3_DECISIONS.md`
- ❌ nginx upstream + 失败摘除 —— 复现：`docs/R3_DECISIONS.md`

## R3-04 Observability

- ✅ request_id 贯穿（第二轮已完成）—— 复现：`python _tools/qa/_check_traceability.py`
- ❌ command_id 与 request_id / event_id 分成三个概念 —— 复现：`python _tools/qa/_check_traceability.py`
- ❌ 业务指标（订单/命令/事件/通知/迁移/调度）—— 复现：`python _tools/ops/_check_ops.py`
- ❌ 全链路诊断接口（人可读）—— 复现：`python _tools/ops/_trace_order.py --help`
- ❌ 没有引入大型观测平台 —— 复现：`python _tools/qa/_check_r3_constraints.py`

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

- ✅ 判据不许静默空转（本轮 `_check_r3_constraints.py` 自带反空转下限）—— 复现：`python _tools/qa/_check_r3_constraints.py`
- ❌ 反向验证必须完整还原（机器证明 before == after）—— 复现：`python _tools/qa/_reverse_verify_r3_constraints.py`
- ❌ 生成物新鲜度（source hash / generated_at / source commit）—— 复现：`python _tools/qa/_check_generated_freshness.py`
- ❌ 报告事实核对 —— 复现：`python _tools/qa/_check_report_facts.py`
- ❌ 依赖可复现性决策（开区间 vs pin，三处版本是否一致）—— 复现：`docs/DEPENDENCY_DECISION.md`

---

## 维护规则

1. 每完成一条退出条件，把 `❌` 换成对应符号并补上**产生它的命令**；
2. ⛔ **没跑过命令不许写 ✅** —— 这条由 `_check_r3_constraints.py` 的 `exit_condition_ledger` 探针核形状，
   由人核事实（形状对不代表事实对，所以每条都必须能跑）；
3. 里程碑做完时，把「最终验收矩阵」对应行按**实际证明到的层次**改符号，⛔ 不许只改代码那一格。

