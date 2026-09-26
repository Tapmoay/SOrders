# R4 扩展契约（Contract Design）

> **R4-02 的产物**。依据 R4 指南 §7（不要万能插件接口）、§8–§11（四类扩展契约）、
> §17–§18（兼容性设计，以及紧跟着的那一脚刹车）、§35（六个要素）。
> **代码形态**：[backend/app/core/contracts/](../backend/app/core/contracts/)（核心侧，⛔ 一行实现都没有）。
> **这一轮不改业务代码**：契约只是把「核心答应扩展什么」写清楚，实现留到 R4-04 / R4-05。

---

## 0. 为什么是「多种契约」而不是「一个插件基类」

指南 §7 原话：

> 千万不要设计一个「万能插件接口」，例如 `Plugin.initialize() / execute() / shutdown()`，
> 然后所有东西都往里面塞。因为 UnitConversion / Pricing / AI Provider / Excel Exporter /
> Notification —— 这些东西**根本不是同一种能力**。

所以 R4 设计的是**多种稳定扩展契约**，一种能力一个模块、一个显式版本。
判据 `_check_extension_contracts.py` 会在契约包与扩展树里扫 `class Plugin` /
`initialize(self)` / `execute(self)` / `shutdown(self)` —— 出现任何一个就报红。

## 1. 四类扩展契约（指南 §8–§11），本轮做到哪一步

| 类 | 适合什么 | 本项目的契约 | 本轮状态 |
| --- | --- | --- | --- |
| 一 · Pure Function | 单位换算、税率、数学、格式转换、纯规则 | `UnitConversionContract v1` | ✅ 本轮定义（R4-02）+ 实现（R4-04） |
| 二 · Policy | 定价、折扣、运费、税费、佣金、特殊业务规则 | `PricingContract v1` | ✅ 本轮定义（R4-02）+ 实现（R4-05） |
| 三 · Provider | AI、短信、邮件、推送、对象存储、第三方地图 | `NotificationDeliveryContract` / `AiProviderContract` / `ExternalIntegrationContract` | ⏸ **只登记在边界图上**，没有第二个实现 |
| 四 · Presentation / Format | Excel、PDF、CSV、特殊报表 | `ReportRenderContract` / `ExportContract` | ⏸ 同上 |

⛔ **第三、四类故意不写契约**：指南 §18 的原话是「先证明**这个契约真的会被多个实现使用**，
再为它设计长期版本兼容」。现在它们各只有一个实现，写了就是过度设计（§31 坑 6）。
它们的**位置**登记在 [R4_CORE_EXTENSION_MAP.md](R4_CORE_EXTENSION_MAP.md) §4.1，
那一天到来时从那里开始。

一条贯穿全部四类的线（指南 §6）：**「计算」可以扩展，「事实」不能扩展。**

---

## 2. UnitConversionContract v1

**核心侧**：[core/contracts/unit_conversion.py](../backend/app/core/contracts/unit_conversion.py)、
[core/contracts/quantity.py](../backend/app/core/contracts/quantity.py)（Quantity / Unit / Dimension）。
**扩展侧**：具体换算（kg 到 g、lb 到 kg、斤 到 kg）。

### 2.1 输入

```python
ConversionRequest(value: Decimal, from_unit: str, to_unit: str)
```

- **只有这三个字段**。⛔ 刻意不带 Session / db / 用户 / 当前时间 ——
  换算是**纯函数**：同样的输入必须给同样的输出，否则「同一批货两个数」就没人能复核。
- `value` 是 `Decimal`（⛔ 不是 float：二进制浮点在 0.1 上就不精确）。
- 单位名是**字符串**，核心不认识任何具体单位 ——⛔ 核心里没有单位名册、没有换算率表。

### 2.2 输出

```python
ConversionResult(quantity: Quantity, factor: Decimal, exact: bool, source: str, note: str = "")
```

- ⛔ **输出必须带核心的 Quantity**（判据在 AST 层核对 `ConversionResult.quantity` 的注解就是 `Quantity`）。
  扩展**不许**返回自己的对象 —— 那正是「核心反过来认识具体实现」的第一步。
