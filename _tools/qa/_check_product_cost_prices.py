"""红线：商品的**附加成本价口径**（FEAT-0025，2026-10-11）—— 默认口径一个字不许动。

R4-BOUNDARY-JUSTIFICATION:
  允许变的是「附加口径」这一族（表 product_cost_prices / AI 动作 products.cost_price.set|delete|restore /
  商品表单里的那个弹层），它们全是 **Extension**；
  不许变的是**默认口径**：订单行的 cost_price_snapshot、账单、毛利只按 products.cost_price 算，
  那是 Core 的计费事实。所以第 ② 条判据就是「ProductCostPrice 不许出现在算钱的那几个文件里」——
  它坏起来**完全静默**：谁把附加口径读进毛利，报表照常出数、只是数字错了，没有任何第二处能对上。

## 由来（用户 2026-10-11 原话，逐字）
> 「我们是可以设置多个成本价的，AI 也都可以调。只不过我们一般情况下是默认按一个成本价，也就是
>   真实成本价，按那个来计算的，一般订单都是按那个来计算的。……有时候计算的时候还有第二个成本价
>   —— 这个成本价可能是加了其他东西、或者比如说有补贴啊等等之后的成本价。所以一定要有多个成本价啊。
>   我在跟他聊天的过程当中，他就没办法设置第二个成本价。」

改之前 AI 只会回「系统里每个商品只有一个成本价」；改之后一个商品可以命名多条口径，
**但订单与毛利只认 products.cost_price**，其余一律标注「参考口径」。

## 为什么必须是静态判据（坏法在界面上都看不出来）
| 坏法 | 界面上看起来 |
|---|---|
| 下单定格改读附加口径 | 新单照下、金额照算 —— 只是**已出的账全部改数** |
| 毛利聚合改读附加口径 | 报表照出数字，只是口径已经不是「真实成本价」 |
| 默认那条不再取自 products.cost_price | 界面照写「订单与毛利按它算」，**那句话却指向了另一个数** |
| 附加口径表飘进 services/**、commands/** | 毫无症状；等发现时已经两套口径各算了一套 |

所以只能盯写法本身。判据先剥注释与文档串（Python 剥 # 与三引号；Kotlin 剥 // 与 /* */，
但**字符串一个字不动** —— 卡片与界面上那句「钱的口径」正是要盯的东西）。

## 判据
1. 后端承载：表 / 迁移 034 / 五条端点 / 路由顺序 / 合成的那条默认口径都在；
2. ⛔ 算钱的文件里一个字都不许出现 ProductCostPrice（白名单之外一律红）；
3. 钱的口径锚点：下单定格、后加行定格、唯一写入口、毛利聚合仍走 cost_basis；
4. AI：三条动作声明 + 入总表 + 两个 handler 注册 + 数据源 + 资源表成对 + 撤回表 + 护栏白名单；
5. prepare 里不写库（写调用只许出现在 commit 之后）；
6. 卡片：哪个商品 / 哪条口径 / **改前 → 改后**；
7. 界面：弹层在位、默认那条排最前并标注、其余标「参考口径」、**手边有恢复入口**；
8. 反空转：断言条数下限 + 单测数量与关键用例。

用法：python _tools/qa/_check_product_cost_prices.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_single_source import code_only  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend/app"
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
AND_TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders"
TESTS = ROOT / "backend/tests/test_product_cost_prices.py"

#: 只有这些文件**允许**提到附加口径（其余一律红）。每条都写清为什么它可以在。
ALLOW = {
    "models/product.py": "表定义本身",
    "models/__init__.py": "模型导出（Base.metadata 里得有它）",
    "migrations/034_product_cost_prices.py": "老库建表（迁移）",
    "api/v1/products.py": "5 个端点就在这个文件里",
    "schemas/product.py": "出参/入参 schema",
}

FAILS: list[str] = []
CHECKS = 0
_CACHE: dict[str, str] = {}


def ok(cond: bool, msg: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        FAILS.append(msg)


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def kt_code(src: str) -> str:
    """剥 Kotlin 的 // 与 /* */（字符串内不动，且保留行号）。"""
    out = list(src)
    n = len(src)
    i = 0
    in_str = False
    while i < n:
        ch = src[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            i += 1
            continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
            continue
        i += 1
    return "".join(out)


def src_of(p: Path) -> str:
    key = str(p)
    if key not in _CACHE:
        if not p.exists():
            _CACHE[key] = ""
            FAILS.append("要盯的文件不在了：" + str(p.relative_to(ROOT)))
        else:
            raw = read(p)
            _CACHE[key] = code_only(raw) if p.suffix == ".py" else kt_code(raw)
    return _CACHE[key]


def need(label: str, p: Path, needle: str) -> None:
    ok(needle in src_of(p), label + " —— " + p.name + " 里没找到：" + needle)


def at_least(label: str, p: Path, needle: str, floor: int) -> None:
    got = src_of(p).count(needle)
    ok(got >= floor, label + " —— " + p.name + " 里「" + needle + "」只出现 " + str(got)
       + " 次（至少 " + str(floor) + " 次）")


def rel(p: Path) -> str:
    return str(p.relative_to(BACKEND)).replace("\\", "/")


PROD = BACKEND / "models/product.py"
MIG = BACKEND / "migrations/034_product_cost_prices.py"
API = BACKEND / "api/v1/products.py"
ENUM = BACKEND / "models/enums.py"
AW = AND / "ai/AiWrite.kt"
CP = AND / "ai/AiWriteCostPrices.kt"
DS = AND / "ai/AiWriteDataSource.kt"
SVC = AND / "ai/AiWriteService.kt"
RES = AND / "ai/AiResources.kt"
REV = AND / "ai/AiRevert.kt"
SHEET = AND / "ui/dispatcher/ProductCostPriceSheet.kt"
VMF = AND / "ui/dispatcher/ProductFormViewModel.kt"
SCR = AND / "ui/dispatcher/ProductFormScreen.kt"
RC = AND / "ui/dispatcher/ReportCenter.kt"
APIS = AND / "data/remote/api/Apis.kt"
DTOS = AND / "data/remote/dto/Dtos.kt"
REPO = AND / "data/repo/AppRepository.kt"
GUARD = ROOT / "_tools/ai/_check_ai_guardrails.py"


def main() -> int:
    # ---- ① 后端承载与端点 ----
    print("① 后端：独立的表 / 迁移 034 / 五条端点 / 路由顺序 / 合成的那条默认口径")
    need("附加口径是独立的表（一个商品可多条）", PROD, "class ProductCostPrice(Base, TimestampMixin, SoftDeleteMixin):")
    need("表名", PROD, '__tablename__ = "product_cost_prices"')
    need("同名不许重复（软删的行仍占着这个名字）", PROD,
         'UniqueConstraint("product_id", "name", name="uq_product_cost_price_product_name")')
    need("口径名可命名", PROD, "name: Mapped[str] = mapped_column(String(64))")
    need("显示顺序", PROD, "sort_order: Mapped[int] = mapped_column(Integer, default=0)")
    at_least("三处 cost_price 列都还在（商品 / 成本价历史 / 附加口径）", PROD,
             "cost_price: Mapped[Decimal] = mapped_column(Numeric(14, 4)", 3)
    need("迁移：版本号", MIG, "VERSION = 34")
    need("迁移：表名", MIG, 'TABLE = "product_cost_prices"')
    need("迁移：能重跑（已经在了就什么都不做）", MIG, "if TABLE in set(inspect(engine).get_table_names()):")
    need("迁移：按模型建表", MIG, "ProductCostPrice.__table__.create(bind=engine, checkfirst=True)")

    need("默认口径的名字（与 AI、App 是同一个字面量）", API, 'DEFAULT_COST_PRICE_NAME = "真实成本价"')
    need("默认那条的口径说明", API, '"订单与毛利按它算（真实成本价）"')
    need("参考口径的说明", API, '"参考口径：不参与订单与毛利的计算"')
    need("默认那条是**合成**出来的，金额取自商品那一格", API, "cost_price=p.cost_price,")
    need("合成那条要标成默认（界面/AI 靠它认人）", API, "is_default=True")
    need("合成那条排最前", API, "sort_order=-1")
    need("列表端点", API, '@router.get("/cost-prices"')
    need("列表：回收站视图", API, "deleted_only: bool = Query(False")
    need("列表：参考口径要真的列出来（不是只给默认那条）", API,
         "items = [_cost_price_out(r) for r in db.scalars(q)]")
    need("列表：软删由 is_deleted 过滤", API, "ProductCostPrice.is_deleted.is_(deleted_only)")
    need("列表：默认那条排最前", API, "items.insert(0, _default_cost_price_out(p))")
    need("新增/设置端点（同名 upsert）", API, '@router.post(')
    need("新增端点的路径（多行写法）", API, '"/{product_id}/cost-prices",')
    need("查已有行时不过滤软删（软删的名字仍占唯一约束）", API, "_cost_row_by_name(db, product_id, body.name)")
    need("默认那个名字不许进这张表", API, "if body.name == DEFAULT_COST_PRICE_NAME:")
    need("同名命中且原来在回收站 → 复活它（不是插第二条）", API, "cost_row.is_deleted = False")
    need("改名/改价端点", API, '@router.patch("/cost-prices/{row_id}"')
    need("部分更新语义（只动请求里出现的字段）", API, "body.model_dump(exclude_unset=True)")
    need("改名撞了别的活行 → 拒绝（同名不许重复的第二道）", API,
         "if clash is not None and clash.id != cost_row.id:")
    need("删除端点", API, '@router.delete("/cost-prices/{row_id}"')
    need("删除是**软删**（用户 2026-09-20 的硬规矩：删了必须能拿回来）", API, "cost_row.is_deleted = True")
    need("软删要记时间", API, "cost_row.deleted_at = utc_now_naive()")
    need("恢复端点", API, '@router.post("/cost-prices/{row_id}/restore"')
    need("恢复要连回收站一起找", API, "_cost_row_or_404(db, row_id, include_deleted=True)")
    body = src_of(API)
    i_cost = body.find('@router.get("/cost-prices"')
    i_pid = body.find('@router.get("/{product_id}"')
    ok(0 <= i_cost < i_pid,
       "路由顺序不对：/cost-prices 必须声明在 /{product_id} 之前，否则会被当成商品 id 吞掉")
    print("   表 + 迁移 4 项 + 端点/语义 22 项；路由顺序（/cost-prices 在 /{product_id} 之前）："
          + ("是" if 0 <= i_cost < i_pid else "否"))

    for code in ("PRODUCT_COST_PRICE_UPSERT", "PRODUCT_COST_PRICE_UPDATE",
                 "PRODUCT_COST_PRICE_DELETE", "PRODUCT_COST_PRICE_RESTORE"):
        need("审计码要用在写入处（" + code + "）", API, "OperationAction." + code)
        need("审计码要在枚举里定义", ENUM, code + ' = "' + code + '"')
    for code, cn in (("PRODUCT_COST_PRICE_UPSERT", "设置成本价口径"),
                     ("PRODUCT_COST_PRICE_UPDATE", "修改成本价口径"),
                     ("PRODUCT_COST_PRICE_DELETE", "删除成本价口径"),
                     ("PRODUCT_COST_PRICE_RESTORE", "恢复成本价口径")):
        need("审计中心要有中文名「" + cn + "」", RC, '"' + code + '" -> "' + cn + '"')
    print("   四个审计码：写入处 + 枚举 + 审计中心中文名")

    # ---- ② ⛔ 算钱的文件里一个字都不许出现附加口径 ----
    hits: list[str] = []
    scanned = 0
    suspect = re.compile(r"ProductCostPrice|product_cost_prices")
    for p in sorted(BACKEND.rglob("*.py")):
        scanned += 1
        r = rel(p)
        if r in ALLOW:
            continue
        if suspect.search(src_of(p)):
            hits.append(r)
    ok(scanned >= 100, "只扫到 " + str(scanned) + " 个后端文件 —— 扫描路径不对，这一节是空转的")
    ok(not hits, "附加口径漏进了算钱的文件里（订单/账单/毛利的口径就是在这里被悄悄改掉的）：" + "、".join(hits))
    print("② ⛔ 扫了 " + str(scanned) + " 个后端文件；附加口径的合法落点 " + str(len(ALLOW))
          + " 处；越界 " + str(len(hits)) + " 处")

    # ---- ③ 钱的口径锚点 ----
    print("③ 钱的口径：订单定格的仍是 products.cost_price，毛利聚合仍走 cost_basis")
    need("下单时定格的是商品的真实成本价", BACKEND / "services/order_flow.py",
         'cost_snap = prod.cost_price or Decimal("0")')
    need("定格结果仍写进订单行的 cost_price_snapshot", BACKEND / "services/order_flow.py",
         "cost_price_snapshot=cost_snap,")
    need("派单员后加的行也定格真实成本价", BACKEND / "api/v1/order_products.py",
         'cost_snapshot = p.cost_price or Decimal("0")')
    need("后加行也写进 cost_price_snapshot", BACKEND / "api/v1/order_products.py",
         "cost_price_snapshot=cost_snapshot,")
    need("真实成本价仍只有一处写入口（会记进成本价历史）", BACKEND / "services/cost_history.py",
         "product.cost_price = new_cost")
    ok((BACKEND / "services/cost_basis.py").exists(), "services/cost_basis.py 不见了（成本口径那一处实现没了）")
    # ⚠️ 毛利聚合**不在** api/v1/reports.py：2026-09 之后搬到了 services/reports/，而且调用形式是
    #    构造 + 逐行取成本两步（CostBasis(db, start, end) / basis.of(pid, snap)）。
    #    断言 "CostBasis.of(" 是错的（那个字符串在代码里根本不存在）→ 判据恒红，第一版就是这么红的。
    rep_files = sorted((BACKEND / "services/reports").glob("*.py")) + [BACKEND / "api/v1/reports.py"]
    ok(len(rep_files) >= 3, "只找到 " + str(len(rep_files)) + " 个报表实现文件（路径又搬了？判据会空转）")
    for fname in ("turnover_query.py", "product_query.py"):
        f = BACKEND / "services/reports" / fname
        need(fname + " 仍从 cost_basis 取成本口径", f, "from app.services.cost_basis import")
        need(fname + " 仍逐行取成本（basis.of）", f, "basis.of(")
    need("毛利聚合用的仍是下单快照（不是拿附加口径现算）", BACKEND / "services/reports/product_query.py",
         "basis.of(lp.product_id, lp.cost_price_snapshot)")
    print("   定格/写入口/毛利聚合锚点 8 条")

    # ---- ④ AI ----
    print("④ AI：三条动作 + 两个 handler + 数据源 + 资源表 + 撤回（AI 必须能设第二条）")
    need("动作 id（设置）", AW, 'const val PRODUCTS_COST_PRICE_SET = "products.cost_price.set"')
    need("动作 id（删除）", AW, 'const val PRODUCTS_COST_PRICE_DELETE = "products.cost_price.delete"')
    need("动作 id（恢复，撤回专用）", AW, 'const val PRODUCTS_COST_PRICE_RESTORE = "products.cost_price.restore"')
    need("三条动作登记进 ALL（模型才看得到）", AW, "AiWriteCostPrices.ACTIONS")
    need("动作对象在", CP, "internal object AiWriteCostPrices {")
    need("设置动作的标题", CP, 'title = "设置成本价口径"')
    need("删除动作的标题", CP, 'title = "删掉一条成本价口径"')
    need("设置 handler", CP, "class SetCostPriceHandler(")
    need("删除 handler", CP, "class DeleteCostPriceHandler(")
    need("设置 handler 认自己的动作", CP, "override val actionId = AiWrites.PRODUCTS_COST_PRICE_SET")
    need("删除 handler 认自己的动作", CP, "override val actionId = AiWrites.PRODUCTS_COST_PRICE_DELETE")
    need("恢复走通用成对动作（undoOnly，模型看不到它）", CP, "restoreAction(")
    need("参数里带 cost_price（自动落进成本那道开关）", CP, 'name = "cost_price"')
    need("默认口径的名字与后端是同一个字面量", CP, 'DEFAULT_COST_PRICE_NAME = "真实成本价"')
    need("prepare 里读活的口径", CP, "ds.productCostPrices(product.id)")
    need("也读回收站（提前说清会把它放回来）", CP, "ds.deletedProductCostPrices(product.id)")
    at_least("默认那条不许被当成可改可删的参考口径（两个 handler 都要把它滤掉）", CP,
             ".filter { !it.isDefault }", 2)
    for label, sig in (("AI 能读到这个商品的附加口径", "productCostPrices"),
                       ("也能读到回收站那一条", "deletedProductCostPrices"),
                       ("新建/设置", "setProductCostPrice"),
                       ("改名/改价", "updateProductCostPrice"),
                       ("软删", "deleteProductCostPrice"),
                       ("恢复", "restoreProductCostPrice")):
        need("数据源：" + label, DS, "override suspend fun " + sig + "(")
        need("接口里有 " + sig, SVC, "suspend fun " + sig + "(")
    need("设置 handler 已注册", SVC, "SetCostPriceHandler(ds, store),")
    need("删除 handler 已注册", SVC, "DeleteCostPriceHandler(ds, store),")
    need("资源：成本价口径", RES, 'key = "cost_price",')
    need("资源：主键键名", RES, 'idKey = "cost_price_id",')
    need("资源：删除是成对的（删 ↔ 放回来）", RES,
         'AiInverse(AiWrites.PRODUCTS_COST_PRICE_DELETE, mapOf("cost_price_id" to AiRevert.ID))')
    need("资源：恢复用 target_id", RES,
         'restore = AiInverse(AiWrites.PRODUCTS_COST_PRICE_RESTORE, mapOf("target_id" to AiRevert.ID))')
    need("资源登记进 TABLE（否则撤回链找不到它）", RES, "COST_PRICE,")
    need("撤回表：设置那条要说清这条没有撤回按钮", REV, "listOf(AiWrites.PRODUCTS_COST_PRICE_SET),")
    need("护栏：prepare 里读这两份是**读**（四个写方法一个都不在白名单里）", GUARD,
         '"productCostPrices", "deletedProductCostPrices",')

    act = src_of(CP).split("val ACTIONS", 1)[-1].split("\n    )", 1)[0]
    for call, cn in (("setAction(),", "设置（AI 必须能设第二条成本价）"),
                     ("deleteAction(),", "删除"),
                     ("restoreAction(", "恢复（撤回专用）")):
        ok(call in act,
           "动作总表里少了「" + cn + "」—— 清单缺一条，AI 当场就做不到那件事")

    cost_c = src_of(CP)
    n_id = cost_c.count("override val actionId =")
    n_prep = cost_c.count("override suspend fun prepare(")
    n_commit = cost_c.count("override suspend fun commit(")
    ok(n_id == n_prep == n_commit >= 2,
       "handler 三件套对不上：actionId=" + str(n_id) + " / prepare=" + str(n_prep)
       + " / commit=" + str(n_commit) + "（应都是 2）")
    for handler in ("class SetCostPriceHandler(", "class DeleteCostPriceHandler("):
        seg = cost_c.split(handler, 1)[-1].split("override suspend fun commit", 1)[0]
        for call in ("ds.setProductCostPrice(", "ds.updateProductCostPrice(",
                     "ds.deleteProductCostPrice(", "ds.restoreProductCostPrice("):
            ok(call not in seg, handler + " 的 prepare 段里出现了写调用 " + call
               + "（卡片只是预览，落库只许在 commit）")
    ok("ds.setProductCostPrice(" in cost_c and "ds.deleteProductCostPrice(" in cost_c,
       "commit 里反而没有写调用了（判据自己在空转）")
    print("   handler 三件套：" + str(n_id) + "/" + str(n_prep) + "/" + str(n_commit)
          + "；两个 handler 的 prepare 里都没有写调用")

    # ---- ⑤ 卡片 ----
    print("⑤ 卡片：哪个商品 / 哪条口径 / 改前 → 改后（缺信息就问）")
    at_least("卡片要写是哪个商品", CP, "商品：", 2)
    at_least("卡片要写是哪条口径", CP, "口径：", 2)
    at_least("改前 → 改后（改名 / 改价 / 新建 / 删除四种情形）", CP, "→ 现在", 4)
    at_least("其中「金额：原来：… → 现在：…」三处（改价 / 新建 / 删除）", CP, "→ 现在：", 3)
    at_least("「金额：原来：」把改前的数摆在卡片上", CP, "金额：原来：", 3)
    at_least("改名要说清它现在叫什么", CP, "改名：原来叫「", 1)
    at_least("卡片要复述订单与毛利的口径不变", CP, "⛔ 订单与毛利的口径不变", 2)
    need("缺信息就问（不猜金额）", CP, "AiWriteArgException(")
    need("新建一条时必须问金额", CP, "新建一条成本价口径要给出金额")
    need("指了一条不存在的口径要说清", CP, "这个商品上没有叫")
    need("默认口径不许被改名/改价（引导去改商品那一格）", CP, "不在附加口径这一族里")

    # ---- ⑥ App ----
    print("⑥ 界面：能看/能加/能改名改价/能删 + 手边有恢复入口；默认那条标明是订单与毛利的口径")
    need("弹层在", SHEET, "internal fun ProductCostPriceSheet(")
    need("默认那条单独认出来", SHEET, "row.isDefault")
    need("只有参考口径能改/能删（默认那条跟着商品走）", SHEET, "if (!row.isDefault) {")
    need("删之前要确认（且文案写清能拿回来）", SHEET, "DangerConfirmDialog(")
    need("回收站要能手边恢复", SHEET, "{ onRestore(row.id) }")
    need("金额过价签规则（不许出现两位以上小数）", SHEET, "InputRules.priceInput(raw)")
    need("钱的口径那句话是裸 Text（关掉提示的人也得看见）", SHEET, "一个商品可以有好几个成本价")
    need("弹层里要有「参考口径」这个标注", SHEET, "参考口径")
    need("弹层里要写清默认那条是订单与毛利算账用的", SHEET, "订单与毛利")
    need("口径多了能滚", SHEET, "verticalScroll(")
    need("VM：读活口径", VMF, "container.repo.productCostPrices(id)")
    need("VM：读回收站", VMF, "container.repo.deletedProductCostPrices(id)")
    need("VM：新建/设置", VMF, "container.repo.setProductCostPrice(")
    need("VM：改名/改价", VMF, "container.repo.updateProductCostPrice(")
    need("VM：删除", VMF, "fun deleteCostPrice(")
    need("VM：恢复", VMF, "fun restoreCostPrice(")
    need("VM：默认口径的名字**不写死在 App**（拿后端给的那条）", VMF,
         "costPrices.firstOrNull { it.isDefault }?.name")
    need("VM：撞上默认名字要说清去哪儿改", VMF, "改它请在编辑页改「成本价」那一格")
    ok("saveCostPrice" in src_of(VMF), "商品表单 VM 少了保存成本价口径的入口")
    need("Screen：入口", SCR, 'label = "成本价口径",')
    need("Screen：点开弹层", SCR, "vm.openCostPrices()")
    need("Screen：接线", SCR, "ProductCostPriceSheet(")
    need("Screen：那一格是订单与毛利的成本价（钱的口径，裸 Text）", SCR, "订单与毛利算账用的那个")
    for fn in ("listProductCostPrices(", "upsertProductCostPrice(", "updateProductCostPrice(",
               "deleteProductCostPrice(", "restoreProductCostPrice("):
        need("接口：" + fn + ")", APIS, fn)
    need("接口：列表端点路径", APIS, '@GET("products/cost-prices")')
    need("Dtos：一条口径", DTOS, "data class ProductCostPriceDto(")
    need("Dtos：默认那条的标记", DTOS, '@SerialName("is_default")')
    for fn in ("productCostPrices(productId", "deletedProductCostPrices(productId",
               "setProductCostPrice(productId", "updateProductCostPrice(", "deleteProductCostPrice(",
               "restoreProductCostPrice("):
        need("仓库：" + fn, REPO, fn)

    # ---- ⑦ 反空转 ----
    print("⑦ 反空转：判据自己也别被掏空")
    for p in (PROD, MIG, API, ENUM, AW, CP, DS, SVC, RES, REV, SHEET, VMF, SCR, RC, APIS, DTOS, REPO, GUARD):
        ok(len(src_of(p)) >= 400, p.name + " 读出来只有 " + str(len(src_of(p))) + " 个字符 —— 文件不对或空了")
    ok(CHECKS >= 60, "断言只有 " + str(CHECKS) + " 条（下限 60）")
    n_kt = len(list(AND.rglob("*.kt")))
    ok(n_kt >= 200, "只扫到 " + str(n_kt) + " 个 .kt（源码树搬走了？判据会空转）")
    if not TESTS.exists():
        ok(False, "单测文件不在了：backend/tests/test_product_cost_prices.py")
    else:
        tbody = code_only(read(TESTS))
        n_tests = tbody.count("def test_")
        ok(n_tests >= 10, "单测只剩 " + str(n_tests) + " 个（要求 ≥10）")
        for name in ("ai_sets_a_second_cost_price_by_name",
                     "order_cost_snapshot_ignores_extra_cost_prices",
                     "extra_cost_prices_never_enter_the_cost_history",
                     "soft_delete_hides_the_row_and_restore_brings_it_back_verbatim",
                     "duplicate_name_never_creates_two_rows"):
            ok(name in tbody, "单测少了关键那一条：" + name + "（它是本判据的动态那一半）")
        print("   单测：" + str(n_tests) + " 个 test（5 条关键情形都在）；.kt 文件 " + str(n_kt) + " 个")

    if FAILS:
        print("")
        print("❌ 附加成本价口径被破坏（" + str(len(FAILS)) + " 项）：")
        for f in FAILS:
            print("   - " + f)
        return 1
    print("")
    print("✅ 附加成本价口径（FEAT-0025）：" + str(CHECKS) + " 条断言全过 —— "
          "默认口径（订单/账单/毛利/cost_price_snapshot）一个字没动，附加口径只在 Extension 里，"
          "三条 AI 动作 + 卡片「改前 → 改后」+ 界面弹层（含恢复入口）都在位。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
