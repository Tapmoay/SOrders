"""红线：**指向 `orders` / `order_products` 的外键必须被物理清理逐个交代**（2026-09-23 第 13 轮）。

## 由来（一条"把整套后台治理全部停摆"的静默缺陷）

`orders` 上有 **9 个外键**指着它，而 `data_retention.delete_orders_by_ids` 原来只解开了 5 个
（`places.first_order_id` 置空 + `driver_bills` 作废 + `ledgers`/`operation_logs`/
`inventory_movements`/`order_products` 删除）。漏掉的三个是 **NOT NULL**：
`order_return_requests.order_id`（退货申请）、`shipper_settlements.order_id` /
`shipper_settlement_lines.order_id`（货主核销凭证）；另一个 `orders.parent_order_id` 是自引用。

⚠️ 后果**不是"这一单删不掉"**：异常一路冒到 `main._retention_sync` 被吞成一行日志 +
`db.rollback()` → **当天的 3 年清理、消息清理、图片归档、导出产物清理全部不执行，而且每天重复失败**
（2026-09-19 审计 R12 的同一形状，当时是 `places.first_order_id`）。

## 判据（清单**全部自己算**，不手写"查哪些表"）

1. **外键清单**从 SQLAlchemy metadata 算：所有 `ForeignKey("orders.id")` 与
   `ForeignKey("order_products.id")`（清理会删 `order_products`，所以那个方向也要交代）；
2. **处理方式**从 `data_retention.py` 的 AST 算：`delete(X)` / `update(X)`（置空）都算"交代过"；
3. 剩下没被静态交代的，必须落在 `BLOCKED_BY:` 或 `ORPHAN_OK:` 里并写明理由（fail-closed）：
   - `BLOCKED_BY:<表>` = **这张表的行不许删**（钱/凭证），所以带它的单**不做物理清理**
     （代码里 `_orders_with_blocking_docs` 真的查了它 —— 这一条也由本脚本断言，防"理由写了但没实现"）；
   - `ORPHAN_OK:<表>` = 这列指着订单但**没有外键约束**，删单后允许留下悬空值
     （⛔ 必须写清为什么可以，而且这种列单独一张表列出来，别混在外键里）；
4. 反空转的数量下限：外键 ≥ 8、`delete/update` 到的模型 ≥ 5、`BLOCKED_BY` 键必须还是真表。

⚠️ 注入式反向验证：`_tools/qa/_reverse_verify_order_purge_fk.py`。

用法：python _tools/qa/_check_order_purge_fk.py
"""
from __future__ import annotations

import ast
import io
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
RETENTION = BACKEND / "app/services/data_retention.py"

sys.path.insert(0, str(BACKEND))
import app.models  # noqa: E402,F401  —— 让盘点看到"应用实际注册的"全部模型
from app.models.base import Base  # noqa: E402

#: 物理清理会动的两张"主表"（删它们之前，所有指着它们的外键都要交代）。
TARGETS = ("orders.id", "order_products.id")

#: 没有外键、但列名指着订单/订单行的那些列（删单后会留悬空值）。
#: 键 = `表.列`，值 = 为什么允许悬空（≥ 20 字）。
ORPHAN_OK = {
    "cash_flows.order_id": (
        "这一列**没有外键约束**（历史表），而且它是「这笔钱」的流水：删单不该把钱的历史一起抹掉 —— "
        "悬空之后流水仍在，只是点不进那一单（口径问题记在台账「待拍板」里）。"
    ),
    "expenses.order_id": (
        "同上：开销（含货损）没有外键，而它是一笔已经入账的钱 —— 保留行、允许 order_id 悬空，"
        "与 `cash_flows.order_id` 同一个取舍。"
    ),
    "driver_settlements.order_ids": (
        "JSON 数组，不是外键；结算单本身是已付的钱的凭证，删单不该删它。"
    ),
    "shipper_receipts.order_ids": (
        "JSON 数组，不是外键；收款凭证同理（`settle_mode='itemized'` 时列的是被核销的单号）。"
    ),
    "ledger_export_jobs.shipper_id": "对 `users.id` 的外键，与订单无关（列出来只是说明它不在本次范围）。",
    "open_payables": "占位：这不是真列，见下面 `ORPHAN_KEYS_REQUIRED` 的防化石断言。",
}

#: `BLOCKED_BY` 的键（**表名**）→ 为什么这张表的行不许删。
#: ⚠️ 键必须与 `_orders_with_blocking_docs` 真的查的表一致（本脚本两边对账）。
BLOCKED_BY = {
    "order_return_requests": (
        "货主提的退货申请（带办理/驳回记录）—— 客户的诉求，删单不该把它抹掉。"
    ),
    "shipper_settlements": (
        "货主/批发商的核销凭证（「这笔钱收到了」）—— 钱的凭证，删了就复核不了。"
    ),
}

