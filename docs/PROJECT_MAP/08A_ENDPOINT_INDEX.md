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


## 全量端点（227 个，按文件分组）


### `backend/app/api/v1/arrears.py` — 5 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/arrears-units` | `list_units` | `backend/app/api/v1/arrears.py:23` | 权限:LEDGER_EDIT |
| 2 | `POST /api/v1/arrears-units` | `create_unit` | `backend/app/api/v1/arrears.py:42` | 权限:LEDGER_EDIT |
| 3 | `PATCH /api/v1/arrears-units/{unit_id}` | `update_unit` | `backend/app/api/v1/arrears.py:108` | 权限:LEDGER_EDIT |
| 4 | `DELETE /api/v1/arrears-units/{unit_id}` | `delete_unit` | `backend/app/api/v1/arrears.py:153` | 权限:LEDGER_EDIT |
| 5 | `POST /api/v1/arrears-units/{unit_id}/restore` | `restore_unit` | `backend/app/api/v1/arrears.py:222` | 权限:LEDGER_EDIT |

### `backend/app/api/v1/auth.py` — 3 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `POST /api/v1/auth/logout` | `logout` | `backend/app/api/v1/auth.py:76` | 仅登录 |
| 2 | `POST /api/v1/auth/login` | `login_json` | `backend/app/api/v1/auth.py:98` | **公开** |
| 3 | `POST /api/v1/auth/token` | `login_form` | `backend/app/api/v1/auth.py:108` | **公开** |

### `backend/app/api/v1/cash_flows.py` — 3 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/cash-flows` | `list_cash_flows` | `backend/app/api/v1/cash_flows.py:57` | 仅登录 + 体内仅允许:派单员 |
| 2 | `GET /api/v1/cash-flows/summary` | `cash_flow_summary` | `backend/app/api/v1/cash_flows.py:81` | 仅登录 + 体内仅允许:派单员 |
| 3 | `GET /api/v1/cash-flows/breakdown` | `cash_flow_breakdown` | `backend/app/api/v1/cash_flows.py:127` | 仅登录 + 体内仅允许:派单员 |

### `backend/app/api/v1/customers.py` — 3 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/customers` | `list_customers` | `backend/app/api/v1/customers.py:27` | 仅登录 + 体内仅允许:派单员 |
| 2 | `POST /api/v1/customers` | `create_customer` | `backend/app/api/v1/customers.py:48` | 仅登录 + 体内仅允许:派单员 |
| 3 | `POST /api/v1/customers/merge` | `merge_customers` | `backend/app/api/v1/customers.py:89` | 仅登录 + 体内仅允许:派单员 |

### `backend/app/api/v1/driver_billing_rules.py` — 6 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/driver-billing-rules` | `list_rules` | `backend/app/api/v1/driver_billing_rules.py:280` | 权限:ORDER_DISPATCH |
| 2 | `POST /api/v1/driver-billing-rules` | `create_rule` | `backend/app/api/v1/driver_billing_rules.py:299` | 权限:ORDER_DISPATCH |
| 3 | `PUT /api/v1/driver-billing-rules/{rule_id}` | `update_rule` | `backend/app/api/v1/driver_billing_rules.py:345` | 权限:ORDER_DISPATCH |
| 4 | `DELETE /api/v1/driver-billing-rules/{rule_id}` | `delete_rule` | `backend/app/api/v1/driver_billing_rules.py:424` | 权限:ORDER_DISPATCH |
| 5 | `POST /api/v1/driver-billing-rules/{rule_id}/restore` | `restore_rule` | `backend/app/api/v1/driver_billing_rules.py:456` | 权限:ORDER_DISPATCH |
| 6 | `POST /api/v1/driver-billing-rules/attach` | `attach_rule` | `backend/app/api/v1/driver_billing_rules.py:483` | 权限:USER_MANAGE |

### `backend/app/api/v1/driver_bills.py` — 2 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/driver-bills` | `list_driver_bills` | `backend/app/api/v1/driver_bills.py:41` | 仅登录 + 体内仅允许:派单员\|司机 |
| 2 | `POST /api/v1/driver-bills/generate` | `generate_bills` | `backend/app/api/v1/driver_bills.py:132` | 仅登录 + 体内仅允许:派单员 |

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
| 1 | `GET /api/v1/expenses` | `list_expenses` | `backend/app/api/v1/expenses.py:22` | 仅登录 + 体内仅允许:派单员 |
| 2 | `POST /api/v1/expenses` | `create_expense` | `backend/app/api/v1/expenses.py:83` | 仅登录 + 体内仅允许:派单员 |

### `backend/app/api/v1/files.py` — 1 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `POST /api/v1/files/parse-sheet` | `parse_sheet` | `backend/app/api/v1/files.py:34` | 角色:dispatcher\|shipper |

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
| 1 | `GET /api/v1/freight-templates` | `list_templates` | `backend/app/api/v1/freight_templates.py:220` | 权限:ORDER_DISPATCH |
| 2 | `POST /api/v1/freight-templates` | `create_template` | `backend/app/api/v1/freight_templates.py:252` | 权限:ORDER_DISPATCH |
| 3 | `PUT /api/v1/freight-templates/{template_id}` | `update_template` | `backend/app/api/v1/freight_templates.py:302` | 权限:ORDER_DISPATCH |
| 4 | `DELETE /api/v1/freight-templates/{template_id}` | `delete_template` | `backend/app/api/v1/freight_templates.py:364` | 权限:ORDER_DISPATCH |
| 5 | `POST /api/v1/freight-templates/{template_id}/restore` | `restore_template` | `backend/app/api/v1/freight_templates.py:427` | 权限:ORDER_DISPATCH |
| 6 | `GET /api/v1/freight-templates/quote` | `quote_freight` | `backend/app/api/v1/freight_templates.py:474` | 权限:ORDER_DISPATCH |

### `backend/app/api/v1/inventory.py` — 3 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/inventory/movements` | `list_movements` | `backend/app/api/v1/inventory.py:26` | 权限:PRODUCT_MANAGE |
| 2 | `POST /api/v1/inventory/movements` | `create_movement` | `backend/app/api/v1/inventory.py:66` | 权限:PRODUCT_MANAGE |
| 3 | `GET /api/v1/inventory/summary` | `inventory_summary` | `backend/app/api/v1/inventory.py:183` | 权限:PRODUCT_MANAGE |

