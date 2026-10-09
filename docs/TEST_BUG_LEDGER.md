# 测试缺陷统一台账（方向 A 订单 / 方向 B 财务）

> **本文件是什么**：两个测试方向 —— 方向 A（订单 ＋ 地点/商品/联系人/车辆等基础数据）与方向 B（账本/收支/发票/挂账/司机结算/报表等财务）——
> 在走查与联调里**发现的 bug 与可疑点**，全部写进**这一个文档**（用户口径 2026-10-09：「让他们测试出来的 bug 写进统一的文档」）。
>
> **它不是什么**：不是变更单，也不是修复记录。本文件**只做记录 ＋ 定位**（现象 / 复现 / 期望 / 实际 / 证据 / 涉及文件:行 / 建议改法）。
> 用户说「修」时，再把条目按仓库规范**立项**为 `docs/changes/BUG-00xx.md` 或 `docs/changes/CHG-00xx.md`
> （复制 `docs/changes/_TEMPLATE.md` 填九节 ＋ 六格，在 `docs/changes/README.md` 加一行表行，在 `docs/AI_WORK_CLAIM.md`「进行中」写一行带 ID 的声明）。
>
> **编号**：`TA-nn` = 方向 A；`TB-nn` = 方向 B。**与 BUG-xxxx / CHG-xxxx 不是同一套号**，立项时再映射（在详情块里写「→ BUG-00xx」）。
> **状态**：`待核实` → `已复现` → `已核实（静态代码路径）` → `已立项 BUG-00xx` → `已修复 <提交>` / `不修（原因）`。
> **严重度**：`堵死`（主流程走不通）/ `错数`（金额·库存·账本·报表算错）/ `可见`（界面·文案·排序·提示）/ `可疑`（说不清但要记）。
> **只追加**：并行会话可能同时在写 —— 已写下的行**一个字都不要改**；要补信息，在该条的详情块里追加一行 `- 补充（日期）＜内容＞`。
> **基准**：本文件建立时 `HEAD = 64fc850`（2026-10-09，CHG-0096 归档提交）；行号按**当时工作区**，引用前请自己再核一遍。

---

## 一、总表（先看这里）

| 编号 | 方向 | 标题 | 严重度 | 状态 | 一句话复现 | 涉及文件 | 证据 |
|---|---|---|---|---|---|---|---|
| TA-01 | A | 订单管理默认停在「派单中」页签：搜一个已派单的完整单号返回「没有匹配的订单」，… | 可疑 | **已修复 74a6ade** | 进入 工作台→订单管理，页面默认停在「派单中」页签（不是「全部」）；在搜索框输入一个确实存在、状态为已派单的单号再点搜索，… | android/app/src/main/java/com/tapmoay/sorders… | shots/TA26_search_pending_tab.png |
| TA-02 | A | 测试文档写的账号密码与库里的实际密码不一致（05_TESTING.md 写 p… | 可见 | **已修复 74a6ade** | docs/PROJECT_MAP/05_TESTING.md:19-21 写「账号密码均 pass12345」，但拿 pa… | docs/PROJECT_MAP/05_TESTING.md:19-21<br>docs/… | 命令原文：python -X utf8 _tmp/ta_api.py --as… |
<!-- TESTBUG:ROWS:A -->
<!-- /TESTBUG:ROWS:A -->
| TB-01 | B | 挂账单位页看不到任何余额：只有信用额度，点卡片也没反应 | 可见 | **已修复 0bcbf39** | 工作台 → 挂账单位：每张卡片只显示 名称 / 电话 / 账期（月结 30 天）/ 信用额度 + 删除 / 编辑；点卡片主… | android/app/src/main/java/com/tapmoay/sorders… | shots/TB_arrears_list.png、shots/TB_arre… |
| TB-02 | B | 一多半的开销在现金流水里查不到：53 张开销只有 23 张有钱出去 | 可疑 | **已修复 de9be4a** | 库 backend/sorders.db 的 expenses 共 53 张（合计 44560.51 元），只有 23 张… | backend/app/api/v1/expenses.py:79-106 | 命令输出：expenses 53 张合计 44560.51；有流水的 23 张… |
| TB-03 | B | 车辆成本表的「成本合计」不等于利润表的「司机运费」：月窗口差 5952 元（8… | 可疑 | **已修复 0bcbf39** | 车辆成本表只累计「现在挂在这台车上的那位司机」的按单应付，没有挂车的司机整块不计入；利润表的司机运费是全量。同一窗口两处数… | backend/app/services/reports/vehicle_cost_que… | shots/TB_vehicle_cost_day.png（顶卡 570.96… |
| TB-04 | B | AI 对账的结论对，但明细桥与账本侧对不齐（退货红冲笔数/金额，且漏了两张已软… | 可疑 | **已修复 0c66e21** | 让 AI 把 2026-09 的已送达订单和账本对一遍，结论正确（178 单里唯一在 9 月账本找不到的是 10-07 才… | backend/app/services/ledger_sync.py:1 | shots/TB_ai_reconcile4.png（差额说明原文）；_tmp… |
| TB-05 | B | AI 设置页「跑工作流」开关点开就弹回：默认工具集漏了 run_workflo… | 可见 | **已修复 371d597** | AI 助手 → 设置 →「AI 能用的能力」抬头写「查询 7/8」；把「跑工作流」那条开关点开（checked=true、… | android/app/src/main/java/com/tapmoay/sorders… | 能力开关页 uiautomator dump（checkable=true 的… |
| TB-06 | B | AI 确认卡拿不到的时候，回执把「已经写进去了」和「什么都没写」糊成了一句 | 可见 | **已修复 a87eaca** | 同一张 AI 确认卡被点了第二下、或者卡片过期后再点确认，回执都只有同一句「没写成：这次操作已经执行过、或者已经过期（确认… | android/app/src/main/java/com/tapmoay/sorders… | 改前 _tmp/tb9/tapcard_pre3_after.png ／ 改后… |
<!-- TESTBUG:ROWS:B -->
<!-- /TESTBUG:ROWS:B -->
| TB-07 | B | 开销能挂到不存在的司机/车辆/订单上；挂到不存在车辆的那笔被车辆成本表静默吞掉 | 可疑 | **已修复 512ec98** | POST /api/v1/expenses 不校验 driver_id / vehicle_id / order_id 是… | backend/app/services/accounting_service.py:88… | _tmp/test_round3/evidence_TB07_expense_… |

---

## 二、方向 A 详情（订单 / 地点 / 商品 / 联系人 / 客户 / 车辆 / 单位换算 / 对应 AI 操作）

<!-- TESTBUG:DETAIL:A -->
### TA-01 · 订单管理默认停在「派单中」页签：搜一个已派单的完整单号返回「没有匹配的订单」，空态不提状态筛选

