"""按「人」搜索的**唯一实现**：姓名 或 手机号，子串匹配。

用户 2026-09-19 原话：
「这些也要添加搜索键。然后这个搜索键可以根据他们的**名称**还有**电话号码**以及
**电话号码的后 4 位**进行搜索」。

为什么单独一个文件：这条规则在本项目里有 3 个消费点 —— 账号名册（`users`）、
客户档案（`customers`）、以及 App 侧账本仪表盘的本地筛选（`core/UserSearch.kt`）。
散着写就会出现「账号管理能按后 4 位搜到、货主管理搜不到」这种同一件事两个口径。

⚠️ **后 4 位不是额外一条规则**：手机号走的是子串匹配，`8001` 天然命中 `13800008001`。
所以这里刻意**不**写「取后四位再比」的分支 —— 多一条分支就多一个会跟主规则分叉的地方
（而分叉的表现是"搜得到/搜不到"，用户只会觉得系统坏了，不会觉得是两条规则）。

⚠️ 大小写：显式 `func.lower()` 把两边对齐，因为 MySQL 的 `like` 默认不分大小写、
而 SQLite（本地开发库）**区分** —— 不写的话同一个查询在开发库与生产库会返回不同的行
（软删账号的手机号带 `_del160` 后缀、姓名也可能有英文，这不是假想问题）。
两边都是 `%...%` 前缀通配，本来就走不到索引，所以 `lower()` 不额外付代价。
"""

from sqlalchemy import func, or_

from app.core.query_text import LIKE_ESCAPE, like_pattern


def name_or_phone_like(name_col, phone_col, kw: str | None):
    """「姓名 or 手机号 子串命中」的 SQL 谓词；`kw` 为空时返回 `None`（= 不加条件）。

    调用点必须自己判 `None`（不加条件），**不要**去构造一个恒真谓词 ——
    那样"搜索条件生效了没有"在 `filters_used` 之类的回报里就说不清了。

    ⚠️ pattern 必须过 `like_pattern()`（2026-09-24 第 19 轮）：直接 `f"%{term}%"` 的话，
    用户在搜索框打一个 `%` 就是"不加条件"—— 实测 `GET /users?q=%25` 返回**全部 59 个账号**。
    """
    like = like_pattern(kw)
    if like is None:
        return None
    term = like.lower()          # 手机号可能带英文后缀（软删的 `_del160`），大小写对齐见模块注释
    return or_(
        func.lower(func.coalesce(name_col, "")).like(term, escape=LIKE_ESCAPE),
        func.lower(func.coalesce(phone_col, "")).like(term, escape=LIKE_ESCAPE),
    )
