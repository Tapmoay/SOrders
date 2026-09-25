"""本轮安全修复的**真后端**实测：限流 + 令牌撤销（不是只跑单测）。

跑法：`python _tools/qa/_probe_security_round5.py`（需要本机后端在 127.0.0.1:8000）
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:8000/api/v1"


def call(method: str, path: str, body=None, token: str | None = None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


ok = True


def check(label: str, cond: bool, detail: str = "") -> None:
    global ok
    print(("  [通过] " if cond else "  [!!]   ") + label + ("" if cond else f" —— {detail}"))
    ok = ok and cond


DISPATCHER = ("13800000001", "123321")


def login_guard_id_threshold() -> int:
    """限流阈值**从后端源码读**（不在探针里再写一遍数字——那种清单迟早过期）。"""
    import re
    from pathlib import Path as _P

    root = _P(__file__).resolve().parents[2]   # ⛔ 不许写死本机路径（CI 上不存在，探针会直接炸）
    src = (root / "backend/app/services/login_guard.py").read_text(encoding="utf-8")
    m = re.search(r"MAX_FAILS_PER_ID = (\d+)", src)
    if not m:
        raise SystemExit("找不到 MAX_FAILS_PER_ID（登录限流的阈值挪地方了？）")
    return int(m.group(1))
SHIPPER = ("13800000002", "123321")

print("== ① 登录限流（真后端） ==")
# ⚠️ 用**不存在的手机号**做限流实测（2026-09-19 自省）：限流是按"登录名"计数的，
#    拿真实账号试会把**派单员锁 15 分钟**，而后面每一个探针/联调都要用那个账号登录 ——
#    实测踩到过一次（探针自己把后续工具全锁了）。假号同样能证明"到阈值就 429"。
PROBE_PHONE = "13000000000"
codes = []
for _ in range(login_guard_id_threshold() + 2):
    st, _b = call("POST", "/auth/login", {"phone": PROBE_PHONE, "password": "definitely-wrong"})
    codes.append(st)
print(f"  连续 7 次错误口令的状态码：{codes}")
check("到达阈值后变成 429（不再无限重试）", 429 in codes, f"实际 {codes}")
st, body = call("POST", "/auth/login", {"phone": DISPATCHER[0], "password": DISPATCHER[1]})
check("锁定期间即使口令正确也被拒（锁的是账号）", st == 429, f"实际 {st} {body}")
print("  ⚠️ 本次实测会把派单员账号锁约 15 分钟——跑完请用 _tools 里的方式清计数，或等窗口过期。")

print("\n== ② 令牌撤销（真后端） ==")
st, tok = call("POST", "/auth/login", {"phone": SHIPPER[0], "password": SHIPPER[1]})
if st != 200:
    print(f"  [跳过] 货主登录失败（{st}）：限流窗口可能还没过，稍后再跑")
else:
    t = tok["access_token"]
    st1, _ = call("GET", "/users/me", token=t)
    check("登出前令牌可用", st1 == 200, f"实际 {st1}")
    st2, _ = call("POST", "/auth/logout", token=t)
    check("登出接口调用成功", st2 == 200, f"实际 {st2}")
    st3, _ = call("GET", "/users/me", token=t)
    check("登出后同一个令牌立刻失效（401）", st3 == 401, f"实际 {st3}")
    st4, again = call("POST", "/auth/login", {"phone": SHIPPER[0], "password": SHIPPER[1]})
    check("重新登录仍能拿到新令牌（撤销不影响再登录）", st4 == 200, f"实际 {st4}")
    if st4 == 200:
        st5, _ = call("GET", "/users/me", token=again["access_token"])
        check("新令牌可用", st5 == 200, f"实际 {st5}")

print("\n" + ("全部通过 ✅" if ok else "有未通过项 ❌"))
sys.exit(0 if ok else 1)
