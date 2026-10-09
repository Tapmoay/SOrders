"""红线：账本行的「合计」不许与「数量 × 单价」打架（2026-10-10 测试台账 TB-10 / BUG-0025）。

### 这条是怎么来的

测试会话 2026-10-10 03:03 CST 在副本库上复现（证据 `_tmp/test_round3/evidence_TB10_ledger_total_escape.txt`）：

    手工记账建的行 quantity=3 / unit_price=20.00（total 自动 60.0000）
    → PATCH /api/v1/ledger/entries/{id} {"total": 288.00} → 200
    → 库里三个数并存（数量×单价 = 60.0000，合计 = 288.0000）
    → GET /api/v1/ledger/accounts 按 total 累加：Shipper 桶 7259.9000 → 7547.9000

用户唯一能走到这条路的是 AI：`android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteLedgerHandlers.kt:130-133`
的 `new_amount` → `Change("合计金额", …, "total", …)`，只放 total（`:161` 还提示用户「可以改：合计金额、数量、单价…」）。
病灶在 `backend/app/api/v1/ledger.py` 的 `update_entry`：原来写的是
`if "total" in raw and raw["total"] is not None: row.total = raw["total"]` —— 显式给了就照收，不看它与 数量×单价 的关系。

### 为什么必须有机器的判据

同一行会同时进三处：货主账户/欠款按 `total` 累加、账本列表与导出按这一行显示、
`sync_order_product_from_ledger` 还拿它回写订单商品行。两个答案并存时**没有任何一处报错**，
人眼在几百行账里也看不出「60 与 288 哪一个是这行的真相」。所以只有机器能钉住两件事：
①「合计」全仓只有一个算法（创建与修改都调它）；②显式给的值与 数量×单价 不符时必须 400。
判据被写坏的方式也很朴素：有人把校验摘掉、把老算法抄回第二个入口、把 `source=ORDER`
（订单行的金额权威在订单侧，本来就可以 ≠ 数量×单价）一起收紧、或者把「只改备注」也拖进重算。

R4-BOUNDARY-JUSTIFICATION: 账本行的金额是 **Core Fact（钱）**，不是能下放给 Extension 的策略 ——
「一行的合计等于什么」决定了货主账户与欠款（规范 §二十六 的 L3 语义：钱 / 账本 / 历史事实）。
这次**没有**新增边界：不引入容差、不引入 `allow_total_mismatch` 之类的逃逸字段，
只把"显式给 total 就照收"改成"必须与 数量×单价 一致，不一致就 400 并把两个数都报出来"——
判据钉的是**既有不变量的收口**，不是一条新策略。

### 反向破坏用例（每条都必须让本判据变红）

    python -X utf8 _tools/finance/_reverse_verify_ledger_total_consistency.py

逐条把下面的锚点弄坏（摘掉校验、抄回老算法、收紧 ORDER 分支、把备注改动也拖进重算……），
每条都必须让本判据红；末尾逐字节还原并读回校验。

### 静默空转保护

文件认不全（`MIN_FILES`）、代码剥注释后太短（`MIN_BODY`）、单测用例数少于 `MIN_CASES`
都先报红："检查在空转"比"没有检查"更糟。

用法：
    python -X utf8 _tools/finance/_check_ledger_total_consistency.py
    python -X utf8 _tools/qa/_check_all.py --only ledger_total_consistency
    python -X utf8 _tools/finance/_check_ledger_total_consistency.py --list
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
LEDGER = BACKEND / "app/api/v1/ledger.py"
SCHEMA = BACKEND / "app/schemas/ledger.py"
TEST_FILE = BACKEND / "tests/test_ledger_total_consistency.py"
CHANGE = ROOT / "docs/changes/BUG-0025.md"
README = ROOT / "docs/changes/README.md"
LEDGER_DOC = ROOT / "docs/TEST_BUG_LEDGER.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = HERE / "_reverse_verify_ledger_total_consistency.py"

#: 反空转下界：低于这些数说明"判据认不出目标了"，先报红，⛔ 不许安静地少查。
MIN_FILES = 4
MIN_BODY = 200
MIN_CASES = 6

SECTIONS = [
    "零、现场（防静默空转）",
    "一、只有一个算法（resolve_line_total）",
    "二、创建路径（POST）走同一处",
    "三、修改路径（PATCH）走同一处",
    "四、已送达闸没被碰坏",
    "五、钱的下界与契约没被放宽",
    "六、单测（改前必须红的那些）",
    "七、文档与登记（变更单 / 登记表 / 台账 / 认领簿 / 反验）",
]

CASE_NAMES = [
    "test_只把合计改成与数量单价不符的值会被拒",
    "test_同时给出数量与单价就改得动合计",
    "test_只改数量或单价时合计跟着重算",
    "test_只改备注绝不动钱",
    "test_手工记账建行时合计也要与数量单价对得上",
    "test_订单来的行仍按订单行金额记账",
]


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def py_code(src: str) -> str:
    """剥掉三引号块与整行注释：判据只锚**代码**，不许被说明文字骗过去。"""
    src = re.sub(r'"""' + "[\\s\\S]*?" + '"""', "", src)
    src = re.sub(r"'''[\\s\\S]*?'''", "", src)
    return re.sub(r"^[ \t]*#.*$", "", src, flags=re.M)


def py_func(src: str, name: str) -> str:
    m = re.search(r"^def " + re.escape(name) + r"\(", src, re.M)
    if not m:
        return ""
    rest = src[m.start():]
    nxt = re.search(r"^(?:def |class |@)", rest[1:], re.M)
    return rest[: nxt.start() + 1] if nxt else rest


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
    if refuse_if_injecting("_check_ledger_total_consistency.py"):
        return 1
    if "--list" in sys.argv:
        for s in SECTIONS:
            print(s)
        return 0

    ck = Checker()
    raw_ledger = read(LEDGER)
    raw_schema = read(SCHEMA)
    raw_test = read(TEST_FILE)
    raw_change = read(CHANGE)
    raw_readme = read(README)
    raw_doc = read(LEDGER_DOC)
    raw_claim = read(CLAIM)

    section(SECTIONS[0])
    files = {
        "ledger": raw_ledger,
        "schema": raw_schema,
        "test": raw_test,
        "change": raw_change,
    }
    ck.ok(f"认得出这一块的 {len(files)} 个文件（少了就先报错，别安静地跳过）",
          all(files.values()) and len(files) >= MIN_FILES,
          "空文件：" + ", ".join(k for k, v in files.items() if not v))
    code = py_code(raw_ledger)
    schema_code = py_code(raw_schema)
    body = py_func(code, "resolve_line_total")
    create = py_func(code, "create_entry")
    update = py_func(code, "update_entry")
    ck.ok(f"剥掉注释后正文还有 {len(code)} 字符（>= {MIN_BODY}），四个函数体都切得出来",
          len(code) >= MIN_BODY and bool(body) and bool(create) and bool(update),
          f"code={len(code)} body={len(body)} create={len(create)} update={len(update)}")

    section(SECTIONS[1])
    ck.ok("「合计」的算法只有一处定义",
          len(re.findall(r"^def resolve_line_total\(", code, re.M)) == 1,
          "定义 " + str(len(re.findall(r"^def resolve_line_total\(", code, re.M))) + " 处")
    ck.ok("签名逐字（source / quantity / unit_price / given_total）",
          "def resolve_line_total(" in code and "given_total: Decimal | None," in body,
          "签名或参数名变了")
    ck.ok("算出来的值就是 单价 × 数量",
          "computed = unit_price * quantity" in body, "没找到 computed = unit_price * quantity")
    ck.ok("订单来的行以订单行金额为准（这一支没被收紧）",
          "if source == LedgerSource.ORDER:" in body
          and "return given_total if given_total is not None else computed" in body,
          "ORDER 分支不见了或改写了")
    ck.ok("对得上就按算出来的算",
          "if given_total is None or given_total == computed:" in body and "return computed" in body,
          "相等那一支不见了")
    ck.ok("对不上就 400（不是悄悄改写，也不是 500）",
          "status_code=status.HTTP_400_BAD_REQUEST" in body, "没有 400")
    ck.ok("文案点明了这一行的等式「合计 = 数量 × 单价」",
          "账本行的「合计」必须等于 数量 × 单价" in body, "文案没写清等式")
    ck.ok("文案把**两个数**都报出来（算出来的 + 收到的，各自点名）",
          re.search(r"= \{_money\(computed\)\}，与你给的 合计 \{_money\(given_total\)\} 不一致", body) is not None,
          "文案没把「算出来的」和「你给的」两个数各自点名摆出来（用户没法自己改对）")
    ck.ok("文案给了能照着做的改法（改成乘积相等的数量/单价）",
          "请同时把数量或单价改成乘积等于它的值" in body, "没给改法")
    ck.ok("文案还给了「记一整笔金额」的写法（没有把能力消灭掉）",
          "例如 数量 1、单价" in body, "没给整笔金额的等价写法")
    ck.ok("⛔ 老算法不许再长回来（创建入口那份）",
          "total = body.unit_price * body.quantity" not in code,
          "老算法又出现了：total = body.unit_price * body.quantity")
    ck.ok("⛔ 老算法不许再长回来（修改入口那份）",
          "row.total = row.unit_price * row.quantity" not in code,
          "老算法又出现了：row.total = row.unit_price * row.quantity")
    ck.ok("⛔ 「显式给了 total 就照收」的形状不许再出现",
          not re.search(r'if "total" in raw and raw\["total"\] is not None:\s*\n\s+row\.total = raw\["total"\]', code),
          "老写法又回来了")

    ck.ok("出口只有两个（ORDER 一次 + 相等/没给一次），没有第三个绕过校验的出口",
          len(re.findall(r"^\s+return ", body, re.M)) == 2,
          "函数体里的 return 有 " + str(len(re.findall(r"^\s+return ", body, re.M))) + " 处")
    ck.ok("⛔ 合计不许从请求里直接搬（两个入口都只能走那一处）",
          not re.search(r'^\s*(?:row\.)?total = (?:body\.total|raw\["total"\])', code, re.M),
          "又出现了把请求里的 total 直接当合计的赋值")

    section(SECTIONS[2])
    ck.ok("记一笔：显式给的合计先进 given_total（0 与空都算「没给」）",
          'given_total = None if (body.total is None or body.total == Decimal("0")) else body.total' in create,
          "create_entry 的取数变了")
    ck.ok("记一笔：合计只由那一处算",
          "total = resolve_line_total(body.source, body.quantity, body.unit_price, given_total)" in create,
          "create_entry 没调 resolve_line_total")
    ck.ok("记一笔：只调一次（不许两处算法）",
          create.count("resolve_line_total(") == 1,
          "调用 " + str(create.count("resolve_line_total(")) + " 次")
    ck.ok("记一笔：来源闸（手工记账只能 MANUAL）还在它前面",
          create.find("手工记账只能记为「手动」来源") != -1
          and create.find("手工记账只能记为「手动」来源") < create.find("resolve_line_total("),
          "来源校验被挪到算法之后了")

    section(SECTIONS[3])
    ck.ok("改一行：显式给的合计先进 given_total",
          'given_total = raw["total"] if ("total" in raw and raw["total"] is not None) else None' in update,
          "update_entry 的取数变了")
    ck.ok("改一行：合计只由那一处算（在 if 之内，缩进就是判据）",
          bool(re.search(r'if given_total is not None or "unit_price" in raw or "quantity" in raw:\s*\n\s+row\.total = resolve_line_total\(row\.source, row\.quantity, row\.unit_price, given_total\)', update)),
          "重算那一行不在闸里（缩进/条件被改）")
    ck.ok("改一行：只调一次（不许两处算法）",
          update.count("resolve_line_total(") == 1,
          "调用 " + str(update.count("resolve_line_total(")) + " 次")
    ck.ok("改一行：不进重算就不会动钱（三个数一个都没给时连赋值都不发生）",
          update.count("row.total = ") == 1, "row.total 被赋值了多次")

    section(SECTIONS[4])
    ck.ok("已送达闸还在（函数没被删）",
          "def _reject_if_order_closed(" in code, "_reject_if_order_closed 不见了")
    ck.ok("改一行时那道闸还拦在改钱之前",
          '_reject_if_order_closed(db, row, wants_detail=wants_detail, what="改这一行的商品与金额")' in update,
          "update_entry 里的闸不见了")
    ck.ok("删一行时那道闸也还在",
          len(re.findall(r"_reject_if_order_closed\(", code)) >= 3,
          "调用点少于 3 处（1 定义 + 改 + 删）")
    ck.ok("闸判的还是订单状态那套（LINE_EDITABLE_STATUSES 同源）",
          "_reject_if_order_closed" in code and "LINE_EDITABLE_STATUSES" in py_func(code, "_reject_if_order_closed"),
          "闸的判据变了")
    ck.ok("已送达那句文案还在（用户看得懂的那句）",
          "已送达" in raw_ledger and "账上这笔钱已经定了" in raw_ledger, "闸的文案不见了")

    section(SECTIONS[5])
    ck.ok("下界仍由 MoneyInput 兜底（两个模型都还继承它）",
          "class LedgerCreate(MoneyInput):" in schema_code and "class LedgerUpdate(MoneyInput):" in schema_code,
          "MoneyInput 继承被拿掉了")
    ck.ok("单价/合计的下界与可空性没变",
          'unit_price: Decimal = Field(default=Decimal("0"), ge=0)' in schema_code
          and "total: Decimal | None = Field(default=None, ge=0)" in schema_code
          and "quantity: int = Field(default=1, ge=1)" in schema_code,
          "schema 的字段定义被改动了")
    ck.ok("⛔ 过期注释（「要改得先拍板」）已经改掉",
          "要改得先拍板" not in raw_schema, "注释还停在旧口径上")
    ck.ok("新注释把新口径写清楚了（并指向唯一算法）",
          "必须等于" in raw_schema and "resolve_line_total" in raw_schema,
          "注释没写清新口径")

    section(SECTIONS[6])
    ck.ok(f"单测用例数 >= {MIN_CASES}（{len(CASE_NAMES)} 条都要在）",
          len([n for n in CASE_NAMES if n in raw_test]) == len(CASE_NAMES),
          "缺：" + ", ".join(n for n in CASE_NAMES if n not in raw_test))
    ck.ok("单测里有「不一致 → 400」的断言（不是只看 200）",
          raw_test.count("400") >= 2, "400 断言太少")
    ck.ok("单测把账户口径也验了（钱真的没多出来）",
          "_account_total(" in raw_test and "ledger/accounts" in raw_test,
          "没有账户侧的断言")
    ck.ok("单测钉住了 ORDER 行不受这条约束",
          "订单" in raw_test and "source" in raw_test, "没有 ORDER 场景")

    section(SECTIONS[7])
    for part in ["## ① 六问", "## ② Must Change / Must Not Change", "## ③ Boundary",
                 "## ④ Behavior Contract", "## ⑤ Data Contract", "## ⑥ CHG 专章",
                 "## ⑦ 测试", "## ⑧ 证据", "## ⑨ 关闭"]:
        ck.ok("变更单里有 " + part, part in raw_change, "没找到 " + part)
    rows = [ln for ln in raw_readme.splitlines() if "BUG-0025" in ln]
    ck.ok("登记表里恰好一行 BUG-0025", len(rows) == 1, "命中 " + str(len(rows)) + " 行")
    ck.ok("登记表那一行写的是「已提交 …」",
          bool(rows) and "已提交" in rows[0], "状态列还没回填")
    trows = [ln for ln in raw_doc.splitlines() if ln.startswith("| TB-10 ")]
    ck.ok("台账里那一行（| TB-10 ）已改成「已修复」",
          len(trows) == 1 and "已修复" in trows[0],
          "命中 " + str(len(trows)) + " 行" + ("，状态还没改" if trows else ""))
    ck.ok("认领簿里有这一单（BUG-0025）", "BUG-0025" in raw_claim, "AI_WORK_CLAIM 里找不到 BUG-0025")
    ck.ok("反验脚本在（" + REVERSE.name + "）", REVERSE.is_file(), "反验脚本不存在")

    return 1 if ck.report("TB-10 账本行的合计与 数量×单价 的一致性") else 0


if __name__ == "__main__":
    raise SystemExit(main())
