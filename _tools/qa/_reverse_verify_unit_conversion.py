r"""反向验证「单位换算」这条红线**真的会红**（2026-09-24）。

## 为什么这条要反向验证
它的判据大多是"某段代码里必须出现某个函数/某条分支"，这类判据有三种典型失效方式：

1. **判据变成空转**：`conflict_reason` 被改名/搬走之后，只写"别处不许再定义一份"的断言会安静地全绿。
2. **只扫整个文件、不扫函数体**：「换算不许动钱」这条必须限定在 `convertedQty` 的**函数体**里
   （`Units.kt` 里还有 `qtyWithUnit`、`damageLabel` 这些本来就跟钱无关的函数）；
   反之，如果判据只看函数名不看体，把换算改成 `qty * price` 也照样绿。
3. **显示层被复制**：数量那一格在四处渲染（订单卡片/明细/账本小卡/下单页），
   把其中一处改回 `qtyWithUnit(` 就少显示一个数，而其它三处还是对的 —— 没人会发现。

另外几条打"静默的两个答案"：同一个源单位两条换算、反向对并存、恢复时不查冲突、
删掉再建变成 500（唯一约束）、换账号沿用上一个人的换算缓存。

⚠️ 快照/还原按**字节**做，跑完逐字节核对（本项目栽过"注入把 bug 留在源码里"）。

用法：python _tools/qa/_reverse_verify_unit_conversion.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_unit_conversion.py"
CHECK_REL = "_tools/qa/_check_unit_conversion.py"

AND = "android/app/src/main/java/com/tapmoay/sorders"
BE = "backend/app"

BE_MODEL = f"{BE}/models/unit_conversion.py"
BE_RULES = f"{BE}/services/unit_conversion.py"
BE_API = f"{BE}/api/v1/unit_conversions.py"
UNITS = f"{AND}/ui/common/Units.kt"
STORE = f"{AND}/ui/common/UnitConverts.kt"
DIALOG = f"{AND}/ui/common/UnitConversionDialog.kt"
SHEET = f"{AND}/ui/common/UnitPickerSheet.kt"
FORM_SCREEN = f"{AND}/ui/dispatcher/ProductFormScreen.kt"
CARD = f"{AND}/ui/common/OrderCard.kt"
PEEK = f"{AND}/ui/common/OrderPeek.kt"
REALTIME = f"{AND}/core/RealtimeHub.kt"
REPORT = f"{AND}/ui/dispatcher/ReportCenter.kt"
TEST = "android/app/src/test/java/com/tapmoay/sorders/ui/common/UnitConversionDisplayTest.kt"

#: (说明, 相对路径, 替换函数, 期望在输出里出现的关键词 —— 空串 = 只要非零退出)
CASES: list[tuple[str, str, object, str]] = [
    (
        "① 判据被改名（判据必须报红，而不是安静地空转）",
        BE_RULES,
        lambda s: s.replace("def conflict_reason(", "def conflict_reasonZZZ(", 1),
        "只有一处定义",
    ),
    (
        "② 「一个源单位只能一条」被放开（同一批货会有两个都像是对的答案）",
        BE_RULES,
        lambda s: s.replace("MAX_TARGETS_PER_UNIT = 1", "MAX_TARGETS_PER_UNIT = 5", 1),
        "常量",
    ),
    (
        "③ 反向对不再拒绝（1 车=8 方 与 1 方=0.125 车 并存）",
        BE_RULES,
        lambda s: s.replace(
            "        if unit_key(r.from_unit) == t and unit_key(r.to_unit) == f:\n",
            "        if False:\n",
            1,
        ),
        "反向对",
    ),
    (
        "④ 加了数据库唯一约束（「删掉再建同一条」会变成 500）",
        BE_MODEL,
        lambda s: s.replace(
            '    __tablename__ = "unit_conversions"\n',
            '    __tablename__ = "unit_conversions"\n'
            '    __table_args__ = (UniqueConstraint("from_unit", "to_unit"),)\n',
            1,
        ),
        "唯一约束",
    ),
    (
        "⑤ 删除改成物理删除（用户 2026-09-20 的硬规矩：一律软删）",
        BE_API,
        lambda s: s.replace("    row.is_deleted = True\n", "    db.delete(row)\n", 1),
        "伪装删除",
    ),
    (
        "⑥ 恢复时不查冲突（放回来 = 「10 车 ≈ ?」有两个答案）",
        BE_API,
        lambda s: s.replace(
            "    reason = rules.conflict_reason(_pairs(_alive(db)), row.from_unit, row.to_unit)\n"
            "    if reason:\n"
            '        raise HTTPException(status_code=409, detail="恢复不了：" + reason)\n',
            "",
            1,
        ),
        "恢复",
    ),
    (
        "⑦ 「删掉再建同一条放回来」那条分支被删（库里会有两条同源换算）",
        BE_API,
        lambda s: s.replace('                "op": "restore_by_create",', '                "op": "create",', 1),
        "放回来",
    ),
    (
        "⑧ 显示判据被改名",
        UNITS,
        lambda s: s.replace("fun convertedQty(", "fun convertedQtyZZZ(", 1),
        "只有一处定义",
    ),
    (
        "⑨ 换算跑去动钱（函数体里出现 price —— 账目会全错）",
        UNITS,
        lambda s: s.replace(
            "    val value = factor.multiply(java.math.BigDecimal(quantity)).stripTrailingZeros().toPlainString()",
            "    val value = factor.multiply(java.math.BigDecimal(quantity * 2)).stripTrailingZeros().toPlainString()"
            " + price",
            1,
        ),
        "钱",
    ),
    (
        "⑩ 改成用 Double 算（会印出 79.99999999999999）",
        UNITS,
        lambda s: s.replace("    val factor = hit.factor.trim().toBigDecimalOrNull() ?: return null",
                            "    val factor = java.math.BigDecimal(hit.factor.trim().toDouble())", 1),
        "BigDecimal",
    ),
    (
        "⑪ 没有换算时不再逐字退回（会显示成 null / 编一个单位）",
        UNITS,
        lambda s: s.replace("    val base = qtyWithUnit(quantity, rawUnit)",
                            '    val base = "$quantity ${rawUnit ?: "件"}"', 1),
        "逐字退回",
    ),
    (
        "⑫ 订单卡片改回自己拼数量（少显示一个数，而其它三处还是对的）",
        CARD,
        lambda s: s.replace('"×" + qtyWithUnitConverted(op.quantity, op.unit, conversions)',
                            '"×" + qtyWithUnit(op.quantity, op.unit)', 1),
        "订单卡片",
    ),
    (
        "⑬ 账本小卡量列宽与渲染不同源（右对齐会当场错位）",
        PEEK,
        lambda s: s.replace('rememberTextWidth("×" + qtyWithUnitConverted(lp.quantity, lp.unit, conversions), qtyStyle)',
                            'rememberTextWidth("×" + qtyWithUnit(lp.quantity, lp.unit), qtyStyle)', 1),
        "同源",
    ),
    (
        "⑭ 又出现第二个换算表持有者（同一屏两张卡会不一样）",
        STORE,
        lambda s: s.replace("object UnitConv {", "object UnitConvZZZ {", 1),
        "持有者",
    ),
    (
        "⑮ 退出登录不清缓存（换账号会看到上一个人的换算）",
        REALTIME,
        lambda s: s.replace("                    UnitConv.clear()\n", "", 1),
        "清掉缓存",
    ),
    (
        "⑯ 「添加单位换算」那颗按钮被删（用户点名要放的入口）",
        SHEET,
        lambda s: s.replace("            if (onAddConversion != null) {", "            if (false) {", 1),
        "按钮",
    ),
    (
        "⑰ 商品表单页自己又画了一个弹窗（两层实现会各自走散）",
        FORM_SCREEN,
        lambda s: s.replace("        UnitConversionDialog(", "        UnitConversionDialogX(", 1),
        "弹窗",
    ),
    (
        "⑱ 审计码的中文名被删（审计页会印原始码）",
        REPORT,
        lambda s: s.replace('    "UNIT_CONVERSION_UPSERT" -> "新增/修改单位换算"\n', "", 1),
        "中文名",
    ),
    (
        "⑲ 显示判据的单测被改坏（一个用例都不调 convertedQty 了）",
        TEST,
        lambda s: s.replace("convertedQty(", "convertedQtyZZZ("),
        "单测",
    ),
    (
        "⑳ 判据清单指向不存在的文件（红线变成空转）",
        CHECK_REL,
        lambda s: s.replace('UNITS = AND / "ui/common/Units.kt"', 'UNITS = AND / "ui/common/UnitsGone.kt"', 1),
        "存在",
    ),
    (
        "㉑ 反向验证脚本自己不见了（新红线没配反向验证）",
        CHECK_REL,
        lambda s: s.replace('REVERSE = "_tools/qa/_reverse_verify_unit_conversion.py"',
                            'REVERSE = "_tools/qa/_reverse_verify_unit_conversion_gone.py"', 1),
        "反向验证",
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


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

    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        crlf = b"\r\n" in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            out_txt = mutated.replace("\r\n", "\n")
            if crlf:
                out_txt = out_txt.replace("\n", "\r\n")
            path.write_bytes(out_txt.encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        hit = code != 0 and (not expect or expect in out)
        if hit:
            print(f"  [OK] {label} → 报红")
        else:
            fails.append(f"{label}：注入之后没有按预期报红（退出码 {code}，期望关键词「{expect}」）")
            print(f"  [MISS] {label} → 仍然全绿")

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
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
