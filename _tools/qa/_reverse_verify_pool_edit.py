#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CHG-0040「改单只通知司机 / 选司机」判据 _check_pool_edit.py 的**反向验证**（注入破坏 → 判据必须抓住）。

为什么需要它：判据全绿只说明「现在是好的」，不说明「坏了会红」。这里把 54 种**真会有人这么改**的破坏
方式逐条注入进产品代码，每注入一条就跑一次判据，要求它 rc != 0，且失败行里出现那一条对应的判据标签
（判据用共用 Checker，失败行形如 "  [!!]   标签"）。

用法：
    python _tools/qa/_reverse_verify_pool_edit.py --list    # 只看注入点清单，一个字节都不动
    python _tools/qa/_reverse_verify_pool_edit.py           # 逐条注入 → 跑判据 → 立刻还原

规矩（照 _tools/qa/_reverse_verify_silent_release.py）：
  * 只按**字节**备份/还原，⛔ 全程不用 git checkout --（那只还原已跟踪文件，会吞掉别人的工作）；
  * 还原后校验 sha256，不符就报 2 让人来处理；
  * 注入前先跑一次判据：干净状态必须是绿的（红的说明判据/产品代码本身有问题，先修）；
  * 注入前先做**锚点唯一性预检**：锚点在文件里必须恰好命中 1 次 —— 命中 0 次＝注入点腐烂，
    命中 >1 次＝这条注入可能打到别人身上（判据看着抓住、其实没碰真正的代码 = 假绿）；
  * 任何一条注入点腐烂都报出来，不许静默跳过。

⚠️ 被硬中断（Ctrl+C / 杀进程 / 断电）会留下注入了 bug 的工作区：
    python _tools/qa/_check_reverse_verify_anchors.py --restore
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
CHECK = ROOT / "_tools" / "qa" / "_check_pool_edit.py"

PRODS = "backend/app/api/v1/order_products.py"
MSG = "backend/app/services/message_center.py"
PUSH = "backend/app/services/push_events.py"
MAIN = "backend/app/main.py"
ANDROID = "android/app/src/main/java/com/tapmoay/sorders/"
TRUST = ANDROID + "core/PushTrust.kt"
HUB = ANDROID + "core/RealtimeHub.kt"
POOL_VM = ANDROID + "ui/dispatcher/DispatcherPoolViewModel.kt"
POOL_UI = ANDROID + "ui/dispatcher/DispatcherPoolScreen.kt"

