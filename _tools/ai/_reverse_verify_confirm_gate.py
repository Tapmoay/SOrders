"""反向验证「拿不到卡时两种话必须分开说」那一组检查（`_check_ai_guardrails.py` §2d-3b）**真的会红**。

### 为什么要单独一个脚本
BUG-0021（真机 2026-10-10 复现）：用户点确认时卡片已经过期，聊天页回的是
「⚠️ 没写成：这次操作已经执行过、或者已经过期（确认卡 5 分钟内有效）。请重新发起。」
—— 前缀说"没写"，正文说"也许已经写了"。对一笔钱的写操作，用户只有一个问题
（"我的账到底动没动？"），而这句话把两个答案一起给了他。

修法只有一句话："写成功那一刻把 token 记下来，两种回执才分得开"。**这句话全靠人记得**：
`take()` 在数据层上本来就是把三种原因合成一个 null 的，编译器不会拦你；单测也只在
"有人写了那条用例"时才拦得住（这一轮确实写了，可它们管不了界面那半句）。
所以这组判据必须有一份"注入 bug 就报错"的证据。

用法：python _tools/ai/_reverse_verify_confirm_gate.py     # 8/8 都红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_ai_guardrails.py"
AI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
WRITE = AI / "AiWrite.kt"
SERVICE = AI / "AiWriteService.kt"
CHAT = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiChatViewModel.kt"


def read_src(p: Path):
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> bytes:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    out = data.encode("utf-8")
    p.write_bytes(out)
    return out


def restore_src(p: Path, text: str, crlf: bool) -> None:
    # 还原**当场核对**：写回后重新读回来比，对不上就非零退出（体例见 `_reverse_verify_card_markdown.py`）。
    wrote = write_src(p, text, crlf)
    if p.read_bytes() != wrote:
        print("⛔ 还原后与快照不一致（注入污染了源码树）：" + str(p))
        raise SystemExit(2)


def run_check() -> str:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return (r.stdout or "") + (r.stderr or "")


MUTATIONS = [
    (
        "把「写成功之后记下 token」改名（两种回执就再也分不开）",
        WRITE,
        "    fun markWritten(token: String) {",
        "    fun noteWritten(token: String) {",
        "写成功之后记下 token",
    ),
    (
        "去掉回执上的「是不是已经写进去了」这一位",
        WRITE,
        "        val alreadyWritten: Boolean = false,",
        "        val writtenBefore: Boolean = false,",
        "拒绝回执带了「是不是已经写进去了」这一位",
    ),
    (
        "「这个 token 写过没有」改名",
        WRITE,
        "    fun hasWritten(token: String): Boolean = synchronized(lock) { token in doneTokens }",
        "    fun wasWritten(token: String): Boolean = synchronized(lock) { token in doneTokens }",
        "并且能问「这个 token 写过没有」",
    ),
    (
        # 最容易写歪的一种：把"记下"提到 commit 之前 —— 写失败时 token 也被 take 走了，
        # 于是第二次点击会被谎报成"已经写进去了"（比不说还糟）。
        "把「记下 token」挪到 commit 之前（写失败也会被记成写过了）",
        SERVICE,
        '            ClientOrigin.asAi(p.actionId) { handler.commit(p.payload, "ai-" + token) }\n'
        "            // 写成功这一刻才记下 token（BUG-0021）：上面这句抛异常时**不能**记，\n"
        "            // 否则用户重试同一张卡会被谎报成「已经写进去了」；记下之后，连点第二下\n"
        "            // 拿到的那句回执才说得准（见本函数开头）。\n"
        "            store.markWritten(token)",
        '            store.markWritten(token)\n'
        '            ClientOrigin.asAi(p.actionId) { handler.commit(p.payload, "ai-" + token) }',
        "记的时机在 commit",
    ),
    (
        "连点第二下的回执不再承认「已经写进去了」",
        SERVICE,
        "这一次已经写进去了（同一张确认卡只生效一次）",
        "这一次执行过了（同一张确认卡只生效一次）",
        "连点第二下时承认「已经写进去了」",
    ),
    (
        "过期那一支不再明说「什么都没写」",
        SERVICE,
        "这一次什么都没写。要办的话请重新发起。",
        "这一次的状态不确定。要办的话请重新发起。",
        "过期 / 取消 / 重启那一支明说「什么都没写」",
    ),
    (
        "把旧的那句「已经执行过、或者已经过期」塞回去",
        SERVICE,
        "这一次什么都没写。要办的话请重新发起。",
        "这次操作已经执行过、或者已经过期。请重新发起。",
        "那句两半互相打架的旧话不许回来",
    ),
    (
        # 界面是最后一道：数据层分开了，界面照样可以给它冠上「没写成」。
        "界面对「已经写进去了」的回执照样冠「没写成」",
        CHAT,
        "                    if (outcome.alreadyWritten) {",
        "                    if (false) {",
        "界面按「写过没有」换口气",
    ),
]


def main() -> int:
    bad = 0
    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) < 1:
            print(f"  [SKIP] {label} —— 原文没找到：{old[:40]}")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            out = run_check()
        finally:
            restore_src(path, src, crlf)
        fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
        hit = any(expect in ln for ln in fails)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → 期望红：{expect}（实际红 {len(fails)} 条）")
        if not hit:
            for ln in fails[:3]:
                print("        " + ln.strip())
            bad += 1
    tail = run_check()
    ok = "项通过" in tail
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1
    total = len(MUTATIONS) + 1
    print("\n" + (f"✅ {total}/{total} 都红了：这条检查真的在检查。" if bad == 0 else f"❌ {bad}/{total} 不达标。"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
