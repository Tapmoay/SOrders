"""造一份**规范**的 3~4 个月演示数据（用户 2026-09-20 提出、2026-09-21 扩到 120 天）。

## 为什么单独写一个（而不是随手 insert）

用户原话：「清洗完之后，我们再重新写一份数据…大概是**不规律的近 3 个月的数据**，
什么数据都有…希望**不要什么地方空掉了**也不要乱写了一堆的，比如说测试数据、
一些批量是一模一样的。也就是说，这次写的数据**一定要正规**，不能是随随便便的，
因为这次我们用来测试的数据很重要」。

所以这份脚本的规矩：

1. **不写"测试/验证/压测"字样**，也不写 `xxx`、`aaa` 这种占位；
2. **每条都不一样**：名字来自姓氏×名字池、地址来自"区×路×门牌"组合，电话**发号前查重**；
3. **该填的都填**：电话、联系人、地址、单位、成本、库存、备注——空字段就是界面上一条横线；
4. **时间不规律但也讲道理**：按业务日铺（早上与下午两个高峰、周日大多不发），
   单量在**月 / 周 / 日**三个尺度上都有多有少，还有尖峰日与清淡日
   （见下面「单量怎么铺」），不搞"每天正好 5 单"这种假规律；
5. **走真实的业务函数**（`order_flow.assign_driver` / `complete_delivery` /
   `message_center.publish_*`），所以账本、司机账单、现金流水、库存流水、消息
   都是**业务代码自己写出来的** —— 我在这里再编一遍，就一定会与线上算法走散
   （而这批数据是拿来验收的）；
6. **日期取自业务时刻**：回放历史时，凡是"送达那一刻"派生出来的行（账本、账单、货损开销、
   货损现金流水、库存流水）都要落回那一单的日子。漏一处，那一类数据就会全挤在今天那一个月，
   而界面上看不出来"是数据造错了"还是"这个月真的只有这些"；
7. **验收用的三个账号自己也要有数据**：数据分给了新造的 24 个货主 / 22 个司机，
   而真机上登的是三个开发号 —— 它们必须是"有单、有账、有地址库"的正常账号；
8. **列形状要对**：JSON 列给 list（给字符串 `"[]"` 会被原样存成字符串，读接口直接 500），
   Text 列给 JSON 字符串 —— 同一个模型里这两种列是并存的（`delivery_photo_urls` vs `image_urls`）。

## 单量怎么铺（2026-09-21 加强：用户要"有多有少"）

用户原话：「这些数据是真实的，大概是 **3 到 4 个月**的数据，而且是每个月、每天、每周
都是不一样的，是**数量是有多有少**」。所以"几个月都一样忙"不算合格。铺法是一条链：

```
逐日权重 = 月度因子 × 星期因子 × 事件因子 × 每日抖动   →  最大余额法精确分到每一天
```

| 尺度 | 怎么体现 | 在哪 |
|---|---|---|
| **月度** | `MONTH_FACTORS` 按**日历月**给因子：7 月水果旺季最忙、**8 月反而最淡**、9 月开学季回升。⛔ 刻意**不是**"越近越忙"——那种规律的结果就是"每个月都比上个月多"，而真实生意有旺有淡 | 各月总单量互不相同、且非单调 |
| **周内** | `WEEKDAY_FACTORS`：周一周二最高、周三偏高、周四周五周六中等、**周日几乎不发车**（0.16） | 逐星期几日均 |
| **日间** | `pick_time()`：早班 6-9 点 + 下午 14-17 点两个主峰（尖峰日全天铺开，清淡日只集中在早上一两个时段） | 逐小时分布 |
| **尖峰日** | **每个整月一个**（旺季那个月两个），月中偏后 —— 像"节前备货/促销"；单量是平时的 **2.4~3.0 倍**，且**全天都有单** | 报告里逐日列出 |
| **清淡日** | **每个整月两个**（月的前/后半各一个），单量只有平时的 **5%~18%**，集中在早班 | 报告里逐日列出 |

**两条不能丢的尾巴**（都是真机上踩出来的，别为了"分布好看"把它们删了）：
最近 3 天各保底 3 单（否则账本/消息中心的「今天/昨天/前天」三个档位点下去全是空的）；
时间**严格递增**（`GET /orders` 按 id 倒序，id 必须与时间同向，否则待派池第一张是两个月前的单）。

跑完会打印一份**分布报告**（逐月 / 逐星期几 / 日极值 / 最忙 5 天 / 尖峰与清淡日各是哪几天），
预览模式也会打印**计划**的那一份 —— 这两份是"有多有少"的验收依据。

## 时间怎么存（2026-09-21 修：与库的口径对齐）

库里所有时间列一律 **UTC naive**（`core/business_time.py`）。所以本文件有两条口径，别混：

| 场合 | 用什么 | 为什么 |
|---|---|---|
| 内部排期/比较/"现在" | `wall_now()`（业务当地墙上时间，`pick_time` 造的就是它） | ⛔ 不许用 `datetime.now()`：那是本机时区，服务器配成 UTC 就整体漂 8 小时 |
| **写库那一刻** | `to_utc_naive(...)` | 第一版直接把墙上时间写进库 → App 读出来 **+8 小时**（"早上 7:30 的单"显示成 15:30，当天较晚的单甚至显示成**未来**） |
| 日期类列（`order_date`/`entry_date`/`month`/`exp_date`） | **业务日**，不换算 | 它们本来就是"哪一天"，不是"几点" |
| SQL 里按日期分桶 | `biz_day_sql(col, dialect)`（UTC+8h 取日期） | ⛔ 不许 `date(时间戳)`：北京 06:30 的单存进去是**前一天 22:30**，取出来就是前一天 —— 凌晨那批单的账本/账单会整批挪走一天 |
| 消息 `publish()` 的 `when` | 传**订单列的原值**（已是 UTC），不再换算 | 再减 8 小时就是双重换算 |

## 它造什么（默认近 120 天）

| 类别 | 量 | 说明 |
|---|---|---|
| 商品分类 / 商品 | 6 / 36 | 生鲜配送的真实品类（水果/蔬菜/肉禽蛋/米面粮油/调味/酒水） |
| 货主 / 批发商 | 24 / 9 | 门店、食堂、餐饮；批发商带专属价（`price_rules`）；**含开发号货主** |
| 司机 / 车辆 / 计费规则 | 22 / 14 / 6 | 计件 / 工资 / 提成 三档；车牌、车型；**含开发号司机**（队首，有车） |
| 地点 / 线路 / 联系人 / 分组 | 60+ / 20 / 36 / 4 | 惠州·东莞一带的地名组合 |
| 挂账单位 / 运费模板 | 6 / 8 | 按路线定价的价目表 |
| 订单 | 默认 2400（120 天，≈20 单/天） | 各状态都有；送达单会**自动**产生账本/账单/现金流水/库存流水 |
| 送达照片 | 每张送达单 1 张 | 真的写到 `uploads/delivery/<id>/`（= App 服务的那棵树，见 `UPLOAD_ROOT`），不是假 URL |
| 手工流水 / 开销 / 司机结算单 | 18 / 30 / ~12 | 手工记账、六类开销、按月的结算单（草稿） |
| 消息中心 | 最近 30 天 | 走真实的 `publish_*`（新单/派单/接单/送达/撤销），只把 Socket 推送换成空实现 |

用法（**在 backend 目录下**）：
    python -m scripts.seed_demo_data            # 预览：只打印将要造什么 + 计划分布报告
    python -m scripts.seed_demo_data --yes      # 真的写库（跑完打印实际分布报告）
    python -m scripts.seed_demo_data --yes --orders 2400 --days 120
    python -m scripts.seed_demo_data --report   # 只读库：把已经造好的那份数据的分布打出来

⚠️ **在一张已经有数据的库上灌（生产就是）**：先清业务数据，否则新旧会混住
   （守卫会直接拦下整条命令）。清库清单是**算出来的**（`Base.metadata`，新表自动覆盖），
   保留 `users` 与几张名册；三个开发登录号 + `--keep` 的手机号不会被删：
       python -m scripts.seed_demo_data --reset                    # 只看看会清掉什么
       python -m scripts.seed_demo_data --reset --yes --keep 13800000004

⚠️ 换库跑（别拿本机开发库做实验）：`database_url` 走环境变量覆盖，优先级高于 `.env`
   （`app/config.py` 用 pydantic-settings，环境变量 > `.env` 文件）：
       $env:DATABASE_URL = "sqlite:///./_seed_check.db"     # PowerShell
       DATABASE_URL=sqlite:///./_seed_check.db python -m scripts.seed_demo_data --yes
"""
from __future__ import annotations

import argparse
import asyncio
import random
import sys
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select, text, update

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

from app.core.business_time import (  # noqa: E402
    BUSINESS_TZ,
    business_date,
    to_utc_naive,
    utc_now_naive,
)
from app.core.security import hash_password  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.arrears import ArrearsUnit  # noqa: E402
from app.models.driver_bill import DriverBill  # noqa: E402
from app.models.driver_billing_rule import DriverBillingRule  # noqa: E402
from app.models.driver_settlement import DriverSettlement  # noqa: E402
from app.models.enums import (  # noqa: E402
    DriverBillType,
    DriverBillStatus,
    LedgerSource,
    OrderStatus,
    SettlementStatus,
    UserRole,
)
from app.models.expense import Expense  # noqa: E402
from app.models.freight_template import FreightTemplate, FreightTemplateDriver  # noqa: E402
from app.models.ledger import Ledger  # noqa: E402
from app.models.order import Order, OrderProduct  # noqa: E402
from app.models.place import Place  # noqa: E402
from app.models.place_category import PlaceCategory  # noqa: E402
from app.models.product import PriceRule, Product  # noqa: E402
from app.models.product_category import ProductCategory  # noqa: E402
from app.models.shipper import ShipperAddress, ShipperContact, ShipperLocation  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.vehicle import Vehicle  # noqa: E402
from app.schemas.order import DamageItem  # noqa: E402
from app.services.order_flow import assign_driver, complete_delivery  # noqa: E402

rng = random.Random(20260920)   # 固定种子：同一份脚本每次造出同一份数据（可复现、可复跑）

# ---------------------------------------------------------------- 单量分布参数
#
# ⛔ 为什么要有这几个表（而不是继续"随机挑日子"）：随机的后果是"月与月差不多"，
#    而用户要的是"有多有少**看得出来**"。因子是显式的，所以能原样写进分布报告里，
#    用户看到的是一个能解释的规律（"7 月水果旺季、8 月淡"），而不是一句"随机就是这样"。
#
# ⚠️ **不是"越近越忙"**：那种规律铺出来的结果必然是"每个月都比上个月多"，
#    而真实生意有旺月也有淡月（旧版就是"越近越忙"，实测相邻月单量几乎一样）。
#: 月度因子：按**日历月**给（与"运行在哪一天"无关，所以换一天跑规律不变）。
#: 7 月夏令水果旺季最忙、8 月反而最淡（高温+学校放假）、9 月开学季回升。
#: ⚠️ 差距要拉得够开：月总单量还会被"这个月摊到几个尖峰日/清淡日"扰动 ±6 单左右，
#:    因子只差 10% 的话，实测出现过 6 月 112 单 vs 7 月 113 单（差 1 单 = 肉眼看不出来，
#:    而用户要的正是"月之间差距肉眼看得出来"）。
#: ⚠️ 但**不能再往下压**：整月的单量有一条验收线（`_verify_demo_data.py` 第 ⑤ 条要求
#:    整月 ≥ 80 单），8 月给 0.98 时实测正好落在 80（零余量，少一单就红）。
MONTH_FACTORS = {
    1: 0.95, 2: 0.80, 3: 1.05, 4: 1.00, 5: 1.05, 6: 1.18,
    7: 1.38, 8: 1.06, 9: 1.22, 10: 1.05, 11: 0.95, 12: 1.08,
}
#: 星期因子（`date.weekday()`：0=周一 … 6=周日）：
#: 周一周二最忙、周三偏高、周四周五周六中等、**周日几乎不发车**（生鲜配送的常态）。
#: ⚠️ 差距要拉得够开：日历效应之外还有月度/事件/抖动三层，差距太小的话
#: 报告里"周五比周三还忙"就会冒出来（实测过：1.20/1.12 那一版就是这样）。
WEEKDAY_FACTORS = {0: 1.28, 1: 1.30, 2: 1.18, 3: 1.00, 4: 0.92, 5: 0.86, 6: 0.16}
#: 尖峰日（节前备货/促销）：单量是平时的 2.4~3.0 倍，且**全天铺开**。
SPIKE_FACTOR = (2.4, 3.0)
#: 清淡日（下雨/市场休市/盘点）：只有平时的 5%~18%，**几乎没单**，集中在早班。
QUIET_FACTOR = (0.05, 0.18)
#: 逐日抖动：让相邻两天不一样（不然"每周同一天都一样多"看着就是造的）。
DAY_JITTER = (0.82, 1.18)
#: 报告里星期几的中文名（下标 = `date.weekday()`）
WD_NAMES = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

