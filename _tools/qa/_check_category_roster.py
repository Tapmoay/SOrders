"""红线：三个「分类名册」页（开销 / 运费 / 商品）的**草稿排序状态机**只有一处，且**三条规则**只有一处。

## 为什么要有这一条（2026-09-21 精简轮，前后两轮）
名册页共用两样东西，两样都曾经被抄成多份：

| 抄的东西 | 原来 | 抄错/写歪的后果（都不报错） |
| --- | --- | --- |
| **三条纯规则**（只提交名册内的行 / `dirty` 判据 / 撤销保住新建项） | 各页各写一遍 | 运费页的「撤销」会把保存后新建的分类**丢掉**；三页存完「未保存」还亮着 |
| **状态机**（拉名册 → 草稿排序 → 提交整份 → 建/改名/删） | 每页约 45 行 | 商品页的建/改名/删之后是**就地重刷**（不清 `loadError`）、另两页走 `load()` —— 同一件事两种写法 |

现在：规则在 `ui/common/CategoryRoster.kt`，状态机在 `ui/common/CategoryRosterViewModel.kt`。
页面只剩「这一页是什么」（拉哪个接口、提交到哪个接口）。

## 判据（清单**自己算**）
1. 名册页 = 真的在调 `repo.reorder*Categories(` 的 UI 文件（现 4 个）；其中**草稿页** = 继承
   `CategoryRosterViewModel` 的那几个（现 3 个：地点是"拖动即提交"，没有草稿态）；
2. 草稿页**不许自己写那三条规则**（都由共用内核调），否则"共用"只是名义上的；
3. 共用内核里三条规则**必须都在**（少一条就是有人把它搬回某页或搬丢了）；
4. 没有草稿态的名册页（地点）仍然自己调 `submittableIds`（它不需要整套状态机）；
5. 原来的**内联写法**一律不许再出现（判据用当时的原文：抄回去立刻红）；
6. 反空转：名册页 ≥4、草稿页 ≥3、共用内核文件必须在。

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
VM_BASE = UI / "common" / "CategoryRosterViewModel.kt"

#: 三条规则（在共用内核里必须都有；在草稿页里必须都没有）
RULES = {
    "submittableIds(": "提交只带名册内的行（id > 0）",
    "orderChanged(": "「改过没有」的判据",
    "revertedOrder(": "撤销回到已保存顺序且保住新建项",
}

#: 「自己又写一遍」的原始写法（判据刻意用**当时的原文**，抄回去立刻红）
REWRITES = {
    "提交又自己拼编号（名册外的合成行会被一起发过去）": r"(val ids|categories)\s*=\s*categories\.map \{ it\.id \}\s*$",
    "撤销又写成「只按 savedOrder 重建」（会丢掉保存后新建的分类）": r"savedOrder\.mapNotNull \{ byId\[it\] \}\s*$",
    "又自己算了一遍「改过没有」（合成行会让它一直是 true）": r"dirty = categories\.map \{ it\.id \} != savedOrder",
}


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def main() -> int:
    fails: list[str] = []
    for f in (ROSTER, VM_BASE):
        if not f.exists():
            print(f"❌ 找不到共用的规则文件：{f.relative_to(ROOT)}（被删/改名了？）")
            return 1

    # 名册页 = 真的在调 `/reorder` 的那个 UI 文件（四个名册 = 四个文件，清单自己算）
    rosters = sorted(
        (p for p in UI.rglob("*.kt") if re.search(r"repo\.reorder\w+Categories\(", read(p))),
        key=lambda p: p.name,
    )
    print(f"名册页（自己算）：{[p.name for p in rosters]}")
    if len(rosters) < 4:
        fails.append(f"只扫到 {len(rosters)} 个名册页（<4）—— 判据在空转")

    # 草稿页 = 继承共用内核的那几个（也扫出来，不写死）
    drafts = [p for p in rosters if re.search(r":\s*CategoryRosterViewModel<", read(p))]
    print(f"带草稿态的名册页（继承共用内核）：{[p.name for p in drafts]}（地点那页是「拖动即提交」）")
    if len(drafts) < 3:
        fails.append(f"继承共用内核的名册页只有 {len(drafts)} 个（<3）—— 状态机没被共用（或判据在空转）")

    for p in rosters:
        src = read(p)
        if p in drafts:
            for rule, why in RULES.items():
                if rule in src:
                    fails.append(f"{p.name}：{why}又写在自己这里了（{rule[:-1]}）—— 该由共用内核调")
        elif "submittableIds(" not in src:
            fails.append(f"{p.name}：提交顺序没走 submittableIds（名册外的合成行会被一起发过去）")

    # 旧的内联写法：**整棵 ui/ 都不许再有**（只排除规则本体那个文件 —— 那正是它们的实现）
    for p in sorted(UI.rglob("*.kt"), key=lambda q: q.name):
        if p == ROSTER:
            continue
        src = read(p)
        for label, pat in REWRITES.items():
            if re.search(pat, src, re.M):
                fails.append(f"{p.name}：{label}")

    base = read(VM_BASE)
    for rule, why in RULES.items():
        if rule not in base:
            fails.append(f"{VM_BASE.name} 里少了「{why}」（{rule[:-1]}）—— 草稿页「没自己写」只是因为没人写")
    # 状态机必须真的是从"规格"推出来的那三条路，而不是各页各写各的
    for need, why in (
        ("protected abstract suspend fun fetchAll()", "拉名册的抽象口子"),
        ("protected abstract suspend fun reorder(ids: List<Long>)", "提交整份顺序的抽象口子"),
        ("private fun replaceAll(", "「列表 + 已保存顺序 + 草稿标记」一起写回的唯一出口"),
    ):
        if need not in base:
            fails.append(f"{VM_BASE.name} 少了{why}（{need}）")

    if fails:
        print("\n❌ 「分类名册的规则与状态机各只有一处」被破坏：")
        for f in fails:
            print("   - " + f)
        return 1
    print(
        f"\n✅ 全部通过：{len(drafts)} 个草稿名册页共用 {VM_BASE.name}（三条规则来自 {ROSTER.name}），"
        f"地点那页自己调 submittableIds。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
