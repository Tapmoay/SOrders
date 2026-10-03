# -*- coding: utf-8 -*-
"""结算单的金额与明细必须**同源**（2026-10-03 BUG-0007）—— 机器判据。

## 这条是怎么来的

三端真机 E2E 走查（`docs/E2E_WALKTHROUGH_REPORT_20261003.md`）之后用户拍板：

> 「你说结账单的数字和明细对不上，这是非常大的问题啊…金钱对不上账会出现问题的，
>  这个必须要修的，必须查明原因，看是不是代码写错了，还是哪个逻辑链路出现了问题」

根因不是「某个数字算错了」，而是**同一个月有两套取数口径**：
`create_settlement` 按「司机 + 月 + 类型 + OPEN + 订单未软删」取明细（其中
`or_(DriverBill.order_id.is_(None), ...)` 让孤儿账单也算进金额），`confirm_settlement`
却按 `order_ids` 重取 —— 孤儿没有单号，永远取不回来 ⇒ `amount` 比明细合计多出孤儿那几笔
⇒ 确认接口 400：`{"detail":"结算单金额 970.00 与明细合计 940.00 不一致，请核对"}`。
真机上的表现是**那张结算单永远确认不了、司机这笔钱结不掉**（只能改库）。

## 为什么必须有机器的判据

修法是「取数只有一处 + 建单当刻锁定 + 恒等式 `amount == 明细合计 + adjustment`」，
这三句都是**结构性**的：谁把 `confirm` 改回按 `order_ids` 重取、谁把 `adjustment`
从校验里拿掉、谁给 `cancel` 的解锁重新挂上门闩，页面上都看不出来 ——
只有下一次月末结算才会以「钱对不上 / 结不掉」的形式炸出来。所以这里逐条钉住写法。

R4-BOUNDARY-JUSTIFICATION: **为什么代码边界解决不了这件事。**
（⛔ 标记里必须是**ASCII 冒号**：`_check_r3_constraints.py::probe_checker_budget` 认的是
`R3-BOUNDARY-JUSTIFICATION:` / `R4-BOUNDARY-JUSTIFICATION:` 这两个**逐字**字符串 —— 本文件第一版
写的是全角「：」，于是全量静检在提交之后当场翻红：R3-D17「新增的检查器没写为什么边界解决不了」。）

「建单与确认取的是同一批明细」不是一个文件的属性 —— `create_settlement` 与 `confirm_settlement`
各自看都合法、各自都有用例；**只有把「建单当刻锁定的行」与「确认 / 付款时点名取的行」放在同一批
数据上对，才知道它们是不是同一批**。类型标注、路由校验、页面提示都挡不住「悄悄改回按月重取」
这一手：它不报错、不抛异常，只会在月末以「钱对不上 / 结不掉」的形式炸出来。

**反向破坏用例**：`_tools/qa/_reverse_verify_settlement_single_source.py` 的 17 条注入（把 `recorded`
打回空 = 改回按月重取、`bill_ids` 不落库、恒等式去掉 `adjustment`、作废门闩挂回去、迁移少搬一列、
自愈门闩改 `if False`、用例改名掉数、登记表 / 文档改 ID……）逐条实测报红，跑完把被碰过的文件
逐字节还原。

**静默空转保护**：本判据只读源码，锚点少一个就当场报红 —— 「取到了 X 的正文」那一组要求正文
长度 > 200 字符（`py_func` 切段失败 = 红），逐条判词又都钉在**具体那一行写法**上；**不做**
「找不到就跳过」的软处理，`--list` 会把全部条目打出来，红的那一条直接给关键词。
不碰数据库、不发请求、不改任何文件；它管的是「这条钱的口径有没有被改回去」。

用法：
    python _tools/qa/_check_settlement_single_source.py
    python _tools/qa/_check_settlement_single_source.py --list
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))

from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
ACCT = BACKEND / "app/services/accounting_service.py"
MODEL = BACKEND / "app/models/driver_settlement.py"
SCHEMA = BACKEND / "app/schemas/accounting_v2.py"
API = BACKEND / "app/api/v1/driver_settlements.py"
BOOT = BACKEND / "app/core/schema_bootstrap.py"
MIG = BACKEND / "app/migrations/017_settlement_bill_ids.py"
KTEST = BACKEND / "tests/test_settlement_single_source.py"
DOC = ROOT / "docs/changes/BUG-0007.md"
REGISTRY = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"

#: 断言「至少扫到这么多后端 .py」—— 防「一个文件都没扫到也算过」。
MIN_FILES = 200
#: 回归用例条数下界（改动前实测 8 条；加用例可以，删用例必须同时改这里）。
MIN_CASES = 8


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def py_code(src: str) -> str:
    """剥 Python 的散文（三引号块 + 整行 `#` 注释）：判据只许锚在代码上。

    ⚠️ 教训（BUG-0006 判据的第一条假阳性）：函数体里的一句注释「并且**不碰**
    `session_revoked_reason`」把纯子串判断喂饱了。
    """
    out = re.sub(r'"""(?:.|\n)*?"""', "", src)
    out = re.sub(r"'''(?:.|\n)*?'''", "", out)
    return "\n".join(ln for ln in out.splitlines() if not ln.strip().startswith("#"))


def py_func(src: str, name: str) -> str:
    """取一个**顶层**函数的正文：从 `def name(` 到下一个顶格的 def/class/@ 或文件末。"""
    i = src.find(f"def {name}(")
    if i < 0:
        return ""
    m = re.search(r"(?m)^(?=def |class |@)", src[i + 1 :])
    return src[i : i + 1 + (m.start() if m else len(src) - i - 1)]


class Checker:
    def __init__(self) -> None:
        self.fails = 0
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print(f"  [OK]   {label}")
        else:
            self.fails += 1
            print(f"  [FAIL] {label}" + (f"\n         → {detail}" if detail else ""))

    def report(self, title: str) -> int:
        print()
        print(f"===== {title} =====")
        print(f"  通过 {self.passes} 项，失败 {self.fails} 项")
        return 1 if self.fails else 0


def section(title: str) -> None:
    print()
    print(f"-- {title} --")


def main() -> int:
    if refuse_if_injecting("结算单金额与明细同源的检查"):
        return 1

    c = Checker()
    acct_raw = read(ACCT)
    acct = py_code(acct_raw)
    create = py_func(acct, "create_settlement")
    confirm = py_func(acct, "confirm_settlement")
    pay = py_func(acct, "pay_settlement")
    cancel = py_func(acct, "cancel_settlement")
    shared = py_func(acct, "settleable_bills")
    model = py_code(read(MODEL))
    schema = py_code(read(SCHEMA))
    api = py_code(read(API))
    boot = py_code(read(BOOT))
    mig = py_code(read(MIG))
    ktest = py_code(read(KTEST))
    doc = read(DOC)
    registry = read(REGISTRY)
    claim = read(CLAIM)

    py_files = [p for p in BACKEND.rglob("*.py") if "migrations" not in p.parts or True]
    section("零、现场")
    c.ok(
        f"扫到 {len(py_files)} 个后端 .py（下界 {MIN_FILES}）",
        len(py_files) >= MIN_FILES,
        "一个文件都没扫到的时候，下面每一条都会「看起来」通过",
    )
    c.ok("accounting_service.py 读到了", bool(acct.strip()))
    for name, body in (
        ("create_settlement", create),
        ("confirm_settlement", confirm),
        ("pay_settlement", pay),
        ("cancel_settlement", cancel),
        ("settleable_bills", shared),
    ):
        c.ok(f"取到了 {name} 的正文", len(body) > 200, f"只有 {len(body)} 字符，切段失败了")

    section("一、取数只有一处（后端）")
    c.ok(
        "settleable_bills 是唯一取数实现（签名带 driver_id / settle_type / month）",
        "def settleable_bills(" in acct
        and "driver_id: int" in shared
        and "settle_type: DriverBillType" in shared
        and "month: str" in shared,
    )
    c.ok(
        "软删口径留在 settleable_bills 里（outerjoin orders + deleted_at is None）",
        ".outerjoin(Order, Order.id == DriverBill.order_id)" in shared
        and "or_(DriverBill.order_id.is_(None), Order.deleted_at.is_(None))," in shared,
        "撤掉它 = 已软删订单的应付又被结算单收走（第十七轮审计那条）",
    )
    c.ok("建单调它取数（create_settlement → settleable_bills）", "bills = settleable_bills(" in create)
    c.ok(
        "确认核对也调它（confirm_settlement → settleable_bills）",
        "for b in settleable_bills(" in confirm,
        "两套取数口径正是 970/940 的病根：确认必须走同一个函数",
    )
    c.ok(
        "create_settlement 自己不再手写取数条件（函数体里没有 select(DriverBill)）",
        "select(DriverBill)" not in create,
    )
    c.ok(
        "建单当刻把「覆盖哪几行」写下来（bill_ids = [b.id for b in bills]）",
        "bill_ids = [b.id for b in bills]" in create,
        "含 order_id 为空的历史孤儿账单 —— 它们没有单号可列",
    )
    c.ok("构造结算单时把 bill_ids 传下去", re.search(r"^\s*bill_ids=bill_ids,\s*$", create, re.M) is not None)
    c.ok(
        "确认优先认 bill_ids（recorded = [int(x) for x in (s.bill_ids or [])] + if recorded:）",
        "recorded = [int(x) for x in (s.bill_ids or [])]" in confirm and "if recorded:" in confirm,
    )
    c.ok(
        "锁定的明细少了就明确报错（「已经不在了」+「请作废后重新结算」）",
        "已经不在了" in confirm and "请作废后重新结算" in confirm and "gone" in confirm,
        "明细被删 / 被别的结算单占用时不许拿旧金额硬确认",
    )
    c.ok(
        "老草稿没有 bill_ids 时仍留了老路（按 order_ids / 按月两条分支）",
        "elif s.settle_type == DriverBillType.PIECE and s.order_ids:" in confirm,
    )
    c.ok(
        "手工改额记差额（adjustment = Decimal(body.amount) - amount）",
        "adjustment = Decimal(body.amount) - amount" in create,
        "原来只改 amount，于是「金额必须等于明细合计」那道校验必然把改过额的单判死",
    )
    c.ok(
        "确认的恒等式：amount == 明细合计 + adjustment",
        "if Decimal(s.amount) != locked_total + adjustment:" in confirm,
    )
    c.ok(
        "付款的恒等式同源（live_total + Decimal(s.adjustment or Decimal(\"0\"))）",
        "if Decimal(s.amount) != live_total + Decimal(s.adjustment or Decimal(\"0\")):" in pay,
    )
    c.ok(
        "报错里点出手工调整那一笔（tail = f\"（本单另有手工调整 {adjustment:+}）\"）",
        "本单另有手工调整" in confirm and "adjustment:+}" in confirm,
        "否则没人看得懂差在哪（金额与明细都摆在那儿，差额却看不到）",
    )
    c.ok(
        "作废解锁按 settled_doc_id 认（不看 settle_type / order_ids）",
        "DriverBill.settled_doc_id == s.id," in cancel
        and "DriverBill.status == DriverBillStatus.SETTLED," in cancel
        and "s.order_ids" not in cancel,
        "旧门闩（settle_type == PIECE and order_ids）让孤儿单/月薪单的「作废单 + 明细已锁」永远解不开",
    )
    c.ok(
        "三处 CAS 占位都还在（confirm / pay / cancel 各一句 claimed.rowcount != 1）",
        sum(1 for b in (confirm, pay, cancel) if "if claimed.rowcount != 1:" in b) == 3,
        "并发确认/作废/付款靠它挡住，别在这次改动里被顺手削弱",
    )

    section("二、数据契约（模型 / 出参 / 迁移 / 自愈）")
    c.ok(
        "模型两张脸：bill_ids 可空 JSON + adjustment NOT NULL DEFAULT 0",
        "bill_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)" in model
        and "adjustment: Mapped[Decimal] = mapped_column(" in model
        and "Numeric(12, 2), default=Decimal(\"0\"), server_default=\"0\"" in model,
    )
    c.ok(
        "出参带上它们（bill_ids: list | None = None / adjustment: Decimal = Decimal(\"0\")）",
        "bill_ids: list | None = None" in schema and "adjustment: Decimal = Decimal(\"0\")" in schema,
    )
    c.ok(
        "列表出参也带上（\"bill_ids\": r.bill_ids, / \"adjustment\": r.adjustment,）",
        '"bill_ids": r.bill_ids,' in api and '"adjustment": r.adjustment,' in api,
    )
    c.ok(
        "建单与改单两处手工构造的响应都补齐（bill_ids=s.bill_ids, adjustment=s.adjustment,）",
        len(re.findall(r"bill_ids=s\.bill_ids, adjustment=s\.adjustment,", api)) >= 2,
    )
    c.ok(
        "正式搬迁走迁移 017（VERSION = 17 / NAME = settlement_bill_ids）",
        "VERSION = 17" in mig and 'NAME = "settlement_bill_ids"' in mig,
    )
    c.ok(
        "迁移里两列都定义了（bill_ids / adjustment）",
        '"bill_ids": "bill_ids JSON"' in mig
        and '"adjustment": "adjustment DECIMAL(12,2) NOT NULL DEFAULT 0"' in mig,
    )
    c.ok(
        "迁移可重跑（逐列判存在）+ 不回填老数据（没有 UPDATE / INSERT INTO driver_settlements）",
        "if name in have:" in mig
        and "UPDATE driver_settlements" not in mig
        and "INSERT INTO driver_settlements" not in mig,
    )
    c.ok(
        "老库兜底副本在 schema_bootstrap（门闩与 ALTER 两条一起认）",
        'if "driver_settlements" in insp.get_table_names():' in boot
        and "ADD COLUMN bill_ids JSON" in boot
        and "ADD COLUMN adjustment " in boot,
        "只判 ALTER 那一行会被「门闩被废掉但语句还在」骗过去（BUG-0006 的漏网教训）",
    )

    section("三、回归测试钉住了行为")
    cases = re.findall(r"(?m)^def (test_\w+)\(", ktest)
    c.ok(f"回归用例 {len(cases)} 条（下界 {MIN_CASES}）", len(cases) >= MIN_CASES, "、".join(cases))
    c.ok(
        "用例点到了六件事：孤儿 / 抢走 / 新增明细 / 手工改额 / 老草稿 / 作废解锁",
        all(
            k in " ".join(cases)
            for k in ("孤儿", "抢走", "新增的明细", "手工改额", "老草稿", "作废解锁")
        ),
        "、".join(cases),
    )
    c.ok(
        "用例断言了那两句关键文案（已经不在了 / 手工调整）",
        "已经不在了" in ktest and "手工调整" in ktest,
    )
    c.ok(
        "用例断言了「新增的明细不许被这张单收走」",
        "DriverBillStatus.OPEN" in ktest and "SETTLED" in ktest,
    )
    c.ok(
        "用例用的是过去月份（结算单按月取数，撞月就串味）",
        "2019-" in ktest and "2031-" not in ktest,
        "未来月份会被 validate_month 挡成 422（上界是本月）",
    )

    section("四、文档与登记")
    c.ok("改动文档在（docs/changes/BUG-0007.md）", "BUG-0007" in doc and "结算单" in doc, "文件不存在或缺关键词")
    c.ok(
        "文档写清了根因与修法（bill_ids + adjustment）",
        "bill_ids" in doc and "adjustment" in doc and "同源" in doc,
    )
    c.ok("改动登记表里有 BUG-0007 行", "| `BUG-0007` |" in registry, "docs/changes/README.md")
    c.ok("认领簿里有 BUG-0007 的块", "BUG-0007" in claim)

    if "--list" in sys.argv:
        print()
        print("  == 它到底在查什么 ==")
        print("  · 后端：`settleable_bills` 是唯一取数实现，建单/确认都调它，create 不再手写取数条件；")
        print("  · 建单当刻锁定 bill_ids，确认优先认它，明细少了就明确报错（不再按月重取）；")
        print("  · 恒等式 amount == 明细合计 + adjustment 在确认与付款两处都成立；")
        print("  · 作废解锁按 settled_doc_id 认（不再挂 settle_type/order_ids 门闩）；")
        print("  · 模型/出参/迁移 017/自愈副本 四处数据契约齐全（老库升得上、老草稿走得通）；")
        print("  · 回归测试 ≥8 条且点到六件事；改动文档 + 登记表 + 认领簿都在。")

    return c.report("结算单金额与明细同源（BUG-0007）")


if __name__ == "__main__":
    sys.exit(main())
