# -*- coding: utf-8 -*-
"""R4-04 的 **Add 演练**：新增一个扩展实现，核心一个字节都不改。

## 它证的是什么（指南 §19 / §37）

> 先做：Unit / Dimension / Quantity / ConversionContract；然后实现 SI；
> 再增加 Imperial；然后 China-traditional。整个过程中：
> **Core 不应该为了新增一种单位而不断修改。这就是第一次真实证明。**

## 三个数（缺一个这条演练就不成立）

1. **Core 修改数 = 0**：`base..head` 之间，核心区（core / services / api / models / commands /
   schemas / deps / main / config / database）的改动行数必须是 0；
2. **既有扩展模块修改数 = 0**：同一区间里，`backend/app/extensions/` 下只允许出现**新增**（A），
   不允许出现修改（M）或删除（D）—— 也就是说"加一种单位"这件事，
   ⛔ 连扩展包里已有的文件都不用动；
3. **两个实现跑同一组契约用例**：`tests/test_unit_conversion_contract.py` 遍历 PROVIDERS，
   新增的实现自动被同一组用例跑一遍（那份用例**不认识任何一种单位**）。

## 为什么把两个 sha 记在文件里，而不是每次现算

"Core 修改数 = 0" 这句话说的是**加实现那一步**。之后再改核心（比如别的一轮整改），
不能让这条历史证据失效 —— 所以区间是**冻结的**：`base` = 落地第一个实现那一刻，
`head` = 落地第二个实现那一刻。每次跑 `--check` 都是拿同一段历史复核，**数不会漂**。

用法：
    python _tools/ops/_r4_add_drill.py --record base    # 落地第一个实现之后跑一次
    python _tools/ops/_r4_add_drill.py --record head    # 落地第二个实现之后跑一次
    python _tools/ops/_r4_add_drill.py --check          # 核三个数（CI 安全，不联网、不碰生产）
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
RECORD = ROOT / "_tools" / "ops" / "r4_drill_records" / "add-drill.json"
CONTRACT_TEST = "tests/test_unit_conversion_contract.py"

#: "核心"的边界 = 指南 §13 那条 `Core Contract <- Extension Implementation` 左边的全部。
CORE_PATHS = (
    "backend/app/core", "backend/app/services", "backend/app/api", "backend/app/models",
    "backend/app/commands", "backend/app/schemas", "backend/app/deps.py",
    "backend/app/main.py", "backend/app/config.py", "backend/app/database.py",
)
EXTENSION_PATH = "backend/app/extensions"
MIN_PROVIDERS = 2


def git(*args: str) -> tuple[int, str]:
    r = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def head_sha() -> str:
    return git("rev-parse", "HEAD")[1].strip()


def load() -> dict:
    if not RECORD.exists():
        return {}
    return json.loads(RECORD.read_text(encoding="utf-8"))


def save(data: dict) -> None:
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    RECORD.write_text(json.dumps(data, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")


def providers_now() -> list[str]:
    """当前有哪些实现（**运行时**问扩展包，不写死名单）。"""
    sys.path.insert(0, str(ROOT / "backend"))
    from app.extensions.unit_conversion import PROVIDERS

    return [p.name for p in PROVIDERS]


def numstat(rng: str, *paths: str) -> int:
    """这个区间里这些路径**改动行数合计**（增 + 删）。"""
    code, out = git("diff", "--numstat", rng, "--", *paths)
    if code != 0:
        return -1
    total = 0
    for line in out.splitlines():
        parts = line.split(chr(9))
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            total += int(parts[0]) + int(parts[1])
    return total


def changed_extension_files(rng: str) -> list[tuple[str, str]]:
    """区间里 extensions/ 下的 (状态, 路径)。"""
    code, out = git("diff", "--name-status", rng, "--", EXTENSION_PATH)
    if code != 0:
        return []
    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        parts = line.split(chr(9))
        if len(parts) >= 2:
            rows.append((parts[0].strip(), parts[1].strip()))
    return rows


def run_contract_tests() -> tuple[int, str]:
    r = subprocess.run([sys.executable, "-m", "pytest", CONTRACT_TEST, "-q"],
                       cwd=str(ROOT / "backend"), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def do_record(role: str) -> int:
    if role not in ("base", "head"):
        print("❌ --record 只认 base / head")
        return 1
    data = load()
    data[role] = head_sha()
    data[role + "_providers"] = providers_now()
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
    print("== Add 演练：新增一个单位换算实现，核心一个字节都不改 ==")
    if not base or not head:
        print("❌ 还没记录区间：先跑 --record base（第一个实现落地后）与 --record head（第二个落地后）")
        return 1
    rng = base + ".." + head
    print("  区间：" + base[:12] + ".." + head[:12])
    print("  当时实现：" + str(data.get("base_providers")) + " -> " + str(data.get("head_providers")))
    print()

    fails: list[str] = []

    code, out = git("merge-base", "--is-ancestor", head, "HEAD")
    if code != 0:
        fails.append("记录的 head 不是当前 HEAD 的祖先 —— 那条历史不在了")

    core_delta = numstat(rng, *CORE_PATHS)
    print("  ① Core 修改数 = " + str(core_delta) + " 行" + ("  ✅" if core_delta == 0 else "  ❌"))
    if core_delta != 0:
        fails.append("核心被改了 " + str(core_delta) + " 行 —— 这条演练的前提（Core 修改数 = 0）不成立")

    ext_rows = changed_extension_files(rng)
    modified = [(s, p) for s, p in ext_rows if not s.startswith("A")]
    added = [p for s, p in ext_rows if s.startswith("A")]
    print("  ② 既有扩展模块修改数 = " + str(len(modified)) + " 个"
          + ("  ✅" if not modified else "  ❌ " + str(modified)))
    print("     新增文件 " + str(len(added)) + " 个：" + str([Path(p).name for p in added]))
    if modified:
        fails.append("扩展包里已有文件被改了：" + str(modified))
    if len(added) < 1:
        fails.append("区间里一个新增实现文件都没有 —— 这不是一次 Add")

    now = providers_now()
    print("  ③ 当前实现：" + str(now) + "（≥" + str(MIN_PROVIDERS) + "）"
          + ("  ✅" if len(now) >= MIN_PROVIDERS else "  ❌"))
    if len(now) < MIN_PROVIDERS:
        fails.append("当前实现少于 " + str(MIN_PROVIDERS) + " 个 —— 同一组契约用例没有第二个实现可跑")

    code, out = run_contract_tests()
    # ⚠️ 挑**结果那一行**（含 passed/failed），不是最后一行 —— 应用启动时那两句 stderr 警告
    #    会排在最后，第一版就是把那句警告当成"用例结果"打出来的（实测）。
    tail = [ln.strip() for ln in out.splitlines() if " passed" in ln or " failed" in ln]
    print("  ④ 契约用例（每个实现各跑一遍）：" + (tail[-1] if tail else "（没有结果行）")
          + ("  ✅" if code == 0 else "  ❌"))
    if code != 0:
        fails.append("契约用例没过 —— 新实现没有守住契约")

    print()
    if fails:
        print("❌ Add 演练不成立：" + str(len(fails)) + " 条")
        for f in fails:
            print("   - " + f)
        return 1
    print("✅ Add 演练成立：新增 " + str(len(added)) + " 个实现文件，Core 改 0 行、既有扩展模块改 0 个，")
    print("   同一组契约用例把 " + str(len(now)) + " 个实现都跑过了。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())