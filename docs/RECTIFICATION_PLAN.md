# 架构整改执行表（RECTIFICATION_PLAN）

> 来源：[ARCHITECTURE_RECTIFICATION.md](ARCHITECTURE_RECTIFICATION.md)（评审报告原文存档）。
> 现状数据：[BASELINE.md](BASELINE.md)（机器生成，含与报告成文时的逐项对照）。
>
> **这一页只回答"做到哪一步了、证据在哪"**。状态只有四种：
> `未开始` / `进行中` / `已完成（带提交号与证据）` / `不做（带理由）`。

## 0. 总方针（报告 §1）

> **不要推倒重写。** 目标不是"换成更高级的技术"，而是把现在靠人记、靠脚本查、靠文件冻结
> 维持的安全性，逐步变成**架构本身天然保证的安全性**。

顺序（报告强调"这个顺序非常重要"）：

```text
阶段 0 基线  →  阶段 1 备份/恢复  →  阶段 2 迁移版本化  →  阶段 3 CI 接管
   →  阶段 4 API 层纯搬迁  →  阶段 5 状态/钱/权限硬边界  →  阶段 6 可靠事件（Outbox）
   →  阶段 7 客户端/AI/文档一致性  →  阶段 8 可观测性  →  阶段 9 多实例/HA（最后）
```

⛔ 报告明确点名的**不要做**：现在重写后端 / 上微服务 / 换数据库 / 上 Kafka / 上 Kubernetes。
理由写在 §1：那会同时改变几十个变量，而这里有 227 个端点、45 张表、41 个 service 文件。

## 1. 执行表

