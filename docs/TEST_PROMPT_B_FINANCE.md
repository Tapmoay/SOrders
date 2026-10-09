# 测试提示词 · 方向 B：财务（账本 / 收支 / 发票 / 结算 / 报表）＋ AI 操作

> **这份是给"测试会话"的开工说明**：照着它就能直接开测，不需要再问人。
> 配套：`docs/TEST_BUG_LEDGER.md`（**所有 bug 写这里**，编号 `TB-nn`）、`docs/DEVELOPMENT_SPEC.md`（施工规范）、`docs/PROJECT_MAP/05_TESTING.md`（测试资产与账号）。
> 建立时的 `HEAD = 64fc850`（2026-10-09）；行号按当时工作区，**引用前自己再核一遍**。

---

## 〇、你这一轮要干的事（一句话 + 边界）

把**钱这条线**从头到尾算一遍：账本与流水、客户收款、挂账单位的余额与额度、支出与开销分类、发票与税务、司机账单与结算、运费结算、供应商与应付款、采购单、报表与导出；
**"一笔钱"在四个落点（订单 / 账本流水 / 现金流水 / 报表）上必须对得上** —— 这是这一方向的中心判据。
AI 助手在钱这条线上的读与写（尤其 **对账工作流**）也要走一遍。发现的问题写进统一台账 `docs/TEST_BUG_LEDGER.md`（方向 B，编号 `TB-01`、`TB-02`…）。

**边界（很重要，别越界）**：
- 归 B：上面这套 + 所有"钱的数字"（金额、余额、应收应付、报表口径、导出文件内容）。
- 归 A（订单方向）：订单状态、订单字段与商品行、下单/派单/接单/送达/改单/退货、地点/商品/联系人/车辆/单位换算/定价这些**基础数据页本身**。
- **交叉点**（B 会碰到，但"动作做没做对"归 A）：`orders.pay` 现场收款、`orders.charge` 挂账到单位、`orders.freight` 改司机运费、`orders.discount` 让价、`ledger.sync_delivered` 补进账本、`price_rules.batch` 批量调价。
  B 这边只判**"钱算得对不对"**（账本、余额、报表、导出）；动作本身有没有按预期落到订单上，写台账时标注「与 A 相关」。
- ⛔ **只记录、不修代码**（用户 2026-10-06 的原话口径：`你现在只是做记录不要做任何改动`）。
- ⛔ **别拿生产库做破坏性试验**：动数据前先 `copy backend\sorders.db _tmp\sorders_backup_<日期>.db`；改完能还原就还原。

---

## 一、先建立项目认知（花 40 分钟，边看边记）

### 1.1 这是什么系统
给**批发商（货主）**下单、平台**派单员**派给**司机**、送达后**记账**的配送订单系统。三块：
- 安卓端（Kotlin）：`android/`；
- 后端（FastAPI）：`backend/`（接口 `backend/app/api/v1/`，业务 `backend/app/services/`，表 `backend/app/models/`）；
- 本地库：`backend/sorders.db`（SQLite，可以直接查）。

### 1.2 钱的六个落点（背下来，出问题先按这个顺序找）
1. **订单**（`models/order.py`）：商品行的单价×数量、让价、司机运费；
2. **账本流水**（`models/ledger.py`、`services/accounting_service.py`、`ledger_sync.py`）：一笔"应该收/应该付"的记录；
3. **现金流水**（`models/cash_flow.py`、`api/v1/cash_flows.py`）：真的收到/付出去的钱；
4. **挂账单位的余额与应收**（`models/arrears.py`、`api/v1/arrears.py`）：挂在单位上还没结的；
5. **司机账单与结算**（`models/driver_bill.py` / `driver_settlement.py` / `driver_billing_rule.py`、`services/driver_pay.py`）：该付司机多少、付了没；
6. **报表与导出**（`api/v1/reports.py`、`services/reports_service.py`、`services/reports/`、`services/stats_export.py`、`ledger_export_worker.py`）：把上面几样汇总给别人看。

