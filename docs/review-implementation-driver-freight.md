# 评审结论 — 司机分类计费改造 落地方案

> 评审对象：docs/implementation-driver-freight.md（依据 docs/plan-driver-freight.md v2）
> 评审方法：逐条对照真实代码（backend/ + android/）核对，非纸面推断。
> 总体结论：**需修改**。方向正确、骨架完整，但有 1 处“现状”误判、1 处关键 Android 回归（¥0）、以及若干一致性/完整性缺口；修完即可实施。

---

## A. 方案核对结果（哪些准确、哪些有误）

### A-1 完全准确的判断
| 方案结论 | 核对结果 |
|---|---|
| enrich_order_out 未做角色过滤，订单明细金额会返回给司机 | **属实**。`services/order_response.py:10 enrich_order_out` 只对 SHIPPER 清空 internal_notes（L24-27），对 DRIVER 无任何金额处理；OrderOut 含 order_products（unit_price/line_total）原样输出。**API 层已漏货款，成立。** |
| 司机端“不显示金额”是 UI 层面且在漏 | **属实（且比方案说的更严重）**。`ui/driver/DriverOrdersScreen.kt:106` 直接复用 `OrderCard(order, onClick)`，而 `ui/common/OrderCard.kt:57` 计算 `total = sum(lineTotal)`、L197 显示 “¥”+total。**司机当前在 UI 上就能看到货款合计。** |
| OrderAssignBody / OrderBatchAssignBody 现不含 freight_fee | **属实**。`schemas/order.py`：OrderAssignBody={driver_id,internal_note}；OrderBatchAssignBody={order_ids,driver_id,internal_note}。 |
| UserCreate/UserUpdate/UserOut 现无 vehicle_type/billing_mode | **属实**。`schemas/user.py` 三模型均无这两字段；users 模型（models/user.py）也无。 |
| 新表零迁移、旧表加列走 schema_bootstrap | **属实**。`core/schema_bootstrap.py`：新表由 `Base.metadata.create_all(checkfirst=True)` 建（导入 models 即可）；旧表用 `ALTER TABLE ... ADD COLUMN` + try/except duplicate。users/orders 两个 section 已存在，加列插入对应分支即可。 |
| OrderProductOut.unit_price/line_total 目前非空 Decimal | **属实**。`schemas/order.py:20-22` 为 `Decimal`（非空）。 |
| Android DTO：OrderDto/UserDto 无新字段；OrderProductDto 金额为 String 默认 “0” | **属实**。`data/remote/dto/Dtos.kt`：UserDto 无这两字段；OrderProductDto.unitPrice/lineTotal 为 `String = "0"`（FlexibleStringSerializer）。 |
| 派单对话框在 DispatcherPoolScreen“选司机 UI” | **属实**。`DispatcherPoolScreen.kt:140-190` 的 AlertDialog 用 RadioButton 列司机；确认派单 button（L184）。 |
| coerceInputValues 等 Json 配置存在 | **属实**。`core/ApiClient.kt:28-31`：`Json { ignoreUnknownKeys=true; coerceInputValues=true; explicitNulls=false; }`。 |
| Modules.kt 派单作业组已存在，账本管理是叶子入口 | **属实**。`Modules.kt`：派单作业 group 有“待派单池/全部订单”；账本管理是 `ModuleEntry("账本管理", Routes.DISPATCH_LEDGER,...)`（无 children）。 |
| 操作日志可复用 ORDER_UPDATE | **属实**。enums.py OperationAction.ORDER_UPDATE 存在；但无专用运费 action。 |

### A-2 有误 / 需纠正的判断
1. **A3“现状 list 可能未过 enrich，需现场补” → 误判（好消息）**。`api/v1/orders.py` 的 list_orders 两个分支（L201 与 L229）**都**已调用 `enrich_order_out(o, db, current)`。列表早已过 enrich。门控只需改 enrich_order_out 本身即可覆盖列表。
2. **A3“批量派单返回，所有 OrderOut 出口都必须过门控” → 表述有误**。batch_assign_orders 返回的是 `OrderBatchAssignOut(results=[{order_id,success,detail}])`，**根本不返回 OrderOut**，无金额可泄。真正给司机的数据经 `push_order_assigned → 客户端 re-fetch list → enrich`。
3. **A8“给司机推单的 payload 一律 apply_driver_view_gating（剥货款…）” → 前提不成立**。`services/message_center.py` 全部推送/通知 payload 只携带 `{"order_id","order_no"}`（grep 证实 L97/110/133/152/177/190/216/236/260/298/339），**从不内嵌 order_products 金额**。后端只把 order_id 推给客户端，客户端刷新走 API 列表（enrich 已门控）。因此“推送 payload 也要门控”是冗余；唯一需要“不含货款”的是新增的“运费更新”通知文案（A4），它本身只放运费即可。
4. **业务计划 v2 第 2 节“司机端 UI 不显示金额” → 与事实相反**。UI 正在显示（见 A-1）。这点要在需求里改口径，否则团队以为“UI 已藏好、只需后端门控”，低估了 Android 侧工作量。

