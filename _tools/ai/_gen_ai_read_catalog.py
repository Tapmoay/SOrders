"""从后端源码生成「AI 可读列表」目录（**机器生成，不许手抄**）。

### 为什么要生成而不是手写
`docs/ai/ai_toolmap.json` 里已经写明：「**不含 Query 参数与 alias，不可据此生成参数白名单**」。
而"让 AI 读所有列表"恰恰要求参数是准的——参数名错一个字符，用户看到的就是"查不到"。
所以这里直接对 `backend/app/api/v1/*.py` 做 AST 解析，把每个只读端点的 Query/Path 参数、
别名、默认值、枚举取值全部抽出来，再落成两份产物：

- `docs/ai/ai_read_catalog.json`  —— 全量目录（人看 / 校验用）
- `android/app/src/main/java/com/tapmoay/sorders/ai/AiReadCatalog.kt` —— App 侧白名单（编译期带上）

`--check` 模式只比对不写入，供红线脚本调用（防止有人手改了 Kotlin 那份）。

### 怎么判定「列表」
按**路径里有没有 `{}`**：有路径参数（`/orders/{order_id}`）的就是"按 id 查详情"，
而 AI **看不到任何内部编号**（本项目第一条硬规矩），所以这类端点不暴露给它。
这一点很重要：暴露了它也只能瞎猜 id。
"""
import ast
import importlib.util
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
API_DIR = ROOT / "backend/app/api/v1"
TOOLMAP = ROOT / "docs/ai/ai_toolmap.json"
JSON_OUT = ROOT / "docs/ai/ai_read_catalog.json"
KT_OUT = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiReadCatalog.kt"

# 端点级授权真相的来源：`backend/scripts/gen_endpoint_index.py` 的 collect()。
# ⚠️ 为什么不自己再写一遍 AST 解析、也不读 `08A_ENDPOINT_INDEX.md`：
#   ① 那份索引是**它的产物**，可能过期；直接调它的 collect() 永远是源码现状；
#   ② 它已经处理了三种授权写法（注解 / Depends / 体内 raise 403）和别名递归，
#      这是踩过坑才攒出来的（索引文档里写着"授权列错得比缺更危险"），抄一遍只会抄漏。
ENDPOINT_GEN = ROOT / "backend/scripts/gen_endpoint_index.py"
RBAC = ROOT / "backend/app/core/rbac.py"
BACKEND_APP = ROOT / "backend/app"

# 后端角色键（rbac.py 的 ROLE_PERMISSIONS 键、UserRole 取值都是小写这些）
BACKEND_ROLES = ("dispatcher", "driver", "shipper")

# 授权列里的中文角色 → 角色键。`司机本人` 是 `_can_view_or_raise` 那种
# "派单员，或者是这个司机自己"的写法，落到角色上就是 driver。
ROLE_CN_TO_KEY = {"派单员": "dispatcher", "司机": "driver", "司机本人": "driver", "货主": "shipper"}

# 体内角色门槛里"说不清"的标签：出现它说明函数体里**有**角色判断但生成器不敢下结论。
# 处理方式：**不据此收窄**（否则 `GET /orders` 这种"货主只能看自己的单"会被整条砍掉，
# 而那恰恰是货主最需要的一条），只把它记进 JSON 的 auth 说明里。
ROLE_CHECK_UNKNOWN = "体内含角色判断（需读源码）"

# 依赖注入参数（不是查询参数）
SKIP_ANNOT = ("Depends", "Request", "Response", "BackgroundTasks", "Session")

# 后端 bool 查询参数的各种写法 → 统一成 bool
BOOL_TYPES = ("bool",)

# 允许出现在工具调用里的参数类型（其余一律不进白名单：对象/列表/文件流都没法让模型安全地填）
ALLOWED_TYPES = {"str", "int", "float", "bool", "date", "datetime", "Literal"}


def ann_name(node: ast.AST | None) -> str:
    """注解 → 类型名（去掉 Optional[...] 外壳，保留 Literal 的取值）。"""
    if node is None:
        return ""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Subscript):
        base = ann_name(node.value)
        if base in ("Optional", "Union", "Annotated"):
            inner = ann_name(node.slice)
            return inner
        return base
    if isinstance(node, ast.BinOp):  # `str | None`
        return ann_name(node.left)
    return ""


