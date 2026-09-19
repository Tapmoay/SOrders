"""探针：真实的流式（SSE）响应到底长什么样——**改流式解析之前先跑它**。

用法：
    python _probe_streaming.py sk-xxxx [base_url] [model]

它回答四个问题（这四个正是 [AiStream.kt] 的解析器赖以成立的假设）：
  1. `stream:true` 时响应体真的是 SSE（`data:` 行 + `[DONE]`）吗？
  2. `stream_options.include_usage` 真的能把 `usage` 带回来吗？在哪个分片里？
  3. 工具调用是不是**按 index 分片**下发的？`arguments` 是不是一片片拼的？
  4. `reasoning_content`（思考过程）是不是也按分片流式下发？

**为什么必须实测**：这些形状在官方文档里要么没写、要么写得含糊，
而解析器一旦假设错，表现是"回答缺字 / 工具少执行一个"——不会报错，
只会静默答错。本项目已经吃过一次同类的亏（`reasoning_effort` 被静默忽略，
见 docs/AI_ASSISTANT_PLAN_V3.md §6.5）。

⚠️ key 只从命令行参数读，**绝不写进任何文件**（本项目红线：key 不落盘明文）。
"""
from __future__ import annotations

import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

TOOL = [
    {
        "type": "function",
        "function": {
            "name": "read_data",
            "description": "读取系统里的一张只读列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "要查哪张表"},
                    "limit": {"type": "integer", "description": "最多返回几条"},
                },
                "required": ["action"],
            },
        },
    }
]


def stream(base: str, key: str, model: str, body: dict):
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=120)
    print(f"[http] {resp.status} content-type={resp.headers.get('Content-Type')!r}")
    for raw in resp:
        line = raw.decode("utf-8", "replace").rstrip("\n")
        if line:
            yield line


def analyze(title: str, base: str, key: str, model: str, body: dict) -> None:
    print(f"\n{'=' * 74}\n== {title}\n{'=' * 74}")
    data_lines = 0
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_fragments: dict[int, dict] = {}
    usage_chunk = None
    seen_done = False
    first_line_printed = False

    for line in stream(base, key, model, body):
        if not line.startswith("data:"):
            print(f"[非 data 行] {line[:100]}")
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            seen_done = True
            print("[收到] data: [DONE]")
            continue
        data_lines += 1
        try:
            obj = json.loads(payload)
        except Exception as e:  # noqa: BLE001
            print(f"[!] 分片解析失败: {e} / {payload[:120]}")
            continue

        if not first_line_printed:
            print(f"[首个 data 分片] {payload[:260]}")
            first_line_printed = True

        if obj.get("usage"):
            usage_chunk = obj["usage"]

        for ch in obj.get("choices") or []:
            d = ch.get("delta") or {}
            if d.get("content"):
                content_parts.append(d["content"])
            if d.get("reasoning_content"):
                reasoning_parts.append(d["reasoning_content"])
            for tc in d.get("tool_calls") or []:
                idx = tc.get("index", 0)
                slot = tool_fragments.setdefault(idx, {"id": None, "name": "", "args": ""})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["name"] += fn["name"]
                if fn.get("arguments"):
                    slot["args"] += fn["arguments"]

    print("\n---- 结论 ----")
    print(f"data 分片数           : {data_lines}")
    print(f"看到 [DONE] 哨兵      : {seen_done}")
    print(f"正文拼接结果          : {''.join(content_parts)[:160]!r}")
    print(f"正文分片数            : {len(content_parts)}")
    if reasoning_parts:
        print(f"思考分片数            : {len(reasoning_parts)}  拼接={''.join(reasoning_parts)[:100]!r}")
    else:
        print("思考分片数            : 0（未开思考，或该端点不返回）")
    print(f"usage 分片            : {usage_chunk}")
    if tool_fragments:
        for idx, slot in sorted(tool_fragments.items()):
            print(f"工具[{idx}] id={slot['id']} name={slot['name']!r}")
            print(f"          args 拼接={slot['args'][:200]!r}")
            try:
                json.loads(slot["args"])
                print("          args 是合法 JSON ✅（说明按片拼接正确）")
            except Exception as e:  # noqa: BLE001
                print(f"          args 不是合法 JSON ❌ {e}")
    else:
        print("工具调用              : 无")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    key = sys.argv[1]
    base = sys.argv[2] if len(sys.argv) > 2 else "https://api.deepseek.com"
    model = sys.argv[3] if len(sys.argv) > 3 else "deepseek-flash"

    common = {"model": model, "temperature": 0.0, "stream": True,
              "stream_options": {"include_usage": True}}

    # ① 纯文字 + 要 usage：验证 SSE 形状与 usage 能否拿到
    analyze(
        "① 纯文字（验证 SSE 形状 + stream_options 能否带回 usage）",
        base, key, model,
        {**common, "messages": [{"role": "user", "content": "用一句话说明今天适合做什么。"}]},
    )

    # ② 带工具：验证 tool_calls 是否按 index 分片、arguments 是否可拼接
    analyze(
        "② 带工具（验证 tool_calls 分片与 arguments 拼接）",
        base, key, model,
        {**common, "messages": [{"role": "user", "content": "帮我看看这个月的订单列表，最多 3 条。"}],
         "tools": TOOL, "tool_choice": "auto"},
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
