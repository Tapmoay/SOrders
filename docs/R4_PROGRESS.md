# R4 第四轮整改进度与退出条件台账

> **规则**：这份文件是「已完成」三个字的唯一出处。⛔ **没达到退出条件的里程碑就是没完成**，
> 不许用「已经差不多了」。
> **冻结基线**：`c67b2cf`（R3 的收口提交）｜**指南**：`C:\Users\Optimistic\Desktop\ppkk.md`
> → 已归档 [ARCHITECTURE_RECTIFICATION_R4.md](ARCHITECTURE_RECTIFICATION_R4.md)
> （**文件 = 指南逐字节原文 + 施工方附录 A**：原文 26669 字节 / 1599 行 / SHA256 `E45A6CAF01143418BDB5F20D36401382456754C267367424B3FAE91D9DA230E0`；
> 核它对不对：`git show HEAD:docs/ARCHITECTURE_RECTIFICATION_R4.md > /tmp/g.md; python -c "import hashlib;print(hashlib.sha256(open('/tmp/g.md','rb').read()).hexdigest().upper())"`）
> **基线快照**（机器采集，⛔ 不是手写）：`_tools/baseline/r4-before/2026-09-27/baseline.json` +
> [R4_BASELINE.md](R4_BASELINE.md)
> **事实优先**：每一行的 `复现：` 后面必须是**真能跑**的命令；跑不通就是 ❌，不许写 ✅。

---

## R4 的**两个命题**（用户 2026-09-27 拍板把它拆开）

> 用户原话：「这不是说 R4 "没完成"。而是把两个不同命题拆开：
>  『**模块化设计真的成立了吗？**』—— 已经证明。
>  『**这个模块化设计能安全接入真实钱路吗？**』—— 还没证明。这个区分一定要保留。」

| 命题 | 状态 | 出口 |
| --- | --- | --- |
| **R4 Structural Proven**（核心/扩展边界 · 契约 · 防火墙 · 注册表 · Add / Replace / Remove / Compatibility） | ✅ **已证明** | 本文件上面那 8 个里程碑 + 验收矩阵 |
| **R4 Production Integration** | ⏳ **进行中** | 见下面「R4-PROD-INTEGRATION」一节 |

⛔ 两条读法都必须守住：**不要把"生产未接线"写成 R4 的失败**；
也**不要把"结构已证明"读成"生产已经安全"**。

---

## R4-PROD-INTEGRATION（很窄的一阶段：结构 → 真实钱路）

用户 2026-09-27 拍板：**不开泛化的 R5**。现在缺的不是一个新的架构主题，
而是「拿一个真正重要的能力，把这个架构接到现实里」。

     R4 Structural ✅
            ↓
     R4-P0 Governance Close            ← ✅ 已完成
            ↓
     R4-P1 Production Pricing Readiness ← ⏳ 进行中
            ↓
     R4-P2 Production Canary
            ↓
     R4-P3 Full Cutover
            ↓
     R4 Production Proven

⚠️ **里程碑编号的约定**（先说清，免得看起来像漏标）：本阶段是 R4 的**子阶段**，⛔ 不是 R5。
而仓库的跨轮棘轮 `_check_r3_constraints.py::probe_commit_milestone_tag` 只认
`R[3-9]-0\d` 这一种形状 —— R4 这一轮只有 `R4-00`…`R4-09` 十个槽，而 `R4-00`…`R4-08`
在上一段已经用完。所以**本阶段的提交统一标 `R4-09`**，
具体是 P0 还是 P1 写在提交标题的后半句里。
⛔ **我们没有为了让自己的提交变绿去放宽那条正则** —— 棘轮红了就改提交，不改判据。

---

### R4-P0 Governance Close —— ✅ 已完成

| 项 | 交付 | 出口证据（可复现） |
| --- | --- | --- |
| **P0-1** | `socket_io.py` 升**证据档**：动它的例外必须写全**四格**（证据 / 原因 / 范围 / 影响面运行时证明） | `_check_core_freeze.py` 第 6 组（`_EVIDENCE_REQUIRED`）——复现：`python _tools/qa/_check_core_freeze.py`；反向验证 `python _tools/qa/_reverse_verify_core_freeze.py` → **14/14** |
| **P0-2** | CI 措辞修正：⛔ 不写「CI 全绿」 | 见本文档「验收矩阵」的**读表须知** |

---

### R4-10 Milestone Tag Grammar v2 —— ✅ 已完成（2026-09-27）

用户 2026-09-27 拍板：「**② 里程碑编号采用 (b)：把 `R4-00…R4-09` 的 10 槽限制正式放宽为
`R4-00…R4-99`。⛔ 不要选 (a)，也不要用 (c) 冒充 R5。**」
并要求「**不能只改正则**……这次应该把它作为一个正式的小治理变更：Milestone Tag Grammar v2」。

| 规矩 | 判据在哪 |
| --- | --- |
| ① 形状 `R<3-9>-<两位数字>`，且**独立成词**（`R4-100` / `R4-A0` / `R10-01` 都不合法） | `_tools/qa/_milestone_tag.py`（语法**只有这一处定义**，判据与反向验证都 import 它） |
| ② 每条提交都要有（v1 就有，⛔ 不放宽） | `_check_r3_constraints.py::probe_commit_milestone_tag` |
| ③ **不许重号**：v2 生效之后每条提交的编号必须唯一 | 同上（从「标题里写着 `Milestone Tag Grammar v2`」那条提交起算，**不翻旧账**） |

出口证据：`python _tools/qa/_reverse_verify_r3_constraints.py` → **19/19**
（10 种破坏 + **8 条单元断言**）。
⭐ 那 8 条是这次特意加的：用户点名要的六个样例（`R4-10` / `R4-27` / `R4-99` 必须**合法**；
`R4-100` / `R4-A0` / `R10-01` 必须**不合法**）只有单元断言证得了 ——
⛔ **"该允许的必须允许"没法用"注入→变红"来证**：一条把所有东西都判红的正则，在注入测试下是**全绿**的。
另加两条重号判定（同号两行要报、不重号必须返回空，⛔ 不许乱报）。

⚠️ 编号顺序与用户给的草案差一格（草案 R4-10 = Freight Provenance Schema）：
**实际施工顺序是先治理后 schema**（用户 §16 的顺序 ①→②），所以 R4-10 落在语法变更上，
schema 顺延到 R4-11。用户明确说过草案「以真正施工顺序为准」。

---

### R4-11 承运运费来源凭据（freight provenance）—— ✅ 已完成（含生产发布，见 ③）

用户 2026-09-27 拍板：「**① §6 做。**」+ 五条退出条件 P1-02a…e。
审计（R4-09）查出来的那个缺口：`orders.freight_fee` 有金额、有分类，
**没记是哪一条价目产生的**，全库也没有任何一处记「按哪一版计价契约算的」。

| 退出条件 | 交付 | 出口（可复现） |
| --- | --- | --- |
| **P1-02a Schema** | `orders.freight_rule_snapshot TEXT NULL` + 线上迁移 | `python _tools/ops/_migration_tests.py --fresh/--old/--concurrent/--fail-fast` |
| **P1-02b Write Atomicity** | 三个写入点都走唯一写入口；全仓 `.freight_fee =` 只许出现在 `order_money.py` | 判据第 3 组；`backend/tests/test_freight_provenance.py` |
| **P1-02c Provenance Completeness** | 快照能恢复：来源 / 计价方式 / 契约身份与版本 / 计费上下文 / 金额 / **哪一条价目** | 判据第 3 组**现场把写入口跑一遍**（⛔ 不是文本匹配），逐键核 |
| **P1-02d Legacy Safety** | 老单该列 NULL：读得出、改得动、⛔ **不回填** | 用例 + 判据「迁移**不回填老数据**」 |
| **P1-02e Reverse Verification** | 缺快照 / 金额与凭据错位 / 绕过写入口 / 来源改裸串 / 回填老数据 —— 各自报红 | `python _tools/qa/_reverse_verify_pricing_provenance.py` → **11/11** |

