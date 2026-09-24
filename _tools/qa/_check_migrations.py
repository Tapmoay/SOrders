#!/usr/bin/env python3
"""_check_migrations.py —— 迁移体系（`backend/app/migrations/`）的静态判据。

### 为什么迁移体系需要"自己的检查"

报告 §18 规则 5：任何自动化工具都必须自己可验证。迁移尤其危险，因为**它平时什么都不说**：
跑对了没有任何输出，跑错了往往是几天后在库里以"数据少了一半"的形式出现。
这一族判据守的全是"恢复现场 / 上线当天"才会暴露的东西：

1. 文件名必须带版本号（否则那是一个"看起来像迁移、谁也不跑"的文件）；
2. 版本号唯一且与文件里的 `VERSION` 一致（不一致时 skip 判据会按文件名的版本号走）；
3. 失败的迁移**不许记账**（记账＝下次不重试＝结构永远半截）—— 判据看的是**源码顺序**；
4. 改了历史迁移**只报错不重跑、也不拦启动**（拦启动＝一个笔误把线上打死）；
5. `schema_versions` 这个名字**只能有一份**（备份脚本也读它，两边写岔了备份清单就永远是 None）；
6. 运行器必须真的**被 bootstrap 调用**（没人调的运行器＝装饰品）。

用法：
    python _tools/qa/_check_migrations.py --check    # 非零退出＝有问题（进 _check_all.py）
    python _tools/qa/_check_migrations.py            # 打印每一项
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIG_DIR = ROOT / "backend" / "app" / "migrations"
BOOTSTRAP = ROOT / "backend" / "app" / "core" / "schema_bootstrap.py"
BACKUP_SH = ROOT / "_tools" / "backup" / "_backup.sh"
TESTS = ROOT / "backend" / "tests" / "test_schema_migrations.py"

#: 判据条数下限：判据自己也会腐烂（文件改名/glob 写错），低于这个数说明这条检查空转了。
MIN_RULES = 18


#: 目标文件里「换行归一」那一句的字面量（用 chr(92) 拼出来，免得判据自己被转义骗到）。
CRLF_LITERAL = 'b"' + chr(92) + 'r' + chr(92) + 'n"'


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def code_only(src: str) -> str:
    """去掉注释与文档字符串 —— **判据只许锚在代码上**。

    ⚠️ 这一条是本仓库反复踩过的同一个坑（_check_all.py 的 docstring 里就写着）：
    判据去搜纯文本时会被**自己写的说明文字**满足 —— 比如「app/ 下别处不许再写 schema_versions」
    这条，bootstrap 的新注释里正好提到了一次它的名字，于是判据报红，而代码其实是对的。
    假红会让人学会无视检查（本项目 §15），所以这里一律先剥散文。
    """
    src = re.sub(r'"""[\s\S]*?"""', "", src)
    src = re.sub(r"'''[\s\S]*?'''", "", src)
    return re.sub(r"^[ \t]*#.*$", "", src, flags=re.M)


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")           # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    check_mode = "--check" in sys.argv

    passed: list[str] = []
    failed: list[str] = []

    def want(cond: bool, ok: str, bad: str) -> None:
        (passed if cond else failed).append(ok if cond else bad)

    # ---------------------------------------------------------- 1. 文件齐不齐
    for name in ("__init__.py", "_runner.py", "001_baseline.py", "__main__.py", "README.md"):
        want((MIG_DIR / name).exists(), f"存在 migrations/{name}", f"⛔ 缺 migrations/{name}")

    runner = read(MIG_DIR / "_runner.py")
    baseline = read(MIG_DIR / "001_baseline.py")
    main_py = read(MIG_DIR / "__main__.py")
    boot = read(BOOTSTRAP)

    # ---------------------------------------------------------- 2. 迁移文件命名与版本号
    mig_files = sorted(p for p in MIG_DIR.glob("*.py")
                       if not p.name.startswith("_") and p.name != "__init__.py")
    want(len(mig_files) >= 1, f"至少有 1 条迁移（当前 {len(mig_files)} 条）", "⛔ 一条迁移都没有")
    versions: list[tuple[int, str]] = []
    for p in mig_files:
        m = re.match(r"^(\d{3,})_([a-z0-9_]+)\.py$", p.name)
        want(m is not None, f"{p.name} 命名合规", f"⛔ {p.name} 不符合 NNN_名字.py（会静默不被执行）")
        if not m:
            continue
        versions.append((int(m.group(1)), p.name))
        src = read(p)
        v = re.search(r"^VERSION\s*=\s*(\d+)", src, re.M)
        want(v is not None and int(v.group(1)) == int(m.group(1)),
             f"{p.name} 里的 VERSION 与文件名一致",
             f"⛔ {p.name} 里的 VERSION（{v.group(1) if v else '缺失'}）与文件名前缀 {m.group(1)} 不一致")
        want(re.search(r"^def upgrade\(", src, re.M) is not None,
             f"{p.name} 有 upgrade(engine)", f"⛔ {p.name} 没定义 upgrade(engine)")
        want(re.search(r"^DESCRIPTION\s*=", src, re.M) is not None,
             f"{p.name} 有 DESCRIPTION", f"⛔ {p.name} 没写 DESCRIPTION（日志里就没法说清它是什么）")
    nums = [v for v, _ in versions]
    want(len(nums) == len(set(nums)), "版本号唯一", f"⛔ 版本号重复：{sorted(nums)}")
    want(nums == sorted(nums), "版本号递增排列", f"⛔ 版本号不递增：{nums}")

    # ---------------------------------------------------------- 3. 运行器的硬纪律
    want("raise MigrationFailed" in runner,
         "失败时抛 MigrationFailed（不吞）", "⛔ 运行器把迁移失败吞掉了")
    # 记账必须发生在 upgrade() **之后**（顺序反了＝"没跑也算跑过"）
    i_call = runner.find("upgrade(engine)")
    i_insert = runner.find(f"INSERT INTO {{VERSION_TABLE}}")
    if i_insert < 0:
        i_insert = runner.find("INSERT INTO {VERSION_TABLE}")
    want(i_call > 0 and i_insert > i_call,
         "先执行 upgrade 再写版本表（顺序正确）",
         "⛔ 版本表的 INSERT 出现在 upgrade() 之前 —— 失败的迁移会被记成成功")
    # 漂移分支里不许有 raise（改了历史迁移不能让 API 起不来）
    # ⚠️ 锚点必须选**代码行**、不能选那句中文说明：第一版锚在文案「已经跑过的迁移不许再改」上，
    #    而它在 logger.error 的参数里 —— 注入「把 logger.error 换成 raise」时 raise 落在锚点**之前**，
    #    判据看不见（反向验证当场抓到这条判据是空转的）。锚在 if 条件行上才稳。
    drift_at = runner.find('if applied[m.version]["checksum"] != m.checksum:')
    if drift_at > 0:
        seg = runner[drift_at:drift_at + 500]
        want("raise" not in seg, "漂移只报错不抛异常（不拦启动）",
             "⛔ 漂移分支里有 raise：一个笔误就能让线上起不来")
    else:
        want(False, "", "⛔ 找不到漂移分支（判据自身失效，请检查 _runner.py 的代码）")
    want("_CREATE_SQL" in runner and "\"mysql\"" in runner and "\"sqlite\"" in runner,
         "版本表两种方言都有建表语句", "⛔ 版本表缺方言（mysql/sqlite）的建表语句")
    want(CRLF_LITERAL in runner,
         "校验和前把 CRLF 归一到 LF",
         "⛔ 校验和没归一换行 —— Windows 与 Linux 会算出不同的值（生产上天天假红）")
    want("/tmp/sorders_migrations.lock" in runner,
         "迁移用独立的锁文件", "⛔ 迁移没有独立锁（与 bootstrap 共用会自锁死）")

    # ---------------------------------------------------------- 4. 接线：必须真的被调用
    want("from app.migrations import" in boot,
         "bootstrap 导入了迁移运行器", "⛔ bootstrap 没导入 run_migrations（没人调的运行器＝装饰品）")
    want("run_migrations(engine)" in boot,
         "bootstrap 调用了 run_migrations(engine)", "⛔ bootstrap 里没有 run_migrations(engine) 调用")
    i_heal = boot.find("def _bootstrap_impl")
    i_run = boot.find("run_migrations(engine)")
    want(i_run > i_heal > 0, "调用在 _bootstrap_impl 之内（自愈之后）",
         "⛔ run_migrations 不在 _bootstrap_impl 里 —— 迁移必须看到自愈过的结构")
    # ⚠️ 判据要锚在**处理器与取值**上，不能只搜名字：只搜 MigrationFailed 的话，
    #    顶上那句 from app.migrations import MigrationFailed 就能满足它（反向验证抓到过）。
    want("except MigrationFailed as e:" in boot,
         "bootstrap 捕获 MigrationFailed 并处理",
         "⛔ bootstrap 没有 except MigrationFailed（失败会被静默忽略或直接崩）")
    want('os.environ.get("SORDERS_SKIP_MIGRATIONS")' in boot,
         "带病启动有显式逃生开关（SORDERS_SKIP_MIGRATIONS=1）",
         "⛔ 逃生开关被改成别的取值/只剩文案 —— 出事时没有显式入口")

    # ---------------------------------------------------------- 5. 表名只有一份
    owners = []
    for p in (MIG_DIR / "_runner.py",):
        owners.append(("_runner.py", read(p)))
    want(all("schema_versions" in src for _, src in owners),
         "版本表名定义在 _runner.py", "⛔ _runner.py 里没有 schema_versions")
    bak = read(BACKUP_SH)
    want("schema_versions" in bak,
         "备份脚本会记录 schema_version（恢复时能对上代码版本）",
         "⛔ _tools/backup/_backup.sh 没读 schema_versions —— 备份清单里那一格永远是 none")
    # 别处不许再写一遍表名的字面量（除 _runner/__init__ 与备份脚本、README 外）
    strays = []
    for p in (ROOT / "backend" / "app").rglob("*.py"):
        if p.parent == MIG_DIR:
            continue
        if "schema_versions" in code_only(read(p)):      # ⚠️ 只搜代码：注释里提到它不算违规
            strays.append(str(p.relative_to(ROOT)))
    want(not strays, "app/ 下没有第二处手写表名", f"⛔ 这些文件又写了一遍 schema_versions：{strays}")

    # ---------------------------------------------------------- 6. 单测与 CLI
    t = read(TESTS)
    n_tests = len(re.findall(r"^def test_", t, re.M))
    want(n_tests >= 8, f"单测 {n_tests} 条（≥8）", f"⛔ 迁移单测只有 {n_tests} 条（<8）")
    # ⚠️ 只数条数挡不住「删掉一条」（反向验证抓到过：11 → 10 仍然 ≥8）。
    #    这里额外要求**五种行为各有一条具名单测** —— 删/改它们必须是故意的。
    for name, why in (
        ("test_second_run_is_a_noop", "幂等（跑过的不再跑）"),
        ("test_pending_run_in_version_order_and_create_tables", "按版本号顺序执行且真的落库"),
        ("test_failed_migration_is_not_recorded_and_retried", "失败不记账且会重试"),
        ("test_changed_historical_migration_is_reported_not_rerun", "改过的历史迁移只报错不重跑"),
        ("test_checksum_ignores_crlf", "校验和跨平台一致"),
        ("test_baseline_is_a_noop", "基线不许碰库（它只是版本锚点）"),
    ):
        want(f"def {name}(" in t, f"单测覆盖：{why}", f"⛔ 少了「{why}」那条单测（{name}）")
    for kw in ("drifted", "MigrationFailed", "_checksum"):
        want(kw in t, f"单测覆盖 {kw}", f"⛔ 单测没覆盖 {kw}")
    # ⚠️ 实测踩到：`from app.config import settings` 在 `app.config` 里**不存在**（只有 get_settings()）。
    #    `_runner.py` 里被 except 吞掉（版本号永远空），`__main__.py` 里**直接起不来**。
    for name in ("_runner.py", "__main__.py"):
        src = code_only(read(MIG_DIR / name))
        want("from app.config import settings" not in src,
             f"{name} 用 get_settings() 取配置",
             f"⛔ {name} 写成了 from app.config import settings（那个符号不存在，CLI 会直接起不来）")
    want("choices=[\"status\", \"upgrade\"]" in main_py,
         "CLI 有 status/upgrade 两个命令", "⛔ __main__.py 缺 status/upgrade")
    want(re.search(r"^\s*(from|import)\s+app\.database", code_only(main_py), re.M) is None,
         "CLI 不 import app.database（避免「看版本」顺带把自愈跑一遍）",
         "⛔ __main__.py 引了 app.database —— 那会在导入时执行 bootstrap")

    # ---------------------------------------------------------- 7. 数量判据（防空转）
    total = len(passed) + len(failed)
    want(total >= MIN_RULES, f"判据条数 {total} ≥ {MIN_RULES}",
         f"⛔ 只跑了 {total} 条判据（< {MIN_RULES}）—— 检查可能空转了")

    if failed:
        print(f"迁移体系静态判据：{len(passed)} 通过 / {len(failed)} 失败")
        for f in failed:
            print("  " + f)
        return 1
    if check_mode:
        print(f"✅ 迁移体系 {len(passed)} 项全部通过（版本表 / 命名 / 记账顺序 / 漂移不拦启动 / 接线 / 表名单点）")
    else:
        for p in passed:
            print("  ✅ " + p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
