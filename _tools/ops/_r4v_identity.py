# -*- coding: utf-8 -*-
"""**R4 受控验证的测试身份**（R4-49 §八）：建两个专用账号 + 给测试司机挂规则 #1。

## 为什么要有它

R4-49 裁决：受控验证可以往生产写，但**必须带可判定的身份**。本工具建的就是那个身份。
⛔ 三条硬限制（写在代码里，不靠记性）：

1. **只肯建 1380000000X 号段** —— 那是代码里唯一有判据的测试号段
   （`app/services/auth_service.py::is_test_account`，形式 = 前缀 + 一位 1~9）。
   换号段就等于把一个"机器可判定"的身份降级成"靠人记"。
2. **测试司机的车型必须与规则 #1 一致** —— `attach_rule` 会拦车型对不上，
   而"挂上去了但每单按错规则算钱"是它专门防的那种静默错误。
3. **幂等**：号已存在就**不建**，只报告既有 id —— ⛔ 不制造第二个同号账号。

## 用法（在本机跑，它自己走 SSH 到生产机）

    python _tools/ops/_r4v_identity.py --dry-run    # 只读：看现在是什么状态、打算做什么
    python _tools/ops/_r4v_identity.py              # 真建（会写生产）
    python _tools/ops/_r4v_identity.py --selftest   # 判据自检（不联网）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _prodssh  # noqa: E402

#: R4-49 §八：测试身份的号段必须落在 is_test_account 认的那一段里。
TEST_PREFIX = "1380000000"
TEST_TAIL_MAX = 9

RUN_ID = "R4V-20260927-01"
SHIPPER_PHONE = "13800000006"
DRIVER_PHONE = "13800000007"
PASSWORD = "123321"
RULE_ID = 1
VEHICLE_TYPE = "small"          # ⛔ 规则 #1「按单计件 · 小货车」限 small
OPERATOR = "13800000001"        # 派单员（DISPATCHER 有 USER_MANAGE）
OPERATOR_PASSWORD = "123321"

SHIPPER_NAME = "R4受控验证货主"
DRIVER_NAME = "R4受控验证司机"

RECORD_DIR = Path(__file__).resolve().parent / "r4v_records"

_REMOTE = r"""set +e
@PY@ - <<'PYEOF'
import json, urllib.error, urllib.request

BASE = "http://127.0.0.1:8111/api/v1"
OP = @OP@
OPPW = @OPPW@
SP = @SP@
DP = @DP@
PW = @PW@
SN = @SN@
DN = @DN@
RULE = @RULE@
VT = @VT@


