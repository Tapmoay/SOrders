# R3 Release Candidate（R3-05-A · 发布候选记录）

> **这份文档是什么**：第三轮指南 §十六（R3-05-A）要求的候选记录 —— 「不要 main → production，先生成
> R3 Release Candidate 并记录 Git SHA / DB migration version / Android version / Backend version /
> Frontend version / requirements lock / config checksum，并做 artifact checksum」。
>
> **状态**：✅ **记录齐全**（每个字段都是**现取**的，命令写在表里，⛔ 没有一个是手抄的）；
> ⛔ **发布本身没有做** —— 备份 / 迁移 / 启动 / 体检全是**写操作**，按禁做 #13/#14 要用户单独许可。
> 生成日期：2026-09-26。

---

## 一、候选里有什么（R3-05-A 点名的字段，逐条）

| 字段 | 值 | 现取命令（可复现） |
|---|---|---|
| **Git SHA** | `684a9374d7333bc513ed0333cfa7e28198f437c7`（分支 `p` → `origin/new`，已推） | `git rev-parse HEAD` |
| 提交时刻 | 2026-09-26T16:59:56+08:00 | `git log -1 --format=%cI` |
| **DB migration version** | **8**（`001_baseline` … `008_operation_log_command_id`） | `python -c "import sys;sys.path.insert(0,'_tools/ops');import _prod_smoke as s;print(s.repo_migration_head())"` |
| **Android 版本** | 产品 **0.2.4**（唯一来源＝仓库根 `VERSION`）＋构建号（日期式 `yyyyMMdd * 100 + 当日序号`） | `Get-Content VERSION` ／ `android/app/build.gradle.kts` |
| **Backend 版本** | `app_version` = **0.2.4**（`config._repo_version()` 现读同一个 `VERSION`）；⚠️ OpenAPI `info.version` 仍是 `0.1.0`（没跟产品版本走，如实记） | `backend/app/config.py` |
| **Frontend 版本** | ⛔ **没有**：`frontend/`（Vue3 旧 H5）已不在工作区，本轮不发布前端 | `git ls-files frontend`（0 个文件） |
| **requirements lock** | ⛔ **没有 lock** —— R3-07d 决策②「本轮不锁」（保持开区间）；改用**生产真实 freeze 指纹**当基准 | `docs/DEPENDENCY_DECISION.md` §七 |
| **config checksum** | systemd unit `2f5734f53645cc18`；nginx 配置 `06d8f1504a2381b81a4d05cbff78252a`；`backend/requirements.txt` `4f6f3ad341928200`（都是 sha256 前 16 位） | `python _tools/ops/_prod_smoke.py --readonly` |
| **artifact checksum** | `app-phone-release.apk`：44,490,405 字节 / `e7823ffeedf5f3fb`（**上一次发布**构建的包，2026-09-23）；后端**没有独立产物**（源码部署，SHA 就是它的标识） | `Get-FileHash android/app/build/outputs/apk/phone/release/*.apk` |

---

## 二、CI 证据（这份候选被机器验过）

| 提交 | 工作流 | 运行号 | 结论 |
|---|---|---|---|
| `684a9374`（候选本身） | Gate | `36231434911` | ✅ success |
| `684a9374` | Tests (Parallel) | `36231434912` | ✅ success |
| `cc949bf5`（本轮代码提交） | Gate / Tests | `36230516735` / `36230516664` | ✅ / ✅ |

⛔ 这几行是**人读的记录**，机器判据只保证「候选 SHA 是本仓库真实提交」（见台账第 1 条的复现命令）。

---

## 三、目标环境现状（**只读**采集，2026-09-26）

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
| 5 | **启动新后端** | `python _tools/deploy/_release.py --step start --go`（再核一次 `checkout <SHA>` → `restart sorders-api`，并核对 `is-active`） | `systemctl is-active` = active | 起不来 → 看 `journalctl -u sorders-api`；回第 5 节 |
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

## 六、⛔ 这份记录里**还没有**的东西（不许当成已发布）

1. ⛔ **发布没有执行**：第 1–7 步一步都没跑（要写许可）；上面所有「期望」都是**计划**，不是结果；
2. ⛔ 生产还停在 `648fbf8`（落后 293 个提交），所以「生产跑过这一版代码」**没有发生**；
3. ⛔ `_tools/deploy/_release.py`（把第 1–7 步串起来的那支脚本）**已经写好了**（2026-09-26），但它**只在本机跑过 `--plan` / `--selftest` / 被护栏拒绝的那一次** —— ⛔ 一次都没在生产上真跑过；
4. ⛔ APK 的 checksum 记的是**上一次发布**那个包；本轮若只发后端，APK 不重打（要重打就重算这一格）。
