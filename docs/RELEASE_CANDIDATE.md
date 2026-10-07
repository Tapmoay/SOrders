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
> ⛔ **2026-10-08 00:4x CST 的 0.2.7 同样是后端与 Android 一起发**：后端八步 `--all --go` 全过（迁移跑到 **28**）、APK `sorders-0.2.7-2026100801.apk` 上传后线上 `version.json` 已指向它 —— §一 各格已按 0.2.7 再重填一次。
>
> 生成日期：2026-09-26（§一 的发布点与运行时指纹行在 A 阶段开始时更新）；**2026-10-07 00:3x CST 发布 0.2.6 之后整张表现取重填**（Git SHA / 迁移版本 / Android 与 Backend 版本 / 两个 checksum 全是发布后从本地与生产现读的）。 **2026-10-08 00:4x CST 发布 0.2.7 之后又整张表现取重填一次**（Git SHA `fd43e1d` / 迁移 28 / Android 与 Backend 0.2.7 / 新 APK 校验和）。

---

## 一、候选里有什么（R3-05-A 点名的字段，逐条）

| 字段 | 值 | 现取命令（可复现） |
|---|---|---|
| **Git SHA** | `fd43e1d8b51bcca6b093902e5d7ea8107d9bd3e4`（**0.2.7 当前发布点**：生产 `git rev-parse HEAD` 现读；这一版含台账 L-33…L-44 ＋ L-47/L-48 ＋ L-49/L-50 共 **16 条**单，自 0.2.6 的发布点 `a31299e` 起 **39 个提交 / 18 份新增变更单**（BUG-0016、BUG-0017、CHG-0065…CHG-0080）；分支 `p` → `origin/new`，已推。⛔ 上一个发布点是 `acda0cedeac22b153b5415515b6eb616927751ec`（0.2.6）） | `git rev-parse HEAD` |
| **运行时代码指纹**（⛔ 这条比 SHA 本身更要紧） | 发布点之后还可能推**只改文档/工具**的提交 ⇒ 真正要核的是「运行时代码没变」：`git diff --stat <Git SHA>..<发布点> -- backend/` **必须为空**。✅ 0.2.7 发布时 `git diff --stat fd43e1d..HEAD -- backend/` **为空**；生产侧同一条判据由 `_prod_smoke.py --readonly` 现读通过（发布前它是 ❌「生产代码 ≠ HEAD」，本次发布把它消掉） | `git diff --stat <Git SHA>..HEAD -- backend/` |
| 提交时刻 | 2026-10-08T00:43:52+08:00 | `git log -1 --format=%cI` |
| **DB migration version** | **29**（⛔ 这是**仓库头**，不是生产现状：0.2.7 发布时生产停在 **28**，本轮的 `029_ai_operation_log` 要等下一次发版 `--step migrate` 才会跑。`029_ai_operation_log` 是CHG-0082 / 台账 L-52（AI 操作流水）：**新建** `ai_operation_logs` 一张表 —— 谁 / 何时 / 哪个动作 / 成没成 /后端给的原因（`user_id` 可空 ＋ `action` ＋ `method` ＋ `path` ＋ `status_code` ＋ `ok` ＋ `error`（≤500 字，500 是写入侧的截断上限） ＋ `request_id` ＋ `duration_ms` ＋ `created_at`）；写入者是 ASGI 中间件`core/ai_operation.py`，用**独立会话**落库 ⇒ 业务事务回滚时「失败那一行」仍然留得下（那正是最该看见的一行）；只记带 `X-SOrders-Origin: ai` 的请求，读端点只有派单员持 `OPERATION_LOG_READ`；可重跑。0.2.7 那次发版把**025_order_discount → 028_order_product_shipper_price** 四条跑掉了（生产 `-m app.migrations status --json`实测「当前版本 28 == 当时的仓库迁移头 28；待跑 0 / 漂移 0 / 陌生版本 0」；0.2.6 时生产停在 **24**）。这四条的字段口径见历史记录：025 = `orders` 七格折扣快照 ＋ `products.no_discount`；026 = `users.downstream_ledger_enabled`；027 = **新建** `shipper_prices`（三层价）；028 = `order_products.shipper_unit_price`（可空、⛔ 无默认值、不回填）—— 四条都可重跑） | `python _tools/ops/_prod_smoke.py --readonly` |
| **Android 版本** | 产品 **0.2.7**（唯一来源＝仓库根 `VERSION`）＋构建号 **2026100801**（日期式 `yyyyMMdd * 100 + 当日序号`；这就是本次包的 `versionCode`） | `Get-Content VERSION` ／ `android/app/build.gradle.kts` |
| **Backend 版本** | `app_version` = **0.2.7**（`config._repo_version()` 现读同一个 `VERSION`；发布后 `/health` 实测 `{"status":"ok","version":"0.2.7","redis":"ok","pricing":{"canary_percent":30,"resolver":"PricingContract v2 @ extensions.pricing"}}`）；⚠️ OpenAPI `info.version` 仍是 `0.1.0`（没跟产品版本走，如实记） | `backend/app/config.py` |
| **Frontend 版本** | ⛔ **没有**：`frontend/`（Vue3 旧 H5）已不在工作区，本轮不发布前端 | `git ls-files frontend`（0 个文件） |
| **requirements lock** | ⛔ **没有 lock** —— R3-07d 决策②「本轮不锁」（保持开区间）；改用**生产真实 freeze 指纹**当基准（0.2.7 现读 `dcfad65fe4b3823f`，49 个包） | `docs/DEPENDENCY_DECISION.md` §七 |
| **config checksum** | systemd unit **`7450d600ccfa8b86`**（`systemctl cat <enabled 的 sorders-api*.service>` 的 sha256 前 16 位，发布后现取 —— 与 0.2.6 同值，本次没动 unit）；nginx 配置 **`98dd5c2f1ee050630048ffa356cf754b`**（`nginx -T` 的 sha256 前 32 位，发布后现取 —— 同值）；`backend/requirements.txt` `4f6f3ad341928200`（本地文件 sha256 前 16 位，本次未变） | `python _tools/ops/_prod_smoke.py --readonly` |
| **artifact checksum** | `app-phone-release.apk` → 线上 `sorders-0.2.7-2026100801.apk`：**45,309,605 字节 / `2957723DCD3416E6`**（sha256 前 16 位；2026-10-08 00:5x CST 上传；`version.json` 记 `version 0.2.7 / versionCode 2026100801 / size 45309605`；HTTP 探包 `206` ＋ `Content-Type=application/vnd.android.package-archive` ＋ `Content-Range=bytes 0-1023/45309605`；APK 签名指纹 `8AAC1B5778F8DDCF` 与线上旧包一致 ⇒ 老用户能覆盖安装）；⛔ 上一版是 0.2.6 的 45,178,533 字节 / `48C6F388B247FC6E`；后端**没有独立产物**（源码部署，SHA 就是它的标识） | `Get-FileHash android/app/build/outputs/apk/phone/release/*.apk` |

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