### `backend/app/api/v1/ledger.py` — 13 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/ledger/entries` | `list_entries` | `backend/app/api/v1/ledger.py:145` | 仅登录 + 体内仅允许:派单员\|货主 |
| 2 | `GET /api/v1/ledger/accounts` | `list_accounts` | `backend/app/api/v1/ledger.py:198` | 仅登录 + 体内仅允许:派单员 |
| 3 | `GET /api/v1/ledger/temp-shipper-names` | `list_temp_shipper_names` | `backend/app/api/v1/ledger.py:267` | 仅登录 + 体内仅允许:派单员 |
| 4 | `POST /api/v1/ledger/sync-from-delivered-orders` | `sync_ledger_from_delivered_orders` | `backend/app/api/v1/ledger.py:297` | 权限:LEDGER_EDIT |
| 5 | `POST /api/v1/ledger/entries` | `create_entry` | `backend/app/api/v1/ledger.py:312` | 权限:LEDGER_EDIT |
| 6 | `GET /api/v1/ledger/entries/{entry_id}` | `get_entry` | `backend/app/api/v1/ledger.py:383` | 仅登录 + 体内仅允许:派单员\|货主 |
| 7 | `PATCH /api/v1/ledger/entries/{entry_id}` | `update_entry` | `backend/app/api/v1/ledger.py:402` | 权限:LEDGER_EDIT |
| 8 | `DELETE /api/v1/ledger/entries/{entry_id}` | `delete_entry` | `backend/app/api/v1/ledger.py:507` | 权限:LEDGER_EDIT |
| 9 | `POST /api/v1/ledger/export-jobs` | `create_export_job` | `backend/app/api/v1/ledger.py:554` | 仅登录 + 体内权限:LEDGER_EDIT + 体内仅允许:派单员\|货主 |
| 10 | `GET /api/v1/ledger/export-jobs/{job_id}` | `get_export_job` | `backend/app/api/v1/ledger.py:683` | 仅登录 |
| 11 | `GET /api/v1/ledger/export-jobs/{job_id}/download` | `download_export_job` | `backend/app/api/v1/ledger.py:701` | 仅登录 |
| 12 | `POST /api/v1/ledger/receipts` | `create_receipt_endpoint` | `backend/app/api/v1/ledger.py:741` | 仅登录 + 体内仅允许:派单员 |
| 13 | `GET /api/v1/ledger/receipts` | `list_receipts` | `backend/app/api/v1/ledger.py:814` | 仅登录 + 体内仅允许:派单员 |

### `backend/app/api/v1/notifications.py` — 10 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/notifications/unread-count` | `unread_count` | `backend/app/api/v1/notifications.py:32` | 仅登录 |
| 2 | `GET /api/v1/notifications` | `list_notifications` | `backend/app/api/v1/notifications.py:40` | 仅登录 |
| 3 | `POST /api/v1/notifications/price-notify` | `notify_price_change` | `backend/app/api/v1/notifications.py:122` | 权限:NOTIFICATION_MANAGE |
| 4 | `POST /api/v1/notifications` | `create_notification` | `backend/app/api/v1/notifications.py:168` | 权限:NOTIFICATION_MANAGE |
| 5 | `POST /api/v1/notifications/read-all` | `mark_all_read` | `backend/app/api/v1/notifications.py:191` | 仅登录 |
| 6 | `POST /api/v1/notifications/batch-delete` | `batch_delete_notifications` | `backend/app/api/v1/notifications.py:210` | 仅登录 |
| 7 | `GET /api/v1/notifications/{notification_id}` | `get_notification` | `backend/app/api/v1/notifications.py:268` | 仅登录 + 体内含角色判断（需读源码） |
| 8 | `PATCH /api/v1/notifications/{notification_id}` | `update_notification` | `backend/app/api/v1/notifications.py:278` | 仅登录 + 体内含角色判断（需读源码） |
| 9 | `DELETE /api/v1/notifications/{notification_id}` | `delete_notification` | `backend/app/api/v1/notifications.py:318` | 仅登录 + 体内含角色判断（需读源码） |
| 10 | `POST /api/v1/notifications/{notification_id}/read` | `mark_read` | `backend/app/api/v1/notifications.py:353` | 仅登录 |

### `backend/app/api/v1/operation_logs.py` — 2 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/operation-logs` | `list_operation_logs` | `backend/app/api/v1/operation_logs.py:31` | 权限:OPERATION_LOG_READ |
| 2 | `GET /api/v1/operation-logs/{log_id}` | `get_operation_log` | `backend/app/api/v1/operation_logs.py:60` | 权限:OPERATION_LOG_READ |

### `backend/app/api/v1/order_products.py` — 5 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/order-products` | `list_order_products` | `backend/app/api/v1/order_products.py:161` | 权限:ORDER_READ_ALL |
| 2 | `POST /api/v1/order-products` | `create_order_product` | `backend/app/api/v1/order_products.py:174` | 权限:ORDER_PRODUCT_EDIT |
| 3 | `GET /api/v1/order-products/{line_id}` | `get_order_product` | `backend/app/api/v1/order_products.py:230` | 权限:ORDER_READ_ALL |
| 4 | `PATCH /api/v1/order-products/{line_id}` | `update_order_product` | `backend/app/api/v1/order_products.py:238` | 权限:ORDER_PRODUCT_EDIT |
| 5 | `DELETE /api/v1/order-products/{line_id}` | `delete_order_product` | `backend/app/api/v1/order_products.py:294` | 权限:ORDER_PRODUCT_EDIT |

### `backend/app/api/v1/order_template_categories.py` — 5 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/order-template-categories` | `list_categories` | `backend/app/api/v1/order_template_categories.py:86` | 权限:ORDER_EDIT |
| 2 | `POST /api/v1/order-template-categories` | `create_category` | `backend/app/api/v1/order_template_categories.py:101` | 权限:ORDER_EDIT |
| 3 | `PATCH /api/v1/order-template-categories/{category_id}` | `update_category` | `backend/app/api/v1/order_template_categories.py:138` | 权限:ORDER_EDIT |
| 4 | `POST /api/v1/order-template-categories/reorder` | `reorder_categories` | `backend/app/api/v1/order_template_categories.py:184` | 权限:ORDER_EDIT |
| 5 | `DELETE /api/v1/order-template-categories/{category_id}` | `delete_category` | `backend/app/api/v1/order_template_categories.py:209` | 权限:ORDER_EDIT |

