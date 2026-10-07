# R3 Release Candidate（R3-05-A · 发布候选记录）

> **这份文档是什么**：第三轮指南 §十六（R3-05-A）要求的候选记录 —— 「不要 main → production，先生成
> R3 Release Candidate 并记录 Git SHA / DB migration version / Android version / Backend version /
> Frontend version / requirements lock / config checksum，并做 artifact checksum」。
>
> **状态**：✅ **记录齐全**（每个字段都是**现取**的，命令写在表里，⛔ 没有一个是手抄的）。
>
> ⭐ **2026-09-26：A 阶段（生产发布）已获用户放行并执行；随后 B（多实例）与 C（五个故障演练）也先后放行并执行完毕**
> （演练四条通过、一条抓到真缺陷，见 `docs/R3_FAILURE_DRILL_EVIDENCE.md`）—— ⛔ 本文档只负责**候选与顺序**，不记录「跑到哪了」。
> 执行记录（每一步的结论与证据）在 `docs/R3_PROGRESS.md` 的 R3-05 一节 —— ⛔ 本文档只负责**候选与顺序**，
> 不负责记录「跑到哪了」（那会变成第二份真相）。
> ⛔ 另：R3/R4 那两次 A **只发布后端**（源码部署，SHA 就是它的标识）。**2026-10-06/07 的 0.2.6 这一次后端与 Android 一起发** ——
> 下面 §一 里的 APK 校验和已经是这次真发出去的包（`sorders-0.2.6-2026100701.apk`，线上 `version.json` 已指向它）。
>
> 生成日期：2026-09-26（§一 的发布点与运行时指纹行在 A 阶段开始时更新）；**2026-10-07 00:3x CST 发布 0.2.6 之后整张表现取重填**（Git SHA / 迁移版本 / Android 与 Backend 版本 / 两个 checksum 全是发布后从本地与生产现读的）。

---

## 一、候选里有什么（R3-05-A 点名的字段，逐条）

