import json
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import PriceRule, Product, User
from app.schemas.price_rule import (
    PriceRuleBatchBody,
    PriceRuleBatchOut,
    PriceRuleCreate,
    PriceRuleOut,
    PriceRuleUpdate,
)

router = APIRouter(prefix="/price-rules", tags=["price-rules"])


def _rule_to_out(pr: PriceRule, db: Session) -> PriceRuleOut:
    su = db.get(User, pr.shipper_id)
    pu = db.get(Product, pr.product_id)
    return PriceRuleOut(
        id=pr.id,
        shipper_id=pr.shipper_id,
        product_id=pr.product_id,
        special_unit_price=pr.special_unit_price,
        shipper_name=(su.full_name or su.phone) if su else None,
        product_name=pu.name if pu else None,
    )


@router.post("/batch", response_model=PriceRuleBatchOut)
def batch_price_rules(
    body: PriceRuleBatchBody,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.PRICE_RULE_MANAGE)),
) -> PriceRuleBatchOut:
    """批量调价：多批发商 × 多商品 一次写价。
    - fixed：所有组合统一单价；percent：按商品默认售价百分比；tier：应用商品自身第 N 档批发价。
    - 已有规则自动覆盖；shipper_ids/product_ids 为空 = 全部批发商/全部商品。
    """
    qs = select(User).where(User.is_member == True)  # noqa: E712
    if body.shipper_ids:
        qs = qs.where(User.id.in_(body.shipper_ids))
    shippers = list(db.scalars(qs).all())
    qp = select(Product)
    if body.product_ids:
        qp = qp.where(Product.id.in_(body.product_ids))
    products = list(db.scalars(qp).all())

    if not shippers or not products:
        raise HTTPException(status_code=400, detail="未找到批发商或商品，请先选择")

    def _price(p: Product) -> Decimal | None:
        if body.mode == "fixed":
            return body.value
        if body.mode == "percent":
            if body.value is None:
                return None
            return (p.default_unit_price or Decimal("0")) * body.value / Decimal("100")
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
    for s in shippers:
        for p in products:
            price = _price(p)
            if price is None or price < 0:
                continue
            pr = db.scalars(
                select(PriceRule).where(
                    PriceRule.shipper_id == s.id,
                    PriceRule.product_id == p.id,
                )
            ).first()
            if pr is None:
                pr = PriceRule(shipper_id=s.id, product_id=p.id, special_unit_price=price)
                db.add(pr)
            else:
                pr.special_unit_price = price
            count += 1
    db.commit()
    return PriceRuleBatchOut(count=count)


@router.get("", response_model=list[PriceRuleOut])
def list_price_rules(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.PRICE_RULE_MANAGE)),
    shipper_id: int | None = None,
) -> list[PriceRuleOut]:
    q = select(PriceRule).order_by(PriceRule.id.desc())
    if shipper_id is not None:
        q = q.where(PriceRule.shipper_id == shipper_id)
    rows = list(db.scalars(q).all())
    return [_rule_to_out(pr, db) for pr in rows]


@router.post("", response_model=PriceRuleOut, status_code=status.HTTP_201_CREATED)
def create_price_rule(
    body: PriceRuleCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.PRICE_RULE_MANAGE)),
) -> PriceRuleOut:
    exists = db.scalars(
        select(PriceRule).where(
            PriceRule.shipper_id == body.shipper_id,
            PriceRule.product_id == body.product_id,
        )
    ).first()
    if exists:
        raise HTTPException(status_code=400, detail="该货主与商品的价格规则已存在")
    pr = PriceRule(
        shipper_id=body.shipper_id,
        product_id=body.product_id,
        special_unit_price=body.special_unit_price,
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)
    return _rule_to_out(pr, db)


@router.get("/{rule_id}", response_model=PriceRuleOut)
def get_price_rule(rule_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission(Permission.PRICE_RULE_MANAGE))) -> PriceRuleOut:
    pr = db.get(PriceRule, rule_id)
    if pr is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    return _rule_to_out(pr, db)


@router.patch("/{rule_id}", response_model=PriceRuleOut)
def update_price_rule(
    rule_id: int,
    body: PriceRuleUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.PRICE_RULE_MANAGE)),
) -> PriceRuleOut:
    pr = db.get(PriceRule, rule_id)
    if pr is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    if body.shipper_id is not None and body.shipper_id != pr.shipper_id:
        dup = db.scalars(
            select(PriceRule).where(
                PriceRule.shipper_id == body.shipper_id,
                PriceRule.product_id == pr.product_id,
                PriceRule.id != pr.id,
            )
        ).first()
        if dup is not None:
            raise HTTPException(status_code=400, detail="目标货主已存在该商品的特价")
        pr.shipper_id = body.shipper_id
    if body.special_unit_price is not None:
        pr.special_unit_price = body.special_unit_price
    db.commit()
    db.refresh(pr)
    return _rule_to_out(pr, db)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_price_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.PRICE_RULE_MANAGE)),
) -> None:
    pr = db.get(PriceRule, rule_id)
    if pr is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    db.delete(pr)
    db.commit()
