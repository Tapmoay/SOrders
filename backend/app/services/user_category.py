# -*- coding: utf-8 -*-
"""账号分类 = **按身份自动推导**（唯一一处）。

用户 2026-10-11 的口径（逐字要点）：
「批发账号管理……其实已经分好了、已经挂上了不同的身份；**既然挂上了不同的身份，我们就自动分类啊，不用我们再手动分类了**。
  像我现在如果选『批发商』，他分的类居然是个『东城水果批发』，但我们的**身份显示的居然是货主**，这肯定是错的 ——
  他应该分到**货主**那里去，不是批发商。**自动分类是要有的**。」

⇒ 规矩：`users.category` **不再由人挑**，一律由身份推出来：

| 身份（role / is_member / vehicle_type） | 自动分类 |
|---|---|
| `DISPATCHER` | 派单员 |
| `SHIPPER` 且 **不是**高级货主 | 货主 |
| `SHIPPER` 且 `is_member=True` | 批发商 |
| `DRIVER` + `vehicle_type=small` | 小车司机 |
| `DRIVER` + `vehicle_type=large`（含认不出/为空的老数据） | 大车司机 |
| `DRIVER` + `vehicle_type=trailer` | 挂车司机 |

⛔ 别处不许再写第二份推导（判据 `_tools/qa/_check_auto_user_category.py` 盯着）。
"""
from __future__ import annotations

DISPATCHER_CATEGORY = "派单员"
SHIPPER_CATEGORY = "货主"
MEMBER_CATEGORY = "批发商"
DRIVER_SMALL_CATEGORY = "小车司机"
DRIVER_LARGE_CATEGORY = "大车司机"
DRIVER_TRAILER_CATEGORY = "挂车司机"

#: 六个分类的固定顺序（与 `user_categories` 名册播种顺序一致）。
AUTO_CATEGORIES: tuple[str, ...] = (
    DISPATCHER_CATEGORY,
    SHIPPER_CATEGORY,
    MEMBER_CATEGORY,
    DRIVER_SMALL_CATEGORY,
    DRIVER_LARGE_CATEGORY,
    DRIVER_TRAILER_CATEGORY,
)


def _role_key(role: object) -> str:
    """角色可能是枚举、也可能是字符串（老数据/调用方传进来的都有）。"""
    raw = getattr(role, "value", role)
    return str(raw or "").strip().lower()


def _vehicle_key(vehicle_type: object) -> str:
    raw = getattr(vehicle_type, "value", vehicle_type)
    return str(raw or "").strip().lower()


def auto_category(role: object, is_member: object = False, vehicle_type: object = None) -> str:
    """按身份推出分类。**这是唯一实现**（见本文件 docstring 的用户口径）。

    - 认不出的角色 ⇒ 货主（与 `Role.fromKey` 的老口径一致：认不出当货主）；
    - 认不出的车型 ⇒ 大车司机（与 `AccountManageViewModel` 的老口径一致：认不出当大车）。
    """
    r = _role_key(role)
    if r == "dispatcher":
        return DISPATCHER_CATEGORY
    if r == "shipper":
        return MEMBER_CATEGORY if bool(is_member) else SHIPPER_CATEGORY
    if r == "driver":
        v = _vehicle_key(vehicle_type)
        if v == "small":
            return DRIVER_SMALL_CATEGORY
        if v == "trailer":
            return DRIVER_TRAILER_CATEGORY
        return DRIVER_LARGE_CATEGORY
    return SHIPPER_CATEGORY


def auto_category_of(user: object) -> str:
    """直接给 ORM 的 `User` 对象算（少写一次三个字段的搬运）。"""
    return auto_category(
        getattr(user, "role", None),
        getattr(user, "is_member", False),
        getattr(user, "vehicle_type", None),
    )