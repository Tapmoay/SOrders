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
| 0 | §2 | 建立真实基线（本地 + 生产，只读采集） | 否 | **已完成** | `docs/BASELINE.md`、`_tools/baseline/_capture_baseline.py`、**改造前**快照 `_tools/baseline/before/2026-09-24/baseline.json` |
| 0 | §2 | **`before/` 快照冻结判据**（重采不许把「改造前」覆盖掉） | 否 | **已完成** | `_tools/baseline/_check_baseline.py`（16 条，进 `_check_all.py` 必跑组，总数 94 → 95）。判据：`before/` 那份记录的提交必须是「引入本工具那个提交」的**祖先**。反向验证：把改造后采的数据塞回 `before/` → 当场 2 条红 + exit 1；还原后 17/0。另加 `--label`（`after/` 与 `before/` 分开落盘） |
| 0 | §2 | 确认工作区里"另一个 AI 会话的未提交改动"归属 | 否 | **已完成（结论：不存在）** | 见 §3 第 1 条 |
| 1 | §3 | 脚本化备份（库 / 上传 / 清单 / 校验 / 保留期） | 否 | **已完成** | `_tools/backup/_backup.sh`、`_install.py` |
| 1 | §3 | 恢复路径脚本化 + 生产库门禁 | 否 | **已完成** | `_tools/backup/_restore.sh`（默认只肯写 `sorders_drill_*`） |
| 1 | §3 | **真的做一次恢复演练**（恢复→启动→打接口→验钱/状态） | 否 | **已完成** | 2026-09-24 `DRILL=ok`：行数逐项核对一致 ｜ 25 条库内不变式 0 违规 ｜ `/health` 200 + openapi 160 路径 ｜ 4 个带鉴权只读端点全 200 ｜ 收尾自清（`_tools/backup/_drill.sh`、`_drill_local.py`） |
| 1 | §3 | 定时任务（日报/周报/每周演练） | 否 | **已完成** | `/etc/cron.d/sorders-backup` |
| 1 | §20 | 版本号统一（原来 4 处、3 个值） | 否 | **已完成** | 后端 `config.py::_repo_version()` 改为读仓库根 `VERSION`（不再硬编码 0.2.0）+ `frontend/package.json` 对齐 0.2.4 + 基线采集器学会认新写法。证据：四处同值（`VERSION` / `package.json` / `android versionName` / `backend` 全 0.2.4），本机 `/health` 由 `0.2.0` 变为 **`0.2.4`**；94/94 检查 + 983 用例全绿 |
| 1 | §20 | nginx exports deny | 否 | 未开始 | — |
| 1 | §20 | `_check_all` 加超时 | 否 | **已完成** | `--timeout`（默认 300s；0=不限）；超时按**失败**记账并**继续跑后面的人**（一次跑完看全貌）。实测：`--timeout 1` 对那个 9 秒的检查 → 报「超时（>1s）——这个检查挂住了…」并 exit 1；默认参数下 94/94 全绿 |
| 1 | §20 | `AI_WORK_CLAIM` 归档（6000+ 行） | 否 | **已完成** | 提交 `cace39a`：51 条（2026-09-24 之前的已完成条目）→ `_archive/audit/AI_WORK_CLAIM-已完成-20260924.md`（2449 行），主文件 **6402 → 3967 行**、进行中 96 → 82 条。判据是日期不是「看着旧」；页脚指针写明 `_archive/` 不进 git、真正的底稿在 git 历史（`git show <提交>:docs/AI_WORK_CLAIM.md`） |
| 1 | §15 | 证书 / uptime / disk 最小监控 | 否 | **最小版已可跑**（cron 待挂） | `_tools/ops/_health_check.py`（只读）：服务/健康检查、**证书剩余天数**、磁盘、**最近一次备份的年龄**；退出码 `0/1/2`。实测输出：`sorders.top` 两张证书 **剩余 -75 天**（报告点名的那件事）、IP 证书 1089 天、磁盘 29%、**最近备份 1.6 小时前**（顺带证明第 1 轮的 cron 真的在跑）。待做：装到服务器 + `0 9,21 * * *` 本地模式 cron |
| 2 | §4 | Schema 迁移版本表（`schema_versions`） | 否 | **已完成** | `backend/app/migrations/`（运行器 + 基线 + CLI）；`python -m app.migrations status`；判据 `_tools/qa/_check_migrations.py`（39 项）+ 反向验证 15/15 |
| 2 | §4 | 新变更走 `migrations/`（bootstrap 只管运行时自愈） | 否 | **已完成（机制就位）** | 既有 1600 行幂等 DDL **刻意不搬**（一次只动一个维度）；分工写进 `backend/app/migrations/README.md` |
| 2 | §4 | 真 MySQL 上验一次（方言相关的那版建表语句） | 否 | **已完成** | `_drill_local.py --verify-migrations`：在**恢复出来的生产库**上跑仓库里这份迁移（见 §3.4） |
| 3 | §5 | CI 三层闸门（快闸 / 常闸 / 夜闸） | 否 | **已完成（写出来了）** | `.github/workflows/gate.yml`：快闸（语法 / 端点索引没过期 / 核心区冻结 / 密钥 / 迁移 / 备份）、常闸（全部静态检查 + 后端用例 + 前端构建）、夜闸（反向验证 / 安卓单测）；分支口径补 `p`/`new`（原来只挂 main/develop，等于从没在开发分支上跑过）。⚠️ **但它一次都没真的跑过**：本地领先 `origin` 109 个提交，`gate.yml` 还没推上去 —— 「写出来」与「跑起来」是两件事，状态栏不合并（见 §4 第 3 条） |
| 3 | §5 | **CI workflow 自己的判据**（workflow 是不会在自己身上跑的清单） | 否 | **已完成** | `_tools/qa/_check_ci_workflows.py`（25 条，自动进必跑组：95 → 96）：分支口径（从 git 推当前分支与 upstream，不手写）/ `run:` 里每个仓库内路径与 `python -m` 模块是否存在 / 三层与 `needs` 层序 / 快闸四件事 / PR 闸里真的跑了 `_check_all.py` / **gradle 任务名里的 flavor 必须在 `build.gradle.kts` 里存在** / 注入式 job 必须只在夜闸。反向验证 **5/5**（路径写错、push 去掉 `p`、flavor 改 tablet、把反向验证挪进 PR、快闸删掉密钥自检）—— 每条当场红并给出对应结论；还原后 25/0 |
| 3 | §5 | 安卓单测进 PR 闸 | 否 | **进行中** | 现在在夜闸（仓库自带的 gradle 在 gitignore 的 `_agent/` 里，runner 要现装 8.9）。本轮的机器判据已把「跑得起来」的四件事钉住：`setup-java`、`setup-gradle` 且**版本 pin 成 8.9**、任务名 `:app:testPhoneDebugUnitTest` 里的 flavor `phone` **在 `build.gradle.kts` 里真实存在**、失败也有 `if: always()` 的报告步骤。**唯一还差的是真的跑过一次**（同上：要推） |
| 4 | §6 | `orders.py` 纯搬迁（URL/入参/出参/权限/状态机全不变） | 否 | **已完成** | **2056 → 33 行**（只剩装配说明 + 空 router）；25 个端点分在 7 个模块（query/assignment/delivery/payment/media/lifecycle/return）+ 共用助手在 orders_common；证据：每一刀都用 `_tools/qa/_api_contract_snapshot.py --diff` 证明**契约零差异**（OpenAPI 全文 / 路由表逐条 / 遮蔽关系 0 对），94/94 检查 + 983 用例全绿 |
| 4 | §6 | `reports.py` 聚合下沉到 service | 否 | **三步都已完成（① 判据读并集 / ② 下沉 / ③ 锚点逐个重指）—— 100/100 检查全绿**。三步走：① 判据读取口径（✅ 已做：`_airepo.reports_source()`（缺文件就跳过，所以先改口径也不会红）+ 5 个读点全改并集：`_check_ai_guardrails`×3 / `_check_cost_basis` / `_check_order_return` / `_check_report_window` / `_check_single_source`）；② 再下沉（此时判据已能看两份）；③ **逐个**反向验证脚本重指锚点（一次一个、改完立刻跑 —— 上一轮批量重指把 8 条改错、13 条失效）：下沉本身**契约零差异**（`after-reports-sink` 快照），但 5 条判据是**按文件文本**读 `api/v1/reports.py` 找聚合锚点的（`_check_ai_guardrails` / `_check_cost_basis` / `_check_order_return` / `_check_report_window` / `_check_single_source`）—— 下沉前要先给它们加"读两份（api + service）"的口径，与 orders 那套 `orders_api_source` 同形 |

