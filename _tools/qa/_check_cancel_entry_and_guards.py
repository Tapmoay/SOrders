"""撤销入口与防连点（L-12 + L-13 + L-14，CHG-0049）静态判据：三处撤销入口各归其位、
一次网络往返只发一遍、失败原因画在弹层里、撤回的落点文案与后端同源。

## 用户原话（2026-10-06）
「派单中我们也**可以撤销**，是不是」；「我点了那个撤销，**失败**了……我点了一次，没反应，
我又点了一次，它就变成失败了」；「如果是**撤回派单**的话，它是回到**待派单**，不是回到派单中的哈，
这个应该是文案错了吧」

## 机制（这条链路上每一段各由谁负责）
| 段 | 在哪 | 怎么规定的 |
| --- | --- | --- |
| 谁看见撤销 | android/.../core/Capabilities.kt | order:cancel_shipper（货主）/ order:cancel_dispatcher（派单员，BYPASS 角色）；两处都还要受 OrderStatusModel.CANCELLABLE 约束 |
| 从哪进 | 派单员订单列表卡片 / 待派单池那一档 / 货主列表卡片 / 订单详情 | 四条路都走 vm.openCancel(...)；详情页的门问能力表（⛔ 不再写死 role == Role.SHIPPER） |
| 只发一遍 | 四个 VM 的 confirmCancel / cancel 首行 | if (acting) return；四处弹窗的确认键 enabled = !vm.acting（共用件 DangerConfirmDialog 透传） |
| 失败画哪 | 派单池 dialogError / 派单员订单列表 dialogError / 货主 cancelError / 详情页 cancelError | 画在**弹层自己**里（FormErrorLine）；⛔ 不许写页面级 error（那会把整页换成 ErrorView，弹层还开着、列表先没了） |
| 撤回的落点 | backend/app/services/order_flow.py::recall_dispatch | status=OrderStatus.PENDING_DISPATCH ⇒ 界面文案必须说「回到待派单池」 |

## ⛔ 这条判据证不了什么
1. **不证真机上点得动**：按钮在卡片上挤不挤、弹窗会不会挡住列表、连点两下是不是真的只发一遍 ——
   静态判据只证明「守卫写在那儿」，acting 的时序得靠人点（乃至抓包）。
2. **不证后端真的拒第二遍**：这里只证客户端不发第二遍；后端幂等/400 的证据在 backend/tests/。
3. **不证权限面收敛**：「派单员能不能撤**别人**名下的单」这层语义由后端 cancel_pending 判，
   本判据只读能力表里那两个键在不在、派单员还在不在 BYPASS_ROLES。
4. **不证文案与状态机长期同源**：这里比对的是 recall_dispatch 里那一行赋值与界面字面量；
   后端将来改落点而界面没跟上，只有这条会红。

R4-BOUNDARY-JUSTIFICATION: 这 46 条里有两类是**边界解决不了**、只能靠静态判据钉住的：
①「⛔ 失败不许写页面级 error」—— dialogError / cancelError / 页面级 error 是**同一个类里的三个 var**，
写错哪一个都能编译、后端也照样回错，只有在真机上才表现为"弹层一直在、点了没反应"
（2026-09-23 真机抓到过）；②「四处守卫必须都在」—— 漏掉任何一处的 if (acting) return 都不会让
任何测试变红，只会让用户在慢网下**撤两遍**（撤销是不可逆动作，第二遍必然被后端拒）。
反向破坏用例见 _tools/qa/_reverse_verify_cancel_entry_and_guards.py（25 条注入，逐条指明本文件哪条该红）。

## 判据（46 条，五组：入口 / 防连点 / 失败落点 / 文案 / 边界）
用法：python _tools/qa/_check_cancel_entry_and_guards.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"
DISP_VM = AND / "ui" / "dispatcher" / "DispatcherOrdersViewModel.kt"
DISP_SCREEN = AND / "ui" / "dispatcher" / "DispatcherOrdersScreen.kt"
POOL_VM = AND / "ui" / "dispatcher" / "DispatcherPoolViewModel.kt"
POOL_SCREEN = AND / "ui" / "dispatcher" / "DispatcherPoolScreen.kt"
SHIP_VM = AND / "ui" / "shipper" / "ShipperOrdersViewModel.kt"
SHIP_SCREEN = AND / "ui" / "shipper" / "ShipperOrdersScreen.kt"
DETAIL_VM = AND / "ui" / "order" / "OrderDetailViewModel.kt"
DETAIL = AND / "ui" / "order" / "OrderDetailScreen.kt"
COMP = AND / "ui" / "common" / "Components.kt"
STATUS = AND / "core" / "OrderStatusModel.kt"
CAPS = AND / "core" / "Capabilities.kt"
FLOW = ROOT / "backend" / "app" / "services" / "order_flow.py"

#: 「正在提交」的守卫（四个 VM 各一行，注释文字各不相同 ⇒ 只判前缀）。
GUARD = "if (acting) return"
#: 弹窗确认键的守卫（四处各一行）。
BTN_GUARD = "enabled = !vm.acting,"
#: 撤销确认弹窗的正文（四个弹窗里这一句**逐字相同** ⇒ 用它当锚点取「这个弹窗」的范围）。
CANCEL_TITLE = 'Text("确认撤销该订单？撤销后货主将在「已撤销」中看到该订单。")'
#: 后端撤回派单的落点（order_flow.recall_dispatch 里那一行）。
FLOW_STATUS = "status=OrderStatus.PENDING_DISPATCH,"


class Checker:
    def __init__(self) -> None:
        self.total = 0
        self.fails: list[str] = []

    def ok(self, label: str, cond: bool, detail: str = "") -> bool:
        self.total += 1
        if not cond:
            self.fails.append("  [FAIL] " + label + (" —— " + detail if detail else ""))
        return bool(cond)

    def present(self, label: str, text: str, pattern: str, where: str = "") -> bool:
        hit = re.search(pattern, text, re.M) is not None
        return self.ok(label, hit, "没找到 " + pattern + ("（在 " + where + "）" if where else ""))

    def absent(self, label: str, text: str, pattern: str, where: str = "") -> bool:
        hit = re.search(pattern, text, re.M) is not None
        return self.ok(label, not hit, "却找到了 " + pattern + ("（在 " + where + "）" if where else ""))


def read(p: Path) -> str:
    if not p.exists():
        print("❌ 找不到文件：" + str(p))
        raise SystemExit(2)
    return p.read_text(encoding="utf-8", errors="replace")


def code_only(text: str) -> str:
    """剥掉块注释与行注释（**保留行号**：注释里的字不算证据）。"""
    def _blank(m: re.Match[str]) -> str:
        return "\n" * m.group(0).count("\n")

    out = re.sub(r"/\*.*?\*/", _blank, text, flags=re.S)
    return "\n".join(ln[: ln.find("//")] if "//" in ln else ln for ln in out.split("\n"))


def after(text: str, needle: str, n: int = 600) -> str:
    """needle 之后 n 个字符的窗口（找不到就是空串 ⇒ 调用方的判据自然变红）。"""
    i = text.find(needle)
    return text[i : i + n] if i >= 0 else ""


def region(text: str, start: str, stop: str) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(stop, i + len(start))
    return text[i:j] if j > 0 else text[i:]


def kt_composable(text: str, name: str) -> str:
    """一个 @Composable 函数的整段（到下一个 @Composable 为止）。"""
    key = "fun " + name + "("
    i = text.find(key)
    if i < 0:
        return ""
    j = text.find("\n@Composable", i + len(key))
    return text[i:j] if j > 0 else text[i:]


def main() -> int:
    disp_vm = code_only(read(DISP_VM))
    disp_screen = code_only(read(DISP_SCREEN))
    pool_vm = code_only(read(POOL_VM))
    pool_screen = code_only(read(POOL_SCREEN))
    ship_vm = code_only(read(SHIP_VM))
    ship_screen = code_only(read(SHIP_SCREEN))
    detail_vm = code_only(read(DETAIL_VM))
    detail = code_only(read(DETAIL))
    comp = code_only(read(COMP))
    status = code_only(read(STATUS))
    caps = code_only(read(CAPS))
    flow = read(FLOW)

    # 「这个弹窗」的范围：用正文那一句当锚点往后取窗口（同一句在几个屏里都有，取的是各自的文件）。
    pool_cancel = after(pool_screen, CANCEL_TITLE, 700)
    disp_cancel = after(disp_screen, CANCEL_TITLE, 700)
    ship_cancel = after(ship_screen, "DangerConfirmDialog(", 500)
    detail_cancel = after(detail, 'Text("确认撤销订单？")', 800)
    dlg = kt_composable(comp, "DangerConfirmDialog")
    recall = region(flow, "def recall_dispatch(", "\ndef ")

    # 三处「撤销门」的窗口（门里只能认状态模型；裸字面量在这里出现 = 用了第二套判据）。
    disp_gate = region(disp_screen, "if (order.status in OrderStatusModel.CANCELLABLE) {", "vm.openCancel(order)")
    ship_gate = region(ship_screen, "if (order.status in OrderStatusModel.CANCELLABLE) {", "vm.openCancel(order)")
    detail_gate = region(detail, "val canCancel = Capabilities.can(", "OutlinedButton(")

    c = Checker()

    # ---------- 一、入口（L-12：派单员也能撤） ----------
    c.present("[入口] 派单员订单列表有「可撤销」的门（OrderStatusModel.CANCELLABLE）",
              disp_screen, r"if \(order\.status in OrderStatusModel\.CANCELLABLE\) \{",
              "DispatcherOrdersScreen")
    c.present("[入口] 派单员订单列表的撤销按钮走 vm.openCancel(order)",
              disp_screen, r"TextButton\(onClick = \{ vm\.openCancel\(order\) \}\) \{",
              "DispatcherOrdersScreen")
    c.present("[入口] 待派单池那一档的撤销入口还在（vm.openCancel(order.id)）",
              pool_screen, r"vm\.openCancel\(order\.id\)", "DispatcherPoolScreen")
    c.present("[入口] 货主列表卡片撤销入口走 vm.openCancel(order)",
              ship_screen, r"onClick = \{ vm\.openCancel\(order\) \},")
    c.absent("[入口] ⛔ 货主列表不再直接改 cancelTarget（入口要顺手清错误）",
             ship_screen, r"vm\.cancelTarget = order")
    c.ok("[入口] 派单员订单列表新增了撤销弹窗（showCancelDialog + vm.confirmCancel）",
         "if (vm.showCancelDialog) {" in disp_screen and "vm.confirmCancel()" in disp_screen,
         "DispatcherOrdersScreen 里没有撤销弹窗")
    c.absent("[入口] 详情页撤销门不再写死 role == Role.SHIPPER",
             detail, r"role == Role\.SHIPPER && order\.status in OrderStatusModel\.CANCELLABLE")
    c.present("[入口] 详情页撤销门问能力表（order:cancel_shipper）",
              detail, r'Capabilities\.can\(role\.key, "order:cancel_shipper"\)')
    c.present("[入口] 详情页撤销门问能力表（order:cancel_dispatcher）",
              detail, r'Capabilities\.can\(role\.key, "order:cancel_dispatcher"\)')
    c.present("[入口] 详情页按能力判据仍受可撤销状态约束",
              detail, r"if \(canCancel && order\.status in OrderStatusModel\.CANCELLABLE\) \{")
    c.present("[入口] 详情页导入了 Capabilities",
              detail, r"import com\.tapmoay\.sorders\.core\.Capabilities")
    c.ok("[入口] 三处撤销门都点名状态模型（门里不写裸状态字面量）",
         all("OrderStatusModel.CANCELLABLE" in g for g in (disp_gate, ship_gate, detail_gate))
         and all(re.search(r'"(PENDING_DISPATCH|DISPATCHED)"', g) is None
                 for g in (disp_gate, ship_gate, detail_gate)),
         "撤销门里用了裸状态字面量，或没点 OrderStatusModel.CANCELLABLE")

    # ---------- 二、防连点（L-13：一次网络往返只发一遍） ----------
    for label, text, sig in (
        ("[防连点] 派单池 confirmCancel 有 if (acting) return", pool_vm, "fun confirmCancel() {"),
        ("[防连点] 货主 confirmCancel 有 if (acting) return", ship_vm, "fun confirmCancel() {"),
        ("[防连点] 详情页 cancel 有 if (acting) return", detail_vm, "fun cancel() {"),
        ("[防连点] 派单员订单列表 confirmCancel 有 if (acting) return", disp_vm, "fun confirmCancel() {"),
    ):
        c.ok(label, GUARD in after(text, sig), "确认函数开头没有 " + GUARD)
    c.ok("[防连点] 派单池撤销弹窗确认键带 enabled = !vm.acting",
         BTN_GUARD in pool_cancel, "弹窗确认键没有 disabled 态")
    c.ok("[防连点] 派单员订单列表撤销弹窗确认键带 enabled = !vm.acting",
         BTN_GUARD in disp_cancel, "弹窗确认键没有 disabled 态")
    c.ok("[防连点] 详情页撤销弹窗确认键带 enabled = !vm.acting",
         BTN_GUARD in detail_cancel, "弹窗确认键没有 disabled 态")
    c.ok("[防连点] 货主撤销弹窗传了 enabled = !vm.acting",
         BTN_GUARD in ship_cancel, "DangerConfirmDialog 调用里没有 enabled")
    c.present("[防连点] 共用件 DangerConfirmDialog 支持 enabled",
              dlg, r"^    enabled: Boolean = true,$", "Components.kt::DangerConfirmDialog")
    c.present("[防连点] 共用件把 enabled 透传给确认键",
              dlg, r"^                enabled = enabled,$", "Components.kt::DangerConfirmDialog")

    # ---------- 三、失败落点（L-13：错误画在弹层自己里面） ----------
    c.ok("[落点] 派单池撤销失败写弹层错误（dialogError）",
         "dialogError = toApiException(e).message" in after(pool_vm, "fun confirmCancel() {"),
         "catch 里没写 dialogError")
    c.ok("[落点] 派单池打开撤销弹层清掉上一次的失败",
         "dialogError = null" in after(pool_vm, "fun openCancel(orderId: Long) {", 200),
         "openCancel 没有清 dialogError")
    c.ok("[落点] 派单池撤销弹窗画错误行",
         "FormErrorLine(vm.dialogError)" in pool_cancel, "弹窗里没有 FormErrorLine(vm.dialogError)")
    c.ok("[落点] 货主撤销失败写弹层错误（cancelError）",
         "cancelError = toApiException(e).message" in after(ship_vm, "fun confirmCancel() {"),
         "catch 里没写 cancelError")
    c.ok("[落点] 货主打开与关闭撤销弹层都清 cancelError",
         "cancelError = null" in after(ship_vm, "fun openCancel(order: OrderDto) {", 200)
         and "cancelError = null" in after(ship_vm, "fun dismissCancel() {", 200),
         "openCancel / dismissCancel 没有清 cancelError")
    c.ok("[落点] 货主撤销弹窗把错误传给共用件",
         "error = vm.cancelError," in ship_screen, "DangerConfirmDialog 调用里没有 error")
    c.ok("[落点] 详情页撤销失败写弹层错误（cancelError）",
         "cancelError = toApiException(e).message" in after(detail_vm, "fun cancel() {"),
         "catch 里没写 cancelError")
    c.ok("[落点] 详情页撤销弹窗画错误行",
         "FormErrorLine(vm.cancelError)" in detail_cancel, "弹窗里没有 FormErrorLine(vm.cancelError)")
    c.ok("[落点] 详情页打开撤销弹层时清掉上一次的失败",
         "vm.cancelError = null" in after(detail, "onCancelClick = {", 120),
         "onCancelClick 没有清 cancelError")
    c.ok("[落点] 派单员订单列表撤销失败写弹层错误（dialogError）",
         "dialogError = toApiException(e).message" in after(disp_vm, "fun confirmCancel() {"),
         "catch 里没写 dialogError")
    c.ok("[落点] 派单员订单列表撤销弹窗画错误行",
         "FormErrorLine(vm.dialogError)" in disp_cancel, "弹窗里没有 FormErrorLine(vm.dialogError)")
    c.ok("[落点] ⛔ 四条撤销路都不再把失败写成页面级 error",
         all(re.search(r"^\s+error = toApiException", s, re.M) is None
             for s in (after(pool_vm, "fun confirmCancel() {"),
                       after(ship_vm, "fun confirmCancel() {"),
                       after(detail_vm, "fun cancel() {"),
                       after(disp_vm, "fun confirmCancel() {"))),
         "撤销的 catch 里写了页面级 error（整页会变成 ErrorView）")
    c.ok("[落点] ⛔ 撤销弹窗不引用页面级 vm.error（只画弹层自己的字段）",
         "vm.error" not in pool_cancel and "vm.error" not in disp_cancel
         and "vm.error" not in detail_cancel and "vm.error" not in ship_cancel,
         "撤销弹窗里画了页面级 vm.error")

    # ---------- 四、文案（L-14：撤回回到待派单） ----------
    c.ok("[文案] 派单员撤回弹窗说「回到待派单池」",
         'Text("撤回后订单回到待派单池（等重新派单），司机端将收到撤回通知。")' in disp_screen,
         "撤回弹窗的正文还是旧的")
    c.ok("[文案] 撤回成功回执说「回到待派单池」",
         'actionResult = "已撤回派单，订单回到待派单池（等重新派单）"' in disp_vm,
         "撤回回执还是「回到派单中」")
    c.absent("[文案] ⛔ 界面里不再有「订单回到派单中」这句错话",
             disp_screen + "\n" + disp_vm, r"订单回到派单中|回到「派单中」")
    c.present("[文案-后端同源] 撤回的落点确实是待派单（后端写 PENDING_DISPATCH）",
              recall, re.escape(FLOW_STATUS), "order_flow.py::recall_dispatch")
    c.ok("[文案] 撤销弹窗说「已撤销」（撤销与撤回是两件事，单子的去处不同）",
         CANCEL_TITLE in pool_screen and CANCEL_TITLE in disp_screen,
         "撤销弹窗没有说清单子去哪了")
    c.ok("[文案] 撤销的确认键写「确认撤销」",
         'Text("确认撤销")' in pool_screen and 'Text("确认撤销")' in disp_screen,
         "撤销确认键的字不对")

    # ---------- 五、边界与反空转 ----------
    c.ok("[反空转] 五份界面/VM 还是完整的文件（行数下限）",
         len(disp_vm.split("\n")) >= 380 and len(disp_screen.split("\n")) >= 350
         and len(pool_screen.split("\n")) >= 550 and len(ship_screen.split("\n")) >= 300
         and len(detail.split("\n")) >= 1900 and len(comp.split("\n")) >= 1200,
         "文件被截断或大面积删改")
    c.ok("[边界] 状态集合没被改宽（CANCELLABLE 仍逐字两个值）",
         re.search(r'val CANCELLABLE: Set<String> = setOf\("PENDING_DISPATCH", "DISPATCHED"\)',
                   status) is not None,
         "CANCELLABLE 的取值被动过")
    c.ok("[边界] 能力表里两个撤销权限都在，且派单员仍是绕过角色",
         '"order:cancel_shipper"' in caps and '"order:cancel_dispatcher"' in caps
         and 'val BYPASS_ROLES: Set<String> = setOf("dispatcher")' in caps,
         "能力表 / BYPASS_ROLES 被动过")
    c.ok("[边界] 四条撤销路都走同一个仓储方法（repo.cancelOrder）",
         all("repo.cancelOrder(" in s for s in (disp_vm, pool_vm, ship_vm, detail_vm)),
         "有撤销路没走 repo.cancelOrder")
    c.absent("[边界] ⛔ 没给撤销接口加参数（只带一个 id）",
             disp_vm + pool_vm + ship_vm + detail_vm, r"repo\.cancelOrder\([^)\n]*,")

    if c.fails:
        print("\n".join(c.fails))
        print("❌ 共 " + str(c.total) + " 条，" + str(len(c.fails)) + " 条不成立")
        return 1
    print("✅ 撤销入口与防连点（L-12 / L-13 / L-14）静态判据：" + str(c.total) + " 条全过"
          "（入口 / 防连点 / 失败落点 / 文案 / 边界）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
