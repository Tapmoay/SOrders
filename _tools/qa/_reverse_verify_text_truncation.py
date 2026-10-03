# -*- coding: utf-8 -*-
"""反验：_tools/qa/_check_text_truncation.py 真的会红吗？

## 为什么这条要反向验证
CHG-0027 的四处改动全是「一个参数 / 一句话 / 一个换行点」，判据盯的是源码结构，
所以最典型的三种失效正好都能在这里复现：

1. **空转**：判据写得不具体（比如只数 maxLines 出现的次数），源码改回去它照样绿；
2. **顺序取值型假绿**：同一个文件里有两处一模一样的 `maxLines = 2,`（地点卡的地址行与
   联系人行），替换错了那一处、判据却照样通过 —— 所以每一处都要单独注入一次；
3. **换说法照样编译**：把 `overflow` 换成 Clip、把「月薪未设置」挪回括号里、
   把 `.noBreak()` 抹掉 —— Kotlin / Python 都能编译通过，只有真机看得出来。
   这类改动**只能靠判据变红**来拦。

这里把上面每一条都做成一次真实注入：改一处 → 跑判据 → 它必须**非零退出**且
红灯里出现对应的那句话 → 逐字节还原。14 种破坏方式，一种都不许漏。

用法：python _tools/qa/_reverse_verify_text_truncation.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / '_tools/qa/_check_text_truncation.py'
CHECK_REL = '_tools/qa/_check_text_truncation.py'

#: Windows 上这些文件可能是 CRLF：注入时归一成 LF，写回时按原样还原（⛔ 不带反斜杠转义快照）
CR = bytes((13,))
LF = bytes((10,))
CRLF = CR + LF

AND = 'android/app/src/main/java/com/tapmoay/sorders/'
NOBREAK = AND + 'util/NoBreak.kt'
ADDR = AND + 'ui/shipper/AddressScreen.kt'
FREIGHT = AND + 'ui/dispatcher/FreightTemplatesScreen.kt'
PROFILE = AND + 'ui/profile/ProfileHeader.kt'
ACCT = AND + 'ui/dispatcher/AccountManageViewModel.kt'
SHIPPER_ORDERS = AND + 'ui/shipper/ShipperOrdersScreen.kt'
LEDGER_PERSON = AND + 'ui/dispatcher/LedgerPersonScreen.kt'
DIALOG_TITLE = AND + 'ui/common/DialogTitle.kt'
DISP_ORDERS = AND + 'ui/dispatcher/DispatcherOrdersScreen.kt'
PAY = 'backend/app/services/driver_pay.py'

#: 两处「看全文的入口」是同一个写法：删掉它就退回「只能靠右边那两颗图标」
CARD_CLICK = 'SectionCard(modifier = Modifier.clickable { onEdit() }) {'

CASES: list[tuple[str, str, object, str]] = [
    (
        '① NoBreak 的幂等早返回被删掉（已经插过一层的串会被再插一层）',
        NOBREAK,
        lambda s: s.replace("if (length < 2 || contains('\\u2060')) return this", 'if (length < 2) return this', 1),
        '幂等早返回在',
    ),
    (
        '② 插进去的不是 U+2060（换成一个可见字符 = 界面上多出怪符号）',
        NOBREAK,
        lambda s: s.replace("        if (i > 0) sb.append('\\u2060')", "        if (i > 0) sb.append('')", 1),
        '真的往相邻字符之间插 U+2060',
    ),
    (
        '③ KDoc 里那条「⛔ 不回传后端或存库」的约束被删（后来人就会拿它去拼接口字段）',
        NOBREAK,
        lambda s: s.replace('不要拿它去拼**要回传后端或存库**的字符串', '不要拿它去拼要发给别人的字符串', 1),
        'KDoc 写清三条约束',
    ),
    (
        '④ 货主端退货弹层不再走 DialogTitle（单号回到 24sp 标题行，又会从中间断成两半）',
        SHIPPER_ORDERS,
        lambda s: s.replace('title = { DialogTitle("申请退货", order.orderNo) },', 'title = { Text("申请退货 " + order.orderNo) },', 1),
        '货主 · 申请退货',
    ),
    (
        '⑤ 多出一处**不在标题里**的 DialogTitle（正文长串会被顶破窄布局）',
        LEDGER_PERSON,
        lambda s: s.replace('title = { DialogTitle("核销", order.orderNo) },', 'title = { DialogTitle("核销", order.orderNo) },\n        DialogTitle("单号", order.orderNo),', 1),
        '每一处都长在弹层标题里',
    ),
    (
        '⑥ DialogTitle.kt 忘了 import noBreak（编译直接挂，但先让判据说出来）',
        DIALOG_TITLE,
        lambda s: s.replace('import com.tapmoay.sorders.util.noBreak', 'import com.tapmoay.sorders.util.formatMoney', 1),
        'import 它的文件也恰好只有 DialogTitle.kt',
    ),
    (
        '⑦ 地点卡联系人行退回一行（走查 P30 的原症状：电话被静默吃掉）',
        ADDR,
        lambda s: s.replace('// 电话少一位就真打不出去了。\n                            maxLines = 2,', '// 电话少一位就真打不出去了。\n                            maxLines = 1,', 1),
        '联系人那一行给了两行',
    ),
    (
        '⑧ 联系人行仍给两行，但溢出退回默认 Clip（连省略号都没有）',
        ADDR,
        lambda s: s.replace('// 电话少一位就真打不出去了。\n                            maxLines = 2,\n                            overflow = TextOverflow.StartEllipsis,', '// 电话少一位就真打不出去了。\n                            maxLines = 2,\n                            overflow = TextOverflow.Clip,', 1),
        '仍放不下时按 StartEllipsis 保尾部',
    ),
    (
        '⑨ 地点卡不再可点（看全文的入口没了，只剩右边那两颗图标）',
        ADDR,
        lambda s: s.replace(CARD_CLICK, 'SectionCard {', 1),
        '地点卡本身可点',
    ),
    (
        '⑩ 运费模板的价目名退回一行（走查 P18 的原症状：截在词中间）',
        FREIGHT,
        lambda s: s.replace('// 连省略号都没有）。两行 + 省略号，剩下的交给「点卡片看全文」。\n                    maxLines = 2,', '// 连省略号都没有）。两行 + 省略号，剩下的交给「点卡片看全文」。\n                    maxLines = 1,', 1),
        '三处小字都给了两行',
    ),
    (
        '⑪ 运费模板卡不再可点（三行小字又只能靠省略号猜）',
        FREIGHT,
        lambda s: s.replace(CARD_CLICK, 'SectionCard {', 1),
        '运费模板卡本身可点',
    ),
    (
        '⑫ 后端那句话被改回旧语序（先肯定后否定 = 读成「我有固定工资」）',
        PAY,
        lambda s: s.replace('return "月薪未设置，不会生成他的工资单（计费方式：固定工资）"', 'return "固定工资（月薪未设置，账单里不会出现他的工资单）"', 1),
        'driver_pay 那句改成否定在前',
    ),
    (
        '⑬ 司机「我的」那句话退回一行（在规则名中间断开）',
        PROFILE,
        lambda s: s.replace('// 一行文字、不动底部留白。\n                            maxLines = 2,', '// 一行文字、不动底部留白。\n                            maxLines = 1,', 1),
        '司机「我的」那句话给了两行',
    ),
    (
        '⑭ 账号密码文案改回一行并列（11 位手机号又会被从中间劈开）',
        ACCT,
        lambda s: s.replace('"\\n密码："', '"　密码："', 1),
        '账号密码分享文案拆成两行',
    ),
    (
        '⑮ 单号那一行退回继承标题字号（24sp 又塞不下 20 个字符，还是会被劈开）',
        DIALOG_TITLE,
        lambda s: s.replace('                style = MaterialTheme.typography.bodyMedium,\n', '', 1),
        '单号那一行降了一号',
    ),
    (
        '⑯ 单号那一行的省略号被删（放不下时又变成静默裁掉）',
        DIALOG_TITLE,
        lambda s: s.replace('                overflow = TextOverflow.Ellipsis,\n', '', 1),
        '单号那一行封一行 + 带省略号',
    ),
]


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def main() -> int:
    print('反验：' + CHECK_REL + '（' + str(len(CASES)) + ' 种破坏方式）')
    print()
    code, out = run_check()
    if code == 0:
        print('  [OK]   前提：源码完好时判据是绿的')
    else:
        print('  [FAIL] 前提不成立：源码完好时判据已经红了 —— 反向验证无从谈起')
        print(out[-3000:])
        return 1

    bad = 0
    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original = path.read_bytes()
        crlf = CRLF in original
        text = original.decode('utf-8').replace('\r\n', '\n')
        changed = mutate(text)  # type: ignore[operator]
        if changed == text:
            print('  [FAIL] ' + label + ' —— 注入没生效（锚点找不到：' + rel + '）')
            bad += 1
            continue
        blob = changed.replace('\n', '\r\n').encode('utf-8') if crlf else changed.encode('utf-8')
        path.write_bytes(blob)
        try:
            code2, out2 = run_check()
        finally:
            path.write_bytes(original)
        dirty = path.read_bytes() != original
        hit = code2 != 0 and (not expect or expect in out2)
        if hit and not dirty:
            print('  [OK]   ' + label + ' → 判据变红')
            continue
        bad += 1
        why = []
        if code2 == 0:
            why.append('判据还是绿的（空转）')
        if expect and expect not in out2:
            why.append('红灯里没有「' + expect + '」')
        if dirty:
            why.append('还原失败（工作区被改坏）')
        print('  [FAIL] ' + label + ' —— ' + '；'.join(why))
        print(out2[-1500:])

    print()
    print('===== 反向验证（截断与长数字 / CHG-0027）=====')
    print('  ' + str(len(CASES) - bad) + '/' + str(len(CASES)) + ' 种破坏方式被抓')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
