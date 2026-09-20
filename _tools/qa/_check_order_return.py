"""红线：**退货**（整单/部分）与**按商品核销** —— 2026-09-20 用户要求的两件事。

## 用户原话（这一版的功能定义）
- 「那个**订单管理**……我们可以进行一个**退货**」
- 「可以**整单退货**，也可以只退其中的**某几个商品**或者是一个商品，他自己勾选」
- 「如果这个单子**已经收了钱**的话，做相应的**退款**……它会显示"订单已结账"，
   我们在退货的话，就会**自动的退款**」
- 订单状态：**新增「已退货」**（用户选的第三项，不是沿用「已撤销」）
- 「账本管理的核心单位也就是最小单位是**订单**……第一层就是货主选择，第 2 层是时间上的统计……
   包括我们**核销账也是在这里核销**，我们可以点击订单点击核销，**可以全部核销，也可以按商品进行核销**」

## 为什么这两件事必须配一条红线（各自的错法都是"钱悄悄少了/多了"）
| 错法 | 后果 |
|---|---|
| 退货只改状态、不写账本红冲 | 退了货还照记营业额 |
| 红冲行写成**正数** | 应收不降反升（退货变成又卖了一次） |
| 红冲金额用 `line_total` 而不是"单价 × 退的数量" | 部分退货被按整行冲掉 |
| 退货不回补库存 | 库存永久少一批货，盘库找不到原因 |
| 已结账的单退货不退现 | 客户的钱收了、货也退了，账上还欠他 |
| 没收到钱的单也退现 | 公司倒贴现金 |
| 退现不设上限（`已收 − 已退现`） | 客户只付了 300、退掉值 400 的货 → 退 400 = 倒贴 100 |
| 按商品核销不校验行归属 | 拿 A 单的商品行去核销 B 单的额度 |
| 核销金额超过欠款 | 欠款变负数（预收），账上说不清 |
| 部分核销就把 `paid` 翻成 True | 这张单从「挂账未收」名单里消失，而它还欠一半 |
| 整单退完不进 `RETURNED` | 该单仍算"已送达未收"，催收名单里永远有一条收不到的钱 |
| 客户端自己算"还能退几件" | 界面让填 3、后端只认 2，用户不知道该信谁 |
| 客户端自己算欠款（总价 − 已收） | 退货红冲与退现都不在"已收"里，减出来的数偏大 → 照着它多要钱 |

## 判据（全部**从源码算**，清单不手写）
后端：枚举 / 迁移 / 服务 / 端点 / 口径唯一性 / 并发写法 / 权限 / 回归测试名；
客户端：状态门与后端同一档、上限公式同源、钱只显示不重算、状态徽章有中文名、页签有色。

用法：python _tools/qa/_check_order_return.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend/app"
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
FRONTEND = ROOT / "frontend/src"


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的断言要跟着改）")
    return p.read_text(encoding="utf-8")


def code_only(src: str) -> str:
    """去掉注释与文档字符串（判据只看代码，不看我们自己在注释里写的漂亮话）。"""
    src = re.sub(r'"""[\s\S]*?"""', "", src)
    src = re.sub(r"^\s*#.*$", "", src, flags=re.M)
    return src


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
        m = re.search(pattern, text)
        self.ok(label, m is not None, f"没找到 {pattern!r}")

    def absent(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is None, f"命中：{m.group(0)[:70]!r}" if m else "")


def main() -> int:
    c = Checker()

    enums = read(BACKEND / "models/enums.py")
    order_model = read(BACKEND / "models/order.py")
    bootstrap = read(BACKEND / "core/schema_bootstrap.py")
    ret = read(BACKEND / "services/order_return.py")
    money = read(BACKEND / "services/order_money.py")
    resp = read(BACKEND / "services/order_response.py")
    acct = read(BACKEND / "services/accounting_service.py")
    orders_api = read(BACKEND / "api/v1/orders.py")
    inv = read(BACKEND / "services/inventory_service.py")
    rbac = read(BACKEND / "core/rbac.py")
    tests = read(ROOT / "backend/tests/test_order_return.py")

    print("== 1. 枚举与迁移（漏一个就是「本机好好的、生产一按退货就 500」）==")
    c.present("订单状态有「已退货」这一档", enums, r'RETURNED = "RETURNED"')
    c.present("账本来源有 RETURN（与货损的 REFUND 分开）", enums, r'RETURN = "return"')
    c.present("审计动作码 ORDER_RETURN", enums, r'ORDER_RETURN = "ORDER_RETURN"')
    c.present("行上有「已退数量」这一列", order_model, r"returned_quantity: Mapped\[int\] = mapped_column")
    c.present("订单上有退货时间", order_model, r"returned_at: Mapped\[datetime \| None\]")
    c.present("旧库补 order_products.returned_quantity", bootstrap, r"ALTER TABLE order_products ADD COLUMN returned_quantity")
    c.present("旧库补 orders.returned_at", bootstrap, r"ALTER TABLE orders ADD COLUMN returned_at")
    c.present("MySQL 的 orders.status 枚举补 RETURNED", bootstrap, r"'DELIVERED','CANCELLED','RETURNED'")
    c.present("MySQL 的 ledgers.source 枚举补 RETURN", bootstrap, r"'ORDER','MANUAL','REFUND','RETURN'")

    print("\n== 2. 退货服务：红冲 / 库存 / 退现 / 状态 ==")
    c.present("红冲行金额为负（退货是减账，不是又一次收入）", ret, r"total=-line_amount")
    c.present("红冲行数量为负", ret, r"quantity=-qty")
    c.present("红冲行成本快照为负（货回来了，COGS 一起冲回）", ret, r"cost_price_snapshot=-cost_total")
    c.present("红冲行来源是 RETURN（不是 REFUND）", ret, r"source=LedgerSource\.RETURN")
    c.present(
        "同一行多次退货**累加到同一行**（唯一约束 (order_product_id, source) 钉着）",
        ret, r"update\(Ledger\)[\s\S]{0,200}?values\(",
    )
    c.present("累加走 SQL 表达式（读改写会在并发下丢掉一次退货）", ret, r"quantity=Ledger\.quantity - qty")
    c.present("已退数量也走 SQL 表达式", ret, r"returned_quantity=OrderProduct\.returned_quantity \+ qty")
    c.absent(
        "不许把已退数量读出来再写回（lost update）",
        code_only(ret),
        r"op\.returned_quantity\s*=\s*[^\n=]*op\.returned_quantity",
    )
    c.present("库存回补走唯一一处实现", ret, r"restock_returned\(db, order, lines, operator_id\)")
    c.present("库存回补用 SQL 表达式自增", inv, r"values\(stock=func\.coalesce\(Product\.stock, 0\) \+ qty\)")
    c.present("库存流水记 RETURNED 状态", inv, r'status="RETURNED"')
    c.present("货损那几件不许退（上限减掉 damage_quantity）", ret, r"- int\(op\.damage_quantity or 0\) - int\(op\.returned_quantity or 0\)")
    c.present("退现上限 = 这次退掉的货值", ret, r"min\(returned_now, already_refundable\)")
    c.present("退现上限还受「已收 − 已退现」限制（不许倒贴）", ret, r"max\(ZERO, m\.settled - m\.refunded\)")
    c.present("退现写 REFUND_CUSTOMER 流出", ret, r"biz_type=CashFlowBizType\.REFUND_CUSTOMER")
    c.present("退现方向是 OUT", ret, r"direction=CashFlowDirection\.OUT")
    c.absent("退货**不许**把 paid 改回 False（钱确实进来过）", code_only(ret), r"\.paid\s*=")
    c.present("只有已送达的单能退", ret, r"order\.status != OrderStatus\.DELIVERED")
    c.present("整单退完才进 RETURNED", ret, r"order\.status = OrderStatus\.RETURNED")
    c.present("整单退完的判据读**库里的真实值**（内存对象是旧的）", ret, r"select\(OrderProduct\.quantity, OrderProduct\.returned_quantity\)")
    c.present("退货留痕（写 ORDER_RETURN 审计）", ret, r"action=OperationAction\.ORDER_RETURN")
    c.present("金额两位小数走全项目同一个进位", ret, r'ROUND_HALF_UP')

    # ---- 退货金额与账本红冲必须是**同一个数**（2026-09-21 修掉差 1 分的缺陷）----
    # 四位单价下（`order_products.unit_price` 是 `Numeric(14,4)`，拆单会算出这种单价）：
    # 两行各 12.3456 × 1 —— 按行先取两位再求和 = 24.70，账本按行落四位再汇总 = 24.69。
    # 两个数印在**同一个响应体**里（`returned_amount` 与 `order.returned_amount`），
    # 而退现按大的那个付出去：真金白银比账上红冲多一分，**两边都不报错**。
    # 所以判据是"只算一处 + 到分只做一次"（数值由 `backend/tests/test_order_return.py` 那条钉着）：
    c.present("这一行的退货货值只算一处（`_line_amount`）",
              ret, r"line_amount = _line_amount\(op, qty\)")
    c.present("红冲行用**调用方传进来的**那个数（不自己再算一遍）",
              ret, r"_reversal_row\(db, order, op, qty, line_amount,")
    c.absent("本次退货金额**不许**按行取两位再求和（到分多取一次就是那 1 分）",
             ret, r"q2\(line_amount\)")
    c.present("到分只在「整次退货」这一层做一次", ret, r"returned_amount = q2\(returned_raw\)")
    reversal_body = re.search(r"def _reversal_row\(([\s\S]*?)\ndef return_order\(", ret)
    c.ok("解析到红冲行那一段（解析失效时先喊，别安静通过）", reversal_body is not None)
    c.absent("红冲行里不再出现第二种货值算法（单价 × 数量只有一处）",
             code_only(reversal_body.group(1)) if reversal_body else "",
             r"unit_price\s*\*\s*Decimal\(")

    print("\n== 3. 端点：权限、加锁、整单回滚 ==")
    c.present("退货端点存在", orders_api, r'@router\.post\("/\{order_id\}/return", response_model=OrderReturnOut\)')
    c.present("权限点是 ORDER_RETURN", orders_api, r"require_permission\(Permission\.ORDER_RETURN\)")
    c.present("取单时锁行（两个退货同时进来会各自算通过）", orders_api, r"select\(Order\)[\s\S]{0,120}?\.where\(Order\.id == order_id\)[\s\S]{0,40}?\.with_for_update\(\)")
    c.present("被拒时回滚（红冲写了一半而库存没回补最难查）", orders_api, r"except OrderReturnError as e:\s*\n\s*db\.rollback\(\)")
    c.present("只有派单员有退货权限（货主不给）", rbac, r'"dispatcher": frozenset\([\s\S]{0,900}?Permission\.ORDER_RETURN')
    # ⚠️ 判据必须取**货主那一段**再找：拿 `rbac.split('"driver"')[0]` 切的话，
    #    前半段里本来就含 `Permission.ORDER_RETURN = "order:return"` 那行**声明**，
    #    于是这条断言永远为红（"永远红的检查＝没有检查"）。
    shipper_block = re.search(r'"shipper": frozenset\(([\s\S]*?)\n    \),', rbac)
    c.ok("解析到了货主权限矩阵那一段（解析失效时先喊，别安静通过）", shipper_block is not None)
    c.absent(
        "货主矩阵里**没有**退货权限（一次退货同时动账、库存与现金，货主端只给读）",
        shipper_block.group(1) if shipper_block else "",
        # ⚠️ 必须带 `\b`（2026-09-21 加"退货申请"权限点时踩到）：货主现在**有**
        #    `Permission.ORDER_RETURN_REQUEST`（申请退货，什么都不动），而它的名字以
        #    `ORDER_RETURN` 开头 —— 裸子串匹配会把"申请权"当成"执行权"，这条断言当场变红，
        #    而下一个人为了让检查变绿，很可能去删掉货主那条**正确**的申请权限。
        #    `_` 是词字符，所以 `ORDER_RETURN\b` 匹配 `Permission.ORDER_RETURN,`、
        #    不匹配 `Permission.ORDER_RETURN_REQUEST` —— 这正是要区分的那条线。
        r"ORDER_RETURN\b",
    )
    c.present("退货只有这一个端点（没有第二个「整单退货」的入口）", orders_api, r"/return")
    n_return_routes = len(re.findall(r'@router\.post\("/\{order_id\}/return', orders_api))
    c.ok(f"退货端点**只声明一次**（实测 {n_return_routes}）", n_return_routes == 1, f"实际 {n_return_routes}")

    print("\n== 4. 钱的口径只有一处（order_money）==")
    c.present("唯一的行级应收公式", money, r"def line_receivable\(")
    c.present("行级应收 = 行金额 − 单价 × 已退数量", money, r"Decimal\(total\) - returned")
    c.present("现场收现金没有流水，要用 paid 兜底", money, r"got if got > ZERO else \(total if o\.paid else ZERO\)")
    c.present("退现只看 REFUND_CUSTOMER（货损流水也挂在订单上）", money, r"def _is_customer_refund\(")
    c.present("出参装配调唯一口径", resp, r"m = money or money_of\(db, order\)")
    c.present("列表端点一次算一页的钱（不是逐单 4 条 SQL）", orders_api, r"money = money_map\(db, page\)")
    c.present("应收/已收/已退现/欠款都进了出参", resp, r'data\["arrears_amount"\] = m\.arrears')
    c.present("报表营业额取应收（减掉退货）", read(BACKEND / "api/v1/reports.py"), r"amount = mm\.receivable")

    print("\n== 5. 按商品核销：归属、上限、不翻 paid ==")
    c.present("收款接口接受 order_product_ids", read(BACKEND / "schemas/accounting_v2.py"), r"order_product_ids: list\[int\]")
    c.present("点名的行必须落在所选的单里", acct, r"if op\.order_id not in locked:")
    c.present("一张单一件商品都没勾 → 拒绝（不是「收整单」）", acct, r"一件商品都没勾")
    c.present("核销金额不许超过欠款", acct, r"if part > m\.arrears:")
    c.present("按商品核销的金额按行算（与整单同一份公式）", acct, r"line_receivable\(op\) for op in picked\[oid\]")
    # ⚠️ 2026-09-20 第三轮改口：整单核销收的是**还欠的钱**（`arrears`），不是"当时卖了多少"
    #    （`receivable`）—— 后者在"按商品核销过一部分"的单上偏大：客户端按欠款发、后端按应收算，
    #    两边金额对不上（这种单从此收不动），金额凑巧对上就是**多收**。
    c.present("整单核销收的是还欠的钱（部分核销过的单要能收剩下那部分）", acct, r"else m\.arrears\b")
    c.absent("整单核销不许按应收算", acct, r"else m\.receivable\b")
    c.present("只有这次收完就结清的单才翻 paid", acct, r"settling = \[oid for oid in order_ids if per_order\[oid\] >= money\[oid\]\.arrears\]")
    c.present("并发下的欠款判定走加锁读", acct, r"money_map\(db, list\(locked\.values\(\)\), lock=True\)")
    c.present("已退货的单不许收款", acct, r"OrderStatus\.RETURNED\.value")
    c.present("已退货的单不许收款/挂账（订单侧同一道门）", orders_api, r"OrderStatus\.CANCELLED, OrderStatus\.RETURNED")

    print("\n== 6. 回归测试真的钉住了这些 ==")
    for name in (
        "test_full_return_reverses_ledger_restocks_and_sets_status",
        "test_return_after_collection_refunds_the_customer",
        "test_partial_return_stays_delivered_and_keeps_the_rest_owed",
        "test_return_is_refused_unless_delivered",
        "test_return_cap_excludes_damaged_and_already_returned",
        "test_itemized_by_product_keeps_paid_false_until_fully_settled",
        "test_receipt_over_arrears_is_refused",
        "test_returned_order_cannot_be_collected",
        "test_money_identity_holds_after_return_and_partial_receipt",
    ):
        c.present(f"端到端钉住「{name}」", tests, name)

    print("\n== 7. 客户端：状态门 / 上限 / 钱只显示不重算 ==")
    status_model = read(ANDROID / "core/OrderStatusModel.kt")
    c.present("客户端有 RETURNABLE 状态门", status_model, r"val RETURNABLE: Set<String> = setOf\(\"DELIVERED\"\)")
    c.present("全部取值里有 RETURNED（少一个＝那一档查无此单）", status_model, r'"RETURNED"')
    dto = read(ANDROID / "data/remote/dto/Dtos.kt")
    c.present("出参带已退数量", dto, r'@SerialName\("returned_quantity"\) val returnedQuantity')
    c.present("出参带欠款（界面一律用它）", dto, r'@SerialName\("arrears_amount"\)')
    stats = read(ANDROID / "ui/dispatcher/LedgerPersonStats.kt")
    c.present("客户端行级应收与后端同一条公式（上限/金额都用它）", stats, r"lineReceivableCents")
    c.present("商品统计的未收按订单欠款比例分摊", stats, r"arrears \* net / receivable")
    c.present("分摊的余数落在最后一行（保证加起来等于订单欠款）", stats, r"i == lines\.lastIndex -> arrears - allocated")
    # 「还能退几件」只能有一份客户端实现（三个消费点：退货弹窗 / AI 卡片 / 账本页）
    rules = read(ANDROID / "core/ReturnRules.kt")
    c.present("可退上限的**唯一一份**客户端规则", rules, r"object ReturnRules")
    c.present("上限减掉货损与已退（与后端 max_returnable 同源）", rules, r"quantity - damageQuantity - returnedQuantity")
    c.present("退货弹窗走那一份", read(ANDROID / "ui/dispatcher/DispatcherOrdersViewModel.kt"), r"ReturnRules\.maxReturnable\(")
    c.present("AI 卡片也走那一份", read(ANDROID / "ai/AiWrite.kt"), r"ReturnRules\.maxReturnable\(quantity, damaged, returned\)")
    c.absent(
        "别处不许再手写一条上限公式（界面让填 3、后端只认 2）",
        read(ANDROID / "ui/dispatcher/DispatcherOrdersViewModel.kt"),
        r"line\.quantity - line\.damageQuantity",
    )
    ui = read(ANDROID / "ui/dispatcher/LedgerPersonScreen.kt")
    c.present("账本页有「结算/核销」弹层", ui, r"fun SettleOrderDialog\(")
    c.present("「全部勾上」是把每行勾满（不是第二条提交路径）", ui, r"vm\.pickAllSettleLines\(\)")
    c.absent("核销金额**不许手输**（后端要求逐分相等，手输必然对不上）", ui, r"SoTextField\(vm\.settleAmount")
    c.present("状态徽章里有「已退货」（否则界面直接印原始码 RETURNED）",
              read(ANDROID / "ui/common/Components.kt"), r'"RETURNED" -> \{[\s\S]{0,200}?label = "已退货"')
    # ⚠️ 同一类 bug 的**第二处**（2026-09-21 修）：`OrderPeek.kt` 的状态中文名少过「已退货」，
    #    后果一样 —— 账本展开行把原始码 `RETURNED` 直接印给用户。
    #    判据**从 `OrderStatusModel.ALL` 算**（不手写 6 个状态名）：少一档就红，
    #    以后后端加状态、客户端忘了补中文名，这里也会点名（这正是它当初漏掉的原因：没人算过总数）。
    status_model = read(ANDROID / "core/OrderStatusModel.kt")
    m_all = re.search(r"val ALL: List<String> = listOf\(([\s\S]*?)\)", status_model)
    all_statuses = re.findall(r'"([A-Z_]+)"', m_all.group(1)) if m_all else []
    c.ok(f"从 OrderStatusModel.ALL 解析出全部状态（{len(all_statuses)} 档；解析失效时先喊，别安静通过）",
         len(all_statuses) >= 5, f"实际 {all_statuses}")
    peek = read(ANDROID / "ui/common/OrderPeek.kt")
    missing_label = [s for s in all_statuses if f'"{s}" ->' not in peek]
    c.ok("OrderPeek 的状态中文名覆盖**全部**档（账本展开行少一档就直接印原始码）",
         not missing_label, f"缺 {missing_label}")
    tabs = read(ANDROID / "ui/dispatcher/DispatcherOrdersViewModel.kt")
    c.present("订单管理有「已退货」页签", tabs, r'"RETURNED" to "已退货"')
    c.present("页签配色也加了第六档", read(ANDROID / "ui/common/SegmentedStatusTabs.kt"), r"已退货 · 棕橙")
    c.present("货主端也能筛到「已退货」", read(ANDROID / "ui/shipper/ShipperOrdersViewModel.kt"), r'OrderTab\("RETURNED"')
    h5 = read(FRONTEND / "constants/order.ts")
    c.present("H5 的中文名也补了这一档", h5, r"RETURNED: '已退货'")
    c.present("H5 的类型也补了这一档", read(FRONTEND / "types/order.ts"), r"\| 'RETURNED'")
    c.present("核销金额由界面算出来只读显示（单张）", ui, r'SettleAmountRow\("本次核销", vm\.settleAmount\(\)\)')
    c.present("批量核销的金额也是算出来的（用户手打的数必然与后端对不上）",
              ui, r'SettleAmountRow\("本次核销", vm\.settleAllAmount\(\)\)')

    print("\n== 8. 退货的界面入口与「下单人=货主只画一行」==")
    screen = read(ANDROID / "ui/dispatcher/DispatcherOrdersScreen.kt")
    c.present("订单管理行上有「退货」按钮", screen, r'Text\("退货"\)')
    c.present("按钮的状态门取 RETURNABLE（点了必然被拒的按钮比没有更糟）", screen, r"order\.status in OrderStatusModel\.RETURNABLE")
    c.present("还有可退的量才给这个按钮", screen, r"vm\.hasReturnable\(order\)")
    # ⚠️ 2026-09-21：这一段逐行编辑器（每行的 下单/货损/已退/可退 + −/+ 与上限）原来在
    #    派单员与货主两个页面里**逐字抄了两遍**（约 31 行）。它是**退货金额的入口** ——
    #    只改一份的后果是"两个角色对同一张单给出不同的可退数量"，而两边都不会报错。
    #    现在收在 `ui/common/Components.kt::OrderReturnLines`，判据跟着改：
    #    ① 编辑器只有一处；② **消费点从源码算**（谁页面上有 `vm.returnQty`，谁就必须用共用组件）；
    #    ③ "· 可退"那行只许出现在一个文件里（再抄一份立刻红）。
    lines_ui = read(ANDROID / "ui/common/Components.kt")
    c.present("逐行退货编辑器只此一处（OrderReturnLines）", lines_ui, r"fun OrderReturnLines\(")
    c.present("上限由调用方传进来（编辑器自己不重算）", lines_ui, r"enabled = qty < max")
    c.present("退货弹窗逐行勾数量（走共用编辑器）", screen, r"onSetQty = \{ id, qty -> vm\.setReturnQty\(id, qty\) \}")
    c.present("界面上的可退上限与后端同一份（vm.maxReturnable）", screen, r"maxReturnable = \{ vm\.maxReturnable\(it\) \}")
    return_screens = [p for p in (ANDROID / "ui").rglob("*.kt") if "vm.returnQty" in read(p)]
    c.ok(
        f"有退货弹窗的页面都用同一份编辑器（从源码算到 {len(return_screens)} 个）",
        len(return_screens) >= 2 and all("OrderReturnLines(" in read(p) for p in return_screens),
        f"页面={[p.name for p in return_screens]}，"
        f"没用的={[p.name for p in return_screens if 'OrderReturnLines(' not in read(p)]}",
    )
    dup_lines = [p.name for p in (ANDROID / "ui").rglob("*.kt") if "· 可退" in read(p)]
    c.ok(
        "「· 可退」那一行只许在一个文件里（再抄一份编辑器就会出现两处）",
        len(dup_lines) == 1,
        f"出现在 {dup_lines}",
    )
    card = read(ANDROID / "ui/common/OrderCard.kt")
    c.present("下单人=货主 时不再重复画货主那一行", card, r"ordererIsShipper\(order\.contactBossName")
    c.present("那条判据只有一处实现（卡片与详情共用）", card, r"internal fun ordererIsShipper\(")

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项不通过：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过：退货与按商品核销的**钱**只有一处算法，客户端只显示不重算。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
