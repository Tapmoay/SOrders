"""数据库迁移（整改报告 §4「整个架构改造的第一核心任务」）。

对外只有四个名字，其余都是实现细节：

```python
from app.migrations import run_migrations, migration_status, current_version, VERSION_TABLE
```

· `run_migrations(engine)` —— 把没跑过的迁移按版本号跑掉（幂等）；
  ⛔ 它**只**跑版本化迁移。「自愈 DDL + 迁移」的完整入口是
  `app.core.schema_bootstrap.prepare_schema(engine)`（= `python -m app.migrations upgrade`）；
· `migration_status(engine)` —— 当前版本 / 待跑 / 内容变过的（给人和 CI 看）；
· `current_version(engine)` —— 只要当前版本号；
· `schema_ready(engine)` —— **只读**核对「结构准备好了吗」（应用启动用它，⛔ 它不建表）；
· `VERSION_TABLE` —— 版本表名（`schema_versions`），备份清单与探针共用这一处。

口径、分工、以及"什么时候该写一条迁移"见同目录 `README.md`。
"""

from __future__ import annotations

from app.migrations._runner import (
    MIGRATIONS_DIR,
    VERSION_TABLE,
    Migration,
    MigrationError,
    MigrationFailed,
    applied_versions,
    current_version,
    discover,
    ensure_version_table,
    last_migration_duration_ms,
    migration_status,
    run_migrations,
    schema_ready,
)

__all__ = [
    "MIGRATIONS_DIR",
    "VERSION_TABLE",
    "Migration",
    "MigrationError",
    "MigrationFailed",
    "applied_versions",
    "current_version",
    "discover",
    "ensure_version_table",
    "last_migration_duration_ms",
    "migration_status",
    "run_migrations",
    "schema_ready",
]
