from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status

from app.core.pagination import finish_page
from app.core.user_search import name_or_phone_like
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import Permission, user_role_key
from app.core.security import hash_password
from app.database import get_db
from app.deps import CurrentUser, require_permission
from app.models import Product, User
from app.models.user import normalize_billing_mode, resolve_billing_mode
from app.models.enums import OperationAction, UserRole
from app.schemas.product_visibility import (
    ProductVisibilityIn,
    ProductVisibilityOut,
    replace_visibility,
    visibility_of,
)
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.services.soft_delete import del_suffix
from app.services.operation_log_service import write_log
from app.services.auth_service import revoke_tokens_and_sockets
from app.services import usage_service

router = APIRouter(prefix="/users", tags=["users"])

# 司机端（司机查看自己/列表时）工资一律隐藏：工资仅派单员可见
def _to_out(u: User, viewer: User) -> User:
    out = UserOut.model_validate(u)
    is_dispatcher = user_role_key(viewer) == UserRole.DISPATCHER.value
    if not is_dispatcher:
        out.salary = None
    # 计费规则：怎么算钱那句话只由 `driver_pay` 生成（界面/确认卡/账单同源，不各写一套）
    if user_role_key(u) == UserRole.DRIVER.value:
        from app.services.driver_pay import pay_summary_for, rule_of_user, snapshot_mode

        rule = rule_of_user(u)
        out.driver_rule_id = rule.rule_id if rule is not None else None
        out.driver_rule_name = rule.name if rule is not None else ""
        # ⚠️ 非派单员不给金额：规则里带着工资数，而"工资仅派单员可见"是既有硬约定
        out.pay_summary = pay_summary_for(u, include_money=is_dispatcher)
        # 「他按不按单拿钱」——派单端据此决定要不要显示运费框，**必须与账单同源**。
        # 客户端原来自己按 `billing_mode ?: 车型` 猜（与 `resolve_billing_mode` 一致，但
        # 少了"规则优先"这一层）：挂着**运费提成**规则的大车司机被判成工资制 → 运费框不显示
        # → 运费永远是空的 → 提成 = 0 × 比例 = 0 → 送达时 `pay.total <= 0` 连账单都不生成
        # （司机白跑一趟，账面上查不到任何异常）。这里直接问 `snapshot_mode` ——
        # 它的文档里写明消费点之一就是"运费对他可不可见"（`order_response` 的 `freight_visible`）。
        out.pays_per_order = snapshot_mode(u) == "PIECE"
    return out


@router.get("/me", response_model=UserOut)
def read_me(current: CurrentUser, db: Session = Depends(get_db)) -> UserOut:
    out = _to_out(current, current)
    # 「他现在有没有按单的账要看」（司机端「我的账单」入口的判据）：
    # ⚠️ 只有在**自己的** /me 上算 —— 列表页不需要它，而它要查一次 driver_bills。
    #    判据本身在 `driver_pay`（钱的唯一口径处），这里只负责把它填进出参。
    if user_role_key(current) == UserRole.DRIVER.value:
        from app.services.driver_pay import has_per_order_earnings

        out.has_per_order_earnings = has_per_order_earnings(db, current)
    return out


