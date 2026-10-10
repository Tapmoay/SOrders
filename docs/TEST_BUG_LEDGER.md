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
| TA-03 | A | 商品删除后没有任何恢复入口：弹窗承诺的「列表顶端回收站」在界面上不存在 | 可见 | 已复现 | 商品管理里删除商品（编辑页「删除商品」或 批量操作→删除）后，弹窗都承诺「列表顶端的『回收站』里可以把它恢复回来」，但商品… | android/app/src/main/java/com/tapmoay/sorders… | _tmp/test_round3/A8_no_recycle_bin_evid… |
| TA-04 | A | 司机端「进行中」列表被实时推送打断后整页报 StandaloneCorouti… | 可见 | **已修复 f7f31f2** | 司机端「进行中」页在一次取数在途时收到实时推送（新派单等），整页被错误态顶掉，文案是协程取消的原始异常串 Standalo… | android\app\src\main\java\com\tapmoay\sorders… | _tmp\test_round3\evidence_a4_list_error… |
| TA-05 | A | 删除/恢复在途单不产生实时推送：司机端刷新前无变化、刷新后静默消失/静默回归（… | 可疑 | **已修复 db7b3a4** | 派单员 DELETE /orders/{id}（司机已接单的在途单）与 POST /{id}/restore 都只写 op… | backend\app\api\v1\orders_lifecycle.py:45<br>… | _tmp\test_round3\evidence_del_restore.md |
| TA-06 | A | 派单员软删在途单后，司机端旧卡片仍可点开：详情页只显示「订单不存在」+「重试」… | 可见 | **已修复 db7b3a4** | 派单员软删一张已派给司机的单（DELETE /orders/{id} → 204）后，司机端「进行中」列表里的卡片不会消失… | backend/app/api/v1/orders_lifecycle.py:45<br>… | _tmp/test_round3/evidence_del_stale_car… |
| TA-07 | A | 预订单模板表单：点「保存」后没有任何可见反馈（校验红字排在视口外，不滚动也不提… | 可见 | **已修复 3988501** | 新建预订单时只填名字、不选商品，点底部「保存」后界面完全不动：没有红字、没有 toast、也没跳走，看起来像按钮坏了。把表… | android/app/src/main/java/com/tapmoay/sorders… | _tmp/test_round3/A13_tpl_save_no_feedba… |
| TA-08 | A | 商品列表卡的单价与改价弹窗口径不一致：0.005 在卡片上显示成 ¥0.01 | 可见 | **已修复 6db304e** | 商品 id=76（T1-prod-frac，库 default_unit_price=0.005，单位 箱）在商品管理列表… | android/app/src/main/java/com/tapmoay/sorders… | _tmp/test_round3/A8_price_frac_display.… |
| TA-09 | A | 改价弹窗输入负数被静默过滤成正数并保存（-3 存成 3，无提示） | 可疑 | **已修复 6db304e** | 商品改价弹窗（改默认售价）里输入 -3，输入框当场变成 3 —— 负号被输入规则悄悄丢掉，没有任何提示；点保存后库里就是 … | android/app/src/main/java/com/tapmoay/sorders… | _tmp/test_round3/A8_price_negative_filt… |
| TA-10 | A | 联系人电话栏输入字母被静默清空，仍能保存出「没有电话」的联系人 | 可疑 | **已修复 6db304e** | 添加联系人时电话栏填 abc，点「添加」直接成功，列表里出现这条联系人，但库里 phone 是空的，没有任何校验提示。同一… | android/app/src/main/java/com/tapmoay/sorders… | _tmp/test_round3/A9_contact_phone_filte… |
| TA-11 | A | 商品删除弹窗承诺的「列表顶端回收站」在 App 里从未实现（TA-03 第4轮… | 堵死 | 已复现 | 商品管理里删除商品（编辑页「删 除」或 批量操作→删除）的确认弹窗都写着「列表顶端的『回收站』里可以把它恢复回来」，但商品… | android/app/src/main/java/com/tapmoay/sorders… | _tmp/test_round4/a_evidence_sweep1.txt |
| TA-12 | A | 九类名册删除是物理删除、后端无 restore，App 只有删完当场那一下「撤… | 堵死 | 已复现 | 商品分类/联系人分类/地点分类/线路分类/运费分类/开销分类/预订单分类/账号分类/车辆分类，这九类「名册」的 DELET… | backend/app/api/v1/product_categories.py:299<… | _tmp/test_round4/a_evidence_sweep1.txt |
| TA-13 | A | 账本行 DELETE 是物理删除且没有 restore 端点（删钱的行只能靠审… | 堵死 | 已复现 | DELETE /api/v1/ledger/entries/{id} 走的是 db.delete(row)，行直接从 le… | backend/app/api/v1/ledger.py:603 | _tmp/test_round4/a_evidence_sweep1.txt |
| TA-14 | A | 常用地址恢复后丢失「默认」标记：删前是默认地址，恢复回来不再是 | 可见 | **已修复 947cef9** | POST /shipper/addresses/{id}/restore 只清 is_deleted/deleted_at… | backend/app/api/v1/shipper.py:189<br>backend/… | _tmp/test_round4/a_evidence_sweep1.txt |
| TA-15 | A | AI 卡片说共享地点「删掉就没了、没有回收站、恢复不了」，实际后端是软删且能恢复 | 可见 | 已复现 | AI 写能力的卡片文案与实现相反：blurb 明说「从共享库里删掉一个地点（谁都选不到了）。删掉就没了，没有回收站。」并在… | android/app/src/main/java/com/tapmoay/sorders… | _tmp/test_round4/a_evidence_sweep1.txt |
| TA-16 | A | 开销（expenses）全系统没有任何删除或修改入口：记错一笔永久留在账上 | 堵死 | **已修复 4beb4be** | 开销只有 GET 与 POST 两个端点，没有 DELETE 也没有 PATCH/PUT；App 侧没有任何 delete… | backend/app/api/v1/expenses.py:17<br>android/… | _tmp/test_round4/a_evidence_sweep1.txt |
| TA-17 | A | 客户合并把被并档案物理删除，不可逆（customers 表连软删列都没有） | 可疑 | 已复现 | POST /api/v1/customers/merge 把引用搬到保留的那一条上，然后把被并档案从库里物理删除；cust… | backend/app/api/v1/customers.py:219<br>backen… | _tmp/test_round4/a_evidence_sweep1.txt |
| TA-18 | A | 车辆与客户没有任何删除入口（车只能停用、客户档案无法清理） | 可疑 | 已复现 | 车辆与客户这两个实体连 DELETE 路由都没有：车辆只能改 is_active 停用（车仍然留在列表里），客户档案一旦建… | backend/app/api/v1/vehicles.py:281<br>backend… | _tmp/test_round4/a_evidence_sweep1.txt |
| TA-19 | A | 司机备注（driver-note）零推送：派单员端订单详情停在旧「内部备注」，… | 可见 | 已复现 | 司机在司机端写现场备注后，后端只把文本以「[司机 时间] 」前缀追加进 orders.internal_notes，全程没… | backend/app/api/v1/orders_delivery.py:125 | _tmp/test_round4/shots/f1_detail_before… |
| TA-20 | A | 商品/价格/库存/开销/结算/车辆等主数据写操作零推送：没有任何一端会收到变更… | 可疑 | 已复现 | products / price-rules / shipper-prices / inventory movements… | backend/app/api/v1/products.py:130 | _tmp/test_round4/push_matrix_8062_maste… |
<!-- TESTBUG:ROWS:A -->
<!-- /TESTBUG:ROWS:A -->
| TB-01 | B | 挂账单位页看不到任何余额：只有信用额度，点卡片也没反应 | 可见 | **已修复 0bcbf39** | 工作台 → 挂账单位：每张卡片只显示 名称 / 电话 / 账期（月结 30 天）/ 信用额度 + 删除 / 编辑；点卡片主… | android/app/src/main/java/com/tapmoay/sorders… | shots/TB_arrears_list.png、shots/TB_arre… |
| TB-02 | B | 一多半的开销在现金流水里查不到：53 张开销只有 23 张有钱出去 | 可疑 | **已修复 de9be4a** | 库 backend/sorders.db 的 expenses 共 53 张（合计 44560.51 元），只有 23 张… | backend/app/api/v1/expenses.py:79-106 | 命令输出：expenses 53 张合计 44560.51；有流水的 23 张… |
| TB-03 | B | 车辆成本表的「成本合计」不等于利润表的「司机运费」：月窗口差 5952 元（8… | 可疑 | **已修复 0bcbf39** | 车辆成本表只累计「现在挂在这台车上的那位司机」的按单应付，没有挂车的司机整块不计入；利润表的司机运费是全量。同一窗口两处数… | backend/app/services/reports/vehicle_cost_que… | shots/TB_vehicle_cost_day.png（顶卡 570.96… |
| TB-04 | B | AI 对账的结论对，但明细桥与账本侧对不齐（退货红冲笔数/金额，且漏了两张已软… | 可疑 | **已修复 0c66e21** | 让 AI 把 2026-09 的已送达订单和账本对一遍，结论正确（178 单里唯一在 9 月账本找不到的是 10-07 才… | backend/app/services/ledger_sync.py:1 | shots/TB_ai_reconcile4.png（差额说明原文）；_tmp… |
| TB-05 | B | AI 设置页「跑工作流」开关点开就弹回：默认工具集漏了 run_workflo… | 可见 | **已修复 371d597** | AI 助手 → 设置 →「AI 能用的能力」抬头写「查询 7/8」；把「跑工作流」那条开关点开（checked=true、… | android/app/src/main/java/com/tapmoay/sorders… | 能力开关页 uiautomator dump（checkable=true 的… |
| TB-06 | B | AI 确认卡拿不到的时候，回执把「已经写进去了」和「什么都没写」糊成了一句 | 可见 | **已修复 a87eaca** | 同一张 AI 确认卡被点了第二下、或者卡片过期后再点确认，回执都只有同一句「没写成：这次操作已经执行过、或者已经过期（确认… | android/app/src/main/java/com/tapmoay/sorders… | 改前 _tmp/tb9/tapcard_pre3_after.png ／ 改后… |
| TB-07 | B | 开销能挂到不存在的司机/车辆/订单上；挂到不存在车辆的那笔被车辆成本表静默吞掉 | 可疑 | **已修复 512ec98** | POST /api/v1/expenses 不校验 driver_id / vehicle_id / order_id 是… | backend/app/services/accounting_service.py:88… | _tmp/test_round3/evidence_TB07_expense_… |
| TB-08 | B | 同一笔司机明细能被两张草稿结算单同时锁住：冲突到确认时才报，且报错把「被占用」… | 可疑 | **已修复 9744177** | driver_settlements.py:93 的注释写「建结算单＝把一批「待结」明细锁进一张单子（钱虽未出，但已经不能… | backend/app/api/v1/driver_settlements.py:93<b… | _tmp/test_round3/evidence_TB08_settleme… |
| TB-09 | B | 客户收款登记之后没有任何撤销/红冲入口：报错文案让用户「联系管理员在账上冲正」… | 可疑 | **已修复 6809393** | 派单员在账本里登记一笔客户收款（POST /api/v1/ledger/receipts）会一次写三处：shipper_r… | backend/app/api/v1/ledger.py:734<br>backend/a… | _tmp/test_round3/evidence_TB09_receipt_… |
| TB-10 | B | 账本行的「合计」能写成与 数量×单价 不符的值：AI「改合计金额」只传 tot… | 可疑 | **已修复 47ccdf0** | 手工记账建的行（quantity=3、unit_price=20.00，total 自动为 60.0000）再用 PATC… | backend/app/api/v1/ledger.py:464-467<br>andro… | _tmp/test_round3/evidence_TB10_ledger_t… |
| TB-11 | B | AI 写留痕可以被任何登录客户端（乃至人手工）伪造：X-SOrders-Ori… | 可疑 | 已复现 | 后端判断「这次写是 AI 干的」只看请求头 X-SOrders-Origin: ai（backend/app/core/c… | backend/app/core/ai_operation.py:24<br>backen… | _tmp/test_round3/ai_out/ai_header_probe… |
| TB-12 | B | 部分核销的收款单撤销后再恢复：订单一付款标志被误翻成已收款（剩余欠款再也收不进… | 堵死 | **已修复 d3b4e37** | 一张已送达、只欠 124.00 的挂账单，用「按商品核销」收了 75.00 后订单仍是未收款（对）；把这张收款单撤销、再恢… | backend/app/api/v1/ledger.py:1142-1145 | _tmp/test_round4/runlog/receipt644_rest… |
| TB-13 | B | 销项票挂不上「送达自动记账」的应收行：ledgers.customer_id … | 可疑 | 已复现 | POST /api/v1/invoices（direction=OUTPUT, invoice_no=R4C-INV-10… | backend/app/services/ledger_sync.py:52-68<br>… | _tmp/test_round4/out_invoice2.txt；_tmp/… |
| TB-14 | B | 滚动收款（不绑单）只进现金流水：欠款表/预收/挂账汇总/营业额一分钱都不冲，客… | 错数 | **已修复 7c0421b** | 订单 645 已送达、欠 124.00。POST /api/v1/ledger/receipts {customer_id… | backend/app/services/reports/balance_query.py… | _tmp/test_round4/out_rolling_balance.tx… |
| TB-15 | B | 结算单付款的 paid_at 被静默丢弃：传 2026-09-30 付款，现金… | 可疑 | 已复现 | PATCH /api/v1/driver-settlements/58 {action:pay, method:cash,… | backend/app/api/v1/driver_settlements.py:149<… | _tmp/test_round4/out_settle.txt；_tmp/te… |
| TB-16 | B | 开销没有删除/冲正入口：DELETE 与 PATCH 都 404，记错一笔就永… | 可见 | 已复现 | POST /api/v1/expenses（其他 1.00）→ 200 建出开销 56，同时写 cash_flows 99… | backend/app/api/v1/expenses.py:20-100 | _tmp/test_round4/out_expense2.txt；_tmp/… |
| TB-17 | B | 批量调价点名一个非会员货主时提示「未找到批发商或商品，请先选择」：用户明明选了… | 可见 | 已复现 | POST /api/v1/price-rules/batch {shipper_ids:[135], product_id… | backend/app/api/v1/price_rules.py:118-141 | _tmp/test_round4/out_pr2.txt；_tmp/test_… |
<!-- TESTBUG:ROWS:B -->
<!-- /TESTBUG:ROWS:B -->

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
### TA-03 · 商品删除后没有任何恢复入口：弹窗承诺的「列表顶端回收站」在界面上不存在

- 严重度：可见　／　状态：已复现　／　记录：2026-10-10 03:22 CST
- 现象：商品管理里删除商品（编辑页「删除商品」或 批量操作→删除）后，弹窗都承诺「列表顶端的『回收站』里可以把它恢复回来」，但商品列表页/批量操作页都找不到任何「回收站 / 已删除 / 恢复」入口；商品模块的「回收站」在 Android 端只以文案形式存在，restore 的调用点只挂在 AI 写入通道上，普通用户误删后无法从界面恢复（只能靠 AI 或调接口）。
- 复现：5556/13900000011：①工作台→商品管理→搜索 T1-prod→T1-prod-zero「编辑」→下滑到「更多设置」→「删除商品」→确认→列表里消失，整页 dump 无回收站；②商品管理→批量操作→搜索 T1-prod→勾选 T1-prod-incat→「删除」→确认→匹配数 4→3，该页 dump 同样无回收站。两次都只有删除没有恢复。
- 期望：按用户 2026-09-20 的硬规矩（删除一律软删 + 界面上要有恢复入口），删除后应在商品列表顶端出现「回收站」入口，能逐个恢复被软删的商品（后端 POST /products/{id}/restore 已具备）。
- 实际：界面上不存在该入口：ProductFormScreen.kt:325/412 与 ProductBatchScreen.kt:290 只有「列表顶端的『回收站』…」这句文案；ProductsViewModel.kt 里没有任何列出已删商品的开关；AppRepository.kt:708 restoreProduct 的唯一调用点是 ai/AiWriteDataSource.kt:2383（AI 写入通道），ui/dispatcher 下 0 处调用。
- 证据：_tmp/test_round3/A8_no_recycle_bin_evidence.txt
- 定位：`android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductFormScreen.kt:325,412；ProductBatchScreen.kt:290；ProductsViewModel.kt（无 include_deleted）；AppRepository.kt:708；ai/AiWriteDataSource.kt:2383`

### TA-04 · 司机端「进行中」列表被实时推送打断后整页报 StandaloneCoroutine was cancelled

- 严重度：可见　／　状态：**已修复 f7f31f2**　／　记录：2026-10-10 03:25 CST
- 现象：司机端「进行中」页在一次取数在途时收到实时推送（新派单等），整页被错误态顶掉，文案是协程取消的原始异常串 StandaloneCoroutine was cancelled，只留一个「重试」按钮；点重试或等下一次推送才恢复。
- 复现：5558 / 13900000013 登录司机端停在「进行中」→ 点顶部「刷新」(74,212) 后 1 秒内用派单员 13900000012 的 token POST /orders/{id}/assign 派新单给 driver_id=128（或任何触发 socket refreshOrders 的动作）→ 列表被整页错误态替换。
- 期望：推送触发的重载应静默完成；被新请求取消的旧请求不应写页面级 error（取消不是失败）。
- 实际：页面级 error 被写入 CancellationException 文案（StandaloneCoroutine was cancelled），列表被 ErrorView 整页替换。
- 证据：_tmp\test_round3\evidence_a4_list_error.md
- 定位：`android\app\src\main\java\com\tapmoay\sorders\ui\driver\DriverOrdersViewModel.kt:305`　`android\app\src\main\java\com\tapmoay\sorders\ui\driver\DriverOrdersViewModel.kt:326-327`　`android\app\src\main\java\com\tapmoay\sorders\ui\driver\DriverOrdersScreen.kt:104`

- 补充（2026-10-10，已修复）：**提交 `f7f31f2`（变更单 docs/changes/BUG-0026.md）**。改法：① 取数收成构造接缝 `fetchOrders`（默认 lambda 逐字等于原取数，只为 JVM 单测可注入）；② `catch (e: CancellationException) { throw e }` 排在 `catch (e: Exception)` **之前**（取消不是失败，与 `ui/shipper/ShipperOrdersViewModel.kt:188`、`ui/dispatcher/ReportCenterViewModel.kt:197` 同规矩）；③ 取数世代号 `loadSeq`（挂起点之前 `val mySeq = ++loadSeq`）＋ 成功路径 / 失败路径 / finally 三处 `if (mySeq != loadSeq) return@launch` 守卫 ⇒ 只有当前这一趟取数能写 `orders` / `ordersTab` / `error` / `loading` / `refreshing`，过期那趟（含被取消那趟）一个状态都不写（不靠 Job 同一性判：`Main.immediate` 下 launch 体可能内联先跑、此时 `loadJob` 还是旧 Job）。单测 `android/app/src/test/java/com/tapmoay/sorders/ui/driver/DriverOrdersLoadCancelTest.kt` 3 档（被取消的取数不写错误页也不收加载态 / 真失败仍然显示错误页 / 失败之后重试成功错误页让位给列表），改前 1 failed / 2 passed → 改后 3 passed；判据 `_tools/qa/_check_cancellation_not_error.py` 23 项全过；反验 `_tools/qa/_reverse_verify_cancellation_not_error.py` 13/13 都红了（被碰文件逐字节还原）。⛔ 本单只动司机端这一处；同类点位另外 4 文件 5 处（`ui/dispatcher/DispatcherOrdersViewModel.kt:171`、`ui/dispatcher/DispatcherPoolViewModel.kt:145` / `:177`、`ui/shipper/ShipperOrdersViewModel.kt:164`、`ui/common/ReturnRequestsViewModel.kt:130`）一个都没动。

### TA-05 · 删除/恢复在途单不产生实时推送：司机端刷新前无变化、刷新后静默消失/静默回归（无任何提示）

- 严重度：可疑　／　状态：已复现　／　记录：2026-10-10 03:32 CST
- 现象：派单员 DELETE /orders/{id}（司机已接单的在途单）与 POST /{id}/restore 都只写 operation_logs、不写 outbox_events；司机端列表在删除后保持原样（无推送、无提示），手动「刷新」后该单静默消失；恢复后同样要手动刷新才回来。
- 复现：5558 / 13900000013 在 App 内「确认接单」629（status=ACCEPTED）→ 派单员 13900000012 DELETE /orders/629（204，DB deleted_at 有值、status 仍 ACCEPTED）→ 观察司机端列表（两次截图字节一致，无变化）→ 点「刷新」→ 629 消失；再 POST /orders/629/restore（200）→ 点「刷新」→ 629 回来且 chip=已接单。
- 期望：在途单被撤/被恢复时司机端应有实时通知或至少自动刷新并给出文案（司机不应靠手动刷新才发现单不见了）。
- 实际：无 outbox 事件 → 无推送；列表在手动刷新前不动，刷新后静默消失/回归，全程无提示。
- 证据：_tmp\test_round3\evidence_del_restore.md
- 定位：`backend\app\api\v1\orders_lifecycle.py:45`　`backend\app\api\v1\orders_lifecycle.py:211`
- 补充（2026-10-10，已修复）：**提交 `db7b3a4`（变更单 docs/changes/BUG-0027.md）**。改法：`delete_cancelled_order`（orders_lifecycle.py:100-114）与 `restore_order`（同文件 :240-249）各在同一个写事务里 `outbox.enqueue(db, "orders.deleted" | "orders.restored", {"order_id": order.id, "user_ids": [司机, 货主]})`（`core/outbox.py:93-94` 的 `AGGREGATE_KEY` 两条都映射 `order_id`，`main.py:222-236` 的 `_outbox_deliver` 登记两支 → `push_events.push_order_deleted` / `push_order_restored` → `message_center.publish_order_deleted` / `publish_order_restored`，站内信 ＋ 系统通知 ＋ 实时信号三腿，幂等键 `order.deleted:<id>`）；司机端 `PushTrust.ORDER_TYPES` 认两个类型、`NewOrderAlert` 把被删并进撤回/取消那一支（共用去重键 `revoked:<id>`、同一句语音「有任务被撤回」）、`RealtimeHub` 的 `order.deleted` 支重拉列表并播报、`order.restored` 支只重拉。证据：后端单测 `backend/tests/test_soft_delete_realtime.py` 6 条（改前 5 failed / 1 passed → 改后 54 passed）；判据 `_tools/qa/_check_soft_delete_realtime.py` **60 项全过**；反验 `_tools/qa/_reverse_verify_soft_delete_realtime.py` **22 条注入全红**；真机改前证据 `_tmp/test_round3/evidence_ta0506_before.md`（改后由父会话在 5558 司机端补）。

### TA-06 · 派单员软删在途单后，司机端旧卡片仍可点开：详情页只显示「订单不存在」+「重试」，不说明已被派单员删除，也不自动移出列表

- 严重度：可见　／　状态：已复现　／　记录：2026-10-10 03:37 CST
- 现象：派单员软删一张已派给司机的单（DELETE /orders/{id} → 204）后，司机端「进行中」列表里的卡片不会消失（无实时推送，见 TA-05）；司机点这张卡片能打开详情页，但整页只有「订单不存在」+「重试」，没有任何「派单员已删除这张单」的说明，卡片也不会自动移出，司机只能自己点刷新才消失。
- 复现：① 派单员 POST /orders 建单 635（T2-删后点卡C，行 T2-橙 ×2 @7）→ assign {"driver_id":128,"freight_fee":15.0,"collect_cash":false} → 200；② 司机端 5558（13900000013）「进行中」出现卡片 T2-地址-删后点卡C（bounds 179,464,773,520）；③ 派单员 DELETE /orders/635 → 204，DB deleted_at=2026-10-09 19:37:00.437359、status 仍 DISPATCHED；④ 不点刷新，4 秒后卡片仍在（截图字节数 192169→191443，仅状态条时间变化）；⑤ 点卡片中心 (476,492) → 详情页只有 返回/订单详情/订单不存在/重试。复现 1：订单 633 同样路径，两次一致。
- 期望：司机端应当收到「订单已被派单员删除/撤回」的实时通知并把卡片移出列表（撤回有「订单已撤回」消息类型，删除没有）；即便卡片还在，点开后也应当给出可理解的原因（如「这单已被派单员删除」），而不是只显示「订单不存在」这行空态文案。
- 实际：删除没有任何实时推送（operation_logs 2391/2393 有 ORDER_DELETE、outbox_events 19:28 之后为空），司机端卡片原样保留；点开走 GET /orders/{id} → 404 {"detail":"订单不存在"}，界面只渲染空态「订单不存在」+「重试」（OrderDetailScreen.kt:232），无任何原因说明。
- 证据：_tmp/test_round3/evidence_del_stale_card.md
- 定位：`backend/app/api/v1/orders_lifecycle.py:45`　`backend/app/api/v1/orders_common.py:62`　`android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailScreen.kt:232`
- 补充（2026-10-10，已修复）：**提交 `db7b3a4`（变更单 docs/changes/BUG-0027.md）**。改法：`orders_common.py:31-72` 新增 `DELETED_ORDER_NOTICES`（两句文案）／`PLAIN_NOT_FOUND_NOTICE`／`_deleted_order_notice(order, role, current)`，`_get_order_scoped` 的软删分支改用 `detail=_deleted_order_notice(...)` —— **状态码仍 404**（不改成 403/410，理由见变更单 §③：状态码差异会让司机反推出「有一张看不见的已删除单」）、非当事人仍「订单不存在」，当事人看到的改成在途「订单已被派单员删除，如需找回请联系派单员从回收站恢复。」／非在途「订单已被删除，如需找回请联系派单员从回收站恢复。」；司机端新增 `ui/order/OrderDeleted.kt`（`OrderDeleted.isDeletedNotice(message)` 认这两句 ＋ `OrderDeletedPanel(message, onBack)` 给「返回」按钮）并在 `ui/order/OrderDetailScreen.kt:236-237` 于 `ErrorView` **之前**插一支渲染它（排在后面就永远轮不到）。证据：判据 60 项（含「那一支排在 ErrorView 之前」「安卓 HINTS 与后端文案逐字相同」两族）；反验里「文案改一个字」「`Text("返回")` → `Text("重试")`」「详情页那一支删掉 ／ 挪到 ErrorView 之后」「`if not mine:` → `if False:`」四条注入都报红；改后真机由父会话在 5558 司机端补。

### TA-07 · 预订单模板表单：点「保存」后没有任何可见反馈（校验红字排在视口外，不滚动也不提示）

- 严重度：可见　／　状态：已修复 3988501　／　修复：2026-10-10（BUG-0031）　／　记录：2026-10-10 03:44 CST
- 现象：新建预订单时只填名字、不选商品，点底部「保存」后界面完全不动：没有红字、没有 toast、也没跳走，看起来像按钮坏了。把表单往下滑一段才看到那句错误就贴在「选商品」下面：「至少选一样商品 —— 预设单就是「以后照这样再下一遍」的那一单」。停在顶部时它的位置约 y≈2794，而可视区只到 y≈2252（底部按钮栏之上），等于永远看不到。
- 复现：5556/13900000011：①工作台→预订单→底栏「新建预订单」→名字填 T1-tpl-ui→点底部「保存」(577,2221)→界面无变化，库 order_templates 无新行；再下滑 540 1800→540 900 才看到红字。②同流程换名字 T1-tpl-e2，复现一次。对照：先选一件商品（赣南脐橙×1→加入清单）再点同一坐标「保存」→ 保存成功（新增 id=5），证明坐标确实在保存按钮上。
- 期望：点保存后校验提示要立刻可见：贴在保存按钮上方、或 toast/snackbar、或自动滚到出错那一行。
- 实际：错误行是表单最后一项 item { FormErrorLine(vm.error) }（排在 商品与数量 → 选商品 之后），停在表单顶部时它在视口之外；保存失败后页面不滚动、也没有 snackbar，用户得不到任何反馈。
- 证据：_tmp/test_round3/A13_tpl_save_no_feedback.txt
- 定位：`android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/OrderTemplateFormScreen.kt:199,438`
- 补充（2026-10-10，已修复）：**提交 `3988501`（变更单 docs/changes/BUG-0031.md）**。改法：OrderTemplateFormScreen.kt 的 bottomBar 里紧贴「保存」上方常驻一行 FormErrorLine(vm.error)，并把 LazyColumn 绑到 rememberLazyListState()、在 LaunchedEffect(vm.error) 里 animateScrollToItem(totalItemsCount - 1) 滚到列表末尾那一行的同款提示。校验规则与文案一字未改。证据：判据 _tools/qa/_check_template_error_visible.py 12/12（改前 6 条不成立）、反验 8/8 全红且逐字节还原、gradle :app:compileEmuDebugKotlin BUILD SUCCESSFUL。

### TA-08 · 商品列表卡的单价与改价弹窗口径不一致：0.005 在卡片上显示成 ¥0.01

- 严重度：可见　／　状态：已修复　／　记录：2026-10-10 03:44 CST　／　修复：2026-10-10（BUG-0028）
- 现象：商品 id=76（T1-prod-frac，库 default_unit_price=0.005，单位 箱）在商品管理列表卡上显示「¥0.01/箱」，点「改价」打开的弹窗里同一个价是 0.005。同一个字段两处口径不同，子分价场景下卡片显示的是真实价的两倍。
- 复现：5556/13900000011：工作台→商品管理→搜索 T1-prod-frac→卡片读到「¥0.01/箱」（库值 0.005）→点该卡「改价」(449,882)→弹窗 EditText text=0.005（dump2 佐证 box=183,1160-897,1328）。
- 期望：列表卡与弹窗/编辑页口径一致：要么都显示 0.005，要么列表也明确说明按分显示。
- 实际：列表卡按两位小数显示（¥0.01），改价弹窗/编辑页走 trimMoneyZeros 显示真值 0.005；保存链路本身没问题（输入 0.005 能原样入库）。
- 证据：_tmp/test_round3/A8_price_frac_display.txt
- 定位：`android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductsScreen.kt:669`
- 修复（BUG-0028）：商品卡的售价行改走保真到四位的 `trimMoneyZeros`（`android/app/src/main/java/com/tapmoay/sorders/ui/common/ProductCardKit.kt:180`）—— 卡片／改价弹窗／库三处同一个口径，子分价现在卡片上就是 `¥0.005/箱`；「金额显示到分、单价不许四舍五入」的分界写进了 `android/app/src/main/java/com/tapmoay/sorders/util/Money.kt` 的 KDoc。⛔ 库精度 `Numeric(14,4)` 与钱算法未动。

### TA-09 · 改价弹窗输入负数被静默过滤成正数并保存（-3 存成 3，无提示）

- 严重度：可疑　／　状态：已修复　／　记录：2026-10-10 03:44 CST　／　修复：2026-10-10（BUG-0028）
- 现象：商品改价弹窗（改默认售价）里输入 -3，输入框当场变成 3 —— 负号被输入规则悄悄丢掉，没有任何提示；点保存后库里就是 3。用户以为自己填了负价会被拦，实际存下一个自己没打算写的合法价。
- 复现：5556/13900000011：商品管理→搜 T1-prod-frac→「改价」→清空输入框→input text -3→dump2 显示 EditText text=3→点「保存」→SELECT default_unit_price FROM products WHERE id=76 → 3（随后已改回 0.005）。同一天更早一次：输入 -1 → 保存 → 库里变成 1。
- 期望：非法输入应当被拒绝并给出提示（或保留原样让用户看见自己填了什么），而不是静默改写成另一个合法值。
- 实际：InputRules.priceInput 把负号过滤掉，-3 变成 3 并被正常保存；界面全程无提示。
- 证据：_tmp/test_round3/A8_price_negative_filter.txt
- 定位：`android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductsScreen.kt:682`
- 修复（BUG-0028）：改价框不再静默改数 —— 含负号/字母的输入**原样留在框里**并当场出红字说明原因（`android/app/src/main/java/com/tapmoay/sorders/core/InputRules.kt:238-262` 的 `priceRewriteNote` ＋ `ui/dispatcher/ProductsScreen.kt:686-707` 的四步块），保存键同时变灰（`:721` 的 `enabled = !busy && priceNote == null && price.toDoubleOrNull() != null`）⇒ `-3` 现在存不进去，用户看得见自己填了什么。

### TA-10 · 联系人电话栏输入字母被静默清空，仍能保存出「没有电话」的联系人

- 严重度：可疑　／　状态：已修复　／　记录：2026-10-10 03:44 CST　／　修复：2026-10-10（BUG-0028）
- 现象：添加联系人时电话栏填 abc，点「添加」直接成功，列表里出现这条联系人，但库里 phone 是空的，没有任何校验提示。同一货主下还能再建第二条空电话联系人（UNIQUE(shipper_id, phone) 挡不住 NULL）。
- 复现：5556/13900000011：工作台→地址与联系人→「联系人」页签→「新增联系人」→称呼 T1-ct-ui / 电话 abc→「添加」→列表出现 T1-ct-ui；SELECT id,shipper_id,phone,display_name FROM shipper_contacts WHERE display_name LIKE T1-% → 47|126|(空)|T1-ct-ui。第二次 T1-ct-ui2 同样 → 48|126|(空)。
- 期望：电话格式非法应当报错或至少提示「非数字已忽略」，不该静默存成空电话。
- 实际：输入被过滤成空（NULL）后照常入库，界面无提示；列表卡只显示名字，用户看不出这条没有电话。
- 证据：_tmp/test_round3/A9_contact_phone_filter.txt
- 定位：`android/app/src/main/java/com/tapmoay/sorders/ui/shipper/AddressScreen.kt:917-921,992,1369-1374`（原记 `ui/dispatcher（联系人表单电话栏）`，实为货主端 `ui/shipper` 的联系人抽屉）
- 修复（BUG-0028）：电话栏丢字当场红字并且**不给保存**（`ui/shipper/AddressScreen.kt:917-921` ＋ `ui/shipper/AddressViewModel.kt:725-728` 的 `contactPhoneNote?.let { formError = it; return }`）；没有电话的联系人卡片上会写「无电话」（`AddressScreen.kt:1369-1374`），placeholder 改成「选填；留空＝无电话」。⛔ 本单在台账二选一里选的是「让空电话可见」而不是「唯一性对 NULL 生效」—— 同一货主仍能建两条「无电话」，代价与另选方案的代价写在 `docs/changes/BUG-0028.md` §⑥。

### TA-11 · 商品删除弹窗承诺的「列表顶端回收站」在 App 里从未实现（TA-03 第4轮复现，定级升级为堵死）

- 严重度：堵死　／　状态：已复现　／　记录：2026-10-10 10:58 CST
- 现象：商品管理里删除商品（编辑页「删 除」或 批量操作→删除）的确认弹窗都写着「列表顶端的『回收站』里可以把它恢复回来」，但商品管理列表页的顶部（搜索框/返回/标题/单位换算/排序）与底部（分类管理/商品新增/批量操作）都没有任何回收站入口；App 里也没有任何地方能列出被删商品。后端 POST /products/{id}/restore 存在，界面上却无路可走。
- 复现：1) 设备 emulator-5556 → 工作台 → 商品管理，uiautomator dump 存 _tmp/test_round4/a_xml_products_top.xml 与 a_xml_products.xml，两处都无「回收站」；2) 点某商品卡的「编辑」→ 编辑商品页（dump a_xml_prod_edit.xml）滚动到「删 除」区 → 点删除，弹窗文案即 ProductFormScreen.kt:409-412；3) 回列表页，没有回收站可进；4) 源码核对：grep 回收站 android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductsScreen.kt 零命中；data/remote/api/Apis.kt 的 listProducts 没有 deleted_only/include_deleted 参数（而订单 :186、预订单模板 :1023、供应商 :1085、付款/应付 :1109/1136/1167、计费规则 :1342、收款记录 :1672、账本/结算 :1796/1944/1976、单位换算 :2063 都有）。
- 期望：弹窗承诺了「列表顶端的回收站」，列表顶端就该有那个入口（用户 2026-09-20 硬规矩：界面要有一个手边的撤销入口，不要只把恢复藏在 AI 撤回卡里）；至少要有办法列出被删商品。
- 实际：App 侧完全没有实现：ProductsScreen.kt 零个「回收站」；listProducts 连 deleted_only 参数都没有，客户端取不回被删商品。删除后商品在界面上永久消失，只能靠后端接口手工恢复。
- 证据：_tmp/test_round4/a_evidence_sweep1.txt
- 定位：`android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductFormScreen.kt:412`　`android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductBatchScreen.kt:290`　`android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductsScreen.kt:1`

