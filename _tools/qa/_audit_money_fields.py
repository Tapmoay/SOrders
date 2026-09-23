"""静态审计：**钱相关字段能不能存进数据库**（判据与后端同源，不另抄一份）。

## 为什么要它
契约模糊测试把 `1e20` 喂给金额字段，实测：
- `POST /driver-billing-rules {"salary": 1e20}` → 201（工资 1e20 真的建出来了）
- `POST /expenses {"amount": 1e20}` → 200；`POST /freight-templates {"fee": 1e20}` → 201
- `POST /price-rules/batch {"value": 1e20}` → 200（一次把 2880 条专属价改成天文数字）

金额列是 `Numeric(12,2)` / `Numeric(14,4)`，上限 9,999,999,999.99：生产 MySQL 会
`Out of range` 报错，本地 SQLite 却照单全收 —— **"本地全绿、上线报错"的典型**。

## 判据（唯一来源）
`app.schemas.money` 里的 `MONEY_RE` / `NOT_MONEY` / `MONEY_MAX`：
凡是被它判定为"钱"的入参字段，该模型必须继承 `MoneyInput`（或字段自己带 `le=`）。
**不在这里再写一份字段清单**——两份清单一定会走散。

用法：
```
python _tools/qa/_audit_money_fields.py          # 有缺口就非零退出（可挂 CI）
python _tools/qa/_audit_money_fields.py --all    # 连已保护的字段一起打印
```
"""
from __future__ import annotations

import os
import sys
import typing
from decimal import Decimal
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
# 审计是只读的：把 DB 指到临时文件，避免顺手在仓库里建出 app.db
os.environ.setdefault("DATABASE_URL", "sqlite:///" + str(Path(os.environ.get("TEMP", "/tmp")) / "_audit_money.db"))
sys.path.insert(0, str(BACKEND))

from annotated_types import Le, Lt  # noqa: E402

import app.main  # noqa: E402,F401  —— 导入真正的 app，让审计看到"应用实际注册的"全部模型
from app.schemas.money import MONEY_RE, NOT_MONEY, MoneyInput  # noqa: E402
from pydantic import BaseModel  # noqa: E402

INPUT_SUFFIX = ("Create", "Update", "Body", "In", "Request", "Patch", "Param")


def all_models() -> list[type[BaseModel]]:
    seen: set[type[BaseModel]] = set()
    stack = list(BaseModel.__subclasses__())
    while stack:
        m = stack.pop()
        if m in seen:
            continue
        seen.add(m)
        stack.extend(m.__subclasses__())
    return sorted(seen, key=lambda c: c.__name__)


def scalar_types(ann: object) -> set[object]:
    out: set[object] = set()
    for arg in typing.get_args(ann) or (ann,):
        out |= scalar_types(arg) if typing.get_args(arg) else {arg}
    return out


def main() -> int:
    # ⛔ `--check` = **进必跑清单的凭据**（2026-09-23 第 18 轮补）。
    #    `_tools/qa/_check_all.py` 的清单是**自己算**的：`_check_*.py` 或任何声明了 `--check` 的脚本。
    #    本脚本名字是 `_audit_*` 又没有 `--check` —— 于是它**一直不在必跑清单里**，
    #    而它报的两条（`RuleCategoryIn.piece_amount` / `MovementCreate.unit_cost` 无上界）
    #    就这样在眼皮底下躺了整轮：**能抓到缺陷的检查没人跑 = 没有检查**。
    #    子代理 B2/B12 都是先手动跑了它才发现"它早就能报红"。
    show_all = "--all" in sys.argv
    check = "--check" in sys.argv
    gaps: list[str] = []
    protected: list[str] = []
    for model in all_models():
        if not any(model.__name__.endswith(s) for s in INPUT_SUFFIX):
            continue
        inherits = issubclass(model, MoneyInput)
        for name, field in model.model_fields.items():
            if name in NOT_MONEY or not MONEY_RE.search(name):
                continue
            if not (scalar_types(field.annotation) & {Decimal, int, float}):
                continue
            has_own_bound = any(isinstance(m, (Le, Lt)) for m in field.metadata)
            where = f"{model.__module__.split('.')[-1]}.{model.__name__}.{name}"
            (protected if (inherits or has_own_bound) else gaps).append(where)

    total = len(gaps) + len(protected)
    if check and not show_all:
        # 必跑模式下只印结论一行（`_check_all.py` 会把每个脚本的输出收进一张表，
        # 39 行字段清单会把别的检查挤出屏幕）
        print(
            f"{'✅' if not gaps else '❌'} 金额入参字段 {total} 个，其中 {len(gaps)} 个没有上界"
            + ("" if not gaps else "："
               + "、".join(g.split(".")[-1] for g in gaps[:3])
               + ("…" if len(gaps) > 3 else ""))
        )
        return 2 if gaps else 0
    print(f"金额语义的入参字段 {total} 个（模型清单由 pydantic 自己算，不手写）")
    if show_all:
        for w in protected:
            print(f"  ✓ {w}")
    print(f"\n没有上界的 {len(gaps)} 个：")
    for w in gaps:
        print(f"  ✗ {w}  ← 该模型应继承 MoneyInput（或字段加 le=）")
    if not gaps:
        print("  （无）")
    return 2 if gaps else 0


if __name__ == "__main__":
    sys.exit(main())
