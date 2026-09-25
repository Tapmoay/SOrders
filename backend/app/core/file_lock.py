'''跨进程文件锁：Linux 用 `fcntl.flock`，Windows 用 `msvcrt.locking`。

## 为什么要有这一个模块（R3-01 实测）

在这之前，迁移与本机自愈的互斥**长这样**：

```python
try:
    import fcntl            # ← Windows 上没有
except ImportError:
    ...                     # ← 于是直接往下跑，**等于没有锁**
```

后果不是「慢一点」，而是：R3-01 的并发迁移测试里，两个进程同时 `upgrade`，
第二个在 `create_all` 上撞到 `table already exists` **直接失败退出**（实测，不是推测）。
而指南 R3-01-E 测试 3 要求的正是「只能一个实际执行，**另一个应该等待 → 发现已经完成 → 继续启动**」。

所以这里把「同一台机器上的互斥」抽成一处实现，两条路径共用：

· 迁移（`app/migrations/_runner.py::_lock`）—— 锁文件 `sorders_migrations.lock`
· 本机自愈（`app/core/schema_bootstrap.py`）—— 锁文件 `sorders_bootstrap.lock`

⛔ 两把锁**名字不同、生命周期不同**（各自进各自出，不嵌套）—— 名字相同会让「谁在等谁」说不清。
⛔ 跨**主机**的互斥不在这里：那是 MySQL 的 `GET_LOCK`（见 `_runner._db_lock`）。
'''
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

#: 拿不到锁最多等多久（与 `_db_lock` 的 `GET_LOCK` 超时同口径：60 秒）。
DEFAULT_WAIT_S = 60.0

#: 本进程已经持有的锁 → 重入层数。
#: ⛔ 为什么必须有它：`fcntl.flock` / `msvcrt.locking` 都是**按打开的文件描述符**算的，
#:    同一个进程对同一个锁文件再拿一次会**把自己锁死**（模块开头那条 --workers 2 的老坑）。
#:    有了计数器，嵌套使用同一个锁就退化成空操作，而不是死锁。
_HELD: dict[str, int] = {}


class FileLockTimeout(RuntimeError):
    '''等锁超时 —— 调用方自己决定怎么翻译（迁移会包成 MigrationError）。'''


class FileLock:
    '''文件锁上下文管理器。进 → 拿锁（阻塞到超时）；出 → 放锁并关文件。

    · Linux/macOS：`fcntl.flock(LOCK_EX)` —— 进程退出时由内核自动释放；
    · Windows：`msvcrt.locking(LK_NBLCK)` 轮询 —— 同样是**进程级**的强制锁，
      进程崩了锁也会被系统收回（不会留下「僵尸锁文件」那种要靠人删的坑）。
    '''

    def __init__(self, path: str | Path, *, wait_s: float = DEFAULT_WAIT_S,
                 reentrant: bool = True) -> None:
        self.path = str(path)
        self.wait_s = wait_s
        #: 同一个进程里再拿一次同一把锁时：
        #: · `reentrant=True`（默认）→ 当成重入，直接放行 —— 迁移入口 `prepare_schema` 需要它
        #:   （它自己拿一把，里面的自愈再拿同一把，不能死锁）；
        #: · `reentrant=False` → **真去抢**，同进程也会被挡住 —— 调度选主要它：
        #:   「同一进程里两个线程同时触发治理」和「两个进程同时触发」一样必须只跑一个。
        self.reentrant = reentrant
        self._fh = None
        self._reentrant = False

    def __enter__(self) -> 'FileLock':
        key = os.path.abspath(self.path)
        if self.reentrant and _HELD.get(key):
            _HELD[key] += 1
            self._reentrant = True
            return self
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # ⛔ 用 append 打开，**不许用 'w+'**：'w+' 会截断文件，而 Windows 的文件锁是**强制**的 ——
        #    别人持锁时截断会直接 `PermissionError: [Errno 13]`（实测：第二个进程不是「等待」，
        #    而是当场崩掉，于是「另一个应该等待」这条要求根本不成立）。
        self._fh = open(self.path, 'a+b')
        try:
            import fcntl
        except ImportError:
            fcntl = None                                  # type: ignore[assignment]
        if fcntl is not None:
            # Linux 的 flock 是建议锁，截断不拦人；但两条平台用同一套打开方式，少一处分叉。
            self._ensure_one_byte()
            if self.wait_s <= 0:
                # ⛔ `wait_s=0` 必须是**真的非阻塞**：`flock(LOCK_EX)` 会一直等下去
                #    （Windows 分支本来就是非阻塞的，两边语义要对齐 —— 调度选主要「拿不到就走」）。
                try:
                    fcntl.flock(self._fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    self._fh.close()
                    self._fh = None
                    raise FileLockTimeout(self._timeout_msg()) from None
            else:
                fcntl.flock(self._fh, fcntl.LOCK_EX)
            if self.reentrant:
                _HELD[key] = 1
            return self
        # ---- Windows ----
        import msvcrt

        self._ensure_one_byte()
        deadline = time.monotonic() + self.wait_s
        while True:
            try:
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                if self.reentrant:
                    _HELD[key] = 1
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    self._fh.close()
                    self._fh = None
                    raise FileLockTimeout(self._timeout_msg())
                time.sleep(0.05)

    def _timeout_msg(self) -> str:
        return ('拿不到文件锁 ' + self.path + '（等了 ' + str(self.wait_s) + 's）——'
                ' 另一个进程还在跑？先看 python -m app.migrations status')

    def _ensure_one_byte(self) -> None:
        '''`msvcrt.locking` 锁的是**字节区间**，文件至少要有 1 字节。

        ⛔ 别人正持着锁时，写入可能被拒绝（Windows 强制锁）—— 那不是错误：
        说明这一字节**已经存在**（正是持锁那位写的），吞掉即可。
        '''
        assert self._fh is not None
        self._fh.seek(0, 2)
        if self._fh.tell() > 0:
            return
        try:
            self._fh.write(b'x')
            self._fh.flush()
        except OSError:
            logger.debug('锁文件已有内容（另一个人正在持锁）', exc_info=True)

    def _release(self) -> None:
        key = os.path.abspath(self.path)
        if self._reentrant:
            left = _HELD.get(key, 1) - 1
            if left > 0:
                _HELD[key] = left
            else:
                _HELD.pop(key, None)
            self._reentrant = False
            return
        if self._fh is None:
            return
        fh, self._fh = self._fh, None
        try:
            try:
                import fcntl
            except ImportError:
                fcntl = None                              # type: ignore[assignment]
            if fcntl is not None:
                fcntl.flock(fh, fcntl.LOCK_UN)
            else:
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:                                   # noqa: BLE001 —— 放锁失败不该盖住业务异常
            logger.debug('放文件锁失败（忽略）', exc_info=True)
        finally:
            fh.close()
            if self.reentrant:
                _HELD.pop(key, None)

    def __exit__(self, *exc) -> bool:
        self._release()
        return False