# (说明，文件，原文，替换成，期望被哪条判据标签抓到)
# 说明那句话就是「真会有人这么改」的理由（照反向验证脚本的房规逐条写清）。
INJECTIONS: list[tuple[str, str, str, str, str]] = [
    # ---- ① 明细三个写端点：通知司机 ----
    ("加行端点忘了通知司机（这一处漏了，改明细对司机就完全无感：列表不刷新、消息中心没一条）", PRODS,
     "    # 行加了 → 预占要跟着加，否则送达时这件货**永远不扣库**（见 resync_reservations 的说明）\n    db.flush()\n    _resync_stock_if_assigned(db, order, current.id)\n    _notify_driver_lines_changed(db, order)\n    db.commit()\n",
     "    # 行加了 → 预占要跟着加，否则送达时这件货**永远不扣库**（见 resync_reservations 的说明）\n    db.flush()\n    _resync_stock_if_assigned(db, order, current.id)\n    db.commit()\n",
     "三个写端点各通知一次（增 / 改 / 删）"),
    ("改行端点忘了通知司机（数量/单价改了司机却不知道）", PRODS,
     # CHG-0071 在改行端点的 flush 与 _resync 之间插了折扣重算块 ⇒ 锚点下移到今天真实存在的
     # 尾部正文；`@router.delete` 保证只命中改行那一段（⛔ 别为了迁就锚点去动产品代码）。
     "    _resync_stock_if_assigned(db, order, current.id)\n    _notify_driver_lines_changed(db, order)\n    db.commit()\n    db.refresh(op)\n    return op\n\n\n@router.delete",
     "    _resync_stock_if_assigned(db, order, current.id)\n    db.commit()\n    db.refresh(op)\n    return op\n\n\n@router.delete",
     "三个写端点各通知一次（增 / 改 / 删）"),
    ("删行端点忘了通知司机（司机到门口才发现少了一件货）", PRODS,
     # （同上：CHG-0071 插在 flush 之后 ⇒ 8 空格缩进的这三行才是今天删行路径的尾部正文）
     "        _resync_stock_if_assigned(db, order, current.id)\n        _notify_driver_lines_changed(db, order)\n    db.commit()\n",
     "        _resync_stock_if_assigned(db, order, current.id)\n    db.commit()\n",
     "三个写端点各通知一次（增 / 改 / 删）"),
    ("加行的通知挪到 commit 之后（事件先发、事务后落 ⇒ 事务回滚了司机却已经收到消息）", PRODS,
     "    db.flush()\n    _resync_stock_if_assigned(db, order, current.id)\n    _notify_driver_lines_changed(db, order)\n    db.commit()\n    db.refresh(op)\n    return op\n\n\n@router.get(\"/{line_id}\", response_model=OrderProductOut)",
     "    db.flush()\n    _resync_stock_if_assigned(db, order, current.id)\n    db.commit()\n    _notify_driver_lines_changed(db, order)\n    db.refresh(op)\n    return op\n\n\n@router.get(\"/{line_id}\", response_model=OrderProductOut)",
     "增：通知在预占对账之后、commit 之前（先对账、再通知、最后提交）"),
    ("改行的通知挪到 commit 之后", PRODS,
     "    _resync_stock_if_assigned(db, order, current.id)\n    _notify_driver_lines_changed(db, order)\n    db.commit()\n    db.refresh(op)\n    return op\n\n\n@router.delete",
     "    _resync_stock_if_assigned(db, order, current.id)\n    db.commit()\n    _notify_driver_lines_changed(db, order)\n    db.refresh(op)\n    return op\n\n\n@router.delete",
     "改：通知在预占对账之后、commit 之前（先对账、再通知、最后提交）"),
    ("删行的通知挪到 commit 之后", PRODS,
     "        _resync_stock_if_assigned(db, order, current.id)\n        _notify_driver_lines_changed(db, order)\n    db.commit()\n",
     "        _resync_stock_if_assigned(db, order, current.id)\n    db.commit()\n    _notify_driver_lines_changed(db, order)\n",
     "删：通知在预占对账之后、commit 之前（先对账、再通知、最后提交）"),
    ("「没派出去的单不发」这道闸写反了（待派单池里的单也发 ⇒ 一条指向空气的消息）", PRODS,
     "    if order.driver_id is None:\n        return\n    outbox.enqueue(db, \"orders.edited\"",
     "    if order.driver_id is not None:\n        return\n    outbox.enqueue(db, \"orders.edited\"",
     "没派出去的单不发（order.driver_id is None 直接返回）"),
    ("事件载荷里丢掉 driver_id（下游不知道发给谁，只能整条丢掉）", PRODS,
     "    outbox.enqueue(db, \"orders.edited\", {\"driver_id\": order.driver_id, \"order_id\": order.id})\n",
     "    outbox.enqueue(db, \"orders.edited\", {\"order_id\": order.id})\n",
     "按订单聚合发 orders.edited（载荷只带 driver_id + order_id）"),
    ("helper 里顺手 commit（业务写与事件不再同一个事务：发件箱的承诺破了）", PRODS,
     "    outbox.enqueue(db, \"orders.edited\", {\"driver_id\": order.driver_id, \"order_id\": order.id})\n",
     "    outbox.enqueue(db, \"orders.edited\", {\"driver_id\": order.driver_id, \"order_id\": order.id})\n    db.commit()\n",
     "不 commit（与本次业务写同一个事务 —— 发件箱的承诺）"),
    ("事件里塞上 shipper_id（下游浮点推送就可能顺手通知货主）", PRODS,
     "    outbox.enqueue(db, \"orders.edited\", {\"driver_id\": order.driver_id, \"order_id\": order.id})\n",
     "    outbox.enqueue(db, \"orders.edited\", {\"driver_id\": order.driver_id, \"order_id\": order.id, \"shipper_id\": order.shipper_id})\n",
     "载荷里没有 shipper_id（这条事件只对司机说）"),
    ("改明细时把「撤回」也发出去（货主那侧会惊动：这正是 CHG-0039 花力气避开的事）", PRODS,
     "    outbox.enqueue(db, \"orders.edited\", {\"driver_id\": order.driver_id, \"order_id\": order.id})\n",
     "    outbox.enqueue(db, \"orders.edited\", {\"driver_id\": order.driver_id, \"order_id\": order.id})\n    outbox.enqueue(db, \"orders.recalled\", {\"order_id\": order.id})\n",
     "明细路径里没有「撤回 / 召回」那种会惊动货主的事件"),
    # ---- ② 司机收到的站内信 ----
    ("站内信发给货主（司机什么也收不到，而货主被平白惊动一次）", MSG,
     "        recipient_id=driver_id,\n        category=\"order\",\n        type=\"order.edited\",\n",
     "        recipient_id=order.shipper_id,\n        category=\"order\",\n        type=\"order.edited\",\n",
     "收件人是司机本人（recipient_id=driver_id）"),
    ("消息类型写成自定义码（客户端按 order. 前缀刷新列表 ⇒ 这条消息不会触发重拉）", MSG,
     "        category=\"order\",\n        type=\"order.edited\",\n        title=\"订单信息有修改\",\n",
     "        category=\"order\",\n        type=\"order.changed\",\n        title=\"订单信息有修改\",\n",
     "消息类型是 order.edited（客户端按前缀 order. 刷新列表）"),
    ("标题改成看不出是什么事的码（司机在消息中心里认不出这条）", MSG,
     "        title=\"订单信息有修改\",\n",
     "        title=\"订单更新\",\n",
     "标题写「订单信息有修改」"),
    ("不念出来（司机正在跑这一单，改的是送到哪、送给谁、送几件）", MSG,
     "        payload={\"order_id\": order_id, \"order_no\": ono},\n        # 改单会改「送到哪、送给谁、送几件」——司机正在跑这一单，值得念出来\n        speech_important=True,\n",
     "        payload={\"order_id\": order_id, \"order_no\": ono},\n        # 改单会改「送到哪、送给谁、送几件」——司机正在跑这一单，值得念出来\n        speech_important=False,\n",
     "值得念出来（司机正在跑这一单，speech_important=True）"),
    ("正文改口说「已同步」（司机以为不用看，到门口才发现地址变了）", MSG,
     "        content=f\"订单 {ono} 的收货信息或货物明细有改动，出车前请打开订单详情核对一遍。\",\n",
     "        content=f\"订单 {ono} 的收货信息或货物明细已同步。\",\n",
     "正文不猜改了哪一处，只让他去详情核对（说错一处比不说更坏）"),
    ("幂等键只按订单（同一张单第二次改动被当成重复吞掉：司机只收到第一条）", MSG,
     "        idem_key=f\"order.edited\" + \":\" + str(order_id) + \":\" + str(driver_id) + \":\" + str(event_id),\n",
     "        idem_key=f\"order.edited\" + \":\" + str(order_id),\n",
     "幂等键带发件箱行号（同一张单第二次改动不能被当成重复吞掉）"),
    ("实时信号写成 order.edited（Android 那一支是 order.updated ⇒ 列表不刷新）", MSG,
     "    await emit_realtime(driver_id, {\"type\": \"order.updated\", \"order_id\": order_id})\n",
     "    await emit_realtime(driver_id, {\"type\": \"order.edited\", \"order_id\": order_id})\n",
     "实时信号是 order.updated（界面据此重拉）"),
    ("顺手也给货主补一条改单消息（用户明确不要：改单只让司机知道）", MSG,
     "    ono = order.order_no\n    n = create_message(\n",
     "    ono = order.order_no\n    await publish_order_edited_shipper(db, order.shipper_id, order_id)\n    n = create_message(\n",
     "这条消息里没有任何给货主的投递"),
    ("只发实时信号、不落站内信（就是这次要修的原始病：消息中心里什么都没有）", PUSH,
     "        await message_center.publish_order_edited_driver(db, driver_id, order_id, event_id=event_id)\n",
     "        await emit_realtime(driver_id, {\"type\": \"order.updated\", \"order_id\": order_id})\n",
     "它调的是刚才那条站内信（不是只发一句实时信号）"),
    ("把发件箱行号从签名里去掉（第二次改单的消息会被幂等键吞掉）", PUSH,
     "async def push_order_edited_to_driver(driver_id: int, order_id: int, *, event_id: int = 0) -> None:\n",
     "async def push_order_edited_to_driver(driver_id: int, order_id: int) -> None:\n",
     "event_id 一路传到幂等键（default 0 只是给老调用点留的）"),
    ("main.py 不把发件箱行号传下去（同一次故障的下游半边）", MAIN,
     "        await push_events.push_order_edited_to_driver(\n            int(event.payload.get(\"driver_id\") or 0),\n            int(event.payload.get(\"order_id\") or 0),\n            event_id=int(event.id or 0),\n        )\n",
     "        await push_events.push_order_edited_to_driver(\n            int(event.payload.get(\"driver_id\") or 0),\n            int(event.payload.get(\"order_id\") or 0),\n        )\n",
     "main.py 把发件箱行号一起传下去（event_id=event.id）"),
    # ---- ③ Android 认这两个事件 ----
    ("PushTrust 的订单事件清单里不留 order.edited（前端把这条推送当陌生类型丢掉）", TRUST,
     "        // CHG-0040：派单员改了这张单的收货信息或货物明细 → 司机收到一条站内信\n        \"order.edited\",\n",
     "        // CHG-0040：派单员改了这张单的收货信息或货物明细 → 司机收到一条站内信\n",
     "PushTrust 的订单事件清单里有 \"order.edited\""),
    ("RealtimeHub 里没有 order.updated 这一支（后端发了没人认：不刷新）", HUB,
     "                    \"order.updated\" -> _refreshOrders.tryEmit(Unit)\n",
     "                    \"order.edit\" -> _refreshOrders.tryEmit(Unit)\n",
     "RealtimeHub 有 \"order.updated\" 分支（以前一支都没有 ⇒ 后端发了没人认）"),
    ("改单顺手播报出来（改单不是新任务，半夜念一句「订单被改了」）", HUB,
     "                    \"order.updated\" -> _refreshOrders.tryEmit(Unit)\n",
     "                    \"order.updated\" -> { _refreshOrders.tryEmit(Unit); announce(\"订单被改了\") }\n",
     "这一支只刷新、不播报（改单不是新任务，别半夜念出来）"),
    # ---- ④ 选司机 ----
    ("筛选没接到列表上（画的是全部组 ⇒ 选了人还是看全部，筛选假生效）", POOL_VM,
     "    val visibleGroups: List<DriverOrderGroup>\n        get() = dispatchedGroups.filter { driverFilterId == null || it.driverId == driverFilterId }\n",
     "    val visibleGroups: List<DriverOrderGroup>\n        get() = dispatchedGroups\n",
     "筛选只筛「已完成派单」的组，不动分组本身"),
    ("名册没拉到时编一个数（「全部司机（0 位）」是假话）", POOL_VM,
     "            return if (drivers.isEmpty()) \"全部司机\" else \"全部司机（\" + drivers.size + \" 位）\"\n",
     "            return \"全部司机（\" + drivers.size + \" 位）\"\n",
     "名册没拉到时不许编数字（「全部司机」/「全部司机（N 位）」两种说法）"),
    ("拉已完成档时不补名册（抽屉永远是空的，而空抽屉看起来跟「这些司机都没有单」一样）", POOL_VM,
     "            // 选司机那颗要用司机名册：从订单详情借进来的这份 VM 只在打开派单弹窗时才拉\n            // 名册（`openAssign`），不在这里补一句的话筛选抽屉永远是空的 —— 而空抽屉\n            // 看起来跟「这些司机都没有单」一模一样（静默失效）。\n            if (drivers.isEmpty()) loadDrivers()\n",
     "            // 选司机那颗要用司机名册：从订单详情借进来的这份 VM 只在打开派单弹窗时才拉\n            // 名册（`openAssign`），不在这里补一句的话筛选抽屉永远是空的 —— 而空抽屉\n            // 看起来跟「这些司机都没有单」一模一样（静默失效）。\n",
     "那句话在 loadDispatched 里（不是别处）"),
    ("触发行不分档（待派档也顶一颗「司机」，点开却是空的）", POOL_UI,
     "            if (vm.tab == DispatcherPoolViewModel.TAB_COMPLETED) {\n                PersonTriggerRow(\n",
     "            if (true) {\n                PersonTriggerRow(\n",
     "触发行只在已完成那一档出现，标签写「司机」"),
    ("触发行自己写一份（不用共用件 ⇒ 形态与其它页面跑偏）", POOL_UI,
     "                PersonTriggerRow(\n                    icon = Icons.Default.Person,\n                    color = MaterialTheme.colorScheme.tertiary,\n                    label = \"司机\",\n",
     "                PersonRow(\n                    icon = Icons.Default.Person,\n                    color = MaterialTheme.colorScheme.tertiary,\n                    label = \"司机\",\n",
     "触发行用的是共用件 PersonTriggerRow"),
    ("抽屉改成底部弹层（用户明确要的是「左边侧边栏」）", POOL_UI,
     "    ModalNavigationDrawer(\n",
     "    ModalBottomSheet(\n",
     "是左侧抽屉（ModalNavigationDrawer + ModalDrawerSheet）"),
    ("左栏自己写一份车型分档（不用 MasterRail）", POOL_UI,
     "                    MasterRail(\n",
     "                    KindRail(\n",
     "左栏车型分档用共用件 MasterRail"),
    ("右栏自己写一份名单（不用 PersonDrawer）", POOL_UI,
     "                        PersonDrawer(\n",
     "                        NameList(\n",
     "右栏名单用共用件 PersonDrawer + PersonOption"),
    ("搜索只看名字（司机重名时找不到人，而唯一实现 core/UserSearch.kt 就在手边）", POOL_UI,
     "                                .filter { d -> UserSearch.matches(vm.driverQuery, d.fullName, d.phone) }\n",
     "                                .filter { d -> d.fullName.contains(vm.driverQuery) }\n",
     "搜索认名字与手机号（唯一实现 core/UserSearch.kt）"),
    ("「全部司机」那一颗没了（选了人就再也回不到全部）", POOL_UI,
     "                            allLabel = \"全部司机\",\n",
     "                            allLabel = \"所有司机\",\n",
     "默认「全部司机」一颗（allLabel）"),
    ("抽屉关掉时状态不收（下次点触发行「打不开」：这正是本项目最讨厌的静默失效）", POOL_UI,
     "    LaunchedEffect(drawer.currentValue) {\n        if (drawer.currentValue == DrawerValue.Closed && vm.showDriverPicker) vm.showDriverPicker = false\n    }\n",
     "",
     "抽屉滑回去时状态跟着收（否则下次点触发行打不开）"),
    ("列表直接画全部组（筛选完全失效，而且看不出是坏的）", POOL_UI,
     "        vm.visibleGroups.forEach { group ->\n",
     "        vm.dispatchedGroups.forEach { group ->\n",
     "列表画的是筛过的组 vm.visibleGroups"),
    ("筛空说成真空的话（「这位司机手上没单」被读成「这些天白干了」）", POOL_UI,
     "                EmptyView(\"这位司机现在没有在途的单\", Modifier.fillMaxWidth().padding(top = 40.dp))\n",
     "                EmptyView(\"还没有派给司机的单\", Modifier.fillMaxWidth().padding(top = 40.dp))\n",
     "筛空与真空说两句不同的话"),
    # ---- ⑤ 改单 ----
    ("改单时把内部备注清空（司机可见的内部备注被这一层顺手抹掉）", POOL_VM,
     "                        internalNotes = o.internalNotes,\n",
     "                        internalNotes = \"\",\n",
     "内部备注原样带回去（这一层不改它）"),
    ("改完不说司机会收到消息（用户要的正是「司机会收到消息」这件事）", POOL_VM,
     "                actionResult = \"已经改好，司机那边会收到一条消息\"\n",
     "                actionResult = \"已经改好\"\n",
     "成功提示点名司机（用户要的就是「司机会收到消息」）"),
    ("防连点被摘（一次网络往返期间再点一次会改两遍，司机收到两条）", POOL_VM,
     "        InputRules.phoneError(editBossPhone.trim())?.let { editError = it; return }\n        if (editBusy) return\n",
     "        InputRules.phoneError(editBossPhone.trim())?.let { editError = it; return }\n",
     "防连点（一次改动进行中不再发第二次）"),
    ("明细不重拉，拿订单详情里那份（不是同一个类型，也拿不到行 id）", POOL_VM,
     "            editLines = container.repo.orderProductLines(orderId)\n",
     "            editLines = container.repo.orderDetail(orderId).orderProducts\n",
     "明细从服务端重拉（fetchEditLines + orderProductLines）"),
    ("保存一件货时只报单价（后端按旧数量重算行金额）", POOL_VM,
     "                    OrderProductUpdateRequest(quantity = qty, unitPrice = price),\n",
     "                    OrderProductUpdateRequest(unitPrice = price),\n",
     "数量与单价一起报（只报单价会按旧数量重算行金额）"),
    ("数量不先挡（填 0 或负数发给后端，错误信息变成看不懂的话）", POOL_VM,
     "        if (qty == null || qty <= 0) {\n",
     "        if (qty == null) {\n",
     "数量必须是大于 0 的整数（本地先挡一道）"),
    ("单价不先挡（随手写的值直接发出去）", POOL_VM,
     "        if (price.isEmpty() || price.toDoubleOrNull() == null) {\n",
     "        if (price.isEmpty()) {\n",
     "单价必须是数字（本地先挡一道）"),
    ("专属价的守卫丢掉货主比较（规则还没到也认 ⇒ 按默认价报给谈好价的批发商就是多收他的钱）", POOL_VM,
     "        if (sid == null || priceRulesShipper != sid) return p.defaultUnitPrice\n",
     "        if (sid == null) return p.defaultUnitPrice\n",
     "专属价的守卫：这份规则不属于这一单货主就回退默认价"),
    ("拉专属价失败时不清状态（把上一单货主的规则继续用在这一单上）", POOL_VM,
     "                priceRules = emptyMap()\n                priceRulesShipper = null\n",
     "                priceRulesShipper = null\n",
     "拉专属价失败时不假装「没有专属价」（清空 + 置 null）"),
    ("改单失败原因不画出来（点了保存没反应，用户只能再点一次）", POOL_UI,
     "            FormTextAreaRow(\n                \"备注\",\n                vm.editRemark,\n                { vm.editRemark = it },\n                placeholder = \"选填 · 给司机看的一句话\",\n            )\n            FormErrorLine(vm.editError)\n",
     "            FormTextAreaRow(\n                \"备注\",\n                vm.editRemark,\n                { vm.editRemark = it },\n                placeholder = \"选填 · 给司机看的一句话\",\n            )\n",
     "失败原因画在弹层里（FormErrorLine，不是整页 ErrorView）"),
    ("「改完只通知司机」这句承诺被改口（口径消失，下一个人就会照它写）", POOL_UI,
     "                \"改完只通知司机，货主端不会有任何提醒。\",\n",
     "                \"改完会通知司机和货主。\",\n",
     "逐字承诺货主无感（与「退回池子」同一个口径）"),
    ("「加一件货」入口没了（明细只能改不能加）", POOL_UI,
     "            TextButton(onClick = { vm.showLinePicker = true }) { Text(\"加一件货\") }\n",
     "",
     "有「加一件货」入口（拉选品件）"),
    ("明细行不可点（只能看不能改）", POOL_UI,
     "                        TextButton(onClick = { vm.openLineEdit(line) }) { Text(\"改\") }\n",
     "",
     "明细逐行可改（openLineEdit）"),
    ("数量或单价少一个框（改数量就得删了重加）", POOL_UI,
     "                \"单价（元）\",\n",
     "                \"价格\",\n",
     "数量与单价都能改"),
    ("删这件货不带警示色（破坏性动作长得跟普通按钮一样）", POOL_UI,
     "                    Text(\"删掉这件货\", color = MaterialTheme.colorScheme.error)\n",
     "                    Text(\"删掉这件货\")\n",
     "删这件货在左边且是警示色（与卡片上「退回池子」同一个规矩）"),
    ("删这件货不接 VM（点了没反应）", POOL_UI,
     "                TextButton(onClick = { vm.deleteLine() }) {\n",
     "                TextButton(onClick = { vm.closeLineEdit() }) {\n",
     "删这件货走 vm.deleteLine()"),
    ("卡片上把「编辑」摘掉（用户要的「全部都可以更改」没有入口）", POOL_UI,
     "                    extra = {\n                        TextButton(onClick = { vm.openEdit(order) }) { Text(\"编辑\") }\n                    },\n",
     "",
     "卡片右侧「编辑」（编辑类动作在右：用户 2026-09-22 定的惯用手规矩）"),
    ("把「退回池子」与「编辑」换边（退回变成右边，破坏性动作放到了顺手的一侧）", POOL_UI,
     "                    leading = {\n                        TextButton(onClick = { vm.openRelease(order.id) }) {\n                            Text(\"退回池子\", color = MaterialTheme.colorScheme.error)\n                        }\n                    },\n                    // 编辑 = 编辑类动作 → 右边（用户 2026-09-22：「编辑一定在右边，惯用手是右手」）\n                    extra = {\n                        TextButton(onClick = { vm.openEdit(order) }) { Text(\"编辑\") }\n                    },\n",
     "                    leading = {\n                        TextButton(onClick = { vm.openEdit(order) }) { Text(\"编辑\") }\n                    },\n                    // 编辑 = 编辑类动作 → 右边（用户 2026-09-22：「编辑一定在右边，惯用手是右手」）\n                    extra = {\n                        TextButton(onClick = { vm.openRelease(order.id) }) {\n                            Text(\"退回池子\", color = MaterialTheme.colorScheme.error)\n                        }\n                    },\n",
     "左侧仍是「退回池子」（反向动作在左）"),
    # ---- ⑥ 反过来：给货主发消息这条路本身 ----
    ("顺手写一条「改单通知货主」（这条边界一旦有了，CHG-0039 那套静默口径就白做了）", MSG,
     "async def publish_order_recalled_shipper(db: Session, shipper_id: int, order_id: int) -> None:\n",
     "async def publish_order_edited_shipper(db: Session, shipper_id: int, order_id: int) -> None:\n    return\n\n\nasync def publish_order_recalled_shipper(db: Session, shipper_id: int, order_id: int) -> None:\n",
     "没有 publish_order_edited_shipper（改单不许给货主发消息）"),
    ("事件载荷带上 shipper_id（下游只要照着 payload 取收件人就会发给货主）", PRODS,
     "    outbox.enqueue(db, \"orders.edited\", {\"driver_id\": order.driver_id, \"order_id\": order.id})\n",
     "    outbox.enqueue(db, \"orders.edited\", {\"driver_id\": order.driver_id, \"order_id\": order.id, \"shipper_id\": order.shipper_id})\n",
     "orders.edited 的载荷里从不带 shipper_id"),
    ("抽屉默认落在空的「未设置车型」档（名册里明明有 25 个人，点开抽屉第一眼却是「这一档还没有司机」——2026-10-05 实机撞上的就是它）", POOL_UI,
     "        mutableStateOf(if (shownKinds.contains(cur)) cur else shownKinds.firstOrNull() ?: \"\")\n",
     "        mutableStateOf(cur)\n",
     "抽屉默认落在「真的有人」的档（空档当默认 = 点开就是空名单）"),
    ("明细行的金额绕开显示漏斗（把后端 Numeric(14,4) 的 60.0000 直接印在卡片上——2026-10-05 实机看到的就是它）", POOL_UI,
     "                                \"\u00d7\" + line.quantity + line.unit + \" \u00b7 \u00a5\" + trimMoneyZeros(line.unitPrice),\n",
     "                                \"\u00d7\" + line.quantity + line.unit + \" \u00b7 \u00a5\" + line.unitPrice,\n",
     "明细行的单价过了金额显示漏斗"),
    ("价框预填丢了 trimMoneyZeros（60.0000 原样填进可编辑价框，用户得先删四个 0 才能改价）", POOL_VM,
     "        linePrice = trimMoneyZeros(line.unitPrice)\n",
     "        linePrice = line.unitPrice\n",
     "价框预填走 trimMoneyZeros"),
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_check() -> tuple[int, str]:
    """跑判据：返回 (退出码, stdout + stderr)。"""
    proc = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
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
    """判据那一行是不是「这一条」：房规的形状是 `  [!!]   <标签>`。

    `want` 允许省掉标签开头的 `⛔ `（凡是被红线点名的那类标签都带它）——
    2026-10-05 实测：want 写短了就等于**反向验证静默空过**，看着是红的、其实没认出来。
    """
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

    if refuse_if_injecting("改单只通知司机 / 选司机（CHG-0040）反向验证"):
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
    print("✅ %d/%d 种破坏方式被抓住 —— 判据在这 %d 个点上都不是空转的。" % (caught, len(INJECTIONS), len(INJECTIONS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
