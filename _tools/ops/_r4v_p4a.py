# -*- coding: utf-8 -*-
"""**P4-① 取桶内测试单**（R4-49 §九 V6 / 覆盖台账缺口 agreed=true）。

## 它在做什么

用户 2026-09-27 裁决走 (B) 路：**按预注册流程造受控测试订单**，直到某一张的
`order_id % 100 < 30`（= 落进 30% Canary 桶，会走 Contract 路径）。

⛔ 它不是"挑一个结果漂亮的订单"：**每一次尝试都要记**，落在桶外的本身就是
**有效的 not_in_canary 对照样本**，⛔ 不删、不抹、不许只留成功那一条。

## 判据写死在这里（⛔ 不靠记性）

1. **目标地址固定** = `塘厦林村工业区21号 3栋1063室` —— 那是 `shipper_addresses.id = 5`
   的 `detail_address`，而规则 #1 勾的价目 #5 的 `route_id = 5`。
   契约按 `route_ids_of(db, order.address_detail)`（地址文本 → 线路编号）认路线，
   地址文本不是这一串就**算不出来**，会在契约里退成 fallback。
2. **只肯用测试货主 183**（`13800000006`，在 is_test_account 认的号段里）。
3. **订单备注写死 `test_run_id`** 前缀 —— 这是身份标记的辅助层。
4. **硬上限 MAX_CREATE 笔**：超过就停，⛔ 不许无限造。

## 用法

    python _tools/ops/_r4v_p4a.py --dry-run     # 只读：算出现在离下一个桶内 id 还有多远
    python _tools/ops/_r4v_p4a.py               # 真造（会写生产）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _prodssh  # noqa: E402

RUN_ID = "R4V-20260927-02"
SCENARIO = "P4-1-agreed-true"
BUCKETS = 100
CANARY_PERCENT = 30
SHIPPER_ID = 183
DRIVER_ID = 184
OPERATOR = "13800000001"
OPERATOR_PASSWORD = "123321"
#: shipper_addresses.id = 5 的 detail_address（→ 规则 #1 勾的价目 #5 的 route_id = 5）
ADDRESS = "塘厦林村工业区21号 3栋1063室"
REMARK = RUN_ID
MAX_CREATE = 60

RECORD_DIR = Path(__file__).resolve().parent / "r4v_records"

_REMOTE = r"""set +e
@PY@ - <<'PYEOF'
import json, sys, urllib.error, urllib.request

BASE = "http://127.0.0.1:8111/api/v1"
OP = @OP@
OPPW = @OPPW@
SHIPPER = @SHIPPER@
ADDR = @ADDR@
REMARK = @REMARK@
BUCKETS = @BUCKETS@
PCT = @PCT@
MAXN = @MAXN@