| 字段 | 值 | 现取命令（可复现） |
|---|---|---|
| **Git SHA** | `acda0cedeac22b153b5415515b6eb616927751ec`（**0.2.6 当前发布点**：生产 `git rev-parse HEAD` 现读；⚠️ 2026-10-07 00:3x 给这两条发版/修复提交的标题补上了可回溯编号，`f488a52`→`03bde4b`、`bd818eb`→`acda0ce`（**树内容一字未动**，重跑 `git diff <新> <旧>` 为空；生产机上 checkout 的还是老对象，内容一致）；这一版含台账 L-01…L-32 的 23 张单（`72f141f` 那一刀）＋ `024` 迁移的 MySQL 兼容性修复；分支 `p` → `origin/new`，已推。⛔ 上一个发布点是 `448dbb3e743c4b96b238d009a2c6ca46a68f441a`（R4）） | `git rev-parse HEAD` |
| **运行时代码指纹**（⛔ 这条比 SHA 本身更要紧） | 发布点之后还可能推**只改文档/工具**的提交 ⇒ 真正要核的是「运行时代码没变」：`git diff --stat <Git SHA>..<发布点> -- backend/` **必须为空**。⚠️ 发布点落位之后若又推过**只改工具/文档**的提交，这个 diff **不为空**是正常的 —— 判据是「`backend/` 下没有差异」，工具与文档不算运行时。✅ 0.2.6 发布时 `git diff --stat acda0ce..HEAD -- backend/` **为空**（发布点就是当前生产代码） | `git diff --stat <Git SHA>..HEAD -- backend/` |
| 提交时刻 | 2026-10-07T00:18:37+08:00 | `git log -1 --format=%cI` |
| **DB migration version** | **26**（`001_baseline` … `026_user_downstream_ledger`：CHG-0076 / 台账 L-39 给 `users` 加一格 `downstream_ledger_enabled`（`BOOLEAN NOT NULL DEFAULT 1`：批发商在「我的 → 管下游的账」里自己决定要不要管下游货主的账，关掉 ⇒ 那本账的收入侧恒 0、核销读端点返空、三个写端点 403，⛔ 不是 403 整页；老库回填 true）；此前 `001_baseline` … `025_order_discount`：CHG-0071 给 `orders` 加七格折扣快照（`discount_kind` / `discount_value` / `discount_amount` / `discount_lines`(JSON，每项 `{line_id, before, after}`) / `discount_reason` / `discount_by_id` / `discount_at`）、给 `products` 加一格 `no_discount`（商品「不参与打折」：打折时**自动跳过**这些行、显式勾中则 4xx ⛔ 不静默过滤）；八格全部可空、**不回填**、老单全 NULL = 「这一单没打过折」；折扣钱落在行金额 `order_products.line_total` 上（`services/order_discount.py` 是唯一算法）；`001_baseline` … `024_product_visibility_targets`：FEAT-0009 给 `shipper_addresses` 加一格 `category` + 索引；FEAT-0010 给 `users` / `vehicles` 各加一格 `category` + 各自索引；BUG-0006 给 `users` 加四格（`session_revoked_reason` / `session_revoked_at` / `session_revoked_version` / `last_login_at`，被顶号/被停用/改密码/过期四种原因落库可查）；BUG-0007 给 `driver_settlements` 加两格（`bill_ids` / `adjustment`：建单当刻把明细锁进单里、手工改额只记差额，恒等式 `amount == 明细合计 + adjustment`）；FEAT-0012 给 `vehicles` 加四格（`purchase_price` / `purchase_date` / `useful_life_years` / `residual_rate`：折旧的四个输入，折旧额本身**不进库**）；FEAT-0013 **新建** `purchase_orders` 与 `purchase_order_items` 两张表（采购单据：把「库存流水 ＋ 成本价 ＋ 供应商应付」绑进同一个事务，⛔ 不拿历史入库流水反推单据）；FEAT-0014 **新建** `invoices` ＋ `invoice_purchase_orders` ＋ `invoice_ledgers` 三张表（发票台账：销项 / 进项共用一张票头，进项票挂采购单、销项票挂账本条目；⛔ 不回填历史的 `shipper_receipts.invoiced`，过去没有票的期间不凭空补票）；FEAT-0015 给 `arrears_units` 加一格 `credit_limit`（挂账单位的信用额度上限：NULL = 不限额、0 = 一点都不许赊，它只作**比较门槛**——⛔ 不参与应收/已收/欠款的任何加减，那三个数全部来自 `order_money`）CHG-0039 给 `orders` 加一格 `shipper_status_hold`（**货主可见状态的冻结值**：派单员把已派的单**静默退回派单池**时，真实状态必须真的回到 `PENDING_DISPATCH`（池子/计数/批量派单全部复用），而货主那一侧仍显示被收回那一刻的状态 —— 出参只对货主覆写、货主档位查询对冻结值感知；重新派出时 `assign_driver` 的 CAS 把它一起清成 NULL；可空、不回填、不加索引）；CHG-0048 给 `shipper_contacts` 加一格 `remark`（联系人自己的备注：**只有本人看得见**，`""` = 没写；选联系人时**只在地点备注还空着时**带进地点备注，带出之后以地点那一行为准、⛔ 不做联动；不回填、不加索引）；024 给 `user_product_visibility` 加两格 `category_name`（分类维；空串 = 「未分类」）/ `mode`（allow｜deny），把 `product_id` 改成 **`NULL` 可写**（分类行要 `product_id IS NULL`），唯一键从 `(user_id, product_id)` 扩成 `uq_upv_category(user_id, category_name, mode)`，旧约束 `uq_user_product_visibility` 原样保留（CHG-0062 / 台账 L-23：可见范围从「只认单品」扩成「分类 ＋ 单品、授权 ＋ 排除」；⚠️ 这条第一次上生产时挂在 `CREATE UNIQUE INDEX IF NOT EXISTS` 上 —— SQLite 认、**MySQL 不认**，报 `(1064, "... near 'IF NOT EXISTS uq_upv_category ON ...'")`，把库留在「两列已加、索引没建、没记账」的半截状态；修成 `_indexes(engine)` 先判存在再建之后原地重跑跑通，老行一行没动、`product_id` 变可空）—— 一事一迁移、十二笔都只加列或只建表、不回填。名册表 `route_categories` / `user_categories` / `vehicle_categories` 都由 `create_all` 建，不在这条链上。⚠️ 本行记的是**仓库 head**；生产上跑到哪一版以 `-m app.migrations status` 为准） | `python -c "import sys;sys.path.insert(0,'_tools/ops');import _prod_smoke as s;print(s.repo_migration_head())"` |
| **Android 版本** | 产品 **0.2.6**（唯一来源＝仓库根 `VERSION`）＋构建号 **2026100701**（日期式 `yyyyMMdd * 100 + 当日序号`；这就是本次包的 `versionCode`） | `Get-Content VERSION` ／ `android/app/build.gradle.kts` |
| **Backend 版本** | `app_version` = **0.2.6**（`config._repo_version()` 现读同一个 `VERSION`；发布后 `/health` 实测 `{"status":"ok","version":"0.2.6","redis":"ok",...}`）；⚠️ OpenAPI `info.version` 仍是 `0.1.0`（没跟产品版本走，如实记） | `backend/app/config.py` |
| **Frontend 版本** | ⛔ **没有**：`frontend/`（Vue3 旧 H5）已不在工作区，本轮不发布前端 | `git ls-files frontend`（0 个文件） |
| **requirements lock** | ⛔ **没有 lock** —— R3-07d 决策②「本轮不锁」（保持开区间）；改用**生产真实 freeze 指纹**当基准 | `docs/DEPENDENCY_DECISION.md` §七 |
| **config checksum** | systemd unit **`7450d600ccfa8b86`**（`systemctl cat <enabled 的 sorders-api*.service>` 的 sha256 前 16 位，发布后现取）；nginx 配置 **`98dd5c2f1ee050630048ffa356cf754b`**（`nginx -T` 的 sha256 前 32 位，发布后现取）；`backend/requirements.txt` `4f6f3ad341928200`（本地文件 sha256 前 16 位，本次未变） | `python _tools/ops/_prod_smoke.py --readonly` |
| **artifact checksum** | `app-phone-release.apk` → 线上 `sorders-0.2.6-2026100701.apk`：**45,178,533 字节 / `48C6F388B247FC6E`**（sha256 前 16 位；2026-10-07 00:21 CST 上传，`version.json` 记 `version 0.2.6 / versionCode 2026100701 / size 45178533`，HTTP 探包 206 + `Content-Type=application/vnd.android.package-archive`）；⛔ 上一版是 0.2.5 的 44,490,405 字节 / `e7823ffeedf5f3fb`（2026-09-23）；后端**没有独立产物**（源码部署，SHA 就是它的标识） | `Get-FileHash android/app/build/outputs/apk/phone/release/*.apk` |

