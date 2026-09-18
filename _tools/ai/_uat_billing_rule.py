"""真机 UAT 辅助：建一条计费规则并挂给司机（走真实后端 HTTP），供设备上肉眼核对列表与账单。

为什么不用 adb 在界面上敲：中文输入在 Windows+模拟器上打不进去（见项目记忆），
而这一步要验的是"后端真数据在界面上的呈现"，不是"输入法能不能用"。
"""
import json
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"


def call(method, path, body=None, token=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        method=method,
        headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})},
    )
    with urllib.request.urlopen(req) as r:
        raw = r.read().decode("utf-8")
        return json.loads(raw) if raw else None


tok = call("POST", "/auth/login", {"phone": "13800000001", "password": "123321"})["access_token"]

rule = call("POST", "/driver-billing-rules", {
    "name": "挂车计件+运费提成-UAT",
    "vehicle_type": "trailer",
    "piece_amount": "300",
    "commission_base": "freight",
    "commission_rate": "5",
    "remark": "真机 UAT",
}, token=tok) if not any(r["name"] == "挂车计件+运费提成-UAT" for r in call("GET", "/driver-billing-rules", token=tok)) \
    else next(r for r in call("GET", "/driver-billing-rules", token=tok) if r["name"] == "挂车计件+运费提成-UAT")
print("建规则:", rule["id"], rule["name"], "|", rule["summary"], "| 车型", rule["vehicle_type"])

rules = call("GET", "/driver-billing-rules", token=tok)
print("规则共", len(rules), "条：", [r["name"] for r in rules])

drivers = call("GET", "/users?role=driver", token=tok)
tgt = next((d for d in drivers if d.get("vehicle_type") == "trailer"), None)
if tgt is None:
    # 挂车规则只能挂给挂车司机（后端会拦车型不匹配），所以真机上没挂车司机就建一个
    import random
    phone = "13" + "".join(random.choice("0123456789") for _ in range(9))
    tgt = call("POST", "/users", {"phone": phone, "password": "123321", "full_name": "UAT挂车司机",
                                  "role": "driver", "vehicle_type": "trailer"}, token=tok)
print("目标司机:", tgt["id"], tgt.get("full_name"), tgt.get("vehicle_type"), "现有规则:", tgt.get("driver_rule_name") or "无")
print("挂载前 pay_summary:", tgt.get("pay_summary"))

call("POST", "/driver-billing-rules/attach", {"driver_id": tgt["id"], "rule_id": rule["id"]}, token=tok)
after = next(d for d in call("GET", "/users?role=driver", token=tok) if d["id"] == tgt["id"])
print("挂载后 pay_summary:", after.get("pay_summary"), "| rule_id:", after.get("driver_rule_id"))
print("RULE_ID=%s DRIVER_ID=%s" % (rule["id"], tgt["id"]))
