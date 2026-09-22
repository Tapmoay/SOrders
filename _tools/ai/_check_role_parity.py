"""角色能力对账：**后端允不允许 / 手机上有没有 / AI 给没给**，三方逐条比。

### 用户定的口径（2026-09-20 第七轮，原话）
> 「AI 也会分成 2 个：一个是普通货主、一个是批发商货主的 AI。相应的权限和能力跟对应角色的
>   所有功能和权限进行统一 —— 这个角色能做什么功能、做什么事情，AI 要赋予相应的能力……
>   但是他**不能越权**，批发商没有的功能 AI 也做不到；包括普通货主，**他做不到的事情、
>   也就是他手机做不到的事情，AI 也做不到**。」

所以这里比的是**三方**，两条断言各管一头：

```
        BACKEND(role)          手机上真能做（后端授权是硬边界）
            ∩
        APP                    界面上真有这个功能（ui/** 里有人在调它）
            ⊆
        AI(role, member) + EXCLUDED（每条要写下来理由）      ← 断言②：不许缺能力
            ⊆
        BACKEND(role)                                        ← 断言①：不许越权
```

### 为什么清单必须自己算
本仓库栽过 5 次「清单是手写的」：新加的端点/动作不在那张签入的表里 → 检查**假绿**。
所以这里三份清单全部现算：

- **BACKEND**：`_gen_ai_read_catalog.endpoint_roles()` —— 它自己是从
  `backend/scripts/gen_endpoint_index.py::collect()` 的鉴权标注（`角色:` / `权限:` /
  `体内仅允许:`）+ `ROLE_PERMISSIONS` 推出来的，而 `_tools/fuzz/_fuzz_authz.py`
  已经拿真后端逐条对过账（声明与实测不一致会红）。**不读任何签入的 JSON。**
- **APP**：`Apis.kt`（`@POST("orders/{id}/exception")` ↔ 函数名）→ `AppRepository.kt`
  （方法 ↔ api 函数）→ 在 `ui/**` 里搜谁在调那个 repo 方法。三步都是现读源码。
- **AI(role)**：`AiWrite.kt` 的白名单 + `AiWrite*.kt` 的动作定义（`id = AiWrites.X` 那一块里
  调的 `ds.<函数>`）→ `AiWriteService.kt` 等实现体里的 `repo.<方法>` → 回到端点。
  另加一层：实现体里调的**私有 helper** 也要跟着走一跳（否则 `moveCategoryTo` 这类
  间接调用会把端点漏掉，表现成"AI 没这个能力"的假缺口）。

### 两个方向都会红
- **越权**（AI 有、BACKEND 没有）：`EXCLUDED` 挡不住它 —— 这是安全边界，无条件红。
- **缺能力**（BACKEND∩APP 有、AI 没有）：必须进 [EXCLUDED]（键 = `角色 端点`）并写清理由；
  没写理由就红——"还没做"和"决定不做"不许混在一起（这条规矩来自 `_write_coverage.py`）。

用法：
    python _tools/ai/_check_role_parity.py           # 打一张三方对账表
    python _tools/ai/_check_role_parity.py --check    # 只校验（不自洽就非零退出，给红线用）
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
AI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
APIS = AND / "data/remote/api/Apis.kt"
REPO = AND / "data/repo/AppRepository.kt"
UI = AND / "ui"

#: AI 侧的实现文件（`ds.<函数>` 的真身在这里，里面调 `repo.<方法>`）。
IMPL_FILES = (
    "AiWriteService.kt",
    "AiWriteCrudHandlers.kt",
    "AiWriteOrderHandlers.kt",
    "AiWriteOrderLineHandlers.kt",
    "AiWriteLedgerHandlers.kt",
    "AiWriteNotificationHandlers.kt",
    "AiWriteShipperLedgerHandlers.kt",
    "AiWriteSettlementHandlers.kt",
)

#: 角色的中文名（报错时给人看）。
ROLE_CN = {"dispatcher": "派单员", "shipper": "货主", "driver": "司机"}

#: ⛔ **批发商货主专属**的动作（`users.is_member=1`）——普通货主的 AI 连清单都不该看见它。
#:
#: 判据来自后端：`shipper_ledger.py` 的四个端点都是 `require_roles(SHIPPER)` 之后再在体内
#: `_require_member`（非批发商 403）。用户 2026-09-20：「AI 也会分成 2 个：一个是普通货主、
#: 一个是批发商货主的 AI」——所以这一维必须落在**能力清单**上，不能只在发卡时拦。
#: 键 = 动作常量名（与 `AiWrite.kt` 里那个 `memberOnly = true` 标记对账，两边必须一致）。
MEMBER_ONLY_ACTIONS = {
    "MY_LEDGER_SETTLE",
    "MY_LEDGER_REVOKE",
    "MY_LEDGER_RESTORE",
}

#: 批发商专属的**读**表（`ai_read_catalog.json` 里 module_cn = 我的账本）。
MEMBER_ONLY_READS = {"shipper_ledger.list_settlements"}

#: ⛔ 后端**角色门写成 `shipper`，但体内只放批发商**的端点。
#:
#: 端点索引解析器只能看见签名上的 `require_roles(SHIPPER)`，看不见函数体里那句
#: `_require_member`（普通货主 403「你给自己下单，没有第二个债务人」）。
#: 所以这一维必须在这里补上，否则两个方向都会报错：普通货主那边报"缺能力"
#: （后端明明允许他），批发商那边报"越权"（他当然该有）。
#: 键 = 端点键；值 = 理由。
MEMBER_ONLY_ENDPOINTS: dict[str, str] = {
    "GET shipper-ledger/settlements": "货主自记账：体内 _require_member（只有批发商有这本账）",
    "POST shipper-ledger/settlements": "同上",
    "DELETE shipper-ledger/settlements/{}": "同上",
    "POST shipper-ledger/settlements/{}/restore": "同上",
}

#: 「这一对删/恢复**故意**只给一边」——每条必须写清理由（由 ④ 那条判据消费）。
#:
#: 键 = `"<角色 tag> <删除动作 id>"`；值 = 理由。
UNDO_PAIR_EXCEPTIONS: dict[str, str] = {
    # 两个货主 tag 都要写：这条按 `tag`（含 `+member`）匹配，少写一个就在批发商那边报红。
    "shipper orders.soft_delete": (
        "恢复只能由**派单员**做：后端 `POST /orders/{id}/restore` 是「体内仅允许：派单员」，"
        "货主端连回收站都没有（与订单详情页那个「删除订单」按钮给出的说法一致）。"
        "所以卡面上如实写「要请派单员恢复」——这一条不是缺能力，是**恢复不在他手上**。"
    ),
    "shipper+member orders.soft_delete": "同上（批发商货主也一样：回收站只有派单员有）",
}
#:
#: 为什么需要它：这条检查的属性分析是**静态的**（"这个动作的处理器里出现过这次调用"），
#: 而有些处理器按角色分叉（同一张卡，货主走 A 分支、派单员走 B 分支）。
#: 静态看不出来 → 会报一条**假越权**（"货主能查全量账号名册"），而假越权比不报更糟：
#: 一旦开始给人"这条不用管"的印象，真越权也会被一起忽略。
#: ⚠️ 加条目必须带**证据**（实测过、或代码里那句判断），不许写"大概不会走到"。
#: 键 = `"<角色> <动作 id> <端点键>"`。
ROLE_BRANCHED_CALLS: dict[str, str] = {
    "shipper orders.create GET users": (
        "`CreateOrderHandler` 对货主走「给自己下单」分支（`selfOrder`），**不查货主名册** —— "
        "后端 `create_order` 对货主是 `target_shipper_id = current.id`、连 shipper_id 都不许传，"
        "而 `GET /users` 对货主是 403（真后端实测过）。"
    ),
}
#:
#: 键 = `"<角色> <METHOD> <归一化路径>"`（⚠️ 路径**不带**前导斜杠，端点键就是这么算的，
#: 见 [endpoint_key]；写错形状的表现是"理由明明写了、却还是报缺口"——已经踩过一次）。
#: 角色写 `shipper` 对所有货主生效；写 `shipper+member` 只对批发商货主生效。
#: ⚠️ 这张表**只许加，不许为了凑覆盖率删**：删掉一条，对应的缺口会立刻在 --check 里冒出来。
EXCLUDED: dict[str, str] = {
    # 上传类：模型给不出文件（与 `_write_coverage.py` 的 EXCLUDED 同一条理由，这里是按角色再确认一遍）。
    "dispatcher POST shipper/locations/image": "上传类：要一个文件，模型给不出（v3.7 永久排除）",
    "shipper POST shipper/locations/image": "上传类：要一个文件，模型给不出（v3.7 永久排除）",
    "dispatcher POST orders/{}/address-image": "上传类：要一个文件，模型给不出（v3.7 永久排除）",
    "shipper POST orders/{}/address-image": "上传类：要一个文件，模型给不出（v3.7 永久排除）",
    "dispatcher POST files/parse-sheet": (
        "AI 附件的入口：文件由用户在系统选择器里选，App 上传解析后把表格正文交给模型"
        "（模型侧没有「申请上传」这个动作，见 _write_coverage.AI_DIRECT_USE）"
    ),
    "shipper POST files/parse-sheet": (
        "同上（货主也能挂 Excel 让 AI 读；入口在用户手上，不在模型手上）"
    ),
    # 登出：会话动作，模型替用户退出登录只会让他莫名其妙被踢回登录页。
    "dispatcher POST auth/logout": "会话动作：AI 不该碰凭据与会话（v3.7 永久排除）",
    "shipper POST auth/logout": "会话动作：AI 不该碰凭据与会话（v3.7 永久排除）",
    # 共享地点库的"埋点"：App 在用户点选共享地点时自动调的计数，不是一件可以申请的事。
    "dispatcher POST places/{}/use": "埋点类：用户点选共享地点时 App 自动调的计数（见 _write_coverage.EXCLUDED）",
    "shipper POST places/{}/use": "埋点类：同上",
    # 新建共享地点：要经纬度（模型给不出，编一个会把司机带错）。
    "dispatcher POST places": "坐标类：新建一个点必然要坐标，模型给不出（v3.41 永久排除）",
    "shipper POST places": "坐标类：同上",
    # 开销分类名册：只有派单员有这一页与这些端点（`expense-categories` 全是 dispatcher）。
    # 个人资料：`PATCH /users/{id}` 的入口在「我的」页（改名/改电话/改密码），
    # 属于**账号与凭据**那一类 —— AI 不碰（与登录/登出同一条理由，见 `_write_coverage.EXCLUDED`）。
    "shipper PATCH users/{}": "账号与凭据：改自己的资料/密码在「我的」页，AI 不碰凭据这一类（v3.7 永久排除）",
    "dispatcher PATCH users/{}": "账号与凭据：同上（派单员那条路由 `users.update` 覆盖，这里指的是只改自己那一半）",
}


def norm(path: str) -> str:
    """路径参数名两侧写法不同（后端 `{order_id}` / Retrofit `{orderId}`），统一成 `{}` 再比。"""
    return re.sub(r"\{[^}]*\}", "{}", path.strip("/"))


def endpoint_key(method: str, path: str) -> str:
    """`("POST", "/api/v1/orders/{order_id}/cancel")` → `"POST orders/{}/cancel"`。"""
    p = re.sub(r"^/api/v1", "", path)
    return f"{method.upper()} {norm(p)}"


# --------------------------------------------------------------------------- BACKEND

def backend_roles() -> dict[str, set[str]]:
    """端点 → 允许调它的角色（**源码现算**，见模块头）。"""
    gen = Path(__file__).resolve().parent / "_gen_ai_read_catalog.py"
    spec = importlib.util.spec_from_file_location("_gen_ai_read_catalog", gen)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    out: dict[str, set[str]] = {}
    for (method, url), info in mod.endpoint_roles().items():
        out[endpoint_key(method, url)] = set(info["roles"])
    return out


# --------------------------------------------------------------------------- APP

# `@POST("orders/{id}/exception")` + 紧随其后的 `fun markException(`
_API_FN = re.compile(r'@(GET|POST|PATCH|DELETE|PUT)\("([^"]*)"\)[\s\S]{0,600}?fun\s+(\w+)\s*\(')
_IFACE = re.compile(r"\binterface\s+(\w+)\s*\{")
# AppRepository 里对 api 的调用：`api.orderApi.markException(...)` / `api.markException(...)`
_REPO_CALL = re.compile(r"\bapi(?:\.(\w+))?\.(\w+)\s*\(")


def strip_kt_comments(src: str) -> str:
    """剥注释 —— 判据不剥注释的话，**KDoc 里写一句示例就能把端点算成"App 在用"**。

    这条自检是从 `_write_coverage.py` 学来的（它写过同一个坑：注释里的 `repo.markRead(id)`
    把端点算成已覆盖）。那边有 `self_test_comment_blindness()`；这里同样要能用注入验证。
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)//.*$", "", src)