⛔ **本轮只补「记事实」，不改任何算法**（用户 §14：风险 A「记录事实失败」与
风险 B「金额变化」不许一起发布、一起排查）。后端用例 **1079 passed**（R4-09 之后 +7）。

⚠️ 顺带记一条**本轮没动的既存观察**：`schemas/order.py::OrderCreate.freight_fee` 是个**没人读的入参**
—— 下单时传它不会写进订单（真正写运费的是后面三个写入点）。所以"下单就带运费"这件事
**今天是不生效的**，而客户端看不出来。与本轮改动无关，留给你拍板。

**P0-1 的关键一条**是那两个**成对**的注入：同一份"老式一行声明"，
对 `business_time.py` **绿**、对 `socket_io.py` **红** ——
它证明**升的是这一档，不是把判据整体收紧**（用户明确要求：只扩这一项，不重新扩大整个核心区）。

⚠️ **一处如实更正**：上一轮我在报告里说「`socket_io.py`……核心区清单的**骨架判据**只钉了 8 项」
—— 那句话写得有歧义，读起来像"它不在骨架里"。**事实是：它从 R4-00 起就在 `_SKELETON` 里**
（8 项之一，见本文件 R4-00）。P0-1 真正补上的是**更强的那一档**：
一行"为什么"不够，要四格。判据与写法写在 `docs/CORE_AND_EXTENSION.md` §2.2。

---

### R4-P1 Production Pricing Readiness —— ⏳ 进行中

| 项 | 状态 | 证据 |
| --- | --- | --- |
| **① 计价事实（provenance）审计** —— 用户点名的"**比发布更重要**的问题" | ✅ **已出结论** | `docs/R4_PRICING_PROVENANCE.md`；判据 `python _tools/qa/_check_pricing_provenance.py`（43 个金额列全部归类）+ 反向验证 `python _tools/qa/_reverse_verify_pricing_provenance.py` → **7/7** |
| ② Pricing Golden Set（脱敏真实样本，Legacy vs Extension **逐笔**比） | ⏳ 未开始 | — |
| ③ Shadow 对照计算（**⛔ 不写 Ledger**，只 calculate / compare / record） | ⏳ 未开始 | — |
| ④ 发布演练（`release → rolling restart → health → smoke → rollback`） | ⏳ 未开始 | — |

**① 的结论一句话**（全文见那份审计）：

- **司机应得**那一路 —— ✅ **齐**：`orders.driver_rule_snapshot` 定格规则、
  `driver_bills` 另存 `rule_id`/`rule_name`/`piece_amount`/`commission_amount`、
  算钱那一步只认快照（`order_pay(rule: PayRule | None, …)` 拿不到活配置）；
- **承运运费**（`orders.freight_fee`）—— ⚠️ **只记金额，不记是哪条价目**；
  而价目可以被就地改价（`orders_assignment.py:186` `existing.fee = …`）；
- **计价契约版本** —— ⛔ **三处都没有**（列 / 快照写入器 / 账本结算，全都没有）。

⇒ 按用户 §5 的拍板：**先补齐事实记录，再接生产**。
补法**建议**见 `docs/R4_PRICING_PROVENANCE.md` §6（**建议，未施工** ——
它要动核心区 `schema_bootstrap.py` 且改钱的口径，属于"单独一轮 + 单独发布 + 单独演练"）。

⚠️ 那份审计也**如实写着它证不了什么**（没查金额对不对 / 没连生产库 / 没替用户拍板 / 票据类没历史）。

---

### ③ 生产 schema-only 发布 —— ✅ 已完成（2026-09-27）

用户 2026-09-27 放行「③ 单独发布 schema-only 变更」。**发布点 = `ca5e49f`**
（`docs/RELEASE_CANDIDATE.md` §一 记的就是它；之后只推了文档/工具提交 ⇒
`git diff --stat ca5e49f..HEAD -- backend/` **为空**，"运行时代码指纹"那条判据成立）。

走的是仓库自己的八步发布器 `_tools/deploy/_release.py`（护栏自检 **32/32**），**逐条留原始输出**：

| 步 | 结果 |
| --- | --- |
| 1 backup | `/opt/sorders-backup/pre_release/20260927T020119Z`，db.sql.gz 531,548 B + uploads.tar.gz 105,962,426 B，sha256 校验通过，回滚命令当场打印；清单留档 `_tools/backup/manifests/20260927T020130Z-pre_release.json` |
| 2 stage | 生产 HEAD = `ca5e49f755497e6719aa5c2da79bbf9fd39e35be`；迁移包在；**服务仍 active（跑的还是旧代码）** |
| 3 migrate | `.venv/bin/python -m app.migrations upgrade` → 结构与迁移都已就绪 |
| 4 verify | 版本 **9** == 本仓库迁移头 9；**待跑 0 / 漂移 0 / 陌生版本 0**；009 校验和 `15a7bbb5c92d` |
| 5 start | 滚动重启 **两个**实例（a:8111 / b:8112）：逐个 `is-active=active` + `/health=200` + **滚动全程经 nginx 都有活上游** |
| 6 health | 6 项正常 / 2 项**已知已接受**的证书告警 / 0 失败；**迁移版本 9**；发件箱 待发 0 / 已发 27 / 放弃 0 |
| 7 smoke（只读） | ✅ **ERROR 0 条、未批准告警 0 条**；已批准告警 2 条（Redis 口令 / MySQL 时区，都带批准理由） |
| 8 business（有限写） | ⛔ **没有跑** —— 用户 §16 的 ③ 只要 backup / migrate / health / smoke / rollback evidence，而本次**只加列、不改任何业务行为** |

**发布后的直接证据**（只读探针 `_tools/ops/_prod_column_probe.py`）：

    生产 orders.freight_rule_snapshot 列数 = 1（1 = 在）
    生产 orders 总列数 = 50
    生产 schema_versions 最高版本 = 9

⛔ 为什么单独有这一条：健康检查报的「迁移版本 9」是**版本表**上的事实，
而这次发布要证的是**那一列真的在表上** —— 两件事只差一步，而那一步正是最容易出岔子的地方。

#### 回滚证据（`_tools/ops/_rollback_rehearsal.py`，⛔ 不是一句承诺）

先在**本仓库**把临时库迁到 9（列出现），再让**上一个发布点 `bb671565` 的代码**
（`git worktree`）对着**同一个库**跑它自己的 `prepare_schema` + 读订单：

    [new] 列在：freight_rule_snapshot / 类型=TEXT / NOT NULL=0 / 默认值=None
    [new] 旧口径的 Order 查询跑通：0 行
    [old] 列在：freight_rule_snapshot / 类型=TEXT / NOT NULL=0 / 默认值=None      ← 旧代码没报错
    [old] 旧口径的 Order 查询跑通：0 行

⇒ 「回滚 = 回退代码 + **保留这一列**」是**跑出来的**：可空 TEXT、无 DEFAULT，
旧代码的建表 / 自愈 / 查询全都不碰它。

#### ⭐ 这次发布**逼出来的一个真缺陷**（判据自己的洞，已修）

第 7 步 smoke **第一次是红的**，红在一行：

    ❌ 未批准的告警 1 条：生产路由数 = 仓库最近一次快照（r2-05-after.json）
       —— 生产 167 条 vs 快照 165 条

查下来是**两件事叠在一起**：

1. **快照过期**：仓库里最近一份路由快照还是 R2-05 的（165 条路径）。现算一下 ——
   `_api_contract_snapshot.py --save r4-11-after` → **235 条路由 / 167 条路径 / 0 对遮蔽**，
   与生产实测的 **167** 完全一致 ⇒ 差别只在"快照太旧"，**不是生产与代码不一致**。
   （权威判据是那条 ERROR：「生产跑的运行时代码 = 本仓库（backend/ 零差异）」，它本来就是 0。）
2. ⛔ **审批表里那条批准永远匹配不上**：`APPROVED_WARNS` 的键是「行名一字不差」（那张表自己写着），
   而 `chk()` 传的行名是 `"生产路由数 = 仓库最近一次快照（" + 快照名 + "）"` ——
   把**文件名**拼进了行名。于是快照一换名，一条**已经写好理由的批准**就变成"未批准"，发布被判失败。
   这正是「**永远红的检查 = 没有检查**」那一族。

