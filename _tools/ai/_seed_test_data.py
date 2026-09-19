"""在**本地开发库**造一整套「近 2 个自然月 + 多人」的测试数据，用于多角度验证 AI 助手。

⚠️ 安全护栏：只对 SQLite 文件生效（读文件头校验）；非 SQLite 直接拒绝。
⚠️ 幂等：所有自己造的行都带 `SOTEST` 标记，重跑会先删干净再加（删不掉的会报错，不会留脏数据）。

### 为什么按「自然月」而不是「最近 60 天」
用户问的是「这个月哪个货主下单最多」这种**自然月**口径，按最近 N 天造数没法验证月份边界。
所以这里造的是：**上月整月 + 本月 1 号到今天**，另外再塞 8 单「上上月」的单子当**边界探针**
（它们绝不能出现在本月/上月的任何统计里）。

### 造了什么（每一项都为了一条可验证的断言）
| 数据 | 设计意图 |
|---|---|
| 30 个货主，上月/本月单量各不相同 | 排行会随区间变化；有「上月活跃本月流失」和「本月新晋」两类，专治把区间写死的 bug |
| 2 个批发商（is_member） | 区分「高级货主」价格体系 |
| 8 个司机：5 计件 + 3 工资制 | 工资制司机**不应**出现「待结运费」；计件司机应有 |
| 10 个商品，其中 3 个到红线 | 含**库存 == 阈值**（应报警）与**库存 == 阈值+1**（不应报警）两个边界 |
| 8 单在上上月 | 区间边界探针，出现在本月/上月统计里就是 bug |
| 3 单挂 `temp_shipper_name`（无账号） | 验证「临时货主」不丢单 |
| 15 单未送达（已派/待派/已接/已撤销） | 验证「已送达」口径没把这些算进去 |
| 跨天送达 + 超期送达 | 让准时率既不是 0% 也不是 100% |
| 现金收款 → cash_flows | 财务流水口径 |
| 1 张本月已付的司机结算单（**带明细与付款流水**） | 「待结运费 = 应结 - 已结」这条减法真的被算过 |

用法：
  python _seed_test_data.py            # 造数据（先清后造）
  python _seed_test_data.py --clean    # 只清理
  python _seed_test_data.py --db <路径>  # 拿另一份库试跑（验证造数本身，不动开发库）
"""
import argparse
import json
import random
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

DB = repo_root() / "backend" / "sorders.db"
TAG = "SOTEST"
RNG = random.Random(20260915)  # 固定种子：重跑结果逐行一致，便于对账

# ---------------------------------------------------------------- 数据蓝图

# (货主名, 是否批发商, 上月单量, 本月单量)
SHIPPER_PLAN: list[tuple[str, bool, int, int]] = [
    ("恒丰粮油批发", True, 12, 7),
    ("老张蔬菜行", False, 9, 6),
    ("万佳副食超市", False, 8, 5),
    ("明辉食品商行", False, 8, 4),
    ("城东水果批发", True, 7, 5),
    ("金源日用百货", False, 7, 4),
    ("广发冷冻食品", False, 5, 3),
    ("新华烟酒行", False, 5, 2),
    ("陈记干货铺", False, 4, 3),
    ("兴隆便利店", False, 4, 2),
    ("百惠超市", False, 4, 2),
    ("刘氏调料行", False, 3, 3),
    ("甘记豆制品", False, 3, 2),
    ("石记水产", False, 3, 2),
    ("宏达食品", False, 3, 2),
    ("吉顺商行", False, 3, 2),
    ("小李杂货", False, 2, 1),
    ("何氏面粉", False, 2, 1),
    ("田记酱菜", False, 2, 2),
    ("高家粮油", False, 2, 1),
    ("周记禽蛋", False, 2, 1),
    ("王家米店", False, 1, 1),
    ("郑记腌菜", False, 1, 1),
    ("沈记果蔬", False, 1, 1),
    ("老陈菜摊", False, 1, 1),
    ("康乐副食", False, 1, 2),
    # —— 专门用来打破「排名不变」的两类 ——
    ("顺发干货批发", False, 11, 0),   # 上月最活跃、本月一单没有
    ("大发糖果", False, 10, 1),      # 上月第二、本月几乎停
    ("新叶生鲜", False, 0, 9),       # 本月新客户，直接冲进本月前列
    ("优鲜配送", False, 1, 7),       # 本月放量
]