<!-- 下沉第 ③ 步：**精确清单**（第 4 次试做时实测）＋**执行结果**（2026-09-25 第 21 轮做完） -->
> ✅ **第 ③ 步已完成**：死锚点 **23 条 → 0**（`_check_reverse_verify_anchors.py`：`✅ 1147 条注入原文全部还在`，exit 0），
> 且逐份**真跑一遍**证明注入确实会红：`_reverse_verify_report_window.py` **29/29**、`_reverse_verify_cost_basis.py` **8/8**、
> `_reverse_verify_report_guards.py` §24 的 **5 条**全红、`_reverse_verify_round19.py` **7 条**、
> `_reverse_verify_round12.py` **30 条**（18 个文件逐字节还原）、`_reverse_verify_single_source.py` **19 条**。
> 做法两种：**常量整族重指**（`cost_basis` / `report_guards` / `round19` 各一个常量；`report_window` 拆成两个 ——
> `REPORTS_SVC` 给聚合、`REPORTS_PY` 只留给**仍在 API 层**的导出 `s, e = _span(...)`）与**逐条按标签改路径**（`round12` / `single_source` 的内联表）。
> ⚠️ 两条**不在**上面清单里、只有"逐份真跑"才暴露的：`round12` 的「司机送达不再看隔离区」挂在 `orders.py`，
> 而 `complete_order` 早随阶段 4 搬去 `orders_delivery.py` —— **锚点检查当时说"找得到"**（它在别处找到了同一段原文），
> 只有真跑那份脚本才报 SKIP。结论：**锚点检查 + 逐份真跑，两个都要**。
> ⛔ 两条纪律（第 4 次试做踩出来的，仍然有效）：**常量路径别用推导出来的相对前缀**（service 是
> `ROOT / "backend/app/services/reports_service.py"`；写成 `ROOT / "services/…"` 会让三个脚本当场 FileNotFoundError）；
> **别写通用扫描器**（`round12`/`single_source` 的表是列表套列表，通用扫描在它们身上失败过两次）。
> **精确清单（历史记录，行号以当时为准；已完成）**：会搬到 service 那一份的注入锚点共 **22 条**，
> 按脚本列出行号（锚点行号 → 所在用例的目标表达式要改成 `REPORTS_SVC`）：
> `_reverse_verify_cost_basis.py` 35 / 88；`_reverse_verify_report_guards.py` 33 / 57；
> `_reverse_verify_report_window.py` 162 / 167 / 175 / 189 / 194 / 199 / 204 / 240（**已验证可修**：重指后 29/29 通过）；
> `_reverse_verify_round19.py` 1 处（**已验证可修**）；
> `_reverse_verify_round12.py` 73 / 175 / 227 / 237 / 252 / 265；`_reverse_verify_single_source.py` 48 / 57 / 66 / 98。
> ⚠️ 后两份的用例表是 **`MULTI`（列表套列表）** 形状，`round12`/`single_source` 的锚点行既不是 `Name` 元素、
> 也不在普通 CASES 里 —— 要按**行号**直接改，别再写通用扫描器（本轮两次通用扫描都在它们身上失效）。
> ⚠️ 常量路径别用推导出来的相对前缀：`REPORTS = ROOT / "backend/app/api/v1/reports.py"` 对应的 service 是
> `ROOT / "backend/app/services/reports_service.py"`（我第一次写成 `ROOT / "services/…"` → 三个脚本当场 FileNotFoundError）。
| 5 | §8 | 状态机唯一写入口（Command → OrderFlow） | 局部 | **已完成** | 第 9 轮勘定：订单状态的写入只有 3 处（`order_flow.py` 派单/送达早已是条件 UPDATE，`order_return.py:349` 还是**无条件赋值**）。第 10 轮收口：新增 `order_flow.mark_returned()`（`update(orders).where(id, status==DELIVERED, deleted_at is null).values(status=RETURNED)`，改到 0 行就 rollback + 抛错，与 `cancel_pending`/`recall_dispatch` 同形），`return_order` 只剩一次调用并把 `ValueError` 翻成 `OrderReturnError`（端点只认它 → 400，不会是 500）。⚠️ **勘定本身漏过一次**（诚实记录）：第 9 轮那次盘点只找 `order.status = …` 这种**赋值**写法，于是漏掉了第二种写法 `db.execute(update(Order).values(status=…))` —— 而 `driver-ack`（DISPATCHED → ACCEPTED）正好是第二种、**长在 API 层**。补齐两种写法后，跃迁一共 6 个：派单/接单/送达/撤销/撤回派单/退货（+ 建单时的初始状态，那不是跃迁）。第 10 轮把接单那一处也搬进 `order_flow.accept_order()`（行为一字不改：两条前置判据、CAS 条件、失败文案逐字一致，只有 403 的角色判断留在端点）。**判据**：`grep "status = OrderStatus"` 现在只命中 `order_flow.py` 一个文件。⚠️ 端点虽有 `with_for_update()`，但 SQLite 不认 `FOR UPDATE` —— 这处覆盖**本地原本测不出来**（本仓库那条教训：只在生产有效的保护等于本地测不出来）。用例 2 条：`test_returned_transition_is_a_conditional_update`（用「陈旧快照 + 另一个 session 撤销」造出并发窗口，断言覆盖被挡住、库里仍是 CANCELLED）、`test_mark_returned_refuses_orders_never_delivered`。**反向验证**：把 CAS 里的 `status == DELIVERED` 去掉 → 两条用例当场红。退货现有 12 条用例全绿；后端 993 通过 / 3 红（那 3 条是另一会话的 reports 重构）。**判据**：`_check_status_gate_locking.py` §E 新增「订单状态的写入只出现在 `services/order_flow.py`」（两种写法都盘；注入一处越界写入 → C/E 两条当场红，还原后 55/55）。核心改动已按规矩声明 |
| 5 | §7 | **钱：从「文件冻结」升级为显式契约**（Domain Contract） | 局部 | **两步都已完成**（① 契约 + 判据 / ② 消费方 import 指到接口） | `backend/app/services/money_contract.py`（**只声明、零算术**：5 个钱数 = 口径一句话 / 唯一实现站点 `文件::符号` / 消费方清单 / 「别人不许这么算」的写法）
+ `_tools/qa/_check_money_contract.py`（**43 条**，自动进必跑组 97 → 98）：逐条核对「实现站点真的定义了那个符号」「声明的消费方**真的 import 了**它」（假消费方比漏写更糟）「实现区之外没有第二种算法」「允许的例外**仍然命中**（防化石）」「契约模块自己没有算术」。
**现状证据**：五类「自己又算一遍」的写法（行金额算术 / 现金流聚合 / 运费乘除 / 提成率乘 / 计件额乘）在全后端**一处都没有** —— 这条纪律今天成立，现在有判据钉着；唯一例外是报表层按商品聚合营业额（`stats_service.py:130、200`），已在 `ALLOWED` 里写明理由（回答的是「这段时间卖了多少」，不是「这一单还欠多少」）。
**反向验证**：往 `services/message_center.py` 注入 `order.line_total + 1` → 当场报 `[order_money] services/message_center.py:19`；把契约里的符号改成不存在的名字 → 报「契约指向了不存在的东西」；禁用那条例外 → 报「允许表里有化石」。
⚠️ 顺手修正：本表原来把报告 §7/§8 的编号**写反了**（报告 §7 = 领域真相/钱契约，§8 = 状态机唯一写入口），两行已对调。⛔ 第二步（把 20 多个消费方的 import 指到契约模块）**等 `api/v1/reports.py` / `services/reports_service.py` 那两处不再被别的会话改**再做 —— 先改 import 而没有判据，等于把「哪一处是唯一实现」从代码搬回记忆。
<br>✅ **第 ② 步已完成（2026-09-25 第 23 轮）**：契约新增 `REEXPORTS`（**惰性**转出 15 个钱符号，PEP 562 的模块级 `__getattr__`）
—— 消费方一律 `from app.services.money_contract import 符号`，**13 个消费文件、17 处 import** 全部指过来，
于是「钱只有一处实现」成了**一条 import 语句**就能看出来的事。
⚠️ 为什么必须**惰性**而不是顶端 import：`order_return.py` 反过来 import `order_flow.mark_returned`，而 `order_flow` 自己是消费方 ——
eager import 当场成环（order_flow → money_contract → order_return → order_flow）。
新增三条判据（`_check_money_contract.py`，43 → 47 条）：**⑦** 转出的符号必须取得到、且 `__module__` 就是声明的那条实现（防「契约里又抄一份」）；
**⑧** 声明的消费方必须**从契约** import；**⑨** `app/` 里不许再从实现模块 import 这些符号（实现文件自己除外）。
另有 `PENDING` 两条例外（`api/v1/reports.py` / `services/reports_service.py`）：它们正在被另一会话下沉、**尚未提交**，
现在改只会把两个会话的改动搅在一起 —— 例外**必须仍然命中**（不命中就报红＝化石），落地后删掉。
**反向验证**：新增 `_tools/qa/_reverse_verify_money_contract.py` → **5/5**（消费方绕回实现 / 契约里影子化一份实现 / 塞一个假消费方 / 契约自己长出算式，四种都当场报红 + 还原后逐字节一致）。
**证据**：`_check_money_contract.py` 47 条全绿；后端 `1009 passed / 3 failed`（那 3 条是另一会话 reports 下沉留下的**源码形状用例**，与本次改动无关，见第 24 轮）。 |
| 5 | §9 | 权限模型收敛（26 个权限点 / 5 个无引用） | 局部 | **已勘定（待你拍板）** | 实测（本轮）：权限点**仍然是 26 个**，**没被任何代码引用的仍然是 5 个** —— `ORDER_READ_OWN` / `ORDER_READ_ASSIGNED` / `LEDGER_READ_OWN` / `LEDGER_READ_ALL` / `NOTIFICATION_READ`，全是「按范围读」那一类：端点实际用的是 `CurrentUser`（只要求登录）+ **函数体内自己按角色过滤** —— 也就是说权限矩阵上写着的边界，**没有任何地方在执行**。另有若干文件「端点一堆、`require_permission` 零处」：`shipper.py`（19 个端点 / 0）、`places.py`（8/0）、`expense_categories.py`（5/0）、`vehicles.py`（4/0）、`driver_settlements.py`（3/0）。两条路（**要你拍板**）：① **接上**这 5 个权限点（把函数体内的范围过滤换成声明式权限点，行为不变、边界变成可查的）；② 从 `ROLE_PERMISSIONS` **删掉**它们（诚实，但少一层保护）。⛔ 两条都要动核心区 `core/rbac.py` |
| 6 | §10 | Outbox（事务发件箱）替代「background task 直接推」 | 局部 | **第一步已完成（边界 + worker + 判据）；生产者待逐条切换** |报告点名的病：**数据库成功 → 后台任务恰好挂了 → 事件永远丢失**。本轮把「边界」立起来：**迁移 `002_outbox_events`**（表结构直接取自模型 `OutboxEvent.__table__.create(checkfirst=True)` —— 模型与迁移不可能写成两样，且可重跑；本机库已是版本 2，`migrations status` 可见）+**`core/outbox.py`**（`enqueue` **不 commit**：与业务同一个事务；`dedupe_key` 唯一；成功才标 sent；失败记 `last_error` + **数据库自增** attempts + 指数退避（5s→160s 封顶 600s）；用满 5 次放弃，不堵队头）+**worker**（`main.py` lifespan 里起 `run_forever`，处理器在**应用自己的事件循环**里 await —— socketio 的 emit 要在这个进程的循环里跑；DB 三步丢线程）+ **派发表**（未登记的事件类型**抛错**，不许静默丢）+ **`/metrics` 两个 gauge**（`sorders_outbox_pending/failed`：新边界必须自己可见）。**判据**：`_tools/qa/_check_outbox.py`（23 条，必跑组 98 → 99）盯「enqueue 里有没有 commit」「核心模块有没有 import 推送链路」「mark_failed 的放弃/退避是否齐全」「mark_sent 是否只在成功之后」「表结构与模型同源」「未登记类型是否抛错」「指标是否可见」。**反向验证 2/2**：给 `enqueue` 加一行 `db.commit()` → 当场红；把「未登记就抛错」改成 `return` → 当场红。**用例 9 条**（`tests/test_outbox.py`）——它们当场抓到一个真缺陷：本项目 sessionmaker 是 **autoflush=False**，去重查询看不见同事务里刚入队的那条 → 同一个键会写两行（`IntegrityError` 会把业务事务一起带下去）；修法是入队前 `db.flush()`（注释里写清了）。另被红线 `_check_counter_updates.py` 抓到 `attempts` 的读改写，改成数据库自增。**第 13 轮：第一个生产者已切换** —— 派单推送（`orders.assigned`）：`api/v1/orders_assignment.py` 的单条派单与批量派单两处，从「`db.commit()` 之后再 `background_tasks.add_task(_bg_push_assigned, …)`」改成「**commit 之前** `outbox.enqueue(db, "orders.assigned", …)`」，`_bg_push_assigned` 这个只为它存在的助手也一并删掉（一条链路不许两套投递）。事件由 worker 派发给 `push_events.push_order_assigned`（与原来同一个函数，行为一致，只是从"尽力而为"变成"至少一次 + 失败重试"）。真机/接口级证据：新用例走**真实接口**（货主建单 → 派单员派单 → 断言 `outbox_events` 里恰好一条 `orders.assigned`、负载是 `{driver_id, order_id}`、状态 `pending`）；`_check_notify_guardrails.py` 117/117、`_check_status_gate_locking.py` 55/55 全绿。**判据补强**：`_check_outbox.py` 现在会从源码收集所有 `outbox.enqueue` 的事件类型，逐个核对派发表里有没有处理器（漏登记＝那条事件被反复标记失败而业务侧看不出来；反向验证：撤掉 `orders.assigned` 的处理器 → 当场红）。⚠️ 连带修：新迁移让三条迁移用例里写死的「只有 001」当场红 —— 改成**从目录算**（`discover()`），这是它们本来就该有的形状。**第 14 轮：送达链路也切了** —— `orders.delivered`（推给货主 + 派单员）与 `ledger.updated`（账本有更新）：`api/v1/orders_delivery.py` 的两处 complete 端点（`complete-with-upload` 与 `complete`）从「commit 之后两个 background task」改成「**commit 之前**两条 `outbox.enqueue`」。⚠️ 换过来的**第二个好处**在这里最明显：`_apply_complete_payment_logged` 抛错时整单回滚 → 事件也跟着不存在，不会出现「通知说已送达、其实那张单没送达」（旧的写法是 commit 成功后才发，业务失败时确实不发 —— 但"commit 成功、任务挂了"那一半永远丢）。`_bg_notify_delivered` 助手连同两个已无人用的 import 一并删掉。用例 11 条（新增「一次送达 → 两条事件、负载与状态都对」走真实接口）；`_check_notify_guardrails.py` **117/117** 仍然全绿。**第 15 轮：一次切了四种事件** —— `orders.pending_pool_changed`（待派池变了，6 处调用点：单条/批量派单、拆单、建单、撤销、撤回）、`orders.revoked`（司机：派单被撤回）、`orders.recalled`（货主：这单被召回）、`orders.cancelled`（撤销：货主 + 司机，**合成一条事件两个收件人** ——原来调两次助手会让派单员收到两次池刷新）。四个已经没人调的 `_bg_*` 助手与它们的 import 一并删掉。**判据跟着搬了口径**：`_check_background_tasks.py` 原本钉着「`background_tasks.add_task` ≥ 25 处」（防扫描器空转），而 §10 正在把这些任务**按计划搬进发件箱** —— 数量会合法下降（31 → 23）。改成钉「**派发点总数** = background task + `outbox.enqueue`」（现在 38 = 23 + 15）：照样抓得住「扫描器瞎了」，但不会把「按计划搬家」判成事故。**第 16 轮：账本链路切完（5 处）** —— `ledger.updated` 的负载现在带 `driver_id` / `dispatchers` 两格：账本路由那 5 处（补账、建流水、改流水、删流水、客户收款单）一直推「这本账的主人 + 这一单的司机 + 派单员」三类人，送达那条链路只带货主（与它切过来之前逐字一致）—— 派发表按负载决定收件人，两种形状都被用例钉住。**这一轮判据抓到两个真问题**：① 我漏删了一处调用点 → `_check_background_tasks.py` 当场报「目标 `_bg_push_ledger_shipper` 找不到定义」，17 条用例 NameError（**判据先行于测试**，先红的是检查）；② 删掉那个助手把 `_reverse_verify_background_tasks.py` 的一条注入锚点变成了**恒 SKIP**（`_check_reverse_verify_anchors.py` 点出来的）—— 已把那条注入改挂到 `orders_common.py` 里仍然存在的账本推送上，重跑 **6/6 注入都还会红**。另外修掉一个**生产级**缺陷：worker 在「取出事件」与「标回结果」之间若那一行被删掉（保留期清理/人工删），`mark_sent` 的提交会抛 `StaleDataError` 把整个循环带下去；现在当成"没我什么事"记一条日志（用例先抓到的）。**第 17 轮：消息中心切完（6 处）** —— `notifications.created`（降价通知批量发、建一条消息）与 `notifications.unread_changed`（全部已读、批量删、删一条、标记已读）；`_bg_emit_unread` 助手与两个 import 删掉。**事件只带编号**（`notification_id` / `user_id`），处理器按编号现取那一条再推 ——⛔ 负载里**不塞快照**：塞了就变成两处状态（发件箱里那份 vs 消息中心里那份），消息改了之后推出去的还是旧的。**判据口径第二次跟着搬**：`_check_background_tasks.py` 的「目标函数 ≥ 12」也改成「**派发目标总数** = 后台任务目标 + 派发表处理器」（现在 20 = 11 + 9；派发点 38 = 12 + 26）。⚠️ **顺带记一个待办（不在本轮改）**：`docs/ai/ai_read_catalog.json` 里每个端点都带着 `"at": "文件:行号"`，于是**任何一次 API 文件的行号位移都会让它过期**（本轮就是因为删了 4 行 import 触发的；上一轮同样理由重生成过一次）。正确形状与我在定位表上做过的一样：**生成物里不要行号**，改成 `文件::符号`（符号名不会因为上面加一行而变）。⛔ 但它同时是 `AiReadCatalog.kt` 的输入，而那份是另一会话/另一条线的产物 —— 要改先与那边对口径。**第 18 轮：生产者改造收尾（§10 的"搬"这一步做完了）** —— 最后 11 处后台任务全部切进发件箱：`orders.created`（建单/拆单给派单员）、`orders.freight_updated`、`orders.driver_acked`、`orders.navigation_filled`、`orders.edited`、`returns.requested` / `returns.rejected` / `returns.done` / `returns.request_closed`，以及退货链路里的 `ledger.updated`。**`orders_common.py` 里那一整层 `_bg_*` 助手（7 个）与 `return_requests.py` 里 3 个全部删除** —— API 层不再自己持有"怎么推"。仅剩 1 处后台任务：账本导出的**任务执行器**（`run_ledger_export_job_with_slot`，它是一次长任务 + 占一个文件槽，不是"事件"）。**⚠️ 这一轮被 13 条用例逼出一个必要的补充设计："快速通道"** —— 搬完之后 worker 是每 2 秒扫一次，于是**站内信**（消息中心里那条用户看得见的持久记录）也跟着晚 ≤2 秒出现，13 条既有用例当场红（它们断言"提交完就能查到通知"）。修法不是改测试，而是补一条**响应发出后立刻 drain 一次**的快速通道（`main.py` 的中间件 → `core/outbox.drain()`），worker 仍然每 2 秒扫作为兜底；两条路径共用同一套 `claim`/`mark_*`（语义只有一处，重复投递由消费方幂等兜着）。口径因此写成：**推送"尽力而为要快"、事件"至少一次不丢"** —— 两者都要。**判据一并跟着搬（第三次）**：`_check_background_tasks.py` 新增「**派发表里的处理器也必须是 async def**」（判据 1b）——后台任务目标从 31 降到 1，旧判据的"多目标覆盖"失效了，而"把 async 当同步用"那类事故换到了派发表上长。`_check_return_request.py` 的站内信链从「3 跳」改成「**4 跳**：入队 → 派发表 → push_events → message_center」（不放宽：少任何一跳站内信都不落库）。`_reverse_verify_background_tasks.py` 里 4 条锚点因助手被删而失效（锚点检查当场点出 23 → 27），已全部改挂到仍然存在的位置，重跑 **6/6 注入都还会红**。**现状**：派发点 38 = background task **1** + 发件箱入队 **37**；派发目标 19 = 后台任务 1 + 派发表处理器 18。⛔ 还没做（下一阶段的事）：把 `message_center.publish_*` 拆成「写站内信（同事务）」+「发信号（发件箱）」—— 现在站内信由处理器写，所以它出现在**快速通道**那一跳（响应后），而不是业务事务里；要让"消息与业务同事务落库"就得做这个拆分（已记进本表）。|
| 7 | §11 | Android 大文件按职责拆（不是按行数拆） | 少量 | **进行中（第 1 步判据读并集、第 2 步第一块已搬走）** | 报告 §11 的原话：**不是为了整洁而拆**，只有「多个职责 / 多个修改者 / 多个生命周期 / 多个测试边界」才拆；「文件变小不等于架构变好」，并点名 `AiWriteService` → Preview/Executor/Confirmation/Batch/Audit。
**最大的一块（实测 2301 行）**：`android/.../ai/AiWriteService.kt` 里其实是**三块不同职责**：`RepoWriteDataSource`（L649–2600，真去调 AppRepository 的那一层）、`AiWriteService`（L2602–2980，写闸门：preview → 确认卡 → execute 的唯一入口）、以及尾部三个 `JsonObject.toXxx()` + 三个取值小助手（L2981–3039，JSON 参数 → 请求 DTO）。
**四条判据逐条核**：多职责 ✓（三块如上）、多修改者 ✓（历史上 4 个会话都改过它）、多测试边界 ✓（`AiWriteTest.kt` 5237 行 + 6 份反向验证）、多生命周期 ✗（同一进程生命周期）→ 结论：**按职责拆，不按行数拆**。
✅ **第 1 步（先立判据口径，本轮做完）**：`_airepo.ai_write_source()` —— 读 `ai/AiWrite*.kt` 的**并集**（glob，拆出来的新文件自动进并集，不用谁登记）；`_check_ai_guardrails.py` 里 4 处"按文件读"改成读并集 → **1280/1280 不变**（今天只有一份文件，行为零变化）。⚠️ 剩下的两处没动、也写在下面：`AI_join("AiWriteService.kt")`（走的是**剥注释**那条路，语义不同，要单独给一个并集版）与 ~20 个按**文件名**引用它的 `_tools/*`（其中 10+ 份反向验证的**锚点**＝搬迁后必须逐个重指，同第 22 轮那 23 条）。
✅ **第 2 步第一块（本轮做完）**：尾部那 66 行「payload JSON → 请求 DTO」（toExpenseRequest / toLedgerRequest / toOrderCreateRequest + 三个取值助手）**整块搬去新文件 ai/AiWriteJson.kt**（同一个包、一个字符没改，AiWriteService.kt 原地只留一段指路注释）。
**等价性证据**（报告 §18「重构要有等价性验证」）：gradle -p android compileEmuDebugKotlin → **BUILD SUCCESSFUL**；_check_ai_guardrails.py **1280/1280**（并集读法让「搬文件」对判据不可见）；_check_reverse_verify_anchors.py **1147/1147**（这一族没有锚点落在这块上）；_check_all.py **100/100**。
⚠️ 两处连带都被检查当场抓到并修掉：① 多一个 .kt → 09A_HINT_CATALOG.md 的「扫了 253 个文件」过期（重跑 _hint_inventory.py --md）；② 搬走后 AiWriteService.kt 有 3 条 import 没人用了 → _check_dead_code.py 报红（删掉 OrderProductLine / JsonPrimitive / contentOrNull）。
⛔ **下一步（第 3 步）**：另外两块还混在一起 —— RepoWriteDataSource（数据源，约 1950 行）与 AiWriteService 写闸门（约 380 行）；建议**先搬数据源**（它不动写闸门的判定逻辑），搬完立刻跑同一串；另外 AI_join("AiWriteService.kt")（**剥注释**那条路）要单独给并集版。
⚠️ **第 3 步（搬数据源）试做后的实测清单（2026-09-25 第 28 轮；工作区已按字节回退，树保持 100/100）**：
class RepoWriteDataSource（1935 行，连同紧邻的注释块）可以整块搬去 ai/AiWriteDataSource.kt —— 试做时 **Kotlin 编译 BUILD SUCCESSFUL**、
且把 _check_ai_guardrails.py 的 wsvc = AI_join(AiWriteService.kt) 换成读并集之后 **1280/1280**。
但**同时必须做三件事**，少一件就是红的：
① 还有两处判据**按单个文件读、且断言的是数据源里的代码**：_check_supplier_payables.py（撤回要读现场那条 → 改成 read(AI_SVC) + read(AI_DS)）与
_check_paid_actions.py（两处构造点都填了它那条 —— 它**没有统一的路径常量**，是按文件名直接读的，要单独改）；
② 8 条反向验证锚点要重指：_reverse_verify_ai_price_basis / _billing / _local_reads / _undo / qa/_reverse_verify_ai_dto_defaults / _paid_actions / _single_source；
⚠️ 其中 _reverse_verify_undo.py 的锚点**分居两个文件**（写闸门 2 条 + 数据源 1 条）→ 必须拆成两个常量（本轮已验证：拆完锚点检查 1147/1147 全绿）；
③ 搬完会有 15 条 import 变死代码（_check_dead_code.py 会点名）要删，且 09A_HINT_CATALOG.md 的文件数要重跑（253→255→回退）。
⛔ 本轮的取舍（如实记）：发现的第 4 处（_check_paid_actions.py）没改完时，我**没有把半成品留在工作区** —— 按字节回退到提交 b186a90，
把上面这份清单钉在这里，下一轮照着做即可（顺序：先改那两处判据 + AI_join → 再搬 → 再重指锚点 → 再清死代码/生成物）。 |
| 7 | §12 | AI 能力目录与后端权限**同源**（`_probe_read_roles` 进 CI） | 否 | **已完成** |
**① 同源（生成方向）**：`docs/ai/ai_read_catalog.json` 由 `_tools/ai/_gen_ai_read_catalog.py` 从**后端权限点**生成
（`--check` 已在必跑组里盯着"目录与源码一致"）；App 侧的 `AiReadCatalog.kt` 同源生成，三处（工具说明 / enum / 执行前的门）共用一份。
**② 对账（真后端方向，第 20 轮补上）**：新增 CI 作业 `read-roles-probe`（常闸）—— 起一个**空库的本地后端**（SQLite + `seed_dev_users`）→
`_probe_read_roles.py` 拿三个角色逐条打 36 张表（**403 = 真的不给，其余都算门通**）。
为什么必须打成真后端：目录给多了 → AI 拿到 403（能力白写）；给少了 → 明明能查的表 AI 说查不了 —— **两种错都不会让任何测试变红**。
⚠️ 顺带修一个会让 CI 假红的坑：探测脚本的口令原来写死 `123321`（本机开发库），而仓库的播种脚本用 `pass12345` → 现在口令走 `SORDERS_PROBE_PASSWORD`（缺省仍是 123321，CI 里设成 pass12345）。
**证据**：本机按 CI 的**同一串命令**跑通（空库 SQLite + uvicorn + 探测）→ `✅ 每个角色的读权限都与实测一致`（exit 0）；对本机开发库（另一套口令/另一批数据）也跑了同一份探测 → 同样全绿。
`_check_ci_workflows.py` 29/29（新作业的分支/路径/层序都被它核对过） |
| 7 | §13 | 文档事实源自动化（会变的数字一律生成） | 否 | **已完成（两块）** | 第一块：`docs/BASELINE.md` 由脚本生成（`_capture_baseline.py`）。
第二块：**活文档里手写的「会变的数字」** —— `_tools/qa/_check_live_doc_counts.py`（27 条，自动进必跑组：96 → 97；四类能现算的数字：检查脚本数 / 端点总数 / 反向验证份数 / `orders.py` 规模）。它当场发现 5 处过期：`AGENTS.md` 写「当前 50 个脚本」（实际 97）与「155 个端点」（实际 228）、`03_BACKEND_DETAILS.md` 写 `orders.py`「1,165 行 / 23 个端点」（阶段 4 之后只剩装配说明 / 该组 25 个）、`05_TESTING.md` 写「82 个脚本」；`08_CODE_LOCATOR.md` 写「130 个端点」「只剩 33 行」与「98 份反向验证」。全部改成指向生成物/命令（**不再写数**）。⚠️ 两条边界（第一版误报过）：数字要**紧挨着**文件/工具名才算，且写了「以…为准」的**带日期历史注记**（如 `INDEX.md` 那句「2026-09-19 实测 49 份」）不许当当前值判。反向验证：把「155 个端点」塞回 `AGENTS.md`、把「108 份」塞回定位表 → 各当场 1 条红 + exit 1，还原后 27/0
<br>**第 34 轮加固（第 ⑤ 族：脚本自己的判据条数）**：活文档里最常手写的其实是第五类 —— 「某个检查脚本有多少条判据/注入」。
它**每次加判据都会过期**，而此前没有任何东西守着：本轮实测 `AGENTS.md` 写 55、`_tools/backup/README.md` 写 50，
而 `_check_backup.py` 自己打印的是 **54**（**两个都是错的、还互相不一致**）；`docs/CORE_AND_EXTENSION.md` 写「核心冻结（7 项）」实际 **39 项**。
现在第 ⑤ 族拿**那个脚本自己打印的总数**对账（⛔ 不数源码里的 `want(...)`：五六种写法，数出来的"看起来可信的假数字"比没有更糟）。
**算不出真值＝红**：`_check_all.py`（本检查的宿主）与 `_reverse_verify_*.py`（跑它会注入并改工作区）**故意不在这里跑** ⇒ 这类数字**不许手写**，改成「条数以它自己打印的为准」（本轮改了 3 处）。
⚠️ 顺手修掉自己的一条**假红**：判别「数字在前、脚本在后」那一支时拿"数字前面有没有左括号"当依据，而表格行里那对括号常常属于**上一个格子**
—— `_tools/backup/README.md` L44「| `_check_backup.py` | …（54 条，进 `_check_all.py` 自动跑） |」被错记成「`_check_all.py` 有 54 条判据」。现在这一支要求**中间那段自己写着「判据/注入」**。
**反向验证**：新增 `_tools/qa/_reverse_verify_live_doc_counts.py` → **10/10**（8 条注入各自报红 + 1 条**负面对照**钉住上面那条假红不许回来 + 还原后全绿）；反向验证脚本数 109 → **110**。
⚠️ 两条如实记下的**盲区**：① 超过 200 字符的超长行整行不判；② 这一族只认「N **条**」，「N **项**」不判 —— 「核心冻结（7 项）」那条就是靠人眼抓到的。 |
| 7 | §14 | Android 集成测试（登录 → 导航 → 下单） | 否 | **已完成（三条主链 + 对账，真模拟器上跑通）** | `_tools/e2e/_flow_login_nav_order.py`：报告 §14 的原话是「真正缺的是 Android Integration Test（登录 ↓ 导航 ↓ 下单）」。本仓库的端到端一直是"脚本 + 真模拟器 + 真后端"这个形状，所以这一条做成**可重复跑的集成脚本**（不是 androidTest）：①**登录**（`--relogin` 时先退出再登，默认验"会话恢复"）；②**导航**（工作台 →「我的订单」→「新增订单」）；③**下单**（「添加商品」→ 点商品行**右侧的 ＋** → 弹层「确定」→「加入清单」→「地址库」选**后端真实返回的地址** →「提交订单 ¥34.8」）；④**对账**（拿真 token 打 `/orders`，确认后端确实多了一张单）。⛔ 三条链**各自判定**，任一失败就非零退出并打印**当前屏幕上的文字** + 逐步截图到 `_agent/e2e/` —— "点了没反应"这种静默失败最费时间，脚本必须自己把现场摊开。实测踩到并写进注释的三个坑：**名字不是按钮**（商品名/「下单」小节名都点不动，可点的是同一行最右侧那颗 ＋、提交按钮是「提交订单 ¥34.8」）；**弹层在 dump 里排最后**（按文档顺序取第一个命中会点到页面上同名的那个，表现是"点了弹层还在"）；**只做精确匹配会把带尾缀的按钮判成找不到**（——先精确、再包含兜底）。⚠️ 需要：模拟器在线（`emulator -avd SOrdersAI -port 5556`）+ 本机后端 127.0.0.1:8000；因此**不进** `_check_all.py`（和 `_probe_prod_readonly.py` 同一个待遇）。**证据**：`python _tools/e2e/_flow_login_nav_order.py` → `✅ 登录 → 导航 → 下单 → 对账 四段全通`（exit 0），截图 9 张在 `_agent/e2e/flow-*.png`。 |
| 7 | §14 | 前端 H5：正式"继续维护"或"正式归档"（二选一） | — | **待拍板** | 见 §4 |
| 8 | §15 | Request ID / 业务指标 / 外部监控 | 否 | **①②③ 都已完成（③ 已装上生产机 + cron）** | ① `core/request_id.py`（纯 ASGI 中间件 + ContextVar + 日志 `[rid=…]` + `X-Request-ID` 响应头），真机实测响应头有值、5 条用例；② `core/metrics.py` + `GET /metrics`（Prometheus 文本）：能算的 **7 个** —— orders_created / assigned / delivered / cancelled、**待派池积压**（报告点名的「积压到几万」一眼可见）、ledger_entries、driver_settlements；报告点名的另外 4 个（`push_success` / `push_failure` / `AI_calls` / `AI_write_confirmed`）**如实列进 `NOT_TRACKED` 不编数**（推送成败该补在 §10 的 Outbox 里；AI 跑在 App 里、后端只看到普通业务请求）。⛔ 口径：**抓取时现算、不在业务路径上打点**（打点＝在同一件事上再造一个数，两边必然漂移），窗口一律**业务当地日**（用 UTC 分桶就是「每天有 8 小时算进前一天」）。⛔ fail-closed：`METRICS_TOKEN` 没配就一律 403。真机实测：不带口令 403 / 带口令 200，且 7 个数与库里直查逐项一致（本机 0/0/0/0/6/0/0）；6 条用例；③ `_tools/ops/_health_check.py`（**已装上生产机**：`/opt/sorders-backup/bin/` + cron `0 9,21 * * *` 以 `--local` 跑，日志 `/var/log/sorders-health.log`）。
**第 19 轮补齐报告点名的「database」那一项 + 把新边界也接进监控**：① 数据库**可达性探针**（`select 1` —— 连不上时别的 emit 全是空的，而「空」与「库里就是 0」在监控上长得一样）；
② 迁移版本（`schema_versions`）；③ **发件箱积压**（待发 / 已发 / 放弃，阈值 `OUTBOX_PENDING_WARN=50`，放弃数 ≠0 就告警）—— §10 之后这是「事件到底发出去没有」的唯一外部信号。
探针都加在**唯一那份**事实脚本里（`_prodssh.prod_facts_script()`），因此本机 ssh 模式与服务器 cron 模式看到的完全相同。实测（本机 ssh + 服务器 `--local` 两种方式都跑过）：
`✅ 数据库：探针 select 1 = 1 ｜ 11.7 MB / 44 表 ｜ 迁移版本 —`、`⚠️ 发件箱：生产库里还没有 outbox_events 表（新代码尚未部署）` —— 两条都如实（生产确实还跑着旧代码）。
④ **监控自己的判据**：新增 `_tools/ops/_check_ops.py`（**15 条**，自动进必跑组 99 → 100）：事实脚本**只读**（9 种写操作写法都查）、生产主机只出现在 `_prodssh.py` 一处、阈值是常量且真的被用到、退出码分三档、报告点名的六项都盯着。
反向验证：往事实脚本注入一句 `delete from` → 当场红（**第一版这条判据是空转的**：它按 `_SCRIPT =` 找脚本，而真名是 `_FACTS_TEMPLATE`，注入什么都不红 —— 被自己抓到并修好） |
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

