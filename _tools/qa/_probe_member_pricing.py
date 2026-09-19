"""真后端实测：**批发商专属价这条链在真接口上是通的**（2026-09-19 审计 H4 的前提）。

## 为什么要有它
H5 下单页原来的缺陷是「不读 `/price-rules`，一律用默认价」——修法是让下单页读它。
但"读了就有效吗"是另一件事，静态红线看不出来：
- 货主账号调 `GET /price-rules` 到底拿不拿得到自己的专属价（`price_rules.py` 里那段
  `if user_role_key(user) == "shipper": q = q.where(PriceRule.shipper_id == user.id)`）？
- 客户端按专属价下的单，落库之后**单价真的是那个数**吗（后端会不会重算/忽略）？

所以这里走真链路：**货主**读自己的价 → 用专属价下单 → 读回订单核对单价 → 软删探针单。

判据：
1. 货主读到的是**只有自己的**规则（别人的一条都不能出现）；
2. 规则里的 `special_unit_price` 与商品默认价不同（否则这条测试证明不了什么，直接跳过）；
3. 用专属价下的单，落库单价**等于专属价**（不是默认价）；
4. 收尾：软删探针订单（`DELETE /orders/{id}`，货主自己删）。

用法：python _tools/qa/_probe_member_pricing.py
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import uuid

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

BASE = "http://127.0.0.1:8000/api/v1"
#: 本机开发库里挂了专属价的会员货主（`price_rules` 实测：商品 38 默认 64、专属 55）
SHIPPER = ("13800000002", "123321")

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
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def ok(label: str, cond: bool, detail: str = "") -> None:
    global passes
    if cond:
        passes += 1
        print(f"  [OK]   {label}")
    else:
        fails.append(label + (f" —— {detail}" if detail else ""))
        print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))


def login(phone: str, password: str) -> str:
    st, data = call("POST", "/auth/login", body={"phone": phone, "password": password})
    if st != 200 or not isinstance(data, dict):
        raise SystemExit(f"登录 {phone} 失败：{st} {data}")
    return data["access_token"]


def main() -> int:
    stok = login(*SHIPPER)
    st, me = call("GET", "/users/me", token=stok)
    if st != 200:
        raise SystemExit(f"取当前用户失败：{st} {me}")
    my_id = int(me["id"])
    print(f"货主 id={my_id}（{me.get('full_name')}）")

    st, rules = call("GET", "/price-rules", token=stok)
    if st != 200 or not isinstance(rules, list):
        raise SystemExit(f"取专属价失败：{st} {rules}")
    print(f"读到专属价 {len(rules)} 条")
    ok("货主只拿得到自己的专属价（别人的一条都不该出现）",
       all(int(r.get("shipper_id") or 0) == my_id for r in rules),
       f"混进了别人的：{sorted({r.get('shipper_id') for r in rules} - {my_id})}")

    # 找一个"专属价 != 默认价"的商品，否则这次测试证明不了什么
    st, products = call("GET", "/products", token=stok)
    if st != 200 or not isinstance(products, list):
        raise SystemExit(f"取商品失败：{st}")
    by_id = {int(p["id"]): p for p in products}
    target = None
    for r in rules:
        pid = int(r["product_id"])
        p = by_id.get(pid)
        if p is None:
            continue
        special = float(r["special_unit_price"])
        default = float(p.get("default_unit_price") or 0)
        if special != default:
            target = (pid, p, special, default)
            break
    if target is None:
        print("\n⚠️ 本机没有「专属价 != 默认价」的可用商品 —— 这条探针这次证明不了什么（不是失败）")
        print(f"✅ 已验的部分：{passes} 项（货主读价的隔离性）")
        return 0 if not fails else 1

    pid, product, special, default = target
    print(f"靶子商品 #{pid} {product.get('name')}：默认 ¥{default} → 专属 ¥{special}")

    tag = uuid.uuid4().hex[:8]
    st, order = call(
        "POST",
        "/orders",
        token=stok,
        body={
            "lines": [
                {
                    "product_id": pid,
                    "product_name_snapshot": product.get("name") or f"探针商品-{tag}",
                    "quantity": 2,
                    "unit_price": special,
                    "line_total": special * 2,
                }
            ],
            "delivery_description": "专属价探针",
            "address_detail": f"专属价探针地址 {tag} 号",
            "contact_dongjia_phone": "13800000000",
        },
    )
    if st not in (200, 201):
        raise SystemExit(f"下单失败：{st} {order}")
    oid = int(order["id"])
    print(f"探针订单 #{oid} {order.get('order_no')}（按专属价 ¥{special} 下的）")

    try:
        line = (order.get("order_products") or [{}])[0]
        got = float(line.get("unit_price") or 0)
        ok("按专属价下的单，落库单价就是专属价（不是默认价）",
           abs(got - special) < 0.005, f"落库 {got}，期望 {special}")
        st2, again = call("GET", f"/orders/{oid}", token=stok)
        if st2 == 200:
            got2 = float((again.get("order_products") or [{}])[0].get("unit_price") or 0)
            ok("重新读回来还是这个价（没有被后端重算）",
               abs(got2 - special) < 0.005, f"读回 {got2}")
    finally:
        # ⚠️ 清理必须**按真实规则**走：货主只能删「已送达/已撤销/异常」的单
        #    （`orders.delete_cancelled_order` 里那道门），刚下的单是 `PENDING_DISPATCH` →
        #    直接 DELETE 会 400，探针就留下了一张脏单（第一次跑就踩到了）。
        #    正确顺序：先撤销 → 再删；撤销失败就退回用派单员身份删（派单员可删任意状态）。
        cleanup = "未清理"
        st_c, _ = call("POST", f"/orders/{oid}/cancel", token=stok)
        if st_c == 200:
            st_d, _ = call("DELETE", f"/orders/{oid}", token=stok)
            cleanup = f"撤销+软删（{st_c}/{st_d}）" if st_d in (200, 204) else f"撤销成功但删除失败 {st_d}"
        else:
            dtok = login("13800000001", "123321")
            st_d, _ = call("DELETE", f"/orders/{oid}", token=dtok)
            cleanup = f"派单员软删（{st_d}）" if st_d in (200, 204) else f"派单员删除也失败 {st_d}"
        print(f"  清理：探针订单 #{oid} → {cleanup}")
        ok("探针自己建的订单清理干净了（不留脏数据）", "失败" not in cleanup and "未清理" not in cleanup,
           cleanup)

    print()
    if fails:
        print(f"❌ {len(fails)} 项不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {passes} 项通过：货主读得到自己的专属价，按它下单落库也是这个价。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
