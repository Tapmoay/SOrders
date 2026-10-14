# 本轮修改表格 · 五项改动（2026-10-15）

> **来源**：用户口述 `m43131`（固定工资司机也要「我的账本」＋派单员核销他的工资）、`m43138`（代理下单选货主 / 货主选联系人要按分类挑）、`m43139`（派单时按路线自动带出运费模板的钱）、`m43140`（退货申请三方可直接改，不必撤销重提）、`m43193`（「下游定价」改版拍板走**甲案** ＋ 授权：以后待拍板项一律按推荐走、不再逐条问）。
> **定位**：这四件的**唯一清单** —— 「有哪些要做、做到什么程度」看这里；每件落地时另立 `docs/changes/<ID>.md` 正单，实现细节以正单为准。
> ⛔ **房规**：不许为了让实现过关去**放宽**既有判据（要动只许**追加窄例外**并在正单里写明理由与影响面）；每项都要 `_tools/qa/_check_<slug>.py` 判据 + `_tools/qa/_reverse_verify_<slug>.py` 注入式反验 + 单测 + `docs/changes/README.md` 登记行 + `docs/AI_WORK_CLAIM.md` 认领行。

## 总表

| # | 拟用单号 | 改什么（一句话） | 用户口径要点 | 主要落点 | 状态 |
|---|---|---|---|---|---|
| A | CHG-0127 | 固定工资司机也有「我的账本」：统计**他的工资**（不是运费），任职期间**固定工资变过**要有记录，**已核销**的要标出来、未核销的重新算 | 「大车司机…固定工资的司机不是没有我的账本吗，我们加一个…这个我的账本就是统计他的工资的」「如果在任职期间他的固定工资发生了改变，我们也同样也是有记录的」「已经核销了…表示已核销，就是重新计算，那个没有核销的工资」「其实也就是跟挂车司机的我的账本是一样的…很多代码是给复用的，能复用就复用」 | 司机端 `ui/driver/DriverFreightScreen.kt` ＋ `ui/profile/ProfileScreen.kt:163-183`（入口闸门）＋ 后端 `driver_bills` 的工资单 | ⏳ 待开工 |
| A2 | （并入 A 或单开） | **派单员在司机账本里对司机的工资核销** | 「我们那个派单员可以在司机账本这里啊，对他的工资进行核销」 | `ui/dispatcher/DispatcherLedgerScreen.kt`（司机账）× `driver_bills` 状态 | ⏳ 待开工 |
| B | CHG-0128 | 代理下单**选货主**、货主选**联系人**（线路收货人 / 地点绑定）都改成「左分类＋右列表」的选择器，能搜、能按分类找 | 「代理下单不是选择货主吗？他现在不是那种列表的形式啊，而是直接拉取我们已经建好了的那个联系人…他们还有分类，直接拉取那个就行了」「如果只是弹出一个列表，而且列表又没有分类的话太那个了」「好像是类似账本管理…我们账本管理的时候也会选择对应的货主和司机」「我们的货主也要改一下，就是他选联系人也是一样的，就相当于他选地点库那样子的形式」「联系人一多起来…找起来非常麻烦」 | `ui/common/ContactPickerSheet.kt`（全 App 唯一一份联系人弹层）＋ `ui/shipper/OrderCreateScreen.kt`（为谁下单）＋ `ui/shipper/AddressScreen.kt`（线路 / 地点两处选联系人） | ⏳ 待开工 |
| C | CHG-0129 | 派单时**订单的地点路线**与**运费模板绑定的路线**匹配上 ⇒ 自动把模板的钱填进运费，不用再手选模板 | 「我们的运费模板不是绑定了路线吗？如果这个派单的…地点路线和那个运费模板的路线是匹配上了，就自动的把钱给输入进去，就不需要我们再手动地去选择那个运费模板的那个钱了」 | `backend/app/models/freight_template.py:22/:38`（`route_id` = 一条常用线路）＋ 派单时的运费填写处 | ⏳ 待开工 |
| D | CHG-0130 | **退货申请可以直接改**（改的是退货的商品：种类、数量）：派单员随时可改（不必让货主撤销重提）；货主 / 批发商只要派单员**还没确认**也能改；**改完只发一条通知**（派单员改了 → 通知货主/批发商；货主或批发商改了 → 通知派单员「此退货订单发生了改动」） | 「退货是可以改的…派单员是可以更改的，不需要重新…让货主撤销然后再重新申请一下，只不过我们会发个通知，告诉货主或批发商他的这个退货申请的订单我们改动了」「货主也是可以更改的，就是只要派单员还没有确认，他也是可以更改，改完之后只会重新发个信息给派单员说此退货订单发生了改动」「主要改的是退货的商品…商品种类、商品数量，派单员可以更改，货主和批发商他们也是可以进行更改的」 | `backend/app/models/order_return_request.py` ＋ 退货申请 API ＋ `ui/common/Components.kt:1429`（逐行填退货数量那一块，两端共用）＋ 消息 `order.return_request*` 四个 type | ⏳ 待开工 |