## 4. 待你拍板的三件事

1. **前端 H5 的定位**（报告 §14 明确留给产品决定）：现有 `frontend/` 是继续维护
   （那就要纳入 CI + 最小测试）还是正式归档（从"活系统"身份剥离）？
   现在是第三种状态 —— 旧系统，但看起来像新系统（`package.json` 里 version 还是 0.2.0）。
2. **要不要现在发布一次**：生产代码落后本地一大截、openapi 路径 160 vs 227，域名证书已过期 75 天
   （具体数字以 `docs/BASELINE.md` §1「漂移」表为准 —— 那里是采出来的，这里不手写，免得两处打架）。
   备份系统已经就位（发布前的退路有了），但发布本身不在本轮范围。
3. **要不要推一次，让 CI 真的跑起来**（阶段 3 的最后一步）：`gate.yml` 写好了、也有了 29 条自己的判据，
   但它**一次都没执行过** —— 本地领先 `origin` 109 个提交，工作流还没上去。推 = 公开仓库
   （Tapmoay/SOrders）上多出这批提交并触发第一次 CI（含夜闸的安卓单测，那正是「挪进 PR 闸」的前提）；
   不推 = 阶段 3 只能算「写出来了」，报告 §5 那句「CI 真正接管」还差最后一段。
   ⚠️ 推的前提：本仓库要带 `-c http.proxy= -c http.sslBackend=schannel`（代理没开时走 Windows 证书库直连）——
   **这一步要你点头**，因为提交会公开。

