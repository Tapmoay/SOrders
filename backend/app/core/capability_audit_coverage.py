'''审计覆盖：**能力 ↔ 审计动作码**（R3-02-C）。

## 为什么是「覆盖」而不是「一一对应」（指南 §R3-02-C 的原话）

> 不要假设「一个 capability = 一个 audit action」。有些业务动作可能：
> 一个 capability → 多个具体 audit events。所以你真正需要定义的是 Capability → Audit Coverage，
> 而不是简单一一映射。

这张表就是那句话的落地，一共三张：

· `AUDIT_COVERAGE`：能力键 → **这个能力会写下的全部动作码**（可以 1:N，也可以 N:1 ——
  例如 `ORDER_CANCEL` 同时属于「货主撤单」与「派单员撤单」两个能力）；
· `AUDIT_EXCEPTIONS`：**至今说不清归属**的动作码 —— 每一条都要写理由与「什么时候删掉这一条」；
· `AUDIT_CAPABILITY_EXEMPT`：**写能力但一个动作码都没有**的 —— 同样要写清楚为什么。

## 归属是怎么定的（不是猜的）

逐块读了网关（`api/v1/*.py` 的 `Depends(require_permission(...))` / 角色门）：

| 动作码前缀 | 网关 |
| --- | --- |
| `FREIGHT_TEMPLATE_*` / `FREIGHT_CATEGORY_*` | `freight_templates.py` → `Permission.ORDER_DISPATCH` |
| `DRIVER_RULE_*` | `driver_billing_rules.py` → `ORDER_DISPATCH` + `USER_MANAGE` |
| `ORDER_TEMPLATE_*` | `order_templates.py` → `Permission.ORDER_EDIT` |
| `SUPPLIER_*` | `suppliers.py` → `Permission.LEDGER_EDIT` |
| `ARREARS_UNIT_*` | `arrears.py` → `Permission.LEDGER_EDIT` |
| `VEHICLE_*` | `vehicles.py:46 _must_dispatcher`（体内角色判断，没有权限点） |

## 判据看到什么、看不到什么（说清楚，免得被当成更强的保证）

✅ 判据能核：每个**写**能力要么有动作码、要么进了豁免表；每个动作码要么被认领、要么进了例外表；
   表里出现的名字必须真的是 `OperationAction` 成员 / 能力键（防化石）；关系**不是双射**；
   被认领的动作码必须在后端源码里**真的被写过**（不是死枚举）；例外与豁免都是只减不增的棘轮。

⛔ 判据**核不了**：「这个动作码确实由这个能力授权」—— 那要逐条读写入点的鉴权，本轮没做。
   所以这里认证的是**覆盖与命名**，不是授权推导。这句话写在这里，是为了不让下一个人以为它证明了更多。
'''
from __future__ import annotations

