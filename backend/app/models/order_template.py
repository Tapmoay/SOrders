"""预订单（订单模板）——「预设好的订单，参数没变直接下单」。

## 用户 2026-09-22 原话
> 「支持 AI 去**预选**……每次下单都要选商品选数量，可以让 AI 去**直接创建对应的商品和对应的数量**，
> 方便直接下单；**甚至可以让 AI 直接去创建预定单** —— 就是**预设好的订单**，这个**参数没有变**，
> **直接下单就可以了**。所以其实我们**还可以再增加一个叫做「预定单」界面**，专门去管理预设的订单。」

## 它是什么（别再改这三条）
1. **一张预设单 = 一行记录**（不是"提前建好的订单"）。它**不占订单号、不进状态机、不动库存、
   不进账本** —— 真下单时走的是已有的 `POST /orders`，与手工下单**同一条路**。
   为什么不做成"状态叫草稿的订单"：那会把订单状态机、回收站、账本口径全部染上一种新状态，
   而它要的只是"把常用的那几项记住"。
2. **`lines` 只存"哪几样、各多少"**（`product_id` + `qty`）。⛔ **不存单价**：
   价格会变，预设一个旧价就会在几个月后**按旧价生成订单**，而界面上完全看不出来。
   金额一律在下单那一刻按商品价 / 批发商专属价算 —— 与手工下单同一处口径。
   ⚠️ 行里仍然存了一份 `name` / `unit` **快照**：预设单列表要在**不发 N 个请求**的前提下
   把行显示出来，而商品后来被改名/下架时，用户得看得见"我当时选的是哪一个"。
3. **`freight_fee` 可以为空**（`null` = 下单时按运费规则/手填）：用户点名要预设运费，
   但不是每张预设单都该锁死运费 —— 锁死之后运价调整了，预设单会一直按老价下单。
   空与"0 元"是**两件事**：`null` 是"没预设"，`0` 是"就是免运费"。

## 删除
走 `SoftDeleteMixin`（用户定的硬规矩：**删除一律软删 + 有恢复路径**）：
`DELETE /order-templates/{id}` 把 `name` 改写成 `{name}_del{id}` 释放名字，
`POST /order-templates/{id}/restore` 放回来（名字被占用时保留现在这个名字）。
"""
from decimal import Decimal

from sqlalchemy import JSON, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class OrderTemplate(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "order_templates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    #: 预设单名（列表上那一行）。**不唯一**：同名的两张预设单是合法的
    #: （"永盛食品周一单"改一改就是"永盛食品周四单"），所以没有唯一索引，
    #: 删除时也就不需要靠改名释放名字 —— 但 `soft_delete.del_suffix` 那一套照做，
    #: 因为它同时是"这行进过回收站"的**可见痕迹**（与全项目其余软删保持同形）。
    name: Mapped[str] = mapped_column(String(64), index=True)

    #: 货主（`users.id`）。**可空** = 下单时再选（有些预设单是"按商品备货"，货主每单不同）。
    #: 没有外键：与 `orders.arrears_unit_id` / `customers.arrears_unit_id` 同一套做法
    #: （软删的表用裸编号 + 自己校验，避免级联把历史改样）。
    shipper_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    origin_address: Mapped[str] = mapped_column(String(256), default="")
    address: Mapped[str] = mapped_column(String(256), default="")
    receiver_name: Mapped[str] = mapped_column(String(64), default="")
    receiver_phone: Mapped[str] = mapped_column(String(20), default="")

    #: 预设运费。`null` = 不预设（下单时按规则算 / 手填）；`0` = 免运费（是两件事，见文件头）。
    freight_fee: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    remark: Mapped[str] = mapped_column(String(256), default="")

    #: 预设的商品行：`[{"product_id": 3, "name": "红富士苹果", "unit": "件", "qty": 6}, …]`。
    #: ⚠️ JSON 列必须容忍 `None`（老库/裸 SQL 会把它写成 NULL），出参侧统一归一到 `[]` ——
    #:    这是本项目栽过的那一类（`default_factory=list` 只兜字段缺失、不兜 None）。
    lines: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)