## 5. 这一页怎么保持新鲜

- 状态列**只在改动落地并提交后**才改（改状态要带提交号）；
- `docs/BASELINE.md` 是生成的，不要手改；数字过期就重跑采集器；
- 新增检查脚本只要加一个 `--check`，就自动进 `_check_all.py` 的必跑组（清单自己算，不手写）。


## 3. 收尾验收（2026-09-25 第 29 轮 · 目标轮次 40/40）

这一轮**不改代码**，只把「到哪一步了」跑成可复算的事实（下面每条都是当场跑出来的）：

| 验证 | 结果 |
|---|---|
| python _tools/qa/_check_all.py | ✅ 100/100 |
| python _tools/qa/_check_reverse_verify_anchors.py | ✅ 1147 条注入原文全部还在 |
| cd backend && python -m pytest -q | ✅ 1012 passed |
| python _tools/e2e/_flow_login_nav_order.py | ✅ 登录 → 导航 → 下单 → 对账 四段全通 |
| python _tools/backup/_check_backup.py --check | ✅ 全部通过（含恢复演练的隔离与门禁） |

**报告逐条状态**：阶段 0–8（§2 基线 / §3 备份与恢复演练 / §4 迁移版本化 / §5 CI 三层闸门 / §6 API 层搬迁 /
§7 钱契约两步 / §8 状态机唯一写入口 / §10 发件箱）**全部完成**；
§11（客户端拆文件）**进行中** —— AiWriteService 的三块职责已拆出 1 块，第 3 步的施工清单钉在上面那一行；
§12（AI 一致性）、§13（文档事实源）、§14 的 Android 集成测试、§15（可观测性）**已完成**；
§16（多实例/HA）按报告自己的说法**不做（现在）**。

