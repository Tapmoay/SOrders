
'''红线：货主自己补联系信息那一扇门（台账 L-27 ＋ L-28 ＋ L-31 ⇒ CHG-0057）。

## 由来（用户 2026-10-06 只读排查台账 `_tmp/USER_BUG_LEDGER_20261006.md` 的 L-27 / L-28 / L-31）
- **L-27 口述（ref m00846）**：「派单员代客下单了，有时候不知道收货人信息是谁、电话要不到，就是要不到。」
  ＋「批发商（代理批发商 / 代货主下单）在订单详情里也可以手动地更改和填写。」
- **L-27 口径补充（ref m01132）**：「…他要自己去解决这个异常订单 —— 他要给这个订单去定性、
  **自己去写一个收货人**，哪怕是个名字。当然，这个收货人他可以去**调用他自己的那个收货人列表**，
  也可以**新建一个收货人**，都是一样的，**我们这些代码是可以复用的**。」
- **L-28 口述（ref m00846）**：「不填联系人这账就变成无主账了。」＋「所以批发商或者货主要有个异常订单，
  告诉他可能会出现无主账 / 可能出问题。」
- **L-28 口径补充（m01132）**：判据收窄为「**收货人与下单人都空**」；**m01199 最终裁定**：存量里四个联系字段
  全空的单要能在**异常订单**里看见并补上，走**查询期自动判据**、**零落库零迁移**，⛔ **不批量写 `is_exception`**。
- **L-31 裁定（m01132）**：A / B / C 三案**全部作废**；账本顶上两段照旧并列
  （`ui/shipper/ShipperLedgerScreen.kt:404-504` **不动**）⇒ L-31 只作 L-27＋L-28 的**动机**，不单独改代码。

## 为什么必须有一条红线盯着它
1. 「整张单的编辑权」（`ORDER_EDIT`，scope=all，派单员）与「只补联系信息」（`ORDER_EDIT_CONTACT`，
   scope=own，货主）是**两个**权限点。一旦有人图省事把上一条加进货主那一格，货主顺手就能改送货地址
   （＝司机跑错地方）与内部备注、**还能改别人名下的单** —— 手机上看不出任何异常，直到账对不上。
2. 端点上少一行 `_get_order_scoped`，货主带着自己的 token 就能补**别人名下**那一单的联系信息（行级越权）。
3. 命令层的 `contact_only` 守卫是**唯一**那道「只准四个字段」的线：`DISPATCHER_ONLY_FIELDS` 漏一个字段
   （例如 `internal_notes`），货主就能写内部备注 —— 又是「坏了不报错」的形状。
4. 「账上认不出人」这个布尔值只许有**一处**算法（`services/order_contact.py::contact_risk_of`）；
   客户端再判一遍，两边口径漂开之后谁对谁错没人知道。
5. 终态单不该再推站内信（司机早跑完了），推过去只是噪音。
6. 站内信正文原先写死「被派单员修改了」；货主自己也能改之后，写死角色就是对他说的假话。

R4-BOUNDARY-JUSTIFICATION: 权限面从「整张单」（ORDER_EDIT / scope=all / 派单员）切出「只补联系信息」
（ORDER_EDIT_CONTACT / scope=own / 货主 ＋ 绕过的派单员），新增一个只读导出布尔值 contact_risk；
不改数据模型、不落库、不做迁移、不动状态机、不动算法 —— Blast Radius L1（主，局部行为）。

## 判据（清单全部自己算；路径写错会先在「读到几个文件」那条报红）
1. rbac：权限点逐字、货主那一格有它、派单员/司机那两格没有它、SCOPES 与 capabilities 的 scope_why 逐字相同。
2. capabilities ＋ 审计覆盖：Capability 五格逐字、段内不出现 dispatcher、动作码复用 `ORDER_UPDATE`。
3. 端点：路径 `/contact`、门是 `ORDER_EDIT_CONTACT`、`_get_order_scoped` 在 `update_order` **之前**、
   `contact_only=True`；旧端点一个字没动（仍是 `ORDER_EDIT`、不传 `contact_only`）。
4. 命令层：三个常量逐字；**自算补集** —— `DISPATCHER_ONLY_FIELDS ∪ CONTACT_FIELDS == OrderUpdate 的字段全集`
   （不手写第二份清单）；三道守门逐字与顺序；`tracked` 按路选；终态单不推。
5. 出参：`contact_risk_of` 唯一实现；`contact_name_blank` 的 strip 口径；`OrderOut.contact_risk`；Kotlin 侧不重判。
6. 站内信：正文逐字且不再写死「被派单员」，其余六项（标题 / type / payload / speech / 幂等键 / 实时推送）没动。
7. Android 七处 ＋ `OrderEditHost` 新成员在 VM 里全有实现 ＋ 这条路**不承诺**「司机能收到消息」。
8. 别人的东西没碰：派单员那条路仍是 `ORDER_EDIT`；账本页零新增；四处 `EditHint(` 仍以 `canEditInfo` 为门；
   AI 侧不在本刀（判据在这里把口径钉住）。
9. 防空转 ＋ 文档（CHG-0057.md 九节 / README 行 / CLAIM 条目 / 反验注入条数）。

⚠️ 注入式反向验证（改坏 → 本脚本必须红，改回 → 绿）：
   python _tools/qa/_reverse_verify_order_contact_edit.py
用法：python _tools/qa/_check_order_contact_edit.py
'''
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 剥 Kotlin 注释的实现只此一份（复用兄弟红线，不抄第二份）。
from _check_pagination_wiring import strip_comments  # noqa: E402
#: 剥 Python 注释 / 文档字符串（换成等长空格、保留行号）。
from _check_single_source import code_only  # noqa: E402
#: 失败行 / 章节标题的形状只此一份（房规）：失败行是 "  [!!]   <标题>"。
from _check_hints import Checker  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / 'backend'
ANDROID = ROOT / 'android/app/src/main/java/com/tapmoay/sorders'
QA = ROOT / '_tools/qa'