### TA-12 · 九类名册删除是物理删除、后端无 restore，App 只有删完当场那一下「撤销」（且是重建、编号会变）

- 严重度：堵死　／　状态：已复现　／　记录：2026-10-10 10:58 CST
- 现象：商品分类/联系人分类/地点分类/线路分类/运费分类/开销分类/预订单分类/账号分类/车辆分类，这九类「名册」的 DELETE 都是物理删除，行直接从库里消失；openapi 的 20 条 /restore 里一条都没有。App 侧只有删完当场那一下的撤销，而且撤销 = 按原名重建一格（新编号），不是恢复。
- 复现：python -X utf8 _tmp/test_round4/a_sweep1.py → POST /product-categories 建 id=11 → DELETE /product-categories/11 → 204 → 再读库 select * from product_categories where id=11 得 None（行没了）。源码：product_categories.py:299 db.delete(row)；contact_categories.py:224 db.execute(sa_delete(ContactCategory)...)；place_categories.py:220；route_categories.py:223；freight_categories.py:206；expense_categories.py:223；order_template_categories.py:235；user_categories.py:227；vehicle_categories.py:206。App：CategoryRostersViewModel.kt:184「重建出来的是新的一行，编号和原来不一样（名册没有回收站）」；CategoryRostersPanel.kt:168「名册是硬删（没有回收站），所以给一个当场能按回来的撤销」；AppRepository.kt:428/:459 同。
- 期望：用户 2026-09-20 定的硬规矩是「所有删除一律软删（伪装删除）＋必须有恢复路径」——名册也是用户在界面上能删的东西，同样该软删 + 有恢复入口。
- 实际：九类名册全部物理删除、无 restore 端点；界面只有删完当场的一次性撤销，离开页面即永久找不回；即便当场撤销也是重建，编号与原来不同（用户若拿旧编号对过账就对不上）。
- 证据：_tmp/test_round4/a_evidence_sweep1.txt
- 定位：`backend/app/api/v1/product_categories.py:299`　`backend/app/api/v1/contact_categories.py:224`　`backend/app/api/v1/ledger.py:603`

