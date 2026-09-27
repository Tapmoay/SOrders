# -*- coding: utf-8 -*-
"""**P4-② 双实例一致性**（R4-49 §九 V10）：同一份输入分别打两个**正在运行**的生产实例，比四项。

## 它证明什么、不证明什么

要证的命题：

    两个**当前正在运行**的生产实例，对**同一份** Pricing 输入，实际执行出了**相同**的 Decision。

⛔ 为什么不能只比「两次结果一样」：
  · 走 nginx 的负载均衡入口连打两次 —— **不知道请求落到哪个实例**，证不了；
  · 拿 /health 的 canary=30 当证据 —— 那只证了配置，没证 Decision；
  · 用两个新起的进程各算一遍 —— 那叫「装配一致 + 独立进程计算一致」，叫不了「双实例生产行为一致」。

## 它怎么做（用户 2026-09-27 定的出口条件）

    A.kind == B.kind  AND  A.resolution == B.resolution
    A.contract.name == B.contract.name  AND  A.contract.version == B.contract.version
    A.quoted_fee == B.quoted_fee
    AND  A/B 各自确认命中了指定实例（响应里的 pid == ss -lntp 那个 pid）
    AND  请求前后**零业务写入**
    AND  输入完全相同（同一个 order / driver / claimed_fee，且订单本身没变）

## ⛔ 几条硬限制

1. **在生产机上跑**：127.0.0.1:8111 / :8112 只有在生产机上才是那两个实例 —— 脚本自己 SSH 过去执行；
2. **⛔ 不走负载均衡入口**：显式 http://127.0.0.1:<port>；
3. **⛔ 不改 Canary、不写库、不派单** —— 用的是只读诊断端点；
4. **证据落三份**：R4V-P4B-A.json / R4V-P4B-B.json / comparison.json。

## 用法

    python _tools/ops/_r4v_p4b.py --dry-run     # 只读：看两个实例在不在、pid 是多少
    python _tools/ops/_r4v_p4b.py               # 真跑（只读请求）
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _prodssh  # noqa: E402

RUN_ID = "R4V-20260927-03"
ORDER_ID = 20900
DRIVER_ID = 184
CLAIMED_FEE = "45.00"
PORTS = (8111, 8112)
OPERATOR = "13800000001"
OPERATOR_PASSWORD = "123321"
RECORD_DIR = Path(__file__).resolve().parent / 'r4v_records'

_REMOTE = r"""set +e
@PY@ - <<'PYEOF'
import json, subprocess, urllib.error, urllib.request

PORTS = @PORTS@
ORDER = @ORDER@
DRIVER = @DRIVER@
FEE = @FEE@
OP = @OP@
OPPW = @OPPW@


# 查库。⛔ 失败**不许静默返回空串** —— 第一版就是这样空过的：
# SQL 语法错 -> stdout 空 -> 前后都是空串 -> 判「相同」= 假绿（本次实测踩到）。
# ⚠️ 这一段在 _REMOTE 那个原始三引号字符串**里面**，⛔ 不许再出现三引号
#    （会把外层字符串提前收掉，Python 当场 SyntaxError —— 本轮实测踩了两次）。
def sql(q):
    r = subprocess.run(["mysql", "-N", "-B", "-e", q], capture_output=True, text=True)
    if r.returncode != 0:
        print("RESULT|FAIL|SQL 失败：" + (r.stderr or "")[:300])
        raise SystemExit(0)
    return r.stdout.strip()


# ⚠️ 表名必须**带库名**（sorders.orders）：远端那条 mysql 没指定库，
#    裸 orders 会报 "ERROR 1046 No database selected"（本轮实测踩到，被新加的护栏当场拦下）。
STATE_Q = ("select id, status, coalesce(freight_fee,''), updated_at, "
           "coalesce(freight_rule_snapshot,'') from sorders.orders where id = " + str(ORDER) + ";")


def http(port, path, token=None):
    url = "http://127.0.0.1:" + str(port) + path
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()[:300]


listen = {}
for p in PORTS:
    listen[p] = subprocess.run(["bash", "-lc", "ss -lntp 2>/dev/null | grep :%d " % p],
                               capture_output=True, text=True).stdout.strip()
    print("LISTEN|" + str(p) + "|" + listen[p])

body = json.dumps({'username': OP, 'password': OPPW}).encode()
req = urllib.request.Request("http://127.0.0.1:" + str(PORTS[0]) + "/api/v1/auth/login",
                             data=body, method='POST')
req.add_header("Content-Type", "application/json")
try:
    with urllib.request.urlopen(req, timeout=25) as r:
        token = json.loads(r.read().decode())["access_token"]
