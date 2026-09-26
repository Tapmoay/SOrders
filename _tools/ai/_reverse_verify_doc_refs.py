"""反向验证「文档引用完整性」这条检查**真的在检查**（它曾经红了 12 轮没人管）。

### 背景
`_ai_doc_check.py` 原来把 `§2e`、`§2f-2b` 这类**红线小节号**当成文档小节号去查，
于是永远报"不存在的引用"、永远退出码 1，而每轮的收尾清单里没有它——
**一条永远红的检查等于没有检查**（没人会去看一条总是红的输出）。
修好之后，它必须能被反向验证：注入一个假引用、或者把红线的子条目改名，都必须变红。

用法：python _tools/ai/_reverse_verify_doc_refs.py     # 3/3 都红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_ai_doc_check.py"
V3 = ROOT / "docs" / "AI_ASSISTANT_PLAN_V3.md"
GUARD = HERE / "_check_ai_guardrails.py"


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
    # 还原**当场核对**（R3-07b）：写回后**重新读回来比**，对不上就非零退出。
    # ⛔ 「写了还原」不是证明；重新读回来的内容 == 快照 才是（L2 要的就是这一句）。
    # 实测教训（2026-09-26）：有份反向验证的还原写的是**另一个文件的字节**，而它自己那句核对
    # 比的也是同一份错字节 ⇒ 恒等通过，把两个源码文件整份写坏。
    wrote = write_src(p, text, crlf)
    if p.read_bytes() != wrote:
        print('⛔ 还原后与快照不一致（注入污染了源码树）：' + str(p))
        raise SystemExit(2)

def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def sub(path: Path, old: str, new: str):
    def mutate(src: str) -> str:
        return src.replace(old, new, 1)

    return (path, mutate)


MUTATIONS = [
    (
        "文档里写一个根本不存在的红线小节号（§99z）",
        [sub(V3, "### 32.1 新增 5 个动作", "### 32.1 新增 5 个动作（见 §99z）")],
        "对不上的引用",
    ),
    (
        "红线的子条目改了号，而文档还引用旧号（§2g-2b 成了死引用）",
        [sub(GUARD, "# ---- 2g-2b 目标参数与字段参数", "# ---- 2g-2c 目标参数与字段参数")],
        "对不上的引用",
    ),
    (
        "红线小节改了号，而文档还引用旧号（§2f 整节成了死引用）",
        [sub(GUARD, 'print("\\n== 2f. 写动作的处理器', 'print("\\n== 2z. 写动作的处理器')],
        "对不上的引用",
    ),
    (
        "红线脚本印不出任何小节号了（正则过期 → 这条检查会空转）",
        [
            (
                GUARD,
                lambda src: src.replace('print("\\n== ', 'print("\\n__ '),
            )
        ],
        "没能从红线脚本里读出小节号",
    ),
]


def main() -> int:
    bad = 0
    code, out = run_check()
    base_ok = code == 0
    print(f"  [{'OK' if base_ok else 'MISS'}] 基线：引用都能对上时退出码 0（实际 {code}）")
    bad += 0 if base_ok else 1

    for label, changes, expect in MUTATIONS:
        originals = []
        skip = False
        for path, mutate in changes:
            src, crlf = read_src(path)
            mutated = mutate(src)
            if mutated == src:
                print(f"  [SKIP] {label} —— 锚点没找到：{path.name}")
                skip = True
                break
            originals.append((path, src, crlf))
            write_src(path, mutated, crlf)
        if skip:
            for path, src, crlf in originals:
                write_src(path, src, crlf)
            bad += 1
            continue
        try:
            code, out = run_check()
        finally:
            for path, src, crlf in originals:
                restore_src(path, src, crlf)
        hit = code != 0 and expect in out
        print(f"  [{'OK' if hit else 'MISS'}] {label} → 期望红：{expect}（实际退出码 {code}）")
        if not hit:
            for ln in out.splitlines()[-3:]:
                print("        " + ln.strip())
            bad += 1

    code, out = run_check()
    ok = code == 0
    print("  [OK] 还原后文档自检恢复正常" if ok else "  [MISS] 还原后没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + 2
    print("\n" + (f"✅ {total}/{total} 都红了：这条检查真的在检查。" if bad == 0 else f"❌ {bad}/{total} 不达标。"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
