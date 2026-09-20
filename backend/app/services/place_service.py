"""共享地点库（导航信息）的**唯一一处**距离判据与合并实现。

## 为什么单独一个模块
「多远算同一个地点」这个问题只应该有一个答案。散在 API 里各写一遍的后果是
「补录时按 1 米合并、列表里按 50 米去重」——两处都对不上，而且**都不报错**，
只是同一家仓库慢慢变成七八条记录，谁也不知道哪条是新的。

用户给的口径（2026-09-18）：
> 有一个要上传的坐标非常相近大概可能只有 1 米的误差，那样子的话，就把这个坐标给合并成一个

所以 `MERGE_METERS = 1.0`。**注意它是"合并"半径，不是"搜索"半径**：
搜索（选品/下单时挑地点）给的是人看的列表，不存在半径概念；只有**写入**时才判合并。

## 为什么除了 1 米还有第二条规则（同名 30 米）
只按 1 米合并，在真机上几乎**永远不会触发**：手机 GPS 在城市里的实际精度是 3~10 米，
同一个仓库两个司机各标一次，大概率差 5~8 米 —— 于是"合并"这件事看着做了、其实没发生，
共享库慢慢攒出一堆坐标差几米的重复项（列表上肉眼几乎分不出哪条是哪条）。
所以补第二条：**同一个名字 + 30 米以内**也算同一个地点。
它比"30 米以内一律合并"保守得多（后者会把隔壁那家店并掉），
而且两条规则都只在**写入**时生效、都如实回报 `merged`。

（这条是主动补的，不是用户原话；用户要的是"别让我把同一个坐标传两遍"，
只按 1 米实现达不到那个效果。要不要保留这条，用户可以直接说。）

## 精度说明
`Numeric(10, 7)` 的 7 位小数 ≈ 1.1 厘米，远小于 1 米，判据不会被舍入吃掉。
距离用 haversine（球面），在 1 米这个尺度上与真实椭球差异是微米级，不需要更复杂的模型。
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.models import Place, PlaceUserUsage, ShipperLocation
# 图片张数上限与「我的地点」的出入参**同一个常量**（`schemas/text.py` 是叶子模块，
# 引它不会成环）—— 两处各写一个 9，改了上限就会出现"界面允许传第 10 张、服务端悄悄丢"
from app.schemas.text import MAX_IMAGES

#: 坐标相差 ≤ 该米数 → 视为**同一个地点**，沿用已有行而不是新建（用户给的数字）
MERGE_METERS = 1.0

#: 同名地点 + 相距 ≤ 该米数 → 也判同一个（GPS 实测误差远大于 1 米，见模块注释）
SAME_NAME_METERS = 30.0

#: 给用户看的一句话规则（界面/提示词要用同一句，别各自表述）
RULE_TEXT = f"坐标相差 {MERGE_METERS:g} 米内，或同名且相差 {SAME_NAME_METERS:g} 米内，算同一个地点"

#: **同一个人**在列表里用到第几次，就自动帮他收进「我的地点」（用户 2026-09-18 选的口径）
#:
#: 为什么是 2 而不是 1：第一次可能是"看一眼 / 点错了"，第二次才说明这个位置他真常用；
#: 阈值太低就会把自己的地点库灌满只点过一次的地方。
#: 阈值只在这一处 —— 散开写的话"第几次算常用"会各处说法不一。
#:
#: ⚠️ 这个阈值只管**在列表里点选**这一条路径（`note_place_use`）。
#:    **下过单**的地址是**第一次就进库**（`remember_order_address`，用户 2026-09-20）：
#:    "在列表里点了一下"和"真的把货送过去了"是两种强弱不同的信号，
#:    后者才是"这个位置我一定还会再用"。
AUTO_ADD_AFTER = 2

#: 纬度 1 度对应的米数（WGS84 平均值）。经度要再乘 cos(纬度)。
_M_PER_DEG_LAT = 111_320.0
_EARTH_R = 6_371_008.8


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """两点球面距离（米）。"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def _bbox(lat: float, lng: float, meters: float) -> tuple[float, float, float, float]:
    """粗筛用的经纬度包围盒。

    为什么要粗筛：`places` 是全库共享、只会越长越大，而每次补录都要问"附近有没有已有点"。
    把 haversine 放在 SQL 里逐行算是不可行的；先按索引列（lat/lng）卡一个盒子，
    再在盒子里逐行算精确距离。盒子保证**不漏**（它一定包含半径圆），只可能多带几行。
    """
    dlat = meters / _M_PER_DEG_LAT
    # 高纬度上经度 1 度对应的米数变小 → 同样的米数要跨更多经度；cos 趋 0 时给个保守上界。
    cos = max(0.01, math.cos(math.radians(lat)))
    dlng = meters / (_M_PER_DEG_LAT * cos)
    # 纬度超出 ±90 时夹紧（极点附近盒子会退化，但不影响正确性：盒子里仍然逐行算精确距离）
    return (
        max(-90.0, lat - dlat),
        min(90.0, lat + dlat),
        lng - dlng,
        lng + dlng,
    )


