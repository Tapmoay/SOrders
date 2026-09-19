"""把仓库根目录的临时产物收进 `_archive/`（**不是删掉**）。

为什么要有这个脚本：用户的原话是「根目录堆了几百个 `_*.png` / `_*.py`」，
而且他对清理的唯一要求是「**不要删了就搞不回来了**」。所以清理 = 打包归档，
归档包留在 `_archive/root-scratch-<日期>.zip` 里，需要时还能翻出来。

它会**自己算**哪些该收（glob 根目录的 `_*` 普通文件），不维护一份手写清单——
按 v3.20 §三.1 的教训，手写清单过期时会安静地什么都不做。
白名单只有两类，都写在 [KEEP] 里并各自有理由。

用法：
    python _tools/ai/_archive_root_scratch.py --list     # 只看要收哪些（不改任何东西）
    python _tools/ai/_archive_root_scratch.py            # 真的收进 _archive/
"""
import argparse
import sys
import zipfile
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "_archive"

# 白名单：[文件名] = 为什么留着（不是"懒得收"）
KEEP: dict[str, str] = {
    # 文档正文引用了这个产物（《AI_ASSISTANT_PLAN_V3》开头那段对账说明），
    # 收走会让文档里的那句话没有对应物。
    "_verify_ast.json": "文档正文引用它",
}


def scratch_files() -> list[Path]:
    """根目录下所有 `_*` 普通文件（目录一律不动——`_tools`/`_agent` 是真的在用的）。"""
    return sorted(
        (p for p in ROOT.glob("_*") if p.is_file() and p.name not in KEEP),
        key=lambda p: p.name,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="只列出来，不改动任何东西")
    args = ap.parse_args()

    files = scratch_files()
    if not files:
        print("✅ 根目录没有临时产物（已经干净）")
        return 0

    total = sum(p.stat().st_size for p in files)
    print(f"根目录临时产物 {len(files)} 个，共 {total / 1024 / 1024:.1f} MB：")
    for p in files:
        print(f"  {p.name}  ({p.stat().st_size / 1024:.0f} KB)")

    if args.list:
        print("\n（--list：没有改动任何东西）")
        return 0

    ARCHIVE.mkdir(exist_ok=True)
    zip_path = ARCHIVE / f"root-scratch-{datetime.now():%Y%m%d-%H%M%S}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, p.name)
    # 先写进 zip、**核对过条目数**再删原件：宁可留着，也不要在归档失败时丢东西。
    with zipfile.ZipFile(zip_path) as z:
        bad = z.testzip()
        n = len(z.namelist())
    if bad is not None or n != len(files):
        zip_path.unlink(missing_ok=True)
        print(f"❌ 归档没写完整（条目 {n}/{len(files)}，坏条目 {bad}），原件一个都没动")
        return 1
    for p in files:
        p.unlink()
    print(f"\n✅ 已收进 {zip_path.relative_to(ROOT)}（{n} 个条目），根目录原件已移走")
    print("   要翻回来：解压该 zip 到仓库根目录即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
