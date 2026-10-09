#!/usr/bin/env python3
"""_tools/finance/_check_expense_links.py —— 开销挂的关联必须真实存在，报表不许静默吞（BUG-0023 / 台账 TB-07）。

### 为什么要有它
台账 TB-07 实测（2026-10 窗口，9 行合计 5804.87）：一笔 7.77 元（expense id=55）的
driver_id / vehicle_id / order_id 全是 999999 —— 写的时候 200 落库，读的时候开销页那一行
名字全是空；同一窗口 GET /reports/profit 的 operating_expense_total=5804.87 认它，
GET /reports/vehicle-cost 的 expense_total=5598.50 不认它（5606.27 − 7.77）：一张表认、
一张表不认，两边都不报错。这条红线把「写入闸门」与「报表口径」两半钉在一起。

### 判据（六组，全部是读源码 + 读单测算出来的，清单不手写）
0. 反空转：三份源码认得出守卫与分桶函数（扫描坏了要先喊，不许安静地全绿）；
1. 写入闸门：守卫只有一份、挂在唯一写入闸门 create_expense 上且在落库之前、
   司机三态（不存在 / 已停用 / 已删除）、车辆两态、订单两态都拦、删除态走唯一实现
   has_del_suffix、失败一律 ValueError（HTTP 层才转 400）、六条文案都点名
   「字段名 + 那个 id + 怎么办」；
2. 报表三桶：_vehicle_expenses 已被 _expense_buckets 替换、不再把没挂车的行过滤掉、
   三块各自计数求和、逐车只吃挂到真实车辆那一块（expense_total 语义不变）、
   六个新字段都在返回体里、expense_window_total = 各车开销合计 + 挂不上的两块、
   notes = 静态六条 + 一次动态说明（只在真有挂不上的钱时出现）、动态行的金额全过
   money_text 且没有 markdown 星号、静态那六条原文没被改写；
3. response_model：VehicleCostReportOut 声明了六个新字段，且返回体的每个键都在
   schema 里有声明（清单是算出来的，不是手写的 —— 少一个键就是一个被静默丢掉的字段）；
4. 单测：backend/tests/test_expense_links.py 里五个行为各一支，钉着 400 与「文案含字段名
   + id」、三块相加、两张表对账的恒等式、「未挂车」说明行恰好一条；
5. 边界：api/v1/expenses.py 没有第二份校验（守卫只在服务层，AI / 种子脚本同一条路）、
   models/expense.py 没有加 ForeignKey（既有孤儿历史行不能被约束卡住）、报表层仍然只读、
   安卓的车辆成本 DTO 仍带 notes（说明行到得了用户眼前）。

用法：python _tools/finance/_check_expense_links.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools" / "qa"))
from _check_hints import Checker, read  # noqa: E402

ACC = ROOT / "backend/app/services/accounting_service.py"
VC = ROOT / "backend/app/services/reports/vehicle_cost_query.py"
SCH = ROOT / "backend/app/schemas/reports.py"
API = ROOT / "backend/app/api/v1/expenses.py"
MODEL = ROOT / "backend/app/models/expense.py"
TEST = ROOT / "backend/tests/test_expense_links.py"
DTO = ROOT / "android/app/src/main/java/com/tapmoay/sorders/data/remote/dto/Dtos.kt"

#: 三个关联字段 —— 判据里的清单算出来的地方就是这里（文案核对也按它循环）。
FIELDS = ("driver_id", "vehicle_id", "order_id")
#: 返回体必须新增的六格（expense_total 的语义一个字都不许变）。
NEW_KEYS = (
    "unlinked_expense_total",
    "unlinked_expense_count",
    "orphan_expense_total",
    "orphan_expense_count",
    "expense_window_total",
    "expense_window_count",
)
#: 五个行为各一支（名字写死在这里：改了名字就等于把行为契约删了）。
TESTS = (
    "test_不存在的关联必须被拒绝",
    "test_停用或已删掉的关联也不许挂",
    "test_车辆成本表把三块开销都摆出来",
    "test_同一个窗口两张表能对上",
    "test_软删司机与停用车辆之后历史开销还在",
)


def py_code(src: str) -> str:
    """剥掉井号注释与三引号文档串（保留字符串字面量）。

    为什么必须剥：判据里多条是「不许再出现某个写法」（isnot(None)、HTTPException、
    db.add(）—— 而本次改动的 docstring 里正写着旧写法的名字（SQL 里带
    vehicle_id IS NOT NULL）。不剥注释的话，「旧写法不许回来」会被自己那段说明误判成红。
    """
    out: list[str] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "#":
            j = src.find("\n", i)
            if j < 0:
                break
            i = j
            continue
        if src.startswith("\"\"\"", i) or src.startswith("'''", i):
            q = src[i:i + 3]
            j = src.find(q, i + 3)
            i = n if j < 0 else j + 3
            continue
        if c in "\"'":
            q = c
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == q:
                    j += 1
                    break
                j += 1
            out.append(src[i:j])
            i = j
            continue
        out.append(c)
        i += 1
    return "".join(out)


def block(src: str, header: str) -> str:
    """从 header 那一行开始，到下一个顶格定义为止（函数体 / 类体）。

    参数表跨行时（def _expense_buckets(）续行以右括号起头，不算新定义。
    """
    lines = src.split("\n")
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith(header):
            start = i
            break
    if start is None:
        return ""
    end = len(lines)
    for j in range(start + 1, len(lines)):
        ln = lines[j]
        if ln and not ln[0].isspace() and not ln.startswith(")"):
            end = j
            break
    return "\n".join(lines[start:end])


def notes_literal(src: str) -> str:
    """_NOTES: tuple[str, ...] = ( 那一段的正文（既有判据也用这个抠法，写法必须保持）。"""
    marker = "_NOTES: tuple[str, ...] = ("
    at = src.find(marker)
    if at < 0:
        return ""
    end = src.find("\n)", at)
    return src[at:end if end > 0 else len(src)]


def main() -> int:
    c = Checker()

    # ── 0. 反空转 ────────────────────────────────────────────────────────
    c.section("0. 反空转（扫描坏了要先喊）")
    for label, path, floor in (
        ("accounting_service.py", ACC, 20000),
        ("reports/vehicle_cost_query.py", VC, 6000),
        ("tests/test_expense_links.py", TEST, 8000),
    ):
        text = read(path) if path.exists() else ""
        c.ok(f"0-1 {label} 在且够长（≥{floor} 字符）", len(text) >= floor,
             "文件被改名 / 搬走 / 清空了？后面的判据会全部空过")
    acc = py_code(read(ACC)) if ACC.exists() else ""
    vc = py_code(read(VC)) if VC.exists() else ""
    c.ok("0-2 认得出守卫 _require_expense_links 与分桶 _expense_buckets",
         "def _require_expense_links(" in acc and "def _expense_buckets(" in vc,
         "函数被改名了？判据锚点必须跟着改，否则这一页会安静地全绿")

    # ── 1. 写入闸门（accounting_service.py）──────────────────────────────
    c.section("1. 写入闸门：关联不存在 / 不可用就不许落库")
    guard = block(acc, "def _require_expense_links(")
    create = block(acc, "def create_expense(")
    c.ok("1-1 守卫只有一份（服务层 _require_expense_links）",
         acc.count("def _require_expense_links(") == 1 and bool(guard),
         "0 份＝没人守；2 份＝两处判据迟早不一样（AI 与种子脚本走的是服务层那一条路）")
    call_at = create.find("_require_expense_links(db, body)")
    expense_at = create.find("e = Expense(")
    add_at = create.find("db.add(e)")
    c.ok("1-2 守卫挂在唯一写入闸门 create_expense 上，且在落库之前",
         call_at > 0 and expense_at > call_at and add_at > call_at,
         "守卫必须在 e = Expense( 与 db.add(e) 之前 —— 先落库再校验等于没校验（现金流水都写下去了）")
    c.ok("1-3 司机三态都拦（不存在 / 已停用 / 已删除）",
         "db.get(User, int(body.driver_id))" in guard
         and "driver is None" in guard
         and 'getattr(driver, "is_active", True)' in guard
         and "has_del_suffix(driver.id, driver.phone, driver.username)" in guard,
         "少一态就会漏：已停用账号 / 回收站里的账号都还能被挂上（用户下一步动作不一样）")
    c.ok("1-4 车辆两态都拦（不存在 / 已停用）",
         "db.get(Vehicle, int(body.vehicle_id))" in guard
         and "vehicle is None" in guard
         and 'getattr(vehicle, "is_active", True)' in guard,
         "车辆没有软删列，停用就是 is_active=False —— 不拦就会挂到一辆已停用的车")
    c.ok("1-5 订单两态都拦（不存在 / 在回收站）",
         "db.get(Order, int(body.order_id))" in guard
         and "order is None" in guard
         and 'getattr(order, "deleted_at", None) is not None' in guard,
         "订单的已删除只有 deleted_at 一个判据（软删 + 回收站）")
    c.ok("1-6 删除态用的是唯一实现 has_del_suffix（不抄第二份）",
         "from app.services.soft_delete import has_del_suffix" in acc
         and not re.search(r"_del\{|_del\"|endswith\(\"_del", guard),
         "手机号后缀 _del<id> 这个约定只有一处实现；手抄一份，改口径时两边就会不一样")
    raises = re.findall(r'raise ValueError\(\s*f"([^"]*)"', guard)
    c.ok(f"1-7 失败一律 ValueError（HTTP 层才转 400）：{len(raises)} 条",
         len(raises) >= 6 and "HTTPException" not in guard,
         "服务层抛 HTTPException 就等于把 AI / 种子脚本那两条路绕过去了（400 由路由层转）")
    bad_msg = [m for m in raises
               if not any(f + "={" in m for f in FIELDS) or "请" not in m]
    c.ok(f"1-8 六条文案都点名「字段名 + 那个 id + 怎么办」：{len(raises)} 条",
         len(raises) >= 6 and not bad_msg,
         "缺字段名 / 缺 id，用户拿着 400 不知道改哪一格：" + "、".join(bad_msg[:3]))

    # ── 2. 报表三桶（vehicle_cost_query.py）──────────────────────────────
    c.section("2. 报表口径：挂不上的钱必须看得见（不许静默吞）")
    buckets = block(vc, "def _expense_buckets(")
    build = block(vc, "def build_vehicle_cost(")
    c.ok("2-1 旧的 _vehicle_expenses 已被三桶函数替换",
         "def _vehicle_expenses(" not in vc and bool(buckets),
         "旧函数只返回挂到车的那一块，孤儿行进了字典却没有任何一行消费它 —— 静默吞就在这里")
    c.ok("2-2 分桶在 build_vehicle_cost 里被调用（车辆 id 集合是算出来的）",
         "_expense_buckets(db, start, end, {int(v.id) for v in vehicles})" in build,
         "三块的分法必须是「这一笔能不能算到某台车上」，集合不许手写")
    c.ok("2-3 分桶不再把没挂车 / 挂不到车的行过滤掉",
         "isnot(None)" not in buckets and "isnot(None)" not in vc,
         "改前 SQL 里那句 vehicle_id IS NOT NULL 就是把孤儿行丢掉的那一刀")
    c.ok("2-4 三块都各自计数与求和（不是只算挂车的）",
         "func.count(Expense.id)" in buckets and "func.sum(Expense.amount)" in buckets
         and 'unlinked["total"] +=' in buckets and 'unlinked["count"] +=' in buckets
         and 'orphan["total"] +=' in buckets and 'orphan["count"] +=' in buckets
         and "window_count +=" in buckets,
         "少一块就等于把「另有 N 笔 X 元」这句话省掉了（用户仍然对不上账）")
    c.ok("2-5 逐车只吃挂到真实车辆那块（expense_total 语义不变）",
         "items = linked.get(int(v.id), [])" in build
         and '"expense_total": expense_total_all,' in build
         and 'expense_total_all = sum((r["expense_total"] for r in per_vehicle), _ZERO)' in build,
         "expense_total 一旦把没挂车的钱吞进来，_tools/seed/_verify_ledger_math.py 的逐车对账会红")
    missing_keys = [k for k in NEW_KEYS if '"' + k + '":' not in build]
    c.ok(f"2-6 六个新字段都在返回体里（缺 {len(missing_keys)}）", not missing_keys,
         "缺的：" + "、".join(missing_keys) + " —— 报表返回体少一格，用户就没法拿两张表对上账")
    c.ok("2-7 expense_window_total = 各车开销合计 + 挂不上的两块",
         'off_vehicle_total = unlinked["total"] + orphan["total"]' in build
         and "expense_window_total = expense_total_all + off_vehicle_total" in build,
         "这一格就是对账用的：少了它，同一窗口里利润表认、车辆成本表不认的那笔钱就又没名字了")
    c.ok("2-8 notes = 静态六条 + 一次动态说明（真有挂不上的钱时才出现）",
         "notes = list(_NOTES)" in build
         and 'if unlinked["count"] or orphan["count"]:' in build
         and "notes.append(" in build and '"notes": notes,' in build,
         "动态行不许常显：没有挂不上的钱时一个字都不多说（否则每张报表都挂一句废话）")
    appt = re.search(r"notes\.append\((.*?)\n\s*\)", build, re.S)
    note_line = appt.group(1) if appt else ""
    c.ok("2-9 动态说明行含笔数与金额，金额全过 money_text",
         note_line.count("money_text(") >= 4
         and "笔" in note_line and "未挂车" in note_line and "查不到车辆" in note_line,
         "至少 4 处金额（未挂车金额 / 查不到车金额 / 窗口合计 / 各车合计）都要过共享显示口径")
    c.ok("2-10 动态说明行没有 markdown 星号，也没有 ¥ 花括号写法",
         "**" not in note_line and "¥{" not in note_line,
         "手机上会原样显示成两个星号；金额写法只有 money_text 一份")
    static_notes = notes_literal(read(VC)) if VC.exists() else ""
    c.ok("2-11 _NOTES 静态那几条原文没被改写（里面没有「未挂车」）",
         "没挂车" in static_notes and "未挂车" not in static_notes,
         "静态口径被改成动态那句话的措辞，单测里「恰好一条说明行」的判据就会失效")

    # ── 3. response_model ────────────────────────────────────────────────
    c.section("3. response_model 同步（返回体不许被静默丢掉）")
    sch = py_code(read(SCH)) if SCH.exists() else ""
    cls = block(sch, "class VehicleCostReportOut(")
    missing_decl = [k for k in NEW_KEYS
                    if not re.search(r"^\s+" + k + r": (Decimal|int)", cls, re.M)]
    c.ok(f"3-1 VehicleCostReportOut 声明了六个新字段（缺 {len(missing_decl)}）",
         not missing_decl, "缺的：" + "、".join(missing_decl))
    ret = build[build.rfind("return {"):]
    ret_keys = re.findall(r'"([a-z_]+)":', ret)
    undeclared = [k for k in ret_keys if not re.search(r"^\s+" + k + r":", cls, re.M)]
    c.ok(f"3-2 返回体的每个键都在 response_model 里有声明（{len(ret_keys)} 个键，缺 {len(undeclared)}）",
         bool(ret_keys) and not undeclared,
         "没声明的键会被 FastAPI 静默丢掉：" + "、".join(undeclared))

    # ── 4. 单测 ──────────────────────────────────────────────────────────
    c.section("4. 单测钉着五个行为")
    test = read(TEST) if TEST.exists() else ""
    missing_tests = [t for t in TESTS if "def " + t + "(" not in test]
    c.ok(f"4-1 五个行为各一支（缺 {len(missing_tests)}）", not missing_tests,
         "缺的：" + "、".join(missing_tests))
    c.ok("4-2 单测钉着 400 与「文案含字段名 + id」",
         test.count("assert r.status_code == 400") >= 4
         and 'r.json()["detail"]' in test and "999999" in test,
         "只断言不是 200 不够：用户要看到是哪个字段、哪个 id")
    identity_vc = ('assert _dec(vc, "expense_window_total") == _dec(pf, "operating_expense_total")'
                   ' + _dec(pf, "tax_total")')
    identity_three = ('_dec(d, "expense_total") + _dec(d, "unlinked_expense_total")'
                      ' + _dec(d, "orphan_expense_total")')
    c.ok("4-3 单测钉着三块相加与两张表对账的恒等式",
         identity_vc in test and identity_three in test,
         "必须是逐字的那两条恒等式：只在文件里出现「operating_expense_total」这种词不算 ——"
         "文档串里也有这个词，恒等式行被删掉时它会替它撑着，判据就空过了")
    c.ok("4-4 单测钉着「未挂车」说明行恰好一条",
         'if "未挂车" in n' in test and "len(hit) == 1" in test,
         "说明行要么漏、要么叠成两条 —— 静态那几条里讲的是没挂车，措辞必须分得开")

    # ── 5. 边界 ──────────────────────────────────────────────────────────
    c.section("5. 边界：不越界、不加约束、不改别人")
    api = py_code(read(API)) if API.exists() else ""
    api_post = block(api, "def create_expense(")
    c.ok("5-1 api/v1/expenses.py 没有第二份校验（守卫只在服务层）",
         "has_del_suffix" not in api and "is_active" not in api
         and "_require_expense_links" not in api
         and "except ValueError" in api_post and "status_code=400" in api_post
         and api_post.count("HTTPException") == 1,
         "写在路由层只能拦住 HTTP：AI 的记一笔支出与两个种子脚本会从旁边走过去；"
         "而且服务层抛的 ValueError 必须由这里转成 400（改成 except Exception 会让 400 变 500）")
    model = py_code(read(MODEL)) if MODEL.exists() else ""
    c.ok("5-2 expenses 表没有加 ForeignKey（既有孤儿历史行不能被约束卡住）",
         "ForeignKey" not in model,
         "库里已经有 id=55 那种孤儿行：加约束要先迁移 + 清数据，代价与风险不成比例（BUG-0023 已定案）")
    c.ok("5-3 报告层仍然只读（没有写动词）",
         not re.search(r"db\.(add|flush|commit|delete|merge)\(", vc)
         and "db.execute(update" not in vc,
         "报表包在 AST 层被 _check_report_boundary.py 禁写，这里再补一张网")
    dto = block(read(DTO), "data class VehicleCostReportDto(") if DTO.exists() else ""
    c.ok("5-4 安卓的车辆成本 DTO 仍带 notes（说明行到得了用户眼前）",
         '@SerialName("notes")' in dto,
         "后端 notes 有内容、客户端 DTO 不解析 = 用户还是看不到另有 N 笔 X 元")

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项未通过（通过 {c.n_ok} 项）：")
        for label, _ in c.fails:
            print(f"   - {label}")
        return 1
    print(f"✅ 全部 {c.n_ok} 项通过。开销的关联必须真实存在、报表不许静默吞、两张表能对上（BUG-0023 / TB-07）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