def balanced(src: str, open_idx: int, op: str = "(", cl: str = ")") -> str:
    """取 `src[open_idx]` 那个 `op` 到**配对**的 `cl`（含两端）。找不到就取到末尾。

    为什么要它（第一版用"切到下一个 `id =` / 下一个 `\n        ),`"那种近似，
    结果是**把整份文件切进来**）：`balance ≠ 排版`。多行调用、异常缩进、
    同一个文件里连着好几个 `restoreAction(...)` —— 近似切片一律会多带邻居，
    而多带的后果是**这条检查报出一堆假越权**（"货主能恢复运费模板"），
    比不报还糟：没人会去信一个天天喊狼来了的检查。
    """
    depth = 0
    i = open_idx
    while i < len(src):
        c = src[i]
        if c == op:
            depth += 1
        elif c == cl:
            depth -= 1
            if depth == 0:
                return src[open_idx: i + 1]
        i += 1
    return src[open_idx:]


def call_at(src: str, pos: int) -> str:
    """把**包住 `src[pos]` 的那一次调用**整段取出来（含紧跟其后的 `{ … }` lambda）。

    用于声明式动作：`crud( … id = X, … ) { ds, p -> ds.createAddress(p) }`
    —— 光取"括号里那一段"会漏掉 lambda，而 `ds.` 调用恰恰写在 lambda 里。
    """
    i = pos
    depth = 0
    open_idx = -1
    while i >= 0:
        c = src[i]
        if c == ")":
            depth += 1
        elif c == "(":
            if depth == 0:
                open_idx = i
                break
            depth -= 1
        i -= 1
    if open_idx < 0:
        return src[pos: pos + 600]
    seg = balanced(src, open_idx)
    tail_start = open_idx + len(seg)
    rest = src[tail_start:]
    m = re.match(r"\s*\{", rest)
    if m:
        brace = tail_start + m.end() - 1
        seg += rest[: m.end() - 1] + balanced(src, brace, "{", "}")
    return seg


