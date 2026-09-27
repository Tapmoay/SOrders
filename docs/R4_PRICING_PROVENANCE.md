# R4-P1 · **计价事实审计**（Pricing Provenance）——「这个金额凭什么」

> 用户 2026-09-27 拍板：接线之前先回答一个问题 ——
> **一个订单最终使用的"计价规则版本"在哪里留下事实？**
>
> 原话：「我现在不应该凭空说你需要具体增加哪一列。应该先检查现有模型：
>  `Order` / `Ledger` / `Settlement` / `Driver bill`，看看**已有的数据是否足够记录
>  Pricing provenance**。」
>
> 判据：「**能重新计算 ≠ 能证明历史为什么是这个金额。**」

⛔ 这份文档是**审计结论**，不是施工计划。每一条都带 `文件:行号` 或一条可复现命令。

---

## §0 ⚠️ 更新（R4-11，2026-09-27）：缺口**已经补上了**

用户 2026-09-27 拍板「**① §6 做。**」并按 §五 拆成五条退出条件（P1-02a…e）。
R4-11 把**承运运费**那一路补完了。**本文档 §1–§6 保留审计当时的结论**（那是基线，
⛔ 不改写成"当时就已经有"），补完之后的形状见这一节与 §7。

| 审计时的结论（R4-09） | 现状（R4-11 之后） |
| --- | --- |
| 承运运费 ⚠️ 只记金额与分类，**不记是哪条价目** | ✅ `orders.freight_rule_snapshot`（同一行、同一事务、同一次定价决定）记着价目身份 |
| 计价契约版本 ⛔ 三处都没有 | ⚠️ **承运那一路有了**（快照里的 `pricing.contract`）；**司机应得那一路仍然没有** |
| 缺口 `orders.freight_fee` 在 `NO_PROVENANCE` 里 | ✅ 已挪进 `RULED`，`NO_PROVENANCE` **空了**（⛔ 空着是结论，不是漏了） |

**三条不变量**（写进代码注释与判据，不是写在这里就算）：
① 金额与凭据**同处写**（承运运费的唯一写入口 `order_money.record_freight_decision`，
判据扫全仓的 `.freight_fee =`）；② **同生共死**（`freight_fee is None` ⟺ 凭据为空）；
③ 每一次写金额 = **一次新的定价决定**（快照整份替换，改动历史在 `operation_logs`）。

⛔ **老数据不补**：R4-11 之前落库的单这一列留 NULL —— 拿今天的价目表倒推历史 = 伪造历史事实
（用户原话：「千万不要猜着补快照」）。判据名字就叫「迁移**不回填老数据**」。

---

## §1 一句话结论

| 钱路 | 事实记录 | 读法 |
| --- | --- | --- |
| **司机应得**（`driver_bills` / 司机结算） | ✅ **齐** | 派单那一刻把整份规则定格进 `orders.driver_rule_snapshot`；账单自己另存 `rule_id` / `rule_name` / `piece_amount` / `commission_amount`；**算钱那一步只认快照**（签名收的是 `PayRule`，不是活用户/活规则/DB 会话） |
| **承运运费**（`orders.freight_fee`） | ⚠️ **半** →（R4-11 补成 ✅，见 §0） | 审计当时只记了**金额**与**分类**（编号 + 名字快照），**没记是哪一条价目**；而价目可以被**就地改价** |
| **计价契约版本**（v1 / v2 / …） | ⛔ **没有** →（R4-11：承运那一路有了） | 全库没有任何一列、也没有生产快照写入器记录"这笔金额按**哪一版算法**算的" |

**所以：R4 的"扩展架构"要接进钱路，先要补第二、三条。** 这不是模块化问题，
是 **Money correctness prerequisite（资金正确性前置条件）**。

---

## §2 怎么查的（可复现）

    python _tools/qa/_check_pricing_provenance.py          # 详细（逐条打印）
    python _tools/qa/_check_pricing_provenance.py --check  # 一行结论
    python _tools/qa/_reverse_verify_pricing_provenance.py # 6 种破坏各自报红 + 还原后恢复

