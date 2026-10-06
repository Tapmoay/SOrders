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

## 另一件事（台账 L-32）：下单与改单时，这四个字段**不能全空**
上面那套是"事后看得出来"（出参 `contact_risk`），这一套是"事前不让它发生"：
`contact_dongjia_*` / `contact_boss_*` 四个字段全空的单，用户口述是「**不可能存在**的」（m01132）。
判据只有一份（`contact_info_missing`），四个落点都调它：下单 `create_order`、改单 `update_order`
（按**合并后的结果**判）、转货新开单 `_create_target_order`、拆单 `split_order`。
⛔ 不做数据库约束（NOT NULL / CHECK）：存量空单会被迁移炸掉；
⛔ 也不写在 Pydantic 那层：`_shipper_xor_temp` 在「下单人＝货主」兜底**之前**跑，会把合格单误拒。
"""

from __future__ import annotations

from collections.abc import Mapping

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


# ---- L-32：下单 / 改单时「下单人 或 收货人」至少有一个有信息 -------------------------
#: 四个联系信息字段 —— **任一个非空即合格**（名字或电话，任选一端）。
#: ⚠️ 与 `CONTACT_NAME_FIELDS` 是**两套**判据（那套只看两个姓名，是"账上认不认得出人"），
#:    台账明令不许合并：一个是事后提示，一个是事前拦截，口径本来就不一样。
CONTACT_INFO_FIELDS: tuple[str, ...] = (
    "contact_dongjia_name",
    "contact_dongjia_phone",
    "contact_boss_name",
    "contact_boss_phone",
)

#: 四个都空时对用户说的那一句话（后端四个落点 + 客户端文案**同源**，⛔ 不许各写一句）。
CONTACT_INFO_REQUIRED = "请填写收货人或下单人（名字或电话，至少一个）"


def merged_contact_info(*sources: object) -> dict[str, str]:
    """把几份"联系信息"按**先后顺序**叠起来（后写覆盖先写）。

    三种形状都认：ORM 行（`Order`）、Pydantic 入参（`OrderCreate` / `OrderUpdate`）、普通 dict。
    ⚠️ `None` 表示"这一份没说这个字段"（`OrderUpdate` 的部分更新语义）⇒ **不算改**，
    所以改单要按"库里的值 + 请求体"叠出来的**合并结果**判，而不是只看请求体。
    """
    merged: dict[str, str] = dict.fromkeys(CONTACT_INFO_FIELDS, "")
    for source in sources:
        if source is None:
            continue
        for field in CONTACT_INFO_FIELDS:
            if isinstance(source, Mapping):
                raw = source.get(field)
            else:
                raw = getattr(source, field, None)
            if raw is None:
                continue
            merged[field] = str(raw).strip()
    return merged


def contact_info_missing(source: object) -> bool:
    """四个联系字段**全空** ⇒ True（"这一单认不出人"的唯一判法，L-32 的四个落点都调它）。

    ⛔ 只去空白，与 `contact_name_blank` / 账本 SQL 的 `nullif(trim(...))` 同一口径。
    """
    return all(not value for value in merged_contact_info(source).values())
