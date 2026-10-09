# 测试提示词 · 方向 A：订单与基础数据（含 AI 操作）

> **这份是给"测试会话"的开工说明**：照着它就能直接开测，不需要再问人。
> 配套：`docs/TEST_BUG_LEDGER.md`（**所有 bug 写这里**，编号 `TA-nn`）、`docs/DEVELOPMENT_SPEC.md`（施工规范）、`docs/PROJECT_MAP/05_TESTING.md`（测试资产与账号）。
> 建立时的 `HEAD = 64fc850`（2026-10-09）；行号按当时工作区，**引用前自己再核一遍**。

---

## 〇、你这一轮要干的事（一句话 + 边界）

把**「订单从下单到送达/退货」这条主线**，连同它依赖的**基础数据**（地点与线路、商品与分类、联系人与客户、车辆、单位换算、定价、预订单模板），
在**真机 + 真实后端 + 真实库**上完整走一遍；**AI 助手**在这条线上的读与大部写操作也要走一遍。
发现的问题写进统一台账 `docs/TEST_BUG_LEDGER.md`（方向 A，编号 `TA-01`、`TA-02`…）。

**边界（很重要，别越界）**：
- 归 A：订单本身（状态、字段、商品行、金额展示口径）、下单/派单/接单/送达/改单/拆单/转货/撤回/退货/回收站，以及上面列的基础数据页。
- 归 B（财务方向，别在这里深挖）：账本与流水、收付款、挂账单位的**余额与应收**、发票、司机账单/结算、运费结算、报表与导出。
- **交叉点**（A 会碰到，但"钱的结果"归 B）：`orders.pay` 现场收款、`orders.charge` 挂账到单位、`orders.freight` 改司机运费、`orders.discount` 让价、`ledger.sync_delivered` 补进账本、`price_rules.*` 调价。
  你在 A 方向只判**「这一步做没做对、有没有按预期落到订单上」**；**金额落到账本/余额/报表对不对，写台账时标注「与 B 相关」**，别两边重复写同一条。
- ⛔ **只记录、不修代码**（用户 2026-10-06 的原话口径：`你现在只是做记录不要做任何改动`）。

---

## 一、先建立项目认知（花 40 分钟，边看边记）

### 1.1 这是什么系统
给**批发商（货主 shipper）**下单、平台**派单员（dispatcher）**派给**司机（driver）**、送达后**记账**的配送订单系统。三块：
- 安卓端（Kotlin）：`android/`（界面在 `android/app/src/main/java/com/tapmoay/sorders/`）
- 后端（FastAPI）：`backend/`（接口在 `backend/app/api/v1/`，业务在 `backend/app/services/`，表在 `backend/app/models/`）
- 本地库：`backend/sorders.db`（SQLite，可以直接用 sqlite3 查）

### 1.2 五个必须记住的事实
1. **订单状态机是唯一的**（`backend/app/models/enums.py:10-26`）：`PENDING_DISPATCH → DISPATCHED → ACCEPTED → DELIVERED`；
   另有 `CANCELLED`（这张单**从未发生过**）与 `RETURNED`（送过、入过账、事后**整单**退回）。
   **部分退货仍然留在 `DELIVERED`**，只打「部分退货」标记 —— 测试时别把这两件事混起来判。
2. **订单是"一行行商品"堆出来的**：一张订单 = 订单头（地点/联系人/时间/状态）＋ 若干 `order line`（商品 + 数量 + 单位 + 单价）。
   订单金额、商品明细、对账、退货都按行算 —— 出问题时先看**行**再看头。
3. **单位换算是一等公民**（`backend/app/services/unit_conversion.py`、`ui/common/Units.kt`/`UnitConverts.kt`）：同一商品可能按件/箱/斤下，展示与金额口径要能对上。
4. **钱有两条线**：订单上的金额（A 关心展示与口径）／账本上的流水（B 关心）。改订单不一定改账本，改账本会回写订单（工具 `_tools/ai/_check_ledger.py` 能看一条流水对应的订单商品行）。
5. **AI 写操作只有一条路**：`preview_write` 生成**确认卡**，用户点「确认」才真正写系统；AI 自己一步都不写。

