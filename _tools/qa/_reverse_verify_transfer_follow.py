#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CHG-0043（转货跟司机）判据 _check_transfer_follow.py 的**反向验证**。

## 为什么需要它
_check_transfer_follow.py 里那 52 条判据大半是 in src 的字面量与位置比对 —— 它们正常跑的时候当然
全绿，问题在于**它们是不是真的盯着东西**：判据写歪了（比对一段谁都不会动的字符串、位置锚点被一次
无害的换行改写绕开）、或者产品代码改坏了而判据恰好没看那一段，两种情况在正常跑的时候长得一模一样
（都是全绿）。这个脚本把 36 种真会有人这么改的破坏方式逐条注入进去，每条跑一次判据，要求：
① 判据必须红（rc != 0）；② 红的那几行里必须有**这一条**判据的标签。
判据用的是共用 Checker，失败行形状是「  [!!]   <标签>」。

## 这份注入表想守住的五件事（与判据同源）
1. **什么时候跟**：源单在司机手上（模块级常量 DRIVER_HOLDING_STATUSES）＋ 这次是**新开**的一张 ＋
   那张新单还没有司机 —— 三个条件缺一不可，而且要**在任何写之前**读意图（整单转空会把司机从源单上
   摘掉，晚一步就读不到人了）；
2. **怎么跟**：行先落盘 → 源单该作废的作废 → **才**派单 → 最后才对目标单的预占对账；
   派单**不拿 SAVEPOINT 兜**（兜不住：Session.rollback() 回滚整笔事务），失败即整笔失败；
   对账前还要再落一次盘（autoflush=False，否则对账会照着 want 再写一整笔 —— 真库探针逮到的第 4 个真 bug）；
3. **状态机**：命令层一句 status 都不写，派单只走 services/order_flow.py 的 assign_driver；
4. **通知口径**：跟上了发 orders.assigned（不是 created / edited）、注册表与领域地图都认领这一路、
   main.py 有人处理、两行审计都带上"这趟货归谁送"；
5. **契约与界面**：schema / 路由 / DTO / 抽屉 / 结果文案五处同名同义，跟上没跟上都要说清楚。

## 用法
* 直接跑：逐条注入 → 跑判据 → 立刻按字节还原 → 打印每条的结论。
* --list：只列注入点，不改任何文件。

## 规矩（照 _tools/qa/_reverse_verify_order_transfer.py）
1. 只按**字节**备份与还原，⛔ 不用 git checkout --（那会把别人未提交的改动一起抹掉）。
2. 还原后用 sha256 比对：不符就报 2，绝不「继续往下跑」。
3. 注入前先跑一次判据：干净状态下必须是绿的（红的话反向验证没有意义）。
4. 注入前做**锚点唯一性预检**：每条锚点在目标文件里必须恰好命中 1 次
   （0 次＝注入点腐烂了；>1 次＝可能打到别人身上，那是**假绿**）。
5. 任何一条腐烂都报出来，不许静默跳过。
6. 两条**文档**注入（认领表整条 / 登记表整行）用 re: 锚点：要删掉的是整段，而判据是
   「文档里还提不提 CHG-0043」这种存在性检查 —— 字面量锚点得把一整行一千多字的登记念一遍。

⚠️ 被硬中断（Ctrl-C / 断电）时，注入可能还留在文件里：
   python _tools/qa/_check_reverse_verify_anchors.py --restore

用法：python _tools/qa/_reverse_verify_transfer_follow.py
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
CHECK = ROOT / "_tools" / "qa" / "_check_transfer_follow.py"

CMD = "backend/app/commands/order.py"
REG = "backend/app/commands/registry.py"
API = "backend/app/api/v1/orders_assignment.py"
SCHEMA = "backend/app/schemas/order.py"
MAIN = "backend/app/main.py"
MAP = "docs/DOMAIN_BOUNDARIES.md"
SHEET = "android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderTransferSheet.kt"
DTO = "android/app/src/main/java/com/tapmoay/sorders/data/remote/dto/Dtos.kt"
VM = "android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailViewModel.kt"
CLAIM = "docs/AI_WORK_CLAIM.md"
README = "docs/changes/README.md"

