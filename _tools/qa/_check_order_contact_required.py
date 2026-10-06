'''
红线：下单时「收货人 / 下单人」四个联系字段不能全空（台账 L-32 ⇒ CHG-0058）。

## 由来（用户 2026-10-06 只读排查台账 _tmp/USER_BUG_LEDGER_20261006.md）
- **L-32 口述（ref m01132）**：「这个**是不可能存在**的 —— **无主账是不可能存在的**……
  我们在**下单的时候也会做个限制：两个必须选一个，必须要有一个是有信息的**。」
- **L-32 判定式（ref m01199）**：contact_dongjia_name / contact_dongjia_phone /
  contact_boss_name / contact_boss_phone 四个字段里**任意一个非空**即合格（名字或电话任选）。
- **L-32 追加（ref m01242）**：「然后**干脆后端也拦一下**吧，就是**保险一点**。」
  ⇒ 最终三重：① 前端下单页（给好文案）② 后端命令层硬拦 ③ AI 核心规范。
- 同批两条（用户 m01072 / m01132）：**L-29** 挂账单的预填名字取「下单人 → 收货人」、一条请求建成；
  **L-30** 司机端订单详情不显示司机姓名与电话，AI 回答里也不出现。

## 为什么必须有一条红线盯着它
1. 判据一旦被抄成第二份，三处就会给出**三个答案**：「只填电话行不行」在页面上说行、后端说不行 ——
   用户只会以为 App 坏了，而账上又多了一单认不出人的。
2. 四个落点（下单 / 改单 / 转单新开 / 拆单）漏掉任何一个，这道保证就能被**绕过**；其中转单与拆单是
   **继承**别人的值，漏了它们，存量空单会一直繁殖（每拆一次多两张空单）。
3. 改单那条路必须按**合并后的结果**判：只看请求体的写法会把「把最后一个联系方式删掉」放过去。
4. **位置**错了也会坏：写在 Pydantic 那层会误拒「派单员选中货主」的合格单（_shipper_xor_temp 跑在兜底之前）；
   写在拆单的原子占位之后，用户看到的是「拆失败但父单没了」。
5. 顺手修的一个真缺陷：拆单子单原来**只抄两个电话、两个名字一个都不抄** —— 拆一次单，归属就丢了。
6. **L-29**：挂账走「先建单位再挂」两步会留下中间态（单位建好了、账没挂上，界面上看不出来）。
7. **L-30**：司机姓名/电话一旦进模型上下文，就会出现在聊天记录里（可能被截图外发）⇒ 从数据侧不给。

R4-BOUNDARY-JUSTIFICATION: 在既有的下单 / 改单 / 转单 / 拆单四条命令路径上新增一道**入参完整性**校验
（同一处纯函数，不改数据模型、不落库、不做迁移、不动状态机、不动金额算法），外加客户端一条提交前提示、
挂账单预填名字的一处纯函数、一处「司机行不给司机看」的界面门与 AI 侧一条规范；
Blast Radius L1（主，局部行为）。

## 判据（清单全部自己算；路径写错会先在「读到几个文件」那条报红）
1. 判据只有一份：后端 order_contact.py 的四元组 / 文案 / merged_contact_info / contact_info_missing；
   ⛔ 不复用 L-28 的两个姓名字段；⛔ 不出现在 backend/app/schemas/ 那一层。
2. 四个落点：下单（兜底之后、白名单之前）/ 改单（终态门之后、字段赋值之前，按合并结果）/
   转单新开（_orderer_contact 之后、target = Order( 之前）/ 拆单（前置条件里、原子占位之前）。
3. 拆单子单四个字段全抄（两个名字必须在）；转单的豁免写在文档里。
4. 文案：CONTACT_INFO_REQUIRED 是唯一来源；validation_errors 的四个中文标签是「收货人 / 下单人」。
5. 客户端：ContactRequirement.kt 是全仓唯一一份判据；下单页 submit 的 when 里有那一条分支。
6. L-29：预填名字（下单人 → 收货人）、一条请求建成、同名复用、近似名只提示不合并。
7. L-30：司机那一行对司机不显示；AI 的行整形器摘掉 driver_name / driver_phone（且在成本开关之前）。
8. AI 规范：AiAnswerStyle 第 10 条 ＋ AiWrite 的四条 hint（不再是「可选」）＋ 编号顺延。
9. 别人的东西没碰：canDialDriver 一个字不动、后端仍导出 driver_phone/driver_name、挂账端点未改。
10. 防空转与文档：后端测试 / 客户端单测存在、CHG-0058.md 九节 / README 行 / CLAIM 条目 / 反验注入条数。

⚠️ 注入式反向验证（改坏 → 本脚本必须红，改回 → 绿）：
   python _tools/qa/_reverse_verify_order_contact_required.py
用法：python _tools/qa/_check_order_contact_required.py
'''
from __future__ import annotations

