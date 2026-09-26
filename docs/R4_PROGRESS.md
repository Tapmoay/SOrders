# R4 第四轮整改进度与退出条件台账

> **规则**：这份文件是「已完成」三个字的唯一出处。⛔ **没达到退出条件的里程碑就是没完成**，
> 不许用「已经差不多了」。
> **冻结基线**：`c67b2cf`（R3 的收口提交）｜**指南**：`C:\Users\Optimistic\Desktop\ppkk.md`
> → 已归档 [ARCHITECTURE_RECTIFICATION_R4.md](ARCHITECTURE_RECTIFICATION_R4.md)
> （**逐字节原文**：26669 字节 / 1599 行 / SHA256 `E45A6CAF01143418BDB5F20D36401382456754C267367424B3FAE91D9DA230E0`；
> 核它对不对：`git show HEAD:docs/ARCHITECTURE_RECTIFICATION_R4.md > /tmp/g.md; python -c "import hashlib;print(hashlib.sha256(open('/tmp/g.md','rb').read()).hexdigest().upper())"`）
> **基线快照**（机器采集，⛔ 不是手写）：`_tools/baseline/r4-before/2026-09-27/baseline.json` +
> [R4_BASELINE.md](R4_BASELINE.md)
> **事实优先**：每一行的 `复现：` 后面必须是**真能跑**的命令；跑不通就是 ❌，不许写 ✅。

---

## 冻结基线（R4-00，2026-09-27）

| 项 | 值 | 来源 |
| --- | --- | --- |
| 提交 | `c67b2cfea27c01f184c05f6fba60120c768d6851` | `git rev-parse HEAD` |
| 分支 | `p`（跟踪 `origin/new`，= `c67b2cf`） | `git branch -vv` |
| R3 报告 | v2.6 | `docs/RECTIFICATION_REPORT_R3.md` |
| R3 台账 | 60 ✅ / 0 ❌ | `docs/R3_PROGRESS.md` |
| 静态检查 | 119/119 通过（总耗时 194.2 秒） | `python _tools/qa/_check_all.py` |
| 后端用例 | 1020 | `python _tools/baseline/_capture_baseline.py --tests` |
| 生产 | Production Runtime 10/10（跑过 ✅ + 五个故障演练 5/5 ✅） | `docs/R3_PROGRESS.md` 三层矩阵 |
| 端点 | 229（其中写端点见端点索引） | `docs/R4_BASELINE.md` |

> ⚠️ 基线里有一条**不是 R4 造成的**既存观察，如实记着：安卓最近一次单测报告 `failures=1`
> （`docs/R4_BASELINE.md` 的风险判定第 2 条）。R4 是后端/架构轮，⛔ 不要把这条算到 R4 头上，
> 也不要因为"反正不是我弄的"就把它从基线里抹掉。

---

## R4-00 冻结基线

- ✅ 基线记录落地（提交 / 检查数 / 用例数 / 生产 10-10 全部进上表，数字由工具采、⛔ 不手写）—— 复现：`python _tools/baseline/_capture_baseline.py --tests --label r4-before --out docs/R4_BASELINE.md`
- ✅ `backend/app/core/socket_io.py` **正式加入核心区清单**，并被骨架判据钉住（删条目即报红）—— 复现：`python _tools/qa/_check_core_freeze.py`
- ✅ 「核心区**不是永久冻结**，只经受证据触发的例外修改」写进 `_tools/qa/_core_files.txt` 文件头与 `docs/CORE_AND_EXTENSION.md` §2.1（三条件：有证据 / 只治那个病 / 写下来）—— 复现：`python _tools/qa/_check_core_freeze.py`
- ✅ R3 棘轮窗口跟着 R3 一起收口（右端点写进 `docs/R3_CONSTRAINTS.md`），R4 的改动不再消耗 R3 的额度 —— 复现：`python _tools/qa/_check_r3_constraints.py`
- ✅ 指南原文归档为 `docs/ARCHITECTURE_RECTIFICATION_R4.md`（带来源 SHA256），北极星那一句同页可查 —— 复现：`python _tools/qa/_check_r4_constraints.py`

---

## R4-01 Core / Extension Boundary Map（先划边界，⛔ 不改代码）

**交付**：`docs/R4_CORE_EXTENSION_MAP.md` —— 把系统能力逐项归类为
**CORE / EXTENSION POINT / EXTENSION IMPLEMENTATION / INFRASTRUCTURE**，并给每项写「为什么是这一档」。

