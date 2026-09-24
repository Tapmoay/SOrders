# 数据库迁移（`app/migrations/`）

> 整改报告 §4：**schema 迁移版本化是整个架构改造的第一核心任务**。
> 报告的原话是「不要直接一把梭哈 Alembic」，分三步：① 先给现有 bootstrap 加版本表；
> ② 把每次 schema 修改变成独立 migration；③ 最后再决定是否完整迁移 Alembic。
> 本轮（2026-09-24）做的是**第 ① 步**，并把第 ② 步的机制备好。

## 分工（这一页最重要的两行）

| 角色 | 谁负责 | 什么时候跑 |
|---|---|---|
| **正式变更**（一次性的结构/数据搬迁） | 本目录 `NNN_*.py` | 每个版本**只跑一次**，跑过记进 `schema_versions` |
| **运行时自愈**（缺表补表、缺列补列、枚举补值、列宽放宽） | [`core/schema_bootstrap.py`](../core/schema_bootstrap.py) | **每次启动**都跑（必须幂等） |

⛔ 本轮**没有**把 bootstrap 那 1600 行搬进 migrations —— 报告 §18 规则 1「一次只动一个维度」：
搬它等于同时在动"迁移机制"和"全部既有 DDL"，出错了分不清是哪一层。既有那些幂等 DDL 保持原样。

## 常用命令

```bash
cd backend
python -m app.migrations status      # 当前版本 / 已应用 / 待跑 / 内容变过的
python -m app.migrations upgrade     # 手动跑待跑的（正常由启动自动跑）
python -m app.migrations upgrade --dry-run
python -m app.migrations --json status       # 给脚本/CI 用
```

启动时自动跑的那一次在 `core/schema_bootstrap.py` 的**最后**（必须排在自愈之后：
迁移要看到"已经补好列/补好枚举"的结构）。

## 写一条新迁移

```python
"""002_add_order_xxx：给 orders 加 xxx（为什么要加，一句话）。"""
from sqlalchemy.engine import Engine
from sqlalchemy import text, inspect

VERSION = 2
NAME = "add_order_xxx"
DESCRIPTION = "orders 加 xxx 列（老库回填 0）"


def upgrade(engine: Engine) -> None:
    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("orders")}
    if "xxx" in cols:            # ⛔ 必须能重跑：MySQL 的 DDL 是隐式提交的，失败可能留半截
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE orders ADD COLUMN xxx INT NOT NULL DEFAULT 0"))
```

四条硬要求：

1. **文件名 = `NNN_短名.py`**（三位以上版本号）。不符合的会被 `discover()` 当场报错 ——
   一个"看起来像迁移、谁也不跑"的文件比没有迁移更危险；
2. **必须能重跑**（先判存在再做）。MySQL 的 DDL 隐式提交，一条迁移可能"改了一半"然后失败；
3. **跑了就不许再改**。改历史迁移会被 `checksum` 抓到（`status` 标红、CI 红），但**不会**重跑它；
   要改就新加一条；
4. **一次只做一件事**。别把"加列 + 回填 + 删旧列"塞进同一条 —— 失败时你不知道停在哪。

## 三条刻意的设计选择（都有代价）

**① 发现"改了历史迁移"只报错、不拦启动。** 那是真问题，但"让 API 起不来"是更大的问题 ——
一个校验和笔误就能把线上打死。所以：`logger.error` + `status` 标红 + CI 红。

**② 迁移失败会拒绝启动**（`MigrationFailed` 从 `bootstrap` 抛出去）。
理由：带着半截结构对外服务比起不来更难查（本仓库 2026-09-04 那次 500 事故就是"结构不对但服务在跑"）。
真要带病启动有显式开关：`SORDERS_SKIP_MIGRATIONS=1`（会打 `CRITICAL` 日志）。

**③ 锁是独立的一把**（`/tmp/sorders_migrations.lock`，不是 bootstrap 那把）。
`flock` 是文件描述符级的 —— 同一个进程里对**同一个文件**再 `LOCK_EX` 会**自己把自己锁死**。
加锁顺序恒为 bootstrap → migrations（顺序反了会和 `uvicorn --workers 2` 死锁）。

## 校验和为什么要归一 CRLF

本机是 Windows（工作区里的 `.py` 是 CRLF），生产是 Linux（LF）。不归一的话同一份迁移在两处算出的
`checksum` 不同，表现是"到了生产就说你改了历史迁移" —— 而**假红会让人学会无视这条检查**
（本项目 §15 的教训：永远红的检查 = 没有检查）。所以 `_checksum()` 先把 `\r\n` 归一到 `\n`。

## 判据在哪

| 层 | 文件 | 管什么 |
|---|---|---|
| 静态 | `_tools/qa/_check_migrations.py --check` | 命名/版本号唯一递增/接线/失败不记账/漂移不抛异常/表名单点 |
| 单测 | `backend/tests/test_schema_migrations.py` | 幂等、顺序、漂移、失败重试、CRLF 校验和 |
| 真机 | `_tools/backup/_drill.sh`（恢复演练） | 恢复出来的**真实生产库**上能不能带着迁移跑起来 |

