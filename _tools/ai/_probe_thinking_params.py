"""实测 DeepSeek 兼容端点的「思考模式」参数与模型列表，避免凭猜写代码。

只发极短的请求（max_tokens 很小），成本可忽略。
用法：python _probe_thinking_params.py
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

BASE = "https://api.deepseek.com"
MODEL = "deepseek-flash"


def key() -> str:
    cred = Path.home() / ".dsh" / ".credentials.yaml"
    for line in cred.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "DEEPSEEK_API_KEY" in line and ":" in line:
            return line.split(":", 1)[1].strip().strip("'\"")
    raise SystemExit("取不到 key")


def call(body: dict, k: str) -> tuple[int, dict | str]:
    req = urllib.request.Request(
        f"{BASE}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {k}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")[:300]
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


def main() -> int:
    k = key()
    base = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "1+1=?"}],
        "max_tokens": 24,
    }

    cases = [
        ("基线（无思考参数）", {}),
        ("reasoning_effort=low", {"reasoning_effort": "low"}),
        ("reasoning_effort=high", {"reasoning_effort": "high"}),
        ("reasoning_effort=minimal", {"reasoning_effort": "minimal"}),
        ("thinking={type:enabled}", {"thinking": {"type": "enabled"}}),
        ("thinking={type:disabled}", {"thinking": {"type": "disabled"}}),
        ("enable_thinking=true", {"enable_thinking": True}),
        ("enable_thinking=false", {"enable_thinking": False}),
        ("reasoning={effort:high}", {"reasoning": {"effort": "high"}}),
    ]

    for name, extra in cases:
        code, resp = call({**base, **extra}, k)
        if code == 200 and isinstance(resp, dict):
            msg = (resp.get("choices") or [{}])[0].get("message") or {}
            reason = msg.get("reasoning_content")
            usage = resp.get("usage") or {}
            print(f"  ✅ {name:<26} 200  reasoning_content={'有' if reason else '无'}"
                  f"  completion_tokens={usage.get('completion_tokens')}")
        else:
            print(f"  ❌ {name:<26} {code}  {str(resp)[:140]}")

    print("\n=== 两个模型是否都接受 reasoning_effort=high ===")
    for m in ("deepseek-flash", "deepseek-v4-pro"):
        code, resp = call({**base, "model": m, "reasoning_effort": "high"}, k)
        ok = code == 200
        has_reason = bool(((resp.get("choices") or [{}])[0].get("message") or {}).get("reasoning_content")) if ok else False
        print(f"  {m:<18} {code}  reasoning_content={'有' if has_reason else '无'}"
              if ok else f"  {m:<18} {code} {str(resp)[:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