### A-3 关键新发现（方案未提及）
- **共享组件 OrderCard 是“司机列表”唯一的金额渲染点**。剥离后 `lineTotal=null → moneyToDouble(null)=0.0 → total=0`，卡片会显示 **“¥0”**（回归）。这是本方案最需要补的 Android 改动，方案 B3 只提“加运费行”，未提“隐藏/替换司机卡片的货款合计行”。
- **OrderDetailScreen 多处按货款渲染**（L130/209/345/352/371/441 用 `moneyToDouble(it.lineTotal)`），司机端同样会变成 ¥0，需同步处理。

---

## B. 遗漏与风险清单（按严重度）

### 🔴 高（必须修，否则回归/语义错误）
- **B-1 司机卡片/详情显示 ¥0**：OrderCard 与 OrderDetailScreen 对司机 viewer 剥离后合计=0 → 显示 “¥0”。需让卡片按角色/数据源区分：司机 SALARY → 隐藏金额行；司机 PIECE → 显示 “运费 ¥xx”（null→“运费待定”）；货主/派单员 → 照旧显示货款。OrderCard 需新增一个控制金额显示的参数（如 `showMoney: Boolean = true` 或传入 freight 逻辑）。
- **B-2 DTO 金额字段必须改为可空，否则无法区分“剥离”与“真实 0”**：见 E 特别评估③。当前 `coerceInputValues=true + explicitNulls=false`，若把 `OrderProductDto.unitPrice/lineTotal` 保持非空 `String="0"` 而后端发 null，coerce 会用默认值“0” → 卡片显示 ¥0，且**无法区分“被剥离”与“真实价格为0”**。必须改为 `String?`（可空），让 null 走 NullableSerializer 落到 null，节点判 null 隐藏。

### 🟠 中（一致性/完整性缺口）
- **B-3 快照写入位置**：方案把 `driver_billing_mode_snapshot` 的写入放在 assign_order API 层，但单派与批量派共用 `assign_driver()`（services/order_flow.py:61）。建议把快照写入放进 `assign_driver` 内部（单/批/改派自动统一），而不是在两个 API 各自维护；否则漏一处在批量就会丢快照。
- **B-4 结算“月份”过滤字段未指明**：司机运费结算按司机×月聚合，应过滤 `delivered_at`（送达时间），不是 `created_at`。方案未指定，易错。
- **B-5 改费清空语义未定义**：POST /orders/{id}/freight 是否允许传 null（清空→“待定”）？DELIVERED/CANCELLED 拒绝已给；但“改费”是否允许改为 0？建议：非负、可传 null 清空为待定，审计记录 old/new（new 为 null 也记）。
- **B-6 批量派单对话框不应出现运费输入**：DispatcherPoolScreen 的派单对话框在 `selectionMode`（批量）时不应显示“运费+模板选择”，只有单派（非 selectionMode）才显示。方案 B2 未区分，UI 会与后端“批量不填运费”矛盾。
- **B-7 司机“本月运费合计”聚合口径**：复用列表客户端合计可行（list 支持 status_filter/date_from/date_to），但需注意 `list_orders` 的 date_from/date_to 过滤的是 `created_at`；“本月运费”应以 `delivered_at` 为准，客户端用 list 的 date 区间不一定等于送达月份。建议：结算/本月合计在服务端统一按 delivered_at 提供（可复用一个聚合接口），或明确以 created_at 口径并接受偏差。建议服务端提供（若 P1 收紧）。
- **B-8 运费可见性判定主体**：门控取 `order.driver_billing_mode_snapshot`（无则 `resolve_billing_mode(order.driver)`）。注意 `resolve_billing_mode` 入参应是**订单的指派司机**（enrich 里已有的 `du`），不是 viewer 本人（虽然 driver 只能看自己的单，但代码上应明确用 du，避免命名混淆）。
- **B-9 billing_mode 推导与校验**：UserUpdate 改 vehicle_type 时，若未显式传 billing_mode 应重新推导；仅 DRIVER 角色允许设 billing_mode（货主/派单员忽略置空）。方案 A7 已提，但需明确落库与推导的优先级（显式值 > 车型推导）。
- **B-10 审计 action 建议专设**：改费用 `ORDER_UPDATE` 会与普通编辑混同；建议新增 `OperationAction.ORDER_FREIGHT`，便于溯源。若坚持复用 ORDER_UPDATE，请在 change_payload 带 `{"field":"freight_fee","before","after"}`。

