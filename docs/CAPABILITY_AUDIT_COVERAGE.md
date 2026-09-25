# 能力 ↔ 审计覆盖（Capability Audit Coverage）

> **本文件由 `_tools/ai/_gen_capability_snapshot.py` 生成，不要手改。**
> 重新生成：`python _tools/ai/_gen_capability_snapshot.py`
>
> `source_hash = sha256:768fdd45c24c637a41e7bd4cc4623c52125ad29997f8e3551b56a1ca5df15bf2`

这张表回答：**一个写能力会留下哪些审计动作码**（指南 §R3-02-C：不要假设一一对应）。

> 名词：**动作码**（action code）= `backend/app/models/enums.py` 里 `OperationAction` 的成员名；
> 一个 capability 可以对应多个 action，一个 action 也可以由多个 capability 产生（例如 `ORDER_CANCEL`）。

| 能力 | 动作码 |
| --- | --- |
| `address:manage` | — |
| `ledger:edit` | `LEDGER_CREATE`, `LEDGER_UPDATE`, `LEDGER_DELETE`, `RECEIPT_CREATE`, `EXPENSE_CREATE`, `EXPENSE_CATEGORY_UPSERT`, `EXPENSE_CATEGORY_DELETE`, `EXPENSE_CATEGORY_REORDER`, `SHIPPER_SETTLE_CREATE`, `SHIPPER_SETTLE_REVOKE`, `SHIPPER_SETTLE_RESTORE`, `DRIVER_BILL_GENERATE`, `SETTLEMENT_CREATE`, `SETTLEMENT_STATUS`, `SUPPLIER_UPSERT`, `SUPPLIER_DELETE`, `SUPPLIER_RESTORE`, `SUPPLIER_PAYABLE_UPSERT`, `SUPPLIER_PAYABLE_DELETE`, `SUPPLIER_PAYABLE_RESTORE`, `SUPPLIER_PAYMENT_CREATE`, `SUPPLIER_PAYMENT_CANCEL`, `SUPPLIER_PAYMENT_RESTORE`, `ARREARS_UNIT_UPSERT`, `ARREARS_UNIT_DELETE`, `ARREARS_UNIT_RESTORE` |
| `notification:manage` | `NOTIFICATION_MODERATE` |
| `order:cancel_dispatcher` | `ORDER_CANCEL` |
| `order:cancel_shipper` | `ORDER_CANCEL` |
| `order:complete_driver` | `ORDER_COMPLETE` |
| `order:create` | `ORDER_CREATE` |
| `order:delete_cancelled` | `ORDER_DELETE`, `ORDER_RESTORE` |
| `order:dispatch` | `ORDER_DISPATCH`, `ORDER_NAVIGATION_FILL`, `FREIGHT_TEMPLATE_UPSERT`, `FREIGHT_TEMPLATE_DELETE`, `FREIGHT_TEMPLATE_RESTORE`, `FREIGHT_CATEGORY_UPSERT`, `FREIGHT_CATEGORY_DELETE`, `FREIGHT_CATEGORY_REORDER`, `DRIVER_RULE_UPSERT`, `DRIVER_RULE_ATTACH` |
| `order:edit` | `ORDER_UPDATE`, `ORDER_EXCEPTION`, `ORDER_SPLIT`, `ORDER_FREIGHT`, `ORDER_FREIGHT_PRICE`, `ORDER_TEMPLATE_UPSERT`, `ORDER_TEMPLATE_DELETE`, `ORDER_TEMPLATE_RESTORE`, `ORDER_TEMPLATE_CATEGORY_UPSERT`, `ORDER_TEMPLATE_CATEGORY_DELETE`, `ORDER_TEMPLATE_CATEGORY_REORDER` |
| `order:recall` | `ORDER_RECALL` |
| `order:return` | `ORDER_RETURN`, `ORDER_RETURN_REQUEST_REJECT`, `ORDER_RETURN_REQUEST_CLOSE` |
| `order:return_request` | `ORDER_RETURN_REQUEST`, `ORDER_RETURN_REQUEST_WITHDRAW` |
| `order_product:edit` | `ORDER_LINE_ADD`, `ORDER_LINE_UPDATE`, `ORDER_LINE_DELETE` |
| `place:manage` | `PLACE_AUTO_ADDED`, `PLACE_UPDATE`, `PLACE_PUBLISH`, `PLACE_DEMOTE`, `PLACE_DELETE`, `PLACE_RESTORE`, `PLACE_CATEGORY_UPSERT`, `PLACE_CATEGORY_DELETE`, `PLACE_CATEGORY_REORDER` |
| `price_rule:manage` | `PRICE_RULE_UPSERT` |
| `product:manage` | `PRODUCT_CREATE`, `PRODUCT_UPDATE`, `PRODUCT_DELETE`, `PRODUCT_RESTORE`, `PRODUCT_VISIBILITY_SET`, `PRODUCT_CATEGORY_UPSERT`, `PRODUCT_CATEGORY_DELETE`, `PRODUCT_CATEGORY_REORDER`, `INVENTORY_ADJUST` |
| `shipper_ledger:read_own` | — |
| `unit_conversion:manage` | `UNIT_CONVERSION_UPSERT`, `UNIT_CONVERSION_DELETE`, `UNIT_CONVERSION_RESTORE` |
| `user:manage` | `USER_CREATE`, `USER_UPDATE`, `USER_DELETE`, `USER_RESTORE`, `CUSTOMER_MERGE` |
| `vehicle:manage` | `VEHICLE_UPSERT`, `VEHICLE_DRIVER_SET` |

## 例外：没有能力认领的动作码

| 动作码 | 为什么 + 什么时候删掉这一条 |
| --- | --- |
| `AI_UNDO` | 这是 AI 撤回卡走的那条路（`AiWriteRestore`）：撤回的是**上一次写动作**，而那条写动作本身已经留下过自己的动作码了 —— 再记一个只会让审计页出现两行同一件事。**什么时候删掉这一条**：如果哪天撤回也要独立留痕（比如「谁撤回的、撤回后值变成什么」要能单独查），就给它一个能力（那意味着 AI 写链路也要进 Capability 表）。 |

## 豁免：写能力但一个动作码都没有

| 能力 | 为什么 + 什么时候删掉这一条 |
| --- | --- |
| `address:manage` | 地址与联系人没有独立的审计动作码（`OperationAction` 里一个 `ADDRESS_*` 都没有）。**什么时候删掉这一条**：如果地址库要可审计（谁改了谁家的地址），先加动作码、再来销这一条。 |
| `order:internal_note` | 司机/派单员给订单写内部备注：它写在 `orders.internal_notes` **字段**上，订单自己的状态与字段变化就是留痕（`ORDER_UPDATE` 那条覆盖了它）。**什么时候删掉这一条**：如果内部备注要单独可查（现在只能在订单详情里看）。 |
| `order:upload_delivery` | 司机上传送达照片：留痕是**图片本体**（`delivery_photos` 表）与订单状态，不是操作日志。**什么时候删掉这一条**：如果照片要做「谁在什么时候传的第几张」这类追溯。 |

---

## 说明：这张表证明什么、不证明什么

✅ 证明**覆盖与命名**：每个写能力都有下落；每个动作码都有着落；名字都是真的；关系不是双射。
⛔ **不证明**「这个动作码确实由这个能力授权」—— 那要逐条读写入点的鉴权，本轮没做。
