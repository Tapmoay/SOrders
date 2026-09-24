"""收款与现金（付款 / 收款；含付款家族私有助手）（orders_payment）—— 2026-09-24 整改阶段 4 **纯搬迁**的产物。

从 `api/v1/orders.py` 原样搬来的 7 个函数（_already_collected,_apply_complete_payment,_apply_complete_payment_logged,_payment_scoped_order,_reject_if_already_collected,pay_order,charge_order）。
除代码组织外**一个字没改** —— URL / 入参 / 出参 / 权限 / 状态机 / 数据库全不变；
证据：`_tools/qa/_api_contract_snapshot.py --diff <搬之前> <搬之后>` 契约零差异。

⚠️ 本模块**自己声明** `router`：按文件解析的 AST 工具（端点索引 / AI 能力表）靠这一行算 URL 前缀。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from app.api.v1.arrears import find_or_create_unit
from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import ArrearsUnit, Order, User
from app.models.enums import OperationAction, OrderStatus
from app.schemas.order import OrderChargeBody, OrderOut
from app.services.operation_log_service import write_log
from app.services.order_flow import complete_delivery, lock_order_row
from app.services.order_money import money_map
from app.services.order_response import enrich_order_out, load_order_for_response


router = APIRouter(prefix="/orders", tags=["orders"])


def _already_collected(db: Session, order: Order) -> bool:
    """这张单**已经收过款**了吗？（判据与 [_reject_if_already_collected] 同一套）

    两条：`order.paid` 是标记，而**指向这张单的 inbound 流水**是"钱真的进来过"的物证
    （标记可能被别的路径改过，物证不会）。
    """
    if order.paid:
        return True
    from app.models import CashFlow

    return (
        db.scalars(
            select(CashFlow).where(
                CashFlow.order_id == order.id,
                func.lower(CashFlow.direction) == "in",
                # 已撤销的流水不算"钱真的进来过"（2026-09-22 起 `cash_flows` 有软删）
                CashFlow.is_deleted.is_(False),
            )
        ).first()
        is not None
    )


def _apply_complete_payment(db, order, payment: str | None) -> str | None:
    """司机完成订单时的收款处理：
    - 派单勾选「收取现金」：司机明确选 cash=现场收现金 / arrears=挂账（未选择按挂账兜底）；
    - 未勾选「收取现金」：账单自动挂账（界面上不出现收款按钮）。

    ⚠️ **明确要现金、但派单没勾选**时必须报错，不许悄悄改成挂账（2026-09-19 真机 E2E 抓到）：
    实测里司机侧传 `payment=cash`、而这一单派单时没勾「收取现金」，结果订单落成
    `payment_method=arrears / paid=False`、接口 200 —— 两边对同一件事的理解**相反**：
    司机以为自己收了现金，系统记的是"还没收"，于是这块账会出现在催收名单里。
    App 侧不会这么发（按钮只在勾选后才出现），但"接口照收却按另一个意思记"正是
    这个项目反复在治的那一类（后端没有的语义要如实拒绝，不许悄悄换掉）。

    ⛔ **已经收过款的单，送达不许把 `paid` 改回 False**（2026-09-19 审计 F1，高）：
    下面原来是无条件赋值，于是这条链一路静默 ——
    ① 先收了一笔钱（预收 / 派单员代收：`POST /ledger/receipts` → `paid=True` + 收款单 + 现金流水）；
    ② 单子照常派送、送达时 `collect_cash` 是默认的 False → 落到 `else` 分支 →
       **`paid` 被抹回 False**，而收款单与流水都还在，审计日志里也**没有任何翻 `paid` 的痕迹**；
    ③ 派单员打开「客户收款」，这张单又出现在"已送达未收"列表里 → 再核销一次 →
       **第二张收款单 + 第二条现金流水**：资金流入 = 2×，营业额 = 1×，客户被重复催收。

    所以现在的口径：**钱只认一次**。
      · 已经收过款 + 司机说收了现金 → 直接拒绝（再收一次就是重复收款）；
      · 已经收过款 + 没说要现金 → **保留**原来的收款方式与 `paid=True`（送达只记送达）。
    返回一句"要不要留痕"的说明（改了收款状态时非 None，调用方写进审计日志）。
    """
    if payment == "cash" and not order.collect_cash:
        raise ValueError(
            "这一单在派单时没有勾选「收取现金」，不能按现金收款。"
            "请让派单员先勾选（或改派），再按现金提交；否则只能按挂账提交。"
        )
    if _already_collected(db, order):
        if payment == "cash":
            raise ValueError(
                "这一单已经收过款了，司机再收一次现金就是重复收款。"
                "请让派单员核对「客户收款」里这张单的记录；确认钱确实没收到的，"
                "先处理掉那笔收款再送达。"
            )
        # 保留原来的收款方式（不许因为"派单没勾现金"就把一笔已收的钱改回未收）
        return f"送达时发现这一单已有收款记录，保留原收款方式（{order.payment_method or '—'} / paid=True）"
    before = (order.paid, order.payment_method)
    if order.collect_cash:
        if payment == "cash":
            order.payment_method = "cash"
            order.paid = True
        else:
            order.payment_method = "arrears"
            order.paid = False
    else:
        order.payment_method = "arrears"
        order.paid = False
    # ⛔ **收到钱的单必须把"挂账单位"那根指向清掉**（2026-09-23 第 7 轮实测）：
    #    同一个字段（`orders.paid` / `payment_method`）有三个写入点，而只有 `pay_order`
    #    （现场收款确认）会顺手清 `arrears_unit_id`；送达这条路一直没清。于是这条顺序
    #    ——「派单员先点挂账 → 司机按**收取现金**送达」——会落成一个自相矛盾的单：
    #    `paid=True / payment_method=cash` 却仍然指着「某某挂账单位」，界面上那张单
    #    还写着挂账单位，而挂账单位页/导出按 `paid=False` 过滤，两处说法不一致。
    #    更要紧的是 **`delete_unit` 会因此永远删不掉那个单位**：
    #    它数的是"所有 `arrears_unit_id` 指向它的订单"（不看 paid），于是那句
    #    「该单位名下已有 N 笔挂账订单，无法删除」说的是一笔**早就收了现金**的单 ——
    #    而界面上没有"改挂账单位"的入口，用户按这句话去处理也解不开（死结）。
    #    与 `pay_order` 同源：钱一收到，挂账指向就该消失。
    if order.paid and order.arrears_unit_id is not None:
        cleared = order.arrears_unit_name or ""
        order.arrears_unit_id = None
        order.arrears_unit_name = ""
    else:
        cleared = ""
    if (order.paid, order.payment_method) == before and not cleared:
        return None
    return (
        f"送达收款处理：paid {before[0]} → {order.paid}，方式 {before[1] or '—'} → {order.payment_method or '—'}"
        + (f"；同时清掉挂账单位「{cleared}」（这一单是现场收现金，不再挂着它）" if cleared else "")
    )


def _apply_complete_payment_logged(db, order, payment: str | None, operator_id: int) -> None:
    """送达时的收款处理 + **留痕**（两个送达端点共用这一处，别各写一遍）。

    ⚠️ 为什么要有这个封装（2026-09-19 全项目 bug 报告 P1-10，实测 500）：
    两个送达端点原先各写了一遍收款调用，其中 `/{order_id}/complete-with-upload`（拍照送达，
    司机端的主力路径）**漏传了第一个位置参数** → `TypeError`（不是 `ValueError`，下面的
    `except ValueError` 接不住）→ **恒 500**，而 `complete_delivery` 已经跑完（改状态、扣库存、
    入账、生成司机账单），只有最后的 `db.commit()` 没执行 → 整笔回滚，**照片却已落盘**。
    另一条路径（`/{order_id}/complete`）虽然调对了，但它的留痕块写在端点里，
    所以拍照送达这一侧连"钱的收款状态变过"这件事都不会进审计。

    收口成一个函数之后，两条路径**在同一个地方**保证「调用参数 + 留痕」两件事都做到：
    留痕是 F1（2026-09-19 审计，高）的要求——送达只写 `ORDER_COMPLETE{photos:N}` 时，
    `paid` 被翻动在审计页上完全看不见，而"钱的状态变过"正是最需要能回查的那一类事实。
    """
    note = _apply_complete_payment(db, order, payment)
    if note:
        write_log(
            db,
            operator_id=operator_id,
            order_id=order.id,
            action=OperationAction.ORDER_COMPLETE,
            change_payload={"payment_change": note},
        )


def _payment_scoped_order(order_id: int, db: Session) -> Order:
    order = db.scalars(
        select(Order).options(selectinload(Order.order_products)).where(Order.id == order_id)
    ).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    # 已撤销 / 已退货的单都不能再收款或挂账（2026-09-20 合并成一条）：
    # 撤销 = 这单没发生过；退货 = 货款已经红冲掉了 —— 两种情况下再记一次收款/挂账，
    # 都是把一笔不存在的应收重新变成"收过钱"或"欠着钱"。
    if order.status in (OrderStatus.CANCELLED, OrderStatus.RETURNED):
        raise HTTPException(status_code=400, detail="已撤销/已退货订单不可收款、挂账")
    return order


def _reject_if_already_collected(db: Session, order: Order, what: str) -> None:
    """这张单**已经收过款**了 → 不许再把它改回「未收」（2026-09-19 审计 R14-2）。

    ### 缺口长什么样（真机可复现的三步，派单员一个人就能做完）
    1. 送货 → `POST /ledger/receipts`（逐单核销）→ 订单 `paid=True` + 一张收款单 + 一条现金流水；
    2. App 上这张已送达单的「挂账」按钮**一直是可点的**（`OrderDetailScreen` 只判 `!acting`）→
       `POST /orders/{id}/charge` → 本函数原来的写法是**无条件** `paid=False, payment_method=arrears`；
    3. 再核销一次 → 收款侧唯一的防重判据就是 `paid`（`accounting_service` 的 `if o.paid` 与
       条件 UPDATE 的 `Order.paid.is_(False)` 都只看它）→ **第二张收款单 + 第二条现金流水**。

    后果是"钱多记一笔"：资金收支流入 = 2×订单金额，而营业额 = 1×（按 `paid` 二选一），
    两个口径永久分叉；客户还会重新出现在「挂账未收」名单里被再催一次。

    ### 判据为什么是两条
    - `order.paid`：正常核销/现场收款的标记；
    - **指向这张单的收款流水**：`paid` 可能被别的路径改过（本轮修的就是"能改回去"这件事），
      而 `cash_flows(order_id=…, direction=in)` 是"钱真的进来过"的物证——它比标记可信。
    """
    # ⛔ 判据**只算一处**（2026-09-21 精简轮收口）：上面 `_already_collected`。
    #    这段原来在这里内联抄了一遍，而 `_already_collected` 的 docstring 一直写着
    #    "判据与 [_reject_if_already_collected] 同一套" —— 注释在承诺一件代码没保证的事：
    #    谁哪天改了 `paid` 与 inbound 流水的取舍，另一边不会跟着动，而**两边都不报错**。
    if not _already_collected(db, order):
        return
    raise HTTPException(
        status_code=400,
        detail=(
            f"这张单已经收过款了，不能{what}。"
            # ⛔ 这句原来写的是"请先在账本里把那笔收款处理掉"——而**系统里根本做不到**
            #    （2026-09-19 审计 F5：`ledger.py` 只有 `POST/GET /ledger/receipts`，
            #    没有 DELETE/PATCH，也没有反向分录）。让用户去做一件做不到的事，
            #    比直接说"做不到"更糟：他会反复找、以为是自己没找到入口。
            "系统目前**没有撤销收款的入口**，所以这一笔只能这样处理："
            "先确认钱是不是真的收到了——如果这笔收款记错了，请联系管理员在账上冲正；"
            "如果钱确实收到了，那这张单不用再收，保持现状即可。"
        ),
    )


@router.post("/{order_id}/pay", response_model=OrderOut)
def pay_order(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_EDIT)),
) -> OrderOut:
    """派单员：现场收款确认（货到付款）。仅派单员界面可用。

    ⛔ **已经收过款的单不许再点"现场收款确认"**（2026-09-24 第 20 轮并行渗透 C1-2 + D5-②）：
    这条路径原来只写 `payment_method='cash' / paid=True / arrears_unit_id=None` ——
    **不写收款单、不写现金流水**。于是"已经核销过一部分"的单（`paid=True`、
    `payment_method` 仍是 `arrears`、`money_map` 按核销流水算出已收 100、还欠 700）上再点一次：

    | 谁 | 看到的 |
    | --- | --- |
    | 界面/AI 卡片 | 「收款：¥800」→ 点确认 → 「已完成」 |
    | 库里 | `paid=True`、**一笔新进账都没有**；`arrears_unit_id` 被清空 → 这单从挂账单位账上**消失** |
    | 挂账名单 | 它已被 `paid=True` 排除 → 那 700 元**没人再追** |

    也就是说"收款方式说现金、欠款说 700"——同一张单两个答案。判据与"改回挂账"那条**同一处**
    （[_reject_if_already_collected]，只看 `paid` + 指向这张单的 inbound 流水）。
    """
    # ⛔ 先**锁住这一行再读**（2026-09-24 第 24 轮并行渗透 01-D1）：
    #    `pay`（写 `paid=True`）与 `charge`（写 `paid=False`）原来都是"普通 SELECT → 判断 →
    #    无条件赋值"，**一处锁都没取**。两个请求交错时：charge 读到 `paid=False` 的旧快照，
    #    再把 `paid` 写回 False —— 于是 `pay` 的那次收款在所有口径里归零
    #    （`pay_order` 按设计**不写收款单、不写流水**，它只改标记），
    #    两道防重门（`o.paid` 与 `m.arrears<=0`）双双放行 → **同一笔钱可以再收一次**：
    #    第二张收款单 + 第二条现金流水，资金流入 2×。
    #    本机只读 SQL 已证"钱收过、账上一笔流水都没有"是既成事实（`orders.id=449`）。
    #    取锁之后 `_reject_if_already_collected` 读到的就是提交后的新值，判据才真的生效。
    order = lock_order_row(db, _payment_scoped_order(order_id, db))
    _reject_if_already_collected(db, order, "再确认一次现场收款")
    order.payment_method = "cash"
    order.paid = True
    order.arrears_unit_id = None
    order.arrears_unit_name = ""
    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action="ORDER_PAY",
        change_payload="现场收款确认",
    )
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    return enrich_order_out(full, db, current)


@router.post("/{order_id}/charge", response_model=OrderOut)
def charge_order(
    order_id: int,
    body: OrderChargeBody,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_EDIT)),
) -> OrderOut:
    """派单员：订单挂账到挂账单位名下。仅派单员界面可用。"""
    # ⛔ 与 `pay_order` 同一处竞争、同一种修法（2026-09-24 第 24 轮并行渗透 01-D1）：
    #    这条路径把 `paid` 写回 False，等于**给这张单重新开一次收款窗口** ——
    #    所以"先锁再判"必须两边都做：只锁一边的话，被写坏的那一边照样发生。
    order = lock_order_row(db, _payment_scoped_order(order_id, db))
    # ⚠️ 已收款的单**不许改回挂账**（2026-09-19 审计 R14-2）：收款侧唯一的防重判据就是 `paid`，
    #    把 paid 改回 False 等于给这张单**重新开了一次收款窗口**（收款单与现金流水都还在）。
    _reject_if_already_collected(db, order, "改回挂账")
    # ⚠️ 2026-09-22「挂账时**自动添加**挂账单位」（用户原话：「假如有个订单，他没有结账，
    #    **直接点击挂账**，这个**挂账单位是自动添加的**」）：
    #    给了名字、名册里没有 → 就地建一个（`find_or_create_unit`，**与"新增挂账单位"
    #    同一份实现**：同一条审计、同一套软删/恢复语义）。给了 id 仍以 id 为准。
    if body.arrears_unit_id is not None:
        unit = db.get(ArrearsUnit, body.arrears_unit_id)
        if unit is None:
            raise HTTPException(status_code=404, detail="挂账单位不存在")
    else:
        unit = find_or_create_unit(db, body.arrears_unit_name, current)
    order.payment_method = "arrears"
    order.paid = False
    order.arrears_unit_id = unit.id
    order.arrears_unit_name = unit.name
    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action="ORDER_CHARGE",
        change_payload="挂账到 " + unit.name,
    )
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    return enrich_order_out(full, db, current)
