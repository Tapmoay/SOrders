"""_reverse_verify_account_category_two_level.py —— CHG-0112 的反向验证（破坏性注入）。

## 为什么必须有它

`_tools/qa/_check_account_category_two_level.py` 是**静态**判据：它只读源码与文档。
静态判据最大的风险是「看着在管、其实永远绿」（本仓库栽过：断言写成了永远成立的形式）。
所以每一条重要断言都要拿一次**真的破坏**去撞它：把源码改坏一处、跑判据、
必须看到对应的那一行变红，然后按字节还原。

## 手法

每条 = (说明, 相对路径, 锚点原文, 替换成, 期望标签)。锚点必须**唯一**（`re.subn(count=1)`），
`re:` 前缀 = 正则锚点，`~` 前缀的期望 = 判据输出里**任意**一条 `[!!]` 行包含这个子串即可。
跑的时候**不许**并发跑别的判据（注入是临时写进源码的）。

配套：python _tools/qa/_check_account_category_two_level.py（**16** 种破坏方式全被抓）

用法：

    python _tools/qa/_reverse_verify_account_category_two_level.py --list
    python _tools/qa/_reverse_verify_account_category_two_level.py

R4-BOUNDARY-JUSTIFICATION: 本脚本只读写工作区文件（临时注入后按字节还原），不连库、不起服务、
不调外部接口；它验证的对象是本事项自己的判据，属于测试工具（Infrastructure），不碰业务核心。
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_account_category_two_level.py"

BE = "backend/app/"
A = "android/app/src/main/java/com/tapmoay/sorders/"

MIG30 = BE + "migrations/030_user_category_parent.py"
BOOT = BE + "core/schema_bootstrap.py"
UAPI = BE + "api/v1/user_categories.py"
REPO = A + "data/repo/AppRepository.kt"
TREE = A + "ui/dispatcher/AccountCategoryTree.kt"
ACC_VM = A + "ui/dispatcher/AccountManageViewModel.kt"
ACC = A + "ui/dispatcher/AccountManageScreen.kt"
DRAWER = A + "ui/common/CategoryDrawer.kt"
PANEL = A + "ui/dispatcher/CategoryRostersPanel.kt"
KTEST = "android/app/src/test/java/com/tapmoay/sorders/ui/dispatcher/AccountCategoryTreeTest.kt"

INJECTIONS: list[tuple[str, str, str, str, str]] = [
    (
        "迁移 030 的索引名与模型 index=True 的默认名不一致（两处会建出两张索引）",
        MIG30,
        'INDEX_NAME = "ix_user_categories_parent_id"',
        'INDEX_NAME = "ix_user_categories_parent"',
        "迁移 030 的索引名与模型 index=True 的默认名一致",
    ),
    (
        "迁移 030 加列不再分开判（老库改了一半就失败时没法重跑）",
        MIG30,
        "if COLUMN not in have:",
        "if True:",
        "迁移 030 能重跑（加列分开判）",
    ),
    (
        "播种不再判「名册整个为空」（会复活用户删掉的单个分类 / 每次启动都插一遍）",
        BOOT,
        "    if existing:\n        return 0",
        "    if False:\n        return 0",
        "只有在名册整个为空时才播种",
    ),
    (
        "六个默认分类的顺序被写反（用户点名的顺序）",
        BOOT,
        '    "小车司机",\n    "大车司机",',
        '    "大车司机",\n    "小车司机",',
        "默认六类的名字与顺序",
    ),
    (
        "回收站里的账号也被算进「在用」（2026-10-10 那次的教训之一）",
        BOOT,
        "            if has_del_suffix(uid, phone, username):\n                continue",
        "            if False:\n                continue",
        "回收站里的账号不算在用",
    ),
    (
        "父不存在时不再拒（会建出一个挂在不存在的父下面的子类）",
        UAPI,
        '    if parent is None:\n        raise HTTPException(status_code=400, detail="上层分类不存在（可能刚被删掉了），换一个再试")',
        "    if parent is None:\n        return None",
        "父必须存在（父不存在 → 400 说清）",
    ),
    (
        "「只两级」的校验被拿掉（第三层会进库，界面只画两层 ⇒ 那一层永远看不见）",
        UAPI,
        "    if parent.parent_id is not None:",
        "    if False:",
        "子类的子类被拒（只两级）",
    ),
    (
        "删大类时不再查它下面的子类（子类会变成没有父的孤儿）",
        UAPI,
        "        .where(UserCategory.parent_id == row.id)",
        "        .where(UserCategory.parent_id == -1)",
        "大类下面还有子类时不许删",
    ),
    (
        "改名不再级联到挂着的账号（改完账号全变未分类，而且不报错）",
        UAPI,
        "            User.__table__.update().where(User.category == old_name).values(category=body.name)",
        '            User.__table__.update().where(User.category == "x").values(category=body.name)',
        "改名级联一个字没动",
    ),
    (
        "父不在名册里的子类不再降级（那一行会从左栏消失 ⇒ 它的账号点不到）",
        TREE,
        "    return if (parent.parentId == null) parent else null",
        "    return parent",
        "父不在 / 父自己是子类时降级成大类",
    ),
    (
        "账户管理的筛选不再带上覆盖集合（点大类只筛大类自己）",
        ACC_VM,
        "        inRail(shown, railKey, { it.category }, railCovers).filter { matchesStatus(it, statusTab) }",
        "        inRail(shown, railKey, { it.category }).filter { matchesStatus(it, statusTab) }",
        "筛选带上覆盖集合",
    ),
    (
        "账户页的抽屉又变回平铺（两级白做了）",
        ACC,
        "                    items = listOf(CategoryDrawerItem(\"\", \"全部\")) + vm.railRows.map {",
        "                    items = listOf(CategoryDrawerItem(\"\", \"全部\")) + catVm.rows.map {",
        "抽屉那几格用 railRows 画",
    ),
    (
        "子类不再缩进（两级看不出层级）",
        DRAWER,
        "            if (depth > 0) Spacer(Modifier.width((18 * depth).dp))",
        "            if (depth < 0) Spacer(Modifier.width((18 * depth).dp))",
        "抽屉零件支持缩进",
    ),
    (
        "名册面板不再画「上层分类」（子类没法从界面上建出来）",
        PANEL,
        "        parentChoices = vm.rows.filter { it.parentId == null },",
        "        parentChoices = emptyList(),",
        "名册面板：只有账号这份名册画「上层分类」",
    ),
    (
        "AppRepository 建分类时把 parentId 丢掉（界面选了归属也建不成子类）",
        REPO,
        "    suspend fun createUserCategory(name: String, sortOrder: Int? = null, parentId: Long? = null) =",
        "    suspend fun createUserCategory(name: String, sortOrder: Int? = null) =",
        "AppRepository.createUserCategory 带上 parentId",
    ),
    (
        "Kotlin 单测不再钉「点大类覆盖子类」（把那一条断言改成只覆盖自己）",
        KTEST,
        '        assertEquals(setOf("货主", "食堂", "超市"), railNamesUnder(roster, "c|货主"))',
        '        assertEquals(setOf("货主"), railNamesUnder(roster, "c|货主"))',
        "单测钉住「点大类筛出所有子类」",
    ),
]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="只列出破坏方式，不动文件")
    args = ap.parse_args()
    if args.list:
        for i, (name, rel, _old, _new, want) in enumerate(INJECTIONS, 1):
            print(f"{i:>2}. {name}")
            print(f"      {rel}   ← 期望被「{want}」抓到")
        return 0

    code, out = run_check()
    if code != 0:
        print("❌ 现在就是红的，先修好再跑反向验证：")
        print(out[-3000:])
        return 2

    caught = 0
    missed: list[str] = []
    for i, (name, rel, old, new, want) in enumerate(INJECTIONS, 1):
        path = ROOT / rel
        if not path.exists():
            print(f"{i:>2}. ⛔ 目标文件不存在：{rel}")
            missed.append(name)
            continue
        raw = path.read_bytes()
        orig_sha = sha(raw)
        text = raw.decode("utf-8")
        eol = "\r\n" if "\r\n" in text else "\n"
        old_s = old.replace("\n", eol)
        new_s = new.replace("\n", eol)
        pat = old_s[3:] if old_s.startswith("re:") else re.escape(old_s)
        injected, n = re.subn(pat, new_s, text, count=1)
        if n != 1:
            print(f"{i:>2}. ❌ 锚点没命中，跳过（注入点腐烂了）：{name}")
            missed.append(name)
            continue
        path.write_text(injected, encoding="utf-8", newline="")
        try:
            _code, out2 = run_check()
        finally:
            now = path.read_bytes()
            if sha(now) != sha(injected.encode("utf-8")):
                print(f"🛑 有别的东西改了 {rel}，拒绝还原（请人工检查）")
                return 2
            path.write_bytes(raw)
            if sha(path.read_bytes()) != orig_sha:
                print(f"🛑 {rel} 没还原干净")
                return 2
        if want.startswith("~"):
            hit = any("[!!]" in ln and want[1:] in ln for ln in out2.splitlines())
        else:
            hit = any("[!!]" in ln and want in ln for ln in out2.splitlines())
        if hit:
            caught += 1
            print(f"{i:>2}. ✅ {name}")
        else:
            missed.append(name)
            print(f"{i:>2}. ❌ 红线居然还是绿的：{name}  ← 期望「{want}」")

    print()
    print(f"{caught}/{len(INJECTIONS)} 种破坏方式被抓住")
    if missed:
        print("漏网的：")
        for name in missed:
            print(f"   - {name}")
        return 1
    print("✅ 全部注入都被抓住，且每个文件都按字节还原")
    return 0


if __name__ == "__main__":
    sys.exit(main())
