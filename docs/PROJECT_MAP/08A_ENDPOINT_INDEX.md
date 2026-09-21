<!-- 本文件由 backend/scripts/gen_endpoint_index.py 生成，请勿手工编辑 -->
<!-- 重新生成：
       cd backend
       python -m scripts.gen_endpoint_index --out ../docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md
     校验是否过期（CI/pre-commit）：
       python -m scripts.gen_endpoint_index --check --out ../docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md
-->

# 08A 端点索引（URL → handler → 授权）

> **本文件是 [08_CODE_LOCATOR.md](08_CODE_LOCATOR.md) 的 companion：机器生成、不做判断。**
> 手写地图负责"改某个功能该动哪几个文件"（需要人判断）；本文件负责"这个 URL 落在哪个函数、
> 谁能调"（纯机械事实）。两者分开，是为了不让上百行端点表撑爆手写地图的阅读预算。
>
> **别通读本文件**——它比手写地图大。要查就 grep，命中一行就够。

## 读法（先读这段，10 秒）

- **查某个 URL** → `grep -n 'orders/{order_id}' 08A_ENDPOINT_INDEX.md`，**不要通读全表**。
- **加新接口** → 先在下面「按文件」表里看同模块既有接口的写法，再照抄授权列。
- **改权限** → 看「权限点反查」段，能立刻知道改一个权限点会影响哪些端点。
- **路径前缀有两种**：绝大多数是 `/api/v1/...`；`backend/app/main.py` 里 3 个是**挂在 app 上**
  的（`/health`、`/static/uploads/{path}`、`/api/v1/system/app-version`），路径已按真实拼接结果写出。

### ⚠️ 授权列的语义（写错权限比没有索引更危险）

| 授权列的值 | 真实含义 | 可信度 |
|---|---|---|
| **公开** | 无任何鉴权依赖（本项目仅登录/注册/发短信 + 3 个 app 级路由） | 可靠 |
| 仅登录 | 只要有效 token，**不限角色**——业务约束在函数体内 | 可靠 |
| 角色:a\|b | `require_roles()` 硬校验，roles 之外一律 403 | 可靠 |
| 权限:XXX | `require_permission(Permission.XXX)` | 可靠 |
| **体内仅允许:X** | 函数体里**直接拒绝**了非 X 的角色（形如 `if role != X: raise 403`） | 可靠 |
| **体内含角色判断（需读源码）** | 检测到角色分支但**无法可靠归纳**——可能是条件性限制（只在某些参数下才要求某角色），也可能是行级过滤（司机只看自己的单）。**必须点进源码** | ⚠️ **不确定** |
| **体内权限:X** | 权限点写在函数体里，而不是签名里 | 可靠 |
| 体内仅允许:派单员\|司机 这类 helper | 由 `_must_dispatcher` 等命名守卫施加 | 可靠 |

> ⚠️ **「体内含角色判断（需读源码）」是刻意保留的"我不知道"**，不是漏检。
> 实测两类反例都栽在这上面：
> · `GET /orders` 的门是 `if (include_deleted or deleted_only) and role != DISPATCHER`——**复合条件**，
>   只在传那两个参数时才限制，全角色平时都能调；
> · `POST /orders` 是 `if role == SHIPPER: … elif role == DISPATCHER: … else: raise 403`——**只看末端 else
>   会把货主也说成不允许**。
> 生成器对这两种都**不下结论**。**授权列宁可写"我不确定"，也不能写错**——读的人会据此判断谁有权限。

**🔴 关键陷阱：`require_permission` 对派单员一律放行。**
见 `backend/app/core/rbac.py` L109-L117：`role_has_permission()` 开头就是
"派单员为最高业务权限：通过 require_permission 校验时一律放行（仍须有效登录）"。
所以 `权限:LEDGER_READ_OWN` 的真实含义是
**（派单员）或（拥有该权限点的角色）**——派单员不看权限点，直接通过。
**因此不能靠读 `rbac.py` 的 `ROLE_PERMISSIONS` 反推某端点的准入范围**，本表的授权列才是入口级真相。

### 其它约定

- 位置列 = `def` 所在行（**不是装饰器行**）。同一处以函数名为准，行号会随编辑漂移。
- 行级隔离（司机只能看自己的单）多数写成 `current.id` 赋值过滤，**入口级授权列看不出**，需读函数体。
- **授权列可能同时出现「入口级」和「体内权限:X」**：前者在签名里（`Depends`），后者写在函数体内
  （常只对某一类角色附加要求）。后者**光看签名看不到**，是本索引刻意补上的。
- 「权限点反查」段末尾会列出**声明了却没任何端点引用**的权限点——改那些等于没改。
- 改代码后本表会过期 → 跑上面的 `--check`，不一致就重新生成。**别手改，改了会被下次生成覆盖。**


## 全量端点（192 个，按文件分组）


### `backend/app/api/v1/arrears.py` — 5 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/arrears-units` | `list_units` | `backend/app/api/v1/arrears.py:22` | 权限:LEDGER_EDIT |
| 2 | `POST /api/v1/arrears-units` | `create_unit` | `backend/app/api/v1/arrears.py:33` | 权限:LEDGER_EDIT |
| 3 | `PATCH /api/v1/arrears-units/{unit_id}` | `update_unit` | `backend/app/api/v1/arrears.py:62` | 权限:LEDGER_EDIT |
| 4 | `DELETE /api/v1/arrears-units/{unit_id}` | `delete_unit` | `backend/app/api/v1/arrears.py:107` | 权限:LEDGER_EDIT |
| 5 | `POST /api/v1/arrears-units/{unit_id}/restore` | `restore_unit` | `backend/app/api/v1/arrears.py:157` | 权限:LEDGER_EDIT |

### `backend/app/api/v1/auth.py` — 3 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `POST /api/v1/auth/logout` | `logout` | `backend/app/api/v1/auth.py:52` | 仅登录 |
| 2 | `POST /api/v1/auth/login` | `login_json` | `backend/app/api/v1/auth.py:76` | **公开** |
| 3 | `POST /api/v1/auth/token` | `login_form` | `backend/app/api/v1/auth.py:81` | **公开** |

### `backend/app/api/v1/cash_flows.py` — 2 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/cash-flows` | `list_cash_flows` | `backend/app/api/v1/cash_flows.py:46` | 仅登录 + 体内仅允许:派单员 |
| 2 | `GET /api/v1/cash-flows/summary` | `cash_flow_summary` | `backend/app/api/v1/cash_flows.py:70` | 仅登录 + 体内仅允许:派单员 |

