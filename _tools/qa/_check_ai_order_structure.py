#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CHG-0085 判据：订单结构三条（转货 / 静默退回派单池 / 补联系信息）接进 AI 的动作目录。

用户口径（2026-10-08，目标① 第二单 / 台账 L-54）：这三条开给 AI。
三条都**不是新能力** —— 端点与人工入口早就有（转货 CHG-0042 / 静默退回 CHG-0039 /
补联系信息 CHG-0057），这一单改的是「模型能不能调、以及调的时候卡片上写什么」。

为什么必须有机器的判据
----------------------
这一域的毛病几乎全是「没报错、但把承诺改小了」，编译器一条都拦不住：
  · 把「静默退回派单池」与「撤回派单」合并成一个动作 —— 后果是**货主收到一条他不该收到的
    通知**（后端 release_order 刻意不发 orders.recalled），而卡片上写的话看上去还挺对；
  · 把货主那一扇门（ORDERS_UPDATE_CONTACT）开给派单员，或者反过来：后端是
    order:edit_contact（scope = own）与 order:dispatch / order:recall 三个权限点，
    开错一边就是一张点下去必然 403 的卡；
  · 参数里混进编号（to_shipper_id / order_product_id）：模型会照着编一个编号，而编出来的
    编号一定落在某个真人头上（价格域踩过同样的坑）；
  · prepare（预览）里偷写后端：那「预览」就不再是「什么都没动过」；
  · 转货卡漏掉「源单会被搬空作废」或「新单跟不跟原司机」：用户点确认时不知道自己在同意什么；
  · 补联系信息不挂撤回：四个字段写下去撤不回来（后端没有别的反悔入口）；
  · 静默退回挂了撤回按钮：它撤回来要么变成「再派一次」（那是另一个动作），要么点了没反应。
这些每一条都能靠「少写一句话 / 改一个常量」悄悄发生，所以逐条钉在这里。

判据（每条都能被 _tools/qa/_reverse_verify_ai_order_structure.py 弄红）
----------------------------------------------------------------------
1. 三条动作登记一处：id 常量、组、三种风险档、参数形状；
2. 角色门与后端那三个权限点一一对应：两条只给派单员（不进 SHIPPER_ACTIONS）、
   补联系信息只给货主（进 SHIPPER_ACTIONS ＋ roles = setOf(AiRole.SHIPPER)）；
3. 参数里没有 xxx_id；转货的 lines 是 TEXT（多行），不是 NUMBER；
4. 三个处理器：prepare 一个字都不写后端、commit 只认 payload、
   静默退回**不许借撤回派单的实现**；
5. 三张卡逐句：转货（转给谁 / 转哪几行各多少件 / 源单会怎样 / 新单跟不跟原司机 / 撤不回来）、
   静默退回（货主端不会有任何变化 / 与撤回派单唯一的区别 / 原司机收到通知）、
   补联系信息（逐格 旧 → 新 / 终态单也能补 / 补错了可以撤回）；
6. 数据源三个方法 ＋ 三跳链路（Apis 三个端点 → AppRepository 三个方法 → ai/ 三个处理器）；
7. 资源与撤回：补联系信息挂 ORDER 资源的 update、四个联系键在 readKeys 与 labels 里；
   转货与静默退回进 UNDO_NONE 并各自写出去路，补联系信息**不**进；
8. 覆盖表：三条写端点从「不做」桶里移走、留下改口径的来龙去脉（并实跑两个覆盖脚本）；
9. 单测 / 文书 / 反验脚本在 / 防「一个断言都没扫到也算过」。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事

问：这几条为什么不能靠「代码边界」解决，非要做成机器的判据？
答：能靠边界解决的部分已经解决了 —— 角色边界在 AiWrites.forModel / SHIPPER_ACTIONS 里
fail-closed（新动作不进白名单 = 货主拿不到）、权限在后端 scope 里、撤回在 AiRevert 里按动作
声明。剩下的三类**没法**用边界表达：
  ① 卡片**说了什么**：后端 transfer 是「并进既有单」还是「新开一张」要到运行时才知道，
     卡片必须把两种可能都写在脸上 —— 这是文案与后端语义的一致性，只有判据能钉；
  ② 两条**长得一样、只有通知对象不同**的动作要不要合并：这是产品决定（用户口径 2026-10-08），
     不是代码能判断的；
  ③ 参数**该不该收编号**：收下编号也能跑通，只是模型会编 —— 边界不会报错。
所以这一单的收口靠这份判据 ＋ 它的反向验证（_reverse_verify_ai_order_structure.py）。

用法
----
    python _tools/qa/_check_ai_order_structure.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))

from _airepo import refuse_if_injecting  # noqa: E402
from _check_product_card_single_source import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
AI = AND / "ai"

AIWRITE = AI / "AiWrite.kt"
HANDLERS = AI / "AiWriteOrderHandlers.kt"
SVC = AI / "AiWriteService.kt"
SRC = AI / "AiWriteDataSource.kt"
RES = AI / "AiResources.kt"
REVERT = AI / "AiRevert.kt"
APIS = AND / "data/remote/api/Apis.kt"
REPO = AND / "data/repo/AppRepository.kt"

TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai/AiWriteTest.kt"
PROMPT_TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai/AiWritePromptTest.kt"

WRITE_COVERAGE = ROOT / "_tools/ai/_write_coverage.py"
READ_COVERAGE = ROOT / "_tools/ai/_read_coverage.py"

LEDGER = ROOT / "_tmp/USER_BUG_LEDGER_20261006.md"

