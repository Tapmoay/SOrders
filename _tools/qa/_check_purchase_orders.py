"""红线：**采购单**（FEAT-0013，2026-10-04 五期计划第三期）—— 一次进货 = 库存 + 成本价 + 供应商应付。

## 由来（需求方拍板的四条口径）

```text
1. 要一张「采购单」页面（进货不再是一个商品一个商品地手工入库）
2. 存这张单要**自动生成**那张供应商应付单（不再两个页面各录一遍）
3. 录错了**允许改单**（那时候的账还没结）
4. 要看一张「成本覆盖」看板（这一段卖出去的钱里，有多少算不出成本）
```

在这之前，「进货」只有一条路：`POST /inventory/movements` 一个一个商品手工入库 ——
账上的货能变多，却记不下「这一车是从谁那儿进的、这一批花了多少钱」，供应商与应付单
在另一套表里、和进货**没有连线**：录一次采购要在两个页面各录一遍，录漏一处也没人发现。

## 形状由 `backend/app/models/purchase.py` 的三条不变量定（本文件只查值）

```text
1. 单头不存合计、明细不存金额    → 合计 = Σ(数量 × 单价)，现算（一个数落两处，早晚有一处忘了改）
2. 一行明细绑定它写下的那条流水  → movement_id：一行 = 一条流水，不是「一张单 = 一堆流水里猜的」
3. 改单是**改写**那条流水        → 不是再记一笔冲销（冲销行进不了加权均价的分母，旧价会永远留下）
```

## 这条判据守的六类事，坏起来**一条报错都不会有**

| 写坏的方式 | 表现 |
|---|---|
| 合计/金额又落一列 | 界面上「一行一行的钱加起来 ≠ 合计」，而两边都看着有理 |
| 改单改成再记一笔冲销 | 旧价永远留在加权均价里、两批货串成一个价，毛利悄悄错 |
| 撤行把成本价记成 0 | 0 被报表读成「成本是 0」= 毛利虚高（比留着旧价错得更贵）⚠️ 实测踩到过 |
| 采购模块自己 insert 一张应付 | 同一笔欠款两处可改，必然对不上；下一次改单又把它覆盖回去 |
| 写请求失败留下半成品 | 一次 400 之后账上悄悄多出一段库存 ⚠️ 实测踩到过 |
| 成本覆盖表自己再算一遍收入 | 同一个数两处口径 —— 本项目报表历史上最贵的一类缺陷 |

## 判据（清单**全部自己算**，不手写「查哪些文件」）

1. **形状**：两张表、三条不变量（合计/金额不许落列、明细绑定流水）。
2. **一个事务**：建单里三件事 + 留痕 + 提交，顺序固定；应付只有一处新建；成本价只有 `record_cost` 一个写入口。
3. **改单是改写**：同一条流水被改写，全模块只有 `_add_line` 新建流水；撤行是 `is_void` 不删行。
4. **撤行不许把成本价抹成 0**：`_reprice_product` 先 flush、排除已脱离的流水、守卫 `unit_cost is None`。
5. **失败不留半成品**：四个写端点全走 `_write(` 守卫（except 里 `db.rollback()`）。
6. **权限**：读端 `Reader`、写端 `Writer`，路由挂在 `router.py` 上。
7. **留痕**：四个动作码在枚举里、服务层各用一次、能力审计里登记过。
8. **成本覆盖表**：只搬运不重算（不碰 `cost_basis`）、只读、窗口复用上游、
   出参模型与 builder 的键**一一对应**、口径说明不含 markdown 星号。
9. **单测**：上面每一条口径都有人钉（`backend/tests/test_purchase_orders.py`）。

⚠️ 注入式反向验证（改坏 → 本脚本必须红）：`_tools/qa/_reverse_verify_purchase_orders.py`（39 种破坏方式全被抓）。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界消除不了**。「一次进货 = 库存 + 成本价 + 供应商应付」
是**一次保存的三个副作用**，三处都在既有表上、都有既有的唯一实现可复用；坏起来每一件都
编译通过、接口也照样 200、单张表看起来还对：

* 「改单写一条冲销行」与「改写原来那条流水」在类型上完全一样（都是往 `inventory_movements` 插/改一行），
  差的是加权均价分母的取法（`change > 0 AND unit_cost IS NOT NULL`）—— 冲销行天然进不去，旧价会永远留下；
* 「撤行把成本价记成 0」是合法 SQL、合法 HTTP —— 0 被报表读成「成本是 0」= 毛利虚高；
* 「采购模块自己 insert 一张应付」同样是 200 —— 与 `services/supplier_service.py` 的相减口径分叉，下一次改单还把它覆盖回去；
* 「成本覆盖表自己再算一遍收入」= 同一个数两处口径（本项目报表历史上最贵的一类缺陷）。

类型系统、权限点与 DB 约束只能保证「不炸」，保证不了「四个数对得上」—— 账对不对只有把
合计 / 库存 / 成本价 / 应付拿去复算才知道。所以守门人是这一条判据 + 注入式反验：39 种破坏方式
（含上面四种写法）每种都要让本脚本报红，且被碰过的文件逐字节还原。

用法：python _tools/qa/_check_purchase_orders.py
"""
from __future__ import annotations

