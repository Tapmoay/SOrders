"""把某张订单派给司机（真接口，给真机 E2E 铺路）。"""

import json
import sys
import urllib.error
import urllib.request

B = "http://127.0.0.1:8000/api/v1"


def req(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(B + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except Exception:
            return e.code, {"raw": raw.decode("utf-8", "replace")}


def main() -> int:
    order_id = int(sys.argv[1]) if len(sys.argv) > 1 else 717
    fee = sys.argv[2] if len(sys.argv) > 2 else None
    s, d = req("POST", "/auth/login", {"username": "13800000001", "password": "123321"})
    if s != 200:
        print("登录失败", s, d)
        return 1
    tok = d["access_token"]
    # ⚠️ 两个坑（第一版都踩了，表现为"找不到司机账号"）：
    #    1. `?role=driver` 要的是**枚举名 DRIVER**（小写返回空列表）；
    #    2. `/users` 默认只回 100 条且按 id 倒序 —— 演示账号 id=3 根本不在里面。
    #       所以必须用 `q=` 按手机号精确搜，不能拉全表再筛。
    s, users = req("GET", "/users?q=13800000003&limit=20", token=tok)
    if s != 200 or not isinstance(users, list):
        print("查账号失败", s, json.dumps(users, ensure_ascii=False)[:200])
        return 1
    driver = next(
        (u for u in users if u.get("phone") == "13800000003" and str(u.get("role", "")).lower() == "driver"),
        None,
    )
    if driver is None:
        print("找不到司机账号")
        return 1
    body = {"driver_id": driver["id"]}
    if fee:
        body["freight_fee"] = fee
    s, o = req("POST", f"/orders/{order_id}/assign", body, tok)
    print("派单", s, o.get("status"), o.get("driver_name"), o.get("order_no"))
    if s != 200:
        print(json.dumps(o, ensure_ascii=False)[:400])
        return 1
    print("address_lat=", o.get("address_lat"), " address_detail=", repr(o.get("address_detail")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
