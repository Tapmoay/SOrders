"""001 基线：把「bootstrap 自愈出来的结构」登记为版本 1。

### 为什么第一条迁移什么都不做

这份仓库在 2026-09-24 之前**所有**的结构变更都发生在 `core/schema_bootstrap.py` 里（幂等 DDL，
每次启动重跑一遍）。也就是说：库里的结构早就不是任何"迁移序列"跑出来的。

于是"从哪开始版本化"只有一个诚实的答案 —— **从现在这一刻开始**：

```text
版本 1 = 本仓库当前 HEAD 的模型结构（由 bootstrap 保证）
版本 2、3、4… = 从今往后每一次真正的结构变更
```

⛔ 这条迁移**不许**改成"把 bootstrap 那 1600 行搬过来重跑一遍"：那些 DDL 已经在每个库上跑过，
搬过来只会制造一次"看起来像迁移、实际是重复动作"的假历史，而报告 §18 规则 1 明确要求一次只动一个维度。

### 它到底有什么用（不是仪式）

1. **回答"数据库现在是什么状态"**：`SELECT MAX(version) FROM schema_versions` 就是答案；
2. **给后面的迁移当锚点**：`002_xxx` 可以放心假定"版本 1 的结构已经在了"；
3. **给备份/恢复当证据**：备份清单里的 `schema_version` 字段就是从这里读的（`_tools/backup/_backup.sh`），
   恢复时能一眼看出"这份备份是版本几的库"。
"""

from __future__ import annotations

from sqlalchemy.engine import Engine

VERSION = 1
NAME = "baseline"
DESCRIPTION = "基线：登记当前结构（不执行 DDL）；此前结构由 schema_bootstrap 自愈保证"


def upgrade(engine: Engine) -> None:  # noqa: ARG001 —— 基线刻意不碰库
    """什么都不做（见模块开头）。有 `upgrade` 是因为运行器要求每条迁移都得有。"""
    return None
