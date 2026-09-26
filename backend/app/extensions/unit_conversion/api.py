# -*- coding: utf-8 -*-
"""单位换算的**只读试算**路由。

## 这个文件为什么这么短（指南 §27）

> 路由可以由 Extension 提供，但**认证、权限、核心安全策略不能被 Extension 自己定义成另一套体系**。

所以这里：

* ⛔ **一行鉴权都没有** —— `require_permission(ORDER_CREATE)` 由**核心**在装配时施加
  （装配代码在 `core/extension_registry.py::mount_extension_routes`，能力点写在 `manifest.py` 里）；
* ⛔ **一行数据库都没有** —— 试算是纯函数，不写任何表、不留任何状态（判据 `_check_data_ownership.py`）；
* 只 import 核心契约与**同包**的实现（判据 `_check_extension_dependencies.py` 第 2 组）。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.contracts.quantity import QuantityError
from app.core.contracts.unit_conversion import ConversionRequest, UnitConversionError
from app.extensions.unit_conversion import resolve

router = APIRouter(tags=["unit-conversion"])


class PreviewOut(BaseModel):
    """试算结果。⛔ 不是 Money：换算**不参与钱**（与既有实现同一条红线）。"""

    value: str
    unit: str
    dimension: str
    factor: str
    exact: bool
    source: str
    note: str = ""


@router.get("/unit-conversion/preview", response_model=PreviewOut)
def preview(
    value: str = Query(..., description="要换算的数值"),
    from_unit: str = Query(..., description="源单位"),
    to_unit: str = Query(..., description="目标单位"),
) -> PreviewOut:
    """试算一次换算（**只读**：不写任何表、不留任何状态）。

    三句中文错各有各的意思，都直接给用户看：
    * 「没有实现认得这对单位」= 这一类单位没人管（不是错误，是没这个能力）；
    * 「不同量纲不能换算」= 拒绝，⛔ 不给一个看起来合理的数；
    * 「源单位与目标单位相同」= 没有可换算的东西。
    """
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="数值请填一个正常的数字：" + value) from exc
    provider = resolve(from_unit, to_unit)
    if provider is None:
        raise HTTPException(
            status_code=400,
            detail="没有实现认得「" + from_unit + "」到「" + to_unit + "」的换算 —— 这一类单位还没有人管",
        )
    try:
        result = provider.convert(ConversionRequest(amount, from_unit, to_unit))
    except UnitConversionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except QuantityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=400, detail="这个实现算不了「" + from_unit + "」到「" + to_unit + "」")
    return PreviewOut(
        value=format(result.quantity.value, "f"),
        unit=result.quantity.unit,
        dimension=result.quantity.dimension,
        factor=format(result.factor, "f"),
        exact=result.exact,
        source=result.source,
        note=result.note,
    )