- 严重度：可疑　／　状态：已复现　／　记录：2026-10-09 08:45 CST
- 现象：进入 工作台→订单管理，页面默认停在「派单中」页签（不是「全部」）；在搜索框输入一个确实存在、状态为已派单的单号再点搜索，列表显示「没有匹配的订单」。切到「全部」页签后同一个单号立刻搜得到。页面标题始终写「全部订单」、右上角药丸写「不限时间」，从界面上看不出「只搜派单中」这一层筛选。
- 复现：账号 派单员 13800000001（App 已登录态）→ 工作台 → 订单管理 → 搜索框输入 SO202610095032003138 → 点「搜索」→ 显示「没有匹配的订单」（shots/TA26_search_pending_tab.png）→ 点页签「全部」→ 同一单号立刻出现在列表里。接口对照：adb logcat 显示 App 发的是 GET http://10.0.2.2:8000/api/v1/orders?status=PENDING_DISPATCH&q=SO202610095032003138 → 200 且为空；点「全部」后发 GET http://10.0.2.2:8000/api/v1/orders?q=SO202610095032003138&date_from=2026-10-09&date_to=2026-10-09 → 200 并把该单返回。
- 期望：空态应当说明是哪一个筛选条件把结果挡住了（现有代码对「带日期窗的档位」就会提示「点右上角可以换一段时间」，状态筛选这一路没有对应提示）；或者搜索时自动放宽到全部状态。
- 实际：只写「没有匹配的订单」；页签高亮与标题「全部订单」互相矛盾，用户容易以为单号不存在、单据丢了。
- 证据：shots/TA26_search_pending_tab.png
- 建议改法：空态按当前筛选条件分支：有状态筛选时补一句「当前只看『派单中』，点页签『全部』可以搜其他状态」；或搜索时默认不带 status。
- 定位：`android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DispatcherOrdersScreen.kt:96-107`　`android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DispatcherOrdersViewModel.kt:156-181`　`android/app/src/main/java/com/tapmoay/sorders/data/remote/api/Apis.kt:164-166`
- 补充（2026-10-09，已修复）：**提交 `74a6ade`（变更单 docs/changes/CHG-0099.md）**。改法：新建 `android/app/src/main/java/com/tapmoay/sorders/ui/common/OrderEmptyHint.kt`（52 行纯函数 `internal fun orderEmptyHint(tabLabel, statusFiltered, windowWord, searching, noMatch)`，四档判断两页共用），`ui/common/OrderWindowViewModel.kt:115` 收成 `fun emptyHint(searching, noMatch)`，`ui/dispatcher/DispatcherOrdersScreen.kt:104` 与 `ui/shipper/ShipperOrdersScreen.kt:104` 各删掉自己那段 `if` 改调它。⛔ 查询一个字符没改（`status` / `q` / 日期窗照旧 —— 本单修的是"话说没说清"不是"搜法"）。验证：判据 `_tools/qa/_check_order_list_ui.py` 113/113 全过；反验 `_tools/qa/_reverse_verify_order_list_ui.py` 32/32 全部报红 ＋ 逐字节还原；单测 `ui/common/OrderEmptyHintTest.kt` 8 档（全量 102 类 / 1444 tests / 0 failures）；真机 `emulator-5554` 搜 `SO202610095032003138` ⇒「「派单中」里没搜到 —— 这一页只看「派单中」，点页签「全部」可以搜别的状态」（`shots/78_CHG-0099_空态_派单中里没搜到.png`），切「全部」立刻搜到（`shots/79_CHG-0099_切到全部就搜到了.png`）。

### TA-02 · 测试文档写的账号密码与库里的实际密码不一致（05_TESTING.md 写 pass12345，实际是 123321）

- 严重度：可见　／　状态：已复现　／　记录：2026-10-09 08:45 CST
- 现象：docs/PROJECT_MAP/05_TESTING.md:19-21 写「账号密码均 pass12345」，但拿 pass12345 调 POST /api/v1/auth/login 一律 401；实际密码是 123321（docs/PROJECT_MAP/09_DEV_ONLY_INDEX.md:20 写的就是 123321）。两份测试文档自相矛盾，照 05_TESTING.md 走会连不上账号，反复试错还会把账号顶进登录锁定。
- 复现：python -X utf8 _tmp/ta_api.py --as=1 GET /api/v1/orders（内部先 POST /api/v1/auth/login）：用 pass12345 → HTTP 401；用 123321 → HTTP 200 并拿到 token。另外用 bcrypt 逐个比对 backend/sorders.db 的 users.password_hash（脚本 _tmp/ta_pwd.py）：id=1（13800000001 派单员）/ id=2（13800000002 货主）/ id=3（13800000003 司机）三个账号的 hash 都匹配 123321、都不匹配 pass12345。期间 13800000001 因反复失败被锁，接口返回 429 与 detail「这个账号连续登录失败太多次，已被临时锁定（约 15 分钟）。请稍后再试；忘记密码请联系派单员重置。」
- 期望：文档与实现一致：或者把文档改成实际密码，或者把种子数据改成文档写的密码。
- 实际：05_TESTING.md:19-21 的 pass12345 是错的，会误导所有按文档测试的人（并且试错会触发账号锁定，把后续测试也堵住）。
- 证据：命令原文：python -X utf8 _tmp/ta_api.py --as=1 GET /api/v1/orders（用 pass12345 → HTTP 401；用 123321 → HTTP 200）
- 建议改法：把 05_TESTING.md:19-21 的 pass12345 改成 123321，与 09_DEV_ONLY_INDEX.md:20 对齐；并在文档里提醒「登录失败若干次会锁 15 分钟」，避免多个测试会话互相顶锁。
- 定位：`docs/PROJECT_MAP/05_TESTING.md:19-21`　`docs/PROJECT_MAP/09_DEV_ONLY_INDEX.md:20`
- 补充（2026-10-09，已修复）：**提交 `74a6ade`**。改法（文档对齐，不是改种子数据）：`docs/PROJECT_MAP/05_TESTING.md` 的「## 2. 模拟器与账号（三台）」表头由「（密码均 pass12345）」改成「（密码均 **123321**）」，并在表下补一条 ⚠️：密码是 123321、`docs/PROJECT_MAP/09_DEV_ONLY_INDEX.md:20` 才是对的；连错几次会把账号锁约 15 分钟（429 detail「这个账号连续登录失败太多次，已被临时锁定（约 15 分钟）。请稍后再试；忘记密码请联系派单员重置。」）；**要确认密码请比对 `backend/sorders.db` 的 `users.password_hash`（bcrypt），不要反复试**。同一次还在这份文档末尾加了「## 9. 大规模测试：两个方向（2026-10-09 起）」一节（用户口径 ＋ 两份作业书与这本台账的入口 ＋ `python -X utf8 _tools/qa/_test_bug_ledger.py list/show/add` 用法）。
<!-- /TESTBUG:DETAIL:A -->

---

## 三、方向 B 详情（账本 / 收付款 / 支出 / 发票 / 挂账单位 / 司机账单与结算 / 运费结算 / 报表与导出 / 供应商与应付款 / 采购单 / 对应 AI 操作）

<!-- TESTBUG:DETAIL:B -->
### TB-01 · 挂账单位页看不到任何余额：只有信用额度，点卡片也没反应

