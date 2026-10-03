"""红线：**整单退货之后，被冲掉的那行自动账必须仍然可见**（BUG-0001，2026-10-03 真机抓到）。

## 由来（用户要求「真人手法跑一遍业务、把问题找出来」，跑到退货时抓到的）

订单 #SO202610036508883054（速冻水饺 ×3 袋 ¥85.5）**整单退货**之后，派单员
「账本管理 → 订单账（今天）」显示 **合计 −85.5 / 共 1 笔流水** —— 而库里明明是**两行**
（`ledgers` id=878 的 +85.5 与 id=879 的 −85.5，`order_id=551`）。
看账的人会以为这一天倒亏 85.5 元；「货主账」「批发商账」同错。

根因一句话：`source=ORDER` 的自动行只认「订单已送达」，而整单退货会把订单转成 `RETURNED`
⇒ 原行被**读口径**吃掉；红冲行（`source != ORDER`）只要求「订单没进回收站」⇒ 它留着。
一减一加变成**只剩一减**。部分退货的单仍是 `DELIVERED`，两行本来就都在 ——
所以这个不对称**只在整单退货**时出现，平时看不出来。

## 这一块会怎么悄悄坏掉（都不是假想）

| 写坏的方式 | 表现（都不报错、不崩） |
|---|---|
| 把 `source=ORDER` 的可见状态改回「只认已送达」 | 整单退货的单账上只剩一减，账面凭空少一笔营收 |
| 顺手给红冲行也加上状态要求 | 两行一起消失，同一张单在账上**整个不见**（更安静） |
| 把营业额那边也放行 `RETURNED` | 两个口径又分家：账本相抵为 0、营业额还在算这一单 |
| 只改代码、不改口径说明 | 下一个人照着说明把它改回去（说明才是他读的那一份） |
| 回归用例被削弱成「至少有 1 行」 | 缺陷复现时用例照样绿 |
| 把那一行账物理删掉 | 隔离区就恢复不了了（本项目从不删账本行） |

## 判据（全部从源码 / 用例 / 登记簿算，⛔ 不手写「要检查的文件清单」）

1. **口径本体**：`visible_ledger_clause()` 里 `source=ORDER` 的可见状态把 `RETURNED` 也算进来；
   红冲行那一支仍然只受「没进回收站」约束（⛔ 不许给它加状态要求）。
2. **口径说明**：模块文档里写明「已送达或已退货」「为什么已退货也要算」，
   并明确「这一条不是把营业额也改宽」（引 `loader.py::load_delivered`）。
3. **回归用例**：三条用例都在，且钉的是「两行都可见 + 相抵为 0 + 账户回到退货前」，
   还有部分退货的边界；走的是真实端点（申请 + 办理），不复用服务层内部调用。
4. **别处不许被改宽**：营业额侧（`loader.py`）**不许**出现 `RETURNED`；
   账本列表 / 汇总 / 导出三处仍然只从 `visible_ledger_select()` 出发。
5. **一行都不许删**：判据文件自己不写库、不 delete（它只负责「读的时候不算进来」）。
6. **留痕**：`docs/changes/BUG-0001.md` 登记在册并点了本文件；反向验证脚本在。
7. 反空转：断言条数低于下限就报错，而不是安静地什么都不查。

⚠️ 注入式反向验证（改坏 → 本脚本必须红）：`_tools/qa/_reverse_verify_ledger_scope_full_return.py`。

用法：python _tools/qa/_check_ledger_scope_full_return.py
"""
from __future__ import annotations

import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
SCOPE = ROOT / "backend/app/services/ledger_scope.py"
LOADER = ROOT / "backend/app/services/reports/loader.py"
TEST = ROOT / "backend/tests/test_ledger_scope_full_return.py"
DOC = ROOT / "docs/changes/BUG-0001.md"
README = ROOT / "docs/changes/README.md"
REVERSE = Path(__file__).resolve().parent / "_reverse_verify_ledger_scope_full_return.py"

#: 账本可见性的**三个**消费点（少接一处就会出现「同一个月的钱两个数」）。
CONSUMERS = [
    ROOT / "backend/app/api/v1/ledger.py",
    ROOT / "backend/app/api/v1/reports.py",
    ROOT / "backend/app/services/ledger_export.py",
]

#: 兜底下限 —— 低于这些数就先喊「被掏空了」，⛔ 不许安静地少查。
MIN_SCOPE_LINES = 60
MIN_TEST_LINES = 120
MIN_ITEMS = 24


def read(p: Path) -> str:
    if not p.is_file():
        raise SystemExit("找不到文件：" + str(p) + "（改名 / 移动了？本脚本的断言要跟着改）")
    return p.read_text(encoding="utf-8", errors="replace")


class Checker:
    def __init__(self) -> None:
        self.passes = 0
        self.fails: list[str] = []

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
        else:
            self.fails.append(label + (" —— " + detail if detail else ""))

    def present(self, label: str, text: str, needle: str) -> None:
        # ⚠️ 一律用**整串包含**判，不用正则：这里要判的就是几处**逐字**的源码，
        #    正则里的反斜杠还会与转义打架（写歪一个就变成恒绿的假判据）。
        self.ok(label, needle in text, "没找到：" + needle)

    def absent(self, label: str, text: str, needle: str) -> None:
        self.ok(label, needle not in text, "不该出现却出现了：" + needle)


