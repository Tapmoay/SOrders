# -*- coding: utf-8 -*-
"""红线：工作台右边那颗胶囊上的字**按实际身份说** —— 货主 / 批发商（CHG-0033，2026-10-04）。

## 用户原话（2026-10-04 第 2 件，对着工作台头部那张截图）
> 「他那个右边的那个**货主**啊，他是**根据实际情况**来定的：如果**对面是货主**的话，
>  他就**货主**，如果**对面是批发商**的话，则就是**批发商**」

## 这条为什么必须有机器的判据
批发商在我们库里**不是第三种角色**：他就是 `role = "SHIPPER"` + `is_member = 1`
（2026-10-04 实测：SHIPPER 共 49 个，其中 **14** 个 `is_member = 1`；永盛食品 `13800000002` 是其中之一）。
所以「看角色画胶囊」这条老规矩**看起来完全正确** —— 那 14 个人（以及他们的货主端账本、核销能力）
一直被告知自己是「货主」。这一整套在类型系统眼里什么都不是：

* 颜色表里那一支被删掉 / 名字改回「货主」→ 编译过，那 14 个人继续看到错的字；
* `roleBadgeKey` 少了 `roleKey == "shipper"` 这道门 → **派单员/司机**被标成批发商时标签跟着变；
* `roleBadgeKey` 被抄成第二份（颜色表一份、工作台一份）→ 改一处漏一处，两处不一致看不出来；
* 工作台忘了把身份交给胶囊（写回 `RoleBadge(role.key)`）→ 一切照常，只是批发商又写「货主」；
* 问身份失败时按 `true` 兜底 → **全体货主被写成批发商**（这比漏掉更难发现：没人会来报"我不是批发商"）；
* 头部自己去问一次（第二个网络调用点）→ 一次请求失败，两种身份在同一个人手机上闪烁。

判据分六层：

0. **反空转**：色源那一支、映射函数、胶囊、工作台取身份那一段都在（截空即红）；
1. **色源**：四支角色/身份 + 兜底、`shipper_member` 那一支写着「批发商」、与货主**同族色**
   （同族是**决定**，不是巧合：他本来就是货主那一族，变的只是标签上那个字）；
2. **唯一那份映射**：全树只有一个 `roleBadgeKey`、那道 `shipper` 门在、只认 `memberShipper` 这一维；
3. **胶囊真的用它**：`RoleBadge` 第二维默认 `false`（fail-closed）、体内只有一次 `rolePaletteOf`；
4. **工作台**：`WelcomeBar` 收下身份、调用点把身份交出去、头部自己不取数、`remember(role.key)`；
5. **接线**：单测在钉（两维 + 只对货主 + fail-closed）、规范 §4.13 写了这条、定位表指路、
   反向验证拿着注入锁、登记簿有 CHG-0033、装包脚本认角色**不靠**胶囊上的字。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界消除不了**。「这人是不是批发商」是**服务端**的事实
（`GET /users/me` 的 `is_member`），而且**必须**再经过一次判断才落到那行字上：`roleBadgeKey` 是个
普通的纯函数、返回 `String`；`RoleBadge` 的第二个参数有默认值 `false`。所以「忘了传」「传反了」
「少一道门」「抄第二份」这四种写法**全部编译通过**，界面也照常显示 —— 只有那 14 个批发商
（或者反过来，全体货主）看到的字是错的。类型系统管不了「这个字符串是从哪来的」，
只能靠一条判据把颜色表、纯函数、工作台与规范对起来，并在反向验证里把这四种写法各跑一遍。

用法：python _tools/qa/_check_workbench_member_badge.py
     python _tools/qa/_check_workbench_member_badge.py --list
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 复用兄弟红线里剥注释的实现，不抄第二份。
#: ⚠️ **必须剥注释**：上面那些「⛔ 别把批发商写进 STRONG_MARK」的话本身写在注释里，
#:    不剥的话下面那几条「代码里没有 …」会被自己的注释弄红（或被绕过）。
from _check_pagination_wiring import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
WORKBENCH = ANDROID / "ui/home/WorkbenchScreen.kt"
COMPONENTS = ANDROID / "ui/common/Components.kt"
BADGE_TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/common/RoleBadgeKeyTest.kt"
INSTALL = ROOT / "_tools/qa/_install_all.py"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
LOCATOR = ROOT / "docs/PROJECT_MAP/08_CODE_LOCATOR.md"
DOC = ROOT / "docs/changes/CHG-0033.md"
REGISTRY = ROOT / "docs/changes/README.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_workbench_member_badge.py"
JUDGE_NAME = "_tools/qa/_check_workbench_member_badge.py"

#: 批发商那一支的键与标签（与 rolePaletteOf / roleBadgeKey 里写死的一样）
MEMBER_KEY = "shipper_member"
MEMBER_LABEL = "批发商"
SHIPPER_LABEL = "货主"
#: 纯函数体下限（抽取失效比判据腐烂更危险）
BODY_FLOOR = 60
#: 单测条数与「真的在调纯函数」的下限
TEST_MIN = 5
MIN_TEST_CALLS = 3


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的断言要跟着改）")
    return p.read_text(encoding="utf-8")


def read_code(p: Path) -> str:
    return strip_comments(read(p))


def def_body(src: str, sig: str, limit: int = 2000) -> str:
    """从 [sig] 处取到**紧跟其后的下一个顶层定义**为止（取不到就按 [limit] 截）。"""
    i = src.find(sig)
    if i < 0:
        return ""
    end = i + limit
    for marker in ("\nfun ", "\ninternal fun ", "\nprivate fun ", "\n@Composable",
                   "\nclass ", "\ndata class ", "\nobject "):
        j = src.find(marker, i + len(sig))
        if i < j < end:
            end = j
    return src[i:end]


def kt_files(root: Path) -> list:
    return sorted(root.rglob("*.kt"))


class Checker:
    def __init__(self) -> None:
        self.fails: list = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print(f"  [OK]   {label}")
        else:
            self.fails.append(label + (f" —— {detail}" if detail else ""))
            print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))

    def present(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is not None, f"没找到 {pattern!r}")

    def absent(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is None, f"命中：{m.group(0)[:60]!r}" if m else "")

    def report(self, what: str) -> int:
        if self.fails:
            print(f"\n❌ {what}：通过 {self.passes} 项，失败 {len(self.fails)} 项")
            for f in self.fails:
                print("   - " + f)
            return 1
        print(f"\n✅ {what}：通过 {self.passes} 项，失败 0 项")
        return 0

def main() -> int:
    c = Checker()
    comp = read_code(COMPONENTS)
    work = read_code(WORKBENCH)

    print("== 0. 反空转：三处都在，抽取没失效 ==")
    palette = def_body(comp, "internal fun rolePaletteOf(")
    c.ok("色源函数 rolePaletteOf 在（取不到就是空转）", len(palette) > 200, f"只有 {len(palette)} 字符")
    key_fn = def_body(comp, "internal fun roleBadgeKey(")
    c.ok(f"映射函数 roleBadgeKey 在且函数体 ≥ {BODY_FLOOR} 字符", len(key_fn) >= BODY_FLOOR, f"只有 {len(key_fn)} 字符")
    badge = def_body(comp, "fun RoleBadge(")
    c.ok("胶囊 RoleBadge 在（取不到就是空转）", len(badge) > 200, f"只有 {len(badge)} 字符")
    wire = def_body(work, "var memberShipper by remember(")
    c.ok("工作台取身份那一段在（截空即红）", len(wire) >= 120, f"只有 {len(wire)} 字符")

    print("== 1. 色源：多一支「批发商」（与货主同一族色） ==")
    arms = re.findall(r'"([^"]*)"\s*->\s*RolePalette\("([^"]*)"\s*,\s*Color\(0xFF([0-9A-Fa-f]{6})\),\s*Color\(0xFF([0-9A-Fa-f]{6})\)\)', palette)
    c.ok(f"三种角色 + 批发商货主都给足了亮/暗两档色（找到 {len(arms)} 支，应有 4 支）", len(arms) == 4, f"实际 {len(arms)} 支：{[a[0] for a in arms]}")
    c.present("兜底那一支还在（不认识的键原样显示，不吞身份）", palette, r"else\s*->\s*RolePalette\(role,")
    by_key = {a[0]: a for a in arms}
    c.ok(f"多出来的那一支的键是 {MEMBER_KEY}（批发商在库里 role 仍是 SHIPPER，不是第四种角色）", MEMBER_KEY in by_key, f"键有：{sorted(by_key)}")
    c.ok(f"货主那一支还是「{SHIPPER_LABEL}」（老行为一个字都没变）", by_key.get("shipper", ("", ""))[1] == SHIPPER_LABEL, f"实际「{by_key.get(chr(115) + chr(104) + chr(105) + chr(112) + chr(112) + chr(101) + chr(114), (chr(45), chr(45)))[1]}」")
    if MEMBER_KEY in by_key:
        c.ok(f"那一支写着「{MEMBER_LABEL}」（用户要的就是这个字）", by_key[MEMBER_KEY][1] == MEMBER_LABEL, f"实际「{by_key[MEMBER_KEY][1]}」")
        same = by_key[MEMBER_KEY][2:] == by_key.get("shipper", ("", "", "", ""))[2:]
        c.ok("批发商与货主同一族色（这是**决定**：他本来就是货主，变的只是那个字）", same, f"批发商 {by_key[MEMBER_KEY][2:]} / 货主 {by_key.get(chr(115) + chr(104) + chr(105) + chr(112) + chr(112) + chr(101) + chr(114), (chr(45), chr(45), chr(45), chr(45)))[2:]}")
    c.ok("批发商没有借名册那个琥珀色（色源里只有角色族色）", "FFF1C6" not in palette and "7A5900" not in palette, "色源里出现了名册那个琥珀色")

    print("== 2. 唯一那份映射（只对货主生效、问不出来按 false） ==")
    holders = [q for q in kt_files(ANDROID) if "fun roleBadgeKey(" in read_code(q)]
    c.ok("全树只有一个 roleBadgeKey（抄第二份 = 改一处漏一处）", len(holders) == 1, f"出现在：{[str(q.relative_to(ROOT)) for q in holders]}")
    c.present("签名收下两个维度（roleKey + memberShipper）", key_fn, r"fun roleBadgeKey\(\s*roleKey:\s*String,\s*memberShipper:\s*Boolean\s*\)")
    c.ok("那道门写着 roleKey == shipper（只对货主生效：派单员/司机被标了也不改标签）", '"shipper"' in key_fn and "roleKey ==" in key_fn, "找不到那道门")
    c.ok(f"两种身份各回各的键（{MEMBER_KEY} / 原样返回）", MEMBER_KEY in key_fn and "else roleKey" in key_fn, "两支写法不对")
    c.absent("没有把身份写死（不许无条件返回批发商）", key_fn, r"if\s*\(\s*true\s*\)")
    c.ok("映射里没有取数 / 没有 Compose 状态（纯函数，能单测）", "remember" not in key_fn and "repo." not in key_fn, "纯函数里混进了状态或网络")

    print("== 3. 胶囊真的用了那份映射 ==")
    c.present("RoleBadge 收下身份那一维，默认 false（fail-closed：忘了传 = 按普通货主画）", badge, r"fun RoleBadge\(\s*role:\s*String,\s*memberShipper:\s*Boolean\s*=\s*false\s*\)")
    c.ok("体内只有一次 rolePaletteOf，参数正是 roleBadgeKey(role, memberShipper)", badge.count("rolePaletteOf(") == 1 and "rolePaletteOf(roleBadgeKey(role, memberShipper))" in badge, "胶囊没把身份交给色源（或者又抄了一份判断）")
    c.ok("映射只调一次（调两次就是自带一套判断）", badge.count("roleBadgeKey(") == 1, f"调了 {badge.count(chr(114) + chr(111) + chr(108) + chr(101) + chr(66) + chr(97) + chr(100) + chr(103) + chr(101) + chr(75) + chr(101) + chr(121) + chr(40))} 次")
    c.absent(f"胶囊里没有自己写「{MEMBER_LABEL}」三个字（字只能来自色源）", badge, MEMBER_LABEL)

    print("== 4. 工作台：问一次身份，交给头部 ==")
    c.ok("WelcomeBar 收下身份（role + memberShipper）", re.search(r"fun WelcomeBar\(\s*role:\s*Role,\s*memberShipper:\s*Boolean\s*\)", work) is not None, "WelcomeBar 的签名里没有身份那一维")
    c.ok("那颗胶囊被喂上身份（RoleBadge(role.key, memberShipper)）", "RoleBadge(role.key, memberShipper)" in work, "胶囊没拿到身份 —— 批发商又会写「货主」")
    c.ok("工作台真的问了一次自己的身份（repo.me().isMember）", "repo.me().isMember" in wire, "没问：那 14 个批发商永远看不到「批发商」")
    c.ok("问不到就当普通货主（getOrDefault(false) 是 fail-closed 的关键）", "getOrDefault(false)" in wire, "兜底不是 false —— 全体货主会被写成批发商")
    c.ok("重新问的条件挂在 role.key 上（换账号/换角色不串味）", "remember(role.key)" in wire and "LaunchedEffect(role.key)" in wire, "没挂 role.key")
    c.ok("头部自己不取数（那一行里只能有一个网络调用点）", "repo.me()" not in def_body(work, "private fun WelcomeBar("), "头部里出现了第二个取数点")
    c.absent(f"工作台没有硬编码「{MEMBER_LABEL}」三个字", work, MEMBER_LABEL)
    c.ok("头部文案还是从 workbenchHeaderText 来的（没为批发商另写一套）", "workbenchHeaderText(role)" in work, "头部文案被分叉了")

    print("== 5. 单测在钉这两维 ==")
    t = read(BADGE_TEST)
    n = t.count("@Test")
    c.ok(f"单测条数 ≥ {TEST_MIN}（实测 {n} 条）", n >= TEST_MIN, f"只有 {n} 条")
    c.ok("单测真的在调纯函数（不是只测了个壳）", t.count("roleBadgeKey(") >= MIN_TEST_CALLS and "rolePaletteOf(" in t, "找不到对纯函数的调用")
    c.ok(f"两种身份都测了（{MEMBER_KEY} 与 shipper 各一条）", MEMBER_KEY in t and '"shipper"' in t, "缺一支")
    c.ok("「只对货主生效」有人测（派单员/司机传 true 也不改标签）", "dispatcher" in t and "driver" in t, "没人测派单员/司机")
    c.ok("fail-closed 那一支有人测（false → 原样返回）", "memberShipper = false" in t, "没人测问不出来的那一支")

    print("== 6. 接线：规范 / 定位表 / 反验 / 登记 / 装包脚本 ==")
    design = read(DESIGN)
    i = design.find("### 4.13")
    sec = design[i:i + 4000] if i >= 0 else ""
    c.ok("规范 §4.13 里写了这条规矩（批发商 + roleBadgeKey + is_member）", MEMBER_LABEL in sec and "roleBadgeKey" in sec and "is_member" in sec, "规范里没有这一条（规范是这条纪律唯一的文字出处）")
    c.ok("规范里指路到本判据", JUDGE_NAME in sec, f"没写 {JUDGE_NAME}")
    rows = [ln for ln in read(LOCATOR).splitlines() if ln.startswith("| **工作台") and JUDGE_NAME in ln]
    c.ok("定位表「工作台」那一行指路到本判据", len(rows) == 1, f"匹配 {len(rows)} 行")
    c.ok("反向验证脚本在", REVERSE.exists(), str(REVERSE))
    rev = read(REVERSE) if REVERSE.exists() else ""
    c.ok("反验脚本拿着注入锁（lock_reverse_verify）", "lock_reverse_verify" in rev, "没上锁：注入期间别的检查会给出不可信的结论")
    c.ok("文档在（docs/changes/CHG-0033.md）", DOC.exists(), str(DOC))
    BT = chr(96)
    c.ok("登记簿里有 CHG-0033 这一行（整行，不是一个链接里的字样）", bool(re.search(r"^\|\s*" + BT + "?CHG-0033" + BT + "?\\s*\\|", read(REGISTRY), re.M)), "没登记（别人不知道这个 ID 用掉了）")
    marks = [ln for ln in read(INSTALL).splitlines() if ln.strip().startswith("STRONG_MARK")]
    c.ok("装包脚本认角色靠头部文案，不靠胶囊上的字（胶囊上的字现在因人而异）", bool(marks) and all(SHIPPER_LABEL not in m and MEMBER_LABEL not in m for m in marks), f"STRONG_MARK 里出现了胶囊上的字：{marks}")

    return c.report("工作台胶囊按实际身份写字（CHG-0033）")


if __name__ == "__main__":
    if "--list" in sys.argv:
        print("工作台那颗胶囊按实际身份写字，分六层：")
        print("  0. 反空转：色源 / 映射 / 胶囊 / 工作台取身份那一段都在；")
        print("  1. 色源：4 支 + 兜底、shipper_member 写「批发商」、与货主同族色；")
        print("  2. 唯一那份映射：全树一份、那道 shipper 门在、只认 memberShipper；")
        print("  3. 胶囊：第二维默认 false、体内只有一次 rolePaletteOf；")
        print("  4. 工作台：WelcomeBar 收身份、胶囊拿到身份、头部不取数、挂 role.key；")
        print("  5. 接线：单测 / 规范 §4.13 / 定位表 / 反验（拿着注入锁）/ 登记簿 / 装包脚本。")
        sys.exit(0)
    sys.exit(main())
