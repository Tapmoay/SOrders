"""反向验证（CHG-0049）：把 _check_cancel_entry_and_guards.py 要钉住的每一句话逐个破坏掉，
看它是不是**真的会红**。

为什么必须反验：下面这些坏法**一个都不会报错**——
- 派单员列表的撤销门从 CANCELLABLE 改成别的状态集合：能编译、能跑，只是撤销键在错的单子上冒出来；
- 撤销按钮的 onClick 改成空：点了没反应，与"接口失败"长得一模一样；
- 货主列表卡片退回直接改 cancelTarget：能撤，只是"上一次的失败原因"留在弹窗里；
- 详情页的 canCancel 删掉状态约束：能编译，送达/已撤销的单也冒出一个撤销键；
- 四个 VM 的 if (acting) return 删掉：慢网下连点两下**撤两遍**（不可逆），测试全绿；
- 弹窗确认键的 enabled 删掉：同上，用户看到的是"撤销失败"；
- 撤销的 catch 把 dialogError/cancelError 写成页面级 error：后端照样回错，只是整页变成 ErrorView
  （弹层还开着、列表先没了 —— 2026-09-23 真机抓到过）；
- 弹窗里的 FormErrorLine 删掉：失败原因一个字都不出现，用户以为"点了没反应"；
- 撤回回执/弹窗文案改回「回到派单中」：与后端 recall_dispatch 落点（PENDING_DISPATCH）矛盾；
- CANCELLABLE 加一个值 / 后端落点改成 DISPATCHED：状态机与文案各说各话。

每条注入都是「(说明, 文件, 原文, 替换成, 期望变红的检查名关键词)」，跑完逐条还原并复核。

R4-BOUNDARY-JUSTIFICATION: 这份脚本存在的原因是**判据自己也会说谎**：上面每一条坏法都通得过
编译与既有测试，只有把源码改坏、看判据红不红，才知道那 46 条断言钉的是不是真东西。

用法：python _tools/qa/_reverse_verify_cancel_entry_and_guards.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_cancel_entry_and_guards.py"
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
FLOW = ROOT / "backend" / "app" / "services" / "order_flow.py"

#: 撤销弹窗的正文（四个弹窗里逐字相同 ⇒ 换成「回到派单中」时只改这一个词）。
CANCEL_TITLE_TAIL = "撤销后货主将在「已撤销」中看到该订单。"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    # ---------- ① 入口 ----------
    (
        "派单员订单列表的撤销门从 CANCELLABLE 改成 RETURNABLE（撤销键在错的单子上冒出来）",
        DISP_SCREEN,
        "if (order.status in OrderStatusModel.CANCELLABLE) {",
        "if (order.status in OrderStatusModel.RETURNABLE) {",
        "[入口] 派单员订单列表有「可撤销」的门",
    ),
    (
        "派单员订单列表的撤销按钮点了不干活（onClick 清空）",
        DISP_SCREEN,
        "TextButton(onClick = { vm.openCancel(order) }) {",
        "TextButton(onClick = { }) {",
        "[入口] 派单员订单列表的撤销按钮走 vm.openCancel(order)",
    ),
    (
        "货主列表卡片退回直接改 cancelTarget（上一次的失败原因不会被清掉）",
        SHIP_SCREEN,
        "onClick = { vm.openCancel(order) },",
        "onClick = { vm.cancelTarget = order },",
        "[入口] 货主列表卡片撤销入口走 vm.openCancel(order)",
    ),
    (
        "待派单池那一档的撤销入口被拆掉（onClick 换成别的动作）",
        POOL_SCREEN,
        "TextButton(onClick = { vm.openCancel(order.id) }) {",
        "TextButton(onClick = { vm.openRecall(order.id) }) {",
        "[入口] 待派单池那一档的撤销入口还在",
    ),
    (
        "详情页撤销门删掉「代客撤销」那一半（派单员在详情页撤不了别人的单）",
        DETAIL,
        'val canCancel = Capabilities.can(role.key, "order:cancel_shipper") ||\n'
        '                    Capabilities.can(role.key, "order:cancel_dispatcher")',
        'val canCancel = Capabilities.can(role.key, "order:cancel_shipper")',
        "[入口] 详情页撤销门问能力表（order:cancel_dispatcher）",
    ),
    (
        "详情页撤销门去掉状态约束（只问能力 ⇒ 送达/已撤销的单也有撤销键）",
        DETAIL,
        "if (canCancel && order.status in OrderStatusModel.CANCELLABLE) {",
        "if (canCancel) {",
        "[入口] 详情页按能力判据仍受可撤销状态约束",
    ),
    (
        "详情页删掉 Capabilities 的 import（门靠巧合全限定名）",
        DETAIL,
        "import com.tapmoay.sorders.core.Capabilities\n",
        "",
        "[入口] 详情页导入了 Capabilities",
    ),
    (
        "派单员订单列表的撤销弹窗确认键去掉 disabled 态",
        DISP_SCREEN,
        "onClick = { vm.confirmCancel() },\n                    enabled = !vm.acting,",
        "onClick = { vm.confirmCancel() },",
        "[防连点] 派单员订单列表撤销弹窗确认键带 enabled",
    ),
    (
        "派单池的撤销弹窗确认键去掉 disabled 态",
        POOL_SCREEN,
        "onClick = { vm.confirmCancel() },\n                    enabled = !vm.acting,",
        "onClick = { vm.confirmCancel() },",
        "[防连点] 派单池撤销弹窗确认键带 enabled",
    ),
    (
        "详情页的撤销弹窗确认键去掉 disabled 态",
        DETAIL,
        "onClick = { vm.cancel() },\n                    enabled = !vm.acting,",
        "onClick = { vm.cancel() },",
        "[防连点] 详情页撤销弹窗确认键带 enabled",
    ),
    (
        "货主撤销弹窗不再传 enabled（共用件的 disabled 态形同虚设）",
        SHIP_SCREEN,
        "enabled = !vm.acting,\n            onConfirm = { vm.confirmCancel() },",
        "onConfirm = { vm.confirmCancel() },",
        "[防连点] 货主撤销弹窗传了 enabled",
    ),
    (
        "共用件 DangerConfirmDialog 干脆不支持 enabled 这个形参",
        COMP,
        "    error: String? = null,\n    enabled: Boolean = true,\n) {",
        ") {",
        "[防连点] 共用件 DangerConfirmDialog 支持 enabled",
    ),
    (
        "共用件收了 enabled 但不透传给确认键（形参摆着看）",
        COMP,
        "                enabled = enabled,\n",
        "",
        "[防连点] 共用件把 enabled 透传给确认键",
    ),
    # ---------- ② 防连点 / ③ 失败落点 ----------
    (
        "派单池的 confirmCancel 删掉防连点守卫（慢网下连点两下撤两遍）",
        POOL_VM,
        "if (acting) return  // 防连点：一次网络往返期间再点两次会发两遍撤销（第二遍必然 400）\n",
        "",
        "[防连点] 派单池 confirmCancel 有 if (acting) return",
    ),
    (
        "货主的 confirmCancel 删掉防连点守卫",
        SHIP_VM,
        "if (acting) return  // 防连点：一次网络往返期间再点两次会发两遍撤销（第二遍必然 400）\n",
        "",
        "[防连点] 货主 confirmCancel 有 if (acting) return",
    ),
    (
        "详情页的 cancel 删掉防连点守卫",
        DETAIL_VM,
        "if (acting) return  // 防连点：一次网络往返期间再点两次会发两遍撤销（第二遍必然 400）\n",
        "",
        "[防连点] 详情页 cancel 有 if (acting) return",
    ),
    (
        "派单员订单列表的 confirmCancel 删掉防连点守卫",
        DISP_VM,
        "if (acting) return  // 防连点：一次网络往返期间再点一次会撤两遍（第二遍必然被后端拒，用户看到的是\"撤销失败\"）\n",
        "",
        "[防连点] 派单员订单列表 confirmCancel 有 if (acting) return",
    ),
    (
        "派单池撤销失败改成写页面级 error（整页换成 ErrorView，列表先没了）",
        POOL_VM,
        "// ⛔ 不写页面级 [error]：那会把整页换成 ErrorView（弹层还开着、列表先没了）\n                dialogError = toApiException(e).message\n",
        "error = toApiException(e).message\n",
        "[落点] 派单池撤销失败写弹层错误",
    ),
    (
        "货主撤销失败改成写页面级 error",
        SHIP_VM,
        "cancelError = toApiException(e).message\n",
        "error = toApiException(e).message\n",
        "[落点] 货主撤销失败写弹层错误",
    ),
    (
        "详情页撤销失败改成写页面级 error",
        DETAIL_VM,
        "cancelError = toApiException(e).message\n",
        "error = toApiException(e).message\n",
        "[落点] 详情页撤销失败写弹层错误",
    ),
    (
        "派单员订单列表的撤销弹窗不再画失败原因（失败原因一个字都不出现）",
        DISP_SCREEN,
        "Text(\"确认撤销该订单？撤销后货主将在「已撤销」中看到该订单。\")\n"
        "                    // 失败原因画在**弹层里**（页面级 error 被弹层盖住，2026-09-23 真机抓到）\n"
        "                    FormErrorLine(vm.dialogError)\n",
        "Text(\"确认撤销该订单？撤销后货主将在「已撤销」中看到该订单。\")\n",
        "[落点] 派单员订单列表撤销弹窗画错误行",
    ),
    (
        "派单池的撤销弹窗不再画失败原因",
        POOL_SCREEN,
        "Text(\"确认撤销该订单？撤销后货主将在「已撤销」中看到该订单。\")\n"
        "                    // 失败原因画在**弹层里**（页面级 error 被弹层盖住，2026-09-23 真机抓到）\n"
        "                    FormErrorLine(vm.dialogError)\n",
        "Text(\"确认撤销该订单？撤销后货主将在「已撤销」中看到该订单。\")\n",
        "[落点] 派单池撤销弹窗画错误行",
    ),
    (
        "货主撤销弹窗不再把失败原因传给共用件",
        SHIP_SCREEN,
        "error = vm.cancelError,\n",
        "",
        "[落点] 货主撤销弹窗把错误传给共用件",
    ),
    (
        "详情页撤销弹窗不再画失败原因",
        DETAIL,
        "FormErrorLine(vm.cancelError)\n",
        "",
        "[落点] 详情页撤销弹窗画错误行",
    ),
    (
        "派单池打开撤销弹层时不清掉上一次的失败原因（旧错误留在新弹窗里）",
        POOL_VM,
        "dialogError = null\n        showCancelDialog = true",
        "showCancelDialog = true",
        "[落点] 派单池打开撤销弹层清掉上一次的失败",
    ),
    (
        "详情页打开撤销弹层时不清掉上一次的失败原因",
        DETAIL,
        "vm.cancelError = null; vm.showCancelDialog = true",
        "vm.showCancelDialog = true",
        "[落点] 详情页打开撤销弹层时清掉上一次的失败",
    ),
    # ---------- ④ 文案 ----------
    (
        "撤回成功的回执改回「回到派单中」（与后端落点 PENDING_DISPATCH 矛盾）",
        DISP_VM,
        "actionResult = \"已撤回派单，订单回到待派单池（等重新派单）\"",
        "actionResult = \"已撤回派单，订单回到派单中\"",
        "[文案] 撤回成功回执说「回到待派单池」",
    ),
    (
        "派单员撤回弹窗的正文改回「回到派单中」",
        DISP_SCREEN,
        "Text(\"撤回后订单回到待派单池（等重新派单），司机端将收到撤回通知。\")",
        "Text(\"撤回后订单回到派单中，司机端将收到撤回通知。\")",
        "[文案] 派单员撤回弹窗说「回到待派单池」",
    ),
    (
        "后端 recall_dispatch 的落点从待派单改成已派单（文案与状态机分家）",
        FLOW,
        "            status=OrderStatus.PENDING_DISPATCH,\n            driver_id=None,",
        "            status=OrderStatus.DISPATCHED,\n            driver_id=None,",
        "[文案-后端同源] 撤回的落点确实是待派单",
    ),
    # ---------- ⑤ 边界 ----------
    (
        "CANCELLABLE 被改宽（多一个 ACCEPTED ⇒ 已接单也能撤）",
        STATUS,
        'val CANCELLABLE: Set<String> = setOf("PENDING_DISPATCH", "DISPATCHED")',
        'val CANCELLABLE: Set<String> = setOf("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED")',
        "[边界] 状态集合没被改宽",
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> bytes:
    text = text.replace("\r\n", "\n")
    if crlf:
        text = text.replace("\n", "\r\n")
    data = text.encode("utf-8")
    p.write_bytes(data)
    return data


def restore_src(p: Path, text: str, crlf: bool) -> None:
    wrote = write_src(p, text, crlf)
    if p.read_bytes() != wrote:
        print("⛔ 还原失败（写回去的字节与读出来的不一致）：" + str(p))
        raise SystemExit(2)


def run_check() -> tuple[int, list[str]]:
    proc = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    fails = [ln for ln in (proc.stdout or "").splitlines() if "[FAIL]" in ln]
    return proc.returncode, fails


def verdict(expect: str) -> bool:
    code, fails = run_check()
    return code != 0 and any(expect in ln for ln in fails)


def main() -> int:
    total = len(MUTATIONS)
    print("== 反验 _check_cancel_entry_and_guards.py（共 %d 条注入 + 收尾复核）==" % total)

    code, fails = run_check()
    if code != 0:
        print("⛔ 源码完好时判据就是红的，先修判据：")
        print("\n".join(fails[:8]))
        return 2
    print("[基线] 源码完好 ⇒ 判据全绿 ✅")

    bad: list[str] = []
    for i, (desc, path, old, new, expect) in enumerate(MUTATIONS, 1):
        text, crlf = read_src(path)
        n = text.count(old)
        if n != 1:
            print("[%d/%d] [SKIP] 原文命中 %d 次（应为 1）：%s" % (i, total, n, desc))
            bad.append(desc + "（注入点不唯一）")
            continue
        write_src(path, text.replace(old, new, 1), crlf)
        try:
            hit = verdict(expect)
        finally:
            restore_src(path, text, crlf)
        if hit:
            print("[%d/%d] ✅ 破坏「%s」⇒ 判据变红" % (i, total, desc))
        else:
            print("[%d/%d] ❌ 破坏「%s」⇒ 判据没红（期望关键词 %s）" % (i, total, desc, expect))
            bad.append(desc)

    code, fails = run_check()
    if code != 0:
        print("⛔ 全部还原之后判据还是红的：")
        print("\n".join(fails[:8]))
        bad.append("还原后判据仍红")

    print()
    if bad:
        print("❌ 反验 %d/%d 条成立；以下不成立：" % (total - len(bad), total))
        for d in bad:
            print("  - " + d)
        return 1
    print("✅ 反验 %d/%d 条全部成立：每条坏法都让判据变红，全部还原后判据仍全绿" % (total, total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
