# 工具白名单骨架（自动生成）

> ⚠️ **这不是「大白话文档」，也不能直接给用户看。**
> 零基础用户需要的是「**UI 入口路径**」列（工作台 → 账本管理 → 手工记账），
> 而本文件生成自后端代码，**拿不到 UI 入口**——后端没有中文功能名
> （handler docstring 覆盖 24%、`summary=` 0 个、`APIRouter(tags=)` 全是英文 slug）。
> 正确做法：从 `android/.../ui/nav/{Modules,Routes,NavGraph}.kt` 生成入口映射，与本表对齐。
>
> 端点事实以 `docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md` 为准。

## 挂账单位（`arrears`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `list_units` | 只读 | `GET /api/v1/arrears-units` |  |  |
| `create_unit` | 写 | `POST /api/v1/arrears-units` |  |  |
| `update_unit` | 写 | `PATCH /api/v1/arrears-units/{unit_id}` |  |  |
| `delete_unit` | 写 | `DELETE /api/v1/arrears-units/{unit_id}` |  |  |
| `restore_unit` | 写 | `POST /api/v1/arrears-units/{unit_id}/restore` | 把删掉的挂账单位恢复回来（DELETE /{id} 的逆操作）。 |  |

## 登录（`auth`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `logout` | 写 | `POST /api/v1/auth/logout` | 登出：**服务端**把这个账号已发出的令牌全部作废（`token_version` +1）+ 断开长连接。 |  |
| `login_json` | 写 | `POST /api/v1/auth/login` | OAuth2 兼容：username 字段填手机号。 |  |
| `login_form` | 写 | `POST /api/v1/auth/token` | OAuth2 兼容：username 字段填手机号。 |  |

## 现金流水（`cash_flows`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `list_cash_flows` | 只读 | `GET /api/v1/cash-flows` |  |  |
| `cash_flow_summary` | 只读 | `GET /api/v1/cash-flows/summary` | **服务端**汇总流入/流出/净额（与列表同一套筛选）。 |  |

## 客户（`customers`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `list_customers` | 只读 | `GET /api/v1/customers` |  |  |
| `create_customer` | 写 | `POST /api/v1/customers` |  |  |
| `merge_customers` | 写 | `POST /api/v1/customers/merge` |  |  |

## 司机计费规则（`driver_billing_rules`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `list_rules` | 只读 | `GET /api/v1/driver-billing-rules` |  |  |
| `create_rule` | 写 | `POST /api/v1/driver-billing-rules` |  |  |
| `update_rule` | 写 | `PUT /api/v1/driver-billing-rules/{rule_id}` |  |  |
| `delete_rule` | 写 | `DELETE /api/v1/driver-billing-rules/{rule_id}` |  |  |
| `restore_rule` | 写 | `POST /api/v1/driver-billing-rules/{rule_id}/restore` | 把删掉的规则恢复回来（撤回底线：删错了要能原样回来）。 |  |
| `attach_rule` | 写 | `POST /api/v1/driver-billing-rules/attach` | 把规则挂到司机身上；`rule_id=null` = 解挂（他退回老口径）。 |  |

## 司机账单（`driver_bills`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `list_driver_bills` | 只读 | `GET /api/v1/driver-bills` |  |  |
| `generate_bills` | 写 | `POST /api/v1/driver-bills/generate` | SALARY：对指定司机（或全部薪资司机，含已停用）生成当月月薪单（幂等）；PIECE：该月已送达未生成的补单（幂等）。 |  |

## 司机结算单（`driver_settlements`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `list_settlements` | 只读 | `GET /api/v1/driver-settlements` |  |  |
| `create_settlement` | 写 | `POST /api/v1/driver-settlements` |  |  |
| `settlement_action` | 写 | `PATCH /api/v1/driver-settlements/{settlement_id}` |  |  |

## 费用（`expenses`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `list_expenses` | 只读 | `GET /api/v1/expenses` |  |  |
| `create_expense` | 写 | `POST /api/v1/expenses` |  |  |

## AI 附件解析（`files`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `parse_sheet` | 写 | `POST /api/v1/files/parse-sheet` | 上传 Excel(.xlsx/.xlsm) 或文本表格(.csv/.tsv/.txt)，读成「一格一格」的文本。 |  |

## 司机运费结算（`freight_settlement`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `freight_settlement` | 只读 | `GET /api/v1/freight-settlement` |  |  |