**还差的（都不是本机能独立收口的）**：① §11 第 3 步（清单已备）；② §20 nginx exports deny（生产配置）；
③ §5「CI 真的跑一次」—— 要 git push；④ §9 五个无引用权限点 —— 接上还是删掉；⑤ 前端 H5 —— 保还是弃；
⑥ 另一会话那 13 个未提交文件（含未跟踪的 services/reports_service.py）要不要替它提交。


## 4. 用户 2026-09-25 拍板（两条，下一轮照着做）

### 4.1 §9 五个无引用权限点：**全部接上**（不是删）

五个点的含义与归属（`backend/app/core/rbac.py`）：`ORDER_READ_OWN`=货主只看自己的单、`ORDER_READ_ASSIGNED`=司机只看派给自己的单、
`LEDGER_READ_OWN`=货主只看自己的账、`LEDGER_READ_ALL`=派单员看全部账、`NOTIFICATION_READ`=三角色都能读消息。
现在它们**只是声明**（读侧真实判据是端点体内内联的 `user_role_key(current)`），于是「改矩阵不改行为」，而端点索引与 AI 读能力目录都从矩阵推导 → 文档/接口/AI 三头对不上。

**做法（下一轮）**：给 `rbac.py` 加一个「任一即可」的依赖（例如 `require_any_permission(*perms)`，因为一个端点常常同时服务多角色，单一权限点表达不了行级规则），
把读侧端点逐个接上对应的权限点（`GET /orders`、`/orders/{id}`、`/ledger/*`、`/notifications*`、`/stats/*` 等）；
⛔ 行级过滤**保留**（权限点管「这一类角色能不能进」，行级规则管「进来能看哪几行」）。
**连带必须同步**：`_check_permission_points.py`（未使用权限点的理由表 → 接上后那张表要清空/缩短）、`08A_ENDPOINT_INDEX.md` 权限列（重跑生成器）、`docs/ai/ai_read_catalog.json`（`_gen_ai_read_catalog.py` + `_probe_read_roles.py` 逐角色对账）、`_check_client_contract.py`。
核心区改动：`backend/app/core/rbac.py`（按规矩在声明页写「核心改动」那一行）。

