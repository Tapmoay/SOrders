"""反向验证：把「货主 / 批发商收支统计」那条红线逐条弄坏，看它**真的会红**。

## 为什么这块必须反向验证
这一块坏掉的方式**全部不报错、不崩**：
· 客户端又把"这一页"加起来当合计 → 单子多的那一段**合计偏小**（而卡片上写着"这一段"）；
· 统计里带上 limit → 同一个 bug 挪到服务端；
· 窗口换成下单日（不过时区换算）→「8-31 下单、9-1 送达」的单在列表里、不在合计里；
· 按人筛只按名字 → 两个同名货主并成一个（"他的欠款翻倍、另一个人的不见了"）；
· 服务端的回退顺序换了 → 与客户端分组键对不上，"人员行写着某人、合计却是全部"；
· 金额不过 `q2` → 同一张卡上出现 `0` 与 `0.00` 两种写法；
· 不给 AI 读能力 → 模型答不了"我这个月还欠多少 / 我该收多少"。

用法：python _tools/qa/_reverse_verify_shipper_ledger_stats.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_shipper_ledger_stats.py"

BACKEND = ROOT / "backend/app"
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
API = BACKEND / "api/v1/shipper_ledger.py"
SCHEMA = BACKEND / "schemas/shipper_settlement.py"
TEST = ROOT / "backend/tests/test_shipper_ledger_summary.py"
VM = ANDROID / "ui/shipper/ShipperLedgerViewModel.kt"
SCREEN = ANDROID / "ui/shipper/ShipperLedgerScreen.kt"
GROUPING = ANDROID / "ui/shipper/ShipperLedgerGrouping.kt"
APIS = ANDROID / "data/remote/api/Apis.kt"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
LOCATOR = ROOT / "docs/PROJECT_MAP/08_CODE_LOCATOR.md"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "① 统计里带上 limit（把截断挪到服务端）",
        API,
        "    # ⚠️ 这里**不设 limit**：统计要的是\"这一段全部\"，截断正是这张卡要修掉的那个 bug。\n    orders = list(db.scalars(stmt).unique().all())",
        "    orders = list(db.scalars(stmt).limit(300).unique().all())",
        "统计**不许**带 limit",
    ),
    (
        "② 不要时区换算（当地 00:00~08:00 送达的单掉出窗口）",
        API,
        "            lo, hi = business_range_utc(df.date(), dt.date())\n            stmt = stmt.where(Order.delivered_at.isnot(None))\n            stmt = stmt.where(Order.delivered_at >= lo).where(Order.delivered_at < hi)\n    stmt = _customer_filter(stmt, customer_name, customer_phone)",
        "            lo, hi = df, dt\n            stmt = stmt.where(Order.delivered_at.isnot(None))\n            stmt = stmt.where(Order.delivered_at >= lo).where(Order.delivered_at < hi)\n    stmt = _customer_filter(stmt, customer_name, customer_phone)",
        "窗口按**送达日**且过了时区换算",
    ),
    (
        "③ 未送达的单也进统计（把 `delivered_at` 非空那道门去掉）",
        API,
        "            stmt = stmt.where(Order.delivered_at.isnot(None))\n            stmt = stmt.where(Order.delivered_at >= lo).where(Order.delivered_at < hi)\n    stmt = _customer_filter(stmt, customer_name, customer_phone)",
        "            stmt = stmt.where(Order.delivered_at >= lo).where(Order.delivered_at < hi)\n    stmt = _customer_filter(stmt, customer_name, customer_phone)",
        "窗口外/未送达的单被排除",
    ),
    (
        "④ 回收站里的单还算进统计",
        API,
        "        .where(Order.deleted_at.is_(None))",
        "        .where(Order.deleted_at.is_not(None))",
        "软删的单不算",
    ),
    (
        "⑤ 统计可读别人的单（去掉自己的作用域）",
        API,
        "        .where(Order.shipper_id == current.id)",
        "        .where(Order.shipper_id.isnot(None))",
        "只算**自己的**单",
    ),
    (
        "⑥ 「已付」改成自己减一遍（不用 order_money 的净已收）",
        API,
        "        paid += m.net_collected",
        "        paid += m.settled",
        "「已付」取净已收",
    ),
    (
        "⑦ 下游「应收」自己写一套公式（不走 line_receivable）",
        API,
        "            receivable += sum((line_receivable(op) for op in o.order_products), ZERO_D)",
        "            receivable += sum(((op.unit_price or ZERO_D) * Decimal(op.quantity or 0) for op in o.order_products), ZERO_D)",
        "下游侧「应收」走 `line_receivable`",
    ),
    (
        "⑧ 「已收」把已撤销的核销也算进去",
        API,
        "                .where(ShipperSettlement.is_deleted.is_(False))",
        "                .where(ShipperSettlement.shipper_id == current.id)",
        "下游侧「已收」只数**未撤销**的核销",
    ),
    (
        "⑨ 按人筛只按名字（两个同名货主并成一个）",
        API,
        "    return stmt.where(_customer_name_expr() == want_name).where(_customer_phone_expr() == want_phone)",
        "    return stmt.where(_customer_name_expr() == want_name)",
        "服务端**同时**按电话筛",
    ),
    (
        "⑩ 服务端的归属回退换成「下单人优先」（与客户端分组键对不上）",
        API,
        '        func.nullif(func.trim(func.coalesce(Order.contact_dongjia_name, "")), ""),\n        func.trim(func.coalesce(Order.contact_boss_name, "")),',
        '        func.nullif(func.trim(func.coalesce(Order.contact_boss_name, "")), ""),\n        func.trim(func.coalesce(Order.contact_dongjia_name, "")),',
        "回退顺序：收货人 → 下单人 → 空",
    ),
    (
        "⑪ 「未指定货主」那一档的字符串换了字（按人筛就废了）",
        API,
        'UNSET_CUSTOMER = "未指定货主"',
        'UNSET_CUSTOMER = "未指定"',
        "「未指定货主」那一档与服务端同一个字符串",
    ),
    (
        "⑫ 金额不过 q2（同一张卡上出现 `0` 与 `0.00`）",
        API,
        "    receivable = q2(receivable)\n    received = q2(received)",
        "    receivable = Decimal(receivable)\n    received = Decimal(received)",
        "三个金额都过 q2",
    ),
    (
        "⑬ 统计端点顺手写一次库（只读端点不该写任何东西）",
        API,
        "    money = money_map(db, orders)",
        "    db.commit()\n    money = money_map(db, orders)",
        "统计端点**不写**任何东西",
    ),
    (
        "⑭ 出参里那句不含运费的说明没了（下一个人顺手把运费加上）",
        SCHEMA,
        "    #: ⚠️ **不含运费** —— `orders.freight_fee` 是**公司付给司机**的钱，不进他与公司之间的账。",
        "    #: （口径说明见端点）",
        "出参里写明了「我该付的是货款、不含运费」",
    ),
    (
        "⑮ 客户端那份求和长回来（`ledgerTotals`）",
        GROUPING,
        " * ⛔ 别再往这个文件里加\"把一页数据加起来的合计函数\"—— 要合计就加端点。",
        " */\nfun ledgerTotals(orders: List<OrderDto>): Long = orders.size.toLong()\n/*",
        "客户端那份求和（`ledgerTotals` / `LedgerTotals`）已经删干净",
    ),
    (
        "⑯ 卡片不再读服务端那份（回到本地求和的老路）",
        SCREEN,
        "    val s = vm.summary",
        "    val s = vm.summaryLocalTotals",
        "卡片读的是服务端那份",
    ),
    (
        "⑰ 统计不再跟着选中的人走（人员行写着某人、合计却是全部）",
        VM,
        "                    customerName = summaryCustomerName(),",
        "                    customerName = null,",
        "统计跟着**选中的那个货主**走",
    ),
    (
        "⑱ 名字与电话没有成对传（半个键会筛错人）",
        VM,
        "                    customerPhone = summaryCustomerPhone(),",
        "                    customerPhone = null,",
        "名字与电话成对传",
    ),
    (
        "⑲ Android 侧那条读封装没了（模型选中了也会 404）",
        APIS,
        '    @GET("shipper-ledger/summary")',
        '    @GET("shipper-ledger/summary-x")',
        "Android 侧有 Retrofit 封装",
    ),
    (
        "⑳ 回归测试被削弱（截断那条不查了）",
        TEST,
        "def test_统计不受列表截断影响(client, token_shipper, token_dispatcher, users):",
        "def _disabled_test_统计不受列表截断影响(client, token_shipper, token_dispatcher, users):",
        "测试钉了「统计不受列表截断影响」",
    ),
    (
        "㉑ 设计规范里那条规矩被删（下一个人不知道「合计必须服务端算」这条界线）",
        DESIGN,
        "  判据 `_tools/qa/_check_shipper_ledger_stats.py`（含反向验证）",
        "  （判据脚本名待补）",
        "设计规范里写了这一条规矩",
    ),
    (
        "㉒ 定位表里那一条被删（改这一块的人找不到判据）",
        LOCATOR,
        "红线 `_tools/qa/_check_shipper_ledger_stats.py` + 反向验证 `_reverse_verify_shipper_ledger_stats.py`。",
        "（判据待补）",
        "定位表里指到了它",
    ),
    (
        "㉓ 换人之后不再重取统计（真机抓到过：标题变了、数字还是全部那份）",
        VM,
        "    fun selectCustomer(key: String?) {\n        selectedCustomerKey = if (key != null && key == selectedCustomerKey) null else key\n        load()\n    }",
        "    fun selectCustomer(key: String?) {\n        selectedCustomerKey = if (key != null && key == selectedCustomerKey) null else key\n    }",
        "换人之后**真的会重取**",
    ),
    (
        "㉔ 清掉选中的人之后不再重取",
        VM,
        "    fun clearCustomer() {\n        selectedCustomerKey = null\n        load()\n    }",
        "    fun clearCustomer() {\n        selectedCustomerKey = null\n    }",
        "清掉选中的人之后也要重取",
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> bytes:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    out = data.encode("utf-8")
    p.write_bytes(out)
    return out



def restore_src(p: Path, text: str, crlf: bool) -> None:
    # 还原**当场核对**（R3-07b）：写回后**重新读回来逐字节比**，对不上就非零退出。
    # ⛔ 「写了还原」不是证明；重新读回来的字节 == 刚写出去的字节 才是（L2 要的就是这一句）。
    wrote = write_src(p, text, crlf)
    if p.read_bytes() != wrote:
        print('⛔ 还原后与快照不一致（注入污染了源码树）：' + str(p))
        raise SystemExit(2)

def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def verdict(expect: str) -> tuple[bool, str]:
    code, out = run_check()
    fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
    hit = code != 0 and any(expect in ln for ln in fails)
    return hit, f"实际红 {len(fails)} 条" + ("" if hit else f"：{[f.strip()[:70] for f in fails[:2]]}")


def main() -> int:
    bad = 0
    code, out = run_check()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时这条红线没过\n{out[-1200:]}")
        return 1
    print("✅ 前提：源码完好时这条红线是绿的")

    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print(f"  [SKIP] {label} —— 原文出现 {src.count(old)} 次，无法唯一替换")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            hit, detail = verdict(expect)
        finally:
            restore_src(path, src, crlf)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    code, out = run_check()
    ok = code == 0
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + 1
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立（红线对它们不敏感）")
        return 1
    print(f"✅ {total}/{total} 全部成立：每条注入都让红线点出了那一条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
