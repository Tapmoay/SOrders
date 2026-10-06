# -*- coding: utf-8 -*-
"""反向验证：`_tools/qa/_check_order_contact_edit.py` 的每一条判据都**真的会红** —— 台账 L-27 ＋ L-28 ＋ L-31（CHG-0057）。

## 为什么要有这一份
这一刀守的全是**静默失效**，而每一种都能编译通过、界面照画：

· 少了端点里那行 `_get_order_scoped(order_id, current, db)` —— 货主带着自己的 token 就能补**别人名下**那一单的联系信息；
· 守卫里少一行（`DISPATCHER_ONLY_FIELDS` 漏一个字段）—— 那一扇"只补联系信息"的门当场等于整张单的编辑权（改地址 / 改内部备注）；
· 终态门写成 `if` 而不是 `elif` —— 存量单（绝大多数已送达）连一个名字都补不上，「去补联系信息」变成点不动的死胡同；
· 判据写成 `any` 而不是 `all`（或者不 `strip()`）—— 风险提示满天飞，真正"账上认不出人"的单淹在里面；
· 正文里写回「被派单员修改了」—— 货主自己改的，这句话是假的。

判据脚本写得再细，只要它自己坏了（锚点漂了、正则写宽了、切段切到文件尾、期望表写错），
它**照样全绿** —— 所以这里逐条把源码改坏一次，要求判据必须报红；连**判据自己**也在注入名单里。

## 手法
- 每条：快照原文件（**按字节**）→ 字符串替换一次 → 跑判据 → 期望某条**具体**的判据变红 → 按字节还原。
- 还原之后**重新读回来逐字节比对**；不一致直接 `SystemExit(2)`（一次没还原，后面所有结论都建立在坏代码上）。
- ⛔ 全程不碰 git 的还原命令：那会把工作区里**别人**的改动一起吞掉。
- 锚点是源码片段，会随源码漂：漂了这里打 `[SKIP]`（`exit 1`），**不装成绿**。

用法：python _tools/qa/_reverse_verify_order_contact_edit.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / '_check_order_contact_edit.py'
BACKEND = ROOT / 'backend/app'
RBAC = BACKEND / 'core/rbac.py'
CAPS = BACKEND / 'core/capabilities.py'
AUDIT = BACKEND / 'core/capability_audit_coverage.py'
CMD = BACKEND / 'commands/order.py'
LIFE = BACKEND / 'api/v1/orders_lifecycle.py'
CONTACT = BACKEND / 'services/order_contact.py'
RESP = BACKEND / 'services/order_response.py'
MSG = BACKEND / 'services/message_center.py'
SCHEMA = BACKEND / 'schemas/order.py'
AND = ROOT / 'android/app/src/main/java/com/tapmoay/sorders'
DTO = AND / 'data/remote/dto/Dtos.kt'
APIS = AND / 'data/remote/api/Apis.kt'
REPO = AND / 'data/repo/AppRepository.kt'
CAPK = AND / 'core/Capabilities.kt'
EDIT = AND / 'ui/order/OrderEditInline.kt'
DETAIL = AND / 'ui/order/OrderDetailScreen.kt'
VM = AND / 'ui/order/OrderDetailViewModel.kt'
SHIP = AND / 'ui/shipper/ShipperOrdersScreen.kt'
CHG = ROOT / 'docs/changes/CHG-0057.md'
README = ROOT / 'docs/changes/README.md'
CLAIM = ROOT / 'docs/AI_WORK_CLAIM.md'

#: (说明, 文件, 原文, 替换成, 期望变红的那条判据里的关键词)
MUTATIONS = [
    (
        '货主那一格里把新门删掉（他自己补不了联系信息 —— 这一刀什么都没解决）',
        RBAC,
        '            Permission.ORDER_EDIT_CONTACT,\n',
        '',
        '货主那一格里有 ORDER_EDIT_CONTACT',
    ),
    (
        '顺手把整张单的 ORDER_EDIT 也塞进货主那一格（他就能改地址与内部备注了）',
        RBAC,
        '            Permission.ORDER_EDIT_CONTACT,\n',
        '            Permission.ORDER_EDIT_CONTACT,\n            Permission.ORDER_EDIT,\n',
        '货主那一格里没有整张单的 ORDER_EDIT',
    ),
    (
        '新权限点的值写回旧的那个（两扇门又变成一扇）',
        RBAC,
        '    ORDER_EDIT_CONTACT = "order:edit_contact"',
        '    ORDER_EDIT_CONTACT = "order:edit"',
        '权限点逐字：ORDER_EDIT_CONTACT',
    ),
    (
        'capabilities 里的 why 改短一句话（两边不再是同一句，双向对账失效）',
        CAPS,
        '        scope_why="货主只能补自己名下的单的联系信息（行级过滤按 shipper_id）",',
        '        scope_why="货主只能补自己名下的单的联系信息",',
        'capabilities 的 scope_why 与 rbac.SCOPES',
    ),
    (
        '把派单员也写进这条 Capability 的 roles（他本来就该走 BYPASS_ROLES）',
        CAPS,
        '        # ⛔ 不写 dispatcher：他走 `rbac.BYPASS_ROLES` 那条绕过，写进来判据会报红。\n        roles=("shipper",),\n',
        '        roles=("shipper", "dispatcher"),\n',
        '这一条 Capability 里不出现 dispatcher',
    ),
    (
        '能力表里的 what 换个说法（客户端能力页上那句话跟着变）',
        CAPS,
        '        what="补自己名下订单的联系信息",',
        '        what="补订单的联系信息",',
        'Capability.what 逐字',
    ),
    (
        '这条 Capability 登记的权限点写成旧的（等于没登记新门）',
        CAPS,
        '        permission="ORDER_EDIT_CONTACT",',
        '        permission="ORDER_EDIT",',
        'Capability.permission 逐字',
    ),
    (
        '审计覆盖换一个动作码（审计页上同一次改单出现两个名字）',
        AUDIT,
        "    'order:edit_contact': ('ORDER_UPDATE',),",
        "    'order:edit_contact': ('ORDER_EDIT_CONTACT',),",
        '审计覆盖复用同一个动作码',
    ),
    (
        '新端点的门换回整张单的 ORDER_EDIT（货主顺手能改地址）',
        LIFE,
        '    current: User = Depends(require_permission(Permission.ORDER_EDIT_CONTACT)),',
        '    current: User = Depends(require_permission(Permission.ORDER_EDIT)),',
        '新端点的门是 ORDER_EDIT_CONTACT',
    ),
    (
        '新端点不调 _get_order_scoped（货主带着自己的 token 就能补别人名下的单）',
        LIFE,
        '    """\n    _get_order_scoped(order_id, current, db)\n',
        '    """\n',
        '新端点先 _get_order_scoped 做归属校验',
    ),
    (
        '新端点不传 contact_only（这扇门立刻等于整张单的编辑权）',
        LIFE,
        '            db, actor=current, order_id=order_id, body=body, contact_only=True',
        '            db, actor=current, order_id=order_id, body=body',
        '新端点调 update_order 时带 contact_only=True',
    ),
    (
        '入参体换成整张单的那个（守卫那条分界线就没有依据了）',
        LIFE,
        '    body: OrderContactUpdate,',
        '    body: OrderUpdate,',
        '新端点的入参体是 OrderContactUpdate',
    ),
    (
        '能补的字段少写一个（收货人电话永远补不上）',
        CMD,
        '    "contact_dongjia_phone",\n    "contact_boss_phone",\n)',
        '    "contact_dongjia_phone",\n)',
        'CONTACT_FIELDS 就是那四个字段',
    ),
    (
        '派单员专属表漏一项（内部备注从此对货主敞开）',
        CMD,
        '    ("remark", "订单备注"),\n    ("internal_notes", "内部备注"),\n)',
        '    ("remark", "订单备注"),\n)',
        'DISPATCHER_ONLY_FIELDS 六项逐字',
    ),
    (
        '两张表混进同一个字段（分界线自相矛盾）',
        CMD,
        '    ("delivery_description", "配送说明"),\n',
        '    ("delivery_description", "配送说明"),\n    ("contact_dongjia_name", "收货人姓名"),\n',
        '两张表不相交',
    ),
    (
        '守门①删掉（四个字段一个都不给也照样走完改单）',
        CMD,
        '        if all(getattr(body, f, None) is None for f in CONTACT_FIELDS):\n            raise CommandError("没有要补的联系信息", 400)\n',
        '',
        '守门①：四个字段一个都没给',
    ),
    (
        '守门②删掉（货主能改地址 / 内部备注 —— 这是这一刀最贵的一条）',
        CMD,
        '        for field, label in DISPATCHER_ONLY_FIELDS:\n            if getattr(body, field, None) is not None:\n                raise CommandError(f"联系信息以外的内容要派单员才能改（{label}）", 403)\n',
        '',
        '守门②：联系字段以外只要给了一个',
    ),
    (
        '守门③写成 if（终态单在补联系信息这条路上被一起挡掉，红条变成死胡同）',
        CMD,
        '    elif order.status in (OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.RETURNED):',
        '    if order.status in (OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.RETURNED):',
        '守门③写成 elif',
    ),
    (
        '审计字段写死成派单员那三项（货主改了名字，日志里一个字都没有）',
        CMD,
        '    tracked = CONTACT_FIELDS if contact_only else DISPATCHER_TRACKED_FIELDS',
        '    tracked = DISPATCHER_TRACKED_FIELDS',
        '审计字段按路选',
    ),
    (
        '推送条件松掉（终态单补个名字也推给早就跑完的司机）',
        CMD,
        '    if order.driver_id and not (contact_only and finished):',
        '    if order.driver_id:',
        '推送条件：终态单在补联系信息这条路不推',
    ),
    (
        '风险判据用 any（只要有一个名字空就报红：提示满天飞，真无主的单淹在里面）',
        CONTACT,
        '    return all(contact_name_blank(getattr(order, f, None)) for f in CONTACT_NAME_FIELDS)',
        '    return any(contact_name_blank(getattr(order, f, None)) for f in CONTACT_NAME_FIELDS)',
        'contact_risk_of 全部看空才算无人认领',
    ),
    (
        '不算空白（全是空格的姓名被当成"填了"，与账本页的 trim 口径分家）',
        CONTACT,
        '    return not (value or "").strip()',
        '    return not (value or "")',
        'contact_name_blank 只去空白',
    ),
    (
        '把电话也拉进判据（与账本页 _customer_name_expr 的口径分家）',
        CONTACT,
        'CONTACT_NAME_FIELDS: tuple[str, ...] = ("contact_dongjia_name", "contact_boss_name")',
        'CONTACT_NAME_FIELDS: tuple[str, ...] = ("contact_dongjia_name", "contact_boss_name", "contact_boss_phone")',
        'CONTACT_NAME_FIELDS 只看两个姓名',
    ),
    (
        '出参里不调服务（客户端那个布尔值永远是 False，红条永远不亮）',
        RESP,
        '    data["contact_risk"] = contact_risk_of(order)',
        '    data["contact_risk"] = False',
        'enrich_order_out 里写 data[contact_risk]',
    ),
    (
        '站内信正文写回「被派单员修改了」（货主自己改的，这句话是假的）',
        MSG,
        '        content=f"订单 {ono} 的收货信息或货物明细有改动，出车前请打开订单详情核对一遍。",',
        '        content=f"订单 {ono} 被派单员修改了，出车前请打开订单详情核对一遍。",',
        '正文逐字',
    ),
    (
        '出参默认 True（老数据一上线全变成「账上认不出人」）',
        SCHEMA,
        '    contact_risk: bool = False',
        '    contact_risk: bool = True',
        '出参模型里有 contact_risk: bool = False',
    ),
    (
        'DTO 里删掉这一格（服务端说的事客户端看不见）',
        DTO,
        '    @SerialName("contact_risk") val contactRisk: Boolean = false,\n',
        '',
        'DTO 有 contact_risk',
    ),
    (
        'Api 的路径写错（打回整张单那个端点上去）',
        APIS,
        '    @PATCH("orders/{orderId}/contact")',
        '    @PATCH("orders/{orderId}")',
        'Api 有 PATCH orders/{orderId}/contact',
    ),
    (
        '仓库转调旧方法（界面看着像补联系信息，实际走的是整张单的门）',
        REPO,
        '        api.orderApi.updateOrderContact(orderId, body)',
        '        api.orderApi.updateOrder(orderId, body)',
        '仓库转调新方法',
    ),
    (
        '生成的能力表里把新门删掉（客户端那颗按钮对谁都不出现）',
        CAPK,
        '        "order:edit_contact" to "补自己名下订单的联系信息",\n',
        '',
        '生成的能力表里有新门',
    ),
    (
        '详情页的能力门换成整张单那把（界面又回到"只有派单员能改"）',
        DETAIL,
        '    val canEditContact = canEditOrderContact(role)',
        '    val canEditContact = canEditInfo',
        '详情页的能力门走 canEditOrderContact',
    ),
    (
        '那一问的权限键写回整张单那个（门又开始问错问题）',
        EDIT,
        'fun canEditOrderContact(role: Role): Boolean = Capabilities.can(role.key, "order:edit_contact")',
        'fun canEditOrderContact(role: Role): Boolean = Capabilities.can(role.key, "order:edit")',
        '那一问只有一处：canEditOrderContact 问的是',
    ),
    (
        '红条的条件改掉（账上认不出人这件事又不显示了）',
        DETAIL,
        '                if (order.contactRisk) {\n                    Spacer(Modifier.height(10.dp))',
        '                if (false) {\n                    Spacer(Modifier.height(10.dp))',
        '详情页在 contactRisk 时出红条',
    ),
    (
        '红条里那颗按钮进的是备注那一栏（点了「去补联系信息」，开的是备注框）',
        DETAIL,
        '                        TextButton(onClick = { edit.startEdit(OrderEditField.CONTACT) }, enabled = !edit.editBusy) {',
        '                        TextButton(onClick = { edit.startEdit(OrderEditField.REMARK) }, enabled = !edit.editBusy) {',
        '红条里那颗按钮进的是 OrderEditField.CONTACT',
    ),
    (
        '编辑栏不挂到详情页上（面板写好了，永远打不开）',
        DETAIL,
        '                if (edit.editingField == OrderEditField.CONTACT) {\n                    ContactFillPanel(edit)\n                }\n',
        '',
        '编辑栏挂在详情页上',
    ),
    (
        '编辑字段常量的值改掉（分流与挂载两边对不上，点了没反应）',
        EDIT,
        '    const val CONTACT = "contact"',
        '    const val CONTACT = "contact_info"',
        '编辑字段常量 CONTACT = contact',
    ),
    (
        'VM 的 saveEdit 不再分流（补联系信息走整张单那条路）',
        VM,
        '        if (editingField == OrderEditField.CONTACT) {\n            saveContactOnly(o)\n            return\n        }\n',
        '',
        'VM 的 saveEdit 在函数头分流给 saveContactOnly',
    ),
    (
        '补联系信息这条路走了旧方法（后端那道门根本收不到这四个字段）',
        VM,
        '                order = container.repo.updateOrderContact(',
        '                order = container.repo.updateOrder(',
        '补联系信息这条路走 updateOrderContact',
    ),
    (
        '两个电话改回必填（要不到电话的单永远补不上 —— 用户报的就是这个）',
        VM,
        '        InputRules.phoneError(phoneDraft, required = false)?.let { editError = it; return }\n        InputRules.phoneError(bossDraft, required = false)?.let { editError = it; return }',
        '        InputRules.phoneError(phoneDraft)?.let { editError = it; return }\n        InputRules.phoneError(bossDraft)?.let { editError = it; return }',
        '两个电话在这条路上都是选填',
    ),
    (
        '成功语又承诺「司机那边会收到一条消息」（终态单后端根本不推）',
        VM,
        '                actionResult = "联系信息已经补上"',
        '                actionResult = "已经改好，司机那边会收到一条消息"',
        '成功后的话里不承诺',
    ),
    (
        '货主订单卡左边那颗红标删掉（列表上再也看不出哪一单没主）',
        SHIP,
        '                                    if (order.contactRisk) {\n                                        CardActionIcon(',
        '                                    if (false) {\n                                        CardActionIcon(',
        '货主订单卡左边那颗红标',
    ),
    (
        '判据自己把「恰好 3 处」写成 4（判据写错时它必须自己报红，而不是静默全绿）',
        CHECK,
        '       len(hits) == 3, str(hits))',
        '       len(hits) == 4, str(hits))',
        '客户端只读这个布尔值',
    ),
    (
        'CHG-0057.md 的 Boundary 结论降级成 L2（红线与反验都钉着这一句）',
        CHG,
        '- **结论**：**CORE（补联系信息这一扇门）＋ INFRASTRUCTURE（新增权限点与能力表登记）**，Blast Radius **L1**',
        '- **结论**：**CORE（补联系信息这一扇门）＋ INFRASTRUCTURE（新增权限点与能力表登记）**，Blast Radius **L2**',
        'CHG-0057.md 的 Boundary 结论逐字',
    ),
    (
        'CHG-0057.md 里把 m01199 那次裁定写丢（存量口径的出处没了）',
        CHG,
        'm01199',
        'm01198',
        'CHG-0057.md 里提到 m01199',
    ),
    (
        'README 的登记簿那一行指到不存在的文件（死链）',
        README,
        '| [CHG-0057.md](CHG-0057.md) |',
        '| [CHG-0057.md](CHG-0058.md) |',
        'README 的登记簿有本刀那一行',
    ),
]


