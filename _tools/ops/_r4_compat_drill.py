# -*- coding: utf-8 -*-
"""R4-07 的 **Compatibility 演练**：契约从 v1 走到 v2，旧实现照样跑。

## 它证的是什么（指南 §17 / §40）

> 故意：PricingContract v1 -> v2 implementation。
> 验证：**旧实现还能工作 / 新实现可以加入 / 核心无需修改**。

## ⚠️ 顺序本身就是指南的一部分（§18）

> R4 的原则：**先证明"这个契约真的会被多个实现使用"，再为它设计长期版本兼容。**

所以这一轮不是一上来就设计 v1/v2/v3 —— 是**到 R4-05 已经有两个实现了**之后才加 v2，
而且 v2 只加**一个**方法（`breakdown`）。⛔ 不搞 compatibility matrix（§18 明确否掉的过度设计）。

## 四个数

1. **Core 修改数 = 0**（区间内；v2 契约与适配器在区间**之前**那一次提交里落地）；
2. **既有扩展模块修改数 = 0**（只许新增实现文件）；
3. **旧实现还能工作**：每个 v1 实现经 `as_v2()` 适配器后仍能出结果，
   且**明细各行之和等于总额**（明细不许变成第二份真相）；
4. **新实现可以加入**：v2 实现被认领，并给出**多行**原生明细。

用法：
    python _tools/ops/_r4_compat_drill.py --record base    # v2 契约与适配器落地之后
    python _tools/ops/_r4_compat_drill.py --record head    # v2 实现落地之后
    python _tools/ops/_r4_compat_drill.py --check          # 核四个数（CI 安全，不联网、不碰生产）
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
RECORD = ROOT / "_tools" / "ops" / "r4_drill_records" / "compat-drill.json"
CONTRACT_TEST = "tests/test_pricing_contract.py"

CORE_PATHS = (
    "backend/app/core", "backend/app/services", "backend/app/api", "backend/app/models",
    "backend/app/commands", "backend/app/schemas", "backend/app/deps.py",
    "backend/app/main.py", "backend/app/config.py", "backend/app/database.py",
)
EXTENSION_PATH = "backend/app/extensions/pricing"


def git(*args: str) -> tuple[int, str]:
    r = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def load() -> dict:
    return json.loads(RECORD.read_text(encoding="utf-8")) if RECORD.exists() else {}


def save(data: dict) -> None:
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    RECORD.write_text(json.dumps(data, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")


def numstat(rng: str, *paths: str) -> int:
    code, out = git("diff", "--numstat", rng, "--", *paths)
    if code != 0:
        return -1
    total = 0
    for line in out.splitlines():
        parts = line.split(chr(9))
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            total += int(parts[0]) + int(parts[1])
    return total


def changed_ext_files(rng: str) -> list[tuple[str, str]]:
    code, out = git("diff", "--name-status", rng, "--", EXTENSION_PATH)
    if code != 0:
        return []
    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        parts = line.split(chr(9))
        if len(parts) >= 2:
            rows.append((parts[0].strip(), parts[1].strip()))
    return rows


def probe_runtime() -> dict:
    """在子进程里跑一段只读探针，把"旧实现还能工作 / 新实现能加入"两件事量出来。"""
    code = (
        "import json; from decimal import Decimal; "
        "from app.core.contracts.pricing import PricingContext, PricingContract, PricingContractV2, as_v2; "
        "from app.core.contracts.quantity import Quantity; "
        "from app.extensions.pricing import PROVIDERS, resolve_v2; "
        "out = {'providers': [p.name for p in PROVIDERS], 'v1_ok': [], 'v2_native': []}; "
        "for p in PROVIDERS: "
        "    kind = getattr(p, 'kind', None) "
        "    if not kind: continue "
        "    ctx = PricingContext(rule_snapshot={'pricing_kind': kind, 'amount': '120.00', 'unit_price': '8.50'}, "
        "                         unit_price=Decimal('8.50'), quantity=Quantity(Decimal('15'), '件', 'count')) "
        "    v2 = resolve_v2(ctx) "
        "    total = v2.price(ctx).money "
        "    lines = v2.breakdown(ctx) "
        "    s = lines[0].money "
        "    for ln in lines[1:]: s = s + ln.money "
        "    out['v1_ok'].append([p.name, isinstance(v2, PricingContract), isinstance(v2, PricingContractV2), "
        "                        s.amount == total.amount, len(lines)]) "
        "    if isinstance(p, PricingContractV2): out['v2_native'].append(p.name) "
        "print(json.dumps(out, ensure_ascii=False))"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT / "backend"), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    for line in reversed(((r.stdout or "") + (r.stderr or "")).splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return {"providers": [], "v1_ok": [], "v2_native": [], "error": (r.stderr or "")[-300:]}


def run_contract_tests() -> tuple[int, str]:
    r = subprocess.run([sys.executable, "-m", "pytest", CONTRACT_TEST, "-q"],
                       cwd=str(ROOT / "backend"), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def do_record(role: str) -> int:
    if role not in ("base", "head"):
        print("--record 只认 base / head")
        return 1
    data = load()
    data[role] = git("rev-parse", "HEAD")[1].strip()
    data[role + "_providers"] = probe_runtime().get("providers", [])
    save(data)
    print("已记录 " + role + " = " + data[role][:12] + "，当时有实现 " + str(data[role + "_providers"]))
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if "--record" in argv:
        i = argv.index("--record")
        return do_record(argv[i + 1] if i + 1 < len(argv) else "")

    data = load()
    base, head = data.get("base"), data.get("head")
    print("== Compatibility 演练：契约 v1 -> v2，旧实现照样跑 ==")
    if not base or not head:
        print("还没记录区间：先跑 --record base（v2 契约与适配器落地后）与 --record head（v2 实现落地后）")
        return 1
    rng = base + ".." + head
    print("  区间：" + base[:12] + ".." + head[:12])
    print("  当时实现：" + str(data.get("base_providers")) + " -> " + str(data.get("head_providers")))
    print()

    fails: list[str] = []
    if git("merge-base", "--is-ancestor", head, "HEAD")[0] != 0:
        fails.append("记录的 head 不是当前 HEAD 的祖先 —— 那条历史不在了")

    core_delta = numstat(rng, *CORE_PATHS)
    print("  1) Core 修改数 = " + str(core_delta) + " 行" + ("  OK" if core_delta == 0 else "  FAIL"))
    if core_delta != 0:
        fails.append("核心被改了 " + str(core_delta) + " 行 —— 「核心无需修改」不成立")

    rows = changed_ext_files(rng)
    modified = [(s, p) for s, p in rows if not s.startswith("A")]
    added = [p for s, p in rows if s.startswith("A")]
    print("  2) 既有扩展模块修改数 = " + str(len(modified)) + " 个"
          + ("  OK" if not modified else "  FAIL " + str(modified)))
    print("     新增文件 " + str(len(added)) + " 个：" + str([Path(p).name for p in added]))
    if modified:
        fails.append("扩展包里已有文件被改了：" + str(modified))

    rt = probe_runtime()
    if rt.get("error"):
        fails.append("运行时探针失败：" + str(rt["error"])[:160])
    v1_ok = rt.get("v1_ok", [])
    print("  3) 旧实现还能工作（经适配器后仍是 v1、也是 v2、明细加起来 == 总额）：")
    for name, is_v1, is_v2, sums, nlines in v1_ok:
        print("     " + name + "  v1=" + str(is_v1) + " v2=" + str(is_v2)
              + " 明细自洽=" + str(sums) + " 行数=" + str(nlines))
        if not (is_v1 and is_v2 and sums):
            fails.append(name + " 经适配器后不满足 v1+v2 或明细对不上")
        if nlines < 1:
            fails.append(name + " 一行明细都给不出")
    if not v1_ok:
        fails.append("一个能算的实现都没有 —— 这条判据在空转")

    native = rt.get("v2_native", [])
    multi = [row for row in v1_ok if row[0] in native and row[4] > 1]
    print("  4) 新实现可以加入：原生 v2 实现 " + str(native) + "，其中给出多行明细的 " + str([r[0] for r in multi]))
    if not native:
        fails.append("一个原生 v2 实现都没有 —— 这条演练没东西可证")
    elif not multi:
        fails.append("原生 v2 实现没有给出多行明细 —— 那 v2 加的方法等于白加")

    code, out = run_contract_tests()
    failed = [ln.strip() for ln in out.splitlines() if " failed" in ln]
    passed = [ln.strip() for ln in out.splitlines() if " passed" in ln]
    print("  5) 契约用例：" + ((failed[-1] + " / ") if failed else "") + (passed[-1] if passed else "（无结果行）")
          + ("  OK" if code == 0 else "  FAIL"))
    if code != 0:
        fails.append("契约用例没过")

    print()
    if fails:
        print("Compatibility 演练不成立：" + str(len(fails)) + " 条")
        for f in fails:
            print("   - " + f)
        return 1
    print("Compatibility 演练成立：新增 " + str(len(added)) + " 个实现文件，Core 改 0 行、既有扩展模块改 0 个，")
    print("   旧实现经适配器照常工作，新实现给得出原生多行明细。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())