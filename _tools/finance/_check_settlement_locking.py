#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_check_settlement_locking.py —— TB-08 / BUG-0024 的机器判据：「建结算单＝锁住这批明细」必须真的发生，报错必须把两种成因分开说。

### 这条是怎么来的
台账 TB-08（测试会话 2026-10-10 02:57 CST 留档，证据 _tmp/test_round3/evidence_TB08_settlement_dup.txt）：
driver_id=3 / 2026-06，同一笔明细 bill id=12（22.00 元）能被**两张草稿结算单**同时收进去
（#59 与 #60 的 bill_ids 都是 [12]，而此刻明细还是 OPEN、settled_doc_id=NULL）；
确认 #59 之后再确认 #60 才报错，而报错把「被别的结算单占用」与「明细已被删除」糊成一句
（被删除或已被别的结算单占用）。更要命的是 api/v1/driver_settlements.py:93 那句注释
写着「建结算单＝把一批待结明细**锁进**一张单子」—— 与实际行为相反（注释与行为必须一致，
这一条是本 bug 的一半）。

### 为什么必须有机器的判据
「锁」在代码里只是**一列赋值**（create_settlement 里的 b.settled_doc_id = s.id）：
谁把它删掉，接口照样 200、两张单照样建得出来，界面上一点异常都看不出来 ——
冲突要拖到确认那一刻才炸，而那时用户已经照着两张单去安排钱了。
同类毛病在 BUG-0007（结算单金额与明细合计对不上）已经栽过一次，它那份判据
（_tools/qa/_check_settlement_single_source.py，40 项）证明静态锚点守得住这条链路；
本脚本是它的**姊妹判据**，专盯「建单当刻的锁」与「报错分因」两件事。

R4-BOUNDARY-JUSTIFICATION: 这一单只动结算单域内部的取数与措辞（accounting_service.py 的
settleable_bills / create_settlement / confirm_settlement / cancel_settlement 四个函数），
没有新增表、没有新增端点、没有改 schema 与前端契约 —— 边界（Core / Extension 分层）解决不了它：
病灶不是「谁越界」，而是「同一条链路里几段代码对『待结』的定义不一致」。
取数仍然只有 settleable_bills 一处实现，只是多了一个关键字参数把「没人锁的」与
「本单锁住的」区分开；边界图上没有任何一处需要重画。

### 反向破坏用例（每条都必须让本判据变红）
_tools/finance/_reverse_verify_settlement_locking.py（12 条注入：拆建单上锁、拆默认过滤、
拆 doc_id、把报错合回一句、拆老草稿过滤、拆作废解锁、让 CANCELLED 复活、把注释改回去、
删回归用例、删登记行……）。跑法：python -X utf8 _tools/finance/_reverse_verify_settlement_locking.py

### 静默空转保护
- 扫不到后端 .py（少于 MIN_FILES 个）直接判红 —— 「一个文件都没读到」不许算通过；
- 每个被判的函数体必须长于 MIN_BODY 字符（py_func 切歪了要喊，不许静默变成空串）；
- 回归用例数有下界（MIN_CASES），用例被删或改名要红；
- 逐条锚点都是**字面量**（不是正则片段），锚点漂了立刻红，而不是安静地什么都不查。

用法：
    python -X utf8 _tools/finance/_check_settlement_locking.py          # 逐条明细
    python -X utf8 _tools/qa/_check_all.py --only settlement_locking    # 只跑这一份
    python -X utf8 _tools/finance/_check_settlement_locking.py --list   # 只列小节，不跑
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
ACCT = BACKEND / "app" / "services" / "accounting_service.py"
API = BACKEND / "app" / "api" / "v1" / "driver_settlements.py"
KTEST = BACKEND / "tests" / "test_settlement_locking.py"
RVERIFY = HERE / "_reverse_verify_settlement_locking.py"
CHANGE = ROOT / "docs" / "changes" / "BUG-0024.md"
README = ROOT / "docs" / "changes" / "README.md"
LEDGER = ROOT / "docs" / "TEST_BUG_LEDGER.md"
CLAIM = ROOT / "docs" / "AI_WORK_CLAIM.md"

