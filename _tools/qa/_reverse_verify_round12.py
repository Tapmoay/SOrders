"""反向验证：第十二轮那批修复的回归测试**真的会红**（2026-09-19）。

## 为什么必须逐条注入
这一轮修的都是"某个入口少了一道判断"这类缺陷（越权读、静默抹账、删掉还在用的文件…），
它们的**共同失效方式**是"看起来还在，但判断已经不生效了"：

| 注入 | 如果测试没牙会怎样 |
|---|---|
| 拿掉进价裁剪 | 货主/司机又能读到 `cost_price`，而界面上完全看不出来 |
| 撤回时不清覆盖值 | 新司机按**上一个司机**的数字算钱（账单上还印着"这一单单独定的"） |
| 报表改回累加 `freight_fee` | 营业纵览的"司机运费支出"重新虚高 90%+，两个页面都不报错 |
| 拿掉账本行的状态守卫 | 已送达的单又能从账本侧改钱 |
| 拿掉滚动收款的金额校验 | 收 1 元能把 1 万元的欠款整单抹掉 |
| 下载端点改回读 `download_url` | 每次下载 500（而这个属性根本不存在） |
| `verify_password` 去掉 try | 脏 hash 的账号登录 500 + 账号存在性预言机 |
| socket 握手不校验 `tv` | 登出后的旧令牌还能收推送 |
| 归档改回"改名 + 删原图" | 满 1 年后所有送达照片 404、且不可恢复 |
| 清理改回 `ids[:200]` | 第 201 张起的图片目录永久残留 |
| 作废账单不通知 | 司机的钱没了，界面上没有任何人看得见 |

用法：`python _tools/qa/_reverse_verify_round12.py`（全部达标 → 退出码 0）
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"

GUARDS = "tests/test_audit_round12_guards.py"
RETEN = "tests/test_audit_round12_retention.py"

#: (说明, 相对路径, 注入, 期望变红的测试)
CASES: list[tuple[str, str, object, str]] = [
    (
        "进价不再按角色裁剪（货主/司机又能读到成本）",
        "backend/app/api/v1/products.py",
        lambda s: s.replace(
            "    if not role_has_permission(role_key, Permission.PRODUCT_MANAGE):\n        out.cost_price = None\n",
            "",
            1,
        ),
        f"{GUARDS}::test_cost_price_only_visible_to_product_manager",
    ),
    (
        "撤回派单不再清逐单覆盖值（新司机按上一个司机的数字算钱）",
        "backend/app/services/order_flow.py",
        lambda s: s.replace(
            "            driver_piece_amount=None,\n            driver_commission_rate=None,\n", "", 1
        ),
        f"{GUARDS}::test_recall_clears_per_order_driver_amount",
    ),
    (
        "派单改回「没填就不改」（残留值跟着下一个司机走）",
        "backend/app/services/order_flow.py",
        lambda s: s.replace(
            "    order.driver_piece_amount = piece_override\n    order.driver_commission_rate = rate_override\n",
            "    if piece_override is not None:\n        order.driver_piece_amount = piece_override\n"
            "    if rate_override is not None:\n        order.driver_commission_rate = rate_override\n",
            1,
        ),
        f"{GUARDS}::test_assign_without_override_does_not_inherit_previous_value",
    ),
    (
        "报表的司机运费支出改回累加订单运费（虚高 90%）",
        # ⚠️ 2026-09-25：聚合下沉到 service 层 —— 注入要打在原文真正住着的文件上（否则静默 SKIP）
        "backend/app/services/reports_service.py",
        lambda s: s.replace(
            "        pay = pay_for_order(o).total if has_per_order_pay(o) else Decimal(\"0\")",
            "        pay = o.freight_fee or Decimal(\"0\")",
            1,
        ),
        f"{GUARDS}::test_turnover_driver_freight_matches_settlement",
    ),
    (
        "账本行不再看订单状态（已送达的单又能从账本侧改钱/删行）",
        "backend/app/api/v1/ledger.py",
        lambda s: s.replace(
            "    _reject_if_order_closed(db, row, wants_detail=wants_detail, what=\"改这一行的商品与金额\")\n",
            "",
            1,
        ),
        f"{GUARDS}::test_delivered_order_ledger_row_cannot_be_edited_or_deleted",
    ),
    (
        "滚动收款绑单时不再校验金额（收 1 元抹掉 1 万欠款）",
        "backend/app/services/accounting_service.py",
        lambda s: s.replace(
            "        total = sum(per_order.values(), Decimal(\"0\"))\n"
            "        if Decimal(body.amount) != total:\n"
            "            raise ValueError(\n"
            "                f\"收款金额 {body.amount} 与所选订单合计 {total} 不一致。\"\n"
            '                "绑了订单就必须逐单对得上；如果只是先收一笔钱（以后再说冲哪几张单），"\n'
            '                "请把订单留空，用滚动收款。"\n'
            "            )\n",
            "",
            1,
        ),
        f"{GUARDS}::test_rolling_receipt_with_orders_requires_matching_amount",
    ),
    (
        "下载端点改回读那个不存在的属性（每次下载 500）",
        "backend/app/api/v1/ledger.py",
        lambda s: s.replace('    stored = job.file_path or ""', '    stored = job.download_url or ""', 1),
        f"{GUARDS}::test_export_download_returns_the_file",
    ),
    (
        "口令校验不再兜异常（脏 hash 的账号登录 500）",
        "backend/app/core/security.py",
        lambda s: s.replace(
            "    try:\n        return pwd_context.verify(plain, hashed)\n"
            "    except Exception:  # noqa: BLE001 - 脏哈希/未知算法/空值一律按\"不对\"处理\n"
            "        return False\n",
            "    return pwd_context.verify(plain, hashed)\n",
            1,
        ),
        f"{RETEN}::test_dirty_password_hash_logs_in_as_401_not_500",
    ),
    (
        "长连接握手不再校验 token_version（登出后旧令牌还能收推送）",
        "backend/app/core/socket_io.py",
        lambda s: s.replace(
            "        if int(payload.get(\"tv\", 0) or 0) != int(getattr(user, \"token_version\", 0) or 0):\n"
            "            return None\n",
            "",
            1,
        ),
        f"{RETEN}::test_socket_connect_rejects_revoked_token",
    ),
    (
        "图片归档改回「另写一个文件 + 删原图」（满 1 年照片全 404）",
        "backend/app/services/image_archive.py",
        lambda s: s.replace(
            "        tmp.replace(src)\n        return src\n",
            "        dst = src.with_name(src.stem + \".compressed.webp\")\n"
            "        tmp.replace(dst)\n        src.unlink(missing_ok=True)\n        return dst\n",
            1,
        ),
        f"{RETEN}::test_archive_compresses_in_place_and_keeps_url_alive",
    ),
    (
        "图片目录清理改回只处理前 200 张",
        "backend/app/services/data_retention.py",
        lambda s: s.replace("    for oid in ids:\n", "    for oid in ids[:200]:\n", 1),
        f"{RETEN}::test_purge_removes_image_dirs_beyond_the_first_200",
    ),
    (
        "作废司机账单不再通知任何人（钱没了只有一行日志）",
        "backend/app/services/data_retention.py",
        lambda s: s.replace("        _notify_bills_cancelled(db, open_bills, total)\n", "", 1),
        f"{RETEN}::test_cancelled_driver_bills_notify_driver_and_dispatchers",
    ),
    (
        "逐单金额的上界判据被拿掉（1e20 又能落库）",
        "backend/app/services/driver_pay.py",
        # ⚠️ 锚点跟着实现走（2026-09-23 静态审计抓到它已腐烂）：那句提示语后来过了
        #    `money_text(MONEY_MAX)`（给人看的数字统一格式化），中间还插了一行注释。
        lambda s: s.replace(
            "    if money(piece_override) > MONEY_MAX:\n"
            "        # 给人看的那句话过 `money_text`（判据仍是上面那行 `money(...) > MONEY_MAX`，`Decimal`）。\n"
            "        return f\"这一单的司机金额不能超过 {money_text(MONEY_MAX)} 元（金钱字段的上限）\"\n",
            "",
            1,
        ),
        f"{RETEN}::test_per_order_piece_amount_has_upper_bound",
    ),
    (
        "报表改回按 UTC 日分桶（东八区当地 0~8 点的单算进前一天）",
        # ⚠️ 2026-09-25：聚合下沉到 service 层 —— 注入要打在原文真正住着的文件上（否则静默 SKIP）
        "backend/app/services/reports_service.py",
        lambda s: s.replace(
            "        ds = business_date(o.delivered_at)\n"
            "        if ds is None or ds < start or ds > end:\n"
            "            continue\n",
            "        ds = o.delivered_at.date()\n"
            "        if ds < start or ds > end:\n"
            "            continue\n",
            1,
        ),
        f"{GUARDS}::test_turnover_buckets_by_business_day_not_utc",
    ),
    (
        "结算页的 from/to 改回直接与 UTC 列比（当地 0~8 点的单看不到）",
        "backend/app/api/v1/freight_settlement.py",
        lambda s: s.replace(
            "    start = to_utc_naive(start)\n    end = to_utc_naive(end)\n",
            "",
            1,
        ),
        f"{GUARDS}::test_turnover_driver_freight_matches_settlement",
    ),
    # ---------------- 第十三轮 ----------------
    # （"司机送达不再看隔离区"那一条需要**同时**撤掉两层修复才算缺陷重现 ——
    #   单层注入时另一层仍然拒绝、测试照常通过，那证明不了判据没牙。见文件末尾的 MULTI。）
    (
        "账单月份改回 UTC 月（月初 8 小时的单记到上个月）",
        "backend/app/services/accounting_service.py",
        lambda s: s.replace(
            "    return business_local(d).strftime(\"%Y-%m\")",
            "    return d.strftime(\"%Y-%m\")",
            1,
        ),
        "tests/test_audit_round13_guards.py::test_bill_month_uses_business_local_month",
    ),
    (
        "月份上界被拿掉（又能造出未来月份的工资单）",
        "backend/app/schemas/accounting_v2.py",
        lambda s: s.replace(
            "    now_month = business_local(datetime.now(timezone.utc)).strftime(\"%Y-%m\")\n"
            "    if s > now_month:\n"
            "        raise ValueError(\n"
            "            f\"月份不能晚于本月（现在是 {now_month}）。{s} 还没到，\"\n"
            "            \"提前生成会造出一笔现在就能付款的应付，而且账单没有删除入口。\"\n"
            "        )\n",
            "",
            1,
        ),
        "tests/test_audit_round13_guards.py::test_future_month_rejected_for_bills_and_settlements",
    ),
    (
        "撤销数改回按 UTC 日筛（当地凌晨撤销的单算到前一天）",
        # ⚠️ 2026-09-25：聚合下沉到 service 层 —— 注入要打在原文真正住着的文件上（否则静默 SKIP）
        "backend/app/services/reports_service.py",
        lambda s: s.replace(
            "            Order.cancelled_at >= c_start,\n            Order.cancelled_at < c_end,\n",
            "            func.date(Order.cancelled_at) >= start,\n            func.date(Order.cancelled_at) <= end,\n",
            1,
        ),
        "tests/test_audit_round13_guards.py::test_turnover_cancelled_count_uses_business_day",
    ),
    (
        "日报小时桶改回 UTC 小时（当地凌晨标成下午）",
        # ⚠️ 2026-09-25：聚合下沉到 service 层 —— 注入要打在原文真正住着的文件上（否则静默 SKIP）
        "backend/app/services/reports_service.py",
        lambda s: s.replace(
            "        h = business_local(o.delivered_at).hour",
            "        h = o.delivered_at.hour",
            1,
        ),
        "tests/test_audit_round13_guards.py::test_turnover_hour_bucket_uses_business_hour",
    ),
    (
        "「挂账未收」又加上 payment_method 那一条（两处口径再次分叉）",
        # ⚠️ 2026-09-25：聚合下沉到 service 层 —— 注入要打在原文真正住着的文件上（否则静默 SKIP）
        "backend/app/services/reports_service.py",
        # ⚠️ 锚点跟着实现走（2026-09-23 静态审计抓到它已腐烂）：下面那句 `paid.is_(False)`
        #    后面多了"与 load_delivered 同一个窗口预过滤"的注释 + `*delivered_span_sql(...)`
        #    （2026-09-23 容量实测那一轮的加速改动）。
        #    这里只锚**那一行**（全库唯一）—— 注入要表达的是"多一条 payment_method 判据"，
        #    与它后面跟什么无关，把整段括号尾巴写进锚点只会让它跟着实现一起烂。
        lambda s: s.replace(
            "                Order.paid.is_(False),\n",
            "                Order.payment_method == \"arrears\",\n"
            "                Order.paid.is_(False),\n",
            1,
        ),
        "tests/test_audit_round13_guards.py::test_arrears_definitions_agree",
    ),
    (
        "导出金额改回字符串（Excel 求和不到钱）",
        # ⚠️ 2026-09-25：聚合下沉到 service 层 —— 注入要打在原文真正住着的文件上（否则静默 SKIP）
        "backend/app/services/reports_service.py",
        # ⚠️ 锚点跟着实现走（2026-09-19 第十八轮）：这一行现在显式写了
        #    `rounding=ROUND_HALF_UP`（F7：导出金额不许用银行家舍入）。
        lambda s: s.replace(
            '    return float(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))',
            "    return str(v)",
            1,
        ),
        "tests/test_audit_round13_guards.py::test_export_amounts_are_numbers",
    ),
    # ---- 第十四轮（消息 / 通知 / 导出 / 时间基准），2026-09-19 ----
    (
        "合并临时货主时又只改账本那一份名字（重新同步会把改名悄悄还原）",
        "backend/app/api/v1/customers.py",
        lambda s: s.replace(
            "            for o in moved_orders:\n                o.temp_shipper_name = new_name\n",
            "",
            1,
        ),
        "tests/test_audit_round15_guards.py::test_merge_renames_both_copies_and_survives_a_resync",
    ),
    (
        # 2026-09-20 更新锚点：截断的两个响应头已经收敛到 `core/pagination.py::finish_page`
        # （8 个列表端点共用），notifications.py 只剩一行 `finish_page(...)`。
        # 注入 = 那行改回手写切片（回不到"回报截断"），pytest 那条必须红。
        "列表截断不再回报（第 201 条以前的消息在 App 里没有入口）",
        "backend/app/api/v1/notifications.py",
        lambda s: s.replace(
            "    return finish_page(rows, limit, response)\n",
            "    return rows[:limit]\n",
            1,
        ),
        "tests/test_audit_round15_guards.py::test_notification_list_reports_truncation_and_honours_limit",
    ),
    (
        "消息列表的 days 又用进程本地时间（少给 8 小时）",
        "backend/app/api/v1/notifications.py",
        lambda s: s.replace(
            "    cutoff = utc_now_naive() - timedelta(days=days)",
            "    cutoff = datetime.now() - timedelta(days=days)",
            1,
        ),
        "tests/test_audit_round15_guards.py::test_days_cutoff_uses_the_utc_single_source",
    ),
    (
        "空 ids 的批量删又落到『删光』分支",
        "backend/app/api/v1/notifications.py",
        lambda s: s.replace(
            '    if not body.ids and not body.all:\n'
            '        raise HTTPException(status_code=400, detail="请指定要删除的消息（ids），或显式传 all=true 清空")\n',
            "",
            1,
        ),
        "tests/test_audit_round15_guards.py::test_batch_delete_with_empty_ids_is_rejected",
    ),
    (
        "表格解析又静默砍列（40 列以上不说出来）",
        "backend/app/services/sheet_parser.py",
        # ⚠️ **两条路径都要换**（xlsx 的 `_read_xlsx_sheet` 与 csv/txt 的 `_parse_text`）：
        #    只替换一处时另一处仍在，测试照样能命中 → 这条注入就变成了假绿
        #    （2026-09-19 实测：第一版锚了 20 空格缩进那一处，而测试走的是 8 空格那一处）。
        #    所以这里不带缩进，`str.replace` 默认替换**全部**出现。
        lambda s: s.replace(
            "truncated=truncated or dropped_cols > 0,",
            "truncated=truncated,",
        ),
        "tests/test_audit_round15_guards.py::test_sheet_parser_flags_column_truncation",
    ),
    (
        "SOCKET 回补又取最旧的 200 条（断线期间的消息永远补不到）",
        "backend/app/core/socket_io.py",
        lambda s: s.replace(
            "                .order_by(Notification.id.desc())\n",
            "                .order_by(Notification.id.asc())\n",
            1,
        ),
        "tests/test_audit_round15_guards.py::test_socket_sync_returns_the_newest_not_the_oldest",
    ),
    # ---- 第十六轮（库存与计数列的原子性），2026-09-19 ----
    (
        "送货扣库存改回读改写（两张单同时送达同一个商品 → 丢一次扣减）",
        "backend/app/services/inventory_service.py",
        lambda s: s.replace(
            "        db.execute(\n"
            "            update(Product)\n"
            "            .where(Product.id == m.product_id)\n"
            "            .values(stock=func.coalesce(Product.stock, 0) + m.change)\n"
            "        )\n",
            "        prod = db.get(Product, m.product_id)\n"
            "        if prod is not None:\n"
            "            prod.stock = (prod.stock or 0) + m.change\n",
            1,
        ),
        "tests/test_audit_round16_counters.py::test_delivery_deduction_does_not_clobber_a_concurrent_stock_change",
    ),
    (
        "手工出库改回『读→算→判→写回绝对值』（库存不足拦不住）",
        "backend/app/api/v1/inventory.py",
        lambda s: s.replace(
            "    res = db.execute(\n"
            "        update(Product)\n"
            "        .where(\n"
            "            Product.id == body.product_id,\n"
            "            func.coalesce(Product.stock, 0) + body.change >= 0,\n"
            "        )\n"
            "        .values(stock=func.coalesce(Product.stock, 0) + body.change)\n"
            "    )\n",
            "    new_stock = (product.stock or 0) + body.change\n"
            "    if new_stock < 0:\n"
            '        raise HTTPException(status_code=400, detail="库存不足")\n'
            "    product.stock = new_stock\n"
            '    res = type("R", (), {"rowcount": 1})()\n',
            1,
        ),
        "tests/test_audit_round16_counters.py::test_manual_outflow_guard_is_atomic_not_check_then_act",
    ),
]


def run_test(node: str) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, "-m", "pytest", node, "-q", "--no-header", "-p", "no:cacheprovider"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(BACKEND),
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


#: 需要**同时撤掉多层修复**才算"缺陷重现"的那一条。
#: 单层注入时另一层仍然拒绝，测试照常通过 —— 那证明不了判据没牙，只证明还有一层。
MULTI = [
    (
        "司机送达不再看隔离区（已删除的单又能在谁都看不见的情况下送达）",
        [
            (
                # ⚠️ 2026-09-25 第 21 轮：司机送达那一族已随阶段 4 从 orders.py 搬到 orders_delivery.py
                #    （`complete_order`）—— 锚点不跟着走，这条注入就**恒 SKIP**（反向验证实测报出）。
                "backend/app/api/v1/orders_delivery.py",
                lambda s: s.replace(
                    "    order = _order_not_deleted_or_404(\n"
                    "        db.scalars(select(Order).options(selectinload(Order.order_products)).where(Order.id == order_id)).first()\n"
                    "    )\n",
                    "    order = db.scalars(\n"
                    "        select(Order).options(selectinload(Order.order_products)).where(Order.id == order_id)\n"
                    "    ).first()\n",
                    1,
                ),
            ),
            (
                "backend/app/services/order_flow.py",
                lambda s: s.replace(
                    "    if order.deleted_at is not None:\n"
                    "        raise ValueError(\"这一单已经被删掉了（在回收站里），不能送达。请让派单员确认这一单的归属。\")\n",
                    "",
                    1,
                ).replace(
                    "            Order.status == OrderStatus.ACCEPTED,\n"
                    "            # 同上：CAS 里也要带这一条，否则\"判完到写之间被删掉\"仍会落成一张看不见的已送达单\n"
                    "            Order.deleted_at.is_(None),\n",
                    "            Order.status == OrderStatus.ACCEPTED,\n",
                    1,
                ),
            ),
        ],
        "tests/test_audit_round13_guards.py::test_driver_cannot_complete_a_deleted_order",
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
    """读成 LF 文本 + 记住原来的换行风格（仓库里 `api/v1/inventory.py` 是 CRLF）。"""
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def _write_src(p: Path, text: str, crlf: bool) -> None:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    p.write_bytes(data.encode("utf-8"))


def main() -> int:
    fails: list[str] = []
    total = 0
    # ⚠️ 跑之前先把**所有会被碰到的文件**的字节快照拍下来，跑完逐个对：
    #    注入是"改文件→跑测试→写回"，任何一次写回出错（或中途被 Ctrl+C / 超时打断）
    #    都会把**源码留在被注入的状态**——实测踩到过一次：`order_flow.py` 里那条
    #    `deleted_at` 守卫被抹掉而没人发现（下一次跑这条判据时表现为"锚点找不到"）。
    touched: set[Path] = set()
    for label, rel, mutate, node in CASES:
        if rel is not None:
            touched.add(ROOT / rel)
    for _label, targets, _node in MULTI:
        for rel, _m in targets:
            touched.add(ROOT / rel)
    snapshot = {p: p.read_bytes() for p in touched if p.exists()}

    for label, rel, mutate, node in CASES:
        if rel is None:  # 占位项，真正的注入在 MULTI 里
            continue
        total += 1
        path = ROOT / rel
        # ⚠️ 按 LF 文本注入、**按原换行风格写回**（2026-09-19 实测踩到）：
        #    仓库里有 CRLF 文件（`api/v1/inventory.py`），脚本里的多行锚点写的是 `\n`，
        #    既会匹配不上（注入静默不生效），文本往返还会把整个文件改成 LF
        #    （收尾的字节比对于是报"没还原"，而其实只是换行符变了）。
        original_bytes = snapshot.get(path)
        original = (
            original_bytes.decode("utf-8") if original_bytes is not None else path.read_text(encoding="utf-8")
        )
        crlf = "\r\n" in original
        plain = original.replace("\r\n", "\n")
        mutated = mutate(plain)
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label} —— 锚点没找到")
            continue
        try:
            _write_src(path, mutated, crlf)
            code, out = run_test(node)
        finally:
            _write_src(path, plain, crlf)

        if code != 0:
            print(f"  [OK] {label} → 对应的测试报红")
        else:
            fails.append(f"{label}：注入之后测试**仍然通过**（判据没牙）")
            print(f"  [MISS] {label} → 测试照常通过")

    # ---- 需要同时撤掉多层修复的那些 ----
    for label, targets, node in MULTI:
        total += 1
        originals: list[tuple[Path, str, bool]] = []
        skip = False
        for rel, mutate in targets:
            path = ROOT / rel
            src, crlf = read_src(path)
            mutated = mutate(src)
            if mutated == src:
                print(f"  [SKIP] {label} —— 锚点没找到：{rel}")
                skip = True
                break
            originals.append((path, src, crlf))
            _write_src(path, mutated, crlf)
        if skip:
            for path, src, crlf in originals:
                _write_src(path, src, crlf)
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            continue
        try:
            code, out = run_test(node)
        finally:
            for path, src, crlf in originals:
                _write_src(path, src, crlf)
        if code != 0:
            print(f"  [OK] {label} → 对应的测试报红（同时撤掉了 {len(targets)} 层修复）")
        else:
            fails.append(f"{label}：注入之后测试**仍然通过**（判据没牙）")
            print(f"  [MISS] {label} → 测试照常通过")

    print()
    # ---- 收尾：源码必须**逐字节**回到跑之前的样子 ----
    dirty = [str(p.relative_to(ROOT)) for p, data in snapshot.items() if p.read_bytes() != data]
    if dirty:
        fails.append("跑完反向验证后源码没还原（这些文件与运行前不一致）：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(snapshot)} 个文件与运行前逐字节一致")

    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {total} 条注入都证明：这些回归测试真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
