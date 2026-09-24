"""反向验证 `_tools/qa/_check_migrations.py`（红线：迁移体系不许静默退化）。

## 为什么必须做

迁移体系的坏法全是**安静**的：

- 记账写在了执行**之前** → 一次失败的迁移被记成"跑过了"，下次启动不再重试，结构永远停在半截；
- 改了历史迁移没人拦 → 别人的库和你以为的不是一个东西；
- 文件名丢了版本号 → 一个"看起来像迁移、谁也不跑"的文件（比没有迁移更危险）；
- 校验和没归一 CRLF → 本机绿、生产红，然后所有人都学会无视这条检查；
- 运行器**没人调用** → 一切都对，就是从来没跑过。

所以逐条注入真缺陷，每条都必须让判据报红；跑完逐字节还原并再验一次绿。

用法：python _tools/qa/_reverse_verify_migrations.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_migrations.py"
MIG = ROOT / "backend" / "app" / "migrations"
RUNNER = MIG / "_runner.py"
BASELINE = MIG / "001_baseline.py"
BOOTSTRAP = ROOT / "backend" / "app" / "core" / "schema_bootstrap.py"
BACKUP_SH = ROOT / "_tools" / "backup" / "_backup.sh"
TESTS = ROOT / "backend" / "tests" / "test_schema_migrations.py"

#: (说明, 文件, 把源码变成什么) —— mutate 返回原文表示"替换串过期了"，会被判为失败。
CASES: list[tuple[str, Path, object]] = [
    # ---- ① 记账顺序（最危险的一条：没跑也算跑过） ----
    (
        "记账写到执行之前（失败的迁移会被记成成功）",
        RUNNER,
        lambda s: s.replace(
            "    migrations = discover(directory, load=True)",
            '    migrations = discover(directory, load=True)  # INSERT INTO {VERSION_TABLE}', 1),
    ),
    # ---- ② 失败不许被吞 ----
    (
        "失败不再抛 MigrationFailed（改成只记日志）",
        RUNNER,
        lambda s: s.replace("                raise MigrationFailed(f\"{m.version:03d}_{m.name} 失败：{e}\") from e",
                            "                pass", 1),
    ),
    # ---- ③ 漂移不许拦启动 ----
    (
        "改过的历史迁移直接抛异常（一个笔误就能把线上打死）",
        RUNNER,
        lambda s: s.replace("                    logger.error(\n",
                            "                    raise MigrationError(\n", 1),
    ),
    # ---- ④ 校验和必须跨平台一致 ----
    (
        "校验和不再归一 CRLF（Windows 与 Linux 会算出不同的值）",
        RUNNER,
        lambda s: s.replace('raw = path.read_bytes().replace(b"\\r\\n", b"\\n")',
                            "raw = path.read_bytes()", 1),
    ),
    # ---- ⑤ 命名与版本号 ----
    (
        "文件里的 VERSION 与文件名前缀不一致（skip 判据会按文件名走）",
        BASELINE,
        lambda s: s.replace("VERSION = 1", "VERSION = 2", 1),
    ),
    (
        "迁移没有 upgrade()（跑起来才发现）",
        BASELINE,
        lambda s: s.replace("def upgrade(engine: Engine) -> None:", "def apply(engine: Engine) -> None:", 1),
    ),
    (
        "迁移没有 DESCRIPTION（日志里说不清它是什么）",
        BASELINE,
        lambda s: s.replace('DESCRIPTION = "基线：登记当前结构（不执行 DDL）；此前结构由 schema_bootstrap 自愈保证"',
                            'NOTE = "x"', 1),
    ),
    # ---- ⑥ 接线（没人调的运行器＝装饰品） ----
    (
        "bootstrap 不再调用 run_migrations（运行器成了装饰品）",
        BOOTSTRAP,
        lambda s: s.replace("        run_migrations(engine)", "        pass", 1),
    ),
    (
        "bootstrap 不再处理 MigrationFailed（失败被静默忽略）",
        BOOTSTRAP,
        lambda s: s.replace("    except MigrationFailed as e:", "    except Exception as e:", 1),
    ),
    (
        "逃生开关被删（带病启动没有显式入口，只能改代码）",
        BOOTSTRAP,
        lambda s: s.replace('os.environ.get("SORDERS_SKIP_MIGRATIONS")', 'os.environ.get("NOPE")', 1),
    ),
    # ---- ⑦ 表名单点 ----
    (
        "app/ 下第二处手写表名（备份脚本与运行器会各写各的）",
        BOOTSTRAP,
        lambda s: s.replace("        run_migrations(engine)",
                            '        _t = "schema_versions"\n        run_migrations(engine)', 1),
    ),
    (
        "备份脚本不再记录 schema_version（恢复时对不上代码版本）",
        BACKUP_SH,
        lambda s: s.replace("schema_versions", "no_such_table", 1),
    ),
    # ---- ⑧ 单测不许被掏空 ----
    (
        "单测被删掉一条（判据下限靠数量守着）",
        TESTS,
        lambda s: s.replace("def test_baseline_is_a_noop", "def _disabled_baseline_is_a_noop", 1),
    ),
]

#: 额外文件型的注入（写完即删）：(说明, 路径, 内容)
EXTRA_CASES: list[tuple[str, Path, str]] = [
    (
        "多了一个没有版本号的文件（看起来像迁移、谁也不跑）",
        MIG / "foo_migration.py",
        "def upgrade(engine):\n    pass\n",
    ),
    (
        "版本号重复（两条迁移抢同一个版本）",
        MIG / "001_duplicate.py",
        'VERSION = 1\nNAME = "duplicate"\nDESCRIPTION = "x"\n\n\ndef upgrade(engine):\n    pass\n',
    ),
]


def run_check() -> int:
    return subprocess.run([sys.executable, str(CHECK), "--check"], capture_output=True, cwd=str(ROOT)).returncode


def main() -> int:
    files = sorted({p for _, p, _ in CASES})
    before = {str(p): p.read_text(encoding="utf-8") for p in files}
    if run_check() != 0:
        print("❌ 前提不成立：源码完好时这条判据就没过（先让 _check_migrations.py 变绿）")
        return 1
    print("✅ 前提：源码完好时判据是绿的")

    fails: list[str] = []
    caught = 0

    for label, path, mutate in CASES:
        original = path.read_text(encoding="utf-8")
        mutated = mutate(original)
        if mutated == original:
            fails.append(f"{label}：注入没生效（替换串过期了，请更新本脚本）")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            code = run_check()
        finally:
            path.write_text(original, encoding="utf-8", newline="")
        if code != 0:
            caught += 1
            print(f"✅ 注入「{label}」→ 报红")
        else:
            fails.append(f"{label}：注入之后没有报红 —— 这条判据是空转的")

    for label, path, body in EXTRA_CASES:
        if path.exists():
            fails.append(f"{label}：注入前文件已存在，跳过（{path.name}）")
            continue
        try:
            path.write_text(body, encoding="utf-8")
            code = run_check()
        finally:
            path.unlink(missing_ok=True)
        if code != 0:
            caught += 1
            print(f"✅ 注入「{label}」→ 报红")
        else:
            fails.append(f"{label}：注入之后没有报红 —— 这条判据是空转的")

    for k, v in before.items():
        if Path(k).read_text(encoding="utf-8") != v:
            fails.append(f"收尾没还原：{k}")
    for _, path, _ in EXTRA_CASES:
        if path.exists():
            fails.append(f"收尾没删掉注入文件：{path}")
    if run_check() != 0:
        fails.append("还原之后判据仍然红（有文件没被改回来）")

    total = len(CASES) + len(EXTRA_CASES)
    if fails:
        print("\n❌ 反向验证没通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ {caught}/{total} 种破坏方式全部被抓到，且源码已还原。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
