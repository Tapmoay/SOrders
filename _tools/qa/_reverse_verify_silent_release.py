#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CHG-0039「静默退回派单池」判据 _check_silent_release.py 的**反向验证**（注入破坏 → 判据必须抓住）。

为什么需要它：判据全绿只说明「现在是好的」，不说明「坏了会红」。这里把 42 种**真会有人这么改**的破坏
方式逐条注入进产品代码，每注入一条就跑一次判据，要求它 rc != 0，且失败行里出现那一条对应的判据标签
（判据用共用 Checker，失败行形如 "  [!!]   标签"）。

用法：
    python _tools/qa/_reverse_verify_silent_release.py --list    # 只看注入点清单，一个字节都不动
    python _tools/qa/_reverse_verify_silent_release.py           # 逐条注入 → 跑判据 → 立刻还原

规矩（照 _tools/qa/_reverse_verify_assign_entry.py）：
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
CHECK = ROOT / "_tools" / "qa" / "_check_silent_release.py"

FLOW = "backend/app/services/order_flow.py"
ASSIGN = "backend/app/api/v1/orders_assignment.py"
RESP = "backend/app/services/order_response.py"
QUERY = "backend/app/api/v1/orders_query.py"
MODEL = "backend/app/models/order.py"
ENUMS = "backend/app/models/enums.py"
REGISTRY = "backend/app/commands/registry.py"
COVERAGE = "backend/app/core/capability_audit_coverage.py"
BOOTSTRAP = "backend/app/core/schema_bootstrap.py"
MIG = "backend/app/migrations/022_shipper_status_hold.py"
ANDROID = "android/app/src/main/java/com/tapmoay/sorders/"
APIS = ANDROID + "data/remote/api/Apis.kt"
POOL_VM = ANDROID + "ui/dispatcher/DispatcherPoolViewModel.kt"
POOL_UI = ANDROID + "ui/dispatcher/DispatcherPoolScreen.kt"
REPORT = ANDROID + "ui/dispatcher/ReportCenter.kt"

