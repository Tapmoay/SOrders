# R3 第三轮整改进度与退出条件台账

> **规则**：这份文件是「已完成」三个字的唯一出处。⛔ **没达到退出条件的里程碑就是没完成**，
> 不许用「已经差不多了」（指南 L1003）。
> **代码基线**：`d4be6f4` ｜ **指南**：`docs/ARCHITECTURE_RECTIFICATION_R3.md`
> **事实优先**：每一行的 `复现：` 后面必须是真能跑的命令；跑不通就是 ❌，不许写 ✅。

---

## 最终验收矩阵

12 项能力 × 5 个层次。⛔ 一行的意义是**这一格被证明过**，不是「代码里有」。
`—` = 这一轮不适用；`❌` = 还没证明。
最后一列写**这一格的依据或出口**（只写判据文件名与里程碑号 —— ⛔ 不写会变的数字）：
看到 ✅ 就照着它去复现，看到 ❌ 就知道它在哪一步关掉。

| 能力 | 代码 | CI | Staging | Production | Failure Drill | 依据 / 出口 |
| --- | --- | --- | --- | --- | --- | --- |
| Migration | ✅ | ✅ | ❌ | ✅ | ✅ | `_check_migrations.py` + `_check_import_purity.py`（R3-01）；生产：`schema_versions` 1..8（A 段实测）；**演练出口 ✅ = R3-06 Drill D**（三轮并发都退出 0、每个版本恰好一行、无重复记账）|
| Order Command | ✅ | ✅ | ❌ | ✅ | ❌ | `_check_order_commands.py`；生产：`order.create#528a7c69` / `order.assign#1b9da010` 两条命令的 command_id 真落库（A6）|
| Money | ✅ | ✅ | ❌ | ❌ | ❌ | `_check_money_contract.py` / `_check_money_dependency.py` / `_check_driver_money.py`；⛔ **生产没验过**：A6 的测试单没收款没送达 ⇒ `ledgers` / `driver_bills` 都是 0 行 |
| Capability API | ✅ | ✅ | ❌ | ❌ | ❌ | `_check_capability_registry.py`（R3-02 退出条件 1–2）；⛔ 生产侧只核到「路由 165 条与快照一致」，**能力本身没有生产判据** |
| Capability AI | ✅ | ✅ | ❌ | ❌ | ❌ | `_check_role_parity.py`（AI(role) ⊆ BACKEND(role)）；⛔ AI **写**动作白名单仍是**人工声明**，见 R3-02 |
| Capability UI | ✅ | ✅ | ❌ | ❌ | ❌ | `_check_capability_unification.py` 第 6 组（工作台入口按能力筛、都有着落）+ `ModulesEntryTest`；生产出口 R3-05-A |
| Capability Audit | ✅ | ✅ | ❌ | ❌ | ❌ | `_check_capability_unification.py`（91 个动作码有着落 / 非双射 / 棘轮只减不增）；⛔ 覆盖关系是**离线产物**，生产侧只有「审计行带着新列」这一点 |
| Outbox | ✅ | ✅ | ❌ | ✅ | ❌ | `_check_outbox.py` + `_check_outbox_idempotency.py`；生产：6 条事件全部 `sent`、重试 0（A6）；**演练出口 R3-06 Drill C ❌** —— 演练抓到真缺陷：投递失败被 python-socketio 吞掉，事件被记成 `sent`（`docs/R3_FAILURE_DRILL_EVIDENCE.md` §三·发现 2）|
| Scheduler | ❌ | ❌ | ❌ | ✅ | ❌ | ⛔ **没有静态判据**（只能真跑）：本机 `_dual_instance.py --all`（R3-03）；**生产**：一个 systemd 里 2 个 worker，`数据保留治理` 一个 `{'skipped': 1}`（拿到锁）+ 一个 `{'skipped_same_day': 1}`（没拿到）|
| Upload | ❌ | ❌ | ❌ | ❌ | ❌ | ⛔ 「多实例下一致」**没有静态判据**（只能真跑，R3-03）；上传自身的限制由 `_check_upload_limits.py` 核；⛔ 生产**没做写探测** ⇒ 可写性未验 |
| Socket multi-instance | ✅ | ✅ | ❌ | ✅ | ✅ | 判据 `_check_multi_instance_readiness.py`（在 119 个检查里）+ **生产实测**（A→B / B→A 双向往返、nginx `upstream`、摘机测试）；**演练出口 ✅ = R3-06 Drill B**（停 Redis：业务照常、总线恢复后自己回来）；⛔ **跨主机未验**，⚠️ 另有 `R_NUMSUB=1` 一条**未定**（见证据文档 §四）|
| Trace | ✅ | ✅ | ❌ | ✅ | ❌ | `_check_traceability.py`（R3-04）；生产：`_trace_order.py SO202609264191401979` 打完整条链（4 行审计带两个号 / 3 条事件 sent）|

**读表须知**

- `代码 ✅` 的意思是：有判据在每次全量检查里核它，且现在全绿（脚本数与耗时以 `python _tools/qa/_check_all.py`
  自己打印的为准 —— ⛔ 手写的那个数必然过期）。
  ⛔ 所以 `代码 ❌` 有**两种**，不是一回事：**还没做**；或者**这件事根本没有静态判据、只能真跑**
  （`Scheduler` / `Upload` / `Socket multi-instance` 三行属于后者 —— 它们在本机真跑过，
  见 R3-03，但「有判据在每次全量检查里核它」这句话对它们不成立）。最后一列会写明是哪种。
- `CI ✅` 的依据是：这条判据确实在 `_check_all.py` 里，而 CI 的 Gate **在 `cc949bf` 整轮 success**
  （2026-09-26 实测：`Gate` + `Tests (Parallel)` 两条工作流都是 success，含安卓端到端那个作业）。
  ⚠️ 在此之前 CI 已红过**四轮**：全是「本机绿、CI 红」——写死 `powershell`、例外表跨环境、
  指纹的排序键用 Path（Windows 大小写不敏感）。三件都只有 CI 看得见，见 `docs/RECTIFICATION_REPORT_R3.md` §5.3。
  ⚠️ 这一列的 ✅ **有保质期**，⚠️ 而且**按提交记、不按 tip 记**：当天推的提交**逐条**记在下面
  「CI 运行记录」一节（⛔ 不挑好的写，红的也留着）。
- `Staging` 一列全是 ❌，因为**这个项目没有 staging 环境**。这一列留着是为了让「生产没验过」这件事一直可见。
- `Production` 一列 ＝ 「**这一版代码在生产上跑过，并且这一格被真跑核过**」。2026-09-26 A 段之后它**不再是全 ❌**：
  Migration / Order Command / Outbox / Scheduler / Trace **五格已 ✅**（证据在 R3-05 的「A 阶段执行记录」与 `docs/R3_A_RELEASE_EVIDENCE.md`），
  其余七格仍 ❌ —— ⛔ **不是因为没上生产**，而是因为**那条路没被验过**：钱没动、Capability 四格没有生产侧判据、
  uploads 没做写探测。⛔ 「只读核对过」与「代码上生产了」**都不顶替**这一列。
- `Failure Drill` 一列 ＝ 「**这条能力有自己的故障演练，而且真的在生产上跑过**」。2026-09-26 C 段之后它**不再是全 ❌**：
  Migration（Drill D）与 Socket multi-instance（Drill B）两格 ✅；其余仍 ❌ —— 分两种：**演练问了但它答不上来**
  （Outbox：Drill C 抓到了真缺陷，见 `docs/R3_FAILURE_DRILL_EVIDENCE.md` §三·发现 2），
  以及**这五个演练压根没问到它**（Money / Capability 四格 / Scheduler / Upload / Trace / Order Command）——
  ⛔ 「没问到」与「问了没答上来」是两件事，别读成一件。

## 三层完成度矩阵（指南 §二十五 原则三）

| 四根主梁 | Code Ready | CI Proven | Runtime Proven |
| --- | --- | --- | --- |
| Migration 不再有隐式副作用 | ✅（R3-01） | ✅（`cc949bf` 整轮） | ✅ 本机真进程真库 ＋ **✅ 生产**（A 段：`schema_versions` 1..8、表数 44 → 48、业务数据零变动）|
| Capability 四端同源 | ✅（R3-02；⛔ AI **写**动作白名单仍是**人工声明**） | ✅ | ✅ 本机（生成物 + 两个 flavor 的 Gradle 单测；⛔ 真机界面未验；生产 ❌，R3-05） |
| 两个实例真的同时跑过 | ✅（R3-03） | ❌（**CI 里不起两个实例** —— 这一格 CI 证不了，只能本机/生产跑） | **部分**：本机同机双进程 4/5；socket / nginx 两格**没验**（本机没有 Redis / 没有 nginx） |
| 生产真的跑过 + 故障演练 | ✅（2026-09-26 A 段：发布八步走完） | ✅ | **部分**：生产**跑过** ✅（9/10 勾选项，见 R3-05）；**故障演练** ⚠️ 五条**都在生产上真跑过**（4 通过 / 1 抓到真缺陷）—— ⛔ 但第 10 项「Failure drills verified」仍是 **❌**，因为那一条判的是「故障**能被发现**」，而它发现的恰恰是「发现不了」|
| 整套静态判据（脚本数以 `_check_all.py` 自己打印的为准） | ✅ | ✅（`cc949bf` 整轮 success） | ✅ 本机 |

### 把 Runtime Proven 拆开看：三段的证据不是一回事

**指南 §二十五 原则三**是三层（Code Ready / CI Proven / Runtime Proven）。⛔ 但「Runtime Proven」内部
**三段的分量完全不同**，混成一个 ✅ 就会把「生产只读核对过」读成「生产跑过」。所以再拆一张：

