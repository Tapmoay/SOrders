from fastapi import APIRouter

from app.api.v1 import (
    ai_operations,
    ai_telemetry,
    arrears,
    auth,
    cash_flows,
    vehicles,
    customers,
    diagnostics,
    devices,
    driver_bills,
    driver_billing_rules,
    driver_settlements,
    exception_resolution,
    expenses,
    files,
    freight_settlement,
    freight_categories,
    freight_templates,
    inventory,
    invoices,
    expense_categories,
    ledger,
    notifications,
    operation_logs,
    contact_categories,
    order_products,
    order_templates,
    order_template_categories,
    suppliers,
    orders,
    orders_assignment,
    orders_delivery,
    orders_discount,
    orders_lifecycle,
    orders_media,
    orders_payment,
    orders_query,
    orders_return,
    place_categories,
    places,
    price_rules,
    product_categories,
    route_categories,
    products,
    purchase_orders,
    reports,
    return_requests,
    shipper,
    shipper_ledger,
    shipper_prices,
    stats,
    system,
    unit_conversions,
    usage,
    user_categories,
    users,
    vehicle_categories,
)

api_router = APIRouter()
api_router.include_router(auth.router)
# AI 调用计数上报（报告 §15 ② 的 AI_calls）：模型跑在 App 里，后端只有靠它才知道跑了几次 ——
# 见 `api/v1/ai_telemetry.py` 开头那段「服务端能知道的 vs 只有客户端知道的」。
api_router.include_router(ai_telemetry.router)
# AI 操作流水（2026-10-08 CHG-0082）：AI 发起的每一次请求一行（成功/失败都记），见 `api/v1/ai_operations.py`
api_router.include_router(ai_operations.router)
api_router.include_router(users.router)
# 设备登记（2026-10-11 FEAT-0018）：**公开**端点，App 拿 install_id 换一份服务端签名；
# 契约的另一半（账号侧看设备 / 解冻）在 `api/v1/users.py` 的 `/{id}/devices*` 上。
api_router.include_router(devices.router)
api_router.include_router(files.router)
api_router.include_router(freight_templates.router)
# 运费分类名册（2026-09-21）：运费模板与计费规则**共用**的一套分类，见 `api/v1/freight_categories.py` 开头
api_router.include_router(freight_categories.router)
api_router.include_router(freight_settlement.router)
api_router.include_router(shipper.router)
# 批发商自己那一本账（他给下游货主核销）：与 `ledger.router`（派单员开的账）是两本账，
# 谁都不写谁 —— 见 `api/v1/shipper_ledger.py` 开头。
api_router.include_router(shipper_ledger.router)
# 批发商**自己给下游**定的价（第三层价）：⛔ 与 `price_rules.router`（派单员给他定的第二层价）
# 不是一回事 —— 谁定的、进哪本账、差额归谁全不一样，见 `api/v1/shipper_prices.py` 开头那张对照表。
api_router.include_router(shipper_prices.router)
api_router.include_router(orders.router)
# orders 的**查询组**（列表 / 待派计数 / 详情）：2026-09-24 整改阶段 4 从 `orders.py` 纯搬迁到
# `api/v1/orders_query.py`（那个文件已经 2000+ 行）。两条 router **各自带** prefix="/orders"，
# 在这里**并列挂载** —— ⛔ 不能改成「orders 里 include 它」：include_router 会把前缀再拼一次，
# 变成 /api/v1/orders/orders/...（实测被契约快照当场抓到）。
# 两边没有同方法同形状的路径，所以先后无所谓；"静态路径不许被动态路径挡住"这条由
# `_tools/qa/_api_contract_snapshot.py` 的遮蔽分析机器盯着。
api_router.include_router(orders_query.router)
# orders 的**收款/现金**（pay / charge）与其付款家族私有助手：2026-09-24 阶段 4 从 orders.py 搬到
# `api/v1/orders_payment.py`。完成订单仍要写那笔钱 → `orders.py` 反过来从它 import（无环）。
api_router.include_router(orders_payment.router)
# orders 的**图片**（地址图 / 送达照片）：同样 2026-09-24 阶段 4 从 orders.py 纯搬迁到 `api/v1/orders_media.py`。
api_router.include_router(orders_media.router)
# orders 的**派单与定价**（批量派单 / 派单 / 撤回 / 拆单 / 定价 / 改运费）：2026-09-24 阶段 4 纯搬迁到
# `api/v1/orders_assignment.py`。
api_router.include_router(orders_assignment.router)
# orders 的**送达与司机**（完成 / 完成带图 / 接单 / 备注 / 补导航 / 撤销）：2026-09-24 阶段 4 纯搬迁到
# `api/v1/orders_delivery.py`。
api_router.include_router(orders_delivery.router)
# orders 的**生命周期**（创建 / 编辑 / 异常标记 / 回收站恢复 / 删除）与**退货**（唯一的执行入口）：
# 2026-09-24 阶段 4 纯搬迁到 `api/v1/orders_lifecycle.py` 与 `api/v1/orders_return.py`。
api_router.include_router(orders_lifecycle.router)
api_router.include_router(orders_return.router)
# orders 的**打折**（给这一单让价 / 取消折扣）：2026-10-07 新加（CHG-0071 / 台账 L-34）。
# 钱落到每一行（`order_products.line_total` 折后值），算法只有一处 `services/order_discount.py`；
# 这一条 router 同样**自带** prefix="/orders"，在这里并列挂载（理由见上面 orders_query 那一段）。
api_router.include_router(orders_discount.router)
# 预订单 / 订单模板（2026-09-22 用户要求：「预设好的订单，参数没有变直接下单」）。
# 它自己不生成订单 —— 真下单仍走上面那条 `orders.router`。
api_router.include_router(order_templates.router)
# 预订单分类名册（2026-09-22）：预订单页左栏那一列（用户：「左边是分类管理…右边就是订单」），
# 与商品/开销/运费分类同一套规矩，见 `api/v1/order_template_categories.py` 开头。
api_router.include_router(order_template_categories.router)
# 供应商 / 厂商档案 + 应付款（2026-09-22 用户要求：「给供应商付尾款」「采购设备」「邮费」）。
# 付款不是新表 —— 它就是 `cash_flows` 里 `biz_type=PAYMENT_SUPPLIER` 的一行，见 `api/v1/suppliers.py` 开头。
api_router.include_router(suppliers.router)
# 退货申请（2026-09-21）：货主**申请** → 派单员**实际执行**。与 `orders.router` 里那条
# `POST /orders/{id}/return`（唯一的执行路径）是两件事，见 `api/v1/return_requests.py` 开头。
api_router.include_router(return_requests.router)
api_router.include_router(places.router)
# 联系人分类名册（FEAT-0007）：与地点分类同一套规矩，见 `api/v1/contact_categories.py` 开头
api_router.include_router(contact_categories.router)
api_router.include_router(place_categories.router)
# 线路分类名册（2026-10-04）：三档页签都要有分类显示，线路这一档原本没有名册，见
# `api/v1/route_categories.py` 开头（与联系人/地点分类同一套规矩，第三份名册）。
api_router.include_router(route_categories.router)
# 账号分类 / 车辆分类名册（2026-10-05）：账户 / 司机 / 货主 / 批发商四个名册页共用一份账号名册，
# 车辆管理页一份。与商品分类同一套规矩（全局主数据、改名级联、占用中拒删），
# 见 `api/v1/user_categories.py` 与 `api/v1/vehicle_categories.py` 开头。
api_router.include_router(user_categories.router)
api_router.include_router(vehicle_categories.router)
api_router.include_router(order_products.router)
api_router.include_router(products.router)
api_router.include_router(product_categories.router)
# 开销分类名册（2026-09-20）：与商品分类同一套规矩，见 `api/v1/expense_categories.py` 开头
api_router.include_router(expense_categories.router)
api_router.include_router(price_rules.router)
api_router.include_router(reports.router)
api_router.include_router(ledger.router)
api_router.include_router(arrears.router)
api_router.include_router(inventory.router)
# 采购单（FEAT-0013）：与库存是同一条链 —— 一次进货同时写库存、成本价与供应商应付，
# 实现见 `app/services/purchase_service.py`（端点只做鉴权与出参）。
api_router.include_router(purchase_orders.router)
# 发票台账（FEAT-0014 第四期「税账」）：登记 / 开具 / 作废，销项与进项共用一条线，
# 实现见 `app/services/tax_service.py`（端点只做鉴权与出参）。
api_router.include_router(invoices.router)
api_router.include_router(notifications.router)
api_router.include_router(operation_logs.router)
api_router.include_router(stats.router)
# 异常订单的**解决**（第二轮 R2-05）：它原来写在 `stats.py` 里，做的却是**写业务状态** ——
# 报表层是「事实消费者，不是生产者」（方向指南 §八）。实现搬进订单域命令层、文件独立成
# `exception_resolution.py`，但 **URL 仍挂在 /stats 下**（那是客户端契约，搬了 App 就打死了）。
api_router.include_router(exception_resolution.router)
api_router.include_router(customers.router)
api_router.include_router(driver_bills.router)
api_router.include_router(driver_billing_rules.router)
api_router.include_router(driver_settlements.router)
api_router.include_router(expenses.router)
api_router.include_router(cash_flows.router)
api_router.include_router(vehicles.router)
# 系统级运行期配置（测试账号的默认 AI 配置，2026-09-21）：见 `api/v1/system.py`
api_router.include_router(system.router)
api_router.include_router(usage.router)
# 单位换算（用户 2026-09-24：一车 = 8 方）—— 新表，`create_all` 自动建
api_router.include_router(unit_conversions.router)
# ⭐ 只读诊断面（R4-49 · P4-②）：把 pricing_runtime 的只读那一半暴露成**实例级观测面**，
# 好让「两个正在跑的生产实例对同一份输入给出同一个 Decision」这件事**可以被直接测量**。
# ⛔ 它不是业务能力：不接受自拼的 Pricing Context、不写库、App 不调它 —— 见 diagnostics.py 的六条硬限制。
api_router.include_router(diagnostics.router)