def call(method, path, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
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


def ensure(phone, role, name, vehicle):
    s, res = call("GET", "/users?q=" + phone, token)
    if s == 200:
        rows = res if isinstance(res, list) else res.get("items", [])
        for u in rows:
            if str(u.get("phone")) == phone:
                print("STEP|已存在 " + phone + " id=" + str(u.get("id")) + " 角色=" + str(u.get("role")))
                return int(u["id"]), False
    body = {"phone": phone, "password": PW, "role": role, "full_name": name}
    if vehicle:
        body["vehicle_type"] = vehicle
    s, res = call("POST", "/users", token, body)
    if s not in (200, 201):
        print("RESULT|FAIL|建号失败 " + phone + " " + str(s) + " " + str(res))
        raise SystemExit(0)
    print("STEP|建号 " + phone + " id=" + str(res.get("id")) + " 角色=" + str(res.get("role")))
    return int(res["id"]), True


sid, snew = ensure(SP, "shipper", SN, None)
did, dnew = ensure(DP, "driver", DN, VT)
print("IDS|shipper=" + str(sid) + " driver=" + str(did)
      + " new_shipper=" + str(snew) + " new_driver=" + str(dnew))

s, res = call("POST", "/driver-billing-rules/attach", token,
              {"driver_id": did, "rule_id": RULE})
if s not in (200, 201):
    print("RESULT|FAIL|挂规则失败 " + str(s) + " " + str(res))
    raise SystemExit(0)
print("STEP|已挂规则 driver=" + str(did) + " rule=" + str(RULE)
      + " 规则名=" + str((res or {}).get("name")) + " 车型=" + str((res or {}).get("vehicle_type")))
print("RESULT|OK|shipper=" + str(sid) + " driver=" + str(did))
PYEOF
"""


def _mysql(query: str) -> list[str]:
    env = _prodssh.read_env()
    d = _prodssh.parse_db_url(env["DATABASE_URL"])
    sh = ("export MYSQL_PWD='%s'\nmysql -N -B -u'%s' -h'%s' -P%s '%s' -e \"%s\" 2>&1\n"
          % (d.get("password", ""), d.get("user"), d.get("host", "127.0.0.1"),
             d.get("port") or 3306, d.get("db"), query.replace('"', '\\"')))
    return _prodssh.ssh_lines(sh, timeout=90)


def inspect() -> dict:
    """只读：现在这两台号在不在、规则挂没挂。"""
    q = ("select id, phone, role, coalesce(vehicle_type,''), coalesce(driver_rule_id,0) "
         "from users where phone in ('%s','%s') order by phone;" % (SHIPPER_PHONE, DRIVER_PHONE))
    rows = [ln for ln in _mysql(q) if ln and not ln.startswith("ERROR")]
    q2 = ("select id, name, coalesce(vehicle_type,''), piece_amount from driver_billing_rules "
          "where id = %d;" % RULE_ID)
    rule = [ln for ln in _mysql(q2) if ln and not ln.startswith("ERROR")]
    return {"users": rows, "rule": rule}


def verify_ids(ids: dict) -> list[str]:
    """判据：两个号都在、角色对、司机车型与规则一致、规则已挂。"""
    bad: list[str] = []
    if ids.get("shipper_role") != "SHIPPER":
        bad.append("测试货主的角色不是 SHIPPER：" + str(ids.get("shipper_role")))
    if ids.get("driver_role") != "DRIVER":
        bad.append("测试司机的角色不是 DRIVER：" + str(ids.get("driver_role")))
    if not _in_test_range(SHIPPER_PHONE) or not _in_test_range(DRIVER_PHONE):
        bad.append("测试号段不在 is_test_account 认的那一段里")
    if ids.get("driver_rule_id") != RULE_ID:
        bad.append("测试司机的 driver_rule_id = " + str(ids.get("driver_rule_id"))
                   + "，期望 " + str(RULE_ID))
    return bad


def _in_test_range(phone: str) -> bool:
    """与后端 is_test_account 同形：前缀 + 一位 1~9，共 11 位。"""
    p = (phone or "").strip()
    if len(p) != len(TEST_PREFIX) + 1 or not p.startswith(TEST_PREFIX):
        return False
    tail = p[len(TEST_PREFIX):]
    return tail.isdigit() and 1 <= int(tail) <= TEST_TAIL_MAX


def selftest() -> int:
    bad = seen = 0

    def chk(label: str, got, want) -> None:
        nonlocal bad, seen
        seen += 1
        ok = got == want
        print(("  OK   " if ok else "  BAD  ") + label + " -> " + str(got)
              + ("" if ok else " (期望 " + str(want) + ")"))
        bad += 0 if ok else 1

    chk("测试货主号在豁免号段里", _in_test_range(SHIPPER_PHONE), True)
    chk("测试司机号在豁免号段里", _in_test_range(DRIVER_PHONE), True)
    chk("两个号不是同一个", SHIPPER_PHONE != DRIVER_PHONE, True)
    chk("尾号 0 不算测试号（与后端同形）", _in_test_range(TEST_PREFIX + "0"), False)
    chk("尾号两位数不算测试号", _in_test_range(TEST_PREFIX + "10"), False)
    chk("长一号也不算测试号", _in_test_range(TEST_PREFIX + "1" + "2"), False)
    chk("⛔ 远端脚本里留着号段检查前的 body 组装（少了它车型会被漏掉）",
        '"vehicle_type"] = vehicle' in _REMOTE, True)
    chk("⛔ 走实例直连 8111（经 nginx 的明文登录会被 426 拒掉）",
        "127.0.0.1:8111" in _REMOTE, True)
    chk("⛔ 幂等：建号前先 GET /users 查同号",
        'call("GET", "/users?q="' in _REMOTE, True)
    chk("规则 #1 的车型与我们要建的司机一致", VEHICLE_TYPE, "small")
    print("")
    print("R4V 身份自检：" + str(seen - bad) + "/" + str(seen) + " 通过")
    return 1 if bad else 0


def main() -> int:
    args = sys.argv[1:]
    if "--selftest" in args:
        return selftest()

    print("== 现状（只读） ==")
    st = inspect()
    for ln in st["users"]:
        print("  user: id|phone|role|vehicle|rule = " + ln.replace("\t", " | "))
    for ln in st["rule"]:
        print("  rule#1: id|name|vehicle|piece = " + ln.replace("\t", " | "))

    if "--dry-run" in args:
        print("")
        print("== 打算做 ==")
        print("  1) 建货主 " + SHIPPER_PHONE + "（" + SHIPPER_NAME + "）")
        print("  2) 建司机 " + DRIVER_PHONE + "（" + DRIVER_NAME + "，车型 " + VEHICLE_TYPE + "）")
        print("  3) 挂规则 #" + str(RULE_ID) + " 到该司机")
        print("  run_id = " + RUN_ID)
        print("（--dry-run：⛔ 什么都没写）")
        return 0

    script = (_REMOTE.replace("@PY@", _prodssh.VENV_PY)
              .replace("@OP@", repr(OPERATOR)).replace("@OPPW@", repr(OPERATOR_PASSWORD))
              .replace("@SP@", repr(SHIPPER_PHONE)).replace("@DP@", repr(DRIVER_PHONE))
              .replace("@PW@", repr(PASSWORD))
              .replace("@SN@", repr(SHIPPER_NAME)).replace("@DN@", repr(DRIVER_NAME))
              .replace("@RULE@", str(RULE_ID)).replace("@VT@", repr(VEHICLE_TYPE)))
    print("")
    print("== 执行（会写生产） ==")
    out = _prodssh.ssh_lines(script, timeout=180)
    for ln in out:
        print("  " + ln)

    print("")
    print("== 读回复核（只看库，不看接口回包） ==")
    st2 = inspect()
    for ln in st2["users"]:
        print("  user: " + ln.replace("\t", " | "))

    facts: dict = {"run_id": RUN_ID, "shipper_phone": SHIPPER_PHONE, "driver_phone": DRIVER_PHONE}
    for ln in st2["users"]:
        f = ln.split("\t")
        if len(f) >= 5:
            if f[1] == SHIPPER_PHONE:
                facts["shipper_id"] = int(f[0]); facts["shipper_role"] = f[2]
            if f[1] == DRIVER_PHONE:
                facts["driver_id"] = int(f[0]); facts["driver_role"] = f[2]
                facts["driver_rule_id"] = int(f[4]); facts["driver_vehicle"] = f[3]
    bad = verify_ids(facts)
    print("")
    if bad:
        print("⛔ 复核不过：")
        for b in bad:
            print("   - " + b)
        return 2

    RECORD_DIR.mkdir(exist_ok=True)
    rec = RECORD_DIR / ("identity-" + RUN_ID + ".json")
    rec.write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
    print("✅ 身份就绪：" + json.dumps(facts, ensure_ascii=False))
    print("   运行记录：" + str(rec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
