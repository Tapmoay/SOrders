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