### `backend/app/api/v1/customers.py` — 3 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/customers` | `list_customers` | `backend/app/api/v1/customers.py:25` | 仅登录 + 体内仅允许:派单员 |
| 2 | `POST /api/v1/customers` | `create_customer` | `backend/app/api/v1/customers.py:43` | 仅登录 + 体内仅允许:派单员 |
| 3 | `POST /api/v1/customers/merge` | `merge_customers` | `backend/app/api/v1/customers.py:84` | 仅登录 + 体内仅允许:派单员 |

### `backend/app/api/v1/driver_billing_rules.py` — 6 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/driver-billing-rules` | `list_rules` | `backend/app/api/v1/driver_billing_rules.py:243` | 权限:ORDER_DISPATCH |
| 2 | `POST /api/v1/driver-billing-rules` | `create_rule` | `backend/app/api/v1/driver_billing_rules.py:257` | 权限:ORDER_DISPATCH |
| 3 | `PUT /api/v1/driver-billing-rules/{rule_id}` | `update_rule` | `backend/app/api/v1/driver_billing_rules.py:303` | 权限:ORDER_DISPATCH |
| 4 | `DELETE /api/v1/driver-billing-rules/{rule_id}` | `delete_rule` | `backend/app/api/v1/driver_billing_rules.py:376` | 权限:ORDER_DISPATCH |
| 5 | `POST /api/v1/driver-billing-rules/{rule_id}/restore` | `restore_rule` | `backend/app/api/v1/driver_billing_rules.py:401` | 权限:ORDER_DISPATCH |
| 6 | `POST /api/v1/driver-billing-rules/attach` | `attach_rule` | `backend/app/api/v1/driver_billing_rules.py:428` | 权限:USER_MANAGE |

### `backend/app/api/v1/driver_bills.py` — 2 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/driver-bills` | `list_driver_bills` | `backend/app/api/v1/driver_bills.py:41` | 仅登录 + 体内仅允许:派单员\|司机 |
| 2 | `POST /api/v1/driver-bills/generate` | `generate_bills` | `backend/app/api/v1/driver_bills.py:104` | 仅登录 + 体内仅允许:派单员 |

### `backend/app/api/v1/driver_settlements.py` — 3 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/driver-settlements` | `list_settlements` | `backend/app/api/v1/driver_settlements.py:28` | 仅登录 + 体内仅允许:派单员\|司机 |
| 2 | `POST /api/v1/driver-settlements` | `create_settlement` | `backend/app/api/v1/driver_settlements.py:79` | 仅登录 + 体内仅允许:派单员 |
| 3 | `PATCH /api/v1/driver-settlements/{settlement_id}` | `settlement_action` | `backend/app/api/v1/driver_settlements.py:122` | 仅登录 + 体内仅允许:派单员 |

### `backend/app/api/v1/expense_categories.py` — 5 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/expense-categories` | `list_categories` | `backend/app/api/v1/expense_categories.py:90` | 仅登录 + 体内仅允许:派单员 |
| 2 | `POST /api/v1/expense-categories` | `create_category` | `backend/app/api/v1/expense_categories.py:112` | 仅登录 + 体内仅允许:派单员 |
| 3 | `PATCH /api/v1/expense-categories/{category_id}` | `update_category` | `backend/app/api/v1/expense_categories.py:148` | 仅登录 + 体内仅允许:派单员 |
| 4 | `POST /api/v1/expense-categories/reorder` | `reorder_categories` | `backend/app/api/v1/expense_categories.py:195` | 仅登录 + 体内仅允许:派单员 |
| 5 | `DELETE /api/v1/expense-categories/{category_id}` | `delete_category` | `backend/app/api/v1/expense_categories.py:226` | 仅登录 + 体内仅允许:派单员 |

### `backend/app/api/v1/expenses.py` — 2 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/expenses` | `list_expenses` | `backend/app/api/v1/expenses.py:21` | 仅登录 + 体内仅允许:派单员 |
| 2 | `POST /api/v1/expenses` | `create_expense` | `backend/app/api/v1/expenses.py:79` | 仅登录 + 体内仅允许:派单员 |

### `backend/app/api/v1/files.py` — 1 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `POST /api/v1/files/parse-sheet` | `parse_sheet` | `backend/app/api/v1/files.py:33` | 角色:dispatcher\|shipper |

### `backend/app/api/v1/freight_categories.py` — 5 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/freight-categories` | `list_categories` | `backend/app/api/v1/freight_categories.py:70` | 权限:ORDER_DISPATCH |
| 2 | `POST /api/v1/freight-categories` | `create_category` | `backend/app/api/v1/freight_categories.py:83` | 权限:ORDER_DISPATCH |
| 3 | `PATCH /api/v1/freight-categories/{category_id}` | `update_category` | `backend/app/api/v1/freight_categories.py:114` | 权限:ORDER_DISPATCH |
| 4 | `POST /api/v1/freight-categories/reorder` | `reorder_categories` | `backend/app/api/v1/freight_categories.py:153` | 权限:ORDER_DISPATCH |
| 5 | `DELETE /api/v1/freight-categories/{category_id}` | `delete_category` | `backend/app/api/v1/freight_categories.py:178` | 权限:ORDER_DISPATCH |

### `backend/app/api/v1/freight_settlement.py` — 1 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/freight-settlement` | `freight_settlement` | `backend/app/api/v1/freight_settlement.py:37` | 仅登录 + 体内仅允许:派单员\|司机 |

### `backend/app/api/v1/freight_templates.py` — 6 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/freight-templates` | `list_templates` | `backend/app/api/v1/freight_templates.py:210` | 权限:ORDER_DISPATCH |
| 2 | `POST /api/v1/freight-templates` | `create_template` | `backend/app/api/v1/freight_templates.py:237` | 权限:ORDER_DISPATCH |
| 3 | `PUT /api/v1/freight-templates/{template_id}` | `update_template` | `backend/app/api/v1/freight_templates.py:287` | 权限:ORDER_DISPATCH |
| 4 | `DELETE /api/v1/freight-templates/{template_id}` | `delete_template` | `backend/app/api/v1/freight_templates.py:349` | 权限:ORDER_DISPATCH |
| 5 | `POST /api/v1/freight-templates/{template_id}/restore` | `restore_template` | `backend/app/api/v1/freight_templates.py:380` | 权限:ORDER_DISPATCH |
| 6 | `GET /api/v1/freight-templates/quote` | `quote_freight` | `backend/app/api/v1/freight_templates.py:427` | 权限:ORDER_DISPATCH |

### `backend/app/api/v1/inventory.py` — 3 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/inventory/movements` | `list_movements` | `backend/app/api/v1/inventory.py:26` | 权限:PRODUCT_MANAGE |
| 2 | `POST /api/v1/inventory/movements` | `create_movement` | `backend/app/api/v1/inventory.py:63` | 权限:PRODUCT_MANAGE |
| 3 | `GET /api/v1/inventory/summary` | `inventory_summary` | `backend/app/api/v1/inventory.py:180` | 权限:PRODUCT_MANAGE |

