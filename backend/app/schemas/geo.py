"""经纬度入参的**统一范围校验**：`*lat` ∈ [-90, 90]、`*lng` ∈ [-180, 180]。

## 为什么必须有（2026-09-18 模糊测试实测）
`POST /shipper/addresses {"address_lat": 1e20}`、`.../locations {"address_lng": 1e20}` 都是 200：
坐标列是 `Numeric(10,7)`，本地 SQLite 把 1e20 原样存下，生产 MySQL 才 Out of range。
更常见的是**能存进去但没意义**的值（例如 lat=500）——地图/导航拿到这种坐标只会失败，
而失败发生在"司机按导航走"的时候，不是录入的时候。

判据按**字段名后缀**（`*lat` / `*lng`），与 `money.MoneyInput` 同一套思路：
范围是地理常量，不该按模型各写一遍；报错是中文。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, model_validator

LAT_MAX = Decimal("90")
LNG_MAX = Decimal("180")


class GeoInput(BaseModel):
    """带经纬度的入参基类：按字段名后缀校验范围。"""

    @model_validator(mode="after")
    def _geo_in_range(self) -> "GeoInput":
        for name in type(self).model_fields:
            value: Any = getattr(self, name, None)
            # ⚠️ `bool` 必须显式排除：Python 里 `isinstance(True, int)` 是 True，
            #    于是 `Decimal(str(False))` = `Decimal('False')` → InvalidOperation。
            #    （第一版就是漏了这一行，`is_default=False` 直接把请求打成 500。）
            if value is None or isinstance(value, bool):
                continue
            if not isinstance(value, (int, float, Decimal)):
                continue
            num = value if isinstance(value, Decimal) else Decimal(str(value))
            if name.endswith("lat") and abs(num) > LAT_MAX:
                raise ValueError(f"{name} 纬度必须在 -90 ~ 90 之间（这是坐标，不是普通数字）")
            if name.endswith(("lng", "lon")) and abs(num) > LNG_MAX:
                raise ValueError(f"{name} 经度必须在 -180 ~ 180 之间（这是坐标，不是普通数字）")
        return self
