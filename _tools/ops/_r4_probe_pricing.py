# -*- coding: utf-8 -*-
"""R4-07 演练用的只读探针：把"旧实现还能工作 / 新实现能加入"两件事量出来（一行 JSON）。

⚠️ 为什么是独立脚本而不是 `python -c "..."`：那段代码要写引号套引号，
第一版就是那么写的，结果**静默失败**（探针返回空、而演练只看到"一个实现都没有"）——
把一个"探测不到"伪装成了"事实如此"。独立文件里没有 shell 引号这回事。

⛔ 只读：不连库、不写文件。
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> int:
    from app.core.contracts.pricing import PricingContext, PricingContract, PricingContractV2, as_v2
    from app.core.contracts.quantity import Quantity
    from app.extensions.pricing import PROVIDERS, resolve_v2

    out: dict[str, object] = {"providers": [], "v1_ok": [], "v2_native": [], "errors": []}
    names: list[str] = []
    v1_ok: list[list[object]] = []
    v2_native: list[str] = []
    for provider in PROVIDERS:
        names.append(provider.name)
        kind = getattr(provider, "kind", None)
        if not kind:
            continue
        context = PricingContext(
            rule_snapshot={"pricing_kind": kind, "amount": "120.00", "unit_price": "8.50"},
            unit_price=Decimal("8.50"),
            quantity=Quantity(Decimal("15"), "件", "count"),
        )
        try:
            v2 = resolve_v2(context)
            total = v2.price(context).money
            lines = v2.breakdown(context)
            summed = lines[0].money
            for line in lines[1:]:
                summed = summed + line.money
            v1_ok.append([provider.name, isinstance(v2, PricingContract),
                          isinstance(v2, PricingContractV2), summed.amount == total.amount,
                          len(lines), total.as_text()])
            if isinstance(provider, PricingContractV2):
                v2_native.append(provider.name)
        except Exception as exc:  # noqa: BLE001 —— 演练要看的就是"能不能算"
            out["errors"].append(provider.name + ": " + str(exc)[:120])
    out["providers"] = names
    out["v1_ok"] = v1_ok
    out["v2_native"] = v2_native
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())