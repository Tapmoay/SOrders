#!/usr/bin/env python3
"""FEAT-0022 车辆年检提醒 ＋ 库存偏低（按百分比）：两条**安静**的口径各自钉住。

用户口径（2026-10-11，逐字）：
  · 「关于这个车辆年检提醒啊，到我给那个车子建档案的时候会填一下就是这车的**上牌日期**。
     或者说是**上一个年检日期**啊方便我们去做一个提醒」；
  · 「**库存偏低**的话，我们**按百分比来算** —— 也就是说，他肯定会设置这个库存的报警嘛……
     然后我们在**报警的那个水平宽松一点**，就显示『库存偏低』，是这样子的。」

## 这两件事为什么必须有自己的判据

它们错起来**全都不报错、界面上还看着正常** —— 只会在某一天安静地告诉用户一件错的事：

| 少了这条判据 | 后果 | 谁会先发现 |
| --- | --- | --- |
| 「恰好等于阈值」被算成 danger | 用户按"已跌破"去紧急补货，其实还没跌破（口径反了） | 没人 |
| 偏低线不是百分比、而是另写一个常数 | 改阈值时两处对不上（扫描扫不出来、出入库却发得出） | 没人 |
| 两个日期都空也算到期 | 系统**自己编**一个到期日出来提醒用户（比不提醒坏得多） | 用户（"这车我没录过"） |
| 两格都录了却拿上牌日期算 | 到期日差好几年，而界面完全看不出来 | 没人 |
| 2/29 那天算错一天 | 四年才撞一次，真出问题时没人会想到是这里 | 没人 |
| 幂等键里没有到期日 | 同一次年检每天刷一条；或第二年的提醒永远发不出来 | 用户（"怎么老提醒"） |
| 逾期那条被降到 warn | 年检过期上路要罚款扣车，界面却按"待办"显示 | 没人 |
| 已经做了的类型留在 NOT_PRODUCED | 下一单以为它还缺字段，再"补"一遍 | 下一个人 |

R4-BOUNDARY-JUSTIFICATION: 本判据**只读文本**（backend 的迁移 / 模型 / 入出参 / 两个服务 /
入口 / 单测 ＋ 四份文档），不连库、不起服务、不写任何文件；
反向验证 _reverse_verify_inspection_and_near_low.py 注入后**逐字节还原**。
判据里的边界声明：
  · 「恰好等于阈值 = 偏低」是**用户口径**（"在报警的那个水平宽松一点"），不是我们自己挑的：
    等于阈值说明还没有跌破它，所以归 warn 而不是 danger；
  · 「到期日当天 = 临期」与既有的 `payable_kind`（第 0 天 = 临期）**同形** ——
    那一天车还能合法上路，说"已逾期"是错的话；
  · 「2/29 → 2/28」是**刻意**夹的：夹到 3/1 会让提醒比"满一年"晚一天，而两侧不对称
    （早一天只是多提醒一次，晚一天是让车主可能过期上路）。

判据口径（本仓库既有约定）：
  1. 认**代码形状**不认文字：先剥注释与三引号再看结构（散文骗过判据的坑踩过）；
  2. 需要看注释/文案的地方用**原文切片**（不剥注释）；切片为空必须由调用方自己 ok(...) 报红；
  3. 每条 ok() 的失败文案互不相同（红了要能一眼看出是哪一条）；
  4. 取法失效（找不到 def / 找不到表）本身也要报红 —— 判据先证明自己看得到东西。

用法：
    python _tools/qa/_check_inspection_and_near_low.py              # 查当前树
    python _tools/qa/_check_inspection_and_near_low.py <另一棵树>    # 反向验证用
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]

MIG = ROOT / "backend/app/migrations/033_vehicle_inspection.py"
MODEL = ROOT / "backend/app/models/vehicle.py"
SCHEMA = ROOT / "backend/app/schemas/accounting_v2.py"
API = ROOT / "backend/app/api/v1/vehicles.py"
SERVICE = ROOT / "backend/app/services/inspection_due.py"
PRODUCERS = ROOT / "backend/app/services/message_producers.py"
CENTER = ROOT / "backend/app/services/message_center.py"
BOOTSTRAP = ROOT / "backend/app/core/schema_bootstrap.py"
VDEP = ROOT / "backend/app/services/vehicle_depreciation.py"
TEST_MSG = ROOT / "backend/tests/test_message_producers.py"
TEST_DUE = ROOT / "backend/tests/test_inspection_due.py"
DESIGN = ROOT / "docs/MESSAGE_CARD_DESIGN.md"
CHANGE = ROOT / "docs/changes/FEAT-0022.md"
CHANGES_README = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
APP_DIR = ROOT / "backend/app"

#: 年检提前多少天提醒（与 `inspection_due.INSPECTION_DUE_SOON_DAYS` 对账）。
DUE_SOON_DAYS = 30
#: 偏低线的百分比（与 `message_producers.NEAR_LOW_RATIO_PERCENT` 对账）。
NEAR_LOW_RATIO = 20
#: 单测条数下限（任务书要求 ≥10；这里两个文件合起来远超它）。
MIN_TESTS = 10

PASS = 0
FAIL: list[str] = []


def ok(cond: bool, msg: str) -> None:
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(msg)


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def code_only(src: str) -> str:
    """剥三引号与整行注释后的代码：散文（注释/docstring）骗不过这一层。"""
    src = re.sub(r'"""[\s\S]*?"""', "", src)
    src = re.sub(r"'''[\s\S]*?'''", "", src)
    return re.sub(r"^[ \t]*#.*$", "", src, flags=re.M)


def region(src: str, signature: str, end_marker: str) -> str:
    i = src.find(signature)
    if i < 0:
        return ""
    j = src.find(end_marker, i + len(signature))
    return src[i:] if j < 0 else src[i:j]


def func(src: str, name: str) -> str:
    """一个函数的**原文**切片（含注释与 docstring）。"""
    return region(src, "def " + name + "(", "\n\n\ndef ")


def count_defs(root: Path, needle: str) -> list[str]:
    """`needle` 在 root 下**哪些文件**里出现过（用来钉「只有一处实现」）。"""
    return sorted(
        str(p.relative_to(ROOT)).replace("\\", "/")
        for p in root.rglob("*.py")
        if needle in read(p)
    )


def count_lines(src: str, needle: str) -> int:
    return sum(1 for line in src.splitlines() if line.strip() == needle)


def table_rows(src: str, header: str) -> dict[str, str]:
    """把「名字: dict[...] = { ... }」那张表读成 {键: 值文本}（行尾注释先切掉）。"""
    body = region(src, header, "\n}")
    rows: dict[str, str] = {}
    for line in body.splitlines():
        line = line.split("#", 1)[0]
        m = re.match(r'\s*"([a-z0-9_.]+)":\s*(\S+?),?\s*$', line)
        if m:
            rows[m.group(1)] = m.group(2)
    return rows


# ---------------------------------------------------------------------------
# 读文件
# ---------------------------------------------------------------------------
src_mig = read(MIG)
src_model = read(MODEL)
src_schema = read(SCHEMA)
src_api = read(API)
src_svc = read(SERVICE)
src_p = read(PRODUCERS)
src_c = read(CENTER)
src_boot = read(BOOTSTRAP)
src_vdep = read(VDEP)
src_test = read(TEST_MSG)
src_due = read(TEST_DUE)
src_design = read(DESIGN)
src_change = read(CHANGE)
src_readme = read(CHANGES_README)
src_claim = read(CLAIM)

for label, src, path in (
    ("迁移 033", src_mig, MIG),
    ("车辆模型", src_model, MODEL),
    ("车辆入出参", src_schema, SCHEMA),
    ("车辆端点", src_api, API),
    ("年检算法", src_svc, SERVICE),
    ("消息生产者", src_p, PRODUCERS),
    ("发消息工厂", src_c, CENTER),
    ("自愈副本", src_boot, BOOTSTRAP),
    ("消息生产者单测", src_test, TEST_MSG),
    ("年检算法单测", src_due, TEST_DUE),
    ("卡片规范", src_design, DESIGN),
):
    ok(bool(src), "读不到" + label + "：" + str(path))

code_svc = code_only(src_svc)
code_p = code_only(src_p)
code_api = code_only(src_api)


# ---------------------------------------------------------------------------
# 一组：字段这一层（迁移 033 / 模型 / 入出参）
# ---------------------------------------------------------------------------
ok("VERSION = 33" in src_mig, "迁移 033 的 VERSION 不是 33")
ok('NAME = "vehicle_inspection"' in src_mig, "迁移 033 的 NAME 不是 vehicle_inspection")
ok(re.search(r"^def upgrade\(engine", src_mig, re.M) is not None, "迁移 033 没有 def upgrade(engine)")
ok(re.search(r"^DESCRIPTION\s*=", src_mig, re.M) is not None, "迁移 033 没有 DESCRIPTION")
ok('TABLE = "vehicles"' in src_mig, "迁移 033 不是改 vehicles 表")
for col, ddl in (
    ("registration_date", "registration_date DATE NULL"),
    ("last_inspection_date", "last_inspection_date DATE NULL"),
):
    ok(ddl in src_mig, "迁移 033 里没有 `" + ddl + "`（列定义/可空性写错了）")
ok("DEFAULT" not in code_only(src_mig),
   "迁移 033 给新列写了 DEFAULT —— 老车没有这份记录，NULL 才是「没录」（⛔ 不许回填一个日期）")
ok("UPDATE vehicles" not in code_only(src_mig).upper(), "迁移 033 里出现了 UPDATE（回填老车 = 替用户编事实）")
ok("CREATE INDEX" not in code_only(src_mig).upper() and "CREATE UNIQUE INDEX" not in code_only(src_mig).upper(),
   "迁移 033 建了索引 —— 这两列只随车辆行按主键读出，没有按它们筛的查询")
ok("inspect(engine)" in src_mig, "迁移 033 没有 inspect(engine)（没法判列已存在）")
ok("return None" in func(src_mig, "_columns"),
   "迁移 033 的 _columns 在表不存在时没有返回 None（全新库会被它自己 ALTER 一遍）")
upg = func(src_mig, "upgrade")
ok("if name in have:" in upg and "continue" in upg,
   "迁移 033 没有逐列判存在性（不可重跑：MySQL 的 DDL 隐式提交，改一半再跑会撞 already exists）")

for col in ("registration_date", "last_inspection_date"):
    ok("Mapped[date | None] = mapped_column(Date, nullable=True)" in src_model and col in src_model,
       "车辆模型里没有可空的 " + col + "（Mapped[date | None] = mapped_column(Date, nullable=True)）")
mc = code_only(src_model)
ok("nullable=False" not in region(src_model, "registration_date: Mapped", "\n\n"),
   "上牌日期被写成了 NOT NULL —— 老车没有这一格，⛔ 不许逼着补录")

for cls in ("VehicleCreate", "VehicleUpdate", "VehicleOut"):
    body = region(src_schema, "class " + cls + "(", "\nclass ")
    ok(bool(body), "找不到 class " + cls + " 的切片（入出参被改名了？）")
    for col in ("registration_date", "last_inspection_date"):
        ok(re.search(r"^\s+" + col + r": date \| None = None", body, re.M) is not None,
           cls + " 里没有 " + col + "（老客户端拿不到这一格，也就永远填不了）")
ok(src_schema.count('"registration_date", "last_inspection_date", mode="before")') == 2,
   "空串=没录 的校验器（_blank_is_none）字段列表里没有把这两格加进 Create 与 Update 各一次 ——"
   " 安卓发得出空串、发不出显式 null，漏了它「清空这一格」就表达不出来")


# ---------------------------------------------------------------------------
# 二组：入口的 PATCH 语义（⛔ 老客户端不传时不许清空）
# ---------------------------------------------------------------------------
vout = func(src_api, "_out")
ok("registration_date=v.registration_date" in vout and "last_inspection_date=v.last_inspection_date" in vout,
   "VehicleOut 的装配点（_out）没有把这两格回给出参 —— 界面永远看不到已录入的年检日期")
ok('"registration_date" in body.model_fields_set' in code_api,
   "PATCH 没有用 model_fields_set 判「传没传」上牌日期 —— is not None 分不出「没传」与「传了空串」")
ok('"last_inspection_date" in body.model_fields_set' in code_api,
   "PATCH 没有用 model_fields_set 判「传没传」上次年检日期")
ok("body.registration_date is not None" not in code_api
   and "body.last_inspection_date is not None" not in code_api,
   "PATCH 里用 is not None 判这两格要不要改 —— 老客户端与「只改车牌」的编辑**根本不带这两格**，"
   "那样一次改车牌就会把用户录的年检日期抹掉")
ok("before_inspection = (v.registration_date, v.last_inspection_date)" in code_api,
   "PATCH 没有在改之前记下两格的旧值（审计行写不出来，也判不出「真的变了没有」）")
date_line = func(src_api, "_date_line")
ok(bool(date_line), "找不到 _date_line（年份日期审计行的唯一一处）")
ok("（清空）" in date_line, "审计行没有「→ （清空）」这一支：清空上牌日期等于这台车从此不再提醒，必须能回查")
ok(date_line.count("return \"\"") >= 1 or 'return ""' in date_line,
   "_date_line 在「没变」时没有返回空串 —— 审计页会被「改了但什么都没变」的记录淹掉")
ok(code_api.count("_inspection_lines(") >= 3,
   "_inspection_lines 的调用点少于 3 处（建车 1 处 + 改车 1 处 + 定义 1 处）：新建/编辑两边都要留痕")
ok("registration_date" not in code_only(src_vdep) and "last_inspection_date" not in code_only(src_vdep),
   "年检两格混进了 vehicle_depreciation（那是折旧四格专用的；两件事的缺失语义完全不同）")


# ---------------------------------------------------------------------------
# 三组：年检算法**只有一处**（周年 / 2-29 / 两格都空 / 分档）
# ---------------------------------------------------------------------------
defs = count_defs(APP_DIR, "def next_due_date(")
ok(defs == ["backend/app/services/inspection_due.py"],
   "def next_due_date( 必须**只在** backend/app/services/inspection_due.py 出现一次，实际：" + repr(defs))
defs_kind = count_defs(APP_DIR, "def inspection_kind(")
ok(defs_kind == ["backend/app/services/inspection_due.py"],
   "def inspection_kind( 必须只在 inspection_due.py 出现一次（分档只有一处），实际：" + repr(defs_kind))
ok("INSPECTION_DUE_SOON_DAYS = " + str(DUE_SOON_DAYS) in src_svc,
   "inspection_due 的提前提醒天数不是 " + str(DUE_SOON_DAYS) + " 天")
next_due = func(src_svc, "next_due_date")
ok("base = last_inspection_date or registration_date" in next_due,
   "next_due_date 的起点不是「上次年检日期，没有才回落到上牌日期」（两格都录时算错起点）")
ok("if base is None:" in next_due and "return None" in next_due,
   "next_due_date 没有「两格都空 ⇒ None」那一支 —— 那会让系统自己编一个到期日出来")
ok("today" not in code_svc,
   "inspection_due 里出现了 today —— ⛔ 不许拿今天当起点（那不是提醒，是系统编的事实）")
ok("business_today" not in code_svc, "inspection_due 里出现了 business_today（同上）")
one_period = func(src_svc, "one_period_later")
ok("day.replace(year=day.year + INSPECTION_PERIOD_YEARS)" in one_period,
   "「加一年」不是按周年算的（replace(year=+1)）—— 加 365 天每四年就会漂一天")
ok("except ValueError:" in one_period and "month=2, day=28" in one_period,
   "2/29 落在平年时没有夹到 2/28（不夹会直接抛 ValueError，夹到 3/1 会让提醒晚一天）")
kind = func(src_svc, "inspection_kind")
ok("left = (due - day).days" in kind, "inspection_kind 没有按「距到期还有几天」分档")
ok('if left < 0:\n        return "vehicle.inspection_overdue"' in kind,
   "分档的逾期边界不是 left < 0（到期日**当天**车还能合法上路，说「已逾期」是错的话）")
ok("if left <= INSPECTION_DUE_SOON_DAYS:" in kind and 'return "vehicle.inspection_due"' in kind,
   "分档的临期边界不是 left <= INSPECTION_DUE_SOON_DAYS")


# ---------------------------------------------------------------------------
# 四组：库存偏低（百分比口径 + 恰好等于阈值那条边界）
# ---------------------------------------------------------------------------
literal = "NEAR_LOW_RATIO_PERCENT = " + str(NEAR_LOW_RATIO)
hits = [str(p.relative_to(ROOT)).replace("\\", "/") for p in APP_DIR.rglob("*.py")
        if count_lines(read(p), literal) == 1]
ok(hits == ["backend/app/services/message_producers.py"],
   literal + " 必须**只有一处**（唯一实现），实际出现在：" + repr(hits))
ok("用户 2026-10-11" in src_p and "宽松" in src_p,
   "偏低线的注释里没有写清用户口径（2026-10-11「在报警的那个水平宽松一点」）——"
   " 下一个人会以为那个 20% 是我们随手拍的")
band = func(src_p, "stock_band")
ok(bool(band), "找不到 def stock_band( —— 库存两档的唯一分档判据")
ok("if alert <= 0:\n        return None" in band,
   "stock_band 没有把 low_stock_alert = 0 当成「不报警」（0 不是「阈值是 0」）")
ok('if stock < alert:\n        return "stock.low"' in band,
   "库存不足的边界不是 stock < alert —— 写成 <= 会把「恰好等于阈值」误报成 danger，"
   "而用户要的正是「到线了但还没跌破」那一档 warn")
ok("stock * 100 < alert * (100 + NEAR_LOW_RATIO_PERCENT)" in band,
   "偏低线的比较不是整数写法（stock * 100 < alert * (100 + 20)）：用浮点 alert * 1.2"
   "在大数上会给出差一件的边界错，而这是「该不该补货」的判断")
ok('return "stock.near_low"' in band, "stock_band 里没有偏低那一档")
ok(count_defs(APP_DIR, "def stock_band(") == ["backend/app/services/message_producers.py"],
   "def stock_band( 不止一处（分档散成两处，两处迟早不一样）")
# ⚠️ 这张表的值是**带空格的元组**（`("库存不足", "，已低于……")`），通用的 table_rows() 读不了它
#    —— 用它自己那条正则（键 + 结论词 + 正文尾句），比放宽通用取法更安全。
bands_region = region(src_p, "_STOCK_BANDS: dict[str, tuple[str, str]] = {", "\n}")
bands: dict[str, str] = {}
for m in re.finditer(r'"(stock\.[a-z_]+)":\s*\(\s*"([^"]*)"\s*,\s*"([^"]*)"\s*\)', bands_region):
    bands[m.group(1)] = m.group(2) + " " + m.group(3)
ok(set(bands) == {"stock.low", "stock.near_low"},
   "_STOCK_BANDS 的键不是恰好两个库存类型，实际：" + repr(sorted(bands)))
ok("已低于报警阈值" in bands.get("stock.low", ""),
   "stock.low 的正文尾句没有说「已低于报警阈值」（正文与档位说的不是同一件事）")
ok("已到报警阈值" in bands.get("stock.near_low", ""),
   "stock.near_low 的正文尾句没有说「已到报警阈值」—— 偏低那一档必须说清「到线了、还没跌破」")
ok("库存不足" in bands.get("stock.low", "") and "库存偏低" in bands.get("stock.near_low", ""),
   "两档的结论词不是「库存不足」/「库存偏低」（EMPHASIS_BY_TYPE 的固定新闻词要对得上）")
notify = func(src_p, "notify_stock_low")
ok("band = stock_band(stock, alert)" in notify,
   "notify_stock_low 没有走 stock_band 判档（自己又写了一遍阈值比较 = 第二个口径）")
ok("type_=band" in notify,
   "notify_stock_low 没有把 band 直接当 type（那就可能出现「算的是偏低、发的是不足」）")
ok('idem_key=band + ":" + str(int(product.id)) + ":" + when.isoformat(),' in notify,
   "库存的幂等键不是「类型:商品:日期」—— 去掉日期会让每日扫描变成每天刷屏，"
   "去掉商品会让两个商品互相顶掉")
scan_stock = func(src_p, "scan_stock_low")
ok("-> tuple[int, int]" in scan_stock.split("\n")[0],
   "scan_stock_low 的返回值不是两个计数（低于阈值 / 偏低），每日扫描没法把两档分开报")
ok("Product.low_stock_alert * (100 + NEAR_LOW_RATIO_PERCENT)" in scan_stock,
   "scan_stock_low 的选行条件另抄了一遍阈值（不是同一个百分比口径）——"
   " 下场是「扫描扫不出来、手工出入库却发得出」，而两边都不报错")
ok("stock_band(stock," in scan_stock,
   "scan_stock_low 没有用 stock_band 分开数两档（返回的两个计数会不可信）")


# ---------------------------------------------------------------------------
# 五组：车辆年检的两个生产者（文案 / 点名 / 幂等键 / 谁不发）
# ---------------------------------------------------------------------------
insp = func(src_p, "notify_inspection")
ok(bool(insp), "找不到 def notify_inspection( —— 车辆年检的生产者")
ok("inspection_due.next_due_date(vehicle.registration_date, vehicle.last_inspection_date)" in insp,
   "notify_inspection 没有用那两个日期现算到期日（自己去算 = 第二个口径，"
   "而 next_due_date 的判据只允许有一处）")
ok("if due is None:\n        return 0" in insp,
   "notify_inspection 没有「算不出到期日 ⇒ 一个字都不发」那一支"
   "（两格都空的车会被硬报一条出来）")
ok('if kind == "vehicle.inspection_overdue":' in insp,
   "notify_inspection 没有按 overdue / due 分两套文案")
ok('days_text = str(-left) + " 天"' in insp,
   "逾期那条没有把「已逾期 N 天」的 N 算进 days_text")
ok('的年检已逾期 " + days_text' in insp,
   "逾期那条的正文不是由 days_text 拼出来的（emphasis_for 会把片段静默丢掉）")
ok('"还有 " + str(left) + " 天"' in insp and '"今天到期"' in insp,
   "临期那条没有「还有 N 天 / 今天到期」两种说法（到期日当天必须说得出话）")
ok('"，" + days_text' in insp,
   "临期那条的正文不是由 days_text 拼出来的 —— emphasis_for 的「片段必须在正文里」"
   "那道闸会把片段静默丢掉（消息照发，卡片上少一个落点）")
ok("emphasis=(plate_text, days_text)" in insp,
   "年检那条没有点名（车牌 + 天数）—— 用户在一屏消息里认不出是哪台车")
ok('idem_key=kind + ":" + str(int(vehicle.id)) + ":" + due.isoformat(),' in insp,
   "年检的幂等键不是「类型:车辆:到期日」—— 去掉到期日会让同一次年检每天刷一条，"
   "去掉车辆会让两台车互相顶掉")
ok('"vehicle_id": int(vehicle.id)' in insp and "永远不跳" in insp,
   "车辆那条的 payload 没有写清「§五：车辆族永远不跳」—— 下一个人会把 vehicle_id 当深链键")
ok('title = "车辆年检已逾期：" + plate_text' in insp,
   "逾期那条的标题不是「车辆年检已逾期：车牌」（标题正好等于固定新闻词会被 emphasis 丢掉）")
ok('title = "车辆年检将到期：" + plate_text' in insp,
   "临期那条的标题不是「车辆年检将到期：车牌」")
scan_insp = func(src_p, "scan_inspection_due")
ok("Vehicle.is_active.is_(True)" in scan_insp,
   "年检扫描没有只扫在用车（停用 = 卖了 / 封存，再催年检是噪音）")
ok("or_(" in scan_insp and "Vehicle.registration_date.is_not(None)" in scan_insp
   and "Vehicle.last_inspection_date.is_not(None)" in scan_insp,
   "年检扫描没有先按「两格至少一个非空」收窄（会白扫全表；但⛔ 这不是分档判据）")
ok("inspection_due.inspection_kind(" in scan_insp,
   "年检扫描没有走 inspection_due.inspection_kind（自己又比了一遍日期 = 第二个分档口径）")
ok("-> tuple[int, int]" in scan_insp.split("\n")[0],
   "scan_inspection_due 的返回值不是两个计数（临期 / 逾期）")


# ---------------------------------------------------------------------------
# 五组之二：PRODUCED / NOT_PRODUCED 的账（FEAT-0021 留的两条必须结清）
# ---------------------------------------------------------------------------
prod_region = region(src_p, "PRODUCED: tuple[str, ...] = (", "\n)")
produced = set(re.findall(r'"([a-z0-9_.]+)"', prod_region))
for t in ("stock.near_low", "vehicle.inspection_due", "vehicle.inspection_overdue"):
    ok(t in produced,
       "PRODUCED 里没有 " + t + "（这一类现在有生产者了，却没登记 —— 下一单会以为它还没做）")

# ⚠️ end_marker 必须是 "}\n"（收尾大括号 + 行尾）：这张表现在是**空字典**（`{}`），
#    用 "\n}" 会一路读到后面 `_STOCK_BANDS` 的收尾大括号上，把 stock.low / stock.near_low
#    当成"没做"的两类（写这条时真踩到了：判据报"同一类既在 PRODUCED 又在 NOT_PRODUCED"，
#    而代码是对的 —— 假红会让人学会无视检查）。
np_region = region(src_p, "NOT_PRODUCED: dict[str, str] = {", "}\n")
np_rows = re.findall(r'^\s{4}"([a-z0-9_.]+)":', np_region, re.M)
ok("NOT_PRODUCED: dict[str, str] = {" in src_p,
   "NOT_PRODUCED 那张表不见了 —— 它是「下一单不做某一类时写理由」的落点，⛔ 空的也要留着")
ok(not np_rows,
   "NOT_PRODUCED 里还有 " + repr(sorted(np_rows)) + " —— FEAT-0022 之后**十类全都有生产者**，"
   "这张表必须是空的（⚠️ 已经做了的类型留在里面 = 告诉下一个人「它还缺字段」，而它已经在发了）")
ok(set(sorted(np_rows)).isdisjoint(produced),
   "同一类既在 PRODUCED 又在 NOT_PRODUCED：" + repr(sorted(set(np_rows) & produced)))

# ---------------------------------------------------------------------------
# 六组：档位与固定新闻词（⛔ 生产者里一个 severity= 都不许写）
# ---------------------------------------------------------------------------
sev = table_rows(src_c, "SEVERITY_BY_TYPE: dict[str, str] = {")
ok(sev.get("stock.near_low") == "SEVERITY_WARN",
   "stock.near_low 的档位不是 warn，实际：" + repr(sev.get("stock.near_low")))
ok(sev.get("stock.low") == "SEVERITY_DANGER",
   "stock.low 的档位不是 danger（偏低做了之后很容易被顺手改成一档）")
ok(sev.get("vehicle.inspection_due") == "SEVERITY_WARN",
   "vehicle.inspection_due 的档位不是 warn，实际：" + repr(sev.get("vehicle.inspection_due")))
ok(sev.get("vehicle.inspection_overdue") == "SEVERITY_DANGER",
   "vehicle.inspection_overdue 的档位不是 danger —— 年检过期上路要罚款扣车，"
   "降成 warn 会让它和「还有 30 天」显示成同一个颜色，实际：" + repr(sev.get("vehicle.inspection_overdue")))
emph = table_rows(src_c, "EMPHASIS_BY_TYPE: dict[str, tuple[str, ...]] = {")
ok("库存偏低" in emph.get("stock.near_low", ""),
   "EMPHASIS_BY_TYPE 里没有 stock.near_low 的固定新闻词「库存偏低」")
ok("已逾期" in emph.get("vehicle.inspection_overdue", ""),
   "EMPHASIS_BY_TYPE 里没有 vehicle.inspection_overdue 的固定新闻词「已逾期」")
ok("年检" in emph.get("vehicle.inspection_due", ""),
   "EMPHASIS_BY_TYPE 里没有 vehicle.inspection_due 的固定新闻词「年检」")
ok("severity" not in code_p,
   "生产者里出现了 severity —— 档位判定只有 message_center.severity_for 一处")
for lit in ("stock.low", "stock.near_low", "vehicle.inspection_due", "vehicle.inspection_overdue"):
    ok('"' + lit + '"' in src_p,
       "生产者里找不到类型名字面量 " + repr(lit) + "（PRODUCED 里写着有生产者，代码里却没有）")


# ---------------------------------------------------------------------------
# 七组：跑得起来吗（兜底扫描挂上了 / 自愈副本跟上了）
# ---------------------------------------------------------------------------
daily = func(src_p, "run_daily_scan")
for needle in ("scan_stock_low(db, day=when)", "scan_inspection_due(db, day=when)"):
    ok(needle in daily, "每日兜底扫描没有调用 " + needle + "（那一类漏发就再没人补）")
for key in ("stock_low", "stock_near_low", "inspection_due", "inspection_overdue"):
    ok('"' + key + '":' in daily, "每日兜底扫描的返回里没有 " + key + " 这个计数")
ok("db.commit()" in daily, "每日扫描没有 commit（扫出来的消息会随请求一起被丢掉）")
for col in ("registration_date", "last_inspection_date"):
    ok("ALTER TABLE vehicles ADD COLUMN " + col + " DATE NULL" in src_boot,
       "schema_bootstrap 的自愈副本里没有 " + col + " 这句 DDL（迁移没跑过就起服务的库会缺列）")
ok("033_vehicle_inspection.py" in src_boot,
   "自愈副本没有写明正式搬迁是哪一条迁移（下一个人会以为它就是正式入口）")


# ---------------------------------------------------------------------------
# 八组：单测（阈值上下 / 两档互斥 / 2-29 / 两格都空 / 连跑两次）
# ---------------------------------------------------------------------------
msg_tests = re.findall(r"^def (test_[a-z0-9_]+)\(", src_test, re.M)
due_tests = re.findall(r"^def (test_[a-z0-9_]+)\(", src_due, re.M)
ok(len(msg_tests) + len(due_tests) >= MIN_TESTS,
   "两个单测文件加起来只有 " + str(len(msg_tests) + len(due_tests)) + " 条（< " + str(MIN_TESTS) + "）")
for name, why in (
    ("test_stock_is_near_low_exactly_at_the_alert_but_not_past_the_line", "恰好等于阈值 = 偏低（不是 danger）"),
    ("test_stock_never_sends_both_bands_for_one_product", "两档互斥：同一件库存事实只发一条"),
    ("test_stock_low_fires_only_below_the_alert", "跌破阈值才是 danger"),
    ("test_stock_near_low_sends_once_a_day_too", "偏低也是同商品同一天一条"),
    ("test_daily_scan_reruns_without_adding_a_single_row", "每日扫描连跑两次第二次 0 条"),
    ("test_inspection_reminds_from_registration_date", "只有上牌日期也能提醒"),
    ("test_inspection_last_date_wins_over_registration", "两格都录时以上次年检日期为准"),
    ("test_inspection_without_any_date_is_silent", "两格都空 ⇒ 一个字都不发"),
    ("test_inspection_kind_buckets_the_three_bands", "三档与两条边界（30 天 / 到期日当天 / 过 1 天）"),
    ("test_inspection_scan_is_idempotent_and_skips_stopped_vehicles", "扫描幂等 + 停用车不催"),
    ("test_feb_29_clamps_to_feb_28_in_a_common_year", "2/29 落在平年夹到 2/28"),
    ("test_kind_buckets_with_two_exact_boundaries", "分档两条边界各自钉住"),
    ("test_no_base_date_means_no_reminder_at_all", "没有起点就没有提醒"),
):
    ok(("def " + name + "(") in (src_test + src_due), "少了那条单测：" + why + "（" + name + "）")
ok('stock_band(10, 10) == "stock.near_low"' in src_test,
   "单测没有在**纯函数**上钉住「等于阈值 = 偏低」这条边界（只在消息层断言的话，"
   "边界被别人改成 <= 时可能仍然绿）")
ok('stock_band(12, 10) is None' in src_test,
   "单测没有钉住「出线（阈值 ×1.2）之后一个字都不发」")
ok('next_due_date(date(2024, 2, 29), None) == date(2025, 2, 28)' in src_due,
   "单测没有钉住 2/29 那条（四年才撞一次，真出事时没人想得到是这里）")
ok('next_due_date(None, date(2025, 5, 1)) == date(2026, 5, 1)' in src_due,
   "单测没有钉住「只有上次年检日期」也能算")
ok("select(func.count()).select_from(Notification)" in src_test,
   "去重那条用例没有真的数通知条数（拿计数当判据）")


# ---------------------------------------------------------------------------
# 九组：文书与规范（变更单九节 / 登记簿 / 声明页 / 卡片规范）
# ---------------------------------------------------------------------------
ok(bool(src_change), "读不到 docs/changes/FEAT-0022.md")
if src_change:
    for part in ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨"):
        ok("## " + part in src_change, "变更单缺第 " + part + " 节")
    ok("FEAT-0022" in src_change, "变更单里没写 ID FEAT-0022")
    ok("NEAR_LOW_RATIO_PERCENT" in src_change or "20%" in src_change,
       "变更单没有写清偏低线的百分比口径")
    ok("NOT_PRODUCED" in src_change,
       "变更单没有说明「这两类已经从 NOT_PRODUCED 移走」（FEAT-0021 留的账要结清）")
    ok("2/29" in src_change or "2 月 29" in src_change, "变更单没有写 2/29 的处理方式")
    ok("33" in src_change, "变更单没有写迁移编号 033")
    ok("幂等" in src_change, "变更单没有写去重靠幂等键")
    ok("恰好等于阈值" in src_change,
       "变更单没有写「恰好等于阈值算偏低」这条边界（它是用户口径的落点）")
ok("FEAT-0022" in src_readme, "docs/changes/README.md 里没有 FEAT-0022 那一行")
ok("FEAT-0022" in src_claim, "声明页 docs/AI_WORK_CLAIM.md 里没有 FEAT-0022 的条目")
ok("vehicle.inspection_overdue" in src_design,
   "卡片规范 §二/§三 没有登记 vehicle.inspection_overdue（新类型没进颜色/档位表）")
ok("20%" in src_design, "卡片规范 §三 没有把偏低线写成百分比口径（还写着旧的「建议水位」）")
ok("永远不跳" in src_design, "卡片规范 §五 没有写清车辆族永远不跳")
ok("恰好等于阈值" in src_design, "卡片规范 §三 没有写「恰好等于阈值算偏低」这条边界")

print("车辆年检与库存偏低判据：%d 条通过，%d 条失败" % (PASS, len(FAIL)))
for msg in FAIL:
    print("  ❌ " + msg)
if FAIL:
    sys.exit(1)
print("  ✅ 两格日期只有一处算法、恰好等于阈值算偏低、两档互斥、年检两档各就各位、"
      "幂等键带到期日、档位只在 message_center、文书与规范都跟上了")