### `backend/app/api/v1/order_templates.py` — 6 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/order-templates` | `list_templates` | `backend/app/api/v1/order_templates.py:163` | 权限:ORDER_EDIT |
| 2 | `POST /api/v1/order-templates` | `create_template` | `backend/app/api/v1/order_templates.py:202` | 权限:ORDER_EDIT |
| 3 | `PATCH /api/v1/order-templates/{template_id}` | `update_template` | `backend/app/api/v1/order_templates.py:244` | 权限:ORDER_EDIT |
| 4 | `POST /api/v1/order-templates/{template_id}/use` | `use_template` | `backend/app/api/v1/order_templates.py:326` | 权限:ORDER_EDIT |
| 5 | `DELETE /api/v1/order-templates/{template_id}` | `delete_template` | `backend/app/api/v1/order_templates.py:350` | 权限:ORDER_EDIT |
| 6 | `POST /api/v1/order-templates/{template_id}/restore` | `restore_template` | `backend/app/api/v1/order_templates.py:383` | 权限:ORDER_EDIT |

### `backend/app/api/v1/orders.py` — 12 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `DELETE /api/v1/orders/{order_id}` | `delete_cancelled_order` | `backend/app/api/v1/orders.py:97` | 仅登录 + 体内权限:ORDER_DELETE_CANCELLED + 体内仅允许:派单员\|货主 |
| 2 | `POST /api/v1/orders` | `create_order` | `backend/app/api/v1/orders.py:158` | 权限:ORDER_CREATE + 体内仅允许:派单员\|货主 |
| 3 | `PATCH /api/v1/orders/{order_id}` | `update_order` | `backend/app/api/v1/orders.py:330` | 权限:ORDER_EDIT |
| 4 | `PATCH /api/v1/orders/{order_id}/exception` | `patch_order_exception` | `backend/app/api/v1/orders.py:398` | 权限:ORDER_EDIT |
| 5 | `POST /api/v1/orders/{order_id}/restore` | `restore_order` | `backend/app/api/v1/orders.py:439` | 仅登录 + 体内仅允许:派单员 |
| 6 | `POST /api/v1/orders/{order_id}/complete-with-upload` | `complete_order_with_upload` | `backend/app/api/v1/orders.py:474` | 权限:ORDER_COMPLETE_DRIVER + 体内含角色判断（需读源码） |
| 7 | `POST /api/v1/orders/{order_id}/driver-ack` | `driver_ack_view` | `backend/app/api/v1/orders.py:524` | 仅登录 + 体内仅允许:司机 |
| 8 | `POST /api/v1/orders/{order_id}/driver-note` | `driver_append_internal_note` | `backend/app/api/v1/orders.py:567` | 权限:ORDER_INTERNAL_NOTE + 体内仅允许:派单员\|司机 |
| 9 | `POST /api/v1/orders/{order_id}/navigation` | `fill_order_navigation` | `backend/app/api/v1/orders.py:606` | 仅登录 + 体内仅允许:派单员\|司机 |
| 10 | `POST /api/v1/orders/{order_id}/complete` | `complete_order` | `backend/app/api/v1/orders.py:765` | 权限:ORDER_COMPLETE_DRIVER |
| 11 | `POST /api/v1/orders/{order_id}/cancel` | `cancel_order` | `backend/app/api/v1/orders.py:793` | 仅登录 + 体内权限:ORDER_CANCEL_SHIPPER + 体内权限:ORDER_CANCEL_DISPATCHER + 体内仅允许:派单员\|货主 |
| 12 | `POST /api/v1/orders/{order_id}/return` | `return_order_endpoint` | `backend/app/api/v1/orders.py:848` | 权限:ORDER_RETURN |

### `backend/app/api/v1/orders_assignment.py` — 6 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `POST /api/v1/orders/batch-assign` | `batch_assign_orders` | `backend/app/api/v1/orders_assignment.py:56` | 权限:ORDER_DISPATCH + 体内含角色判断（需读源码） |
| 2 | `POST /api/v1/orders/{order_id}/price-freight` | `price_freight` | `backend/app/api/v1/orders_assignment.py:95` | 权限:ORDER_DISPATCH |
| 3 | `POST /api/v1/orders/{order_id}/assign` | `assign_order` | `backend/app/api/v1/orders_assignment.py:264` | 权限:ORDER_DISPATCH |
| 4 | `POST /api/v1/orders/{order_id}/split` | `split_order_endpoint` | `backend/app/api/v1/orders_assignment.py:319` | 权限:ORDER_DISPATCH |
| 5 | `POST /api/v1/orders/{order_id}/freight` | `update_order_freight` | `backend/app/api/v1/orders_assignment.py:344` | 权限:ORDER_DISPATCH |
| 6 | `POST /api/v1/orders/{order_id}/recall` | `recall_order` | `backend/app/api/v1/orders_assignment.py:386` | 权限:ORDER_RECALL |

### `backend/app/api/v1/orders_media.py` — 2 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `POST /api/v1/orders/{order_id}/address-image` | `upload_order_address_image` | `backend/app/api/v1/orders_media.py:37` | 仅登录 + 体内含角色判断（需读源码） |
| 2 | `POST /api/v1/orders/{order_id}/delivery-photos` | `upload_delivery_photos` | `backend/app/api/v1/orders_media.py:128` | 权限:ORDER_UPLOAD_DELIVERY + 体内含角色判断（需读源码） |

### `backend/app/api/v1/orders_payment.py` — 2 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `POST /api/v1/orders/{order_id}/pay` | `pay_order` | `backend/app/api/v1/orders_payment.py:207` | 权限:ORDER_EDIT |
| 2 | `POST /api/v1/orders/{order_id}/charge` | `charge_order` | `backend/app/api/v1/orders_payment.py:258` | 权限:ORDER_EDIT |

