"""反向验证：把「整单退货之后账本要两边都在」这条红线逐条弄坏，看它**真的会红**。

## 为什么这块必须反向验证

这一块坏掉的方式**全部不报错、不崩、界面上也看不出来**：
· 可见状态退回「只认已送达」→ 整单退货的单账上只剩一减，数字看着像真的；
· 顺手给红冲行也加状态要求 → 两行一起消失（比原缺陷更安静）；
· 营业额那边也放行 `RETURNED` → 账本与营业额又分家，两边都不报错；
· 只改代码不改口径说明 → 下一个人照着说明把它改回去；
· 回归用例被削弱成「至少有 1 行」/「相抵不是负数就行」→ 缺陷复现时用例照样绿。

⚠️ 本文件里的第 3、6 条注入打的是**用例自己**：本项目栽过「用例写着断言、其实是恒真」的形状，
所以「用例被削弱 → 判据必须红」与「源码被改坏 → 判据必须红」同等重要。

用法：python _tools/qa/_reverse_verify_ledger_scope_full_return.py    # 全部报红 → 退出码 0
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_ledger_scope_full_return.py"

SCOPE = ROOT / "backend/app/services/ledger_scope.py"
LOADER = ROOT / "backend/app/services/reports/loader.py"
TEST = ROOT / "backend/tests/test_ledger_scope_full_return.py"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "可见状态退回「只认已送达」（整单退货的单账上只剩一减 —— 这就是原缺陷）",
        SCOPE,
        "Order.status.in_((OrderStatus.DELIVERED, OrderStatus.RETURNED))",
        "Order.status == OrderStatus.DELIVERED",
        "已退货",
    ),
    (
        "顺手把红冲行也加上状态要求（两行一起消失，同一张单在账上整个不见）",
        SCOPE,
        "Ledger.source != LedgerSource.ORDER,",
        "Ledger.source.is_(None),",
        "红冲行",
    ),
    (
        "口径说明里的「已退货」被删（下一个人照着说明把代码改回去）",
        SCOPE,
        "订单**已送达或已退货**且",
        "订单**已送达**且",
        "口径首条",
    ),
    (
        "营业额那边也放行「已退货」（两个口径又分家：账本相抵 0、营业额还在算）",
        LOADER,
        "Order.status == OrderStatus.DELIVERED,",
        "Order.status.in_((OrderStatus.DELIVERED, OrderStatus.RETURNED)),",
        "营业额",
    ),
    (
        "回归用例被削弱：「两行都可见」改成「至少有 1 行」",
        TEST,
        "assert len(visible) == 2, (",
        "assert len(visible) >= 1, (",
        "两行都可见",
    ),
    (
        "回归用例被削弱：「相抵为 0」改成「相抵为 1 就行」",
        TEST,
        "Decimal(\"0\"), (",
        "Decimal(\"1\"), (",
        "相抵为 0",
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
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
    # 还原**当场核对**：写回后重新读回来逐字节比，对不上就非零退出。
    # ⛔ 「写了还原」不是证明；重新读回来的字节 == 刚写出去的字节 才是。
    wrote = write_src(p, text, crlf)
    if p.read_bytes() != wrote:
        print("⛔ 还原后与快照不一致（注入污染了源码树）：" + str(p))
        raise SystemExit(2)


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def verdict(expect: str) -> tuple[bool, str]:
    code, out = run_check()
    fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
    hit = code != 0 and any(expect in ln for ln in fails)
    return hit, "实际红 " + str(len(fails)) + " 条" + ("" if hit else "：" + str([f.strip()[:70] for f in fails[:2]]))


def main() -> int:
    bad = 0
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线没过");
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时这条红线是绿的")

    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print("  [SKIP] " + label + " —— 原文出现 " + str(src.count(old)) + " 次，无法唯一替换")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            hit, detail = verdict(expect)
        finally:
            restore_src(path, src, crlf)
        print("  [" + ("OK" if hit else "MISS") + "] " + label + " → " + detail)
        if not hit:
            bad += 1

    code, out = run_check()
    ok = code == 0
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + 1
    print("")
    if bad:
        print("❌ " + str(bad) + "/" + str(total) + " 条不成立（红线对它们不敏感）")
        return 1
    print("✅ " + str(total) + "/" + str(total) + " 全部成立：每条注入都让红线点出了那一条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
