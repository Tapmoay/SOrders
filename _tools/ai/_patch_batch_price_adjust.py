"""给批量调价加「相对调整」模式，并让接口回报前后值。

### 为什么必须改后端
用户要的是「在**现在这个价**基础上涨/降百分之多少」。现有 `percent` 模式算的是
`default_unit_price * value / 100`——**按商品默认价的百分比设定**，跟"相对调整"是两回事。

对一个已经单独谈过价的批发商，用默认价算出来的数字**看着也合理**，
所以这种错不会有人发现，直到对账。所以必须由后端按"当前生效价"来算。

用法：cd backend && python ../_tools/ai/_patch_batch_price_adjust.py
（幂等：重复跑不会重复插入）
"""
from __future__ import annotations

import pathlib
import re
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[2] / "backend"


def patch_schema() -> bool:
    p = BACKEND / "app" / "schemas" / "price_rule.py"
    s = p.read_text(encoding="utf-8")
    if "adjust_percent" in s:
        print("  schema 已打过补丁，跳过")
        return False
    s = s.replace(
        '    mode: Literal["fixed", "tier", "percent"] = "fixed"\n',
        '    mode: Literal["fixed", "tier", "percent", "adjust"] = "fixed"\n',
    )
    # 在 tier_index 之后插入 adjust_percent
    anchor = '    tier_index: int | None = Field(None, ge=0, description="tier=应用商品自身第几档批发价")\n'
    add = (
        '    adjust_percent: Decimal | None = Field(\n'
        '        None,\n'
        '        ge=Decimal("-100"),\n'
        '        le=Decimal("1000"),\n'
        '        description="adjust=在【当前生效价】基础上涨/降百分之多少"\n'
        '        "（+10=涨10%，-15=降15%）。当前生效价 = 已有的专属价；没有专属价则用商品默认价。",\n'
        '    )\n'
    )
    assert anchor in s, "找不到 tier_index 那行"
    s = s.replace(anchor, anchor + add)

    old_out = "class PriceRuleBatchOut(BaseModel):\n    count: int\n"
    new_out = (
        "class PriceRuleBatchChange(BaseModel):\n"
        '    """一条改动的前后值。**接口回报它，卡片和结果才对得上账。**\n\n'
        "    before=None 表示这个批发商之前没有专属价（按通用价买）。\n"
        '    """\n\n'
        "    shipper_name: str\n"
        "    product_name: str\n"
        "    before: Decimal | None = None\n"
        "    after: Decimal\n\n\n"
        "class PriceRuleBatchOut(BaseModel):\n"
        "    count: int\n"
        "    skipped: int = 0\n"
        "    changes: list[PriceRuleBatchChange] = []\n"
    )
    assert old_out in s, "找不到 PriceRuleBatchOut"
    s = s.replace(old_out, new_out)
    p.write_text(s, encoding="utf-8")
    print("  schema 已更新")
    return True


def patch_endpoint() -> bool:
    p = BACKEND / "app" / "api" / "v1" / "price_rules.py"
    s = p.read_text(encoding="utf-8")
    if "adjust_percent" in s:
        print("  endpoint 已打过补丁，跳过")
        return False

    start = s.index("    def _price(p: Product) -> Decimal | None:")
    end = s.index("    db.commit()", start) + len("    db.commit()")
    new = '''    def _price(p: Product, pr: "PriceRule | None") -> Decimal | None:
        if body.mode == "fixed":
            return body.value
        if body.mode == "percent":
            if body.value is None:
                return None
            return (p.default_unit_price or Decimal("0")) * body.value / Decimal("100")
        if body.mode == "adjust":
            # 相对调整：在**当前生效价**上按百分比涨/降。
            # 为什么必须读 pr.special_unit_price 而不是 default_unit_price：
            # 用户说的是「在现在这个价基础上涨 10%」。拿默认价算，
            # 对一个已经单独谈过价的批发商就是错的——而且错得隐蔽（数字看着也合理）。
            if body.adjust_percent is None:
                return None
            base = pr.special_unit_price if pr is not None else (p.default_unit_price or Decimal("0"))
            raw = base * (Decimal("100") + body.adjust_percent) / Decimal("100")
            return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        # tier：商品自身批发价第 N 档
        if body.tier_index is None:
            return None
        try:
            tiers = json.loads(p.tier_prices) if isinstance(p.tier_prices, str) else (p.tier_prices or [])
            if body.tier_index < len(tiers):
                return Decimal(str(tiers[body.tier_index]["unit_price"]))
        except Exception:
            return None
        return None

    count = 0
    skipped = 0
    changes: list[PriceRuleBatchChange] = []
    for s in shippers:
        for p in products:
            pr = db.scalars(
                select(PriceRule).where(
                    PriceRule.shipper_id == s.id,
                    PriceRule.product_id == p.id,
                )
            ).first()
            price = _price(p, pr)
            if price is None or price < 0:
                skipped += 1
                continue
            before = pr.special_unit_price if pr is not None else None
            if pr is None:
                pr = PriceRule(shipper_id=s.id, product_id=p.id, special_unit_price=price)
                db.add(pr)
            else:
                pr.special_unit_price = price
            count += 1
            # 明细只留前 200 条：组合可能上万。回报它的目的是**让卡片和结果能核对**，
            # 不是把整张表搬回客户端。
            if len(changes) < 200:
                changes.append(
                    PriceRuleBatchChange(
                        shipper_name=(s.full_name or s.username or "")[:64],
                        product_name=(p.name or "")[:64],
                        before=before,
                        after=price,
                    )
                )
    db.commit()
    return PriceRuleBatchOut(count=count, skipped=skipped, changes=changes)'''
    s = s[:start] + new + s[end:]

    # 导入补全
    if "ROUND_HALF_UP" not in s:
        s = s.replace("from decimal import Decimal", "from decimal import ROUND_HALF_UP, Decimal", 1)
        if "ROUND_HALF_UP" not in s:
            s = s.replace("import decimal", "from decimal import ROUND_HALF_UP, Decimal", 1)
    if "PriceRuleBatchChange" not in s.split("@router")[0]:
        m = re.search(r"from app\.schemas\.price_rule import \(([^)]*)\)", s)
        if m:
            inner = m.group(1).rstrip()
            s = s.replace(m.group(0), f"from app.schemas.price_rule import ({inner}\n    PriceRuleBatchChange,\n)", 1)
        else:
            m2 = re.search(r"from app\.schemas\.price_rule import ([^\n]+)", s)
            assert m2, "找不到 schemas 导入行"
            names = m2.group(1)
            s = s.replace(m2.group(0), f"from app.schemas.price_rule import PriceRuleBatchChange, {names}", 1)
    p.write_text(s, encoding="utf-8")
    print("  endpoint 已更新")
    return True


def main() -> int:
    print("批量调价补丁")
    a = patch_schema()
    b = patch_endpoint()
    print(f"完成（schema={a} endpoint={b}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
