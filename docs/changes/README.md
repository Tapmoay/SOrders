# 开发事项登记簿（docs/changes/）

> **这一页是什么**：SOrders 的**开发事项台账**。一个事项 = 一个文件 = 一个 ID。
> 规则出自 [`DEVELOPMENT_SPEC.md`](../DEVELOPMENT_SPEC.md) §一（四种身份）与 §七（F0 模板）。
>
> **谁该读它**：动手之前。找不到自己的事项号，说明**还没立项**。

---

## 1. 四种 ID

| 前缀 | 含义 | 一句话判据 | 起始号 |
| --- | --- | --- | --- |
| `FEAT-xxxx` | 新功能 | 原来**没有**，现在增加 | `FEAT-0001` |
| `CHG-xxxx` | 既有功能**修改** | 原来**已经存在**，现在改变行为 | `CHG-0001` |
| `BUG-xxxx` | 缺陷修复 | 现在的行为**不符合**已声明的行为 | `BUG-0001` |
| `GOV-xxxx` | 开发治理 / 架构治理变化 | 改的是**规则本身**（文档、判据、清单） | `GOV-0001` |

**编号规则**（细则见规范 §1.2）：

- 每类 **4 位**，**独立自增**；**永不复用、永不回收**。
- 一个号销掉（取消 / 合并）→ 留一条记录写明「已取消，去向 xxxx」，⛔ 不许把号让给别人。
- **目录里的文件名就是台账**：⛔ 没有第二份手写清单（下面那张表是给人看的索引，
  `_check_dev_spec.py` 会核对它**是否漏条目**，所以它不可能悄悄过期）。

---

## 2. 怎么开一个新事项（四步）

```text
1. 复制 _TEMPLATE.md  →  <ID>.md
2. 填「六问」与「Must Change / Must Not Change」        ← 规范 §二
3. 填「Boundary」（Core / Extension / Infrastructure / Presentation）  ← 规范 §三、§F1
4. 在 docs/AI_WORK_CLAIM.md 的「## 进行中」写一行，**首行带 ID**
```

⛔ **第 4 步不是可选的**：多会话协作下，没声明的改动会和别人的改动互相覆盖。

**CHG 还要多做两块**：`Before / After` 与 `Must Preserve / Blast Radius`（规范 §十三、§二十六）。

**收尾**：把「六格」补齐（`Changed / Preserved / Evidence / Known Limitations / Rollback / Historical Data Impact`），
再把这一页的表加一行。

---

## 3. 现有事项

| ID | 类型 | 一句话 | 状态 | 文件 |
| --- | --- | --- | --- | --- |
| `GOV-0001` | GOV | 把《新功能开发与既有功能修改规范 v1.0》写进仓库，并接线到开工入口 | ✅ 已关闭 | [GOV-0001.md](GOV-0001.md) |
| `FEAT-0001` | FEAT | 换算率可以绑定到某辆车（L3：动 schema_bootstrap 加一列） | 🔧 进行中 | [FEAT-0001.md](FEAT-0001.md) |
| `FEAT-0002` | FEAT | 共享地点按距离分档排序（L1，只排序不合并） | 🔧 进行中 | [FEAT-0002.md](FEAT-0002.md) |
| `FEAT-0003` | FEAT | 下单选地点时加一个「我就在这里」按钮（L1） | 🔧 进行中 | [FEAT-0003.md](FEAT-0003.md) |

> ⛔ 这张表**必须**与目录里的文件一一对应 —— `python _tools/qa/_check_dev_spec.py` 会两边对账：
> 有文件没登记 → 红；登记了但文件不在 → 红。

---

## 4. 判据

```
python _tools/qa/_check_dev_spec.py      # 事项登记：文件名 ↔ 内文 ID ↔ 本页表，三处一致
```

模板与必填小节：[`_TEMPLATE.md`](_TEMPLATE.md)。
