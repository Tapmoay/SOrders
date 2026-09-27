# R4 证据索引（一页）

> **用途**：任何人拿到仓库后，10 分钟内能从「结论」追到「证据文件」，再追到「能重跑的入口」。
> ⛔ 这一页**不是**权威来源 —— 它只是索引：每一条的结论都由它自己那行指向的文件与命令产生。
> ⛔ 这里**不写任何人手汇总的数字**（那种数会烂）；要数就当场跑那条命令。
>
> 维护规则：**每一行必须有一个真实存在的文件 + 一个真实存在的入口**。
> 由 `_tools/qa/_check_r4_closeout.py` 机器核（文件不在 / 入口不在 ⇒ 当场报红）。

---

## 一、架构（R4 的「结构成立」那一半）

| 结论 | 证据文件 | 复现入口 |
| --- | --- | --- |
| Core / Extension 边界划清（能力 / 表 / 事件各一个归属） | `docs/R4_CORE_EXTENSION_MAP.md` | `python _tools/qa/_check_core_extension_boundary.py` |
| 扩展不许反向依赖核心（四条规则） | `_tools/qa/_check_extension_dependencies.py` | `python _tools/qa/_check_extension_dependencies.py` |
| 扩展不认领核心表（数据归属） | `_tools/qa/_check_data_ownership.py` | `python _tools/qa/_check_data_ownership.py` |
| Add / Replace / Remove **是实练**（不是设计上支持） | `_tools/ops/r4_drill_records/add-drill.json` | `python _tools/ops/_r4_acceptance.py --check` |
| Replace：换一个 `pricing_kind` 就换算法（120.00 vs 127.50）、Core 0 行 | `_tools/ops/r4_drill_records/replace-drill.json` | `python _tools/ops/_r4_replace_drill.py --check` |
| Remove：删掉扩展不破坏 Core（12/12 步、47 张表逐名一致） | `_tools/ops/r4_drill_records/remove-drill.json` | `python _tools/ops/_r4_remove_drill.py --check` |
| Compatibility：契约 v1→v2，旧实现经适配器照常跑 | `_tools/ops/r4_drill_records/compat-drill.json` | `python _tools/ops/_r4_compat_drill.py --check` |
| 指南原文逐字节归档（26669 字节 + SHA256） | `docs/ARCHITECTURE_RECTIFICATION_R4.md` | `python _tools/qa/_check_r4_constraints.py` |

## 二、生产接线（定价真的在生产上跑）

| 结论 | 证据文件 | 复现入口 |
| --- | --- | --- |
| 编排器已装配、Canary 生效、两个实例一致 | `_tools/ops/_canary_status.py` | `python _tools/ops/_canary_status.py` |
| 生产窗口的状态与九条判据（含 `unknown` / `missing` 三态） | `docs/R4_CANARY_WINDOW.md` | `python _tools/ops/_canary_status.py --since 2026-09-27T07:01:00` |
| 生产数据形状与自检数据形状一致（7 组 / 40 项） | `_tools/qa/_check_prod_shape.py` | `python _tools/qa/_check_prod_shape.py` |
| 上面那 40 项**不是自说自话**（11 种注入都被抓到） | `_tools/qa/_reverse_verify_prod_shape.py` | `python _tools/qa/_reverse_verify_prod_shape.py` |
| 冻结实验可重跑（T0/T1/T2 各有判据） | `_tools/ops/_freeze_probe.py` | `python _tools/ops/_freeze_probe.py --selftest` |

## 三、受控生产验证（R4-49 · 四个场景的生产证据）