# (说明，文件，原文，替换成，期望被哪条判据标签抓到)
# 说明那句话就是「真会有人这么改」的理由（照反向验证脚本的房规逐条写清）。
INJECTIONS: list[tuple[str, str, str, str, str]] = [
    ("服务层 CAS 现读 order.status（CAS 之后它已经是 PENDING_DISPATCH ⇒ 冻结值变成「派单中」，货主一眼看穿）", FLOW,
     "            shipper_status_hold=shipper_status_hold,\n",
     "            shipper_status_hold=order.status,\n",
     "CAS 里带上冻结值"),
    ("冻结值干脆不记（写 None ⇒ 退回后货主立刻看到「派单中」）", FLOW,
     "    shipper_status_hold = order.status\n",
     "    shipper_status_hold = None\n",
     "冻结值在 CAS 之前取"),
    ("真状态不回到派单池（留在 DISPATCHED ⇒ 池子里根本没有这一单，「退回」是假的）", FLOW,
     "            status=OrderStatus.PENDING_DISPATCH,\n            # 冻结货主可见状态（CHG-0039）：只对货主出参生效，派单员/司机看到的都是真实状态。\n",
     "            status=OrderStatus.DISPATCHED,\n            # 冻结货主可见状态（CHG-0039）：只对货主出参生效，派单员/司机看到的都是真实状态。\n",
     "真状态回到 PENDING_DISPATCH"),
    ("前置状态门被摘（已送达/已撤销的单也能被退回池子）", FLOW,
     "    if order.status not in allowed:\n        raise ValueError(\"仅「已派单/已接单」订单可退回派单池\")\n",
     "",
     "状态门不满足时抛 ValueError"),
    ("CAS 抢占失败不回滚（失败后 session 里还留着半截事务，后面谁用谁脏）", FLOW,
     "    if claimed.rowcount != 1:\n        db.rollback()\n        raise ValueError(\"这张单刚刚被别的操作改过（可能已送达/已撤销），请刷新后再退回\")\n",
     "    if claimed.rowcount != 1:\n        raise ValueError(\"这张单刚刚被别的操作改过（可能已送达/已撤销），请刷新后再退回\")\n",
     "CAS 抢占失败要回滚"),
    ("逐单覆盖值不清（下一任司机按上一任的数字拿钱 —— 钱口径账错）", FLOW,
     "            # 冻结货主可见状态（CHG-0039）：只对货主出参生效，派单员/司机看到的都是真实状态。\n            shipper_status_hold=shipper_status_hold,\n            driver_id=None,\n            dispatched_at=None,\n            driver_acknowledged_at=None,\n            # ⚠️ 逐单覆盖值一起清掉（理由见 \x60recall_dispatch\x60 里那段，同一条账错）。\n            driver_piece_amount=None,\n            driver_commission_rate=None,\n",
     "            # 冻结货主可见状态（CHG-0039）：只对货主出参生效，派单员/司机看到的都是真实状态。\n            shipper_status_hold=shipper_status_hold,\n            driver_id=None,\n            dispatched_at=None,\n            driver_acknowledged_at=None,\n            # ⚠️ 逐单覆盖值一起清掉（理由见 \x60recall_dispatch\x60 里那段，同一条账错）。\n",
     "清掉司机与逐单覆盖值"),
    ("不释放这一单占用的库存（退回后库存还被那张单占着）", FLOW,
     "    db.refresh(order)\n    auto_stock_release(db, order, operator.id)\n    write_log(\n        db,\n        operator_id=operator.id,\n        order_id=order.id,\n        action=OperationAction.ORDER_RELEASE_SILENT,\n",
     "    db.refresh(order)\n    write_log(",
     "释放这一单占用的库存"),
    ("审计码并回 ORDER_RECALL（审计里再也分不出「会通知货主」和「静默」）", FLOW,
     "        action=OperationAction.ORDER_RELEASE_SILENT,\n",
     "        action=OperationAction.ORDER_RECALL,\n",
     "落自己的审计码"),
    ("审计载荷不记被收回的司机（事后查不出是谁的货被退回去了）", FLOW,
     "            \"released_driver_id\": released_driver_id,\n",
     "            \"driver_id\": released_driver_id,\n",
     "审计里记下被收回的司机与冻结值"),
    ("服务层顺手把货主事件也发了（静默线当场破功）", FLOW,
     "    db.refresh(order)\n    auto_stock_release(db, order, operator.id)\n    write_log(\n        db,\n        operator_id=operator.id,\n        order_id=order.id,\n        action=OperationAction.ORDER_RELEASE_SILENT,\n",
     "    outbox.enqueue(db, \"orders.recalled\", {\"order_id\": order.id})\n    db.refresh(order)\n    auto_stock_release(db, order, operator.id)\n    write_log(\n        db,\n        operator_id=operator.id,\n        order_id=order.id,\n        action=OperationAction.ORDER_RELEASE_SILENT,\n",
     "不发货主事件 orders.recalled"),
    ("assign_driver 不再解冻（重派出去的单，货主还看到上一轮的旧状态）", FLOW,
     "        .values(status=OrderStatus.DISPATCHED, driver_id=driver.id, dispatched_at=_now(), shipper_status_hold=None)\n",
     "        .values(status=OrderStatus.DISPATCHED, driver_id=driver.id, dispatched_at=_now())\n",
     "assign_driver 的 CAS 把冻结值写回 NULL"),
    ("release_dispatch 被改名（端点/注册表/判据全指空）", FLOW,
     "def release_dispatch(\n",
     "def release_dispatch_silent(\n",
     "release_dispatch 存在"),
    ("端点权限换成派单权限（静默退回变成另一个权限点的事）", ASSIGN,
     "    current: User = Depends(require_permission(Permission.ORDER_RECALL)),\n) -> OrderOut:\n    \"\"\"把一张已派出去的单**静默**退回派单池（CHG-0039，2026-10-05 用户要求）。\n",
     "    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),\n) -> OrderOut:\n    \"\"\"把一张已派出去的单**静默**退回派单池（CHG-0039，2026-10-05 用户要求）。\n",
     "退回端点沿用 ORDER_RECALL 权限"),
    ("旧司机 id 不再抓（被收回的司机收不到 orders.revoked，手里那张单还在）", ASSIGN,
     "    old_driver_id = order.driver_id\n    try:\n        release_dispatch(db, order, current, body.reason)\n",
     "    old_driver_id = None\n    try:\n        release_dispatch(db, order, current, body.reason)\n",
     "旧司机 id 在动作之前抓"),
    ("端点不再通知被收回的司机（他的列表里那张单永远掉不掉）", ASSIGN,
     "    if old_driver_id:\n        outbox.enqueue(\n            db,\n            \"orders.revoked\",\n            {\"driver_id\": old_driver_id, \"order_id\": order_id, \"reason\": body.reason},\n        )\n",
     "    if old_driver_id:\n        pass\n",
     "退回端点发 orders.revoked"),
    ("端点把货主事件塞回来（货主收到「订单被撤回」提醒 —— 静默彻底破功）", ASSIGN,
     "    if old_driver_id:\n        outbox.enqueue(\n            db,\n            \"orders.revoked\",\n            {\"driver_id\": old_driver_id, \"order_id\": order_id, \"reason\": body.reason},\n        )\n    outbox.enqueue(db, \"orders.pending_pool_changed\", {})\n",
     "    if old_driver_id:\n        outbox.enqueue(\n            db,\n            \"orders.revoked\",\n            {\"driver_id\": old_driver_id, \"order_id\": order_id, \"reason\": body.reason},\n        )\n    outbox.enqueue(db, \"orders.recalled\", {\"order_id\": order_id, \"reason\": body.reason})\n    outbox.enqueue(db, \"orders.pending_pool_changed\", {})\n",
     "退回端点不发 orders.recalled"),
    ("新列不进模型（列成了孤儿，谁也读不到）", MODEL,
     "    shipper_status_hold: Mapped[OrderStatus | None] = mapped_column(Enum(OrderStatus), nullable=True)\n",
     "",
     "orders.shipper_status_hold 在模型里"),
    ("schema_bootstrap 也去建这列（同一件事两个来源 —— 本项目头号忌讳）", BOOTSTRAP,
     "                    conn.execute(text(enum_repair_ddl(table_name, column)))\n",
     "                    if column.name == \"shipper_status_hold\":\n                        conn.execute(text(enum_repair_ddl(table_name, column)))\n",
     "core/schema_bootstrap.py 里一次都不提它"),
    ("迁移版本号与文件名不一致（_check_migrations 也会红）", MIG,
     "VERSION = 22\n",
     "VERSION = 21\n",
     "版本号与文件名一致"),
    ("迁移写死 MySQL 方言（SQLite 上后端起不来）", MIG,
     "    if engine.dialect.name == \"sqlite\":\n",
     "    if engine.dialect.name == \"mysql\":\n",
     "按方言取类型名"),
    ("迁移丢了「列已在就返回」（重跑一次就炸）", MIG,
     "    if COLUMN in {c[\"name\"] for c in insp.get_columns(TABLE)}:\n        return\n",
     "",
     "可重跑：先判表在不在"),
    ("迁移手写第二份六档清单（与 models/enums.py 漂移的开始）", MIG,
     "    values = \", \".join(f\"'{s.value}'\" for s in OrderStatus)\n",
     "    values = \"'PENDING_DISPATCH', 'DISPATCHED', 'ACCEPTED', 'DELIVERED', 'CANCELLED', 'RETURNED'\"\n",
     "取值从 models/enums.py::OrderStatus 现算"),
    ("审计码并回 ORDER_RECALL（两个动作共用一个码值）", ENUMS,
     "    ORDER_RELEASE_SILENT = \"ORDER_RELEASE_SILENT\"\n",
     "    ORDER_RELEASE_SILENT = \"ORDER_RECALL\"\n",
     "OperationAction 有 ORDER_RELEASE_SILENT"),
    ("注册表把 impl 指回召回（命令指向会通知货主的那个实现）", REGISTRY,
     "        impl=\"services.order_flow:release_dispatch\",\n",
     "        impl=\"services.order_flow:recall_dispatch\",\n",
     "它指向 services.order_flow:release_dispatch"),
    ("注册表 events 加回货主事件（登记表说它会提醒货主）", REGISTRY,
     "        events=(\"orders.revoked\", \"orders.pending_pool_changed\"),\n",
     "        events=(\"orders.revoked\", \"orders.recalled\", \"orders.pending_pool_changed\"),\n",
     "这条命令的 events 恰好两条"),
    ("能力审计覆盖表退回一个码（新动作码没人认领）", COVERAGE,
     "    'order:recall': ('ORDER_RECALL', 'ORDER_RELEASE_SILENT'),\n",
     "    'order:recall': ('ORDER_RECALL',),\n",
     "能力审计覆盖表里 order:recall 认下两个动作码"),
    ("报告中心不再给这个码中文标签（审计列表里出现裸英文码）", REPORT,
     "    \"ORDER_RELEASE_SILENT\" -> \"退回派单池（货主无感）\"\n",
     "",
     "报告中心给这个码中文标签"),
    ("出参不再覆写（货主直接看到真实状态「派单中」）", RESP,
     "            data[\"status\"] = shipper_visible_status_of(order)\n",
     "            data[\"status\"] = order.status.value\n",
     "货主的 status 只从 shipper_visible_status_of 出去"),
    ("覆写条件放宽（没冻结过的单也被改写）", RESP,
     "    if order.status == OrderStatus.PENDING_DISPATCH and order.shipper_status_hold is not None:\n",
     "    if order.status == OrderStatus.PENDING_DISPATCH:\n",
     "只有真状态是 PENDING_DISPATCH 且冻结值非空时才覆写"),
    ("档位 SQL 只剩一支（被静默退回的单从货主「已派单」档里消失）", RESP,
     "    return or_(\n        and_(Order.shipper_status_hold.is_(None), Order.status == status_filter),\n        and_(\n            Order.shipper_status_hold == status_filter,\n            Order.status == OrderStatus.PENDING_DISPATCH,\n        ),\n    )\n",
     "    return and_(Order.shipper_status_hold.is_(None), Order.status == status_filter)\n",
     "SQL 两个分支：没冻结的按真状态"),
    ("货主档位查询退回真状态（同一条单跑到他的「派单中」档去）", QUERY,
     "            q = q.where(shipper_status_matches(status_filter))\n",
     "            q = q.where(Order.status == status_filter)\n",
     "货主档位查询走 shipper_status_matches"),
    ("App 端点又调回会提醒货主的撤回", APIS,
     "    @POST(\"orders/{orderId}/release\")\n",
     "    @POST(\"orders/{orderId}/recall\")\n",
     "Apis.kt 有 @POST(\"orders/{orderId}/release\")"),
    ("确认退回改调 recallOrder（点了「退回池子」结果货主收到撤回提醒）", POOL_VM,
     "                container.repo.releaseOrder(oid, releaseReason.trim())\n",
     "                container.repo.recallOrder(oid, releaseReason.trim())\n",
     "确认退回只调静默端点 releaseOrder"),
    ("「已完成派单」丢掉已接单档（司机已接的单从分页里消失）", POOL_VM,
     "                val accepted = container.repo.orders(status = \"ACCEPTED\")\n",
     "                val accepted = container.repo.orders(status = \"DELIVERED\")\n",
     "已完成档 = DISPATCHED + ACCEPTED 两档相加"),
    ("已完成派单不再按司机分组（又变回一单一卡）", POOL_VM,
     "            .groupBy { it.driverId }\n",
     "            .groupBy { it.id }\n",
     "「已完成派单」按司机分组"),
    ("load() 不再按档位分流（切到已完成档拿不到数据）", POOL_VM,
     "        if (tab == TAB_COMPLETED) loadDispatched() else loadPool()\n",
     "        loadPool()\n",
     "load() 按档位分流"),
    ("退回时顺手给货主发条消息（用户逐字要求：不会有任何提醒）", POOL_VM,
     "                actionResult = \"已退回派单池，货主端不会有任何变化\"\n",
     "                container.repo.notifyShipper(oid, \"您的订单已被退回派单池\")\n                actionResult = \"已退回派单池，货主端不会有任何变化\"\n",
     "confirmRelease 里没有任何给货主发消息"),
    ("池页两档退回一档（分页没了）", POOL_UI,
     "                labels = listOf(\"待派单池\", \"已完成派单\"),\n",
     "                labels = listOf(\"待派单池\"),\n",
     "池页用通用 SegmentedPicker 切两档"),
    ("池页新建 OrderTab 档位表（走订单列表的档位，判据对每一格都有要求）", POOL_UI,
     "                labels = listOf(\"待派单池\", \"已完成派单\"),\n",
     "            OrderTab(null, \"全部\", null)\n                labels = listOf(\"待派单池\", \"已完成派单\"),\n",
     "没新建 OrderTab 档位表"),
    ("「退回池子」被换成中性词（静默动作在界面上不见了）", POOL_UI,
     "                            Text(\"退回池子\", color = MaterialTheme.colorScheme.error)\n",
     "                            Text(\"查看\", color = MaterialTheme.colorScheme.error)\n",
     "已完成档的动作是「退回池子」"),
    ("确认框不再承诺货主无感（界面把静默动作说成普通动作）", POOL_UI,
     "                        \"货主端不会有任何变化：他看到的还是「已派单 / 已接单」，也不会有任何提醒。\",\n",
     "                        \"退回后这张单会回到派单池。\",\n",
     "退回确认框逐字承诺货主无感"),
    ("已完成档的截断提示被摘（后端 300 条上限静默截断）", POOL_UI,
     "        if (vm.dispatchedHitCap) {\n",
     "        if (false) {\n",
     "已完成档也有截断提示"),
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


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

    if refuse_if_injecting("静默退回派单池（CHG-0039）反向验证"):
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
