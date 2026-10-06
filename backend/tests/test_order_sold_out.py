"""台账 L-35 / BUG-0017：沽清（下架）的商品**不能再下单** —— 后端这一道闸。

用户 m01347 原话（台账 `_tmp/USER_BUG_LEDGER_20261006.md` 的 L-35 段）：
> 「文字的话你就留一个**已沽清**吧；灰掉了之后**就不能点**的哈……就是**整卡变灰**嘛……
>  就是**拦住不让下**，不可能是提示后他仍然可以下呀。」

客户端那两处（选品页那一格点不动、提交前拦住并点名哪一行）只挡得住**界面**：
AI 下单、老包、直接打接口都绕得过 —— 所以同一条规矩必须在下单这条**唯一的**路上
（`app/services/order_flow.py :: build_order_products`）也成立。

⛔ 老单不走这条路（改数量 / 转单 / 拆单都不经过 `build_order_products`）：
历史订单里那些"后来被沽清"的行照旧能看、能动 —— 这一份判据不碰它们。
"""

from __future__ import annotations

from decimal import Decimal

from app.models import Order, Product
from tests.conftest import auth_headers

SOLD_OUT_WORD = "已经沽清（下架）"


def _mk_product(db_session, name: str, *, active: bool = True, deleted: bool = False) -> int:
    p = Product(
        name=name,
        unit="件",
        default_unit_price=Decimal("12.30"),
        cost_price=Decimal("6.00"),
        stock=100,
        is_active=active,
        is_deleted=deleted,
    )
    db_session.add(p)
    db_session.commit()
    return int(p.id)


def _line(name: str, product_id: int | None = None, qty: int = 2) -> dict:
    ln: dict = {
        "product_name_snapshot": name,
        "quantity": qty,
        "unit_price": "12.30",
        "line_total": "24.60",
    }
    if product_id is not None:
        ln["product_id"] = product_id
    return ln


def _post(client, token: str, lines: list[dict], **over):
    payload: dict = {
        "lines": lines,
        "address_detail": "沽清闸门测试地址",
        "contact_dongjia_name": "收货人甲",
    }
    payload.update(over)
    return client.post("/api/v1/orders", json=payload, headers=auth_headers(token))


def test_沽清的商品带商品编号下单被拒(client, db_session, token_shipper) -> None:
    """① 商品库里那件已经沽清 ⇒ 整单被拒，说清是第几行、哪一件、怎么办。"""
    pid = _mk_product(db_session, "沽清探针货", active=False)
    r = _post(client, token_shipper, [_line("沽清探针货", pid)])
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert SOLD_OUT_WORD in detail, detail
    assert "第 1 行" in detail, detail
    assert "沽清探针货" in detail, detail


def test_在售的商品照旧能下单(client, db_session, token_shipper) -> None:
    """② 回归：这条闸门只认沽清 —— 在售商品照旧下得出去，成本快照照旧按商品库取。"""
    pid = _mk_product(db_session, "在售探针货")
    r = _post(client, token_shipper, [_line("在售探针货", pid)])
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["order_products"][0]["product_id"] == pid


def test_手输的自定义商品不受影响(client, db_session, token_shipper) -> None:
    """③ 边界：没有 product_id 的手输商品（"不填商品编号"那条路）不在这道闸门里。"""
    r = _post(client, token_shipper, [_line("手输入库的散货")])
    assert r.status_code == 201, r.text
    assert r.json()["order_products"][0]["product_id"] is None


def test_已删除的商品仍然走原来那句(client, db_session, token_shipper) -> None:
    """④ 边界：删除与沽清是两句话（原来的那句一个字不动）。"""
    pid = _mk_product(db_session, "已删探针货", deleted=True)
    r = _post(client, token_shipper, [_line("已删探针货", pid)])
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "已经删除了" in detail, detail
    assert SOLD_OUT_WORD not in detail, detail


def test_混合行时点名的是沽清那一行(client, db_session, token_shipper) -> None:
    """⑤ 正向：第 2 行沽清 ⇒ 提示说的是「第 2 行」，不冤枉第 1 行那件在售的。"""
    ok_pid = _mk_product(db_session, "在售探针货甲")
    bad_pid = _mk_product(db_session, "沽清探针货乙", active=False)
    r = _post(client, token_shipper, [_line("在售探针货甲", ok_pid), _line("沽清探针货乙", bad_pid)])
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "第 2 行" in detail, detail
    assert "沽清探针货乙" in detail, detail
    assert "第 1 行" not in detail, detail


def test_被拒时一件订单都没落库(client, db_session, token_shipper) -> None:
    """⑥ 失败时不产生半成品事实：整单回滚，一条订单都不留。"""
    pid = _mk_product(db_session, "沽清探针货丙", active=False)
    before = db_session.query(Order).count()
    r = _post(client, token_shipper, [_line("沽清探针货丙", pid)])
    assert r.status_code == 400, r.text
    db_session.expire_all()
    assert db_session.query(Order).count() == before