**修法（两条都做了，⛔ 不是把告警批准掉）**：
① 存一份现算快照 `_tools/qa/_api_snapshots/r4-11-after.json`（告警本身消失）；
② `_prod_smoke.py` 的行名改成**固定**的，快照名挪进**详情**两格（审批表这才真的生效）。
修完重跑第 7 步 → ✅ ERROR 0 / 未批准 0。

顺带修了发布工具里一处**手写的过期期望值**：`STEP_DOC["migrate"]` 写着「版本 0 → 8」，
而迁移头已经是 9 —— 那句话会让操作的人拿着一个过期的期望去判"成功没有"。改成由 verify 自己算。

---

### ④ Pricing Golden Set —— ✅ 已完成（2026-09-27）

用户 §11 点名的那一份。**Legacy vs Extension 逐笔 0 漂移**（15 条语料），全文 `docs/R4_GOLDEN_SET.md`。

| 项 | 交付 | 出口（可复现） |
| --- | --- | --- |
| **候选实现** | `backend/app/extensions/pricing/freight_template.py` —— 把核心的价目匹配**原样搬进** PricingContract v2（⛔ 一行业务规则都不改） | 四个实现：`freight_template` / `per_quantity` / `standard` / `tiered` |
| **语料** | `_tools/qa/_golden/freight_pricing.json`（15 条：8 个桶有样例 + 3 个桶**明确不适用**并写了理由） | `python _tools/qa/_check_golden_set.py --compare` |
| **比对器 + 判据** | `_tools/qa/_check_golden_set.py`（必跑组） | ✅ 语料 15 条 —— match 15 / **mismatch 0** |
| **反向验证** | `_tools/qa/_reverse_verify_golden_set.py` | ✅ **7/7**（三种边界口径被改坏 + 语料缺桶 / 期望改错 / 声明的「不适用」被打脸） |

⭐ **这一格还证伪了我自己的一个猜想**：我以为「价目存三位小数时核心会原样给出、只有候选才量化」，
实测两边都是 12.35 —— 量化发生在**读库**那一步（`Numeric(12,2)` 的结果处理器），两条路都经过它。
Golden Set 的价值不只是「回归」，还是「**证伪**」。

⛔ **它证不了什么，如实记着**（详见那份文档 §5）：不证明「核心是对的」（只证明候选与核心一致）；
不是真实生产数据；⭐ 最大的残余风险是**喂给候选的那份快照是我转录的**（`snapshot_from_db`），
⛔ 不是核心自己导出的 ⇒ ⑤ Shadow 必须用**核心侧构造器**再证一次。

---

### ⑤ Shadow 定价对照 —— ✅ 已完成（2026-09-27）

用户 §7 点名的那一份。**真实订单全量 2116 笔，0 漂移，0 写库。** 全文 `docs/R4_SHADOW.md`。

| 项 | 交付 | 出口（可复现） |
| --- | --- | --- |
| **核心侧快照** | `services/freight_pricing.freight_snapshot_of`，与报价 `quote_for` **共用同一个读取**（`driver_template_ids` / `route_ids_of` / `candidate_templates`） | ✅ Golden Set 换成它之后**仍然 15/15 / mismatch 0** |
| **对照器** | `_tools/qa/_shadow_pricing.py`（`--check` 进必跑组；`--orders` 对真库跑） | `python _tools/qa/_shadow_pricing.py --check` → total 2 / matched 2 / mismatch 0 / **写库：没有** |
| **真订单那一趟** | 生产机上**只读工作树** + 发布 dump 恢复出来的演练库（⛔ `/opt/SOrders` 全程停在 `ca5e49f`、⛔ 不碰生产库） | 原始事实 `_tools/ops/r4_shadow_r417.json` |

**结果（全量，不是抽样）**：

    total 2116 / matched 2116 / **mismatched 0** / error 0 / unsupported 0
    写库前 {"orders": 2403, "ledgers": 4648, "cash_flows": 72, "outbox_events": 27, "driver_bills": 1515}
    写库后 {"orders": 2403, "ledgers": 4648, "cash_flows": 72, "outbox_events": 27, "driver_bills": 1515}
    wrote_anything: false

`total = 2116` = 那份快照里**所有有司机的订单**（2403 张里 2116 张）。

⭐ **同一天把 R4-16 自己记下的最大残余风险消掉了**：喂给候选的快照原来是我转录的
（Golden Set 文档 §5.3 把它记成"最大的残余风险"），现在换成**核心自己导出的**那一份。
⛔ 核心那份**不写 `pricing_kind`**（指南 §13 单向性），由调用方补。

⚠️ 顺带：演练库从 v8 迁到 v9（009 在**生产形状的真实数据**上又跑了一遍，**108 ms**）；
收工后核对 `prod HEAD = ca5e49f`（没动过）、库只剩 `sorders`、`/tmp` 无残留。

⛔ **这一格证不了什么**（详见文档 §4）：不证明候选"更好"（只证明两边一样）；
不证明生产真的会切（**没有接线**）；快照的时间点是 2026-09-27T02:01Z 不是"永远"；
没有覆盖别的 `pricing_kind`；**没有做有限写烟测**（本轮不改任何业务行为）。

---

### ⑥ 发布演练（Pricing Release Rehearsal）—— ✅ 已完成（2026-09-27）

用户 §16 的第 ⑥ 格：「Shadow 通过后再做 Pricing Release Rehearsal」，而且 §3 说得很清楚 ——
**要证的整条链成立**：`release → 滚动重启 → health → smoke → **rollback**`，
⛔ **不产生真实的生产计价切换**。

**演练用的代码**：`2204a47`（R4-17 那一版：核心侧快照 + Shadow 对照器 + 候选实现）。
⛔ 它**不含任何计价切换** —— 生产跑的还是 Legacy。

#### 前半程：发布（全部 ✅）

| 步 | 结果 |
| --- | --- |
| backup | `/opt/sorders-backup/pre_release/20260927T042413Z`（db 530,495 B + uploads 105,224,536 B），回滚命令当场打印 |
| stage | 生产 HEAD → `2204a4795a8d29d23053384023b29967667ea45d`（**只落代码、不重启**） |
| migrate | 结构与迁移都已就绪 |
| verify | 版本 9 == 迁移头；待跑 0 / 漂移 0 / 陌生版本 0 |
| start | 两个实例滚动重启：逐个 `active` + `/health=200` + **全程经 nginx 有活上游** |
| health | 6 项正常 / 2 项已知已接受 / 0 失败 |
| smoke | **ERROR 0 / 未批准告警 0** |

#### 后半程：**回滚**（真回滚，不是"演练一遍命令"）

| 步 | 结果 |
| --- | --- |
| start（回 `ca5e49f`） | 两个实例滚动重启：逐个 `active` + `/health=200` + 全程 nginx 有活上游 |
| health | 6 项正常 / 2 项已知已接受 / 0 失败 |
| smoke | ✅ **32 通过 / 2 告警 / 0 不一致**（⚠️ 必须带 `--at` 才跑得对，见下） |

收工后生产停在**发布点 `ca5e49f`** —— 与演练前一致。

#### ⭐ 这一格**逼出来的一个真缺陷**：回滚根本没法用烟测验收

第一次跑回滚那半程，`smoke` **报红**：

    ❌ 生产跑的运行时代码 = 本仓库（`backend/` 零差异） —— 生产 ca5e49f7 与本仓库的 `backend/` 差 **287** 行

查下来这**不是**回滚出了问题，而是**判据只认本机 HEAD**：
回滚之后生产停在 `ca5e49f`，而本机 HEAD 是更新的 `2204a47` ⇒ `backend/` 当然有差异。
**一个正确的回滚，必然被这条判据判成红。**

⛔ 我**没有**用"从旧提交的工作树里跑"来绕过它（那只是把问题推给操作的人记性）——
给 `_prod_smoke.py` 加了 **`--at <提交>`**："这次要核的是哪一版"。
判据本身一个字没放宽：仍然是「生产跑的运行时代码 == **那一版**，`backend/` 零差异」。
加完之后：`--at ca5e49f…` → **32 通过 / 2 告警 / 0 不一致**。

