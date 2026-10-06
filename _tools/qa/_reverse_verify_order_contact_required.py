# -*- coding: utf-8 -*-
"""反向验证：`_tools/qa/_check_order_contact_required.py` 的每一条判据都**真的会红** —— 台账 L-32 ＋ L-29 ＋ L-30（CHG-0058）。

## 为什么要有这一份
这一刀守的全是**静默失效**，每一种都能编译通过、界面照画、测试照绿：

· 后端命令层少一行 `if contact_info_missing(...)` —— 客户端那道提示只是"用户体验"，没有它，**任何**下单/改单/转单/拆单的接口调用（脚本、旧版 App、AI 直连）都能造出"无主账"；
· 那条判据写在「下单人＝货主」兜底**之前**（或写进 Pydantic）—— 派单员选中货主下单的**合格单**当场被误拒；
· 改单那道门只看 `order` 不看合并结果 —— 用户把最后一个联系方式改空，账上又认不出人了，而这一刀等于没做；
· 拆单抄子单时漏抄两个**名字** —— 子单落在司机手里，收货人只剩一个电话；
· `contact_info_missing` 被复制出第二份（或改成 `any`、去掉 `strip()`）—— 前端一个答案、后端一个答案、AI 一个答案，用户看到三种提示；
· 挂账单那边退回"先建单位再挂账"两步 —— 中途失败就留下"单位建好了、账没挂上"的中间态；
· 司机姓名/电话重新从界面上（或 AI 的行整形器里）漏出来 —— 用户 m01132/m01220 明确要求不显示、不喂给模型。

判据脚本写得再细，只要它自己坏了（锚点漂了、`find` 串到上一个函数、期望表写错），它**照样全绿** ——
所以这里逐条把源码改坏一次，要求判据必须报红；连**判据自己**也在注入名单里。

## 手法
- 每条：快照原文件（**按字节**）→ 字符串替换一次 → 跑判据 → 期望某条**具体**的判据变红 → 按字节还原。
- 还原之后**重新读回来逐字节比对**；不一致直接 `SystemExit(2)`（一次没还原，后面所有结论都建立在坏代码上）。
- ⛔ 全程不碰 git 的还原命令：那会把工作区里**别人**的改动一起吞掉。
- 锚点是源码片段，会随源码漂：漂了这里打 `[SKIP]`（`exit 1`），**不装成绿**。

用法：python _tools/qa/_reverse_verify_order_contact_required.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / '_check_order_contact_required.py'
BACKEND = ROOT / 'backend/app'
CONTACT = BACKEND / 'services/order_contact.py'
CMD = BACKEND / 'commands/order.py'
FLOW = BACKEND / 'services/order_flow.py'
VERR = BACKEND / 'core/validation_errors.py'
PURCHASE = BACKEND / 'services/purchase_service.py'
RESP = BACKEND / 'services/order_response.py'
SCHEMA_ORDER = BACKEND / 'schemas/order.py'
MODEL_ORDER = BACKEND / 'models/order.py'
BTEST = ROOT / 'backend/tests/test_order_contact_required.py'
TEXTGUARD = ROOT / 'backend/tests/test_text_guard.py'
ANDROID = ROOT / 'android/app/src/main/java/com/tapmoay/sorders'
ANDTEST = ROOT / 'android/app/src/test/java/com/tapmoay/sorders'
REQ = ANDROID / 'ui/common/ContactRequirement.kt'
REQ_TEST = ANDTEST / 'ui/common/ContactRequirementTest.kt'
CREATE_VM = ANDROID / 'ui/shipper/OrderCreateViewModel.kt'
CREATE_SCREEN = ANDROID / 'ui/shipper/OrderCreateScreen.kt'
CONTACT_FILL = ANDROID / 'ui/common/ContactFill.kt'
CHARGE = ANDROID / 'ui/order/ChargeUnitName.kt'
ORDER_VM = ANDROID / 'ui/order/OrderDetailViewModel.kt'
DETAIL = ANDROID / 'ui/order/OrderDetailScreen.kt'
DTO = ANDROID / 'data/remote/dto/Dtos.kt'
REPO = ANDROID / 'data/repo/AppRepository.kt'
DRIVER_CALL = ANDROID / 'ui/common/DriverCall.kt'
AI_STYLE = ANDROID / 'ai/AiAnswerStyle.kt'
AI_LOOP = ANDROID / 'ai/AiAgentLoop.kt'
AI_WRITE = ANDROID / 'ai/AiWrite.kt'
AI_ROW = ANDROID / 'ai/AiRowShaper.kt'
AI_TOOLS = ANDROID / 'ai/AiTools.kt'
CHG = ROOT / 'docs/changes/CHG-0058.md'
CHG_README = ROOT / 'docs/changes/README.md'
CLAIM = ROOT / 'docs/AI_WORK_CLAIM.md'
MUTATIONS: list[tuple[str, Path, str, str, str]] = [
    (
        '后端：字段表改名（四个联系字段不再是那一份）',
        CONTACT, 'CONTACT_INFO_FIELDS: tuple[str, ...] = (', 'CONTACT_INFO_FIELDS_OLD: tuple[str, ...] = (',
        '四个联系字段逐字',
    ),
    (
        '后端：文案被改成另一句（三处就不"同源"了）',
        CONTACT, 'CONTACT_INFO_REQUIRED = "请填写收货人或下单人（名字或电话，至少一个）"',
        'CONTACT_INFO_REQUIRED = "请填写联系信息"',
        '文案逐字（唯一来源）',
    ),
    (
        '后端：不再认 Pydantic 那种形状（派单员代理下单会漏判）',
        CONTACT, 'isinstance(source, Mapping)', 'isinstance(source, dict)',
        'merged_contact_info 认三种形状',
    ),
    (
        '后端：all 写成 any（只填了电话也算"缺"）',
        CONTACT, 'return all(not value for value in merged_contact_info(source).values())',
        'return any(not value for value in merged_contact_info(source).values())',
        'contact_info_missing 是唯一判法',
    ),
    (
        '后端：把 L-28 那套（两个姓名 + 风险提示）与本刀合并',
        CONTACT, 'CONTACT_NAME_FIELDS: tuple[str, ...] = ("contact_dongjia_name", "contact_boss_name")',
        'CONTACT_NAME_FIELDS: tuple[str, ...] = ("contact_dongjia_name", "contact_boss_name", "contact_boss_phone")',
        '⛔ 没有被合并进 L-28 那套',
    ),
    (
        '后端：别处又抄了一份 contact_info_missing（第二份真相）',
        RESP, 'data["driver_name"] = du.full_name or ""',
        'data["driver_name"] = du.full_name or ""\n\n\ndef contact_info_missing(source):\n    return False\n',
        'contact_info_missing 在全后端只有一处定义',
    ),
    (
        '后端：写进 Pydantic 层（跑在兜底之前 ⇒ 误拒合格单）',
        SCHEMA_ORDER, 'class OrderCreate(ShowableModel, GeoInput):',
        'def contact_info_missing(source):  # noqa: D103\n    return False\n\n\nclass OrderCreate(ShowableModel, GeoInput):',
        '⛔ 不写在 Pydantic 那层',
    ),
    (
        '后端：把四个联系字段改成数据库不可空（存量空单一起炸）',
        MODEL_ORDER, 'contact_boss_name: Mapped[str] = mapped_column(String(64), default="")',
        'contact_boss_name: Mapped[str] = mapped_column(String(64), default="", nullable=False)',
        '⛔ 模型层四个联系字段仍可空',
    ),
    (
        '下单：判据整段消失（接口直连就能造无主账）',
        CMD, 'if contact_info_missing(', 'if False and contact_info_missing(',
        '下单：判据在「下单人＝货主」兜底之后',
    ),
    (
        '下单：只取请求体、不取兜底后的下单人',
        CMD, '"contact_boss_name": boss_name,', '"contact_boss_name": target_shipper.full_name,',
        '下单：四个值取自请求体',
    ),
    (
        '改单：只看 order 不看合并结果（最后一个联系方式能改空）',
        CMD, 'if contact_info_missing(merged_contact_info(order, body)):', 'if contact_info_missing(order):',
        '改单：调的是 merged_contact_info',
    ),
    (
        '改单：判据整段消失',
        CMD, 'if contact_info_missing(merged_contact_info(order, body)):', 'if False:',
        '改单：判据在终态门之后',
    ),
    (
        '转单新开：兜底那一步没了（判据顺序前提被破坏）',
        CMD, 'boss_name, boss_phone = _orderer_contact(db, shipper_id, temp_name)',
        'boss_name, boss_phone = _source_contact(source)',
        '转单新开：判据在 _orderer_contact 之后',
    ),
    (
        '拆单：判据整段消失（拆出来的子单可以没有人）',
        FLOW, 'if contact_info_missing(order):', 'if False:',
        '拆单：判据在原子占位之前',
    ),
    (
        '拆单：子单漏抄收货人名字',
        FLOW, 'contact_dongjia_name=order.contact_dongjia_name,', 'contact_dongjia_name=None,',
        '子单抄收货人名字',
    ),
    (
        '拆单：子单漏抄下单人名字',
        FLOW, 'contact_boss_name=order.contact_boss_name,', 'contact_boss_name=None,',
        '子单抄下单人名字',
    ),
    (
        '拆单：子单漏抄电话',
        FLOW, 'contact_dongjia_phone=order.contact_dongjia_phone,', 'contact_dongjia_phone=None,',
        '子单仍抄两个电话',
    ),
    (
        '采购单被误当成订单域的 Order（豁免表写错）',
        PURCHASE, 'PurchaseOrder(', 'PurchaseOrderX(',
        '豁免的那处不是订单域的 Order',
    ),
    (
        '文案：下单人那个标签写回去了',
        VERR, '"contact_boss_name": "下单人姓名",', '"contact_boss_name": "老板姓名",',
        '四个中文标签',
    ),
    (
        '文案：旧叫法（货主电话）回来了',
        VERR, '"contact_dongjia_phone": "收货人电话",', '"contact_dongjia_phone": "货主电话",',
        '旧叫法',
    ),
    (
        '文案：后端测试的 422 断言没跟着改',
        TEXTGUARD, '"收货人姓名" in', '"货主姓名" in',
        '后端测试那边也改了',
    ),
    (
        '防空转：后端那条拆单用例没了',
        BTEST, 'test_拆单子单继承父单的两个名字', 'test_拆单子单',
        '后端测试在',
    ),
    (
        '客户端：常量文案改了（与后端不再逐字一致）',
        REQ, 'const val CONTACT_REQUIRED_MESSAGE = "请填写收货人或下单人（名字或电话，至少一个）"',
        'const val CONTACT_REQUIRED_MESSAGE = "请填写联系信息"',
        '常量逐字',
    ),
    (
        '客户端：all 写成 any（只填电话也被拦）',
        REQ, 'listOf(dongjiaName, dongjiaPhone, bossName, bossPhone).all { it.isNullOrBlank() }',
        'listOf(dongjiaName, dongjiaPhone, bossName, bossPhone).any { it.isNullOrBlank() }',
        '纯函数（四个参数',
    ),
    (
        '客户端：单测没了（判据不再有单测兜着）',
        REQ_TEST, 'CONTACT_REQUIRED_MESSAGE', 'CONTACT_REQUIRED',
        '客户端有单测',
    ),
    (
        '下单页：那条分支没了（点了才说原因的路径断了）',
        CREATE_VM, 'contactInfoMissing(dongjiaName, dongjiaPhone, bossName, bossPhone) ->', 'else ->',
        '下单页 submit 里有那一条分支',
    ),
    (
        '下单页：自己又写了一句提示（第二份文案）',
        CREATE_VM, 'error = CONTACT_REQUIRED_MESSAGE', 'error = "请填写联系信息"',
        '下单页引用的是那份常量',
    ),
    (
        '别人的东西：收货人两栏的覆盖规矩被动了',
        CONTACT_FILL, 'enum class ContactFillMode', 'enum class ContactFillModeX',
        '收货人两栏的覆盖规矩仍是那两条',
    ),
    (
        '别人的东西：下单页的输入框被删了一个',
        CREATE_SCREEN, '"下单人电话"', '"下单电话"',
        '下单页四个输入框仍在',
    ),
    (
        'L-29：挂账单不再预填名字',
        ORDER_VM, 'chargeNewUnitName = defaultArrearsUnitName(order?.contactBossName, order?.contactDongjiaName)',
        'chargeNewUnitName = ""',
        '预填名字＝下单人 → 收货人',
    ),
    (
        'L-29：挂账没走那条按名字的请求',
        ORDER_VM, 'order = container.repo.chargeOrder(orderId, name)', 'order = container.repo.chargeOrder(orderId, 0L)',
        '挂账走一条请求',
    ),
    (
        'L-29：退回"先建单位再挂账"两步（中间态回来了）',
        ORDER_VM, 'order = container.repo.chargeOrder(orderId, name)',
        'container.repo.createArrearsUnit(name)\n            order = container.repo.chargeOrder(orderId, name)',
        '不再自己先建单位',
    ),
    (
        'L-29：DTO 的 name 字段不可空（id 那条路会被写进 null）',
        DTO, '@SerialName("arrears_unit_name") val arrearsUnitName: String? = null,',
        '@SerialName("arrears_unit_name") val arrearsUnitName: String? = "",',
        'DTO 两个字段都可空',
    ),
    (
        'L-29：仓库层那条按名字的重载改名了',
        REPO, 'suspend fun chargeOrder(orderId: Long, arrearsUnitName: String) =',
        'suspend fun chargeOrderByName(orderId: Long, arrearsUnitName: String) =',
        '仓库层按名字的重载在',
    ),
    (
        'L-29：按钮又写成"新建并挂账"（看不出建的是哪个名字）',
        DETAIL, 'Text(if (acting) "处理中…" else "新建「" + newName.trim() + "」并挂账")',
        'Text(if (acting) "处理中…" else "新建并挂账")',
        '按钮文案带上要建的名字',
    ),
    (
        'L-29：近似名提示没了（"打了一个空格"直接建第二个单位）',
        DETAIL, 'similarArrearsUnitName(newName, units.map { it.name })', 'null',
        '近似名提示只提示',
    ),
    (
        'L-29：面板拿不到预填值（框还是空的）',
        DETAIL, 'initialName = vm.chargeNewUnitName,', 'initialName = "",',
        '面板拿得到预填值',
    ),
    (
        'L-30：司机那一行对司机又显示出来了',
        DETAIL, 'if (role != Role.DRIVER && !order.driverName.isNullOrBlank()) {',
        'if (!order.driverName.isNullOrBlank()) {',
        '司机那一行对司机不显示',
    ),
    (
        'L-30：能拨的人被顺手改了（这不是本刀的面）',
        DRIVER_CALL, 'fun canDialDriver(', 'fun canDialDriverX(',
        '能拨的人不变',
    ),
    (
        'L-30：行整形器不再摘司机电话',
        AI_ROW, 'if (k == "driver_name" || k == "driver_phone") return true',
        'if (k == "driver_name") return true',
        'AI 行整形器摘掉司机姓名与电话',
    ),
    (
        'L-30：摘字段挪到成本开关之后（开成本的角色会漏）',
        AI_ROW, 'if (allowCost) return false', 'if (allowCost) return true',
        '摘字段在成本开关之前',
    ),
    (
        'L-30：工具层又手搓 driver_name（不过闸门）',
        AI_TOOLS, 'put("completed_orders", d.completedCount)',
        'put("driver_name", safeName(d.driverName))\n                            put("completed_orders", d.completedCount)',
        'AI 工具不再手搓 driver_name',
    ),
    (
        'L-30：后端把司机的号码一起摘了（打电话那条路会死）',
        RESP, 'data["driver_phone"]', 'data["driver_phone_x"]',
        '后端仍导出这两列',
    ),
    (
        'AI：核心规范第 10 条没了',
        AI_STYLE, '10. **下单时「收货人 / 下单人」至少要有一个有信息**（名字或电话，任选其一就够）：',
        '10. **下单时请填联系信息**：',
        '核心规范第 10 条逐字',
    ),
    (
        'AI：规范不再要求"缺信息就问"',
        AI_STYLE, '缺信息就问，不要自己编', '缺信息就随便填一个',
        '规范里写了「缺信息就问，不要自己编」',
    ),
    (
        'AI：创建订单的 hint 不再说"至少要填一个"',
        AI_WRITE, '"**至少要填一个**，四个全空下不出单",', '"四个里最好填一个",',
        '创建订单的四条 hint 说了',
    ),
    (
        'AI：改单的 hint 不再说"不能一起改空"',
        AI_WRITE, '不能一起改空', '可以一起改空',
        '改单那四条 hint 说了',
    ),
    (
        'AI：编号没顺延（两条都叫 10）',
        AI_LOOP, 'appendLine("11. 系统里的只读列表都能通过', 'appendLine("10. 系统里的只读列表都能通过',
        '编号顺延',
    ),
    (
        '判据自己：把"四个落点"的期望数字改错（判据必须自己报红）',
        CHECK, "cmd.count('contact_info_missing(') == 3", "cmd.count('contact_info_missing(') == 4",
        '四个落点都是同一个函数',
    ),
    (
        '文档：CHG 的九节标题少了一节',
        CHG, '## ⑦', '## 七',
        'CHG-0058.md 有九节标题',
    ),
    (
        '文档：Boundary 那一行不是逐字（L1 写成 L2）',
        CHG, '，Blast Radius **L1**', '，Blast Radius **L2**',
        'Boundary 那一行逐字',
    ),
    (
        '文档：拆单那条"继承后仍为空 ⇒ 拦"没写',
        CHG, '继承', '拷贝',
        '文档写了四个落点与「继承后仍为空 ⇒ 拦」',
    ),
    (
        '文档：README 那一行指向了不存在的文件（死链）',
        CHG_README, '| [CHG-0058.md](CHG-0058.md) |', '| [CHG-0058.md](CHG-0059.md) |',
        'README 有 CHG-0058 那一行',
    ),
    (
        '文档：AI_WORK_CLAIM 里的编号写错了',
        CLAIM, 'CHG-0058', 'CHG-0059',
        'AI_WORK_CLAIM 有条目',
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
    files = sorted({
        CONTACT, CMD, FLOW, VERR, PURCHASE, RESP, SCHEMA_ORDER, MODEL_ORDER, BTEST, TEXTGUARD,
        REQ, REQ_TEST, CREATE_VM, CREATE_SCREEN, CONTACT_FILL, ORDER_VM, DETAIL,
        DTO, REPO, DRIVER_CALL, AI_STYLE, AI_LOOP, AI_WRITE, AI_ROW, AI_TOOLS,
        CHECK, CHG, CHG_README, CLAIM,
    }, key=str)
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
    print("前提：判据 " + str(out0.count("[OK]")) + " 项全绿 ✅；开始逐条注入坏代码。（CHARGE = "
          + CHARGE.name + " 未在注入名单里）\n")
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