MIN_FILES = 200
MIN_BODY = 200
MIN_CASES = 7
ACCT_REL = "backend/app/services/accounting_service.py"

SECTIONS = [
    "零、现场（防静默空转）",
    "一、建单当刻真的上锁",
    "二、确认：看得见自己锁的、说得清别人锁的",
    "三、作废把锁放回待结、且不复活已作废的明细",
    "四、单写者：给 settled_doc_id 赋值的地方只有那三处",
    "五、注释与行为一致（这条是本 bug 的一半）",
    "六、回归用例（不许掉数）",
    "七、文档与登记（变更单 / 登记表 / 台账 / 认领簿 / 反验）",
]

CASE_NAMES = [
    "test_同一笔明细不能被两张草稿单同时锁住",
    "test_确认时报错要把被占用与已删除分开说",
    "test_作废草稿单把锁放回待结",
    "test_老草稿按月重取也不许抢别人锁住的明细",
    "test_保留任务已作废的明细_作废草稿单时不许复活",
    "test_两个月份的草稿单各自锁各自的",
    "test_确认到付款的顺路还在",
]

#: 要在 confirm 里点名的既有措辞（BUG-0007 的判据与既有测试都锚着它们，不许弄丢）。
KEEP_IN_CONFIRM = ["已经不在了", "请作废后重新结算", "gone"]
#: 修掉的那句「糊成一句」的老话：出现即判红。
OLD_CONFLATED = "（被删除或已被别的结算单占用）"


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def py_code(src: str) -> str:
    """剥掉三引号块与整行注释：判据只锚**代码**，不许被说明文字骗过去。"""
    src = re.sub(r'"""[\s\S]*?"""', "", src)
    src = re.sub(r"'''[\s\S]*?'''", "", src)
    return re.sub(r"^[ \t]*#.*$", "", src, flags=re.M)


def py_func(src: str, name: str) -> str:
    m = re.search(r"^def " + re.escape(name) + r"\(", src, re.M)
    if not m:
        return ""
    rest = src[m.start():]
    nxt = re.search(r"^(?:def |class |@)", rest[1:], re.M)
    return rest[: nxt.start() + 1] if nxt else rest


def assign_sites() -> list[tuple[str, str]]:
    """谁给 driver_bills.settled_doc_id 赋值（扫全后端，不含测试）。

    这一列就是「锁」，所以它的**写点**必须是一份可数的清单：多一处就多一种绕过方式。
    """
    pat = re.compile(r"\.settled_doc_id\s*=\s*(?!=)")
    out: list[tuple[str, str]] = []
    for p in sorted(BACKEND.rglob("*.py")):
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
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
    print(f"-- {title} --")


