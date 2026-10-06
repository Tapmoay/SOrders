# -*- coding: utf-8 -*-
"""红线：订单详情页的「就地改单」—— **只有派单员**在还没结束的单上点哪一块改哪一块，
改完**只告诉经手那张单的司机**，钱一律由后端重算（CHG-0041）。

## 由来（用户 2026-10-05 逐字，语音转写）
「编辑订单不是新增一个订单界面而是在**详情订单界面**……点击对应的状态然后进行编辑」
「如果更改的话，**对应的司机是会收到消息的**说他这个信息已经更改了」

## 为什么必须有一条红线盯着它
这一页原来只是「看」：收货信息卡与商品明细卡全是只读的 InfoRow，改一单要退出去、
回「新增订单」重来一遍。现在它们成了**写入口**（`ui/order/OrderEditInline.kt` 那套输入块），
而写入口的每一处判据都死在"不报错"上：

* **角色门写松一点**：货主打开自己的单，行尾多出一颗「改」—— 界面上什么错都没有，
  他点下去才 403（后端 `Permission.ORDER_EDIT` 只发给 dispatcher）。真机实测（2026-10-05，
  模拟器 5556 货主端）：「改」/「加一件货」一个节点都 dump 不到，那才是**对的**形态。
* **状态门写宽一点**：已送达/已撤销的单也画出输入框，用户填半天、点保存必然 400 ——
  这一页「挂账」那颗按钮就是这么被修过一次的（见 `OrderStatusModel.canChargeToArrears`）。
* **钱**：明细改完的金额必须由后端重算（`resolve_line_total`）。客户端只要自己算一遍，
  两边就会不一致，而"不一致"不会报错 —— 它只会在账本里留下一笔和订单对不上的数。
* **横幅**：这一页**第一次**有结果横幅。删掉它，改单仍然成功、界面仍然刷新，
  用户却永远不知道"司机那边收到消息了没有"。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界解决不了**。被查的全是「松一点 / 窄一点 / 少一句」的形状：
角色门写成只看状态、状态门把终态放进来、客户端自己乘一遍行金额、横幅删掉、本地校验挪到请求之后 ——
这五处**都不会编译失败、也不会让任何单测变红**（后端权限点与金额算法一个字没动）。
边界那一半已经先做了（`OrderEditHost` 一个接口收口状态、行金额只由 `resolve_line_total` 算），
但「界面有没有挂在门上」「横幅写没写司机」只存在于**调用点**，所以判据只能扫结构：
两个门各只有一处、四颗「改」恰好四颗且全在门后、VM 里不许出现 lineTotal、校验必须在请求之前。
运行时那一头交给 _tools/qa/_reverse_verify_detail_inline_edit.py（按条注入破坏）与
模拟器 5554（派单员改地址/改数量/改备注）／5556（货主端 dump 不到「改」）的实测截图。

## 判据（清单全部自己算；路径写错会先在「读到几个文件」那条报红）
1. 「改」的角色门与状态门各只有一处，且只认 `OrderStatusModel.EDITABLE` / `LINE_EDITABLE`。
2. 六个入口（四颗「改」+「加一件货」+ 点整行）每一个都挂在那两个门后面；全仓的「改」调用点只有那四颗。
3. 两个状态集合就是"在途三态"，且与后端 `LINE_EDITABLE_STATUSES` 逐值一致。
4. 保存成功的四句话逐字点名「司机」，并且本页真的把 `vm.actionResult` 画了出来。
5. 客户端只报数量 + 单价；行金额与合计都取服务端的权威值（`lineTotal`），界面不给改金额的框。
6. 本地校验先于请求（电话 / 数量 / 单价不合格就不发请求）；`internalNotes` 原样带回。
7. 写库路径不新增：仍是 `PATCH /orders/{id}` 与 `POST/PATCH/DELETE /order-products`；
   那两个权限点只有 dispatcher 有，货主与司机一个都没有。

⚠️ 注入式反向验证（改坏 → 本脚本必须红，改回 → 绿）：
   python _tools/qa/_reverse_verify_detail_inline_edit.py

用法：python _tools/qa/_check_detail_inline_edit.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 剥 Kotlin 注释的实现只此一份（复用兄弟红线，不抄第二份）。
from _check_pagination_wiring import strip_comments  # noqa: E402
#: 剥 Python 注释 / 文档字符串（换成等长空格、保留行号）。
from _check_single_source import code_only  # noqa: E402
#: 失败行 / 章节标题的形状只此一份（房规）：失败行是 "  [!!]   <标题>" ——
#: _reverse_verify_*.py 正是拿这个前缀去认「这一条被判据抓住了」。
from _check_hints import Checker  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

#: CHG-0041 点名的三个 Kotlin 文件（就是这一页的写入口）。
INLINE = ANDROID / "ui/order/OrderEditInline.kt"
DETAIL_VM = ANDROID / "ui/order/OrderDetailViewModel.kt"
DETAIL = ANDROID / "ui/order/OrderDetailScreen.kt"
#: 判据引用的"权威"：状态集合、端点定义、后端重算、权限点。
STATUS_MODEL = ANDROID / "core/OrderStatusModel.kt"
APIS = ANDROID / "data/remote/api/Apis.kt"
ORDER_PRODUCTS = BACKEND / "app/api/v1/order_products.py"
RBAC = BACKEND / "app/core/rbac.py"

#: 被点名的文件都必须在（少一个就先报红，不静默空转）。
REQUIRED = [INLINE, DETAIL_VM, DETAIL, STATUS_MODEL, APIS, ORDER_PRODUCTS, RBAC]

#: 能改的状态 = 在途三态（后端 orders.update_order 拒终态、order_products 用同一个档）。
IN_FLIGHT = ["PENDING_DISPATCH", "DISPATCHED", "ACCEPTED"]

C = Checker()


def ok(label: str, cond: bool, detail: str = "") -> None:
    C.ok(label, cond, detail)


def section(title: str) -> None:
    C.section(title)


def kt(path: Path) -> str:
    """Kotlin 文件：注释已剥（注释里写"这里只给派单员看"是不算数的）。"""
    return strip_comments(path.read_text(encoding="utf-8")) if path.is_file() else ""


def py(path: Path) -> str:
    """后端文件：注释与文档字符串已剥（保留行号）。"""
    return code_only(path.read_text(encoding="utf-8")) if path.is_file() else ""


#: Kotlin 函数的修饰符可以堆叠（private suspend fun …），且顶层 composable 缩进是 0 而不是 4 ⇒
#: 认「同一缩进上的下一个 fun / @ / }」才既收得到成员函数、也收得到文件末尾那批顶层 composable。
_KT_MODS = r"(?:(?:private|internal|public|protected|override|suspend|inline|operator|open|tailrec)\s+)*"
_KT_FUN = _KT_MODS + "fun "


def kt_section(path: Path, name: str) -> str:
    """Kotlin 某个函数的源码段（到同一缩进上的下一个 fun / @ / } 为止）。空串 = 找不到。"""
    src = kt(path)
    m = re.search(rf"(?m)^([ \t]*){_KT_FUN}{re.escape(name)}\(", src)
    if not m:
        return ""
    pad = re.escape(m.group(1))
    tail = src[m.end():]
    nxt = re.search(rf"(?m)^{pad}(?:{_KT_FUN}|@|\}})", tail)
    return src[m.start(): m.end() + (nxt.start() if nxt else len(tail))]


def braced(src: str, at: int) -> str:
    """从 at 往后第一个 `{` 起按花括号配对取整块。空串 = 没有块 / 不配对。

    判「这个动作是不是在那个 if 里面」只能靠它：`if (canEditLines)` 在屏上出现 3 次，
    单纯 `in src` 会指到别的那一段上（那是**假绿**：动作其实在门外）。
    """
    i = src.find("{", at)
    if i < 0:
        return ""
    depth = 0
    for j in range(i, len(src)):
        ch = src[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[i: j + 1]
    return ""


def guarded(src: str, gate: str, inner: str) -> bool:
    """inner 是否出现在 gate 后面那个花括号块里（gate 出现多次时，任何一处算数）。"""
    start = 0
    while True:
        pos = src.find(gate, start)
        if pos < 0:
            return False
        if inner in braced(src, pos + len(gate)):
            return True
        start = pos + 1


def kotlin_set(src: str, name: str) -> list[str]:
    """`val NAME: Set<String> = setOf(…)` 里的那些字符串（解析不出来＝空表）。"""
    m = re.search(rf"val {re.escape(name)}: Set<String> = setOf\(([^)]*)\)", src)
    return re.findall(r'"([A-Z_]+)"', m.group(1)) if m else []


def py_status_tuple(src: str, name: str) -> list[str]:
    """`NAME = (OrderStatus.X, OrderStatus.Y, …)` 里的那些枚举值（解析不出来＝空表）。"""
    m = re.search(rf"(?m)^{re.escape(name)} = \(([^)]*)\)", src)
    return re.findall(r"OrderStatus\.([A-Z_]+)", m.group(1)) if m else []


def role_block(src: str, role: str) -> str:
    """`"<role>": frozenset({ … })` 那一块（判某个权限点是不是只发给这个角色）。"""
    m = re.search(rf'"{re.escape(role)}": frozenset\(', src)
    return braced(src, m.end()) if m else ""


def main() -> int:
    section("0. 反空转：读到几个文件")
    missing = [str(p.relative_to(ROOT)) for p in REQUIRED if not p.is_file()]
    ok("CHG-0041 点名的文件全在（7 个）", not missing, "缺：" + ", ".join(missing))
    order_mods = sorted((ANDROID / "ui/order").glob("*.kt"))
    ok("ui/order 下的模块 >= 3 个（防路径写错后空转）", len(order_mods) >= 3, f"实际 {len(order_mods)}")

    screen = kt(DETAIL)
    vm = kt(DETAIL_VM)
    inline = kt(INLINE)
    prods = py(ORDER_PRODUCTS)
    status_src = kt(STATUS_MODEL)

    # ---- ① 谁看得到「改」--------------------------------------------------
    section("① 谁看得到「改」：角色门 + 状态门（ui/order/OrderDetailScreen.kt）")
    gate_info = "val canEditInfo = role == Role.DISPATCHER && order.status in OrderStatusModel.EDITABLE"
    gate_lines = "val canEditLines = role == Role.DISPATCHER && order.status in OrderStatusModel.LINE_EDITABLE"
    ok(
        "canEditInfo 逐字：role == Role.DISPATCHER && OrderStatusModel.EDITABLE",
        gate_info in screen,
        "角色门被删或被改宽（例如 role != Role.DRIVER）＝货主/司机的界面上也会出现「改」",
    )
    ok(
        "canEditLines 逐字：role == Role.DISPATCHER && OrderStatusModel.LINE_EDITABLE",
        gate_lines in screen,
        "明细门同样只能是派单员；状态那一半必须来自 OrderStatusModel（本页不许另写一套）",
    )
    ok(
        "两个门各只有一处（本页不另写第二套状态判断）",
        screen.count("val canEditInfo =") == 1 and screen.count("val canEditLines =") == 1,
        f"canEditInfo={screen.count('val canEditInfo =')} canEditLines={screen.count('val canEditLines =')}",
    )
    n_gated = screen.count("if (canEditInfo) EditHint(")
    n_any = screen.count("EditHint(")
    ok(
        "四颗「改」全挂在 canEditInfo 后面（恰好 4 处）",
        n_gated == 4 and n_any == 4,
        f"带门的 {n_gated} 颗 / 总共 {n_any} 颗 —— 差几颗就是有几颗漏给了别的角色",
    )
    callers = sorted(
        (p.relative_to(ANDROID).as_posix(), kt(p).count("EditHint("))
        for p in ANDROID.rglob("*.kt")
        if kt(p).count("EditHint(") > 0
    )
    ok(
        "全仓「改」的调用点只有详情页那 4 颗（别处冒出第 5 颗＝那个页面的人也能看到它）",
        callers == [("ui/order/OrderDetailScreen.kt", 4), ("ui/order/OrderEditInline.kt", 1)],
        f"实际 {callers}（OrderEditInline.kt 那 1 处是函数定义）",
    )
    ok(
        "「加一件货」在 canEditLines 里面",
        guarded(screen, "if (canEditLines)", "edit.openLinePicker()"),
        "门被去掉＝货主与司机也能往单里加货",
    )
    ok(
        "点整行改明细也要过 canEditLines",
        "if (canEditLines) Modifier.clickable { edit.startLineEdit(line) } else Modifier," in screen,
        "行本身看不出可点，门写在这里；掉了就是三端都能点开行内编辑",
    )
    ok(
        "行内编辑块只在 canEditLines 且正是这一行时挂",
        "if (canEditLines && edit.editingLineId == line.id) {" in screen,
        "少了前半截＝只要编辑态还在，任何角色打开这一页都会看到输入框",
    )

    # ---- ② 六个入口 -------------------------------------------------------
    section("② 点哪一块改哪一块：四个编辑块 + 六个入口（用户要的形态）")
    for field in ("ADDRESS", "DONGJIA", "BOSS", "REMARK"):
        ok(
            f"收货信息有一块能改：edit.startEdit(OrderEditField.{field})",
            f"edit.startEdit(OrderEditField.{field})" in screen,
            "四行（收货地址 / 收货人 / 下单人 / 备注）各一颗「改」，少一行就是那一行改不了",
        )
    ok("地址块：编辑态换成 AddressEditBlock(edit)", "AddressEditBlock(edit)" in screen)
    ok(
        "收货人块：姓名与电话一起改（ContactEditBlock(edit, \"收货人\", …)）",
        'ContactEditBlock(edit, "收货人", OrderEditField.DONGJIA_NAME, OrderEditField.DONGJIA_PHONE)' in screen,
        "只改电话会让那一行半新半旧（后端本来也是一条 PATCH 收这两个字段）",
    )
    ok(
        "下单人块：ContactEditBlock(edit, \"下单人\", …)",
        'ContactEditBlock(edit, "下单人", OrderEditField.BOSS_NAME, OrderEditField.BOSS_PHONE)' in screen,
    )
    ok("备注块：RemarkEditBlock(edit)", "RemarkEditBlock(edit)" in screen)
    ok(
        "明细行：编辑态换成 ProductLineEditBlock(edit, line)",
        "ProductLineEditBlock(edit, line)" in screen,
        "少这一块＝「点某一行可以改数量与单价」是一句空话",
    )
    ok(
        "「点某一行可以改数量与单价」这句只画给 canEditLines 的人",
        guarded(screen, "if (canEditLines)", "点某一行可以改数量与单价"),
        "行本身看不出可点，这句话是入口的可见性兜底；画给所有人＝先告诉他再拒绝他",
    )
    ok(
        "空明细的引导句只在 canEditLines 且这一单真的没有货时画",
        "if (canEditLines && order.orderProducts.isEmpty()) {" in screen,
    )

    # ---- ③ 横幅与文案 -----------------------------------------------------
    section("③ 保存完要看得见「司机收到消息」：本页第一次有结果横幅")
    ok(
        "本页真的把 vm.actionResult 画出来了",
        "vm.actionResult?.let { msg ->" in screen,
        "删掉它：改单照样成功、界面照样刷新，用户永远不知道司机收到消息没有",
    )
    ok(
        "改收货信息的成功文案逐字点名司机",
        'actionResult = "已经改好，司机那边会收到一条消息"' in vm,
        "用户 2026-10-05 要的就是这一句",
    )
    ok(
        "改一件货的成功文案逐字点名司机",
        'actionResult = "这件货改好了，司机那边会收到一条消息"' in vm,
    )
    ok(
        "删掉一件货的成功文案逐字点名司机",
        'actionResult = "这一件货删掉了，司机那边会收到一条消息"' in vm,
    )
    ok(
        "加货的文案说清加了几件、并点名司机",
        'actionResult = "加了 " + added + " 件货，司机那边会收到一条消息"' in vm,
        "批量加货是逐行请求，件数必须自己报（用户核对的就是这个数）",
    )
    ok(
        "文案是往 actionResult 里写，不是直接弹一个 Toast / 写死一句",
        "actionResult = " in vm and "Toast" not in vm,
        "写死一句＝改失败了也显示成功",
    )

    # ---- ④ 钱一律由后端算 -------------------------------------------------
    section("④ 钱一律由后端算（客户端只报数量 + 单价）")
    ok(
        "saveLine 报的是数量 + 单价两个值",
        "OrderProductUpdateRequest(quantity = qty, unitPrice = price)" in vm,
        "只报单价时后端按旧数量算，会出现「改了价、总额没动」这种没人看得懂的结果",
    )
    ok(
        "客户端不自己算行金额（VM 里没有 lineTotal / line_total）",
        "lineTotal" not in vm and "line_total" not in vm,
        "自算一遍＝界面上的数与后端权威值可以不一致，而这不报错",
    )
    seg_line_block = kt_section(INLINE, "ProductLineEditBlock")
    n_boxes = seg_line_block.count("EditBox(")
    ok(
        "行内编辑只有数量与单价两个输入框（界面不给改金额的框）",
        n_boxes == 2,
        f"实际 {n_boxes} 个 —— 多一个金额框＝用户以为能直接改钱",
    )
    ok(
        "屏上的合计仍取服务端的行小计之和（不是单价 × 数量）",
        "val total = order.orderProducts.sumOf { moneyToDouble(it.lineTotal) }" in screen,
        "前端自算合计＝与订单/账本金额对不上",
    )
    ok(
        "后端行金额仍走唯一算法 resolve_line_total",
        "op.line_total = resolve_line_total(new_up, new_qty, body.line_total)" in prods,
        "重算只有这一处（backend/app/services/order_flow.py::resolve_line_total）",
    )
    ok(
        "后端只给一个值时也按另一个的现值重算",
        "new_up = body.unit_price if body.unit_price is not None else op.unit_price" in prods
        and "new_qty = body.quantity if body.quantity is not None else op.quantity" in prods,
    )

    # ---- ⑤ 先校验再发请求 -------------------------------------------------
    section("⑤ 本地校验先于请求（不合格就不发请求）")
    seg_edit = kt_section(DETAIL_VM, "saveEdit")
    ok("saveEdit 段找得到", bool(seg_edit), "函数改名了就要同步改这条判据")
    i_p1 = seg_edit.find("InputRules.phoneError(phoneDraft)")
    i_p2 = seg_edit.find("InputRules.phoneError(bossDraft)")
    i_req = seg_edit.find("container.repo.updateOrder(")
    ok(
        "两个电话校验都在发请求之前",
        -1 < i_p1 < i_p2 < i_req,
        f"收货人电话={i_p1} 下单人电话={i_p2} 请求={i_req}（-1＝找不到）",
    )
    ok(
        "六个字段全量提交（地址 / 两个电话 / 两个名字 / 备注）",
        all(
            k in seg_edit
            for k in (
                "addressDetail = draft(OrderEditField.ADDRESS_DETAIL).trim()",
                "val phoneDraft = draft(OrderEditField.DONGJIA_PHONE).trim()",
                "contactDongjiaPhone = phoneDraft",
                "val bossDraft = draft(OrderEditField.BOSS_PHONE).trim()",
                "contactBossPhone = bossDraft",
                "contactDongjiaName = draft(OrderEditField.DONGJIA_NAME).trim()",
                "contactBossName = draft(OrderEditField.BOSS_NAME).trim()",
                "remark = draft(OrderEditField.REMARK_TEXT).trim()",
            )
        ),
        "PATCH 是「给什么改什么」，其余字段必须带着当前值回去",
    )
    ok(
        "internalNotes 原样带回（改单不许顺手清掉内部备注）",
        "internalNotes = o.internalNotes," in seg_edit,
    )
    seg_line = kt_section(DETAIL_VM, "saveLine")
    ok("saveLine 段找得到", bool(seg_line))
    i_qty = seg_line.find('editError = "数量要填一个大于 0 的整数"')
    i_price = seg_line.find('editError = "单价要填数字"')
    i_req2 = seg_line.find("container.repo.updateOrderProduct(")
    ok(
        "数量与单价的校验都在发请求之前",
        -1 < i_qty < i_price < i_req2,
        f"数量={i_qty} 单价={i_price} 请求={i_req2}（-1＝找不到）",
    )
    ok(
        "失败就在地显示后端原文（不假装成功）",
        seg_edit.count("editError = toApiException(e).message") == 1
        and seg_line.count("editError = toApiException(e).message") == 1,
    )
    ok(
        "红字由 OrderEditInline 的 FormErrorLine 画（就地，不弹窗）",
        "FormErrorLine(error)" in inline,
    )
    ok(
        "保存中防连点（busy 时按钮写「保存中…」）",
        'Text(if (busy) "保存中…" else saveLabel)' in inline,
        "一次往返里再点一次＝改两遍，司机收到两条",
    )

    # ---- ⑥ 写库路径不新增 -------------------------------------------------
    section("⑥ 写库路径不新增：仍是既有端点（本次零后端改动）")
    ok(
        "改单走既有 updateOrder（不新开一条写库路径）",
        "container.repo.updateOrder(" in vm,
        "另起一个只改地址的端点＝同一件事两条路，迟早只改一边",
    )
    ok(
        "改行 / 删行 / 加货走既有的三个方法",
        "container.repo.updateOrderProduct(" in vm
        and "container.repo.deleteOrderProduct(lineId)" in vm
        and "container.repo.addOrderProduct(" in vm,
    )
    apis = kt(APIS)
    for anno, name in (
        ('@PATCH("orders/{orderId}")', "updateOrder"),
        ('@PATCH("order-products/{lineId}")', "updateOrderProduct"),
        ('@DELETE("order-products/{lineId}")', "deleteOrderProduct"),
    ):
        ok(f"{name} 仍是 {anno}", anno in apis)
    ok(
        "order-products 只有三个写端点（POST / PATCH / DELETE 各一个）",
        prods.count("@router.post(") == 1
        and prods.count("@router.patch(") == 1
        and prods.count("@router.delete(") == 1,
        f"post={prods.count('@router.post(')} patch={prods.count('@router.patch(')} delete={prods.count('@router.delete(')}",
    )

    # ---- ⑦ 权限点 ---------------------------------------------------------
    section("⑦ 角色门对得上服务端的权限点（backend/app/core/rbac.py）")
    rb = py(RBAC)
    disp = role_block(rb, "dispatcher")
    ok(
        "dispatcher 有 ORDER_EDIT 与 ORDER_PRODUCT_EDIT",
        "Permission.ORDER_EDIT," in disp and "Permission.ORDER_PRODUCT_EDIT," in disp,
        "解析不到 dispatcher 那一格＝这条判据在空转",
    )
    for role in ("shipper", "driver"):
        blk = role_block(rb, role)
        # ⚠️ CHG-0057（L-27）：货主多了一个**只改联系信息**的权限点
        #    `ORDER_EDIT_CONTACT` —— 而 "Permission.ORDER_EDIT" 正好是它的**前缀**，
        #    原来那条断言（"Permission.ORDER_EDIT" not in blk）加了新点之后必然假红。
        #    改成先把 ORDER_EDIT_CONTACT 从这一格的字面里抠掉，再看剩下的里有没有
        #    ORDER_EDIT（整单改）与 ORDER_PRODUCT_EDIT（改货）—— 意图一字未改：
        #    货主 / 司机改不动单据本体与货物，货主只多那一扇补联系信息的门。
        blob = blk.replace("Permission.ORDER_EDIT_CONTACT", "")
        full_edit = "Permission.ORDER_EDIT" in blob
        product_edit = "Permission.ORDER_PRODUCT_EDIT" in blob
        contact_edit = "Permission.ORDER_EDIT_CONTACT" in blk
        if role == "shipper":
            ok(
                "shipper 改不动单据本体与货物（只有 ORDER_EDIT_CONTACT 那一个联系信息的门）",
                bool(blk) and not full_edit and not product_edit and contact_edit,
                "客户端放行、后端 403，用户点下去才知道不行；⛔ 也不许顺手把 ORDER_EDIT 给他",
            )
        else:
            ok(
                f"{role} 一个字都改不了（三个改单权限点一个都没有）",
                bool(blk) and not full_edit and not product_edit and not contact_edit,
                "客户端放行、后端 403，用户点下去才知道不行",
            )

    # ---- ⑧ 能改哪些状态 ---------------------------------------------------
    section("⑧ 能改哪些状态：就是「在途三态」，且与后端逐值一致")
    editable = kotlin_set(status_src, "EDITABLE")
    line_editable = kotlin_set(status_src, "LINE_EDITABLE")
    backend_le = py_status_tuple(prods, "LINE_EDITABLE_STATUSES")
    ok(
        "EDITABLE 逐值 = 在途三态（PENDING_DISPATCH / DISPATCHED / ACCEPTED）",
        sorted(editable) == sorted(IN_FLIGHT),
        f"实际 {editable}",
    )
    ok(
        "客户端的 LINE_EDITABLE 与后端 LINE_EDITABLE_STATUSES 逐值一致",
        bool(line_editable) and line_editable == backend_le,
        f"客户端 {line_editable} / 后端 {backend_le} —— 宽的那一边就是把「点下去必然 400」摆在用户面前",
    )
    ok(
        "后端那个状态元组只有一处定义",
        prods.count("LINE_EDITABLE_STATUSES = (") == 1,
        f"实际 {prods.count('LINE_EDITABLE_STATUSES = (')} 处",
    )
    ok(
        "能改的状态里没有终态（已送达 / 已撤销 / 已退货）",
        not ({"DELIVERED", "CANCELLED", "RETURNED"} & (set(editable) | set(line_editable) | set(backend_le))),
        f"EDITABLE={editable} LINE_EDITABLE={line_editable} 后端={backend_le}",
    )

    print("\n" + "=" * 60)
    if C.fails:
        print(f"❌ {len(C.fails)} 项不通过（通过 {C.n_ok} 项）：")
        for label, _ in C.fails:
            print(f"   - {label}")
        return 1
    print(f"✅ 全部 {C.n_ok} 项通过：只有派单员能就地改单，改完点名司机，钱由后端重算。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
