"""手工记账的金额下界（2026-09-24 第 26 轮 10 区 F1）。

## 缺陷长什么样
`LedgerCreate.quantity` 一直有 `ge=1`，而 `unit_price` / `total` **什么界都没有**。
旧 H5 的手工记账表单里单价框是 `type="number"`（同表单的数量用的是 `type="digit"`，
输不出负号），提交前只判 `Number.isFinite`、不判负 → 「单价 10 × 数量 2 / 总额 −999999」
这一行能直接进库，然后被货主账**直接累加**、进导出，还写一条 `LEDGER_CREATE` 审计。

AI 那一侧早就拒负数（`AiWriteArgs.parseMoney`：`v.signum() < 0` → 一句中文），
所以缺口只在**绕开 App 的客户端**上 —— 而那正是 H5 的形状。服务端是唯一的兜底。
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from tests.conftest import auth_headers


def _body(shipper_id: int, **over: object) -> dict:
    body: dict = {
        "shipper_id": shipper_id,
        "entry_date": "2026-09-24",
        "product_name": "金额下界探针",
        "quantity": 2,
        "unit_price": "10.00",
        "note": "第 26 轮 10 区 F1",
    }
    body.update(over)
    return body


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_手工记账的单价与总额不许是负数(
    client: TestClient, users: dict, token_dispatcher: str
) -> None:
    """负单价 / 负总额一律 422，**一行都不许落库**（负额会污染货主账与导出）。"""
    for field, value in (("unit_price", "-10.00"), ("total", "-999999")):
        r = client.post(
            "/api/v1/ledger/entries",
            json=_body(users["shipper"].id, **{field: value}),
            headers=auth_headers(token_dispatcher),
        )
        assert r.status_code == 422, f"{field}={value} 应当被拒，实际 {r.status_code}：{r.text}"

    # 反向：合法的正数照旧能记（别把闸门做成"什么都拦"）
    ok = client.post(
        "/api/v1/ledger/entries",
        json=_body(users["shipper"].id, total="20.00"),
        headers=auth_headers(token_dispatcher),
    )
    assert ok.status_code in (200, 201), ok.text
    # 0 也允许（`total=0` 是"这一单没收钱"的合法写法；只有**负**才是错的）
    zero = client.post(
        "/api/v1/ledger/entries",
        json=_body(users["shipper"].id, unit_price="0", total="0"),
        headers=auth_headers(token_dispatcher),
    )
    assert zero.status_code in (200, 201), zero.text
