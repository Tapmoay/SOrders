# -*- coding: utf-8 -*-
"""核心 / 扩展边界判据（R4-01 的机器形态）。

R4-BOUNDARY-JUSTIFICATION: 这一条**不是**"再多一条红线"能替代的东西。它守的是
**类别的正确性**（这个东西到底是核心、扩展点、扩展实现，还是基础设施）——
而"分错档"这个错误在任何单点上都不违反代码边界：一个把 Ledger 标成 EXTENSION 的注解、
一个把"算运费"写进核心的 if 分支，**语法合法、类型正确、测试全绿**，
只有"把整张图拿出来看"才发现它错了。所以它必须是一份**声明 + 一份对账**，
而不是某个模块内部的约束。

## 为什么它必须对账，而不是背清单

R4 指南 §3 点名了最危险的误判：看到 15 个领域、47 张表、57 条命令，
就"给 15 个领域全部做成模块"。**这一页的作用正是阻止那件事** —— 先把每样东西定在哪一档。
所以判据核的是"**是不是每样东西都被定过档**"（Unclassified = 0），而不是"文档写得好不好看"。
它自己算三样东西，**一样都不从文档抄**：

1. **表清单**：backend/app/models 里所有 __tablename__；
2. **事件类型**：源码里 outbox.enqueue(db, "…") 的字符串字面量；
3. **实现站点**：每一条 impl 声明的 文件::符号 拿去源码里核对真的存在。

## 判据（七组）

1. **文档形状**：块数 ≥ 下限、id 唯一、class 合法、九个字段齐全、why ≥ 20 字；
2. **Unclassified = 0**：47 张表**恰好一个归属**（与 DOMAIN_BOUNDARIES 铁律 1 同源，
   但多问一句"它属于核心还是扩展"）；
3. **事件（指南 §28）**：代码里的 18 个事件类型与 §5.2 的表**双向**对上，
   且最后一列**必须全是 ❌**（= 核心事实不依赖事件消费者）；
4. **Event 不是隐藏调用**：main.py::_outbox_deliver 里每一个调用
   都只许落在"推送/消息"白名单里 —— 出现任何一个业务服务就是"事件变成了隐形 RPC"；
5. **实现站点真实存在**（防化石：写了一个已经被改名/删掉的符号）；
6. **契约版本上限**（§31 坑 13：不许为了兼容保留 10 代接口）；
7. **静默空转保护**：块数 / 表数 / 事件数 / 真正核对过的 impl 数都要过下限 ——
   清单被掏空或格式变了导致"一条都没核"时**报红**，不是安静地全绿。

用法：
    python _tools/qa/_check_core_extension_boundary.py            # 非零退出＝有对不上的
    python _tools/qa/_check_core_extension_boundary.py --list     # 只列块（不判）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import refuse_if_injecting, repo_root  # noqa: E402

ROOT = repo_root()
DOC = ROOT / "docs/R4_CORE_EXTENSION_MAP.md"
DOMAINS_DOC = ROOT / "docs/DOMAIN_BOUNDARIES.md"
APP = ROOT / "backend" / "app"
MODELS = APP / "models"
MAIN = APP / "main.py"

FENCE = chr(96) * 3
Q = chr(39)          # 单引号：Python 源码里两种引号都可能出现，用拼接避免转义地狱
DQ = chr(34)
QUOTES = "[" + DQ + Q + "]"

CLASSES = {"CORE", "EXTENSION_POINT", "EXTENSION_IMPL", "INFRASTRUCTURE"}
FIELDS = ("id", "中文名", "class", "domain", "owns", "contract", "why", "impl", "pending")

MIN_BLOCKS = 45
MIN_TABLES = 45
MIN_EVENTS = 15
MIN_WHY = 20
MIN_REASON = 20
MIN_CHECKED_IMPL = 20
#: 不许用 pending 躲判定（指南 §32：真正模糊的才留 pending）。
MAX_PENDING = 8
#: §31 坑 13：同一契约不许留 10 代接口。
MAX_CONTRACT_MAJORS = 3
#: §28：事件消费者只许调这些模块（推送 / 站内信投递）。
DELIVER_ALLOWLIST = ("push_events", "message_center")

BLOCK_RE = re.compile("^" + FENCE + "capability\n(.*?)^" + FENCE + "$", re.S | re.M)
DOMAIN_BLOCK_RE = re.compile("^" + FENCE + "domain\n(.*?)^" + FENCE + "$", re.S | re.M)
TABLENAME_RE = re.compile("__tablename__\\s*=\\s*" + QUOTES + "([^" + DQ + Q + "]+)" + QUOTES)
ENQUEUE_RE = re.compile("outbox\\.enqueue\\(\\s*[^,]+,\\s*" + QUOTES
                        + "([a-z_]+\\.[a-z_]+)" + QUOTES)
CONTRACT_RE = re.compile("^([A-Za-z][A-Za-z0-9_]*(?:\\s+[A-Za-z][A-Za-z0-9_]*)*?)\\s+v(\\d+)$")
EVENT_BRANCH_RE = re.compile('event\\.event_type\\s*==\\s*' + DQ + '([^' + DQ + ']+)' + DQ)
CALL_RE = re.compile("await\\s+([A-Za-z_]\\w*)\\.([A-Za-z_]\\w*)\\(")


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print("  [OK]   " + label)
        else:
            self.fails.append(label + (" —— " + detail if detail else ""))
            print("  [FAIL] " + label + (" —— " + detail if detail else ""))


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit("找不到文件：" + str(p) + "（被改名/搬走了？这条判据要跟着改）")
    return p.read_text(encoding="utf-8", errors="replace")


def parse_blocks(text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in BLOCK_RE.finditer(text):
        item: dict[str, str] = {}
        for line in m.group(1).splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            if k.strip():
                item[k.strip()] = v.strip()
        if item.get("id"):
            out.append(item)
    return out


def domain_names() -> set[str]:
    """DOMAIN_BOUNDARIES.md 里声明的 15 个域名（**自己算**，不从边界图抄）。"""
    text = read(DOMAINS_DOC)
    names: set[str] = set()
    for m in DOMAIN_BLOCK_RE.finditer(text):
        for line in m.group(1).splitlines():
            if line.startswith("name:"):
                names.add(line.split(":", 1)[1].strip())
    return names


def model_tables() -> set[str]:
    names: set[str] = set()
    for f in sorted(MODELS.rglob("*.py")):
        names.update(TABLENAME_RE.findall(f.read_text(encoding="utf-8", errors="replace")))
    return names


def code_events() -> set[str]:
    types: set[str] = set()
    for f in sorted(APP.rglob("*.py")):
        types.update(ENQUEUE_RE.findall(f.read_text(encoding="utf-8", errors="replace")))
    return types


def doc_events(text: str) -> list[tuple[str, str]]:
    marker = "### 5.2 事件清单"
    if marker not in text:
        return []
    # ⚠️ 必须在**整行**的 --- 处截断：表格自己的分隔行（| --- | --- |）也含 ---，
    #    按子串切会在第一行分隔行就把表切没了（第一版就是这么写的，事件一条都解析不出来）。
    sec = re.split("\\n---\\s*\\n", text.split(marker, 1)[1], maxsplit=1)[0]
    rows: list[tuple[str, str]] = []
    for ln in sec.splitlines():
        s = ln.strip()
        if not s.startswith("|") or set(s) <= set("|- "):
            continue
        cells = [x.strip() for x in s.strip("|").split("|")]
        if len(cells) < 5 or cells[0].startswith("事件类型"):
            continue
        rows.append((cells[0].strip(chr(96)), cells[-1]))
    return rows


def split_entries(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip() and x.strip() != "-"]


def locate_impl(entry: str) -> str:
    e = entry.strip().strip(chr(96))
    if not e or e == "-":
        return ""
    path, _, sym = e.partition("::")
    path = path.strip()
    for base in (APP, ROOT):
        p = base / path
        if not p.exists():
            continue
        if sym:
            body = p.read_text(encoding="utf-8", errors="replace")
            if not re.search("^\\s*(async\\s+)?def\\s+" + re.escape(sym.strip()) + "\\b",
                             body, re.M):
                return e + "（文件在，但没有 def " + sym.strip() + "）"
        return ""
    return e + " 不存在"


def deliver_body() -> str:
    text = read(MAIN)
    m = re.search("^async def _outbox_deliver\\b", text, re.M)
    if not m:
        return ""
    rest = text[m.start():]
    nxt = re.search("^(async )?def ", rest[1:], re.M)
    return rest[: nxt.start() + 1] if nxt else rest


def main() -> int:
    argv = sys.argv[1:]
    if refuse_if_injecting("核心/扩展边界检查"):
        return 1
    text = read(DOC)
    blocks = parse_blocks(text)
    if "--list" in argv:
        for b in blocks:
            print(b["id"] + "  " + b.get("class", "?") + "  " + b.get("owns", "-"))
        return 0

    c = Checker()
    print("== 1. 文档形状 ==")
    c.ok("边界图有 " + str(len(blocks)) + " 条能力（≥" + str(MIN_BLOCKS) + "）",
         len(blocks) >= MIN_BLOCKS, "块数低于下限 —— 图被掏空了？")
    ids = [b.get("id", "") for b in blocks]
    c.ok("id 唯一且非空", len(ids) == len(set(ids)) and all(ids),
         "重复或缺失：" + str([i for i in ids if ids.count(i) > 1][:3]))
    bad_cls = [b["id"] for b in blocks if b.get("class") not in CLASSES]
    c.ok("class 只能是四档之一", not bad_cls, str(bad_cls[:3]))
    missing = [b.get("id", "?") for b in blocks if any(f not in b for f in FIELDS)]
    c.ok("九个字段齐全", not missing, "缺字段：" + str(missing[:3]))
    short = [b["id"] for b in blocks if len(b.get("why", "")) < MIN_WHY]
    c.ok("每条 why ≥ " + str(MIN_WHY) + " 字", not short, "太短：" + str(short[:3]))
    bad_pending = [b["id"] for b in blocks if b.get("pending") not in ("yes", "no")]
    c.ok("pending 只能是 yes/no", not bad_pending, str(bad_pending[:3]))
    pend = [b for b in blocks if b.get("pending") == "yes"]
    c.ok("pending 的条数 ≤ " + str(MAX_PENDING) + "（不许用 pending 躲判定）",
         len(pend) <= MAX_PENDING, "有 " + str(len(pend)) + " 条")
    for b in pend:
        c.ok("pending=" + b["id"] + " 写了 pending_reason（≥" + str(MIN_REASON) + " 字）",
             len(b.get("pending_reason", "")) >= MIN_REASON, "没写或太短")
    no_contract = [b["id"] for b in blocks
                   if b.get("class") == "EXTENSION_POINT" and b.get("contract", "-") in ("", "-")]
    c.ok("每个 EXTENSION_POINT 都写了 contract（铁律 4：没有契约的扩展点只是愿望）",
         not no_contract, str(no_contract[:3]))

    print()
    print("== 2. Unclassified = 0：每张表恰好一个归属 ==")
    tables = model_tables()
    claimed: dict[str, list[str]] = {}
    for b in blocks:
        for t in split_entries(b.get("owns", "-")):
            claimed.setdefault(t, []).append(b["id"])
    orphans = sorted(tables - set(claimed))
    ghosts = sorted(set(claimed) - tables)
    multi = {t: v for t, v in claimed.items() if len(v) > 1}
    c.ok("模型里的 " + str(len(tables)) + " 张表都在图上（≥" + str(MIN_TABLES) + "）",
         len(tables) >= MIN_TABLES and not orphans, "没有归属：" + str(orphans[:5]))
    c.ok("图上没有不存在的表名（防化石）", not ghosts, "幽灵表：" + str(ghosts[:5]))
    c.ok("没有一张表有两个归属", not multi, "多头：" + str(list(multi)[:3]))

    print()
    print("== 2b. 域覆盖：15 个域都被定过档（命令按域归属，域被定档 = 命令被定档）==")
    doms = domain_names()
    used = {b.get("domain", "-").strip() for b in blocks} - {"-", ""}
    c.ok("DOMAIN_BOUNDARIES 的 " + str(len(doms)) + " 个域都解析出来了", len(doms) >= 15,
         "只解析到 " + str(len(doms)) + " 个 —— 那份文档的结构变了？")
    c.ok("每个域在边界图上都至少有一条能力", not (doms - used),
         "没被定档的域：" + str(sorted(doms - used)[:5]))
    c.ok("边界图上的域名都是真的（防编造）", not (used - doms),
         "不存在的域：" + str(sorted(used - doms)[:5]))

    print()
    print("== 3. 事件（指南 §28：Event 是事实通知，不是隐藏调用）==")
    ev_code = code_events()
    rows = doc_events(text)
    ev_doc = {r[0] for r in rows}
    c.ok("代码里的事件类型有 " + str(len(ev_code)) + " 个（≥" + str(MIN_EVENTS) + "）",
         len(ev_code) >= MIN_EVENTS, "扫不到事件 —— 入队写法变了？")
    c.ok("代码产生的事件全部在 §5.2 登记", not (ev_code - ev_doc),
         "没人认领：" + str(sorted(ev_code - ev_doc)[:5]))
    c.ok("§5.2 登记的事件全部真的在产生", not (ev_doc - ev_code),
         "化石：" + str(sorted(ev_doc - ev_code)[:5]))
    not_fact = [r[0] for r in rows if not r[1].startswith("❌")]
    c.ok("§5.2 最后一列**全是 ❌**（核心事实不依赖事件消费者）", not not_fact,
         "这些事件其实在承担业务：" + str(not_fact[:5]))

    print()
    print("== 4. Event 不是隐藏调用：发件箱派发表只许调推送 / 消息 ==")
    body = deliver_body()
    c.ok("找得到 main.py::_outbox_deliver（否则这一组在空转）", bool(body))
    calls = CALL_RE.findall(body)
    mods = sorted({m for m, _ in calls})
    bad_mods = [m for m in mods if m not in DELIVER_ALLOWLIST]
    c.ok("派发表里的模块全在白名单内（" + "、".join(DELIVER_ALLOWLIST) + "）", not bad_mods,
         "事件消费者调到了业务服务：" + str(bad_mods) + " —— 这就是「事件变成隐形 RPC」")
    branches = set(EVENT_BRANCH_RE.findall(body))
    c.ok("派发表覆盖了全部事件类型", branches == ev_code,
         "缺处理器的：" + str(sorted(ev_code - branches)[:5]))
    handler_names = sorted({f for _, f in CALL_RE.findall(body)})
    c.ok("派发表里的处理器都带 push_ / emit_ 前缀（推送口径一处实现）",
         all(n.startswith(("push_", "emit_")) for n in handler_names),
         "不合口径：" + str([n for n in handler_names if not n.startswith(("push_", "emit_"))][:3]))
    print("  派发表调用 " + str(len(calls)) + " 处，涉及模块：" + "、".join(mods))

    print()
    print("== 5. impl 实现站点真实存在（防化石）==")
    checked = 0
    broken: list[str] = []
    for b in blocks:
        for entry in split_entries(b.get("impl", "-")):
            checked += 1
            why = locate_impl(entry)
            if why:
                broken.append(b["id"] + " → " + why)
    c.ok("核对过 " + str(checked) + " 个实现站点（≥" + str(MIN_CHECKED_IMPL) + "）",
         checked >= MIN_CHECKED_IMPL, "一个都没核到 —— 这一组在空转")
    c.ok("声明的实现站点全部存在", not broken, str(broken[:3]))

    print()
    print("== 6. 契约版本上限（§31 坑 13：不许留 10 代接口）==")
    versions: dict[str, set[str]] = {}
    for b in blocks:
        m = CONTRACT_RE.match(b.get("contract", "-").strip())
        if m:
            versions.setdefault(m.group(1), set()).add(m.group(2))
    fat = {k: sorted(v) for k, v in versions.items() if len(v) > MAX_CONTRACT_MAJORS}
    c.ok("每个契约的版本数 ≤ " + str(MAX_CONTRACT_MAJORS), not fat, str(fat))
    c.ok("图里至少声明了一个带版本号的契约（否则这一组在空转）",
         bool(versions), "一个契约版本都没写")
    if versions:
        print("  契约：" + "；".join(k + " v" + "/v".join(sorted(v))
                                    for k, v in sorted(versions.items())))

    print()
    print("== 7. 静默空转保护 ==")
    c.ok("块数 / 表数 / 事件数 / impl 数四项下限都达标",
         len(blocks) >= MIN_BLOCKS and len(tables) >= MIN_TABLES
         and len(ev_code) >= MIN_EVENTS and checked >= MIN_CHECKED_IMPL)

    print()
    print("=" * 60)
    if c.fails:
        print("❌ " + str(len(c.fails)) + " 项不通过：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print("✅ 全部 " + str(c.passes) + " 项通过：Unclassified = 0（" + str(len(tables))
          + " 张表各一个归属）、" + str(len(ev_code)) + " 个事件全是事实通知、"
          + str(checked) + " 个实现站点真实存在。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
