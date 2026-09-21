"""探针：测试账号默认 AI 配置那三个门（登录 / 白名单 / 有没有配 key）。

跑法（本机或服务器）：python _probe_ai_default.py [base_url]
默认 http://127.0.0.1:8000/api/v1；只打印状态码与字段名，**不打印 key 本身**。
"""
import json
import sys
import urllib.error
import urllib.request

B = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000") + "/api/v1"


def call(path: str, data=None, tok: str | None = None):
    req = urllib.request.Request(B + path, method="POST" if data else "GET")
    req.add_header("Content-Type", "application/json")
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    try:
        with urllib.request.urlopen(req, json.dumps(data).encode() if data is not None else None) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:160]


print("未登录 ->", call("/system/ai-default")[0], "(期望 401)")

for phone in ("13800000001", "13800000003", "13800000005"):
    st, body = call("/auth/login", {"username": phone, "password": "123321"})
    if st != 200:
        print(phone, "登录失败:", st, body)
        continue
    tok = body["access_token"]
    st, body = call("/system/ai-default", tok=tok)
    if st == 200:
        print(phone, "->", st, "字段:", sorted(body.keys()), "| key 长度:", len(body.get("api_key", "")),
              "| base:", body.get("base_url"), "| model:", body.get("model"))
    else:
        print(phone, "->", st, body)