### `backend/app/api/v1/ledger.py` — 13 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/ledger/entries` | `list_entries` | `backend/app/api/v1/ledger.py:109` | 仅登录 + 体内仅允许:派单员\|货主 |
| 2 | `GET /api/v1/ledger/accounts` | `list_accounts` | `backend/app/api/v1/ledger.py:162` | 仅登录 + 体内仅允许:派单员 |
| 3 | `GET /api/v1/ledger/temp-shipper-names` | `list_temp_shipper_names` | `backend/app/api/v1/ledger.py:230` | 仅登录 + 体内仅允许:派单员 |
| 4 | `POST /api/v1/ledger/sync-from-delivered-orders` | `sync_ledger_from_delivered_orders` | `backend/app/api/v1/ledger.py:260` | 权限:LEDGER_EDIT |
| 5 | `POST /api/v1/ledger/entries` | `create_entry` | `backend/app/api/v1/ledger.py:275` | 权限:LEDGER_EDIT |
| 6 | `GET /api/v1/ledger/entries/{entry_id}` | `get_entry` | `backend/app/api/v1/ledger.py:346` | 仅登录 + 体内仅允许:派单员\|货主 |
| 7 | `PATCH /api/v1/ledger/entries/{entry_id}` | `update_entry` | `backend/app/api/v1/ledger.py:365` | 权限:LEDGER_EDIT |
| 8 | `DELETE /api/v1/ledger/entries/{entry_id}` | `delete_entry` | `backend/app/api/v1/ledger.py:470` | 权限:LEDGER_EDIT |
| 9 | `POST /api/v1/ledger/export-jobs` | `create_export_job` | `backend/app/api/v1/ledger.py:517` | 仅登录 + 体内权限:LEDGER_EDIT + 体内仅允许:派单员\|货主 |
| 10 | `GET /api/v1/ledger/export-jobs/{job_id}` | `get_export_job` | `backend/app/api/v1/ledger.py:627` | 仅登录 + 体内仅允许:派单员\|货主 |
| 11 | `GET /api/v1/ledger/export-jobs/{job_id}/download` | `download_export_job` | `backend/app/api/v1/ledger.py:648` | 仅登录 + 体内权限:LEDGER_EDIT + 体内仅允许:派单员\|货主 |
| 12 | `POST /api/v1/ledger/receipts` | `create_receipt_endpoint` | `backend/app/api/v1/ledger.py:692` | 仅登录 + 体内仅允许:派单员 |
| 13 | `GET /api/v1/ledger/receipts` | `list_receipts` | `backend/app/api/v1/ledger.py:739` | 仅登录 + 体内仅允许:派单员 |

### `backend/app/api/v1/notifications.py` — 10 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/notifications/unread-count` | `unread_count` | `backend/app/api/v1/notifications.py:31` | 仅登录 |
| 2 | `GET /api/v1/notifications` | `list_notifications` | `backend/app/api/v1/notifications.py:39` | 仅登录 |
| 3 | `POST /api/v1/notifications/price-notify` | `notify_price_change` | `backend/app/api/v1/notifications.py:121` | 权限:NOTIFICATION_MANAGE |
| 4 | `POST /api/v1/notifications` | `create_notification` | `backend/app/api/v1/notifications.py:163` | 权限:NOTIFICATION_MANAGE |
| 5 | `POST /api/v1/notifications/read-all` | `mark_all_read` | `backend/app/api/v1/notifications.py:186` | 仅登录 |
| 6 | `POST /api/v1/notifications/batch-delete` | `batch_delete_notifications` | `backend/app/api/v1/notifications.py:205` | 仅登录 |
| 7 | `GET /api/v1/notifications/{notification_id}` | `get_notification` | `backend/app/api/v1/notifications.py:243` | 仅登录 + 体内含角色判断（需读源码） |
| 8 | `PATCH /api/v1/notifications/{notification_id}` | `update_notification` | `backend/app/api/v1/notifications.py:253` | 仅登录 + 体内含角色判断（需读源码） |
| 9 | `DELETE /api/v1/notifications/{notification_id}` | `delete_notification` | `backend/app/api/v1/notifications.py:276` | 仅登录 + 体内含角色判断（需读源码） |
| 10 | `POST /api/v1/notifications/{notification_id}/read` | `mark_read` | `backend/app/api/v1/notifications.py:294` | 仅登录 |

### `backend/app/api/v1/operation_logs.py` — 2 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/operation-logs` | `list_operation_logs` | `backend/app/api/v1/operation_logs.py:31` | 权限:OPERATION_LOG_READ |
| 2 | `GET /api/v1/operation-logs/{log_id}` | `get_operation_log` | `backend/app/api/v1/operation_logs.py:58` | 权限:OPERATION_LOG_READ |

### `backend/app/api/v1/order_products.py` — 5 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/order-products` | `list_order_products` | `backend/app/api/v1/order_products.py:72` | 权限:ORDER_READ_ALL |
| 2 | `POST /api/v1/order-products` | `create_order_product` | `backend/app/api/v1/order_products.py:85` | 权限:ORDER_PRODUCT_EDIT |
| 3 | `GET /api/v1/order-products/{line_id}` | `get_order_product` | `backend/app/api/v1/order_products.py:143` | 权限:ORDER_READ_ALL |
| 4 | `PATCH /api/v1/order-products/{line_id}` | `update_order_product` | `backend/app/api/v1/order_products.py:151` | 权限:ORDER_PRODUCT_EDIT |
| 5 | `DELETE /api/v1/order-products/{line_id}` | `delete_order_product` | `backend/app/api/v1/order_products.py:207` | 权限:ORDER_PRODUCT_EDIT |

