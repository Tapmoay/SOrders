"""挂账时**自动添加挂账单位**（2026-09-22 用户要求）。

用户原话：「我们这个挂账有个联动：假如有个订单，他没有结账，**直接点击挂账**，
这个**挂账单位是自动添加的**」—— 之前三处都没有这个联动（后端只收已存在的 id、
App 只能从名册里选、AI 侧名字对不上就反问），所以这一轮把它做出来。

三条口径各一个用例（都是"不报错但会出事"的那种）：
1. **名字不存在 → 就地建一个**并挂上（这就是"自动添加"本身）；
2. **名字已存在 → 复用那一行**（不新建第二行：挂账是按 `arrears_unit_name` 快照分组的，
   建出两个同名单位等于把同一个人拆成两笔账）；
3. **名字躺回收站里 → 放回来**（`arrears_units.name` 上有唯一索引，而删除是软删 ——
   直接 INSERT 会撞唯一索引报 500，表现是"这个名字从此用不了"）。
"""
from sqlalchemy import select

from app.api.v1.arrears import find_or_create_unit
from app.models import ArrearsUnit


def _by_name(db, name: str) -> ArrearsUnit:
    return db.scalars(select(ArrearsUnit).where(ArrearsUnit.name == name)).one()


def test_名字不存在就地建一个(db_session, users):
    """① 自动添加：名字不在名册里也要能挂上（这就是用户要的那个联动）。"""
    before = db_session.scalars(select(ArrearsUnit)).all()
    unit = find_or_create_unit(db_session, "  新单位甲  ", users["dispatcher"])
    db_session.commit()

    # 前后空格要 strip（否则「新单位甲」和「新单位甲 」会变成两笔账）
    assert unit.name == "新单位甲"
    assert unit.id is not None
    assert len(db_session.scalars(select(ArrearsUnit)).all()) == len(before) + 1


def test_名字已存在复用那一行(db_session, users):
    """② 同名再来一次：**复用**，不许建出第二行。"""
    db_session.add(ArrearsUnit(name="老单位乙"))
    db_session.commit()
    first = _by_name(db_session, "老单位乙")

    again = find_or_create_unit(db_session, "老单位乙", users["dispatcher"])
    db_session.commit()

    assert again.id == first.id
    assert len(db_session.scalars(select(ArrearsUnit).where(ArrearsUnit.name == "老单位乙")).all()) == 1


def test_躺回收站里的同名放回来(db_session, users):
    """③ 软删过的同名：**放回同一行**（不是插一行 —— 唯一索引会 500）。"""
    u = ArrearsUnit(name="被删过的丙", is_deleted=True)
    db_session.add(u)
    db_session.commit()
    uid = u.id

    back = find_or_create_unit(db_session, "被删过的丙", users["dispatcher"])
    db_session.commit()

    assert back.id == uid
    assert back.is_deleted is False
    assert len(db_session.scalars(select(ArrearsUnit).where(ArrearsUnit.name == "被删过的丙")).all()) == 1


def test_空白名字被拒(db_session, users):
    """⛔ 空白名字不许建出「无名单位」：那笔账以后谁也认不出来。"""
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        find_or_create_unit(db_session, "   ", users["dispatcher"])
