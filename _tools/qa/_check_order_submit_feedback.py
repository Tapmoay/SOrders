# -*- coding: utf-8 -*-
'''红线：**提交被挡下来时，那句话必须画在手边**（E2E 报告 P7 / P23）。

## 用户在真机上看到的是什么
货主「下单」页与派单员「代理下单」页（**同一个** `OrderCreateScreen`）什么都不填，
点底部「提交订单 ¥0」：**屏幕上没有任何变化** —— 不弹提示、不标红、不滚动。
E2E 报告里两张截图**字节完全相同**（`o_empty.png` / `o_empty2.png` 均 183380 B；
代理下单页连点三次都是 179797 B）。真人只会以为 App 卡死了。

## 根因不是「没有校验」，是**那句话画错了地方**
`OrderCreateViewModel.submit()` 一直在写中文校验话术（请至少添加一组商品 …），
但界面上唯一的渲染点是 `LazyColumn` 的**最后一项** —— 下单页的表单很长，
要一直滚到底才看得见那一行。规范把这件事写得很清楚
（`docs/PROJECT_MAP/06_DESIGN_SYSTEM.md` §4.8）：

> 表单的错误必须和表单同生共死 —— 画在表单里、打开表单时清掉。
> 页面级错误状态只留给「这一页的数据没加载出来」。

`_check_delete_undo.py` 里那条「**手边是个位置**」的同款判据也点了名：
「长列表里塞在末尾等于没有（OrderCreateScreen 那份同款做法就是这么来的）」。

## 判据分五层
1. **反空转**：页面 / 底栏 / `submit()` 三段都抠得出来（抠不到就是在空转，不是通过）；
2. **落点**：那句话画在 **Scaffold 的 bottomBar** 里（`FormErrorLine(vm.error, …)`），
   全页**只有这一处**渲染 —— 滚动区末尾那份必须已经删掉（`vm.error?.let` 归零）；
3. **按得下去**：提交按钮不是静默 disabled（`enabled = !vm.submitting`）——
   校验没过也要能点，点了才有反馈；
4. **话说在前面**：代理下单那道「请选择货主或填写临时货主姓名」闸门必须在
   **同步的 when** 里（点下去立刻看到），协程里那道**兜底**仍然留着
   （角色要等会话读到，抢在 init 之前点提交时同步那道闸还看不见）；
5. **出处与留痕**：规范 §4.8 那句话还在、共用组件 `FormErrorLine` 还在、
   两个入口仍然共用这一页、`docs/changes/BUG-0003.md` 九节齐、登记簿与声明块都在、
   配套反向验证脚本在。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界解决不了**。「那句话画在哪」是纯位置属性 ——
把渲染点搬回滚动区末尾、把同步闸门挪进协程、把按钮改成静默 disabled，
三种改法都通过编译、都通过渲染，真机上点下去照样「没有反应」。
类型系统看不见 bottomBar 与 LazyColumn 的区别，Compose 也没有任何修饰符能表达
「这段文字必须与触发它的那个按钮同屏」。所以只能扫**渲染点的位置**与**闸门的同步性**，
并把「校验话术一句都不能少」按清单挡住（某条校验被删掉 → 那一类输入变成静默通过）。

用法：python _tools/qa/_check_order_submit_feedback.py
配套：python _tools/qa/_reverse_verify_order_submit_feedback.py（每种破法都要被抓）
'''
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_hints import Checker, read, strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / 'android/app/src/main/java/com/tapmoay/sorders'
SCREEN = AND / 'ui/shipper/OrderCreateScreen.kt'
VM = AND / 'ui/shipper/OrderCreateViewModel.kt'
NAV = AND / 'ui/nav/NavGraph.kt'
COMPONENTS = AND / 'ui/common/Components.kt'
SPEC = ROOT / 'docs/PROJECT_MAP/06_DESIGN_SYSTEM.md'
CHANGE = ROOT / 'docs/changes/BUG-0003.md'
REGISTRY = ROOT / 'docs/changes/README.md'
CLAIM = ROOT / 'docs/AI_WORK_CLAIM.md'
REVERSE = ROOT / '_tools/qa/_reverse_verify_order_submit_feedback.py'

