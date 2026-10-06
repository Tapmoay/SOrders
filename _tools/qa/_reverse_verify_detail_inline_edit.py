#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CHG-0041（订单详情页就地改单）判据 _check_detail_inline_edit.py 的**反向验证**。

## 为什么需要它
`_check_detail_inline_edit.py` 里那 55 条判据全是 `in src` 的字面量比对 —— 它们当然会全绿，
问题在于**它们是不是真的盯着东西**：判据写歪了（比对一段谁都不会动的字符串）、或者产品代码
改坏了而判据恰好没看那一段，两种情况在正常跑的时候长得一模一样（都是全绿）。
这个脚本的办法是**把 30 种真会有人这么改的破坏方式逐条注入进去**，每条跑一次判据，
要求：① 判据必须红（rc != 0）；② 红的那几行里必须有**这一条**判据的标签。
判据用的是共用 Checker，失败行形状是 `  [!!]   <标签>`。

## 用法
* 直接跑：逐条注入 → 跑判据 → 立刻按字节还原 → 打印每条的结论。
* `--list`：只列注入点，不改任何文件。

## 规矩（照 _tools/qa/_reverse_verify_silent_release.py）
1. 只按**字节**备份与还原，⛔ 不用 `git checkout --`（那会把别人未提交的改动一起抹掉）。
2. 还原后用 sha256 比对：不符就报 2，绝不"继续往下跑"。
3. 注入前先跑一次判据：干净状态下必须是绿的（红的话反向验证没有意义）。
4. 注入前做**锚点唯一性预检**：每条锚点在目标文件里必须**恰好命中 1 次**
   （0 次＝注入点腐烂了；>1 次＝可能打到别人身上，那是**假绿**）。
5. 任何一条腐烂都报出来，不许静默跳过。

⚠️ 被硬中断（Ctrl-C / 断电）时，注入可能还留在文件里：
   python _tools/qa/_check_reverse_verify_anchors.py --restore

用法：python _tools/qa/_reverse_verify_detail_inline_edit.py
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
CHECK = ROOT / "_tools" / "qa" / "_check_detail_inline_edit.py"

ANDROID = "android/app/src/main/java/com/tapmoay/sorders/"
SCREEN = ANDROID + "ui/order/OrderDetailScreen.kt"
DETAIL_VM = ANDROID + "ui/order/OrderDetailViewModel.kt"
INLINE = ANDROID + "ui/order/OrderEditInline.kt"
STATUS = ANDROID + "core/OrderStatusModel.kt"
PRODS = "backend/app/api/v1/order_products.py"
RBAC = "backend/app/core/rbac.py"