| 层 | 状态 | 依据 / ⛔ 边界（这一段证不了什么） |
|---|---|---|
| 本机运行（Local Runtime） | ✅ **主要部分** | 双实例 4/5、真实迁移四态、真实上传、真库真请求 —— `docs/R3_RUNTIME_EVIDENCE.md`；⛔ socket 跨实例与 nginx 两格**本机也没验** |
| 生产只读（Production Read） | ✅ | 八项只读核对 —— `docs/R3_PROD_READONLY_EVIDENCE.md`；⛔ 只核对**现状**（结论大多是「生产还没有这一版」），**不是**运行验证，⛔ 不顶替验收矩阵里任何一个 `Production` 格 |
| 生产运行（Production Runtime） | ✅ **部分（7/10）** | A 段七项已完成（备份 / 迁移 / 启动 / health / 只读烟测 / **写烟测** / trace）；⭐ **B（socket / 多实例）与 C（五个故障演练）都已完成**（2026-09-26）—— 勾选表 **9/10**，只剩第 10 项因**演练抓到真缺陷**而仍是 ❌（见 R3-06）；勾选表在 R3-05「A 阶段执行记录」一节 |

---

## 写阶段出口（Write Phase A / B / C）

⚠️ **口径（2026-09-26 用户拍板）**：**A ✅ 已完成**；**B ✅ 已完成**；**发布控制面已与双实例拓扑对齐**（见下面 R3-05）；**备份隔离恢复验证 ✅ 已完成**；⭐ **C（五个故障演练）✅ 已执行**（2026-09-26：五条在生产上真跑过，六阶段 X0–X5，原始输出进仓库）—— **4 条通过 / 1 条（event-delay）抓到真缺陷**，详见 R3-06 与 `docs/R3_FAILURE_DRILL_EVIDENCE.md`。

```text
             R3 Production
                  A ✅（已完成）
                  ↓
          B Multi-instance ✅（Redis → 双实例 Socket → Socket 实测 → nginx upstream → 摘机测试，全部做完）
                  ↓ B 验收 ✅
          备份隔离恢复验证（新增前置）
                  ↓
          C Failure Drill
                  ↓
              R3 CLOSED
```

⛔ **B 段的顺序不许调**（用户钉死）：先把 Redis 与两个实例备好、**先验 Socket 双向**，最后才动 nginx —— 否则一旦出问题，
要同时面对 Redis / Socket / nginx **三个变量**。⛔ 而且：**「Redis 有 PONG」≠「Socket 适配器活着」**
（生产 Redis 现在 keyspace 是空的）—— 必须实测 `handshake → room → emit → 跨实例收到` 这条链。
它的用处是把「剩下 13 条怎么关」钉成**三段可执行、可停、可回滚**的路，而不是一次做完。

```text
A 结构迁移   备份 → 迁移 → 启动 → health → 只读烟测 → trace 一单
                        ↓ 全绿才准进
B 多实例     nginx upstream + 失败摘除（要先有第二个实例）/ Socket 跨实例
                        ↓ 全绿才准进
C 故障演练   worker-crash / redis-down / event-delay / lock-contention / disk-full
```

| 段 | 关掉哪几条 ❌ | 入口条件 | 出口判据（怎么算过关） | 失败怎么办 |
|---|---|---|---|---|
| **A 发布** | R3-05 六条：备份 / 迁移 / 启动 / health / 只读烟测 / trace 一单 | 用户一句话许可（禁做 #13/#14） | `_release.py --step X --go` 八步全过（各步判据见 `--plan`；⛔ 2026-09-26 执行前实测发现少了一步，见 R3-05）；`_prod_smoke.py --readonly` 退出码 **0**（⚠️ 今天跑出来是 **1** —— 生产还是旧代码）；`_trace_order.py <单号>` 能按 request_id 串起整条链 | **回滚 A**（代码退回上一个可用提交）/ **回滚 B**（用发布前的 dump 恢复库）；四步与「回滚后要做的三件事」在 `docs/RELEASE_CANDIDATE.md` §四·§五 |
| **B 多实例**（**2026-09-26 已放行并完成**）| R3-03 两条：Socket.IO 跨实例推送 / nginx upstream + 失败摘除 | ✅ **已完成** | 全部达标：B0 备料（⛔ 发现「生产 keyspace 空」**推不出**「没在用适配器」—— `.env` 里本来就有 `SOCKET_REDIS_URL`）→ B1 **Socket 双向实测通过** → B2 nginx `upstream` + **摘机测试通过** + 失败摘除有原始日志；原始输出 `docs/R3_B_MULTIINSTANCE_EVIDENCE.md` | 回滚：`systemctl enable --now sorders-api` + 把 nginx 两个文件从 `/opt/sorders-backup/b2-nginx-20260926-223624/` 拷回 + reload |
| **备份的隔离恢复验证**（用户 2026-09-26 定的 C 前置）| **已完成**：取一份**迁移之后**的备份 `pre_release/20260926T145643Z` → 跑项目自己的四阶段演练（恢复 / 库内不变式 / 隔离实例启动 / 真 token 打只读端点）| ✅ **DRILL=ok** | `schema_versions` **1..8** ／ 表 **48** ／ orders **2403**、ledgers **4648**、users **60**、products **37**（与 manifest 逐项相同）／ 关键查询（订单 / 账本 join / 身份 34+24+2 / 跨表审计行 / 新结构 outbox=13、带 rid 4、带 cid 3）全部读得出；原始输出 `docs/R3_RESTORE_VERIFICATION.md` | 恢复失败 → **C 段不许开始**（没有可用的回滚点，破坏性演练就没有安全网）|\n| **C 演练** | R3-06 五条：worker-crash / redis-down / event-delay / lock-contention / disk-full | **B 验收 ✅ ＋ 备份恢复验证 ✅** | 每条按 `C-X0 前置 → X1 取基线 → X2 注入 → X3 观察期望信号 → X4 恢复 → X5 核业务状态` 六步；⛔ **只证「服务起来了」不算过，要证「业务状态没被弄坏」** | 每条都写了「怎么停」；演练不动业务数据（`operation_logs` 除外 —— 那是它自己的证据）|

⚠️ **B 段可以只做一半**：装一个本机 Redis 就能把 socket 那一格验掉（代价＝本机多一个常驻服务）；
nginx 那一格**必须**在生产上做 —— 「upstream + 失败摘除」在当前部署形态里**根本不存在**（单后端反代）。
⛔ 借生产 Redis 做测试是**不能走**的路（会把测试实例的推送混进生产客户端同一个 channel）。

#### B 段三步（用户 2026-09-26 钉死的顺序）

| 步 | 做什么 | 出口判据 |
|---|---|---|
| **B0 备料** | 确认生产 Redis 可用（⛔ **有 PONG ≠ Socket 能用**）；起第二个实例（A :8111 / B :8112），共享 MySQL / Redis / uploads；⛔ **这一步不动 nginx** | 两个实例各自能登录、各自 `/health` 200；两边的 token 互认（同一份 JWT secret）|
| **B1 Socket 双向实测** | 客户端分别连 A 与 B；**A 上的写入，连在 B 上的客户端收到；反过来也要收得到** | 两个方向都**实测**收到（⛔ 不是「Redis 配置看起来没问题」—— 要 `handshake → room → emit → 跨实例收到` 这一整条）|
| **B2 最后才动 nginx** | 把单后端 `proxy_pass` 换成 `upstream { A B }` | 正常请求两个后端都接得到；**摘掉 A → B 继续服务**、**摘掉 B → A 继续服务**；`max_fails` / `fail_timeout` / `proxy_next_upstream` **真的触发过** |

⛔ B2 之前生产 nginx **一个字都不许改**（那条 `proxy_pass http://127.0.0.1:8000` 是当前唯一在用的入口）。
⛔ 每一步失败就停在那一步 —— 与 A 段同一条纪律（不跳过、不做旁路修补）。

#### CI 偶发红的处置（用户 2026-09-26 拍板）

`b3dad61` 那次「安卓单测」红 **不修、不为它加逻辑**：⛔ 别把一次环境波动变成架构改造。
规矩：**保留记录 + 写清原因 + 观察重复率** —— 同一个作业在**连续 3 / 5 / 10 次**里再次出现，才升级成「CI 稳定性问题」立项。
（这一次的判断依据已经写在那两行里：改动**一行安卓代码没碰**，而**下一个同类提交六项全过**。）

---

## CI 运行记录（2026-09-26 推的提交，逐条记）

⛔ 这一节**只记事实**：哪一次绿、哪一次红、红在哪一个作业。它的位置故意放在两张矩阵**之外**
（矩阵那两节被 `_check_r3_constraints.py::probe_progress_shape` 逐行解析，混一张别的表进去会把它判红 ——
本节的初版就踩过：那张表有 3 列、判据要求 ≥5 格）。