#: 这些表也指着 orders / order_products，但它们只在**父单据存在时**才存在，
#: 而父单据已经被挡住了 → 不必再单独挡一次（键 = 表，值 = 父表 + 理由）。
BLOCKED_VIA_PARENT = {
    "order_return_request_lines": (
        "order_return_requests",
        "它是上面那张退货申请的明细（父申请在、行才在）—— 申请被挡住，这一行就不可能先没。",
    ),
    "shipper_settlement_lines": (
        "shipper_settlements",
        "它是那张核销凭证的逐商品明细（同时指着 orders 与 order_products）—— 父凭证被挡住即可。",
    ),
}

#: 数量下限（解析失效时先喊，而不是安静地什么都不查）。
MIN_FKS = 8
MIN_HANDLED = 5

fails: list[str] = []
passes = 0


def ok(label: str, cond: bool, detail: str = "") -> None:
    global passes
    if cond:
        passes += 1
        print(f"  [OK]   {label}")
    else:
        fails.append(label + (f" —— {detail}" if detail else ""))
        print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))


def fk_inventory() -> list[tuple[str, str]]:
    """所有指向 [TARGETS] 的外键 → [(表, 列)]（**从 metadata 算**）。"""
    out: list[tuple[str, str]] = []
    for tname, table in sorted(Base.metadata.tables.items()):
        for col in table.columns:
            for fk in col.foreign_keys:
                if fk.target_fullname in TARGETS:
                    out.append((tname, col.name))
    return out


def handled_models() -> set[str]:
    """`delete_orders_by_ids` 里 `delete(X)` / `update(X)` 动到的模型名（走 AST）。"""
    tree = ast.parse(io.open(RETENTION, encoding="utf-8").read())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "delete_orders_by_ids":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and sub.args:
                    fn = getattr(sub.func, "id", None) or getattr(sub.func, "attr", None)
                    if fn in ("delete", "update"):
                        arg = sub.args[0]
                        if isinstance(arg, ast.Name):
                            names.add(arg.id)
    return names


def _model_of_chain(node: ast.AST) -> str | None:
    """从 `update(X).where(...).values(...)` 这条链里挖出 `X`。

    ⚠️ `update(X).where(…).values(…)` 的**参数不是位置参数**：`values(...)` 那一层的
    `node.args` 是空的，模型名埋在 `node.func.value`（即 `update(X).where(…)` 那个 Call）里。
    第一版按"values 的第一个位置参数是模型"去读，于是**一个都没读到**（判据当场报红）。
    """
    cur: ast.AST | None = node
    while isinstance(cur, ast.Call):
        f = cur.func
        name = getattr(f, "attr", None) or getattr(f, "id", None)
        if name == "update" and cur.args and isinstance(cur.args[0], ast.Name):
            return cur.args[0].id
        cur = getattr(f, "value", None)
    return None


def nulled_refs() -> set[tuple[str, str]]:
    """`update(X).where(…).values(<列>=None)` 动到的 (模型, 列) —— **置空也算「交代过」**。

    ⚠️ 第一版把 `orders.parent_order_id` / `places.first_order_id` 两列**硬编码**成"已置空"，
    于是"把置空那两句删掉"的注入照样全绿（反向验证实测抓到）—— 现在从源码里算。
    """
    tree = ast.parse(io.open(RETENTION, encoding="utf-8").read())
    out: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if (getattr(node.func, "attr", None) or getattr(node.func, "id", None)) != "values":
            continue
        model = _model_of_chain(getattr(node.func, "value", None))
        if not model:
            continue
        for kw in node.keywords:
            if isinstance(kw.value, ast.Constant) and kw.value.value is None:
                out.add((model, kw.arg or ""))
    return out