CHG_ID = "CHG-0085"
CHG_DOC = ROOT / "docs/changes/CHG-0085.md"
REGISTRY = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = "_tools/qa/_reverse_verify_ai_order_structure.py"

#: 九节标题（按前缀认：这几节的标题后面还带括号说明）
CHG_SECTIONS = (
    "## ① 六问",
    "## ② Must Change / Must Not Change",
    "## ③ Boundary",
    "## ④ Behavior Contract",
    "## ⑤ Data Contract",
    "## ⑥ CHG 专章",
    "## ⑦ 测试",
    "## ⑧ 证据",
    "## ⑨ 关闭",
)

#: 行数下限（防文件被搬走 / 被截断之后「一个断言都没扫到」也算过）
MIN_AIWRITE_LINES = 2700
MIN_HANDLER_LINES = 1500
MIN_SVC_LINES = 1100
MIN_SRC_LINES = 2100
MIN_RES_LINES = 1400
MIN_REVERT_LINES = 1000
MIN_TEST_LINES = 6000
MIN_PROMPT_TEST_LINES = 100

#: 必须真的数到这几个文件（少一个就说明目录结构变了，判据要跟着改）
REQUIRED_FILES = (
    AIWRITE, HANDLERS, SVC, SRC, RES, REVERT, APIS, REPO,
    TEST, PROMPT_TEST, CHG_DOC, REGISTRY, CLAIM, LEDGER, WRITE_COVERAGE, READ_COVERAGE,
)

LF = chr(10)

#: 三条动作的（中文名, id 常量, 动作 id）—— 每一处要用到三条的地方都从这一张表走
ACTIONS = (
    ("转货", "ORDERS_TRANSFER", "orders.transfer"),
    ("静默退回派单池", "ORDERS_RELEASE", "orders.release"),
    ("补联系信息", "ORDERS_UPDATE_CONTACT", "orders.update_contact"),
)

#: 预览（prepare）里**一个字都不许出现**的写调用：出现即「预览动了数据」。
WRITE_CALLS = (
    "ds.transferOrderLines(",
    "ds.releaseOrder(",
    "ds.updateOrderContact(",
    "ds.recallOrder(",
    "ds.cancelOrder(",
    "ds.updateOrder(",
    "ds.assignOrder(",
)


def read(p: Path) -> str:
    """读文件；**读不到就返回空串**。

    缺文件由第 0 节「文件在」那一条报红。⛔ 绝不能在这里抛 FileNotFoundError：脚本一崩就
    没有 [FAIL] 行，而反向验证的判据是「期望的检查名出现在 [FAIL] 行里」，崩了等于什么都能过。
    """
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def code(p: Path) -> str:
    return strip_comments(read(p))


def subs(text: str, needle: str) -> int:
    return text.count(needle)


def raw_block(src: str, sig: str) -> str:
    """从 sig 起按大括号配平取整块（取不到返回空串，让断言自己去红）。"""
    i = src.find(sig)
    if i < 0:
        return ""
    j = src.find("{", i)
    if j < 0:
        return ""
    depth = 0
    for k in range(j, len(src)):
        ch = src[k]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[j:k + 1]
    return ""


def part_of(src: str, start: str, end: str) -> str:
    i = src.find(start)
    if i < 0:
        return ""
    j = src.find(end, i)
    return src[i:j] if j > i else src[i:]


def class_block(src: str, cls: str) -> str:
    """一个处理器类整块（取不到返回空串）。"""
    return raw_block(src, "class " + cls + "(")


def strings_in(block: str) -> list:
    """块里所有双引号字符串（够用：这三段卡片文案里没有转义双引号）。"""
    return list(block.split('"')[1::2])


def card_blob(block: str) -> str:
    return " | ".join(strings_in(block))


def spec_of(src: str, const: str) -> str:
    """抓「id = <const>,」那一条 AiWriteAction 规格（到下一个规格为止）。

    ⛔ 窗口必须**短**、且以「下一行就是下一条规格」为界：钉在全文件会让「参数里没有 xxx_id」
    这类否定断言变成空转 —— 别处的 to_shipper_id 会让它永远为假，而它看上去还像在管这件事。
    """
    i = src.find("id = " + const + ",")
    if i < 0:
        return ""
    j = src.find(LF + "        AiWriteAction(", i)
    return src[i:j] if j > i else src[i:i + 1800]


def run_cmd(args: list) -> tuple:
    """实跑一个脚本，返回（输出, 退出码）。跑不起来也不抛（抛了就没有 [FAIL] 行）。"""
    try:
        p = subprocess.run(
            args, cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=600,
        )
        return (p.stdout or "") + (p.stderr or ""), p.returncode
    except Exception as e:  # noqa: BLE001
        return "跑不起来：" + str(e), -1