import ast
import io
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
#: ⛔ 复用兄弟判据里「取一个模块级 Python 函数体」的实现（按顶格定义切），不抄第二份。
from _check_report_window import py_def_body  # noqa: E402
from _check_single_source import code_only  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "backend/app/models/purchase.py"
SERVICE = ROOT / "backend/app/services/purchase_service.py"
API = ROOT / "backend/app/api/v1/purchase_orders.py"
REPORTS_SCHEMA = ROOT / "backend/app/schemas/reports.py"
COVERAGE = ROOT / "backend/app/services/reports/cost_coverage_query.py"
REPORTS = ROOT / "backend/app/api/v1/reports.py"
ROUTER = ROOT / "backend/app/api/v1/router.py"
ENUMS = ROOT / "backend/app/models/enums.py"
CAPA = ROOT / "backend/app/core/capability_audit_coverage.py"
SUPPLIERS_API = ROOT / "backend/app/api/v1/suppliers.py"
TEST = ROOT / "backend/tests/test_purchase_orders.py"

fails: list[str] = []
passes = 0


def ok(label: str, cond: bool, detail: str = "") -> None:
    global passes
    if cond:
        passes += 1
        print(f"  [OK]   {label}")
    else:
        fails.append(label + (f" —— {detail}" if detail else ""))
        print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的判据要跟着改，不许静默跳过）")
    return io.open(p, encoding="utf-8", errors="replace").read()


def ast_names(src: str, cls: str) -> set[str]:
    """一个 class 里**显式声明**的字段名（注解赋值）—— 模型与 pydantic schema 通用。

    ⚠️ 用 AST 而不是正则：这里判的是「有没有这一列」，正则会把注释与文档里提到的名字算进来。
    """
    for node in ast.parse(src).body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            return {t.target.id for t in node.body
                    if isinstance(t, ast.AnnAssign) and isinstance(t.target, ast.Name)}
    return set()


def ast_str_tuple(src: str, name: str) -> list[str]:
    """模块级的一个字符串元组常量（`_NOTES` 那种）。"""
    value = None
    for node in ast.parse(src).body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == name:
            value = node.value
        elif isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            value = node.value
        else:
            continue
        if isinstance(value, ast.Tuple):
            return [e.value for e in value.elts if isinstance(e, ast.Constant)]
    return []


