from datetime import datetime

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.phone import MobilePhone, OptionalMobilePhone
from app.core.security import DEFAULT_INITIAL_PASSWORD
from app.models.enums import UserRole
from app.schemas.money import MoneyInput


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    phone: str
    #: **拿来显示**的号码（None = 别给拨号入口）。口径唯一处 = services/soft_delete.dialable_phone：
    #: 活号原样、软删去后缀、**活着却带后缀（恢复时撞号）→ None**（那个号已经是别人的了）。
    #: ⛔ 为什么不直接把 [phone] 去后缀：《新增/编辑账号》表单拿 [phone] 回显（draftPhone），
    #:    去掉后缀再存回去 = 把一个已经释放给别人的号码写回这个账号（撞唯一约束 / 抢号）。
    #:    2026-10-03 真机抓到的 P1：账户管理 / 司机管理把 13923111638_del62 原样端给了用户。
    phone_display: str | None = None
    #: 这一行**现在**在不在回收站里（= 号码/用户名带 `_del{id}` 后缀 **且** `is_active` 为 False；
    #: 实现 = api/v1/users.py::_in_recycle_bin）。界面据此决定给「恢复」还是给「启用」。
    #: ⚠️ 两个反例都得排除：**停用**的账号号码是好的（不是删除）、**恢复时撞号**的账号人已经回来
    #:    了（只是号码归了别人 —— 那件事由 [phone_display] 的 None 表达）。
    is_deleted: bool = False
    full_name: str
    role: UserRole
    is_active: bool
    is_member: bool = False
    #: 「他要不要管下游的账」（CHG-0076 / 台账 L-39）：**批发商自己的偏好**，默认开（老账号＝现状）。
    #: ⛔ 与 [is_member] 不是一回事 —— 那个是**身份**（工作台徽章靠它），这个是他在「我的」页
    #:    拨的开关；关掉只影响这本账显示什么、以及能不能核销，**一分钱都不动**。
    downstream_ledger_enabled: bool = True
    #: 账号分类（空串 = 未分类）。名册与顺序在 `user_categories` 表里，这一格只存名字。
    #: 账户 / 司机 / 货主 / 批发商四个名册页左侧那一列，就是按这一格分组的（2026-10-05）。
    category: str = ""
    vehicle_type: str | None = None
    billing_mode: str | None = None
    salary: Decimal | None = None
    # 挂着的计费规则（v3.36）：司机管理页要能一眼看出"他是按哪份规则算钱的"。
    # `pay_summary` 由 `driver_pay` 生成（规则说什么，或没挂规则时的老口径），
    # **界面不许自己拼这句话**——拼了就会和账单口径不一致。
    driver_rule_id: int | None = None
    driver_rule_name: str = ""
    pay_summary: str = ""
    # 「他按不按单拿钱」——决定派单端**要不要给这个司机显示运费框**。
    # ⛔ 与账单同一个判据（`driver_pay.snapshot_mode`，规则优先），客户端**不许**自己按
    #    车型/`billing_mode` 猜：猜错的表现是运费框不显示 → 运费为空 → 提成型的规则算成 0
    #    → 送达时 `pay.total <= 0` **连账单都不生成**（2026-09-19 全项目报告 P0-3）。
    #    None = 非司机（这个字段对他没有意义）。
    pays_per_order: bool | None = None
    # 「他**现在有没有按单的账要看**」—— 决定司机端「我的账单」那一格显不显示（2026-09-21 真机抓到）。
    # ⛔ 与上面那个是**两件事**：`pays_per_order` 面向**以后派的单**（派单端要它决定运费框），
    #    这一个面向**已经发生的钱**（当前按单 **或** 账上已有按单账单）。
    #    判据在 `services/driver_pay.has_per_order_earnings`（钱的唯一口径处），客户端不许自己算：
    #    只按 `pays_per_order` 判的后果是——被改成固定工资的司机，他那笔改规则之前攒下的
    #    按单钱（prod 实测 ¥2024）在 App 里**再也看不到**（订单卡片已经不画任何金额了）。
    #    None = 非司机或这次没查（客户端按 false 处理）。
    has_per_order_earnings: bool | None = None
    # 「他有没有固定工资（月薪）要算」—— 司机端「我的账本」那一格显不显示（2026-10-15 CHG-0127）。
    # ⛔ 这是**第三个**判据，不是上面两个的补充：上面两个说的是**按单的钱**，这一个说的是**月薪**。
    #    用户 2026-10-15 推翻了 2026-09-20 那条旧裁定（「拿固定工资的司机不需要「我的账本」」）：
    #    固定工资司机也要有一本账 ——「这个我的账本就是统计，他的工资的」。
    #    判据在 `services/driver_pay.monthly_salary_of`（工资的**唯一口径处**：挂了规则问规则、
    #    没挂规则回退老口径），客户端**不许**自己看 `salary` 猜 —— 那个字段对非派单员还被抹成 None
    #    （「工资仅派单员可见」是既有硬约定，这里只出**有没有**，不出多少钱）。
    #    None = 非司机或这次没查（客户端按 false 处理）。
    has_salary: bool | None = None
    created_at: datetime


