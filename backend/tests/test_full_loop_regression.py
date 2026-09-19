"""跨域端到端回归：**一整条生产循环跑在一张单上**，验证这几轮修的不变量互不打架。

前面每一轮都是"按缺陷性质"修的（库存预占、账本唯一、收款口径、结算占位、审计痕迹、
毛利口径、状态跃迁 CAS……）。修完各自的单测之后，还缺一件事：
**它们在同一条订单的完整流程里同时成立吗？** —— 单点正确但互相抵消是完全可能的
（例如"预占跟着行变"与"送达按流水扣库"分别在两处实现，谁改谁就分叉）。

这个文件跑一张单的全生命周期，并在**每一步**断言当时该成立的那条：

    下单 → 派单（预占）→ 改行数量（预占重算）→ 接单 → 送达（实扣 + 账单）
        → 账本（唯一）→ 报表（口径闭合）→ 收款（逐单核销 + 流水）
        → 结算（占位）→ 审计（每一步都有痕迹）
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.models import CashFlow, DriverBill, InventoryMovement, Ledger, OperationLog, Product
from tests.conftest import auth_headers


def _stock(db_session, pid: int) -> int:
    db_session.expire_all()
    return int(db_session.get(Product, pid).stock or 0)


def _reserved(db_session, oid: int) -> int:
    db_session.expire_all()
    rows = db_session.scalars(
        select(InventoryMovement).where(
            InventoryMovement.order_id == oid,
            InventoryMovement.source == "ORDER",
            InventoryMovement.status == "RESERVED",
        )
    ).all()
    return sum(int(m.change or 0) for m in rows)


def _actions(db_session) -> list[str]:
    db_session.expire_all()
    return [x.action for x in db_session.scalars(select(OperationLog))]


def test_full_production_loop_holds_all_audited_invariants(
    client, db_session, users, token_dispatcher, token_shipper, token_driver
):
    h = auth_headers(token_dispatcher)
    hs = auth_headers(token_shipper)
    hd = auth_headers(token_driver)
    # 报表锚点 = **业务当地日**（2026-09-19 审计 R12-M11：报表按当地日分桶，
    # 而 `delivered_at` 存的是 UTC；锚点原样用 UTC 日期时，东八区当地 0~8 点会错一天）
    from app.core.business_time import business_today

    today = business_today().isoformat()

    # ---- 0. 一份"每单 30 + 运费 10%"的规则：让它同时覆盖"按单"与"提成"两条算法 ----
    rule = client.post(
        "/api/v1/driver-billing-rules",
        json={"name": "端到端探针规则", "piece_amount": "30",
              "commission_base": "freight", "commission_rate": "10"},
        headers=h,
    )
    assert rule.status_code in (200, 201), rule.text
    assert client.post(
        "/api/v1/driver-billing-rules/attach",
        json={"driver_id": users["driver"].id, "rule_id": rule.json()["id"]},
        headers=h,
    ).status_code in (200, 201)

    # ---- 1. 商品（成本 4 元）+ 货主下单 2 件 ----
    prod = client.post(
        "/api/v1/products",
        json={"name": "端到端探针货", "default_unit_price": "10", "cost_price": "4", "stock": 100},
        headers=h,
    )
    assert prod.status_code in (200, 201), prod.text
    pid = prod.json()["id"]
    stock0 = _stock(db_session, pid)

    order = client.post(
        "/api/v1/orders",
        # ⚠️ 货主自己下单**不能带 `shipper_id`**（后端会 400「货主下单无需指定货主」）；
        #    只有派单员代理下单才需要 shipper_id / temp_shipper_name。
        json={
            "lines": [{
                "product_id": pid, "product_name_snapshot": "端到端探针货",
                "quantity": 2, "unit_price": "10", "line_total": "20",
            }],
            "address_detail": "端到端探针地址",
        },
        headers=hs,
    )
    assert order.status_code == 201, order.text
    oid = int(order.json()["id"])
    assert order.json()["status"] == "PENDING_DISPATCH"

    # ---- 2. 派单：只预占、不动实际库存 ----
    # ⚠️ 这里必须显式勾「收取现金」：第 5 步司机要按现金送达，而"没勾选却按现金收"现在会被
    #    后端明确拒绝（2026-09-19 真机 E2E 抓到的静默分歧，见 test_complete_payment_contract.py）。
    assert client.post(
        f"/api/v1/orders/{oid}/assign",
        json={"driver_id": users["driver"].id, "freight_fee": "200", "collect_cash": True},
        headers=h,
    ).status_code == 200
    assert _stock(db_session, pid) == stock0, "派单只预占，实际库存不该动"
    assert _reserved(db_session, oid) == -2

    # ---- 3. 派单后改数量 2 → 5：预占必须跟着重算（K1）----
    line = client.get(f"/api/v1/order-products?order_id={oid}", headers=h).json()[0]
    assert client.patch(f"/api/v1/order-products/{line['id']}", json={"quantity": 5},
                        headers=h).status_code == 200
    assert _reserved(db_session, oid) == -5, "改量后预占要跟着变（否则送达按旧流水扣库）"

    # ---- 4. 接单 ----
    assert client.post(f"/api/v1/orders/{oid}/driver-ack", headers=hd).status_code == 200

    # ---- 5. 送达（现场收现金）：实扣 = 当前订单行数量；账单按**规则**算 ----
    done = client.post(
        f"/api/v1/orders/{oid}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/loop.jpg"], "payment": "cash"},
        headers=hd,
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "DELIVERED"
    assert _stock(db_session, pid) == stock0 - 5, "送达按**当前订单行**扣库（不是按旧流水）"

    db_session.expire_all()
    bills = [
        b for b in db_session.scalars(select(DriverBill).where(DriverBill.order_id == oid))
    ]
    assert len(bills) == 1, f"一张单只能有一张账单（实际 {len(bills)}）"
    # 每单 30 + 运费 10% × 200 = 30 + 20 = 50
    assert float(bills[0].amount) == 50.0, f"账单要按规则算（每单30+提成10%），实际 {bills[0].amount}"

    # ---- 6. 账本：同一订单行只入账一次（M8 的唯一约束）----
    db_session.expire_all()
    ledgers = [x for x in db_session.scalars(select(Ledger).where(Ledger.order_id == oid))]
    assert len(ledgers) == 1, f"同一订单行只能有一行系统账（实际 {len(ledgers)}）"

    # ---- 7. 报表口径闭合：营业额 = 已收 + 挂账；毛利只按有成本快照的行（R1）----
    rep = client.get(f"/api/v1/reports/turnover?mode=day&date={today}", headers=h).json()
    assert abs(float(rep["collected"]) + float(rep["arrears_total"]) - float(rep["total_amount"])) < 0.005, \
        "已收 + 挂账必须等于营业额（完整划分）"
    # 毛利口径：**收入侧只收有成本快照的行**（本单每件成本 4、卖 10、5 件 → 参与毛利的收入 50）
    assert float(rep["cost_covered_amount"]) >= 50.0, "有成本快照的收入要被统计进毛利基数"
    assert float(rep["cost_total"]) >= 20.0, "成本合计要按快照算进报表（4 × 5 = 20）"

    # ---- 8. 收款：这张单**已经标了已收现金**，逐单核销必须被拒（不能重复收款）----
    cust = client.post(
        "/api/v1/customers",
        json={"name": "端到端探针客户", "kind": "tmp", "phone": "13900007777"},
        headers=h,
    )
    assert cust.status_code in (200, 201), cust.text
    cid = cust.json()["id"]
    dup = client.post(
        "/api/v1/ledger/receipts",
        json={"customer_id": cid, "amount": "50.00", "method": "cash",
              "settle_mode": "itemized", "order_ids": [oid], "received_at": today},
        headers=h,
    )
    assert dup.status_code == 400, f"已经收过款的单不能再核销一次：{dup.status_code} {dup.text}"

    # ---- 9. 结算：建单 → 确认 → 付款（占位保证只付一次）----
    settle = client.post(
        "/api/v1/driver-settlements",
        json={"driver_id": users["driver"].id, "month": bills[0].month, "settle_type": "piece"},
        headers=h,
    )
    assert settle.status_code in (200, 201), settle.text
    sid = settle.json()["id"]
    assert client.patch(f"/api/v1/driver-settlements/{sid}", json={"action": "confirm"},
                        headers=h).status_code == 200
    assert client.patch(f"/api/v1/driver-settlements/{sid}", json={"action": "pay", "method": "cash"},
                        headers=h).status_code == 200
    # 重复付款必须被拒（并发/双击）
    again = client.patch(f"/api/v1/driver-settlements/{sid}", json={"action": "pay", "method": "cash"},
                         headers=h)
    assert again.status_code == 400, f"同一张结算单不能付两次：{again.status_code} {again.text}"
    db_session.expire_all()
    flows = [
        f for f in db_session.scalars(
            select(CashFlow).where(
                CashFlow.doc_id == sid,
                # ⚠️ 必须同时限定 biz_type：`doc_id` 是**通用文档号**，收款单/结算单/开销
                #    共用同一个取值空间 —— 只按 doc_id 查会把别的单据的流水一起数进来
                #    （全量套件里实测数出 2 条，单文件跑时恰好没撞上）。
                CashFlow.biz_type.in_(["PAYMENT_DRIVER", "PAYMENT_SALARY"]),
            )
        )
    ]
    assert len(flows) == 1, f"一次付款只能落一条现金流水（实际 {len(flows)}）"

    # ---- 10. 审计：这条链上每一步都留了痕（M9）----
    acts = _actions(db_session)
    for want in (
        "ORDER_CREATE", "ORDER_DISPATCH", "ORDER_LINE_UPDATE", "ORDER_COMPLETE",
        "SETTLEMENT_CREATE", "SETTLEMENT_STATUS",
    ):
        assert want in acts, f"少了操作日志：{want}（审计页就查不到这一步）"