| 提交 | Gate | Tests (Parallel) | 说明 |
|---|---|---|---|
| `5cb27fb` / `bcb11a9` / `2ed3e5a` | ❌ / ❌ / ❌ | ✅ / ✅ / ✅ | 三个「本机绿、CI 红」缺陷的取证过程（根因见报告 §5.2）。⚠️ 三个提交**红法不同**，别读成同一件事：`5cb27fb` ＝ 静态检查 + AI 读权限对账 + 端到端（无 rc）；`bcb11a9` ＝ 静态检查（`_check_generated_freshness` 3 条 / `_check_report_facts` 2 条）+ 端到端（`rc=1`）；`2ed3e5a` ＝ **只有**静态检查（2 条 / 1 条）—— 端到端这一次是**过**的 |
| `cc949bf` | ✅ | ✅ | 指纹排序键修好之后的**第一次整轮绿** |
| `684a937` | ✅ | ✅ | 收口文档（含安卓端到端那个作业）|
| `88b6a66` / `5e9eda7` | — | — | **cancelled**：连推两次时 GitHub 按并发组取消了前一次 —— ⛔ 那不是红 |
| `97c5caa` | ❌ | ✅ | ⚠️ **只有「安卓端到端（登录 → 导航 → 下单）」作业红**：注解原文「**rc=1**」⇒ 按工作流的分档是「**脚本跑了并报失败**」（不是「模拟器没起来」）。同一提交只动了两处 `.md`；静态检查 / 后端用例 / AI 权限对账 / 安卓单测全绿。⚠️ 哪一段挂的读不到（日志要登录）|
| `dadf095a`（这一节的收尾提交） | ✅ | ✅ | **整轮绿**（含安卓端到端那个作业 —— 也就是上一次红的那一个，这次模拟器起来了。同一份工作流、只差一个 `md` 提交）|
| `a591ff2` / `1c2c572` | ✅ / ✅ | ✅ / ✅ | 两次整轮绿（后一次是「发布工具 + 护栏自检」那个提交）|
| `c4c8206` / `cc47565` | ❌ / ❌ | ✅ / ✅ | 两次都只有安卓端到端红（`rc=1` ＝ 脚本跑了并失败）|
| `a8cdc5d`（本报告重写版那个提交） | ❌ | ✅ | ⚠️ 只有安卓端到端红 —— 这一次是**另一种**：注解原文「**连 `/tmp/e2e.rc` 都没有 —— 模拟器压根没起来**」＝**这次没有跑**（不是流程失败）。同一提交只动了两份 `.md` |
| `b0a364a` | ✅ | ✅ | **整轮绿**（含安卓端到端那个作业）—— 台账「`CI ✅`」那一列的**依据提交** |
| `7030d25` | ❌ | ✅ | ⚠️ 只有安卓端到端红，**没有 `/tmp/e2e.rc`** ⇒ 模拟器没起来、**这次没有跑**（不是流程失败）|
| `5fa3526` | ❌ | ✅ | ⚠️ 只有安卓端到端红，**`rc=1`**，而且这一次注解里**直接读到了失败点**：「环境齐，可以跑 ｜ ① 登录 ｜ ❌ 既没看到工作台也没看到登录页。当前屏幕：**Pixel Launcher isn't responding**」⇒ 失败在**环境**那一格（系统 launcher 自己 ANR 盖住了屏幕），⛔ 不是 App 崩、也不是流程代码错 |
| `6b66857` | ✅ | ✅ | **整轮绿**（含安卓端到端）|
| `8be5594` | — | — | ⛔ **它没有自己的运行**：它与 `a896c48` 是**同一次 push** 推的，而 GitHub 一次 push 只按 **tip** 触发 —— ⛔ 这不是「被取消」，是**本来就没跑**（与 `88b6a66`/`5e9eda7` 那一次的 cancelled 不是一回事）|
| `a896c48`（台账口径修复 + 报告 v2.1） | ✅ | ✅ | **整轮绿**（含安卓端到端）—— 本节最后一行 |
| `b0492e7`（**本节的收尾提交**：CI 记录补齐） | ✅ | ✅ | **整轮绿**（含安卓端到端）|
| `b3dad61`（A0 收口；这次 push 的 **tip**，同一次 push 还带了 `e98c7d7` 与 `10c91d2`） | ❌ | ✅ | ⚠️ **红的是「安卓单测」、不是端到端**：Gate 里六个作业，只有 `Normal Gate · 安卓单测（PR 上也拦）` 红在「跑模拟器变体的单测」那一步（⛔ 该作业**不发注解**，所以这一次没有注解可读，只能读作业名与步骤名）。它的改动只有 `_tools/deploy/_release.py` + 三份 `.md`，**一行安卓代码都没碰**；而**下一个提交**（同样只改 `_tools/` 与 `docs/`）六项全过 ⇒ 判为**偶发/环境**，⛔ 不是代码问题 |
| `3b9ad52`（**A 段执行记录**） | ✅ | ✅ | **整轮绿**（六个作业全过，含安卓单测与端到端）|
| `58514a4` | — | ✅ | ⚠️ Gate 是 **cancelled**、⛔ **不是红**：推 `8221d23` 时它还在跑，GitHub 按**并发组**把前一次取消了（与 `88b6a66`/`5e9eda7` 同一种）。Tests 那条跑完了、success |
| `8221d23`（**本节的收尾提交**：§12.3 改成台账原文） | ❌ | ✅ | ⚠️ **只有安卓端到端红**，**`rc=1`**，注解原文与 `5fa3526` 那次**一字不差**：「① 登录 ｜ ❌ 既没看到工作台也没看到登录页。当前屏幕：**Pixel Launcher isn't responding**」⇒ 同一个**环境**故障（模拟器太慢、系统 launcher 自己 ANR），⛔ **不是 App 崩、也不是流程代码错**；同一个运行里静态检查 / 后端用例 / AI 权限对账 / 安卓单测**全绿**。⛔ 这一行不外推 —— 本表自己的收尾提交（下一条）会重新跑一次 |

  ⭐ 当天合计：这个「安卓端到端」作业跑了 **21 次：绿 12 次、`rc=1` 红 6 次、无 rc 红 3 次**（另有 1 次 **cancelled**、⛔ 不计入：`58514a4`）
  （⚠️ 这是**截至表里最后一行（`b0492e7`）**的数 —— 口径：上表列出的每个提交各算一次，
  `cancelled` 的不计入；⛔ 每推一次就会变，**别手抄，重数**）。
  ⛔ **右边界**：表里最后一行永远是「**写这张表的那次提交之前**的那一个」—— 记完就推、推完又要记，会无限套娃。
  所以**收尾提交自己那一行之后不再追认**，要看它按提交号去 GitHub 查（口径不变：**按提交记、不按 tip 记**）。
  · `rc=1` ＝ **脚本真的跑了，流程里某一段失败**（`bcb11a9`、`97c5caa`、`c4c8206`、`cc47565`、`5fa3526`、`8221d23`）
    —— ⚠️ 其中 `5fa3526` 与 `8221d23` 两次的注解**一字不差**，都是 **Pixel Launcher isn't responding**（系统 launcher ANR）：
    「脚本跑了并失败」≠「App 有问题」—— 失败点在**环境**那一格，同一提交的四条真作业都是绿的；
  · 无 `rc` ＝ **模拟器压根没起来**（`5cb27fb`、`a8cdc5d`、`7030d25`）—— 「没跑」不等于「通过」。
  ⚠️ **两种红的含义完全不同**，台账不再把它们混成一句「基础设施问题」——两种都由工作流自己的分档打印出来。
  ⭐ 当天也把 `/tmp/e2e.log` 的尾部加进了 `rc=1` 那条注解 ⇒ 下一次**流程失败**时，注解里会直接写出是哪一段。
  ⭐ **它当场就起效了**：`5fa3526` 那一次就是 `rc=1`，注解里直接读到 ——
  「环境齐，可以跑 ｜ ① 登录 ｜ ❌ 既没看到工作台也没看到登录页。当前屏幕：**Pixel Launcher isn't responding** ｜ Close app ｜ Wait」
  ⇒ 失败在**环境**这一格：模拟器太慢，**系统 launcher 自己 ANR** 弹窗盖住了屏幕（与 2026-09-25 第 60 轮记录的那种一模一样），
  ⛔ 不是 App 崩、也不是流程代码错。这就是「注解匿名可读」这条工程决定的回报 —— 以前只能靠猜。

⭐ **口径：按提交记、不按 tip 记** —— 每推一个新提交都会产生一次新的运行，所以「**现在的 tip 是绿的**」
这句话**只对表里列出的那个提交**成立。⚠️ 反例就在上表里：`97c5caa`（只改了两处 `.md`）上那个作业红着（**流程里某一段失败**），
而下一次推的 `dadf095a` 同样的工作流就整轮绿了；反过来 `a8cdc5d` 又碰上**模拟器没起来**（这次根本没跑）—— 
⛔ 所以既不许拿一次红判定代码有问题，也不许拿一次绿保证下一次绿。

---
## R3-00 Baseline（本轮起点）

- ✅ 指南已归档：`docs/ARCHITECTURE_RECTIFICATION_R3.md`（SHA256 `193AB545…5297`，1219 行）—— 复现：`python -c "import hashlib,pathlib;p=pathlib.Path('docs/ARCHITECTURE_RECTIFICATION_R3.md');print(hashlib.sha256(p.read_bytes()).hexdigest()[:8], len(p.read_text(encoding='utf-8').splitlines()))"`
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
- ✅ 退出条件 4/10：migration version 正确（版本 7，7 条全部记账）—— 复现：`cd backend; python -c "import os,sys,tempfile,runpy; d=tempfile.mkdtemp(); os.environ['DATABASE_URL']='sqlite:///'+(d.replace(os.sep,'/')+'/m.db'); sys.path.insert(0,'.'); sys.argv=['app.migrations','status']; runpy.run_module('app.migrations', run_name='__main__')"`
  ⚠️ 这条命令为什么这么长：原来的 `python -m app.migrations status` 读的是**环境里配的 DATABASE_URL** ——
  本机有 `.env`（SQLite）所以它绿，而 CI 上**没有 `.env`**、缺省值是 MySQL ⇒ 报 `Can't connect to MySQL server`
  （2026-09-26 CI 实测）。改成**自己造一个临时库再问它**：两个平台都跑得通，证的还是同一件事（迁移体系认得出版本表）。
- ✅ 退出条件 5/10：空库迁移通过（48 张表 / 版本 7 / 启动核对通过）—— 复现：`python _tools/ops/_migration_tests.py --fresh`
- ✅ 退出条件 6/10：旧库迁移通过（无迁移记录的老库 → 版本 7，结构一行没丢）—— 复现：`python _tools/ops/_migration_tests.py --old`
- ✅ 退出条件 7/10：两个进程同时迁移 → 都成功、每个版本恰好一行 —— 复现：`python _tools/ops/_migration_tests.py --concurrent`
  ⚠️ 本机是 Windows + SQLite，证的是**本机互斥**；跨主机那一段是 MySQL `GET_LOCK`，要到 R3-03 在生产库上真跑一次才算数
- ✅ 退出条件 8/10：迁移失败 → 不记账、不半残（失败版本没进版本表，1..7 都在）—— 复现：`python _tools/ops/_migration_tests.py --fail-fast`
- ✅ 退出条件 9/10：后端用例全绿（**条数以 `pytest -q` 自己打印的为准**）—— 复现：`cd backend; python -m pytest -q`
- ✅ 退出条件 10/10：全量静态检查全绿（**脚本数/逐条耗时/总耗时都以它自己打印的为准**）—— 复现：`python _tools/qa/_check_all.py`