### 0.2.7 发布（2026-10-08 00:4x CST，只读采集）

| 项 | 值 |
|---|---|
| 生产当前提交 | `fd43e1d8b51bcca6b093902e5d7ea8107d9bd3e4`（＝ 发布点；发布前是 `bd818eb7`，即 0.2.6 的老对象 `acda0ce`） |
| 服务 | `sorders-api-a.service`(8111) ＋ `sorders-api-b.service`(8112) 滚动重启后**都 `is-active=active`**、各自 `/health` 200、经 nginx 入口 401（＝有活上游）、两台 effective config 指纹都 `canary_percent=30`（与 `.env` 一致） |
| 结构版本 | 发布前 **24** → `--step migrate` 跑掉 **025 / 026 / 027 / 028** → `-m app.migrations status --json`：**当前 28 == 仓库迁移头 28，待跑 0 / 漂移 0 / 陌生版本 0** |
| 库 / 盘 | 13.6 MB / **58 张表**（0.2.6 时 57）；上传 2119 文件 / 189M；磁盘 66%（可用 13G）；备份 36 份 / 2.2G |
| 运行环境 | 生产 venv Python **3.11.13** / **49 个包**（freeze `dcfad65fe4b3823f`）；MySQL 8.0.44；Redis 6.2.20；nginx 1.20.1 |
| 本次的备份 | `/opt/sorders-backup/pre_release/20261007T164408Z`（`db.sql.gz` 537,533 B ＋ `uploads.tar.gz` 108,179,142 B / 2119 文件，sha256 校验通过；清单 `_tools/backup/manifests/20261007T164419Z-pre_release.json`，库行数 orders=2460 / ledgers=4656 / users=63 / products=37 / tables=57） |
| 只读烟测 | `_prod_smoke.py --readonly`：**31 通过 / 3 已批准告警 / 0 不一致**（发布前是「29 通过 / 3 告警 / **2 不一致**」—— 那两条「生产代码 ≠ HEAD」「库结构 ≠ 28」正是本次消掉的）；已批准告警仍是 Redis 设口令 / MySQL 时区 UTC / 生产路由数 202 ≠ 快照 167 |