def fn_body(src: str, sig_end: int) -> str:
    """函数签名结束位置之后，取**函数体**：`{ … }` 配对；表达式体（`= …`）取到下一行同缩进的声明。"""
    rest = src[sig_end:]
    m = re.search(r"[={]", rest)
    if m and m.group(0) == "{":
        return balanced(rest, m.start(), "{", "}")
    nxt = re.search(r"\n    (?:override\s+)?(?:suspend\s+)?fun\s+\w+\s*\(", rest)
    return rest[: nxt.start()] if nxt else rest


def api_endpoints() -> dict[tuple[str, str], str]:
    """(**接口名**, Api 函数名) → 端点键。

    ⚠️ 必须带上接口名（第一版只用函数名，**撞名即错**）：`createSettlement` 在
    `accountingApi`（司机结算）与 `shipperLedgerApi`（货主自记账）里**各有一个**，
    只用函数名做键的话后读到的会盖掉前一个 —— 于是「司机结算单」那个动作被算成
    打到了 `/shipper-ledger/settlements`，检查当场报一条**假越权**
    （"派单员能动货主自己的账"）。
    """
    src = APIS.read_text(encoding="utf-8")
    out: dict[tuple[str, str], str] = {}
    ifaces = [(m.start(), m.group(1)) for m in _IFACE.finditer(src)]
    for m in _API_FN.finditer(src):
        iface = ""
        for pos, name in ifaces:
            if pos < m.start():
                iface = name
            else:
                break
        out[(iface, m.group(3))] = f"{m.group(1)} {norm(m.group(2))}"
    return out


