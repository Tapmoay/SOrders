# <ID> · <一句话标题>

> **复制这一份**（`docs/changes/_TEMPLATE.md`）→ 改名成 `<ID>.md` → 逐格填。
> ⛔ **别删小节**：`_check_dev_spec.py` 按小节名核对；确实不适用就写
> `（不适用：<理由>）` —— **空着**和**写"不适用"**是两件事，前者报红。

---

- **ID**：`FEAT-0000`
- **类型**：FEAT / CHG / BUG / GOV
- **状态**：草拟 / 进行中 / 已关闭 / 已取消（去向 xxxx）
- **Owner**：<谁>
- **开工日期**：YYYY-MM-DD ｜ **关闭日期**：YYYY-MM-DD
- **Blast Radius**：L0 / L1 / L2 / L3

---

## ① 六问

```text
① 我要解决什么问题？
② 当前用户 / 业务流程是什么？
③ 哪个现有事实或能力会发生变化？
④ 哪些东西明确不能变化？
⑤ 这个变化属于 Core、Extension 还是 Infrastructure？
⑥ 什么证据能够证明它完成？
```

① <答>
② <答>
③ <答>
④ <答>
⑤ <答>
⑥ <答>

---

## ② Must Change / Must Not Change

```text
Must Change:
- <…>

Must Not Change:
- <…>
```

---

## ③ Boundary（Core / Extension / Infrastructure / Presentation）

- **结论**：<CORE / EXTENSION POINT / EXTENSION IMPL / INFRASTRUCTURE / PRESENTATION / 不适用：<理由>>
- **五问依据**（规范 §三）：
  - ① 是否定义核心事实？<是/否 + 一句>
  - ② 是否改变核心不变量？<是/否 + 一句>
  - ③ 是否必须永久存在？<是/否 + 一句>
  - ④ 是否可能出现多个实现？<是/否 + 一句>
  - ⑤ 删除后 Core 是否仍然成立？<是/否 + 一句>
- **要改 Core 时的三问**（规范 §F1，只在结论含 CORE 时填）：
  - 为什么现有 Extension 边界无法解决？<…>
  - 为什么修改 Core 是必要的？<…>
  - 修改后 Core 的不变量是什么？<…>
- **核心改动声明行**（改核心区文件时**必须**，写在 `AI_WORK_CLAIM.md`「进行中」）：
  `核心改动：<路径> —— 为什么必须动核心：<一句话>`

---

## ④ Behavior Contract

```text
Input          <…>
Output         <…>
Success        <…>
Failure        <…>（失败时**不**发生什么：不改变状态 / 不产生半成品事实）
Boundary Cases <…>
Side Effects   <…>
Authorization  <用哪个既有权限点，⛔ 不新建体系>
Compatibility  <Compatible / Breaking + 理由>
```

---

## ⑤ Data Contract

- **新增/改动哪些字段**：<…>
- **Owner 是谁**：<…>（归属表见 `docs/R4_CORE_EXTENSION_MAP.md` §3/§4）
- **什么时候写 / 什么时候不写**：<…>
- **是否允许 NULL**：<…>
- **历史数据怎么办**：<…>
  ⛔ 过去没有 provenance 就写 `NULL / unknown`，**不许**按现在的规则猜过去。
- **迁移怎么做 / Rollback 怎么办**：<…>
- **删除本功能后历史数据还能不能解释**：<…>

---

## ⑥ CHG 专章（FEAT / GOV 不适用时写「不适用：<理由>」）

### Before

<改之前，用户看到的 / 系统做的是什么。写具体动作，⛔ 不写"修改了 X 逻辑"。>

### After

<改之后，同样的动作会变成什么。>

### Must Preserve

```text
- 历史订单 / 历史金额 / 已冻结的 Pricing Fact
- 历史 Provenance / Audit / Ledger
- 权限
- API compatibility
- <本事项特有的：…>
```

### Blast Radius（L0～L3）

<级别 + 一句为什么；各级要求见规范 §二十六>

---

## ⑦ 测试（四件事都要，缺一件就不算完整）

| | 本事项怎么做 | 结果 |
| --- | --- | --- |
| **正向** Positive —— 新行为正确 | <判据 / 记录> | |
| **回归** Regression —— 原本不该变的仍然正确 | `python _tools/qa/_check_all.py` + <域判据> | |
| **边界** Boundary | <显式列出的边界用例> | |
| **反向 / 失败** Negative —— 错误输入不产生错误事实 | <失败路径判据 + 它会红的证明> | |

⛔ 判据必须**能判红**：配一份 `_reverse_verify_*.py`，或说明为什么不配。
⛔ 别让 `SQL 失败 / 空 stdout / 解析失败` 变成 `before == after == ""` → PASS（规范 §17.2）。

---

## ⑧ 证据

按规范 §二十一 的八段式，每行 = 结论 → 真实文件 → 能重跑的入口。

| Claim | Evidence（文件） | Command（入口） | Expected | Actual |
| --- | --- | --- | --- | --- |
| <…> | <…> | <…> | <…> | <…> |

- **Environment**：<本地 / 生产，版本、HEAD>
- **Timestamp**：<…>
- **Commit**：<…>

⛔ 禁止「我跑过了」「应该没问题」「看起来一致」。

---

## ⑨ 关闭（六格）

```text
Changed:                ______
Preserved:              ______
Evidence:               ______
Known Limitations:      ______
Rollback:               ______
Historical Data Impact: ______
```

**最后一个问题**（规范 §三十五 / §三十六）：

- FEAT：如果明天这个功能被删除，Core 能不能继续正常成立？<是 / 否 + 一句>
- CHG：如果把这次修改回滚，哪些历史事实必须保持完全不变？<…>
