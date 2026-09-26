# 核心不动，其余插件式扩展

> 用户 2026-09-21 原话：
> 「我们现在…在改东西、再加购加功能的话，我们采一个核心的准则就是**核心的逻辑代码是不要乱动、
> 核心是不要变**，然后其他的就是**以插件的形式** —— **能调方法调方法、能继承就继承、能调 API 就调 API**。」

这份文档是那条准则的落地：**哪些文件算核心**、**新功能该往哪儿加**、**怎么自检**。
准则的机器判据是 `_tools/qa/_check_core_freeze.py`（反向验证 `_tools/qa/_reverse_verify_core_freeze.py`）。

---

## §1 三条路（加/改功能时按这个顺序想）

| 想做的事 | 该走的路 | 例子（仓库里真实存在的） |
| --- | --- | --- |
| 已有能力「外面再包一层」 | **调方法**（组合 / 装饰器） | `ai/AiWriteBatch.kt` 包住任何一个既有 AI 写处理器：既有处理器**一行都没改** |
| 有一族东西只差几个参数 | **继承 / 声明式规格** | `CrudWriteHandler` + `CrudSpec`：26 个"改某个实体的某几个字段"的动作不写处理器 |
| 要动数据 / 要落库 | **调 API**（后端端点） | 所有 AI 写动作都走 App 已有的 `AppRepository` → 后端端点，不为 AI 造接口 |

⛔ **反过来的路不要走**：为了加一个小功能去改核心文件里的算法；为了接一个页面去改订单状态机；
为了让界面好看一点去改钱的口径。那些"顺手"的改动**不会报错**，只会让下一次对账差一笔钱。

## §2 什么算「核心」

核心区清单在 **`_tools/qa/_core_files.txt`**（每条都写了"为什么它是核心"）。一句话概括：

- **钱**：一张单的钱、司机应得、退货红冲、账本入账、货主核销（`order_money` / `driver_pay` /
  `order_return` / `accounting_service` / `shipper_settle`）
- **状态与权限**：订单状态迁移、角色权限点、鉴权依赖、领域词汇表（`order_flow` / `rbac` / `deps.py` / `enums.py`）
- **口径**：业务时区（UTC naive 存库）、订单出参与司机视角门控（`business_time` / `order_response`）
- **线上数据**：生产库结构变更的唯一入口（`core/schema_bootstrap.py`）
- **AI 的写闸门**：`ai/AiWriteService.kt`（preview → 确认卡 → execute 的唯一写入口）
- **可靠投递**：`core/socket_io.py`（推送的最底层原语，`sio.emit` 只在这里；发件箱的「至少一次投递」
  承诺就建立在它的**成败语义**上 —— R3-06 生产 Drill C 证明它位于可靠投递边界，所以它不因为「想做插件化」
  就被拆出核心，见 §2.1）

### 改了核心文件必须做的一件事

在 `docs/AI_WORK_CLAIM.md` 的 **「## 进行中」** 一节里写一行（照抄这个格式）：

```
核心改动：backend/app/services/order_money.py —— 为什么必须动核心：退货红冲要多带一个来源标记
```

- 判据只认**这一节**里的这一行；写在文件末尾的记录区等于没写。
- 判据只看**未提交**的改动：提交之后改动进了 git 历史，声明页不再是唯一记录。
- 判据是 **fail-closed** 的两条：①清单不许被掏空（骨架文件少一个就红）②清单里不许有化石
  （路径不存在就红）—— 所以"把条目删掉"这条捷径走不通。

### §2.1 核心区**不是永久冻结**：它只能被「证据触发的例外」修改（R4-00，2026-09-27）

这条规则的**来历**是 R3 的最后一段：生产故障演练 Drill C 用原始输出证明了一件与"冻结"相反的事 ——
一条真实业务写入的发件箱事件被记成 `sent attempts=0`，而日志里有 16 条
`Cannot publish to redis... giving up`。**继续冻结，会让"运行时正确"这个结论被一个已被实测抓到的
P1 架住**（全过程见 `docs/R3_FAILURE_DRILL_EVIDENCE.md` §三·发现 2）。

所以用户 2026-09-26 拍板，把规则改成下面三条件（同一份写在 `_tools/qa/_core_files.txt` 的文件头）：

| 条件 | 意思 | 缺了它会发生什么 |
| --- | --- | --- |
| ① **有证据** | 改的理由是**生产演练 / 线上原始输出 / 失败用例**里的原始证据，不是"我觉得这样更好" | 核心区会变成"谁想改都能改"，冻结这条线名存实亡 |
| ② **只治那个病** | 改动范围 = 证据界定的**那一条链**；⛔ 顺手做的重构 / 换实现 / 加抽象层**不算例外** | 一次例外会滚成一次大重构 —— 正是 R4 指南 §44 点名要拦住的那条路 |
| ③ **写下来** | 「进行中」一行 `核心改动：<路径> —— 为什么必须动核心：…`，外加一条「**演练 → 缺陷 → 修复 → 重跑**」证据链 | 下一个人只看得到"核心被改过"，看不到"为什么非改不可" |

⛔ **反面同样成立：没有这三件事就不许动核心。** 判据 `_check_core_freeze.py` 的第 3 条（未提交的改动
必须当场声明）与第 4 条（HEAD 那个提交碰过的核心文件也要有一行）就是条件 ③ 的机器形态；
①与②机器判不了，所以它们**逐条写在核心清单的文件头**，让动手的人先读到 —— 不是靠记性。