### `backend/app/api/v1/orders.py` — 25 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/orders` | `list_orders` | `backend/app/api/v1/orders.py:246` | 仅登录 + 体内仅允许:派单员\|司机\|货主 |
| 2 | `GET /api/v1/orders/pending-dispatch-count` | `pending_dispatch_count` | `backend/app/api/v1/orders.py:420` | 仅登录 + 体内仅允许:派单员 |
| 3 | `POST /api/v1/orders/batch-assign` | `batch_assign_orders` | `backend/app/api/v1/orders.py:436` | 权限:ORDER_DISPATCH + 体内含角色判断（需读源码） |
| 4 | `GET /api/v1/orders/{order_id}` | `get_order` | `backend/app/api/v1/orders.py:475` | 仅登录 |
| 5 | `DELETE /api/v1/orders/{order_id}` | `delete_cancelled_order` | `backend/app/api/v1/orders.py:481` | 仅登录 + 体内权限:ORDER_DELETE_CANCELLED + 体内仅允许:派单员\|货主 |
| 6 | `POST /api/v1/orders` | `create_order` | `backend/app/api/v1/orders.py:528` | 权限:ORDER_CREATE + 体内仅允许:派单员\|货主 |
| 7 | `PATCH /api/v1/orders/{order_id}` | `update_order` | `backend/app/api/v1/orders.py:655` | 权限:ORDER_EDIT |
| 8 | `PATCH /api/v1/orders/{order_id}/exception` | `patch_order_exception` | `backend/app/api/v1/orders.py:711` | 权限:ORDER_EDIT |
| 9 | `POST /api/v1/orders/{order_id}/restore` | `restore_order` | `backend/app/api/v1/orders.py:752` | 仅登录 + 体内仅允许:派单员 |
| 10 | `POST /api/v1/orders/{order_id}/address-image` | `upload_order_address_image` | `backend/app/api/v1/orders.py:781` | 仅登录 + 体内含角色判断（需读源码） |
| 11 | `POST /api/v1/orders/{order_id}/delivery-photos` | `upload_delivery_photos` | `backend/app/api/v1/orders.py:892` | 权限:ORDER_UPLOAD_DELIVERY + 体内含角色判断（需读源码） |
| 12 | `POST /api/v1/orders/{order_id}/complete-with-upload` | `complete_order_with_upload` | `backend/app/api/v1/orders.py:913` | 权限:ORDER_COMPLETE_DRIVER + 体内含角色判断（需读源码） |
| 13 | `POST /api/v1/orders/{order_id}/driver-ack` | `driver_ack_view` | `backend/app/api/v1/orders.py:963` | 仅登录 + 体内仅允许:司机 |
| 14 | `POST /api/v1/orders/{order_id}/driver-note` | `driver_append_internal_note` | `backend/app/api/v1/orders.py:1006` | 权限:ORDER_INTERNAL_NOTE + 体内仅允许:派单员\|司机 |
| 15 | `POST /api/v1/orders/{order_id}/navigation` | `fill_order_navigation` | `backend/app/api/v1/orders.py:1034` | 仅登录 + 体内仅允许:派单员\|司机 |
| 16 | `POST /api/v1/orders/{order_id}/price-freight` | `price_freight` | `backend/app/api/v1/orders.py:1156` | 权限:ORDER_DISPATCH |
| 17 | `POST /api/v1/orders/{order_id}/assign` | `assign_order` | `backend/app/api/v1/orders.py:1294` | 权限:ORDER_DISPATCH |
| 18 | `POST /api/v1/orders/{order_id}/split` | `split_order_endpoint` | `backend/app/api/v1/orders.py:1346` | 权限:ORDER_DISPATCH |
| 19 | `POST /api/v1/orders/{order_id}/freight` | `update_order_freight` | `backend/app/api/v1/orders.py:1371` | 权限:ORDER_DISPATCH |
| 20 | `POST /api/v1/orders/{order_id}/complete` | `complete_order` | `backend/app/api/v1/orders.py:1529` | 权限:ORDER_COMPLETE_DRIVER |
| 21 | `POST /api/v1/orders/{order_id}/cancel` | `cancel_order` | `backend/app/api/v1/orders.py:1557` | 仅登录 + 体内权限:ORDER_CANCEL_SHIPPER + 体内权限:ORDER_CANCEL_DISPATCHER + 体内仅允许:派单员\|货主 |
| 22 | `POST /api/v1/orders/{order_id}/return` | `return_order_endpoint` | `backend/app/api/v1/orders.py:1604` | 权限:ORDER_RETURN |
| 23 | `POST /api/v1/orders/{order_id}/pay` | `pay_order` | `backend/app/api/v1/orders.py:1750` | 权限:ORDER_EDIT |
| 24 | `POST /api/v1/orders/{order_id}/charge` | `charge_order` | `backend/app/api/v1/orders.py:1776` | 权限:ORDER_EDIT |
| 25 | `POST /api/v1/orders/{order_id}/recall` | `recall_order` | `backend/app/api/v1/orders.py:1809` | 权限:ORDER_RECALL |

### `backend/app/api/v1/place_categories.py` — 5 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/place-categories` | `list_categories` | `backend/app/api/v1/place_categories.py:97` | 角色:dispatcher\|shipper |
| 2 | `POST /api/v1/place-categories` | `create_category` | `backend/app/api/v1/place_categories.py:109` | 角色:dispatcher\|shipper |
| 3 | `PATCH /api/v1/place-categories/{category_id}` | `update_category` | `backend/app/api/v1/place_categories.py:146` | 角色:dispatcher\|shipper |
| 4 | `POST /api/v1/place-categories/reorder` | `reorder_categories` | `backend/app/api/v1/place_categories.py:194` | 角色:dispatcher\|shipper |
| 5 | `DELETE /api/v1/place-categories/{category_id}` | `delete_category` | `backend/app/api/v1/place_categories.py:221` | 角色:dispatcher\|shipper |

### `backend/app/api/v1/places.py` — 8 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/places` | `list_places` | `backend/app/api/v1/places.py:39` | 仅登录 |
| 2 | `POST /api/v1/places` | `create_place` | `backend/app/api/v1/places.py:60` | 仅登录 |
| 3 | `POST /api/v1/places/{place_id}/use` | `use_place` | `backend/app/api/v1/places.py:91` | 仅登录 |
| 4 | `GET /api/v1/places/{place_id}` | `get_place` | `backend/app/api/v1/places.py:124` | 仅登录 |
| 5 | `PATCH /api/v1/places/{place_id}` | `update_place` | `backend/app/api/v1/places.py:164` | 角色:dispatcher |
| 6 | `POST /api/v1/places/{place_id}/demote` | `demote_place` | `backend/app/api/v1/places.py:205` | 角色:dispatcher |
| 7 | `DELETE /api/v1/places/{place_id}` | `delete_place` | `backend/app/api/v1/places.py:243` | 角色:dispatcher |
| 8 | `POST /api/v1/places/{place_id}/restore` | `restore_place` | `backend/app/api/v1/places.py:272` | 角色:dispatcher |

### `backend/app/api/v1/price_rules.py` — 6 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `POST /api/v1/price-rules/batch` | `batch_price_rules` | `backend/app/api/v1/price_rules.py:90` | 权限:PRICE_RULE_MANAGE |
| 2 | `GET /api/v1/price-rules` | `list_price_rules` | `backend/app/api/v1/price_rules.py:233` | 角色:dispatcher\|shipper |
| 3 | `POST /api/v1/price-rules` | `create_price_rule` | `backend/app/api/v1/price_rules.py:263` | 权限:PRICE_RULE_MANAGE |
| 4 | `GET /api/v1/price-rules/{rule_id}` | `get_price_rule` | `backend/app/api/v1/price_rules.py:325` | 权限:PRICE_RULE_MANAGE |
| 5 | `PATCH /api/v1/price-rules/{rule_id}` | `update_price_rule` | `backend/app/api/v1/price_rules.py:344` | 权限:PRICE_RULE_MANAGE |
| 6 | `DELETE /api/v1/price-rules/{rule_id}` | `delete_price_rule` | `backend/app/api/v1/price_rules.py:393` | 权限:PRICE_RULE_MANAGE |