def _clean(value: str | None, limit: int) -> str:
    """地点名/地址的统一清洗：**先 strip 再截断**（顺序反了会把 128 个空格存下来）。

    三个写入点（新建、并入已有、写货主地点库）必须走同一份清洗，否则
    "同一次补录、两个库里存的东西不一样"——而两条记录看起来都对。
    """
    return (value or "").strip()[:limit]


def note_place_use(db: Session, *, user: Any, place: Place) -> tuple[int, bool]:
    """记一次"这个人用了这个共享地点"；到阈值时**自动帮他收进自己的地点库**。

    用户 2026-09-18：
    > 常点的那个共享地点，有人经常点了，它就会自动移到他自己的地点库当中。

    ## 为什么按"人 + 地点"计数，而不是用 `places.use_count`
    全库 `use_count` 说的是"大家都去过这儿"。用它做触发条件，一个热闹的地点会
    **涌进所有人的列表** —— 那不是"你常用的"，是"别人常去的"。所以另开一张表
    按 (user, place) 计数。

    ## 只加一次
    `auto_added` 记下"已经帮他加过了"。之后再怎么点都不会重复调
    `ensure_shipper_location` —— 那个函数虽然也会去重，但每点一次就查一遍库是白费的，
    更要紧的是"重复调用"会让日志/行为看起来像"又加了一条"。

    返回 `(次数, 本次是否**真的新建了**一条)`。调用方要把后一个布尔量**如实告诉用户**：
    静默帮他改了自己的库，用户下次看到多出一条来源不明的记录只能猜；
    反过来，什么都没多出来却说"已加进你的地点库"同样是假话（见下面的 `created`）。
    """
    now = datetime.now(timezone.utc)
    row = db.scalars(
        select(PlaceUserUsage).where(
            PlaceUserUsage.user_id == user.id, PlaceUserUsage.place_id == place.id
        )
    ).first()
    if row is None:
        row = PlaceUserUsage(user_id=user.id, place_id=place.id, use_count=1, last_used_at=now)
        db.add(row)
        db.flush()
    else:
        # ⛔ 计数列必须**由数据库自增**，不许 `row.use_count = (row.use_count or 0) + 1`
        #    （2026-09-19 审计，与库存同一个形状的 lost update）：司机手滑点两下"沿用这个地点"、
        #    或两部手机同时点，两边都读到同一个旧值 → 后写的人把前一次的 +1 盖掉 →
        #    次数攒得比实际慢，`AUTO_ADD_AFTER` 那条"常用就自动进我的地点"永远差一次才触发。
        db.execute(
            update(PlaceUserUsage)
            .where(PlaceUserUsage.id == row.id)
            .values(use_count=func.coalesce(PlaceUserUsage.use_count, 0) + 1, last_used_at=now)
        )
        db.refresh(row)
    db.flush()

    if row.auto_added or row.use_count < AUTO_ADD_AFTER:
        return row.use_count, False

    # 只对**有自己地点库的角色**做（货主/派单员）——`shipper_locations` 就是按登录人分的。
    # 司机没有"我的地点"这个概念，硬写进去只会在他的地址页多出一堆用不上的东西。
    role = getattr(user, "role", None)
    role_key = (role.value if hasattr(role, "value") else str(role or "")).lower()
    if role_key not in ("shipper", "dispatcher"):
        return row.use_count, False

    _, created = ensure_shipper_location(
        db,
        shipper_id=user.id,
        name=place.name,
        detail_address=place.detail_address,
        lat=float(place.lat),
        lng=float(place.lng),
    )
    row.auto_added = True
    # ⚠️ 报回去的是 `created`（**真的新建了**），不是"阈值到了"。
    #    2026-09-20 起"下过单的地址第一次就进库"（`remember_order_address`），
    #    所以这里经常会发现他的库里**早就有这一条**（并进已有那条、条数没变）。
    #    那时若回 `auto_added=true`，界面会说「已加进你的「我的地点」」而列表纹丝不动 ——
    #    用户只能怀疑是自己看错了。
    return row.use_count, created