# (司机名, 车型, 计费方式, 派单权重)
DRIVER_PLAN: list[tuple[str, str, str, int]] = [
    ("王建国", "4.2米", "PIECE", 4),
    ("李永强", "4.2米", "PIECE", 3),
    ("赵德海", "6.8米", "PIECE", 3),
    ("孙志伟", "面包车", "PIECE", 2),
    ("吴国平", "9.6米", "PIECE", 1),
    ("刘长顺", "6.8米", "SALARY", 2),
    ("陈立新", "4.2米", "SALARY", 1),
    ("郑海涛", "面包车", "SALARY", 1),
]

# (商品名, 售价, 成本, 单位, 库存, 报警阈值)  —— 阈值列专门留了两个边界
PRODUCT_PLAN: list[tuple[str, str, str, str, int, int]] = [
    ("海天酱油 500ml", "48.00", "30.00", "箱", 2, 10),        # 2 <= 10  报警
    ("金龙鱼调和油 5L", "128.00", "96.00", "箱", 3, 12),      # 3 <= 12  报警
    ("娃哈哈纯净水 596ml", "36.00", "24.00", "箱", 50, 50),   # 50 == 50 报警（边界：等于也报）
    ("康师傅红烧牛肉面", "60.00", "42.00", "箱", 260, 40),    # 不报
    ("双汇火腿肠", "88.00", "62.00", "箱", 31, 30),           # 31 = 阈值+1 不报（边界：差一个不报）
    ("雪花啤酒 500ml", "72.00", "50.00", "箱", 180, 40),
    ("蒙牛纯牛奶 250ml", "96.00", "70.00", "箱", 90, 20),
    ("雕牌洗衣粉", "42.00", "28.00", "箱", 60, 15),
    ("厨邦蚝油 700g", "56.00", "38.00", "箱", 120, 25),
    ("上好佳薯片", "64.00", "45.00", "箱", 200, 30),
]

TEMP_SHIPPERS = ["散客老周", "路边老赵", "临时客户-工地"]  # 无账号，只有名字
BEIJING_OFFSET_HOURS = 8  # 库里存 UTC；东八区 09:00 派单 = 01:00 UTC


def guard() -> None:
    if not DB.exists():
        sys.exit(f"找不到 {DB}")
    with open(DB, "rb") as f:
        if f.read(16) != b"SQLite format 3\x00":
            sys.exit("拒绝执行：目标不是 SQLite 开发库")


