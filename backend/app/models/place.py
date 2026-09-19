from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    pass


class Place(Base, TimestampMixin, SoftDeleteMixin):
    """**全局共享地点库**（导航信息）。

    ## 为什么要有这张表（不是"顺手多一张主数据"）
    下单时收货地址常常只有一行文字（"XX 路口进来第三家"），没有坐标 —— 于是司机拿到单
    只能靠打电话问路。而**知道坐标的人恰恰是到过现场的司机**：他到了、定位准了，
    这个坐标就是免费的、一次性的正确答案。

    以前这个知识**没有任何地方可以放**：订单的 `address_lat/lng` 只有下单人能写
    （`PATCH /orders/{id}` 不带这两个字段的独立入口），司机的 App 里也没有入口。
    结果同一个地方被问一百遍，每个司机各问一次。

    ## 三条设计约束
    1. **全局共享**（用户 2026-09-18 明确要求）："所有导航信息我们都有共同的库，
       方便下次有人比如说他也是相同的位置，那直接拉过来，省的每个人都要手动上传一次。"
       —— 所以这张表**不按人分区**，任何人录入的点所有角色都能查到。
    2. **相近坐标合并**（同一句要求）："有一个要上传的坐标非常相近大概可能只有 1 米的误差，
       那样子的话，就把这个坐标给合并成一个"。判据在 `services/place_service.py`，
       **只有一处实现**（`MERGE_METERS`），谁都不许自己写一遍距离公式。
    3. **删除是"伪装删除"**（`SoftDeleteMixin`，2026-09-19 用户定的规矩）：
       用户原话「还有这些所有功能的删（撤）销操作就是软删啊，他们都是要有的」。
       第一版做成过物理删除（理由写在下边），用户一句话就否了 —— 而且他的底线在
       `SoftDeleteMixin` 的注释里写着「不要删了就搞不回来了」。所以：
       · 列表/合并判据/详情都只认 `is_deleted = False` 的行；
       · `POST /places/{id}/restore` 原样放回来；
       · 删除时**不再**删 `place_user_usage`（那正是软删的好处：谁用过它几次的记录留着，
         恢复之后一切照旧）。
       ⚠️ **`find_place_near` 必须一起过滤**，否则会出现最隐蔽的一种错：
       补录一个刚刚被删掉的坐标时，"合并"进那条谁也看不见的行 —— 用户补了坐标却哪儿都没有。

    ⚠️ `lat/lng` 用 `Numeric(10, 7)`（与 `orders/shipper_locations` 同精度）：
    7 位小数 ≈ 1.1 厘米，1 米的合并判据落在这个精度之内，不会被舍入吃掉。
    """

    __tablename__ = "places"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 地点名（司机/货主给这个位置起的名字，如"老王家仓库"）；允许为空——只有坐标也是有效的
    name: Mapped[str] = mapped_column(String(128), default="")
    detail_address: Mapped[str] = mapped_column(String(512), default="")
    lat: Mapped[Decimal] = mapped_column(Numeric(10, 7), index=True)
    lng: Mapped[Decimal] = mapped_column(Numeric(10, 7), index=True)
    # 这条坐标是怎么来的：driver=司机送达现场补录；dispatcher=派单员录入；shipper=货主录入
    source: Mapped[str] = mapped_column(String(16), default="driver")
    # 被几个人用过（每次"沿用已有坐标"都 +1）：列表按它倒序 —— 常用的排前面
    use_count: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # 首次录入来源订单（可空）：出了问题能顺着查回"是哪个司机在哪一单上标的"
    first_order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlaceUserUsage(Base, TimestampMixin):
    """**谁用过这个共享地点几次** —— 「常点就自动进他自己的地点库」的依据。

    用户 2026-09-18 的要求：
    > 常点的那个共享地点，有人经常点了，它就会自动移到他自己的地点库当中。

    判据是 **同一个人用同一个地点的次数**（不是全库总次数 "use_count"）：
    全库次数只说明"大家都去过这儿"，而你个人把它收进自己的库，
    应该由**你自己**的行为决定 —— 否则一个热闹的地点会涌进所有人的列表。

    阈值只有一处实现：`place_service.AUTO_ADD_AFTER`。
    ⚠️ 这张表的行**不随用户删除而清**（软删用户恢复后，他的常用地点还应该在）。
    """

    __tablename__ = "place_user_usage"
    __table_args__ = (UniqueConstraint("user_id", "place_id", name="uq_place_user_usage"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    place_id: Mapped[int] = mapped_column(ForeignKey("places.id"), index=True)
    use_count: Mapped[int] = mapped_column(Integer, default=1)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: 已经帮他加进「我的地点」了吗（只加一次；加过再点不会重复加）
    auto_added: Mapped[bool] = mapped_column(Boolean, default=False)
