'''_check_roster_cards.py —— 名册卡 + 左栏分类抽屉（CHG-0023）的静态判据。

## 这一批做了什么（用户 2026-10-05 原话）

> 他那个侧边栏样式太不好看了，而且你看全部展开的话，他属于啊内容又比较短太空旷了，
> 我们可以搞一个半展开……包括我们这有张卡片啊，比如说我们重要的……就是名称和电话号码吧，
> 我们要有对应的语义色和图标。让信息明确。

两件事：

1. **左栏分类抽屉半展开**：`ui/common/CategoryDrawer.kt` 里一个共用常量
   `CategoryDrawerWidth = 240.dp`，四个分类抽屉（账户 / 司机·货主·批发商 / 车辆 / 地址）
   都写在这个宽度上；那行常驻说明压到 8 字；每一格左边补图标，选中的一格有 accent 底。
2. **名册卡的两条事实**：名称 = 本页模块色的圈底图标 + 16sp 加粗；电话 = `Icons.Default.Phone`
   + `PhoneGreen`（青绿）+ 15sp **前景色**（不是灰字），整行长按复制。两条都住
   `ui/common/RosterCard.kt`（一份实现，四个页面共用）。

顺带（同一次复核）：账户管理页拿回自己的棕（`AccountBrown = 0xFF8D6E63`，与工作台宫格那一格
同值），司机 / 货主 / 批发商页的胶囊与 FAB 改成按池子取模块色，「管理分类」面板里四颗裸
`IconButton` 换成 `CardActionIcon`、条数与撤销条装在纯白卡上。

## 判据盯的是什么

1. 共用件那两条事实（图标 / 色 / 字号 / 不是灰字 / 长按复制）—— 盯的是**共用件**，
   所以四个页面用的是同一份，改坏一处四处一起红；
2. 四个页面**真的用上了**（不是各画各的）；
3. 抽屉宽度：4 处半展开、三个「选人」抽屉**不许**跟着收窄；
4. 规范 `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md` 里 §4.24 与 §2 那一行（账户管理·棕）在不在；
5. 文档三件（CHG-0023.md 九节 / 登记表一行 / 声明块）与反验脚本的条数对得上。

## 一条容易踩的坑（判据自己记着）

「电话不是灰字」**不能**用全文搜 `onSurfaceVariant` 来判：共用件别的地方本来就可能用到中性色。
判的是**电话那一行那一个 color =**，所以下面第 1 节先把 `RosterPhoneRow` 整段切出来再看。

配套：python _tools/qa/_reverse_verify_roster_cards.py（47 条注入，全是「改坏了不会有任何报错」的类型）。

R4-BOUNDARY-JUSTIFICATION: 本判据只读源码与文档（`read()`），不编译、不跑 UI、不连后端；
它认证的是「这两件事的形态与登记齐不齐」，**跑不出**「装到 5554 上真的好看」——
那一头由 `python _tools/qa/_install_all.py --only 5554` 加截图人工判。

用法：

    python _tools/qa/_check_roster_cards.py            # 打印每一项
    python _tools/qa/_check_roster_cards.py --check     # 非零退出 = 有问题
'''

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _check_hints import Checker, read  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / 'android' / 'app' / 'src' / 'main' / 'java' / 'com' / 'tapmoay' / 'sorders'
UI = AND / 'ui'
COMMON = UI / 'common'
DISP = UI / 'dispatcher'

ROSTER = COMMON / 'RosterCard.kt'
DRAWER = COMMON / 'CategoryDrawer.kt'
PANEL = DISP / 'CategoryRostersPanel.kt'
ACCOUNT = DISP / 'AccountManageScreen.kt'
USERS = DISP / 'UsersManageScreen.kt'
VEHICLE = DISP / 'VehicleManageScreen.kt'
ADDRESS = UI / 'shipper' / 'AddressScreen.kt'
COLOR = UI / 'theme' / 'Color.kt'
MODULES = UI / 'nav' / 'Modules.kt'
SPEC = ROOT / 'docs' / 'PROJECT_MAP' / '06_DESIGN_SYSTEM.md'
DOC = ROOT / 'docs' / 'changes' / 'CHG-0023.md'
README = ROOT / 'docs' / 'changes' / 'README.md'
CLAIM = ROOT / 'docs' / 'AI_WORK_CLAIM.md'
REV = ROOT / '_tools' / 'qa' / '_reverse_verify_roster_cards.py'


