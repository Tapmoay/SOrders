"""文件版 SQLite **不许**用 `StaticPool`（2026-09-19 审计，本机抖动/假红线的根因）。

## 为什么
`StaticPool` = 所有 Session 复用**同一条** SQLite 连接。对 `:memory:` 是必需的
（每条新连接都是另一个空库），但对**文件库**会让"请求"和"后台任务"共用一条连接：
A 请求的事务还没提交时，B（`background_tasks` 里那些各自开 `SessionLocal()` 的推送/账本同步）
的 `commit()`/`rollback()` 会把 A 的改动**一起提交或一起回滚**。

实测症状（两轮探针各撞到一次，查下来都不是代码缺陷）：
- 撤销订单返回 200，紧接着再派单也 200（中间那次 CANCELLED 被别的会话回滚了）；
- 建单后立刻查不到行 → 500「订单保存失败」。

两者单独重跑都正常、生产（MySQL，每 Session 独占连接）也不会这样 —— 但它会让本机所有
**并发结论都不可信**，而本仓库的并发闸恰恰是在本机验的。修完之后连跑两次全量探针，
可疑项稳定回到 1 条（只剩"超卖口径待拍板"）。
"""
from __future__ import annotations


def test_file_sqlite_engine_does_not_share_one_connection():
    from app.database import engine

    url = str(engine.url)
    pool_name = type(engine.pool).__name__
    if url.startswith("sqlite") and ":memory:" not in url:
        assert pool_name != "StaticPool", (
            f"文件版 SQLite（{url}）用了 StaticPool —— 请求与后台任务会共用一条连接、"
            "互相提交/回滚对方的改动（表现为随机的假失败与假通过）"
        )
    else:
        # 内存库必须用 StaticPool（否则每条连接都是另一个空库）
        assert pool_name == "StaticPool" or url.startswith("mysql"), (
            f"内存库应当用 StaticPool，实际 {pool_name}"
        )