**判定规则**（指南 §4，四条）：
1. 它是否**定义系统事实**（订单最终状态 / 账本最终金额 / 谁是谁 / 谁有没有权限 / 事务成不成功 / 事件可不可靠投递）→ Core
2. 它变化时**核心语义是否应该改变** → Core；只改变规则实现 → Extension
3. 这个能力消失以后**核心业务还能不能成立**（Order / Money / Auth / Ledger 仍然成立）→ Extension
4. 插件**是否应该能够决定核心事实** → 只要答案是"是"，先判 Core

**退出条件**
- ✅ `docs/R4_CORE_EXTENSION_MAP.md` 存在，51 条能力覆盖四档（CORE 24 / EXTENSION_POINT 12 / EXTENSION_IMPL 8 / INFRASTRUCTURE 7）—— 复现：`python _tools/qa/_check_core_extension_boundary.py`
- ✅ **Unclassified = 0**：47 张表**恰好一个归属**（不许多头、不许孤儿、不许幽灵表名）—— 复现：`python _tools/qa/_check_core_extension_boundary.py`
- ✅ **15 个域全部被定过档**（命令按域归属，域被定档 = 命令被定档；域清单由 `DOMAIN_BOUNDARIES.md` **自己算**，不从本图抄）—— 复现：`python _tools/qa/_check_core_extension_boundary.py`
- ✅ 18 个事件类型**双向**对上（代码产生的都在 §5.2 登记、§5.2 登记的都在产生），且最后一列**全是 ❌** = Event 是事实通知、不是隐藏调用（§28）—— 复现：`python _tools/qa/_check_core_extension_boundary.py`
- ✅ 判据**真的会红**：14 条反向破坏用例 + 1 条正面前提全部成立 —— 复现：`python _tools/qa/_reverse_verify_r4_all.py`
- ⚠️ 三条 `pending: yes` 是**如实留白**（税费 / 促销 / 搜索排序：系统里根本没有这类业务），理由逐条写在块里 —— 复现：`python _tools/qa/_check_core_extension_boundary.py --list`

## R4-02 Contract Design（Unit Conversion + Pricing）

**交付**：`UnitConversionContract v1` 与 `PricingContract v1`，每个写清
**输入 / 输出 / 错误 / 不变量 / 兼容要求 / 生命周期**。
⛔ 指南 §7 明确：**不要设计万能插件接口**（`Plugin.initialize/execute/shutdown` 那种），按能力类型分契约。
⛔ §18：第一个版本**不要**做版本系统，先证明"这个契约真的会被多个实现使用"。

**退出条件**
- ✅ 两个契约（`UnitConversionContract` / `PricingContract`）各有 `CONTRACT_VERSION = 1` 与六个要素，且**契约里一行实现都没有**（AST 去掉文档字符串与注释后扫 db / Session / select）—— 复现：`python _tools/qa/_check_extension_contracts.py`
- ✅ 契约的错误语义是**中文可照着改**的一句，不是异常类型名（`MoneyError` / `QuantityError` / `UnitConversionError` / `PricingError` / `NoPricingRule` / `AmbiguousPricingRule`）—— 复现：`cd backend; python -m pytest tests/test_extension_contracts.py -q`
- ✅ **输出必须是核心类型**：AST 核对 `PricingResult.money: Money` 与 `ConversionResult.quantity: Quantity`（指南 §20「只接受 Money」的机器形态）—— 复现：`python _tools/qa/_check_extension_contracts.py`
- ✅ **顺手做实的一件**：`Rounding` 这条跨十几个文件的口头约定收进 `contracts/money.py` 一处定义，判据用 AST 对全项目 **14 处 `quantize`** 逐条对账（都显式写了 `rounding=`，两位小数那一档都是 `ROUND_HALF_UP`）—— 复现：`python _tools/qa/_check_extension_contracts.py`
- ✅ 判据**真的会红**：契约判据的 10 条反向破坏用例全部成立 —— 复现：`python _tools/qa/_reverse_verify_r4_all.py`
- ⏳ 「Core 侧不认识任何具体实现名（无 `ColdChainPricing` 这类字面量）」这一条**不在本里程碑**：它是依赖防火墙的事，出口在 R4-03 的 `_check_extension_dependencies.py`

## R4-03 Dependency Firewall + 五个检查器

