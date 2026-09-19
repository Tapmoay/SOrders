"""验证用户提供的新 API key：是否有效、能用哪些模型、思考开关是否生效。

用法：python _verify_user_key.py sk-xxxx
"""
import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

BASE = "https://api.deepseek.com"


def call(path: str, key: str, body: dict | None = None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST" if body else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")[:300]
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


def main() -> int:
    if len(sys.argv) < 2:
        sys.exit("用法：python _verify_user_key.py sk-xxxx")
    key = sys.argv[1].strip()

    code, data = call("/models", key)
    print(f"1) GET /models -> {code}")
    if code != 200:
        print(f"   ❌ key 不可用：{data}")
        return 1
    models = [m.get("id") for m in (data.get("data") or [])] if isinstance(data, dict) else []
    print(f"   ✅ 可用模型：{models}")

    target = "deepseek-flash" if "deepseek-flash" in models else (models[0] if models else None)
    if not target:
        print("   ❌ 没有可用模型")
        return 1

    for label, extra in (
        ("思考开", {"thinking": {"type": "enabled"}}),
        ("思考关", {"thinking": {"type": "disabled"}}),
    ):
        code, resp = call("/chat/completions", key, {
            "model": target,
            "messages": [{"role": "user", "content": "1+1=?"}],
            "max_tokens": 32,
            **extra,
        })
        if code != 200 or not isinstance(resp, dict):
            print(f"2) {label} ({target}) -> ❌ {code} {str(resp)[:160]}")
            continue
        msg = (resp.get("choices") or [{}])[0].get("message") or {}
        u = resp.get("usage") or {}
        print(f"2) {label} ({target}) -> ✅ reasoning={'有' if msg.get('reasoning_content') else '无'} "
              f"completion_tokens={u.get('completion_tokens')} 答复={(msg.get('content') or '')[:40]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