| E | CHG-0131 | 「下游定价」改版走**甲案**：按人（一人一张卡）＋ 商品列表；卡片上直接改「全部下游的默认价」，要给某一个人单独定价才进抽屉 | 用户拍板（`m43193`）：「我选择方案甲」 | `android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductCostPriceSheet.kt` ＋ 同名 ViewModel | ⏳ 待开工 |

## A · 固定工资司机也有「我的账本」＋派单员核销他的工资

### 现状（已勘察，逐个是真事实）
- **入口今天被一条旧裁定挡着**：`android/app/src/main/java/com/tapmoay/sorders/ui/profile/ProfileScreen.kt:163-183`。:165-168 原样记着 2026-09-20 的用户裁定「拿固定工资的司机不需要「我的账本」，所以他是没有的」，三档条件：①一直固定工资、从没按单跑过 ⇒ **没有**这一格；②当前 `pays_per_order`（或「固定工资＋抽成」）⇒ **有**；③2026-09-21 补的一档：被改成固定工资、但账上已有按单账单 ⇒ **有**（否则那笔钱在 App 里彻底看不见，而 `GET /freight-settlement` 其实一条不少）。:183 `title = "我的账本"`。相关：`android/app/src/main/java/com/tapmoay/sorders/ui/profile/ProfileViewModel.kt:77-102`（显隐由 `pays_per_order` 决定，每次进页面静默重拉）。
  ⇒ **本单就是要推翻 2026-09-20 那条裁定**：固定工资司机从「没有」改成「有」，而且这本账的内容是**工资**。
- **界面已经在了、只是只喂运费**：`android/app/src/main/java/com/tapmoay/sorders/ui/driver/DriverFreightScreen.kt`（:25 KDoc「司机「我的账本」：**时间档位（顶栏右上角药丸）＋趋势图＋合计＋明细**」；:46 `title = { Text("我的账本") }`）＋ `android/app/src/main/java/com/tapmoay/sorders/ui/driver/DriverFreightViewModel.kt`（:21 原话「⛔ 取数口径**一个字没动**：仍走 `repo.freightSettlementRange`（司机应得只有 `services/driver_pay.py` 一处算）」；:164 / :219 两处调用）。
- **工资单这一层后端早就有**：`backend/app/models/driver_bill.py:12` `class DriverBill(Base, TimestampMixin)`、:35 `settled_doc_id: Mapped[int | None]`；`backend/app/models/enums.py:400` `class DriverBillType`、:405 `class DriverBillStatus`、:407 `SETTLED = "settled"`；`backend/app/api/v1/driver_bills.py`（:142 注释：挂了计费规则的司机可能**既有按单应付、又有固定工资**，例「工资 6000 ＋ 运费 5%」）；`backend/app/services/driver_pay.py`（:18 表「① 固定工资 ｜ `salary` ｜ 元/月，走月度工资单（`driver_bills` 的 SALARY 单）」；:156 文案「固定工资 X 元/月」；:325-329 「月薪未设置，不会生成他的工资单（计费方式：固定工资）」；:333 「这个司机这个月的固定工资（0 = 不给他生成工资单）」；:387-388 `has_per_order_pay` 的存在理由；:417 「固定工资制司机不按单产生应付」）。规则本体：`backend/app/models/driver_billing_rule.py`、`backend/app/api/v1/driver_billing_rules.py`、`backend/app/schemas/driver_billing_rule.py`。
- **App 侧接口面（都已存在，不用新开）**：`android/app/src/main/java/com/tapmoay/sorders/data/remote/api/Apis.kt:1669/:1672` `@GET("freight-settlement")`（`month` / `from,to` 两条）、:1687 `@GET("driver-bills")`、:1694 `@POST("driver-bills/generate")`；`android/app/src/main/java/com/tapmoay/sorders/data/repo/AppRepository.kt:1252-1253` `freightSettlement(month)` / `freightSettlementRange(from, to)`、:1414 `driverBills(driverId: Long? = null, month: String? = null, status: String? = null)`。
- **派单员侧现成的生成工资单 UI**：`android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/AccountToolsScreens.kt:480` `container.repo.driverBills(month = month, status = "open")`；AI 侧现成动作 `android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteSettlementHandlers.kt:94`（`POST /driver-bills/generate`，幂等）、:150 `ds.driverBills(null, month, "salary")`。
- **核销交互可以照抄的那本账**：批发商自记账 —— `backend/app/models/shipper_settlement.py`（整单核销 / 按商品核销、可撤销、软删；:24 父被删＝整笔不存在，所以「已核销多少」永远只有一个判据）＋ `android/app/src/main/java/com/tapmoay/sorders/ui/shipper/ShipperLedgerScreen.kt`（`SettleOrderDialog`、`RevokedCard`、`OrderSettlementsDialog`）。司机账那一页在 `android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DispatcherLedgerScreen.kt`（`DriverAccountCard`、`LedgerTabBar`）。