## 订单/运费模板（`freight_templates`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `list_templates` | 只读 | `GET /api/v1/freight-templates` |  |  |
| `create_template` | 写 | `POST /api/v1/freight-templates` |  |  |
| `update_template` | 写 | `PUT /api/v1/freight-templates/{template_id}` |  |  |
| `delete_template` | 写 | `DELETE /api/v1/freight-templates/{template_id}` |  |  |
| `restore_template` | 写 | `POST /api/v1/freight-templates/{template_id}/restore` | 把删掉的运费模板恢复回来（DELETE /{id} 的逆操作）。 |  |

## 库存管理（`inventory`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `list_movements` | 只读 | `GET /api/v1/inventory/movements` |  |  |
| `create_movement` | 写 | `POST /api/v1/inventory/movements` | 手工出入库：**判据与加减在同一条 SQL 里**（2026-09-19 审计）。 |  |
| `inventory_summary` | 只读 | `GET /api/v1/inventory/summary` | 库存概览：商品名 + 当前库存 + 在途占用量（派单中未送达，低库存排前）。 |  |

## 账本（`ledger`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `list_entries` | 只读 | `GET /api/v1/ledger/entries` |  |  |
| `list_accounts` | 只读 | `GET /api/v1/ledger/accounts` | 派单员账本账户汇总：货主账 / 批发商账（按流水累计 + 笔数）。 |  |
| `list_temp_shipper_names` | 只读 | `GET /api/v1/ledger/temp-shipper-names` | 派单员：曾出现过的临时货主称呼（账本或订单），用于快捷筛选；订单送达时已自动入账，无需「创建账本」。 |  |
| `sync_ledger_from_delivered_orders` | 写 | `POST /api/v1/ledger/sync-from-delivered-orders` | 按历史已送达订单补全/刷新账本（幂等）。仅派单员。 |  |
| `create_entry` | 写 | `POST /api/v1/ledger/entries` |  |  |
| `get_entry` | 只读 | `GET /api/v1/ledger/entries/{entry_id}` |  |  |
| `update_entry` | 写 | `PATCH /api/v1/ledger/entries/{entry_id}` | 派单员：订单自动同步行与手动行均可改明细；修改订单来源行时会尝试回写对应订单明细。 |  |
| `delete_entry` | 写 | `DELETE /api/v1/ledger/entries/{entry_id}` |  |  |
| `create_export_job` | 只读 | `POST /api/v1/ledger/export-jobs` | 建一个账本导出任务（异步生成，完成后发站内信带下载链接）。 |  |
| `get_export_job` | 只读 | `GET /api/v1/ledger/export-jobs/{job_id}` |  |  |
| `download_export_job` | 只读 | `GET /api/v1/ledger/export-jobs/{job_id}/download` | 下载导出的账本文件（**带鉴权**）。 |  |
| `create_receipt_endpoint` | 写 | `POST /api/v1/ledger/receipts` | 客户收款单（逐单核销默认）：绑定订单并标记 paid=1；生成资金流水。 |  |
| `list_receipts` | 只读 | `GET /api/v1/ledger/receipts` |  |  |

## 消息通知（`notifications`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `unread_count` | 只读 | `GET /api/v1/notifications/unread-count` |  |  |
| `list_notifications` | 只读 | `GET /api/v1/notifications` |  |  |
| `notify_price_change` | 写 | `POST /api/v1/notifications/price-notify` | 派单员：价格变更后向选定货主发送站内通知并推送 Socket。 |  |
| `create_notification` | 写 | `POST /api/v1/notifications` |  |  |
| `mark_all_read` | 写 | `POST /api/v1/notifications/read-all` |  |  |
| `batch_delete_notifications` | 写 | `POST /api/v1/notifications/batch-delete` | 批量删除消息：ids 指定列表，或 all=true 清空该账户全部消息（二选一）。 |  |
| `get_notification` | 只读 | `GET /api/v1/notifications/{notification_id}` |  |  |
| `update_notification` | 写 | `PATCH /api/v1/notifications/{notification_id}` |  |  |
| `delete_notification` | 写 | `DELETE /api/v1/notifications/{notification_id}` |  |  |
| `mark_read` | 写 | `POST /api/v1/notifications/{notification_id}/read` |  |  |

## 操作日志（`operation_logs`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `list_operation_logs` | 只读 | `GET /api/v1/operation-logs` |  |  |
| `get_operation_log` | 只读 | `GET /api/v1/operation-logs/{log_id}` |  |  |