class UserCreate(MoneyInput):
    # 派单员建号：账号=手机号，必须 11 位（1 开头）——客户端已限制，服务端兜底。
    # 规则本身在 `app/core/phone.py`（原来这里写着 `pattern=r"^1\d{10}$"`，是**第二条**同义实现，
    # 已收拢到唯一实现处；`max_length=11` 与规则同宽，只是给"文本上界"审计一个可读的界）。
    phone: MobilePhone = Field(..., max_length=11)
    username: str | None = Field(None, min_length=3, max_length=32)
    # 初始密码：**不给就用规定的默认值**（用户 2026-10-11：「我们的所有账号初始密码默认是 123321，
    # 这是规定死的……我叫它创建一个账号，它直接帮我创建好、不要问我密码是什么」，见 CHG-0118）。
    # 原来这里是 `Field(...)`（必填）——那等于逼建号的人（或 AI）先去问一个密码，而这条规定
    # 本来就是"不用问"。语义上仍与 UserUpdate 一致：**不传 = 用默认**，传了就按传的。
    # ⛔ 默认值只有这一处（`core/security.py::DEFAULT_INITIAL_PASSWORD`）；
    # ⛔ 密码永不进返回体（`UserOut` 里没有这个字段）与操作日志（`users.py::create_user` 的 payload）。
    password: str = Field(DEFAULT_INITIAL_PASSWORD, min_length=6, max_length=128)
    full_name: str = Field(default="", max_length=128)
    role: UserRole
    is_member: bool = False
    #: 账号分类（空串 = 未分类）。带了个名册里没有的名字 → 后端顺手补进名册（排到最后），
    #: 不让"先建分类再建号"变成一道手续。
    category: str = Field("", max_length=32)
    vehicle_type: str | None = Field(None, max_length=16)
    billing_mode: str | None = Field(None, max_length=16)
    salary: Decimal | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _default_username(self) -> "UserCreate":
        if not self.username:
            object.__setattr__(self, "username", self.phone)
        return self


class UserUpdate(MoneyInput):
    # 改账号手机号：与建号**同一条规则**（`app/core/phone.py`），原先只有 min/max_length，
    # 也就是说建号必须 11 位、改号却可以改成任意 5~32 个字符 —— 改完就登不进来了。
    phone: OptionalMobilePhone = Field(None, max_length=11)
    password: str | None = Field(None, min_length=6, max_length=128)
    full_name: str | None = Field(None, max_length=128)
    role: UserRole | None = None
    is_active: bool | None = None
    is_member: bool | None = None
    #: 账号分类（空串 = 未分类）。**不传 = 不动**；传了名册里没有的名字 → 自动补进名册。
    #: ⛔ 仅派单员可改（司机自己改 = 自己挑一个分组）。
    category: str | None = Field(None, max_length=32)
    vehicle_type: str | None = Field(None, max_length=16)
    billing_mode: str | None = Field(None, max_length=16)
    salary: Decimal | None = Field(None, ge=0)


class DownstreamLedgerIn(BaseModel):
    """「我的 → 管下游的账」那颗开关的入参（CHG-0076 / 台账 L-39）。

    ⚠️ 只有**他本人**能改这一格（`PATCH /users/me/downstream-ledger`）——
    派单员不代设（口径 ④），所以这里没有 user_id、也没有别的字段。
    """

    #: true = 管下游的账（显示别人欠他的钱、给谁什么价）；false = 这本账只显示他欠派单员的钱
    enabled: bool
