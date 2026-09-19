"""给某个账号发一条站内信（真接口），用来复现/验证消息页的提示框问题。

用法：python _tools/qa/_send_test_message.py [收件人手机号] [标题] [正文]
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

B = "http://127.0.0.1:8000/api/v1"


def req(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(B + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except Exception:
            return e.code, {"raw": raw.decode("utf-8", "replace")}


def main() -> int:
    phone = sys.argv[1] if len(sys.argv) > 1 else "13800000002"
    title = sys.argv[2] if len(sys.argv) > 2 else "提示框复现用"
    content = sys.argv[3] if len(sys.argv) > 3 else "这条消息只用来复现「切页后提示框又冒出来」。"
    s, d = req("POST", "/auth/login", {"username": "13800000001", "password": "123321"})
    if s != 200:
        print("登录失败", s, d)
        return 1
    tok = d["access_token"]
    s, users = req("GET", f"/users?q={phone}&limit=20", token=tok)
    # ⚠️ 两个坑（前面踩过）：`?role=` 要枚举名；`/users` 默认只回 100 条按 id 倒序
    target = next((u for u in users if u.get("phone") == phone), None)
    if target is None:
        print("找不到收件人", phone, users)
        return 1
    s, n = req(
        "POST",
        "/notifications",
        {"recipient_id": target["id"], "title": title, "content": content, "category": "system"},
        tok,
    )
    print("发信", s, json.dumps(n, ensure_ascii=False)[:200])
    return 0 if s in (200, 201) else 1


if __name__ == "__main__":
    raise SystemExit(main())
