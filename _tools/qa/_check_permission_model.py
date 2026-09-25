#!/usr/bin/env python3
"""_check_permission_model.py —— 权限模型的三维与例外（进 `_check_all.py` 自动跑）。

### 为什么需要它（报告 §9）
报告要的是 `User → Role → Permission → Action → Resource → Scope`，
而项目原来的形态是「RBAC 矩阵 + `require_permission` + `require_roles` + **函数体内联判断** + 行级过滤」——
`rbac.py` 自己的 docstring 把它的病写得很清楚：

> 改 `ROLE_PERMISSIONS`（比如把 `LEDGER_READ_ALL` 从派单员那儿去掉）**不会**改变任何端点的行为，
> 而端点索引的权限列与 AI 读能力目录又是从这张矩阵推导的 → 文档说「没权限了」、接口照样能读。

本轮补的是**模型的那三维**（Action / Resource / Scope）与**显式的例外声明**；
这一条判据负责让它们不会悄悄退化。

### 判据
1. 每个权限点的值都能拆成 `resource:action`（不写第二份映射表，就靠这条形状）；
2. 每个权限点都有 Scope 声明，取值合法、理由非空且够长（26 个一个不少）；
3. `BYPASS_ROLES` 每条都要写**什么时候删掉它**，而且**必须仍然命中**（不命中＝化石）；
4. ⛔ `role_has_permission` 的函数体里**不许再出现硬编码的角色名比较** ——
   例外只能住在 `BYPASS_ROLES` 里（行为不变，但从「读代码猜」变成「查表」）。

用法：python _tools/qa/_check_permission_model.py [--check]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
RBAC = ROOT / "backend/app/core/rbac.py"
MIN_PERMS = 26
MIN_REASON = 12


def body_of(src: str, header: str) -> str:
    """从 `header` 那一行开始，切到下一个顶层 `def` / `class` 之前（够用即可）。"""
    i = src.find(header)
    if i < 0:
        return ""
    j = len(src)
    for m in re.finditer(r"(?m)^(def |class |[A-Z_]+[:=])", src[i + len(header):]):
        j = i + len(header) + m.start()
        break
    return src[i:j]


def main() -> int:
    check_mode = "--check" in sys.argv[1:]
    sys.path.insert(0, str(ROOT / "backend"))
    from app.core.rbac import BYPASS_ROLES, SCOPES, SCOPE_KINDS, Permission, role_has_permission  # noqa: PLC0415

    src = RBAC.read_text(encoding="utf-8")
    src = re.sub(r"(?m)^\s*#.*$", "", src)          # 判据只看代码，不看注释（本仓库的血泪规矩）
    fails: list[str] = []
    passed = 0

    perms = list(Permission)
    if len(perms) < MIN_PERMS:
        fails.append(f"只数到 {len(perms)} 个权限点（<{MIN_PERMS}）—— 判据可能空转了")
    else:
        passed += 1

    # ---- 1. resource:action 的形状（不写第二份映射表就靠它）----
    bad_shape = []
    for p in perms:
        if p.value.count(":") != 1:
            bad_shape.append(f"{p.name}={p.value!r}")
        else:
            res, act = p.value.split(":")
            if not res or not act:
                bad_shape.append(f"{p.name}={p.value!r}")
    if bad_shape:
        fails.append("这些权限点的值不是 `resource:action` 的形状（资源/动作分不清）：" + "、".join(bad_shape))
    else:
        passed += 1

    # ---- 2. Scope 一个不少、取值合法、理由够长 ----
    missing = [p.name for p in perms if p not in SCOPES]
    if missing:
        fails.append("这些权限点没有 Scope 声明（报告 §9 要的就是这一维）：" + "、".join(missing))
    else:
        passed += 1
    bad_kind = [f"{p.name}={k}" for p, (k, _) in SCOPES.items() if k not in SCOPE_KINDS]
    if bad_kind:
        fails.append("Scope 取值不在 SCOPE_KINDS 里：" + "、".join(bad_kind))
    else:
        passed += 1
    thin = [p.name for p, (_, why) in SCOPES.items() if len(why.strip()) < MIN_REASON]
    if thin:
        fails.append(f"这些 Scope 的理由太短（<{MIN_REASON} 字，等于没写）：" + "、".join(thin))
    else:
        passed += 1
    extra = [p.name for p in SCOPES if p not in perms]
    if extra:
        fails.append("SCOPES 里有已经不存在的权限点（化石）：" + "、".join(extra))
    else:
        passed += 1

    # ---- 3. 例外表：理由要写「什么时候删」，且必须命中 ----
    if not BYPASS_ROLES:
        fails.append("BYPASS_ROLES 是空的 —— 如果没有例外，就该把这段机制删掉，而不是留一张空表")
    for role, why in BYPASS_ROLES.items():
        if "删掉这一条" not in why:
            fails.append(f"BYPASS_ROLES[{role!r}] 没写「什么时候删掉这一条」")
        if len(why.strip()) < 60:
            fails.append(f"BYPASS_ROLES[{role!r}] 的理由太短（<60 字）")
        # 必须**真的命中**：换个角色名它就不再生效 → 化石
        from app.core.rbac import Permission as P  # noqa: PLC0415

        probe = next(iter(P))
        if not role_has_permission(role, probe) or role_has_permission("shipper_" + role, probe):
            fails.append(f"BYPASS_ROLES[{role!r}] 没有命中（改过名字？）—— 例外表成了化石")
    if not fails:
        passed += 1

    # ---- 4. ⛔ 函数体里不许再硬编码角色名 ----
    body = body_of(src, "def role_has_permission(")
    if "key in BYPASS_ROLES" not in body:
        fails.append("role_has_permission 没有走 BYPASS_ROLES —— 例外又回到函数体里了")
    elif re.search(r"==\s*UserRole\.", body) or re.search(r"UserRole\.[A-Z_]+(\.value)?\s*==", body):
        fails.append("role_has_permission 里又出现了硬编码的角色名比较 —— 例外只能住在 BYPASS_ROLES 里")
    else:
        passed += 1

    print(f"权限模型：{len(perms)} 个权限点 / {len(SCOPES)} 条 Scope / {len(BYPASS_ROLES)} 条例外角色")
    if fails:
        for f in fails:
            print("  ❌ " + f)
        return 1
    print(f"  ✅ {passed} 组判据全部通过：resource:action 的形状齐全、26 个 Scope 都有理由、"
          "例外住在表里（可审计、可化石检测）、函数体里没有硬编码角色名。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())