def repo_methods() -> dict[str, str]:
    """AppRepository 的方法名 → 端点键（取方法体里第一个 api 调用）。

    ⚠️ 子 api 的属性名与接口名**大小写不同**（`api.shipperLedgerApi` ↔ `interface
    ShipperLedgerApi`），所以查表要按小写归一 —— 不归一的后果是**一条都匹配不上**
    （实测：整个检查变成"0 个端点"，反空转那条会红，但如果不红就成了一条永远绿的空检查）。
    """
    src = REPO.read_text(encoding="utf-8")
    fn2ep = api_endpoints()
    by_lower: dict[tuple[str, str], str] = {k: v for k, v in fn2ep.items()}
    by_lower |= {(i.lower(), f): v for (i, f), v in fn2ep.items()}
    by_fn: dict[str, str] = {}
    for (_i, f), v in fn2ep.items():
        by_fn.setdefault(f, v)

    out: dict[str, str] = {}
    for m in re.finditer(r"(?:suspend\s+)?fun\s+(\w+)\s*\(", src):
        body = fn_body(src, m.end())
        for sub, fn in _REPO_CALL.findall(body):
            ep = by_lower.get((sub, fn)) or by_lower.get((sub.lower(), fn)) or by_fn.get(fn)
            if ep:
                out[m.group(1)] = ep
                break
    return out


def app_endpoints() -> dict[str, set[str]]:
    """端点 → 有哪些**界面文件**在调它（`ui/**`）。空集 = 手机上根本没有这个功能的入口。"""
    repo2ep = repo_methods()
    out: dict[str, set[str]] = {}
    for f in sorted(UI.rglob("*.kt")):
        src = strip_kt_comments(f.read_text(encoding="utf-8"))
        for name in set(re.findall(r"\brepo\.(\w+)\s*\(", src)):
            ep = repo2ep.get(name)
            if ep:
                out.setdefault(ep, set()).add(f.name)
    return out


# --------------------------------------------------------------------------- AI

_ACTION_BLOCK = re.compile(r"id\s*=\s*(?:AiWrites\.)?([A-Z][A-Z0-9_]*)\s*,")
#: 撤回工厂调用点里的动作 id：`restoreAction(cn = …, id = AiWrites.MY_LEDGER_RESTORE, …)`
_RESTORE_ID = re.compile(r"id\s*=\s*(?:AiWrites\.)?([A-Z][A-Z0-9_]*)\s*,")
# 手写处理器：`class CancelOrderHandler(...) { override val actionId = AiWrites.ORDERS_CANCEL … }`
_HANDLER = re.compile(r"override\s+val\s+actionId\s*=\s*AiWrites\.([A-Z][A-Z0-9_]*)")
_NEXT_TOP_LEVEL = re.compile(r"\n(?:internal\s+|private\s+)?(?:class|object|fun|val)\s")
_DS_CALL = re.compile(r"\bds\.(\w+)\s*\(")

#: 反空转计数器：参数式处理器认出了几条 `ds.` 关联（[param_handlers] 写，main 里断言）。
PARAM_HANDLER_PAIRS: list[int] = [0]


def action_ds_fns() -> dict[str, set[str]]:
    """动作常量名 → 它最终调的 `ds.<函数>` 名。

    **两条路都要走**（少一条就会把"有动作"误报成"缺口"）：
    1. **声明式**（`crud(id = …, …) { ds, p -> ds.createAddress(p) }` 与 `restoreAction(…)`）——
       调用点就在动作定义块里；
    2. **手写处理器**（`class CancelOrderHandler { override val actionId = ORDERS_CANCEL;
       … ds.cancelOrder(…) }`）—— `AiWriteAction(...)` 里只有 `params` 和文案，
       真正的调用在另一个文件的类里，靠 `actionId` 关联。
    """
    out: dict[str, set[str]] = {}

    def add(const: str, text: str) -> None:
        fns = _DS_CALL.findall(text)
        if fns:
            out.setdefault(const, set()).update(fns)

    for f in sorted(AI.glob("AiWrite*.kt")):
        if f.name == "AiWriteRestore.kt":  # 工厂**定义**，不是动作
            continue
        src = strip_kt_comments(f.read_text(encoding="utf-8"))
        # ① 声明式：`crud( … id = X … ) { ds, p -> ds.createAddress(p) }` —— 取**包住它的那次调用**
        for m in _ACTION_BLOCK.finditer(src):
            add(m.group(1), call_at(src, m.start()))
        # ①b 撤回专用（工厂调用点）：`restoreAction("地址", AiWrites.ADDRESS_RESTORE, …) { ds, id -> … }`
        #     ⚠️ 调用点是**位置参数**（第一版只认 `id = X` 这种具名写法 → 7 条恢复动作全部
        #        报"挂不上端点"，而那正是货主撤回路径缺的那一批）。
        for m in re.finditer(r"\brestoreAction\s*\(", src):
            open_paren = src.index("(", m.end() - 1)
            seg = balanced(src, open_paren)
            # ⚠️ 真正的调用写在**尾随 lambda** 里（`restoreAction(…) { ds, id -> ds.restoreAddress(id) }`）
            #    —— 只取括号那一段会漏掉它，7 条恢复动作全部报"挂不上端点"。
            tail = src[open_paren + len(seg):]
            lm = re.match(r"\s*\{", tail)
            if lm:
                brace = open_paren + len(seg) + lm.end() - 1
                seg += tail[: lm.end() - 1] + balanced(src, brace, "{", "}")
            ident = _RESTORE_ID.search(seg) or re.search(r"AiWrites\.([A-Z][A-Z0-9_]*)", seg)
            if ident:
                add(ident.group(1), seg)
        # ② 手写处理器：类体到下一个顶层声明为止
        for m in _HANDLER.finditer(src):
            rest = src[m.end():]
            nxt = _NEXT_TOP_LEVEL.search(rest)
            add(m.group(1), rest[: nxt.start()] if nxt else rest)
    out.pop("", None)
    return out