### `backend/app/api/v1/product_categories.py` — 5 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/product-categories` | `list_categories` | `backend/app/api/v1/product_categories.py:83` | 仅登录 |
| 2 | `POST /api/v1/product-categories` | `create_category` | `backend/app/api/v1/product_categories.py:93` | 权限:PRODUCT_MANAGE |
| 3 | `PATCH /api/v1/product-categories/{category_id}` | `update_category` | `backend/app/api/v1/product_categories.py:123` | 权限:PRODUCT_MANAGE |
| 4 | `POST /api/v1/product-categories/reorder` | `reorder_categories` | `backend/app/api/v1/product_categories.py:167` | 权限:PRODUCT_MANAGE |
| 5 | `DELETE /api/v1/product-categories/{category_id}` | `delete_category` | `backend/app/api/v1/product_categories.py:197` | 权限:PRODUCT_MANAGE |

### `backend/app/api/v1/products.py` — 8 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/products` | `list_products` | `backend/app/api/v1/products.py:77` | 权限:ORDER_CREATE + 体内含角色判断（需读源码） |
| 2 | `POST /api/v1/products` | `create_product` | `backend/app/api/v1/products.py:109` | 权限:PRODUCT_MANAGE |
| 3 | `GET /api/v1/products/cost-history` | `product_cost_history` | `backend/app/api/v1/products.py:165` | 权限:PRODUCT_MANAGE |
| 4 | `GET /api/v1/products/{product_id}` | `get_product` | `backend/app/api/v1/products.py:204` | 仅登录 |
| 5 | `PATCH /api/v1/products/{product_id}` | `update_product` | `backend/app/api/v1/products.py:222` | 权限:PRODUCT_MANAGE |
| 6 | `POST /api/v1/products/{product_id}/image` | `upload_product_image` | `backend/app/api/v1/products.py:275` | 权限:PRODUCT_MANAGE |
| 7 | `DELETE /api/v1/products/{product_id}` | `delete_product` | `backend/app/api/v1/products.py:327` | 权限:PRODUCT_MANAGE |
| 8 | `POST /api/v1/products/{product_id}/restore` | `restore_product` | `backend/app/api/v1/products.py:366` | 权限:PRODUCT_MANAGE |

### `backend/app/api/v1/reports.py` — 4 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/reports/turnover` | `turnover_report` | `backend/app/api/v1/reports.py:340` | 权限:ORDER_DISPATCH |
| 2 | `GET /api/v1/reports/products` | `product_report` | `backend/app/api/v1/reports.py:353` | 权限:ORDER_DISPATCH |
| 3 | `GET /api/v1/reports/arrears-summary` | `arrears_summary` | `backend/app/api/v1/reports.py:413` | 权限:ORDER_DISPATCH |
| 4 | `GET /api/v1/reports/export` | `export_report` | `backend/app/api/v1/reports.py:443` | 权限:ORDER_DISPATCH |

### `backend/app/api/v1/return_requests.py` — 6 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `POST /api/v1/return-requests` | `create_return_request` | `backend/app/api/v1/return_requests.py:187` | 权限:ORDER_RETURN_REQUEST |
| 2 | `GET /api/v1/return-requests/mine` | `list_my_return_requests` | `backend/app/api/v1/return_requests.py:220` | 权限:ORDER_RETURN_REQUEST |
| 3 | `POST /api/v1/return-requests/{request_id}/withdraw` | `withdraw_return_request` | `backend/app/api/v1/return_requests.py:257` | 权限:ORDER_RETURN_REQUEST |
| 4 | `GET /api/v1/return-requests` | `list_return_requests` | `backend/app/api/v1/return_requests.py:277` | 权限:ORDER_RETURN |
| 5 | `POST /api/v1/return-requests/{request_id}/reject` | `reject_return_request` | `backend/app/api/v1/return_requests.py:317` | 权限:ORDER_RETURN |
| 6 | `POST /api/v1/return-requests/{request_id}/fulfill` | `fulfill_return_request` | `backend/app/api/v1/return_requests.py:337` | 权限:ORDER_RETURN |

### `backend/app/api/v1/shipper.py` — 19 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/shipper/addresses` | `list_addresses` | `backend/app/api/v1/shipper.py:66` | 角色:dispatcher\|shipper |
| 2 | `POST /api/v1/shipper/addresses` | `create_address` | `backend/app/api/v1/shipper.py:76` | 角色:dispatcher\|shipper |
| 3 | `GET /api/v1/shipper/addresses/{address_id}` | `get_address` | `backend/app/api/v1/shipper.py:107` | 角色:dispatcher\|shipper |
| 4 | `PATCH /api/v1/shipper/addresses/{address_id}` | `update_address` | `backend/app/api/v1/shipper.py:115` | 角色:dispatcher\|shipper |
| 5 | `DELETE /api/v1/shipper/addresses/{address_id}` | `delete_address` | `backend/app/api/v1/shipper.py:163` | 角色:dispatcher\|shipper |
| 6 | `POST /api/v1/shipper/addresses/{address_id}/restore` | `restore_address` | `backend/app/api/v1/shipper.py:175` | 角色:dispatcher\|shipper |
| 7 | `POST /api/v1/shipper/addresses/{address_id}/set-default` | `set_default_address` | `backend/app/api/v1/shipper.py:190` | 角色:dispatcher\|shipper |
| 8 | `GET /api/v1/shipper/contacts` | `list_contacts` | `backend/app/api/v1/shipper.py:207` | 角色:dispatcher\|shipper |
| 9 | `POST /api/v1/shipper/contacts` | `upsert_contact` | `backend/app/api/v1/shipper.py:217` | 角色:dispatcher\|shipper |
| 10 | `PATCH /api/v1/shipper/contacts/{contact_id}` | `update_contact` | `backend/app/api/v1/shipper.py:241` | 角色:dispatcher\|shipper |
| 11 | `POST /api/v1/shipper/locations/image` | `upload_location_image` | `backend/app/api/v1/shipper.py:275` | 角色:dispatcher\|shipper |
| 12 | `GET /api/v1/shipper/locations` | `list_locations` | `backend/app/api/v1/shipper.py:311` | 角色:dispatcher\|shipper |
| 13 | `POST /api/v1/shipper/locations` | `create_location` | `backend/app/api/v1/shipper.py:321` | 角色:dispatcher\|shipper |
| 14 | `PATCH /api/v1/shipper/locations/{location_id}` | `update_location` | `backend/app/api/v1/shipper.py:350` | 角色:dispatcher\|shipper |
| 15 | `DELETE /api/v1/shipper/locations/{location_id}` | `delete_location` | `backend/app/api/v1/shipper.py:397` | 角色:dispatcher\|shipper |
| 16 | `POST /api/v1/shipper/locations/{location_id}/share` | `share_location` | `backend/app/api/v1/shipper.py:408` | 角色:dispatcher |
| 17 | `POST /api/v1/shipper/locations/{location_id}/restore` | `restore_location` | `backend/app/api/v1/shipper.py:454` | 角色:dispatcher\|shipper |
| 18 | `DELETE /api/v1/shipper/contacts/{contact_id}` | `delete_contact` | `backend/app/api/v1/shipper.py:469` | 角色:dispatcher\|shipper |
| 19 | `POST /api/v1/shipper/contacts/{contact_id}/restore` | `restore_contact` | `backend/app/api/v1/shipper.py:483` | 角色:dispatcher\|shipper |

