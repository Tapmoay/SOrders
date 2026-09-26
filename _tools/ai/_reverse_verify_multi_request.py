"""注入验证：把「标记已读」处理器的 commitNote 摘掉 → 新红线必须报出来。"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# ⛔ 不许写死本机路径（`D:\AProjects\...` / `C:\Users\...`）：CI 在 /home/runner/... 上跑，
#    写死 = 这条反向验证在外面永远不生效，而本机看起来一切正常。根目录一律从 __file__ 推。
ROOT = Path(__file__).resolve().parents[2]
P = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteNotificationHandlers.kt"
BAK = Path(tempfile.gettempdir()) / "_noth_backup.kt"
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
    # R3-07b：还原**当场核对**（写回后再读回来逐字节比）
    if P.read_bytes() != BAK.read_bytes():
        print("⛔ 还原后与快照不一致（注入污染了源码树）：" + str(P))
        sys.exit(2)

out = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
if "MarkNotificationsReadHandler" in out and "commitNote" in out:
    print("✅ 注入「摘掉 commitNote」→ 红线报出 MarkNotificationsReadHandler（判据真的有牙）")
else:
    print("❌ 注入后红线没报 —— 这条检查是摆设")
    print(out[-600:])
    sys.exit(1)

p2 = subprocess.run([sys.executable, "_tools/ai/_check_ai_guardrails.py"], cwd=str(ROOT))
print("✅ 还原后红线恢复通过" if p2.returncode == 0 else "❌ 还原后仍然不通过")