RBAC = BACKEND / 'app/core/rbac.py'
CAPS = BACKEND / 'app/core/capabilities.py'
AUDIT = BACKEND / 'app/core/capability_audit_coverage.py'
SCHEMA = BACKEND / 'app/schemas/order.py'
CONTACT = BACKEND / 'app/services/order_contact.py'
RESP = BACKEND / 'app/services/order_response.py'
MSG = BACKEND / 'app/services/message_center.py'
LIFE = BACKEND / 'app/api/v1/orders_lifecycle.py'
CMD = BACKEND / 'app/commands/order.py'

DTO = ANDROID / 'data/remote/dto/Dtos.kt'
APIS = ANDROID / 'data/remote/api/Apis.kt'
REPO = ANDROID / 'data/repo/AppRepository.kt'
EDIT = ANDROID / 'ui/order/OrderEditInline.kt'
DETAIL = ANDROID / 'ui/order/OrderDetailScreen.kt'
VM = ANDROID / 'ui/order/OrderDetailViewModel.kt'
SHIP = ANDROID / 'ui/shipper/ShipperOrdersScreen.kt'
CAPK = ANDROID / 'core/Capabilities.kt'
LEDGER = ANDROID / 'ui/shipper/ShipperLedgerScreen.kt'
AIWRITE = ANDROID / 'ai/AiWrite.kt'

CHG = ROOT / 'docs/changes/CHG-0057.md'
CHG_README = ROOT / 'docs/changes/README.md'
CLAIM = ROOT / 'docs/AI_WORK_CLAIM.md'
REV = QA / '_reverse_verify_order_contact_edit.py'
DETAIL_CHECK = QA / '_check_detail_inline_edit.py'
DETAIL_REV = QA / '_reverse_verify_detail_inline_edit.py'
HINT_CATALOG = ROOT / 'docs/PROJECT_MAP/09A_HINT_CATALOG.md'

#: 逐字：CHG-0057.md 的「③ Boundary」第一行必须是这一句（判据与反验都用它当锚点）。
BOUNDARY_LINE = (
    '- **结论**：**CORE（补联系信息这一扇门）＋ INFRASTRUCTURE（新增权限点与能力表登记）**，'
    'Blast Radius **L1**'
)

#: 逐字：站内信正文（货主自己也能改之后，不再写死「被派单员修改了」）。
MSG_CONTENT = (
    '     content=f"订单 {ono} 的收货信息或货物明细有改动，出车前请打开订单详情核对一遍。",'
)