def main() -> int:
    model = read(MODEL)
    service = read(SERVICE)
    api = read(API)
    coverage = read(COVERAGE)
    coverage_code = code_only(coverage)  #: 剥掉注释与文档字符串后的代码（「不碰」判的是代码，不是说明）
    reports = read(REPORTS)
    router = read(ROUTER)
    enums = read(ENUMS)
    capa = read(CAPA)
    suppliers_api = read(SUPPLIERS_API)
    test = read(TEST)

    # ---- ① 形状：三条不变量 ----
    print("① 形状：单头不存合计、明细不存金额、一行绑定一条流水")
    _order_cols = ast_names(model, "PurchaseOrder")
    _item_cols = ast_names(model, "PurchaseOrderItem")
    ok("两张表都在模型里，字段齐全（单头：供应商/日期/备注/那张应付；明细：商品/数量/单价/流水/撤行）",
       {"supplier_id", "doc_date", "remark", "payable_id", "operator_id"} <= _order_cols
       and {"order_id", "product_id", "quantity", "unit_cost", "movement_id", "is_void"} <= _item_cols,
       f"单头 {sorted(_order_cols)}；明细 {sorted(_item_cols)}")
    ok("⛔ 单头没有合计列（合计 = Σ 明细，现算）",
       not ({"total", "amount", "total_amount", "sum"} & _order_cols),
       "同一个数落两处，早晚会有一处忘了改 —— 界面上「一行行加起来 ≠ 合计」正是这么来的")
    ok("⛔ 明细没有金额列（= 数量 × 单价，现算）",
       not ({"amount", "line_amount", "total"} & _item_cols))
    ok("明细绑定它写下的那条流水（`movement_id` → `inventory_movements.id`）",
       re.search(r"movement_id[\s\S]{0,240}?ForeignKey\(\"inventory_movements\.id\"\)", model) is not None,
       "没有这条绑定，改单时就找不到该改哪一条流水")
    ok("撤行**不删这一行**（`is_void` 是标记，撤掉的量与原价要留在单上对证）",
       "is_void" in _item_cols and "撤行" in model)

    # ---- ② 建单：三件事一个事务 ----
    print(chr(10) + "② 建单：库存 + 成本价 + 应付，一个事务里一次写完")
    create = py_def_body(service, "create_order")
    _i_items = create.find("_add_line(")
    _i_pay = create.find("_sync_payable(")
    _i_log = create.find("write_log(")
    _i_commit = create.find("db.commit()")
    ok("三件事 + 留痕 + 提交都在建单里，且顺序是 明细 → 应付 → 留痕 → 提交",
       -1 < _i_items < _i_pay < _i_log < _i_commit,
       f"位置 _add_line={_i_items} _sync_payable={_i_pay} write_log={_i_log} commit={_i_commit}")
    add = py_def_body(service, "_add_line")
    ok("加一行 = 写一条入库流水 + 加库存 + 记成本价（三件事同一处）",
       "InventoryMovement(" in add and "_apply_stock(" in add and "record_cost(" in add)
    ok("那条流水的来源写着 `SOURCE_PURCHASE`（流水列表里一眼可辨）",
       re.search(r"source=SOURCE_PURCHASE", add) is not None)
    ok("入库流水记在 `COMMITTED` 上（撤行才转 `VOID`）", "status=STATUS_COMMITTED" in add)
    _n_pay = service.count("SupplierPayable(")
    ok("应付单**只有一处新建**（`SupplierPayable(` 全模块 1 次，且在 `_sync_payable` 里）",
       _n_pay == 1 and "SupplierPayable(" in py_def_body(service, "_sync_payable"),
       f"实际 {_n_pay} 次")
    ok("成本价只有 `record_cost` 一个写入口（采购模块里没有直接给 `cost_price` 赋值）",
       ".cost_price =" not in service)
    _n_amt = service.count("Decimal(str(item.unit_cost or 0))")
    ok("金额只有 `line_amount` 一处运算（界面上一行行加起来 == 合计）",
       "def line_amount(" in service and "def total_of(" in service and _n_amt == 1,
       f"实际 {_n_amt} 处")

    # ---- ③ 改单是改写那条流水 ----
    print(chr(10) + "③ 改单是**改写**那条流水，撤行是 is_void（⛔ 不是再记一笔冲销）")
    _n_move = service.count("InventoryMovement(")
    ok("全模块只在一处新建入库流水（`_add_line`）",
       _n_move == 1 and "InventoryMovement(" in add,
       f"实际 {_n_move} 处 —— 改单若也新建流水，旧价会永远留在加权均价里")
    setline = py_def_body(service, "_set_line")
    ok("改数量/单价改的是**同一条**流水（`mv.change = quantity` / `mv.unit_cost = unit_cost`）",
       "mv.change = quantity" in setline and "mv.unit_cost = unit_cost" in setline)
    ok("只有真的改了价才动成本价（`if old_cost is None or q2(old_cost) != q2(unit_cost)`）",
       re.search(r"if old_cost is None or q2\(old_cost\) != q2\(unit_cost\):", setline) is not None)
    detach = py_def_body(service, "_detach_line")
    ok("脱离（撤行 / 进回收站）把流水摆成「没发生过」：change=0 / unit_cost=NULL / status=VOID",
       "mv.change = 0" in detach and "mv.unit_cost = None" in detach and "mv.status = STATUS_VOID" in detach)
    _n_void = service.count("mv.status = STATUS_VOID")
    ok("「哪条流水不算数」只有这一种写法", _n_void == 1, f"实际 {_n_void} 处")
    voidline = py_def_body(service, "_void_line")
    ok("撤行**不删这一行**：`item.is_void = True`，且函数体里没有 db.delete",
       "item.is_void = True" in voidline and "db.delete" not in voidline)
    attach = py_def_body(service, "_attach_line")
    ok("恢复按明细行上的数量与原价原样写回",
       "mv.change = item.quantity" in attach and "mv.unit_cost = item.unit_cost" in attach
       and "mv.status = STATUS_COMMITTED" in attach)
    apply_items = py_def_body(service, "_apply_items")
    ok("改单是**整单替换**：请求里没给的行最后走 `_void_line`",
       re.search(r"for item in existing[\s\S]{0,300}?_void_line\(", apply_items) is not None)
    ok("`items=None` 只改单头（⛔ 与「传一个空数组」不是一回事）",
       re.search(r"if items is not None:[\s\S]{0,160}?_apply_items\(", py_def_body(service, "update_order")) is not None)

    # ---- ④ 撤行不许把成本价抹成 0 ----
    print(chr(10) + "④ 撤行不许把成本价抹成 0（2026-10-04 实测抓到的静默缺陷）")
    rep = py_def_body(service, "_reprice_product")
    _i_flush = rep.find("db.flush()")
    _i_sel = rep.find("select(InventoryMovement)")
    ok("先 `db.flush()` 再查「最近一次还活着的带价入库」", -1 < _i_flush < _i_sel,
       f"位置 flush={_i_flush} select={_i_sel} —— 不 flush 时 WHERE 按库里的旧值判、拿回来的却是身份映射里那个 unit_cost=None 的实例")
    ok("查询排除已脱离的流水（`InventoryMovement.status != STATUS_VOID`）",
       re.search(r"InventoryMovement\.status != STATUS_VOID", rep) is not None)
    ok("没有带价入库时如实留着旧价（守卫里认 `unit_cost is None`）",
       re.search(r"last is None or last\.unit_cost is None", rep) is not None,
       "⛔ 绝不把 None 递给 record_cost —— 它把 None 当 0，0 会被报表读成「成本是 0」＝毛利虚高")
    ok("重算出来的价确实记回去了（判据不是「函数被清空」才通过）",
       "record_cost(" in rep and "last.unit_cost," in rep)
    _n_rep = service.count("_reprice_product(db, ")
    ok("重算只发生在脱离那条路上", _n_rep == 1, f"实际 {_n_rep} 处调用")

    # ---- ⑤ 失败不留半成品 ----
    print(chr(10) + "⑤ 失败不留半成品：写端点中途报错要把这一事务改过的行回滚掉")
    ok("有 `_write(` 这道守卫，except 分支里先回滚再抛（⛔ 不是只 raise）",
       re.search(r"def _write\([\s\S]{0,1600}?except HTTPException:[\s\S]{0,300}?db\.rollback\(\)[\s\S]{0,300}?raise", api) is not None,
       "生产里 db.close() 会回滚，但测试与 AI 复用同一个会话时不会 —— 半成品会被下一次请求的 commit 带进库")
    _wrapped = sorted(re.findall(r"_write\(\s*psvc\.(\w+),", api))
    ok("四个写端点全走守卫（create / update / soft_delete / restore）",
       _wrapped == ["create_order", "restore_order", "soft_delete_order", "update_order"], f"实际 {_wrapped}")
    _naked = sorted(re.findall(r"psvc\.(create_order|update_order|soft_delete_order|restore_order)\(", api))
    ok("⛔ 没有绕开守卫的裸调用", _naked == [], f"实际 {_naked}")

    # ---- ⑥ 端点与权限 ----
    print(chr(10) + "⑥ 端点与权限：读端 Reader、写端 Writer")
    _n_ep = api.count("@router.")
    ok("六个端点齐全（列表 / 详情 / 建 / 改 / 撤 / 恢复）", _n_ep >= 6, f"实际 {_n_ep} 个装饰器")
    ok("路由前缀就是 `/purchase-orders`", "prefix=" in api and "/purchase-orders" in api)
    _n_reader = api.count("_: User = Reader")
    _n_writer = api.count("operator: User = Writer")
    ok("两个读端点是 Reader、四个写端点是 Writer", _n_reader >= 2 and _n_writer >= 4,
       f"实际 Reader={_n_reader} Writer={_n_writer}")
    ok("router.py 里挂上了这个路由",
       re.search(r"include_router\(purchase_orders\.router\)", router) is not None)
    _n_guard = suppliers_api.count("psvc.guard_supplier_payable(db, p)")
    ok("供应商页改/删那张应付之前都要先过守卫（⛔ 不然改单会把它悄悄覆盖回去）",
       _n_guard >= 2, f"实际 {_n_guard} 处")

    # ---- ⑦ 留痕 ----
    print(chr(10) + "⑦ 四动作码留痕（谁在什么时候建/改/撤/恢复了哪张单）")
    for code in ("PURCHASE_ORDER_CREATE", "PURCHASE_ORDER_UPDATE", "PURCHASE_ORDER_DELETE", "PURCHASE_ORDER_RESTORE"):
        _n = service.count(code)
        ok(f"`{code}` 在枚举里、且服务层正好用了一次", code in enums and _n == 1, f"服务层实际 {_n} 次")
    _bq = chr(34)
    _snap_call = "change_payload={" + _bq + "before" + _bq + ": before, " + _bq + "after" + _bq + ": _snapshot(order)}"
    ok("改单留痕带 before / after 两份快照", _snap_call in service)
    ok("能力审计里登记过这四个动作码（→ Permission.PRODUCT_MANAGE）",
       "PURCHASE_ORDER_CREATE" in capa and "PURCHASE_ORDER_DELETE" in capa and "PRODUCT_MANAGE" in capa)

    # ---- ⑧ 成本覆盖表 ----
    print(chr(10) + "⑧ 成本覆盖表：只搬运、不重算（收入那一侧与营业纵览同一句）")
    cov = py_def_body(coverage, "build_cost_coverage")
    ok("只读（没有 add / commit / delete / flush）",
       re.search(r"db\.(add|commit|delete|flush)\(", coverage) is None)
    ok("不碰 `cost_basis`（不自己判「这个商品有没有成本价」、不重算任何金额）",
       "cost_basis" not in coverage_code and "_weighted_avg" not in coverage_code,
       "把收入那一侧再算一遍就又多出一处口径 —— 本项目报表历史上最贵的一类缺陷")
    ok("收入那一侧整段取自营业纵览（同一个 span、同一段窗口）",
       re.search(r"build_turnover\(db, mode, anchor, span=span\)", cov) is not None
       and re.search(r"start, end = turnover\[._window.\]", cov) is not None)
    ok("「算不出成本的收入」只有这一句（= 营业额 − 参与毛利的收入，与利润表同一句）",
       re.search(r"revenue_uncovered.*revenue_total - revenue_covered", cov) is not None)
    ok("「没记过进货价」只看流水（change > 0 且带 unit_cost），不看商品台账那一列",
       re.search(r"InventoryMovement\.change > 0,[\s\S]{0,120}?InventoryMovement\.unit_cost\.isnot\(None\)", coverage) is not None)
    _out_keys = set(re.findall(r"\"(\w+)\":", cov)) - {"_window"}
    _out_fields = ast_names(read(REPORTS_SCHEMA), "CostCoverageReportOut")
    ok("出参模型与 builder 返回的键**一一对应**（少一个 = 前端永远显示默认值，多一个 = 白算）",
       bool(_out_keys) and _out_keys == _out_fields,
       f"builder {sorted(_out_keys)}；schema {sorted(_out_fields)}")
    _prod_keys = set(re.findall(r"\"(\w+)\":", py_def_body(coverage, "_never_priced")))
    _prod_fields = ast_names(read(REPORTS_SCHEMA), "CostCoverageProduct")
    ok("商品清单那一行的键也一一对应", bool(_prod_keys) and _prod_keys == _prod_fields,
       f"builder {sorted(_prod_keys)}；schema {sorted(_prod_fields)}")
    notes = ast_str_tuple(coverage, "_NOTES")
    ok("口径说明至少 4 条，且⛔ 不含 markdown 星号（这几句是用户直接看到的）",
       len(notes) >= 4 and all("*" not in n for n in notes), f"实际 {len(notes)} 条")
    ok("说明里写清了「两份清单不是一回事」（⛔ 页面上不许把 A 说成 B 的原因）",
       any(("不等价" in n or "不等于" in n) for n in notes))
    ok("补录入口写了采购单与入库两处（用户照着这句话就知道去哪补）",
       any("采购单" in n and "入库" in n for n in notes))
    _ep = "@router.get(" + chr(34) + "/cost-coverage" + chr(34)
    # ⛔ 下面这三条都要落在**这个端点自己**身上：`data.pop("_window", None)` 在 reports.py 里出现 5 次，
    # 判整个文件的「有」等于没判（2026-10-04 反向验证实测：把 cost-coverage 端点里那句删掉，判据照样绿）。
    _ep_body = py_def_body(reports, "cost_coverage_report")
    _pop = "data.pop(" + chr(34) + "_window" + chr(34) + ", None)"
    ok("端点存在、与营业纵览同一个 `_span(`、且丢掉内部键 `_window`",
       _ep in reports
       and re.search(r"span = _span\(mode, anchor, date_from, date_to\)[\s\S]{0,160}?build_cost_coverage\(db, mode, anchor, span=span\)", _ep_body) is not None
       and _pop in _ep_body)

    # ---- ⑨ 单测 ----
    print(chr(10) + "⑨ 单测：上面每条口径各有人钉（backend/tests/test_purchase_orders.py）")
    for needle, label in (
        ("_assert_identity", "Σ(change) == products.stock 恒等式"),
        ("test_改数量与单价_改写那条流水而不是再记一笔", "改单是改写那条流水"),
        ("test_请求里没给的行算撤行_库存退回去_流水留痕但不算数", "撤行语义（行留下、流水脱离）"),
        ("_cost_price(", "撤行之后成本价还在（不抹成 0）"),
        ("test_撤销整张单_库存退回去_应付进回收站_能原样恢复", "软删可恢复"),
        ("test_每一步都留痕", "四动作码留痕"),
        ("test_货主和司机都进不来", "货主/司机写不了采购单"),
        ("test_成本覆盖报表_没记过进货价的商品列在里面_记了就出列", "成本覆盖表"),
        ("test_已经付过钱的单_删不掉_也改不到小于已付", "付过钱的单不让改小/删掉"),
    ):
        ok(f"单测里有「{label}」那一条", needle in test)

    print(chr(10) + "=" * 64)
    if fails:
        print(f"❌ {len(fails)} 项不通过：")
        for item in fails:
            print("   - " + item)
        return 1
    print(f"✅ 全部 {passes} 项通过：一次进货 = 库存 + 成本价 + 供应商应付，三件事一个事务；改单改写那条流水，撤行不抹成本价。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())