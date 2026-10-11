"""035_module_categories：模块自有分类名册（批发商管理 / 司机管理 / 货主管理各一份，2026-10-12 FEAT-0026）。

### 为什么有这张表（用户 2026-10-12 原话）

> 「我批发商管理他那个分类啊，他那个分类是**跟账号管理不一样**的，**他现在串在一起了**。
>  他那个分类是**可以新建的、另外建的**。只不过我们**账号管理拉取他们的分类的时候是搞 2 级分类**；
>  当然，我们这些**子分类是不会拉取主分类**的。也就如**司机管理**，还有其他的**批发商管理**，
>  **他们是有自己的分类的**，他们的分类基本上就是 **1 级**、不会有 2 级的。
>  然后我们的**账号管理**，他的那个分类他是**有 2 级的**，他是**主动拉取**的，
>  而且我们分类**已经固定好了**的。」

拆之前：司机管理 / 货主管理 / 批发商管理三个名册页与账户页**共用** `user_categories` 这一张表
（详见 `docs/changes/FEAT-0026.md` 第②节的耦合点清单）。于是"在批发商管理里加一个分类"与
"给账号名册加一个大类"是**同一个写端点**（`POST /user-categories`），两种意图混在一起、
在界面上说不清谁改了谁。拆之后：模块名册是这张表（`module_categories`，**平表、只有一级**），
账号名册是 `user_categories`（一级固定六类，二级由本表**拉取**）。

### 为什么走迁移而不是 schema_bootstrap

`migrations/README.md` 的分工：**正式变更**走本目录、**运行时自愈**走
`core/schema_bootstrap.py`。本事项不只是建一张新表（那种由 `create_all` 顺手就建了，
先例：`product_categories` / `place_categories`），它还带**存量数据的搬运** ——
"哪些行该搬"是历史事实，自愈那一段不该、也不能替用户做判断（它每次启动都跑）。

### 搬什么、为什么必须搬

`user_categories` 里现在可能已经有**挂在模块的一级下面**的二级行（CHG-0112 之后用户在
「批发商」下面建的"食堂客户"就是这么来的）。不搬的话：

1. 那些账号的 `users.category` 里写着"食堂客户"，而**新的模块名册是空的** ——
   批发商管理页的「管理分类」打开是空的，用户会以为分类丢了；
2. 账号册那边它仍是一行**真实的**二级（不是拉取的），而它的增 / 删 / 改在拆分之后
   被写路径挡住了（"请到对应模块的「管理分类」里改"）—— 同一格在两个地方都说得通，就又是"串在一起"。

⇒ 搬：把挂在 **批发商 / 货主 / 小车司机 / 大车司机 / 挂车司机** 下面的二级行，
按名字与顺序原样落到对应模块的那份名册里，然后**撤掉旧行**。
「搬」不是「删」：那一格的名字、顺序、归属（挂在哪个一级下面）一个字节都没变，
只是从 `user_categories` 换到了 `module_categories`，
而且到了新家之后照样能改名 / 排序 / 软删（软删那套在 `api/v1/module_categories.py`）。
⛔ 留着旧行是不行的：账号册 GET 会**同时**给出真实的旧行与拉取来的新行，同一格在左栏里出现两次。

`派单员` 下面的子分类**不动**：没有"派单员管理"这一页，它没有自己的名册（见 FEAT-0026 的
Known Limitations）。

### 幂等（README 硬要求「必须能重跑」）

- 表用 `checkfirst=True` 建（全新库由 `create_all` 先建好，这里等于没做）；
- 逐行判「这一份名册里是否已经有同名的活行」：有就**只撤旧行**、不插第二行；
- 撤旧行与插新行在**同一个事务**里（`engine.begin()`），要么都成要么都不成。

⚠️ 索引随表走（`module / name / sort_order` 三条，模型里 `index=True`）——
`Table.create()` 会把它们一起建出来；这一点与 014 / 030 那种"给已存在的表补一列 + 补索引"
不同，那两份要自己 `CREATE INDEX`。
"""

from __future__ import annotations

from sqlalchemy import func, inspect, select
from sqlalchemy.engine import Engine

from app.models import ModuleCategory, UserCategory

VERSION = 35
NAME = "module_categories"
DESCRIPTION = (
    "建 module_categories（模块自有、只有一级）+ 把账号册里挂在模块一级下面的二级行搬过来。⛔ 一格不丢"
)

TABLE = "module_categories"
SOURCE_TABLE = "user_categories"

#: 一级分类名 → 它归哪一份模块名册（`派单员` 没有模块 ⇒ 不搬；司机是一对三）。
MOVE: dict[str, str] = {
    "批发商": "members",
    "货主": "shippers",
    "小车司机": "drivers",
    "大车司机": "drivers",
    "挂车司机": "drivers",
}


def upgrade(engine: Engine) -> None:
    insp = inspect(engine)
    if SOURCE_TABLE not in insp.get_table_names():
        # 全新库：连账号名册都还没有，没有可搬的东西（表由 create_all 按模型建）。
        return
    # ① 表：全新库已经由 create_all 建好；老库/半路库在这里按模型建一次（幂等）。
    ModuleCategory.__table__.create(bind=engine, checkfirst=True)

    dst = ModuleCategory.__table__
    src = UserCategory.__table__
    # ② 搬：插新行 + 撤旧行在同一个事务里。
    with engine.begin() as conn:
        tops = conn.execute(
            select(src.c.id, src.c.name).where(src.c.parent_id.is_(None))
        ).fetchall()
        for top_id, top_name in tops:
            module = MOVE.get((top_name or "").strip())
            if module is None:
                continue
            kids = conn.execute(
                select(src.c.id, src.c.name, src.c.sort_order)
                .where(src.c.parent_id == top_id)
                .order_by(src.c.sort_order, src.c.id)
            ).fetchall()
            for kid_id, kid_name, kid_sort in kids:
                already = conn.execute(
                    select(func.count())
                    .select_from(dst)
                    .where(
                        dst.c.module == module,
                        dst.c.name == kid_name,
                        dst.c.is_deleted.is_(False),
                    )
                ).scalar() or 0
                if not already:
                    conn.execute(
                        dst.insert().values(
                            module=module,
                            name=kid_name,
                            sort_order=kid_sort or 0,
                            is_deleted=False,
                        )
                    )
                # ⛔ 无论如何都撤掉旧行：它的内容已经在模块名册里（或者本来就在），
                #    留着会让账号册里同一格出现两次。
                conn.execute(src.delete().where(src.c.id == kid_id))