### `backend/app/api/v1/shipper_ledger.py` — 4 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/shipper-ledger/settlements` | `list_settlements` | `backend/app/api/v1/shipper_ledger.py:121` | 角色:shipper |
| 2 | `POST /api/v1/shipper-ledger/settlements` | `create_settlement` | `backend/app/api/v1/shipper_ledger.py:166` | 角色:shipper |
| 3 | `DELETE /api/v1/shipper-ledger/settlements/{settlement_id}` | `delete_settlement` | `backend/app/api/v1/shipper_ledger.py:286` | 角色:shipper |
| 4 | `POST /api/v1/shipper-ledger/settlements/{settlement_id}/restore` | `restore_settlement` | `backend/app/api/v1/shipper_ledger.py:318` | 角色:shipper |

### `backend/app/api/v1/stats.py` — 8 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/stats/shipper-product-chart` | `get_shipper_product_chart` | `backend/app/api/v1/stats.py:31` | 权限:STATS_READ |
| 2 | `GET /api/v1/stats/shipper-activity` | `get_shipper_activity` | `backend/app/api/v1/stats.py:51` | 权限:STATS_READ |
| 3 | `GET /api/v1/stats/product-drilldown` | `get_product_drilldown` | `backend/app/api/v1/stats.py:63` | 权限:STATS_READ |
| 4 | `GET /api/v1/stats/driver-performance` | `get_driver_performance` | `backend/app/api/v1/stats.py:75` | 权限:STATS_READ |
| 5 | `GET /api/v1/stats/shipper-performance` | `get_shipper_performance` | `backend/app/api/v1/stats.py:90` | 权限:STATS_READ |
| 6 | `GET /api/v1/stats/exception-orders` | `get_exception_orders` | `backend/app/api/v1/stats.py:105` | 权限:STATS_READ |
| 7 | `POST /api/v1/stats/exception-orders/{order_id}/resolve` | `resolve_exception_order` | `backend/app/api/v1/stats.py:116` | 权限:STATS_READ |
| 8 | `POST /api/v1/stats/export` | `post_stats_export` | `backend/app/api/v1/stats.py:164` | 权限:STATS_READ |

### `backend/app/api/v1/users.py` — 10 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/users/me` | `read_me` | `backend/app/api/v1/users.py:54` | 仅登录 |
| 2 | `GET /api/v1/users` | `list_users` | `backend/app/api/v1/users.py:59` | 权限:USER_MANAGE |
| 3 | `POST /api/v1/users` | `create_user` | `backend/app/api/v1/users.py:86` | 权限:USER_MANAGE |
| 4 | `GET /api/v1/users/{user_id}` | `get_user` | `backend/app/api/v1/users.py:135` | 仅登录 + 体内含角色判断（需读源码） |
| 5 | `GET /api/v1/users/{user_id}/product-visibility` | `get_product_visibility` | `backend/app/api/v1/users.py:145` | 仅登录 + 体内含角色判断（需读源码） |
| 6 | `PUT /api/v1/users/{user_id}/product-visibility` | `set_product_visibility` | `backend/app/api/v1/users.py:160` | 权限:USER_MANAGE + 体内含角色判断（需读源码） |
| 7 | `PATCH /api/v1/users/{user_id}` | `update_user` | `backend/app/api/v1/users.py:220` | 仅登录 + 体内含角色判断（需读源码） |
| 8 | `POST /api/v1/users/{user_id}/swap-shipper-driver` | `swap_shipper_driver` | `backend/app/api/v1/users.py:314` | 权限:USER_MANAGE + 体内含角色判断（需读源码） |
| 9 | `DELETE /api/v1/users/{user_id}` | `delete_user` | `backend/app/api/v1/users.py:338` | 权限:USER_MANAGE |
| 10 | `POST /api/v1/users/{user_id}/restore` | `restore_user` | `backend/app/api/v1/users.py:369` | 权限:USER_MANAGE |

### `backend/app/api/v1/vehicles.py` — 4 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/vehicles` | `list_vehicles` | `backend/app/api/v1/vehicles.py:156` | 仅登录 + 体内仅允许:派单员 |
| 2 | `POST /api/v1/vehicles` | `create_vehicle` | `backend/app/api/v1/vehicles.py:162` | 仅登录 + 体内仅允许:派单员 |
| 3 | `PATCH /api/v1/vehicles/{vehicle_id}` | `update_vehicle` | `backend/app/api/v1/vehicles.py:177` | 仅登录 + 体内仅允许:派单员 |
| 4 | `POST /api/v1/vehicles/{vehicle_id}/driver` | `set_vehicle_driver` | `backend/app/api/v1/vehicles.py:211` | 仅登录 + 体内仅允许:派单员 |

### `backend/app/main.py` — 3 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /static/uploads/{file_path:path}` | `static_uploads` | `backend/app/main.py:183` | **公开** |
| 2 | `GET /health` | `health` | `backend/app/main.py:221` | **公开** |
| 3 | `GET /api/v1/system/app-version` | `app_version` | `backend/app/main.py:230` | **公开** |

## 权限点反查（改一个权限点影响哪些端点）

