"""订单联系信息的风险判据（台账 L-28）——**这一单在账上认不认得出人**。

## 一句话
收货人姓名与下单人姓名**都空** ⇒ 这一单在任何「按人看」的账目里都归不进谁，
是「无主账」的入口（用户 m01132 的口径；m01199 追加的「存量里四个联系字段全空的那批
要能看见并补上」是本判据的**子集**：四个全空 ⇒ 两个名字必空）。

## 为什么只认这两个姓名字段，而不是四个联系字段
台账里的证据链只有一处认人，而它认的**只有名字**（`api/v1/shipper_ledger.py`）：

· `_customer_name_expr()` = `收货人名 → 下单人名 → 空`（SQL 表达式），
  它是账本页「按人分组」与「按人筛」的**唯一依据** —— ⛔ 与客户端
  `ui/shipper/ShipperLedgerGrouping.kt::customerNameOf` 逐字同源，
  空档名 `UNSET_CUSTOMER = "未指定货主"` 是两者共用的那一个。
· 货主记一笔核销时，`ShipperSettlement.customer_name` 照**同一套回退落库**
  （`api/v1/shipper_ledger.py` 的核销端点）—— 名字空的时候，
  日后这笔钱在账上说不清是向谁收的（设计立意见 `models/shipper_settlement.py`）。

电话为空**不改变**上面这两件事（电话是「同名不同电话不合并」的第二键）：
名字为空、电话各不相同时，同一批空名单还会**散成好几个都叫「未指定货主」的桶** ——
那正是台账里「账目怪相」的可见形状。

## 判据放服务端，客户端只读
规则只能有一处实现：出参 `OrderOut.contact_risk` 由 `order_response.enrich_order_out` 填，
客户端与 AI 都只读那个布尔值（⛔ 不许在 Kotlin 里照 `customerNameOf` 再判一遍 ——
那正是「同一个问题两个答案」的经典形状）。
"""

from __future__ import annotations

from app.models import Order

#: 账目认人时用的两个姓名字段（顺序与 `_customer_name_expr` 的回退顺序一致）。
CONTACT_NAME_FIELDS: tuple[str, ...] = ("contact_dongjia_name", "contact_boss_name")


def contact_name_blank(value: str | None) -> bool:
    """一个姓名算不算「没写」。

    ⛔ 只去空白，**不发明第二套口径**：与 `_customer_name_expr` 里的
    `nullif(trim(coalesce(…, 空串)), 空串)` 同一个判法（全是空格 = 空）。
    """
    return not (value or "").strip()


def contact_risk_of(order: Order) -> bool:
    """这一单要不要提示「联系信息没填全」（出参 `contact_risk` 的唯一算法）。

    ⚠️ 只看**两个姓名**，不看电话、不看派单员专属的地址与备注（理由见模块头）。
    """
    return all(contact_name_blank(getattr(order, f, None)) for f in CONTACT_NAME_FIELDS)