#: 逐字：命令层三张表（顺序即入参顺序即审计 before/after 顺序）。
WANT_CONTACT = [
    'contact_dongjia_name',
    'contact_boss_name',
    'contact_dongjia_phone',
    'contact_boss_phone',
]
WANT_ONLY = [
    ('delivery_description', '配送说明'),
    ('address_detail', '送货地址'),
    ('address_lat', '送货地址坐标'),
    ('address_lng', '送货地址坐标'),
    ('remark', '订单备注'),
    ('internal_notes', '内部备注'),
]
WANT_TRACKED = ['delivery_description', 'address_detail', 'remark']

#: 被点名的文件都必须在（少一个就先报红，不静默空转）。
REQUIRED = [
    RBAC, CAPS, AUDIT, SCHEMA, CONTACT, RESP, MSG, LIFE, CMD,
    DTO, APIS, REPO, EDIT, DETAIL, VM, SHIP, CAPK, LEDGER, AIWRITE,
    CHG, CHG_README, CLAIM, REV,
]

C = Checker()


def ok(label: str, cond: bool, detail: str = '') -> None:
    C.ok(label, cond, detail)


def section(title: str) -> None:
    C.section(title)


def py(path: Path) -> str:
    '''后端文件：注释与文档字符串已剥（保留行号）。'''
    return code_only(path.read_text(encoding='utf-8')) if path.is_file() else ''


def kt(path: Path) -> str:
    '''Kotlin 文件：注释已剥。'''
    return strip_comments(path.read_text(encoding='utf-8')) if path.is_file() else ''


def raw(path: Path) -> str:
    '''原样读（注释也留着）：文档与反验脚本要看人写的字。'''
    return path.read_text(encoding='utf-8') if path.is_file() else ''


def between(src: str, start: str, end: str) -> str:
    '''从 start 之后到下一个 end 之间的源码。空串 = 找不到 start。'''
    i = src.find(start)
    if i < 0:
        return ''
    i += len(start)
    j = src.find(end, i)
    return src[i:] if j < 0 else src[i:j]


def py_section(path: Path, name: str) -> str:
    '''后端某个**顶层函数**的源码段（到下一个顶层 def/class 为止）。空串 = 找不到。'''
    src = py(path)
    m = re.search(rf'(?m)^(?:async )?def {re.escape(name)}\(', src)
    if not m:
        return ''
    tail = src[m.end():]
    nxt = re.search(r'(?m)^(?:async )?def |^class ', tail)
    return src[m.start(): m.end() + (nxt.start() if nxt else len(tail))]


def py_class(path: Path, name: str) -> str:
    '''后端某个**顶层类**的源码段（到下一个顶层 class/def 为止）。空串 = 找不到。'''
    src = py(path)
    m = re.search(rf'(?m)^class {re.escape(name)}\b', src)
    if not m:
        return ''
    tail = src[m.end():]
    nxt = re.search(r'(?m)^class |^(?:async )?def ', tail)
    return src[m.start(): m.end() + (nxt.start() if nxt else len(tail))]


def block(path: Path, name: str) -> str:
    '''模块级赋值块的源码：从 NAME: ... = ( 到与之配平的 )。空串 = 找不到。'''
    src = py(path)
    m = re.search(rf'(?m)^{re.escape(name)}[^=\n]*= \(', src)
    if not m:
        return ''
    i = src.rfind('(', m.start(), m.end())
    depth = 0
    for j in range(i, len(src)):
        if src[j] == '(':
            depth += 1
        elif src[j] == ')':
            depth -= 1
            if depth == 0:
                return src[i: j + 1]
    return ''


def flat_items(path: Path, name: str) -> list[str]:
    '''模块级字符串元组里的字段名（顺序即源码顺序）。'''
    return re.findall(r'"([a-z_][a-z0-9_]*)"', block(path, name))


def pair_items(path: Path, name: str) -> list[tuple[str, str]]:
    '''模块级 (字段, 标签) 元组表。'''
    return re.findall(r'\(\s*"([a-z_]+)",\s*"([^"]*)"\s*\)', block(path, name))


def order_update_fields() -> list[str]:
    '''OrderUpdate 的字段清单（**从类体自己算**，不手写第二份）。'''
    return re.findall(r'(?m)^    ([a-z_][a-z0-9_]*)\s*:', py_class(SCHEMA, 'OrderUpdate'))


def kt_hits(needle: str) -> list[str]:
    '''Android 源码树里包含 needle 的 .kt 文件（相对路径；注释已剥）。'''
    out = []
    for p in sorted(ANDROID.rglob('*.kt')):
        if needle in strip_comments(p.read_text(encoding='utf-8')):
            out.append(p.relative_to(ROOT).as_posix())
    return out


