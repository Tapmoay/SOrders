#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CHG-0042（派单期跨货主转货）判据 _check_order_transfer.py 的**反向验证**。

## 为什么需要它
_check_order_transfer.py 里那 64 条判据大半是 in src 的字面量比对 —— 它们正常跑的时候当然全绿，
问题在于**它们是不是真的盯着东西**：判据写歪了（比对一段谁都不会动的字符串）、或者产品代码
改坏了而判据恰好没看那一段，两种情况在正常跑的时候长得一模一样（都是全绿）。
这个脚本把 33 种真会有人这么改的破坏方式逐条注入进去，每条跑一次判据，要求：
① 判据必须红（rc != 0）；② 红的那几行里必须有**这一条**判据的标签。
判据用的是共用 Checker，失败行形状是「  [!!]   <标签>」。

## 这份注入表想守住的五件事（与判据同源）
1. **货归谁**：转货只动 order.shipper_id 的归属，顺手抄付款方式 / 挂账单位都是另一件事；
2. **状态机**：源单被搬空是借 cancel_pending 作废的，命令层一个字都不写 order.status；
3. **钱与审计**：两行 ORDER_TRANSFER（一出一进）、payload 金额一律 str、事务只收尾一次；
4. **在途语义**：已接单的单不许被整单搬空，客户端的状态门必须与后端挡板逐值互补；
5. **库存预占与备注**：货搬走 / 搬空之后，占着的库存必须跟着走或放掉，写下的备注不许被 refresh 吃掉
   —— 这两处都是**真实库探针**（_tmp/_probe_chg0042_transfer.py）在真库副本上逮到的，静态判据当时全绿。

## 用法
* 直接跑：逐条注入 → 跑判据 → 立刻按字节还原 → 打印每条的结论。
* --list：只列注入点，不改任何文件。

## 规矩（照 _tools/qa/_reverse_verify_detail_inline_edit.py）
1. 只按**字节**备份与还原，⛔ 不用 git checkout --（那会把别人未提交的改动一起抹掉）。
2. 还原后用 sha256 比对：不符就报 2，绝不「继续往下跑」。
3. 注入前先跑一次判据：干净状态下必须是绿的（红的话反向验证没有意义）。
4. 注入前做**锚点唯一性预检**：每条锚点在目标文件里必须恰好命中 1 次
   （0 次＝注入点腐烂了；>1 次＝可能打到别人身上，那是**假绿**）。
5. 任何一条腐烂都报出来，不许静默跳过。

⚠️ 被硬中断（Ctrl-C / 断电）时，注入可能还留在文件里：
   python _tools/qa/_check_reverse_verify_anchors.py --restore

用法：python _tools/qa/_reverse_verify_order_transfer.py
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import (  # noqa: E402
    lock_reverse_verify,
    refuse_if_injecting,
    unlock_reverse_verify,
)

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_order_transfer.py"