**三层完成度**：Code Ready ✅ ｜ CI Proven ✅（2026-09-26 整轮 success —— 见上面「CI 运行记录」；⛔ 之前写的「还没推」已过期）｜ Runtime Proven ✅（本机真进程真库；**生产**仍未验证）

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

**三层完成度**：Code Ready ✅ ｜ CI Proven ✅（2026-09-26 整轮 success —— 见上面「CI 运行记录」；⛔ 之前写的「还没推」已过期）｜ Runtime Proven ✅（本机两个 flavor 的 Gradle 单测都跑过；**真机界面未验**）

## R3-03 Multi-instance Runtime（硬门槛）

工具：`python _tools/ops/_dual_instance.py --all`（真起两个 uvicorn :8111/:8112，共用一个库 + 一个上传目录）。
原始输出记在 `docs/R3_RUNTIME_EVIDENCE.md`；架构决策记在 `docs/R3_DECISIONS.md`。

- ✅ 两个实例同时运行（都接请求；**A 登录的 token 到 B 上也认**）—— 复现：`python _tools/ops/_dual_instance.py --all`（下面三条共用这一次运行）
- ✅ migration 只执行一次 —— 复现：`python _tools/ops/_migration_tests.py --concurrent`（R3-01 的用例，两个进程同时 upgrade）
- ✅ scheduler 只执行一次（启动即跑的那轮治理：**真跑 1 次 / 跳过 1 次**）—— 复现：`python _tools/ops/_dual_instance.py --all`
- ✅ upload 一致（A 传的图 B 取得到，**字节一致**）—— 复现：`python _tools/ops/_dual_instance.py --all`
- ✅ 杀掉 A 之后 B 继续服务（`/health` 200 + 登录读自己 200）—— 复现：`python _tools/ops/_dual_instance.py --all`
- ✅ 上传资产的运行模型已决策（**本机文件系统资产**；多实例＝同机多进程/同一挂载点；对象存储留 R4）—— 复现：`python _tools/qa/_check_r3_constraints.py`（`upload_decision_record` 探针）
- ✅ **Socket.IO 跨实例推送**（2026-09-26 B 段实测，**两个方向都收到**）—— 复现：`python _tools/qa/_check_multi_instance_readiness.py --check`
  ⭐ 实测（raw WebSocket 直接讲 Socket.IO 协议，⛔ 不是「Redis 配置看起来没问题」）：
  ```text
  OK   A 上 emit -> 连在 B 上的客户端收到 -> 收到（0.1s）      ← 第一次（隔离的 db 1 上验机制）
  OK   B 上 emit -> 连在 A 上的客户端收到 -> 收到（1.5s）
  OK   A 上 emit -> 连在 B 上的客户端收到 -> 收到（1.7s）      ← 第二次（真拓扑 db 0 上复验）
  OK   B 上 emit -> 连在 A 上的客户端收到 -> 收到（0.0s）
  ```
  ⛔ 上面那条复现命令核的是`docs/MULTI_INSTANCE_READINESS.md` 里 `socket-cross-process` 这道门：
  它声明 done，判据就去 `docs/R3_B_MULTIINSTANCE_EVIDENCE.md` 里核那四串**实测结论**真的在不在（可在 CI 上跑）。
  原始输出与「⛔ 这份证据证不了什么」在同文档。
  ⛔ 本机**没有 Redis**，Socket.IO 的跨进程适配器起不来，这一格**没有验**，不假装通过。
  要验需要有 Redis 的环境。⛔ 有一条**不能走**的路：借生产的 Redis —— 那会把测试实例的推送混进
  生产客户端的同一个 channel（除非用不同的 Redis DB 序号，而那就等于在生产机上起临时实例）。
  三条候选路径写在下面「卡在哪儿」一节。
  ⭐ 2026-09-26 生产只读核对补上一条**事实**：生产 Redis 的 `info keyspace` **没有任何 db 行**（键空间是空的）
  ⇒ 生产**也没有**在用跨实例适配器。所以这一格不是「本机缺 Redis」，而是**本机与生产都没有证据**。
- ✅ **nginx upstream + 失败摘除**（2026-09-26 B 段在生产上做成并**摘机验过**）—— 复现：`python _tools/qa/_check_multi_instance_readiness.py --check`
  ⭐ 现在的形态：`upstream sorders_backend { ip_hash; server 127.0.0.1:8111 max_fails=2 fail_timeout=10s; server 127.0.0.1:8112 … }`
  + 三个 location 都带 `proxy_next_upstream error timeout http_502 http_503 http_504`（`ip_hash` 是因为 Socket.IO 先 polling 再升级 websocket，那一串必须落同一个后端）。
  ⭐ **摘机测试**：摘掉 A → 请求仍 401（B 接管）；恢复 A、等过 `fail_timeout` 窗口、再摘掉 B → 请求仍 401（A 继续服务）。
  ⭐ **失败摘除的原始证据**（`/var/log/nginx/error.log`）：`connect() failed (111: Connection refused) … upstream 8111` 与 `no live upstreams … upstream http://sorders_backend`
  ⇒ ⛔ 不是「配置文件里看起来有」，是 nginx 真的把那台标了不可用。⚠️ 我第一次跑时第三步出过 502 —— 是我自己的时序（`fail_timeout` 窗口没过完就摘了第二台），重跑即过，如实记着。
  （那道门的 `status` 仍是 `not-done`）。本机没有 nginx；它要动生产 nginx，属 R3-05（且要用户许可）。
  ⭐ 2026-09-26 生产只读核对了 nginx **现状**（`nginx -T`，只读）：`proxy_pass http://127.0.0.1:8000` ——
  **单后端**；配置里**没有** `upstream` 块，也**没有** `max_fails` / `fail_timeout` / `proxy_next_upstream`。
  ⇒ 「upstream + 失败摘除」在**当前部署形态里根本不存在**（后端是**一个** systemd 服务里的 2 个 uvicorn worker）。
  要让它成立，必须**同时**改部署形态（→ 多实例/多端口）与 nginx 配置 —— 那是发布变更，属写阶段。

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

**三层完成度**：Code Ready ✅ ｜ CI Proven ✅（2026-09-26 整轮 success —— 见上面「CI 运行记录」）｜ Runtime Proven ✅（本机同机双进程 + **生产两个实例**：socket 双向实测、nginx upstream + 摘机测试都过；⛔ **跨主机未验**）

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
- ✅ 业务指标（订单/命令/事件/通知/迁移/调度）—— 复现：`cd backend; python -c "import os,sys,tempfile; d=tempfile.mkdtemp(); os.environ['DATABASE_URL']='sqlite:///'+(d.replace(os.sep,'/')+'/m.db'); sys.path.insert(0,'.'); from app.database import engine, SessionLocal; from app.core.schema_bootstrap import prepare_schema; prepare_schema(engine); from app.core.metrics import snapshot, NOT_TRACKED; print(len(snapshot(SessionLocal())), len(NOT_TRACKED))"`
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

**三层完成度**：Code Ready ✅ ｜ CI Proven ✅（2026-09-26 整轮 success —— 见上面「CI 运行记录」；⛔ 之前写的「还没推」已过期）｜ Runtime Proven ✅（本机真库真请求：3 个用例跑在真实接口上）

## R3-05 Production Release

⛔ 这八条**一条都没做**（它们全都要写操作：备份 → 迁移 → 启动 → 体检）。用户 2026-09-26 只放行了**只读**那一半，
所以「只读核对」单独记在下面那个小节里，⛔ 不拿它顶替这里的任何一条。

- ✅ Release Candidate 记录齐全（Git SHA / 迁移版本 / Android / Backend / Frontend / 依赖锁 / 配置校验和 / 产物校验和）—— 复现：`python -c "import pathlib,re,subprocess,sys; t=pathlib.Path('docs/RELEASE_CANDIDATE.md').read_text(encoding='utf-8'); need=['Git SHA','DB migration version','Android 版本','Backend 版本','Frontend 版本','requirements lock','config checksum','artifact checksum']; bad=[k for k in need if k not in t]; m=re.search(r'\*\*Git SHA\*\* \| .{0,3}([0-9a-f]{40})', t); shaok=bool(m) and subprocess.run(['git','cat-file','-e',m.group(1)+'^{commit}']).returncode==0; ver=pathlib.Path('VERSION').read_text(encoding='utf-8').strip(); verok=ver in t; head=max(int(''.join(c for c in p.stem.split('_')[0] if c.isdigit())) for p in pathlib.Path('backend/app/migrations').glob('0*.py')); mm=re.search(r'\*\*DB migration version\*\* \| \*\*(\d+)\*\*', t); migok=bool(mm) and int(mm.group(1))==head; print('缺字段',bad,'SHA在库',shaok,'VERSION',ver,verok,'迁移头',head,'记录一致',migok); sys.exit(1 if (bad or not shaok or not verok or not migok) else 0)"`
  ⭐ 记录本体：`docs/RELEASE_CANDIDATE.md`（每个字段都写了自己的**现取命令**，⛔ 没有一个是手抄的）。
  ⛔ 这一条 ✅ 证的是「**记录齐全且与仓库事实对得上**」（字段齐、SHA 真是本仓库的提交、迁移版本与目录现数一致、版本号与根 `VERSION` 一致）；⛔ **不证**发布做过了 —— 下面第 2–7 条仍然全是 ❌。
- ✅ 发布工具在位、且**护栏自检**通过（顺序强制 / 备份新鲜度 / SHA 必须在仓库里 / 算不出事实就拒绝 / 没 `--go` 一律只打印）—— 复现：`python _tools/deploy/_release.py --selftest`
  ⛔ 这一条证的是**工具的护栏**（23 项自检），**不证**发布跑过 —— 下面第 2–7 条仍然全是 ❌。
  ⛔ 工具默认只打印：`--plan` 打印八步与判据；`--step X` 不带 `--go` 只给结论；真执行要 `--go`。
