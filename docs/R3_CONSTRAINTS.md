# R3 第三轮整改 · 要点与禁做清单（机器可核对）

> **指南**：`C:\Users\Optimistic\Desktop\ppll.md` → 已归档 `docs/ARCHITECTURE_RECTIFICATION_R3.md`
> （SHA256 `193AB545848F6CE27869118FB26F1C8CFFCA569B6929F49F5176132F4DBA5297`，21633 字节，1219 行）
> **基线提交**：`d4be6f4`（本文件提交之前的那一个）
> **为什么有这份文件**：第二轮发生过一次「指南里写了不要做，还是做了」（指南 §十六 说不要加检查器，第二轮加了 9 个）。
> 散文里的「不要」靠记性守不住 —— 所以这一轮把所有「不要」**逐条抄进来，并给每一条配一个可判定的探针**，
> 由 `_tools/qa/_check_r3_constraints.py` 每跑一次全量检查就核一次。

---

## 一、这一轮到底在做什么（一句话）

> 第二轮是在问：**「架构上有没有定义清楚？」**
> 第三轮是在问：**「真实世界一运行，它还成立吗？」**

所以第三轮**不追求更多抽象，追求更多真实证据**。四根主梁：

1. **Migration 不再有隐式副作用**（`import app.database` 不许改库）
2. **Capability 真正四端同源**（API / AI / **UI** / **Audit**）
3. **两个实例真的同时跑过**（不是「代码看起来支持」）
4. **生产真的跑过、并经历过故障演练**

## 二、里程碑与顺序（指南 §二十三，不许跳步）

```text
R3-00 Baseline
  ↓
R3-01 Migration Lifecycle        ← 本轮最高优先级
  ↓
R3-02 Capability UI / Audit
  ↓
R3-03 Multi-instance Runtime     ← 硬门槛：真起两个实例
  ↓
R3-04 Observability
  ↓
R3-05 Production RC + 发布
  ↓
R3-06 Failure Drill
  ↓
R3-07 Meta-System Hardening      ← 故意放在生产之后
```

依赖：`R3-01 → R3-03 → R3-05 → R3-06`；`R3-02 / R3-04 / R3-07` 可部分并行。
⛔ R3-07 放在生产之后是**故意的**：整改体系要保护的是实际系统，不是一份漂亮的整改报告。

## 三、施工原则（指南 §二十五，五条）

| # | 原则 | 这一轮怎么落实 |
| --- | --- | --- |
| 一 | **不以代码量为成果**，尽可能少改业务代码 | 探针 `backend_app_delta` 钉住净增行数上限 |
| 二 | **能通过边界解决，就不要增加 Checker** | 探针 `checker_budget`：本轮每个新增 checker 必须带 `R3-BOUNDARY-JUSTIFICATION` 一行 |
| 三 | 任何「已完成」分三层：**Code Ready / CI Proven / Runtime Proven** | `docs/R3_PROGRESS.md` 的三层矩阵，探针 `progress_shape` 钉形状 |
| 四 | **不再允许文档语义超过代码事实**（Fact first, wording second） | 同上：矩阵里 ❌ 不许写成 ✅；数字一律带复现命令 |
| 五 | **先主动制造故障**，才能证明系统真的能恢复 | R3-06 五个 Drill（kill / Redis 挂 / 事件延迟 / 锁竞争 / 磁盘将满） |

> ⚠️ **关于原则二的一处自指张力（必须先说清）**：这份清单本身也是「一份文档」，而它要防的正是「文档里的不要被违反」。
> 只写文档 = 靠记性；只加检查器 = 又在加检查器。我的取舍是：
> **把「不要」变成可判定的探针，且本轮新增的 checker 必须逐条写明「为什么边界解决不了」**。
> 这条元规则本身也进了清单（`R3-D17`）并由此判据自己核 —— 你可以随时推翻它。

---

## 四、禁做清单（逐条抄自指南，附行号）

行号是 `docs/ARCHITECTURE_RECTIFICATION_R3.md`（与 `ppll.md` 逐字节相同）里的行号。