| 结论 | 证据文件 | 复现入口 |
| --- | --- | --- |
| 测试身份可机器判定（货主 183 / 司机 184 + 规则 #1） | `_tools/ops/r4v_records/identity-R4V-20260927-01.json` | `python _tools/ops/_r4v_identity.py --dry-run` |
| **App → 生产 API → Runtime → DB** 整条链通（真机，`#20853`） | `_tools/ops/r4v_records/p3-wire-R4V-20260927-01.json` | `python _tools/ops/_canary_status.py --since 2026-09-27T07:01:00` |
| `kind=legacy_client` / `resolution=not_in_canary`（新鲜证据） | `_tools/ops/r4v_records/p3-wire-R4V-20260927-01.json` | `python _tools/ops/_canary_status.py --since 2026-09-27T07:01:00` |
| `resolution=contract`（`#20900`，47 笔取桶内的明细全留档） | `_tools/ops/r4v_records/p4a-attempts-R4V-20260927-02.json` | `python _tools/ops/_canary_status.py --since 2026-09-27T07:01:00` |
| **`agreed=true`**（算法值被原样接受） | `_tools/ops/r4v_records/p4a-agreed-true-R4V-20260927-02.json` | `python _tools/ops/_canary_status.py --since 2026-09-27T07:01:00` |
| **`override=true`**（人工改价，`#20709` 独立抄录） | `_tools/ops/r4v_records/p4a-agreed-true-R4V-20260927-02.json` | `python _tools/ops/_canary_status.py --since 2026-09-27T07:01:00` |
| `fallback` / `frozen` 两支的生产样本 | `_tools/ops/r4v_records/p4a-attempts-R4V-20260927-02.json` | `python _tools/ops/_canary_status.py --since 2026-09-27T07:01:00` |
| 双实例一致（A/B 四项全同 + 零写入 + 输入相同） | `_tools/ops/r4v_records/R4V-P4B-comparison.json` | `python _tools/ops/_r4v_p4b.py` |
| A 侧原始响应（含 pid，与 `ss -lntp` 对得上） | `_tools/ops/r4v_records/R4V-P4B-A.json` | `python _tools/ops/_r4v_p4b.py` |
| B 侧原始响应（含 pid，与 `ss -lntp` 对得上） | `_tools/ops/r4v_records/R4V-P4B-B.json` | `python _tools/ops/_r4v_p4b.py` |
| 只读诊断面（⛔ 非业务 API、⛔ 匿名不可达、⛔ 不写库） | `backend/app/api/v1/diagnostics.py` | `python _tools/qa/_check_r4_closeout.py` |

## 四、证明基础设施（让上面那些结论**可信**的那一层）

| 结论 | 证据文件 | 复现入口 |
| --- | --- | --- |
| 判据自己测自己这一类假绿无处可藏（形状审计） | `docs/R4_PROGRESS.md` | `python _tools/qa/_check_prod_shape.py` |
| 测试库按进程隔离（两个 pytest 并发不再互踩） | `_tools/qa/_probe_test_db_isolation.py` | `python _tools/qa/_probe_test_db_isolation.py` |
| 全部静态检查（清单自己算，⛔ 不手写） | `_tools/qa/_check_all.py` | `python _tools/qa/_check_all.py` |
| 台账里每条 ✅ 都跑得通（R3 那一侧） | `_tools/qa/_check_report_facts.py` | `python _tools/qa/_check_report_facts.py` |
| 本页每一行的文件与入口都真的在 | `_tools/qa/_check_r4_closeout.py` | `python _tools/qa/_check_r4_closeout.py` |
| R4 指南归档件结构完整（⛔ **不核**逐字节等于原件） | `docs/ARCHITECTURE_RECTIFICATION_R4.md` | `python _tools/qa/_check_r4_constraints.py` |
| Final Review 的七问与裁决 | `docs/R4_FINAL_REVIEW.md` | `python _tools/qa/_check_r4_closeout.py` |

---

## ⛔ 这一页证不了什么（如实写）

1. **它不重跑上面那些重命令** —— 那是 `python _tools/qa/_check_all.py --deep` 与各条命令自己的事。
   本页的机器判据只保证**引用没烂**（文件与入口都在）。
2. **`Natural Observation`（上线后真实流量）不在这一页** —— 它被显式推迟到上线后，
   见 `docs/R4_FINAL_REVIEW.md` 的裁决。⛔ 不许把它的空缺读成「R4 没做完」。
3. **指南归档件那条只核结构** —— 附录声明的原件 `26669 字节 / SHA256 E45A6CAF…` **从仓库里重算不出来**
   （原件不在仓库）。⛔ 不许把那条 ✅ 读成「归档正文与原件逐字节相同」。
4. **2409 条历史订单的来源不是一个测量结论** —— 那是需求方依据领域知识做的**判定**，
   写法见 `docs/R4_FINAL_REVIEW.md` §六。⛔ 不许引用成「SQL 查出来它们是测试数据」。
