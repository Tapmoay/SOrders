#!/usr/bin/env python3
"""_check_order_commands.py —— 订单命令注册表与代码的逐条对账（进 `_check_all.py` 自动跑）。

### 为什么需要它（第二轮 R2-02）
指南 §三 要的是「订单状态必须成为真正的**唯一写入口**」，并且明确
「不要为了唯一入口而建立一个巨大万能函数」。第一轮已经把状态跃迁收进了
`services/order_flow.py`（7 处条件 UPDATE），但**每一处的前置状态只写在函数体的注释里** ——
注释会腐烂，而且没有任何机器事实说得出「订单到底有哪几条命令」。

这一条判据把两件事钉在一起：

```text
  声明（backend/app/commands/registry.py）  ⇄  代码（条件 UPDATE / 构造期状态）
```

### 判据
1. 注册表非空且条数达标（反空转）；
2. 每条命令的 `impl` 真的存在；
3. 归属域是地图上的域（订单命令必须是 `order`）；
4. `capabilities` 都是真的权限点；
5. `from_states` / `to_state` 都是真的 `OrderStatus`；
6. `events` 都在地图上有域认领（不许编一个没人负责的事实）；
7. `effects` 都是真的表，且**不属于本域**（跨域写要显式登记）；
8. ⭐ **CAS 对账**：`services/order_flow.py` 里每一处条件 UPDATE 的
   （前置状态集合 → 目标状态）必须与注册表**一模一样**（多一条、少一条、前置写错都报红）；
9. ⭐ **构造期状态**：`Order(status=…)` 写下的状态必须是某条命令的 `to_state`；
   ⛔ 而且 `backend/app/api/**` 里**一处都不许有** —— 这就是指南 §十九 的退出条件
   「API 不直接改变 order.status」；
10. 不改状态的命令（`to_state == ""`）：`from_states` 必须等于
    `OrderStatus 全集 − 实现里那道 status in (...) 挡板挡掉的状态`；
11. 反空转：CAS 站点数 ≥ `MIN_CAS_SITES`。

用法：python _tools/qa/_check_order_commands.py [--check]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "backend"))
import _domain_map as dm  # noqa: E402

MIN_COMMANDS = 9
MIN_CAS_SITES = 7

ORDER_FLOW = ROOT / "backend/app/services/order_flow.py"
API_DIR = ROOT / "backend/app/api"

UPDATE_ORDER_RE = re.compile(r"update\(Order\)")
CONSTRUCT_ORDER_RE = re.compile(r"(?<![A-Za-z_])Order\(")
STATUS_KW_RE = re.compile(r"status=OrderStatus\.(\w+)")
STATUS_EQ_RE = re.compile(r"Order\.status\s*==\s*OrderStatus\.(\w+)")
STATUS_IN_RE = re.compile(r"Order\.status\.in_\((\w+)\)")
TUPLE_VAR_RE = re.compile(r"(?m)^\s*(\w+)\s*=\s*\(([^)]*)\)")
BLOCKED_RE = re.compile(r"if\s+\w+\.status\s+in\s*\(([^)]*)\)")


def code_only(src: str) -> str:
    """去掉文档字符串与**整行**注释 —— 本仓库的老规矩：判据只看代码，不看注释。

    ⚠️ 为什么必须去：`order_flow.py` 的 `mark_returned` 注释里就写着
    「改之前这里是无条件赋值 order.status = OrderStatus.RETURNED」——
    不去注释的话，那条历史说明会被当成一次真的写入。
    """
    out = re.sub(r'(?s)""".*?"""', "", src)
    out = re.sub(r"(?s)'''.*?'''", "", out)
    out = re.sub(r"(?m)^\s*#.*$", "", out)
    return out


def cas_sites(src: str) -> list[tuple[frozenset[str], str]]:
    """把条件 UPDATE 读成 (前置状态集合, 目标状态)。

    ⚠️ 窗口取到**下一处** `update(Order)` 为止（找不到就给 2000 字符）——
    因为 `recall_dispatch` 的 `.values(` 与 `status=` 是**跨行**的，
    按行解析会把它整个漏掉（漏掉的后果是「少一条命令」那条判据永远绿）。
    """
    sites: list[tuple[frozenset[str], str]] = []
    for m in UPDATE_ORDER_RE.finditer(src):
        chunk = src[m.start(): m.start() + 2000]
        nxt = chunk.find("update(Order)", 10)
        if nxt > 0:
            chunk = chunk[:nxt]
        to_m = STATUS_KW_RE.search(chunk)
        if not to_m:
            continue
        froms: set[str] = set(STATUS_EQ_RE.findall(chunk))
        for var in STATUS_IN_RE.findall(chunk):
            froms |= _var_states(src, var, m.start())
        sites.append((frozenset(froms), to_m.group(1)))
    return sites


def _var_states(src: str, var: str, before_pos: int) -> set[str]:
    """解析 `Order.status.in_(allowed)` 里的 `allowed` —— 取**这一处之前最近的那次赋值**。

    ⚠️ 为什么要按位置就近解析（第一版建了一张全局变量表，当场被自己抓到）：
    `order_flow.py` 里 `allowed` 被赋值**两次** —— `cancel_pending` 是 `(待派单, 已派单)`、
    `recall_dispatch` 是 `(已派单, 已接单)`。全局表只留得下最后那一次，
    于是撤销的前置状态被判成了撤回的那一对，报出来的是「代码与声明对不上」——
    而这一次**错的是判据，不是代码**。赋值就在各自的 CAS 前面几行，就近解析才是真实语义。
    """
    pat = re.compile(r"(?m)^\s*" + re.escape(var) + r"\s*=\s*\(([^)]*)\)")
    hits = list(pat.finditer(src[:before_pos]))
    if not hits:
        return set()
    return set(re.findall(r"OrderStatus\.(\w+)", hits[-1].group(1)))


def construct_sites(src: str) -> list[str]:
    """把 `Order(… status=OrderStatus.X …)` 的 X 读出来（构造期状态）。"""
    out: list[str] = []
    for m in CONSTRUCT_ORDER_RE.finditer(src):
        # ⛔ `update(Order)` 里也含 `Order(`（前面是左括号，躲不过那个 lookbehind）——
        #    不排掉的话，条件 UPDATE 的 `status=…` 会被当成「构造期状态」，
        #    而那一条判据的本意是「**新建**订单时初始状态写在哪」。
        if src[max(0, m.start() - 7):m.start()] == "update(":
            continue
        chunk = src[m.start(): m.start() + 2500]
        nxt = CONSTRUCT_ORDER_RE.search(chunk, 6)
        if nxt:
            chunk = chunk[:nxt.start()]
        hit = STATUS_KW_RE.search(chunk)
        if hit:
            out.append(hit.group(1))
    return out


def main() -> int:
    check_mode = "--check" in sys.argv[1:]
    from app.commands.registry import ORDER_COMMANDS  # noqa: PLC0415
    from app.core.rbac import Permission  # noqa: PLC0415
    from app.models.enums import OrderStatus  # noqa: PLC0415

    fails: list[str] = []
    passed = 0
    blocks, _bad = dm.load_blocks()
    domain_names = {d.get("name", "") for d in blocks}
    owner_of = dm.owner_map(blocks)
    ev_owner = dm.event_owner_map(blocks)
    real_events = dm.real_events()
    tables = dm.real_tables()
    all_states = {s.name for s in OrderStatus}
    all_perms = {x.name for x in Permission}
    names = [c.name for c in ORDER_COMMANDS]

    # ---- 1. 注册表本身 ----------------
    if len(ORDER_COMMANDS) < MIN_COMMANDS:
        fails.append(f"只登记到 {len(ORDER_COMMANDS)} 条命令（<{MIN_COMMANDS}）—— 注册表缩水了？")
    else:
        passed += 1
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        fails.append("命令标识重复：" + "、".join(sorted(dup)))
    else:
        passed += 1
    thin = [c.name for c in ORDER_COMMANDS if len(c.why.strip()) < 12]
    if thin:
        fails.append("这些命令没写「为什么它是一条独立命令」：" + "、".join(thin))
    else:
        passed += 1

    # ---- 2/3/4/5/6/7. 每条命令的字段都对得上吗 ----------------
    before = len(fails)
    for c in ORDER_COMMANDS:
        why = dm.command_problem(c.impl)
        if why:
            fails.append(f"命令 {c.name} 的实现对不上代码：{why}")
        if c.domain not in domain_names:
            fails.append(f"命令 {c.name} 的归属域 {c.domain} 不在地图上")
        if c.domain == "order" and not c.impl.startswith(("services.order_flow:", "commands.order:")):
            fails.append(f"命令 {c.name} 声称属于订单域，但实现既不在 order_flow 也不在 commands.order：{c.impl}")
        for cap in c.capabilities:
            if cap not in all_perms:
                fails.append(f"命令 {c.name} 的权限点 {cap} 不是 Permission 的成员")
        for st in list(c.from_states) + ([c.to_state] if c.to_state else []):
            if st not in all_states:
                fails.append(f"命令 {c.name} 引用了不存在的订单状态 {st}")
        for ev in c.events:
            if ev not in real_events:
                fails.append(f"命令 {c.name} 声称会发事件 {ev}，但代码里没有任何 enqueue 产生它")
            elif ev not in ev_owner:
                fails.append(f"命令 {c.name} 的事件 {ev} 没有域认领（没人负责的事实）")
        for eff in c.effects:
            if eff not in tables:
                fails.append(f"命令 {c.name} 的副作用表 {eff} 不存在")
            elif owner_of.get(eff) == c.domain:
                fails.append(f"命令 {c.name} 把本域的表 {eff} 写进 effects —— effects 只登记跨域写")
    if len(fails) == before:
        passed += 1

    # ---- 8. ⭐ CAS 对账 ----------------
    src = code_only(ORDER_FLOW.read_text(encoding="utf-8"))
    code_sites = cas_sites(src)
    declared = [(frozenset(c.from_states), c.to_state) for c in ORDER_COMMANDS
                if c.to_state and c.impl.startswith("services.order_flow:")]
    if len(code_sites) < MIN_CAS_SITES:
        fails.append(f"order_flow 里只读到 {len(code_sites)} 处条件 UPDATE（<{MIN_CAS_SITES}）—— 解析可能坏了")
    else:
        passed += 1
    only_code = [x for x in code_sites if x not in declared]
    only_decl = [x for x in declared if x not in code_sites]
    for f, t in only_code:
        fails.append(f"代码里有一处条件 UPDATE 没被任何命令声明：{sorted(f)} → {t}")
    for f, t in only_decl:
        fails.append(f"注册表声明了一处代码里不存在的跃迁：{sorted(f)} → {t}")
    if not only_code and not only_decl:
        passed += 1

    # ---- 9. ⭐ 构造期状态：必须是某条命令的 to_state；API 层一处都不许有 ----------------
    targets = {c.to_state for c in ORDER_COMMANDS if c.to_state}
    api_hits: list[str] = []
    bad_construct: list[str] = []
    for f in sorted((ROOT / "backend/app").rglob("*.py")):
        text = code_only(f.read_text(encoding="utf-8"))
        found = construct_sites(text)
        if not found:
            continue
        rel = str(f.relative_to(ROOT))
        if API_DIR in f.parents:
            api_hits.append(rel + "：" + str(found))
        for st in found:
            if st not in targets:
                bad_construct.append(rel + " 写了 " + st)
    if api_hits:
        fails.append("⛔ api/ 层直接构造订单并写状态（指南 §十九 的退出条件是「API 不直接改变 order.status」）："
                     + "；".join(api_hits))
    else:
        passed += 1
    if bad_construct:
        fails.append("这些构造期状态不是任何命令的 to_state：" + "；".join(bad_construct))
    else:
        passed += 1

    # ---- 9b. 地图与注册表必须互相指得到 ----------------
    order_block = next((d for d in blocks if d.get("name") == "order"), None)
    map_cmds = set(dm.split_list(order_block.get("commands", ""))) if order_block else set()
    before = len(fails)
    if not order_block:
        fails.append("地图里找不到订单域（docs/DOMAIN_BOUNDARIES.md 被改坏了？）")
    for c in ORDER_COMMANDS:
        if c.impl not in map_cmds:
            fails.append(f"命令 {c.name} 的实现 {c.impl} 不在地图的订单域 commands 行里 —— "
                         "归属与形状必须两处都在")
    for ref in sorted(map_cmds):
        if ref.startswith("commands.order:") and ref not in {c.impl for c in ORDER_COMMANDS}:
            fails.append(f"地图的订单域声明了 {ref}，但命令注册表里没有它 —— 形状漏了一条")
    if len(fails) == before:
        passed += 1

    # ---- 10. 不改状态的命令：前置 = 全集 − 实现里挡掉的 ----------------
    before = len(fails)
    for c in ORDER_COMMANDS:
        if c.to_state:
            continue
        path = dm.impl_path(c.impl)
        body = code_only(path.read_text(encoding="utf-8")) if path else ""
        fn = c.impl.partition(":")[2]
        i = body.find("def " + fn + "(")
        body = body[i:] if i >= 0 else ""
        blocked: set[str] = set()
        for m in BLOCKED_RE.finditer(body):
            blocked |= set(re.findall(r"OrderStatus\.(\w+)", m.group(1)))
        if not blocked:
            fails.append(f"命令 {c.name} 声明了前置状态，但实现里找不到那道 status in (...) 挡板")
            continue
        expect = all_states - blocked
        if set(c.from_states) != expect:
            fails.append(f"命令 {c.name} 的前置状态与实现不符：声明 {sorted(c.from_states)} / 实现允许 {sorted(expect)}")
    if len(fails) == before:
        passed += 1

    print(
        f"订单命令：{len(ORDER_COMMANDS)} 条命令 / order_flow 里 {len(code_sites)} 处条件 UPDATE / "
        f"{len(targets)} 个构造期目标状态 / API 层直写状态 {len(api_hits)} 处"
    )
    if fails:
        for f in fails:
            print("  ❌ " + f)
        return 1
    if check_mode:
        print("  ✅ 全部通过")
    else:
        print(f"  ✅ {passed} 组判据全部通过：声明与代码逐条对得上（跃迁 / 构造期状态 / 权限 / 事件 / 跨域副作用），"
              "且 API 层一处都没有直接写订单状态。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