- 严重度：可见　／　状态：已复现　／　记录：2026-10-09 12:06 CST
- 现象：工作台 → 挂账单位：每张卡片只显示 名称 / 电话 / 账期（月结 30 天）/ 信用额度 + 删除 / 编辑；点卡片主体没有任何反应（点击前后 uiautomator dump 的节点完全一致）。整页看不到「已挂账 / 已收 / 余额 / 已用额度」，接口 GET /api/v1/arrears-units 的响应里也没有余额字段。要查某单位还欠多少钱只能去 报表中心 → 客户欠款（或客户欠款导出）——而方向 B 的判据是「余额＝挂账−已收，页面/报表/导出三处一致」，这条路径上「页面」这一处没有落点，也就无法互相对照。
- 复现：派单员账号（App 15900000009 / 接口 15900000010，口令 123321）→ 工作台 → 挂账单位（shots/TB_arrears_list.png）→ 点第一张卡「信立农批市场管理处」主体 → 页面无变化（shots/TB_arrears_tap.png 与点击前逐节点一致）；GET /api/v1/arrears-units → 7 个存活单位，字段只有 id/name/phone/remark/credit_limit 等。对照：GET /api/v1/reports/customer-balances?date=2026-10-08 有 已用额度/还能赊/超限（信立 5156.6 / 额度 8000；德赛工业园食堂 3348.2 > 额度 1894.26 标「超了」）。
- 期望：按方向 B 判据（docs/TEST_PROMPT_B_FINANCE.md 的 B3：余额＝挂账−已收 应在页面/报表/导出三处一致），挂账单位这一页应当能直接看到该单位的余额或已用额度，或点进卡片能看它的挂账明细；至少要有一条从「额度」走到「还欠多少」的路。
- 实际：页面上只有额度、没有余额，卡片不可点；安卓侧 UnitCard 只接了 onEdit / onDelete，没有详情入口。
- 证据：shots/TB_arrears_list.png、shots/TB_arrears_tap.png；GET /arrears-units 响应（7 条、无余额字段）；对照 GET /reports/customer-balances（有 已用额度/还能赊/超限）。
- 建议改法：卡片上补一行「已挂账 / 已用额度（余额）」，或加「看这个单位的账」入口跳到客户欠款明细；余额直接复用 customer-balances 的口径，别另算一套。
- 定位：`android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ArrearsUnitsScreen.kt:100-106`　`backend/app/api/v1/arrears.py:1`
- 补充（2026-10-09，已修复）：**提交 `0bcbf39`（变更单 docs/changes/CHG-0100.md）**。改法（只补展示，客户端一个减法都不做）：新建纯函数 `android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ArrearsBalanceLine.kt`（`internal data class ArrearsBalanceLine(val text: String, val warn: Boolean)` ＋ `internal fun arrearsBalanceLine(row: CustomerBalanceRowDto?): ArrearsBalanceLine`，五档：到目前还没有欠款记录 / 没有欠款 · 预收 ¥X / 已挂账 ¥X · 额度：不限额 / 已挂账 ¥X · 额度 ¥L（已超）/ 已挂账 ¥X · 还能赊 ¥A，数字全来自既有的 `GET /reports/customer-balances`）；`ArrearsUnitsViewModel.kt` 并发拉名册与余额（`customerBalancesReport(mode = "day", date = LocalDate.now().toString(), includeOrders = false)` ＋ `filter { it.kind == "unit" }` ＋ `mapNotNull { r -> r.unitId?.let { id -> id to r } }`；余额那一路失败只写 `balanceError`，名册失败才写 `loadError`）；`ArrearsUnitsScreen.kt` 卡上多一行余额（超限标红）＋ 列表顶上「余额没取到：…」＋「重试」。⛔ `GET /arrears-units` 一个字段没加、客户欠款表口径没动、卡片动作没动（点卡片仍不可点，见本条「建议改法」里那条未做的入口）。验证：判据 `_tools/qa/_check_arrears_units.py` 77/77；反验 `_tools/qa/_reverse_verify_arrears_units.py` 34/34 全部报红 ＋ 被碰过的 11 个文件逐字节还原；单测 `ArrearsBalanceLineTest.kt` 8 档（全量 103 个类 / tests=1452 / failures=0 / skipped=2）；真机 `emulator-5554`（派单员 13800000001）：信立农批市场管理处卡上「已挂账 ¥5566.3 · 还能赊 ¥2433.7」、德赛工业园食堂「已挂账 ¥3444.1 · 额度 ¥1894.26（已超）」（`shots/80_CHG-0100_挂账单位_看到余额.png`）、不限额与「到目前还没有欠款记录」（`shots/81_CHG-0100_挂账单位_不限额与无欠款.png`）。注：余额是时点账（as_of = 看的那一天），与 2026-10-08 记这条时看到的数不同属口径使然，不是回归。

### TB-02 · 一多半的开销在现金流水里查不到：53 张开销只有 23 张有钱出去

- 严重度：可疑　／　状态：已复现　／　记录：2026-10-09 12:06 CST
- 现象：库 backend/sorders.db 的 expenses 共 53 张（合计 44560.51 元），只有 23 张能在 cash_flows 找到对应的支出流水（EXPENSE_* 合计 8720.51 元，逐条金额相等、无孤儿流水）；另外 30 张一分钱都没进现金流水（exp_date 全部 ≤2026-09-12，created_at 全是播种批次 2026-09-20 09:58:27.189947；2026-10-04 之后新建的 id 41-53 都有流水）。后果：报表中心 → 现金流量表（真金白银）照不到这 30 笔，9 月「期间费用」10468.91 元与同期现金流出里的 EXPENSE_* 对不起来，按「开销＝钱出去了」的口径去查会以为钱没花。
- 复现：只读 SQL（脚本 _tmp/tb/sweep.py、sweep2.py 已跑）：统计 expenses 里找不到对应 cash_flows 行的开销（对应关系是 cash_flows.doc_id = expenses.id 且 direction 为 out）→ 30 张；再按月份与分类汇总（6 月 2 张 356.00 / 7 月 15 张 19798.00 / 8 月 14 张 8229.00 / 9 月 15 张 10468.91 / 10 月 7 张 5708.60）。对照 backend/app/api/v1/expenses.py:79-106（create_expense → accounting_service.create_expense）与 :91 的注释。
- 期望：按 backend/app/api/v1/expenses.py:91 的注释口径「开销＝钱出去了（还会写一条 cash_flows OUT），必须留痕（2026-09-19 审计）」，每一张开销都应有一条对应的现金流出；现金流量表与开销表之间的差额应当有出处可查。
- 实际：30/53 张开销（全部是开发库播种批次写入的历史数据）没有任何现金流水，页面上也没有任何提示说明这段历史没回填。新建开销这条路径是好的：2026-10-04 之后新建的 id 41-53 都写了流水。
- 证据：命令输出：expenses 53 张合计 44560.51；有流水的 23 张 → EXPENSE_* 8720.51；无流水 30 张（exp_date ≤2026-09-12、created_at=2026-09-20 09:58:27.189947）。脚本 _tmp/tb/sweep.py。
- 建议改法：给历史 30 张开销补写 cash_flows OUT，或在现金流量表/资金收支页的口径说明里写清「某些历史开销没有现金流水所以这里看不到」。
- 定位：`backend/app/api/v1/expenses.py:79-106`
- 补充（2026-10-09，静态代码路径核实）：根因已定位 —— 这 30 张没有现金流水的开销**不是记账路径的 bug**，是开发库的播种历史：`backend/scripts/seed_demo_data.py:1167-1171` 直接 `for _ in range(30): et = rng.choice(list(EXPENSE_NOTES)); car = …; db.add(Expense(exp_date=…, category=et, amount=Decimal(rng.choice([…]))))`，绕过了服务层；记账路径本是 `backend/app/api/v1/expenses.py:79-106` 的 `create_expense` → `accounting_service.create_expense`（它会写一条 `cash_flows` OUT），所以播种批次没有流水。与既有事实吻合：30 张的 `created_at` 全是 `2026-09-20 09:58:27.189947`、`exp_date` 全 ≤2026-09-12，2026-10-04 之后新建的 id 41-53 都写了流水（新建这条路是好的）。→ 两种改法（**修 / 不修由用户拍板，本行不预设结论**）：① 给历史 30 张补写 `cash_flows` OUT（一次性补记，之后现金流量表与开销表对齐）；② 不改数据，在现金流量表 / 资金收支页的口径说明里写清「某些历史开销没有现金流水，所以这里看不到」，并把本条标成 `不修（开发库播种历史数据）`。本条状态按台账链由 `已复现` 推进到 `已核实（静态代码路径）`。
- 补充（2026-10-09，已修复）：**提交 `de9be4a`（变更单 docs/changes/BUG-0018.md）**。改法：① 记账口径收成一处 —— `backend/app/services/accounting_service.py:839` 新增模块级 `EXPENSE_BIZ_TYPES`、`:851` `expense_biz_type(category)`、`:860` `write_expense_cash_flow(db, expense, operator_id=None)`，`create_expense`（`:886`）不再在函数体里手写 `CashFlow(...)`；② 播种脚本 `backend/scripts/seed_demo_data.py:1170-1185` 那 30 笔改走 `create_expense(...)`（不再 `db.add(Expense(...))` 绕过记账）；③ 存量补齐 —— 新建一次性脚本 `backend/scripts/backfill_expense_cash_flows.py`（幂等、默认预览、`--yes` 才写）给 30 张各补一条 OUT 流水（本机实跑：预览 30 → 写 30 → 再预览 0）。判据 `_tools/qa/_check_expense_cash_flow.py` **62 项全过** ＋ 反验 `_tools/qa/_reverse_verify_expense_cash_flow.py` **29/29 全部成立** ＋ `backend/tests/test_expense_cash_flow_backfill.py` 4 个用例；全量静检 219/230（11 条不成立与本单无关）。