### `backend/app/api/v1/orders_query.py` — 3 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/orders` | `list_orders` | `backend/app/api/v1/orders_query.py:76` | 仅登录 + 体内仅允许:派单员\|司机\|货主 |
| 2 | `GET /api/v1/orders/pending-dispatch-count` | `pending_dispatch_count` | `backend/app/api/v1/orders_query.py:256` | 仅登录 + 体内仅允许:派单员 |
| 3 | `GET /api/v1/orders/{order_id}` | `get_order` | `backend/app/api/v1/orders_query.py:272` | 仅登录 |

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
| 1 | `GET /api/v1/places` | `list_places` | `backend/app/api/v1/places.py:53` | 仅登录 |
| 2 | `POST /api/v1/places` | `create_place` | `backend/app/api/v1/places.py:87` | 仅登录 |
| 3 | `POST /api/v1/places/{place_id}/use` | `use_place` | `backend/app/api/v1/places.py:118` | 仅登录 |
| 4 | `GET /api/v1/places/{place_id}` | `get_place` | `backend/app/api/v1/places.py:151` | 仅登录 |
| 5 | `PATCH /api/v1/places/{place_id}` | `update_place` | `backend/app/api/v1/places.py:191` | 角色:dispatcher |
| 6 | `POST /api/v1/places/{place_id}/demote` | `demote_place` | `backend/app/api/v1/places.py:232` | 角色:dispatcher |
| 7 | `DELETE /api/v1/places/{place_id}` | `delete_place` | `backend/app/api/v1/places.py:270` | 角色:dispatcher |
| 8 | `POST /api/v1/places/{place_id}/restore` | `restore_place` | `backend/app/api/v1/places.py:299` | 角色:dispatcher |

### `backend/app/api/v1/price_rules.py` — 6 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `POST /api/v1/price-rules/batch` | `batch_price_rules` | `backend/app/api/v1/price_rules.py:91` | 权限:PRICE_RULE_MANAGE |
| 2 | `GET /api/v1/price-rules` | `list_price_rules` | `backend/app/api/v1/price_rules.py:244` | 角色:dispatcher\|shipper |
| 3 | `POST /api/v1/price-rules` | `create_price_rule` | `backend/app/api/v1/price_rules.py:280` | 权限:PRICE_RULE_MANAGE |
| 4 | `GET /api/v1/price-rules/{rule_id}` | `get_price_rule` | `backend/app/api/v1/price_rules.py:365` | 权限:PRICE_RULE_MANAGE |
| 5 | `PATCH /api/v1/price-rules/{rule_id}` | `update_price_rule` | `backend/app/api/v1/price_rules.py:384` | 权限:PRICE_RULE_MANAGE |
| 6 | `DELETE /api/v1/price-rules/{rule_id}` | `delete_price_rule` | `backend/app/api/v1/price_rules.py:452` | 权限:PRICE_RULE_MANAGE |

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
| 1 | `GET /api/v1/products` | `list_products` | `backend/app/api/v1/products.py:80` | 权限:ORDER_CREATE + 体内含角色判断（需读源码） |
| 2 | `POST /api/v1/products` | `create_product` | `backend/app/api/v1/products.py:127` | 权限:PRODUCT_MANAGE |
| 3 | `GET /api/v1/products/cost-history` | `product_cost_history` | `backend/app/api/v1/products.py:183` | 权限:PRODUCT_MANAGE |
| 4 | `GET /api/v1/products/{product_id}` | `get_product` | `backend/app/api/v1/products.py:222` | 仅登录 |
| 5 | `PATCH /api/v1/products/{product_id}` | `update_product` | `backend/app/api/v1/products.py:240` | 权限:PRODUCT_MANAGE |
| 6 | `POST /api/v1/products/{product_id}/image` | `upload_product_image` | `backend/app/api/v1/products.py:293` | 权限:PRODUCT_MANAGE |
| 7 | `DELETE /api/v1/products/{product_id}` | `delete_product` | `backend/app/api/v1/products.py:346` | 权限:PRODUCT_MANAGE |
| 8 | `POST /api/v1/products/{product_id}/restore` | `restore_product` | `backend/app/api/v1/products.py:423` | 权限:PRODUCT_MANAGE |

### `backend/app/api/v1/reports.py` — 4 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/reports/turnover` | `turnover_report` | `backend/app/api/v1/reports.py:436` | 权限:ORDER_DISPATCH |
| 2 | `GET /api/v1/reports/products` | `product_report` | `backend/app/api/v1/reports.py:451` | 权限:ORDER_DISPATCH |
| 3 | `GET /api/v1/reports/arrears-summary` | `arrears_summary` | `backend/app/api/v1/reports.py:517` | 权限:ORDER_DISPATCH |
| 4 | `GET /api/v1/reports/export` | `export_report` | `backend/app/api/v1/reports.py:548` | 权限:ORDER_DISPATCH |

### `backend/app/api/v1/return_requests.py` — 6 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `POST /api/v1/return-requests` | `create_return_request` | `backend/app/api/v1/return_requests.py:227` | 权限:ORDER_RETURN_REQUEST + 角色:shipper |
| 2 | `GET /api/v1/return-requests/mine` | `list_my_return_requests` | `backend/app/api/v1/return_requests.py:261` | 权限:ORDER_RETURN_REQUEST + 角色:shipper |
| 3 | `POST /api/v1/return-requests/{request_id}/withdraw` | `withdraw_return_request` | `backend/app/api/v1/return_requests.py:309` | 权限:ORDER_RETURN_REQUEST + 角色:shipper |
| 4 | `GET /api/v1/return-requests` | `list_return_requests` | `backend/app/api/v1/return_requests.py:330` | 权限:ORDER_RETURN |
| 5 | `POST /api/v1/return-requests/{request_id}/reject` | `reject_return_request` | `backend/app/api/v1/return_requests.py:375` | 权限:ORDER_RETURN |
| 6 | `POST /api/v1/return-requests/{request_id}/fulfill` | `fulfill_return_request` | `backend/app/api/v1/return_requests.py:395` | 权限:ORDER_RETURN |