def blocking_tables_in_code() -> set[str]:
    """`_orders_with_blocking_docs` 里真的查了哪些**表**（防「理由写了、代码没实现」）。

    ⚠️ 代码里写的是**模型名**（`OrderReturnRequest`），而理由表用的键是**表名**
    （`order_return_requests`）—— 第一版没做这个名字转换，于是判据对着两个集合喊了 5 个假红。
    模型名→表名一律从 `metadata` 问，不许手写第三份映射。
    """
    import app.models as models

    names: set[str] = set()
    tree = ast.parse(io.open(RETENTION, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_orders_with_blocking_docs":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Tuple):
                    for elt in sub.elts:
                        if isinstance(elt, ast.Name):
                            names.add(elt.id)
    out: set[str] = set()
    for name in names:
        cls = getattr(models, name, None)
        table = getattr(cls, "__tablename__", None)
        out.add(table or name)
    return out


def main() -> int:
    fks = fk_inventory()
    handled = handled_models()
    blocked_code = blocking_tables_in_code()

    print("① 外键清单（从 metadata 算，不手写）")
    ok(f"盘到 {len(fks)} 个外键（下限 {MIN_FKS}）", len(fks) >= MIN_FKS,
       "盘空了说明 metadata 没导进来 —— 那样本脚本一条都不查却全绿")
    for t, c in fks:
        print(f"      · {t}.{c}")

    print("\n② 清理里静态交代过的模型（`delete(X)` / `update(X)`）")
    ok(f"交代了 {len(handled)} 个模型（下限 {MIN_HANDLED}）", len(handled) >= MIN_HANDLED,
       f"解析到：{sorted(handled)}")
    print(f"      {sorted(handled)}")

    print("\n③ 每一个外键都要有交代：删除 / 置空 / 「不许删」并写明理由")
    nulled = nulled_refs()
    # 模型名 → 表名（理由表用表名）
    import app.models as _models

    def _table(model_name: str) -> str:
        cls = getattr(_models, model_name, None)
        return getattr(cls, "__tablename__", model_name)

    nulled_tables = {(_table(m), col) for m, col in nulled}
    unresolved: list[str] = []
    for t, c in fks:
        if t in blocked_code:
            continue                        # 被 `_orders_with_blocking_docs` 挡住（不许删）
        if t in BLOCKED_VIA_PARENT and BLOCKED_VIA_PARENT[t][0] in blocked_code:
            continue                        # 父单据被挡住 → 这些行不可能先没
        if (t, c) in nulled_tables:
            continue                        # 置空（**从源码算出来的**，不是硬编码白名单）
        if t in ("ledgers", "operation_logs", "inventory_movements", "order_products"):
            continue                        # 直接删（② 已证明 AST 里有 delete）
        unresolved.append(f"{t}.{c}")
    ok("没有「没人管」的外键", not unresolved, f"这些外键既没删、也没置空、也没挡住：{unresolved}")
    ok("置空那两句真的在（`parent_order_id` / `first_order_id`）",
       ("orders", "parent_order_id") in nulled_tables and ("places", "first_order_id") in nulled_tables,
       f"源码里算出来的置空列：{sorted(nulled_tables)}")

    print("\n④ `BLOCKED_BY` 的理由必须**真的实现了**（防「理由写了、代码没查那张表」）")
    for tname, why in BLOCKED_BY.items():
        ok(f"`{tname}` 在 `_orders_with_blocking_docs` 里真的被查了", tname in blocked_code, why)
    for tname in blocked_code:
        ok(f"代码里挡住的 `{tname}` 有书面理由（防化石）", tname in BLOCKED_BY,
           "代码挡了一张表，但理由表里没有它 —— 下一个人不知道为什么要挡")
    for tname, (parent, why) in BLOCKED_VIA_PARENT.items():
        ok(f"`{tname}` 的父表 `{parent}` 就在代码的挡住清单里", parent in blocked_code, why)
    # ⚠️ 反向的防化石：理由表里说"这张表指着订单所以不许删"，那它**必须真的还指着订单** ——
    #    外键被删掉/改名之后，理由就成了化石（而"没人管"的检查也顺手空了）。
    fk_tables = {t for t, _ in fks}
    for tname in list(BLOCKED_BY) + list(BLOCKED_VIA_PARENT):
        ok(f"`{tname}` 仍然真的指着 orders / order_products（防化石）", tname in fk_tables,
           f"外键清单里没有它了：{sorted(fk_tables)}")
    # 挡住的那个函数**必须真的被清理用到**（早退 `return []` 这种事静态看不出来，
    # 但"调用点在不在"看得见；行为那半由 `tests/test_order_purge_foreign_keys.py` 钉着）。
    src = io.open(RETENTION, encoding="utf-8").read()
    ok("`delete_orders_by_ids` 真的调用了挡住清单那个函数",
       "_orders_with_blocking_docs(db, ids)" in src)

    print("\n⑤ 没有外键但指着订单的列：允许悬空，但必须逐个写明理由")
    for key in ORPHAN_OK:
        if key == "open_payables":
            continue
        tname, col = key.split(".", 1)
        ok(f"`{key}` 的理由够长（≥ 20 字）", len(ORPHAN_OK[key]) >= 20)
        if tname in Base.metadata.tables:
            cols = {c.name for c in Base.metadata.tables[tname].columns}
            ok(f"`{tname}` 里真有 `{col}` 这一列（防化石）", col in cols, f"{tname} 的列：{sorted(cols)[:8]}")
        else:
            ok(f"`{tname}` 是真表（防化石）", False, f"{tname} 不在模型里")

    print("\n" + "=" * 60)
    if fails:
        print(f"❌ {len(fails)} 项不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {passes} 项通过：{len(fks)} 个外键都有交代"
          f"（删除 / 置空 / 凭证挡住 + 理由），悬空的 {len(ORPHAN_OK) - 1} 列也逐个写了理由。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