def snapshot(p: Path) -> bytes:
    """按**字节**快照（不是按文本：文本层归一过行尾，写回去就变了一次格式）。"""
    return p.read_bytes()


def mutate(p: Path, old: str, new: str) -> int:
    """把 `old` 换成 `new`，返回换了几处（0 = 锚点漂了）。

    ⚠️ 行尾：读到 CRLF 就先归一成 LF 再替换，写回时**按原来的行尾风格**还原 —— 否则一棵 CRLF 的
    Kotlin 文件会被写成 LF（`git status` 里看不出来，但字节确实变了）。
    """
    raw = p.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8")
    if crlf:
        text = text.replace("\r\n", "\n")
    n = text.count(old)
    if n == 0:
        return 0
    text = text.replace(old, new)
    p.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
    return n


def restore(p: Path, original: bytes) -> None:
    """按字节写回（不是「把替换反着做一遍」—— 那要求替换是可逆的，而它不必是）。"""
    p.write_bytes(original)


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def hit(out: str, want: str) -> bool:
    """判据的失败行必须是 `  [!!]   {label}` 这个形状（反向验证只认它）。"""
    return ("[!!]   " + want) in out


def main() -> int:
    files = [RBAC, CAPS, AUDIT, CMD, LIFE, CONTACT, RESP, MSG, SCHEMA, DTO, APIS, REPO, CAPK,
             EDIT, DETAIL, VM, SHIP, CHECK, CHG, README, CLAIM]
    missing = [str(p) for p in files if not p.exists()]
    if missing:
        print("❌ 前提不成立：这些文件还不存在 —— " + "、".join(missing))
        return 2
    snaps = {str(p): snapshot(p) for p in files}
    code0, out0 = run_check()
    if code0 != 0:
        print("❌ 前提不成立：判据现在不是全绿，先让它全绿再来跑反向验证。尾部输出：")
        print(out0[-2000:])
        return 2
    print("前提：判据 " + str(out0.count("[OK]")) + " 项全绿 ✅；开始逐条注入坏代码。\n")
    ok = 0
    bad: list[str] = []
    skipped: list[str] = []
    try:
        for i, (why, path, old, new, want) in enumerate(MUTATIONS, 1):
            n = mutate(path, old, new)
            if n == 0:
                print("[SKIP] " + f"{i:2d}. " + why + " —— 锚点在这个文件里出现 0 次，无法注入")
                skipped.append(why)
                continue
            try:
                code, out = run_check()
            finally:
                restore(path, snaps[str(path)])
            if code != 0 and hit(out, want):
                print("  [OK] " + f"{i:2d}. " + why + " —— 「" + want + "」报红了")
                ok += 1
            else:
                print("  [!!] " + f"{i:2d}. " + why + " —— 期望「" + want + "」报红，实际 "
                      + ("判据仍然全绿（这一条是**假的**）" if code == 0 else "报红的是别的一条"))
                bad.append(why)
    finally:
        for k, v in snaps.items():
            restore(Path(k), v)

    dirty = [k for k, v in snaps.items() if Path(k).read_bytes() != v]
    if dirty:
        print("❌ 还原不干净（重新读回来与快照字节不一致）：" + "、".join(dirty))
        return 2
    code1, out1 = run_check()
    if code1 != 0:
        print("❌ 还原之后判据不是全绿（说明有文件被写坏了）：")
        print(out1[-2000:])
        return 2
    print("\n还原：" + str(len(files)) + " 个文件都按字节比对一致，判据重新全绿 ✅")
    print("=" * 60)
    if bad or skipped:
        print("❌ " + str(len(bad)) + " 条没被抓到、" + str(len(skipped)) + " 条锚点漂了（共 "
              + str(len(MUTATIONS)) + " 条）")
        return 1
    print("✅ " + str(ok) + "/" + str(len(MUTATIONS)) + " 全部成立：每条注入都被对应判据抓到，"
          + "且源码按字节还原。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
