"""真机 E2E：**派单时逐单定价/定比例 → 送达 → 账单等于手算的数**（v3.37）。

## 为什么要有它
`test_driver_billing_api.py` 已经证明"接口把钱算对了"，证明不了**真机上那两个输入框
填进去的数真的走到了账单**——中间还隔着 DTO/仓库/ViewModel/Screen 四层，
而这个仓库栽过的正是这种"后端对、客户端没传"的静默失败（批量派单的运费字段就是活例子）。

## 三段式
```
python _tools/ai/_uat_billing_override.py prepare   # 建规则 + 挂车司机 + 两张订单（界面操作前的准备）
   ...在模拟器上：派单作业 → 打开订单 → 选挂车司机 → 填「这一单的钱 / 提成 %」→ 确认派单
python _tools/ai/_uat_billing_override.py verify    # 司机接单+送达 → 核对账单 == 手算
python _tools/ai/_uat_billing_override.py taps      # 打印当前页所有文字（找点击目标）
```
`verify` 手算：规则「每单 300 + 运费的 5%」，运费 1000，逐单比例填 8 → 300 + 80 = **380.00**；
第二张单不填覆盖值 → 300 + 50 = **350.00**（证明"不填就走规则"和"填了才覆盖"是两回事）。
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

BASE = "http://127.0.0.1:8000/api/v1"
ADB = r"D:\APPS\sdk\platform-tools\adb.exe"
ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "_tools/ai/_uat_billing_override.json"

RULE_NAME = "UAT逐单覆盖-每单300+运费5%"
FREIGHT = "1000.00"
RATE_OVERRIDE = "8"
EXPECT_A = "380.00"   # 300 + 1000×8%
EXPECT_B = "350.00"   # 300 + 1000×5%（没填覆盖 → 用规则里的比例）


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
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return {"__error__": e.code, "detail": e.read().decode("utf-8", "replace")}


def login(phone: str) -> str:
    return call("POST", "/auth/login", {"phone": phone, "password": "123321"})["access_token"]


def adb(*args: str) -> str:
    r = subprocess.run([ADB, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    return (r.stdout or "") + (r.stderr or "")


def prepare() -> int:
    tok = login("13800000001")
    rules = call("GET", "/driver-billing-rules", token=tok)
    rule = next((r for r in rules if r["name"] == RULE_NAME), None)
    if rule is None:
        rule = call("POST", "/driver-billing-rules", {
            "name": RULE_NAME, "vehicle_type": "trailer",
            "salary": "0", "piece_amount": "300",
            "commission_base": "freight", "commission_rate": "5",
            "remark": "真机 E2E（逐单覆盖）",
        }, token=tok)
    print(f"规则：#{rule['id']} {rule['name']} | {rule['summary']}")

    drivers = call("GET", "/users?role=driver", token=tok)
    drv = next((d for d in drivers if d.get("vehicle_type") == "trailer"), None)
    if drv is None:
        import random
        phone = "13" + "".join(random.choice("0123456789") for _ in range(9))
        drv = call("POST", "/users", {"phone": phone, "password": "123321", "full_name": "UAT逐单覆盖司机",
                                      "role": "driver", "vehicle_type": "trailer"}, token=tok)
    print(f"司机：#{drv['id']} {drv.get('full_name')} | 现在：{drv.get('pay_summary') or '没挂规则'}")
    if drv.get("driver_rule_id") != rule["id"]:
        call("POST", "/driver-billing-rules/attach", {"driver_id": drv["id"], "rule_id": rule["id"]}, token=tok)
        drv = next(d for d in call("GET", "/users?role=driver", token=tok) if d["id"] == drv["id"])
        print(f"  挂载后：{drv.get('pay_summary')}")

    # 两张订单：A 走逐单覆盖，B 不填（证明"不填就走规则"不是空话）
    shipper = login("13800000002")
    ids = []
    for tag in ("A", "B"):
        o = call("POST", "/orders", {
            "lines": [{"product_name_snapshot": f"逐单覆盖UAT-{tag}", "quantity": 2,
                       "unit_price": "50.00", "line_total": "100.00"}],
            "delivery_description": f"逐单覆盖 UAT {tag}",
        }, token=shipper)
        ids.append(o["id"])
        print(f"订单 {tag}：#{o['id']} {o['order_no']}（待派单）")

    STATE.write_text(json.dumps({
        "rule_id": rule["id"], "driver_id": drv["id"], "driver_name": drv.get("full_name"),
        "order_a": ids[0], "order_b": ids[1],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n状态写进 {STATE}")
    print(f"""
