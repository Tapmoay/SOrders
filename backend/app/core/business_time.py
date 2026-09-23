"""业务时间：库里存 UTC，**报表/账单按业务当地日**分桶（2026-09-19 审计 R12-M11）。

## 为什么要单独一个模块
这条缺陷的表现是"**每天有 8 小时，日报显示的是前一天的数**"：

- 写库用的是 UTC（`order_flow._now() = datetime.now(timezone.utc)`），
  `orders.delivered_at` 存的是 UTC 时刻（SQLite 里读回来是 naive，值仍是 UTC）；
- 而报表按 `o.delivered_at.date()` 分桶，手机/派单员传的锚点日期是**当地日**
  （Android `ReportCenterViewModel` 用 `LocalDate.now()`）。

东八区下，当地 00:00~08:00 送达的单，UTC 时刻还在**前一天** → 它们被分到前一天：
派单员早上 7 点打开「今天的营业纵览」，看到的是 0（或者昨天的数），
而同一批单在「司机运费结算」页（按区间取、不按日分桶）里明明在。两个页面都不报错。

（这条是我自己写报表回归测试时撞出来的：刚送达的单在 `mode=day&date=<今天>` 里 delta=0，
换成该单 `delivered_at` 的 UTC 日期才对得上 —— 于是顺着查到了这里。）

## 口径
- **业务时区固定为东八区**：用户、司机、货主都在国内，单据上的"今天"就是当地的今天。
  做成配置项的话，"哪一天算今天"就会随部署环境漂移，而报表数字必须可复核。
- 读回来的时间**可能是 naive**（SQLite / 未带时区的列）：按"写进去的就是 UTC"处理
  （见 `order_flow._now`），先补 tzinfo 再换算，两种形状都不会算错。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

#: 业务时区（东八区）。用户与业务都在国内，单据上的"今天"= 当地的今天。
BUSINESS_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def as_utc(dt: datetime) -> datetime:
    """把库里的时间归一成**带时区的 UTC**（naive 一律当成 UTC，那是写入方的口径）。"""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def business_local(dt: datetime) -> datetime:
    """UTC 时刻 → 业务当地时刻。"""
    return as_utc(dt).astimezone(BUSINESS_TZ)


def business_date(dt: datetime | None) -> date | None:
    """UTC 时刻 → **业务当地日**（报表分桶、账单归属日都用它）。"""
    return None if dt is None else business_local(dt).date()


def business_today() -> date:
    """业务当地的今天（服务端兜底用；客户端一般自己传锚点）。"""
    return datetime.now(timezone.utc).astimezone(BUSINESS_TZ).date()


def business_day_start_utc(d: date) -> datetime:
    """当地某一天的 00:00 → 对应的 **UTC naive** 时刻（与库里存的时间同形，可直接比）。

    用途：按"当地日区间"筛 `delivered_at`（司机运费结算、司机绩效）。
    直接拿当地日期去和 UTC 列比，会让当地 00:00~08:00 的记录漏掉
    （2026-09-19 审计 R12-M11：同一批单在报表里有、在结算页里没有）。
    """
    local_midnight = datetime(d.year, d.month, d.day, tzinfo=BUSINESS_TZ)
    return local_midnight.astimezone(timezone.utc).replace(tzinfo=None)


def business_range_utc(start: date, end: date) -> tuple[datetime, datetime]:
    """当地日区间 `[start, end]`（闭区间）→ UTC 的 `[起, 止)`（半开区间）。"""
    return business_day_start_utc(start), business_day_start_utc(end + timedelta(days=1))


def to_utc_naive(dt: datetime) -> datetime:
    """把一个**当地墙上时间**（客户端传的 `from`/`to`）换成库里那种 UTC naive 时刻。

    - 带时区的（`2026-09-19T00:00:00+08:00`）→ 直接换算；
    - 不带时区的（客户端就是这么传的：`2026-09-19T00:00:00`）→ **按业务当地时区解释**。

    两种形状都不会算错，而"直接拿去和 UTC 列比"会让当地 00:00~08:00 的记录漏掉
    （2026-09-19 审计 R12-M11：报表里有的单，在司机运费结算页里看不到）。
    """
    local = dt if dt.tzinfo is not None else dt.replace(tzinfo=BUSINESS_TZ)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def utc_now_naive() -> datetime:
    """「现在」在**库里那种 UTC naive** 形状下是什么 —— 任何"拿现在去比库里的时间列"
    都必须用它，不许用 `datetime.now()`。

    ⛔ `datetime.now()` 是**进程本地时间**（naive）；而库里的时间列按本模块的口径存的是
    **UTC**。两者相减就是固定的时区偏差，而且完全静默：

    - R14-9（2026-09-19 审计）：`GET /notifications?days=1` 用 `datetime.now() - 1天` 去比
      UTC 的 `created_at`，本机实测**少给 8 小时 / 1508 条**（"最近一天"变成"最近 16 小时"）。
      同一个 `days=30` 在这条接口（本地时间）与保留任务（UTC）上是两个基准，
      生产 MySQL 上 `created_at` 还是 `NOW()`（会话时区）——"保留 30 天"实际早删约 8 小时。
    - 软删除的 `deleted_at` 也踩过同一个坑：`orders` 写的是 UTC，而商品/定价/挂靠单位/
      运费模板/司机计费规则/地址写的是 `datetime.now()`，30 天隔离期因此**早 8 小时**到期。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_stamp(dt: datetime | None = None, *, fmt: str = "%m-%d %H:%M") -> str:
    """**印给人看**的时间戳（业务当地时刻），缺省 `MM-DD HH:MM`。

    ## 为什么必须走这一处（2026-09-23 第 18 轮并行渗透 A2-3）
    有两处把时间戳**写进订单数据里**（`internal_notes` 的 `[司机 09-20 23:10]` / `[派单指派 …]`），
    用的却是 `datetime.now(timezone.utc)` —— 当地 09-21 07:10 写的备注，单子上印着 `09-20 23:10`
    （连日期都跨了），而这段文本**一旦写进 `orders.internal_notes` 就再也改不了**
    （那是累计文本，历史不可追溯）。用户拿它跟司机对时间时，两边说的不是同一天。

    ⛔ 与 `utc_now_naive()` 的分工：那个是"拿去和库里比"的值，这个是"印给人看"的字。
    两者**不许混用**（拿这个去比时间列 = 又是 8 小时偏差；拿那个去印 = 用户看到 UTC）。
    """
    return business_local(dt if dt is not None else utc_now_naive()).strftime(fmt)
