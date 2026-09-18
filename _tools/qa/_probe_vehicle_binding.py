"""打真后端验「车辆绑定 / 解绑」这条路（v3.44）。

### 为什么要单独一个探针
这一轮修的两条缺陷都属于**"界面说成功了、其实没发生"**：
`driver_id=null` 被静默忽略（解绑做不到）、`PATCH` 不查车牌重复（两车同号）。
这类缺陷的特征是：**HTTP 200 + 响应体看着对**，只有落库与留痕能证伪。
所以判据必须落在"库里那一列"和"审计那一行"上，而不是状态码。

顺带回答另一个问题：**审计有没有真的写**。上一轮真机 E2E 发现 `PATCH /vehicles`
一条日志都没有——当时无法定论（跑着的 uvicorn 没 `--reload`，很可能是旧进程）。
这个探针是重启后端后的复验手段。

用法：
    python _tools/qa/_probe_vehicle_binding.py            # 跑一遍并还原
    python _tools/qa/_probe_vehicle_binding.py --keep     # 不还原（留现场给人看）
"""
import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
BASE = "http://127.0.0.1:8000/api/v1"
DB = ROOT / "backend/sorders.db"
PHONE, PASSWORD = "13800000001", "123321"


def call(method: str, path: str, token: str | None = None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw[:200]
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


def db(sql: str, args=()):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return list(con.execute(sql, args))
    finally:
        con.close()


def vehicles() -> str:
    return str(db("select id,plate_no,vehicle_type,driver_id,is_active from vehicles order by id"))


def veh_logs() -> list[str]:
    return [f"{r[0]} {r[1]} {r[2]}" for r in
            db("select id,action,change_content from operation_logs where action like 'VEHICLE%' order by id")]


# 探针自己造的那辆车。**车辆没有删除端点**（车牌会出现在记账/油耗的历史里，
# 界面上只提供"停用"），所以它只能由探针直接删库里的那一行——留着一辆叫
# 「测A00099」的停用车，下次谁打开车辆管理都会以为是自己建的。
PROBE_PLATE = "测A00099"


def _drop_probe_vehicle() -> None:
    con = sqlite3.connect(DB)
    try:
        con.execute("delete from vehicles where plate_no=?", (PROBE_PLATE,))
        con.commit()
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="跑完不还原")
    a = ap.parse_args()

    st, tok = call("POST", "/auth/login", body={"phone": PHONE, "password": PASSWORD})
    if st != 200:
        print(f"❌ 登录失败（本地后端在跑吗？）：{st} {tok}")
        return 1
    token = tok["access_token"]

    before = db("select id,driver_id from vehicles order by id")
    if not before:
        print("❌ 库里一辆车都没有 —— 先建一辆再来验")
        return 1
    vid, orig_driver = before[0]
    print(f"== 起始：{vehicles()}")
    print(f"   审计里已有机动车记录 {len(veh_logs())} 条")

    bad = 0

    def check(label: str, cond: bool, detail: str) -> None:
        nonlocal bad
        print(f"  [{'OK' if cond else 'FAIL'}] {label} —— {detail}")
        if not cond:
            bad += 1

    # ---- ① 解绑（缺省 driver_id）----
    n0 = len(veh_logs())
    st, body = call("POST", f"/vehicles/{vid}/driver", token, {})
    check("解绑返回 200 且 driver_id 变成 null",
          st == 200 and body.get("driver_id") is None, f"{st} {body}")
    check("库里 driver_id 真的空了",
          db("select driver_id from vehicles where id=?", (vid,))[0][0] is None, vehicles())
    logs = veh_logs()
    check("解绑写了审计（VEHICLE_DRIVER_SET + op=detach）",
          len(logs) == n0 + 1 and "VEHICLE_DRIVER_SET" in logs[-1] and "detach" in logs[-1],
          logs[-1] if logs else "（没有日志）")

    # ---- ② 车牌查重（改成一辆已在用的车牌必须被拦）----
    # ⚠️ 探针必须**先把自己上次留下的那辆车清掉**：`POST /vehicles` 会查重，
    #    第二次跑就会拿到 400 → `dup_id=None` → 后面 PATCH 打在 `/vehicles/None` 上
    #    变成 422，而报出来的是"绑定有问题"（实测踩到，白跑一轮）。
    _drop_probe_vehicle()
    st, body = call("POST", "/vehicles", token, {"plate_no": PROBE_PLATE, "vehicle_type": "small"})
    dup_id = body.get("id") if st == 200 else None
    if dup_id is None:
        print(f"❌ 探针车建不出来：{st} {body}")
        return 1
    st2, body2 = call("PATCH", f"/vehicles/{dup_id}", token, {"plate_no": db(
        "select plate_no from vehicles where id=?", (vid,))[0][0]})
    check("把车牌改成另一辆已在用的 → 400（老代码是 200）", st2 == 400, f"{st2} {body2}")
    # 自己撞自己：只改车型、车牌照旧
    st3, body3 = call("PATCH", f"/vehicles/{dup_id}", token, {"plate_no": PROBE_PLATE, "vehicle_type": "large"})
    check("只改车型（带上同一个车牌）不会被自己拦下", st3 == 200, f"{st3} {body3}")

    # ---- ③ 绑回原司机 ----
    if orig_driver is not None:
        st, body = call("POST", f"/vehicles/{vid}/driver", token, {"driver_id": orig_driver})
        check("绑回原司机返回 200", st == 200 and body.get("driver_id") == orig_driver, f"{st} {body}")
        check("绑回也留痕（op=attach）", "attach" in veh_logs()[-1], veh_logs()[-1])

    # ---- ④ 解绑一辆本来就没绑的车：不留痕 ----
    n1 = len(veh_logs())
    call("POST", f"/vehicles/{dup_id}/driver", token, {})
    st, body = call("POST", f"/vehicles/{dup_id}/driver", token, {})
    check("对没有司机的车再解绑一次 → 200 但不留痕（审计不该被空记录淹掉）",
          st == 200 and len(veh_logs()) == n1, f"{st}，日志 {len(veh_logs())} vs {n1}")

    # ---- 还原 ----
    if not a.keep:
        _drop_probe_vehicle()
        if orig_driver is not None:
            call("POST", f"/vehicles/{vid}/driver", token, {"driver_id": orig_driver})
        print(f"== 还原后：{vehicles()}")

    print("\n" + ("✅ 车辆绑定这几条都成立。" if bad == 0 else f"❌ {bad} 条不成立。"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
