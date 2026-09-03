from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import Permission, user_role_key
from app.core.security import hash_password
from app.database import get_db
from app.deps import CurrentUser, require_permission
from app.models import User
from app.models.user import resolve_billing_mode
from app.models.enums import UserRole
from app.schemas.user import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])

# 司机端（司机查看自己/列表时）工资一律隐藏：工资仅派单员可见
def _to_out(u: User, viewer: User) -> User:
    out = UserOut.model_validate(u)
    if user_role_key(viewer) != UserRole.DISPATCHER.value:
        out.salary = None
    return out


@router.get("/me", response_model=UserOut)
def read_me(current: CurrentUser) -> UserOut:
    return _to_out(current, current)


@router.get("", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.USER_MANAGE)),
    role: UserRole | None = Query(None),
    is_member: bool | None = Query(None, description="会员筛选（is_member=true 取高级货主）"),
    skip: int = 0,
    limit: int = Query(100, le=500),
) -> list[User]:
    q = select(User).order_by(User.id.desc()).offset(skip).limit(limit)
    if role is not None:
        q = q.where(User.role == role)
    if is_member is not None:
        q = q.where(User.is_member.is_(is_member))
    return [_to_out(u, current) for u in db.scalars(q).all()]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.USER_MANAGE)),
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
        billing_mode=(
            body.billing_mode
            if body.billing_mode
            else resolve_billing_mode((body.vehicle_type or "").strip() or None, None)
        ),
    )
    db.add(u)
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


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
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

    if body.phone is not None:
        u.phone = body.phone
    if body.password is not None:
        u.password_hash = hash_password(body.password)
    if body.full_name is not None:
        u.full_name = body.full_name
    if body.role is not None and is_dispatcher:
        u.role = body.role
    if body.is_active is not None and is_dispatcher:
        u.is_active = body.is_active
    if body.is_member is not None and is_dispatcher:
        u.is_member = body.is_member
    if body.salary is not None and user_role_key(u) == UserRole.DRIVER.value:
        u.salary = body.salary
    # 司机车型/计费方式：仅司机角色有意义；billing_mode 缺省由车型自动推导
    if user_role_key(u) == UserRole.DRIVER.value:
        if body.vehicle_type is not None:
            u.vehicle_type = (body.vehicle_type or "").strip() or None
        if body.billing_mode is not None:
            u.billing_mode = (body.billing_mode or "").strip() or None
        elif body.vehicle_type is not None:
            u.billing_mode = resolve_billing_mode(u.vehicle_type, None)

    db.commit()
    db.refresh(u)
    return _to_out(u, current)


@router.post("/{user_id}/swap-shipper-driver", response_model=UserOut)
def swap_shipper_driver(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.USER_MANAGE)),
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
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.USER_MANAGE)),
) -> None:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    u.is_active = False
    db.commit()