### 🟡 低（可后补，不影响正确性）
- **B-11 vehicle_type 索引**：模型列 `index=True`，但 schema_bootstrap 的 ALTER TABLE ADD COLUMN **不会**为旧表建索引，需额外 `CREATE INDEX IF NOT EXISTS ix_users_vehicle_type`（参考 username 的做法）。非必需（正确性依赖不大），但方案说 index=True 就应落实。
- **B-12 模板 vehicle_type 校验**：FreightTemplateCreate/Update 的 vehicle_type(可空) 建议用 `VehicleType | None` 枚举校验，而不是裸 String(16)，避免脏值。
- **B-13 freight_fee 精度**：方案 Numeric(12,2)。订单货款用 Numeric(14,4)。运费按元保留 2 位即可，但若与金额显示 formatMoney 统一建议对齐 2 位（现状可接受）。
- **B-14 快照字段对货主/派单员暴露**：OrderOut 含 `driver_billing_mode_snapshot`，对货主暴露略多余（无害），可考虑只在需要时输出；不强制。

---

## C. 修改建议（具体到文件）

### 后端
1. **services/order_response.py**：在 `enrich_order_out` 内，viewer 为 DRIVER 时调用公共函数 `apply_driver_view_gating(data, order, du, viewer, db)`：遍历 `data["order_products"]` 把每项 `unit_price`/`line_total` 置 None；`data["freight_fee"]` 仅当 `_driver_mode = order.driver_billing_mode_snapshot or resolve_billing_mode(du)` 为 PIECE 才保留，否则 None。公共函数放同文件，列表/详情/全部出口共用。**不需要**对推送/通知额外加门控（见 A-2-3）。
2. **schemas/order.py**：`OrderProductOut.unit_price/line_total → Decimal | None`；`OrderOut + freight_fee: Decimal|None、driver_billing_mode_snapshot: str|None`；`OrderAssignBody + freight_fee: Decimal|None = None`；OrderBatchAssignBody 不动。
3. **services/order_flow.py**：`assign_driver` 内写 `order.driver_billing_mode_snapshot = resolve_billing_mode(driver)`；`recall_dispatch` 保留快照（重派覆盖）。`assign_driver` 可加可选 `freight_fee` 入参以支持单派带价（batch 不传）。
4. **api/v1/orders.py**：`assign_order` 把 `body.freight_fee` 写入 `order.freight_fee`（随 commit 落库）；新增 `POST /orders/{id}/freight`（仅派单员；DELIVERED/CANCELLED 拒绝；审计 change_payload 含 old/new；若订单司机快照为 PIECE → 推送“运费更新”通知+realtime）。`batch_assign_orders` 复用 assign_driver 写好快照即可。
5. **schemas/user.py**：UserCreate/UserUpdate 加 `vehicle_type: VehicleType|None`、`billing_mode: BillingMode|None`；UserOut 加两字段。
6. **api/v1/users.py**：create_user/update_user 接收并落库；`resolve_billing_mode` 用于缺省推导；仅 DRIVER 有意义。
7. **models/enums.py**：新增 `VehicleType`、`BillingMode`；可加 `OperationAction.ORDER_FREIGHT`。
8. **models/user.py / order.py**：加列（vehicle_type String(16) nullable index、billing_mode String(16) nullable；order.freight_fee Numeric(12,2) nullable、driver_billing_mode_snapshot String(16) nullable）。
9. **models/freight_template.py**：新模型（含 created_by FK、TimestampMixin）。
10. **schemas/freight_template.py**：Create/Update/Out（vehicle_type 用枚举校验）。
11. **api/v1/freight_templates.py**：CRUD，仅派单员；注册 main.py。
12. **api/v1/freight_settlement.py**：GET /freight-settlement?month=YYYY-MM（仅派单员），**按 delivered_at** 聚合 DELIVERED 且 freight_fee 非空。
13. **core/schema_bootstrap.py**：users section 加 vehicle_type/billing_mode 的 ALTER（含 CREATE INDEX IF NOT EXISTS ix_users_vehicle_type）；orders section 加 freight_fee/driver_billing_mode_snapshot 的 ALTER；freight_templates 由 create_all 自动建。
14. **services/message_center.py**：新增“运费更新”通知（recipient=司机，文案含新运费，payload 只带 order_id/order_no，**绝不带货款**）。