### `backend/app/api/v1/shipper.py` — 19 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/shipper/addresses` | `list_addresses` | `backend/app/api/v1/shipper.py:67` | 角色:dispatcher\|shipper |
| 2 | `POST /api/v1/shipper/addresses` | `create_address` | `backend/app/api/v1/shipper.py:81` | 角色:dispatcher\|shipper |
| 3 | `GET /api/v1/shipper/addresses/{address_id}` | `get_address` | `backend/app/api/v1/shipper.py:112` | 角色:dispatcher\|shipper |
| 4 | `PATCH /api/v1/shipper/addresses/{address_id}` | `update_address` | `backend/app/api/v1/shipper.py:120` | 角色:dispatcher\|shipper |
| 5 | `DELETE /api/v1/shipper/addresses/{address_id}` | `delete_address` | `backend/app/api/v1/shipper.py:168` | 角色:dispatcher\|shipper |
| 6 | `POST /api/v1/shipper/addresses/{address_id}/restore` | `restore_address` | `backend/app/api/v1/shipper.py:180` | 角色:dispatcher\|shipper |
| 7 | `POST /api/v1/shipper/addresses/{address_id}/set-default` | `set_default_address` | `backend/app/api/v1/shipper.py:195` | 角色:dispatcher\|shipper |
| 8 | `GET /api/v1/shipper/contacts` | `list_contacts` | `backend/app/api/v1/shipper.py:212` | 角色:dispatcher\|shipper |
| 9 | `POST /api/v1/shipper/contacts` | `upsert_contact` | `backend/app/api/v1/shipper.py:223` | 角色:dispatcher\|shipper |
| 10 | `PATCH /api/v1/shipper/contacts/{contact_id}` | `update_contact` | `backend/app/api/v1/shipper.py:247` | 角色:dispatcher\|shipper |
| 11 | `POST /api/v1/shipper/locations/image` | `upload_location_image` | `backend/app/api/v1/shipper.py:281` | 角色:dispatcher\|shipper |
| 12 | `GET /api/v1/shipper/locations` | `list_locations` | `backend/app/api/v1/shipper.py:318` | 角色:dispatcher\|shipper |
| 13 | `POST /api/v1/shipper/locations` | `create_location` | `backend/app/api/v1/shipper.py:328` | 角色:dispatcher\|shipper |
| 14 | `PATCH /api/v1/shipper/locations/{location_id}` | `update_location` | `backend/app/api/v1/shipper.py:361` | 角色:dispatcher\|shipper |
| 15 | `DELETE /api/v1/shipper/locations/{location_id}` | `delete_location` | `backend/app/api/v1/shipper.py:413` | 角色:dispatcher\|shipper |
| 16 | `POST /api/v1/shipper/locations/{location_id}/share` | `share_location` | `backend/app/api/v1/shipper.py:424` | 角色:dispatcher |
| 17 | `POST /api/v1/shipper/locations/{location_id}/restore` | `restore_location` | `backend/app/api/v1/shipper.py:470` | 角色:dispatcher\|shipper |
| 18 | `DELETE /api/v1/shipper/contacts/{contact_id}` | `delete_contact` | `backend/app/api/v1/shipper.py:485` | 角色:dispatcher\|shipper |
| 19 | `POST /api/v1/shipper/contacts/{contact_id}/restore` | `restore_contact` | `backend/app/api/v1/shipper.py:499` | 角色:dispatcher\|shipper |

### `backend/app/api/v1/shipper_ledger.py` — 5 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/shipper-ledger/summary` | `ledger_summary` | `backend/app/api/v1/shipper_ledger.py:214` | 角色:shipper |
| 2 | `GET /api/v1/shipper-ledger/settlements` | `list_settlements` | `backend/app/api/v1/shipper_ledger.py:328` | 角色:shipper |
| 3 | `POST /api/v1/shipper-ledger/settlements` | `create_settlement` | `backend/app/api/v1/shipper_ledger.py:373` | 角色:shipper |
| 4 | `DELETE /api/v1/shipper-ledger/settlements/{settlement_id}` | `delete_settlement` | `backend/app/api/v1/shipper_ledger.py:509` | 角色:shipper |
| 5 | `POST /api/v1/shipper-ledger/settlements/{settlement_id}/restore` | `restore_settlement` | `backend/app/api/v1/shipper_ledger.py:558` | 角色:shipper |

### `backend/app/api/v1/stats.py` — 8 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/stats/shipper-product-chart` | `get_shipper_product_chart` | `backend/app/api/v1/stats.py:32` | 权限:STATS_READ |
| 2 | `GET /api/v1/stats/shipper-activity` | `get_shipper_activity` | `backend/app/api/v1/stats.py:53` | 权限:STATS_READ |
| 3 | `GET /api/v1/stats/product-drilldown` | `get_product_drilldown` | `backend/app/api/v1/stats.py:66` | 权限:STATS_READ |
| 4 | `GET /api/v1/stats/driver-performance` | `get_driver_performance` | `backend/app/api/v1/stats.py:79` | 权限:STATS_READ |
| 5 | `GET /api/v1/stats/shipper-performance` | `get_shipper_performance` | `backend/app/api/v1/stats.py:95` | 权限:STATS_READ |
| 6 | `GET /api/v1/stats/exception-orders` | `get_exception_orders` | `backend/app/api/v1/stats.py:111` | 权限:STATS_READ |
| 7 | `POST /api/v1/stats/exception-orders/{order_id}/resolve` | `resolve_exception_order` | `backend/app/api/v1/stats.py:123` | 权限:STATS_READ |
| 8 | `POST /api/v1/stats/export` | `post_stats_export` | `backend/app/api/v1/stats.py:171` | 权限:STATS_READ |

