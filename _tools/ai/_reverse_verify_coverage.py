"""反向验证「覆盖率脚本的『不做理由』表」**真的会拦住新缺口**。

### 为什么值得单独一个脚本
`_write_coverage.py` 在 v3.20 加了一条判据：**每个未覆盖的写端点都必须有一条写下来的
「为什么不给 AI」**。这条判据的价值全在"它会不会红"上——如果它永远返回 0，
那它只是把"还剩 14 个"换成了"还剩 14 个（都写了理由）"，
而**新出现一个真缺口时不会有任何声音**。

所以这里注入三类 bug，每一类都必须让脚本报错（退出码非零 + 打印"没有理由"）：

1. 删掉一条理由（模拟"这个端点确实是新缺口"）；
2. 把理由表的键写错（路径归一化变了：`orders/{id}/…` → `orders/{}/…`）；
3. 把"已覆盖"的判据改坏（所有端点都算覆盖）——那会让"未覆盖"永远是 0，
   理由表也就永远不会被用到（**最坏的一种**：检查还在、但已经不看任何东西了）。

用法：python _tools/ai/_reverse_verify_coverage.py     # 3/3 都红 → 退出码 0
"""
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
HERE = Path(__file__).resolve().parent
COVERAGE = HERE / "_write_coverage.py"


def read_src(p: Path):
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> None:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    p.write_bytes(data.encode("utf-8"))


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(COVERAGE), "--check"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def mutation_drop_reason(src: str) -> str:
    """删掉一条理由：那一条端点必须变成「没有理由」。"""
    return src.replace(
        '    ("POST", "orders/{}/driver-note"): "司机端动作：目标③司机端不开放 AI",\n',
        "",
        1,
    )


def mutation_wrong_key(src: str) -> str:
    """理由的键写错（路径没归一）：等于没写。"""
    return src.replace(
        '    ("POST", "orders/{}/driver-ack"): "司机端动作：目标③司机端不开放 AI",',
        '    ("POST", "orders/{id}/driver-ack"): "司机端动作：目标③司机端不开放 AI",',
        1,
    )


def mutation_all_covered(src: str) -> str:
    """把"已覆盖"判据改坏：什么都算覆盖 —— 理由表就永远不会被用到。"""
    return src.replace(
        "        covered = strong or weak\n",
        "        covered = True  # 反向验证注入的 bug\n",
        1,
    )


def mutation_stale_key(src: str) -> str:
    """给一个**不存在的端点**留一条理由：化石条目（比没有更糟）。"""
    return src.replace(
        '    ("POST", "auth/token"): "登录/注册：AI 不该碰凭据（v3.7 定的永久排除）",',
        '    ("POST", "auth/token"): "登录/注册：AI 不该碰凭据（v3.7 定的永久排除）",\n'
        '    ("POST", "auth/token-refresh"): "这条端点在 2026-01 就被删了，理由忘了一起删",',
        1,
    )


MUTATIONS = [
    ("删掉一条「不做」理由（＝出现真缺口）", mutation_drop_reason, "没有理由", 1),
    ("理由表的键写错（路径没归一，等于没写）", mutation_wrong_key, "没有理由", 1),
    # 覆盖判据被改坏时，"未覆盖"恒为 0 → 理由表永远不会被查。
    # 这时唯一能红的判据是"写了不做的端点同时被算成已覆盖"（自相矛盾），所以期望文案不同。
    ("把「已覆盖」判据改坏（未覆盖恒为 0，理由表成了摆设）", mutation_all_covered, "同时被算成已覆盖", 1),
    ("端点点名后理由没跟着改（化石条目）", mutation_stale_key, "对不上任何端点", 1),
]


def main() -> int:
    src, crlf = read_src(COVERAGE)
    code, out = run_check()
    base_ok = code == 0 and "0 条是真缺口" in out
    print(f"  [{'OK' if base_ok else 'MISS'}] 基线：理由表齐全时退出码 0（实际 {code}）")
    bad = 0 if base_ok else 1

    for label, mutate, expect, want_code in MUTATIONS:
        mutated = mutate(src)
        if mutated == src:
            print(f"  [SKIP] {label} —— 目标文本没找到（脚本被改过？）")
            bad += 1
            continue
        write_src(COVERAGE, mutated, crlf)
        try:
            code, out = run_check()
        finally:
            write_src(COVERAGE, src, crlf)
        hit = code == want_code and expect in out
        print(f"  [{'OK' if hit else 'MISS'}] {label} → 期望红：{expect}（实际退出码 {code}）")
        if not hit:
            for ln in out.splitlines()[-4:]:
                print("        " + ln.strip())
            bad += 1

    code, out = run_check()
    ok = code == 0 and "0 条是真缺口" in out
    print("  [OK] 还原后覆盖率脚本恢复正常" if ok else "  [MISS] 还原后没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + 2
    print("\n" + (f"✅ {total}/{total} 都红了：这条检查真的在检查。" if bad == 0 else f"❌ {bad}/{total} 不达标。"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
