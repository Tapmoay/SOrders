"""预订单（订单模板）——「预设好的订单，参数没变直接下单」（用户 2026-09-22）。

## 这个文件只做一件事
把"常用的那一单"**存下来 / 改掉 / 删掉 / 恢复**。它**不生成订单** ——
真下单走已有的 `POST /orders`（与手工下单同一条路），所以这里一行都不碰
订单状态机、库存、账本。见 `models/order_template.py` 文件头那三条。

## 三处与本仓库其他 CRUD 一致的做法（不要各写一套）
1. **列表排序走 `usage_service.with_popularity`**（常用度优先 → 先创建在前）：
   2026-09-22 定的统一列表规则；`POST /{id}/use` 是那一份计数的唯一写入点。
2. **删除一律软删**（`SoftDeleteMixin`）：`name` 加 `_del{id}` 后缀给出可见痕迹，
   `POST /{id}/restore` 是它的逆操作；**软删的预设单改不了**（`ensure_alive`）。
3. **每个写端点都写审计**（`operation_log_service.write_log`）：预设单会变成真订单，
   "这条预设是谁建的、谁改的、谁删的"必须查得到。

## ⚠️ 一个刻意的选择：`PATCH` 里"没传"与"传 null"不是一回事
字符串/金额字段沿用全项目的写法（`None` = 不改这一项）；
但 `shipper_id` **必须能清空**（从"固定货主"改回"下单时再选"），
所以它走 `model_fields_set`：**键出现了就按你给的值写**（`null` = 清空）。
混着用的后果很具体：货主改不掉，用户只能删了重建。
"""

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
# 「名册里没有的分类名 → 补进名册」只有这一份实现（与商品那一侧同一个做法）
from app.api.v1.order_template_categories import ensure_category
from app.models import OrderTemplate, User
from app.models.enums import OperationAction, UserRole
from app.schemas.order_template import (
    MAX_LINES,
    OrderTemplateCreate,
    OrderTemplateLine,
    OrderTemplateOut,
    OrderTemplateUpdate,
)
from app.services import usage_service
from app.services.operation_log_service import write_log
from app.services.order_money import q2
from app.services.soft_delete import del_suffix, ensure_alive
router = APIRouter(prefix="/order-templates", tags=["order-templates"])

#: 预设运费的合理区间（与全项目金额边界同一口径，`Numeric(12,2)`）。
MAX_FEE = Decimal("9999999.99")