@router.get("", response_model=list[UserOut])
def list_users(
    response: Response,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.USER_MANAGE)),
    role: UserRole | None = Query(None),
    is_member: bool | None = Query(None, description="会员筛选（is_member=true 取高级货主）"),
    q: str | None = Query(None, description="按姓名或手机号模糊搜索（手机号后 4 位也行）"),
    skip: int = 0,
    limit: int = Query(100, le=500),
) -> list[User]:
    # 多取一行判截断（2026-09-19 外部完整检查 §9.1）：账号列表超过 100 时界面不说，
    # 派单员会以为"没有这个账号"再去建一个（而同号会撞唯一约束）。
    # 2026-09-22 统一规则：**常用度 → 先创建的在前**（用户：「拉批发商或普通货主……
    # 先按称谓分好类，再按常用的顺序排」——分组由调用方按 `is_member` 做，这里只管顺序）
    stmt = usage_service.with_popularity(
        select(User), User, usage_service.KIND_USER, current
    ).offset(skip).limit(limit + 1)
    if role is not None:
        stmt = stmt.where(User.role == role)
    if is_member is not None:
        stmt = stmt.where(User.is_member.is_(is_member))
    # 姓名/手机号搜索只有一份实现（`app/core/user_search.py`）：账号名册、客户档案、
    # 以及 App 侧账本仪表盘三处必须是同一个口径。
    pred = name_or_phone_like(User.full_name, User.phone, q)
    if pred is not None:
        stmt = stmt.where(pred)
    rows = [_to_out(u, current) for u in db.scalars(stmt).all()]
    return finish_page(rows, limit, response)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.USER_MANAGE)),
) -> User:
    if db.scalars(select(User).where(User.phone == body.phone)).first():
        raise HTTPException(status_code=400, detail="该手机号已存在")
    un = body.username or body.phone
    if db.scalars(select(User).where(User.username == un)).first():
        raise HTTPException(status_code=400, detail="该用户名已存在")
    u = User(
        username=un,
        phone=body.phone,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
        is_member=body.is_member,
        salary=body.salary,
        vehicle_type=(body.vehicle_type or "").strip() or None,
        billing_mode=resolve_billing_mode(
            (body.vehicle_type or "").strip() or None,
            body.billing_mode or None,
        ),
    )
    db.add(u)
    db.flush()
    # 账号的新建/改动以前也不进操作日志（`USER_CREATE` 枚举存在但没人用）——
    # "谁建的这个账号、谁给他改的权限"查不到。补上（v3.26）。
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.USER_CREATE,
        change_payload={
            "user_id": u.id,
            "username": u.username,
            "full_name": u.full_name,
            "phone": u.phone,
            "role": u.role,
            "is_member": u.is_member,
            # ⛔ 绝不记密码（连哈希也不记）：操作日志是给人看的审计页，不是凭据库
        },
    )
    db.commit()
    db.refresh(u)
    return _to_out(u, current)


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, current: CurrentUser, db: Session = Depends(get_db)) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    if user_role_key(current) != UserRole.DISPATCHER.value and current.id != user_id:
        raise HTTPException(status_code=403, detail="无权访问")
    return _to_out(u, current)