def param_handlers() -> dict[str, set[str]]:
    """**参数式处理器**：动作常量 → 它调到的 `ds.<函数>`。

    有些处理器把动作 id 当**构造参数**收，而不是写成 `override val actionId = AiWrites.X`：

        OrderTemplateWriteHandler(AiWrites.ORDER_TEMPLATE_CREATE, ds, store)   // 注册点
        internal class OrderTemplateWriteHandler(
            override val actionId: String, …,          // ← 不是常量赋值，[action_ds_fns] 的 ② 认不出
        ) { … ds.createOrderTemplate(payload) … }

    所以它的动作↔实现关联**只存在于注册点那一个实参上**：先按 `XxxHandler(AiWrites.Y, …)`
    找出（类名, 常量）对，再去那份"类名 → 类体"索引里取实现体，最后从体里抽 `ds.` 调用。

    ⚠️ 为什么必须认这种写法（2026-09-22 踩的）：预订单的「建/改预设单」就是这个形状，
    它们**一直有 AI 动作**；但在"预订单页只能看/删/去下单"的年代，`POST /order-templates`
    不在「手机上能做」那一侧，所以判据一直是绿的。页面第一次能新建/编辑（UI 开始调
    `repo.createOrderTemplate`）当场报成**假缺口** —— 而按这个检查的话术，下一个人会去
    `EXCLUDED` 里写一条"不做"的理由，那是一条**假话**。
    """
    bodies: dict[str, str] = {}
    for f in sorted(AI.glob("AiWrite*.kt")):
        s = strip_kt_comments(f.read_text(encoding="utf-8"))
        for m in re.finditer(r"\bclass\s+(\w+)\b", s):
            rest = s[m.end():]
            nxt = _NEXT_TOP_LEVEL.search(rest)
            bodies[m.group(1)] = rest[: nxt.start()] if nxt else rest

    out: dict[str, set[str]] = {}
    for f in sorted(AI.glob("AiWrite*.kt")):
        s = strip_kt_comments(f.read_text(encoding="utf-8"))
        for m in re.finditer(r"\b(\w+Handler)\s*\(\s*AiWrites\.([A-Z][A-Z0-9_]*)", s):
            body = bodies.get(m.group(1))
            if not body:
                continue
            fns = _DS_CALL.findall(body)
            if fns:
                out.setdefault(m.group(2), set()).update(fns)
    # 反空转：一条都认不出说明注册点的写法又变了（那时这条判据会静默退回"看不见"）
    PARAM_HANDLER_PAIRS[0] = sum(len(v) for v in out.values())
    return out


def impl_repo_methods() -> dict[str, set[str]]:
    """数据源函数名 → 它的实现体里（含一跳私有 helper）调到的 repo 方法名。"""
    bodies: dict[str, str] = {}
    for rel in IMPL_FILES:
        p = AI / rel
        if not p.exists():
            continue
        src = strip_kt_comments(p.read_text(encoding="utf-8"))
        for m in re.finditer(r"override\s+suspend\s+fun\s+(\w+)\s*\(", src):
            bodies[m.group(1)] = fn_body(src, m.end())

    def repo_calls(text: str) -> set[str]:
        return set(re.findall(r"\brepo\.(\w+)\s*\(", text))

    out: dict[str, set[str]] = {}
    for fn, body in bodies.items():
        found = repo_calls(body)
        # 一跳私有 helper：`moveCategoryTo(...)` 这类间接调用（末尾要有 `(`）
        for helper in set(re.findall(r"\b([a-z]\w+)\s*\(", body)) - found:
            hb = bodies.get(helper)
            if hb:
                found |= repo_calls(hb)
        out[fn] = found
    return out


