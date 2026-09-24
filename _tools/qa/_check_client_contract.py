"""红线：**客户端的状态门必须与后端逐值一致**（2026-09-19 审计 H1，R17）。

## 由来：这一整类缺陷以前没有任何检查看得到
`frontend/`（旧版 H5）在 `_tools/` 下**一次都没被任何检查提到过**（grep `frontend/` = 0 命中），
而它的订单状态模型停留在**四档**（少 `DISPATCHED`）。后果不是"少个页签"，是这一档订单
在 H5 上**根本没有入口**：

| 端 | 症状 |
|---|---|
| 司机 H5 | `fetchOrders('ACCEPTED')` —— 新派来的单（`DISPATCHED`）**不出现**：司机看不到、接不了，这一趟卡死 |
| 派单员 H5 | 页签只有「待派单/运输中」，两档都不含 `DISPATCHED` —— 派错司机后**看不到、也撤不回** |
| 货主 H5 | 「全部」里能看到，但 `ORDER_STATUS_LABEL[o.status]` 是 `undefined`（标签直接印 undefined） |
| App（新客户端） | 派单员撤回按钮写 `status == "ACCEPTED"`，后端 `recall_dispatch` 允许 `(DISPATCHED, ACCEPTED)` —— **派错司机的第一时间撤不回来** |

共同点：**真源在后端**（`order_flow.py` / `orders.py` / `order_products.py` 的状态门），
客户端各写一遍字面量。真源改了、字面量没跟着改，界面既不报错也不提示，
只是"少一个按钮 / 少一档列表 / 印出 undefined"。所以判据是**逐值对账**，
不是"某个词有没有出现过"（后者会被自己文档里的词骗过去，本项目栽过）。

## 判据（所有清单都是**算出来的**，不手写）
1. `ENUM` ← `backend/app/models/enums.py::OrderStatus`；
2. **后端状态门** ← 源码里的固定代码形状（形状对不上＝硬失败，绝不静默通过）：
   - `allowed = (…)`：`order_flow.cancel_pending` / `recall_dispatch`
   - `if order.status != OrderStatus.X`：`assign_driver` / `driver_ack_view` / `complete_delivery`
  （2026-09-24 起 `driver_ack_view` **只做委派** —— 那道比较搬去了 `order_flow.accept_order`，判据跟着认）
   - `return order.status in (…)`：`order_products._order_allows_line_edit`
     （2026-09-23 起**也认** `return order.status in <具名常量>`：那三个状态提成了
     `LINE_EDITABLE_STATUSES`，与原子占位的 `WHERE` 共用一份）
   - `if order.status in (…): raise`：`update_order` / `update_order_freight` → 允许 = ENUM 减去它
   - `if order.status == OrderStatus.X: raise`：`_payment_scoped_order` → 允许 = ENUM 减去它
3. 客户端声明的集合（H5 `constants/order.ts` / App `core/OrderStatusModel.kt`）与 2 **逐值相等**；
4. **每一档状态都要有入口**：按角色分组扫客户端里"能列出订单"的写法，
   必须覆盖**这个角色能做的动作**所要求的状态；有「全部（不过滤）」入口的组视为全覆盖；
5. 客户端不许出现**枚举以外**的订单状态字面量（旧四态、拼错的码）；
6. H5 调的端点必须真实存在（端点表由 `gen_endpoint_index.collect()` 现算，不读可能过期的 Markdown）。

用法：python _tools/qa/_check_client_contract.py
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 复用单源红线里的 `code_only`：后端那一半必须剥掉注释/文档字符串——
#: 本文件自己的文档里就写着 `allowed = (…)`、`!= OrderStatus.X` 这些形状，
#: 不剥的话"把真代码删掉、判据照样绿"。
from _check_single_source import code_only  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend/app"
ENUMS = BACKEND / "models/enums.py"
ORDER_FLOW = BACKEND / "services/order_flow.py"
#: orders 由多个模块组成（2026-09-24 阶段 4 纯搬迁），判据要看**并集**：见 _airepo.orders_api_source
ORDERS_API = BACKEND / "api/v1/orders.py"
#: 付款家族（_payment_scoped_order 等）2026-09-24 阶段 4 搬去了 orders_payment.py
ORDERS_PAY = BACKEND / "api/v1/orders_payment.py"
#: 派单与定价（update_order_freight / price_freight / assign / recall / split）2026-09-24 阶段 4 搬去了这里
ORDERS_ASSIGN = BACKEND / "api/v1/orders_assignment.py"
#: 送达与司机（driver_ack_view / complete / navigation / cancel）2026-09-24 阶段 4 搬去了这里
ORDERS_DELIVERY = BACKEND / "api/v1/orders_delivery.py"
#: 生命周期（update_order / create / patch exception / restore / delete）2026-09-24 阶段 4 搬去了这里
ORDERS_LIFECYCLE = BACKEND / "api/v1/orders_lifecycle.py"
ORDER_PRODUCTS = BACKEND / "api/v1/order_products.py"
ENDPOINT_GEN = ROOT / "backend/scripts/gen_endpoint_index.py"

#: ⚠️ 2026-09-25：frontend/（旧版 H5）已按用户拍板归档 —— 下面每一块涉及 H5 的判据都在 HAS_H5 里：
#: 目录不在就整块跳过（而不是读不到文件当场崩）；后端↔App 那一半照旧在跑。
#: 为什么不直接删：万一以后重新启用 H5，把目录放回去就能立刻恢复这些对账。
FE_SRC = ROOT / "frontend/src"
HAS_H5 = (ROOT / "frontend").is_dir()
FE_CONST = FE_SRC / "constants/order.ts"
FE_TYPES = FE_SRC / "types/order.ts"
FE_API_DIR = FE_SRC / "api"

KT = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
KT_MODEL = KT / "core/OrderStatusModel.kt"
KT_RECALL_SCREEN = KT / "ui/dispatcher/DispatcherOrdersScreen.kt"

#: 「能列出订单」的写法 → (正则, 种类)。种类：code=捕获组就是一个状态码；
#: group=整个匹配里含若干状态码；model=App 侧的状态集合引用（展开成它的取值）。
FE_PATTERNS: tuple[tuple[str, str], ...] = (
    # `fetchOrders` / `fetchOrdersPage` 都要认：后者是"顺便把截断位取回来"的版本（H2），
    # 只认前者的话，某天把所有调用点升级成 Page 版，这条覆盖判据就会**整段空转**。
    (r"fetchOrders(?:Page)?\(\s*'([A-Z_]+)'", "code"),
    (r"fetchOrdersByStatuses\(\s*\[[^\]]*\]", "group"),
    (r"status:\s*'([A-Z_]+)'", "code"),
    (r"\[\s*'[A-Z_]+'(?:\s*,\s*'[A-Z_]+')*\s*\]", "group"),
)
KT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r'OrderTab\(\s*"([A-Z_]+)"', "code"),
    (r'"[A-Z_]+"\s*to\s*"', "group"),
    (r'orders\(status\s*=\s*"([A-Z_]+)"', "code"),
    (r'listOf\((?:\s*"[A-Z_]+"\s*,?)+\)', "group"),
    (r"OrderStatusModel\.([A-Z_]+)", "model"),
)
#: 第⑤条只看**明确的状态比较**（宽泛的 listOf 会撞上 PIECE/SALARY 之类的别的枚举）。
FE_STATUS_COMPARE: tuple[str, ...] = (
    r"status\s*==\s*'([A-Z_]+)'",
    r"status\s*!==?\s*'([A-Z_]+)'",
    r"status\s*:\s*'([A-Z_]+)'",
    r"fetchOrders(?:Page)?\(\s*'([A-Z_]+)'",
)
KT_STATUS_COMPARE: tuple[str, ...] = (
    r'status\s*==\s*"([A-Z_]+)"',
    r'status\s*!=\s*"([A-Z_]+)"',
    r'status\s+in\s+setOf\(\s*"([A-Z_]+)"',
    r'OrderTab\(\s*"([A-Z_]+)"',
)

#: 非后端路由的路径（逐条写理由）。
PATH_ALLOW: dict[str, str] = {
    "/static/": "静态图片由 nginx 直接反代，不在 FastAPI 路由表里",
}

#: 允许**原样**绑定的金额字段（带理由）。判断依据是"这里是用户要输入/编辑的原始值"，
#: 格式化会把用户正在敲的内容改掉。
MONEY_RAW_ALLOW: tuple[str, ...] = (
    # 下单页的商品单价输入框（`v-model` 绑的是字符串表单值，见 OrderCreate.vue）
    "OrderCreate.vue → unit_price",
)

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


def strip_js(src: str) -> str:
    """去掉 TS/Kotlin 注释（保留换行，行号不乱）。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"(?m)^\s*//.*$", "", src)
    src = re.sub(r"//[^\n\"']*$", "", src, flags=re.M)
    return src