REL = 'ui/shipper/OrderCreateScreen.kt'
#: 这一页的下限（现在 1400+ 行）：被搬走或清空时必须先喊，不许安静全绿。
MIN_LINES = 1200
#: 底栏那一段的下限（抠不到说明锚点烂了）
MIN_BAR = 300
DOC_PARTS = '①②③④⑤⑥⑦⑧⑨'
#: 规范里那句根据（本判据的出处）。
SPEC_QUOTE = '表单的错画在表单里'
#: 五句「能照着做」的话术，少一句就是某类输入变成了静默通过。
MESSAGES = (
    '请选择货主或填写临时货主姓名',
    '请至少添加一组商品',
    '商品名称不能为空',
    '没有价格',
    'phoneError',
)
#: 同步闸门与协程兜底这两句话（一模一样的两道闸，位置不同）
GATE = 'shipperId == null && tempShipperName.isNullOrBlank()'
SYNC_GATE = 'proxyMode && ' + GATE + ' ->'
ASYNC_GATE = 'if (s?.role == ' + chr(34) + 'dispatcher' + chr(34) + ' && ' + GATE + ') {'


def slice_between(src: str, start: str, end: str) -> str:
    '''抠 [start, end] 之间的正文（含两端）。找不到返回空串。'''
    i = src.find(start)
    if i < 0:
        return ''
    j = src.find(end, i + len(start))
    return src[i : j + len(end)] if j >= 0 else src[i:]


def slice_fun(src: str, header: str) -> str:
    '''抠一个函数的正文：从 header 起、到**与自己同缩进**的那个右花括号。'''
    i = src.find(header)
    if i < 0:
        return ''
    indent = i - (src.rfind(chr(10), 0, i) + 1)
    close = chr(10) + ' ' * indent + '}'
    j = src.find(close, i)
    return src[i : j + len(close)] if j >= 0 else src[i:]