⚠️ 另一条如实记着：从 `ca5e49f` 自己的那棵树跑烟测，会报 **1 条未批准告警**（生产路由数 vs
R2 时代那份快照）—— 那正是 R4-15 修掉的那个"批准表键把快照文件名拼进去"的毛病，
**发布点那一版自己带着它**。所以"用旧提交的树跑"这条路当时也走不通 —— 两条路都堵，
才逼出 `--at` 这个正确形状。

#### ⛔ 这一格证不了什么

1. **没有产生任何计价切换** —— 生产跑的还是 Legacy（那是 ⑦ Canary 的事）；
2. **没有做有限写烟测**（`business` 那一步）—— 本轮不改业务行为；
3. 演练用的是 `2204a47`，**而 ⑦ 真正要发的那一版还会再改代码**（接线本身）——
   所以这一次证的是"**这条链**成立"，⛔ 不是"接线那一版也一定成立"。

---

### ⑦ Canary：核心的**唯一组装点**（Composition Root）—— ✅ 机制已完成 / ⏳ 生产未开启

用户 §8：「**必须在核心的唯一组装点切换**……不要在 orders.py / driver_pay.py /
accounting_service.py 分别加 if extension_enabled，否则你刚刚建立的 R4 又开始腐烂。」
用户 §9：「**同一订单不能在运行过程中换算法**。」

| 项 | 交付 | 出口（可复现） |
| --- | --- | --- |
| **组装点** | `backend/app/core/pricing_runtime.py` —— `decide()` / `policy_for()` / `canary_percent()` | 判据第 3 组新增 4 项（业务代码里没有开关、`resolve_v2(` 只在装配根…） |
| **装配根接线** | `app/main.py` 注册 `resolve_v2`（**依赖倒置**：核心只留槽位） | `python _tools/qa/_check_extension_dependencies.py` → 8 项全过 |
| **开关** | `freight_pricing_canary_percent`（0..100，⛔ **缺省 0 = 关**） | 判据核"缺省必须是关" |
| **三条写入点** | 全部改问组装点（⛔ 一个 `if` 都没有） | `backend/tests/test_pricing_runtime.py` 6 条用例 |

**Canary 的口径（比"开关"更要紧的三件事）**：

1. **策略是纯函数**：`policy_for(order_id, percent)` 按订单编号分桶 ⇒ 同一次派单里重复问、
   甚至三个写入点分别问，答案都一样（⛔ 不用随机、也不用"这次请求带什么"）；
2. **走契约时金额由契约确认**：派单界面带的数 = 价目算出来的数 ⇒ 快照写
   `pricing.kind="freight_template"` + `contract=PricingContract v2` + `agreed: true`；
3. ⛔ **派单员改过价时以人为准**：金额照样是人的那个数，但快照写 `override: true`，
   并把**两个数都留在 note 里** —— 换"算钱的源"是 ⑧ Full Cutover 的事，
   不是这一格（用户 §14：风险 A「记录事实失败」与风险 B「金额变化」不许一起发）。

**独立契约身份**（R4-11 那条"编一个 PricingContract v1 就是记假事实"在这里兑现了）：
`FREIGHT_KIND_CONTRACTS` 让两条路各自带自己的身份 ——
`legacy_client → FreightPricingCore v1`、`freight_template → PricingContract v2`。

#### ⭐ 这一格**自己撞上了 R4 的防火墙**（如实记着）

第一版我把 `from app.extensions.pricing import resolve_v2` **写进了 `core/pricing_runtime.py`** ——
`_check_all.py` 当场报：

    ❌ 只有装配根（main.py）能 import app.extensions —— 核心反向依赖了具体扩展

修法**不是**把它加进白名单，而是改成**依赖倒置**：核心只留一个
`register_pricing_resolver` 槽位，由**装配根**（`main.py`，与它挂扩展路由同一处）填；
槽位空着时组装点**如实退回旧路**（不是崩，也不是假装算过）。

⛔ **生产还没开**（`freight_pricing_canary_percent` 仍是 0）：开启是一次配置变更 + 滚动重启，
而且要有真实派单才看得出效果 —— 那是下一步的事。
⚠️ 所以上面这 6 条用例是**本机证据**，⛔ 不构成"生产已经在走契约"。

---

### ⭐ 本阶段提交的 CI 结果（R4-09，2026-09-27）

用户 2026-09-27 要求把 CI 那一列的措辞改准（见「验收矩阵」读表须知）。下面是**这一批提交**的实测：

| 项 | 结果 |
| --- | --- |
| 触发提交 / 时刻 | `b2c8c71`（本条记录写下的那一次）／**2026-09-26T23:43:57Z** |
| 落在哪个时间窗 | **16:00Z–24:00Z** —— 正是「UTC 日期 ≠ 业务日期」那个原来必红的窗口 |
| `Gate` #74 | ✅ 六个实质作业全绿（Fast Gate / 后端用例 / AI 读权限对账 / 全部静态检查 / 安卓单测 / 安卓端到端）|
| `Tests (Parallel)` #72 | ✅ |
| **常闸 · 安卓端到端** | ✅ **这一次真的跑了，并且判定通过**（见下面的判据）|

**"真的跑了"是怎么判的（不是看那格是不是绿的）**：`.github/workflows/gate.yml:251-255` 写着
这个作业的四种结局必须分得开，其中两种是**"不许静默绿"**的：
「带理由跳过」发 `::warning title=安卓端到端带理由跳过::`、「模拟器压根没起来」发
`::warning title=安卓端到端这次没跑::`。
⛔ 所以"作业是绿的"**本身不算证据** —— 要看它有没有发那两条注解。
这一次该作业的注解里**只有** Node 20 / setup-java 的版本弃用提醒与一条 runner 镜像通知，
**没有**那两条 ⇒ 判定是「跑通」。

⚠️ 两条如实说明：
① 上一条记录（R4-08 那次）里这格是「**没能起模拟器 = 没跑**」——同一台 runner 换一次运行就好了，
   本轮**没有**去查它为什么时好时坏（那是 runner 侧的事，与本轮改动无关）；
② 本行记的是 `b2c8c71` 那一次的结果。之后每一条提交由它**自己**那次 CI 结果覆盖 ——
   ⛔ 不许拿这一行去证明别的提交。

---

## 冻结基线（R4-00，2026-09-27）

| 项 | 值 | 来源 |
| --- | --- | --- |
| 提交 | `c67b2cfea27c01f184c05f6fba60120c768d6851` | `git rev-parse HEAD` |
| 分支 | `p`（跟踪 `origin/new`，= `c67b2cf`） | `git branch -vv` |
| R3 报告 | v2.6 | `docs/RECTIFICATION_REPORT_R3.md` |
| R3 台账 | 60 ✅ / 0 ❌ | `docs/R3_PROGRESS.md` |
| 静态检查 | 119/119 通过（总耗时 194.2 秒） | `python _tools/qa/_check_all.py` |
| 后端用例 | 1020 | `python _tools/baseline/_capture_baseline.py --tests` |
| 生产 | Production Runtime 10/10（跑过 ✅ + 五个故障演练 5/5 ✅） | `docs/R3_PROGRESS.md` 三层矩阵 |
| 端点 | 229（其中写端点见端点索引） | `docs/R4_BASELINE.md` |

> ⚠️ 基线里有一条**不是 R4 造成的**既存观察，如实记着：安卓最近一次单测报告 `failures=1`
> （`docs/R4_BASELINE.md` 的风险判定第 2 条）。R4 是后端/架构轮，⛔ 不要把这条算到 R4 头上，
> 也不要因为"反正不是我弄的"就把它从基线里抹掉。

---

## R4-00 冻结基线

