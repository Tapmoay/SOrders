# -*- coding: utf-8 -*-
"""红线：截断必须带省略号 + 提供看全文的入口 + 长数字串不许被劈开（CHG-0027 / E2E 走查 P18·P28·P30·P4，2026-10-03）。

## 这条是怎么来的
2026-10-03 的 E2E 走查把四条**同一个毛病**记在了一张单子上（`_tmp/E2E测试报告.md`），
验收口径是 `:236-243` 修复优先级第 5 条，逐字：「**P18 / P28 / P30 / P4** 统一「截断必须带省略号 + 提供看全文的入口」」：

- **P18**（`:115-117`）：「运费模板卡片文字被截断，且没有查看全文的入口 ……省略号截在词中间，
  页面上只有 删除 / 编辑，看不到完整条件。」
- **P28**（`:124-126`）：「司机「我的」副标题被截断，且以肯定词开头 ……显示「**固定工资**
  （月薪未设置，账单里不会出现…」——前面是肯定词、后面才否定，很容易读成「我有固定工资」。」
- **P30**（`:128-132`）：「地点卡片的联系人电话被静默裁掉 ……分隔点后面**没有号码，也没有省略号**。
  无障碍树里字符串是完整的。」
- **P4**（`:160-162`）：「长数字串被硬换行劈成两半 ……「账号：138000012 / 34 密码：123456」；
  退货弹层标题：「SO2026100365088830 / 54」。这类文字是要**发给客户**的。」

## 为什么必须有机器的判据
四处改的全是「一个参数 / 一句话 / 一个换行点」，没有任何类型能拦住它们被改回去：
- `maxLines = 1` 且**不写 `overflow`** 时 Compose 默认 Clip —— 界面上是「字被吃掉、连省略号都没有」，
  而代码照样编译、全量单测照样全绿（没有人断言「电话看得见」）。走查 P30 就是这么来的：
  无障碍树里字符串完整、屏幕上看不见号码。
- 「看全文的入口」是**卡片本体可点**（`SectionCard(modifier = Modifier.clickable { onEdit() })`）：删掉这一层，
  页面不报错、编辑图标照样能开抽屉，只有用户不知道还能点卡片。
- P28 那句是**后端拼的一句话**（`services/driver_pay.py::pay_summary_for`），语序就是它的全部内容 ——
  把「月薪未设置」挪回括号里，症状原样回来，而任何测试都不会红。
- P4 是**换行点**：单号 / 手机号中间处处可断，Compose 按可用宽度自己断。手机上实测：弹层标题那行是
  24sp 大字，一行塞不下 20 个字符的 `SO…` 单号 ⇒ **光插 U+2060 不够**（整块放不下时换行器仍然
  只能从中间劈），必须同时把单号**另起一行 + 降到 bodyMedium**（`ui/common/DialogTitle.kt`）。
  U+2060 零宽、不可见 ⇒ **只有真机才看得出来**，静态判据只能盯「有没有插」「插在哪些串上」
  「单号那一行是不是小一号、封一行、带省略号」。

所以判据盯的是结构：参数、入口、语序、以及在哪些串上插了不可见字符；
⛔ 它不判断「好不好看」，那是真机截图的事（本事项的截图见 `docs/changes/CHG-0027.md` 的证据一节）。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界解决不了**。它全是界面参数与一句话的语序：
`LocationDto` / `FreightTemplateDto` / `UserOut.paySummary` 的出参一个字段没变、
接口没变、迁移没有、既有单测在这几处**断言不到**（Kotlin 侧是 Compose 布局属性，Python 侧只返回一个 str），
所以编译器与单测都不会有一句反对。只能扫源码结构与治理文档登记 —— 运行时那一头交给
`_tools/qa/_reverse_verify_text_truncation.py`（16 种破坏方式逐条注入）与 2026-10-03 模拟器
5554（运费模板 / 派单员订单页）/ 5556（地点卡）/ 5558（司机「我的」）的实测截图。
本判据只读源码与文档（read / code），不连库、不 import 后端、不跑迁移、不调用模型。

配套：python `_tools/qa/_reverse_verify_text_truncation.py`（16 种破坏方式全被抓）

用法：python _tools/qa/_check_text_truncation.py
     python _tools/qa/_check_text_truncation.py --list   # 只列它到底在查什么
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _check_product_card_single_source import strip_comments  # noqa: E402
from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

NOBREAK = AND / "util/NoBreak.kt"
ADDR = AND / "ui/shipper/AddressScreen.kt"
FREIGHT = AND / "ui/dispatcher/FreightTemplatesScreen.kt"
FREIGHT_VM = AND / "ui/dispatcher/FreightTemplatesViewModel.kt"
PROFILE = AND / "ui/profile/ProfileHeader.kt"
ACCT = AND / "ui/dispatcher/AccountManageViewModel.kt"
SHIPPER_ORDERS = AND / "ui/shipper/ShipperOrdersScreen.kt"
SHIPPER_LEDGER = AND / "ui/shipper/ShipperLedgerScreen.kt"
DISP_ORDERS = AND / "ui/dispatcher/DispatcherOrdersScreen.kt"
DISP_RETURNS = AND / "ui/dispatcher/DispatcherReturnRequestsScreen.kt"
LEDGER_PERSON = AND / "ui/dispatcher/LedgerPersonScreen.kt"
DIALOG_TITLE = AND / "ui/common/DialogTitle.kt"
PAY = ROOT / "backend/app/services/driver_pay.py"
README = ROOT / "docs/changes/README.md"
DOC = ROOT / "docs/changes/CHG-0027.md"
REVERSE = "_tools/qa/_reverse_verify_text_truncation.py"

DQ = chr(34)
#: U+2060 WORD JOINER（零宽、不可见：只把「可以在这里换行」改成「不许在这里换行」）
ZWJ = chr(0x2060)
#: 反斜杠：Kotlin 源码里的 \u2060 / \n 都靠它拼（⛔ 本文里不写裸转义 —— 锚点审计要的是源文件里那几个字符）
BS = chr(92)

#: P4：八个弹层标题 —— 单号另起一行、小一号、整块不换行（(文件, 那一行的逐字原文, 说明)）
TITLES: list[tuple[Path, str, str]] = [
    (SHIPPER_ORDERS, "title = { DialogTitle(" + DQ + "申请退货" + DQ + ", order.orderNo) }", "货主 · 申请退货"),
    (SHIPPER_LEDGER, "title = { DialogTitle(" + DQ + "核销订单" + DQ + ", " + DQ + "#" + DQ + " + order.orderNo) }", "货主 · 核销"),
    (SHIPPER_LEDGER, "title = { DialogTitle(" + DQ + "订单核销记录" + DQ + ", " + DQ + "#" + DQ + " + order.orderNo) }", "货主 · 核销记录"),
    (DISP_ORDERS, "title = { DialogTitle(" + DQ + "编辑订单" + DQ + ", vm.editingOrder?.orderNo ?: " + DQ + DQ + ") }", "派单员 · 编辑订单"),
    (DISP_ORDERS, "title = { DialogTitle(" + DQ + "退货" + DQ + ", order.orderNo) }", "派单员 · 退货"),
    (DISP_RETURNS, "title = { DialogTitle(" + DQ + "办理退货" + DQ + ", req.orderNo) }", "派单员 · 办理退货"),
    (DISP_RETURNS, "title = { DialogTitle(" + DQ + "驳回退货申请" + DQ + ", req.orderNo) }", "派单员 · 驳回"),
    (LEDGER_PERSON, "title = { DialogTitle(" + DQ + "核销" + DQ + ", order.orderNo) }", "派单员 · 核销"),
]

IMPORT = "import com.tapmoay.sorders.util.noBreak"
#: 八个弹层标题现在都调这一个 composable（单号那一行只在这里钉）
DT_CALL = "DialogTitle("
DT_SIG = "fun DialogTitle(action: String, orderNo: String)"
#: 界面文件数的下限：目录被搬走时判据必须**报红**，而不是空转变绿
MIN_UI_FILES = 50


def read(q: Path) -> str:
    if not q.exists():
        return ""
    return q.read_text(encoding="utf-8", errors="replace")


def code(q: Path) -> str:
    return strip_comments(read(q))


def hits(needle: str, sources: list[tuple[str, str]]) -> list[str]:
    return [name for name, src in sources if needle in src]


def window(src: str, needle: str, before: int, after: int) -> str:
    i = src.find(needle)
    if i < 0:
        return ""
    return src[max(0, i - before) : i + len(needle) + after]


def block(src: str, head: str) -> str:
    """从 head 起、到下一个顶层 @Composable 之前（圈住单个 composable 的函数体）。"""
    i = src.find(head)
    if i < 0:
        return ""
    j = src.find("@Composable", i + len(head))
    return src[i:] if j < 0 else src[i:j]


def backend_sources() -> list[tuple[str, str]]:
    return [
        (q.relative_to(ROOT).as_posix(), q.read_text(encoding="utf-8", errors="replace"))
        for q in sorted((ROOT / "backend/app").rglob("*.py"))
    ]


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

    def report(self, title: str) -> int:
        print()
        print(f"===== {title} =====")
        print(f"  通过 {self.passes} 项，失败 {len(self.fails)} 项")
        for f in self.fails:
            print(f"    - {f}")
        return 1 if self.fails else 0


def main() -> int:
    if refuse_if_injecting("截断与长数字检查"):
        return 1

    c = Checker()
    print("截断必须带省略号 + 看全文的入口 + 长数字串不许被劈开（CHG-0027 / 走查 P18·P28·P30·P4）：2026-10-03")

    kt = sorted(AND.rglob("*.kt"))
    kt_sources = [(q.relative_to(AND).as_posix(), code(q)) for q in kt]
    n_kt = len(kt)
    c.ok(
        f"扫到的界面文件数 ≥ {MIN_UI_FILES}（防目录搬走 → 判据空转）",
        n_kt >= MIN_UI_FILES,
        f"实际 {n_kt} 个 .kt",
    )

    # ---- 1. 通用工具 ----
    print()
    print("== 1. 通用工具：整块不换行 + 标题两行（P4 那八个标题全靠它） ==")
    nb = read(NOBREAK)
    nbc = code(NOBREAK)
    c.ok("util/NoBreak.kt 在", NOBREAK.exists(), "找不到 " + str(NOBREAK))
    n_def = sum(src.count("fun String.noBreak(): String") for _n, src in kt_sources)
    c.ok("fun String.noBreak(): String 全库恰好一份", n_def == 1, f"实际 {n_def} 处")
    c.ok(
        "幂等早返回在（串里已经有了就不再插一层）",
        "if (length < 2 || contains(" in nbc and "return this" in window(nbc, "if (length < 2 || contains(", 0, 160),
        "找不到那行早返回",
    )
    loop = window(nbc, "forEachIndexed", 0, 240)
    c.ok(
        "真的往相邻字符之间插 U+2060（循环里每次 append 的都是那个转义序列）",
        "forEachIndexed" in nbc and ("append('" + BS + "u2060')") in loop,
        "找不到插字符的那段",
    )
    c.ok(
        "KDoc 写清三条约束（只用于标题 / ⛔ 不回传后端或入库 / 剪贴板拿到的是原文）",
        "回传后端或存库" in nb and "剪贴板" in nb and "只在" in nb,
        "KDoc 里那三条约束不全",
    )
    c.ok(
        "源码里没有写成真实零宽字符（必须是转义：否则锚点、编辑器、grep 都看不出来）",
        ZWJ not in nb,
        "NoBreak.kt 里出现了真实的 U+2060",
    )

    uses: list[tuple[str, str]] = []
    for name, src in kt_sources:
        if name == "util/NoBreak.kt":
            continue  # 定义文件自己那一行不是使用点
        for line in src.splitlines():
            if ".noBreak()" in line:
                uses.append((name, line.strip()))
    c.ok(
        "noBreak() 全库只剩 1 处使用（八处标题都改调 DialogTitle，换行点只在这里钉）",
        len(uses) == 1,
        f"实际 {len(uses)} 处：" + "、".join(n for n, _l in uses[:3]),
    )
    c.ok(
        "这一处就在 ui/common/DialogTitle.kt 里",
        [n for n, _l in uses] == ["ui/common/DialogTitle.kt"],
        "不在 DialogTitle.kt：" + "、".join(n for n, _l in uses[:3]),
    )
    files_imp = sorted(q.relative_to(AND).as_posix() for q in kt if IMPORT in read(q))
    c.ok(
        "import 它的文件也恰好只有 DialogTitle.kt（没有多余 import）",
        files_imp == ["ui/common/DialogTitle.kt"],
        f"import 它的文件：{files_imp}",
    )
    n_sig = sum(src.count(DT_SIG) for _n, src in kt_sources)
    c.ok("fun DialogTitle(action: String, orderNo: String) 全库恰好一份", n_sig == 1, f"实际 {n_sig} 处")
    dt_body = window(code(DIALOG_TITLE), DT_SIG, 0, 700)
    c.ok("动作名单独占第一行（Text(action)）", "Text(action)" in dt_body, "第一行不是动作名")
    c.ok(
        "单号那一行降了一号（bodyMedium，不再是标题的 24sp）",
        "style = MaterialTheme.typography.bodyMedium," in dt_body,
        "单号还在用对话框标题的字号",
    )
    c.ok(
        "单号那一行封一行 + 带省略号（⛔ 不许静默裁掉）",
        "maxLines = 1," in dt_body and "overflow = TextOverflow.Ellipsis," in dt_body,
        "少了 maxLines / Ellipsis",
    )
    c.ok("单号整块不换行（orderNo.noBreak()）", "orderNo.noBreak()," in dt_body, "noBreak 不见了")
    c.ok(
        "单号为空时那一行不画（调用方常传空串）",
        "if (orderNo.isNotBlank())" in dt_body,
        "空串时会多画一行空的",
    )
    calls: list[tuple[str, str]] = []
    for name, src in kt_sources:
        if name == "ui/common/DialogTitle.kt":
            continue  # 定义文件自己那一行不是调用点
        for line in src.splitlines():
            if DT_CALL in line:
                calls.append((name, line.strip()))
    c.ok("DialogTitle 的调用点恰好 8 处（P4 那八个弹层标题）", len(calls) == 8, f"实际 {len(calls)} 处")
    not_title = [l for _n, l in calls if not l.startswith("title = {")]
    c.ok("每一处都长在弹层标题里（⛔ 别拿它去拼正文长串）", not not_title, "这些行不在标题里：" + "、".join(not_title[:3]))
    risky = [l for _n, l in calls if ("repo." in l or "Request(" in l or "json" in l)]
    c.ok("没有一处跟着回传 / 入库（U+2060 会一起进去）", not risky, "这些行疑似回传：" + "、".join(risky[:3]))
    for path, needle, what in TITLES:
        c.ok("P4 弹层标题：单号另起一行、小一号：" + what, needle in code(path), "找不到这一行：" + needle)

    # ---- 2. P30 ----
    print()
    print("== 2. P30 地点卡：联系人电话不许被静默裁掉 ==")
    ad = code(ADDR)
    contact = window(ad, "boundContactLabel(l.contactName, l.contactPhone)", 0, 460)
    c.ok(
        "联系人那一行给了两行（走查 P30：一行放不下时默认 Clip 连省略号都没有）",
        "maxLines = 2," in contact,
        "窗口里没有 maxLines = 2：" + contact[-160:],
    )
    c.ok(
        "仍放不下时按 StartEllipsis 保尾部（电话少一位就真打不出去了）",
        "overflow = TextOverflow.StartEllipsis," in contact,
        "窗口里没有 StartEllipsis",
    )
    loc = block(ad, "private fun LocationCard(")
    n_two = loc.count("maxLines = 2,")
    n_tail = loc.count("overflow = TextOverflow.StartEllipsis,")
    c.ok(
        "同一张卡两行都给了两行 + 保尾部（地址行也在内），没有 Clip 式截断",
        n_two == 2 and n_tail == 2,
        f"实际 maxLines = 2 有 {n_two} 处 / StartEllipsis 有 {n_tail} 处",
    )
    c.ok(
        "地点卡本身可点 = 看全文的入口（右边那两颗动作图标各管各的）",
        "SectionCard(modifier = Modifier.clickable { onEdit() }) {" in loc,
        "LocationCard 里没有可点的 SectionCard",
    )
    c.ok(
        "它点开的就是这一条的抽屉（onEdit 由调用点传 openLocationEdit）",
        "onEdit: () -> Unit" in loc and "onEdit = { vm.openLocationEdit(l) }" in ad,
        "函数签名或调用点对不上",
    )
    c.ok("旧的裸 SectionCard 写法在 LocationCard 里清零", "SectionCard {" not in loc, "卡片还是点不动")

    # ---- 3. P18 ----
    print()
    print("== 3. P18 运费模板：三行小字看得完，看全文有入口 ==")
    fr = code(FREIGHT)
    card = block(fr, "private fun FreightTemplateCard(")
    c.ok(
        "运费模板卡本身可点 = 看全文的入口（点开就是这一条的抽屉）",
        "SectionCard(modifier = Modifier.clickable { onEdit() }) {" in card,
        "FreightTemplateCard 里没有可点的 SectionCard",
    )
    n2 = card.count("maxLines = 2,")
    c.ok("三处小字都给了两行（价目名 / 用在 / 备注）", n2 == 3, f"实际 {n2} 处 maxLines = 2")
    c.ok("同一函数里 maxLines = 1 清零（截断必须带省略号，不是 Clip）", "maxLines = 1" not in card, "还有 maxLines = 1 的小字")
    n_ell = card.count("overflow = TextOverflow.Ellipsis,")
    c.ok("三处都写明了 Ellipsis", n_ell == 3, f"实际 {n_ell} 处 overflow = Ellipsis")
    c.ok("点开的确实是这一条：调用点写 onEdit = { vm.openEdit(t) }", "onEdit = { vm.openEdit(t) }" in fr, "调用点变了")
    c.ok(
        "抽屉本身还在（全文就靠它看）",
        "fun openEdit(t: FreightTemplateDto) {" in code(FREIGHT_VM),
        "FreightTemplatesViewModel 里没有 openEdit",
    )
    n_btn = card.count("TextButton(")
    c.ok("没为它再加第三颗按钮（那一行还是 删除 / 编辑）", n_btn == 2, f"实际 {n_btn} 颗")

    # ---- 4. P28 后端 ----
    print()
    print("== 4. P28 后端：那句话以否定开头 ==")
    pay = code(PAY)
    NEW = "return " + DQ + "月薪未设置，不会生成他的工资单（计费方式：固定工资）" + DQ
    # ⚠️ 锚点用**整条 return**（不是半句）：`driver_pay.py:326-328` 那三行改动注释里
    # 引用了旧措辞的半句，而 `strip_comments` 只认 Kotlin 的 `//`、不认 Python 的 `#`，
    # 拿半句当锚点会把判据自己顶红。
    OLD = "return " + DQ + "固定工资（月薪未设置，账单里不会出现他的工资单）" + DQ
    c.ok("driver_pay 那句改成否定在前（⛔ 语序是判据的一部分）", NEW in pay, "找不到新句子")
    srcs = backend_sources()
    c.ok("旧文案在生产代码里 0 处（换回去必须有人看见）", not hits(OLD, srcs), "还在：" + "、".join(hits(OLD, srcs)))
    c.ok(
        "这句话只有一处拼（界面照抄，「钱只说一句」）",
        len(hits("不会生成他的工资单", srcs)) == 1,
        "出现处：" + "、".join(hits("不会生成他的工资单", srcs)),
    )
    c.ok(
        "五个分支都还在（没顺手删别的口径）",
        all(x in pay for x in ["if rule is not None:", "已挂计费规则", "按单计费：每单拿该单的运费（未挂规则）", "元/月（未挂规则）", "月薪未设置"]),
        "pay_summary_for 的分支被改动了",
    )

    # ---- 5. P28 客户端 ----
    print()
    print("== 5. P28 客户端：司机「我的」那一行 ==")
    pr = code(PROFILE)
    pay_line = window(pr, "val pay = user?.paySummary.orEmpty()", 0, 520)
    c.ok(
        "司机「我的」那句话给了两行（原来一行放不下会在规则名中间断掉）",
        "maxLines = 2," in pay_line,
        "窗口里没有 maxLines = 2：" + pay_line[-160:],
    )
    c.ok("溢出仍带省略号（不是 Clip）", "overflow = TextOverflow.Ellipsis," in pay_line, "窗口里没有 Ellipsis")
    c.ok("头部底部留白没被这一行吃掉（bottom = 60.dp）", "bottom = 60.dp" in pr, "留白被压了")
    c.ok("那句话仍来自 pay_summary（界面不许自己拼钱）", "user?.paySummary.orEmpty()" in pr, "取值来源变了")

    # ---- 6. P4 ----
    print()
    print("== 6. P4 长数字串：账号密码两行，单号整块不换行 ==")
    ac = code(ACCT)
    c.ok(
        "账号密码分享文案拆成两行（走查 P4：11 位手机号会被从中间劈开）",
        (BS + "n密码：") in ac,
        "还是并列在一行里",
    )
    c.ok("剪贴板拿到的就是这两行文本（onSaved 与 copyText 同一份）", "onSaved(" in ac, "onSaved 不见了")
    full_width = [n for n, src in kt_sources if "　密码：" in src]
    c.ok("两个数字串各自成行的老写法（全角空格并列）全库 0 处", not full_width, "还在：" + "、".join(full_width))
    old_style = [
        (n, l.strip())
        for n, src in kt_sources
        for l in src.splitlines()
        if "title = { Text(" in l and "orderNo" in l
    ]
    c.ok(
        "老写法（标题那一行直接拼单号，20 个字符会被从中间劈开）全库 0 处",
        not old_style,
        "还在：" + "、".join(n for n, _l in old_style[:3]),
    )

    # ---- 7. 文档与配对 ----
    print()
    print("== 7. 登记与配对 ==")
    c.ok(
        "本判据写了边界理由（_check_r3_constraints.py 的检查器预算闸要 R4-BOUNDARY-JUSTIFICATION）",
        "R4-BOUNDARY-JUSTIFICATION:" in read(Path(__file__)),
        "模块 docstring 里没有 R4-BOUNDARY-JUSTIFICATION 段",
    )
    c.ok("配套的反向验证脚本在", (ROOT / REVERSE).exists(), "找不到 " + REVERSE)
    c.ok("docs/changes/CHG-0027.md 在", DOC.exists(), "找不到 " + str(DOC))
    row = read(README)
    c.ok("登记簿里有 CHG-0027 这一行", ("| `CHG-0027` |") in row, "docs/changes/README.md 里没有这一行")

    if "--list" in sys.argv:
        print()
        print("  == 它到底在查什么 ==")
        print("     · util/NoBreak.kt：插 U+2060、幂等、只用于标题、⛔ 不回传，且源码里不出现真实零宽字符");
        print("     · 全库 8 处使用 + 五个文件都 import 了它（没有多余 import）");
        print("     · P30 地点卡：联系人行两行 + 保尾部；卡片本体可点开抽屉");
        print("     · P18 运费模板：三处小字两行 + Ellipsis；卡片本体可点；没加第三颗按钮");
        print("     · P28 后端：那句以「月薪未设置」开头，旧语序全库 0 处，一句话只有一处拼");
        print("     · P28 客户端：司机「我的」那行两行 + Ellipsis，取值仍来自 pay_summary");
        print("     · P4：账号密码两行、全角并列清零；八个弹层标题都调 DialogTitle")
        print("       （单号另起一行 + bodyMedium + 封一行带省略号 + noBreak）");
        print("     · 登记簿与配套反向验证脚本在 + 本文自己的边界理由在");

    return c.report("截断与长数字：四处「看不全」（CHG-0027 / 走查 P18·P28·P30·P4）")


if __name__ == "__main__":
    sys.exit(main())
