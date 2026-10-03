"""车辆台账：车牌 / 车型 / 挂靠司机（货损油费维修按车归属）+ **车辆自身的属性**。

## 车型与车身型式是**两件事**（2026-09-27 用户要的车辆属性）

* `vehicle_type`（小货车 / 大货车 / 挂车）＝ **计费口径**：这辆车按什么算钱。
  它的取值被五处共用（车辆台账 / 司机计费规则 / 运费模板 / 司机应付 / `resolve_billing_mode`），
  其中 `models/user.py::resolve_billing_mode` 的「挂车→按单计费、其余→固定工资」**是钱**。
  ⛔ 本表**不扩它的取值**，一个字都不动。
* `body_type`（箱式车 / 平板车 / 自卸车 / 挂车 / 未设置）＝ **车身型式**：
  它决定**这辆车能填哪些属性**（见 `services/vehicle_attrs.py`）。

用户 2026-09-27 原话：

> 「可以给一辆车**固定一个属性**……在**创建车辆的时候就需要填相应的属性**。
>  **不同的车型会需要填的属性是不同的**……别说有可能是个**平板车**、有可能是一个**自卸车**。」
> 「（车辆属性）**是要算钱的**……主要的是**吨和方**这种即便（计量）单位。」

## 属性列的三条规矩

1. **一列一个事实**：车厢 / 台面 / 车斗的长宽高是**同一个事实的不同叫法**，
   所以是 `cargo_length_m` / `cargo_width_m` / `cargo_height_m` 三列，
   不是九列 —— 拆开之后"这辆车载货区多长"会有三个 Owner。
2. **全部可空、NULL 是"这一项没量过"**，⛔ 不回填老车（替它们猜一个容量就是伪造台账事实）。
3. **存 Numeric 不存 Float**：`load_tons` / `volume_cubic` 是**要参与换算**的两个数
   （「一车 = 多少方 / 多少吨」），浮点会让 8 变成 7.999999999999999
   （与 `unit_conversions.factor` 用 `Numeric(14,4)` 同一条理由）。
   ⚠️ 列宽与迁移 `010_vehicle_attrs` 必须**逐列一致**，否则新库（create_all）与老库（ALTER）会长得不一样。
"""

from decimal import Decimal

from sqlalchemy import Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Vehicle(Base, TimestampMixin):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plate_no: Mapped[str] = mapped_column(String(16), unique=True)
    #: **计费口径**的车型（小货车 / 大货车 / 挂车）。⛔ 与车身型式是两件事，取值不许扩。
    vehicle_type: Mapped[str] = mapped_column(String(16), default="")
    driver_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(default=True)

    # ---------------- 车身型式 + 车辆属性（2026-09-27 · 迁移 010） ----------------
    #
    # 取值与含义的**唯一一份**判据在 `services/vehicle_attrs.py`（纯函数、有单测）：
    # 哪些型式能填哪些列、每项叫什么、范围多少，全在那一张表里。
    # ⛔ 这里只声明列，不写任何 when(型式) 的判断。

    #: 车身型式：box 箱式车 / flat 平板车 / dump 自卸车 / trailer 挂车 / `''` 未设置。
    #: 空串是**正式取值**（老车、以及"还不知道这车是什么型式"），不是"没填"。
    body_type: Mapped[str] = mapped_column(String(16), default="")
    #: 车高（米）
    height_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    #: 车宽（米）
    width_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    #: 净重（吨）
    curb_weight_t: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    #: ⭐ **载重（吨）** —— 参与「一车 = 多少吨」的换算
    load_tons: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    #: ⭐ **容积（方）** —— 参与「一车 = 多少方」的换算；自卸车上它叫「斗容」
    volume_cubic: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    #: 载货区长（米）：箱式车叫车厢长、平板车叫台面长、自卸车叫车斗长
    cargo_length_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    #: 载货区宽（米）
    cargo_width_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    #: 载货区高（米）——**平板车没有这一项**（需求方给的清单里就没有"台面高"）
    cargo_height_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    #: 轴数（个，整数）——只有挂车有
    axle_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: 分类（2026-10-05 用户要求「车辆管理……在这个位置也加个分类」）：自由文本，
    #: 空串 = 未分类，顺序由全局名册表 `vehicle_categories` 管（迁移 014 加在已有库上）。
    #: ⚠️ 与 `vehicle_type`（车型，计费口径）、`body_type`（车身型式）是**三件事**：
    #: 分类只用于"派单员怎么把车队分组看"，⛔ 不许参与任何计费 / 匹配判断。
    category: Mapped[str] = mapped_column(String(32), default="", index=True)
