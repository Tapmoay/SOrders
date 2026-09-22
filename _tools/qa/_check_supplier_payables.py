"""红线：**供应商 / 厂商档案 + 应付款**——后端 + AI + 界面（2026-09-22 用户要求）。

## 用户原话与拍板
> 「支出主要是**给某个供应商或者说是厂商支付尾款**……**购买一个装备或者说是设备**……
> 比如说类似**邮费**啊」；拍板口径：**跟客户一个量级的档案**（**可挂账、可查还欠多少、可分次付款**）。

## 这一块最容易悄悄坏掉的八件事（每条都有判据）
1. **`cash_flows` 的软删被漏在一处读法之外**：撤销一笔付款是"把那一行藏起来"，
   而 `cash_flows` 是**所有收付的总账**，读它的地方有 5 处（收支列表/汇总/分组、订单的钱、
   订单已收款判据、报表导出）。
   ⛔ 漏一处的后果是"欠款说没付、收支说付了"——**同一笔钱两个答案，而两边都不报错**。
   判据自己**算出**这 5 处（不让清单手写，本项目栽过 6 次），逐处断言它带了 `is_deleted`。
2. **欠款被算了第二遍**：`欠款 = Σ应付 − Σ付款` 只允许有一处实现（`services/supplier_service.py`）。
   端点上（或界面上）再减一遍，就一定会有一天两边不一样 —— 而界面上没有任何办法分辨信哪个。
3. **付款超付**：超了就是预付款，而预付款在这套账里没有位置（欠款变负数，没人读得对）。
4. **撤销付款写成了"反向再记一笔"**：那会在账上留下一对谁也不敢删的行，而且"这笔到底算不算"
   以后只能靠人去读备注。用户定的硬规矩是**删除一律软删 + 必须有恢复路径**。
5. **有付款的应付单能删掉**：那些钱就变成"付出去了、账上没有任何对应的应付款"
   （与"付了一张没有明细的结算单"同一类历史缺陷）。
6. **名字没被释放**：`suppliers.name` 唯一 + 删除是软删 —— 不把名字改成 `name_del{id}`，
   "删掉再建同名"会直接撞唯一约束（500）。
7. **AI 那一头漏登记**：十一条写动作、三组读能力都要进目录/工具清单/撤回资源表，
   读能力还要被某个 App 模块认领（否则用户从界面上根本看不到这个功能）。
8. **付款那张卡上没写"还差多少"**：钱付出去撤不回来，用户核对一笔付款时看的就是那两个数。

用法：python _tools/qa/_check_supplier_payables.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_pagination_wiring import strip_comments  # noqa: E402

BACKEND = ROOT / "backend/app"
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
API = BACKEND / "api/v1/suppliers.py"
MODEL = BACKEND / "models/supplier.py"
FLOW_MODEL = BACKEND / "models/cash_flow.py"
SERVICE = BACKEND / "services/supplier_service.py"
SCHEMA = BACKEND / "schemas/supplier.py"
TEST = ROOT / "backend/tests/test_supplier_payables.py"
BOOTSTRAP = BACKEND / "core/schema_bootstrap.py"
ENUMS = BACKEND / "models/enums.py"
USAGE = BACKEND / "services/usage_service.py"
LIST_SCREEN = ANDROID / "ui/dispatcher/SuppliersScreen.kt"
DETAIL_SCREEN = ANDROID / "ui/dispatcher/SupplierDetailScreen.kt"
ROUTES = ANDROID / "ui/nav/Routes.kt"
NAV = ANDROID / "ui/nav/NavGraph.kt"
MODULES = ANDROID / "ui/nav/Modules.kt"
REPORT = ANDROID / "ui/dispatcher/ReportCenter.kt"
AI_DECL = ANDROID / "ai/AiWriteSuppliers.kt"
AI_HANDLER = ANDROID / "ai/AiWriteSupplierHandlers.kt"
AI_RES = ANDROID / "ai/AiResources.kt"
AI_SVC = ANDROID / "ai/AiWriteService.kt"
AI_CRUD = ANDROID / "ai/AiWriteCrudHandlers.kt"
AW = ANDROID / "ai/AiWrite.kt"
COVERAGE = ROOT / "_tools/ai/_app_feature_coverage.py"
GUARDRAILS = ROOT / "_tools/ai/_check_ai_guardrails.py"
READ_CATALOG = ROOT / "docs/ai/ai_read_catalog.json"
ENDPOINTS = ROOT / "docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
LOCATOR = ROOT / "docs/PROJECT_MAP/08_CODE_LOCATOR.md"

#: 十一写动作 + 三读动作。⚠️ 动作 id → `AiWrites` 里的常量名**显式列出**，不靠推导：
#: 推导过一次，`supplier_payment.cancel` 被推成 `SUPPLIER_CANCEL`（真名是
#: `SUPPLIER_PAYMENT_CANCEL`），于是四条断言集体假红 —— 而"假红"的下场是这个检查被无视。
WRITE_ACTIONS: tuple[tuple[str, str], ...] = (
    ("supplier.create", "SUPPLIER_CREATE"),
    ("supplier.update", "SUPPLIER_UPDATE"),
    ("supplier.delete", "SUPPLIER_DELETE"),
    ("supplier.restore", "SUPPLIER_RESTORE"),
    ("supplier_payable.create", "SUPPLIER_PAYABLE_CREATE"),
    ("supplier_payable.update", "SUPPLIER_PAYABLE_UPDATE"),
    ("supplier_payable.delete", "SUPPLIER_PAYABLE_DELETE"),
    ("supplier_payable.restore", "SUPPLIER_PAYABLE_RESTORE"),
    ("supplier_payment.pay", "SUPPLIER_PAYMENT_PAY"),
    ("supplier_payment.cancel", "SUPPLIER_PAYMENT_CANCEL"),
    ("supplier_payment.restore", "SUPPLIER_PAYMENT_RESTORE"),
)
READ_ACTIONS = ("list_suppliers", "list_payables", "list_payments")


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的断言要跟着改）")
    return p.read_text(encoding="utf-8")


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
        self.ok(label, re.search(pattern, text) is not None, f"没找到 /{pattern}/")

    def absent(self, label: str, text: str, pattern: str) -> None:
        self.ok(label, re.search(pattern, text) is None, f"不该出现 /{pattern}/ 却出现了")


def _func_body(src: str, name: str) -> str:
    """取一个模块级函数的函数体（到下一个 `\\ndef ` 或文件尾为止）。

    ⚠️ 为什么要有它：判据里凡是"这个守卫还在不在"的断言，**只看函数名是不够的** ——
       反向验证第一次跑就抓到了：`def soft_delete_payable` 在、里面那句 `if n: raise`
       被改成 `n = 0`，红线照样全绿。函数名是"有一个函数"，函数体才是"它真的会拦"。
    """
    m = re.search(rf"^def {re.escape(name)}\(", src, re.M)
    if not m:
        return ""
    rest = src[m.end():]
    nxt = re.search(r"^def ", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def cashflow_readers() -> list[Path]:
    """**自己算出**读 `cash_flows` 的文件清单（⛔ 不许手写：本项目的「手写清单」已烂过 6 次）。

    判据 = 文件里出现了 `select(CashFlow)` 或 `query(CashFlow)`。
    ⚠️ 只算**取数**的文件：只写不读的（`accounting_service.py`、`order_return.py`）不在此列 ——
       它们构造 `CashFlow(...)` 而不查它。
    """
    pat = re.compile(r"select\s*\(\s*CashFlow|query\s*\(\s*CashFlow")
    out = []
    for p in sorted(BACKEND.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        if pat.search(read(p)):
            out.append(p)
    return out


def main() -> int:
    c = Checker()

    api = read(API)
    model = read(MODEL)
    flow_model = read(FLOW_MODEL)
    svc = read(SERVICE)
    schema = read(SCHEMA)
    boot = read(BOOTSTRAP)
    enums = read(ENUMS)
    test = read(TEST)
    ai_decl = read(AI_DECL)
    ai_handler = read(AI_HANDLER)
    ai_res = read(AI_RES)
    ai_svc = read(AI_SVC)
    ai_crud = read(AI_CRUD)
    aw = read(AW)

    # ---- ① 两张表：档案 + 应付单；付款**不是表** ----
    c.present("供应商档案模型（软删 + 时间戳）", model, r"class Supplier\(Base, TimestampMixin, SoftDeleteMixin\)")
    c.present("应付单模型（软删 + 时间戳）", model, r"class SupplierPayable\(Base, TimestampMixin, SoftDeleteMixin\)")
    c.present("名字唯一（重复档案会把同一个供应商的欠款拆成两半）", model, r'Index\("uq_suppliers_name", "name", unique=True\)')
    c.present("应付金额是 Numeric(12,2)（钱不许用 float）", model, r"amount: Mapped\[Decimal\] = mapped_column\(Numeric\(12, 2\)\)")
    c.present("模型文件头写明了「付款不是新表，它就是 cash_flows 的一行」", model, r"付款＝`cash_flows` 的一行")
    c.absent("⛔ 没有第三张「付款单」表（同一笔钱不许两处记）", model, r"class SupplierPayment\(")

    # ---- ② cash_flows 的软删 + 迁移 + **每一处读法都过滤** ----
    c.present("cash_flows 模型带软删（撤销付款的实现方式）", flow_model, r"class CashFlow\(Base, TimestampMixin, SoftDeleteMixin\)")
    c.present("线上迁移补这两列（唯一入口）", boot, r'ALTER TABLE cash_flows ADD COLUMN \{col\} \{ddl_type\}')
    c.present("迁移里两列的名字都在", boot, r'\(\("is_deleted", "BOOLEAN NOT NULL DEFAULT 0"\), \("deleted_at", "DATETIME"\)\)')
    c.present("⛔ 回填 0（留 NULL 会让历史流水整体从账上消失）",
              boot, r"UPDATE cash_flows SET is_deleted = 0 WHERE is_deleted IS NULL")

    readers = cashflow_readers()
    c.ok(f"算出来的 cash_flows 读取处数量合理（实测 {len(readers)}）", len(readers) >= 4,
         f"{[p.name for p in readers]}")
    for p in readers:
        src = read(p)
        name = p.relative_to(ROOT).as_posix()
        c.present(f"{name} 取 cash_flows 时带了 is_deleted 过滤",
                  src, r"CashFlow\.is_deleted\.is_\(False\)")
        # ⚠️ **只断言"文件里出现过一次"是不够的**：一个文件里可能有**好几处**取数
        #    （`order_money.py` 就有 3 处：加锁那一条 + 两个 `_group_sum`），
        #    漏掉其中一处时"出现过"依然成立 —— 反向验证抓到过这个假绿。
        #    所以再数一遍：**过滤的次数 ≥ 取数的次数**（两个数都自己算，不手写）。
        sites = len(re.findall(r"CashFlow\.order_id\.in_\(ids\)|select\(\s*CashFlow\s*\)", src))
        filters = len(re.findall(r"CashFlow\.is_deleted\.is_\(False\)", src))
        c.ok(f"{name} 的**每一处**取数都带过滤（{filters} ≥ {sites}）", filters >= sites,
             f"取数处 {sites}、过滤只有 {filters} 处 —— 漏掉的那一处会让「同一笔钱两个答案」")

    # ---- ③ 欠款口径只有一处 ----
    c.present("口径在服务里（Σ应付 − Σ付款 只此一份）",
              svc, r"def supplier_totals\(")
    c.present("付款求和带上了「没被撤销」这一条",
              svc, r"CashFlow\.is_deleted\.is_\(False\)")
    c.present("服务文件头写明「欠款只有一个实现」", svc, r"欠款只有一个实现")
    api_stripped = strip_comments(api)
    c.absent("⛔ 端点里不许自己 SUM 付款（那是第二个口径）",
             api_stripped, r"func\.sum\(\s*CashFlow\.amount")
    # 「端点里不许自己减出欠款」的判据要**精确**：`unpaid=svc.unpaid_of(...)` 那种
    # 关键字实参是**转发**、不是计算，拿 `unpaid\s*=` 去搜会把正确写法一起判红（那是假红，
    # 而假红的下场是这个检查被无视）。真正的违规形状是"端点里出现 paid 参与的加减"。
    c.absent("⛔ 端点里不许自己减出欠款（`- paid` 这种算术只许在服务里）",
             api_stripped, r"[-+]\s*paid\b")

    # ---- ④ 四条"宁可拒绝也不猜" ----
    c.present("付款不许超过还差（提前告知那两句）", svc, r"if amt > left:")
    # ⚠️ 但那两句是**读-判断-写**，而付款写的是**一行新的 cash_flows**（没有行可以 CAS）：
    #    三个并发的付款请求各自读到"已付 0、还差 1000"，各自插 1000 ——
    #    2026-09-23 并发实测：一张 1000 元的应付单**付出去 3000**（三条资金流水）。
    #    真闸门是"把应付单那一行当互斥量、把余额判据放进 WHERE"的条件 UPDATE。
    c.present("真闸门是条件 UPDATE（余额判据在 WHERE 里，由数据库串行化）",
              svc, r"update\(SupplierPayable\)[\s\S]{0,400}?SupplierPayable\.amount - paid_sub >= amt")
    c.present("已付合计用**统一的付款判据**算（不是端点里自己 SUM）",
              svc, r"paid_sub = \(\s*\n\s*select\(func\.coalesce\(func\.sum\(CashFlow\.amount\), 0\)\)[\s\S]{0,200}?_paid_filter\(")
    c.present("抢不到行 → 回滚 + 说清「刚刚被另一笔付款用掉了/付清了」",
              svc, r"if claimed\.rowcount != 1:[\s\S]{0,400}?db\.rollback\(\)[\s\S]{0,200}?刚刚被另一笔付款")
    c.present("付清了不许再付（说清应付/已付）", svc, r"已经付清了")
    # ⚠️ 这三条**必须看函数体**，不能只看"函数在不在"：反向验证抓到的第一个假绿就是这里 ——
    #    `def soft_delete_payable` 存在、而里面那句 `if n: raise` 被改成 `n = 0`，
    #    红线照样全绿（"函数在"与"它真的会拦"是两件事）。
    payable_del = _func_body(svc, "soft_delete_payable")
    c.ok("取到 soft_delete_payable 的函数体（取不到这条检查就是空转）", len(payable_del) > 200)
    c.present("⛔ 有活着的付款时**真的会拦**（函数体里得有 raise）", payable_del, r"raise HTTPException")
    c.present("⛔ 拦的判据是「数出来的笔数 > 0」（不是写死 0）", payable_del, r"n = payable_payment_count\(")
    supplier_del = _func_body(svc, "soft_delete_supplier")
    c.ok("取到 soft_delete_supplier 的函数体", len(supplier_del) > 200)
    c.present("⛔ 有应付单时**真的会拦**", supplier_del, r"raise HTTPException")
    c.present("删供应商**释放名字**（否则删掉再建同名会 500）",
              svc, r"supplier\.name = del_suffix\(supplier\.name, supplier\.id, SUPPLIER_NAME_WIDTH\)")
    c.present("恢复付款有三道门（单据还活着 / 供应商还活着）",
              api, r"它对应的应付单还在回收站里")
    c.present("按编号取付款时要认出「这不是一笔付款」",
              api, r"f\.party_type != svc\.PARTY_SUPPLIER")

    # ---- ⑤ 审计：九个动作码 + 中文名 ----
    for code in ("SUPPLIER_UPSERT", "SUPPLIER_DELETE", "SUPPLIER_RESTORE",
                 "SUPPLIER_PAYABLE_UPSERT", "SUPPLIER_PAYABLE_DELETE", "SUPPLIER_PAYABLE_RESTORE",
                 "SUPPLIER_PAYMENT_CREATE", "SUPPLIER_PAYMENT_CANCEL", "SUPPLIER_PAYMENT_RESTORE"):
        c.present(f"动作码 {code} 进了领域词汇表", enums, rf"{code} = \"{code}\"")
        c.present(f"审计页有 {code} 的中文名（⛔ 不许显示原始码）", read(REPORT), rf'"{code}" -> "')
    c.present("付款那一步真的写审计（钱出去了）", api, r"OperationAction\.SUPPLIER_PAYMENT_CREATE")

    # ---- ⑥ 常用度排序走唯一那份实现 ----
    c.present("usage 里加了 supplier 这个 kind", read(USAGE), r'KIND_SUPPLIER = "supplier"')
    c.present("列表排序走 with_popularity（⛔ 不自己写 ORDER BY）",
              api, r"with_popularity\(stmt, Supplier, usage_service\.KIND_SUPPLIER, current\)")

    # ---- ⑦ AI：十一条写动作 + 三组读能力 + 撤回资源 ----
    for act, const in WRITE_ACTIONS:
        c.present(f"AiWrites 里定义了 {act}", aw, rf'"{act}"')
        c.present(f"{act} 进了动作清单（ALL 里挂了 AiWriteSuppliers.ACTIONS）",
                  aw, r"AiWriteSuppliers\.ACTIONS")
        # 恢复类走 `restoreAction(...)`（没有 `id =` 那一段），所以只断言常量出现在声明文件里；
        # 「带 id = 的四个」另有一条更严的判据（下面那一条）。
        c.present(f"{act} 的声明引用了 AiWrites.{const}（`_show_undo_status` 靠它解析）",
                  ai_decl, rf"AiWrites\.{const}\b")
    # 只有带 `id = AiWrites.X,` 的那 6 个（档案/应付单的增改删）；
    # 三个 `restore` 走 `restoreAction(...)`（那一段本来就没有 `id =`），所以不在这一组里。
    for act, const in (WRITE_ACTIONS[0], WRITE_ACTIONS[1], WRITE_ACTIONS[2],
                       WRITE_ACTIONS[4], WRITE_ACTIONS[5], WRITE_ACTIONS[6]):
        c.present(f"{act} 的声明行写的就是 `id = AiWrites.{const}`",
                  ai_decl, rf"id = AiWrites\.{const},")
    c.present("付款是**手写**处理器（卡片要算「还差多少 → 付完还差多少」）", ai_handler, r"class SupplierPaymentWriteHandler\(")
    c.present("付款动作是 HIGH（钱真的出去了）", ai_decl, r'id = AiWrites\.SUPPLIER_PAYMENT_PAY,[\s\S]{0,200}?risk = AiWriteRisk\.HIGH')
    # ⚠️ 这两条只断言**那一行文字在**，不钉金额插值的写法：金额显示有一条独立的规矩
    #    （`moneyText` 去尾零，另一条线的红线在管），把插值形式钉死会与它互相打架 ——
    #    实测就撞过一次（对面把 `${payable.unpaid}` 包成 `moneyText(...)` 之后这两条假红）。
    c.present("卡片上写了「现在还差多少」", ai_handler, r"现在还差：")
    c.present("卡片上写了「付完之后还差多少」", ai_handler, r"付完之后：还差 ")
    c.present("卡片上写了「钱真的出去了」（不静默）", ai_handler, r"钱真的出去了")
    # ⚠️ 这两条**看的是真实的判据表达式**，不是"消息文本里出现过那句话"：
    #    第一版只搜「超过了这张单还差的」，而那句话在 throw 的参数里 ——
    #    把 `if (amountValue > unpaid)` 改成 `if (false)` 之后它照样绿（反向验证抓到的）。
    c.present("超付在**发卡之前**就拒绝（判据就是「这次付的 > 还差」）",
              ai_handler, r"if \(amountValue > unpaid\) \{")
    c.present("确实抛了（不是判了什么都不做）", ai_handler, r"if \(amountValue > unpaid\) \{[\s\S]{0,400}?throw AiWriteArgException")
    c.present("付清了也拒绝", ai_handler, r"if \(unpaid\.signum\(\) <= 0\) \{")
    c.present("声明式的付款撤销走 CrudSpec（一个目标 + 空字段表）",
              ai_decl, r"params = crudParams\(targets, fields\)")
    c.present("恢复动作走 restoreAction（undoOnly，模型看不见）",
              ai_decl, r'restoreAction\("供应商"')
    c.present("付款的「撤销 ↔ 恢复」在资源表里**成对**声明",
              ai_res, r"paired\(\s*\n\s*AiWrites\.SUPPLIER_PAYMENT_CANCEL,\s*\n\s*AiInverse\(\s*\n?\s*AiWrites\.SUPPLIER_PAYMENT_RESTORE")
    c.present("付款的撤回**不是**「再付一笔」（放回来走 restore）",
              ai_res, r"再付一笔同样的钱")
    c.ok("三个资源都进了撤回表（漏一个＝那类记录撤不回来）",
         all(k in ai_res for k in ('key = "supplier"', 'key = "supplier_payable"', 'key = "supplier_payment"')),
         "AiResource.TABLE 里缺一个")
    c.present("撤回要读现场（含回收站里的行，否则撤回链第二步退化）",
              ai_svc, r'repo\.suppliers\(includeDeleted = true\)')
    c.present("三个读名册方法在数据源接口里", ai_svc, r"suspend fun suppliers\(\): List<AiName>")
    c.present("读方法进了 guardrails 的读白名单（否则会被当成「在 prepare 里写库」）",
              read(GUARDRAILS), r'"suppliers", "supplierPayables", "supplierPayments",')
    for act in READ_ACTIONS:
        # ⚠️ 读目录 JSON 里 module 与 action 是**两个字段**（不是点号拼起来的那种 id）——
        #    写成 `"suppliers.list_suppliers"` 会四条断言集体假红。
        c.present(f"读目录里有 {act}（模型靠它选工具）", read(READ_CATALOG), rf'"action": "{act}"')
    c.present("那三条读能力都挂在 suppliers 模块下", read(READ_CATALOG), r'"module": "suppliers"')
    c.present("读能力被 App 模块认领（否则界面上看不到这个功能）",
              read(COVERAGE), r'"供应商/应付": \(')

    # ---- ⑧ 界面：两页 + 两个入口 + 界面上不自己算钱 ----
    detail = read(DETAIL_SCREEN)
    list_screen = read(LIST_SCREEN)
    c.present("档案页在", list_screen, r"fun SuppliersScreen\(")
    c.present("一个供应商的账在（应付单 + 付款记录）", detail, r"fun SupplierDetailScreen\(")
    c.present("挂一笔应付款的入口在", detail, r"挂一笔应付款（欠他多少）")
    c.present("付款弹层里会算出「付完之后还差」", detail, r"付完之后还差 ¥")
    c.present("超付在界面上就拦住（按钮不可点 + 一句人话）", detail, r"超过了还差的")
    c.present("撤销付款有「撤回」（用户定的硬规矩）", detail, r'actionLabel = "撤回"')
    c.present("删供应商也有「撤回」+ 回收站入口", list_screen, r'actionLabel = "撤回"')
    c.present("回收站入口在（「删除一律软删 + 手边要有恢复路径」）", list_screen, r"回收站")
    ui = strip_comments(list_screen) + strip_comments(detail)
    # ⚠️ 判据只认**减号**（`+` 不行：Kotlin 的字符串拼接全是 `+`，
    #    `"已付 ¥" + formatMoney(s.paidTotal)` 那种正确写法会被误判成"做算术" ——
    #    而假红的下场是这个检查被无视，反向验证第二次跑就抓到了这一条）。
    #    真正的违规形状是"两个合计相减"：`(payableTotal ?: 0) - (paidTotal ?: 0)`。
    # ✅ 唯一允许的界面内减法：付款弹层里"付完之后还差"那句展示（用的是**用户刚输入的数**
    #    和这张单的 `unpaid`，不是从两个合计里重新推一个欠款出来）。
    c.absent("⛔ 界面上不许自己减出欠款（`paidTotal` 附近不许出现减号）",
             ui, r"(paidTotal[^\n]{0,40}-)|(-[^\n]{0,40}paidTotal)")
    c.present("Routes 里两条路由", read(ROUTES), r'DISPATCH_SUPPLIERS = "dispatcher/suppliers"')
    c.present("详情路由（编号走查询串，一处拼）", read(ROUTES), r"fun supplierDetail\(supplierId: Long\)")
    c.present("NavGraph 注册了档案页", read(NAV), r"SuppliersScreen\(")
    c.present("NavGraph 注册了详情页", read(NAV), r"SupplierDetailScreen\(")
    c.present("账本管理入口页多了一格", read(MODULES), r'ModuleEntry\("供应商/应付", Routes\.DISPATCH_SUPPLIERS')
    c.present("「收支」页支出卡底部也有入口（用户说的就是「支出里给供应商付款」）",
              read(ANDROID / "ui/dispatcher/LedgerCashScreen.kt"), r"供应商 / 应付款")
    c.present("入口页那一格的颜色与邻居分得开（深玫红，判据实测 ≥60）",
              read(MODULES), r'ModuleEntry\("供应商/应付", Routes\.DISPATCH_SUPPLIERS, Icons\.Default\.Factory, color = 0xFFAD1457L\)')

    # ---- ⑨ 后端测试钉住了"欠款是算出来的、撤销两边一起变" ----
    c.present("测试里钉了分次付款", test, r"def test_分次付款_每次都要看得见")
    c.present("测试里钉了「撤销之后欠款变回来 + 收支也不再算它」",
              test, r"def test_撤销一笔付款_欠款变回来_收支也不再算它")
    c.present("测试里钉了超付被拒", test, r"def test_付款不许超过还差")
    c.present("测试里钉了有付款的单不许删", test, r"def test_有付款的单不许删")
    c.present("测试里钉了回收站里的供应商改不了", test, r"def test_回收站里的供应商改不了")
    c.present("测试里钉了货主/司机进不来（这些端点能动钱）", test, r"def test_货主和司机都进不来")

    # ---- ⑩ 文档指针 ----
    c.present("端点索引里有它（文档不许过期）", read(ENDPOINTS), r"GET /api/v1/suppliers")
    c.ok("设计规范里写了这一条规矩（并指路本判据）",
         "供应商" in read(DESIGN) and "_check_supplier_payables.py" in read(DESIGN),
         "缺一条：供应商/应付款的规矩 + 指路到本文件")
    loc = read(LOCATOR)
    c.ok("定位表里指到了它（并点名本判据）",
         "供应商" in loc and "_check_supplier_payables.py" in loc,
         "改这一块的人应当能从定位表找到本文件")

    total = c.passes + len(c.fails)
    if total < 60:
        print(f"❌ 只跑了 {total} 项（<60）—— 判据在空转，停。")
        return 1
    if c.fails:
        print(f"❌ 供应商/应付款红线不通过（{c.passes}/{total}）：")
        for f in c.fails:
            print("   [FAIL] " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过：欠款只有一个口径（付/撤两边一起变）、付款＝一行资金流水、"
          f"删除一律软删可恢复、AI 十一条动作与三组读能力都在（含撤回后路）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