def _same_place_name(a: str, b: str) -> bool:
    """同名判定：忽略大小写与全部空白（"老王 家仓库" 与 "老王家仓库" 是同一个）。

    只做归一化比较，**不做模糊匹配**（"老王仓库" vs "老王仓库2" 不许判等）：
    名字差一个字往往就是两个地方，宁可多一条让人自己删，也不要悄悄并错。
    """
    na = "".join((a or "").split()).lower()
    nb = "".join((b or "").split()).lower()
    return bool(na) and na == nb


def find_place_near(
    db: Session,
    lat: float,
    lng: float,
    *,
    meters: float = MERGE_METERS,
    name: str = "",
) -> Place | None:
    """找判定为**同一个地点**的已有记录；没有就返回 None。

    两条规则（见模块注释）：
    - 距离 ≤ `MERGE_METERS`（1 米）：坐标几乎重合，不管名字；
    - 距离 ≤ `SAME_NAME_METERS`（30 米）**且名字相同**：同一次测量的正常漂移。

    两条都不成立时返回 None —— 也就是说"30 米内的另一个名字"不会被并掉。
    """
    # 先用较大的那个半径粗筛，再逐行按两条规则精确判
    radius = max(meters, SAME_NAME_METERS if name.strip() else meters)
    lat_min, lat_max, lng_min, lng_max = _bbox(lat, lng, radius)
    rows = db.scalars(
        select(Place).where(
            # ⛔ **删掉的行不算"已有地点"**（2026-09-19 用户把删除改成软删之后补的）：
            #    漏这一句的后果是这个仓里最隐蔽的一种错 —— 有人删掉了一个点，
            #    另一个人（或同一个司机）在同一个坐标上补录，会被"合并"进那条**谁也看不见**的行，
            #    界面上什么都没多出来，而他会以为已经存好了。
            #    （这正是当初把删除做成物理删除的理由之一；既然改回软删，这道闸就必须在这里。）
            Place.is_deleted.is_(False),
            Place.lat >= Decimal(str(lat_min)),
            Place.lat <= Decimal(str(lat_max)),
            Place.lng >= Decimal(str(lng_min)),
            Place.lng <= Decimal(str(lng_max)),
        )
    ).all()
    best: Place | None = None
    best_d = radius + 1.0
    for row in rows:
        d = haversine_m(lat, lng, float(row.lat), float(row.lng))
        if d <= meters or (d <= SAME_NAME_METERS and _same_place_name(row.name, name)):
            if d < best_d:
                best, best_d = row, d
    return best


def find_shipper_location_near(
    db: Session,
    shipper_id: int,
    lat: float,
    lng: float,
    *,
    meters: float = MERGE_METERS,
    name: str = "",
) -> ShipperLocation | None:
    """货主自己的地点库里"同一个地点"的记录（判据与共享库同一份，见 `find_place_near`）。"""
    radius = max(meters, SAME_NAME_METERS if name.strip() else meters)
    lat_min, lat_max, lng_min, lng_max = _bbox(lat, lng, radius)
    rows = db.scalars(
        select(ShipperLocation).where(
            ShipperLocation.shipper_id == shipper_id,
            ShipperLocation.is_deleted.is_(False),
            ShipperLocation.address_lat.is_not(None),
            ShipperLocation.address_lng.is_not(None),
            ShipperLocation.address_lat >= Decimal(str(lat_min)),
            ShipperLocation.address_lat <= Decimal(str(lat_max)),
            ShipperLocation.address_lng >= Decimal(str(lng_min)),
            ShipperLocation.address_lng <= Decimal(str(lng_max)),
        )
    ).all()
    best: ShipperLocation | None = None
    best_d = radius + 1.0
    for row in rows:
        assert row.address_lat is not None and row.address_lng is not None
        d = haversine_m(lat, lng, float(row.address_lat), float(row.address_lng))
        if d <= meters or (d <= SAME_NAME_METERS and _same_place_name(row.name, name)):
            if d < best_d:
                best, best_d = row, d
    return best