def _money(raw: str | None, field: str) -> Decimal | None:
    """`None`/空串 = **不预设**（返回 None，不是 0）；认不出来的数字直接拒绝。

    ⚠️ 空串与 `0` 是两件事：前者是"这单不预设运费"，后者是"免运费"。
    把空串当 0 会让每一张没填运费的预设单都变成免运费单。
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        v = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{field}填的不是一个数字：{raw}") from exc
    if v < 0 or v > MAX_FEE:
        raise HTTPException(status_code=400, detail=f"{field}超出可填范围（0 ~ {MAX_FEE}）")
    return q2(v)


def _clean_lines(rows: list[OrderTemplateLine] | None) -> list[dict]:
    """把入参行归一成**入库用的那份**（唯一的行规整实现，create 与 update 共用）。

    三条判据：
    · **没有商品的行直接拒绝**（不静默丢掉）—— 少一行货的预设单会在下单时变成
      "少订了一样"，而两边都不报错；
    · 同一个商品出现两次 → 拒绝（让用户自己合成一行，⛔ 不替他相加：数量错了看不出来）；
    · 上限 `MAX_LINES`（schema 已经卡了一道，这里再兜一次：AI 那条路可能绕过 schema）。
    """
    out: list[dict] = []
    seen: dict[int, str] = {}
    for i, r in enumerate(rows or [], start=1):
        if not r.product_id:
            raise HTTPException(status_code=400, detail=f"第 {i} 行没有选商品")
        pid = int(r.product_id)
        if pid in seen:
            raise HTTPException(
                status_code=400,
                detail=f"「{seen[pid] or pid}」在第 {i} 行又出现了一次，请合成一行（数量相加）",
            )
        seen[pid] = (r.name or "").strip()
        out.append(
            {
                "product_id": pid,
                # 名字/单位是**快照**：商品改名或下架之后，预设单里仍要看得见"当时选的是哪一个"
                "name": (r.name or "").strip()[:64],
                "unit": (r.unit or "").strip()[:16],
                "qty": max(1, min(int(r.qty or 1), 100_000)),
            }
        )
    if len(out) > MAX_LINES:
        raise HTTPException(status_code=400, detail=f"一张预设单最多 {MAX_LINES} 行货（现在 {len(out)} 行）")
    return out


def _shipper_names(db: Session, rows: list[OrderTemplate]) -> dict[int, str]:
    """一次查完这一页要显示的货主名（⛔ 不要每行发一个查询）。

    ⚠️ 账号的显示名是 `full_name or phone`（`User` **没有** `name` 字段 ——
    全项目都这么取：`order_response` / `vehicles` / `stats_service` 同一口径）。
    """
    ids = {int(r.shipper_id) for r in rows if r.shipper_id}
    if not ids:
        return {}
    found = db.scalars(select(User).where(User.id.in_(ids))).all()
    return {int(u.id): (u.full_name or u.phone or "") for u in found}


def _out(row: OrderTemplate, names: dict[int, str]) -> OrderTemplateOut:
    """出参拼装**只有这一处**（列表/建/改/恢复四条路共用，免得四个地方各拼一遍）。"""
    return OrderTemplateOut(
        id=row.id,
        name=row.name,
        shipper_id=row.shipper_id,
        shipper_name=names.get(int(row.shipper_id)) if row.shipper_id else None,
        category=row.category or "",
        origin_address=row.origin_address or "",
        address=row.address or "",
        receiver_name=row.receiver_name or "",
        receiver_phone=row.receiver_phone or "",
        # ⚠️ **不让 Pydantic 从 ORM 取这个字段**：`Numeric` 出来的是 Decimal，
        #    直接序列化会变成 `12.3` 这种少一位的写法。金额出参一律两位小数（全项目同一口径）。
        freight_fee=None if row.freight_fee is None else str(q2(Decimal(row.freight_fee))),
        remark=row.remark or "",
        lines=row.lines or [],
        created_at=row.created_at,
    )


def _check_shipper(db: Session, shipper_id: int | None) -> None:
    """货主必须是一个**真实在用**的货主/批发商账号。

    ⚠️ `User` **没有** `is_deleted`：账号的"伪装删除"是
    `is_active=False` + `phone/username 加 _del{id} 后缀`（见 `api/v1/users.py::delete_user`）。
    所以这里判 `is_active` —— 它同时挡住"已删除"与"已停用"两种（对预设单来说都是
    "这个货主现在不能用"），而不是去 `getattr(u, "is_deleted", False)` 拿一个永远为假的判据。
    """
    if shipper_id is None:
        return
    u = db.get(User, int(shipper_id))
    if u is None:
        raise HTTPException(status_code=400, detail="选的货主不存在，请重新选")
    if not u.is_active:
        raise HTTPException(status_code=400, detail="选的货主账号已停用（或已删除），请重新选")
    if str(getattr(u.role, "value", u.role)) != UserRole.SHIPPER.value:
        raise HTTPException(status_code=400, detail="预设单的货主只能是货主/批发商账号")


@router.get("", response_model=list[OrderTemplateOut])
def list_templates(
    # ⚠️ 参数名必须是 `current`：下面 `with_popularity(..., current)` 要用它
    # （这个坑在 `arrears.py` 踩过一次：写成 `_` 时**编译期看不出来**，打到端点才 500）。
    current: User = Depends(require_permission(Permission.ORDER_EDIT)),
    #: 回收站视图（用户定的硬规矩：删除一律软删 + **界面上要有一个手边的恢复入口**）。
    #: 不加这个参数的话，软删的预设单只能靠删完那一下的 snackbar「撤回」——
    #: 手一滑点掉、或者过一会儿才想起来，就再也找不回来了。
    deleted_only: bool = False,
    db: Session = Depends(get_db),
) -> list[OrderTemplateOut]:
    """这一页的预设单：**常用的在前，其次先建的在前**（2026-09-22 统一列表规则）。

    `deleted_only=true` 时给的是**回收站**里那几张（按删的时间倒序，不算常用度 ——
    回收站要的是"我刚删的那张在最上面"）。
    """
    if deleted_only:
        rows = list(
            db.scalars(
                select(OrderTemplate)
                .where(OrderTemplate.is_deleted.is_(True))
                .order_by(OrderTemplate.deleted_at.desc(), OrderTemplate.id.desc())
            )
        )
    else:
        rows = list(
            db.scalars(
                usage_service.with_popularity(
                    select(OrderTemplate).where(OrderTemplate.is_deleted.is_(False)),
                    OrderTemplate,
                    usage_service.KIND_ORDER_TEMPLATE,
                    current,
                )
            )
        )
    names = _shipper_names(db, rows)
    return [_out(r, names) for r in rows]


@router.post("", response_model=OrderTemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(
    body: OrderTemplateCreate,
    db: Session = Depends(get_db),
    operator: User = Depends(require_permission(Permission.ORDER_EDIT)),
) -> OrderTemplateOut:
    _check_shipper(db, body.shipper_id)
    category = (body.category or "").strip()[:32]
    # 名册里没有的分类名 → 补进名册（与商品那一侧同一条：不让派单员"先建分类再建预设单"）
    ensure_category(db, category)
    tpl = OrderTemplate(
        name=body.name.strip(),
        shipper_id=body.shipper_id,
        category=category,
        origin_address=body.origin_address.strip(),
        address=body.address.strip(),
        receiver_name=body.receiver_name.strip(),
        receiver_phone=(body.receiver_phone or "").strip(),
        freight_fee=_money(body.freight_fee, "预设运费"),
        remark=body.remark.strip(),
        lines=_clean_lines(body.lines),
    )
    db.add(tpl)
    db.flush()
    write_log(
        db,
        operator_id=operator.id,
        order_id=None,
        action=OperationAction.ORDER_TEMPLATE_UPSERT,
        change_payload={
            "template_id": tpl.id,
            "name": tpl.name,
            "category": tpl.category or "",
            "scope": "create",
            "lines": len(tpl.lines or []),
        },
    )
    db.commit()
    db.refresh(tpl)
    return _out(tpl, _shipper_names(db, [tpl]))


@router.patch("/{template_id}", response_model=OrderTemplateOut)
def update_template(
    template_id: int,
    body: OrderTemplateUpdate,
    db: Session = Depends(get_db),
    operator: User = Depends(require_permission(Permission.ORDER_EDIT)),
) -> OrderTemplateOut:
    tpl = db.get(OrderTemplate, template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="预设单不存在")
    # ⚠️ 已经在回收站里的预设单**改不了**：列表上看不见它，改它只会得到一句"已完成"，
    #    而用户以为改的是"现在在用的那一张"（与挂账单位同一条规矩）。
    ensure_alive(tpl, "预设单", "POST /order-templates/{id}/restore")

    before = {
        "name": tpl.name,
        "shipper_id": tpl.shipper_id,
        "category": tpl.category or "",
        "address": tpl.address,
        "freight_fee": None if tpl.freight_fee is None else str(q2(Decimal(tpl.freight_fee))),
        "lines": len(tpl.lines or []),
    }
    sent = body.model_fields_set

    if body.name is not None:
        tpl.name = body.name.strip()
    # ⚠️ 分类走 `model_fields_set`：**空串是一个真实操作**（"移到未分类"），
    #    用 `is not None` 判的话它会被当成"没传"，而界面上看不出来
    #    （与 `freight_fee`、`shipper_id` 同一条理由）。
    if "category" in sent:
        new_cat = (body.category or "").strip()[:32]
        ensure_category(db, new_cat)
        tpl.category = new_cat
    # `shipper_id` 走 model_fields_set：**键出现就按给的值写**（null = 清空 → 下单时再选）。
    # `clear_shipper` 是给客户端的显式开关（Android 的 `explicitNulls=false` 会把 null 丢掉，
    # 没有它"清空货主"永远发不出去）。
    if body.clear_shipper:
        tpl.shipper_id = None
    elif "shipper_id" in sent:
        _check_shipper(db, body.shipper_id)
        tpl.shipper_id = body.shipper_id
    if body.origin_address is not None:
        tpl.origin_address = body.origin_address.strip()
    if body.address is not None:
        tpl.address = body.address.strip()
    if body.receiver_name is not None:
        tpl.receiver_name = body.receiver_name.strip()
    if body.receiver_phone is not None:
        tpl.receiver_phone = (body.receiver_phone or "").strip()
    # ⚠️ 运费这里**不用 `is not None` 判**：`_money("")` 与 `_money(None)` 都是"不预设"，
    #    而"把预设运费改回不预设"是一个真实操作（见文件头），所以同样走 model_fields_set。
    if "freight_fee" in sent:
        tpl.freight_fee = _money(body.freight_fee, "预设运费")
    if body.remark is not None:
        tpl.remark = body.remark.strip()
    if body.lines is not None:
        tpl.lines = _clean_lines(body.lines)

    write_log(
        db,
        operator_id=operator.id,
        order_id=None,
        action=OperationAction.ORDER_TEMPLATE_UPSERT,
        change_payload={
            "template_id": tpl.id,
            "scope": "update",
            "before": before,
            "after": {
                "name": tpl.name,
                "shipper_id": tpl.shipper_id,
                "category": tpl.category or "",
                "address": tpl.address,
                "freight_fee": None if tpl.freight_fee is None else str(q2(Decimal(tpl.freight_fee))),
                "lines": len(tpl.lines or []),
            },
        },
    )
    db.commit()
    db.refresh(tpl)
    return _out(tpl, _shipper_names(db, [tpl]))


@router.post("/{template_id}/use", response_model=OrderTemplateOut)
def use_template(
    template_id: int,
    db: Session = Depends(get_db),
    operator: User = Depends(require_permission(Permission.ORDER_EDIT)),
) -> OrderTemplateOut:
    """记一次"用这张预设单下了单"（**常用度计数的唯一写入点**）。

    ⚠️ 它**不改预设单本身**（所以没有 `ORDER_TEMPLATE_UPSERT` 审计）：
    计数是"排序用的统计"，不是业务事实（与 `usage` 那个模块同一个口径）。
    ⛔ 也**不在这里生成订单**：下单是 `POST /orders` 的事，两边分开才对得上账。
    """
    tpl = db.get(OrderTemplate, template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="预设单不存在")
    ensure_alive(tpl, "预设单", "POST /order-templates/{id}/restore")
    usage_service.record_usage(
        db, user=operator, kind=usage_service.KIND_ORDER_TEMPLATE, target_id=tpl.id
    )
    db.commit()
    db.refresh(tpl)
    return _out(tpl, _shipper_names(db, [tpl]))


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    operator: User = Depends(require_permission(Permission.ORDER_EDIT)),
) -> None:
    """伪装删除（用户定的硬规矩：一律软删 + 手边有恢复入口）。

    ⚠️ **不需要"还有谁在用"的拦截**：预设单与订单之间**没有引用**
    （真订单是按下单那一刻的参数生成的，生成完就与预设单无关了）。
    这一点与挂账单位不同 —— 那边删之前必须数引用，这里数不出来也不该数。
    """
    tpl = db.get(OrderTemplate, template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="预设单不存在")
    if tpl.is_deleted:
        raise HTTPException(status_code=400, detail="这张预设单已经在回收站里了")
    original_name = tpl.name
    tpl.is_deleted = True
    tpl.deleted_at = utc_now_naive()
    # 名字加后缀：名字列虽然不是唯一的，但这一套是**全项目软删的同一形状**
    # （也是"这行进过回收站"看得见的痕迹），恢复时按同样的规则去掉。
    tpl.name = del_suffix(tpl.name, tpl.id, 64)
    write_log(
        db,
        operator_id=operator.id,
        order_id=None,
        action=OperationAction.ORDER_TEMPLATE_DELETE,
        change_payload={"template_id": tpl.id, "name": original_name, "note": "伪装删除，可 restore 恢复"},
    )
    db.commit()


@router.post("/{template_id}/restore", response_model=OrderTemplateOut)
def restore_template(
    template_id: int,
    db: Session = Depends(get_db),
    operator: User = Depends(require_permission(Permission.ORDER_EDIT)),
) -> OrderTemplateOut:
    """把删掉的预设单放回来（`DELETE /{id}` 的逆操作）。"""
    tpl = db.get(OrderTemplate, template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="预设单不存在")
    if not tpl.is_deleted:
        raise HTTPException(status_code=400, detail="这张预设单没有被删除，不需要恢复")
    suffix = f"_del{tpl.id}"
    if tpl.name.endswith(suffix):
        tpl.name = tpl.name[: -len(suffix)]
    tpl.is_deleted = False
    tpl.deleted_at = None
    write_log(
        db,
        operator_id=operator.id,
        order_id=None,
        action=OperationAction.ORDER_TEMPLATE_RESTORE,
        change_payload={"template_id": tpl.id, "name": tpl.name},
    )
    db.commit()
    db.refresh(tpl)
    return _out(tpl, _shipper_names(db, [tpl]))
