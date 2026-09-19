"""司机账单唯一性：**数据库级**闸门（同一单同一类型只能有一张）。

### 为什么要有这份测试
`POST /orders/{id}/complete` 生成司机账单是"读-判断-写"。两个并发请求各自读到
"还没有账单"，于是同一张单两条 60 元账单（本机实测复现，见
`test_concurrent_delivery_money.py`）。v3.40 用条件 UPDATE 占位挡住了那个入口，
但**代码里的闸门只守它自己那条路**——补单接口、脚本、以后新写的批处理都能再插一次。

所以这里钉的是数据库本身：`uq_driver_bills_order_type`。
判据全是**效果**（插入会不会被拒 / 索引在不在），不看注释、不看声明。

⚠️ 同时钉住反面：月薪单不绑单（`order_id` 为 NULL），**不能**被这条索引误拦——
标准 SQL 里 NULL 不参与唯一性比较，多行 `(NULL,'salary')` 必须还能共存。
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.core.schema_bootstrap import bootstrap_schema
from app.models import DriverBill


def _bill(order_id: int | None, bill_type: str = "piece", amount: str = "60") -> DriverBill:
    return DriverBill(
        driver_id=999,
        bill_type=bill_type,  # type: ignore[arg-type]
        order_id=order_id,
        month="2026-09",
        amount=Decimal(amount),
        status="open",  # type: ignore[arg-type]
        note="唯一性测试",
    )


def test_unique_index_exists_on_this_database(db_session) -> None:
    """自检：这条约束真的落在当前库上（否则下面两条测试会在空转）。"""
    rows = db_session.execute(
        text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='driver_bills'")
    ).fetchall()
    names = {r[0] for r in rows}
    assert "uq_driver_bills_order_type" in names, f"唯一索引不在（现有索引：{sorted(names)}）"


def test_second_piece_bill_for_same_order_is_rejected(db_session) -> None:
    """同一张单的第二张 PIECE 账单会被**数据库**拒绝（钱不能付两次）。"""
    db_session.add(_bill(987654))
    db_session.commit()

    db_session.add(_bill(987654))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    left = db_session.query(DriverBill).filter_by(order_id=987654).count()
    assert left == 1, f"回滚后应只剩 1 张，实际 {left} 张"


def test_salary_bills_without_order_are_not_blocked(db_session) -> None:
    """月薪单不绑单：多行 (NULL,'salary') 必须还能共存（NULL 不参与唯一比较）。"""
    for _ in range(2):
        db_session.add(_bill(None, "salary", "6000"))
    db_session.commit()
    n = db_session.query(DriverBill).filter_by(order_id=None, bill_type="salary").count()
    assert n >= 2, "唯一索引把月薪单也拦住了——NULL 语义理解错了"


def test_bootstrap_skips_index_when_duplicates_already_exist(tmp_path) -> None:
    """旧库已有重复行时：**不建索引、也不许崩**（启动失败比脏数据严重得多）。

    这是"迁移脚本"这类代码最容易出事的地方：DDL 抛异常 → 服务起不来循环重启。
    所以这里用一个独立的临时库，先手写两张重复账单，再跑一遍 bootstrap。
    """
    eng = create_engine(f"sqlite:///{tmp_path / 'dup.db'}")
    with eng.begin() as c:
        c.execute(
            text(
                "CREATE TABLE driver_bills ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT, driver_id INTEGER, bill_type VARCHAR(8),"
                " order_id INTEGER, month VARCHAR(7), amount NUMERIC(12,2), status VARCHAR(12),"
                " created_at DATETIME, updated_at DATETIME)"
            )
        )
        for _ in range(2):
            c.execute(
                text(
                    "INSERT INTO driver_bills (driver_id, bill_type, order_id, month, amount, status)"
                    " VALUES (999, 'piece', 555, '2026-09', 60, 'open')"
                )
            )

    bootstrap_schema(eng)  # 不许抛

    with eng.connect() as c:
        names = {
            r[0]
            for r in c.execute(
                text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='driver_bills'")
            )
        }
        n = c.execute(text("SELECT COUNT(*) FROM driver_bills WHERE order_id = 555")).scalar()
    assert "uq_driver_bills_order_type" not in names, "有重复行时不该建唯一索引（会把启动搞崩）"
    assert n == 2, "重复行不该被 bootstrap 动过（它只读不写业务数据）"

    # 反向对照（**必须有**，否则上面那条只能证明"索引没建"，证明不了"是因为重复才没建"）：
    # 同样的临时表、同样的路径，只是没有重复行 → 索引必须被建出来。
    eng2 = create_engine(f"sqlite:///{tmp_path / 'clean.db'}")
    with eng2.begin() as c:
        c.execute(
            text(
                "CREATE TABLE driver_bills ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT, driver_id INTEGER, bill_type VARCHAR(8),"
                " order_id INTEGER, month VARCHAR(7), amount NUMERIC(12,2), status VARCHAR(12),"
                " created_at DATETIME, updated_at DATETIME)"
            )
        )
        c.execute(
            text(
                "INSERT INTO driver_bills (driver_id, bill_type, order_id, month, amount, status)"
                " VALUES (999, 'piece', 556, '2026-09', 60, 'open')"
            )
        )
    bootstrap_schema(eng2)
    with eng2.connect() as c:
        names2 = {
            r[0]
            for r in c.execute(
                text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='driver_bills'")
            )
        }
    assert "uq_driver_bills_order_type" in names2, "没有重复行时索引没建出来——迁移根本没跑到"