def main() -> int:
    if refuse_if_injecting("_check_settlement_locking.py"):
        return 1
    if "--list" in sys.argv:
        for s in SECTIONS:
            print("  " + s)
        return 0

    ck = Checker()
    acct_raw = read(ACCT)
    acct = py_code(acct_raw)
    api_raw = read(API)
    sb = py_func(acct, "settleable_bills")
    create = py_func(acct, "create_settlement")
    confirm = py_func(acct, "confirm_settlement")
    pay = py_func(acct, "pay_settlement")
    cancel = py_func(acct, "cancel_settlement")
    why_gone = py_func(acct, "_why_gone")
    claimed_where = py_func(acct, "_claimed_where")
    label = py_func(acct, "_settlement_label")

    # ---------------------------------------------------------------- 零、现场
    section(SECTIONS[0])
    py_files = sorted(BACKEND.rglob("*.py"))
    ck.ok(f"后端 .py 扫到 {len(py_files)} 个（下界 {MIN_FILES}）", len(py_files) >= MIN_FILES,
          f"只扫到 {len(py_files)} 个 —— 工作区或路径不对，下面所有结论都不能信")
    ck.ok(f"accounting_service.py 读到了（{len(acct_raw)} 字节）", len(acct_raw) > 5000,
          f"{ACCT_REL} 只有 {len(acct_raw)} 字节")
    bodies = {"settleable_bills": sb, "create_settlement": create, "confirm_settlement": confirm,
              "pay_settlement": pay, "cancel_settlement": cancel, "_why_gone": why_gone,
              "_claimed_where": claimed_where, "_settlement_label": label}
    thin = [n for n, b in bodies.items() if len(py_code(b)) < MIN_BODY]
    ck.ok(f"八个函数的正文都切得出来（各长于 {MIN_BODY} 字符）", not thin,
          "切歪了/不在了：" + "、".join(thin))

    # ------------------------------------------------- 一、建单当刻真的上锁
    section(SECTIONS[1])
    ck.ok("settleable_bills 的签名多出 doc_id / include_claimed 两个口子",
          "doc_id: int | None = None" in sb and "include_claimed: bool = False" in sb,
          "签名里没有这两个关键字参数 —— 取数就没法区分「没人锁的」与「本单锁住的」")
    ck.ok("默认只取「没人锁的」：DriverBill.settled_doc_id.is_(None)",
          "if not include_claimed:" in sb and "rows = rows.where(DriverBill.settled_doc_id.is_(None))" in sb,
          "默认过滤没了 —— 同一笔明细又能同时进两张草稿单（TB-08 复发）")
    ck.ok("传了 doc_id 时把本单自己锁住的也算回来",
          "DriverBill.settled_doc_id == doc_id" in sb and "or_(" in sb,
          "没这一条，confirm 按 bill_ids 核对时一行都取不回来 → 自己的单永远确认不了")
    ck.ok("create_settlement 里 b.settled_doc_id = s.id 写在 db.flush() 之后",
          "b.settled_doc_id = s.id" in create and "db.flush()" in create
          and create.index("db.flush()") < create.index("b.settled_doc_id = s.id"),
          "没有 flush 就拿不到 id；先上锁后 flush 写下去的是 None")
    ck.ok("create_settlement 里没有 DriverBillStatus.SETTLED（建单不结账）",
          "DriverBillStatus.SETTLED" not in create,
          "建单把明细翻成 SETTLED ⇒ 钱还没出账就算结过了")
    ck.ok("create_settlement 里没有 b.status =（上锁不改状态，仍是 OPEN）",
          "b.status =" not in create,
          "建单顺手改了 status ⇒ 「待结」与「已结」在草稿阶段就分不出来了")
    ck.ok("「空手而归」分开说：include_claimed=True 只用来点名是谁锁着",
          "include_claimed=True" in create and "已经被别的结算单锁住了" in create
          and "无待结算明细（请先生成账单）" in create,
          "第二张单被挡住时不说清是谁锁着，用户只能靠猜")
    ck.ok("锁的写法在 create 里只有一处、全文件只有两处 = s.id",
          create.count("b.settled_doc_id = s.id") == 1 and acct.count("b.settled_doc_id = s.id") == 2,
          f"create={create.count('b.settled_doc_id = s.id')} 全文={acct.count('b.settled_doc_id = s.id')}")

    # --------------------------------------------------- 二、确认时的两件事
    section(SECTIONS[2])
    ck.ok("confirm_settlement 取数带 doc_id=s.id",
          "doc_id=s.id" in confirm,
          "本单锁住的行仍是 OPEN 且 settled_doc_id=本单 ⇒ 不带 doc_id 就取不回来")
    ck.ok("confirm 的报错走 _why_gone 逐笔给结论",
          "_why_gone(db, s, gone)" in confirm, "报错没走分因逻辑")
    miss = [w for w in KEEP_IN_CONFIRM if w not in confirm]
    ck.ok("confirm 仍说「已经不在了」＋「请作废后重新结算」（既有判据与测试都锚它们）",
          not miss, "丢了：" + "、".join(miss))
    ck.ok("糊成一句的老话已经不在 accounting_service.py 里",
          OLD_CONFLATED not in acct_raw, "老话还在：" + OLD_CONFLATED)
    ck.ok("_why_gone 把三种成因分开：占用 / 已删除 / 状态已变",
          "已被别的结算单占用" in why_gone and "已被删除" in why_gone and "已不是待结状态" in why_gone,
          "有一类没说出来")
    ck.ok("_why_gone 用 settled_doc_id 与本单 id 区分「被谁锁着」",
          "row.settled_doc_id is not None" in why_gone and "!= int(s.id)" in why_gone,
          "不区分本单/别人的话，本单自己的行也会被当成「被别人占用」")
    ck.ok("_claimed_where 附单号（明细 X 在结算单 #Y）",
          "明细 {b.id} 在结算单" in claimed_where and "limit: int = 3" in claimed_where,
          "只说「被占用」不说是哪张单 —— 用户下一步（去作废哪张）无从下手")
    ck.ok("_settlement_label 四档状态都有人话",
          all(w in acct for w in ["_SETTLEMENT_STATUS_TEXT", '"草稿"', '"已确认"', '"已付款"', '"已作废"'])
          and "getattr(doc.status" in label,
          "状态是人话的一部分：不写「（草稿）」用户不知道该作废哪一张")
    ck.ok("老草稿的两条重取分支都加了「不许抢别人锁住的」",
          confirm.count("DriverBill.settled_doc_id.is_(None)") == 2,
          f"只加了 {confirm.count('DriverBill.settled_doc_id.is_(None)')} 处（按单号 / 按月各一处）")

    # --------------------------------------------------- 三、作废解锁
    section(SECTIONS[3])
    ck.ok("cancel 解锁仍认 settled_doc_id == s.id",
          "DriverBill.settled_doc_id == s.id," in cancel, "解锁的锚点丢了")
    ck.ok("cancel 解锁同时放回 SETTLED 与 OPEN 两种状态",
          "DriverBill.status == DriverBillStatus.SETTLED," in cancel
          and "DriverBill.status == DriverBillStatus.OPEN," in cancel and "or_(" in cancel,
          "只认 SETTLED ⇒ 建单当刻锁住的（仍 OPEN）永远解不开，那笔明细再也结不了")
    ck.ok("cancel 解锁里没有 CANCELLED（保留任务作废的明细不许复活）",
          "DriverBillStatus.CANCELLED" not in cancel,
          "把 CANCELLED 也放回 ⇒ 凭空多出一笔应付")
    ck.ok("cancel 把锁清成 None、状态回 OPEN",
          "b.settled_doc_id = None" in cancel and "b.status = DriverBillStatus.OPEN" in cancel)
    ck.ok("pay_settlement 的取数与金额恒等式没被改坏",
          "DriverBill.settled_doc_id == s.id" in pay
          and "live_total + Decimal(s.adjustment or Decimal(\"0\"))" in pay,
          "付款那一侧的 settled_doc_id 口径被动过")

    # --------------------------------------------------- 四、单写者
    section(SECTIONS[4])
    sites = assign_sites()
    ck.ok("给 settled_doc_id 赋值的地方只有 3 处（全在 accounting_service.py）",
          len(sites) == 3 and all(rel == ACCT_REL for rel, _ in sites),
          "实际：" + "；".join(f"{rel} {line}" for rel, line in sites))
    shapes = [line for _, line in sites]
    ck.ok("三处的形状：= s.id 两处 ＋ = None 一处",
          shapes.count("b.settled_doc_id = s.id") == 2 and shapes.count("b.settled_doc_id = None") == 1,
          "实际：" + "；".join(shapes))

    # --------------------------------------------------- 五、注释与行为一致
    section(SECTIONS[5])
    ck.ok("接口层注释仍然写着「真的发生」（这条注释现在是真的）",
          "真的发生" in api_raw, "注释又被改回与行为相反的那句")
    ck.ok("接口层注释说清了「锁」落在 settled_doc_id 上",
          "settled_doc_id" in api_raw and "作废" in api_raw,
          "注释没说怎么锁、怎么解锁 ⇒ 下一个人还会以为建单不落任何痕迹")
    ck.ok("create 的注释写清状态仍是 OPEN",
          "状态**仍是 OPEN**" in acct_raw or "状态仍是 OPEN" in acct_raw,
          "不写清楚的话，读代码的人会把「上锁」误当成「已结算」")
    ck.ok("cancel 的注释写清「锁在建单当刻就打上了」",
          "在建单当刻就打上了" in acct_raw, "解锁那一侧的注释又只剩 SETTLED 的旧口径")
    sb_doc = re.search(r'"""([\s\S]*?)"""', sb) if sb else None
    ck.ok("settleable_bills 的 docstring 写清「待结 ≠ 没人锁」",
          "「待结」≠「没人锁」" in acct_raw, "取数口径的说明丢了")

    # --------------------------------------------------- 六、回归用例
    section(SECTIONS[6])
    ktest = read(KTEST)
    names = re.findall(r"^def (test_[^\s(]+)\(", ktest, re.M)
    ck.ok(f"回归用例文件在，用例 {len(names)} 条（下界 {MIN_CASES}）",
          bool(ktest) and len(names) >= MIN_CASES,
          f"{KTEST.relative_to(ROOT)} 不在或只有 {len(names)} 条用例")
    lost = [n for n in CASE_NAMES if n not in names]
    ck.ok(f"七条用例逐条还在（{len(CASE_NAMES)} 条）", not lost, "丢了或改名了：" + "、".join(lost))

    # --------------------------------------------------- 七、文档与登记
    section(SECTIONS[7])
    change = read(CHANGE)
    need = ["# BUG-0024 ·", "## ① 六问", "## ② Must Change / Must Not Change", "## ③ Boundary",
            "R4-BOUNDARY-JUSTIFICATION：", "## ④ Behavior Contract", "## ⑤ Data Contract",
            "## ⑥ CHG 专章", "## ⑦ 测试", "## ⑧ 证据", "## ⑨ 关闭"]
    lack = [s for s in need if s not in change]
    ck.ok("变更单 docs/changes/BUG-0024.md 在，且九节齐全", bool(change) and not lack,
          "缺：" + "、".join(lack) if lack else "文件不在")
    rows = [ln for ln in read(README).splitlines() if "BUG-0024" in ln]
    ck.ok("登记表 docs/changes/README.md 有 BUG-0024 行（状态列带「已提交」）",
          len(rows) == 1 and "已提交" in rows[0],
          f"命中 {len(rows)} 行")
    led = [ln for ln in read(LEDGER).splitlines() if ln.startswith("| TB-08 ")]
    ck.ok("台账 docs/TEST_BUG_LEDGER.md 的 TB-08 行标着「已修复」",
          len(led) == 1 and "已修复" in led[0],
          f"命中 {len(led)} 行" + (f"：{led[0][:120]}" if led else ""))
    claim_text = read(CLAIM)
    ck.ok(f"认领簿写了「核心改动：{ACCT_REL}」（动了核心区必须声明）＋ 认得是本单 BUG-0024",
          f"核心改动：{ACCT_REL}" in claim_text and "BUG-0024" in claim_text,
          "AI_WORK_CLAIM.md 里没有这一行 —— _check_core_freeze.py 会红")
    ck.ok("反向验证脚本在（每条注入都要让本判据红）", RVERIFY.is_file(),
          f"{RVERIFY.relative_to(ROOT)} 不在")

    return 1 if ck.report("TB-08 结算单锁定与报错分因") else 0


if __name__ == "__main__":
    raise SystemExit(main())
