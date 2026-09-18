"""实测「上下文超长」时端点的真实报错，用来校准两件事（都别靠猜）：

1. `inferWindow()` 给 `deepseek-flash` 猜的 128k 对不对（猜大 = 用户吃 400）；
2. `mentionsContextOverflow()` 的关键短语能不能命中**真实**报错体
   —— 这条是自动缩窗口自愈链的命门，猜错就整条链失效。

做法：故意发一个超长提示词（约 150k token），请求会被拒绝，**不产生生成费用**。
用法：python _probe_context_overflow.py
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

BASE = "https://api.deepseek.com"
MODEL = "deepseek-flash"

# 与 LlmClient.CONTEXT_OVERFLOW_PHRASES 保持一致（这里手抄一份，是为了让探针能独立跑；
# 两边不一致时以 Kotlin 那份为准，并在探针里补上真实命中的短语）
PHRASES = [
    "context length",
    "context_length_exceeded",
    "maximum context",
    "max context",
    "context window",
    "reduce the length",
    "maximum number of tokens",
    "input is too long",
    "prompt is too long",
]


def key() -> str:
    cred = Path.home() / ".dsh" / ".credentials.yaml"
    for line in cred.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "DEEPSEEK_API_KEY" in line and ":" in line:
            return line.split(":", 1)[1].strip().strip("'\"")
    raise SystemExit("取不到 key")


def post(body: dict, k: str) -> tuple[int, str]:
    req = urllib.request.Request(
        f"{BASE}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {k}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def main() -> int:
    k = key()
    # 可调提示词长度：命令行给重复次数（每份 ≈ 45 字符 ≈ 10 token，实测比例见下）
    repeats = int(sys.argv[1]) if len(sys.argv) > 1 else 12_000

    # 先确认这个小请求是通的（避免把「key 错」误读成「超长」）
    code, body = post(
        {"model": MODEL, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1,
         "thinking": {"type": "disabled"}},
        k,
    )
    print(f"[基线] 短请求 → HTTP {code}")
    if code != 200:
        print("基线就不通，后面的结论无效：", body[:300])
        return 1

    # 再发一个超长提示词。实测比例：540k 字符 = 120,005 token（≈4.5 字符/token）
    filler = "The quick brown fox jumps over the lazy dog. " * repeats
    print(f"[超长] 提示词 {len(filler)} 字符（≈ {int(len(filler)/4.5)} token）→ 发送…")
    code, body = post(
        {"model": MODEL, "messages": [{"role": "user", "content": filler}], "max_tokens": 1,
         "thinking": {"type": "disabled"}},
        k,
    )
    print(f"[超长] → HTTP {code}")
    if code == 200:
        try:
            pt = json.loads(body)["usage"]["prompt_tokens"]
            print(f"[超长] 被接受了：prompt_tokens = {pt} → 这个模型的真实窗口 **≥ {pt}**")
        except Exception:
            print(body[:600])
    else:
        print("---- 响应体（截断 1200 字符）----")
        print(body[:1200])
        print("--------------------------------")

    low = body.lower()
    hits = [p for p in PHRASES if p in low]
    print(f"命中的关键短语：{hits if hits else '（一个都没命中）'}")

    if code == 200:
        print("⚠️ 没被拒绝：窗口比这次发的更大，inferWindow 需要相应调大（否则会过早压缩）")
        return 0
    if hits:
        print("✅ 报错能被 mentionsContextOverflow 认出来 → 自动缩窗口自愈链的判断依据成立")
        return 0
    print("❌ 报错认不出来 → 自愈链会失效，必须把真实措辞加进 CONTEXT_OVERFLOW_PHRASES")
    return 1


if __name__ == "__main__":
    sys.exit(main())