---

## 二、CI 证据（这份候选被机器验过）

### R4 这一次（2026-09-27）

| 提交 | 工作流 | 运行号 | 结论 |
|---|---|---|---|
| `b681fec`（R4-12，本次发布点的**上一个**提交） | Gate | `76` | ✅ success（六个实质作业全绿） |
| `b681fec` | Tests (Parallel) | `74` | ✅ success |
| **常闸 · 安卓端到端** | Gate 的一个作业 | — | ✅ **这一次真的跑了并判定通过**（注解里只有版本弃用提醒，**没有**那两条「带理由跳过 / 这次没跑」） |
| `ca5e49f`（发布点本身） | Gate / Tests | — | ⏳ 与本文档同一批推送，由它自己那次运行覆盖 |

### R3 那一次（2026-09-26，留档）

| 提交 | 工作流 | 运行号 | 结论 |
|---|---|---|---|
| `684a9374`（当时的候选） | Gate | `36231434911` | ✅ success |
| `684a9374` | Tests (Parallel) | `36231434912` | ✅ success |
| `cc949bf5` | Gate / Tests | `36230516735` / `36230516664` | ✅ / ✅ |

⛔ 这几行是**人读的记录**，机器判据只保证「候选 SHA 是本仓库真实提交」（见台账第 1 条的复现命令）。

---

## 三、目标环境现状（**只读**采集）

### 0.2.6 发布（2026-10-06 16:2xZ 起，只读采集）

| 项 | 值 |
|---|---|
| 生产当前提交 | 发布前工作区已 stage 到 `03bde4b`（0.2.6 的版本号提交，服务跑的还是 0.2.5 那版代码）→ 本次 stage 到 `acda0cedeac2` |
| 服务 | `sorders-api-a.service` + `sorders-api-b.service`，滚动重启后**都 active**、`/health` 200（8111 / 8112 都 200）、经 nginx 入口全程有活上游；effective config 指纹两台一致：`canary_percent=30`（与 `.env` 的 30 相符） |
| 结构版本 | ⚠️ 发布**前**是「23 ＋ 半截」（`024` 第一次跑挂掉：两列已加、索引没建、没记账）→ 发布**后** `-m app.migrations status --json`：**当前 24 == 仓库迁移头 24，待跑 0 / 漂移 0 / 陌生版本 0**；库里实测 `product_id` 可空、`uq_upv_category` 在、老约束在、行数 11 一行没丢 |
| 库 | 13.5 MB / 57 表；发件箱 待发 0 / 已发 223 / 放弃 0 |
| 磁盘 | 66%（25G / 40G，剩 13G）；备份 36 份 / 2.2G；最近一次 **0.0 小时前** |
| 健康检查 | 6 项正常 / **2 项已知已接受的证书告警** / 0 失败（退出码 1 = 只有已知告警，符合放行口径） |
| 上传 | `/opt/SOrders/backend/uploads`：2119 个文件 / 189M |
| 本次的备份 | `/opt/sorders-backup/pre_release/20261006T161920Z`（`db.sql.gz` 538,744 B ＋ `uploads.tar.gz` 108,019,355 B / 2119 文件，sha256 通过；清单 `_tools/backup/manifests/20261006T161931Z-pre_release.json`）—— 这是 §五 回滚 B 的那个 dump |

