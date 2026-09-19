"""真机验证：**跨过固定预算之后，AI 还答不答得对早前的问题**。

### 为什么这条必须上真机（单测拦不住的三件事）
1. `fitToBudget` 是纯函数、有单测；但**"什么时候调用它""压缩在后台跑完之后状态有没有落对"**
   全在 `AiChatViewModel` 里，单测碰不到；
2. 后台摘要协程的 `generation` 比对、`persist()`、芯片文案优先级，都是"不报错但会错"的那类；
3. 真正要证明的是一句人话：**收口之后，模型还记得第一轮问过什么、答案是多少吗。**

### 判定信号（不靠肉眼读截图）
`files/ai_conversations_u1.json` 里那个对话的：
  · `compactedUpTo > 0` 且 `summary` 非空 → **预算真的触发了、摘要真的生成了**；
  · 最后一轮的回答里出现第一轮那个数字 → **跨过收口边界仍然答得对**。

用法：python _tools/ai/_probe_ctx_budget_e2e.py
前置：模拟器已开、App 已登录、**当前是一个新对话**（脚本不负责建对话）。
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ADB = r"D:\APPS\sdk\platform-tools\adb.exe"
SERIAL = "emulator-5554"
# ⚠️ 本机**没有 pwsh**（PowerShell 7），只有 Windows PowerShell 5.1。
#    直接写 "pwsh" 会 FileNotFoundError（实测踩到）。5.1 读 .ps1 按 ANSI，
#    所以 `_emulator_say.ps1` 必须是 **UTF-8 with BOM**（它已经是，别把 BOM 去掉）。
PS = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
HERE = Path(__file__).resolve().parent
SAY = HERE / "_emulator_say.ps1"
CONV = "files/ai_conversations_u1.json"

# 第一轮问什么、期望最后一轮还能答出什么（判定用的锚点）
ANCHOR_Q = "最近 7 天一共有多少单？只回一个数字，不要表格，不要解释。"
ANCHOR_RE = re.compile(r"\d+")

# 后面几轮故意要"长答案"——它们才是把历史推过 8k 预算的动力
FILLERS = [
    "把商品列表全部列出来：名称、单价、库存。能列多少列多少，用表格。",
    "把货主名单和各自的单数列成表格。",
    "把司机名单和各自的接单数列成表格。",
    "把最近 30 天的订单逐条列出来：日期、单号、货主、金额，用表格。",
]
RECALL_Q = "我最开始问你的第一个问题是什么？当时的答案是多少？"


def adb(*args: str, timeout: int = 120) -> bytes:
    return subprocess.run([ADB, "-s", SERIAL, *args], capture_output=True, timeout=timeout).stdout


def pull_convs() -> dict | None:
    raw = adb("exec-out", "run-as", "com.tapmoay.sorders", "cat", CONV)
    if not raw or b"conversations" not in raw:
        return None
    try:
        return json.loads(raw.decode("utf-8", "replace").replace("\r\n", "\n"))
    except Exception:
        return None


def est(text: str) -> int:
    if not text:
        return 0
    cjk = sum(1 for ch in text if ord(ch) >= 0x2E80)
    return cjk + (len(text) - cjk + 3) // 4


def history_tokens(msgs: list) -> int:
    """与 AiContext.estimateHistoryTokens 同口径（跳过错误气泡；user 用 attachmentBlock）。"""
    n = 0
    for m in msgs:
        if m.get("isError"):
            continue
        body = (m.get("attachmentBlock") or m.get("text") or "") if m.get("role") == "user" else (m.get("text") or "")
        if not body.strip():
            continue
        n += est(body) + 4
    return n


def newest(data: dict, include_empty: bool = False) -> dict | None:
    """最近更新的那个对话。

    ⚠️ `include_empty` 是必须的：**刚点「+」建出来的空对话还没落盘**（`persist()` 在第一次发送时才写），
    所以"只看有消息的"会把上一段对话误当成当前对话——第一版就栽在这，
    脚本直接报"当前对话已经有 4 条消息"，而屏幕上明明是空的。
    """
    convs = data.get("conversations", [])
    if not include_empty:
        convs = [c for c in convs if c.get("messages")]
    if not convs:
        return None
    return max(convs, key=lambda c: c.get("updatedAt") or 0)


def by_id(data: dict, cid: str) -> dict | None:
    for c in data.get("conversations", []):
        if c.get("id") == cid:
            return c
    return None


def say(text: str, wait: int = 45) -> None:
    p = subprocess.run(
        [PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SAY), "-Text", text, "-WaitSeconds", str(wait)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
    )
    out = ((p.stdout or "") + (p.stderr or "")).strip().splitlines()
    print("    " + (out[-1] if out else "(无语输出)"))
    if p.returncode != 0:
        raise SystemExit("⚠️ 这一轮没发出去（见上一行），停下来别继续——继续下去数据是错的")


def wait_reply(cid: str, prev_msgs: int, timeout: int = 240) -> dict | None:
    """等这一轮的回答落地（盘点文件的信号比固定 sleep 可靠：persist 在一轮跑完才写）。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = pull_convs()
        c = by_id(d, cid) if d else None
        if c and len(c["messages"]) > prev_msgs:
            last = c["messages"][-1]
            if last.get("role") == "assistant" and (last.get("text") or "").strip() and not last.get("isError"):
                return c
        time.sleep(4)
    return None