## 订单商品行（`order_products`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `list_order_products` | 只读 | `GET /api/v1/order-products` |  |  |
| `create_order_product` | 写 | `POST /api/v1/order-products` |  |  |
| `get_order_product` | 只读 | `GET /api/v1/order-products/{line_id}` |  |  |
| `update_order_product` | 写 | `PATCH /api/v1/order-products/{line_id}` |  |  |
| `delete_order_product` | 写 | `DELETE /api/v1/order-products/{line_id}` |  |  |

## 订单/派单（`orders`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `list_orders` | 只读 | `GET /api/v1/orders` |  |  |
| `pending_dispatch_count` | 只读 | `GET /api/v1/orders/pending-dispatch-count` | 派单工作台：当前「派单中」订单数量，用于底部 Tab / 铃铛角标。 |  |
| `batch_assign_orders` | 写 | `POST /api/v1/orders/batch-assign` |  |  |
| `get_order` | 只读 | `GET /api/v1/orders/{order_id}` | 软删除订单 → 进入隔离区 30 天（用户不可见；派单员可恢复；到期物理清理）。 |  |
| `delete_cancelled_order` | 写 | `DELETE /api/v1/orders/{order_id}` | 软删除订单 → 进入隔离区 30 天（用户不可见；派单员可恢复；到期物理清理）。 |  |
| `create_order` | 写 | `POST /api/v1/orders` | 创建订单，初始状态为派单中（PENDING_DISPATCH）。 |  |
| `update_order` | 写 | `PATCH /api/v1/orders/{order_id}` |  |  |
| `patch_order_exception` | 写 | `PATCH /api/v1/orders/{order_id}/exception` |  |  |
| `restore_order` | 写 | `POST /api/v1/orders/{order_id}/restore` | 派单员：从隔离区恢复订单（软删除后 30 天内可恢复）。 |  |
| `upload_order_address_image` | 写 | `POST /api/v1/orders/{order_id}/address-image` | 上传收货地址参考图（定位不清时辅助找路）。 |  |
| `upload_delivery_photos` | 写 | `POST /api/v1/orders/{order_id}/delivery-photos` |  |  |
| `complete_order_with_upload` | 写 | `POST /api/v1/orders/{order_id}/complete-with-upload` |  |  |
| `driver_ack_view` | 写 | `POST /api/v1/orders/{order_id}/driver-ack` |  |  |
| `driver_append_internal_note` | 写 | `POST /api/v1/orders/{order_id}/driver-note` |  |  |
| `fill_order_navigation` | 写 | `POST /api/v1/orders/{order_id}/navigation` | **司机到场后给这单补上导航信息**（订单原本没有坐标时才能补）。 |  |
| `assign_order` | 写 | `POST /api/v1/orders/{order_id}/assign` |  |  |
| `split_order_endpoint` | 写 | `POST /api/v1/orders/{order_id}/split` | 把待派单拆分为 N 个子单（按比例拆分件数），分别派单。 |  |
| `update_order_freight` | 写 | `POST /api/v1/orders/{order_id}/freight` | 派单员补录/修改司机运费（送达/撤销后锁定；传 null 清空回待定）。 |  |
| `complete_order` | 写 | `POST /api/v1/orders/{order_id}/complete` |  |  |
| `cancel_order` | 写 | `POST /api/v1/orders/{order_id}/cancel` |  |  |
| `pay_order` | 写 | `POST /api/v1/orders/{order_id}/pay` | 派单员：现场收款确认（货到付款）。仅派单员界面可用。 |  |
| `charge_order` | 写 | `POST /api/v1/orders/{order_id}/charge` | 派单员：订单挂账到挂账单位名下。仅派单员界面可用。 |  |
| `recall_order` | 写 | `POST /api/v1/orders/{order_id}/recall` |  |  |

## 地点分类（`place_categories`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `list_categories` | 只读 | `GET /api/v1/place-categories` | **自己那一份**分类名册（按显示顺序）。司机没有地点库，拿不到。 |  |
| `create_category` | 写 | `POST /api/v1/place-categories` |  |  |
| `update_category` | 写 | `PATCH /api/v1/place-categories/{category_id}` | 改名 / 改顺序。**改名会级联改掉挂在这一类下的地点**（同一事务）。 |  |
| `reorder_categories` | 写 | `POST /api/v1/place-categories/reorder` | 整份顺序一次提交：`ids[0]` 排最前。**必须覆盖自己全部现存分类**（理由同商品分类： |  |
| `delete_category` | 写 | `DELETE /api/v1/place-categories/{category_id}` | 删掉自己名册里的一行。**还有地点挂着时拒绝**（告诉有几条）。 |  |