- ✅ 基线记录落地（提交 / 检查数 / 用例数 / 生产 10-10 全部进上表，数字由工具采、⛔ 不手写）—— 复现：`python _tools/baseline/_capture_baseline.py --tests --label r4-before --out docs/R4_BASELINE.md`
- ✅ `backend/app/core/socket_io.py` **正式加入核心区清单**，并被骨架判据钉住（删条目即报红）—— 复现：`python _tools/qa/_check_core_freeze.py`
- ✅ 「核心区**不是永久冻结**，只经受证据触发的例外修改」写进 `_tools/qa/_core_files.txt` 文件头与 `docs/CORE_AND_EXTENSION.md` §2.1（三条件：有证据 / 只治那个病 / 写下来）—— 复现：`python _tools/qa/_check_core_freeze.py`
- ✅ R3 棘轮窗口跟着 R3 一起收口（右端点写进 `docs/R3_CONSTRAINTS.md`），R4 的改动不再消耗 R3 的额度 —— 复现：`python _tools/qa/_check_r3_constraints.py`
- ✅ 指南原文归档为 `docs/ARCHITECTURE_RECTIFICATION_R4.md`（带来源 SHA256），北极星那一句同页可查 —— 复现：`python _tools/qa/_check_r4_constraints.py`

---

## R4-01 Core / Extension Boundary Map（先划边界，⛔ 不改代码）

**交付**：`docs/R4_CORE_EXTENSION_MAP.md` —— 把系统能力逐项归类为
**CORE / EXTENSION POINT / EXTENSION IMPLEMENTATION / INFRASTRUCTURE**，并给每项写「为什么是这一档」。

**判定规则**（指南 §4，四条）：
1. 它是否**定义系统事实**（订单最终状态 / 账本最终金额 / 谁是谁 / 谁有没有权限 / 事务成不成功 / 事件可不可靠投递）→ Core
2. 它变化时**核心语义是否应该改变** → Core；只改变规则实现 → Extension
3. 这个能力消失以后**核心业务还能不能成立**（Order / Money / Auth / Ledger 仍然成立）→ Extension
4. 插件**是否应该能够决定核心事实** → 只要答案是"是"，先判 Core

**退出条件**
- ✅ `docs/R4_CORE_EXTENSION_MAP.md` 存在，51 条能力覆盖四档（CORE 24 / EXTENSION_POINT 12 / EXTENSION_IMPL 8 / INFRASTRUCTURE 7）—— 复现：`python _tools/qa/_check_core_extension_boundary.py`
- ✅ **Unclassified = 0**：47 张表**恰好一个归属**（不许多头、不许孤儿、不许幽灵表名）—— 复现：`python _tools/qa/_check_core_extension_boundary.py`
- ✅ **15 个域全部被定过档**（命令按域归属，域被定档 = 命令被定档；域清单由 `DOMAIN_BOUNDARIES.md` **自己算**，不从本图抄）—— 复现：`python _tools/qa/_check_core_extension_boundary.py`
- ✅ 18 个事件类型**双向**对上（代码产生的都在 §5.2 登记、§5.2 登记的都在产生），且最后一列**全是 ❌** = Event 是事实通知、不是隐藏调用（§28）—— 复现：`python _tools/qa/_check_core_extension_boundary.py`
- ✅ 判据**真的会红**：14 条反向破坏用例 + 1 条正面前提全部成立 —— 复现：`python _tools/qa/_reverse_verify_r4_all.py`
- ⚠️ 三条 `pending: yes` 是**如实留白**（税费 / 促销 / 搜索排序：系统里根本没有这类业务），理由逐条写在块里 —— 复现：`python _tools/qa/_check_core_extension_boundary.py --list`

## R4-02 Contract Design（Unit Conversion + Pricing）

**交付**：`UnitConversionContract v1` 与 `PricingContract v1`，每个写清
**输入 / 输出 / 错误 / 不变量 / 兼容要求 / 生命周期**。
⛔ 指南 §7 明确：**不要设计万能插件接口**（`Plugin.initialize/execute/shutdown` 那种），按能力类型分契约。
⛔ §18：第一个版本**不要**做版本系统，先证明"这个契约真的会被多个实现使用"。

**退出条件**
- ✅ 两个契约（`UnitConversionContract` / `PricingContract`）各有 `CONTRACT_VERSION = 1` 与六个要素，且**契约里一行实现都没有**（AST 去掉文档字符串与注释后扫 db / Session / select）—— 复现：`python _tools/qa/_check_extension_contracts.py`
- ✅ 契约的错误语义是**中文可照着改**的一句，不是异常类型名（`MoneyError` / `QuantityError` / `UnitConversionError` / `PricingError` / `NoPricingRule` / `AmbiguousPricingRule`）—— 复现：`cd backend; python -m pytest tests/test_extension_contracts.py -q`
- ✅ **输出必须是核心类型**：AST 核对 `PricingResult.money: Money` 与 `ConversionResult.quantity: Quantity`（指南 §20「只接受 Money」的机器形态）—— 复现：`python _tools/qa/_check_extension_contracts.py`
- ✅ **顺手做实的一件**：`Rounding` 这条跨十几个文件的口头约定收进 `contracts/money.py` 一处定义，判据用 AST 对全项目 **14 处 `quantize`** 逐条对账（都显式写了 `rounding=`，两位小数那一档都是 `ROUND_HALF_UP`）—— 复现：`python _tools/qa/_check_extension_contracts.py`
- ✅ 判据**真的会红**：契约判据的 10 条反向破坏用例全部成立 —— 复现：`python _tools/qa/_reverse_verify_r4_all.py`
- ⏳ 「Core 侧不认识任何具体实现名（无 `ColdChainPricing` 这类字面量）」这一条**不在本里程碑**：它是依赖防火墙的事，出口在 R4-03 的 `_check_extension_dependencies.py`

## R4-03 Dependency Firewall + 五个检查器

**四条防火墙规则**（指南 §12/§13）：① Core 不能 import 具体 Extension；② Extension 不能直接改 Core 拥有的数据；
③ Extension 不能绕过 Capability；④ Extension 不能直接 import 私有内部。
**五个检查器**（§30，⛔ 只做这五个，每个必须有「为什么代码边界无法解决 / 反向破坏用例 / 静默空转保护」）：
`_check_core_extension_boundary` / `_check_extension_dependencies` / `_check_data_ownership` /
`_check_extension_manifest` / `_check_extension_contracts`。

**横切要求**（指南正文，逐条要有落点）：Extension Registry 与 Manifest（§15）、
配置模块化 `CORE_*` 与 `EXT_*` 分离（§26）、路由由 Extension 声明但**鉴权归 Core**（§27）、
Event 只作事实通知（§28）、模块依赖图可自动生成（§29）。

**退出条件**
- ✅ 五个检查器都在（boundary 30 项 / contracts 21 项 / dependencies 8 项 / ownership 9 项 / manifest 16 项），每个都带 `R4-BOUNDARY-JUSTIFICATION:` 一行 —— 复现：`python _tools/qa/_check_all.py`
- ✅ 五个检查器各有**反向破坏用例**，共 40 条注入 + 5 条正面前提 + 5 条还原校验 = **45/45 全部成立** —— 复现：`python _tools/qa/_reverse_verify_r4_all.py`
- ✅ 五个检查器各有**静默空转保护**（块数 / 表数 / 事件数 / impl 数 / 契约数 / quantize 处数 / 核心文件数 / 权限点数 / 字段数 / 类别数 / 文档覆盖度，逐项有下限；核不到就报红而不是全绿）—— 复现：`python _tools/qa/_reverse_verify_r4_all.py`
- ✅ Manifest 能声明 `id / version / kind / requires / provides / consumes / emits / config / compatibility / owns_tables / routes / capability`（12 个必备字段；注册表、dataclass、文档**三方一致**）—— 复现：`python _tools/qa/_check_extension_manifest.py`
- ✅ 依赖图可生成并可回答「谁依赖谁 / 谁拥有这张表 / 谁提供这个 capability / 谁监听这个 event」—— 复现：`python _tools/qa/_check_extension_dependencies.py --graph`
- ✅ 配置分离：扩展一律 `EXT_<ID>_<KEY>`、核心一律 `CORE_*`，⛔ 扩展不许直接读环境变量 —— 复现：`python _tools/qa/_check_extension_manifest.py`
- ✅ **四条防火墙规则**各有落点：① Core 不能 import 具体 Extension（只有装配根 `main.py` 可以）；② Extension 不能改核心拥有的数据（只能 calculate 出 Money，写语句一条都不许有）；③ Extension 不能绕过 Capability（扩展代码里一行鉴权都没有，能力点由核心施加）；④ Extension 不能 direct-import 私有内部（只许 `app.core.contracts.*` 与 `app.core.extension_registry`）—— 复现：`python _tools/qa/_check_extension_dependencies.py` + `python _tools/qa/_check_data_ownership.py`
- ⏳ **扩展数为 0，所以「每个扩展都合规」那一半此刻只核了空集**（如实记着，不粉饰）：第一个扩展由 R4-04 落地，届时 `_check_extension_manifest.py` 的 `MIN_EXTENSIONS` 要从 0 抬到 1 —— 那是一次**收紧**，不给它留模糊空间

