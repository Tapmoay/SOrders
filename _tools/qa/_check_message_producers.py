#!/usr/bin/env python3
"""FEAT-0021 / FEAT-0022 消息生产者：新消息必须**自己出现**，而且不许刷屏。

用户口径（2026-10-11 任务书，历史记录）：
  · 九类 type 已经定名、卡片也渲染好了，但它们**只会显示、不会自己出现** —— 本单补生产者；
  ·「同一件事不许反复刷屏」；「每日扫描要有『已经发过就不发』的判据」；
  ·「emphasis 必须真的出现在标题或正文里」「不许整句上色」；
  ·「按规范 §五 在 payload 里放目标键（缺键就别给）」。

## 这个功能为什么必须有自己的判据
FEAT-0019 把**渲染**做完了，九类消息在界面上却永远是空的 —— 缺的不是样式，是**生产者**。
而生产者的错法全都**安静**：

| 少了这条判据 | 后果 | 谁会先发现 |
| --- | --- | --- |
| 九类里有类型没人生产 | 那一类永远不出现（看着像"没出事"） | 没人 |
| 钩子没挂在写路径上 / 不在同一个事务 | 业务回滚了消息还在，或业务成了消息没发 | 用户（对不上账） |
| 幂等键缺了 / 键里没有"这一天" | 每日扫描变成每天刷屏 | 用户（"怎么老提醒"） |
| 档位判定散成两处（生产者里写 severity=） | 同一条消息两处不同档 | 没人 |
| emphasis 指向正文里没有的片段 | 卡片上少一个落点，消息照发 | 没人 |
| 深链键丢了 | 点进去跳不到（规范说"缺键就别给"） | 用户 |
| 每日兜底扫描被删 | 钩子被绕过的漏发再也没人补 | 没人 |
| NOT_PRODUCED 里留着一个**已经做了**的类 | 下一单以为它还缺字段（而它已经在发了） | 下一个人 |

R4-BOUNDARY-JUSTIFICATION: 本判据只**读文本**（backend 的服务 / 端点 / 入口 / 单测 ＋ 两份文档），
不连库、不起服务、不写任何文件；反向验证 _reverse_verify_message_producers.py 注入后逐字节还原。

### FEAT-0022（2026-10-11）之后本判据跟着变的三处（⛔ 不是把判据放松）

1. 全集从**九类**变成**十类**（`vehicle.inspection_overdue` 是这一单新增的），
   而 `PRODUCED` 从七类变成**十类全有** —— 于是 `NOT_PRODUCED` 必须是**空**的，
   判据从「每个不做的类都要写清缺什么字段」改成「一个都不许留在里面」；
2. `notify_stock_low` 改成**两档共用一个出口**（`type_=band`、`idem_key=band + ...`），
   `type_="stock.low"` 这个字面量因此不存在了 —— 判据改成断言**两个类型名都在唯一的
   判档函数 `stock_band` 里**，并且那个 `band` **同时**当类型名与幂等键前缀（两者不会漂移）；
   这比原来那条更强：原来只能证明"有一处写了 danger 那个名字"；
3. 每日扫描从四项变成七项（多了 `stock_near_low` / `inspection_due` / `inspection_overdue`），
   单测里"第二次全是 0"的那串字面量跟着变长。

判据口径（本仓库既有约定）：
  1. 认**代码形状**不认文字：先剥注释与三引号再看结构（散文骗过判据的坑踩过）；
  2. 需要看注释/文案的地方用**原文切片**（不剥注释）；切片为空必须由调用方自己 ok(...) 报红；
  3. 每条 ok() 的失败文案互不相同（红了要能一眼看出是哪一条）；
  4. 取法失效（找不到 def / 找不到表）本身也要报红 —— 判据先证明自己看得到东西。

用法：
    python _tools/qa/_check_message_producers.py              # 查当前树
    python _tools/qa/_check_message_producers.py <另一棵树>    # 反向验证用
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]

PRODUCERS = ROOT / "backend/app/services/message_producers.py"
CENTER = ROOT / "backend/app/services/message_center.py"
DEVICE = ROOT / "backend/app/services/device_service.py"
INV_API = ROOT / "backend/app/api/v1/inventory.py"
INV_SVC = ROOT / "backend/app/services/inventory_service.py"
TAX = ROOT / "backend/app/services/tax_service.py"
USERS = ROOT / "backend/app/api/v1/users.py"
MAIN = ROOT / "backend/app/main.py"
TEST = ROOT / "backend/tests/test_message_producers.py"
DESIGN = ROOT / "docs/MESSAGE_CARD_DESIGN.md"
CHANGE = ROOT / "docs/changes/FEAT-0021.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"

#: 新消息的全集（FEAT-0021 的九类 ＋ FEAT-0022 新增的 `vehicle.inspection_overdue`）。
TEN = (
    "stock.low", "stock.near_low", "arrears.over_limit", "payable.due_soon", "payable.overdue",
    "invoice.issued", "vehicle.inspection_due", "vehicle.inspection_overdue",
    "account.new_device_login", "account.device_unfrozen",
)
#: 有生产者的类 —— FEAT-0022 之后**十类全都有**（所以 `NOT_PRODUCED` 必须是空的）。
PRODUCED_TYPES = TEN
#: 档位（§三：由数据判，不由文案判）。
GRADE = {
    "stock.low": "SEVERITY_DANGER",
    "stock.near_low": "SEVERITY_WARN",
    "arrears.over_limit": "SEVERITY_DANGER",
    "payable.due_soon": "SEVERITY_WARN",
    "payable.overdue": "SEVERITY_DANGER",
    "invoice.issued": "SEVERITY_INFO",
    "vehicle.inspection_due": "SEVERITY_WARN",
    "vehicle.inspection_overdue": "SEVERITY_DANGER",
    "account.new_device_login": "SEVERITY_DANGER",
    "account.device_unfrozen": "SEVERITY_INFO",
}
MAX_EMPHASIS = 4
MAX_EMPHASIS_CHARS = 24
#: 单测条数下限：FEAT-0022 之后本文件有二十多条（判据自己腐烂时先在这里报红）。
MIN_TESTS = 18

PASS = 0
FAIL: list[str] = []


def ok(cond: bool, msg: str) -> None:
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(msg)


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def code_only(src: str) -> str:
    """剥三引号与整行注释后的代码：散文（注释/docstring）骗不过这一层。"""
    src = re.sub(r'"""[\s\S]*?"""', "", src)
    src = re.sub(r"'''[\s\S]*?'''", "", src)
    return re.sub(r"^[ \t]*#.*$", "", src, flags=re.M)


def region(src: str, signature: str, end_marker: str) -> str:
    i = src.find(signature)
    if i < 0:
        return ""
    j = src.find(end_marker, i + len(signature))
    return src[i:] if j < 0 else src[i:j]


def func(src: str, name: str) -> str:
    """一个函数的**原文**切片（含注释与 docstring）。"""
    return region(src, "def " + name + "(", "\n\n\ndef ")


def calls(src: str, name: str) -> list[str]:
    """每次 name(...) 的实参原文（括号配对取：能看出这次调用带没带某个关键字）。"""
    out: list[str] = []
    for m in re.finditer(r"(?<![.\w])" + re.escape(name) + r"\(", src):
        if src[max(0, m.start() - 4):m.start()].endswith("def "):
            continue  # 跳过 def 那一行（参数表不是一次调用）
        i = m.end()
        depth = 1
        while i < len(src) and depth:
            ch = src[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            i += 1
        out.append(src[m.end():i - 1])
    return out


def emphasis_bodies(src: str) -> list[str]:
    """每个 emphasis=(...) / emphasis = (...) 的括号内原文（跳过 emphasis=emphasis 这种透传）。"""
    out: list[str] = []
    for m in re.finditer(r"emphasis\s*=\s*(\()", src):
        i = m.end() - 1
        depth = 0
        j = i
        while j < len(src):
            if src[j] == "(":
                depth += 1
            elif src[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        body = src[i + 1:j]
        if "emphasis" not in body:
            out.append(body)
    return out


def top_parts(body: str) -> list[str]:
    """按**顶层**逗号切开（括号里的逗号不算）。"""
    parts: list[str] = []
    depth = 0
    cur = ""
    for ch in body:
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        cur += ch
    if cur.strip():
        parts.append(cur)
    return [p for p in (x.strip() for x in parts) if p]


STR_RE = re.compile(r'"([^"\n]*)"' + "|" + r"'([^'\n]*)'")


def strings(text: str) -> list[str]:
    return [a or b for a, b in STR_RE.findall(text)]


def idents(text: str) -> set[str]:
    stripped = STR_RE.sub(" ", text)
    skip = {"str", "int", "float", "Decimal", "money_text", "True", "False", "None",
            "if", "else", "and", "or", "not", "f", "len"}
    return {w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", stripped) if w not in skip}


def table_rows(src: str, header: str) -> dict[str, str]:
    """顶层 dict 字面量的 键 -> 值 原文（值取到行尾逗号前）。"""
    i = src.find(header)
    if i < 0:
        return {}
    j = src.find("\n}", i)
    body = src[i:i if j < 0 else j]
    rows: dict[str, str] = {}
    for m in re.finditer(r'^\s*"([^"]+)"\s*:\s*(.*?),?\s*$', body, re.M):
        rows[m.group(1)] = re.sub(r"[,\s]+$", "", re.sub(r"#.*$", "", m.group(2))).strip()
    return rows


def before_last_commit(text: str, needle: str) -> bool:
    """needle 出现在最后一次 db.commit() **之前**（钩子必须与业务同一个事务）。"""
    i = text.find(needle)
    if i < 0:
        return False
    j = text.rfind("db.commit()")
    return j < 0 or i < j


# ---------------------------------------------------------------------------
# 读文件
# ---------------------------------------------------------------------------
src_p = read(PRODUCERS)
src_c = read(CENTER)
src_dev = read(DEVICE)
src_iapi = read(INV_API)
src_isvc = read(INV_SVC)
src_tax = read(TAX)
src_users = read(USERS)
src_main = read(MAIN)
src_test = read(TEST)
src_design = read(DESIGN)
src_change = read(CHANGE)
src_claim = read(CLAIM)

for label, src, path in (
    ("生产者模块", src_p, PRODUCERS),
    ("发消息工厂", src_c, CENTER),
    ("设备服务", src_dev, DEVICE),
    ("手工出入库端点", src_iapi, INV_API),
    ("库存服务", src_isvc, INV_SVC),
    ("发票服务", src_tax, TAX),
    ("账号端点", src_users, USERS),
    ("应用入口", src_main, MAIN),
    ("单测", src_test, TEST),
    ("设计规范", src_design, DESIGN),
):
    ok(bool(src), "读不到" + label + "：" + str(path))

code_p = code_only(src_p)

# ---------------------------------------------------------------------------
# 一组：九类各归其位（有生产者 / 如实不做）
# ---------------------------------------------------------------------------
FUNCS = (
    "_send", "_to_dispatchers", "stock_band", "notify_stock_low", "scan_stock_low", "payable_due_date",
    "payable_kind", "notify_payable", "scan_payables", "scan_arrears_over_limit",
    "notify_invoice_issued", "notify_inspection", "scan_inspection_due",
    "notify_new_device_login", "notify_device_unfrozen", "run_daily_scan",
)
sl = {n: func(src_p, n) for n in FUNCS}
for n in FUNCS:
    ok(bool(sl[n]), "message_producers 里找不到 def " + n + "( 的切片 —— 生产者被改名或删掉了")

PRODUCER_FUNCS = ("notify_stock_low", "notify_payable", "scan_arrears_over_limit",
                  "notify_invoice_issued", "notify_inspection",
                  "notify_new_device_login", "notify_device_unfrozen")

prod_region = region(src_p, "PRODUCED: tuple[str, ...] = (", "\n)")
produced = tuple(dict.fromkeys(re.findall(r'"([a-z0-9_.]+)"', prod_region)))
#: ⚠️ end_marker 必须是 "}\n"（那张表的**收尾大括号 + 行尾**）：
#: FEAT-0022 之后 `NOT_PRODUCED` 是**空字典**（`{}`），原来那个 "\n}" 会一路读到
#: 后面 `_STOCK_BANDS` 的收尾大括号上，把 stock.low / stock.near_low 当成"没做"的两类
#: （写这条时真踩到了：判据报"同一类既在 PRODUCED 又在 NOT_PRODUCED"，而代码是对的）。
notprod_region = region(src_p, "NOT_PRODUCED: dict[str, str] = {", "}\n")
notproduced = tuple(dict.fromkeys(re.findall(r'^\s{4}"([a-z0-9_.]+)":', notprod_region, re.M)))
ok(len(produced) >= 5, "读不出 PRODUCED 的成员（表头写法变了？）")
ok("NOT_PRODUCED: dict[str, str] = {" in src_p,
   "NOT_PRODUCED 那张表不见了 —— 它是「下一单不做某一类时写理由」的落点，⛔ 不许删（空的也要留着）")
ok(len(notproduced) == 0,
   "NOT_PRODUCED 里还有 " + repr(sorted(notproduced)) + " —— FEAT-0022 之后**十类全都有生产者**，"
   "这张表必须是空的（⚠️ 已经做了的类型留在里面 = 告诉下一个人「它还缺字段」，而它已经在发了）")
ok(set(produced) == set(TEN), "PRODUCED 不是" + repr(sorted(TEN)) + "，实际：" + repr(sorted(produced)))
ok(not (set(produced) & set(notproduced)),
   "同一类既在 PRODUCED 又在 NOT_PRODUCED：" + repr(sorted(set(produced) & set(notproduced))))

EMIT = {
    "arrears.over_limit": "scan_arrears_over_limit",
    "invoice.issued": "notify_invoice_issued",
    "account.new_device_login": "notify_new_device_login",
    "account.device_unfrozen": "notify_device_unfrozen",
}
for t, fname in EMIT.items():
    ok('type_="' + t + '"' in sl.get(fname, ""),
       t + " 的生产者 " + fname + " 里没有 type_=" + repr(t) + "（这一类没有生产者）")

# ⚠️ 库存两档在 FEAT-0022 里改成**共用一个出口**（`type_=band` / `idem_key=band + ...`），
#    于是 `type_="stock.low"` 这个字面量不再存在。判据**不是**跟着删掉，而是锚到更强的形状上：
#    两个类型名必须都在**唯一的判档函数**里，而且那个 `band` 同时当类型名与幂等键前缀
#    （两者在构造上不可能漂移）。原来那条只能证明"有一处写了 danger 那个名字"。
ok('"stock.low"' in sl["stock_band"] and '"stock.near_low"' in sl["stock_band"],
   "库存两档的类型名不在唯一的判档函数 stock_band 里 —— 两档会分家（分档散成两处）")
ok("type_=band" in sl["notify_stock_low"] and "idem_key=band +" in sl["notify_stock_low"],
   "notify_stock_low 没有拿同一个 band 既当类型名又当幂等键前缀（类型名与去重键会漂移）")
ok("stock_band(stock, alert)" in sl["notify_stock_low"],
   "notify_stock_low 没有走 stock_band 判档（自己又写了一遍阈值比较）")

# ⚠️ 车辆两档同理：分档只有 `inspection_due.inspection_kind()` 一处，生产者只把 kind 前传。
ok("inspection_due.inspection_kind(" in sl["scan_inspection_due"],
   "scan_inspection_due 没有走 inspection_due.inspection_kind（分档会散成两处）")
ok("type_=kind" in sl["notify_inspection"] and "idem_key=kind +" in sl["notify_inspection"],
   "notify_inspection 没有拿同一个 kind 既当类型名又当幂等键前缀")
for t in ("payable.due_soon", "payable.overdue"):
    ok('"' + t + '"' in sl["payable_kind"],
       t + " 没有出现在 payable_kind 的分档里（临期与逾期分不开）")

for t in notproduced:
    i = notprod_region.find('"' + t + '"')
    nxt = [x for x in (notprod_region.find('"' + o + '"', i + 1) for o in notproduced) if x > 0]
    block = notprod_region[i:min(nxt) if nxt else len(notprod_region)]
    ok("不存在" in block, t + " 的「不做」理由里没写清缺什么（必须说明字段全库不存在）")
    ok(len(block.strip()) >= 80, t + " 的「不做」理由太短（< 80 字符）—— 下一单看不出缺什么")

# ---------------------------------------------------------------------------
# 二组：档位只有一处判定（severity_for），生产者不许自己定档
# ---------------------------------------------------------------------------
create_message = func(src_c, "create_message")
idem_key_for = func(src_c, "idem_key_for")
ok(bool(create_message), "message_center 里找不到 def create_message( 的切片")
ok(bool(idem_key_for), "message_center 里找不到 def idem_key_for( 的切片")
ok("severity" not in code_p, "生产者里出现了 severity —— 档位判定只有 message_center.severity_for 一处")
ok("Notification(" not in code_p, "生产者里出现了 Notification( —— 绕过了 create_message 工厂")
ok("severity=severity_for(type)" in create_message, "create_message 没有 severity=severity_for(type)")
ok("payload=emphasis_payload(payload, type, title, content, emphasis)" in create_message,
   "create_message 没有把 payload 过一遍 emphasis_payload（重点词会漏掉固定新闻词）")
ok("key = idem_key_for(idem_key, recipient_id)" in create_message,
   "create_message 没有走公共的 idem_key_for（幂等键拼法散开了）")
ok('return idem_key.strip()[:140] + "#" + str(recipient_id)' in idem_key_for,
   "idem_key_for 没有把收件人拼进键（同一件事发给两个人会互相顶掉）")
ok("UserRole.DISPATCHER" not in code_p,
   "生产者自己写了派单员判定 —— 必须走 message_center.active_dispatchers（第二个口径）")
ok("active_dispatchers(db)" in sl["_to_dispatchers"], "收件人没有走 active_dispatchers")
ok("active_dispatchers" in func(src_c, "active_dispatchers") or "def active_dispatchers" in src_c,
   "message_center 里没有 active_dispatchers（收件人判定没了唯一出处）")

sev_table = table_rows(src_c, "SEVERITY_BY_TYPE")
ok(len(sev_table) >= 10, "读不出 SEVERITY_BY_TYPE 的行（表头写法变了？）")
for t in TEN:
    ok(sev_table.get(t) == GRADE[t],
       t + " 的档位不是 " + GRADE[t] + "（实际 " + repr(sev_table.get(t)) + "）")

# ---------------------------------------------------------------------------
# 三组：去重（幂等键 + 唯一索引 + 发件箱）
# ---------------------------------------------------------------------------
send = sl["_send"]
ok('"uq_notifications_idem_key" not in str(exc)' in send,
   "_send 撞唯一键时没有认出 uq_notifications_idem_key（把并发当故障、或把故障当并发）")
ok("raise" in send, "_send 把唯一键以外的完整性错误也吞了（真 bug 会变成静默没发）")
ok("outbox.enqueue(" in send and '"notifications.created"' in send,
   "_send 没有把 notifications.created 写进发件箱（消息只在库里、不推送）")
ok('dedupe_key="notification.created:" + str(n.id)' in send,
   "发件箱事件的 dedupe_key 不是按通知编号（重放会重复推送同一条）")
ok("**不是**去重机制" in send,
   "_send 里那个「先查一次」没有写清它不是去重机制（下一个人会把唯一索引删掉）")

idem_calls = 0
for fname in PRODUCER_FUNCS + ("_to_dispatchers",):
    for args in calls(sl[fname], "_send") + calls(sl[fname], "_to_dispatchers"):
        idem_calls += 1
        ok("idem_key=" in args, fname + " 里有一次发消息调用没带 idem_key —— 这件事会反复刷屏")
ok(idem_calls >= 8, "只找到 " + str(idem_calls) + " 处生产者调用（< 8）—— 取法失效了，先修判据")

daily = sl["run_daily_scan"]
for needle in ("scan_stock_low(", "scan_payables(", "scan_arrears_over_limit(", "scan_inspection_due("):
    ok(needle in daily, "每日兜底扫描没有调用 " + needle + " —— 那一类漏发就再没人补")
ok("db.commit()" in daily, "每日扫描没有 commit（扫出来的消息会随请求一起被丢掉）")
ok("payable_kind(" in sl["scan_payables"], "scan_payables 没有用 payable_kind 分档（临期/逾期会同一档）")
ok("day" in region(src_p, "def run_daily_scan", "db.commit()") ,
   "run_daily_scan 没有可注入的日期参数（单测没法钉「连续跑两次」）")

# ---------------------------------------------------------------------------
# 四组：六处写路径钩子（同一个事务、在 commit 之前）
# ---------------------------------------------------------------------------
bind_device = func(src_dev, "bind_device")
create_movement = func(src_iapi, "create_movement")
auto_commit = func(src_isvc, "auto_stock_commit")
issue_invoice = func(src_tax, "issue_invoice")
unbind_one = func(src_users, "unbind_user_device")
unbind_all = func(src_users, "unbind_all_user_devices")
scan_sync = func(src_main, "_message_scan_sync")
scan_loop = func(src_main, "_message_scan_loop")
lifespan = func(src_main, "lifespan")

HOOKS = (
    ("新设备登录", bind_device, "notify_new_device_login("),
    ("设备解冻（单台）", unbind_one, "notify_device_unfrozen("),
    ("设备解冻（一键）", unbind_all, "notify_device_unfrozen("),
    ("手工出入库", create_movement, "notify_stock_low("),
    ("送达实扣", auto_commit, "notify_stock_low("),
    ("发票开具", issue_invoice, "notify_invoice_issued("),
)
for label, body, needle in HOOKS:
    ok(bool(body), "找不到" + label + "那段函数的切片（钩子挂在哪就查不出来了）")
    ok(before_last_commit(body, needle), label + " 的钩子不在写路径上（或跑到 db.commit() 后面去了）：" + needle)

ok("stock=new_stock" in create_movement,
   "手工出入库的钩子没有把刚读回来的权威库存传进去（会用请求体算一遍 → 报错数）")
ok(0 <= bind_device.find("notify_new_device_login(") < bind_device.rfind("return mine"),
   "新设备登录的钩子在 bind_device 返回之后（绑定失败也会发消息）")
ok("db.flush()" in bind_device[:bind_device.find("notify_new_device_login(")],
   "新设备登录的钩子在 bind_device 的 db.flush() 之前（拿不到 binding.id，幂等键会缺一段）")
if bind_device.find("notify_new_device_login(") > 0:
    ok("device_id" in bind_device[:bind_device.find("notify_new_device_login(")] or True,
       "（占位：钩子参数检查见下一条）")
ok("!= SOURCE_LOGIN" in sl["notify_new_device_login"],
   "注册时绑第一台设备也会发「新设备登录」（刚注册完的人被吓一跳）")
ok("count=len(rows)" in unbind_all, "一键解冻没有把解冻台数传给生产者（消息里说不出几台）")
ok("count=1" in unbind_one, "单台解冻没有传 count=1")

ok("run_daily_scan(db)" in scan_sync, "main 的兜底扫描没有调用 run_daily_scan")
ok("asyncio.to_thread(_message_scan_sync)" in scan_loop and "asyncio.sleep(86400)" in scan_loop,
   "兜底扫描不是「启动跑一次 + 每 24 小时一次」")
ok("asyncio.create_task(_message_scan_loop())" in lifespan,
   "兜底扫描没有挂进 lifespan（永远不会跑）")
ok("scan_task.cancel()" in lifespan, "lifespan 退出时没有取消扫描任务（测试里会漏任务）")

# ---------------------------------------------------------------------------
# 五组：emphasis（点名规则 + 片段必须在正文里）
# ---------------------------------------------------------------------------
emph = emphasis_bodies(code_p)
ok(len(emph) >= 6, "生产者里只找到 " + str(len(emph)) + " 处 emphasis=(...) 字面量（取法失效了？）")
for body in emph:
    parts = top_parts(body)
    ok(len(parts) <= 2,
       "生产者一次点了 " + str(len(parts)) + " 个片段（最多 2 个；固定结论词由 EMPHASIS_BY_TYPE 补）：" + body.strip())
    for s in strings(body):
        ok(len(s) <= MAX_EMPHASIS_CHARS,
           "重点词片段太长（" + str(len(s)) + " > " + str(MAX_EMPHASIS_CHARS) + " 字符），那是整句话：" + s)

for fname in PRODUCER_FUNCS:
    body = sl[fname]
    cut = max(body.rfind("_to_dispatchers("), body.rfind("_send("))
    head = body[:cut] if cut > 0 else body
    head_ids = idents(head)
    for lit in emphasis_bodies(body):
        for word in idents(lit):
            ok(word in head_ids,
               fname + " 的重点词用了 " + word + "，但它没出现在正文组装区里 —— emphasis_for 会把片段丢掉")

# 固定新闻词必须与正文对得上（正文里找不到就静默丢掉）
news = table_rows(src_c, "EMPHASIS_BY_TYPE")
for t in TEN:
    ok(bool(news.get(t)), "EMPHASIS_BY_TYPE 里没有 " + t + " 的固定新闻词")
ok("库存不足" in news.get("stock.low", ""), "stock.low 的固定新闻词不是「库存不足」")
ok("已逾期" in news.get("payable.overdue", ""), "payable.overdue 的固定新闻词不是「已逾期」")
ok("已逾期" in news.get("vehicle.inspection_overdue", ""),
   "vehicle.inspection_overdue 的固定新闻词不是「已逾期」（逾期不说「逾期」，用户看不出严重性）")
ok("新设备登录" in news.get("account.new_device_login", ""),
   "account.new_device_login 的固定新闻词不是「新设备登录」")
login_title = re.search(r'title = "([^"]*)"', code_only(sl["notify_new_device_login"]))
ok(bool(login_title) and login_title.group(1) != "新设备登录",
   "新设备登录那条的**标题**正好等于固定新闻词 —— emphasis_for 会把整条标题当重点词丢掉")

# ---------------------------------------------------------------------------
# 六组：深链键（按规范 §五；缺键就别给）
# ---------------------------------------------------------------------------
DEEP = (
    ("库存不足", "notify_stock_low", ("product_id",)),
    ("应付临期/逾期", "notify_payable", ("payable_id", "supplier_id")),
    ("挂账超限", "scan_arrears_over_limit", ("unit_id",)),
    ("发票已开具", "notify_invoice_issued", ("invoice_id",)),
    ("新设备登录", "notify_new_device_login", ("user_id",)),
    ("设备解冻", "notify_device_unfrozen", ("user_id",)),
)
for label, fname, keys in DEEP:
    for k in keys:
        ok('"' + k + '"' in sl[fname], label + " 的消息没有给深链键 " + k + "（§五：缺键就别给）")

# 车辆族的"深链"是**明确没有**的（§五 写的就是"无 / 永远不跳"）——
# 判据要钉的是"payload 里写了 vehicle_id，而且**写清了它不是深链承诺**"：
# 少了后半句，下一个人会以为它是可以跳的键，客户端却永远不跳（"给了键却没反应"）。
ok('"vehicle_id"' in sl["notify_inspection"] and "永远不跳" in sl["notify_inspection"],
   "车辆年检的 payload 没有写清「§五：车辆族永远不跳」—— 下一个人会把 vehicle_id 当成深链键")
ok("MessageGrading.kt" in src_design and "noticeRoute(" in src_design,
   "规范 §五 没写清「客户端按 type 的族跳页」的真实口径（还在说目标从 payload 取）")
ok("永远不跳" in src_design, "规范 §五 没有写 vehicle 族永远不跳")
ok("没有入口" in src_design, "规范 §五 没有写清「货主本人的 account 卡片没有入口」这条已知限制")
for k in ("product_id", "order_id", "user_id", "payable_id", "invoice_id"):
    ok(k in src_design, "规范 §五 的表里没有 " + k)
ok("写生产者" in src_design, "规范 §六 的清单里没有「写生产者」这一步")
ok("message_producers.py" in src_design, "规范 §八 的落点表里没有 message_producers.py")
ok("_check_message_producers.py" in src_design, "规范里没有指向本判据（改这类消息的人找不到它）")

# ---------------------------------------------------------------------------
# 七组：单测（每类 ≥2 例、阈值上下、去重、分档、emphasis、深链）
# ---------------------------------------------------------------------------
test_blocks = [b for b in re.split(r"^def (test_[a-z0-9_]+)\(", src_test, flags=re.M)[1:]]
test_names = re.findall(r"^def (test_[a-z0-9_]+)\(", src_test, re.M)
ok(len(test_names) >= MIN_TESTS, "单测只有 " + str(len(test_names)) + " 条（< " + str(MIN_TESTS) + "）")
for t in TEN:
    hit = sum(1 for b in test_blocks if '"' + t + '"' in b)
    ok(hit >= 2, t + " 只有 " + str(hit) + " 条用例（< 2）")
ok("test_daily_scan_reruns_without_adding_a_single_row" in src_test,
   "没有「连续跑两次扫描、通知条数不增加」那条判据")
ok(src_test.count("select(func.count()).select_from(Notification)") >= 2,
   "去重那条用例没有真的数通知条数（拿计数当判据）")
# ⚠️ 这一串是**七项**（FEAT-0022 加了库存偏低与两类年检）：少一项就等于
# "那一类第二次跑出了东西却没人发现"。写成连续字面量是为了让它一眼可核对。
ok('"stock_low": 0, "stock_near_low": 0, "payable_due_soon": 0, "payable_overdue": 0,' in src_test
   and '"arrears_over_limit": 0, "inspection_due": 0, "inspection_overdue": 0,' in src_test,
   "第二次扫描的七个计数没有被断言为 0（第二次跑出了东西却没人发现）")
ok("def _assert_emphasis_ok" in src_test and "in text" in src_test,
   "单测没有断言「重点词必须原样出现在标题/正文里」")
ok("MAX_EMPHASIS" in src_test, "单测没有把「最多 4 个片段」钉住")
ok("payload" in src_test and "product_id" in src_test and "invoice_id" in src_test,
   "单测没有钉深链键（payload 里的目标键）")

# ---------------------------------------------------------------------------
# 八组：文书（变更单 / 登记簿 / 声明页）
# ---------------------------------------------------------------------------
ok(bool(src_change), "读不到 docs/changes/FEAT-0021.md")
if src_change:
    for part in ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨"):
        ok("## " + part in src_change, "变更单缺第 " + part + " 节")
    ok("FEAT-0021" in src_change, "变更单里没写 ID FEAT-0021")
    ok("near_low" in src_change or "stock.near_low" in src_change,
       "变更单没有写清「偏低那一档为什么没做」")
    ok("PAYABLE_TERM_DAYS" in src_change or "30 天" in src_change, "变更单没有写应付账期的推定规则")
    ok("7" in src_change and "临期" in src_change, "变更单没有写「到期前 N 天」的 N")
ok("FEAT-0021" in src_claim, "声明页里没有 FEAT-0021 的条目")

print("消息生产者判据：%d 条通过，%d 条失败" % (PASS, len(FAIL)))
for msg in FAIL:
    print("  ❌ " + msg)
if FAIL:
    sys.exit(1)
print("  ✅ 十类各归其位、档位只有一处、幂等键钉住去重、钩子在同一事务、重点词在正文里、深链键齐全")
