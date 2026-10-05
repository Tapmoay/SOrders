"""红线：派单员把已派的单退回派单池时，**货主那一侧必须完全无感**（CHG-0039）。

## 由来（用户 2026-10-05 逐字，语音转写）
「这个操作货主端是不会显示的 —— 货主端仍然会显示状态为已派单或者说司机已接单；
订单的状态会默默发生改变，不会有任何的消息提醒。这个操作只限于派单员，
货主不会有任何的交易提醒，而且货主也不需要知道这个。」

## 为什么必须有一条红线盯着它
「退回派单池」与既有的「撤回派单」（`services/order_flow.py::recall_dispatch`）在
**状态跃迁、清掉的字段、库存与钱的口径上逐字相同**，唯一的差别是**通知对象**：
撤回会走 `orders.recalled` → `services/push_events.py::push_order_to_shipper` →
`services/message_center.py::publish_order_recalled_shipper`，给货主发一条「派单已撤回」。

所以只要有人图省事让退回复用撤回那条路（把 `release_dispatch` 删掉、端点改成调
`recall_dispatch`，或者顺手补一句 `outbox.enqueue(db, "orders.recalled", ...)`），
**货主手机上就会多一条消息** —— 而单测不会红、界面不会异常、派单员也看不出来。
这份判据让那件事变成红的。

三条「坏了不报错」的性质，正是本条红线的靶子：
1. 复用撤回 ⇒ 通知货主（用户唯一那条边界被越过）；
2. 不出参覆写 ⇒ 货主那一侧**当场**看到「派单中」，等于把静默动作告诉他了；
3. 货主档位查询不认冻结值 ⇒ 那张单从他的「已派单」档**消失**、跑到「派单中」档。

## 判据（清单全部自己算；路径写错会先在「读到几个文件」那条报红）
1. 服务层：`release_dispatch` 的 CAS 带冻结值、冻结值在 CAS **之前**取、不发任何货主事件、
   清掉司机与逐单覆盖（钱）、释放库存、落 `ORDER_RELEASE_SILENT` 审计码。
2. 解冻：重新派出去时 `assign_driver` 的 CAS 把这一列写回 NULL（否则货主永远停在旧状态）。
3. 端点层：只发 `orders.revoked`（司机掉单）+ `orders.pending_pool_changed`（派单员刷新），
   **不发** `orders.recalled`；且整个 `api/v1` 里 `orders.recalled` 只许出现在召回端点那一处。
4. 货主可见状态只有一处定义、一处覆写、一个查询口径。
5. 新列只从迁移进（`core/schema_bootstrap.py` 里 0 次），迁移可重跑、按方言取类型、取值现算。
6. 命令注册表 + 审计中文标签 + Android 那一路（端点/DTO/仓库/池 VM/池页/报告中心）。

⚠️ 注入式反向验证（改坏 → 本脚本必须红，改回 → 绿）：
   python _tools/qa/_reverse_verify_silent_release.py

用法：python _tools/qa/_check_silent_release.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 剥 Kotlin 注释的实现只此一份（复用兄弟红线，不抄第二份）。
from _check_pagination_wiring import strip_comments  # noqa: E402
#: 剥 Python 注释/文档字符串（换成等长空格、保留行号）—— 下面有几处**顺序**比较要靠它。
from _check_single_source import code_only  # noqa: E402
#: 失败行/章节标题的形状只此一份（房规）：失败行是 `  [!!]   <标题>` ——
#: `_reverse_verify_*.py` 正是拿这个前缀去认「这一条被判据抓住了」，自己另写一种就等于反向验证静默空过。
from _check_hints import Checker  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
API_V1 = BACKEND / "app/api/v1"
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

FLOW = BACKEND / "app/services/order_flow.py"
RESP = BACKEND / "app/services/order_response.py"
QUERY = BACKEND / "app/api/v1/orders_query.py"
ASSIGN = BACKEND / "app/api/v1/orders_assignment.py"
MODEL = BACKEND / "app/models/order.py"
ENUMS = BACKEND / "app/models/enums.py"
BOOT = BACKEND / "app/core/schema_bootstrap.py"
REG = BACKEND / "app/commands/registry.py"
COV = BACKEND / "app/core/capability_audit_coverage.py"
MIG = BACKEND / "app/migrations/022_shipper_status_hold.py"
PUSH = BACKEND / "app/services/push_events.py"
MSG = BACKEND / "app/services/message_center.py"

APIS = ANDROID / "data/remote/api/Apis.kt"
REPO = ANDROID / "data/repo/AppRepository.kt"
DTO = ANDROID / "data/remote/dto/Dtos.kt"
PVM = ANDROID / "ui/dispatcher/DispatcherPoolViewModel.kt"
PSCR = ANDROID / "ui/dispatcher/DispatcherPoolScreen.kt"
RPT = ANDROID / "ui/dispatcher/ReportCenter.kt"

#: 被点名的文件都必须在（少一个就先报错，不静默空转）。
REQUIRED = [
    FLOW, RESP, QUERY, ASSIGN, MODEL, ENUMS, BOOT, REG, COV, MIG, PUSH, MSG,
    APIS, REPO, DTO, PVM, PSCR, RPT,
]

C = Checker()


def ok(label: str, cond: bool, detail: str = "") -> None:
    C.ok(label, cond, detail)


def section(title: str) -> None:
    C.section(title)


def py(path: Path) -> str:
    """后端文件：注释与文档字符串已剥（保留行号）。"""
    return code_only(path.read_text(encoding="utf-8")) if path.is_file() else ""


def kt(path: Path) -> str:
    """Kotlin 文件：注释已剥。"""
    return strip_comments(path.read_text(encoding="utf-8")) if path.is_file() else ""


def py_section(path: Path, name: str) -> str:
    """后端某个**顶层函数**的源码段（到下一个顶层 def/class 为止）。空串 = 找不到。"""
    src = py(path)
    m = re.search(rf"(?m)^def {re.escape(name)}\(", src)
    if not m:
        return ""
    tail = src[m.end():]
    nxt = re.search(r"(?m)^(?:def |class )", tail)
    return src[m.start(): m.end() + (nxt.start() if nxt else len(tail))]


def kt_section(path: Path, name: str) -> str:
    """Kotlin 某个成员函数的源码段（缩进 4 空格的 fun name( 到下一个成员/右括号）。"""
    src = kt(path)
    m = re.search(rf"(?m)^    (?:private |internal |public |override )?fun {re.escape(name)}\(", src)
    if not m:
        return ""
    tail = src[m.end():]
    nxt = re.search(r"(?m)^(?:    (?:private |internal |public |override )?fun |    @|\})", tail)
    return src[m.start(): m.end() + (nxt.start() if nxt else len(tail))]


def main() -> int:
    section("0. 反空转：读到几个文件")
    missing = [str(p.relative_to(ROOT)) for p in REQUIRED if not p.is_file()]
    ok("CHG-0039 点名的文件全在（18 个）", not missing, "缺：" + ", ".join(missing))

    api_mods = sorted(API_V1.glob("*.py"))
    ok("api/v1 下模块 >= 20 个（防路径写错后空转）", len(api_mods) >= 20, f"实际 {len(api_mods)}")

    release = py_section(FLOW, "release_dispatch")
    recall = py_section(FLOW, "recall_dispatch")
    assign = py_section(FLOW, "assign_driver")
    endpoint = py_section(ASSIGN, "release_order")

    section("① 服务层：静默退回的动作本身（services/order_flow.py::release_dispatch）")
    ok("release_dispatch 存在（它是这条动作的唯一定义处）", bool(release))
    ok("recall_dispatch 仍在（两条路并存，不是把撤回改名）", bool(recall))
    ok(
        "CAS 里带上冻结值（shipper_status_hold=shipper_status_hold）",
        "shipper_status_hold=shipper_status_hold" in release,
        "货主可见状态必须与真实状态在同一条 UPDATE 里落库",
    )
    ok(
        "冻结值在 CAS 之前取（shipper_status_hold = order.status）",
        "shipper_status_hold = order.status" in release
        and release.index("shipper_status_hold = order.status") < release.index("update(Order)"),
        "CAS 之后 order.status 已经是 PENDING_DISPATCH，事后现读会把货主也改成「派单中」",
    )
    ok(
        "真状态回到 PENDING_DISPATCH（池子/计数/批量派单才能天然复用）",
        "status=OrderStatus.PENDING_DISPATCH" in release,
    )
    ok(
        "前置状态门 = 已派单/已接单（与撤回同一档）",
        "OrderStatus.DISPATCHED, OrderStatus.ACCEPTED" in release,
    )
    ok(
        "状态门不满足时抛 ValueError（由端点翻成 400）",
        "if order.status not in allowed:" in release
        and "仅「已派单/已接单」订单可退回派单池" in release,
        "⛔ 只判 raise ValueError 会漏：CAS 抢占失败那条也 raise ⇒ 状态门被整段摘掉照样绿（反向验证第 4 条实测）",
    )
    ok(
        "CAS 抢占失败要回滚并报「刚被别的操作改过」",
        "rowcount != 1" in release and "db.rollback()" in release,
    )
    ok("⛔ 不发货主事件 orders.recalled", "orders.recalled" not in release)
    ok("⛔ 不直接调 publish_order_recalled_shipper（那是撤回那条路）", "publish_order_recalled_shipper" not in release)
    ok(
        "清掉司机与逐单覆盖值（钱：否则下一任司机按上一任的数字拿钱）",
        all(
            f in release
            for f in (
                "driver_id=None",
                "dispatched_at=None",
                "driver_acknowledged_at=None",
                "driver_piece_amount=None",
                "driver_commission_rate=None",
            )
        ),
    )
    ok("释放这一单占用的库存（auto_stock_release）", "auto_stock_release(" in release)
    ok(
        "落自己的审计码 ORDER_RELEASE_SILENT（与 ORDER_RECALL 分开）",
        "OperationAction.ORDER_RELEASE_SILENT" in release,
    )
    ok(
        "审计里记下被收回的司机与冻结值（事后能查谁在什么时候把谁的货退回去了）",
        '"released_driver_id": released_driver_id' in release
        and '"shipper_status_hold": shipper_status_hold.value' in release
        and '"order_snapshot": snapshot' in release,
        "⛔ 只判变量名会漏：局部变量 released_driver_id 还在 ⇒ 载荷里把键名换掉照样绿（反向验证第 9 条实测）",
    )

    section("② 解冻：重新派出去时，货主跟着新事实走")
    ok(
        "assign_driver 的 CAS 把冻结值写回 NULL",
        "shipper_status_hold=None" in assign,
        "⛔ 不清的话，货主永远停在上一任司机那一档（订单已送到也显示「已派单」）",
    )

    section("③ 端点层：只发两条事件，且不发提醒货主的那一条")
    ok("POST /{order_id}/release 存在", bool(endpoint) and '@router.post("/{order_id}/release"' in py(ASSIGN))
    ok("退回端点发 orders.revoked（被收回的司机立刻掉单）", '"orders.revoked"' in endpoint)
    ok("退回端点发 orders.pending_pool_changed（派单员的池子刷新）", '"orders.pending_pool_changed"' in endpoint)
    ok(
        "⛔ 退回端点不发 orders.recalled",
        '"orders.recalled"' not in endpoint,
        "outbox 是全项目唯一那条提醒货主的通道",
    )
    ok("退回端点沿用 ORDER_RECALL 权限（与撤回同一个操作人，不新增权限点）", "Permission.ORDER_RECALL" in endpoint)
    ok("旧司机 id 在动作之前抓（动作会把 driver_id 清掉）", "old_driver_id = order.driver_id" in endpoint)

    recalled_sites = []
    for path in api_mods:
        src = py(path)
        n = src.count('"orders.recalled"')
        if n:
            recalled_sites.append((path.name, n, "recall_order" in src))
    ok(
        "整个 api/v1 里 orders.recalled 恰好 1 处，且只在召回端点里",
        len(recalled_sites) == 1 and recalled_sites[0][1] == 1 and recalled_sites[0][2],
        f"实际 {recalled_sites}",
    )
    ok(
        "货主那条通知的落点仍在 push_events（撤回专用，退回这条不经过它）",
        "publish_order_recalled_shipper" in py(PUSH),
    )
    ok(
        "push_events 的 docstring 写明它服务的是「撤回」（给下一个人看的说明）",
        '"""撤回：落库+推送' in PUSH.read_text(encoding="utf-8"),
    )
    ok("message_center 里 publish_order_recalled_shipper 仍在（撤回没被顺手删掉）", "def publish_order_recalled_shipper(" in py(MSG))

    section("④ 货主可见状态：一处定义、一处覆写、一个查询口径")
    resp = py(RESP)
    ok("shipper_visible_status_of 存在（该口径的唯一定义处）", "def shipper_visible_status_of(" in resp)
    ok(
        "只有真状态是 PENDING_DISPATCH 且冻结值非空时才覆写",
        "order.status == OrderStatus.PENDING_DISPATCH and order.shipper_status_hold is not None" in resp,
        "少任一半条件，货主就会看到一张「派单中」的单，或者永远停在冻结值",
    )
    ok(
        "shipper_status_matches 存在（列表按档位筛的 SQL 版，与上面同一口径）",
        "def shipper_status_matches(" in resp,
    )
    matches = py_section(RESP, "shipper_status_matches")
    ok(
        "SQL 两个分支：没冻结的按真状态、冻结过的按冻结值",
        "shipper_status_hold.is_(None)" in matches
        and "Order.status == status_filter" in matches
        and "shipper_status_hold == status_filter" in matches,
    )
    enrich = py_section(RESP, "enrich_order_out")
    ok(
        '货主的 status 只从 shipper_visible_status_of 出去（data["status"] = …）',
        'data["status"] = shipper_visible_status_of(order)' in enrich,
    )
    ok(
        "覆写发生在货主分支里（不是所有角色都改）",
        'data["status"] = shipper_visible_status_of(order)' in enrich
        and "UserRole.SHIPPER" in enrich
        and enrich.index("UserRole.SHIPPER") < enrich.index('data["status"] = shipper_visible_status_of(order)'),
    )
    query = py(QUERY)
    ok("订单列表导入并使用了 shipper_status_matches", "shipper_status_matches" in query)
    ok(
        "货主档位查询走 shipper_status_matches（否则被静默退回的单会从他的「已派单」档消失）",
        "q = q.where(shipper_status_matches(status_filter))" in query,
    )
    ok(
        "其余角色仍按真状态筛（派单员看的是事实，不是冻结值）",
        "q = q.where(Order.status == status_filter)" in query,
    )
    ok("货主/非货主的分流由 role == UserRole.SHIPPER.value 判", "role == UserRole.SHIPPER.value" in query)
    ok(
        "shipper_status_matches 在 api 层只用这 1 处（一个口径，别各写一份）",
        query.count("shipper_status_matches") == 2 and query.count("shipper_status_matches(") == 1,
        f"实际 提及 {query.count('shipper_status_matches')} 次 / 调用 {query.count('shipper_status_matches(')} 次（import 1 + 调用 1）",
    )

    section("⑤ 新列只从一条链进来：模型 + 迁移（schema_bootstrap 里 0 次）")
    model = py(MODEL)
    ok(
        "orders.shipper_status_hold 在模型里、与 status 同型且可空",
        "shipper_status_hold: Mapped[OrderStatus | None]" in model and "Enum(OrderStatus), nullable=True" in model,
    )
    ok(
        "⛔ core/schema_bootstrap.py 里一次都不提它（加列是正式变更 ⇒ 必须是一条迁移）",
        "shipper_status_hold" not in py(BOOT),
        "两处都写 = 同一件事两个来源（本项目头号忌讳）",
    )
    mig = py(MIG)
    ok("迁移 022 存在", bool(mig))
    ok("版本号与文件名一致（VERSION = 22）", "VERSION = 22" in mig and 'NAME = "shipper_status_hold"' in mig)
    ok("有 DESCRIPTION（迁移名册要能自解释）", "DESCRIPTION = (" in mig)
    ok(
        "可重跑：先判表在不在、再判列在不在，重复跑是空操作",
        "insp.get_table_names()" in mig and 'COLUMN in {c["name"] for c in insp.get_columns(TABLE)}' in mig,
        "MySQL 的 DDL 隐式提交，一条迁移可能改了一半才失败",
    )
    ok(
        "按方言取类型名（SQLite 没有 ENUM，写死 ENUM 会让后端起不来）",
        'engine.dialect.name == "sqlite"' in mig and "VARCHAR(16)" in mig and "ENUM(" in mig,
    )
    ok("取值从 models/enums.py::OrderStatus 现算（⛔ 不手写第二份六档清单）", "for s in OrderStatus" in mig)
    ok("只加这一列，不改别的表", mig.count("ALTER TABLE") == 1 and "ADD COLUMN {COLUMN}" in mig)

    section("⑥ 审计码 / 命令注册表 / 中文标签")
    ok(
        "OperationAction 有 ORDER_RELEASE_SILENT（与 ORDER_RECALL 分开）",
        'ORDER_RELEASE_SILENT = "ORDER_RELEASE_SILENT"' in py(ENUMS),
    )
    reg = py(REG)
    ok("注册表登记了 order.release_silent", 'name="order.release_silent"' in reg)
    ok(
        "它指向 services.order_flow:release_dispatch（不是 recall_dispatch）",
        'impl="services.order_flow:release_dispatch"' in reg,
    )
    spec = ""
    m = re.search(r'name="order\.release_silent",[\s\S]{0,900}?\n    \),', reg)
    if m:
        spec = m.group(0)
    ok(
        "这条命令的 events 恰好两条、且不含 orders.recalled",
        'events=("orders.revoked", "orders.pending_pool_changed")' in spec,
        "注册表要能回答「哪条命令会提醒货主」——那正是用户划下的边界",
    )
    ok(
        "它的状态跃迁与撤回逐字相同（PENDING_DISPATCH），权限也是 ORDER_RECALL",
        'capabilities=("ORDER_RECALL",)' in spec and 'to_state="PENDING_DISPATCH"' in spec,
    )
    ok(
        "能力审计覆盖表里 order:recall 认下两个动作码",
        "'order:recall': ('ORDER_RECALL', 'ORDER_RELEASE_SILENT')," in py(COV),
    )
    ok(
        "报告中心给这个码中文标签（审计列表不许出现裸英文码）",
        '"ORDER_RELEASE_SILENT" ->' in kt(RPT),
    )

    section("⑦ Android：端点 → 仓库 → 池子那一档 → 界面承诺")
    ok('Apis.kt 有 @POST("orders/{orderId}/release")', '@POST("orders/{orderId}/release")' in kt(APIS))
    ok("Apis.kt 的 releaseOrder 方法签名存在", "suspend fun releaseOrder(" in kt(APIS))
    ok(
        "OrderReleaseBody 的原因可选（退回原因只有派单员看得到，不该逼他填）",
        'data class OrderReleaseBody(val reason: String = "")' in kt(DTO),
    )
    ok(
        "仓库层有 releaseOrder（界面不直接拼 URL）",
        'suspend fun releaseOrder(orderId: Long, reason: String = "")' in kt(REPO),
    )
    vm = kt(PVM)
    ok("池 VM 有两个分页常量 TAB_POOL / TAB_COMPLETED", "const val TAB_POOL = 0" in vm and "const val TAB_COMPLETED = 1" in vm)
    ok(
        "load() 按档位分流（实时刷新/重试/派完/退完都只认它）",
        "if (tab == TAB_COMPLETED) loadDispatched() else loadPool()" in vm,
    )
    ok(
        "已完成档 = DISPATCHED + ACCEPTED 两档相加",
        'container.repo.orders(status = "DISPATCHED")' in vm and 'container.repo.orders(status = "ACCEPTED")' in vm,
    )
    ok(
        "截断按两次查询各自判（合并后条数可能是 300 的两倍，会误判）",
        "assigned.size >= ORDER_LIST_LIMIT || accepted.size >= ORDER_LIST_LIMIT" in vm,
    )
    ok("「已完成派单」按司机分组（一张卡 = 一个司机）", "groupBy { it.driverId }" in vm)
    ok("分组头取不到名字时有兜底（卡片头不许空着）", "未指派司机" in vm)
    confirm = kt_section(PVM, "confirmRelease")
    ok("confirmRelease 存在", bool(confirm))
    ok(
        "确认退回只调静默端点 releaseOrder（⛔ 不许调 recallOrder —— 那条会提醒货主）",
        "container.repo.releaseOrder(" in confirm and "recallOrder" not in confirm,
    )
    ok(
        "成功提示里点名「货主端不会有任何变化」（操作者要知道这条动作是无声的）",
        "货主端不会有任何变化" in vm,
    )
    ok(
        "⛔ confirmRelease 里没有任何给货主发消息/广播的动作",
        not re.search(r"notify|sendMessage|publish|shipperNotify", confirm),
        "货主无感是这条动作的定义，不是可选行为",
    )
    ok("退回成功后按新档拉一次（退掉的单不能还留在列表里）", "load()" in confirm)
    scr = kt(PSCR)
    ok(
        "池页用通用 SegmentedPicker 切两档，标签是「待派单池 / 已完成派单」",
        'labels = listOf("待派单池", "已完成派单")' in scr and "SegmentedPicker(" in scr,
    )
    ok("⛔ 没新建 OrderTab 档位表（那是订单列表的档位，判据对每一格都有要求）", "OrderTab(" not in scr)
    ok(
        "已完成档的动作是「退回池子」且在 OrderCard 的 leading（左＝反向动作）",
        '"退回池子"' in scr and "leading = {" in scr,
    )
    ok(
        "退回确认框逐字承诺货主无感（界面不许把静默动作说成「撤回」）",
        "货主端不会有任何变化" in scr and "也不会有任何提醒" in scr,
    )
    ok("已完成档也有截断提示（后端 300 条上限同样会截它）", "TruncationNote(" in scr and "dispatchedHitCap" in scr)

    print("\n" + "=" * 60)
    if C.fails:
        print(f"❌ {len(C.fails)} 项不通过（通过 {C.n_ok} 项）：")
        for label, _ in C.fails:
            print(f"   - {label}")
        return 1
    print(f"✅ 全部 {C.n_ok} 项通过：退回派单池对货主完全无感（状态冻结、零事件、零提醒）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
