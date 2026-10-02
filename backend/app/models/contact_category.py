from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    pass


class ContactCategory(Base, TimestampMixin):
    """**联系人分类名册**（每个用户管自己的那一份，决定联系人列表左侧那一列的名字与顺序）。

    ## 与地点分类（`PlaceCategory`）是同一套做法
    名册管顺序、字符串管归属（归属那一格是 `shipper_contacts.category` 这个自由文本），
    改名**级联**改那一列，删除时**还有联系人挂着就拒绝** —— 与商品分类/地点分类/开销分类
    一字不差的五条纪律（`services/category_order.py` 里那句「整份顺序的校验四个名册共用一份」
    现在多了一份）。

    ## 为什么不给 `place_categories` 加一个 `kind` 列，而是**另起一张表**
    1. 两张名册**级联的目标不同**：一个改 `shipper_locations.category`、一个改
       `shipper_contacts.category`。合表之后每一次增删改都要先判 `kind`，
       判错一次就是「把货主的联系人分类搬进他的地点库」—— 这是用户看得见的错。
    2. `place_categories` 上有 `uq_place_category_owner_name(shipper_id, name)`：
       合表要把唯一键改成 `(shipper_id, kind, name)`，而 **SQLite 改不了唯一约束**
       （只能整表重建，见迁移 011 里那段"中转表 + DROP"）。为省一张表去重建一张有数据的表，
       风险与收益不成比例。
    3. 在本仓库里商品分类 / 地点分类 / 开销分类 / 模板分类**本来就是四张独立的表**，
       第五张是同一个形状，不是新发明。

    ## 按人分区
    与 `place_categories` 同一个理由：`shipper_contacts.shipper_id` 就是"这个人自己的名册"，
    货主与派单员用**同一套接口、各自的库互不可见**（批发商在本仓库就是货主，没有独立角色）。
    名册必须带 `shipper_id`，否则货主 A 建一个「老客户」，会出现在货主 B 的联系人列表里。

    ⚠️ 名册里没有的分类名**不是错误**（老数据、或别处直接写库）：列表会把它排在名册后面。
    不许因为它不在名册里就把那位联系人藏起来 —— 那是"看不见 ≠ 没有"的老坑（地点侧同一条）。

    ⚠️ 改名**必须级联改** `shipper_contacts.category`（同一事务，见
    `api/v1/contact_categories.py::update_category`），否则联系人会挂着一个已经不存在的分类名。
    """

    __tablename__ = "contact_categories"
    __table_args__ = (UniqueConstraint("shipper_id", "name", name="uq_contact_category_owner_name"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    #: 谁的库（`shipper_contacts.shipper_id` 同一个口径：就是登录用户 id）
    shipper_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    #: 分类名（与 `shipper_contacts.category` 同一个口径：strip 过、≤32 字）
    name: Mapped[str] = mapped_column(String(32), index=True)
    #: 显示顺序：**小的在前**。新建的排到最后（不是 0 —— 排到 0 会抢在第一个前面）
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
