"""实测：thinking 开关 + tools 组合，以及 reasoning_content 的行为细节。

背景：`deepseek-flash` 基线就带 reasoning_content；要让"关思考"真正生效必须用
`thinking:{"type":"disabled"}`（`reasoning_effort` / `enable_thinking` 均被静默忽略）。
本脚本确认：①思考开关在带 tools 时是否仍生效 ②开启思考时 tool_calls 是否仍正常返回。
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

BASE = "https://api.deepseek.com"
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "pending_dispatch_count",
            "description": "待派单池的订单数量",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inventory_alerts",
            "description": "列出库存已达报警阈值的商品",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


def key() -> str:
    cred = Path.home() / ".dsh" / ".credentials.yaml"
    for line in cred.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "DEEPSEEK_API_KEY" in line and ":" in line:
            return line.split(":", 1)[1].strip().strip("'\"")
    raise SystemExit("取不到 key")


def call(body: dict, k: str):
    req = urllib.request.Request(
        f"{BASE}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {k}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.loads(r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")[:300]
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


def main() -> int:
    k = key()
    for model in ("deepseek-flash", "deepseek-v4-pro"):
        print(f"\n=== {model} ===")
        for label, extra in (
            ("思考开 + 带工具", {"thinking": {"type": "enabled"}, "tools": TOOLS, "tool_choice": "auto"}),
            ("思考关 + 带工具", {"thinking": {"type": "disabled"}, "tools": TOOLS, "tool_choice": "auto"}),
        ):
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "你是派单系统助手，只能通过工具查数据。今天是 2026-09-14。"},
                    {"role": "user", "content": "现在还有几单没派出去？"},
                ],
                "max_tokens": 200,
                **extra,
            }
            code, resp = call(body, k)
            if code != 200 or not isinstance(resp, dict):
                print(f"  ❌ {label}: {code} {str(resp)[:160]}")
                continue
            msg = (resp.get("choices") or [{}])[0].get("message") or {}
            calls = msg.get("tool_calls") or []
            usage = resp.get("usage") or {}
            names = [((c.get("function") or {}).get("name")) for c in calls]
            print(f"  ✅ {label:<14} tool_calls={names or '无'}  "
                  f"reasoning={'有' if msg.get('reasoning_content') else '无'}  "
                  f"tokens={usage.get('completion_tokens')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
