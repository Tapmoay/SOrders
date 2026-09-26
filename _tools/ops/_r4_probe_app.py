# -*- coding: utf-8 -*-
"""R4 演练用的小探针：打印**应用与模型**的只读事实（一行 JSON）。

为什么单独一个文件、而不是在演练脚本里 `python -c "..."`：
`-c` 里塞多行 Python 要跟 shell 的引号打架（本项目栽过好几次），
而且"探测"这件事本身值得是一个能被单独跑、单独看的脚本。

⛔ 它**只读**：不连库、不写文件、不起服务。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

#: `__tablename__ = "users"` 或 `= 'users'` —— 两种引号都要认（模型里两种都出现过）。
_DQ = chr(34)
_SQ = chr(39)
_QS = "[" + _DQ + _SQ + "]"
TABLENAME_RE = re.compile("__tablename__" + r"\s*=\s*" + _QS
                          + "([^" + _DQ + _SQ + "]+)" + _QS)


def route_paths() -> tuple[bool, list[str], str]:
    """应用起不起得来 + 它挂了哪些路由。起不来就把原因带回去（⛔ 不吞）。"""
    try:
        from app.main import fastapi_app
    except Exception as exc:  # noqa: BLE001 —— 演练要看的就是"起不起得来"
        return False, [], str(exc)[:300]
    return True, sorted(getattr(r, "path", "") for r in fastapi_app.routes), ""


def table_names() -> list[str]:
    names: set[str] = set()
    for f in (ROOT / "backend" / "app" / "models").rglob("*.py"):
        names.update(TABLENAME_RE.findall(f.read_text(encoding="utf-8", errors="replace")))
    return sorted(names)


def main() -> int:
    boot, routes, err = route_paths()
    print(json.dumps({"boot": boot, "boot_error": err, "routes": routes,
                      "tables": table_names()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())