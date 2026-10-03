# -*- coding: utf-8 -*-
'''反向验证：`_check_order_submit_feedback.py` 的每一条判据是不是**真的会红**。

### 为什么必须反向验证
检查脚本自己也会骗人：锚点写错、判据写宽、期望文案对不上，都会让它**恒绿**。
这一份把 BUG-0003 的 12 种「会悄悄坏掉」的写法逐个注入源码，跑一次判据，确认它
红在**预期那一条**，再还原 —— 全部报红才算通过（退出码 0）。

### 每条注入对应哪一种坏法（都通过编译、真机上也「看着正常」）
· 底栏那行错误提示被删 → 那句话又只剩滚动区末尾那份（P7/P23 原样复现）；
· 滚动区末尾又塞一份渲染 → 长列表里塞在末尾等于没有；
· 提交按钮被条件禁用 → 用户连「点一下」都做不到，更不会有反馈；
· 底栏不再挂在 Scaffold 的 bottomBar 上 → 那条提示跟着内容跑；
· 同步那道货主闸门被挪走 → 点下去又要等服务端转一圈才有话说；
· 协程里那道兜底被删 → 抢在 init 之前点提交就溜过去了；
· 某条校验话术被删 → 那一类输入变成静默通过；
· 派单员那一处不再用 proxyMode 进这一页 → P23 那个入口换页了；
· 共用组件 FormErrorLine 被删 → 底栏那行成了空名字；
· 规范 §4.8 那句话被删 → 判据的出处没了；
· 登记表里 BUG-0003 那一行被删 → 留痕断了；
· 声明块被删 → 开工声明没了（别人不知道这一片有人在做）。

⚠️ 这份脚本会**临时改写**源码再还原（还原后逐字节核对）。被硬中断（工具调用被取消）
会留下注入的 bug —— 那时跑 `python _tools/qa/_check_reverse_verify_anchors.py --restore`
按注入串还原，⛔ 不要去改锚点（那会把 bug 永久钉进源码）。

用法：python _tools/qa/_reverse_verify_order_submit_feedback.py
'''
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / '_tools' / 'qa' / '_check_order_submit_feedback.py'
AND = 'android/app/src/main/java/com/tapmoay/sorders'
SCREEN = AND + '/ui/shipper/OrderCreateScreen.kt'
VM = AND + '/ui/shipper/OrderCreateViewModel.kt'
NAV = AND + '/ui/nav/NavGraph.kt'
COMP = AND + '/ui/common/Components.kt'
SPEC = 'docs/PROJECT_MAP/06_DESIGN_SYSTEM.md'
REGISTRY = 'docs/changes/README.md'
Q = chr(34)
NL = chr(10)

