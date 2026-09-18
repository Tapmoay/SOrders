# 03 后端代码详解

## 1. app/ 分层

```
app/
├── main.py            # create_fastapi_app()：CORS + api_router(prefix=/api/v1) + /health + 静态 uploads
│                      # lifespan：挂数据保留策略（data_retention.py：3 年 / 软删 30 天）；app = socketio.ASGIApp(sio, other=fastapi)
├── config.py          # Settings（.env 可覆盖）：api_v1_prefix、database_url、jwt、amap
├── database.py        # create_engine(SQLite StaticPool 或 MySQL pool_pre_ping)；SessionLocal；bootstrap_schema
├── deps.py            # CurrentUser / require_permission / get_db
├── redis_client.py    # **只有一个用途**：给 /health 提供 redis_ok()。多 worker 的 Socket 连接共享不在这里
├── core/
│   ├── rbac.py        # Permission 枚举 + ROLE_PERMISSIONS；role_has_permission（⚠️ 派单员恒真，见 08A）
│   ├── security.py    # hash_password / verify_password / create_access_token / decode_token
│   ├── schema_bootstrap.py  # 启动即 ALTER TABLE 补列（不加列就删掉；大小写/驱动兼容）
│   ├── socket_io.py   # sio = socketio.AsyncServer；L23-L32 按 socket_redis_url 自建 socketio.AsyncRedisManager（多 worker 共享连接状态，空则退化为单进程内存）
│   └── ws_hub.py      # ⚠️ **死代码**（全后端零引用）：裸 WebSocket，无角色房间。别照它改推送，真实推送链见 08 号
├── models/            # SQLAlchemy 2.0 ORM（__init__ 汇总导出）
├── schemas/           # Pydantic v2（Out 含 from_attributes；入参带校验）
├── api/v1/            # 路由层（**不是薄层**，见下方说明）
└── services/          # 业务逻辑（见 §3）
```

> ⚠️ **`api/v1/` 不是薄层**（本节此前如此描述，不成立）。实测规模：**`api/v1/` 28 文件 6,396 行 vs `services/` 24 文件 4,113 行**——路由层比服务层大 **1.5 倍**。
>
> 大量业务逻辑直接写在路由文件里，典型：
> - `api/v1/reports.py`（496 行）的 `build_turnover()` / `build_products()` 是**完整聚合实现**，接口与导出共用，**不调用 `services/`**
> - `api/v1/shipper.py`（405 行）、`api/v1/notifications.py`（269 行）同理
> - `api/v1/orders.py` 单文件 **1,165 行 / 23 个端点**，是后端最大文件
>
> **后果**：找"某功能实现在哪"时，**`services/` 不是首选**——先去 `api/v1/<模块>.py` 看。按"路由薄、逻辑在 service"的常识去找会扑空。

## 2. 数据模型（models/）