## 共享地点库（`places`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `list_places` | 只读 | `GET /api/v1/places` |  |  |
| `create_place` | 写 | `POST /api/v1/places` | 往共享地点库加一个点；**坐标 ≤1 米内已有点时并入那一条**（不新建重复行）。 |  |
| `use_place` | 写 | `POST /api/v1/places/{place_id}/use` | 记一次"我用了这个共享地点"；**同一个人用到第 2 次就自动收进他自己的地点库**。 |  |
| `get_place` | 只读 | `GET /api/v1/places/{place_id}` |  |  |

## 批发商定价（`price_rules`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `batch_price_rules` | 写 | `POST /api/v1/price-rules/batch` | 批量调价：多批发商 × 多商品 一次写价。 |  |
| `list_price_rules` | 只读 | `GET /api/v1/price-rules` | 专属价列表。三个筛选条件的关系是**先锁角色、再叠加**，谁也绕不过角色那一层： |  |
| `create_price_rule` | 写 | `POST /api/v1/price-rules` |  |  |
| `get_price_rule` | 只读 | `GET /api/v1/price-rules/{rule_id}` | 日志里要写**人看得懂的名字**，不是编号（编号在审计页上没有任何意义）。 |  |
| `update_price_rule` | 写 | `PATCH /api/v1/price-rules/{rule_id}` |  |  |
| `delete_price_rule` | 写 | `DELETE /api/v1/price-rules/{rule_id}` |  |  |

## 商品分类（`product_categories`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `list_categories` | 只读 | `GET /api/v1/product-categories` | 分类名册（按显示顺序）。**任何登录角色都能读** —— 下单页要用它排左侧那一列。 |  |
| `create_category` | 写 | `POST /api/v1/product-categories` |  |  |
| `update_category` | 写 | `PATCH /api/v1/product-categories/{category_id}` | 改名 / 改顺序。**改名会级联改掉挂在它下面的商品**（同一事务，见模块注释）。 |  |
| `reorder_categories` | 写 | `POST /api/v1/product-categories/reorder` | 整份顺序一次提交：`ids[0]` 排最前。 |  |
| `delete_category` | 写 | `DELETE /api/v1/product-categories/{category_id}` | 删除分类名册里的一行。**还有商品挂着时拒绝**（告诉有几个）。 |  |

## 商品管理（`products`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `list_products` | 只读 | `GET /api/v1/products` |  |  |
| `create_product` | 写 | `POST /api/v1/products` |  |  |
| `product_cost_history` | 只读 | `GET /api/v1/products/cost-history` | 成本价的**生效时间轴**（新的在前）：某个价从什么时候到什么时候、是哪来的。 |  |
| `get_product` | 只读 | `GET /api/v1/products/{product_id}` |  |  |
| `update_product` | 写 | `PATCH /api/v1/products/{product_id}` | 按请求中**实际出现的字段**更新（含显式 name_color=null 以清除颜色）。 |  |
| `upload_product_image` | 写 | `POST /api/v1/products/{product_id}/image` | 上传商品展示图，写入 image_url（静态路径）。 |  |
| `delete_product` | 写 | `DELETE /api/v1/products/{product_id}` | **软删除**商品（可 `POST /{id}/restore` 恢复）。下架请用 PATCH is_active=false。 |  |
| `restore_product` | 写 | `POST /api/v1/products/{product_id}/restore` | 把软删除的商品恢复回来（`DELETE /{id}` 的逆操作）。 |  |

## 报表中心（`reports`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `turnover_report` | 只读 | `GET /api/v1/reports/turnover` |  |  |
| `product_report` | 只读 | `GET /api/v1/reports/products` |  |  |
| `arrears_summary` | 只读 | `GET /api/v1/reports/arrears-summary` |  |  |
| `export_report` | 只读 | `GET /api/v1/reports/export` | 报表 Excel 导出（内存流 xlsx）。 |  |

