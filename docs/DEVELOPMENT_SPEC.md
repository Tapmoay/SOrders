# SOrders 新功能开发与既有功能修改规范 v1.0

> **来源**：需求方 2026-09-27 交来的规范全文（三十八节）。
> 本页是它**落进这个仓库之后**的版本 —— 规则一条不少，每条都补上 **【本仓库落点】**（真实文件 / 真实命令）
> 与 **【判据】**（有没有机器判据、是哪一条）。⛔ 不把"应该做"写成"已经做到"。
>
> **状态**：✅ 生效（2026-09-27，需求方拍板）。第一个按本规范登记的事项是
> [`GOV-0001`](changes/GOV-0001.md) —— 建立本规范这件事**本身**也走了一遍它自己的流程。
>
> **怎么用这一页**：
>
> | 你要干什么 | 从哪一节开始 |
> | --- | --- |
> | 只想知道动手前必须做什么 | [附录 B · 一页速查卡](#附录-b一页速查卡) |
> | 要开一个**新功能** | §七（F0→F3），模板 `docs/changes/_TEMPLATE.md` |
> | 要**改一个已有功能** | §十二～§十六（CHG 专章），再回 §二十六 定 Blast Radius |
> | 判它到底是 Core 还是 Extension | §三 五问 + [R4_CORE_EXTENSION_MAP.md](R4_CORE_EXTENSION_MAP.md) §7 |
> | 要动**钱 / 状态 / 权限 / 历史 / 迁移** | §八 会自动升级审查等级 —— 先读那一节 |
> | 想知道某条规则**有没有机器判据** | [附录 A · 判据对照表](#附录-a--规则--机器判据对照表) |
>
> ⚠️ **新鲜度**：§一～§三十八 是**规范**（不随代码漂移）；每节的 **【本仓库落点】** 会漂。
> 二者不一致时 **以代码与判据为准**，并顺手改本页。
> 本页的接线判据：`python _tools/qa/_check_dev_spec.py`。

---

## 目录

- [零、这份规范在仓库里的位置](#零这份规范在仓库里的位置)
- [一、先定四个长期身份](#一先定四个长期身份)
- [二、所有开发开始前，先回答六个问题](#二所有开发开始前先回答六个问题)
- [三、第一道门：判断它到底是什么](#三第一道门判断它到底是什么)
- [四、最重要的架构原则](#四最重要的架构原则)
- [五、任何 Extension 必须通过 Contract](#五任何-extension-必须通过-contract)
- [六、数据所有权规则](#六数据所有权规则)
- [七、一个新功能的标准施工流程](#七一个新功能的标准施工流程)
- [八、涉及金额、状态、历史事实时，自动升级审查等级](#八涉及金额状态历史事实时自动升级审查等级)
- [九、API 开发规范](#九api-开发规范)
- [十、数据库修改规范](#十数据库修改规范)
- [十一、配置修改规范](#十一配置修改规范)
- [十二、功能修改规范 —— CHG](#十二功能修改规范--chg)
- [十三、所有 CHG 必须先写旧行为和新行为](#十三所有-chg-必须先写旧行为和新行为)
- [十四、修改不能靠测试都绿了证明完整](#十四修改不能靠测试都绿了证明完整)
- [十五、如果修改的是现有 Contract](#十五如果修改的是现有-contract)
- [十六、不要把配置变化伪装成代码没有变](#十六不要把配置变化伪装成代码没有变)
- [十七、测试规范：判据必须能够判红](#十七测试规范判据必须能够判红)
- [十八、测试数据必须尽量匹配生产形状](#十八测试数据必须尽量匹配生产形状)
- [十九、共享测试资源必须隔离](#十九共享测试资源必须隔离)
- [二十、生产验证规范](#二十生产验证规范)
- [二十一、证据记录规范](#二十一证据记录规范)
- [二十二、改变行为时，要区分三个东西](#二十二改变行为时要区分三个东西)
- [二十三、Feature 的 Add / Replace / Remove 思维](#二十三feature-的-add--replace--remove-思维)
- [二十四、不要为了一个功能建立万能框架](#二十四不要为了一个功能建立万能框架)
- [二十五、防蔓延规则](#二十五防蔓延规则)
- [二十六、Modification Blast Radius](#二十六modification-blast-radius)
- [二十七、任何 L3 修改必须回答一个问题](#二十七任何-l3-修改必须回答一个问题)
- [二十八、Release 规范](#二十八release-规范)
- [二十九、代码、数据、算法不要同时无理由大改](#二十九代码数据算法不要同时无理由大改)
- [三十、Definition of Done](#三十definition-of-done)
- [三十一、不能因为测试绿了就 Complete](#三十一不能因为测试绿了就-complete)
- [三十二、Change 的最终关闭方式](#三十二change-的最终关闭方式)
- [三十三、什么时候必须停下来重新设计](#三十三什么时候必须停下来重新设计)
- [三十四、什么时候不应该整改](#三十四什么时候不应该整改)
- [三十五、Feature Review 的最后一个问题](#三十五feature-review-的最后一个问题)
- [三十六、Modification Review 的最后一个问题](#三十六modification-review-的最后一个问题)
- [三十七、最终开发循环](#三十七最终开发循环)
- [三十八、最终北极星](#三十八最终北极星)
- [附录 A · 规则 → 机器判据对照表](#附录-a--规则--机器判据对照表)
- [附录 B · 一页速查卡](#附录-b一页速查卡)
- [附录 C · 与既有文档的关系 / 这份规范没有解决的事](#附录-c-与既有文档的关系--这份规范没有解决的事)

---

## 零、这份规范在仓库里的位置

### 0.1 谁是权威（五份文档的分工，⛔ 不要互相抄）

| 文档 | 它**只**管这一件事 | 什么时候读 |
| --- | --- | --- |
| **`docs/DEVELOPMENT_SPEC.md`（本页）** | **流程与纪律**：一个事项怎么立项、怎么判边界、怎么证明、怎么关闭 | **动手之前** |
| [`docs/CORE_AND_EXTENSION.md`](CORE_AND_EXTENSION.md) | **核心区文件清单与扩展点清单**：新东西往哪个文件加 | 决定"改哪儿"时 |
| [`docs/R4_CORE_EXTENSION_MAP.md`](R4_CORE_EXTENSION_MAP.md) | **边界事实**：47 张表 / 扩展点 / 事件，各自归谁；五问判定表 | 判 Core 还是 Extension 时 |
| [`docs/R4_CONTRACTS.md`](R4_CONTRACTS.md) | **契约定义**：UnitConversionContract / PricingContract 的输入输出错误不变量 | 写扩展实现时 |
| [`docs/AI_WORK_CLAIM.md`](AI_WORK_CLAIM.md) | **谁正在改什么**（多会话协作）；核心改动声明 | 动手**前**第一件事 |

⛔ **不要让两份文档说同一件事。** 同一句话出现在两处，就一定会出现两处不一致 —— 这是本项目
已经栽过的坑（过期地图比没有地图更糟：读的人会直接相信结论而不再核实）。

### 0.2 三个入口 —— "每次开工都能读到"是怎么被保证的

"写下来的规则会被读到"不是自然发生的，是**接线**出来的。本规范的线接在三处：

| # | 入口 | 机制 | 断了会怎样 |
| --- | --- | --- | --- |
| ① | [`AGENTS.md`](../AGENTS.md) 顶部「开工前必读」段 | 仓库根 `AGENTS.md` **每轮自动进上下文**（无需谁记得去读） | 下一个会话冷启动 → 它对该会话"不存在" |
| ② | 记忆 `target=key`（分支 `p`） | 随上下文快照注入 | 同上 |
| ③ | [`docs/PROJECT_MAP/INDEX.md`](PROJECT_MAP/INDEX.md) 导航表 + 全量文档目录 | 项目地图第一站 | 从地图侧回不到本页（单向引用） |

**判据**：`python _tools/qa/_check_dev_spec.py` 会检查 ①②③ 三处**都还指着本页**。
它红了不是"文档没写"，而是 **"写了的规则已经没人读得到了"**。

### 0.3 一条命令跑完全部判据

```
python _tools/qa/_check_all.py                  # 全部静态检查（清单**自己算**，加新脚本不用登记）
python _tools/qa/_check_all.py --list           # 只看它到底在查什么
python backend/scripts/check_reachability.py    # 自动加载入口 → 全部文档，可达性（报孤儿文档）
```

---

## 一、先定四个长期身份

### 1.1 规则

今后的日常开发，**不再使用 `R4-xx` 作为所有事情的编号**。`R4-xx` 属于
**架构整改 / 治理阶段的历史**（第一轮～第四轮，见 `docs/RECTIFICATION_REPORT_R3.md` 等）。

日常开发使用四种 ID：

| ID | 含义 | 一句话判据 |
| --- | --- | --- |
| **`FEAT-xxxx`** | 新功能 | 原来**没有**，现在增加 |
| **`CHG-xxxx`** | 既有功能修改 | 原来**已经存在**，现在改变行为 |
| **`BUG-xxxx`** | 缺陷修复 | 现在的行为**不符合**已声明的行为 |
| **`GOV-xxxx`** | 开发治理 / 架构治理变化 | 改的是**规则本身**（本页、判据、清单） |

> **一个开发事项必须有唯一身份。**
>
> ⛔ 不要使用「临时改一下」「顺便修一下」「先做着」「这个以后再整理」作为长期工作状态。

### 1.2 编号规则（本仓库约定）

- 每类 **4 位**，**独立自增**（`FEAT-0001`、`CHG-0001`、`BUG-0001`、`GOV-0001` 各走各的）。
- **永不复用、永不回收**：一个号销掉（取消 / 合并）就留一条记录写明"已取消，去向 xxx"，
  ⛔ 不许把号让给别的事项 —— 号一旦被引用过，复用就等于制造两个事实。
- 分配方式：看 `docs/changes/` 目录里的**文件名**（目录即台账，⛔ 没有第二份手写清单）。

### 1.3 【本仓库落点】

| 事项 | 落在哪 |
| --- | --- |
| 事项定义（一条一个文件） | `docs/changes/<ID>.md`（模板 `docs/changes/_TEMPLATE.md`） |
| 谁在做 | `docs/AI_WORK_CLAIM.md`「进行中」每条**第一行带 ID** |
| 代码提交 | commit message **首行以 ID 开头**：`FEAT-0007 司机批量派单：…` |
| 发布证据 | `_tools/ops/` 下的运行记录 + 该 ID 的 `docs/changes/<ID>.md`「关闭」一节 |
| 历史编号 | `R4-xx` / `R3-xx` **保持原样**，⛔ 不回溯改名（改名会让所有已有证据的引用失效） |

### 1.4 【判据】

`python _tools/qa/_check_dev_spec.py`：
① 每个 `docs/changes/<ID>.md` 的文件名 ID 与文件内声明一致；② 不出现重号；
③ 四类前缀都在；④ 模板里的必填小节一份不少。

---

## 二、所有开发开始前，先回答六个问题

### 2.1 规则

任何 `FEAT` / `CHG` / `BUG`，**在写代码之前**先回答：

```text
① 我要解决什么问题？
② 当前用户 / 业务流程是什么？
③ 哪个现有事实或能力会发生变化？
④ 哪些东西**明确不能变化**？
⑤ 这个变化属于 Core、Extension 还是 Infrastructure？
⑥ 什么证据能够证明它完成？
```

### 2.2 尤其是第④条 —— 必须写成两块

```text
Must Change
Must Not Change
```

例（用本仓库真实的业务对象）：

```text
事项：司机重新派单（CHG）

Must Change:
- 新增一次派单操作

Must Not Change:
- 已冻结的 Pricing Decision（orders.pricing_decision_snapshot 及其来源）
- 历史 freight snapshot（orders.driver_rule_snapshot / 账单上的 rule_id）
- Order 生命周期语义（order_flow.py 的状态迁移表）
- Authorization 模型（core/rbac.py 的角色→权限点）
```

> 这会极大减少"改着改着改出别的问题"。

### 2.3 【本仓库落点】

- 六问与两块清单的**载体**是 `docs/changes/<ID>.md`（模板已含小节）。
- `Must Not Change` 里点名到的文件，如果确实非动不可 → 走 §二十七（L3 必答一题）。

### 2.4 【判据】

**人判**。机器只能核"这两个小节存在且非空"（`_check_dev_spec.py` 的模板必填小节项）。

---

## 三、第一道门：判断它到底是什么

### 3.1 五档

```text
CORE
EXTENSION POINT
EXTENSION IMPLEMENTATION
INFRASTRUCTURE
PRESENTATION
```

### 3.2 五问（与 R4 已钉死的判定表是**同一份**，⛔ 不要写第二份）

| # | 问题 | 答"是"的含义 |
| --- | --- | --- |
| ① | 是否**定义核心事实**？ | Core 候选 |
| ② | 是否**改变核心不变量**？ | Core 候选 |
| ③ | 是否**必须永久存在**？ | Core 候选 |
| ④ | 是否可能**出现多个实现**？ | Extension 候选 |
| ⑤ | **删除后 Core 是否仍然成立**？ | Extension 候选 |

- ①②③ 任一明显为"是" ⇒ 优先按 **Core 候选**处理。
- ④⑤ 明显为"是"、且 ①②③ 全为"否" ⇒ 优先按 **Extension 候选**处理。
- **模糊时**：

> **先不要抽象。** 先做一个真实实现。等第二个实现出现，再判断真正应该抽象什么。

### 3.3 【本仓库落点】

- 判定表正文：[R4_CORE_EXTENSION_MAP.md](R4_CORE_EXTENSION_MAP.md) §7（含完整分档规则）。
- **CORE 的实际清单**是文件级的：`_tools/qa/_core_files.txt`（每条都写了"为什么它是核心"）。
- 分档结果必须写进 `docs/changes/<ID>.md` 的「Boundary」一节。

### 3.4 【判据】

| 判据 | 管什么 |
| --- | --- |
| `python _tools/qa/_check_core_extension_boundary.py` | 五条铁律 + Unclassified = 0 |
| `python _tools/qa/_reverse_verify_r4_all.py` | 把每条铁律弄坏一次，看它会不会红 |
| `python _tools/qa/_check_core_freeze.py` | 核心区文件被改却没声明 → 当场红 |

---

## 四、最重要的架构原则

### 4.1 Core 定义"什么是真的"

| 核心事实 | 本仓库的真实落点 |
| --- | --- |
| Order 状态 | `backend/app/services/order_flow.py` |
| Money | `backend/app/services/order_money.py`、`backend/app/core/contracts/money.py` |
| Ledger | `backend/app/services/accounting_service.py` |
| Identity / Authorization | `backend/app/core/rbac.py`、`backend/app/deps.py` |
| Transaction | [BUSINESS_TRANSACTION_MAP.md](BUSINESS_TRANSACTION_MAP.md) + `_tools/qa/_check_business_transactions.py` |
| Audit | `backend/app/models/enums.py::OperationAction` + `_check_audit_coverage.py` |
| 核心持久化不变量 | `backend/app/core/schema_bootstrap.py`（线上结构变更唯一入口） |

（**完整清单**：`_tools/qa/_core_files.txt`。⛔ 上表是举例，不是清单。）

### 4.2 Extension 定义"怎么做"

价格计算 / 单位换算 / 特殊计费 / 税费 / 促销 / 通知 Provider / AI Provider / 导出格式 /
第三方服务适配器 —— 这些**可以变化**。

因此：

> **算法可以替换，核心事实不能被替换。**

R4 指南 §6 把这句话说成：「**"计算"可以扩展，"事实"不能扩展。**」

### 4.3 【本仓库落点】

- 扩展清单与注册表：[R4_EXTENSIONS.md](R4_EXTENSIONS.md)（manifest 字段 / 注册表 / `EXT_*` 配置 / 依赖图）。
- 四类契约：[R4_CONTRACTS.md](R4_CONTRACTS.md) §1。
- 契约代码：`backend/app/core/contracts/`（核心侧）与 `backend/app/extensions/`（扩展侧）。

---

## 五、任何 Extension 必须通过 Contract

### 5.1 禁止

```text
Core → Concrete Extension                        ⛔
Extension → Core Private Function                ⛔
Extension → UPDATE Core Table                    ⛔
Extension → 绕过 Capability                      ⛔
Extension → 直接操作另一个 Extension 的内部数据      ⛔
```

### 5.2 允许

```text
Core Contract
    ↑
Extension Implementation
    ↑
Infrastructure Adapter
```

### 5.3 ⛔ 尤其禁止"万能插件接口"

```python
Plugin.execute(...)     # ⛔ 不要把所有东西塞进一个接口
```

不同能力使用**不同** Contract：

| 类 | 适合什么 | 本项目的契约 | 状态 |
| --- | --- | --- | --- |
| 一 · **Pure Function** | 单位换算、税率、数学、格式转换、纯规则 | `UnitConversionContract v1` | ✅ 已定义 + 已实现 |
| 二 · **Policy** | 定价、折扣、运费、税费、佣金、特殊业务规则 | `PricingContract v1` / **v2**（当前生产用 v2） | ✅ 已定义 + 已实现 |
| 三 · **Provider** | AI、短信、邮件、推送、对象存储、第三方地图 | `NotificationDeliveryContract` / `AiProviderContract` / `ExternalIntegrationContract` | ⏸ 只登记位置，**故意不写契约** |
| 四 · **Presentation / Format** | Excel、PDF、CSV、特殊报表 | `ReportRenderContract` / `ExportContract` | ⏸ 同上 |

> 第三、四类**故意不写契约**：先证明"这个契约真的会被多个实现使用"，再为它设计长期版本兼容。
> 现在它们各只有一个实现，写了就是过度设计。

### 5.4 【判据】

| 判据 | 它盯的原文规则 |
| --- | --- |
| `_tools/qa/_check_extension_contracts.py` | ⛔ 出现 `class Plugin` / `initialize(self)` / `execute(self)` / `shutdown(self)` 就红；`EXTENSION_POINT` 必须 ≥2 个实现或写 `pending_reason`；同一契约版本数设上限且每代必须有真实实现 |
| `_tools/qa/_check_core_extension_boundary.py` | 五条铁律 + Unclassified = 0；核心模型里不许出现扩展专属列 |
| `_tools/qa/_check_extension_dependencies.py` | 核心区文件里不许出现具体扩展的名字（Core → Concrete Extension） |
| `_tools/qa/_check_data_ownership.py` | Extension → Core 表写语句 / 直接写 Ledger（见 §六） |
| `_tools/qa/_reverse_verify_r4_all.py` | 证明上面每一条**真的会红** |

---

## 六、数据所有权规则

### 6.1 规则

任何数据实体都必须有明确 Owner：

```text
orders              → Order Core
ledger / ledgers    → Money / Ledger Core
users               → Identity Core
pricing_rules       → Pricing Extension
provider_config     → Provider Extension
```

非 Owner 只能：`Query` / `Command` / `Event`。**不能** `UPDATE owner_table`。

### 6.2 ⭐ 最贵的一条

> **Extension 不得直接修改 Core-owned financial facts。**
>
> 例如 Pricing 可以 `calculate → Money`，**但不能** `calculate → UPDATE ledger`。

### 6.3 【本仓库落点】

- **表归属表**（跨域 47 张表）：[R4_CORE_EXTENSION_MAP.md](R4_CORE_EXTENSION_MAP.md) §3（核心）/ §4（扩展点与扩展实现）。
- 判据扫描的**表清单不是手写的**：来自 `backend/app/models/**` 的 `__tablename__`。

### 6.4 【判据】

`python _tools/qa/_check_data_ownership.py`（扩展不许对核心拥有的表发写语句；
"直接写 Ledger"是单独一条用例）。

### 6.5 ⚠️ 这条**没有**覆盖到的（如实写着）

本仓库的表归属只登记**跨域表归属**，**没有**登记"谁读了对方的哪个字段"。
粒度再细会变成第二份 schema。出现"读错了字段"的真实事故时再细化
（同一句话也写在 [R4_CORE_EXTENSION_MAP.md](R4_CORE_EXTENSION_MAP.md) §9）。

---

## 七、一个新功能的标准施工流程

### F0 · Feature Definition

创建 `docs/changes/<ID>.md`，必须包含：

```text
Problem
User / Actor
Scenario
Scope
Out of Scope
Must Change
Must Not Change
Owner
Acceptance Criteria
```

**模板**：`docs/changes/_TEMPLATE.md`（照抄，别自己另起一份）。

### F1 · Boundary Decision

明确：`Core` / `Extension` / `Infrastructure` / `Presentation`。

**如果需要修改 Core，必须解释三件事**：

```text
为什么现有 Extension 边界无法解决？
为什么修改 Core 是必要的？
修改后 Core 的不变量是什么？
```

⛔ 不能因为"这样写比较方便"就修改核心。

→ 本仓库的机器形态：改核心文件必须先在 `docs/AI_WORK_CLAIM.md`「进行中」写
`核心改动：<路径> —— 为什么必须动核心：<一句话>`，
否则 `_check_core_freeze.py` 当场红（§二十七）。

### F2 · Behavior Contract

**先写行为，再写实现。** 至少定义：

```text
Input / Output / Success / Failure / Boundary Cases
Side Effects / Authorization / Compatibility
```

```text
输入：order_id、driver_id
成功：产生派单事实
失败：不改变订单状态；不产生半成品 Pricing Fact
```

### F3 · Data Contract

如果涉及数据，必须**提前**定义：

```text
新增哪些字段？谁拥有？什么时候写？什么时候不写？
是否允许 NULL？历史数据怎么办？迁移怎么做？
删除功能后历史数据还能不能解释？
```

> ⭐ **历史事实不能因为新功能被修改成"现在看起来合理的样子"。**
>
> 如果过去没有 provenance：`NULL / unknown` **比**「根据现在的规则猜过去」**更正确**
> —— 前者是一句诚实的"不知道"，后者是一个**看起来像证据的猜测**。

### 7.1 【判据】

- `_check_dev_spec.py`：模板九个小节齐全。
- 涉及迁移 → `_check_migrations.py`；涉及新端点 → `_tools/ai/_write_coverage.py --check`；
  涉及新审计码 → `_check_action_labels.py`；涉及 App 模块 → `_tools/ai/_app_feature_coverage.py --check`。

---

## 八、涉及金额、状态、历史事实时，自动升级审查等级

### 8.1 触发词（命中任意一项就不能走普通流程直接合并）

```text
Money / Ledger / Order Lifecycle / Authorization / Audit
Historical Fact / Pricing Decision / 核心状态 / 数据库迁移
```

### 8.2 至少增加四项

```text
Invariant Review          不变量复核
Backward Compatibility    向后兼容
Migration Review          迁移复核
Runtime Evidence          运行证据（不是"测试绿了"）
```

### 8.3 特别是金额 —— 拆开，不要糊成一个大改动

```text
记录事实的变化        （schema / 字段 / 快照）
        ↓
计算逻辑的变化        （算法 / 规则 / 装配）
```

因为两者出了问题，**排查方向完全不同**。

### 8.4 【本仓库落点】

| 触发词 | 该跑的判据（真实存在） |
| --- | --- |
| Money | `_check_money_contract.py`、`_check_money_dependency.py`、`_check_money_display.py`、`_check_driver_money.py` |
| Ledger | `_check_ledger_cash.py`、`_check_ledger_dashboard.py`、`_check_ledger_manual_entry.py`、`_check_shipper_ledger_stats.py` |
| Order Lifecycle | `_check_order_commands.py`、`_check_status_gate_locking.py`、`_check_order_row_columns.py` |
| Authorization | `_check_permission_model.py`、`_check_permission_points.py`、`_check_inline_role_gates.py` |
| Audit | `_check_audit_coverage.py`、`_check_action_labels.py` |
| Historical Fact | `_check_data_ownership.py`（禁区 9）、`_check_soft_delete_guards.py`、`_check_order_purge_fk.py` |
| Pricing Decision | `_check_pricing_provenance.py`、`_check_golden_set.py`、`_check_canary_freeze.py` |
| 数据库迁移 | `_check_migrations.py`（+ `backend/app/core/schema_bootstrap.py`） |

---

## 九、API 开发规范

### 9.1 新增 API 必须写清九项

```text
Endpoint / Method / Input / Output / Permission
Error / Side Effect / Idempotency / Compatibility
```

### 9.2 ⛔ API 不允许自己创造权限体系

继续使用 **Core Capability / Permission**。⛔ 不要出现 `extension_permission.py`
然后自己再发明一套授权世界。

### 9.3 【本仓库落点】

| 做什么 | 加在哪 |
| --- | --- |
| 端点本体 | `backend/app/api/v1/<域>.py` + `api/v1/router.py` 追加一行 `include_router` |
| 权限 | 现有 `require_roles(...)` / 权限点（`core/rbac.py`），⛔ 不新建体系 |
| 端点索引 | 重跑 `cd backend && python -m scripts.gen_endpoint_index --out ../docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md` |
| AI 读能力 | `python _tools/ai/_gen_ai_read_catalog.py` |

### 9.4 【判据】

`_check_permission_model.py` / `_check_permission_points.py` / `_check_inline_role_gates.py` /
`_check_endpoint_index_fresh.py` / `_check_client_contract.py`；
写端点还会被 `python _tools/ai/_write_coverage.py --check` 拦
（要么加 AI 动作，要么在 `EXCLUDED` 写理由）。

---

## 十、数据库修改规范

### 10.1 所有数据库变化必须回答五问

```text
Owner 是谁？ / Migration 怎么走？ / 旧数据怎么办？
Rollback 怎么办？ / 新旧版本能否并存？
```

### 10.2 三个特别禁止

```text
⛔ 禁止：线上直接手改结构后再补 Migration
⛔ 禁止：应用代码先假设新字段存在，再补 Schema
⛔ 禁止：为了新功能猜着回填历史事实
```

### 10.3 推荐顺序

```text
Schema Design → Migration → Compatibility → Runtime → Application Behavior
```

### 10.4 【本仓库落点】

- **线上迁移的唯一入口**：`backend/app/core/schema_bootstrap.py`（在 `_core_files.txt` 里，
  改它 = 改核心区，必须走 §二十七 的声明）。
- 判据：`python _tools/qa/_check_migrations.py`。
- ⛔ 生产口令 / 密钥一律走环境变量，**不进源码**：`_check_secrets.py`
  （在 `_check_all.py` 必跑组里）。

---

## 十一、配置修改规范

### 11.1 规则

配置必须区分：

```text
CORE_*
EXT_*
INFRA_*
```

⛔ 不要让一个 Extension 到处污染 `.env` / `settings.py` / `main.py` / `config.py`。

### 11.2 新配置必须说明六件事

```text
默认值 / 是否安全 / 缺失时行为 / 生产是否必须显式配置 /
是否影响历史数据 / 是否影响现有实例
```

### 11.3 【本仓库落点】

- **扩展的配置由 manifest 声明**，一律 `EXT_*` 前缀，命名规则 =
  `EXT_<扩展名>_<配置键>`。真实例子：`unit_conversion` 声明 `config=("UNIT_SYSTEM",)`
  → 环境变量 `EXT_UNIT_CONVERSION_UNIT_SYSTEM`
  （见 `backend/app/extensions/unit_conversion/manifest.py`）。
- 判据：`_check_extension_manifest.py`（扩展的环境变量必须由 manifest 声明，且一律 `EXT_*` 前缀）。

### 11.4 ⚠️ 这条**只做到了一半**（如实写着）

- `EXT_*` 有机器判据 ✅
- `CORE_*` / `INFRA_*` 目前**还没有**统一前缀约定与判据 ⛔
  —— 这是本规范**新增**的要求，**不是已经做到的事**。谁先碰到，谁在 `docs/changes/` 里
  立一条 `GOV-xxxx`，把约定与判据一起补齐。

## 十二、功能修改规范 —— CHG

| | 回答的问题 |
| --- | --- |
| **FEAT** | 原来**没有**，现在增加。 |
| **CHG** | 原来**已经存在**，现在**改变行为**。 |

**CHG 比 FEAT 更危险。** 因为：

> **FEAT 主要增加复杂度；CHG 很容易破坏已经存在的假设。**

### 12.1 【本仓库落点】

凡是动到下面这些的人，**默认就是 CHG**（不是 FEAT）：

- `order_flow.py` 的状态迁移 / `order_money.py` 的金额口径 / `driver_pay.py` 的应得
- `order_response.py` 的出参与司机视角门控
- `core/rbac.py` 的权限点 / `deps.py` 的鉴权依赖
- 任何**既有**端点的入参语义、出参字段、错误码
- 任何**既有**配置键的含义（哪怕 Python 一行没改 —— 见 §十六）

---

## 十三、所有 CHG 必须先写"旧行为"和"新行为"

### 13.1 规则

⛔ 不要写"修改报价逻辑"这种。必须写：

```text
Before:
司机修改价格后……

After:
司机修改价格后……
```

再写：

```text
Must Preserve:
- 历史订单
- 已冻结 Pricing Fact
- 权限
- API compatibility
```

### 13.2 为什么 `Must Preserve` 和 `Must Not Change` 要分开写

`Must Not Change` 说的是「**我不改它**」（我的意图）；
`Must Preserve` 说的是「**我证明它没被改**」（我的证据）。
前者是承诺，后者才是验收 —— 一条 CHG 里两者都要有。

### 13.3 【本仓库落点】

模板 `docs/changes/_TEMPLATE.md` 的 CHG 段含
`Before` / `After` / `Must Preserve` / `Blast Radius` 四块，
缺一块 `_check_dev_spec.py` 报红。

---

## 十四、修改不能靠"测试都绿了"证明完整

### 14.1 必须至少证明四件事

```text
① 新行为正确
② 原本不应该改变的行为仍然正确
③ 边界行为正确
④ 错误输入不会产生错误事实
```

也就是 **Positive Test + Regression Test + Boundary Test + Negative Test**。

### 14.2 【本仓库怎么落】

| 你要证明的 | 本项目里"算数"的形式 |
| --- | --- |
| ① 新行为正确 | 该域的 `_check_<域>.py` + 真机/真跑的运行记录 |
| ② 回归 | 全量 `python _tools/qa/_check_all.py` + 该域的 `_reverse_verify_<域>.py` |
| ③ 边界 | 判据里**显式列出的边界用例**（如 §十七 的七类） |
| ④ 错误输入不产生错误事实 | **失败路径判据**：非法输入必须**什么也不写**，并且这条要能被反向验证证明会红 |

⛔ 只跑 ①②的叫"测试通过"，不叫"证明完整"。

---

## 十五、如果修改的是现有 Contract

### 15.1 必须明确是 Compatible 还是 Breaking

**Compatible**（可走普通变更）：新增**可选**字段；新增不会破坏旧实现的能力。

**Breaking**（必须全走）：删除字段 / 修改字段含义 / 改变错误语义 /
改变金额精度 / 改变状态定义。

Breaking 必须同时具备：

```text
Version
Migration
Adapter / Compatibility Layer
Rollback Plan
```

⛔ 不能偷偷把 `v1` 改成"实际上现在是 v1.1 了"。

### 15.2 【本仓库落点】

- 契约版本化的**真实先例**：`PricingContract v1 → v2`
  只加一个方法（见 [R4_CONTRACTS.md](R4_CONTRACTS.md) §3.7）。
- 判据：`_check_extension_contracts.py` ——
  同一契约的**版本数设上限**，且每代必须**有真实存在的实现**
  （防的就是"为了兼容保留 10 代接口"）。
- 客户端兼容：`_check_client_contract.py`。

---

## 十六、不要把"配置变化"伪装成"代码没有变"

### 16.1 规则

```text
价格规则 / Canary / 权限 / Feature Flag
```

即使**没有改 Python**，也可能改变系统行为。因此：

> **行为发生变化，就是一次 Change。**
>
> 不是只有 commit 有代码 diff 才算变更。

### 16.2 【本仓库真实例子】

| 只改配置就能改行为的东西 | 本仓库的判据 |
| --- | --- |
| Canary 比例（当前 **30%**） | `_check_canary_freeze.py`、`_check_canary_config_fingerprint.py` |
| 生产价目 / 运费模板 | `_check_freight_pricing.py`、`_check_golden_set.py` |
| 司机计费规则挂载 | `_check_money_dependency.py` |
| 单位制（`EXT_UNIT_CONVERSION_UNIT_SYSTEM`） | `_check_unit_conversion.py` |
| Feature Flag / 开关 | 由 §十一 的 manifest 判据管前缀与声明 |

→ 只改这些配置的，**照样开一条 `CHG-xxxx`**，§十三 四块照写。

---

## 十七、测试规范：判据必须能够判红

### 17.1 这是 R4-45 之后必须继承的一条

> **如果故意破坏目标，它不能变红，就不算证据。**

重要判据必须尽量包含：

```text
Positive Case / Negative Case / Shape Variation
Missing Data / Unknown Value / Wrong Type / Boundary Value
```

### 17.2 ⛔ 尤其不要让这三种失败变成 PASS

```text
SQL 失败 / stdout 为空 / 解析失败
        ↓
最后变成 before == after == ""
        ↓
PASS          ⛔ 这类问题以后统一禁止
```

**这条不是推演，是踩过的：** R4-49 的 P4-② 第一次跑的"零写入证明"就是**空过的** ——
SQL 里写坏了（引号被转义成两个字面量字符），mysql 报错，stdout 为空，
于是 `before == after == ""` 被判"完全相同、零写入"。
**判据与数据形状不匹配，却给了 PASS。** 修法三条：

① SQL 失败**不许**静默返回空串（非零退出必须让判据红）；
② `before` 必须**非空**才谈"相同"；
③ 表名带库名（裸 `orders` 会 `ERROR 1046 No database selected`）。

### 17.3 【本仓库落点】

- 反向验证：`python _tools/ai/_reverse_verify_all.py`（域子集：`--only ai|qa|notify|fuzz`、
  `--changed`、`--for <文件>`）。**每一份判据原则上都配一份反向验证。**
- 判据自己的判据：`_check_reverse_verify_anchors.py`（注入点必须锚在真代码上）、
  `_check_reverse_verify_restore.py`（跑完必须还原）。
- ⛔ **永远红的检查 = 没有检查**（本项目已栽过两次：`_ai_doc_check.py` 红了 12 轮没人管；
  `_app_feature_coverage.py --check` 红了一整轮，因为收尾清单是手写的）。
  所以 `_check_all.py` 的**清单是自己算的**。

---

## 十八、测试数据必须尽量匹配生产形状

### 18.1 规则

```text
Production:  true / false
Test:        1 / 0            ⛔ 不允许
```

测试必须尽可能使用生产真实数据形状：

```text
NULL / "" / true / false / number / string / unknown enum / missing key
```

否则：

> **测试"逻辑"通过，不代表测试"现实"通过。**

### 18.2 【本仓库落点】

- `python _tools/qa/_check_prod_shape.py`（生产**形状**判据，条数以它自己打印的为准）
- `python _tools/qa/_reverse_verify_prod_shape.py`（注入破坏，证明它会红）
- ⚠️ **这条覆盖的是"生产形状"这一层，不是"所有测试数据"。** 别把它读成"测试数据已经全合规"。

---

## 十九、共享测试资源必须隔离

### 19.1 规则

并发测试不能共享：

```text
SQLite / Lock File / Temp File / Port / Global Cache / Shared Singleton
```

每个并发执行环境必须有自己的资源标识：

```text
DB:    sorders_test_<worker/pid>.db
Lock:  sorders_<worker/pid>.lock
```

同时：

> **cleanup 也必须只清自己的资源。**
>
> ⛔ 不得 `cleanup → rmtree 整个共享目录 → 把别人的测试库删掉`。

### 19.2 【本仓库落点与已知债】

- 判据：`python _tools/qa/_probe_test_db_isolation.py`（跑在 `.test_dbs` 上的隔离探查）。
- ⚠️ **已知债（如实写在这里，别假装没有）**：全量 `pytest` 偶尔会在 `.test_dbs`
  里**残留一个 SQLite 文件**。R4 期间记录在案，**没有修**（不影响结论，但违反本节）。
  谁修好，谁把它升成判据。

---

## 二十、生产验证规范

### 20.1 受控生产测试允许，但必须有七样

```text
test_run_id / test identity / test scope / expected result
actual result / timestamp / environment
```

### 20.2 测试数据必须

> **可识别、可整体筛选、可排除。**

⛔ 不能再制造"几年后不知道这 2409 条是什么"的数据。

### 20.3 ⭐ 本仓库已经付过代价的一条（R4-49）

历史上积压的 **2409 条订单**（2026-05-24 → 2026-09-27）**无法仅依据数据库内容区分来源**：

- 55 个非模拟器账号**全部**创建于 2026-09-21；
- 只有 5 个账号用 `138000000%` 模拟器前缀；
- 于是"它们是历史测试数据"这件事，**在库里读不出来**。

正确写法（**Measurement 与 Judgment 必须分开**）：

> 历史订单数据的来源**无法仅依据数据库内容区分**；本阶段依据需求方对数据来源的领域知识，
> 将其**判定**为历史测试/演练数据，不纳入 Natural Production Observation。
> 判定人：需求方 ｜ 2026-09-27。

⛔ **全面禁止**写成"2409 条都是测试数据"（那是把判断伪装成测量）。

### 20.4 【本仓库落点】

| 东西 | 在哪 |
| --- | --- |
| 测试身份的判定谓词 | `is_test_account`：手机号前缀 `1380000000` + 一位 1–9 |
| 受控验证脚本 | `_tools/ops/_r4v_identity.py` / `_r4v_p4a.py` / `_r4v_p4b.py` |
| 运行记录（真实存在） | `_tools/ops/r4v_records/`（每次一个 JSON，含 `test_run_id`） |
| 冒烟与健康 | `_tools/ops/_prod_smoke.py`、`_check_ops.py` |

---

## 二十一、证据记录规范

### 21.1 任何重要结论都用这个形状

```text
Claim
 ↓
Evidence
 ↓
Command
 ↓
Expected
 ↓
Actual
 ↓
Environment
 ↓
Timestamp
 ↓
Commit
```

例（本仓库真实的一条）：

```text
Claim:      双实例 Pricing Decision 一致
Evidence:   R4V-P4B-A.json / R4V-P4B-B.json / R4V-P4B-comparison.json
Command:    python _tools/ops/_r4v_p4b.py ...
Expected:   same contract / same resolution / same amount
Actual:     PASS
```

### 21.2 ⛔ 禁止

```text
"我跑过了" / "应该没问题" / "看起来一致"
```

作为长期验收结论。

### 21.3 【本仓库落点】

- 一页索引范式：[R4_EVIDENCE_INDEX.md](R4_EVIDENCE_INDEX.md) —— **每行 = 结论 → 真实文件 → 能重跑的入口**。
- 台账里那行 `复现：` **必须指向真实存在的脚本**：
  `_tools/qa/_check_report_facts.py` 会逐条跑（R4-49 抓到过 1 条指向不存在的脚本 —— 这就是它存在的意义）。
- 新增证据页时，**顺手把它接进** [docs/PROJECT_MAP/INDEX.md](PROJECT_MAP/INDEX.md) 的全量文档目录，
  否则 `check_reachability.py` 会报孤儿文档。

---

## 二十二、改变行为时，要区分三个东西

### 22.1 规则

所有复杂功能都强制区分：

```text
Decision
Fact
Projection
```

例如 Pricing：

```text
Pricing Algorithm
      ↓
Decision
      ↓
Core Fact
      ↓
Projection / UI
```

> **UI 显示什么不等于事实改变。**

### 22.2 【本仓库落点】

| 层 | 本仓库的落点 | 判据 |
| --- | --- | --- |
| Algorithm | `backend/app/extensions/pricing/`（PricingContract） | `_check_freight_pricing.py`、`_check_golden_set.py` |
| Decision | `backend/app/core/pricing_runtime.py::decide` | `_check_pricing_provenance.py`、`_check_canary_freeze.py` |
| Fact | 订单上的冻结快照（`pricing_decision_snapshot` 等） | `_check_data_ownership.py`（禁区 9） |
| Projection / UI | 出参门控与界面 | `_check_driver_money.py`、`_check_money_display.py`、`_check_report_boundary.py` |

⛔ 改 Projection 时**不许顺手改 Fact**：这正是 `_check_driver_money.py` 第 4 项钉住的东西。

---

## 二十三、Feature 的 Add / Replace / Remove 思维

### 23.1 对于可替换能力，至少考虑四种动作

```text
Add / Replace / Disable / Remove
```

例如 `Pricing Extension A → Pricing Extension B`，要求：

> **Core 不因为 B 出现而重新认识 B 的具体实现。**

删除 Extension 时四件事必须**区别处理**：

```text
Disable      （关掉，代码还在）
Uninstall    （移出仓库/注册表）
Code Removal （删代码）
Data Removal （删数据）        ⛔ 与上一件不是一回事
```

> **删除实现 ≠ 删除它创造的历史事实。**

### 23.2 【本仓库落点】

真实演练脚本：`python _tools/ops/_r4_remove_drill.py` ——
它会检查：目录移出仓库后，注册表里没有它了、静态检查里没有 orphan import / config。
⚠️ 它自己踩过的坑也写在那里：孤儿引用的标记必须**精确**（第一版拿扩展名当标记，
把核心自己的 `import` 也当成了孤儿引用）。

---

## 二十四、不要为了一个功能建立"万能框架"

### 24.1 规则

出现"第一个功能"时，⛔ 不要马上：

```text
PluginManager / UniversalFactory / GenericProvider
SuperModule / BaseBusinessEngine
```

优先顺序：

```text
真实需求 → 真实实现 → 第二个实现出现 → 找共同部分 → 抽象
```

> 这是 R4 最值得延续的一条经验。

### 24.2 【判据】

`_check_extension_contracts.py` 会扫：
`class Plugin` / `initialize(self)` / `execute(self)` / `shutdown(self)`
—— 出现任何一个就红。同时 `EXTENSION_POINT` 必须**要么有 ≥2 个实现、要么写 `pending_reason`**。

---

## 二十五、防蔓延规则

### 25.1 新功能只能修改自己需要修改的边界

如果 `FEAT-A` 突然需要修改：`Order Core` / `Pricing` /
`Ledger` / `Auth` / `Notification@@ —— **不能直接开干**。必须停下来问：

> **为什么一个功能会同时穿透这么多边界？**

可能是：真正的跨领域业务 / 边界设计错误 / Feature scope 太大。

**先拆问题，再写代码。**

### 25.2 【本仓库落点】

- 依赖方向是**机器可核**的：`_check_extension_dependencies.py`（核心区文件里不许出现具体扩展的名字）。
- 跨域事务的真实地图：[BUSINESS_TRANSACTION_MAP.md](BUSINESS_TRANSACTION_MAP.md)（它就是回答"哪些域天然要一起动"的那一页）。

---

## 二十六、Modification Blast Radius

每一个 CHG 都必须标记影响范围：

| 级别 | 含义 | 例子（本仓库） | 最低要求 |
| --- | --- | --- | --- |
| **L0** | Presentation Only | 按钮位置、颜色、文案、排版 | 最低审查 |
| **L1** | Local Behavior | 局部业务逻辑、局部查询、非核心计算 | **回归测试** |
| **L2** | Contract / Data | API Contract、Database Schema、Extension Contract、跨模块行为 | **兼容性与迁移检查** |
| **L3** | Core / Historical Fact / Security | Core Fact、Money、Ledger、Authorization、Order Lifecycle、Historical Meaning、Security Boundary | **正式变更审查（§二十七）** |

### 26.1 【本仓库落点】

| 级别 | 落到哪些判据 |
| --- | --- |
| L0 | `_check_adaptive_layout.py`、`_check_form_panel_style.py`、`_check_hints.py`、`_check_workbench_header.py` |
| L1 | 该域的 `_check_<域>.py` + `_reverse_verify_<域>.py` |
| L2 | `_check_client_contract.py`、`_check_migrations.py`、`_check_extension_contracts.py`、`_check_endpoint_index_fresh.py` |
| L3 | §二十七 全部 + `_check_core_freeze.py` + `_check_data_ownership.py` + `_check_core_extension_boundary.py` |

⛔ **级别不是自选的**：级别由**改了什么**决定，不由"我觉得这个改动很小"决定。
判据：`docs/changes/<ID>.md` 里的 `Blast Radius` 一行必填（`L0`～`L3`）。

---

## 二十七、任何 L3 修改必须回答一个问题

> **为什么不能通过新增 Extension / Adapter / Contract 来解决？**

- 答案只是"这样改比较方便" → **不通过**。
- 答案是"这个变化本身改变了 SOrders 的核心语义" → 可以修改 Core，但必须写：

```text
Old Invariant
New Invariant
Why Change Is Necessary
Migration
Compatibility
Regression
Rollback
```

### 27.1 【本仓库的三条件 + 声明格式】

核心区**不是永久冻结**，但只能被**证据触发的例外**修改。三条件
（细则与来历见 [CORE_AND_EXTENSION.md](CORE_AND_EXTENSION.md) §2.1）：

| 条件 | 意思 |
| --- | --- |
| ① **有证据** | 理由是生产演练 / 线上原始输出 / 失败用例里的**原始证据**，不是"我觉得这样更好" |
| ② **只治那个病** | 改动范围 = 证据界定的**那一条链**；⛔ 顺手做的重构不算例外 |
| ③ **写下来** | 声明行 + 一条「**演练 → 缺陷 → 修复 → 重跑**」证据链 |

声明行写在哪（判据只认这一节）：

```text
docs/AI_WORK_CLAIM.md 的「## 进行中」

核心改动：backend/app/services/order_money.py —— 为什么必须动核心：退货红冲要多带一个来源标记
```

**证据档**（`socket_io.py` 这一项要写全四格：证据 / 原因 / 范围 / 影响面运行时证明）：
见 `_tools/qa/_core_files.txt` 的文件头与 [CORE_AND_EXTENSION.md](CORE_AND_EXTENSION.md) §2.2。

---

## 二十八、Release 规范

### 28.1 任何进入生产的 Feature / CHG 都走这条链

```text
Code → Unit / Integration Tests → Static Checks → Migration Check
     → Backup → Deploy → Health → Smoke → Runtime Verification → Observation
```

涉及核心 / 金额 / 数据迁移时：**Rollback Plan 必须在发布前存在。**

### 28.2 【本仓库落点 —— 全是可执行的】

```text
python _tools/qa/_check_all.py                              # Static Checks（清单自己算）
python _tools/backup/_pre_release.py --note "上线 FEAT-0007（改了什么）"   # Backup（发布前**必做**）
python _tools/deploy/_release.py                            # Deploy：backup→stage→migrate→verify→start→health→smoke→business
```

- 冒烟：`_tools/ops/_prod_smoke.py`（ERROR 0 才算过）；健康：`_tools/ops/_health_check.py`。
- 发布后必须确认「**生产 HEAD == 本地 HEAD**」，否则 `_check_backend_fresh.py` / 冒烟会红。

### 28.3 ⚠️ 这一轮修掉的一个**假红**（记在这里，防止它回来）

R4-49 时 `_release.py` 的 `start` 步骤连续 3 次给**健康部署**报 FAIL：
它用**固定等待**（重启后歇几秒再探一次），而那一刻 `/health` 返回 `000@@，
同一时刻手工 `curl` 却是 200。

> **假红多了，人会学会无视红** —— 而"永远红的检查 = 没有检查"是本项目认过的账。

修法：改成**有上限的轮询**（探到 200 立刻过），并加自检判据钉住不许回退。

---

## 二十九、代码、数据、算法不要同时无理由大改

如果一个功能同时涉及 `Schema + Algorithm + Configuration + API`，
优先拆成多个可解释变化：

```text
CHG-001  Schema
CHG-002  Runtime
CHG-003  Behavior Switch
```

这样出现问题时知道：**是数据库？是算法？是配置？还是装配？**

（这条与 §八·8.3「金额要拆开」是同一条原则的两种写法。）

---

## 三十、Definition of Done

一个 `FEAT` / `CHG` 只有满足下面条件才能标 **Complete**：

```text
□ Problem 明确                    □ Scope 明确
□ Boundary 明确                   □ Must Change 明确
□ Must Not Change 明确

□ Contract 明确                   □ Data Ownership 明确
□ Permission 明确                 □ Compatibility 明确

□ 正向测试                        □ 回归测试
□ 边界测试                        □ 反向 / 失败测试

□ Static Checks                   □ Runtime Checks（必要时）
□ Migration Evidence（必要时）

□ 文档更新                        □ 运行证据保存
□ 配置变更记录                    □ Rollback 方案（必要时）

□ 没有 orphan route               □ 没有 orphan capability
□ 没有 orphan config              □ 没有 orphan import
□ 没有未声明的数据所有权
□ 没有 orphan 文档                ← 本仓库新增的一条（见下）

□ 工作区干净                      □ Commit 身份明确（首行 = 本事项 ID）
```

### 30.1 每一条"没有 orphan X"在本仓库的真实判据

| DoD 项 | 判据（真实存在） |
| --- | --- |
| 没有 orphan route / capability | `_check_capability_registry.py`、`_check_capability_unification.py` |
| 没有 orphan config | `_check_extension_manifest.py`（扩展配置必须由 manifest 声明） |
| 没有 orphan import / 死代码 | `_check_dead_code.py`、`_check_dep_declaration.py`、`_check_import_purity.py` |
| 没有 orphan 脚本 | `_check_tool_scripts.py` |
| **没有 orphan 文档** | `python backend/scripts/check_reachability.py`（从 `AGENTS.md` 做图遍历，报不可达的文档） |
| 没有未声明的数据所有权 | `_check_data_ownership.py` + `_check_core_extension_boundary.py`（Unclassified = 0） |
| 工作区干净 | `git status --porcelain` 为空 ＋ `_check_secrets.py` |

⭐ 「**没有 orphan 文档**」这一条是本规范**新增**的：一份证据页写在仓库里却从入口到不了，
**对新会话就等于不存在**。它和 orphan route 是同一种病。

---

## 三十一、不能因为"测试绿了"就 Complete

Complete 的定义**不是** `Tests = PASS`，而是：

```text
Behavior + Boundary + Evidence + Compatibility + Operational Safety
```

全部满足。

---

## 三十二、Change 的最终关闭方式

每个 CHG 最后都要在 `docs/changes/<ID>.md` 里回答六格：

```text
Changed:                  ______
Preserved:                ______
Evidence:                 ______
Known Limitations:        ______
Rollback:                 ______
Historical Data Impact:   ______
```

### 32.1 尤其是 `Preserved`

因为修改旧功能最大的问题不是「新功能有没有工作？」而是：

> **「旧世界还有什么东西被我偷偷改变了？」**

`Preserved` 一格必须写**能被复核的东西**（哪个判据、哪份记录、哪次 diff），
⛔ 不写"我确认没影响"。

---

## 三十三、什么时候必须停下来重新设计

出现以下任一情况，**禁止继续堆代码**：

```text
① Core 出现第三个 extension-specific if
② 一个 Feature 开始直接修改多个 Core 表
③ 一个 Extension 需要读取另一个 Extension 的内部结构
④ 同一个业务事实出现两个 Owner
⑤ 一个 API 出现第二套权限体系
⑥ 同一历史事实需要两个解释来源
⑦ 为了兼容新功能必须修改大量无关模块
⑧ 为一个功能开始创建 Universal Factory / Universal Plugin
⑨ 测试 checker 无法构造阴性对照
⑩ 不知道某个修改会不会影响历史数据
```

出现这些，不是"继续干"，而是：

> **回到 Boundary / Contract 重新设计。**

### 33.1 其中几条已经有机器判据

| 条 | 判据 |
| --- | --- |
| ② Extension 直接改 Core 表 | `_check_data_ownership.py` |
| ④ 同一事实两个 Owner | `_check_core_extension_boundary.py`（Unclassified = 0）、`_check_single_source.py` |
| ⑤ 第二套权限体系 | `_check_permission_model.py`、`_check_permission_points.py` |
| ⑧ Universal Factory | `_check_extension_contracts.py` |
| ⑨ checker 无法构造阴性对照 | `_check_reverse_verify_anchors.py` + 每份判据自己的 `_reverse_verify_*` |
| ①②③⑥⑦⑩ | **人判**（⚠️ 如实写着：这几条机器判不了，所以它们写在**这一页**，让动手的人先读到） |

---

## 三十四、什么时候"不应该整改"

同样重要。出现 `代码有点丑` / `一个文件有 500 行` / `重复三行代码` /
`未来可能会有第二个实现` —— **都不代表**要重构、拆模块、建抽象框架。

只有：

> **实际变化已经证明当前结构阻碍变化。**

才进入架构修改。

### 34.1 【本仓库的对应纪律】

- 核心区清单里**故意不写**"模块数 ≥ N"这类目标（见 [R4_CORE_EXTENSION_MAP.md](R4_CORE_EXTENSION_MAP.md) §8 禁区 14/15：
  这两条**只能人判**）。
- ⛔ 不许把"能拆"误认为"值得拆"。

---

## 三十五、Feature Review 的最后一个问题

所有新功能完成前问：

> **如果明天这个功能被删除，Core 能不能继续正常成立？**

- **Yes** → 边界大概率健康。
- **No** → 必须重新检查：它到底是不是 Core？还是只是被**错误地塞进** Core？

---

## 三十六、Modification Review 的最后一个问题

所有修改完成前问：

> **如果把这次修改回滚，哪些历史事实必须保持完全不变？**

答案应该明确：

```text
历史订单 / 历史金额 / 历史 Pricing Decision
历史 Provenance / Audit / Ledger
```

**不能因为功能修改而重新解释。**

---

## 三十七、最终开发循环

### 37.1 新功能

```text
问题 → 定义 → 边界 → Contract → Invariant
     → 实现 → 测试 → 证据 → 发布 → 观察 → 关闭
```

### 37.2 修改旧功能

```text
现状 → Old Behavior → Desired Behavior → Must Preserve
     → Impact Level → 实现 → Regression → Evidence → 发布 → 关闭
```

---

## 三十八、最终北极星

⛔ 不要用「代码越模块化越好」作为架构目标。
⛔ 也不要用「改动越少越好」作为变更目标。

真正应该遵守的是：

> **稳定的东西保持稳定，变化的东西把变化限制在自己的边界内。**

进一步：

> **一次修改应该只改变它被明确授权改变的东西，同时用证据证明它没有偷偷改变其他东西。**

再进一步：

> **好的开发不是让系统永远不变化，而是让系统能够变化，却不会因为变化失去自己的语义。**

---

## 附录 A · 规则 → 机器判据对照表

> ⛔ 这张表的用法：**先看"能判红吗"这一列**。
> 写"人判"的，不是"不用管"，而是"机器管不了，所以它写在这一页，靠你读到"。

| 规范节 | 规则的机器形态 | 判据（真实存在） | 能判红吗 |
| --- | --- | --- | --- |
| §一 身份 | 每个事项有唯一 ID，无重号，文件名与声明一致 | `_tools/qa/_check_dev_spec.py` | ✅ |
| §一/§零 接线 | `AGENTS.md` / 记忆 / 地图 三处都指着本页 | `_tools/qa/_check_dev_spec.py` | ✅ |
| §三 分档 | 五问分档、Unclassified = 0 | `_check_core_extension_boundary.py` | ✅ |
| §四 Core 不变 | 核心区文件不许被静默修改 | `_check_core_freeze.py` + `_reverse_verify_core_freeze.py` | ✅ |
| §五 契约 | ⛔ 万能基类；契约必须有实现或理由 | `_check_extension_contracts.py` | ✅ |
| §五 Core→Extension | 核心区文件里不许出现扩展名 | `_check_extension_dependencies.py` | ✅ |
| §六 数据所有权 | 扩展不许写核心表 / 不许写 Ledger | `_check_data_ownership.py` | ✅ |
| §九 API | 权限点只有一套；端点索引不过期 | `_check_permission_points.py` / `_check_permission_model.py` / `_check_endpoint_index_fresh.py` | ✅ |
| §九 写端点 | 新写端点必须有 AI 动作或书面理由 | `_tools/ai/_write_coverage.py --check` | ✅ |
| §十 迁移 | 迁移可重放、与模型一致 | `_check_migrations.py` | ✅ |
| §十 口令 | 口令/密钥不进源码 | `_check_secrets.py` | ✅ |
| §十一 配置 | 扩展配置由 manifest 声明且 `EXT_*` | `_check_extension_manifest.py` | ✅（仅 `EXT_*`） |
| §十四 四件事 | 正向/回归/边界/反向 | 各域判据 + `_reverse_verify_*` | ✅（分域） |
| §十五 契约兼容 | 版本数上限、每代有真实实现 | `_check_extension_contracts.py` | ✅ |
| §十六 配置即变更 | Canary / 价目 / 单位制被冻结 | `_check_canary_freeze.py` / `_check_golden_set.py` / `_check_unit_conversion.py` | ✅ |
| §十七 判据能判红 | 每份判据配反向验证；注入点锚在真代码 | `_reverse_verify_all.py` / `_check_reverse_verify_anchors.py` / `_check_reverse_verify_restore.py` | ✅ |
| §十八 生产形状 | 测试数据形状 = 生产形状 | `_check_prod_shape.py` + `_reverse_verify_prod_shape.py` | ✅（形状层） |
| §十九 资源隔离 | 并发测试各自资源、cleanup 只清自己 | `_probe_test_db_isolation.py` | ⚠️ 部分（见 §19.2 已知债） |
| §二十 生产验证 | 测试数据可识别可排除 | `is_test_account` 谓词 + `_tools/ops/r4v_records/` | ⚠️ 靠记录纪律 |
| §二十一 证据 | 台账 `复现：` 指向真实脚本 | `_check_report_facts.py` | ✅ |
| §二十二 Decision/Fact/Projection | 事实与投影不许互相改写 | `_check_pricing_provenance.py` / `_check_driver_money.py` / `_check_report_boundary.py` | ✅ |
| §二十三 Add/Replace/Remove | 移除后无 orphan import/config | `_tools/ops/_r4_remove_drill.py` | ✅（演练式） |
| §二十四 不要万能框架 | 见 §五 | `_check_extension_contracts.py` | ✅ |
| §二十六 Blast Radius | 级别必填 | `_check_dev_spec.py`（模板必填小节） | ✅ |
| §二十七 L3 声明 | 改核心必须有声明行（含证据档四格） | `_check_core_freeze.py` 第 3/4/6 条 | ✅ |
| §二十八 发布 | 备份 → 发布 → 冒烟 → 版本一致 | `_tools/backup/_check_backup.py --check` / `_tools/deploy/_release.py` / `_tools/ops/_prod_smoke.py` | ✅ |
| §三十 DoD | 五类 orphan 全为零 | 见 §30.1 表 | ✅ |
| §三十 / orphan 文档 | 每份文档从入口可达 | `backend/scripts/check_reachability.py` | ✅ |
| §二/§十三 六问与 Before-After | 小节存在且非空 | `_check_dev_spec.py` | ⚠️ 只核存在，内容人判 |
| §三十三 ①②③⑥⑦⑩ | 停下来重新设计 | —— | ⛔ **只能人判**（写在本页） |

---

## 附录 B · 一页速查卡

```text
开工前（四行，缺一行就别动手）
  1. 给它一个身份：FEAT-xxxx / CHG-xxxx / BUG-xxxx / GOV-xxxx
  2. 在 docs/AI_WORK_CLAIM.md「进行中」写一行（**首行带 ID** + 改哪些文件 + 明确不碰哪些）
  3. 在 docs/changes/<ID>.md 写六问 + Must Change / Must Not Change
  4. 判边界：Core 还是 Extension？（五问；模糊就先做真实实现）

写代码时
  · 新东西走扩展点，⛔ 不改核心
  · 必须动核心 → 声明行 +（socket_io.py 还要写全四格证据）
  · 一个功能同时穿透 Order Core / Pricing / Ledger / Auth / Notification → 停下来先拆

改已有功能（CHG）
  · Before / After / Must Preserve / Blast Radius 四块
  · 四件事都证明：正向 + 回归 + 边界 + 反向
  · 只改配置也是 Change（Canary / 价目 / 开关）

收工前
  · python _tools/qa/_check_all.py
  · python backend/scripts/check_reachability.py        # 没有 orphan 文档
  · 必要的域跑 _reverse_verify_<域>.py（证明判据真的会红）
  · docs/changes/<ID>.md 补齐六格：Changed / Preserved / Evidence /
    Known Limitations / Rollback / Historical Data Impact
  · 发布走：_pre_release.py → _release.py → 冒烟 → 生产 HEAD == 本地 HEAD

⛔ 永远不要
  · "临时改一下" / 拿"测试绿了"当完成
  · 把 SQL 失败 / 空 stdout / 解析失败 变成 PASS
  · 让判据永远红（永远红的检查 = 没有检查）
  · 把判断（Judgment）写成测量（Measurement）
  · 为了兼容新功能去改一堆无关模块
  · 为了"未来可能有第二个实现"现在就建框架
```

---

## 附录 C · 与既有文档的关系 / 这份规范**没有**解决的事

### C.1 与 R4 的关系

| R4 建立了什么 | 本规范怎么用它 |
| --- | --- |
| 核心 / 扩展边界图（[R4_CORE_EXTENSION_MAP.md](R4_CORE_EXTENSION_MAP.md)） | §三/§四/§六 的**事实来源**（本规范不重写它） |
| 四类契约（[R4_CONTRACTS.md](R4_CONTRACTS.md)） | §五 的**定义来源** |
| 清单/注册表/配置/装配（[R4_EXTENSIONS.md](R4_EXTENSIONS.md)） | §十一 的**约定来源** |
| 受控生产验证与证据纪律（[R4_CONTROLLED_VALIDATION.md](R4_CONTROLLED_VALIDATION.md)、[R4_EVIDENCE_INDEX.md](R4_EVIDENCE_INDEX.md)） | §二十/§二十一 的**先例** |
| 核心区证据触发的例外（[CORE_AND_EXTENSION.md](CORE_AND_EXTENSION.md) §2.1/§2.2） | §二十七 的**规则来源** |

> **R4 属于"架构整改 / 治理阶段历史"**；从本规范生效起，新事项用四种 ID，
> ⛔ **不再造 R4.1 / R5**（用户 2026-09-27 明确：不要"以后可能出问题"就提前再造一轮整改）。

### C.2 这份规范**没有**解决的事（如实列着）

| 没做到的 | 为什么 | 什么时候补 |
| --- | --- | --- |
| `CORE_*` / `INFRA_*` 配置前缀**没有**约定与判据 | 本仓库此前只有 `EXT_*` 被 manifest 管住 | 谁先碰到谁立 `GOV-xxxx`（§11.4） |
| §三十三 的 ①②③⑥⑦⑩ **只能人判** | 机器判不了"这算不算穿透了边界" | 出现真实事故、能写出判据时再补 |
| 六问 / Before-After / Must Preserve 的**内容质量** | 机器只能核小节存在且非空 | 靠 review；写得糊的会被下一轮的自己读到 |
| `.test_dbs` 残留在全量 pytest 下偶发 | 已记录、未修（§19.2） | 谁修好谁升成判据 |
| 「核心不能被插件替换」没有**运行期**判据 | 它是设计约束，不是运行时可观测性质 | R4 的 Add/Replace 演练**间接**证明过（核心修改数 = 0） |

> ⛔ 把上面这些当"待办清单"看是对的；当"没做的事就不算数"看是错的 ——
> **它们被写在这里，就是为了让下一个人知道边界在哪，而不是重新推一遍。**
