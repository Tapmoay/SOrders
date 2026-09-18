"""共享地点库（导航信息）的入参 / 出参。"""

from __future__ import annotations

from decimal import Decimal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from app.schemas.geo import GeoInput
from app.schemas.text import MAX_ADDRESS, MAX_NAME


class PlaceCreate(GeoInput):
    """手工往共享地点库里加一个点（货主/派单员录入）。"""

    name: str = Field(default="", max_length=MAX_NAME)
    detail_address: str = Field(default="", max_length=MAX_ADDRESS)
    address_lat: Decimal
    address_lng: Decimal

    @model_validator(mode="after")
    def _coords_required(self) -> "PlaceCreate":
        # 地点库的**唯一硬条件就是有坐标**：没有坐标的"地点"是地址簿，不是导航信息，
        # 而地址簿有另外三张表（shipper_addresses / shipper_locations / shipper_contacts）。
        # `GeoInput` 只校验范围，不校验存在性——两个 `None` 都能过，所以这里补一刀。
        if self.address_lat is None or self.address_lng is None:
            raise ValueError("共享地点必须有坐标（这是给导航用的，不是文字地址）")
        return self

    @model_validator(mode="after")
    def _needs_a_name(self) -> "PlaceCreate":
        """**名字和地址不能都是空**（2026-09-18 加的，因为这张表**没有删除接口**）。

        为什么这条比看起来重要：`places` 是**全库共享**的一张表，而且**没有任何入口能删掉一条**
        —— 所以一条没有名字的记录是**永久的**：它会在每个人的「共享地点」列表里显示成
        「未命名地点」+ 空地址，谁也认不出那是哪儿，谁也没法清理。
        （开发库里真出现过一条：合同模糊测试往 `POST /places` 打了 5 次空名请求，
        按 1 米合并成一条 `name="   "` 的记录 —— 修好 strip 之后它会变成 `""`，
        但"空名记录"这件事本身还是该在入口拦掉。）

        只要求**二选一**：只要有一个能认出来的信息就够了（有人就是"先钉个点、地址回头补"）。
        """
        if not (self.name or "").strip() and not (self.detail_address or "").strip():
            raise ValueError("请给这个地点起个名字或填个地址（共享库里只有坐标的话，别人认不出是哪儿）")
        return self


class PlaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str = ""
    detail_address: str = ""
    # 出参沿用全项目的 `address_lat/address_lng` 命名（与 shipper_addresses/orders 一致），
    # 而模型列名是 `lat/lng`。
    # ⚠️ `validation_alias` 是必需的，不是风格问题：`from_attributes` 只找同名属性，
    #    找不到就报 missing —— 或者更糟，字段有默认值时**静默落默认值**。
    #    凡是"出参名 ≠ 列名"的字段都必须显式写这一行。
    address_lat: Decimal = Field(validation_alias=AliasChoices("address_lat", "lat"))
    address_lng: Decimal = Field(validation_alias=AliasChoices("address_lng", "lng"))
    source: str = "driver"
    use_count: int = 1
    # 本次是"并入了已有地点"还是"新建了一个点"（只在本接口的返回里有意义；列表恒为 False）
    merged: bool = False


class PlaceUseOut(BaseModel):
    """"我用了一次这个共享地点"的答复。

    `auto_added=True` 只有在**刚好跨过阈值那一次**才会出现（`place_service.AUTO_ADD_AFTER`），
    界面要据它说一句"已加进「我的地点」"——不能不说，也不能每次都说。
    """

    place_id: int
    #: 我累计用过这个地点几次
    use_count: int
    #: 这一次是否**刚刚**把它自动加进了我的地点库
    auto_added: bool = False


class OrderNavigationBody(GeoInput):
    """司机/派单员给一张**还没有坐标**的订单补上导航信息。"""

    address_lat: Decimal
    address_lng: Decimal
    # 地点名（选填）：货主地点库里显示的就是它；留空则用订单原有收货地址
    name: str = Field(default="", max_length=MAX_NAME)
    # 顺带把文字地址补/改掉（选填）：司机在现场往往比下单人更清楚具体是哪一栋
    detail_address: str = Field(default="", max_length=MAX_ADDRESS)

    @model_validator(mode="after")
    def _coords_required(self) -> "OrderNavigationBody":
        if self.address_lat is None or self.address_lng is None:
            raise ValueError("补导航信息需要具体的坐标（经纬度都要有）")
        return self
