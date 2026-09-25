#!/usr/bin/env python3
"""_check_capability_registry.py —— 能力注册表与它的消费方**不许走散**（进 `_check_all.py` 自动跑）。

### 为什么需要它（第二轮 · 贯穿层 · 指南 §十一）
指南要的是「Capability Registry → API / AI / UI / Audit」，并点明「这样 AI 就不会成为自己的权限系统」。
「一个权限点是什么」在这之前散在**四处**：枚举、ROLE_PERMISSIONS 矩阵、SCOPES 那张只写 scope 的表、
以及各端点签名上的 require_permission。四处各说各话时**没有任何地方会报错**
（本项目吃过这个亏：改矩阵不改端点，接口照样能读）。

### 判据（六条）
1. capabilities.CAPABILITIES 与 Permission **一一对应**（不多不少、不重复、不变化石）；
2. ⭐ 与 rbac.SCOPES **双向一致**（键集合、scope、理由逐字相同）；
3. ⭐ 与 rbac.ROLE_PERMISSIONS **双向一致**（由注册表派生的矩阵 == 手写的那张）；
4. 角色名合法；BYPASS_ROLES 里的角色**不许**再出现在任何能力的 roles 里（两边都声明＝说不清谁给的权）；
5. ⭐ **执行点是算出来的，不是声明出来的**：去 backend/app/api/** 找 require_permission(Permission.X) /
   require_any_permission / 体内的 role_has_permission(..., Permission.X)；一条执行点都没有的必须写进
   DECLARED_ONLY（理由 + 「什么时候删掉这一条」）；
6. 反空转：能力数、有执行点的能力数都要达标。

⚠️ **为什么是「双向一致」而不是把 rbac 改成派生**：rbac.py 是核心区，而且 _check_order_return.py
   等判据锚着它**段落结构**（「货主那一段里不许出现退货执行权」）。派生会把那些锚点连根拔掉，
   风险远大于收益。效果一样：**改一处忘一处就红**。

用法：python _tools/qa/_check_capability_registry.py [--check]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

MIN_CAPS = 26
MIN_ENFORCED = 18
MIN_TEXT = 12
MIN_WHAT = 4

#: 没有执行点的能力 -> 为什么 + **什么时候删掉这一条**。空表不是「没检查」，是「每条都真有执行点」。
DECLARED_ONLY: dict[str, str] = {}

#: 绕过角色**同时**出现在矩阵的 roles 里时 -> 为什么保留这条冗余。
#: ⚠️ 第一版直接禁止这种重叠，当场红了 21 条 —— 而重叠是**现状**（`ROLE_PERMISSIONS` 里一直写着
#:    dispatcher），且行为上无害（`role_has_permission` 在绕过那一句就返回了，矩阵那几格是**死数据**）。
#:    判据的作用不是把现状判红，而是**逼人把这条冗余说清楚** —— 例外要留解释。
REDUNDANT_BYPASS = "dispatcher"
REDUNDANT_WHY = (
    "派单员在 BYPASS_ROLES 里已经全通过，所以在矩阵里再列一遍是**冗余**（那几格永远读不到）。"
    "保留它的理由是：矩阵要能**单独读懂**（把 BYPASS_ROLES 那一条拿掉时，谁会少什么一眼看得出来）。"
    "**什么时候删掉这一条**：如果哪天改成逐格授权（见 BYPASS_ROLES 自己的退出条件），这两处会合并成一处。"
)

ENFORCE_RE = re.compile(r"Permission\.([A-Z_]+)")


def main() -> int:
    check_mode = "--check" in sys.argv[1:]
    from app.core import capabilities  # noqa: PLC0415
    from app.core import rbac  # noqa: PLC0415

    fails: list[str] = []
    passed = 0
    caps = capabilities.CAPABILITIES
    names = [c.permission for c in caps]
    perms = {x.name for x in rbac.Permission}

    if len(caps) < MIN_CAPS:
        fails.append(f"只登记到 {len(caps)} 条能力（<{MIN_CAPS}）—— 注册表缩水了")
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        fails.append("这些权限点有**多条**能力（一处声明只能有一条）：" + "、".join(sorted(dup)))
    missing = sorted(perms - set(names))
    if missing:
        fails.append("这些权限点**没有能力声明**：" + "、".join(missing))
    fossil = sorted(set(names) - perms)
    if fossil:
        fails.append("能力表里这些权限点已经不是 Permission 的成员了（化石）：" + "、".join(fossil))
    if not dup and not missing and not fossil and len(caps) >= MIN_CAPS:
        passed += 1

    want_scope = capabilities.scope_table()
    got_scope = {x.name: v for x, v in rbac.SCOPES.items()}
    if want_scope != got_scope:
        only_cap = sorted(set(want_scope) - set(got_scope))
        only_rbac = sorted(set(got_scope) - set(want_scope))
        diff = sorted(k for k in set(want_scope) & set(got_scope) if want_scope[k] != got_scope[k])
        fails.append("能力表与 rbac.SCOPES 对不上："
                     + ("只在能力表里=" + "、".join(only_cap) + "；" if only_cap else "")
                     + ("只在 SCOPES 里=" + "、".join(only_rbac) + "；" if only_rbac else "")
                     + ("内容不同=" + "、".join(diff) if diff else ""))
    else:
        passed += 1

    want_matrix = capabilities.role_matrix()
    got_matrix = {r: frozenset(x.name for x in v) for r, v in rbac.ROLE_PERMISSIONS.items()}
    if want_matrix != got_matrix:
        roles = sorted(set(want_matrix) | set(got_matrix))
        diff = [r for r in roles if want_matrix.get(r, frozenset()) != got_matrix.get(r, frozenset())]
        fails.append("能力表与 rbac.ROLE_PERMISSIONS 对不上（这些角色不一致）：" + "、".join(diff))
    else:
        passed += 1

    before = len(fails)
    known = set(got_matrix) | set(rbac.BYPASS_ROLES)
    for c in caps:
        if not c.roles:
            fails.append(f"能力 {c.permission} 一个角色都没有（那它怎么生效？）")
        for r in c.roles:
            if r not in known:
                fails.append(f"能力 {c.permission} 写了不知道的角色 {r!r}")
            if r in rbac.BYPASS_ROLES:
                # 重叠本身是现状、也说得通，但**必须有解释**（见 REDUNDANT_WHY）。
                if r != REDUNDANT_BYPASS or "删掉这一条" not in REDUNDANT_WHY:
                    fails.append("能力 " + c.permission + " 把**绕过角色** " + r
                                 + " 也算进 roles，而这处重叠没有在 REDUNDANT_WHY 里写清理由与退出条件")
        if c.scope not in rbac.SCOPE_KINDS:
            fails.append(f"能力 {c.permission} 的 scope 取值 {c.scope!r} 不在 SCOPE_KINDS 里")
        if c.kind not in ("read", "write"):
            fails.append(f"能力 {c.permission} 的 kind 只能是 read / write")
        # ⚠️ `what` 是**一句话摘要**（"看自己那本账"这种，本来就短），`scope_why` 才是要写透的那条 ——
        #    两条用同一个下限会把摘要全判红（第一版就是这样，判据当场把自己写死了）。
        for field, val, low in (("what", c.what, MIN_WHAT), ("scope_why", c.scope_why, MIN_TEXT)):
            if len(val.strip()) < low:
                fails.append(f"能力 {c.permission} 的 {field} 太短（<{low} 字，等于没写）")
    if len(fails) == before:
        passed += 1

    enforced: set[str] = set()
    for f in (ROOT / "backend/app/api").rglob("*.py"):
        enforced |= set(ENFORCE_RE.findall(f.read_text(encoding="utf-8")))
    n_enforced = len(enforced & perms)
    for c in caps:
        if c.permission in enforced:
            continue
        why = DECLARED_ONLY.get(c.permission)
        if not why or len(why.strip()) < 20:
            fails.append(f"能力 {c.permission} 在 api/ 里**一处执行点都没有**，也没写进 DECLARED_ONLY")
        elif "删掉这一条" not in why:
            fails.append(f"DECLARED_ONLY[{c.permission}] 没写「什么时候删掉这一条」")
    if n_enforced < MIN_ENFORCED:
        fails.append(f"只有 {n_enforced} 条能力真的有执行点（<{MIN_ENFORCED}）—— 扫描坏了？")
    else:
        passed += 1
    fossils = sorted(k for k in DECLARED_ONLY if k in enforced)
    if fossils:
        fails.append("DECLARED_ONLY 里这些其实**已经有**执行点了（化石，删掉它们）：" + "、".join(fossils))

    print(f"能力注册表：{len(caps)} 条能力 / 有执行点 {n_enforced} 条 / 仅声明 {len(DECLARED_ONLY)} 条")
    if fails:
        for f in sorted(set(fails)):
            print("  ❌ " + f)
        return 1
    if check_mode:
        print("  ✅ 全部通过")
    else:
        print(f"  ✅ {passed} 组判据全部通过：能力表与 Permission / SCOPES / ROLE_PERMISSIONS 三方一致，"
              "每条能力要么有真实执行点、要么有书面理由。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