## R4-04 第一个真实扩展：Unit Conversion

**目标**（指南 §19）：先做 `Unit / Dimension / Quantity / ConversionContract`，再实现 SI，
再增加 Imperial，再增加 China-traditional。**整个过程中 Core 不应该为了新增一种单位而不断修改。**

**退出条件**
- ✅ **Core 修改数 = 0**（Add 演练的唯一判据）：区间 `54f2418..cf3588f` 里核心区**改 0 行** —— 复现：`python _tools/ops/_r4_add_drill.py --check`
- ✅ **既有扩展模块修改数 = 0**：同一区间里 `backend/app/extensions/` 下只出现**新增**（1 个文件 `china_traditional.py`），没有任何修改/删除 —— 复现：`python _tools/ops/_r4_add_drill.py --check`
- ✅ 扩展自足（自己声明路由与能力点、自己拥有 0 张表、⛔ 没往 Core Model 加扩展专属字段）—— 复现：`python _tools/qa/_check_core_extension_boundary.py` + `python _tools/qa/_check_data_ownership.py`
- ✅ 契约有单测，且**两个实现各跑一遍同一组契约用例**（那份用例**不认识任何一种单位**：单位与量纲从实现自己的 `units()` 里读）—— 复现：`cd backend; python -m pytest tests/test_unit_conversion_contract.py -q`
- ✅ **重叠必须一致**：凡有两个以上实现都支持的一对单位，值 / 因子 / 量纲**逐位相同**。加第二个实现会带出这件事 —— 两个实现都认识桥接单位（kg/m/l），"谁先回答"取决于字典序，所以它不能靠"反正答案一样"糊过去 —— 复现：`cd backend; python -m pytest tests/test_unit_conversion_contract.py -q -k overlapping`
- ✅ 第一版实现 + 第二版实现：SI（11 个单位 / 3 类量纲）与市制（8 个市制单位 + 6 个桥接单位）—— 复现：`cd backend; python -c "from app.extensions.unit_conversion import PROVIDERS; print([p.name for p in PROVIDERS])"`
- ⏳ Remove 演练（完整卸载）后核心仍成立 —— 出口在 R4-06

**四条如实记着的边界**：
1. ⛔ **不收「尺」与「寸」**：1 尺 = 1/3 米，十进制除不尽，收进来会让 `1 尺→米→尺` 回不到 1（契约用例的往返回归会当场红）。要收它们得先回答"保留几位、谁来定"，那是另一件事。
2. 本轮的换算只覆盖**量纲感知的内建单位**；用户自己填的换算率（`1 车 = 8 方`，存在 `unit_conversions` 表）走的仍是既有那一条路，**一个字节都没动**。
3. 扩展的 `config`（`EXT_UNIT_CONVERSION_UNIT_SYSTEM`）目前**没有任何代码读它** —— 它是"配置要经注册表"这条规矩的活样本，R4-06 的 orphan config 核查会拿它当对象。
4. 路由 `/api/v1/unit-conversion/preview` 的鉴权是 `ORDER_CREATE`（能下单的人就能试算），与既有 `POST /api/v1/unit-conversions` 的 shipper+dispatcher 口径一致；⛔ 扩展代码里**一行鉴权都没有**，它由核心在装配时施加。

## R4-05 第二个真实扩展：Pricing

**目标**（指南 §20）：`Order → PricingContext → PricingContract → Money` 成立。
Core **只接受 `Money`**，⛔ 不接受任何插件自己的对象。

**退出条件**
- ✅ 链路成立：`Order → PricingContext → PricingContract → Money` —— 左边两格由核心的 `core/pricing_context.py::context_of` 负责（扩展没有库访问权），右边**必须是核心的 `Money`**（AST/运行期双重核对）—— 复现：`cd backend; python -m pytest tests/test_pricing_contract.py -q`
- ✅ **两个 Pricing 实现可替换**，替换时 Core 修改 **0 行**、既有扩展模块修改 **0 个**（区间 `51c4a72..a7fee0c`，只新增 1 个文件 `per_quantity.py`）—— 复现：`python _tools/ops/_r4_replace_drill.py --check`
- ✅ **替换是配置行为，不是开发行为**：同一张订单只换规则快照里的 `pricing_kind`，两个实现给出**不同的**结果（统一价 120.00 元 / 按量 8.50 × 15 件 = 127.50 元），而代码一行没改 —— 复现：`python _tools/ops/_r4_replace_drill.py --check`
- ✅ Extension ⛔ 不写账本：只能 `calculate → Money`，最终事实交给 Core 事务（扩展包里一条写语句都没有、也碰不到 `ledgers` / `cash_flows`）—— 复现：`python _tools/qa/_check_data_ownership.py`
- ✅ 历史可解释：订单上保有**派单那一刻定格的规则快照**（`orders.driver_rule_snapshot`），删除扩展后历史单仍解释得通 —— 复现：`python _tools/qa/_check_data_ownership.py`
- ✅ 顺带兑现 R4-03 台账里那条承诺：`_check_extension_manifest.py` 的 `MIN_EXTENSIONS` **从 0 抬到 1**（从这一刻起「扩展数掉到 0」会当场报红，而不是安静地全绿）—— 复现：`python _tools/qa/_check_extension_manifest.py`

**一条如实记着的边界**：`Order → PricingContext` 这一段**在测试里是真的**（用一张 `Order` 实例走完整链路），
但 ⛔ **生产订单计价仍然走既有的核心实现**（`services/freight_pricing.py` / `services/driver_pay.py`）。
本轮**不做接线** —— 那会改钱的口径，与「Core 修改数 = 0」直接冲突，也需要单独的发布与演练。
本里程碑证的是「**这条链在契约层成立、且换实现不用动核心**」，不是「生产已经换成扩展在算钱」。

## R4-06 Remove Drill

**四件不同的事要分开**（指南 §24）：`Disable` / `Uninstall` / `Code Removal` / `Data Removal`。
⚠️ **扩展被删除，不代表它创造的历史事实可以删除**（Money / Audit / Order History 上必须钉死）。

**退出条件**
- ✅ 完整删除 Unit Conversion 之后：**全量静态检查全绿**（红 0 条；脚本数以 `_check_all.py` 自己打印的为准，⛔ 不手写）—— 复现：`python _tools/ops/_r4_remove_drill.py --check`
- ✅ 后端用例全绿：**1065 passed**（R3 基线 1020，本轮 +45）—— 复现：`cd backend; python -m pytest -q`
- ✅ core smoke 通过：发件箱 / 投递原语 / 两个契约共 **50 passed**（都不碰那个扩展）—— 复现：`cd backend; python -m pytest tests/test_socket_io.py tests/test_outbox.py tests/test_extension_contracts.py tests/test_pricing_contract.py -q`
- ✅ **API smoke**：拆掉之后应用照常起得来，核心路由 235 → **234**（正好少它那一条）—— 复现：`python _tools/ops/_r4_probe_app.py` + `python _tools/ops/_r4_remove_drill.py --check`
- ✅ **没有 orphan**：route（那条 preview 消失）/ capability（`ORDER_CREATE` 在别处仍有执行点，能力注册表检查全过）/ config（`EXT_UNIT_CONVERSION` 无人引用）/ import（`app.extensions.unit_conversion` 无人引用）—— 四类一个都没有 —— 复现：`python _tools/ops/_r4_remove_drill.py --check`
- ✅ **核心数据没被破坏**：47 张表逐名比对一致（它 `owns_tables=()`，本来就没有数据要删）—— 复现：`python _tools/ops/_r4_remove_drill.py --check`
- ✅ 指南 §24 的四件事**分开做**：停用 Disable（清单 `enabled=False`，路由消失、代码还在）/ 卸载 Uninstall（目录移出仓库）/ 删代码 Code Removal / 数据 Data Removal（无数据可删）—— 复现：`python _tools/ops/_r4_remove_drill.py --check`
- ✅ 演练**可重跑且安全**：开跑前拒绝脏工作区；跑完按字节还原（6 个文件逐个核 sha256）+ 路由回来 + `git status` 干净 —— 复现：`python _tools/ops/_r4_remove_drill.py --check`