- `exact=False` 表示发生过四舍五入 —— 界面要能说出「约」这个字。
- `source` 是**给人看的理由**（哪个实现算的）。⛔ 核心**不许**拿它做分支。

### 2.3 错误

| 情况 | `supports` | 行为 |
| --- | --- | --- |
| **不是我的活**（这个实现不认识其中某个单位） | `False` | 返回 `None` —— 由调用方去问下一个实现 |
| **这次换算不合法**（同单位、量纲冲突） | `True` | 抛 `UnitConversionError`，消息是**一句能照着改的中文** |

⭐ **中间那一格是 R4-04 实测定下来的**（写进契约，免得第二个实现重新想一遍）：
「归我管」与「这次换算合法」是两件事。第一版把量纲冲突也算成"不支持"，
后果是用户问「cm 到 g」时拿到「没有实现认得这对单位」——
而真正该说的是「一个是长度、一个是质量，不能换算」。**错误消息的质量就是这一格的价值。**

把这两件事分开是**多实现并存的前提**：混在一起，第二个实现就没法与第一个共存了。
错误消息的形状沿用项目既有口径（后端抛的中文会被 App 原样显示，见 `core/validation_errors.py`）。

### 2.4 不变量

1. **量纲相同的量才允许换算**；`unknown` 量纲**之间也不允许**
   （那正是「10 车约等于 50 袋」这类静默错误的来源）；
2. **没有唯一答案时不许猜**：同一个源单位有两条换算 / 反向对并存就拒绝，不是任选一条
   （与既有 `services/unit_conversion.py` 的四条规则同源）；
3. **`factor` 与 `quantity` 必须自洽**：`to.value = from.value × factor`（在 `exact` 的精度内）；
4. 换算**不参与钱**：⛔ 实现里不许出现价格 / 金额 —— 2026-09-24 的红线
   `_check_unit_conversion.py` 第 4 层已经钉着这一条。

### 2.5 兼容要求

- 版本号在模块里只有一处：`CONTRACT_VERSION = 1`；
- **加字段**给默认值即可，⛔ **不许删字段、不许改字段语义**；
- 需要改语义时**加 v2**，v1 的实现继续可用（指南 §17），
  但版本数上限 3（§31 坑 13：不许为了兼容保留 10 代接口，判据核）；
- 扩展只需声明 `name` / `version` 两个属性 + 两个方法 —— **没有基类、没有注册装饰器**。

### 2.6 生命周期

| 阶段 | 契约要求 |
| --- | --- |
| **安装** | 实现放进 `backend/app/extensions/`，在 manifest 里声明 `provides: unit.convert` |
| **运行** | 纯函数，无状态；同一个请求调两次结果必须相同 |
| **停用** | 从注册表摘掉即可 —— ⛔ 不需要 `shutdown()`（它没有要释放的资源） |
| **卸载** | 删代码 + 删 manifest 条目；**它自己的运营数据**（换算率）按 R4-06 的 Remove Drill 处理 |
| **历史** | ⚠️ 已经落进订单的数量与快照**不因扩展被删而消失**（指南 §24：Disable / Uninstall / Code Removal / Data Removal 是四件事） |

---

## 3. PricingContract v1

**核心侧**：[core/contracts/pricing.py](../backend/app/core/contracts/pricing.py)、
[core/contracts/money.py](../backend/app/core/contracts/money.py)（Money / Currency / Rounding）。
**扩展侧**：PricingAlgorithm（基础运费、重量附加费、偏远费、冷链路、促销……）。

指南 §20 的链子：

```text
Order -> PricingContext -> PricingContract -> Money -> Core Settlement / Ledger
```

### 3.1 输入

```python
PricingContext(order_id, order_no, category, from_place, to_place,
               quantity: Quantity | None, unit_price: Decimal | None,
               driver_id, vehicle_type, rule_snapshot: Mapping[str, Any])
```

- ⛔ **这里没有 Session / db / 用户身份**。拿得到 db 就能改写事实；
  「扩展不许写核心表」这条边界，靠**根本不给它写的能力**来守，比靠判据守更硬。
