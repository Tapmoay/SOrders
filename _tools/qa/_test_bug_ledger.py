# -*- coding: utf-8 -*-
"""测试缺陷统一台账的**追加器**（方向 A / 方向 B 共用 docs/TEST_BUG_LEDGER.md）。

为什么要有它：那个文件被两个方向、可能还有并行会话同时写 —— 手改容易撞车、编号容易重。
本脚本**读全文 → 改 → 原子写回**（临时文件 + os.replace），并自动算下一个编号。

用法（都在仓库根跑）：

    python -X utf8 _tools/qa/_test_bug_ledger.py list [--dir A|B]
    python -X utf8 _tools/qa/_test_bug_ledger.py show TA-01
    python -X utf8 _tools/qa/_test_bug_ledger.py add --dir A --title "标题" --severity 可见 ^
        --status 已复现 --phenomenon "现象" --repro "复现步骤" --expect "期望" --actual "实际" ^
        --where backend/app/api/v1/orders.py:88 --where android/app/src/main/java/.../OrderDetail.kt:12 ^
        --evidence "shots/x.png（派单后池子里还有这一单）" --fix "建议改法"

⚠️ 本文件**不**以 _check_ 开头，也不声明 --check，所以 _tools/qa/_check_all.py 的全量静检不会跑它
（见 _tools/qa/_check_all.py:100-118 的 discover()：只收 _check_*.py 与声明了 --check 的脚本）。
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import os
import re
import sys
import time
from pathlib import Path

# GBK 控制台/管道下 ✅/❌ 会 UnicodeEncodeError（"看着跑过了，其实没验"）——
# `_tools/qa/_check_tool_scripts.py:101` 会扫这一条，别删。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "docs" / "TEST_BUG_LEDGER.md"
CST = dt.timezone(dt.timedelta(hours=8))
DIRS = {"A": "方向 A（订单与基础数据）", "B": "方向 B（财务）"}
SEVERITY = ["堵死", "错数", "可见", "可疑"]
STATUS = ["待核实", "已复现", "已核实（静态代码路径）", "已立项", "已修复", "不修"]
CN = {"A": "二", "B": "三"}
PREFIX = {"A": "TA", "B": "TB"}
REV = {"TA": "A", "TB": "B"}


def read_text(p: Path) -> str:
    if not p.exists():
        raise SystemExit("找不到台账文件：" + str(p))
    with io.open(p, encoding="utf-8", newline="") as f:
        return f.read()


def write_text(p: Path, text: str) -> None:
    tmp = p.with_suffix(p.suffix + ".tmp")
    with io.open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, p)


def rows(text: str, which: str) -> list:
    """返回该方向已有的 (编号, 整行)。"""
    out = []
    for line in text.split("\n"):
        m = re.match(r"\|\s*(" + PREFIX[which] + r"-\d+)\s*\|", line)
        if m:
            out.append((m.group(1), line.rstrip()))
    return out


def next_id(text: str, which: str) -> str:
    n = 0
    for existing, _ in rows(text, which):
        n = max(n, int(existing.split("-")[1]))
    return PREFIX[which] + "-" + ("%02d" % (n + 1))


def cell(s: str, limit: int = 0) -> str:
    s = " ".join((s or "").split())
    if limit and len(s) > limit:
        s = s[: limit - 1] + "…"
    return s.replace("|", "／") or "—"


def insert_before(text: str, marker: str, block: str, gap: str = "\n") -> str:
    """把 block 插到锚点前面。

    ⚠️ gap 是**块与下一块之间**的空隙：总表行用单换行（一行一条），
    详情块必须用空行 —— 不然连着追加两条时 `### TA-02` 会紧贴在 TA-01 的最后一行下面
    （本脚本自己踩过：第一版写死单换行）。
    """
    if marker not in text:
        raise SystemExit("台账里找不到锚点 " + marker + " —— 文件被改过？先看 docs/TEST_BUG_LEDGER.md 的一、二、三节。")
    return text.replace(marker, block.rstrip("\n") + gap + marker, 1)



class _Lock:
    """跨进程互斥：两个方向的测试会话可能同时往同一份台账里追加。

    做法：O_CREAT|O_EXCL 抢一个 .lock 文件，抢不到就退避重试（最多 ~20 秒），
    拿到锁再"读全文 → 改 → os.replace 原子写回" —— 这样不会丢更新。
    """

    def __init__(self, target: Path, timeout: float = 20.0):
        self.path = target.with_suffix(target.suffix + ".lock")
        self.timeout = timeout
        self.fd = None

    def __enter__(self):
        t0 = time.time()
        while True:
            try:
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, str(os.getpid()).encode("ascii"))
                return self
            except FileExistsError:
                if time.time() - t0 > self.timeout:
                    raise SystemExit("台账被另一个进程锁着（" + str(self.path) + "）。等一会儿再来，或删掉这个 .lock 文件。")
                time.sleep(0.2)

    def __exit__(self, *exc):
        try:
            if self.fd is not None:
                os.close(self.fd)
        finally:
            try:
                os.remove(str(self.path))
            except OSError:
                pass
        return False

def cmd_add(a) -> int:
    p = Path(a.ledger) if a.ledger else LEDGER
    with _Lock(p):
        return _add_locked(a, p)


def _add_locked(a, p: Path) -> int:
    text = read_text(p)
    which = a.dir.upper()
    if which not in DIRS:
        raise SystemExit("--dir 只能给 A 或 B")
    if a.severity not in SEVERITY:
        raise SystemExit("--severity 只能给：" + " / ".join(SEVERITY))
    if a.status not in STATUS:
        raise SystemExit("--status 只能给：" + " / ".join(STATUS))
    bid = next_id(text, which)
    now = dt.datetime.now(CST).strftime("%Y-%m-%d %H:%M")
    wheres = [w for w in (a.where or []) if w.strip()]
    table_row = "| " + " | ".join([
        bid, which, cell(a.title, 40), a.severity, a.status,
        cell(a.phenomenon, 62), cell("<br>".join(wheres), 46), cell(a.evidence, 40)]) + " |"
    detail = ["### " + bid + " · " + a.title, ""]
    line1 = "- 严重度：" + a.severity + "　／　状态：" + a.status + "　／　记录：" + now + " CST"
    if a.owner:
        line1 += "　／　记录人：" + a.owner
    detail.append(line1)
    for label, key in (("现象", "phenomenon"), ("复现", "repro"), ("期望", "expect"),
                       ("实际", "actual"), ("证据", "evidence"), ("建议改法", "fix")):
        v = (getattr(a, key) or "").strip()
        if v:
            detail.append("- " + label + "：" + v)
    if wheres:
        detail.append("- 定位：" + "　".join("@@%s@@" % w for w in wheres))
    detail.append("")
    detail_text = "\n".join(detail).replace("@@", chr(96))
    text = insert_before(text, "<!-- TESTBUG:ROWS:" + which + " -->", table_row)
    text = insert_before(text, "<!-- /TESTBUG:DETAIL:" + which + " -->", detail_text, gap="\n\n")
    write_text(p, text)
    print("✅ 已追加 " + bid + "（" + DIRS[which] + "）：" + a.title)
    print("   总表行 → 一、总表 " + which + " 段；详情块 → 第" + CN[which] + "节")
    return 0


def cmd_list(a) -> int:
    p = Path(a.ledger) if a.ledger else LEDGER
    text = read_text(p)
    for which in ("A", "B"):
        if a.dir and a.dir.upper() != which:
            continue
        got = rows(text, which)
        print("")
        print("== " + DIRS[which] + "：" + str(len(got)) + " 条 ==")
        if not got:
            print("（还没有）")
            continue
        for _, line in got:
            print(line)
    print("")
    return 0


def cmd_show(a) -> int:
    p = Path(a.ledger) if a.ledger else LEDGER
    text = read_text(p)
    tid = a.id.upper()
    m = re.search(r"^### " + re.escape(tid) + r" ·.*?(?=^### |\Z)", text, re.M | re.S)
    if m:
        print(m.group(0).rstrip())
        return 0
    which = REV.get(tid.split("-")[0], "A")
    print("没找到 " + tid + " 的详情块（第" + CN.get(which, "二") + "节）。总表里的行：")
    for existing, line in rows(text, which):
        if existing == tid:
            print(line)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="测试缺陷统一台账（docs/TEST_BUG_LEDGER.md）追加器")
    ap.add_argument("--ledger", default=None, help="台账路径（默认 docs/TEST_BUG_LEDGER.md；自测时才用）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    add = sub.add_parser("add", help="追加一条")
    add.add_argument("--dir", required=True, help="A=订单与基础数据；B=财务")
    add.add_argument("--title", required=True)
    add.add_argument("--severity", required=True)
    add.add_argument("--status", default="待核实")
    add.add_argument("--phenomenon", default="")
    add.add_argument("--repro", default="")
    add.add_argument("--expect", default="")
    add.add_argument("--actual", default="")
    add.add_argument("--evidence", default="")
    add.add_argument("--fix", default="")
    add.add_argument("--where", action="append", default=[], help="文件:行，可重复")
    add.add_argument("--owner", default="")
    add.set_defaults(fn=cmd_add)

    ls = sub.add_parser("list", help="看总表里已有的行")
    ls.add_argument("--dir", default=None, help="只看某个方向")
    ls.set_defaults(fn=cmd_list)

    sh = sub.add_parser("show", help="看某条的详情块")
    sh.add_argument("id")
    sh.set_defaults(fn=cmd_show)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