def slice_fun(src: str, head: str) -> str:
    '''从 head 那一行切到下一个顶层声明（@Composable / private fun / fun）。'''
    i = src.find(head)
    if i < 0:
        return ''
    rest = src[i + len(head):]
    m = re.search(r'^(?:@|private fun |fun |internal fun )', rest, re.M)
    return src[i:i + len(head) + (m.start() if m else len(rest))]


def main() -> int:
    c = Checker()

    roster = read(ROSTER)
    name = slice_fun(roster, 'fun RosterNameRow(')
    phone = slice_fun(roster, 'fun RosterPhoneRow(')

    c.section('1. 名册卡的共用件（两条事实各一份实现）')
    c.ok('共用件 RosterCard.kt 在，名称行与电话行两个零件都导出',
         ROSTER.exists() and 'fun RosterNameRow(' in roster and 'fun RosterPhoneRow(' in roster,
         '两个零件必须住在一个文件里 —— 四个页面共用同一份')
    c.ok('名册卡名称行：本页模块色的圈底图标（34dp 底 / 18dp 图标）',
         'TintedIcon(icon, accent, size = 18.dp, container = 34.dp)' in name)
    c.ok('名册卡名称行：16sp 加粗（与车辆卡车牌同号）',
         'fontSize = 16.sp' in name and 'fontWeight = FontWeight.Bold' in name)
    c.ok('名册卡名称行：icon 与 accent 都是形参（每页给自己的模块色）',
         re.search(r'fun RosterNameRow\([\s\S]{0,240}?icon: ImageVector', name) is not None
         and re.search(r'fun RosterNameRow\([\s\S]{0,240}?accent: Color', name) is not None)
    c.ok('名册卡电话行：Phone 图标 + PhoneGreen',
         'Icons.Default.Phone' in phone and 'tint = PhoneGreen' in phone)
    c.ok('名册卡电话行：15sp 前景色，⛔ 不是灰字（onSurfaceVariant）',
         re.search(r'color = MaterialTheme\.colorScheme\.onSurface,', phone) is not None
         and 'onSurfaceVariant' not in phone,
         '用户要的是「一眼看得到号码」，灰字等于又把它降级成备注')
    c.ok('名册卡电话行：整行长按复制（combinedClickable + onLongClickLabel + copyTextToClipboard）',
         all(t in phone for t in ('combinedClickable(', 'onLongClickLabel', 'copyTextToClipboard(')))
    c.ok('电话那个绿是全库一个 token（PhoneGreen = MgrGreen，不是随手一个绿）',
         'val PhoneGreen: Color = Color(MgrGreen)' in roster)

    acct = read(ACCOUNT)
    users = read(USERS)
    veh = read(VEHICLE)
    drawer = read(DRAWER)

    c.section('2. 四个名册页真的用上了共用件')
    c.ok('账户卡：名称行走 RosterNameRow、电话行走 RosterPhoneRow',
         'RosterNameRow(' in acct and 'RosterPhoneRow(' in acct,
         '长按复制搬进共用件之后，账户页也要跟着走那一份')
    c.ok('账户卡名称前的图标是人形（Icons.Default.Person）', 'Icons.Default.Person' in acct)
    c.ok('司机 / 货主 / 批发商卡：电话行走共用件，u.phone 原样传进去',
         'RosterPhoneRow(' in users and 'phone = u.phone,' in users)
    c.ok('司机 / 货主 / 批发商卡：名称提到 16sp 那一档（与账户卡同号）',
         'style = MaterialTheme.typography.titleMedium,' in users)
    c.ok('司机 / 货主 / 批发商卡：姓氏圆底与池子强调色没被改掉',
         'clip(CircleShape).background(accent.copy(alpha = 0.16f))' in users and 'poolAccent(pool)' in users)
    c.ok('车辆卡：车牌那行的圈底图标 + 模块色还在（黄绿，没跟着换成棕）',
         'TintedIcon(Icons.Default.LocalShipping, VehicleAccent, size = 18.dp, container = 34.dp)' in veh)
    c.ok('⛔ 地址页的线路卡没被顺手改（那一页电话仍是很小很灰的次要信息）',
         'RosterPhoneRow(' not in read(ADDRESS) and 'RosterNameRow(' not in read(ADDRESS))

    c.section('3. 左栏分类抽屉：半展开 240dp')
    c.ok('共用常量 CategoryDrawerWidth = 240.dp（用户嫌默认宽度「太旷」）',
         'val CategoryDrawerWidth = 240.dp' in drawer)
    for label, p in (('账户管理', ACCOUNT), ('司机 / 货主 / 批发商', USERS),
                     ('车辆管理', VEHICLE), ('地址与联系人', ADDRESS)):
        c.ok(f'{label}：抽屉是半展开（ModalDrawerSheet 挂在共用宽度上）',
             'ModalDrawerSheet(modifier = Modifier.width(CategoryDrawerWidth))' in read(p))
    for label, p in (('司机运费结算页', DISP / 'FreightSettlementScreen.kt'),
                     ('账本页', DISP / 'DispatcherLedgerScreen.kt'),
                     ('货主账本页', UI / 'shipper' / 'ShipperLedgerScreen.kt')):
        src = read(p) if p.exists() else ''
        c.ok(f'{label}的选人抽屉⛔ 不跟着收窄（里面是搜索框 + 一列人，不是分类）',
             'ModalDrawerSheet {' in src and 'CategoryDrawerWidth' not in src)

    c.section('4. 抽屉里的每一格')
    c.ok('每一格左边有图标：全部 = Apps / 分类 = Folder / 管理分类 = Settings',
         'if (item.key.isEmpty()) Icons.Default.Apps else Icons.Default.Folder' in drawer
         and 'Icons.Default.Settings' in drawer)
    c.ok('选中那一格有 accent 底（⛔ 不只是字变色）',
         'if (selected) accent.copy(alpha = 0.12f) else Color.Transparent' in drawer
         and 'Icons.Default.Check' in drawer)
    c.ok('那行常驻说明 ≤ 8 字（用户口径：常驻就几个字）',
         '选一类只看这一类' in drawer and '不选就是全部' not in drawer)
    c.ok('抽屉里一格条数都不显示（用户 2026-09-19 的裁定）',
         '个账号' not in drawer and '辆车' not in drawer)

    panel = read(PANEL)
    c.section('5. 「管理分类」面板（同屏第二层）')
    c.ok('面板一行里的四个动作都走 CardActionIcon（⛔ 不是裸 IconButton）',
         panel.count('CardActionIcon(') == 4 and 'IconButton(' not in panel,
         '裸 IconButton 里塞 18dp 图标正是规范 §4.2c 里用户说过「这个不行」的形态')
    c.ok('删除那颗用 MessageRed（⛔ 不是裸色值）',
         'tint = Color(MessageRed),' in panel and 'Color(0xFF' not in panel,
         '整个面板不许再出现裸十六进制（强调色一律走形参）')
    c.ok('条数与撤销条装在纯白卡上（规范 §5.0：抽屉里的卡片必须纯白）',
         'color = MaterialTheme.colorScheme.surfaceContainerHigh' not in panel
         and 'SectionCard(' in panel)
    c.ok('面板强调色是形参：账号名册默认账户棕、车辆名册默认车辆黄绿',
         'accent: Color = Color(AccountBrown),' in panel and 'accent: Color = VehicleAccent,' in panel,
         '一色一功能：面板不许借别的模块的颜色（规范 §4.3）')
    c.ok('上移 / 下移用宿主页模块色，⛔ 不再写死地址页的湖蓝',
         re.search(r'tint = if \(first\)[^\n]*else accent', panel) is not None
         and re.search(r'tint = if \(last\)[^\n]*else accent', panel) is not None
         and 'Color(ShipperTeal)' not in panel)

    color = read(COLOR)
    mods = read(MODULES)
    c.section('6. 账户管理页拿回自己的棕')
    c.ok('主题 token 里有 AccountBrown（账户管理：棕）', 'val AccountBrown = 0xFF8D6E63L' in color)
    c.ok('棕底上的字也有 token（OnAccountBrown）', 'val OnAccountBrown = 0xFFFFFFFFL' in color)
    c.ok('工作台宫格那一格与 token 同值（一处定义、一处对账）',
         'color = 0xFF8D6E63L' in mods,
         '宫格那行故意保留裸字面量：_check_ledger_dashboard.py 的 BAND_EXEMPT 按裸值扫')
    c.ok('账户页的胶囊 / 名称圈底图标 / FAB 都用这个棕（⛔ 不再借地址页的湖蓝）',
         acct.count('Color(AccountBrown)') >= 3 and 'ShipperTeal' not in acct)
    c.ok('账户页的 FAB 是带字的 Extended FAB（照车辆页那套），⛔ 不是裸 FloatingActionButton',
         'ExtendedFloatingActionButton(' in acct
         and len(re.findall(r'(?<!Extended)FloatingActionButton\(', acct)) == 0
         and 'contentColor = Color(OnAccountBrown),' in acct and '新增账号' in acct)

    c.section('7. 司机 / 货主 / 批发商页：三池各用各的模块色')
    c.ok('三池的模块色映射在（司机 = 黄绿 / 货主 = 深青 / 批发商 = 金）',
         'UserPool.DRIVERS -> Color(DriverLime)' in users
         and 'UserPool.SHIPPERS -> Color(InventoryTeal)' in users
         and 'UserPool.MEMBERS -> Color(MemberGold)' in users)
    c.ok('分类胶囊与抽屉都按池子取色（⛔ 不再写死货主那一页的深青）',
         users.count('poolModuleColor(pool)') >= 2)
    c.ok('FAB 的底色与压在上面的字色各有一套（亮色上压深字，过 AA）',
         'contentColor = poolOnColor(pool),' in users and 'Color(OnDriverLime)' in users)
    c.ok('司机页的 FAB 也是带字的 Extended FAB',
         'ExtendedFloatingActionButton(' in users
         and len(re.findall(r'(?<!Extended)FloatingActionButton\(', users)) == 0)
    c.ok('⛔ 卡片上那三个深色（姓氏圆底 / 徽章）一个字没动',
         'Color(0xFF5A6B00)' in users and 'Color(0xFF0A3168)' in users and 'Color(0xFF7A5900)' in users)
    c.ok('整个文件只剩返回那一颗 IconButton（判据 _check_users_ui.py 钉着）',
         users.count('IconButton(') == 1)

    spec = read(SPEC)
    c.section('8. 规范写死了这两件事')
    c.ok('规范 §4.24 在（名册卡两条事实 + 抽屉半展开）',
         re.search(r'^### 4\.24 ', spec, re.M) is not None)
    c.ok('规范 §2 表里有账户管理那一行（棕 #8D6E63 / AccountBrown）',
         re.search(r'\| 账户管理 \| 棕 #8D6E63 \| AccountBrown \|', spec) is not None)
    c.ok('规范里写着抽屉宽度 240dp、为什么是它、以及哪三个抽屉不收窄',
         'CategoryDrawerWidth = 240.dp' in spec and '选人' in spec
         and ('PersonDrawer' in spec or 'CustomerDrawer' in spec))
    c.ok('「电话不许退回灰字」写进了规范', '不许' in spec and ('灰字' in spec))
    c.ok('这次一并修的规范漂移：TintedIcon 指到 OrderCard.kt、HintOnce 标成待删兼容壳',
         'ui/common/OrderCard.kt' in spec and '待删的兼容壳' in spec)

    c.section('9. 文档三件与反验')
    doc = read(DOC) if DOC.exists() else ''
    c.ok('docs/changes/CHG-0023.md 存在且九节齐',
         all(f'## {x}' in doc for x in '①②③④⑤⑥⑦⑧⑨'))
    c.ok('文档里写着半径是 L0（纯展示层：不动后端、不动 DTO、不动权限）', '**L0**' in doc)
    c.ok('变更登记表里有 CHG-0023 这一行（行首 ID 格 + 链接那一格）',
         re.search(r'^\| `CHG-0023` \| CHG \|', read(README), re.M) is not None
         and '[CHG-0023.md](CHG-0023.md)' in read(README))
    c.ok('AI_WORK_CLAIM.md 里有 CHG-0023 声明块（进行中 / 已完成都算）',
         re.search(r'^### \[2026-10-05 [^\]]*\][^\n]*\*\*CHG-0023', read(CLAIM), re.M) is not None)
    rev = read(REV) if REV.exists() else ''
    n_rev = len(re.findall(r'^    \($', rev, re.M))
    c.ok('反验脚本 _reverse_verify_roster_cards.py 在，条数与本文件说的一致',
         REV.exists() and n_rev >= 30 and f'{n_rev} 条注入' in (__doc__ or ''),
         f'实际数到 {n_rev} 条注入')

    print('\n' + '=' * 60)
    if c.fails:
        print(f'❌ {len(c.fails)} 项未通过（通过 {c.n_ok} 项）：')
        for label, detail in c.fails:
            print(f'   - {label}')
            if detail:
                print(f'     {detail}')
        return 1
    print(f'✅ 全部 {c.n_ok} 项通过：名册卡的两条事实 + 左栏分类抽屉半展开（CHG-0023）。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