def main() -> int:
    d = pull_convs()
    if not d:
        print("❌ 读不到对话文件（App 没登录？adb 不通？）")
        return 1
    # ⚠️ **空对话根本不落盘**（`persist()` 第一次发送时才写），所以"当前是哪个对话"没法从盘上读出来。
    #    可靠的信号是**差集**：第一轮发完之后，多出来的那个 id 就是我们在聊的这个。
    before_ids = {c.get("id") for c in d.get("conversations", [])}
    print(f"开跑前盘上有 {len(before_ids)} 个对话；第一轮发完用差集锁定当前这个。")

    turns = [ANCHOR_Q, *FILLERS, RECALL_Q]
    anchor_answer = ""
    cid = ""

    for i, q in enumerate(turns, 1):
        c = by_id(pull_convs(), cid) if cid else None
        before = len(c["messages"]) if c else 0
        print(f"\n[{i}/{len(turns)}] 预算触发前历史 ≈ {history_tokens(c['messages']) if c else 0} token"
              f"（预算 {8000}）｜问：{q[:34]}…")
        say(q)
        if not cid:
            d = pull_convs()
            fresh = [c for c in d.get("conversations", []) if c.get("id") not in before_ids and c.get("messages")]
            if not fresh:
                print("    ❌ 发完之后没有出现新对话——你是不是在旧对话里发的？停下来看截图")
                return 1
            c = max(fresh, key=lambda x: x.get("updatedAt") or 0)
            cid = c["id"]
            print(f"    锁定新对话 {cid[:8]}（盘上原有 {len(before_ids)} 个，差集 {len(fresh)} 个）")
        c = wait_reply(cid, before)
        if c is None:
            print("    ❌ 等不到回答（超时）——停下来看截图，别把后面的结论建立在这上面")
            return 1
        msgs = c["messages"]
        hist = history_tokens(msgs)
        print(f"    答完了：{len(msgs)} 条消息，历史 ≈ {hist} token"
              f"，summary={len(c.get('summary') or '')} 字，compactedUpTo={c.get('compactedUpTo', 0)}")
        if i == 1:
            anchor_answer = (msgs[-1].get("text") or "").strip()
            print(f"    锚点答案：{anchor_answer[:60]!r}")

    # ---------------- 判定 ----------------
    d = pull_convs()
    c = by_id(d, cid)
    msgs = c["messages"]
    hist_before = history_tokens(msgs)
    recall = ""
    for m in reversed(msgs):
        if m.get("role") == "assistant" and (m.get("text") or "").strip():
            recall = (m.get("text") or "").strip()
            break
    n_anchor = ANCHOR_RE.search(anchor_answer)
    print("\n================ 判定 ================")
    print(f"对话长度：{len(msgs)} 条消息")
    print(f"收口前历史 ≈ {hist_before} token（预算 8000；超过说明这一轮会走 fitToBudget）")
    print(f"summary = {len(c.get('summary') or '')} 字，compactedUpTo = {c.get('compactedUpTo', 0)}")
    print(f"\n回忆轮回答：{recall[:400]!r}\n")

    ok_budget = (c.get("compactedUpTo", 0) > 0) and bool((c.get("summary") or "").strip())
    print(("✅ " if ok_budget else "❌ ") + "预算真的触发了：摘要已生成、compactedUpTo 已推进")

    ok_recall = bool(n_anchor) and n_anchor.group(0) in recall
    print(("✅ " if ok_recall else "❌ ") +
          f"跨过收口边界仍答得对：第一轮答案是 {n_anchor.group(0) if n_anchor else '?'}，"
          f"回忆轮{'答对了' if ok_recall else '**没答对**'}")
    return 0 if (ok_budget and ok_recall) else 2


if __name__ == "__main__":
    sys.exit(main())
