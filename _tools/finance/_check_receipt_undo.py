#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_check_receipt_undo.py —— TB-09 / BUG-0029 的机器判据：客户收款登记之后**必须有一条能撤销、也能恢复的路**。

### 这条是怎么来的
台账 TB-09（测试会话 2026-10-10 03:03 CST 留档，证据 _tmp/test_round3/evidence_TB09_receipt_no_undo.txt）：
派单员在账本里登记一笔客户收款（POST /api/v1/ledger/receipts）会一次写**四个落点** ——
shipper_receipts 一行、它写下的 cash_flows(RECEIPT_CASH 等) 若干行、被翻成 paid=true 的那几张订单、
以及由前两者算出来的 turnover.collected/arrears 与 customer-balances；而撤销入口**一个都没有**
（DELETE/PATCH /ledger/receipts/{id}、POST /{id}/restore、/{id}/cancel、DELETE /cash-flows/{id} 全部 404）。
系统自己知道：backend/app/api/v1/orders_payment.py:199 的报错原文写着「系统目前没有撤销收款的入口……
请联系管理员在账上冲正」—— 而管理员同样没有入口。

### 为什么必须有机器的判据
「撤销」在代码里是**三处一起写标记**（流水软删、订单收回未收款、收款单软删），「恢复」是把它们原样放回。
这类改动最危险的形态是**只做一半**：只软删流水不翻 orders.paid，或者只翻 paid 不软删流水 —— 两边的数都
回不去（backend/app/services/order_money.py 的口径是「有流水按流水算、没流水才按 paid 算」），
而界面上**一点异常都看不出来**。所以这条链路必须钉住四件事：四个落点一起回滚、只回滚一次、软删而不是
物删、每一次都留痕；再加上「界面要有一个手边的撤销入口」（用户 2026-09-20 的硬规矩第④条 —— 这一条 bug
的原始形态正是「只有系统自己知道撤不回来」）。

R4-BOUNDARY-JUSTIFICATION: 这一单加的是**一个新的扩展点**（两个写端点 ＋ 收款单的软删两列），没有改任何
既有口径：create_receipt 的金额校验、settle_mode 的两种语义、cash_flows 的逐单生成规则一个字都没动；
核心区只碰了两处且都是纯追加（enums 的两个动作码、schema_bootstrap 的幂等 DDL）。边界没有重画的必要 ——
病灶是「一条写入路径没有反向路径」，不是「谁越界」。

### 反向破坏用例（每条都必须让本判据变红）
_tools/finance/_reverse_verify_receipt_undo.py（逐条注入：只软删流水不翻 paid、只翻 paid 不软删流水、
软删改成物删、恢复不做三道门、把「已经撤销过」的拒绝拆掉、列表不再过滤 is_deleted、两个审计码摘掉、
ReportCenter 摘掉中文名、界面摘掉撤销/恢复键、AI 侧把排期理由删掉、回归用例改名、变更单少一节、
登记表去掉状态、台账行改名、认领簿换号……）。跑法：python -X utf8 _tools/finance/_reverse_verify_receipt_undo.py

### 静默空转保护
- 后端 .py 少于 MIN_FILES 个直接判红 —— 「一个文件都没读到」不许算通过；
- 每个被判的函数体必须长于 MIN_BODY 字符（切歪了要喊，不许静默变成空串）；
- 回归用例数有下界（MIN_CASES），用例被删或改名要红；
- 逐条锚点都是**字面量**，锚点漂了立刻红，而不是安静地什么都不查。

用法：
    python -X utf8 _tools/finance/_check_receipt_undo.py            # 逐条明细
    python -X utf8 _tools/qa/_check_all.py --only receipt_undo     # 只跑这一份
    python -X utf8 _tools/finance/_check_receipt_undo.py --list    # 只列小节，不跑
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ai"))

from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
MODEL = BACKEND / "app" / "models" / "shipper_receipt.py"
ENUMS = BACKEND / "app" / "models" / "enums.py"
BOOT = BACKEND / "app" / "core" / "schema_bootstrap.py"
SCHEMA = BACKEND / "app" / "schemas" / "accounting_v2.py"
API = BACKEND / "app" / "api" / "v1" / "ledger.py"
MONEY = BACKEND / "app" / "services" / "order_money.py"
KTEST = BACKEND / "tests" / "test_receipt_undo.py"