def clean(con: sqlite3.Connection) -> dict[str, int]:
    """删掉自己造的所有行。返回每张表删了多少，便于确认没漏。

    ### 一个必须先想清楚的问题：造出来的单上，别人又建了东西怎么办
    UAT/探针脚本会在造出来的 SOTEST 单上**真的走一遍**「送达 → 结算 → 付款」，
    于是库里出现一批 `note` 不带 TAG 的结算单，它们的明细全是 SOTEST 单。
    第一版清理只按 `order_no LIKE 'SOTEST%'` 删订单，结果：
    **订单没了、账单还在、结算单变成"已付款却没有明细"**——正是本轮 ③ 那个形状
    （试跑副本上当场复现：22 条指向空号的已结账单 + 1 张 0 明细的已付结算单）。

    现在的判据是**算出来的**，不是猜的：逐条看结算单的明细，
      · 明细**全部**指向 TAG 单 → 这张结算单整个身子都压在造数数据上，连它一起删
        （连同它的付款流水，否则会留下一笔没有单据的支出）；
      · 只要有一条明细指向**非** TAG 单 → 这是掺了真实数据的结算单，**它和它用到的
        那几张单整张留下**（宁可留几张多余的测试单，也不要毁掉别人记好的账）。
    """
    cur = con.cursor()
    tagged = {
        r[0] for r in cur.execute("SELECT id FROM orders WHERE order_no LIKE ?", (f"{TAG}%",))
    }
    own_docs = {
        r[0]
        for r in cur.execute("SELECT id FROM driver_settlements WHERE note LIKE ?", (f"{TAG}%",))
    }
    foreign_docs = {
        r[0]
        for r in cur.execute(
            "SELECT DISTINCT settled_doc_id FROM driver_bills WHERE settled_doc_id IS NOT NULL"
        )
    } - own_docs
    adopted: list[int] = []     # 整个身子都在造数数据上 → 一起删
    keep_docs: list[int] = []   # 掺了真实数据 → 连它用到的单一起留下
    for did in sorted(foreign_docs):
        used = [
            r[0]
            for r in cur.execute(
                "SELECT order_id FROM driver_bills WHERE settled_doc_id = ?", (did,)
            )
            if r[0] is not None
        ]
        (adopted if used and all(o in tagged for o in used) else keep_docs).append(did)

    protected = {
        r[0]
        for did in keep_docs
        for r in cur.execute(
            "SELECT order_id FROM driver_bills WHERE settled_doc_id = ? AND order_id IS NOT NULL",
            (did,),
        )
    }
    ids = sorted(tagged - protected)
    counts: dict[str, int] = {}
    # 派生行删哪些表：**按库结构算**（凡是带 order_id 列的表），不手写表名。
    # 手写清单漏过一次：第一版只写了 order_products/operation_logs/driver_bills/ledgers/cash_flows，
    # 于是 UAT 在造数单上留下的 8 条 `inventory_movements` 变成了指向空号的孤儿行
    # （试跑副本上被不变式审计当场报出来）。"要检查/要清理哪些表"这类清单一律让脚本自己算。
    dep_tables: list[str] = []
    # ⚠️ 先把表名 fetchall 出来，再逐个 PRAGMA：在同一个 cursor 上"边遍历边 execute"
    #    会让外层遍历提前结束（第一版就是这样，结果派生行一条都没删，审计立刻报 700+ 孤儿行）。
    for (t,) in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall():
        if t == "orders":
            continue
        cols = [r[1] for r in cur.execute(f"PRAGMA table_info({t})").fetchall()]
        if "order_id" in cols:
            dep_tables.append(t)
    # 收款单里的 order_ids 是 JSON 数组：只删"整个都指向要删的单"的那些，别误伤真实收款
    doomed = set(ids)
    receipts = [
        r[0]
        for r in cur.execute("SELECT id, order_ids FROM shipper_receipts WHERE order_ids IS NOT NULL")
        if (json.loads(r[1]) or [None]) and set(json.loads(r[1])) <= doomed
    ]
    for oid in ids:
        for tbl in dep_tables:
            counts[tbl] = counts.get(tbl, 0) + cur.execute(
                f"DELETE FROM {tbl} WHERE order_id=?", (oid,)
            ).rowcount
    for rid in receipts:
        counts["shipper_receipts"] = counts.get("shipper_receipts", 0) + cur.execute(
            "DELETE FROM shipper_receipts WHERE id=?", (rid,)
        ).rowcount
    # ⚠️ 删订单本身也必须**按 id 列表**删，不能再来一句 `WHERE order_no LIKE 'SOTEST%'`：
    #    第一版就是这样（试跑副本当场抓到）：上面按 id 跳过了受保护的单，
    #    下面那条 LIKE 又把它删掉了 → 留下 22 条指向空号的已结账单。
    #    "同一个集合在两处用两种写法"是这个项目反复栽过的坑。
    if ids:
        qs = ",".join("?" * len(ids))
        counts["orders"] = cur.execute(f"DELETE FROM orders WHERE id IN ({qs})", ids).rowcount

    # 「整个身子压在造数数据上」的结算单：明细 → 付款流水 → 结算单本身
    for did in adopted:
        counts["driver_bills"] = counts.get("driver_bills", 0) + cur.execute(
            "DELETE FROM driver_bills WHERE settled_doc_id = ?", (did,)
        ).rowcount
        counts["cash_flows"] = counts.get("cash_flows", 0) + cur.execute(
            "DELETE FROM cash_flows WHERE doc_id = ? AND biz_type LIKE 'PAYMENT%'", (did,)
        ).rowcount
        counts["driver_settlements"] = counts.get("driver_settlements", 0) + cur.execute(
            "DELETE FROM driver_settlements WHERE id = ?", (did,)
        ).rowcount
    if adopted:
        print(f"  清理：连别人的 {len(adopted)} 张结算单一起删了（它们的明细全是本工具造的单："
              f"{adopted}）——不删的话它们会变成「已付款却没有明细」")
    if protected:
        print(f"  清理：**留下** {len(protected)} 张 SOTEST 单（结算单 {keep_docs} 里掺了非本工具的数据）")

    # 自己建的结算单：明细先删（否则删掉结算单会剩下一批 settled_doc_id 指向空号的账单）
    counts["driver_bills"] = counts.get("driver_bills", 0) + cur.execute(
        "DELETE FROM driver_bills WHERE settled_doc_id IN "
        "(SELECT id FROM driver_settlements WHERE note LIKE ?)", (f"{TAG}%",)
    ).rowcount
    for tbl, sql in (
        ("driver_settlements", "DELETE FROM driver_settlements WHERE note LIKE ?"),
        ("products", "DELETE FROM products WHERE name LIKE ?"),
        ("users", "DELETE FROM users WHERE username LIKE ?"),
        ("cash_flows", "DELETE FROM cash_flows WHERE note LIKE ?"),
    ):
        counts[tbl] = counts.get(tbl, 0) + cur.execute(sql, (f"{TAG}%",)).rowcount
    con.commit()
    return {k: v for k, v in counts.items() if v}