def py_hits(needle: str) -> list[str]:
    '''后端 app/ 里包含 needle 的 .py 文件（相对路径；注释与文档字符串已剥）。'''
    out = []
    for p in sorted((BACKEND / 'app').rglob('*.py')):
        if needle in code_only(p.read_text(encoding='utf-8')):
            out.append(p.relative_to(ROOT).as_posix())
    return out


def main() -> int:
    section('0. 被点名的文件（少一个就先报红，不静默空转）')
    missing = [str(p.relative_to(ROOT)) for p in REQUIRED if not p.is_file()]
    ok(f'被点名的 {len(REQUIRED)} 个文件都在', not missing, '缺：' + '、'.join(missing))
    ok('python 源码树非空（防空转）', len(list((BACKEND / 'app').rglob('*.py'))) >= 100)
    ok('Android 源码树非空（防空转）', len(list(ANDROID.rglob('*.kt'))) >= 60)

    rbac = py(RBAC)
    caps = py(CAPS)
    cmd = py(CMD)
    life = py(LIFE)
    schema = py(SCHEMA)

    section('1. rbac：新门只开给货主，两条门分得开')
    ok('权限点逐字：ORDER_EDIT_CONTACT = "order:edit_contact"',
       'ORDER_EDIT_CONTACT = "order:edit_contact"' in rbac)
    i_old = rbac.find('ORDER_EDIT = "order:edit"')
    i_new = rbac.find('ORDER_EDIT_CONTACT = "order:edit_contact"')
    ok('新权限点紧跟在旧权限点之后（贴在一起才看得出这是两条不同的门）',
       0 <= i_old < i_new, f'ORDER_EDIT@{i_old} / ORDER_EDIT_CONTACT@{i_new}')
    shipper = between(rbac, '"shipper": frozenset(', '"driver": frozenset(')
    driver = between(rbac, '"driver": frozenset(', '"dispatcher": frozenset(')
    dispatcher = between(rbac, '"dispatcher": frozenset(', '\n}')
    ok('货主那一格里有 ORDER_EDIT_CONTACT', 'Permission.ORDER_EDIT_CONTACT,' in shipper)
    ok('货主那一格里没有整张单的 ORDER_EDIT（一个字都不许有）',
       'Permission.ORDER_EDIT,' not in shipper)
    ok('派单员那一格里没有 ORDER_EDIT_CONTACT（他走 BYPASS_ROLES 那条绕过进来）',
       'ORDER_EDIT_CONTACT' not in dispatcher)
    ok('司机那一格里没有 ORDER_EDIT_CONTACT', 'ORDER_EDIT_CONTACT' not in driver)
    ok('旧权限点 ORDER_EDIT 仍在派单员那一格里（他的路一个字没动）',
       'Permission.ORDER_EDIT,' in dispatcher)
    scope_why = '货主只能补自己名下的单的联系信息（行级过滤按 shipper_id）'
    ok('SCOPES 里给新门写了 own ＋ 一句 why（逐字）',
       f'Permission.ORDER_EDIT_CONTACT: ("own", "{scope_why}"),' in rbac)
    ok('capabilities 的 scope_why 与 rbac.SCOPES 的那句逐字相同（双向对账的两边）',
       f'scope_why="{scope_why}",' in caps)

    section('2. capabilities ＋ 审计覆盖：登记的是门，不是动作')
    ok('Capability.permission 逐字', 'permission="ORDER_EDIT_CONTACT",' in caps)
    ok('Capability.what 逐字', 'what="补自己名下订单的联系信息",' in caps)
    ok('Capability.scope = own', 'scope="own",' in caps)
    ok('Capability.kind = write', 'kind="write",' in caps)
    ok('Capability.roles = ("shipper",)（派单员不写进来，他走绕过）',
       'roles=("shipper",),' in caps)
    cap_block = between(caps, 'permission="ORDER_EDIT_CONTACT",', 'Capability(')
    ok('这一条 Capability 里不出现 dispatcher（写了判据会报红）',
       'dispatcher' not in cap_block, cap_block.strip()[:60])
    ok('能力表里 Capability 条数没被删（防空转）', caps.count('Capability(') >= 20)
    ok('审计覆盖复用同一个动作码：order:edit_contact -> ORDER_UPDATE',
       "    'order:edit_contact': ('ORDER_UPDATE',)," in py(AUDIT))

    section('3. 端点：先做归属校验，再走进同一份改单实现')
    ep = between(life, 'def update_order_contact(', '@router.')
    ok('新端点路径逐字：/{order_id}/contact',
       '@router.patch("/{order_id}/contact", response_model=OrderOut)' in life)
    ok('新端点的门是 ORDER_EDIT_CONTACT（不是 ORDER_EDIT）',
       'require_permission(Permission.ORDER_EDIT_CONTACT)' in ep)
    ok('新端点的入参体是 OrderContactUpdate', 'body: OrderContactUpdate,' in ep)
    ok('新端点先 _get_order_scoped 做归属校验（少了这行货主能补别人名下的单）',
       '_get_order_scoped(order_id, current, db)' in ep)
    ok('归属校验在 update_order 之前（顺序反了等于没校验）',
       -1 < ep.find('_get_order_scoped(') < ep.find('order_commands.update_order('))
    ok('新端点调 update_order 时带 contact_only=True', 'contact_only=True' in ep)
    old_ep = between(life, 'def update_order(', 'def update_order_contact(')
    ok('旧端点的门仍是 ORDER_EDIT（派单员那条路一个字没动）',
       'require_permission(Permission.ORDER_EDIT)' in old_ep)
    ok('旧端点不传 contact_only（它还是整张单的门）', 'contact_only' not in old_ep)

    section('4. 命令层：三张表 ＋ 三道守门（唯一那道只准四个字段的线）')
    contact_items = flat_items(CMD, 'CONTACT_FIELDS')
    only_items = pair_items(CMD, 'DISPATCHER_ONLY_FIELDS')
    tracked_items = flat_items(CMD, 'DISPATCHER_TRACKED_FIELDS')
    fields = order_update_fields()
    ok('CONTACT_FIELDS 就是那四个字段（姓名两对，顺序即入参顺序）',
       contact_items == WANT_CONTACT, str(contact_items))
    ok('DISPATCHER_ONLY_FIELDS 六项逐字（这张表就是两条门的分界线本身）',
       only_items == WANT_ONLY, str(only_items))
    ok('DISPATCHER_TRACKED_FIELDS 三项（派单员那条路的审计字段行为冻结）',
       tracked_items == WANT_TRACKED, str(tracked_items))
    ok('OrderUpdate 的字段清单自己算出来是 10 个', len(fields) == 10, str(fields))
    ok('自算补集：六个派单员专属字段 ∪ 四个联系字段 == OrderUpdate 的全部字段（漏一个就是红的）',
       {f[0] for f in only_items} | set(contact_items) == set(fields),
       str(sorted(set(fields) - ({f[0] for f in only_items} | set(contact_items)))))
    ok('两张表不相交（同一个字段不许同时属于两条门）',
       not ({f[0] for f in only_items} & set(contact_items)))
    fn = py_section(CMD, 'update_order')
    ok('update_order 有 contact_only 开关（默认 False = 派单员那条老路）',
       'contact_only: bool = False' in fn)
    ok('终态先算好 finished（推送条件要用它）',
       'finished = order.status in (OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.RETURNED)' in fn)
    ok('守门①：四个字段一个都没给 ⇒ 400 没有要补的联系信息',
       'if all(getattr(body, f, None) is None for f in CONTACT_FIELDS):' in fn
       and 'raise CommandError("没有要补的联系信息", 400)' in fn)
    ok('守门②：联系字段以外只要给了一个 ⇒ 403（fail-closed）',
       'for field, label in DISPATCHER_ONLY_FIELDS:' in fn
       and 'raise CommandError(f"联系信息以外的内容要派单员才能改（{label}）", 403)' in fn)
    ok('守门③写成 elif（写成 if 会让终态单在补联系信息这条路也被放行；判据按这个形状对账）',
       'elif order.status in (OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.RETURNED):' in fn
       and 'raise CommandError("订单已结束，不可再编辑")' in fn)
    i1 = fn.find('if all(getattr(body, f, None) is None for f in CONTACT_FIELDS):')
    i2 = fn.find('for field, label in DISPATCHER_ONLY_FIELDS:')
    i3 = fn.find('elif order.status in (')
    ok('三道守门的顺序：先看有没有可改的、再看有没有越界、最后才看状态',
       -1 < i1 < i2 < i3, f'{i1}/{i2}/{i3}')
    ok('审计字段按路选：tracked = CONTACT_FIELDS if contact_only else DISPATCHER_TRACKED_FIELDS',
       'tracked = CONTACT_FIELDS if contact_only else DISPATCHER_TRACKED_FIELDS' in fn)
    ok('before/after 都用 tracked（不再写死那三项）',
       'before = {f: getattr(order, f) for f in tracked}' in fn
       and 'after = {f: getattr(order, f) for f in tracked}' in fn)
    ok('推送条件：终态单在补联系信息这条路不推（司机早跑完了）',
       'if order.driver_id and not (contact_only and finished):' in fn)
    ok('推送仍在 commit 之前（同一事务，不会丢）',
       -1 < fn.find('outbox.enqueue(db, "orders.edited"') < fn.find('db.commit()'))

    section('5. 出参：一个布尔值，只有一处算法')
    svc = py(CONTACT)
    ok('CONTACT_NAME_FIELDS 只看两个姓名（电话为空不改变这件事）',
       flat_items(CONTACT, 'CONTACT_NAME_FIELDS') == ['contact_dongjia_name', 'contact_boss_name'])
    ok('contact_name_blank 只去空白（与 _customer_name_expr 的 nullif(trim(...)) 同一个判法）',
       'return not (value or "").strip()' in svc)
    ok('contact_risk_of 全部看空才算无人认领（all，不是 any）',
       'return all(contact_name_blank(getattr(order, f, None)) for f in CONTACT_NAME_FIELDS)' in svc)
    ok('contact_name_blank 全仓只有这一处实现（别的文件不许有第二个判法）',
       py_hits('contact_name_blank') == ['backend/app/services/order_contact.py'],
       str(py_hits('contact_name_blank')))
    resp = py(RESP)
    ok('order_response 从服务里取那个函数（不是自己再写一遍）',
       'from app.services.order_contact import contact_risk_of' in resp)
    ok('enrich_order_out 里写 data[contact_risk] = contact_risk_of(order)',
       'data["contact_risk"] = contact_risk_of(order)' in py_section(RESP, 'enrich_order_out'))
    ok('出参模型里有 contact_risk: bool = False（默认 False = 老数据不炸）',
       'contact_risk: bool = False' in schema)
    ok('contact_risk_of 只在定义处与出参处出现（没有第三处自己算一遍）',
       py_hits('contact_risk_of') == [
           'backend/app/services/order_contact.py',
           'backend/app/services/order_response.py',
       ],
       str(py_hits('contact_risk_of')))

    section('6. 站内信：正文不再写死角色，其余六项没动')
    ok('正文逐字（不猜改的是哪一处，只让他去详情核对）', MSG_CONTENT in py(MSG))
    ok('全后端不再有「被派单员修改了」这句假话', not py_hits('被派单员修改了'))
    push = py_section(MSG, 'publish_order_edited_driver')
    ok('标题仍是「订单信息有修改」', 'title="订单信息有修改",' in push)
    ok('type 仍是 order.edited（客户端只重拉列表的那条路）', 'type="order.edited",' in push)
    ok('payload 仍是 order_id ＋ order_no 两项',
       'payload={"order_id": order_id, "order_no": ono},' in push)
    ok('仍是重要语音（出车前核对）', 'speech_important=True,' in push)
    ok('幂等键仍带 event_id（同一单的不同次改动不会被吞）',
       'idem_key=f"order.edited" + ":" + str(order_id) + ":" + str(driver_id) + ":" + str(event_id),' in push)
    ok('仍实时推 order.updated 给司机',
       'await emit_realtime(driver_id, {"type": "order.updated", "order_id": order_id})' in push)

    section('7. Android：七处 ＋ 宿主新成员全有实现')
    ok('DTO 有 contact_risk（客户端只读）',
       '@SerialName("contact_risk") val contactRisk: Boolean = false,' in kt(DTO))
    ok('Api 有 PATCH orders/{orderId}/contact 的新方法',
       '@PATCH("orders/{orderId}/contact")' in kt(APIS)
       and 'suspend fun updateOrderContact(@Path("orderId") orderId: Long, @Body body: OrderUpdateRequest): OrderDto' in kt(APIS))
    ok('仓库转调新方法（薄薄一层，不加工）',
       'suspend fun updateOrderContact(orderId: Long, body: com.tapmoay.sorders.data.remote.dto.OrderUpdateRequest) =' in kt(REPO)
       and 'api.orderApi.updateOrderContact(orderId, body)' in kt(REPO))
    ok('生成的能力表里有新门（货主那一格）',
       '"order:edit_contact" to "补自己名下订单的联系信息",' in kt(CAPK))
    detail = kt(DETAIL)
    # 键与那一问只有一处：OrderEditInline.kt 的 canEditOrderContact()。写在详情页上会让那个
    # 文件凑够 3 个权限键字面量，被 _check_capability_unification.py 与 R3-D04 判成第二份真相。
    ok('详情页的能力门走 canEditOrderContact（不是 canEditInfo）',
       'val canEditContact = canEditOrderContact(role)' in detail)
    ok('详情页在 contactRisk 时出红条（账上认不出人）', 'if (order.contactRisk) {' in detail)
    ok('红条里那颗按钮进的是 OrderEditField.CONTACT 那一栏',
       'edit.startEdit(OrderEditField.CONTACT)' in detail and 'Text("去补联系信息")' in detail)
    ok('编辑栏挂在详情页上（editingField == CONTACT）',
       'if (edit.editingField == OrderEditField.CONTACT) {' in detail and 'ContactFillPanel(edit)' in detail)
    edit = kt(EDIT)
    ok('编辑字段常量 CONTACT = contact', 'const val CONTACT = "contact"' in edit)
    ok('那一问只有一处：canEditOrderContact 问的是 order:edit_contact 这一格',
       'fun canEditOrderContact(role: Role): Boolean = Capabilities.can(role.key, "order:edit_contact")' in edit)
    panel = between(edit, 'fun ContactFillPanel(', 'private fun EditBox(')
    ok('面板标题逐字「补联系信息」', 'Text("补联系信息", style = MaterialTheme.typography.titleSmall)' in panel)
    ok('四格逐字：收货人姓名 / 收货人电话 / 下单人姓名 / 下单人电话',
       all(f'label = "{x}",' in panel for x in ['收货人姓名', '收货人电话', '下单人姓名', '下单人电话']))
    ok('电话那两格用手机键盘 ＋ 电话输入规则',
       panel.count('keyboard = KeyboardType.Phone') == 2 and panel.count('InputRules.phoneInput') == 2)
    ok('两个电话都是选填（不是必填 —— 要不到电话正是这一条的由来）',
       'required = false' not in panel)
    ok('复用现成的联系人弹层（用户 m01132：这些代码是可以复用的）',
       'ContactPickerSheet(' in panel and 'edit.pickContactForDongjia(it)' in panel)
    ok('能就地新建一个收货人再选他', 'edit.createContactAndPick(name, phone)' in panel)
    for member in [
        'val showContactSheet: Boolean',
        'val contactsError: String?',
        'val loadingContacts: Boolean',
        'val creatingContact: Boolean',
        'val contactSaveError: String?',
        'fun openContactSheet()',
        'fun closeContactSheet()',
        'fun loadContacts()',
        'fun pickContactForDongjia(c: ContactDto)',
        'fun createContactAndPick(name: String, phone: String)',
    ]:
        ok(f'OrderEditHost 声明了 {member}', member in edit)
    vm = kt(VM)
    ok('VM 的 saveEdit 在函数头分流给 saveContactOnly（另一扇门）',
       'if (editingField == OrderEditField.CONTACT) {' in vm and 'saveContactOnly(o)' in vm)
    ok('VM 有 saveContactOnly 的实现（宿主接口的唯一实现者）',
       'private fun saveContactOnly(o: OrderDto) {' in vm)
    contact_fn = between(vm, 'private fun saveContactOnly(', 'override var showContactSheet')
    ok('补联系信息这条路走 updateOrderContact（不是 updateOrder）',
       'order = container.repo.updateOrderContact(' in contact_fn)
    ok('两个电话在这条路上都是选填（required = false）',
       contact_fn.count('required = false') == 2)
    ok('成功后的话里不承诺「司机能收到消息」（终态单后端不推）',
       'actionResult = "联系信息已经补上"' in contact_fn
       and '收到一条消息' not in contact_fn)
    for member in [
        'override fun openContactSheet() {',
        'override fun closeContactSheet() {',
        'override fun loadContacts() {',
        'override fun pickContactForDongjia(c: ContactDto) {',
        'override fun createContactAndPick(name: String, phone: String) {',
    ]:
        ok(f'VM 实现了 {member}', member in vm)
    for member in [
        'override var showContactSheet',
        'override var contacts',
        'override var contactsError',
        'override var loadingContacts',
        'override var creatingContact',
        'override var contactSaveError',
    ]:
        ok(f'VM 实现了 {member}', member in vm)
    ok('货主订单卡左边那颗红标（contentDescription 与 label 都叫「补联系信息」）',
       'CardActionIcon(' in kt(SHIP) and 'Icons.Default.WarningAmber,' in kt(SHIP)
       and 'if (order.contactRisk) {' in kt(SHIP)
       and kt(SHIP).count('补联系信息') >= 2)
    hits = kt_hits('contactRisk')
    ok('客户端只读这个布尔值：全仓恰好 3 处（定义 1 ＋ 显示 2），没有第二份判断',
       len(hits) == 3, str(hits))

    section('8. 别人的东西没碰（Must Not Change）')
    ok('账本页零新增（L-31 只作动机，ShipperLedgerScreen.kt 不动）',
       'contactRisk' not in kt(LEDGER) and 'order:edit_contact' not in kt(LEDGER))
    ok('详情页四处 EditHint( 还在（CHG-0041 那四处提示没被挪窝）',
       kt(DETAIL).count('EditHint(') == 4)
    ok('canEditInfo / canEditLines 两道老门仍在（整张单的编辑权没被放宽）',
       'val canEditInfo = ' in kt(DETAIL) and 'val canEditLines = ' in kt(DETAIL))
    ok('AI 侧不在本刀：AiWrite.kt 里没有新权限点（口径钉在这里）',
       'order:edit_contact' not in kt(AIWRITE))
    ok('既有红线随动①：_check_detail_inline_edit.py 认识第三个权限点',
       'ORDER_EDIT_CONTACT' in raw(DETAIL_CHECK))
    ok('既有红线随动②：那份反验也加了一条「把新门关上」的注入',
       'ORDER_EDIT_CONTACT' in raw(DETAIL_REV))
    hint_fresh = subprocess.run(
        [sys.executable, str(QA / '_hint_inventory.py'), '--check'],
        capture_output=True, text=True, encoding='utf-8', errors='replace')
    ok('既有红线随动③：提示目录已重生成（作者脚本自己说它不是过期目录）',
       HINT_CATALOG.exists() and hint_fresh.returncode == 0,
       ((hint_fresh.stdout or '').strip().splitlines() or [''])[-1])

    section('9. 文档与反验（本刀必须登记的四处）')
    chg = raw(CHG)
    ok('CHG-0057.md 存在且不是空壳（> 4000 字符）', len(chg) > 4000, str(len(chg)))
    for needle in ['CHG-0057', 'L-27', 'L-28', 'L-31', 'm00846', 'm01132', 'm01199',
                   'order:edit_contact', 'contact_risk', 'orders.edited']:
        ok(f'CHG-0057.md 里提到 {needle}', needle in chg)
    for head in ['## ① 六问', '## ② Must Change / Must Not Change', '## ③ Boundary',
                 '## ④ Behavior Contract', '## ⑤ Data Contract', '## ⑥ CHG 专章',
                 '## ⑦ 测试', '## ⑧ 证据', '## ⑨ 关闭']:
        ok(f'CHG-0057.md 有 {head} 这一节', head in chg)
    ok('CHG-0057.md 的 Boundary 结论逐字（红线与反验都钉这一句）', BOUNDARY_LINE in chg)
    ok('README 的登记簿有本刀那一行（与目录一一对应）',
       '[CHG-0057.md](CHG-0057.md)' in raw(CHG_README))
    ok('AI_WORK_CLAIM 有本刀那一条', 'CHG-0057' in raw(CLAIM))
    rev = raw(REV)
    n_inj = rev.count('\n    (\n')
    ok('反验脚本存在且是 5 元组表形状（≥ 24 条注入）', n_inj >= 24, f'{n_inj} 条')
    ok('反验脚本跑的是本判据（不是别人那份）', '_check_order_contact_edit.py' in rev)

    print('\n' + '=' * 60)
    if C.fails:
        print(f'❌ {len(C.fails)} 项不通过（通过 {C.n_ok} 项）：')
        for label, _detail in C.fails:
            print(f'   - {label}')
        return 1
    print(f'✅ 全部 {C.n_ok} 项通过：货主只能补自己名下那一单的联系信息（四个字段），账上认不出人只有一处算法。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