AND = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"
APIS = AND / "data" / "remote" / "api" / "Apis.kt"
REPO = AND / "data" / "repo" / "AppRepository.kt"
DTOS = AND / "data" / "remote" / "dto" / "Dtos.kt"
SCREEN = AND / "ui" / "dispatcher" / "AccountToolsScreens.kt"
REPORT = AND / "ui" / "dispatcher" / "ReportCenter.kt"
REVERT = AND / "ai" / "AiRevert.kt"
COVER = ROOT / "_tools" / "ai" / "_write_coverage.py"

CHANGE = ROOT / "docs" / "changes" / "BUG-0029.md"
README = ROOT / "docs" / "changes" / "README.md"
LEDGER = ROOT / "docs" / "TEST_BUG_LEDGER.md"
CLAIM = ROOT / "docs" / "AI_WORK_CLAIM.md"
RVERIFY = HERE / "_reverse_verify_receipt_undo.py"

MIN_FILES = 200
MIN_BODY = 800
MIN_CASES = 7

SECTIONS = [
    "零、现场（防静默空转）",
    "一、软删两列（模型 ＋ 线上迁移）",
    "二、撤销：四个落点一起回滚",
    "三、恢复：三道门 ＋ 原样放回",
    "四、只回滚一次（幂等）与不物删",
    "五、列表默认过滤 ＋ 回收站档",
    "六、审计：两个码写痕 ＋ 两个中文名",
    "七、App 手边入口（不许只留接口不画界面）",
    "八、AI 侧门禁与那句不再说假话的撤回理由",
    "九、回归用例与文档登记",
]

CASE_NAMES = [
    "test_cancel_then_restore_moves_all_four_landing_points",
    "test_second_cancel_and_second_restore_are_rejected",
    "test_cancel_never_physically_deletes_anything",
    "test_receipt_list_hides_cancelled_until_include_deleted",
    "test_cancel_and_restore_each_leave_one_audit_log",
    "test_restore_refuses_when_the_order_was_collected_again",
    "test_cancel_needs_dispatcher_and_a_real_receipt",
]


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def py_code(src: str) -> str:
    """剥掉三引号块与整行注释：判据只锚**代码**，不许被说明文字骗过去。"""
    # 三引号块用 .*? ＋ flags=re.S 剥（不写反斜杠：这个脚本自己也被判据读，别让它带语法警告）
    src = re.sub(chr(34) * 3 + ".*?" + chr(34) * 3, "", src, flags=re.S)
    src = re.sub(chr(39) * 3 + ".*?" + chr(39) * 3, "", src, flags=re.S)
    return re.sub("^[ \t]*#.*$", "", src, flags=re.M)


def py_func(src: str, name: str) -> str:
    m = re.search("^def " + re.escape(name) + "[(]", src, re.M)
    if not m:
        return ""
    rest = src[m.start():]
    nxt = re.search("^(?:def |class |@)", rest[1:], re.M)
    return rest[: nxt.start() + 1] if nxt else rest


def flow_lookup_sites() -> list[tuple[str, str]]:
    """谁在「找出这笔收款写下的资金流水」（判据必须只有一处）。"""
    #: 只认「按收款单找流水」那一处（suppliers / 开销回填那些也是 doc_id，但对象不同）
    pat = re.compile("CashFlow[.]doc_id == receipt_id")
    out: list[tuple[str, str]] = []
    for p in sorted(BACKEND.rglob("*.py")):
        rel = p.relative_to(ROOT).as_posix()
        if "/tests/" in rel or p.name.startswith("test_"):
            continue
        for line in py_code(read(p)).splitlines():
            if pat.search(line):
                out.append((rel, line.strip()))
    return out


class Checker:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0

    @property
    def total(self) -> int:
        return self.passed + self.failed

    def ok(self, label: str, cond: bool, detail: str = "") -> bool:
        if cond:
            self.passed += 1
            print(f"  [OK]   {label}")
        else:
            self.failed += 1
            print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))
        return bool(cond)

    def report(self, title: str) -> int:
        print()
        print(f"===== {title} =====")
        print(f"  通过 {self.passed} 项，失败 {self.failed} 项")
        if self.failed == 0:
            print(f"全部 {self.total} 项通过。")
        return self.failed


def section(title: str) -> None:
    print()
    print(f"---- {title} ----")


def q(s: str) -> str:
    """拼一段**带双引号**的源码字面量（本脚本自己用双引号写 Python 字符串，不引号嵌套）。"""
    return chr(34) + s + chr(34)