# (说明，文件，原文，替换成，期望被哪条判据标签抓到)
# 说明那句话就是「真会有人这么改」的理由（照反向验证脚本的房规逐条写清）。
INJECTIONS: list[tuple[str, str, str, str, str]] = [
    (
        '去掉「这次是新开的一张」这个条件：并进目标货主手里那张既有单时也去派单 —— 那张单上压着别人的货，'
        '派给谁得派单员说了算',
        CMD,
        '    if follow_driver_id is not None and created and target.driver_id is None:',
        '    if follow_driver_id is not None and target.driver_id is None:',
        '触发条件是「源单在司机手上 + 这次是新开的一张 + 新单还没有司机」三合一',
    ),
    (
        '「货在司机手上」的常量里多塞一个终态：撤销的单也算"在他手上"，空壳单会被重新派出去',
        CMD,
        'DRIVER_HOLDING_STATUSES: tuple[OrderStatus, ...] = (\n    OrderStatus.DISPATCHED,\n    OrderStatus.ACCEPTED,\n)',
        'DRIVER_HOLDING_STATUSES: tuple[OrderStatus, ...] = (\n    OrderStatus.DISPATCHED,\n    OrderStatus.ACCEPTED,\n    OrderStatus.CANCELLED,\n)',
        '「货在司机手上」写成模块级常量，成员恰好 DISPATCHED / ACCEPTED',
    ),
    (
        '把多行条件改写成一行（无害的排版）：位置锚点「follow_driver_id = (」从此找不到了 —— '
        '意图读取早不早于第一处写就没人看着了，而这一条正是整单转空那条路的命门',
        CMD,
        '    follow_driver_id = (\n        int(order.driver_id)\n        if order.driver_id is not None and order.status in DRIVER_HOLDING_STATUSES\n        else None\n    )',
        '    follow_driver_id = int(order.driver_id) if order.driver_id is not None and order.status in DRIVER_HOLDING_STATUSES else None',
        '意图读取早于第一处写（整单转空会把司机从源单上摘掉，晚读就读不到了）',
    ),
    (
        '跟随取的是**操作人**的 id（谁按的按钮就把新单派给谁）：界面与单测全绿，货却到了另一个人的车上',
        CMD,
        '        driver = db.get(User, follow_driver_id)',
        '        driver = db.get(User, actor.id)  # 谁按的按钮就派给谁',
        '跟随取的是**源单的司机**，不是操作人',
    ),
    (
        '图省事把派单挪到行搬完之前：预占是在派单那一刻按整张单的现状写的，这时候写出去的是搬之前的数',
        CMD,
        '    # 审计要用的行快照：**先取**再动行（\x60db.delete\x60 之后主键读起来不一定还在）。',
        '    assign_driver(\n        db,\n        target,\n        db.get(User, follow_driver_id),\n        actor,\n        "先把单派出去，省得后面忘",\n    )\n\n    # 审计要用的行快照：**先取**再动行（\x60db.delete\x60 之后主键读起来不一定还在）。',
        '派单晚于落盘与明细失效（预占按搬完之后的现状写）',
    ),
    (
        '把存档点加回去（"兜一下更安全"）：assign_driver 在 CAS 失败那条路上自己 db.rollback()，'
        'SQLAlchemy 回滚的是**整笔事务**、存档点一起被放掉 —— 包了照样把已经搬好的行整段丢掉，'
        '而函数还会接着写审计与发件箱并 commit（真库探针实测过）',
        CMD,
        '            try:\n                assign_driver(\n                    db,\n                    target,\n                    driver,\n                    actor,\n                    f"这一趟货本来就在这位司机手上（源单 {order.order_no}），转货后跟随原司机派单",\n                )',
        '            try:\n                with db.begin_nested():\n                    assign_driver(\n                        db,\n                        target,\n                        driver,\n                        actor,\n                        f"这一趟货就在这位司机手上（源单 {order.order_no}），转货后跟随原司机派单",\n                    )',
        '派单**不拿** SAVEPOINT 兜（Session.rollback() 回滚整笔事务，存档点一起被放掉 —— 兜不住就别假装兜）',
    ),
    (
        '派不出去时静默降级（"别让派单员看见报错"）：库里留下一句"新订单待派单"、那张单却根本不存在',
        CMD,
        '            except ValueError as e:\n                raise CommandError(\n                    f"新单没能派给原司机（{e}）；这笔转货没有完成（源单没动、货也没搬），请重试",\n                    status_code=409,\n                ) from e',
        '            except ValueError as e:\n                follow_skipped = f"新单没有跟过去（{e}）"',
        '派不出去就是整笔失败：except ValueError 直接抛 CommandError(409)，并写明「这笔转货没有完成」',
    ),
    (
        '宽泛兜异常（except Exception）：已经 rollback 过、会话状态不明的这一次继续往下写审计与发件箱',
        CMD,
        '            except ValueError as e:',
        '            except Exception as e:  # noqa: BLE001',
        '不宽泛兜异常（except Exception 会让已经坏掉的会话继续往下写）',
    ),
    (
        '停用检查删掉：停用的司机被推去走「整笔失败」那条硬路 —— 明明是可预期的情形，却让整笔转货白做',
        CMD,
        '        elif not driver.is_active:\n            problem = "原来那位司机已经停用（离职或被删除）"',
        '        # 停用的也让他跟着吧（少挡一种情形）',
        '停用司机挡在前面（否则会被推去走「整笔失败」那条硬路）',
    ),
    (
        '降级不再带那句话回去：新单躺在待派单池里，界面上却什么都不说（用户以为什么都没发生）',
        CMD,
        '            follow_skipped = f"{problem}，新单没有跟过去，已放进待派单池，请重新指派一位司机"',
        '            follow_skipped = problem',
        '三种可预期的「跟不上」仍然只降级、不拦整笔转货（只如实带一句话回去）',
    ),
    (
        '跟上了却记的是司机 id（界面上会显示一串数字，司机自己都认不出那是谁）',
        CMD,
        '            followed_name = _user_label(driver)',
        '            followed_name = str(driver.id)',
        '跟上时记的是司机显示名，不是 id',
    ),
    (
        '跟随这条路自己写一句状态（状态机从此有第二个入口，而且是绕过 CAS 的那一个）',
        CMD,
        '            followed_name = _user_label(driver)',
        '            target.status = OrderStatus.DISPATCHED  # 省一层，免得依赖派单那边\n            followed_name = _user_label(driver)',
        '命令层不写状态（没有 target.status = / order.status = / update(Order)）',
    ),
    (
        '顺手把钱抄过去（付款方式 / 挂账单位）：转货只动货，两边却都多出一个谁也没要求过的结论',
        CMD,
        '            followed_name = _user_label(driver)',
        '            target.payment_method = order.payment_method  # 顺手把钱也抄过去\n            followed_name = _user_label(driver)',
        '跟随这条路不碰钱（转货不重算价格）',
    ),
    (
        '派单备注不点名源单号：司机那边看不出这趟货原来在哪张单上，出问题只能靠翻备注猜',
        CMD,
        '                    f"这一趟货本来就在这位司机手上（源单 {order.order_no}），转货后跟随原司机派单",',
        '                    "这一趟货本来就在这位司机手上，转货后跟随原司机派单",',
        '派单备注点名源单号（司机那边看得出这趟货原来在哪张单上）',
    ),
    (
        '两个跟随事实挪到触发之后才声明：某条分支下 TransferResult 根本没这两个名字，'
        '一条路走下来直接 NameError（而类型检查看不出来）',
        CMD,
        '    followed_name: str | None = None\n    follow_skipped: str | None = None\n    if follow_driver_id is not None and created and target.driver_id is None:',
        '    if follow_driver_id is not None and created and target.driver_id is None:\n        followed_name: str | None = None\n        follow_skipped: str | None = None',
        '两个跟随事实在触发之前就声明成 None（任何分支下 TransferResult 都有值）',
    ),
    (
        '在跟随之前又加一次目标单对账（"省得后面再算"）：同一个数被复核两遍，第二遍还会照着 want 再写一笔'
        '（真库探针实测：该占 4 件被写成 8 件）',
        CMD,
        '    followed_name: str | None = None\n    follow_skipped: str | None = None\n    if follow_driver_id is not None and created and target.driver_id is None:',
        '    _resync_stock_if_assigned(db, target, actor.id)\n    followed_name: str | None = None\n    follow_skipped: str | None = None\n    if follow_driver_id is not None and created and target.driver_id is None:',
        '目标单的预占对账仍然只有一处',
    ),
    (
        '把目标单的预占对账整段删掉（"派单那边已经写好了，不用再算一遍"）：目标单的占用从此没人复核，'
        '派单那一刻写的数错了也没人发现（真库探针实测：该占 4 件被写成 8 件）',
        CMD,
        '    #    （真库探针实测：新单该占 4 件，被写成 8 件）。\n    db.flush()\n    _resync_stock_if_assigned(db, target, actor.id)',
        '    #    （真库探针实测：新单该占 4 件，被写成 8 件）。\n    db.flush()',
        '派单早于目标单的预占对账（对账是复核，不该由它写占用）',
    ),
    (
        '跟上了也照样发 orders.created：司机那边收到的是"新订单待派单"，而这张单已经在他手上了',
        CMD,
        '    # 发件箱：与业务写**同一个事务**（outbox.enqueue 自己不 commit，由本层最后 commit 一次）。\n    outbox.enqueue(db, "orders.pending_pool_changed", {})',
        '    # 发件箱：与业务写**同一个事务**（outbox.enqueue 自己不 commit，由本层最后 commit 一次）。\n    outbox.enqueue(db, "orders.pending_pool_changed", {})\n    outbox.enqueue(db, "orders.created", {"order_id": int(target.id)})',
        '发件箱按「跟上了 → 新单 → 并进已派单的单」三分支排列',
    ),
    (
        'orders.assigned 带的是**源单**的 id 与司机：司机手机上的那条站内信指向一张不是他手上的单',
        CMD,
        '            db, "orders.assigned", {"driver_id": int(target.driver_id), "order_id": int(target.id)}',
        '            db, "orders.assigned", {"driver_id": int(order.driver_id), "order_id": int(order.id)}',
        'orders.assigned 带的是**目标单**的 id 与司机（不是源单的）',
    ),
    (
        '「进」那一行审计不再带跟随事实：货进来了，事后却查不出这趟货归谁送',
        CMD,
        '            "source_shipper_id": order.shipper_id,\n            "followed_driver": followed_name,',
        '            "source_shipper_id": order.shipper_id,',
        '两行审计都带上了跟随事实（out / in 各一次）',
    ),
    (
        '两行审计合成一行（少写一行）：转出那半截从此没有动作码，按动作码筛日志的人再也看不到它',
        CMD,
        '        order_id=target.id,\n        action=OperationAction.ORDER_TRANSFER,',
        '        order_id=target.id,\n        action=OperationAction.ORDER_LINE_UPDATE,',
        '两行审计本身还在（没有为了少写一行把它合成一行）',
    ),
    (
        '结果里两个跟随字段没填回去：界面拿不到事实，只能按 null 当"没这回事"',
        CMD,
        '        followed_driver_name=followed_name,',
        '        followed_driver_name=None,',
        '结果里两个跟随字段被真的填回去',
    ),
    (
        '把目标单对账前那一次 flush 删掉（"派单那边刚写完，看得见"）：会话是 autoflush=False，'
        'SELECT SUM 看不见还在会话里的预占流水，对账会照着 want 再写一整笔 —— 真库探针逮到的第 4 个真 bug',
        CMD,
        '    #    （真库探针实测：新单该占 4 件，被写成 8 件）。\n    db.flush()\n    _resync_stock_if_assigned(db, target, actor.id)',
        '    #    （真库探针实测：新单该占 4 件，被写成 8 件）。\n    _resync_stock_if_assigned(db, target, actor.id)',
        '派单之后、目标单对账之前又落了一次盘（autoflush=False：派单刚写的预占流水不落盘就 SUM 不到，会照着 want 再写一整笔 —— 真库探针实测的第 4 个真 bug）',
    ),
    (
        '注册表少声明 orders.assigned：发件箱照样发，下游按注册表对账就会漏掉这一路',
        REG,
        '            "orders.cancelled",\n            "orders.assigned",',
        '            "orders.cancelled",',
        '注册表声明的事件与实现里真发的逐字一致（五项，按集合比）',
    ),
    (
        '领域地图不再认领 orders.assigned：地图与实现两处形状不对称，谁发这个事件从此查不到',
        MAP,
        'events: orders.assigned, orders.created, orders.delivered, orders.cancelled, orders.recalled, orders.revoked, orders.edited, orders.driver_acked, orders.freight_updated, orders.pending_pool_changed, orders.navigation_filled',
        'events: orders.created, orders.delivered, orders.cancelled, orders.recalled, orders.revoked, orders.edited, orders.driver_acked, orders.freight_updated, orders.pending_pool_changed, orders.navigation_filled',
        '领域地图的订单域 events 行认领着 orders.assigned',
    ),
    (
        'main.py 的处理器改名（事件只声明不处理）：司机那边永远收不到"您有新的派单"这条站内信',
        MAIN,
        '    if event.event_type == "orders.assigned":',
        '    if event.event_type == "orders.assigned_legacy":',
        'main.py 有人接 orders.assigned（事件不是只声明不处理）',
    ),
    (
        'schema 的描述不再点名 CHG-0043：口径变化从此查不到出处（两个字段是怎么来的没人说得清）',
        SCHEMA,
        '        description="新开的那张单跟着源单的司机派了出去：这位司机的显示名字；没跟= null（CHG-0043）",',
        '        description="新开的那张单跟着源单的司机派了出去：这位司机的显示名字；没跟= null",',
        'OrderTransferOut 两个字段与命令层同名，且描述点名 CHG-0043',
    ),
    (
        '路由自己编一个值（不原样透出命令层的事实）：并单那条路上命令层给了实情，HTTP 层却把它抹成 null',
        API,
        '        followed_driver_name=result.followed_driver_name,',
        '        followed_driver_name=None if not result.created_target else result.followed_driver_name,',
        '路由原样透出两个字段（不吞、不自己编）',
    ),
    (
        '客户端 DTO 少一个 @SerialName：字段永远解析不出来，界面上那句原因永远是空的',
        DTO,
        '    @SerialName("follow_skipped_reason") val followSkippedReason: String? = null,',
        '    val followSkippedReason: String? = null,',
        '客户端 DTO 与后端 schema 同名同类型（缺省 null）',
    ),
    (
        '抽屉里那行只读说明换个标签：界面上不再说"新单归谁跑"，转货的人不知道新单会落在谁手上',
        SHEET,
        '                FormRow(label = "新单归谁跑") {',
        '                FormRow(label = "备注") {',
        '抽屉里有一行说明「新单归谁跑」，取值来自源单司机',
    ),
    (
        '抽屉只留一个分支（"跟原司机"那一支不再说）：明明会跟着原司机走，界面上一律说"进待派单池"',
        SHEET,
        '                        text = if (holder != null) "跟原司机 " + holder else "进待派单池",',
        '                        text = "进待派单池",',
        '两个分支都说清楚：跟原司机 / 进待派单池',
    ),
    (
        '解释句从 Hint 降到裸 Text：判据 _check_hints 的口径是"解释句必须走 Hint"，降级之后'
        '这一句在判据眼里就是普通数据，谁都挡不住它被改成带插值的动态文案',
        SHEET,
        '            Hint(\n                "填上的数量就是转出去的数量；留着不填的，原样不动；全填满就把原来那张作废。" +\n                    "原来那趟活儿在谁手上，新开的那张单就直接派给谁（并进他手上那张单时，就在那张单上加货）。"\n            )',
        '            Text(\n                "填上的数量就是转出去的数量；留着不填的，原样不动；全填满就把原来那张作废。" +\n                    "原来那趟活儿在谁手上，新开的那张单就直接派给谁（并进他手上那张单时，就在那张单上加货）。"\n            )',
        '静态规则写在 Hint 里（⛔ Hint 不许插值，具体人名走 FormRow）',
    ),
    (
        '结果文案不点名跟上的司机：转完只看到"已把 3 行货转给某某"，新单在谁手上一个字都不说',
        VM,
        '            r.followedDriverName != null -> "，新单已派给原司机 " + r.followedDriverName',
        '            r.followedDriverName != null -> ""',
        '结果文案用上两个回参字段（跟上了点名司机，没跟上把原因说出来）',
    ),
    (
        '碰掉 CHG-0042 的旧文案（"源单已撤销"）：货全转走了，派单员却以为原来那张单还在',
        VM,
        '            r.sourceCancelled -> head + "，源单已撤销（货全转走了）" + follow',
        '            r.sourceCancelled -> head + follow',
        'CHG-0042 那条「源单已撤销」的文案没被这次改动碰掉',
    ),
    (
        '认领表里这一条整段删掉（会话结束了却没登记）：别人接手时不知道这一条动过谁的状态机口径',
        CLAIM,
        're:### \\[2026-10-05 18:1x[^\\n]*\\n(?:[^\\n]*\\n)*?\\*\\*状态\\*\\*[^\\n]*\\n',
        '',
        'AI_WORK_CLAIM.md 留了状态行',
    ),
    (
        '登记表里这一行删掉（变更登记号在表里查不到）：CHG-0043 这一条从此没有编号可引用',
        README,
        're:\\| \x60CHG-0043\x60 \\| CHG \\|[^\\n]*\\n',
        '',
        'docs/changes/README.md 登记了这一条',
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

    if refuse_if_injecting("转货跟司机（CHG-0043）反向验证"):
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
