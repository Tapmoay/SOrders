"""把一个待派单订单派给某个司机 —— 用来在真机上验证「司机端新单提醒」。

为什么要单独一个脚本：司机端「来单了」的验证必须走**真实链路**
（POST /orders/{id}/assign → 后端 background task → Socket.IO 推送 → 手机响），
用 adb 伪一条 Socket 事件是验不出"后端到底发没发、发的是什么"的。

用法：
    python _tools/notify/_assign_order.py                 # 自动挑一单待派单派给司机3
    python _tools/notify/_assign_order.py --driver 68      # 指定司机
    python _tools/notify/_assign_order.py --order 402      # 指定订单 id
    python _tools/notify/_assign_order.py --list           # 只看有哪些可派的单
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

BASE = "http://127.0.0.1:8000/api/v1"
DISPATCHER = ("13800000001", "123321")


def call(method: str, path: str, token: str | None = None, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def login(username: str, password: str) -> str:
    status, res = call("POST", "/auth/login", body={"username": username, "password": password})
    if status != 200:
        raise SystemExit(f"登录失败 {status}: {res}")
    return res["access_token"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--driver", type=int, default=3, help="司机 user id（缺省 3 = 13800000003 Driver）")
    ap.add_argument("--order", type=int, default=None, help="订单 id（缺省自动挑一单待派单）")
    ap.add_argument("--list", action="store_true", help="只列可派的单")
    args = ap.parse_args()

    token = login(*DISPATCHER)
    _, pending = call("GET", "/orders?status=PENDING_DISPATCH&limit=10", token)
    rows = pending if isinstance(pending, list) else (pending or {}).get("items", [])
    print(f"待派单 {len(rows)} 单：")
    for o in rows[:10]:
        print(f"  id={o['id']}  {o.get('order_no')}  货主={o.get('shipper_name') or o.get('temp_shipper_name')}")
    if args.list:
        return 0
    if not rows and args.order is None:
        print("❌ 没有待派单的订单——先在 App 或接口下单一单再跑")
        return 1

    order_id = args.order if args.order is not None else rows[0]["id"]
    status, res = call(
        "POST",
        f"/orders/{order_id}/assign",
        token,
        {"driver_id": args.driver, "freight_fee": 50.0, "collect_cash": False},
    )
    if status != 200:
        print(f"❌ 派单失败 {status}: {res}")
        return 1
    print(f"✅ 已派单：id={res['id']} {res.get('order_no')} → 司机 {args.driver}（状态 {res.get('status')}）")
    print("   司机手机现在应该：通知栏弹出「新派单」+ 响「号角 + 来订单了，你有新的订单，请及时查看」")
    print("   （一段约 5 秒，按设置重复；播放期间媒体音量临时抬到 80%，播完还原）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
