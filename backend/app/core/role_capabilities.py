'''角色能力：**没有权限点、但仍被角色门护着的业务事实**（R3-02）。

## 为什么需要这一张表

R3-02 要的是「Capability 四端同源」：UI 问 `can(order:assign)`、AI 问同一句、审计按同一套词表留痕。
但本项目**不是所有授权都有权限点**：地址与联系人、地点库、单位换算这几块用的是
`require_roles(UserRole.SHIPPER, UserRole.DISPATCHER)`（见 `api/v1/shipper.py:29`）；
车辆管理更彻底 —— 它是**体内角色判断**（`vehicles.py:46 _must_dispatcher`）。
没有名字，UI/AI 就无从问起 —— 于是它们各自硬编码 `role == ...`，这正是「第二份权限真相」的来源。

## 这一张表是什么、不是什么

- **是**：给这些「角色门事实」一个**稳定的名字**（与 `Permission` 的值同一个命名空间），
  以及它的**证据**（`gate` 指向真实的角色门那一行，判据会去核）。
- ⛔ **不是**：新造一套权限系统。角色门**一行没动** —— 名字只是让 UI/AI/审计有个可问的东西。
  所以每一项都必须写 `why_not_permission` 与 `when_to_remove`（**什么时候收成真正的权限点**）。

## 判据
`_tools/qa/_check_capability_unification.py`：
· 每一项的 `gate` 指向的那一行必须真有 `require_roles(` **或** 体内角色判断（`_must_dispatcher`）；
· 声明里的角色必须都出现在那一行里；
· 键不许与任何 `Permission` 的值重名（两套真相不许混在一个命名空间里）；
· `kind` 只能是 read / write，写能力必须在审计覆盖里有下落（动作码，或写清为什么没有）。
'''
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoleCapability:
    '''一条「由角色门（而不是权限点）护着的业务事实」。'''

    #: 与 `Permission` 的值同一个命名空间（`资源:动作`）。⛔ 不许与任何权限点重名。
    key: str
    #: 给人看的一句话：这条能力到底允许什么。
    what: str
    #: 角色门里列的角色（不含绕过 —— 派单员另有 BYPASS_ROLES）。
    roles: tuple[str, ...]
    #: read / write —— 审计覆盖按它分（写能力要有动作码，或者写清为什么没有）。
    kind: str
    #: 真实角色门所在的位置（`相对路径:行号`）—— 判据去那里核它真的在。
    gate: str
    #: 为什么它至今不是权限点（一句话）。
    why_not_permission: str
    #: **什么时候把它收成真正的权限点**（例外要留退出条件）。
    when_to_remove: str


#: ⛔ 键与角色都要拿来判据核。新增一条时：先把 `gate` 指向的那一行读一遍。
ROLE_CAPABILITIES: tuple[RoleCapability, ...] = (
    RoleCapability(
        key='address:manage',
        what='地址与联系人：常用线路、联系人、地点（含图片）',
        roles=('shipper', 'dispatcher'),
        kind='write',
        gate='backend/app/api/v1/shipper.py:30',
        why_not_permission='这一整块是「按人分区」的：货主管自己的地址库，派单员用同一套接口管代理下单要用的地址；'
                            '权限点表述不了「只能动自己那一份」，那是 scope 才管的事。',
        when_to_remove='如果哪天把 scope=own 的权限点体系补全（`order:read_own` 那种已经在用了），'
                        '这块可以收成 `address:manage` + scope=own。',
    ),
    RoleCapability(
        key='place:manage',
        what='地点库与地点分组（谁都能标自己的常用地点，派单员另有发布/下架）',
        roles=('shipper', 'dispatcher'),
        kind='write',
        gate='backend/app/api/v1/place_categories.py:42',
        why_not_permission='同上：地点是**按人**的。派单员多出来的「发布/下架」由 `places.py:173 DispatcherOnly` 单独守。',
        when_to_remove='与 address:manage 同批（scope 体系补全时）。',
    ),
    RoleCapability(
        key='unit_conversion:manage',
        what='单位换算（一车=8 方那类），货主与派单员都能自己设',
        roles=('shipper', 'dispatcher'),
        kind='write',
        gate='backend/app/api/v1/unit_conversions.py:44',
        why_not_permission='它是**全局共享**的一份换算表，没有「谁的那一份」可分，'
                            '所以当初直接按角色开放（用户 2026-09-24 明确要求货主也能设）。',
        when_to_remove='如果哪天它要收成派单员专属，改成 `require_permission(UNIT_CONVERSION_MANAGE)` 即可 ——'
                        '那时这一条连同 UI/AI 两端的引用一起删。',
    ),
    RoleCapability(
        key='shipper_ledger:read_own',
        what='货主自己的账（明细与汇总，只读）',
        roles=('shipper',),
        kind='read',
        gate='backend/app/api/v1/shipper_ledger.py:67',
        why_not_permission='`ledger:read_own` 只写在 `ROLE_PERMISSIONS` 里，**端点上一处都没用**；'
                            '真正常在用的是这个角色门（`ShipperOnly`）。两边同时存在，说不清谁说了算。',
        when_to_remove='把端点接回 `require_permission(Permission.LEDGER_READ_OWN)` 的那一天（那时这条删掉，'
                        'UI/AI 改问权限点）。在那之前，它是这一块**唯一能问的名字**。',
    ),
    RoleCapability(
        key='vehicle:manage',
        what='车辆名册与「这辆车归哪个司机」',
        roles=('dispatcher',),
        kind='write',
        gate='backend/app/api/v1/vehicles.py:46',
        why_not_permission='它的授权是**体内角色判断**（`_must_dispatcher`）而不是权限点 ——'
                            '属于那 35 处「体内门槛」棘轮里的一处；本轮不搬它（搬它要动端点鉴权）。',
        when_to_remove='体内门槛棘轮往下降、把它接成 `require_permission(...)` 的那一天。',
    ),
)

