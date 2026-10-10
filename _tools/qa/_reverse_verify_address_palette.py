# -*- coding: utf-8 -*-
'''反向验证「地址与联系人页的配色与常驻文案」这条红线**真的会红**（CHG-0014，2026-10-03）。

## 为什么这条要反向验证
它的判据几乎全是**正向存在性**判据（这一段里必须有某个色 / 某个名字），这类判据有三种典型失效方式：

1. **判据空转**：把裸色值写回去、把 token 换回旧色之后判据静默全绿；
2. **抽取失效 → 切片取到空串**：between(...) 取空之后，「这一段里不许有 MoneyOrange」这类否定式判据
   在空串上**恒真**。本脚本把起点 / 终点 / 分组 / 备注那几行的锚点改坏，逼切片出声；
3. **只扫整个文件**：Color(MgrGreen) 出现 5 次也照样算过 —— 本脚本专门再把一处电话写成裸值。

另外还有「定义漂移」那一类：Color.kt 里那两个 token 被删、RouteRail.kt 又自带一份 private val、
三档色被写死成裸值、规范里那一节被删 —— 这四条都不影响编译，但下一个人就查不到口径了。

⚠️ 快照/还原按**字节**做，跑完逐字节核对（本项目栽过「注入把 bug 留在源码里」）。

用法：python _tools/qa/_reverse_verify_address_palette.py
'''
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / '_tools/qa/_check_address_palette.py'

ADDR = 'android/app/src/main/java/com/tapmoay/sorders/ui/shipper/AddressScreen.kt'
RAIL = 'android/app/src/main/java/com/tapmoay/sorders/ui/common/RouteRail.kt'
COLOR = 'android/app/src/main/java/com/tapmoay/sorders/ui/theme/Color.kt'
DESIGN = 'docs/PROJECT_MAP/06_DESIGN_SYSTEM.md'
TABS_CHECK = '_tools/qa/_check_address_tabs.py'
FORM_PANEL = '_tools/qa/_reverse_verify_form_panel.py'
DOC = 'docs/changes/CHG-0014.md'
REGISTRY = 'docs/changes/README.md'

Q = chr(34)  # 双引号：Kotlin 字面量里一大堆，拼出来比转义好读
#: ⚠️ `_reverse_verify_form_panel.py` 里 Kotlin 的双引号是**转义写过**的（反斜杠 + 双引号），
#: 所以打它的锚点要按转义后的样子拼，否则注入静默 MISS（这条第一遍就跑出过 SKIP）。
ESC = chr(92) + chr(34)
FORM_PANEL_ANCHOR = 'title = ' + ESC + '起点（可选）' + ESC + ', tint = Color(OriginTeal)'

#: 起点 / 终点两个分组的锚点（判据就是按它们切片的，注入必须打在同一处）
ORIGIN_ANCHOR = 'title = ' + Q + '起点（可选）' + Q + ', tint = Color(OriginTeal)'
END_ANCHOR = 'title = ' + Q + '终点（必填）' + Q + ', tint = Color(DestOrange)'
#: 本页三档色那一行
TAB_LINE = 'private val ADDRESS_TAB_COLORS = listOf(Color(OriginTeal), Color(ShipperTeal), Color(MoneyOrange))'
#: 「分组」那一行的两行锚点（iconTint 紧跟 onClick，才不会打到别处的湖蓝）
CAT_ANCHOR = 'iconTint = Color(ShipperTeal),' + '\n' + '                            onClick = { catExpanded = true },'


def drop_line(text: str, needle: str) -> str:
    """整行删掉（那一行里含 needle 的行）。"""
    return '\n'.join(ln for ln in text.split('\n') if needle not in ln)


def drop_subsection(text: str, heading: str) -> str:
    """删掉某个 ### 小节（从 heading 那一行到下一个 ### / ## 之前）。"""
    i = text.find(heading)
    if i < 0:
        return text
    ends = [j for j in (text.find('\n### ', i + len(heading)), text.find('\n## ', i + len(heading))) if j > 0]
    j = min(ends) if ends else len(text)
    return text[:i] + text[j + 1:]


