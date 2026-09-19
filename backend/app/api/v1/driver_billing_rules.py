"""司机计费规则模板（派单员）：可命名的一份规则，挂到司机身上决定他怎么算钱。

### 为什么是"模板 + 挂载"而不是继续在司机身上堆字段
用户 2026-09-18 的原话：「可以创建固定的模板……给司机挂上我们已经配置好的模板，
那规则可能是命好了一个名称」。他描述的场景里有**两类司机 × 四五种给钱方式**，
如果继续在 `users` 上堆 `salary`/`billing_mode`，就是"每种组合加一个字段"，
加到第五种时没人说得清某一列到底参与不参与计算。规则表把"怎么算钱"变成**数据**：
加一种给钱方式 = 加一份规则，不是改六个消费点的代码。

### 写路径只有一条（挂载/解挂）
挂载**只能**走 `POST /driver-billing-rules/attach`，不许从 `PATCH /users/{id}` 也能改——
两条写路径必然分叉（一条记得写日志、另一条忘了；一条校验车型、另一条不校验），
而分叉的那一刻没人会发现（这个仓库已经在"改价"和"账号"两处栽过重复入口，见 §20.5）。

### 金额怎么算
**这里一行钱的算法都没有**——全部在 `services/driver_pay.py`。这个文件只负责：
把规则存下来、按名字找到它、校验它、挂上去、留痕。
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import DriverBillingRule, Product, User
from app.models.enums import OperationAction, UserRole
from app.schemas.driver_billing_rule import (
    AttachRuleBody,
    DriverBillingRuleCreate,
    DriverBillingRuleOut,
    DriverBillingRuleUpdate,
    validate_rule_params,
)
from app.services.driver_pay import PayRule, monthly_salary_of, rule_of_user, snapshot_mode
from app.services.operation_log_service import write_log

router = APIRouter(prefix="/driver-billing-rules", tags=["driver-billing-rules"])

_VEHICLE_CN = {"small": "小型车", "large": "大车", "trailer": "挂车"}


def _write_log(db: Session, operator: User, action: OperationAction, payload: dict) -> None:
    # 用统一的 `write_log`（它知道 payload 要序列化成 change_content），
    # 不要自己 `OperationLog(...)`——那个模型上没有 change_payload 这个字段（踩过）。
    write_log(db, operator_id=operator.id, order_id=None, action=action, change_payload=payload)


def _pay_rule(r: DriverBillingRule) -> PayRule:
    return PayRule(
        rule_id=r.id,
        name=r.name or "",
        salary=r.salary or 0,
        piece_amount=r.piece_amount or 0,
        piece_unit=r.piece_unit or "order",
        commission_base=r.commission_base or "none",
        commission_rate=r.commission_rate or 0,
        vehicle_type=r.vehicle_type or None,
        commission_product_ids=tuple(int(x) for x in (r.commission_product_ids or [])),
    )


def _check_products(db: Session, ids: list[int]) -> list[int]:
    """抽成范围里的商品必须真的存在（名字→编号已经在客户端解析过了，这里兜数据库）。

    不校验的后果很隐蔽：规则看起来配了 3 个商品，实际有一个编号是错的 →
    那个商品的提成永远算不出来，而**没有任何地方会报错**。
    """
    if not ids:
        return []
    uniq = sorted({int(i) for i in ids})
    found = set(db.scalars(select(Product.id).where(Product.id.in_(uniq))))
    missing = [i for i in uniq if i not in found]
    if missing:
        raise HTTPException(status_code=400, detail=f"抽成范围里有对不上的商品编号：{missing}")
    return uniq


def _product_names(db: Session, ids: list[int]) -> list[str]:
    if not ids:
        return []
    rows = db.scalars(select(Product).where(Product.id.in_(ids))).all()
    by_id = {p.id: p.name for p in rows}
    return [by_id.get(i, f"#{i}") for i in ids]


def _to_out(db: Session, r: DriverBillingRule, attached: int | None = None) -> DriverBillingRuleOut:
    if attached is None:
        attached = db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.driver_rule_id == r.id, User.role == UserRole.DRIVER.value)
        ) or 0
    scope = [int(x) for x in (r.commission_product_ids or [])]
    return DriverBillingRuleOut(
        id=r.id,
        name=r.name,
        vehicle_type=r.vehicle_type,
        salary=r.salary,
        piece_amount=r.piece_amount,
        piece_unit=r.piece_unit,
        commission_base=r.commission_base,
        commission_rate=r.commission_rate,
        commission_product_ids=scope,
        commission_product_names=_product_names(db, scope),
        remark=r.remark or "",
        summary=_pay_rule(r).describe(),  # 一句话说清它怎么给钱（界面/卡片直接显示，不各写一套）
        attached_count=attached,
        is_deleted=bool(r.is_deleted),
        created_at=r.created_at,
    )


def _get_or_404(db: Session, rule_id: int) -> DriverBillingRule:
    r = db.get(DriverBillingRule, rule_id)
    if r is None:
        raise HTTPException(status_code=404, detail="未找到该计费规则")
    return r


@router.get("", response_model=list[DriverBillingRuleOut])
def list_rules(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
    vehicle_type: str | None = Query(None),
    deleted_only: bool = Query(False, description="只看回收站里的（删错了要能找回来）"),
) -> list[DriverBillingRuleOut]:
    q = select(DriverBillingRule).order_by(DriverBillingRule.id.desc())
    q = q.where(DriverBillingRule.is_deleted.is_(True) if deleted_only else DriverBillingRule.is_deleted.is_(False))
    if vehicle_type:
        q = q.where(DriverBillingRule.vehicle_type == vehicle_type)
    return [_to_out(db, r) for r in db.scalars(q)]


@router.post("", response_model=DriverBillingRuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(
    body: DriverBillingRuleCreate,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> DriverBillingRuleOut:
    params = body.model_dump()
    params["commission_product_ids"] = _check_products(db, params.get("commission_product_ids") or [])
    err = validate_rule_params(params)
    if err:
        raise HTTPException(status_code=400, detail=err)
    # 同名规则会让"按名字挂载"变成掷骰子（AI 说「挂上挂车计件」，到底是哪一份？）
    dup = db.scalars(
        select(DriverBillingRule).where(
            DriverBillingRule.name == params["name"].strip(),
            DriverBillingRule.is_deleted.is_(False),
        )
    ).first()
    if dup is not None:
        raise HTTPException(status_code=409, detail=f"已经有一份叫「{params['name'].strip()}」的规则了（名字要能唯一认出它）")

    r = DriverBillingRule(
        name=params["name"].strip(),
        vehicle_type=(params.get("vehicle_type") or None),
        salary=params.get("salary") or 0,
        piece_amount=params.get("piece_amount") or 0,
        piece_unit=params.get("piece_unit") or "order",
        commission_base=params.get("commission_base") or "none",
        commission_rate=params.get("commission_rate") or 0,
        commission_product_ids=_check_products(db, params.get("commission_product_ids") or []),
        remark=params.get("remark") or "",
        created_by=current.id,
    )
    db.add(r)
    db.flush()
    _write_log(db, current, OperationAction.DRIVER_RULE_UPSERT, {"rule_id": r.id, "op": "create", "after": r.params()})
    db.commit()
    db.refresh(r)
    return _to_out(db, r, attached=0)


@router.put("/{rule_id}", response_model=DriverBillingRuleOut)
def update_rule(
    rule_id: int,
    body: DriverBillingRuleUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> DriverBillingRuleOut:
    r = _get_or_404(db, rule_id)
    if r.is_deleted:
        raise HTTPException(status_code=400, detail="这份规则在回收站里，先恢复再改")
    before = r.params()

    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="没有要改的内容")
    merged = dict(before)
    merged.update({k: v for k, v in patch.items() if v is not None or k == "vehicle_type"})
    if "commission_product_ids" in patch:
        merged["commission_product_ids"] = _check_products(db, patch["commission_product_ids"] or [])
    err = validate_rule_params(merged)
    if err:
        raise HTTPException(status_code=400, detail=err)

    if "name" in patch and patch["name"] is not None:
        name = patch["name"].strip()
        dup = db.scalars(
            select(DriverBillingRule).where(
                DriverBillingRule.name == name,
                DriverBillingRule.id != r.id,
                DriverBillingRule.is_deleted.is_(False),
            )
        ).first()
        if dup is not None:
            raise HTTPException(status_code=409, detail=f"已经有一份叫「{name}」的规则了")
        r.name = name
    if "vehicle_type" in patch:
        r.vehicle_type = (patch["vehicle_type"] or None)
    if patch.get("salary") is not None:
        r.salary = patch["salary"]
    if patch.get("piece_amount") is not None:
        r.piece_amount = patch["piece_amount"]
    if patch.get("piece_unit") is not None:
        r.piece_unit = patch["piece_unit"]
    if patch.get("commission_base") is not None:
        r.commission_base = patch["commission_base"]
    if patch.get("commission_rate") is not None:
        r.commission_rate = patch["commission_rate"]
    if "commission_product_ids" in patch:
        r.commission_product_ids = merged["commission_product_ids"]
    if patch.get("remark") is not None:
        r.remark = patch["remark"]

    after = r.params()
    changes = [{"field": k, "from": before[k], "to": after[k]} for k in before if before[k] != after[k]]
    # ⚠️ 改规则**不动历史账单**：派单时已经把规则快照到订单上了，
    #    所以这里改完只影响"以后派的单"。卡片上必须写清这一点，否则用户以为账单会跟着变。
    if changes:
        _write_log(db, current, OperationAction.DRIVER_RULE_UPSERT, {"rule_id": r.id, "op": "update", "changes": changes})
    db.commit()
    db.refresh(r)
    return _to_out(db, r)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> None:
    r = _get_or_404(db, rule_id)
    attached = db.scalar(
        select(func.count())
        .select_from(User)
        .where(User.driver_rule_id == r.id, User.role == UserRole.DRIVER.value)
    ) or 0
    # 还挂着司机就不许删：删掉之后那些司机**悄悄退回老口径**（计件=全额运费），
    # 而"悄悄改了 3 个人的工资算法"是这次改造里最不能接受的一种失败。
    if attached:
        raise HTTPException(
            status_code=400,
            detail=f"还有 {attached} 个司机挂着这份规则，先给他们换掉或解挂再删",
        )
    r.is_deleted = True
    r.deleted_at = utc_now_naive()
    _write_log(db, current, OperationAction.DRIVER_RULE_UPSERT, {"rule_id": r.id, "op": "delete", "before": r.params()})
    db.commit()


@router.post("/{rule_id}/restore", response_model=DriverBillingRuleOut)
def restore_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> DriverBillingRuleOut:
    """把删掉的规则恢复回来（撤回底线：删错了要能原样回来）。"""
    r = _get_or_404(db, rule_id)
    if not r.is_deleted:
        raise HTTPException(status_code=400, detail="这份规则没有被删除，不需要恢复")
    name_taken = db.scalars(
        select(DriverBillingRule).where(
            DriverBillingRule.name == r.name,
            DriverBillingRule.id != r.id,
            DriverBillingRule.is_deleted.is_(False),
        )
    ).first()
    if name_taken is not None:
        raise HTTPException(status_code=409, detail=f"回收站外面已经有一份叫「{r.name}」的规则了，先把那份改名")
    r.is_deleted = False
    r.deleted_at = None
    _write_log(db, current, OperationAction.DRIVER_RULE_UPSERT, {"rule_id": r.id, "op": "restore"})
    db.commit()
    db.refresh(r)
    return _to_out(db, r)


@router.post("/attach", response_model=DriverBillingRuleOut | None)
def attach_rule(
    body: AttachRuleBody,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.USER_MANAGE)),
) -> DriverBillingRuleOut | None:
    """把规则挂到司机身上；`rule_id=null` = 解挂（他退回老口径）。

    三条拦截，每一条都对应一种"看起来成功了、其实算错钱"：
    1. 目标不是司机 → 挂上去没有任何效果（规则只对司机的账单生效）；
    2. 规则在回收站里 → 挂上去了，但账单里读不到它；
    3. **车型对不上**（规则写"挂车"却挂给大车司机）→ 从这一刻起他每一单都按错误的规则算钱，
       而且界面上只显示"已挂载"。
    """
    driver = db.get(User, body.driver_id)
    if driver is None:
        raise HTTPException(status_code=404, detail="未找到该司机")
    if (driver.role.value if hasattr(driver.role, "value") else str(driver.role)) != UserRole.DRIVER.value:
        raise HTTPException(status_code=400, detail="计费规则只能挂给司机账号")

    if body.rule_id is None:
        before_rule = rule_of_user(driver)
        driver.driver_rule_id = None
        db.flush()
        _write_log(
            db,
            current,
            OperationAction.DRIVER_RULE_ATTACH,
            {
                "driver_id": driver.id,
                "driver_name": driver.full_name or driver.phone,
                "op": "detach",
                "before": before_rule.name if before_rule else None,
                "after": None,
                # 解挂之后按什么算，必须写清楚——否则用户以为"他就不拿钱了"
                "fallback": snapshot_mode(driver),
            },
        )
        db.commit()
        return None

    rule = _get_or_404(db, body.rule_id)
    if rule.is_deleted:
        raise HTTPException(status_code=400, detail="这份规则在回收站里，先恢复再挂")
    vt = driver.vehicle_type or None
    if rule.vehicle_type and rule.vehicle_type != vt:
        raise HTTPException(
            status_code=400,
            detail=(
                f"车型对不上：规则「{rule.name}」限{_VEHICLE_CN.get(rule.vehicle_type, rule.vehicle_type)}，"
                f"而这个司机是{_VEHICLE_CN.get(vt, vt or '未设置车型')}。"
                "要么把规则改成通用，要么先改司机的车型。"
            ),
        )

    before_rule = rule_of_user(driver)
    driver.driver_rule_id = rule.id
    db.flush()
    _write_log(
        db,
        current,
        OperationAction.DRIVER_RULE_ATTACH,
        {
            "driver_id": driver.id,
            "driver_name": driver.full_name or driver.phone,
            "op": "attach",
            "rule_id": rule.id,
            "rule_name": rule.name,
            "before": before_rule.name if before_rule else None,
            "after": rule.name,
            # 老口径下他原来怎么算（改前→改后，和改价卡片同一个形状）
            "before_salary": str(monthly_salary_of(driver)) if before_rule is None else None,
        },
    )
    db.commit()
    return _to_out(db, rule)
