"""实测「上下文缓存」到底命中不命中——直接决定「每次都全量重发」贵不贵。

背景（DeepSeek 官方文档，上下文硬盘缓存默认开启）：
  · 缓存按**前缀**匹配，命中价 $0.003/M，未命中价 $0.15/M（deepseek-flash 低谷价）——**差 50 倍**；
  · 「一轮 A+B、下一轮 A+B+C」能命中 A+B（这正是多轮对话的形态，见官方 Example 1）；
  · 但只要**前缀第一段就变了**（例如 system 提示词每问都不一样），后面全部无法命中。

四次请求，逐步加长，看 usage 里的 prompt_cache_hit_tokens：

  ① 首轮（system + Q1）                    期望 hit ≈ 0（第一次当然没有缓存）
  ② 正常多轮（system + Q1 + A1 + Q2）       期望 hit ≈ system+Q1 的长度   ← 现在的实现走的就是这条
  ③ system 里塞了"本次相关记忆"（每个问题都变）期望 hit **塌回 0**        ← 这是要验证的隐患
  ④ 把"本次相关记忆"改放进最后一条 user 消息 期望 hit **恢复正常**        ← 这是候选修法

用法：python _tools/ai/_probe_cache.py
成本：四次的输入合计约 6k token，输出各 16 token，不到 1 分钱。
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


def post(messages: list, k: str) -> tuple[int, dict]:
    body = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": 16,
        "temperature": 0.0,
        "thinking": {"type": "disabled"},
    }
    req = urllib.request.Request(
        f"{BASE}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {k}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, {"raw": e.read().decode("utf-8", "replace")[:400]}


def est(text: str) -> int:
    cjk = sum(1 for ch in text if ord(ch) >= 0x2E80)
    return cjk + (len(text) - cjk + 3) // 4


def show(tag: str, code: int, body: dict) -> int:
    if code != 200:
        print(f"{tag} → HTTP {code}：{body.get('raw', body)}")
        return -1
    u = body.get("usage", {})
    hit = u.get("prompt_cache_hit_tokens")
    miss = u.get("prompt_cache_miss_tokens")
    total = u.get("prompt_tokens")
    print(f"{tag} → HTTP 200  prompt={total}  **cache_hit={hit}**  cache_miss={miss}"
          f"  completion={u.get('completion_tokens')}")
    return hit if isinstance(hit, int) else -1


def main() -> int:
    k = key()

    # 稳定的 system（模拟真实的身份提示词 + 工具清单，取一段够长的固定文本）
    stable_sys = (
        "你是派单送货管理系统的助手。所有数字只能来自工具返回值，严禁编造。"
        "金额保留两位小数，日期一律 YYYY-MM-DD。先给结论再列明细。"
    ) * 40  # ≈ 1.5k token，够触发并看清缓存行为
    q1 = "先随便说一句，我要建立对话的第一轮内容用于缓存测试。"
    a1 = "好的，第一轮已经建立。"

    print(f"stable system ≈ {est(stable_sys)} token\n")

    # ① 首轮
    code, body = post(
        [{"role": "system", "content": stable_sys}, {"role": "user", "content": q1}], k
    )
    h1 = show("① 首轮    ", code, body)
    if h1 < 0:
        print("基线不通，后面的结论无效。")
        return 1
    # 用真实回答做 A1，后面的前缀才是真的"发给过服务端的那份"
    a1 = body["choices"][0]["message"].get("content") or a1

    # ② 正常多轮：前缀 = system + Q1，应命中
    code, body = post(
        [
            {"role": "system", "content": stable_sys},
            {"role": "user", "content": q1},
            {"role": "assistant", "content": a1},
            {"role": "user", "content": "第二轮：接着上面说。"},
        ],
        k,
    )
    h2 = show("② 正常多轮", code, body)

    # ③ system 里塞进"每问都变"的内容（模拟 memoryHint/habits 挂在 systemExtra 上）
    code, body = post(
        [
            {"role": "system", "content": stable_sys + "\n【本次相关记忆】张三上次要求先结账。"},
            {"role": "user", "content": q1},
            {"role": "assistant", "content": a1},
            {"role": "user", "content": "第三轮：接着上面说。"},
        ],
        k,
    )
    h3 = show("③ system 每问都变", code, body)

    # ④ 同样的易变内容，改挂到最后一条 user 消息上（前缀保持稳定）
    code, body = post(
        [
            {"role": "system", "content": stable_sys},
            {"role": "user", "content": q1},
            {"role": "assistant", "content": a1},
            {"role": "user", "content": "【本次相关记忆】张三上次要求先结账。\n\n第四轮：接着上面说。"},
        ],
        k,
    )
    h4 = show("④ 易变内容挪到 user", code, body)

    # ⑤ 同样的易变内容，塞到 system 的**开头**（模拟把"今天日期/相关记忆"放在最前面）
    code, body = post(
        [
            {"role": "system", "content": "【本次相关记忆】张三上次要求先结账。\n" + stable_sys},
            {"role": "user", "content": q1},
            {"role": "assistant", "content": a1},
            {"role": "user", "content": "第五轮：接着上面说。"},
        ],
        k,
    )
    h5 = show("⑤ 易变内容放 system 头", code, body)

    print()
    base = max(h2, 1)
    print(f"② 命中 {h2} token 是基准")
    print(f"③ system 尾部加易变内容 → {h3}（{h3 * 100 // base}%）")
    print(f"④ 易变内容挪到 user   → {h4}（{h4 * 100 // base}%）")
    print(f"⑤ system **头部**加易变内容 → {h5}（{max(h5, 0) * 100 // base}%）")
    print()
    # 真正的结论：缓存按"固定 token 间隔切出来的前缀单元"匹配，
    # **易变内容放得越靠前，作废的范围越大**；放在末尾则只作废它自己。
    ok = h2 > 0 and h5 <= h2 * 0.2
    print("✅ 结论：易变内容放在前缀**末尾**几乎不损失缓存（③≈②），"
          "放到**开头**才会把缓存整段打掉（⑤塌陷）。" if ok else
          "⚠️ 与预期不符，别急着按结论改代码——先看上面五行原始数字。")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
