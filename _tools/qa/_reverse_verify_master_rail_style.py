"""反向验证：`_check_master_rail_style.py` 真的会对「左栏又跟分类抽屉不一样了」变红。

做法：往**源码**里注入坏改动 → 跑红线 → 期望某条判据变红 → **按字节还原**（还原后再读回来逐字节比）。
⛔ 一条都不许"写了还原当证明"。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QA = ROOT / "_tools/qa"
CHECK = QA / "_check_master_rail_style.py"

# PowerShell 的默认控制台是 GBK —— 不重设成 utf-8，打印 ✅ 就会 UnicodeEncodeError（2026-10-07 实测）。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
COMPONENTS = ANDROID / "ui/common/Components.kt"
CREATE = ANDROID / "ui/shipper/OrderCreateScreen.kt"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
LOCATOR = ROOT / "docs/PROJECT_MAP/08_CODE_LOCATOR.md"

MUTATIONS = [
    (
        "① 选中态退回白底（用户说的「不一样」又回来了）",
        COMPONENTS,
        ".background(if (on) accent.copy(alpha = 0.12f) else Color.Transparent)",
        ".background(if (on) MaterialTheme.colorScheme.surface else Color.Transparent)",
        "选中底色是浅强调色底",
    ),
    (
        "② 浅底 alpha 与分类抽屉分叉（两边不是一个口径了）",
        COMPONENTS,
        "if (on) accent.copy(alpha = 0.12f) else Color.Transparent",
        "if (on) accent.copy(alpha = 0.24f) else Color.Transparent",
        "两处的浅底 alpha 是同一个值",
    ),
    (
        "③ 左侧竖条宽度被改（4dp 是这一列的记号）",
        COMPONENTS,
        "Box(Modifier.fillMaxHeight().width(4.dp).background(accent))",
        "Box(Modifier.fillMaxHeight().width(3.dp).background(accent))",
        "4dp 语义色竖条",
    ),
    (
        "④ 图标的 tint 不再跟着选中态（选中的那格图标不发亮）",
        COMPONENTS,
        "?: if (on) accent else MaterialTheme.colorScheme.onSurfaceVariant",
        "?: MaterialTheme.colorScheme.onSurfaceVariant",
        "图标 tint 跟着选中态走",
    ),
    (
        "⑤ 把分类抽屉那半个对勾抄了过来（分类名会被挤成两行）",
        COMPONENTS,
        "val twoLine = items.any { it.subtitle != null }",
        "val twoLine = items.any { it.subtitle != null }\n    Icon(Icons.Default.Check, contentDescription = null)",
        "这一列不画对勾",
    ),
    (
        "⑥ 第一格上面也画分隔线（列首多一条线）",
        COMPONENTS,
        "if (item.dividerBefore && index > 0) {",
        "if (item.dividerBefore) {",
        "分隔线只在不是第一格时画",
    ),
    (
        "⑦ 「线路」这一格丢了图标（一列里出现锯齿）",
        CREATE,
        'RailItem("a", "线路", icon = Icons.Default.Route)',
        'RailItem("a", "线路")',
        "线路 = Route",
    ),
    (
        "⑧ 「我的地点」也声明了分隔线（数据格之间多一条线）",
        CREATE,
        'RailItem("l", "我的地点", icon = Icons.Default.Home)',
        'RailItem("l", "我的地点", icon = Icons.Default.Home, dividerBefore = true)',
        "只有「管理分组」这一格声明了分隔线",
    ),
    (
        "⑨ 「管理分组」那条线丢了（数据格与「去别处」混在一起）",
        CREATE,
        'RailItem("manage", "管理分组", icon = Icons.Default.Settings, dividerBefore = true)',
        'RailItem("manage", "管理分组", icon = Icons.Default.Settings)',
        "管理分组 = Settings",
    ),
    (
        "⑩ 自定义分组丢了图标",
        CREATE,
        "icon = Icons.Default.Folder",
        "icon = null",
        "自定义分组 = Folder",
    ),
    (
        "⑪ 这一列的强调色换成主题主色（不再是地址湖蓝）",
        CREATE,
        "accent = Color(ShipperTeal)",
        "accent = MaterialTheme.colorScheme.primary",
        "强调色 = 地址湖蓝",
    ),
    (
        "⑫ ShipperTeal 的 import 被删（强调色退回主题色）",
        CREATE,
        "import com.tapmoay.sorders.ui.theme.ShipperTeal\n",
        "",
        "ShipperTeal 有 import",
    ),
    (
        "⑬ 设计规范里那条规矩被删（下一个人不知道左栏该怎么长）",
        DESIGN,
        "  判据 `_tools/qa/_check_master_rail_style.py`（含反向验证 `_reverse_verify_master_rail_style.py`）",
        "  （判据脚本名待补）",
        "设计文档写了左栏的长相",
    ),
    (
        "⑭ 定位表里那一条被删（改这一块的人找不到判据）",
        LOCATOR,
        "红线 `_tools/qa/_check_master_rail_style.py` + 反向验证 `_reverse_verify_master_rail_style.py`。",
        "（判据待补）",
        "代码定位表点名判据",
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> bytes:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    out = data.encode("utf-8")
    p.write_bytes(out)
    return out


def restore_src(p: Path, text: str, crlf: bool) -> None:
    # 还原**当场核对**：写回后重新读回来逐字节比，对不上就非零退出。
    wrote = write_src(p, text, crlf)
    if p.read_bytes() != wrote:
        print("⛔ 还原后与快照不一致（注入污染了源码树）：" + str(p))
        raise SystemExit(2)


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def verdict(expect: str, code: int, out: str) -> tuple[bool, str]:
    fails = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("·")]
    hit = code != 0 and any(expect in ln for ln in fails)
    if hit:
        return True, ""
    return False, f"期望含「{expect}」的 [FAIL]，实际 code={code}，fails={fails[:5]}"


def main() -> int:
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时红线就是红的 —— 先修判据。")
        print(out[-2000:])
        return 1
    print(f"✅ 前提：源码完好时 {CHECK.name} 全绿")

    bad = 0
    for i, (title, path, old, new, expect) in enumerate(MUTATIONS, 1):
        text, crlf = read_src(path)
        n = text.count(old)
        if n != 1:
            print(f"[SKIP] {i:>2}. {title} —— 原文命中 {n} 次（要 1 次，判据与源码对不上了）")
            bad += 1
            continue
        try:
            write_src(path, text.replace(old, new), crlf)
            code2, out2 = run_check()
            hit, detail = verdict(expect, code2, out2)
        finally:
            restore_src(path, text, crlf)
        print(f"{'[OK]  ' if hit else '[MISS]'} {i:>2}. {title}")
        if not hit:
            print("      " + detail)
            bad += 1

    code3, out3 = run_check()
    if code3 != 0:
        print("❌ 还原之后红线仍然红 —— 注入污染了源码树，停。")
        print(out3[-2000:])
        return 1
    print("✅ 还原后红线重新全绿（每一条注入都按字节还原并当场核对过）")
    if bad:
        print(f"❌ {bad}/{len(MUTATIONS)} 条不成立（红线对它们不敏感）")
        return 1
    print(f"✅ 反向验证 {len(MUTATIONS)}/{len(MUTATIONS)} 全部成立。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