#: 能力键（`Permission` 的**值**，或 `role_capabilities.RoleCapability.key`）→ 它会写下的动作码。
AUDIT_COVERAGE: dict[str, tuple[str, ...]] = {
    # ---- 订单 ----
    'order:create': ('ORDER_CREATE',),
    'order:edit': ('ORDER_UPDATE', 'ORDER_EXCEPTION', 'ORDER_SPLIT', 'ORDER_FREIGHT', 'ORDER_FREIGHT_PRICE',
                   'ORDER_TEMPLATE_UPSERT', 'ORDER_TEMPLATE_DELETE', 'ORDER_TEMPLATE_RESTORE',
                   'ORDER_TEMPLATE_CATEGORY_UPSERT', 'ORDER_TEMPLATE_CATEGORY_DELETE',
                   'ORDER_TEMPLATE_CATEGORY_REORDER'),
    'order:dispatch': ('ORDER_DISPATCH', 'ORDER_NAVIGATION_FILL', 'FREIGHT_TEMPLATE_UPSERT',
                      'FREIGHT_TEMPLATE_DELETE', 'FREIGHT_TEMPLATE_RESTORE', 'FREIGHT_CATEGORY_UPSERT',
                      'FREIGHT_CATEGORY_DELETE', 'FREIGHT_CATEGORY_REORDER', 'DRIVER_RULE_UPSERT',
                      'DRIVER_RULE_ATTACH'),
    'order:recall': ('ORDER_RECALL',),
    'order:cancel_dispatcher': ('ORDER_CANCEL',),
    'order:cancel_shipper': ('ORDER_CANCEL',),
    'order:delete_cancelled': ('ORDER_DELETE', 'ORDER_RESTORE'),
    'order:return': ('ORDER_RETURN', 'ORDER_RETURN_REQUEST_REJECT', 'ORDER_RETURN_REQUEST_CLOSE'),
    'order:return_request': ('ORDER_RETURN_REQUEST', 'ORDER_RETURN_REQUEST_WITHDRAW'),
    'order_product:edit': ('ORDER_LINE_ADD', 'ORDER_LINE_UPDATE', 'ORDER_LINE_DELETE'),
    'order:complete_driver': ('ORDER_COMPLETE',),
    # ---- 钱 ----
    'ledger:edit': ('LEDGER_CREATE', 'LEDGER_UPDATE', 'LEDGER_DELETE', 'RECEIPT_CREATE', 'EXPENSE_CREATE',
                    'EXPENSE_CATEGORY_UPSERT', 'EXPENSE_CATEGORY_DELETE', 'EXPENSE_CATEGORY_REORDER',
                    'SHIPPER_SETTLE_CREATE', 'SHIPPER_SETTLE_REVOKE', 'SHIPPER_SETTLE_RESTORE',
                    'DRIVER_BILL_GENERATE', 'SETTLEMENT_CREATE', 'SETTLEMENT_STATUS',
                    'SUPPLIER_UPSERT', 'SUPPLIER_DELETE', 'SUPPLIER_RESTORE', 'SUPPLIER_PAYABLE_UPSERT',
                    'SUPPLIER_PAYABLE_DELETE', 'SUPPLIER_PAYABLE_RESTORE', 'SUPPLIER_PAYMENT_CREATE',
                    'SUPPLIER_PAYMENT_CANCEL', 'SUPPLIER_PAYMENT_RESTORE', 'ARREARS_UNIT_UPSERT',
                    'ARREARS_UNIT_DELETE', 'ARREARS_UNIT_RESTORE'),
    'price_rule:manage': ('PRICE_RULE_UPSERT',),
    # ---- 商品 / 库存 ----
    'product:manage': ('PRODUCT_CREATE', 'PRODUCT_UPDATE', 'PRODUCT_DELETE', 'PRODUCT_RESTORE',
                       'PRODUCT_VISIBILITY_SET', 'PRODUCT_CATEGORY_UPSERT', 'PRODUCT_CATEGORY_DELETE',
                       'PRODUCT_CATEGORY_REORDER', 'INVENTORY_ADJUST'),
    # ---- 账号 / 通知 ----
    'user:manage': ('USER_CREATE', 'USER_UPDATE', 'USER_DELETE', 'USER_RESTORE', 'CUSTOMER_MERGE'),
    'notification:manage': ('NOTIFICATION_MODERATE',),
    # ---- 角色能力（没有权限点的那几块，见 role_capabilities.py）----
    'place:manage': ('PLACE_AUTO_ADDED', 'PLACE_UPDATE', 'PLACE_PUBLISH', 'PLACE_DEMOTE', 'PLACE_DELETE',
                     'PLACE_RESTORE', 'PLACE_CATEGORY_UPSERT', 'PLACE_CATEGORY_DELETE', 'PLACE_CATEGORY_REORDER'),
    'unit_conversion:manage': ('UNIT_CONVERSION_UPSERT', 'UNIT_CONVERSION_DELETE', 'UNIT_CONVERSION_RESTORE'),
    'vehicle:manage': ('VEHICLE_UPSERT', 'VEHICLE_DRIVER_SET'),
    'address:manage': (),
    'shipper_ledger:read_own': (),
}

#: 动作码 → 为什么没有能力认领 + **什么时候删掉这一条**。⛔ 空表不是「没检查」，是「每条都有着落」。
AUDIT_EXCEPTIONS: dict[str, str] = {
    'AI_UNDO': '这是 AI 撤回卡走的那条路（`AiWriteRestore`）：撤回的是**上一次写动作**，'
               '而那条写动作本身已经留下过自己的动作码了 —— 再记一个只会让审计页出现两行同一件事。'
               '**什么时候删掉这一条**：如果哪天撤回也要独立留痕（比如「谁撤回的、撤回后值变成什么」要能单独查），'
               '就给它一个能力（那意味着 AI 写链路也要进 Capability 表）。',
}

#: 写能力 → 为什么它一个动作码都没有（留痕走的是别的路）。
AUDIT_CAPABILITY_EXEMPT: dict[str, str] = {
    'order:internal_note': '司机/派单员给订单写内部备注：它写在 `orders.internal_notes` **字段**上，'
                            '订单自己的状态与字段变化就是留痕（`ORDER_UPDATE` 那条覆盖了它）。'
                            '**什么时候删掉这一条**：如果内部备注要单独可查（现在只能在订单详情里看）。',
    'order:upload_delivery': '司机上传送达照片：留痕是**图片本体**（`delivery_photos` 表）与订单状态，'
                             '不是操作日志。**什么时候删掉这一条**：如果照片要做「谁在什么时候传的第几张」这类追溯。',
    'address:manage': '地址与联系人没有独立的审计动作码（`OperationAction` 里一个 `ADDRESS_*` 都没有）。'
                       '**什么时候删掉这一条**：如果地址库要可审计（谁改了谁家的地址），先加动作码、再来销这一条。',
}

#: 例外与豁免的条数上限（⛔ 只减不增）：
EXCEPTION_RATCHET = 1
EXEMPT_RATCHET = 3