### 口径（本单怎么做）
1. **入口**：固定工资司机（大车 / 小车 / 挂车都算）都有这一格；闸门条件从「有按单的钱要对」改成「有工资单或按单账单要对」。
2. **内容是工资**：这本账主段吃 `driver_bills` 的 SALARY 单（月度工资单）；被改成固定工资之前留下的按单账单**一条也不许藏**（`GET /freight-settlement` 本来就是一条不少的，见 `ProfileScreen.kt:172`）。
3. **任职期间的工资变更要有记录**：按 `driver_billing_rules` 的时间线读「哪一段是 6000 / 哪一段改成 7000」，在账本里能看出来（具体呈现形式实现时定，但**必须有**）。
4. **核销状态**：已核销的工资单显示「已核销」；未核销的照常参与「重新计算」（合计只算未核销的应得）。
5. **派单员核销**：在派单端「司机账」里对某司机的工资单做核销 / 撤销核销，落到 `driver_bills.settled_doc_id` / `DriverBillStatus.SETTLED`。

### 硬约束
- 司机应得的**计算只有一处**：`backend/app/services/driver_pay.py`（`DriverFreightViewModel.kt:21` 那条注释钉着）。⛔ 不许在 App 里再算一遍工资。
- **能复用就复用**（用户原话）：界面段、图表、档位、核销弹层都优先复用挂车司机那本账与批发商那本的现成件。
- **旧口径测试必须一起改**：`backend/tests/test_driver_billing_api.py:384` `test_固定工资加提成_月薪单和按单账单是两张`、:616、:654 `test_改成固定工资之后_账上的按单钱仍然要能对账`、**:693 `test_一直拿固定工资没按单跑过的司机_没有我的账单入口`**（最后这条正是本单要推翻的口径）。

### 尚未勘察（开工第一步）
`DriverFreightScreen` 的「时间档位 / 趋势图 / 合计 / 明细」各段能不能直接吃「工资单」数据（今天只喂 `/freight-settlement` 的运费组）；`driver_bills` 的核销字段在 App 侧有没有任何界面（目前看没有，要新建）。

## B · 选人选择器：左分类＋右列表

