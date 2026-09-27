# -*- coding: utf-8 -*-
"""**Canary 观察期的有限写**（R4-34）：在**一张明明白白的演练单**上走真实链路。

## 为什么要有它

观察窗口与 T0/T1/T2 冻结实验都需要**真实的计价决策**，而生产上除了一条真实派单没有别的
办法产生它。这一步在发布器的第 8 步（`business`）里是**故意不自动化**的 ——
因为它要往生产写业务数据。

## ⛔ 三条硬限制（写在代码里，不靠记性）

1. **只肯建演练单**：送货地址里必须带标记 `R4 演练单`；
2. **只肯动演练单**：`refreight` / `recall` 之前先查库核对那条标记，⛔ 不是演练单一律拒绝 ——
   绝不碰任何真实客户的单；
3. **撤销而不是删除**（照用户 2026-09-20 的硬规矩）。

## 用法（在**本机**跑，它自己走 SSH 到生产机、经 nginx 打真实接口）

    python _tools/ops/_canary_live_write.py --phase create
    python _tools/ops/_canary_live_write.py --phase refreight --order <id>
    python _tools/ops/_canary_live_write.py --phase cancel    --order <id>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _prodssh  # noqa: E402

MARK = "R4 演练单"
DRIVER = 3
SHIPPER = 2
FEE_1 = "66.00"
FEE_2 = "77.00"

_REMOTE = r"""set +e
@PY@ - <<'PYEOF'
import json, subprocess, urllib.error, urllib.request

# ⛔ 走**实例直连**（8111），不走 nginx 的 80：
#    经 nginx 的明文请求会被 `core/transport.py` 用 **426** 拒掉（登录不许走明文，
#    这是 2026-09-19 外部检查 C-1 的修法），而**没有 X-Forwarded-Proto 的请求**
#    （= 没经过 nginx 的本机/内部调用）按那份设计的原话是**不拦**的 ——
#    生产上 8111/8112 只监听 127.0.0.1，对外不可达，所以这条路不是公开入口。
#    ⚠️ 第一版写成 http://127.0.0.1/api/v1，登录当场吃了 426。
BASE = "http://127.0.0.1:8111/api/v1"
MARK = @MARK@
PHASE = @PHASE@
ORDER = @ORDER@
DRIVER = @DRIVER@
SHIPPER = @SHIPPER@
FEE_1 = @FEE1@
FEE_2 = @FEE2@


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


def sql(q):
    return subprocess.run(["mysql", "-N", "-B"], input=q,
                          capture_output=True, text=True).stdout.strip()


def snap(oid):
    return sql("select o.id, o.order_no, o.status, o.freight_fee, "
               "coalesce(json_unquote(json_extract(o.freight_rule_snapshot, '$.pricing.kind')), '(无)'), "
               "coalesce(json_unquote(json_extract(o.freight_rule_snapshot, '$.pricing.reason')), '(无)'), "
               # ⚠️ `at` 在快照**顶层**（payload['at']），⛔ 不是 $.pricing.at —— 第一版写错，读出来永远是 (无)
               "coalesce(json_unquote(json_extract(o.freight_rule_snapshot, '$.at')), '(无)') "
               "from sorders.orders o where o.id = " + str(oid))


def addr_of(oid):
    return sql("select coalesce(address_detail, '') from sorders.orders where id = " + str(oid))


s = call("POST", "/auth/login", body={"username": "13800000001", "password": "123321"})
if s[0] != 200:
    print("RESULT|FAIL|登录失败 " + str(s[0]) + " " + str(s[1]))
    raise SystemExit(0)
token = s[1]["access_token"]

if PHASE == "create":
    s, res = call("POST", "/orders", token, {
        "shipper_id": SHIPPER,
        "address_detail": MARK,
        "lines": [{"product_name_snapshot": "演练货", "quantity": 1,
                   "unit_price": "10", "line_total": "10"}],
    })
    if s not in (200, 201):
        print("RESULT|FAIL|建单失败 " + str(s) + " " + str(res))
        raise SystemExit(0)
    oid = int(res["id"])
    print("STEP|建单 id=" + str(oid) + " " + str(res.get("order_no")) + " 状态=" + str(res.get("status")))
    s, res = call("POST", "/orders/" + str(oid) + "/assign", token,
                  {"driver_id": DRIVER, "freight_fee": float(FEE_1), "collect_cash": False})
    if s not in (200, 201):
        print("RESULT|FAIL|派单失败 " + str(s) + " " + str(res))
        print("ROLLBACK|建单成功但派单失败，单 id=" + str(oid))
        raise SystemExit(0)
    print("STEP|派单 id=" + str(res.get("id")) + " 状态=" + str(res.get("status"))
          + " 运费=" + str(res.get("freight_fee")))
    print("SNAP|" + snap(oid).replace(chr(9), "|"))
    print("RESULT|OK|" + str(oid))
    raise SystemExit(0)

