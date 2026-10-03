from typing import TYPE_CHECKING

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    pass


class VehicleCategory(Base, TimestampMixin):
    """**车辆分类名册**（派单员维护，决定车辆管理页左侧那一列的顺序）。

    与 `UserCategory` / `ProductCategory` 同一套：名册只存 `name + sort_order`，
    车辆用 `vehicles.category` 这个字符串归属于某一类（空串 = 未分类），
    改名要级联、建车时带了名册里没有的分类名就自动补进名册、删除时还有车挂着就拒绝。

    ⚠️ 与 `vehicles.vehicle_type`（车型：小货车/大货车/挂车，**计费口径**）和
    `vehicles.body_type`（车身型式）是**三件不同的事**：那两个是运输属性，会影响
    计费与匹配；分类只是"派单员怎么把车队分组看"，⛔ 不许拿它参与任何计费/匹配判断。
    """

    __tablename__ = "vehicle_categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
