"""创建数据库表（开发用）。生产环境请使用 Alembic 迁移。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import engine
from app.models.base import Base

from app.models import (  # noqa: F401
    Ledger,
    LedgerExportJob,
    Notification,
    OperationLog,
    Order,
    OrderProduct,
    PriceRule,
    Product,
    ShipperAddress,
    ShipperContact,
    User,
)


def main() -> None:
    Base.metadata.create_all(bind=engine)
    print("Tables created.")


if __name__ == "__main__":
    main()