### 现状（已勘察）
- 全 App 挑联系人**只有一份**弹层：`android/app/src/main/java/com/tapmoay/sorders/ui/common/ContactPickerSheet.kt:23`（KDoc 原话「「选择联系人」—— 全 App **唯一一份**挑联系人的弹层」；:26 与 :44 记着用户最早那两句要求）。
- 线路表单 / 地点表单两处入口：`android/app/src/main/java/com/tapmoay/sorders/ui/shipper/AddressScreen.kt:526-540`（2026-09-24 从**下拉菜单**换成弹层，理由写在 :527「下拉在人一多时滚不完、也搜不了」）、:856、:912-914（两份表单**共用**同一份弹层）；VM 侧 `android/app/src/main/java/com/tapmoay/sorders/ui/shipper/AddressViewModel.kt:329`（`contactPickTarget`：`"line"` = 线路收货人 / `"loc"` = 地点绑定联系人）、:428、:440-444。
- 代理下单入口（要改的就是它）：`android/app/src/main/java/com/tapmoay/sorders/ui/shipper/OrderCreateScreen.kt:265`（同一句话说三遍：标题「为谁下单」＋大字「请选择货主」＋小灰字「点击选择货主」）。
- **可复用的样式就是「选司机」那一份**：`android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/AssignDriverDialog.kt:48` 记着用户原话「选择司机列表的时候搞一个**左侧抽屉**吧…他直接拉起分类，像商品那样拉起一些分类列表」；:88（抽屉只在点「选择司机」那一行时开）、:113（`title = "选择司机"`）、:174（选中回填「姓名 电话」）。

### 口径（本单怎么做）
1. 代理下单的**货主选择**、货主下单时的**联系人选择**（线路收货人 / 地点绑定）统一改成：左侧分类列 ＋ 右侧对应列表 ＋ 顶部可搜。
2. 分类取**联系人自己的分类**（名册里已经存好的那一套），没建分类的人落在「未分类」，不许把没分类的人藏起来。
3. 弹层仍走 `ContactPickerSheet` 一处（⛔ 不许出现第二份挑人的弹层）；选司机那份样式作为视觉基准。

## C · 派单按路线自动带出运费模板的钱

### 现状（已勘察）
- 运费模板**已经绑了路线**：`backend/app/models/freight_template.py:22`（注释：「`route_id` → 一条**路线**（`shipper_addresses` 那一行；复用「地址与联系人 → 常用线路」）」）、:38 字段定义；建表/补列在 `backend/app/core/schema_bootstrap.py:1060`。
- Android 侧字段已透传：`android/app/src/main/java/com/tapmoay/sorders/data/remote/dto/Dtos.kt:1959/:1970`（`@SerialName("route_id") val routeId: Long? = null`）、表单在 `android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/FreightTemplatesViewModel.kt:139`（`draftRouteId = t.routeId`）:168（提交时带回 `routeId`）。
- 钱这条链路：`backend/app/core/pricing_runtime.py:22`（`freight_template`｜核心读事实（`freight_snapshot_of`）→ `PricingContext` → **契约** → 扩展算 → Money）、:53 `KIND_CONTRACT = "freight_template"`。

### 口径（本单怎么做）
1. 派单时按**订单的地点 / 路线**去匹配运费模板（模板的 `route_id`），命中就把他那一档的价格自动填进运费格。
2. 匹配**多条**时不许瞎猜：给最贴近的那条（同路线同车型同分类）并让人看得见选的是哪条。
3. 人仍可改（自动填入不等于钉死）—— 这一条实现时如与既有判据冲突，按「自动填默认值 ＋ 手改优先」处理，并在正单里写明。

## D · 退货申请可以直接改（三方可改，改完只发一条通知）

### 现状（已勘察）
- 后端：`backend/app/models/order_return_request.py`（货主提的退货申请，带办理/驳回记录）；消息四个 type 在 `backend/app/services/message_center.py:72-75`（`order.return_request` / `.rejected` / `.done` / `.closed`，:116-119 中文名分别是「申请退货 / 被驳回 / 已办理 / 已自动关闭」）、:873 `publish_return_request_closed`；推送四处 `backend/app/main.py:191-205`；幂等/外发在 `backend/app/core/outbox.py:102`（原话「一次退货改了订单行 / 钱 / 库存，聚合根是**那张订单**」）；权限 `backend/app/core/rbac.py:40` `ORDER_RETURN_REQUEST = "order:return_request"`、:165（`own`，货主只能给自己的单提）。
- Android：`android/app/src/main/java/com/tapmoay/sorders/data/remote/api/Apis.kt:349-371`（提交 / 我的申请 / 派单员待办三条）、`android/app/src/main/java/com/tapmoay/sorders/data/repo/AppRepository.kt:188-214`、**两端共用的逐行填数量那块**在 `android/app/src/main/java/com/tapmoay/sorders/ui/common/Components.kt:1429`（原话「派单员（执行退货）与货主（申请退货）**共用这一份**」）、消息落点 `android/app/src/main/java/com/tapmoay/sorders/ui/messages/NoticeRouting.kt:55/:59` 与 `ui/messages/MessageGrading.kt:26/:387`。

