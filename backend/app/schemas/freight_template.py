from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.money import MoneyInput


class FreightTemplateBase(MoneyInput):
    name: str = Field(..., min_length=1, max_length=128)
    #: 挂在哪条路线上（`shipper_addresses.id`）。给了它就用路线的起点/终点当快照。
    route_id: int | None = Field(None, ge=1)
    #: 起点/终点：**只在没有 route_id 时**才由调用方给（老客户端兼容）；
    #: 有 route_id 时这两个值会被路线的快照覆盖，免得"模板上的路线"和"实际路线"两处不一样。
    from_place: str = Field("", max_length=128)
    to_place: str = Field("", max_length=128)
    #: 这条价目叫什么（小车价 / 大车价 / 回程价…）
    price_name: str = Field("", max_length=32)
    vehicle_type: str | None = Field(None, max_length=16)
    fee: Decimal = Field(Decimal("0"), ge=0)
    remark: str = Field("", max_length=2000)
    #: 这条价目归哪些司机用（可以多个）。派单时选了司机就按它自动带价。
    driver_ids: list[int] = Field(default_factory=list, max_length=200)
    #: **这条价目算哪几类货**（运费分类名册里的编号，可以多个）。用户 2026-09-21：
    #: 「一个模板可以有多个分类」。派单匹配 = 路线 + 分类 + 司机 → 唯一一条价目。
    category_ids: list[int] = Field(default_factory=list, max_length=50)


class FreightTemplateCreate(FreightTemplateBase):
    pass


class FreightTemplateUpdate(MoneyInput):
    name: str | None = Field(None, min_length=1, max_length=128)
    route_id: int | None = Field(None, ge=1)
    from_place: str | None = Field(None, max_length=128)
    to_place: str | None = Field(None, max_length=128)
    price_name: str | None = Field(None, max_length=32)
    vehicle_type: str | None = Field(None, max_length=16)
    fee: Decimal | None = Field(None, ge=0)
    remark: str | None = Field(None, max_length=2000)
    #: `None` = 不动绑定；`[]` = 全部解绑（PATCH 语义，与图片那几个字段一致）
    driver_ids: list[int] | None = Field(None, max_length=200)
    #: 同上：`None` = 不动；`[]` = 这一类都不管了
    category_ids: list[int] | None = Field(None, max_length=50)


class FreightTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    route_id: int | None = None
    from_place: str
    to_place: str
    price_name: str = ""
    vehicle_type: str | None
    fee: Decimal
    remark: str
    created_by: int | None
    created_at: datetime
    #: 绑在这条价目上的司机编号（列表接口一次填好，界面不用再逐条问）
    driver_ids: list[int] = Field(default_factory=list)
    #: 这条价目算哪几类货（编号 + 名字都下发：名字用于显示，编号用于回填表单）
    category_ids: list[int] = Field(default_factory=list)
    category_names: list[str] = Field(default_factory=list)
    #: 这条价目**被哪几份计费规则用着**（价目归规则 —— 反向也要看得见）
    rule_names: list[str] = Field(default_factory=list)


class FreightQuoteCandidate(BaseModel):
    template_id: int
    name: str
    fee: Decimal
    price_name: str = ""
    route: str = ""
    category_names: list[str] = []
    driver_names: list[str] = []


class FreightQuoteOut(BaseModel):
    """这一单的运价结论（`matched` 为空时看 `reason` —— 界面直接显示那句话，不自己编）。"""

    matched: FreightQuoteCandidate | None = None
    category_id: int | None = None
    category_name: str = ""
    reason: str = ""
    #: 同样优先级的候选多于一条（**不猜**，让派单员挑）
    ambiguous: list[FreightQuoteCandidate] = []
