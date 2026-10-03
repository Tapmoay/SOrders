"""016_session_end_reason：`users` 加四列（会话结束原因 / 结束时间 / 版本凭据 / 最后登录）。

### 为什么加它们（2026-10-03 三端真机 E2E 走查 BUG-0006）

> 「被顶号 / 被停用 / 改了密码 / 令牌过期，在用户眼里**全是同一句话**，不说原因；
>  服务端明明握着 reason 字符串。」
> 「users 表**没有 last_login_at 字段**，事后在库里查不到「谁顶了谁」。」

四处调用 `revoke_tokens_and_sockets(db, user, background_tasks, reason)` 时**都**传了那句原因
（登出 / 被顶号 / 改密码 / 被停用），但它当时只用来排推送与写日志 —— **从没有落库**：
客户端既说不出原因，运维事后也查不到"谁顶了谁"。

### 为什么走迁移而不是 schema_bootstrap

`migrations/README.md` 的分工：**正式变更**走本目录、**运行时自愈**走
`core/schema_bootstrap.py`。本事项加的是**四列新列**（列定义本身），与
`012_contact_categories` / `013_route_categories` / `014_user_categories` /
`015_vehicle_categories` 同一条理由。`schema_bootstrap` 里那份是同一句 DDL 的自愈副本，
给"迁移没跑过就直接起服务"的库兜底（先例：`products.category` / `shipper_locations.category`）。

### 四条设计选择

1. **⛔ 不回填**。这四列回答的是"上一次登录 / 上一次退出发生了什么"，而**老库里没有任何一列
   能推出它** —— 编一个原因出来就是替用户记错账（与 009～015 同一条纪律：宁可空着）。
   默认值必须是"什么都没记"：空串 / NULL / 0。
2. **`session_revoked_reason` 是 `VARCHAR(64) NOT NULL DEFAULT ''`**：长度按列定，
   不靠调用方自觉（写入侧统一 `(reason or "").strip()[:64]`）。
3. **`session_revoked_version` 是"这句话还算不算数"的凭据**：读侧要求
   `session_revoked_version == token_version` 才肯把那句话说出来（否则说兜底句）——
   所以它与 `token_version` 同型同默认（`NOT NULL DEFAULT 0`：老库补列不会把任何人踢下线）。
4. **没有索引**：这四列的读法只有一种 —— 按主键取一行（`get_current_user` 手里已经有 `user`），
   没有任何按它们筛的查询；建索引只会拖慢写入。

### 可重跑

逐列判存在性、逐列执行（MySQL 的 DDL 隐式提交：一条迁移可能改了一半才失败，
下次重跑必须能接着往下走 —— README 硬要求）。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 16
NAME = "session_end_reason"
DESCRIPTION = (
    "users 加四列（会话结束原因 / 结束时间 / 版本凭据 / 最后登录）："
    "被顶号 / 被停用 / 改密码 / 过期分得清，事后查得到谁顶了谁。⛔ 不回填老数据"
)

TABLE = "users"

COLUMNS: dict[str, str] = {
    "session_revoked_reason": "session_revoked_reason VARCHAR(64) NOT NULL DEFAULT ''",
    "session_revoked_at": "session_revoked_at DATETIME",
    "session_revoked_version": "session_revoked_version {int_type} NOT NULL DEFAULT 0",
    "last_login_at": "last_login_at DATETIME",
}


def _int_type(engine: Engine) -> str:
    """sqlite 认 `INTEGER`、MySQL 认 `INT`（与 `core/schema_bootstrap.py` 那条同形）。"""
    return "INTEGER" if engine.dialect.name == "sqlite" else "INT"


def _columns(engine: Engine) -> set[str] | None:
    """`users` 现有的列名；None = 表还不存在（全新库由 `create_all` 按模型建全）。"""
    insp = inspect(engine)
    if TABLE not in insp.get_table_names():
        return None
    return {c["name"] for c in insp.get_columns(TABLE)}


def upgrade(engine: Engine) -> None:
    have = _columns(engine)
    if have is None:
        # 全新库：模型里已经有这四列，create_all 建出来的表就是全的。
        return
    for name, ddl in COLUMNS.items():
        if name in have:
            continue
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN " + ddl.format(int_type=_int_type(engine))))
