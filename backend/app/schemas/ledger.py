from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import LedgerSource
from app.schemas.money import MoneyInput
from app.schemas.text import MAX_TEXT


class LedgerCreate(MoneyInput):
    shipper_id: int | None = None
    temp_shipper_name: str | None = Field(None, max_length=128)
    entry_date: date
    product_name: str = Field(..., min_length=1, max_length=256)
    quantity: int = Field(default=1, ge=1)
    unit_price: Decimal = Field(default=Decimal("0"))
    total: Decimal | None = Field(default=None)
    order_id: int | None = None
    order_product_id: int | None = None
    product_id: int | None = None
    source: LedgerSource = LedgerSource.MANUAL
    note: str = Field("", max_length=MAX_TEXT)

    @model_validator(mode="after")
    def _one_shipper_bucket(self) -> "LedgerCreate":
        has_id = self.shipper_id is not None
        tn = (self.temp_shipper_name or "").strip()
        if has_id and tn:
            raise ValueError("不能同时指定货主账号与临时货主名称")
        if not has_id and not tn:
            raise ValueError("请指定货主账号或临时货主名称")
        if tn:
            object.__setattr__(self, "temp_shipper_name", tn)
        else:
            object.__setattr__(self, "temp_shipper_name", None)
        return self


class LedgerUpdate(MoneyInput):
    """账本编辑：自动订单行仅备注；手动行可改明细（关联订单仅作核对，不回写订单明细）。"""

    note: str | None = Field(None, max_length=MAX_TEXT)
    entry_date: date | None = None
    product_name: str | None = Field(None, min_length=1, max_length=256)
    quantity: int | None = Field(None, ge=1)
    unit_price: Decimal | None = None
    total: Decimal | None = None
    order_id: int | None = None
    product_id: int | None = None


class LedgerSyncFromOrdersBody(BaseModel):
    """从历史已送达订单补全/刷新账本行（幂等）。"""

    shipper_id: int | None = Field(
        None,
        description="仅处理该系统货主的订单",
    )
    temp_shipper_name: str | None = Field(
        None,
        max_length=128,
        description="仅处理该临时货主名称的订单（与 shipper_id 互斥）",
    )

    @model_validator(mode="after")
    def _xor(self) -> "LedgerSyncFromOrdersBody":
        sid = self.shipper_id
        tn = (self.temp_shipper_name or "").strip()
        if sid is not None and tn:
            raise ValueError("不能同时指定 shipper_id 与 temp_shipper_name")
        if tn:
            object.__setattr__(self, "temp_shipper_name", tn)
        else:
            object.__setattr__(self, "temp_shipper_name", None)
        return self


class LedgerAccountOut(BaseModel):
    """账本账户汇总（派单员按货主/批发商维度）。"""

    id: int | None = None          # shipper_id；临时货主为 None
    temp_name: str | None = None
    name: str
    #: 注册货主的手机号（临时货主为 None）。
    #  ⚠️ 2026-09-19 补：**同名不同人**在账本里本来就分不开（两个「张老板」是两行一模一样的卡），
    #    而用户 2026-09-19 要的搜索键是「名称 / 电话号码 / 电话号码后 4 位」——
    #    手机号不下发，App 就**只能按名字搜**，等于那条需求只做了一半。
    #    带软删后缀的（`13800001234_del160`）在这里已经去尾（见 `strip_del_suffix`）：
    #    给用户看的是一个**能拨的号**。
    phone: str | None = None
    #: 这个账号还能不能登录（停用/已删除都算 false）。仪表盘要据此标出来 ——
    #  一个登不进来的货主混在名单里，用户会以为"他只是没下单"。
    is_active: bool = True
    count: int
    total: Decimal


class LedgerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shipper_id: int | None = None
    temp_shipper_name: str | None = None
    #: 这一笔挂在**谁**名下（注册货主 → 人名/手机号；临时货主 → 那句称呼）。
    #  ⚠️ 2026-09-19 补：原来只有 `shipper_id` + `temp_shipper_name`，
    #    于是**注册货主**的账在「订单账」那一栏全部显示成「临时货主」——**名字根本没下发**。
    #    而 AI 又**看不到任何内部编号**（本项目第一条硬规矩），只给 id 等于让模型
    #    读得到这张表却**说不出这一笔是谁的**。
    #    由后端算（`ledger_response._shipper_name`，**一次 IN 批量取人**）而不是客户端拿 id 去查。
    shipper_name: str | None = None
    entry_date: date
    product_name: str
    quantity: int
    unit_price: Decimal
    total: Decimal
    order_id: int | None
    order_product_id: int | None = None
    product_id: int | None
    order_no: str | None = None
    order_delivery_description: str | None = Field(
        None,
        description="关联订单的送货说明（如规格/定制要求摘要），便于区分同名商品",
    )
    source: LedgerSource
    note: str
    created_at: datetime
