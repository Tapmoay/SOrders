# 司机分类计费改造 — 代码落地方案 v2（评审后修订）

> 修订：已采纳评审 B-1~B-14 全部意见。关键修正：①现状澄清——司机端 UI 已在 OrderCard 显示货款合计（sum lineTotal），门控后必须同步隐藏否则显示 ¥0；②快照写入统一放 assign_driver；③OrderOut 不暴露快照字段；④结算按 delivered_at 口径；⑤批量派单 UI 无运费输入。

## A. 后端改动

### A1 枚举与模型
- enums.py：VehicleType(SMALL/LARGE/TRAILER)、BillingMode(SALARY/PIECE)；**OperationAction 新增 ORDER_FREIGHT**（改运费审计专用）。
- models/user.py：+vehicle_type(String(16) nullable,index)、+billing_mode(String(16) nullable)。resolve_billing_mode(u)：有值用值；trailer→PIECE；其余→SALARY。
- models/order.py：+freight_fee(Numeric(12,2) nullable)、+driver_billing_mode_snapshot(String(16) nullable，内部用，**不进 OrderOut**)。
- 新 models/freight_template.py：id/name/from_place/to_place/vehicle_type(nullable)/fee(Numeric(12,2))/remark/created_by/TimestampMixin。

### A2 schemas
- user.py：UserCreate/UserUpdate +vehicle_type: VehicleType|None、billing_mode: BillingMode|None；UserOut 同加。
- order.py：OrderOut +freight_fee: Decimal|None（**不加快照字段**）；OrderAssignBody +freight_fee: Decimal|None=None；OrderProductOut.unit_price/line_total → Decimal|None。
- 新 freight_template schemas：Create/Update/Out（vehicle_type 校验 ∈{small,large,trailer}或空；fee ge=0）。

### A3 序列化门控（最高优先）
- services/order_response.py enrich_order_out：
  - viewer 为司机 → 每项 order_products 的 unit_price/line_total 置 None；freight_fee 仅当 resolve_billing_mode(order.driver) 且优先 order.driver_billing_mode_snapshot 为 PIECE 才保留，否则 None。
  - 公共函数 apply_driver_view_gating(data, order, driver)，列表/详情/推送共用；核对 list_orders 出口必须过 enrich。
- **核对后确认**：batch-assign 返回 OrderBatchAssignOut 无 OrderOut，不用门控；推送走 message_center 不内嵌 OrderOut，但推送文本若含金额需按同一规则。

### A4 派单与运费
- services/order_flow.py assign_driver() 内部统一写：order.driver_billing_mode_snapshot = resolve_billing_mode(driver)。
- api/v1/orders.py assign_order：body.freight_fee → order.freight_fee（可空）。
- 新 POST /orders/{id}/freight（仅派单员）：body={freight_fee: Decimal|None}；**可传 null 清空回"待定"**；非负校验；DELIVERED/CANCELLED 拒绝；审计 action=ORDER_FREIGHT payload={old,new}（null 也记）；司机快照为 PIECE → notification+WS "运费更新"。
- recall_dispatch 不清 freight_fee（重派沿用）。

### A5 订单模板
- 新 api/v1/freight_templates.py：GET/POST/PUT/DELETE 仅派单员；schema 校验车型枚举与 fee 非负。

### A6 结算
- 新 api/v1/freight_settlement.py：GET /freight-settlement?month=YYYY-MM。
  - 派单员：聚合当月 **delivered_at** 的 DELIVERED 且 freight_fee 非空订单 → 按司机分组（司机名/单数/合计/明细）。
  - 司机角色：返回自己当月合计+明细（同一接口按角色变体，司机端"本月运费合计"用，避免客户端日期口径错误）。

### A7 用户接口
- users.py create_user/update_user：接收并校验两字段（仅 DRIVER 生效；billing_mode 缺省由车型推导）。

### A8 数据库迁移
- schema_bootstrap.py：users 两列、orders 两列 ADD COLUMN + **CREATE INDEX IF NOT EXISTS**（users.vehicle_type）；freight_templates 建表（checkfirst）。

## B. Android 改动

### B1 数据层
- Dtos.kt：UserDto +vehicleType/billingMode；OrderDto +freightFee(String?)；**OrderProductDto.unitPrice/lineTotal 改 String? = null**（区分"剥离"与"0"）；FreightTemplateDto；OrderAssignRequest +freightFee；FreightUpdateRequest。
- Apis.kt：UserApi 加字段；OrderApi +updateFreight；新 FreightTemplateApi、FreightSettlementApi。
- AppRepository.kt：templates/saveTemplate/deleteTemplate/updateFreight/freightSettlement。

### B2 派单员 UI
- UsersManageScreen+VM（司机池）：车型三选胶囊；列表车型标签（挂车→"按单计费"）。
- 新 FreightTemplatesScreen+VM：列表/新建/编辑/删除（SoTextField+车型胶囊）。入口：派单作业组"订单模板"（icon=ReceiptLong，色=MoneyOrange）。
- DispatcherPoolScreen 派单对话框：**仅单派（非 selectionMode）且司机 PIECE** 时显示"运费"SoTextField+"从模板选择"（模板弹窗带出 fee）；批量派单不显示运费。
- OrderDetailScreen+VM（派单员）：运费行+"修改运费"按钮（DELIVERED/CANCELLED 后隐藏）。
- 新 FreightSettlementScreen+VM（派单员）：月份胶囊+按司机分组（司机/单数/合计/明细）。入口：账本管理组"司机运费结算"。

### B3 司机端 UI（含 ¥0 回归修复）
- OrderCard.kt：**司机角色（SALARY 或 PIECE）不渲染货款合计行**（原 total=sum(lineTotal) 对司机隐藏）；PIECE 且 freightFee 非空时显示"运费 ¥xx"（null→"运费待定"）。货主视角照旧显示货款。
- OrderDetailScreen：司机视角金额区同样按角色隐藏货款、PIECE 显示运费；撤回/撤销标注"不结算"。
- ProfileScreen：挂车司机"本月运费合计"卡片 → 新 DriverFreightScreen+VM（调 /freight-settlement 当月数据，列表+合计）。
- DriverOrdersScreen：完成 tab 卡片运费显示（经 OrderCard 复用）。

### B4 路由
- Routes.kt + NavGraph.kt：FREIGHT_TEMPLATES / FREIGHT_SETTLEMENT / DRIVER_FREIGHT。
- Modules.kt：两个入口（派单作业组+账本管理组）。

## C. 实施顺序
1. A1+A8 模型迁移 → 重启后端
2. A2+A3+A4+A5+A6+A7 接口门控 → curl 冒烟
3. B1 → B2/B3/B4 → dev-build.ps1 三台
4. 场景验证

## D. 验证清单
1. 司机管理：司机 A 挂车、司机 B 小车。
2. 模板：东城→西城 挂车 ¥800。
3. 货主下单→派给 A（模板带 800）：A 卡片/详情"运费 ¥800"，通知含 800。
4. B 接单：UI 无任何金额；curl 验证 order_products 单价 null、freight_fee null。
5. 送达：A"我的"本月合计 800；派单员结算视图 800。
6. 改费 800→850：A 收通知；审计 ORDER_FREIGHT old/new。
7. 清空运费（null）：A 端回"待定"。
8. 撤销单：不计费；标注"不结算"。
9. 回归：货主订单/账本金额正常；派单员视图全字段正常。

## E. 风险
- enrich_order_out 全局出口：回归货主/派单员金额显示。
- coerceInputValues 与 null：OrderProductDto 改 String? 后实测序列化。
- 老司机 billing_mode=null → resolve=SALARY 零风险。