**四条防火墙规则**（指南 §12/§13）：① Core 不能 import 具体 Extension；② Extension 不能直接改 Core 拥有的数据；
③ Extension 不能绕过 Capability；④ Extension 不能直接 import 私有内部。
**五个检查器**（§30，⛔ 只做这五个，每个必须有「为什么代码边界无法解决 / 反向破坏用例 / 静默空转保护」）：
`_check_core_extension_boundary` / `_check_extension_dependencies` / `_check_data_ownership` /
`_check_extension_manifest` / `_check_extension_contracts`。

**横切要求**（指南正文，逐条要有落点）：Extension Registry 与 Manifest（§15）、
配置模块化 `CORE_*` 与 `EXT_*` 分离（§26）、路由由 Extension 声明但**鉴权归 Core**（§27）、
Event 只作事实通知（§28）、模块依赖图可自动生成（§29）。

**退出条件**
- ✅ 五个检查器都在（boundary 30 项 / contracts 21 项 / dependencies 8 项 / ownership 9 项 / manifest 16 项），每个都带 `R4-BOUNDARY-JUSTIFICATION:` 一行 —— 复现：`python _tools/qa/_check_all.py`
- ✅ 五个检查器各有**反向破坏用例**，共 40 条注入 + 5 条正面前提 + 5 条还原校验 = **45/45 全部成立** —— 复现：`python _tools/qa/_reverse_verify_r4_all.py`
- ✅ 五个检查器各有**静默空转保护**（块数 / 表数 / 事件数 / impl 数 / 契约数 / quantize 处数 / 核心文件数 / 权限点数 / 字段数 / 类别数 / 文档覆盖度，逐项有下限；核不到就报红而不是全绿）—— 复现：`python _tools/qa/_reverse_verify_r4_all.py`
- ✅ Manifest 能声明 `id / version / kind / requires / provides / consumes / emits / config / compatibility / owns_tables / routes / capability`（12 个必备字段；注册表、dataclass、文档**三方一致**）—— 复现：`python _tools/qa/_check_extension_manifest.py`
- ✅ 依赖图可生成并可回答「谁依赖谁 / 谁拥有这张表 / 谁提供这个 capability / 谁监听这个 event」—— 复现：`python _tools/qa/_check_extension_dependencies.py --graph`
- ✅ 配置分离：扩展一律 `EXT_<ID>_<KEY>`、核心一律 `CORE_*`，⛔ 扩展不许直接读环境变量 —— 复现：`python _tools/qa/_check_extension_manifest.py`
- ✅ **四条防火墙规则**各有落点：① Core 不能 import 具体 Extension（只有装配根 `main.py` 可以）；② Extension 不能改核心拥有的数据（只能 calculate 出 Money，写语句一条都不许有）；③ Extension 不能绕过 Capability（扩展代码里一行鉴权都没有，能力点由核心施加）；④ Extension 不能 direct-import 私有内部（只许 `app.core.contracts.*` 与 `app.core.extension_registry`）—— 复现：`python _tools/qa/_check_extension_dependencies.py` + `python _tools/qa/_check_data_ownership.py`
- ⏳ **扩展数为 0，所以「每个扩展都合规」那一半此刻只核了空集**（如实记着，不粉饰）：第一个扩展由 R4-04 落地，届时 `_check_extension_manifest.py` 的 `MIN_EXTENSIONS` 要从 0 抬到 1 —— 那是一次**收紧**，不给它留模糊空间

## R4-04 第一个真实扩展：Unit Conversion

**目标**（指南 §19）：先做 `Unit / Dimension / Quantity / ConversionContract`，再实现 SI，
再增加 Imperial，再增加 China-traditional。**整个过程中 Core 不应该为了新增一种单位而不断修改。**

