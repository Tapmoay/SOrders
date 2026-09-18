"""拆单的件数分配（`order_flow.split_order` 的算法部分）。

### 为什么这条值得单测
拆单的**比例**是用户唯一能看见的东西，件数是系统算的。算错了用户看不见，而它会一路
带进金额、库存流水和账本。以前的算法是"每份各自四舍五入"，误差会累加：
3 件拆 2 单变成 4 件、100 件拆 3 单变成 99 件、1 件拆 2 单变成 2 件。
这里把算法本身的判据钉住：**每个商品行的合计恒等于原数量**。
"""

from __future__ import annotations

import pytest

from app.services.order_flow import allocate_split_quantities


@pytest.mark.parametrize(
    "qty,parts,expect",
    [
        (3, [1, 1], [2, 1]),          # 旧算法：2 + 2 = 4 件（凭空多一件）
        (100, [1, 1, 1], [34, 33, 33]),  # 旧算法：33 + 33 + 33 = 99 件（少一件）
        (1, [1, 1], [1, 0]),          # 旧算法：1 + 1 = 2 件（一件货变两件）
        (10, [1, 1], [5, 5]),
        (10, [3, 1], [8, 2]),
        (7, [1, 1, 1], [3, 2, 2]),
        (5, [2, 3], [2, 3]),
        (2, [1, 1, 1, 1], [1, 1, 0, 0]),  # 份数比件数多：前几单各 1 件，其余 0
    ],
)
def test_sum_always_equals_original(qty: int, parts: list[int], expect: list[int]) -> None:
    got = allocate_split_quantities(qty, parts)
    assert got == expect
    assert sum(got) == qty, f"{qty} 件拆 {parts} 得到 {got}，合计 {sum(got)}"


def test_never_creates_more_units_than_original() -> None:
    """穷举一批组合：合计必须恒等于原数量，且没有负数。"""
    for qty in range(1, 60):
        for a in range(1, 6):
            for b in range(1, 6):
                got = allocate_split_quantities(qty, [a, b])
                assert sum(got) == qty, f"{qty} / [{a},{b}] → {got}"
                assert all(x >= 0 for x in got)


def test_proportional_is_respected_when_possible() -> None:
    # 比例 3:1 分 100 件 → 75 / 25
    assert allocate_split_quantities(100, [3, 1]) == [75, 25]


def test_zero_or_negative_parts_are_rejected() -> None:
    with pytest.raises(ValueError):
        allocate_split_quantities(10, [0, 0])
    with pytest.raises(ValueError):
        allocate_split_quantities(10, [1, -1])
    with pytest.raises(ValueError):
        allocate_split_quantities(10, [1])