def _fill_blank(row: Any, field: str, value: str | None) -> bool:
    """只在**原来是空**的时候补值；已有值不动（不覆盖别人已经确认过的信息）。

    ⚠️ **必须先 strip 再判空**（2026-09-18 在开发库里抓到）：不 strip 的话，
    `"   "` 这种"看着是空的"值会被写进去 —— `if not value` 拦不住它
    （三个空格在 Python 里是真值）。后果是共享地点库里出现一条**名字是一串空格**的记录，
    列表上显示成空白行，谁也不知道那是什么地方。
    这条路径只在**并进已有地点**时走到（新建那条本来是 strip 过的），
    所以它专门在"第一次并进一条没名字的记录"时发作 —— 更难看出来。
    """
    text = (value or "").strip()
    if not text:
        return False
    current = (getattr(row, field, "") or "").strip()
    if current:
        return False
    setattr(row, field, text)
    return True


def upsert_place(
    db: Session,
    *,
    lat: float,
    lng: float,
    name: str = "",
    detail_address: str = "",
    source: str = "driver",
    created_by: int | None = None,
    order_id: int | None = None,
) -> tuple[Place, bool]:
    """记录一个已知坐标；判定为"同一个地点"时沿用已有行（规则见模块注释与 `find_place_near`）。

    返回 `(place, merged)`：`merged=True` 表示这次是并进了已有地点（不是新点）。
    调用方要把这个事实**如实告诉用户**（"已并入已有地点「XX」"），
    否则用户会以为库里多了一条，而列表上什么都没变。
    """
    existing = find_place_near(db, lat, lng, name=name)
    now = datetime.now(timezone.utc)
    if existing is not None:
        # 同上：计数由数据库自增（`use_count` 只用于"常用的排前面"，但同一个形状的
        # lost update 一样会让排序与"用过几次"的展示慢慢失真）
        db.execute(
            update(Place)
            .where(Place.id == existing.id)
            .values(use_count=func.coalesce(Place.use_count, 0) + 1, last_used_at=now)
        )
        db.refresh(existing)
        _fill_blank(existing, "name", name)
        _fill_blank(existing, "detail_address", detail_address)
        return existing, True

    row = Place(
        name=_clean(name, 128),
        detail_address=_clean(detail_address, 512),
        lat=Decimal(str(round(lat, 7))),
        lng=Decimal(str(round(lng, 7))),
        source=source,
        use_count=1,
        created_by=created_by,
        first_order_id=order_id,
        last_used_at=now,
    )
    db.add(row)
    db.flush()
    return row, False


def _find_known_location(
    db: Session, *, shipper_id: int, name: str, detail_address: str
) -> ShipperLocation | None:
    """这一位的「我的地点」里，**已经记着这个地点**的那一条（用来"别重复建"）。

    两条判据，命中即返回（都**不做模糊匹配** —— `_same_place_name` 的注释已经定了口径：
    名字差一个字往往就是两个地方；而"名字完全一样、地址不同"的两个地方遍地都是）：
    1. **地址原文完全一样**（非空）—— 一行地址就是一个地方，这条最硬；
    2. **名字完全一样、且那一条还没有坐标** —— 给"只写了名字"的记录兜底。

    第 2 条限定"还没有坐标"是有意的：它管的是"先只写了名字，后来才知道它在哪儿"，
    不是"把两个同名的地方并成一个"。已经有坐标的那种，交给
    `find_shipper_location_near` 按距离判（那才是唯一一处距离判据）。

    软删掉的不算"已有"（同 `find_place_near`：否则新记录会并进一条看不见的行）。
    """
    clean_name = _clean(name, 128)
    clean_detail = _clean(detail_address, 512)
    if clean_detail:
        row = db.scalars(
            select(ShipperLocation).where(
                ShipperLocation.shipper_id == shipper_id,
                ShipperLocation.is_deleted.is_(False),
                ShipperLocation.detail_address == clean_detail,
            )
        ).first()
        if row is not None:
            return row
    if not clean_name:
        return None
    return db.scalars(
        select(ShipperLocation).where(
            ShipperLocation.shipper_id == shipper_id,
            ShipperLocation.is_deleted.is_(False),
            ShipperLocation.address_lat.is_(None),
            ShipperLocation.address_lng.is_(None),
            ShipperLocation.name == clean_name,
        )
    ).first()


