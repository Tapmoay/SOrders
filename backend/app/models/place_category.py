from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    pass


class PlaceCategory(Base, TimestampMixin):
    """**地点分类名册**（每个用户管自己的那一份，决定地址库里左侧分类的顺序）。

    ## 为什么需要一张表，而不是只留 `shipper_locations.category` 这个字符串
    和商品分类（`ProductCategory`）是同一个理由：**名册管顺序**，字符串管归属。
    用户 2026-09-19 明确要「地点库的分类…他们可以自行的添加分类，也可以进行分类的管理…
    **也同样可以调整顺序**」——"顺序"这件事只能存在一个地方，存在字符串里没有地方放。

    ## 与商品分类最大的不同：**按人分区**
    商品分类是**全店一份**（派单员维护，所有货主下单时看到同一列）。
    地点库是**每个人自己那一份**（`shipper_locations.shipper_id` 就是"这个人自己的库"，
    货主和派单员都用同一套接口、各自的库互不可见），所以名册必须带 `shipper_id`：
    否则货主 A 建一个「常送小区」，会出现在货主 B 的地址库里。

    ⚠️ 名册里没有的分类名**不是错误**（老数据、或别处直接写库）：地址库会把它排在
    名册后面。不许因为它不在名册里就把那条地点藏起来 —— 那是"看不见 ≠ 没有"的老坑。

    ⚠️ 改名**必须级联改** `shipper_locations.category`（同一事务，见
    `api/v1/place_categories.py::update_category`），否则地点会挂着一个已经不存在的分类名。
    """

    __tablename__ = "place_categories"
    __table_args__ = (UniqueConstraint("shipper_id", "name", name="uq_place_category_owner_name"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    #: 谁的库（`shipper_locations.shipper_id` 同一个口径：就是登录用户 id）
    shipper_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    #: 分类名（与 `shipper_locations.category` 同一个口径：strip 过、≤32 字）
    name: Mapped[str] = mapped_column(String(32), index=True)
    #: 显示顺序：**小的在前**。新建的排到最后（不是 0 —— 排到 0 会抢在第一个前面）
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