**退出条件**
- ✅ **Core 修改数 = 0**（Add 演练的唯一判据）：区间 `54f2418..cf3588f` 里核心区**改 0 行** —— 复现：`python _tools/ops/_r4_add_drill.py --check`
- ✅ **既有扩展模块修改数 = 0**：同一区间里 `backend/app/extensions/` 下只出现**新增**（1 个文件 `china_traditional.py`），没有任何修改/删除 —— 复现：`python _tools/ops/_r4_add_drill.py --check`
- ✅ 扩展自足（自己声明路由与能力点、自己拥有 0 张表、⛔ 没往 Core Model 加扩展专属字段）—— 复现：`python _tools/qa/_check_core_extension_boundary.py` + `python _tools/qa/_check_data_ownership.py`
- ✅ 契约有单测，且**两个实现各跑一遍同一组契约用例**（那份用例**不认识任何一种单位**：单位与量纲从实现自己的 `units()` 里读）—— 复现：`cd backend; python -m pytest tests/test_unit_conversion_contract.py -q`
- ✅ **重叠必须一致**：凡有两个以上实现都支持的一对单位，值 / 因子 / 量纲**逐位相同**。加第二个实现会带出这件事 —— 两个实现都认识桥接单位（kg/m/l），"谁先回答"取决于字典序，所以它不能靠"反正答案一样"糊过去 —— 复现：`cd backend; python -m pytest tests/test_unit_conversion_contract.py -q -k overlapping`
- ✅ 第一版实现 + 第二版实现：SI（11 个单位 / 3 类量纲）与市制（8 个市制单位 + 6 个桥接单位）—— 复现：`cd backend; python -c "from app.extensions.unit_conversion import PROVIDERS; print([p.name for p in PROVIDERS])"`
- ⏳ Remove 演练（完整卸载）后核心仍成立 —— 出口在 R4-06

**四条如实记着的边界**：
1. ⛔ **不收「尺」与「寸」**：1 尺 = 1/3 米，十进制除不尽，收进来会让 `1 尺→米→尺` 回不到 1（契约用例的往返回归会当场红）。要收它们得先回答"保留几位、谁来定"，那是另一件事。
2. 本轮的换算只覆盖**量纲感知的内建单位**；用户自己填的换算率（`1 车 = 8 方`，存在 `unit_conversions` 表）走的仍是既有那一条路，**一个字节都没动**。
3. 扩展的 `config`（`EXT_UNIT_CONVERSION_UNIT_SYSTEM`）目前**没有任何代码读它** —— 它是"配置要经注册表"这条规矩的活样本，R4-06 的 orphan config 核查会拿它当对象。
4. 路由 `/api/v1/unit-conversion/preview` 的鉴权是 `ORDER_CREATE`（能下单的人就能试算），与既有 `POST /api/v1/unit-conversions` 的 shipper+dispatcher 口径一致；⛔ 扩展代码里**一行鉴权都没有**，它由核心在装配时施加。

## R4-05 第二个真实扩展：Pricing

**目标**（指南 §20）：`Order → PricingContext → PricingContract → Money` 成立。
Core **只接受 `Money`**，⛔ 不接受任何插件自己的对象。

**退出条件**
- ✅ 链路成立：`Order → PricingContext → PricingContract → Money` —— 左边两格由核心的 `core/pricing_context.py::context_of` 负责（扩展没有库访问权），右边**必须是核心的 `Money`**（AST/运行期双重核对）—— 复现：`cd backend; python -m pytest tests/test_pricing_contract.py -q`
- ✅ **两个 Pricing 实现可替换**，替换时 Core 修改 **0 行**、既有扩展模块修改 **0 个**（区间 `51c4a72..a7fee0c`，只新增 1 个文件 `per_quantity.py`）—— 复现：`python _tools/ops/_r4_replace_drill.py --check`
- ✅ **替换是配置行为，不是开发行为**：同一张订单只换规则快照里的 `pricing_kind`，两个实现给出**不同的**结果（统一价 120.00 元 / 按量 8.50 × 15 件 = 127.50 元），而代码一行没改 —— 复现：`python _tools/ops/_r4_replace_drill.py --check`
- ✅ Extension ⛔ 不写账本：只能 `calculate → Money`，最终事实交给 Core 事务（扩展包里一条写语句都没有、也碰不到 `ledgers` / `cash_flows`）—— 复现：`python _tools/qa/_check_data_ownership.py`
- ✅ 历史可解释：订单上保有**派单那一刻定格的规则快照**（`orders.driver_rule_snapshot`），删除扩展后历史单仍解释得通 —— 复现：`python _tools/qa/_check_data_ownership.py`
- ✅ 顺带兑现 R4-03 台账里那条承诺：`_check_extension_manifest.py` 的 `MIN_EXTENSIONS` **从 0 抬到 1**（从这一刻起「扩展数掉到 0」会当场报红，而不是安静地全绿）—— 复现：`python _tools/qa/_check_extension_manifest.py`

**一条如实记着的边界**：`Order → PricingContext` 这一段**在测试里是真的**（用一张 `Order` 实例走完整链路），
但 ⛔ **生产订单计价仍然走既有的核心实现**（`services/freight_pricing.py` / `services/driver_pay.py`）。
本轮**不做接线** —— 那会改钱的口径，与「Core 修改数 = 0」直接冲突，也需要单独的发布与演练。
本里程碑证的是「**这条链在契约层成立、且换实现不用动核心**」，不是「生产已经换成扩展在算钱」。