- ✅ 生产验收清单已建立（R3-05-C：12 项**按权限分段** —— 只读那段今天跑过，写那段一条没跑）—— 复现：`python -c "import pathlib,re,sys; docs=['docs/RELEASE_CANDIDATE.md','docs/PRODUCTION_ACCEPTANCE.md','docs/R3_FAILURE_DRILL.md']; miss=[d for d in docs if not pathlib.Path(d).exists()]; lines=[(d,ln) for d in docs for ln in pathlib.Path(d).read_text(encoding='utf-8').splitlines() if not any(k in ln for k in ('待写','还没写','不存在','待建'))]; bad=sorted({d+':'+p for d,ln in lines for p in re.findall(r'_tools/[A-Za-z0-9_./-]+\.py', ln) if not pathlib.Path(p).exists()}); print('缺文档',miss,'引用了不存在的脚本',bad); sys.exit(1 if (miss or bad) else 0)"`
  清单本体：`docs/PRODUCTION_ACCEPTANCE.md`（逐项给了命令与判据；⛔ 混在一起就会变成「借验收之名做写测试」）。
- ✅ 备份（生产实测 2026-09-26）：`/opt/sorders-backup/pre_release/20260926T133009Z` —— 库 `db.sql.gz` 526,286 B ＋ 上传 `uploads.tar.gz` 105,962,426 B ÷ 2115 个文件，**sha256 校验通过**；清单留在 `_tools/backup/manifests/20260926T133017Z-pre_release.json`（行数 orders=2402 / ledgers=4648 / users=60 / products=37 / tables=44） —— 复现：`python -c "import json,pathlib,sys; fs=sorted(pathlib.Path('_tools/backup/manifests').glob('*pre_release.json')); m=json.loads(fs[-1].read_text(encoding='utf-8')); a=m.get('artifacts') or {}; print(fs[-1].name, m['kind'], m['db']['rows']); sys.exit(0 if ('db.sql.gz' in a and 'uploads.tar.gz' in a) else 1)"`
  ⛔ 这条命令核的是「**那份清单真的在库里、两样产物都记着**」—— 它能在 CI 上跑（不碰生产）。
  ⛔ 备份命令本身**不许**写进 ✅ 的复现位：那会让每次全量检查都真去生产备份一次。
  ⛔ 它也**证不了备份能恢复** —— **没有真的恢复过一次**（那要写操作，属另一次许可）。原始输出：`docs/R3_A_RELEASE_EVIDENCE.md` §二。
- ✅ **代码落位**（`stage`：把 <SHA> 落到生产、**⛔ 不重启服务**）—— 生产实测：HEAD = `b3dad61bbdfae6a3b64a5d0be2d75d20641213a7`、`app/migrations` 在了，而**服务仍 active 且 `/health` 还是 0.2.0（跑的还是旧代码）**、`ActiveEnterTimestamp` 未变 —— 复现：`python _tools/deploy/_release.py --step stage`（⛔ 不带 `--go` 只打印判定，且**不连生产**）
  ⭐ 这一步是**执行 A 之前**实测发现的：迁移的入口 `-m app.migrations` 属于新代码，而生产上当时没有那个包
  ⇒ 原方案「先迁移后应用」在**第一次**发布时**落不了地**（会以 `No module named app.migrations` 失败，而那不是数据问题、是顺序问题）。
  ⛔ 修法是**动手前把顺序补对**（`stage` → `migrate` → `verify` → `start`，并同步改 `docs/RELEASE_CANDIDATE.md` §四），**不是**失败之后临时绕过。原始输出：同文档 §三。
- ✅ 迁移（先迁移后应用）—— 生产实测：`schema_versions` **1..8 各一行**（001 0ms / 002 1ms / 003 194ms / 004 127ms / 005 2ms / 006 268ms / 007 3ms / 008 115ms）；新增 `outbox_events` / `ai_call_daily` / `schema_versions` / `unit_conversions`（第 4 张是新代码的**模型表**，由运行时自愈建），表数 44 → 48；⛔ **业务数据一行没动**（orders 2402 / ledgers 4648 / users 60 / products 37，与备份清单逐项相同） —— 复现：`python _tools/deploy/_release.py --step migrate`（⛔ 不带 `--go` 只打印，不连生产）
  ⚠️ 真跑要 `--go`；生产上它执行的就是迁移的唯一入口 `cd /opt/SOrders/backend && .venv/bin/python -m app.migrations upgrade`（＝自愈 + 8 条版本化迁移）。原始输出：同文档 §四。
- ✅ **验证结构**（`verify`：判 `status --json` 的**结论**）—— 生产实测：**当前版本 8 == 本仓库迁移头 8；待跑 0 / 漂移 0 / 陌生版本 0** —— 复现：`python _tools/deploy/_release.py --step verify`（⛔ 不带 `--go` 只打印，不连生产）
  ⚠️ **第一次它是红的，而红的是判据、不是生产**：原判据要求输出里有「待跑：0 条」，而 `status` 那行**只在有待跑时才打** ⇒ 迁移越干净越报红。
  已改成读 `--json` 的三个列表（`pending` / `drifted` / `unknown_in_db`）+ 与**本仓库迁移头**比对，并抽成纯函数进 `--selftest`（自检 17 → **24** 项）—— ⛔ 判据**变强**了，不是放松。两次原始输出都在同文档 §五。
- ✅ 启动新后端 —— 生产实测：`is-active = active`，重启时刻 21:36:06；**`/health` 版本 0.2.0 → 0.2.4**（＝新代码真的在跑）；启动日志「数据库结构已经是版本 8」＋ 结构化日志 `[rid=…] [cid=-]` —— 复现：`python _tools/deploy/_release.py --selftest`（⛔ 这条核的是**这一步的四条护栏**：G1 不给 `--go` 只打印、G2 顺序强制、G3 备份新鲜度、G4 算不出事实就拒绝；⛔ 它**证不了**生产起没起来 —— 那要连生产，没法写进 CI 能跑的复现位）
  ⭐ **2026-09-26 二次对齐（发布控制面 ↔ 双实例拓扑）**：B 段把生产换成「两个 unit + nginx upstream」之后，这一步原来写死的 `systemctl restart sorders-api` 变成**在重启一个已停用的 unit**（命令会「成功」返回、`is-active` 却不是 active）。已改成：**从系统里实际 enabled 的 `sorders-api*` unit 取目标**（⛔ 不硬编码 unit 名，⛔ 也不硬编码端口 —— 端口从每个 unit 的 `ExecStart` 里读）、**逐个滚动重启**，每重启一个就核 `is-active` ＋ 该实例 `/health` ＋ **经 nginx 的入口仍有活上游**，全部通过才算过。
  实测（`--step start --go`）：`拓扑：滚动重启 2 个（按名字排序）：sorders-api-a.service、sorders-api-b.service` → `[1/2] … is-active=active ｜ /health=200 ｜ 经 nginx 入口：401（有活上游）` → `[2/2] …` 同 → `✅ 全部 2 个实例：active + /health 200 + 滚动全程 nginx 都有活上游`。
  ⛔ 顺带复验「不影响 Socket 双实例能力」（⛔ 不是重做 B1/B2）：滚动重启后再跑一次跨实例实测 —— A→B 收到（0.5s）、B→A 收到（0.0s）。护栏自检 24 → **32/32**（新增 `roll_plan` / `roll_verdict` 的 8 条用例）。
  ⛔ 这一条记的是「**发布工具与拓扑重新对齐**」，⛔ **不算新的生产运行时能力**，也不重做 A 的整套验收。
  ⚠️ 真跑要 `--go`（本轮是 `--step start --go --sha b3dad61…`）；生产侧原始输出：同文档 §六。
- ✅ health（**启动之后**的体检）—— 生产实测：**6 项正常 / 2 告警 / 0 失败**；数据库探针 = 1、48 表、**迁移版本 8**；发件箱 待发 0 / 已发 0 / 放弃 0；2 条告警是**已知/已接受**的证书（域名未备案，App 走 IP 证书，还有 1087 天） —— 复现：`python _tools/ops/_check_ops.py --check`（⛔ 核的是**体检工具本身**：只读、阈值只有一处、退出码分档；生产那一次的输出在同文档 §六）
- ✅ 只读烟测 —— 生产实测：**ERROR 0 条、未批准 WARN 0 条、已批准 WARN 2 条**（31 通过）；⭐ 顺带量到 `request_id` 直连与**经 nginx 都原样回来**、生产跑的运行时代码与本仓库 **`backend/` 零差异** —— 复现：`python _tools/ops/_check_ops.py --check`
  ⭐ **判据（用户 2026-09-26 拍板，正式语义）**：
  ```text
  A5 通过 = ERROR = 0  且  没有未批准的 WARN
                    ├── ERROR > 0        → ❌
                    ├── 未批准 WARN > 0  → ❌（未批准的告警**就是** ERROR）
                    └── 只有已批准 WARN  → ✅
  ```
  ⛔ 两个语义被钉死：**「证书 / Redis 口令 / 服务端时区」这类既知项 ＝ WARN ＝ 不阻塞**；
  **「生产跑的不是这一版代码」＝ ERROR ＝ 必须阻塞**（它在 `_prod_smoke.py` 里**根本没有 `warn_only` 这一档**）。
  ⛔ 实现不是口号：烟测里有一张 **`APPROVED_WARNS` 登记表**（键 = 行名，值 = 批准理由 + 什么时候能删），
  任何**不在表里**的告警会被 `chk()` **直接升级成 ERROR**（类别 `approval`）——「默默地告警一下就过去」这条路被堵死。
  ⚠️ 这次落地的同时把三处**分类错误**也修了：① `request_id 经 nginx` 与 ② `nginx 有 /socket.io/ 转发` 原来是可批准告警 ⇒ 改成 **ERROR**
  （它们一旦红，等于「trace 链在入口断掉」/「实时推送在入口断掉」，不是告警）；③ 依赖版本区间那条改成**只记录不判对错**（拍板②：本轮不锁声明）。
  ⛔ 原来的「退出码 0」确实太粗（1 档混装「不一致」与「既知告警」）—— 这一次改的是**分层**，不是降低标准。
  生产那一次的输出（含改判据前那次 exit 1）在 `docs/R3_A_RELEASE_EVIDENCE.md` §七。