### `backend/app/api/v1/suppliers.py` — 15 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/suppliers` | `list_suppliers` | `backend/app/api/v1/suppliers.py:137` | 权限:LEDGER_EDIT |
| 2 | `POST /api/v1/suppliers` | `create_supplier` | `backend/app/api/v1/suppliers.py:158` | 权限:LEDGER_EDIT |
| 3 | `GET /api/v1/suppliers/{supplier_id}` | `get_supplier` | `backend/app/api/v1/suppliers.py:184` | 权限:LEDGER_EDIT |
| 4 | `PATCH /api/v1/suppliers/{supplier_id}` | `update_supplier` | `backend/app/api/v1/suppliers.py:196` | 权限:LEDGER_EDIT |
| 5 | `DELETE /api/v1/suppliers/{supplier_id}` | `delete_supplier` | `backend/app/api/v1/suppliers.py:234` | 权限:LEDGER_EDIT |
| 6 | `POST /api/v1/suppliers/{supplier_id}/restore` | `restore_supplier` | `backend/app/api/v1/suppliers.py:250` | 权限:LEDGER_EDIT |
| 7 | `GET /api/v1/supplier-payables` | `list_payables` | `backend/app/api/v1/suppliers.py:268` | 权限:LEDGER_EDIT |
| 8 | `POST /api/v1/suppliers/{supplier_id}/payables` | `create_payable` | `backend/app/api/v1/suppliers.py:288` | 权限:LEDGER_EDIT |
| 9 | `PATCH /api/v1/supplier-payables/{payable_id}` | `update_payable` | `backend/app/api/v1/suppliers.py:320` | 权限:LEDGER_EDIT |
| 10 | `DELETE /api/v1/supplier-payables/{payable_id}` | `delete_payable` | `backend/app/api/v1/suppliers.py:365` | 权限:LEDGER_EDIT |
| 11 | `POST /api/v1/supplier-payables/{payable_id}/restore` | `restore_payable` | `backend/app/api/v1/suppliers.py:382` | 权限:LEDGER_EDIT |
| 12 | `GET /api/v1/supplier-payments` | `list_payments` | `backend/app/api/v1/suppliers.py:400` | 权限:LEDGER_EDIT |
| 13 | `POST /api/v1/supplier-payables/{payable_id}/payments` | `pay_payable` | `backend/app/api/v1/suppliers.py:437` | 权限:LEDGER_EDIT |
| 14 | `DELETE /api/v1/supplier-payments/{flow_id}` | `cancel_payment` | `backend/app/api/v1/suppliers.py:462` | 权限:LEDGER_EDIT |
| 15 | `POST /api/v1/supplier-payments/{flow_id}/restore` | `restore_payment` | `backend/app/api/v1/suppliers.py:487` | 权限:LEDGER_EDIT |

### `backend/app/api/v1/system.py` — 1 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/system/ai-default` | `read_ai_default` | `backend/app/api/v1/system.py:23` | 仅登录 |

### `backend/app/api/v1/unit_conversions.py` — 5 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/unit-conversions` | `list_conversions` | `backend/app/api/v1/unit_conversions.py:62` | 角色:dispatcher\|shipper |
| 2 | `POST /api/v1/unit-conversions` | `create_conversion` | `backend/app/api/v1/unit_conversions.py:80` | 角色:dispatcher\|shipper |
| 3 | `PATCH /api/v1/unit-conversions/{conversion_id}` | `update_conversion` | `backend/app/api/v1/unit_conversions.py:157` | 角色:dispatcher\|shipper |
| 4 | `DELETE /api/v1/unit-conversions/{conversion_id}` | `delete_conversion` | `backend/app/api/v1/unit_conversions.py:212` | 角色:dispatcher\|shipper |
| 5 | `POST /api/v1/unit-conversions/{conversion_id}/restore` | `restore_conversion` | `backend/app/api/v1/unit_conversions.py:235` | 角色:dispatcher\|shipper |

### `backend/app/api/v1/usage.py` — 1 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `POST /api/v1/usage/reset` | `reset_usage` | `backend/app/api/v1/usage.py:34` | 仅登录 |

### `backend/app/api/v1/users.py` — 10 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/users/me` | `read_me` | `backend/app/api/v1/users.py:55` | 仅登录 + 体内含角色判断（需读源码） |
| 2 | `GET /api/v1/users` | `list_users` | `backend/app/api/v1/users.py:68` | 权限:USER_MANAGE |
| 3 | `POST /api/v1/users` | `create_user` | `backend/app/api/v1/users.py:101` | 权限:USER_MANAGE |
| 4 | `GET /api/v1/users/{user_id}` | `get_user` | `backend/app/api/v1/users.py:150` | 仅登录 + 体内含角色判断（需读源码） |
| 5 | `GET /api/v1/users/{user_id}/product-visibility` | `get_product_visibility` | `backend/app/api/v1/users.py:160` | 仅登录 + 体内含角色判断（需读源码） |
| 6 | `PUT /api/v1/users/{user_id}/product-visibility` | `set_product_visibility` | `backend/app/api/v1/users.py:175` | 权限:USER_MANAGE + 体内含角色判断（需读源码） |
| 7 | `PATCH /api/v1/users/{user_id}` | `update_user` | `backend/app/api/v1/users.py:235` | 仅登录 + 体内含角色判断（需读源码） |
| 8 | `POST /api/v1/users/{user_id}/swap-shipper-driver` | `swap_shipper_driver` | `backend/app/api/v1/users.py:347` | 权限:USER_MANAGE + 体内含角色判断（需读源码） |
| 9 | `DELETE /api/v1/users/{user_id}` | `delete_user` | `backend/app/api/v1/users.py:395` | 权限:USER_MANAGE |
| 10 | `POST /api/v1/users/{user_id}/restore` | `restore_user` | `backend/app/api/v1/users.py:432` | 权限:USER_MANAGE |

### `backend/app/api/v1/vehicles.py` — 4 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /api/v1/vehicles` | `list_vehicles` | `backend/app/api/v1/vehicles.py:157` | 仅登录 + 体内仅允许:派单员 |
| 2 | `POST /api/v1/vehicles` | `create_vehicle` | `backend/app/api/v1/vehicles.py:165` | 仅登录 + 体内仅允许:派单员 |
| 3 | `PATCH /api/v1/vehicles/{vehicle_id}` | `update_vehicle` | `backend/app/api/v1/vehicles.py:180` | 仅登录 + 体内仅允许:派单员 |
| 4 | `POST /api/v1/vehicles/{vehicle_id}/driver` | `set_vehicle_driver` | `backend/app/api/v1/vehicles.py:214` | 仅登录 + 体内仅允许:派单员 |

### `backend/app/main.py` — 3 个

| # | 方法与路径 | handler | 位置 | 授权 |
|---|---|---|---|---|
| 1 | `GET /static/uploads/{file_path:path}` | `static_uploads` | `backend/app/main.py:183` | **公开** |
| 2 | `GET /health` | `health` | `backend/app/main.py:221` | **公开** |
| 3 | `GET /api/v1/system/app-version` | `app_version` | `backend/app/main.py:230` | **公开** |

## 权限点反查（改一个权限点影响哪些端点）