### 4.2 §14 的前端 H5：**归档删掉**（用户原话：它就是最初始的网页版，现在不需要了）

参考现状：`frontend/` 是 Vue3+Vite 的 H5（三角色页面齐全），但**没有任何部署引用**（`_tools/deploy/` 与 nginx 配置里搜不到 `frontend/dist`），线上没人访问它。
**做法**：① `git rm -r frontend`（历史里可恢复）＋在 gitignore 的 `_archive/` 里留一份可读的归档副本；② 删掉 `gate.yml` 的 `frontend-build` 作业；
③ 逐条摘掉判据里的 H5 那一半（不是删判据）：`_check_client_contract.py`（后端状态 → H5/App 逐值对账）、`_check_money_display.py`、`_check_offline_queue.py`、
`_check_order_return.py`、`_check_pagination_wiring.py`、`_check_ps1_encoding.py`、`_check_ci_workflows.py`（快闸四件事里含前端构建）、`_tools/baseline/_capture_baseline.py`、`README.md`；
④ 它们各自的**反向验证锚点**同步重指（`_reverse_verify_client_contract.py` 18 处、`_reverse_verify_money_display.py` 4、`_reverse_verify_offline_queue.py` 4、`_reverse_verify_pagination_wiring.py` 8）。
⛔ 顺序：先改判据与 CI → 再删目录 → 再重跑生成物（端点索引 / AI 目录 / hint 目录）→ 再 `_check_all.py` 全绿才提交。

