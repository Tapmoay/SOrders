"""核心业务逻辑探针（缺陷挖掘用）：**只读探针 + 明确的写后即清**。

## 这个脚本的定位
它不是单元测试，是"**以攻击者的方式问业务问题**"：把边界值、缺字段、跨字段不一致、
不该允许的状态组合挨个打一遍，然后把"能过"的那些挑出来人工判断——
因为这里绝大多数缺陷的表现都是**接口 200、数据落库、界面上看不出来**。

## 使用
```
python _tools/qa/_probe_core_flows.py            # 跑全部
python _tools/qa/_probe_core_flows.py 商品         # 只跑某一组（前缀匹配）
```
每条打印：`[通过]`=按预期被拒/行为正确；`[!!]`=**可疑**（放行了不该放行的、或结果不符预期）。
脚本自己清理建出来的数据（软删商品 / 软删订单），不删别人的数据。
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
import random
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

BASE = "http://127.0.0.1:8000/api/v1"
ROOT = Path(__file__).resolve().parents[2]

DISPATCHER = ("13800000001", "123321")
SHIPPER = ("13800000002", "123321")
DRIVER = ("13800000003", "123321")

FINDINGS: list[str] = []

#: 探针自己建出来的账号（收尾时软删掉）。见 [cleanup_created] 的理由。
CREATED_USERS: list[int] = []


def cleanup_created(tok: str) -> None:
    """收掉探针自己建的账号（**软删**，语义与 `DELETE /users/{id}` 相同）。

    ⚠️ 为什么要收：每跑一次这个脚本会建 ~11 个账号（司机/货主/批发商），而它原来一个都不删。
    跑十几轮之后库里攒了 **158 个「探针*」账号**——后果不是占空间，是**把数字搅浑**：
    用户管理/司机名册/货主名册里全是假账号，AI 验收要的"30 个货主 / 8 个司机"得重新数。
    这些账号被订单/账单引用，所以只能软删（硬删会留下指向空号的账单与订单）。
    恢复：`POST /users/{id}/restore`。
    """
    if not CREATED_USERS:
        return
    done = 0
    for uid in CREATED_USERS:
        st, _ = call("DELETE", f"/users/{uid}?hard=false", token=tok)
        done += 1 if st in (200, 204) else 0
    print(f"\n  [清理] 探针账号 {done}/{len(CREATED_USERS)} 个已软删"
          f"（被订单/账单引用着，硬删会留孤儿行；要恢复走 POST /users/{{id}}/restore）")


def call(method: str, path: str, body=None, token: str | None = None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        method=method,
        headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def login(cred) -> str:
    _, r = call("POST", "/auth/login", {"phone": cred[0], "password": cred[1]})
    return r["access_token"]


def ok(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  [通过] {label}")
    else:
        print(f"  [!!]   {label} —— {detail}")
        FINDINGS.append(f"{label} —— {detail}")


def uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


# ------------------------------------------------------------------ 商品域

def probe_products(tok: str) -> None:
    print("\n== 商品创建/编辑：边界与异常值 ==")

    st, r = call("POST", "/products", {"name": uniq("负价商品"), "default_unit_price": "-5"}, token=tok)
    if st == 201:
        # 建出来了就立刻清掉，别留在商品目录里
        call("DELETE", f"/products/{r['id']}", token=tok)
    ok("商品默认单价不允许负数", st != 201,
       f"201 建出了单价 {r.get('default_unit_price') if isinstance(r, dict) else r} 的商品（下单时会算出负数金额）")

    st, r = call("POST", "/products", {"name": uniq("负成本商品"), "cost_price": "-3"}, token=tok)
    if st == 201:
        call("DELETE", f"/products/{r['id']}", token=tok)
    ok("商品成本价不允许负数", st != 201, f"201 建出了成本价 {r.get('cost_price') if isinstance(r, dict) else r} 的商品（毛利会算错）")

    st, r = call("POST", "/products", {"name": "   "}, token=tok)
    if st == 201:
        call("DELETE", f"/products/{r['id']}", token=tok)
    ok("商品名不能是纯空格", st != 201, f"201 建出了名字是空格的商品（列表里一行空白，点进去才知道是什么）")

    name = uniq("重名商品")
    st1, p1 = call("POST", "/products", {"name": name}, token=tok)
    st2, p2 = call("POST", "/products", {"name": name}, token=tok)
    for p in (p1, p2):
        if isinstance(p, dict) and p.get("id"):
            call("DELETE", f"/products/{p['id']}", token=tok)
    print(f"  [信息] 同名商品两次创建：{st1} / {st2}"
          + ("（允许，靠 id 区分）" if st2 == 201 else "（拒绝）"))

    st, r = call("POST", "/products", {"name": uniq("档位重复"), "tier_prices": [
        {"label": "批发", "unit_price": "9"}, {"label": "批发", "unit_price": "8"}]}, token=tok)
    if st == 201:
        call("DELETE", f"/products/{r['id']}", token=tok)
    print(f"  [信息] 同名档位两次：{st}"
          + ("（允许——但界面上两个'批发'档，选哪个看不出来）" if st == 201 else "（拒绝）"))

    st, r = call("POST", "/products", {"name": uniq("下架测试")}, token=tok)
    pid = r["id"]
    st2, _ = call("PATCH", f"/products/{pid}", {"is_active": False}, token=tok)
    st3, lst = call("GET", "/products?include_inactive=true", token=tok_get(SHIPPER))
    seen = any(x["id"] == pid for x in (lst or [])) if isinstance(lst, list) else False
    if st3 == 200 and seen:
        print("  [信息] 货主请求 include_inactive=true 时能看到下架商品（会不会能下单？见下条）")
    call("DELETE", f"/products/{pid}", token=tok)


def tok_get(cred) -> str:
    return login(cred)


# ------------------------------------------------------------------ 下单金额

def probe_order_math(tok: str) -> None:
    print("\n== 下单：金额口径与跨字段一致性 ==")
    shipper = login(SHIPPER)

    st, p = call("POST", "/products", {"name": uniq("探针商品"), "default_unit_price": "10"}, token=tok)
    pid = p["id"]

    # ① line_total 与 单价×数量 不一致
    st, o = call("POST", "/orders", {
        "lines": [{"product_id": pid, "product_name_snapshot": "探针货", "quantity": 3,
                   "unit_price": "10.00", "line_total": "1.00"}],
        "delivery_description": "探针：行金额与单价不符",
    }, token=shipper)
    if st == 201:
        line = o["order_products"][0]
        ok("行金额与「单价×数量」不一致时应当拒绝或按算出来的值存",
           float(line["line_total"]) == 30.0,
           f"落库的 line_total={line['line_total']}，而 3×10=30（账本/营业额按行金额入账，两边就分叉了）")
        call("DELETE", f"/orders/{o['id']}", token=tok)
    else:
        print(f"  [通过] 行金额与单价不符被拒（{st}）")

    # ② 不存在的商品编号
    st, o = call("POST", "/orders", {
        "lines": [{"product_id": 99999999, "product_name_snapshot": "不存在的商品", "quantity": 1,
                   "unit_price": "10.00", "line_total": "10.00"}],
        "delivery_description": "探针：不存在的商品编号",
    }, token=shipper)
    if st == 201:
        print("  [信息] 不存在的 product_id 被接受（手工行本来就允许没有商品，成本快照为 0 → 毛利按 0 成本算）")
        call("DELETE", f"/orders/{o['id']}", token=tok)
    else:
        print(f"  [通过] 不存在的 product_id 被拒（{st}）")

    # ③ 已删除的商品还能下单吗
    st, p2 = call("POST", "/products", {"name": uniq("待删商品"), "default_unit_price": "10"}, token=tok)
    pid2 = p2["id"]
    call("DELETE", f"/products/{pid2}", token=tok)
    st, o = call("POST", "/orders", {
        "lines": [{"product_id": pid2, "product_name_snapshot": "已删商品", "quantity": 1,
                   "unit_price": "10.00", "line_total": "10.00"}],
        "delivery_description": "探针：已删商品下单",
    }, token=shipper)
    if st == 201:
        ok("已删除的商品不该能下单（商品都从目录里消失了）", False,
           f"201 接受了下单（订单 #{o['id']}）——货主可以用一个已经删掉的商品建单")
        call("DELETE", f"/orders/{o['id']}", token=tok)
    else:
        print(f"  [通过] 已删商品下单被拒（{st}）")

    # ④ 数量 0 / 负数（schema 是 ge=1，这里确认真的被拦）
    for qty in (0, -1):
        st, _ = call("POST", "/orders", {
            "lines": [{"product_id": pid, "product_name_snapshot": "数量探针", "quantity": qty,
                       "unit_price": "10.00"}],
            "delivery_description": f"探针：数量 {qty}",
        }, token=shipper)
        ok(f"数量 {qty} 被拒（422 也算拒）", st != 201, f"居然返回 {st}")

    # ⑤ 空行
    st, _ = call("POST", "/orders", {"lines": [], "delivery_description": "探针：空行"}, token=shipper)
    ok("订单至少一行商品", st != 201, f"居然返回 {st}")

    call("DELETE", f"/products/{pid}", token=tok)


def _mk_driver(tok: str, name: str = "探针司机") -> tuple[int, str]:
    """建一个司机并登录，返回 (id, token)。手机号随机，避免撞已有账号。"""
    phone = "13" + "".join(random.choice("0123456789") for _ in range(9))
    st, r = call("POST", "/users", {"phone": phone, "password": "123321",
                                    "full_name": name, "role": "driver", "vehicle_type": "trailer"}, token=tok)
    if st not in (200, 201):
        raise RuntimeError(f"建司机失败 {st}: {r}")
    CREATED_USERS.append(int(r["id"]))
    st, r2 = call("POST", "/auth/login", {"phone": phone, "password": "123321"})
    return int(r["id"]), r2["access_token"]


def _mk_order_with_line(shipper: str, pid: int | None = None) -> int:
    line = {"product_name_snapshot": "状态机探针货", "quantity": 1, "unit_price": "10.00", "line_total": "10.00"}
    if pid:
        line["product_id"] = pid
    st, o = call("POST", "/orders", {"lines": [line], "delivery_description": "状态机探针"}, token=shipper)
    assert st == 201, o
    return int(o["id"])


# ------------------------------------------------------------------ 状态机

def probe_state_machine(tok: str) -> None:
    print("\n== 状态机：非法跃迁与越权 ==")
    shipper = login(SHIPPER)
    d1, t1 = _mk_driver(tok, "探针司机甲")
    d2, t2 = _mk_driver(tok, "探针司机乙")

    def status(oid: int) -> str:
        _, o = call("GET", f"/orders/{oid}", token=tok)
        return o.get("status") if isinstance(o, dict) else f"?{o}"

    def assign(oid: int, did: int):
        return call("POST", f"/orders/{oid}/assign", {"driver_id": did, "freight_fee": "50.00"}, token=tok)

    # ① 待派单：别人（没被派的司机）能不能接单 / 直接送达
    oid = _mk_order_with_line(shipper)
    st, r = call("POST", f"/orders/{oid}/driver-ack", token=t2)
    ok("还没派单时，司机不能接单", st != 200, f"返回 {st} {r}")
    st, r = call("POST", f"/orders/{oid}/complete", {"delivery_photo_urls": ["/static/uploads/delivery/x.jpg"]}, token=t2)
    ok("还没派单时，司机不能送达", st != 200, f"返回 {st} {r}")

    # ② 派给甲之后，乙能不能接单 / 送达（越权）
    st, _ = assign(oid, d1)
    assert st == 200, "派单应成功"
    st, r = call("POST", f"/orders/{oid}/driver-ack", token=t2)
    ok("派给甲的单，乙不能接单", st != 200, f"返回 {st} {r}")
    st, r = call("POST", f"/orders/{oid}/complete", {"delivery_photo_urls": ["/static/uploads/delivery/x.jpg"]}, token=t2)
    ok("派给甲的单，乙不能送达", st != 200, f"返回 {st} {r}")

    # ③ 同一单派两次
    st, r = assign(oid, d2)
    ok("已经派出去的单不能再派一次", st != 200, f"返回 {st} {r}（会把第一个司机挤掉）")

    # ④ 甲接单后：撤回、撤销、再送达两次
    st, _ = call("POST", f"/orders/{oid}/driver-ack", token=t1)
    ok("被派的司机能接单", st == 200, f"返回 {st}")
    st, _ = call("POST", f"/orders/{oid}/complete",
                 {"delivery_photo_urls": ["/static/uploads/delivery/ok.jpg"]}, token=t1)
    ok("接单后能送达", st == 200, f"返回 {st}")
    st, r = call("POST", f"/orders/{oid}/complete",
                 {"delivery_photo_urls": ["/static/uploads/delivery/ok2.jpg"]}, token=t1)
    ok("已送达的单不能再送达一次（会重复出账）", st != 200, f"返回 {st} {r}")
    st, r = call("POST", f"/orders/{oid}/recall", {"reason": "探针：送达后再撤回"}, token=tok)
    ok("已送达的单不能撤回派单", st != 200, f"返回 {st} {r}")
    st, r = call("POST", f"/orders/{oid}/cancel", token=tok)
    ok("已送达的单不能撤销", st != 200, f"返回 {st} {r}")

    # ⑤ 已撤销的单：接单/送达/派单
    oid2 = _mk_order_with_line(shipper)
    st, r = call("POST", f"/orders/{oid2}/cancel", token=tok)
    ok("待派单的单能撤销", st == 200, f"返回 {st} {r}")
    st, r = assign(oid2, d1)
    ok("已撤销的单不能再派单", st != 200, f"返回 {st} {r}")
    st, r = call("POST", f"/orders/{oid2}/driver-ack", token=t1)
    ok("已撤销的单不能接单", st != 200, f"返回 {st} {r}")

    # ⑥ 已接单（司机在途）能不能撤回 —— 业务上允许（改派），但要能说清原司机收到什么
    oid3 = _mk_order_with_line(shipper)
    assign(oid3, d1)
    call("POST", f"/orders/{oid3}/driver-ack", token=t1)
    st, r = call("POST", f"/orders/{oid3}/recall", {"reason": "探针：在途改派"}, token=tok)
    ok("已接单（在途）的单可以撤回改派", st == 200, f"返回 {st} {r}")
    ok("撤回后回到待派单", status(oid3) == "PENDING_DISPATCH", f"实际 {status(oid3)}")
    st, r = call("POST", f"/orders/{oid3}/driver-ack", token=t1)
    ok("撤回之后原司机不能再接单（已经没派给他了）", st != 200, f"返回 {st} {r}")

    # ⑦ 司机能不能自己撤销/改派（角色越权）
    oid4 = _mk_order_with_line(shipper)
    assign(oid4, d1)
    st, r = call("POST", f"/orders/{oid4}/cancel", token=t1)
    ok("司机不能撤销订单", st != 200, f"返回 {st} {r}")
    st, r = call("POST", f"/orders/{oid4}/assign", {"driver_id": d2}, token=t1)
    ok("司机不能改派给别人", st != 200, f"返回 {st} {r}")
    st, r = call("POST", f"/orders/{oid4}/assign", {"driver_id": d2}, token=shipper)
    ok("货主不能把别人的单改派", st != 200, f"返回 {st} {r}")

    # 收尾：把探针建出来的单都撤销掉，不留垃圾在待派池里
    for o in (oid, oid3, oid4):
        if status(o) in ("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED"):
            call("POST", f"/orders/{o}/cancel", token=tok)


# ------------------------------------------------------------------ 库存

def probe_inventory(tok: str) -> None:
    print("\n== 库存：预占/实扣/回库 三步账对不对得上 ==")
    shipper = login(SHIPPER)
    d1, t1 = _mk_driver(tok, "库存探针司机")
    st, p = call("POST", "/products", {"name": uniq("库存探针"), "default_unit_price": "10", "stock": 10}, token=tok)
    pid = p["id"]

    def stock() -> float:
        _, row = call("GET", f"/products/{pid}", token=tok)
        return float(row["stock"])

    def order(qty: int) -> int:
        st, o = call("POST", "/orders", {"lines": [{
            "product_id": pid, "product_name_snapshot": "库存探针货", "quantity": qty,
            "unit_price": "10.00", "line_total": str(10 * qty)}],
            "delivery_description": "库存探针"}, token=shipper)
        assert st == 201, o
        return int(o["id"])

    ok("创建时库存 = 10", stock() == 10, f"实际 {stock()}")

    # ① 派单只是预占：实际库存不动
    oid = order(3)
    call("POST", f"/orders/{oid}/assign", {"driver_id": d1}, token=tok)
    ok("派单只是预占，实际库存不动", stock() == 10, f"派单后库存 {stock()}（预占不该改实际库存）")

    # ② 送达才真正扣
    call("POST", f"/orders/{oid}/driver-ack", token=t1)
    call("POST", f"/orders/{oid}/complete", {"delivery_photo_urls": ["/static/uploads/delivery/inv.jpg"]}, token=t1)
    ok("送达后真正扣库存（10-3=7）", stock() == 7, f"送达后库存 {stock()}")

    # ③ 派单 → 撤回 → 再派 → 送达：不能因为"撤回补了一条回库流水"就多出来
    oid2 = order(2)
    call("POST", f"/orders/{oid2}/assign", {"driver_id": d1}, token=tok)
    call("POST", f"/orders/{oid2}/recall", {"reason": "库存探针：撤回"}, token=tok)
    ok("撤回派单不动实际库存（本来就没扣）", stock() == 7, f"撤回后库存 {stock()}")
    call("POST", f"/orders/{oid2}/assign", {"driver_id": d1}, token=tok)
    call("POST", f"/orders/{oid2}/driver-ack", token=t1)
    call("POST", f"/orders/{oid2}/complete", {"delivery_photo_urls": ["/static/uploads/delivery/inv2.jpg"]}, token=t1)
    ok("撤回再派再送达：只扣一次（7-2=5）", stock() == 5, f"实际 {stock()}")

    # ④ 派单 → 撤销：不能把没扣过的库存"还"出来
    oid3 = order(1)
    call("POST", f"/orders/{oid3}/assign", {"driver_id": d1}, token=tok)
    call("POST", f"/orders/{oid3}/cancel", token=tok)
    ok("撤销一张只派过、没送达的单，库存不变（不许虚增）", stock() == 5, f"撤销后库存 {stock()}")

    # ⑤ 超卖：下单 100 件（库存只有 5）——能不能派、送达后库存是多少
    oid4 = order(100)
    st, _ = call("POST", f"/orders/{oid4}/assign", {"driver_id": d1}, token=tok)
    call("POST", f"/orders/{oid4}/driver-ack", token=t1)
    call("POST", f"/orders/{oid4}/complete", {"delivery_photo_urls": ["/static/uploads/delivery/inv3.jpg"]}, token=t1)
    print(f"  [信息] 超卖：下单 100 件（库存 5）派单 {st} → 送达后库存 {stock()}（负数=允许，但要知道会发生）")
    if stock() < 0:
        FINDINGS.append(
            f"超卖会走到负库存（{stock()}）：目前**下单/派单都不拦**，只有送达那天账上才知道"
            " —— 需要产品拍板是「下单就拦」还是「允许负库存」"
        )

    call("DELETE", f"/products/{pid}", token=tok)


# ------------------------------------------------------------------ 权限边界

def probe_permissions(tok: str) -> None:
    print("\n== 权限边界：越权读别人的数据 / 越权写 ==")
    shipper_a = login(SHIPPER)
    d1, t1 = _mk_driver(tok, "权限探针司机甲")
    d2, t2 = _mk_driver(tok, "权限探针司机乙")

    # 第二个货主（用来测"看到别人的单"）
    phone = "13" + "".join(random.choice("0123456789") for _ in range(9))
    st, sb = call("POST", "/users", {"phone": phone, "password": "123321", "full_name": "权限探针货主乙",
                                     "role": "shipper"}, token=tok)
    if st not in (200, 201):
        print(f"  [信息] 建第二个货主失败（{st}），跳过货主越权那两项")
        shipper_b = None
    else:
        CREATED_USERS.append(int(sb["id"]))
        shipper_b = call("POST", "/auth/login", {"phone": phone, "password": "123321"})[1]["access_token"]

    # A 的单
    st, o = call("POST", "/orders", {"lines": [{"product_name_snapshot": "权限探针货", "quantity": 1,
                                                "unit_price": "10.00", "line_total": "10.00"}],
                                     "delivery_description": "权限探针"}, token=shipper_a)
    oid = int(o["id"])
    call("POST", f"/orders/{oid}/assign", {"driver_id": d1, "freight_fee": "30.00"}, token=tok)
    call("POST", f"/orders/{oid}/driver-ack", token=t1)
    call("POST", f"/orders/{oid}/complete", {"delivery_photo_urls": ["/static/uploads/delivery/perm.jpg"]}, token=t1)

    if shipper_b:
        st, r = call("GET", f"/orders/{oid}", token=shipper_b)
        ok("货主乙看不到货主甲的单（按编号直接访问）", st in (403, 404), f"返回 {st}：{str(r)[:120]}")
        st, r = call("GET", "/orders", token=shipper_b)
        leaked = [x for x in (r if isinstance(r, list) else [])
                  if x.get("shipper_id") not in (None, 0) and x.get("id") == oid]
        ok("货主乙的订单列表里没有货主甲的单", not leaked, f"列表里出现了 #{oid}")

        # 司机甲的账单：货主乙能不能看到钱
        st, r = call("GET", f"/driver-bills?driver_id={d1}", token=shipper_b)
        ok("货主看不到司机账单", st in (403, 404), f"返回 {st}：{str(r)[:120]}")

    # 司机乙读司机甲的账单 / 结算
    st, r = call("GET", f"/driver-bills?driver_id={d1}", token=t2)
    if st == 200 and isinstance(r, list):
        foreign = [b for b in r if b.get("driver_id") != d2]
        ok("司机看不到别的司机的账单", not foreign,
           f"司机乙读到了 {len(foreign)} 条不属于他的账单（第一条 driver_id={foreign[0].get('driver_id') if foreign else '-'}）")
    else:
        print(f"  [信息] 司机读账单接口返回 {st}（拒绝也算对）")

    st, r = call("GET", f"/freight-settlement?driver_id={d1}", token=t2)
    if st == 200 and isinstance(r, dict):
        groups = r.get("groups") or r.get("drivers") or []
        foreign = [g for g in groups if g.get("driver_id") not in (None, d2)]
        ok("司机看不到别人的运费结算", not foreign, f"司机乙读到了 {len(foreign)} 个别人的结算分组")
    else:
        print(f"  [信息] 司机读运费结算返回 {st}")

    # 越权写：司机/货主改商品、改计费规则、看报表
    for label, method, path, body, tokx in (
        ("货主不能建商品", "POST", "/products", {"name": "越权商品"}, shipper_a),
        ("司机不能建商品", "POST", "/products", {"name": "越权商品"}, t1),
        ("货主不能看司机计费规则", "GET", "/driver-billing-rules", None, shipper_a),
        ("司机不能看司机计费规则", "GET", "/driver-billing-rules", None, t1),
        ("货主不能看库存", "GET", "/inventory/summary", None, shipper_a),
        ("司机不能看报表", "GET", "/reports/turnover", None, t1),
        ("货主不能建账号", "POST", "/users", {"phone": "13000000000", "password": "x1234567",
                                              "full_name": "越权", "role": "driver"}, shipper_a),
    ):
        st, r = call(method, path, body, token=tokx)
        ok(f"{label}", st in (401, 403, 404), f"返回 {st}：{str(r)[:100]}")


# ------------------------------------------------------------------ 账本与收款

def probe_money(tok: str) -> None:
    print("\n== 账本与收款：核销口径、重复核销、报表口径 ==")
    shipper = login(SHIPPER)
    d1, t1 = _mk_driver(tok, "收款探针司机")

    _, me = call("GET", "/users/me", token=shipper)
    customer_id = None
    st, accounts = call("GET", "/ledger/accounts?kind=shipper", token=tok)
    if st == 200 and isinstance(accounts, list):
        # 账本里的"客户"是按 customer 档案来的：找到属于这个货主的那个
        for a in accounts:
            if a.get("shipper_id") == me.get("id") or a.get("customer_id"):
                customer_id = a.get("customer_id")
                break
    if customer_id is None:
        st, custs = call("GET", "/customers", token=tok)
        if st == 200 and isinstance(custs, list) and custs:
            mine = [c for c in custs if c.get("user_id") == me.get("id")]
            customer_id = (mine or custs)[0]["id"]
    if customer_id is None:
        print("  [跳过] 找不到可用的客户档案，跳过收款探针")
        return
    print(f"  [信息] 用客户档案 #{customer_id} 做收款探针")

    def turnover() -> dict:
        # ⚠️ 这个接口的 date 是**必填**的：不传会 422，而 422 的响应体里没有 collected
        #    —— 第一版探针没传，于是"已收"永远是 0，重复核销那条检查变成了 0 == 0 的恒真判断
        #    （探针自己也会踩"空转判据"这个坑）。
        _, r = call("GET", f"/reports/turnover?mode=day&date={date.today().isoformat()}", token=tok)
        return r if isinstance(r, dict) else {}

    def receipts_of(oid: int) -> list:
        _, rows = call("GET", "/ledger/receipts", token=tok)
        return [x for x in (rows or []) if oid in (x.get("order_ids") or [])]

    # 送达一张 100 元的单
    st, o = call("POST", "/orders", {"lines": [{"product_name_snapshot": "收款探针货", "quantity": 1,
                                                "unit_price": "100.00", "line_total": "100.00"}],
                                     "delivery_description": "收款探针"}, token=shipper)
    oid = int(o["id"])
    call("POST", f"/orders/{oid}/assign", {"driver_id": d1, "freight_fee": "30.00"}, token=tok)
    call("POST", f"/orders/{oid}/driver-ack", token=t1)
    call("POST", f"/orders/{oid}/complete", {"delivery_photo_urls": ["/static/uploads/delivery/pay.jpg"]}, token=t1)

    before = turnover()
    before_collected = float(before.get("collected") or 0)

    def receipt(amount: str, oids: list[int], mode: str = "itemized"):
        return call("POST", "/ledger/receipts", {
            "customer_id": customer_id, "amount": amount, "method": "cash",
            "settle_mode": mode, "order_ids": oids, "received_at": "2026-09-18",
        }, token=tok)

    # ① 金额对不上 → 拒
    st, r = receipt("50.00", [oid])
    ok("逐单核销金额与订单合计不符要拒", st != 200, f"返回 {st} {str(r)[:120]}")

    # ② 正确核销
    st, r = receipt("100.00", [oid])
    ok("逐单核销 100 元成功", st in (200, 201), f"返回 {st} {str(r)[:160]}")
    mid = turnover()
    mid_collected = float(mid.get("collected") or 0)
    print(f"  [信息] 已收：核销前 {before_collected} → 核销后 {mid_collected}")

    # ③ 同一张单再核销一次（现实里很常见：客户分两次给、或者手滑点了两下）
    n_before = len(receipts_of(oid))
    st2, r2 = receipt("100.00", [oid])
    n_after = len(receipts_of(oid))
    after = turnover()
    after_collected = float(after.get("collected") or 0)
    print(f"  [信息] 已收（报表）：核销后 {mid_collected} → 重复核销后 {after_collected}")
    ok("同一张单不能被核销两次（否则收款记录里同一张单出现两次，钱多记一笔）",
       n_after == n_before,
       f"第二次核销返回 {st2}，这张单的收款记录从 {n_before} 条变成 {n_after} 条：{r2}")

    # ④ 该单在收款记录里出现了几次（重复核销的直接证据）
    mine = receipts_of(oid)
    print(f"  [信息] 这张单出现在 {len(mine)} 条收款记录里（金额 {[x.get('amount') for x in mine]}）")

    # ⑤ 未送达的单能不能收款
    st, o2 = call("POST", "/orders", {"lines": [{"product_name_snapshot": "未送达探针货", "quantity": 1,
                                                 "unit_price": "20.00", "line_total": "20.00"}],
                                      "delivery_description": "未送达探针"}, token=shipper)
    oid2 = int(o2["id"])
    st, r = receipt("20.00", [oid2])
    print(f"  [信息] 给「还没派单」的单核销收款：返回 {st}（预收款业务上可能正当，但要知道会发生）")

    # ⑥ 收过款的单再撤销
    st, r = call("POST", f"/orders/{oid}/cancel", token=tok)
    print(f"  [信息] 已收款的「已送达」单撤销：返回 {st}（送达后本来就不许撤）")

    call("POST", f"/orders/{oid2}/cancel", token=tok)


# ------------------------------------------------------------------ 报表口径

def probe_reports(tok: str) -> None:
    """报表的"钱去哪了"必须闭合：营业额 = 已收 + 挂账（差额为 0）。

    做法是**看增量**而不是看绝对值：报表按窗口聚合全库的已送达单，
    直接比总数会被别的用例/历史数据搅乱。
    """
    print("\n== 报表口径：营业额 / 已收 / 挂账 三个数要闭合 ==")
    shipper = login(SHIPPER)
    d1, t1 = _mk_driver(tok, "报表探针司机")

    def snap() -> dict:
        # ⚠️ 锚点日期必须取**后端的"今天"**：后端的 _now() 是 UTC（`datetime.now(timezone.utc)`），
        #    而报表按 `delivered_at.date()` 落窗口。宿主在东八区时本地日期会比 UTC 早一天，
        #    用 `date.today()` 去查会**一条都查不到**（第一版就是这么"看不见自己刚送的单"的）。
        anchor = datetime.now(timezone.utc).date().isoformat()
        _, r = call("GET", f"/reports/turnover?mode=day&date={anchor}", token=tok)
        r = r if isinstance(r, dict) else {}
        return {
            "amount": float(r.get("total_amount") or 0),
            "collected": float(r.get("collected") or 0),
            "arrears": float(r.get("arrears_total") or 0),
        }

    def deliver(collect_cash: bool, payment: str | None, amount: str = "100.00") -> int:
        _, o = call("POST", "/orders", {"lines": [{"product_name_snapshot": "报表探针货", "quantity": 1,
                                                   "unit_price": amount, "line_total": amount}],
                                        "delivery_description": "报表探针"}, token=shipper)
        oid = int(o["id"])
        call("POST", f"/orders/{oid}/assign",
             {"driver_id": d1, "freight_fee": "30.00", "collect_cash": collect_cash}, token=tok)
        call("POST", f"/orders/{oid}/driver-ack", token=t1)
        body = {"delivery_photo_urls": ["/static/uploads/delivery/rep.jpg"]}
        if payment:
            body["payment"] = payment
        call("POST", f"/orders/{oid}/complete", body, token=t1)
        return oid

    base = snap()
    cash_oid = deliver(True, "cash")
    arrears_oid = deliver(False, "arrears")
    s1 = snap()
    d_amount = round(s1["amount"] - base["amount"], 2)
    d_collected = round(s1["collected"] - base["collected"], 2)
    d_arrears = round(s1["arrears"] - base["arrears"], 2)
    print(f"  [信息] 增量：营业额 +{d_amount} / 已收 +{d_collected} / 挂账 +{d_arrears}")

    ok("营业额增量 = 两张单的金额合计（200）", d_amount == 200.0, f"实际 {d_amount}")
    ok("「已收 + 挂账」与营业额闭合（200 = 100 + 100）",
       round(d_collected + d_arrears, 2) == d_amount,
       f"已收 {d_collected} + 挂账 {d_arrears} = {round(d_collected + d_arrears, 2)}，"
       f"而营业额是 {d_amount}——差出来的钱在报表上哪一列都不属于")

    # 挂账单后来结清（arrears_settle）：钱必须从「挂账」挪到「已收」，而不是两边都消失
    me = call("GET", "/users/me", token=shipper)[1]
    cust = call("POST", "/customers", {"name": uniq("报表探针客户"), "user_id": me["id"]}, token=tok)[1]
    if isinstance(cust, dict) and cust.get("id"):
        st, r = call("POST", "/ledger/receipts", {
            "customer_id": cust["id"], "amount": "100.00", "method": "arrears_settle",
            "settle_mode": "itemized", "order_ids": [arrears_oid],
            "received_at": date.today().isoformat(),
        }, token=tok)
        s2 = snap()
        e_collected = round(s2["collected"] - s1["collected"], 2)
        e_arrears = round(s2["arrears"] - s1["arrears"], 2)
        print(f"  [信息] 挂账结清后增量：已收 {e_collected:+} / 挂账 {e_arrears:+}（收款接口 {st}）")
        if st in (200, 201):
            ok("挂账结清后：钱从「挂账」挪到「已收」（两者合计不变）",
               round(e_collected + e_arrears, 2) == 0.0,
               f"已收 {e_collected:+}、挂账 {e_arrears:+} —— 合计变了 "
               f"{round(e_collected + e_arrears, 2)}，这笔钱在报表上凭空消失")
            ok("结清挂账会把「已收」加上这 100（不能只减少挂账）",
               e_collected == 100.0, f"「已收」只动了 {e_collected}")

    # 软删（隔离区）的单必须从报表里消失
    s3 = snap()
    call("DELETE", f"/orders/{cash_oid}", token=tok)
    s4 = snap()
    ok("删掉的单不再算进营业额（隔离区的单不许还算钱）",
       round(s3["amount"] - s4["amount"], 2) == 100.0,
       f"删掉 100 元的单之后营业额只减了 {round(s3['amount'] - s4['amount'], 2)}")


# ------------------------------------------------------------------ 并发与重复提交

def probe_concurrency(tok: str) -> None:
    """并发打同一个资源的两个写请求 —— 找"读-判断-写"之间没有锁的缝隙。

    ⚠️ 本机后端是 SQLite（写是串行的），所以**这里没复现不等于线上安全**：
    生产是 MySQL + 多 worker，同样的缝隙只会更容易撞上。结论要分两半说：
    "复现了" = 确认缺陷；"没复现" = 只能说这段代码**没有防它的机制**（下面去源码里找证据）。
    """
    print("\n== 并发/重复提交：同一个资源被两个请求同时写 ==")
    from concurrent.futures import ThreadPoolExecutor

    shipper = login(SHIPPER)
    d1, t1 = _mk_driver(tok, "并发探针司机甲")
    d2, _t2 = _mk_driver(tok, "并发探针司机乙")

    def mk_order() -> int:
        st, o = call("POST", "/orders", {"lines": [{"product_name_snapshot": "并发探针货", "quantity": 1,
                                                    "unit_price": "60.00", "line_total": "60.00"}],
                                         "delivery_description": "并发探针"}, token=shipper)
        assert st == 201, o
        return int(o["id"])

    def run_pair(fn) -> list:
        with ThreadPoolExecutor(max_workers=2) as ex:
            return [f.result() for f in [ex.submit(fn, 0), ex.submit(fn, 1)]]

    # ① 同一张待派单单，两个请求同时派给**不同**司机
    oid = mk_order()

    def assign(i: int):
        return call("POST", f"/orders/{oid}/assign",
                    {"driver_id": d1 if i == 0 else d2, "freight_fee": "20.00"}, token=tok)

    res = run_pair(assign)
    codes = [r[0] for r in res]
    final = call("GET", f"/orders/{oid}", token=tok)[1]
    ok("并发派单：只有一个请求能成功（否则订单被派给两个人）",
       codes.count(200) == 1,
       f"两个请求返回 {codes}，最终司机 {final.get('driver_name') if isinstance(final, dict) else final}")

    # ② 同一张已接单单，两个请求同时送达（司机手滑点两下 / 网络重试）
    call("POST", f"/orders/{oid}/cancel", token=tok)
    oid2 = mk_order()
    call("POST", f"/orders/{oid2}/assign", {"driver_id": d1, "freight_fee": "50.00"}, token=tok)
    call("POST", f"/orders/{oid2}/driver-ack", token=t1)

    def complete(_: int):
        return call("POST", f"/orders/{oid2}/complete",
                    {"delivery_photo_urls": ["/static/uploads/delivery/race.jpg"]}, token=t1)

    codes2 = [r[0] for r in run_pair(complete)]
    bills = call("GET", f"/driver-bills?driver_id={d1}", token=tok)[1]
    mine = [b for b in (bills or []) if b.get("order_id") == oid2]
    ok("并发送达：同一张单只能生成一条司机账单（否则司机拿两份钱）",
       len(mine) == 1,
       f"两个请求返回 {codes2}，这张单的司机账单有 {len(mine)} 条：{[(b['id'], b['amount']) for b in mine]}")

    # ③ 同一张未收款单，两个请求同时逐单核销
    me = call("GET", "/users/me", token=shipper)[1]
    cust = call("POST", "/customers", {"name": uniq("并发探针客户"), "user_id": me["id"]}, token=tok)[1]
    oid3 = mk_order()
    if isinstance(cust, dict) and cust.get("id"):
        def receipt(_: int):
            return call("POST", "/ledger/receipts", {
                "customer_id": cust["id"], "amount": "60.00", "method": "cash",
                "settle_mode": "itemized", "order_ids": [oid3],
                "received_at": datetime.now(timezone.utc).date().isoformat(),
            }, token=tok)

        codes3 = [r[0] for r in run_pair(receipt)]
        rows = call("GET", "/ledger/receipts", token=tok)[1]
        hits = [x for x in (rows or []) if oid3 in (x.get("order_ids") or [])]
        ok("并发核销：同一张单只能落一条收款记录（否则钱多记一笔）",
           len(hits) <= 1,
           f"两个请求返回 {codes3}，这张单有 {len(hits)} 条收款记录")
    else:
        print("  [跳过] 没建出客户档案，跳过并发核销")

    # 最后一道闸：数据库级唯一索引（v3.41 补的）。以前这里是"信息：没有唯一约束"，
    # 现在改成**查库核对**——它不该再只是"Python 里的先查再插"。
    import sqlite3

    db = ROOT / "backend" / "sorders.db"
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
            names = {
                r[0]
                for r in c.execute(
                    "select name from sqlite_master where type='index' and tbl_name='driver_bills'"
                )
            }
    except sqlite3.Error as e:  # noqa: BLE001
        names = set()
        print(f"  [信息] 查不到索引（{e}）")
    ok("司机账单有 (order_id, bill_type) 唯一索引（并发下不靠 Python 的先查再插）",
       "uq_driver_bills_order_type" in names,
       f"driver_bills 上的索引：{sorted(names)}")

    for o in (oid2, oid3):
        st = call("GET", f"/orders/{o}", token=tok)[1]
        if isinstance(st, dict) and st.get("status") in ("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED"):
            call("POST", f"/orders/{o}/cancel", token=tok)


# ------------------------------------------------------------------ 司机钱的三方对账

def probe_driver_money(tok: str) -> None:
    """同一个司机的"还欠他多少"必须在**三个地方**是同一个数：

    ① 司机账单（`driver_bills` 的 OPEN 明细）② 绩效页的「待结运费」 ③ 运费结算页该司机合计。
    这三处历史上各自抄过 `freight_fee`（v3.36 才收口到 `driver_pay`），只要有一处落后，
    表现就是"账单说 120、结算页说 500"——两边都不报错。
    """
    print("\n== 司机钱：账单 / 绩效 / 结算页 三方对账 ==")
    shipper = login(SHIPPER)
    d1, t1 = _mk_driver(tok, "对账探针司机")

    rule = call("POST", "/driver-billing-rules", {
        "name": uniq("对账规则"), "vehicle_type": "trailer", "salary": "0",
        "piece_amount": "300", "commission_base": "freight", "commission_rate": "5",
    }, token=tok)[1]
    if isinstance(rule, dict) and rule.get("id"):
        call("POST", "/driver-billing-rules/attach", {"driver_id": d1, "rule_id": rule["id"]}, token=tok)

    today = datetime.now(timezone.utc).date()
    month = today.strftime("%Y-%m")
    bills_before = call("GET", f"/driver-bills?driver_id={d1}", token=tok)[1] or []
    open_before = sum(float(b["amount"]) for b in bills_before
                      if b.get("bill_type") == "piece" and b.get("status") == "open")

    delivered: list[int] = []
    for freight, _expect in (("1000.00", 350.0), ("500.00", 325.0)):
        st, o = call("POST", "/orders", {"lines": [{"product_name_snapshot": "对账探针货", "quantity": 1,
                                                   "unit_price": "80.00", "line_total": "80.00"}],
                                         "delivery_description": "对账探针"}, token=shipper)
        oid = int(o["id"])
        call("POST", f"/orders/{oid}/assign",
             {"driver_id": d1, "freight_fee": freight, "collect_cash": True}, token=tok)
        call("POST", f"/orders/{oid}/driver-ack", token=t1)
        call("POST", f"/orders/{oid}/complete",
             {"delivery_photo_urls": ["/static/uploads/delivery/rec.jpg"], "payment": "cash"}, token=t1)
        delivered.append(oid)
    expected_total = 350.0 + 325.0

    bills = call("GET", f"/driver-bills?driver_id={d1}", token=tok)[1] or []
    bill_sum = round(sum(float(b["amount"]) for b in bills
                         if b.get("bill_type") == "piece" and b.get("status") == "open") - open_before, 2)

    st, perf = call("GET", f"/stats/driver-performance?date_from={today.isoformat()}"
                           f"&date_to={today.isoformat()}", token=tok)
    rows = (perf or {}).get("drivers", []) if isinstance(perf, dict) else []
    mine = [r for r in rows if r.get("driver_id") == d1]
    perf_owed = float(mine[0].get("freight_owed") or 0) if mine else None

    st2, settle = call("GET", f"/freight-settlement?month={month}", token=tok)
    grps = (settle or {}).get("groups", []) if isinstance(settle, dict) else []
    mine_g = [g for g in grps if g.get("driver_id") == d1]
    settle_total = float(mine_g[0].get("total") or 0) if mine_g else 0.0

    print(f"  [信息] 手算应得 {expected_total}｜账单 +{bill_sum}｜绩效待结 {perf_owed}｜结算页 {settle_total}")
    ok("司机账单合计 = 手算（规则算出来的钱，不是运费）", bill_sum == expected_total,
       f"账单 {bill_sum} ≠ 手算 {expected_total}")
    if perf_owed is not None:
        ok("绩效页「待结运费」= 手算", perf_owed == expected_total,
           f"绩效 {perf_owed} ≠ 手算 {expected_total}（账单 {bill_sum}）")
    else:
        print("  [信息] 绩效页没有这个司机的行（可能这一天没数据）")
    ok("运费结算页合计 = 手算", settle_total == expected_total,
       f"结算页 {settle_total} ≠ 手算 {expected_total}（账单 {bill_sum}）")

    st, s = call("POST", "/driver-settlements", {"driver_id": d1, "month": month,
                                                 "settle_type": "piece"}, token=tok)
    if isinstance(s, dict) and s.get("id"):
        call("PATCH", f"/driver-settlements/{s['id']}", {"action": "confirm"}, token=tok)
        after = call("GET", f"/driver-bills?driver_id={d1}", token=tok)[1] or []
        still_open = [b for b in after
                      if b.get("bill_type") == "piece" and b.get("status") == "open"
                      and b.get("order_id") in delivered]
        ok("结算确认后，这批账单不再是「待结」明细（不能被第二张结算单重复占用）",
           not still_open, f"还有 {len(still_open)} 条待结：{[(b['order_id'], b['amount']) for b in still_open]}")

        # ⚠️ 口径要点：**确认 ≠ 付钱**。
        #    - 绩效页的「待结运费」= 应结 − **已付款**(PAID) 的结算单，所以这时应当**还是** 675；
        #    - 运费结算页那个数是"本月司机运费**支出**"（界面标题就这么写），本来就该一直是 675。
        #    第一版探针把"确认后清零"当期望，那是**探针自己写错了期望**（会把对的报成错的）。
        st, perf2 = call("GET", f"/stats/driver-performance?date_from={today.isoformat()}"
                                f"&date_to={today.isoformat()}", token=tok)
        rows2 = (perf2 or {}).get("drivers", []) if isinstance(perf2, dict) else []
        mine2 = [r for r in rows2 if r.get("driver_id") == d1]
        owed_after_confirm = float(mine2[0].get("freight_owed") or 0) if mine2 else None
        ok("只确认没付款时，绩效「待结运费」不变（确认≠付钱）",
           owed_after_confirm == expected_total,
           f"确认后待结变成 {owed_after_confirm}（应仍为 {expected_total}）")

        # 真正付款之后，绩效待结归零
        st_pay, pay = call("PATCH", f"/driver-settlements/{s['id']}", {"action": "pay", "method": "cash"}, token=tok)
        st, perf3 = call("GET", f"/stats/driver-performance?date_from={today.isoformat()}"
                                f"&date_to={today.isoformat()}", token=tok)
        rows3 = (perf3 or {}).get("drivers", []) if isinstance(perf3, dict) else []
        mine3 = [r for r in rows3 if r.get("driver_id") == d1]
        owed_paid = float(mine3[0].get("freight_owed") or 0) if mine3 else None
        if st_pay in (200, 201):
            ok("付款之后绩效「待结运费」归零（已结的不能还算欠他）",
               owed_paid == 0.0, f"付款后待结还有 {owed_paid}")
        else:
            print(f"  [信息] 结算付款返回 {st_pay} {str(pay)[:120]}")
    else:
        print(f"  [信息] 建结算单返回 {st} {str(s)[:120]}")

    if isinstance(rule, dict) and rule.get("id"):
        call("DELETE", f"/driver-billing-rules/{rule['id']}", token=tok)


# ------------------------------------------------------------------ 导出

def probe_export(tok: str) -> None:
    """导出的 Excel 与接口上的数字必须是**同一份**（导出最容易悄悄跑偏）。

    做法：把 `GET /reports/export` 拿到的 xlsx 解析出来，找"营业额/已收/挂账"那几个格子，
    和 `GET /reports/turnover` 的返回值逐个对。
    """
    print("\n== 导出：Excel 里的数字 == 接口上的数字 ==")
    shipper = login(SHIPPER)
    d1, t1 = _mk_driver(tok, "导出探针司机")

    st, o = call("POST", "/orders", {"lines": [{"product_name_snapshot": "导出探针货", "quantity": 1,
                                                "unit_price": "123.45", "line_total": "123.45"}],
                                     "delivery_description": "导出探针"}, token=shipper)
    oid = int(o["id"])
    call("POST", f"/orders/{oid}/assign", {"driver_id": d1, "freight_fee": "30.00", "collect_cash": True}, token=tok)
    call("POST", f"/orders/{oid}/driver-ack", token=t1)
    call("POST", f"/orders/{oid}/complete",
         {"delivery_photo_urls": ["/static/uploads/delivery/xls.jpg"], "payment": "cash"}, token=t1)

    anchor = datetime.now(timezone.utc).date().isoformat()
    st, data = call("GET", f"/reports/turnover?mode=day&date={anchor}", token=tok)
    if not isinstance(data, dict):
        print(f"  [跳过] 报表接口返回 {st}")
        return
    try:
        import io as _io

        import openpyxl
    except ImportError:
        print("  [跳过] 本机没有 openpyxl，无法解析导出文件")
        return

    req = urllib.request.Request(
        BASE + f"/reports/export?kind=turnover&mode=day&date={anchor}",
        headers={"Authorization": "Bearer " + tok},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        print(f"  [跳过] 导出接口返回 {e.code}：{e.read().decode('utf-8', 'replace')[:120]}")
        return

    wb = openpyxl.load_workbook(_io.BytesIO(raw), data_only=True)
    cells: dict[str, object] = {}
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            for i, v in enumerate(row):
                if isinstance(v, str) and v in ("营业额", "已收", "挂账未收", "司机运费支出", "货损金额"):
                    nxt = row[i + 1] if i + 1 < len(row) else None
                    if nxt is not None:
                        cells[v] = nxt
    print(f"  [信息] Excel 里读到的格子：{ {k: str(v) for k, v in cells.items()} }")

    def eq(a, b) -> bool:
        try:
            return abs(float(a) - float(b)) < 0.005
        except (TypeError, ValueError):
            return False

    ok("导出的「已收」= 报表的 collected", eq(cells.get("已收"), data.get("collected")),
       f"Excel {cells.get('已收')} vs 接口 {data.get('collected')}")
    ok("导出的「挂账未收」= 报表的 arrears_total",
       eq(cells.get("挂账未收"), data.get("arrears_total")),
       f"Excel {cells.get('挂账未收')} vs 接口 {data.get('arrears_total')}")
    # 营业额在导出里是和"商品毛利"同一行的第二列，单独核对一次
    total_in_xls = None
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            if row and row[0] == "司机运费支出":
                total_in_xls = row[3] if len(row) > 3 else None
    if total_in_xls is not None:
        ok("导出里的营业额与接口一致（同一份聚合，不许各算各的）",
           eq(str(total_in_xls).lstrip("¥"), data.get("total_amount")),
           f"Excel {total_in_xls} vs 接口 {data.get('total_amount')}")


# ------------------------------------------------------------------ 价格（多档批发价 / 专属价）

def probe_pricing(tok: str) -> None:
    """价格是谁说了算：多档批发价（tier_prices）与批发商专属价（price_rules）在下单时的口径。

    这两处**后端都不做校验**（下单的 `unit_price` 由客户端传），所以要测的不是"能不能绕"
    （也没必要绕：代理下单本来就要能手改价），而是：
    ① 档位价/专属价是不是纯展示；② 落库是不是老实照抄客户端（金额口径一致）；
    ③ 改商品价之后已下的单会不会跟着变（快照语义）。
    """
    print("\n== 价格：多档批发价 / 批发商专属价 在下单时的口径 ==")
    shipper = login(SHIPPER)

    p = call("POST", "/products", {"name": uniq("价格探针商品"), "default_unit_price": "10",
                                   "tier_prices": [{"label": "批发", "unit_price": "8"},
                                                   {"label": "大批发", "unit_price": "6"}]}, token=tok)[1]
    pid = p["id"]
    print("  [信息] 商品默认价 %s，档位价 %s"
          % (p["default_unit_price"], [(t["label"], t["unit_price"]) for t in p["tier_prices"]]))

    # ① 客户端给档位价就落档位价（后端不做二次定价）
    st, o = call("POST", "/orders", {"lines": [{"product_id": pid, "product_name_snapshot": "价格探针货",
                                                "quantity": 10, "unit_price": "8.00",
                                                "line_total": "80.00"}],
                                     "delivery_description": "价格探针"}, token=shipper)
    oid = None
    ok("货主按档位价（8.00）下单能落库", st == 201, f"返回 {st} {str(o)[:120]}")
    if st == 201:
        oid = o["id"]
        ok("落库单价 = 客户端给的档位价（后端不做二次定价）",
           float(o["order_products"][0]["unit_price"]) == 8.0,
           f"落库 {o['order_products'][0]['unit_price']}")

    # ② 批发商专属价：后端只存不管（下单时用哪个价由客户端决定）
    mem_phone = "13" + "".join(random.choice("0123456789") for _ in range(9))
    st, mem = call("POST", "/users", {"phone": mem_phone, "password": "123321",
                                      "full_name": "价格探针批发商", "role": "shipper",
                                      "is_member": True}, token=tok)
    if st in (200, 201):
        CREATED_USERS.append(int(mem["id"]))
        st2, _ = call("POST", "/price-rules", {"shipper_id": mem["id"], "product_id": pid,
                                               "special_unit_price": "5"}, token=tok)
        st3, rows = call("GET", f"/price-rules?shipper_id={mem['id']}", token=tok)
        print("  [信息] 设专属价 5.00 返回 %s；查询回 %s" % (st2, str(rows)[:120]))
        st4, o2 = call("POST", "/orders", {"lines": [{"product_id": pid,
                                                      "product_name_snapshot": "价格探针货",
                                                      "quantity": 10, "unit_price": "100.00",
                                                      "line_total": "1000.00"}],
                                           "delivery_description": "价格探针"}, token=shipper)
        print("  [信息] 货主按**自己填的** 100 元下单：返回 %s%s"
              % (st4, "（后端不拦——价是谈出来的，后端只保证金额口径一致）" if st4 == 201 else ""))
        if st4 == 201:
            call("DELETE", f"/orders/{o2['id']}", token=tok)
    else:
        print(f"  [信息] 建批发商失败 {st} {str(mem)[:120]}")

    # ③ 改商品默认价之后：已下的单不变（行里是快照）
    call("PATCH", f"/products/{pid}", {"default_unit_price": "12"}, token=tok)
    if oid is not None:
        after = call("GET", f"/orders/{oid}", token=tok)[1]
        ok("改商品价之后，已下的单金额不变（行里是快照）",
           float(after["order_products"][0]["unit_price"]) == 8.0,
           f"变成了 {after['order_products'][0]['unit_price']}（历史金额被追溯）")
        call("DELETE", f"/orders/{oid}", token=tok)

    call("DELETE", f"/products/{pid}", token=tok)


GROUPS = {
    "商品": probe_products,
    "下单": probe_order_math,
    "状态机": probe_state_machine,
    "库存": probe_inventory,
    "权限": probe_permissions,
    "收款": probe_money,
    "报表": probe_reports,
    "并发": probe_concurrency,
    "司机钱": probe_driver_money,
    "导出": probe_export,
    "价格": probe_pricing,
}


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    tok = login(DISPATCHER)
    for name, fn in GROUPS.items():
        if only and not name.startswith(only):
            continue
        try:
            fn(tok)
        except Exception as e:  # 探针自己炸了也要说清楚，别静默跳过
            print(f"  [探针异常] {name}: {type(e).__name__}: {e}")
            FINDINGS.append(f"{name} 探针异常：{e}")

    cleanup_created(tok)

    print("\n" + "=" * 64)
    if FINDINGS:
        print(f"可疑 {len(FINDINGS)} 条：")
        for f in FINDINGS:
            print("  - " + f)
        return 1
    print("这一组没有发现可疑点。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
