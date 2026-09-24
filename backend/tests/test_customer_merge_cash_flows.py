"""客户合并必须把**真正记钱的那张表**也搬过去（2026-09-24 第 26 轮；第 25 轮 03 区 F1/F5）。

## 缺陷长什么样
一个客户的钱有三个键：档案 id（`customers.id`）、账号（`orders.shipper_id`）、
散客名字（`temp_shipper_name`）。而「这个客户收了多少、退了多少」在**资金流水**里是按
`cash_flows.party_type='customer' + party_id` 筛的（`GET /cash-flows/summary?...&party_id=`）。

`POST /customers/merge` 搬了 `ledgers.customer_id`、`shipper_receipts.customer_id`、
两份 `temp_shipper_name`，**唯独没搬 `cash_flows.party_id`** —— 全后端 0 处更新该列。
后果（本机实测）：customer 流水 income **¥11007.00 / 26 行**，按 `party_id=7` 筛得 ¥3755.60、
按 `party_id=8` 得 ¥3080.10 —— 合并之后按保留客户筛，**被并客户那几笔永远少一份**，
而流水的 `party_name` 还写着**已经被删掉**的那个客户名。
也就是说"把钱并到一起"（做合并的本来目的）在资金流水这一侧根本不会发生。

顺带修 F5：`merge_ids` 里有一个**不存在**的编号时原来 `continue` —— 照样 200、照样写一条
"合并成功"的审计，重复提交还会在审计页上留下两条一模一样的记录。合并是改钱的归属，
现在当场 404 说清楚。
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from tests.conftest import auth_headers


def _mk_customer(client: TestClient, h: dict, name: str) -> int:
    r = client.post(
        "/api/v1/customers",
        # ⚠️ `kind` 的合法取值是 **registered / tmp**（不是 shipper —— 那是"订单归属"那一侧的词）
        json={"name": name, "kind": "registered"},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    return int(r.json()["id"])


def _mk_flow(db_session, party_id: int, party_name: str, amount: str) -> int:
    """插一条客户资金流水（`party_type='customer'`，按 `party_id` 归属）。"""
    from app.models import CashFlow

    cf = CashFlow(
        party_type="customer",
        party_id=party_id,
        party_name=party_name,
        direction="in",
        # ⛔ 必须是 `CashFlowBizType` 里的**合法取值**（2026-09-24 第 27 轮实测）：
        #    第一版写的是 `"RECEIPT_CUSTOMER"` —— 那个值**不存在**，于是这一行进测试库之后，
        #    任何序列化资金流水的端点都会 `ResponseValidationError` → 因为测试库是
        #    **同一个文件里跨用例复用**的，它把整批用例一起带红（实测 20 failed / 683 errors）。
        #    教训与"别污染共享夹具"同源：往共享库里插的行，字段取值必须是**真的合法**。
        biz_type="RECEIPT_CASH",
        amount=Decimal(amount),
        flow_date=__import__("datetime").date(2026, 9, 1),
        note=f"合并探针-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(cf)
    db_session.commit()
    return int(cf.id)


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_合并要把资金流水也搬过去(
    client: TestClient, db_session, token_dispatcher: str
) -> None:
    h = auth_headers(token_dispatcher)
    suffix = uuid.uuid4().hex[:6]
    keep_id = _mk_customer(client, h, f"保留客户-{suffix}")
    gone_id = _mk_customer(client, h, f"被并客户-{suffix}")
    keep_name = f"保留客户-{suffix}"
    gone_name = f"被并客户-{suffix}"

    flow = _mk_flow(db_session, gone_id, gone_name, "123.45")

    r = client.post(
        "/api/v1/customers/merge",
        json={"keep_id": keep_id, "merge_ids": [gone_id]},
        headers=h,
    )
    assert r.status_code == 200, r.text

    from app.models import CashFlow

    db_session.expire_all()
    moved = db_session.get(CashFlow, flow)
    assert moved is not None, "流水不该被删"
    assert moved.party_id == keep_id, (
        "客户合并没有把 `cash_flows.party_id` 搬过去 —— 资金流水是**真正记钱**的那张表"
        f"（按 party_id 筛客户的钱），漏搬等于'合并之后按保留客户筛永远少一笔'：{moved.party_id}"
    )
    assert (moved.party_name or "").strip() == keep_name, (
        f"流水上的客户名还是那个已经被删掉的客户：{moved.party_name!r}"
    )


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_合并里出现不存在的编号要当场拒绝(
    client: TestClient, db_session, token_dispatcher: str
) -> None:
    """打错编号不许静默 200（否则审计页会留下一条"合并成功"而实际什么都没做）。"""
    h = auth_headers(token_dispatcher)
    keep_id = _mk_customer(client, h, f"保留客户-{uuid.uuid4().hex[:6]}")

    from app.models import OperationLog

    before = db_session.query(OperationLog).filter_by(action="CUSTOMER_MERGE").count()
    r = client.post(
        "/api/v1/customers/merge",
        json={"keep_id": keep_id, "merge_ids": [99999999]},
        headers=h,
    )
    assert r.status_code == 404, f"合并一个不存在的编号应当 404：{r.status_code} {r.text[:160]}"
    db_session.expire_all()
    after = db_session.query(OperationLog).filter_by(action="CUSTOMER_MERGE").count()
    assert after == before, "被拒绝的合并不许留一条'合并成功'的审计"