接下来在模拟器上（派单员 13800000001）：
  1. 工作台 → 派单作业 → 打开 订单A（#{ids[0]}）→ 派单
  2. 选「挂车司机」组 → 选 {drv.get('full_name')}
  3. 运费填 {FREIGHT}；下面会出现「这一单单独定（不填就按他的规则算）」
     —— 金额填 300、提成填 {RATE_OVERRIDE} → 确认派单
  4. 同样派 订单B（#{ids[1]}），运费 {FREIGHT}，**两个框留空** → 确认派单
  5. 回到这里跑：python _tools/ai/_uat_billing_override.py verify
""")
    return 0


def verify() -> int:
    if not STATE.exists():
        print(f"❌ 先跑 prepare（找不到 {STATE}）")
        return 1
    st = json.loads(STATE.read_text(encoding="utf-8"))
    tok = login("13800000001")
    drivers = call("GET", "/users?role=driver", token=tok)
    drv = next(d for d in drivers if d["id"] == st["driver_id"])
    dtok = login(drv["phone"])

    fails: list[str] = []
    for key, expect, label in (("order_a", EXPECT_A, "填了逐单覆盖"), ("order_b", EXPECT_B, "没填（走规则）")):
        oid = st[key]
        o = call("GET", f"/orders/{oid}", token=tok)
        st_ = o.get("status")
        # 脚本会被重跑（上一轮可能已经接单/送达了）：三种状态都算"已经派出去了"，
        # 只认 DISPATCHED 会把"重跑"误报成"还没派单"。
        if st_ not in ("DISPATCHED", "ACCEPTED", "DELIVERED"):
            fails.append(f"{label}：订单 #{oid} 状态是 {st_}，还没派出（先在界面上派单）")
            continue
        print(f"{label}：订单 #{oid} 覆盖值 金额={o.get('driver_piece_amount')} 比例={o.get('driver_commission_rate')}")
        if st_ == "DISPATCHED":
            call("POST", f"/orders/{oid}/driver-ack", token=dtok)
        if st_ != "DELIVERED":
            call("POST", f"/orders/{oid}/complete", {"delivery_photo_urls": ["/static/uploads/delivery/uat-override.jpg"]}, token=dtok)
        bills = call("GET", f"/driver-bills?driver_id={st['driver_id']}", token=tok)
        hit = [b for b in bills if b.get("order_id") == oid and b["bill_type"] == "piece"]
        if not hit:
            fails.append(f"{label}：送达后**没有生成账单**（那一笔钱静默消失了）")
            continue
        got = f"{float(hit[0]['amount']):.2f}"
        flag = "✅" if got == expect else "❌"
        print(f"  账单 {hit[0]['amount']}（期望 {expect}）{flag} | {hit[0].get('note')}")
        if got != expect:
            fails.append(f"{label}：账单 {got} ≠ 手算 {expect}")

    if fails:
        print("\n❌ E2E 不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print("\n✅ 真机 E2E 通过：填了走覆盖、没填走规则，两条路的账单都等于手算的数。")
    return 0


def taps() -> int:
    """打印当前页所有文字（找点击目标；中文用 `_emulator_say.ps1` 输入）。"""
    adb("shell", "uiautomator", "dump", "/sdcard/_ui.xml")
    xml = adb("shell", "cat", "/sdcard/_ui.xml")
    import re
    for tag in re.findall(r"<node[^>]*>", xml):
        t = re.search(r'text="([^"]*)"', tag)
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if t and t.group(1) and b:
            print(f"{t.group(1)}   {(int(b.group(1)) + int(b.group(3))) // 2},{(int(b.group(2)) + int(b.group(4))) // 2}")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "prepare"
    sys.exit({"prepare": prepare, "verify": verify, "taps": taps}.get(cmd, prepare)())