### Android
1. **data/remote/dto/Dtos.kt**：`OrderProductDto.unitPrice/lineTotal → String?`；`OrderDto + freightFee:String?、driverBillingModeSnapshot:String?`；`UserDto + vehicleType:String?、billingMode:String?`；新增 FreightTemplateDto、FreightUpdateRequest、FreightSettlementDto；`OrderAssignRequest + freightFee:String?`。
2. **core/ApiClient.kt**：保持 `coerceInputValues=true`（不必关闭）；但**不要依赖它做语义判断**（见 E-③），以 `String?` 为准。
3. **data/remote/api/Apis.kt**：UserApi 请求体加字段；OrderApi + updateFreight()；新增 FreightTemplateApi、FreightSettlementApi。
4. **data/repo/AppRepository.kt**：包装 templates()/saveTemplate()/deleteTemplate()/updateFreight()/settlement()。
5. **ui/common/OrderCard.kt**：新增控制金额显示的参数（如 `showMoney: Boolean = true`），司机列表传 false 并按 freight/status 显示“运费 ¥xx / 运费待定 / 不结算”；货主/派单员默认 true 显示货款。**这是本方案最关键的 Android 修正。**
6. **ui/order/OrderDetailScreen.kt**：司机视角：SALARY 无金额行；PIECE 显示运费（null→待定）；撤回/撤销标注“不结算”；改费按钮送达/撤销后隐藏。
7. **ui/driver/DriverOrdersScreen.kt**：已完成 tab 卡片传 showMoney=false 并按 freight 渲染；撤回/撤销标“不结算”。
8. **ui/dispatcher/DispatcherPoolScreen.kt**：单派（非 selectionMode）且选中司机 billingMode==PIECE 时显示运费输入 + “从模板”按钮；批量不显示。
9. **ui/dispatcher/UsersManageScreen.kt**：创建/编辑司机加“车型”三选；列表标注车型/按单计费。
10. **ui/dispatcher/FreightTemplatesScreen.kt**（新）+VM。
11. **ui/dispatcher/FreightSettlementScreen.kt**（新）+VM。
12. **ui/profile/ProfileScreen.kt**：挂车司机“本月运费合计”卡片 → **ui/driver/DriverFreightScreen.kt**（新）+VM。
13. **ui/nav/Routes.kt**：新增 `DISPATCH_FREIGHT_TEMPLATES`、`DISPATCH_FREIGHT_SETTLEMENT`、`DRIVER_FREIGHT`（沿用现有 DISPATCH_/DRIVER_ 前缀，勿用方案里的大写裸名）。
14. **ui/nav/NavGraph.kt**：三条 composable 注册。
15. **ui/nav/Modules.kt**：派单作业组加“订单模板”；把“账本管理”改为分组（children=[账本, 司机运费结算]）或新增独立入口——**注意当前账本管理是叶子，改成分组是额外改动**。

---

## D. 实施顺序调整

方案 C 大体合理，建议微调：

1. **先改后端序列化与模型**（A1+A9）+ **门控**（A3，含 OrderProductOut 可空）→ 重启后端 → **立即用 curl 验证司机/货主/派单员三视角**（货主明细金额可见、司机明细金额为 null），先堵漏。
2. **修 OrderCard + OrderDetailScreen 的共享组件**（B-1/B-2）→ 这是 Android 侧唯一高风险回归点，**必须与后端门控同步落地**，否则司机端显示 ¥0。
3. 派单/运费/模板/结算（A4/A5/A6/A7/A8）→ curl 冒烟。
4. Android 数据层（B1）→ 用户/派单 UI（B2）→ 路由（B4）→ 司机端（B3）。
5. 场景验证（D）。

> 两点调整：(a) 把“OrderCard 角色化金额显示”提到司机端 UI 的第一优先级（与后端门控同批），不是最后；(b) 把“快照写入”放进 assign_driver，避免单/批分支漏写。

---

## E. 特别评估（四点）

