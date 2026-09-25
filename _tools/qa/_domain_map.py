#!/usr/bin/env python3
"""领域边界地图的**共用解析器**（不是判据，不会被 `_check_all.py` 直接跑）。

## 为什么要有它
地图（`docs/DOMAIN_BOUNDARIES.md`）有几条判据要看：R2-01 的八条铁律、
R2-02 的命令注册表（命令归哪个域、副作用跨不跨域、事件有没有主）。
⛔ 让第二个判据自己再写一遍 "解析 domain 块 / 扫 __tablename__ / 扫 enqueue" 就是
「同一个事实写两遍」—— 本项目在这种地方栽过很多次（地图改了、一处判据改了、另一处没改）。
所以解析只有这一份，两边 import 它。

⚠️ 三个"自己算"的口径（不从文档抄）：表名来自 `models/**` 的 `__tablename__`；
事件来自 `outbox.enqueue(...)` 的字符串字面量；命令是否存在来自源码里的 `def`。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs/DOMAIN_BOUNDARIES.md"
APP = ROOT / "backend/app"
MODELS = APP / "models"

#: 每个域块必须有的键（少一个就是「地图缺了一半」）。
REQUIRED_KEYS = (
    "name", "中文名", "为什么是它自己的域",
    "owns", "commands", "reads", "events", "pure_consumer",
)

BLOCK_RE = re.compile(r"(?ms)^```domain[ \t]*$(.*?)^```[ \t]*$")
TABLE_RE = re.compile(r"__tablename__\s*=\s*\"([^\"]+)\"")
ENQUEUE_RE = re.compile(r"enqueue\(\s*db,\s*\"([^\"]+)\"")
DEF_DEFAULT_RE = re.compile(r"^\s*def\s+{name}\s*\(")


def split_list(value: str) -> list[str]:
    """逗号分隔的清单；`-` 与空串都表示「没有」。"""
    v = (value or "").strip()
    if not v or v == "-":
        return []
    return [x.strip() for x in v.split(",") if x.strip()]


def parse_blocks(text: str) -> tuple[list[dict], list[str]]:
    """把 `docs/DOMAIN_BOUNDARIES.md` 里的 domain 块解析成字典列表。

    返回 (blocks, 读不出来的行)。第二项非空就是「地图里有判据看不懂的东西」——
    ⛔ 不许静默跳过：那种行往往正是有人手写了一个判据不认识的字段。
    """
    blocks: list[dict] = []
    bad: list[str] = []
    for m in BLOCK_RE.finditer(text):
        d: dict = {}
        for line in m.group(1).splitlines():
            if not line.strip():
                continue
            key, sep, val = line.partition(":")
            if not sep or not key.strip():
                bad.append(line.strip()[:60])
                continue
            d[key.strip()] = val.strip()
        blocks.append(d)
    return blocks, bad


def load_blocks() -> tuple[list[dict], list[str]]:
    return parse_blocks(DOC.read_text(encoding="utf-8"))


def real_tables() -> set[str]:
    """项目里真有哪几张表 —— **自己算**，不从文档抄。"""
    out: set[str] = set()
    for f in MODELS.rglob("*.py"):
        out.update(TABLE_RE.findall(f.read_text(encoding="utf-8")))
    return out


def real_events() -> set[str]:
    """代码里真的在产生哪些事件类型 —— **自己算**。

    ⚠️ 用 `\\s*` 而不是 ` `：本项目多处 `enqueue(...)` 是**跨行**写的
    （`orders_return.py` / `return_requests.py` / `ledger.py`），
    只认单行会把它们漏掉，而漏掉的后果是「没人认领的事实」那条判据**永远绿**。
    """
    out: set[str] = set()
    for f in APP.rglob("*.py"):
        out.update(ENQUEUE_RE.findall(f.read_text(encoding="utf-8")))
    return out


def owner_map(blocks: list[dict]) -> dict[str, str]:
    """表名 → 域名（地图上的归属；重复归属留给判据去报红，这里取先出现的那个）。"""
    out: dict[str, str] = {}
    for d in blocks:
        for t in split_list(d.get("owns", "")):
            out.setdefault(t, d.get("name", "?"))
    return out


def event_owner_map(blocks: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for d in blocks:
        for ev in split_list(d.get("events", "")):
            out.setdefault(ev, d.get("name", "?"))
    return out


def dotted_to_rel(name: str) -> str | None:
    """`app.services.order_money` → `app/services/order_money.py`（相对 `backend/` 的路径）。

    找不到（既不是模块也不是包）返回 None。R2-03 起的两个依赖图判据共用这一份 ——
⛔ 各写一份的话，一处改了另一处不改，两张图的节点集就会悄悄不一样。
    """
    if not name.startswith("app."):
        return None
    tail = name[len("app."):].replace(".", "/")
    backend = ROOT / "backend"
    cand = APP / (tail + ".py")
    if cand.is_file():
        return cand.relative_to(backend).as_posix()
    pkg = APP / tail / "__init__.py"
    if pkg.is_file():
        return pkg.relative_to(backend).as_posix()
    return None


def command_problem(ref: str) -> str:
    """命令 `模块:函数` 是否真的存在；不存在就返回原因（空串 = 存在）。"""
    mod, sep, fn = ref.partition(":")
    if not sep or not mod or not fn:
        return "不是 `模块:函数` 的形状"
    path = APP / (mod.replace(".", "/") + ".py")
    if not path.exists():
        return "模块不存在：" + mod
    src = path.read_text(encoding="utf-8")
    if not re.search(r"(?m)^def " + re.escape(fn) + r"\(", src):
        return "函数不存在：" + fn
    return ""


def impl_path(ref: str) -> Path | None:
    mod = ref.partition(":")[0]
    path = APP / (mod.replace(".", "/") + ".py")
    return path if path.exists() else None
