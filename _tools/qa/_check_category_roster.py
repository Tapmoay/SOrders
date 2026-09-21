"""红线：四个**分类名册**（开销 / 运费 / 商品 / 地点）拖动排序时共用的三条规则**只许一处**。

## 为什么要有这一条（2026-09-21 精简轮）
这三条规则原来在各自的 ViewModel 里各写一遍，而它**已经走散过**：

| 现场 | 后果 |
| --- | --- |
| 运费那一页的「撤销排序」是"只按 `savedOrder` 重建"的版本（开销/商品两页保留） | 保存之后**新建的分类会从列表里消失**（后端还在，用户以为被删了）——同一个按钮、三页两种行为，谁都没报错 |
| 三页提交的都是 `categories.map { it.id }`（只有开销页过滤 `id > 0`） | 开销名册的列表里混着"名册外的分类（老数据）"这种**界面造的合成行**（`id == 0`），带上就是后端整批拒绝（「顺序里有不存在的分类编号：[0]」） |
| 三页都用 `categories.map { it.id } != savedOrder` 算"改过没有" | 名册外的合成行一直都在列表最后、后端也从不返回它 → **保存成功之后"未保存"标记仍然亮着** |

三条规则现在只有一处实现：`ui/common/CategoryRoster.kt`（[submittableIds] / [revertedOrder] / [orderChanged]）。

## 判据（清单**自己算**：调 `repo.reorder*Categories(` 的 UI 文件就是名册页）
1. 每个名册页都必须用共用规则，**不许自己再写一遍**（三条各自的原始写法一律不许出现）；
2. 那个共用文件里三件必须都在（否则"名册页没自己写"只是因为**没人写**）；
3. 反空转：名册页 ≥4、带 `savedOrder`（草稿态）的 ≥3（地点那一页是"拖动即提交"，没有草稿态）。

用法：python _tools/qa/_check_category_roster.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui"
ROSTER = UI / "common" / "CategoryRoster.kt"

#: 「自己又写一遍」的三种原始写法（判据刻意用**当时的原文**，抄回去立刻红）
REWRITES = {
    "又自己拼了一份提交编号（没走 submittableIds）": r"categories\.map \{ it\.id \}\s*$",
    "撤销又写成「只按 savedOrder 重建」（会丢掉保存后新建的分类）": r"savedOrder\.mapNotNull \{ byId\[it\] \}\s*$",
    "又自己算了一遍「改过没有」（合成行会让它一直是 true）": r"dirty = categories\.map \{ it\.id \} != savedOrder",
}


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def main() -> int:
    fails: list[str] = []
    if not ROSTER.exists():
        print(f"❌ 找不到共用的规则文件：{ROSTER.relative_to(ROOT)}（被删/改名了？）")
        return 1

    # 名册页 = 真的在调 `/reorder` 的那个 UI 文件（四个名册 = 四个文件，清单自己算）
    rosters = sorted(
        (p for p in UI.rglob("*.kt") if re.search(r"repo\.reorder\w+Categories\(", read(p))),
        key=lambda p: p.name,
    )
    print(f"名册页（自己算）：{[p.name for p in rosters]}")
    if len(rosters) < 4:
        fails.append(f"只扫到 {len(rosters)} 个名册页（<4）—— 判据在空转")

    with_saved = [p for p in rosters if "savedOrder" in read(p)]
    print(f"带草稿态（savedOrder）的名册页：{[p.name for p in with_saved]}（地点那页是「拖动即提交」）")
    if len(with_saved) < 3:
        fails.append(f"带草稿态的名册页只有 {len(with_saved)} 个（<3）—— 判据在空转")

    for p in rosters:
        src = read(p)
        if "submittableIds(" not in src:
            fails.append(f"{p.name}：提交顺序没走 submittableIds（名册外的合成行会被一起发过去）")
        if p in with_saved:
            for fn, why in (("orderChanged(", "「改过没有」"), ("revertedOrder(", "「撤销排序」")):
                if fn not in src:
                    fails.append(f"{p.name}：{why}没走共用规则（{fn[:-1]}）")
        for label, pat in REWRITES.items():
            if re.search(pat, src, re.M):
                fails.append(f"{p.name}：{label}")

    shared = read(ROSTER)
    for fn in ("fun <T> submittableIds(", "fun <T> orderChanged(", "fun <T> revertedOrder("):
        if fn not in shared:
            fails.append(f"共用规则文件里少了 `{fn}` —— 名册页「没自己写」只是因为没人写")

    if fails:
        print("\n❌ 「分类名册的三条规则只有一处」被破坏：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ 全部通过：{len(rosters)} 个名册页都在用 {ROSTER.name} 里那三条规则（没有自己再写一遍）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
