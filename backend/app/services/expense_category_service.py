"""开销分类名册的**领域服务**（第二轮 R2-03：把依赖方向掰回来）。

## 为什么这个函数要从路由里搬出来
它原来住在 `api/v1/expense_categories.py` 里，而**唯一的另一个调用方是** `services/accounting_service.py` ——
于是 `services/` 反过来 import 了 `app.api.v1`：

```text
  accounting_service（钱的落库） ──import──▶ app.api.v1.expense_categories（HTTP 路由）
```

方向是反的。指南 §十七.3 的判据说得直白：「**能不能通过改变依赖方向解决，而不是增加一个检查器？**」
「新建开销时分类名自动补进名册」是**业务规则**，不是 HTTP 的事 —— 它属于服务层。
搬过来之后依赖变成单向：`api → services` 与 `services → services`，
而 `_tools/qa/_check_money_dependency.py` 会把「services 不许 import api」钉成一条 **0 例外** 的规则。

## 口径一个字没改
函数体是从 `api/v1/expense_categories.py` 原样搬来的（含那句「返回被新建的名册行」的约定）。
⛔ 这是**移动**，不是重写：搬完路由与开销单两条路径调的还是同一个函数（判据 `_check_expense_page.py` 钉着调用点）。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ExpenseCategory


def next_sort(db: Session) -> int:
    """名册里的下一个排序号（追加到最后）。

    ⚠️ 名字从 `_next_sort` 改成 `next_sort` 是**跨模块**取用的必然结果：
    下划线开头的名字按约定是模块私有，而路由那边（`POST /expense-categories` 不传 sort_order 时）要用它。
    """
    top = db.scalar(select(func.max(ExpenseCategory.sort_order)))
    return (top or 0) + 1


def ensure_category(db: Session, name: str, link_kind: str = "none") -> ExpenseCategory | None:
    """确保这个分类名在名册里（不在就补到最后）。给新开销复用。

    返回被新建的名册行；已经在名册里则返回 None（调用方据此决定要不要记日志）。
    """
    clean = (name or "").strip()[:32]
    if not clean:
        return None
    exists = db.scalars(select(ExpenseCategory).where(ExpenseCategory.name == clean)).first()
    if exists is not None:
        return None
    row = ExpenseCategory(name=clean, sort_order=next_sort(db), link_kind=link_kind or "none")
    db.add(row)
    db.flush()
    return row