def literal_values(node: ast.AST | None) -> list[str]:
    """`Literal["a","b"]` → ["a","b"]；其它返回空。"""
    if isinstance(node, ast.Subscript) and ann_name(node.value) == "Literal":
        out = []
        for el in getattr(node.slice, "elts", []):
            if isinstance(el, ast.Constant):
                out.append(str(el.value))
        return out
    return []


def enum_table() -> dict[str, list[str]]:
    """`backend/app/models/enums.py` → {枚举类名: [取值]}。

    为什么必须解析它：像 `status_filter: OrderStatus | None = Query(None, alias="status")`
    这种**枚举类型**的查询参数，如果只按"类型名不在允许列表里就跳过"处理，
    `status` 会从目录里消失——而"按状态筛订单"恰恰是派单员最常问的一类问题。
    实测就是这么漏掉的：模型想按已送达筛，但目录里没有这个条件，它只能如实说"接口不支持"。
    （AGENTS.md 也写着：想知道状态/枚举叫什么，先读 enums.py。）
    """
    out: dict[str, list[str]] = {}
    py = ROOT / "backend/app/models/enums.py"
    if not py.exists():
        raise SystemExit(f"找不到 {py}（枚举表是参数白名单的一部分，不能缺）")
    tree = ast.parse(py.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        vals: list[str] = []
        for stmt in node.body:
            # `NAME = "value"` 形态（本仓库全部是 str 枚举，成员名与取值相同）
            if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant):
                if isinstance(stmt.value.value, str):
                    vals.append(stmt.value.value)
        if vals:
            out[node.name] = vals
    return out


def perm_roles() -> dict[str, set[str]]:
    """`权限:ORDER_DISPATCH` → 持有该权限点的角色集合（来自 rbac.py 的 ROLE_PERMISSIONS）。"""
    tree = ast.parse(RBAC.read_text(encoding="utf-8"))
    node: ast.AST | None = None
    for st in ast.walk(tree):
        if isinstance(st, ast.AnnAssign) and getattr(st.target, "id", "") == "ROLE_PERMISSIONS":
            node = st.value
        elif isinstance(st, ast.Assign) and any(
            getattr(t, "id", "") == "ROLE_PERMISSIONS" for t in st.targets
        ):
            node = st.value
    if not isinstance(node, ast.Dict):
        raise SystemExit(f"读不出 {RBAC} 里的 ROLE_PERMISSIONS（改名了？授权推导要跟着改）")
    out: dict[str, set[str]] = {}
    for k, v in zip(node.keys, node.values):
        role = getattr(k, "value", None)
        if role not in BACKEND_ROLES:
            continue
        for el in ast.walk(v):
            if isinstance(el, ast.Attribute):
                out.setdefault(el.attr, set()).add(role)
    if not out:
        raise SystemExit("ROLE_PERMISSIONS 解析出来是空的——权限点→角色的映射不能缺")
    return out


