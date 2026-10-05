"""022_shipper_status_hold：给 orders 加 shipper_status_hold（货主看到的"最后状态"，仅冻结用）。

### 为什么加它（CHG-0039，用户 2026-10-05 要求）

用户要的动作：派单员可以把一个司机手里**某一个货主**的货退回来、重新派给别人/别的车
（「派单员可以将某一个货主调整为一个货主……这些货物先送这个货主的」），退回之后
「原来的那个货主的货物就会重新回到派单池」。

⛔ 但货主那一侧**必须完全无感**（用户原话，逐字）：「这个操作货主端是不会显示的 ——
货主端仍然会显示状态为已派单或者说司机已接单；订单的状态会默默发生改变，
不会有任何的消息提醒……货主也不需要知道」。

### 为什么是「真实状态退回 + 冻结货主可见状态」这一条路

退回池子之后，这张单要能被**再派一次**，所以真实状态必须真的回到 `PENDING_DISPATCH`：
池子列表、待派计数（`/orders/pending-dispatch-count`）、批量派单、`assign_driver` 的状态门
（`if order.status != OrderStatus.PENDING_DISPATCH: raise ValueError("仅「待派单」状态可派单")`）
全部天然复用，不需要在任何一个入口放宽判断，也不会出现"派单员看到的是假状态"。
货主那一侧靠这一列冻结：出参时只对货主覆写（`services/order_response.py` 的货主分支），
于是货主看到的还是他被派单时的那一档（DISPATCHED / ACCEPTED）。

### 三条设计选择

1. **可空、无默认值、不回填**：NULL = 这张单没有冻结，一切以真实状态为准。
   ⛔ 不回填、⛔ 不设默认 —— 回填成 `status` 等于宣称"所有单都被冻结过"，
   那会让这一列从"一次静默动作的痕迹"变成"第二份状态副本"（两份状态必然对不上，
   与 009～021 同一条纪律：宁可空着）。
2. **类型就是那六档的枚举**（与 `orders.status` 同一个 `OrderStatus`）：它存的一定是
   某一个真实状态值，用字符串列就会让 `'accepted'` / `'ACCEPTED'` 这种脏值写进来。
   缺失档位由 `core/schema_bootstrap.py::enum_repair_ddl` 在启动时按模型补齐（那才是唯一入口）。
3. **不加索引**：这一列的读法只有两种 —— "出参时读这一行的值"（按主键，已在该行上）
   和"货主查自己那一档"（`api/v1/orders_query.py`，本就有 `shipper_id` 与 `status` 上的索引），
   没有任何按它单独筛选的高频查询。

### 何时被清空（解冻）

这张单重新派出去时，`services/order_flow.py::assign_driver` 的 CAS 把这一列一起写成 NULL
（同一条 UPDATE）：新司机上任之后，货主看到的状态就该跟着新事实走了。

### 两个方言（本机 SQLite、生产 MySQL）

这一列在两边的**类型名不一样**，所以 DDL 按方言分支（先例：`016_session_end_reason.py::_int_type`、
`011_contact_phone_optional.py`、`005_ai_call_daily.py`）：

- **SQLite（本机开发库 `backend/sorders.db`）没有 `ENUM` 类型**：`create_all` 按模型建出来的
  `orders.status` 就是 `VARCHAR(16)`（枚举里最长那个名字的长度），所以这里也用 `VARCHAR(16) NULL`。
  ⛔ 不能写成 `ENUM(...)` —— SQLite 直接语法报错，迁移跑不过去，后端就起不来
  （`app/main.py::assert_schema_ready` 会因为"仓库里有版本 22、库里没有"拒绝启动）。
- **MySQL 走真正的 `ENUM(...)`**：取值清单从 `models/enums.py::OrderStatus` 现算，
  与 `orders.status` 同型；将来加一档状态时由 `core/schema_bootstrap.py::enum_repair_ddl`
  在启动时把缺的值 MODIFY 进来（那条自愈只在 MySQL 上跑，SQLite 不需要）。

### 可重跑

`migrations/README.md` 硬要求：MySQL 的 DDL 隐式提交，一条迁移可能改了一半才失败。
这里先判表在不在、再判列在不在，重复跑是空操作。
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 22
NAME = "shipper_status_hold"
DESCRIPTION = (
    "orders 加 shipper_status_hold（ENUM 六档可空）：静默退回派单池时冻结货主可见状态；"
    "NULL = 没冻结、以真实状态为准，⛔ 不回填老数据、⛔ 不设默认值"
)

TABLE = "orders"
COLUMN = "shipper_status_hold"


def _enum_type(engine: Engine) -> str:
    """这一列在两种方言下的类型名（见 docstring「两个方言」）。

    ⛔ 六档取值**不在这里手写第二份**：从模型那张枚举表现算（`models/enums.py::OrderStatus`）——
    手写一份的后果是将来加一档状态时这里静默少一档，而 ENUM 缺值在 MySQL 上是**写入直接报错**
    （不是"存成别的值"）。这与 `core/schema_bootstrap.py::enum_repair_ddl` 同一条纪律：
    取值只有一个来源。
    """
    if engine.dialect.name == "sqlite":
        # SQLite 认 VARCHAR（就是 create_all 给 `orders.status` 用的那个类型），没有 ENUM。
        return "VARCHAR(16)"
    from app.models.enums import OrderStatus

    values = ", ".join(f"'{s.value}'" for s in OrderStatus)
    return f"ENUM({values})"


def upgrade(engine: Engine) -> None:
    insp = inspect(engine)
    if TABLE not in insp.get_table_names():
        # 全新库由 create_all 按模型建表（`Order.shipper_status_hold` 已经在模型里），这里没什么可做的。
        return
    if COLUMN in {c["name"] for c in insp.get_columns(TABLE)}:
        return
    # DDL 的类型名按方言取（六档取值只有 `models/enums.py::OrderStatus` 一个来源，见 `_enum_type`）。
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} " + _enum_type(engine) + " NULL"))
