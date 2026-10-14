# -*- coding: utf-8 -*-
"""红线：退货申请**可以直接改**，但改的只有商品明细、而且只发一条通知（CHG-0130）。

## 由来（用户 2026-10-15 口述，父会话 m43140 转来）
「退货是可以改的…**派单员是可以更改的**，不需要重新…让货主撤销然后再重新申请一下，只不过我们会发个通知，
告诉货主或批发商他的这个退货申请的订单我们改动了」；
「**货主也是可以更改的**，就是**只要派单员还没有确认**，他也是可以更改，改完之后只会重新发个信息给派单员
说此退货订单发生了改动」；
「主要改的是退货的商品…**商品种类、商品数量**，派单员可以更改，货主和批发商他们也是可以进行更改的」。

改动前的口径是「数量锁死：要改数量只能驳回、让货主重提」—— 那正是用户要废掉的那条路。

## 为什么必须有一条红线盯着它
这条实现里有六种「改坏了也不报错」的坏法，每一条都编译通过、界面照画：

* **把已有行删掉重建**：明细看起来一模一样，但 `order_return_request_lines` 那一行**是凭证**
  （`data_retention.py`：清掉单会把凭证一起毁掉）—— 删了重建会让审计指向的行断掉，
  也会让「改动前」变成查不回来的东西；
* **顺手把状态/备注/办理人一起写**：状态机被悄悄扩宽，办理之后还能改，钱和库存就对不上了；
* **在 amend 里另写一份「能退几件」的上限**：两份上限总有一天分叉（提交那一份已经有一套规则）；
* **改明细时真的去动钱/货**：用户说的是「改申请单」，动钱动货的仍然只有「办理退货」那一刻；
* **通知发成「每改一个字段一条」或发给改的人自己**：用户原话是「只会重新发个信息给派单员」；
* **界面给终态的单也露出入口**：用户填完才被后端拒 —— 那是把判据交给了「用户的手感」。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界解决不了**。被查的全是「改哪几行、发几条、发给谁、入口露不露」：
`ln.quantity = wanted.pop(...)` 换成 `db.delete(ln)`、`_check_pending(req, "改")` 换成
`if req.status != "pending": return`（静默不报错）、`create_message` 从 1 次变 2 次、收件人从
`req.shipper_id` 换成 `actor_id`、界面那道 `if (canAmendReturnRequest(req))` 换成 `if (true)` ——
这几处没有一处会编译失败，也没有一处会让既有单测或后端判据变红（本轮零契约、零金额、零库存改动）。
边界那一半已经先做了（状态判据走既有的 `_check_pending`、上限走既有的 `_validate_lines`、界面判据收进
一个纯函数 `canAmendReturnRequest`），但「有没有调它、调一次还是两次、发给谁」只存在于**调用点**，
所以判据只能扫结构 + 扫次数 + 扫收件人。运行时那一头交给
_tools/qa/_reverse_verify_return_request_editable.py（逐条注入破坏）。

## 判据（清单全部自己算；路径写错会先在「关键文件都在」那条报红）
 1. 关键文件都在，且源码都有实体（反空转）；
 2. 后端只有一个写端点，权限点是 ORDER_RETURN_REQUEST，⛔ 不挂 ShipperOnly（挂上就把派单员挡在外面）；
 3. 角色白名单只有货主 + 派单员；司机一律 403，话术是中文；
 4. 请求体只有商品明细（items）；服务层异常一律 400 + 中文原样给用户；
 5. 锁序与办理退货一致（先取申请行再看订单行）；写库顺序是先 enqueue 事件再 commit；
 6. 状态门走既有的 _check_pending（⛔ 不另写一份「能改吗」），非派单员还要过 _check_operator_is_owner；
 7. 上限走既有的 _validate_lines（⛔ 不另写一份 max_returnable）；
 8. 已在申请里的行**就地改数量**、本次不要的行才删；⛔ 不删行重建（db.delete 一次都没有）；
 9. 一个字节都不许动的东西：状态 / 备注 / 驳回理由 / 办理人 / 账本 / 库存（amend 体里一次都不出现）；
10. 审计留痕：ORDER_RETURN_REQUEST_AMEND + 四个键（申请单号 / 改动前 / 改动后 / 改动人）都在；
11. 新消息 type 只加了一条：severity 与中文名两张表各一行，既有四个 type 一个都没动；
12. **只发一条**：派单员改 → 只有一次 create_message（收件人是货主）；货主/批发商改 → 每个派单员一条；
13. 幂等键带 event_id（同一张申请可以被改很多次，只用 request_id 会让第二次起被吞掉）；
14. 出箱聚合根是那张申请（returns.amended 的聚合键是 request_id）；main.py 那一支 < 500 字符
    （那半句是 _check_return_request.py 第 1 跳的解析窗口，注释一长就会被误判成「没登记处理器」）；
15. Android 纯逻辑：三方同一句 canAmendReturnRequest、上限与全仓唯一那处同源、填 0 不放进去、
    空明细拦在本地并引到「撤回申请」；
16. Android 入口：两端各一处 canAmendReturnRequest 闸 + onAmend；弹层**全仓只有一份实现**，
    且复用共用的 OrderReturnLines（⛔ 不复制第二份填数量块）；
17. 文案：通知对象说对了、「此退货订单发生了改动」是用户原话、界面上不出现「操作成功」这种空话；
18. 测试与登记：后端六用例 + Android 十单测、变更单九节、README 一行、认领一段，
    反验脚本 ≥ 3 条注入且与本脚本声明的条数对得上。
19. 新消息**点得进去**：ui/messages/NoticeRouting.kt 里 TYPE_AMENDED 一处常量 + 派单员 / 货主两支路由
    各回自己那一页，两支都带 focus（点进去定位到那一张，⛔ 不是把用户扔回列表顶上）。

⚠️ 注入式反向验证（改坏 → 本脚本必须红，改回 → 绿）：
   python _tools/qa/_reverse_verify_return_request_editable.py（7 种破坏方式全被抓）

用法：python _tools/qa/_check_return_request_editable.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 失败行 / 章节标题的形状只此一份（房规）：失败行是 "  [!!]   <标题>" —— _reverse_verify_*.py
#: 正是拿这个前缀去认「这一条被判据抓住了」。剥 Kotlin 注释的实现也只此一份（保留字符串字面量）。
from _check_hints import Checker, strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
AND_TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders"
APPS = ROOT / "backend/app"

API = APPS / "api/v1/return_requests.py"
SVC = APPS / "services/order_return_request.py"
MSG = APPS / "services/message_center.py"
PUSH = APPS / "services/push_events.py"
MAIN = APPS / "main.py"
ENUMS = APPS / "models/enums.py"
AUDIT = APPS / "core/capability_audit_coverage.py"
OUTBOX = APPS / "core/outbox.py"
BE_TEST = ROOT / "backend/tests/test_return_request_amend.py"

AMEND = ANDROID / "ui/common/ReturnRequestAmend.kt"
VMS = ANDROID / "ui/common/ReturnRequestsViewModel.kt"
UI = ANDROID / "ui/common/ReturnRequestsUi.kt"
KT_TEST = AND_TEST / "ui/common/ReturnRequestAmendTest.kt"
DISP_SCREEN = ANDROID / "ui/dispatcher/DispatcherReturnRequestsScreen.kt"
DISP_VM = ANDROID / "ui/dispatcher/DispatcherReturnRequestsViewModel.kt"
SHIP_SCREEN = ANDROID / "ui/shipper/ShipperReturnRequestsScreen.kt"
SHIP_VM = ANDROID / "ui/shipper/ShipperReturnRequestsViewModel.kt"
APIS = ANDROID / "data/remote/api/Apis.kt"
REPO = ANDROID / "data/repo/AppRepository.kt"
DTOS = ANDROID / "data/remote/dto/Dtos.kt"
NR = ANDROID / "ui/messages/NoticeRouting.kt"

CHG = ROOT / "docs/changes/CHG-0130.md"
README = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_return_request_editable.py"

REQUIRED = [API, SVC, MSG, PUSH, MAIN, ENUMS, AUDIT, OUTBOX, BE_TEST,
            AMEND, VMS, UI, KT_TEST, DISP_SCREEN, DISP_VM, SHIP_SCREEN, SHIP_VM,
            APIS, REPO, DTOS, NR, CHG, README, CLAIM, REVERSE]

#: 反空转下限：源码读不到东西时下面每一条都会「找不到就空过」。
MIN_KT = 100
MIN_BACKEND = 4000

#: 换行与三引号都从字符码来（这个脚本里一个转义序列都不用，省得被谁改写坏）。
NL = chr(10)
Q3 = '"' * 3

C = Checker()


def ok(label: str, cond: bool, detail: str = "") -> None:
    C.ok(label, cond, detail)


def section(title: str) -> None:
    C.section(title)


def raw(path: Path) -> str:
    if not path.is_file():
        return ""
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
        return NL.join(fh.read().splitlines()) + NL


def kt(path: Path) -> str:
    """Kotlin 文件：注释已剥（KDoc 里写着一句话是不算数的）。"""
    return strip_comments(raw(path))


def between(text: str, start: str, end: str) -> str:
    """start 到它后面第一个 end 之间那一块（锚点不在 → 空串，调用点自己会报红）。"""
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    return text[i:] if j < 0 else text[i:j]


def after_doc(text: str) -> str:
    """摘掉函数体开头那段 docstring（说明文字不算代码，不许拿它冒充实现）。"""
    i = text.find(Q3)
    if i < 0:
        return text
    j = text.find(Q3, i + 3)
    return text if j < 0 else text[j + 3:]


def finish() -> int:
    print(NL + "=" * 60)
    total = C.n_ok + len(C.fails)
    if C.fails:
        print(f"❌ {len(C.fails)} 项不通过（通过 {C.n_ok} 项）：")
        for label, _ in C.fails:
            print(f"   - {label}")
        print(f"_check_return_request_editable: {C.n_ok}/{total} 通过")
        return 1
    print("✅ 全部 %d 项通过：三方都能改这张退货申请的商品明细，改完只发一条通知。" % C.n_ok)
    print(f"_check_return_request_editable: {C.n_ok}/{total} 通过")
    return 0


def main() -> int:
    # ── 0. 反空转（文件读不到时下面每一条都会空过）──────────────────────────
    section("0. 反空转（文件读不到时下面每一条都会空过）")
    missing = [p for p in REQUIRED if not p.is_file()]
    ok("关键文件都在：" + "、".join(p.name for p in REQUIRED), not missing,
       "缺：" + "、".join(str(p) for p in missing))
    if missing:
        print(NL + "❌ 关键文件缺失，后面的判据全部跳过（不许安静地绿）")
        return finish()

    api, svc, msg = raw(API), raw(SVC), raw(MSG)
    ok("后端三份源码都读到了（%d / %d / %d 字符，下限 %d）" % (len(api), len(svc), len(msg), MIN_BACKEND),
       min(len(api), len(svc), len(msg)) > MIN_BACKEND, "读不到内容 → 后面全是空转")
    kts = sorted(ANDROID.rglob("*.kt"))
    ok("ANDROID 下扫到 %d 个 .kt（下限 %d）" % (len(kts), MIN_KT), len(kts) >= MIN_KT,
       "目录被搬走 → 一条都没扫到 → 全绿")

    # ── 1. 后端接口面 ───────────────────────────────────────────────────────
    section("① 后端接口面：一个写端点，三方都能进，门禁只认行级规则")
    ep = between(api, '@router.post("/{request_id}/amend"', "# --------------------------------------------------------------------------- 派单端")
    ok("端点块读到了（%d 字符 > 600）" % len(ep), len(ep) > 600, "锚点被挪走 → 下面几条会空过")
    ok("端点登记：POST /{request_id}/amend，response_model=ReturnRequestOut",
       '@router.post("/{request_id}/amend", response_model=ReturnRequestOut)' in api)
    ok("端点只要一个权限点：Permission.ORDER_RETURN_REQUEST",
       "Depends(require_permission(Permission.ORDER_RETURN_REQUEST))" in ep)
    deps = re.findall(r"Depends[(]([^)]*)[)]", ep)
    ok("端点只有两个依赖（get_db + 上面那个权限点，没有角色锁）", len(deps) == 2, "实际依赖：%r" % (deps,))
    ok("⛔ 没挂 ShipperOnly（挂上派单员就进不来了，而用户要的正是三方都能改）",
       "ShipperOnly = None" not in ep and "require_roles(UserRole.SHIPPER)" not in ep)
    ok("docstring 里写下了「为什么不挂 ShipperOnly」（下一轮才有人知道）",
       "ShipperOnly" in ep and "派单员就进不来了" in ep)
    ok("角色白名单只有货主 + 派单员两值",
       "if role not in (UserRole.SHIPPER.value, UserRole.DISPATCHER.value):" in ep)
    ok("司机等一律 403，而且话术是中文、说清谁能改",
       'detail="只有货主、批发商和派单员能改退货申请",' in ep)
    ok("actor_role 只有一处判定：_amend_actor_role（dispatcher / shipper 两值）",
       "def _amend_actor_role(user: User) -> str:" in api
       and "user_role_key(user) == UserRole.DISPATCHER.value" in api
       and "svc.ACTOR_DISPATCHER" in api and "svc.ACTOR_SHIPPER" in api)
    ok("请求体只有商品明细（body.items，一个字段都不多）",
       "items=[ReturnItem(order_product_id=i.order_product_id, quantity=i.quantity) for i in body.items]" in ep)
    ok("服务层异常一律 400 + 中文原样给用户（不吞、不换文案）",
       "except svc.ReturnRequestError as e:" in ep and "status_code=400, detail=str(e)" in ep)
    i_req = ep.find("_load_request(db, request_id, lock=True)")
    i_ord = ep.find("_load_order_locked(db, req.order_id)")
    ok("锁序与办理退货一致：先取申请行（lock=True）再锁订单行", 0 <= i_req < i_ord,
       "顺序反了会和办理退货撞锁（同一张单两条路锁的先后不同）")
    i_eq, i_commit = ep.find('outbox.enqueue(db, "returns.amended"'), ep.find("db.commit()")
    ok("写库顺序：先 enqueue 事件、再 commit（消息不能先于事实发出去）", 0 <= i_eq < i_commit)
    ok("响应回的是改完之后那张申请（重新读一次再走 _build_out）",
       "return _build_out(db, [_load_request(db, request_id)])[0]" in ep)

    # ── 2. 服务层 ───────────────────────────────────────────────────────────
    section("② 服务层：改的只有商品明细，别的什么都不动")
    m = between(svc, "def amend(", "class FulfillResult")
    mb = after_doc(m)
    ok("amend() 读到了（%d 字符 > 800）" % len(m), len(m) > 800, "锚点被挪走 → 下面几条会空过")
    ok("状态门走既有的 _check_pending（⛔ 不另写一份「能改吗」）", '_check_pending(req, "改")' in m)
    ok("非派单员还要过 _check_operator_is_owner（货主/批发商只能改自己的）",
       "if actor_role != ACTOR_DISPATCHER:" in m and "_check_operator_is_owner(req, actor_id)" in m)
    ok("上限走既有的 _validate_lines（⛔ 不另写一份 max_returnable）",
       "ops = _validate_lines(order, items)" in m and "max_returnable" not in mb)
    ok("已在申请里的行就地改数量（不是删了重建）",
       "ln.quantity = wanted.pop(ln.order_product_id)" in m)
    ok("本次不要的行才删，⛔ 一次 db.delete( 都没有（那行是凭证的一部分）",
       "req.lines.remove(ln)" in m and "db.delete(" not in mb)
    ok("按商品名快照写新行（明细是可查的凭证，不是只存 id）",
       "product_name=ops[op_id].product_name_snapshot" in m)
    ok("审计留痕：动作码 + 四个键一个不少",
       "action=OperationAction.ORDER_RETURN_REQUEST_AMEND," in m
       and all(k in m for k in ('"申请单号": str(req.id)', '"改动前": before', '"改动后": after', '"改动人"')))
    ok("「改动人」只有两个取值（批发商在库里也是货主，这是事实不是省略）",
       '"派单员" if actor_role == ACTOR_DISPATCHER else "货主/批发商"' in m)
    ok("改动前后用同一份摘要函数（lines_summary），形状与申请单一致",
       "before = lines_summary(list(req.lines))" in m and 'after = "、".join(' in m)
    ok("⛔ 状态/备注/驳回理由/办理人一个都不动",
       not re.search(r"req[.](status|note|reject_reason|handled_by|fulfilled_by)", mb),
       "amend 体里出现了这些字段")
    ok("⛔ 不写账本 / 不写库存 / 不改订单状态（那是办理退货那一刻的事）",
       not re.search(r"ledger|inventory|stock|apply_return|fulfill[(]", mb), "amend 体里出现了钱/货相关调用")
    ok("两个角色常量与消息侧逐字对齐（dispatcher / shipper）",
       'ACTOR_DISPATCHER = "dispatcher"' in svc and 'ACTOR_SHIPPER = "shipper"' in svc)
    ok("摘要函数只有一处（改前/改后/申请单三处共用同一形状）",
       svc.count("def lines_summary(") == 1 and 'or "（没有商品）"' in svc)
    am_res = between(svc, "class AmendResult:", "def lines_summary(")
    ok("AmendResult 只带 before / after 两个字符串（⛔ 不把明细对象塞进结果）",
       am_res.count(": str") == 2 and "before: str" in am_res and "after: str" in am_res,
       "实际字段数：%d" % am_res.count(": str"))

    # ── 3. 消息与出箱 ───────────────────────────────────────────────────────
    section("③ 消息与出箱：只加一条 type、只发一条通知")
    ok("新 type 在 severity 表里、与既有四个同档（不是 ERROR）",
       '"order.return_request.amended": SEVERITY_WARN,' in msg)
    ok("新 type 的中文名是「有改动」", '"order.return_request.amended": ("有改动",),' in msg)
    ok("既有四个 type 的语义一个都没动（申请退货 / 被驳回 / 已办理 / 已自动关闭）",
       all(t in msg for t in ('"order.return_request": ("申请退货",),',
                              '"order.return_request.rejected": ("被驳回",),',
                              '"order.return_request.done": ("已办理",),',
                              '"order.return_request.closed": ("已自动关闭",),')))
    n_sev = len(re.findall(r'"order[.]return_request[^"]*": SEVERITY_', msg))
    ok("退货家族的 type 只多了一条（现算 %d 个，必须是 5）" % n_sev, n_sev == 5)
    pub = between(msg, "async def publish_return_request_amended(", "async def publish_order_returned_to_driver(")
    ok("publish 函数读到了（%d 字符 > 800）" % len(pub), len(pub) > 800)
    disp = between(pub, 'if actor_role == "dispatcher":', "dispatchers_recipients = active_dispatchers(db)")
    ok("派单员改的那一支**只有一次** create_message（用户：只会重新发个信息）",
       disp.count("create_message(") == 1, "实际 %d 次" % disp.count("create_message("))
    ok("派单员改 → 收件人是这张申请的货主（不是改的人自己）", "recipient_id=req.shipper_id," in disp)
    ok("派单员改 → 标题「退货申请有改动」、正文带「原来是…现在是…」",
       'title="退货申请有改动",' in disp
       and 'content=f"订单 {ono} 的退货申请被派单员改了：原来是 {before}，现在是 {after}。",' in disp)
    ok("派单员改 → 发完就 return（不落进派单员那一支去多发一遍）",
       "db.commit()" in disp and "db.refresh(n)" in disp and "await emit_notification(n)" in disp
       and pub.count("active_dispatchers(db)") == 1)
    ok("派单员改 → 额外发一条 realtime（与「被驳回 / 已办理」同一条形状）",
       '"type": "order.return_request.amended",' in disp and "await emit_realtime(" in disp)
    ok("货主/批发商改 → 收件人是全体派单员（active_dispatchers 只调一次）",
       "for d in dispatchers_recipients:" in pub and pub.count("active_dispatchers(") == 1)
    ok("货主/批发商改 → 正文点出是谁改的，并请对方按新数量办理",
       "emphasis=(who,)," in pub and '"请按新的数量办理。"' in pub)
    ok("幂等键带 event_id（同一张申请可以改很多次，只用 request_id 会被吞掉）",
       'idem = f"order.return_request.amended:{request_id}:{event_id}"' in pub)
    ok("payload 里带了 before/after/actor_role（通知上的「原来是…」不靠回查）",
       all(k in pub for k in ('payload["before"] = before', 'payload["after"] = after',
                              'payload["actor_role"] = actor_role')))
    push = between(raw(PUSH), "async def push_return_request_amended(", NL + "async def ")
    ok("push 包装与既有三条同形（SessionLocal + publish + finally close）",
       "db = SessionLocal()" in push and "await message_center.publish_return_request_amended(" in push
       and "finally:" in push and "db.close()" in push)
    ok("push 的 docstring 说明了 before/after 由服务层带（异步回查只会查到「改之后」）",
       "不在这里回查明细" in push)
    ok("出箱聚合根是那张申请（returns.amended 的聚合键是 request_id，与 returns.done 同粒度）",
       '"returns.amended": "request_id",' in raw(OUTBOX))
    branch = between(raw(MAIN), '    if event.event_type == "returns.amended":', NL + "    if event.event_type ")
    ok("main.py 派发表里登记了这一支（读到了 %d 字符）" % len(branch),
       "push_return_request_amended(" in branch)
    ok("⚠️ 这一支必须短（%d 字符 < 500）：_check_return_request.py 第 1 跳按这个窗口解析，"
       "注释一长就把「登记了处理器」误判成红" % len(branch), 0 < len(branch) < 500)
    ok("派发表里传了 event_id（幂等键要用它）", "event_id=int(event.id or 0)," in branch)
    ok("审计动作码在枚举里、且算在 order:return_request 这个能力下",
       'ORDER_RETURN_REQUEST_AMEND = "ORDER_RETURN_REQUEST_AMEND"' in raw(ENUMS)
       and "'ORDER_RETURN_REQUEST_AMEND')," in raw(AUDIT))

    # ── 4. Android 纯逻辑 ───────────────────────────────────────────────────
    section("④ Android 纯逻辑（ui/common/ReturnRequestAmend.kt：判据收在一处）")
    ak = kt(AMEND)
    ok("canAmendReturnRequest 只有一处定义，判据是 req.isPending（三方同一句）",
       ak.count("fun canAmendReturnRequest(") == 1
       and "fun canAmendReturnRequest(req: ReturnRequestDto): Boolean = req.isPending" in ak)
    ok("两个角色常量与后端逐字对齐（dispatcher / shipper）",
       'const val AMEND_ACTOR_DISPATCHER = "dispatcher"' in ak
       and 'const val AMEND_ACTOR_SHIPPER = "shipper"' in ak)
    ok("可退上限与全仓唯一那处规则同源（调 ReturnRules.maxReturnable，⛔ 不自己减）",
       "ReturnRules.maxReturnable(" in ak and not re.search(r"quantity[ 	]*-[ 	]*", ak))
    ok("填 0 = 这一行不要了（只把大于 0 的行交上去）",
       "lines.filter { (qty[it.id] ?: 0) > 0 }.map { it.id }" in ak)
    ok("摘要形状与后端一致（商品×数量、「、」分隔）", 'joinToString("、")' in ak and "×" in ak)
    ok("通知对象说对了：派单员改 → 货主和批发商；货主/批发商改 → 派单员",
       "改完只发一条通知给货主和批发商" in ak and "改完只发一条通知给派单员" in ak)
    ok("「此退货订单发生了改动」是用户原话，逐字保留", "此退货订单发生了改动" in ak)
    ok("空明细在本地就拦下，并把用户引到「撤回申请」（不是让他干瞪眼）",
       '一行都不要就变成撤销申请了，那要走「撤回申请」。' in ak)
    ok("插值写成 ${who}（Kotlin 允许 CJK 标识符，连写的「$who发一条通知」会被当成变量名）",
       "已给${who}发一条通知。" in ak)
    ok("每次最多改的行数写成一个常量（界面与本地校验共用同一份）",
       "const val AMEND_MAX_LINES = 20" in ak and "AMEND_MAX_LINES" in ak)
    ok("界面上不出现「操作成功」这种空话", "操作成功" not in raw(AMEND) and "操作成功" not in raw(UI))

    # ── 5. 入口与弹层 ───────────────────────────────────────────────────────
    section("⑤ 入口与弹层：两端各一处闸，弹层全仓只有一份实现")
    d_sc, s_sc = kt(DISP_SCREEN), kt(SHIP_SCREEN)
    ok("派单端：入口闸用 canAmendReturnRequest（⛔ 不是自己写状态判断）",
       "if (canAmendReturnRequest(req)) {" in d_sc and "isPending" not in d_sc)
    ok("派单端：接了 onAmend = { vm.askAmend(req) }", "onAmend = { vm.askAmend(req) }," in d_sc)
    ok("派单端：挂了那个弹层（ReturnRequestAmendDialog(vm)）", "ReturnRequestAmendDialog(vm)" in d_sc)
    ok("派单端：那一行有「改明细」按钮", 'Text("改明细")' in d_sc)
    ok("货主端：入口闸用 canAmendReturnRequest（批发商与货主同属这一侧）",
       "if (canAmendReturnRequest(req)) {" in s_sc and "isPending" not in s_sc)
    ok("货主端：接了 onAmend = { vm.askAmend(req) }", "onAmend = { vm.askAmend(req) }," in s_sc)
    ok("货主端：挂了那个弹层（ReturnRequestAmendDialog(vm)）", "ReturnRequestAmendDialog(vm)" in s_sc)
    n_dialog = sum(raw(p).count("fun ReturnRequestAmendDialog(") for p in ANDROID.rglob("*.kt"))
    ok("弹层全仓只有一份实现（现算 %d 处，必须是 1）" % n_dialog, n_dialog == 1,
       "两份实现＝两个地方各自决定「谁能改」，早晚分叉")
    n_lines = sum(raw(p).count("fun OrderReturnLines(") for p in ANDROID.rglob("*.kt"))
    ok("填数量块全仓只有一份实现（现算 %d 处，必须是 1）" % n_lines, n_lines == 1,
       "复制第二份＝上限规则出现第二份真相")
    dlg = between(kt(UI), "fun ReturnRequestAmendDialog(", NL + "@Composable")
    ok("弹层读到了（%d 字符 > 1200）" % len(dlg), len(dlg) > 1200)
    ok("弹层复用共用的填数量块 OrderReturnLines（⛔ 不复制第二份）",
       "OrderReturnLines(" in dlg and "onSetQty = { id, qty -> vm.setAmendQty(id, qty) }," in dlg)
    ok("弹层说清了改的是什么、不动什么（钱货仍在「办理退货」那一刻变）",
       "不动库存、不动账本、不影响退款" in dlg and "办理退货" in dlg)
    ok("弹层里有「原来是…」与「改后：」前后的对照", '"现在是："' in dlg and '"改后："' in dlg)
    ok("弹层把通知对象那句摆出来（用 amendNoticeLine，不自己写一遍）",
       "amendNoticeLine(vm.amendActorRole)" in dlg)
    ok("读商品的时候不装死（amendLoading / 「正在读这一单的商品…」）", "正在读这一单的商品…" in dlg)
    ok("确认按钮：改着的时候点不动，一行都没有也不给提交",
       "enabled = !vm.acting && !vm.amendLoading && vm.amendLines.isNotEmpty()," in dlg)
    ok("忙碌文案是口语（改着呢…）", "改着呢…" in dlg)
    ok("取消按钮用 cancelAmend（不直接把状态清空）", "vm.cancelAmend()" in dlg)
    ok("弹层里既有统一提示（Hint）也有表单错误行（FormErrorLine）",
       "Hint(" in dlg and "FormErrorLine(" in dlg)

    # ── 6. 两端共用的 VM ────────────────────────────────────────────────────
    section("⑥ 两端共用的 VM（ui/common/ReturnRequestsViewModel.kt）")
    vm = kt(VMS)
    ok("amendActorRole 是 public abstract（弹层是顶层函数，protected 读不到）",
       "abstract val amendActorRole: String" in vm)
    ok("两个子 VM 各 override 一次，值来自纯逻辑那一份常量",
       kt(DISP_VM).count("override val amendActorRole: String = AMEND_ACTOR_DISPATCHER") == 1
       and kt(SHIP_VM).count("override val amendActorRole: String = AMEND_ACTOR_SHIPPER") == 1)
    ask = between(vm, "fun askAmend(", "fun setAmendQty(")
    ok("askAmend 先过 canAmendReturnRequest；不是待处理就只说一句中文、不弹层",
       "if (!canAmendReturnRequest(req)) {" in ask
       and 'actionResult = "这一张已经确认过了，改不了。"' in ask)
    ok("弹层要的是能算上限的订单行（repo.order(...).orderProducts），不是申请单上那几行",
       "container.repo.order(req.orderId)" in ask and "amendMaxReturnable(it) > 0" in ask)
    ok("预填的是申请单现有数量，并夹在 0..可退上限之间",
       "picked[ln.id] ?: 0" in ask and "coerceIn(0, amendMaxReturnable(ln))" in ask)
    ok("填数量在本地夹一次（setAmendQty 也 coerceIn）", "coerceIn(0, amendMaxReturnable(" in vm)
    cf = between(vm, "fun confirmAmend(", NL + "}")
    ok("confirmAmend：本地先拦（空明细/超行），再打接口",
       "amendSubmitError(" in cf and "container.repo.amendReturnRequest(req.id, items)" in cf)
    ok("成功后刷新清单 + 口语提示（含「已给…发一条通知」）",
       "actionResult = amendDoneMessage(amendActorRole, after)" in cf and "load()" in cf)
    ok("失败原样显示后端中文（客户端不重写判据）", "amendFormError = toApiException(e).message" in cf)

    # ── 7. 接线 ─────────────────────────────────────────────────────────────
    section("⑦ 接线（Dtos / Apis / AppRepository：只加一条通路）")
    ok("Retrofit 端点：POST return-requests/{requestId}/amend + @Body ReturnRequestAmendBody",
       '@POST("return-requests/{requestId}/amend")' in raw(APIS)
       and "@Body body: ReturnRequestAmendBody," in raw(APIS))
    ok("仓库方法转发（不在这里判状态/权限）",
       "suspend fun amendReturnRequest(" in raw(REPO) and "ReturnRequestAmendBody(items = items)" in raw(REPO))
    body_dto = between(raw(DTOS), "data class ReturnRequestAmendBody(", NL + ")")
    n_fields = len(re.findall(r"(?m)^[ 	]+val ", body_dto))
    ok("请求体只有 items 一个字段（现算 %d 个；⛔ 不带 orderId：多一个入口参数就多一条改错单的路）" % n_fields,
       n_fields == 1 and "val items: List<OrderReturnItem>," in body_dto)

    # ── 8. 测试与登记 ───────────────────────────────────────────────────────
    section("⑧ 测试与登记（代码 / 判据 / 反验 / 单测 四件事）")
    be = raw(BE_TEST)
    for name, why in (("test_dispatcher_amend_changes_lines_and_notifies_shipper_once", "派单员改：明细真变 + 一条通知"),
                      ("test_shipper_amend_while_pending_then_fulfill_uses_new_quantity", "货主未确认可改，办理按新数量"),
                      ("test_amend_refused_after_done_rejected_or_withdrawn", "终态拒绝（已办理/已驳回/已撤回）"),
                      ("test_amend_refuses_empty_zero_over_cap_and_non_integer", "空明细/全 0/越界/非整数被拒"),
                      ("test_amend_swaps_product_kind_and_keeps_one_request", "换商品种类不换一张申请"),
                      ("test_amend_refuses_stranger_driver_and_missing_request", "司机 403 / 别人的 400 / 不存在 404")):
        ok("后端用例在：%s（%s）" % (name, why), ("def %s(" % name) in be)
    ok("用例断言了明细真的变了，且状态/备注没被顺手改",
       'assert got["lines"][0]["quantity"] == 3' in be
       and 'f"改明细不该动状态：' in be and 'f"改明细不该动备注：' in be)
    ok("用例断言了只产生一条通知、而且没发给改的人自己",
       '"改动通知应该只有一条，实际' in be and "派单员收到了自己改出来的通知" in be
       and "货主收到了自己改出来的通知" in be)
    ok("用例断言了审计留痕（动作码 + 改动前/改动后/改动人）",
       ".filter_by(action=OperationAction.ORDER_RETURN_REQUEST_AMEND)" in be
       and '"改动前" in (log.change_content or "")' in be and '"改动人"' in be)
    ok("用例断言了办理按改之后的数量算钱（不改钱，但钱要按新数量算）",
       'Decimal(r.json()["returned"]["returned_amount"]) == Decimal("25.00")' in be)
    ok("用例断言了终态拒绝的话术是中文（已办完 / 已驳回 / 已撤回三条路）",
       '"已经办完了" in done.text and "不能改" in done.text' in be
       and '"已经被驳回了"' in be and '"已经被申请人撤回了"' in be)
    ok("用例断言了空明细/填 0/越界/非整数被拒且都是中文",
       '"商品明细" in empty.text and "至少 1 项" in empty.text' in be
       and '"最多只能退 2"' in be and '"要填整数"' in be)
    ok("用例断言了换商品种类**不换一张申请**（⛔ 不是删了重提）",
       'f"换商品种类不该换一张申请：' in be and 'f"换种类多出了一张申请"' in be)
    ok("用例断言了越权那一次一个字节都没落地",
       "越权那次改动居然生效了" in be and "被拒的请求动到了明细" in be)
    kt_test = raw(KT_TEST)
    n_cases = len(re.findall(r"(?m)^[ 	]*@Test[ 	]*$", kt_test))
    ok("Android 单测 @Test 有 %d 条（下限 3）" % n_cases, n_cases >= 3)
    for token, why in (("只有待处理能改_已办理_已驳回_已撤回_已自动关闭都改不了", "哪些状态可改"),
                       ("派单员改了就通知货主和批发商_而且只发一条", "改动后通知谁（派单员改）"),
                       ("货主或批发商改了只通知派单员_并且说成这单发生了改动", "改动后通知谁（货主改）"),
                       ("空明细不给提交_", "空明细拦在本地")):
        ok("单测覆盖：%s（%s）" % (why, token), token in kt_test)
    nr = raw(NR)
    ok("新 type 在 NoticeRouting.kt 里有自己的常量与两支路由（派单员 / 货主各回自己那一页）",
       'const val TYPE_AMENDED = "order.return_request.amended"' in nr
       and "roleKey == Role.DISPATCHER.key && type == TYPE_AMENDED ->" in nr
       and "roleKey == Role.SHIPPER.key && type == TYPE_AMENDED ->" in nr,
       "消息点不进去 = 用户收到通知却不知道去哪一张单上办")
    # ⚠️ 不能只判「这两个字符串在不在」：shipperReturnRequests(requestId) 在文件别处还有一份（别的 type 也回我的退货申请页），
    # 只判字符串的话，把货主那支改指派单端页面（注入 ⑦）照样全绿。必须判「分支头 + 紧跟的那一页」成对。
    ok("两支路由都带 focus（点进去定位到那一张，不是列表顶上；各自指回自己那一页）",
       bool(re.search(r"roleKey == Role\.DISPATCHER\.key && type == TYPE_AMENDED ->\s*\n\s*"
                      r"Routes\.dispatcherReturnRequests\(requestId\)", nr))
       and bool(re.search(r"roleKey == Role\.SHIPPER\.key && type == TYPE_AMENDED ->\s*\n\s*"
                          r"Routes\.shipperReturnRequests\(requestId\)", nr)))
    ok("单测钉住了这条通知的去向（现算 %d 处 noticeReturnRoute）" % kt_test.count("noticeReturnRoute("),
       kt_test.count("noticeReturnRoute(") >= 3
       and "Routes.shipperReturnRequests(31)" in kt_test
       and "Routes.dispatcherReturnRequests(31)" in kt_test
       and 'assertEquals("order.return_request.amended", TYPE_AMENDED)' in kt_test)
    chg = raw(CHG)
    ok("变更单在、且写够了（%d 字符 > 3000）" % len(chg), len(chg) > 3000,
       "变更单是这一轮的交付物之一（docs/changes/_TEMPLATE.md 骨架不许删小节）")
    n_sec = len(re.findall(r"(?m)^## ", chg))
    ok("九节结构齐全（现算 %d 节，下限 9）" % n_sec, n_sec >= 9)
    for token, why in (("## ① 六问", "六问"), ("## ② Must Change", "变更边界"), ("## ③ Boundary", "四层边界"),
                       ("## ④ Behavior Contract", "行为契约"), ("## ⑤ Data Contract", "数据契约"),
                       ("## ⑥ CHG 专章", "专章"), ("## ⑦ 测试", "四件事"), ("## ⑧ 证据", "证据表"),
                       ("## ⑨ 关闭", "关闭六格"), ("a9d7250b-9722-4cef-b9f5-f13968ac4ed3", "Owner 会话 id"),
                       ("m43140", "用户口径出处"), ("2026-10-15", "开工/关闭日期")):
        ok("变更单写到：%s（%s）" % (token, why), token in chg)
    ok("README 登记了这一笔", "](CHG-0130.md)" in raw(README))
    ok("AI_WORK_CLAIM 里有这一笔的认领", "CHG-0130" in raw(CLAIM))
    rev = raw(REVERSE)
    n_inj = len(re.findall(r"(?m)^    [(][ 	]*$", rev))
    ok("反验脚本在、且注入够多（%d 条，房规下限 3）" % n_inj, REVERSE.is_file() and n_inj >= 3,
       "没有反向验证＝判据可能全是空转（改坏了也全绿）")
    ok("反验脚本有「按字节还原 + sha256 自证」那一半",
       all(t in rev for t in ("read_bytes", "write_bytes", "sha256", "anchor_preflight")),
       "还原不干净 / 不预检锚点，会把别人的在途改动一起卷进来")
    m_claim = re.search(r"（([0-9]+) 种破坏方式全被抓）", __doc__ or "")
    ok("本脚本 docstring 里声明的注入条数与反验脚本的实际条数一致"
       + ("（声明 %s，实际 %d）" % (m_claim.group(1), n_inj) if m_claim else "（声明没找到）"),
       bool(m_claim) and int(m_claim.group(1)) == n_inj,
       "对账写错了就是第二份真相")

    return finish()


if __name__ == "__main__":
    sys.exit(main())