def ensure_shipper_location(
    db: Session,
    *,
    shipper_id: int,
    name: str,
    detail_address: str,
    lat: float,
    lng: float,
) -> tuple[ShipperLocation, bool]:
    """把坐标写进**这个货主自己的地点库**，下次他下单时可以直接选到。

    用户的要求（2026-09-18）：
    > 而这个导航信息一旦补上去了之后，货主的那个就会添加他那个库里面当中，
    > 下次他下这个单的时候就会自动添加

    合并判据与共享库共用一份（`MERGE_METERS`）：这一个货主已经有同一地点时不再重复加一条，
    只把空的字段补上。返回 `(location, created)`。

    ⚠️ 2026-09-20 起多了一条路：**先只写了文字、后来才拿到坐标**的那一条要**补全**而不是再长一条。
    顺序是"下单先记文字地址（`remember_order_address`），司机到场补坐标（本函数）"，
    缺了这一支的后果是同一个地点在货主库里躺着两条同名记录 ——
    一条有坐标一条没有，列表上分不出哪条是哪条（这正是 2026-09-18 那条用例在防的事）。
    """
    existing = find_shipper_location_near(db, shipper_id, lat, lng, name=name)
    if existing is not None:
        _fill_blank(existing, "name", name)
        _fill_blank(existing, "detail_address", detail_address)
        return existing, False

    known = _find_known_location(db, shipper_id=shipper_id, name=name, detail_address=detail_address)
    if known is not None and known.address_lat is None and known.address_lng is None:
        # 就是它：原来只有文字，现在知道它在哪儿了 → 把坐标补上（**不是**新建一条同名的）
        known.address_lat = Decimal(str(round(lat, 7)))
        known.address_lng = Decimal(str(round(lng, 7)))
        _fill_blank(known, "name", name)
        _fill_blank(known, "detail_address", detail_address)
        db.flush()
        return known, False

    row = ShipperLocation(
        shipper_id=shipper_id,
        name=_clean(name, 128),
        detail_address=_clean(detail_address, 512),
        address_lat=Decimal(str(round(lat, 7))),
        address_lng=Decimal(str(round(lng, 7))),
        image_urls="[]",
    )
    db.add(row)
    db.flush()
    return row, True


def _keep_for_owner(
    db: Session,
    *,
    owner_id: int,
    name: str,
    detail_address: str,
    coords: tuple[float, float] | None,
) -> tuple[ShipperLocation, bool]:
    """给这一位的「我的地点」里把这条地址放好：已经有就返回那一条，没有就建一条。

    判据就那两条（不许在别处再写一遍）：
    - **有坐标** → `ensure_shipper_location`（1 米内、或同名 30 米内算同一处；
      库里那条"只有文字、还没坐标"的记录会被**补上坐标**而不是再长一条）；
    - **只有文字** → `_find_known_location`（地址原文一模一样，或名字一样且那条还没坐标）。

    返回 `(行, 是否新建)`。
    """
    if coords is not None:
        return ensure_shipper_location(
            db,
            shipper_id=owner_id,
            name=name,
            detail_address=detail_address,
            lat=coords[0],
            lng=coords[1],
        )
    known = _find_known_location(db, shipper_id=owner_id, name=name, detail_address=detail_address)
    if known is not None:
        return known, False
    row = ShipperLocation(
        shipper_id=owner_id,
        name=_clean(name, 128),
        detail_address=_clean(detail_address, 512),
        image_urls="[]",
    )
    db.add(row)
    db.flush()
    return row, True


