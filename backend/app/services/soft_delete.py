"""软删派生值：`原值 + _del{id}`，**并且保证不超过列宽**。

2026-09-19 审计（G4）：软删（"伪装删除"）要把唯一列改成一个不再冲突的值，号码/名字才能释放
给新记录用。三处都在拼 `f"{原值}_del{id}"`，而只有 `users.username` 做了截断 ——
本机 SQLite **不校验 VARCHAR 长度**（永远绿），生产 MySQL 报 `Data too long`，
再被 `main.py` 的处理器翻成**"填写的内容超出可保存范围"**：用户什么都没填，只是点了删除。

所以：**凡是要往一个定宽列里写"原值＋后缀"，都必须过这里**。
"""

from __future__ import annotations

import re

from fastapi import HTTPException

#: `_del` + 纯数字，**只认结尾**（见 [strip_del_suffix]）。
_DEL_TAIL = re.compile(r"_del\d+$")


def del_suffix(original: str | None, row_id: int, width: int) -> str:
    """返回 `原值_del{id}`，总长不超过 `width`（后缀本身太长时也不截断后缀）。

    `width` 传**列宽**（`String(32)` 就传 32）。留一点余量不需要我们自己算——
    后缀长度是确定的，直接从基值里扣。
    """
    base = (original or "").strip()
    suffix = f"_del{int(row_id)}"
    keep = max(0, int(width) - len(suffix))
    return base[:keep] + suffix


def strip_del_suffix(value: str | None) -> str:
    """[del_suffix] 的逆运算：`13800001234_del160` → `13800001234`。

    只用于**展示**（2026-09-19：账本仪表盘要显示货主手机号，把带后缀的号码给用户看
    等于给了一个打不通的号）。

    ⚠️ **不要拿它去库里查**：库里那一列存的就是带后缀的值（"删除"正是这么实现的），
       用去尾后的值做等值查询**永远查不到那一行**。
    ⚠️ 只从**末尾**去掉 `_del` + 纯数字：写"见到 `_del` 就切"会把合法值截断，
       而这里的输入是用户可见的号码/姓名，截错了没人看得出是代码错还是数据错。
    """
    return _DEL_TAIL.sub("", (value or "").strip())


def dialable_phone(user) -> str | None:
    """这个账号的**可拨号码**（`None` = 别给拨号入口）。

    ## 三种情形（2026-09-24 第 20 轮并行渗透 D9-F3）
    | 账号状态 | 库里的值 | 该显示什么 |
    | --- | --- | --- |
    | 活着、号码没有后缀 | `13800001234` | 原号码 |
    | **软删**（号码被让出去了） | `13800001234_del160` | **去掉后缀**：历史订单上还要看得出"这单是谁拉的" |
    | **活着、却带后缀**（恢复时撞号） | `13800001234_del160` | **不给号码** |

    最后一行是本函数存在的理由：那种账号是"恢复回来时号码已经被别人抢走"的产物
    （`api/v1/users.py::restore_user` 保留后缀、只恢复身份）。此时 `strip_del_suffix`
    去尾得到的 `13800001234` 是**别人的号码** —— 订单详情上那颗拨号键会打给
    一个与这一单毫无关系的人。宁可没有号码，也不能给一个错的号码。
    """
    raw = (getattr(user, "phone", None) or "").strip()
    if not raw:
        return None
    if _DEL_TAIL.search(raw) and getattr(user, "is_active", True):
        return None
    return strip_del_suffix(raw) or None


def ensure_alive(row, what: str, restore_hint: str) -> None:
    """这一行是不是**已经进了回收站**；是就 400 拒绝，并把"怎么恢复"写清楚。

    2026-09-19 审计（R11-F4）：软删的资源里，`GET` 列表全都过滤了 `is_deleted`，
    `DELETE`/`restore` 也都查了标记，**唯独"改"这条路漏了几处**——
    `PUT /freight-templates/{id}`、`PATCH /arrears/units/{id}`、`PATCH /price-rules/{id}`、
    `POST /shipper/addresses/{id}/set-default` 都能改到已经删掉（界面上看不见）的行，
    而且**返回 200**：用户（和 AI 助手）看到的是「已完成」，列表里却什么都找不到；
    更糟的是它会让"删除"这个动作失去意义——`delete_address` 特意把 `is_default` 置 false
    防止默认标记留在看不见的行上，`set-default` 又能把它设回去。

    用法：`ensure_alive(t, "运费模板", "POST /freight-templates/{id}/restore")`。
    404 还是 400？——**用 400 而不是 404**：这条记录确实存在（在回收站里），
    说"未找到"会让用户以为编号错了，而他要做的事情是"先恢复"。
    """
    if getattr(row, "is_deleted", False):
        raise HTTPException(
            status_code=400,
            detail=f"这条{what}已经删除了（在回收站里），改不了；先恢复它再改：{restore_hint}",
        )