| id | 指南原话 | 行号 |
| --- | --- | --- |
| R3-D01 | 第三轮不要再继续大规模重构业务代码 / 不要再追求「这轮又改了几千行」 | L6 / L1015 |
| R3-D02 | 不要再按「发现一个问题修一个问题」的方式推进 | L28 |
| R3-D03 | 禁止 import → DDL；也禁止 application startup → 偷偷迁移 | L98 / L104 |
| R3-D04 | 不要把 Capability Registry 直接复制到 Android；Android 不能再拥有第二份独立 Capability 真相 | L277 / L307 |
| R3-D05 | 不要假设「一个 capability = 一个 audit action」 | L341 |
| R3-D06 | 第三轮这里不能只继续写文档，必须真正跑起来 | L405 |
| R3-D07 | 不能直接假设你会用 OSS；不要边开发边决定 | L430 / L436 |
| R3-D08 | Migration Lock 和 Scheduler Lock 不是同一个锁（不同名字、不同生命周期） | L461-465 |
| R3-D09 | 不要「代码看起来支持双实例」，要真正同时启动 | L506 |
| R3-D10 | 第三轮不要丢掉 `_trace_order.py` | L556 |
| R3-D11 | request_id / command_id / event_id 不要混成一个；不能假设 1 request = 1 event | L570 / L587 |
| R3-D12 | 不要一开始上大型 Observability 平台（Prometheus/Grafana/Jaeger/Loki/OTel/ELK 全家桶） | L623 |
| R3-D13 | 不要直接 main → production；不要 restart systemd → hope | L683 / L718 |
| R3-D14 | 第一阶段不要直接拿生产做完整写操作测试（先只读） | L755 |
| R3-D15 | Requirements Lock 不要变成「顺手就锁了」，先做依赖可复现性决策 | L889 |
| R3-D16 | 不要用「已经差不多了」——没达退出条件就是没完成 | L1003 |
| R3-D17 | 能通过边界解决，就不要增加 Checker；先改边界，再加检查器 | L1023 |
| R3-D18 | 不再允许「文档语义超过代码事实」（文档说 UI/Audit 已接 Capability，实际没有） | L1054 |
| R3-D19 | 第四轮的东西不要现在提前做（读模型 / 缓存 / 容量规划 / 对象存储 / 高可用 / 弹性扩容 / 更复杂异步） | L1140-1151 |

## 五、必做契约（同样逐条可判定）

| id | 指南要求 | 行号 |
| --- | --- | --- |
| R3-B01 | R3-01-C：建立 **Import Purity 判据**，并且做成真正的反向验证（注入 import → schema version 必须完全不变） | L142-169 |
| R3-B02 | R3-01-E：三个测试（空库 / 旧库 / 双实例并发迁移） | L193-221 |
| R3-B03 | R3-03-D：双实例实验 6 个 + 故障恢复（杀掉 A，B 必须继续工作） | L502-541 |
| R3-B04 | R3-04-A：Trace ID 三个层次不许混 | L562-589 |
| R3-B05 | R3-05-C：生产只读验收清单 `PRODUCTION_ACCEPTANCE.md` | L726-761 |
| R3-B06 | R3-06：五个故障演练（A~E） | L763-802 |
| R3-B07 | R3-07：元系统四条（判据不许静默空转 / 反向验证必须完整还原 / 生成物新鲜度 / 报告事实核对） | L804-888 |
| R3-B08 | §二十六：最终验收矩阵（能力 × 代码/CI/Staging/Production/Failure Drill） | L1097-1123 |

---

## 六、机器契约（判据读这一段）

⛔ 下面每个块都要满足：`id` 唯一、`原文` ≥8 字、`位置` 形如 `L数字`、
`类别` ∈ {禁做, 必做}、`探针` 必须是判据里真实实现的那几个、`判定` ∈ {棘轮, 阶段}。
`判定: 棘轮` = 现在就要守住；`判定: 阶段` = 到 `里程碑` 才开始判定。

`棘轮上限: 1`　`不判定上限: 13`

（`不判定上限` 是**当天的实数**：那几条属于后面里程碑的探针，产物还不存在，所以现在判不了。
这两个数**都只能减不能增** —— 判据会拿 `git show HEAD:docs/R3_CONSTRAINTS.md` 跟上一版比。）

```constraint
id: R3-D01
类别: 禁做
原文: 第三轮不要再继续大规模重构业务代码（不要追求「这轮又改了几千行」）
位置: L6
探针: backend_app_delta
判定: 棘轮
什么时候会守住: 见 docs/R3_PROGRESS.md 对应里程碑的退出条件
```

