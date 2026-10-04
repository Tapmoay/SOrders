# -*- coding: utf-8 -*-
"""**钱路 provenance（计价来源）判据**：一笔历史金额，能不能说清"它凭什么是这个数"。

R4-BOUNDARY-JUSTIFICATION: **代码边界解决不了这件事，因为缺口长在"少写了一格"上。**

一个金额被写进库里、而"产生它的规则"没被写下来 —— 单看**任何一个文件**都是合法的：
`orders_assignment.py` 那一刻手里就有 `Quote.matched.template_id`，然后只写了
`freight_fee` 与分类，语法正确、事务正确、测试通过、金额也对。错的只有一件事：
**那一格没落库**。而"哪些钱必须有来源"只存在于**整张图**里（全部 `Numeric` 列 ×
谁是配置 / 谁是算出来的），不存在于任何单个文件里 —— 所以这一条只能是对账式的，
与 `_check_data_ownership.py` 属于同一类（指南 §14 那个"代码上完全看不出来"的坑）。

**反向破坏用例**（`_tools/qa/_reverse_verify_pricing_provenance.py`，六种）：
给订单补上价目身份列（棘轮必须响）／给订单加契约版本列／拿掉账单的 `rule_id`／
让快照读一个写不进去的键／让算钱那一步能拿到活用户／加一个没人归类的钱列 ——
每一种都必须当场报红，还原后必须恢复。

**静默空转保护**：① 清单**自己算**（遍历 mapper 的 `Numeric` 列，⛔ 不手写）；
② 「扫到 ≥30 个金额列」的下限（枚举失效时先喊，而不是安静地全绿）；
③ 分类表**双向**核对（未归类红、化石也红）—— 少了任何一条，"什么都不看"也会全绿。

⛔ 本判据**不检查金额对不对**：它只回答"这个金额凭什么"，不回答"算得对不对"。

## 为什么要有它（用户 2026-09-27 的原话）

> 「一个订单最终使用的"计价规则版本"在哪里留下事实？……如果系统只知道 `order_id = A`
>  而不知道当时采用的 `Pricing Rule = v1`，那么历史事实就无法可靠重建。」
>
> 「**能重新计算 ≠ 能证明历史为什么是这个金额。**」

这是 **Money correctness prerequisite（资金正确性前置条件）** —— 不是模块化问题。
在把任何扩展接进钱路之前，先要能回答这个问题。

## 判据的形状（清单**自己算**，不手写）

1. **每一笔钱都必须被归类** —— 遍历 SQLAlchemy mapper 的**全部 `Numeric` 列**，
   逐个核对它在下面四张表里**恰好出现一次**：
   `CONFIG`（配置/入参，不是算出来的）/ `SELF`（自描述：产生它的输入就在同一行）/
   `RULED`（由规则算出来 → **必须有 provenance**）/ `NO_PROVENANCE`（**缺口**：有书面理由，
   且理由必须**仍然成立**）。坐标列由名字形状认出，不算钱。
   ⛔ 新增一个钱列而没归类 → 当场红（"给 AI 开一条后路"的规矩）。
2. **`RULED` 那一档的 provenance 必须真的在**（列在 / 快照读写同源 / 那个算法读不到活配置）。
3. **`NO_PROVENANCE` 那一档的缺口必须仍然是真的** —— 化石棘轮：
   有人把事实记录补上了，这条会红，逼着把条目挪进 `RULED` **并同步文档**。
4. **契约版本**：核心事实里没有任何一列（也没有生产快照写入器）记录"这笔金额按**哪一版计价契约**算的"
   —— 同样带化石棘轮（补上了就红，逼你改这里）。
5. `--check` 模式只印结论一行（进 `_check_all.py` 的必跑组靠它）。

## 它与 R4 的关系

R4 证明的是"扩展可以被添加 / 替换 / 拆除，核心不跟着改"。
它**没有**证明"扩展算出来的钱，事后能说清是哪个扩展的哪一版算的"。
这一条判据就是那道门：**过不了它，就不该把扩展接进生产钱路。**

用法：
    python _tools/qa/_check_pricing_provenance.py            # 详细
    python _tools/qa/_check_pricing_provenance.py --check    # 必跑模式（一行结论）
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
# 只读审计：库指到临时目录，别在仓库里建出 app.db
os.environ.setdefault(
    "DATABASE_URL", "sqlite:///" + (Path(tempfile.mkdtemp()) / "prov.db").as_posix()
)
sys.path.insert(0, str(BACKEND))

import app.main  # noqa: E402,F401  —— 导入真正的 app，让枚举看到应用实际注册的全部模型
from sqlalchemy import Numeric  # noqa: E402

from app.models.base import Base  # noqa: E402

DRIVER_PAY = BACKEND / "app" / "services" / "driver_pay.py"
ORDER_MONEY = BACKEND / "app" / "services" / "order_money.py"
ASSIGN_API = BACKEND / "app" / "api" / "v1" / "orders_assignment.py"
BOOTSTRAP = BACKEND / "app" / "core" / "schema_bootstrap.py"
MIGRATIONS = BACKEND / "app" / "migrations"
MIGRATION_009 = MIGRATIONS / "009_freight_rule_snapshot.py"

#: 承运运费的**唯一写入口**所在文件（判据 3b：全仓 `.freight_fee =` 只许出现在这里）。
FREIGHT_WRITE_ALLOWED = {"backend/app/services/order_money.py"}

#: 命中赋值但**不是订单事实**的地方（豁免要写清理由，且锚点必须仍然存在 —— 防化石）。
FREIGHT_WRITE_EXEMPT = {
    "backend/app/api/v1/order_templates.py":
        "订单**模板**的预设运费（配置：新建订单时带过去的默认值，不是任何一张单的事实）",
}
FREIGHT_WRITE_EXEMPT_ANCHOR = "tpl.freight_fee = _money(body.freight_fee, "

#: 快照必须能恢复的东西（用户 2026-09-27 §五 P1-02c）—— 键路径 → 人读的名字。
PROVENANCE_REQUIRED: tuple[tuple[tuple[str, ...], str], ...] = (
    (("source",), "pricing source（这一次运费怎么产生的）"),
    (("pricing", "kind"), "pricing kind（用了什么计价方式）"),
    (("pricing", "contract", "name"), "pricing contract（属于哪一版计价契约）"),
    (("pricing", "contract", "version"), "pricing contract version"),
    # ⭐ R4-36：`kind` 只回答"金额最终由谁产生"，回答不了"这一次是怎么走到那一步的"——
    #    少了 resolution，legacy_client + reason=ok 会同时盖住"没抽中"与"已冻结沿用旧路"。
    (("pricing", "resolution"), "pricing resolution（这一次走的是哪条路）"),
    (("category",), "effective calculation context（按哪一类货算的）"),
    (("rule",), "哪一条价目"),
    (("fee",), "final fee（当时的金额）"),
)


def _dig(obj, path: tuple[str, ...]):
    cur = obj
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


class _FakeOrder:
    """一个只有那四列的假订单 —— 让**真的**写入口在判据里跑一遍（⛔ 不是文本匹配）。"""

    freight_fee = None
    freight_category_id = None
    freight_category = ""
    freight_rule_snapshot = None


def scan_freight_fee_writes() -> list[str]:
    """全仓扫 `.freight_fee =` 的赋值（注释行不算），返回白名单之外的。"""
    hits: list[str] = []
    for p in sorted((BACKEND / "app").rglob("*.py")):
        rel = p.relative_to(ROOT).as_posix()
        if rel in FREIGHT_WRITE_ALLOWED or rel in FREIGHT_WRITE_EXEMPT:
            continue
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            # ⚠️ 点号必须转义：不转义时 ".freight_fee" 会退化成 ".freight_fee"，
            #    而那个点能匹配任意字符 —— 于是一句**关键字实参** `freight_fee=None,`
            #    也会被当成"越界赋值"（本判据第一版就是这么误报的，实测抓到自己）。
            if re.search(r"\.freight_fee\s*=", ln.split("#", 1)[0]):
                hits.append(f"{rel}:{i}")
    return hits

# ---------------------------------------------------------------- 四张分类表
# ⛔ 规则：**每一条都必须仍然成立**。加了钱列不归类 → 红（第 1 组）；
#    分类表里留着一个已经不存在的列 → 红（化石，第 1 组）。

#: 配置 / 入参 / 快照：是"别人给进来的数"或"它自己就是快照"，不是"系统按规则算出来的金额"。
CONFIG = {
    "products.default_unit_price": "商品默认价（配置）",
    "products.cost_price": "商品成本价（配置）",
    "product_cost_history.cost_price": "成本价变更历史（它自己就是历史）",
    "price_rules.special_unit_price": "批发商专属价（配置）",
    "freight_templates.fee": "运费价目（配置；历史单不引用它 —— 见 NO_PROVENANCE）",
    "order_templates.freight_fee": "订单模板的预设运费（配置）",
    "driver_billing_rules.salary": "司机计费规则：固定工资（配置）",
    "driver_billing_rules.piece_amount": "司机计费规则：每单/每件金额（配置）",
    "driver_billing_rules.commission_rate": "司机计费规则：提成比例（配置）",
    "driver_billing_rule_categories.piece_amount": "按分类的每单金额（配置）",
    "driver_billing_rule_categories.commission_rate": "按分类的提成比例（配置）",
    "users.salary": "司机个人工资（配置）",
    "unit_conversions.factor": "单位换算系数（扩展配置：R4-04 的 unit_conversion 扩展）",
    "inventory_movements.unit_cost": "出入库单价（录入即事实）",
    "ledgers.unit_price": "账本行单价（录入/同步即事实）",
    "ledgers.cost_price_snapshot": "账本行成本快照（它自己就是快照）",
    "order_products.unit_price": "订单行单价（下单时谈定的价，值即事实）",
    "order_products.cost_price_snapshot": "订单行成本快照（它自己就是快照）",
    "orders.driver_piece_amount": "派单员对这一单单独定的金额（值即事实）",
    "orders.driver_commission_rate": "派单员对这一单单独定的比例（值即事实）",
    "expenses.amount": "开销金额（录入即事实）",
    "cash_flows.amount": "现金流水金额（录入即事实）",
    "shipper_receipts.amount": "货主收款金额（录入即事实）",
    "supplier_payables.amount": "供应商应付金额（录入即事实）",
    # FEAT-0013：采购单明细的单价就是 row 输入（建单/改单时人填的价），
    # 它与它写出的 `inventory_movements.unit_cost` 同源 —— 不是算出来的，归 CONFIG。
    "purchase_order_items.unit_cost": "采购单价（录入即事实：建单/改单时人填的价，不是算出来的）",
    "shipper_settlements.amount": "货主核销金额（录入即事实）",
    "shipper_settlement_lines.amount": "核销明细金额（录入即事实）",
    # ---- 车辆属性（2026-09-28 · FEAT-0001）：**派单员建车时量了填进来的事实**，
    # 与 `unit_conversions.factor` 同一档（都是"别人给进来的数"，不是系统按规则算出来的）。
    # ⛔ **它们不是钱**：目前**一个消费点都没有**（接进换算是 FEAT-0005，而那一步也
    #    只作用于**数量的显示**，"钱一个字节都不动"是 2026-09-24 就定死的口径）。
    # ⚠️ 为什么逐列登记、不写一条通配：判据第 1 组是「每一列**恰好**落在一张表里」——
    #    通配会让"以后往 vehicles 里加一个真的金额列"也顺带免检。
    "vehicles.height_m": "车辆属性：车高(米)（建车时量了填进来的事实）",
    "vehicles.width_m": "车辆属性：车宽(米)（同上）",
    "vehicles.curb_weight_t": "车辆属性：净重(吨)（同上）",
    "vehicles.load_tons": "车辆属性：载重(吨)（同上；⭐ 以后参与「一车 = 多少吨」的**数量显示**）",
    "vehicles.volume_cubic": "车辆属性：容积(方)（同上；⭐ 以后参与「一车 = 多少方」的**数量显示**）",
    "vehicles.cargo_length_m": "车辆属性：载货区长(米)（同上）",
    "vehicles.cargo_width_m": "车辆属性：载货区宽(米)（同上）",
    "vehicles.cargo_height_m": "车辆属性：载货区高(米)（同上）",
    # ---- 折旧台账四格里的三格（2026-10-04 · FEAT-0012 第二期）：**录入即事实**，
    # 与上面那批车辆属性同一档 —— 它们是**折旧的输入**，不是系统按规则算出来的金额。
    # ⛔ 折旧额本身（每月多少钱）**永不落库**（`services/vehicle_depreciation.py` 按窗口现算），
    #    所以这里没有"由规则算出来的钱列"，也就没有 provenance 缺口。
    # ⚠️ 第四格 `purchase_date` 是日期列不是 Numeric，本来就不在这份清单里。
    "vehicles.purchase_price": "折旧的输入：购置价（元；建车/补录时录入的事实）",
    "vehicles.useful_life_years": "折旧的输入：使用年限（年；同上）",
    "vehicles.residual_rate": "折旧的输入：残值率（0–0.5；同上，留空 = 0%）",
    # ---- 司机结算单的手工调整额（2026-10-03 · BUG-0007）：建单时派单员**手填进来的差额**
    # （不是系统按规则算出来的），从此恒等式 `amount == 明细合计 + adjustment` 在确认与
    # 付款两处都成立 —— 所以它归「录入即事实」这一档，不是 RULED。
    "driver_settlements.adjustment": "结算单的手工调整额（建单时录入即事实；恒等式 amount == 明细合计 + adjustment）",
}

#: 坐标：名字是 lat/lng 的那几个，与钱无关。
COORD_NAMES = {
    "address_lat", "address_lng", "origin_lat", "origin_lng", "lat", "lng",
}

#: 自描述：产生它的输入**就在同一行**，所以这一行自己就能重建它。
SELF = {
    "order_products.line_total": "= quantity × unit_price（两个输入都在同一行）",
    "ledgers.total": "= quantity × unit_price（两个输入都在同一行）",
}

#: 由**规则/算法**算出来 → 必须能在同一行（或它引用的那份快照）上找到"产生它的规则"。
RULED = {
    "driver_bills.amount": {
        "where": "orders.driver_rule_snapshot（派单那一刻定格的规则）+ driver_bills.rule_id / rule_name",
        "why": "送达生成账单用的是快照；司机后来换规则不改已送完的单",
    },
    "driver_bills.piece_amount": {
        "where": "同上（快照里的 piece_amount / by_category）",
        "why": "账单要能独立复核是按什么算的",
    },
    "driver_bills.commission_amount": {
        "where": "同上（快照里的 commission_base × commission_rate）",
        "why": "提成也来自同一份快照",
    },
    "driver_settlements.amount": {
        "where": "driver_settlement_lines.amount 的合计（逐单指向 driver_bills / orders）",
        "why": "结算单是聚合，来源逐单可查"
               "（2026-10-03 BUG-0007：取数只有 settleable_bills 一处，确认/付款按建单当刻"
               "锁定的 bill_ids 认账，恒等式 amount == 明细合计 + adjustment）",
    },
    "orders.freight_fee": {
        "where": "orders.freight_rule_snapshot（同一行、同一个事务、同一次定价决定）",
        "why": "R4-11 补上的：这笔承运价出自哪条价目、按什么计价方式、属于哪一版计价契约、"
               "当时算出来多少 —— 全在那份快照里；写入口只有 "
               "services/order_money.record_freight_decision 一处",
    },
}

#: ⛔ **缺口**（有书面理由；理由必须**仍然成立** —— 补上了就红，逼你改成 RULED）。
#:
#: ⭐ 2026-09-27（R4-11）：这里原来躺着 `orders.freight_fee` —— R4-P1 的审计查出来的那个缺口。
#: 现在它**已经补上**（挪进了 RULED），所以这张表空了。
#: ⛔ **空着是结论，不是漏了**：判据第 1 组仍然要求每一列恰好落在一张表里，
#:    新的缺口不会因为"这里空着"而被放过 —— 它只会以"未归类"的形式当场报红。
NO_PROVENANCE: dict[str, str] = {}

#: 记录"按哪一版计价契约算的"的列名形状（现在核心事实里**一处都没有**）。
CONTRACT_VERSION_RE = re.compile(
    r"(pricing_kind|pricing_version|contract_version|rule_version|pricing_contract)",
    re.IGNORECASE,
)


def numeric_columns() -> list[str]:
    """枚举**应用实际注册的**全部 Numeric 列 → ["表.列"]（清单自己算，不手写）。"""
    out: list[str] = []
    for t in Base.metadata.sorted_tables:
        for c in t.columns:
            if isinstance(c.type, Numeric):
                out.append(f"{t.name}.{c.name}")
    return out


def is_coord(col: str) -> bool:
    return col.rsplit(".", 1)[1].lower() in COORD_NAMES


def func_body(path: Path, name: str) -> str:
    """取一个顶层函数的源码正文（到下一条 `def ` / 分隔线为止）。"""
    text = path.read_text(encoding="utf-8")
    m = re.search(rf"^def {re.escape(name)}\(", text, re.M)
    if not m:
        raise SystemExit(f"{path.name} 里找不到函数 {name} —— 判据要跟着改")
    rest = text[m.end():]
    nxt = re.search(r"^(?:def |# -{3,})", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def main() -> int:
    check = "--check" in sys.argv
    fails: list[str] = []
    passes = 0

    def ok(label: str, cond: bool, detail: str = "") -> None:
        nonlocal passes
        if cond:
            passes += 1
            if not check:
                print(f"  [OK]   {label}")
        else:
            fails.append(label + (f" —— {detail}" if detail else ""))
            print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))

    actual = numeric_columns()
    coords = [c for c in actual if is_coord(c)]
    declared = list(CONFIG) + list(SELF) + list(RULED) + list(NO_PROVENANCE)

    if not check:
        print("== 1. 每一笔钱都必须被归类（清单自己算：遍历 mapper 的 Numeric 列）==")
    ok(f"扫到 {len(actual)} 个金额列（含坐标 {len(coords)} 个）", len(actual) >= 30)
    dup = [k for k in declared
           if [k in CONFIG, k in SELF, k in RULED, k in NO_PROVENANCE].count(True) > 1]
    ok("同一个列没有同时出现在两张分类表里", not dup, f"重复：{dup}")
    unclassified = [c for c in actual if c not in set(declared) and not is_coord(c)]
    ok("没有**未归类**的钱列（新增钱列必须归类，否则这条就红）", not unclassified,
       f"未归类：{unclassified}（放进 CONFIG / SELF / RULED / NO_PROVENANCE 之一）")
    ghost = [k for k in declared if k not in actual]
    ok("分类表里没有**化石**（列已经不存在了）", not ghost, f"不存在：{ghost}")

    if not check:
        print("\n== 2. RULED 那一档：provenance 必须真的在 ==")
    order_cols = {c.name for c in Base.metadata.tables["orders"].columns}
    bill_cols = {c.name for c in Base.metadata.tables["driver_bills"].columns}
    ok("orders.driver_rule_snapshot 列在（RULED 的 provenance 就指着它）",
       "driver_rule_snapshot" in order_cols)
    ok("driver_bills 上有 rule_id / rule_name（账单能独立复核是按什么算的）",
       {"rule_id", "rule_name"} <= bill_cols,
       f"缺：{sorted({'rule_id', 'rule_name'} - bill_cols)}")

    # 2c. 快照的**写**与**读**必须同源：漏一个键 = 历史金额重建不出来（静默错的那一类）
    to_body = func_body(DRIVER_PAY, "rule_to_snapshot")
    from_body = func_body(DRIVER_PAY, "rule_from_snapshot")
    written = set(re.findall(r'"([a-z_]+)"\s*:', to_body))
    read = set(re.findall(r'\.get\("([a-z_]+)"\)', from_body))
    ok(f"快照写出的键 ⊇ 读回的键（写 {len(written)} 个 / 读 {len(read)} 个）",
       read <= written,
       f"读得到但写不进去：{sorted(read - written)}（快照里没有 → 历史金额重建不出来）")
    ok("快照里带着 rule_id（能指回那条规则）", "rule_id" in written)

    # 2d. **算钱的那一步拿不到活配置** —— 它只认一份已经定格的规则。
    #     ⚠️ 第一版这条写的是"driver_pay.py 不 import app.models"，实测**过严**：
    #     那个文件确实在几处**函数体内** import 了 Model（`resolve_billing_mode` /
    #     `DriverBill` / `Order`），但那些都不是"取规则来算钱"。判据要钉的是**取规则那一步**，
    #     不是"这个文件永远不许提 models"（过严的判据要么被绕过，要么逼人做假）。
    pay_text = DRIVER_PAY.read_text(encoding="utf-8")
    sig_m = re.search(r"def order_pay\((.*?)\)\s*->", pay_text, re.S)
    sig = sig_m.group(1) if sig_m else ""
    ok("算钱的那一步（order_pay）收的是 PayRule，不是活用户 / 活规则 / 数据库会话",
       bool(sig) and "PayRule" in sig and not re.search(r"\b(db|session|user)\b", sig),
       "签名：" + repr(sig.strip()[:120]))
    pfo = func_body(DRIVER_PAY, "pay_for_order")
    ok("订单 → 应得 只经 rule_from_snapshot 取规则（读不到活规则）",
       "rule_from_snapshot(" in pfo
       and "driver_rule_id" not in pfo and "DriverBillingRule" not in pfo,
       "它一旦按活规则算，司机换一次规则，已送完的单金额就跟着变")

    if not check:
        print("\n== 3. 承运运费：金额与来源凭据必须**同处写**（R4-11）==")
    # 3a 列在
    ok("orders.freight_rule_snapshot 列在（承运运费的来源凭据就住在这儿）",
       "freight_rule_snapshot" in order_cols)
    # 3b **唯一写入口**：全仓 .freight_fee 的赋值只许出现在白名单里。
    #    ⚠️ 这是"钱只算一处"那条规矩的静态形态：两个写入口 = 迟早出现
    #    "订单 135、账单 120" 这种两边都不报错的分叉。
    stray = scan_freight_fee_writes()
    ok(f".freight_fee 的赋值只出现在唯一写入口里（越界 {len(stray)} 处）", not stray,
       f"越界：{stray} ⇒ 改走 order_money.record_freight_decision（金额与凭据必须一起写）")
    tmpl_src = (BACKEND / "app" / "api" / "v1" / "order_templates.py").read_text(encoding="utf-8")
    ok(f"豁免表里的理由**仍然成立**（{len(FREIGHT_WRITE_EXEMPT)} 条，锚点还在）",
       FREIGHT_WRITE_EXEMPT_ANCHOR in tmpl_src,
       "订单模板那一处已经不是原文了 —— 豁免要跟着复核，⛔ 不许留化石")
    # 3c 三个写入点都走同一个入口
    ap = ASSIGN_API.read_text(encoding="utf-8")
    n_calls = ap.count("record_freight_decision(")
    ok(f"三个写入点都走同一个入口（扫到 {n_calls} 处调用）", n_calls >= 3,
       "手动定价 / 派单 / 事后补录 —— 少一处就有一类运费没有来源凭据")
    # ⚠️ 判据要认**实参形态**（source=FREIGHT_SOURCE_X），不能只认常量名 ——
    #    常量名在 import 那行也出现，于是"某一处改成了裸字符串"这种绕过会**静默变绿**。
    ok("三个写入点各自说清了自己是哪种来源（manual / assign / adjust）",
       all(("source=" + s) in ap for s in ("FREIGHT_SOURCE_MANUAL", "FREIGHT_SOURCE_ASSIGN",
                                           "FREIGHT_SOURCE_ADJUST")),
       "有一处没写 source 常量 ⇒ 那一次定价的来源说不清（也可能被改成了裸字符串）")

    # 3d ⭐ **把真的写入口跑一遍**（不是文本匹配）：五样东西必须都能从快照里恢复（用户 P1-02c）
    from app.services.order_money import (  # noqa: E402
        freight_provenance_of,
        record_freight_decision,
    )

    o = _FakeOrder()
    record_freight_decision(o, source="manual", fee=Decimal("120"), category_id=3,
                            category_name="蔬菜", resolution="not_in_canary",
                            rule={"template_id": 12, "fee": "120.00", "origin": "saved"})
    snap = freight_provenance_of(o)
    ok("写入口把金额写成两位小数（120 → 120.00）", str(o.freight_fee) == "120.00",
       f"实际 {o.freight_fee!r}")
    ok("快照里的 fee 与订单金额**一致**（不一致就是这条判据要拦的那种错位）",
       snap.get("fee") == str(o.freight_fee), f"快照 {snap.get('fee')!r} vs 订单 {o.freight_fee!r}")
    for path, label in PROVENANCE_REQUIRED:
        v = _dig(snap, path)
        ok(f"快照能恢复「{label}」", v not in (None, "", {}),
           f"缺 {'.'.join(path)} ⇒ 这份快照回答不了「这个数凭什么」")
    ok("快照里记着**价目身份**（rule.template_id）—— 这正是 R4-P1 审计查出来的那个缺口",
       _dig(snap, ("rule", "template_id")) == 12)
    ok("快照带着自己的格式版本 v（将来加字段时读得懂老快照）",
       _dig(snap, ("v",)) == 1)

    # 3d-2 ⭐ **原因码**（R4-21 生产观察逼出来的）：退回旧路必须说清是哪一种
    #     —— 第一版只有一句笼统的"契约没算出结论"，在生产上拿到之后还得去查库才知道是哪种。
    from app.core.pricing_runtime import REASON_TEXT
    from app.core import pricing_runtime as _rt
    codes = sorted(v for k, v in vars(_rt).items()
                   if k.startswith("REASON_") and isinstance(v, str))
    ok(f"原因码是**一组互不相同的**取值（{len(codes)} 个：{'/'.join(codes)}）",
       len(codes) == len(set(codes)) and len(codes) >= 5)
    ok("每个原因码都配了一句人话（⛔ 不许有解释不了的原因码）",
       set(codes) <= set(REASON_TEXT), "缺解释：" + str(sorted(set(codes) - set(REASON_TEXT))))
    o4 = _FakeOrder()
    record_freight_decision(o4, source="assign", fee=Decimal("88"),
                            kind="legacy_client", reason="no_candidates",
                            resolution="fallback")
    # ⭐ R4-36：`resolution` 必须**与 kind 正交**地落进快照 —— 否则「没抽中」与
    #    「已冻结沿用旧路」写出来一模一样，生产上分不出来（T0/T1/T2 就是这么卡住的）。
    ok("写入口把「这一次走的是哪条路」写进快照（pricing.resolution）",
       _dig(freight_provenance_of(o4), ("pricing", "resolution")) == "fallback")
    from app.core.pricing_runtime import RESOLUTIONS  # noqa: E402
    ok("resolution 是一组互不相同的取值，且**恰好四个**（增加值必须来这里报到）",
       len(set(RESOLUTIONS)) == len(RESOLUTIONS) and set(RESOLUTIONS) ==
       {"contract", "fallback", "not_in_canary", "frozen"}, str(RESOLUTIONS))
    ok("写入口把原因码原样写进快照（pricing.reason）",
       _dig(freight_provenance_of(o4), ("pricing", "reason")) == "no_candidates")
    ok("没给原因码时**不编**一个（⛔ 不许写假原因）",
       "reason" not in _dig(freight_provenance_of(o), ("pricing",)) if isinstance(
           _dig(freight_provenance_of(o), ("pricing",)), dict) else False)

    # 3e 不变量：清空金额时凭据**一起**清空（同生共死）
    o2 = _FakeOrder()
    record_freight_decision(o2, source="adjust", fee=None)
    ok("清空运费时来源凭据一起清空（不变量：金额与凭据同生共死）",
       o2.freight_fee is None and o2.freight_rule_snapshot is None,
       f"金额 {o2.freight_fee!r} / 凭据 {(o2.freight_rule_snapshot or '')[:20]!r}")
    o3 = _FakeOrder()
    o3.freight_rule_snapshot = "{这不是 JSON"
    ok("坏掉的快照当「没有」（⛔ 不抛：一份脏 JSON 不该让订单详情 500）",
       freight_provenance_of(o3) == {})
    ok("老单（R4-11 之前落库、这一列为 NULL）读出来就是「没有来源」—— 不猜、不补",
       freight_provenance_of(_FakeOrder()) == {})

    # 3f 迁移在，而且**不回填**
    # ⚠️ 机制选择是判据的一部分（R4-11 当天改过一次）：migrations/README.md 的分工是
    #    「**正式变更**走 migrations/、**运行时自愈**走 schema_bootstrap」，
    #    加一列是正式变更 ⇒ 它必须是一条迁移。⛔ 两处都写 = 同一个事实两个来源。
    mig = MIGRATION_009.read_text(encoding="utf-8")
    ok("009_freight_rule_snapshot 迁移里加了这一列（正式变更走 migrations/）",
       "freight_rule_snapshot" in mig and "ADD COLUMN" in mig)
    ok("⛔ schema_bootstrap 里**没有**重复这一列（否则就成了两个来源）",
       "ADD COLUMN freight_rule_snapshot" not in BOOTSTRAP.read_text(encoding="utf-8"),
       "bootstrap 是**运行时自愈**，正式变更不该落在那里（migrations/README.md 的分工）")
    # 回填要**全目录**扫：只扫一个文件的话，换个地方偷偷 UPDATA 一下就绕过去了
    mig_text = "\n".join(p.read_text(encoding="utf-8")
                            for p in sorted((BACKEND / "app" / "migrations").glob("*.py")))
    all_ddl = mig_text + "\n" + BOOTSTRAP.read_text(encoding="utf-8")
    ok("迁移**不回填老数据**（用户 §3：猜着补快照 = 伪造历史事实）",
       not re.search(r"UPDATE\s+orders\s+SET[^\n]*freight_rule_snapshot", all_ddl, re.I),
       "出现了回填语句 —— 那会把「当时的价目」编出来")

    # 3h ⛔ 指南 §8：**唯一组装点** —— 业务代码里一个开关都不许有（R4-20）
    root = (BACKEND / "app" / "core" / "pricing_runtime.py").read_text(encoding="utf-8")
    ok("组装点在（core/pricing_runtime.py：decide + policy_for）",
       "def decide(" in root and "def policy_for(" in root)
    # ⚠️ 扫的是**代码形态**（调用 / 取属性），不是「出现过 Canary 这个词」——
    #    第一版扫的是裸词，于是那两处**注释里解释"这里没有开关"**的说明被扫红了（假红）。
    #    判据要认的是 `policy_for(` / `canary_percent(` / `freight_pricing_canary`
    #    这种**真的在用**的形状。
    SWITCH = re.compile(r"policy_for\(|canary_percent\(|freight_pricing_canary")
    for rel in ("app/api/v1/orders_assignment.py", "app/services/accounting_service.py",
                "app/services/driver_pay.py", "app/services/order_money.py"):
        hits = [ln.strip() for ln in (BACKEND / rel).read_text(encoding="utf-8").splitlines()
                if SWITCH.search(ln.split("#", 1)[0])]
        ok(rel + " 里**没有计价开关**（policy_for / canary_percent）—— 换算法只改组装点",
           not hits, "业务代码里长出了开关：" + str(hits[:2])
                     + "（指南 §8 点名的「R4 又开始腐烂」那种形状）")
    # ⚠️ 这一条与 `_check_extension_dependencies.py` 第 1 组是**同一件事的两面**：
    #    那一条管"核心不许 import 具体扩展"，这一条管"解析器只在**装配根**接一次"。
    #    第一版我把 `from app.extensions.pricing import resolve_v2` 写进了
    #    `core/pricing_runtime.py` —— 当场被那条判据抓到（「核心反向依赖了具体扩展」），
    #    于是改成**依赖倒置**：核心只留一个槽位，装配根填。
    callers = sorted(p.relative_to(ROOT).as_posix() for p in (BACKEND / "app").rglob("*.py")
                     if "resolve_v2(" in p.read_text(encoding="utf-8"))
    allowed = {"backend/app/main.py", "backend/app/extensions/pricing/__init__.py"}
    ok("resolve_v2( 只在**装配根**与扩展包里出现（其它地方一处都不许有）",
       set(callers) <= allowed, "多出来的地方：" + str([c for c in callers if c not in allowed]))
    ok("核心只留**槽位**、不认识具体扩展（register_pricing_resolver / pricing_resolver）",
       "def register_pricing_resolver(" in root and "def pricing_resolver(" in root)
    cfg = (BACKEND / "app" / "config.py").read_text(encoding="utf-8")
    ok("Canary 开关**缺省是关**（freight_pricing_canary_percent: int = 0）",
       re.search(r"freight_pricing_canary_percent:\s*int\s*=\s*0", cfg) is not None,
       "新东西默认必须是关的（与本仓库对 AI 写闸门那条规矩一致）")

    # 3g 旁证：价目身份**在派单那一刻是拿得到的**（所以当年那个缺口是"被丢掉了"，不是"没有"）
    fp = (BACKEND / "app" / "services" / "freight_pricing.py").read_text(encoding="utf-8")
    ok("价目身份在派单那一刻拿得到（Candidate.template_id / quote_for 返回它）",
       "template_id" in fp and "def quote_for" in fp)
    ok("quote_for 是**只读**的（不写库）：历史金额没有被它悄悄重算",
       "db.commit" not in fp and "db.add(" not in fp)

    if not check:
        print("\n== 4. 契约版本：**驱动那一路**仍然一处都没记（承运那一路已经补上了）==")
    # ⚠️ 这一段的口径在 R4-11 变了，如实记着：
    #    审计（R4-09）当时的结论是「**三处都没有**」；R4-11 把**承运**那一路补上了
    #    （快照里的 pricing.contract —— 第 3 组现场跑过、逐个键核过）。
    #    仍然没有的是**驱动应得**那一路：它的快照里只有 rule_id / piece_mode，
    #    ⛔ 没有"按哪一版契约算的"。所以这两条判据**只管那一路**，⛔ 不许顺手删掉。
    version_cols = sorted(
        f"{t.name}.{c.name}" for t in Base.metadata.sorted_tables for c in t.columns
        if CONTRACT_VERSION_RE.search(c.name)
    )
    ok("没有任何**列**记录计价契约 / 规则版本（承运那一路记在快照 JSON 里，不占列）",
       not version_cols,
       f"现在有了：{version_cols} ⇒ 说明有人把它做成了列，把口径写清楚再改这一条")
    ok("司机计费快照写入器（rule_to_snapshot）仍然不写版本号 —— 这是**已知缺口**，不是漏判",
       not CONTRACT_VERSION_RE.search(to_body),
       "现在写了 ⇒ 那是好事（驱动那一路也补上了）：把这一条改成正面断言，"
       "并同步 docs/R4_PRICING_PROVENANCE.md §5")

    if not check:
        print("\n== 5. 汇总 ==")
        print(f"  CONFIG {len(CONFIG)} / SELF {len(SELF)} / RULED {len(RULED)} / "
              f"NO_PROVENANCE {len(NO_PROVENANCE)} / 坐标 {len(coords)} = {len(actual)}")
        print("  ⛔ 本判据**不检查金额对不对**，它只检查「这个金额凭什么」有没有留下事实。")

    if check:
        print(
            ("✅" if not fails else "❌")
            + f" 钱路 provenance：{len(actual)} 个金额列全部归类，"
            + f"RULED {len(RULED)} 项来源齐全"
            + (f"，缺口 {len(NO_PROVENANCE)} 项（已在文档里如实声明）" if NO_PROVENANCE
               else "，**缺口 0 项**（R4-09 查出来的那个已经在 R4-11 补上）")
            + ("" if not fails else f"；{len(fails)} 项不通过")
        )
    if fails:
        print(f"\n❌ {len(fails)} 项不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    if not check:
        print(f"\n✅ 全部 {passes} 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