def call(method, path, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()[:300]


s = call("POST", "/auth/login", body={"username": OP, "password": OPPW})
if s[0] != 200:
    print("RESULT|FAIL|操作账号登录失败 " + str(s[0]) + " " + str(s[1]))
    raise SystemExit(0)
token = s[1]["access_token"]
print("STEP|操作账号已登录 " + OP)

made = 0
while made < MAXN:
    s, res = call("POST", "/orders", token, {
        "shipper_id": SHIPPER,
        "address_detail": ADDR,
        "remark": REMARK,
        "lines": [{"product_name_snapshot": "R4V受控验证货",
                   "quantity": 1, "unit_price": "10", "line_total": "10"}],
    })
    if s not in (200, 201):
        print("RESULT|FAIL|建单失败 " + str(s) + " " + str(res))
        raise SystemExit(0)
    oid = int(res["id"])
    made += 1
    inbucket = (oid % BUCKETS) < PCT
    print("TRY|" + str(oid) + "|" + str(res.get("order_no")) + "|mod=" + str(oid % BUCKETS)
          + "|" + ("IN" if inbucket else "OUT"))
    if inbucket:
        print("RESULT|OK|target=" + str(oid) + " created=" + str(made))
        raise SystemExit(0)

print("RESULT|LIMIT|created=" + str(made) + " 笔仍未命中桶内，⛔ 停手")
PYEOF
"""


def _sql(query: str) -> list[str]:
    env = _prodssh.read_env()
    d = _prodssh.parse_db_url(env["DATABASE_URL"])
    sh = ("export MYSQL_PWD='%s'\nmysql -N -B -u'%s' -h'%s' -P%s '%s' -e \"%s\" 2>&1\n"
          % (d.get("password", ""), d.get("user"), d.get("host", "127.0.0.1"),
             d.get("port") or 3306, d.get("db"), query.replace('"', '\\"')))
    return [x for x in _prodssh.ssh_lines(sh, timeout=90) if x and not x.startswith("ERROR")]


def distance_to_bucket() -> dict:
    """只读：现在离下一个桶内 id 还有多远。"""
    rows = _sql("select max(id) from orders;")
    mx = int(rows[0].split("\t")[0])
    nxt = mx + 1
    while (nxt % BUCKETS) >= CANARY_PERCENT:
        nxt += 1
    return {"max_id": mx, "next_in_bucket": nxt, "need": nxt - mx}


def selftest() -> int:
    bad = seen = 0

    def chk(label: str, got, want) -> None:
        nonlocal bad, seen
        seen += 1
        ok = got == want
        print(("  OK   " if ok else "  BAD  ") + label + " -> " + str(got)
              + ("" if ok else " (期望 " + str(want) + ")"))
        bad += 0 if ok else 1

    chk("桶判据与后端同形（BUCKETS=100 / pct=30）", (BUCKETS, CANARY_PERCENT), (100, 30))
    chk("目标地址是 shipper_addresses.id=5 的那一串",
        ADDRESS, "塘厦林村工业区21号 3栋1063室")
    chk("货主是测试号段里的 183", SHIPPER_ID, 183)
    chk("司机是测试号段里的 184（⛔ 不是那 6 个真实司机）", DRIVER_ID, 184)
    chk("⛔ 远端脚本里留着硬上限（少了它会无限造单）", "made < MAXN" in _REMOTE, True)
    chk("⛔ 落在桶外的每一次尝试也都打出来（不许只留成功那一条）",
        '"OUT" if inbucket' not in _REMOTE and '("IN" if inbucket else "OUT")' in _REMOTE, True)
    chk("⛔ 走实例直连 8111（经 nginx 的明文登录会被 426 拒掉）",
        "127.0.0.1:8111" in _REMOTE, True)
    chk("备注就是 test_run_id（身份标记的辅助层）", REMARK, RUN_ID)
    print("")
    print("P4-① 自检：" + str(seen - bad) + "/" + str(seen) + " 通过")
    return 1 if bad else 0


def main() -> int:
    args = sys.argv[1:]
    if "--selftest" in args:
        return selftest()

    info = distance_to_bucket()
    print("== 现状（只读） ==")
    print("  当前最大订单 id      : " + str(info["max_id"])
          + "（mod 100 = " + str(info["max_id"] % BUCKETS) + "）")
    print("  下一个桶内 id        : " + str(info["next_in_bucket"]))
    print("  还差                : " + str(info["need"]) + " 笔")
    print("  预注册目标地址       : " + ADDRESS)
    print("  预注册 run_id       : " + RUN_ID)

    if "--dry-run" in args:
        print("")
        print("（--dry-run：⛔ 什么都没写）")
        return 0

    script = (_REMOTE.replace("@PY@", _prodssh.VENV_PY)
              .replace("@OP@", repr(OPERATOR)).replace("@OPPW@", repr(OPERATOR_PASSWORD))
              .replace("@SHIPPER@", str(SHIPPER_ID)).replace("@ADDR@", repr(ADDRESS))
              .replace("@REMARK@", repr(REMARK)).replace("@BUCKETS@", str(BUCKETS))
              .replace("@PCT@", str(CANARY_PERCENT)).replace("@MAXN@", str(MAX_CREATE)))
    print("")
    print("== 执行（会写生产） ==")
    out = _prodssh.ssh_lines(script, timeout=600)
    tries: list[dict] = []
    target = None
    result = ""
    for ln in out:
        print("  " + ln)
        if ln.startswith("TRY|"):
            f = ln.split("|")
            tries.append({"order_id": int(f[1]), "order_no": f[2],
                          "mod": int(f[3].split("=")[1]), "in_bucket": f[4] == "IN"})
        if ln.startswith("RESULT|"):
            f = ln.split("|")
            result = f[1]
            if result == "OK":
                # ⚠️ 第一版写成 f[2].split("=")[1] —— 但那一格是
                #    "target=20900 created=47"，split 出来带尾巴，当场 ValueError，
                #    运行记录因此没写成（订单已经建出去了）。改成只认 "target=" 那一段数字。
                for part in f[2].split():
                    if part.startswith("target="):
                        target = int(part.split("=", 1)[1])

    # 只看库复核
    ids = ",".join(str(t["order_id"]) for t in tries) or "0"
    rows = _sql("select id, order_no, shipper_id, status, coalesce(freight_fee,''), "
                "left(coalesce(remark,''),40) from orders where id in (" + ids + ") order by id;")
    print("")
    print("== 读回复核（只看库） ==")
    for r in rows:
        print("  " + r.replace("\t", " | "))
    print("  库里查到 " + str(len(rows)) + " 笔，运行记录里有 " + str(len(tries)) + " 笔")

    rec = {
        "run_id": RUN_ID, "scenario_id": SCENARIO,
        "preregistered": {
            "bucket_rule": "order_id % 100 < 30（与 pricing_runtime.policy_for 同形）",
            "address": ADDRESS,
            "address_reason": "shipper_addresses.id=5 的 detail_address ⇒ 价目 #5 的 route_id=5 命中",
            "shipper_id": SHIPPER_ID, "driver_id": DRIVER_ID,
            "expected_when_in_bucket": {
                "kind": "freight_template", "resolution": "contract",
                "agreed": True, "override": False,
                "algorithm_amount": "45.00", "final_amount": "45.00",
            },
        },
        "attempts": tries,
        "attempt_count": len(tries),
        "in_bucket_ids": [t["order_id"] for t in tries if t["in_bucket"]],
        "target_order_id": target,
        "result": result,
    }
    RECORD_DIR.mkdir(exist_ok=True)
    rec_path = RECORD_DIR / ("p4a-attempts-" + RUN_ID + ".json")
    rec_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    print("")
    print("运行记录：" + str(rec_path))
    if target:
        print("✅ 桶内目标单 = #" + str(target) + "（下一步：派给司机 " + str(DRIVER_ID)
              + "，运费填算法值 45.00，⛔ 不改价）")
        return 0
    print("⛔ 没拿到桶内单（result=" + result + "）—— ⛔ 不许当成通过")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