| 表 | 文件 | 关键字段 |
|---|---|---|
| users | user.py | role/is_member/billing_mode/vehicle_type/salary/password_hash |
| orders | order.py | status/order_no/shipper_id/temp_shipper_name/driver_id/freight_fee/collect_cash/payment_method/paid/arrears_unit_*/delivered_at/expected_deliver_before/is_exception/exception_*/image_urls(JSON)　⚠️ 旧写的 `damage_photo_*` 全库 **0 命中**，已不存在, driver_billing_mode_snapshot |
| order_products | order.py | product_name_snapshot/quantity/unit_price/line_total/**cost_price_snapshot**/**damage_quantity** |
| products | product.py | name/name_color/**default_unit_price**/**cost_price**（毛利来源）/unit/tier_prices(JSON 多档)/stock(初值)/is_active/**image_url**（⚠️ 旧写的 `unit_price`、`image` 两个字段名都不存在）/low_stock_alert |
| price_rules | product.py（⚠️ **没有独立的 `price_rule.py`**；`PriceRule` 定义在 `models/product.py` L42） | shipper_id(批发商)/product_id/special_unit_price |
| ledger | ledger.py | shipper_id/temp_shipper_name/entry_date/product_name/quantity/unit_price/total/source(ORDER/MANUAL/**REFUND**——⚠️ 漏 REFUND 会 500)/order_id/note |
| cash_flows | cash_flow.py | flow_date/direction(IN\|OUT)/amount/party_type/party_name/channel/biz_type/order_id/doc_id |
| expenses | expense.py | exp_date/category(8类)/amount/driver_id/vehicle_id/order_id/note |
| driver_bills | driver_bill.py | driver_id/bill_type(PIECE\|SALARY)/order_id/month/amount/status(OPEN\|SETTLED)/settled_doc_id |
| driver_settlements | driver_settlement.py | driver_id/settle_type/month/period_from/to/amount/status(DRAFT\|CONFIRMED\|PAID\|CANCELLED)/order_ids(JSON) |
| arrears_units | arrears.py | name/phone/remark |
| shipper_addresses/locations/contacts | shipper.py | 三列表结构（线路/地点/联系人）；image_urls(JSON) |
| customers | customer.py | kind(registered\|tmp)/user_id/is_member/arrears_unit_id |
| shipper_receipts | shipper_receipt.py | customer_id/amount/method/received_at/order_ids/settle_mode |
| inventory_movements | inventory.py | product_id/change(增减量)/note/operator_id/source/order_id/status(COMMITTED…)　⚠️ 旧记载的 `type(IN/OUT/ADJUST)`+`qty` 是 V2 之前 schema，**已不存在** |
| notifications | notification.py | **recipient_id**（⚠️ 不叫 `user_id`）/category(system\|order\|reminder)/type/speech_important/title/content/payload(JSON)/**read_at**（⚠️ 不叫 `read`，且是时间戳不是布尔）　当前 31 行 |
| operation_logs | operation_log.py | operator_id/order_id/action/change_content |
| vehicles | vehicle.py | plate_no/vehicle_type/driver_id/is_active |
| freight_templates | freight_template.py | name/from_place/to_place/fee/remark |
| ledger_export_jobs | export_job.py | 异步导出任务状态机 |

### 订单状态枚举（enums.py OrderStatus）
`PENDING_DISPATCH → DISPATCHED → ACCEPTED → DELIVERED`，另有 `CANCELLED`。

> ⚠️ **勘误（2026-09-14，经独立复核确认）**：本节此前写作 `PENDING_DISPATCH → ASSIGNED → DELIVERED | CANCELLED`，并称"另有 COMPLETED 视图状态"。
> **`ASSIGNED` 与 `COMPLETED` 这两个状态在代码里根本不存在**——唯一真相源是 `app/models/enums.py` 的 `OrderStatus`，共**五态**。
> 照旧写法改代码会直接 `AttributeError`；而且旧写法把 `ACCEPTED`（司机接单）整段漏掉了。
>
> 全后端 `OrderStatus` 赋值共 **6 处**：5 处在 `app/services/order_flow.py`（L76 DISPATCHED / L153 CANCELLED / L190 DELIVERED / L229 CANCELLED / L251 PENDING_DISPATCH），
> **第 6 处在 `app/api/v1/orders.py` L686**（`driver_ack_view`，DISPATCHED→ACCEPTED）。完整副作用见 `08_CODE_LOCATOR.md`。

## 3. services/ 关键服务

| 文件 | 职责 |
|---|---|
| order_flow.py | 订单创建/派单/完成/撤销/召回 的编排；计费快照 ⚠️ `resolve_billing_mode` 实际在 **`models/user.py` L51**，不在本文件 |
| order_response.py | OrderOut 组装 + 司机视图门控（apply_driver_view_gating）+ driver_billing_mode 快照 |
| ledger_sync.py | 已送达订单自动同步账本（幂等） |
| ledger_response.py / ledger_export.py / ledger_export_worker.py | 账本出入参 / Excel / 异步任务 |
| accounting_service.py | 账本 V2 核心（司机账单/结算/收款/开销/资金流水唯一写入点） |
| stats_service.py | 报表/统计聚合（driver_performance/exception_orders/shipper_*） |
| stats_export.py | 看板 Excel 导出（openpyxl 内存流） |
| message_center.py / message_push.py | 站内信 + Socket 推送 |
| operation_log_service.py | 敏感操作审计写日志 |
| auth_service.py / token_response.py | 登录/JWT（⚠️ **没有注册**：`sms_code.py` 与自助建号已于 2026-09-18 删除，建账号只有派单员 `POST /users`） |
| core/validation_errors.py | **校验失败的中文说明**（422 的 `detail` 从 Pydantic 英文结构体换成中文，`errors` 留原始数组） |
| schemas/text.py | **文本入参长度上限的唯一定义处**（MAX_URL/MAX_IMAGES/MAX_NOTE/MAX_TEXT + `Url` 类型；与列宽对齐，审计工具 `_tools/qa/_audit_text_fields.py` 逐字段核对） |
| shipper_contact_service.py | 联系人唯一性校验（重复电话 409） |
| push_events.py | 订单状态事件广播 |
| ~~cancelled_order_retention.py~~ | ⚠️ **死代码（零引用）**，其 L18 的 10 天常量与现行 30 天策略**冲突**。真正的保留策略在 `data_retention.py`（121 行）。**与 08_CODE_LOCATOR.md 一致** |

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

### 文档校验四件套（改完代码 / 文档后各跑一次）

| 命令（在 `backend/` 下） | 查什么 | 抓不到的 |
|---|---|---|
| `python -m scripts.check_refs ..\docs\**\*.md` | **反引号里的路径**是否真实存在（扫**整个 docs 树**，不只 PROJECT_MAP） | ① 一切语义错误 ② **markdown 链接**（它只认反引号） |
| `python -m scripts.check_reachability` | **markdown 链接有效性 + 入口可达性**（从 `AGENTS.md` 做图遍历，报孤儿文档） | 内容对不对 |
| `python -m scripts.gen_endpoint_index --check --out ..\docs\PROJECT_MAP\08A_ENDPOINT_INDEX.md` | **端点索引是否过期**（重新生成后比对） | 生成逻辑本身的错 |
| `python -m scripts.check_doc_claims` | **文档断言 vs 代码**：锚点身份、模型字段名、层规模、逐文件行数/端点数、权限/端点计数、调用点数，**外加 markdown 结构**（表格列数 / 代码段内裸竖线 / 标题层级） | 还没写成断言的声称 |

> ⚠️ **为什么不能只跑第一件**（两条实测）：
> ① 一份 168 处引用的文档，`check_refs` 报 **0 处失效**，独立复核却找出 **9 处语义错误**——"文件存在、但结论不对"它天然看不见。
> ② **`check_refs` 只认反引号**，所以 `AGENTS.md` 里 `[文本](路径)` 形式的链接**从来没有被校验过**——
> 而那是唯一自动注入的文件，它断链 = 整套文档对 agent 不存在（本项目真发生过：94 KB 地图沉睡 5 个月）。
> `check_reachability` 补的正是这个盲区，它**第一次运行就抓出 10 份孤儿文档**。
>
> 另外：**校验器本身也要先验证**——拿已知答案的样本对一遍，再做负向测试（故意改错，确认它真的报错）。
> 实测中一个校验器三轮里报出的"问题"有一半是它自己错；还有一次它**静默跳过 4 处没查**却报"全部一致"。
>
> 📌 **每发现一类新的"声称"，就往 `check_doc_claims.py` 加一条断言**——包括文档里引用的**计数**
> （"130 个端点里 63 个挂了权限"这类）。计数有信息量，但手写必漂；正确做法不是删掉，而是**写成断言让机器守住**。

## 6. 测试入口

```powershell
cd D:\AProjects\ASDH\orders\backend
python -m pytest tests/ -x -q
```

## 7. 常见联调手段

- 登录拿 token → Invoke-RestMethod（PowerShell）或 python requests
- 直接操作数据库：`python -c "from app.database import SessionLocal; ..."`（注意 GBK 输出 → sys.stdout.reconfigure(encoding='utf-8')）
- Socket 联调：`_sio_test.py` [ignore-ref]（本机一次性联调脚本，未入库） [ignore-ref]（本机一次性联调脚本，未入库） 等参考（python-socketio client）
