'''命令追踪 ID（R3-04-A）—— `request_id` / `command_id` / `event_id` 是**三个**概念，不许混。

## 指南 §R3-04-A 的原话

```text
request_id     ↓     command_id     ↓     OrderCompleted     ↓     event_id
一个 HTTP 请求可以触发：多个 command / 多个 event
所以不能假设：1 request = 1 event
```

## 三者各是什么（本项目里的实际含义）

| 概念 | 一次是什么 | 谁给 | 落在哪 |
| --- | --- | --- | --- |
| `request_id` | **一次 HTTP 请求** | `core/request_id.py` 的中间件（或客户端透传 `X-Request-ID`）| `operation_logs.request_id`、每行日志 |
| `command_id` | **一条命令的一次执行**（`order.create#3f2a1c9d`）| 本模块的 `command_scope()`，由命令层自己开 | `operation_logs.command_id`、每行日志 |
| `event_id` | **一条发件箱事件** | `core/outbox.py` 入队时生成 | `outbox_events.id` |

⛔ **为什么不能合成一个**：一次请求可以派 N 张单（`batch-assign` 一次请求 → N 条 `order.assign` 命令），
一条命令又可以产生多条事件（`order.create` → `orders.created` + `orders.pending_pool_changed`）。
合成一个 id 之后，「这次请求到底改了几张单」「这条事件是哪条命令产生的」都答不了。

## 边界（说清楚，免得被当成更强的保证）

`command_id` 由**命令层自己开**（`app/commands/order.py`），不是中间件给的 ——
所以**只有走命令层的动作有它**；直接调 service / order_flow 的老路径仍然只有 `request_id`。
判据 `_check_traceability.py` 核的就是这条边界（哪些入口有、哪些还没有）。
'''
from __future__ import annotations

import functools
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

#: 当前命令的追踪 id。默认空串 = 不在命令上下文里（请求外、或走的是非命令层路径）。
_command_id: ContextVar[str] = ContextVar('command_id', default='')

#: 命令名与 id 之间用 `#` 分隔：日志里一眼能看出**这是哪条命令**（只给一个裸 hex 谁也认不出）。
SEP = '#'


def get_command_id() -> str:
    '''当前命令的追踪 id（不在命令里时返回空串）。日志 filter 与审计行都用它。'''
    return _command_id.get()


def new_command_id(name: str) -> str:
    '''生成一条命令的 id：`<name>#<8 位十六进制>`。'''
    return name + SEP + uuid.uuid4().hex[:8]


def traced_command(name: str):
    '''给命令函数套一层：进入时开作用域，里面的审计行自动带上同一个 `command_id`。

    ⛔ **用它而不是在每个函数体里手写 `with`**：手写要把整个函数体缩进一层，
    那种 diff 没法 review（而且以后有人加函数时一定会漏）。一行装饰器，意图也看得见。
    `functools.wraps` 保住签名与 docstring —— 路由层的形参、判据的 AST 解析都不受影响。
    '''

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with command_scope(name):
                return fn(*args, **kwargs)

        return wrapper

    return deco


@contextmanager
def command_scope(name: str) -> Iterator[str]:
    '''命令层用它罩住一次执行：进入时分配 id，退出时还原（可嵌套 —— 内层命令有自己的 id）。

    ⛔ 用 `ContextVar` + `reset(token)` 而不是「设完再设回空串」：后者在并发请求下会把
    **别人的** command_id 擦掉（本项目在 request_id 上就是这么做的，理由相同）。
    '''
    cid = new_command_id(name)
    token = _command_id.set(cid)
    try:
        yield cid
    finally:
        _command_id.reset(token)

