# -*- coding: utf-8 -*-
'''红线：**派单这条路，两个入口一份实现，档位按真实车型分、话贴在手边**（E2E 报告 P8 / P9 / P12）。

## 报告里用户看到的是什么
- **P8**（`_tmp/d_dispatch.png` / `d_drivers.png` / `d_chosen.png`）：派单弹窗只有「大车司机 / 挂车司机」
  两个页签，可下拉里既有小车司机也有挂车司机；挑中小车司机王强之后，输入框上方那行标签**还写着
  「大车司机」**。领域事实（`docs/plan-driver-freight.md`）：司机分**小车 / 大车 / 挂车**三种。
- **P9**：先「从联系人里选收货人」挑好刘秋萍，再去地址库选一条线路 —— 收货人两栏变成线路上的
  郑立新，**页面上没有任何变化可看**（`o_ct1/o_ct2/o_addrset.png`）。司机照着界面上的名字找到的是另一个人。
- **P12**（`_tmp/d_detail2.png`）：订单详情页只有 现场支付 / 挂账 / 拆分订单 / 删除订单 ——
  想看这张单派给谁、想派单，必须记住单号、退回「派单作业」池子里去翻同一张单。

## 根因
1. 弹窗里那两个页签是**车型分组**（注释从 `isPieceDriver` 改成 `vehicleType` 时写的），
   但分组用的是布尔 `pickVehicle`（大车组 / 挂车组）—— `small` 被吞进大车组；
   标签写死 `if (pickVehicle) 挂车司机 else 大车司机`，**不跟选中的人走**。
2. 收货人两栏有四个来源（手打 / 选联系人 / 选线路 / 选地点），线路与地点那两条是**静默覆盖**：
   规矩本身不动（`ContactFill.kt` 文件头写着为什么），但**换人了必须说**。
3. 派单弹窗与它需要的一切（司机名册、档位、运费/收现金/备注、`repo.assignOrder`）原本只长在
   `ui/dispatcher/DispatcherPoolScreen.kt` 里 —— 订单详情页要用，只能再写一份或搬一份。

## 判据分六层
1. **反空转**：三个页面 + 共用弹窗体都抠得出来；
2. **P8 档位**：弹窗按 `vehicleType` 真值分档、下拉按该档过滤、标签经**唯一一份** `driverKindLabel`；
   布尔分档（`pickVehicle`）与写死的两个档位名归零；
3. **P12 入口**：订单详情页有「派单」主按钮（闸门与拆分同源 `OrderStatusModel.ASSIGNABLE`）、
   借 `autoLoadPool = false` 的那份 VM、并把**同一个**弹窗挂在页面上；池页面里不再有第二份弹窗体；
4. **P9 一句话**：`receiverSwapNotice` 是唯一判据（有单测）；线路 / 地点两条支路都说话；
   用户自己动过那两栏（手改名称 / 手改电话 / 挑联系人 / 预填）之后提示必须清掉；话画在那两栏**正下方**；
5. **出处与留痕**：`_check_delete_undo.py` 那句「手边是个位置」还在、两个脚本 + 文档 + 登记表 + 声明块都在；
6. **2026-10-05（CHG-0038）形态层**：主框是**底部抽屉**（拉到屏高、内容可滚，全文件只剩运费模板那一处
   `AlertDialog`）、选司机点开的是**左侧抽屉**（左栏车型档位 `MasterRail` + 右栏 `PersonDrawer` 名单，
   不再用下拉框）、「这一单单独定」整块在界面上**不存在**（但 VM 字段与后端参数还在）、运费模板入口保留。
   用户原话：「不要搞弹窗了，直接也搞个底部抽屉吧，拉的比较上面一点拉高一点」「选择司机列表的时候
   搞一个左侧抽屉吧…不然司机多了就不好搞」「像什么这一单决定多少钱提成多少这个不要管」
   「这个模板可以保留」。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界解决不了**。P8 是「同一个布尔量被当成三种车型用」——
`vehicleType` 是后端的字符串，类型系统拦不住 `small` 被当成大车；P12 是**入口存在性**：
详情页少一条能走通的路，编译、单测、类型检查一律正常；P9 是「一次写入没有任何回显」，
`applAddress` 覆盖与不覆盖在类型上完全一样。所以只能扫**分档取值、标签来源、按钮闸门、
提示落点**这四处结构，并把「弹窗只许有一份实现」按清单挡住（谁再抄一份，两份规矩就会走散）。

用法：python _tools/qa/_check_assign_entry.py
配套：python _tools/qa/_reverse_verify_assign_entry.py（35 种破坏方式全被抓）
'''
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_hints import Checker, read, strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / 'android/app/src/main/java/com/tapmoay/sorders'
DIALOG = AND / 'ui/dispatcher/AssignDriverDialog.kt'
POOL = AND / 'ui/dispatcher/DispatcherPoolScreen.kt'
PVM = AND / 'ui/dispatcher/DispatcherPoolViewModel.kt'
DETAIL = AND / 'ui/order/OrderDetailScreen.kt'
CONTACT = AND / 'ui/common/ContactFill.kt'
USERS = AND / 'ui/dispatcher/UsersManageScreen.kt'
CREATE_SCREEN = AND / 'ui/shipper/OrderCreateScreen.kt'
CREATE_VM = AND / 'ui/shipper/OrderCreateViewModel.kt'
TEST = ROOT / 'android/app/src/test/java/com/tapmoay/sorders/ui/common/ContactFillTest.kt'
DELETE_UNDO = ROOT / '_tools/qa/_check_delete_undo.py'
DOC = ROOT / 'docs/changes/BUG-0004.md'
REGISTRY = ROOT / 'docs/changes/README.md'
CLAIM = ROOT / 'docs/AI_WORK_CLAIM.md'
REVERSE = ROOT / '_tools/qa/_reverse_verify_assign_entry.py'

