"""真机验证：**「把全部货主名单列出来」现在能不能真的列全**。

判定不靠肉眼：
  · 从对话文件里取最后一轮回答；
  · 数它的表格行 / 列表项（`|` 行与 `- ` 行），与库里的真实条数对；
  · 再扫一遍回答里有没有"只看了前 N""跟我说一声"这类**把活儿推回给用户**的话。

用法：python _tools/ai/_probe_list_completeness.py "把全部货主名单列出来，一个都不要漏。"
前置：模拟器已开、App 已登录、**当前停在一个新对话页**（脚本不负责点导航）。
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
PS = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
SAY = Path(__file__).resolve().parent / "_emulator_say.ps1"
CONV = "files/ai_conversations_u1.json"

# 「把活儿推回给用户」的话术——出现任何一句就说明修得不彻底
PUSHBACK = ["跟我说一声", "说一声继续", "剩下的要接着看", "只看了前", "需要继续看吗", "要不要继续"]


def adb(*args: str, timeout: int = 120) -> bytes:
    return subprocess.run([ADB, "-s", SERIAL, *args], capture_output=True, timeout=timeout).stdout


def pull() -> dict | None:
    raw = adb("exec-out", "run-as", "com.tapmoay.sorders", "cat", CONV)
    if not raw or b"conversations" not in raw:
        return None
    try:
        return json.loads(raw.decode("utf-8", "replace").replace("\r\n", "\n"))
    except Exception:
        return None


def main() -> int:
    q = sys.argv[1] if len(sys.argv) > 1 else "把全部货主名单列出来，一个都不要漏。"
    d = pull()
    if not d:
        print("❌ 读不到对话文件")
        return 1
    before_ids = {c.get("id") for c in d.get("conversations", [])}
    print(f"问题：{q}")
    p = subprocess.run(
        [PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SAY), "-Text", q, "-WaitSeconds", "60"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
    )
    print(((p.stdout or "") + (p.stderr or "")).strip().splitlines()[-1:])
    if p.returncode != 0:
        return 1

    cid, c = "", None
    t0 = time.time()
    while time.time() - t0 < 300:
        d = pull()
        fresh = [x for x in d.get("conversations", []) if x.get("id") not in before_ids and x.get("messages")]
        c = max(fresh, key=lambda x: x.get("updatedAt") or 0) if fresh else None
        if c and c["messages"] and c["messages"][-1].get("role") == "assistant" and (c["messages"][-1].get("text") or "").strip():
            break
        time.sleep(5)
    if not c:
        print("❌ 没等到回答")
        return 1

    ans = c["messages"][-1]["text"].strip()
    lines = ans.splitlines()
    table_rows = [ln for ln in lines if ln.strip().startswith("|") and not re.match(r"^\s*\|[\s\-:|]+\|\s*$", ln)]
    bullets = [ln for ln in lines if ln.strip().startswith(("- ", "* ")) or re.match(r"^\s*\d+[.、]", ln)]
    items = max(len(table_rows) - 1, 0) + len(bullets)   # 表格行减掉表头
    hit = [w for w in PUSHBACK if w in ans]
    nums = [int(x) for x in re.findall(r"\b(\d{2,3})\b", ans)]

    print("\n================ 判定 ================")
    print(f"回答长度：{len(ans)} 字符 / {len(lines)} 行")
    print(f"数出来的条目：表格行 {max(len(table_rows) - 1, 0)} + 列表项 {len(bullets)} = **{items}**")
    print(f"回答里出现过的两位数以上的数字：{sorted(set(nums))[:12]}")
    print(f"把活儿推回给用户的措辞：{hit if hit else '（无）✅'}")
    print(f"\n回答开头 200 字：{ans[:200]!r}")
    print(f"回答结尾 200 字：{ans[-200:]!r}")

    ok = (items >= 50) and not hit
    print(("\n✅ " if ok else "\n❌ ") +
          (f"列表确实拉全了（{items} 条），且没有把'继续'推给用户" if ok else
           f"仍然不全或仍在推给用户（条目 {items}，推诿措辞 {hit}）"))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
