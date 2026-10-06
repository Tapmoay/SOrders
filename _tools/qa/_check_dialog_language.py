# -*- coding: utf-8 -*-
"""弹窗语言：全 App 的弹窗收敛成**白卡 ＋ 顶部一个语义色图标**（台账 L-20 / CHG-0064，2026-10-06）。

## 用户口径（原话）
「很多弹窗都太难看了，像我们这个批发商和货主他那个退货……那个弹窗太难看了，不符合我们的设计基调。」
（用户 m00481）

## 机制：难看是从哪来的
M3 的 `AlertDialog` 默认容器色 = `colorScheme.surfaceContainerHigh`（本主题那层灰，见 CHG-0051 /
CHG-0063），再加那 6dp 的 tonal elevation。全库几十处调用点**无一处**设过 `containerColor`，
也**无一处**带图标 ⇒ 所有弹窗长同一个灰底，而且「删了就回不来」的动作与「填个表单」长得一模一样。

## 这一刀做了什么（CHG-0064）
1. 共用零件 `ui/common/Components.kt` 的 `CardAlertDialog` 长出 `tone: DialogTone`（默认 INFO）
   与 `DialogToneIcon`（INFO=提示蓝 / WARN=警告橙 / DANGER=危险红，三档**形状也不同**）；
2. `DangerConfirmDialog` 改成转发本件 ＋ `tone = DialogTone.DANGER`（21 处"红色确认钮"的老
   调用点一次性对齐，21 处）；
3. 全库 62 处裸 `AlertDialog(` 一次性迁到本件 ⇒ 本件体内那**一行** `AlertDialog(` 成了全库
   唯一剩下的一处。

## 判据
1. 全库**代码**里裸 `AlertDialog(` 恰好 1 处，且在 `CardAlertDialog` 的函数体里；
2. 零件：白卡三行（`containerColor = surface` / `shapes.extraLarge` / `tonalElevation = 0.dp`）
   ＋ 默认档 INFO ＋ 图标接线（`icon ?: { DialogToneIcon(tone) }`）；
3. `DialogTone` **只三档**，三档的图标与色值一一对应（INFO=`primary` / WARN=`WarningAmber` /
   DANGER=`colorScheme.error`）；
4. `DangerConfirmDialog` 转发本件 ＋ DANGER（按钮那两行没被顺手改）；
5. 危险正文 ⇒ 必须 DANGER（关键词 `删除|撤销|撤回|作废|解绑|不可逆`）＋ 用户点名的那 6 处退货弹窗
   逐个钉住档位；
6. 登记与随动：CHG-0064.md / README 行 / CLAIM 条目 / 设计基线里的弹窗容器口径；
7. 防静默空转：扫到的 .kt >= MIN_KT，调用点 >= MIN_CALLS，且三档**都真有人在用**。

## 为什么这条必须有机器的判据
「弹窗太丑」在类型上表达不出来：`containerColor: Color` 就是一个颜色，`#E1DDD5`（灰）与
`#FFFFFF`（白卡）都是合法的 `Color`；「危险动作要红图标」更是只写在人的脑子里。这一刀坏掉的方式
**全都不报错**：零件那三行被抽掉一行、档位被抹平成一个颜色、某处又自己画一层底、
危险弹窗忘了给 DANGER —— 编译通过、用例全绿，界面上却是「一眼看出不对」的那种坏。
反向验证：python _tools/qa/_reverse_verify_dialog_language.py（12 种破坏方式全被抓）。

用法：python _tools/qa/_check_dialog_language.py
"""
from __future__ import annotations

import collections
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
COMP = AND / "ui/common/Components.kt"
COLOR = AND / "ui/theme/Color.kt"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
CHG = ROOT / "docs/changes/CHG-0064.md"
README = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_dialog_language.py"

#: 防静默空转的下限（实测 292 份 .kt / 68 处调用点）。
MIN_KT = 250
MIN_CALLS = 60
MIN_DANGER = 15
MIN_WARN = 8