DOC_PARTS = '①②③④⑤⑥⑦⑧⑨'
#: 档位名只许从这一处来（`driverKindLabel` 的三种返回值）。
KIND_LABELS = ('小车司机', '大车司机', '挂车司机')
#: 名字绑在哪个车型键上（只认这三行 —— 光看名字在不在，会被别处的字面量蒙混过关）。
#: 反向验证第 ㉖/㉗ 条就是靠这一条抓出来的：`large` 改叫小车、`trailer` 改叫大车时，
#: 别处（表单选项 listOf("large" to "大车司机", …)）还留着同样的字，光比名字会假绿。
KIND_BRANCHES = ('"small" -> "小车司机"', '"large" -> "大车司机"', '"trailer" -> "挂车司机"')
#: 订单详情页「派单」与「拆分订单」共用的那条闸门。
GATE = 'role == Role.DISPATCHER && order.status in OrderStatusModel.ASSIGNABLE'
#: 收货人两栏被带出之后那句提示（P9）。
NOTICE_FUN = 'fun receiverSwapNotice('
#: 弹窗过滤选中档位那一句（P8 的第二处：原来把 small 吞进大车组）。
FILTER = 'vm.drivers.filter { (it.vehicleType ?: ' + chr(34) + chr(34) + ') == pick }'
#: 线路 / 地点两条支路各说各的话（整句匹配：地点支路不许替线路支路顶罪）。
LINE_CALL = 'receiverSwapNotice(before, ReceiverContact(dongjiaName, dongjiaPhone), ' + chr(34) + '这条线路' + chr(34) + ')'
PLACE_CALL = 'receiverSwapNotice(before, c, ' + chr(34) + '这个地点' + chr(34) + ')'


def slice_from(src: str, start: str, span: int = 900) -> str:
    '''从 start 起切 span 个字（找不到返回空串）。'''
    i = src.find(start)
    return src[i : i + span] if i >= 0 else ''


