from datetime import datetime
from typing import TYPE_CHECKING

from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import UserRole

if TYPE_CHECKING:
    from app.models.driver_billing_rule import DriverBillingRule
    from app.models.ledger import Ledger
    from app.models.notification import Notification
    from app.models.operation_log import OperationLog
    from app.models.order import Order
    from app.models.shipper import ShipperAddress, ShipperContact


class User(Base, TimestampMixin):
    """账号。

    `token_version`（2026-09-19 审计补）：**服务端撤销令牌**的唯一凭据。
    令牌里带签发时的版本号，`deps.get_current_user` 每次都拿它和库里的比 ——
    改密码 / 停用 / 删除 / 主动登出时把这一列 +1，那些旧令牌立刻失效。
    没有它的时候：用户丢了手机、或密码泄漏后改了密码，**旧令牌照样能用满 24 小时**
    （"改密码"这个最自然的止损动作在有效期内完全无效）。
    老库由 `schema_bootstrap` 补列、默认 0；老令牌里没有这个 claim 也按 0 处理
    → **升级不会把所有人踢下线**。
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(128), default="")
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    #: 令牌版本（服务端撤销用）。改密码 / 停用 / 删除 / 登出时 +1 →
    #: 已发出的旧令牌在下一次请求就失效（见 `deps.get_current_user`）。
    #: 老库由 `schema_bootstrap` 补列、默认 0；老令牌没有这个 claim 也按 0 处理。
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    #: **上一次会话是怎么结束的**（2026-10-03 E2E 走查 BUG-0006）。
    #: 登录顶号 / 登出 / 改密码 / 停用 / 删除都在 `revoke_tokens_and_sockets` 里写这一列
    #: （与版本号 +1 同一个事务）。没有它的时候，被顶号 / 被停用 / 改了密码 / 令牌过期
    #: 四种原因共用一句「登录已失效」，用户只能瞎猜。
    #: `session_revoked_version` = **撤销那一刻**的 `token_version`，它是「这句话还算不算数」
    #: 的凭据：只有它等于当前 `token_version`，这条 reason 描述的才是最近这一次结束
    #: （对账逻辑见 `deps._session_ended_detail`）。
    session_revoked_reason: Mapped[str] = mapped_column(
        String(64), default="", server_default=""
    )
    session_revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    session_revoked_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    #: 最后一次登录成功的时间（**UTC naive**，`core/business_time.utc_now_naive()`）。
    #: 走查原话：「事后在库里查不到谁顶了谁」——它加上上面两列，让一次顶号留得下痕迹。
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 司机画像（仅司机有意义）：small小车/large大车/trailer挂车
    vehicle_type: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    # 计费方式：salary固定工资/piece按单计费（挂车默认按单，可独立设置）
    billing_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 固定工资司机月薪（仅派单员可见；司机端接口一律隐藏）
    salary: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # 挂着的计费规则模板（v3.36）：设了它就由规则决定怎么算钱，
    # `billing_mode`/`salary` 退化成"没挂规则时的老口径"（存量数据照旧）。
    # ⚠️ 挂载只有一条写路径：`POST /driver-billing-rules/attach`（见该文件的注释）。
    driver_rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("driver_billing_rules.id"), nullable=True, index=True
    )
    # 会员标记：货主中的高级货主（仅对货主有意义）
    is_member: Mapped[bool] = mapped_column(Boolean, default=False)
    # 「他要不要管下游的账」（CHG-0076 / 台账 L-39）：**批发商自己的偏好**，默认开（＝现状）。
    # ⛔ 与上面的 `is_member` 是**两件事**：那个是**身份**（他是批发商还是普通货主，只有派单员能改，
    #    工作台那个「批发商」徽章靠它），这一格是他**自己**在「我的」页拨的开关
    #    （关掉 ⇒ 这本账只显示他欠派单员的钱，核销一起收走）。
    # 本列**只由迁移 026 加**（`app/migrations/026_user_downstream_ledger.py`）——
    # ⛔ `core/schema_bootstrap.py` 里不写（加列是正式变更，两处都写＝同一件事两个来源）。
    downstream_ledger_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # 商品可见范围（v3.43）：`all`（默认，不限制）/ `custom`（只给白名单里的商品）。
    # ⚠️ 默认**必须是 all**：老账号没有配置，如果默认当成"白名单为空 = 什么都看不到"，
    #    上线那一刻所有货主的选品页都会是空的 —— 这种"默认把功能关掉"的迁移是灾难。
    #    所以用它做开关，白名单明细在 `user_product_visibility` 表里。
    product_scope: Mapped[str] = mapped_column(String(16), default="all")
    # 账号分类（2026-10-05 用户要求「账户管理司机管理货主管理批发商管理……在这个位置也加个分类」）：
    # **自由文本**（与 `products.category` 同一个做法，空串 = 未分类），顺序由全局名册表
    # `user_categories` 管（`create_all` 建表；本列由迁移 014 加在已有库上）。
    # ⛔ 不是外键：分类名本来就是给人看的短词，字符串匹配够用；代价是**改名必须级联**。
    category: Mapped[str] = mapped_column(String(32), default="", index=True)

    orders_as_shipper: Mapped[list["Order"]] = relationship(
        back_populates="shipper", foreign_keys="Order.shipper_id"
    )
    orders_as_driver: Mapped[list["Order"]] = relationship(
        back_populates="driver", foreign_keys="Order.driver_id"
    )
    ledgers: Mapped[list["Ledger"]] = relationship(back_populates="shipper")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="recipient")
    operation_logs: Mapped[list["OperationLog"]] = relationship(back_populates="operator")
    addresses: Mapped[list["ShipperAddress"]] = relationship(back_populates="shipper")
    contacts: Mapped[list["ShipperContact"]] = relationship(back_populates="shipper")
    # 挂着的计费规则（只读用；挂载/解挂走 driver-billing-rules/attach）
    driver_rule: Mapped["DriverBillingRule | None"] = relationship(foreign_keys=[driver_rule_id])


def normalize_billing_mode(raw: str | None) -> str | None:
    """把用户/客户端传进来的计费方式**归一成大写**（`PIECE` / `SALARY`）。

    ### 为什么必须归一（这是一个真实发生过的"钱算错"）
    这个字段是自由文本，而它的消费方**各自写了一种判据**：
    `freight_settlement.py` 比 `== "PIECE"`（大小写敏感）、`driver_bills.py` 用 `.upper()`、
    `accounting_service.py` 也用 `.upper()`、安卓端比 `== "PIECE"`。
    于是"库里存了小写 `piece`"这一个事实，在不同页面上会得到**互相矛盾**的结论：
    司机账单里算他是计件，而「司机运费结算」页里看不到他的单；
    派单页判定他是工资制，于是**不显示运费输入框**，这一单的运费永远是空的。

    写入侧收口成一处，是唯一能让上面那些判据同时成立的做法
    （不是把 6 个消费点各改一遍——下次再加一个消费点又会漏）。
    """
    if raw is None:
        return None
    s = raw.strip().upper()
    if not s:
        return None
    # 认不出来的值原样留着（大写）：编一个默认值会把"用户设了一个我们不认识的东西"藏起来
    return s


def resolve_billing_mode(vehicle_type: str | None, billing_mode: str | None) -> str:
    """计费方式解析：显式值优先；挂车默认按单计费，其余默认固定工资。**一律大写。**"""
    normalized = normalize_billing_mode(billing_mode)
    if normalized:
        return normalized
    return "PIECE" if vehicle_type == "trailer" else "SALARY"
