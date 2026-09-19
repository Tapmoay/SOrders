"""真机三端 E2E 的后半段（司机侧）：补运费 → 接单 → 送达（收现金）→ 核对不变量。

前半段是**真的在模拟器上点的**：货主端 UI 下单（订单 1145 / SO202609186443056346）、
派单员端 **AI 助手**生成确认卡并确认派单（driver 68）。这里接着用 API 完成司机侧
（App 调的是同一批端点），最后再回设备上核对两端的显示。
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:8000/api/v1"
OID = 1145
DRIVER = ("13820000001", "pass12345")     # 测试司机001（PIECE）
DISPATCHER = ("13800000001", "123321")


def call(method: str, path: str, body=None, token: str | None = None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


ok = True


def check(label: str, cond: bool, detail: str = "") -> None:
    global ok
    print(("  [通过] " if cond else "  [!!]   ") + label + ("" if cond else f" —— {detail}"))
    ok = ok and cond


tok_d = call("POST", "/auth/login", {"phone": DISPATCHER[0], "password": DISPATCHER[1]})[1]["access_token"]
tok_v = call("POST", "/auth/login", {"phone": DRIVER[0], "password": DRIVER[1]})[1]["access_token"]

st, prod = call("GET", "/products?include_inactive=true", token=tok_d)
st, order = call("GET", f"/orders/{OID}", token=tok_d)
pid = order["order_products"][0]["product_id"]
qty = int(order["order_products"][0]["quantity"])
st, p0 = call("GET", f"/products/{pid}", token=tok_d)
stock0 = int(p0["stock"])
print(f"  订单 {order['order_no']}｜商品 {pid} × {qty}｜送达前库存 {stock0}｜状态 {order['status']}")

# ① 派单员补运费（AI 派单时没给，它自己提示过）
st, r = call("POST", f"/orders/{OID}/freight", {"freight_fee": "100.00"}, token=tok_d)
check("派单员补录运费 100", st == 200, f"{st} {r}")

# ② 司机接单 + 送达（收现金）
st, r = call("POST", f"/orders/{OID}/driver-ack", token=tok_v)
check("司机接单", st == 200, f"{st} {r}")
st, r = call("POST", f"/orders/{OID}/complete",
             {"delivery_photo_urls": ["/static/uploads/delivery/e2e-ui.jpg"], "payment": "cash"}, token=tok_v)
check("司机送达（现场收现金）", st == 200, f"{st} {r}")

# ③ 核对不变量
st, order2 = call("GET", f"/orders/{OID}", token=tok_d)
check("订单变成已送达", order2["status"] == "DELIVERED", order2["status"])
check("标记为已收款（现金）", bool(order2["paid"]) and order2["payment_method"] == "cash",
      f"paid={order2['paid']} method={order2['payment_method']}")

st, p1 = call("GET", f"/products/{pid}", token=tok_d)
check(f"库存真的扣了 {qty} 件", int(p1["stock"]) == stock0 - qty, f"{stock0} → {p1['stock']}")

st, bills = call("GET", f"/driver-bills?driver_id=68", token=tok_d)
mine = [b for b in (bills or []) if b.get("order_id") == OID]
check("生成了一条司机账单（PIECE，无规则=全额运费）",
      len(mine) == 1 and abs(float(mine[0]["amount"]) - 100.0) < 0.005,
      f"{[(b['id'], b['amount']) for b in mine]}")

st, msgs = call("GET", f"/notifications?days=1", token=tok_d)
titles = [m.get("title", "") for m in (msgs or [])][:6]
check("落了一条送达相关站内信（货主/派单员可查）", len(titles) > 0, f"{titles}")

print("\n" + ("全部通过 ✅" if ok else "有未通过项 ❌"))
sys.exit(0 if ok else 1)
