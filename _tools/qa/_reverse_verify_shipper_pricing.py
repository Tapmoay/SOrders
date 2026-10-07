"""反向验证：把「下游定价」（CHG-0077 / 台账 L-38）的每一条红线**弄坏一次**，看判据抓不抓得住。

## 为什么这一块必须反向验证

这一层价的坏法有个共同点：**当场看不出来**。三个金额（订单口径 / 他自己的口径 / 价目表）
在界面上长得都像"这一单该收多少"，改错一处时接口照样 200、页面照样有数 ——
只有老单的金额悄悄换了口径。所以每条坏法都要有一件东西**当得住**：

| 坏法（本次真的注进去过） | 谁抓得住 | 为什么 |
| --- | --- | --- |
| 下游应收改成读订单行单价（`line_unit_price`） | 单测① | 老单 / 新单都变成订单口径，两个数当场不同（24 vs 30） |
| 快照每次覆盖（去掉"只填 NULL"那句） | 单测③ | 再定格一次就把 8 改成 12，历史被追改 |
| 删掉"联系人是不是他自己的"那道闸门 | 单测⑦ | 别人的客户也能定价 ⇒ 钱挂到别人名册上 |
| 摘掉「管下游的账」那道闸门（L-39） | 单测⑥ | 关了开关照样写 ⇒ 界面藏起来的东西不是"关掉" |
| 单价 `gt=0` 拿掉 | 单测⑦ | 0 元的价目表行看着像"设过了"，实际等于白送 |
| 权限点常量换成派单员那一档 | 判据⑤ | 三处登记逐字对不上（rbac / 能力表 / 审计覆盖） |
| 028 迁移加 `DEFAULT 0` | 判据① | "当时没有价"与"当时价格是 0"分不开 |
| 定位表那一行不再提这层价 | 判据⑦ | 改这一块的人找不到判据与红线 |

⚠️ 判据与单测**都必须是绿的**才开跑（前提），否则每一条都会"抓到"，
这份报告就变成了自欺（第二遍注入没修好、第一遍的红还留着）。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

#: 不 import _airepo 时，GBK 控制台下打第一个 ✅ 就 UnicodeEncodeError。
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # pragma: no cover - 老解释器没有 reconfigure
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_shipper_pricing.py"
TEST = "tests/test_shipper_pricing.py"

BACKEND = ROOT / "backend"
ORDER_MONEY = BACKEND / "app/services/order_money.py"
PRICE_SVC = BACKEND / "app/services/shipper_price.py"
PRICE_API = BACKEND / "app/api/v1/shipper_prices.py"
PRICE_SCHEMA = BACKEND / "app/schemas/shipper_price.py"
RBAC = BACKEND / "app/core/rbac.py"
MIG28 = BACKEND / "app/migrations/028_order_product_shipper_price.py"
LOCATOR = ROOT / "docs/PROJECT_MAP/08_CODE_LOCATOR.md"

#: (说明, 文件, 原文, 换成, 期望红掉的那条，判法)
CASES: list[tuple[str, Path, str, str, str, str]] = [
    # ---- 行为（由单测判：接口 / 钱 / 闸门的行为）----
    (
        "下游应收改成读订单行单价（老单与新单换同一个口径）",
        ORDER_MONEY,
        "    price = op.shipper_unit_price",
        "    price = op.line_unit_price",
        "单测①（没定过价时下游应收逐字退回订单口径）：新单应当是 8×3=24，改坏后变成 30",
        "pytest",
    ),
    (
        "快照每次覆盖（去掉「只填 NULL」那句）",
        PRICE_SVC,
        "        if pid is None or op.shipper_unit_price is not None:",
        "        if pid is None:",
        "单测③（快照只填 NULL）：改价后再定格一次，8 会被改成 12",
        "pytest",
    ),
    (
        "删掉「联系人是不是他自己的」那道闸门",
        PRICE_API,
        "        if contact is None or contact.shipper_id != current.id:",
        "        if False:  # 闸门被摘掉（反向验证）",
        "单测⑦（别人的联系人要当场 400）：摘掉之后会写进一条挂在别人名册上的价",
        "pytest",
    ),
    (
        "摘掉「管下游的账」那道闸门（L-39 那本开关不再收口）",
        PRICE_API,
        "    _require_member(current)\n    _require_downstream(current)\n    product = db.get(Product, body.product_id)",
        "    _require_member(current)\n    product = db.get(Product, body.product_id)",
        "单测⑥（关掉开关的批发商五个端点全 403）：设价那一路会变成 201",
        "pytest",
    ),
    (
        "单价 gt=0 拿掉（0 元也能进价目表）",
        PRICE_SCHEMA,
        '    unit_price: Decimal = Field(..., gt=Decimal("0"), description="他自己定的下游单价（元）")',
        '    unit_price: Decimal = Field(..., description="他自己定的下游单价（元）")',
        "单测⑦（单价 0 / -1 要 422）：0 会变成 201 —— 一条看着像'设过了'、实际白送的价",
        "pytest",
    ),
    # ---- 形状（由判据判：登记 / 迁移 / 文档这些"不在运行时"的红线）----
    (
        "权限点常量换成派单员那一档（三处登记当场对不上）",
        RBAC,
        '    SHIPPER_PRICE_MANAGE = "shipper_price:manage"',
        '    SHIPPER_PRICE_MANAGE = "price_rule:manage"',
        "判据⑤（权限点三处登记逐字对齐）",
        "check",
    ),
    (
        "028 迁移给新列加 DEFAULT 0",
        MIG28,
        '        conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} NUMERIC(14, 4) NULL"))',
        '        conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} NUMERIC(14, 4) NULL DEFAULT 0"))',
        "判据①（⛔ 028 里没有 DEFAULT）",
        "check",
    ),
    (
        "定位表那一行不再提这层价（改成'下游价目'）",
        LOCATOR,
        "| **下游定价**（批发商给自己名下的商品定价",
        "| **下游价目**（批发商给自己名下的商品定价",
        "判据⑦（定位表里有这一层价的那一行）",
        "check",
    ),
]


def run_check() -> int:
    proc = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    return proc.returncode


def run_pytest() -> tuple[int, str]:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            TEST,
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(BACKEND),
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def main() -> int:
    files = sorted({case[1] for case in CASES})
    before = {path: _read(path) for path in files}

    print("== 前提：判据与单测都必须是绿的（否则'抓到'不算数）==")
    if run_check() != 0:
        print("❌ 前提不成立：_check_shipper_pricing.py 本来就是红的，先修好它")
        return 1
    code, out = run_pytest()
    if code != 0 or re.search(r"\d+ failed", out):
        print("❌ 前提不成立：单测本来就是红的，先修好它")
        print(out[-2000:])
        return 1
    print("✅ 判据绿 ＋ 单测绿")

    fails: list[str] = []
    for i, (label, path, old, new, expect, judge) in enumerate(CASES, start=1):
        original_bytes = path.read_bytes()
        original = original_bytes.decode("utf-8").replace("\r\n", "\n")
        hits = original.count(old)
        if hits != 1:
            fails.append(f"{i:02d} {label}：替换串出现 {hits} 次（要唯一）")
            print(f"[MISS] {i:02d} {label} —— 替换串出现 {hits} 次（要唯一）")
            continue
        caught = False
        detail = ""
        try:
            path.write_text(original.replace(old, new, 1), encoding="utf-8", newline="")
            if judge == "pytest":
                code, out = run_pytest()
                caught = code != 0 or bool(re.search(r"\d+ failed", out))
                detail = (re.search(r"\d+ failed[^\n]*", out) or [""])[0] if caught else ""
            else:
                caught = run_check() != 0
        finally:
            path.write_bytes(original_bytes)
        if caught:
            print(f"[OK]   {i:02d} {label} —— 抓住了（{expect}）{(' ' + detail) if detail else ''}")
        else:
            fails.append(f"{i:02d} {label}：注进去之后没人报红（{expect}）")
            print(f"[MISS] {i:02d} {label} —— 注进去之后没人报红")

    print("== 收尾：每个文件都要还原，且还原之后判据仍然是绿的 ==")
    for path in files:
        now = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
        if now != before[path]:
            fails.append(f"收尾没还原：{path.relative_to(ROOT)}")
            print(f"❌ 收尾没还原：{path.relative_to(ROOT)}")
    if run_check() != 0:
        fails.append("还原之后判据是红的（说明还原不干净）")
        print("❌ 还原之后判据是红的")

    total = len(CASES) + 1
    if fails:
        print(f"\n❌ {total - len(fails)}/{total} 成立：")
        for f in fails:
            print(f"   - {f}")
        return 1
    print(f"\n✅ {total}/{total} 全部成立（{len(CASES)} 条坏法各自被抓住 ＋ 收尾还原与判据复绿）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