CASES: list[tuple[str, str, object, str]] = [
    # ---- 1. 一个概念一个色 ----
    (
        '① 电话那一行的裸色值回潮（iconTint 又写死 Color(0xFF00AC6E)）',
        ADDR,
        lambda s: s.replace("iconTint = Color(MgrGreen),", "iconTint = Color(0xFF00AC6E),", 1),
        '本页 Color(0xFF 字面量 == 0',
    ),
    (
        '② 起点组的分组 tint 回退成库存青（Color(InventoryTeal)）',
        ADDR,
        lambda s: s.replace(ORIGIN_ANCHOR, ORIGIN_ANCHOR.replace("Color(OriginTeal)", "Color(InventoryTeal)"), 1),
        '起点组的分组 tint 就是 Color(OriginTeal)',
    ),
    (
        '③ 终点组的分组 tint 回退成账本橙（Color(MoneyOrange)）',
        ADDR,
        lambda s: s.replace(END_ANCHOR, END_ANCHOR.replace("Color(DestOrange)", "Color(MoneyOrange)"), 1),
        '终点组的分组 tint 就是 Color(DestOrange)',
    ),
    (
        '④ 终点组里混回一个 MoneyOrange 的行 tint（一个概念两个橙）',
        ADDR,
        lambda s: s.replace("iconTint = Color(DestOrange),", "iconTint = Color(MoneyOrange),", 1),
        '终点组里不再混着 MoneyOrange',
    ),
    (
        '⑤ 「新增联系人」的图标又变回青绿（人 = 湖蓝这条口径破了）',
        ADDR,
        lambda s: s.replace("tint = Color(ShipperTeal))", "tint = Color(MgrGreen))", 1),
        '「新增联系人」的图标是湖蓝',
    ),
    (
        '⑥ 地点「分组」又借商品管理的紫',
        ADDR,
        lambda s: s.replace(
            CAT_ANCHOR,
            CAT_ANCHOR.replace('Color(ShipperTeal)', 'Color(0xFFA980F1)'),
            1,
        ),
        '地点「分组」的图标是湖蓝',
    ),
    (
        '⑦ 地点「备注」又借「已撤销」那个灰',
        ADDR,
        lambda s: s.replace("iconTint = MaterialTheme.colorScheme.outline,", "iconTint = Color(0xFF8A8A8E),", 1),
        '地点「备注」走中性色',
    ),
    (
        '⑧ 线路卡上那个电话图标整行被改（尺寸 / 无障碍文案一起）',
        ADDR,
        lambda s: s.replace("tint = Color(MgrGreen))", "tint = Color(MgrGreen), size = 20.dp)", 1),
        '线路卡上那个电话图标整行都是 MgrGreen',
    ),
    # ---- 2. 定义只有一份 ----
    (
        '⑨ Color.kt 里 val OriginTeal 那行被删（token 没了定义）',
        COLOR,
        lambda s: drop_line(s, 'val OriginTeal'),
        'Color.kt 里 val OriginTeal 恰好定义一次',
    ),
    (
        '⑩ RouteRail.kt 又自带一份 private val OriginTeal（定义两份）',
        RAIL,
        lambda s: s + '\n' + 'private val OriginTeal = Color(0xFF49AABA)' + '\n',
        '全库只有 Color.kt 定义 OriginTeal',
    ),
    (
        '⑪ 三档色被写死成裸值（不再走 token）',
        ADDR,
        lambda s: s.replace(TAB_LINE, 'private val ADDRESS_TAB_COLORS = listOf(Color(0xFF49AABA), Color(0xFF00A4CE), Color(0xFFBC7730))', 1),
        '顶部三档的三个色走命名 token',
    ),
    # ---- 3. 常驻文案 ----
    (
        '⑫ 12 字标题回潮（常用线路（联系人+地点））',
        ADDR,
        lambda s: s.replace('Text(' + Q + '常用线路' + Q + ',', 'Text(' + Q + '常用线路（联系人+地点）' + Q + ',', 1),
        '那条 12 字标题',
    ),
    (
        '⑬ 起点分组标题回潮（起点（可选，从这出发）= 11 字）',
        ADDR,
        lambda s: s.replace(ORIGIN_ANCHOR, ORIGIN_ANCHOR.replace('起点（可选）', '起点（可选，从这出发）'), 1),
        '起点分组标题压到 8 字内',
    ),
    (
        '⑭ 说明句从 Hint 退回裸 Text（用户关掉提示也照样显示）',
        ADDR,
        lambda s: s.replace('Hint(hint,', 'Text(hint,', 1),
        '说明句走 Hint(hint',
    ),
    # ---- 4. 规范 / 跨批锚点 ----
    (
        '⑮ 规范 §2 里「线路语义色」那一节被删（下一个改色的人查不到口径）',
        DESIGN,
        lambda s: drop_subsection(s, '### 线路语义色'),
        '规范 §2 里新增了「线路语义色」',
    ),
    (
        '⑯ 上一批的判据没同批改（_check_address_tabs.py 的三档色常量还是旧的）',
        TABS_CHECK,
        lambda s: s.replace('listOf(Color(OriginTeal), Color(ShipperTeal), Color(MoneyOrange))', 'listOf(Color(ShipperTeal), Color(MgrGreen), Color(MoneyOrange))', 1),
        '上一批的判据同批改了锚点',
    ),
    (
        '⑰ 反向验证那边（form_panel）的起点锚点没同批改',
        FORM_PANEL,
        lambda s: s.replace(FORM_PANEL_ANCHOR, 'title = ' + ESC + '起点（可选，从这出发）' + ESC + ', tint = Color(InventoryTeal)', 2),
        '反向验证的表单锚点也同批改了',
    ),
    # ---- 5. 文档 / 登记 ----
    (
        '⑱ 文档少一节（九节是 _check_dev_spec 与本判据共同的底线）—— ⚠️ 必须把 ⑨ **全部**抹掉：这文档里 ⑨ 出现过两次，只删 `## ⑨` 那一行还剩一处，判据照样绿（这条注入原来是死的）',
        DOC,
        lambda s: s.replace('⑨', ''),
        '文档九节齐全',
    ),
    (
        '⑲ 登记簿里 CHG-0014 那一行被撤掉',
        REGISTRY,
        lambda s: drop_line(s, 'CHG-0014'),
        '登记簿里有 CHG-0014',
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding='utf-8', errors='replace'
    )
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0:
        print('❌ 前提不成立：源码完好时这条红线就没过')
        print(out[-1500:])
        return 1
    print('✅ 前提：源码完好时红线是绿的')

    touched = sorted({rel for _l, rel, _m, _e in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}

    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        # 按行尾归一后再替换（Windows 上 Kotlin 文件可能是 CRLF），写回时按原样还原
        crlf = b'\r\n' in original_bytes
        plain = original_bytes.decode('utf-8').replace('\r\n', '\n')
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(label + '：注入没生效（锚点变了，请更新本脚本）')
            print('  [SKIP] ' + label)
            continue
        try:
            out_txt = mutated.replace('\r\n', '\n')
            if crlf:
                out_txt = out_txt.replace('\n', '\r\n')
            path.write_bytes(out_txt.encode('utf-8'))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        hit = code != 0 and (not expect or expect in out)
        if hit:
            print('  [OK] ' + label + ' → 报红')
        else:
            fails.append(label + f'：注入之后没有按预期报红（退出码 {code}，期望关键词「{expect}」）')
            print('  [MISS] ' + label + ' → 仍然全绿')

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append('跑完没逐字节还原：' + '、'.join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print('⚠️  已强制还原：' + '、'.join(dirty))
    else:
        print(f'✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致')

    print()
    if fails:
        print('❌ 反向验证不通过：')
        for f in fails:
            print('   - ' + f)
        return 1
    print(f'✅ {len(CASES)} 条注入都证明这条红线真的在检查。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
