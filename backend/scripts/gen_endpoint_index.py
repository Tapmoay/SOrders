#!/usr/bin/env python3
"""gen_endpoint_index.py —— 从代码生成「端点索引」：URL → handler → 位置 → 授权。

为什么单独成文件、不写进手写地图：
    端点清单是**低价值高体积**的信息。127 个端点写进手写定位表，体积会翻好几倍，
    把真正需要人判断的「业务概念 → 核心文件」挤掉。而且端点表是**纯机械信息**，
    人写必错、还会腐烂——机器生成则一次写对、随时重生成。
    → 手写地图只放"需要判断的"，机器生成的放 companion 文件。

用法（在 backend/ 下）：
    python -m scripts.gen_endpoint_index                    # 打印统计
    python -m scripts.gen_endpoint_index --out ../docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md
    python -m scripts.gen_endpoint_index --check --out ../docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md
        # ── 校验模式：重新生成并与磁盘比对，不一致则 exit 1（可接 CI / pre-commit）
        #    这是"生成物不腐烂"的关键：文件自己声明怎么重生成、并有机器守住它。

解析范围（读代码得出，非猜测）：
    · `app/api/v1/*.py` 里的 `router = APIRouter(prefix=...)` + `@router.<method>("<path>")`
    · 全量 URL = settings.api_v1_prefix（默认 /api/v1）+ router prefix + path
    · 授权来自三处，缺一不可：
        1. 函数签名注解：CurrentUser / ShipperOrDispatcher / Depends(require_roles(...)) / …
        2. 模块级别名：`X = Annotated[User, Depends(require_roles(...))]`（递归解析）
        3. 函数体内的手写守卫：`_must_dispatcher(current)` 等（解析该 helper 的实际行为）

⚠️ 语义陷阱（rbac.py L110）：`require_permission` 对**派单员一律放行**，不看权限点。
    所以「权限:xxx」列的真实含义是「（派单员）或（拥有该权限点的角色）」。
    本脚本在输出里显式声明这一点——索引写错权限比没有索引更危险。
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys

SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv"}

_CJK = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")


def est_tokens(text: str) -> float:
    """估算 token 数——**中文和英文不能用一个系数**。

    ⚠️ 踩过的坑：一直用 `chars / 3.5`（英文经验值）。中文在主流 BPE 分词器里约
    **0.7 token/字**，于是对中文文档会**系统性低估 1.2~1.7 倍**——
    而"这份索引是不是太大了"的判断全建立在这个数上。
    （实测：本文件生成的索引 CJK 占 6%，偏差小；但手写文档 CJK 占 25~47%，偏差 1.3~1.7×。）
    """
    n_cjk = len(_CJK.findall(text))
    return n_cjk * 0.7 + (len(text) - n_cjk) * 0.28

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")

# 权限别名 → 人类可读标签（未收录的走 AST 递归解析）
LOGIN_ONLY = "仅登录"

# 角色键 → 中文（授权列里统一用中文，避免"仅派单员"与"体内仅允许:dispatcher"两种说法并存）
ROLE_CN = {"dispatcher": "派单员", "driver": "司机", "shipper": "货主"}

# 有名字的守卫 helper → 它实际施加的约束。
# ⚠️ 格式必须与 `_find_inline_role_gates` 产出的**完全一致**，否则同一个约束会被列两遍
#    （实测踩过：`customers` 同时出现"仅派单员"和"体内仅允许:dispatcher"）。
GUARD_VERB = {
    "_must_dispatcher": "体内仅允许:派单员",
    "_require_dispatcher": "体内仅允许:派单员",
    "_dispatcher_only": "体内仅允许:派单员",
    "_can_view_or_raise": "体内仅允许:派单员|司机本人",
}


# ─────────────────────────── AST 小工具 ───────────────────────────

def _unparse(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:                                   # pragma: no cover
        return ""


def _attr_tail(node: ast.AST) -> str:
    """`UserRole.DISPATCHER` → `DISPATCHER`；`Permission.ORDER_DISPATCH` → `ORDER_DISPATCH`。"""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant):
        return str(node.value)
    return _unparse(node)


def _collect_aliases(trees: dict[str, ast.Module]) -> dict[str, ast.AST]:
    """收集 `X = Annotated[...]` / `X = Depends(...)` 这类模块级别名，供递归解析。"""
    aliases: dict[str, ast.AST] = {}
    for tree in trees.values():
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            tgt = node.targets[0]
            if isinstance(tgt, ast.Name) and tgt.id[:1].isupper():
                aliases.setdefault(tgt.id, node.value)
    return aliases


def _resolve_annot(node: ast.AST | None, aliases: dict[str, ast.AST],
                   depth: int = 0) -> list[str]:
    """把注解表达式解析成授权标签列表。返回 [] = 无鉴权。"""
    if node is None or depth > 6:
        return []

    # 模块级别名 → 展开
    if isinstance(node, ast.Name):
        if node.id == "CurrentUser":
            return [LOGIN_ONLY]
        if node.id in aliases:
            return _resolve_annot(aliases[node.id], aliases, depth + 1)
        if node.id == "get_current_user":
            return [LOGIN_ONLY]
        return []

    # Annotated[User, Depends(...)] / Depends(...)
    if isinstance(node, ast.Subscript):
        base = _unparse(node.slice)
        if node.value is not None and _unparse(node.value).endswith("Annotated"):
            return _resolve_annot(node.slice, aliases, depth + 1)
        del base
        return []

    if isinstance(node, ast.Tuple):
        out: list[str] = []
        for el in node.elts:
            out.extend(_resolve_annot(el, aliases, depth + 1))
        return out

    if isinstance(node, ast.Call):
        fn = _unparse(node.func)
        tail = fn.split(".")[-1]

        if tail == "Depends":
            return _resolve_annot(node.args[0], aliases, depth + 1) if node.args else []

        if tail == "require_roles":
            roles = sorted({r.lower() for r in (_attr_tail(a) for a in node.args) if r})
            return ["角色:" + "|".join(roles)] if roles else []

        if tail == "require_permission":
            perms = [_attr_tail(a) for a in node.args]
            perms = [p for p in perms if p]
            return ["权限:" + "|".join(perms)] if perms else []

        if tail == "get_current_user":
            return [LOGIN_ONLY]

    return []


def _find_guard_calls(node: ast.AST) -> list[str]:
    """在函数体内找手写守卫 helper 的调用（含嵌套块）。"""
    found: list[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            name = _unparse(sub.func).split(".")[-1]
            if name in GUARD_VERB and name not in found:
                found.append(name)
    return found


def _find_inline_perms(node: ast.AST) -> list[str]:
    """在函数体内找**内联**的 `role_has_permission(role, Permission.X)` 调用。

    为什么必须收：鉴权不止 `Depends(require_permission(...))` 一种写法。本项目还有 5 处
    把权限判断写在函数体里（如 `orders.py` 的删除端点对货主额外要求 ORDER_DELETE_CANCELLED）。
    只认 Depends 的话，「改 X 权限点会影响哪些端点」会漏掉这些——**漏报比误报危险**。
    这类判断通常是**条件性**的（只对某个角色生效），所以单独标注"体内"，不并入入口级授权。
    """
    found: list[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            name = _unparse(sub.func).split(".")[-1]
            if name != "role_has_permission":
                continue
            for a in sub.args:
                if isinstance(a, ast.Attribute) and isinstance(a.value, ast.Name) \
                        and a.value.id == "Permission":
                    if a.attr not in found:
                        found.append(a.attr)
    return found


def _find_inline_role_gates(node: ast.AST) -> list[str]:
    """找出函数体内**直接写**的角色硬门槛，返回人类可读标签。

    为什么必须收：授权有**三种**写法，前两种生成器早就认了，第三种一直漏：
      ① 签名注解  `current: CurrentUser` / `ShipperOrDispatcher`
      ② 签名默认值 `Depends(require_roles(...))` / `Depends(require_permission(...))`
      ③ **函数体内** `if user_role_key(current) != UserRole.DISPATCHER.value: raise 403`
    第 ③ 种实测有 36 个端点命中，其中一部分是**硬门槛**——只认前两种会让授权列
    把"仅派单员"的端点误标成"仅登录"。**授权列错得比缺更危险**：读的人会据此以为谁都能调。

    判定要点：光有 `UserRole.X` 不算门槛（多数是行级过滤，如"司机只看自己的单"）；
    必须同时具备 **角色比对** 与 **该分支里 raise 403**，才算"拒绝"型门槛。

    角色变量还要跟踪一步：本项目常先 `role = user_role_key(current)` 再比较，
    所以只搜 `user_role_key` 字面量会漏掉一半。
    """
    # 收集"从 user_role_key(...) 赋值的变量名"
    role_vars = {"current", "user"}          # 常见形参名，直接比较也算
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assign) and "user_role_key(" in _unparse(sub.value):
            for t in sub.targets:
                if isinstance(t, ast.Name):
                    role_vars.add(t.id)

    def is_role_test(test: ast.AST) -> bool:
        src = _unparse(test)
        if "UserRole." not in src:
            return False
        if "user_role_key(" in src:
            return True
        # `role != UserRole.DISPATCHER.value` 形式
        return any(re.search(r"\b" + re.escape(v) + r"\b", src) for v in role_vars)

    def direct_403(branch: list[ast.stmt]) -> bool:
        """该分支**自身**是否直接 raise 403。

        ⚠️ 必须只看直接子语句，不能 ast.walk 进嵌套 If——这是本函数第一版的致命缺陷：
           `if role == SHIPPER: if body.shipper_id != current.id: raise 403`
           被误读成"排除货主"，实际含义是"货主还要满足一个条件"。
           它让授权列出现 `货主 + 体内排除:货主` 这种自相矛盾的值。
           **宁可少报，不可报错**：授权列错得比缺更危险。
        """
        return any(isinstance(x, ast.Raise) and "403" in _unparse(x) for x in branch)

    # 函数体的**直接语句**集合——只有位于这一层的判断才算"入口级门槛"。
    # 在 if/elif 链里出现的 `else: raise 403` 不算：链前面的分支可能已经放行了别的角色
    # （实测 `create_order` 就因此被误标成"仅派单员"，而货主本来也能下单）。
    top_level = {id(st) for st in getattr(node, "body", [])}

    # **只认「角色不在某些角色里」这一种形态**：条件含义必须是 `role ∉ {…}`，
    # 且当它直接 raise 403 时，能推出"允许的就是列出的那些角色"。
    #
    # ⚠️ 光是"含 and/or 就不下结论"曾经漏掉一整类硬门槛（实测 driver_bills / driver_settlements）：
    #     `if role != UserRole.DISPATCHER.value and role != UserRole.DRIVER.value: raise 403`
    #   ——它是**同一件事写了两次**（不在 A 且不在 B），本质等于 `role not in (A, B)`。
    #   漏掉的代价很实在：授权列写成"仅登录 + 需读源码"，读的人（还有 AI 的读目录生成器）
    #   会以为货主也能调，实际货主拿的是 403。
    #   而 `list_orders` 那种 `(include_deleted or deleted_only) and role != DISPATCHER.value`
    #   必须继续判不出来——它混了非角色条件，只在传特定参数时才限制。
    #   两者的分界很清晰：**每个操作数都得是纯角色比较**才算数。
    def excluded_shape(test: ast.AST) -> tuple[set[str], bool]:
        """`(角色集合, 是否就是「role ∉ 角色集合」这种形态)`。"""
        if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
            acc: set[str] = set()
            for v in test.values:
                rs, ok = excluded_shape(v)
                if not ok:
                    return set(), False
                acc |= rs
            return acc, bool(acc)
        if (
            isinstance(test, ast.Compare)
            and len(test.ops) == 1
            and isinstance(test.ops[0], (ast.NotEq, ast.NotIn))
            and is_role_test(test)
        ):
            return {r.lower() for r in re.findall(r"UserRole\.([A-Z_]+)", _unparse(test))}, True
        return set(), False

    labels: list[str] = []
    unresolved = False
    for sub in ast.walk(node):
        if not isinstance(sub, ast.If) or not is_role_test(sub.test):
            continue
        src = _unparse(sub.test)
        if id(sub) not in top_level:
            unresolved = True
            continue

        roles, ok = excluded_shape(sub.test)
        if ok and direct_403(sub.body):
            lab = "体内仅允许:" + "|".join(ROLE_CN.get(r, r) for r in sorted(roles))
            if lab not in labels:
                labels.append(lab)
            continue

        # 形态二：`if role == A: … elif role != B: raise 403`
        #   —— 第一个分支先兜住 A，剩下的只要不是 B 就 403，所以允许的正好是 {A, B}。
        #   为什么这种 if/elif 敢下结论、而 `else: raise 403` 不敢：这里的 raise 被**纯角色比较**
        #   守着，条件里没混别的量。`create_order` 那种 `if role == SHIPPER: … elif role == DISPATCHER: … else: raise 403`
        #   依然判不出来（它的 else 不带角色条件），仍然是"需读源码"——那正是不能误报的例子。
        if (
            isinstance(sub.test, ast.Compare)
            and len(sub.test.ops) == 1
            and isinstance(sub.test.ops[0], (ast.Eq, ast.In))
            and is_role_test(sub.test)
            and not direct_403(sub.body)
            and len(sub.orelse) == 1
            and isinstance(sub.orelse[0], ast.If)
        ):
            inner = sub.orelse[0]
            inner_roles, inner_ok = excluded_shape(inner.test)
            if inner_ok and direct_403(inner.body):
                first = {r.lower() for r in re.findall(r"UserRole\.([A-Z_]+)", _unparse(sub.test))}
                lab = "体内仅允许:" + "|".join(ROLE_CN.get(r, r) for r in sorted(first | inner_roles))
                if lab not in labels:
                    labels.append(lab)
                continue

        # 形态三：`if role == A: … elif role == B: … else: raise 403`
        #   允许的正好是链上出现过的那些角色——不是它们就落到 else 的 403。
        #   ⚠️ 这与历史 bug 的区别很关键：那时是"看到 else 里 raise 403 就只认最后一个角色"，
        #      于是 `create_order` 被误标成"仅派单员"（货主本来也能下单）。
        #      这里要求：链上**每个**分支的判断都是纯角色比较，且末端 else 直接 raise 403，
        #      然后把**链上所有角色并起来**——宁可把集合说全，也不说成单个角色。
        if (
            isinstance(sub.test, ast.Compare)
            and len(sub.test.ops) == 1
            and isinstance(sub.test.ops[0], (ast.Eq, ast.In))
            and is_role_test(sub.test)
            and not direct_403(sub.body)
        ):
            chain = {r.lower() for r in re.findall(r"UserRole\.([A-Z_]+)", _unparse(sub.test))}
            tail = sub.orelse
            ok_chain = True
            while len(tail) == 1 and isinstance(tail[0], ast.If):
                nxt = tail[0]
                nt = nxt.test
                if not (
                    isinstance(nt, ast.Compare)
                    and len(nt.ops) == 1
                    and isinstance(nt.ops[0], (ast.Eq, ast.In))
                    and is_role_test(nt)
                    and not direct_403(nxt.body)
                ):
                    ok_chain = False
                    break
                chain |= {r.lower() for r in re.findall(r"UserRole\.([A-Z_]+)", _unparse(nt))}
                tail = nxt.orelse
            if (
                ok_chain
                and chain
                and len(tail) == 1
                and isinstance(tail[0], ast.Raise)
                and "403" in _unparse(tail[0])
            ):
                lab = "体内仅允许:" + "|".join(ROLE_CN.get(r, r) for r in sorted(chain))
                if lab not in labels:
                    labels.append(lab)
                continue

        # 其它形态一律**不下结论**（见上方两处实测反例），只标记"这里有角色判断"。
        # 复合条件里只要有一个非角色操作数，就走这里（`include_deleted or deleted_only` 那种）。
        if " and " in src or " or " in src:
            unresolved = True
            continue
        unresolved = True

    if unresolved and not labels:
        labels.append("体内含角色判断（需读源码）")
    return labels


def _find_inline_hard_perms(node: ast.AST) -> list[str]:
    """体内**无条件**的权限门槛：顶层 `if not role_has_permission(role, Permission.X): raise 403`。

    与 `_find_inline_perms`（扫到权限名就算，可能是条件性的）不同：这条形态的条件里
    只有"有没有这个权限"，没混别的量，所以它和签名里挂 `Depends(require_permission(X))`
    等价，属于**入口级**约束。

    实测（`products.list_products`）：`if not role_has_permission(rk, Permission.ORDER_CREATE): raise 403`
    —— 司机没有 ORDER_CREATE，所以司机调它必然 403。不标出来的话，读的人（以及按本表
    裁剪能力的 AI 读目录）会以为司机也能读商品目录。
    """
    out: list[str] = []
    top_level = {id(st) for st in getattr(node, "body", [])}
    for sub in ast.walk(node):
        if not isinstance(sub, ast.If) or id(sub) not in top_level:
            continue
        test = sub.test
        if not (isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)):
            continue
        call = test.operand
        if not isinstance(call, ast.Call) or "has_permission" not in _unparse(call.func):
            continue
        perms = re.findall(r"Permission\.([A-Z_]+)", _unparse(call))
        if not perms:
            continue
        if any(isinstance(x, ast.Raise) and "403" in _unparse(x) for x in sub.body):
            for p in perms:
                if p not in out:
                    out.append(p)
    return out


def _uses_current_id(node: ast.AST) -> bool:
    """函数体是否出现 `current.id`（行级数据隔离的典型标记）。"""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and sub.attr == "id":
            if isinstance(sub.value, ast.Name) and sub.value.id == "current":
                return True
    return False


# ─────────────────────────── 扫描 ───────────────────────────

def _scan_module(path: str, tree: ast.Module) -> tuple[dict[str, str], list[dict]]:
    """返回 ({变量名: prefix}, 端点列表)。

    ⚠️ 只认名叫 `router` 的变量是不够的：`app/main.py` 里是
       `application = FastAPI(...)` + `@application.get("/health")`——
       漏掉它会让索引静默缺少 `/health`，而"索引里没有"会被读成"不存在"。
       所以泛化：任何模块级变量只要赋值成 `APIRouter(...)` 或 `FastAPI(...)` 都算路由宿主。
    """
    hosts: dict[str, tuple[str, str]] = {}
    # ⚠️ 必须遍历整棵树，不能只看 module body：本项目 `main.py` 的路由宿主
    # `application = FastAPI(...)` 建在工厂函数 `create_fastapi_app()` **内部**，
    # 只看模块顶层会让 /health、/static/uploads/{path}、/system/app-version 三个真实
    # 路由\静默消失——索引缺项会被读成"不存在"，比写错更危险。
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        ctor = _unparse(node.value.func).split(".")[-1]
        if ctor not in ("APIRouter", "FastAPI"):
            continue
        prefix = ""
        for kw in node.value.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                prefix = str(kw.value.value)
        for tgt in node.targets:
            if isinstance(tgt, ast.Name):
                hosts[tgt.id] = (prefix, ctor)

    endpoints: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            if not isinstance(deco, ast.Call):
                continue
            f = deco.func
            if not (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)):
                continue
            if f.value.id not in hosts or f.attr not in HTTP_METHODS:
                continue
            prefix, ctor = hosts[f.value.id]
            sub = deco.args[0].value if deco.args and isinstance(deco.args[0], ast.Constant) else ""
            endpoints.append({
                "file": path,
                "lineno": node.lineno,
                "def_lineno": node.lineno,
                "method": f.attr.upper(),
                "sub": str(sub),
                "prefix": prefix,
                "app_level": ctor == "FastAPI",   # 挂在 app 上 → 不走 /api/v1
                "name": node.name,
                "node": node,
                "decos": deco,
            })
    return {k: v[0] for k, v in hosts.items()}, endpoints


def _func_lineno(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """`def` 关键字所在行。

    ⚠️ Python 3.8+ 起 `ast.FunctionDef.lineno` **已经**指向 `def` 行，
    装饰器另在 `decorator_list[i].lineno`。不要再加 `len(decorator_list)`——
    那是 3.7 及更早的行为，照抄会让每个行号都偏大（本项目 127 个端点全错一位）。
    """
    return node.lineno


def collect(app_root: str, files: list[str]) -> tuple[list[dict], dict[str, ast.AST]]:
    trees: dict[str, ast.Module] = {}
    for rel in files:
        full = os.path.join(app_root, rel)
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                trees[rel] = ast.parse(fh.read())
        except (SyntaxError, OSError) as exc:
            print(f"warning: 跳过 {rel}: {exc}", file=sys.stderr)

    aliases = _collect_aliases(trees)

    rows: list[dict] = []
    for rel, tree in trees.items():
        _, eps = _scan_module(rel, tree)
        for ep in eps:
            node = ep["node"]
            labels: list[str] = []
            a = node.args
            # ⚠️ 鉴权有两种写法，必须都扫：
            #   `current: CurrentUser`                      → 在 annotation
            #   `_: User = Depends(require_permission(...))` → 在 default
            # 本项目绝大多数是后者（实测 66 处），只看 annotation 会全部漏掉、
            # 把受保护端点误报成「公开」——比没有索引危险得多。
            # AST 里 default 不在 arg 上：位置参数的默认值挂在 args.defaults（右对齐），
            # 仅关键字参数的挂在 args.kw_defaults（与 kwonlyargs 一一对应，None 表示无默认值）。
            positional = a.posonlyargs + a.args
            pad = [None] * (len(positional) - len(a.defaults))
            for arg, default in zip(positional, pad + list(a.defaults)):
                for lab in _resolve_annot(arg.annotation, aliases):
                    if lab not in labels:
                        labels.append(lab)
                for lab in _resolve_annot(default, aliases):
                    if lab not in labels:
                        labels.append(lab)
            for arg, default in zip(a.kwonlyargs, a.kw_defaults):
                for lab in _resolve_annot(arg.annotation, aliases):
                    if lab not in labels:
                        labels.append(lab)
                for lab in _resolve_annot(default, aliases):
                    if lab not in labels:
                        labels.append(lab)
            guards = _find_guard_calls(node)
            guard_labels = [GUARD_VERB[g] for g in guards]
            # 体内**无条件**权限门槛 = 入口级约束（等价于签名挂 require_permission），
            # 所以直接并进 auth；条件性的那些仍留在 inline_perms 里单列。
            hard_perms = _find_inline_hard_perms(node)
            for p in hard_perms:
                lab = "权限:" + p
                if lab not in labels:
                    labels.append(lab)
            ep["auth"] = labels
            ep["guards"] = guards
            ep["guard_labels"] = guard_labels
            ep["hard_perms"] = hard_perms
            ep["inline_perms"] = [p for p in _find_inline_perms(node) if p not in hard_perms]
            ep["inline_roles"] = _find_inline_role_gates(node)
            ep["scoped"] = _uses_current_id(node)
            ep["lineno"] = _func_lineno(node)
            ep.pop("node")
            ep.pop("decos")
            rows.append(ep)

    rows.sort(key=lambda r: (r["file"], r["lineno"]))
    return rows, aliases


def _all_permissions(api_dir: str) -> set[str]:
    """从 `app/core/rbac.py` 的 `class Permission` 读出全部权限点成员名。

    用途：与"被端点引用到的权限点"做差集，报出**声明了却没端点用**的权限点——
    这类权限点改起来毫无效果，却很容易被当成"我改了权限"。
    """
    # api_dir = app/api/v1 → 上两级才是 app/，rbac.py 在 app/core/rbac.py
    core = os.path.join(os.path.dirname(os.path.dirname(api_dir.rstrip("/\\"))), "core", "rbac.py")
    if not os.path.isfile(core):
        return set()
    try:
        with open(core, encoding="utf-8", errors="replace") as fh:
            tree = ast.parse(fh.read())
    except (SyntaxError, OSError):
        return set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Permission":
            return {t.id for st in node.body if isinstance(st, ast.Assign)
                    for t in st.targets if isinstance(t, ast.Name)}
    return set()


def compose_url(row: dict, api_prefix: str) -> str:
    # 挂在 FastAPI app 上的路由（如 /health）不走 /api/v1
    head = "" if row.get("app_level") else api_prefix
    return (head + row["prefix"] + row["sub"]) or "/"


def auth_text(row: dict) -> str:
    parts = list(row["auth"])
    for g in row["guard_labels"]:
        if g not in parts:
            parts.append(g)
    # 函数体内内联判的权限点：条件性的（常只对某角色生效），单列出来不并入入口级
    for p in row.get("inline_perms", []):
        parts.append("体内权限:" + p)
    # 函数体内直接写的角色硬门槛（带 raise 403 的那种）
    for r in row.get("inline_roles", []):
        parts.append(r)

    if not parts:
        return "**公开**"
    if parts == [LOGIN_ONLY]:
        return LOGIN_ONLY
    # 「仅登录」只在有更强的入口级约束（角色/权限点）时才省略；
    # ⚠️ 若只有体内权限/体内角色门槛，**必须保留**「仅登录」——否则会读成"这个端点只要权限点"，
    #    而真相是"先登录，再在体内按角色条件判断"。（此前这里有早退 bug，把体内约束整段吞掉了。）
    if LOGIN_ONLY in parts and any(p.startswith(("角色:", "权限:")) for p in parts):
        parts = [p for p in parts if p != LOGIN_ONLY]

    # ⚠️ 必须转义 `|`：`角色:dispatcher|shipper` 里的竖线不转义会被 Markdown
    # 当成表格列分隔符，一格变两格，读表的人会看到被劈开的半个值。
    return " + ".join(parts).replace("|", "\\|")


# ─────────────────────────── 渲染 ───────────────────────────

HEADER = """<!-- 本文件由 backend/scripts/gen_endpoint_index.py 生成，请勿手工编辑 -->
<!-- 重新生成：
       cd backend
       python -m scripts.gen_endpoint_index --out ../docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md
     校验是否过期（CI/pre-commit）：
       python -m scripts.gen_endpoint_index --check --out ../docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md