#: 三个开发登录账号：**只复用、不重建**，并且 `--reset` 永远不删它们
#: （用户手机与模拟器上登的就是这三个）。
DEV_PHONES = ("13800000001", "13800000002", "13800000003")

#: `--reset` 清库时**保留**的表。
#:
#: ⚠️ 保留名单是**手写**的，要清的表是**算出来**的（`Base.metadata`）—— 反过来才对：
#:    要清的清单手写一定会过期（`_tools/seed/_reset_dev_db.py` 那张就过期了，
#:    见 `reset_business_data` 的注释），而"哪些表不能清"是**业务判断**，算不出来。
RESET_KEEP = {
    "users",                           # ★ 三个开发登录账号（用户手机/模拟器上登着它们，硬要求）
    "expense_categories",              # 名册：`schema_bootstrap` 从在用数据回填的，种子不造
    "freight_categories",              # 同上
    "driver_billing_rule_categories",  # 名册（种子不造）
    "driver_billing_rule_templates",   # 计费规则模板（种子不造）
    "freight_template_categories",     # 名册（种子不造）
}

# ---------------------------------------------------------------- 素材池
SURNAMES = "陈林黄张李王吴刘蔡杨许郑谢郭洪曾廖赖徐周叶苏庄江何高罗简朱游詹施沈柯"
GIVEN_M = ["志强", "建国", "伟明", "海涛", "俊杰", "文斌", "少华", "国平", "锦辉", "德胜",
           "永强", "兆丰", "庆华", "伟东", "立新", "春生", "耀光", "宏斌", "添福", "水生"]
GIVEN_F = ["秀英", "桂芳", "丽娟", "美玲", "玉兰", "小燕", "惠珍", "秋萍", "春梅", "婉婷"]

DISTRICTS = {
    "惠城": ((23.08, 114.41), ["麦地路", "下埔路", "演达大道", "江北文昌一路", "龙丰街道办前路"]),
    "仲恺": ((23.03, 114.32), ["和畅五路", "陈江大道", "惠风东三路", "东江高新科技园"]),
    "惠阳": ((22.79, 114.46), ["淡水人民六路", "秋长街道办前路", "三和经济开发区"]),
    "博罗": ((23.17, 114.29), ["罗阳镇商业东街", "园洲镇振兴大道"]),
    "樟木头": ((22.91, 114.07), ["樟罗大道", "柏地工业区"]),
    "常平": ((22.97, 113.99), ["常平大道", "土塘工业路"]),
    "塘厦": ((22.81, 114.10), ["塘龙中路", "林村工业区"]),
    "龙岗": ((22.72, 114.18), ["横岗街道办前路", "布吉西环路"]),
}
STORES = ["生活超市", "生鲜超市", "农副产品店", "川菜馆", "湘菜馆", "客家菜馆", "肠粉店",
          "烧腊饭店", "火锅店", "快餐店", "幼儿园食堂", "中学食堂", "工业园食堂", "月子中心"]
FAMILY_NAMES = ["旺客来", "家家福", "好又多", "惠民生", "鑫源", "老友记", "陈记", "顺发",
                "金穗", "东江", "兴隆", "福满堂", "聚福楼", "百味居"]
WAREHOUSES = ["中央厨房", "配送中心", "冷链仓", "干货仓"]

CATEGORIES = [
    ("时令水果", ["赣南脐橙", "海南香蕉", "红富士苹果", "麒麟西瓜", "阳光玫瑰葡萄", "四会砂糖橘"]),
    ("蔬菜豆制品", ["本地菜心", "水东芥菜", "荷兰豆", "鲜香菇", "老豆腐", "黄豆芽"]),
    ("肉禽蛋品", ["清远土鸡", "麻鸭", "猪前腿肉", "牛腩", "鲜鸡蛋", "冰鲜鸡翅"]),
    ("米面粮油", ["丝苗米", "泰国香米", "高筋面粉", "花生油", "玉米胚芽油", "糯米"]),
    ("调味干货", ["金标生抽", "蚝油", "干辣椒", "八角", "腐竹", "东北木耳"]),
    ("酒水饮料", ["饮用纯净水", "橙汁饮料", "罐装凉茶", "珠江啤酒", "客家米酒", "原味豆奶"]),
]
UNITS = ["箱", "件", "袋", "桶", "筐", "包"]
# ⚠️ 车型**只有一套词表**：后端与 App 认的都是 `small`/`large`/`trailer`
#    （`services/driver_pay._VEHICLE_TYPES`、`api/v1/vehicles.py::_VEHICLE_TYPES`、
#     `api/v1/freight_templates.py::_VALID_VEHICLE`、`VehicleManageScreen.vehicleTypeLabel`），
#    中文名只是**显示层**（小货车/大货车/挂车）。
#    第一版这里写的是「面包车 / 4.2米厢式货车 / 6.8米货车 / 三轮车」——那是另一套词表，
#    后果是三处**静默**的：22 位司机与 14 台车在真机上车型一栏全显示「未设置车型」、
#    8 张运费模板的车型是后端不认的值、App 的新增/编辑表单存下去就 422。
#    权重靠重复表达：小车最多、挂车最少（挂车只有 6.8 米以上才有）。
VEHICLE_TYPES = ["small", "small", "large", "large", "trailer"]
PLATE_PREFIX = ["粤L", "粤S", "粤B"]
# ⛔ 开销分类自 2026-09-20 起是**可维护名册**（`/expense-categories`）里的名字，
#    存的就是中文名本身（旧库里的 fuel/repair/… 已由 `schema_bootstrap` 翻成中文）。
#    ⚠️ 之前这里是枚举值、中文只是界面标签：第一版把中文当存储值时写库一声不响、
#    读的时候 `ExpenseOut` 校验失败 → `GET /expenses` 整个端点 500。
#    货损不在这里：它是送达时按货损件数自动记的（`accounting_service`）。
EXPENSE_NOTES = {
    "加油": ["仲恺加油站 92#", "江北中石化", "塘厦加气站", "常平服务区加油"],
    "过路": ["惠河高速", "潮莞高速", "博深高速", "长深高速"],
    "维修": ["换两条后胎", "刹车片保养", "空调加雪种", "年检代办", "换机油三滤"],
    "停车": ["信立农批月租", "樟木头市场临停", "龙岗园区停车"],
    "保险": ["交强险续保", "商业险续保", "承运人责任险"],
    "罚款": ["违停罚单", "超载罚款"],
    "其他": ["仓库加班餐", "跟车午餐", "早班早餐", "打印纸与标签", "送货单印刷",
                            "月结话费", "对讲机电池", "临时装卸工钱", "叉车租用"],
}
ARREARS_UNITS = ["仲恺中学食堂", "信立农批市场管理处", "惠阳人民医院饭堂", "德赛工业园食堂",
                 "伯恩光学食堂", "TCL 液晶产业园食堂"]
ROUTES = [("惠州江北", "东莞樟木头", 62), ("惠州仲恺", "深圳龙岗", 88), ("惠州惠阳", "东莞塘厦", 74),
          ("博罗罗阳", "惠州江北", 38), ("惠州江北", "惠阳淡水", 45), ("东莞常平", "惠州仲恺", 66),
          ("惠州仲恺", "博罗园洲", 52), ("深圳龙岗", "惠州惠城", 92)]
DRIVER_REMARKS = ["", "", "客户验收无异议", "少一箱已拍照确认", "货主自提", "代收现金已交财务"]
LEDGER_NOTES = ["门店自提现结", "补记上月尾款", "现金支付已点清", "微信转账已到账",
                "换货冲抵", "客户现场结清", "月底结清差额"]

USED_PHONE: set[str] = set()
#: `users.username` 在库里唯一。种子每轮从**同一个种子**出发，所以"上一轮造过的名字"
#: 这一轮会原样再发一次 —— 只要库里留着任何账号（`--keep` 的、或上一次没清干净的），
#: 就是 `UNIQUE constraint failed: users.username`（实测踩到）。
USED_USERNAME: set[str] = set()

#: 照片落盘根目录 = `backend/uploads/`。⛔ **不是 `backend/static/`**：
#:  服务端那条静态路由（`app/main.py` 的 `/static/uploads/{path}`）读的是 `Path("uploads")`，
#:  App 自己上传的送达照片也写 `app/api/v1/orders.py::UPLOAD_DIR = Path("uploads")/"delivery"`，
#:  保留/压缩任务（`services/data_retention.py`、`services/image_archive.py`）同样只扫 `uploads/`；
#:  生产 nginx 也是 `location /static/uploads/ { alias …/backend/uploads/; }`（生产上
#:  `backend/static` **根本不存在**）。
#:  ⚠️ 第一版这里是 `Path("static")`，于是每一张种子照片都写进了一个**没人服务**的目录：
#:  真机上全是坏图、保留任务永远扫不到它们，而验收脚本查的也是 `static/`（跟种子犯同一个错）
#:  —— 所以它一直是绿的。**URL 前缀仍然写 `/static/uploads/…`**，那是客户端的取图路径，
#:  与"文件落在磁盘哪个目录"本来就是两件事（App 那边也是这样）。
UPLOAD_ROOT = Path("uploads")


def wall_now() -> datetime:
    """**业务当地的墙上时间**（`pick_time()` 造出来的就是它）。

    ### 这个文件里的两条时间口径，别混
    - **内部**（排期、比较、"现在"）：一律用它 —— 见名知意：`cap = wall_now() - 30min`。
      ⛔ 不许用 `datetime.now()`：那是**本机时区**的墙上时间，服务器配成 UTC 就会整体漂 8 小时。
    - **写库那一刻**：一律过 `to_utc_naive()` —— 库里的时间列是 **UTC naive**
      （`core/business_time.py` 的口径，`TimestampMixin` 的 default 也是 `utc_now_naive()`）。
      第一版把墙上时间直接写进库，App 读出来就 +8 小时（"早上 7:30 的单"显示成 15:30），
      当天较晚的单甚至显示成**未来**；而日期类字段（`order_date`/`entry_date`/`month`）
      本来就是业务日，所以账目不错位、只有"几点"是错的 —— 这类缺陷在库外看不出来。

    ### ⚠️ 减 8 小时带出来的坑（2026-09-21 用户点名要防的那条）
    北京 06:30 的单，UTC 是**前一天 22:30**。所以**任何"按日期分桶"的地方都不许拿存下来的
    UTC 时间戳取 `.date()`** —— 那会把凌晨那批单的账本/账单整批挪到前一天。规则：
    分桶用**业务日**（`business_date(utc_ts)`，或 SQL 里 `date(ts + 8h)`，见 `_biz_day_sql`）。
    """
    return datetime.now(BUSINESS_TZ).replace(tzinfo=None)


def biz_day_sql(col: str, dialect: str) -> str:
    """SQL 里把**库里的 UTC 时间列**换成**业务当地日**（两种库写法不同）。

    ⛔ 这一句的存在本身就是为了防那个坑：库里存 UTC，北京 06:30 的单存进去是**前一天 22:30**，
    直接 `date(col)` 取出来就是前一天 —— 凌晨那批单的账本/账单会整批挪走一天。
    业务日的定义与 `core/business_time.py::business_date` 一致：**UTC + 8 小时取日期**。
    （`col` 允许是 `coalesce(时间列, date列)`：给 DATE 加 8 小时仍是同一天，两边都对。）
    """
    if dialect == "mysql":
        return f"date(date_add({col}, interval 8 hour))"
    return f"date({col}, '+8 hours')"


