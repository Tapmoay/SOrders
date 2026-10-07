"""红线：批发商那层「下游价」只走他自己那本账（CHG-0077 / 台账 L-38）。

## 为什么单为这一块写一条红线

用户 2026-10-07 原话（ref m01547）：「他同样可以给他**自己的商品进行定价**，但这个定价
**只走他自己的账**……**别人欠他的就按照他自己定的价**来……同理，他也可以**给不同的人不同的价格**」。

三层价从此并列：① 商品目录价（派单员，products.unit_price）；② 给他的专属价（派单员，
price_rules.special_unit_price）；③ **他给下游的价**（他自己，shipper_prices.unit_price）。

这一块坏掉的方式**全部不报错**：

- 他定的那层价被算进**公司那本账**（或者反过来）—— 两张报表各自都"对"，客户对账时才发现差额；
- 改一次价把**老单**的历史金额一起改了 —— 已经收过的钱与应收当场对不上，而且没有任何报错；
- 快照写成「每次都覆盖」—— 表面上一切正常，历史账单在悄悄变形；
- 少一道闸（权限点 / 是不是批发商 / 有没有关掉这本账）—— 派单员能代设、普通货主也能给自己定价，
  两种都安静地写出「对谁都不生效」的价；
- 单价上限被删掉 —— 界面能存进一个把 Numeric(14,4) 撑爆的数（本机 SQLite 照收，生产 MySQL 报错）。

## 判据分七层（缺一层都等于没防住）

① 迁移与模型：新表 / 新列只从 migrations 进（schema_bootstrap 里一个字都没有），两条迁移都能重跑；
② 服务层：三层价的回落顺序、联系人匹配的四步、快照**只填 NULL**、可定价范围只有两类来源；
③ 钱：下游应收只有 order_money.line_downstream_receivable 一处算，没有快照就**逐字**退回旧口径；
④ 端点层：五个端点、三道闸、行级过滤、软删与恢复用条件 UPDATE、写与审计同一次提交；
⑤ 权限与能力：shipper_price:manage 只给 shipper，三处登记（rbac / capabilities / 审计覆盖）逐字对齐；
⑥ 客户端：入口按能力表出现、闸门不满足时不拉列表、话术逐字用后端原话；
⑦ 文档与台账：变更单、域边界、取值来源、定位表、认领行都在。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事

这一条**边界解决不了**：它管的是「**同一层价有没有被算进第二本账**」，而那件事不是哪个函数能拦住的。
line_downstream_receivable 已经是一处实现（代码边界把它锁死了），可「谁在什么时候调用它」「订单行上
的快照是不是只在下单那一刻写」「老单落库的那一列是不是 NULL」全发生在**调用点与数据里**。
所以本判据读三样东西：源码里的调用点、迁移里的 DDL、以及钱的契约（money_contract 的 forbid 正则
本身就是「别处又算了一遍」的机器判据）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_pagination_wiring import strip_comments  # noqa: E402

BACKEND = ROOT / "backend/app"
MIG27 = BACKEND / "migrations/027_shipper_prices.py"
MIG28 = BACKEND / "migrations/028_order_product_shipper_price.py"
MODEL = BACKEND / "models/shipper_price.py"
ORDER_MODEL = BACKEND / "models/order.py"
SVC = BACKEND / "services/shipper_price.py"
MONEY = BACKEND / "services/order_money.py"
CONTRACT = BACKEND / "services/money_contract.py"
SETTLE = BACKEND / "services/shipper_settle.py"
API = BACKEND / "api/v1/shipper_prices.py"
LEDGER_API = BACKEND / "api/v1/shipper_ledger.py"
SCHEMA = BACKEND / "schemas/shipper_price.py"
BOOTSTRAP = BACKEND / "core/schema_bootstrap.py"
RBAC = BACKEND / "core/rbac.py"
CAPS = BACKEND / "core/capabilities.py"
COVERAGE = BACKEND / "core/capability_audit_coverage.py"
ENUMS = BACKEND / "models/enums.py"
ROUTER = BACKEND / "api/v1/router.py"
CREATE_ORDER = BACKEND / "commands/order.py"

AND_ROUTES = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/nav/Routes.kt"
AND_MODULES = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/nav/Modules.kt"
AND_NAV = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/nav/NavGraph.kt"
AND_VM = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/ShipperPricesViewModel.kt"
AND_SCREEN = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/ShipperPricesScreen.kt"

CHG = ROOT / "docs/changes/CHG-0077.md"
CHG_README = ROOT / "docs/changes/README.md"
DOMAINS = ROOT / "docs/DOMAIN_BOUNDARIES.md"
PROVENANCE = ROOT / "_tools/qa/_check_pricing_provenance.py"
LOCATOR = ROOT / "docs/PROJECT_MAP/08_CODE_LOCATOR.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"

#: 允许出现 shipper_unit_price 参与算术的文件（实现站点与写入站点；其余地方出现就是第二份算法）
ALLOW_ARITH = {
    "backend/app/services/order_money.py",
    "backend/app/services/shipper_price.py",
    "backend/app/models/order.py",
    "backend/app/migrations/028_order_product_shipper_price.py",
    "backend/app/api/v1/shipper_prices.py",
    "backend/app/schemas/shipper_price.py",
}
ARITH = re.compile(r"\bshipper_unit_price\b\s*[-+*/]|[-+*/]=\s*[\w.]{0,24}\bshipper_unit_price\b")


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的断言要跟着改）")
    return p.read_text(encoding="utf-8")


def py_files(sub: str) -> list[Path]:
    return sorted(p for p in (ROOT / sub).rglob("*.py") if "__pycache__" not in p.parts)


def kotlin_code(src: str) -> str:
    """去掉 Kotlin 的注释（块注释 + 行尾 //），只留代码 —— 注释里提到某个名字不算「客户端认识它」。"""
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return "\n".join(re.sub(r"//.*$", "", ln) for ln in src.split("\n"))