| 阶段 | 报告章节 | 做什么 | 改业务逻辑 | 状态 | 证据 |
|---|---|---|---|---|---|
| 0 | §2 | 建立真实基线（本地 + 生产，只读采集） | 否 | **已完成** | `docs/BASELINE.md`、`_tools/baseline/_capture_baseline.py`、快照 `_tools/baseline/before/2026-09-24/baseline.json` |
| 0 | §2 | 确认工作区里"另一个 AI 会话的未提交改动"归属 | 否 | **已完成（结论：不存在）** | 见 §3 第 1 条 |
| 1 | §3 | 脚本化备份（库 / 上传 / 清单 / 校验 / 保留期） | 否 | **已完成** | `_tools/backup/_backup.sh`、`_install.py` |
| 1 | §3 | 恢复路径脚本化 + 生产库门禁 | 否 | **已完成** | `_tools/backup/_restore.sh`（默认只肯写 `sorders_drill_*`） |
| 1 | §3 | **真的做一次恢复演练**（恢复→启动→打接口→验钱/状态） | 否 | **已完成** | 2026-09-24 `DRILL=ok`：行数逐项核对一致 ｜ 25 条库内不变式 0 违规 ｜ `/health` 200 + openapi 160 路径 ｜ 4 个带鉴权只读端点全 200 ｜ 收尾自清（`_tools/backup/_drill.sh`、`_drill_local.py`） |
| 1 | §3 | 定时任务（日报/周报/每周演练） | 否 | **已完成** | `/etc/cron.d/sorders-backup` |
| 1 | §20 | 版本号统一（原来 4 处、3 个值） | 否 | **已完成** | 后端 `config.py::_repo_version()` 改为读仓库根 `VERSION`（不再硬编码 0.2.0）+ `frontend/package.json` 对齐 0.2.4 + 基线采集器学会认新写法。证据：四处同值（`VERSION` / `package.json` / `android versionName` / `backend` 全 0.2.4），本机 `/health` 由 `0.2.0` 变为 **`0.2.4`**；94/94 检查 + 983 用例全绿 |
| 1 | §20 | nginx exports deny | 否 | 未开始 | — |
| 1 | §20 | `_check_all` 加超时 | 否 | **已完成** | `--timeout`（默认 300s；0=不限）；超时按**失败**记账并**继续跑后面的人**（一次跑完看全貌）。实测：`--timeout 1` 对那个 9 秒的检查 → 报「超时（>1s）——这个检查挂住了…」并 exit 1；默认参数下 94/94 全绿 |
| 1 | §20 | `AI_WORK_CLAIM` 归档（6000+ 行） | 否 | 未开始 | — |
| 1 | §15 | 证书 / uptime / disk 最小监控 | 否 | **最小版已可跑**（cron 待挂） | `_tools/ops/_health_check.py`（只读）：服务/健康检查、**证书剩余天数**、磁盘、**最近一次备份的年龄**；退出码 `0/1/2`。实测输出：`sorders.top` 两张证书 **剩余 -75 天**（报告点名的那件事）、IP 证书 1089 天、磁盘 29%、**最近备份 1.6 小时前**（顺带证明第 1 轮的 cron 真的在跑）。待做：装到服务器 + `0 9,21 * * *` 本地模式 cron |
| 2 | §4 | Schema 迁移版本表（`schema_versions`） | 否 | **已完成** | `backend/app/migrations/`（运行器 + 基线 + CLI）；`python -m app.migrations status`；判据 `_tools/qa/_check_migrations.py`（39 项）+ 反向验证 15/15 |
| 2 | §4 | 新变更走 `migrations/`（bootstrap 只管运行时自愈） | 否 | **已完成（机制就位）** | 既有 1600 行幂等 DDL **刻意不搬**（一次只动一个维度）；分工写进 `backend/app/migrations/README.md` |
| 2 | §4 | 真 MySQL 上验一次（方言相关的那版建表语句） | 否 | **已完成** | `_drill_local.py --verify-migrations`：在**恢复出来的生产库**上跑仓库里这份迁移（见 §3.4） |
| 3 | §5 | CI 三层闸门（快闸 / 常闸 / 夜闸） | 否 | **已完成** | `.github/workflows/gate.yml`；分支口径补 `p`/`new`（原来只挂 main/develop，等于从没在开发分支上跑过） |
| 3 | §5 | 安卓单测进 PR 闸 | 否 | **进行中** | 现在在夜闸（仓库自带的 gradle 在 gitignore 的 `_agent/` 里，runner 要现装 8.9）；首次跑通后挪进 PR 闸 |
| 4 | §6 | `orders.py` 纯搬迁（URL/入参/出参/权限/状态机全不变） | 否 | **已完成** | **2056 → 33 行**（只剩装配说明 + 空 router）；25 个端点分在 7 个模块（query/assignment/delivery/payment/media/lifecycle/return）+ 共用助手在 orders_common；证据：每一刀都用 `_tools/qa/_api_contract_snapshot.py --diff` 证明**契约零差异**（OpenAPI 全文 / 路由表逐条 / 遮蔽关系 0 对），94/94 检查 + 983 用例全绿 |
| 4 | §6 | `reports.py` 聚合下沉到 service | 否 | **第 ① 步已完成（94/94 绿）；② 下沉、③ 锚点逐个重指待做**。三步走：① 判据读取口径（✅ 已做：`_airepo.reports_source()`（缺文件就跳过，所以先改口径也不会红）+ 5 个读点全改并集：`_check_ai_guardrails`×3 / `_check_cost_basis` / `_check_order_return` / `_check_report_window` / `_check_single_source`）；② 再下沉（此时判据已能看两份）；③ **逐个**反向验证脚本重指锚点（一次一个、改完立刻跑 —— 上一轮批量重指把 8 条改错、13 条失效）：下沉本身**契约零差异**（`after-reports-sink` 快照），但 5 条判据是**按文件文本**读 `api/v1/reports.py` 找聚合锚点的（`_check_ai_guardrails` / `_check_cost_basis` / `_check_order_return` / `_check_report_window` / `_check_single_source`）—— 下沉前要先给它们加"读两份（api + service）"的口径，与 orders 那套 `orders_api_source` 同形 |

