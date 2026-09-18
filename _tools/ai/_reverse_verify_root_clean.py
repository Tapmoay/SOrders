"""反向验证「仓库根目录不许堆临时产物」那条红线**真的会红**。

做法：在一个**临时克隆出来的目录结构**里验证不现实（那条红线读的是真仓库根），
所以这里用最直接也最诚实的办法——**真的往根目录放一个临时文件**，
跑检查看它是否报红，然后立刻删掉自己刚放的那个文件（只删自己放的，不碰别的）。

用法：python _tools/ai/_reverse_verify_root_clean.py    # 报红 → 退出码 0
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
# 名字要一眼看出是探针：万一脚本被杀在半路，它留下的东西也不该被误当成真产物。
PROBE = ROOT / "_zz_reverse_verify_probe.log"


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    fails: list[str] = []

    code, out = run_check()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时检查就没过\n{out[-1200:]}")
        return 1
    print("✅ 前提：根目录干净时检查是绿的")

    PROBE.write_text("reverse-verify probe\n", encoding="utf-8")
    try:
        code, out = run_check()
        hit = code != 0 and "根目录" in out and PROBE.name in out
        print(
            "✅ 根目录放一个临时文件 → 红线报红（并且点名是哪个文件）"
            if hit
            else f"❌ 放了临时文件检查居然还是绿的（判据是空转的）\n{out[-1200:]}"
        )
        if not hit:
            fails.append("根目录堆临时文件没被判红")
    finally:
        PROBE.unlink(missing_ok=True)

    code, out = run_check()
    if code != 0:
        fails.append("探针删掉之后检查没恢复绿")
        print(f"❌ 探针删掉之后检查没恢复绿\n{out[-1200:]}")
    else:
        print("✅ 探针删掉 → 红线恢复绿（没有留下副作用）")

    if fails:
        print("\n❌ 反向验证不通过：\n   - " + "\n   - ".join(fails))
        return 1
    print("\n✅ 这条判据证明会红。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
