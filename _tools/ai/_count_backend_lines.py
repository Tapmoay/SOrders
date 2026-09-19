"""统计后端各层真实行数（供文档声明核对；口径 = readlines 物理总行数）。只读。"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

BACKEND = repo_root() / "backend" / "app"


def count(sub: str) -> tuple[int, int]:
    files = sorted((BACKEND / sub).glob("*.py"))
    lines = sum(len(f.read_text(encoding="utf-8", errors="ignore").splitlines()) for f in files)
    return len(files), lines


def main() -> int:
    for sub in ("api/v1", "services", "models", "schemas", "core"):
        n, ln = count(sub)
        print(f"  {sub:<12} {n:>3} 文件  {ln:>6} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