# (说明, 相对路径, 锚点, 替换成, 期望哪条判据报红)
MUTATIONS: list[tuple[str, str, str, str, str]] = [
    (
        '① 底栏那行错误提示被删掉（又只剩滚动区末尾那份 → 点了没反应）',
        SCREEN,
        '            FormErrorLine(vm.error, Modifier.padding(start = 16.dp, end = 16.dp, top = 16.dp))' + NL,
        '',
        '提交按钮正上方画了 FormErrorLine',
    ),
    (
        '② 滚动区末尾又塞了一份渲染（长列表里塞在末尾等于没有）',
        SCREEN,
        '            item { Spacer(Modifier.height(8.dp)) }',
        '            item { vm.error?.let { Text(it) } }' + NL + '            item { Spacer(Modifier.height(8.dp)) }',
        '整页只有一处渲染 vm.error',
    ),
    (
        '③ 提交按钮被条件禁用（点都点不下去，更不会有反馈）',
        SCREEN,
        '                            enabled = !vm.submitting,',
        '                            enabled = vm.lines.isNotEmpty() && !vm.submitting,',
        '提交按钮不是静默 disabled',
    ),
    (
        '④ 底栏不再挂在 Scaffold 的 bottomBar 上（那条提示跟着内容跑）',
        SCREEN,
        '        bottomBar = {',
        '        bottomBarX = {',
        '认得出来 Scaffold 的 bottomBar 那一段',
    ),
    (
        '⑤ 代理下单的货主闸门被挪走（同步那道没了）',
        VM,
        '            proxyMode && shipperId == null && tempShipperName.isNullOrBlank() ->' + NL,
        '',
        '代理下单的货主闸门在同步 when 里',
    ),
    (
        '⑥ 协程里那道兜底闸被删掉（抢在 init 之前点提交就溜过去了）',
        VM,
        '                        if (s?.role == ' + Q + 'dispatcher' + Q + ' && shipperId == null && tempShipperName.isNullOrBlank()) {',
        '                        if (false) {',
        '协程里那道兜底闸还留着',
    ),
    (
        '⑦ 「请至少添加一组商品」那条校验被删（这一类输入变成静默通过）',
        VM,
        '            lines.isEmpty() -> error = ' + Q + '请至少添加一组商品' + Q,
        '            // (校验没了)',
        '校验话术还在：请至少添加一组商品',
    ),
    (
        '⑧ 派单员那一处不再用 proxyMode 进这一页（P23 那个入口换页了）',
        NAV,
        '                proxyMode = true,',
        '                proxyModeX = true,',
        '派单员那一处用 proxyMode = true 进同一页',
    ),
    (
        '⑨ 共用组件 FormErrorLine 被删（底栏那行成了空名字）',
        COMP,
        'fun FormErrorLine(',
        'fun FormErrorLineX(',
        '共用组件 FormErrorLine 还在',
    ),
    (
        '⑩ 规范 §4.8 那句话被删（判据的出处没了）',
        SPEC,
        '### 4.8 错误的**落点**：表单的错画在表单里，页面级的错只管' + Q + '这一页没加载出来' + Q,
        '### 4.8 错误的落点',
        '规范 §4.8 那句根据还在',
    ),
    (
        '⑪ 登记表里 BUG-0003 那一行被删（留痕断了）',
        REGISTRY,
        '| `BUG-0003` |',
        '| `BUG-000X` |',
        '登记表里有 BUG-0003 这一行',
    ),
    (
        '⑫ 声明块被删（AI_WORK_CLAIM 里不再有 BUG-0003 的进行中声明）',
        'docs/AI_WORK_CLAIM.md',
        '会话：**BUG-0003 空表单点「提交订单」零反馈',
        '会话：**BUG-000X 空表单点「提交订单」零反馈',
        'AI_WORK_CLAIM.md 里有 BUG-0003 声明块',
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        cwd=str(ROOT),
    )
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def verdict(expect: str, code: int, out: str) -> str:
    if code == 0:
        return '注入之后判据还是绿的'
    if expect not in out:
        return '红了，但不是预期那一条（没看到 ' + expect + '）'
    return ''


def main() -> int:
    code, out = run_check()
    if code != 0:
        print('⚠️ 源码完好时判据就是红的 —— 先把判据修绿再来反向验证：')
        print(out)
        return 2
    print('基线：源码完好 → 判据全绿；下面逐个注入 ' + str(len(MUTATIONS)) + ' 条')
    bad = 0
    for i, (why, rel, old, new, expect) in enumerate(MUTATIONS, 1):
        p = ROOT / rel
        data = p.read_bytes()
        crlf = b'\r\n' in data
        src = data.decode('utf-8')
        if crlf:
            old = old.replace(NL, '\r\n')
            new = new.replace(NL, '\r\n')
        if src.count(old) != 1:
            print('[SKIP] ' + str(i) + ' ' + why + ' —— 锚点在 ' + rel + ' 里出现 ' + str(src.count(old)) + ' 次（锚点腐烂，去脚本里改锚点）')
            bad += 1
            continue
        try:
            p.write_bytes(src.replace(old, new, 1).encode('utf-8'))
            mcode, mout = run_check()
        finally:
            p.write_bytes(data)
            if p.read_bytes() != data:
                raise SystemExit('还原失败：' + rel + ' —— 手工核对这个文件！')
        problem = verdict(expect, mcode, mout)
        print(('[OK] ' if not problem else '[BAD] ') + str(i) + ' ' + why + ('' if not problem else ' —— ' + problem))
        if problem:
            bad += 1
    if bad:
        print('❌ ' + str(len(MUTATIONS) - bad) + '/' + str(len(MUTATIONS)) + ' 条成立')
        return 1
    print('✅ ' + str(len(MUTATIONS)) + '/' + str(len(MUTATIONS)) + ' 条全部成立：每条注入都被判据抓到，并红在预期那一条')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())