#: ⛔ 数裸弹窗必须排除 `Card` 前缀（`CardAlertDialog(` 里含子串 `AlertDialog(`）。
BARE = r"(?<!Card)AlertDialog\("
CARD = r"CardAlertDialog\("
#: 调用点的长相：整行只有调用名（定义那一行是 `fun CardAlertDialog(`，不会被它匹配）。
OPEN = re.compile(r"^(\s*)CardAlertDialog\(\s*$")
#: 「删了/撤了/退掉就回不来」这一族动词 —— 正文里出现就必须是 DANGER 档。
DANGER_WORDS = re.compile(r"删除|撤销|撤回|作废|解绑|不可逆")

#: 用户点名的那几处退货弹窗（m00481：「像我们这个批发商和货主他那个退货……」）。
#: (文件, 标题里那一段, 该是什么档, 为什么)
PINS = [
    ("ui/dispatcher/DispatcherOrdersScreen.kt", 'DialogTitle("退货"', "DANGER",
     "派单员给货主办退货：落地就回不来"),
    ("ui/dispatcher/DispatcherReturnRequestsScreen.kt", 'DialogTitle("办理退货"', "DANGER",
     "办完这条退货申请就落地了"),
    ("ui/dispatcher/DispatcherReturnRequestsScreen.kt", 'DialogTitle("驳回退货申请"', "WARN",
     "驳回要留神，但不是删除"),
    ("ui/shipper/ShipperOrdersScreen.kt", 'DialogTitle("申请退货"', "WARN",
     "表单：填完不一定提交"),
    ("ui/shipper/ShipperOrdersScreen.kt", 'Text("撤回这张退货申请？")', "DANGER",
     "撤回就回不来"),
    ("ui/shipper/ShipperReturnRequestsScreen.kt", 'Text("撤回这张退货申请？")', "DANGER",
     "撤回就回不来"),
]


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def code_only(text: str) -> str:
    """去掉注释但保留换行数（行号对得上）。

    ⛔ 零件的 KDoc 里**故意**写着「那一行 `AlertDialog(` 是全库唯一剩下的一处」这类话；
    判据要钉的是**代码**，不是注释里提没提它。
    """
    text = re.sub(r"/\*[\s\S]*?\*/", lambda m: "\n" * m.group(0).count("\n"), text)
    return re.sub(r"//[^\n]*", "", text)


def count(text: str, pattern: str) -> int:
    return len(re.findall(pattern, text))


def call_bodies(text: str) -> list[tuple[int, str]]:
    """每个调用点的「代码正文」（行号 1 起）：从 `CardAlertDialog(` 那一行数到同缩进的 `)`。"""
    lines = text.split("\n")
    out: list[tuple[int, str]] = []
    for i, ln in enumerate(lines):
        m = OPEN.match(ln)
        if not m:
            continue
        indent = len(m.group(1))
        buf = [ln]
        for j in range(i + 1, min(len(lines), i + 80)):
            buf.append(lines[j])
            if lines[j].strip().startswith(")") and (len(lines[j]) - len(lines[j].lstrip())) == indent:
                break
        out.append((i + 1, "\n".join(buf)))
    return out


def tone_of(body: str) -> str:
    if "tone = DialogTone.DANGER" in body:
        return "DANGER"
    if "tone = DialogTone.WARN" in body:
        return "WARN"
    return "INFO"


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print(f"  [OK]   {label}")
        else:
            self.fails.append(label + (f" —— {detail}" if detail else ""))
            print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))

    def present(self, label: str, text: str, pattern: str) -> None:
        self.ok(label, re.search(pattern, text) is not None, f"没找到 {pattern!r}")


