from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class UnitConversion(Base, TimestampMixin, SoftDeleteMixin):
    """**单位换算**：一个单位等于另一个单位多少（一车 = 8 方）。

    ## 用户要的是什么（2026-09-24 原话）
    > 「我们再加一个功能叫做**自动换算单位**。比如说我们有个单位叫一车，但是这一车如果是去拉沙子的话，
    >  大概是八方，所以就说**一车是等于 8 方**。自动的换算单位也可以自动的选择匹配单位 ——
    >  我们的**货主和派单员**，他可以自动的设置单位，比如说一车等于 8 方。…
    >  然后我们再计算的时候或者是算账的时候会自动启动换算的功能。比如说我下的十车，
    >  会有 **2 个数据**：第一个是 10 车，第 2 个则是 80 方。」

    所以兑换率是**量的等价**，不是价：一行"10 车"在界面上要同时说出"≈ 80 方"。
    ⛔ **钱一个字节都不跟着换算**（单价、行金额、账本、报表全按原来的单位算）——
    "按方计价"是另一件事（会同时动价格口径与成本），需要单独拍板。

    ## 三条设计约束
    1. **全库共用一张表**（不按人分区）：`1 车 = 8 方` 是这车沙子的事实，不是某个人偏好；
       而且"货主下的单"与"派单员看的同一张单"必须显示同一个换算 —— 按人分区会让同一单
       在两个角色那儿出现两个数。谁能改由 `api/v1/unit_conversions.py` 的角色门槛定。
    2. **一个单位只能换算到一处**（`from_unit` 唯一，活着的行里）：`1 车 = 8 方` 与
       `1 车 = 50 袋` 同时存在时，界面上"10 车 ≈ ?"就没有唯一答案。
       判据在 `services/unit_conversion.py`，**只有一处实现**。
    3. **只做一跳，不做链式**：`一车=8方` + `1方=50袋` **不**推 `一车=400袋`
       （链式要防环、要选路径、还要说清"这个数是推出来的"）。第一版明确不做，写在这里，
       免得下一个人以为漏了。

    ## 为什么换算率的精度是 (14, 4)
    单位换算常常是"一车 8 方"这种整数，也会有"1 斤 = 0.5 公斤"这种小数。
    4 位小数足够表达常见的换算（0.0001 的误差在"再来 10 万倍"之后才到 10），
    而 14 位整数部分放得下任何现实数量级。**存 Decimal 不存 float**：换算结果要参与显示，
    浮点误差会让"10 车"永远显示成 `79.99999999999999`。

    ## 删除是「伪装删除」（用户 2026-09-20 定的硬规矩）
    `SoftDeleteMixin` + `POST /unit-conversions/{id}/restore`。
    ⚠️ 这里**刻意不加** `(from_unit, to_unit)` 的数据库唯一约束：
    约束会把"删掉再建同一条"变成 500（`shipper_contacts` 就被这个坑逼出了 `_del{id}` 后缀那一套）。
    唯一性判据放在 `services/unit_conversion.py` 里，它能**认出被删过的那一条并把它放回来**
    （见 `api/v1/unit_conversions.py::create_conversion`）。
    """

    __tablename__ = "unit_conversions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    #: 源单位（"车"）。最多 16 个字符 —— 单位是短词，`products.unit` 也是 32 以内。
    from_unit: Mapped[str] = mapped_column(String(16), index=True)
    #: 目标单位（"方"）。
    to_unit: Mapped[str] = mapped_column(String(16))
    #: `1 from_unit = factor to_unit`
    factor: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    #: 备注（"沙子按 8 方算"之类，选填）
    remark: Mapped[str] = mapped_column(String(256), default="")
    #: 谁建的（审计用；离开这个账号之后这一行仍然有效）
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
