"""反向验证「AI 声明式 CRUD 的声明与实现不许走散」这条红线**真的会红**（2026-09-19 审计）。

四类破坏：
| 注入 | 证明的是 |
|---|---|
| 把 `updateDriverRule` 里的 `pieceUnit = fields.str("piece_unit")` 删掉（**本轮真抓到的那条高**） | 判据真的在比对 pick 键与实现 |
| 把 `updateVehicle` 的 `active` 搬法删掉 | 判据不是只盯着计费规则那一处 |
| 客户建档又把 `member` 开关加回来 | 定点判据（不许写没人读的列）真的在 |
| 分类位置改回"只写绝对值" | 定点判据（必须走 reorder）真的在 |

用法：python _tools/qa/_reverse_verify_ai_declarative_crud.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_ai_declarative_crud.py"
BASE = "android/app/src/main/java/com/tapmoay/sorders/ai/"
SVC = BASE + "AiWriteService.kt"
BASIC = BASE + "AiWriteBasicData.kt"

CASES: list[tuple[str, str, object]] = [
    # ⚠️ 注入为什么打**键集合**而不是打实现里的某一行：
    #    `pieceUnit = fields.str("piece_unit"),` 这一行在 `createDriverRule` 与 `updateDriverRule`
    #    里**各有一份**（文本完全相同），`replace(..., 1)` 会打到前面那份 ——
    #    而创建类动作不走 `pick`，判据本来就不看它 → 注入"没生效"却报成"判据没牙"（实测踩到）。
    #    往键集合里加一个实现里没有的键，既能唯一命中，又正好是这条判据要防的形状
    #    （声明里有、实现里没有 = 模型说了、卡片写了、请求里没有）。
    (
        "给 DRIVER_RULE_KEYS 加一个实现里没有的键（声明与实现走散）",
        BASIC,
        lambda s: s.replace(
            '"commission_products", "remark",',
            '"commission_products", "remark", "piece_note",',
            1,
        ),
    ),
    (
        "给 VEHICLE_KEYS 加一个实现里没有的键（换一处集合，证明判据不是写死某一份）",
        BASIC,
        lambda s: s.replace(
            'private val VEHICLE_KEYS = setOf("plate_no", "vehicle_type", "active")',
            'private val VEHICLE_KEYS = setOf("plate_no", "vehicle_type", "active", "probe_key")',
            1,
        ),
    ),
    (
        "改车辆又不搬 active",
        SVC,
        lambda s: s.replace('                isActive = fields.str("active")?.toBooleanStrictOrNull(),\n', "", 1),
    ),
    (
        "客户建档又把「是不是批发商」开关加回来",
        BASIC,
        lambda s: s.replace(
            '                textField("phone", "电话", "可选；同号会被沿用，见卡片说明", maxChars = 20),',
            '                textField("phone", "电话", "可选；同号会被沿用，见卡片说明", maxChars = 20),\n'
            '                boolField("member", "是不是批发商", "true=批发商（高级货主）"),',
            1,
        ),
    ),
    (
        "分类位置改回「只写绝对值」",
        SVC,
        lambda s: s.replace(
            '        fields.str("sort_order")?.toIntOrNull()?.let { moveCategoryTo(created.id, it) }',
            "        // 注入：只写绝对值",
            1,
        ),
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


def run_check() -> int:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return r.returncode


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
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            write_src(path, mutated, crlfs[rel])
            red = run_check() != 0
        finally:
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