⛔ **本次后端与 Android 一起发**：八步（backup → stage → migrate → verify → start → health → smoke → business）全过、`release-exit=0`；
只读烟测 `_prod_smoke.py --readonly`：**ERROR 0 条 / 未批准告警 0 条 / 已批准告警 3 条**（Redis 设了口令；MySQL 时区口径是 UTC；生产路由数 = 仓库最近一次快照）。
⚠️ 第 8 步 business 是**人工有限写烟测**（脚本故意不自动化）—— 本次**尚未逐条做**，要按 `docs/PRODUCTION_ACCEPTANCE.md` §三 走一遍并留痕。

### R4 发布前（2026-09-27 01:5xZ）

| 项 | 值 |
|---|---|
| 生产当前提交 | `bb671565`（R3-06 修复版）—— ⛔ **落后发布点 4 个提交** |
| 服务 | `sorders-api-a.service` + `sorders-api-b.service` 两个实例，**都 active**；`/health` 200（8111 / 8112 都 200）；version `0.2.4` |
| 结构版本 | **8**（`operation_log_command_id`）→ 本次升到 **9**（`freight_rule_snapshot`） |
| 库 | 11.8 MB / 48 表；发件箱 待发 0 / 已发 27 / 放弃 0 |
| 磁盘 | 32%（12G / 40G，剩 26G）；备份 21 份 / 1022M；最近一次 **1.4 小时前** |
| 健康检查 | 6 项正常 / **2 项已知已接受的证书告警** / 0 失败（退出码 1 = 只有已知告警，符合放行口径） |
| 生产与候选不一致 | **2 项**（生产停在 `bb671565`）—— 那正是发布这一步要消除的东西 |

⛔ **本次只发布后端**（源码部署，SHA 就是它的标识），而且**只改结构 + 记录事实**：
加一列 `orders.freight_rule_snapshot`（可空、⛔ 不回填），**不改任何算法、不改任何金额**。

**回滚性质（发布前就查过，不是事后许诺）**：这条迁移是**纯加列**。旧代码在带新列的库上照常跑
（SQLAlchemy 按列名取列，不做 `SELECT *`），所以回滚 = 回退代码 + **保留这一列**即可；
新列里装的是来源凭据，不参与任何金额计算。

### R3 那一次（2026-09-26，留档）

| 项 | 值 |
|---|---|
| 生产当前提交 | `648fbf8`（2026-09-23T09:02:55+08:00，分支 `new`）—— ⛔ **落后候选 293 个提交** |
| 服务 | `sorders-api` active，自 2026-09-23 08:58:54 起未重启（NRestarts=0） |
| `/health` | 200，响应 `{"status":"ok","version":"0.2.0","redis":"ok"}`（⚠️ 旧硬编码版本 0.2.0，候选是 0.2.4） |
| 主机 | Alibaba Cloud Linux 3.2104 U13，2 核 / 1870 MB，已开机 93 天 |
| 运行时 | Python **3.11.13**（候选开发机是 3.12）；MySQL **8.0.44**；Redis **6.2.20**；nginx **1.20.1** |
| 依赖 | 49 个包；**15/15 运行依赖落在声明区间内**（`cryptography` **43.0.3**）；9 条开发依赖没装（正常） |
| 数据库 | 44 张表 / 11.6 MB；orders 2402 / ledgers 4648 / users 60 / products 37；⚠️ `time_zone = SYSTEM` |
| 结构版本 | ⛔ **没有** `schema_versions` 表（版本化迁移还没上生产）；⛔ 没有 `outbox_events`；`operation_logs` 没有 `request_id`/`command_id` 列 |
| 上传 | `/opt/SOrders/backend/uploads`：2115 个文件 / 187M |
| 磁盘 | 40G 中已用 29%（可用 27G） |
| 备份 | `/opt/sorders-backup`：10 份库备份 / 208M，最近一次 1.1 小时前 |
| nginx | 单后端 `proxy_pass http://127.0.0.1:8000`；**没有** `upstream` / 没有失败摘除 |

