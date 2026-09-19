import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402
"""看仓库已有的 gen_endpoint_index.py 能产出什么，判断我的生成器是不是重复轮子。只读。"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

SRC = repo_root() / "backend" / "scripts" / "gen_endpoint_index.py"


def main() -> int:
    s = SRC.read_text(encoding="utf-8")
    print(f"文件 {SRC.name}：{len(s.splitlines())} 行 / {len(s)} 字节")
    print("\n=== 能力关键词命中 ===")
    for kw in ("import ast", "openapi", "alias", "summary", "--check", "json",
               "require_permission", "require_roles", "params", "参数"):
        print(f"  {kw:<20} {s.count(kw)}")

    print("\n=== CLI 参数 ===")
    for m in re.finditer(r'add_argument\(\s*["\']([^"\']+)', s):
        print("  ", m.group(1))

    print("\n=== 顶层 class / def ===")
    for m in re.finditer(r"^(?:class|def)\s+(\w+)", s, re.M):
        print("  ", m.group(1))

    print("\n=== 是否已提取 Query 参数与 alias ===")
    for m in re.finditer(r"^.*\balias\b.*$", s, re.M):
        t = m.group(0).strip()
        if len(t) < 160:
            print("  ", t)

    return 0


if __name__ == "__main__":
    sys.exit(main())
