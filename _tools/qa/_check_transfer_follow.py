# -*- coding: utf-8 -*-
"""红线：转货之后**新开的那张单跟不跟原司机**（CHG-0043）—— 「换的是货主，不是这一趟活儿」。

## 由来（goal round 1 拿 objective 逐条对 CHG-0042 做审计）
objective 的原话是「……否则**新建一张归属目标货主、跟随同司机**的单」。CHG-0042 建出来的新单
是一条 PENDING_DISPATCH，静静躺在待派单池里，司机那边什么都没发生 —— 货在他的车上，
单却不在他手上。CHG-0043 把这一步补上：**新单直接派给源单的司机**。

## 为什么必须有一条红线盯着它
这一改把三件各自都对、凑起来会错的事串到了一起：
1. **状态跃迁**：派单是状态机的事，写入只许发生在 services/order_flow.py。图省事在命令层写一句
   target.status = DISPATCHED，界面与单测全绿，状态机却从此有了第二个入口 —— 而且是**绕过 CAS**
   的那一个（两个派单员同时按下转货，两边的行都会搬走、两边都以为派成功了）。
2. **预占**：预占是「派单那一刻」按整张单写下的净额（auto_stock_out）。行还没搬完就派，写出去的是
   搬之前的数；派早了还会与目标单随后那句 resync 各写一笔（两笔占用，总账照样平，只有按单看才发现）。
3. **通知口径**：司机那边的文案由**事件名**决定。跟上了却发 orders.edited（"订单信息有修改"），
   他会去找一张自己手上根本没有的单；跟着司机走了却发 orders.created（"新订单待派单"），
   派单员点进去只会扑空。
另有一条**会吞掉整笔账**的坑：assign_driver 在「这一单刚被别人派走」那条路上自己 db.rollback()
（order_flow.py:171-173 的 CAS 分支）。SQLAlchemy 的 Session.rollback() 回滚的是**整笔事务**，
连 with db.begin_nested() 建的那个存档点一起放掉 —— 所以**包 SAVEPOINT 是假保险**（真库探针实测：
包了照样把已搬好的行整段丢掉，函数还接着写审计与发件箱并 commit）。正确形状是「失败即整笔失败」：
派不出去就抛 CommandError，没有 commit ⇒ 源单没动、货也没搬。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界解决不了**。上面每一条都是「少一层 try / 早一行 /
换一个事件名」，类型上全合法、跑起来全成功，只有库里的结果与司机手机上的文案不同。边界那一半
已经先做了（状态写入收在 order_flow、事件名由后端定、客户端只渲染后端给的字段），
「这一处有没有绕过去」只存在于**调用点与字面量**，所以判据只能扫结构与取值。
运行时那一头交给 _tools/qa/_reverse_verify_transfer_follow.py（逐条注入破坏，改坏 → 必须红）。

## 判据（清单全部自己算；路径写错会先在「读到几个文件」那条报红）
1. 触发条件：源单在司机手上（模块级常量 DRIVER_HOLDING_STATUSES）＋ 这次是**新开**的一张 ＋
   那张新单还没有司机 —— 三个条件缺一不可（并进别人既有单时不动，那上面压着别的货）。
2. 时机与事务：行先落盘 → 源单该作废的作废 → **才**派单 → 最后才对目标单的预占对账；
   派单这一步**不拿 SAVEPOINT 兜**（兜不住），失败即整笔失败（抛 CommandError，什么都没提交）；
   只有「账号找不到 / 已不是司机 / 已停用」三种可预期情形才降级成「没跟上」继续把转货做完。
   派单之后、目标单对账之前**还要再落一次盘**：会话是 autoflush=False，派单刚写下的预占流水不落盘
   就 SUM 不到，对账会照着 want 再写一整笔（真库探针逮到的第 4 个真 bug）。
3. 状态机：命令层一句 status 都不写（派单只走 order_flow.assign_driver）。
4. 事件与审计：跟上了发 orders.assigned（不是 edited / created）；进出两行审计都带上跟随事实；
   注册表声明的事件与实现里真发的逐字一致。
5. 契约与界面：schema / 路由 / DTO / 抽屉 / 结果文案五处同名同义，跟上没跟上都要说清楚。

⚠️ 注入式反向验证（改坏 → 本脚本必须红，改回 → 绿）：
   python _tools/qa/_reverse_verify_transfer_follow.py

用法：python _tools/qa/_check_transfer_follow.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 剥 Kotlin 注释只此一份（复用兄弟红线，不抄第二份）。
from _check_pagination_wiring import strip_comments  # noqa: E402
#: 剥 Python 注释 / 文档字符串（换成等长空格、保留行号）。
from _check_single_source import code_only  # noqa: E402
#: 失败行 / 章节标题的形状只此一份（房规）：_reverse_verify_*.py 拿它认「这一条被判据抓住了」。
from _check_hints import Checker  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

CMD = BACKEND / "app/commands/order.py"
REG = BACKEND / "app/commands/registry.py"
API = BACKEND / "app/api/v1/orders_assignment.py"
SCHEMA = BACKEND / "app/schemas/order.py"
FLOW = BACKEND / "app/services/order_flow.py"
MAIN = BACKEND / "app/main.py"
MAP = ROOT / "docs/DOMAIN_BOUNDARIES.md"
SHEET = ANDROID / "ui/order/OrderTransferSheet.kt"
DTO = ANDROID / "data/remote/dto/Dtos.kt"
VM = ANDROID / "ui/order/OrderDetailViewModel.kt"
CHG = ROOT / "docs/changes/CHG-0043.md"
CHG42 = ROOT / "docs/changes/CHG-0042.md"
README = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"

#: 被点名的文件都必须在（少一个就先喊，不静默空转）。
REQUIRED = [CMD, REG, API, SCHEMA, FLOW, MAIN, MAP, SHEET, DTO, VM, CHG, CHG42, README, CLAIM]

Q = chr(34)
NL = chr(10)

#: 源单「在司机手上」的两个状态（与实现里的模块级常量逐字比）。
HOLDING = ["DISPATCHED", "ACCEPTED"]
#: 跟随这条路也不许顺手抄一格钱。
MONEY_FIELDS = ["payment_method", "arrears_unit", "collect_cash"]

C = Checker()


def ok(label: str, cond: bool, detail: str = "") -> None:
    C.ok(label, cond, detail)


def section(title: str) -> None:
    C.section(title)


def py(path: Path) -> str:
    """后端文件：注释与文档字符串已剥（保留行号，用户可见的字面量还在）。"""
    return code_only(path.read_text(encoding="utf-8")) if path.is_file() else ""


def kt(path: Path) -> str:
    """Kotlin 文件：注释已剥。"""
    return strip_comments(path.read_text(encoding="utf-8")) if path.is_file() else ""


def raw(path: Path) -> str:
    """原文（判据要看着注释 / 文档里的原话时用）。"""
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def norm(src: str) -> str:
    """空白折叠成单空格 —— 反向验证要按字面量认锚点，比较前先归一。"""
    return " ".join(src.split())


def items(text: str) -> list[str]:
    """(A, B, C) 里的名字，按原顺序取出来。"""
    return [p.strip().strip(Q) for p in text.split(",") if p.strip()]


def field(spec: str, key: str) -> str:
    """CommandSpec 里某一格的值（元组取括号里，字符串取引号里）。"""
    i = spec.find(key + "=(")
    if i >= 0:
        j = spec.find(")", i)
        return spec[i + len(key) + 2 : (j if j > 0 else len(spec))]
    i = spec.find(key + "=" + Q)
    if i >= 0:
        j = spec.find(Q, i + len(key) + 2)
        return spec[i + len(key) + 2 : (j if j > 0 else len(spec))]
    return ""


def enqueued(src: str) -> list[str]:
    """源码里真发出去的事件名（只认 outbox.enqueue 后面那个字面量），按出现顺序。

    ⚠️ 传进来的应当是 norm() 之后的文本（换行会被折成一个空格），且 db 那个针脚可能被换行
    推到下一行（`outbox.enqueue(` + 换行 + `db, "事件名"`）—— 两种写法都要认，所以这里先把
    db 针脚吃掉再看紧跟的是不是一个字符串字面量。
    """
    out: list[str] = []
    for part in src.split("outbox.enqueue(")[1:]:
        p = part.lstrip()
        if p.startswith("db"):
            p = p[2:].lstrip()
            if p.startswith(","):
                p = p[1:].lstrip()
        if p.startswith(Q):
            out.append(p[1:].split(Q)[0])
    return out


def main() -> int:
    missing = [str(p.relative_to(ROOT)) for p in REQUIRED if not p.is_file()]
    section("0. 反空转（被点名的文件都在 / 两个锚点找得到）")
    ok("被点名的 %d 个文件都在" % len(REQUIRED), not missing, "缺=" + str(missing))
    if missing:
        print(NL + "=" * 60)
        print("❌ 文件都不全，后面每一格都会静默空过，先补齐再来。")
        return 1

    cmd = py(CMD)
    ti = cmd.find('@traced_command("order.transfer")')
    transfer = cmd[ti:] if ti >= 0 else ""
    ok("order.transfer 的实现段找得到（装饰器 → 文件末尾）", ti >= 0 and len(transfer) > 4000, "长度=" + str(len(transfer)))

    trigger = "if follow_driver_id is not None and created and target.driver_id is None:"
    fi = transfer.find(trigger)
    tre = transfer.find("_resync_stock_if_assigned(db, target, actor.id)", fi) if fi >= 0 else -1
    follow = transfer[fi:tre] if (fi >= 0 and tre > fi) else (transfer[fi:] if fi >= 0 else "")
    ok("跟随块找得到（触发条件那一行 → 目标单预占对账之前）", fi >= 0 and 400 < len(follow) < 4000, "长度=" + str(len(follow)))
    nf = norm(follow)
    nt = norm(transfer)

    # ── 1. 何时跟 ────────────────────────────────────────────────────────
    section("1. 什么时候跟（触发条件 / 意图取值早于任何写）")
    ci = cmd.find("DRIVER_HOLDING_STATUSES: tuple[OrderStatus, ...] = (")
    cblk = cmd[ci : cmd.find(")", ci)] if ci >= 0 else ""
    members = [t.strip().replace("OrderStatus.", "").strip(",") for t in cblk.split("(", 1)[1].split(",") if t.strip()]
    ok("「货在司机手上」写成模块级常量，成员恰好 DISPATCHED / ACCEPTED", ci >= 0 and members == HOLDING, "成员=" + str(members))
    ok("常量旁点名了「函数体里不许再出现同形状表达式」（挡板只许一处）", "挡板" in raw(CMD)[max(0, raw(CMD).find("DRIVER_HOLDING_STATUSES") - 500) : raw(CMD).find("DRIVER_HOLDING_STATUSES")])
    ok("触发条件是「源单在司机手上 + 这次是新开的一张 + 新单还没有司机」三合一", trigger in nf, "触发行=" + str(trigger in nf))
    ok("意图只在源单确实在司机手上时取（司机空 / 状态只是待派单都不取）", "order.driver_id is not None and order.status in DRIVER_HOLDING_STATUSES" in nt)
    reads = [p for p in (transfer.find("follow_driver_id = ("),) if p >= 0]
    first_write = min([p for p in (transfer.find("for op, qty in moves:"), transfer.find("db.delete(op)")) if p >= 0] or [-1])
    ok("意图读取早于第一处写（整单转空会把司机从源单上摘掉，晚读就读不到了）", bool(reads) and first_write > 0 and reads[0] < first_write, "读=" + str(reads) + " 首写=" + str(first_write))
    ok("跟随取的是**源单的司机**，不是操作人", "db.get(User, follow_driver_id)" in nf and "db.get(User, actor.id)" not in nf)

    # ── 2. 怎么跟（时机 / 事务 / 状态机）──────────────────────────────────
    section("2. 怎么跟（派单的时机 / 失败即整笔失败 / 一句 status 都不写）")
    imp = cmd[cmd.find("from app.services.order_flow import (") : cmd.find(")", cmd.find("from app.services.order_flow import ("))]
    ok("assign_driver 从 order_flow 借进来（派单这条路只此一份实现）", "assign_driver," in imp, "import 块=" + norm(imp)[:160])
    ok("transfer_lines 里调用 assign_driver 恰好一处", transfer.count("assign_driver(") == 1, "次数=" + str(transfer.count("assign_driver(")))
    ok("命令层不写状态（没有 target.status = / order.status = / update(Order)）", not re.search(r"\b(order|target)\.status\s*=(?!=)", follow) and "update(Order)" not in nf and ".values(" not in nf)
    p_flush = transfer.find("db.flush()")
    p_cancel = transfer.find("cancel_pending(db, order, actor)")
    p_expire = transfer.find('db.expire(order, ["order_products"])')
    p_assign = transfer.find("assign_driver(")
    ok("派单晚于落盘与明细失效（预占按搬完之后的现状写）", 0 <= p_flush < p_expire < p_assign, "flush=" + str(p_flush) + " expire=" + str(p_expire) + " assign=" + str(p_assign))
    ok("派单晚于源单作废（整单转空也照样跟）", 0 <= p_cancel < p_assign, "cancel=" + str(p_cancel) + " assign=" + str(p_assign))
    ok("派单早于目标单的预占对账（对账是复核，不该由它写占用）", 0 <= p_assign < tre, "assign=" + str(p_assign) + " 对账=" + str(tre))
    ok("目标单的预占对账仍然只有一处", transfer.count("_resync_stock_if_assigned(db, target, actor.id)") == 1)
    flushes = [m.start() for m in re.finditer(re.escape("db.flush()"), transfer)]
    ok("派单之后、目标单对账之前又落了一次盘（autoflush=False：派单刚写的预占流水不落盘就 SUM 不到，"
       "会照着 want 再写一整笔 —— 真库探针实测的第 4 个真 bug）",
       len(flushes) >= 2 and p_assign < flushes[1] < tre
       and transfer[flushes[1] + len("db.flush()") : tre].strip() == "",
       "flush 位置=" + str(flushes) + " assign=" + str(p_assign) + " 对账=" + str(tre))
    sect = raw(CMD)[raw(CMD).find("── 跟随原司机") : raw(CMD).find("_resync_stock_if_assigned(db, target, actor.id)")]
    ok("派单**不拿** SAVEPOINT 兜（Session.rollback() 回滚整笔事务，存档点一起被放掉 —— 兜不住就别假装兜）",
       "begin_nested" not in nf and "SAVEPOINT" in sect and "with db" not in nf)
    ok("派不出去就是整笔失败：except ValueError 直接抛 CommandError(409)，并写明「这笔转货没有完成」",
       "except ValueError as e:" in nf and "raise CommandError(" in nf and "status_code=409" in nf
       and "这笔转货没有完成（源单没动、货也没搬），请重试" in raw(CMD))
    ok("那段注释点名了「Session.rollback() 回滚整笔事务 + 探针实测」这个坑（免得后人又加回存档点）",
       "整笔事务" in sect and "探针" in sect and "rollback" in sect, "注释里没把理由说清楚")
    fl = py(FLOW)
    ab = fl[fl.find("def assign_driver(") : fl.find("def recall_dispatch(")]
    ok("前提属实：assign_driver 在 CAS 失败那条路上自己 db.rollback()", "db.rollback()" in ab and "这一单已经被派过了" in ab)
    ok("跟不上的三种前置情形都先自己挡（不拿 ValueError 当控制流）", all(s in nf for s in ("原来那位司机的账号已经找不到了", "原来那位司机的账号已经不是司机了", "原来那位司机已经停用（离职或被删除）")))
    ok("停用司机挡在前面（否则会被推去走「整笔失败」那条硬路）", "not driver.is_active" in nf)
    ok("三种可预期的「跟不上」仍然只降级、不拦整笔转货（只如实带一句话回去）",
       "新单没有跟过去，已放进待派单池，请重新指派一位司机" in raw(CMD) and "follow_skipped = f" in nf)
    ok("不宽泛兜异常（except Exception 会让已经坏掉的会话继续往下写）", "except Exception" not in nf)
    p_d1 = nt.find("followed_name: str | None = None")
    p_d2 = nt.find("follow_skipped: str | None = None")
    p_trig = nt.find(trigger)
    ok("两个跟随事实在触发之前就声明成 None（任何分支下 TransferResult 都有值）",
       0 <= p_d1 < p_trig and 0 <= p_d2 < p_trig, "声明=" + str([p_d1, p_d2]) + " 触发=" + str(p_trig))
    ok("跟上时记的是司机显示名，不是 id", "followed_name = _user_label(driver)" in nf)
    ok("派单备注点名源单号（司机那边看得出这趟货原来在哪张单上）", "源单 {order.order_no}" in nf)

    # ── 3. 谁先知道（事件 / 审计）────────────────────────────────────────
    section("3. 谁先知道（事件三分支 / 两行审计 / 域认领）")
    p_pool = nt.find('outbox.enqueue(db, "orders.pending_pool_changed", {})')
    p_a_cond = nt.find("if followed_name is not None:")
    p_a = nt.find('"orders.assigned"')
    p_c_cond = nt.find("elif created:")
    p_c = nt.find('"orders.created"')
    p_e_cond = nt.find("elif target.driver_id is not None:")
    p_e = nt.find('"orders.edited"')
    ok("发件箱按「跟上了 → 新单 → 并进已派单的单」三分支排列", -1 < p_pool < p_a_cond < p_a < p_c_cond < p_c < p_e_cond < p_e, "次序=" + str([p_pool, p_a_cond, p_a, p_c_cond, p_c, p_e_cond, p_e]))
    ok("orders.assigned 带的是**目标单**的 id 与司机（不是源单的）", '"orders.assigned", {"driver_id": int(target.driver_id), "order_id": int(target.id)}' in nt)
    ok("跟上了就不发 orders.created（那条文案是「新订单待派单」，会让派单员扑空）", "elif created:" in nt)
    spec = REG.read_text(encoding="utf-8") if REG.is_file() else ""
    si = spec.find('name="order.transfer"')
    spec_blk = spec[si : spec.find(NL + "    ),", si)] if si >= 0 else ""
    declared = items(field(spec_blk, "events"))
    # 实现里发件箱是**分支**的（跟上了 / 新单 / 并进已派单的单），orders.edited 有两个发点、
    # orders.assigned 那一句还是换行的 ⇒ 比集合（去重、不看顺序），比顺序是比不出来的。
    real = enqueued(nt)
    ok("注册表声明的事件与实现里真发的逐字一致（五项，按集合比）",
       sorted(declared) == sorted(set(real)) and len(declared) == 5, "声明=" + str(declared) + " 代码=" + str(real))
    map_line = [ln for ln in raw(MAP).splitlines() if "events:" in ln and "orders.created" in ln and "orders.assigned" in ln]
    ok("领域地图的订单域 events 行认领着 orders.assigned", len(map_line) == 1, "命中=" + str(len(map_line)))
    ok("main.py 有人接 orders.assigned（事件不是只声明不处理）", 'if event.event_type == "orders.assigned":' in py(MAIN))
    ok("两行审计都带上了跟随事实（out / in 各一次）", transfer.count('"followed_driver": followed_name,') == 2 and transfer.count('"follow_skipped_reason": follow_skipped,') == 2)
    ok("两行审计本身还在（没有为了少写一行把它合成一行）", transfer.count("action=OperationAction.ORDER_TRANSFER") == 2)
    ok("跟随这条路不碰钱（转货不重算价格）", not any(f in nf for f in MONEY_FIELDS))
    ok("结果里两个跟随字段被真的填回去", "followed_driver_name=followed_name," in nt and "follow_skipped_reason=follow_skipped," in nt)

    # ── 4. 契约与界面 ────────────────────────────────────────────────────
    section("4. 契约与界面（后端字段 → DTO → 抽屉 → 结果文案）")
    ok("TransferResult 的两个新字段都带默认值（加字段不改旧调用方）", "followed_driver_name: str | None = None" in cmd and "follow_skipped_reason: str | None = None" in cmd)
    sc = py(SCHEMA)
    ok("OrderTransferOut 两个字段与命令层同名，且描述点名 CHG-0043", "followed_driver_name: str | None = Field(" in sc and "follow_skipped_reason: str | None = Field(" in sc and sc.count("CHG-0043") >= 2)
    ap = py(API)
    ok("路由原样透出两个字段（不吞、不自己编）", "followed_driver_name=result.followed_driver_name," in ap and "follow_skipped_reason=result.follow_skipped_reason," in ap)
    dt = kt(DTO)
    ok("客户端 DTO 与后端 schema 同名同类型（缺省 null）", '@SerialName("followed_driver_name") val followedDriverName: String? = null' in dt and '@SerialName("follow_skipped_reason") val followSkippedReason: String? = null' in dt)
    sh = kt(SHEET)
    ok("抽屉里有一行说明「新单归谁跑」，取值来自源单司机", 'FormRow(label = "新单归谁跑")' in sh and "order.driverName" in sh)
    ok("两个分支都说清楚：跟原司机 / 进待派单池", "跟原司机 " in sh and "进待派单池" in sh)
    hi = sh.find("原来那趟活儿在谁手上，新开的那张单就直接派给谁")
    ok("静态规则写在 Hint 里（⛔ Hint 不许插值，具体人名走 FormRow）", hi > 0 and "Hint(" in sh[max(0, hi - 500) : hi])
    vm = kt(VM)
    ok("结果文案用上两个回参字段（跟上了点名司机，没跟上把原因说出来）", "r.followedDriverName" in vm and "r.followSkippedReason" in vm and "原司机" in vm)
    ok("CHG-0042 那条「源单已撤销」的文案没被这次改动碰掉", "源单已撤销（货全转走了）" in vm)

    # ── 5. 文档与登记 ────────────────────────────────────────────────────
    section("5. 文档与登记（变更文档 / 登记表 / 认领表）")
    chg = raw(CHG)
    ok("CHG-0043 变更文档在，且点名它改的是 CHG-0042 立下的哪条口径", chg.count("CHG-0042") >= 2 and "跟随" in chg)
    ok("变更文档骨架齐（摘要 / Before / After / 影响面 / Must Preserve / 测试 / 证据 / 收尾）", chg.count(NL + "## ") >= 6, "章节数=" + str(chg.count(NL + "## ")))
    ok("CHG-0042 的文档还在（不许把前一份改掉来掩盖口径变化）", "CHG-0042" in raw(CHG42))
    ok("docs/changes/README.md 登记了这一条", "CHG-0043" in raw(README))
    ok("AI_WORK_CLAIM.md 留了状态行", "CHG-0043" in raw(CLAIM))

    print(NL + "=" * 60)
    if C.fails:
        print("❌ %d 项不通过（通过 %d 项）：" % (len(C.fails), C.n_ok))
        for label, _ in C.fails:
            print("   - " + label)
        return 1
    print("✅ 全部 %d 项通过：新单跟着原来那位司机走，状态机 / 预占 / 通知三条口径都没有被绕过。" % C.n_ok)
    return 0


if __name__ == "__main__":
    sys.exit(main())