### 1.3 五条仓库口径（是判据，不是建议）
1. **金额只有一套格式化**：`services/money_contract.py` ＋ `money_text.py`（前端 `util/Money.kt`）—— 同一个数在不同页面显示不一致 = bug。
2. **历史事实不追改**：已经发生的单/账，改价、改联系人、改单位换算率都**不该回头改历史**（该另起一条）。
3. **营业日 ≠ 自然日**（`backend/tests/test_date_window_business_day.py`）：报表与账本的"今天/这个月"要看营业日口径。
4. **单一来源**：结算/账单的金额只能由一个地方算出来（`[判据] _check_settlement_single_source.py`）—— 两处各算一遍必然对不上。
5. **AI 写操作只有一条路**：`preview_write` 生成**确认卡**，用户点「确认」才写；AI 自己一步都不写。

### 1.4 必读（按顺序）
| 顺序 | 文件 | 你要拿到什么 |
|---|---|---|
| 1 | `docs/PROJECT_MAP/03_BACKEND_DETAILS.md` | 账本/结算/报表的业务规则 |
| 2 | `docs/PROJECT_MAP/02_BACKEND_API.md` ＋ `08A_ENDPOINT_INDEX.md` | 接口清单（含 `/ledger`、`/reports`、`/invoices`…） |
| 3 | `docs/PROJECT_MAP/04_ANDROID_MAP.md` ＋ `08_CODE_LOCATOR.md` | 财务页面在哪个文件 |
| 4 | `docs/PROJECT_MAP/05_TESTING.md` | 怎么跑测试、**测试账号在哪**（密码看这里） |
| 5 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md` | 钱的展示口径（颜色、正负号、千分位） |
| 6 | `docs/PROJECT_MAP/99_STRESS_TEST_REPORT.md` | **一份合格的测试报告长什么样**（照它的形状写你的收口） |
| 7 | `docs/DEVELOPMENT_SPEC.md` §八（涉及金额/状态/历史事实要升级审查）§十七（判据必须能够判红）§二十一（证据记录规范） | 金额类问题的证据要求更严 |
| 8 | `docs/PROJECT_MAP/09_DEV_ONLY_INDEX.md` | 哪些入口是开发态（别当 bug） |

---

## 二、把环境跑起来（同 A 方向，三件事）

```powershell
# 1) 后端
Start-Process C:\python\python.exe -ArgumentList -m,uvicorn,app.main:app,--host,0.0.0.0,--port,8000,--log-level,warning -WorkingDirectory D:\AProjects\ASDH\orders\backend -WindowStyle Hidden
# 2) 安卓（本仓库没有 gradlew）
D:\AProjects\ASDH\orders\_agent\gradle\gradle-8.9\bin\gradle.bat -p D:\AProjects\ASDH\orders\android :app:assembleEmuDebug
python _tools/qa/_install_all.py --only 5554 --no-build
# 3) 中文输入（模拟器剪贴板共享常常是关的，必须用 ADBKeyboard）
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" -s emulator-5554 shell ime set com.android.adbkeyboard/.AdbIME
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" -s emulator-5554 shell am broadcast -a ADB_INPUT_TEXT --es msg "这个月对一下账，看看有没有漏记的"
```
- 截图：`adb shell screencap -p /sdcard/_s.png` ＋ `adb pull`（⛔ 不要用 PowerShell `>` 重定向写 PNG）。
- 中文别乱码：`[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; $env:PYTHONIOENCODING="utf-8"`。

### 2.1 财务方向的三个"尺子"工具（比看页面快得多）
| 工具 | 看什么 | 用法 |
|---|---|---|
| `_tools/ai/_check_ledger.py` | 一条账本流水 ＋ 它关联的订单商品行（验证"改账本会不会回写订单"） | `python -X utf8 _tools/ai/_check_ledger.py <流水号或订单号>` |
| `_tools/ai/_check_receipt.py` | 一笔收款有没有真的进现金流水 | `python -X utf8 _tools/ai/_check_receipt.py <…>` |
| `_tools/ai/_check_order.py` | 一张订单当前状态与金额 | `python -X utf8 _tools/ai/_check_order.py SO…` |
再加一个万能手段：直接用 sqlite3 查 `backend/sorders.db`（**先备份**）。

---

## 三、测试路线（B 方向 14 条主线）

### B1 账本主线：记一笔 / 改 / 删 / 客户收款
- 入口：`ui/dispatcher/LedgerHomeScreen.kt`、`LedgerCreateScreen.kt`、`LedgerPersonScreen.kt`、`LedgerPersonStats.kt`、`DispatcherLedgerScreen.kt`（＋ VM）。
- 怎么走：手工记一笔（金额/对象/时间/来源）→ 看它进了哪 → 改金额 → 删掉 → 走一次**记客户收款** → 再走一次"补进账本"。
- 重点看：
  1. **改一笔会不会连带改订单**（`[判据] _check_ledger_manual_entry.py`、`_check_ledger_scope_full_return.py`）—— 回写是设计，回写**错了**才是 bug；
  2. 删掉之后**报表里是不是也跟着少**（不能只删一半）；
  3. 手工记的账**不该被算成"已进账本"的自动对账结果**（这条 AI 对账工作流会用到）；
  4. 付款被拦住的情形（`[判据] _check_ledger_pay_block_gate.py`）—— 什么条件下该拦住，提示说不说得清。
- 去哪核实：`backend/app/api/v1/ledger.py`、`backend/app/services/ledger_scope.py`、`ledger_response.py`、`ledger_sync.py`、`[判据] _check_ledger_cash.py / _check_ledger_dashboard.py / _check_ledger_dialog_style.py / _check_ledger_self_debt.py`。

### B2 现金流水（真的收到/付出去的钱）
- 入口：`ui/dispatcher/LedgerCashScreen.kt`、`LedgerCashDetailScreen.kt`。
- 重点看：**一笔收款有没有同时出现在"账本流水"与"现金流水"**（这两个是不同的东西，缺一个就是 bug）；现金流水的时间口径（写到哪天）；金额正负号与颜色（`ui/common/Charts.kt`、`[判据] _check_report_money_color.py`）。
- 去哪核实：`backend/app/api/v1/cash_flows.py`、`models/cash_flow.py`。

### B3 挂账单位、余额与额度
- 入口：`ui/dispatcher/ArrearsUnitsScreen.kt`（＋ VM）、`AccountManageScreen.kt`（＋ VM）、`AccountToolsScreens.kt`。
- 怎么走：给一个单位设**额度**（`arrears_unit.set_credit_limit`，HIGH）→ 挂一单到这个单位 → 看余额 → 超额度再挂一笔（看该不该拦、怎么提示）→ 收一笔款 → 看余额与额度回没回。
- 重点看：**余额 = 挂账 － 已收** 这个等式在页面上、报表里、导出文件里三处是否一致；额度改了以后**历史超额的挂账**怎么显示。
- 去哪核实：`backend/app/api/v1/arrears.py`、`ui/dispatcher/ArrearsUnitsViewModel.kt`、`[判据] _check_arrears_units.py / _check_customer_balances.py`。

### B4 支出与开销分类
- 入口：`ui/dispatcher/ExpensesScreen.kt`、`ExpenseCreateScreen.kt`、`ExpenseCategoriesScreen.kt`。
- 重点看：支出记了以后**有没有进报表的支出项**；分类删掉/改名后历史支出怎么显示；支出的关联（`core/ExpenseLink.kt`）指向订单还是车辆，指向的东西被删了会怎样。
- 去哪核实：`backend/app/api/v1/expenses.py`、`expense_categories.py`、`backend/app/services/expense_category_service.py`、`[判据] _check_expense_page.py`。

### B5 发票与税务
- 入口：`ui/dispatcher/InvoicesScreen.kt`、`InvoiceFormScreen.kt`。
- 怎么走：开一张发票 → 改 → 作废 → 删；再跑一次税务汇总报表。
- 重点看：**已作废的发票有没有从报表里剔除**；发票金额与订单/账本的关系；税的口径（`services/tax_service.py`）。
- 去哪核实：`backend/app/api/v1/invoices.py`、`models/invoice.py`、`[判据] _check_tax_invoices.py / _check_ai_invoices.py`。

### B6 司机账单与结算
- 入口：`ui/dispatcher/DriverBillingRulesScreen.kt`（＋ VM，计费规则）、`FreightSettlementScreen.kt`（＋ VM）、`LedgerPersonScreen.kt`、`ui/driver/DriverFreightScreen.kt`（＋ VM）。
- 怎么走：先设计费规则 → 跑"生成司机账单" → 确认账单 → 付一笔 → 再取消一张；对同一司机，用**两种不同的路径**（司机侧看到的运费 vs 派单员侧结算）对比。
- 重点看：**两处算出来的钱必须一样**（`[判据] _check_settlement_single_source.py`、`_check_driver_money.py`、`_check_driver_ledger_merge.py`）；规则改了以后**已生成账单**要不要变（按口径：不变）；账单/结算的**状态机**（生成→确认→付款→取消）能不能跳步。
- 去哪核实：`backend/app/api/v1/driver_bills.py`、`driver_billing_rules.py`、`driver_settlements.py`、`backend/app/services/driver_pay.py`。

### B7 运费结算（货主侧）与运费分类/模板
- 入口：`ui/dispatcher/FreightSettlementScreen.kt`（＋ VM）、`FreightCategoriesScreen.kt`、`FreightTemplatesScreen.kt`（＋ VM）、`FreightPricingScreens.kt`。
- 重点看：结算上限（`[判据] _check_shipper_settle_ceiling.py`）、运费模板套用后金额、分类改名对历史的影响、`services/freight_pricing.py` / `shipper_settle.py` / `shipper_price.py` 与页面是不是一套数。
- 去哪核实：`backend/app/api/v1/freight_settlement.py`、`freight_categories.py`、`freight_templates.py`、`shipper_ledger.py`、`ui/shipper/ShipperLedgerScreen.kt`（＋ VM、`ShipperLedgerGrouping.kt`）、`[判据] _check_freight_settlement_ui.py / _check_shipper_ledger_stats.py`。

### B8 供应商与应付款
- 入口：`ui/dispatcher/SuppliersScreen.kt`、`SupplierDetailScreen.kt`、`ui/common/SupplierEditorDialog.kt`。
- 怎么走：建供应商 → 建一笔应付款 → 付一笔 → 取消一笔；删供应商（看有历史应付时该不该让删）。
- 重点看：应付款余额 = 应付 － 已付；删除/停用供应商后历史单据是否还能显示名字；金额与报表的"应付"口径一致。
- 去哪核实：`backend/app/api/v1/suppliers.py`、`backend/app/services/supplier_service.py`、`[判据] _check_supplier_payables.py / _check_supplier_inline_create.py`。

### B9 采购单
- 入口：`ui/dispatcher/PurchaseOrdersScreen.kt`、`PurchaseOrderFormScreen.kt`。
- 重点看：采购单入库后**库存与成本**是否同步（`services/inventory_service.py`、`cost_basis.py`、`cost_history.py`、`warehouse.py`）；采购单删了以后库存回不回去；采购单价与商品成本的关系。
- 去哪核实：`backend/app/api/v1/purchase_orders.py`、`backend/app/services/purchase_service.py`、`[判据] _check_purchase_orders.py / _check_ai_purchase_orders.py / _check_inventory_purchase_merge.py`。

### B10 报表与统计（口径最容易错的地方）
- 入口：`ui/dispatcher/ReportCenter.kt`（＋ VM）、`ReportHome.kt`、`ReportFinance.kt`、`ReportPriority.kt`、`ui/dispatcher/report/ReportV2Home.kt` / `ReportV2Screen.kt` / `ReportV2Model.kt` / `ReportV2Nodes.kt` / `ReportV2Ui.kt` / `ReportV2ViewModel.kt`。
- 怎么走（**每张报表都按同一套问法**）：① 换个时间窗口（今天 / 这个月 / 自定义）—— 数变没变、变对了没；② 同一口径在**两张报表**之间对不对得上；③ 打印/导出后文件里的数与屏幕一致没。
- 报表清单（后端 `api/v1/reports.py` ＋ `services/reports/`）：营业额、利润、成本覆盖、车辆成本、税务汇总、挂账汇总、客户余额、商品报表。
- 重点看：`[判据] _check_report_window.py`（窗口）、`_check_report_facts.py`（事实）、`_check_report_metrics.py`（指标定义）、`_check_report_boundary.py`（边界：哪些单算/不算）、`_check_profit_report.py`、`_check_export_guards.py`（导出的护栏）。

### B11 导出（Excel/表格）与"给客户看的东西"
- 入口：报表页的导出、`ui/dispatcher/LedgerHomeScreen.kt` 的导出、AI 的导出卡（`ai/AiExportCard.kt`、`AiExportService.kt`）。
- 重点看：导出任务的**状态**（`models/export_job.py`、`services/ledger_export_worker.py`、`ledger_export_paths.py`）—— 失败会不会一直转圈；导出文件里的**列名/金额格式/时间窗口**与屏幕是否一致；大窗口导出会不会超时；`[判据] _check_export_guards.py / _check_ai_export_files.py / _check_ai_export_card.py`。

### B12 货主账本与结算（shipper_ledger）
- 入口：`ui/shipper/ShipperLedgerScreen.kt`（＋ VM）、`ShipperLedgerGrouping.kt`；后端 `api/v1/shipper_ledger.py`、`models/shipper_settlement.py` / `shipper_receipt.py`。
- 重点看：**货主看到的账**与派单员看到的同一笔账是否一致；结算分组（按天/按单）后合计对不对；删一单之后货主的账跟着变不变。

### B13 对账与"漏记"（财务方向的核心业务问题）
- 做法（人工先做一遍，再让 AI 做一遍对比）：给定时间窗 `[from, to]`：**已送达的订单**的应收 vs **账本里对应的入账**，逐单比 —— 漏记、多记、金额不等、时间窗口外补记（例如 10-08 才补记的 9 月单）。
- 期望的正确结论长什么样（可以直接拿它当"标准答案"的形状）：先给结论（有没有漏记、共几单、合计多少），再给两行汇总（已送达订单 / 账本对应入账），再列"要留意"的单（标了现场收现金但状态还未收），最后单独说"不在本月窗口内补记的行"。
- 去哪核实：`_tools/ai/_check_ledger.py`、`_tools/ai/_check_order.py`、`services/ledger_sync.py`（补进账本）、`[判据] _check_ledger_scope_full_return.py`。

### B14 AI 助手（B 方向要测的那一半）
见第四节。

---

## 四、AI 助手怎么测（B 方向）

### 4.1 它由什么组成（读这四个文件）
| 文件 | 干什么的 |
|---|---|
| `android/app/src/main/java/com/tapmoay/sorders/ai/AiAgentLoop.kt` | 拼系统提示词、跑"模型 → 工具 → 模型"循环 |
| `android/app/src/main/java/com/tapmoay/sorders/ai/AiTools.kt` | 工具总表（名字/分组/参数/说明/执行入口） |
| `android/app/src/main/java/com/tapmoay/sorders/ai/AiReadCatalog.kt` | **读动作 69 条**（`python -X utf8 _tools/ai/_show_read_catalog.py` 打印） |
| `android/app/src/main/java/com/tapmoay/sorders/ai/AiWrite.kt` | **写动作 83 条**（带中文名与 LOW/MEDIUM/HIGH 风险） |
另外：`ai/AiWorkflow.kt` ＋ `ai/AiWorkflowRunner.kt` —— 两条只读工作流：**对账** `ledger.reconcile`（B 的主场）、**批量调价** `price.batch`。

### 4.2 B 方向重点测的读动作
`ledger.list_accounts` / `ledger.list_entries` / `ledger.list_receipts` / `ledger.list_temp_shipper_names`、
`shipper_ledger.ledger_summary` / `list_settlements`、`cash_flows.cash_flow_summary` / `cash_flow_breakdown` / `list_cash_flows`、
`expenses.list_expenses` / `expense_categories.list_categories`、`invoices.list_invoices`、`arrears.list_units`、
`driver_bills.list_driver_bills` / `driver_billing_rules.list_rules` / `driver_settlements.list_settlements`、`freight_settlement.freight_settlement` / `freight_categories` / `freight_templates`、
`suppliers.list_suppliers` / `list_payables` / `list_payments`、`purchase_orders.list_purchase_orders`、
`reports.`{`turnover_report`, `profit_report`, `cost_coverage_report`, `tax_summary_report`, `vehicle_cost_report`, `arrears_summary_report`, `customer_balances_report`}、`operation_logs.list_operation_logs`。

### 4.3 B 方向重点测的写动作（全部走确认卡）
- 账目 12 条：`ledger.create_entry`（MEDIUM）、`ledger.update_entry`（HIGH）、`ledger.delete_entry`（HIGH）、`ledger.create_receipt`（记客户收款 HIGH）、`ledger.sync_delivered`（补进账本 MEDIUM）、`expenses.create`、`arrears_unit.set_credit_limit`（HIGH）、`settlements.generate_bills` / `create` / `confirm` / `pay` / `cancel`。
- 发票 5 条：`invoices.create/update/issue/void/delete`；
- 供应商与应付款 8 条：`supplier.create/update/delete`、`supplier_payable.create/update/delete`、`supplier_payment.pay/cancel`（HIGH）；
- 我的账本 2 条：`my_ledger.settle` / `revoke`；采购单 3 条：`purchase_orders.create/update/delete`；运费分类/开销分类各 1 条；
- 消息 6 条：`notifications.*`；
- 交叉（动作归 A，钱的后果归 B）：`orders.pay` / `orders.charge` / `orders.freight` / `orders.discount` / `price_rules.batch`。

### 4.4 必测矩阵（B 方向版）
| # | 场景 | 怎么造 | 看什么 |
|---|---|---|---|
| 1 | 对账工作流 | "这个月对一下账，看看有没有漏记的" | 两步读动作都发了没（`orders.list_orders` ＋ `ledger.list_entries`）；结论里的**单数与合计金额与库一致**；"现场收现金但还没收"的单有没有被单列 |
| 2 | 对账 → 补记 | 接上一步说"那帮我补进账本" | 应该是 `ledger.sync_delivered` 的**确认卡**，卡里单号/金额与上一步的清单逐一对得上 |
| 3 | 记收款 | "顺发农副产品店记一笔收款 106.4" | 确认卡金额/对象正确；写完用 `_tools/ai/_check_receipt.py` 核**现金流水**有没有这一笔 |
| 4 | 报表口径 | "上个月利润多少" | 有没有问清窗口/口径；数与报表页对得上（不一致就是 bug，记 `错数`） |
| 5 | 越权 | 用货主身份问全平台流水 | 应该拒绝并说明（这是权限红线） |
| 6 | 编数 | 问一个不存在的单位/供应商 | 不许编，应该说查不到 ＋ 最接近的候选 |
| 7 | 写 → 取消 | 发卡后点取消 | 库里**一点都不能变**（用三个 `_check_*.py` 工具复核） |
| 8 | 写 → 确认 → 撤回 | 确认后点"撤回" | 回到原值（不是近似值），报表跟着回 |
| 9 | 确认卡过期 | 发卡后放 5 分钟再点 | 清楚提示"已执行过或已过期，重新发起一次" |
| 10 | 大窗口导出 | "把这个月的货主账单导成表格" | 导出任务状态会走完；文件里的列名/金额格式与屏幕一致 |
| 11 | 高风险提示 | `ledger.delete_entry`（HIGH） | 确认卡上有没有明确说后果（删的是哪一笔、能不能撤回） |
| 12 | AI 流水页 | 上面每条做完都去 AI 助手 → 设置 → **AI 操作流水** 看一遍 | 动作名对不对、有没有多余读、失败原因是什么（⚠️ 已知：这个页面只显示英文 id，旧台账 L-58 已记，别重复记） |

### 4.5 AI 的硬边界（当判据用）
1. 写只有 `preview_write` 一条路（确认卡 + 用户点确认）；**AI 自己不能直接写**。
2. 高风险（HIGH）动作必须在卡上说清后果。
3. 读受权限约束（`LEDGER_EDIT`、`STATS_READ`、`ORDER_*`、`PRICE_RULE_MANAGE`、`PRODUCT_MANAGE`、`USER_MANAGE`、`NOTIFICATION_MANAGE` ＋ 角色 `role:DISPATCHER` / `role:SHIPPER`）。
4. **不许编数字**：查不到就说查不到。
5. 后端每次 AI 请求都留痕：`backend/app/api/v1/ai_operations.py`（`GET /api/v1/ai/operations`），与业务写入的 `operation_logs` 是**两份不同的日志**。

---

## 五、发现 bug 写哪里（硬规矩）

**统一台账：`docs/TEST_BUG_LEDGER.md`**（方向 B 用 `TB-nn`）。先看它的「一、总表」与「四、怎么写一条」。

```powershell
python -X utf8 _tools/qa/_test_bug_ledger.py add --dir B ^
  --title "记客户收款后现金流水里没有这一笔" --severity 错数 --status 已复现 ^
  --phenomenon "账本流水进了，现金流水没有这一笔；报表的现金口径因此少 106.4" ^
  --repro "AI 助手：顺发农副产品店记一笔收款 106.4 → 点确认 → 账本页能看到；现金流水页没有" ^
  --expect "一笔收款应同时体现在账本流水与现金流水" --actual "只有账本流水" ^
  --where backend/app/api/v1/ledger.py:210 --evidence "shots/TB01_ledger_ok.png, shots/TB01_cash_missing.png" ^
  --fix "收款落账后同步写一条现金流水"
python -X utf8 _tools/qa/_test_bug_ledger.py list
python -X utf8 _tools/qa/_test_bug_ledger.py show TB-01
```

**写一条的门槛**：复现步骤（账号/页面/输入/点了什么）＋ 期望（引哪条口径）vs 实际 ＋ 证据（截图路径 / 命令原文＋输出 / SQL＋结果）＋ 定位（`文件:行`，给不出就写"未定位"＋读过的文件）。
**严重度**：`错数` 是这个方向的默认档（金额/余额/报表算错）；界面文案排序用 `可见`；主流程走不通 `堵死`；说不清 `可疑`。
**⛔ 三条禁令**：只记录不改代码；不改别人已写的行（补信息在自己那条里追加 `- 补充（日期）…`）；不贴大段日志与二进制。

---

## 六、把现有测试当"探针"用

| 资产 | 位置 | 怎么用 |
|---|---|---|
| 后端接口测试 | `backend/tests/`（168 个 py；B 类约 65 个：ledger/cash/expense/invoice/arrear/driver/freight/settle/report/money/receipt/supplier/purchase/tax/profit/export…） | 在 `backend/` 下 `python -m pytest tests -q`：**先记基线**（哪些本来就红），之后再跑，新红的才是线索 |
| 静态判据 | `_tools/qa/_check_*.py`（201 个；B 类约 49 个，如 `_check_ledger_cash.py`、`_check_money_contract.py`、`_check_money_display.py`、`_check_settlement_single_source.py`、`_check_report_window.py`、`_check_report_facts.py`、`_check_export_guards.py`、`_check_profit_report.py`、`_check_arrears_units.py`、`_check_supplier_payables.py`、`_check_tax_invoices.py`） | 单跑：`python -X utf8 _tools/qa/_check_money_contract.py` |
| 安卓单测 | `android/app/src/test/java/com/tapmoay/sorders/`（97 个；B 相关：`ui/dispatcher` 8 个 —— FreightSettlementNotice / FreightTabs / LedgerPersonStats / ReportFinance / ReportPriority / ProductFormDiff / VehicleManageScreen / ProductCategoriesOrder） | `gradle.bat -p … :app:testEmuDebugUnitTest` |
| 全量静检 | `python _tools/qa/_check_all.py`（几分钟） | 只在判断"某处是不是本来就红"时跑 |
⚠️ **测试/判据红了不等于 bug**：先确认是不是别人这半天改出来的（`git log`、`git status`、`docs/AI_WORK_CLAIM.md`「进行中」），记的时候写清核对基准。

---

## 七、什么**不要**记成 bug（降噪）
1. 开发态入口（`docs/PROJECT_MAP/09_DEV_ONLY_INDEX.md`）；
2. 故意留的占位（仓里唯一残留是 `docs/changes/FEAT-0009.md:247`，别碰、也别记）；
3. 并行会话正在改的东西（`git status` 里被改的文件）；
4. 纯文案偏好（只有与 `06_DESIGN_SYSTEM.md` 的口径冲突时才记，严重度 `可见`）；
5. **已经记过的同一条**（先 `list` 查重；同一条在详情块里追加，不新开）。

---

## 八、收口（每轮结束都做）
1. **每轮**：`python -X utf8 _tools/qa/_test_bug_ledger.py list` 看自己这轮加了几条；走查流水记在 `_tmp/` 自己的笔记里。
2. **方向测完**：在 `docs/TEST_BUG_LEDGER.md` 的「五、收口」写一段：走了哪些路径、发现几条、几条已复现、几条判定"不是 bug"及原因；形状照 `docs/PROJECT_MAP/99_STRESS_TEST_REPORT.md`。
3. **要人修**：按 严重度 `堵死` > `错数` > `可见` > `可疑` 列出要立项的条目；立项由主会话按仓库规范做（`docs/changes/BUG-00xx.md` 九节 ＋ README 一行 ＋ AI_WORK_CLAIM 一行）。
