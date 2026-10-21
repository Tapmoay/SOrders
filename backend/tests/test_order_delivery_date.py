"""FEAT-0028：下单时可以选「送达日期」，后端只拒**早于今天**那一种。

用户 2026-10-21 原话：
> 「货主和批发商以及派单员，他们在下单的时候……**可以选择送到的日期**；……
>   告诉他们**订单必须提前一天下达**，当天下的单不一定能准时送达。」

三条口径，一条用例盯一条：

1. **传了明天** ⇒ 原样落库，并且**出参读得回来**（出参没有它，详情 / 卡片 / AI 全都看不见）；
2. **传了昨天** ⇒ 400 + 一句中文（"送达日期不能早于今天"）。判的是**业务当地日**
   （`business_today()`），不是服务器时区那天 —— 东八区凌晨那几个小时两者差一天；
3. **不传** ⇒ NULL 照收（老版本 App / AI 下单走的就是这条路）。⛔ 服务端**不许**替它认一个默认值：
   那等于替用户答应了一个他没选过的日子。
"""

from __future__ import annotations

from datetime import timedelta

from app.core.business_time import business_today
from tests.conftest import auth_headers


def _post(client, token: str, **over):
    payload: dict = {
        "lines": [
            {
                "product_name_snapshot": "送达日探针货",
                "quantity": 1,
                "unit_price": "10.00",
                "line_total": "10.00",
            }
        ],
        "address_detail": "送达日测试地址",
        "contact_dongjia_name": "收货人甲",
    }
    payload.update(over)
    return client.post("/api/v1/orders", json=payload, headers=auth_headers(token))


def test_明天的送达日原样落库并回读(client, token_shipper) -> None:
    tomorrow = (business_today() + timedelta(days=1)).isoformat()
    r = _post(client, token_shipper, delivery_date=tomorrow)
    assert r.status_code == 200 or r.status_code == 201, r.text
    assert r.json()["delivery_date"] == tomorrow, r.text


def test_昨天的送达日被拒且说中文(client, token_shipper) -> None:
    yesterday = (business_today() - timedelta(days=1)).isoformat()
    r = _post(client, token_shipper, delivery_date=yesterday)
    assert r.status_code == 400, r.text
    assert "送达日期不能早于今天" in r.json()["detail"], r.text


def test_不传送达日也能下单且留空(client, token_shipper) -> None:
    """老版本 App / AI 下单不带这个字段 —— 照收，且**不替它编一个日子**。"""
    r = _post(client, token_shipper)
    assert r.status_code == 200 or r.status_code == 201, r.text
    assert r.json()["delivery_date"] is None, r.text