class Checker:
    def __init__(self) -> None:
        self.passes = 0
        self.fails: list = []

    def ok(self, name: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print("  [OK]   " + name)
        else:
            self.fails.append(name)
            print("  [FAIL] " + name + ("  <- " + detail if detail else ""))

    def has(self, name: str, hay: str, needle: str) -> None:
        self.ok(name, needle in hay, "没找到：" + needle)

    def hasnt(self, name: str, hay: str, needle: str) -> None:
        self.ok(name, needle not in hay, "不该出现：" + needle)

def main() -> int:
    if refuse_if_injecting("订单结构三条（CHG-0085）判据"):
        return 0

    c = Checker()
    w = read(AIWRITE)
    wc = code(AIWRITE)
    h = read(HANDLERS)
    hc = code(HANDLERS)
    s = read(SVC)
    sc = code(SVC)
    src = read(SRC)
    rs = read(RES)
    rv = read(REVERT)
    apis = read(APIS)
    repo = read(REPO)
    t = read(TEST)
    pt = read(PROMPT_TEST)

    print("== 0. 文件在，而且不是空壳 ==")
    for p in REQUIRED_FILES:
        c.ok("文件在：" + str(p.relative_to(ROOT)), p.exists())
    c.ok("行数下限（AiWrite.kt）", len(w.splitlines()) >= MIN_AIWRITE_LINES, "实际 " + str(len(w.splitlines())))
    c.ok("行数下限（AiWriteOrderHandlers.kt）", len(h.splitlines()) >= MIN_HANDLER_LINES, "实际 " + str(len(h.splitlines())))
    c.ok("行数下限（AiWriteService.kt）", len(s.splitlines()) >= MIN_SVC_LINES, "实际 " + str(len(s.splitlines())))
    c.ok("行数下限（AiWriteDataSource.kt）", len(src.splitlines()) >= MIN_SRC_LINES, "实际 " + str(len(src.splitlines())))
    c.ok("行数下限（AiResources.kt）", len(rs.splitlines()) >= MIN_RES_LINES, "实际 " + str(len(rs.splitlines())))
    c.ok("行数下限（AiRevert.kt）", len(rv.splitlines()) >= MIN_REVERT_LINES, "实际 " + str(len(rv.splitlines())))
    c.ok("行数下限（AiWriteTest.kt）", len(t.splitlines()) >= MIN_TEST_LINES, "实际 " + str(len(t.splitlines())))
    c.ok("行数下限（AiWritePromptTest.kt）", len(pt.splitlines()) >= MIN_PROMPT_TEST_LINES, "实际 " + str(len(pt.splitlines())))
    c.has("处理器文件头顶写着这三条各自被钉住", h, "_tools/qa/_check_ai_order_structure.py")

    print("== 1. 三条动作登记一处（id / 组 / 标题 / 风险档 / 进 MANUAL） ==")
    for cn, const, sid in ACTIONS:
        c.ok(cn + "：id 常量只声明一次", subs(wc, 'const val ' + const + ' = "' + sid + '"') == 1)
        c.ok(cn + "：规格只登记一处（id = " + const + "）", subs(w, "id = " + const + ",") == 1)
        c.ok(cn + "：规格不在处理器文件里偷偷再写一份", subs(h, "id = " + const + ",") == 0)
        spec = spec_of(w, const)
        c.ok(cn + "：规格块抽得出来（不是空转）", len(spec) > 300, "只抽到 " + str(len(spec)) + " 字符")
        c.has(cn + "：挂在「订单」组下", spec, "group = G_ORDER,")
    c.has("转货那张卡的标题讲清是给别的货主", spec_of(w, "ORDERS_TRANSFER"), 'title = "转货（转给别的货主）",')
    c.ok("转货是 HIGH 档（动两张单、撤不回来）", "risk = AiWriteRisk.HIGH," in spec_of(w, "ORDERS_TRANSFER"))
    c.has("静默退回的标题把「货主无感」写在标题上", spec_of(w, "ORDERS_RELEASE"), 'title = "退回派单池（货主无感）",')
    c.ok("静默退回也是 HIGH 档", "risk = AiWriteRisk.HIGH," in spec_of(w, "ORDERS_RELEASE"))
    sp_c = spec_of(w, "ORDERS_UPDATE_CONTACT")
    c.has("补联系信息的标题", sp_c, 'title = "补联系信息",')
    c.ok("补联系信息是 MEDIUM 档（补错了可以撤回 ⇒ 不能跟 HIGH 一档）", "risk = AiWriteRisk.MEDIUM," in sp_c)
    i_manual = wc.find("private val MANUAL")
    c.ok("MANUAL 列表找得到（下面的位置判断才有意义）", i_manual > 0)
    for cn, const, _sid in ACTIONS:
        c.ok(cn + "：规格就写在这个手写列表里", i_manual < wc.find("id = " + const + ","))
    c.has("三条接进了动作总表（ALL 里的 MANUAL）", wc, "id = ORDERS_TRANSFER,")
    c.ok(
        "三条在 ALL 里各只出现一次（不是既在 MANUAL 又在别处加了第二份）",
        subs(wc, "id = ORDERS_TRANSFER,") == 1 and subs(wc, "id = ORDERS_RELEASE,") == 1
        and subs(wc, "id = ORDERS_UPDATE_CONTACT,") == 1,
    )
    c.has("常量上方写着「三条都不是新能力」（免得后人以为是新端点）", w, "三条都**不是新能力**")
    c.has("常量上方点名台账", w, "台账 L-54")

    print("== 2. 角色门：与后端那三个权限点一一对应 ==")
    i_sa = wc.find("val SHIPPER_ACTIONS")
    tail = wc[i_sa:] if i_sa >= 0 else ""
    j_sa = tail.find(LF + "    )")
    sa = tail[:j_sa] if j_sa > 0 else ""
    c.ok("SHIPPER_ACTIONS 白名单抽得出来（不是空转）", len(sa) > 200, "只抽到 " + str(len(sa)) + " 字符")
    c.ok("补联系信息进 SHIPPER_ACTIONS（货主拿得到这一张卡）", "ORDERS_UPDATE_CONTACT" in sa)
    c.ok("转货**不**进 SHIPPER_ACTIONS（货主连清单里都看不见）", "ORDERS_TRANSFER" not in sa)
    c.ok("静默退回**不**进 SHIPPER_ACTIONS", "ORDERS_RELEASE" not in sa)
    c.ok("补联系信息标了 roles = setOf(AiRole.SHIPPER)", "roles = setOf(AiRole.SHIPPER)," in sp_c)
    c.ok("转货没标 roles（它只给派单员）", "roles =" not in spec_of(w, "ORDERS_TRANSFER"))
    c.ok("静默退回没标 roles（它只给派单员）", "roles =" not in spec_of(w, "ORDERS_RELEASE"))
    c.has("白名单那条 fail-closed 注释还在（新加的动作不进白名单 = 货主拿不到）", w, "新加的动作不进白名单 = 货主拿不到")
    c.has("角色门的实现是按白名单放行（不是黑名单排除）", wc, "it.id in SHIPPER_ACTIONS && (!it.memberOnly || member)")
    c.has("常量上方写明两条是派单员的后端权限点", w, "ORDER_DISPATCH")
    c.has("常量上方写明静默退回对应后端撤回权限点", w, "ORDER_RECALL")
    c.has("常量上方写明补联系信息是自己的那一扇门", w, "ORDER_EDIT_CONTACT")
    c.has("常量上方写明派单员改这四个字段走既有的改单卡（不重复开一扇门）", w, "ORDERS_UPDATE 那张卡")
    c.has("处理器 kdoc 写明终态单补完不推司机", h, "终态单补完**不推**司机")

    print("== 3. 参数形状：没有编号，lines 是多行文本 ==")
    sp_t = spec_of(w, "ORDERS_TRANSFER")
    c.has("转货参数 order", sp_t, "AiWriteParam(\"order\", \"订单\", required = true")
    c.has("转货参数 to_shipper（只写姓名）", sp_t, '"to_shipper", "转给谁（系统里已有的货主）",')
    c.has("转货参数 to_temp_name（没有账号的临时货主）", sp_t, '"to_temp_name", "转给谁（没有账号的临时货主）",')
    c.has("转货参数 lines", sp_t, '"lines", "转哪几件"')
    c.has("转货的 lines 是 TEXT（多行 JSON），不是单行输入", sp_t, "kind = AiWriteParamKind.TEXT,")
    c.has("转货提示里写明两个名字二选一", sp_t, "二选一")
    c.has("转货提示里写明只传姓名、编号由系统找", sp_t, "**只传货主姓名**，编号由系统自己找")
    c.has("转货提示里写明留空 = 整单转出", sp_t, "**留空 = 整单转出**")
    c.has("转货提示里写明一次最多 10 行", sp_t, "最多 10 行")
    c.ok("⛔ 转货参数里没有 to_shipper_id（编号由系统自己找）", "to_shipper_id" not in sp_t)
    c.ok("⛔ 转货参数里没有任何 xxx_id", '_id"' not in sp_t)
    sp_r = spec_of(w, "ORDERS_RELEASE")
    c.has("静默退回参数 order", sp_r, "AiWriteParam(\"order\", \"订单\", required = true")
    c.has("静默退回参数 reason（可选）", sp_r, '"reason", "退回原因",')
    c.has("静默退回提示写明它进的是司机那条通知", sp_r, "被收回的那位司机会在他那条「派单被撤回」通知里看到")
    c.ok("静默退回只有两个参数", subs(sp_r, "AiWriteParam(") == 2, "实际 " + str(subs(sp_r, "AiWriteParam(")))
    c.ok("⛔ 静默退回参数里没有任何 xxx_id", '_id"' not in sp_r)
    c.ok("补联系信息只有五个参数（订单 ＋ 四个字段）", subs(sp_c, "AiWriteParam(") == 5, "实际 " + str(subs(sp_c, "AiWriteParam(")))
    for name, cn in (("dongjia_name", "收货人名称"), ("dongjia_phone", "收货人电话"), ("boss_name", "下单人名称"), ("boss_phone", "下单人电话")):
        c.has("补联系信息参数 " + name, sp_c, '"' + name + '", "' + cn + '"')
    c.has("补联系信息提示写明四个字段至少填一项", sp_c, "四个字段里至少填一项")
    c.has("补联系信息卡面写明终态单也能补", sp_c, "**已送达、已撤销的单也能补**")
    c.has("补联系信息卡面写明它只能补联系信息", sp_c, "只能补联系信息")
    c.ok("⛔ 补联系信息参数里没有任何 xxx_id", '_id"' not in sp_c)
    c.has("转货的风险说明写在 blurb 里（源单搬空会作废）", sp_t, "源单被搬空会自动按「撤销」作废")
    c.has("转货 blurb 写明新开那张会跟原司机", sp_t, "**新开的那张单**会跟着他一起派出去")
    c.has("转货 blurb 写明并进既有单时不跟", sp_t, "（并进既有单时不跟）")
    c.has("转货 blurb 写明一次改两张单、撤不回来", sp_t, "一次同时改两张单，**撤不回来**")
    c.has("静默退回 blurb 写明不给货主任何消息", sp_r, "这条**不给货主任何消息**")
    c.has("静默退回 blurb 写明这不是漏发（是定义）", sp_r, "这是这个动作的定义，不是漏发")
    c.ok("静默退回 blurb 里留着与撤回派单的对比", "撤回派单" in sp_r)

    print("== 4. 三个处理器：预览不写后端、提交只认 payload ==")
    for cn, cls, action, call in (
        ("转货", "TransferOrderHandler", "AiWrites.ORDERS_TRANSFER", "ds.transferOrderLines("),
        ("静默退回", "ReleaseOrderHandler", "AiWrites.ORDERS_RELEASE", "ds.releaseOrder("),
        ("补联系信息", "UpdateOrderContactHandler", "AiWrites.ORDERS_UPDATE_CONTACT", "ds.updateOrderContact("),
    ):
        cl = class_block(h, cls)
        c.ok(cn + "：处理器类在（" + cls + "）", len(cl) > 300, "只抽到 " + str(len(cl)) + " 字符")
        c.has(cn + "：认的动作 id 对得上", cl, "override val actionId = " + action)
        c.has(cn + "：prepare 在", cl, "override suspend fun prepare(")
        c.has(cn + "：commit 在", cl, "override suspend fun commit(")
        prep = part_of(cl, "override suspend fun prepare(", "override suspend fun commit(")
        com = cl[cl.find("override suspend fun commit("):] if "override suspend fun commit(" in cl else ""
        c.ok(cn + "：prepare / commit 都抽得出来（不是空转）", len(prep) > 200 and len(com) > 80, "prepare " + str(len(prep)) + " / commit " + str(len(com)))
        c.has(cn + "：提交里真的调了写方法", com, call)
        c.ok(cn + "：写方法在处理器里只调一次", subs(hc, call) == 1, "实际 " + str(subs(hc, call)))
        c.ok(cn + "：先按订单号解析（resolveOrder）", "resolveOrder(params)" in prep)
        c.ok(cn + "：commit 只认 payload（不回头读 params）", "params" not in com)
        c.ok("⛔ " + cn + "：预览里一个字都不写后端", call not in prep)
        for bad in WRITE_CALLS:
            c.ok("⛔ " + cn + "：预览里没有 " + bad, bad not in prep)
    tr_cl = class_block(h, "TransferOrderHandler")
    re_cl = class_block(h, "ReleaseOrderHandler")
    co_cl = class_block(h, "UpdateOrderContactHandler")
    c.has("静默退回的 kdoc 引了后端那句原话（货主端不会有任何提醒）", h, "货主端仍显示已派单 / 司机已接单，状态会默默发生改变，不会有任何的消息提醒")
    c.has("转货：用名册把姓名换成编号", tr_cl, "AiWriteArgs.strict(")
    c.has("转货：去名册里搜货主", tr_cl, "ds.searchShippers(")
    c.has("转货：一次最多 10 行的常量", h, "private const val MAX_TRANSFER_LINES = 10")
    c.has("转货：明细解析单独一个函数", h, "private fun parseTransferLines(")
    c.has("转货：用数组把多行接住（不是让模型写一段话）", h, "val raw = node as? JsonArray")
    c.has("转货：键不在 = 整单转出（这是「留空」的唯一含义）", h, "if (node == null || node is JsonNull) return lines.map { it to it.quantity }")
    c.ok("⛔ 静默退回不许借「撤回派单」的动作实现", "AiWrites.ORDERS_RECALL" not in re_cl)
    c.has("静默退回：提交时理由缺省是空串（后端允许空）", re_cl, 'ds.releaseOrder(payload.reqLong("order_id"), payload.str("reason").orEmpty())')
    c.has("静默退回：状态门用 RECALLABLE（与撤回派单同一个状态集合）", re_cl, "OrderStatusModel.RECALLABLE")
    c.has("静默退回：状态门文案", re_cl, "只有「已派单」或「司机已接单」的单能退回派单池")
    c.has("补联系信息：四个参数 → 四个字段（只收非空的项）", h, "private fun contactChanges(params: JsonObject): List<ContactChange>")
    for cn, key in (("收货人名称", "contact_dongjia_name"), ("收货人电话", "contact_dongjia_phone"), ("下单人名称", "contact_boss_name"), ("下单人电话", "contact_boss_phone")):
        c.has("补联系信息：" + cn + " 映射到 " + key, h, 'ContactChange("' + cn + '", "' + key + '"')
    c.has("补联系信息的电话规则文案", h, "不要填汉字、字母或符号")
    c.has("补联系信息的电话归一用 InputRules.phoneInput", h, "InputRules.phoneInput(trimmed)")
    c.has("补联系信息的电话校验用 InputRules.phoneError", h, "InputRules.phoneError(v)")
    c.has("终态三兄弟的口径与后端同一份", h, 'private val FINISHED_STATUSES = setOf("DELIVERED", "CANCELLED", "RETURNED")')
    c.has("补联系信息的 payload 只放 order_id ＋ 改动项", co_cl, 'put("order_id", order.id)')
    c.has("补联系信息的 payload 逐项落改动字段", co_cl, "for (c in changes) put(c.key, c.value)")

    print("== 5. 三张卡逐句 ==")
    cb_t = card_blob(tr_cl)
    cb_r = card_blob(re_cl)
    cb_c = card_blob(co_cl)
    c.ok("转货卡片文本抽得出来（不是空转）", len(cb_t) > 400, "只抽到 " + str(len(cb_t)) + " 字符")
    c.ok("静默退回卡片文本抽得出来", len(cb_r) > 200, "只抽到 " + str(len(cb_r)) + " 字符")
    c.ok("补联系信息卡片文本抽得出来", len(cb_c) > 200, "只抽到 " + str(len(cb_c)) + " 字符")
    c.has("转货卡：目标货主那一行", cb_t, "目标货主：")
    c.has("转货卡：说清源单会被搬空、状态由它决定", cb_t, "的货全搬空 ⇒ 这张单会变成「已撤销」作废、占用的库存释放")
    c.ok("转货卡：另一种结局也写在卡上（源单还剩几行、状态不变）", "还剩 " in cb_t and "行），状态不变" in cb_t)
    c.has("转货卡：目标单是并进还是新开由后端找（两种都说）", cb_t, "只有唯一一张时才并进去；否则新开一张（地址、收货人、备注照抄这一单）")
    c.has("转货卡：新开那张会跟着原司机", cb_t, "新开的那张会跟着他一起派出去")
    c.has("转货卡：并进既有单时不跟（那张单有自己的司机）", cb_t, "（并进既有单时不跟 —— 那张单有自己的司机）")
    c.has("转货卡：单价沿用原来的（不是重新定价）", cb_t, "目标单沿用这几行原来的单价")
    c.has("转货卡：新单不带原收款方式 / 挂账单位 / 运费", cb_t, "新单不带这一单的收款方式、挂账单位和运费")
    c.has("转货卡：同货主并单说清楚", cb_t, "后端按「同货主并单」处理")
    c.has("转货卡：临时货主只记一个名字", cb_t, "临时货主：系统里没有他的账号，目标单上只记一个名字")
    c.has("转货卡：收货人全空时的警告", cb_t, "这一单的收货人姓名和电话都是空的")
    c.has("转货卡：警告里引后端原话", cb_t, "「请填写收货人或下单人（名字或电话，至少一个）」")
    c.has("转货卡：只转一部分时说清转多少件 / 多少钱", cb_t, "合计转出 ")
    c.has("转货卡：逐行列出转哪几件", cb_t, "件 × ")
    c.has("转货卡：⛔ 撤不回来", cb_t, "这一次会同时改两张单（源单少几件、目标单多几件，源单还可能作废），撤不回来")
    c.has("转货卡：说清要还原得反向转一次", cb_t, "要转回去得再发起一次反向的转货")
    c.has("转货：整单转空已经被拦（卡片里指的是另一条路）", tr_cl, "整单转空要走「撤回派单」再转（已接单的单不能直接作废）；也可以只转一部分。")
    c.has("转货：终态门文案（已送达 / 已撤销 / 已退货）", tr_cl, "「已送达」「已撤销」「已退货」的单不能转货（那些货已经算过账，或者已经退回去了）")
    c.has("转货：转给谁必须二选一的拦截文案", tr_cl, "转给谁只能给一个：to_shipper（系统里已经有的货主）或者 to_temp_name（临时货主）。")
    c.has("转货：谁都没给时的追问文案", tr_cl, "这批货转给谁？告诉我货主姓名；如果他在系统里没有账号，用 to_temp_name 给一个临时货主的名字。")
    c.has("静默退回卡：先给「货主那边」一个分段标题", cb_r, "———— 货主那边 ————")
    c.has("静默退回卡：货主端不会有任何变化", cb_r, "不会有任何变化：他看到的还是「")
    c.has("静默退回卡：这是定义、不是漏发", cb_r, "（这就是这个动作的定义 —— 与「撤回派单」唯一的区别就在这里：那一条会告诉货主）")
    c.has("静默退回卡：给「司机那边」一个分段标题", cb_r, "———— 司机那边 ————")
    c.has("静默退回卡：原司机收到撤回通知", cb_r, "会收到一条撤回通知")
    c.has("静默退回卡：没写理由时照实说", cb_r, "（没写原因）")
    c.has("静默退回卡：写到「这一单本身」", cb_r, "———— 这一单本身 ————")
    c.has("静默退回卡：回到待派单、司机栏清空", cb_r, "回到「待派单」，司机栏清空，可以重新派给别人")
    c.has("静默退回卡：司机计件费 / 提成会清掉", cb_r, "派单时单独定的司机计件费 / 提成会清掉（那两项是跟着这位司机走的），占用的库存释放")
    c.has("静默退回卡：⛔ 撤不回来、要再跑就重新派单", cb_r, "⛔ 撤不回来：要再跑起来请重新派单；货主那边从头到尾都不知道发生过这件事")
    c.has("补联系卡：分段标题「补这几项」", cb_c, "———— 补这几项 ————")
    c.has("补联系卡：分段标题「补完之后」", cb_c, "———— 补完之后 ————")
    c.has("补联系卡：逐格 旧 → 新（箭头在卡上）", cb_c, " → ")
    c.has("补联系卡：旧值为空时说「（空）」", h, "AiRevertJson.textOf(before?.get(key)).ifBlank { \"（空）\" }")
    c.has("补联系卡：空参数时的拦截文案（列全四个字段）", co_cl, "你还没说要补哪一项。这一单可以补：收货人名称、收货人电话、下单人名称、下单人电话（至少填一项）。")
    c.has("补联系卡：终态单补完不推司机", cb_c, "这一单已经是「")
    c.has("补联系卡：非终态且有司机时推一条「订单有改动」", cb_c, "会收到一条「订单有改动」的提醒（他手上的电话可能已经换了）")
    c.has("补联系卡：只能补联系信息（别的字段要派单员）", cb_c, "这一条只能补联系信息：送货地址、配送说明、备注那些要派单员才能改")
    c.has("补联系卡：补错了可以撤回", cb_c, "补错了可以撤回（撤回把这几项改回原来的值）")
    c.ok("补联系卡：没有在卡上写任何内部键名（对用户只出现名字与电话）", "contact_dongjia" not in cb_c and "contact_boss" not in cb_c)

    print("== 6. 数据源与三跳链路（Apis → AppRepository → ai/） ==")
    c.has("数据源：转货", src, "override suspend fun transferOrderLines(")
    c.has("数据源：静默退回", src, "override suspend fun releaseOrder(orderId: Long, reason: String)")
    c.has("数据源：补联系信息", src, "override suspend fun updateOrderContact(orderId: Long, fields: JsonObject)")
    c.has("接口声明：转货", s, "suspend fun transferOrderLines(")
    c.has("接口声明：静默退回", s, "suspend fun releaseOrder(orderId: Long, reason: String)")
    c.has("接口声明：补联系信息", s, "suspend fun updateOrderContact(orderId: Long, fields: JsonObject)")
    c.ok("接口声明都只有一处", subs(sc, "suspend fun transferOrderLines(") == 1 and subs(sc, "suspend fun releaseOrder(") == 1 and subs(sc, "suspend fun updateOrderContact(") == 1)
    c.has("端点：转货是 POST orders/{orderId}/transfer", apis, '@POST("orders/{orderId}/transfer")')
    c.has("端点：静默退回是 POST orders/{orderId}/release", apis, '@POST("orders/{orderId}/release")')
    c.has("端点：补联系信息是 PATCH orders/{orderId}/contact", apis, '@PATCH("orders/{orderId}/contact")')
    c.has("转货返回的是两张单（源单 ＋ 目标单）", apis, "OrderTransferResultDto")
    c.has("端点 kdoc 写明后端刻意不发 orders.recalled（静默的定义）", apis, "orders.recalled")
    c.ok("撤回派单与静默退回确实是两个端点（同一个状态跃迁、不同通知）", "recallOrder" in apis and '@POST("orders/{orderId}/release")' in apis)
    c.has("仓储：转货", repo, "api.orderApi.transferOrderLines(orderId, body)")
    c.has("仓储：静默退回（带 OrderReleaseBody）", repo, "api.orderApi.releaseOrder(orderId, com.tapmoay.sorders.data.remote.dto.OrderReleaseBody(reason))")
    c.has("仓储：补联系信息", repo, "api.orderApi.updateOrderContact(orderId, body)")
    c.has("仓储 kdoc：静默退回与撤回的唯一差别是通知对象", repo, "与 [recallOrder] 的唯一差别是**通知对象**")
    c.has("仓储 kdoc：补联系信息走货主专用的那扇门", repo, "只报四个联系字段，走货主专用的那扇门")
    c.has("仓储 kdoc：转货与拆单不是一回事", repo, "与 [splitOrder] **不是一回事**")
    c.ok("三个写方法在处理器文件里各只调一次（链路只有一条）", subs(hc, "ds.transferOrderLines(") == 1 and subs(hc, "ds.releaseOrder(") == 1 and subs(hc, "ds.updateOrderContact(") == 1)
    c.has("处理器注册进服务：转货", s, "TransferOrderHandler(ds, store),")
    c.has("处理器注册进服务：静默退回", s, "ReleaseOrderHandler(ds, store),")
    c.has("处理器注册进服务：补联系信息", s, "UpdateOrderContactHandler(ds, store),")
    c.ok("注册处各只有一处", subs(sc, "TransferOrderHandler(ds, store)") == 1 and subs(sc, "ReleaseOrderHandler(ds, store)") == 1 and subs(sc, "UpdateOrderContactHandler(ds, store)") == 1)
    c.has("处理器文件里有这一段的小标题", h, "订单结构三条（CHG-0085）")

    print("== 7. 资源与撤回 ==")
    c.has("补联系信息挂 ORDER 资源的 update（⇒ 有一键撤回）", rs, "update(AiWrites.ORDERS_UPDATE_CONTACT),")
    c.ok("补齐那一行只有一处", subs(rs, "update(AiWrites.ORDERS_UPDATE_CONTACT),") == 1)
    c.ok("⛔ 转货不挂资源（它没有一键撤回）", "AiWrites.ORDERS_TRANSFER" not in rs)
    c.ok("⛔ 静默退回不挂资源", "AiWrites.ORDERS_RELEASE" not in rs)
    for key, cn in (("contact_dongjia_name", "收货人名称"), ("contact_dongjia_phone", "收货人电话"), ("contact_boss_name", "下单人名称"), ("contact_boss_phone", "下单人电话")):
        c.ok("资源读回键里有「" + cn + "」（撤回要读得回旧值）", '"' + key + '"' in rs)
        c.ok("资源中文名里有「" + cn + "」", '"' + key + '" to "' + cn + '",' in rs)
    c.has("补联系信息的资源注释写明只动四个联系字段", rs, "只动四个联系字段，**终态单也允许**")
    c.has("转货：已声明撤不回来（UNDO_NONE 里有它一条）", rv, "listOf(AiWrites.ORDERS_TRANSFER),")
    c.has("静默退回：已声明撤不回来", rv, "listOf(AiWrites.ORDERS_RELEASE),")
    c.ok("转货与静默退回各自一条（不是合并成一条 listOf 两项的声明）", subs(rv, "listOf(AiWrites.ORDERS_TRANSFER),") == 1 and subs(rv, "listOf(AiWrites.ORDERS_RELEASE),") == 1)
    i_tr = rv.find("listOf(AiWrites.ORDERS_TRANSFER),")
    i_re = rv.find("listOf(AiWrites.ORDERS_RELEASE),")
    seg_tr = rv[i_tr:i_tr + 300] if i_tr >= 0 else ""
    seg_re = rv[i_re:i_re + 300] if i_re >= 0 else ""
    c.ok("转货的理由就写在这一条声明里（不是挂在别处）", len(seg_tr) > 60 and "转货一次动两张单" in seg_tr)
    c.has("转货的理由：它一次动两张单", seg_tr, "转货一次动两张单（源单少了那几行、目标单多了那几行，搬空了源单还会作废）——")
    c.has("转货的理由点名出路（再发起一次反向的转货）", seg_tr, "要转回去请再发起一次反向的转货（把那些货从目标单转回来）")
    c.ok("静默退回的理由也写在这一条声明里", len(seg_re) > 60 and "退回派单池只是把单" in seg_re)
    c.has("静默退回的理由：货主那边什么都不知道", seg_re, "退回派单池只是把单从司机手里收了回来（货主那边什么都不知道）——")
    c.has("静默退回的理由点名出路（重新派给原来的司机）", seg_re, "要还原就重新派给原来的司机")
    c.ok("⛔ 补联系信息**不**进 UNDO_NONE（它有一键撤回）", "AiWrites.ORDERS_UPDATE_CONTACT" not in rv)

    print("== 8. 覆盖表：三条从「不做」里移走，留下改口径的来龙去脉 ==")
    wcov = read(WRITE_COVERAGE)
    c.hasnt("POST orders/{}/transfer 不再挂在「不做」里", wcov, '("POST", "orders/{}/transfer")')
    c.hasnt("POST orders/{}/release 不再挂在「不做」里", wcov, '("POST", "orders/{}/release")')
    c.hasnt("PATCH orders/{}/contact 不再挂在「不做」里", wcov, '("PATCH", "orders/{}/contact")')
    c.ok("覆盖表里两处改口径的来龙去脉都在（CHG-0085 开给 AI）", subs(wcov, "CHG-0085 开给 AI") == 2, "实际 " + str(subs(wcov, "CHG-0085 开给 AI")))
    c.has("覆盖表里点名台账 L-54", wcov, "台账 L-54")
    c.has("静默退回那条改口径的理由留了（原来的理由是哪一类）", wcov, "理由是这个动作的定义就是**货主无感**")
    c.has("转货那条改口径的理由留了（原来是排期，不是能力缺口）", wcov, "是排期，不是能力缺口")
    c.has("转货改口径后由谁承担多行输入（写成 `lines` 数组）", wcov, "由 `lines` 数组 ＋")
    c.has("补联系信息那条写清与「改单」不是一个动作", wcov, "这一条与「改单」**不是同一个动作**")
    c.has("补联系信息那条点名后端权限点", wcov, "order:edit_contact")
    c.has("补联系信息那条写明终态单放行（这一扇门存在的理由）", wcov, "货送完了才发现号码写错")
    c.has("两条只给派单员这件事写在覆盖表里", wcov, "货主连清单里都看不见")
    wout, wrc = run_cmd([sys.executable, str(WRITE_COVERAGE)])
    c.ok("写覆盖脚本实跑通过（exit 0）", wrc == 0, "exit " + str(wrc))
    c.has("写覆盖表：三条已不在未覆盖里（29 条全有理由、0 条真缺口）", wout, "未覆盖 29（其中 29 条有写下来的「不做」理由，0 条是真缺口）")
    rout, rrc = run_cmd([sys.executable, str(READ_COVERAGE), "--check"])
    c.ok("读覆盖脚本 --check 实跑通过（exit 0）", rrc == 0, "exit " + str(rrc))
    c.has("读覆盖：没交代的仍然是 0", rout, "❓ 没交代：0")

    print("== 9. 单测 / 文书 / 反验 / 防静默空转 ==")
    for name in ("转货：转给系统里的货主", "转货：临时货主", "转货：转给谁必须二选一", "转货：明细的形状",
                 "转货：终态单不能转", "转货：收货人姓名电话都是空的", "静默退回：卡片要写明货主那边没有任何变化",
                 "静默退回：不写理由", "静默退回：待派单、已送达的单没有", "补联系信息：货主补自己那一单",
                 "补联系信息：一个字段都不给要拦住", "补联系信息：终态单也能补", "订单结构三条的角色门"):
        c.has("单测里有这一条：" + name, t, name)
    n_cases = subs(t, "fun `转货：") + subs(t, "fun `静默退回：") + subs(t, "fun `补联系信息：") + subs(t, "fun `订单结构三条的角色门")
    c.ok("单测里数到 13 条本单用例", n_cases == 13, "实际 " + str(n_cases))
    c.ok("单测里钉住了动作总数上界 165", "AiWrites.ALL.size <= 165" in t)
    c.has("单测里钉住了角色矩阵：货主不能转货", t, "assertFalse(\"转货会同时改两张单，货主只能发起退货申请\", AiWrites.allows(shipper, AiWrites.ORDERS_TRANSFER))")
    c.has("单测里钉住了角色矩阵：货主能补联系信息", t, "assertTrue(AiWrites.allows(shipper, AiWrites.ORDERS_UPDATE_CONTACT))")
    c.has("单测里钉住了模型可见性（货主的清单里没有转货）", t, "assertFalse(AiWrites.forModel(shipper).any { it.id == AiWrites.ORDERS_TRANSFER })")
    c.has("说明书上限已抬到 27000（动作数涨了）", pt, "上限 27000")
    c.ok("变更单九节齐（少一节 _check_dev_spec.py 也会红）", all(x in read(CHG_DOC) for x in CHG_SECTIONS))
    c.has("变更单里写了台账 L-54", read(CHG_DOC), "L-54")
    c.has("登记簿里有这一条", read(REGISTRY), CHG_ID)
    c.has("工作声明里有这一条", read(CLAIM), CHG_ID)
    c.has("台账里有 L-54 那一行", read(LEDGER), "L-54")
    c.ok("反向验证脚本在", (ROOT / REVERSE).exists(), REVERSE)
    c.ok("判据自己数到了足够多的断言（>= 110 条）", c.passes >= 110, "实际 " + str(c.passes))

    print()
    if c.fails:
        print("❌ " + str(len(c.fails)) + " 条不通过（共 " + str(c.passes + len(c.fails)) + " 条）：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print("✅ 全部 " + str(c.passes) + " 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
