"""单位换算（一车 = 8 方）的出入参。

用户 2026-09-24：「我们的**货主和派单员**，他可以自动的设置单位，比如说一车等于 8 方。…
我们再计算的时候或者是算账的时候会自动启动换算的功能，比如说我下的十车，
会有 2 个数据：第一个是 10 车，第 2 个则是 80 方。」

⚠️ `factor` 是 **Decimal**（`Numeric(14,4)`）：换算率要参与数量显示，
浮点会让"10 车"变成 `79.99999999999999`。Android 侧用 `FlexibleStringSerializer` 接
（Pydantic v2 把 Decimal 序列化成字符串，而老后端可能是数字）。
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.services.unit_conversion import FACTOR_MAX, MAX_UNIT_LEN


class UnitConversionCreate(BaseModel):
    #: 源单位（"车"）。长度上限与列宽一致。
    from_unit: str = Field(..., max_length=MAX_UNIT_LEN)
    #: 目标单位（"方"）
    to_unit: str = Field(..., max_length=MAX_UNIT_LEN)
    #: `1 from_unit = factor to_unit`。**这里不写 ge/gt**：越界要让用户看到
    #: `services/unit_conversion.py` 里那句中文，而不是 pydantic 的英文结构体
    #: （与司机计费规则 `validate_rule_params` 同一条纪律）。
    factor: Decimal
    remark: str = Field(default="", max_length=256)


class UnitConversionUpdate(BaseModel):
    """部分更新：`None` = 这一项不改。"""

    from_unit: str | None = Field(None, max_length=MAX_UNIT_LEN)
    to_unit: str | None = Field(None, max_length=MAX_UNIT_LEN)
    factor: Decimal | None = None
    remark: str | None = Field(None, max_length=256)


class UnitConversionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_unit: str
    to_unit: str
    factor: Decimal
    remark: str = ""
    #: UTC（与全库同基准），客户端换算成本地时区显示
    created_at: datetime
    #: 回收站里那一批才非空（`GET /unit-conversions?deleted_only=true`）
    deleted_at: datetime | None = None


#: 换算率上限对外也说一遍（AI 的卡片要用它判"这个数是不是打错了"）
__all__ = ["UnitConversionCreate", "UnitConversionUpdate", "UnitConversionOut", "FACTOR_MAX"]
