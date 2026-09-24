"""反向验证「权限点要么在用、要么有书面理由」这条红线**真的会红**（F8）。

## 四类破坏
| 注入 | 证明的是 |
|---|---|
| 新加一个没人用的权限点（不写理由） | 判据真的在看"有没有被引用" |
| 把一个**已经在用**的权限点塞进说明表 | "说明过期"也要红（防拿说明表当万能口子） |
| 把一个只在用的权限点从枚举里删掉、表里留着 | 化石检测 |
| 扫描目录指错 | 解析失效时必须喊，而不是安静地什么都不查 |

用法：python _tools/qa/_reverse_verify_permission_points.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_permission_points.py"
RBAC = "backend/app/core/rbac.py"
CHECKREL = "_tools/qa/_check_permission_points.py"

CASES: list[tuple[str, str, object]] = [
    (
        "新加一个没人用的权限点、也不写理由",
        RBAC,
        lambda s: s.replace(
            '    STATS_READ = "stats:read"\n',
            '    STATS_READ = "stats:read"\n    PROBE_DEAD_POINT = "probe:dead"\n',
            1,
        ),
    ),
    (
        "把一个**已经在用**的权限点塞进『只声明不用』的表（过期说明）",
        CHECKREL,
        # ⚠️ 2026-09-25：那 5 个读侧权限点**已经接上**（见 deps.py::require_any_permission），
        #    DECLARED_ONLY 因此变成了空表 —— 锚点跟着改成「往空表里塞两条已经在用的」，
        #    判据与期望一字未动（本仓库的规矩：只改锚点，不动判据）。
        lambda s: s.replace(
            "DECLARED_ONLY: dict[str, str] = {}",
            'DECLARED_ONLY: dict[str, str] = {\n'
            '    "USER_MANAGE": "注入：假装这个没在用",\n'
            '    "NOTIFICATION_READ": "注入：假装这个没在用",\n}',
            1,
        ),
    ),
    (
        "把说明表里的权限点从枚举里删掉（化石条目）",
        RBAC,
        lambda s: s.replace('    LEDGER_READ_ALL = "ledger:read_all"\n', "", 1),
    ),
    (
        "扫描目录指错（一个引用都找不到 → 全被当成没在用）",
        CHECKREL,
        lambda s: s.replace('BACKEND = ROOT / "backend/app"', 'BACKEND = ROOT / "backend/app/nope"', 1),
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> None:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    p.write_bytes(data.encode("utf-8"))


def run_check(target: Path | None = None) -> int:
    p = subprocess.run(
        [sys.executable, str(target or CHECK)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode


def main() -> int:
    fails: list[str] = []
    if run_check() != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({rel for _l, rel, _m in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}
    crlfs = {rel: b"\r\n" in originals[rel] for rel in touched}

    for label, rel, mutate in CASES:
        path = ROOT / rel
        plain = originals[rel].decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        tmp: Path | None = None
        try:
            if rel == CHECKREL:
                tmp = path.with_suffix(".py.injected")
                write_src(tmp, mutated, crlfs[rel])
                red = run_check(tmp) != 0
            else:
                write_src(path, mutated, crlfs[rel])
                red = run_check() != 0
        finally:
            if tmp is not None and tmp.exists():
                tmp.unlink()
            path.write_bytes(originals[rel])
        if red:
            print(f"  [OK] {label} → 红线报红")
        else:
            fails.append(f"{label}：注入之后红线**仍然全绿**（判据没牙）")
            print(f"  [MISS] {label} → 全绿")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