⛔ **本次后端与 Android 一起发**：八步（backup → stage → migrate → verify → start → health → smoke → business）全过、`release-exit=0`（日志 `_tmp/release_027.txt`）。
✅ 第 8 步 business 是**人工有限写烟测**（`_release.py` 故意不自动化）—— 2026-10-08 01:0x CST **已补做并留痕**：`python _tools/ops/_canary_live_write.py` 三阶段全绿（脚本自检 **8/8**，三次都拿到 `RESULT|OK`、退出码 0）：`--phase create` 建演练单 **id=20904 / SO202610087129642729**（送货地址带标记「R4 演练单」，运费 66.00，派单后 `DISPATCHED`）→ `--phase refreight --order 20904`（运费改 **77.00**，`pricing kind = legacy_client`）→ `--phase cancel --order 20904`（状态 `CANCELLED`，**撤销而不是删除**）。

**APK 这一次**（0.2.7 / 2026100801）：`assemblePhoneRelease`（Gradle 8.9 ＋ `-PapiBaseUrl=https://8.145.40.22`，⛔ 没改 `android/local.properties`）→ `check_phone_apk.py` ✅（versionName 0.2.7 / versionCode 2026100801 / 含 `arm64-v8a` 与 `armeabi-v7a` / 编译进包的 BuildConfig 是生产地址）→ `publish_apk.py` 上传 `sorders-0.2.7-2026100801.apk` ＋ 刷新 `sorders-latest.apk` ＋ 重写 `version.json`，回读 `version 0.2.7 / versionCode 2026100801 OK`、探包 `206`。
⚠️ **这一趟踩到一个坑（发布后已修）**：`publish_apk.py --note` 的中文说明在 **Windows PowerShell 5.1** 下被 `Get-Content` 按 **gb2312** 解码 ⇒ 写进线上 `version.json` 的 `note` 是乱码；发现后用 base64 直写线上文件修正、经 HTTP 回读**逐字一致**（0.2.6 那份 note 也呈同类乱码特征）。治本（给脚本加 `--note-file`／写盘前编码自检）记入台账待拍板。

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

### 2026-10-08 复核（0.2.7 发布之后）

1. ✅ **发布已执行**：`python _tools/deploy/_release.py --all --go` 八步全过、`release-exit=0`（后端与 Android 一起发）；
2. ✅ 生产**就在发布点** `fd43e1d8b51bcca6b093902e5d7ea8107d9bd3e4`，`/health` version `0.2.7`、结构版本 **28**（仓库头 = 生产现状：待跑 0 / 漂移 0 / 陌生版本 0）；
3. ✅ 更新链现读：线上 `version.json` = `0.2.7` / `2026100801` / `sorders-0.2.7-2026100801.apk`，`_tools/deploy/_check_update_flow.py` **43/43**；
4. ✅ 第 8 步 business 的**有限写烟测已于 2026-10-08 01:0x CST 补做**（用户点头后才跑）：带硬限制的 `_tools/ops/_canary_live_write.py`（只肯动 R4 演练单、撤销不删除）三阶段全绿 —— 建单 **20904** → 改运费 **77.00** → **CANCELLED**，自检 8/8，详见 §三「0.2.7 发布」那段末尾；
5. ⚠️ 新增一条已知坑：线上 `version.json` 的 `note` 中文在 **Windows PowerShell 5.1** 下会被 `Get-Content` 的 gb2312 解码打乱（本次已用 base64 直写修正，治本待定）。
