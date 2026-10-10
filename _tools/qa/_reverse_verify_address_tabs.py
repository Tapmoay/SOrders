# -*- coding: utf-8 -*-
'''反向验证「地址与联系人页顶部三档与搜索框」这条红线**真的会红**（CHG-0013，2026-10-03）。

## 为什么这条要反向验证
它的判据几乎全是**正向存在性**判据（这一段里必须有某个零件），这类判据有三种典型失效方式：

1. **判据空转**：把共用件换回自定义胶囊、把 SearchField 退回 SoTextField 之后判据静默全绿；
2. **抽取失效 → 切片取到空串**：between(...) 取空之后，「这一段里不许有 SoTextField」这类否定式判据
   在空串上**恒真**。本脚本把搜索区的起点改掉（切片抽不出来）、把那份 SearchField 退回 SoTextField，
   逼切片出声；
3. **只扫整个文件**：SearchField( 出现两次也照样算过 —— 本脚本专门多塞一个搜索框进去。

另外还有「共用件退化」那一类：SegmentedStatusTabs 少一个参数、外边距被改、
SearchField 的默认提示语被就地写死、共用件里的 ✕ 被删 —— 这四条都不影响编译，但形态会一点点走样。

⚠️ 2026-10-05（CHG-0024）搜索区形态变了：从「按档三选一（联系人档 SearchField / 另外两档 SoTextField）」
改成「三档同一个 SearchField，只有占位语按档不同」。注入 ⑤⑥⑦⑨⑩⑪ 的锚点跟着搬，语义不变。

⚠️ 快照/还原按**字节**做，跑完逐字节核对（本项目栽过「注入把 bug 留在源码里」）。

用法：python _tools/qa/_reverse_verify_address_tabs.py
'''
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / '_tools/qa/_check_address_tabs.py'

ADDR = 'android/app/src/main/java/com/tapmoay/sorders/ui/shipper/AddressScreen.kt'
SEG = 'android/app/src/main/java/com/tapmoay/sorders/ui/common/SegmentedStatusTabs.kt'
COMPONENTS = 'android/app/src/main/java/com/tapmoay/sorders/ui/common/Components.kt'
DESIGN = 'docs/PROJECT_MAP/06_DESIGN_SYSTEM.md'
AI_GUARD = '_tools/ai/_check_ai_guardrails.py'
DOC = 'docs/changes/CHG-0013.md'
REGISTRY = 'docs/changes/README.md'

Q = chr(34)  # 双引号：Kotlin 字面量里一大堆，拼出来比转义好读
QQ = Q + Q  # 空串（Kotlin 的空字符串字面量）
SEG_SIG = 'fun SegmentedStatusTabs('

#: 现在那份顶部三档调用（第 ① 条注入要整块换掉它）
SEG_CALL = '\n'.join([
    '                    SegmentedStatusTabs(',
    '                        labels = ADDRESS_TABS,',
    '                        colors = ADDRESS_TAB_COLORS,',
    '                        selected = tab,',
    '                        onSelect = { tab = it; keyword = ' + QQ + ' },',
    '                    )',
    '',
])
ON_SELECT = 'onSelect = { tab = it; keyword = ' + QQ + ' }'
COLORS_DECL = (
    'private val ADDRESS_TAB_COLORS = listOf('
    'Color(OriginTeal), Color(ShipperTeal), Color(MoneyOrange))'
)
ROUTE_HINT = '0 -> ' + Q + '搜线路：收货人 / 电话 / 地址' + Q
#: 搜索区那一段的起点（2026-10-05 三档统一之后：一个 Box 里装一份 SearchField）
SEARCH_ZONE_OPEN = ('                    Box(Modifier.fillMaxWidth()'
                    '.padding(horizontal = 16.dp, vertical = 8.dp)) {')
#: 那份 SearchField 的调用行（全文件唯一一处 —— 三档共用）
SEARCH_OPEN = '                        SearchField('
#: 联系人档的占位语：走共用件自己的默认（core/UserSearch.HINT）
CONTACT_HINT_LINE = '                                1 -> UserSearch.HINT'
#: 收窄到「搜索区里那些行」的两个端点（切片用，与判据里的常量对齐）
SEARCH_END = '                    val kw = keyword.trim()'
SEARCH_ZONE_END = SEARCH_END
CLEAR_BTN = '\n'.join([
    '                            IconButton(',
    '                                onClick = { keyword = ' + QQ + ' },',
    '                                modifier = Modifier.align(Alignment.CenterEnd),',
    '                            ) {',
    '                                Icon(Icons.Default.Close, contentDescription = ' + Q + '清空搜索' + Q + ', modifier = Modifier.size(18.dp))',
    '                            }',
    '',
])
OLD_CLEAR_BTN = '\n'.join([
    '                            TextButton(',
    '                                onClick = { keyword = ' + QQ + ' },',
    '                                modifier = Modifier.align(Alignment.CenterEnd),',
    '                            ) { Text(' + Q + '清除' + Q + ') }',
    '',
])
USER_MATCH_LINE = 'else vm.contacts.filter { UserSearch.matches(kw, it.displayName, it.phone) }'


