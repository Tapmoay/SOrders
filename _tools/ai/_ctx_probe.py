"""真机对话文件 → 下一轮到底会发多少上下文（只读，不改任何数据）。

用途：回答「AI 接着对话是把全部上下文都发出去吗」时，拿真机上的对话文件算一遍，
而不是凭印象说「会」。口径与 `AiContext.estimateTokens` 一致（CJK≈1 token/字，其余 4 字符/token）。

用法：
    python _tools/ai/_ctx_probe.py <ai_conversations_u1.json>
"""
import json
import sys


def est(text: str) -> int:
    if not text:
        return 0
    cjk = sum(1 for ch in text if ord(ch) >= 0x2E80)
    return cjk + (len(text) - cjk + 3) // 4


def main() -> int:
    path = sys.argv[1]
    with open(path, encoding="utf-8-sig") as fh:
        data = json.load(fh)
    convs = data.get("conversations", [])
    print(f"对话数：{len(convs)}")
    for c in convs:
        msgs = c.get("messages", [])
        if not msgs:
            continue
        # historyForModel 的口径：跳过错误气泡；user 用 attachmentBlock（有则替 text）；assistant 只用 text
        kept, chars, tokens = [], 0, 0
        for m in msgs:
            if m.get("isError"):
                continue
            body = (m.get("attachmentBlock") or m.get("text") or "") if m.get("role") == "user" \
                else (m.get("text") or "")
            if not body.strip():
                continue
            kept.append(m)
            chars += len(body)
            tokens += est(body) + 4
        files = sum(1 for m in msgs if m.get("attachments"))
        img = sum(1 for m in msgs if (m.get("attachmentBlock") or "").find("这是一张图片") >= 0)
        print("---")
        print(f"  会话 {c.get('id','')[:8]}  共 {len(msgs)} 条消息（错误气泡 {len(msgs)-len(kept)} 条不进历史）")
        print(f"  带附件的消息 {files} 条，其中带图 {img} 条")
        print(f"  compactedUpTo={c.get('compactedUpTo', 0)}  summary={len(c.get('summary') or '')} 字")
        print(f"  下一轮实际会带的正文：{chars} 字符 ≈ {tokens} token（还没算系统提示词约 3.5k）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
