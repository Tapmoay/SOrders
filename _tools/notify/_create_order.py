"""以**货主身份**下一单 —— 用来在真机上验证「派单员端新单语音播报」（2026-09-21）。

为什么要单独一个脚本：派单员那条语音的触发是
`POST /orders` →（后端 background task）`publish_new_order_to_dispatchers`
→ Socket.IO 推给每个派单员 → 派单员手机念「来订单了，有新订单待派单，请及时处理」。
用 adb 伪一条 Socket 事件验不出"后端到底发没发、发给谁"，
而这条链路上任何一环断了，用户那头的表现都只是**安静**。

配对脚本：司机那条用 `_tools/notify/_assign_order.py`（派单 → 司机手机响）。

用法：
    python _tools/notify/_create_order.py                 # 下一单（默认货主 13800000002）
    python _tools/notify/_create_order.py --as dispatcher  # 用派单员身份代理下单（会推给所有派单员，包括他自己）
    python _tools/notify/_create_order.py --remark 验证派单员语音

⚠️ 会往本地演示库写一条真实订单（待派单）。验证完自己决定留不留：
   派单员 App「订单管理」里可以删（软删，进隔离区，可恢复）。
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

BASE = "http://127.0.0.1:8000/api/v1"
ACCOUNTS = {
    "shipper": ("13800000002", "123321"),     # 货主：正常下单路径
    "dispatcher": ("13800000001", "123321"),  # 派单员：代理下单（同样会推给所有派单员）
}


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
    ap.add_argument("--as", dest="as_who", choices=sorted(ACCOUNTS), default="shipper",
                    help="用谁的账号下单（缺省 shipper = 货主本人下单）")
    ap.add_argument("--remark", default="验证派单员语音播报", help="订单备注")
    ap.add_argument("--address", default="惠州市惠阳区验证路 1 号", help="收货地址（终点）")
    args = ap.parse_args()

    token = login(*ACCOUNTS[args.as_who])
    body = {
        "lines": [{
            "product_name_snapshot": "验证用蔬菜",
            "quantity": 1,
            "unit_price": 10,
            "line_total": 10,
            "unit": "件",
        }],
        "address_detail": args.address,
        "remark": args.remark,
    }
    status, res = call("POST", "/orders", token, body)
    if status not in (200, 201):
        print(f"❌ 下单失败 {status}: {res}")
        return 1
    print(f"✅ 已下单：id={res['id']} {res.get('order_no')}（状态 {res.get('status')}）")
    print("   派单员手机现在应该：通知栏弹出「新订单待派单」+ 响「号角 + 来订单了，有新订单待派单，请及时处理」")
    print("   排障：adb logcat -s SOrdersAlert（应有「开始播报 kind=PENDING_ORDER」）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
