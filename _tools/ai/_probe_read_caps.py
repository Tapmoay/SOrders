"""`read_data` 到底被谁截断了：**App 还是后端**？

这个问题决定了修法完全不同：
  · 如果后端已经把全量返回了 → 是我们 App 在 `AiReadService` 里 `take(limit)` 丢掉的，改客户端即可；
  · 如果后端自己就只返 20/50 条 → 得让 App 把 limit 传下去，甚至要在后端加分页。

做法：真登录取 token，然后按 AI 会用的那几个接口各打一次，数返回条数。

用法：python _tools/ai/_probe_read_caps.py
前置：本机 uvicorn 起在 8000（`cd backend && python -m uvicorn app.main:app --port 8000`）。
"""
import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

BASE = "http://127.0.0.1:8000/api/v1"


def call(method: str, path: str, token: str | None = None, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


def rows_of(obj) -> tuple[int, str]:
    """返回 (条数, 说明)。后端有的直接给数组，有的包在 items/data/list 里。"""
    if isinstance(obj, list):
        return len(obj), "裸数组"
    if isinstance(obj, dict):
        for k in ("items", "data", "list", "rows", "records"):
            if isinstance(obj.get(k), list):
                return len(obj[k]), f"包在 .{k}（外层键：{','.join(list(obj)[:6])}）"
        return 0, f"对象（键：{','.join(list(obj)[:8])}）"
    return 0, type(obj).__name__


def main() -> int:
    code, tok = call("POST", "/auth/login", body={"phone": "13800000001", "password": "123321"})
    if code != 200 or not isinstance(tok, dict):
        code, tok = call("POST", "/auth/login", body={"username": "13800000001", "password": "123321"})
    if code != 200 or not isinstance(tok, dict):
        print(f"❌ 登录失败 HTTP {code}：{tok}")
        return 1
    token = tok.get("access_token") or tok.get("token") or ""
    print(f"✅ 登录成功（派单员）拿 {len(token)} 字符的 token\n")

    # AI 侧那张白名单里的关键几张表（路径与 AiReadCatalog 一致）
    probes = [
        ("GET", "/users?role=SHIPPER", "货主名单"),
        ("GET", "/users?role=DRIVER", "司机名单"),
        ("GET", "/users", "用户名单（不筛角色）"),
        ("GET", "/products", "商品名单"),
        ("GET", "/orders", "订单（不传 limit）"),
        ("GET", "/orders?limit=500", "订单（limit=500）"),
    ]
    for method, path, label in probes:
        code, obj = call(method, path, token)
        if code != 200:
            print(f"  {label:22} HTTP {code}  {obj}")
            continue
        n, how = rows_of(obj)
        print(f"  {label:22} → **{n} 条**  {how}")

    print("\n对照：AI 工具侧 DEFAULT_ROWS=20 / MAX_ROWS=50（AiTools.kt），"
          "超过就 take(limit) 丢掉并置 truncated=true。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