### TB-03 · 车辆成本表的「成本合计」不等于利润表的「司机运费」：月窗口差 5952 元（83%）

- 严重度：可疑　／　状态：已复现　／　记录：2026-10-09 12:06 CST
- 现象：车辆成本表只累计「现在挂在这台车上的那位司机」的按单应付，没有挂车的司机整块不计入；利润表的司机运费是全量。同一窗口两处数字：day 2026-09-03 → 210.00 vs 423.00（差 213.00）；week 2026-08-31~09-06 → 398.00 vs 813.00（差 415.00）；month 2026-09 → 1246.00 vs 7198.00（差 5952.00，83%）；month 2026-10（至 10-08）→ 145.00 vs 492.00（差 347.00）。9-3 实测 10 名送达司机里有 4 名（driver 49 刘永强 / 50 赖俊杰 / 51 黄添福 / 52 游春生）没有挂车，差额 213.00 正好等于其中三人的账单合计（90+78+45）。
- 复现：脚本 python -X utf8 _tmp/tb/vc.py（同一窗口同时拉 /api/v1/reports/profit 与 /api/v1/reports/vehicle-cost，打印 delivery_cost 与 delivery_cost_total）；SQL 侧复算：driver_bills 按司机合计（9-3 十个司机共 423.00，其中有车司机那部分 210.00）。页面路径：报表中心 → 详细报表 → 车辆成本（截图 shots/TB_vehicle_cost_day.png、shots/TB_vehicle_cost_bottom.png）。
- 期望：判定：不是 bug —— 页面最底部「口径说明（这几笔钱是怎么算的）」第 3 条原文已写明「「配送成本」= 现在挂在这台车上的那位司机，在这一段时间里按单应付的合计（与运费结算页、利润表同源）。换过司机的话，历史单算在当时那位司机头上、不会跟着车走。」（源码 backend/app/services/reports/vehicle_cost_query.py:47-53 的 _NOTES 五条、导出表头 backend/app/api/v1/reports.py:329 是同一句）。所以数字本身不算错。
- 实际：但页面顶卡写「车辆成本合计」、三笔成本下方写「= 成本合计」，这两处都没有「仅挂靠司机」的限定；_NOTES 只解释了「没挂车的开销进不了本表、仍在利润表期间费用里」，对「没有车的司机的配送成本也不在合计里」一个字都没提。月窗口差到 83% 时页面上没有任何提示，拿这张表的合计去对利润表会被当成错账。
- 证据：shots/TB_vehicle_cost_day.png（顶卡 570.96、三笔成本、挂靠司机配送成本 22）、shots/TB_vehicle_cost_bottom.png（口径说明 5 条原文）；_tmp/tb/vc.py 四组窗口数字。
- 建议改法：低优先、只是防误读：在「= 成本合计」那一行或顶卡的「车辆成本合计」下补一句小字「配送成本只含挂在这台车上的司机；没挂车的司机的运费在利润表的司机运费里」，出处可直接复用 _NOTES 第 3 条。
- 定位：`backend/app/services/reports/vehicle_cost_query.py:128`　`backend/app/services/reports/vehicle_cost_query.py:47-53`　`backend/app/services/reports/profit_query.py:118`
- 补充（2026-10-09，已修复）：**提交 `0bcbf39`（变更单 docs/changes/CHG-0100.md）**。改法（只补口径说明，三笔成本与合计一个数字都没动）：`android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt` 的 VehicleCostTab 顶卡「车辆成本合计」下加一句常显小字「配送成本只算挂在这台车上的司机；没挂车的司机在利润表的「司机运费」里，不进这一格。」，两处「= 成本合计」改写成「= 成本合计（只含挂靠司机）」（总表与逐台车各一处）；`backend/app/services/reports/vehicle_cost_query.py` 的 `_NOTES` 第 3 条末尾补一句「没挂车的司机，他们这段时间的配送成本一分钱都不在「成本合计」里 —— 那些钱在利润表的「司机运费」那一格（那张表不按车分组）。」（导出表头 `backend/app/api/v1/reports.py:329` 与 `_NOTES` 同源，一并生效）；`_tools/qa/_hint_inventory.py` 的 OVERRIDE 复核表补一条把这句话钉成常显（钱的口径，属四族之一，不许挂到「我的 → 提示」开关上，并把 `docs/PROJECT_MAP/09A_HINT_CATALOG.md` 重新生成）。⛔ 折旧、车辆开销、挂靠司机配送成本三笔数与合计、折旧未覆盖名单（粤SZM3825 / 粤B12345）、权限与卡片动作全没动。验证：判据 `_tools/qa/_check_vehicle_depreciation.py` 80/80；反验 `_tools/qa/_reverse_verify_vehicle_depreciation.py` 23/23 全部报红 ＋ 12 个文件逐字节还原；判据/反验新增的都是「这句限定在不在」而不是数字；全量静检 226/228（剩下两条红属并行会话提交 356c2f0，与本单无关）；真机 `emulator-5554`：顶卡「车辆成本合计 ¥570.96」＋小字原文＋「= 成本合计（只含挂靠司机）¥570.96」（`shots/82_CHG-0100_车辆成本_合计带限定.png`）。

### TB-04 · AI 对账的结论对，但明细桥与账本侧对不齐（退货红冲笔数/金额，且漏了两张已软删的整单退货单）