## §3 扩展点清单（新东西往这些地方加）

| 要加的东西 | 加在哪 | 别做什么 |
| --- | --- | --- |
| AI 能做的**写动作** | `ai/AiWrite.kt::AiWrites.ALL` 追加一个 `AiWriteAction`（能用 `CrudSpec` 描述就**别**写处理器） | ⛔ 别改 `preview_write` / `execute` 的链路；⛔ 别把动作加进 `undoOnly` 之外还被模型看见的名单 |
| 需要特殊状态核对的写动作 | 新增 `AiWriteHandler` 实现（一个域一个文件） | ⛔ 别在既有处理器里加 `if (actionId == …)` 分支 |
| **批量**形式的写动作 | 什么都不用做：`ai/AiWriteBatch.kt` 会包住每一个处理器；只需在动作上标 `batch = true` | ⛔ 别为批量改处理器内部 |
| AI 的**读能力** | `ai/AiReadCatalog.kt`（机器生成：`python _tools/ai/_gen_ai_read_catalog.py`）或本机能力 `ai/AiLocalReads.kt` | ⛔ 别手改生成物（`--check` 会红） |
| AI 的**撤回**方案 | `ai/AiResources.kt`（改类 = 写回旧值 / 删除 = 恢复动作 / 成对） | ⛔ 别在处理器里自己实现撤回 |
| 后端**端点** | `backend/app/api/v1/<域>.py` + 在 `api/v1/router.py` 追加一行 `include_router` | ⛔ 别改既有端点的语义；改完重跑 `08A_ENDPOINT_INDEX.md` 生成器 |
| 一条**通知** | `backend/app/services/message_center.py` 里加一个 `publish_*` | ⛔ 别在业务代码里手拼通知体 |
| 新增**审计动作码** | `models/enums.py::OperationAction` + `ui/dispatcher/ReportCenter.kt::actionLabel` 补中文名（`_check_action_labels.py` 会红） | ⛔ 别让审计页显示原始码 |
| App 的**页面 / 模块入口** | `ui/nav/Modules.kt` 追加 `ModuleEntry`；路由在 `ui/nav/NavGraph.kt` | ⛔ 别改 `RoleHomeScreen` 的 Tab 结构 |
| 页面上共用的**控件** | `ui/common/Components.kt`（`SegmentedStatusTabs` / `DatePresetPill` + `DateFilterDialogs` / `SectionCard` / `OneShotSnackbar` / `EmptyView`…） | ⛔ 别在页面里再抄一遍（抄出来的那份迟早和共用那份走散） |
| 订单卡片上**多加一块** | `ui/common/OrderCard.kt` 的 `extra: @Composable RowScope.() -> Unit` 插槽 | ⛔ 别改卡片主体的信息结构（三种角色共用） |
| 一条**新的检查** | 放一个 `_tools/qa/_check_*.py`（`_check_all.py` 的清单**自己算**，不用登记）+ 配一份反向验证 | ⛔ 别写"永远绿"的检查（§15 的教训） |

## §4 判据与自检

```
python _tools/qa/_check_core_freeze.py                 # 核心冻结（39 项）
python _tools/qa/_reverse_verify_core_freeze.py        # 证明它真的会红（注入条数以它自己打印的为准）
python _tools/qa/_check_driver_money.py                # 司机端不显示金额（23 项，本轮新增）
python _tools/ai/_check_ai_guardrails.py               # AI 红线（含批量的那一节）
```

## §5 两个真实范例（本轮做的，可以照着抄）

**① 司机端不显示金额**（展示层口径变了，核心一格没动）
钱怎么算（`driver_pay.order_pay`）、后端发给司机什么（`order_response.apply_driver_view_gating`）
**一个字节都没改**；改的只是两个 Composable 里"画不画那个数"。
为什么后端门控不能一起删：它同时管着**完成流程**（按单计费的司机可以直接「完成订单」，
固定工资的司机要走「拍照送达」）—— 顺手删掉就是改流程，正是准则要防的那类"看起来只是显示问题"。
判据 `_check_driver_money.py` 把这条一并钉住了（第 4 项）。

**② AI 批量捷径**（给 AI 开的"批量 + 单个"两条路）
`ai/AiWriteBatch.kt` 是一个**装饰器**：`prepare` 收到 `items` 就逐条调用**既有处理器**，
把 N 条合成一张确认卡；`commit` 逐条执行、逐条如实汇报。
接线点只有一处（`AiWriteService` 里 `handlers` 建表后包一层），**50 个既有处理器一行都没改** ——
这就是"能调方法调方法"。

## §6 加功能时仍然要做的三件事（避免"能力白做"）

1. 后端新增**写端点** → 同时加 AI 动作，或在 `_tools/ai/_write_coverage.py` 的 `EXCLUDED` 里写一条理由；
2. App 新增**功能模块 / 读能力 / 写能力域** → `_tools/ai/_app_feature_coverage.py --check` 要过（能力得被某个模块认领）；
3. 新增**审计动作码** → `ui/dispatcher/ReportCenter.kt::actionLabel` 里补中文名。

（这三条与 [AGENTS.md](../AGENTS.md) 里那份"给 AI 开一个后路"是同一件事，细节见那儿。）
