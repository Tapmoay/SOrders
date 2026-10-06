# -*- coding: utf-8 -*-
"""反向验证「同一个事实只许有一种说法」这条红线**真的会红**（CHG-0028 / P3 / P5 / P11 / P13）。

## 为什么这条要反向验证
它的判据全是"两处实现必须对齐"这类**结构上的**断言（不是运行时行为），典型失效方式有三种，
每一种都必须被单独证明会红：

1. **判据变成空转**：共用那一份被改名 / 搬走之后，判据会安静地全绿 —— 本脚本把定义删掉，
   必须报红（**0 处也红**，不是"找到 0 处也算过"）。
2. **只认"有人用"、不认"谁写的"**：卡片上 label = "钱货风险" 与 label = orderExceptionRisk(...).label
   在类型上完全一样 —— 判据只查"有没有 label"的话永远看不出这句词是抄来的。
3. **两份实现各自都对**：默认车型写成独立字面量 "trailer"，顺序一改它照样编译、照样跑 ——
   只有把默认值与下拉第一项钉成同源，才挡得住它悄悄漂走。

另外几条打判据自己：红星复活、商品数自己拼、共用函数改词、"已下架"回潮，
以及**判据自己的 REVERSE 常量被改名**（自指用例）与登记表行被改名。

⚠️ 快照 / 还原按**字节**做，跑完逐字节核对（本项目栽过"注入把 bug 留在源码里"）。

用法：python _tools/qa/_reverse_verify_wording_consistency.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_wording_consistency.py"
CHECK_REL = "_tools/qa/_check_wording_consistency.py"

#: Windows 上 Kotlin 文件可能是 CRLF：按字节快照、归一后再替换、写回时按原样还原
CR = bytes((13,))
LF = bytes((10,))
CRLF = CR + LF

FORM = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductFormScreen.kt"
BATCH = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductBatchScreen.kt"
PICKER = "android/app/src/main/java/com/tapmoay/sorders/ui/common/CategoryPickerSheet.kt"
VEHICLE = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/VehicleManageScreen.kt"
ORDERS = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DispatcherOrdersScreen.kt"
PRIORITY = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportPriority.kt"
USERS = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/UsersManageScreen.kt"
# CHG-0062：那一列商品行搬进了这个共用零件（第 5 节的用词注入也跟着搬过来）。
PART = "android/app/src/main/java/com/tapmoay/sorders/ui/common/ProductCheckList.kt"
README = "docs/changes/README.md"

#: 共用那一份（改词 / 删掉都要红）与卡片那一句
CAT_LABEL = 'internal fun categoryCountLabel(n: Int): String = if (n > 0) "$n 个商品" else "暂无商品"'
CARD_LABEL = "label = if (order.isException) orderExceptionRisk(order).label else null,"
SAME_SOURCE = "internal val DEFAULT_VEHICLE_TYPE = VEHICLE_TYPES.first().first"
VEHICLE_LINE = 'internal val VEHICLE_TYPES = listOf("small" to "小货车", "large" to "大货车", "trailer" to "挂车")'

#: (说明, 相对路径, 替换函数, 期望在输出里出现的关键词 —— 空串 = 只要非零退出)
CASES: list[tuple[str, str, object, str]] = [
    (
        "① 库存那一行又把红星画回来（P3 原样复发：同一行还写着「（选填）」）",
        FORM,
        lambda s: s.replace(
            'placeholder = "初始库存（选填）",',
            'placeholder = "初始库存（选填）",' + chr(10) + "                            required = true,",
            1,
        ),
        "红星",
    ),
    (
        "② 批量操作页自己拼一份商品数（P5 原样复发：0 个商品时说「0 个商品」）",
        BATCH,
        lambda s: s.replace(
            "CategoryChoice(it.name, categoryCountLabel(it.productCount))",
            'CategoryChoice(it.name, it.productCount.toString() + " 个商品")',
            1,
        ),
        "自己拼",
    ),
    (
        "③ 共用那一份把 0 的说法改掉（三页会立刻各说各的）",
        PICKER,
        lambda s: s.replace('else "暂无商品"', 'else "0 个商品"', 1),
        "只有一份",
    ),
    (
        "④ 共用那一份被整个删掉（0 处也红：判据不许空转）",
        PICKER,
        lambda s: s.replace(CAT_LABEL, "", 1),
        "只有一份",
    ),
    (
        "⑤ 车型顺序改回「挂车排第一」（P11 原样复发）",
        VEHICLE,
        lambda s: s.replace(
            VEHICLE_LINE,
            'internal val VEHICLE_TYPES = listOf("trailer" to "挂车", "large" to "大货车", "small" to "小货车")',
            1,
        ),
        "小货车排第一",
    ),
    (
        "⑥ 默认车型不再是下拉第一项（写成独立字面量，顺序一改就漂走）",
        VEHICLE,
        lambda s: s.replace(SAME_SOURCE, 'internal val DEFAULT_VEHICLE_TYPE = "trailer"', 1),
        "同源",
    ),
    (
        "⑦ 新建车辆那一格硬写车型（用户不动这一格就会建错车型）",
        VEHICLE,
        lambda s: s.replace("        draftType = DEFAULT_VEHICLE_TYPE", '        draftType = "trailer"', 1),
        "硬写",
    ),
    (
        "⑧ 订单卡上那句类别词被删掉（P13 原样复发：又只剩一个「异常」）",
        ORDERS,
        lambda s: s.replace(CARD_LABEL, "", 1),
        "说了是哪一类",
    ),
    (
        "⑨ 订单卡自己抄一份类别词（报表页改词的那天它就说另一个名字）",
        ORDERS,
        lambda s: s.replace(CARD_LABEL, 'label = if (order.isException) "钱货风险" else null,', 1),
        "不自己写",
    ),
    (
        "⑩ 报表页那条入口不再取全事实（已解决 / 逾期的单会被判成另一个类别）",
        PRIORITY,
        lambda s: s.replace(
            "exceptionRiskOf(e.exceptionReason, resolved = e.exceptionResolvedAt != null, overdue = isOverdue(e))",
            "exceptionRiskOf(e.exceptionReason, resolved = false, overdue = false)",
            1,
        ),
        "薄封装",
    ),
    (
        "⑪ 账户管理那一行的商品行又写回「已下架」（同一个状态两个词）",
        PART,
        lambda s: s.replace(
            "badge = if (p.isActive) null else ({ ProductSoldOutBadge() }),",
            'badge = if (p.isActive) null else ({ Text("已下架", color = Color.Gray) }),',
            1,
        ),
        "已沽清",
    ),
    (
        "⑫ 判据自己的 REVERSE 常量被改名（自指用例：配对那一条必须红）",
        CHECK_REL,
        lambda s: s.replace(
            'REVERSE = "_tools/qa/_reverse_verify_wording_consistency.py"',
            'REVERSE = "_tools/qa/_reverse_verify_wording_consistencyX.py"',
            1,
        ),
        "反向验证",
    ),
    (
        "⑬ 登记表里 CHG-0028 那一行被改名（文档对账必须红）",
        README,
        lambda s: s.replace("| " + chr(96) + "CHG-0028" + chr(96) + " |", "| " + chr(96) + "CHG-0028x" + chr(96) + " |", 1),
        "登记表",
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
        crlf = CRLF in original_bytes
        plain = original_bytes.decode("utf-8").replace(CRLF.decode(), LF.decode())
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            out_txt = mutated
            if crlf:
                out_txt = out_txt.replace(LF.decode(), CRLF.decode())
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
