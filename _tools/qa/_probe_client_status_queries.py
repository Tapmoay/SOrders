"""真后端实测：**H5 司机端那两条查询能不能拿到「已派单」的单**（2026-09-19 审计 H1 的现场复核）。

## 为什么单独跑这一条
H1 的修法是客户端侧的（H5 原来只查 `ACCEPTED`），这类改动**单测与静态红线都不足以证明它有用**：
真正要证的是"按 H5 现在发的两个请求，一台刚被派单的司机的手机上会出现这张单"。
所以这里走**真链路**：派单员建单 → 派给司机 → 用**司机账号**按 H5 的两条查询去取。

判据（全绿才算过）：
1. `GET /orders?status=DISPATCHED`（司机本人）能拿到**刚派给他的那一张**；
2. 该单的 `is_new_for_driver == true`（H5 卡片上的感叹号与「接单」按钮靠它）；
3. `GET /orders?status=ACCEPTED` 此时**不含**它（两档不重不漏，合并后恰好一张）；
4. 司机 `POST /orders/{id}/driver-ack` 之后，它出现在 `ACCEPTED`、从 `DISPATCHED` 消失；
5. 收尾：把探针建的单软删（`DELETE /orders/{id}`，派单员），不留脏数据。

用法：python _tools/qa/_probe_client_status_queries.py
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import uuid

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

BASE = "http://127.0.0.1:8000/api/v1"
DISPATCHER = ("13800000001", "123321")
DRIVER_PHONE = "13800000003"

fails: list[str] = []
passes = 0


def call(method: str, path: str, token: str | None = None, body: dict | None = None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(raw) if raw else None), dict(r.headers)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw), dict(e.headers)
        except json.JSONDecodeError:
            return e.code, raw, dict(e.headers)


def ok(label: str, cond: bool, detail: str = "") -> None:
    global passes
    if cond:
        passes += 1
        print(f"  [OK]   {label}")
    else:
        fails.append(label + (f" —— {detail}" if detail else ""))
        print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))


def login(phone: str, password: str = "123321") -> str:
    st, data, _ = call("POST", "/auth/login", body={"phone": phone, "password": password})
    if st != 200 or not isinstance(data, dict):
        raise SystemExit(f"登录 {phone} 失败：{st} {data}")
    return data["access_token"]


def main() -> int:
    dtok = login(*DISPATCHER)

    # ⚠️ 用 `q=` 找这个司机，而不是拉整册：`GET /users` 的 `limit` 缺省 100、上限 500，
    #    而本机库里有 482 个司机 —— 不检索就会"名册里没有这个人"（这正是 H5/App 那边
    #    「指派弹层只列出前 N 个」的同一个坑，本轮的 H2 记录在案）。
    st, drivers, _ = call("GET", f"/users?role=driver&q={DRIVER_PHONE}", token=dtok)
    if st != 200:
        raise SystemExit(f"取司机名册失败：{st} {drivers}")
    driver = next((d for d in drivers if d.get("phone") == DRIVER_PHONE), None)
    if driver is None:
        raise SystemExit(f"司机名册里没有 {DRIVER_PHONE}（拿到 {len(drivers)} 条）")

    tag = uuid.uuid4().hex[:8]
    st, order, _ = call(
        "POST",
        "/orders",
        token=dtok,
        body={
            "lines": [
                {"product_name_snapshot": f"探针商品-{tag}", "quantity": 1, "unit_price": "10.00"}
            ],
            "delivery_description": "H5 状态查询探针",
            "address_detail": f"探针地址 {tag} 号",
            # 派单员代下单必须有归属：这里用临时货主称呼（不建账号，收尾不用清理）
            "temp_shipper_name": f"H1探针-{tag}",
        },
    )
    if st not in (200, 201):
        raise SystemExit(f"建单失败：{st} {order}")
    oid = order["id"]
    print(f"探针订单 #{oid} {order['order_no']}（派单员代下单）")

    try:
        st, _, _ = call(
            "POST",
            f"/orders/{oid}/assign",
            token=dtok,
            body={"driver_id": driver["id"], "internal_note": "H1 探针"},
        )
        ok("派单成功（订单进入 DISPATCHED）", st == 200, f"HTTP {st}")

        dtoken = login(DRIVER_PHONE)
        st, dispatched, _ = call("GET", "/orders?status=DISPATCHED", token=dtoken)
        ok("司机按 H5 的第一条查询能拿到这张单（修好之前查不到）",
           st == 200 and any(o["id"] == oid for o in dispatched), f"HTTP {st}")
        mine = next((o for o in dispatched if o["id"] == oid), None)
        if mine:
            ok("它被标成「司机的新单」（H5 的感叹号与接单按钮靠这个字段）",
               mine.get("is_new_for_driver") is True, f"实际 {mine.get('is_new_for_driver')}")
            ok("司机的列表里带 driver_phone/司机名（卡片要显示）",
               bool(mine.get("driver_phone")), f"driver_phone={mine.get('driver_phone')}")
        else:
            fails.append("司机没拿到这张单，后面两条判据无从谈起")

        st, accepted, _ = call("GET", "/orders?status=ACCEPTED", token=dtoken)
        ok("此时 ACCEPTED 里没有它（两档不重叠，合并后恰好一张）",
           st == 200 and not any(o["id"] == oid for o in accepted))

        st, acked, _ = call("POST", f"/orders/{oid}/driver-ack", token=dtoken)
        ok("司机确认接单成功", st == 200, f"HTTP {st} {acked if st != 200 else ''}")

        st, dispatched2, _ = call("GET", "/orders?status=DISPATCHED", token=dtoken)
        st2, accepted2, _ = call("GET", "/orders?status=ACCEPTED", token=dtoken)
        ok("接单后它从 DISPATCHED 消失", not any(o["id"] == oid for o in dispatched2))
        ok("接单后它出现在 ACCEPTED（H5「完成订单」的前提）",
           any(o["id"] == oid for o in accepted2))
    finally:
        st, _, _ = call("DELETE", f"/orders/{oid}", token=dtok)
        print(f"  清理：软删探针订单 #{oid} → HTTP {st}")

    print()
    if fails:
        print(f"❌ {len(fails)} 项不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {passes} 项通过：H5 的两条查询在真后端上确实拿得到「已派单」的单。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