| 权限点 | 端点数 | 端点 |
|---|---|---|
| `LEDGER_EDIT` | 25 | `GET /api/v1/arrears-units`<br>`POST /api/v1/arrears-units`<br>`PATCH /api/v1/arrears-units/{unit_id}`<br>`DELETE /api/v1/arrears-units/{unit_id}`<br>`POST /api/v1/arrears-units/{unit_id}/restore`<br>`POST /api/v1/ledger/sync-from-delivered-orders`<br>`POST /api/v1/ledger/entries`<br>`PATCH /api/v1/ledger/entries/{entry_id}`<br>`DELETE /api/v1/ledger/entries/{entry_id}`<br>`POST /api/v1/ledger/export-jobs`（体内条件判断）<br>`GET /api/v1/suppliers`<br>`POST /api/v1/suppliers`<br>`GET /api/v1/suppliers/{supplier_id}`<br>`PATCH /api/v1/suppliers/{supplier_id}`<br>`DELETE /api/v1/suppliers/{supplier_id}`<br>`POST /api/v1/suppliers/{supplier_id}/restore`<br>`GET /api/v1/supplier-payables`<br>`POST /api/v1/suppliers/{supplier_id}/payables`<br>`PATCH /api/v1/supplier-payables/{payable_id}`<br>`DELETE /api/v1/supplier-payables/{payable_id}`<br>`POST /api/v1/supplier-payables/{payable_id}/restore`<br>`GET /api/v1/supplier-payments`<br>`POST /api/v1/supplier-payables/{payable_id}/payments`<br>`DELETE /api/v1/supplier-payments/{flow_id}`<br>`POST /api/v1/supplier-payments/{flow_id}/restore` |
| `NOTIFICATION_MANAGE` | 2 | `POST /api/v1/notifications/price-notify`<br>`POST /api/v1/notifications` |
| `OPERATION_LOG_READ` | 2 | `GET /api/v1/operation-logs`<br>`GET /api/v1/operation-logs/{log_id}` |
| `ORDER_CANCEL_DISPATCHER` | 1 | `POST /api/v1/orders/{order_id}/cancel`（体内条件判断） |
| `ORDER_CANCEL_SHIPPER` | 1 | `POST /api/v1/orders/{order_id}/cancel`（体内条件判断） |
| `ORDER_COMPLETE_DRIVER` | 2 | `POST /api/v1/orders/{order_id}/complete-with-upload`<br>`POST /api/v1/orders/{order_id}/complete` |
| `ORDER_CREATE` | 2 | `POST /api/v1/orders`<br>`GET /api/v1/products` |
| `ORDER_DELETE_CANCELLED` | 1 | `DELETE /api/v1/orders/{order_id}`（体内条件判断） |
| `ORDER_DISPATCH` | 25 | `GET /api/v1/driver-billing-rules`<br>`POST /api/v1/driver-billing-rules`<br>`PUT /api/v1/driver-billing-rules/{rule_id}`<br>`DELETE /api/v1/driver-billing-rules/{rule_id}`<br>`POST /api/v1/driver-billing-rules/{rule_id}/restore`<br>`GET /api/v1/freight-categories`<br>`POST /api/v1/freight-categories`<br>`PATCH /api/v1/freight-categories/{category_id}`<br>`POST /api/v1/freight-categories/reorder`<br>`DELETE /api/v1/freight-categories/{category_id}`<br>`GET /api/v1/freight-templates`<br>`POST /api/v1/freight-templates`<br>`PUT /api/v1/freight-templates/{template_id}`<br>`DELETE /api/v1/freight-templates/{template_id}`<br>`POST /api/v1/freight-templates/{template_id}/restore`<br>`GET /api/v1/freight-templates/quote`<br>`POST /api/v1/orders/batch-assign`<br>`POST /api/v1/orders/{order_id}/price-freight`<br>`POST /api/v1/orders/{order_id}/assign`<br>`POST /api/v1/orders/{order_id}/split`<br>`POST /api/v1/orders/{order_id}/freight`<br>`GET /api/v1/reports/turnover`<br>`GET /api/v1/reports/products`<br>`GET /api/v1/reports/arrears-summary`<br>`GET /api/v1/reports/export` |
| `ORDER_EDIT` | 15 | `GET /api/v1/order-template-categories`<br>`POST /api/v1/order-template-categories`<br>`PATCH /api/v1/order-template-categories/{category_id}`<br>`POST /api/v1/order-template-categories/reorder`<br>`DELETE /api/v1/order-template-categories/{category_id}`<br>`GET /api/v1/order-templates`<br>`POST /api/v1/order-templates`<br>`PATCH /api/v1/order-templates/{template_id}`<br>`POST /api/v1/order-templates/{template_id}/use`<br>`DELETE /api/v1/order-templates/{template_id}`<br>`POST /api/v1/order-templates/{template_id}/restore`<br>`PATCH /api/v1/orders/{order_id}`<br>`PATCH /api/v1/orders/{order_id}/exception`<br>`POST /api/v1/orders/{order_id}/pay`<br>`POST /api/v1/orders/{order_id}/charge` |
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
| `dispatcher\|shipper` | 30 | `POST /api/v1/files/parse-sheet`<br>`GET /api/v1/place-categories`<br>`POST /api/v1/place-categories`<br>`PATCH /api/v1/place-categories/{category_id}`<br>`POST /api/v1/place-categories/reorder`<br>`DELETE /api/v1/place-categories/{category_id}`<br>`GET /api/v1/price-rules`<br>`GET /api/v1/shipper/addresses`<br>`POST /api/v1/shipper/addresses`<br>`GET /api/v1/shipper/addresses/{address_id}`<br>`PATCH /api/v1/shipper/addresses/{address_id}`<br>`DELETE /api/v1/shipper/addresses/{address_id}`<br>`POST /api/v1/shipper/addresses/{address_id}/restore`<br>`POST /api/v1/shipper/addresses/{address_id}/set-default`<br>`GET /api/v1/shipper/contacts`<br>`POST /api/v1/shipper/contacts`<br>`PATCH /api/v1/shipper/contacts/{contact_id}`<br>`POST /api/v1/shipper/locations/image`<br>`GET /api/v1/shipper/locations`<br>`POST /api/v1/shipper/locations`<br>`PATCH /api/v1/shipper/locations/{location_id}`<br>`DELETE /api/v1/shipper/locations/{location_id}`<br>`POST /api/v1/shipper/locations/{location_id}/restore`<br>`DELETE /api/v1/shipper/contacts/{contact_id}`<br>`POST /api/v1/shipper/contacts/{contact_id}/restore`<br>`GET /api/v1/unit-conversions`<br>`POST /api/v1/unit-conversions`<br>`PATCH /api/v1/unit-conversions/{conversion_id}`<br>`DELETE /api/v1/unit-conversions/{conversion_id}`<br>`POST /api/v1/unit-conversions/{conversion_id}/restore` |
| `shipper` | 8 | `POST /api/v1/return-requests`<br>`GET /api/v1/return-requests/mine`<br>`POST /api/v1/return-requests/{request_id}/withdraw`<br>`GET /api/v1/shipper-ledger/summary`<br>`GET /api/v1/shipper-ledger/settlements`<br>`POST /api/v1/shipper-ledger/settlements`<br>`DELETE /api/v1/shipper-ledger/settlements/{settlement_id}`<br>`POST /api/v1/shipper-ledger/settlements/{settlement_id}/restore` |