判据的形状（清单**自己算**，不手写）：遍历 SQLAlchemy mapper 的**全部 `Numeric` 列**，
逐个要求它出现在四张表里**恰好一次** ——
`CONFIG`（配置/入参）/ `SELF`（自描述：产生它的输入就在同一行）/
`RULED`（由规则算出来 → **必须有 provenance**）/ `NO_PROVENANCE`（缺口，有书面理由）。
坐标列由名字形状认出。

⭐ 这条的**真正价值**不在今天：**以后谁新增一个钱列而没归类，当场红**。
（本项目的老教训：一张手写的清单迟早和代码走散 —— 所以清单必须自己算。）

---

## §3 司机应得那一路：provenance 是**齐的**

| 判据 | 证据 |
| --- | --- |
| 订单上有那份定格规则 | `backend/app/models/order.py:83-85`（`driver_rule_snapshot`，Text/JSON） |
| 派单那一刻真的写了 | `backend/app/services/order_flow.py:183` —— `order.driver_rule_snapshot = rule_to_snapshot(rule)` |
| 快照**写的键 ⊇ 读的键** | `driver_pay.rule_to_snapshot`（12 个键）vs `rule_from_snapshot`（读 12 个）—— 判据比对两边**源码**，漏一个键当场红 |
| 算钱那一步拿不到活配置 | `order_pay(rule: PayRule \| None, *, …)`（`services/driver_pay.py:218-227`）—— 没有 db / session / user；`pay_for_order` 只经 `rule_from_snapshot(` 取规则 |
| 账单能独立复核 | `backend/app/models/driver_bill.py:40-43`：`rule_id` / `rule_name` / `piece_amount` / `commission_amount` |

**这一路可以直接接生产** —— 它已经满足"历史金额说得出凭什么"。

⚠️ 一处**如实记着**：`rule_to_snapshot` 里有 `piece_mode`（`uniform` / `category`）。
那是**规则形态**，不是**契约版本** —— 它选"按统一价还是按分类价"，不选"用哪一版算法"。
两件事不要混（见 §5）。

---

## §4 承运运费那一路：缺口的确切形状

### §4.1 缺什么

订单上关于这笔承运价只有三样东西（`backend/app/models/order.py:69-80`）：

| 列 | 是什么 |
| --- | --- |
| `freight_fee` | **金额本身** |
| `freight_category_id` | 这一类货的编号（用于算钱） |
| `freight_category` | 分类名的**快照**（分类改名后历史单还看得懂） |

⛔ **没有** `freight_templates.id` —— 也就是**这条价出自哪一条价目**。

### §4.2 为什么这是个真问题（不是"洁癖"）

价目**可以被就地改价**：手动定价那一路对已经存在的那条价目直接写
`backend/app/api/v1/orders_assignment.py:186` —— `existing.fee = body.freight_fee`。

于是订单 A 的形状是：

    订单 A 的 freight_fee = 120.00   ← 事实（金额在，永远在）
    它出自哪条价目？                  ← ⛔ 只有当时那一刻在内存里，落库时被丢掉了

**半年后没有任何办法回答"这 120.00 当时凭什么"**：价目可能已经被改成 135.00，
也可能已经被软删。金额本身不会错（**没有任何路径按活价目重算历史单**，见 §4.4），
但**复核**做不了 —— 有争议时拿不出那条价。

### §4.3 是"被丢掉了"，不是"根本不存在"

这一点决定了修法，所以单独说清：

| 事实 | 证据 |
| --- | --- |
| 匹配结果里**有**价目身份 | `services/freight_pricing.py:65` 的 `Candidate.template_id`；`:117` 构造时填它；`:236-240` 由 `quote_for` 返回 |
| 派单界面是**先问一次**再提交金额的 | `GET /freight-templates/quote`（`api/v1/freight_templates.py:473-491`）—— 只读端点，`quote_for` 里没有 `db.add` / `db.commit` |
| 提交时只带了金额与分类 | `api/v1/orders_assignment.py:145-147` —— 写 `freight_fee` / `freight_category_id` / `freight_category`，`template_id` 没用上 |