except Exception as exc:
    print("RESULT|FAIL|登录失败 " + repr(exc)[:200]); raise SystemExit(0)
print("STEP|令牌已取得")

PATH_Q = ("/api/v1/diagnostics/orders/" + str(ORDER)
          + "/pricing-decision?driver_id=" + str(DRIVER) + "&claimed_fee=" + FEE)

for p in PORTS:
    before = sql(STATE_Q)
    s, resp_body = http(p, PATH_Q, token)
    after = sql(STATE_Q)
    print("CALL|" + str(p) + "|" + str(s))
    print("BEFORE|" + str(p) + "|" + before.replace(chr(9), "|"))
    print("RESP|" + str(p) + "|" + json.dumps(resp_body, ensure_ascii=False))
    print("AFTER|" + str(p) + "|" + after.replace(chr(9), "|"))
print("DONE")
PYEOF
"""


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def grep_line(out, prefix):
    return [x[len(prefix):] for x in out if x.startswith(prefix)]


def selftest() -> int:
    bad = seen = 0

    def chk(label, got, want):
        nonlocal bad, seen
        seen += 1
        ok = got == want
        print(("  OK   " if ok else "  BAD  ") + label + " -> " + str(got)
              + ("" if ok else " (期望 " + str(want) + ")"))
        bad += 0 if ok else 1

    chk("两个端口就是两个实例", PORTS, (8111, 8112))
    chk("⛔ 远端脚本只用 127.0.0.1 打端口，不打任何外部入口",
        "127.0.0.1:" in _REMOTE and "https://" not in _REMOTE, True)
    chk("⛔ 远端脚本里留着零写入判据（前后各读一次订单四列+快照）",
        _REMOTE.count("STATE_Q") >= 3, True)
    chk("⛔ 远端脚本里读 ss -lntp（实例身份靠它钉死）", "ss -lntp" in _REMOTE, True)
    chk("⛔ 用的是只读诊断端点，⛔ 不是派单",
        "/diagnostics/orders/" in _REMOTE and "/assign" not in _REMOTE, True)
    chk("⛔ SQL 失败不许静默返回空串", "if r.returncode != 0:" in _REMOTE, True)
    chk("⛔ STATE_Q 里没有 chr(39)chr(39) 那种把 SQL 写坏的拼法",
        "chr(39)" not in _REMOTE and "coalesce(freight_fee,'')" in _REMOTE, True)
    chk("⛔ 查库语句带库名（远端 mysql 没选库，裸表名会 1046）",
        "from sorders.orders" in _REMOTE, True)
    chk("⛔ 零写入判据不许空过（before 必须非空）",
        'bool(load(t)["zero_write_proof"]["before"].strip())' in __import__("inspect").getsource(main), True)
    print("")
    print("P4-② 自检：" + str(seen - bad) + "/" + str(seen) + " 通过")
    return 1 if bad else 0


def main() -> int:
    args = sys.argv[1:]
    if "--selftest" in args:
        return selftest()

    if "--dry-run" in args:
        out = _prodssh.ssh_lines(
            "ss -lntp 2>/dev/null | grep -E ':8111 |:8112 ' ; echo ---; "
            "for P in 8111 8112; do printf 'health %s -> ' \"$P\"; "
            "curl -s -m 8 http://127.0.0.1:$P/health; echo; done", timeout=90)
        for l in out:
            print("  " + l)
        print("（--dry-run：⛔ 什么都没写、也没打诊断端点）")
        return 0

    script = (_REMOTE.replace('@PY@', _prodssh.VENV_PY)
              .replace('@PORTS@', str(list(PORTS))).replace('@ORDER@', str(ORDER_ID))
              .replace('@DRIVER@', str(DRIVER_ID)).replace('@FEE@', repr(CLAIMED_FEE))
              .replace('@OP@', repr(OPERATOR)).replace('@OPPW@', repr(OPERATOR_PASSWORD)))
    print("== 打两个实例（只读） ==")
    out = _prodssh.ssh_lines(script, timeout=300)
    for l in out:
        print("  " + l[:400])

    listen = {int(l.split("|")[0]): l.split("|", 1)[1] for l in grep_line(out, "LISTEN|")}
    resp = {}
    for l in grep_line(out, "RESP|"):
        port_s, body = l.split("|", 1)
        try:
            resp[int(port_s)] = json.loads(body)
        except Exception:
            resp[int(port_s)] = {"_raw": body}
    before = {int(l.split("|")[0]): l.split("|", 1)[1] for l in grep_line(out, "BEFORE|")}
    after = {int(l.split("|")[0]): l.split("|", 1)[1] for l in grep_line(out, "AFTER|")}

    if len(resp) != 2:
        print("⛔ 没拿到两个实例的响应 —— ⛔ 不许当成通过")
        return 2

    RECORD_DIR.mkdir(exist_ok=True)
    input_hash = _hash(json.dumps({"order_id": ORDER_ID, "driver_id": DRIVER_ID,
                                   "claimed_fee": CLAIMED_FEE}, sort_keys=True))
    for p in PORTS:
        pid_in_listen = None
        for tok in listen.get(p, "").replace(",", " ").split():
            if tok.startswith("pid="):
                pid_in_listen = int(tok[4:].split(",")[0])
        rec = {
            "run_id": RUN_ID, "port": p,
            "instance_fingerprint": {
                "listen_line": listen.get(p, ""), "pid_from_listen": pid_in_listen,
                "pid_from_response": resp[p].get("pid"),
                "listen_matches_response": pid_in_listen == resp[p].get("pid"),
                "resolver": resp[p].get("resolver"),
            },
            "input": {"order_id": ORDER_ID, "driver_id": DRIVER_ID, "claimed_fee": CLAIMED_FEE},
            "input_hash": input_hash,
            "raw_response": resp[p],
            "zero_write_proof": {
                "before": before.get(p, ""), "after": after.get(p, ""),
                "identical": before.get(p, "") == after.get(p, ""),
            },
        }
        path = RECORD_DIR / ("R4V-P4B-" + ("A" if p == PORTS[0] else "B") + ".json")
        path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        print("  写出 " + str(path))

    A, B = resp[PORTS[0]], resp[PORTS[1]]

    def ck(name, x, y):
        return {"field": name, "A": x, "B": y, "pass": x == y and x is not None}

    checks = [
        ck("kind", A.get("kind"), B.get("kind")),
        ck("resolution", A.get("resolution"), B.get("resolution")),
        ck("contract.name", (A.get("contract") or {}).get("name"),
           (B.get("contract") or {}).get("name")),
        ck("contract.version", (A.get("contract") or {}).get("version"),
           (B.get("contract") or {}).get("version")),
        ck("quoted_fee", A.get("quoted_fee"), B.get("quoted_fee")),
    ]

    def load(t):
        return json.loads((RECORD_DIR / ("R4V-P4B-" + t + ".json")).read_text(encoding="utf-8"))

    inst_ok = all(load(t)["instance_fingerprint"]["listen_matches_response"] for t in ("A", "B"))
    # ⛔ 「前后相同」必须**在非空的前提下**才算数 —— 空串 == 空串 不是零写入证明
    zw_ok = all(load(t)["zero_write_proof"]["identical"]
                and bool(load(t)["zero_write_proof"]["before"].strip())
                for t in ("A", "B"))
    hashes_ok = len({load(t)["input_hash"] for t in ("A", "B")}) == 1
    comp = {
        "run_id": RUN_ID,
        "preregistered": {
            "A.kind==B.kind": True, "A.resolution==B.resolution": True,
            "A.contract.name==B.contract.name": True,
            "A.contract.version==B.contract.version": True,
            "A.quoted_fee==B.quoted_fee": True,
            "A/B 均确认命中指定实例": True, "请求前后无业务写入": True,
            "输入完全相同": True,
        },
        "checks": checks,
        "instance_identity_ok": inst_ok,
        "zero_write_ok": zw_ok,
        "same_input_ok": hashes_ok,
        "verdict": ("PASS" if (all(c["pass"] for c in checks) and inst_ok
                              and zw_ok and hashes_ok) else "FAIL"),
    }
    cpath = RECORD_DIR / "R4V-P4B-comparison.json"
    cpath.write_text(json.dumps(comp, ensure_ascii=False, indent=2), encoding="utf-8")

    print("")
    print("== 比较 ==")
    for c in checks:
        print(("  OK   " if c["pass"] else "  BAD  ") + c["field"]
              + "  A=" + str(c["A"]) + "  B=" + str(c["B"]))
    print("  实例身份（响应 pid == ss -lntp pid）：" + ("OK" if inst_ok else "BAD"))
    print("  零写入（前后逐字节相同）：" + ("OK" if zw_ok else "BAD"))
    print("  同一输入（input hash 相同）：" + ("OK" if hashes_ok else "BAD"))
    print("")
    print("P4-② 判定：" + comp["verdict"])
    print("比较记录：" + str(cpath))
    return 0 if comp["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())