- ✅ trace 一单 —— 生产实测：`_trace_order.py SO202609264191401979` 一条命令打完整条链 —— 4 行审计**带上 command_id 与 request_id 两个号**（`order.create#528a7c69` / `order.assign#1b9da010`）、3 条发件箱事件全部 `sent` 重试 0、通知 8 条；⭐ **三个 request_id 与客户端拿到的 `X-Request-ID` 是同一串** —— 复现：`python _tools/qa/_check_traceability.py`（⛔ 核的是**工具与链路形状**：7 段链路的表与列都在、工具真的查了它们、全程只读；生产那一次的原始输出在同文档 §八）
  ⚠️ 生产侧必须在**生产机上**跑（工具读库，而生产 MySQL 外网不可达）：`cd /opt/SOrders/backend && set -a && . /opt/SOrders/.env && set +a && .venv/bin/python ../_tools/ops/_trace_order.py <单号>`。
  ⚠️ 那一单是**按 `PRODUCTION_ACCEPTANCE.md` §三 建的测试单**（建 1 / 派 1 / 撤 1，只动三个测试账号），已撤销；`ledgers 4648 → 4648`（钱没动）。
- ✅ 回滚 / 前向修复方案已写 —— 复现：`python -c "import pathlib,re,sys; docs=['docs/RELEASE_CANDIDATE.md','docs/PRODUCTION_ACCEPTANCE.md','docs/R3_FAILURE_DRILL.md']; miss=[d for d in docs if not pathlib.Path(d).exists()]; lines=[(d,ln) for d in docs for ln in pathlib.Path(d).read_text(encoding='utf-8').splitlines() if not any(k in ln for k in ('待写','还没写','不存在','待建'))]; bad=sorted({d+':'+p for d,ln in lines for p in re.findall(r'_tools/[A-Za-z0-9_./-]+\.py', ln) if not pathlib.Path(p).exists()}); print('缺文档',miss,'引用了不存在的脚本',bad); sys.exit(1 if (miss or bad) else 0)"`
  方案分四条：**回滚 A**（代码退回上一个可用提交）／**回滚 B**（用发布前的 dump 恢复库）／**前向修复**（数据没错、问题小而明确时宁可再修一版）／**回滚后要做的三件事**。
  ⛔ 这条命令同时钉住一件事：**三份新文档里提到的 `_tools/*.py` 必须真的存在**（标了「待写／还没写」的除外）—— 免得文档里写着一支根本不存在的脚本。

### A 阶段执行记录（2026-09-26，用户原话：「开始写阶段，但只开始 A」）

⛔ 口径：**每一步单独判定**（用户的 A0–A6），任何一步失败**立即停在原地** —— ⛔ 不「先跑后面看看」。
⛔ 只放行 **A**：B（多实例）与 C（故障演练）**未放行**，本记录里不出现它们的任何动作。

| 步 | 做了什么 | 结果 | 证据 |
|---|---|---|---|
| **A0 RC** | 候选记录的 Git SHA 指到本次发布点；新增「**运行时代码指纹**」判据（`git diff <SHA>..<发布点> -- backend/` 必须为空）| ✅ | `docs/RELEASE_CANDIDATE.md` §一 |
| **A1 备份** | `_pre_release.py` → `/opt/sorders-backup/pre_release/20260926T133009Z`（库 526,286 B ／ 上传 105,962,426 B ÷ 2115 文件，sha256 通过）| ✅ | 清单 `_tools/backup/manifests/20260926T133017Z-pre_release.json`：orders=2402 / ledgers=4648 / users=60 / products=37 / tables=44 |
| **A2a 代码落位** | `_release.py --step stage --go`：生产 `git fetch` + `checkout b3dad61`（**不重启**）| ✅ | 生产 HEAD = `b3dad61bbdfa…`；`app/migrations` 在了；**服务仍 active、`/health` 200、版本仍是 0.2.0（跑的还是旧代码）**、`ActiveEnterTimestamp` 未变（仍是 2026-09-23 那次）|
| **A2b 迁移** | `_release.py --step migrate --go` → `prepare_schema`（自愈）+ 8 条版本化迁移 | ✅ | `schema_versions` 1..8 各一行；新增 `outbox_events` / `ai_call_daily` / `schema_versions` / `unit_conversions`（第 4 张是新代码的**模型表**，由运行时自愈建，不是迁移建）；表数 44 → 48；⛔ **业务数据一行没动**：orders 2402 / ledgers 4648 / users 60 / products 37（与 A1 清单逐项相同）|
| **A2c 验证结构** | 第一次 `--step verify --go` **判据报失败** → 停在原地查 → 是**判据错**、不是迁移错；修判据后重跑 | ⚠️→✅ | 见下面「A2c 那一次假红」 |
| **A3 启动** | `--step start --go --sha b3dad61…` → `checkout` + `systemctl restart` | ✅ | `is-active = active`；重启时刻 21:36:06；`/health` 版本从 **0.2.0 → 0.2.4**（＝新代码真的在跑）；启动日志「数据库结构已经是版本 8」＋ 结构化日志 `[rid=…] [cid=-]` |
| **A4 体检** | `--step health --go` → `_health_check.py` | ✅ | 6 项正常 / 2 告警（证书，已知/已接受）/ **0 失败**；数据库探针 = 1、48 表、**迁移版本 8**；发件箱 待发 0 / 已发 0 / 放弃 0 |
| **A5 只读烟测** | 第一次 exit 1 → 查 → 一处判据错（提交号自指）＋ 一处判据过粗（退出码把「不一致」与「既知告警」混在一档）；改判据后重跑 | ⚠️→✅ | `❌ 0 条`；30 通过 / 2 告警（Redis 无口令、MySQL 服务端默认时区 —— 都是既知/已接受）；⭐ 顺带量到：request_id 直连与经 nginx **都原样回来**、生产路由 165 条与快照一致、生产跑的运行时代码与本仓库 **backend/ 零差异** |
| **A6 trace 一单** | 只读那半：三端登录 + **27 条读接口全 200**；有限写那半（按 `PRODUCTION_ACCEPTANCE.md` §三）：建 1 单 → 派 1 次 → 撤 1 次，只动测试账号；然后 `_trace_order.py SO202609264191401979`（在**生产机上**跑，那个工具读库）| ✅ | 4 行审计带 `command_id` + `request_id`（`order.create#528a7c69` / `order.assign#1b9da010`）；3 条发件箱事件全部 `sent`、重试 0；通知 8 条；⭐ **三个 request_id 与客户端拿到的 `X-Request-ID` 是同一串**；⛔ 测试单已撤（CANCELLED），`ledgers 4648 → 4648`（一分钱没动）|

⭐ 原始输出（每一步的命令与输出、库端对账、以及 ⛔ 这份证据证不了什么）：`docs/R3_A_RELEASE_EVIDENCE.md`。

#### A 做完之后：「Production Runtime Proven」勾选表（用户 2026-09-26 要求单列一张）

⛔ 以后**不许**再用一句「生产已经上线」代替它 —— 这一张表就是「生产运行」这四个字的定义：

| # | 勾选项 | 状态 | 证据 |
|---|---|---|---|
| 1 | Backup verified | ✅ | `/opt/sorders-backup/pre_release/20260926T133009Z`（sha256 通过；清单进库）|
| 2 | Migration verified | ✅ | `schema_versions` 1..8；`status --json`：待跑 0 / 漂移 0 / 陌生版本 0 |
| 3 | Application started | ✅ | `is-active=active`；`/health` 版本 **0.2.4**（≠ 旧 0.2.0）|
| 4 | Health verified | ✅ | `_health_check.py`：6 正常 / 2 已知告警 / **0 失败** |
| 5 | Read-only smoke verified | ✅ | `_prod_smoke.py --readonly`：**❌ 0 条** / 2 既知告警 |
| 6 | Trace verified | ✅ | 一条命令打完整条链，4 行审计带两个号；事件 `sent`、通知 8 条 |
| 7 | Business write smoke verified | ✅ | 建 1 单 / 派 1 次 / 撤 1 次（只动测试账号）；测试单已撤、钱没动 |
| 8 | Socket verified | ✅ | **2026-09-26 B 段实测**：A→B 与 B→A 两个方向都收到（raw WebSocket 直连两个实例；机制在隔离 db 1 上验一次、真拓扑 db 0 上再验一次）|
| 9 | Multi-instance verified | ✅ | **2026-09-26**：两个 unit（A :8111 / B :8112）＋ nginx `upstream`＋**摘机测试**通过；⛔ 同机两进程，**跨主机未验** |
| 10 | Failure drills verified | ❌ | **C 段已执行**（2026-09-26）：五条在生产上真跑过，**4 条通过**；⛔ **event-delay 不通过** —— 演练要证的是「故障**能被发现**」，而它抓到的恰恰是「**发现不了**」（投递失败被 python-socketio 吞掉、事件被记成 `sent`）。这一格因此**算不过**，即使演练本身做完了 |

⇒ **9 / 10**（B 段又关掉两条）。⛔ 但「Production Runtime Proven」**不许简化成这一个分数** —— 用户 2026-09-26 要求按四块分开写：

| 块 | 状态 | 说明 |
|---|---|---|
| **Production Runtime Foundation** | ✅ **9 / 10** | 上面那张勾选表：备份 / 迁移 / 启动 / 体检 / 只读烟测 / trace / 写烟测 / **socket** / **多实例** 已 ✅；只剩**演练** ❌ |
| **Business Write Correctness** | ⛔ **未充分证明** | 这次的测试单**没送达、没收款** ⇒ `ledgers` / `driver_bills` **0 行**。⛔ **「没覆盖」≠「有问题」** —— Money 那一格是**未知**，不是 ❌ 的缺陷 |
| **Multi-instance Runtime** | ✅ **已证明（同机）** | 2026-09-26 B 段：两个实例 + socket 双向实测 + nginx upstream + 摘机测试。⛔ **跨主机未验**（共享盘 / 跨机选主 / 远端 Redis 都没做）|
| **Failure Recovery** | ⛔ **未证明** | 五个故障演练 + **备份的隔离恢复验证**（**C 段**，等 B 验收后再放行）|

