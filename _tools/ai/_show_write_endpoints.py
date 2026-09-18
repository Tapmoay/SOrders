"""按模块列出写端点的 body 字段与后端守卫（补能力前先看这张表，别凭记忆写）。

用法：
    python _tools/ai/_show_write_endpoints.py                # 全部未覆盖的
    python _tools/ai/_show_write_endpoints.py notifications  # 只看某个模块
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
EPS = json.loads((ROOT / "docs/ai/write-endpoints.json").read_text(encoding="utf-8"))


def show_guards(ep: dict) -> None:
    """把这个 handler 里的状态检查/403/400 行摘出来——卡片的前置条件就写在这些行里。"""
    p = ROOT / "backend/app/api" / ep["file"]
    if not p.exists():
        return
    src = p.read_text(encoding="utf-8")
    lines = src.splitlines()
    start = ep["line"] - 1
    body = []
    depth = 0
    for ln in lines[start : start + 90]:
        body.append(ln)
        if re.match(r"^\S", ln) and body and len(body) > 1 and not ln.startswith(("@", "def", "async")):
            break
    for ln in body:
        s = ln.strip()
        if any(k in s for k in ("HTTPException", "status_code=", "if order", "if not ", "is None")):
            if "detail=" in s or s.startswith("if ") or "status_code" in s:
                print("      ", s[:120])


def main() -> int:
    want = sys.argv[1] if len(sys.argv) > 1 else None
    for e in EPS:
        f = e.get("file") or ""
        if want and want not in f:
            continue
        print(f"{e['method']:6s} {e['path']:56s} {e['handler']:28s} auth={e.get('auth')}")
        for x in e.get("bodyFields") or []:
            req = "必填" if x["required"] else "可选"
            print(f"       {x['name']:28s} {x['type']:18s} {req} 默认={x.get('default')}")
        show_guards(e)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
