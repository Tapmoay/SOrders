"""实测后端新增的 3 个端点（方案 v3.1 缺口 A/B/C）。需要本机后端已在 8000 运行。

用法：python _probe_new_endpoints.py
"""
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

BASE = "http://127.0.0.1:8000/api/v1"
DB = repo_root() / "backend" / "sorders.db"


def call(method: str, path: str, token: str | None = None, body: dict | None = None):
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode("utf-8", "ignore")
            try:
                return r.status, json.loads(raw)
            except Exception:  # noqa: BLE001
                return r.status, raw[:300]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")[:300]
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


TEST_PHONE = "13900000001"  # 由 _mk_test_dispatcher.py 在本地开发库创建


def find_dispatcher_phone() -> str | None:
    """优先用测试账号（密码已知），否则退回库里第一个派单员。"""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    row = con.execute("SELECT phone FROM users WHERE phone=? LIMIT 1", (TEST_PHONE,)).fetchone()
    if row:
        con.close()
        return row[0]
    row = con.execute(
        "SELECT phone FROM users WHERE role='DISPATCHER' AND phone IS NOT NULL LIMIT 1"
    ).fetchone()
    con.close()
    return row[0] if row else None


def main() -> int:
    phone = find_dispatcher_phone()
    print(f"派单员手机号（自库中取）: {phone}")
    if not phone:
        print("库里没有派单员，退出")
        return 1

    token = None
    for pwd in ("test1234", "123456", "admin123", "12345678", "a123456"):
        code, data = call("POST", "/auth/login", body={"phone": phone, "password": pwd})
        if code == 200 and isinstance(data, dict) and data.get("access_token"):
            token = data["access_token"]
            print(f"登录成功（密码={pwd}）role={data.get('role')}")
            break
        print(f"  密码 {pwd!r} -> {code} {str(data)[:80]}")
    if not token:
        print("\n⚠️ 无法登录：本地库的密码不是常见测试密码。请人工提供，或用后端测试夹具建号。")
        return 1

    print("\n=== 缺口 A：GET /users?q=（货主搜索）===")
    for q in ("", "S", "张", "138"):
        code, data = call("GET", f"/users?role=shipper&q={urllib.parse.quote(q)}&limit=5", token)
        n = len(data) if isinstance(data, list) else "-"
        print(f"  q={q!r:<6} -> {code} 条数={n}")

    print("\n=== 缺口 C：GET /inventory/summary?below_alert=true ===")
    for flag in ("false", "true"):
        code, data = call("GET", f"/inventory/summary?below_alert={flag}", token)
        n = len(data) if isinstance(data, list) else "-"
        sample = data[:2] if isinstance(data, list) else data
        print(f"  below_alert={flag:<5} -> {code} 条数={n} 样例={json.dumps(sample, ensure_ascii=False)[:150]}")

    print("\n=== 缺口 B：GET /stats/shipper-performance ===")
    code, data = call(
        "GET", "/stats/shipper-performance?date_from=2026-01-01&date_to=2026-12-31", token
    )
    print(f"  -> {code}")
    print(f"  {json.dumps(data, ensure_ascii=False)[:600]}")
    return 0


if __name__ == "__main__":
    import urllib.parse  # noqa: E402

    sys.exit(main())