#### A2c 那一次假红（判据错，⛔ 不是生产错）

`verify` 原来的判据是「`status` 的输出里必须有『待跑：0 条』」。而 `status` 里那一行是
`if st["pending"]:` **才打**的 ⇒ **迁移越干净，这句话越不出现**，判据**必然误报失败**。
生产实测输出（库其实已经是 8/8）：

```text
当前版本：8
已应用：8 条
  ✅ 001 baseline（0 ms，f5af981021b7）
  …（8 条全 ✅，各自带校验和）…
```

**怎么处置的**（⛔ 不是「绕过」）：判据改成读 `status --json` 的**结论** ——
`pending` / `drifted` / `unknown_in_db` 三个列表都空、且 `current` == **本仓库迁移头**；
并抽成**纯函数** `verify_verdict()` 进 `--selftest`（新增 6 条用例，自检 17 → **23** 项全过）。
根因是「判据写出来**从没被真输出验过**」，所以修法不只是改一行，是让它**可被自检**。
⛔ 判据是**变强**了：原来只核一句中文措辞，现在还核漂移、库里陌生版本、以及与仓库迁移头是否一致。

### 现场只读核对（2026-09-26，用户拍板③「生产只读放行」）

⛔ 上面八条退出条件**一条都没做**（它们要写操作：备份 / 迁移 / 启动）。用户放行的是**只读**那一半，
所以这里如实分开记：**只读核对做完了、写阶段一步没动**。

工具（新）：`python _tools/ops/_prod_smoke.py --readonly` —— 一段固定的只读脚本，八项各有真探针，
原始事实可 `--json` 留档；`_tools/ops/_check_ops.py` 逐条钉着它「一句写操作都不许有」。

| 核对项 | 实测（2026-09-26） |
|---|---|
| 版本 | 生产 `648fbf8`（2026-09-23，分支 new）—— ⛔ **落后本仓库 HEAD 293 个提交**（⚠️ 这个数会随提交继续涨，现算用 `git rev-list --count 648fbf8..HEAD`）；跟踪文件没被手改过 |
| 依赖 | 生产 49 个包；**15/15 运行依赖落在声明区间内**（`cryptography` **43.0.3** ∈ `>=42,<44`）；9 条开发依赖没装（正常） |
| migration | ⛔ 生产**没有** `app.migrations` 模块、库里**没有** `schema_versions` 表 ⇒ R3-01 还没上生产 |
| DB | ✅ 可达；44 张表 / 11.6 MB；⚠️ `time_zone = SYSTEM`（不是 UTC）；⛔ 没有 `outbox_events` 表 |
| Redis | ✅ PONG（6.2.20）；keyspace **空**；⚠️ 无口令（既知） |
| nginx | ✅ 1.20.1，247 行配置；`proxy_pass http://127.0.0.1:8000`（单后端）；⛔ 无 `upstream` / 无失败摘除 |
| uploads | ✅ 2115 个文件 / 187M（⛔ 没做写入探测 —— 「可写」本轮没验） |
| trace | ⛔ 生产 `operation_logs` **没有** `request_id` / `command_id` 列、代码里没有 `app/core/request_id.py`、带 `X-Request-ID` 打过去响应头里也没有它 ⇒ R3-04 那一层还没上生产 |
| 现状健康（另外量到的） | 服务 active、`/health` 200、磁盘 29%（可用 27G）、备份 10 份 / 208M（⚠️ 备份年龄是会变的数，以 `_health_check.py` 当场打印的为准）|

完整证据（含全量 `pip freeze` 与「这一次证不了什么」）：`docs/R3_PROD_READONLY_EVIDENCE.md`。

- ✅ 只读烟测**脚本**在位、且被机器钉成只读（八项各有真探针，探针清单与脚本声明互相对账）—— 复现：`python _tools/ops/_check_ops.py --check`
  ⛔ 这一条证的是**工具**（它只读、覆盖面在），**不证**「生产验过了」—— 那要写阶段的许可。

## R3-06 Failure Drill

**2026-09-26 C 段：五个演练在**生产机**上真跑过**（每条六阶段 X0 前置 → X1 基线 → X2 注入 → X3 观察 → X4 恢复 → X5 核业务状态）。
逐字原始输出在 `_tools/ops/drill_records/*.json`（进仓库），汇总与「证不了什么」见 `docs/R3_FAILURE_DRILL_EVIDENCE.md`。
结论 **4 ✅ / 1 ❌** —— ⛔ 那个 ❌ **是演练抓到的真缺陷**（发件箱把「投递失败」记成了「已发送」），不是「没跑」。
演练前先备了份：`/opt/sorders-backup/pre_release/20260926T150728Z`（orders=2403 ledgers=4648 users=60 products=37 tables=48）。
工具：`python _tools/ops/_drill.py`（不给 `--go` 只打印；`--target prod` 要 `--go` + `--i-know-prod` 三个信号；
`--verify` 在 **CI 侧**核记录 —— 六阶段齐 + 必须的信号在 + 结论 pass，⛔ 不连生产）。

- ✅ 故障演练工具在位、护栏自检 12/12、五个本机预演 5/5、且**生产演练真跑过并留了记录** —— 复现：`python _tools/ops/_drill.py --selftest`
  ⛔ 这一条证的是**工具与护栏**；生产那五条各自另有下面那五行。

- ✅ Drill A：杀掉一个 worker，是否恢复 —— 复现：`python _tools/ops/_drill.py --verify worker-crash` → `1/1`
  ⭐ 生产实测（`worker-crash-20260926T151826Z.json`）：`systemctl kill -s KILL sorders-api-a` 之后 50 次采样 × 0.5s ——
  **B 全程 50/50 = 200**、**经 nginx 的入口 50/50 = 401（一次 5xx 都没有）**、被杀实例 `10 activating / 40 active`、
  **NRestarts 0→1、恢复 5.5 秒**（对上 `RestartSec=5`）、X5 业务行逐项一致。
  ⚠️ 要点：`proxy_next_upstream` 把「连不上 A」当场重试到 B ⇒ 客户端整段窗口**一个错误码都没看到**。
  ⛔ 证不了：杀的是**两个独立 unit 里的一个**（生产不是「一个 systemd 里 2 个 worker」，形态不同）；不证跨主机；不证真机体感。
- ✅ Drill B：Redis 不可用，业务还能不能工作 —— 复现：`python _tools/ops/_drill.py --verify redis-down` → `1/1`
  ⭐ 生产实测（`redis-down-20260926T151904Z.json`）：停 Redis 期间 `PING=Connection refused`、两个实例的 `/health` 都变 `"redis":"error"`（**如实报出来了**），
  而业务照常：登录拿到 155 字符 token、`/users/me` 200、读订单 200、读账本 200、**写一条消息也 200 且行真的在库里**（id 41732）；恢复后 `PONG`/`channels=socketio` 全回来。
  ⚠️ 方案里「生产 Redis 没人用」那条前提**已过期**：B 段之后 Socket.IO 的跨实例总线就是它（`pubsub channels` 里的 `socketio`）。
  ⛔ 证不了：只证「不可用」不证「慢」；不证 App 端「推送晚到」的体感。⚠️ 另有一条**未定**（`R_NUMSUB=1`，见证据文档 §四）。
- ❌ Drill C：事件消费延迟，业务数据是否仍然正确 —— 复现：`python _tools/ops/_drill.py --verify event-delay`（⛔ 现在会红，**红得对**）
  ⭐ 生产实测（`event-delay-20260926T151742Z.json`）：**5/6 信号** —— 业务写入 ✅、追平/不重复/净零 ✅、X5 ✅；
  ❌ 而 **「投递失败要被发件箱看见」不成立**：停 Redis 期间写的那条事件被记成 `sent attempts=0`，
  同一时刻日志里是 **16 条** `Cannot publish to redis... giving up`。
  ⇒ **真缺陷**：python-socketio 的 Redis manager 把 publish 失败自己吞了（记日志、不抛异常），
  于是 outbox 看到「成功」，重试/退避/`failed`+`last_error` 一条都不触发 —— 正是 outbox 模块开头点名要治的病，
  边界治住了业务事务与事件，却在**最外层的 emit** 上漏了回来。后果：跨实例那条推送**永久丢掉且没有任何地方记着**（站内信行还在，伤的是实时性不是数据）。
  ⛔ **本轮只记录、未改代码**（核心区冻结中）；修法方向与判据写在 `docs/R3_FAILURE_DRILL_EVIDENCE.md` §三·发现 2。
- ✅ Drill D：迁移锁竞争，第二实例是否正常等待 —— 复现：`python _tools/ops/_drill.py --verify lock-contention` → `1/1`
  ⭐ 生产实测（`lock-contention-20260926T151551Z.json`，6/6 信号）：一条连接先拿住 `sorders_migrations` 15 秒，
  两个迁移进程同时开跑（第二个换 TMPDIR ⇒ 各有一把本机 flock，把「两台主机各自一把」还原出来）：
  **T+6s 时 A=alive、B=alive（都在等，不是撞车失败）**、`IS_USED_LOCK=2157`、三轮都是 `A_RC=0 / B_RC=0`、
  `VERSIONS_SUMMARY=8/8`（每个版本恰好一行）、`ALREADY_EXISTS=0`、`IS_FREE_LOCK=1`、X5 逐项一致。
  ⚠️ **同一次演练抓到发现 1**：三轮里每轮都有 1~2 处**并发 DDL**（1213 死锁 / 1684「concurrent DDL statement」），
  根因是自愈 bootstrap 的 DDL 只受 `/tmp` 那把**本机** flock 保护（`schema_bootstrap.py:232`），服务端 `GET_LOCK` 是**之后**才拿的。
  ⚠️ 生产现状是**同机两个 unit**（共享 `/tmp`）⇒ **没中招**；这是「跨主机多实例」的具体拦路石，与 `MULTI_INSTANCE_READINESS.md` 的 `bootstrap-self-heal` 那一格对得上。
