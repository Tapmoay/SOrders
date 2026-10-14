# -*- coding: utf-8 -*-
"""选人弹层的「左分类 + 右列表 + 可搜」（CHG-0128）—— 注入式反向验证。

## 这一份是干什么的
`_check_contact_picker_categories.py` 的每一条 ok() 都必须**绑在源码字面量上**：
把源码改坏 → 判据必须红；改回 → 必须绿（否则那条判据就是空转的，写了等于没写）。
这一份把「改坏」做成 7 种**真会有人这么改**的破坏方式：

1. 把联系人弹层的左分类栏换成一排胶囊（看着「有分类」，其实那一列没了）；
2. 货主弹层的右列表不吃分类筛（点哪一格都是所有人，屏幕上看不出错）；
3. PersonGroups.kt 不再转发商品那一份算法，自己手写一遍分组（一开始一模一样，改一处就分叉）；
4. 筛选时把「未分类」的人顺手排掉（不报错，只是"人少了一批"）；
5. 货主弹层串上地址那边的颜色（一色一功能）；
6. 单测里「与商品那边同一份实现」那条护栏被删（久了就没人记得是同一份）；
7. 切分类顺手把搜索词清了（用户输了半截手机号，一点分类就白输了）。

## 规矩
- `INJECTIONS` 的顺序是 **(说明, 文件, 原文, 替换成, 期望被判据抓住的标签)**；
  ⛔ 前两格别写反（写反 = 「原文=空串命中几千次」，整份脚本空转）。
- 每条：备份字节 → 只替换一次 → 跑判据 → 断言**必须红**（退出码非 0，
  且那一条标签真的打印了 `  [!!]   <标签>`）→ **逐字节还原** → sha256 自证与改前一致。
- 锚点预检（`anchor_preflight`）：原文在任何目标文件里不是**恰好 1 次**，
  就**一个字节都不改**并非零退出（不许"改一半"）。
- 跑法：python -X utf8 _tools/qa/_reverse_verify_contact_picker_categories.py
  先看清单：python -X utf8 _tools/qa/_reverse_verify_contact_picker_categories.py --list
  尾部打印「N/N 种破坏方式都被判据抓住了」，EXIT=0。
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, refuse_if_injecting, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_contact_picker_categories.py"

AND = "android/app/src/main/java/com/tapmoay/sorders"
CONTACT = AND + "/ui/common/ContactPickerSheet.kt"
SHIPPER = AND + "/ui/common/ShipperPickerSheet.kt"
GROUPS = AND + "/ui/common/PersonGroups.kt"
TEST = "android/app/src/test/java/com/tapmoay/sorders/ui/common/PersonGroupsTest.kt"

#: (说明, 文件, 原文, 替换成, 期望被判据抓住的标签)
INJECTIONS: list[tuple[str, str, str, str, str]] = [
    ("把联系人弹层的左分类栏换成一排胶囊（那一列没了，看着却像有分类）", CONTACT, "MasterRail(", "CategoryTriggerChip(", "联系人弹层：有左分类栏 MasterRail("),
    ("货主弹层的右列表不吃分类筛（点哪一格都是所有人）", SHIPPER, "val visible = remember(shown, group) { inGroup(shown, group) { it.category } }", "val visible = remember(shown, group) { shown }", "货主弹层：右栏由 inGroup( 筛（⇒ 选中「全部」时一条都不少）"),
    ("PersonGroups.kt 不再转发商品那一份算法，自己手写一遍分组", GROUPS, "categoryTabsOf(items.map(categoryOf))", "items.map { categoryNameOf(categoryOf(it)) }.distinct().let { names -> listOf(ALL_CATEGORY) + names.filter { it != NO_CATEGORY } }", "PersonGroups.kt 的分组是**转发**给商品那一份（categoryTabsOf(items.map(categoryOf))）"),
    ("筛选时把「未分类」的人顺手排掉（不报错，只是人少了一批）", GROUPS, "if (group == ALL_CATEGORY) items else items.filter { categoryNameOf(categoryOf(it)) == group }", "if (group == ALL_CATEGORY) items else items.filter { categoryNameOf(categoryOf(it)) == group && categoryNameOf(categoryOf(it)) != NO_CATEGORY }", "PersonGroups.kt 的筛选按 categoryNameOf(categoryOf(it)) == group（「未分类」也是按这一条比）"),
    ("货主弹层串上地址那边的颜色（一色一功能被破）", SHIPPER, "accent = Color(InventoryTeal)", "accent = Color(ShipperTeal)", "两份弹层不串色（联系人弹层里没有 InventoryTeal，货主弹层里没有 ShipperTeal）"),
    ("单测里「与商品那边同一份实现」那条护栏被删", TEST, "categoryTabsOf(rows.map { it.category }),", "rows.map { it.category },", "PersonGroupsTest.kt 测的是与商品那边同一份实现（含 categoryTabsOf(）"),
    ("切分类顺手把搜索词清了（用户输了半截手机号，一点分类就白输了）", CONTACT, "onSelect = { group = it },", 'onSelect = { group = it; keyword = "" },', "联系人弹层：切分类**不清空**搜索词（onSelect = { group = it }，不是顺手把 keyword 也清了）"),
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_check() -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def anchor_preflight() -> int:
    """原文不唯一就一个字节都不改（改一半比不改更糟：工作区会留下半截注入）。"""
    bad: list[str] = []
    for n, (why, rel, old, _new, _want) in enumerate(INJECTIONS, 1):
        path = ROOT / rel
        if not path.is_file():
            bad.append(f"{n:>2}. 目标文件不在：{rel}")
            continue
        with path.open(encoding="utf-8", errors="replace", newline="") as fh:
            text = fh.read().replace("\r\n", "\n")
        hits = text.count(old)
        if hits != 1:
            bad.append(f"{n:>2}. 锚点出现 {hits} 次（要求恰好 1 次）：{rel} :: {old[:80]}")
    if bad:
        print("🛑 锚点预检不通过（一个字节都没改）：")
        for b in bad:
            print("   - " + b)
        return 2
    print(f"✅ 锚点预检通过：{len(INJECTIONS)} 条锚点在各自文件里都恰好出现 1 次")
    return 0


def caught_by(out: str, want: str) -> bool:
    return ("  [!!]   " + want) in out or ("  [!!]   ⛔ " + want) in out


_PENDING: dict[Path, bytes] = {}


def restore_pending() -> None:
    for path, raw in list(_PENDING.items()):
        path.write_bytes(raw)
        _PENDING.pop(path, None)


def main() -> int:
    if "--list" in sys.argv:
        print(f"破坏方式清单（{len(INJECTIONS)} 条）：")
        for n, (why, rel, old, new, want) in enumerate(INJECTIONS, 1):
            print(f"{n:>2}. {why}")
            print(f"    文件：{rel}")
            print(f"    改：{old[:100]}")
            print(f"    成：{new[:100]}")
            print(f"    期望被抓：{want}")
        return 0

    if refuse_if_injecting("选人弹层左分类反验"):
        return 1

    print(f"0. 干净状态先跑一次判据（{CHECK.name}，必须全绿）……")
    rc0, out0 = run_check()
    if rc0 != 0:
        print("🛑 干净状态下判据就不是绿的 —— 注入反验没有意义（先把它修绿）：")
        for line in out0.splitlines()[-12:]:
            print("   " + line)
        return 2
    print("   ✅ 干净状态全绿")

    rc = anchor_preflight()
    if rc != 0:
        return rc

    lock_reverse_verify()
    caught = 0
    total = len(INJECTIONS)
    try:
        for n, (why, rel, old, new, want) in enumerate(INJECTIONS, 1):
            path = ROOT / rel
            orig = path.read_bytes()
            _PENDING[path] = orig
            before = sha(path)
            text = orig.decode("utf-8")
            eol = "\r\n" if "\r\n" in text else "\n"
            o = old.replace("\n", eol)
            nn = new.replace("\n", eol)
            text2, hits = re.subn(re.escape(o), lambda _m: nn, text, count=1)
            if hits != 1:
                print(f"❌ [{n}/{total}] {why}：替换没命中（{hits} 次）")
                _PENDING.pop(path, None)
                continue
            path.write_bytes(text2.encode("utf-8"))
            try:
                rc2, out2 = run_check()
            finally:
                path.write_bytes(orig)
                _PENDING.pop(path, None)
            same = sha(path) == before
            got = caught_by(out2, want)
            good = got and rc2 != 0 and same
            print(f"{'✅' if good else '❌'} [{n}/{total}] {why}")
            print(f"      判据退出码 {rc2}（要非 0）／期望标签出现 {got}／逐字节还原 {same}")
            if good:
                caught += 1
            else:
                print(f"      期望标签：{want}")
                print("      判据输出尾部：")
                for line in out2.splitlines()[-8:]:
                    print("        " + line)
    finally:
        restore_pending()
        unlock_reverse_verify()

    print("\n" + "=" * 60)
    if caught == total:
        print(f"✅ {caught}/{total} 种破坏方式都被判据抓住了（判据不是空转的）")
        return 0
    print(f"❌ 只有 {caught}/{total} 种被抓住 —— 判据在那些地方是空转的")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