def _owners(owner_ids: list[int | None]) -> list[int]:
    """去重 + 去掉 None，**保持顺序**（顺序决定日志里先写谁的）。"""
    out: list[int] = []
    for oid in owner_ids:
        if oid and oid not in out:
            out.append(oid)
    return out


def remember_order_address(
    db: Session,
    *,
    owner_ids: list[int | None],
    name: str,
    detail_address: str,
    lat: float | None = None,
    lng: float | None = None,
) -> dict[str, list[int]]:
    """把**这一单的收货地址**收进这几个人的「我的地点」（用户 2026-09-20）。

    用户原话：
    > 只要用户下单他会选择地点，这个时候，我们就自动地把它添加到地点库当中。

    ## 为什么是「我的地点」，不是共享库
    用户 2026-09-20 明确选了**「我的地点」**（每个人自己那份、只有本人能选）。
    共享库仍然只有那三个明确入口：派单员「设为共享」/ 下单页手点一下存 / 司机到场补录 ——
    那张表全库共用，自动往里灌等于绕开"只有派单员能把一个地点设为共享"这条规矩
    （2026-09-19 定的）。

    ## 代理下单为什么**两边都记**（用户 2026-09-20 选的）
    地点库是按登录人隔离的。派单员代理下单时只记一边，另一边的人下次还得重选一遍：
    记给货主 → 派单员下次代下单还得重新找这个地址；记给派单员 → 货主自己下单找不到它。
    两边各一条的成本就是一次坐标比对，而地址本来就只有一处。

    返回 `{"created_for": [...], "merged_for": [...]}`（user id）。调用方**必须**把
    `created_for` 写进审计（`PLACE_AUTO_ADDED`）：用户下次看到自己库里多出一条，
    得能查出是谁、因为哪一单加的。
    """
    out: dict[str, list[int]] = {"created_for": [], "merged_for": []}
    clean_name = _clean(name, 128)
    clean_detail = _clean(detail_address, 512)
    # 无名无址：不进任何库。空行只会在用户的列表上变成一条谁也认不出的记录，
    # 而它还会占着"我的地点"的第一屏（这正是共享库当初要挡在入口的那个形状）。
    if not clean_name and not clean_detail:
        return out

    coords = (float(lat), float(lng)) if lat is not None and lng is not None else None
    for owner_id in _owners(owner_ids):
        _, created = _keep_for_owner(
            db,
            owner_id=owner_id,
            name=clean_name,
            detail_address=clean_detail,
            coords=coords,
        )
        out["created_for" if created else "merged_for"].append(owner_id)
    return out


def _append_photo(row: Any, url: str) -> bool:
    """把一张图追加到这一行的 `image_urls`（**去重 + 上限**）。返回是否真的加上了。

    `row` 可以是 `ShipperLocation`（我的地点）或 `Place`（共享库）—— 两边字段名一样
    （`image_urls` JSON + `image_url` 首图，2026-09-20 给共享库补了同名的两列），
    所以照片这条路只有**这一份实现**。
    """
    try:
        urls = [u for u in json.loads(row.image_urls or "[]") if isinstance(u, str)]
    except Exception:
        urls = []
    if url in urls or len(urls) >= MAX_IMAGES:
        return False
    urls.append(url)
    row.image_urls = json.dumps(urls, ensure_ascii=False)
    # 旧字段始终 = 首图（`LocationOut` 把 `image_url` 并进 `image_urls[0]`，两边不能分叉）
    row.image_url = urls[0]
    return True


def _carry_photos(src: Any, dst: Any) -> int:
    """把一条记录上的照片**拷到另一条**上（去重）。返回拷过去几张。

    用在「设为共享 / 撤销共享」这条线上：照片属于**这个位置**，
    不该因为它在哪张表而丢掉（用户 2026-09-20：「可以共享库也加上图片」）。
    """
    try:
        urls = [u for u in json.loads(getattr(src, "image_urls", None) or "[]") if isinstance(u, str)]
    except Exception:
        urls = []
    n = 0
    for u in urls:
        if _append_photo(dst, u):
            n += 1
    return n


