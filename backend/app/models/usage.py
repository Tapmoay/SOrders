from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class UsageCounter(Base, TimestampMixin):
    """**某人用过某个东西几次** —— 「常用的排前面」的**唯一依据**。

    ## 用户 2026-09-22 定的规则（原话）
    > 我们那个**隐性规则**，它是**优先级第一**的，它的规则是**大于基础排序**的……
    > 新建的在最前面**只有第一天的时候有效**，第二天的时候它就会被优先级第一的规则给覆盖……
    > **技术是按人来搞**……看请求吧，他请求要拉哪个列表，有些是拉线路的、有些是拉地点的、
    > 有些是拉那些人的……**所有的列表，包括列表的抓取以及列表的排序**，全按照我们这样的规则进行。

    于是所有"挑东西的列表"的排序是：
    **① 常用度降序（本表）→ ② 先创建的在前（`id` 升序）**，
    而"看记录的列表"（订单/账本/消息/审计/流水）**不适用** —— 那些必须最新在前。

    ## 这张表是从 `place_user_usage` 泛化来的（不是新发明一套）
    地点那套（`place_user_usage`）形状是对的：**按 (人, 东西) 计数**、
    **计数由数据库自增**、带 `last_used_at`。它唯一的问题是**只装得下地点**（列名写死 `place_id`），
    而规则要求联系人 / 线路 / 地点 / 商品 / 货主 / 批发商 / 司机 / 客户 / 挂靠单位 / 车辆 /
    运费模板 / 计费规则 / 价格规则**都按同一套排**。所以：

    - 本表 = 那张表的通用版：`(user_id, kind, target_id)` + 唯一键；
    - 地点原有的"常用就自动进我的地点库"语义**原样带过来**（[auto_added]，见下）；
    - 旧表 `place_user_usage` 的数据由 `core/schema_bootstrap.py` **搬进来**（kind = `place`），
      搬完旧表保留为备份、**不再读写** —— ⛔ 别两边各写一份（同一个动作记两处必然对不上）。

    ## 三条不能改的约束
    1. **按人计数**，不是全库：全库次数说的是"大家都用过"，用它排序会把热闹的东西顶到所有人的列表前面
       （地点那一轮已经踩过，见 `place_service.note_place_use` 的注释）。
    2. ⛔ **计数必须由数据库自增**（`UPDATE … SET use_count = use_count + 1`），
       **不许** `row.use_count = (row.use_count or 0) + 1`（2026-09-19 审计，与库存同一个形状的
       lost update：两部手机同时点，后写的把前一次的 +1 盖掉）。唯一实现在 `usage_service.record_usage`。
    3. **`kind` 的取值只有一处**（`usage_service` 里的 `KIND_*` 常量）：列表端点排序时用的 `kind`
       必须与"记一次"时用的**完全一致**，否则计数记了、列表却按另一个 kind 查 → 表现为"我点了一百次，
       它就是不往前"（不报错、不崩溃）。
    """

    __tablename__ = "usage_counters"
    __table_args__ = (UniqueConstraint("user_id", "kind", "target_id", name="uq_usage_counter"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    #: 哪一类东西（`usage_service.KIND_*`）：联系人 / 线路 / 地点 / 商品 / 人 / 客户…
    kind: Mapped[str] = mapped_column(String(24), index=True)
    #: 那一类东西的主键（**不做外键**：一张表装十几类，外键指不了十几个表；
    #: 行被删掉时留着的孤儿计数无害 —— 排序只在 id 命中时才用得上它）
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    use_count: Mapped[int] = mapped_column(Integer, default=1)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: **地点专属**：已经帮他收进「我的地点」了吗（只加一次）。别的 kind 恒 False。
    #: ⚠️ 它留在这张通用表里是有意的：地点的"常用就自动入库"与计数是**同一个动作的两面**，
    #: 拆到两张表就等于同一个动作写两处（那是这个仓库里反复出事的那种形状）。
    auto_added: Mapped[bool] = mapped_column(Boolean, default=False)
