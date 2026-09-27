# R4-17 · Shadow 定价对照（真实订单，只读，⛔ 不写 Ledger）

> 用户 §7：「影子阶段必须证明的不是『跑过』，而是『**没有漂移**』。」
> 「**Shadow 模式下绝对不能写 Ledger** —— 只做 calculate / compare / record。」
> 「如果发现 120.00 vs 120.01，不要立刻说『差一点点没关系』。尤其是钱。」

出口：`python _tools/qa/_shadow_pricing.py --check`（本机自检，进必跑组）
　　　真实订单那一趟：见 §3（原始事实 `_tools/ops/r4_shadow_r417.json`）

---

## §1 两条路，同一份事实

| | 算什么 | 怎么算 |
| --- | --- | --- |
| **Legacy** | 生产今天真的在跑的那一版 | `services/freight_pricing.quote_for(db, order, driver_id)` |
| **Extension** | R4-16 的候选实现 | `freight_snapshot_of(...)` → `PricingContext` → **`resolve_v2`（走契约）** → `freight_template` |

⭐ 两边读的是**同一份东西**：快照由**核心**导出（`freight_snapshot_of`，与 `quote_for`
共用 `driver_template_ids` / `route_ids_of` / `candidate_templates`）。
⛔ 不是对照脚本自己照着读一遍 —— 那样比的是两个算法，不是同一个算法的两条路。

**这一条同时消掉了 R4-16 自己记下的最大残余风险**（`docs/R4_GOLDEN_SET.md` §5.3：
"喂给候选的快照是我转录的"）。Golden Set 换用核心侧构造器之后**仍然是 15/15、mismatch 0**
—— 既说明那份转录忠实，也说明风险**从构造上消失**了。

---

## §2 ⛔「没写库」是被**证**出来的

跑之前、跑之后各数一遍 `orders / ledgers / cash_flows / outbox_events / driver_bills` 的行数，
**必须一模一样**，不等就报红。对照本身只做 `SELECT`。

---

## §3 真实订单那一趟（2026-09-27）

**跑在哪**：生产机上开一个**只读工作树**（`git worktree add --detach /tmp/r417 <SHA>`），
⛔ `/opt/SOrders` **全程停在发布点 `ca5e49f` 没动**；数据用的是把发布时那份 dump
恢复出来的**演练库** `sorders_drill_r417`（⛔ 不碰生产库）。

**数据是什么**：`/opt/sorders-backup/pre_release/20260927T020119Z`（2026-09-27T02:01Z 的生产快照）
→ 恢复核对：orders 2403 / ledgers 4648 / users 60 / products 37 / tables 48，逐项与 manifest 一致。
⚠️ 它是**那一刻**的事实，不是"当前"。

**顺带**：演练库从 v8 迁到 v9 —— 009 在**生产形状的真实数据**上又跑了一遍（**108 ms**）。

**结果（全量，不是抽样）**：

    total 2116 / matched 2116 / **mismatched 0** / error 0 / unsupported 0
    写库前 {"orders": 2403, "ledgers": 4648, "cash_flows": 72, "outbox_events": 27, "driver_bills": 1515}
    写库后 {"orders": 2403, "ledgers": 4648, "cash_flows": 72, "outbox_events": 27, "driver_bills": 1515}
    wrote_anything: false

`total = 2116` 就是**这一份快照里所有有司机的订单**（2403 张里 2116 张）—— 不是限量样本。

**收工**：`git worktree remove` + `DROP DATABASE sorders_drill_r417`；
之后核对：`prod HEAD = ca5e49f`（没动过）、库只剩 `sorders`、`/tmp` 无残留。

---

## §4 ⛔ 这一格**证不了**什么

1. **不证明候选实现"更好"** —— 它只证明**两边一样**。一样，恰恰是"可以替换"的前提，
   不是"应该替换"的理由。
2. **不证明生产真的会切** —— 它没有接线：生产跑的还是 Legacy（`quote_for`）。
3. ⚠️ **快照的时间点是 2026-09-27T02:01Z**，不是"永远"。以后的数据形状变了（新分类、
   新规则形态），要么再跑一次，要么靠 Golden Set 那类构造语料兜着。
4. **这一趟没有覆盖"扩展拥有表 / 多币种 / 按量计费"** —— 那些是别的 `pricing_kind`。
5. ⛔ **没有做有限写烟测**（`business` 那一步）—— 本轮不改任何业务行为，也不需要动生产数据。

---

## §5 与下一格的关系

    R4-17 Shadow                真实订单全量 2116 笔，0 漂移，0 写库            ✅
          ↓
    R4-18 发布演练               release → 滚动重启 → health → smoke → rollback    ⏳
          ↓
    R4-19 Canary                 核心**唯一组装点**切换；同一订单生命周期不换算法    ⏳
          ↓
    R4-20 Full Cutover           LegacyPricing 保留为**回滚实现**                  ⏳
