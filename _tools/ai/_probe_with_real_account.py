"""用真实派单员账号（密码 123321）登录取 token，并实测 3 个新端点。只读，不改数据。"""
import json
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

BASE = "http://127.0.0.1:8000/api/v1"
DB = repo_root() / "backend" / "sorders.db"
TOKEN_FILE = Path(__file__).resolve().parent / ".token"


def call(method: str, path: str, token: str | None = None, body: dict | None = None):
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {token}"} if token else {})},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode("utf-8", "ignore")
            try:
                return r.status, json.loads(raw)
            except Exception:  # noqa: BLE001
                return r.status, raw[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")[:200]
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


def main() -> int:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    phones = [r[0] for r in con.execute(
        "SELECT phone FROM users WHERE role='DISPATCHER' AND phone IS NOT NULL ORDER BY id")]
    con.close()
    print(f"库里的派单员：{phones}")

    token = None
    who = None
    for p in phones:
        for pwd in ("123321", "test1234"):
            code, data = call("POST", "/auth/login", body={"phone": p, "password": pwd})
            if code == 200 and isinstance(data, dict) and data.get("access_token"):
                token, who = data["access_token"], (p, pwd, data.get("role"))
                break
        if token:
            break
    if not token:
        print("⚠️ 全部登录失败")
        return 1
    print(f"✅ 登录成功：phone={who[0]} role={who[2]}")
    TOKEN_FILE.write_text(token, encoding="ascii")

    print("\n--- 缺口 A: GET /users?q= ---")
    for q in ("", "S", "张", "138", "139"):
        code, data = call("GET", f"/users?role=shipper&q={urllib.parse.quote(q)}&limit=5", token)
        n = len(data) if isinstance(data, list) else str(data)[:60]
        print(f"   q={q!r:<6} -> {code} 条数/值={n}")

    print("\n--- 缺口 B: GET /stats/shipper-performance ---")
    code, data = call("GET", "/stats/shipper-performance?date_from=2026-01-01&date_to=2026-12-31", token)
    top = data.get("shippers", [])[:3] if isinstance(data, dict) else data
    print(f"   -> {code} 货主数={len(data.get('shippers', [])) if isinstance(data, dict) else '-'}")
    print(f"   前 3: {json.dumps(top, ensure_ascii=False)}")

    print("\n--- 缺口 C: GET /inventory/summary?below_alert=true ---")
    code, data = call("GET", "/inventory/summary?below_alert=true", token)
    print(f"   -> {code} 条数={len(data) if isinstance(data, list) else '-'}")
    if isinstance(data, list) and data:
        print(f"   样例: {json.dumps(data[0], ensure_ascii=False)}")

    print("\n--- 顺带：现有只读端点能否用（AI 工具要调）---")
    for p in ("/stats/driver-performance?date_from=2026-01-01&date_to=2026-12-31",
              "/inventory/summary?below_alert=false",
              "/ledger/accounts?kind=shipper"):
        code, data = call("GET", p, token)
        n = len(data) if isinstance(data, list) else ("dict" if isinstance(data, dict) else "-")
        print(f"   {p[:58]:<60} -> {code} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