### 1.3 必读（按顺序，别跳）
| 顺序 | 文件 | 你要拿到什么 |
|---|---|---|
| 1 | `docs/PROJECT_MAP/07_END_TO_END_FLOW.md` | 一条订单从下单到送达的完整生命周期 |
| 2 | `docs/PROJECT_MAP/01_ARCHITECTURE.md` | 三端怎么连、数据怎么流 |
| 3 | `docs/PROJECT_MAP/04_ANDROID_MAP.md` ＋ `08_CODE_LOCATOR.md` | **哪个页面在哪个文件**（本提示词第三节给的表也是从这里来的） |
| 4 | `docs/PROJECT_MAP/03_BACKEND_DETAILS.md` ＋ `08A_ENDPOINT_INDEX.md` | 接口与业务规则 |
| 5 | `docs/PROJECT_MAP/05_TESTING.md` | 怎么跑测试、**测试账号在哪**（密码看这里，不要往本文件里抄） |
| 6 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md` | 界面口径：按钮该长什么样、文案该说什么、空态/颜色规范 |
| 7 | `docs/DEVELOPMENT_SPEC.md` §十七（判据必须能够判红）§十八（测试数据匹配生产形状）§二十一（证据记录规范） | 你这轮的产出算不算"证据" |
| 8 | `docs/PROJECT_MAP/09_DEV_ONLY_INDEX.md` | **哪些页面/入口是开发态**（别把开发态当 bug） |

---

## 二、把环境跑起来（这三件事不通就别往下走）

### 2.1 后端
```powershell
# 起服务（在仓库根）
Start-Process C:\python\python.exe -ArgumentList -m,uvicorn,app.main:app,--host,0.0.0.0,--port,8000,--log-level,warning -WorkingDirectory D:\AProjects\ASDH\orders\backend -WindowStyle Hidden
# 看接口文档
start http://127.0.0.1:8000/docs
```
- 库：`backend/sorders.db`（改数据前先备份一份到 `_tmp/`）。
- 中文输出别乱码：`[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; $env:PYTHONIOENCODING="utf-8"`。

### 2.2 安卓装机（模拟器 emulator-5554）
```powershell
# 编译（本仓库没有 gradlew，必须用带路径的 gradle）
D:\AProjects\ASDH\orders\_agent\gradle\gradle-8.9\bin\gradle.bat -p D:\AProjects\ASDH\orders\android :app:assembleEmuDebug
# 装到 5554
python _tools/qa/_install_all.py --only 5554 --no-build
# adb 不在 PATH 时：C:\Users\Optimistic\AppData\Local\Android\Sdk\platform-tools\adb.exe
```

### 2.3 真机输入中文（**必须用 ADBKeyboard，模拟器剪贴板共享常常是关的**）
```powershell
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" -s emulator-5554 shell ime enable com.android.adbkeyboard/.AdbIME
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" -s emulator-5554 shell ime set com.android.adbkeyboard/.AdbIME
# 点一下输入框，然后：
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" -s emulator-5554 shell am broadcast -a ADB_INPUT_TEXT --es msg "帮我加一个常用地址，收货人张三"
```
- 截图：`adb shell screencap -p /sdcard/_s.png` 然后 `adb pull` —— ⛔ **绝不要**用 PowerShell 的 `>` 重定向写 PNG（会把图写坏）。
- ⛔ 别再走「剪贴板粘贴」那条老路：`_tools/ai/_emulator_say.ps1` 这台模拟器上粘贴进不了输入框（它会如实报"粘贴没进输入框"）。

---

## 三、测试路线（A 方向 14 条主线）

> 每条都按同一个模板走：**入口 → 怎么走 → 重点看什么 → 去哪核实**。
> 后面标 `[判据]` 的是仓库里已有的静态判据，改动后能跑；标 `[单测]` 的是安卓单测；标 `[接口]` 的是后端接口文件 —— 遇到问题直接去读它们，比翻页面快。

### A1 登录 / 角色 / 首页
- 入口：启动页 → 登录（`ui/` 根目录的登录页）→ 按角色进不同首页（派单员=派单作业，货主=我要下单，司机=我的运输）。
- 重点：**同一账号在不同角色下的可见范围**；退出登录再进来状态是否干净；被禁用/停用的账号能不能进。
- 去哪核实：`core/Capabilities.kt`（权限位）、`backend/app/api/v1/auth.py`。

### A2 下单（货主端）
- 入口：`ui/shipper/OrderCreateScreen.kt`（＋ `OrderCreateViewModel.kt`、`OrdererPrefill.kt`）。
- 怎么走：选收货地址（地点）→ 选商品 → 改数量/单位 → 填联系人 → 选日期 → 提交。
- 重点看：
  1. **地点选择**：搜索、按分组/线路筛、地图选点（`ui/common/AmapPicker.kt`、`AmapViewDialog.kt`）回来地址与经纬度是否一致；
  2. **商品与数量**：`ui/common/ProductPicker.kt`、`ProductCardKit.kt`、`QtyStepper.kt`；单位换算（`UnitPickerSheet.kt`）切换后**单价×数量**要不要跟着变；
  3. **联系人**：`ui/common/ContactFill.kt`、`ContactRequirement.kt` —— 哪些字段是必填（`[判据] _tools/qa/_check_order_contact_required.py`）、填了以后下单人会不会被记住（`OrdererPrefill`）；
  4. **提交反馈**：`[判据] _check_order_submit_feedback.py` —— 提交中/成功/失败三种状态有没有都画出来。
- 下单成功后：**用库核对**（`python -X utf8 _tools/ai/_check_order.py <订单号>`），看状态、行、金额、地点、联系人是否与你填的一致。

### A3 派单池与派单
- 入口：`ui/dispatcher/DispatcherPoolScreen.kt`（＋ VM）、`AssignDriverDialog.kt`。
- 怎么走：待派单池 → 选一张单 → 派单 → 选司机 → 回列表；再走「批量派单」；再走「撤销派单」（回池子）。
- 重点看：派单**成功后那张单还在不在池子里**、状态与按钮是否同步、批量派单部分失败时列表有没有说清哪几张没成、司机侧是否同时收到（`core/NewOrderAlert.kt`、`RealtimeHub.kt`）。
- 去哪核实：`backend/app/api/v1/orders_assignment.py`、`[判据] _check_order_list_ui.py / _check_order_commands.py`。

### A4 司机端接单与送达
- 入口：`ui/driver/DriverOrdersScreen.kt`（＋ VM）、`DriverFreightScreen.kt`（＋ VM）。
- 怎么走：接单（ACCEPTED）→ 送达（DELIVERED，可能要求拍照/上传）→ 看运费页。
- 重点看：**状态只能按状态机往前走**（不能跳、不能倒）、照片上传失败时能不能重试、送达后派单员侧与货主侧是否同步、运费展示与订单上的一致。
- 去哪核实：`backend/app/api/v1/orders_delivery.py`、`[判据] _check_delivery_flow.py / _check_order_transfer.py`。

### A5 订单列表、详情与各种改动
- 入口：`ui/dispatcher/DispatcherOrdersScreen.kt`（＋ VM）→ `ui/order/OrderDetailScreen.kt`（＋ `OrderDetailViewModel.kt`）、`OrderEditInline.kt`、`OrderDiscount.kt`/`OrderDiscountDialog.kt`、`OrderTransferSheet.kt`、`ChargeUnitName.kt`。
- 怎么走（每种都做一遍）：改单（联系人/时间/备注）→ 加一行商品 → 改一行 → 删一行 → 让价 → 取消让价 → 改司机运费 → 转货给别的司机 → 拆单 → 标记异常/解除 → 移入回收站 → 从回收站恢复。
- 重点看：
  1. **改完之后列表卡片、详情、金额三处是否一致**（`ui/common/OrderCard.kt`、`OrderPeek.kt`、`OrderTabs.kt`、`SegmentedStatusTabs.kt`、`core/OrderStatusModel.kt`）；
  2. **行级改动的守恒**：删一行后总额与行数和是否还对得上；拆单后两张单金额之和 = 原来那张；
  3. 让价与挂账单位名（`[判据] _check_order_discount.py`；对应单测 `android/app/src/test/java/com/tapmoay/sorders/ui/order/OrderDiscountTest.kt`、`ChargeUnitNameTest.kt`）；
  4. 转货后**原单去哪了**、司机侧看到的是不是新单；
  5. 回收站里恢复的单，行、金额、状态有没有走样。
- 去哪核实：`backend/app/api/v1/orders*.py`（orders / orders_lifecycle / orders_discount / orders_payment / orders_query / orders_return）、`backend/app/services/order_flow.py`、`order_money.py`、`order_discount.py`。

### A6 退货
- 入口：`ui/dispatcher/DispatcherReturnRequestsScreen.kt`（＋ VM）、`ui/shipper/ShipperReturnRequestsScreen.kt`（＋ VM）、`ui/common/ReturnRequestsUi.kt`、`ReturnRequestChip.kt`、`ReturnRequestFocus.kt`。
- 怎么走：货主提退货申请 → 派单员看到 → 拒绝一次（看提示与状态）→ 再申请 → 完成退货（整单）。再单独走一次**部分退货**（只退一行的一部分）。
- 重点看：**整单退 → 订单变 `RETURNED`；部分退 → 订单仍 `DELIVERED` 只打「部分退货」标记**（这是设计，不是 bug）；退货后**金额与账本怎么变的要标「与 B 相关」**；已退货的单还能不能被派单/改单。
- 去哪核实：`backend/app/api/v1/return_requests.py`、`orders_return.py`、`backend/app/services/order_return.py`、`order_return_request.py`、`core/ReturnRules.kt`、`[判据] _check_order_return.py / _check_order_return_visible.py`。

### A7 地点与线路（基础数据）
- 入口：`ui/dispatcher/PlaceCategoriesScreen.kt`、`RouteCategoriesScreen.kt`、`ui/shipper/AddressScreen.kt`（＋ VM）、`ui/common/AmapViewDialog.kt`。
- 重点看：新增/改名/排序/停用；**排序（reorder）后各处顺序是否一致**（列表、选择器、地图标记）；地址照片的水印（`[判据] _check_place_photo_watermark.py`）；两个选择器是不是同一套（`_check_place_picker_shared.py`）；地图上点选回来的落点精度。
- 去哪核实：`backend/app/api/v1/places.py`、`place_categories.py`、`route_categories.py`、`backend/app/services/place_service.py`、`[判据] _check_address_cards.py / _check_address_palette.py / _check_address_tabs.py / _check_place_ranking.py / _check_order_place_map.py`。

### A8 商品与分类
- 入口：`ui/dispatcher/ProductsScreen.kt`（＋ VM）、`ProductFormScreen.kt`（＋ VM）、`ProductBatchScreen.kt`、`ProductCategoriesScreen.kt`（＋ VM）、`ProductSortScreen.kt`。
- 重点看：**同一商品在多处显示是否一个来源**（`[判据] _check_product_card_single_source.py`）；停用商品还能不能下单/派单（`_check_product_active_confirm.py`）；批量改价/按表格导入（`ui/dispatcher/BatchPriceSheets.kt`）后**价格基数（含税/不含税）有没有被换掉**；分类排序与商品列表排序。
- 去哪核实：`backend/app/api/v1/products.py`、`product_categories.py`、`price_rules.py`、`backend/app/services/cost_basis.py`、`sheet_parser.py`、`[判据] _check_product_check_list.py / _check_shipper_pricing.py`。

### A9 联系人与客户
- 入口：`ui/dispatcher/ContactCategoriesScreen.kt`（＋ VM）、`ui/common/ContactPickerSheet.kt`、`CustomerEditorDialog.kt`、`PersonPicker.kt`、`ShipperPickerSheet.kt`。
- 重点看：同一个人在不同订单上改名/改电话后**历史单是否被改**（历史事实不该被改写）；重名怎么区分；删除联系人后历史订单还能不能显示名字。
- 去哪核实：`backend/app/api/v1/customers.py`、`contact_categories.py`、`backend/app/services/order_contact.py`、`shipper_contact_service.py`、`[判据] _check_contact_binding.py / _check_contact_names.py / _check_contact_remark.py / _check_contact_categories.py`。

### A10 车辆与司机资料
- 入口：`ui/dispatcher/VehicleManageScreen.kt`、`VehicleAttrs.kt`。
- 重点看：车辆属性（`backend/app/services/vehicle_attrs.py`）、折旧（`vehicle_depreciation.py` —— **它的钱归 B**）、车辆停用后还能不能派单。
- 去哪核实：`backend/app/api/v1/vehicles.py`、`vehicle_categories.py`、`[判据] _check_vehicle_form.py / _check_vehicle_attrs.py / _check_vehicle_ui.py`。

### A11 单位换算
- 入口：`ui/common/UnitConversionsScreen.kt`（＋ VM）、`UnitPickerSheet.kt`、`UnitConversionDialog.kt`、`Units.kt`、`UnitConverts.kt`。
- 重点看：换算率改了以后**历史订单的展示口径**变不变（不该变）；同一商品两种单位下单，账面数量对不对；除不尽时的小数位与舍入（`[判据] _check_money_contract.py` 属于 B，但**单位换算导致的金额差**在 A 这边要记）。
- 去哪核实：`backend/app/api/v1/unit_conversions.py`、`backend/app/services/unit_conversion.py`。

### A12 定价（默认价 / 批发商专属价 / 单笔让价 / 司机运费）
- 入口：`ui/dispatcher/PriceMatrixScreen.kt`（＋ VM，价格矩阵）、`ui/shipper/ShipperPricesScreen.kt`（＋ VM，货主自己的下游价）、`ui/dispatcher/FreightPricingScreens.kt`、订单详情里的让价与运费入口。
- 怎么走：改一个商品的**默认价** → 看货主端下单时的取价 → 给某个批发商设**专属价** → 再下单看取的是哪一套 → 在订单上**让价** → 再改司机运费。
- 重点看：**默认价与专属价是两套**，别混（AI 也会特意提醒这句）；改价后**已存在的订单**价格要不要跟着变（按仓库口径：历史事实不动）；让价与运费都不该把商品单价偷偷改掉。
- 去哪核实：`backend/app/api/v1/price_rules.py`、`shipper_prices.py`、`backend/app/services/shipper_price.py`、`freight_pricing.py`、`[判据] _check_shipper_pricing.py / _check_freight_pricing.py / _check_freight_pricing_clarity.py`。

### A13 预订单模板（套用下单）
- 入口：`ui/dispatcher/OrderTemplatesScreen.kt`、`OrderTemplateFormScreen.kt`、`OrderTemplateCategoriesScreen.kt`。
- 重点看：模板改了会不会影响已经下过的单；模板里的商品/地点失效（停用/删除）后再套用会怎样（应该有明确提示，不是静默丢行）。
- 去哪核实：`backend/app/api/v1/order_templates.py`、`order_template_categories.py`、`[判据] _check_order_templates.py`。

### A14 AI 助手（A 方向要测的那一半）
见第四节 —— 单独一节，因为它有自己的一套方法。

---

## 四、AI 助手怎么测（A 方向）

### 4.1 先搞清它由什么组成（读这四个文件就够了）
| 文件 | 干什么的 |
|---|---|
| `android/app/src/main/java/com/tapmoay/sorders/ai/AiAgentLoop.kt` | 拼系统提示词、跑"模型 → 工具 → 模型"的循环 |
| `android/app/src/main/java/com/tapmoay/sorders/ai/AiTools.kt` | 工具总表：名字、分组、参数、说明、执行入口 |
| `android/app/src/main/java/com/tapmoay/sorders/ai/AiReadCatalog.kt` | **读动作 69 条**（机器生成；打印用 `python -X utf8 _tools/ai/_show_read_catalog.py`） |
| `android/app/src/main/java/com/tapmoay/sorders/ai/AiWrite.kt` | **写动作 83 条**（每条带中文名与风险等级） |
另有两个"自己会跑"的东西：`ai/AiWorkflow.kt` ＋ `ai/AiWorkflowRunner.kt`（两条只读工作流：**对账** `ledger.reconcile`、**批量调价** `price.batch`）。

### 4.2 A 方向重点测的读动作（都在上面那个清单里）
`orders.*`、`order_products.*`、`order_templates.*`、`order_template_categories.*`、`places.*`、`place_categories.*`、`route_categories.*`、
`products.*`、`product_categories.*`、`price_rules.*`、`shipper_prices.*`、`shipper.*`、`customers.*`、`contact_categories.*`、
`inventory.*`、`return_requests.*`、`vehicles.*`、`vehicle_categories.*`、`unit_conversions.*`、`users.*`、`user_categories.*`、`notifications.*`、`stats.*`、`reports.product_report`。

### 4.3 A 方向重点测的写动作（都是"确认卡 + 点确认才写"）
- 订单（28 条）：`orders.assign`（派单 HIGH）、`orders.recall`（撤回）、`orders.transfer`（转货）、`orders.release`（退回派单池）、`orders.create`、`orders.update`、`orders.update_contact`、`orders.cancel`、`orders.return`、`orders.split`（拆单）、`orders.batch_assign`（批量派单）、`orders.add_line` / `update_line` / `delete_line`、`orders.soft_delete` / `restore`、`orders.mark_exception` / `resolve_exception`、`orders.pay` / `charge`（钱 → 标「与 B 相关」）、`orders.freight`、`orders.price_freight`、`orders.discount` / `discount_clear`、`orders.fill_nav`、`order_templates.create/update/delete`。
- 商品与基础数据：`products.apply_table`（按表格改商品）、`product_category.reorder`、`place_category.reorder`、`route_category.reorder`、`contact_category.reorder`、`vehicle_category.reorder`、`order_template_category.reorder`、`user_category.reorder`、`user.product_visibility`（设置商品可见范围 HIGH）。
- 定价：`price_rules.batch`（批量调价 HIGH）、`price_rules.apply_table`、`shipper_price.set/delete`。
- 退货：`return_request.apply` / `withdraw` / `reject` / `fulfill`。
- 消息：`notifications.read_all` / `mark_read` / `update` / `send` / `price_change` / `delete`。

### 4.4 必测矩阵（每条至少走一遍，出了就写台账）
| # | 场景 | 怎么造 | 看什么 |
|---|---|---|---|
| 1 | 正常读 | "这个月哪些货主的单最多" | 有没有真查到数据（看"执行过程"里发了哪几个读动作） |
| 2 | 读的参数 | "查一下张三这周的单" | 有没有把**人名当过滤条件**传下去，还是拉全表自己筛 |
| 3 | 多轮追问 | 先问列表，再问"第二张单的详情" | 上一轮的上下文有没有接住 |
| 4 | 歧义 | "把花生油降 5%"（商品名不存在时） | 会不会**编**一个商品出来（这是高危 bug） |
| 5 | 没权限 | 用货主身份问订单池 | 有没有越权读到不该读的 |
| 6 | 写 → 确认 | "给 SO… 派给司机老王" | 确认卡内容是否与它说的**完全一致**（金额、单号、对象） |
| 7 | 写 → 取消 | 发卡后点取消 | 系统里**一点都不能变**（用 `_tools/ai/_check_order.py` 复核） |
| 8 | 写 → 确认成功 | 同上点确认 | 库里真的变了、订单卡片刷新、消息里出现"撤回" |
| 9 | 点撤回 | 写成功后点"撤回" | 是否回到原值（不是近似值） |
| 10 | 确认卡过期 | 发卡后放 5 分钟再点确认 | 提示应是"已经执行过或已过期…重新发起"这类清楚的话 |
| 11 | 角色边界 | 让 AI 干它不该干的（货主改司机运费） | 应该直接拒绝并说明 |
| 12 | 工作流 | "这个月对一下账，看看有没有漏记的" | 两步读动作都发了没、结论里的数字与库一致没（**这条与 B 相关**） |
| 13 | 工作流（调价） | "把花生油降 5%" | 认不认得出 `price.batch`、会不会把"默认价/专属价"混起来 |

### 4.5 用「AI 操作流水」反查（最有效的取证手段）
- 入口：AI 助手页 → 设置 → **AI 操作流水**（`ui/ai/AiSettingsScreen.kt`、`ui/ai/AiOperationsViewModel.kt`）。⚠️ 这个入口只给**派单员**画（后端要 `OPERATION_LOG_READ`）。
- 它记的是 **AI 发起的每一次请求**（成功/4xx/5xx 都记，接口 `backend/app/api/v1/ai_operations.py`，路径 `GET /api/v1/ai/operations`）。
- 怎么看：① 动作名对不对（应是你那条问题该发的动作）；② 是不是发了**多余**的读；③ 失败的原因（4xx 说明参数违规）。
- ⚠️ 已知问题（已在旧台账 L-58 记过）：这个页面显示的是**英文动作 id**，没有中文名 —— 别重复记。

### 4.6 AI 的硬边界（当判据用）
1. AI **写**只有 `preview_write` 一条路：先出确认卡，用户点确认才写。**AI 自己不能直接写**。
2. 写动作有**风险等级**（LOW/MEDIUM/HIGH），HIGH 的必须明确提示后果。
3. 读动作受**权限**约束（后端权限码：`ORDER_CREATE / ORDER_EDIT / ORDER_DISPATCH / ORDER_RECALL / ORDER_RETURN / ORDER_RETURN_REQUEST / ORDER_PRODUCT_EDIT / ORDER_INTERNAL_NOTE / ORDER_COMPLETE_DRIVER / ORDER_UPLOAD_DELIVERY / PRODUCT_MANAGE / PRICE_RULE_MANAGE / USER_MANAGE / STATS_READ / LEDGER_EDIT / NOTIFICATION_MANAGE` ＋ 角色 `role:DISPATCHER` / `role:SHIPPER`）。
4. **不许编数据**：查不到就说查不到（例：问"城东水果批发"这个货主，系统里没有，正确回答是"没查到，最接近的是城东水产"）。

---

## 五、发现 bug 写哪里（硬规矩）

**统一台账：`docs/TEST_BUG_LEDGER.md`**（方向 A 用 `TA-nn`）。写之前先看它的「一、总表」和「四、怎么写一条」。

```powershell
# 追加一条（在仓库根跑；脚本自己算下一个编号 TA-nn，原子写，不会和 B 方向打架）
python -X utf8 _tools/qa/_test_bug_ledger.py add --dir A ^
  --title "派单成功后待派单池里还留着这一单" --severity 可见 --status 已复现 ^
  --phenomenon "点了派单，卡片状态已是派单中，切回待派单池它还在列表里" ^
  --repro "派单作业-待派单池-任选一单-派单-选司机-返回列表" ^
  --expect "该单应从待派单池消失" --actual "仍在，按钮还是「派单」" ^
  --where backend/app/api/v1/orders_assignment.py:88 --where android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DispatcherPoolViewModel.kt:120 ^
  --evidence "shots/TA01_pool_after_assign.png" --fix "派单成功后前端移除该行或重拉列表"

python -X utf8 _tools/qa/_test_bug_ledger.py list      # 看两个方向已有的行
python -X utf8 _tools/qa/_test_bug_ledger.py show TA-01 # 看某条详情
```

**写一条的门槛**（缺一项就别写进去，先自己再复现一次）：
1. **复现步骤**：账号/页面/点了什么/输入了什么 —— 别人照着能再走一遍；
2. **期望 vs 实际**：期望要写"按什么规矩应该怎样"（引文档或引状态机），不是"我觉得"；
3. **证据**：截图路径 / 命令原文＋输出 / 库里的行（SQL ＋ 结果），至少一个；
4. **定位**：能给 `文件:行` 就给；给不出就写"未定位"＋你读过的文件。

**严重度四档**：`堵死`（主流程走不通）／`错数`（金额·库存·订单金额算错）／`可见`（界面·文案·排序·提示）／`可疑`（说不清但要记）。
拿不准就写 `可疑` —— 宁可多记一条，别漏。

**⛔ 三条禁令**：
- ⛔ 只记录**不改代码**（用户没说"修"之前）；
- ⛔ 不改台账里**别人已写下的行**（并行会话在写；要补就在自己那条详情块里追加 `- 补充（日期）…`）；
- ⛔ 不在台账里贴大段日志或图片二进制（贴路径）。

---

## 六、把现有测试当"探针"用（别重写，先借用）

| 资产 | 位置 | 怎么用 |
|---|---|---|
| 后端接口测试 | `backend/tests/`（168 个 py；A 类约 59 个） | 在 `backend/` 下 `python -m pytest tests -q` 跑一遍：**先记基线**，之后再跑，新红的才是线索 |
| 静态判据 | `_tools/qa/_check_*.py`（201 个；A 类约 47 个，如 `_check_order_commands.py`、`_check_order_return.py`、`_check_place_ranking.py`、`_check_product_card_single_source.py`、`_check_contact_binding.py`、`_check_order_discount.py`、`_check_delivery_flow.py`） | 单跑：`python _tools/qa/_check_order_commands.py`（判据输出 ✅/❌） |
| 安卓单测 | `android/app/src/test/java/com/tapmoay/sorders/`（97 个；`ui/common` 17、`ui/order` 2、`core` 15 与 A 相关） | `gradle.bat -p … :app:testEmuDebugUnitTest` 跑全量；条数用 `python _tools/qa/_android_test_count.py` |
| 端到端脚本 | `_tools/e2e/_flow_login_nav_order.py`（登录→导航→下单） | `python -X utf8 _tools/e2e/_flow_login_nav_order.py --serial 5554 --account 13800000002 --shot-dir _agent/e2e` |
| 全量静检 | `python _tools/qa/_check_all.py`（几分钟） | 只在你要判断"某处是不是本来就红"时跑 |

⚠️ **判据/测试失败不等于 bug**：先 git stash 或看 `git log` 确认是不是**这半天里别人改出来的**，再决定记不记（记的话在详情里写清"HEAD 与提交"）。

---

## 七、什么**不要**记成 bug（降噪）
1. **开发态页面/入口**（见 `docs/PROJECT_MAP/09_DEV_ONLY_INDEX.md`）；
2. 明显是**故意留的占位**（仓库里唯一的占位符是 `docs/changes/FEAT-0009.md:247` 那个，别碰也别记）；
3. **并行会话正在改**的东西（`git status` 里被改的文件、以及 `docs/AI_WORK_CLAIM.md`「进行中」里的单）—— 先确认不是"改了一半"，再记；
4. 文案的**个人偏好**（"我觉得这样说更好"）—— 只有当它与 `06_DESIGN_SYSTEM.md` 的口径冲突时才记，严重度 `可见`；
5. 你已经记过一次的同一个问题（先 `list` 查重，同一条就在详情块里追加，不新开一条）。

---

## 八、收口（每轮结束都做）
1. **每轮**：`python -X utf8 _tools/qa/_test_bug_ledger.py list` 看自己这轮加了几条；把"我这轮走了哪些路径"记在 `_tmp/` 自己的笔记里（不往台账里写流水账）。
2. **方向测完**：在 `docs/TEST_BUG_LEDGER.md` 的「五、收口」里写一段 —— 走了哪些路径、发现几条、几条已复现、几条判定"不是 bug"及原因。
3. **要人修**：把要立项的那几条**按优先级列出来**（严重度 `堵死` > `错数` > `可见` > `可疑`），立项的活儿由主会话按仓库规范做（`docs/changes/BUG-00xx.md` 九节 + README 一行 + AI_WORK_CLAIM 一行）。