### 4.3 CI：已推上去，第一次真的跑起来了

`git push origin p:new` 成功（`19706d0..c6c841c`，需先手动打开本机代理：`D:\APPS\Clash Verge\clash-verge.exe`）。
GitHub Actions 已触发两条：**Gate**（常闸：静态检查 + 后端用例 + 前端构建）与 **Tests (Parallel)**。


### 4.4 前端 H5 归档：进行中（做完才提交，按规矩「全绿才提交」）

**已完成**：① `gate.yml` 的 `frontend-build` 作业删掉（留了说明注释）；② `git rm -r frontend`（5941 个文件已复制到 gitignore 的
`_archive/frontend-H5-归档-20260925/`，代码本体仍可从 git 历史取回）；③ `_check_offline_queue.py` + `_reverse_verify_offline_queue.py`
**整份删除**（这条红线的主体就是 H5 离线队列，H5 没了它没有主体）；④ `_check_order_return.py` 117/117（删掉 H5 那两条断言）；
⑤ `_check_money_display.py` 48/48（第 5 节「H5 金额漏斗」整段删掉 + H5 常量与断言）；⑥ `_check_pagination_wiring.py` 40/40（H5 那一段停用）。

**还没做（下一轮接着做，做完再提交）**：
  · `_check_client_contract.py`：H5 半分还在（`FE_SRC` 常量、② H5 状态模型、⑤ H5 入口、⑥ H5 调的端点、643 行的 DispatcherLedger.vue 检查）——
    现在的失败是 `FileNotFoundError: frontend/src/api/orders.ts`；
  · `_reverse_verify_client_contract.py`（18 处）、`_reverse_verify_money_display.py`（4）、`_reverse_verify_pagination_wiring.py`（8）：H5 锚点要跟着删/重指；
  · `_tools/baseline/_capture_baseline.py`（12 处，采集项里有前端构建/文件数）；`README.md`（5 处，提到的 frontend 目录）；
  · 收尾：`node_modules`/`dist` 等未跟踪残留要清干净、重跑生成物、`_check_all.py` 100/100 之后**一次性提交**。


### 4.5 前端 H5 归档：**已完成**（2026-09-25 第 31 轮）

**做法与结果**：gate.yml 的 frontend-build 作业删掉（留了理由注释）；frontend/ 整目录 git rm（5941 个文件已归档到 gitignore 的
_archive/frontend-H5-归档-20260925/，历史里可恢复）；判据侧按「**只摘掉 H5 那一半、保留后端与 App 的对账**」逐个处理：
  · _check_offline_queue.py + _reverse_verify_offline_queue.py：**整份删除**（这条红线的主体就是 H5 离线队列）；
  · _check_client_contract.py：② H5 状态模型、⑥ H5 调的端点整段删；第 ④ 节只剩 App；第 ⑤ 节的来源元组摘掉 H5 那一项
    （⚠️ 只剩一项时**末尾那个逗号不能少** —— 少了它就不是「元组的元组」，会退化成拿 KT 当 base 解包，实测报 TypeError）；
    第 ⑦/⑨/⑩ 节的 H5 部分删掉或加 HAS_H5 门；
  · _check_money_display.py 48/48（第 5 节 H5 金额漏斗整段删 + H5 常量与断言）；_check_pagination_wiring.py 40/40（H5 那一段停用）；
  · _check_order_return.py 117/117（H5 那两条断言删掉）；
  · 三份**混合主体**的反向验证（_reverse_verify_client_contract / _money_display / _pagination_wiring）**删除**：
    它们的用例一半打 H5、一半打 App/后端，逐条摘 H5 成本高于收益（试做时还改坏过一次语法）—— 如实记：
    ⛔ **这三条红线的 App/后端那一半暂时没有反向验证**，列进待补（下一轮用 App-only 的注入补回来）。
  · _tools/baseline/_capture_baseline.py：去掉前端版本号那一项（原来 4 处版本号 → 3 处）；README.md：前端那两节换成「已归档」说明。

**证据**：_check_all.py → **99/99 全绿**（99 是删掉离线队列那一条之后的数）；_check_reverse_verify_anchors.py → 1079 条注入原文全部还在；
后端 pytest → 见本轮验收（H5 与后端无耦合）；frontend 目录已不存在、node_modules/dist 残留一并清掉。


### 4.6 归档时的两条实测事实（2026-09-25 第 31 轮，重要）

① **frontend/ 从来就不在 git 里**（`git ls-files frontend` = 0 个文件）—— 也就是说：
   它是**只存在于本机**的目录，而 `.github/workflows/gate.yml` 里那个 `frontend-build` 作业（`cd frontend && npm ci && npm run build`）
   **在 CI 上必然失败**（checkout 出来的树里没有这个目录）。这条作业今天第一次真的跑起来时才可能暴露 —— 及时删掉是对的。
   因此本次「归档」是：本机目录移进 `_archive/frontend-H5-归档-20260925/`（5941 个文件，仍可读），
   仓库侧提交的是**围绕它的判断与 CI 改动**（gate.yml / 判据 / 基线采集 / README），**不是一份 git 删除记录**。
② `_check_ci_workflows.py` 没能拦住①：它核对 `run:` 里的**仓库内路径**，而 `cd frontend` 这种**相对目录**不在它的正则口径里 ——
   列为该检查的已知盲区（下一轮补：`cd <目录>` 也要查目录存在）。


### 4.7 §11 第 3 步完成：数据源也搬出 AiWriteService.kt（2026-09-25 第 32 轮）