def main() -> int:
    c = Checker()
    dialog_raw = read(DIALOG) if DIALOG.exists() else ''
    dialog = strip_comments(dialog_raw)
    pool_raw = read(POOL)
    pool = strip_comments(pool_raw)
    pvm = strip_comments(read(PVM))
    detail_raw = read(DETAIL)
    detail = strip_comments(detail_raw)
    contact = strip_comments(read(CONTACT))
    users = strip_comments(read(USERS))
    cscreen = read(CREATE_SCREEN)
    cvm = strip_comments(read(CREATE_VM))

    # ── 1. 反空转 ─────────────────────────────────────────────────────────
    c.section('1. 反空转：弹窗体 / 池页面 / 详情页 / 收货人那两栏，四处都抠得出来')
    c.ok('ui/dispatcher/AssignDriverDialog.kt 在，且是完整一份弹窗（≥150 行）',
         DIALOG.exists() and len(dialog_raw.splitlines()) >= 150,
         f'读到 {len(dialog_raw.splitlines())} 行 —— 共用弹窗体被搬走或清空了？')
    c.ok('待派单池页面还是完整一页（≥150 行）', len(pool_raw.splitlines()) >= 150)
    c.ok('订单详情页还是完整一页（≥1500 行）', len(detail_raw.splitlines()) >= 1500,
         f'读到 {len(detail_raw.splitlines())} 行')
    c.ok('共用件 ContactFill.kt 认得出来（文件头那套规矩 + 那句话都在）',
         len(read(CONTACT)) > 3000 and NOTICE_FUN in contact and 'ContactFillMode' in contact)
    c.ok('车型标签的唯一来源 driverKindLabel 还在 UsersManageScreen.kt',
         'internal fun driverKindLabel(' in users)

    # ── 2. P8：档位 ───────────────────────────────────────────────────────
    c.section('2. P8：档位按真实车型分，标签跟选中的人走')
    c.ok('弹窗按 vehicleType **真值**过滤（不是大车/挂车两档布尔）',
         FILTER in dialog,
         '找不到按选中档位过滤那一句 —— 下拉里又会混进别的车型（small 被吞进大车组）')
    c.ok('布尔分档归零（弹窗里不再有 pickVehicle）', 'pickVehicle' not in dialog and 'pickVehicle' not in pool,
         '还留着「大车组 / 挂车组」那个布尔 —— small 一定被算错')
    c.ok('档位是数据驱动的（driverKindLabel 说的三档，只画真的有人 的）',
         'kindOrder' in dialog and 'vm.drivers.any' in dialog,
         '页签写死成两档了 —— 名册里只有挂车司机时，第一页还是空的大车档')
    c.ok('标签经唯一一份 driverKindLabel（不写死大车/挂车）',
         'driverKindLabel(vm.selectedDriver?.vehicleType' in dialog)
    c.ok('整个 ui 里 driverKindLabel 只有一个定义（谁再写一份就会走散）',
         users.count('fun driverKindLabel(') == 1 and dialog.count('fun driverKindLabel(') == 0)
    for lab, br in zip(KIND_LABELS, KIND_BRANCHES):
        c.ok(f'三种车型的名字都还在：{lab}', br in users,
             '车型键与名字对不上了 —— small 会被当成大车（计费口径跟着错）')
    c.ok('弹窗自己的错误行用共用件 FormErrorLine', 'FormErrorLine(vm.error)' in dialog,
         '弹窗里的失败话术没有落点 —— 用户点「确认派单」被挡下来时看不到话')

    # ── 2b. 2026-10-05（CHG-0038）：主框是底部抽屉，司机改成左侧抽屉里选 ──────
    c.section('2b. 2026-10-05（CHG-0038）：主框是底部抽屉，司机改成左侧抽屉里选')
    c.ok('主框已经是底部抽屉（不是居中弹窗）', 'ModalBottomSheet(' in dialog,
         '又变回居中弹窗了 —— 用户 2026-10-05 要的是「不要搞弹窗了，直接也搞个底部抽屉吧」')
    n_alert = dialog.count('AlertDialog(')
    c.ok('全文件只剩一处 AlertDialog（运费模板那颗子弹窗，本轮没动）', n_alert == 1,
         f'读到 {n_alert} 处 —— 主框又退回居中弹窗了？')
    c.ok('抽屉拉到屏高、内容可滚（用户「拉的比较上面一点 拉高一点」）',
         'fillMaxHeight()' in dialog and 'verticalScroll(rememberScrollState())' in dialog)
    c.ok('选司机不再用下拉框（司机一多就得在一条竖列里翻）',
         'ExposedDropdownMenuBox' not in dialog and 'PersonTriggerRow(' in dialog,
         '选司机那行退回下拉框了 —— 用户：「不然司机多了就不好搞」')
    c.ok('点开 = 左侧抽屉：车型档位左栏 + 这一档的司机名单',
         'ModalNavigationDrawer(' in dialog and 'MasterRail(' in dialog and 'PersonDrawer(' in dialog,
         '选司机的左侧抽屉没了（左栏档位 / 右栏名单）')
    c.ok('抽屉里点中人写回同一个 selectedDriverId',
         'vm.selectedDriverId = key?.toLongOrNull()' in dialog)
    c.ok('「这一单单独定」整块已经不在界面上',
         '这一单单独定' not in dialog and '这一单的钱 ¥' not in dialog and '提成 %' not in dialog,
         '逐单覆盖那块又长回来了 —— 用户：「这个不要管，我们以后直接在那个订单里去给他订了」')
    c.ok('删的只是界面：VM 里那两个字段还在（后端参数也还在）',
         'assignPieceAmount' in pvm and 'assignCommissionRate' in pvm)
    c.ok('运费模板入口保留（用户点名要留：「这个模板可以保留」）',
         'templatePick = true' in dialog and '选择运费模板' in dialog)

    # ── 3. P12：详情页入口 ───────────────────────────────────────────────
    c.section('3. P12：订单详情页能派单，且与池子共用同一份实现')
    c.ok('详情页引入了共用弹窗与那份 VM',
         'com.tapmoay.sorders.ui.dispatcher.AssignDriverDialog' in detail_raw
         and 'com.tapmoay.sorders.ui.dispatcher.DispatcherPoolViewModel' in detail_raw)
    c.ok('详情页那份 VM 是 autoLoadPool = false（只为弹一个框，不该拉整池）',
         'DispatcherPoolViewModel(container, autoLoadPool = false)' in detail_raw)
    c.ok('VM 真的支持 autoLoadPool（构造参数 + init 里那道闸）',
         'private val autoLoadPool: Boolean = true,' in pvm and 'if (autoLoadPool) {' in pvm,
         'autoLoadPool 没了 —— 详情页一进去就会顺手拉几百条待派单')
    c.ok('名册按需拉（loadDrivers），不是只在 init 里拉一次',
         'private fun loadDrivers()' in pvm and 'if (drivers.isEmpty()) loadDrivers()' in pvm,
         '详情页借的那份 VM 名册永远是空的 —— 弹窗里一个司机都挑不到')
    head = slice_from(detail, GATE)
    # 「派单」块 = 第一条闸门到 onAssignClick 之间那一段（OutlinedButton( 里含 Button( 子串，得分开判）
    head_gate = head.split('onAssignClick')[0] if 'onAssignClick' in head else ''
    c.ok('「派单」是这一页的主色 Button（拆分仍是 OutlinedButton）',
         bool(head_gate) and 'Button(' in head_gate and 'OutlinedButton(' not in head_gate,
         '派单入口要么没了、要么被写成次要按钮（这是这一页唯一能把单推走的一步）')
    c.ok('两条闸门同源（派单与拆分都认 OrderStatusModel.ASSIGNABLE）',
         detail.count(GATE) >= 2, f'只找到 {detail.count(GATE)} 处 —— 两个按钮的状态范围走散了')
    c.ok('详情页把弹窗挂上了（派成了重拉这一页）',
         'AssignDriverDialog(assignVm)' in detail_raw and 'vm.load()' in detail_raw)
    c.ok('派成之后池子那份 VM 会回调（不是只有池页面自己知道）',
         'fun confirmAssign(onAssigned: () -> Unit = {})' in pvm and 'onAssigned()' in pvm)
    c.ok('池页面改用共用弹窗（自己那份弹窗体已经删掉）',
         'AssignDriverDialog(vm)' in pool and 'ExposedDropdownMenuBox' not in pool,
         '池页面里还留着第二份派单弹窗体 —— 两份规矩一定会走散')
    c.ok('池页面那个运费模板子弹窗跟着搬走了（templatePick 归零）', 'templatePick' not in pool)
    c.ok('两个入口都用同一个可组合函数名（定义一份、调用两处）',
         dialog.count('fun AssignDriverDialog(') == 1
         and pool.count('AssignDriverDialog(') == 1 and detail.count('AssignDriverDialog(') == 1)

    # ── 4. P9：一句话 ─────────────────────────────────────────────────────
    c.section('4. P9：带出把收货人换掉了，必须说一声')
    c.ok('判据只有一处（receiverSwapNotice 只有这一个定义）',
         NOTICE_FUN in contact and contact.count('fun receiverSwapNotice(') == 1)
    c.ok('线路那一支会说话', LINE_CALL in cvm)
    c.ok('地点那一支也会说话', PLACE_CALL in cvm)
    c.ok('覆盖前先留了一份值（不然没法比「换没换」）', cvm.count('val before = ReceiverContact(') >= 2)
    n_clear = cvm.count('receiverNotice = null')
    c.ok('用户一动手就清掉那句旧话（手改名称 / 手改电话 / 挑联系人 / 预填 ≥4 处）',
         n_clear >= 4, f'只找到 {n_clear} 处 —— 用户自己改完还挂着上一句，等于对着他喊错话')
    c.ok('话画在收货人那两栏正下方（不是页面末尾）',
         'vm.receiverNotice?.let' in cscreen
         and 0 <= cscreen.find('vm.receiverNotice?.let') < cscreen.find('下单人：名称 + 电话'),
         '提示被挪到别处了 —— 长列表里塞在末尾等于没有（BUG-0003 的教训）')
    c.ok('单测盖着这句话（纯 JVM，不需要模拟器）',
         TEST.exists() and read(TEST).count('receiverSwapNotice(') >= 4)

    # ── 5. 出处与留痕 ─────────────────────────────────────────────────────
    c.section('5. 出处与留痕（防清单过期 → 判据空转）')
    undo = read(DELETE_UNDO) if DELETE_UNDO.exists() else ''
    c.ok('「手边」是个位置那条同款判据还在（本判据的出处）', '提示画在列表**上面**' in undo)
    doc = read(DOC) if DOC.exists() else ''
    c.ok('docs/changes/BUG-0004.md 存在且九节齐',
         DOC.exists() and all(f'## {k}' in doc for k in DOC_PARTS))
    c.ok('登记表里有 BUG-0004 这一行', '| `BUG-0004` |' in read(REGISTRY))
    c.ok('AI_WORK_CLAIM.md 里有 BUG-0004 声明块（认声明块的标题行）',
         '会话：**BUG-0004' in read(CLAIM))
    c.ok('配套反向验证脚本在', REVERSE.exists())

    # ── 汇总 ─────────────────────────────────────────────────────────────
    print(chr(10) + '=' * 60)
    if c.fails:
        print(f'❌ {len(c.fails)} 项未通过（通过 {c.n_ok} 项）：')
        for label, _ in c.fails:
            print(f'   - {label}')
        return 1
    print(f'✅ 全部 {c.n_ok} 项通过：派单弹窗按真实车型分档、标签跟选中的人走；'
          f'订单详情页与待派单池共用同一份实现；带出换掉收货人时会贴在那两栏下方说一声；'
          f'派单那一层是底部抽屉 + 左侧抽屉选司机（CHG-0038）。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
