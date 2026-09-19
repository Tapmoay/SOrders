# -*- coding: utf-8 -*-
"""服务器手术式补丁：orders分页 / users权限 / 金额非负（与本地 p 分支一致，逐处唯一性校验）"""
import io

PAIRS = [
    ("/opt/SOrders/backend/app/api/v1/orders.py", "    date_from: str | None = Query(None, alias=\"date_from\", description=\"YYYY-MM-DD（含当天）\"),\n    date_to: str | None = Query(None, alias=\"date_to\", description=\"YYYY-MM-DD（含当天）\"),\n) -> list[OrderOut]:\n    role = user_role_key(current)\n    qtrim = (search_q or \"\").strip() or None", "    date_from: str | None = Query(None, alias=\"date_from\", description=\"YYYY-MM-DD（含当天）\"),\n    date_to: str | None = Query(None, alias=\"date_to\", description=\"YYYY-MM-DD（含当天）\"),\n    limit: int | None = Query(None, ge=1, le=5000, description=\"返回条数上限（待派池缺省=300，其余缺省=全量）\"),\n) -> list[OrderOut]:\n    role = user_role_key(current)\n    effective_limit = limit\n    if effective_limit is None and role == UserRole.DISPATCHER.value and status_filter == OrderStatus.PENDING_DISPATCH:\n        effective_limit = 300  # 待派池防护：万级积压时只取最新300单，防接口十几秒/内存暴涨\n    qtrim = (search_q or \"\").strip() or None"),
    ("/opt/SOrders/backend/app/api/v1/orders.py", "        orders = list(db.scalars(stmt).unique().all())\n        return [enrich_order_out(o, db, current) for o in orders]", "        if effective_limit is not None:\n            stmt = stmt.limit(effective_limit)\n        orders = list(db.scalars(stmt).unique().all())\n        return [enrich_order_out(o, db, current) for o in orders]"),
    ("/opt/SOrders/backend/app/api/v1/orders.py", "    orders = list(db.scalars(q).unique().all())\n    return [enrich_order_out(o, db, current) for o in orders]", "    if effective_limit is not None:\n        q = q.limit(effective_limit)\n    orders = list(db.scalars(q).unique().all())\n    return [enrich_order_out(o, db, current) for o in orders]"),
    ("/opt/SOrders/backend/app/api/v1/users.py", "    if body.salary is not None and user_role_key(u) == UserRole.DRIVER.value:\n        u.salary = body.salary\n    # 司机车型/计费方式：仅司机角色有意义；billing_mode 缺省由车型自动推导\n    if user_role_key(u) == UserRole.DRIVER.value:", "    # 安全修复：工资/计费方式/车型仅派单员可改（司机自改会绕过结算规则、篡改工资）\n    if (body.salary is not None or body.billing_mode is not None or body.vehicle_type is not None) and not is_dispatcher:\n        raise HTTPException(status_code=403, detail=\"仅派单员可修改工资/计费方式/车型\")\n    if body.salary is not None and user_role_key(u) == UserRole.DRIVER.value:\n        u.salary = body.salary\n    # 司机车型/计费方式：仅司机角色有意义；billing_mode 缺省由车型自动推导\n    if user_role_key(u) == UserRole.DRIVER.value:"),
    ("/opt/SOrders/backend/app/schemas/order.py", "class OrderProductIn(BaseModel):\n    product_id: int | None = None\n    product_name_snapshot: str = Field(..., min_length=1, max_length=256)\n    quantity: int = Field(default=1, ge=1)\n    unit_price: Decimal = Field(default=Decimal(\"0\"))\n    line_total: Decimal = Field(default=Decimal(\"0\"))", "class OrderProductIn(BaseModel):\n    product_id: int | None = None\n    product_name_snapshot: str = Field(..., min_length=1, max_length=256)\n    quantity: int = Field(default=1, ge=1)\n    unit_price: Decimal = Field(default=Decimal(\"0\"), ge=0)\n    line_total: Decimal = Field(default=Decimal(\"0\"), ge=0)"),
    ("/opt/SOrders/backend/app/schemas/order.py", "    product_name_snapshot: str = Field(..., min_length=1, max_length=256)\n    quantity: int = Field(default=1, ge=1)\n    unit_price: Decimal = Field(default=Decimal(\"0\"))\n    line_total: Decimal | None = Field(default=None)", "    product_name_snapshot: str = Field(..., min_length=1, max_length=256)\n    quantity: int = Field(default=1, ge=1)\n    unit_price: Decimal = Field(default=Decimal(\"0\"), ge=0)\n    line_total: Decimal | None = Field(None, ge=0)"),
    ("/opt/SOrders/backend/app/schemas/order.py", "class OrderProductUpdate(BaseModel):\n    product_id: int | None = None\n    product_name_snapshot: str | None = Field(None, min_length=1, max_length=256)\n    quantity: int | None = Field(None, ge=1)\n    unit_price: Decimal | None = None\n    line_total: Decimal | None = None", "class OrderProductUpdate(BaseModel):\n    product_id: int | None = None\n    product_name_snapshot: str | None = Field(None, min_length=1, max_length=256)\n    quantity: int | None = Field(None, ge=1)\n    unit_price: Decimal | None = Field(None, ge=0)\n    line_total: Decimal | None = Field(None, ge=0)"),
]

for path, old, new in PAIRS:
    try:
        s = io.open(path, encoding="utf-8").read()
    except Exception as e:
        print("READ_FAIL", path, e); continue
    if old not in s:
        print("MISS:", path, old[:70].replace(chr(10), "|")); continue
    n = s.count(old)
    if n != 1:
        print("MULTI(%d):" % n, path, old[:70].replace(chr(10), "|")); continue
    io.open(path, "w", encoding="utf-8").write(s.replace(old, new))
    print("OK:", path)