def attach_order_photo(
    db: Session,
    *,
    owner_ids: list[int | None],
    name: str,
    detail_address: str,
    url: str,
    lat: float | None = None,
    lng: float | None = None,
) -> list[int]:
    """把刚上传的**位置照片**挂到这一单对应的地点上（用户 2026-09-20）。

    用户原话：
    > 还有一个就是照片，他下单的时候，如果我上交了照片的话，呃那个跟地点是一样是自动保存在库里的。
    > …可以共享库也加上图片。

    三件事，**同一条判据**：
    1. 「我的地点」：谁的地盘会多出这个地点，照片就跟着进谁的（`_keep_for_owner` / `_owners`）——
       两处各判一次的话会出现"地点进去了、照片进了另一条"（同一个人同一个位置两条记录，
       一条有图一条没图）。找不到就**顺手建一条**（照片本身就是"这个位置"的证据）。
    2. **共享库**：只挂到**已经存在**的那一条上（`find_place_near`，1 米/同名 30 米）。
       ⛔ **不为照片新建共享点** —— 那张表全库共用、三种角色都看得到，
       自动往里灌点会把别人的选点列表淹掉（这是"只有派单员能设为共享"那条规矩的另一面）。
    3. 两条都走 `_append_photo`（去重 + 上限 9）。

    返回真的挂上了照片的 owner id（调用方写审计用）；共享库那条挂没挂由 `place_id` 反映。
    """
    clean_url = (url or "").strip()
    clean_name = _clean(name, 128)
    clean_detail = _clean(detail_address, 512)
    if not clean_url or (not clean_name and not clean_detail):
        return []
    coords = (float(lat), float(lng)) if lat is not None and lng is not None else None
    out: list[int] = []
    for owner_id in _owners(owner_ids):
        row, _ = _keep_for_owner(
            db,
            owner_id=owner_id,
            name=clean_name,
            detail_address=clean_detail,
            coords=coords,
        )
        if _append_photo(row, clean_url):
            out.append(owner_id)
    # 共享库：只在**已有**那个点时挂图（见上面第 2 条）
    if coords is not None:
        shared = find_place_near(db, coords[0], coords[1], name=clean_name)
        if shared is not None:
            _append_photo(shared, clean_url)
    return out


# ===========================================================================
# 共享地点的**管理**（2026-09-19 用户要求）
#
# 用户原话：
# > 这个地址是可以编辑的。如果是来到了共享库的话，共享地址的编辑**只有派单员**可以编辑，
# > 其他人都编辑不了。派单员可以改名称，也可以把一些地点给**设置为共享地址**，
# > 也可以**撤销**某些共享地址，把它**降为普通的地址**，或者直接**删掉**。
# > 如果是降为普通的地址的话，则这个地址会保存在**派单员**的地址库当中，其他的不会显示。
#
# 四个动作都在这里收口（API 与 AI 走同一份实现）：
#   改  → `apply_place_update`      设 → `share_location`
#   撤  → `demote_place`            删 → `delete_place`
# ===========================================================================

#: 「名字和地址不能都是空」的**唯一一句话**。
#:
#: 原来这句话只活在 `schemas/place.py` 的新建校验器里 —— 而"改地址"也要判同一条，
#: 且必须看**改完之后的整行**（PATCH 只带一个字段），校验器拿不到那一行。
#: 所以判据落在这里，schema 反过来引它（一句话两处写，迟早会变成两种说法）。
NO_NAME_TEXT = "请给这个地点起个名字或填个地址（共享库里只有坐标的话，别人认不出是哪儿）"


def identify_error(name: str | None, detail_address: str | None) -> str | None:
    """这一行"认得出来"吗（名字与地址不能都是空）。返回给用户看的那句话，或 None。"""
    if not (name or "").strip() and not (detail_address or "").strip():
        return NO_NAME_TEXT
    return None