def action_consts() -> tuple[dict[str, str], set[str]]:
    """`AiWrite.kt` 的常量名 → 动作 id；以及 `SHIPPER_ACTIONS` 白名单（常量名集合）。"""
    src = strip_kt_comments((AI / "AiWrite.kt").read_text(encoding="utf-8"))
    consts = dict(re.findall(r'const val ([A-Z][A-Z0-9_]*)\s*=\s*"([^"]+)"', src))
    m = re.search(r"val SHIPPER_ACTIONS: Set<String> = setOf\(([\s\S]*?)\n    \)", src)
    if not m:
        raise SystemExit("❌ 找不到 SHIPPER_ACTIONS —— 货主白名单被搬走或改名了？")
    return consts, set(re.findall(r"\b([A-Z][A-Z0-9_]+)\b", m.group(1)))


def member_only_from_source() -> set[str]:
    """源码里标了 `memberOnly = true` 的动作常量名（与 [MEMBER_ONLY_ACTIONS] 对账）。"""
    out: set[str] = set()
    for f in sorted(AI.glob("AiWrite*.kt")):
        src = strip_kt_comments(f.read_text(encoding="utf-8"))
        marks = [(m.start(), m.group(1)) for m in _ACTION_BLOCK.finditer(src)]
        for i, (pos, const) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else len(src)
            if "memberOnly = true" in src[pos:end]:
                out.add(const)
    return out


def role_only_from_source() -> dict[str, set[str]]:
    """源码里标了 `roles = setOf(AiRole.X)` 的动作常量名 → 角色键集合（2026-09-21）。

    为什么必须从源码读而不是手写一张表：`roles` 决定了"派单员能不能看见货主那条动作"，
    手写一份就等于这条检查在验我自己的记忆。而漏掉的后果正是这次踩到的那个：
    **派单员的清单里多出两张点下去必然失败的卡**（后端以「这不是你的订单」拒绝）。
    """
    out: dict[str, set[str]] = {}
    for f in sorted(AI.glob("AiWrite*.kt")):
        src = strip_kt_comments(f.read_text(encoding="utf-8"))
        marks = [(m.start(), m.group(1)) for m in _ACTION_BLOCK.finditer(src)]
        for i, (pos, const) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else len(src)
            block = src[pos:end]
            m = re.search(r"roles = setOf\(([^)]*)\)", block)
            if not m:
                continue
            out[const] = {r.lower() for r in re.findall(r"AiRole\.([A-Z]+)", m.group(1))}
    return out


def ai_role_endpoints(role: str, member: bool) -> dict[str, set[str]]:
    """这个角色（+ 是不是批发商）能用的动作 → 各自打到的端点。

    ⚠️ 判据必须与 `AiWrites.forRole` **逐字同构**（这里是它的第二实现，两边走散就等于
    这条检查在验一个不存在的系统）：三层——
    ① `roles` 点名过的动作只给它点名的角色（退货申请那种"两个角色各一半"的域）；
    ② 派单员 = 剩下的全部**减去** `memberOnly`；货主 = 白名单**再减去**「不是批发商就没有」的。
    """
    consts, whitelist = action_consts()
    ds_by_const = action_ds_fns()
    # ⚠️ **两种处理器的结果要并起来**（2026-09-22）：`action_ds_fns` 认的是"动作定义块里
    #    就写了 `ds.x(...)`"，而参数式处理器把调用写在**类体**里、关联只在注册点上
    #    （见 [param_handlers]）。少了这一句，那批动作在派单员那一侧会被算成"没有实现"
    #    —— 表现就是一条**假缺口**（"手机上能做、AI 没能力"）。
    for const, fns in param_handlers().items():
        ds_by_const.setdefault(const, set()).update(fns)
    impl = impl_repo_methods()
    repo2ep = repo_methods()
    member_only = member_only_from_source()
    role_only = role_only_from_source()

    def role_ok(c: str) -> bool:
        return c not in role_only or role in role_only[c]

    if role == "dispatcher":
        allowed = {c for c in consts if c in ds_by_const and c not in member_only and role_ok(c)}
    else:
        allowed = {
            c for c in whitelist
            if c in consts and (c not in member_only or member) and role_ok(c)
        }
    out: dict[str, set[str]] = {}
    for const in sorted(allowed):
        eps: set[str] = set()
        for ds in ds_by_const.get(const, ()):
            for rm in impl.get(ds, ()):
                if rm in repo2ep:
                    eps.add(repo2ep[rm])
        out[consts[const]] = eps
    return out


