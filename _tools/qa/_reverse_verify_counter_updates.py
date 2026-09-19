"""反向验证「计数列只能由数据库自增」这条红线**真的会红**（2026-09-19 审计）。

## 为什么这条要反向验证
它的判据要同时做到两件相反的事，很容易只做到一半：
- **要抓**：`obj.col = ... obj.col ...` 这种读改写（并发下 last-write-wins）；
- **不许误抓**：文本列的拼接/改名（`u.name = del_suffix(u.name)`、
  `notes = (notes or "") + "…"`）是另一码事 —— 一起报出来的话白名单会膨胀到十几条，
  判据就废了（"允许的例外比规则还多"＝没有规则）。

所以每一类注入都要单独证明：真 bug 的形状**红**、不是 bug 的形状**绿**。

## 七条注入
| 注入 | 期望 | 证明的是 |
|---|---|---|
| `auto_stock_commit` 改回读改写 | 红 | 库存送货扣减这一处 |
| 手工出库改回"读→算→判→写回绝对值" | 红 | **中间变量**形状（读改写正则抓不到它，靠 stock 赋值条款） |
| `place_user_usage.use_count` 改回读改写 | 红 | 计数列 |
| `places.use_count` 改回读改写 | 红 | 计数列（第二处） |
| 在**文本**列上写读改写 | **绿** | 判据按列类型过滤（不误抓） |
| 在 `quantity`（注解式声明、没写 Integer）上写读改写 | 红 | 模型解析认两种声明写法 |
| 把模型目录指错 | 红 | 数值列清单解析失效时必须喊，而不是静默变宽 |

⚠️ 快照/还原按**字节**做，跑完逐字节核对。

用法：python _tools/qa/_reverse_verify_counter_updates.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_counter_updates.py"

INV_SVC = "backend/app/services/inventory_service.py"
INV_API = "backend/app/api/v1/inventory.py"
PLACE = "backend/app/services/place_service.py"
ORDERS = "backend/app/api/v1/orders.py"
CHECKREL = "_tools/qa/_check_counter_updates.py"

#: (说明, 相对路径, 注入, 期望是否报红)
CASES: list[tuple[str, str, object, bool]] = [
    (
        "送货扣库存改回读改写（两张单同时送达同一个商品 → 丢一次扣减）",
        INV_SVC,
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
        True,
    ),
    (
        "手工出库改回『读→算→判→写回绝对值』（库存不足拦不住 + 覆盖并发扣减）",
        INV_API,
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
            "        raise HTTPException(status_code=400, detail=\"库存不足\")\n"
            "    product.stock = new_stock\n"
            "    res = type(\"R\", (), {\"rowcount\": 1})()\n",
            1,
        ),
        True,
    ),
    (
        "个人使用次数改回读改写（常用地点永远差一次才自动进库）",
        PLACE,
        lambda s: s.replace(
            "        db.execute(\n"
            "            update(PlaceUserUsage)\n"
            "            .where(PlaceUserUsage.id == row.id)\n"
            "            .values(use_count=func.coalesce(PlaceUserUsage.use_count, 0) + 1, last_used_at=now)\n"
            "        )\n"
            "        db.refresh(row)\n",
            "        row.use_count = (row.use_count or 0) + 1\n"
            "        row.last_used_at = now\n",
            1,
        ),
        True,
    ),
    (
        "共享地点总次数改回读改写（列表排序用的计数）",
        PLACE,
        lambda s: s.replace(
            "        db.execute(\n"
            "            update(Place)\n"
            "            .where(Place.id == existing.id)\n"
            "            .values(use_count=func.coalesce(Place.use_count, 0) + 1, last_used_at=now)\n"
            "        )\n"
            "        db.refresh(existing)\n",
            "        existing.use_count = (existing.use_count or 0) + 1\n"
            "        existing.last_used_at = now\n",
            1,
        ),
        True,
    ),
    (
        "文本列上的『读改写』**不许**被误抓（拼接备注不是计数）",
        ORDERS,
        lambda s: s.replace(
            '    order.internal_notes = (order.internal_notes or "").strip()\n',
            '    order.internal_notes = (order.internal_notes or "探针").strip()\n',
            1,
        ),
        False,
    ),
    (
        "注解式声明的数值列（quantity）上写读改写也要红",
        "backend/app/api/v1/order_products.py",
        lambda s: s.replace(
            "def _resync_stock_if_assigned(db: Session, order: Order, operator_id: int) -> int:",
            "def _resync_stock_if_assigned(db: Session, order: Order, operator_id: int) -> int:\n"
            "    _op = (order.order_products or [None])[0]\n"
            "    if _op is not None:\n"
            "        _op.quantity = (_op.quantity or 0) + 0  # 注入：读改写\n",
            1,
        ),
        True,
    ),
    (
        "模型目录指错（数值列清单解析失效 → 判据静默变宽）",
        CHECKREL,
        lambda s: s.replace('MODELS = BACKEND / "models"', 'MODELS = BACKEND / "models/nope"', 1),
        True,
    ),
]


def run_check(target: Path | None = None) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(target or CHECK)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def read_src(p: Path) -> tuple[str, bool]:
    """读成 LF 文本 + 记住原来的换行风格。

    ⚠️ 必须做这一步：仓库里有的文件是 **CRLF**（`api/v1/inventory.py` 就是），
    脚本里的多行锚点写的是 `\\n` → 在 CRLF 文件上**永远匹配不上**，
    表现为 `[SKIP] 注入没生效`（2026-09-19 实测：第一版就是这么漏掉那条注入的）。
    """
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> None:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    p.write_bytes(data.encode("utf-8"))


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({rel for _l, rel, _m, _e in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}
    crlfs = {rel: b"\r\n" in originals[rel] for rel in touched}

    for label, rel, mutate, want_red in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        plain = original_bytes.decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        tmp: Path | None = None
        try:
            if rel == CHECKREL:
                tmp = path.with_suffix(".py.injected")
                write_src(tmp, mutated, crlfs[rel])
                code, out = run_check(tmp)
            else:
                write_src(path, mutated, crlfs[rel])
                code, out = run_check()
        finally:
            if tmp is not None and tmp.exists():
                tmp.unlink()
            path.write_bytes(original_bytes)
        red = code != 0
        if red == want_red:
            print(f"  [OK] {label} → {'报红' if red else '保持全绿'}")
        else:
            fails.append(
                f"{label}：期望{'报红' if want_red else '全绿'}，实际{'报红' if red else '全绿'}（判据没牙/误抓）"
            )
            print(f"  [MISS] {label} → 实际{'报红' if red else '全绿'}")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查（含 1 条『不许误抓』）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
