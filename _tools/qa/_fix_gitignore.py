"""把 .gitignore 里被写坏的那一段修好，并补上这一轮发现的漏网产物。

为什么需要脚本：`.gitignore` 末尾被写进了一段 **UTF-16 片段**
（`_\\x00a\\x00r\\x00c\\x00h\\x00i\\x00v\\x00e\\x00/\\x00` + 两个裸 NUL），
于是 `_archive/` **实际上没有被忽略** —— git 看到的是"一个带 NUL 的怪行"，
而 `git status` 里就一直躺着一个 81MB 的 `_archive/`。手写这一行很容易再踩回去，
所以用脚本按**字节**修，并顺手补上同类的漏网项。

用法：python _tools/qa/_fix_gitignore.py [--dry]
"""
import io
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[annotation-unchecked]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
GI = ROOT / ".gitignore"

# 保留到这一行为止（之后是被写坏的那一段：UTF-16 残片 + NUL）
KEEP_UNTIL = "/_agent/"
# 这一轮补的规则：每一条都对应 `git status` 里真实出现的产物
ADDED = """

# ---- 本地工作区产物（v3.44 补：它们以前没被忽略，git status 里一直躺着）----
# ⚠️ 这一段的上一行原来是一段 **UTF-16 残片**（`_\\x00a\\x00r\\x00…`），
#    所以 `_archive/` 从来没被真正忽略过。改这里请用能看见字节的方式（`_tools/qa/_fix_gitignore.py`）。
/_archive/
/_dl/
/_amap_probe/
/_*.json
android/local.properties.dev
android/local.properties.bak
backend/sorders.db*
backend/_uvicorn.*
backend/_wal_launch*.py
_tools/**/out/
docs/ai/_backup_*/
_test_tools/*.log
_test_tools/*.png
_test_tools/*.tgz
"""


def main() -> int:
    raw = GI.read_bytes()
    txt = raw.decode("utf-8", errors="replace")
    if "本地工作区产物（v3.44 补" in txt and "\x00" not in txt:
        print("✅ 已经修过了（NUL 没有了、规则段也在）——不再重复追加，免得把规则写两遍")
        return 0
    lines = txt.splitlines()
    cut = None
    for i, ln in enumerate(lines):
        if ln.strip() == KEEP_UNTIL:
            cut = i + 1
            break
    if cut is None:
        print(f"❌ 找不到锚点 {KEEP_UNTIL!r} —— .gitignore 被改过了，先人工看一眼")
        return 1
    head = [ln for ln in lines[:cut] if "\x00" not in ln]
    bad = [i for i, ln in enumerate(lines) if "\x00" in ln]
    print(f"保留 {len(head)} 行；丢掉含 NUL 的行 {len(bad)} 条")
    new = "\r\n".join(head) + ADDED.replace("\n", "\r\n")
    if "--dry" in sys.argv:
        print(new[-900:])
        return 0
    io.open(GI, "w", encoding="utf-8", newline="").write(new)
    print(f"已重写 {GI}（{len(new)} 字符，UTF-8 无 BOM，CRLF）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