## 需要注意的端点（机器可判定的三类风险）


### 1. 同一 方法+路径 被注册多次：0 处

_（无重复注册）_

### 2. 完全公开（无鉴权）：5 个

| 方法与路径 | handler | 位置 |
|---|---|---|
| `POST /api/v1/auth/login` | `login_json` | `backend/app/api/v1/auth.py:98` |
| `POST /api/v1/auth/token` | `login_form` | `backend/app/api/v1/auth.py:108` |
| `GET /static/uploads/{file_path:path}` | `static_uploads` | `backend/app/main.py:183` |
| `GET /health` | `health` | `backend/app/main.py:221` |
| `GET /api/v1/system/app-version` | `app_version` | `backend/app/main.py:230` |

### 3. 仅登录、且检测不到任何角色/权限约束：17 个

> 这些端点的准入范围**在本表里看不出来**——约束（如果有）在函数体里按参数或 `current.id` 过滤。
> 反过来说：**这一节是「该去读源码」的清单**，不是「谁都能调」的清单。

| 方法与路径 | handler | 位置 | 含 `current.id` |
|---|---|---|---|
| `POST /api/v1/auth/logout` | `logout` | `backend/app/api/v1/auth.py:76` | — |
| `GET /api/v1/ledger/export-jobs/{job_id}` | `get_export_job` | `backend/app/api/v1/ledger.py:683` | — |
| `GET /api/v1/ledger/export-jobs/{job_id}/download` | `download_export_job` | `backend/app/api/v1/ledger.py:701` | — |
| `GET /api/v1/notifications/unread-count` | `unread_count` | `backend/app/api/v1/notifications.py:32` | ✅ |
| `GET /api/v1/notifications` | `list_notifications` | `backend/app/api/v1/notifications.py:40` | ✅ |
| `POST /api/v1/notifications/read-all` | `mark_all_read` | `backend/app/api/v1/notifications.py:191` | ✅ |
| `POST /api/v1/notifications/batch-delete` | `batch_delete_notifications` | `backend/app/api/v1/notifications.py:210` | ✅ |
| `POST /api/v1/notifications/{notification_id}/read` | `mark_read` | `backend/app/api/v1/notifications.py:353` | ✅ |
| `GET /api/v1/orders/{order_id}` | `get_order` | `backend/app/api/v1/orders_query.py:272` | — |
| `GET /api/v1/places` | `list_places` | `backend/app/api/v1/places.py:53` | — |
| `POST /api/v1/places` | `create_place` | `backend/app/api/v1/places.py:87` | ✅ |
| `POST /api/v1/places/{place_id}/use` | `use_place` | `backend/app/api/v1/places.py:118` | ✅ |
| `GET /api/v1/places/{place_id}` | `get_place` | `backend/app/api/v1/places.py:151` | — |
| `GET /api/v1/product-categories` | `list_categories` | `backend/app/api/v1/product_categories.py:83` | — |
| `GET /api/v1/products/{product_id}` | `get_product` | `backend/app/api/v1/products.py:222` | — |
| `GET /api/v1/system/ai-default` | `read_ai_default` | `backend/app/api/v1/system.py:23` | — |
| `POST /api/v1/usage/reset` | `reset_usage` | `backend/app/api/v1/usage.py:34` | ✅ |

> ⚠️ 「含 `current.id`」只是**粗筛**：函数体里出现 `current.id` 既可能是行级过滤（`where(shipper_id == current.id)`），也可能只是审计日志的 `operator_id=current.id`。全表共 **128** 个端点命中（占 56%），**要确认是哪种必须读函数体**。涉及文件：`backend/app/api/v1/customers.py`、`backend/app/api/v1/driver_billing_rules.py`、`backend/app/api/v1/driver_bills.py`、`backend/app/api/v1/driver_settlements.py`、`backend/app/api/v1/expense_categories.py`、`backend/app/api/v1/expenses.py`、`backend/app/api/v1/freight_categories.py`、`backend/app/api/v1/freight_settlement.py`、`backend/app/api/v1/freight_templates.py`、`backend/app/api/v1/inventory.py`、`backend/app/api/v1/ledger.py`、`backend/app/api/v1/notifications.py`、`backend/app/api/v1/order_products.py`、`backend/app/api/v1/order_template_categories.py`、`backend/app/api/v1/orders.py`、`backend/app/api/v1/orders_assignment.py`、`backend/app/api/v1/orders_media.py`、`backend/app/api/v1/orders_payment.py`、`backend/app/api/v1/orders_query.py`、`backend/app/api/v1/place_categories.py`、`backend/app/api/v1/places.py`、`backend/app/api/v1/price_rules.py`、`backend/app/api/v1/product_categories.py`、`backend/app/api/v1/products.py`、`backend/app/api/v1/return_requests.py`、`backend/app/api/v1/shipper.py`、`backend/app/api/v1/shipper_ledger.py`、`backend/app/api/v1/stats.py`、`backend/app/api/v1/unit_conversions.py`、`backend/app/api/v1/usage.py`、`backend/app/api/v1/users.py`。