| 权限点 | 端点数 | 端点 |
|---|---|---|
| `LEDGER_EDIT` | 11 | `GET /api/v1/arrears-units`<br>`POST /api/v1/arrears-units`<br>`PATCH /api/v1/arrears-units/{unit_id}`<br>`DELETE /api/v1/arrears-units/{unit_id}`<br>`POST /api/v1/arrears-units/{unit_id}/restore`<br>`POST /api/v1/ledger/sync-from-delivered-orders`<br>`POST /api/v1/ledger/entries`<br>`PATCH /api/v1/ledger/entries/{entry_id}`<br>`DELETE /api/v1/ledger/entries/{entry_id}`<br>`POST /api/v1/ledger/export-jobs`（体内条件判断）<br>`GET /api/v1/ledger/export-jobs/{job_id}/download`（体内条件判断） |
| `NOTIFICATION_MANAGE` | 2 | `POST /api/v1/notifications/price-notify`<br>`POST /api/v1/notifications` |
| `OPERATION_LOG_READ` | 2 | `GET /api/v1/operation-logs`<br>`GET /api/v1/operation-logs/{log_id}` |
| `ORDER_CANCEL_DISPATCHER` | 1 | `POST /api/v1/orders/{order_id}/cancel`（体内条件判断） |
| `ORDER_CANCEL_SHIPPER` | 1 | `POST /api/v1/orders/{order_id}/cancel`（体内条件判断） |
| `ORDER_COMPLETE_DRIVER` | 2 | `POST /api/v1/orders/{order_id}/complete-with-upload`<br>`POST /api/v1/orders/{order_id}/complete` |
| `ORDER_CREATE` | 2 | `POST /api/v1/orders`<br>`GET /api/v1/products` |
| `ORDER_DELETE_CANCELLED` | 1 | `DELETE /api/v1/orders/{order_id}`（体内条件判断） |
| `ORDER_DISPATCH` | 25 | `GET /api/v1/driver-billing-rules`<br>`POST /api/v1/driver-billing-rules`<br>`PUT /api/v1/driver-billing-rules/{rule_id}`<br>`DELETE /api/v1/driver-billing-rules/{rule_id}`<br>`POST /api/v1/driver-billing-rules/{rule_id}/restore`<br>`GET /api/v1/freight-categories`<br>`POST /api/v1/freight-categories`<br>`PATCH /api/v1/freight-categories/{category_id}`<br>`POST /api/v1/freight-categories/reorder`<br>`DELETE /api/v1/freight-categories/{category_id}`<br>`GET /api/v1/freight-templates`<br>`POST /api/v1/freight-templates`<br>`PUT /api/v1/freight-templates/{template_id}`<br>`DELETE /api/v1/freight-templates/{template_id}`<br>`POST /api/v1/freight-templates/{template_id}/restore`<br>`GET /api/v1/freight-templates/quote`<br>`POST /api/v1/orders/batch-assign`<br>`POST /api/v1/orders/{order_id}/price-freight`<br>`POST /api/v1/orders/{order_id}/assign`<br>`POST /api/v1/orders/{order_id}/split`<br>`POST /api/v1/orders/{order_id}/freight`<br>`GET /api/v1/reports/turnover`<br>`GET /api/v1/reports/products`<br>`GET /api/v1/reports/arrears-summary`<br>`GET /api/v1/reports/export` |
| `ORDER_EDIT` | 4 | `PATCH /api/v1/orders/{order_id}`<br>`PATCH /api/v1/orders/{order_id}/exception`<br>`POST /api/v1/orders/{order_id}/pay`<br>`POST /api/v1/orders/{order_id}/charge` |
| `ORDER_INTERNAL_NOTE` | 1 | `POST /api/v1/orders/{order_id}/driver-note` |
| `ORDER_PRODUCT_EDIT` | 3 | `POST /api/v1/order-products`<br>`PATCH /api/v1/order-products/{line_id}`<br>`DELETE /api/v1/order-products/{line_id}` |
| `ORDER_READ_ALL` | 2 | `GET /api/v1/order-products`<br>`GET /api/v1/order-products/{line_id}` |
| `ORDER_RECALL` | 1 | `POST /api/v1/orders/{order_id}/recall` |
| `ORDER_RETURN` | 4 | `POST /api/v1/orders/{order_id}/return`<br>`GET /api/v1/return-requests`<br>`POST /api/v1/return-requests/{request_id}/reject`<br>`POST /api/v1/return-requests/{request_id}/fulfill` |
| `ORDER_RETURN_REQUEST` | 3 | `POST /api/v1/return-requests`<br>`GET /api/v1/return-requests/mine`<br>`POST /api/v1/return-requests/{request_id}/withdraw` |
| `ORDER_UPLOAD_DELIVERY` | 1 | `POST /api/v1/orders/{order_id}/delivery-photos` |
| `PRICE_RULE_MANAGE` | 5 | `POST /api/v1/price-rules/batch`<br>`POST /api/v1/price-rules`<br>`GET /api/v1/price-rules/{rule_id}`<br>`PATCH /api/v1/price-rules/{rule_id}`<br>`DELETE /api/v1/price-rules/{rule_id}` |
| `PRODUCT_MANAGE` | 13 | `GET /api/v1/inventory/movements`<br>`POST /api/v1/inventory/movements`<br>`GET /api/v1/inventory/summary`<br>`POST /api/v1/product-categories`<br>`PATCH /api/v1/product-categories/{category_id}`<br>`POST /api/v1/product-categories/reorder`<br>`DELETE /api/v1/product-categories/{category_id}`<br>`POST /api/v1/products`<br>`GET /api/v1/products/cost-history`<br>`PATCH /api/v1/products/{product_id}`<br>`POST /api/v1/products/{product_id}/image`<br>`DELETE /api/v1/products/{product_id}`<br>`POST /api/v1/products/{product_id}/restore` |
| `STATS_READ` | 8 | `GET /api/v1/stats/shipper-product-chart`<br>`GET /api/v1/stats/shipper-activity`<br>`GET /api/v1/stats/product-drilldown`<br>`GET /api/v1/stats/driver-performance`<br>`GET /api/v1/stats/shipper-performance`<br>`GET /api/v1/stats/exception-orders`<br>`POST /api/v1/stats/exception-orders/{order_id}/resolve`<br>`POST /api/v1/stats/export` |
| `USER_MANAGE` | 7 | `POST /api/v1/driver-billing-rules/attach`<br>`GET /api/v1/users`<br>`POST /api/v1/users`<br>`PUT /api/v1/users/{user_id}/product-visibility`<br>`POST /api/v1/users/{user_id}/swap-shipper-driver`<br>`DELETE /api/v1/users/{user_id}`<br>`POST /api/v1/users/{user_id}/restore` |

> **「体内条件判断」** = 该权限点不是在签名里用 `Depends(require_permission(...))` 校验的，而是写在函数体里（通常只对某类角色附加要求）。改这类权限点**不会**被签名层看见，必须点进源码。

> 记住派单员超权：上表端点派单员**无需**拥有该权限点也能通过。

### 声明了但没有任何端点引用的权限点：5 / 26 个

> 这些权限点只存在于 `backend/app/core/rbac.py` 的枚举里，**改它们不影响任何端点**（也不会报错，容易误以为生效了）。

- `LEDGER_READ_ALL`
- `LEDGER_READ_OWN`
- `NOTIFICATION_READ`
- `ORDER_READ_ASSIGNED`
- `ORDER_READ_OWN`

