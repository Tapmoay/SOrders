# 钱的依赖图（MONEY_DEPENDENCY_GRAPH）

> **第二轮整改 R2-03 的产物**。依据：方向指南（[ARCHITECTURE_RECTIFICATION_R2.md](ARCHITECTURE_RECTIFICATION_R2.md)）第五节
> 「把钱契约从统一入口升级成**统一依赖方向**」。

---

## 0. 指南说得很直白

> 第二轮真正要做的是：**验证依赖图**，而不是继续增加钱的接口。
>
> 也就是说：**不要继续为了形式去建立三个 Calculator 类**。

第一轮已经把「钱只有一处实现」做成了机器判据（[`_check_money_contract.py`](../_tools/qa/_check_money_contract.py)：
5 个钱数 / 15 个转出符号 / 逐条核对实现站点与消费方）。本轮补的是**方向**：

```text
  ✅ 目标形状
  Reports ─┐
  Ledger ──┤
  Settlement ─┤──▶  money_contract  ──▶  Money implementation
  AI ──────┤
  Order ───┘

  ⛔ 禁止的形状
  A → money_contract → B;   B → accounting → C;   C → order_money → A     （环）
```

---

## 1. 三层（判据按这三层判）

### 口径层（TIER 0）—— **纯算术**，不落库、不改状态、不认识 HTTP

| 模块 | 它是什么 |
|---|---|
| `services/order_money.py` | 一张单的四个钱（应收 / 已收 / 已退现 / 欠款） |
| `services/money_text.py` | 金额显示口径（去尾零） |
| `services/driver_pay.py` | 司机应得（工资 + 计件 + 提成三件可任意组合） |
| `services/shipper_settle.py` | 货主核销的上限与剩余 |
| `services/cost_basis.py` | 成本口径（货损与毛利的原料） |

**只许 import 三样**：标准库/三方、`app.models.*`、`app.core.*`，以及**本层**。
（实测：五个模块一共只有 17 条内部依赖，全部落在这三样里。）

### 落库层（TIER 1）—— 会写库 / 会改状态，因此**允许**依赖订单域与别的领域服务

| 模块 | 它是什么 |
|---|---|
| `services/accounting_service.py` | 账本入账、应付明细、结算单、开销单 |
| `services/order_return.py` | 退货红冲与退现 |
| `services/ledger_sync.py` | 送达 → 账本的同步 |
| `services/supplier_service.py` | 供应商应付与付款 |
| `services/ledger_scope.py` / `ledger_response.py` | 账本的可见范围与出参口径 |

**⛔ 一条** `app.api.*` **都不许有**，`REPORTING` 那三个模块（报表 / 统计 / 导出）也不许有。

### 契约（唯一的转出口）

[`services/money_contract.py`](..//backend/app/services/money_contract.py)：15 个符号**惰性转出**
（PEP 562 的模块级 `__getattr__`，因为 `order_return ↔ order_flow` 是环，顶端 eager import 当场成环）。

⛔ 它自己**一行算术都没有**（第一轮就钉着）；本轮再加一条：**转出的目标必须是钱模块** ——
指到别处就等于`契约变成了别人的门面`。

**⚠️ 契约是转发器，不是新的实现点。** 事务判据会把转发**解开**到真正的实现上：
`api/v1/orders_return.py` 写的是 `from app.services.money_contract import return_order`（这正是指南要的形状），
调用图会把这条边落到 `order_return.py:return_order` 上 —— 实测 **32 处**调用是这样解开的。
换句话说：**依赖指向契约，而执行落在实现**，这件事现在有机器证据。

---

## 2. 本轮改掉的一处**方向倒置**

判据第一次跑起来就抓到了一条真的违规：

```text
  accounting_service.py（钱的落库层） ──import──▶ app.api.v1.expense_categories（HTTP 路由）
```

它原来长这样：

```python
    # accounting_service.create_expense 里
    from app.api.v1.expense_categories import ensure_category
```

「新建开销时，分类名不在名册里就自动补进去」是**业务规则**，不是 HTTP 的事。
指南 §十七.3 的判据在这里正好用得上：**能不能通过改变依赖方向解决，而不是增加一个检查器？**
能 —— 于是把 `ensure_category` 搬进了新的
[`services/expense_category_service.py`](../backend/app/services/expense_category_service.py)，
路由反过来从服务层 import 它。

⛔ 口径一个字没改（函数体原样搬）；搬完 `_check_money_dependency.py` 的
「任何模块都不许反向 import 路由」这条**0 例外**的规则才立得住。

---

## 3. 判据

```text
python _tools/qa/_check_money_dependency.py            # 八条：方向 / 分层 / 契约 / 名单 / 反空转
python _tools/qa/_reverse_verify_money_dependency.py   # 反向验证 9/9
```

它跑的是 **AST import 图**（含**函数体内的惰性 import** —— 反向 import 路由那一处恰恰就是函数内 import，
按行正则扫会漏掉）。实测：202 个模块 / 1049 条内部依赖 / 钱模块 12 个 / **例外 0 条**。

### 例外表现在是空的 —— 这是结论，不是偷懒

判据里有一张 `ALLOWED` 表。它现在是空的，意思是「上述规则**确实一条例外都没有**」。
表一旦非空，判据会逐条核对：理由 ≥20 字、必须写「什么时候删掉这一条」、而且**必须仍然命中**
（不命中＝化石，报红）。这与第一轮给证书例外、Scope 例外定的那三条纪律同源。

---

## 4. 这一页**没有**解决的事

| 没做的 | 为什么 | 什么时候该做 |
|---|---|---|
| `services/order_return.py` 反过来 import `order_flow.mark_returned`（环） | 这是**故意的**：退货要把整单退完的单置成 RETURNED，而那件事只有状态机一个入口能做。真正的解法是让订单域**发出**一个「整单退完」的事实、由状态机去消费它 —— 那是 R2-04 发件箱该长出来的形状 | 事件边界那条线（R2-04）之后重新评估 |
| 只画了模块级依赖，没有画`谁在运行期调了谁` | 静态 import 图证明的是**方向**；运行期的调用链在 [BUSINESS_TRANSACTION_MAP.md](BUSINESS_TRANSACTION_MAP.md) 里按 AST 调用图核 | 已做（R2-03 第二半） |
| 报表层只被要求「不许被钱依赖」，没要求「它自己不许依赖写服务」 | 那是 R2-05（报表只读边界）的事，分开做、各自配判据 | R2-05 |