### TA-13 · 账本行 DELETE 是物理删除且没有 restore 端点（删钱的行只能靠审计日志手工还原）

- 严重度：堵死　／　状态：已复现　／　记录：2026-10-10 10:58 CST
- 现象：DELETE /api/v1/ledger/entries/{id} 走的是 db.delete(row)，行直接从 ledgers 表消失；openapi.json 的 20 条 /restore 里没有 /ledger/entries/{id}/restore。删除前只往 operation_logs 写一行 LEDGER_DELETE（change_payload.before 里带 entry_date/product_name/quantity/unit_price/total/source/order_id/shipper_id/note），那行日志是唯一还原线索。
- 复现：源码：backend/app/api/v1/ledger.py:566 def delete_entry → ledger.py:603 db.delete(row)；核对 http://127.0.0.1:8061/openapi.json 的 paths，带 /restore 的路径共 20 条，不含 ledger/entries。（本轮未跑到实拍：建账本行需 shipper_id 或 temp_shipper_name，POST /ledger/entries 返回 422「请指定货主账号或临时货主名称」，未重跑。）
- 期望：同文件里收款单就是软删 + 恢复的样板（DELETE /ledger/receipts/{id} 软删、POST /ledger/receipts/{id}/restore 原样放回）；账本行同样是钱，按硬规矩应当软删且有一键恢复路径。
- 实际：物理删除、无 restore 端点。掉了一行只能人去读 operation_logs 然后手工补录，补出来的是新行（新 id），与原行不是同一条。
- 证据：_tmp/test_round4/a_evidence_sweep1.txt
- 定位：`backend/app/api/v1/ledger.py:603`