def main() -> int:
    c = Checker()
    kts = sorted(AND.rglob("*.kt"))
    files = {p: code_only(read(p)) for p in kts}
    comp = read(COMP)
    comp_code = files[COMP]

    print("== 0. 防静默空转 ==")
    c.ok(f"扫到的 .kt 有 {len(kts)} 份（>= {MIN_KT}）", len(kts) >= MIN_KT)
    calls = [(p, ln, b) for p, t in files.items() for ln, b in call_bodies(t)]
    c.ok(f"全库 CardAlertDialog 调用点 {len(calls)} 处（>= {MIN_CALLS}）", len(calls) >= MIN_CALLS,
         f"实际 {len(calls)}")
    tiers = collections.Counter(tone_of(b) for _p, _ln, b in calls)
    c.ok(f"三档都真有人在用（INFO {tiers['INFO']} / WARN {tiers['WARN']} / DANGER {tiers['DANGER']}）",
         tiers["DANGER"] >= MIN_DANGER and tiers["WARN"] >= MIN_WARN, str(dict(tiers)))
    for p in (COMP, COLOR, DESIGN, REVERSE):
        c.ok(f"关键文件在：{p.relative_to(ROOT).as_posix()}", p.exists())

    print("== 1. 全库只剩定义自己那一处裸弹窗 ==")
    bare_left = {p.relative_to(AND).as_posix(): count(t, BARE) for p, t in files.items() if count(t, BARE)}
    bare_total = sum(bare_left.values())
    c.ok(f"全库代码里裸 AlertDialog( = {bare_total} 处（只剩 CardAlertDialog 定义体内那一处）",
         bare_total == 1, f"实际 {bare_total} 处：{bare_left}")
    c.ok("剩下那一处就在 ui/common/Components.kt 里",
         list(bare_left) == ["ui/common/Components.kt"], str(bare_left))
    i_def = comp_code.find("fun CardAlertDialog(")
    m_bare = re.search(BARE, comp_code)
    i_end = comp_code.find("\n}", i_def) if i_def >= 0 else -1
    c.ok("那一处在 CardAlertDialog 的函数体里（不是哪个页面又自己长出一层底）",
         bool(m_bare) and i_def >= 0 and i_def < m_bare.start() < (i_end if i_end > i_def else len(comp_code)),
         "裸弹窗跑到定义外面去了")
    c.ok(f"调用点远多于定义（{len(calls)} 处调用都走零件）", len(calls) >= MIN_CALLS)

    print("== 2. 零件：白卡 ＋ 默认档 ＋ 图标接线 ==")
    body_i = comp_code.find("fun CardAlertDialog(")
    body = comp_code[body_i:body_i + 1600] if body_i >= 0 else ""
    c.present("白卡：containerColor = MaterialTheme.colorScheme.surface", body,
              r"containerColor = MaterialTheme\.colorScheme\.surface,")
    c.present("弹层圆角：shape = MaterialTheme.shapes.extraLarge", body,
              r"shape = MaterialTheme\.shapes\.extraLarge,")
    c.present("⛔ tonalElevation = 0.dp（M3 那 6dp 会给白底再刷一层主色薄雾）", body,
              r"tonalElevation = 0\.dp,")
    c.present("默认档：tone: DialogTone = DialogTone.INFO（不写就是提示蓝）", body,
              r"tone: DialogTone = DialogTone\.INFO,")
    c.present("图标接线：icon = icon ?: { DialogToneIcon(tone) }", body,
              r"icon = icon \?: \{ DialogToneIcon\(tone\) \},")
    c.present("槽位照旧：properties 透传", body, r"properties = properties,")

    print("== 3. DialogTone：只三档，档与色一一对应 ==")
    m_enum = re.search(r"enum class DialogTone\s*\{([^}]*)\}", comp_code)
    names = [t for t in re.split(r"[,\s]+", m_enum.group(1)) if t] if m_enum else []
    c.ok("只三档（INFO / WARN / DANGER —— 多一档就多一种「这件事是什么性质」的歧义）",
         sorted(names) == ["DANGER", "INFO", "WARN"], str(names))
    i_icon = comp_code.find("fun DialogToneIcon(")
    icon = comp_code[i_icon:i_icon + 1200] if i_icon >= 0 else ""
    c.present("INFO 档 ＝ 提示蓝（Icons.Filled.Info ＋ colorScheme.primary）", icon,
              r"DialogTone\.INFO -> Icons\.Filled\.Info[\s\S]{0,400}?DialogTone\.INFO -> MaterialTheme\.colorScheme\.primary")
    c.present("WARN 档 ＝ 警告橙（Icons.Filled.WarningAmber ＋ Color(WarningAmber)）", icon,
              r"DialogTone\.WARN -> Icons\.Filled\.WarningAmber[\s\S]{0,400}?DialogTone\.WARN -> Color\(WarningAmber\)")
    c.present("DANGER 档 ＝ 危险红（Icons.Filled.Dangerous ＋ colorScheme.error）", icon,
              r"DialogTone\.DANGER -> Icons\.Filled\.Dangerous[\s\S]{0,400}?DialogTone\.DANGER -> MaterialTheme\.colorScheme\.error")
    c.present("图标尺寸 28dp", icon, r"Modifier\.size\(28\.dp\)")
    c.ok("三档的**形状**也各不相同（只靠颜色分档，色盲用户读不到）",
         all(f"Icons.Filled.{n}" in icon for n in ("Info", "WarningAmber", "Dangerous")), "图标少了一个")
    c.present("警告橙是 import 来的（不是就地写一个橙色字面量）", comp_code,
              r"import com\.tapmoay\.sorders\.ui\.theme\.WarningAmber")
    c.present("Color.kt 里那份橙色还在（WARN 档的色源；Color.kt 写的是 Long 字面量 0xFFFF9F1CL）",
              read(COLOR), r"val WarningAmber = 0xFFFF9F1C")

    print("== 4. DangerConfirmDialog 对齐到 DANGER（老调用点跟着走） ==")
    i_dcd = comp_code.find("fun DangerConfirmDialog(")
    dcd = comp_code[i_dcd:i_dcd + 1400] if i_dcd >= 0 else ""
    c.present("DangerConfirmDialog 转发本件（自己不再画一层底）", dcd, r"\n\s*CardAlertDialog\(")
    c.present("并且显式带 DANGER 档", dcd, r"tone = DialogTone\.DANGER,")
    c.present("红色确认钮那两行还在（本事项没动按钮与文案）", dcd,
              r"containerColor = MaterialTheme\.colorScheme\.error,")

    print("== 5. 危险正文 ⇒ 必须 DANGER（规则 ＋ 用户点名那 6 处逐个钉） ==")
    danger_sites = [(p, ln) for p, ln, b in calls if DANGER_WORDS.search(b)]
    loose = [(p, ln) for p, ln, b in calls if DANGER_WORDS.search(b) and tone_of(b) != "DANGER"]
    c.ok(f"全库有 {len(danger_sites)} 处正文带危险词（删除/撤销/撤回/作废/解绑/不可逆）",
         len(danger_sites) >= MIN_DANGER, f"实际 {len(danger_sites)}")
    c.ok("每一处危险正文都配了 DANGER 档（一条都没漏）", not loose,
         "漏了：" + ", ".join(f"{p.name}:{ln}" for p, ln in loose))
    for rel, fragment, want, why in PINS:
        hits = [(ln, b) for p, ln, b in calls if p.relative_to(AND).as_posix() == rel and fragment in b]
        got = tone_of(hits[0][1]) if len(hits) == 1 else f"命中 {len(hits)} 处"
        c.ok(f"{rel} 的「{fragment}」是 {want} 档（{why}）", len(hits) == 1 and got == want, f"实际 {got}")

    print("== 6. 登记与随动 ==")
    c.ok("docs/changes/CHG-0064.md 在（本事项的立项文档）", CHG.exists())
    chg = read(CHG) if CHG.exists() else ""
    c.present("CHG-0064 点得出台账编号 L-20", chg, r"L-20")
    c.present("CHG-0064 点得出零件名（后来的人知道改哪里）", chg, r"CardAlertDialog")
    c.present("CHG-0064 点了语义档（DialogTone）", chg, r"DialogTone")
    c.present("docs/changes/README.md 有 CHG-0064 的登记行（链到文档）", read(README),
              r"\[CHG-0064\.md\]\(CHG-0064\.md\)")
    claim = read(CLAIM)
    c.present("AI_WORK_CLAIM 有本事项的条目（标题行）", claim, r"会话：\*\*CHG-0064")
    c.present("AI_WORK_CLAIM 的交叉点行记了这个零件", claim, r"ui/common/Components\.kt")
    c.present("设计基线写了弹窗容器口径（白卡 ＋ 顶部语义色图标）", read(DESIGN), r"CardAlertDialog")
    rv = read(REVERSE) if REVERSE.exists() else ""
    c.ok("反验脚本在，且注入表至少 10 条", rv.count("\n    (\n") >= 10,
         f"实际 {rv.count(chr(10) + '    (' + chr(10))} 条")

    print()
    if c.fails:
        print(f"❌ {len(c.fails)} 项不通过：")
        for f in c.fails:
            print(f"  - {f}")
        return 1
    print(f"✅ 全部 {c.passes} 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