## R4-06 Remove Drill

**四件不同的事要分开**（指南 §24）：`Disable` / `Uninstall` / `Code Removal` / `Data Removal`。
⚠️ **扩展被删除，不代表它创造的历史事实可以删除**（Money / Audit / Order History 上必须钉死）。

**退出条件**
- ✅ 完整删除 Unit Conversion 之后：**全量静态检查全绿**（124/124，红 0 条）—— 复现：`python _tools/ops/_r4_remove_drill.py --check`
- ✅ 后端用例全绿：**1065 passed**（R3 基线 1020，本轮 +45）—— 复现：`cd backend; python -m pytest -q`
- ✅ core smoke 通过：发件箱 / 投递原语 / 两个契约共 **50 passed**（都不碰那个扩展）—— 复现：`cd backend; python -m pytest tests/test_socket_io.py tests/test_outbox.py tests/test_extension_contracts.py tests/test_pricing_contract.py -q`
- ✅ **API smoke**：拆掉之后应用照常起得来，核心路由 235 → **234**（正好少它那一条）—— 复现：`python _tools/ops/_r4_probe_app.py` + `python _tools/ops/_r4_remove_drill.py --check`
- ✅ **没有 orphan**：route（那条 preview 消失）/ capability（`ORDER_CREATE` 在别处仍有执行点，能力注册表检查全过）/ config（`EXT_UNIT_CONVERSION` 无人引用）/ import（`app.extensions.unit_conversion` 无人引用）—— 四类一个都没有 —— 复现：`python _tools/ops/_r4_remove_drill.py --check`
- ✅ **核心数据没被破坏**：47 张表逐名比对一致（它 `owns_tables=()`，本来就没有数据要删）—— 复现：`python _tools/ops/_r4_remove_drill.py --check`
- ✅ 指南 §24 的四件事**分开做**：停用 Disable（清单 `enabled=False`，路由消失、代码还在）/ 卸载 Uninstall（目录移出仓库）/ 删代码 Code Removal / 数据 Data Removal（无数据可删）—— 复现：`python _tools/ops/_r4_remove_drill.py --check`
- ✅ 演练**可重跑且安全**：开跑前拒绝脏工作区；跑完按字节还原（6 个文件逐个核 sha256）+ 路由回来 + `git status` 干净 —— 复现：`python _tools/ops/_r4_remove_drill.py --check`

**这次演练抓到的三条真东西（如实记着，它们比"通过"更值钱）**：

1. **一次完整卸载不只是删一个目录**：还要重跑两张由源码集合推导出来的产物（界面文案目录、端点索引）
   并删掉 AI 读覆盖表里那条登记 —— 不删就是**化石**（那个检查器专门防这个）。
   所以"重新生成 + 删登记"是**卸载的一部分**，不是额外工作；演练里已经把它做成第 3a 步。
2. **`tests/test_extension_contracts.py` 里的 pricing 内联实现漏了 R4-05 新加的 `applies_to()`** ——
   `isinstance` 假失败，而**全量静态检查不跑 pytest**，所以它一直没露出来。
   是这次演练跑 core smoke 才抓到的。教训：**改了协议就立刻把所有内联实现跑一遍**，别只跑新写的那几个文件。
3. 演练脚本自己踩了两次同一个坑：**用子串当标记**（`unit-conversion` 是 `unit-conversions` 的子串、
   `unit_conversion` 是核心 `unit_conversions` 模块的子串）→ "路由消失"永远判 False、孤儿引用全是假阳。
   判据要盯的是**那一个具体的东西**，不是"名字里恰好含这几个字"。

## R4-07 Compatibility Drill

**目标**（指南 §17，⚠️ 同时受 §18 约束：不要过度做版本系统）：
故意做 `PricingContract v1 → v2` 的实现，验证旧实现还能工作、新实现可以加入、核心无需修改。

