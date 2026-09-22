from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.core.rbac import Permission, user_role_key
from app.database import get_db
from app.deps import require_permission, require_roles
from app.models.enums import OperationAction, UserRole
from app.models import PriceRule, Product, User
from app.schemas.price_rule import (
    PriceRuleBatchBody,
    PriceRuleBatchOut,
    PriceRuleCreate,
    PriceRuleOut,
    PriceRuleUpdate,
    PriceRuleBatchChange,
)
from app.services.operation_log_service import write_log
from app.services.soft_delete import ensure_alive
from app.services import usage_service
from datetime import datetime

router = APIRouter(prefix="/price-rules", tags=["price-rules"])

# 一次批量调价最多**逐条**写多少行审计日志（与响应里的 changes 上限一致）。
# 为什么要有上限：`shipper_ids`/`product_ids` 都留空时组合可能上万，
# 逐条记会把日志表冲掉；但**一条都不记**更糟——价格改了却查不到是谁改的。
# 所以：能逐条记就逐条记，超了补一行汇总（写明"只记了前 N 条"），
# 让"改了价但日志里什么都没有"这种状态**不可能出现**。
MAX_LOGGED_CHANGES = 200


def _log_price_changes(
    db: Session,
    *,
    operator_id: int,
    mode: str,
    body: "PriceRuleBatchBody",
    changes: list[PriceRuleBatchChange],
    total: int,
) -> None:
    """把这次调价的**每一条改动**写进操作日志（谁在什么时候把哪个批发商的哪个商品从多少改成多少）。"""
    for c in changes[:MAX_LOGGED_CHANGES]:
        write_log(
            db,
            operator_id=operator_id,
            order_id=None,
            action=OperationAction.PRICE_RULE_UPSERT,
            change_payload={
                "scope": "batch",
                "mode": mode,
                "shipper": c.shipper_name,
                "product": c.product_name,
                "before": None if c.before is None else str(c.before),
                "after": str(c.after),
            },
        )
    if total > MAX_LOGGED_CHANGES:
        write_log(
            db,
            operator_id=operator_id,
            order_id=None,
            action=OperationAction.PRICE_RULE_UPSERT,
            change_payload={
                "scope": "batch",
                "mode": mode,
                "changes": total,
                "logged": MAX_LOGGED_CHANGES,
                "note": f"这次共 {total} 条改动，日志里只逐条记了前 {MAX_LOGGED_CHANGES} 条",
            },
        )


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
    current: User = Depends(require_permission(Permission.PRICE_RULE_MANAGE)),
) -> PriceRuleBatchOut:
    """批量调价：多批发商 × 多商品 一次写价。
    - fixed：所有组合统一单价；percent：按商品默认售价百分比；adjust：在【当前生效价】基础上按百分比涨/降。
    - 已有规则自动覆盖；shipper_ids/product_ids 为空 = 全部批发商/全部商品。

    ⚠️ 2026-09-19 起**没有** `mode="tier"`（取商品自身"批发价第 N 档"那一档）：`products.tier_prices`
    是"看着像批发价、下单谁都不照它走"的概念，已被用户拍板删掉，传 `tier` 由 schema 直接 422 拒掉。
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
    # ⚠️ **点名的对象必须真的存在、而且商品不能在回收站里**（2026-09-21 修的真实缺陷）：
    #    在选品页/商品管理里，`is_deleted=True` 的商品**对谁都不显示**，下单也选不到它 ——
    #    所以给这种商品写出来的价"对谁都不生效"，而返回与审计日志都写着"价格已设置"，
    #    用户以为调过价了（这正是本仓列为最贵的一类：**静默无效**）。
    #    批量动作**不做部分成功**（仓库既有纪律）：有一个对不上就整批拒绝、并点名是哪几个，
    #    否则用户核对 N 行时看不出"少调了哪一个"。
    if body.product_ids:
        alive = {p.id for p in products if not p.is_deleted}
        missing_p = [pid for pid in body.product_ids if pid not in alive]
        if missing_p:
            raise HTTPException(
                status_code=400,
                detail=f"这些商品不存在或已在回收站，先确认商品再调价（否则这条价对谁都不生效）：{missing_p}",
            )
    if body.shipper_ids:
        found_s = {u.id for u in shippers}
        missing_s = [sid for sid in body.shipper_ids if sid not in found_s]
        if missing_s:
            raise HTTPException(
                status_code=400,
                detail=f"这些账号不存在或不是批发商（专属价只对批发商有意义）：{missing_s}",
            )

    # ⚠️ **服务端**必须有全表护栏（2026-09-19 审计 K5 复核后修）：
    #    这一行原来只写在客户端（`AiWritePricing.kt`），于是任何直接打接口的人
    #    （旧客户端、脚本、以后新加的界面）**两个范围都留空**就等于"给全部批发商 × 全部商品调价"——
    #    一次请求改掉整张价格表，而且卡片/返回里只报"改了 N 条"。
    #    闸门必须长在服务端：客户端那道只是提前告知，不是防线。
    if not body.shipper_ids and not body.product_ids:
        raise HTTPException(
            status_code=400,
            detail="要指定范围：批发商或商品至少选一个。两个都不选等于给**全部批发商 × 全部商品**调价，"
                   "一次改掉整张价格表——请点名范围后再提交。",
        )

    def _price(p: Product, pr: "PriceRule | None") -> Decimal | None:
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
            # ⚠️ **软删的规则不算"当前生效价"**（2026-09-19 审计「声明式 CRUD」专项，高）：
            #    下面那次查询故意不过滤 `is_deleted`（唯一约束要求复用那一行），
            #    但一条软删的规则**对谁都不生效**：`GET /price-rules` 过滤它、下单页拿不到它、
            #    客户实际按默认价成交。此时把它的旧价当基准，等于"在一份看不见的价上打折"：
            #    AI 的确认卡（按可见价算）写「10.00 → 8.50」，库里却写 17.00（= 隐藏的 20.00 × 85%），
            #    而且这个数**用户核对不出来**——卡上那个 8.50 是他唯一能看到的依据。
            base = p.default_unit_price or Decimal("0")
            if pr is not None and not pr.is_deleted:
                base = pr.special_unit_price
            raw = base * (Decimal("100") + body.adjust_percent) / Decimal("100")
            return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        # mode 只有 fixed / percent / adjust 三档（schema 的 `Literal` 把别的取值挡在 422），
        # 上面三分支已经把三条路都走完了 —— 这个 return 只为"函数每条路径都有返回值"而留。
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
                # ⚠️ 命中**软删**的那一行时必须一起**复活**它（2026-09-19 审计 K4 复核后修）。
                #    上面那次查询故意不过滤 `is_deleted`（唯一约束要求复用那一行），
                #    但原来只写了价、没把 `is_deleted` 置回 False →
                #    ① `GET /price-rules` 过滤软删 → 批量调完价**列表里看不到**，
                #       用户以为"改价失败了"；
                #    ② `adjust` 模式的基准读的就是 `pr.special_unit_price`（这个文件上面那几行），
                #       于是百分比在**一份看不见的价**上反复滚。
                #    `create_price_rule` 的复活分支（本文件下方）一直是写全的，这里对齐它。
                if pr.is_deleted:
                    pr.is_deleted = False
                    pr.deleted_at = None
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
    # ⚠️ 审计必须和写入在**同一个事务**里：分开提交时，"写价成功但日志没落"会留下
    # 一笔无迹可查的价格改动，而这恰恰是最需要追溯的一类改动（AI 的表格批量调价
    # 一次会打好几个请求，全靠日志把每一行还原出来）。
    _log_price_changes(
        db, operator_id=current.id, mode=body.mode, body=body, changes=changes, total=count
    )
    db.commit()
    return PriceRuleBatchOut(count=count, skipped=skipped, changes=changes)


@router.get("", response_model=list[PriceRuleOut])
def list_price_rules(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.DISPATCHER, UserRole.SHIPPER)),
    shipper_id: int | None = None,
    product_id: int | None = None,
) -> list[PriceRuleOut]:
    """专属价列表。三个筛选条件的关系是**先锁角色、再叠加**，谁也绕不过角色那一层：

    1. 批发商（货主）**先**被锁成只看自己的（`PriceRule.shipper_id == user.id`）——
       所以货主带**别人的** `shipper_id` 只会得到**空列表**，拿不到别人的价；
    2. 再叠加 `shipper_id`（只看某个批发商，派单员用来做「这个批发商都有哪些专属价」）；
    3. 再叠加 `product_id`（只看某个商品，用来做「这个商品各家批发商分别什么价」）——
       App 新增的「按商品看各批发商价」页要用它：以前只能按 `shipper_id` 筛，
       客户端要凑出"这一个商品的所有专属价"就只能拉全表再自己过滤（正是本轮修掉的那种毛病）。

    两个筛选是**并列 AND**（同时给就是"这个批发商的这个商品"），都不给 = 这个角色能看的全部。
    """
    # 2026-09-22 统一规则：常用度 → 先创建的在前
    # ⚠️ 这里的用户参数叫 `user`（不是 `current`）—— 常用度要按**谁在看**算，
    #    所以实参得跟着这个函数的形参名走（写错了就是每次调用都 500，编译期看不出来）。
    q = usage_service.with_popularity(
        select(PriceRule).where(PriceRule.is_deleted.is_(False)),
        PriceRule, usage_service.KIND_PRICE_RULE, user,
    )
    # 批发商（货主）只读自己的专属价，用于下单时展示实际价格；派单员可看全部
    if user_role_key(user) == "shipper":
        q = q.where(PriceRule.shipper_id == user.id)
    if shipper_id is not None:
        q = q.where(PriceRule.shipper_id == shipper_id)
    if product_id is not None:
        q = q.where(PriceRule.product_id == product_id)
    rows = list(db.scalars(q).all())
    return [_rule_to_out(pr, db) for pr in rows]


@router.post("", response_model=PriceRuleOut, status_code=status.HTTP_201_CREATED)
def create_price_rule(
    body: PriceRuleCreate,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.PRICE_RULE_MANAGE)),
) -> PriceRuleOut:
    # ⚠️ **先确认这两个对象真的在**（2026-09-21 修的真实缺陷）：这一条原来只查"这个货主+商品的
    #    规则是不是已经存在"，完全没查**商品/货主本身存不存在**。后果是给一个不存在（或已软删）
    #    的商品编号设价：接口 201、审计日志写着"价格已设置"，而那个商品在选品页/下单页**对谁都不显示**
    #    （列表按 `is_deleted=False` 过滤）→ 这条价从写进去那一刻起就**对谁都不生效**，
    #    而界面上看不出任何异常。宁可当场拒绝，也不许写一条"看起来设过了"的价。
    product = db.get(Product, body.product_id)
    if product is None or product.is_deleted:
        raise HTTPException(
            status_code=400,
            detail="这个商品不存在或在回收站里，先确认商品再设价（否则这条价对谁都不生效）",
        )
    if db.get(User, body.shipper_id) is None:
        raise HTTPException(status_code=400, detail="这个账号不存在，请先确认货主/批发商")
    # ⚠️ 这里**故意不过滤 is_deleted**：软删的行仍占着 (shipper_id, product_id) 唯一约束，
    # 所以再给这个货主设一次这个商品的价格必须**复活那一行**，而不是插一条新的
    # （插会直接撞唯一约束 500）。复活 = 用户表达的意思，也不需要恢复这个多余动作。
    exists = db.scalars(
        select(PriceRule).where(
            PriceRule.shipper_id == body.shipper_id,
            PriceRule.product_id == body.product_id,
        )
    ).first()
    if exists and not exists.is_deleted:
        raise HTTPException(status_code=400, detail="该货主与商品的价格规则已存在")
    if exists is not None:
        exists.is_deleted = False
        exists.deleted_at = None
        exists.special_unit_price = body.special_unit_price
        db.commit()
        db.refresh(exists)
        return _rule_to_out(exists, db)
    pr = PriceRule(
        shipper_id=body.shipper_id,
        product_id=body.product_id,
        special_unit_price=body.special_unit_price,
    )
    db.add(pr)
    db.flush()
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.PRICE_RULE_UPSERT,
        change_payload={
            "scope": "single",
            "shipper": _name_of(db, body.shipper_id),
            "product": _product_name_of(db, body.product_id),
            "before": None,
            "after": str(body.special_unit_price),
        },
    )
    db.commit()
    db.refresh(pr)
    return _rule_to_out(pr, db)


@router.get("/{rule_id}", response_model=PriceRuleOut)
def get_price_rule(rule_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission(Permission.PRICE_RULE_MANAGE))) -> PriceRuleOut:
    pr = db.get(PriceRule, rule_id)
    if pr is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    return _rule_to_out(pr, db)


def _name_of(db: Session, user_id: int | None) -> str:
    """日志里要写**人看得懂的名字**，不是编号（编号在审计页上没有任何意义）。"""
    u = db.get(User, user_id) if user_id else None
    return ((u.full_name or u.phone or "") if u else "")[:64]


def _product_name_of(db: Session, product_id: int | None) -> str:
    p = db.get(Product, product_id) if product_id else None
    return ((p.name or "") if p else "")[:64]


@router.patch("/{rule_id}", response_model=PriceRuleOut)
def update_price_rule(
    rule_id: int,
    body: PriceRuleUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.PRICE_RULE_MANAGE)),
) -> PriceRuleOut:
    pr = db.get(PriceRule, rule_id)
    if pr is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    # ⚠️ 软删的专属价**改不了**（R11-F4）：界面按 is_deleted 过滤，看不见它；
    #    改它只会得到一句「已完成」+ 一条价格变动日志，而批发商看到的价格**一个字都没变**。
    #    （要重新启用这条价：`POST /price-rules` 传同一个（批发商+商品）会复活它。）
    ensure_alive(pr, "批发商专属价", "POST /price-rules 重新设一次这个价（会复活这一行）")
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
    before = pr.special_unit_price
    if body.special_unit_price is not None:
        pr.special_unit_price = body.special_unit_price
    if before != pr.special_unit_price:
        # ⚠️ 只在价格**真的变了**时记日志：把"只改了别的字段"也记成一次调价，
        # 会让审计页被无意义的行淹没（那一页只显示最近 60 条）。
        write_log(
            db,
            operator_id=current.id,
            order_id=None,
            action=OperationAction.PRICE_RULE_UPSERT,
            change_payload={
                "scope": "single",
                "shipper": _name_of(db, pr.shipper_id),
                "product": _product_name_of(db, pr.product_id),
                "before": None if before is None else str(before),
                "after": str(pr.special_unit_price),
            },
        )
    db.commit()
    db.refresh(pr)
    return _rule_to_out(pr, db)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_price_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.PRICE_RULE_MANAGE)),
) -> None:
    pr = db.get(PriceRule, rule_id)
    if pr is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    # 删掉一条专属价 = 这个批发商回到商品默认价，**这也是价格变动**，必须留痕。
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.PRICE_RULE_UPSERT,
        change_payload={
            "scope": "delete",
            "shipper": _name_of(db, pr.shipper_id),
            "product": _product_name_of(db, pr.product_id),
            "before": None if pr.special_unit_price is None else str(pr.special_unit_price),
            "after": "（删除专属价，回到商品默认价）",
        },
    )
    # 伪装删除（v3.26）：撤回来就是把这条专属价恢复，价格一个字节都不差。
    # 行还占着 (shipper_id, product_id) 唯一约束，见 create 里的复活分支。
    pr.is_deleted = True
    pr.deleted_at = utc_now_naive()
    db.commit()