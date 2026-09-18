"""反向验证 §30（选品页分类 / 订单行单位 / 共享地点库与补导航）。

## 为什么这一节也必须配反向验证
§30 的判据同样以**静态结构断言**为主（"这句在不在源码里"），而这类判据最容易变成空转：
正则少个转义、扫错了文件、替换串过期 —— 它照样全绿，什么也没查。
本仓库已经栽过 6 次，规矩是：**新增红线就要有对应的注入实验**。

这一轮特别容易空转的三条（注入点都选在"旧检查不看的地方"）：
1. **合并判据只有一处**：只在服务里留 `MERGE_METERS = 1.0` 常量、但判定行被改成
   恒真/恒假 —— 只锚常量的断言照样绿，而合并实际已经不按规则走了；
2. **出参名 ≠ 列名必须显式 AliasChoices**：去掉它不会有任何报错，
   `unit` 只是**静默恒为空串**（表现是"选了 3 箱，详情页只剩 3"）；
3. **超上限整批拒绝**：把 `return null` 改成 `return merged`（变成部分成功）
   —— 只锚那句中文提示的断言照样绿。

用法：`python _tools/qa/_reverse_verify_place_and_picker.py`
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
AI_TOOLS = ROOT / "_tools" / "ai"
GUARDRAILS = AI_TOOLS / "_check_ai_guardrails.py"

PICKER = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/common/ProductPicker.kt"
OCM = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/OrderCreateViewModel.kt"
OCS = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/OrderCreateScreen.kt"
ORDER_SCHEMA = ROOT / "backend/app/schemas/order.py"
ORDER_FLOW = ROOT / "backend/app/services/order_flow.py"
PLACE_SCHEMA = ROOT / "backend/app/schemas/place.py"
PLACE_SVC = ROOT / "backend/app/services/place_service.py"
PLACE_API = ROOT / "backend/app/api/v1/places.py"
ORDERS_API = ROOT / "backend/app/api/v1/orders.py"
ENUMS = ROOT / "backend/app/models/enums.py"
COVERAGE = AI_TOOLS / "_write_coverage.py"
MERGE_PROBE = ROOT / "_tools/qa/_probe_place_merge.py"

SECTION = 30

#: (说明, 目标文件, 替换函数)
CASES: list[tuple[str, Path, object]] = [
    (
        "分类清单改成手写枚举（商品管理里加一类、选品页不会多一格）",
        PICKER,
        lambda s: s.replace(
            "    products.forEach { p -> counts[categoryOf(p)] = (counts[categoryOf(p)] ?: 0) + 1 }",
            '    counts["饮料"] = 1\n    counts["粮油"] = 1',
            1,
        ),
    ),
    (
        "「未分类」无条件出现（全是未分类时和「全部」内容一模一样，纯噪音）",
        PICKER,
        lambda s: s.replace(
            "if (counts.containsKey(NO_CATEGORY) && out.size > 1) out += NO_CATEGORY",
            "if (counts.containsKey(NO_CATEGORY)) out += NO_CATEGORY",
            1,
        ),
    ),
    (
        "同一件商品不再累加，改成一货一行（10 组上限被白白吃掉）",
        OCM,
        lambda s: s.replace(
            "it.productId != null && it.productId == item.productId",
            "false",
            1,
        ),
    ),
    (
        "超上限改成部分成功（用户核对 5 件、看不出第 3 件没进去）",
        OCM,
        lambda s: s.replace(
            "return if (merged.size > MAX_ORDER_LINES) null else merged",
            "return merged",
            1,
        ),
    ),
    (
        "下单页不再把界面选的单位发给后端（选了 3 箱、订单上还是 3 件）",
        OCM,
        lambda s: s.replace(
            "OrderProductLine.create(it.name.trim(), it.quantity, it.price, it.productId, it.unit)",
            "OrderProductLine.create(it.name.trim(), it.quantity, it.price, it.productId)",
            1,
        ),
    ),
    (
        "出参 unit 去掉 AliasChoices（不报错，只是恒为空串）",
        ORDER_SCHEMA,
        lambda s: s.replace(
            'unit: str = Field("", validation_alias=AliasChoices("unit", "unit_snapshot"))',
            'unit: str = ""',
            1,
        ),
    ),
    (
        "不传单位时不再回退商品库的单位（一律写死「件」）",
        ORDER_FLOW,
        lambda s: s.replace(
            'if not unit:\n                unit = (prod.unit or "件").strip()',
            'if not unit:\n                unit = "件"',
            1,
        ),
    ),
    (
        "拆单时单位不再跟着拆（子单变「3 件」而父单是「3 箱」）",
        ORDER_FLOW,
        lambda s: s.replace(
            'unit_snapshot=(lp.unit_snapshot or "")[:32],',
            "",
            1,
        ),
    ),
    (
        "合并判据不再真的参与判定（常量还在，规则已经不走了）",
        PLACE_SVC,
        # ⚠️ 两处（共享库 + 货主自己的地点库）**都要换**：只换第一处的话，
        #    红线仍能在另一处匹配到同一行 → 照样绿（第一版就是这么漏过去的）。
        lambda s: s.replace(
            "if d <= meters or (d <= SAME_NAME_METERS and _same_place_name(row.name, name)):",
            "if False:",
        ),
    ),
    (
        "同名规则被删掉（真机 GPS 漂移下合并几乎永不触发）",
        PLACE_SVC,
        lambda s: s.replace("SAME_NAME_METERS = 30.0", "SAME_NAME_METERS = 0.0", 1),
    ),
    (
        "共享库改成按人分区（「相同位置直接拉过来」就不成立了）",
        PLACE_API,
        lambda s: s.replace(
            "    stmt = select(Place)\n",
            "    stmt = select(Place).where(Place.created_by == current.id)\n",
            1,
        ),
    ),
    (
        "已有坐标的订单允许被覆盖（把正确坐标改成错坐标，而且看不出来）",
        ORDERS_API,
        lambda s: s.replace(
            "这张订单已经有导航信息了，不需要补录",
            "补录一下也没关系",
            1,
        ),
    ),
    (
        "补导航不写货主地点库（用户要的「下次下单自动带出」落空）",
        ORDERS_API,
        lambda s: s.replace(
            "        _, shipper_location_created = place_service.ensure_shipper_location(",
            "        shipper_location_created = False\n        if False:\n            place_service.ensure_shipper_location(",
            1,
        ),
    ),
    (
        "补导航留痕的动作码被删（审计页再也查不出坐标是谁标的）",
        ENUMS,
        lambda s: s.replace('    ORDER_NAVIGATION_FILL = "ORDER_NAVIGATION_FILL"', "", 1),
    ),
    (
        "AI 覆盖表里删掉「不做补导航」的理由（coverage 会红，说明理由表真的在管）",
        COVERAGE,
        lambda s: s.replace(
            '    ("POST", "orders/{}/navigation"): "坐标类：经纬度是现场 GPS 测出来的事实，模型给不出、编一个会把司机带错（v3.41 永久排除）",\n',
            "",
            1,
        ),
    ),
    (
        "合并探针的期望值被改成「异名也该并」（判据被改坏 → 探针必须报不符）",
        MERGE_PROBE,
        lambda s: s.replace(
            '(PREFIX + "-隔壁", DEG_6_7M, False, "异名 + 6.7 米：不许并（否则吃掉隔壁那家）"),',
            '(PREFIX + "-隔壁", DEG_6_7M, True, "异名 + 6.7 米：不许并（否则吃掉隔壁那家）"),',
            1,
        ),
    ),
    # ---------------- 无主记录护栏（这张表没有删除接口）----------------
    (
        "`POST /places` 不再拦「无名无址」（往全库共享库里塞永久无名记录）",
        PLACE_SCHEMA,
        lambda s: s.replace(
            '        if not (self.name or "").strip() and not (self.detail_address or "").strip():',
            "        if False:",
            1,
        ),
    ),
    (
        "补导航不再拦「名字与地址都空」（同上，而且这条连订单地址都没有）",
        ORDERS_API,
        lambda s: s.replace(
            "    if not place_name and not detail:",
            "    if False:",
            1,
        ),
    ),
    (
        "补名字时不 strip（一串空格会被写进库 —— `if not value` 拦不住 \"   \"）",
        PLACE_SVC,
        lambda s: s.replace(
            '    text = (value or "").strip()\n    if not text:\n        return False',
            "    text = value or \"\"\n    if not text:\n        return False",
            1,
        ),
    ),
    (
        "清洗顺序改成先截断再 strip（128 个空格会被存下来、真名字被截掉）",
        PLACE_SVC,
        lambda s: s.replace(
            'return (value or "").strip()[:limit]',
            'return (value or "")[:limit].strip()',
            1,
        ),
    ),
    (
        "补名字时会**覆盖已有的名字**（别人确认过的信息被后来的请求改掉）",
        PLACE_SVC,
        lambda s: s.replace(
            '    current = (getattr(row, field, "") or "").strip()\n    if current:\n        return False',
            '    current = (getattr(row, field, "") or "").strip()\n    if False:\n        return False',
            1,
        ),
    ),
    (
        "货主端的「存入共享库」入口被拿掉（共享库只剩司机那条路）",
        OCS,
        lambda s: s.replace("vm.saveCurrentPlaceToSharedLibrary()", "Unit", 1),
    ),
]


def run(path: Path) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def section(out: str, n: int) -> str:
    """只取 §n 那一段（段内失败标记是 `[FAIL]`，不是汇总里的 ❌）。"""
    head = f"== {n}."
    if head not in out:
        return ""
    rest = out.split(head, 1)[1]
    return rest.split("\n" + "=" * 60, 1)[0]


def main() -> int:
    fails: list[str] = []
    code, out = run(GUARDRAILS)
    if code != 0:
        print(f"❌ 前提不成立：源码完好时红线就没过\n{out[-1500:]}")
        return 1
    if not section(out, SECTION):
        print(f"❌ 前提不成立：输出里找不到 §{SECTION} 这一段")
        return 1
    rc, rout = run(MERGE_PROBE)
    if rc != 0:
        print(
            "❌ 前提不成立：真后端探针 `_probe_place_merge.py` 没过"
            "（它要 backend 在 :8000 跑着、且源码完好）\n" + rout[-1200:]
        )
        return 1
    print(f"✅ 前提：源码完好时红线是绿的（§{SECTION} 在），合并探针也是绿的")

    for label, path, mutate in CASES:
        original = path.read_text(encoding="utf-8")
        mutated = mutate(original)
        if mutated == original:
            fails.append(f"{label}：注入没生效（替换串过期了，请更新本脚本）")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            if path == MERGE_PROBE:
                code2, out2 = run(MERGE_PROBE)
                red = code2 != 0
            else:
                code2, out2 = run(GUARDRAILS)
                red = code2 != 0 and "[FAIL]" in section(out2, SECTION)
        finally:
            path.write_text(original, encoding="utf-8", newline="")

        # 注入 `_write_coverage.py` 时红的是它自己，不是红线 —— 单独跑一次确认。
        if path == COVERAGE and not red:
            try:
                path.write_text(mutated, encoding="utf-8", newline="")
                code3, _ = run(COVERAGE)
                red = code3 != 0
            finally:
                path.write_text(original, encoding="utf-8", newline="")

        if red:
            print(f"✅ 注入「{label}」→ 报红")
        else:
            fails.append(f"{label}：注入之后没有报红 —— 这条判据是空转的")

    if fails:
        print("\n❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ §{SECTION} 共 {len(CASES)} 条注入全部证明会红。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