### TA-14 · 常用地址恢复后丢失「默认」标记：删前是默认地址，恢复回来不再是

- 严重度：可见　／　状态：已修复 947cef9　／　修复：2026-10-10（BUG-0032）　／　记录：2026-10-10 10:58 CST
- 现象：POST /shipper/addresses/{id}/restore 只清 is_deleted/deleted_at，不还原 is_default。DELETE 时特意把它置 false（防止默认标记留在看不见的行上），恢复时没有放回来，于是「默认地址」这一格静默丢失。
- 复现：python -X utf8 _tmp/test_round4/a_sweep1.py（5b.常用地址）→ POST /shipper/addresses 带 is_default=true 建 id=26（库 is_default=1）→ DELETE /shipper/addresses/26 → 204 → 库 is_default=0 → POST /shipper/addresses/26/restore → 200 → 逐字段 diff 结果 {"is_default": [1, 0]}（同批其它实体 diff 都是 {}）。源码：shipper.py:177-186 delete_address 里 a.is_default = False；shipper.py:189-201 restore_address 只写 is_deleted=False / deleted_at=None。
- 期望：restore 是 DELETE 的逆操作，应当逐字段还原（同批 products / contacts / locations / order-templates / freight-templates / arrears-units / places 实测 diff 都是 {}）。
- 实际：恢复后 is_default 停在 false：下单页取不到默认地址、地址列表里一条带默认标记的都没有，而接口回了一张「已恢复」的成功卡。
- 证据：_tmp/test_round4/a_evidence_sweep1.txt
- 定位：`backend/app/api/v1/shipper.py:189`　`backend/app/api/v1/shipper.py:185`
- 补充（2026-10-10，已修复）：**提交 `947cef9`（变更单 docs/changes/BUG-0032.md）**。病灶：DELETE /shipper/addresses/{id} 故意把 is_default 清成 false（R11-F4：默认标记不能留在看不见的行上），而 restore_address 只把 is_deleted 放回去 ⇒ 删掉默认地址再恢复，默认就没了。改法：恢复时用 func.count() 数一下「这段期间有没有别人当上默认」（同 shipper_id、is_deleted=False、is_default=True、id != 自己），没人当才 a.is_default = True（不抢别人后来的选择）；删除路径仍清标记。证据：单测 backend/tests/test_address_default_restore.py 3 passed（去掉修复 1 failed）、判据 _tools/qa/_check_address_default_restore.py 16/16（改前 6 条不成立）、反验 6/6 全红且逐字节还原。

### TA-15 · AI 卡片说共享地点「删掉就没了、没有回收站、恢复不了」，实际后端是软删且能恢复

- 严重度：可见　／　状态：已复现　／　记录：2026-10-10 10:58 CST
- 现象：AI 写能力的卡片文案与实现相反：blurb 明说「从共享库里删掉一个地点（谁都选不到了）。删掉就没了，没有回收站。」并在 details 里写「⚠️ 恢复不了（共享库没有回收站）」；而实际后端 places.py 的 delete_place 是软删、有 POST /places/{id}/restore，App 也有 restorePlace。
- 复现：源码对照：android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteBasicData.kt:349 blurb、:356 details「恢复不了（共享库没有回收站）」；ai/AiResources.kt:122 亦称选点表「物理删除、没有回收站」。实际：backend/app/api/v1/places.py:300 delete_place（软删，注释写「软删，POST /places/{id}/restore 能拿回来」）、places.py:329 restore_place；App 侧 ui/shipper/AddressViewModel.kt:925 restorePlace、ui/shipper/OrderCreateViewModel.kt:442/464。接口实测：删 places id=65 → is_deleted 0→1，POST /places/65/restore → 200，逐字段 diff {}。
- 期望：AI 对用户说的话应当与后端实际行为一致；能恢复的就要说能恢复（用户是按这句话决定敢不敢删的）。
- 实际：AI 把「能恢复」说成「恢复不了、没有回收站」，用户可能因此不敢用它、或者以为数据已经彻底丢了，而实际上恢复入口就在手边。
- 证据：_tmp/test_round4/a_evidence_sweep1.txt
- 定位：`android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteBasicData.kt:349`　`backend/app/api/v1/places.py:329`

### TA-16 · 开销（expenses）全系统没有任何删除或修改入口：记错一笔永久留在账上