import re
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
ANDTEST = ROOT / 'android/app/src/test/java/com/tapmoay/sorders'
QA = ROOT / '_tools/qa'

CONTACT = BACKEND / 'app/services/order_contact.py'
CMD = BACKEND / 'app/commands/order.py'
FLOW = BACKEND / 'app/services/order_flow.py'
VERR = BACKEND / 'app/core/validation_errors.py'
PURCHASE = BACKEND / 'app/services/purchase_service.py'
RESP = BACKEND / 'app/services/order_response.py'
BTEST = BACKEND / 'tests/test_order_contact_required.py'
SCHEMAS = BACKEND / 'app/schemas'
MODEL_ORDER = BACKEND / 'app/models/order.py'

REQ = ANDROID / 'ui/common/ContactRequirement.kt'
REQ_TEST = ANDTEST / 'ui/common/ContactRequirementTest.kt'
CREATE_VM = ANDROID / 'ui/shipper/OrderCreateViewModel.kt'
CHARGE = ANDROID / 'ui/order/ChargeUnitName.kt'
CHARGE_TEST = ANDTEST / 'ui/order/ChargeUnitNameTest.kt'
ORDER_VM = ANDROID / 'ui/order/OrderDetailViewModel.kt'
DETAIL = ANDROID / 'ui/order/OrderDetailScreen.kt'
DTO = ANDROID / 'data/remote/dto/Dtos.kt'
REPO = ANDROID / 'data/repo/AppRepository.kt'
APIS = ANDROID / 'data/remote/api/Apis.kt'
DRIVER_CALL = ANDROID / 'ui/common/DriverCall.kt'
CONTACT_FILL = ANDROID / 'ui/common/ContactFill.kt'
AI_STYLE = ANDROID / 'ai/AiAnswerStyle.kt'
AI_LOOP = ANDROID / 'ai/AiAgentLoop.kt'
AI_WRITE = ANDROID / 'ai/AiWrite.kt'
AI_ROW = ANDROID / 'ai/AiRowShaper.kt'
AI_TOOLS = ANDROID / 'ai/AiTools.kt'

CHG = ROOT / 'docs/changes/CHG-0058.md'
CHG_README = ROOT / 'docs/changes/README.md'
CLAIM = ROOT / 'docs/AI_WORK_CLAIM.md'
REV = QA / '_reverse_verify_order_contact_required.py'

#: 逐字：CHG-0058.md 的「③ Boundary」第一行必须是这一句（判据与反验都用它当锚点）。
BOUNDARY_LINE = (
    '- **结论**：**CORE（下单 / 改单 / 转单 / 拆单四条路上的入参完整性校验）'
    '＋ CLIENT（下单页提示与挂账单预填）＋ AI（核心规范一条）**，Blast Radius **L1**'
)

#: 逐字：后端唯一那条文案（客户端 / AI / 文档都引用它）。
MESSAGE = 'CONTACT_INFO_REQUIRED = "请填写收货人或下单人（名字或电话，至少一个）"'

#: 逐字：四个落点各一条锚点。
CREATE_FALLBACK = 'boss_name = (target_shipper.full_name or "").strip()'
CREATE_WHITELIST = 'bad = ['
ORDERER_CONTACT = 'boss_name, boss_phone = _orderer_contact(db, shipper_id, temp_name)'
TARGET_ORDER = 'target = Order('
UPDATE_TERMINAL = 'elif order.status in (OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.RETURNED):'
UPDATE_MERGED = 'if contact_info_missing(merged_contact_info(order, body)):'
UPDATE_TRACKED = 'tracked = CONTACT_FIELDS if contact_only else DISPATCHER_TRACKED_FIELDS'
SPLIT_GUARD = 'if contact_info_missing(order):'
SPLIT_CLAIM = 'claimed = db.execute('
CHILD_DONGJIA = 'contact_dongjia_name=order.contact_dongjia_name,'
CHILD_BOSS = 'contact_boss_name=order.contact_boss_name,'