## 地址与联系人（`shipper`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `list_addresses` | 只读 | `GET /api/v1/shipper/addresses` |  |  |
| `create_address` | 写 | `POST /api/v1/shipper/addresses` |  |  |
| `get_address` | 只读 | `GET /api/v1/shipper/addresses/{address_id}` |  |  |
| `update_address` | 写 | `PATCH /api/v1/shipper/addresses/{address_id}` |  |  |
| `delete_address` | 写 | `DELETE /api/v1/shipper/addresses/{address_id}` |  |  |
| `restore_address` | 写 | `POST /api/v1/shipper/addresses/{address_id}/restore` | 把删掉的常用地址恢复回来（DELETE /addresses/{id} 的逆操作）。 |  |
| `set_default_address` | 写 | `POST /api/v1/shipper/addresses/{address_id}/set-default` |  |  |
| `list_contacts` | 只读 | `GET /api/v1/shipper/contacts` |  |  |
| `upsert_contact` | 写 | `POST /api/v1/shipper/contacts` |  |  |
| `update_contact` | 写 | `PATCH /api/v1/shipper/contacts/{contact_id}` |  |  |
| `upload_location_image` | 写 | `POST /api/v1/shipper/locations/image` | 上传地点图片（创建订单时随地点信息一并带入）。 |  |
| `list_locations` | 只读 | `GET /api/v1/shipper/locations` |  |  |
| `create_location` | 写 | `POST /api/v1/shipper/locations` |  |  |
| `update_location` | 写 | `PATCH /api/v1/shipper/locations/{location_id}` |  |  |
| `delete_location` | 写 | `DELETE /api/v1/shipper/locations/{location_id}` | 把删掉的地点恢复回来（DELETE /locations/{id} 的逆操作）。 |  |
| `restore_location` | 写 | `POST /api/v1/shipper/locations/{location_id}/restore` | 把删掉的地点恢复回来（DELETE /locations/{id} 的逆操作）。 |  |
| `delete_contact` | 写 | `DELETE /api/v1/shipper/contacts/{contact_id}` |  |  |
| `restore_contact` | 写 | `POST /api/v1/shipper/contacts/{contact_id}/restore` | 把删掉的联系人恢复回来（DELETE /contacts/{id} 的逆操作）。 |  |

## 统计口径（`stats`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `get_shipper_product_chart` | 只读 | `GET /api/v1/stats/shipper-product-chart` |  |  |
| `get_shipper_activity` | 只读 | `GET /api/v1/stats/shipper-activity` |  |  |
| `get_product_drilldown` | 只读 | `GET /api/v1/stats/product-drilldown` |  |  |
| `get_driver_performance` | 只读 | `GET /api/v1/stats/driver-performance` |  |  |
| `get_shipper_performance` | 只读 | `GET /api/v1/stats/shipper-performance` |  |  |
| `get_exception_orders` | 只读 | `GET /api/v1/stats/exception-orders` |  |  |
| `resolve_exception_order` | 写 | `POST /api/v1/stats/exception-orders/{order_id}/resolve` | 派单员解决异常：填写解决说明，订单标记已解决。 |  |
| `post_stats_export` | 只读 | `POST /api/v1/stats/export` |  |  |

## 司机/货主/批发商/账号（`users`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `read_me` | 只读 | `GET /api/v1/users/me` |  |  |
| `list_users` | 只读 | `GET /api/v1/users` |  |  |
| `create_user` | 写 | `POST /api/v1/users` |  |  |
| `get_user` | 只读 | `GET /api/v1/users/{user_id}` |  |  |
| `get_product_visibility` | 只读 | `GET /api/v1/users/{user_id}/product-visibility` | 某个货主/批发商能看到哪些商品（白名单）。派单员在用户编辑页回显它。 |  |
| `set_product_visibility` | 写 | `PUT /api/v1/users/{user_id}/product-visibility` | 整份设置某个货主/批发商的可见商品（**白名单**：勾了的才给他看）。 |  |
| `update_user` | 写 | `PATCH /api/v1/users/{user_id}` |  |  |
| `swap_shipper_driver` | 写 | `POST /api/v1/users/{user_id}/swap-shipper-driver` | 货主 ↔ 司机身份切换（派单员操作）。派单员账号不可切换。 |  |
| `delete_user` | 写 | `DELETE /api/v1/users/{user_id}` |  |  |
| `restore_user` | 写 | `POST /api/v1/users/{user_id}/restore` | 把删掉的账号恢复回来（`DELETE /{id}` 的逆操作）。 |  |

## 车辆管理（`vehicles`）

| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |
|---|---|---|---|---|
| `list_vehicles` | 只读 | `GET /api/v1/vehicles` |  |  |
| `create_vehicle` | 写 | `POST /api/v1/vehicles` |  |  |
| `update_vehicle` | 写 | `PATCH /api/v1/vehicles/{vehicle_id}` |  |  |
| `set_vehicle_driver` | 写 | `POST /api/v1/vehicles/{vehicle_id}/driver` | 把车绑给某个司机 / 解绑。`driver_id` 缺省或 null **都算解绑**。 |  |
