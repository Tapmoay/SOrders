"""运费价目（派单员）：**路线 → 多条价目 → 每条绑若干司机**，派单选司机自动带价。

用户 2026-09-19 的三句话（改造的全部依据）：
> 「它是**根据路线**来创建的。你说先要创建一个路线，然后才能根据这个路线来创建一个模板，
>   然后我们才能根据这个模板来创建一个对应的订单的价格」；
> 「同一个路线，我们可以配置**多个价格**，比如价格一价格二价格三，都可以修改」；
> 「这个价格是会**跟司机绑定**的…相同的路线不同的司机可能给不同的价格，所以下单的时候
>   就不需要选择那个价格模板了，因为我们只要选了司机他是自动跟上的」。

所以这个模块有两件事必须自己盯住（都不在别处）：
1. **路线快照**：模板上的起点/终点来自路线那一条，不是调用方随手打的字；
2. **一条路线上一个司机只属于一档** —— 否则"选了司机自动带价"没有唯一答案，
   而这种歧义不会报错，只会默默取到另一条价目。
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import FreightCategory, FreightTemplate, FreightTemplateCategory, FreightTemplateDriver, ShipperAddress, User
from app.models.enums import OperationAction, UserRole
from app.schemas.freight_template import (
    FreightQuoteCandidate,
    FreightQuoteOut,
    FreightTemplateCreate,
    FreightTemplateOut,
    FreightTemplateUpdate,
)
from app.services.freight_pricing import Quote, quote_for
from app.services.operation_log_service import write_log
from app.services.soft_delete import ensure_alive

router = APIRouter(prefix="/freight-templates", tags=["freight-templates"])

_VALID_VEHICLE = {"small", "large", "trailer", ""}


def _validate_vehicle(v: str | None) -> str | None:
    if v is None or v == "":
        return None
    if v not in _VALID_VEHICLE:
        raise HTTPException(status_code=400, detail="车型不合法")
    return v


def _resolve_route(
    db: Session, current: User, route_id: int | None, from_place: str, to_place: str
) -> tuple[int | None, str, str]:
    """把 `route_id` 换成"起点/终点快照"。

    有 `route_id`：路线必须是**他自己的**、没被删的（`shipper_addresses` 是按人分区的，
    派单员只能挂自己那份「常用线路」——别人的地址簿不是他的主数据）。
    没有 `route_id`：沿用调用方给的文字（老客户端与 AI 的老卡片还走得通），
    但**创建**时必须二选一，不然又回到"随手打两段字就是一个模板"。
    """
    if route_id is None:
        if not from_place.strip() and not to_place.strip():
            raise HTTPException(
                status_code=400,
                detail="请先选一条**路线**（起点+终点）再建价目；路线可以在「地址与联系人」里建，"
                       "也可以在这个表单里现场新建一条",
            )
        return None, from_place.strip(), to_place.strip()
    addr = db.get(ShipperAddress, route_id)
    if addr is None or addr.is_deleted or addr.shipper_id != current.id:
        raise HTTPException(status_code=404, detail="这条路线不存在（或不是你的）")
    # 路线上的起点/终点就是快照来源：`origin_address` 是起点（可空），`detail_address` 是终点
    return addr.id, (addr.origin_address or "").strip()[:128], (addr.detail_address or "").strip()[:128]


def _driver_ids(db: Session, template_ids: list[int]) -> dict[int, list[int]]:
    """一次把多条价目的司机绑定查出来（列表页别按行查 —— N+1）。"""
    if not template_ids:
        return {}
    rows = db.execute(
        select(FreightTemplateDriver.template_id, FreightTemplateDriver.driver_id).where(
            FreightTemplateDriver.template_id.in_(template_ids)
        )
    ).all()
    out: dict[int, list[int]] = {}
    for tid, did in rows:
        out.setdefault(tid, []).append(did)
    return out


def _set_drivers(db: Session, t: FreightTemplate, driver_ids: list[int]) -> None:
    """整份替换这条价目绑的司机，并守住"一个司机在同一条路线上只属于一档"。

    ⛔ 这条规则必须在这里判（不能只靠界面）：界面上看不出"这个司机已经在同路线的另一档里"，
    而放过去之后**派单自动带价会取到哪一档就是不确定的** —— 两个人各改一次，
    同一单出来的运费可能不一样，且两边都不报错。
    """
    wanted = list(dict.fromkeys(int(i) for i in driver_ids))
    # 同一个司机不许同时挂在这条路线的两条价目上（先查同路线的兄弟模板）
    if wanted and t.route_id is not None:
        siblings = db.scalars(
            select(FreightTemplate).where(
                FreightTemplate.route_id == t.route_id,
                FreightTemplate.id != t.id,
                FreightTemplate.is_deleted.is_(False),
            )
        ).all()
        sib_ids = [s.id for s in siblings]
        taken = _driver_ids(db, sib_ids)
        for sid, dids in taken.items():
            for did in dids:
                if did in wanted:
                    other = next(s for s in siblings if s.id == sid)
                    raise HTTPException(
                        status_code=400,
                        detail=f"司机 {did} 已经在这条路线的「{other.price_name or other.name}」里了；"
                               f"同一个司机在一条路线上只能属于一档（否则派单时不知道该带哪个价）",
                    )
    for row in db.scalars(
        select(FreightTemplateDriver).where(FreightTemplateDriver.template_id == t.id)
    ).all():
        db.delete(row)
    for did in wanted:
        db.add(FreightTemplateDriver(template_id=t.id, driver_id=did))
    db.flush()


def _rule_names(db: Session, template_ids: list[int]) -> dict[int, list[str]]:
    """价目 → 用它的规则名（一次查完；卡片上要写"这条价目归哪几份规则"）。"""
    from app.models import DriverBillingRule, DriverBillingRuleTemplate

    if not template_ids:
        return {}
    rows = db.execute(
        select(DriverBillingRuleTemplate.template_id, DriverBillingRule.name)
        .join(DriverBillingRule, DriverBillingRule.id == DriverBillingRuleTemplate.rule_id)
        .where(
            DriverBillingRuleTemplate.template_id.in_(template_ids),
            DriverBillingRule.is_deleted.is_(False),
        )
    ).all()
    out: dict[int, list[str]] = {}
    for tid, name in rows:
        out.setdefault(tid, []).append(name)
    return out


def _out(db: Session, t: FreightTemplate) -> FreightTemplateOut:
    o = FreightTemplateOut.model_validate(t)
    o.driver_ids = _driver_ids(db, [t.id]).get(t.id, [])
    cats = _category_ids(db, [t.id]).get(t.id, [])
    o.category_ids = cats
    o.category_names = _category_names(db, cats)
    o.rule_names = _rule_names(db, [t.id]).get(t.id, [])
    return o


def _category_ids(db: Session, template_ids: list[int]) -> dict[int, list[int]]:
    """一次把多条价目挂的分类查出来（列表页别按行查 —— N+1）。"""
    if not template_ids:
        return {}
    rows = db.execute(
        select(FreightTemplateCategory.template_id, FreightTemplateCategory.category_id).where(
            FreightTemplateCategory.template_id.in_(template_ids)
        )
    ).all()
    out: dict[int, list[int]] = {}
    for tid, cid in rows:
        out.setdefault(tid, []).append(cid)
    return out


def _category_names(db: Session, category_ids: list[int]) -> list[str]:
    """分类编号 → 名字（**一次查完**；界面上要显示"这条价目算哪几类货"）。"""
    if not category_ids:
        return []
    rows = db.execute(
        select(FreightCategory.id, FreightCategory.name).where(FreightCategory.id.in_(category_ids))
    ).all()
    by_id = {cid: name for cid, name in rows}
    # 顺序跟调用方给的编号顺序走（表单里勾选的先后不该影响显示顺序）
    return [by_id[cid] for cid in category_ids if cid in by_id]


def _set_categories(db: Session, t: FreightTemplate, category_ids: list[int]) -> None:
    """整份替换这条价目挂的分类。

    ⛔ 编号必须真的存在：挂一个不存在的分类，派单匹配时那条价目**永远不会命中**
    （界面看着配好了、运费永远带不出来），而两边都不报错。
    """
    wanted = list(dict.fromkeys(int(i) for i in category_ids))
    if wanted:
        found = set(
            db.scalars(select(FreightCategory.id).where(FreightCategory.id.in_(wanted))).all()
        )
        missing = [i for i in wanted if i not in found]
        if missing:
            raise HTTPException(status_code=400, detail=f"这些运费分类不存在：{missing}")
    for row in db.scalars(
        select(FreightTemplateCategory).where(FreightTemplateCategory.template_id == t.id)
    ).all():
        db.delete(row)
    for cid in wanted:
        db.add(FreightTemplateCategory(template_id=t.id, category_id=cid))
    db.flush()


@router.get("", response_model=list[FreightTemplateOut])
def list_templates(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
    vehicle_type: str | None = Query(None),
) -> list[FreightTemplateOut]:
    q = select(FreightTemplate).where(FreightTemplate.is_deleted.is_(False)).order_by(
        FreightTemplate.route_id.is_(None), FreightTemplate.route_id, FreightTemplate.id
    )
    if vehicle_type:
        q = q.where(FreightTemplate.vehicle_type == vehicle_type)
    rows = list(db.scalars(q))
    bind = _driver_ids(db, [r.id for r in rows])
    cats = _category_ids(db, [r.id for r in rows])
    out = []
    for r in rows:
        o = FreightTemplateOut.model_validate(r)
        o.driver_ids = bind.get(r.id, [])
        o.category_ids = cats.get(r.id, [])
        o.category_names = _category_names(db, o.category_ids)
        out.append(o)
    rules = _rule_names(db, [r.id for r in rows])
    for o in out:
        o.rule_names = rules.get(o.id, [])
    return out


@router.post("", response_model=FreightTemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(
    body: FreightTemplateCreate,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> FreightTemplateOut:
    route_id, from_place, to_place = _resolve_route(
        db, current, body.route_id, body.from_place, body.to_place
    )
    t = FreightTemplate(
        name=body.name.strip(),
        route_id=route_id,
        from_place=from_place,
        to_place=to_place,
        price_name=body.price_name.strip()[:32],
        vehicle_type=_validate_vehicle(body.vehicle_type),
        fee=body.fee,
        remark=body.remark,
        created_by=current.id,
    )
    db.add(t)
    db.flush()
    _set_drivers(db, t, body.driver_ids)
    _set_categories(db, t, body.category_ids)
    # ⚠️ 运费模板是派单填运费的**参考价**，改一个数字影响所有人报价——原来一次日志都不写
    #    （2026-09-19 审计 R14-1，与挂账单位同一批）。审计页上必须能回答"这条价是谁定的"。
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.FREIGHT_TEMPLATE_UPSERT,
        change_payload={
            "template_id": t.id,
            "scope": "create",
            "name": t.name,
            "route_id": t.route_id,
            "price_name": t.price_name,
            "from_place": t.from_place,
            "to_place": t.to_place,
            "vehicle_type": t.vehicle_type,
            "fee": str(t.fee),
            "driver_ids": body.driver_ids,
            "category_ids": body.category_ids,
        },
    )
    db.commit()
    db.refresh(t)
    return _out(db, t)


@router.put("/{template_id}", response_model=FreightTemplateOut)
def update_template(
    template_id: int,
    body: FreightTemplateUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> FreightTemplateOut:
    t = db.get(FreightTemplate, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="未找到该模板")
    # ⚠️ 软删的模板**改不了**（R11-F4）：列表里看不见它，改它只会得到一句「已完成」，
    #    用户以为改好了、界面上却什么都没有（AI 助手走的也是这条路）。
    ensure_alive(t, "运费模板", "POST /freight-templates/{id}/restore")
    before = {"name": t.name, "route_id": t.route_id, "price_name": t.price_name,
              "from_place": t.from_place, "to_place": t.to_place,
              "vehicle_type": t.vehicle_type, "fee": str(t.fee),
              "driver_ids": _driver_ids(db, [t.id]).get(t.id, []),
              "category_ids": _category_ids(db, [t.id]).get(t.id, [])}
    if body.name is not None:
        t.name = body.name.strip()
    if body.route_id is not None:
        route_id, from_place, to_place = _resolve_route(
            db, current, body.route_id, t.from_place, t.to_place
        )
        t.route_id, t.from_place, t.to_place = route_id, from_place, to_place
    if body.from_place is not None and body.route_id is None:
        t.from_place = body.from_place.strip()
    if body.to_place is not None and body.route_id is None:
        t.to_place = body.to_place.strip()
    if body.price_name is not None:
        t.price_name = body.price_name.strip()[:32]
    if body.vehicle_type is not None:
        t.vehicle_type = _validate_vehicle(body.vehicle_type)
    if body.fee is not None:
        t.fee = body.fee
    if body.remark is not None:
        t.remark = body.remark
    if body.driver_ids is not None:
        _set_drivers(db, t, body.driver_ids)
    if body.category_ids is not None:
        _set_categories(db, t, body.category_ids)
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.FREIGHT_TEMPLATE_UPSERT,
        change_payload={
            "template_id": t.id,
            "scope": "update",
            "before": before,
            "after": {"name": t.name, "route_id": t.route_id, "price_name": t.price_name,
                      "from_place": t.from_place, "to_place": t.to_place,
                      "vehicle_type": t.vehicle_type, "fee": str(t.fee),
                      "driver_ids": _driver_ids(db, [t.id]).get(t.id, []),
              "category_ids": _category_ids(db, [t.id]).get(t.id, [])},
        },
    )
    db.commit()
    db.refresh(t)
    return _out(db, t)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> None:
    t = db.get(FreightTemplate, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="未找到该模板")
    # 伪装删除（v3.26）：模板是下次派单时的参考价，删错了要能原样回来。
    #
    # ⚠️ 分类绑定（`freight_template_categories`）**跟着删掉**：那张表不软删，
    #    留着的话"这个分类还有几条价目挂着"会把一条已经不存在的价目算进去 ——
    #    于是分类永远删不掉，而界面上根本看不到是它挡着。
    for row in db.scalars(
        select(FreightTemplateCategory).where(FreightTemplateCategory.template_id == t.id)
    ).all():
        db.delete(row)
    t.is_deleted = True
    t.deleted_at = utc_now_naive()
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.FREIGHT_TEMPLATE_DELETE,
        change_payload={"template_id": t.id, "name": t.name, "fee": str(t.fee),
                        "note": "伪装删除，可 restore 恢复"},
    )
    db.commit()


@router.post("/{template_id}/restore", response_model=FreightTemplateOut)
def restore_template(
    template_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> FreightTemplate:
    """把删掉的运费模板恢复回来（DELETE /{id} 的逆操作）。"""
    t = db.get(FreightTemplate, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="未找到该模板")
    if not t.is_deleted:
        raise HTTPException(status_code=400, detail="这个模板没有被删除，不需要恢复")
    t.is_deleted = False
    t.deleted_at = None
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.FREIGHT_TEMPLATE_RESTORE,
        change_payload={"template_id": t.id, "name": t.name},
    )
    db.commit()
    db.refresh(t)
    return t


def _quote_out(q: Quote) -> FreightQuoteOut:
    def cand(c) -> FreightQuoteCandidate:
        return FreightQuoteCandidate(
            template_id=c.template_id,
            name=c.name,
            fee=c.fee,
            price_name=c.price_name,
            route=c.route,
            category_names=list(c.category_names),
            driver_names=list(c.driver_names),
        )

    return FreightQuoteOut(
        matched=cand(q.matched) if q.matched is not None else None,
        category_id=q.category_id,
        category_name=q.category_name,
        reason=q.reason,
        ambiguous=[cand(c) for c in q.ambiguous],
    )


@router.get("/quote", response_model=FreightQuoteOut)
def quote_freight(
    order_id: int = Query(..., description="这一单"),
    driver_id: int | None = Query(None, description="按这个司机找价目（不传 = 只看分类/路线）"),
    category_id: int | None = Query(None, description="不传 = 用订单上已有的分类"),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> FreightQuoteOut:
    """**派单时自动带价**用的报价（唯一的匹配实现：`services/freight_pricing.py`）。

    没匹配到不是错误：它会带着"为什么没匹配到"回去，界面显示成「运费待定价」，
    由派单员手动定价（`POST /orders/{id}/price-freight`）。
    """
    from app.models import Order

    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    return _quote_out(quote_for(db, order, driver_id=driver_id, category_id=category_id))
