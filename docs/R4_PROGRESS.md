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
- ❌ 两个契约各有 `v1` 声明与六个要素，且**契约里一行实现都没有** —— 复现：`python _tools/qa/_check_extension_contracts.py`
- ❌ 契约的错误语义是**中文可照着改**的一句，不是异常类型名 —— 复现：`python _tools/qa/_check_extension_contracts.py`
- ❌ Core 侧**不认识任何具体实现名**（无 `ColdChainPricing` 这类字面量）—— 复现：`python _tools/qa/_check_extension_dependencies.py`

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
- ❌ 五个检查器都在，且都带 `R4-BOUNDARY-JUSTIFICATION:` 一行 —— 复现：`python _tools/qa/_check_all.py`
- ❌ 五个检查器各有**反向破坏用例**（把每条规则弄坏一次，看它会不会红）—— 复现：`python _tools/qa/_reverse_verify_r4_all.py`
- ❌ 五个检查器各有**静默空转保护**（清单为空 / 数量低于下限时报错，而不是"全绿"）—— 复现：`python _tools/qa/_reverse_verify_r4_all.py`
- ❌ Manifest 能声明 `id / version / kind / requires / provides / consumes / emits / config / compatibility`（涉及库再加 `owns_tables`）—— 复现：`python _tools/qa/_check_extension_manifest.py`
- ❌ 依赖图可生成并可回答「谁依赖谁 / 谁拥有这张表 / 谁提供这个 capability / 谁监听这个 event」—— 复现：`python _tools/qa/_check_extension_dependencies.py --graph`
- ❌ 配置分离：扩展的环境变量一律 `EXT_*`，核心一律 `CORE_*`，⛔ 扩展不许读核心配置项 —— 复现：`python _tools/qa/_check_extension_manifest.py`

## R4-04 第一个真实扩展：Unit Conversion

**目标**（指南 §19）：先做 `Unit / Dimension / Quantity / ConversionContract`，再实现 SI，
再增加 Imperial，再增加 China-traditional。**整个过程中 Core 不应该为了新增一种单位而不断修改。**

**退出条件**
- ❌ **Core 修改数 = 0**（这一条是本轮 Add 演练的**唯一判据**）—— 复现：`python _tools/ops/_r4_add_drill.py --check`
- ❌ 扩展自足（自己的表 / 自己的配置 / 自己的路由声明；⛔ 不往 Core Model 加扩展专属字段）—— 复现：`python _tools/qa/_check_core_extension_boundary.py`
- ❌ 契约有单测，且**两个实现各跑一遍同一组契约用例** —— 复现：`cd backend; python -m pytest tests/test_unit_conversion_contract.py -q`
- ❌ Add 演练：新增一个实现，Core 不改、既有模块不改 —— 复现：`python _tools/ops/_r4_add_drill.py --check`
- ❌ Remove 演练（完整卸载）后核心仍成立 —— 复现：`python _tools/ops/_r4_remove_drill.py --check`

## R4-05 第二个真实扩展：Pricing

**目标**（指南 §20）：`Order → PricingContext → PricingContract → Money` 成立。
Core **只接受 `Money`**，⛔ 不接受任何插件自己的对象。

**退出条件**
- ❌ 链路成立：`Order → PricingContext → PricingContract → Money Core` —— 复现：`cd backend; python -m pytest tests/test_pricing_contract.py -q`
- ❌ **两个 Pricing 实现可替换**，替换时 Core 与 Order / Money / Ledger **修改数 = 0** —— 复现：`python _tools/ops/_r4_replace_drill.py --check`
- ❌ Extension ⛔ 不写账本：只能 `calculate → Money`，最终事实交给 Core 事务 —— 复现：`python _tools/qa/_check_data_ownership.py`
- ❌ 历史可解释：订单上保存**当时的计费规则快照**，删除扩展后历史单仍解释得通 —— 复现：`python _tools/qa/_check_data_ownership.py`

## R4-06 Remove Drill

**四件不同的事要分开**（指南 §24）：`Disable` / `Uninstall` / `Code Removal` / `Data Removal`。
⚠️ **扩展被删除，不代表它创造的历史事实可以删除**（Money / Audit / Order History 上必须钉死）。

**退出条件**
- ❌ 完整删除 Unit Conversion 之后：full static checks 全绿 —— 复现：`python _tools/qa/_check_all.py`
- ❌ 后端用例全绿 —— 复现：`cd backend; python -m pytest -q`
- ❌ core smoke + API smoke 通过 —— 复现：`python _tools/ops/_r4_remove_drill.py --check`
- ❌ **没有 orphan**：route / capability / config / import 四类孤儿一个都没有 —— 复现：`python _tools/qa/_check_extension_manifest.py`
- ❌ **核心数据没被破坏**：删除前后核心事实表逐表比对一致 —— 复现：`python _tools/ops/_r4_remove_drill.py --check`

## R4-07 Compatibility Drill

**目标**（指南 §17，⚠️ 同时受 §18 约束：不要过度做版本系统）：
故意做 `PricingContract v1 → v2` 的实现，验证旧实现还能工作、新实现可以加入、核心无需修改。

**退出条件**
- ❌ v1 与 v2 两个实现**同时可用**，同一组契约用例两边都跑 —— 复现：`cd backend; python -m pytest tests/test_pricing_contract.py -q`
- ❌ 核心修改数 = 0 —— 复现：`python _tools/ops/_r4_replace_drill.py --check`
- ❌ ⛔ 不出现"10 代接口"（§31 坑 13）：只为**真实存在的**旧实现提供兼容层 —— 复现：`python _tools/qa/_check_extension_contracts.py`

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