-->

# 08A 端点索引（URL → handler → 授权）

> **本文件是 [08_CODE_LOCATOR.md](08_CODE_LOCATOR.md) 的 companion：机器生成、不做判断。**
> 手写地图负责"改某个功能该动哪几个文件"（需要人判断）；本文件负责"这个 URL 落在哪个函数、
> 谁能调"（纯机械事实）。两者分开，是为了不让上百行端点表撑爆手写地图的阅读预算。
>
> **别通读本文件**——它比手写地图大。要查就 grep，命中一行就够。

## 读法（先读这段，10 秒）

- **查某个 URL** → `grep -n 'orders/{order_id}' 08A_ENDPOINT_INDEX.md`，**不要通读全表**。
- **加新接口** → 先在下面「按文件」表里看同模块既有接口的写法，再照抄授权列。
- **改权限** → 看「权限点反查」段，能立刻知道改一个权限点会影响哪些端点。
- **路径前缀有两种**：绝大多数是 `/api/v1/...`；`backend/app/main.py` 里 3 个是**挂在 app 上**
  的（`/health`、`/static/uploads/{path}`、`/api/v1/system/app-version`），路径已按真实拼接结果写出。

### ⚠️ 授权列的语义（写错权限比没有索引更危险）

| 授权列的值 | 真实含义 | 可信度 |
|---|---|---|
| **公开** | 无任何鉴权依赖（本项目仅登录/注册/发短信 + 3 个 app 级路由） | 可靠 |
| 仅登录 | 只要有效 token，**不限角色**——业务约束在函数体内 | 可靠 |
| 角色:a\\|b | `require_roles()` 硬校验，roles 之外一律 403 | 可靠 |
| 权限:XXX | `require_permission(Permission.XXX)` | 可靠 |
| **体内仅允许:X** | 函数体里**直接拒绝**了非 X 的角色（形如 `if role != X: raise 403`） | 可靠 |
| **体内含角色判断（需读源码）** | 检测到角色分支但**无法可靠归纳**——可能是条件性限制（只在某些参数下才要求某角色），也可能是行级过滤（司机只看自己的单）。**必须点进源码** | ⚠️ **不确定** |
| **体内权限:X** | 权限点写在函数体里，而不是签名里 | 可靠 |
| 体内仅允许:派单员\\|司机 这类 helper | 由 `_must_dispatcher` 等命名守卫施加 | 可靠 |