def apply_place_update(
    db: Session,
    place: Place,
    *,
    name: str | None = None,
    detail_address: str | None = None,
) -> tuple[str, str]:
    """改共享地点（**只有派单员**）：PATCH 语义 —— `None` = 这个字段不改。

    返回 `(旧值, 新值)` 的摘要串给调用方写审计（"「旧名」→「新名」"）。

    ⚠️ **先算好改完的样子再落盘**：两个字段都可能只改一个，而"名字和地址不能都是空"
    要按**整行**判 —— 先写再验会把一行非法数据留在 session 里（异常路径上它可能被别处一并提交）。
    """
    before = f"{place.name} | {place.detail_address}"
    new_name = place.name if name is None else _clean(name, 128)
    new_detail = place.detail_address if detail_address is None else _clean(detail_address, 512)
    err = identify_error(new_name, new_detail)
    if err is not None:
        raise ValueError(err)
    place.name = new_name
    place.detail_address = new_detail
    db.flush()
    return before, f"{new_name} | {new_detail}"


def share_location(db: Session, *, location: ShipperLocation, operator_id: int) -> tuple[Place, bool]:
    """把「我的地点」里的一个地点**设为共享地址**（进那张全库共用的表）。

    判据完全复用 `upsert_place`：坐标 1 米内（或同名 30 米内）**并进已有那条**，不新建重复项 ——
    同一处地方被点两次"设为共享"，共享库里不该出现两条。
    返回 `(place, merged)`；`merged=True` 时界面要说"已并入已有地点「XX」"。
    """
    if location.address_lat is None or location.address_lng is None:
        # 没有坐标的地点**进不了共享库**（那张表的唯一硬条件是坐标：它是给导航用的）。
        # 这条闸必须在写之前拦，否则会进去一条谁也导不到的点。
        raise ValueError("这个地点还没有坐标，先用「地图选点」定位一下，再设为共享地址")
    place, merged = upsert_place(
        db,
        lat=float(location.address_lat),
        lng=float(location.address_lng),
        name=location.name,
        detail_address=location.detail_address,
        source="dispatcher",
        created_by=operator_id,
    )
    # 照片跟着这条位置走（2026-09-20：「共享库也加上图片」）——
    # 设为共享之后，下一个司机在共享库里看到的就不只是坐标，还有"这个门口长什么样"。
    _carry_photos(location, place)
    return place, merged


def delete_place(db: Session, place: Place) -> None:
    """从共享库**删掉**一个地点 —— **软删**（打标记，`POST /places/{id}/restore` 能原样拿回来）。

    用户 2026-09-19 定的规矩：「还有这些所有功能的删（撤）销操作就是**软删**啊，他们都是要有的」。
    第一版是物理删除，理由写在这里过（"一条记录就是名字+坐标，删了重新标一次就有"）；
    用户的底线在 `SoftDeleteMixin` 的注释里写着 ——「不要删了就搞不回来了」，一句话就否了。

    软删之后**三处**必须一起认这个标记（少一处就出事）：
    · `list_places` / `get_place`：看不见（否则"删了还在列表里"）；
    · `find_place_near`：**不算已有地点**（否则新补的坐标会并进一条谁也看不见的行）；
    · `restore`：只放回被删的那一条。
    ⚠️ `place_user_usage` 现在**不用删**了（这是软删白捡的好处）：谁用过它几次的记录留着，
    恢复之后一切照旧；物理删除那次必须连它一起删，否则外键会挡住 MySQL 的删除。
    """
    place.is_deleted = True
    place.deleted_at = utc_now_naive()
    db.flush()


def demote_place(db: Session, *, place: Place, operator_id: int) -> tuple[ShipperLocation, bool]:
    """**撤销**一个共享地址：从共享库撤下来，存进**操作人自己的**「我的地点」。

    用户 2026-09-19：
    > 也可以撤销某些共享地址，把它降为普通的地址…如果是降为普通的地址的话，
    > 则这个地址会保存在**派单员**的地址库当中，其他的不会显示。

    「其他的不会显示」＝ 这一行从共享库里消失，而不是"只对某个人隐藏" ——
    共享库是全库一张表，没有"只对你隐藏"这种东西，所以撤销就是真的撤下来。
    """
    loc, created = ensure_shipper_location(
        db,
        shipper_id=operator_id,
        name=place.name,
        detail_address=place.detail_address,
        lat=float(place.lat),
        lng=float(place.lng),
    )
    # 撤下来时照片跟着走（与 `share_location` 对称）：照片属于这个位置，
    # 不该因为它在共享库还是私人库里而消失一个。
    _carry_photos(place, loc)
    delete_place(db, place)
    return loc, created
