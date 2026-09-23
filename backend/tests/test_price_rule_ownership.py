"""批发商专属价的**归属**改动：要校验目标账号、要留痕（2026-09-24 第 22 轮 F12-1）。

## 缺陷长什么样
`PATCH /price-rules/{id}` 是唯一能让一条专属价**换主人**的入口 —— 而它原来：

| # | 问题 | 后果 |
|---|---|---|
| ① | `body.shipper_id` 指向**不存在**的账号照样 200（`create` 查了，PATCH 没查） | 这条价从此对谁都不生效，却仍占着 `(shipper_id, product_id)` 唯一槽位 —— 别的货主再也设不进这个商品的价，而接口说"已完成" |
| ② | 只改归属、不改价时 `before != pr.special_unit_price` 为假 → **一条日志都没有** | 批发商成交价读的就是这一行；改错了是钱上的事，而审计页查不出"原来归谁" |

② 的形状还有个判据缺口：`_tools/qa/_check_audit_coverage.py` 第 ② 条只问
"`db.commit()` 之前文本上出现过 `write_log(`"——**停在同一个函数里就算过**，
看不见"`write_log` 被一个恒假的 `if` 包着"。这条缺口没有机械修法（写得太宽会变成假判据），
所以这里用**行为用例**钉住：改归属必须留下一条带 `moved_from` 的日志。
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from tests.conftest import auth_headers


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


def _price_logs(db_session) -> list[dict]:
    """所有专属价审计行的 change 内容（字段名是 `change_content`，JSON 文本）。"""
    from app.models import OperationAction, OperationLog

    db_session.expire_all()
    out: list[dict] = []
    for r in db_session.scalars(
        select(OperationLog).where(OperationLog.action == OperationAction.PRICE_RULE_UPSERT)
    ):
        try:
            payload = json.loads(r.change_content or "{}")
        except ValueError:
            payload = {}
        out.append(payload if isinstance(payload, dict) else {})
    return out


def _fixtures(client: TestClient, db_session, token_dispatcher: str) -> tuple[int, int, int, str]:
    """建一个商品 + 两个批发商账号 + 一条归 A 的专属价，返回 (rule_id, product_id, A_id, B名)。"""
    from app.models import PriceRule, Product, User

    h = auth_headers(token_dispatcher)
    product = Product(name=_uniq("归属探针商品"), default_unit_price=Decimal("10"), stock=0)
    db_session.add(product)
    db_session.flush()

    made: list[User] = []
    for i in range(2):
        phone = ("139" + uuid.uuid4().hex[:8].translate(str.maketrans("abcdef", "012345")))[:11]
        r = client.post(
            "/api/v1/users",
            headers=h,
            json={
                "phone": phone,
                "password": "pass12345",
                "full_name": _uniq(f"归属探针批发商{i}"),
                "role": "shipper",
                "is_member": True,
            },
        )
        assert r.status_code in (200, 201), r.text
        made.append(db_session.get(User, int(r.json()["id"])))

    rule = PriceRule(
        shipper_id=made[0].id, product_id=product.id, special_unit_price=Decimal("8.00")
    )
    db_session.add(rule)
    db_session.commit()
    return rule.id, product.id, made[0].id, made[1].full_name


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_改归属必须留痕(client: TestClient, db_session, token_dispatcher: str) -> None:
    """只改归属（价格一个字没动）也必须写一条审计，且写明原来归谁。"""
    rid, _pid, _a_id, b_name = _fixtures(client, db_session, token_dispatcher)
    from app.models import PriceRule, User

    b_id = db_session.scalars(
        select(User.id).where(User.full_name == b_name)
    ).first()

    before = len(_price_logs(db_session))
    r = client.patch(
        f"/api/v1/price-rules/{rid}", json={"shipper_id": b_id}, headers=auth_headers(token_dispatcher)
    )
    assert r.status_code == 200, r.text
    assert r.json()["shipper_id"] == b_id

    logs = _price_logs(db_session)
    assert len(logs) == before + 1, (
        f"只改归属也要留一条痕（原来这里一条都没有）—— 实际新增 {len(logs) - before} 条"
    )
    payload = logs[-1]
    assert payload.get("moved_from"), f"日志要写明原来算在谁头上：{payload}"
    assert payload.get("shipper") == b_name, f"日志要写清新的归属是谁：{payload}"
    # ⚠️ 前后都是列里的精度（`Numeric(14,4)` → "8.0000"）：日志里存的是**值**不是显示，
    #    所以不过 `money_text`（去尾零那条规矩只作用于"给人看的字"）。
    #    这里要证明的是"没把它记成一次调价"，不是格式。
    assert payload.get("before") == "8.0000" and payload.get("after") == "8.0000", (
        f"价格没动，前后都该是 8.0000（不能把'没改价'记成一次调价）：{payload}"
    )


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_改到不存在的账号要被拒绝且不动数据(
    client: TestClient, db_session, token_dispatcher: str
) -> None:
    """目标账号不存在 → 400（`create` 一直是这么查的），并且谁也不许被悄悄改掉。"""
    rid, _pid, a_id, _b = _fixtures(client, db_session, token_dispatcher)
    from app.models import PriceRule

    before = len(_price_logs(db_session))
    r = client.patch(
        f"/api/v1/price-rules/{rid}",
        json={"shipper_id": 99999999},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 400, (
        f"改到一个不存在的账号居然成功了（{r.status_code}）——"
        "这条价从此对谁都不生效，却还占着（货主+商品）的唯一槽位"
    )
    assert "账号" in r.json()["detail"], r.json()

    db_session.expire_all()
    assert db_session.get(PriceRule, rid).shipper_id == a_id, "被拒绝的改动不许动数据"
    assert len(_price_logs(db_session)) == before, "被拒绝的改动不许留审计（假审计比没有审计更糟）"


@pytest.mark.dispatcher
@pytest.mark.fast
def test_价格没动也没换归属时不写日志(
    client: TestClient, db_session, token_dispatcher: str
) -> None:
    """原样回传（价格相同、归属相同）不该在审计页上多出一行 —— 那一页只显示最近 60 条。"""
    rid, _pid, a_id, _b = _fixtures(client, db_session, token_dispatcher)

    before = len(_price_logs(db_session))
    r = client.patch(
        f"/api/v1/price-rules/{rid}",
        json={"special_unit_price": "8.00", "shipper_id": a_id},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text
    assert len(_price_logs(db_session)) == before, "什么都没变就不该记一条调价"
