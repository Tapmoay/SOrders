"""031_account_devices：建一张「账号 ↔ 设备绑定」表（FEAT-0018，2026-10-11 用户要求）。

### 为什么需要一张新表
用户要的是两条跨时间的判据：①「一个账号最多绑 3 台设备、换设备要等 6 个月」；
②「一台设备不能短时间内绑一堆账号（防批量刷号）」。两条都要按 **(账号, 设备) 这一对**随时间查 ——
现在有几台有效绑定、最早那台是什么时候绑的、这台设备 24 小时内绑过几个号。
`users` 表上一列都存不下（一个账号多台、一台设备多号，是**多对多**关系）。
为什么这张表是这个形状（尤其是"解绑不删行"）见 `app/models/account_device.py`
开头那段（⛔ 别在这里抄第二份，两份必然有一天不一致）。

### 为什么走迁移而不是 schema_bootstrap
与 `019_purchase_orders` / `020_invoices` / `027_shipper_prices` /
`029_ai_operation_log` 同一条：建表是**正式变更**（老库要建表、新库由 `create_all` 按模型建）。
⛔ `core/schema_bootstrap.py` 里**没有**这张表，本次也不新开
（`_tools/qa/_check_silent_release.py` 第 5 条钉着这条纪律）。

### 为什么用模型建表
`AccountDevice.__table__.create` 让两种方言（本机 SQLite / 生产 MySQL）落到**同一个形状**上
（`user_id` / `device_id` 两个索引与 `(user_id, device_id)` 唯一约束都跟着模型走），
不会出现「迁移建的表少一条索引」这种只在生产才发作的偏差 —— 同 `024` / `027` / `029`
的 `table.create` 手法。
"""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

VERSION = 31
NAME = "account_devices"
DESCRIPTION = (
    "account_devices：账号 ↔ 设备绑定（一行一对，解绑不删行）。"
    "一个账号最多 3 台有效绑定、换设备要等最旧那台满 6 个月；"
    "一台设备最多绑 5 个账号、24 小时内最多新增 2 个（FEAT-0018）"
)

TABLE = "account_devices"


def upgrade(engine: Engine) -> None:
    """建这张表；已经在了就什么都不做（⛔ 必须能重跑）。"""
    if TABLE in set(inspect(engine).get_table_names()):
        return
    from app.models.account_device import AccountDevice

    AccountDevice.__table__.create(bind=engine, checkfirst=True)