**这次演练抓到的三条真东西（如实记着，它们比"通过"更值钱）**：

1. **一次完整卸载不只是删一个目录**：还要重跑两张由源码集合推导出来的产物（界面文案目录、端点索引）
   并删掉 AI 读覆盖表里那条登记 —— 不删就是**化石**（那个检查器专门防这个）。
   所以"重新生成 + 删登记"是**卸载的一部分**，不是额外工作；演练里已经把它做成第 3a 步。
2. **`tests/test_extension_contracts.py` 里的 pricing 内联实现漏了 R4-05 新加的 `applies_to()`** ——
   `isinstance` 假失败，而**全量静态检查不跑 pytest**，所以它一直没露出来。
   是这次演练跑 core smoke 才抓到的。教训：**改了协议就立刻把所有内联实现跑一遍**，别只跑新写的那几个文件。
3. 演练脚本自己踩了两次同一个坑：**用子串当标记**（`unit-conversion` 是 `unit-conversions` 的子串、
   `unit_conversion` 是核心 `unit_conversions` 模块的子串）→ "路由消失"永远判 False、孤儿引用全是假阳。
   判据要盯的是**那一个具体的东西**，不是"名字里恰好含这几个字"。

## R4-07 Compatibility Drill

**目标**（指南 §17，⚠️ 同时受 §18 约束：不要过度做版本系统）：
故意做 `PricingContract v1 → v2` 的实现，验证旧实现还能工作、新实现可以加入、核心无需修改。

**退出条件**
- ✅ v1 与 v2 两个实现**同时可用**，同一组契约用例两边都跑（19 passed；阶梯价是原生 v2）—— 复现：`cd backend; python -m pytest tests/test_pricing_contract.py -q`
- ✅ **核心修改数 = 0**（区间 `f666cf7..5bb144d`，只新增 1 个文件 `tiered.py`；v2 契约与适配器在区间**之前**那一次提交里落地）—— 复现：`python _tools/ops/_r4_compat_drill.py --check`
- ✅ **旧实现还能工作**：v1 实现经 `as_v2()` 适配器后**仍然满足 v1**（`isinstance(p, PricingContract)` 为真），旧消费方一行代码都不用改；且明细各行之和**等于**总额 —— 复现：`python _tools/ops/_r4_compat_drill.py --check`
- ✅ **新实现可以加入**：`tiered` 给出 2 行**原生**明细（前 10 件 × 8.00 + 超出 5 件 × 9.00 = 125.00），而 v1 实现只合成 1 行 —— 复现：`python _tools/ops/_r4_compat_drill.py --check`
- ✅ ⛔ 不出现「10 代接口」：v2 **只加一个方法**（`breakdown`），⛔ 不搞 v1/v2/v3 + compatibility matrix（§18 明确否掉的过度设计）；边界图的契约版本数上限仍是 3，当前只到 v2 —— 复现：`python _tools/qa/_check_core_extension_boundary.py`

**顺序本身就是指南的一部分，如实记一笔**：§18 说「**先证明这个契约真的会被多个实现使用，
再为它设计长期版本兼容**」。所以 v2 **不是**在 R4-02 设计契约时就一起设计的 ——
是到 R4-05 已经有两个实现了之后才加的，而且只加了一个方法。
⛔ 也没有为"任何旧实现"都写适配器：只为**真实存在的**旧实现提供兼容层（§31 坑 13）。

## R4-08 最终架构验收

**五条判据**（指南 §41，⛔ 看的不是"模块数量增加了多少"）：
1. 新增扩展**不会污染 Core**
2. 替换扩展**不会修改 Core**
3. 删除扩展**不会破坏 Core**
4. 扩展依赖**全部可见**
5. **历史核心事实不会因为扩展删除而失效**

**退出条件**
- ✅ **五条判据各有实测证据**（不是散文）：1 新增不污染 Core｜2 替换不改 Core（含契约 v1→v2）｜3 删除不破坏 Core｜4 依赖全部可见｜5 历史核心事实不因扩展删除而失效 —— 复现：`python _tools/ops/_r4_acceptance.py --check`
- ✅ 指南 §42 的验收矩阵落进 `docs/ARCHITECTURE_RECTIFICATION_R4.md` **附录 A**，且 Add / Replace / Remove **是实际演练**（三条演练器 + 一份 Remove 记录，证据都在 `_tools/ops/r4_drill_records/`）—— 复现：`python _tools/ops/_r4_acceptance.py --check`
- ✅ 北极星那一句（§44）写进该文档附录 A.1；⛔ 附录**明确标着"不是指南原文"**，原文仍是逐字节那 26669 字节（SHA256 写在附录开头）—— 复现：`python _tools/ops/_r4_acceptance.py --check`
- ✅ 依赖图可以现场生成（指南 §29）：谁依赖谁 / 谁提供能力 / 谁拥有表 / 核心事实表多少张 —— 复现：`python _tools/ops/_r4_drill_graph.py`
- ✅ **CI 一列按下面那句口径读，⛔ 不是一个"全绿"**：**Required R4 CI gates 全绿；安卓端到端未运行，本轮不计通过** —— 明细见本文档「CI 验证」一节。
  （这一格原来留 ⏳ 的条件是"推送并确认 CI 跑过之前不许写 ✅"——现在跑过了，所以写 ✅；
   但写的是**那六行判据**在 CI 上全绿，**不是**"CI 整轮全绿"。R3 为"文档语义超过代码事实"栽过四轮。）

---

## 验收矩阵（Add / Replace / Remove 是**实练**）

> 指南 §42 的矩阵。⛔ 一行的意义是**这一格被真跑证明过**，不是「代码里有」。

| 能力 | Code | CI | Runtime | Add | Replace | Remove | 依据 / 出口 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Core Boundary | ✅ | ✅ | ✅ | — | — | — | R4-01：`docs/R4_CORE_EXTENSION_MAP.md`（52 条能力 / 47 张表各一个归属 / 18 事件全是事实通知）+ `_check_core_extension_boundary.py`（30 项） |
| Unit Conversion | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | R4-04：Add 出口 `_r4_add_drill.py`（Core 0 行 / 既有模块 0 个）；Remove 出口 `_r4_remove_drill.py`（12/12 步，全量检查红 0 条） |
| Pricing | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | R4-05：Replace 出口 `_r4_replace_drill.py`（换一个 `pricing_kind` 就换算法：120.00 vs 127.50，Core 0 行） |
| Dependency Firewall | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | R4-03：四条规则各有判据（`_check_extension_dependencies.py` 8 项 + `_check_data_ownership.py` 9 项） |
| Data Ownership | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | R4-03：扩展不认领核心表（34 张核心事实表一张没被染指）+ 历史快照列在 + 删除演练 47 张表逐名一致 |
| Compatibility | ✅ | ✅ | — | ✅ | ✅ | ✅ | R4-07：`_r4_compat_drill.py`（v1 实现经适配器照常跑、v2 实现给 2 行原生明细，Core 0 行） |

**读表须知**

