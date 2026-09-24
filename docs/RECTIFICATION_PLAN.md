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
| 5 | §8 | 状态机唯一写入口（Command → OrderFlow） | 局部 | **已完成** | 第 9 轮勘定：订单状态的写入只有 3 处（`order_flow.py` 派单/送达早已是条件 UPDATE，`order_return.py:349` 还是**无条件赋值**）。第 10 轮收口：新增 `order_flow.mark_returned()`（`update(orders).where(id, status==DELIVERED, deleted_at is null).values(status=RETURNED)`，改到 0 行就 rollback + 抛错，与 `cancel_pending`/`recall_dispatch` 同形），`return_order` 只剩一次调用并把 `ValueError` 翻成 `OrderReturnError`（端点只认它 → 400，不会是 500）。⚠️ **勘定本身漏过一次**（诚实记录）：第 9 轮那次盘点只找 `order.status = …` 这种**赋值**写法，于是漏掉了第二种写法 `db.execute(update(Order).values(status=…))` —— 而 `driver-ack`（DISPATCHED → ACCEPTED）正好是第二种、**长在 API 层**。补齐两种写法后，跃迁一共 6 个：派单/接单/送达/撤销/撤回派单/退货（+ 建单时的初始状态，那不是跃迁）。第 10 轮把接单那一处也搬进 `order_flow.accept_order()`（行为一字不改：两条前置判据、CAS 条件、失败文案逐字一致，只有 403 的角色判断留在端点）。**判据**：`grep "status = OrderStatus"` 现在只命中 `order_flow.py` 一个文件。⚠️ 端点虽有 `with_for_update()`，但 SQLite 不认 `FOR UPDATE` —— 这处覆盖**本地原本测不出来**（本仓库那条教训：只在生产有效的保护等于本地测不出来）。用例 2 条：`test_returned_transition_is_a_conditional_update`（用「陈旧快照 + 另一个 session 撤销」造出并发窗口，断言覆盖被挡住、库里仍是 CANCELLED）、`test_mark_returned_refuses_orders_never_delivered`。**反向验证**：把 CAS 里的 `status == DELIVERED` 去掉 → 两条用例当场红。退货现有 12 条用例全绿；后端 993 通过 / 3 红（那 3 条是另一会话的 reports 重构）。**判据**：`_check_status_gate_locking.py` §E 新增「订单状态的写入只出现在 `services/order_flow.py`」（两种写法都盘；注入一处越界写入 → C/E 两条当场红，还原后 55/55）。核心改动已按规矩声明 |
| 5 | §7 | **钱：从「文件冻结」升级为显式契约**（Domain Contract） | 局部 | **第一步已完成** | `backend/app/services/money_contract.py`（**只声明、零算术**：5 个钱数 = 口径一句话 / 唯一实现站点 `文件::符号` / 消费方清单 / 「别人不许这么算」的写法）
+ `_tools/qa/_check_money_contract.py`（**43 条**，自动进必跑组 97 → 98）：逐条核对「实现站点真的定义了那个符号」「声明的消费方**真的 import 了**它」（假消费方比漏写更糟）「实现区之外没有第二种算法」「允许的例外**仍然命中**（防化石）」「契约模块自己没有算术」。
**现状证据**：五类「自己又算一遍」的写法（行金额算术 / 现金流聚合 / 运费乘除 / 提成率乘 / 计件额乘）在全后端**一处都没有** —— 这条纪律今天成立，现在有判据钉着；唯一例外是报表层按商品聚合营业额（`stats_service.py:130、200`），已在 `ALLOWED` 里写明理由（回答的是「这段时间卖了多少」，不是「这一单还欠多少」）。
**反向验证**：往 `services/message_center.py` 注入 `order.line_total + 1` → 当场报 `[order_money] services/message_center.py:19`；把契约里的符号改成不存在的名字 → 报「契约指向了不存在的东西」；禁用那条例外 → 报「允许表里有化石」。
⚠️ 顺手修正：本表原来把报告 §7/§8 的编号**写反了**（报告 §7 = 领域真相/钱契约，§8 = 状态机唯一写入口），两行已对调。⛔ 第二步（把 20 多个消费方的 import 指到契约模块）**等 `api/v1/reports.py` / `services/reports_service.py` 那两处不再被别的会话改**再做 —— 先改 import 而没有判据，等于把「哪一处是唯一实现」从代码搬回记忆 |
| 5 | §9 | 权限模型收敛（26 个权限点 / 5 个无引用） | 局部 | **已勘定（待你拍板）** | 实测（本轮）：权限点**仍然是 26 个**，**没被任何代码引用的仍然是 5 个** —— `ORDER_READ_OWN` / `ORDER_READ_ASSIGNED` / `LEDGER_READ_OWN` / `LEDGER_READ_ALL` / `NOTIFICATION_READ`，全是「按范围读」那一类：端点实际用的是 `CurrentUser`（只要求登录）+ **函数体内自己按角色过滤** —— 也就是说权限矩阵上写着的边界，**没有任何地方在执行**。另有若干文件「端点一堆、`require_permission` 零处」：`shipper.py`（19 个端点 / 0）、`places.py`（8/0）、`expense_categories.py`（5/0）、`vehicles.py`（4/0）、`driver_settlements.py`（3/0）。两条路（**要你拍板**）：① **接上**这 5 个权限点（把函数体内的范围过滤换成声明式权限点，行为不变、边界变成可查的）；② 从 `ROLE_PERMISSIONS` **删掉**它们（诚实，但少一层保护）。⛔ 两条都要动核心区 `core/rbac.py` |
| 6 | §10 | Outbox（事务发件箱）替代「background task 直接推」 | 局部 | **第一步已完成（边界 + worker + 判据）；生产者待逐条切换** |报告点名的病：**数据库成功 → 后台任务恰好挂了 → 事件永远丢失**。本轮把「边界」立起来：**迁移 `002_outbox_events`**（表结构直接取自模型 `OutboxEvent.__table__.create(checkfirst=True)` —— 模型与迁移不可能写成两样，且可重跑；本机库已是版本 2，`migrations status` 可见）+**`core/outbox.py`**（`enqueue` **不 commit**：与业务同一个事务；`dedupe_key` 唯一；成功才标 sent；失败记 `last_error` + **数据库自增** attempts + 指数退避（5s→160s 封顶 600s）；用满 5 次放弃，不堵队头）+**worker**（`main.py` lifespan 里起 `run_forever`，处理器在**应用自己的事件循环**里 await —— socketio 的 emit 要在这个进程的循环里跑；DB 三步丢线程）+ **派发表**（未登记的事件类型**抛错**，不许静默丢）+ **`/metrics` 两个 gauge**（`sorders_outbox_pending/failed`：新边界必须自己可见）。**判据**：`_tools/qa/_check_outbox.py`（23 条，必跑组 98 → 99）盯「enqueue 里有没有 commit」「核心模块有没有 import 推送链路」「mark_failed 的放弃/退避是否齐全」「mark_sent 是否只在成功之后」「表结构与模型同源」「未登记类型是否抛错」「指标是否可见」。**反向验证 2/2**：给 `enqueue` 加一行 `db.commit()` → 当场红；把「未登记就抛错」改成 `return` → 当场红。**用例 9 条**（`tests/test_outbox.py`）——它们当场抓到一个真缺陷：本项目 sessionmaker 是 **autoflush=False**，去重查询看不见同事务里刚入队的那条 → 同一个键会写两行（`IntegrityError` 会把业务事务一起带下去）；修法是入队前 `db.flush()`（注释里写清了）。另被红线 `_check_counter_updates.py` 抓到 `attempts` 的读改写，改成数据库自增。**第 13 轮：第一个生产者已切换** —— 派单推送（`orders.assigned`）：`api/v1/orders_assignment.py` 的单条派单与批量派单两处，从「`db.commit()` 之后再 `background_tasks.add_task(_bg_push_assigned, …)`」改成「**commit 之前** `outbox.enqueue(db, "orders.assigned", …)`」，`_bg_push_assigned` 这个只为它存在的助手也一并删掉（一条链路不许两套投递）。事件由 worker 派发给 `push_events.push_order_assigned`（与原来同一个函数，行为一致，只是从"尽力而为"变成"至少一次 + 失败重试"）。真机/接口级证据：新用例走**真实接口**（货主建单 → 派单员派单 → 断言 `outbox_events` 里恰好一条 `orders.assigned`、负载是 `{driver_id, order_id}`、状态 `pending`）；`_check_notify_guardrails.py` 117/117、`_check_status_gate_locking.py` 55/55 全绿。**判据补强**：`_check_outbox.py` 现在会从源码收集所有 `outbox.enqueue` 的事件类型，逐个核对派发表里有没有处理器（漏登记＝那条事件被反复标记失败而业务侧看不出来；反向验证：撤掉 `orders.assigned` 的处理器 → 当场红）。⚠️ 连带修：新迁移让三条迁移用例里写死的「只有 001」当场红 —— 改成**从目录算**（`discover()`），这是它们本来就该有的形状。**第 14 轮：送达链路也切了** —— `orders.delivered`（推给货主 + 派单员）与 `ledger.updated`（账本有更新）：`api/v1/orders_delivery.py` 的两处 complete 端点（`complete-with-upload` 与 `complete`）从「commit 之后两个 background task」改成「**commit 之前**两条 `outbox.enqueue`」。⚠️ 换过来的**第二个好处**在这里最明显：`_apply_complete_payment_logged` 抛错时整单回滚 → 事件也跟着不存在，不会出现「通知说已送达、其实那张单没送达」（旧的写法是 commit 成功后才发，业务失败时确实不发 —— 但"commit 成功、任务挂了"那一半永远丢）。`_bg_notify_delivered` 助手连同两个已无人用的 import 一并删掉。用例 11 条（新增「一次送达 → 两条事件、负载与状态都对」走真实接口）；`_check_notify_guardrails.py` **117/117** 仍然全绿。**第 15 轮：一次切了四种事件** —— `orders.pending_pool_changed`（待派池变了，6 处调用点：单条/批量派单、拆单、建单、撤销、撤回）、`orders.revoked`（司机：派单被撤回）、`orders.recalled`（货主：这单被召回）、`orders.cancelled`（撤销：货主 + 司机，**合成一条事件两个收件人** ——原来调两次助手会让派单员收到两次池刷新）。四个已经没人调的 `_bg_*` 助手与它们的 import 一并删掉。**判据跟着搬了口径**：`_check_background_tasks.py` 原本钉着「`background_tasks.add_task` ≥ 25 处」（防扫描器空转），而 §10 正在把这些任务**按计划搬进发件箱** —— 数量会合法下降（31 → 23）。改成钉「**派发点总数** = background task + `outbox.enqueue`」（现在 38 = 23 + 15）：照样抓得住「扫描器瞎了」，但不会把「按计划搬家」判成事故。⛔ 其余链路（账本路由内的 5 处、退货申请 3 处、消息中心 5 处、代下单/改单/接单通知、导出任务）仍走 background task |
| 7 | §11 | Android 大文件按职责拆（不是按行数拆） | 少量 | 未开始 | — |
| 7 | §12 | AI 能力目录与后端权限**同源**（`_probe_read_roles` 进 CI） | 否 | 未开始 | — |
| 7 | §13 | 文档事实源自动化（会变的数字一律生成） | 否 | **已完成（两块）** | 第一块：`docs/BASELINE.md` 由脚本生成（`_capture_baseline.py`）。
第二块：**活文档里手写的「会变的数字」** —— `_tools/qa/_check_live_doc_counts.py`（27 条，自动进必跑组：96 → 97；四类能现算的数字：检查脚本数 / 端点总数 / 反向验证份数 / `orders.py` 规模）。它当场发现 5 处过期：`AGENTS.md` 写「当前 50 个脚本」（实际 97）与「155 个端点」（实际 228）、`03_BACKEND_DETAILS.md` 写 `orders.py`「1,165 行 / 23 个端点」（阶段 4 之后只剩装配说明 / 该组 25 个）、`05_TESTING.md` 写「82 个脚本」；`08_CODE_LOCATOR.md` 写「130 个端点」「只剩 33 行」与「98 份反向验证」。全部改成指向生成物/命令（**不再写数**）。⚠️ 两条边界（第一版误报过）：数字要**紧挨着**文件/工具名才算，且写了「以…为准」的**带日期历史注记**（如 `INDEX.md` 那句「2026-09-19 实测 49 份」）不许当当前值判。反向验证：把「155 个端点」塞回 `AGENTS.md`、把「108 份」塞回定位表 → 各当场 1 条红 + exit 1，还原后 27/0 |
| 7 | §14 | Android 集成测试（登录 → 导航 → 下单） | 否 | 未开始 | — |
| 7 | §14 | 前端 H5：正式"继续维护"或"正式归档"（二选一） | — | **待拍板** | 见 §4 |
| 8 | §15 | Request ID / 业务指标 / 外部监控 | 否 | **①② 已完成；③ 最小版已可跑** | ① `core/request_id.py`（纯 ASGI 中间件 + ContextVar + 日志 `[rid=…]` + `X-Request-ID` 响应头），真机实测响应头有值、5 条用例；② `core/metrics.py` + `GET /metrics`（Prometheus 文本）：能算的 **7 个** —— orders_created / assigned / delivered / cancelled、**待派池积压**（报告点名的「积压到几万」一眼可见）、ledger_entries、driver_settlements；报告点名的另外 4 个（`push_success` / `push_failure` / `AI_calls` / `AI_write_confirmed`）**如实列进 `NOT_TRACKED` 不编数**（推送成败该补在 §10 的 Outbox 里；AI 跑在 App 里、后端只看到普通业务请求）。⛔ 口径：**抓取时现算、不在业务路径上打点**（打点＝在同一件事上再造一个数，两边必然漂移），窗口一律**业务当地日**（用 UTC 分桶就是「每天有 8 小时算进前一天」）。⛔ fail-closed：`METRICS_TOKEN` 没配就一律 403。真机实测：不带口令 403 / 带口令 200，且 7 个数与库里直查逐项一致（本机 0/0/0/0/6/0/0）；6 条用例；③ `_tools/ops/_health_check.py` |
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