<!-- 下沉第 ③ 步的**精确清单**（本轮实测出来的，下一轮照着做即可） -->
> **第 ③ 步的精确定位（2026-09-24 第 4 次试做时实测出来的）**：会搬到 service 那一份的注入锚点共 **22 条**，
> 按脚本列出行号（锚点行号 → 所在用例的目标表达式要改成 `REPORTS_SVC`）：
> `_reverse_verify_cost_basis.py` 35 / 88；`_reverse_verify_report_guards.py` 33 / 57；
> `_reverse_verify_report_window.py` 162 / 167 / 175 / 189 / 194 / 199 / 204 / 240（**已验证可修**：重指后 29/29 通过）；
> `_reverse_verify_round19.py` 1 处（**已验证可修**）；
> `_reverse_verify_round12.py` 73 / 175 / 227 / 237 / 252 / 265；`_reverse_verify_single_source.py` 48 / 57 / 66 / 98。
> ⚠️ 后两份的用例表是 **`MULTI`（列表套列表）** 形状，`round12`/`single_source` 的锚点行既不是 `Name` 元素、
> 也不在普通 CASES 里 —— 要按**行号**直接改，别再写通用扫描器（本轮两次通用扫描都在它们身上失效）。
> ⚠️ 常量路径别用推导出来的相对前缀：`REPORTS = ROOT / "backend/app/api/v1/reports.py"` 对应的 service 是
> `ROOT / "backend/app/services/reports_service.py"`（我第一次写成 `ROOT / "services/…"` → 三个脚本当场 FileNotFoundError）。
| 5 | §7 | 状态机唯一写入口（Command → OrderFlow） | 局部 | 未开始 | — |
| 5 | §8 | 钱：从"文件冻结"升级为显式契约 | 局部 | 未开始 | — |
| 5 | §9 | 权限模型收敛（26 个权限点 / 5 个无引用） | 局部 | 未开始 | — |
| 6 | §10 | Outbox（事务发件箱）替代"background task 直接推" | 局部 | 未开始 | — |
| 7 | §11 | Android 大文件按职责拆（不是按行数拆） | 少量 | 未开始 | — |
| 7 | §12 | AI 能力目录与后端权限**同源**（`_probe_read_roles` 进 CI） | 否 | 未开始 | — |
| 7 | §13 | 文档事实源自动化（会变的数字一律生成） | 否 | **已完成（第一块）** | `docs/BASELINE.md` 由脚本生成 |
| 7 | §14 | Android 集成测试（登录 → 导航 → 下单） | 否 | 未开始 | — |
| 7 | §14 | 前端 H5：正式"继续维护"或"正式归档"（二选一） | — | **待拍板** | 见 §4 |
| 8 | §15 | Request ID / 业务指标 / 外部监控 | 否 | **① 已完成；③ 最小版已可跑；② 待做** | ① `core/request_id.py`（纯 ASGI 中间件 + ContextVar + 日志 `[rid=…]` + `X-Request-ID` 响应头），真机实测响应头有值、5 条用例、988 用例绿；③ `_tools/ops/_health_check.py`；② 业务指标（orders_created / push_success / AI_calls…）未做 |
| 9 | §16 | 多实例 / HA | 架构级 | **不做（现在）** | 报告 §16：先有迁移版本化与可靠事件，否则三个实例一起跑 DDL 是新的灾难 |

## 2. 施工纪律（报告 §18，落到本仓库的具体命令）

| 规则 | 在本仓库怎么执行 |
|---|---|
| 一次只动一个维度 | 改完 → `python _tools/qa/_check_all.py` 全绿 → 单独 commit（用户 2026-09-23 明确要求每轮提交） |
| 核心区不边重构边重设计 | 动 `_tools/qa/_core_files.txt` 里的文件前，先在 `docs/AI_WORK_CLAIM.md` 写一行 `核心改动：<路径> —— 为什么必须动核心：<一句话>`；`_check_core_freeze.py` 会查 |
| 重构要有等价性验证 | 拆 `orders.py` 时：端点集合 / 入参 / 出参 / 权限四处逐条对齐（`_check_endpoint_index_fresh.py` + `_check_client_contract.py` + `_check_permission_points.py`） |
| 先迁移，再删除旧路径 | 新路径与旧路径并存 → 对账 → 再删；不"重写→删除→祈祷" |
| 工具必须自己可验证 | 新写的检查脚本加 `--check` 就自动进 `_check_all.py`；配反向验证 |