#: 逐字：四个中文标签（422 提示里直接端到用户眼前的字）。
LABELS = [
    '"contact_dongjia_phone": "收货人电话",',
    '"contact_dongjia_name": "收货人姓名",',
    '"contact_boss_phone": "下单人电话",',
    '"contact_boss_name": "下单人姓名",',
]
OLD_LABELS = ['货主电话', '货主姓名', '老板电话', '老板姓名']

#: 逐字：客户端那一份判据（全仓唯一）。
REQ_CONST = 'const val CONTACT_REQUIRED_MESSAGE = "请填写收货人或下单人（名字或电话，至少一个）"'
REQ_FUN = 'fun contactInfoMissing('
REQ_CALL = 'contactInfoMissing(dongjiaName, dongjiaPhone, bossName, bossPhone) ->'

#: 逐字：L-29（挂账预填与一条请求建成）。
PREFILL = 'chargeNewUnitName = defaultArrearsUnitName(order?.contactBossName, order?.contactDongjiaName)'
CHARGE_BY_NAME = 'container.repo.chargeOrder(orderId, name)'
CHARGE_DTO_ID = '@SerialName("arrears_unit_id") val arrearsUnitId: Long? = null,'
CHARGE_DTO_NAME = '@SerialName("arrears_unit_name") val arrearsUnitName: String? = null,'
CHARGE_REPO = 'suspend fun chargeOrder(orderId: Long, arrearsUnitName: String) ='
CHARGE_ONECLICK = 'Text(if (acting) "处理中…" else "新建「" + newName.trim() + "」并挂账")'
CHARGE_SIMILAR = 'similarArrearsUnitName(newName, units.map { it.name })'

#: 逐字：L-30（司机那一行的门、AI 侧摘字段）。
DRIVER_GATE = 'if (role != Role.DRIVER && !order.driverName.isNullOrBlank()) {'
ROW_HIDE = 'if (k == "driver_name" || k == "driver_phone") return true'
ROW_COST = 'if (allowCost) return false'

#: 逐字：AI 核心规范第 10 条与四条 hint 的新口径。
AI_RULE10 = '10. **下单时「收货人 / 下单人」至少要有一个有信息**（名字或电话，任选其一就够）：'
AI_HINT = '**至少要填一个**，四个全空下不出单'
AI_LOOP_11 = 'appendLine("11. 系统里的只读列表都能通过'


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit('找不到文件：' + str(p) + '（改名/移动了？本脚本的断言要跟着改）')
    return p.read_text(encoding='utf-8')


def py(p: Path) -> str:
    return code_only(read(p))


def kt(p: Path) -> str:
    return strip_comments(read(p))


def first(text: str, needle: str) -> int:
    return text.find(needle)


def ordered_after(text: str, anchor: str, *needles: str) -> bool:
    '''从 anchor 之后开始找这几个字面量，且必须**按给定顺序**出现。

    ⚠️ 不能直接用 str.find：同一个字面量在这个文件里出现好几次（每个函数各一处），
    find 只认第一处 ⇒ 会把上一个函数里的那一处当成这一个函数的，判据变成永远绿/永远红。
    '''
    i = text.find(anchor)
    if i < 0:
        return False
    for n in needles:
        j = text.find(n, i)
        if j < 0:
            return False
        i = j
    return True