### 口径（本单怎么做）
1. **派单员**：对一张待处理的退货申请可以直接改（**不必**让货主撤销再重提），改的是**退货的商品：种类、数量**。
2. **货主 / 批发商**：只要派单员**还没确认**（还在待处理），自己也能改同一份申请。
3. **改完只发一条通知**：派单员改的 → 通知货主 / 批发商「退货申请已改动」；货主或批发商改的 → 通知派单员「此退货订单发生了改动」。不改语义、不新增状态机分支，只加这一条消息 type。
4. ⛔ 已经办理完 / 已驳回 / 已自动关闭的申请**不许再改**（要改只能重新提）。

## E · 「下游定价」改版：走甲案（按人 ＋ 商品列表）

### 拍板（2026-10-15，`m43193` 逐字）
「然后我那个改的样式啊，我选择方案甲」

### 甲案是什么（三选一样张：`_tmp/mock_pricing/index.html` ＋ `_tmp/mock_pricing/preview_full.png`）
- 商品列表页上，**一个下游客户一张卡**：上段「全部下游的默认价」一个输入框 ＋ 保存；下段按人分行（姓名 ＋ 电话 ＋ 单价输入框 ＋ 保存），每行还带「删除这条价」。
- **默认价直接在列表卡片上改**（不必进抽屉）；只有要给**某一个人**单独定价时，才点那个人右侧的「定价」进抽屉编辑。
- 视觉照全 App 现值：主色 `#009663`、分类色 `#BC7730`、卡片圆角 16、输入框高 45、主按钮高 52。

### 开工时要对齐的既有件
`android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductCostPriceSheet.kt`（:173 那句「口径名称，例如「返点后成本」」现在是 `_tools/qa/_check_input_rules.py` 的红点）＋ 它的 ViewModel ＋ 两条点在它身上的判据：`_check_input_rules.py`、`_check_sheet_form_pages.py`（:80 抽屉内容缺 `fillMaxHeight(` 那条红同样在它身上）。⇒ **顺手把这两个红一起修掉**（它们本来就是这块的账）。

### 决策记录：本轮的「不再问」授权
- 用户 2026-10-15（`m43193`）：「接下来的所有问题啊，你全都按推荐的走。然后不要来问我自己做判断。但判断的核心依据…以用户为目标嘛，以用户减少使用摩擦为目标。」
  ⇒ 本轮所有待拍板项**按推荐方案自行决定**并写进对应正单，不再逐条发问；判断依据＝最终用户视角 ＋ 减少使用摩擦。
  ⇒ 由此定下的默认口径：**C 项**＝自动填默认值、手改优先、多条命中选最贴近的那条并显示选了谁；**D 项**＝只新增一条消息 type、不动状态机、已办理/已驳回/已关闭不许再改；**B 项**＝左分类 ＋ 右列表 ＋ 可搜，未分类的人归「未分类」不许藏。
## 每项的验收（缺一件不算完）

| 项 | 说明 |
|---|---|
| 代码 | 后端 + Android 真正的实现，不留 TODO |
| 判据 | `_tools/qa/_check_<slug>.py` 自己算得出来，逐项标 ✅ |
| 反验 | `_tools/qa/_reverse_verify_<slug>.py` ≥3 条注入，每条都能把判据弄红，改回即绿 + 逐字节还原 |
| 单测 | Android `:app:testEmuDebugUnitTest` + 后端 pytest 对应用例（含被推翻的旧口径用例） |
| 文书 | `docs/changes/CHG-01xx.md` 九节齐全 ＋ `README.md` 登记行 ＋ `AI_WORK_CLAIM.md` 认领行 |
| 静检 | `python -X utf8 _tools/qa/_check_all.py` 与 `backend/scripts/check_reachability.py` 不因本单变红 |
| 提交 | 明细分笔、明确 pathspec（⛔ 不 `git add -A`、⛔ 不 push） |