## 3. 阶段 0 / 1 的结论（本次做完的部分）

### 1. 工作区里"另一个会话的未提交改动"——**已经不存在了**

报告说工作区有两个未提交文件。实测（`git status` + `git hash-object` 逐一比对）：

- 唯一显示为 ` M` 的 `DispatcherLedgerViewModel.kt`，**工作区哈希与 HEAD 完全相同**
  （`4e5159f3…` == `4e5159f3…`）—— 属于本仓库已知的一类假阳性：
  注入/反向验证脚本把文件原样写回，只换了 mtime，于是 `git status` 报 ` M` 但 `git diff` 一行都没有。
  判据是哈希，修法是 `git add` 刷新索引（**不是** `git checkout --`）。
- 其余条目都是本次整改自己新增的文件。

结论：**可以开始结构性改造，不存在"两个会话混合结果"的风险**。

### 2. 基线的六条机器判定（`docs/BASELINE.md` §4）

| 类别 | 事实 | 处置 |
|---|---|---|
| 版本漂移 | `VERSION`=0.2.4 ｜ `frontend/package.json`=0.2.0 ｜ `config.py:app_version`=0.2.0 ｜ 生产 `/health`=0.2.0（旧代码） | 阶段 1（报告 §20 第 ⑧ 项） |
| 结构漂移 | 模型声明 45 张表，生产库 44 张：`unit_conversions` 只在模型里 | 根因＝**生产代码落后**（生产 HEAD `648fbf81`，本地 `020d35e8`，openapi 路径 160 vs 227）。表由 `schema_bootstrap` 在部署时建，属于"该发版了"而不是"表丢了" |
| 证书 | 域名证书 `sorders.top` 已过期 75 天（App 走的是 IP 证书，那条还在有效期） | 阶段 1 监控项；域名未备案，续期前不可用 |
| 备份 | 生产机上脚本化备份产物 = 0 | **本轮已消掉**：见下 |
| 代码漂移 | 生产在跑的代码 ≠ 本地工作区 | 需要一次发布（不在本轮范围） |
| 工作区 | 未提交改动 | 见上面第 1 条 |

### 3. 备份 / 恢复 / 演练（本轮的核心交付）

三条命令、脚本在 `_tools/backup/`（口径与现场手册见该目录的 `README.md`）：

```bash
python _tools/backup/_install.py                     # 装到生产机 + 挂定时任务
python _tools/backup/_pre_release.py --note "…"      # 发布前一条命令
python _tools/backup/_drill_local.py                 # 恢复演练
```

**第一次真跑就抓到两个只有真跑才会暴露的问题**（都留档在脚本注释里）：

1. `dirs=$(find …)` 在目录不存在时返回非零 → 在 `set -e` 下**把一次已经成功的备份判成失败**，
   `trap` 再给目录打上 `.FAILED`，于是那份完好的备份反而拒绝被恢复。修法：`|| true` + 先 `mkdir -p`。
2. `urlparse` **不做**百分号解码：口令里带 `@ : / %` 时 `MYSQL_PWD` 拿到的是 `p%40ss` 形态 →
   `Access denied`，现场极易被误判成"口令被改了"。修法：`urllib.parse.unquote`。

## 4. 待你拍板的两件事

1. **前端 H5 的定位**（报告 §14 明确留给产品决定）：现有 `frontend/` 是继续维护
   （那就要纳入 CI + 最小测试）还是正式归档（从"活系统"身份剥离）？
   现在是第三种状态 —— 旧系统，但看起来像新系统（`package.json` 里 version 还是 0.2.0）。
2. **要不要现在发布一次**：生产代码落后本地 88 个提交、openapi 路径 160 vs 227，
   域名证书已过期 75 天。备份系统已经就位（发布前的退路有了），但发布本身不在本轮范围。

## 5. 这一页怎么保持新鲜

- 状态列**只在改动落地并提交后**才改（改状态要带提交号）；
- `docs/BASELINE.md` 是生成的，不要手改；数字过期就重跑采集器；
- 新增检查脚本只要加一个 `--check`，就自动进 `_check_all.py` 的必跑组（清单自己算，不手写）。