> 反过来说，某个业务动作**没被权限点保护**时，这里看不出来——要看上面「仅登录」段的端点，它们的准入靠函数体内判断。

## 角色反查（`require_roles` 硬校验的端点）

| 角色组合 | 端点数 | 端点 |
|---|---|---|
| `dispatcher` | 5 | `PATCH /api/v1/places/{place_id}`<br>`POST /api/v1/places/{place_id}/demote`<br>`DELETE /api/v1/places/{place_id}`<br>`POST /api/v1/places/{place_id}/restore`<br>`POST /api/v1/shipper/locations/{location_id}/share` |
| `dispatcher\|shipper` | 25 | `POST /api/v1/files/parse-sheet`<br>`GET /api/v1/place-categories`<br>`POST /api/v1/place-categories`<br>`PATCH /api/v1/place-categories/{category_id}`<br>`POST /api/v1/place-categories/reorder`<br>`DELETE /api/v1/place-categories/{category_id}`<br>`GET /api/v1/price-rules`<br>`GET /api/v1/shipper/addresses`<br>`POST /api/v1/shipper/addresses`<br>`GET /api/v1/shipper/addresses/{address_id}`<br>`PATCH /api/v1/shipper/addresses/{address_id}`<br>`DELETE /api/v1/shipper/addresses/{address_id}`<br>`POST /api/v1/shipper/addresses/{address_id}/restore`<br>`POST /api/v1/shipper/addresses/{address_id}/set-default`<br>`GET /api/v1/shipper/contacts`<br>`POST /api/v1/shipper/contacts`<br>`PATCH /api/v1/shipper/contacts/{contact_id}`<br>`POST /api/v1/shipper/locations/image`<br>`GET /api/v1/shipper/locations`<br>`POST /api/v1/shipper/locations`<br>`PATCH /api/v1/shipper/locations/{location_id}`<br>`DELETE /api/v1/shipper/locations/{location_id}`<br>`POST /api/v1/shipper/locations/{location_id}/restore`<br>`DELETE /api/v1/shipper/contacts/{contact_id}`<br>`POST /api/v1/shipper/contacts/{contact_id}/restore` |
| `shipper` | 4 | `GET /api/v1/shipper-ledger/settlements`<br>`POST /api/v1/shipper-ledger/settlements`<br>`DELETE /api/v1/shipper-ledger/settlements/{settlement_id}`<br>`POST /api/v1/shipper-ledger/settlements/{settlement_id}/restore` |

## 需要注意的端点（机器可判定的三类风险）


### 1. 同一 方法+路径 被注册多次：0 处

_（无重复注册）_

### 2. 完全公开（无鉴权）：5 个

| 方法与路径 | handler | 位置 |
|---|---|---|
| `POST /api/v1/auth/login` | `login_json` | `backend/app/api/v1/auth.py:76` |
| `POST /api/v1/auth/token` | `login_form` | `backend/app/api/v1/auth.py:81` |
| `GET /static/uploads/{file_path:path}` | `static_uploads` | `backend/app/main.py:183` |
| `GET /health` | `health` | `backend/app/main.py:221` |
| `GET /api/v1/system/app-version` | `app_version` | `backend/app/main.py:230` |

### 3. 仅登录、且检测不到任何角色/权限约束：14 个

> 这些端点的准入范围**在本表里看不出来**——约束（如果有）在函数体里按参数或 `current.id` 过滤。
> 反过来说：**这一节是「该去读源码」的清单**，不是「谁都能调」的清单。

| 方法与路径 | handler | 位置 | 含 `current.id` |
|---|---|---|---|
| `POST /api/v1/auth/logout` | `logout` | `backend/app/api/v1/auth.py:52` | — |
| `GET /api/v1/notifications/unread-count` | `unread_count` | `backend/app/api/v1/notifications.py:31` | ✅ |
| `GET /api/v1/notifications` | `list_notifications` | `backend/app/api/v1/notifications.py:39` | ✅ |
| `POST /api/v1/notifications/read-all` | `mark_all_read` | `backend/app/api/v1/notifications.py:186` | ✅ |
| `POST /api/v1/notifications/batch-delete` | `batch_delete_notifications` | `backend/app/api/v1/notifications.py:205` | ✅ |
| `POST /api/v1/notifications/{notification_id}/read` | `mark_read` | `backend/app/api/v1/notifications.py:294` | ✅ |
| `GET /api/v1/orders/{order_id}` | `get_order` | `backend/app/api/v1/orders.py:475` | — |
| `GET /api/v1/places` | `list_places` | `backend/app/api/v1/places.py:39` | — |
| `POST /api/v1/places` | `create_place` | `backend/app/api/v1/places.py:60` | ✅ |
| `POST /api/v1/places/{place_id}/use` | `use_place` | `backend/app/api/v1/places.py:91` | ✅ |
| `GET /api/v1/places/{place_id}` | `get_place` | `backend/app/api/v1/places.py:124` | — |
| `GET /api/v1/product-categories` | `list_categories` | `backend/app/api/v1/product_categories.py:83` | — |
| `GET /api/v1/products/{product_id}` | `get_product` | `backend/app/api/v1/products.py:204` | — |
| `GET /api/v1/users/me` | `read_me` | `backend/app/api/v1/users.py:54` | — |

> ⚠️ 「含 `current.id`」只是**粗筛**：函数体里出现 `current.id` 既可能是行级过滤（`where(shipper_id == current.id)`），也可能只是审计日志的 `operator_id=current.id`。全表共 **119** 个端点命中（占 61%），**要确认是哪种必须读函数体**。涉及文件：`backend/app/api/v1/customers.py`、`backend/app/api/v1/driver_billing_rules.py`、`backend/app/api/v1/driver_bills.py`、`backend/app/api/v1/driver_settlements.py`、`backend/app/api/v1/expense_categories.py`、`backend/app/api/v1/expenses.py`、`backend/app/api/v1/freight_categories.py`、`backend/app/api/v1/freight_settlement.py`、`backend/app/api/v1/freight_templates.py`、`backend/app/api/v1/inventory.py`、`backend/app/api/v1/ledger.py`、`backend/app/api/v1/notifications.py`、`backend/app/api/v1/order_products.py`、`backend/app/api/v1/orders.py`、`backend/app/api/v1/place_categories.py`、`backend/app/api/v1/places.py`、`backend/app/api/v1/price_rules.py`、`backend/app/api/v1/product_categories.py`、`backend/app/api/v1/products.py`、`backend/app/api/v1/return_requests.py`、`backend/app/api/v1/shipper.py`、`backend/app/api/v1/shipper_ledger.py`、`backend/app/api/v1/stats.py`、`backend/app/api/v1/users.py`。
