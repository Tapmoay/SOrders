# -*- coding: utf-8 -*-
"""账号分类＝按身份自动推导（用户 2026-10-11 口径）。"""
from __future__ import annotations

from app.services.user_category import (
    AUTO_CATEGORIES, DISPATCHER_CATEGORY, DRIVER_LARGE_CATEGORY, DRIVER_SMALL_CATEGORY,
    DRIVER_TRAILER_CATEGORY, MEMBER_CATEGORY, SHIPPER_CATEGORY, auto_category,
)


def test_dispatcher_is_dispatcher_category():
    assert auto_category("DISPATCHER") == DISPATCHER_CATEGORY


def test_plain_shipper_is_shipper_category():
    assert auto_category("SHIPPER") == SHIPPER_CATEGORY
    assert auto_category("SHIPPER", False) == SHIPPER_CATEGORY


def test_member_shipper_is_wholesaler_category():
    assert auto_category("SHIPPER", True) == MEMBER_CATEGORY


def test_driver_three_types():
    assert auto_category("DRIVER", False, "small") == DRIVER_SMALL_CATEGORY
    assert auto_category("DRIVER", False, "trailer") == DRIVER_TRAILER_CATEGORY
    assert auto_category("DRIVER", False, "large") == DRIVER_LARGE_CATEGORY


def test_driver_unknown_or_empty_vehicle_type_falls_back_to_large():
    """认不出/为空的老数据当大车司机（与 App 侧老口径一致）。"""
    assert auto_category("DRIVER", False, None) == DRIVER_LARGE_CATEGORY
    assert auto_category("DRIVER", False, "") == DRIVER_LARGE_CATEGORY
    assert auto_category("DRIVER", False, "挂车") == DRIVER_LARGE_CATEGORY


def test_case_and_enum_tolerance():
    """角色/车型可能是枚举，也可能是大小写不一的字符串。"""
    assert auto_category("dispatcher") == DISPATCHER_CATEGORY
    assert auto_category("Driver", False, "TRAILER") == DRIVER_TRAILER_CATEGORY

    class _E:
        value = "SHIPPER"

    assert auto_category(_E(), True) == MEMBER_CATEGORY


def test_unknown_role_falls_back_to_shipper():
    assert auto_category(None) == SHIPPER_CATEGORY
    assert auto_category("") == SHIPPER_CATEGORY


def test_all_outputs_are_in_the_fixed_six():
    seen = {
        auto_category("DISPATCHER"), auto_category("SHIPPER"), auto_category("SHIPPER", True),
        auto_category("DRIVER", False, "small"), auto_category("DRIVER", False, "large"),
        auto_category("DRIVER", False, "trailer"),
    }
    assert seen == set(AUTO_CATEGORIES)
    assert len(AUTO_CATEGORIES) == 6