def drop_line(s: str, needle: str) -> str:
    '''整行删掉（登记簿 / 规范表格那种一行一条的）。'''
    return '\n'.join(ln for ln in s.split('\n') if needle not in ln)


def drop_section2(s: str, heading: str) -> str:
    '''整节删掉（从 heading 那一行到下一个同级 ## 之前）。'''
    i = s.find(heading)
    if i < 0:
        return s
    j = s.find('\n## ', i + len(heading))
    return s[:i] if j < 0 else s[:i] + s[j + 1 :]


def drop_section3(s: str, heading: str) -> str:
    '''整节删掉（从 heading 那一行到下一个同级 ### 之前）。'''
    i = s.find(heading)
    if i < 0:
        return s
    j = s.find('\n### ', i + len(heading))
    return s[:i] if j < 0 else s[:i] + s[j + 1 :]


def in_decl(s: str, sig: str, old: str, new: str, n: int = 1) -> str:
    '''只在某个函数的**声明 + 函数体**里替换（默认值写在参数表里，必须连声明一起要）。'''
    i = s.find(sig)
    if i < 0:
        return s
    b = s.find('{', i)
    depth = 0
    end = -1
    for k in range(b, len(s)):
        if s[k] == '{':
            depth += 1
        elif s[k] == '}':
            depth -= 1
            if depth == 0:
                end = k + 1
                break
    if end < 0:
        return s
    seg = s[i:end]
    if old not in seg:
        return s
    return s[:i] + seg.replace(old, new, n) + s[end:]