- ✅ Drill E：磁盘将满，能否被发现 —— 复现：`python _tools/ops/_drill.py --verify disk-full` → `1/1`
  ⭐ 生产实测（`disk-full-20260926T151953Z.json`，6/6 信号）：31% → **92%**（剩 3.3G）→ 删掉后回到 **31%**；
  把 cron 那一行命令原样跑一遍：**退出码 1**，磁盘告警真的落进 `/var/log/sorders-health.log`；最紧张的当口 MySQL 照常读出 2403。
  ⚠️ 计划推 87%、实测 92%（`df -k` 与 `df -h` 取整之间的差）；⛔ **刻意没撞 95%** 失败线（那要把在跑的 MySQL 所在盘压到剩 ~1.5G，不可接受）。
  ⛔ 证不了「有人被叫醒」：告警落**日志文件**，**没有**邮件/IM 通道 —— 这是**发现的缺口**，如实记，不粉饰。

## R3-07 Meta-System Hardening

指南 §二十一 的四条 + §二十二 的依赖决策。**a / b / c / d / e 五项都已落地**（依赖决策 2026-09-26 拍板，见 `docs/DEPENDENCY_DECISION.md` §七）。

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

- ✅ **反向验证的注入锚点不许腐烂**（R3-07b2）—— 复现：`python _tools/qa/_check_reverse_verify_anchors.py`
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
  判据 55 项仍全过、反向验证 13/13 全红。
  ⏳ 再修 2 份（累计 **7/11**）：⑥ `category_roster`：④ 号注入报了「（没有任何判据承认这条注入）」，其实判据**红了**
  （退出码 1），只是报的是它自己那条具体规则「提交顺序没走 `submittableIds`」而不是当年那句泛泛的「继承共用内核的名册页只有」——
  期望词过期，按实际行为改 → 4/4。⑦ `inline_role_gates`：② 的期望词同样过期（判据报「声明已收敛…体内还有 1 处」，比
  当年的「涨到 45 处」更具体）；③④ 是**锚点写死了台账尾部**（台账后来又追加了 4 条 ⇒ 出现 0 次 ⇒ 恒 SKIP），
  改成**从判据源码现取**（`_ledger_tail()`）；⛔ 顺带踩到一个细节：`LEDGER_REASON` 不能取「最后一条」——
  后面的条目是**多个字符串拼起来的**，只缩短其中一段整条照样超下限 ⇒ ⑦ 号注入变假绿；改成取**第一条**（单串）→ **10/10**。
  ⏳ **还剩 4 份**（都是「注入生效但**没有任何判据报红**」= 判据真缺规则/测试，不是锚点问题）：
  · `audit_coverage`：「豁免表里的模块其实还在写日志」——判据没有「豁免条目必须真的没在写日志」这条；
  · `permission_points`：「说明表里的权限点从枚举里删掉」——判据没有「说明表的键必须还在枚举里」这条；
  · ~~`r3_constraints`：禁做 #15 没有探针~~ → **本轮修好（9/11）**：探针**早就有**，但它的第一句是
  「`docs/DEPENDENCY_DECISION.md` 存在就放行」—— 我那轮建了那份**证据文档**，于是它**永久 hold** ⇒
  反向验证里「顺手锁死一条」变成打不动判据的假绿。⛔ **文件存在 ≠ 决策做了**。
  处置：`docs/DEPENDENCY_DECISION.md` 里加一行**机器读的状态**（`> **状态**：待用户拍板`），探针改成只读那一行；
  拍板后把状态改成「已拍板」它就放行。⛔ 而且第一版探针写的是 `"已拍板" in 整份文档` —— 文档的说明文字里
  就写着「拍板之后把这一行改成『已拍板』」⇒ 永远为真（**第二次踩**）；改成只读**那一行**才对。→ 9/9。
  · ~~`audit_coverage`：缺「豁免表里的模块必须真的没在写日志」~~ → **本轮修好（9/11）**：那条判据（②b）**早就有**，
  错的是**注入**：它塞的 `stats.py` 里**一处 `write_log(` 都没有**（实测 0 处），塞进豁免表本来就是合法豁免
  ⇒ 判据不红是对的。⛔ 同一个坑第二次（判据注释里记着上一次是 `arrears.py`）—— 改成塞 `products.py`（4 处）→ 10/10。
    · ~~`permission_points`~~ → **修好（10/11）**：化石规则**早就有**（`DECLARED_ONLY` 里有表外的键就红），
  错的是**注入**：它只做「把枚举里那条删掉」，而 `DECLARED_ONLY` 现在是**空表**（所有权限点都被引用了）
  ⇒ 删完既没化石也没别的规则会响，判据全绿是对的。改成**自带前提**（往说明表里塞一条根本不是权限点的条目）→ 4/4。
  · ~~`round17`~~ → **修好（11/11）**：红线 §25b 那条判据**比自己的名字弱** —— 它要求「文件里有 `with_for_update()`，
  且 400 字符内有 `DriverBillType.SALARY`」，而那个文件里有**两处** `with_for_update()`（锁司机行、对已存在月薪单的
  加锁读）⇒ 删掉司机行锁之后另一处照样满足正则。改成拆三件事：① 有「锁司机行」这个调用、② 有月薪单**存在性查询**、
  ③ **锁在查询之前**。⛔ 收紧过程本身踩了两次：`[^)]*` 跨不过 `.where(…)` 的括号（连干净源码都判红）、
  以及拿裸的 `DriverBillType.SALARY` 比顺序（它在文件里更早就出现过）—— 两个都记在判据注释里。
  ⭐ **11/11 全部修完**，每一份都用 `_reverse_verify_all.py --only <名字>` 跑过 **1/1 达标**；
  其中 5 份是锚点/期望词过期、8 份是「判据其实有牙、探针或注入写错了」，还有 2 份（`list_order`/`round17`）
  **确实把判据收紧了**（收紧后判据在干净源码上仍然全绿：红线 1282 项、`_check_list_order` 55 项）。
  · `round17`：「月薪单生成前不锁司机行」——修复**没有被任何测试钉住**（要补一条并发回归）。
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
- ✅ 依赖可复现性决策（开区间 vs pin，三处版本是否一致）—— **已拍板**：本轮**不锁**（保持开区间）＋ `cryptography` 以**生产真实版本**为准 —— 复现：`python _tools/qa/_check_r3_constraints.py`
  ⭐ 生产那一格量到了：**43.0.3 ∈ `>=42,<44`**（15/15 运行依赖全在区间内）—— 四条拍板与落地记在 `docs/DEPENDENCY_DECISION.md` §七。
  **前半（证据 + 判据）已就位**：① 三处版本摆齐（声明 / 本机 / CI；**生产那一格空着** —— 要 R3-05 上机器 `pip freeze`）；
  ② 机器判据 `python _tools/qa/_check_dep_declaration.py`（24 条声明逐条对**本机实际装的版本**，不成立的必须
  登记 + 写「什么时候删掉这一条」+ 棘轮只减不增（=1）+ 防化石），反向验证 6/6；
  ③ 实测抓到一处真不一致：`cryptography` 声明 `>=42,<44`、本机是 **48.0.0**（高 5 个大版本），
  上限来自 `f20b93a`「初始提交 v0.01」（2026-04-09），仓库里找不到理由 —— 已登记为例外，⛔ 不自己改。
  **用户 2026-09-26 拍板四条**（原话「① c ② 不要 lock ③ 只读放行 ④ 要 push」）→ 逐条落地记在
  `docs/DEPENDENCY_DECISION.md` §七。
  ⭐ **生产那一格量到了**（决策③ 只读放行）：只读烟测逐条对账 → 生产 **15/15 运行依赖全部落在声明区间内**，
  其中 `cryptography` = **43.0.3**（∈ `>=42,<44`）—— ⛔ 也就是说：**声明没有错，偏差在「本机 48.0.0」这一头**。
  按本机去改声明，等于拿本机的偏差去改一件生产上本来正确的事（决策①「不凭本机猜生产」拦的就是这个）。
  往哪边对齐（放宽声明 / 降本机 / 上 lock）留到**专门的依赖治理那一轮**（决策② 本轮不锁）。
  原始数据：`docs/R3_PROD_READONLY_EVIDENCE.md` §二.2（含全量 `pip freeze` 49 个包）。
  ⚠️ 探针也跟着改了：`_check_r3_constraints.py` 的 R3-D15 现在**读出决策的内容再判**（写「不锁」⇒ 继续拦 `==`；
  写「要锁」而判据还没实现「锁定后该核什么」⇒ 报红）—— ⛔ 拍板 ≠ 放行，反向验证 ⑧ 仍然 9/9。

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
5. ⛔ **改任一张矩阵，必须在同一个提交里把 `docs/RECTIFICATION_REPORT_R3.md` §12 的嵌入副本一起改**
   （照抄，不许改写）。这一条是**踩过才写的**：2026-09-26 报告 v2 里 §2.3 写 R3-02 ✅ 7/7，
   而 §12.1 矩阵还写着 `Capability UI` / `Capability Audit` = ❌ ——
   矩阵写于 R3-02 **动工之前**，做完后只补了里程碑小节、没人回头改矩阵，
   于是「正文说做了、矩阵说没做」在**同一个文件**里共存了一整天。v2.1 已改正（两边逐字一致）。
6. ⛔ 矩阵里**每一格都要有出处**：新增的「依据 / 出口」列要么写得出判据文件名，要么写得出它在**哪一段写阶段**关掉。
   判据改名或删掉时，这一列跟着改 —— 否则 ✅ 会变成一句没人能复现的话。
7. ⛔ `代码 ❌` 不许只写 ❌ 了事：要写清是**还没做**，还是**根本没有静态判据、只能真跑**
   （`Scheduler` / `Upload` / `Socket multi-instance` 是后者）——
   两种情况混在一起，读表的人会把「本机真跑过」读成「什么都没做」。

