# 03 后端代码详解

## 1. app/ 分层

```
app/
├── main.py            # create_fastapi_app()：CORS + api_router(prefix=/api/v1) + /health + 静态 uploads
│                      # lifespan：每 24h 清理过期已撤销订单；app = socketio.ASGIApp(sio, other=fastapi)
├── config.py          # Settings（.env 可覆盖）：api_v1_prefix、database_url、jwt、amap、sms_reveal_code
├── database.py        # create_engine(SQLite StaticPool 或 MySQL pool_pre_ping)；SessionLocal；bootstrap_schema
├── deps.py            # CurrentUser / require_permission / get_db
├── redis_client.py    # 可选 Redis 健康检查（本地无 Redis 仍可用）
├── core/
│   ├── rbac.py        # Permission 枚举 + ROLE_PERMISSIONS；role_has_permission（派单员恒真）
│   ├── security.py    # hash_password / verify_password / create_access_token / decode_token
│   ├── schema_bootstrap.py  # 启动即 ALTER TABLE 补列（不加列就删掉；大小写/驱动兼容）
│   ├── socket_io.py   # sio = socketio.AsyncServer
│   └── ws_hub.py      # 房间管理/广播（按角色房间）
├── models/            # SQLAlchemy 2.0 ORM（__init__ 汇总导出）
├── schemas/           # Pydantic v2（Out 含 from_attributes；入参带校验）
├── api/v1/            # 路由（薄层：参数校验→services 或直接查询→Out）
└── services/          # 业务逻辑（见 §3）
```

## 2. 数据模型（models/）

| 表 | 文件 | 关键字段 |
|---|---|---|
| users | user.py | role/is_member/billing_mode/vehicle_type/salary/password_hash |
| orders | order.py | status/order_no/shipper_id/temp_shipper_name/driver_id/freight_fee/collect_cash/payment_method/paid/arrears_unit_*/delivered_at/expected_deliver_before/is_exception/exception_*/damage_photo_*, image_urls(JSON), driver_billing_mode_snapshot |
| order_products | order.py | product_name_snapshot/quantity/unit_price/line_total/**cost_price_snapshot**/**damage_quantity** |
| products | product.py | name/unit_price/unit/tier_prices(JSON 多档)/stock(初值)/image |
| price_rules | price_rule.py | shipper_id(批发商)/product_id/special_unit_price |
| ledger | ledger.py | shipper_id/temp_shipper_name/entry_date/product_name/quantity/unit_price/total/source(ORDER|MANUAL)/order_id/note |
| cash_flows | cash_flow.py | flow_date/direction(IN|OUT)/amount/party_type/party_name/channel/biz_type/order_id/doc_id |
| expenses | expense.py | exp_date/category(8类)/amount/driver_id/vehicle_id/order_id/note |
| driver_bills | driver_bill.py | driver_id/bill_type(PIECE|SALARY)/order_id/month/amount/status(OPEN|SETTLED)/settled_doc_id |
| driver_settlements | driver_settlement.py | driver_id/settle_type/month/period_from/to/amount/status(DRAFT|CONFIRMED|PAID|CANCELLED)/order_ids(JSON) |
| arrears_units | arrears.py | name/phone/remark |
| shipper_addresses/locations/contacts | shipper.py | 三列表结构（线路/地点/联系人）；image_urls(JSON) |
| customers | customer.py | kind(registered|tmp)/user_id/is_member/arrears_unit_id |
| shipper_receipts | shipper_receipt.py | customer_id/amount/method/received_at/order_ids/settle_mode |
| inventory_movements | inventory.py | product_id/type(IN|OUT|ADJUST)/qty/note |
| notifications | notification.py | user_id/title/content/type/read |
| operation_logs | operation_log.py | operator_id/order_id/action/change_content |
| vehicles | vehicle.py | plate_no/vehicle_type/driver_id/is_active |
| freight_templates | freight_template.py | name/from_place/to_place/fee/remark |
| ledger_export_jobs | export_job.py | 异步导出任务状态机 |

### 订单状态枚举（enums.py OrderStatus）
`PENDING_DISPATCH → ASSIGNED → DELIVERED | CANCELLED`（司机端还分分派中/已接单展示；另有 COMPLETED 视图状态）

## 3. services/ 关键服务

| 文件 | 职责 |
|---|---|
| order_flow.py | 订单创建/派单/完成/撤销/召回 的编排；`resolve_billing_mode` 计费快照 |
| order_response.py | OrderOut 组装 + 司机视图门控（apply_driver_view_gating）+ driver_billing_mode 快照 |
| ledger_sync.py | 已送达订单自动同步账本（幂等） |
| ledger_response.py / ledger_export.py / ledger_export_worker.py | 账本出入参 / Excel / 异步任务 |
| accounting_service.py | 账本 V2 核心（司机账单/结算/收款/开销/资金流水唯一写入点） |
| stats_service.py | 报表/统计聚合（driver_performance/exception_orders/shipper_*） |
| stats_export.py | 看板 Excel 导出（openpyxl 内存流） |
| message_center.py / message_push.py | 站内信 + Socket 推送 |
| operation_log_service.py | 敏感操作审计写日志 |
| auth_service.py / token_response.py / sms_code.py | 登录/JWT/短信 |
| shipper_contact_service.py | 联系人唯一性校验（重复电话 409） |
| push_events.py | 订单状态事件广播 |
| cancelled_order_retention.py | 过期已撤销订单清理（24h 任务） |

## 4. 数据库迁移注意

- **没有 Alembic**：Schema 演进全走 `core/schema_bootstrap.py` 的 `ALTER TABLE ... ADD COLUMN`（幂等，检测列名存在性）
- 新加列：在 bootstrap 添加（参考现有 `if "xx" not in col_names` 模式）
- 本地 SQLite：`backend/sorders.db`（改动 .py 重启生效；改表结构无需删库，bootstrap 自动补）

## 5. 常用后端维护脚本

| 脚本 | 用途 |
|---|---|
| backend/scripts/seed_dev_users.py | 写入/补种子账号 138000000x |
| backend/scripts/reset_dev_passwords.py | 全部密码重置为 pass12345 |
| backend/scripts/init_tables.py | 手动建表（一般不需要，导入即建） |
| backend/scripts/backfill_cost_snapshots.py | 历史订单补齐 cost_price_snapshot（报表毛利前提） |
| backend/tests/ | pytest（conftest 造测试账号；注意与 seed 账号一致） |

## 6. 测试入口

```powershell
cd D:AProjectsASDHordersackend
python -m pytest tests/ -x -q
```

## 7. 常见联调手段

- 登录拿 token → Invoke-RestMethod（PowerShell）或 python requests
- 直接操作数据库：`python -c "from app.database import SessionLocal; ..."`（注意 GBK 输出 → sys.stdout.reconfigure(encoding='utf-8')）
- Socket 联调：`_sio_test.py` 等参考（python-socketio client）