if PHASE in ("refreight", "cancel"):
    addr = addr_of(ORDER)
    if MARK not in addr:
        print("RESULT|REFUSE|这张单的地址里没有演练标记（" + repr(addr[:40]) + "）—— 绝不碰真实单")
        raise SystemExit(0)
    if PHASE == "refreight":
        s, res = call("POST", "/orders/" + str(ORDER) + "/freight", token, {"freight_fee": float(FEE_2)})
        print("STEP|再写一次运费 -> " + str(s))
        if s not in (200, 201):
            print("RESULT|FAIL|" + str(res))
            raise SystemExit(0)
    else:
        # ⚠️ 是 **/cancel（撤销）**，不是 /recall（撤回派单）：
        #    `OrderRecallBody.reason` 是必填的，发空 body 会 422 ——
        #    第一版发 `{}` 吃了 422，单子还留在 DISPATCHED 上（实测）。
        s, res = call("POST", "/orders/" + str(ORDER) + "/cancel", token)
        print("STEP|撤销 -> " + str(s))
    print("SNAP|" + snap(ORDER).replace(chr(9), "|"))
    print("RESULT|OK|" + str(ORDER))
    raise SystemExit(0)

print("RESULT|FAIL|不认识的 phase：" + PHASE)
PYEOF
"""


def parse_result(out: str) -> tuple[str, str]:
    """远端打的 `RESULT|<码>|<说明>` → (码, 说明)。⛔ 一行都没有就是**空码 = 没结论**。

    ⚠️ 为什么抠成纯函数（R4-45）：本工具是**唯一会往生产写业务数据**的那一个，
    而它的结论全靠远端这一行。以前这段藏在 `run()` 里、只能在真跑时验 ——
    形状一变（少了说明、多打了一行）就会退化成"⛔ 没拿到结论"，而没人当场知道。
    """
    code = msg = ""
    for ln in out.splitlines():
        if ln.startswith("RESULT|"):
            parts = ln.split("|")
            code, msg = parts[1], (parts[2] if len(parts) > 2 else "")
    return code, msg


def selftest() -> int:
    """⛔ 它会写**生产** —— 三条硬限制与回传解析都必须有机器证明，⛔ 不靠记性。"""
    bad = 0
    seen = 0

    def chk(label: str, got, want) -> None:
        nonlocal bad, seen
        seen += 1
        ok = got == want
        print(("  OK   " if ok else "  BAD  ") + label + " → " + str(got)
              + ("" if ok else "（期望 " + str(want) + "）"))
        bad += 0 if ok else 1

    chk("回传解析：正常一行", parse_result("STEP|x\nRESULT|OK|123\n"), ("OK", "123"))
    chk("回传解析：没有说明也认（⛔ 不许因为少一段就说「没拿到结论」）",
        parse_result("RESULT|REFUSE|"), ("REFUSE", ""))
    chk("回传解析：完全没有 RESULT ⇒ 空码（= 没结论，⛔ 不许当成完成）",
        parse_result("STEP|x\n"), ("", ""))
    chk("回传解析：多行时以**最后一行**为准", parse_result("RESULT|FAIL|a\nRESULT|OK|b\n"), ("OK", "b"))

    chk("⛔ 远端脚本里**留着**演练单标记判据（少了它 refreight/cancel 会碰真实客户的单）",
        "if MARK not in addr:" in _REMOTE and "绝不碰真实单" in _REMOTE, True)
    chk("⛔ 远端脚本里是 /cancel（撤销），不是 /recall（撤回要必填 reason，发空 body 会 422）",
        '"/cancel"' in _REMOTE, True)
    chk("⛔ 走实例直连 8111（经 nginx 的明文请求会被 core/transport.py 用 426 拒掉）",
        "127.0.0.1:8111" in _REMOTE, True)
    chk("⛔ 两个 phase 都不许在没有 --order 时往下走",
        ('if phase in ("refreight", "cancel") and not order:' in
         __import__("inspect").getsource(main)), True)

    print("")
    print("Canary 有限写自检：" + str(seen - bad) + "/" + str(seen) + " 通过")
    return 1 if bad else 0


def run(phase: str, order: int = 0) -> tuple[str, str]:
    script = (_REMOTE.replace("@PY@", _prodssh.VENV_PY)
              .replace("@MARK@", repr(MARK))
              .replace("@PHASE@", repr(phase))
              .replace("@ORDER@", str(int(order)))
              .replace("@DRIVER@", str(DRIVER))
              .replace("@SHIPPER@", str(SHIPPER))
              .replace("@FEE1@", repr(FEE_1))
              .replace("@FEE2@", repr(FEE_2)))
    out = _prodssh.ssh_script(script, timeout=180, check=False).stdout.decode("utf-8", "replace")
    print(out.rstrip())
    return parse_result(out)


def main() -> int:
    argv = sys.argv
    if "--selftest" in argv:
        return selftest()
    phase = argv[argv.index("--phase") + 1] if "--phase" in argv else "create"
    order = int(argv[argv.index("--order") + 1]) if "--order" in argv else 0
    if phase in ("refreight", "cancel") and not order:
        print("⛔ 这两个 phase 必须给 --order")
        return 2
    code, msg = run(phase, order)
    print("")
    print({"OK": "✅ 完成：" + msg, "REFUSE": "⛔ 拒绝了：" + msg,
           "FAIL": "❌ 失败：" + msg}.get(code, "⛔ 没拿到结论（远端没打 RESULT）"))
    return 0 if code == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())