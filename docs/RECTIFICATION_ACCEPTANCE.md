# 整改验收（按报告章节逐条对账）

> **本文件由 `_tools/qa/_gen_acceptance.py` 生成，不要手改**（报告 §13：会变化的数字一律不手写）。
> 重新生成： `python _tools/qa/_gen_acceptance.py --full --out docs/RECTIFICATION_ACCEPTANCE.md`

生成于 2026-09-25 01:34 UTC ｜ 分支 p ｜ 提交 c7d9516 ｜ 模式：完整（含全量静态检查与后端用例）

⚠️ 本页是**快照**：生成之后仓库还会往前走。**数字以重新跑出来的为准**，别拿这一页当当前值（这正是报告 §13 说的「文档系统要变成事实生成系统」）。

这张表回答一个问题：**报告的每一条建议，落在哪个文件、用哪条命令能重新证明它还在。**
最后一列是**命令自己打印出来的那一行**，不是人写的。

| 阶段 | 报告章节 | 做了什么 | 复现命令 | 命令自己打印的结论 |
| --- | --- | --- | --- | --- |
| 0 | §2 真实世界基线 | 基线由脚本采集（before/ 冻结、after/ 可重采） | ✅ `python _tools/baseline/_check_baseline.py` | ✅ 全部通过（改造前的快照还在，且没被改过） |
| 1 | §3 备份 / 恢复演练 | 脚本化备份 + 默认不碰生产库的恢复 + 每周演练 | ✅ `python _tools/backup/_check_backup.py --check` | ✅ 全部通过（含恢复演练的隔离与门禁） |
| 2 | §4 Schema 迁移版本化 | 版本表 + 每次结构变更一条迁移（跑过记进 schema_versions） | ✅ `python -m app.migrations status` | 当前版本：3 |
| 2 | §4 迁移判据 | 命名 / 版本号唯一递增 / 接线 / 失败不记账 / 漂移不抛异常 | ✅ `python _tools/qa/_check_migrations.py` | ✅ 判据条数 48 ≥ 18 |
| 3 | §5 CI 正式接管检查体系 | 三层闸门（快闸 / 常闸 / 夜闸）+ 分支口径 p、new | ✅ `python _tools/qa/_check_ci_workflows.py` | ✅ 全部通过（分支口径 / 路径 / 层序 / 危险 job 的时机 / gradle 任务名都对得上） |
| 4 | §6 API 层纯搬迁 | orders.py / reports.py 拆开，URL 与出参一个字不变 | ✅ `python _tools/qa/_check_endpoint_index_fresh.py` | ✅ 端点索引与源码一致（不是过期地图） |
| 5 | §7 钱：从文件冻结升级为领域契约 | 钱只有一处实现，消费方一律从契约 import | ✅ `python _tools/qa/_check_money_contract.py` | ✅ 全部通过（每个钱数只有一处实现，消费方真的在用它） |
| 5 | §8 状态机唯一写入口 | 状态迁移只在 order_flow；写前取锁 + 原子占位 | ✅ `python _tools/qa/_check_status_gate_locking.py` | ✅ 全部 55 项通过。 |
| 5 | §9 权限模型真的在执行 | 26 个权限点逐个有交代（在用 / 有理由） | ✅ `python _tools/qa/_check_permission_points.py` | ✅ 26 个权限点都有交代（26 个在用、0 个有书面理由）。 |
| 6 | §10 事务发件箱（可靠事件） | 事件与业务同事务；worker 派发 + 重试；生产者不许绕开 | ✅ `python _tools/qa/_check_outbox.py` | ✅ 全部通过（入队同事务 / 失败可重试 / 表结构同源 / 边界可见） |
| 7 | §11 客户端大文件按职责拆 | AiWriteService 的三块职责＝三个文件（判据读并集，搬文件对判据不可见） | ✅ `python _tools/ai/_check_ai_guardrails.py --check` | ✅ 全部 1280 项通过。 |
| 8 | §12 AI 能力目录与后端权限同源 | 读能力由后端权限点**生成**，不手写（对账探针在 CI） | ✅ `python _tools/ai/_check_role_parity.py` | ✅ 全部 17 项通过：AI 的能力 = 角色的能力（不越权，也不缺）。 |
| 8 | §13 文档事实源自动化 | 会变的数字不手写：生成物 + 判据守住 | ✅ `python _tools/qa/_check_live_doc_counts.py` | ✅ 全部通过（活文档里手写的数字都与现状一致，或已被指向生成物） |
| 10 | §15 可观测性 | Request ID 一条链路 / 业务指标现算 / 外部监控四项（跑得到生产） | ✅ `python _tools/ops/_check_ops.py` | ✅ 全部通过（只读、阈值一处、退出码分档、该盯的都盯着） |
| - | §18 施工纪律：判据自己也要被验证 | 反向验证的注入原文还找得到（锚点不许腐烂） | ✅ `python _tools/qa/_check_reverse_verify_anchors.py` | ✅ 1127 条注入原文全部还在（90/113 份脚本的注入表都认得出）。 |
| - | §19 Domain + Database invariants | 直接查库：钱 / 库存 / 状态 / 单据自相矛盾吗 | ✅ `python _tools/fuzz/_fuzz_invariants.py --check` | 小结：检查 41 项 / 确认缺陷 0 / 可疑 0 / 信息 5 / 0.8s |
| - | §5 全量静态检查（移交 CI 的那一套） | 清单自己算，一条命令跑完全部静态检查 | ✅ `python _tools/qa/_check_all.py` | ✅ 99/99 个检查全部通过（并且 AGENTS.md 里写了要跑它）。 |
| 9 | §14 后端全量用例 | 重构的等价性靠用例钉住（每一步都跑过） | ✅ `python -m pytest -q` | 1015 passed |

## 还没做的（如实列，附原因与卡在谁那儿）

| 事项 | 现状 | 原因 |
| --- | --- | --- |
| 把这些提交推到 GitHub，让 CI 真的跑那三层闸门 | 本地领先 origin/new | 本机到 GitHub 的链路不通（代理整体失效、22 与 443 都被切断）；国内站点与生产 SSH 正常 |
| Tests (Parallel) 那两个红 job | **真因已复现并修掉**：xdist 默认分发把同一个文件的用例拆到不同 worker，而这些用例共享 per-worker 的库 → 加 --dist loadfile（本机 `-n auto` 2 failed、加后 1015 passed），并配了判据第 12 条 + 反向验证第 ⑦ 条 | 还差**一次 push**：CI 上跑一遍才算数 |
| 安卓单测从夜闸挪进 PR 闸 | 仍在夜闸（机器判据已把「跑得起来」的四件事钉住） | 需要 CI 能跑，才能验证「挪进去不会让每个 PR 都红」 |
| 把整改后的代码发到生产 | 生产仍跑旧代码（外部监控里如实写着「还没有 outbox_events 表」「迁移版本 —」） | **等你拍板**；上线时启动会自动跑 002/003 两条迁移，迁移失败会拒绝启动（逃生门 SORDERS_SKIP_MIGRATIONS=1） |

## 需要环境才能跑的两条（不摆进上表，免得把「本机没数据」记成失败）

- _tools/ai/_probe_read_roles.py ：要一个**跑着的后端**（CI 的 read-roles-probe job 就是干这个的）。
- _tools/fuzz/_fuzz_invariants.py ：要**本机开发库**；没有库时它会响亮地跳过（不会假装通过）。

---

报告 §20 结尾的提醒也适用于这一页：**不要再加检查器，要改架构**。
所以这里没有新增任何判据 —— 它只是把**已有的那些**按报告章节摆成一张可复现的对照表。
