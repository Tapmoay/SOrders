"""列出所有写端点 + 白名单判定（诊断用：确认 fuzz 工具到底会碰哪些端点）。

用法：
```
python _tools/fuzz/_list_ops.py              # 全部写端点 + 是否被 DENY
python _tools/fuzz/_list_ops.py --danger     # 只看被 DENY 的
```
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fuzzlib import denied, openapi, write_ops  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]


def main() -> int:
    only_danger = "--danger" in sys.argv
    doc = openapi()
    ops = write_ops(doc, (), skip_denied=False)
    blocked = tested = 0
    for op in ops:
        filled = op.path
        for a, b in (("{", "1"), ("}", "")):
            filled = filled.replace(a, b)
        why = denied(op.method, filled)
        if why:
            blocked += 1
            print(f"  ⛔ {op.method:6} {op.path:52} {why}")
        else:
            tested += 1
            if not only_danger:
                print(f"  ·  {op.method:6} {op.path:52} 字段 {len(op.fields)}")
    print(f"\n写端点 {len(ops)} 个：fuzz 会测 {tested} 个 / 白名单拦下 {blocked} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
