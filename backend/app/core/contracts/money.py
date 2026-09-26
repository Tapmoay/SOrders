# -*- coding: utf-8 -*-
"""钱的**核心表示**：Money / Currency / Rounding（R4-02 · PricingContract v1 的 Core 侧）。

## 为什么必须有它（指南 §9 / §20）

> 核心拥有：Money / Currency / Rounding / Transaction / Ledger
> 扩展拥有：PricingAlgorithm
> **核心只接受 Money，不能接受某个插件自己的对象。** —— 指南 §20 原话

没有这个类型，上面那句话**没有落点**：扩展返回一个 Decimal、一个 float、一个 dict，
核心都得照单全收，而「钱只有一个口径」就退化成一句口号。

## ⚠️ 它**不是**第二份「钱怎么算」的实现 —— 这条必须说清

本仓库最贵的一条规矩是「**一笔钱只有一个数**」，实现站点在
services/order_money.py、services/driver_pay.py、services/accounting_service.py、
services/order_return.py 等处，由 _check_money_contract.py 钉着。

这一页只定义「**一个金额长什么样**」（类型 + 进位方式），
⛔ **一行业务金额都不算**：它不知道什么叫应收、什么叫欠款、什么叫司机运费。

它给出的 QUANTUM / ROUNDING 必须与仓库里那批既有实现**逐字一致** ——
判据 _tools/qa/_check_extension_contracts.py 会把 services/** 与 api/** 里的字面量抠出来
与本文件对账，不一致当场报红。所以它是**把一条口头约定变成一处定义**，不是新增一处算法。

## 三个不变量（扩展必须遵守；判据核前两条）

1. **金额一律两位小数、ROUND_HALF_UP**
   （⛔ 不是 quantize 的默认 ROUND_HALF_EVEN —— 半分上会差一分钱，
   accounting_service.py 的注释里记着这个坑）；
2. **币种必须配套**：不同币种不许相加减（抛 MoneyError，而不是「默默按数字加」）；
3. 金额一旦构造就**不可变**（frozen）—— 改金额只能造一个新的，⛔ 不许就地改。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

#: 金额的最小单位（分）。全项目一致的两位小数口径。
#: ⛔ 改这一行 = 改全项目「钱长什么样」—— 判据会拿既有的那批实现跟你对账。
QUANTUM = Decimal("0.01")

#: 进位方式。⛔ **不是** quantize() 的默认值（默认 ROUND_HALF_EVEN）。
ROUNDING = ROUND_HALF_UP

#: 默认币种。当前系统只做人民币；多币种是一个**尚未出现第二个实现**的扩展点，
#: 所以这里只留字段，不编造汇率（编了就是「看起来支持多币种」）。
DEFAULT_CURRENCY = "CNY"


class MoneyError(ValueError):
    """钱这件事上说不通时抛的错。

    消息一律是**一句能照着改的中文** —— 后端抛出的中文会被 App 原样显示给用户
    （从 v3.x 起就定下的口径，见 core/validation_errors.py）。
    """


@dataclass(frozen=True)
class Money:
    """一个金额：**不可变**，构造时就归一成两位小数。

        Money(Decimal("1.005"))              -> 1.01 CNY
        Money("8") + Money("0.5")            -> 8.50 CNY
        Money("8") + Money("0.5", "USD")     -> MoneyError（币种不同）
    """

    amount: Decimal
    currency: str = DEFAULT_CURRENCY

    def __post_init__(self) -> None:
        try:
            value = Decimal(self.amount)
        except Exception as exc:  # noqa: BLE001 —— 任何一种「给的不是数」都归到这里
            raise MoneyError("金额必须是数字：" + repr(self.amount)) from exc
        object.__setattr__(self, "amount", value.quantize(QUANTUM, rounding=ROUNDING))
        object.__setattr__(self, "currency", (self.currency or DEFAULT_CURRENCY).strip().upper())

    # ---------------------------------------------------------------- 构造
    @classmethod
    def zero(cls, currency: str = DEFAULT_CURRENCY) -> "Money":
        return cls(Decimal("0"), currency)

    @classmethod
    def of(cls, amount: object, currency: str = DEFAULT_CURRENCY) -> "Money":
        """从任何一种「看起来像钱」的东西造一个：字符串 / int / Decimal 都行，⛔ float 不行。"""
        if isinstance(amount, float):
            raise MoneyError("不要用小数（float）表示金额：二进制浮点在 0.1 上就不精确，请用字符串或 Decimal")
        return cls(amount if isinstance(amount, Decimal) else Decimal(str(amount)), currency)

    # ---------------------------------------------------------------- 校验
    def _same_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise MoneyError(
                "两个金额的币种不同（" + self.currency + " / " + other.currency + "），不能直接相加减"
            )

    # ---------------------------------------------------------------- 运算
    def __add__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            raise MoneyError("金额只能和金额相加，收到的是 " + type(other).__name__)
        self._same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            raise MoneyError("金额只能和金额相减，收到的是 " + type(other).__name__)
        self._same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> "Money":
        return Money(-self.amount, self.currency)

    def times(self, factor: object) -> "Money":
        """乘一个**无量纲**的因子（件数 / 比例）。⛔ 因子不许是另一个金额。"""
        if isinstance(factor, Money):
            raise MoneyError("金额不能乘以金额（那不是一个金额该有的运算）")
        if isinstance(factor, float):
            raise MoneyError("不要用小数（float）乘金额：请用字符串或 Decimal")
        return Money(self.amount * Decimal(str(factor)), self.currency)

    # ---------------------------------------------------------------- 判定
    def is_zero(self) -> bool:
        return self.amount == 0

    def is_negative(self) -> bool:
        return self.amount < 0

    def as_text(self) -> str:
        """给人看的形态（两位小数、不带货币符号）。

        ⛔ 界面上的显示口径仍然是 services/money_text.py 那一处，这一条只是排障用。
        """
        return format(self.amount, "f")

    def __str__(self) -> str:  # pragma: no cover —— 只为排障时好看
        return self.as_text() + " " + self.currency
