import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402
"""交叉验证：08A（权威，AST 生成） 与 docs/ai/ai_toolmap.json（我的工具白名单）是否一致。

意义：两份清单来自**两个不同的生成器**。差异要么说明我的生成器有 bug，
要么说明 08A 与我覆盖面不同（例如 08A 含 main.py 的 app 级端点）。只读。
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = repo_root()
IDX = ROOT / "docs" / "PROJECT_MAP" / "08A_ENDPOINT_INDEX.md"
TM = ROOT / "docs" / "ai" / "ai_toolmap.json"

# 08A 的表格行形如：| 1 | `GET /api/v1/orders` | `handler` | `path:line` | 授权 |
ROW = re.compile(r"\|\s*\d+\s*\|\s*`(GET|POST|PUT|PATCH|DELETE)\s+([^`]+)`")


def main() -> int:
    text = IDX.read_text(encoding="utf-8")
    rows = ROW.findall(text)
    idx = {(m, p.strip()) for m, p in rows}

    d = json.loads(TM.read_text(encoding="utf-8"))
    mine = {(a["method"].upper(), a["path"]) for v in d["modules"].values() for a in v["actions"]}

    print(f"08A 解析出端点：{len(idx)}")
    print(f"toolmap 端点：{len(mine)}")

    only_idx = sorted(idx - mine)
    only_mine = sorted(mine - idx)
    print(f"\n【08A 有、toolmap 没有】{len(only_idx)} 条：")
    for m, p in only_idx:
        print(f"   {m:<6} {p}")
    print(f"\n【toolmap 有、08A 没有】{len(only_mine)} 条：")
    for m, p in only_mine:
        print(f"   {m:<6} {p}")
    if not only_idx and not only_mine:
        print("\n✅ 两份清单完全一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