def main() -> int:
    c = Checker()
    scope = read(SCOPE)
    loader = read(LOADER)
    test = read(TEST)
    doc = read(DOC)
    readme = read(README)

    # ---- ① 口径本体 ----
    c.present("自动账本行的可见状态把「已退货」也算进来（本缺陷的修复本体）", scope,
              "Order.status.in_((OrderStatus.DELIVERED, OrderStatus.RETURNED))")
    c.absent("⛔ source=ORDER 不许再退回「只认已送达」（整单退货会只剩一减）", scope,
             "Order.status == OrderStatus.DELIVERED")
    c.present("红冲行（source != ORDER）仍然只受「没进回收站」约束", scope,
              "Ledger.source != LedgerSource.ORDER,")
    c.present("约束关系是「没进回收站」与「来源」两层 or", scope, "~exists(order_row.where(Order.deleted_at.isnot(None)))")
    c.present("可见性判据只有一个入口", scope, "def visible_ledger_clause()")
    c.present("列表 / 聚合的统一入口还在", scope, "def visible_ledger_select()")
    scope_lines = scope.count("\n") + 1
    c.ok("账本口径这一份没被掏空（行数下限 " + str(MIN_SCOPE_LINES) + "）",
         scope_lines >= MIN_SCOPE_LINES, "只有 " + str(scope_lines) + " 行")

    # ---- ② 口径说明（下一个人读的是说明，不是代码） ----
    c.present("模块口径首条写明「已送达或已退货」", scope, "订单**已送达或已退货**且")
    c.present("说明里有那一节（为什么已退货也要算）", scope, "也要算（BUG-0001")
    c.present("说明里点了 loader 只收已送达（营业额没被一起改宽）", scope, "loader.py::load_delivered")
    c.present("说明里写死了「这一条不是把营业额也改宽」", scope, "把营业额也改宽")
    c.present("说明里留了真机证据（¥85.5 那一笔）", scope, "85.5")
    c.present("说明里留了库里那两行的 id（证据可回溯）", scope, "id=878")
    c.present("函数 docstring 也同步了（改一处漏一处＝两份口径）", scope, "已送达或已退货**且**没进回收站");

    # ---- ③ 回归用例 ----
    tlines = test.count("\n") + 1
    c.ok("回归用例文件没被掏空（行数下限 " + str(MIN_TEST_LINES) + "）",
         tlines >= MIN_TEST_LINES, "只有 " + str(tlines) + " 行")
    c.present("用例一：整单退货后读口径仍能看到两行", test,
              "def test_full_return_keeps_the_reversed_row_visible(")
    c.present("用例二：账本净额 = 营业额（两边一起退回原样）", test,
              "def test_ledger_net_equals_turnover_after_a_full_return(")
    c.present("用例三：部分退货的边界（改前改后必须逐位一致）", test,
              "def test_partial_return_keeps_counting_the_remaining_rows(")
    c.present("用例要求整单退货后**两行都可见**", test, "assert len(visible) == 2, (")
    c.present("用例要求原行与红冲行相抵为 0", test, "Decimal(\"0\"), (")
    c.present("用例要求账户口径回到退货之前", test, "整单退货之后账户总额没有回到退货之前")
    c.present("用例钉了部分退货的边界（剩下的 1 件 × 500）", test, "Decimal(\"1000\")")
    c.present("用例钉了部分退货订单仍是已送达", test, "OrderStatus.DELIVERED")
    c.present("用例走的是真实端点（申请 + 办理），不直接调服务层", test, "/api/v1/return-requests")
    c.present("用例取订单行走真实端点", test, "/api/v1/order-products?order_id=")
    c.present("用例复用兄弟用例的造数助手（不抄第二份）", test,
              "from tests.test_audit_round20_ledger_scope import")

    # ---- ④ 别处不许被改宽 / 一行都不许删 ----
    c.absent("⛔ 营业额口径没有被一起改宽（loader 里不许出现 RETURNED）", loader, "OrderStatus.RETURNED")
    c.present("loader 里那一句仍然是 == DELIVERED", loader, "Order.status == OrderStatus.DELIVERED,")
    for p in CONSUMERS:
        c.present("账本口径的消费点仍从唯一入口出发：" + p.name, read(p), "visible_ledger_select()")
    c.absent("⛔ 判据文件自己不写库（它只负责「读的时候不算进来」）", scope, "db.commit(")
    c.absent("⛔ 一行账本都不许在这里被删", scope, "delete(")

    # ---- ⑤ 留痕与指针 ----
    c.present("BUG-0001 登记在登记簿里（表要与目录对得上）", readme, "](BUG-0001.md)")
    c.present("BUG-0001.md 点了本判据（改这一块之前先看它）", doc,
              "_check_ledger_scope_full_return.py")
    c.present("BUG-0001.md 的「不许改」点了部分退货那一条", doc, "部分退货")
    c.ok("注入式反向验证脚本在（改坏 → 本判据必须红）", REVERSE.is_file(), str(REVERSE))

    total = c.passes + len(c.fails)
    if total < MIN_ITEMS:
        print("❌ 只跑了 " + str(total) + " 项（<" + str(MIN_ITEMS) + "）—— 判据在空转，停。")
        return 1
    if c.fails:
        print("❌ 整单退货账本口径红线不通过（" + str(c.passes) + "/" + str(total) + "）：")
        for f in c.fails:
            print("   [FAIL] " + f)
        return 1
    print("✅ 全部 " + str(c.passes) + " 项通过：整单退货之后账本两行都还在（相抵为 0），"
          "营业额那边一个字都没放宽，三个消费点仍然同源。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
