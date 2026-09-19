"""红线：**权限点要么被真正使用，要么有一条写清理由的说明**（2026-09-19 审计 F8）。

## 由来
`core/rbac.py` 里声明了 24 个权限点，但其中 5 个（`ORDER_READ_OWN` / `ORDER_READ_ASSIGNED` /
`LEDGER_READ_OWN` / `LEDGER_READ_ALL` / `NOTIFICATION_READ`）**从来没有被任何端点用过** ——
读侧的真实判据是端点体内内联的 `user_role_key(current)`（行级规则一个权限点表达不了）。

后果不是"少了个功能"，而是**一个会静默失效的错觉**：
- 改 `ROLE_PERMISSIONS`（比如把 `LEDGER_READ_ALL` 从派单员那儿去掉）**不改变任何行为**；
- 而 `docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md` 的"权限:"列与 AI 读能力目录
  （`AiReadCatalog` 的 roles）**都是从这张矩阵推导的** → 文档说"没权限"、接口照样能读；
- 下一个接手的人会照着矩阵去改，然后发现"改了没用"。

## 判据（清单自己算）
1. 从 `core/rbac.py` 解析出所有权限点（`Permission` 枚举成员名）；
2. 在 `backend/app/**/*.py`（**排除 rbac.py 自己**）里找引用：`Permission.<名>`
   或字符串字面量；
3. 没有被引用的 → 必须出现在下面的 [DECLARED_ONLY] 里，**每条写清"为什么声明了却不用"**；
4. 三条反化石/反空转：表里的键必须还是真权限点；表不许变长（>6 就报错）；
   权限点总数不少于 20（解析失效时先喊，而不是安静地什么都不查）。

用法：python _tools/qa/_check_permission_points.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend/app"
RBAC = BACKEND / "core/rbac.py"

#: 声明了但没有任何 `require_permission` 在用的权限点 → **理由**。
#: 每条都要回答："那读侧到底靠什么判？改了矩阵会发生什么？"
DECLARED_ONLY: dict[str, str] = {
    "ORDER_READ_OWN":
        "读侧由 `orders.py` 端点体内内联判断（货主只看自己的）；权限点表达不了行级规则",
    "ORDER_READ_ASSIGNED":
        "同上：司机的 `_get_order_scoped` 按 driver_id 判，不用矩阵",
    "LEDGER_READ_OWN":
        "`ledger.py::list_entries` 内联判角色与 shipper_id",
    "LEDGER_READ_ALL":
        "同上（派单员看全部）；⚠️ 把它从派单员矩阵里去掉**不会**改变行为",
    "NOTIFICATION_READ":
        "`notifications.py` 的列表/已读/删除全部内联判 recipient_id",
}

MAX_DECLARED_ONLY = 6
MIN_POINTS = 20


def main() -> int:
    fails: list[str] = []
    src = RBAC.read_text(encoding="utf-8")
    points = re.findall(r"^    ([A-Z][A-Z0-9_]*)\s*=\s*\"", src, re.M)
    print(f"权限点 {len(points)} 个")

    if len(points) < MIN_POINTS:
        print(f"❌ 只解析出 {len(points)} 个权限点（<{MIN_POINTS}）——解析失效，停。")
        return 1

    others = "".join(
        f.read_text(encoding="utf-8") for f in sorted(BACKEND.rglob("*.py")) if f.name != "rbac.py"
    )
    unused = [p for p in points if f"Permission.{p}" not in others and f'"{p}"' not in others]
    print(f"没有被任何端点/服务引用的 {len(unused)} 个：{'、'.join(unused) if unused else '（无）'}")

    unexplained = [p for p in unused if p not in DECLARED_ONLY]
    if unexplained:
        fails.append(
            "这些权限点声明了却没有任何 `require_permission` 在用，也没有书面理由"
            "（改矩阵会静默无效）：" + "、".join(unexplained)
        )

    fossils = [p for p in DECLARED_ONLY if p not in points]
    if fossils:
        fails.append("说明表里挂着已经不是权限点的条目（化石）：" + "、".join(fossils))

    used_already = [p for p in DECLARED_ONLY if p not in unused]
    if used_already:
        fails.append(
            "这些权限点**已经**被引用了，却还挂在『只声明不用』的表里（说明过期）："
            + "、".join(used_already)
        )

    if len(DECLARED_ONLY) > MAX_DECLARED_ONLY:
        fails.append(
            f"『只声明不用』的权限点有 {len(DECLARED_ONLY)} 个（上限 {MAX_DECLARED_ONLY}）——"
            "变长说明又多了没人管的权限点，请先问清楚它为什么不接线"
        )

    if fails:
        print("\n❌ 权限点与实现走散了：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ {len(points)} 个权限点都有交代（{len(points) - len(unused)} 个在用、"
          f"{len(unused)} 个有书面理由）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