def undo_pairs() -> dict[str, str]:
    """「删除动作 → 它的恢复动作」——从 `AiResources.kt` 的资源表里解析（不手写）。

    为什么这条属于"角色能力对账"：用户 2026-09-19 定的硬规矩是
    「**所有删除一律软删 + 必须有恢复路径**」。而恢复路径对 AI 来说是一个**动作**
    （`restoreAction(...)` 造出来的 `undoOnly`），它同样要过 `AiWrites.allows`。
    于是有一条**跨动作的角色不变量**：
        **谁有那个"删"，谁就必须有对应的那个"恢复"** ——
    少一边的表现是"用户点了自己那张卡上的撤回，被自己的权限门挡掉，记录躺在回收站里"。
    这一轮真的踩了：地址/联系人/地点三条恢复动作一直没进 `SHIPPER_ACTIONS`。
    """
    src = strip_kt_comments((AI / "AiResources.kt").read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for m in re.finditer(
        r"paired\(\s*AiWrites\.(\w+)\s*,\s*AiInverse\(\s*AiWrites\.(\w+)", src
    ):
        restore, delete = m.group(1), m.group(2)
        out[delete] = restore
    return out


def kotlin_rule_isomorphic() -> list[str]:
    """检查脚本里的"角色规则"必须与 `AiWrite.kt` 里那两行**逐字一致**。

    ⚠️ 为什么必须有这一条（反向验证当场证明的）：这个脚本的 `ai_role_endpoints` 是
    `AiWrites.forRole` 的**第二实现**，它算的是"我以为的规则"。把 Kotlin 里的
    `ALL.filter { !it.memberOnly }` 改成 `ALL`（派单员因此能碰货主自己那本账），
    Python 那一份**毫不知情**，检查照样全绿 —— 那就是一条"验的是模型、不是代码"的检查。
    所以这里把被建模的那两行钉成字面量：改了 Kotlin 就得同步改这里，否则当场红。
    """
    src = strip_kt_comments((AI / "AiWrite.kt").read_text(encoding="utf-8"))
    problems: list[str] = []
    # ⚠️ 2026-09-21：这一条从 `ALL.filter { !it.memberOnly }` 变成了"再叠一层 `roles`"——
    #    退货申请那一组里，申请/撤回是货主的、驳回/办理是派单员的，
    #    而 `memberOnly` 不够用（它只区分"批发商货主"），派单员会把货主那两条一起拿到手
    #    （点下去必被后端以「这不是你的订单」拒绝 = 本仓库列为最坏的一类"能看见但用不了"）。
    #    这里的字面量跟着改，仍要求**两个方向都过 `roles`**：只顺手过滤一边，
    #    另一边就会多出必然失败的动作 —— 那正是这次要治的病。
    if not re.search(
        r"AiRole\.DISPATCHER -> ALL\.filter \{[\s\S]{0,160}?it\.roles == null \|\| role in it\.roles",
        src,
    ):
        problems.append("AiWrite.kt 里派单员那一条不再是「roles + memberOnly 过滤」")
    # ⚠️ 2026-09-21 补：上面那条只钉了 `roles` 那半句，**`memberOnly` 那半句在代码演进时被丢了** ——
    #    而这一段 docstring 里写的就是"当初加这条判据是为了抓住 `ALL.filter { !it.memberOnly } → ALL`"。
    #    实测（`_reverse_verify_role_parity.py`）：把派单员那一支的 `&& !it.memberOnly` 摘掉，
    #    退出码 0、全绿 —— 判据成了摆设。两半句必须**各钉各的**。
    if not re.search(r"AiRole\.DISPATCHER -> ALL\.filter \{[\s\S]{0,200}?!it\.memberOnly", src):
        problems.append("AiWrite.kt 里派单员那一条不再按 memberOnly 过滤（派单员能碰货主自己那本账）")
    if not re.search(r"AiRole\.SHIPPER -> ALL\.filter \{[\s\S]{0,240}?it\.memberOnly", src):
        problems.append("AiWrite.kt 里货主那一条不再过 memberOnly（普通货主会看见批发商专属动作）")
    if not re.search(
        r"AiRole\.SHIPPER -> ALL\.filter \{[\s\S]{0,200}?it\.id in SHIPPER_ACTIONS", src,
    ):
        problems.append("AiWrite.kt 里货主那一条不再是「按 SHIPPER_ACTIONS + memberOnly 过滤」")
    if not re.search(
        r"AiRole\.SHIPPER -> ALL\.filter \{[\s\S]{0,200}?it\.roles == null \|\| role in it\.roles",
        src,
    ):
        problems.append("AiWrite.kt 里货主那一条没有过 `roles`（只过滤了白名单）")
    return problems


def globally_excluded() -> dict[str, str]:
    """`_write_coverage.py` 里**已经写下来的**「不做」理由（端点键 → 理由）。

    为什么直接复用而不是抄一份：那些理由是**按端点**下的判断（上传类 / 导出类 / 埋点类 /
    主数据维护），与"谁能调它"无关 —— 抄第二份的唯一后果是两处理由迟早走散，
    而走散之后这条检查会报一个"另一个脚本早就解释过"的假缺口。
    """
    from _write_coverage import AI_DIRECT_USE, EXCLUDED as WC_EXCLUDED  # noqa: E402

    out: dict[str, str] = {}
    for (method, path), why in {**WC_EXCLUDED, **AI_DIRECT_USE}.items():
        out[endpoint_key(method, "/" + path)] = why
    return out


# --------------------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="不自洽就非零退出（给 _check_all 用）")
    ap.add_argument("--role", default="shipper")
    args = ap.parse_args()

    backend = backend_roles()
    app = app_endpoints()
    consts, whitelist = action_consts()
    member_only_src = member_only_from_source()
    global_excl = globally_excluded()
    pairs = undo_pairs()
    pairs_by_id = {consts[d]: consts[r] for d, r in pairs.items() if d in consts and r in consts}

    fails: list[str] = []
    checks = 0

    def ok(label: str, cond: bool, detail: str = "") -> None:
        nonlocal checks
        checks += 1
        if not cond:
            fails.append(label + (f" —— {detail}" if detail else ""))

    # ---- 自洽：member 标记两边一致（源码里的 `memberOnly = true` ↔ 表里的常量名）----
    ok(
        "批发商专属动作两边一致（源码 memberOnly ↔ MEMBER_ONLY_ACTIONS）",
        member_only_src == MEMBER_ONLY_ACTIONS,
        f"源码 {sorted(member_only_src)} / 表里 {sorted(MEMBER_ONLY_ACTIONS)}"
        "（漏一个 = 普通货主的 AI 会看见一张点了必然 403 的卡）",
    )
    ok("动作常量解析没空转", len(consts) >= 100, f"只解析出 {len(consts)} 个常量")
    ok("货主白名单解析没空转", len(whitelist) >= 20, f"只解析出 {len(whitelist)} 个")
    ok("资源表的「删↔恢复」配对解析没空转", len(pairs_by_id) >= 6,
       f"只解析出 {len(pairs_by_id)} 对（少于 6 对说明 AiResources.kt 的写法变了）")
    # ⚠️ 参数式处理器（`XxxHandler(AiWrites.Y, …)`）那条路**必须真的认出东西**：
    #    认不出时它静默退回"看不见那些动作"，于是报出来的是一批**假缺口**
    #    （2026-09-22 预订单的建/改就是这样冒出来的）。
    ai_role_endpoints("dispatcher", False)   # 跑一遍把计数器填上
    ok("参数式处理器解析没空转", PARAM_HANDLER_PAIRS[0] >= 2,
       f"只认出 {PARAM_HANDLER_PAIRS[0]} 条 ds 关联（下限 2：预订单的建/改就是这种形状）")
    # ⓪ 检查脚本建模的那两条规则，必须与 Kotlin 源码**逐字一致**（见 kotlin_rule_isomorphic）
    for p in kotlin_rule_isomorphic():
        ok("检查脚本与 AiWrite.kt 的角色规则同构", False, p)

    for role in ("dispatcher", "shipper"):
        for member in ((False, True) if role == "shipper" else (False,)):
            tag = f"{role}{'+member' if member else ''}"
            ai = ai_role_endpoints(role, member)
            ai_eps = {e for eps in ai.values() for e in eps}
            backend_eps = {k for k, roles in backend.items() if role in roles}
            # 批发商专属的端点：普通货主那边**不算能力**（体内 _require_member 会 403），
            # 批发商那边**算能力**（他本来就有）。
            def owned_by(endpoint: str) -> bool:
                return endpoint in MEMBER_ONLY_ENDPOINTS and member

            # ① 不许越权：AI 打到的每个端点，后端必须允许这个角色
            over = sorted(
                e for e in ai_eps
                if e not in backend_eps and not owned_by(e)
                and not any(f"{role} {a} {e}" in ROLE_BRANCHED_CALLS for a in ai)
            )
            ok(f"[{tag}] 不越权：AI 的 {len(ai_eps)} 个端点都在后端授权内", not over,
               "越权端点：" + "、".join(over[:8]))
            # ② 不许缺能力：后端允许 ∩ 手机上有入口 ⊆ AI ∪ EXCLUDED ∪ 全局已解释的
            wanted = sorted(e for e in backend_eps if e in app)
            missing = sorted(
                e for e in wanted
                if e not in ai_eps
                and not e.startswith(("GET ", "HEAD "))          # 读能力由 ai_read_catalog 管
                and e not in global_excl
                and not (e in MEMBER_ONLY_ENDPOINTS and not member)  # 那一本账只有批发商有
                and f"{tag} {e}" not in EXCLUDED
                and f"{role} {e}" not in EXCLUDED
            )
            ok(f"[{tag}] 不缺能力：手机上能做的 {len(wanted)} 个端点都有 AI 动作或书面理由",
               not missing, "缺口：" + "、".join(missing[:8]))
            # ③ 反空转：解析出来的动作必须真的挂到端点上（挂不上的要能说清为什么）
            empty = sorted(a for a, eps in ai.items() if not eps)
            ok(f"[{tag}] 每个动作都挂到了端点上（{len(ai)} 个动作）", not empty,
               "挂不上的动作：" + "、".join(empty[:8]))
            # ④ 软删必须留恢复路径：**谁有那个"删"，谁就必须有对应的"恢复"**
            #    （例外=恢复**不在这个角色手上**，且已写清理由，见 UNDO_PAIR_EXCEPTIONS）
            broken = sorted(
                d for d, r in pairs_by_id.items()
                if d in ai and r not in ai and f"{tag} {d}" not in UNDO_PAIR_EXCEPTIONS
            )
            ok(f"[{tag}] 每个「删除」都带着它的「恢复」（软删硬规矩）", not broken,
               "有删没有恢复：" + "、".join(broken[:8])
               + "（点了撤回会被自己的权限门挡掉，记录躺在回收站里）")

            if not args.check:
                print(f"\n【{tag}】动作 {len(ai)} 个 / 端点 {len(ai_eps)} 个"
                      f"（后端允许 {len(backend_eps)}，其中手机上有入口 {len(wanted)}）")
                if missing:
                    print("  ⚠️ 缺口：")
                    for e in missing:
                        print("    · " + e)

    if not args.check:
        print(f"\n后端端点 {len(backend)} 个；App 界面在调的 {len(app)} 个")

    print("\n" + "=" * 60)
    if fails:
        print(f"❌ 角色能力账不自洽（{len(fails)}/{checks} 项不通过）：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {checks} 项通过：AI 的能力 = 角色的能力（不越权，也不缺）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