def phone() -> str:
    """13x 本地号段，**发号前查重**（重号在真实库里是唯一约束冲突）。"""
    while True:
        p = "13" + str(rng.choice([5, 6, 7, 8, 9])) + f"{rng.randint(0, 99999999):08d}"
        if p not in USED_PHONE:
            USED_PHONE.add(p)
            return p


def person(female_ratio: float = 0.3) -> str:
    return rng.choice(SURNAMES) + rng.choice(GIVEN_F if rng.random() < female_ratio else GIVEN_M)


def uniq_username(name: str) -> str:
    """账号名（`users.username` 唯一）：撞了就加个数字后缀。

    ⚠️ 为什么光靠"随机不重名"不够：种子每轮从同一个 `Random(20260920)` 出发，
    同样的输入序列必然产出同样的名字 —— 于是**上一轮造过的名字这一轮会再发一次**，
    只要库里还留着任何账号就是唯一键冲突（实测：`--reset --yes --keep <某个种子造过的号>`
    先撞 phone、后撞 username，两次都是崩在"造账号"这一步）。
    后缀人看不出来（名字本身是随机的"姓氏+名字"），而后缀不会进 `full_name`。
    """
    if name not in USED_USERNAME:
        USED_USERNAME.add(name)
        return name
    for i in range(2, 99):
        cand = f"{name}{i}"
        if cand not in USED_USERNAME:
            USED_USERNAME.add(cand)
            return cand
    return f"{name}{len(USED_USERNAME)}"


def address() -> tuple[str, float, float]:
    key = rng.choice(list(DISTRICTS))
    (lat0, lng0), roads = DISTRICTS[key]
    road = rng.choice(roads)
    no = rng.randint(1, 199)
    tail = rng.choice([f"{no}号", f"{no}号之一", f"{no}号 {rng.randint(1, 8)}栋{rng.randint(101, 2508)}室"])
    detail = f"{key}区{road}{tail}" if not key.startswith(("樟木头", "常平", "塘厦", "龙岗")) else f"{key}{road}{tail}"
    return detail, round(lat0 + rng.uniform(-0.03, 0.03), 6), round(lng0 + rng.uniform(-0.03, 0.03), 6)


def pick_time(d: date, profile: str = "normal") -> datetime:
    """下单位置不规律但有高峰：早班 6-9 点、下午 14-17 点是主峰。

    `profile` 也管时刻 —— 尖峰日**全天铺开**（早上 / 午间 / 下午 / 傍晚都有单），
    清淡日**只集中在早班那一两个时段**（就是"今天只有早上一趟车"的那种日子）。
    """
    if profile == "spike":
        r = rng.random()
        h = (rng.choice([6, 7, 8, 8, 9, 9, 10]) if r < 0.34
             else rng.choice([11, 12, 13]) if r < 0.46
             else rng.choice([14, 15, 15, 16, 16, 17]) if r < 0.84
             else rng.choice([18, 19, 20]))
    elif profile == "quiet":
        h = rng.choice([7, 8, 8, 9])
    else:
        r = rng.random()
        h = rng.choice([6, 7, 7, 8, 8, 9]) if r < 0.45 else \
            rng.choice([14, 15, 16, 17]) if r < 0.8 else rng.choice([10, 11, 12, 13, 18])
    return datetime.combine(d, time(h, rng.randint(0, 59), rng.randint(0, 59)))