def func_body(src: str, name: str) -> str:
    """取一个函数的函数体（到下一个顶层 def / @router. 为止）。"""
    m = re.search(rf"^def {re.escape(name)}\(", src, re.M)
    if not m:
        return ""
    rest = src[m.end():]
    nxt = re.search(r"^(?:def |@router\.)", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def block(src: str, start: str, end: str) -> str:
    """start 那段到 end 之前的文本（用于角色表那种"一大块"的断言）。"""
    i = src.find(start)
    if i < 0:
        return ""
    j = src.find(end, i + len(start))
    return src[i: j if j >= 0 else len(src)]


class Checker:
    def __init__(self) -> None:
        self.passes = 0
        self.fails: list[str] = []

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
        else:
            self.fails.append(label + (f" —— {detail}" if detail else ""))

    def present(self, label: str, text: str, pattern: str) -> None:
        self.ok(label, re.search(pattern, text, re.M) is not None, f"没找到 /{pattern}/")

    def absent(self, label: str, text: str, pattern: str) -> None:
        self.ok(label, re.search(pattern, text, re.M) is None, f"不该出现 /{pattern}/ 却出现了")


def main() -> int:
    c = Checker()

    mig27, mig28 = read(MIG27), read(MIG28)
    model, order_model, svc = read(MODEL), read(ORDER_MODEL), read(SVC)
    svc_nc = strip_comments(svc)
    money, money_nc = read(MONEY), strip_comments(read(MONEY))
    contract = read(CONTRACT)
    api = read(API)
    api_nc = strip_comments(api)
    schema_nc = strip_comments(read(SCHEMA))
    rbac, rbac_nc = read(RBAC), strip_comments(read(RBAC))
    caps = read(CAPS)
    coverage = read(COVERAGE)
    bootstrap_nc = strip_comments(read(BOOTSTRAP))
    locator = read(LOCATOR)
    chg = read(CHG)
    claim = read(CLAIM)

    recv = strip_comments(func_body(money, "line_downstream_receivable"))
    snap = strip_comments(func_body(svc, "snapshot_order_lines"))
    price_of = strip_comments(func_body(svc, "price_of"))
    find_row = strip_comments(func_body(svc, "find_row"))
    match_contact = strip_comments(func_body(svc, "match_contact"))
    allowed = strip_comments(func_body(svc, "allowed_product_ids"))
    identity = strip_comments(func_body(svc, "customer_identity"))
    set_price = strip_comments(func_body(api, "set_shipper_price"))
    delete_price = strip_comments(func_body(api, "delete_shipper_price"))
    restore_price = strip_comments(func_body(api, "restore_shipper_price"))

    # ---- ⓪ 判据自己不许空转 ----
    c.ok("取到七个关键函数的函数体（取不到下面几条就是空转）",
         all(len(x) > 200 for x in (recv, snap, price_of, match_contact, set_price, delete_price, restore_price)),
         f"长度 {[len(x) for x in (recv, snap, price_of, match_contact, set_price, delete_price, restore_price)]}")
    c.ok("find_row / allowed_product_ids / customer_identity 也取到了",
         all(len(x) > 150 for x in (find_row, allowed, identity)),
         f"长度 {[len(x) for x in (find_row, allowed, identity)]}")

    # ---- ① 迁移与模型：新表 / 新列只从 migrations 进，且都能重跑 ----
    c.present("027 是建表那条迁移（VERSION = 27）", mig27, r"^VERSION = 27\s*$")
    c.present("027 用模型建表（两种方言落到同一个形状，索引与唯一约束跟着模型走）",
              mig27, r"ShipperPrice\.__table__\.create\(bind=engine, checkfirst=True\)")
    c.present("027 能重跑（表已经在就返回）",
              mig27, r"if TABLE in set\(inspect\(engine\)\.get_table_names\(\)\):\s*\n\s*return")
    c.present("028 是加列那条迁移（VERSION = 28）", mig28, r"^VERSION = 28\s*$")
    c.present("028 能重跑（先判列在不在）",
              mig28, r'if COLUMN in \{c\["name"\] for c in insp\.get_columns\(TABLE\)\}:')
    c.present("028 加的是**可空、无默认值**的一列（可空 ⇒ 老行自然是 NULL）",
              mig28, r'ADD COLUMN \{COLUMN\} NUMERIC\(14, 4\) NULL"')
    c.absent("⛔ 028 里**没有** DEFAULT（有默认值就分不清'当时没有价'与'当时价格是 0'）",
             mig28, r"(?i)\bdefault\s+0")
    c.absent("⛔ 028 不回填老数据（按今天的价目表倒推 = 伪造历史事实）",
             mig28, r"(?i)UPDATE\s+order_products|UPDATE\s+\{TABLE\}")
    c.present("028 的读法写明了老行回落 unit_price", mig28, r"回落 unit_price")
    c.absent("⛔ core/schema_bootstrap.py 里**没有**这张表（两个来源 = 静默发布）",
             bootstrap_nc, r"shipper_prices")
    c.absent("⛔ core/schema_bootstrap.py 里**没有**这一列", bootstrap_nc, r"shipper_unit_price")
    c.present("模型：表名 shipper_prices", model, r'__tablename__ = "shipper_prices"')
    c.present("模型：唯一键 uq_shipper_price_scope(shipper_id, contact_id, product_id)",
              model, r'UniqueConstraint\("shipper_id", "contact_id", "product_id", name="uq_shipper_price_scope"\)')
    c.present("模型：contact_id 可空（NULL = 这个商品的默认下游价）",
              model, r'contact_id: Mapped\[int \| None\] = mapped_column\(\s*\n\s*ForeignKey\("shipper_contacts\.id"\), nullable=True')
    c.present("模型：单价 Numeric(14, 4)（与订单行同一个精度）",
              model, r"unit_price: Mapped\[Decimal\] = mapped_column\(Numeric\(14, 4\)\)")
    c.present("模型：注释写明唯一键**管不住**默认价那一档（NULL 互不相等）",
              model, r"SQLite / MySQL 里 NULL 互不相等")
    c.present("订单行上的快照列：可空、无默认",
              order_model, r"shipper_unit_price: Mapped\[Decimal \| None\] = mapped_column\(Numeric\(14, 4\), nullable=True\)")

    # ---- ② 服务层：可定价范围、回落顺序、匹配四步、只填 NULL ----
    c.present("可定价范围 = 他下过单的商品 ∪ 派单员给他设过专属价的商品（第一类）",
              allowed, r"Order\.shipper_id == shipper_id, OrderProduct\.product_id\.is_not\(None\)")
    c.present("可定价范围（第二类：别人已经按专属价给他供过货的）",
              allowed, r"PriceRule\.shipper_id == shipper_id, PriceRule\.is_deleted\.is_\(False\)")
    c.present("定位那一行时**不过滤** is_deleted（软删过的行仍占着这个组合，要复活它）",
              find_row, r"order_by\(ShipperPrice\.id\)\)\.first\(\)")
    c.absent("⛔ find_row 里不许出现 is_deleted 过滤（写了就会插新行 → 直接撞唯一键）",
             find_row, r"ShipperPrice\.is_deleted")
    c.present("回落顺序：先看**这个人的专属价**", price_of, r"if own is not None:\s*\n\s*return own\.unit_price")
    c.present("再回落**默认价**（contact_id IS NULL 那一档）",
              price_of, r"stmt\.where\(ShipperPrice\.contact_id\.is_\(None\)\)\)\.first\(\)")
    c.present("只认没软删的行（此刻的价只用于下单定格与界面参考）",
              price_of, r"ShipperPrice\.is_deleted\.is_\(False\),")
    c.present("匹配第一步：下单时点的那一条（验它属于他自己、且没进回收站）",
              match_contact, r"row\.shipper_id == shipper_id and not row\.is_deleted")
    c.present("匹配第二步：电话精确命中", match_contact, r"ShipperContact\.phone == phone")
    c.present("匹配第三步：姓名**必须唯一命中**（多命中就不认）",
              match_contact, r"if len\(rows\) == 1:")
    c.present("匹配第四步：都没认出来 ⇒ None（只走默认价）",
              match_contact, r"return None\s*$|return int\(rows\[0\]\.id\)")
    c.present("快照**只填 NULL**（已经带快照的行、老单永不被追改）",
              snap, r"if pid is None or op\.shipper_unit_price is not None:\s*\n\s*continue")
    c.present("没定过价的行**不写 0**，留 NULL 让下游账逐字退回订单口径",
              snap, r"if price is None:\s*\n\s*continue")
    c.present("返回定格了几行（0 = 没定过价，一切照旧）", snap, r"filled \+= 1")
    c.present("「这一单归谁」的回退与账本 / 页面**同一套**（收货人 → 下单人 → 空）",
              identity, r'order\.contact_dongjia_name or ""\)\.strip\(\) or \(order\.contact_boss_name or ""')
    c.present("身份那段注释点名了另外两处逐字同一套回退（改要一起改）",
              svc, r"ShipperLedgerGrouping\.kt::customerNameOf")

    # ---- ③ 钱：只有一处算法，没有快照就逐字退回旧口径 ----
    c.present("下游应收读的是**订单行上的快照**", recv, r"price = op\.shipper_unit_price")
    c.present("没有快照 ⇒ **原样退回** line_receivable（老单一个数都不许变）",
              recv, r"if price is None:\s*\n\s*return line_receivable\(op\)")
    c.present("有快照 ⇒ 单价 ×（数量 − 已退），q2 到分",
              recv, r"left = Decimal\(int\(op\.quantity or 0\) - int\(op\.returned_quantity or 0\)\)")
    c.present("退货按**下游单价**冲，退成 0 就是 0",
              recv, r"return q2\(Decimal\(price\) \* left\) if left > ZERO else q2\(ZERO\)")
    c.present("钱的契约里有下游应收那一条", contract, r'key="downstream_receivable"')
    c.present("契约的**实现站点**指向 order_money 那一处",
              contract, r'impls=\("services/order_money\.py::line_downstream_receivable",\)')
    c.present("契约的 forbid 正则钉着「别处又算了一遍」",
              contract, r'"shipper_unit_price_arith"')
    c.present("契约把下游应收**转出**（消费方取的永远是同一个对象）",
              contract, r'"line_downstream_receivable": \("app\.services\.order_money", "line_downstream_receivable"\)')
    c.present("账本端点取的是契约转出的那个符号",
              read(LEDGER_API), r"from app\.services\.money_contract import line_downstream_receivable, money_map")
    c.present("核销口径层（TIER0）直接 import 同一个实现，不另算一套",
              read(SETTLE), r"from app\.services\.order_money import line_downstream_receivable, q2")
    hits = []
    for p in py_files("backend/app"):
        rel = p.relative_to(ROOT).as_posix()
        if rel in ALLOW_ARITH:
            continue
        if ARITH.search(strip_comments(p.read_text(encoding="utf-8"))):
            hits.append(rel)
    c.ok("⛔ 下游单价**没有**在别处参与算术（契约那条 forbid 正则，全树扫一遍）",
         not hits, "命中：" + ", ".join(hits))
    calls = []
    for p in py_files("backend/app"):
        rel = p.relative_to(ROOT).as_posix()
        if rel == "backend/app/services/shipper_price.py":
            continue
        if re.search(r"snapshot_order_lines\(", strip_comments(p.read_text(encoding="utf-8"))):
            calls.append(rel)
    c.ok("快照**只有下单建行那一处**调用点（改单 / 转单 / 拆单 / 派单员加行都不碰它）",
         calls == ["backend/app/commands/order.py"], "调用点：" + ", ".join(calls))
    c.present("调用点在**下单**那一段里（写完 order_products 之后立刻定格）",
              strip_comments(read(CREATE_ORDER)),
              r"db\.flush\(\)[\s\S]{0,600}?shipper_price\.snapshot_order_lines\(db, order, picked_contact_id=body\.contact_id\)")
    c.absent("⛔ 定价这两个文件**不碰**订单行金额（line_total）",
             svc_nc + api_nc, r"\.line_total\s*[-+*/]?=")
    c.absent("⛔ 定价这两个文件**不碰**公司那本账（ledger / cash_flows / orders.paid）",
             svc_nc + api_nc, r"CashFlow\(|Ledger\(|sync_ledger|\.paid\s*=(?!=)")

    # ---- ④ 端点层：五个端点、三道闸、行级过滤、条件 UPDATE ----
    c.ok("恰好五个端点（products / 列表 / 设价 / 删价 / 恢复）",
         len(re.findall(r"@router\.(?:get|post|delete)\(", api_nc)) == 5,
         f"找到 {len(re.findall(r'@router[.](?:get|post|delete)[(]', api_nc))} 个")
    c.ok("静态路径 /products 写在动态路径 /{price_id} **之前**（否则被挡住）",
         api_nc.find('@router.get("/products"') < api_nc.find('@router.delete("/{price_id}"'),
         "顺序反了：遮蔽分析会判红")
    c.ok("五个端点**每个都过** _require_member（普通货主没有下游这本账）",
         len(re.findall(r"_require_member\(current\)", api_nc)) == 5,
         f"找到 {len(re.findall(r'_require_member[(]current[)]', api_nc))} 处")
    c.ok("五个端点**每个都过** _require_downstream（L-39 那本开关关掉就一起收）",
         len(re.findall(r"_require_downstream\(current\)", api_nc)) == 5,
         f"找到 {len(re.findall(r'_require_downstream[(]current[)]', api_nc))} 处")
    c.ok("五个端点**每个都挂** shipper_price:manage（权限点一处都不许漏）",
         len(re.findall(r"require_permission\(Permission\.SHIPPER_PRICE_MANAGE\)", api_nc)) == 5,
         f"找到 {len(re.findall(r'require_permission[(]Permission[.]SHIPPER_PRICE_MANAGE[)]', api_nc))} 处")
    c.present("两道闸是**从账本那边 import 过来**的，⛔ 不在本文件里复制一份",
              api, r"from app\.api\.v1\.shipper_ledger import _require_downstream, _require_member")
    c.ok("四条直查都带行级过滤（ShipperPrice.shipper_id == current.id：可定价商品 / 列表 / 删 / 恢复）",
         len(re.findall(r"ShipperPrice\.shipper_id == current\.id", api_nc)) >= 4,
         f"只有 {len(re.findall(r'ShipperPrice[.]shipper_id == current[.]id', api_nc))} 处")
    c.present("设价那一处也不靠入参：find_row 的 shipper_id 直接取 current.id（⛔ 不是从 body 取）",
              set_price, r"find_row\(\s*\n\s*db, shipper_id=current\.id,")
    c.absent("⛔ 入参里没有「替谁设」这一档（结构上就代设不了）", schema_nc, r"\bshipper_id\s*[:=]")
    c.absent("⛔ 入参里没有 order_id（这一层价不落在订单上，只在下单时定格）", schema_nc, r"\border_id\s*[:=]")
    c.present("入参继承 MoneyInput（金额上限只有 schemas/money.py 一处判）",
              schema_nc, r"class ShipperPriceSet\(MoneyInput\)")
    c.present("单价 gt=0（0 元的价目表行看着像'设过了'，实际等于白送）",
              schema_nc, r'unit_price: Decimal = Field\(\.\.\., gt=Decimal\("0"\)')
    c.present("写入口先验商品真的在（不在回收站）",
              set_price, r"if product is None or product\.is_deleted:")
    c.present("再验商品**在可定价范围里**（⛔ 不是平台上全部商品）",
              set_price, r"if body\.product_id not in shipper_price\.allowed_product_ids\(db, current\.id\):")
    c.present("联系人不属于他就是 400（⛔ 不是别人的客户）",
              set_price, r"if contact is None or contact\.shipper_id != current\.id:")
    c.present("联系人在回收站 ⇒ 告诉他先恢复（ensure_alive 那句带出路）",
              set_price, r'ensure_alive\(contact, "联系人", "先到「联系人」里把它从回收站恢复，再给他定价"\)')
    c.present("命中软删那一行时连 is_deleted 一起放回 False（否则界面上看不见这条价）",
              set_price, r"row\.is_deleted = False\s*\n\s*row\.deleted_at = None")
    c.present("只在**真的变了**时记日志（新建 / 复活 / 改价）",
              set_price, r"if created or revived or before != body\.unit_price:")
    c.ok("写入与审计**共用一次提交**（先写日志、后 commit）",
         0 <= set_price.find("write_log(") < set_price.find("db.commit()"),
         "顺序反了：价改了而日志没落")
    c.present("删价用**条件 UPDATE**（不是'读到没有 → 再写'）",
              delete_price, r"update\(ShipperPrice\)")
    c.present("删价的条件里有 is_deleted == False（判据与写入同一语句）",
              delete_price, r"ShipperPrice\.is_deleted\.is_\(False\),")
    c.present("删价检查 rowcount != 1 才拒绝（连点两下只算一次）",
              delete_price, r"if changed != 1:")
    c.present("恢复同样用条件 UPDATE，且条件里有 is_deleted == True",
              restore_price, r"ShipperPrice\.is_deleted\.is_\(True\),")
    c.present("恢复也要 rowcount != 1 才算数", restore_price, r"if changed != 1:")
    c.present("删价话术说清'以后按什么算、历史不动'（日志里也这么记）",
              api, r"删掉这个人的专属价：他回落默认下游价，没有默认价就回落订单行单价")
    c.present("恢复话术说清'只让它重新生效，不放回已经算过的钱'",
              api, r"把这条下游价放回来（价格一个字节没变）")
    c.ok("三个写端点各自记一条审计（动作码 SHIPPER_PRICE_UPSERT）",
         len(re.findall(r"OperationAction\.SHIPPER_PRICE_UPSERT", api_nc)) == 3,
         f"找到 {len(re.findall(r'OperationAction[.]SHIPPER_PRICE_UPSERT', api_nc))} 处")
    c.ok("路由注册进主 router（少这一句端点根本不存在）",
         len(re.findall(r"shipper_prices", strip_comments(read(ROUTER)))) >= 2,
         "router.py 里没找到 shipper_prices 的 import + include_router")

    # ---- ⑤ 权限与能力：三处登记逐字对齐 ----
    c.present("权限点常量 = shipper_price:manage", rbac, r'SHIPPER_PRICE_MANAGE = "shipper_price:manage"')
    shipper_block = block(rbac_nc, '"shipper": frozenset(', '),')
    c.present("给了 shipper 角色", shipper_block, r"Permission\.SHIPPER_PRICE_MANAGE,")
    dispatcher_block = block(rbac_nc, '"dispatcher": frozenset(', '),')
    driver_block = block(rbac_nc, '"driver": frozenset(', '),')
    c.absent("⛔ 派单员**没有**这个权限点（不代设、也不看他的价目表）",
             dispatcher_block, r"SHIPPER_PRICE_MANAGE")
    c.absent("⛔ 司机**没有**这个权限点", driver_block, r"SHIPPER_PRICE_MANAGE")
    c.present("能力表里有这一条（what / scope=own / roles=shipper）",
              caps, r'permission="SHIPPER_PRICE_MANAGE",\s*\n\s*what="给下游客户定自己的价')
    c.present("能力表：scope = own（行级过滤按 shipper_id）", caps, r'scope="own",\s*\n\s*scope_why="他只能定自己名下那几件商品')
    c.present("能力表：只给 shipper 角色", caps, r'roles=\("shipper",\),\s*\n\s*kind="write",')
    scope_why = "他只能定自己名下那几件商品、只对自己那本下游账生效（行级过滤按 shipper_id）"
    c.ok("rbac 的 scope_why 与能力表**逐字相同**（判据 _check_capability_registry 双向对账）",
         rbac.count(scope_why) == 1 and caps.count(scope_why) == 1,
         f"rbac {rbac.count(scope_why)} 处 / capabilities {caps.count(scope_why)} 处")
    c.present("审计覆盖表里有它（能力必须有动作码，否则审计页看不见这次改动）",
              coverage, r"'shipper_price:manage': \('SHIPPER_PRICE_UPSERT',\),")
    c.present("动作码登记进枚举", read(ENUMS), r'SHIPPER_PRICE_UPSERT = "SHIPPER_PRICE_UPSERT"')
    c.present("审计页有中文标题（不是让人看英文码）",
              ROOT.joinpath("android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt").read_text(encoding="utf-8"),
              r'"SHIPPER_PRICE_UPSERT" -> "改下游定价"')

    # ---- ⑥ 客户端：入口按能力表、闸门不满足不拉列表、话术逐字 ----
    routes = read(AND_ROUTES)
    modules = read(AND_MODULES)
    nav = read(AND_NAV)
    vm = read(AND_VM)
    screen = read(AND_SCREEN)
    c.present("路由常量 shipper/prices", routes, r'const val SHIPPER_PRICES = "shipper/prices"')
    c.present("工作台格子（货主那一栏里，插在退货申请之后）",
              modules, r'ModuleEntry\("下游定价", Routes\.SHIPPER_PRICES, Icons\.Default\.PriceChange, color = 0xFF7B1FA2L\),')
    c.present("格子的能力表门 = shipper_price:manage（没能力就不出现）",
              modules, r'Routes\.SHIPPER_PRICES to "shipper_price:manage",')
    c.present("导航图里挂上了这一页", nav, r"composable\(Routes\.SHIPPER_PRICES\) \{")
    c.present("导航图 import 了这一页",
              nav, r"import com\.tapmoay\.sorders\.ui\.shipper\.ShipperPricesScreen")
    c.present("闸门 = 是批发商 且 没关掉这本账（与账本页同一条）",
              vm, r"val canManageDownstream: Boolean get\(\) = isMember && downstreamEnabled")
    c.present("闸门不满足时**不拉价目表**（省一次请求，也避免闪过空表）",
              vm, r"if \(canManageDownstream\) \{")
    c.present("页面：闸门不满足时给的是**后端原话**（不是自己编的文案）",
              screen, r"只有批发商（高级货主）需要给下游货主核销 —— 普通货主是给自己下单、收自己的货，没有这一项")
    c.present("页面：关掉开关那一态告诉他**回哪儿打开**",
              screen, r"你已经在「我的 → 管下游的账」里关掉了这本账 —— 要记下游的核销，先回去把它打开")
    c.present("删价的结果话术：不追改已经算过的钱（用户最容易误以为'删了就少收'）",
              vm, r"已删除这条价 —— 以后下的单按新价算，已经算过的钱一分不动")
    c.present("恢复的结果话术：不放回任何已经算过的钱",
              vm, r"已恢复这条价 —— 只让它重新生效，不放回任何已经算过的钱")
    c.absent("⛔ 客户端**不认识**订单行上的快照列（钱只有后端一处算法；注释里提到不算）",
             kotlin_code(vm) + kotlin_code(screen), r"shipper_unit_price")

    # ---- ⑦ 文档与台账 ----
    c.present("变更单在、且写明了台账 L-38 与用户原话 ref",
              chg, r"台账 \*\*L-38\*\*（用户原话 ref \*\*m01547\*\*）")
    c.present("变更单：核心改动声明行写了两条（order_money / models/order）",
              chg, r"核心改动：backend/app/services/order_money\.py")
    c.present("变更单：⑦ 测试四件事那一格还在（缺一件不算完整）", chg, r"四件事都要，缺一件就不算完整")
    c.present("变更单列表里有 CHG-0077", read(CHG_README), r"CHG-0077")
    c.present("域边界：shipper_prices 归钱域（它是金额事实的输入，不是「这个人是谁」）",
              read(DOMAINS), r"owns: [^\n]*shipper_prices")
    c.present("域边界：写明了「下游应收只有一处算法」", read(DOMAINS), r"下游应收只有一处算法")
    c.present("取值来源：两条新列都归了档（都不是系统算出来的）",
              read(PROVENANCE), r'"shipper_prices\.unit_price"')
    c.present("取值来源：快照那一列也归了档",
              read(PROVENANCE), r'"order_products\.shipper_unit_price"')
    c.present("定位表里指到了本判据（改这一块的人找得到）", locator, r"_check_shipper_pricing\.py")
    c.present("定位表里有这一层价的那一行", locator, r"下游定价")
    c.present("认领行：order_money 那条核心改动声明在（改核心区必须）",
              claim, r"核心改动：\x60backend/app/services/order_money\.py\x60 —— 为什么必须动核心")
    c.present("认领行：models/order 那条核心改动声明在",
              claim, r"核心改动：\x60backend/app/models/order\.py\x60 —— 为什么必须动核心")

    total = c.passes + len(c.fails)
    if total < 45:
        print(f"❌ 只跑了 {total} 项（<45）—— 判据在空转，停。")
        return 1
    if c.fails:
        print(f"❌ 下游定价「只走他自己那本账」红线不通过（{c.passes}/{total}）：")
        for f in c.fails:
            print("   [FAIL] " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过：三层价各管一层（第三层只进他自己的账）、快照只在下单那一刻填 NULL、"
          f"下游应收只有一处算法（没有快照就逐字退回旧口径）、五个端点三道闸齐全、"
          f"软删与恢复都是条件 UPDATE、权限点只给批发商且三处登记逐字对齐、客户端闸门与话术都按后端口径。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