@router.get("/{user_id}/product-visibility", response_model=ProductVisibilityOut)
def get_product_visibility(
    user_id: int,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> ProductVisibilityOut:
    """某个货主/批发商能看到哪些商品（白名单）。派单员在用户编辑页回显它。"""
    if user_role_key(current) != UserRole.DISPATCHER.value and current.id != user_id:
        raise HTTPException(status_code=403, detail="无权访问")
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    return visibility_of(db, user_id)


@router.put("/{user_id}/product-visibility", response_model=ProductVisibilityOut)
def set_product_visibility(
    user_id: int,
    body: ProductVisibilityIn,
    current: User = Depends(require_permission(Permission.USER_MANAGE)),
    db: Session = Depends(get_db),
) -> ProductVisibilityOut:
    """整份设置某个货主/批发商的可见商品（**白名单**：勾了的才给他看）。

    ⚠️ 两条拒绝，都是为了不让用户"以为配好了、其实没有"：
    1. `scope=custom` 但一个商品都没勾 → 拒绝（那等于让他什么都看不到；
       真要做这件事，是先把 scope 设成 custom 再逐个勾，而不是空着交上来）；
    2. 勾了但**所有**编号都不在商品库里（全被删了）→ 拒绝并说明。
    只挡这两条，是因为它们都会让界面显示"已设置"而实际效果是"空目录"。
    """
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    if user_role_key(u) not in (UserRole.SHIPPER.value,):
        raise HTTPException(
            status_code=400,
            detail="商品可见范围只对货主/批发商有意义（派单员不受限，否则改错了没人能改回来）",
        )
    if body.scope == "custom":
        if not body.product_ids:
            raise HTTPException(
                status_code=400,
                detail="选了「只给勾选的商品」却一个都没勾 —— 那样他打开选品页会是空的。"
                "请至少勾一个商品，或者改回「全部商品」。",
            )
        alive = set(
            db.scalars(
                select(Product.id).where(
                    Product.id.in_(body.product_ids), Product.is_deleted.is_(False)
                )
            ).all()
        )
        if not alive:
            raise HTTPException(
                status_code=400,
                detail="勾选的商品都不在商品库里了（可能已被删除），请重新勾选",
            )
    out = replace_visibility(db, u, body)
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.PRODUCT_VISIBILITY_SET,
        change_payload={
            "user_id": u.id,
            "user_name": u.full_name or u.phone,
            "scope": out.scope,
            "product_ids": out.product_ids,
            "product_count": len(out.product_ids),
        },
    )
    db.commit()
    return out


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    background_tasks: BackgroundTasks,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    if user_role_key(current) != UserRole.DISPATCHER.value and current.id != user_id:
        raise HTTPException(status_code=403, detail="无权访问")
    is_dispatcher = user_role_key(current) == UserRole.DISPATCHER.value
    if not is_dispatcher and current.id != user_id:
        raise HTTPException(status_code=403, detail="无权访问")
    if not is_dispatcher and (body.role is not None or body.is_active is not None or body.phone is not None):
        raise HTTPException(status_code=403, detail="无权修改他人的角色、手机号或状态")

    # 改前 → 改后逐字段记（不含密码：审计页是给人看的，不是凭据库）
    before = {
        "phone": u.phone,
        "full_name": u.full_name,
        "role": u.role,
        "is_active": u.is_active,
        "is_member": u.is_member,
        "salary": str(u.salary) if u.salary is not None else None,
        "billing_mode": u.billing_mode,
        "vehicle_type": u.vehicle_type,
    }
    if body.phone is not None:
        u.phone = body.phone
    if body.password is not None:
        u.password_hash = hash_password(body.password)
        # 改密码 → 旧令牌立刻失效 + **长连接立刻断开**（2026-09-19 审计；外部完整检查 C-3 补后半）：
        # 否则'改密码'这个最自然的止损动作，对已经泄漏的令牌在 24 小时内完全无效，
        # 而那条已经建起来的 socket 更是继续收推送。
        revoke_tokens_and_sockets(db, u, background_tasks, "改密码")
    if body.full_name is not None:
        u.full_name = body.full_name
    if body.role is not None and is_dispatcher:
        u.role = body.role
    if body.is_active is not None and is_dispatcher:
        u.is_active = body.is_active
        # 停用一个账号 → **已发出的令牌立刻失效 + 断开长连接**（2026-09-19 审计）：
        # 在这之前 `deps` 只查 `is_active`，而 JWT 是自包含的，所以停用只挡住"下一次登录"，
        # 已经登录中的会话要等令牌自然过期（24h）。丢手机/离职场景下这是最要紧的一下。
        if body.is_active is False:
            revoke_tokens_and_sockets(db, u, background_tasks, "账号被停用")
    if body.is_member is not None and is_dispatcher:
        u.is_member = body.is_member
    # 安全修复：工资/计费方式/车型仅派单员可改（司机自改会绕过结算规则、篡改工资）
    if (body.salary is not None or body.billing_mode is not None or body.vehicle_type is not None) and not is_dispatcher:
        raise HTTPException(status_code=403, detail="仅派单员可修改工资/计费方式/车型")
    if body.salary is not None and user_role_key(u) == UserRole.DRIVER.value:
        u.salary = body.salary
    # 司机车型/计费方式：仅司机角色有意义；billing_mode 缺省由车型自动推导
    if user_role_key(u) == UserRole.DRIVER.value:
        if body.vehicle_type is not None:
            u.vehicle_type = (body.vehicle_type or "").strip() or None
        if body.billing_mode is not None:
            # ⚠️ 必须归一（见 `normalize_billing_mode` 的注释）：这里以前是 `.strip()` 原样落库，
            # 于是"AI 用小写、页面用大写"两套写法同时存在于库里，
            # 而各消费点的大小写敏感判据互相矛盾（运费录不进、结算漏单、派单页不显示运费框）。
            u.billing_mode = normalize_billing_mode(body.billing_mode)
        elif body.vehicle_type is not None:
            u.billing_mode = resolve_billing_mode(u.vehicle_type, None)

    after = {
        "phone": u.phone,
        "full_name": u.full_name,
        "role": u.role,
        "is_active": u.is_active,
        "is_member": u.is_member,
        "salary": str(u.salary) if u.salary is not None else None,
        "billing_mode": u.billing_mode,
        "vehicle_type": u.vehicle_type,
    }
    changes = [
        {"field": k, "from": before[k], "to": after[k]} for k in before if before[k] != after[k]
    ]
    if changes:
        write_log(
            db,
            operator_id=current.id,
            order_id=None,
            action=OperationAction.USER_UPDATE,
            change_payload={"user_id": u.id, "username": u.username, "changes": changes},
        )
    db.commit()
    db.refresh(u)
    return _to_out(u, current)