- `rule_snapshot` 是派单时**定格**进订单的规则快照（指南 §25 的 C 类数据：历史投影），
  构造时被包成 `MappingProxyType` —— 扩展算价时顺手改快照就等于改历史，契约层面堵死。
- `quantity` 带单位与量纲，所以它合法地跨得进扩展（Quantity 是核心类型）。

### 3.2 输出

```python
PricingResult(money: Money, rule_name: str, detail: str = "", candidates: tuple[str, ...] = ())
```

- ⛔ **只接受核心的 Money** —— 指南 §20 原话「不能接受某个插件自己的对象」，
  判据在 AST 层核对 `PricingResult.money` 的注解就是 `Money`；
- `rule_name` / `detail` 是给人和审计看的：账单要能**独立复核「按什么算的」**
  （与 `driver_bills` 另存 `rule_id` / `rule_name` / `piece_amount` 是同一条口径）；
- ⛔ 不许返回裸 `Decimal`、不许返回 `None`、不许返回自定义对象。

### 3.3 错误

| 情况 | 异常 | 含义 |
| --- | --- | --- |
| 一条都匹配不上 | `NoPricingRule` | **不是系统错误** —— 既有口径是「没匹配到就没有定价，由派单员手动定价」 |
| 同一档匹配到多条 | `AmbiguousPricingRule`（带 `candidates`） | **不猜**，把候选交出去让人挑 |
| 上下文本身说不通 | `PricingError` | 一句能照着改的中文 |

第二条与既有 `services/freight_pricing.py` 的「同一档里多于一条 = 不猜」是**同一条规矩**，
这一次它从「一处实现」升级成「契约要求每个实现都遵守」。

### 3.4 不变量

1. **⛔ 扩展不许写账本**：只能 calculate 出 Money，最终事实交给核心事务
   （指南 §14 / §31 坑 5：「calculate 完直接 UPDATE ledger」是最高危的一类）；
2. **金额一律两位小数 + ROUND_HALF_UP**，且必须用 `Money` 构造（构造时就归一）；
3. **同一档多条就不猜**（见上）；
4. **给定同一份快照与上下文，结果必须一样** —— 所以规则必须**快照进订单**，
   而不是算价时现查配置；
5. **历史可解释**：删除扩展之后，历史账单仍要解释得通（靠快照，不靠扩展现算）。

### 3.5 兼容要求

- `CONTRACT_VERSION = 1`，模块级唯一一处；
- 加字段给默认值，⛔ 不许删字段、不许改语义；改语义加 v2（v1 实现继续可用）；
- 版本数上限 3（判据核）；
- **两种实现必须能被同一组契约用例跑过** —— 这是 R4-05 的 Replace 演练要证明的事；
- ⛔ 契约**不承诺**「哪个实现被选中」：那是**注册表**的事，不是契约的事
  （§29 的依赖图要能回答它）。

### 3.6 生命周期

| 阶段 | 契约要求 |
| --- | --- |
| **安装** | 实现放进 `backend/app/extensions/`，manifest 声明 `provides: pricing.calculate` 与 `owns_tables` |
| **运行** | 无状态纯计算；⛔ 不许在算价时写任何表 |
| **替换** | 换一个实现，核心**一行不改**（R4-05 的 Replace 演练，出口是「Core 修改数 = 0」） |
| **停用** | 摘掉注册；**已经有账单的订单不受影响**（钱的事实已经在库里） |
| **卸载** | 删代码 + 删 manifest。⚠️ **它拥有的运营数据（价目 / 规则）与它创造的历史事实（账单）是两回事**：前者可随模块生命周期处理，后者**不可**（指南 §24 / §25） |

### 3.7 v2：只加一个方法（R4-07）

⚠️ **顺序本身就是指南的一部分**：§18 说「先证明这个契约真的会被多个实现使用，
再为它设计长期版本兼容」。所以 v2 不是在 R4-02 设计 v1 时一起设计的 ——
是到 R4-05 已经有两个实现之后才加的，而且**只加一个方法**。

```text
PricingContract v1   = name / version / applies_to / price
PricingContract v2   = v1 的全部 + breakdown() -> tuple[PricingLine, ...]
```