**退出条件**
- ✅ v1 与 v2 两个实现**同时可用**，同一组契约用例两边都跑（19 passed；阶梯价是原生 v2）—— 复现：`cd backend; python -m pytest tests/test_pricing_contract.py -q`
- ✅ **核心修改数 = 0**（区间 `f666cf7..5bb144d`，只新增 1 个文件 `tiered.py`；v2 契约与适配器在区间**之前**那一次提交里落地）—— 复现：`python _tools/ops/_r4_compat_drill.py --check`
- ✅ **旧实现还能工作**：v1 实现经 `as_v2()` 适配器后**仍然满足 v1**（`isinstance(p, PricingContract)` 为真），旧消费方一行代码都不用改；且明细各行之和**等于**总额 —— 复现：`python _tools/ops/_r4_compat_drill.py --check`
- ✅ **新实现可以加入**：`tiered` 给出 2 行**原生**明细（前 10 件 × 8.00 + 超出 5 件 × 9.00 = 125.00），而 v1 实现只合成 1 行 —— 复现：`python _tools/ops/_r4_compat_drill.py --check`
- ✅ ⛔ 不出现「10 代接口」：v2 **只加一个方法**（`breakdown`），⛔ 不搞 v1/v2/v3 + compatibility matrix（§18 明确否掉的过度设计）；边界图的契约版本数上限仍是 3，当前只到 v2 —— 复现：`python _tools/qa/_check_core_extension_boundary.py`

**顺序本身就是指南的一部分，如实记一笔**：§18 说「**先证明这个契约真的会被多个实现使用，
再为它设计长期版本兼容**」。所以 v2 **不是**在 R4-02 设计契约时就一起设计的 ——
是到 R4-05 已经有两个实现了之后才加的，而且只加了一个方法。
⛔ 也没有为"任何旧实现"都写适配器：只为**真实存在的**旧实现提供兼容层（§31 坑 13）。

## R4-08 最终架构验收

**五条判据**（指南 §41，⛔ 看的不是"模块数量增加了多少"）：
1. 新增扩展**不会污染 Core**
2. 替换扩展**不会修改 Core**
3. 删除扩展**不会破坏 Core**
4. 扩展依赖**全部可见**
5. **历史核心事实不会因为扩展删除而失效**

**退出条件**
- ❌ 五条各有实测证据（不是散文）—— 复现：`python _tools/ops/_r4_acceptance.py --check`
- ❌ 指南 §42 的验收矩阵落进 `docs/ARCHITECTURE_RECTIFICATION_R4.md`，且 Add / Replace / Remove **是实际演练**、不是静态概念 —— 复现：`python _tools/ops/_r4_acceptance.py --check`
- ❌ 北极星那一句（§44）写进该文档 —— 复现：`python _tools/ops/_r4_acceptance.py --check`

---

## 验收矩阵（Add / Replace / Remove 是**实练**）

> 指南 §42 的矩阵。⛔ 一行的意义是**这一格被真跑证明过**，不是「代码里有」。

| 能力 | Code | CI | Runtime | Add | Replace | Remove | 依据 / 出口 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Core Boundary | ❌ | ❌ | ❌ | — | — | — | R4-01 + `_check_core_extension_boundary.py` |
| Unit Conversion | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | R4-04；Add/Remove 出口 = `_r4_add_drill.py` / `_r4_remove_drill.py` |
| Pricing | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | R4-05；Replace 出口 = `_r4_replace_drill.py` |
| Dependency Firewall | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | R4-03 + `_check_extension_dependencies.py` |
| Data Ownership | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | R4-03 + `_check_data_ownership.py` |
| Compatibility | ❌ | ❌ | — | ✅ | ❌ | ❌ | R4-07；v1/v2 并存出口 = `tests/test_pricing_contract.py` |

**读表须知**

- `Code ✅` = 有判据在每次全量检查里核它；`Runtime ✅` = **在本机真跑过**（起进程 / 真库）。
- `—` = 这一轮不适用（Compatibility 没有 Add：「新增」在它这里是 v2 实现，已单独一列）。
- Add / Replace / Remove 三列**只认演练记录**（`_tools/ops/r4_drill_records/`），⛔ 不认"设计上支持"。

---

## 与 R3 的关系（⛔ 不要重复劳动）

| | R3 | R4 |
| --- | --- | --- |
| 问的问题 | 「真实世界一运行，它还成立吗？」 | 「持续演化时，核心会不会被侵蚀？」 |
| 证据形态 | **运行时证据**（生产跑过 + 故障演练） | **架构证据**（Add / Replace / Remove 实练） |
| 是否动代码 | 少量（且只在证据触发的例外下） | 只动**扩展区**；核心修改数 = 0 是判据 |

R4 **继承** R3 的三条纪律：① 会变的数字不手写（由工具采）；② 「已完成」必须有可执行退出条件；
③ 提交必须能回溯到里程碑编号（这条跨轮继续由 `_check_r3_constraints.py` 守）。