> ⚠️ **「体内含角色判断（需读源码）」是刻意保留的"我不知道"**，不是漏检。
> 实测两类反例都栽在这上面：
> · `GET /orders` 的门是 `if (include_deleted or deleted_only) and role != DISPATCHER`——**复合条件**，
>   只在传那两个参数时才限制，全角色平时都能调；
> · `POST /orders` 是 `if role == SHIPPER: … elif role == DISPATCHER: … else: raise 403`——**只看末端 else
>   会把货主也说成不允许**。
> 生成器对这两种都**不下结论**。**授权列宁可写"我不确定"，也不能写错**——读的人会据此判断谁有权限。

**🔴 关键陷阱：`require_permission` 对派单员一律放行。**
见 `backend/app/core/rbac.py` L109-L117：`role_has_permission()` 开头就是
"派单员为最高业务权限：通过 require_permission 校验时一律放行（仍须有效登录）"。
所以 `权限:LEDGER_READ_OWN` 的真实含义是
**（派单员）或（拥有该权限点的角色）**——派单员不看权限点，直接通过。
**因此不能靠读 `rbac.py` 的 `ROLE_PERMISSIONS` 反推某端点的准入范围**，本表的授权列才是入口级真相。

### 其它约定

- 位置列 = `def` 所在行（**不是装饰器行**）。同一处以函数名为准，行号会随编辑漂移。
- 行级隔离（司机只能看自己的单）多数写成 `current.id` 赋值过滤，**入口级授权列看不出**，需读函数体。
- **授权列可能同时出现「入口级」和「体内权限:X」**：前者在签名里（`Depends`），后者写在函数体内
  （常只对某一类角色附加要求）。后者**光看签名看不到**，是本索引刻意补上的。
