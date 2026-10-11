"""_reverse_verify_category_rosters_split.py —— FEAT-0026 的反向验证（破坏性注入）。

## 为什么必须有它

_tools/qa/_check_category_rosters_split.py 是**静态**判据：它只读源码与文档。
静态判据最大的风险是「看着在管、其实永远绿」（本仓库栽过：断言写成了永远成立的形式）。
所以每一条重要断言都要拿一次**真的破坏**去撞它：把源码改坏一处、跑判据、
必须看到对应的那一行变红，然后按字节还原。

## 手法

每条 = (说明, 相对路径, 锚点原文, 替换成, 期望标签)。锚点必须**唯一**（re.subn(count=1)），
re: 前缀 = 正则锚点，~ 前缀的期望 = 判据输出里**任意**一条 [!!] 行包含这个子串即可。
跑的时候**不许**并发跑别的判据（注入是临时写进源码的），也**不许**并发跑 gradle。

覆盖的破坏方式（用户点名的六类都在里面）：
两册改回同一张表、把「拉取」改成写进账号名册一级（parent_id 丢掉）、拉取行变成可改、
去掉软删、去掉恢复、账号名册改成可自由加、去掉迁移（映射表改错 + 搬完不撤旧行）、
客户端把只读行又画成可改的。

配套：python _tools/qa/_check_category_rosters_split.py（**12** 种破坏方式全被抓）

用法：

    python _tools/qa/_reverse_verify_category_rosters_split.py --list
    python _tools/qa/_reverse_verify_category_rosters_split.py

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
CHECK = ROOT / "_tools" / "qa" / "_check_category_rosters_split.py"

BE = "backend/app/"
A = "android/app/src/main/java/com/tapmoay/sorders/"

MMODEL = BE + "models/module_category.py"
MSVC = BE + "services/module_category.py"
MAPI = BE + "api/v1/module_categories.py"
UAPI = BE + "api/v1/user_categories.py"
MIG35 = BE + "migrations/035_module_categories.py"
MTESTS = "backend/tests/test_module_categories_split.py"
ROSTER_VM = A + "ui/dispatcher/CategoryRostersViewModel.kt"
PANEL = A + "ui/dispatcher/CategoryRostersPanel.kt"
USERS_VM = A + "ui/dispatcher/UsersManageViewModel.kt"

INJECTIONS: list[tuple[str, str, str, str, str]] = [
    (
        "两册改回同一张表（模块名册又写进 user_categories）",
        MMODEL,
        '__tablename__ = "module_categories"',
        '__tablename__ = "user_categories"',
        "模块名册有自己的表 module_categories",
    ),
    (
        "拉取时把归属丢掉（模块分类会被拉成账号册的一级 = 又串在一起）",
        MSVC,
        "                        parent_id=top.id,",
        "                        parent_id=None,",
        "⛔ 拉取行永远带 parent_id（子分类不会被拉成一级）",
    ),
    (
        "拉取行的编号不再是负数（跟库里那些行的编号撞在一起）",
        MSVC,
        "    return row_id < 0",
        "    return False",
        "拉取行的编号是负数（不跟库里的行撞号）",
    ),
    (
        "模块名册的删除改回硬删（删错了没法恢复）",
        MAPI,
        "    row.is_deleted = True\n    row.deleted_at = utc_now_naive()",
        "    db.delete(row)",
        "删除写 is_deleted + deleted_at（不是 db.delete）",
    ),
    (
        "恢复端点不再摘掉软删标记（按了撤销也回不来）",
        MAPI,
        "    gone.is_deleted = False",
        "    gone.is_deleted = True",
        "恢复把软删标记摘掉（is_deleted=False + deleted_at=None）",
    ),
    (
        "账号名册改成可自由加（一级固定六类这条规矩没了）",
        UAPI,
        'detail="账号分类的一级是固定的六类（派单员 / 货主 / 批发商 / 小车司机 / 大车司机 / "',
        'detail="随便建"',
        "账号册不能新建一级（400 说清：一级是固定的六类）",
    ),
    (
        "账号册又能给模块的一级挂子类（模块名册之外又出现第二份）",
        UAPI,
        're:\\s*"请到那一页的「管理分类」里新建（这里只读、自动拉取）。",',
        '                    "",',
        "账号册不能给模块的一级挂子类（那一份归模块名册管）",
    ),
    (
        "迁移的映射表改错一格（批发商的分类会搬进货主名册）",
        MIG35,
        '    "批发商": "members",',
        '    "批发商": "shippers",',
        "搬的是五个模块一级下面的二级（派单员不搬 —— 它没有模块页）",
    ),
    (
        "迁移搬完不撤旧行（账号册里同一格出现两次）",
        MIG35,
        "                conn.execute(src.delete().where(src.c.id == kid_id))",
        "                pass",
        "插新行 + 撤旧行在同一个事务里（搬不是删）",
    ),
    (
        "客户端把拉取行又画成可改（按下去后端 400，界面骗人）",
        ROSTER_VM,
        "        readOnly = pulled || top || d.module != null,",
        "        readOnly = false,",
        "只读行写一句「为什么不能在这儿改、要去哪儿改」",
    ),
    (
        "名册面板不再滤掉只读行（固定六类又变回能当父）",
        PANEL,
        "    val picks = parentChoices.filterNot { it.readOnly }",
        "    val picks = parentChoices",
        "只读行不画四颗动作（画了再报 400 是骗人的）",
    ),
    (
        "三池页又读回账号册（批发商管理看到的还是账号那份名册）",
        USERS_VM,
        "            val names = container.repo.moduleCategories(pool.key).map { it.name }",
        "            val names = container.repo.userCategories().map { it.name }",
        "三池页各读自己那一份名册（键就是 pool.key）",
    ),
    (
        "用户点名的那条单测被删掉（子分类不会被拉成一级 没人管了）",
        MTESTS,
        "def test_子分类不会被拉成一级(",
        "def test_x_子分类不会被拉成一级(",
        "用例在：test_子分类不会被拉成一级",
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
