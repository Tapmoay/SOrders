"""反向验证 `_tools/qa/_check_order_purge_fk.py`（指向 orders / order_products 的外键必须逐个交代）。

## 为什么必须做

这条判据守的事**坏了不会有任何报错**：漏解一个外键，`delete_orders_by_ids` 抛 IntegrityError，
而它被 `main._retention_sync` 吞成一行日志 + `rollback()` —— **当天的 3 年清理、消息清理、
图片归档、导出产物清理全部不执行，而且每天重复失败**。本机跑测试也不会发现，
因为测试语料里原来就没有"带退货申请/核销凭证的软删单"。

所以逐条注入真缺陷，每条都必须让判据报红；跑完逐字节还原并再验一次绿。

用法：python _tools/qa/_reverse_verify_order_purge_fk.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_order_purge_fk.py"
RETENTION = ROOT / "backend/app/services/data_retention.py"
MODELS = ROOT / "backend/app/models"

CASES: list[tuple[str, Path, object]] = [
    (
        "「不许删」的清单把核销凭证去掉（删单时外键必炸 → 当天治理全停）",
        RETENTION,
        lambda s: s.replace(
            "    for want in (OrderReturnRequest, ShipperSettlement):",
            "    for want in (OrderReturnRequest,):",
            1,
        ),
    ),
    (
        "「不许删」的清单把退货申请去掉（同一类炸法）",
        RETENTION,
        lambda s: s.replace(
            "    for want in (OrderReturnRequest, ShipperSettlement):",
            "    for want in (ShipperSettlement,):",
            1,
        ),
    ),
    (
        "子单那根 `parent_order_id` 不再置空（自引用外键，父单删不掉）",
        RETENTION,
        lambda s: s.replace(
            "    db.execute(\n        update(Order).where(Order.parent_order_id.in_(ids)).values(parent_order_id=None)\n    )",
            "    pass",
            1,
        ),
    ),
    (
        "`places.first_order_id` 不再置空（2026-09-19 R12 那个原始形状）",
        RETENTION,
        lambda s: s.replace(
            "    db.execute(\n        update(Place).where(Place.first_order_id.in_(ids)).values(first_order_id=None)\n    )",
            "    pass",
            1,
        ),
    ),
    (
        "有人新加了一张指着 orders 的表（`order_attachments`），清理没交代它",
        Path("__new_table__"),
        None,          # 见下面的特判：这条要同时改模型与 data_retention
    ),
    (
        "理由表里塞一个不存在的表（防化石失效）",
        CHECK,
        lambda s: s.replace(
            '    "shipper_settlements": (',
            '    "shipper_settlements_x": (\n        "不存在的表：这一行是注入用的化石。"\n    ),\n    "shipper_settlements": (',
            1,
        ),
    ),
    (
        "挡住那张表的函数被改成永远返回空（**行为**注入：静态判据看不出来，由单测抓）",
        RETENTION,
        lambda s: s.replace(
            "def _orders_with_blocking_docs(db: Session, ids: list[int]) -> list[int]:",
            "def _orders_with_blocking_docs(db: Session, ids: list[int]) -> list[int]:  # noqa\n    return []",
            1,
        ),
        "pytest",
    ),
    (
        "清理不再调用挡住清单（理由与函数都在，但没人用）",
        RETENTION,
        lambda s: s.replace("blocked = _orders_with_blocking_docs(db, ids)", "blocked = []", 1),
    ),
    (
        "外键清单盘空（判据变成空转）",
        MODELS / "order_return_request.py",
        lambda s: s.replace(
            'order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)',
            "order_id: Mapped[int] = mapped_column(index=True)",
            1,
        ),
    ),
]


def run(path: Path) -> int:
    p = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    return p.returncode


def run_pytest() -> tuple[int, str]:
    """跑那条**行为**判据（挡住清单真的生效、真的发站内信）。"""
    p = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_order_purge_foreign_keys.py", "-q",
         "--no-header", "-p", "no:cacheprovider"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT / "backend"),
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _inject_new_table() -> tuple[Path, str] | None:
    """特判：**新加一张指着 orders 的表**，清理里一个字都不提 → 判据必须报红。

    这条是"防未来"的那一条：真正会出的问题不是现在这几张表，而是下一个人加表时没人想起清理。
    """
    target = MODELS / "order_attachment.py"
    if target.exists():
        return None
    return target, (
        "\nfrom sqlalchemy import ForeignKey\n"
        "from sqlalchemy.orm import Mapped, mapped_column\n\n"
        "from app.models.base import Base, TimestampMixin\n\n\n"
        "class OrderAttachment(Base, TimestampMixin):\n"
        '    __tablename__ = "order_attachments"\n\n'
        "    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)\n"
        '    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)\n'
    )


def main() -> int:
    before = {str(c[1]): c[1].read_text(encoding="utf-8") for c in CASES if c[1].exists()}
    if run(CHECK) != 0:
        print("❌ 前提不成立：源码完好时这条判据就没过（先让它变绿）")
        return 1
    print("✅ 前提：源码完好时判据是绿的")

    fails: list[str] = []
    for case in CASES:
        label, path, mutate = case[0], case[1], case[2]
        judge = case[3] if len(case) > 3 else "check"
        if mutate is None:
            # 新加一张表的特判：加文件 + 让 `app.models` 认到它
            made = _inject_new_table()
            if made is None:
                fails.append(f"{label}：探针文件已存在，先删掉再跑")
                continue
            new_path, src = made
            init = MODELS / "__init__.py"
            init_bytes = init.read_bytes()  # R3-07b：快照取**字节**，还原才可能字节级
            init_src = init_bytes.decode("utf-8").replace(chr(13) + chr(10), chr(10))
            try:
                new_path.write_text(src, encoding="utf-8", newline="")
                init.write_text(
                    init_src.rstrip("\n") + "\nfrom app.models.order_attachment import OrderAttachment  # noqa: E402,F401\n",
                    encoding="utf-8",
                    newline="",
                )
                code = run(CHECK)
            finally:
                new_path.unlink(missing_ok=True)
                init.write_bytes(init_bytes)
            if code != 0:
                print(f"✅ 注入「{label}」→ 报红")
            else:
                fails.append(f"{label}：注入之后没有报红 —— 判据盯不住「新增的表」")
            continue

        original_bytes = path.read_bytes()

        original = original_bytes.decode("utf-8").replace(chr(13) + chr(10), chr(10))
        mutated = mutate(original)
        if mutated == original:
            fails.append(f"{label}：注入没生效（替换串过期了，请更新本脚本）")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            if judge == "pytest":
                code, out = run_pytest()
                import re as _re

                caught = bool(_re.search(r"\d+ failed", out))
            else:
                code, caught = run(CHECK), run(CHECK) != 0
        finally:
            path.write_bytes(original_bytes)
        if caught:
            print(f"✅ 注入「{label}」→ 报红（{'单测' if judge == 'pytest' else '红线'}）")
        else:
            fails.append(f"{label}：注入之后没有报红 —— 这一层判据是空转的")

    for k, v in before.items():
        if Path(k).read_text(encoding="utf-8") != v:
            fails.append(f"收尾没还原：{k}")
    if run(CHECK) != 0:
        fails.append("还原之后判据仍然红（有文件没被改回来）")

    if fails:
        print("\n❌ 反向验证没通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ {len(CASES)}/{len(CASES)} 种破坏方式全部被抓到，且源码已还原。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
