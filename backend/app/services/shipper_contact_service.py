from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ShipperContact, User


def upsert_boss_contact(db: Session, shipper_id: int, phone: str, display_name: str = "") -> None:
    """把这一单的「下单人」记进货主的联系人（他下次下单能直接选到这个人）。

    ⛔ **别把他自己记成他自己的联系人**（2026-09-22 加）：
    「下单人」的口径是**这一单的货主** —— 代理下单时它本来就是这位货主
    （用户 2026-09-22：「派单员……不能填写自己的名称和电话号码，他要填的是**自动填选的是货主的**」），
    而货主自己下单时它也是他自己。两条路都会走到这里，记下来就是货主名册里多出一条
    **指向他自己**的联系人：界面上看不出是怎么来的，删了下次下单还会长出来
    （实测本机库里那个字段目前是 0 行，但这条口子一旦放开就会天天长）。
    """
    phone = phone.strip()
    if not phone:
        return
    own_phone = db.scalar(select(User.phone).where(User.id == shipper_id))
    if own_phone and own_phone.strip() == phone:
        return
    row = db.scalars(
        select(ShipperContact).where(
            ShipperContact.shipper_id == shipper_id,
            ShipperContact.phone == phone,
        )
    ).first()
    if row is None:
        db.add(
            ShipperContact(
                shipper_id=shipper_id,
                phone=phone,
                display_name=display_name or "",
            )
        )
    elif display_name and not row.display_name:
        row.display_name = display_name
