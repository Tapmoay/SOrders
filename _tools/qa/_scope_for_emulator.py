"""临时：给货主 13800000002 设 / 清商品可见白名单，供真机 E2E 用。

用法：
  python _tools/qa/_scope_for_emulator.py set     # 设成"只给探针商品"
  python _tools/qa/_scope_for_emulator.py clear   # 恢复"全部商品"
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

B = "http://127.0.0.1:8000/api/v1"
PHONE = "13800000002"


def req(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(B + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except Exception:
            return e.code, {"raw": raw.decode("utf-8", "replace")}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "set"
    s, d = req("POST", "/auth/login", {"username": "13800000001", "password": "123321"})
    assert s == 200, (s, d)
    tok = d["access_token"]

    s, users = req("GET", f"/users?q={PHONE}&limit=20", token=tok)
    assert isinstance(users, list), (s, users)
    shipper = next(u for u in users if u.get("phone") == PHONE)

    if mode == "clear":
        print(req("PUT", f"/users/{shipper['id']}/product-visibility", {"scope": "all", "product_ids": []}, tok))
        return 0

    s, prods = req("GET", "/products", token=tok)
    assert isinstance(prods, list), (s, prods)
    keep = next((p for p in prods if p["name"].startswith("探针商品")), None)
    if keep is None:
        print("找不到「探针商品*」，可用商品：", [p["name"] for p in prods[:5]])
        return 1
    print("货主", shipper["id"], "只给看：", keep["id"], keep["name"])
    print(req("PUT", f"/users/{shipper['id']}/product-visibility", {"scope": "custom", "product_ids": [keep["id"]]}, tok))
    return 0


if __name__ == "__main__":
    sys.exit(main())