# (说明，文件，原文，替换成，期望被哪条判据标签抓到)
# 说明那句话就是「真会有人这么改」的理由（照反向验证脚本的房规逐条写清）。
INJECTIONS: list[tuple[str, str, str, str, str]] = [
    (
        '把实现指回一个已经不存在的服务模块：订单域命令只许落 order_flow 或 commands.order，落到别处等于命令层多出一个家（这条判据就是被它逼出来的）',
        'backend/app/commands/registry.py',
        'impl="commands.order:transfer_lines"',
        'impl="services.order_transfer:transfer_lines"',
        '实现落在 commands.order:transfer_lines（订单域命令只许落 order_flow 或 commands.order）',
    ),
    (
        '能力点从 ORDER_EDIT 换成一颗新的 ORDER_TRANSFER：看着更贴切，实则新建了一套权限点（权限体系从此两处说话）',
        'backend/app/commands/registry.py',
        'impl="commands.order:transfer_lines",\n        capabilities=("ORDER_EDIT",),',
        'impl="commands.order:transfer_lines",\n        capabilities=("ORDER_TRANSFER",),',
        '能力点是 ORDER_EDIT（与 order.edit / order.split 同一颗，不新建权限点）',
    ),
    (
        '前置状态少写一个（漏掉「已接单」）：注册表与实现里的挡板从此对不上，而少的那一态恰好是司机已经认下的单',
        'backend/app/commands/registry.py',
        'impl="commands.order:transfer_lines",\n        capabilities=("ORDER_EDIT",),\n        from_states=("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED"),',
        'impl="commands.order:transfer_lines",\n        capabilities=("ORDER_EDIT",),\n        from_states=("PENDING_DISPATCH", "DISPATCHED"),',
        'from_states 逐字是「待派单 / 已派单 / 已接单」',
    ),
    (
        '声明 to_state 是 CANCELLED：看起来更「完整」，其实把「转货本身改状态」写进了机器对账的事实里（真正作废源单的是 cancel_pending）',
        'backend/app/commands/registry.py',
        'impl="commands.order:transfer_lines",\n        capabilities=("ORDER_EDIT",),\n        from_states=("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED"),\n        to_state="",',
        'impl="commands.order:transfer_lines",\n        capabilities=("ORDER_EDIT",),\n        from_states=("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED"),\n        to_state="CANCELLED",',
        'to_state 是空串（转货本身不改源单的状态）',
    ),
    (
        '声明里漏掉「源单被搬空」那个事件：发件箱照样发，注册表从此少说一件事（下游按注册表对账就会漏掉这一路）',
        'backend/app/commands/registry.py',
        'events=(\n            "orders.created",\n            "orders.edited",\n            "orders.cancelled",\n            "orders.assigned",\n            "orders.pending_pool_changed",\n        ),',
        'events=(\n            "orders.created",\n            "orders.edited",\n            "orders.assigned",\n            "orders.pending_pool_changed",\n        ),',
        '声明的五个事件与实现里真的 enqueue 的五个逐字一致',
    ),
    (
        '挡板少列一个终态（把「已退货」放进来）：退过货的单还能再转一次，那些货已经退回去了，两边账都会多出一批不存在的货',
        'backend/app/commands/order.py',
        '    if order.status in (\n        OrderStatus.DELIVERED,\n        OrderStatus.CANCELLED,\n        OrderStatus.RETURNED,\n    ):',
        '    if order.status in (\n        OrderStatus.DELIVERED,\n        OrderStatus.CANCELLED,\n    ):',
        '挡板逐字挡掉「已送达 / 已撤销 / 已退货」三个终态',
    ),
    (
        '图省事自己写状态（把借 cancel_pending 换成直接赋 CANCELLED）：界面、单测全绿，状态机却从此有了第二个入口',
        'backend/app/commands/order.py',
        'cancel_pending(db, order, actor)',
        'order.status = OrderStatus.CANCELLED  # 自己改，省一层',
        '命令层不写 order.status / 不做 update(Order).values(status=…)',
    ),
    (
        '顺手把付款方式也抄到新单上：转货只动货，钱的事一个字都不该碰（抄过去两边都多出一个谁也没要求过的结论）',
        'backend/app/commands/order.py',
        '        remark=source.remark,\n        driver_remark=source.driver_remark,',
        '        remark=source.remark,\n        driver_remark=source.driver_remark,\n        payment_method=source.payment_method,',
        '转货不碰钱：实现里不出现 payment_method / 挂账单位 / 现场收现',
    ),
    (
        '构造期状态抄成源单的状态（DISPATCHED）：新单会带着一个没人派过、也没人接过的「已派单」出生',
        'backend/app/commands/order.py',
        '        status=OrderStatus.PENDING_DISPATCH,\n        shipper_id=shipper_id,\n        temp_shipper_name=temp_name,',
        '        status=OrderStatus.DISPATCHED,\n        shipper_id=shipper_id,\n        temp_shipper_name=temp_name,',
        '目标单构造期状态是 PENDING_DISPATCH，且只此一处',
    ),
    (
        '自己拼单号：单号一旦不是 new_order_no() 发的，全库唯一与日期前缀这两件事就没人保证了',
        'backend/app/commands/order.py',
        '    target = Order(\n        order_no=new_order_no(),',
        '    target = Order(\n        order_no="SO-TMP-" + str(actor.id),',
        '目标单号走 new_order_no()（不自己拼单号）',
    ),
    (
        '「进」的那一行审计换成别的动作码：货进来了，日志里却写成改明细 —— 事后只能靠猜',
        'backend/app/commands/order.py',
        '        action=OperationAction.ORDER_TRANSFER,\n        change_payload={\n            "direction": "in",',
        '        action=OperationAction.ORDER_LINE_UPDATE,\n        change_payload={\n            "direction": "in",',
        '两行 ORDER_TRANSFER 审计（一出一进）',
    ),
    (
        '审计里直接塞 Decimal（不 str）：write_log 走 json.dumps，这一行会在写日志的时候抛',
        'backend/app/commands/order.py',
        '"unit_price": str(price),',
        '"unit_price": price,',
        '审计的 change_payload 里金额是 str（Decimal 直接塞会抛）',
    ),
    (
        '并进既有单前不加锁：两个人同时往同一张单上并货，行与预占都会算重（而两条路各自看都对）',
        'backend/app/commands/order.py',
        '        else:\n            db.execute(select(Order.id).where(Order.id == target.id).with_for_update())',
        '        else:\n            pass  # 省一次锁',
        '并进既有单前给目标单加锁（锁序恒为源单 → 目标单）',
    ),
    (
        '目标单的预占不重算：目标单上多出来的货在库里没有对应的预占，库存会虚高',
        'backend/app/commands/order.py',
        '    _resync_stock_if_assigned(db, target, actor.id)',
        '    # 预占先不管了',
        '预占各重算一次：源单没作废就重算它，目标单总是重算',
    ),
    (
        '事务被拆开：中途先 commit 一次，业务写与发件箱不再同一个事务（改单没成，司机却可能已经收到消息）',
        'backend/app/commands/order.py',
        '    # 审计要用的行快照',
        '    db.commit()  # 先把源单落一次\n\n    # 审计要用的行快照',
        '命令层只 commit 一次（业务写与发件箱同一个事务）',
    ),
    (
        '「已接单不许整单转空」那道门里的状态写错（DISPATCHED）：已接单的单会被直接作废，司机手机上那张单莫名其妙空掉',
        'backend/app/commands/order.py',
        'if empties_source and order.status == OrderStatus.ACCEPTED:',
        'if empties_source and order.status == OrderStatus.DISPATCHED:',
        '「已接单」不许整单转空（先撤回派单再转）',
    ),
    (
        '端点换成只读权限：任何能看单的人都能把货转走',
        'backend/app/api/v1/orders_assignment.py',
        '    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),\n) -> OrderTransferOut:',
        '    current: User = Depends(require_permission(Permission.ORDER_READ_ALL)),\n) -> OrderTransferOut:',
        '端点存在，权限点 ORDER_DISPATCH（与派单同一颗，不新建）',
    ),
    (
        'CommandError 被吞成通用异常：业务给的那句人话（「司机已经接单了…」）到不了派单员眼前，只剩 500',
        'backend/app/api/v1/orders_assignment.py',
        '    except order_commands.CommandError as e:',
        '    except Exception as e:',
        '路由只负责 HTTP：CommandError 原样透出',
    ),
    (
        '路由自己 commit：事务收尾跑到 HTTP 层，命令层再想回滚也回不了',
        'backend/app/api/v1/orders_assignment.py',
        '    return OrderTransferOut(\n        order=enrich_order_out(result.order, db, current),',
        '    db.commit()\n    return OrderTransferOut(\n        order=enrich_order_out(result.order, db, current),',
        '路由自己不 commit（事务收尾在命令层）',
    ),
    (
        '客户端状态门多一个终态（已送达也能转）：界面上给得出这个按钮，后端却要拒，用户白跑一趟',
        'android/app/src/main/java/com/tapmoay/sorders/core/OrderStatusModel.kt',
        'val TRANSFERABLE: Set<String> = setOf("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED")',
        'val TRANSFERABLE: Set<String> = setOf("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED", "DELIVERED")',
        '客户端 TRANSFERABLE 与后端挡板的补集逐值一致（在途三态）',
    ),
    (
        '入口的角色门拆掉只按状态判：货主与司机打开在途的单，都能看见「转货」',
        'android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailScreen.kt',
        'if (role == Role.DISPATCHER && order.status in OrderStatusModel.TRANSFERABLE) {',
        'if (order.status in OrderStatusModel.TRANSFERABLE) {',
        '转货入口恰好一处，且挂在「派单员 + 在途三态」门上',
    ),
    (
        '抽屉自己写一个加减器（不用共用的那一份）：数量控件从此两份，形态与上限各说各话',
        'android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderTransferSheet.kt',
        'QtyStepper(',
        'LocalQtyStepper(',
        '抽屉里的数量控件是共用的那一份（QtyStepper），上限夹在本行现有数量内',
    ),
    (
        '抽屉不再夹本行现有数量：能把比现有更多的件数填出去，后端只能拒',
        'android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderTransferSheet.kt',
        'onQtyChange = { onQtyChange(it.coerceIn(0, line.quantity)) },',
        'onQtyChange = { onQtyChange(it) },',
        '抽屉里的数量控件是共用的那一份（QtyStepper），上限夹在本行现有数量内',
    ),
    (
        '抽屉自己算行金额：金额口径从此两处说话（真源是服务端的行金额）',
        'android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderTransferSheet.kt',
        'UnitTag(line.unit)',
        'UnitTag(line.unit)\n            val lineTotal = moneyToDouble(line.unitPrice) * qty',
        '抽屉不自己算钱（只显示服务端给的单价，不做乘法）',
    ),
    (
        '把「先选人」这条本地校验去掉：直接发请求，让后端拒（用户要先跑一趟网络才知道自己没选货主）',
        'android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailViewModel.kt',
        'transferError = "请先选一位货主（或填临时货主）"',
        'transferError = null',
        '没选人 / 没填行都不发请求（本地校验先于请求）',
    ),
    (
        '客户端不再夹上限：比现有更多的件数照样发出去，白跑一趟网络才被后端拒',
        'android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailViewModel.kt',
        'q.coerceAtMost(line.quantity)',
        'q',
        '客户端也把上限夹在现有数量内（后端会拒，但不该让他先跑一趟网络）',
    ),
    (
        '成功后不按回参重拉：源单可能已经被搬空作废，页面上却还是转之前那张单的样子',
        'android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailViewModel.kt',
        '                actionResult = transferResultText(r)\n                showTransferSheet = false\n                load()',
        '                actionResult = transferResultText(r)\n                showTransferSheet = false',
        '成功后按回参重拉，不复算金额',
    ),
    (
        '结果文案不再说源单被作废：货全转走了，派单员却以为那张单还在',
        'android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailViewModel.kt',
        'head + "，源单已撤销（货全转走了）"',
        'head + ""',
        '结果文案点名「源单已撤销」（搬空必须让派单员看见）',
    ),
    (
        '领域地图里撤掉这条命令的登记：地图与实现两处形状不再对称（谁拥有这个动作从此查不到）',
        'docs/DOMAIN_BOUNDARIES.md',
        ', commands.order:transfer_lines',
        '',
        '领域地图的订单域 commands 行里有 commands.order:transfer_lines',
    ),
    (
        '动作码的值抄成拆单（ORDER_SPLIT）：审计里读出来是「拆分订单」，转货在事后完全看不见',
        'backend/app/models/enums.py',
        'ORDER_TRANSFER = "ORDER_TRANSFER"',
        'ORDER_TRANSFER = "ORDER_SPLIT"',
        'ORDER_TRANSFER 动作码在 models/enums.py 里，且只定义一次',
    ),
    (
        '调 _put_line 时少写一个 db 针脚：类型上完全合法、写的时候也读得通，第一次转货就 TypeError 500'
        ' —— 真实库探针就是这么逮到它的（静态判据当时全绿）',
        'backend/app/commands/order.py',
        '_put_line(db, target, op, int(qty))',
        '_put_line(target, op, int(qty))',
        '_put_line 的调用与定义同口径（少一个 db 针脚 ⇒ 第一次转货就 TypeError 500）',
    ),
    (
        '行搬完不落盘、也不让明细集合失效就去对预占：对账读的是内存里那份缓存（整行搬走的那行还在、数量还是原值），'
        '差额算成 0 —— 源单从此永久占着一批已经不存在的货，而总账是平的、对账看不出来',
        'backend/app/commands/order.py',
        '    db.flush()\n    db.expire(order, ["order_products"])',
        '    pass  # 对账读的就是内存里的行，用不着落盘',
        '行搬完先落盘 + 让明细集合失效，再让预占对账（否则整行搬走时差额算成 0，源单永久占着不存在的货）',
    ),
    (
        '把内部备注挪回 cancel_pending 之前写：cancel_pending 里有一次 db.refresh(order)，'
        '而 sessionmaker 是 autoflush=False —— 没落盘的备注被整段丢掉，源单上看不见「货转给谁了」',
        'backend/app/commands/order.py',
        '    source_cancelled = False\n    if empties_source:',
        '    order.internal_notes = _note_with(\n        order.internal_notes,\n        f"[转货 {_stamp()}] 已转出给「{label}」（{target.order_no}）：{len(moves)} 行",\n    )\n    source_cancelled = False\n    if empties_source:',
        '两处内部备注写在最后（cancel_pending 里的 db.refresh 会把没落盘的备注整段丢掉）',
    ),
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_check() -> tuple[int, str]:
    """跑判据：返回 (退出码, stdout + stderr)。"""
    proc = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def count_hits(text: str, old: str) -> int:
    pat = old[3:] if old.startswith("re:") else re.escape(old)
    return len(re.findall(pat, text))


def anchor_preflight() -> list[str]:
    """锚点必须唯一命中：0 次＝注入点腐烂；>1 次＝可能打到别人身上（假绿）。"""
    bad: list[str] = []
    for i, (name, rel, old, _new, _want) in enumerate(INJECTIONS, 1):
        p = ROOT / rel
        if not p.is_file():
            bad.append("%2d. %s —— 文件不存在：%s" % (i, name, rel))
            continue
        hits = count_hits(p.read_text(encoding="utf-8"), old)
        if hits != 1:
            bad.append("%2d. %s —— 锚点在 %s 命中 %d 次（必须恰好 1 次）" % (i, name, rel, hits))
    return bad


def caught_by(out: str, want: str) -> bool:
    """判据那一行是不是「这一条」：房规的形状是「  [!!]   <标签>」。"""
    return ("[!!]   " + want) in out or ("[!!]   ⛔ " + want) in out


_PENDING: dict[str, tuple[bytes, bytes, str]] = {}


def restore_pending() -> None:
    for rel, (orig, wrote, orig_sha) in list(_PENDING.items()):
        p = ROOT / rel
        try:
            cur = p.read_bytes()
        except OSError:
            print("  🛑 %s 读不到了 —— 请人工处理！" % rel)
            continue
        if cur != wrote:
            print("  🛑 %s 内容与注入时不一致（有人在动它）—— **拒绝还原**，请人工处理！" % rel)
            continue
        p.write_bytes(orig)
        if sha(p) != orig_sha:
            print("  🛑 %s 还原后 sha256 不符 —— 请人工处理！" % rel)
        else:
            _PENDING.pop(rel, None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="只列注入点，不改任何文件")
    args = ap.parse_args()

    if args.list:
        for i, (name, rel, _old, _new, want) in enumerate(INJECTIONS, 1):
            print("%2d. %s" % (i, name))
            print("      %s   ← 期望被「%s」抓到" % (rel, want))
        print("\n共 %d 条注入。" % len(INJECTIONS))
        return 0

    if refuse_if_injecting("派单期跨货主转货（CHG-0042）反向验证"):
        return 1

    rc, out = run_check()
    if rc != 0:
        print("🛑 干净状态下判据就是红的 —— 先修判据/产品代码，反向验证没有意义。")
        print(out[-3000:])
        return 2

    bad = anchor_preflight()
    if bad:
        print("🛑 锚点预检不过（这些注入点会打空或打到别处）—— 一个字节都没改：")
        for line in bad:
            print("   - " + line)
        return 2

    lock_reverse_verify()
    caught = 0
    problems: list[str] = []
    try:
        for i, (name, rel, old, new, want) in enumerate(INJECTIONS, 1):
            path = ROOT / rel
            orig = path.read_bytes()
            orig_sha = sha(path)
            text = orig.decode("utf-8")
            eol = "\r\n" if "\r\n" in text else "\n"
            o = old.replace("\n", eol)
            n = new.replace("\n", eol)
            pat = o[3:] if o.startswith("re:") else re.escape(o)
            text2, hits = re.subn(pat, lambda _m: n, text, count=1)
            if hits != 1:
                problems.append("%d. %s —— 锚点没命中（注入点腐烂了）" % (i, name))
                print("  [%2d/%d] ⚠️  锚点没命中：%s" % (i, len(INJECTIONS), name))
                continue
            wrote = text2.encode("utf-8")
            _PENDING[rel] = (orig, wrote, orig_sha)
            path.write_bytes(wrote)

            rc, out = run_check()

            cur = path.read_bytes()
            if cur != wrote:
                print("  🛑 %s 在验证期间被改动过 —— 拒绝还原，请人工处理！" % rel)
                return 2
            path.write_bytes(orig)
            if sha(path) != orig_sha:
                print("  🛑 %s 还原后 sha256 不符 —— 请人工处理！" % rel)
                return 2
            _PENDING.pop(rel, None)

            if rc != 0 and caught_by(out, want):
                caught += 1
                print("  [%2d/%d] ✅ %s" % (i, len(INJECTIONS), name))
            else:
                why = "判据没红（漏网）" if rc == 0 else "红了但不是这一条（找不到「%s」）" % want
                problems.append("%d. %s —— %s" % (i, name, why))
                print("  [%2d/%d] ❌ %s —— %s" % (i, len(INJECTIONS), name, why))
                for line in out.splitlines():
                    if line.startswith("  [!!]"):
                        print("        " + line.strip())
    finally:
        restore_pending()
        unlock_reverse_verify()

    print()
    if problems:
        print("❌ %d 条注入没被抓住（判据在那些地方是空转的）：" % len(problems))
        for line in problems:
            print("   - " + line)
        return 1
    print(
        "✅ %d/%d 种破坏方式被抓住 —— 判据在这 %d 个点上都不是空转的。"
        % (caught, len(INJECTIONS), len(INJECTIONS))
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