### ① 司机视角剥离货款：OrderProductOut 金额改可空的影响面
- **必要**：gate 用 None 表示“剥离”，OrderOut.order_products 用 OrderProductOut 校验，必须允许 None，否则 enrich 重建 order 会校验失败。
- **波及**：(a) `api/v1/order_products.py` 的 4 个独立端点（list/create/detail/patch）共用 OrderProductOut，改可空是“放宽”——DB 该列非空，实际仍回 Decimal，仅 schema 允许 None；功能无损，但需**回归 curl 确认 order_products 仍返回数字**。(b) Android 侧 **OrderCard / OrderDetailScreen** 是实际影响面（见 ②③），因为 `moneyToDouble(lineTotal)` 对 null→0。货主/派单员的账本、列表、详情不受影响（viewer 非 driver，gate 不触发，金额保留）。
- **结论**：服务端影响可控且集中；**真正的风险在 Android 共享组件**。

### ② 门控放 enrich_order_out 是否覆盖所有出口
- **已逐一核对**：orders.py 全部返回 OrderOut 的出口（list ×2、get、create、update、exception、complete_with_upload、driver_ack、driver_note、assign、complete、cancel、pay、charge、recall）**都**经过 enrich_order_out。**单点即全覆盖，无遗漏出口。**
- **计划的两处担心不成立**：list 已过 enrich；batch 返回 result 信封（不进 enrich，但无需进，因为不带订单数据）。推送/通知 payload 只带 order_id/order_no，真正数据经客户端 re-fetch 列表并过 enrich。
- **结论**：把门控只写进 enrich_order_out（viewer=DRIVER 分支）即可满足 S1/S4“序列化统一门控”。计划的“推送/通知也要门控”应删除（或仅用于确保新增运费通知文案不含货款）。

### ③ coerceInputValues 对 null 的 Kotlinx 行为
- 已确认 `ApiClient.kt` 配置 `coerceInputValues=true`、`explicitNulls=false`。
- 对**非空** `String="0"` 属性遇后端 `null`：coerceInputValues=true 会用默认值“0”（不抛异常），结果是“0”，**无法区分剥离与真实0**。
- 对 **FlexibleStringSerializer**（`KSerializer<String>`）遇 `JsonNull`：`JsonNull` 属于 `JsonPrimitive` 子类，deserialize 会走 `el.content` 返回字符串 **“null”**（字面量），更糟。
- **结论**：**不要依赖 coerceInputValues 做语义判断，也不必关它。** 正确做法是把 `OrderProductDto.unitPrice/lineTotal` 改为 **`String?`（可空）**——kotlinx 会用 NullableSerializer 包裹，null→null，非 null→内容；卡片判 null 隐藏。**必须实测**（跑一次 5558 司机拿一张 PIECE 单与一张 SALARY 单，确认 null 不崩溃且被正确隐藏）。

### ④ 快照字段写法与“司机换类型”兼容
- 设计正确：`driver_billing_mode_snapshot` 派单时写入（建议放 assign_driver），可见性优先用快照、无快照回退当前 resolve_billing_mode(driver)；老单（无快照）回退当前类型。**与“司机换类型保护”兼容。**
- 边界：司机从 piece 改 salary（或反向）不影响已派单快照（正确，冻结当时类型）；改派（recall→重派）覆盖为当次司机类型（方案已说明）。
- **唯一理论缺口**：结算按 `freight_fee 非空 + DELIVERED`，与“该单计费入口 = 快照=PIECE”不是同一判断。若出现“快照=salary 但 freight_fee 已填”（现实中 UI 不会给 salary 单填运费），该单会进结算却对司机不可见。建议：结算视图同时展示该单的 bill mode/快照，或结算口径与可见性一致（按快照=PIECE 且 freight 非空）。**风险低，建议在结算视图保留一列类型标签即可。**
- 建议：快照再多存一个 freight value 不必要（freight 是订单字段）；快照只存 bill mode 是够的。

---

## 总体评价
**需修改。** 方案对数据模型、门控思路、结算/视图拆分、兼容策略的判断基本准确（尤其“API 已漏货款”这个核心现实问题），骨架完整。但需修正 3 处：①“list 未过 enrich/推送/批量要门控”的误判（实际单点 enrich 即全覆盖）；②OrderCard/OrderDetailScreen 对司机显示的 ¥0 回归（方案未处理，最关键）；③DTO 金额字段必须改可空（否则 coerceInputValues 掩盖剥离语义）。补上 B 清单的完整性缺口后可按 D 顺序实施。