# (说明，文件，原文，替换成，期望被哪条判据标签抓到)
# 说明那句话就是「真会有人这么改」的理由（照反向验证脚本的房规逐条写清）。
INJECTIONS: list[tuple[str, str, str, str, str]] = [
    # ---- ① 角色门与状态门：谁能看到「改」 ----
    (
        "把「改」的角色门拆掉，只按状态判 —— 从「派单员专用」变成「能改的单谁都能改」",
        SCREEN,
        "val canEditInfo = role == Role.DISPATCHER && order.status in OrderStatusModel.EDITABLE",
        "val canEditInfo = order.status in OrderStatusModel.EDITABLE",
        "canEditInfo 逐字：role == Role.DISPATCHER && OrderStatusModel.EDITABLE",
    ),
    (
        "明细门放给货主（role == Role.SHIPPER）：他打开自己的单就能加货、改数量单价",
        SCREEN,
        "val canEditLines = role == Role.DISPATCHER && order.status in OrderStatusModel.LINE_EDITABLE",
        "val canEditLines = role == Role.SHIPPER && order.status in OrderStatusModel.LINE_EDITABLE",
        "canEditLines 逐字：role == Role.DISPATCHER && OrderStatusModel.LINE_EDITABLE",
    ),
    (
        "收货地址那颗「改」不再过门 —— 真机 5556 货主端就是拿这条判据测的（应该一个节点都 dump 不到）",
        SCREEN,
        "if (canEditInfo) EditHint(onClick = { edit.startEdit(OrderEditField.ADDRESS) })",
        "EditHint(onClick = { edit.startEdit(OrderEditField.ADDRESS) })",
        "四颗「改」全挂在 canEditInfo 后面（恰好 4 处）",
    ),
    (
        "「加一件货」不过门：货主与司机都看得见，点下去才 403",
        SCREEN,
        'if (canEditLines) {\n                    TextButton(onClick = { edit.openLinePicker() }) { Text("加一件货") }\n                }',
        'TextButton(onClick = { edit.openLinePicker() }) { Text("加一件货") }',
        "「加一件货」在 canEditLines 里面",
    ),
    (
        "点整行的门被去掉：三端随便点一行都会弹出行内编辑框",
        SCREEN,
        "if (canEditLines) Modifier.clickable { edit.startLineEdit(line) } else Modifier,",
        "Modifier.clickable { edit.startLineEdit(line) },",
        "点整行改明细也要过 canEditLines",
    ),
    (
        "行内编辑块的门少了一半：只要 editingLineId 还在（哪怕角色不对）就画输入框",
        SCREEN,
        "if (canEditLines && edit.editingLineId == line.id) {",
        "if (edit.editingLineId == line.id) {",
        "行内编辑块只在 canEditLines 且正是这一行时挂",
    ),
    # ---- ② 六个入口：少一个，用户就少一条路 ----
    (
        "备注那一行的「改」被去掉（四行里少一行：那一行从此只能去「新增订单」里改）",
        SCREEN,
        "if (canEditInfo) EditHint(onClick = { edit.startEdit(OrderEditField.REMARK) })",
        "// 备注先不给改",
        "收货信息有一块能改：edit.startEdit(OrderEditField.REMARK)",
    ),
    (
        "点行之后不再换成编辑块（换成别的东西）：点行什么都不会发生",
        SCREEN,
        "ProductLineEditBlock(edit, line)",
        "ProductLineRow(line)",
        "明细行：编辑态换成 ProductLineEditBlock(edit, line)",
    ),
    (
        "那句「点某一行可以改数量与单价」画给所有人：先告诉他可以点，再让他点不动",
        SCREEN,
        'if (canEditLines) {\n                    Text(\n                        "点某一行可以改数量与单价",\n                        style = MaterialTheme.typography.bodySmall,\n                        color = MaterialTheme.colorScheme.onSurfaceVariant,\n                    )\n                    Spacer(Modifier.height(6.dp))\n                }',
        'Text(\n                    "点某一行可以改数量与单价",\n                    style = MaterialTheme.typography.bodySmall,\n                    color = MaterialTheme.colorScheme.onSurfaceVariant,\n                )\n                Spacer(Modifier.height(6.dp))',
        "「点某一行可以改数量与单价」这句只画给 canEditLines 的人",
    ),
    # ---- ③ 结果横幅与那四句文案 ----
    (
        "横幅写死一句：改失败也显示「已经改好」，用户看不到真正的结果",
        SCREEN,
        "vm.actionResult?.let { msg ->",
        '"已经改好".let { msg ->',
        "本页真的把 vm.actionResult 画出来了",
    ),
    (
        "改收货信息那句不再点名司机 —— 用户 2026-10-05 要的正是「司机那边会收到一条消息」",
        DETAIL_VM,
        'actionResult = "已经改好，司机那边会收到一条消息"',
        'actionResult = "已经改好"',
        "改收货信息的成功文案逐字点名司机",
    ),
    (
        "改明细那句不再点名司机（司机其实还是会收到，但用户以为不会了）",
        DETAIL_VM,
        'actionResult = "这件货改好了，司机那边会收到一条消息"',
        'actionResult = "这件货改好了"',
        "改一件货的成功文案逐字点名司机",
    ),
    (
        "删掉一件货之后什么都不说：件数变了、司机收到消息了，用户看不到任何反馈",
        DETAIL_VM,
        'actionResult = "这一件货删掉了，司机那边会收到一条消息"',
        'actionResult = "这一件货删掉了"',
        "删掉一件货的成功文案逐字点名司机",
    ),
    (
        "加货后不说加了几件（批量加货是逐行请求，件数正是用户要核对的那个数）",
        DETAIL_VM,
        'actionResult = "加了 " + added + " 件货，司机那边会收到一条消息"',
        'actionResult = "加好了，司机那边会收到一条消息"',
        "加货的文案说清加了几件、并点名司机",
    ),
    # ---- ④ 钱：一律由后端算 ----
    (
        "行内编辑多摆一个「行金额（元）」输入框：用户以为能直接改钱（后端会重算/400，他看到的是白改）",
        INLINE,
        'EditBox(\n                label = "单价（元）",\n                value = edit.linePrice,\n                onValue = { edit.updateLinePrice(InputRules.priceInput(it)) },\n                keyboard = KeyboardType.Decimal,\n                modifier = Modifier.weight(1f),\n            )',
        'EditBox(\n                label = "单价（元）",\n                value = edit.linePrice,\n                onValue = { edit.updateLinePrice(InputRules.priceInput(it)) },\n                keyboard = KeyboardType.Decimal,\n                modifier = Modifier.weight(1f),\n            )\n            EditBox(\n                label = "行金额（元）",\n                value = edit.linePrice,\n                onValue = { edit.updateLinePrice(InputRules.priceInput(it)) },\n                keyboard = KeyboardType.Decimal,\n                modifier = Modifier.weight(1f),\n            )',
        "行内编辑只有数量与单价两个输入框（界面不给改金额的框）",
    ),
    (
        "屏上的合计改成本地自算（单价 × 数量）：行小计与合计从此可以和后端/账本对不上，而这不报错",
        SCREEN,
        "val netTotal = netOrderMoneyText(order)",
        'val netTotal = "¥" + formatMoney(order.orderProducts.sumOf { moneyToDouble(it.unitPrice) * it.quantity }.toString())',
        "屏上的合计走共用口径",
    ),
    (
        "后端行金额改成自己乘（不再走唯一算法）：四舍五入/单位换算的规矩全没了",
        PRODS,
        "op.line_total = resolve_line_total(new_up, new_qty, body.line_total)",
        "op.line_total = new_up * new_qty",
        "后端行金额仍走唯一算法 resolve_line_total",
    ),
    (
        "客户端自己算一遍行金额并塞进请求（lineTotal）：账本跟着错的经典来源",
        DETAIL_VM,
        "OrderProductUpdateRequest(quantity = qty, unitPrice = price),",
        "OrderProductUpdateRequest(quantity = qty, unitPrice = price, lineTotal = (price.toDouble() * qty).toString()),",
        "客户端不自己算行金额（VM 里没有 lineTotal / line_total）",
    ),
    # ---- ⑤ 本地校验先于请求 ----
    (
        "保存前不再校验电话（改成交给后端判）：用户填错一个字，看到的是后端那句看不懂的话",
        DETAIL_VM,
        "InputRules.phoneError(phoneDraft)?.let { editError = it; return }\n        InputRules.phoneError(bossDraft)?.let { editError = it; return }",
        "// 电话交给后端判（生产库里的老数据本来就不规范）",
        "两个电话校验都在发请求之前",
    ),
    (
        "数量校验放宽成「不为空就行」（0 与负数也放过去）：后端不会替用户兜这一档",
        DETAIL_VM,
        'if (qty == null || qty <= 0) {\n            editError = "数量要填一个大于 0 的整数"\n            return\n        }',
        'if (qty == null) {\n            editError = "数量要填一个整数"\n            return\n        }',
        "数量与单价的校验都在发请求之前",
    ),
    (
        "六字段全量提交时把 internalNotes 丢了：后端是「给什么改什么」，这一趟就等于把内部备注清空",
        DETAIL_VM,
        "internalNotes = o.internalNotes,\n",
        "",
        "internalNotes 原样带回（改单不许顺手清掉内部备注）",
    ),
    # ---- ⑥ 写库路径不新增 ----
    (
        "改单改走一个新端点（updateOrderInline）：同一件事两条路，迟早只改一边",
        DETAIL_VM,
        "container.repo.updateOrder(",
        "container.repo.updateOrderInline(",
        "改单走既有 updateOrder（不新开一条写库路径）",
    ),
    (
        "删行改走一个新端点（deleteOrderProductInline）",
        DETAIL_VM,
        "container.repo.deleteOrderProduct(lineId)",
        "container.repo.deleteOrderProductInline(lineId)",
        "改行 / 删行 / 加货走既有的三个方法",
    ),
    (
        "后端给 order-products 多开一个批量端点（本次明说零后端改动）",
        PRODS,
        '@router.patch("/{line_id}", response_model=OrderProductOut)',
        '@router.patch("/batch", response_model=list[OrderProductOut])\n@router.patch("/{line_id}", response_model=OrderProductOut)',
        "order-products 只有三个写端点（POST / PATCH / DELETE 各一个）",
    ),
    # ---- ⑦ 权限点（服务端那一半） ----
    (
        "把 ORDER_EDIT 也发给货主：客户端门还在也没用 —— 门迟早会跟着权限点放宽",
        RBAC,
        '"shipper": frozenset(\n        {\n            Permission.ORDER_CREATE,',
        '"shipper": frozenset(\n        {\n            Permission.ORDER_EDIT,\n            Permission.ORDER_CREATE,',
        "shipper 改不动单据本体与货物（只有 ORDER_EDIT_CONTACT 那一个联系信息的门）",
    ),
    # ⚠️ CHG-0057（L-27）：货主那一扇补联系信息的门**必须**在 rbac 里开着 —— 少了它，
    #    详情页那颗「去补联系信息」按钮就成了"点下去必然 403"的摆件（用户点下去才知道不行）。
    (
        "把 ORDER_EDIT_CONTACT 从货主那一格里删掉（新开的那扇门又关上了）",
        RBAC,
        "            Permission.ORDER_EDIT_CONTACT,\n",
        "",
        "shipper 改不动单据本体与货物（只有 ORDER_EDIT_CONTACT 那一个联系信息的门）",
    ),
    (
        "dispatcher 那一格少了 ORDER_PRODUCT_EDIT：派单员从此改不了明细（点保存必然 403）",
        RBAC,
        "Permission.ORDER_PRODUCT_EDIT,\n",
        "",
        "dispatcher 有 ORDER_EDIT 与 ORDER_PRODUCT_EDIT",
    ),
    # ---- ⑧ 能改哪些状态：两边逐值对账 ----
    (
        "客户端的 LINE_EDITABLE 多一档（已送达也能改）：界面上画得出，后端必然 400",
        STATUS,
        'val LINE_EDITABLE: Set<String> = setOf("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED")',
        'val LINE_EDITABLE: Set<String> = setOf("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED", "DELIVERED")',
        "客户端的 LINE_EDITABLE 与后端 LINE_EDITABLE_STATUSES 逐值一致",
    ),
    (
        "后端把已送达也放开（客户端不变）：两边判据从此不一致，宽的那一边就是漏洞",
        PRODS,
        "LINE_EDITABLE_STATUSES = (\n    OrderStatus.PENDING_DISPATCH,\n    OrderStatus.DISPATCHED,\n    OrderStatus.ACCEPTED,\n)",
        "LINE_EDITABLE_STATUSES = (\n    OrderStatus.PENDING_DISPATCH,\n    OrderStatus.DISPATCHED,\n    OrderStatus.ACCEPTED,\n    OrderStatus.DELIVERED,\n)",
        "客户端的 LINE_EDITABLE 与后端 LINE_EDITABLE_STATUSES 逐值一致",
    ),
    (
        "EDITABLE 放宽到「在途三态 + 已送达」：地址电话能改一张已经送完的单",
        STATUS,
        'val EDITABLE: Set<String> = setOf("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED")',
        'val EDITABLE: Set<String> = setOf("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED", "DELIVERED")',
        "EDITABLE 逐值 = 在途三态（PENDING_DISPATCH / DISPATCHED / ACCEPTED）",
    ),
    (
        "后端把已撤销也放进可改状态（终态的单本来就不该再动）",
        PRODS,
        "LINE_EDITABLE_STATUSES = (\n    OrderStatus.PENDING_DISPATCH,\n    OrderStatus.DISPATCHED,\n    OrderStatus.ACCEPTED,\n)",
        "LINE_EDITABLE_STATUSES = (\n    OrderStatus.PENDING_DISPATCH,\n    OrderStatus.DISPATCHED,\n    OrderStatus.ACCEPTED,\n    OrderStatus.CANCELLED,\n)",
        "能改的状态里没有终态（已送达 / 已撤销 / 已退货）",
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
    """判据那一行是不是「这一条」：房规的形状是 `  [!!]   <标签>`。"""
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

    if refuse_if_injecting("订单详情页就地改单（CHG-0041）反向验证"):
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