def plan_days(days: list[date], total: int) -> tuple[list[date], dict[date, str]]:
    """把 `total` 单分到 `days` 这几十天里，并给每天定一个"性格"（normal/spike/quiet）。

    返回 `(逐单的业务日列表, {日期: 性格})`：列表**正好** `total` 个、乱序
    （调用方会按时刻重排），性格只用来决定"那一天的时刻怎么铺"和写进报告。

    铺法见文件头「单量怎么铺」：逐日权重 = 月度因子 × 星期因子 × 事件因子 × 抖动，
    再用**最大余额法**分下去（用 round 或随机的话总数会飘，报告里的数字就对不上了）。
    """
    profile: dict[date, str] = {d: "normal" for d in days}
    # ① 先定尖峰日 / 清淡日：它们既要参与权重，也要写进报告（"哪几天是尖峰"是给人看的）。
    #
    # ⚠️ **按整月均衡分配，不是"每 20 天随机挪"**：随机挪会撞出"某个月两个尖峰、
    #    隔壁月一个都没有"，而一个月 ±6 单的事件扰动**足以把月度差距抹平** ——
    #    实测两轮都是这样（6 月 112 vs 7 月 113、6 月 111 vs 7 月 116），
    #    而用户要的正是"月之间差距肉眼看得出来"。
    #    现在每个整月一个尖峰（**旺季那个月再加一个** —— 这本身就是"旺季更忙"的一部分）、
    #    两个清淡日；事件在月与月之间均衡，月总单量的差距就由月度因子说话。
    #    "整月" = 落在窗口里 ≥ 18 天的月份（窗口两头那半个月不排：它们本来就只铺十几天）。
    months: dict[str, list[date]] = {}
    for d in days:
        months.setdefault(f"{d:%Y-%m}", []).append(d)
    full = [k for k, v in months.items() if len(v) >= 18]
    peak = max(full, key=lambda k: MONTH_FACTORS[int(k[5:7])]) if full else None

    def _place(pool: list[date], taken: set[int]) -> date | None:
        """在 pool 里挑一天：避开周日（本来就不发车），并尽量不让同月两次撞同一个星期几。

        ⚠️ 为什么要避开同一个星期几：只有四五个尖峰日，两个都落在周一的话，
        报告里周一的日均会被抬成"最忙的两倍"—— 看起来像星期规律，其实是事件日期撞了
        （实测过：4 个尖峰里 2 个在周一 → 周一 5.4 单/天 vs 周二 4.4）。
        """
        cands = [d for d in pool if d.weekday() != 6]
        if not cands:
            return None
        return rng.choice([d for d in cands if d.weekday() not in taken] or cands)

    spike_dow: set[int] = set()
    for k in full:
        mdays = months[k]
        pool = mdays[len(mdays) // 2:]          # 月中偏后：像"节前备货"，而不是月初
        for _ in range(2 if k == peak else 1):
            d = _place(pool, spike_dow)
            if d is not None:
                profile[d] = "spike"
                spike_dow.add(d.weekday())

    quiet_dow: set[int] = set()
    for k in full:
        mdays = months[k]
        for half in (mdays[: len(mdays) // 2], mdays[len(mdays) // 2:]):
            d = _place([x for x in half if profile[x] == "normal"], quiet_dow)
            if d is not None:
                profile[d] = "quiet"
                quiet_dow.add(d.weekday())

    # ② 逐日权重
    w: dict[date, float] = {}
    for d in days:
        f = MONTH_FACTORS[d.month] * WEEKDAY_FACTORS[d.weekday()] * rng.uniform(*DAY_JITTER)
        if profile[d] == "spike":
            f *= rng.uniform(*SPIKE_FACTOR)
        elif profile[d] == "quiet":
            f *= rng.uniform(*QUIET_FACTOR)
        w[d] = f

    # ③ 最近 3 天各保底几单 —— 随机挑日子实测会把尾部挑空（09-16~09-20 一单都没有），
    #    于是「账本 → 今天 / 昨天 / 前天」三个档位点下去全是空的、消息中心最新一条是三天前，
    #    而这三个档位正是刚做完的功能，看起来就像坏了。
    #    早于早上 8 点跑就退回一天（今天只铺**已经过去的时段**，还没到的时段不该有单）。
    tail = days[-3:] if wall_now().hour >= 8 else days[-4:-1]
    per_tail = min(3, max(1, total // max(1, len(tail))))
    alloc = {d: (per_tail if d in tail else 0) for d in days}
    rest = max(0, total - per_tail * len(tail))

    # ④ 最大余额法：整数部分先给，余数给"小数部分最大"的那几天
    s = sum(w.values())
    quota = {d: rest * w[d] / s for d in days}
    for d in days:
        alloc[d] += int(quota[d])
    left = total - sum(alloc.values())
    for d in sorted(days, key=lambda x: (-(quota[x] - int(quota[x])), x))[:max(0, left)]:
        alloc[d] += 1

    return [d for d in days for _ in range(alloc[d])], profile


def distribution_report(counts: dict[date, int], days: list[date], title: str,
                        profile: dict[date, str] | None = None) -> None:
    """把"有多有少"摊开给人看 —— 这是验收「数量有多有少」的唯一依据。

    `counts` 是 `{业务日: 单量}`：预览时来自计划，真跑时**来自库里**（那一份才是事实）。
    `profile` 是计划里每天的"性格"（`plan_days` 的产物）：给了就直接拿它列尖峰/清淡日，
    没给（`--report` 只读模式）才按数据反推 —— 反推的判据写在标题里，因为它会漏掉淡月的尖峰日。
    """
    total = sum(counts.values())
    print(f"\n=== 分布报告：{title} ===")
    print(f"共 {total} 单，跨 {len(days)} 天（{days[0]} ~ {days[-1]}）")

    # ① 逐月：第一段与最后一段往往是**半个月**，所以必须同时给"天数"和"日均"，否则没法比
    print("\n逐月总单量：")
    by_month: dict[str, list[int]] = {}
    for d in days:
        by_month.setdefault(f"{d:%Y-%m}", []).append(counts.get(d, 0))
    for m, ns in by_month.items():
        flag = "  ← 半月" if len(ns) < 25 else ""
        print(f"   {m}   {len(ns):>3} 天   {sum(ns):>4} 单   日均 {sum(ns) / len(ns):>5.1f}{flag}")

    # ② 逐星期几（日均 = 该星期几的总单 ÷ 该星期几的天数）
    print("\n逐星期几：")
    dow_tot = [0] * 7
    dow_days = [0] * 7
    for d in days:
        dow_tot[d.weekday()] += counts.get(d, 0)
        dow_days[d.weekday()] += 1
    avg_dow = {i: (dow_tot[i] / dow_days[i] if dow_days[i] else 0.0) for i in range(7)}
    for i, nm in enumerate(WD_NAMES):
        print(f"   {nm}   {dow_days[i]:>2} 天 {dow_tot[i]:>4} 单   日均 {avg_dow[i]:>5.1f}  "
              + "█" * int(round(avg_dow[i])))

    # ③ 日极值 + 最忙的 5 天
    ranked = sorted(((counts.get(d, 0), d) for d in days), key=lambda x: (-x[0], x[1]))
    vals = sorted(counts.get(d, 0) for d in days)
    print(f"\n日单量：最小 {ranked[-1][0]}（{ranked[-1][1]:%m-%d}）  "
          f"最大 {ranked[0][0]}（{ranked[0][1]:%m-%d}）  中位 {vals[len(vals) // 2]}")
    print("最忙的 5 天：" + "、".join(f"{d:%m-%d}（{n}）" for n, d in ranked[:5]))

    # ④ 尖峰日 / 清淡日
    #
    # ⚠️ 计划里有这两张名单时**直接用名单**，不要拿"该星期几的全局日均"去反推：
    #    判据 `≥ 2 × 全局星期均值` 会**漏掉淡月里的尖峰日** —— 实测 8 月那个尖峰日
    #    只有 7 单（8 月本来就淡），而全局周二均值 4.9 的 2 倍是 9.8，于是它被漏掉，
    #    报告上看起来"8 月一个尖峰都没有"，而计划里明明排了。
    #    只读模式（`--report`，手上没有名单）才退回"按数据认"，并把判据写在标题里。
    if profile is not None:
        spikes = [d for d in days if profile[d] == "spike"]
        quiets = [d for d in days if profile[d] == "quiet"]
        note = "（计划：节前备货/促销）"
        qnote = "（计划：下雨/休市/盘点）"
    else:
        spikes = [d for d in days if counts.get(d, 0) >= max(5.0, 2.0 * avg_dow[d.weekday()])]
        quiets = [d for d in days
                  if d.weekday() != 6 and counts.get(d, 0) <= 0.4 * avg_dow[d.weekday()]]
        note = "（按数据认：≥ 该星期几日均的 2 倍）"
        qnote = "（按数据认：≤ 该星期几日均的 40%，周日不计）"

    def _brief(ds: list[date]) -> str:
        head = "、".join(f"{d:%m-%d}（{counts.get(d, 0)}）" for d in ds[:12])
        return head + (f" … 等 {len(ds)} 天" if len(ds) > 12 else "")

    print(f"\n尖峰日 {len(spikes)} 天{note}：{_brief(spikes)}")
    print(f"清淡日 {len(quiets)} 天{qnote}：{_brief(quiets)}")


def counts_from_db(db, days: list[date]) -> dict[date, int]:
    """库里这段时间的逐日单量（报告的事实来源）。"""
    rows = db.execute(
        select(Order.order_date, func.count())
        .where(Order.order_date >= days[0], Order.order_date <= days[-1])
        .group_by(Order.order_date)
    ).all()
    got = {r[0]: r[1] for r in rows}
    return {d: got.get(d, 0) for d in days}


def reset_business_data(db, dry_run: bool, extra_keep: list[str] | None = None) -> int:
    """清掉**业务数据与多余账号**、只留三个开发登录号与名册（`--reset`）。返回清掉的行数。

    ## 为什么清单是算出来的
    `_tools/seed/_reset_dev_db.py` 里那张 `WIPE_ORDER` 是**手写**的，写于 2026-09-20，
    而它已经过期了：之后新增的退货申请（`order_return_requests` / `order_return_request_lines`）
    与货主结算（`shipper_settlements` / `shipper_settlement_lines`）四张表**都不在清单里** ——
    实测按它清完，库里还留着 12 + 12 + 4 + 10 行。漏一张的后果不是报错，
    而是**新旧数据混在一起**：分布报告、验收脚本、真机页面都看不出来。

    所以这里从 `Base.metadata` 自己算（新表自动被覆盖），只把"不能清"写在 [RESET_KEEP] 里。
    另外它还有两个它做不到的好处：**跨库**（SQLAlchemy，SQLite 与生产 MySQL 同一份代码）
    与**先子后父**（`sorted_tables` 是父在前，倒过来删）。

    ## 为什么连"别的账号"也要删（这一条是实测撞出来的）
    只清业务表是不够的：生产那 4 个账号里有 1 个非开发号司机，本机临时库里有 23 个 ——
    它们会让紧跟着的守卫（"库里已经有别的司机了"）**照样拦下整条命令**，
    而错误信息指向的还是"--reset 没跑"（明明跑了）。所以 `--reset` 的语义是
    **把库带回"只剩三个登录号"的干净状态**（与 `_reset_dev_db.py` 完全一致）：
    业务表清空 + `users` 里非保留手机号的行删掉。dry-run 会把要删的账号逐个打出来。

    ⚠️ 名册（开销分类/运费分类/计费规则模板…）不删：它们是 `schema_bootstrap` 从在用数据里
    回填的，删掉之后**服务不重启就没人再回填**（界面上那一栏直接空掉），而种子又不造它们。

    ## ⛔ 表名一律用 `identifier_preparer.quote()`，不许自己写 `"表名"`
    第一版写的是 `text(f'select count(*) from "{t}"')`。SQLite 里 `"x"` 是标识符，能跑；
    而 **MySQL 默认 sql_mode 下 `"x"` 是字符串字面量** → `1064` 语法错。更糟的是当时
    用 try/except 把报错吞成"跳过"，于是 **`--reset` 什么表都没清、还一路显示成功**
    （2026-09-21 生产彩排实测：清完 `driver_bills` 仍是 168 行旧数据 + 新造的）。
    所以现在两件事一起改：**引号交给方言去加** + **任何一张表数不动/清不动就整条命令失败**
    （`--reset` 的语义是"把库带回干净状态"，静默跳过等于交出一份新旧混住的数据）。
    """
    from app.models import base as basemod  # noqa: E402

    prep = db.get_bind().dialect.identifier_preparer      # SQLite → "x"；MySQL → `x`
    keep = list(DEV_PHONES) + [p for p in (extra_keep or []) if p not in DEV_PHONES]
    ph = ",".join(f"'{p}'" for p in keep)

    tables = [t.name for t in basemod.Base.metadata.sorted_tables]
    targets = [t for t in reversed(tables) if t not in RESET_KEEP]   # 先子后父
    counts: list[tuple[str, int]] = []
    for t in targets:
        sql = f"select count(*) from {prep.quote(t)}"
        try:
            counts.append((t, db.scalar(text(sql)) or 0))
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"--reset 统计不了 {t}（{type(e).__name__}: {e}）。\n"
                f"  这张表在 ORM metadata 里、却在库里数不动 —— 多半是 bootstrap 没把它建出来。\n"
                f"  SQL: {sql}\n"
                f"  ⛔ 不跳过：跳过会让 --reset 交出一份「新旧混住」的数据，而日志全是绿的。"
            ) from e
    total = sum(n for _, n in counts)

    users_t = prep.quote("users")
    doomed = db.execute(text(
        f"select id, phone, role, full_name from {users_t} where phone not in ({ph}) order by id"
    )).all()

    print(f"\n{'将' if dry_run else ''}清空 {len(counts)} 张业务表，共 {total} 行"
          f"（只列出非空的）：")
    for t, n in counts:
        if n:
            print(f"   {n:>7}  {t}")
    print(f"{'将' if dry_run else ''}删除 {len(doomed)} 个非保留账号，保留 {', '.join(keep)}：")
    for r in doomed[:40]:
        print(f"   {r[0]:>5}  {r[1]:<13} {r[2]:<11} {r[3] or ''}")
    if len(doomed) > 40:
        print(f"   … 还有 {len(doomed) - 40} 个")
    print(f"   保留的表：{', '.join(sorted(RESET_KEEP))}")
    if dry_run:
        return total

    # ⛔ 任何一张表清不动 → **整条命令失败**（不是打印一行跳过继续跑）。
    #    全部 DELETE 在**同一个事务**里，失败就 rollback：宁可一张没清，也不要清一半。
    for t, _ in counts:
        sql = f"delete from {prep.quote(t)}"
        try:
            db.execute(text(sql))
        except Exception as e:  # noqa: BLE001
            db.rollback()
            raise RuntimeError(
                f"--reset 清不动 {t}（{type(e).__name__}: {e}）。\n  SQL: {sql}\n"
                f"  已回滚：这张表与其余表**一行都没删**，库还是你原来那份。"
            ) from e
    if doomed:
        try:
            db.execute(text(f"delete from {users_t} where phone not in ({ph})"))
        except Exception as e:  # noqa: BLE001
            db.rollback()
            raise RuntimeError(f"--reset 删不掉多余账号（{type(e).__name__}: {e}），已回滚。") from e
    db.commit()
    still = {t: db.scalar(text(f"select count(*) from {prep.quote(t)}")) for t, _ in counts}
    left = {k: v for k, v in still.items() if v}
    if left:
        # 清完还非零 = 这条命令没达成它的语义，必须让人看见（而不是当成"大概清干净了"）
        raise RuntimeError(f"--reset 跑完了，但这些表仍有数据：{left}（库没回到干净状态）")
    print("清空后仍非零的业务表：（全空）")
    print(f"剩余账号：{db.scalar(text(f'select count(*) from {users_t}'))} 个")
    return total


def write_delivery_photo(order_id: int, order_no: str, when: datetime, name: str) -> str:
    """写一张**真的**送达照片（App 里能打开，不是假 URL）。

    480×640 的灰底图 + 单号/时间/收货人；真实业务里这是司机拍的货物照，
    这里给的是"能看得出是哪一单"的占位（颜色随单号变，免得满屏一模一样）。
    """
    from PIL import Image, ImageDraw

    d = UPLOAD_ROOT / "delivery" / str(order_id)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "seed.jpg"
    tint = 210 + (order_id % 30)
    im = Image.new("RGB", (480, 640), (tint, tint - 6, tint - 14))
    dr = ImageDraw.Draw(im)
    for i in range(0, 640, 40):                      # 一点纹理：不是纯色块
        dr.line([(0, i), (480, i + 20)], fill=(tint - 18, tint - 22, tint - 30), width=1)
    dr.rectangle([24, 24, 456, 616], outline=(120, 120, 128), width=3)
    dr.text((40, 60), f"送达凭证  {order_no}", fill=(40, 40, 48))
    dr.text((40, 96), f"时间  {when:%Y-%m-%d %H:%M}", fill=(60, 60, 70))
    dr.text((40, 132), f"收货  {name}", fill=(60, 60, 70))
    dr.text((40, 560), "SOrders · 演示数据（按单生成）", fill=(120, 120, 130))
    im.save(path, quality=82)
    return f"/static/uploads/delivery/{order_id}/seed.jpg"


def write_place_photo(place_id: int, name: str) -> str:
    from PIL import Image, ImageDraw

    d = UPLOAD_ROOT / "places"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"seed-{place_id}.jpg"
    tint = 200 + (place_id % 40)
    im = Image.new("RGB", (640, 480), (tint - 10, tint, tint - 4))
    dr = ImageDraw.Draw(im)
    dr.rectangle([20, 20, 620, 460], outline=(120, 126, 132), width=3)
    dr.text((40, 60), f"档口/门店：{name}", fill=(40, 44, 50))
    dr.text((40, 430), "SOrders · 演示数据", fill=(120, 126, 132))
    im.save(path, quality=82)
    return f"/static/uploads/places/seed-{place_id}.jpg"


def main() -> int:
    t0 = wall_now()              # 造数是要在生产上真跑一次的，耗时得如实报出来
    ap = argparse.ArgumentParser(description="造一份规范的 3~4 个月演示数据")
    ap.add_argument("--yes", action="store_true", help="真的写库（缺省只预览）")
    #: 单量：默认 2400 —— 120 天摊下来约 20 单/天。定这个数的依据是**主数据自己**：
    #: 本脚本造 33 个客户（24 货主 + 9 批发商）、23 个司机，于是
    #:   · 每个客户 ≈ 0.6 单/天（一周 4 趟，食堂/超市补货就是这个量级）；
    #:   · 每个司机 ≈ 0.9 单/天（这一行是整车配送，一天一两趟）。
    #: 再往上加就不真实了（客户一天要下两次单），要更大的绝对量得先加客户数。
    #: 420（旧默认）只有 3.5 单/天 —— 报表里月营业额才一万多，22 个司机分不下来，看着就不像在经营。
    ap.add_argument("--orders", type=int, default=2400)
    #: 天数：默认 120 天（3~4 个月）。用户 2026-09-21：「大概是 3 到 4 个月的数据」
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--report", action="store_true",
                    help="只读库：把已经造好的数据打一份分布报告，不写任何东西"
                         "（⚠️ 与 --yes 同用时它不生效：真跑本来就会在最后打同一份报告）")
    #: 先清业务数据（**保留三个开发登录号与名册**）再灌。清库清单是算出来的，SQLite 与 MySQL 通用。
    ap.add_argument("--reset", action="store_true",
                    help="先清空业务数据（保留 users 里那三个开发号与几张名册）再灌；单独用它只预览会清什么")
    ap.add_argument("--keep", action="append", default=[], metavar="PHONE",
                    help="--reset 时额外保留的手机号（可重复）；三个开发号永远保留。"
                         "⚠️ 守卫也认它 —— 只留账号不清数据的话，那个账号仍会拦住整条命令")
    args = ap.parse_args()

    db = SessionLocal()
    # 发号池先灌入**库里已有的手机号**：`phone()` 每一轮都从同一个种子出发，于是
    # "上一轮造过的号"这一轮会**再发一次** —— 在空库上没感觉，但只要库里留着任何账号
    # （`--keep` 保留的、或上一次没清干净的），就是 `UNIQUE constraint failed: users.phone`
    # （实测踩到：`--reset --yes --keep <某个种子造过的司机号>` 直接崩在造账号那一步）。
    # 顺带堵住一个一直没有触发过的口子：发号规则 `13[5-9]xxxxxxxx` 与三个开发号同形，
    # 理论上能撞上 `13800000001`。
    USED_PHONE.update(p for (p,) in db.query(User.phone).all() if p)
    USED_USERNAME.update(u for (u,) in db.query(User.username).all() if u)
    today = wall_now().date()    # 业务当地的今天（服务器时区可能是 UTC，不能写 date.today()）
    start = today - timedelta(days=args.days)
    days = [start + timedelta(days=i) for i in range(args.days + 1)]

    # ⚠️ 只读报告排在**所有守卫之前**：它最常见的用途就是在生产上核"已经灌好的那一份"，
    #    而生产上当然有别的司机账号（实测被守卫拦过）。它一个字都不写，没有理由拦它。
    # ⚠️ 带 `--yes` 时它**不返回**：真跑在最后本来就会打同一份报告（还是从库里读的那份），
    #    于是 `--reset --yes … --report` 这种写法不会被误当成"只看报告、不灌数"。
    if args.report and not args.yes:
        distribution_report(counts_from_db(db, days), days, "库里现有的数据（只读）")
        return 0

    # ★ 三个开发登录账号是**复用**的（不是重建）：按手机号查，缺一个就直接停 ——
    #   这份数据是给"已经有这三个登录号"的库用的（本机由 `_reset_dev_db.py` 保留，
    #   生产由建号流程建）。缺号时 `.one()` 会抛 NoResultFound 那种看不懂的栈，
    #   所以先给一句能照着做的中文。
    # ⚠️ 保留名单**只有一份**：`--reset` 保留谁，紧跟着的守卫就必须认谁。
    #    两处各写一份的后果是 `--keep` 变成**自相矛盾**的参数 —— 它救了那个账号，
    #    而守卫照样因为那个账号把整条命令拦下（生产上 `13800000004` 是司机，实测正好会被拦）。
    dev_phones = tuple(DEV_PHONES) + tuple(p for p in args.keep if p not in DEV_PHONES)
    # 缺号检查只认**三个开发号**：`--keep` 那些的语义是"别删它"，不要求它先存在
    missing = [p for p in DEV_PHONES if db.query(User).filter(User.phone == p).count() == 0]
    if missing:
        print(f"⚠️ 库里缺这几个登录账号：{'、'.join(missing)}")
        print("   这份脚本**只复用**这三个账号（按手机号查），它不负责建号 —— 先建号再跑。")
        return 1

    # 清业务数据要在"查已存在的司机"**之前**做，否则 `--reset --yes` 会被自己的守卫拦住。
    # ⚠️ `extra_keep` 与下面守卫用的 [dev_phones] 是**同一份保留名单**（一个救账号、一个认账号），
    #    两边必须一起看，改一处就要改另一处。
    if args.reset:
        reset_business_data(db, dry_run=not args.yes, extra_keep=args.keep)
        if not args.yes:
            print("\n（预览模式：什么都没删。加 --yes 才会清、清完接着灌）")
            return 0

    # 守卫：库里已经有**别的司机**就说明这是一张有数据的库，直接在它上面灌会新旧混住
    # （重复的商品名会撞唯一键、老的 9 月单会混进分布报告里）。先 `--reset --yes`。
    # ⚠️ "别的"是按 [dev_phones] 判的，而它与 `--reset` 用的是**同一份保留名单**（见上）。
    if db.query(User).filter(User.role == UserRole.DRIVER,
                             User.phone.notin_(dev_phones)).count() > 0:
        print("⚠️ 库里已经有别的司机账号了 —— 这份脚本是给**清空后的库**用的，先跑：")
        print("   python -m scripts.seed_demo_data --reset --yes     # 清业务数据并接着灌（推荐）")
        print("   python -m scripts.seed_demo_data --reset           # 只看看会清掉什么")
        print("   要连某个司机账号一起留着，就加 --keep <手机号>（`--reset` 与这个守卫都认它）")
        return 1
    dispatcher = db.query(User).filter(User.phone == "13800000001").one()

    # ⚠️ 计划要**在预览分支之前**算出来：预览与真跑必须看到同一份计划
    #    （`plan_days` 会消耗 rng，放到后面算的话预览看到的分布就不是将要写进去的那份）
    plan, profile = plan_days(days, args.orders)
    print(f"将造 {start} ~ {today}（{args.days} 天）的演示数据：订单 {args.orders} 单")
    if not args.yes:
        planned: dict[date, int] = {d: 0 for d in days}
        for d in plan:
            planned[d] += 1
        distribution_report(planned, days, "计划（还没写库）", profile)
        print("\n（预览模式，什么都没写。加 --yes 执行）")
        return 0

    pwd = hash_password("123321")

    # ---------------------------------------------------------- ① 商品分类 + 商品
    for i, (name, _) in enumerate(CATEGORIES, start=1):
        db.add(ProductCategory(name=name, sort_order=i))
    products: list[Product] = []
    for cat, names in CATEGORIES:
        for name in names:
            cost = Decimal(rng.choice([6, 8, 9, 11, 12, 14, 16, 18, 22, 26, 32, 38, 45]))
            price = (cost * Decimal(str(round(rng.uniform(1.15, 1.45), 2)))).quantize(Decimal("0.5"))
            products.append(Product(name=name, category=cat, unit=rng.choice(UNITS),
                                    default_unit_price=price, cost_price=cost,
                                    stock=rng.choice([0, 12, 36, 60, 90, 120, 200, 320]),
                                    low_stock_alert=rng.choice([10, 20, 30]),
                                    is_active=True, name_color="#17181C"))
    db.add_all(products)
    db.flush()
    print(f"  商品分类 {len(CATEGORIES)} 个、商品 {len(products)} 件")

    # ---------------------------------------------------------- ② 货主 / 批发商 / 计费规则 / 司机 / 车辆
    shippers: list[User] = []
    for i in range(24):
        nm = person(0.25) if i < 6 else rng.choice(FAMILY_NAMES) + rng.choice(STORES)
        shippers.append(User(username=uniq_username(nm), full_name=nm, phone=phone(), role=UserRole.SHIPPER,
                             password_hash=pwd, is_active=True, is_member=False))
    members: list[User] = []
    for nm in ["兴发果业", "顺鑫蔬菜批发", "恒丰粮油", "城东水产", "万家冻品", "新叶生鲜配送",
               "金禾米业", "广达调味"]:
        members.append(User(username=uniq_username(nm), full_name=nm, phone=phone(), role=UserRole.SHIPPER,
                            password_hash=pwd, is_active=True, is_member=True))
    db.add_all(shippers + members)
    db.flush()

    # ⚠️ **客户档案（`customers`）必须一起建**：账本/收款单挂的是 `customer_id`，而
    #    `resolve_customer_for_order` 只**查**不建 —— 直接拿模型建了货主账号却忘了这张档案，
    #    收款单会一条都建不出来（`customer_id` 无处可挂，而且它是静默返回 None）。
    #    真系统里这一步是「客户管理 → 新增」做的（`api/v1/customers.py::create_customer`，
    #    唯一写入点：`kind='registered'` + `user_id` + `tmp_phone_key=None`）。
    from app.models.customer import Customer  # noqa: E402
    from app.models.enums import CustomerKind  # noqa: E402

    for s in shippers + members:
        db.add(Customer(kind=CustomerKind.REGISTERED, user_id=s.id, name=s.full_name,
                        phone=s.phone, tmp_phone_key=None, is_member=s.is_member))
    # 散客（没有账号、只有电话的临时货主）——真实业务里这一类不少，账本上按名字记
    tmp_names = ["陈伯（散客）", "李姐（散客）", "罗师傅（散客）"]
    for nm in tmp_names:
        p = phone()
        db.add(Customer(kind=CustomerKind.TMP, user_id=None, name=nm, phone=p,
                        tmp_phone_key=p, is_member=False))
    db.commit()

    rules: list[DriverBillingRule] = []
    # 计件规则**带上车型**（`driver_billing_rules.vehicle_type`）：这是"这种车按这个价"的真实口径，
    # 也让 `POST /driver-billing-rules/attach` 的「车型对不上」拦截有东西可拦（挂车的价挂不到小车上）。
    # 月薪与提成规则不限车型（NULL = 都能挂）。
    for nm, piece, rate, salary, vt in [
        ("按单计件 · 小货车", Decimal("22"), None, None, "small"),
        ("按单计件 · 大货车", Decimal("45"), None, None, "large"),
        ("按单计件 · 挂车", Decimal("78"), None, None, "trailer"),
        ("月薪司机 · 固定 6500", None, None, Decimal("6500"), None),
        ("运费提成 8%", None, Decimal("8"), None, None),
        ("运费提成 12%", None, Decimal("12"), None, None),
    ]:
        rules.append(DriverBillingRule(name=nm, piece_amount=piece, commission_rate=rate,
                                       salary=salary, vehicle_type=vt))
    db.add_all(rules)
    db.flush()
    # 车型 → 计件规则，**唯一一份映射**（保证造不出"车型对不上"的挂载）
    piece_by_vt = {"small": rules[0], "large": rules[1], "trailer": rules[2]}

    drivers: list[User] = []
    for i in range(22):
        nm = person(0.08)
        vt = rng.choice(VEHICLE_TYPES)
        rule = piece_by_vt[vt]
        if i in (5, 9, 16):                     # 三位月薪司机
            rule = rules[3]
        elif i in (3, 12, 19):                  # 三位提成司机
            rule = rng.choice(rules[4:])
        drivers.append(User(username=uniq_username(nm), full_name=nm, phone=phone(), role=UserRole.DRIVER,
                            password_hash=pwd, is_active=True, vehicle_type=vt,
                            driver_rule_id=rule.id,
                            billing_mode="SALARY" if rule.salary else "PIECE"))
    # ⚠️ **三个开发登录账号必须自己也有数据**（2026-09-20 真机发现的大洞）：
    #    第一版把所有订单分给了新造的 24 个货主 / 22 个司机，于是换个账号登进去就是一片空白 ——
    #    货主号 0 单 0 账本 0 地点、司机号 0 单 0 账单（派单员号靠"全局视图"看着是满的，
    #    正好把这件事盖住了）。这份数据是拿来验收的，而验收用的就是这三个账号。
    #    所以：货主号进批发商池（它 `is_member=1`，本来就该有专属价、批发商账、收款单），
    #    司机号放在车队**队首**（车辆是按 `drivers[i % len]` 发的，站队首才有车）。
    dev_shipper = db.query(User).filter(User.phone == "13800000002").one()
    dev_driver = db.query(User).filter(User.phone == "13800000003").one()
    # 占位名（Shipper/Driver/Dispatcher）本身就是"测试数据"的样子 —— 它会作为**商户名**
    # 出现在账本、订单、消息中心里。只在还是占位名的时候改，改过（或用户自己起过名）就不碰。
    for u, pretty in ((dispatcher, "陈国强"), (dev_shipper, "永盛食品"), (dev_driver, "李伟明")):
        if u.full_name in ("Dispatcher", "Shipper", "Driver"):
            u.full_name = pretty
            u.username = pretty
    dev_driver.vehicle_type = "small"           # 小车 → 挂小货车那一档（车型对得上）
    dev_driver.billing_mode = "PIECE"
    dev_driver.driver_rule_id = piece_by_vt["small"].id
    drivers.insert(0, dev_driver)
    members.append(dev_shipper)
    db.add_all(drivers)
    db.flush()

    for i in range(14):
        drv = drivers[i % len(drivers)]
        plate = PLATE_PREFIX[i % 3] + "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(2)) \
            + f"{rng.randint(1000, 9999)}"
        db.add(Vehicle(plate_no=plate, vehicle_type=drv.vehicle_type, driver_id=drv.id, is_active=True))
    for nm in ARREARS_UNITS:
        db.add(ArrearsUnit(name=nm, phone=phone(), remark="月结 30 天"))
    templates: list[FreightTemplate] = []
    for i, (a, b, fee) in enumerate(ROUTES):
        templates.append(FreightTemplate(
            name=f"{a} → {b}", route_id=i + 1, from_place=a, to_place=b,
            price_name=rng.choice(["一车价", "整车配送", "按车结算"]),
            vehicle_type=rng.choice(VEHICLE_TYPES), fee=Decimal(fee),
            remark="含装卸；超 3 吨另议", created_by=dispatcher.id))
    db.add_all(templates)
    db.flush()
    for t in templates[:6]:
        db.add(FreightTemplateDriver(template_id=t.id, driver_id=rng.choice(drivers).id))
    db.flush()
    print(f"  货主 {len(shippers)}、批发商 {len(members)}、司机 {len(drivers)}、车辆 14、"
          f"计费规则 {len(rules)}、挂账单位 {len(ARREARS_UNITS)}、运费模板 {len(templates)}")

    # ---------------------------------------------------------- ③ 地点库 / 线路 / 联系人 / 分组
    for i, nm in enumerate(["常用配送点", "食堂档口", "市场档口", "工厂仓库"], start=1):
        db.add(PlaceCategory(shipper_id=dispatcher.id, name=nm, sort_order=i))
    locs: list[ShipperLocation] = []
    for i in range(64):
        nm = f"{person(0.35)}的店" if i % 9 == 0 else rng.choice(FAMILY_NAMES) + rng.choice(STORES)
        if i % 7 == 0:
            nm = f"{nm}（{rng.choice(WAREHOUSES)}）"
        detail, lat, lng = address()
        locs.append(ShipperLocation(shipper_id=dispatcher.id, name=nm, detail_address=detail,
                                    address_lat=lat, address_lng=lng, remark="",
                                    category=rng.choice(["常用配送点", "食堂档口", "市场档口", "工厂仓库"]),
                                    is_warehouse=(i % 7 == 0), image_urls="[]"))
    db.add_all(locs)
    db.flush()
    for i, l in enumerate(locs):
        img = write_place_photo(i + 1, l.name) if i < 10 else None
        db.add(Place(name=l.name, detail_address=l.detail_address, lat=l.address_lat, lng=l.address_lng,
                     source="dispatcher", use_count=rng.randint(0, 12), created_by=dispatcher.id,
                     image_urls=f'["{img}"]' if img else "[]"))
    for i in range(20):
        a, b = rng.sample(locs, 2)
        db.add(ShipperAddress(shipper_id=dispatcher.id, receiver_name=person(0.4), phone=phone(),
                              detail_address=b.detail_address, address_lat=b.address_lat,
                              address_lng=b.address_lng, origin_address=a.detail_address,
                              origin_lat=a.address_lat, origin_lng=a.address_lng,
                              remark="", is_default=(i == 0), image_urls="[]"))
    contacts = [(person(0.45), l) for l in rng.sample(locs, 36)]
    for nm, l in contacts:
        db.add(ShipperContact(shipper_id=dispatcher.id, display_name=f"{nm}（{l.name}）", phone=phone()))
    # 货主侧也各有一两个自己的地点。**开发号的货主固定 3 个**（第 0 个就是它）：
    # 它是真机上要登进去验收的那个账号，地址库空着等于这个模块没数据。
    for k, s in enumerate([dev_shipper] + rng.sample(shippers, 12)):
        for _ in range(3 if k == 0 else rng.randint(1, 3)):
            detail, lat, lng = address()
            db.add(ShipperLocation(shipper_id=s.id, name=f"{s.full_name}{rng.choice(['仓库', '门店', '档口', '食堂'])}",
                                   detail_address=detail, address_lat=lat, address_lng=lng,
                                   remark="", image_urls="[]"))
    db.flush()
    # 开发号的货主还要有**线路与联系人**：地址与联系人页是三段（常用线路 / 联系人 / 地点），
    # 只给地点的话另外两段在真机上还是空的 —— 而这一页正是要验收的。
    own_dev = (db.query(ShipperLocation)
               .filter(ShipperLocation.shipper_id == dev_shipper.id,
                       ShipperLocation.is_deleted == False).all())   # noqa: E712
    for i in range(2):
        a, b = rng.sample(own_dev, 2)
        db.add(ShipperAddress(shipper_id=dev_shipper.id, receiver_name=person(0.4), phone=phone(),
                              detail_address=b.detail_address, address_lat=b.address_lat,
                              address_lng=b.address_lng, origin_address=a.detail_address,
                              origin_lat=a.address_lat, origin_lng=a.address_lng,
                              remark="", is_default=(i == 0), image_urls="[]"))
    for l in own_dev:
        db.add(ShipperContact(shipper_id=dev_shipper.id,
                              display_name=f"{person(0.45)}（{l.name}）", phone=phone()))
    db.commit()
    print(f"  地点 {len(locs)} + 货主自有 {len(own_dev)}（开发号）、线路 20 + 2、联系人 {len(contacts)} + 3、地点分组 4")

    # ---------------------------------------------------------- ④ 批发商专属价
    n_price = 0
    for m in members:
        for p in rng.sample(products, rng.randint(6, 12)):
            db.add(PriceRule(shipper_id=m.id, product_id=p.id,
                             special_unit_price=(p.default_unit_price *
                                                 Decimal(str(round(rng.uniform(0.82, 0.95), 2)))
                                                 ).quantize(Decimal("0.5"))))
            n_price += 1
    db.commit()
    print(f"  批发商专属价 {n_price} 条")

    # ---------------------------------------------------------- ⑤ 订单（走真实业务函数）
    made = 0
    stat = {s: 0 for s in ("delivered", "cancelled", "pending", "dispatched", "accepted")}
    own_by_shipper: dict[int, list[ShipperLocation]] = {}
    for s in shippers + members:
        own = db.query(ShipperLocation).filter(ShipperLocation.shipper_id == s.id,
                                               ShipperLocation.is_deleted == False).all()  # noqa: E712
        if own:
            own_by_shipper[s.id] = own

    # ⚠️ **先把"哪天几单"展开成具体时刻、排好序，再照着建单**。顺序不是小事：
    #    `GET /orders` 是 `order_by(Order.id.desc())`（列表按 id 排），所以 id 必须与时间同向，
    #    **包括同一天内的先后**（只按"天"排序还不够：天内的下单时刻是随机的，
    #    实测还有 895 个逆序对）。第一版是随机挑日子即时建单，于是 7 月的单拿到了比 9 月更大的 id，
    #    真机上「派单作业 → 待派池」第一张是两个月前的单（看起来像一批单没人管）。
    #
    # `plan` 与 `profile` 在 main() 开头就算好了（那里有个 `plan_days` 的注释说明为什么）：
    #   · `plan`  —— 逐单的业务日（正好 `--orders` 个，乱序）
    #   · `profile` —— 每天的性格（normal/spike/quiet），决定**那一天的时刻怎么铺**
    # 时刻也要按性格走：尖峰日全天铺开、清淡日只集中在早班（见 `pick_time`）。
    # 单不能下在"现在"之后；留 30 分钟余量（送达时刻还在这之后）
    cap = wall_now() - timedelta(minutes=30)
    slots = sorted(min(pick_time(d, profile[d]), cap - timedelta(minutes=rng.randint(0, 40)))
                   for d in plan)
    for i in range(1, len(slots)):                            # 严格递增（id 与时间同向）
        if slots[i] <= slots[i - 1]:
            slots[i] = slots[i - 1] + timedelta(minutes=1)
    for created in slots:
        d = created.date()
        per_day = 1          # plan 已展开成一个个时刻：一个时刻建一单
        for _ in range(per_day):
            shipper = rng.choice(shippers + members)
            lines = rng.sample(products, rng.choices([1, 2, 3, 4, 5], weights=[38, 28, 18, 10, 6], k=1)[0])
            own = own_by_shipper.get(shipper.id)
            loc = rng.choice(own) if own and rng.random() < 0.7 else rng.choice(locs)
            route = rng.choice(ROUTES)
            payment = rng.choices(["arrears", "cash"], weights=[78, 22], k=1)[0]
            # 单号形状与生产一致：`SO{下单日}{10 位随机}`（`services/auth_service.py::gen_order_no`）
            o = Order(order_no=f"SO{created:%Y%m%d}{rng.randrange(10**10):010d}",
                      status=OrderStatus.PENDING_DISPATCH,
                      shipper_id=shipper.id, order_date=created.date(),
                      # ⚠️ `order_date` 是**业务日**（上面那个 `created` 就是业务当地的墙上时间），
                      #    所以它不做时区换算；而两个时间戳必须过 `to_utc_naive()`（见 `wall_now` 的注释）。
                      created_at=to_utc_naive(created), updated_at=to_utc_naive(created),
                      delivery_description=rng.choice(["送到后门卸货", "走正门找收货员", "卸在一楼月台",
                                                       "提前 10 分钟打电话", "冷藏品请直接进冷库"]),
                      address_detail=loc.detail_address, address_lat=loc.address_lat,
                      address_lng=loc.address_lng, contact_dongjia_phone=phone(),
                      # 收货人 = 到现场接货的那个人（真实业务里是店里/食堂的某个人，不是货主本人）；
                      # 下单人 = 下这一单的人（这里是货主账号本人）。
                      # ⛔ 两列都**必须填**：卡片与详情显示的就是这两个名字，空着界面上就是一条横线
                      #    （`_verify_demo_data.py` 的「该填的都填」会拦）。
                      contact_dongjia_name=person(0.4),
                      contact_boss_name=shipper.full_name,
                      contact_boss_phone=shipper.phone,
                      remark=rng.choice(["", "", "尽量上午送到", "货要新鲜的", "上次少了两箱，这次点清", "带票据过来"]),
                      freight_fee=Decimal(route[2]) + Decimal(rng.choice([0, 0, 5, 10, 15])),
                      payment_method=payment,
                      # 派单时勾了「收取现金」：司机送到就得当场收（这是派单动作上的标志，不是收款记录）
                      collect_cash=(payment == "cash"),
                      paid=False, is_exception=False,
                      # ⛔ `delivery_photo_urls` 是 **JSON 列**，必须给 list；
                      #    给字符串 `"[]"` 会原样存成"一个字符串"，读的时候
                      #    `OrderOut.delivery_photo_urls: list | None` 直接 500
                      #    （真机实测：派单作业页 `GET /orders?status=PENDING_DISPATCH` 全挂）。
                      #    隔壁 `image_urls` 是 Text 列、还带 `mode="before"` 的解析器，
                      #    所以那边写成字符串是对的 —— 两列形状不同，别照抄。
                      image_urls="[]", delivery_photo_urls=[])
            db.add(o)
            db.flush()
            for p in lines:
                qty = rng.choices([1, 2, 3, 4, 5, 6, 8, 10, 12, 20],
                                  weights=[22, 18, 14, 12, 10, 8, 6, 5, 3, 2], k=1)[0]
                price = p.default_unit_price
                if shipper.is_member:
                    pr = db.query(PriceRule).filter(PriceRule.shipper_id == shipper.id,
                                                    PriceRule.product_id == p.id).first()
                    if pr is not None:
                        price = pr.special_unit_price
                db.add(OrderProduct(order_id=o.id, product_id=p.id, product_name_snapshot=p.name,
                                    unit_snapshot=p.unit, quantity=qty, unit_price=price,
                                    line_total=(price * qty).quantize(Decimal("0.01")),
                                    cost_price_snapshot=p.cost_price))
            made += 1

            # ⚠️ **"还在飞"的状态只出现在最近 10 天**（待派 / 派单中 / 已接单）：
            #    两个多月前下的单不可能到现在还挂在待派池里 —— 真机上那就是"一批单没人管"的假象
            #    （第一版按比例随机铺，7 月的单也有待派的，滚到下面就看见）。
            #    老单只可能是"已送达 / 已撤销"两档（0.72 : 0.08 的比例不变）。
            # ⚠️ 判据用**业务日之差**（`today - created.date()`），不是"现在减下单时刻"：
            #    后者会把"正好 10 天前"那一天的早班单算成超期（10 天前 08:00 的单 vs 现在 09:00
            #    = 10.04 天），而验收脚本是按**日期差**判的（`julianday(date('now','localtime'))`）
            #    —— 两边口径不一致时，红的是数据，而错的是判据（实测被验收脚本抓过一次）。
            fresh = (today - created.date()).days <= 10
            roll = rng.random() if fresh else rng.uniform(0.0, 0.80)
            if roll < 0.72:                       # 已送达：账本/账单/现金流水由业务函数写
                driver = rng.choice(drivers)
                assign_driver(db, o, driver, dispatcher,
                              internal_note=rng.choice(["", "", "客户催过", "顺路带过去", "熟客"]))
                o.dispatched_at = created + timedelta(minutes=rng.randint(5, 90))
                o.driver_acknowledged_at = o.dispatched_at + timedelta(minutes=rng.randint(2, 120))
                o.status = OrderStatus.ACCEPTED
                db.flush()
                dlv = min(o.driver_acknowledged_at + timedelta(hours=rng.uniform(0.7, 9)),
                          wall_now() - timedelta(hours=1))
                # ⚠️ 当天现造的单会被上面那个 `now - 1 小时` 压到**下单之前**（"送达早于下单"）。
                #    那就改成"下单后过一会儿送到"（`created` 留了 30 分钟余量，仍在过去）。
                if dlv <= created:
                    dlv = created + timedelta(minutes=rng.randint(5, 25))
                # ⚠️ 当天现造的单会被上面那个 `now - 1 小时` 压回来：派单/接单时刻是"下单 + 几分钟"，
                #    压过之后可能出现**送达早于接单**（真机上就是一条自相矛盾的订单）。
                #    倒着修：送达不动，把派单/接单压到送达之前，且都不早于下单时刻。
                #    先只**算**出来，写回放在 `complete_delivery` 之后（原因见下面那段注释）。
                dsp, ack = o.dispatched_at, o.driver_acknowledged_at
                if dlv <= ack:
                    room = max(0, int((dlv - created).total_seconds() // 60))
                    ack = max(created, dlv - timedelta(minutes=min(room // 2, 60)))
                    dsp = max(created, ack - timedelta(minutes=min(room // 3, 30)))
                o.delivered_at = dlv
                dmg = None
                if rng.random() < 0.035:          # 3.5% 有货损（果蔬磕碰是常事）
                    line = db.query(OrderProduct).filter(OrderProduct.order_id == o.id).first()
                    if line and line.quantity > 1:
                        # ⚠️ 这里必须是 schema 对象（`DamageItem`），不是 dict ——
                        #    `complete_delivery` 按属性读（`item.order_product_id`）
                        dmg = [DamageItem(order_product_id=line.id, quantity=1)]
                photo = write_delivery_photo(o.id, o.order_no, dlv, shipper.full_name)
                complete_delivery(db, o, driver, [photo],
                                  driver_remark=rng.choice(DRIVER_REMARKS),
                                  damage_items=dmg,
                                  damage_note="运输途中挤压" if dmg else "")
                # ⚠️ `complete_delivery` 内部把 `delivered_at` 写成**"现在"**（线上就该这样）；
                #    我们是在一次性回放三个月的历史，所以**送达时间要按回放的时间重设回去** ——
                #    否则账本、司机账单、报表会全部挤在"今天"那一个月（第一版就是这样：
                #    订单跨 6~9 月，账本 683 行全在 9 月）。只改时间，金额一个字都不动。
                #
                # ⛔ 这三个时刻必须在 `complete_delivery` **之后**写：它的第一件事是
                #    `lock_order_row` → `db.refresh(order)`，会把**还没 flush 的内存改动整份丢掉**
                #    （`dispatched_at` / `driver_acknowledged_at` 就属于这一类）。
                #    第一版只给 `delivered_at` 补了这一步，于是"送达早于接单"的那一单漏了出来。
                # ⚠️ 这四个时间戳**必须在这里过 `to_utc_naive()`**（库里存 UTC，见 `wall_now`）：
                #    上面的 `dlv/dsp/ack` 都是业务当地的墙上时间，直接写库会让 App 读成 +8 小时。
                o.delivered_at = to_utc_naive(dlv)
                o.dispatched_at = to_utc_naive(dsp)
                o.driver_acknowledged_at = to_utc_naive(ack)
                o.updated_at = to_utc_naive(dlv)
                if rng.random() < 0.04:
                    o.is_exception = True
                    o.exception_reason = rng.choice(["客户说少送一箱", "迟到两小时", "包装破损"])
                # ⚠️ 这里**不**直接写 `paid`：核销必须走收款单（下面第 ⑦ 步），
                #    否则会出现"订单已收款、但账上没有任何一笔对应的收款记录"（账实不符）。
                stat["delivered"] += 1
            elif roll < 0.80:
                o.status = OrderStatus.CANCELLED
                o.cancelled_at = to_utc_naive(created + timedelta(hours=rng.randint(1, 20)))
                stat["cancelled"] += 1
            elif roll < 0.86:
                assign_driver(db, o, rng.choice(drivers), dispatcher, internal_note="")
                o.dispatched_at = to_utc_naive(created + timedelta(minutes=rng.randint(5, 60)))
                stat["dispatched"] += 1
            elif roll < 0.92:
                assign_driver(db, o, rng.choice(drivers), dispatcher, internal_note="")
                o.dispatched_at = to_utc_naive(created + timedelta(minutes=rng.randint(5, 60)))
                o.driver_acknowledged_at = to_utc_naive(
                    created + timedelta(minutes=rng.randint(5, 60) + rng.randint(3, 60)))
                o.status = OrderStatus.ACCEPTED
                stat["accepted"] += 1
            else:
                stat["pending"] += 1
            db.commit()
            if made % 50 == 0:
                print(f"    …已造 {made} 单")
    print(f"  订单 {made}：送达 {stat['delivered']} / 待派 {stat['pending']} / 派单中 {stat['dispatched']} / "
          f"已接单 {stat['accepted']} / 已撤销 {stat['cancelled']}")

    # ---------------------------------------------------------- ⑥ 手工流水 / 开销
    for _ in range(18):
        p = rng.choice(products)
        qty = rng.randint(2, 30)
        db.add(Ledger(shipper_id=rng.choice(shippers).id, entry_date=rng.choice(days),
                      product_name=p.name, quantity=qty, unit_price=p.default_unit_price,
                      total=(p.default_unit_price * qty).quantize(Decimal("0.01")),
                      product_id=p.id, source=LedgerSource.MANUAL, note=rng.choice(LEDGER_NOTES)))
    # ⚠️ 车相关的几类**必须挂上车**（2026-09-20）：开销卡片上"燃油/维修突出车辆"
    #    靠的就是 `vehicle_id`（分类名册的 `link_kind=vehicle` 只说明"该突出车"）——
    #    一笔都不挂车的话，真机上永远只看到"退到司机"的兜底路径，看不到正路径。
    VEHICLE_CATEGORIES = ("加油", "维修", "过路", "停车", "罚款", "保险")
    # 车是上面逐台 `db.add` 建的、没留列表变量 —— 这里现查一次（可用的那几台）
    cars = list(db.scalars(select(Vehicle).where(Vehicle.is_active.is_(True))))
    for _ in range(30):
        et = rng.choice(list(EXPENSE_NOTES))
        car = rng.choice(cars) if (et in VEHICLE_CATEGORIES and cars) else None
        db.add(Expense(exp_date=rng.choice(days), category=et,
                       amount=Decimal(rng.choice([80, 120, 180, 260, 350, 480, 620, 900, 1500, 2600, 3800, 5200])),
                       note=rng.choice(EXPENSE_NOTES[et]),
                       vehicle_id=car.id if car else None,
                       # 车相关的开销**跟着车走**（挂车的那台车的司机），其余才随机挑一个司机
                       driver_id=(car.driver_id if car else None)
                       if et in VEHICLE_CATEGORIES
                       else (rng.choice(drivers).id if et in ("货损",) else None),
                       operator_id=dispatcher.id))
    db.commit()
    print("  手工流水 18 笔、开销 30 笔")

    # ---------------------------------------------------------- ⑦ 收款单（核销 → 现金流水）
    #
    # ⚠️ 两个必须知道的坑（这条是实测踩出来的）：
    #   · PIECE/COMMISSION 的司机账单 `month` 是**业务函数按"现在"写的**，而我们是把三个月的
    #     订单一次性回放 —— 所以先把账单月份**对齐回那一单的实际送达月**（只改日期，不动金额）。
    #     不补这一步，无论哪个月的单，账单全挤在当月，月度结算/报表根本测不了。
    #   · 收款必须走 `create_receipt`（不是直接写 `orders.paid`）：逐单核销会**逐单**生成
    #     现金流水，直接改 paid 就变成"钱收了、账上没有"。
    # ⚠️ 下面这四句是**同一件事**：`complete_delivery` 那一串业务函数写的都是"此刻"（线上就该这样），
    #    而我们是在一次性回放三个月的历史 —— 凡是**日期取自送达时刻**的行，都要按那一单的实际
    #    送达时间重设回去，否则它们全部挤在今天那一个月，报表与日期筛选直接测不了。
    #
    #    这份清单**不是手写的**：`_tools/seed/_verify_demo_data.py` 会自己算出所有带 `order_id`
    #    的表，凡是没被这里对齐、也没写书面理由的，验收时就红。第一版只对齐了 `source='ORDER'`
    #    的账本行，于是 6 条货损红冲账本 + 6 条货损开销 + 6 条货损现金流水 + 70 条库存流水
    #    全留在"今天"（真机上账本第一屏就是 6 条 09-20 的红冲行、库存流水按月份查是空的）。
    #    ⛔ **一个字都不许用 `date(时间戳)`**：库里存的是 UTC，北京 06:30 的单存进去是
    #       **前一天 22:30**，`date()` 取出来就是前一天 —— 那批凌晨单的账本/账单会整批挪走
    #       （用户 2026-09-21 点名要防的坑，验收脚本里也钉了一条判据）。
    #       业务日 = UTC + 8 小时再取日期（`core/business_time.business_date` 的定义），
    #       两种库写法不同，所以走 `biz_day_sql`。
    #
    # ⚠️ **每一条都带一个"子查询确实算得出值"的门**（`order_id` 指向的订单还在、且它两个日期
    #    列至少有一个非空）。理由：`order_id` 可能指向一张**已经不在了**的订单（软删清理、
    #    或上一轮 `--reset` 只清掉了一部分），那时相关子查询回 NULL；往 NOT NULL 列写 NULL 就是
    #    `IntegrityError (1048, "Column 'month' cannot be null")` —— 整条命令死在半路
    #    （2026-09-21 MySQL 彩排实测）。孤儿行本来就不属于这份数据，也不该被"对齐"。
    dialect = db.get_bind().dialect.name
    order_day = biz_day_sql("coalesce(o.delivered_at, o.order_date)", dialect)

    def alignable(table: str) -> str:
        """`where` 的那一段：这一行确实挂着一张算得出业务日的订单。"""
        return (f"order_id is not null and exists (select 1 from orders o "
                f"where o.id = {table}.order_id "
                f"and coalesce(o.delivered_at, o.order_date) is not null)")

    db.execute(text(f"""
        update driver_bills set month = (
            select substr({order_day}, 1, 7) from orders o where o.id = driver_bills.order_id
        ) where {alignable('driver_bills')}
    """))
    # 账本：订单来源（ORDER）与货损红冲（REFUND）都取那一单的业务日。
    # 手工记账（MANUAL）没有 `order_id`，本来就不过这一句 —— 它的日子是种子自己铺的。
    db.execute(text(f"""
        update ledgers set entry_date = (
            select {order_day} from orders o where o.id = ledgers.order_id
        ) where {alignable('ledgers')}
    """))
    # 开销：**只动挂在订单上的**（货损开销就是送达那一刻记的）；
    # 另外六类开销（油费/过路费/办公耗材…）与订单无关，保持种子自己铺的日期。
    db.execute(text(f"""
        update expenses set exp_date = (
            select {order_day} from orders o where o.id = expenses.order_id
        ) where {alignable('expenses')}
    """))
    # 现金流水：**只动货损那一类**。收款流水（RECEIPT_*）的日子是**收款日** ——
    # "客户 8 月才结 6 月的账"本来就该晚于送达日，一起改会把这条真实业务改成 6 月收款。
    db.execute(text(f"""
        update cash_flows set flow_date = (
            select {order_day} from orders o where o.id = cash_flows.order_id
        ) where biz_type = 'EXPENSE_LOSS' and {alignable('cash_flows')}
    """))
    # 库存流水：`created_at` 就是它的**业务时间**（`GET /inventory/movements` 正是按它做
    # date_from/date_to 过滤），全留到今天的话"按月份查库存流水"永远是空的。
    # ⚠️ 这一句是**时间戳对时间戳**（不是取日期），所以照抄订单的 UTC 值即可，不做 +8 换算。
    db.execute(text("""
        update inventory_movements set created_at = (
            select coalesce(o.delivered_at, o.created_at) from orders o where o.id = inventory_movements.order_id
        ) where order_id is not null and exists (
            select 1 from orders o where o.id = inventory_movements.order_id
              and coalesce(o.delivered_at, o.created_at) is not null
        )
    """))
    db.commit()

    from app.models.enums import ReceiptSettleMode  # noqa: E402
    from app.schemas.accounting_v2 import ShipperReceiptCreate  # noqa: E402
    from app.services.accounting_service import create_receipt, resolve_customer_for_order  # noqa: E402

    # ⚠️ 客户档案（`customers`）是**业务自己按需建的**（`resolve_customer_for_order`）——
    #    送达时只有"有货损"那条支路会建它，所以这里得先按同一入口补齐，
    #    否则收款单没有 `customer_id` 可挂（第一轮就是在这里空的）。
    delivered = (db.query(Order)
                 # ⚠️ `paid` 可能是 NULL（老行/未收款），`== False` 在 SQL 里匹配不到 NULL ——
                 #    写成 `paid.isnot(True)` 才把"没收过款的"都捞上来（第一轮就是这里空的）
                 .filter(Order.status == OrderStatus.DELIVERED, Order.paid.isnot(True))
                 .order_by(Order.delivered_at).all())
    by_shipper: dict[int, list[Order]] = {}
    for o in delivered:
        if o.shipper_id:
            by_shipper.setdefault(o.shipper_id, []).append(o)
    for sid, _orders in by_shipper.items():
        try:
            resolve_customer_for_order(db, _orders[0])
        except Exception as e:  # noqa: BLE001
            print(f"    （一位货主的客户档案没建成：{e}）")
    db.commit()

    n_receipt = 0
    for sid, orders in list(by_shipper.items()):
        if n_receipt >= 8:
            break
        picked = orders[: rng.randint(1, min(4, len(orders)))]
        amount = sum((op.line_total for o in picked for op in o.order_products), Decimal("0"))
        if amount <= 0:
            continue
        cust = resolve_customer_for_order(db, picked[0])
        if cust is None:
            continue
        try:
            create_receipt(db, ShipperReceiptCreate(
                customer_id=cust.id, amount=amount,
                method=rng.choice(["cash", "transfer", "wechat"]),
                # ⚠️ `received_at` 是**业务日**，而 `delivered_at` 现在是 UTC 时间戳 ——
                #    直接 `.date()` 会把凌晨送达的那批收款挪到前一天（`business_date` 才是口径）。
                received_at=(business_date(picked[-1].delivered_at)
                             if picked[-1].delivered_at else wall_now().date()),
                order_ids=[o.id for o in picked], settle_mode=ReceiptSettleMode.ITEMIZED,
                note=rng.choice(["现场结清", "微信转账", "月结第一笔", "老板亲自来结"]),
            ), operator_id=dispatcher.id)
            n_receipt += 1
        except Exception as e:  # noqa: BLE001
            print(f"    （一位客户的收款跳过：{e}）")
    rolling = [s for s, _ in by_shipper.items()][:4]
    for sid in rolling:                       # 滚动收款：不绑订单，钱只在收款记录里
        cust = resolve_customer_for_order(db, by_shipper[sid][0])
        if cust is None:
            continue
        try:
            create_receipt(db, ShipperReceiptCreate(
                customer_id=cust.id, amount=Decimal(rng.choice([500, 800, 1200, 2000, 3000])),
                method=rng.choice(["cash", "transfer"]),
                received_at=rng.choice(days), order_ids=[],
                settle_mode=ReceiptSettleMode.ROLLING, note="先付一笔，月底再对",
            ), operator_id=dispatcher.id)
            n_receipt += 1
        except Exception as e:  # noqa: BLE001
            print(f"    （滚动收款跳过：{e}）")
    db.commit()
    print(f"  收款单 {n_receipt} 张（含逐单核销与滚动收款）")

    # ---------------------------------------------------------- ⑦b 退货（整单 / 部分）
    #
    # 2026-09-20 加的两件事（退货、按商品核销）**必须在这份演示数据里出现过**：
    # 演示数据是用来验收的（用户原话「这次我们用来测试的数据很重要」），
    # 数据里没有一条退货，就等于「已退货」那一档、账本红冲、库存回补、退现这四样
    # 在真机上永远看不到，而它们恰恰是最容易悄悄坏掉的。
    #
    # 走**真实业务函数** `return_order`（与端点同一个入口），所以账本/库存/现金流水
    # 都是业务代码自己写的 —— 造数脚本不直接写这几张表。
    from app.services.order_return import ReturnItem, return_order  # noqa: E402

    n_return = 0
    # 挑几单**已送达且没被整单核销**的（收款那一步已经标走了 `paid=True` 的那批），
    # 退货要覆盖两种：① 整单退完（→ 状态变「已退货」）② 只退其中几件（→ 留在已送达）
    cand = [o for o in delivered if not o.paid and o.order_products]
    for o, mode in zip(cand[:4], ("full", "part", "part", "full")):
        try:
            lines = [op for op in o.order_products if (op.quantity or 0) > 0]
            if not lines:
                continue
            if mode == "full":
                items = [ReturnItem(order_product_id=op.id, quantity=op.quantity) for op in lines]
            else:
                op = lines[0]
                qty = max(1, (op.quantity or 1) // 2)
                if qty >= op.quantity:
                    continue
                items = [ReturnItem(order_product_id=op.id, quantity=qty)]
            return_order(db, o, items, note=rng.choice(["客户说不要了", "送错规格", "货不对版"]),
                         operator_id=dispatcher.id)
            n_return += 1
        except Exception as e:  # noqa: BLE001
            db.rollback()
            print(f"    （一单退货跳过：{e}）")
    db.commit()
    print(f"  退货 {n_return} 单（整单退 → 已退货；部分退 → 留在已送达）")

    # ---------------------------------------------------------- ⑧ 司机结算单（按月，草稿）
    n_set = 0
    for back in (0, 1, 2):
        first = today.replace(day=1)
        for _ in range(back):
            first = (first - timedelta(days=1)).replace(day=1)
        month = first.strftime("%Y-%m")
        for drv in drivers:
            bills = db.query(DriverBill).filter(DriverBill.driver_id == drv.id,
                                                DriverBill.month == month,
                                                DriverBill.status == DriverBillStatus.OPEN).all()
            if not bills:
                continue
            db.add(DriverSettlement(driver_id=drv.id,
                                    settle_type=DriverBillType.SALARY if drv.billing_mode == "SALARY"
                                    else DriverBillType.PIECE,
                                    month=month, period_from=first,
                                    period_to=first.replace(day=28),
                                    amount=sum((b.amount for b in bills), Decimal("0")),
                                    status=SettlementStatus.DRAFT,
                                    order_ids=[b.order_id for b in bills if b.order_id],
                                    operator_id=dispatcher.id, note="按月结算"))
            n_set += 1
    db.commit()
    print(f"  司机结算单 {n_set} 张（草稿）")

    # ---------------------------------------------------------- ⑨ 消息中心
    #
    # 为什么必须造：**消息中心是工作台上的一个模块**，而这份数据要"什么地方都不空"
    # （用户 2026-09-20：「希望不要什么地方空掉了」）。第一版一条消息都没有。
    #
    # 走**真实的 `publish_*`**（`services/message_center.py`），不在这里 `db.add(Notification(...))`：
    # 标题/正文/分类/`speech_important`/payload 的形状只有那一份实现，在脚本里再抄一遍，
    # 改文案时就一定与线上走散（抄的这一份没人会想起来改）。
    # 脚本里没有 Socket.IO 服务，所以只把"往外推"的那一个入口换成空实现 —— 落库那半是原样代码。
    from app.models.notification import Notification  # noqa: E402
    from app.services import message_center as mc  # noqa: E402

    async def _no_push(*_a, **_kw) -> None:
        return None

    mc.emit_to_user = _no_push          # type: ignore[assignment]
    mc.emit_unread_count = _no_push     # type: ignore[assignment]

    def publish(fn, when, *fn_args) -> int:
        """跑一条真实发布函数，再把刚写下的那几行的时间改回**它播报的那件事**发生的时刻。

        `publish_*` 自己不写时间（`TimestampMixin` 默认填"此刻"），而我们在回放历史 ——
        消息列表就是按时间排的，"派单消息显示今天、单子是六月的"是自相矛盾的。

        ⚠️ `when` 传进来的是**订单上那一列的原值**（`o.created_at` / `o.delivered_at` …），
        它们已经是**库里那种 UTC naive**（订单写库时过过 `to_utc_naive`），所以这里**不再换算** ——
        再减 8 小时就是双重换算，消息会比单子早 8 小时。
        """
        before = db.scalar(select(func.max(Notification.id))) or 0
        asyncio.run(fn(db, *fn_args))
        rows = db.execute(select(Notification.id).where(Notification.id > before)).all()
        if rows:
            db.execute(update(Notification).where(Notification.id.in_([r[0] for r in rows]))
                       .values(created_at=when, updated_at=when))
            db.commit()
        return len(rows)

    # 只播**最近 30 天**的单：消息保留期就是 30 天（`data_retention.NOTIFICATION_RETENTION_DAYS`，
    # 启动时与 `GET /notifications?days=` 都会物理清掉更早的），造三个月只会被清掉一部分，
    # 反而让"消息条数"这件事变得没法解释。
    # ⚠️ 截止点是**库里那种 UTC naive**（`utc_now_naive()`），因为 `created_at` 现在存的就是 UTC ——
    #    拿本机的墙上时间去比会差 8 小时（`business_time` 记着这条老账）。
    recent = (db.query(Order).filter(Order.created_at >= utc_now_naive() - timedelta(days=30))
              .order_by(Order.created_at).all())
    n_msg = 0
    for o in recent:
        n_msg += publish(mc.publish_new_order_to_dispatchers, o.created_at, o.id)
        if o.driver_id is None:
            continue
        n_msg += publish(mc.publish_order_assigned, o.dispatched_at or o.created_at, o.id)
        if o.driver_acknowledged_at is not None and o.shipper_id:
            n_msg += publish(mc.publish_driver_ack_shipper, o.driver_acknowledged_at,
                             o.shipper_id, o.id)
        if o.status == OrderStatus.DELIVERED and o.delivered_at is not None:
            n_msg += publish(mc.publish_order_delivered, o.delivered_at, o.id)
        elif o.status == OrderStatus.CANCELLED:
            who = [u for u in (o.shipper_id, o.driver_id) if u]
            n_msg += publish(mc.publish_order_cancelled_multi, o.cancelled_at or o.created_at, who, o.id)
    # 已读状态要讲道理：两天前的都读过了，最近两天的留着未读（角标才有数可看）。
    # 用 SQL 一句扫完，而不是逐条 `n.read_at = ...`（几百条逐条写太慢）。
    #
    # ⚠️ 这一句**两种库的写法不同，而两种都要在**：本机开发库是 SQLite、生产是 MySQL。
    #    原来只有 SQLite 那一种写法（`datetime(x, '+1 hour')` / `datetime('now','localtime',…)`），
    #    拿到生产 MySQL 上就是"函数不存在" —— 而它跑在**最后一步**，等于前面几百单
    #    全造完了才炸，最坏的情况是只差这一步却要重来。
    #    MySQL 用 `date_add/date_sub`；"两天前"取 `utc_timestamp()`（`database.py` 已把
    #    MySQL 会话时区钉成 UTC，与库里存 UTC 的口径一致）。SQLite 侧同理：`datetime('now')`
    #    就是 UTC（**不带** `'localtime'` —— 消息现在存的是 UTC，拿本机时间去比会多读 8 小时）。
    if db.get_bind().dialect.name == "mysql":
        db.execute(text("""
            update notifications set read_at = date_add(created_at, interval 1 hour)
            where created_at < date_sub(utc_timestamp(), interval 2 day)
        """))
    else:
        db.execute(text("""
            update notifications set read_at = datetime(created_at, '+1 hour')
            where created_at < datetime('now', '-2 day')
        """))
    db.commit()
    unread = db.scalar(text("select count(*) from notifications where read_at is null"))
    print(f"  消息 {n_msg} 条（最近 30 天，其中未读 {unread} 条）")

    # 分布报告：**从库里读**（那一份才是事实），而不是拿上面的计划再打一遍 ——
    # 两者不一致就说明写库这一步出了事，报告必须能暴露它。
    distribution_report(counts_from_db(db, days), days, "实际写入库里的数据", profile)

    print(f"\n✅ 造数完成（耗时 {(wall_now() - t0).total_seconds():.1f} 秒）。建议接着看：")
    print("   真机「工作台 → 订单账 / 司机账 / 货主账 / 报表中心」，几个数应当互相对得上")
    return 0


if __name__ == "__main__":
    sys.exit(main())