- 严重度：堵死　／　状态：已复现　／　记录：2026-10-10 10:58 CST
- 现象：开销只有 GET 与 POST 两个端点，没有 DELETE 也没有 PATCH/PUT；App 侧没有任何 deleteExpense 调用，开销列表页里连一个删除/撤销的字样都没有。金额写错或记重一笔之后，用户没有任何办法撤掉它。
- 复现：1) DELETE /api/v1/expenses/54 → 404 Not Found；DELETE /api/v1/expenses/1 → 404（同批 DELETE /vehicles/1 返回 405，说明这不是路由前缀问题）；2) http://127.0.0.1:8061/openapi.json 里 /api/v1/expenses 只有 get/post，/api/v1/expenses/{id} 这个路径不存在；3) backend/app/api/v1/expenses.py 全文只有 @router.get("") 与 @router.post("")(expenses.py:20 / :79)；表 expenses 的 PRAGMA table_info 里没有 is_deleted/deleted_at；4) android/app/src/main/java/com/tapmoay/sorders/data/remote/api/Apis.kt:1582 @GET("expenses") / :1598 @POST("expenses")，全工程 grep deleteExpense 零命中；ui/dispatcher/ExpensesScreen.kt 里 删/撤销/delete 零命中。
- 期望：用户 2026-09-20 定的是「所有删除一律软删 + 必须有恢复路径」——先有删除才有恢复；同一套账里的账本行、收款单、供应商付款、结算单都有删除/撤销路径，开销不该是唯一没有出路的。
- 实际：开销进了库就再也动不了：金额填错、记重一笔都只能永久留在账上并进入成本与报表。界面上也没有一句「记错了怎么办」的说明。
- 证据：_tmp/test_round4/a_evidence_sweep1.txt
- 定位：`backend/app/api/v1/expenses.py:17`　`android/app/src/main/java/com/tapmoay/sorders/data/remote/api/Apis.kt:1598`
- 补充（2026-10-10，已修复）：`expenses` 挂软删（`is_deleted` / `deleted_at` ＋ `schema_bootstrap.py` 幂等自愈段补列 ＋ `ix_expenses_is_deleted` ＋ 回填 0）；新增 `DELETE /api/v1/expenses/{id}`（204 软删：开销单与它写下的那条 `cash_flows`（`party_type="expense"` ＋ `party_id`）一起打标记，审计 `EXPENSE_DELETE`）与 `POST /api/v1/expenses/{id}/restore`（200 原样放回，审计 `EXPENSE_RESTORE`）；五处取数处（分类名册在用笔数 / 名册外兜底 / 删分类守卫、利润表期间费用、车辆成本表开销桶、报表导出、回填脚本）全部排除已撤销；`GET /expenses` 加 `deleted_only` 二选一档；App 开销页行上「撤销」（二次确认）＋ 标题栏「显示已撤销」档里的「恢复」＋ 撤销后 snackbar「撤回」。⛔ 金额算法一个字节没改：撤销后 利润表期间费用 / 车辆成本表窗口开销 / 收支页 三处合计都满足「删前 − 这一笔 = 删后」。证据：判据 `_tools/finance/_check_expense_soft_delete.py` 78 项 ＋ 反验 19 条注入全红且逐字节还原 ＋ `backend/tests/test_expense_soft_delete.py` 10 passed；提交 `4beb4be`。`

### TA-17 · 客户合并把被并档案物理删除，不可逆（customers 表连软删列都没有）

- 严重度：可疑　／　状态：已复现　／　记录：2026-10-10 10:58 CST
- 现象：POST /api/v1/customers/merge 把引用搬到保留的那一条上，然后把被并档案从库里物理删除；customers 表没有 is_deleted/deleted_at，删除不可逆。源码注释自陈这一点。
- 复现：源码：backend/app/api/v1/customers.py:110-111 注释「合并做的是『把引用搬到 keep 上，然后把被并档案物理删除』（customers 表连 is_deleted 都没有，不可逆）」；customers.py:219 db.delete(m)。库结构：PRAGMA table_info(customers) 共 10 列（id, kind, user_id, name, phone, is_member, arrears_unit_id, created_at, updated_at, tmp_phone_key），无软删列。openapi 里客户域只有 GET / POST / POST /merge，没有 restore。
- 期望：合并是「把两个档案并成一个」，被并方通常还需要事后查得到「它当时并到谁那里去了」；按硬规矩删除应当软删 + 可恢复。
- 实际：被并的那一行直接从库里消失，只留下 operation_logs 里一行审计；没有撤回、没有恢复端点、表结构也不支持软删。
- 证据：_tmp/test_round4/a_evidence_sweep1.txt
- 定位：`backend/app/api/v1/customers.py:219`　`backend/app/api/v1/customers.py:110`

### TA-18 · 车辆与客户没有任何删除入口（车只能停用、客户档案无法清理）

- 严重度：可疑　／　状态：已复现　／　记录：2026-10-10 10:58 CST
- 现象：车辆与客户这两个实体连 DELETE 路由都没有：车辆只能改 is_active 停用（车仍然留在列表里），客户档案一旦建出来就无法清理。
- 复现：1) DELETE /api/v1/vehicles/1 → 405 Method Not Allowed；DELETE /api/v1/customers/1 → 404 Not Found；2) 源码 backend/app/api/v1/vehicles.py 只有 GET "" / POST "" / PATCH "/{vehicle_id}" / POST "/{vehicle_id}/driver"；backend/app/api/v1/customers.py 只有 GET "" / POST "" / POST "/merge"；3) 表 vehicles 有 is_active（PRAGMA 22 列），customers 连状态位都没有。
- 期望：能建的档案就应当有「删除 + 恢复」这一对（用户 2026-09-20 硬规矩）；即便有意不提供删除，界面也该给出「停用/归档」的明确出路。
- 实际：车辆只能停用，客户完全没有出路。这与「所有删除一律软删 + 有恢复路径」是另一面：这两类根本没有删除。
- 证据：_tmp/test_round4/a_evidence_sweep1.txt
- 定位：`backend/app/api/v1/vehicles.py:281`　`backend/app/api/v1/customers.py:26`

### TA-19 · 司机备注（driver-note）零推送：派单员端订单详情停在旧「内部备注」，无提示不刷新

- 严重度：可见　／　状态：已复现　／　记录：2026-10-10 11:08 CST
- 现象：司机在司机端写现场备注后，后端只把文本以「[司机 时间] 」前缀追加进 orders.internal_notes，全程没有 outbox 事件、没有站内信、Socket.IO 一条消息都不发；派单员端已经打开的订单详情页永远停在旧值，页面上没有任何提示，只有手动退出再进入该单才会看到新备注。同类家族：TA-05/BUG-0027（软删恢复不发推送）、BUG-0026（推送打断取数）。
- 复现：① 5556（派单员 13900000011）在 8059 上打开订单详情：工作台→订单管理→搜索框输单号→点搜索（页签要先切「全部」，默认「派单中」搜不到）；本会话用订单 648 SO202610107870773368。② 用该单司机账号（13900000017）POST http://127.0.0.1:8059/api/v1/orders/648/driver-note，请求体 note=A4推送-司机现场备注(设备验证) → HTTP 200。③ 动作前后 select max(id) from outbox_events 都是 1096（零新增）；等 6 秒后 5556 详情页仍无「内部备注」行，adb -s emulator-5556 logcat -d -s SOrdersSock SOrdersAlert 本次窗口零输出。④ 返回列表再点开同一单 → 出现「内部备注 / [司机 10-10 11:03] A4推送-司机现场备注(设备验证)」。
- 期望：司机备注是订单详情里对派单员/货主都可见的字段（OrderDetailScreen.kt:1151 的「内部备注」行），写完后正在看这一单的派单员应当收到一条 order.updated 类实时事件并刷新，或至少有「有更新」的提示。
- 实际：写入只改 orders.internal_notes（orders id=648 updated_at 2026-10-10 03:03:07.944453），outbox_events 无新增、Socket.IO 无事件、派单员端界面与像素都不变（截图 201829 → 201858 字节）且无任何提示；手动重进才显示。
- 证据：_tmp/test_round4/shots/f1_detail_before.png;_tmp/test_round4/shots/f1_detail_after_push.png;_tmp/test_round4/shots/f1_detail_after_manual_refresh.png;_tmp/test_round4/push_f1.py;_tmp/test_round4/push_matrix_8062_order2.json
- 定位：`backend/app/api/v1/orders_delivery.py:125`

### TA-20 · 商品/价格/库存/开销/结算/车辆等主数据写操作零推送：没有任何一端会收到变更通知

- 严重度：可疑　／　状态：已复现　／　记录：2026-10-10 11:08 CST
- 现象：products / price-rules / shipper-prices / inventory movements / expenses / driver-settlements / vehicles / users 这些模块的写端点全部不写 outbox（全仓库只有 8 个 api/v1 文件带 outbox），客户端也没有订阅这些域的刷新信号：另一台设备（另一个派单员、或货主端下单页）看到的价格/库存/结算状态只会因为自己手动重新进入页面才变。
- 复现：在 8062 沙箱（库 sorders_r4b.db，脚本 _tmp/test_round4/push_scen.py master / master2）逐条执行并读 outbox 增量：POST /products 201、PATCH /products/{id} 改价 200 / 下架 200 / 上架 200、POST /price-rules 201 + PATCH 200 + DELETE 204、POST /inventory/movements 201（含负数量出库）、POST /expenses 200、PATCH /driver-settlements/{id} action=confirm 200 + pay 200、PATCH /vehicles/{id} 改 driver_id 200、PATCH /users/{id} 改名 200、DELETE /products/{id} 204 + restore 200 —— 每一步 select max(id) from outbox_events 都不变（结果存 push_matrix_8062_master*.json）。
- 期望：若这些改动会影响另一端正在看的数字（例如货主下单页展示的商品价格与库存、另一台派单员的商品/库存列表），应有实时事件，或明确「以刷新后为准」的提示；不该出现「一个人改了、另一个人屏幕上还是旧数」的沉默差。
- 实际：全部零事件、零站内信；服务端数据确实变了（库里价格/库存/结算状态都已更新），但没有任何一端被通知。本轮只能在 8062 沙箱证明「没有推送通道」，未能观测用户实际损失（货主端设备本轮不可用：5554 不许碰、5556 是派单员、5558 是司机），故严重度记「可疑」而不是「错数」。
- 证据：_tmp/test_round4/push_matrix_8062_master.json;_tmp/test_round4/push_matrix_8062_master2.json;_tmp/test_round4/push_scen.py
- 定位：`backend/app/api/v1/products.py:130`

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

### TB-08 · 同一笔司机明细能被两张草稿结算单同时锁住：冲突到确认时才报，且报错把「被占用」与「已删除」糊成一句

- 严重度：可疑　／　状态：**已修复 9744177**　／　记录：2026-10-10 02:57 CST
- 现象：driver_settlements.py:93 的注释写「建结算单＝把一批「待结」明细锁进一张单子（钱虽未出，但已经不能再被第二张单占用）」，实测同一司机同一月连续建两张草稿单 #59/#60，两张的 bill_ids 都是 [12]、amount 都是 22.00，而被锁的明细 id=12 仍是 open / settled_doc_id 为空。确认 #59 之后再确认 #60 才被拦下，报错是「这张结算单锁定的 1 笔明细里有 1 笔已经不在了（被删除或已被别的结算单占用），请作废后重新结算」——用户分不清是明细被删了还是被别的单占了。钱不会重复付（守卫有效，cash_flows 里只有 #59 那一笔）。
- 复现：账号 13900000001（派单员，8020 副本库）：1) POST /api/v1/driver-settlements {"driver_id":3,"settle_type":"piece","month":"2026-06"} 连做两次 → 200 id=59 与 id=60，两者 bill_ids 都是 [12]、amount 22.00；2) PATCH /api/v1/driver-settlements/59 {"action":"confirm"} → 200 confirmed，明细 12 变 settled/settled_doc=59；3) PATCH /api/v1/driver-settlements/60 {"action":"confirm"} → 400（上句原文）；4) PATCH /api/v1/driver-settlements/60 {"action":"cancel"} → 200 收尾。脚本 _tmp/test_round3/t3b_close.py、t3c_guard.py、ev_tb08.py。
- 期望：要么建单时就把明细标成「已被某张草稿单占用」并让第二张单建不出来（注释所写），要么列表页明确标出「这笔明细同时挂在 N 张草稿单上」；确认失败时应把「被别的结算单占用」与「明细已删除」拆成两句，别让用户以为明细被删了。
- 实际：两张草稿单同时占用同一笔明细；确认第二张时才报错，且错误措辞把两种成因混在一句里；草稿单列表照原样显示两张都能结同一笔钱。
- 证据：_tmp/test_round3/evidence_TB08_settlement_dup.txt（含两次建单回执、确认被拦的 400 原文、SQL 行）；_tmp/test_round3/t3_out/t3b_log.json、t3c_log.json
- 建议改法：create_settlement 里对 settleable_bills 加占用检查（或给 driver_bills 加 draft_doc_id 字段锁草稿），confirm 的报错拆成「被别的结算单占用」/「明细已删除」两种；草稿单列表把重复占用标出来。
- 定位：`backend/app/api/v1/driver_settlements.py:93`　`backend/app/services/accounting_service.py:611`　`backend/app/services/accounting_service.py:661`　`backend/app/services/accounting_service.py:570`
- 补充（2026-10-10，已修复）：**提交 `9744177`（变更单 docs/changes/BUG-0024.md）**。改法：① 锁复用已有列 `driver_bills.settled_doc_id` —— `create_settlement` 在 `db.add(s)` 之后 `db.flush()` 拿 id，再逐行写 `b.settled_doc_id = s.id`（状态仍是 `open`，钱未出）⇒ 注释里那句「已经不能再被第二张单占用」在建单当刻真的发生；`settleable_bills` 新增 `doc_id` / `include_claimed` 两个关键字口子，**默认只取「没人锁的」**（`DriverBill.settled_doc_id.is_(None)`），确认时传 `doc_id=s.id` 把本单自己锁住的算回来。② 建单时若这个月的待结明细都被别的单锁着 ⇒ 400 并点名：「2026-06 的 1 笔待结明细已经被别的结算单锁住了（明细 12 在结算单 #57（草稿））；请先作废那张单再来建单，本单未创建」。③ 确认的报错按成因分句（新增模块级 `_why_gone` 三分桶：被别的结算单占用 / 已被删除 / 已不是待结状态；`_settlement_label` 把单号翻成「#57（草稿）」，`_claimed_where` 点名单号），保留「已经不在了」与「请作废后重新结算」两个既有锚点，糊成一句的老话从文件里消失。④ 作废解锁从「只放回 SETTLED」扩成 `settled_doc_id == s.id` 且 `status ∈ {settled, open}`（⛔ 不含 `cancelled` —— 保留任务作废的明细不复活）。⑤ `backend/app/api/v1/driver_settlements.py:93` 的注释与行为对齐（扩写「锁落在哪一列、状态是什么、谁解锁、为什么要 flush」）。证据：单测 `backend/tests/test_settlement_locking.py` 7 条（改前在 HEAD 干净副本里 **5 failed / 2 passed**，改后 7 passed、与既有 8 条合计 15 passed）；判据 `_tools/finance/_check_settlement_locking.py` **39 项全过**；反验 `_tools/finance/_reverse_verify_settlement_locking.py` **24/24 都红了**＋逐字节还原；现场 8032（HEAD 副本 = 改前：两张草稿单都 200、`bill_ids` 都是 `[12]`、明细仍 open）／8033（工作树 = 改后：第一张 200、第二张 **400** 点名单号；确认报错分因）—— `_tmp/tb08/live_before.txt` ／ `_tmp/tb08/live_after.txt`。

### TB-09 · 客户收款登记之后没有任何撤销/红冲入口：报错文案让用户「联系管理员在账上冲正」，而管理员也没有这个入口

- 严重度：可疑　／　状态：**已修复 6809393**　／　记录：2026-10-10 03:03 CST
- 现象：派单员在账本里登记一笔客户收款（POST /api/v1/ledger/receipts）会一次写三处：shipper_receipts 一行 + cash_flows(RECEIPT_CASH) 一行 + 把 orders.paid 翻成 true。登记错了之后**接口与 App 都没有任何撤销入口**：DELETE/PATCH /api/v1/ledger/receipts/{id} → 404，POST /api/v1/ledger/receipts/{id}/restore 与 /cancel → 404，DELETE /api/v1/cash-flows/{id} 与 POST /api/v1/cash-flows/{id}/restore → 404（openapi 里 /api/v1/cash-flows 只有 get、/api/v1/ledger/receipts 只有 get,post）。而 cash_flows 表本身有 is_deleted/deleted_at 两列、供应商付款那条路就有 DELETE /api/v1/supplier-payments/{flow_id} + POST /{flow_id}/restore ⇒ 同一张表在客户收款这条路上没有撤销。系统自己知道：backend/app/api/v1/orders_payment.py:199 的报错原文写「系统目前**没有撤销收款的入口**…如果这笔收款记错了，请联系管理员在账上冲正」——但「管理员」也没有任何入口（没有反向分录端点、没有收款单删除）。后果：一笔记错的收款永久留在「已收」里（营业额 collected 增加、挂账 arrears 减少、资金收支 income 增加），只能靠把货退掉（REFUND_CUSTOMER 退现）或直接改库来纠正。
- 复现：账号 13900000001（派单员，8020 副本库 sorders_a3.db，HEAD b07e7ad）：1) POST /api/v1/ledger/receipts {"customer_id":28,"amount":"147.30","method":"cash","received_at":"2026-10-10","order_ids":[597],"settle_mode":"itemized"} → 200 收款单 id=37，cash_flows id=94 biz_type=RECEIPT_CASH amount=147.3 doc_id=37，orders.paid=true；2) 依次 DELETE/PATCH /api/v1/ledger/receipts/37、POST /api/v1/ledger/receipts/37/restore、POST /api/v1/ledger/receipts/37/cancel、DELETE /api/v1/cash-flows/94、POST /api/v1/cash-flows/94/restore → **全部 404 {"detail":"Not Found"}**；3) 对照会计口径的变化：cash-flows/summary income 1032.10→1179.40、/reports/turnover collected 585.90→733.20 且 arrears_total 1336.40→1189.10、customer-balances totals.balance 72504.40→72357.10、orders/597 paid=true。脚本 _tmp/test_round3/t6b.py、t6c.py、ev_tb09.py（可重跑）。
- 期望：要么给撤销入口（软删 cash_flows + 删/作废 shipper_receipts + 回滚 orders.paid/payment_method，全部留痕），要么在**收款之前**就明示「收款登记不可撤销」；⛔ 至少不要把用户指向一条不存在的路（「联系管理员在账上冲正」——管理员在系统里同样没有入口）。
- 实际：三个层级（收款单、现金流水、订单标记）都没有撤销端点，App 账本中心也只有 listReceipts/createReceipt；报错文案承诺的「管理员冲正」在系统里不存在；一笔记错的收款只能靠退货退现或直接改库纠正。
- 证据：_tmp/test_round3/evidence_TB09_receipt_no_undo.txt（逐条 404 原文 ＋ SQL 行 ＋ orders_payment.py 文案）；_tmp/test_round3/t6_out/t6c_log.json
- 建议改法：加 POST /api/v1/ledger/receipts/{id}/cancel（软删对应 cash_flows、回收 shipper_receipts、把 orders.paid 与 payment_method 回滚到收款前，写 LEDGER/RECEIPT 留痕）；或者若产品决定不可撤销，就把 orders_payment.py 那句改成「收款登记不可撤销，请谨慎核对」并去掉「联系管理员」。
- 定位：`backend/app/api/v1/ledger.py:734`　`backend/app/api/v1/ledger.py:814`　`backend/app/api/v1/cash_flows.py:54`　`backend/app/api/v1/orders_payment.py:195-201`　`backend/app/services/accounting_service.py:355`　`android/app/src/main/java/com/tapmoay/sorders/data/remote/api/Apis.kt:1668-1674`
- 补充（2026-10-10，已修复）：**提交 `6809393`（变更单 docs/changes/BUG-0029.md）**。改法：① `shipper_receipts` 挂 `SoftDeleteMixin`（`is_deleted` / `deleted_at`）＋ `backend/app/core/schema_bootstrap.py` 幂等 DDL（补两列 ＋ `ix_shipper_receipts_is_deleted` ＋ 回填 `is_deleted = 0`）；② 新增 `DELETE /api/v1/ledger/receipts/{receipt_id}`（204）与 `POST /api/v1/ledger/receipts/{receipt_id}/restore`（200）：撤销**一次把四个落点一起回滚** —— 这笔收款写下的资金流水逐行软删（判据只有一处：`doc_id == 收款单 id` 且 `party_type == customer` 且 `biz_type ∈ {RECEIPT_CASH, RECEIPT_TRANSFER, RECEIPT_ARREARS}`）、被核销且此刻仍是 `paid=true` 的订单收回未收款（`paid=false` ＋ `payment_method="arrears"`）、收款单软删；`turnover` 的 collected/arrears 与 `customer-balances` 由前两者算出来，跟着一起回去。恢复的四道门（订单不存在 / 在回收站 / 已撤销或已退货 / 现在已是「已收款」）**都在改数之前**判完并点名单号；③ `GET /ledger/receipts` 默认过滤 `is_deleted` ＋ 出参 `is_deleted`/`deleted_at`，`include_deleted=true` 是回收站档（界面「恢复」的落点）；④ 两个审计码 `RECEIPT_CANCEL` / `RECEIPT_RESTORE`（各写一条 `operation_logs`，与写入同事务）＋ `ui/dispatcher/ReportCenter.kt::actionLabel` 的「撤销收款」/「恢复收款」；⑤ App：`ui/dispatcher/AccountToolsScreens.kt` 收款记录每行「撤销」（二次确认弹层 ＋ 撤销后 snackbar 自带「撤回」→ 恢复）＋ 标题行右侧「显示已撤销／只看未撤销」档里的「恢复」（**手边入口，不是只藏在 AI 撤回卡里** —— 用户 2026-09-20 硬规矩第④条）。⛔ **没动**：`accounting_service.create_receipt` 的金额校验与两档 `settle_mode`、`cash_flows` 的逐单生成规则、任何金额字段、结算与司机账单；两处收款读取（`api/v1/arrears.py:243` 挂账单位占用计数、`api/v1/customers.py:154` 客户合并搬迁）**刻意不过滤** `is_deleted`（那一行还在库里、还指着那些对象）。AI 侧本轮不开放：两个端点在 `_tools/ai/_write_coverage.py` 的 `EXCLUDED` 里各有一条**排期**理由，同时 `ai/AiRevert.kt` 里那句「收款一旦入账，撤回来等于把账抹掉」改成指向真实入口（那句话在本单之后是假话）。证据：单测 `backend/tests/test_receipt_undo.py` 7 条（改前 `_tmp/test_round3/red_receipt_undo.txt` = **7 failed（全是 404）**；改后 `green_receipt_undo.txt` = **7 passed**，含四个落点三组数：收款后 collected=100.00/arrears=0/income=100.00/balance=0.00 且 `paid=True` → 撤销后 collected=0.00/arrears=100.00/income=0/balance=100.00 且 `paid=False`、收款单与流水 `is_deleted=1` → 再恢复后逐项回到第一组）；判据 `_tools/finance/_check_receipt_undo.py` **70 项全过**；反验 `_tools/finance/_reverse_verify_receipt_undo.py` 逐条注入全红 ＋ 末尾逐字节还原并读回核对；`_tools/ai/_write_coverage.py --check` 与 `_tools/ai/_check_action_labels.py` 都 `EXIT=0`。⚠️ 真机（5556 货主端 / 5558 司机端同屏对账）由父会话补。


### TB-10 · 账本行的「合计」能写成与 数量×单价 不符的值：AI「改合计金额」只传 total，落库后同一行两个答案

- 严重度：可疑　／　状态：已复现　／　记录：2026-10-10 03:03 CST
- 现象：手工记账建的行（quantity=3、unit_price=20.00，total 自动为 60.0000）再用 PATCH /api/v1/ledger/entries/{id} 只给 {"total":"288.00"} → 200 落库，库里该行 quantity=3 / unit_price=20 / total=288，而 quantity×unit_price=60 —— 同一行两个答案。账本账户与欠款口径**按 total 走**（Shipper 账户 total 200.0000→488.0000）；界面把这行的数量/单价/合计三个数并排显示，也没有任何不一致标记。写入点 backend/app/api/v1/ledger.py:464-467 是显式设计：给了 total 就用 total，否则才 unit_price × quantity。危险在于用户唯一能造出这种行的路径是 AI —— android/.../ai/AiWriteLedgerHandlers.kt:130-133 的「合计金额」参数（new_amount）只把 total 放进 payload、不动 quantity/unit_price（:161 的能力提示原文「可以改：合计金额、数量、单价、日期、摘要、备注」），而人工界面**不提供**改账本行的入口（repo.updateLedger 全仓唯一调用点 AiWriteDataSource.kt:628）。对照：对 source=ORDER 的行（订单 597 的 ledger id=970）只改 total 会被已送达闸挡下（400），所以回写订单行那条路在 HEAD 上对已送达/已退货单不可达 —— 本条只针对 MANUAL 行。
- 复现：账号 13900000001（派单员，8020 副本库）：1) POST /api/v1/ledger/entries {"entry_date":"2026-10-10","product_name":"TR3-total逸出","shipper_id":2,"quantity":3,"unit_price":"20.00","source":"manual"} → 201 id=976，total=60.0000；2) PATCH /api/v1/ledger/entries/976 {"total":"288.00"} → 200；3) SQL：ledgers 行 quantity=3/unit_price=20/total=288；GET /api/v1/ledger/accounts?date_from=2026-10-01&date_to=2026-10-31 → Shipper 账户 total 200.0000→488.0000（按 288 计）；4) 对照 ORDER 行：PATCH /api/v1/ledger/entries/970 {"total":"999.00"} → 400「这张单已送达，账上这笔钱已经定了…」；5) 清理 DELETE /api/v1/ledger/entries/976 → 204。脚本 _tmp/test_round3/ev_tb10.py（可重跑）、t6a2.py。
- 期望：改「合计」时要么同步单价（让 数量×单价 == 合计 恒成立），要么把这种行显式标成「整行金额（与数量×单价无关）」并在界面/导出上标出来；至少 AI 的「改合计金额」卡片应当说清「只改合计，数量×单价 不会跟着变」。
- 实际：200 落库，账户/欠款按 total 计，行内 数量×单价 与 合计 永久不一致，界面与 AI 都不提示；写审计只记 before/after 的三个数，事后能看出不一致但没有任何一处会拦下它。
- 证据：_tmp/test_round3/evidence_TB10_ledger_total_escape.txt（建行/改合计/账户前后/ORDER 行反例/SQL 行）；_tmp/test_round3/t6_out/t6a2_log.json
- 建议改法：LedgerUpdate 在只给 total 时同步 unit_price = total / quantity（或加 total_override 标记并在列表/导出显示）；AI 卡片对「只改合计」加一句三数会不一致的提示。
- 定位：`backend/app/api/v1/ledger.py:464-467`　`android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteLedgerHandlers.kt:130-133`　`android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteLedgerHandlers.kt:161`　`android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteDataSource.kt:628`

- 补充（2026-10-10，已修复）：**提交 `47ccdf0`（变更单 docs/changes/BUG-0025.md）**。改法：合计的算法收成**唯一**一处 `resolve_line_total`（`backend/app/api/v1/ledger.py:141-182`，配 `_money` `:136-139`）—— 手工行（source=MANUAL）的合计必须 ≡ 数量 × 单价，不一致就 **400**，文案把两个数都报出来（「这一行是 数量 3 × 单价 20.00 = 60.00，与你给的 合计 288.00 不一致」＋「要改合计，请同时把数量或单价改成乘积等于它的值（例如 数量 1、单价 288.00 —— 记一整笔金额就这么写）」）；`create_entry`（`:382-383`）与 `update_entry`（`:519-521`）都改成调它，**创建路径同样收口**（POST 带不一致的 total 也 400）。⚠️ 台账「建议改法」里那条 `unit_price = total / quantity` 没采用 —— 那会凭空造出用户没说的单价（折扣抹零场景更错），改成要求一致、由人自己写清楚。订单来的行（source=ORDER）仍按订单行金额记、那一支没变；「已送达」闸 `_reject_if_order_closed`（`:97-134`）与「只改备注或摘要绝不动钱」那道闸都没碰。⛔ 没加 `allow_total_mismatch` 这类旁路、没动表/模型/迁移、没回填历史行、没动 Android。判据 `_tools/finance/_check_ledger_total_consistency.py` ＋ 反验 `_tools/finance/_reverse_verify_ledger_total_consistency.py` ＋ 单测 `backend/tests/test_ledger_total_consistency.py`（改前 2 failed / 4 passed）。现场证据：`_tmp/test_round3/fix_TB10_live_改前.txt`（8031：只改合计 → 200、账户 7259.9000→7547.9000）／`_tmp/test_round3/fix_TB10_live_改后.txt`（8032：同一步 → 400、同时给数量与单价 → 200、账户只 +60）。

### TB-11 · AI 写留痕可以被任何登录客户端（乃至人手工）伪造：X-SOrders-Origin / X-SOrders-Ai-Action 两个头不做授权

- 严重度：可疑　／　状态：已复现　／　记录：2026-10-10 03:04 CST
- 现象：后端判断「这次写是 AI 干的」只看请求头 X-SOrders-Origin: ai（backend/app/core/client_origin.py:30），动作名看 X-SOrders-Ai-Action（:38），而 core/ai_operation.py:24 自己写明「**不做授权**：X-SOrders-Origin / X-SOrders-Ai-Action 都是客户端可控的」。我拿一个普通登录账号（13900000001 派单员）在 POST /api/v1/ledger/entries 上手工带上这两个头（actions 头写 ledger_create，实际是人发的请求），后端照单全收：operation_logs 新增一行 id=2315 action=LEDGER_CREATE **origin=ai** request_id=6dba57027151；GET /api/v1/ai/operations 里出现 id=165 {user_id:126, action:"ledger_create", method:POST, path:/api/v1/ledger/entries, status_code:201, ok:true, user_name:"Dispatcher_TR3"} —— UI/审计上它就是一条「AI 写的」记录；而 backend/app/api/v1/ai_telemetry.py:8 明说指标 sorders_ai_write_confirmed_today 是「后端从库里数（operation_logs.origin = ai）」（该表当前 origin=ai 共 38 行）。影响面：AI 写审计与 AI 写入指标的可信度（不是金额算错）——任何已登录用户都能给自己的写请求贴上「AI 干的」标签，也能反过来掩盖真实的 AI 写入。
- 复现：账号 13900000001（派单员，8020 副本库 sorders_a3.db，HEAD b07e7ad）：POST http://127.0.0.1:8020/api/v1/ledger/entries，Header 加 X-SOrders-Origin: ai 与 X-SOrders-Ai-Action: ledger_create，body {"entry_date":"2026-10-10","product_name":"TR3-AI头探针","shipper_id":2,"quantity":1,"unit_price":"1.00","source":"manual"} → 201 id=976（正常写入，权限照旧按 human 判）；随后 SQL 查 operation_logs（select id, action, origin, request_id from operation_logs order by id desc limit 3）看到该行 origin=ai；GET /api/v1/ai/operations → 该请求以 action=ledger_create/ok=true 出现；清理 DELETE /api/v1/ledger/entries/976 → 204（审计行保留）。脚本 _tmp/test_round3/t8a_ai_header.py（可重跑）。
- 期望：要么把这两个头纳入服务端校验（例如只认 App 端签发的短时令牌/与登录设备绑定），要么在文档与 UI 上明确「origin=ai 与 AI 写入指标不是可信审计，只是客户端自报」；至少不要让它成为唯一的区分依据（ai_operation.py:7 原文就是「唯一区分得出来的是请求头 X-SOrders-Origin: ai」）。
- 实际：两个头无授权、无签名、无白名单，任意登录客户端（含 curl / 脚本）带上即生效：写请求被记成 origin=ai，并出现在 GET /api/v1/ai/operations 与 sorders_ai_write_confirmed_today 这个从库里数的指标里；代码注释承认这是已知取舍（「不做授权…客户端可控」）。
- 证据：_tmp/test_round3/ai_out/ai_header_probe.txt（请求原文 ＋ operation_logs/SQL 行 ＋ /ai/operations 返回 ＋ 清理）；脚本 _tmp/test_round3/t8a_ai_header.py
- 建议改法：若要可信留痕：App 落库写请求时由服务端在登录会话上打标（例如登录时下发 per-session 标记，或写请求走一次性 ticket），不要只信客户端请求头；或者把该指标改名为「客户端自报的 AI 写入数」并在 UI 注明不可信。
- 定位：`backend/app/core/ai_operation.py:24`　`backend/app/core/ai_operation.py:7`　`backend/app/core/client_origin.py:30`　`backend/app/core/client_origin.py:38`　`backend/app/core/metrics.py:246-249`　`backend/app/api/v1/ai_telemetry.py:8`　`backend/app/api/v1/ai_operations.py`

### TB-12 · 部分核销的收款单撤销后再恢复：订单一付款标志被误翻成已收款（剩余欠款再也收不进来）

- 严重度：堵死　／　状态：已修复 d3b4e37　／　修复：2026-10-10（BUG-0033）　／　记录：2026-10-10 10:58 CST
- 现象：一张已送达、只欠 124.00 的挂账单，用「按商品核销」收了 75.00 后订单仍是未收款（对）；把这张收款单撤销、再恢复，订单立刻变成 paid=1/payment_method=cash，但同一响应里 arrears_amount 还是 49.00、settled_amount 只有 75.00 —— 一张单同时说自己已收清、又还欠 49。副作用：①剩余 49 元再也收不进来（逐单核销接口 400「已经收过款了…不能重复收款」，只能走不绑单的「滚动收款」，这 49 会永久挂在单上）；②挂账单位汇总报表（/reports/arrears-summary）按 paid=False 过滤，这张还欠 49 的单整条消失（金额少 124.00 而不是 49.00），与营业额的 arrears_total（仍含这 49）分叉。
- 复现：① 建一张已送达未收款的单（本例 orders.id=644，货值 124.00）；② POST /api/v1/ledger/receipts {customer_id:41, amount:75.00, method:cash, order_ids:[644], order_product_ids:[1203], settle_mode:itemized, received_at:2026-10-10} → 200，receipt id=38，此时 GET /api/v1/orders/644 仍是 paid=false、arrears_amount=49.00（正确）；③ DELETE /api/v1/ledger/receipts/38 → 204；④ POST /api/v1/ledger/receipts/38/restore → 200；⑤ GET /api/v1/orders/644 → paid=true、payment_method=cash、settled_amount=75.00、arrears_amount=49.00（自相矛盾）；⑥ 再 POST /api/v1/ledger/receipts 收剩余 49（整单或按行两种写法）→ 均 400「已经收过款了…」。整单核销的收款单（receipt id=37）同样三步走完全对称，不触发。
- 期望：恢复收款单只应恢复它自己的流水与收款单，并按 create_receipt 的同一判据决定本次是否结清这张单：仅当该单已收金额 >= 应收（settling）才 paid=True。部分核销恢复后订单应仍是 paid=false、arrears_amount=49.00，剩余 49 可以用逐单核销正常收。
- 实际：恢复端点无条件把所选订单翻成已收款：backend/app/api/v1/ledger.py:1142-1145 or oid in order_ids: o.paid = True; o.payment_method = ...，缺 settling 判据（对照 backend/app/services/accounting_service.py:482 settling = [oid for oid in order_ids if per_order[oid] >= money[oid].arrears]）。恢复时其余 50 个变化键都正确回补（turnover.day.collected 248→323、cash.sum.day.income 124→199、custbal balance 72658.40→72583.40、ship.ledger.unpaid 248→173、turnover.day.arrears_total 154→79），唯一分叉是 paid 标志与由它派生的挂账单位汇总（arrears-summary [sum].amount 1490.4→1366.4、count 15→14）。
- 证据：_tmp/test_round4/runlog/receipt644_restore_partial_BUG.json
- 定位：`backend/app/api/v1/ledger.py:1142-1145`
- 补充（2026-10-10，已修复）：**提交 `d3b4e37`（变更单 docs/changes/BUG-0033.md）**。改法：恢复分支先取「撤销那一步翻过哪几张单」——审计 RECEIPT_CANCEL 的 payload.orders_rolled_back（新函数 _cancel_rolled_orders，按 receipt_id 精确匹配），只把**名单里**的订单翻回已收款；撤销时没翻过的（按商品部分核销、本来就还没收清）一个字段都不动。找不到名单时返回空集（不翻）——宁可让用户再收一次，也不要「欠着钱却显示已收」。创建侧的 settling 判据、撤销侧行为、恢复的四道门、出参与表结构一律未动。证据：单测 backend/tests/test_receipt_partial_restore.py 3 passed（拿掉闸门 → 1 failed，断言逐字「恢复把还欠着 40 的单翻成了已收款（TB-12：这 40 永远收不回来）」）、BUG-0029 老用例两文件 10 passed、判据 _tools/finance/_check_receipt_restore_settling.py 18/18（改前源码上 8 条不成立）、反验 7/7 全红且逐字节还原。

### TB-13 · 销项票挂不上「送达自动记账」的应收行：ledgers.customer_id 全仓没有写入入口，报错却让人去账本里补客户

- 严重度：可疑　／　状态：已复现　／　记录：2026-10-10 11:12 CST
- 现象：POST /api/v1/invoices（direction=OUTPUT, invoice_no=R4C-INV-101, invoice_date=2026-10-10, amount=124.00, tax_rate=3, customer_id=41, ledger_ids=[984]）→ 400「账本第 #984 行没有客户档案（历史行按名称兜底），挂不到销项票上。先在账本里给它补上客户，再回来开票。」。984 是订单 643 送达时自动记的应收行（source=ORDER）。照提示去补：PATCH /api/v1/ledger/entries/984 {customer_id:41} → HTTP 200，但 SQL 复查 customer_id 仍是 NULL，重试建票仍 400。全仓 ledgers.customer_id 只有两个写入点、都是红冲行：services/order_return.py:185（退货红冲）与 services/accounting_service.py:330（送达货损红冲）；送达自动记账行 services/ledger_sync.py:52-68 不写该列，且 LedgerCreate / LedgerUpdate / sync-from-orders 三个入参 schema 都没有 customer_id（app/schemas/ledger.py:11 / :52 / :65）⇒ 接口层根本补不上。对照组：同一接口把票挂在退货红冲行 988（customer_id=41、total=-49）上 → 201 成功 ⇒ 只有红冲行能挂票，正常应收行永远挂不上；而且 tax_service._check_links（services/tax_service.py:341）只校验客户一致、完全不校验金额（49.00 的销项票挂在 -49 的行上照样过）。
- 复现：1) POST /api/v1/invoices {direction:OUTPUT, invoice_no:R4C-INV-101, invoice_date:2026-10-10, amount:124.00, tax_rate:3, customer_id:41, ledger_ids:[984]} → 400；2) PATCH /api/v1/ledger/entries/984 {customer_id:41} → 200；3) select customer_id from ledgers where id=984 → NULL；4) 重发第 1 步 → 仍 400；5) 把 ledger_ids 改成 [988]（退货红冲行）→ 201。
- 期望：送达自动记账的应收行应当带上客户档案（同服务里已有 resolve_customer_for_order 可复用），或者把提示改成一条真的走得通的路（现在指的这条不存在）
- 实际：提示让人「先在账本里给它补上客户」，而接口层没有任何入口能补（未知字段被静默丢弃）；销项票与送达应收永远挂不上，只有退货红冲行能挂。App 侧 Apis.kt:2086 与 Dtos.kt:2974 有 ledger_ids 入参，但 InvoiceFormScreen.kt:255-268 从不发送 ⇒ 目前只有直接调接口或脚本会撞上
- 证据：_tmp/test_round4/out_invoice2.txt；_tmp/test_round4/runlog/invoice_chain_c41_run2.json
- 定位：`backend/app/services/ledger_sync.py:52-68`　`backend/app/services/tax_service.py:329-337`

### TB-14 · 滚动收款（不绑单）只进现金流水：欠款表/预收/挂账汇总/营业额一分钱都不冲，客户已付 124 元催收名单照旧要 173

- 严重度：错数　／　状态：已修复 7c0421b　／　修复：2026-10-10（BUG-0036）　／　记录：2026-10-10 11:12 CST
- 现象：订单 645 已送达、欠 124.00。POST /api/v1/ledger/receipts {customer_id:41, amount:124.00, method:cash, settle_mode:rolling, received_at:2026-10-10}（不绑单）→ 200（收款单 39），写 cash_flows 98（in 124.00, RECEIPT_CASH, order_id=NULL）。三态实测（收款单在 / DELETE / restore）：/cash-flows/summary?date_from=2026-10-10&date_to=2026-10-10 的 income 323.00 → 199.00 → 323.00（钱只在这本账上动），而 /reports/customer-balances?date=2026-10-10&mode=day 的 totals.balance 恒 72707.40、该客户那一行 balance 恒 173.00、prepaid 恒 0.00，/reports/arrears-summary?date_from=2026-10-01&date_to=2026-10-31 合计恒 1490.4；营业额 /reports/turnover 的 collected 与 arrears_total 也一步不动（这一步 23 个变化键全是 cash.* 与 receipts.*）。设计文档 docs/ACCOUNTING_V2_DESIGN.md:263 写的是「rolling（可选）：冲抵该客户应收余额（欠款表=余额+账龄，不逐单）」；而 CashFlowBizType.RECEIPT_PREPAID（backend/app/models/enums.py:396）与 App 的「预收款」标签（android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportFinance.kt:148-150）都在，全仓却没有一处写这个 biz（grep 只有枚举定义本身）⇒ 只做了一半：钱记了、欠款没销。系统自己的拒绝文案还把滚动收款当正当出口（如果是补差额，请改用「滚动收款」）。
- 复现：1) POST /api/v1/ledger/receipts {customer_id:41, amount:124.00, method:cash, settle_mode:rolling, received_at:2026-10-10} → 200；2) GET /api/v1/cash-flows/summary?date_from=2026-10-10&date_to=2026-10-10 → income 里含这 124；3) GET /api/v1/reports/customer-balances?date=2026-10-10&mode=day → 该客户 balance/prepaid 不变；4) DELETE /api/v1/ledger/receipts/39 → 204：income 掉 124，第 3 步的数一个都不动；5) POST /api/v1/ledger/receipts/39/restore → 200 全部回来。脚本 _tmp/test_round4/probe_rolling_balance.py
- 期望：滚动收款应当冲抵该客户应收余额（欠款表 balance 减 124，或按设计落进 prepaid 行），至少催收口径要能看见这笔已经收到的钱
- 实际：现金流水 +124；欠款表余额与预收、挂账单位汇总、营业额已收与欠款全部不动 —— 同一笔钱两个口径差 124，界面上没有一句话解释，客户已经付过的钱还会被再催一次
- 证据：_tmp/test_round4/out_rolling_balance.txt；_tmp/test_round4/runlog/receipt645_rolling_unalloc.json
- 定位：`backend/app/services/reports/balance_query.py:120-149`　`backend/app/services/accounting_service.py:495-520`　`docs/ACCOUNTING_V2_DESIGN.md:263`

### TB-15 · 结算单付款的 paid_at 被静默丢弃：传 2026-09-30 付款，现金流水落在 10-10 那个月

- 严重度：可疑　／　状态：已复现　／　记录：2026-10-10 11:12 CST
- 现象：PATCH /api/v1/driver-settlements/58 {action:pay, method:cash, paid_at:2026-09-30} → 200，回参 paid_at=2026-10-10T03:00:36，写出的 cash_flows 95 的 flow_date=2026-10-10（9-30 付的钱进了 10 月的现金流水）。根因：backend/app/api/v1/driver_settlements.py:149 调 pay_settlement(db, s, body.method, current.id)，从不传 body.paid_at；服务签名 pay_settlement(db, s, method, operator_id)（services/accounting_service.py:871）里也没有这个参数，paid_at 由 _now() 决定（:900 落库，:914 flow_date=business_date(s.paid_at)）。而请求 schema SettlementActionBody 里明摆着有 paid_at。影响面已查：App 两个写入点（Apis.kt:1557、AiWriteSettlementHandlers.kt:582 的 ds.settlementAction(id,pay,method)）都不发 paid_at；paid_at 只出现在出参 Dtos.kt:2242 与显示 AccountToolsScreens.kt:567 ⇒ 目前只有直接调接口才会撞上，故记可疑而不是错数。
- 复现：1) POST /api/v1/driver-settlements {driver_id:54, settle_type:piece, month:2026-10} → 200 草稿（会自动锁住该月 OPEN 明细）；2) PATCH /api/v1/driver-settlements/<id> {action:confirm} → 200；3) PATCH /api/v1/driver-settlements/<id> {action:pay, method:cash, paid_at:2026-09-30} → 200，回参里的 paid_at 是今天；4) select flow_date from cash_flows where doc_id=<id> → 落在今天那个月。
- 期望：传了 paid_at 就按它写 flow_date（钱哪一天付的就进哪个月的现金流水），或者干脆不收这个字段并在 422 里明说
- 实际：200 成功，但回参里的日期已经不是用户传的那个（静默丢弃）；跨月付款会落进错误的月份，调用方看不出任何异常
- 证据：_tmp/test_round4/out_settle.txt；_tmp/test_round4/runlog/settle_chain_d54.json
- 定位：`backend/app/api/v1/driver_settlements.py:149`　`backend/app/services/accounting_service.py:871-914`

### TB-16 · 开销没有删除/冲正入口：DELETE 与 PATCH 都 404，记错一笔就永久留在现金流水、车辆成本与利润里

- 严重度：可见　／　状态：已复现　／　记录：2026-10-10 11:12 CST
- 现象：POST /api/v1/expenses（其他 1.00）→ 200 建出开销 56，同时写 cash_flows 99（out 1.00, EXPENSE_OTHER, doc_id=56），并进利润表期间费用（profit.day.operating_expense_total 272.50→273.50）与车辆成本（vehcost.month.expense_window_total 5981.10→5982.10、unlinked_expense_total 248.60→249.60，恒等式 expense_total + unlinked == window_total 仍然成立）。随后 DELETE /api/v1/expenses/56 → 404 Not Found；PATCH /api/v1/expenses/56 {amount:2.00} → 404；想用一笔负数冲正 POST /api/v1/expenses {amount:-1.00} → 422「金额：要大于 0」（gt=0）。router backend/app/api/v1/expenses.py 只有 GET(:20) 与 POST(:79)，没有 PATCH/DELETE/作废端点；App 侧也只有 createExpense（Apis.kt:1598），没有删除或编辑。这与「所有删除一律软删＋必须有恢复路径」的规矩不一致（同规矩见 backend/app/models/shipper_receipt.py:1-15）。
- 复现：1) POST /api/v1/expenses {exp_date:2026-10-10, category:其他, amount:1.00, note:R4C-证据重跑-开销不可删} → 200（id 56）；2) DELETE /api/v1/expenses/56 → 404；3) PATCH /api/v1/expenses/56 {amount:2.00} → 404；4) POST /api/v1/expenses {amount:-1.00} → 422。
- 期望：记错的开销要有出路：软删＋恢复（与收款单、现金流水同一套规矩），或者一笔可查的冲正分录
- 实际：三条路全不通，只能改库；错的开销会继续计入现金流水、车辆成本与利润表，直到有人手工动数据库
- 证据：_tmp/test_round4/out_expense2.txt；_tmp/test_round4/runlog/expense_noreverse_rerun.json
- 定位：`backend/app/api/v1/expenses.py:20-100`

### TB-17 · 批量调价点名一个非会员货主时提示「未找到批发商或商品，请先选择」：用户明明选了批发商，系统却说没选

- 严重度：可见　／　状态：已复现　／　记录：2026-10-10 11:12 CST
- 现象：POST /api/v1/price-rules/batch {shipper_ids:[135], product_ids:[1], mode:fixed, value:1.00} → 400「未找到批发商或商品，请先选择」（货主 135 是我建的真实 SHIPPER 账号，只是 users.is_member=0）。根因：backend/app/api/v1/price_rules.py:103 先 `select(User).where(User.is_member == True)` 过滤掉的账号不会进 shippers，于是 :118-119 的 `if not shippers or not products: raise 400 未找到批发商或商品，请先选择` 先触发，:126-141 那段专门写的点名提示（会说清是哪个账号不是批发商 / 哪个商品不存在）在这个分支永远走不到。对照：同一个请求把 shipper_ids 换成 31（城东水产，is_member=1）→ 200 成功，三档 fixed/percent/adjust 都正常。
- 复现：1) POST /api/v1/price-rules/batch {shipper_ids:[135], product_ids:[1], mode:fixed, value:1.00} → 400 未找到批发商或商品，请先选择；2) 同样请求换 shipper_ids:[31] → 200。
- 期望：点名了却查不到时要说清是哪一侧：这个账号不是批发商（或不存在）—— 后端已经把这段文案写好了，不该被前面的空列表闸挡住
- 实际：用户点了批发商却被告知「请先选择」，看不出是账号身份不对还是商品被删了；只有 is_member=1 的账号能调价，这条规矩界面上没有任何提示
- 证据：_tmp/test_round4/out_pr2.txt；_tmp/test_round4/runlog/pricerules_b3b.json
- 定位：`backend/app/api/v1/price_rules.py:118-141`

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