- `Code ✅` = 有判据在每次全量静态检查里核它（脚本数由 `python _tools/qa/_check_all.py` 自己打印，全部通过；⛔ 不在这里手写那个数字）；`Runtime ✅` = **在本机真跑过**；`—` = 不适用。
- ✅ `CI ✅` 的**准确读法**（用户 2026-09-27 明确要求改这个措辞）：**Required R4 CI gates 全绿**
  —— `Gate` 六个实质作业 + `Tests (Parallel)` 五个作业，两次 run 都全绿。
  ⛔ **不要写成、也不要读成「CI 全绿」**：`常闸 · 安卓端到端` 那次**没有跑**（runner 起不了模拟器，
  它自己的注解原话是「这次没有跑，不是通过」）⇒ **本轮不计通过**。
  ⛔ 这条措辞**不许为了好看而放宽**：「没跑 ≠ 通过」是 R3/R4 一路守下来的那条原则。
- ⛔ Add / Replace / Remove 三列**只认演练记录**（`_tools/ops/r4_drill_records/`），不认"设计上支持"。

---

## CI 验证（R4 收尾，2026-09-27）

R4 的验收矩阵有一列是 `CI`。**这一列不是装饰** —— 它逼出了两个真问题，两个都不是 R4 自己引入的：

### ① 后端用例在 CI 上红 8 条 —— 而它**每天只在 16:00Z–24:00Z 这 8 小时里红**

- ✅ 现象：CI 的「Normal Gate · 后端用例」红（8 failed / 1063 passed），本机**同样提交**跑 **1072 passed**；
  在**全新 worktree**（＝ CI 的检出条件）里也是 1071 passed / 1 skipped。
- ✅ 定位：红的 8 条全是**按日期开窗**的用例（货主核销窗口、营业额、毛利探针）。它们传的窗口是
  `date.today()` —— **跑 CI 那台机器的本地日期**，而 CI runner 是 **UTC**；本项目的口径是
  「库里 UTC naive、界面一律 +8」（`core/business_time.py::business_today()`）。
  **UTC 16:00 之后两者的日期就不同了**：runner 说 9-26，业务侧已经是 9-27 ⇒ 窗口查不到那一行。
- ✅ **本机验到了那条机制**（⚠️ **不是**"把 runner 换成 UTC"：Windows 的 Python **不认 `TZ`** ——
  实测 `time.tzname` 仍是「中国标准时间」，所以本机整体模拟不出 UTC runner。
  ⛔ 我一度把一次"`TZ=UTC` 复现"写进了台账，**那是错的**，已改成下面这条能站住的证据）：
  把那一条用例的窗口**往后挪一天**（＝ UTC runner 在 16:00Z 之后看到的那个偏移）→
  **复现出与 CI 一模一样的失败**；挪回来 → 通过。
  于是"一天的窗口偏移就是这个失败"被证到了，再与另外两条对上：
  ① 同一批用例在 **15:48Z / 15:56Z 绿**、在 **17:23Z / 17:33Z 红** —— 两次之间**只有日期不同**；
  ② 红的 8 条**全是**按日期开窗 / 按日期查数的用例。
- ✅ 修法：那 5 个文件里 6 处 `date.today()` → **`business_today()`**（＝ 客户端真正会发的那个日期）。
- ✅ **闭环了**（证据在下面「④ 在原来必红的时间窗里又跑了一次」）：本机在 +8，两种写法算出**同一个**日期，
  所以"本机 1072 passed" **修之前也成立** —— 本机绿这件事证明不了这个修复。
  真正的证据是：修完之后 CI **又在「UTC 日期 ≠ 业务日期」的那一刻**跑了一次，并全绿。

⚠️ **这条缺陷与 R4 无关**，它一直在那儿：CI 每天有三分之一的时间是红的，而**日志匿名读不到**，
所以「红了」只表现为一句 `Process completed with exit code 1`。
它被看见，是因为 R4 把 CI 的失败摘要接到了 `--junitxml` 上（见 ②）。

### ② 「公开仓库读不到日志」——连"把摘要发成注解"这条老办法也失效了

- 现象：R4 第一次推上去，Gate 的后端用例红了，而注解里**只有一句"失败摘要如下"、摘要一条都没有**。
- 根因：那条老办法是 `pytest ... 2>&1 | tee 日志 || { grep FAILED 日志; }`，而**那个日志文件是空的**
  —— 诊断管道本身坏掉，比被测代码还难查。
- 修法：新增 `_tools/qa/_ci_pytest.py`，走 **`--junitxml`**（pytest 自己写的结构化成败记录，
  与终端输出有没有被吃掉无关），逐条发成 CI 注解；`gate.yml` 的「跑全量用例」改用它。
  ⛔ 用例全过 → 退出 0；有失败 → 退出 1（不许把"没跑"当成"通过"）。
  ✅ 实测：正是它把上面那 8 条的名字送出来的。

### ④ 在原来必红的时间窗里又跑了一次（这就是闭环）

那个缺陷只在 **UTC 日期 ≠ 业务日期（+8）** 时发作，也就是 **UTC 16:00Z–24:00Z** 这 8 小时。
所以"修完 CI 绿了"本身**不算证据** —— 换个时间点它本来也会绿。

✅ 修完之后**两次** CI run 的创建时刻分别是 `2026-09-26T22:39:13Z` 与 `2026-09-26T22:51:04Z` —— **都正落在那 8 小时里**
（当时本机 +8 已是 09-27 06:39，UTC 还是 09-26）⇒ UTC 日期与业务日期**确实不同**，
**正是原来必红的那个条件**。结果是：

| 作业 | 结果 |
| --- | --- |
| Fast Gate（语法 / 端点索引 / 核心冻结 / 密钥 / 迁移 / 备份） | ✅ |
| Normal Gate · 全部静态检查（清单自己算） | ✅ |
| **Normal Gate · 后端用例**（原来 8 failed / 1063 passed） | ✅ |
| Normal Gate · 安卓单测 | ✅ |
| Normal Gate · AI 读权限对账（起真后端逐条打） | ✅ |
| Tests (Parallel)：Fast / Slow / Full / Integration / Role-based 五个作业 | ✅ 全部（两次 run 都是）|
| 常闸 · 安卓端到端（登录 → 导航 → 下单） | ⚠️ 见下 |

⚠️ **安卓端到端那个作业**在 CI 上时绿时红，原因写在它自己的注解里：
「这台 runner 上**没能起模拟器** —— **这次没有跑**，不是通过」。
⛔ 所以这一格**不能**读成"安卓端到端通过了"：它在本轮**一次都没有真的跑过**。
（R3 那次它是绿的；这是 runner 的模拟器能力问题，与本轮改动无关 —— 但也不能拿它充数。）

### ③ 还有一条是 R4 自己的（判据抓到的，如实记着）

- `527bad4` 那条提交的标题里**漏了里程碑编号**（写成「R4 收尾」，而棘轮要的是 `R4-0\d`）→
  `_check_r3_constraints.py` 的 `commit_milestone_tag` 当场报红，并**连带**让 `_check_report_facts.py` 红
  （`docs/R3_PROGRESS.md` 里那条 ✅ 的复现命令就是跑这个检查）。
- 修法：`git commit --amend` 补上 `R4-08` + `git push --force-with-lease`。
- ⭐ 这正是 R3 那条跨轮棘轮存在的意义：**它在我自己身上生效了**。

---

## 与 R3 的关系（⛔ 不要重复劳动）

| | R3 | R4 |
| --- | --- | --- |
| 问的问题 | 「真实世界一运行，它还成立吗？」 | 「持续演化时，核心会不会被侵蚀？」 |
| 证据形态 | **运行时证据**（生产跑过 + 故障演练） | **架构证据**（Add / Replace / Remove 实练） |
| 是否动代码 | 少量（且只在证据触发的例外下） | 只动**扩展区**；核心修改数 = 0 是判据 |

R4 **继承** R3 的三条纪律：① 会变的数字不手写（由工具采）；② 「已完成」必须有可执行退出条件；
③ 提交必须能回溯到里程碑编号（这条跨轮继续由 `_check_r3_constraints.py` 守）。
