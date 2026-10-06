# -*- coding: utf-8 -*-
"""红线：已挂账的单，订单详情底部那两颗按钮要变成「核销」＋「改挂账单位」（台账 L-44 / CHG-0069）。

## 这条是怎么来的
2026-10-07 用户台账 L-44（原话 ref m01874）：「挂完账之后仍然还有挂账按钮在那里呃这个不应该这样子的……
如果挂完账之后，它这些按钮要变成什么要变成核销啊，是这样子的要核销账啊，而不是可以又可以挂账啊。」
病灶：挂账只改 `payment_method = "arrears"`，`paid` 仍 False、`settledAmount` 仍 0 ⇒
`OrderStatusModel.canChargeToArrears` 仍为真 ⇒ 底部「现场支付 / 挂账」原样都在 —— 而这两颗在这一档上
点了都是坏的：再挂一次＝欠款**静默改挂到另一家**；点「现场支付」＝欠款**静默蒸发且不记流水**。
口径六问 m01956 全部落定：① 主「核销」＋ 次「改挂账单位」；② 点核销＝**直接整单核销**；
③ 已收现金那一档显示「已收清」并把两颗禁用按钮收掉；④ 没有客户档案时**在弹窗里就地建 / 关联**；
⑤ 挂账单上的「现场支付」收掉不画；⑥ AI 只加「已挂账」判据（派单员 AI 核销先不开）。

## 为什么必须有机器的判据
这一条改完之后，界面上"长得很像"的错法至少有六种，全都照样编译、照样跑单测：

1. **分档写反**：`when` 里先判 `charged` 再判 `paid`，或者干脆只看 `paymentMethod == "arrears"` ——
   已收清的单会重新长出「核销」按钮，点下去后端 400（`已经收过款了…不能重复收款`）。
2. **两个谓词被合并**：把「已挂账」并进 `canChargeToArrears` —— 那是界面与 AI 共用的"已收款"门，
   语义只有"钱收没收到"一件事；混进"已挂账"之后 AI 侧连话都说不清（它会说"你收过款了"）。
3. **核销那一步不是整单**：金额从 `amount`（商品行合计）取、或者顺手传了 `orderProductIds` ——
   退过货的单上两个数差一大截（本机 order 13：行 42.80 / 欠 21.40），后端逐单按欠款校验会 400。
4. **没有客户档案那扇门写错**：直接发请求（后端必 400「订单 X 无客户归属」），或者拿**名字**去认客户档案
   （重名＝把钱收到别人头上）；临时货主那一档还必须只给引导、连请求都不发。
5. **收款方式被抄了第二份**：四个选项与顺序是用户看得见的东西，账本页 + 订单详情两处各排一遍，
   迟早会出现"单张核销有挂账结清、这处没有"的漂移。
6. **红线失配**：`_check_paid_actions.py` ③ 取挂账那颗按钮**之前 900 字符**的窗口、
   `_reverse_verify_paid_actions.py` 的锚点① 钉着那一行 32 空格的 `canChargeToArrears(...)` ——
   给那段原文多包一层块（缩进一变）就全失配，而界面上一点看不出区别。

所以判据分八层（空转闸 / 两个谓词 / 三档按钮 / 整单核销 / 无档案两道门与共用件 / AI 侧 / 不改的东西 / 文档），
并且**自带空转闸**：扫到的 .kt 数、抽出来的函数体长度、以及判据自己的总项数都要达标 ——
少了任何一头，这条红线会安静地全绿，比没有判据更危险。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界解决不了**。病是"挂完账之后底部还是那两颗"，而"分档对不对"
在类型上完全一样：`when` 的先后、谓词里有没有 `paymentMethod == "arrears"`、核销请求里传的是
`arrearsAmount` 还是 `amount`、没有档案时弹的是引导还是直接发请求 —— 全都照样编译、照样跑单测，
界面上（不进模拟器真的点一遍）看不出区别。所以只能扫**结构**：三个分支的顺序与形态、两个谓词的函数体、
核销请求那六行、两道门的先后、以及共用件是不是真的只有一份。
配套：python _tools/qa/_reverse_verify_order_settle_button.py（每一种拆法都要被抓）；
「屏幕上真的能用」那一头由模拟器实测的截图负责（`shots/chg0069_*_5554.png`）。
本判据只读源码与文档（`read()`），不连库、不 import 后端、不跑迁移。

用法：python _tools/qa/_check_order_settle_button.py
      python _tools/qa/_check_order_settle_button.py --list   # 只列它到底在查什么
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
# 注释剥离**只有一份实现**（抄一份必踩同一个坑）
from _check_product_card_single_source import strip_comments  # noqa: E402
from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders"
SCREEN = AND / "ui/order/OrderDetailScreen.kt"
VM = AND / "ui/order/OrderDetailViewModel.kt"
MODEL = AND / "core/OrderStatusModel.kt"
PICKER = AND / "ui/common/SettleMethodPicker.kt"
EDITOR = AND / "ui/common/CustomerEditorDialog.kt"
LEDGER_PERSON = AND / "ui/dispatcher/LedgerPersonScreen.kt"
LEDGER_VM = AND / "ui/dispatcher/DispatcherLedgerViewModel.kt"
AI_WRITE = AND / "ai/AiWrite.kt"
AI_DS = AND / "ai/AiWriteDataSource.kt"
AI_HANDLERS = AND / "ai/AiWriteOrderHandlers.kt"
AI_TEST = TEST / "ai/AiWriteTest.kt"
MODEL_TEST = TEST / "core/OrderStatusModelTest.kt"
ORDERS_PAYMENT = ROOT / "backend/app/api/v1/orders_payment.py"
ACCOUNTING = ROOT / "backend/app/services/accounting_service.py"
DTOS = AND / "data/remote/dto/Dtos.kt"
CATALOG = ROOT / "docs/PROJECT_MAP/09A_HINT_CATALOG.md"
SPEC = ROOT / "docs/changes/CHG-0069.md"
README = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = "_tools/qa/_reverse_verify_order_settle_button.py"

#: 扫到的界面文件数下限（防目录改名 / 搬走之后"一个文件都没扫到"也算过）
MIN_UI_FILES = 100
#: 抽出来的函数体字符数下限（**抽取失效比判据腐烂更危险** —— 那会变成一条永远绿的检查）
BODY_FLOOR = 200
SMALL_BODY_FLOOR = 120
PREDICATE_FLOOR = 60
#: ⛔ 空转即停：判据自己的总项数下限（少了就是判据被删空）
MIN_ITEMS = 40

CHARGED_PICK = "val charged = OrderStatusModel.isChargedToArrears(order.paymentMethod, order.paid, order.settledAmount)"
#: 反验 _reverse_verify_paid_actions.py 的锚点①（32 空格，⛔ 逐字不许动）
ANCHOR_PAID_ACTIONS_MODEL = "                                OrderStatusModel.canChargeToArrears(order.paid, order.settledAmount),"
#: 反验 _reverse_verify_paid_actions.py 的锚点②（8 空格，⛔ 逐字不许动）
ANCHOR_PAID_ACTIONS_AI = "        if (!OrderStatusModel.canChargeToArrears(order.paid, order.settledAmount)) {"
AI_CHARGED = "OrderStatusModel.isChargedToArrears(order.paymentMethod, order.paid, order.settledAmount)"
SAME_CUSTOMER = "container.repo.customers().firstOrNull { it.userId != null && it.userId == o.shipperId }"


def read(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def code(p: Path) -> str:
    return strip_comments(read(p))


def count(needle: str, text: str) -> int:
    return text.count(needle)


def fn_body(src: str, sig: str) -> str:
    """sig（如 `fun settleNow(`）那个函数的**函数体**（按大括号配对，不是按行猜）。"""
    i = src.find(sig)
    if i < 0:
        return ""
    b = src.find("{", i)
    if b < 0:
        return ""
    depth = 0
    for j in range(b, len(src)):
        ch = src[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[b : j + 1]
    return ""


def expr_body(src: str, sig: str, span: int = 400) -> str:
    """sig 那个**表达式体**函数的定义段（`fun x(...) = ...` 后面没有大括号）。"""
    i = src.find(sig)
    if i < 0:
        return ""
    j = src.find("\n\n", i)
    return src[i : j if j > 0 else i + span]


def sig_of(src: str, sig: str, span: int = 400) -> str:
    """签名那一段（从 `fun X(` 起 span 个字符）—— 参数表在这里，函数体里没有。"""
    i = src.find(sig)
    return "" if i < 0 else src[i : i + span]


def has_line(src: str, line: str) -> bool:
    """这一行**整行**在（含缩进）—— 防"多缩进一层也算命中"这种假过。"""
    norm = src.replace("\r\n", "\n")
    return ("\n" + line + "\n") in ("\n" + norm + "\n")


def before(src: str, a: str, b: str) -> bool:
    """a 在 b **之前**（两个都找得到才算真）。"""
    i, j = src.find(a), src.find(b)
    return i >= 0 and j >= 0 and i < j


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

    @property
    def total(self) -> int:
        return self.passes + len(self.fails)

    def report(self, title: str) -> int:
        print()
        print(f"===== {title} =====")
        print(f"  通过 {self.passes} 项，失败 {len(self.fails)} 项，共 {self.total} 项")
        for f in self.fails:
            print(f"    - {f}")
        return 1 if self.fails else 0


def main() -> int:
    if refuse_if_injecting("订单详情挂账按钮分档检查"):
        return 1

    c = Checker()
    print("已挂账的单：底部换成「核销」＋「改挂账单位」（台账 L-44 / CHG-0069）：2026-10-07")

    LABEL_CHARGE = "Text(\"挂账\")"
    LABEL_PAY = "Text(if (order.paid) \"已收款\" else \"现场支付\")"
    ZHANG = read(SCREEN)

    all_kt = list(AND.rglob("*.kt"))
    all_ui = "".join(code(p) for p in all_kt)
    screen, vm, model = code(SCREEN), code(VM), code(MODEL)
    picker, editor = code(PICKER), code(EDITOR)
    ledger_person, ledger_vm = code(LEDGER_PERSON), code(LEDGER_VM)
    ai_write, ai_ds, ai_handlers = code(AI_WRITE), code(AI_DS), code(AI_HANDLERS)

    # ---- 0. 空转闸：先证明"确实扫到了东西" ----
    c.ok(
        f"扫到的界面文件数 ≥ {MIN_UI_FILES}（防目录搬走 → 判据空转）",
        len(all_kt) >= MIN_UI_FILES,
        f"实际 {len(all_kt)}",
    )
    for p, why, floor in (
        (SCREEN, "订单详情（三档按钮区 ＋ 四处挂载）", 2000),
        (VM, "订单详情 VM（核销状态与三个动作）", 2000),
        (MODEL, "两个谓词本体", 2000),
        (AI_HANDLERS, "AI 挂账 handler", 2000),
        (PICKER, "共用收款方式选择器", 500),
        (EDITOR, "共用建客户档案弹层", 500),
    ):
        c.ok(f"空转闸：{why}读得到（{p.name}）", len(code(p)) >= floor, f"{len(code(p))} 字符")
    charged_row = fn_body(screen, "private fun ChargedActionsRow(")
    collected_row = fn_body(screen, "private fun CollectedActionsRow(")
    confirm_dlg = fn_body(screen, "private fun SettleConfirmDialog(")
    temp_dlg = fn_body(screen, "private fun TempShipperSettleDialog(")
    box = fn_body(vm, "fun openSettle(")
    now = fn_body(vm, "fun settleNow(")
    make = fn_body(vm, "fun createCustomerAndSettle(")
    editor_body = fn_body(editor, "fun CustomerEditorDialog(")
    picker_body = fn_body(picker, "fun SettleMethodPicker(")
    handler_body = fn_body(ai_handlers, "class ChargeOrderHandler(")
    charged_pred = expr_body(model, "fun isChargedToArrears(")
    settle_pred = expr_body(model, "fun canSettle(")
    charge_pred = expr_body(model, "fun canChargeToArrears(")
    for label, body, floor in (
        ("ChargedActionsRow（已挂账那一档两颗按钮）", charged_row, SMALL_BODY_FLOOR),
        ("CollectedActionsRow（已收清那一档）", collected_row, SMALL_BODY_FLOOR),
        ("SettleConfirmDialog（核销确认弹层）", confirm_dlg, BODY_FLOOR),
        ("TempShipperSettleDialog（临时货主引导）", temp_dlg, SMALL_BODY_FLOOR),
        ("OrderDetailViewModel.openSettle", box, BODY_FLOOR),
        ("OrderDetailViewModel.settleNow", now, BODY_FLOOR),
        ("OrderDetailViewModel.createCustomerAndSettle", make, BODY_FLOOR),
        ("CustomerEditorDialog（共用建档案弹层）", editor_body, BODY_FLOOR),
        ("SettleMethodPicker（共用收款方式）", picker_body, SMALL_BODY_FLOOR),
        ("ChargeOrderHandler（AI 挂账）", handler_body, BODY_FLOOR),
        ("OrderStatusModel.isChargedToArrears", charged_pred, PREDICATE_FLOOR),
        ("OrderStatusModel.canSettle", settle_pred, PREDICATE_FLOOR),
        ("OrderStatusModel.canChargeToArrears", charge_pred, PREDICATE_FLOOR),
    ):
        c.ok(
            f"空转闸：{label} 的函数体抽得出来（≥ {floor} 字符）",
            len(body) >= floor,
            f"只抽到 {len(body)} 字符 —— 抽取失效会让下面每一条都安静地过",
        )

    # ---- 1. 两个谓词：一处实现、两处消费 ----
    c.ok(
        "isChargedToArrears 签名逐字（paymentMethod / paid / settledAmount 三个一起看）",
        "fun isChargedToArrears(paymentMethod: String?, paid: Boolean, settledAmount: String?): Boolean =" in model,
        "签名被改过 —— 界面与 AI 两处调用点会一起失配",
    )
    c.ok(
        "isChargedToArrears 真要的三件事：未收款 ＋ 收款方式是挂账 ＋ 一分钱没进过",
        "!paid" in charged_pred
        and 'paymentMethod == "arrears"' in charged_pred
        and "settledAmount?.toDoubleOrNull() ?: 0.0" in charged_pred,
        f"函数体：{charged_pred[:160]}",
    )
    c.ok(
        "canSettle 签名逐字（paid / status / arrearsAmount）",
        "fun canSettle(paid: Boolean, status: String, arrearsAmount: String?): Boolean =" in model,
        "签名被改过 —— 账本页那份是同口径的对照物",
    )
    c.ok(
        "canSettle 与账本页同口径：未收清 ＋ 不是已撤销/已退货 ＋ 欠款 > 0",
        "!paid" in settle_pred
        and "CANCELLED" in settle_pred
        and "RETURNED" in settle_pred
        and "> 0.0" in settle_pred,
        f"函数体：{settle_pred[:160]}",
    )
    c.ok(
        "账本页那份 canSettle(o: OrderDto) 仍在（「同口径」这句话要有个对照物）",
        "fun canSettle(o: OrderDto): Boolean =" in ledger_vm,
        "账本页那份被删/改名了 —— 这条判据的「同口径」失去锚点",
    )
    c.ok(
        "canChargeToArrears 本体逐字未动（已收款那道门只认钱）",
        "!paid && (settledAmount?.toDoubleOrNull() ?: 0.0) <= 0.0" in charge_pred,
        f"函数体：{charge_pred[:160]}",
    )
    c.ok(
        "⛔ 没有把「已挂账」并进 canChargeToArrears（它的函数体里不许出现 paymentMethod）",
        "paymentMethod" not in charge_pred,
        "两个谓词混在一起了 —— 这是界面与 AI 共用的「钱收没收到」门，AI 侧会说错话",
    )
    c.ok(
        "isChargedToArrears 的消费点恰好 2 处（界面 1 ＋ AI 1）",
        count("OrderStatusModel.isChargedToArrears(", all_ui) == 2,
        f"数到 {count('OrderStatusModel.isChargedToArrears(', all_ui)} 处 —— 有人又抄了一份判据",
    )
    c.ok(
        "canSettle 的消费点恰好 1 处（订单详情；账本页那份是它自己的写法）",
        count("OrderStatusModel.canSettle(", all_ui) == 1,
        f"数到 {count('OrderStatusModel.canSettle(', all_ui)} 处",
    )

    # ---- 2. 详情页三档按钮 ----
    c.ok(
        "分档条件逐字（三个字段一起喂进去）",
        CHARGED_PICK in screen and count(CHARGED_PICK, screen) == 1,
        "分档那一行被改过 —— 已挂账的单会退回原来那两颗",
    )
    c.ok(
        "三档都在：已收款 → 已收清；已挂账 → 核销；其余 → 原样两颗",
        "order.paid -> CollectedActionsRow()" in screen
        and "charged -> ChargedActionsRow(" in screen
        and "else -> Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {" in screen,
        "三档里少了哪一档",
    )
    c.ok(
        "⛔ 顺序：已收清排在 charged 之前（已收清的单不许长出「核销」）",
        before(screen, "order.paid -> CollectedActionsRow()", "charged -> ChargedActionsRow("),
        "顺序反了 —— 已收清的单会显示核销，点下去后端 400",
    )
    c.ok(
        "⛔ 顺序：charged 排在 else（原样两颗）之前",
        before(screen, "charged -> ChargedActionsRow(", "else -> Row("),
        "顺序反了 —— 已挂账的单还是那两颗",
    )
    c.ok(
        "已挂账那一档画的是「核销」＋「改挂账单位」两颗",
        "Text(\"核销\")" in charged_row and "Text(\"改挂账单位\")" in charged_row,
        f"函数体：{charged_row[:160]}",
    )
    c.ok(
        "⛔ 已挂账那一档不再画「现场支付」（口径 ⑤：点下去＝欠款静默蒸发）",
        "现场支付" not in charged_row,
        "这一档又把现场支付画回来了 —— 它会把欠款抹掉且不记流水",
    )
    c.ok(
        "「核销」接 onSettleClick、「改挂账单位」接 onChangeUnitClick，忙时都禁用",
        "onClick = onSettleClick" in charged_row
        and "onClick = onChangeUnitClick" in charged_row
        and "enabled = !acting" in charged_row,
        f"函数体：{charged_row[:200]}",
    )
    c.ok(
        "内容 composable 的参数表多了 onSettleClick: () -> Unit",
        "    onSettleClick: () -> Unit," in screen,
        "签名没接上 —— 那颗按钮点了什么都不会发生",
    )
    c.ok(
        "接线：onSettleClick = { vm.openSettle() }",
        "onSettleClick = { vm.openSettle() }," in screen,
        "没接到 VM 上",
    )
    c.ok(
        "「已收清」那一档：一颗对勾 ＋ 一句说明（不再是两颗禁用按钮）",
        "Icons.Default.CheckCircle" in collected_row and "已收清" in collected_row,
        f"函数体：{collected_row[:160]}",
    )
    c.ok(
        "⛔ 原文那两颗按钮逐字未动（现场支付/挂账仍留在 else 那一档）",
        LABEL_PAY in screen and LABEL_CHARGE in screen,
        "原文被改写过 —— 未收款那一档的行为会跟着变",
    )
    c.ok(
        "⛔ 全文件 Text(挂账) 只剩 1 处（_check_paid_actions.py ③ 按**第一处**取 900 字符窗口）",
        count(LABEL_CHARGE, ZHANG) == 1,
        f"数到 {count(LABEL_CHARGE, ZHANG)} 处 —— 注释里写一遍也算，窗口会取错地方",
    )

    # ---- 3. 核销＝整单（VM）----
    c.ok(
        "openSettle 先过 canSettle 那道门并给一句人话",
        "!OrderStatusModel.canSettle(o.paid, o.status, o.arrearsAmount)" in box
        and "这一单已经没有可收的钱了" in box,
        f"函数体：{box[:200]}",
    )
    c.ok(
        "openSettle 认客户档案只按 userId（⛔ 不按名字：重名会把钱收到别人头上）",
        SAME_CUSTOMER in box,
        "认人的方式被改过",
    )
    c.ok(
        "openSettle 记下三件事：settleCustomerId / settleTempShipper / settleMethod",
        "settleCustomerId = cust?.id" in box
        and "settleTempShipper = o.shipperId == null" in box
        and "settleMethod = \"cash\"" in box,
        f"函数体：{box[:240]}",
    )
    c.ok(
        "openSettle 的分岔：有档案 → 核销确认；没有 → 建/关联档案那一扇门",
        "if (cust != null) showSettleConfirm = true else showCustomerDialog = true" in box,
        "分岔没了 —— 没有档案的单会直接发一次注定失败的请求",
    )
    c.ok(
        "settleNow 走的是既有端点与既有 DTO（createReceipt ＋ ReceiptCreateRequest）",
        "container.repo.createReceipt(" in now and "ReceiptCreateRequest(" in now,
        "又写了一套核销请求",
    )
    c.ok(
        "⛔ 金额取欠款 arrearsAmount（不是商品行合计 amount）",
        "amount = o.arrearsAmount," in now,
        "金额口径错了 —— 退过货的单会被后端逐单校验打回 400",
    )
    c.ok(
        "⛔ 整单核销：orderIds = listOf(orderId) ＋ settleMode = itemized ＋ 没有 orderProductIds",
        "orderIds = listOf(orderId)," in now
        and "settleMode = \"itemized\"," in now
        and "orderProductIds" not in now,
        "口径②说好了点核销＝直接整单，这里出现了按商品的痕迹",
    )
    c.ok(
        "收款方式走这一刻选中的那一颗（method = settleMethod）",
        "method = settleMethod," in now,
        "收款方式写死了 / 取错地方了",
    )
    c.ok(
        "收完重拉这一单、报一句「已核销 ¥X」、把确认弹层关掉",
        "order = container.repo.order(orderId)" in now
        and "actionResult = \"已核销 ¥\"" in now
        and "showSettleConfirm = false" in now,
        f"函数体：{now[:260]}",
    )
    c.ok(
        "createCustomerAndSettle：临时货主只给引导、**连请求都不发**",
        "if (sid == null) {" in make
        and "货主管理" in make
        and before(make, "if (sid == null) {", "container.repo.createCustomer("),
        "临时货主那条路会把注定失败的请求发出去（后端 400「订单 X 无客户归属」）",
    )
    c.ok(
        "createCustomerAndSettle：带 userId 建一次就是「关联」（kind = registered ＋ userId = sid）",
        "kind = \"registered\"," in make and "userId = sid," in make,
        "建出来的是没有账号的临时档案 —— 核销照样记不到谁头上",
    )
    c.ok(
        "建完直开核销：settleCustomerId → 关档案弹层 → 开核销确认",
        before(make, "settleCustomerId = c.id", "showSettleConfirm = true")
        and "showCustomerDialog = false" in make,
        f"函数体：{make[:240]}",
    )
    c.ok(
        "VM 里那四个状态都在（showSettleConfirm / showCustomerDialog / settleTempShipper / settleCustomerId）",
        all(
            s in vm
            for s in (
                "var showSettleConfirm",
                "var showCustomerDialog",
                "var settleTempShipper",
                "var settleCustomerId",
            )
        ),
        "少了一个状态 —— 弹层挂不上",
    )

    # ---- 4. 没有客户档案那两道门 ＋ 两个共用件 ----
    c.ok(
        "临时货主那一档只给引导（说清临时货主 ＋ 去哪儿关联）",
        "临时货主" in temp_dlg and "货主管理" in temp_dlg,
        f"函数体：{temp_dlg[:200]}",
    )
    c.ok(
        "⛔ 临时货主那一档里没有核销请求（createReceipt / ReceiptCreateRequest 都不许出现）",
        "createReceipt" not in temp_dlg and "ReceiptCreateRequest" not in temp_dlg,
        "引导那一档也去发请求了",
    )
    c.ok(
        "两道门按 settleTempShipper 分岔（临时货主 → 引导；正式货主 → 就地建/关联）",
        "if (vm.settleTempShipper) {" in screen
        and "TempShipperSettleDialog(" in screen
        and "CustomerEditorDialog(" in screen,
        "分岔没了",
    )
    c.ok(
        "核销确认弹层：标题带单号（走共用 DialogTitle，单号另起一行不劈开）、金额只显示不让人改",
        "DialogTitle(\"核销\", orderNo)" in confirm_dlg
        and "formatMoney(amount)" in confirm_dlg
        and "确认核销" in confirm_dlg,
        f"函数体：{confirm_dlg[:220]}",
    )
    c.ok(
        "核销确认弹层吃的是共用收款方式选择器（没有第二份）",
        "SettleMethodPicker(selected = method, onSelect = onMethodChange)" in confirm_dlg,
        "订单详情又排了一遍收款方式",
    )
    c.ok(
        "建客户档案弹层只有一份实现（ui/common/CustomerEditorDialog.kt）",
        count("fun CustomerEditorDialog(", all_ui) == 1,
        f"数到 {count('fun CustomerEditorDialog(', all_ui)} 处 —— 与 L-40「就地新建只许一份实现」同一条纪律",
    )
    c.ok(
        "订单详情只是挂载它（调用点 1 处）",
        count("CustomerEditorDialog(", screen) == 1,
        f"数到 {count('CustomerEditorDialog(', screen)} 处",
    )
    c.ok(
        "建档案弹层：两个字段行走共用表单行（名称必填 ＋ 电话输入规则）",
        "FormInputRow(" in editor_body
        and "required = true" in editor_body
        and "InputRules.phoneInput(" in editor_body,
        f"函数体：{editor_body[:200]}",
    )
    c.ok(
        "⛔ 建档案弹层里不许出现描边输入框（表单行有唯一实现，_check_form_panel_style.py 盯着）",
        "OutlinedTextField" not in editor_body,
        "又造了一份描边表单行",
    )
    c.ok(
        "建档案弹层：空名字不许提交、忙时禁用、按钮说的是「建好并核销」",
        "enabled = !busy && name.isNotBlank()" in editor and "建好并核销" in editor,
        f"函数体：{editor_body[:200]}",
    )
    c.ok(
        "收款方式四个选项只有一份（SETTLE_METHODS，账本页与订单详情都从这里拿）",
        "SETTLE_METHODS" in picker and "SETTLE_METHODS" not in ledger_person,
        "账本页又自己排了一份选项表",
    )
    c.ok(
        "四个选项与顺序逐字（现金 / 转账 / 微信 / 挂账结清）",
        all(
            x in picker
            for x in (
                "\"cash\" to \"现金\"",
                "\"transfer\" to \"转账\"",
                "\"wechat\" to \"微信\"",
                "\"arrears_settle\" to \"挂账结清\"",
            )
        ),
        "选项的取值或文案被改过 —— 收款单的性质会跟着变",
    )
    c.ok(
        "⛔ 账本个人页里不再有自己那张选项表（搬走之后一行都不许留）",
        "arrears_settle" not in ledger_person,
        "账本页还留着自己那一份胶囊 / 取值",
    )
    c.ok(
        "⛔ 收款方式那张表只许有一份（picker 里 arrears_settle 那一行）—— 不许再长第三份",
        count('"arrears_settle" to "挂账结清",', all_ui) == 1,
        f"数到 {count(chr(34) + 'arrears_settle' + chr(34) + ' to ' + chr(34) + '挂账结清' + chr(34) + ',', all_ui)} 处 —— 多出来的那一份要合并进 ui/common/SettleMethodPicker.kt",
    )
    c.ok(
        "账本页那颗选择器仍在（签名行逐字 —— 原判据与反验的锚点）",
        "private fun SettleMethodChips(vm: DispatcherLedgerViewModel) {" in ledger_person,
        "签名行被改过 —— _check_ledger_dashboard.py 与它的反验会失配",
    )
    c.ok(
        "账本页那次改成委托：函数体里只调共用件，没有第二份实现",
        "SettleMethodPicker(selected = vm.settleMethod" in ledger_person
        and "FilterChip(" not in ledger_person,
        "账本页还留着自己的那一份胶囊",
    )
    c.ok(
        "账本页两个调用点没丢（单张核销 ＋ 批量核销）",
        count("SettleMethodChips(vm)", ledger_person) == 2,
        f"数到 {count('SettleMethodChips(vm)', ledger_person)} 处",
    )

    # ---- 5. AI 侧：只加「已挂账」判据 ----
    c.ok(
        "AiOrderRef 末尾追加了 paymentMethod（排在 arrearsAmount 之后 —— 位置参数调用才安全）",
        "val paymentMethod: String = \"cash\"," in ai_write
        and before(ai_write, "val arrearsAmount: String = amount,", "val paymentMethod: String = \"cash\","),
        "新字段插在中间会把它后面的字段整体顶掉一位（类注释写明了这条）",
    )
    c.ok(
        "两个构造点都补了 paymentMethod = d.paymentMethod（恰好 2 处）",
        count("paymentMethod = d.paymentMethod,", ai_ds) == 2,
        f"数到 {count('paymentMethod = d.paymentMethod,', ai_ds)} 处",
    )
    c.ok(
        "AiWriteTest 里 AiOrderRef( 的调用点仍 ≥ 20（新字段追加在最后的前提）",
        count("AiOrderRef(", code(AI_TEST)) >= 20,
        f"数到 {count('AiOrderRef(', code(AI_TEST))} 处",
    )
    c.ok(
        "ChargeOrderHandler 里新判据排在旧判据**之前**（先拦已挂账，再说已收款）",
        before(handler_body, AI_CHARGED, "if (!OrderStatusModel.canChargeToArrears("),
        "顺序反了 —— 已挂账的单会被说成「已经收过款了」",
    )
    c.ok(
        "新判据抛的是 AiWriteArgException，话术指路订单详情",
        "AiWriteArgException(" in handler_body
        and "已经挂账" in handler_body
        and "订单详情" in handler_body,
        f"函数体：{handler_body[:260]}",
    )
    c.ok(
        "⛔ 反验锚点②（8 空格那句）逐字仍在",
        has_line(read(AI_HANDLERS), ANCHOR_PAID_ACTIONS_AI),
        "缩进被改了 —— _reverse_verify_paid_actions.py 会失配",
    )

    # ---- 6. 不改的东西 ----
    c.ok(
        "⛔ 反验锚点①（32 空格那行）逐字仍在",
        has_line(ZHANG, ANCHOR_PAID_ACTIONS_MODEL),
        "缩进被改了（给原文多包一层块就会这样）",
    )
    c.ok(
        "后端 charge_order 唯一的门没动（仍只挡已收款）",
        '_reject_if_already_collected(db, order, "改回挂账")' in read(ORDERS_PAYMENT),
        "后端那道门被动了 —— 本条只该改界面",
    )
    c.ok(
        "后端收款 / 挂账两个端点都还在（没有新端点）",
        count('@router.post("/{order_id}/', read(ORDERS_PAYMENT)) == 2,
        f"数到 {count(chr(64) + chr(114) + chr(111) + chr(117) + chr(116) + chr(101) + chr(114), read(ORDERS_PAYMENT))} 个 router 装饰器",
    )
    c.ok(
        "核销算法与三条拒没动（无客户归属 / 不属于该客户 / 不能重复收款）",
        all(x in read(ACCOUNTING) for x in ("无客户归属", "不属于该客户", "不能重复收款")),
        "后端的核销算法被改了 —— 本条只该复用",
    )
    raw_dto = sig_of(code(DTOS), "data class ReceiptCreateRequest(", 2000)
    cut = raw_dto.find("\n)")
    dto_span = raw_dto[:cut] if cut > 0 else raw_dto
    dto_fields = [ln.strip() for ln in dto_span.splitlines() if ln.strip().endswith(",")]
    c.ok(
        "DTO 没动：ReceiptCreateRequest 的 orderProductIds 仍排在**最后一个**（按位置传参的老调用点安全）",
        bool(dto_fields) and "orderProductIds" in dto_fields[-1],
        f"最后一行字段是 {dto_fields[-1] if dto_fields else '(抽不到)'}",
    )
    c.ok(
        "客户端的挂账调用点没多也没少（VM 里仍是那两处）",
        count("container.repo.chargeOrder(", vm) == 2,
        f"数到 {count('container.repo.chargeOrder(', vm)} 处",
    )
    c.ok(
        "PaymentBadge 三档文案仍在（挂账 · X / 已收款 / 未收款）",
        "\"挂账 · \"" in screen and "\"已收款\"" in screen and "\"未收款\"" in screen,
        "徽章被顺手改了 —— 那不是本条的范围",
    )
    c.ok(
        "单测两条新用例在（两个谓词的真值表）",
        "只有已挂账且没收钱的那一档才换核销按钮" in read(MODEL_TEST)
        and "已收清或已退货的单没有可核销的钱" in read(MODEL_TEST),
        "判据没有配套的单测真值表",
    )

    # ---- 7. 文档与配对（判据自己也要有人盯）----
    c.ok(
        "新提示进了提示清单（跑过 python _tools/qa/_hint_inventory.py --md）",
        "档案先记这两样" in read(CATALOG),
        "09A_HINT_CATALOG.md 里没有这句 —— 提示总开关管不到它",
    )
    c.ok("变更单 docs/changes/CHG-0069.md 存在", SPEC.exists(), "变更单没了")
    spec = read(SPEC)
    c.ok(
        "变更单写清了两份脚本的名字（判据 ＋ 反向验证）",
        "_check_order_settle_button.py" in spec and "_reverse_verify_order_settle_button.py" in spec,
        "⑥/⑦ 里没有这份脚本的名字",
    )
    c.ok(
        "变更单的边界结论写的是 PRESENTATION（这次只动界面分档）",
        "PRESENTATION" in spec,
        "边界结论没写 / 写成了核心",
    )
    c.ok(
        "变更单写清了四条口径（核销 / 改挂账单位 / 已收清 / 客户档案）",
        all(x in spec for x in ("核销", "改挂账单位", "已收清", "客户档案")),
        "口径没写进变更单",
    )
    c.ok(
        "变更单引了用户原话的那条 ref（m01874）",
        "m01874" in spec,
        "没接回台账原话",
    )
    c.ok(
        "登记簿里有这一行（docs/changes/README.md）",
        "CHG-0069" in read(README),
        "README 里没有它 —— 下一个人会以为这条没人在做",
    )
    c.ok(
        "认领里有这一条（docs/AI_WORK_CLAIM.md）",
        "CHG-0069" in read(CLAIM),
        "AI_WORK_CLAIM.md 里没有它",
    )
    c.ok("这条红线配了反向验证脚本", (ROOT / REVERSE).exists(), f"找不到 {REVERSE}")

    # ---- 8. ⛔ 空转即停：判据自己的总项数 ----
    c.ok(
        f"判据总项数 ≥ {MIN_ITEMS}（少了就是判据被删空 —— 空转的检查比没有检查更危险）",
        c.total + 1 >= MIN_ITEMS,
        f"只有 {c.total + 1} 项",
    )

    if "--list" in sys.argv:
        print()
        print("  == 它到底在查什么 ==")
        print("     · 空转闸：扫到的 .kt ≥ 100、十三段函数体抽得出来、判据自己的项数 ≥ 40")
        print("     · 两个谓词：isChargedToArrears 三件事一起看、canSettle 与账本页同口径、canChargeToArrears 一字未动")
        print("     · 三档按钮：已收清 / 核销＋改挂账单位 / 原样两颗，顺序与文案逐字")
        print("     · 整单核销：金额取 arrearsAmount、orderIds 只这一单、settleMode = itemized、没有 orderProductIds")
        print("     · 两道门：没有档案时按 userId 认人、临时货主只给引导不发请求、建完直开核销")
        print("     · 共用件：收款方式与建客户档案各只一份，账本页那次改成委托")
        print("     · AI 侧：AiOrderRef 末尾追加 paymentMethod、新判据排在旧判据之前")
        print("     · 红线：两条反验锚点逐字仍在、后端与 DTO 没动、徽章与原文两颗按钮没动")
        print("     · 文档：提示清单收进新句、变更单 / 登记簿 / 认领 / 反向验证脚本在")

    return c.report("已挂账的单：底部换成核销＋改挂账单位（L-44 / CHG-0069）")


if __name__ == "__main__":
    sys.exit(main())