- 「权限点反查」段末尾会列出**声明了却没任何端点引用**的权限点——改那些等于没改。
- 改代码后本表会过期 → 跑上面的 `--check`，不一致就重新生成。**别手改，改了会被下次生成覆盖。**
"""


def render(rows: list[dict], api_prefix: str, repo_rel: str, api_dir: str) -> str:
    out: list[str] = [HEADER]

    # 按文件分组
    by_file: dict[str, list[dict]] = {}
    for r in rows:
        by_file.setdefault(r["file"], []).append(r)

    out.append(f"\n## 全量端点（{len(rows)} 个，按文件分组）\n")
    for rel in sorted(by_file):
        eps = by_file[rel]
        loc = f"{repo_rel}/{rel}" if repo_rel else rel
        out.append(f"\n### `{loc}` — {len(eps)} 个\n")
        out.append("| # | 方法与路径 | handler | 位置 | 授权 |")
        out.append("|---|---|---|---|---|")
        for i, r in enumerate(eps, 1):
            url = compose_url(r, api_prefix)
            out.append(f"| {i} | `{r['method']} {url}` | `{r['name']}` | `{loc}:{r['lineno']}` "
                       f"| {auth_text(r)} |")

    # 权限点反查（入口级 require_permission + 函数体内联 role_has_permission）
    perms: dict[str, list[tuple[str, str]]] = {}
    roles: dict[str, list[str]] = {}
    for r in rows:
        url = f"{r['method']} {compose_url(r, api_prefix)}"
        for lab in r["auth"]:
            if lab.startswith("权限:"):
                perms.setdefault(lab[3:], []).append((url, "入口"))
            elif lab.startswith("角色:"):
                roles.setdefault(lab[3:], []).append(url)
        for p in r.get("inline_perms", []):
            perms.setdefault(p, []).append((url, "体内"))

    used = set(perms)
    all_perms = _all_permissions(api_dir)
    unused = sorted(all_perms - used)

    out.append("\n## 权限点反查（改一个权限点影响哪些端点）\n")
    if perms:
        out.append("| 权限点 | 端点数 | 端点 |")
        out.append("|---|---|---|")
        for k in sorted(perms):
            items = perms[k]
            cell = "<br>".join(
                f"`{u}`" + ("（体内条件判断）" if kind == "体内" else "") for u, kind in items)
            out.append(f"| `{k}` | {len(items)} | {cell} |")
        out.append("\n> **「体内条件判断」** = 该权限点不是在签名里用 `Depends(require_permission(...))` 校验的，"
                   "而是写在函数体里（通常只对某类角色附加要求）。改这类权限点**不会**被签名层看见，"
                   "必须点进源码。")
        out.append("\n> 记住派单员超权：上表端点派单员**无需**拥有该权限点也能通过。")
    else:
        out.append("_（无：全项目没有端点用 `require_permission`）_")

    if all_perms:
        out.append(f"\n### 声明了但没有任何端点引用的权限点：{len(unused)} / {len(all_perms)} 个\n")
        if unused:
            out.append("> 这些权限点只存在于 `backend/app/core/rbac.py` 的枚举里，**改它们不影响任何端点**"
                       "（也不会报错，容易误以为生效了）。\n")
            for p in unused:
                out.append(f"- `{p}`")
        else:
            out.append("_（全部权限点都有端点引用）_")
        out.append("\n> 反过来说，某个业务动作**没被权限点保护**时，这里看不出来——"
                   "要看上面「仅登录」段的端点，它们的准入靠函数体内判断。")

    out.append("\n## 角色反查（`require_roles` 硬校验的端点）\n")
    if roles:
        out.append("| 角色组合 | 端点数 | 端点 |")
        out.append("|---|---|---|")
        for k in sorted(roles):
            urls = roles[k]
            out.append(f"| `{k.replace('|', chr(92) + '|')}` | {len(urls)} | "
                       + "<br>".join(f"`{u}`" for u in urls) + " |")
    else:
        out.append("_（无）_")

    # 需要注意的端点
    dup: dict[str, list[str]] = {}
    for r in rows:
        key = f"{r['method']} {compose_url(r, api_prefix)}"
        loc = f"{repo_rel}/{r['file']}:{r['lineno']}" if repo_rel else f"{r['file']}:{r['lineno']}"
        dup.setdefault(key, []).append(loc)
    dups = {k: v for k, v in dup.items() if len(v) > 1}

    pub = [r for r in rows if not r["auth"]]
    # ⚠️ 「仅登录」这一档必须把**体内**约束也算上，否则会和上面的授权列自相矛盾——
    #    授权列写着"仅登录 + 体内仅允许:派单员"，这里却把它列为"无守卫"。
    #    实测踩过：加了体内角色检测后，这一节仍报 36 个，而实际只剩十来个。
    login_only = [r for r in rows
                  if r["auth"] == [LOGIN_ONLY] and not r["guard_labels"]
                  and not r.get("inline_roles") and not r.get("inline_perms")]
    scoped = [r for r in rows if r["scoped"]]

    out.append("\n## 需要注意的端点（机器可判定的三类风险）\n")

    out.append(f"\n### 1. 同一 方法+路径 被注册多次：{len(dups)} 处\n")
    if dups:
        out.append("FastAPI 按注册顺序匹配，**先注册的生效，后面的永远不会被调用**（死代码）。\n")
        out.append("| 方法与路径 | 定义位置（按注册顺序） |")
        out.append("|---|---|")
        for k in sorted(dups):
            out.append(f"| `{k}` | " + "<br>".join(f"`{p}`" for p in dups[k]) + " |")
    else:
        out.append("_（无重复注册）_")

    out.append(f"\n### 2. 完全公开（无鉴权）：{len(pub)} 个\n")
    if pub:
        out.append("| 方法与路径 | handler | 位置 |")
        out.append("|---|---|---|")
        for r in pub:
            loc = f"{repo_rel}/{r['file']}" if repo_rel else r["file"]
            out.append(f"| `{r['method']} {compose_url(r, api_prefix)}` | `{r['name']}` "
                       f"| `{loc}:{r['lineno']}` |")
    else:
        out.append("_（无）_")

    out.append(f"\n### 3. 仅登录、且检测不到任何角色/权限约束：{len(login_only)} 个\n")
    out.append("> 这些端点的准入范围**在本表里看不出来**——约束（如果有）在函数体里按参数或 `current.id` 过滤。\n"
               "> 反过来说：**这一节是「该去读源码」的清单**，不是「谁都能调」的清单。\n")
    if login_only:
        out.append("| 方法与路径 | handler | 位置 | 含 `current.id` |")
        out.append("|---|---|---|---|")
        for r in login_only:
            loc = f"{repo_rel}/{r['file']}" if repo_rel else r["file"]
            out.append(f"| `{r['method']} {compose_url(r, api_prefix)}` | `{r['name']}` "
                       f"| `{loc}:{r['lineno']}` | {'✅' if r['scoped'] else '—'} |")
    else:
        out.append("_（无）_")

    if scoped:
        out.append(f"\n> ⚠️ 「含 `current.id`」只是**粗筛**：函数体里出现 `current.id` 既可能是行级过滤"
                   f"（`where(shipper_id == current.id)`），也可能只是审计日志的 `operator_id=current.id`。"
                   f"全表共 **{len(scoped)}** 个端点命中（占 {len(scoped) * 100 // max(len(rows), 1)}%），"
                   "**要确认是哪种必须读函数体**。涉及文件：" +
                   "、".join(f"`{repo_rel}/{f}`" if repo_rel else f"`{f}`"
                            for f in sorted({r['file'] for r in scoped})) + "。")

    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):          # Windows 控制台默认 GBK
        try:
            stream.reconfigure(encoding="utf-8")     # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(
        prog="python -m scripts.gen_endpoint_index",
        description="生成端点索引：URL → handler → 位置 → 授权")
    ap.add_argument("--app-root", default="app", help="FastAPI 应用目录（默认 app）")
    ap.add_argument("--api-prefix", default=None, help="API 前缀，默认从 app/config.py 读")
    ap.add_argument("--out", help="输出 Markdown 文件（省略则只打印统计）")
    ap.add_argument("--check", action="store_true",
                    help="校验模式：与 --out 文件比对，不一致 exit 1")
    ap.add_argument("--repo-root", default=None, help="仓库根（默认向上找 .git）")
    args = ap.parse_args(argv)

    if args.check and not args.out:
        print("error: --check 需要同时给 --out", file=sys.stderr)
        return 2

    here = os.path.abspath(os.getcwd())
    app_root = args.app_root if os.path.isabs(args.app_root) else os.path.join(here, args.app_root)
    if not os.path.isdir(app_root):
        print(f"error: 应用目录不存在: {app_root}", file=sys.stderr)
        return 2

    repo_root = os.path.abspath(args.repo_root) if args.repo_root else _find_repo_root(here)
    # 引用基准：文档里的路径是「仓库相对」，即 backend/app/api/v1/x.py。
    # app_root 通常 = backend/app，所以要把 app 这一层也拼回来，否则会写成
    # backend/api/v1/x.py（少了 app/，路径全错）。
    try:
        repo_rel = os.path.relpath(app_root, repo_root).replace("\\", "/")
    except ValueError:
        repo_rel = ""
    if repo_rel == ".":
        repo_rel = ""

    # 收集 api/v1 下所有 .py
    api_dir = os.path.join(app_root, "api", "v1")
    if not os.path.isdir(api_dir):
        print(f"error: 找不到 {api_dir}", file=sys.stderr)
        return 2
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(app_root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            if fn.endswith(".py"):
                full = os.path.join(dirpath, fn)
                files.append(os.path.relpath(full, app_root).replace("\\", "/"))
    files.sort()

    # API 前缀：优先命令行，其次 app/config.py
    api_prefix = args.api_prefix
    if api_prefix is None:
        api_prefix = _read_api_prefix(app_root) or "/api/v1"

    rows, _ = collect(app_root, files)
    text = render(rows, api_prefix, repo_rel, api_dir)

    print(f"扫描文件      : {len(files)}")
    print(f"端点数        : {len(rows)}")
    print(f"API 前缀      : {api_prefix}")
    print(f"输出体积      : {len(text)} chars  ≈ {est_tokens(text):,.0f} tokens")
    print(f"仓库相对根     : {repo_rel or '(仓库根)'}")

    if args.check:
        out_path = args.out
        if not os.path.isfile(out_path):
            print(f"\n❌ --check: 文件不存在，请先生成: {out_path}", file=sys.stderr)
            return 1
        with open(out_path, encoding="utf-8") as fh:
            on_disk = fh.read()
        if on_disk != text:
            print(f"\n❌ --check: {out_path} 与代码不一致（端点索引已过期）。\n"
                  f"   重新生成: python -m scripts.gen_endpoint_index --out {out_path}",
                  file=sys.stderr)
            return 1
        print("\n✅ --check: 端点索引与代码一致")
        return 0

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        print(f"已写出        : {args.out}")
    return 0


def _read_api_prefix(app_root: str) -> str | None:
    """从 app/config.py 读 api_v1_prefix 默认值。"""
    cfg = os.path.join(app_root, "config.py")
    if not os.path.isfile(cfg):
        return None
    try:
        with open(cfg, encoding="utf-8", errors="replace") as fh:
            tree = ast.parse(fh.read())
    except (SyntaxError, OSError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == "api_v1_prefix" and isinstance(node.value, ast.Constant):
            return str(node.value.value)
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "api_v1_prefix" \
                        and isinstance(node.value, ast.Constant):
                    return str(node.value.value)
    return None


def _find_repo_root(start: str) -> str:
    cur = os.path.abspath(start)
    while True:
        if os.path.isdir(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return os.path.abspath(start)
        cur = parent


if __name__ == "__main__":
    raise SystemExit(main())