def main() -> int:
    if "--list" in sys.argv:
        for s in SECTIONS:
            print(s)
        return 0
    if refuse_if_injecting("_check_receipt_undo.py"):
        return 1

    ck = Checker()
    model_raw = read(MODEL)
    boot_raw = read(BOOT)
    enums_raw = read(ENUMS)
    schema_raw = read(SCHEMA)
    api_raw = read(API)
    money_raw = read(MONEY)
    ktest = read(KTEST)
    apis_raw = read(APIS)
    repo_raw = read(REPO)
    dtos_raw = read(DTOS)
    screen_raw = read(SCREEN)
    report_raw = read(REPORT)
    revert_raw = read(REVERT)
    cover_raw = read(COVER)

    cancel = py_func(py_code(api_raw), "cancel_receipt_endpoint")
    restore = py_func(py_code(api_raw), "restore_receipt_endpoint")
    flows_fn = py_func(py_code(api_raw), "_receipt_flows")
    list_fn = py_func(py_code(api_raw), "list_receipts")

    # --------------------------------------------------- 零、现场
    section(SECTIONS[0])
    nfiles = len(list(BACKEND.rglob("*.py")))
    ck.ok(f"后端 .py 扫到 {nfiles} 个（下界 {MIN_FILES}）", nfiles >= MIN_FILES, "读到的文件太少，判据可能空转")
    for p, tag in ((MODEL, "模型"), (ENUMS, "枚举"), (BOOT, "自举"), (SCHEMA, "出参"), (API, "接口"), (KTEST, "回归用例")):
        ck.ok(f"{tag}文件在：{p.relative_to(ROOT).as_posix()}", p.is_file())
    ck.ok("cancel_receipt_endpoint 的函数体读到了", len(cancel) > MIN_BODY, f"只有 {len(cancel)} 字符（切歪了？）")
    ck.ok("restore_receipt_endpoint 的函数体读到了", len(restore) > MIN_BODY, f"只有 {len(restore)} 字符（切歪了？）")
    ck.ok("_receipt_flows 的函数体读到了", len(flows_fn) > 200, f"只有 {len(flows_fn)} 字符")

    # --------------------------------------------------- 一、软删两列
    section(SECTIONS[1])
    ck.ok("模型上真的挂了 SoftDeleteMixin（不是自己手写两个字段）",
          "class ShipperReceipt(Base, TimestampMixin, SoftDeleteMixin):" in model_raw,
          "收款单没有 is_deleted/deleted_at ⇒ 撤销只能物删，违反用户 2026-09-20 的硬规矩")
    ck.ok("模型 docstring 写清了「查询侧必须一起改」",
          "查询侧必须一起改" in model_raw and "include_deleted" in model_raw,
          "不写这一句，下一个人会以为加了列就完事")
    ck.ok("线上迁移补了 shipper_receipts 的两列（幂等 DDL）",
          "if " + chr(34) + "shipper_receipts" + chr(34) + " in tables:" in boot_raw
          and "ALTER TABLE shipper_receipts ADD COLUMN {col} {ddl_type}" in boot_raw
          and q("is_deleted") + ", " + q("BOOLEAN NOT NULL DEFAULT 0") in boot_raw
          and q("deleted_at") + ", " + q("DATETIME") in boot_raw,
          "缺迁移 ⇒ 已上线的库没有这两列，撤销接口当场 500")
    ck.ok("迁移建了 is_deleted 索引", "CREATE INDEX ix_shipper_receipts_is_deleted" in boot_raw)
    ck.ok("迁移把历史行回填成 0（不是留 NULL）",
          "UPDATE shipper_receipts SET is_deleted = 0 WHERE is_deleted IS NULL" in boot_raw,
          "留 NULL 的话 WHERE is_deleted = 0 不成立，历史收款会整体消失")
    ck.ok("迁移注释写明了「另两处读取刻意不过滤」的理由",
          "挂账单位占用计数" in boot_raw and "客户合并时的搬迁" in boot_raw,
          "不写清就是「漏了一处」与「判断」分不开")
    ck.ok("出参加了两个字段（回收站档要靠它画「已撤销」与「恢复」）",
          "is_deleted: bool = False" in schema_raw and "deleted_at: datetime | None = None" in schema_raw)

    # --------------------------------------------------- 二、撤销
    section(SECTIONS[2])
    ck.ok("撤销端点挂在 DELETE /receipts/{receipt_id}",
          "@router.delete(" + q("/receipts/{receipt_id}") in api_raw, "路由不在 ⇒ 就是 TB-09 那个 404")
    ck.ok("撤销要 DISPATCHER（403 非派单员）",
          "detail=" + q("仅派单员可操作") in cancel, "没闸门：货主/司机能把别人账上的收款撤掉")
    ck.ok("不存在的收款单 → 404", "detail=" + q("这笔收款记录不存在") in cancel)
    ck.ok("已经撤销过的 → 400 明确拒绝（不是静默成功）",
          "已经撤销过了，不用再撤一次" in cancel, "第二次撤销会把账上的数改第二遍")
    ck.ok("找不到流水 → 400 拒绝（宁可不动，也不做半个撤销）",
          "没有对应的资金流水，没法撤销" in cancel)
    ck.ok("落点①：这笔收款的资金流水逐行软删（is_deleted=True ＋ deleted_at）",
          "f.is_deleted = True" in cancel and "f.deleted_at = now" in cancel)
    ck.ok("落点②：订单收回未收款（paid=False ＋ payment_method 回到挂账）",
          "o.paid = False" in cancel and "o.payment_method = " + q("arrears") in cancel,
          "只软删流水不翻 paid，order_money 的兜底那条会继续把这笔算成已收")
    ck.ok("落点③：收款单本身软删（不是物理删除）",
          "r.is_deleted = True" in cancel and "r.deleted_at = now" in cancel)
    ck.ok("落点④：由前两者算出的那两处不用另写 —— 口径只有 order_money 一处",
          "got if got > ZERO else (total if o.paid else ZERO)" in money_raw,
          "order_money 的兜底口径变了：四个落点一起回滚的前提就没了")
    ck.ok("撤销写一条 RECEIPT_CANCEL 留痕（含逐项 payload）",
          "action=OperationAction.RECEIPT_CANCEL" in cancel
          and all(q(k) in cancel for k in ("receipt_id", "order_ids", "flow_ids", "orders_rolled_back")),
          "钱动了不留痕，事后答不上「这笔是谁撤的」")
    ck.ok("撤销也入发件箱（货主/司机手机上的数要跟着变）",
          "_receipt_push(db, r.customer_id, order_ids)" in cancel)
    ck.ok("找这笔收款的流水只有一处判据，且认全三种 biz",
          len(flow_lookup_sites()) == 1 and "RECEIPT_FLOW_BIZ" in flows_fn
          and all(b in api_raw for b in ("RECEIPT_CASH", "RECEIPT_TRANSFER", "RECEIPT_ARREARS")),
          "实际：" + "；".join(rel for rel, _ in flow_lookup_sites())
          + "（只认 RECEIPT_CASH 的话，转账/微信/挂账结清的收款撤不干净）")

    # --------------------------------------------------- 三、恢复
    section(SECTIONS[3])
    ck.ok("恢复端点挂在 POST /receipts/{receipt_id}/restore（返回收款单）",
          "@router.post(" + q("/receipts/{receipt_id}/restore") in api_raw
          and "response_model=ShipperReceiptOut" in api_raw)
    ck.ok("没被撤销的 → 400（幂等，不许把数改回来第二遍）",
          "没有被撤销，不需要恢复" in restore)
    ck.ok("门①：订单不存在 → 400 点名单号", "不存在，恢复这笔收款会把钱算在一张查不到的单上" in restore)
    ck.ok("门②：订单在回收站 → 400 点名", "在回收站里，请先把它恢复回来再恢复这笔收款" in restore)
    ck.ok("门③：订单已撤销/已退货 → 400 点名",
          "OrderStatus.CANCELLED.value" in restore and "OrderStatus.RETURNED.value" in restore
          and "已撤销或已退货" in restore)
    ck.ok("门④：该单又被收过一次（现在已是已收款）→ 400 并点名",
          "现在已经是「已收款」了" in restore and "请先撤销那一次收款" in restore,
          "不拦的话，同一笔钱会被算两遍")
    ck.ok("恢复把订单写回已收（paid=True ＋ payment_method 按收款方式写回）",
          "o.paid = True" in restore and "o.payment_method = " + q("cash") in restore)
    ck.ok("恢复把流水与收款单原样放回（is_deleted=False ＋ deleted_at=None）",
          "f.is_deleted = False" in restore and "f.deleted_at = None" in restore
          and "r.is_deleted = False" in restore and "r.deleted_at = None" in restore)
    ck.ok("恢复写一条 RECEIPT_RESTORE 留痕", "action=OperationAction.RECEIPT_RESTORE" in restore)
    ck.ok("三道门都在**改数之前**（门先跑完再放回，不是边放边判）",
          restore.index("现在已经是「已收款」了") < restore.index("o.paid = True"),
          "门在写之后 ⇒ 已经改了一半才拒绝")

    # --------------------------------------------------- 四、幂等与不物删
    section(SECTIONS[4])
    ck.ok("撤销与恢复里都没有物理删除（db.delete 一处都没有）",
          "db.delete(" not in cancel and "db.delete(" not in restore,
          "物删的话这笔钱的历史就没了（用户定的规矩是软删）")
    ck.ok("「收款单已删」是幂等的唯一依据",
          "if r.is_deleted:" in cancel and "if not r.is_deleted:" in restore,
          "靠别的东西判（比如订单状态）会在第二次调用时改第二遍数")
    ck.ok("订单侧的回滚是「当前还是已收才动」的幂等形状",
          "if not o.paid:" in cancel and "continue" in cancel)

    # --------------------------------------------------- 五、列表与回收站
    section(SECTIONS[5])
    ck.ok("收款记录加了 include_deleted 档（默认 False）",
          "include_deleted: bool = Query(False, description=" + q("含已撤销的（回收站）") + ")" in api_raw)
    ck.ok("默认过滤 is_deleted（不带这一句，撤销点了跟没点一样）",
          "if not include_deleted:" in list_fn and "ShipperReceipt.is_deleted.is_(False)" in list_fn)
    ck.ok("列表出参把 is_deleted/deleted_at 带出去（界面靠它画恢复键）",
          "is_deleted=bool(r.is_deleted), deleted_at=r.deleted_at," in list_fn)

    # --------------------------------------------------- 六、审计
    section(SECTIONS[6])
    ck.ok("两个新审计码在 enums.py 里（各自独立，不复用 RECEIPT_CREATE）",
          "RECEIPT_CANCEL = " + q("RECEIPT_CANCEL") in enums_raw
          and "RECEIPT_RESTORE = " + q("RECEIPT_RESTORE") in enums_raw
          and enums_raw.index("RECEIPT_CANCEL = ") != enums_raw.index("RECEIPT_CREATE = "))
    ck.ok("enums 的注释写清了「为什么不复用 RECEIPT_CREATE」",
          "为什么不复用" in enums_raw and "方向相反的两件事" in enums_raw)
    ck.ok("ReportCenter.kt 给了两个中文名（否则审计页只显示原始码）",
          q("RECEIPT_CANCEL") + " -> " + q("撤销收款") in report_raw
          and q("RECEIPT_RESTORE") + " -> " + q("恢复收款") in report_raw)

    # --------------------------------------------------- 七、App 手边入口
    section(SECTIONS[7])
    ck.ok("Apis.kt 两个新端点（DELETE ＋ restore）",
          "@DELETE(" + q("ledger/receipts/{receiptId}") in apis_raw
          and "@POST(" + q("ledger/receipts/{receiptId}/restore") in apis_raw
          and "suspend fun cancelReceipt(" in apis_raw and "suspend fun restoreReceipt(" in apis_raw)
    ck.ok("Apis.kt 的收款记录带 include_deleted 查询参数",
          "@Query(" + q("include_deleted") + ") includeDeleted: Boolean = false" in apis_raw)
    ck.ok("AppRepository 三个方法（含 includeDeleted 开关）",
          "includeDeleted: Boolean = false" in repo_raw
          and "suspend fun cancelReceipt(receiptId: Long)" in repo_raw
          and "suspend fun restoreReceipt(receiptId: Long)" in repo_raw)
    ck.ok("Dtos.kt 的 ReceiptDto 认识 is_deleted（老后端回落 false）",
          "@SerialName(" + q("is_deleted") + ") val isDeleted: Boolean = false" in dtos_raw)
    ck.ok("收款页有「撤销」键（手边可点，不是只留接口）",
          "Text(" + q("撤销") + ", color = MaterialTheme.colorScheme.error)" in screen_raw)
    ck.ok("收款页有「恢复」键", "Text(" + q("恢复") + ")" in screen_raw)
    ck.ok("收款页有回收站档（撤销完再回来也找得到）",
          "Text(if (vm.showDeleted) " + q("只看未撤销") + " else " + q("显示已撤销") + ")" in screen_raw)
    ck.ok("撤销走二次确认弹层（钱的动作先问一句）",
          "DangerConfirmDialog(" in screen_raw and "title = " + q("撤销这笔收款？") in screen_raw)
    ck.ok("撤销后那条 snackbar 自带「撤回」（手边那一下）",
          "actionLabel = " + q("撤回") in screen_raw and "restoreLastCancelled" in screen_raw)
    ck.ok("撤销/恢复真的走 repo（不是画了个假按钮）",
          "container.repo.cancelReceipt(r.id)" in screen_raw and "container.repo.restoreReceipt(r.id)" in screen_raw)
    ck.ok("已撤销的行在界面上有话说（不是安静地变成一样）",
          "这笔钱现在不算数" in screen_raw and "deletedAt" in screen_raw)

    # --------------------------------------------------- 八、AI 侧门禁
    section(SECTIONS[8])
    ck.ok("两个新端点在 _write_coverage 的 EXCLUDED 里有书面理由（排期，不是永久排除）",
          q("DELETE") + ", " + q("ledger/receipts/{}") in cover_raw
          and q("POST") + ", " + q("ledger/receipts/{}/restore") in cover_raw
          and "本轮只做人手出口" in cover_raw)
    ck.ok("AiRevert 里那句「撤回来等于把账抹掉」已经不在（BUG-0029 之后它是假话）",
          "撤回来等于把账抹掉" not in revert_raw, "还在 ⇒ AI 会把用户指向一条不存在的路")
    ck.ok("AiRevert 改成指向真实入口（账本 →「客户收款」的收款记录）",
          "请到账本" in revert_raw and "撤销" in revert_raw, "撤回理由没有说清去哪儿撤")

    # --------------------------------------------------- 九、回归用例与文档
    section(SECTIONS[9])
    names = re.findall("^def (test_[A-Za-z0-9_]+)[(]", ktest, re.M)
    ck.ok(f"回归用例文件在，用例 {len(names)} 条（下界 {MIN_CASES}）",
          bool(ktest) and len(names) >= MIN_CASES, f"只有 {len(names)} 条")
    lost = [n for n in CASE_NAMES if n not in names]
    ck.ok(f"七条用例逐条还在（{len(CASE_NAMES)} 条）", not lost, "丢了或改名了：" + "、".join(lost))
    ck.ok("用例里有「四个落点」那一条的核心断言（collected/arrears/income/balance 逐个比）",
          all(q(k) in ktest for k in ("collected", "arrears_total", "income", "balance"))
          and "_landing_points" in ktest)
    change = read(CHANGE)
    need = ["# BUG-0029 ·", "## ① 六问", "## ② Must Change / Must Not Change", "## ③ Boundary",
            "R4-BOUNDARY-JUSTIFICATION：", "## ④ Behavior Contract", "## ⑤ Data Contract",
            "## ⑥ CHG 专章", "## ⑦ 测试", "## ⑧ 证据", "## ⑨ 关闭"]
    lack = [s for s in need if s not in change]
    ck.ok("变更单 docs/changes/BUG-0029.md 在，且九节齐全", bool(change) and not lack,
          ("缺：" + "、".join(lack)) if change else "文件不在")
    rows = [ln for ln in read(README).splitlines() if "BUG-0029" in ln]
    ck.ok("登记表 docs/changes/README.md 有 BUG-0029 行（状态列带「已提交」）",
          len(rows) == 1 and "已提交" in rows[0], f"命中 {len(rows)} 行")
    led = [ln for ln in read(LEDGER).splitlines() if ln.startswith("| TB-09 ")]
    ck.ok("台账 docs/TEST_BUG_LEDGER.md 的 TB-09 行标着「已修复」",
          len(led) == 1 and "已修复" in led[0], f"命中 {len(led)} 行")
    claim_text = read(CLAIM)
    ck.ok("认领簿有 BUG-0029 的声明 ＋ 两行「核心改动：」",
          "BUG-0029" in claim_text
          and "核心改动：backend/app/models/enums.py" in claim_text
          and "核心改动：backend/app/core/schema_bootstrap.py" in claim_text,
          "_check_core_freeze.py 会红：动了核心区文件就必须声明")
    ck.ok("反向验证脚本在（每条注入都要让本判据红）", RVERIFY.is_file(),
          RVERIFY.relative_to(ROOT).as_posix() + " 不在")

    return 1 if ck.report("TB-09 客户收款的撤销（软删）与恢复") else 0


if __name__ == "__main__":
    raise SystemExit(main())

