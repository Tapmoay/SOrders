"""生产库**只读**体检（2026-09-23 第 9 轮起）：把"只有真库能给的证据"变成一条可重复的命令。

## 为什么需要它

前 8 轮的证据源都是本机：SQLite 单测、静态红线、模拟器真机。它们**证明不了**这几件事：

1. **线上库里那些行真的自洽吗** —— 单测造的是干净数据；真库里有代下单、软删隔离区、
   货损退货、跨月结算、历史遗留列。前几轮抓到的那类缺陷（"已收款却还指着挂账单位"）
   恰恰只在真库里表现为**两个数各说各的**，接口一律 200、界面上谁也看不出来。
2. **索引到底在不在、优化器走没走** —— 本机 SQLite 的 `EXPLAIN QUERY PLAN` 与 MySQL 是两套
   优化器。本机"加了窗口过滤就快了"在 MySQL 上可能根本不成立（第 9 轮实测就是这样：
   窗口条件没进任何索引，报表那一族查询在生产上是 **`Table scan on o`**，读全表 2402 行）。
3. **线上数据和仓库代码是不是同一套口径** —— 比如"结算单金额必须等于它列的司机账单合计"，
   只有拿真库那 51 张 draft 单去比才知道有没有分叉。

## 只读保证（本脚本的第一条纪律）

发出的 SQL **只有 `SELECT` / `EXPLAIN ANALYZE` / `SHOW`**，脚本自己在发之前过一遍
`FORBIDDEN` 正则（`INSERT/UPDATE/DELETE/ALTER/DROP/...` 一律拒绝执行）—— 也就是说
"这个工具会不会误写生产库"这件事**不靠人记性**，靠一条判据。凭据只在服务器侧读
（`/root/.sorders-db-credentials.txt`，600），本地不留、不打印，命令行里也不出现口令形状
（`_check_secrets.py` 会红的那种）。⛔ 不重启服务、不跑迁移、不改任何一行数据。

## 用法

```
python _tools/qa/_probe_prod_readonly.py                # 19 条库级不变式 + 三条热点查询的计划 + 索引清单
python _tools/qa/_probe_prod_readonly.py --expect-index # 额外**硬性**要求报表窗口索引存在且被用上（部署后跑这个）
python _tools/qa/_probe_prod_readonly.py --validate-ddl # 把 bootstrap 那两句 DDL 在**会话级临时表**上演一遍
python _tools/qa/_probe_prod_readonly.py --sql          # 只打印会发出去的 SQL（审计用，不连服务器）
```

⚠️ 唯一的例外是 `--validate-ddl`：它会 `CREATE/ALTER/DROP TEMPORARY TABLE`，但作用对象是
**会话级临时表**（连上就建、断开就消失、`SHOW TABLES` 看不见、与 `orders` 无关），列类型从
`orders` 的真实定义抄过来。为什么值得破这个例：`schema_bootstrap` 的 DDL 外面包着
`try/except DBAPIError: logger.warning(...)`，**写错了不会有任何报错**，只会每次启动多一行 warning、
索引永远不存在 —— 而本机是 SQLite，验不了 MySQL 语法。默认不跑这一段。

## "0 行"什么时候才算证据

每条不变式都同时报 **命中范围（total）**：`bad = 0` 只有在 `total > 0` 时才说明问题；
表是空的也会是 0 行。所以每条都带 `min_scope`，不够就报 `N/A` 而不是 `OK`
（第 9 轮实测抓到过一条：结算单那条不变式一开始按"账单已盖结算章"写，而生产上 51 张单
全是 draft、1515 张账单全没盖章 → 51/51 "bad"，是**判据写错**不是缺陷；改成
"结算单金额 = 它列的那些订单的司机账单合计"之后是 0/51，这才是真判据）。

⚠️ 这条工具**不进** `_check_all.py`（它要连生产库）：脚本名不是 `_check_*`，
也刻意不声明 `--check` —— 清单是自算的，声明了就每次静态检查都要连一次线上。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

#: 仓库根与后端目录：两段"代码 ↔ 线上库"的对账要 import `app.*`（枚举清单、生成的 DDL）。
ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"

#: 生产机（阿里云）。用密钥登录，和 `_tools/deploy/publish_apk.py` 同一把钥匙、同一个写法。
HOST = "8.145.40.22"
SSH_KEY = os.path.join(os.path.expanduser("~"), ".ssh", "id_ed25519_sorders")
#: 凭据文件在服务器上（600）。**只在远端 shell 里 source**，本地既不知道也不打印。
REMOTE_CRED = "/root/.sorders-db-credentials.txt"
DB_NAME = "sorders"

SSH_BASE = [
    "ssh", "-i", SSH_KEY,
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=no",
    "-o", "ConnectTimeout=15",
    f"root@{HOST}",
]

#: 远端那条命令：读凭据 → 用环境变量传口令（**命令行里不出现口令**，`_check_secrets.py` 的红线形状）
REMOTE_MYSQL = (
    f"set -a; . {REMOTE_CRED}; set +a; "
    f'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u"$MYSQL_USER" --batch --raw -N {DB_NAME}'
)

#: 只读自检：任何一条 SQL 命中它就**拒绝执行**（防止以后有人往这张表里加一句 UPDATE）。
FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|REPLACE|GRANT|REVOKE|RENAME|LOCK|CALL|LOAD)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Invariant:
    """一条库级不变式：跑出来两个数 —— 违规行数（bad）与命中范围（total）。"""

    key: str
    title: str
    sql: str
    why: str
    #: 命中范围的下限：低于它说明"这批数据在这条判据上还没有发言权"→ 报 N/A 而不是 OK。
    min_scope: int = 1


#: ⚠️ 每条都以 `bad, total` 两列返回（`COALESCE(SUM(...),0)` 兜住空表）。
INVARIANTS: tuple[Invariant, ...] = (
    Invariant(
        "A", "已收款却还指着挂账单位",
        "SELECT COALESCE(SUM(CASE WHEN o.arrears_unit_id IS NOT NULL THEN 1 ELSE 0 END),0), COUNT(*)"
        "  FROM orders o WHERE o.paid = 1",
        "钱收到了就不该再挂在某个单位的账上（第 7 轮修的正是这条；挂账汇总会重复计一笔）",
        min_scope=1,
    ),
    Invariant(
        "B", "库存为负",
        "SELECT COALESCE(SUM(CASE WHEN p.stock < 0 THEN 1 ELSE 0 END),0), COUNT(*)"
        "  FROM products p",
        "库存只能走出入库流水，负数说明某条流水没记或记反了",
    ),
    Invariant(
        "C", "订单已终态却还留着预占库存（RESERVED）",
        "SELECT COALESCE(SUM(CASE WHEN o.id IS NULL OR o.status IN ('DELIVERED','CANCELLED')"
        " THEN 1 ELSE 0 END),0), COUNT(*)"
        "  FROM inventory_movements m LEFT JOIN orders o ON o.id = m.order_id"
        " WHERE m.status = 'RESERVED'",
        "预占是「下单占住、送达/撤销时落地」的两步动作；停在 RESERVED 就是库存被永久占着",
        min_scope=1,
    ),
    Invariant(
        "D", "订单行金额 ≠ 数量 × 单价",
        "SELECT COALESCE(SUM(CASE WHEN ABS(p.line_total - ROUND(p.quantity * p.unit_price, 2)) > 0.01"
        " THEN 1 ELSE 0 END),0), COUNT(*)"
        "  FROM order_products p",
        "行金额是账本与营业额的分母；与 数量×单价 不一致就是两个口径（第 6 轮那类「同一笔钱两个数」）",
    ),
    Invariant(
        "E", "同一 (司机, 订单, 类型) 有重复账单",
        "SELECT (SELECT COUNT(*) FROM (SELECT driver_id, order_id, bill_type FROM driver_bills"
        " GROUP BY driver_id, order_id, bill_type HAVING COUNT(*) > 1) d),"
        " (SELECT COUNT(*) FROM driver_bills)",
        "重复账单＝同一趟活算两次钱（送达那条路必须幂等）",
    ),
    Invariant(
        "F", "已送达却没有订单账本",
        "SELECT COALESCE(SUM(CASE WHEN (SELECT COUNT(*) FROM ledgers l"
        " WHERE l.order_id = o.id AND l.source = 'ORDER') = 0 THEN 1 ELSE 0 END),0), COUNT(*)"
        "  FROM orders o WHERE o.status = 'DELIVERED'",
        "送达即入账；没有账本行＝营业额少了这一单（司机账单还在，两边对不上）",
    ),
    Invariant(
        "G", "已送达却没有送达时间",
        "SELECT COALESCE(SUM(CASE WHEN o.delivered_at IS NULL THEN 1 ELSE 0 END),0), COUNT(*)"
        "  FROM orders o WHERE o.status = 'DELIVERED'",
        "业务日/报表窗口/工资月度全靠它；缺了这单在报表里就「哪一天都不算」",
    ),
    Invariant(
        "H", "已撤销却没有撤销时间",
        "SELECT COALESCE(SUM(CASE WHEN o.cancelled_at IS NULL THEN 1 ELSE 0 END),0), COUNT(*)"
        "  FROM orders o WHERE o.status = 'CANCELLED'",
        "撤销时间缺失时，「撤销单」在时间维度上不存在（审计与日报都少一块）",
    ),
    Invariant(
        "I", "待派单却已经挂着司机",
        "SELECT COALESCE(SUM(CASE WHEN o.driver_id IS NOT NULL THEN 1 ELSE 0 END),0), COUNT(*)"
        "  FROM orders o WHERE o.status = 'PENDING_DISPATCH'",
        "状态与司机是同一件事的两面；分叉会让这单同时出现在待派池和司机的任务里",
    ),
    Invariant(
        "J", "已送达却又有撤销时间",
        "SELECT COALESCE(SUM(CASE WHEN o.cancelled_at IS NOT NULL THEN 1 ELSE 0 END),0), COUNT(*)"
        "  FROM orders o WHERE o.status = 'DELIVERED'",
        "送达后又被撤销（或撤销后又被送达）＝状态机走过回头路，钱和货都对不上",
    ),
    Invariant(
        "K", "账本业务日 ≠ 送达业务日（+8 时区）",
        "SELECT COALESCE(SUM(CASE WHEN l.entry_date <> COALESCE(DATE(o.delivered_at + INTERVAL 8 HOUR),"
        " o.order_date) THEN 1 ELSE 0 END),0), COUNT(*)"
        "  FROM ledgers l JOIN orders o ON o.id = l.order_id WHERE l.source = 'ORDER'",
        "口径是 `business_date(delivered_at)`（Asia/Shanghai）；跨月/跨日错位会让月报与日报各说各的",
    ),
    Invariant(
        "L", "逐单核销的收款单绑了「还没收到钱」的单",
        "SELECT COALESCE(SUM(CASE WHEN (SELECT COUNT(*) FROM orders o"
        " WHERE COALESCE(o.paid,0) = 0 AND JSON_CONTAINS(r.order_ids, CAST(o.id AS JSON))) > 0"
        " THEN 1 ELSE 0 END),0), COUNT(*)"
        "  FROM shipper_receipts r WHERE r.settle_mode = 'itemized'",
        "收款单＝钱到了；它指着的单必须已经 paid（否则货主账上会出现「既收了又没收」）",
    ),
    Invariant(
        "M", "收款单绑了不存在的订单",
        "SELECT COALESCE(SUM(CASE WHEN (SELECT COUNT(*) FROM"
        " JSON_TABLE(r.order_ids, '$[*]' COLUMNS(oid INT PATH '$')) jt"
        " WHERE NOT EXISTS (SELECT 1 FROM orders o2 WHERE o2.id = jt.oid)) > 0"
        " THEN 1 ELSE 0 END),0), COUNT(*)"
        "  FROM shipper_receipts r",
        "订单号是 JSON 数组存的；指到不存在的行＝这笔收款再也核销不到任何单上",
    ),
    Invariant(
        "N", "司机账单金额 ≤ 0",
        "SELECT COALESCE(SUM(CASE WHEN b.amount <= 0 THEN 1 ELSE 0 END),0), COUNT(*)"
        "  FROM driver_bills b",
        "账单是要付给司机的钱；0 或负数说明计费规则算错了（「按单计费」没取到金额那类）",
    ),
    Invariant(
        "O", "现金流水金额 ≤ 0",
        "SELECT COALESCE(SUM(CASE WHEN c.amount <= 0 THEN 1 ELSE 0 END),0), COUNT(*)"
        "  FROM cash_flows c",
        "流水报表直接按金额求和；非正金额会静默改掉口径",
    ),
    Invariant(
        "P", "司机结算单金额 ≠ 它列的那些订单的账单合计",
        "SELECT COALESCE(SUM(CASE WHEN ABS(s.amount - (SELECT COALESCE(SUM(b.amount),0)"
        " FROM JSON_TABLE(s.order_ids, '$[*]' COLUMNS(oid INT PATH '$')) jt"
        " JOIN driver_bills b ON b.order_id = jt.oid AND b.driver_id = s.driver_id)) > 0.01"
        " THEN 1 ELSE 0 END),0), COUNT(*)"
        "  FROM driver_settlements s",
        "⚠️ 不能按「账单上盖没盖结算章」判：draft 单本来就不盖章（实测 51/51 假红）。"
        "真判据是「结算单上的数 = 明细合计」（红线 §22 钱只算一处）",
    ),
    Invariant(
        "Q", "运费为负",
        "SELECT COALESCE(SUM(CASE WHEN o.freight_fee < 0 THEN 1 ELSE 0 END),0), COUNT(*)"
        "  FROM orders o",
        "运费同时是司机计件工资的基数与营业额的一部分",
    ),
    Invariant(
        "R", "订单行数量/单价/金额异常",
        "SELECT COALESCE(SUM(CASE WHEN p.quantity <= 0 OR p.unit_price < 0 OR p.line_total < 0"
        " OR COALESCE(p.damage_quantity,0) < 0 OR COALESCE(p.returned_quantity,0) < 0"
        " THEN 1 ELSE 0 END),0), COUNT(*)"
        "  FROM order_products p",
        "负数量/负金额会让营业额、库存、退货三条链路同时算错",
    ),
    Invariant(
        "S", "paid=1 却找不到任何收款凭证",
        "SELECT COALESCE(SUM(CASE WHEN (SELECT COUNT(*) FROM cash_flows c WHERE c.order_id = o.id) = 0"
        " AND (SELECT COUNT(*) FROM shipper_receipts r WHERE r.settle_mode = 'itemized'"
        " AND JSON_CONTAINS(r.order_ids, CAST(o.id AS JSON))) = 0 THEN 1 ELSE 0 END),0), COUNT(*)"
        "  FROM orders o WHERE o.paid = 1",
        "标记成已收款必须有凭据（流水或收款单）；只有标记的话账实不符且查不回去",
    ),
)


@dataclass(frozen=True)
class HotQuery:
    """一条热点查询：`EXPLAIN ANALYZE` 出来的计划必须能让人看出"读了多少行"。"""

    key: str
    title: str
    sql: str
    #: 这条计划里**应该**出现的索引名（None = 只报告、不断言）
    expect_index: str | None


HOT_QUERIES: tuple[HotQuery, ...] = (
    HotQuery(
        "R1", "报表窗口（营业纵览/商品经营/导出 共用的那一族）",
        "SELECT o.id FROM orders o WHERE o.status = 'DELIVERED' AND o.deleted_at IS NULL"
        " AND o.delivered_at >= '2026-09-01 00:00:00' AND o.delivered_at < '2026-10-01 00:00:00'",
        "ix_orders_status_delivered",
    ),
    HotQuery(
        "R2", "待派池（派单员首页按创建倒序）",
        "SELECT o.id FROM orders o WHERE o.status = 'PENDING_DISPATCH'"
        " ORDER BY o.created_at DESC LIMIT 300",
        "ix_orders_status_created",
    ),
    HotQuery(
        "R3", "账本窗口（账本页/报表都打这条）",
        "SELECT l.id FROM ledgers l WHERE l.entry_date >= '2026-09-01' AND l.entry_date <= '2026-09-30'",
        "ix_ledgers_entry_date",
    ),
)

#: 索引清单：名字 → (表, 期望列序)。列序要紧（等值列在前、范围列在后）。
INDEXES: tuple[tuple[str, str, str], ...] = (
    ("ix_orders_status_delivered", "orders", "status,delivered_at"),
    ("ix_orders_status_created", "orders", "status,created_at"),
    ("ix_ledgers_entry_date", "ledgers", "entry_date"),
)

#: 体检上下文（报告用，不判红）：这些数就是"这条判据有多少发言权"的背景。
PROFILE_SQL = (
    "SELECT 'orders', COUNT(*) FROM orders"
    " UNION ALL SELECT 'order_products', COUNT(*) FROM order_products"
    " UNION ALL SELECT 'ledgers', COUNT(*) FROM ledgers"
    " UNION ALL SELECT 'driver_bills', COUNT(*) FROM driver_bills"
    " UNION ALL SELECT 'cash_flows', COUNT(*) FROM cash_flows"
    " UNION ALL SELECT 'shipper_receipts', COUNT(*) FROM shipper_receipts"
    " UNION ALL SELECT 'driver_settlements', COUNT(*) FROM driver_settlements"
    " UNION ALL SELECT 'inventory_movements', COUNT(*) FROM inventory_movements"
    " UNION ALL SELECT 'users', COUNT(*) FROM users"
    " UNION ALL SELECT 'products', COUNT(*) FROM products"
)


def enum_drift_section(have_enums: bool = True) -> tuple[list[str], list[str]]:
    """**代码里的枚举 ↔ 线上库的 `COLUMN_TYPE`** 对账（返回 失败 / 备注 两个清单）。

    为什么这条必须查线上库：MySQL 里往枚举列写一个**不在枚举里**的值是**直接报错** ——
    2026-09-04 那两次生产 500 就是这个形状（`orders.status` 缺 `DISPATCHED` → 派单 100% 500；
    `ledgers.source` 缺 `REFUND` → 货损完成 500）。而**本地怎么测都是对的**：
    开发库是 SQLite（没有 ENUM）、测试库是 `create_all` 现建的（天然是全集）——
    只有线上那台 MySQL 才知道那一列到底有没有跟上代码。

    两个方向都要查：
    - **线上缺**（代码有、库里没有）→ 写它就 500 → **判红**；
    - **线上多**（库里有、代码没有）→ 读出来 SQLAlchemy 认不出这个值 → 一样是 500 → **判红**。
      （要"退役"一个取值必须先迁数据再改列，所以线上多出来就是没做完的迁移。）

    枚举列的清单**从模型 metadata 算**（`_enum_columns()`），不手写；
    本地那一侧由 `_tools/qa/_check_enum_drift.py` 盯着。
    """
    fails: list[str] = []
    notes: list[str] = []
    try:
        sys.path.insert(0, str(BACKEND))
        import app.models  # noqa: F401
        from app.core.schema_bootstrap import _enum_columns

        cols = [(t, c.name, [str(v) for v in c.type.enums]) for t, c in _enum_columns()]
    except Exception as e:  # pragma: no cover - 环境问题要如实报出来，不能静默跳过
        print(f"  [FAIL] 读不到模型里的枚举列（{e}）—— 这一段就没在查，别当它绿了")
        return [f"读不到模型枚举列：{e}"], notes
    if not cols:
        print("  [FAIL] 模型里一个枚举列都没盘到 —— 这一段是空转的")
        return ["枚举列清单为空"], notes

    print(f"  代码里有 {len(cols)} 个枚举列；逐列问线上库的 `COLUMN_TYPE`")
    for table, column, values in cols:
        run = remote_sql(
            "SELECT COLUMN_TYPE FROM information_schema.COLUMNS"
            f" WHERE TABLE_SCHEMA = '{DB_NAME}' AND TABLE_NAME = '{table}'"
            f" AND COLUMN_NAME = '{column}';"
        )
        raw = run.out.strip() if run.ok else ""
        if not raw:
            fails.append(f"{table}.{column}：线上没有这一列（表/列改名了？）")
            print(f"  [FAIL] {table}.{column}：线上没有这一列")
            continue
        inner = raw[raw.find("(") + 1:raw.rfind(")")]
        live = [x.strip().strip("'") for x in inner.split(",")]
        missing = [v for v in values if v not in live]
        extra = [v for v in live if v not in values]
        if not missing and not extra:
            print(f"  [OK]   {table}.{column} —— 线上 {len(live)} 个取值与代码一致")
        else:
            if missing:
                fails.append(f"{table}.{column}：线上缺 {missing} —— 写这些值直接 500")
                print(f"  [FAIL] {table}.{column} 线上缺 {missing}（{len(live)}/{len(values)}）"
                      f" ← 2026-09-04 那两次 500 的形状")
            if extra:
                fails.append(f"{table}.{column}：线上多出 {extra} —— 读这些行会 500（迁移没做完）")
                print(f"  [FAIL] {table}.{column} 线上多出 {extra}（代码认不出这个取值）")
    if len(cols) < 5:
        notes.append(f"枚举列只有 {len(cols)} 个（少于预期的 5 个）—— 是不是有模型没注册进来？")
    return fails, notes


@dataclass
class Run:
    """一次远端查询的结果。"""

    ok: bool
    out: str
    err: str


def remote_sql(sql: str, *, timeout: int = 180) -> Run:
    """把 SQL 用 stdin 喂给远端的 mysql（只读自检在这里，拦住一切写语句）。"""
    hit = FORBIDDEN.search(sql)
    if hit:
        return Run(False, "", f"⛔ 本工具只发只读 SQL，这条里有 `{hit.group(0)}` —— 拒绝执行")
    p = subprocess.run(
        [*SSH_BASE, REMOTE_MYSQL],
        input=sql,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return Run(p.returncode == 0, p.stdout, p.stderr)


def rows(out: str) -> list[list[str]]:
    """把 `--batch` 的 tab 分隔输出切成二维表（空行丢掉）。"""
    return [line.split("\t") for line in out.splitlines() if line.strip()]


def all_sql() -> str:
    """本工具会发出去的全部 SQL（`--sql` 打印它，也是只读自检的输入面）。"""
    parts = [f"-- 索引清单\n{index_sql()}", f"-- 体检上下文\n{PROFILE_SQL};"]
    for inv in INVARIANTS:
        parts.append(f"-- {inv.key} {inv.title}\n{inv.sql};")
    for q in HOT_QUERIES:
        parts.append(f"-- {q.key} {q.title}\nEXPLAIN ANALYZE {q.sql};")
    return "\n\n".join(parts)


def index_sql() -> str:
    names = ",".join(f"'{n}'" for n, _, _ in INDEXES)
    return (
        "SELECT table_name, index_name,"
        " GROUP_CONCAT(column_name ORDER BY seq_in_index SEPARATOR ',')"
        "  FROM information_schema.statistics"
        f" WHERE table_schema = '{DB_NAME}' AND index_name IN ({names})"
        " GROUP BY table_name, index_name"
    )


def main() -> int:
    argv = sys.argv[1:]
    if "--sql" in argv:
        print(all_sql())
        return 0
    expect_index = "--expect-index" in argv
    validate_ddl = "--validate-ddl" in argv
    if not os.path.exists(SSH_KEY):
        print(f"❌ 找不到 SSH 私钥：{SSH_KEY}（生产体检需要它；部署脚本用的也是这一把）")
        return 1

    fails: list[str] = []
    notes: list[str] = []

    # ---- ① 19 条库级不变式 ----
    print("① 库级不变式（每条都报「违规行数 / 命中范围」：范围是 0 的话这条判据没有发言权）")
    batch = "\n".join(
        f"SELECT '{inv.key}', t.* FROM ({_two_cols(inv.sql)}) t;" for inv in INVARIANTS
    )
    run = remote_sql(batch)
    if not run.ok:
        print(f"❌ 连不上生产库或 SQL 出错：{run.err.strip()[:400]}")
        return 1
    got = {r[0]: (int(r[1]), int(r[2])) for r in rows(run.out) if len(r) >= 3}
    for inv in INVARIANTS:
        if inv.key not in got:
            fails.append(f"{inv.key} {inv.title}：没有结果（SQL 出错或没被打印）")
            print(f"  [FAIL] {inv.key} {inv.title} —— 没有结果")
            continue
        bad, total = got[inv.key]
        if total < inv.min_scope:
            notes.append(f"{inv.key} 命中范围只有 {total} 行（< {inv.min_scope}）→ 没发言权")
            print(f"  [N/A]  {inv.key} {inv.title} —— 命中范围 {total} 行，不够判定"
                  f"（{inv.why}）")
        elif bad == 0:
            print(f"  [OK]   {inv.key} {inv.title} —— 0 / {total}")
        else:
            fails.append(f"{inv.key} {inv.title}：{bad} / {total} 行违规")
            print(f"  [FAIL] {inv.key} {inv.title} —— {bad} / {total} 行违规（{inv.why}）")

    # ---- ② 索引清单 ----
    print("\n② 索引清单（等值列在前、范围列在后）")
    run = remote_sql(index_sql())
    have = {r[1]: r[2] for r in rows(run.out) if len(r) >= 3}
    for name, table, want in INDEXES:
        actual = have.get(name)
        if actual is None:
            msg = f"{name}（{table}: {want}）**不存在**"
            if name == "ix_orders_status_delivered":
                notes.append(
                    "报表窗口索引还没落地：补丁在仓库里（`models/order.py` + `schema_bootstrap.py`），"
                    "要在生产**重启一次服务**才会由 bootstrap 建出来（本轮按纪律没重启）"
                )
                print(f"  [--]   {msg} ← 预期（补丁待部署）；R1 仍是全表扫")
            else:
                fails.append(f"{msg} —— 这条不该缺（它早就在线上了）")
                print(f"  [FAIL] {msg}")
        elif actual == want:
            print(f"  [OK]   {name}（{table}: {actual}）")
        else:
            fails.append(f"{name} 列序不对：期望 {want}、实际 {actual}")
            print(f"  [FAIL] {name} 列序不对：期望 {want}、实际 {actual}")

    # ---- ③ 三条热点查询的计划 ----
    print("\n③ 热点查询的 `EXPLAIN ANALYZE`（看的是**读了多少行**，不是耗时——耗时受机器负载影响）")
    for q in HOT_QUERIES:
        run = remote_sql(f"EXPLAIN ANALYZE {q.sql};")
        plan = " ".join(run.out.split())
        if not run.ok:
            fails.append(f"{q.key} 计划取不到：{run.err.strip()[:200]}")
            print(f"  [FAIL] {q.key} 计划取不到：{run.err.strip()[:200]}")
            continue
        used = q.expect_index in plan if q.expect_index else False
        scanned = "Table scan" in plan
        print(f"  · {q.key} {q.title}")
        for line in [l.strip() for l in run.out.splitlines() if l.strip()]:
            print(f"      {line[:200]}")
        if q.expect_index is None:
            print("      → 只报告，不断言")
        elif used:
            print(f"  [OK]   {q.key} 走了 {q.expect_index}")
        elif q.key == "R1" and "ix_orders_status_delivered" not in have:
            print(f"  [--]   {q.key} 还没走 {q.expect_index}：索引尚未部署（见 ②），"
                  f"现在是{'全表扫' if scanned else '别的计划'}")
        else:
            fails.append(f"{q.key} 没走 {q.expect_index}（计划里 {'Table scan' if scanned else '换了别的路径'}）")
            print(f"  [FAIL] {q.key} 没走 {q.expect_index}")

    # ---- ④ 枚举漂移（代码 ↔ 线上库）----
    print("\n④ 枚举漂移：代码里的取值 ↔ 线上库的 `COLUMN_TYPE`（本地怎么测都测不出这一条）")
    enum_fails, enum_notes = enum_drift_section()
    fails += enum_fails
    notes += enum_notes

    # ---- ⑤ 补丁里的 DDL 语法预演（`--validate-ddl`，用**会话级临时表**，不碰任何真实表）----
    if validate_ddl:
        print("\n⑤ `--validate-ddl`：把 bootstrap 那段 DDL 在一张**临时表**上演一遍"
              "（会话一断自动消失、`SHOW TABLES` 看不见、与 `orders` 无关）")
        fails += validate_ddl_on_temp_table(have)

    # ---- ⑥ 硬性要求（部署后跑 `--expect-index` 确认）----
    if expect_index:
        print("\n⑥ `--expect-index`：报表窗口索引必须已存在且被优化器用上")
        idx = have.get("ix_orders_status_delivered")
        if idx != "status,delivered_at":
            fails.append("ix_orders_status_delivered 不存在或列序不对（服务重启后 bootstrap 应该建出来）")
            print(f"  [FAIL] ix_orders_status_delivered = {idx!r}（期望 status,delivered_at）")
        else:
            print("  [OK]   ix_orders_status_delivered 存在且列序正确")

    # ---- ⑦ 体检上下文（只报告）----
    print("\n⑦ 体检上下文（这些数决定上面每条的发言权；只报告，不判红）")
    run = remote_sql(PROFILE_SQL + ";")
    for r in rows(run.out):
        if len(r) >= 2:
            print(f"  · {r[0]:<20} {r[1]}")
    span = remote_sql(
        "SELECT CONCAT(MIN(DATE(order_date)), ' → ', MAX(DATE(order_date))), COUNT(*) FROM orders;"
    )
    for r in rows(span.out):
        if len(r) >= 2:
            print(f"  · 订单业务日跨度            {r[0]}（{r[1]} 单）")

    print("\n" + "=" * 60)
    if notes:
        print("备注：")
        for n in notes:
            print("   - " + n)
    if fails:
        print(f"\n❌ {len(fails)} 项不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    n_na = sum(1 for inv in INVARIANTS if inv.key in got and got[inv.key][1] < inv.min_scope)
    print(f"✅ 生产库只读体检通过：{len(INVARIANTS) - n_na}/{len(INVARIANTS)} 条不变式有发言权且 0 违规"
          f"（{n_na} 条数据量不够、报 N/A），索引与热点计划见上。")
    return 0


def _two_cols(sql: str) -> str:
    """把一条不变式包成子查询（`SELECT key, bad, total FROM (…) t`）。"""
    return sql.strip().rstrip(";")


def validate_ddl_on_temp_table(have: dict[str, str]) -> list[str]:
    """把 bootstrap 里那两句 DDL 在**临时表**上演一遍，返回失败清单。

    ### 为什么值得单独做这一步
    `schema_bootstrap` 是新库/老库结构对齐的**唯一入口**，而它跑在启动路径上、
    外面包着 `try/except DBAPIError: logger.warning(...)` —— 也就是说：
    **DDL 写错了不会有任何报错**，只会每次启动多一行 warning，然后索引永远不存在
    （第 9 轮量的那个 `Table scan on orders` 就会一直在）。而这段代码在本机无法验证：
    开发库是 SQLite（没有 `SHOW INDEX`、没有 `ADD INDEX` 这种语法）。
    所以拿生产那台 **MySQL 8.0.44** 当"语法编译器"，但⛔ **不碰任何真实表**：

    - 建的是 `CREATE TEMPORARY TABLE`（会话级：连接一断就消失，别的会话与 App 都看不见，
      `SHOW TABLES` 里也不出现）；
    - 列的类型**从 `orders` 真实定义抄过来**（`status` 的 ENUM 取值、`delivered_at` 的类型），
      这样"能不能给这一列建索引"这件事是被真的验证过的，不是我按常识猜的；
    - 只验证**两句**：`SHOW INDEX … WHERE Key_name = …` 的守卫语义（建之前必须是 0 行）
      与 `ALTER TABLE … ADD INDEX (status, delivered_at)` 能否成功、列序是不是 1/2。
    """
    fails: list[str] = []
    # 真实列定义（只读 information_schema）
    run = remote_sql(
        "SELECT column_name, column_type FROM information_schema.columns"
        f" WHERE table_schema = '{DB_NAME}' AND table_name = 'orders'"
        "   AND column_name IN ('status','delivered_at');"
    )
    cols = {r[0]: r[1] for r in rows(run.out) if len(r) >= 2}
    need = ("status", "delivered_at")
    missing = [c for c in need if c not in cols]
    if missing:
        print(f"  [FAIL] 从 information_schema 读不到 orders 的列定义：缺 {missing}")
        return [f"读不到 orders 列定义（缺 {missing}）"]

    temp = "_dsh_idx_ddl_check"
    # ⚠️ `SHOW INDEX` **不能当派生表用**（第一版写成 `SELECT … FROM (SHOW INDEX …) g`，
    #    MySQL 直接 1064 —— 它只能在语句顶层执行）。所以按顺序发、用 `MARK` 行分段认领结果。
    sql = (
        f"DROP TEMPORARY TABLE IF EXISTS {temp};\n"
        f"CREATE TEMPORARY TABLE {temp} (\n"
        f"  id INT NOT NULL PRIMARY KEY,\n"
        f"  status {cols['status']} NOT NULL,\n"
        f"  delivered_at {cols['delivered_at']} NULL\n"
        ");\n"
        "SELECT 'MARK', 'before';\n"
        f"SHOW INDEX FROM {temp} WHERE Key_name = 'ix_orders_status_delivered';\n"
        f"ALTER TABLE {temp} ADD INDEX ix_orders_status_delivered (status, delivered_at);\n"
        "SELECT 'MARK', 'after';\n"
        f"SHOW INDEX FROM {temp} WHERE Key_name = 'ix_orders_status_delivered';\n"
        f"DROP TEMPORARY TABLE {temp};\n"
        "SELECT 'MARK', 'done';\n"
    )
    # ⚠️ 这一段里有 DDL（`CREATE/ALTER/DROP TEMPORARY TABLE`），所以**绕过**只读自检，
    #    但每一条都写死在上面这段里、只作用于临时表 —— 不接收任何外部输入。
    p = subprocess.run(
        [*SSH_BASE, REMOTE_MYSQL],
        input=sql,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if p.returncode != 0:
        print(f"  [FAIL] 临时表预演失败：{p.stderr.strip()[:300]}")
        return [f"临时表 DDL 预演失败：{p.stderr.strip()[:200]}"]

    # 按 MARK 分段认领：SHOW INDEX 的每一行是 Table/Non_unique/Key_name/Seq_in_index/Column_name/…
    phase = "?"
    before_rows, after_rows, done = 0, [], False
    for line in p.stdout.splitlines():
        f = line.split("\t")
        if f[:2] == ["MARK", "before"]:
            phase = "before"
            continue
        if f[:2] == ["MARK", "after"]:
            phase = "after"
            continue
        if f[:2] == ["MARK", "done"]:
            done = True
            continue
        if not line.strip():
            continue
        if phase == "before":
            before_rows += 1
        elif phase == "after":
            # 列序：Seq_in_index（第 4 列）→ Column_name（第 5 列）
            if len(f) >= 5:
                after_rows.append((f[3], f[4]))
    after_rows.sort(key=lambda t: int(t[0]) if t[0].isdigit() else 99)

    if not done:
        fails.append("预演没有跑到最后（脚本可能在中间报错了）")
        print("  [FAIL] 预演没跑完")
    if before_rows != 0:
        fails.append(f"建之前守卫就返回了 {before_rows} 行（`Key_name` 过滤没生效）")
        print(f"  [FAIL] 建之前守卫返回 {before_rows} 行")
    else:
        print("  [OK]   `SHOW INDEX … WHERE Key_name = 'ix_orders_status_delivered'` 建之前是 0 行（守卫语义对）")
    order = [c for _, c in after_rows]
    if order == ["status", "delivered_at"]:
        print("  [OK]   `ALTER TABLE … ADD INDEX (status, delivered_at)` 成功，列序 status→delivered_at"
              "（等值列在前、范围列在后）")
    else:
        fails.append(f"索引建出来列序不对：{order}")
        print(f"  [FAIL] 索引列序不对：{order}")
    print(f"      · `status` 用的是 orders 的真实类型：{cols['status'][:120]}")
    print("      · 临时表已 DROP（会话级，本就没进过任何真实表）")
    fails += validate_enum_repair_on_temp_table()
    return fails


def validate_enum_repair_on_temp_table() -> list[str]:
    """把**生成出来的**枚举补全 DDL 拿真 MySQL 演一遍：新值写得进、老数据不丢。

    这是"枚举列自愈"那一整条链路的真机证据（本机是 SQLite，验不了）：
    临时表先造成**旧枚举**（少最后一个取值，模拟老库），塞一行已有数据，
    跑一句 `enum_repair_ddl(...)` **生成出来的** DDL（⛔ 不是手抄一份），然后：
    ① 列的定义里出现了全部取值；② 那一行老数据还在、值没变；③ 用**新增的那个取值**再插一行 ——
    这一步正是 2026-09-04 生产 500 的形状（写一个不在枚举里的值），能插进去才算真的修好了。
    """
    fails: list[str] = []
    try:
        sys.path.insert(0, str(BACKEND))
        import app.models  # noqa: F401
        from app.core.schema_bootstrap import enum_repair_ddl
        from app.models.order import Order

        col = Order.__table__.c.status
        values = [str(v) for v in col.type.enums]
    except Exception as e:
        print(f"  [FAIL] 取不到 `orders.status` 的枚举定义（{e}）—— 这一段没在查")
        return [f"取不到 orders.status 枚举：{e}"]

    old_values = values[:-1]
    new_value = values[-1]
    temp = "_dsh_enum_repair_check"
    ddl = enum_repair_ddl(temp, col)          # ← 生成器给的 DDL，原样拿去执行
    sql = (
        f"DROP TEMPORARY TABLE IF EXISTS {temp};\n"
        f"CREATE TEMPORARY TABLE {temp} (\n"
        f"  id INT NOT NULL PRIMARY KEY,\n"
        f"  status ENUM({','.join(chr(39) + v + chr(39) for v in old_values)}) NOT NULL\n"
        ");\n"
        f"INSERT INTO {temp} (id, status) VALUES (1, '{old_values[-1]}');\n"
        f"{ddl};\n"
        f"INSERT INTO {temp} (id, status) VALUES (2, '{new_value}');\n"
        "SELECT 'MARK', 'rows';\n"
        f"SELECT id, status FROM {temp} ORDER BY id;\n"
        "SELECT 'MARK', 'type';\n"
        # ⚠️ 临时表**不在 information_schema 里**（会话级，数据字典看不见）—— 只能 `SHOW COLUMNS`。
        f"SHOW COLUMNS FROM {temp} LIKE 'status';\n"
        f"DROP TEMPORARY TABLE {temp};\n"
        "SELECT 'MARK', 'done';\n"
    )
    # ⚠️ 与索引那段同理：这里也有 DDL（只作用于临时表），所以绕过只读自检 ——
    #    语句全部写死在上面这段里，不接收任何外部输入。
    p = subprocess.run(
        [*SSH_BASE, REMOTE_MYSQL],
        input=sql,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if p.returncode != 0:
        print(f"  [FAIL] 枚举补全预演失败：{p.stderr.strip()[:400]}")
        return [f"枚举补全 DDL 预演失败：{p.stderr.strip()[:200]}"]

    phase, kept, live_type, done = "?", None, None, False
    for line in p.stdout.splitlines():
        f = line.split("\t")
        if f[:2] == ["MARK", "rows"]:
            phase = "rows"
            continue
        if f[:2] == ["MARK", "type"]:
            phase = "type"
            continue
        if f[:2] == ["MARK", "done"]:
            done = True
            continue
        if not line.strip():
            continue
        if phase == "rows" and len(f) >= 2:
            if f[0] == "1":
                kept = f[1]                      # 老数据：值必须一字不变
            elif f[0] == "2":
                print(f"  [OK]   新增取值 `{new_value}` 能写进去了（这就是当年 500 的那一步）")
        elif phase == "type":
            # `SHOW COLUMNS` 的列：Field / Type / Null / Key / Default / Extra
            if len(f) >= 2 and f[0] == "status":
                live_type = f[1]

    if not done:
        fails.append("枚举补全预演没跑到最后（中间报错了）")
        print("  [FAIL] 预演没跑完")
    elif kept != old_values[-1]:
        fails.append(f"补全之后老数据变了：{kept!r} ≠ {old_values[-1]!r}")
        print(f"  [FAIL] 补全之后老数据变了：{kept!r}")
    else:
        print(f"  [OK]   补全之后老数据还在且值没变（status={kept!r}）")
    if live_type and all(f"'{v}'" in live_type for v in values):
        print(f"  [OK]   补全后的列定义含全部 {len(values)} 个取值")
    else:
        fails.append(f"补全之后的列定义不对：{live_type!r}")
        print(f"  [FAIL] 补全之后的列定义不对：{live_type!r}")
    print(f"      · 生成器给的 DDL：{ddl[:160]}")
    print("      · 临时表已 DROP（会话级，本就没进过任何真实表）")
    return fails


if __name__ == "__main__":
    raise SystemExit(main())