def main() -> int:
    c = Checker()
    raw = read(SCREEN)
    src = strip_comments(raw)
    vm = strip_comments(read(VM))
    nav = read(NAV)
    comp = read(COMPONENTS)
    bar = slice_between(src, 'bottomBar = {', ') { padding ->')
    sub = slice_fun(vm, 'fun submit(onDone: () -> Unit)')

    # ── 1. 反空转 ─────────────────────────────────────────────────────────
    c.section('1. 反空转：页面 / 底栏 / submit() 三段都认得出来')
    c.ok(f'{REL} 还是完整的一页（至少 {MIN_LINES} 行）',
         SCREEN.exists() and len(raw.splitlines()) >= MIN_LINES,
         f'读到 {len(raw.splitlines())} 行 —— 文件被搬走或清空了？')
    c.ok('认得出来 Scaffold 的 bottomBar 那一段',
         len(bar) >= MIN_BAR, f'只抠到 {len(bar)} 字')
    c.ok('认得出来 ViewModel 的 submit() 正文',
         len(sub) > 800, f'只抠到 {len(sub)} 字')
    c.ok('共用组件 FormErrorLine 还在（不然底栏那行就是个空名字）',
         'fun FormErrorLine(' in comp)

    # ── 2. 落点 ───────────────────────────────────────────────────────────
    c.section('2. 落点：那句话画在常驻底栏里，不在滚动区末尾')
    c.ok('提交按钮正上方画了 FormErrorLine(vm.error, …)',
         'FormErrorLine(vm.error' in bar,
         '底栏里找不到 FormErrorLine —— 提交被挡下来时用户又看不到话了')
    n_render = src.count('FormErrorLine(vm.error') + src.count('vm.error?.let')
    c.ok('整页只有一处渲染 vm.error（滚动区末尾那份已经删掉）',
         n_render == 1, f'实际 {n_render} 处 —— 长列表里塞在末尾等于没有')
    c.ok('旧的「列表最后一项」画法归零', 'vm.error?.let' not in src)
    c.ok('底栏挂在 Scaffold 的 bottomBar 上（不是页面里随手一块）',
         'Scaffold(' in src and 'bottomBar = {' in src)
    c.ok('提交按钮是那个「提交订单 ¥…」的主按钮',
         '提交订单 ¥' in bar and 'vm.submit { onCreated() }' in bar)
    c.ok('底栏在滚动区之前（同屏可见，不跟着列表滚走）',
         0 <= src.find('bottomBar = {') < src.find(') { padding ->'),
         '底栏与滚动区的先后关系看不懂了')

    # ── 3. 按得下去 ───────────────────────────────────────────────────────
    c.section('3. 按得下去：校验没过也要能点，点了才有反馈')
    c.ok('提交按钮不是静默 disabled（enabled = !vm.submitting）',
         'enabled = !vm.submitting,' in bar,
         '按钮被条件禁用的话，用户连「点一下」都做不到，更不会有反馈')
    c.ok('提交中那一支还写着「提交中…」（按钮自己会说在干活）',
         '提交中…' in bar)

    # ── 4. 话说在前面 ─────────────────────────────────────────────────────
    c.section('4. 话说在前面：同步闸门 + 协程兜底 + 五句话术都在')
    c.ok('代理下单的货主闸门在同步 when 里',
         SYNC_GATE in vm, '找不到同步那道闸 —— 点下去又要等服务端转一圈才有话说')
    i_gate = vm.find(SYNC_GATE)
    i_launch = vm.find('viewModelScope.launch {', i_gate if i_gate >= 0 else 0)
    c.ok('同步闸门排在协程之前（点下去立刻看到）',
         i_gate >= 0 and i_launch > i_gate,
         '闸门被挪到协程后面了 —— 那就回到了「等网络回话」')
    c.ok('协程里那道兜底闸还留着（会话没读到时同步闸看不见角色）',
         ASYNC_GATE in vm)
    for m in MESSAGES:
        c.ok(f'校验话术还在：{m}', m in sub)
    c.ok('提交失败仍然把后端那句话写给用户',
         'error = toApiException(e).message' in sub)

    # ── 5. 两个入口 ───────────────────────────────────────────────────────
    c.section('5. 两个入口共用这一页（P7 货主下单 + P23 代理下单）')
    n_nav = nav.count('OrderCreateScreen(')
    c.ok('NavGraph 里至少两处进这一页（两端各一处）', n_nav >= 2,
         f'只找到 {n_nav} 处 —— 某个入口换页了？那这一页的修复盖不到它')
    c.ok('派单员那一处用 proxyMode = true 进同一页',
         'proxyMode = true,' in nav,
         '代理下单换成了另一个页面 / 忘了带 proxyMode —— P23 那个入口就盖不到了')
    c.ok('这一页按角色分岔（proxyMode 决定顶栏标题）',
         'if (proxyMode) ' + chr(34) + '代理下单' + chr(34) + ' else ' + chr(34) + '下单' + chr(34) in src)

    # ── 6. 出处与留痕 ─────────────────────────────────────────────────────
    c.section('6. 出处与留痕（防清单过期 → 判据空转）')
    spec = read(SPEC)
    spec48 = next((ln for ln in spec.splitlines() if ln.startswith('### 4.8')), '')
    c.ok('规范 §4.8 那句根据还在', SPEC_QUOTE in spec48)
    c.ok('规范里三格错误状态的分工还在（loadError / formError / notice）',
         '`formError`' in spec and '`loadError`' in spec and '`notice`' in spec)
    doc = read(CHANGE) if CHANGE.exists() else ''
    c.ok('docs/changes/BUG-0003.md 存在且九节齐',
         CHANGE.exists() and all(f'## {k}' in doc for k in DOC_PARTS))
    c.ok('登记表里有 BUG-0003 这一行', '| `BUG-0003` |' in read(REGISTRY))
    c.ok('AI_WORK_CLAIM.md 里有 BUG-0003 声明块（认声明块的标题行，不认别处顺口提到）',
         '会话：**BUG-0003' in read(CLAIM))
    c.ok('配套反向验证脚本在', REVERSE.exists())

    # ── 汇总 ─────────────────────────────────────────────────────────────
    print(chr(10) + '=' * 60)
    if c.fails:
        print(f'❌ {len(c.fails)} 项未通过（通过 {c.n_ok} 项）：')
        for label, _ in c.fails:
            print(f'   - {label}')
        return 1
    print(f'✅ 全部 {c.n_ok} 项通过：下单页被挡下来时那句话画在提交按钮正上方（常驻底栏）、'
          f'滚动区末尾那份已删、按钮始终可按、五句校验话术与两道货主闸门都在。')
    return 0


if __name__ == '__main__':
    sys.exit(main())