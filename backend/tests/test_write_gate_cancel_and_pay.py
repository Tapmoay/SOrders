"""两条「写路径闸门」的回归用例（2026-09-24 第 24 轮并行渗透 03-F1 + 01-D1）。

## ① 回收站里的单不许撤销（03-F1，[中]）
`POST /orders/{id}/cancel` 原来是一次**裸 select**，判据链里没有 `deleted_at` ——
而 R13-D1 当年只给「送达 / 上传凭证 / 追加备注 / 派单」四条写路径补了 `_order_not_deleted_or_404`，
撤销是第 5 条，漏了。后果是**两个角色两种答案**：货主 `GET /orders/{id}` 是 404、
`?deleted_only=true` 是 403（界面上根本看不到这张单），可同一个 id 发 `POST /cancel` 却成功 ——
一张他看不见的单被改成「已撤销」，还推一条「已撤销」通知给他（点进去 404）。

## ② 现场收款与挂账互不设防（01-D1，[高]）
`pay`（写 `paid=True`）与 `charge`（写 `paid=False`）原来都是"普通 SELECT → 判断 → 无条件赋值"，
一处锁都没取。交错时 `charge` 用旧快照把 `paid` 写回 False ⇒ `pay` 那笔收款在所有口径里归零
（`pay_order` 按设计不写收款单/流水），两道防重门双双放行 ⇒ **同一笔钱再收一次**。
修法是在两侧都"**先取锁再判**"（`lock_order_row`）。

⛔ 诚实的边界：真正的**并发**交错在单进程测试里造不出来（SQLite 上 `lock_order_row` 只是
"重新查一次"）。所以这里钉的是**判据本身成立**（先收款后挂账必须被拒）+ **取锁的写法在位**
（源码级断言，与 `_check_status_gate_locking.py` 的 A 节同源）——
不钉"并发下一定不会出事"，那要有 MySQL 的压力测试才算数。
"""

from __future__ import annotations

import inspect

import pytest
from starlette.testclient import TestClient

from tests.conftest import auth_headers


def _mk_order(client: TestClient, token_dispatcher: str, shipper_id: int) -> dict:
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": shipper_id,
            "lines": [{"product_name_snapshot": "闸门探针", "quantity": 1, "unit_price": "20"}],
            "address_detail": "闸门探针",
            "delivery_description": "闸门探针",
        },
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_回收站里的单不许撤销(
    client: TestClient, users: dict, token_dispatcher: str, token_shipper: str
) -> None:
    """派单员把一张待派单删进回收站之后：**两个角色都不能再撤销它**（都回 404 订单不存在）。"""
    h = auth_headers(token_dispatcher)
    body = _mk_order(client, token_dispatcher, users["shipper"].id)
    oid = body["id"]

    assert client.delete(f"/api/v1/orders/{oid}", headers=h).status_code == 204
    # 前置条件：这张单确实进了隔离区。⚠️ 派单员**看得见**它（回收站是他的视图，200），
    # 而货主那边是 404 —— 两种答复都对，下面要守的是"**都不能撤销**"。
    assert client.get(f"/api/v1/orders/{oid}", headers=h).status_code == 200
    assert client.get(
        f"/api/v1/orders/{oid}", headers=auth_headers(token_shipper)
    ).status_code == 404

    # ★ 货主不能用撤销去改一张他看不见的单（原来这里返回 200）
    r = client.post(f"/api/v1/orders/{oid}/cancel", headers=auth_headers(token_shipper))
    assert r.status_code == 404, (
        f"货主撤销了一张在回收站里的单（{r.status_code}）——他界面上看不到它，"
        f"却会收到一条「已撤销」通知：{r.text[:160]}"
    )
    # 派单员同样不行（与另外四条写路径同一个判据、同一句答复）
    r = client.post(f"/api/v1/orders/{oid}/cancel", headers=h)
    assert r.status_code == 404, f"派单员也不该撤销回收站里的单：{r.status_code} {r.text[:160]}"

    # 单子状态一个字没动
    detail = client.get("/api/v1/orders", params={"deleted_only": True, "limit": 200}, headers=h).json()
    row = next(o for o in detail if o["id"] == oid)
    assert row["status"] == "PENDING_DISPATCH", row["status"]
    assert row["deleted_at"] is not None


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_先收款再挂账必须被拒(client: TestClient, users: dict, token_dispatcher: str) -> None:
    """`pay` 之后 `charge` 必须 400 —— 这道判据就是 01-D1 那条竞争要保护的东西。"""
    h = auth_headers(token_dispatcher)
    body = _mk_order(client, token_dispatcher, users["shipper"].id)
    oid = body["id"]

    paid = client.post(f"/api/v1/orders/{oid}/pay", headers=h)
    assert paid.status_code == 200, paid.text
    assert paid.json()["paid"] is True

    charged = client.post(
        f"/api/v1/orders/{oid}/charge",
        json={"arrears_unit_name": "闸门探针挂账单位"},
        headers=h,
    )
    assert charged.status_code == 400, (
        f"已收款的单被改回了挂账（{charged.status_code}）——那等于把 paid 写回 False，"
        f"给这张单重新开一次收款窗口：{charged.text[:200]}"
    )
    assert "已经收过款" in charged.json()["detail"], charged.json()

    again = client.get(f"/api/v1/orders/{oid}", headers=h).json()
    assert again["paid"] is True and again["payment_method"] == "cash", (
        f"被拒之后库里不许有任何改动：paid={again['paid']} method={again['payment_method']}"
    )


@pytest.mark.dispatcher
@pytest.mark.fast
def test_收款与挂账两条路都先取锁再判() -> None:
    """源码级钉子：`pay_order` / `charge_order` 的第一句必须是"锁 + 重读"。

    为什么要有它（而不是只靠上面那条行为用例）：这两条路的差别只在**并发**时显形，
    而单进程里怎么点都是绿的。真正会退化的写法是"顺手把 `lock_order_row` 去掉"
    （看起来无害：单线程行为一模一样），所以这里把它钉住 ——
    与 `_tools/qa/_check_status_gate_locking.py` 的 A 节同一个主张。
    """
    # ⚠️ 2026-09-24 整改阶段 4：pay_order / charge_order 从 `orders.py` 纯搬迁到 `orders_payment.py`
    #    （判据一个字没改，只跟着搬家）。
    from app.api.v1 import orders_payment as mod

    for fn in (mod.pay_order, mod.charge_order):
        src = inspect.getsource(fn)
        assert "lock_order_row(db, _payment_scoped_order(" in src, (
            f"{fn.__name__} 不再「先取锁再判」——并发下同一笔钱可能被收两次：\n{src[:400]}"
        )
        lock_at = src.index("lock_order_row(")
        check_at = src.index("_reject_if_already_collected(")
        assert lock_at < check_at, (
            f"{fn.__name__} 里 `lock_order_row` 出现在判据**之后**（{lock_at} > {check_at}）——"
            "先判后锁等于没锁，判完到拿锁之间那道缝还在"
        )