- 严重度：可疑　／　状态：已复现　／　记录：2026-10-09 12:06 CST
- 现象：让 AI 把 2026-09 的已送达订单和账本对一遍，结论正确（178 单里唯一在 9 月账本找不到的是 10-07 才送达的 Shipper 那单 200 元，按营业日该落 10 月，不是漏记；手工记账 5 笔 1477.00 不算营业额），但明细桥里的「退货红冲 8 笔：−431.50 元」与账本侧对不上：9 月窗口内 source=RETURN 的行共 10 笔 −570.70（6 笔 −277.30 挂在仍是已送达的单上，4 笔 −293.40 属 4 张整单退货单：422/423 各 −77.10、450/451 各 −69.60）。AI 只提了 422/423（+154.20 那一项），漏掉 450/451 —— 这两张单已软删（deleted_at 非空），它们的 ORDER 行 +139.20 与 RETURN 行 −139.20 在账本里成对存在、净额 0，所以不影响结论，但用户照这段解释去核账会对不上数。
- 复现：App（派单员 13800000001，测试号自动拿服务端默认 Key）→ AI 助手 → 输入 Reconcile September 2026 delivered orders against the ledger, tell me if anything is missing and show the totals；AI 的工具调用序列：orders.list 178 条 → ledger.list 分页 200+200+123+55+57 条 → reports.turnover 20 段（截图 shots/TB_ai_reconcile.png / TB_ai_reconcile2.png / TB_ai_reconcile3.png / TB_ai_reconcile4.png）。账本侧复算：python -X utf8 _tmp/tb/rec4.py（列出 9 月窗口内 RETURN/REFUND 行明细，并按订单是否 9 月送达分组）。
- 期望：对账给出的每一笔明细都应能在账本里逐行找到（笔数与金额一致）；窗口里存在整单退货/软删单这类「成对红冲、净额 0」的行时应当点出来（哪怕只说一句「另有 2 张已删除的单成对红冲、净额 0，不计入差额」）。
- 实际：「退货红冲 8 笔 −431.50」与账本窗口内实际 10 笔 −570.70 对不上；450/451 那一对（已软删）在解释里完全没有出现。结论本身（无漏记、200 元那单属 10 月）经 SQL 复核正确；另：这条对账问答花了约 11 分钟、会话上下文累计 1184.8k tokens。
- 证据：shots/TB_ai_reconcile4.png（差额说明原文）；_tmp/tb/rec4.py 输出：9 月窗口 RETURN 10 笔 −570.70（6 笔挂已送达单 −277.30；4 笔属 422/423/450/451 共 −293.40）。
- 建议改法：若要对账可复算：对账工作流固定把「账本窗口内逐行明细（含 source=RETURN 红冲与已软删的单）」整理好再交给模型归纳，别让模型自己按单拼明细。
- 定位：`backend/app/services/ledger_sync.py:1`
- 补充（2026-10-09）：这一条的定位应算「未定位」—— 那段退货红冲明细是模型在回答里自己拼的，不在某一行代码里；涉及的取数来源是 backend/app/services/ledger_sync.py（source=ORDER / RETURN / REFUND 三种行的写入口径）与 backend/app/api/v1/ledger.py 的读接口（ledger.list）。上面那行只是文件级引用，不要当成缺陷所在行。
- 补充（2026-10-09，已修复）：**提交 `0c66e21`（变更单 docs/changes/BUG-0019.md）**。改法：对账工作流的返回值改由**代码**算账本那一侧的逐行明细 —— `ledger_detail`（按来源分组的笔数/金额，来源中文走全 App 唯一那份 `core/LedgerSourceLabel.kt`）／`returns`（退货红冲逐行）／`returns_count`／`returns_amount`／`whole_order_returns`（整单退还是部分退由 `isWholeOrderReturn(row, seen)` 判）＋ `scope_note`（进了回收站的单两边都不计的取数口径）；提示词加三行纪律（⛔ 不许自己按单拼明细、不许自己加总，被核对前先讲 `scope_note`）；`core/LedgerSourceLabel.kt` 补 `"return" -> "退货红冲"`。**仍存在的边界**：真机那一轮是**点名** `run_workflow` 的提问 —— TB-04 原文那种自然提问会不会自动挑工作流，不在本单范围内。判据 `_tools/qa/_check_ai_workflow.py` **162 项全过** ＋ 反验 **49/49 全部成立** ＋ `AiWorkflowRunnerTest` 23 项全绿；真机三张 `shots/86_BUG-0019_账本分项与退货红冲_代码算的.png`／`shots/87_BUG-0019_口径_回收站的单两边都不计.png`／`shots/90_BUG-0019_执行过程_跑工作流完成.png`。

### TB-05 · AI 设置页「跑工作流」开关点开就弹回：默认工具集漏了 run_workflow，AI 跑不了对账工作流

- 严重度：可见　／　状态：已立项　／　记录：2026-10-09 23:46 CST　／　记录人：DSH session-bd8fe093-bbe1-4814-af6d-586e0980ff81
- 现象：AI 助手 → 设置 →「AI 能用的能力」抬头写「查询 7/8」；把「跑工作流」那条开关点开（checked=true、prefs 的 enabled_tools 里确实存了 run_workflow），退出这一页再进来它又变回关的、抬头还是 7/8。模型侧因此从来没有这个工具：点名让它跑 ledger.reconcile，它回「这个我查不了 —— 对账工作流（ledger.reconcile）在我这边没有启用，我跑不了它，也不会替它编一份结果出来。」
- 复现：App 派单员 13800000001 → AI 助手 → 设置 (1006,212) → 往下滚 →「AI 能用的能力」desc=打开能力开关 → 点「跑工作流」那条开关 (958,1383) ⇒ checked=true；返回再进这一页 ⇒ 又变回 checked=false。prefs 原文：adb -s emulator-5554 exec-out run-as com.tapmoay.sorders cat shared_prefs/sorders_ai_prefs_u1.xml ⇒ enabled_tools 含 run_workflow、tools_seen 不含它。点名跑工作流：在 AI 助手输入 Run the run_workflow tool with workflow set to ledger.reconcile, from 2026-09-01, to 2026-09-30。
- 期望：用户点开的工具开关要真的生效：存进 prefs 的 run_workflow 必须在默认集里、再进这一页仍是开的、抬头报数变成 8/8，模型的工具表里有 run_workflow（工作流才跑得起来）。
- 实际：android/app/src/main/java/com/tapmoay/sorders/ai/AiKeyStore.kt:636-646 的 DEFAULT_ENABLED_TOOLS 只有 9 项、漏了 AiTools.RUN_WORKFLOW；同文件 :698-703 的 resolveEnabledTools 末尾 return (saved + brandNew).intersect(DEFAULT_ENABLED_TOOLS) 把用户点开的名字静默筛掉（:626 的 KDoc 早就警告过这个失效形状）；而设置页 android/app/src/main/java/com/tapmoay/sorders/ai/AiTools.kt:1201-1209 的 settingsItems 渲染开关时不看默认集 ⇒「开关看起来有、其实没有」。
- 证据：能力开关页 uiautomator dump（checkable=true 的 View 的 checked 位：点开前后 true / 再进 false）；prefs 原文 enabled_tools 与 tools_seen 两串；模型两次回绝的会话（31.4k / 31.2k tokens）；真机 emulator-5554
- 建议改法：默认集补 AiTools.RUN_WORKFLOW（常量 KDoc 的「7 个只读工具」订正为 8）＋ 单测钉住「存进 prefs 的 run_workflow 不许被筛掉」与「默认集里必须有它」—— 已立项 BUG-0022（docs/changes/BUG-0022.md）
- 定位：`android/app/src/main/java/com/tapmoay/sorders/ai/AiKeyStore.kt:636-646`　`android/app/src/main/java/com/tapmoay/sorders/ai/AiKeyStore.kt:698-703`　`android/app/src/main/java/com/tapmoay/sorders/ai/AiTools.kt:1201-1209`
- 补充（2026-10-09，已修复）：**提交 `371d597`（变更单 docs/changes/BUG-0022.md）**。改法：`android/app/src/main/java/com/tapmoay/sorders/ai/AiKeyStore.kt` 的 `DEFAULT_ENABLED_TOOLS` 补 `AiTools.RUN_WORKFLOW`（常量 KDoc 的「7 个只读工具」订正为 8）⇒ `resolveEnabledTools` 末尾那句 `intersect(DEFAULT_ENABLED_TOOLS)` 不再把它静默筛掉；单测 `AiEnabledToolsTest`（7 项）＋ `AiEndpointRulesTest`（6 项）钉住。反着验一次：临时删掉默认集那一行 ⇒ 13 项里 3 项当场变红（`AiEnabledToolsTest.kt:42`／`:60`、`AiEndpointRulesTest.kt:34`），源码逐字节还原。真机：抬头从「查询 7/8」变 **8/8**（`shots/88_BUG-0022_设置页_抬头8比8.png`）、开关留在开的位置（`shots/89_BUG-0022_开关留在开的位置.png`）、工作流真跑起来（`shots/90_BUG-0019_执行过程_跑工作流完成.png`）。⛔ 判据/反验两个脚本（`_tools/qa/_check_ai_workflow.py`／`_tools/qa/_reverse_verify_ai_workflow.py`）随 BUG-0019 那一笔 `0c66e21` 提交 —— 同一份文件同时含两单的节与注入。

