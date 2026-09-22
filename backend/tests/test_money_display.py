"""金额**显示**口径：末尾多余的 0 去掉（`56.70 → 56.7`、`87.00 → 87`），有效位一位不少（`56.77`）。

用户 2026-09-22 原话：「把所有的那个关于金钱的那个显示…**有零的全省**…如果是 56.7 啊，
就直接这样子，不要 56.70…包括 87…不要写 87.00 了…但是如果账单是 **56.77** 的话…
**是必须要有的，它不能直接把七给约掉了**」。

## 为什么这个测试必须存在

同一条规则管三端：安卓 `util/Money.kt::formatMoney`、H5 `utils/formatMoney.ts::formatMoney2`、
后端 `app/services/money_text.py`。而"显示"与"值"只差几个字符 —— 混一次的后果都是**不报错的**：

- 拿显示口径去填**可编辑**的价框 → 用户没改价、价却真的变了（`12.3456 → 12.35`，2026-09-21 踩过）；
- 拿显示口径去当**判据** → 收款页那个数永远与后端 `Decimal` 对不上，**多行/多单时永久收不了款**（P0-4）。

所以两侧都要钉：① 显示侧去零；② 值侧仍是一位不动的两位小数。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.money_text import money_text
from app.services.order_money import q2


# ---------------------------------------------------------------- ① 显示侧：去尾零

def test_用户给的三个例子():
    assert money_text("56.70") == "56.7"
    assert money_text("87.00") == "87"
    # ⛔ 这一条就是"去零"与"约掉"的分界：末尾不是 0 的位，一位都不许少
    assert money_text("56.77") == "56.77"


def test_只动末尾的零():
    assert money_text(Decimal("10.0000")) == "10"
    assert money_text(Decimal("0.50")) == "0.5"
    assert money_text(Decimal("0.00")) == "0"
    assert money_text(Decimal("3.25")) == "3.25"
    assert money_text(Decimal("3190.68")) == "3190.68"
    # 后端单价列是 Numeric(14,4)：显示只留两位（这是"到分为止"，**不是**精度口径）
    assert money_text("12.3456") == "12.35"
    assert money_text("12.5000") == "12.5"


def test_进位与全项目那一处完全一样_半分为单位():
    # 5 厘 → 1 分（HALF_UP，不是银行家舍入）；4 厘 → 0
    assert money_text(Decimal("0.005")) == "0.01"
    assert money_text(Decimal("0.004")) == "0"


def test_负零不是钱():
    # `-0.001` 若只做去零会印成 `-0`，界面上就是「¥-0」
    assert money_text(Decimal("-0.001")) == "0"
    assert money_text(Decimal("-5.50")) == "-5.5"


def test_空值给零_坏值要抛():
    assert money_text(None) == "0"
    assert money_text("") == "0"
    # 静默印成 0 会让"钱算错"看起来像"这笔是零" —— 宁可当场炸
    with pytest.raises(Exception):
        money_text("abc")


# ---------------------------------------------------------------- ② 值侧：一位不动

def test_值侧仍然是两位小数_不许被显示口径污染():
    """`q2` 是**值**（判据/出参/入库），它必须一直是两位小数。

    这条与上面那组是一对：`money_text` 化的是"给人看的字"，`q2` 化的是"要参与比较的数"。
    谁把 `q2` 改成去尾零，收款页与账本就对不上了（P0-4 那把收款卡死的原型）。
    """
    assert str(q2(Decimal("87"))) == "87.00"
    assert str(q2(Decimal("56.7"))) == "56.70"
    assert str(q2(Decimal("12.3456"))) == "12.35"
    # 显示口径是它的**下游**：同一个数，两条路各得其所
    assert money_text(q2(Decimal("87"))) == "87"


def test_供应商出参那三个数仍是两位小数():
    """`suppliers._money` 是**接口出参**（值是钱），不是给人看的那句话。

    `backend/tests/test_supplier_payables.py` 逐条钉着 `"1200.50"` —— 这里再钉一次边界，
    免得以后有人"顺手统一口径"把出参也去零（客户端还会再过一次自己的显示口径）。
    """
    from app.api.v1.suppliers import _money

    assert _money(Decimal("1200.50")) == "1200.50"
    assert _money(Decimal("87")) == "87.00"
