"""红线：**货主 / 批发商「我的账本」顶上那段收支统计**（2026-09-22 用户第 ⑥ 条要求）。

## 用户原话与拍板
> 「**账本的那个统计**，**货主和批发商也做一下**」；拍板口径：**各自「我的账本」里补一段
> 他自己的收支统计**（⛔ 不是把派单员那份「收支」放开给他们看）。

## 这一块最容易悄悄坏掉的六件事（每条都有判据）
1. **合计又变成"客户端把这一页加起来"**：这一页的订单列表是**带 limit 的一页**，
   单子一多，客户端加出来的合计就**偏小**，而卡片上写着"这一段"。
   期① 的审计里那个"客户端求和少算 62%"是同一个形状（同一个数两个答案，两边都不报错）。
   ⛔ 判据：客户端**不许**再把订单列表求和当合计（`ledgerTotals` 那一类函数不许回来），
   而且卡片读的必须是服务端那个 `summary`。
2. **两个方向被写串**：下游那本账（批发商自己记的核销）**一个字节都不许写**公司那本
   （`orders.paid` / `cash_flows` / `ledgers`）。核销之后"我该付的"必须一分钱不动。
3. **窗口口径走散**：统计必须与列表**同窗口**（按订单**送达日**、过 `business_range_utc` 换算），
   否则「8-31 下单、9-1 送达」的单会出现在列表里、却不在合计里。
4. **按人筛的键只有名字**：两个同名货主会被并成一个（"他的欠款翻倍、另一个人的不见了"）。
   服务端的回退必须与客户端 `customerKeyOf` **同一套**（收货人 → 下单人 → 未指定）。
5. **统计自己也带 limit**：那就等于把同一个 bug 挪到服务端。
6. **AI 那一头漏登记**：新端点是**读**能力（进读目录、被某个 App 模块认领），
   不进读目录的话模型答不了"我这个月还欠多少 / 我该收多少"。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_pagination_wiring import strip_comments  # noqa: E402

BACKEND = ROOT / "backend/app"
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
API = BACKEND / "api/v1/shipper_ledger.py"
SCHEMA = BACKEND / "schemas/shipper_settlement.py"
SETTLE_SVC = BACKEND / "services/shipper_settle.py"
MONEY_SVC = BACKEND / "services/order_money.py"
TEST = ROOT / "backend/tests/test_shipper_ledger_summary.py"
VM = ANDROID / "ui/shipper/ShipperLedgerViewModel.kt"
SCREEN = ANDROID / "ui/shipper/ShipperLedgerScreen.kt"
GROUPING = ANDROID / "ui/shipper/ShipperLedgerGrouping.kt"
APIS = ANDROID / "data/remote/api/Apis.kt"
REPO = ANDROID / "data/repo/AppRepository.kt"
READ_CATALOG = ROOT / "docs/ai/ai_read_catalog.json"
ENDPOINTS = ROOT / "docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
LOCATOR = ROOT / "docs/PROJECT_MAP/08_CODE_LOCATOR.md"
COVERAGE = ROOT / "_tools/ai/_app_feature_coverage.py"


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的断言要跟着改）")
    return p.read_text(encoding="utf-8")


def func_body(src: str, name: str) -> str:
    """取一个模块级函数的函数体（到下一个 `\\ndef ` / `\\n@router.` 为止）。

    ⚠️ 为什么必须按函数切：`shipper_ledger.py` 里有**四个**端点，其中列表那条**本来就用
       `limit`**（分页）、还**本来就会写库**（核销）。在整份文件上搜"有没有 limit / 有没有
       write_log"，红的一定是列表那几条 —— 那种假红的下场是这个检查被无视。
    """
    m = re.search(rf"^def {re.escape(name)}\(", src, re.M)
    if not m:
        return ""
    rest = src[m.end():]
    nxt = re.search(r"^(?:def |@router\.)", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


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

    api = read(API)
    api_nc = strip_comments(api)
    summary_body = strip_comments(func_body(api, "ledger_summary"))
    name_expr = strip_comments(func_body(api, "_customer_name_expr"))
    phone_expr = strip_comments(func_body(api, "_customer_phone_expr"))
    schema = read(SCHEMA)
    vm = strip_comments(read(VM))
    screen = strip_comments(read(SCREEN))
    grouping = read(GROUPING)

    # ---- ① 端点：只读、只给货主、不设 limit ----
    # ⚠️ 下面这些都**只看 `ledger_summary` 的函数体**：同一个文件里还有**四个**端点
    #    （列表那条本来就用 `limit`、核销那几条本来就会写库）。在整份文件上搜，
    #    红的一定是别人 —— 那种假红的下场是这个检查被无视。
    c.ok("取到 ledger_summary 的函数体（取不到下面几条就是空转）", len(summary_body) > 800)
    c.ok("取到两个「归属人」表达式（按人筛那几条要靠它）",
         len(name_expr) > 100 and len(phone_expr) > 100)
    c.present("新端点是 `GET /summary`", api, r'@router\.get\("/summary", response_model=ShipperLedgerSummaryOut\)')
    c.present("守卫与这本账其余端点同一个（只有货主能读）", api, r"current: ShipperOnly")
    c.absent("⛔ 统计**不许**带 limit（那就把截断挪到服务端了）", summary_body, r"\.limit\(|effective_limit")
    c.present("窗口按**送达日**且过了时区换算（与列表同一套）",
              summary_body, r"business_range_utc\(df\.date\(\), dt\.date\(\)\)")
    c.present("窗口外/未送达的单被排除（`delivered_at` 非空 + 区间）",
              summary_body, r"Order\.delivered_at\.isnot\(None\)")
    c.present("软删的单不算（进回收站的单不进统计）",
              summary_body, r"Order\.deleted_at\.is_\(None\)")
    c.present("只算**自己的**单", summary_body, r"Order\.shipper_id == current\.id")

    # ---- ② 口径复用：三个数各只有一处实现 ----
    c.present("订单侧的钱走 `order_money.money_map`（唯一实现）", summary_body, r"money_map\(db, orders\)")
    c.present("「应付」取 `receivable`（订单金额 − 已退）", summary_body, r"payable \+= m\.receivable")
    c.present("「已付」取净已收（现场收现金没有流水，只有它算得对）", summary_body, r"paid \+= m\.net_collected")
    c.present("「还欠」取 `arrears`（与订单出参同一个数）", summary_body, r"unpaid \+= m\.arrears")
    c.present("下游侧「应收」走 `line_receivable`（不另写一套公式）", summary_body, r"line_receivable\(op\)")
    c.present("下游侧「已收」只数**未撤销**的核销",
              summary_body, r"ShipperSettlement\.is_deleted\.is_\(False\)")
    c.present("「待收」= 应收 − 已收（减法只有这一处）", summary_body, r"unreceived=q2\(receivable - received\)")
    c.present("三个金额都过 q2（同一张卡上不许出现 `0` 与 `0.00` 两种写法）",
              summary_body, r"receivable = q2\(receivable\)")
    c.present("出参里写明了「我该付的是货款、不含运费」", schema, "不含运费")

    # ---- ③ 按人筛的键 = 名字 + 电话（与客户端同一套回退）----
    filter_body = strip_comments(func_body(api, "_customer_filter"))
    c.ok("取到 `_customer_filter` 的函数体（取不到下面两条就是空转）", len(filter_body) > 200)
    c.present("服务端按名字筛", filter_body, r"_customer_name_expr\(\) == want_name")
    c.present("服务端**同时**按电话筛（只按名字会把同名货主并成一个）",
              filter_body, r"_customer_phone_expr\(\) == want_phone")
    c.present("回退顺序：收货人 → 下单人 → 空",
              name_expr, r"contact_dongjia_name[\s\S]{0,200}?contact_boss_name")
    c.present("电话的回退与名字同一套（收货人 → 下单人）",
              phone_expr, r"contact_dongjia_phone[\s\S]{0,200}?contact_boss_phone")
    c.present("「未指定货主」那一档与服务端同一个字符串",
              api, r'UNSET_CUSTOMER = "未指定货主"')
    c.present("客户端有同名常量（两边差一个字，按人筛就废了）",
              grouping, r'UNSET_CUSTOMER = "未指定货主"')

    # ---- ④ 客户端：合计只许有一个来源（服务端），旧求和必须删干净 ----
    c.present("VM 里有 summary 状态（服务端那份）", vm, r"var summary by mutableStateOf<ShipperLedgerSummaryDto\?>")
    c.present("取数走仓储那一条（不是自己拼 URL）", vm, r"container\.repo\.myLedgerSummary\(")
    c.present("统计与列表**同窗口**", vm, r"myLedgerSummary\(\s*\n?\s*deliveredFrom = rangeFrom")
    c.present("统计跟着**选中的那个货主**走", vm, r"customerName = summaryCustomerName\(\)")
    # ⚠️ 真机实测抓到的 bug（2026-09-22）：换人之后卡片**标题**变了、**数字**还是全部那份
    #    —— 因为统计是服务端算的，换人不取数它不会自己变。
    # ⚠️ 判据必须**圈在函数体内**：中间那段用 `[^{}]*?`（**不许跨花括号**），
    #    否则它会一路找到紧随其后的 `clearCustomer` 里那个 `load()` 去满足自己
    #    —— 反向验证当场抓到过这个假绿（第一版写成 `[\s\S]{0,300}?` 就中招了）。
    c.present("换人之后**真的会重取**（抽屉里点一下 / 清掉都得重取）",
              vm, r"fun selectCustomer\(key: String\?\) \{[^{}]*?\bload\(\)[^{}]*?\}")
    c.present("清掉选中的人之后也要重取",
              vm, r"fun clearCustomer\(\) \{[^{}]*?\bload\(\)[^{}]*?\}")
    c.present("名字与电话成对传（半个键会筛错人）", vm, r"customerPhone = summaryCustomerPhone\(\)")
    c.ok("⛔ 客户端那份求和（`ledgerTotals` / `LedgerTotals`）已经删干净",
         "ledgerTotals" not in vm and "LedgerTotals" not in read(VM) and
         "fun ledgerTotals" not in grouping and "data class LedgerTotals" not in grouping,
         "它拿一页数据当全部 —— 列表一带 limit 合计就偏小")
    c.present("分组文件里留了一段说明：要合计就加端点", grouping, r"要合计就加端点")
    c.present("卡片读的是服务端那份（`vm.summary`）", screen, r"val s = vm\.summary\b")
    c.present("卡片画两个方向：支出·我该付的", screen, r"支出 · 我该付的")
    c.present("卡片画两个方向：收入·我该收的（只有批发商）", screen, r"收入 · 我该收的")
    c.present("普通货主那边有一句解释（他只有支出这一边）",
              screen, r"这里只有你欠公司的这一边")
    c.absent("⛔ 卡片里不许再出现客户端求和的字段（`centsToMoney(t.` 那种）",
             screen, r"totals\.")
    c.present("抽屉里「全部」那一行也用服务端的数", screen, r'formatMoney\(vm\.summary\?\.unreceived')

    # ---- ⑤ 两本账不许串：断言在服务层的唯一实现上 ----
    c.present("下游那本账的口径只有一处实现", read(SETTLE_SVC), r"行应收     = `order_money\.line_receivable")
    c.present("订单侧的钱只有一处实现", read(MONEY_SVC), r'"""一批订单的钱')
    c.absent("⛔ 统计端点**不写**任何东西（它是只读的）",
             summary_body, r"db\.add\(|db\.commit\(|write_log\(")

    # ---- ⑥ 测试钉住了那几件"不报错但会算错"的事 ----
    t = read(TEST)
    c.present("测试钉了「统计不受列表截断影响」", t, r"def test_统计不受列表截断影响")
    c.present("测试钉了「核销之后我该付的一分钱不动」", t, r"def test_批发商_收入侧是下游那本账")
    c.present("测试钉了「撤销核销统计跟着退回去」", t, r"def test_撤销核销之后统计跟着退回去")
    c.present("测试钉了「同名不同电话不许合并」", t, r"def test_按货主筛_同名不同电话不许合并")
    c.present("测试钉了「窗口按送达日」", t, r"def test_窗口按送达日")
    c.present("测试钉了「回收站里的单不算」", t, r"def test_回收站里的单不算")
    c.present("测试钉了「派单员与司机读不到」", t, r"def test_派单员与司机读不到")
    c.present("测试钉了「已付含现场收现金」", t, r"def test_已付的口径含现场收现金")

    # ---- ⑦ AI 后路 + 文档指针 ----
    c.present("读目录里有它（模型靠它选工具）", read(READ_CATALOG), r'"action": "ledger_summary"')
    c.present("读能力被 App 模块认领", read(COVERAGE), r'"我的账本"')
    c.present("端点索引里有它（文档不许过期）", read(ENDPOINTS), r"GET /api/v1/shipper-ledger/summary")
    c.present("Android 侧有 Retrofit 封装", read(APIS), r'@GET\("shipper-ledger/summary"\)')
    c.present("仓储有转出方法", read(REPO), r"suspend fun myLedgerSummary\(")
    c.ok("设计规范里写了这一条规矩（并指路本判据）",
         "货主" in read(DESIGN) and "_check_shipper_ledger_stats.py" in read(DESIGN),
         "缺一条：货主/批发商的收支统计 + 指路到本文件")
    loc = read(LOCATOR)
    c.ok("定位表里指到了它（并点名本判据）",
         "_check_shipper_ledger_stats.py" in loc,
         "改这一块的人应当能从定位表找到本文件")

    total = c.passes + len(c.fails)
    if total < 40:
        print(f"❌ 只跑了 {total} 项（<40）—— 判据在空转，停。")
        return 1
    if c.fails:
        print(f"❌ 货主/批发商收支统计红线不通过（{c.passes}/{total}）：")
        for f in c.fails:
            print("   [FAIL] " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过：统计只有**服务端**一个来源（与列表同窗口、同一个人），"
          f"两个方向各有各的口径、谁都不写谁，AI 读能力也接上了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