#: (说明, 相对路径, 替换函数, 期望在输出里出现的关键词 —— 空串 = 只要非零退出)
CASES: list[tuple[str, str, object, str]] = [
    # ---- 1. 导航收编 ----
    (
        '① 顶部三档换回自定义描边胶囊（每一页都不一样，用户每次都要重新认）',
        ADDR,
        lambda s: s.replace(SEG_CALL, '            AddressTabBar(tab = tab, onTab = { tab = it })' + '\n', 1),
        'AddressTabBar',
    ),
    (
        '② 三档色写死成裸色值（不再引用 Color.kt 的命名 token）',
        ADDR,
        lambda s: s.replace(
            COLORS_DECL,
            'private val ADDRESS_TAB_COLORS = listOf(Color(0xFF49AABA), Color(0xFF00A4CE),'
            ' Color(0xFFBC7730))',
            1,
        ),
        '三档颜色走命名 token',
    ),
    (
        '③ 三档顺序被调换（联系人 / 地址 换位）',
        ADDR,
        lambda s: s.replace(
            'listOf(' + Q + '路线' + Q + ', ' + Q + '联系人' + Q + ', ' + Q + '地址' + Q + ')',
            'listOf(' + Q + '路线' + Q + ', ' + Q + '地址' + Q + ', ' + Q + '联系人' + Q + ')',
            1,
        ),
        '三档标签与顺序',
    ),
    (
        '④ 切档时不再清空搜索（换档后是一个被上个档关键词过滤过的空白页）',
        ADDR,
        lambda s: s.replace(ON_SELECT, 'onSelect = { tab = it }', 1),
        '切档时顺手清空搜索',
    ),
    # ---- 2. 搜索框（三档同一个形状）----
    (
        '⑤ 那一份 SearchField 退回自己写的 SoTextField（同一件事两个答案）',
        ADDR,
        lambda s: s.replace(SEARCH_OPEN, '                        SoTextField(', 1),
        '搜索区里不再自己写 SoTextField',
    ),
    (
        '⑥ 搜索区的起点被改（切片抽不出来 → 否定式判据在空串上恒真）',
        ADDR,
        lambda s: s.replace(SEARCH_ZONE_OPEN, '                    Column(Modifier.fillMaxWidth()) {', 1),
        '搜索区那一段能抽出来',
    ),
    (
        '⑦ 又塞一个 SearchField（只扫整个文件就看不出来）',
        ADDR,
        lambda s: s.replace(
            SEARCH_ZONE_OPEN,
            '                    SearchField(value = keyword, onValueChange = { keyword = it })' + '\n' + SEARCH_ZONE_OPEN,
            1,
        ),
        '出现 2 次',
    ),
    (
        '⑧ 线路档占位语被改（AI 判据的锚点 + 输入规则表的 EXCLUDED 键都会失配）',
        ADDR,
        lambda s: s.replace(ROUTE_HINT, '0 -> ' + Q + '搜线路' + Q, 1),
        '线路档占位语被改了',
    ),
    (
        '⑨ 联系人那一档的旧占位语又回来了（说明档与档之间又开始各写各的）',
        ADDR,
        lambda s: s.replace(CONTACT_HINT_LINE, '                                1 -> ' + Q + '搜联系人：姓名 / 电话' + Q, 1),
        '旧的「搜联系人」占位语已消失',
    ),
    # ---- 3. 清空按钮 ----
    (
        '⑩ 旧的文字清空按钮（Text(清除)）又回来了',
        ADDR,
        lambda s: s.replace(CONTACT_HINT_LINE, CONTACT_HINT_LINE + '\n' + OLD_CLEAR_BTN.rstrip('\n'), 1),
        '旧的文字清空按钮（Text(清除)）已消失',
    ),
    (
        '⑪ 联系人档的提示语被就地写死（不再同源共用件）',
        ADDR,
        lambda s: s.replace(CONTACT_HINT_LINE, '                                1 -> ' + Q + '搜姓名 / 手机号' + Q, 1),
        '联系人档的提示语仍来自共用件',
    ),
    # ---- 4. 共用件退化 ----
    (
        '⑫ 共用件 SegmentedStatusTabs 少一个参数（7 个调用点会一起受影响）',
        SEG,
        lambda s: in_decl(s, SEG_SIG, '    selected: Int,', '    initial: Int,'),
        '共用件签名被改了',
    ),
    (
        '⑬ 共用件的左右外边距被改（本页的档位条会跟着变窄）',
        SEG,
        lambda s: in_decl(s, SEG_SIG, '.padding(horizontal = 16.dp)', '.padding(horizontal = 12.dp)'),
        '外边距契约被改了',
    ),
    (
        '⑭ 共用件 SearchField 的默认提示语被就地写死（不再同源 UserSearch.HINT）',
        COMPONENTS,
        lambda s: s.replace(
            'placeholder: String = com.tapmoay.sorders.core.UserSearch.HINT,',
            'placeholder: String = ' + Q + '搜索' + Q + ',',
            1,
        ),
        '提示语被就地写死',
    ),
    (
        '⑮ 共用件 SearchField 里那个 ✕ 被删（一键清空没了）',
        COMPONENTS,
        lambda s: s.replace('contentDescription = ' + Q + '清空搜索' + Q, 'contentDescription = null'),
        'SearchField 里没有清空按钮',
    ),
    (
        '⑯ 别处又冒出一份 SegmentedStatusTabs 实现（共用件被就地复制）',
        COMPONENTS,
        lambda s: s + '\n' + 'fun SegmentedStatusTabs(labels: List<String>, colors: List<Color>,'
        ' selected: Int, onSelect: (Int) -> Unit) { }' + '\n',
        '共用件没被就地复制一份',
    ),
    # ---- 5. 规范原文那一节 ----
    (
        '⑰ 规范 §3 组件速查整节被删（导航 / 搜索各自唯一实现的出处）',
        DESIGN,
        lambda s: drop_section2(s, '## 3.'),
        '§3 组件速查那一节还在',
    ),
    (
        '⑱ 规范 §3 里只删掉 SegmentedStatusTabs 那一行',
        DESIGN,
        lambda s: drop_line(s, '| SegmentedStatusTabs |'),
        '§3 里点名了这两个共用件',
    ),
    (
        '⑲ 规范 §4.4（按人搜只有一份）整节被删',
        DESIGN,
        lambda s: drop_section3(s, '### 4.4'),
        '§4.4 那一节还在',
    ),
    # ---- 6. 本批没顺手改别的 ----
    (
        '⑳ 线路卡的 A→B 轨道被顺手删掉',
        ADDR,
        lambda s: s.replace('RouteRail(', ''),
        '找不到 RouteRail(',
    ),
    (
        '㉑ 按人匹配的口径退回就地 contains（手机号后 4 位那条规则失效）',
        ADDR,
        lambda s: s.replace(USER_MATCH_LINE, 'else vm.contacts.filter { it.displayName.contains(kw, true) }', 1),
        '找不到 UserSearch.matches',
    ),
    (
        '㉒ AI 判据认的那句搜索框锚点被改（_check_ai_guardrails.py:4074）',
        AI_GUARD,
        lambda s: s.replace('搜线路：收货人 / 电话 / 地址', '搜线路'),
        '锚点句没了',
    ),
    # ---- 7. 文档 / 登记 ----
    (
        '㉓ 文档少一节（九节是 _check_dev_spec 与本判据共同的底线）',
        DOC,
        lambda s: s.replace('## ⑨', '', 1),
        '文档缺节',
    ),
    (
        '㉔ 登记簿里 CHG-0013 那一行被撤掉',
        REGISTRY,
        lambda s: drop_line(s, 'CHG-0013'),
        '没登记',
    ),
    (
        '㉕ 本页又自己画一枚清空按钮（三档会叠两个 ✕）',
        ADDR,
        lambda s: s.replace(CONTACT_HINT_LINE, CONTACT_HINT_LINE + '\n' + CLEAR_BTN.rstrip('\n'), 1),
        '本页不再自己画清空按钮',
    ),
    (
        '㉖ 规范里那段「三档同一个 SearchField」被抹掉（下一个人会照着旧口径再写一份 SoTextField）',
        DESIGN,
        lambda s: s.replace('三档（路线 / 联系人 / 地址）用的是同一个', '地址那两档还是自己写', 1),
        '规范没记下这次对齐',
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