def main() -> int:
    c = Checker()
    contact, cmd, flow, verr = py(CONTACT), py(CMD), py(FLOW), py(VERR)
    purchase, resp = py(PURCHASE), py(RESP)
    req, create_vm, charge, order_vm, detail = kt(REQ), kt(CREATE_VM), kt(CHARGE), kt(ORDER_VM), kt(DETAIL)
    dto, repo, apis, driver_call = kt(DTO), kt(REPO), kt(APIS), kt(DRIVER_CALL)
    ai_style, ai_loop, ai_write = kt(AI_STYLE), kt(AI_LOOP), kt(AI_WRITE)
    ai_row, ai_tools = kt(AI_ROW), kt(AI_TOOLS)

    c.section('① 判据只有一份（后端 order_contact.py）')
    c.ok(
        '四个联系字段逐字（名字与电话都要，不是只看名字）',
        'CONTACT_INFO_FIELDS: tuple[str, ...] = (' in contact
        and all(('"' + f + '",') in contact for f in [
            'contact_dongjia_name', 'contact_dongjia_phone',
            'contact_boss_name', 'contact_boss_phone',
        ]),
    )
    c.ok('文案逐字（唯一来源）', MESSAGE in contact)
    c.ok(
        'merged_contact_info 认三种形状、None 不算改',
        'def merged_contact_info(*sources: object) -> dict[str, str]:' in contact
        and 'isinstance(source, Mapping)' in contact
        and 'if raw is None:' in contact,
    )
    c.ok(
        'contact_info_missing 是唯一判法（四个全空）',
        'def contact_info_missing(source: object) -> bool:' in contact
        and 'return all(not value for value in merged_contact_info(source).values())' in contact,
    )
    c.ok(
        '⛔ 没有被合并进 L-28 那套（两个姓名字段与 contact_risk_of 原样）',
        'CONTACT_NAME_FIELDS: tuple[str, ...] = ("contact_dongjia_name", "contact_boss_name")' in contact
        and 'def contact_risk_of(order: Order) -> bool:' in contact,
    )
    backend_defs = [
        p for p in BACKEND.rglob('*.py') if 'def contact_info_missing(' in p.read_text(encoding='utf-8')
    ]
    c.ok(
        'contact_info_missing 在全后端只有一处定义',
        [p.name for p in backend_defs] == ['order_contact.py'],
        '实际：' + str([str(p.relative_to(ROOT)) for p in backend_defs]),
    )
    schema_hits = [
        p for p in SCHEMAS.rglob('*.py') if 'contact_info_missing' in p.read_text(encoding='utf-8')
    ]
    c.ok(
        '⛔ 不写在 Pydantic 那层（会误拒「派单员选中货主」的合格单）',
        not schema_hits,
        '实际：' + str([str(p.relative_to(ROOT)) for p in schema_hits]),
    )
    c.ok('⛔ 不做数据库约束（NOT NULL / CHECK 会连存量行一起炸）', 'NOT NULL' not in contact and 'CheckConstraint' not in contact)
    model = code_only(read(MODEL_ORDER))
    columns = [
        ln.strip() for ln in model.splitlines()
        if ln.strip().startswith(('contact_dongjia_', 'contact_boss_'))
    ]
    c.ok(
        '⛔ 模型层四个联系字段仍可空（不加 nullable=False / 不加 CheckConstraint）',
        len(columns) == 4
        and all('default=""' in ln for ln in columns)
        and all('nullable=False' not in ln for ln in columns)
        and all('CheckConstraint' not in ln for ln in columns)
        and 'CheckConstraint' not in model,
        '实际：' + str(columns),
    )

    c.section('② 四个落点（顺序也是判据）')
    c.ok(
        '下单：判据在「下单人＝货主」兜底之后、商品白名单之前',
        ordered_after(cmd, 'def create_order(db: Session', CREATE_FALLBACK, 'if contact_info_missing(', CREATE_WHITELIST),
    )
    c.ok(
        '下单：四个值取自请求体 + 兜底结果（不是只取请求体）',
        all(s in cmd for s in [
            '"contact_dongjia_name": body.contact_dongjia_name,',
            '"contact_dongjia_phone": body.contact_dongjia_phone,',
            '"contact_boss_name": boss_name,',
            '"contact_boss_phone": boss_phone,',
        ]),
    )
    c.ok(
        '改单：判据在终态门之后、字段赋值（tracked）之前，且按合并结果',
        ordered_after(cmd, 'def update_order(', UPDATE_TERMINAL, UPDATE_MERGED, UPDATE_TRACKED),
    )
    c.ok('改单：调的是 merged_contact_info(order, body)', 'contact_info_missing(merged_contact_info(order, body))' in cmd)
    c.ok(
        '转单新开：判据在 _orderer_contact 之后、target = Order( 之前',
        ordered_after(cmd, ORDERER_CONTACT, 'if contact_info_missing(', TARGET_ORDER),
    )
    c.ok('拆单：判据在原子占位之前', ordered_after(flow, 'def split_order(', SPLIT_GUARD, SPLIT_CLAIM))
    c.ok('四个落点都是同一个函数（不是各写一遍判定）', cmd.count('contact_info_missing(') == 3 and flow.count('contact_info_missing(') == 1)

    c.section('③ 拆单子单四个字段全抄（顺手修的真缺陷）')
    c.ok('子单抄收货人名字', CHILD_DONGJIA in flow)
    c.ok('子单抄下单人名字', CHILD_BOSS in flow)
    c.ok('子单仍抄两个电话', 'contact_dongjia_phone=order.contact_dongjia_phone,' in flow and 'contact_boss_phone=order.contact_boss_phone,' in flow)
    c.ok('豁免的那处不是订单域的 Order（采购单）', 'PurchaseOrder(' in purchase and 'from app.models import' in purchase)

    c.section('④ 文案与旧叫法')
    c.ok('四个中文标签都是「收货人 / 下单人」', all(s in verr for s in LABELS))
    c.ok('旧叫法（货主电话 / 老板电话…）在这个表里清零', not any(s in verr for s in OLD_LABELS))
    c.ok('后端测试那边也改了（422 提示的断言）', '"收货人姓名" in' in read(BACKEND / 'tests/test_text_guard.py'))

    c.section('⑤ 客户端只有一份判据')
    c.ok('常量逐字', REQ_CONST in req)
    c.ok('纯函数（四个参数，全空才是真）', REQ_FUN in req and 'listOf(dongjiaName, dongjiaPhone, bossName, bossPhone).all { it.isNullOrBlank() }' in req)
    kt_defs = [
        p for p in (ROOT / 'android/app/src/main').rglob('*.kt')
        if REQ_FUN in p.read_text(encoding='utf-8')
    ]
    c.ok(
        'fun contactInfoMissing 全客户端只有一处定义',
        [p.name for p in kt_defs] == ['ContactRequirement.kt'],
        '实际：' + str([str(p.relative_to(ROOT)) for p in kt_defs]),
    )
    c.ok('下单页 submit 里有那一条分支（点了立刻给原因）', REQ_CALL in create_vm)
    c.ok('下单页引用的是那份常量（不是自己写一句）', 'error = CONTACT_REQUIRED_MESSAGE' in create_vm)
    c.ok('客户端有单测', REQ_TEST.exists() and 'CONTACT_REQUIRED_MESSAGE' in read(REQ_TEST))

    c.section('⑥ L-29 挂账单：预填 / 一条请求 / 近似名只提示')
    c.ok('预填名字＝下单人 → 收货人', PREFILL in order_vm)
    c.ok('预填判据是纯函数（不在 VM 里手写回退）', 'fun defaultArrearsUnitName(' in charge and 'fun similarArrearsUnitName(' in charge)
    c.ok('挂账走一条请求（按名字）', CHARGE_BY_NAME in order_vm)
    c.ok('不再自己先建单位（两步那套已删）', 'createArrearsUnit(' not in order_vm)
    c.ok('DTO 两个字段都可空（id 那条路仍只有 id）', CHARGE_DTO_ID in dto and CHARGE_DTO_NAME in dto)
    c.ok('仓库层按名字的重载在', CHARGE_REPO in repo)
    c.ok('端点签名没动（仍是 OrderChargeBody）', 'suspend fun chargeOrder(@Path("orderId") orderId: Long, @Body body: OrderChargeBody)' in apis)
    c.ok('按钮文案带上要建的名字', CHARGE_ONECLICK in detail)
    c.ok('近似名提示只提示（调的是那个纯函数）', CHARGE_SIMILAR in detail)
    c.ok('面板拿得到预填值', 'initialName = vm.chargeNewUnitName,' in detail and 'var newName by remember { mutableStateOf(initialName) }' in detail)
    c.ok('L-29 有单测', CHARGE_TEST.exists() and 'similarArrearsUnitName' in read(CHARGE_TEST) and 'defaultArrearsUnitName' in read(CHARGE_TEST))

    c.section('⑦ L-30 司机信息：界面不给司机看 ＋ AI 一律不喂')
    c.ok('司机那一行对司机不显示', DRIVER_GATE in detail)
    c.ok('能拨的人不变（canDialDriver 一个字没动）', 'fun canDialDriver(' in driver_call)
    c.ok('AI 行整形器摘掉司机姓名与电话', ROW_HIDE in ai_row)
    c.ok('摘字段在成本开关之前（否则开成本的角色会漏）', first(ai_row, ROW_HIDE) < first(ai_row, ROW_COST))
    c.ok('AI 工具不再手搓 driver_name', 'put("driver_name"' not in ai_tools)
    c.ok('后端仍导出这两列（打电话那条路要用）', 'data["driver_phone"]' in resp and 'data["driver_name"]' in resp)

    c.section('⑧ AI 规范与动作措辞')
    c.ok('核心规范第 10 条逐字', AI_RULE10 in ai_style)
    c.ok('规范里写了「缺信息就问，不要自己编」', '缺信息就问，不要自己编' in ai_style)
    c.ok('创建订单的四条 hint 说了「至少要填一个」', AI_HINT in ai_write)
    c.ok('改单那四条 hint 说了「不能一起改空」（不传＝不改）', '不能一起改空' in ai_write and '不传＝不改' in ai_write)
    c.ok('编号顺延（只读列表那条变 11）', AI_LOOP_11 in ai_loop and 'appendLine("10. 系统里的只读列表' not in ai_loop)

    c.section('⑨ 别人的东西没碰')
    c.ok('收货人两栏的覆盖规矩仍是那两条', bool(re.search(r'enum class ContactFillMode\b', kt(CONTACT_FILL))) and 'BROUGHT' in kt(CONTACT_FILL) and 'PICKED' in kt(CONTACT_FILL))
    c.ok('下单页四个输入框仍在（不是删字段换校验）', all(s in kt(ANDROID / 'ui/shipper/OrderCreateScreen.kt') for s in ['"收货人名称"', '"收货人电话"', '"下单人名称"', '"下单人电话"']))

    c.section('⑩ 防空转与文档')
    btest = read(BTEST)
    c.ok('后端测试在（下单全空 / 代理兜底 / 改单合并 / 拆单继承 四件）', all(s in btest for s in [
        'test_货主自己下单四个联系字段全空时被拒',
        'test_派单员代理下单仍由货主账号兜底',
        'test_改单把最后一个联系方式改空会被拒',
        'test_拆单子单继承父单的两个名字',
    ]))
    c.ok('⛔ 没做数据库约束 / 没做迁移（这一刀零落库）', 'add_column' not in contact and 'ALTER TABLE' not in contact)
    c.ok('CHG-0058.md 在', CHG.exists())
    if CHG.exists():
        chg = read(CHG)
        c.ok('CHG-0058.md 有九节标题', all(s in chg for s in ['## ①', '## ②', '## ③', '## ④', '## ⑤', '## ⑥', '## ⑦', '## ⑧', '## ⑨']))
        c.ok('Boundary 那一行逐字', BOUNDARY_LINE in chg)
        c.ok('文档写了四个落点与「继承后仍为空 ⇒ 拦」', '继承' in chg and '原子占位' in chg)
    c.ok('README 有 CHG-0058 那一行', '| [CHG-0058.md](CHG-0058.md) |' in read(CHG_README))
    c.ok('AI_WORK_CLAIM 有条目', 'CHG-0058' in read(CLAIM))
    c.ok('反验脚本在', REV.exists())
    if REV.exists():
        injections = read(REV).count('    (')
        c.ok('反验注入条数够多（≥30）', injections >= 30, '实际：' + str(injections))

    c.section('汇总')
    print()
    if c.fails:
        print('❌ ' + str(len(c.fails)) + ' 项不通过：')
        for label, detail in c.fails:
            print('   - ' + label + ((' —— ' + detail) if detail else ''))
        return 1
    print('✅ 全部 ' + str(c.n_ok) + ' 项通过：下单时「收货人 / 下单人」至少要有一个有信息（三重拦截同源），'
          '挂账单预填名字并一条请求建成，司机姓名与电话不给司机看也不给 AI。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