### TB-06 · AI 确认卡拿不到的时候，回执把「已经写进去了」和「什么都没写」糊成了一句

- 严重度：可见　／　状态：已修复　／　记录：2026-10-10 01:17 CST　／　记录人：DSH session-bd8fe093-bbe1-4814-af6d-586e0980ff81
- 现象：同一张 AI 确认卡被点了第二下、或者卡片过期后再点确认，回执都只有同一句「没写成：这次操作已经执行过、或者已经过期（确认卡 5 分钟内有效）。请重新发起。」—— 这句话把「其实已经写进去了」和「什么都没写」两半糊在一起，用户看不出这一笔到底出去没有。
- 复现：App（派单员 13800000001，emulator-5556）→ AI 助手 → 新对话 → 发那条记一笔支出的英文提问（要求 preview_write 出确认卡）→ 出卡「确认：记一笔支出」→ 等满 5 分钟（卡 5 分钟有效）再点卡片底部那颗「确认：记一笔支出」⇒ 对话底部只多一句合成话（改前包，_tmp/tb9/tapcard_pre3_after.png，01:07:25 点 / 01:07:39 回执）。
- 期望：「已经写进去了」与「什么都没写」必须分开说：写过了的要讲清这一次没有写第二遍、要改回来点撤回；没写过的要明说「这一次什么都没写」并提示重新发起。
- 实际：改前 ai/AiWritePreviewStore.take() 返回 null 同时表示「已用过 / 已过期 / 被清掉」三种原因，AiWriteService.execute 拿不到卡时只能回那句合成话（改前 :1231-1235）。
- 证据：改前 _tmp/tb9/tapcard_pre3_after.png ／ 改后 _tmp/tb9/p21d_post_after.png（同一句提问、同一姿势）；判据 _tools/ai/_check_ai_guardrails.py 第 2d-3b 节 +8 项（1335 项全过）；反验 _tools/ai/_reverse_verify_confirm_gate.py 9/9 都红了；单测 AiWriteTest 353 项 0 失败；反着验一次 4 项当场变红。
- 建议改法：已修（BUG-0021）。
- 定位：`android/app/src/main/java/com/tapmoay/sorders/ai/AiWrite.kt:384-396`　`android/app/src/main/java/com/tapmoay/sorders/ai/AiWrite.kt:473`　`android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteService.kt:1236-1251`　`android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteService.kt:1305`　`android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiChatViewModel.kt:312-317`

- 补充（2026-10-10，已修复）：**提交 `a87eaca`（变更单 docs/changes/BUG-0021.md）**。改法：`ai/AiWrite.kt` 新增 `doneTokens`（`LinkedHashSet<String>`，只留最近 `DONE_KEEP = 8` 个、只在内存里）与 `markWritten(token)` / `hasWritten(token)`，`AiWriteOutcome.Rejected` 补第三位 `alreadyWritten`；`ai/AiWriteService.kt` 的 `execute` 改成「拿不到卡时先问 `hasWritten`」—— 写过了回「这一次已经写进去了（同一张确认卡只生效一次），没有写第二遍。要改回来的话，点上面那条「撤回」…」＋ `alreadyWritten = true`，没写过回「这张确认卡已经失效了（有效期 5 分钟，App 重启或新开对话也会清掉），这一次什么都没写。要办的话请重新发起。」，并在 `handler.commit(p.payload, "ai-" + token)` **成功之后**才 `store.markWritten(token)`（抛异常时不记，否则重试会被谎报）；`ui/ai/AiChatViewModel.kt` 按这一位换口气（ℹ️ / ⚠️ 没写成）。真机 `emulator-5556` 改前 / 改后各一次对照（`_tmp/tb9/tapcard_pre3_after.png` / `_tmp/tb9/p21d_post_after.png`）。

<!-- /TESTBUG:DETAIL:B -->

---

### 方向 B 收口小结（测试会话 a7dc87d5，2026-10-09）

**走通的路径**：B1 账本（记/改/删 ＋ 客户收款：AI 记一笔手工账 → 工作台→账本管理→订单账 页「¥12.5 / 共 1 笔流水」与库逐格一致；取消 / 确认 / 撤回三条路径各走一遍）；B2 现金流水（收款单 36 笔 17485.70 ＝ cash_flows 的 RECEIPT_* 合计，逐张相等；2026-09 收入 5446.60 / 支出 6928.61 / 净 -1482.01 与 finance 导出逐格一致）；B3 挂账单位余额与额度（GET /arrears-units 7 家 ＋ /reports/arrears-summary 逐单位 与 SQL 复算一字不差；customer-balances 38 行 Σ ＝ totals 72504.40，单位桶与货主桶互斥不重复计钱；未分配挂账 51799.10 ＝ Σ货主行）；B4 支出与开销分类（53 张开销按分类/月份汇总与利润表期间费用吻合：9 月 10468.91）；B5 发票与税务（应交增值税 ＝ 销项 − 进项：2026-09 -965.62、2026-10 -109.40，作废票与未填税率票被剔除，与 tax-summary 导出逐格一致）；B6 司机账单与结算（2026-09 三个数 7428.00 / 7242.00 / 7198.00 已由源码 docstring 声明，见下「不是 bug」第 2 条；2026-08 与 2026-10 两处合计完全相等 2910.00 / 492.00）；B7 运费结算货主侧（货主「我的账本」页 与 /shipper-ledger/summary 逐格一致）；B8 供应商与应付款（/suppliers payable_total 28033.78 / paid 1200.50 / unpaid 26833.28，与 cash_flows PAYMENT_SUPPLIER 2 笔 1200.50 对得上）；B9 采购单（13 张，与 supplier_payables 的「采购单 #n」一一对应）；B10 报表口径（报表中心五张表 ＋ 11 个详细报表，跨 2026-10-08 / 2026-09-03 / 2026-08-31~09-06 / 2026-09 / 2026-10 五个窗口互对）；B11 导出（finance / profit / audit / customers / cost-coverage / tax-summary / customer-balances 七种导出与对应接口逐格一致，文件名日期段＝真实取数区间）；B12 货主账本（同 B7：货主与派单员看到的同一笔账一致）；B13 对账与漏记（SQL 判据：已送达且有归属的订单行 0 漏记、逐单金额 0 差异、无归属订单 0 张；AI 对账一次走通）；B14 AI 助手（读 ＋ 写：预览卡的中/高风险措辞、取消不落库、确认落库、撤回回到原值、补账幂等空跑）。

**没走完 / 没走成**：① 越权（货主账号问全平台流水）与 ② 编数（问一个不存在的挂账单位）两条 AI 用例没走完 —— 换号登录时停在登录页（输入框坐标错位，手机号和密码被打进同一个框），随后被叫停；③ AI 确认卡「5 分钟过期」只用设备上历史会话里的一条旧红字（「没写成：这次操作已经执行过、或者已经过期（确认卡 5 分钟内有效）」）作旁证，没有当场等 5 分钟复现；④ 大窗口导出没跑成：/reports/export 必须带 date，单传 date_from/date_to 会 422「日期：必填」，没再补参数重试；⑤ 写侧未动：采购单入库对库存/成本的联动、ExpenseLink 指向对象被删、作废一张发票再看报表剔除、司机账单状态机跳步 —— 这几条只做了读侧核对；⑥ 司机接单/送达侧（5558）未碰。