⇒ 缺口是**"这一格本来拿得到，落库时没写"**。修法是"多写一格"，
不是"重新设计一套匹配"。

### §4.4 这一条**不是**在说金额会算错（别把它读大）

已经查过：**没有任何路径按活价目重算历史单**。

- `quote_for` 只在报价端点上被调用（`api/v1/freight_templates.py:491`），**只读**；
- 全库 `FreightTemplate` 的消费点只有：报价、价目 CRUD、分类绑定、规则里"勾了哪些价目" ——
  没有一处拿它去改已落库的 `orders.freight_fee`；
- 手动定价那条路是**写一个新数**，不是重新推导。

所以 §4 这一条影响的是**可复核性**（拿不出凭据），**不是**已落库金额的正确性。
两件事必须分开说 —— 把它们混在一起，等于用一个不存在的事故去推动一次改动。

---

## §5 契约版本：⛔ 三处都没有

用户的问题原话是「当时采用的 Pricing Rule = v1」。查下来：

| 查的地方 | 结果 |
| --- | --- |
| 核心事实表的**列名**（扫 `pricing_kind` / `pricing_version` / `contract_version` / `rule_version` / `pricing_contract`） | **0 列** |
| 生产快照写入器 `rule_to_snapshot` | 不写版本号（只写 `piece_mode` 这种**规则形态**） |
| 账本 / 结算 / 账单 | 都不记版本 |

**为什么这一条对"接生产"是硬前置**：R4 已经证明 `PricingContract` **可以从 v1 升到 v2
而旧实现经适配器照常跑**（R4-07 演练，见 `docs/R4_CONTRACTS.md` §3.7）。
但那是在**测试里**证明的。一旦扩展真的开始给生产订单算钱，就会出现：

    订单 A（今天）    v1 算 → 120.00
    订单 A（半年后重算） v2 算 → 127.50

—— 而库里**没有任何一格**能把这两次区分开。这正是用户说的
「**历史事实就无法可靠重建**」。

---

## §6 补法（**建议**，不是已经做了）

最小形状是**照抄已经成立的那一套**（`driver_rule_snapshot` 的形状），不发明新机制：

1. `orders` 上加一列 `freight_rule_snapshot`（Text/JSON，可空 —— 空 = 老数据 / 手动定价）；
2. 在 `freight_fee` 的**三个写入点**（自动带价、手动定价、补录运费）同时写它，
   内容至少含：`template_id` / `template_name` / `price_name` / `fee` /
   `category_id` / `pricing_kind`（**这就是契约版本那一格**）；
3. 把 `orders.freight_fee` 从 `NO_PROVENANCE` 挪进 `RULED`。

⭐ 好处是**一份列同时兑现两件事**：① 历史复核拿得出凭据；② `pricing_kind` 让 R4-05 的
"**换数据就换算法**"从演练变成生产里真的成立（用户 §12 要的那条
`Order → PricingContext → PricingContract → implementation → Money`）。

⛔ 代价与边界（先写在前面，别到验收时才发现）：

- 它要动 `core/schema_bootstrap.py`（核心区，线上迁移唯一入口）+ `models/order.py`
  ⇒ 要走**证据触发的例外**，在声明页写那一行；
- 它**改的是钱的口径**，按 R4 的纪律属于"单独一轮 + 单独发布 + 单独演练"；
- 老数据那一段永远是空的 —— **不能假装补齐了**，出参要如实表达"老单没有这份凭据"。

---

## §7 补完之后的形状（R4-11）——**五条退出条件逐条对账**

用户 2026-09-27 给的 P1-02a…e，逐条落到可复现的出口：