def _load_endpoint_gen():
    spec = importlib.util.spec_from_file_location("_gen_endpoint_index", ENDPOINT_GEN)
    if spec is None or spec.loader is None:
        raise SystemExit(f"加载不了 {ENDPOINT_GEN}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def roles_from_row(row: dict, perms: dict[str, set[str]], mod) -> set[str]:
    """端点授权行 → 「哪些角色调它不会被挡」。

    规则（**入口级是硬的，体内只在明确写死时才是硬的**）：
      · `权限:X`      → 持有 X 的角色（rbac.py 是这份映射的唯一真相）；
      · `角色:a|b`    → 就是这几个；
      · `仅登录`/公开 → 所有角色（**行级隔离由后端在体内做**，例如货主调 /orders 只拿到自己的单）；
      · `体内仅允许:A|B` / `体内排除:C` → 与/差（这两类在索引里是**带 raise 403 的硬门槛**）；
      · `体内权限:X`（条件性）与 `体内含角色判断（需读源码）` → **不收窄**：
        前者只在部分分支生效，后者是"说不清"。为此砍掉一条能力，代价是用户明明有权限却被告知不能查。
    """
    allow: set[str] | None = None
    for lab in row.get("auth", []):
        if lab == mod.LOGIN_ONLY:
            continue
        if lab.startswith("角色:"):
            want = {s for s in lab[len("角色:"):].split("|") if s in BACKEND_ROLES}
        elif lab.startswith("权限:"):
            want = perms.get(lab[len("权限:"):], set())
        else:
            raise SystemExit(
                f"认不出的入口级授权标签：{lab!r}（端点 {mod.compose_url(row, '/api/v1')}）"
                "——宁可报错也不要瞎猜：授权推导猜错，等于把不该给的能力给了 AI。"
            )
        allow = want if allow is None else (allow & want)
    roles = set(BACKEND_ROLES if allow is None else allow)

    for lab in list(row.get("guard_labels", [])) + list(row.get("inline_roles", [])):
        if lab == ROLE_CHECK_UNKNOWN:
            continue
        if lab.startswith("体内仅允许:"):
            roles &= {ROLE_CN_TO_KEY[t] for t in lab[len("体内仅允许:"):].split("|") if t in ROLE_CN_TO_KEY}
        elif lab.startswith("体内排除:"):
            roles -= {ROLE_CN_TO_KEY[t] for t in lab[len("体内排除:"):].split("|") if t in ROLE_CN_TO_KEY}
    return roles


def endpoint_roles() -> dict[tuple[str, str], dict]:
    """{(METHOD, url): {"roles": {...}, "auth": "授权原文"}}。"""
    mod = _load_endpoint_gen()
    app_root = str(BACKEND_APP)
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(app_root):
        dirnames[:] = [d for d in dirnames if d not in mod.SKIP_DIRS]
        for fn in sorted(filenames):
            if fn.endswith(".py"):
                files.append(os.path.relpath(os.path.join(dirpath, fn), app_root).replace("\\", "/"))
    files.sort()
    rows, _ = mod.collect(app_root, files)
    prefix = mod._read_api_prefix(app_root) or "/api/v1"
    perms = perm_roles()
    out: dict[tuple[str, str], dict] = {}
    for r in rows:
        url = mod.compose_url(r, prefix)
        out[(str(r.get("method", "")).upper(), url)] = {
            "roles": roles_from_row(r, perms, mod),
            "auth": mod.auth_text(r),
        }
    return out


def query_meta(call: ast.Call) -> dict:
    """把一个 `Query(...)` / `Path(...)` 调用的参数抽成 dict（**含第一个位置参数 = 默认值**）。

    ⚠️ 这里踩过一次：FastAPI 的写法是 `Query(default, alias=...)`，默认值常写成**位置参数**
    （`Query(None, alias="date_from")`）。只读关键字参数就会把它当成"没有默认值"→ 判成**必填**，
    于是工具会给每个可选日期都补上"本月"——**把用户的「所有订单」悄悄变成「本月订单」**。
    是单测 `optionalDatesAreNotFilledIn` 抓住的。
    """
    meta: dict = {}
    if call.args:
        try:
            meta["default"] = ast.literal_eval(call.args[0])
        except Exception:
            # `Query(...)` 里的 `...` 是 Ellipsis，literal_eval 在部分版本上会抛；统一当"必填"
            meta["default"] = Ellipsis
        if isinstance(call.args[0], ast.Constant) and call.args[0].value is Ellipsis:
            meta["default"] = Ellipsis
    for kw in call.keywords:
        if kw.arg is None:
            continue
        try:
            meta[kw.arg] = ast.literal_eval(kw.value)
        except Exception:
            meta[kw.arg] = None
    return meta


def is_route(fn: ast.AST, methods: tuple[str, ...]) -> bool:
    for d in getattr(fn, "decorator_list", []):
        if isinstance(d, ast.Call) and getattr(d.func, "attr", "") in methods:
            return True
    return False


def route_info(fn: ast.AST) -> tuple[str, str]:
    """(method, path)"""
    for d in getattr(fn, "decorator_list", []):
        if isinstance(d, ast.Call) and getattr(d.func, "attr", "") in ("get", "post", "patch", "delete", "put"):
            path = ""
            if d.args and isinstance(d.args[0], ast.Constant):
                path = str(d.args[0].value)
            return getattr(d.func, "attr"), path
    return "", ""


def extract() -> dict:
    toolmap = json.loads(TOOLMAP.read_text(encoding="utf-8"))
    read_ids = {
        f"{mod}.{a['action']}": a
        for mod, m in toolmap["modules"].items()
        for a in m["actions"]
        if a["risk"] == "read"
    }
    cn_of = {mod: m.get("cn", mod) for mod, m in toolmap["modules"].items()}

    # 端点授权（谁能调）——**每个动作都必须查到**，查不到直接报错，不许默默放行。
    auth_of = endpoint_roles()

    # handler 名 → 参数表（同名 handler 在不同模块里也可能重名，所以按 (模块, handler) 索引）
    found: dict[str, dict] = {}
    enums_of = enum_table()
    for py in sorted(API_DIR.glob("*.py")):
        mod = py.stem
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not is_route(fn, ("get",)):
                continue
            method, path = route_info(fn)
            key = f"{mod}.{fn.name}"
            if key not in read_ids or key in EXCLUDE:
                continue
            # ⚠️ **路径以 toolmap 为准，不用 AST 里那个**：`@router.get("/summary")` 拿到的是
            # **相对路由前缀**的路径（还有大量是空串，例如 `@router.get("")`），
            # 直接拿来发请求会打到 `/api/v1/` 上 → 404。
            # 踩过一次：真机上模型如实回报「read_data 整个暂不可用」，就是这里。
            full_path = read_ids[key]["path"]
            if path and not full_path.endswith(path):
                raise SystemExit(
                    f"❌ {key} 的路径对不上：toolmap={full_path} / 源码={path}"
                    "（路由前缀改过？先重跑 _gen_ai_toolmap.py，再重跑本脚本）",
                )
            # 只收**路径里没有 {}** 的端点：带路径参数的是"按 id 查详情"，
            # 而 AI 看不到任何内部编号（第一条硬规矩）——暴露了它也只能瞎猜 id。
            if "{" in full_path:
                continue
            params = []
            skipped = []
            for a in fn.args.args + fn.args.kwonlyargs:
                name = a.arg
                if name in ("self", "db", "session"):
                    continue
                ann = a.annotation
                ann_s = ast.unparse(ann) if ann is not None else ""
                if any(s in ann_s for s in SKIP_ANNOT):
                    continue
                t = ann_name(ann)
                default_node = None
                # 找默认值
                all_args = fn.args.args
                if a in all_args:
                    idx = all_args.index(a) - (len(all_args) - len(fn.args.defaults))
                    if idx >= 0:
                        default_node = fn.args.defaults[idx]
                elif a in fn.args.kwonlyargs:
                    di = fn.args.kwonlyargs.index(a)
                    default_node = fn.args.kw_defaults[di]

                is_query = isinstance(default_node, ast.Call) and getattr(default_node.func, "id", "") == "Query"
                is_path = isinstance(default_node, ast.Call) and getattr(default_node.func, "id", "") == "Path"
                if not (is_query or is_path):
                    continue
                meta = query_meta(default_node)
                default = meta.get("default", Ellipsis)
                alias = meta.get("alias") or name
                enums = literal_values(ann)
                if not enums and t in enums_of:
                    # 枚举类型的查询参数：把它当成"只允许这几个取值"，且**必须留在目录里**
                    enums = enums_of[t]
                    t = "Literal"
                elif enums:
                    t = "Literal"
                if t not in ALLOWED_TYPES and not is_path:
                    skipped.append(f"{alias}:{t}")
                    continue
                params.append({
                    "name": alias,
                    "arg": name,
                    "type": t,
                    # 必填 = 默认值是 `...`（FastAPI 约定）；注意 `Query(None)` 是**可选**
                    "required": default is Ellipsis and not is_path,
                    "enum": enums,
                    "is_id": alias.endswith("_id") or alias == "id" or name.endswith("_id"),
                    "is_path": is_path,
                    "desc": "",
                })
            key_auth = auth_of.get((method.upper(), full_path))
            if key_auth is None:
                raise SystemExit(
                    f"❌ {key} 的授权查不到：{method.upper()} {full_path} 不在端点索引生成器的结果里。\n"
                    "   宁可报错也不放行：没有授权就等于不知道该给谁看，"
                    "放行会让货主/司机拿到一张必然 403 的表（AI 只能如实回一句'查不了'）。"
                )
            found[key] = {
                "module": mod,
                "action": fn.name,
                "cn": cn_of.get(mod, mod),
                "module_cn": cn_of.get(mod, mod),
                "method": method,
                "path": full_path,
                "at": f"backend/app/api/v1/{py.name}:{fn.lineno}",
                "auth": key_auth["auth"],
                "roles": sorted(key_auth["roles"]),
                # 只有批发商货主能读的表（见 MEMBER_ONLY_READS 的理由）
                "member_only": f"{mod}.{fn.name}" in MEMBER_ONLY_READS,
                "params": params,
                "skipped_params": skipped,
            }

    missing = sorted(set(read_ids) - set(found))
    # 「找不到 handler」只对**本来应该收进来的**动作报错：带路径参数的详情端点、非 GET 的导出、
    # 以及 EXCLUDE 里明确排除的，本来就不在目录里，不算缺失。
    expected = {
        k: v for k, v in read_ids.items()
        if "{" not in v["path"] and v["method"] == "get" and k not in EXCLUDE
    }
    missing = sorted(set(expected) - set(found))
    return {
        "generated_by": "_gen_ai_read_catalog.py",
        "authority_note": (
            "只读端点目录，参数来自 backend/app/api/v1/*.py 的 AST（含 alias）。"
            "只收**路径里没有 {}** 的端点：带路径参数的是按 id 查详情，而 AI 看不到任何内部编号。"
        ),
        "counts": {
            "read_endpoints": len(read_ids),
            "listed": len(found),
            "missing_handler": missing,
        },
        "actions": sorted(found.values(), key=lambda x: f"{x['module']}.{x['action']}"),
    }


# 明确排除（每条都要写清理由，免得以后有人以为是漏了）
EXCLUDE = {
    # GET 但返回的是**文件流**（xlsx），不是列表；导出走专门的 export_sheet 工具（要写临时文件）
    "reports.export_report",
}

# 每个动作的中文说明（**必须逐条写**：模型选工具靠的就是这句话）。
# 缺条目时生成器直接报错退出，逼着人补——不许出现"没有说明的工具"。
CN_DESC = {
    "orders.list_orders": "订单列表（可按状态/日期/货主名/司机名筛选）",
    # 退货申请（2026-09-21）：**两张表分给两个人**，说明里必须写清"谁的申请"，
    # 否则模型会给派单员查"我提的申请"（他从来不提单），或让货主看到全店的待办。
    "return_requests.list_my_return_requests": (
        "我（货主）自己提过的退货申请：待派单员处理的、已办完的、被驳回的（含驳回原因）"
    ),
    "return_requests.list_return_requests": (
        "待派单员处理的退货申请（货主提的、还没办的）：谁提的、要退哪几样、各几件"
    ),
    "orders.pending_dispatch_count": "待派单池还有多少单",
    "order_products.list_order_products": "订单商品行（按订单或商品查）",
    "products.list_products": "商品列表（含库存、批发价档位）",
    "products.product_cost_history": (
        "商品成本价的历史（某段时间的成本价是多少、从什么时候到什么时候、是进货录的还是手改的）"
    ),
    "product_categories.list_categories": "商品分类名册（下单页左侧那一列的分组与显示顺序，带每类下有几个商品）",
    "inventory.inventory_summary": "库存汇总（可只看低于报警线的）",
    "inventory.list_movements": "库存流水（入库/出库/盘点记录）",
    "users.list_users": "账号/人员列表（货主、司机、批发商、内部账号，可按角色与关键词筛）",
    "users.read_me": "当前登录账号自己的资料",
    "customers.list_customers": "客户列表",
    "vehicles.list_vehicles": "车辆列表",
    "ledger.list_entries": "订单账流水（手动记账 + 订单产生的收支）",
    "ledger.list_accounts": "按货主/批发商汇总的账目（谁欠多少、结了多少）",
    "ledger.list_receipts": "收款记录",
    "ledger.list_temp_shipper_names": "临时货主名清单",
    "cash_flows.list_cash_flows": "现金流水",
    "cash_flows.cash_flow_summary": "现金收支汇总（按期合计流入/流出）",
    # 账本管理「收支」页那两段（2026-09-22）：**每一路钱分别多少**。
    # 汇总只有三个数，答不了"这段时间钱都花哪了 / 收入都是从哪来的"——那正是用户会问的。
    "cash_flows.cash_flow_breakdown": "收支分项（收入按来源、支出按去路，每路带金额与笔数）",
    # 预订单（2026-09-22）：模型要"照上次那样再下一单"时先读它，再走 orders.create。
    "order_templates.list_templates": "预订单（预设好的订单：货主/地址/运费/商品与数量）",
    # 供应商 / 厂商 + 应付款（2026-09-22 用户要求「给供应商付尾款」）。
    # 三张表对应三件事：档案名册（谁）、应付单（欠他多少）、付款记录（钱什么时候出去的）。
    # ⚠️ 三句话都要写清"它回答什么问题" —— 模型就是照这三句话决定读哪一张的。
    "suppliers.list_suppliers": "供应商/厂商名册（含各自还欠多少、累计应付与已付）",
    "suppliers.list_payables": "应付单（欠某个供应商的每一笔钱：事由、应付总额、已付、还差、付过几次）",
    "suppliers.list_payments": "付款记录（给供应商付过的每一笔：金额、日期、方式，以及它挂在哪张应付单上）",
    # 货主自己那一本账的**收支统计**（2026-09-22 用户要求「账本的统计，货主和批发商也做一下」）。
    # ⚠️ 这一句要说清**两个方向**：模型最容易把"我该付的"和"我该收的"说成一件事，
    #    而它们一本是公司账、一本是他自己给下游记的账（谁都不写谁）。
    "shipper_ledger.ledger_summary": (
        "我的收支统计（这一段我该付给公司的：货款/已付/还欠；批发商另有一边："
        "我该向下游货主收的货款/已收/待收）"
    ),
    "expenses.list_expenses": "支出记录",
    "arrears.list_units": "挂账单位列表",
    "driver_bills.list_driver_bills": "司机账单",
    "driver_settlements.list_settlements": "司机结算记录",
    "freight_settlement.freight_settlement": "司机运费结算（按司机聚合，含订单明细）",
    "freight_templates.list_templates": "运费模板",
    "driver_billing_rules.list_rules": "司机计费规则（固定工资/每单金额/提成，可挂给司机）",
    "price_rules.list_price_rules": "批发商专属定价规则",
    "reports.turnover_report": "营业报表（营业额/成本/毛利，按日期范围）",
    "reports.product_report": "商品报表（销量、货损）",
    "reports.arrears_summary": "挂账/欠款汇总报表",
    "stats.get_driver_performance": "司机跑货统计（单量、准时率、待结运费）",
    "stats.get_shipper_performance": "货主跑货统计（下单量、金额、异常等）",
    "stats.get_shipper_activity": "货主下单活跃度统计",
    "stats.get_shipper_product_chart": "某货主的商品维度图表数据",
    "stats.get_product_drilldown": "某商品的明细下钻",
    "stats.get_exception_orders": "异常订单（货损、超时等）",
    "shipper.list_addresses": "地址与线路库",
    "shipper.list_contacts": "联系人库",
    "shipper.list_locations": "地点库",
    # 批发商自己那一本账（2026-09-20）：他给下游货主收的钱记在哪。
    # ⚠️ 说明里必须点破"这是**他自己**的账、与派单员那本无关" —— 否则模型会把
    #    「张三还欠我 300」答成"公司账上张三还欠 300"（两本账在同一张订单上）。
    "shipper_ledger.list_settlements": (
        "我（批发商）给下游货主收钱的核销记录 —— **自己那一本账**，"
        "与派单员记录的公司账是两笔钱；可按订单、按送达日窗口查，"
        "`include_deleted=true` 能看到已撤销的那些"
    ),
    # 地点分类名册（2026-09-19）：地址库左侧那一列。**按人分区** —— 读到的是"当前登录人
    # 自己那一份"，不是全店的（与商品分类不同，那条要写清，否则模型会以为改一处影响所有人）。
    "place_categories.list_categories": "地点分类名册（**当前登录人自己那份**：地点库左侧那一列的名字与顺序）",
    # 预订单分类名册（2026-09-22）：预订单页左侧那一列（"我这几张常用的单分成哪几类"）。
    # ⚠️ 与商品分类同一套做法（存名字、改名级联），但**各管各的** —— 名字常常相同
    # （周单/月单…），改一边不影响另一边。带 `template_count` = 每类下挂着几张预设单。
    "order_template_categories.list_categories": (
        "预订单分类名册（预订单页左侧那一列的分组与显示顺序，带每类下挂着几张预设单）"
    ),
    # 共享地点库（v3.41）：司机到场补录的坐标，全库共用 —— 与上面的"我的地点库"不同，
    # 这张表不按人分区，所以说明里要写明"别人标过的也在这"。
    "places.list_places": "共享地点库（司机/货主标过的导航坐标，不分人、大家共用；可按地点名或地址搜）",
    "notifications.list_notifications": "消息中心列表",
    "notifications.unread_count": "未读消息数",
    "operation_logs.list_operation_logs": "操作日志（谁在什么时候改了什么）",
}

#: 只有**批发商货主**（`users.is_member=1`）能读的表 —— 普通货主的 AI 连清单里都不该有它。
#:
#: 2026-09-20 用户第七轮：「AI 也会分成 2 个：一个是普通货主、一个是批发商货主的 AI……
#: 普通货主**手机做不到的事情，AI 也做不到**」。普通货主那一本账（`我的账本`）上
#: **根本没有"给下游货主核销"这一段**，所以核销记录这张表对他不是"读出来是空的"，
#: 而是**这个功能不存在**：给清单只会让模型照着它去解释一件他做不了的事。
#:
#: 键 = `模块.动作`；值 = 理由（写下来是为了它能被审计，不是为了好看）。
#: ⚠️ 后端那一侧这两张表的角色是 `shipper`（`require_roles(SHIPPER)`），
#:    普通货主调它拿到的是**空列表而不是 403** —— 所以这一层裁的是"界面有没有这段"，
#:    不是"会不会被拒"。判据必须落在代码里（这里），不能指望后端拦。
MEMBER_ONLY_READS: dict[str, str] = {
    "shipper_ledger.list_settlements": (
        "批发商货主自己那一本账（给下游货主核销的记录）：普通货主手机上「我的账本」"
        "根本没有这一段（他给自己下单，没有第二个债务人）"
    ),
}


def filter_hint(a: dict) -> str:
    """一行「这张表能按什么筛」——写进工具说明里，让模型不用猜参数。

    为什么值得生成：模型看不到每个接口的参数清单，只能凭 action 的中文名猜。
    实测踩过：它想按状态筛订单，却不知道 `orders.list_orders` 支持 `status`，
    于是只能如实回答"这个接口不支持按状态筛"——**目录里有、说明里没写，等于没有**。
    """
    parts = []
    for p in a["params"]:
        if p["required"] and p["name"] in ("limit",):
            continue
        if p["enum"]:
            parts.append(f'{p["name"]}({"|".join(p["enum"][:6])})')
        else:
            parts.append(p["name"])
    hint = "、".join(parts)
    return hint[:110]


def to_kotlin(cat: dict, module_cn: dict) -> str:
    lines = [
        "package com.tapmoay.sorders.ai",
        "",
        "// ⚠️ 本文件由 `_tools/ai/_gen_ai_read_catalog.py` **机器生成**，不要手改。",
        "// 重新生成：python _tools/ai/_gen_ai_read_catalog.py",
        "// 校验是否过期：python _tools/ai/_gen_ai_read_catalog.py --check",
        "",
        "/** AI 能读的一条只读列表/查询接口（来自后端 AST，见生成脚本）。 */",
        "data class ReadAction(",
        "    /** `模块.动作`，模型在工具参数里写的就是它。 */",
        "    val action: String,",
        "    /** 中文名（模块中文名 + 说明），模型据此选工具。 */",
        "    val cn: String,",
        "    val path: String,",
        "    /** 「这张表能按什么筛」——直接写进工具说明，模型不用猜参数名。 */",
        "    val filterHint: String,",
        "    /**",
        "     * 谁能调这个端点（后端角色键：dispatcher / driver / shipper）。",
        "     *",
        "     * 来自后端端点索引生成器对**源码**的解析（权限点 → 角色、体内 raise 403 的角色门槛），",
        "     * 不是手抄的：权限点改名、端点换守卫，这里会跟着变。**空集 = 谁也不给**（fail-closed）。",
        "     */",
        "    val roles: Set<String>,",
        "    /**",
        "     * 只有**批发商货主**（`users.is_member=1`）能读这张表。",
        "     *",
        "     * 判据来自生成脚本的 `MEMBER_ONLY_READS`（与写侧 `AiWriteAction.memberOnly` 对称）：",
        "     * 普通货主手机上**没有这一段界面** —— 给他的 AI 列出来，只会让它去解释",
        "     * 一件他做不了的事。**空集 roles 之外的第二个维度，别混。**",
        "     */",
        "    val memberOnly: Boolean,",
        "    /** 该端点声明的查询参数（白名单：只转这些，别的参数一律不转）。 */",
        "    val params: List<ReadParam>,",
        ")",
        "",
        "/** 一个可用的查询参数。 */",
        "data class ReadParam(",
        "    val name: String,",
        "    val type: String,",
        "    val required: Boolean,",
        "    val enum: List<String>,",
        "    /** 是不是内部编号类参数（AI 不许看到编号，但可以按**名字**让工具自己解析）。 */",
        "    val isId: Boolean,",
        ")",
        "",
        "object AiReadCatalog {",
        "",
        "    val ACTIONS: List<ReadAction> = listOf(",
    ]
    for a in cat["actions"]:
        cn = CN_DESC[f"{a['module']}.{a['action']}"]
        cn = cn.replace('"', "＂")
        hint = filter_hint(a).replace('"', "＂")
        roles = ", ".join(f'"{r}"' for r in a["roles"])
        roles_kt = f"setOf({roles})" if roles else "emptySet()"
        member_kt = "true" if a.get("member_only") else "false"
        lines.append(
            f'        ReadAction("{a["module"]}.{a["action"]}", "{cn}", "{a["path"]}", "{hint}", '
            f"{roles_kt}, {member_kt}, listOf("
        )
        for p in a["params"]:
            en = ", ".join(f'"{v}"' for v in p["enum"])
            en = f"listOf({en})" if en else "emptyList()"
            flag = "true" if p["is_id"] else "false"
            lines.append(
                f'            ReadParam("{p["name"]}", "{p["type"]}", '
                f'{"true" if p["required"] else "false"}, {en}, {flag}),'
            )
        lines.append("        )),")
    lines += [
        "    )",
        "",
        "    private val BY_ACTION: Map<String, ReadAction> = ACTIONS.associateBy { it.action }",
        "",
        "    fun find(action: String): ReadAction? = BY_ACTION[action.trim()]",
        "",
        "    /** 按模块分组（设置页按模块列开关用）。 */",
        "    fun modules(): List<String> = ACTIONS.map { it.action.substringBefore('.') }.distinct().sorted()",
        "",
        "    /** 模块的中文名（来自后端模块表，设置页显示用）。 */",
        "    val MODULE_CN: Map<String, String> = mapOf(",
    ]
    for m in sorted(module_cn):
        cn = module_cn[m].replace('"', "＂")
        lines.append(f'        "{m}" to "{cn}",')
    lines += [
        "    )",
        "",
        "    /** 某个模块下有哪些表（设置页那句说明用）。 */",
        "    fun actionsOf(module: String): List<ReadAction> = ACTIONS.filter { it.action.startsWith(module + \".\") }",
        "}",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    check = "--check" in sys.argv
    cat = extract()
    missing_desc = [
        f"{a['module']}.{a['action']}" for a in cat["actions"]
        if f"{a['module']}.{a['action']}" not in CN_DESC
    ]
    if missing_desc:
        print("❌ 下面这些动作还没有中文说明，必须逐条补进 CN_DESC（模型选工具靠它）：")
        for m in missing_desc:
            print("   - " + m)
        return 1
    if cat["counts"]["missing_handler"]:
        print("❌ toolmap 里标为 read 但在源码里找不到 handler：")
        for m in cat["counts"]["missing_handler"]:
            print("   - " + m)
        return 1

    payload = json.dumps(cat, ensure_ascii=False, indent=1) + "\n"
    module_cn = {a["module"]: a["module_cn"] for a in cat["actions"]}
    kt = to_kotlin(cat, module_cn)

    if check:
        ok = True
        for p, want in ((JSON_OUT, payload), (KT_OUT, kt)):
            if not p.exists():
                print(f"❌ 缺少产物：{p}")
                ok = False
            elif p.read_text(encoding="utf-8") != want:
                print(f"❌ 产物已过期：{p}（重跑生成脚本）")
                ok = False
        if ok:
            print(f"✅ 目录与源码一致（{cat['counts']['listed']} 个列表端点）")
            return 0
        return 1

    JSON_OUT.write_text(payload, encoding="utf-8")
    KT_OUT.write_text(kt, encoding="utf-8")
    listed = cat["counts"]["listed"]
    id_actions = [a["action"] for a in cat["actions"] if any(p["is_id"] for p in a["params"])]
    print(f"✅ 已生成：{JSON_OUT.relative_to(ROOT)}（{listed} 个端点）")
    print(f"✅ 已生成：{KT_OUT.relative_to(ROOT)}")
    print(f"   其中 {len(id_actions)} 个端点带编号类参数（要按名字解析，不能把编号透给模型）：")
    for a in id_actions:
        print("   - " + a)

    # ⚠️ 被跳过的参数要**打印出来**：漏掉一个筛选条件（如 status）不会报错，
    # 只会让模型在真机上如实回答"这个接口不支持按状态筛"——那次就是这么发现的。
    skipped = [(a["module"] + "." + a["action"], p) for a in cat["actions"] for p in a["skipped_params"]]
    if skipped:
        print(f"\n⚠️ 有 {len(skipped)} 个查询参数被跳过（类型不在白名单里），确认它们确实不该给 AI：")
        for act, p in skipped:
            print(f"   - {act}: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