def enum_values() -> list[str]:
    src = ENUMS.read_text(encoding="utf-8")
    m = re.search(r"class OrderStatus\(str, enum\.Enum\):(.*?)(?=\nclass )", src, re.S)
    if m is None:
        return []
    return re.findall(r'^\s+([A-Z_]+)\s*=\s*"', m.group(1), re.M)


def body_of(path: Path, func: str) -> str:
    """函数体（到下一个顶层 `def`/装饰器/`class` 为止），注释已剥掉。"""
    src = code_only(path.read_text(encoding="utf-8"))
    m = re.search(rf"^def {re.escape(func)}\(", src, re.M)
    if m is None:
        raise KeyError(f"{path.name} 里找不到 def {func}(")
    rest = src[m.end():]
    nxt = re.search(r"^(def |@|class )", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def _members(text: str) -> set[str]:
    return set(re.findall(r"OrderStatus\.([A-Z_]+)", text))


def kt_body(src: str, signature: str) -> str:
    """Kotlin 函数的函数体（按花括号配平从 `signature` 往后取，注释已剥掉）。

    ⚠️ 为什么需要它（2026-09-23 第 6 轮，反向验证抓到）：`priceFor` 那条判据原来写成
    **"整个文件里出现过 `priceRulesShipper != subject`"** —— 而同一个形状在提交闸门、
    `alertSummary` 里还有两处，于是**把 `priceFor` 里那道守卫整个删掉，这条判据照样绿**
    （反向验证报 MISS：注入进去了、红线没红）。判据必须钉在**那个函数体**上，
    不然它会一直被别处的同形语句喂饱。
    """
    i = src.find(signature)
    if i < 0:
        return ""
    brace = src.find("{", i)
    if brace < 0:
        return ""
    depth = 0
    for j in range(brace, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[brace + 1 : j]
    return src[brace + 1 :]


def _tuple_after(body: str, head: str) -> set[str] | None:
    m = re.search(head + r"\s*\(([^)]*)\)", body)
    return None if m is None else _members(m.group(1))


def parse_backend_gates(enum: set[str]) -> dict[str, tuple[set[str], str]]:
    """{集合名: (允许的状态, 判据出处)}。形状对不上时抛 KeyError（硬失败）。"""
    gates: dict[str, tuple[set[str], str]] = {}

    for name, func in (("CANCELLABLE", "cancel_pending"), ("RECALLABLE", "recall_dispatch")):
        body = body_of(ORDER_FLOW, func)
        s = _tuple_after(body, r"allowed\s*=")
        if not s:
            raise KeyError(f"order_flow.{func} 里没解析出 `allowed = (…)`")
        gates[name] = (s, f"order_flow.{func}::allowed")

    for name, path, func in (
        ("ASSIGNABLE", ORDER_FLOW, "assign_driver"),
        ("ACKABLE", ORDERS_DELIVERY, "driver_ack_view"),
        ("COMPLETABLE", ORDER_FLOW, "complete_delivery"),
    ):
        body = body_of(path, func)
        where = f"{path.name}::{func}::status != X"
        m = re.search(r"order\.status\s*!=\s*OrderStatus\.([A-Z_]+)", body)
        if m is None:
            # ⚠️ 2026-09-24（整改阶段 5 §7）：状态跃迁搬进 OrderFlow 之后，端点上只剩一次调用 ——
            #    判据要跟着代码走（否则这里硬失败，而那道门其实还在，只是深了一层）。
            #    ⛔ 但**不许**因此放宽：必须真在 `order_flow` 里找到那道比较才算数，
            #    找不到同样硬失败（"形状对不上时静默通过 = 这条红线不存在"）。
            call = re.search(r"\b(\w+)\s*\(", body)
            delegated = ""
            for cand in re.findall(r"\b(accept_order|assign_driver|complete_delivery|cancel_pending)\s*\(", body):
                try:
                    delegated = body_of(ORDER_FLOW, cand)
                except KeyError:
                    continue
                where = f"order_flow.{cand}::status != X（{path.name} 的端点只做委派）"
                break
            m = re.search(r"order\.status\s*!=\s*OrderStatus\.([A-Z_]+)", delegated) if delegated else None
            if m is None:
                raise KeyError(
                    f"{path.name}::{func} 里没解析出 `order.status != OrderStatus.X`，"
                    "委派去的 order_flow 函数里也没有 —— 那道状态门不见了"
                )
        gates[name] = ({m.group(1)}, where)

    body = body_of(ORDER_PRODUCTS, "_order_allows_line_edit")
    m = re.search(r"return\s+order\.status\s+in\s*\(([^)]*)\)", body)
    if m is not None:
        members = _members(m.group(1))
        src = "order_products::_order_allows_line_edit::return order.status in (…)"
    else:
        # ⚠️ 2026-09-23 第 6 轮：那三个状态被提成了**具名常量** `LINE_EDITABLE_STATUSES`
        #    （Python 判据与上面那条原子占位的 `WHERE` 共用它 —— 两处各写一遍会出现
        #    "改一个忘一个"，而两次判据不一致时宽的那一处就是漏洞）。
        #    所以这里也要认新写法：从常量定义里取值，而不是硬失败或者跳过。
        m2 = re.search(r"return\s+order\.status\s+in\s+([A-Z_]+)", body)
        if m2 is None:
            raise KeyError(
                "order_products._order_allows_line_edit 里既没解析出 `return order.status in (…)`，"
                "也没解析出 `return order.status in <常量名>`"
            )
        const = m2.group(1)
        full = ORDER_PRODUCTS.read_text(encoding="utf-8", errors="replace")
        m3 = re.search(rf"^{const}\s*=\s*\(([^)]*)\)", full, re.M)
        if m3 is None:
            raise KeyError(f"order_products 里找不到常量 {const} 的定义（它被改名/搬走了？）")
        members = _members(m3.group(1))
        src = f"order_products::{const}"
    gates["LINE_EDITABLE"] = (members, src)

    # ⚠️ 逐条指明**文件**：`update_order_freight` 2026-09-24 阶段 4 搬去了 orders_assignment.py
    for name, func, src_file in (("EDITABLE", "update_order", ORDERS_LIFECYCLE),
                                 ("FREIGHT_EDITABLE", "update_order_freight", ORDERS_ASSIGN)):
        body = body_of(src_file, func)
        m = re.search(r"if\s+order\.status\s+in\s*\(([^)]*)\)\s*:\s*\n\s*raise", body)
        if m is None:
            raise KeyError(f"orders.{func} 里没解析出 `if order.status in (…): raise`")
        gates[name] = (enum - _members(m.group(1)), f"orders.{func}::status in (…) → raise")

    body = body_of(ORDERS_PAY, "_payment_scoped_order")
    # 两种写法都认：单值的 `== OrderStatus.X`（原来那种）与多值的 `in (A, B)`。
    # ⚠️ 2026-09-20 加退货时合并成了 `in (CANCELLED, RETURNED)` —— 只认单值时这里会硬失败
    #    （"形状变了，判据跟不上"），而如果当时改成"两种都不认就跳过"，这条红线就静默没了。
    m = re.search(r"if\s+order\.status\s+==\s*OrderStatus\.([A-Z_]+)\s*:\s*\n\s*raise", body)
    if m is not None:
        gates["NOT_CANCELLED"] = (enum - {m.group(1)}, "orders::_payment_scoped_order::status == X → raise")
    else:
        m = re.search(r"if\s+order\.status\s+in\s*\(([^)]*)\)\s*:\s*\n\s*raise", body)
        if m is None:
            raise KeyError(
                "orders._payment_scoped_order 里既没解析出 `if order.status == OrderStatus.X: raise`，"
                "也没解析出 `if order.status in (…): raise`"
            )
        gates["NOT_CANCELLED"] = (
            enum - _members(m.group(1)),
            "orders::_payment_scoped_order::status in (…) → raise",
        )

    return gates


def fe_const_set(name: str) -> set[str]:
    if HAS_H5:  # ⚠️ frontend/ 已归档：这一块跳过（见计划表 §4.2）
        src = strip_js(FE_CONST.read_text(encoding="utf-8"))
    m = re.search(rf"export const {name}[^=]*=\s*\[([^\]]*)\]", src)
    if m is None:
        raise KeyError(f"constants/order.ts 里找不到 {name}")
    out = set(re.findall(r"'([A-Z_]+)'", m.group(1)))
    if not out:
        raise KeyError(f"constants/order.ts::{name} 解析出来是空的")
    return out


def kt_set(name: str) -> set[str]:
    src = strip_js(KT_MODEL.read_text(encoding="utf-8"))
    m = re.search(
        rf"val {name}\s*:\s*(?:Set|List)<String>\s*=\s*(?:setOf|listOf)\(([^)]*)\)", src
    )
    if m is None:
        raise KeyError(f"OrderStatusModel.kt 里找不到 {name}")
    out = set(re.findall(r'"([A-Z_]+)"', m.group(1)))
    if not out:
        raise KeyError(f"OrderStatusModel::{name} 解析出来是空的")
    return out


def harvest(text: str, patterns: tuple[tuple[str, str], ...]) -> tuple[set[str], set[str]]:
    """返回（状态码集合, 引用到的模型集合名）。"""
    codes: set[str] = set()
    models: set[str] = set()
    for pat, kind in patterns:
        for m in re.finditer(pat, text):
            if kind == "model":
                models.add(m.group(1))
            elif kind == "code":
                codes.add(m.group(1))
            else:
                codes |= set(re.findall(r'["\']([A-Z_]+)["\']', m.group(0)))
    return codes, models


def scan_group(base: Path, patterns: tuple[tuple[str, str], ...], exts: tuple[str, ...]):
    """扫一个角色目录 →（状态码, 模型名, 是否有「全部」入口, 文件数）。"""
    codes: set[str] = set()
    models: set[str] = set()
    unfiltered = False
    n = 0
    for p in sorted(base.rglob("*")):
        if not p.is_file() or p.suffix not in exts:
            continue
        n += 1
        src = strip_js(p.read_text(encoding="utf-8", errors="replace"))
        c, mm = harvest(src, patterns)
        codes |= c
        models |= mm
        if re.search(r"OrderTab\(\s*null", src) or re.search(r"^\s*null to \"", src, re.M):
            unfiltered = True
        if re.search(r"\{\s*title:\s*'全部'\s*\}", src):
            unfiltered = True
    return codes, models, unfiltered, n


def backend_paths() -> set[str]:
    spec = importlib.util.spec_from_file_location("_gen_endpoint_index_cc", ENDPOINT_GEN)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"加载不了 {ENDPOINT_GEN}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    files = [str(p.relative_to(BACKEND)).replace("\\", "/") for p in sorted(BACKEND.rglob("*.py"))]
    rows, _ = mod.collect(str(BACKEND), files)
    prefix = mod._read_api_prefix(str(BACKEND)) or "/api/v1"
    return {mod.compose_url(r, prefix) for r in rows}


def norm_path(p: str) -> str:
    """路径归一：`{order_id}` / `${id}` 都折成 `{}`，末尾斜杠去掉。"""
    p = re.sub(r"\$\{[^}]*\}", "{}", p)
    p = re.sub(r"\{[^}]*\}", "{}", p)
    return p.rstrip("/")


#: H5 的 axios baseURL（`frontend/src/api/client.ts::normalizeApiBase` 保证含 `/api/v1`）
FE_API_BASE = "/api/v1"


def main() -> int:
    enum_list = enum_values()
    ok("从 enums.py 解析出 OrderStatus（>=4 档，防解析失效后空转）", len(enum_list) >= 4, f"实际 {enum_list}")
    if len(enum_list) < 4:
        return 1
    enum = set(enum_list)

    print("\n① 后端状态门（真源，从源码解析）")
    try:
        gates = parse_backend_gates(enum)
    except KeyError as e:
        print(f"❌ 后端状态门的代码形状变了，判据跟不上：{e}")
        print("   这条必须硬失败：形状对不上时静默通过 = 这条红线不存在。")
        return 1
    for name, (vals, how) in gates.items():
        print(f"  · {name:16s} = {sorted(vals)}   ← {how}")

    # H5 状态模型那一节随 frontend/ 归档整段删掉（计划表 4.2）；后端与 App 的对账在下一节。
    print("\n③ App（android/）的状态模型")
    try:
        kt_all = kt_set("ALL")
    except KeyError as e:
        kt_all = set()
        fails.append(str(e))
        print(f"  [FAIL] {e}")
    ok("App OrderStatusModel.ALL == 后端 OrderStatus", kt_all == enum,
       f"少 {sorted(enum - kt_all)}、多 {sorted(kt_all - enum)}" if kt_all != enum else "")

    for name in ("CANCELLABLE", "RECALLABLE", "ASSIGNABLE", "LINE_EDITABLE", "ACKABLE",
                 "COMPLETABLE", "EDITABLE", "FREIGHT_EDITABLE", "NOT_CANCELLED"):
        try:
            got = kt_set(name)
        except KeyError as e:
            fails.append(str(e))
            print(f"  [FAIL] {e}")
            continue
        ok(f"App OrderStatusModel.{name} == 后端 {name}", got == gates[name][0],
           f"App {sorted(got)} vs 后端 {sorted(gates[name][0])}")

    try:
        driver_open = kt_set("DRIVER_OPEN")
        need = gates["ACKABLE"][0] | gates["COMPLETABLE"][0]
        ok("App OrderStatusModel.DRIVER_OPEN ⊇ 接单档 ∪ 送达档（否则司机进不了这两帧）",
           driver_open >= need, f"缺 {sorted(need - driver_open)}")
    except KeyError as e:
        fails.append(str(e))
        print(f"  [FAIL] {e}")

    screen = strip_js(KT_RECALL_SCREEN.read_text(encoding="utf-8"))
    ok("App 派单员撤回按钮读 OrderStatusModel.RECALLABLE（不是硬写 ACCEPTED）",
       "OrderStatusModel.RECALLABLE" in screen and 'status == "ACCEPTED"' not in screen)

    print("\n④ 每一档状态都要有入口（按角色分组）")
    required: dict[str, set[str]] = {
        "driver": gates["ACKABLE"][0] | gates["COMPLETABLE"][0] | {"DELIVERED"},
        "dispatcher": gates["ASSIGNABLE"][0] | gates["RECALLABLE"][0] | gates["CANCELLABLE"][0] | {"DELIVERED"},
        "shipper": gates["CANCELLABLE"][0] | {"DELIVERED"},
    }
    for role, need in required.items():
        # ⚠️ 2026-09-25：H5 那一半随 frontend/ 归档删掉（计划表 §4.2）——
        #    这一段原来先扫 H5 的 views/components，再扫 App 的 ui/<role>；现在只剩 App 那一半。
        kbase = KT / "ui" / role

        kbase = KT / "ui" / role
        k_codes, k_models, k_unf, kn = scan_group(kbase, KT_PATTERNS, (".kt",))
        bad_models: list[str] = []
        for name in k_models:
            try:
                k_codes |= kt_set(name)
            except KeyError:
                bad_models.append(name)
        ok(f"App 扫到 {role} 目录（>=1 个文件）", kn >= 1, f"实际 {kn}")
        ok(f"App {role} 引用的状态集合都存在", not bad_models, "、".join(bad_models))
        kcovered = k_codes | (enum if k_unf else set())
        ok(f"App {role} 有入口到达 {sorted(need)}", kcovered >= need,
           f"只覆盖 {sorted(k_codes)}，缺 {sorted(need - kcovered)}")

    print("\n⑤ 客户端不许出现枚举以外的订单状态字面量")
    bad: list[str] = []
    # ⚠️ 2026-09-25：H5 那一项已摘掉（frontend/ 归档，计划表 §4.2）—— 只剩 App；
    #    ⛔ 注意末尾那个逗号：只有一项时没有它就不是"元组的元组"，会退化成拿 KT 当 base 解包。
    for base, pats, exts in (
        (KT, KT_STATUS_COMPARE, (".kt",)),
    ):
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix not in exts:
                continue
            src = strip_js(p.read_text(encoding="utf-8", errors="replace"))
            for pat in pats:
                for v in re.findall(pat, src):
                    if v not in enum:
                        bad.append(f"{p.relative_to(ROOT)} → {v}")
    ok("客户端的状态字面量都在后端枚举里（旧四态/拼错的码会在这里红）", not bad,
       "；".join(sorted(set(bad))[:8]))

    # H5 调的端点那一节随 frontend/ 归档整段删掉（计划表 4.2）。
    print("\n⑦ 「退出登录」必须真的让服务端作废令牌")
    # H5 那两条（api/auth.ts 有 logout / store 真的调它）随 frontend/ 归档删掉。

    print("\n⑧ 界面不许把「后端原始值」直接印给用户")
    # (a) 状态码：`{{ ex.status }}` / `:value="o.status"` 这种直接把枚举码摆到用户眼前
    raw_status: list[str] = []
    if HAS_H5:  # ⚠️ frontend/ 已归档：这一块跳过（见计划表 §4.2）
        for p in (sorted(FE_SRC.rglob("*.vue")) if HAS_H5 else []):   # H5 已归档则零次
            src = strip_js(p.read_text(encoding="utf-8", errors="replace"))
            for m in re.finditer(
                r"\{\{\s*([\w.]*\.status)\s*\}\}|:value=\"([\w.]*\.status)\"", src
            ):
                raw_status.append(f"{p.relative_to(ROOT)} → {m.group(1) or m.group(2)}")
    ok("界面不直接把订单状态码印出来（要过 ORDER_STATUS_LABEL / statusLabel 之类的映射）",
       not raw_status, "；".join(raw_status[:6]))

    # (b) 金额：**字段清单从后端 schema 算**（`Decimal` 类型的字段），
    #     界面上绑定它们时一律要过 `formatMoney2` —— 后端序列化的是字符串，
    #     实测 `default_unit_price = '12.5000'`、`avg_order_value = '149.9885265700483091787439614'`，
    #     不格式化就会印出「¥12.5000」「149.9885265700483091787439614」。
    money_fields: set[str] = set()
    for p in sorted((BACKEND / "schemas").glob("*.py")):
        src = p.read_text(encoding="utf-8")
        money_fields |= {
            m.group(1)
            for m in re.finditer(
                r"^\s{4}([a-z_][a-z0-9_]*)\s*:\s*(?:Optional\[)?Decimal", src, re.M
            )
        }
    ok("从后端 schema 解析出金额字段（>=10 个，防解析失效后空转）",
       len(money_fields) >= 10, f"实际 {len(money_fields)}")
    money_pat = re.compile(r"\b(" + "|".join(sorted(money_fields)) + r")\b")
    raw_money: list[str] = []
    if HAS_H5:  # ⚠️ frontend/ 已归档：这一块跳过（见计划表 §4.2）
        for p in (sorted(FE_SRC.rglob("*.vue")) if HAS_H5 else []):   # H5 已归档则零次
            src = strip_js(p.read_text(encoding="utf-8", errors="replace"))
            for m in re.finditer(
                r"\{\{\s*([^}]+?)\s*\}\}|:value=\"([^\"]*)\"|:title=\"([^\"]*)\""
                r"|:label=\"([^\"]*)\"|:text=\"([^\"]*)\"",
                src,
            ):
                expr = next((g for g in m.groups() if g), "")
                if "formatMoney" in expr or "money(" in expr:
                    continue
                hit = money_pat.search(expr)
                if hit:
                    raw_money.append(f"{p.relative_to(ROOT)} → {hit.group(1)}")
    allowed = [x for x in raw_money if any(a in x for a in MONEY_RAW_ALLOW)]
    bad_money = [x for x in raw_money if x not in allowed]
    ok("界面上的金额字段都过了 formatMoney2（否则印出 `12.5000` 这种服务端精度）",
       not bad_money, "；".join(bad_money[:6]))

    print("\n⑨ 下单页必须按「批发商专属价」报价（两端同口径）")
    # 后端 `GET /price-rules` 的存在理由写在 `price_rules.py` 的注释里：
    # 「批发商（货主）只读自己的专属价，**用于下单时展示实际价格**」。
    # 下单页不去读它 → 批发商按**零售价**成交（谁也不会发现，直到对账）。
    # 清单自己算：谁调 `createOrder(` 谁就是下单页。
    # ⚠️ 2026-09-25：原来这里先扫 H5 的下单页（谁调 createOrder( 谁就是），
    #    再扫 App 的 OrderCreateViewModel —— H5 那一半随 frontend/ 归档删掉（计划表 §4.2），
    #    下面只剩 App 那一半（后端 /price-rules 的存在理由与它一并对账）。
    app_create = KT / "ui/shipper/OrderCreateViewModel.kt"
    if app_create.exists():
        kt = strip_js(app_create.read_text(encoding="utf-8"))
        ok("App 下单 ViewModel 按专属价报价", "specialUnitPrice" in kt and "priceFor" in kt)
        # ⚠️ 判据钉在 **`priceFor` 的函数体**里（2026-09-23 第 6 轮修）：
        #    原来写成"整个文件里出现过 `priceRulesShipper != subject`" —— 同一个形状在
        #    提交闸门与 `alertSummary` 里还有两处，于是**把 `priceFor` 里那道守卫整段删掉
        #    这条判据照样绿**（反向验证报 MISS 抓到的）。
        pf = kt_body(kt, "fun priceFor(")
        ok("App 下单 ViewModel 有「这份价属于谁」的守卫（防报价串号）",
           bool(pf) and re.search(r"priceRulesShipper\s*!=\s*subject", pf) is not None,
           "判据看的是 `fun priceFor(` 的函数体 —— 别处出现同形语句不算")
        ok("守卫生效时**回退默认价**（不是继续用上一份专属价）",
           bool(pf) and re.search(r"priceRulesShipper\s*!=\s*subject\)\s*return\s+\w+\.defaultUnitPrice", pf)
           is not None,
           f"priceFor 里没看到「守卫 → 回退默认价」这一对（实际：{pf.strip()[:80]!r}）")
    else:
        fails.append("找不到 App 下单 ViewModel（改名了？判据要跟着改，不许静默跳过）")
        print("  [FAIL] 找不到 android/.../ui/shipper/OrderCreateViewModel.kt")

    print("\n⑩ 界面里的「关联/效果」承诺必须与后端一致")
    # 手工记账的「关联订单」：后端**刻意**把 `order_id` 置空
    # （`ledger.py`：挂了会被当日订单账重复计入），只把它写进审计日志当线索。
    # 所以界面上选了单号时，必须如实说明"这笔账不会挂到那张单上" ——
    # 否则用户会以为钱挂到了那单上（界面上确实显示了单号）。
    if HAS_H5:  # ⚠️ frontend/ 已归档：这一块跳过（见计划表 §4.2）
        # H5 已归档（计划表 4.2）：目录不在时下面那条 if 直接不成立。
        ledger_vue = FE_SRC / "views/dispatcher/DispatcherLedger.vue"
    if HAS_H5 and ledger_vue.exists():
        src = strip_js(ledger_vue.read_text(encoding="utf-8"))
        picks_order = "showOrderPick = true" in src
        ok("账本手工记账确实提供「关联订单」选择（判据的前提）", picks_order)
        # ⚠️ 只查"文件里出现过这句话"是不够的：把 `v-if` 改成 false 之后，
        #    那句话还在文件里、界面却永远不显示（反向验证抓到过一次）。
        #    判据要钉住**接线**：这句话由"选中了订单"来门控。
        ok("选了订单时界面如实说明「不会挂到订单上」",
           "manual-order-hint" in src
           and "不会挂到订单上" in src
           and re.search(r'v-if="manualForm\.order_id\s*!=\s*null"', src) is not None)
    else:
        if HAS_H5:
            fails.append("找不到 DispatcherLedger.vue（改名了？判据要跟着改，不许静默跳过）")
        if HAS_H5:
            print("  [FAIL] 找不到 frontend/src/views/dispatcher/DispatcherLedger.vue（H5 已归档则不该出现）")

    print("\n" + "=" * 60)
    if fails:
        print(f"❌ {len(fails)} 项不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {passes} 项通过：客户端状态门与后端逐值一致，每一档状态都有入口。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
