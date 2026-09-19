"""反向验证「客户端状态门与后端逐值一致」这条红线**真的会红**（H1 / R17）。

## 这一组注入为什么这样选
这条红线的价值全在"**真源是后端**"上：如果它只是比对自己文档里写过的一串常量，
那么把后端状态门改小一档、客户端照样全绿 —— 那它就等于没有。所以注入分三类：

| 类 | 注入 | 证明的是 |
|---|---|---|
| A 后端真源 | 改 `cancel_pending` / `recall_dispatch` 的 `allowed`、把 `order_flow` 的锚点改名 | 判据真的在读后端源码；锚点消失时**硬失败**而不是静默通过 |
| B 客户端模型 | H5 少一档类型/标签/颜色、两个状态集合各少一档；App 的 `ALL`/`ACKABLE`/`RECALLABLE`/`NOT_CANCELLED` 少一档 | 逐值对账（少一档就红） |
| C 入口与调用 | 把司机/派单员的查询改回只查 `ACCEPTED`、App 撤回按钮写回硬编码、H5 加一个不存在的端点、登出只清本机 | 第④⑤⑥⑦条判据有牙 |

用法：python _tools/qa/_reverse_verify_client_contract.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_client_contract.py"

FE_TYPES = "frontend/src/types/order.ts"
FE_CONST = "frontend/src/constants/order.ts"
FE_DRIVER = "frontend/src/views/driver/DriverOpenOrders.vue"
FE_DISPATCH = "frontend/src/views/dispatcher/DispatcherPending.vue"
FE_AUTH = "frontend/src/api/auth.ts"
FE_STORE = "frontend/src/stores/auth.ts"
KT_MODEL = "android/app/src/main/java/com/tapmoay/sorders/core/OrderStatusModel.kt"
KT_RECALL = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DispatcherOrdersScreen.kt"
KT_DRIVER = "android/app/src/main/java/com/tapmoay/sorders/ui/driver/DriverOrdersViewModel.kt"
PY_FLOW = "backend/app/services/order_flow.py"
FE_DASHBOARD = "frontend/src/views/dispatcher/DispatcherDashboard.vue"
FE_LEDGER = "frontend/src/views/dispatcher/DispatcherLedger.vue"
FE_ORDER_CREATE = "frontend/src/views/shipper/OrderCreate.vue"
KT_ORDER_CREATE = (
    "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/OrderCreateViewModel.kt"
)

CASES: list[tuple[str, str, object]] = [
    # ---- A 后端真源（改后端 → 客户端必须跟着红）----
    (
        "后端撤销门少一档（cancel_pending 的 allowed 去掉 DISPATCHED）",
        PY_FLOW,
        lambda s: s.replace(
            "allowed = (OrderStatus.PENDING_DISPATCH, OrderStatus.DISPATCHED)",
            "allowed = (OrderStatus.PENDING_DISPATCH,)",
            1,
        ),
    ),
    (
        "后端撤回门少一档（recall_dispatch 的 allowed 只留 ACCEPTED）",
        PY_FLOW,
        lambda s: s.replace(
            "allowed = (OrderStatus.DISPATCHED, OrderStatus.ACCEPTED)",
            "allowed = (OrderStatus.ACCEPTED,)",
            1,
        ),
    ),
    (
        "后端锚点被改名（`allowed =` 没了）→ 必须硬失败，不许静默通过",
        PY_FLOW,
        lambda s: s.replace(
            "    allowed = (OrderStatus.DISPATCHED, OrderStatus.ACCEPTED)\n",
            "    permitted = (OrderStatus.DISPATCHED, OrderStatus.ACCEPTED)\n",
            1,
        ),
    ),
    # ---- B 客户端模型（少一档就红）----
    (
        "H5 类型少一档（OrderStatus 去掉 DISPATCHED）",
        FE_TYPES,
        lambda s: s.replace("  | 'DISPATCHED'\n", "", 1),
    ),
    (
        "H5 标签表少一档（ORDER_STATUS_LABEL 去掉 DISPATCHED）",
        FE_CONST,
        lambda s: s.replace("  DISPATCHED: '已派单',\n", "", 1),
    ),
    (
        "H5 标签颜色少一档（orderStatusTagType 去掉 DISPATCHED 分支）",
        FE_CONST,
        lambda s: s.replace(
            "    case 'DISPATCHED':\n      return 'default'\n",
            "",
            1,
        ),
    ),
    (
        "H5 撤销门少一档（CANCELLABLE_STATUSES 只剩 PENDING_DISPATCH）",
        FE_CONST,
        lambda s: s.replace(
            "export const CANCELLABLE_STATUSES: readonly OrderStatus[] = ['PENDING_DISPATCH', 'DISPATCHED']",
            "export const CANCELLABLE_STATUSES: readonly OrderStatus[] = ['PENDING_DISPATCH']",
            1,
        ),
    ),
    (
        "H5 撤回门少一档（RECALLABLE_STATUSES 只剩 ACCEPTED）",
        FE_CONST,
        lambda s: s.replace(
            "export const RECALLABLE_STATUSES: readonly OrderStatus[] = ['DISPATCHED', 'ACCEPTED']",
            "export const RECALLABLE_STATUSES: readonly OrderStatus[] = ['ACCEPTED']",
            1,
        ),
    ),
    (
        "App 状态全集少一档（ALL 去掉 DISPATCHED）",
        KT_MODEL,
        lambda s: s.replace('        "DISPATCHED",\n', "", 1),
    ),
    (
        "App 接单门少一档（ACKABLE 写成 ACCEPTED）",
        KT_MODEL,
        lambda s: s.replace(
            'val ACKABLE: Set<String> = setOf("DISPATCHED")',
            'val ACKABLE: Set<String> = setOf("ACCEPTED")',
            1,
        ),
    ),
    (
        "App 撤回门少一档（RECALLABLE 只剩 ACCEPTED）",
        KT_MODEL,
        lambda s: s.replace(
            'val RECALLABLE: Set<String> = setOf("DISPATCHED", "ACCEPTED")',
            'val RECALLABLE: Set<String> = setOf("ACCEPTED")',
            1,
        ),
    ),
    (
        "App 收款门多一档（NOT_CANCELLED 把已撤销也放进来）",
        KT_MODEL,
        lambda s: s.replace(
            '        setOf("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED", "DELIVERED")',
            '        setOf("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED", "DELIVERED", "CANCELLED")',
            1,
        ),
    ),
    (
        "App 删掉一个集合（NOT_CANCELLED）→ 必须报『找不到』而不是跳过",
        KT_MODEL,
        lambda s: s.replace("    val NOT_CANCELLED: Set<String> =\n", "    private val UNUSED_ALIAS: Set<String> =\n", 1),
    ),
    # ---- C 入口与调用 ----
    (
        "司机 H5 查询改回只查 ACCEPTED（H1 原样复现）",
        FE_DRIVER,
        lambda s: s.replace(
            "await fetchOrdersByStatuses(['DISPATCHED', 'ACCEPTED'])",
            "await fetchOrdersByStatuses(['ACCEPTED'])",
            1,
        ),
    ),
    (
        "派单员 H5「运输中」页签去掉已派单",
        FE_DISPATCH,
        lambda s: s.replace(
            "? ['PENDING_DISPATCH'] : ['DISPATCHED', 'ACCEPTED']",
            "? ['PENDING_DISPATCH'] : ['ACCEPTED']",
            1,
        ),
    ),
    (
        "App 派单员撤回按钮写回硬编码 ACCEPTED",
        KT_RECALL,
        lambda s: s.replace(
            "if (order.status in OrderStatusModel.RECALLABLE) {",
            'if (order.status == "ACCEPTED") {',
            1,
        ),
    ),
    (
        "App 司机「进行中」改回只查 ACCEPTED",
        KT_DRIVER,
        lambda s: s.replace(
            "if (tab == 0) OrderStatusModel.DRIVER_OPEN else listOf(\"DELIVERED\")",
            "if (tab == 0) listOf(\"ACCEPTED\") else listOf(\"DELIVERED\")",
            1,
        ),
    ),
    (
        "H5 又调一个不存在的端点（/auth/register 复活）",
        FE_AUTH,
        lambda s: s.replace(
            "export async function logout() {",
            "export async function register2() {\n  await http.post('/auth/register', {})\n}\n\nexport async function logout() {",
            1,
        ),
    ),
    (
        "H5 状态字面量拼错（PENDING_DISPACTH）",
        FE_CONST,
        lambda s: s.replace("  PENDING_DISPATCH: '派单中',", "  PENDING_DISPACTH: '派单中',", 1),
    ),
    (
        "H5 登出退回「只清本机」（不调后端 /auth/logout）",
        FE_STORE,
        lambda s: s.replace("      await apiLogout()\n", "      void 0\n", 1),
    ),
    # ---- 第十八轮新增：界面把后端原始值直接印给用户 ----
    (
        "看板把订单状态码直接印出来（用户看到 DELIVERED 而不是「已送达」）",
        FE_DASHBOARD,
        lambda s: s.replace(
            'ORDER_STATUS_LABEL[ex.status as OrderStatus] || ex.status', "ex.status", 1
        ),
    ),
    (
        "看板把服务端精度的金额直接印出来（149.9885265700483091787439614）",
        FE_DASHBOARD,
        lambda s: s.replace(
            "`¥${formatMoney2(activity.avg_order_value)}`",
            "`¥${activity.avg_order_value}`",
            1,
        ),
    ),
    (
        "账本页商品下拉把 12.5000 直接印出来",
        FE_LEDGER,
        lambda s: s.replace(
            "`默认单价 ¥${formatMoney2(p.default_unit_price)}`",
            "`默认单价 ¥${p.default_unit_price}`",
            1,
        ),
    ),
    # ---- 第十九轮新增：批发商专属价（下单报价） ----
    (
        "H5 下单页不再读批发商专属价（批发商按零售价成交）",
        FE_ORDER_CREATE,
        lambda s: s.replace(
            "    const rows: PriceRule[] = await fetchPriceRules(isDispatcher.value ? subject : undefined)\n",
            "    const rows: PriceRule[] = []\n",
            1,
        ),
    ),
    (
        "H5 下单页读了专属价但不用（单价还是取默认价）",
        FE_ORDER_CREATE,
        lambda s: s.replace(
            "  lines.value[i].unit_price = priceForProduct(pr)",
            "  lines.value[i].unit_price = Number(pr.default_unit_price)",
            1,
        ),
    ),
    (
        "H5 下单页换主体时不清空上一份专属价（拿甲的价给乙下单）",
        FE_ORDER_CREATE,
        lambda s: s.replace(
            "  if (priceRulesSubject.value !== subject) {\n",
            "  if (false) {\n",
            1,
        ),
    ),
    (
        "App 下单 ViewModel 去掉「这份价属于谁」的守卫（报价串号）",
        KT_ORDER_CREATE,
        lambda s: s.replace("if (priceRulesShipper != subject) return p.defaultUnitPrice", "if (false) return p.defaultUnitPrice", 1),
    ),
    # ---- 第十九轮新增：界面里的「关联」承诺 ----
    (
        "账本手工记账把「不会挂到订单上」的说明删掉（用户以为钱挂到了那单上）",
        FE_LEDGER,
        lambda s: s.replace(
            '      <p v-if="manualForm.order_id != null" class="manual-order-hint">\n',
            '      <p v-if="false" class="manual-order-hint">\n',
            1,
        ),
    ),
    (
        "账本手工记账把说明整段删掉",
        FE_LEDGER,
        lambda s: s.replace(
            '      <p v-if="manualForm.order_id != null" class="manual-order-hint">\n'
            "        手工记账不会挂到订单上（订单账由送达/货损自动生成，挂了会重复计入）。\n"
            "        这里选的单号只写进审计日志，方便日后查这笔钱的来由。\n"
            "      </p>\n",
            "",
            1,
        ),
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> None:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    p.write_bytes(data.encode("utf-8"))


def run_check(target: Path | None = None) -> int:
    p = subprocess.run(
        [sys.executable, str(target or CHECK)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode


def main() -> int:
    fails: list[str] = []
    if run_check() != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({rel for _l, rel, _m in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}
    crlfs = {rel: b"\r\n" in originals[rel] for rel in touched}

    for label, rel, mutate in CASES:
        path = ROOT / rel
        plain = originals[rel].decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            write_src(path, mutated, crlfs[rel])
            red = run_check() != 0
        finally:
            path.write_bytes(originals[rel])
        if red:
            print(f"  [OK] {label} → 红线报红")
        else:
            fails.append(f"{label}：注入之后红线**仍然全绿**（判据没牙）")
            print(f"  [MISS] {label} → 全绿")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