完整原始事实：`docs/R3_PROD_READONLY_EVIDENCE.md`。

---

## 四、发布顺序（R3-05-B：**先迁移、后应用**）

⛔ 顺序不许调：R3-01 之后应用**启动时会核对结构**（`assert_schema_ready()`），库没准备好会**拒绝启动**
——这正是「restart systemd → hope」被禁掉的原因。

| # | 步骤 | 命令 | 期望 | 失败怎么办 |
|---|---|---|---|---|
| 1 | **备份**（必做，先备份再动） | `python _tools/backup/_pre_release.py --note "R3-05 发布 <SHA>"` | 库 dump + 上传文件 + 清单；记下 dump 路径与 sha256 | 备份失败 → **停止发布**（没有回滚点就不许往前走） |
| 2 | **代码落位**（⭐ 2026-09-26 补） | `python _tools/deploy/_release.py --step stage --go`（生产上 `git fetch origin` → `git checkout <SHA>`，**⛔ 不重启服务**） | 生产 `git rev-parse HEAD` == <SHA>，且 `app/migrations` 这个包**在**了；服务仍 active（跑的还是旧代码）| 失败 → 停止（服务与库都还没被动过；要退只需 checkout 回旧 SHA）|
| 3 | **迁移**（唯一入口） | `python _tools/deploy/_release.py --step migrate --go`（它执行生产上的 `cd /opt/SOrders/backend && .venv/bin/python -m app.migrations upgrade`） | 版本 0 → 8；`schema_versions` 出现 8 行 | 失败 → **不启动**，按第 5 节「前向修复」或从 dump 恢复 |
| 4 | **验证结构** | `.venv/bin/python -m app.migrations status` | 「当前版本：8 / 待跑：0 条」 | 与期望不符 → 不启动 |
| 5 | **启动新后端（滚动重启）** | `python _tools/deploy/_release.py --step start --go` —— 再核一次 `checkout <SHA>`，然后**逐个**重启 `systemctl list-unit-files 'sorders-api*.service' --state=enabled` 里的每个 unit；每重启一个就核 `is-active` ＋ 该实例 `/health` ＋ **经 nginx 的入口仍有活上游** | 全部实例：`is-active` = active 且 `/health` = 200 且滚动全程入口有活上游 | 任一实例不 active / health 非 200 / 入口拿不到活上游 → 停下看 `journalctl -u <那个 unit>`；回第 5 节 |

> ⛔ **2026-09-26 修的口径漂移**：这一步原来写死 `systemctl restart sorders-api`。B 段把生产换成「两个 unit（`sorders-api-a` :8111 / `sorders-api-b` :8112）+ nginx upstream」之后，那句话就变成「**在重启一个已经停用的 unit**」—— 命令会「成功」返回、而 `is-active` 不是 active。现在它从**系统里实际 enabled 的 unit** 取目标（⛔ 不硬编码 unit 名、也不硬编码端口），并且**滚动**重启（一起重启会让 nginx 出现 `no live upstreams`，等于把拓扑唯一的冗余丢掉）。
| 6 | **体检** | `python _tools/ops/_health_check.py` | 退出码 0（或只有「已知/已接受」的证书告警） | 退出码 2 → 立刻回滚 |
| 7 | **只读烟测** | `python _tools/ops/_prod_smoke.py --readonly` | 退出码 **0**（现状健康 **且**与这一版代码一致） | 退出码 2 → 回滚；退出码 1 → 看是哪几项不一致 |
| 8 | **业务烟测（有限写）** | `docs/PRODUCTION_ACCEPTANCE.md` 里「需要写权限」的那几项 | 逐条按那份清单走 | 任何一条不符合 → 回滚或前向修复 |

### 四·补 为什么第 2 步是**执行前**补上去的（⛔ 不是失败之后绕过去的）

