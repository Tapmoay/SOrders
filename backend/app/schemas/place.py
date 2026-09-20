"""共享地点库（导航信息）的入参 / 出参。"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.geo import GeoInput
from app.schemas.text import MAX_ADDRESS, MAX_IMAGES, MAX_NAME
from app.services import place_service

#: `(0,0)` 哨兵的判据阈值 —— 与安卓侧 `core/SunLocation.isPlausible` 是同一个数。
_SENTINEL_EPS = Decimal("0.01")


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
        # ⛔ `(0,0)` 是"**没有定位**"的占位值，不是坐标（2026-09-19 全项目报告 P1-13，中）：
        #    高德定位失败回的就是 `(0,0)`（不是 null），而安卓的地图选点在修好之前会把它
        #    原样交出来 → 于是它既进了订单、也进了这张**没有删除接口**的表（脏点是永久的，
        #    而且会被别人的单复用来当导航点）。
        #    判据与安卓侧 `core/SunLocation.isPlausible` **同一个阈值**（两个绝对值都 < 0.01）：
        #    "这个坐标是不是真的"在本仓只该有一处口径。
        #    ⚠️ 只拦**这一对**：单独一个 `0` 是合法坐标（赤道 / 本初子午线上的地点）。
        #    闸放在这里而不是 `GeoInput`：`places` **只有 GET/POST，没有改和删**，
        #    所以这道闸零误伤；而地址/订单那几张表有历史脏行，拦在它们入口会让
        #    "改个电话"也被迫先重选坐标 —— 那是另一件要单独拍板的事。
        if abs(self.address_lat) < _SENTINEL_EPS and abs(self.address_lng) < _SENTINEL_EPS:
            raise ValueError("这两个数是「没有定位」的占位值（0,0），不是坐标：请在地图上重新选点")
        return self

    @model_validator(mode="after")
    def _needs_a_name(self) -> "PlaceCreate":
        """**名字和地址不能都是空**（2026-09-18 加的，因为这张表当时**没有任何入口能删掉一条**）。

        为什么这条比看起来重要：`places` 是**全库共享**的一张表 —— 所以一条没有名字的记录
        是**所有人都要看的**：它会在每个人的「共享地点」列表里显示成「未命名地点」+ 空地址，
        谁也认不出那是哪儿。（开发库里真出现过一条：合同模糊测试往 `POST /places` 打了 5 次
        空名请求，按 1 米合并成一条 `name="   "` 的记录。）

        只要求**二选一**：只要有一个能认出来的信息就够了（有人就是"先钉个点、地址回头补"）。

        ⚠️ 判据本身在 `services/place_service.identify_error`（**只有那一处**）：
        2026-09-19 加了"改共享地址"之后，同一句话也要用在校验**改完之后的整行**上，
        而校验器只看得到入参、看不到那一行 —— 所以那句话搬到服务层，这里反过来引它。
        """
        err = place_service.identify_error(self.name, self.detail_address)
        if err:
            raise ValueError(err)
        return self


class PlaceUpdate(BaseModel):
    """改共享地址（**只有派单员**，见 `api/v1/places.py`）。

    部分更新语义：`None` = 这个字段不动（`""` = 清空）。两个字段都不传是**空操作**，
    接口会直接 400 —— 让一次什么都没改的请求返回 200，界面上看起来像"改成功了"。
    """

    name: str | None = Field(None, max_length=MAX_NAME)
    detail_address: str | None = Field(None, max_length=MAX_ADDRESS)


class PlaceDemoteOut(BaseModel):
    """「撤销共享地址」的答复：撤下来之后它落在**操作人自己的**「我的地点」里的那一条。

    `created=False` 表示操作人自己的地点库里**本来就有**这个点（按 1 米/同名 30 米判），
    只是把共享库里那条撤掉了 —— 界面要如实说，不能让用户以为"多出来一条"。
    """

    place_id: int
    location_id: int
    created: bool


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
    # 位置照片（2026-09-20 加：用户要「共享库也加上图片」）。
    # ⚠️ JSON 列在旧数据里可能是 NULL —— `default_factory` 只兜字段缺失、不兜 None
    #    （全项目同一条规矩，见 `_ImageUrlsMixin`）。校验器把 None 归一 []。
    image_urls: list[str] = Field(default_factory=list, max_length=MAX_IMAGES)
    # 首图（兼容旧读出方）：与 `image_urls[0]` 同源
    image_url: str | None = None

    @field_validator("image_urls", mode="before")
    @classmethod
    def _norm_images(cls, v: Any) -> list[str]:
        """模型列是 JSON 字符串（或 None）；旧数据可能是 NULL → 一律归一成列表。"""
        if v is None:
            return []
        if isinstance(v, str):
            try:
                loaded = json.loads(v or "[]")
            except Exception:
                return []
            return [x for x in loaded if isinstance(x, str)] if isinstance(loaded, list) else []
        return v

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