@router.post("/{user_id}/swap-shipper-driver", response_model=UserOut)
def swap_shipper_driver(
    user_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.USER_MANAGE)),
) -> User:
    """货主 ↔ 司机身份切换（派单员操作）。派单员账号不可切换。"""
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    rk = user_role_key(u)
    if rk == UserRole.DISPATCHER.value:
        raise HTTPException(status_code=400, detail="不能变更派单员角色")
    if rk == UserRole.SHIPPER.value:
        u.role = UserRole.DRIVER
    elif rk == UserRole.DRIVER.value:
        u.role = UserRole.SHIPPER
    else:
        raise HTTPException(status_code=400, detail="仅支持货主与司机身份切换")
    db.commit()
    db.refresh(u)
    return _to_out(u, current)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    current: User = Depends(require_permission(Permission.USER_MANAGE)),
    db: Session = Depends(get_db),
) -> None:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    if u.is_active is False and str(u.phone or "").endswith(f"_del{u.id}"):
        raise HTTPException(status_code=400, detail="这个账号已经删过了")
    orig_phone, orig_username = u.phone, u.username
    u.is_active = False
    # 释放手机号/用户名（允许用同号重新建号），数据仍保留可追溯
    u.phone = del_suffix(u.phone, u.id, 32)   # 列宽 String(32)：先截断再拼，别再让它撞 Data too long
    u.username = del_suffix(u.username, u.id, 32)   # 列宽 String(32)
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.USER_DELETE,
        change_payload={
            "user_id": u.id,
            "username": orig_username,
            "phone": orig_phone,
            "note": "软删除（可 POST /users/{id}/restore 恢复），手机号已释放",
        },
    )
    db.commit()


@router.post("/{user_id}/restore", response_model=UserOut)
def restore_user(
    user_id: int,
    current: User = Depends(require_permission(Permission.USER_MANAGE)),
    db: Session = Depends(get_db),
) -> User:
    """把删掉的账号恢复回来（`DELETE /{id}` 的逆操作）。

    删除时手机号/用户名被加了 `_del{id}` 后缀（为了释放号码给新账号用），
    这里**把后缀去掉**还原。冲突处理：如果那个号码已经被别人注册了，
    只恢复账号与身份、**保留现在的号码**，并把这件事写在返回里——
    硬抢回来会把另一个账号顶掉，那是更大的错。
    """
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    suffix = f"_del{u.id}"
    restored: list[str] = []
    conflicts: list[str] = []
    if isinstance(u.phone, str) and u.phone.endswith(suffix):
        want = u.phone[: -len(suffix)]
        taken = db.scalars(select(User).where(User.phone == want, User.id != u.id)).first()
        if taken is None:
            u.phone = want
            restored.append("手机号")
        else:
            conflicts.append(f"手机号 {want} 已经被别的账号占用，保留了当前的 {u.phone}")
    if isinstance(u.username, str) and u.username.endswith(suffix):
        u.username = u.username[: -len(suffix)]
        restored.append("用户名")
    u.is_active = True
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.USER_RESTORE,
        change_payload={
            "user_id": u.id,
            "username": u.username,
            "phone": u.phone,
            "restored": restored,
            "conflicts": conflicts,
        },
    )
    db.commit()
    db.refresh(u)
    return _to_out(u, current)