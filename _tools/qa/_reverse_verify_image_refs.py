"""反向验证：`_check_image_refs.py`（图片引用清单 + 删文件的两条路）到底管不管事。

## 为什么要这一份
`_check_image_refs.py` 是一条"删文件"的红线 —— 它绿着的时候，用户看不见任何东西；
它空转的时候，也**一样看不见**（图片是到期才被删的，等发现时原图已经 unlink，不可恢复）。
这个仓库对这类"永远绿也永远没人知道"的判据定过规矩：**新增红线就要有注入实验**。
本脚本把这条红线新加的三条判据逐个注入坏掉，证明它们真的会红：

1. `purge_orphan_images` 不再扫 `delivery/` → 磁盘只增不减（孤儿文件谁都不删）；
2. 送达凭证的保护清单 `DELIVERY_PHOTO_COLUMNS` 被删掉 → "按引用清 delivery"变成删掉刚送完的照片；
3. `delete_orders_by_ids` 不再问保护集 → 按 id 整目录删，把共享地点库还在用的地址图删掉（不可恢复）；
4. 通用清单里的一行被删掉（`Place.image_urls`）→ "模型里有 url 列却没人保护"必须报红。

用法：`python _tools/qa/_reverse_verify_image_refs.py`
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
CHECK = ROOT / "_tools" / "qa" / "_check_image_refs.py"
ARCHIVE = ROOT / "backend/app/services/image_archive.py"
RETENTION = ROOT / "backend/app/services/data_retention.py"

#: (说明, 目标文件, 替换函数)
CASES: list[tuple[str, Path, object]] = [
    (
        "purge_orphan_images 不再扫 delivery（只写盘不建引用的文件谁都不删）",
        ARCHIVE,
        lambda s: s.replace('for sub in ("locations", "products", "delivery"):',
                            'for sub in ("locations", "products"):', 1),
    ),
    (
        "送达凭证的保护清单被删掉（按引用清 delivery → 删掉刚送完的单的照片）",
        ARCHIVE,
        lambda s: s.replace('DELIVERY_PHOTO_COLUMNS: tuple[tuple[type, str], ...] = ((Order, "delivery_photo_urls"),)',
                            'DELIVERY_PHOTO_COLUMNS: tuple[tuple[type, str], ...] = ()', 1),
    ),
    (
        "订单物理清理不再问保护集（按 id 整目录删 → 删掉共享地点库还在用的图）",
        RETENTION,
        lambda s: s.replace("    keep = protected_image_urls(db)", "    keep = set()", 1),
    ),
    (
        "通用清单里少一行（Place.image_urls）→ 模型里有 url 列却没人保护",
        ARCHIVE,
        lambda s: s.replace('    (Place, "image_urls", True),\n', "", 1),
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    code, out = run_check()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时这条红线就没过\n{out[-1500:]}")
        return 1
    print("✅ 前提：源码完好时图片引用红线是绿的")

    fails: list[str] = []
    for label, path, mutate in CASES:
        original_bytes = path.read_bytes()
        original = original_bytes.decode("utf-8").replace(chr(13) + chr(10), chr(10))
        mutated = mutate(original)
        if mutated == original:
            fails.append(f"{label}：注入没生效（替换串过期了，请更新本脚本）")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            code2, out2 = run_check()
            red = code2 != 0
        finally:
            path.write_bytes(original_bytes)
        # R3-07b：还原**当场核对**（不是「看起来还原了」）—— 对不上就记账，别让坏代码留在树里
        if path.read_bytes() != original_bytes:
            fails.append(f"{label}：还原后与快照不一致 —— 注入污染了源码树")
            continue
        if red:
            print(f"✅ 注入「{label}」→ 报红")
        else:
            fails.append(f"{label}：注入之后没有报红 —— 这条判据是空转的")

    if fails:
        print("\n❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ 图片引用红线共 {len(CASES)} 条注入全部证明会红。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