```constraint
id: R3-D02
类别: 禁做
原文: 不要再按「发现一个问题修一个问题」的方式推进，固定成里程碑
位置: L28
探针: commit_milestone_tag
判定: 棘轮
什么时候会守住: 见 docs/R3_PROGRESS.md 对应里程碑的退出条件
```

```constraint
id: R3-D03
类别: 禁做
原文: 禁止 import → DDL；也禁止 application startup → 偷偷迁移
位置: L98
探针: import_purity
判定: 棘轮
什么时候会守住: 见 docs/R3_PROGRESS.md 对应里程碑的退出条件
```

```constraint
id: R3-D04
类别: 禁做
原文: 不要把 Capability Registry 直接复制到 Android；Android 不能再拥有第二份独立 Capability 真相
位置: L277
探针: android_no_second_truth
判定: 棘轮
什么时候会守住: 见 docs/R3_PROGRESS.md 对应里程碑的退出条件
```

```constraint
id: R3-D05
类别: 禁做
原文: 不要假设「一个 capability = 一个 audit action」，要定义 Audit Coverage
位置: L341
探针: audit_coverage_shape
判定: 阶段
里程碑: R3-02
```

```constraint
id: R3-D06
类别: 禁做
原文: 第三轮这里不能只继续写文档，必须真正跑起来
位置: L405
探针: runtime_evidence
判定: 阶段
里程碑: R3-03
```

```constraint
id: R3-D07
类别: 禁做
原文: 不能直接假设你会用 OSS；不要边开发边决定（上传资产先做架构决策）
位置: L430
探针: upload_decision_record
判定: 阶段
里程碑: R3-03
```

```constraint
id: R3-D08
类别: 禁做
原文: Migration Lock 和 Scheduler Lock 不是同一个锁：不同名字、不同生命周期
位置: L461
探针: distinct_lock_names
判定: 棘轮
什么时候会守住: 见 docs/R3_PROGRESS.md 对应里程碑的退出条件
```

```constraint
id: R3-D09
类别: 禁做
原文: 不要「代码看起来支持双实例」，要真正同时启动两个实例
位置: L506
探针: runtime_evidence
判定: 阶段
里程碑: R3-03
```

```constraint
id: R3-D10
类别: 禁做
原文: 第三轮不要丢掉 _trace_order.py
位置: L556
探针: trace_tool_kept
判定: 棘轮
什么时候会守住: 见 docs/R3_PROGRESS.md 对应里程碑的退出条件
```

```constraint
id: R3-D11
类别: 禁做
原文: request_id / command_id / event_id 不要混成一个；不能假设 1 request = 1 event
位置: L570
探针: trace_id_hierarchy
判定: 棘轮
什么时候会守住: 见 docs/R3_PROGRESS.md 对应里程碑的退出条件
```

```constraint
id: R3-D12
类别: 禁做
原文: 不要一开始上大型 Observability 平台（Prometheus/Grafana/Jaeger/Loki/OTel/ELK 全家桶）
位置: L623
探针: no_observability_stack
判定: 棘轮
什么时候会守住: 见 docs/R3_PROGRESS.md 对应里程碑的退出条件
```

```constraint
id: R3-D13
类别: 禁做
原文: 不要直接 main → production；不要 restart systemd → hope
位置: L683
探针: deploy_ordered_steps
判定: 阶段
里程碑: R3-05
```

```constraint
id: R3-D14
类别: 禁做
原文: 第一阶段不要直接拿生产做完整写操作测试，先只读
位置: L755
探针: smoke_readonly_default
判定: 阶段
里程碑: R3-05
```

```constraint
id: R3-D15
类别: 禁做
原文: Requirements Lock 不要变成「顺手就锁了」，先做依赖可复现性决策
位置: L889
探针: requirements_not_blindly_locked
判定: 棘轮
什么时候会守住: 见 docs/R3_PROGRESS.md 对应里程碑的退出条件
```

```constraint
id: R3-D16
类别: 禁做
原文: 不要用「已经差不多了」——没达退出条件就是没完成
位置: L1003
探针: exit_condition_ledger
判定: 棘轮
什么时候会守住: 见 docs/R3_PROGRESS.md 对应里程碑的退出条件
```

