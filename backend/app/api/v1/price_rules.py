from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import PriceRule, Product, User
from app.schemas.price_rule import PriceRuleCreate, PriceRuleOut, PriceRuleUpdate

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
