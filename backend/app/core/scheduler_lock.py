'''调度任务的**选主**（R3-03-B）：多实例时只让一个执行者跑。

## 两层锁，缺一层都不成立

```text
本机层  FileLock(<tempdir>/sorders_retention.lock)   同机多进程（uvicorn --workers N）
跨主机  MySQL GET_LOCK('sorders:scheduler:retention') 跨机器（多实例部署）
```

⛔ **与迁移锁不是同一把**（指南 §R3-03-B 明说）：

| | 锁名 | 生命周期 |
| --- | --- | --- |
| 迁移 | `sorders_migrations` | 只在跑迁移的那几秒 |
| 调度 | `sorders:scheduler:retention` | 只在跑那一轮治理的期间 |

判据 `_check_r3_constraints.py` 的 `distinct_lock_names` 探针会拿所有 `*LOCK_NAME*` 常量核对重名。

## 为什么是「拿不到就跳过」而不是「等它跑完」

这是数据治理：等第一个跑完再原样跑一遍**没有任何意义**（那一轮该删的已经删了），
而排队会让第二个 worker 白白占着启动路径。所以两层都用**非阻塞**语义。

## 诚实交代：本机（SQLite/Windows）证到哪一步

· 本机层：R3-01 起 `FileLock` 在 Windows 上也是真锁（`msvcrt.locking`），同机多进程可证；
· 跨主机层：`GET_LOCK` **只在 MySQL 上成立** —— SQLite 上如实不做，只记一行日志。
  所以「跨机器只跑一个」这一条**在本机证不了**，要到多实例环境上验（与 `_db_lock` 同口径）。
'''
from __future__ import annotations

import logging
import tempfile
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.file_lock import FileLock, FileLockTimeout

logger = logging.getLogger(__name__)

#: ⛔ 与迁移锁 `sorders_migrations` **不同名**（指南 §R3-03-B）。
SCHEDULER_LOCK_NAME = 'sorders:scheduler:retention'

#: 本机层的锁文件（与迁移锁文件 `sorders_migrations.lock` 也不同名）。
SCHEDULER_LOCK_FILE = str(Path(tempfile.gettempdir()) / 'sorders_scheduler_retention.lock')

#: `GET_LOCK` 的等待秒数：**0 = 试一次，拿不到就走**（见模块开头：排队没有意义）。
SCHEDULER_LOCK_WAIT_S = 0


@contextmanager
def scheduler_leader(engine: Engine) -> Iterator[bool]:
    '''拿到选主权就 yield True，否则 yield False（调用方跳过这一轮）。

    ⛔ 顺序固定：**先本机、后服务端**（与迁移锁一致）。反着写会在同一台机器上先占住服务端锁、
    再等本机锁，而本机锁的持有者可能正是等着服务端锁的另一个进程 —— 死锁。
    '''
    # ---- 本机层（非阻塞）----
    # ⛔ `reentrant=False`：调度选主**同进程也要挡住** —— 同一进程里两个线程同时触发治理，
    #    与两个进程同时触发是同一件事（迁移那把锁要重入，这把不要）。
    local = FileLock(SCHEDULER_LOCK_FILE, wait_s=0, reentrant=False)
    try:
        local.__enter__()
    except FileLockTimeout:
        logger.info('本机已有另一个进程在跑（%s），本轮跳过', SCHEDULER_LOCK_FILE)
        yield False
        return

    got = True
    conn = None
    try:
        # ---- 跨主机层（仅 MySQL；SQLite 上如实不做）----
        if engine.dialect.name == 'mysql':
            conn = engine.connect()
            try:
                got = conn.execute(
                    text('SELECT GET_LOCK(:n, :t)'),
                    {'n': SCHEDULER_LOCK_NAME, 't': SCHEDULER_LOCK_WAIT_S},
                ).scalar() == 1
            except Exception:                       # noqa: BLE001 —— 拿不到就跳过，不许拖垮启动
                logger.warning('取调度锁失败（当成拿不到，本轮跳过）', exc_info=True)
                got = False
            if not got:
                logger.info(
                    '另一个实例已经是执行者（%s），本轮跳过', SCHEDULER_LOCK_NAME,
                )
        else:
            logger.debug(
                '调度选主：当前库是 %s（单机文件库），只用本机锁；跨主机选主只在 MySQL 上成立',
                engine.dialect.name,
            )
        yield got
    finally:
        if conn is not None:
            try:
                conn.execute(text('SELECT RELEASE_LOCK(:n)'), {'n': SCHEDULER_LOCK_NAME})
                conn.commit()
            except Exception:                       # noqa: BLE001
                logger.debug('释放调度锁失败（连接关闭时会自动释放）', exc_info=True)
            finally:
                conn.close()
        local.__exit__(None, None, None)
