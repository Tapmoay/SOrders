# 外部参考笔记（不属于本仓库，也不参与文档校验）

这里放的是**对另一个仓库的代码考古笔记**，不是 SOrders 的现状文档。

| 文件 | 内容 | 基线 |
|---|---|---|
| [ai-vertical-agent-plan.md](ai-vertical-agent-plan.md) | 更早的一版「AI 能力方案」：垂直工具型 Agent + 长期记忆。⚠️ 其中的基线（127 端点 / 30 文件）已过时 | 本仓 2026-09 中旬 |
| [ref-operit-ai-engine.md](ref-operit-ai-engine.md) | Operit 对话引擎运行时机制：一次对话怎么跑、上下文怎么装、工具怎么调、多厂商怎么抹平 | 外部仓 `D:\AProjects\ASDH\_refs\Operit` HEAD `b2c7610` |
| [ref-operit-memory.md](ref-operit-memory.md) | Operit 长期记忆系统：记忆怎么存、怎么检索打分、怎么让 AI 决定写什么 | 同上 |
| [ref-operit-tools.md](ref-operit-tools.md) | Operit 工具（Tool）体系考古 | 同上 |
| [ref-operit-ui-ia.md](ref-operit-ui-ia.md) | Operit 的 UI 信息架构，重点在**设置界面与记忆界面** | 同上 |

## 为什么放在这里，而不是 `docs/`

这 5 份里的文件引用（`ToolRegistration.kt`、`data/model/ModelConfigData.kt` …）
**只存在于上面那个外部 checkout，本仓库里没有、也不该有**。

放在 `docs/` 下会造成两个自相矛盾的结果：

- `backend/scripts/check_refs.py` 会扫到它们，报出 40+ 条永远修不好的"失效引用"——
  这种假红看久了，真出问题时也会被忽略；
- `backend/scripts/check_reachability.py` 又要求它们必须从入口可达。

**"这些引用不该按本仓校验"是一个事实**，所以把它们移出被校验的 `docs/` 树，
由 [docs/PROJECT_MAP/INDEX.md](../../../docs/PROJECT_MAP/INDEX.md) 明确指路。

> 读之前先假设状态描述是错的：它们是**当时**的调研结论，不是 SOrders 的现状。
> 要了解 SOrders 当前怎么做，看 `docs/PROJECT_MAP/` 与 `docs/AI_ASSISTANT_PLAN_V3.md`。

## 如果外部 checkout 没了

`D:\AProjects\ASDH\_refs\Operit` 一旦被删，上面的行号与路径就都无法复核了。
那时这些笔记的价值只剩"当时为什么这么设计"——**结论本身要重新验证**。
