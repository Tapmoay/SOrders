"""拿真后端逐条打一遍「AI 读目录」，验证角色表与真实鉴权一致。

### 为什么必须实测，而不是"看代码推"
读目录是按角色裁剪的（`docs/ai/ai_read_catalog.json` 的 `roles`）。裁剪错了有两种后果，
**两种都不会让任何测试变红**：
  · 给多了 → 货主问一句"我的账单呢"，AI 拿到 403，只能如实回"查不了"（能力白写）；
  · 给少了 → 明明能查的表，AI 却说"我没这个权限"（用户永远不知道有这功能）。
所以这里做的是**端到端对账**：对每个角色登录真后端，把每条端点都打一次，
`403` = 真的不给，其它（200/400/422/404）= 门是通的（400 多是缺必填参数，不影响判定）。

用法：
    python _tools/ai/_probe_read_roles.py                 # 对 localhost:8000
    python _tools/ai/_probe_read_roles.py --base http://8.145.40.22
退出码 1 = 有对不上的（角色表该改）。
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

# 开发账号（三端各一个，密码相同）。只用于本机/测试环境对账。
#
# ⚠️ 口令走环境变量（2026-09-25 纳入 CI 时加）：本机开发库的口令是 `123321`，
#    而仓库里的播种脚本 `backend/scripts/seed_dev_users.py` 用的是 `pass12345` ——
#    CI 上没人会去改口令，于是"对账脚本登不进去"会被当成"权限对不上"（假红）。
#    所以口令可配：CI 里 `SORDERS_PROBE_PASSWORD=pass12345 python _tools/ai/_probe_read_roles.py`。
PROBE_PASSWORD = os.environ.get("SORDERS_PROBE_PASSWORD", "123321")
ACCOUNTS = {
    "dispatcher": ("13800000001", PROBE_PASSWORD),
    "shipper": ("13800000002", PROBE_PASSWORD),
    "driver": ("13800000003", PROBE_PASSWORD),
}
# 必填参数没法凭空知道，用一组"总能满足"的默认值顶上；填不上就让它 400，也算门通。
DUMMY = {"date_from": "2026-01-01", "date_to": "2026-12-31", "month": "2026-09", "from": "2026-01-01", "to": "2026-12-31"}


def call(url: str, token: str | None, method: str = "GET") -> int:
    req = urllib.request.Request(url, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0  # 连不上


def login(base: str, phone: str, pw: str) -> str | None:
    body = json.dumps({"phone": phone, "password": pw}).encode()
    req = urllib.request.Request(f"{base}/api/v1/auth/login", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode()).get("access_token")
    except Exception as e:
        print(f"  ⚠️ 登录失败（{phone}）：{e}")
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    args = ap.parse_args()

    cat = json.loads((repo_root() / "docs/ai/ai_read_catalog.json").read_text(encoding="utf-8"))
    tokens = {role: login(args.base, *ACCOUNTS[role]) for role in ACCOUNTS}
    if not tokens["dispatcher"]:
        print("❌ 连不上后端或账号不对，先把本机后端跑起来：cd backend && python -m uvicorn app.main:app --port 8000")
        return 2

    bad = 0
    skipped = 0
    for role in ("dispatcher", "shipper", "driver"):
        tok = tokens[role]
        if not tok:
            continue
        print(f"\n== {role} ==")
        for a in sorted(cat["actions"], key=lambda x: x["action"]):
            # ⚠️ **本机能力不该出现在这份生成目录里**（"读手机定位"这类查的是这台手机，
            #    没有后端端点）：拿空路径去打后端只会得到 404，而下面 `reachable = code != 403`
            #    会把 404 判成"门是通的" —— 于是一条本机能力被静默算成"后端读端点实测通过"。
            #    它们的唯一声明处是 `android/.../ai/AiLocalReads.kt`（`path` 留空），
            #    由 `_check_ai_guardrails.py` §2b-3 守着。这里**跳过**它们，不去发那个请求。
            if not str(a.get("path", "")).startswith("/api/v1/"):
                print(f"  -- {a.get('module')}.{a.get('action')} 跳过（本机能力，没有后端端点）")
                skipped += 1
                continue
            q = "&".join(f"{k}={v}" for k, v in DUMMY.items() if any(p["name"] == k for p in a["params"]))
            code = call(f"{args.base}{a['path']}" + (f"?{q}" if q else ""), tok)
            declared = role in a["roles"]
            reachable = code != 403
            flag = "OK " if declared == reachable else "❌ "
            if declared != reachable:
                bad += 1
            name = f"{a['module']}.{a['action']}"
            print(f"  {flag}{name:44s} 实际 {code} / 声明 {'可用' if declared else '不可用'}")
    print()
    if skipped:
        print(f"（跳过了 {skipped} 条本机能力：没有后端端点可打 —— 见上面的说明）")
    if bad:
        print(f"❌ {bad} 条对不上：改 `_tools/ai/_gen_ai_read_catalog.py` 的角色推导，或修后端守卫。")
        return 1
    print("✅ 每个角色的读权限都与实测一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