第一次发布时，生产上**没有** `app/migrations` 这个包（只读实测 `ls /opt/SOrders/backend/app/migrations`
→ No such file）——而迁移的唯一入口 `-m app.migrations upgrade` **正是这个包提供的**。
所以原方案里「第 2 步迁移」在生产上必然以 `No module named app.migrations` 失败，
而那不是数据问题、是**顺序问题**：代码不先到位，迁移就没得跑。

修法是把顺序补对（`stage` → `migrate` → `verify` → `start`），而不是在失败之后临时
手动 `git checkout` 一下再重跑 —— 后者会让「代码落位」这个状态**不进任何记录**，
出了事分不清是「代码没落位」「迁移失败」还是「服务起不来」。⛔ 这条纪律就是本文件存在的理由。

---

## 五、回滚 / 前向修复（R3-05 第 8 条退出条件）

### 5.1 什么时候回滚（触发条件，命中任一条就动手）

1. 第 4 步起不来，或起来后第 5/6 步退出码 **2**；
2. 第 7 步里出现**业务数据错**（钱算错 / 状态走错 / 权限漏）——这类**不许**「先观察一下」；
3. 迁移把库里结构改坏（第 3 步对不上，或迁移中途报错）。

### 5.2 回滚 A：代码回退（不动库）

```bash
git -C /opt/SOrders checkout 648fbf8134c4ffcae86e698255fdf2427ded71c2   # 上一个已知可用提交（2026-09-23）
systemctl restart sorders-api
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health      # 期望 200
```

⚠️ 只在**库结构兼容**时可行（迁移是加列/加表，旧代码通常还能跑）；不兼容就走 5.3。

### 5.3 回滚 B：库回滚（用第 1 步的 dump）

```bash
# 生产上：先停服务，再按 _tools/backup/README.md 的恢复流程恢复第 1 步那份 dump
systemctl stop sorders-api
bash _tools/backup/_restore.sh <dump 路径> --i-know     # ⛔ 不带 --i-know 只肯往 sorders_drill_* 恢复
systemctl start sorders-api
```

⛔ 恢复会**丢掉 dump 之后写入的数据**（发布窗口里的业务操作）——所以发布要挑低峰，并事先告诉使用者。

### 5.4 前向修复（比回滚更安全的一种情形）

如果问题**小而明确**（例如某个接口 500、某段日志刷屏），且**数据没错**：宁可**再推一个小提交**修它，
也不要回滚（回滚会把已经正确落库的数据一起丢掉）。判据：数据没错 + 只影响一个功能 + 能在 30 分钟内修完。

### 5.5 回滚之后要做什么

1. 跑 `python _tools/ops/_health_check.py` 与 `python _tools/ops/_prod_smoke.py --readonly`，两条都要给出结论；
2. 把「哪一步失败、报什么、怎么处置」写进 `docs/R3_PROGRESS.md`（⛔ 不写「已恢复」三个字就完事）；
3. 如果这次失败暴露了**判据看不见的东西**，按禁做 #17 先想边界解法，再决定要不要加检查。

---

## 六、⛔ 这份记录里**还没有**的东西（R3 当时留档；2026-10-07 复核见下）

1. ⛔ **发布没有执行**：第 1–7 步一步都没跑（要写许可）；上面所有「期望」都是**计划**，不是结果；
2. ⛔ 生产还停在 `648fbf8`（落后 293 个提交），所以「生产跑过这一版代码」**没有发生**；
3. ⛔ `_tools/deploy/_release.py`（把第 1–7 步串起来的那支脚本）**已经写好了**（2026-09-26），但它**只在本机跑过 `--plan` / `--selftest` / 被护栏拒绝的那一次** —— ⛔ 一次都没在生产上真跑过；
4. ⛔ APK 的 checksum 记的是**上一次发布**那个包；本轮若只发后端，APK 不重打（要重打就重算这一格）。

### 2026-10-07 复核（0.2.6 发布之后）

1. ✅ **发布已执行**（且不止一次：R3-05-A 之后 R3 的 C 段与 R4、以及本次 0.2.6）—— 本次 `python _tools/deploy/_release.py --all --go` 八步全过、`release-exit=0`；
2. ✅ 生产**就在发布点** `acda0cedeac22b153b5415515b6eb616927751ec`，`/health` version `0.2.6`、结构版本 `24`；
3. ✅ `_tools/deploy/_release.py` 已在生产真跑过（本次即一次；R3/R4 也跑过）；
4. ⚠️ 第 8 步 business 的**有限写烟测仍是人工**、本次**尚未做**（脚本故意不自动化）—— 见 §三「0.2.6 发布」那段末尾。