| 退出条件 | 交付 | 出口（可复现） |
| --- | --- | --- |
| **P1-02a Schema** | `orders.freight_rule_snapshot TEXT NULL`（+ 迁移） | `backend/app/core/schema_bootstrap.py`；`python _tools/ops/_migration_tests.py --fresh --old --concurrent` |
| **P1-02b Write Atomicity** | 三个写入点**都**调同一个写入口（⛔ 全仓 `.freight_fee =` 只许出现在它里面） | 判据第 3 组；`backend/tests/test_freight_provenance.py` 三个写入点各一条用例 |
| **P1-02c Provenance Completeness** | 快照能恢复：来源 / 计价方式 / 契约身份与版本 / 计费上下文 / 当时的金额 / **哪一条价目** | 判据第 3 组**现场把写入口跑一遍**（⛔ 不是文本匹配）逐键核 |
| **P1-02d Legacy Safety** | 老单这一列 NULL：读得出来、改得动、⛔ **不回填** | 用例 `test_老单没有来源凭据也照常读照常改价`；判据「迁移**不回填老数据**」 |
| **P1-02e Reverse Verification** | 缺快照 / 金额与凭据错位 / 绕过写入口 / 来源改裸串 / 回填老数据 —— 五种破坏各自报红 | `python _tools/qa/_reverse_verify_pricing_provenance.py` |

### 快照长什么样（一份真的）

    {
      "v": 1,
      "at": "2026-09-27T01:12:34",
      "source": "manual",                          ← 这一次运费怎么产生的
      "fee": "135.00",                             ← 当时的金额（必须等于 orders.freight_fee）
      "category": {"id": 3, "name": "蔬菜"},        ← 按哪一类货算的
      "rule": {                                     ← 哪一条价目（空 = 没有价目来源）
        "template_id": 12, "template_name": "…", "price_name": "小车价",
        "route": "A → B",
        "fee": "135.00",                           ← **价目当时**的金额（价目改价之后才对得上）
        "origin": "saved"                          ← saved = 这次真的写/改了一条价目
      },                                            ←   derived = 服务端按同一算法复算出来的
      "pricing": {
        "kind": "freight_template",                 ← 用了什么计价方式
        "contract": {"name": "FreightPricingCore", "version": 1}   ← 属于哪一版计价契约
      }
    }

⚠️ **两条边界，别读大**：

1. 生产今天跑的**不是** PricingContract 扩展（那是 R4 的演练产物），而是核心的**价目匹配**。
   所以 `kind` / `contract` 如实写 `freight_template` / `FreightPricingCore v1` ——
   ⛔ 编一个 "PricingContract v1" 写上去就是**记假事实**。扩展真的接上生产钱路时（R4-P2），
   这两个值必须**一起**改：那正是它们存在的意义。
2. `rule.origin="derived"` 说的是"**服务端在那一刻按同一个匹配算法复算出来的结论**"
   （`services/freight_pricing.quote_for` 是唯一的匹配实现，派单弹窗上那个价也是它算的）——
   不是"猜"。而且它是 **best-effort**：复算失败只会让 `rule` 记成 `null`，
   ⛔ 绝不让派单失败（审计字段不该变成钱路上的单点故障）。

---

## §8 ⛔ 本审计**证不了**什么

1. **没有查金额对不对**：本判据只回答"凭什么"，不回答"算得对不对"。
   后者是另一条线（`_check_freight_pricing.py` / `_check_money_contract.py` / 后端用例）。
2. **没有验证生产库**：全部结论来自**代码与数据模型**，没有连生产库取一行真数据核对。
3. **没有替用户拍板**"承运价该不该记价目身份"这个产品决策 —— 本审计只把现状说清：
   **现在没有，而它在派单那一刻是拿得到的。**
4. **票据类金额没有历史**：`expenses` / `cash_flows` / `shipper_receipts` 记的是
   "人录进来的数"，值即事实；⛔ 但它们**改之前长什么样**没有历史表 —— 那属于审计日志的范畴，
   本审计没碰。
