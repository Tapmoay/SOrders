"""注入验证：把「标记已读」处理器的 commitNote 摘掉 → 新红线必须报出来。"""
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(r"D:\AProjects\ASDH\orders")
P = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteNotificationHandlers.kt"
BAK = Path(r"C:\Users\Optimistic\AppData\Local\Temp\_noth_backup.kt")
shutil.copy2(P, BAK)

src = P.read_text(encoding="utf-8")
old = """    /** 逐条结果（[commitNote] 取走即清空）——见下面 commit 里的说明。 */
    private var pendingNote: String? = null

    override fun commitNote(): String? = pendingNote.also { pendingNote = null }
"""
assert old in src, "锚点没找到"
P.write_text(src.replace(old, "", 1), encoding="utf-8", newline="")
try:
    p = subprocess.run([sys.executable, "_tools/ai/_check_ai_guardrails.py"],
                       cwd=str(ROOT), capture_output=True)
finally:
    shutil.copy2(BAK, P)

out = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
if "MarkNotificationsReadHandler" in out and "commitNote" in out:
    print("✅ 注入「摘掉 commitNote」→ 红线报出 MarkNotificationsReadHandler（判据真的有牙）")
else:
    print("❌ 注入后红线没报 —— 这条检查是摆设")
    print(out[-600:])
    sys.exit(1)

p2 = subprocess.run([sys.executable, "_tools/ai/_check_ai_guardrails.py"], cwd=str(ROOT))
print("✅ 还原后红线恢复通过" if p2.returncode == 0 else "❌ 还原后仍然不通过")