def main() -> int:
    global DB

    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true", help="只清理，不造数")
    ap.add_argument("--db", default="", help="目标库路径（默认开发库；试跑用）")
    a = ap.parse_args()
    if a.db:
        DB = Path(a.db).resolve()
    guard()

    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys=OFF")
    cur = con.cursor()

    removed = clean(con)
    if removed:
        print("  已清理上次造的数据：" + "、".join(f"{k} {v} 行" for k, v in removed.items()))

    if a.clean:
        print("  仅清理模式，结束")
        con.close()
        return 0

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    today = date.today()
    # 上上月 / 上月 / 本月 的边界
    this_first = today.replace(day=1)
    last_end = this_first - timedelta(days=1)
    last_first = last_end.replace(day=1)
    prev_end = last_first - timedelta(days=1)
    prev_first = prev_end.replace(day=1)

    print(f"  区间：上上月 {prev_first}~{prev_end}（仅作边界探针）")
    print(f"        上月   {last_first}~{last_end}")
    print(f"        本月   {this_first}~{today}")

    dispatcher_id = cur.execute(
        "SELECT id FROM users WHERE role='DISPATCHER' ORDER BY id LIMIT 1"
    ).fetchone()
    dispatcher_id = dispatcher_id[0] if dispatcher_id else None

    # ---------------------------------------------------------- 货主
    def add_user(username, phone, name, role, member=False, **extra) -> int:
        cols = ["username", "phone", "password_hash", "full_name", "role", "is_active",
                "is_member", "created_at", "updated_at"]
        vals: list = [username, phone, "x", name, role, 1, 1 if member else 0, now, now]
        for k, v in extra.items():
            cols.append(k)
            vals.append(v)
        cur.execute(f"INSERT INTO users ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
        return int(cur.lastrowid or 0)

    # 手机号冲突检查：撞到别人（非 SOTEST）就走人，别把真实数据搅乱
    # 前缀取 1371 —— 开发库里已用的是 1391000/1382000/1380000/1390000，1371 是空段
    phones = [f"1371000{i:04d}" for i in range(len(SHIPPER_PLAN) + len(DRIVER_PLAN) + 1)]
    clash = cur.execute(
        f"SELECT phone FROM users WHERE phone IN ({','.join('?' * len(phones))}) "
        f"AND username NOT LIKE ?", (*phones, f"{TAG}%")
    ).fetchall()
    if clash:
        sys.exit(f"手机号被占用（非本脚本造的数据）：{[c[0] for c in clash]}，请改前缀再跑")

    shippers: list[tuple[int, str, int, int]] = []  # (id, 名字, 上月单量, 本月单量)
    for i, (name, member, n_last, n_this) in enumerate(SHIPPER_PLAN):
        uid = add_user(f"{TAG}_s{i:02d}", phones[i], name, "SHIPPER", member=member)
        shippers.append((uid, name, n_last, n_this))
    print(f"  货主 {len(shippers)} 个（含 {sum(1 for s in SHIPPER_PLAN if s[1])} 个批发商）")

    # ---------------------------------------------------------- 司机
    drivers: list[tuple[int, str, str, int]] = []
    for i, (name, vehicle, billing, weight) in enumerate(DRIVER_PLAN):
        uid = add_user(
            f"{TAG}_d{i:02d}", phones[len(SHIPPER_PLAN) + i], name, "DRIVER",
            vehicle_type=vehicle, billing_mode=billing,
            **({"salary": "6500.00"} if billing == "SALARY" else {}),
        )
        drivers.append((uid, name, billing, weight))
    print(f"  司机 {len(drivers)} 个（计件 {sum(1 for d in DRIVER_PLAN if d[2] == 'PIECE')}、"
          f"工资制 {sum(1 for d in DRIVER_PLAN if d[2] == 'SALARY')}）")

    # ---------------------------------------------------------- 商品
    products: list[tuple[int, str, Decimal, Decimal]] = []
    for i, (name, price, cost, unit, stock, alert) in enumerate(PRODUCT_PLAN):
        cur.execute(
            "INSERT INTO products (name, default_unit_price, cost_price, is_active, stock, unit,"
            " low_stock_alert, tier_prices, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"{TAG}{name}", price, cost, 1, stock, unit, alert, "[]", now, now),
        )
        products.append((int(cur.lastrowid or 0), name, Decimal(price), Decimal(cost)))
    alerts_expected = [p for p in PRODUCT_PLAN if p[5] > 0 and p[4] <= p[5]]
    print(f"  商品 {len(products)} 个（应触发报警 {len(alerts_expected)} 个："
          + "、".join(p[0] for p in alerts_expected) + "）")

    # ---------------------------------------------------------- 订单
    seq = 0
    stat = {"delivered": 0, "ledger": 0, "cash": 0, "other": 0}

    def pick_driver() -> tuple[int, str, str]:
        pool = [d for d in drivers for _ in range(d[3])]
        return RNG.choice(pool)

    def add_order(day: date, shipper_id: int | None, temp_name: str | None, status: str,
                  driver: tuple[int, str, str] | None, lines: list[tuple[int, str, Decimal, Decimal]],
                  late: bool) -> tuple[int, Decimal]:
        """写一单 + 明细（+已送达时的账本行与资金流水）。返回 (order_id, 订单总额)。"""
        nonlocal seq
        seq += 1
        # 单号必须唯一：库上有一条 UNIQUE(orders.order_no)。清理**故意留下**的
        # SOTEST 单（别的工具在它们上面结算过）会占掉同一天的号段，
        # 于是重跑时撞 UNIQUE —— 试跑副本上当场撞过一次。这里往后顺延，不去改别人的单号。
        while cur.execute(
            "SELECT 1 FROM orders WHERE order_no = ?", (f"{TAG}{day.strftime('%Y%m%d')}{seq:05d}",)
        ).fetchone():
            seq += 1
        order_no = f"{TAG}{day.strftime('%Y%m%d')}{seq:05d}"
        # 库里时间一律 UTC：北京 09:00 派单 = 01:00 UTC，北京 15:00 送达 = 07:00 UTC
        dispatched = datetime.combine(day, datetime.min.time()) + timedelta(hours=1, minutes=RNG.randint(0, 30))
        if status == "DELIVERED":
            d_day = day + timedelta(days=1) if late else day
            delivered = datetime.combine(d_day, datetime.min.time()) + timedelta(hours=7, minutes=RNG.randint(0, 59))
        else:
            delivered = None
        acked = dispatched + timedelta(minutes=RNG.randint(10, 90)) if status in ("ACCEPTED", "DELIVERED") else None
        collect = status == "DELIVERED" and RNG.random() < 0.42
        freight = Decimal(RNG.choice([20, 25, 30, 35, 40, 45, 50, 60])).quantize(Decimal("0.01"))
        # 期望送达时间：给部分单子设一个偏早的 SLA，制造「超期」样本（准时率不会是 100%）
        sla = datetime.combine(day, datetime.min.time()) + timedelta(hours=RNG.choice([3, 5, 20]))
        has_exc = RNG.random() < 0.04
        photos = [f"/static/uploads/order/{order_no}_{k}.jpg" for k in range(RNG.randint(1, 2))] \
            if status == "DELIVERED" and RNG.random() < 0.85 else []

        cur.execute(
            "INSERT INTO orders (order_no, status, shipper_id, temp_shipper_name, driver_id, order_date,"
            " delivery_description, address_detail, address_lat, address_lng,"
            " contact_dongjia_phone, contact_boss_phone, remark, internal_notes,"
            " driver_remark, delivery_photo_urls, dispatched_at, driver_acknowledged_at, delivered_at,"
            " cancelled_at, expected_deliver_before, is_exception, exception_reason, exception_resolution,"
            " payment_method, paid, arrears_unit_id, arrears_unit_name, created_at, updated_at,"
            " address_image_url, freight_fee, driver_billing_mode_snapshot, parent_order_id,"
            " exception_resolved_at, collect_cash, damage_note, image_urls, deleted_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (order_no, status, shipper_id, temp_name, driver[0] if driver else None, day.isoformat(),
             "送货上门", f"测试收货地址 {RNG.randint(1, 99)} 号", None, None,
             f"1371000{seq:04d}", f"1372000{seq:04d}",
             "", "", "门口有人", json.dumps(photos, ensure_ascii=False),
             dispatched.strftime("%Y-%m-%d %H:%M:%S"),
             acked.strftime("%Y-%m-%d %H:%M:%S") if acked else None,
             delivered.strftime("%Y-%m-%d %H:%M:%S") if delivered else None,
             None, sla.strftime("%Y-%m-%d %H:%M:%S"),
             1 if has_exc else 0,
             RNG.choice(["客户改时间", "地址找不到", "货物破损"]) if has_exc else "",
             "已现场处理" if has_exc else "",
             "cash" if collect else "arrears", 1 if collect else 0, None, "",
             datetime.combine(day, datetime.min.time()).strftime("%Y-%m-%d %H:%M:%S"), now,
             None, str(freight), driver[2] if driver else None, None, None,
             1 if collect else 0, "", "[]", None),
        )
        oid = int(cur.lastrowid or 0)
        op_ids: list[tuple[int, int, str, int, Decimal, Decimal]] = []
        for pid, pname, price, cost in lines:
            qty = RNG.choice([1, 2, 3, 5, 8])
            lt = (price * qty).quantize(Decimal("0.01"))
            dmg = qty if (status == "DELIVERED" and RNG.random() < 0.02) else 0
            cur.execute(
                "INSERT INTO order_products (order_id, product_id, product_name_snapshot, quantity,"
                " unit_price, line_total, created_at, updated_at, cost_price_snapshot, damage_quantity)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (oid, pid, f"{TAG}{pname}", qty, str(price), str(lt), now, now, str(cost), dmg),
            )
            op_ids.append((int(cur.lastrowid or 0), pid, pname, qty, price, lt))
        total = sum((x[5] for x in op_ids), Decimal("0")).quantize(Decimal("0.01"))

        if status == "DELIVERED" and (shipper_id is not None or (temp_name or "").strip()):
            entry_date = (delivered.date() if delivered else day).isoformat()
            for opid, pid, pname, qty, price, lt in op_ids:
                cur.execute(
                    "INSERT INTO ledgers (shipper_id, temp_shipper_name, entry_date, product_name,"
                    " quantity, unit_price, total, order_id, order_product_id, product_id, source,"
                    " note, created_at, updated_at, cost_price_snapshot, customer_id)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (shipper_id, temp_name if shipper_id is None else None, entry_date,
                     f"{TAG}{pname}", qty, str(price), str(lt), oid, opid, pid, "ORDER",
                     "订单送达自动记账", now, now,
                     str(next(c for p, n, _, c in products if p == pid)), None),
                )
                stat["ledger"] += 1
            if collect:
                name = temp_name or next((n for i, n, _, _ in shippers if i == shipper_id), "")
                cur.execute(
                    "INSERT INTO cash_flows (flow_date, direction, amount, party_type, party_id,"
                    " party_name, channel, biz_type, order_id, doc_id, note, operator_id,"
                    " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (entry_date, "in", str(total), "customer", shipper_id, f"{TAG}{name}",
                     "cash", "RECEIPT_CASH", oid, None, f"{TAG} 送达收现金 {order_no}",
                     dispatcher_id, now, now),
                )
                stat["cash"] += 1
        stat["delivered" if status == "DELIVERED" else "other"] += 1
        return oid, total

    def spread(month_first: date, month_last: date, n: int) -> list[date]:
        """把 n 单铺进这个月，同一天可以有多单。"""
        days = (month_last - month_first).days + 1
        return sorted(month_first + timedelta(days=RNG.randrange(days)) for _ in range(n))

    def line_pick() -> list[tuple[int, str, Decimal, Decimal]]:
        k = RNG.choice([1, 1, 1, 2, 3])
        return RNG.sample(products, k)

    # 上月 + 本月：每个货主按蓝图铺单
    for uid, name, n_last, n_this in shippers:
        for d in spread(last_first, last_end, n_last):
            add_order(d, uid, None, "DELIVERED", pick_driver(), line_pick(), late=RNG.random() < 0.14)
        for d in spread(this_first, today, n_this):
            add_order(d, uid, None, "DELIVERED", pick_driver(), line_pick(), late=RNG.random() < 0.14)

    # 上上月：8 单「边界探针」——任何本月/上月统计里出现它们都是 bug
    probe_shipper = shippers[0][0]
    for d in spread(prev_first, prev_end, 8):
        add_order(d, probe_shipper, None, "DELIVERED", pick_driver(), line_pick(), late=False)

    # 临时货主（无账号）：3 单
    for name, d in zip(TEMP_SHIPPERS, spread(this_first, today, len(TEMP_SHIPPERS))):
        add_order(d, None, name, "DELIVERED", pick_driver(), line_pick(), late=False)

    # 未送达的一批：近 6 天，验证「已送达」口径没把它们算进去
    recent = [today - timedelta(days=k) for k in range(6)]
    for st, n in (("DISPATCHED", 6), ("PENDING_DISPATCH", 5), ("ACCEPTED", 2), ("CANCELLED", 1)):
        for i in range(n):
            d = recent[i % len(recent)]
            sh = shippers[i % len(shippers)][0]
            add_order(d, sh, None, st, pick_driver() if st != "PENDING_DISPATCH" else None,
                      line_pick(), late=False)

    # 一张「本月」已付的司机结算单：让「待结运费 = 应结 - 已结」真的发生一次减法。
    #
    # ⚠️ 这张单**必须带明细**（2026-09-18 修）。原来是直接 INSERT 一行 `status=paid`、
    #    `order_ids=[]` 的结算单，既没有 `driver_bills`、也没有付款流水 —— 库里因此留下
    #    一张「付了 352 元、账上没有任何应付款」的假账（`_tools/qa/_probe_settlement_orphan.py`
    #    报出来的就是它）。App 里**造不出**这种单（建单要待结明细、确认要金额与明细一致、
    #    付款要状态是已确认），所以它只能是造数工具绕开业务规则写出来的。
    #    现在照 App 的顺序造：先明细（settled + settled_doc_id 指回来）→ 再结算单 →
    #    再付款流水，金额三者一致。
    piece_driver = drivers[0][0]
    this_month = this_first.strftime("%Y-%m")
    cand = cur.execute(
        "SELECT id, COALESCE(freight_fee,0) FROM orders WHERE driver_id=? AND status='DELIVERED'"
        " AND delivered_at >= ? ORDER BY id",
        (piece_driver, f"{this_month}-01 00:00:00"),
    ).fetchall()
    want = (sum((Decimal(str(c[1])) for c in cand), Decimal("0")) * Decimal("0.4")).quantize(Decimal("0.01"))
    picked: list[tuple[int, Decimal]] = []
    acc = Decimal("0")
    for oid_, fee in cand:
        f = Decimal(str(fee)).quantize(Decimal("0.01"))
        if f <= 0:
            continue
        picked.append((int(oid_), f))
        acc += f
        if acc >= want:
            break
    if not picked:
        print("  （该司机本月没有已送达的单，跳过「已付结算单」的造数——不许造无明细的）")
    else:
        settled_amount = acc.quantize(Decimal("0.01"))
        cur.execute(
            "INSERT INTO driver_settlements (driver_id, settle_type, month, period_from, period_to,"
            " amount, status, order_ids, paid_at, method, operator_id, note, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (piece_driver, "piece", this_month, this_first.isoformat(), today.isoformat(),
             str(settled_amount), "paid", json.dumps([o for o, _ in picked]), now, "cash", dispatcher_id,
             f"{TAG} 批量测试结算（40%）", now, now),
        )
        sid = int(cur.lastrowid or 0)
        for oid_, amt in picked:
            cur.execute(
                "INSERT INTO driver_bills (driver_id, bill_type, order_id, month, amount, status,"
                " settled_doc_id, note, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                # 金额 = 该单运费：这些造出来的司机**没有计费规则**，App 在送达时
                # 算出来的应付就是全额运费（`driver_pay.pay_for_order` 的 rule=None 分支），
                # 所以这里抄运费与"钱只算一处"不冲突——审计工具会用 driver_pay 重算对账。
                (piece_driver, "piece", oid_, this_month, str(amt), "settled", sid,
                 f"{TAG} 结算明细（造数）", now, now),
            )
        cur.execute(
            "INSERT INTO cash_flows (flow_date, direction, amount, party_type, party_id, party_name,"
            " channel, biz_type, order_id, doc_id, note, operator_id, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (today.isoformat(), "out", str(settled_amount), "driver", piece_driver, "",
             "cash", "PAYMENT_DRIVER", None, sid, f"{TAG} 司机结算单 #{sid}（{this_month}）",
             dispatcher_id, now, now),
        )
        print(f"  已付结算单 #{sid}：{len(picked)} 条明细 / {settled_amount} 元"
              f"（明细 + 结算单 + 付款流水三者一致）")

    con.commit()

    # ------------------------------------------------------------ 自检（2026-09-18 加）
    #
    # 造数工具真正危险的地方不是"造得少"，是**造出自相矛盾的账**：
    # 本轮的 ③ 就是它造出来的——一张已付款、0 条明细的结算单（352 元），
    # 每次对账检查都要重新怀疑一次。所以造完立刻自查两条与本轮缺陷同源的判据，
    # 不许"造完就走"。
    bad = cur.execute(
        "SELECT COUNT(*) FROM driver_settlements s WHERE s.note LIKE ? "
        "AND s.status IN ('confirmed','paid') AND NOT EXISTS "
        "(SELECT 1 FROM driver_bills b WHERE b.settled_doc_id = s.id)",
        (f"{TAG}%",),
    ).fetchone()[0]
    orphan_bills = cur.execute(
        "SELECT COUNT(*) FROM driver_bills WHERE order_id IS NOT NULL "
        "AND order_id NOT IN (SELECT id FROM orders)"
    ).fetchone()[0]
    leak = cur.execute(
        "SELECT COUNT(*) FROM driver_settlements s WHERE s.status IN ('confirmed','paid') "
        "AND NOT EXISTS (SELECT 1 FROM driver_bills b WHERE b.settled_doc_id = s.id)"
    ).fetchone()[0]
    if bad:
        sys.exit(f"  ⛔ 自检失败：本次造的结算单里有 {bad} 张没有明细（造数不一致，必须修工具）")
    print(f"  自检：本次造的已付结算单都有明细 ✅；全库孤儿账单 {orphan_bills} 条、"
          f"无明细的已确认/已付款结算单 {leak} 张"
          + ("（都不是本次造的数，属历史遗留）" if (orphan_bills or leak) else ""))

    # ------------------------------------------------------------ 结果核对
    print("\n  造完后的核对（这些数字就是 AI 应该答出来的）：")
    for label, sql, args in (
        ("上月已送达订单", "SELECT COUNT(*) FROM orders WHERE order_no LIKE ? AND status='DELIVERED'"
                          " AND order_date>=? AND order_date<=?", (f"{TAG}%", last_first, last_end)),
        ("本月已送达订单", "SELECT COUNT(*) FROM orders WHERE order_no LIKE ? AND status='DELIVERED'"
                          " AND order_date>=? AND order_date<=?", (f"{TAG}%", this_first, today)),
        ("上上月探针单（应=8）", "SELECT COUNT(*) FROM orders WHERE order_no LIKE ? AND order_date>=?"
                                " AND order_date<=?", (f"{TAG}%", prev_first, prev_end)),
        ("账本行", "SELECT COUNT(*) FROM ledgers WHERE note LIKE ? OR note LIKE ?",
         ("订单送达自动记账", f"{TAG}%")),
        ("资金流水", "SELECT COUNT(*) FROM cash_flows WHERE note LIKE ?", (f"{TAG}%",)),
        ("到红线的商品（应=3）", "SELECT COUNT(*) FROM products WHERE name LIKE ?"
                                " AND low_stock_alert>0 AND stock<=low_stock_alert", (f"{TAG}%",)),
    ):
        print(f"    {label}: {cur.execute(sql, args).fetchone()[0]}")

    print("\n    本月货主前 5（按已送达单数）：")
    for r in cur.execute(
        "SELECT u.full_name, COUNT(*) c FROM orders o JOIN users u ON u.id=o.shipper_id"
        " WHERE o.order_no LIKE ? AND o.status='DELIVERED' AND o.order_date>=? AND o.order_date<=?"
        " GROUP BY o.shipper_id ORDER BY c DESC, u.full_name LIMIT 5",
        (f"{TAG}%", this_first, today),
    ):
        print(f"      {r[0]}：{r[1]} 单")
    print("    上月货主前 5（按已送达单数）：")
    for r in cur.execute(
        "SELECT u.full_name, COUNT(*) c FROM orders o JOIN users u ON u.id=o.shipper_id"
        " WHERE o.order_no LIKE ? AND o.status='DELIVERED' AND o.order_date>=? AND o.order_date<=?"
        " GROUP BY o.shipper_id ORDER BY c DESC, u.full_name LIMIT 5",
        (f"{TAG}%", last_first, last_end),
    ):
        print(f"      {r[0]}：{r[1]} 单")
    print("\n    本月司机跑货（按已送达单数）：")
    for r in cur.execute(
        "SELECT u.full_name, u.billing_mode, COUNT(*) c, COALESCE(SUM(o.freight_fee),0) f"
        " FROM orders o JOIN users u ON u.id=o.driver_id"
        " WHERE o.order_no LIKE ? AND o.status='DELIVERED' AND o.delivered_at>=?"
        " GROUP BY o.driver_id ORDER BY c DESC", (f"{TAG}%", this_first.isoformat()),
    ):
        print(f"      {r[0]}（{r[1]}）：{r[2]} 单，运费 {Decimal(str(r[3])):.2f}"
              + ("  ← 工资制，工具不应给待结运费" if r[1] == "SALARY" else ""))

    con.close()
    print(f"\n  ✅ 完成：已送达 {stat['delivered']} 单、账本 {stat['ledger']} 行、"
          f"现金流水 {stat['cash']} 条、未送达/撤销 {stat['other']} 单")
    print("  测完用 `python _seed_test_data.py --clean` 一键清掉。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
