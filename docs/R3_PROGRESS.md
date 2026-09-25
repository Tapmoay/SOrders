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
| Migration | ❌ | ✅ | ❌ | ❌ | ❌ |
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
| Migration 不再有隐式副作用 | ❌（R3-01 待做） | ❌ | ❌ |
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

- ❌ 退出条件 1/10：`import app.database` 不执行 DDL —— 复现：`python _tools/qa/_check_import_purity.py`
- ❌ 退出条件 2/10：application startup 不执行 migration —— 复现：`python _tools/qa/_check_import_purity.py`
- ❌ 退出条件 3/10：migration 有唯一入口 —— 复现：`cd backend; python -m app.migrations status`
- ❌ 退出条件 4/10：migration version 正确 —— 复现：`cd backend; python -m app.migrations status`
- ❌ 退出条件 5/10：空库迁移通过 —— 复现：`python _tools/ops/_migration_tests.py --fresh`
- ❌ 退出条件 6/10：旧库（version 7 → 新版本）迁移通过 —— 复现：`python _tools/ops/_migration_tests.py --old`
- ❌ 退出条件 7/10：双实例并发迁移只执行一次 —— 复现：`python _tools/ops/_migration_tests.py --concurrent`
- ❌ 退出条件 8/10：migration 失败不会启动半残服务 —— 复现：`python _tools/ops/_migration_tests.py --fail-fast`
- ❌ 退出条件 9/10：现有 1015 tests 全绿 —— 复现：`cd backend; python -m pytest -q`
- ❌ 退出条件 10/10：全量静态检查全绿 —— 复现：`python _tools/qa/_check_all.py`

## R3-02 Capability → UI / Audit

- ❌ 26/26 capabilities 有执行点 —— 复现：`python _tools/qa/_check_capability_registry.py`
- ✅ API 使用 Capability（第二轮已完成）—— 复现：`python _tools/qa/_check_capability_registry.py`
- ✅ AI 使用同一 Capability（第二轮已完成，走 `rbac.ROLE_PERMISSIONS`）—— 复现：`python _tools/ai/_check_role_parity.py`
- ❌ UI 不再自行定义角色能力（`android/.../ai/AiWrite.kt` 手抄了 13 项）—— 复现：`python _tools/qa/_check_r3_constraints.py`
- ❌ Audit action 能证明 write capability 的留痕覆盖 —— 复现：`python _tools/qa/_check_audit_coverage.py`
- ❌ 不存在第二份静态 Capability 真相 —— 复现：`python _tools/qa/_check_r3_constraints.py`

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