```constraint
id: R3-D17
类别: 禁做
原文: 能通过边界解决，就不要增加 Checker；先改边界，再加检查器
位置: L1023
探针: checker_budget
判定: 棘轮
什么时候会守住: 见 docs/R3_PROGRESS.md 对应里程碑的退出条件
```

```constraint
id: R3-D18
类别: 禁做
原文: 不再允许「文档语义超过代码事实」（Fact first, wording second）
位置: L1054
探针: progress_shape
判定: 棘轮
什么时候会守住: 见 docs/R3_PROGRESS.md 对应里程碑的退出条件
```

```constraint
id: R3-D19
类别: 禁做
原文: 第四轮的东西不要现在提前做（读模型/缓存/容量/对象存储/高可用/弹性扩容/更复杂异步）
位置: L1140
探针: no_premature_round4
判定: 棘轮
什么时候会守住: 见 docs/R3_PROGRESS.md 对应里程碑的退出条件
```

```constraint
id: R3-B01
类别: 必做
原文: 建立 Import Purity 判据，并做成真正的反向验证（注入 import → schema version 不变）
位置: L142
探针: import_purity_dynamic
判定: 阶段
里程碑: R3-01
```

```constraint
id: R3-B02
类别: 必做
原文: R3-01-E 三个测试：空库迁移 / 旧库迁移 / 双实例并发迁移
位置: L193
探针: migration_tests
判定: 阶段
里程碑: R3-01
```

```constraint
id: R3-B03
类别: 必做
原文: 双实例实验 6 个，含「杀掉 A，B 必须继续工作」
位置: L502
探针: runtime_evidence
判定: 阶段
里程碑: R3-03
```

```constraint
id: R3-B04
类别: 必做
原文: Trace ID 三层不许混：request_id → command_id → event_id
位置: L562
探针: trace_id_hierarchy
判定: 棘轮
什么时候会守住: 见 docs/R3_PROGRESS.md 对应里程碑的退出条件
```

```constraint
id: R3-B05
类别: 必做
原文: 生产只读验收清单 PRODUCTION_ACCEPTANCE.md
位置: L726
探针: production_acceptance_doc
判定: 阶段
里程碑: R3-05
```

```constraint
id: R3-B06
类别: 必做
原文: 五个故障演练（worker crash / Redis 挂 / 事件延迟 / 迁移锁竞争 / 磁盘将满）
位置: L763
探针: failure_drill_record
判定: 阶段
里程碑: R3-06
```

```constraint
id: R3-B07
类别: 必做
原文: 元系统四条：判据不许静默空转 / 反向验证完整还原 / 生成物新鲜度 / 报告事实核对
位置: L804
探针: generated_freshness
判定: 阶段
里程碑: R3-07
```

```constraint
id: R3-B08
类别: 必做
原文: 最终验收矩阵：能力 × 代码 / CI / Staging / Production / Failure Drill
位置: L1097
探针: progress_shape
判定: 棘轮
什么时候会守住: 见 docs/R3_PROGRESS.md 对应里程碑的退出条件
```

## 七、棘轮台账（只减不增）

当前 `棘轮上限: 1`。**棘轮已经降过一次**（2 → 1），记录在下面；⛔ 只许继续降。

| 探针 | 现状 | 什么时候归零 |
| --- | --- | --- |
| `android_no_second_truth` | `android/.../ai/AiWrite.kt` 里手抄了后端 `ROLE_PERMISSIONS['shipper']` 的 13 项 | R3-02 |

### 降棘轮记录（每一次都必须写出是哪条命令让它变绿的）

| 日期 | 条目 | 从 | 到 | 是哪条命令 |
| --- | --- | --- | --- | --- |
| 2026-09-26 | `import_purity` | 未守住 | **守住** | `python _tools/qa/_check_import_purity.py` →「import 纯净」（R3-01） |
| 2026-09-26 | `import_purity_dynamic` | 不判定 | **守住** | 产物落地：`_tools/qa/_check_import_purity.py` 存在且含 schema_version/before/after（R3-01） |
| 2026-09-26 | `migration_tests` | 不判定 | **守住** | 产物落地：`_tools/ops/_migration_tests.py --all` → 4/4（R3-01） |

这条棘轮的规则：**上限只能减不能增**（判据会拿 `git show HEAD:docs/R3_CONSTRAINTS.md` 比对上一版），
每减少一条必须在 R3_PROGRESS.md 里写出**是哪条命令让它变绿的**。