| 关注点 | v1 实现 | v2 实现 |
| --- | --- | --- |
| 出总额 | ✅ `price()` | ✅ `price()` |
| 出明细 | ❌ 给不出 | ✅ `breakdown()`（多行原生） |
| 经 `as_v2()` 适配器之后 | ✅ 可当 v2 用（明细**合成一行**，并如实标着 `synthesized_breakdown`） | ✅ 原样返回 |
| 还能当 v1 用吗 | ✅ | ✅（**v2 是 v1 的超集，不是另一个协议世界**） |

**不变式**：明细各行金额之和**必须等于** `price()` 的总额，由 `_check_extension_contracts.py`
与契约用例双核 —— 否则"明细"就成了第二份真相，而两份真相迟早对不上。

⛔ **没做的事**：没有 v3、没有 compatibility matrix、没有为"任何旧实现"都写适配器 ——
只为**真实存在的**旧实现提供兼容层（§31 坑 13）。版本数上限 3，由边界图判据盯着。

---

## 4. 顺手做实的一件事：把一条跨十几个文件的口头约定变成一处定义

指南说「核心拥有 Money / Currency / **Rounding**」。而本轮开工时实测：
**Rounding 并不是被某处「拥有」的** —— 它是 `quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)`
这一串在 `backend/app` 里被抄了十几遍的**约定**，靠注释互相提醒
（`accounting_service.py:281` 那段注释写的就是「别用默认的 ROUND_HALF_EVEN，半分上差一分钱」）。

本轮**不迁移**那十几处（迁移等于动核心区十几个文件，与应用本轮的「Core 修改数 = 0」直接冲突，
也正是指南 §44 警告的那种大重构）。改的是另一件事：

> 现在 `contracts/money.py` 把 `QUANTUM` 与 `ROUNDING` **定义一次**，
> 判据 `_check_extension_contracts.py` 用 AST 把全项目每一处 `quantize` 调用抠出来，
> 逐条核对：① 显式写了 `rounding=`；② 两位小数那一档就是 `ROUND_HALF_UP`。

于是这条约定从「靠记性守」变成「机器每次全量检查都核一遍」。
实测口径：**扫到 14 处 quantize，全部显式写了 `rounding=`，两位小数那一档全部是 `ROUND_HALF_UP`**。
⛔ 它**不是**第二份「钱怎么算」的实现 —— `money.py` 一行业务金额都不算、
不知道什么叫应收 / 欠款 / 司机运费（那些仍然只有 `order_money` / `driver_pay` 等处一处实现）。

---

## 5. 这一轮**没有**做的事（如实列着）

| 没做 | 为什么 | 什么时候该做 |
| --- | --- | --- |
| Provider / Format 两类契约 | 各自只有一个实现；指南 §18 明说「先证明契约会被多个实现使用」 | 真出现第二个通知渠道 / 第二种报表格式时 |
| 版本兼容层（v1 到 v2 的 adapter） | 指南 §18 明确「不要一开始就搞 v1/v2/v3 + compatibility matrix」 | R4-07 的 Compatibility Drill 会先证明它用得上 |
| 把既有的十几处 `quantize` 迁到 `Money` | 那会动核心区十几个文件 —— 与本轮的「Core 修改数 = 0」冲突 | 单独一轮，且要有证据触发（参照 `CORE_AND_EXTENSION.md` §2.1 的例外三条件） |
| 契约的**运行期**校验（谁能调用、注册表如何选实现） | 那是注册表的事，不是契约的事 | R4-03 的 manifest + R4-04/05 的演练 |

---

## 6. 判据

```text
python _tools/qa/_check_extension_contracts.py                     # 八组判据（含全项目 quantize 口径对账）
cd backend; python -m pytest tests/test_extension_contracts.py -q   # 契约本身的 16 条单测
python _tools/qa/_reverse_verify_r4_all.py                         # 反向破坏用例（把每条判据弄坏一次）
```

判据**自己算**的部分（⛔ 不是从这一页抄的）：契约名与版本号来自模块级常量（AST 取值）、
输出类型来自注解（AST）、`quantize` 调用来自 AST 遍历、扩展偷偷 import 也来自 AST 的 import 节点。

