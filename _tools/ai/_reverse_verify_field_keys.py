"""反向验证「字段 key 覆盖」这条新红线**真的会红**。

### 为什么值得单独一个脚本
这条检查的由来是一次**真机实测抓到的静默丢数据**：
`users.create` 的字段规格是 `textField("name", …).copy(key = "full_name")`，
payload 里存的是 `full_name`，而 commit 读的是 `p.str("name")` —— 永远是空。
表现：卡片上写着「姓名：AI测试账号」、执行完还回「已完成：新建货主账号：AI测试账号」，
而库里那条账号的姓名是空的（用户只会在名册里看到一个「未命名」）。

这条检查自己也很容易变成空转（"扫到了 0 个带 key 覆盖的字段"就是恒真），
所以除了注入 bug，还要验证**"扫不到东西"时会红**。

用法：python _tools/ai/_reverse_verify_field_keys.py     # 3/3 都红 → 退出码 0
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
MASTER = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteMasterData.kt"
BASIC = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteBasicData.kt"


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

def run_check() -> str:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return (r.stdout or "") + (r.stderr or "")


def sub(path: Path, old: str, new: str):
    def mutate(src: str) -> str:
        return src.replace(old, new, 1)

    return (path, mutate)


MUTATIONS = [
    (
        "把真机实测抓到的那个 bug 放回去（commit 按参数名 name 取 payload）",
        [sub(MASTER, 'fullName = p.str("full_name").orEmpty(),', 'fullName = p.str("name").orEmpty(),')],
        "USERS_CREATE: 字段 name→full_name 的 commit 不许按参数名取",
    ),
    (
        "把所有 key 覆盖改个名（＝一个都扫不到，这条检查会空转）",
        [
            (MASTER, lambda src: src.replace('key = "', 'keyDisabled = "')),
            (BASIC, lambda src: src.replace('key = "', 'keyDisabled = "')),
        ],
        "真的扫到了带 key 覆盖的字段",
    ),
    (
        "注释里写一句真代码（检查必须先把注释剥掉，否则会被注释骗）",
        [
            sub(
                MASTER,
                "        // ---------------------------------------------------------- 商品",
                '        // 反例：textField("name", …).copy(key = "full_name") + p.str("name")',
            )
        ],
        # 这条注释**不该**让任何检查变红：预期是全绿，所以反过来断言"没有变红"
        "__EXPECT_GREEN__",
    ),
]


def main() -> int:
    bad = 0
    base = run_check()
    base_ok = "项通过" in base
    print(f"  [{'OK' if base_ok else 'MISS'}] 基线：没有注入时红线全绿")
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
            out = run_check()
        finally:
            for path, src, crlf in originals:
                restore_src(path, src, crlf)

        fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
        if expect == "__EXPECT_GREEN__":
            # 注释不该影响结论：这一条要的是"仍然全绿"
            hit = "项通过" in out and not fails
            print(f"  [{'OK' if hit else 'MISS'}] {label} → 期望仍然全绿（注释不该被当成代码）")
            if not hit:
                for ln in fails[:3]:
                    print("        " + ln.strip())
            bad += 0 if hit else 1
            continue

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

    total = len(MUTATIONS) + 2
    print("\n" + (f"✅ {total}/{total} 都达标：这条检查真的在检查。" if bad == 0 else f"❌ {bad}/{total} 不达标。"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
