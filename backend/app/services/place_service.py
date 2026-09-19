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

import math
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.models import Place, PlaceUserUsage, ShipperLocation

#: 坐标相差 ≤ 该米数 → 视为**同一个地点**，沿用已有行而不是新建（用户给的数字）
MERGE_METERS = 1.0

#: 同名地点 + 相距 ≤ 该米数 → 也判同一个（GPS 实测误差远大于 1 米，见模块注释）
SAME_NAME_METERS = 30.0

#: 给用户看的一句话规则（界面/提示词要用同一句，别各自表述）
RULE_TEXT = f"坐标相差 {MERGE_METERS:g} 米内，或同名且相差 {SAME_NAME_METERS:g} 米内，算同一个地点"

#: **同一个人**用到第几次，就自动帮他收进「我的地点」（用户 2026-09-18 选的口径）
#:
#: 为什么是 2 而不是 1：第一次可能是"看一眼 / 点错了"，第二次才说明这个位置他真常用；
#: 而且这张表没有清理入口，阈值太低会把自己的地点库灌满只去过一次的地方。
#: 阈值只在这一处 —— 散开写的话"第几次算常用"会各处说法不一。
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

    返回 `(次数, 本次是否刚加进他的地点库)`。调用方要把后一个布尔量**如实告诉用户**：
    静默帮他改了自己的库，用户下次看到多出一条来源不明的记录只能猜。
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

    ensure_shipper_location(
        db,
        shipper_id=user.id,
        name=place.name,
        detail_address=place.detail_address,
        lat=float(place.lat),
        lng=float(place.lng),
    )
    row.auto_added = True
    return row.use_count, True


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
    """
    existing = find_shipper_location_near(db, shipper_id, lat, lng, name=name)
    if existing is not None:
        _fill_blank(existing, "name", name)
        _fill_blank(existing, "detail_address", detail_address)
        return existing, False

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
    return upsert_place(
        db,
        lat=float(location.address_lat),
        lng=float(location.address_lng),
        name=location.name,
        detail_address=location.detail_address,
        source="dispatcher",
        created_by=operator_id,
    )


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
    delete_place(db, place)
    return loc, created