**金额三处核对的结果**：屏幕（App）/ 接口 / 导出 / 库四个来源两两互对，**没有发现一处算错的钱**。要点：报表中心五张表与 /reports/* 逐格一致；7 种导出与接口逐格一致；账本 975 行 91395.30 与「订单账」页那笔一致；36 张收款单 ＝ 现金流水收款；挂账 7 家在页面/报表/导出三处一致；税账与票面税额吻合。**唯二「两处数字不一样」的地方都立了条目且都不是算错钱**：TB-03（车辆成本合计只含挂靠司机，页面口径说明第 3 条已声明）、TB-04（AI 对账的明细桥不完整，结论正确）。

**判定「不是 bug」（都实测过，别再重复记）**：
1. 车辆成本表「成本合计」与利润表「司机运费」的口径差（见 TB-03）：页面最底部的「口径说明」第 3 条 ＋ 导出表头 backend/app/api/v1/reports.py:329 原文都写明「配送成本＝现在挂在这台车上的那位司机本期按单应付的合计」，换成 source 是 backend/app/services/reports/vehicle_cost_query.py:47-53 的 _NOTES 第 3 条。
2. 2026-09 的三个数（账单 7428.00 / 账单接口 7242.00 / 运费结算 7198.00）：backend/app/api/v1/driver_bills.py:50-67 的 docstring 已把三处差异逐条写在明处（已软删的订单、整单退货的单），并注明「整单退货的司机运费照不照结」是产品决策、已挂「待拍板」。
3. 已送达后整单退货的单在账本里 ORDER ＋ RETURN 成对红冲（422 / 423 / 450 / 451），不是漏记、也不是错账。
4. 期间费用（权责，开销表）与现金流量表（真金白银）之间的差额本身是正常口径；只有「30 张历史开销完全没有流水」这一条立了 TB-02。
5. 5 笔手工记账不产生现金流水、也不抬高营业额 —— 设计如此（手工记账 ≠ 收到钱）。
6. AI「补进账本」没有日期范围、只能按货主补：这是工具本身的形状，AI 也如实说明并先问再出卡。
7. AI 页在非测试号（15900000009 / 15900000010）显示「还没配置模型 API Key」是设计如此 —— backend/app/services/auth_service.py:49 的测试号白名单是 1380000000x，AiContainer.kt:367 ensureDefaultKey 只在本地没 Key 且服务端有默认 Key 时才补。
8. 模拟器上「送达 10-07 18:17」不是时区 bug：5556 的 persist.sys.timezone ＝ GMT，App 按系统时区格式化（android/app/src/main/java/com/tapmoay/sorders/util/TimeFmt.kt:36 / :58 / :95），后端存 UTC、报表按东八区业务日分桶（backend/app/core/business_time.py）。
9. 货主账本页那笔「未指定货主 欠我 ¥200」是 settlement 里客户名为空时的兜底显示，金额与订单一致（不是算错钱）。

**给后续测试会话的环境提醒**：①口令是 123321（docs/PROJECT_MAP/05_TESTING.md:19-21 的 pass12345 是错的，见 TA-02），连错 5 次锁 15 分钟；②**同一个账号在接口层登录会把 App 顶下线**（users.session_revoked_reason「账号在另一台设备登录」）—— 本轮 App 用 15900000009、接口用自建 TB 账号 15900000010（users.id=125，role 要传小写 dispatcher）；③5556 只有 ASCII 输入法，给 AI 提问只能用英文；④报表接口参数名不统一：/cash-flows* 用 date_from/date_to，/driver-bills 只认 month，/reports/export 必须带 date，/freight-settlement 认 month 或 from/to —— FastAPI 会静默忽略未声明的 query 参数，先查 openapi.json 再判定「过滤失效」；⑤AI 页对话变长后输入框会上移，别死记坐标（点输入框提示文字再输），从 AI 页返回上级用左上角「返回」而不是 keyevent 4；⑥截图只能 adb shell screencap -p 到 /sdcard 再 adb pull。

**本轮留下的测试数据**：users.id=125 / 15900000010「TB测试派单员」（本轮自建，可删）；AI 会话记录（派单员 13800000001 的对话）留在设备上；账本行 id=976（TBtest01 1×12.5，2026-10-09，source=MANUAL）是 AI 写路径测试时建的、**已由同一条 AI 撤回删掉**，库里现在没有；数据库备份 _tmp/sorders_backup_20261009_tb.db（做「补进账本」幂等测试之前的那一份）。
### TB-07 · 开销能挂到不存在的司机/车辆/订单上；挂到不存在车辆的那笔被车辆成本表静默吞掉

- 严重度：可疑　／　状态：已复现　／　记录：2026-10-10 02:57 CST
- 现象：POST /api/v1/expenses 不校验 driver_id / vehicle_id / order_id 是否存在：三个外键全填 999999 也 200 落库（id=55，7.77 元，现金流水照写 cash_flows id=93 EXPENSE_REPAIR order_id=999999）。开销页把取不到的名字写成空字符串，与「本来就没挂」看不出区别；同一窗口车辆成本表 expense_total=5598.50（= 挂车合计 5606.27 − 孤儿 7.77），利润表期间费用=5804.87（含这 7.77）——两张表差一笔，页面上没有任何说明。
- 复现：账号 13900000001（派单员，8020 副本库 sorders_a3.db）：1) POST /api/v1/expenses {"exp_date":"2026-10-09","category":"维修","amount":7.77,"driver_id":999999,"vehicle_id":999999,"order_id":999999} → 200 id=55；2) GET /api/v1/expenses?date_from=2026-10-01&date_to=2026-10-31 → 该行 driver_name/order_no/vehicle_name 全是空串、link_kind=vehicle；3) GET /api/v1/reports/vehicle-cost?mode=month&date=2026-10-15 → expense_total=5598.50；4) GET /api/v1/reports/profit?mode=month&date=2026-10-15 → operating_expense_total=5804.87；5) SQL 复算：10 月开销合计 5804.87、挂车 5606.27、挂到不存在车辆 7.77。脚本 _tmp/test_round3/ev_tb07.py（可重跑）。
- 期望：关联对象不存在时应拒绝（400/422），或至少把该行标成「关联已失效」；车辆成本表若排除孤儿车辆开销，应在口径说明里写明并给出被排除的笔数/金额，不能让同一窗口两张表差一笔而无声。
- 实际：200 落库，无任何校验与提示；页面只显示空字符串；车辆成本表静默少这 7.77（它不进任何 per_vehicle 行，也不进 expense_total），利润表含它 ⇒ 车辆成本表「成本合计」与利润表「期间费用」永久差这一笔。
- 证据：_tmp/test_round3/evidence_TB07_expense_orphan.txt（SQL＋接口输出）；_tmp/test_round3/t2_out/t2_log.json
- 建议改法：create_expense 里校验三个外键（或复用「关联必须存在」的统一守卫）；报表侧对孤儿关联显式归类（未挂车/已失效）并在口径说明里报出笔数与金额。
- 定位：`backend/app/services/accounting_service.py:887`　`backend/app/api/v1/expenses.py:56-72`　`backend/app/services/reports/vehicle_cost_query.py:69-75`
- 补充（2026-10-10，已修复）：**提交 `512ec98`（变更单 docs/changes/BUG-0023.md）**。改法：① 唯一写入闸门 `backend/app/services/accounting_service.py::create_expense` 新增 `_require_expense_links`（司机 3 态：不存在 / 已停用 / 已删（走全仓唯一份 `backend/app/services/soft_delete.py::has_del_suffix`）；车辆 2 态：不存在 / 已停用；订单 2 态：不存在 / 在回收站（`deleted_at` 非空），共 7 条 `raise ValueError`，文案写明字段名＋id＋怎么改；HTTP 层原有的 `except ValueError → 400` 一个字节未改）；② `backend/app/services/reports/vehicle_cost_query.py` 把窗口开销拆三桶（挂到真实车辆 / 没挂车 / 查无此车，`_vehicle_expenses` → `_expense_buckets`），新增 `unlinked_expense_total` / `unlinked_expense_count` / `orphan_expense_total` / `orphan_expense_count` / `expense_window_total` / `expense_window_count` 六个顶层字段（`backend/app/schemas/reports.py::VehicleCostReportOut` 同步声明），并在真有挂不上车的钱时往 `notes` 追加一行带笔数与金额的说明（`expense_total` 语义一字未变，仍只算挂到真实车辆的）；③ 单测 `backend/tests/test_expense_links.py` 5 档＋判据 `_tools/finance/_check_expense_links.py` **33 项全过**＋反验 `_tools/finance/_reverse_verify_expense_links.py` **25/25 都红了**。接口证据：8031（改前）三个 999999 的 POST ⇒ **200**、车辆成本表 `expense_total=5521.11` vs 利润表 5727.48（无声差 206.37）；8032（改后）同一请求 ⇒ **400**「司机不存在（driver_id=999999）…」、`orphan_expense_total=7.77` / `unlinked 198.60×2` / `expense_window_total=5738.59` 与利润表 5738.59 **一致**（`_tmp/test_round3/fix_TB07_before.txt` ／ `fix_TB07_after.txt`）。


---

## 四、怎么写一条（给测试会话看的规矩）

1. **先复现一遍再写**：写清账号（1380000000x）／页面／输入／接口／数据 id —— 别人照着你写的能再走一遍。
2. **证据至少要有一个**（三选一）：截图路径（`shots/…`，说明尺寸与看到的关键文字）、命令原文 ＋ 输出尾部、库里查出来的行（给 SQL 与结果）。
3. **定位能给就给**：后端 `backend/app/…:123`；安卓 `android/app/src/main/java/com/tapmoay/sorders/…:456`。找不到就写「未定位」＋你走过的文件。
4. **严重度**按四档选，拿不准写 `可疑` —— 宁可记一条可疑，也别漏。
5. **追加用脚本**（原子写，两个方向同时写也不会互相覆盖）：

   `python -X utf8 _tools/qa/_test_bug_ledger.py add --dir A --title "派单后池子里还留着这一单" --severity 可见 --status 已复现 --phenomenon "…" --repro "…" --expect "…" --actual "…" --where backend/app/api/v1/orders_assignment.py:88 --evidence shots/xx.png`
   `python -X utf8 _tools/qa/_test_bug_ledger.py list`
   `python -X utf8 _tools/qa/_test_bug_ledger.py show TA-01`

6. ⛔ 不要在本文件里贴大段日志（>30 行）或图片二进制 —— 贴路径。
7. ⛔ 只记录，**不要顺手改代码**：用户没说「修」之前，本文件是排查产物（这条是 2026-10-06 用户原话口径）。

## 五、收口（写在这一节里，不改上面的行）

（等某个方向测完，由收口那次会话在这里写：测了几条、发现几条、几条已立项、几条判定「不是 bug」及原因。）
### 方向 A 收口小结（测试会话 e5d6c383，2026-10-09）

**走通的路径**：A1 登录/角色（App 上以派单员已登录态操作；接口层用 13800000001/2/3 分别登录校验角色可见性）；A2 建单（接口建测试单 619 / SO202610095032003138，两行货：红富士×3件、香蕉×2件）；A3 派单池＋派单（池卡片展示口径、选司机抽屉、一车运费、确认派单 → DISPATCHED）；A5 订单列表/详情（搜索、状态页签、订单详情、整单打折、行内改数量与单价）；A14 AI 助手（读两条：司机手机号、订单状态与金额；写四条：预览卡、取消、确认、撤回；外加 AI 操作流水页）。

**没走成 / 未走**：A4 司机接单与送达（司机账号在 5558，本轮不占用其它模拟器）；A6 退货、A7 地点与线路、A8 商品与分类、A9 联系人与客户、A10 车辆与司机资料、A11 单位换算、A12 定价、A13 预订单模板 —— 未走；AI 侧未测：确认卡 5 分钟过期、非派单员角色的读权限边界、工作流对账与批量调价（后两个与 B 相关）。

**发现**：本方向共 2 条 —— TA-01（可疑，已复现，订单管理默认「派单中」页签导致搜已派单号显示没有匹配的订单）、TA-02（可见，已复现，测试文档密码 pass12345 与实际 123321 不符）。0 条立项、0 条堵死、0 条错数。

**判定「不是 bug」（都实测过，别再重复记）**：
1. 派单抽屉切车型档会顺带把该档第一位设成已选（AssignDriverDialog.kt:100-106 注释写明是本轮保留的既有行为）。
2. AI 的「撤回」是两段式：点撤回会再出一张 preview_write 确认卡，点确认才回滚 —— 符合「写只有 preview_write」的硬边界，且撤回本身还能再撤回。
3. 货主视角看不到司机运费（同一单返回 freight_fee=null、freight_visible=false，库里有 850.55）—— 口径设计。
4. 整单打折 10% 后：order_products.unit_price 仍是折前价（11 / 8），line_total 是折后价（29.70 / 14.40），goods_amount=44.10、discount_amount=4.90、discount_lines 记录每行 33.00→29.70 与 16.00→14.40 —— 与订单详情页（¥29.7 / ¥14.4 / 合计 ¥44.1）和 AI 回答（原价 ¥49、让价 10% 减 ¥4.90、让价后 ¥44.10）三处完全一致。
5. 折扣之后打开「改这一件货」只点保存（不改任何值）：line_total 仍 29.70、discount_amount 仍 4.9、合计仍 ¥44.1 —— 行内编辑不会把折扣冲掉。
6. 派单池卡片「共 5 件」＝各行数量之和（3+2）、「¥49」＝各行小计之和；运费输入 850.559 被截成 850.55（两位小数规则）。
7. 「订单管理搜不到已派单的单号」已被 TA-01 覆盖：接口 q 参数本身正常（GET /api/v1/orders?q=单号 → 200 返回该单），是页签 status=PENDING_DISPATCH 过滤所致，不是接口 bug。
8. 按截图预览目测换算坐标导致「点了没反应」是测试方法问题（预览 536x1192 与设备 1080x2400 不成简单比例，实测差约 470px）—— 不是 bug，点击坐标一律以 uiautomator dump 的 bounds 为准。

**给后续测试会话的环境提醒**：①测试账号密码是 123321，登录失败会锁 15 分钟（13800000001 一度被锁，返回 429），别拿它反复试错；②5554 这台会自己跳回「AI 助手」页，怀疑别的会话用不带 -s 的 adb 把点击注入了第一台设备 —— 每步操作前后都要重新 dump 确认当前屏；③中文输入必须把整条远程命令作为一个参数传（adb -s emulator-5554 shell "am broadcast -a ADB_INPUT_TEXT --es msg '中文'"），并且截图只能 screencap＋pull；④运费、金额这类展示与库/接口逐一对过，本方向未发现错数。

**本轮留下的测试数据（TA 前缀，可清理）**：订单 619 / SO202610095032003138（已派单给司机 Driver 13800000003，运费 850.55，整单 10% 折扣后商品金额 44.10）、商品 id=73「TA测试商品」（现默认单价 12.5 元）。