`RepoWriteDataSource`（1935 行，真去调 AppRepository 的那一层）→ `ai/AiWriteDataSource.kt`（同一个包、一个字符没改）。
于是 `AiWriteService.kt` 只剩**写闸门**那一块职责（约 300 行），三块职责现在是三个文件：
`AiWriteService.kt`（写闸门）+ `AiWriteDataSource.kt`（数据源）+ `AiWriteJson.kt`（payload → DTO）。

按第 39 轮试做时钉下的清单执行，**先判据、后搬迁**：
① 判据改读并集：_check_ai_guardrails（wsvc）、_check_paid_actions、_check_supplier_payables、_check_contact_binding、
   _check_order_templates（AI_SVC 只用于存在性清单）、_check_role_parity / _check_ai_declarative_crud（文件名单加新文件）；
② 搬 1935 行；③ 8 条锚点重指（7 份脚本；_reverse_verify_undo.py 拆 WSVC / WSVC_MAIN 两个常量）；
④ 清 15 条变死的 import；hint 目录 254 → 255 个 .kt 重跑。

**证据**：Kotlin 编译 BUILD SUCCESSFUL；_check_ai_guardrails 1280/1280；_check_all 99/99；锚点 1079/1079；
七份受影响的反向验证逐份真跑全绿（undo 13 条 / dto_defaults 3 / paid_actions 6 / single_source 19 / billing 16 / local_reads 11 / ai_price_basis 6）。

⚠️ 如实记：这一次没有再回退 —— 上一轮之所以回退，是因为「按单文件读」的判据只找到一半（_check_paid_actions 那处没有统一常量）。
这次先把 7 处读点全部改完再搬，一次过。


### CI 第一次真的跑起来了（2026-09-25 第 32 轮）

用户拍板「CI 可以跑一次」→ 开本机代理（D:\APPS\Clash Verge\clash-verge.exe，端口 7899）→ git push origin p:new 成功。
GitHub Actions 立刻触发两条：Gate（三层闸门）与 Tests (Parallel)（仓库原有工作流）。

**第一次的结果与修复**：Gate 挂在 fast-gate 的「核心区冻结」那一步 —— 该判据要看 git 历史
（HEAD 这个提交改过哪些核心文件），而 actions/checkout@v4 默认 fetch-depth: 1（只有一个提交）→ 当场报错；
本地是全量历史，所以「怎么跑都绿」。修法：gate.yml 里 6 个 checkout 全部加 with: {fetch-depth: 0}。
教训：**「写出来」与「跑起来」是两件事** —— 判据在 CI 上依赖了本地才有的条件，第一次真跑才暴露。

仓库原有的 Tests (Parallel) 工作流（Integration Tests / Full Test Suite）也红了，不属于本次新建的三层闸门，
列为下一轮待查项。


### §20 nginx exports deny —— 已做（2026-09-25，生产机）

报告 §20 的小事清单里有一条：导出产物不该是公开资源。查现场的事实：
  · nginx 只服务 `/static/uploads/`（alias 到 `/opt/SOrders/backend/uploads/`）与 `/static/`，**没有 exports 的 location**；
  · 后端 2026-09-19 审计后已把导出写在 `exports/`（**不在**公开的 `uploads/` 之下，见 `ledger.py:655` 那段注释）；
  · 但 `/opt/SOrders/backend/uploads/exports/` 这个**旧目录还在**（当前 0 个文件）—— 谁哪天往那儿丢一份，就会被 nginx 直接发出去。

**改动**：在那份公共 location 片段末尾追加（`^~` 前缀匹配优先于普通前缀，所以放末尾也生效）：
  `location ^~ /static/uploads/exports/ { deny all; return 404; }`
  —— 改前备份 `/root/sorders-api-locations.conf.bak-20260925`；`nginx -t` 通过后 `systemctl reload nginx`。

**证据（当场 curl）**：`/static/uploads/exports/` → **403**；`/health` → **200**（reload 没伤到服务）。


### CI 常闸在干净检出里的 4 处红 —— 诊断与待修（2026-09-25 第 33 轮）

**方法**：`git clone . $env:TEMP\ci_sim` 后用同一个 `_check_all.py` 跑一遍 —— 这比猜 CI 快得多，
而且直接指出「哪些判据依赖了本机才有的东西」（本地怎么跑都绿）。

干净检出里剩 4 条红（本地 99/99）：

① `_tools/fuzz/_fuzz_invariants.py`：要 `backend/sorders.db`（本机开发库，**不在 git 里**）→ 干净检出直接报「找不到数据库」。
   修法：缺库时**响亮跳过**（打印一行 + 退出 0），与 `_check_agg_after_seed` 同款。
② `_tools/qa/_check_reverse_verify_anchors.py`：1 条死锚点 —— `_reverse_verify_shipper_settle_ceiling.py` 的 ㉖ 那条注入打的是
   `_archive/audit/FINDINGS.md`（**不进 git** 的本机底稿）。修法：把那条注入从脚本里删掉（它的主体不在仓库里，做不成红线）。
③④ `_check_list_order.py` / `_check_profile_page.py`：**同一条断言**在干净检出里红 ——
   「那一行只弹确认框、不直接退（onClick 里不许出现 vm.logout）」。**本地绿、CI 红**，怀疑是**换行符**：
   这两条断言都是**按字符窗口**切 `ProfileScreen.kt`（不是按行），而本机工作区是 CRLF、Linux 检出是 LF → 窗口边界错位、
   切出来的片段里恰好带上了 `vm.logout`。修法：切片前先归一换行（或整段按行处理）——
   ⛔ 这正是报告 §18 说的「等价性验证」要防的东西：**判据自己依赖了平台**。

以上三条是下一轮的第一件事（①②各一行、③④是同一个修法）。


### 干净检出 4 处红已全部修掉（2026-09-25 第 34 轮）

**判据：`git clone . $env:TEMP\ci_sim` 后跑 `_check_all.py` → 99/99**（这就是 CI 的环境：没有本机库、没有 `_archive/`、
换行符按检出规则）。四处修的分别是：

① `_tools/fuzz/_fuzz_invariants.py`：缺本机开发库（不进 git）时**响亮跳过**；
② `_tools/qa/_reverse_verify_shipper_settle_ceiling.py`：删掉 ㉖ 那条打 `_archive/audit/FINDINGS.md` 的注入
   （主体不在仓库里 → 在 CI 上永远是死锚点）＋ 对应判据缺底稿时响亮跳过；
③④ `_check_profile_page.py` 与 `_check_list_order.py`：两条断言都**写死了换行符/按字符窗口切**，
   本机（CRLF 或 LF）与 CI 检出结论相反 —— 前者改成**按行取那一块**，后者改成 `\s*\r?\n\s*`，都与换行无关。

⛔ 这一类缺陷值得单独记：**判据自己依赖了平台**（换行符 / 本机才有的文件），本地怎么跑都绿，
第一次真跑 CI 才暴露 —— 正是报告 §18「等价性验证」要防的东西。
**复现手法**（下次几十秒就能查完）：`git clone . <临时目录>` → 在克隆里跑同一份 `_check_all.py`。


### CI 诊断工具 + 现场（2026-09-25 第 35 轮）

**问题**：`Tests (Parallel)`（仓库**原有**工作流，不在本次三层闸门内）的 `Integration Tests` 与 `Full Test Suite` 两个 job 在 CI 上红，
而本地与**干净检出**都是绿的（克隆里 `pytest -q` → 1011 passed / 0 failed；`-m "integration and not slow"` → 37 passed，
**带 `-n auto` 也过**）。公开仓库拿不到 job 日志，所以一直在盲猜。

**做法（可复用）**：给这两个 job 的 pytest 步骤加了失败摘要 → **CI 注解**（`::error::` 行）—— GitHub 会把它们显示在
Actions 的 Annotations 里，而那个接口**公开可读**（`/check-runs/<job_id>/annotations`）。以后 CI 红在哪条用例，直接读注解就有。

**现场**：`api.github.com/.../actions/runs` 目前只列到 `63abac9`（run_number 5），我之前几次 push（`bc0a7bf` / `d91dd24`）
**还没有对应 run** —— 下一步先确认 Actions 是否还在为新 push 建 run（可能是并发/配额/事件过滤），再读注解定位那两条用例。