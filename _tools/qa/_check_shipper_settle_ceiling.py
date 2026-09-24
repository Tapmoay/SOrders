"""红线：**批发商那本账「同一笔钱不许被记两遍」**（2026-09-23 第 16 轮）。

## 为什么单为这一块写一条红线

钱的口径在本项目一共五处，前四处都治过"同一笔钱被记两遍"：

| 处 | 防重算的写法 |
| --- | --- |
| 订单应收/已收（`order_money`） | 一份实现，四个消费点共用 |
| 司机应付（`driver_pay`） | 一份实现，五个消费点共用 |
| 公司收款（`accounting_service.create_receipt`） | `money_map(..., lock=True)` |
| 退货红冲（`order_return`） | 可退数量与金额都过判据 |
| **批发商自记账（`shipper_settle`）** | ⛔ 原来一条都没有 —— 本判据钉住本轮补的两道防线 |

这一块坏掉的方式**全部不报错**：多收的钱在"下游那本账"上，行上的"还可核销"被夹成 0、
汇总的"待收"变成负数 —— 两个数都不崩，用户要到自己对账时才发现。

## 判据分五层（缺一层都等于没防住）
① 服务层：上限只有一处实现、算它的时候**能**加锁读、超了有唯一的判据形态；
② 端点层：**先锁订单行再算钱**、写完再算一次、恢复也要过上限、撤销/恢复用条件 UPDATE；
③ 不变量：核销仍然**一个字节都不写** `orders.paid` / `cash_flows` / `ledgers`（这一域存在的全部理由）
   + 权限门没被顺手放开（只有货主、只有批发商能写）；
④ 判据不是空转：单测文件存在且那几条断言还在（含"恢复必须被拒"那条，它原来是反的）；
⑤ 跨接口：库级不变式 + 并发探针里有这一档。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_pagination_wiring import strip_comments  # noqa: E402

BACKEND = ROOT / "backend/app"
API = BACKEND / "api/v1/shipper_ledger.py"
SVC = BACKEND / "services/shipper_settle.py"
SCHEMA = BACKEND / "schemas/shipper_settlement.py"
TEST = ROOT / "backend/tests/test_shipper_settle_ceiling.py"
OLD_TEST = ROOT / "backend/tests/test_shipper_settlement.py"
INVARIANTS = ROOT / "_tools/fuzz/_fuzz_invariants.py"
PROBE = ROOT / "_tools/perf/_concurrency_probe.py"
LOCATOR = ROOT / "docs/PROJECT_MAP/08_CODE_LOCATOR.md"
FINDINGS = ROOT / "_archive/audit/FINDINGS.md"


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的断言要跟着改）")
    return p.read_text(encoding="utf-8")


def func_body(src: str, name: str) -> str:
    """取一个函数的函数体（到下一个顶层 `def ` / `@router.` 为止）。"""
    m = re.search(rf"^def {re.escape(name)}\(", src, re.M)
    if not m:
        return ""
    rest = src[m.end():]
    nxt = re.search(r"^(?:def |@router\.)", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def after(text: str, needle: str) -> str:
    """`needle` 之后的全部文本（取不到就给空串 → 依赖它的断言自己会红）。"""
    i = text.find(needle)
    return text[i + len(needle):] if i >= 0 else ""


class Checker:
    def __init__(self) -> None:
        self.passes = 0
        self.fails: list[str] = []

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
        else:
            self.fails.append(label + (f" —— {detail}" if detail else ""))

    def present(self, label: str, text: str, pattern: str) -> None:
        self.ok(label, re.search(pattern, text) is not None, f"没找到 /{pattern}/")

    def absent(self, label: str, text: str, pattern: str) -> None:
        self.ok(label, re.search(pattern, text) is None, f"不该出现 /{pattern}/ 却出现了")


def main() -> int:
    c = Checker()

    svc = read(SVC)
    svc_nc = strip_comments(svc)
    api = read(API)
    api_nc = strip_comments(api)
    create = strip_comments(func_body(api, "create_settlement"))
    restore = strip_comments(func_body(api, "restore_settlement"))
    delete = strip_comments(func_body(api, "delete_settlement"))
    settled_map = strip_comments(func_body(svc, "settled_line_map"))
    breaches = strip_comments(func_body(svc, "over_settled_lines"))
    test = read(TEST)
    old_test = read(OLD_TEST)

    # ---- ① 服务层：上限只有一处实现，且算它的时候能加锁读 ----
    c.ok("取到三个关键函数的函数体（取不到下面几条就是空转）",
         len(create) > 800 and len(restore) > 600 and len(breaches) > 400)
    c.present("「还可核销」仍然是**一处**实现（行应收 − 已核销，夹到 0）",
              svc_nc, r"def line_remaining\(op: OrderProduct, settled: Decimal\)[\s\S]{0,300}?line_receivable\(op\)")
    c.present("算「已核销多少」的那条查询**能**加锁读（`lock=True`）",
              settled_map, r"if lock:\s*\n\s*stmt = stmt\.with_for_update\(\)")
    c.present("加锁读的注释写明了为什么（REPEATABLE READ 下普通 SELECT 读的是快照）",
              svc, r"REPEATABLE READ")
    c.present("默认那一档**不加锁**（读列表不该锁库）", settled_map, r"lock: bool = False")
    c.present("超额的判据**只有一处**（`over_settled_lines`）",
              svc_nc, r"def over_settled_lines\(")
    c.present("判据是「记的 > 该收的」（相等 = 收齐，不算超）",
              breaches, r"if got > recv:")
    c.present("超额带着**超出多少**（`over`）与**本次想记多少**（`wanted`）一起回（话术要用）",
              svc_nc, r"over=q2\(got - recv\), wanted=want")
    c.present("恢复路径靠 `extra` 把「即将记进来的那几笔」算进去",
              breaches, r"add = extra or \{\}")

    # ---- ② 端点层：先锁订单行 → 算钱 → 写 → 再算一次 ----
    c.present("核销**先锁订单行**再算钱（同一张单的并发核销在这里排队）",
              create, r"_locked_order\(db, _own_order\(db, current, body\.order_id\)\)")
    o_lock, o_read = create.find("_locked_order("), create.find("lines_of_order(")
    c.ok("顺序是**先锁行、后算「还可核销」**（反过来的话锁了也没用）",
         0 <= o_lock < o_read, f"锁在 {o_lock}、算钱在 {o_read}")
    c.present("核销时那次「已核销多少」读的是**加锁**的那一档",
              create, r"lines_of_order\(db, order, lock=True\)")
    c.present("写完 `flush` 之后**再算一次**（防线②，不依赖行锁）",
              create, r"db\.flush\(\)\s*\n\s*breaches = over_settled_lines\(db, order, lock=True\)")
    c.present("真超了就**整笔回滚**（不许留下半笔）", create, r"breaches:\s*\n\s*db\.rollback\(\)")
    c.present("恢复**先重算上限**（把这一笔当作即将记进来）",
              restore, r"over_settled_lines\(db, order, extra=extra, lock=True\)")
    c.present("恢复放行之后**还要再看一眼**（并发下另一个恢复请求也走这条）",
              after(restore, "db.flush()"), r"over_settled_lines\(db, order, lock=True\)")
    c.present("恢复也**先锁订单行**", restore, r"order = _locked_order\(db, order\)")
    c.present("恢复被拒时给的是「先撤掉后面又记的那一笔」这种能照着做的话",
              api, r"先撤掉撤销之后又记的那一笔")

    # 条件 UPDATE：撤销 / 恢复都必须"判据与写入在同一个语句里"
    for name, body, flag in (("撤销", delete, "False"), ("恢复", restore, "True")):
        c.present(f"{name}用的是**条件 UPDATE**（不是读到没有 → 再写）",
                  body, r"update\(ShipperSettlement\)")
        c.present(f"{name}的条件里有 `is_deleted == {flag}`（判据与写入同一语句）",
                  body, rf"ShipperSettlement\.is_deleted\.is_\(\s*{flag}\s*\)")
        c.present(f"{name}检查 `rowcount != 1` 才拒绝（连点两下只算一次）",
                  body, r"rowcount\s*\n?\s*if changed != 1:|if changed != 1:")
    c.present("撤销被拒时是 400 + 中文（不是 500、不是静默成功）",
              delete, r'status_code=400, detail="这笔核销已经撤掉了')

    # ---- ③ 不变量：两本账不许串 + 权限门没被顺手放开 ----
    c.absent("⛔ 核销**仍然不写** `orders.paid`（那是派单员向他收钱的标记）",
             api_nc + svc_nc, r"\.paid\s*=(?!=)")
    c.absent("⛔ 核销**仍然不写**现金流水（写进去就是公司账上凭空多一笔已收）",
             api_nc + svc_nc, r"CashFlow\(|INSERT INTO cash_flows")
    c.absent("⛔ 核销**仍然不写**账本（写它会让「他欠公司多少」当场变少）",
             api_nc + svc_nc, r"Ledger\(|sync_ledger")
    c.ok("五个端点（统计/列表/核销/撤销/恢复）**全都**只给货主（角色门没被放开）",
         len(re.findall(r"current: ShipperOnly", api_nc)) >= 5,
         f"只找到 {len(re.findall(r'current: ShipperOnly', api_nc))} 处")
    c.ok("三个写端点仍然各自过 `_require_member`（普通货主不该写这本账）",
         len(re.findall(r"_require_member\(current\)", api_nc)) >= 3,
         f"只找到 {len(re.findall(r'_require_member\(current\)', api_nc))} 处")
    c.present("拒绝的话术里带金额（`money_text` 去尾零，与全项目同一条显示口径）",
              api, r"money_text\(b\.receivable\)")

    # ---- ④ 判据不是空转：测试还在、而且方向是对的 ----
    for fn in (
        "test_恢复一笔位置已被占用的核销必须被拒",
        "test_还有余量时恢复照旧可以",
        "test_恢复之后不许超过上限_逐行也要判",
        "test_撤销与恢复连点两下只算一次",
        "test_算还可核销这一步必须能加锁读",
    ):
        c.present(f"单测钉着「{fn}」", test, rf"def {fn}\(")
    # ⚠️ ①③两条各有一句 `assert back.status_code == 400`，所以判据必须**圈在①的函数体里**
    #    （在整份文件上搜，把①那句改回 200 时它会被③那句顶上 → 假绿）。
    t1 = strip_comments(func_body(test, "test_恢复一笔位置已被占用的核销必须被拒"))
    c.ok("取到①的函数体（取不到下面两条就是空转）", len(t1) > 600)
    c.present("①那条断言恢复**必须 400**（不是「能通就行」）", t1, r"assert back\.status_code == 400")
    c.present("①那条说明白了原因（同一笔钱被记两遍：已收 160、应收 80）",
              t1, r"已收 160、应收 80")
    c.present("②那条断言**还有余量时必须照旧成功**（防误伤，不是一律拒绝）",
              test, r"assert back\.status_code == 200")
    c.present("断言「待收」不许为负（超收在汇总上的样子）",
              test, r'assert s\["unreceived"\] == "0\.00"')
    c.present("机制那条看的是 statement 的加锁参数（不看方言，SQLite 会把 FOR UPDATE 丢掉）",
              test, r'getattr\(s, "_for_update_arg", None\) is not None')
    c.present("撤销/恢复的机制那条看的是**真的发出去的 UPDATE**（不看源码形状）",
              test, r"isinstance\(s, Update\)")
    c.present("旧测试里那条「恢复成功」的断言已经改成「必须被拒」",
              old_test, r"assert back\.status_code == 400, \"同一笔钱不许被记两遍：恢复必须重算上限\"")
    c.present("旧测试里补上了「先撤掉后记的那笔再恢复」这条正路（不然只是把功能堵死）",
              old_test, r"先撤掉\"again\"那笔")
    c.absent("⛔ 旧测试里不许再出现「两笔都在 = 已收齐」那种说法（这正是被治掉的缺陷）",
             old_test, r"两笔都在")

    # ---- ⑤ 跨接口：库级不变式 + 并发探针 ----
    c.present("库级不变式里有这一条（Σ 未撤销核销行 ≤ 行金额）",
              read(INVARIANTS), r"某一行的核销合计超过了它的货值")
    c.present("并发探针里有 `settle` 这一档（CASES 清单里 —— 判据必须盯住**清单那一行**："
              "只搜「settle」的话，`args.only == \"settle\"` 那句会把它顶上，摘掉清单也照样绿）",
              read(PROBE), r'CASES: list\[str\] = \[[^\]]*"settle"')
    c.present("探针的判据是「库内的 Σ 不超上限」（不是只看 HTTP 状态码）",
              read(PROBE), r"if settle_over:")
    c.present("探针把「两笔同时成功」算成缺陷",
              read(PROBE), r"并发核销：这一单被记了")

    # ---- ⑥ 文档指针 ----
    c.present("定位表里指到了本判据（改这一块的人找得到）",
              read(LOCATOR), r"_check_shipper_settle_ceiling\.py")
    # ⚠️ 2026-09-25（CI 第一次真跑时发现）：_archive/ **不进 git**（本机底稿目录），
    #    干净检出里没有这份 FINDINGS —— 缺底稿时**响亮地跳过**（不假装通过，也不让常闸在 CI 上必红）。
    if FINDINGS.exists():
        c.present("FINDINGS 里有「退货把应收冲小之后已收大于应收」那一条待拍板",
                  read(FINDINGS), r"退货把应收冲小")
    else:
        print("  [SKIP] FINDINGS 那条：本机没有 _archive/audit/FINDINGS.md（不进 git）—— 只有带底稿的机器能判")
    c.present("服务层文件头写明了「两道防线分别在哪儿」",
              svc, r"两道防线分别在")

    total = c.passes + len(c.fails)
    if total < 35:
        print(f"❌ 只跑了 {total} 项（<35）—— 判据在空转，停。")
        return 1
    if c.fails:
        print(f"❌ 批发商核销「不许被记两遍」红线不通过（{c.passes}/{total}）：")
        for f in c.fails:
            print("   [FAIL] " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过：核销的上限只有一处、算它时能加锁读、写完还会再算一次，"
          f"恢复也要过上限，撤销/恢复是条件 UPDATE；两本账依然谁也不写谁，"
          f"并发探针与库级不变式都盯着它。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
