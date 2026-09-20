"""真机（真后端）走一遍**退货申请**全流程：货主申请 → 派单员收到通知 → 办理 → 库存才变。

这不是静态检查，是**打真 HTTP** 的探针（`_probe_*` 前缀不会被 `_check_all.py` 自动跑）。
用法（先确保本机后端在 127.0.0.1:8000）：

    python _tools/qa/_probe_return_request.py

它回答的是**静态检查回答不了**的那两个问题：
1. 「申请阶段真的一分钱、一件货都不动吗」——把库存和账本条数在申请前后各拍一次；
2. 「派单员真能收到通知吗」——去 `notifications` 里找那条 `order.return_request`。

⚠️ 会在本机开发库留下一条测试单（与 `_tools/notify/_assign_order.py` 同一取舍）：
   单号前缀 `SOPROBE-`，方便事后清理。
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"
ACCOUNTS = {
    "dispatcher": ("13800000001", "123321"),
    "shipper": ("13800000002", "123321"),
    "driver": ("13800000003", "123321"),
}

OK, BAD = "[OK]", "[!!]"
fails: list[str] = []


def call(method: str, path: str, token: str | None = None, body: dict | None = None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:  # noqa: BLE001
            return e.code, {"detail": raw[:200]}


def login(who: str) -> str:
    phone, pw = ACCOUNTS[who]
    st, body = call("POST", "/auth/login", body={"phone": phone, "password": pw})
    if st != 200 or not body:
        raise SystemExit(f"❌ {who} 登录失败：{st} {body}")
    return body["access_token"]


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"  {OK if cond else BAD} {label}" + (f"　{detail}" if detail else ""))
    if not cond:
        fails.append(label)


def main() -> int:
    td, ts, tv = login("dispatcher"), login("shipper"), login("driver")

    # ---- 1. 备一张「已送达」的单（带商品编号，退货红冲才有成本快照）----
    st, products = call("GET", "/products?limit=1", td)
    if st != 200 or not products:
        raise SystemExit(f"❌ 拿不到商品：{st} {products}")
    p = products[0]
    pid, pname, unit_price = p["id"], p["name"], str(p.get("default_unit_price") or "10.00")

    qty = 3
    st, order = call(
        "POST",
        "/orders",
        ts,
        {
            "lines": [
                {
                    "product_id": pid,
                    "product_name_snapshot": pname,
                    "quantity": qty,
                    "unit_price": unit_price,
                    "line_total": str(float(unit_price) * qty),
                }
            ],
            "delivery_description": "SOPROBE 退货申请探针地址",
            "address_detail": "SOPROBE 退货申请探针地址",
        },
    )
    if st != 201:
        raise SystemExit(f"❌ 下单失败：{st} {order}")
    oid, ono = order["id"], order["order_no"]
    print(f"\n探针单：{ono}（id={oid}）· {pname} ×{qty} @ {unit_price}")

    # 派给**登录的这个司机本人**（拿 `/users?role=driver` 的第一条会派给别的司机，
    # 于是 driver-ack 403、complete 400 —— 第一版就是这么错的）
    st, me = call("GET", "/users/me", tv)
    driver_id = me["id"] if st == 200 else None
    if driver_id is None:
        raise SystemExit("❌ 拿不到司机身份")
    for path, body in (
        (f"/orders/{oid}/assign", {"driver_id": driver_id}),
        (f"/orders/{oid}/driver-ack", None),
    ):
        st, r = call("POST", path, tv if "ack" in path else td, body)
        check(f"{path} → 200", st == 200, f"{st}")
    st, r = call(
        "POST",
        f"/orders/{oid}/complete",
        tv,
        {"delivery_photo_urls": ["/static/uploads/delivery/probe.jpg"]},
    )
    check("送达 → 200", st == 200, f"{st}")

    def stock_now() -> int:
        # ⚠️ 商品名是中文：查询串必须 percent-encode（不编码会在 http.client 里
        #    抛 UnicodeEncodeError: 'ascii' codec —— 第一次就是这么挂的）
        from urllib.parse import quote

        s, ps = call("GET", f"/products?q={quote(pname)}&limit=200", td)
        return int(next(x["stock"] for x in ps if x["id"] == pid))

    def ledger_rows() -> int:
        s, rows = call("GET", f"/ledger/entries?order_id={oid}", td)
        return len(rows) if isinstance(rows, list) else -1

    stock_delivered = stock_now()
    rows_after_delivery = ledger_rows()
    st, detail = call("GET", f"/orders/{oid}", td)
    lines = detail["order_products"]
    line_id = lines[0]["id"]

    # ---- 2. 货主申请：★ 什么都不许动 ----
    print("\n== 申请阶段（用户要求：此刻库存/账本一动不动）==")
    before = (stock_delivered, rows_after_delivery)
    st, req = call(
        "POST",
        "/return-requests",
        ts,
        {"order_id": oid, "items": [{"order_product_id": line_id, "quantity": 2}], "note": "有两件破了"},
    )
    check("货主申请 → 201", st == 201, f"{st} {req if st != 201 else ''}")
    if st != 201:
        return 1
    rid = req["id"]
    check("状态=待派单员处理", req.get("status") == "pending" and req.get("status_label") == "待派单员处理", str(req.get("status_label")))
    check("件数与申请表一致（数量锁死）", req["lines"][0]["quantity"] == 2, str(req["lines"]))
    after = (stock_now(), ledger_rows())
    check("★ 库存没动（货还在客户手里）", after[0] == before[0], f"{before[0]} → {after[0]}")
    check("★ 账本没多一行（应收还没红冲）", after[1] == before[1], f"{before[1]} → {after[1]}")
    st, d2 = call("GET", f"/orders/{oid}", td)
    check("★ 已退金额仍是 0", float(d2["returned_amount"]) == 0.0, str(d2["returned_amount"]))
    check("★ 订单状态仍是已送达", d2["status"] == "DELIVERED", str(d2["status"]))

    # ---- 3. 派单员收到通知 ----
    print("\n== 通知 ==")
    st, notes = call("GET", "/notifications?days=1", td)
    hit = [
        n for n in (notes or [])
        if n.get("type") == "order.return_request" and (n.get("payload") or {}).get("request_id") == rid
    ]
    check("派单员收到「退货申请待处理」且带申请单号", bool(hit), f"{len(hit)} 条")
    if hit:
        print(f"      「{hit[-1]['title']}」{hit[-1]['content']}")

    # ---- 4. 货主自己退不了（越权必须 403）----
    st, _ = call(
        "POST",
        f"/orders/{oid}/return",
        ts,
        {"items": [{"order_product_id": line_id, "quantity": 2}]},
    )
    check("★ 货主直接调退货接口 → 403（申请制的那条线）", st == 403, f"{st}")

    # ---- 5. 派单员办理：★ 库存与账本此刻才变 ----
    print("\n== 办理阶段（用户要求：派单员进行完了之后库存才变）==")
    st, done = call("POST", f"/return-requests/{rid}/fulfill", td)
    check("办理 → 200", st == 200, f"{st} {done if st != 200 else ''}")
    if st == 200:
        check("申请单转「已办理」", done["request"]["status"] == "done", str(done["request"]["status_label"]))
        print(f"      退货金额 ¥{done['returned']['returned_amount']}　退款 ¥{done['returned']['refund_amount']}")
        stock_after = stock_now()
        check("★ 退回来的 2 件补回库存", stock_after == stock_delivered + 2, f"{stock_delivered} → {stock_after}")
        rows_after = ledger_rows()
        check("★ 账本多了一行（红冲）", rows_after > rows_after_delivery, f"{rows_after_delivery} → {rows_after}")
        st, d3 = call("GET", f"/orders/{oid}", td)
        check("已退金额 = 2 × 单价", abs(float(d3["returned_amount"]) - 2 * float(unit_price)) < 0.01, str(d3["returned_amount"]))
        check("仍是「已送达」（只退了 2/3）", d3["status"] == "DELIVERED", str(d3["status"]))
        st, n2 = call("GET", "/notifications?days=1", ts)
        done_notes = [n for n in (n2 or []) if n.get("type") == "order.return_request.done"]
        check("货主收到「退货已办理」", bool(done_notes), f"{len(done_notes)} 条")
        if done_notes:
            print(f"      「{done_notes[-1]['title']}」{done_notes[-1]['content']}")

    # ---- 6. 撤回与驳回（两条闭环）----
    print("\n== 撤回 / 驳回 ==")
    st, req2 = call(
        "POST",
        "/return-requests",
        ts,
        {"order_id": oid, "items": [{"order_product_id": line_id, "quantity": 1}]},
    )
    check("剩下的 1 件可以再申请", st == 201, f"{st} {req2 if st != 201 else ''}")
    if st == 201:
        rid2 = req2["id"]
        st, _ = call("POST", f"/return-requests/{rid2}/withdraw", ts)
        check("货主撤回 → 200", st == 200, f"{st}")
        st, r = call("POST", f"/return-requests/{rid2}/fulfill", td)
        check("撤回之后派单员办不了 → 400", st == 400, f"{st} {r.get('detail', '') if isinstance(r, dict) else ''}")

        st, req3 = call(
            "POST",
            "/return-requests",
            ts,
            {"order_id": oid, "items": [{"order_product_id": line_id, "quantity": 1}]},
        )
        if st == 201:
            rid3 = req3["id"]
            st, blank = call("POST", f"/return-requests/{rid3}/reject", td, {"reason": "   "})
            check("空理由驳回 → 400/422", st in (400, 422), f"{st}")
            st, rej = call("POST", f"/return-requests/{rid3}/reject", td, {"reason": "货已拆封，不能退"})
            check("驳回 → 200", st == 200, f"{st}")
            st, n3 = call("GET", "/notifications?days=1", ts)
            rej_notes = [n for n in (n3 or []) if n.get("type") == "order.return_request.rejected"]
            check("货主收到驳回理由", bool(rej_notes) and "货已拆封" in (rej_notes[-1]["content"] or ""), "")

    print("\n" + "=" * 60)
    if fails:
        print(f"❌ {len(fails)} 项不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print("✅ 全流程通过：申请不动货 → 通知到位 → 派单员办理后库存与账本才变")
    return 0


if __name__ == "__main__":
    sys.exit(main())
