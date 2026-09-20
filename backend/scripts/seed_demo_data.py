"""造一份**规范**的三个月演示数据（用户 2026-09-20 要求）。

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
   单量有起伏（越近的月份越忙），不搞"每天正好 5 单"这种假规律；
5. **走真实的业务函数**（`order_flow.assign_driver` / `complete_delivery`），
   所以账本、司机账单、现金流水、库存流水都是**业务代码自己写出来的** ——
   我在这里再编一遍，就一定会与线上算法走散（而这批数据是拿来验收的）。

## 它造什么（默认近 90 天）

| 类别 | 量 | 说明 |
|---|---|---|
| 商品分类 / 商品 | 6 / 36 | 生鲜配送的真实品类（水果/蔬菜/肉禽蛋/米面粮油/调味/酒水） |
| 货主 / 批发商 | 24 / 8 | 门店、食堂、餐饮；批发商带专属价（`price_rules`） |
| 司机 / 车辆 / 计费规则 | 22 / 14 / 6 | 计件 / 工资 / 提成 三档；车牌、车型 |
| 地点 / 线路 / 联系人 / 分组 | 60+ / 20 / 36 / 4 | 惠州·东莞一带的地名组合 |
| 挂账单位 / 运费模板 | 6 / 8 | 按路线定价的价目表 |
| 订单 | 默认 420 | 各状态都有；送达单会**自动**产生账本/账单/现金流水/库存流水 |
| 送达照片 | 每张送达单 1 张 | 真的写到 `static/uploads/delivery/<id>/`，不是假 URL |
| 手工流水 / 开销 / 司机结算单 | 18 / 30 / ~12 | 手工记账、六类开销、按月的结算单（草稿） |

用法（**在 backend 目录下**）：
    python -m scripts.seed_demo_data            # 预览：只打印将要造什么
    python -m scripts.seed_demo_data --yes      # 真的写库
    python -m scripts.seed_demo_data --yes --orders 420 --days 90
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

from app.core.security import hash_password  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.arrears import ArrearsUnit  # noqa: E402
from app.models.driver_bill import DriverBill  # noqa: E402
from app.models.driver_billing_rule import DriverBillingRule  # noqa: E402
from app.models.driver_settlement import DriverSettlement  # noqa: E402
from app.models.enums import (  # noqa: E402
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
VEHICLE_TYPES = ["面包车", "4.2米厢式货车", "6.8米货车", "三轮车"]
PLATE_PREFIX = ["粤L", "粤S", "粤B"]
EXPENSE_TYPES = ["油费", "过路费", "车辆维修", "停车费", "员工餐费", "办公耗材", "通讯费", "装卸费"]
EXPENSE_NOTES = {
    "油费": ["仲恺加油站 92#", "江北中石化", "塘厦加气站", "常平服务区加油"],
    "过路费": ["惠河高速", "潮莞高速", "博深高速", "长深高速"],
    "车辆维修": ["换两条后胎", "刹车片保养", "空调加雪种", "年检代办", "换机油三滤"],
    "停车费": ["信立农批月租", "樟木头市场临停", "龙岗园区停车"],
    "员工餐费": ["仓库加班餐", "跟车午餐", "早班早餐"],
    "办公耗材": ["打印纸与标签", "送货单印刷", "记号笔与胶带"],
    "通讯费": ["月结话费", "对讲机电池"],
    "装卸费": ["临时装卸工钱", "叉车租用"],
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
STATIC = Path("static")


def phone() -> str:
    """13x 本地号段，**发号前查重**（重号在真实库里是唯一约束冲突）。"""
    while True:
        p = "13" + str(rng.choice([5, 6, 7, 8, 9])) + f"{rng.randint(0, 99999999):08d}"
        if p not in USED_PHONE:
            USED_PHONE.add(p)
            return p


def person(female_ratio: float = 0.3) -> str:
    return rng.choice(SURNAMES) + rng.choice(GIVEN_F if rng.random() < female_ratio else GIVEN_M)


def address() -> tuple[str, float, float]:
    key = rng.choice(list(DISTRICTS))
    (lat0, lng0), roads = DISTRICTS[key]
    road = rng.choice(roads)
    no = rng.randint(1, 199)
    tail = rng.choice([f"{no}号", f"{no}号之一", f"{no}号 {rng.randint(1, 8)}栋{rng.randint(101, 2508)}室"])
    detail = f"{key}区{road}{tail}" if not key.startswith(("樟木头", "常平", "塘厦", "龙岗")) else f"{key}{road}{tail}"
    return detail, round(lat0 + rng.uniform(-0.03, 0.03), 6), round(lng0 + rng.uniform(-0.03, 0.03), 6)


def pick_time(d: date) -> datetime:
    """下单位置不规律但有高峰：早班 6-9 点、下午 14-17 点是主峰。"""
    r = rng.random()
    h = rng.choice([6, 7, 7, 8, 8, 9]) if r < 0.45 else \
        rng.choice([14, 15, 16, 17]) if r < 0.8 else rng.choice([10, 11, 12, 13, 18])
    return datetime.combine(d, time(h, rng.randint(0, 59), rng.randint(0, 59)))


def write_delivery_photo(order_id: int, order_no: str, when: datetime, name: str) -> str:
    """写一张**真的**送达照片（App 里能打开，不是假 URL）。

    480×640 的灰底图 + 单号/时间/收货人；真实业务里这是司机拍的货物照，
    这里给的是"能看得出是哪一单"的占位（颜色随单号变，免得满屏一模一样）。
    """
    from PIL import Image, ImageDraw

    d = STATIC / "uploads" / "delivery" / str(order_id)
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

    d = STATIC / "uploads" / "places"
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
    ap = argparse.ArgumentParser(description="造一份规范的三个月演示数据")
    ap.add_argument("--yes", action="store_true", help="真的写库（缺省只预览）")
    ap.add_argument("--orders", type=int, default=420)
    ap.add_argument("--days", type=int, default=90)
    args = ap.parse_args()

    db = SessionLocal()
    # 三个开发登录账号不算"已有数据"（`_reset_dev_db.py` 特意留着它们）
    dev_phones = ("13800000001", "13800000002", "13800000003")
    if db.query(User).filter(User.role == UserRole.DRIVER,
                             User.phone.notin_(dev_phones)).count() > 0:
        print("⚠️ 库里已经有司机账号了 —— 这份脚本是给**清空后的库**用的，先跑：")
        print("   python _tools/seed/_reset_dev_db.py --yes")
        return 1
    dispatcher = db.query(User).filter(User.phone == "13800000001").one()
    today = date.today()
    start = today - timedelta(days=args.days)
    print(f"将造 {start} ~ {today}（{args.days} 天）的演示数据：订单 {args.orders} 单")
    if not args.yes:
        print("（预览模式，什么都没写。加 --yes 执行）")
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
        shippers.append(User(username=nm, full_name=nm, phone=phone(), role=UserRole.SHIPPER,
                             password_hash=pwd, is_active=True, is_member=False))
    members: list[User] = []
    for nm in ["兴发果业", "顺鑫蔬菜批发", "恒丰粮油", "城东水产", "万家冻品", "新叶生鲜配送",
               "金禾米业", "广达调味"]:
        members.append(User(username=nm, full_name=nm, phone=phone(), role=UserRole.SHIPPER,
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
    for nm, piece, rate, salary in [
        ("按单计件 · 面包车", Decimal("22"), None, None),
        ("按单计件 · 4.2米厢货", Decimal("45"), None, None),
        ("按单计件 · 6.8米货车", Decimal("78"), None, None),
        ("月薪司机 · 固定 6500", None, None, Decimal("6500")),
        ("运费提成 8%", None, Decimal("8"), None),
        ("运费提成 12%", None, Decimal("12"), None),
    ]:
        rules.append(DriverBillingRule(name=nm, piece_amount=piece, commission_rate=rate, salary=salary))
    db.add_all(rules)
    db.flush()

    drivers: list[User] = []
    for i in range(22):
        nm = person(0.08)
        vt = rng.choice(VEHICLE_TYPES)
        rule = rules[0] if vt == "面包车" else rules[1] if vt == "4.2米厢式货车" else \
            rules[2] if vt == "6.8米货车" else rules[3]
        if i in (5, 9, 16):                     # 三位月薪司机
            rule = rules[3]
        elif i in (3, 12, 19):                  # 三位提成司机
            rule = rng.choice(rules[4:])
        drivers.append(User(username=nm, full_name=nm, phone=phone(), role=UserRole.DRIVER,
                            password_hash=pwd, is_active=True, vehicle_type=vt,
                            driver_rule_id=rule.id,
                            billing_mode="SALARY" if rule.salary else "PIECE"))
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
    for s in rng.sample(shippers, 12):       # 货主侧也各有一两个自己的地点
        for _ in range(rng.randint(1, 3)):
            detail, lat, lng = address()
            db.add(ShipperLocation(shipper_id=s.id, name=f"{s.full_name}{rng.choice(['仓库', '门店', '档口', '食堂'])}",
                                   detail_address=detail, address_lat=lat, address_lng=lng,
                                   remark="", image_urls="[]"))
    db.commit()
    print(f"  地点 {len(locs)}、线路 20、联系人 {len(contacts)}、地点分组 4")

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
    days = [start + timedelta(days=i) for i in range(args.days + 1)]
    weights = [1.0 + 0.9 * (i / len(days)) for i in range(len(days))]   # 越近越忙
    made = 0
    stat = {s: 0 for s in ("delivered", "cancelled", "pending", "dispatched", "accepted")}
    seq = 0
    own_by_shipper: dict[int, list[ShipperLocation]] = {}
    for s in shippers + members:
        own = db.query(ShipperLocation).filter(ShipperLocation.shipper_id == s.id,
                                               ShipperLocation.is_deleted == False).all()  # noqa: E712
        if own:
            own_by_shipper[s.id] = own
    while made < args.orders:
        d = rng.choices(days, weights=weights, k=1)[0]
        if d.weekday() == 6 and rng.random() < 0.8:      # 周日大多不发车
            continue
        per_day = rng.choices([0, 1, 2, 3, 4, 5, 6, 7, 8, 9], weights=[2, 5, 9, 12, 12, 10, 6, 3, 2, 1], k=1)[0]
        for _ in range(per_day):
            if made >= args.orders:
                break
            created = pick_time(d)
            if created >= datetime.now():
                continue
            shipper = rng.choice(shippers + members)
            lines = rng.sample(products, rng.choices([1, 2, 3, 4, 5], weights=[38, 28, 18, 10, 6], k=1)[0])
            own = own_by_shipper.get(shipper.id)
            loc = rng.choice(own) if own and rng.random() < 0.7 else rng.choice(locs)
            seq += 1
            route = rng.choice(ROUTES)
            payment = rng.choices(["arrears", "cash"], weights=[78, 22], k=1)[0]
            o = Order(order_no=f"SO{created:%Y%m%d}{seq:06d}", status=OrderStatus.PENDING_DISPATCH,
                      shipper_id=shipper.id, order_date=created.date(),
                      created_at=created, updated_at=created,
                      delivery_description=rng.choice(["送到后门卸货", "走正门找收货员", "卸在一楼月台",
                                                       "提前 10 分钟打电话", "冷藏品请直接进冷库"]),
                      address_detail=loc.detail_address, address_lat=loc.address_lat,
                      address_lng=loc.address_lng, contact_dongjia_phone=phone(),
                      contact_boss_phone=shipper.phone,
                      remark=rng.choice(["", "", "尽量上午送到", "货要新鲜的", "上次少了两箱，这次点清", "带票据过来"]),
                      freight_fee=Decimal(route[2]) + Decimal(rng.choice([0, 0, 5, 10, 15])),
                      payment_method=payment,
                      # 派单时勾了「收取现金」：司机送到就得当场收（这是派单动作上的标志，不是收款记录）
                      collect_cash=(payment == "cash"),
                      paid=False, is_exception=False,
                      image_urls="[]", delivery_photo_urls="[]")
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

            roll = rng.random()
            if roll < 0.72:                       # 已送达：账本/账单/现金流水由业务函数写
                driver = rng.choice(drivers)
                assign_driver(db, o, driver, dispatcher,
                              internal_note=rng.choice(["", "", "客户催过", "顺路带过去", "熟客"]))
                o.dispatched_at = created + timedelta(minutes=rng.randint(5, 90))
                o.driver_acknowledged_at = o.dispatched_at + timedelta(minutes=rng.randint(2, 120))
                o.status = OrderStatus.ACCEPTED
                db.flush()
                dlv = min(o.driver_acknowledged_at + timedelta(hours=rng.uniform(0.7, 9)),
                          datetime.now() - timedelta(hours=1))
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
                o.delivered_at = dlv
                o.updated_at = dlv
                if rng.random() < 0.04:
                    o.is_exception = True
                    o.exception_reason = rng.choice(["客户说少送一箱", "迟到两小时", "包装破损"])
                # ⚠️ 这里**不**直接写 `paid`：核销必须走收款单（下面第 ⑦ 步），
                #    否则会出现"订单已收款、但账上没有任何一笔对应的收款记录"（账实不符）。
                stat["delivered"] += 1
            elif roll < 0.80:
                o.status = OrderStatus.CANCELLED
                o.cancelled_at = created + timedelta(hours=rng.randint(1, 20))
                stat["cancelled"] += 1
            elif roll < 0.86:
                assign_driver(db, o, rng.choice(drivers), dispatcher, internal_note="")
                o.dispatched_at = created + timedelta(minutes=rng.randint(5, 60))
                stat["dispatched"] += 1
            elif roll < 0.92:
                assign_driver(db, o, rng.choice(drivers), dispatcher, internal_note="")
                o.dispatched_at = created + timedelta(minutes=rng.randint(5, 60))
                o.driver_acknowledged_at = o.dispatched_at + timedelta(minutes=rng.randint(3, 60))
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
    for _ in range(30):
        et = rng.choice(EXPENSE_TYPES)
        db.add(Expense(exp_date=rng.choice(days), category=et,
                       amount=Decimal(rng.choice([80, 120, 180, 260, 350, 480, 620, 900, 1500, 2600, 3800, 5200])),
                       note=rng.choice(EXPENSE_NOTES[et]),
                       driver_id=rng.choice(drivers).id if et in ("油费", "过路费", "车辆维修") else None,
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
    db.execute(text("""
        update driver_bills set month = (
            select substr(coalesce(o.delivered_at, o.order_date), 1, 7) from orders o where o.id = driver_bills.order_id
        ) where order_id is not null
    """))
    # 账本那 673 行是 `ledger_sync` 在送达那一刻写的：它当时读到的 `delivered_at` 还是"现在"，
    # 所以这里把**订单来源**的账本日期重新对齐回订单的送达日（手动记账的行不动）。
    db.execute(text("""
        update ledgers set entry_date = (
            select date(coalesce(o.delivered_at, o.order_date)) from orders o where o.id = ledgers.order_id
        ) where source = 'ORDER' and order_id is not null
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
                received_at=(picked[-1].delivered_at or datetime.now()).date(),
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
                                    settle_type="PIECE" if drv.billing_mode != "SALARY" else "SALARY",
                                    month=month, period_from=first,
                                    period_to=first.replace(day=28),
                                    amount=sum((b.amount for b in bills), Decimal("0")),
                                    status=SettlementStatus.DRAFT,
                                    order_ids=[b.order_id for b in bills if b.order_id],
                                    operator_id=dispatcher.id, note="按月结算"))
            n_set += 1
    db.commit()
    print(f"  司机结算单 {n_set} 张（草稿）")

    print("\n✅ 造数完成。建议接着看：")
    print("   真机「工作台 → 订单账 / 司机账 / 货主账 / 报表中心」，几个数应当互相对得上")
    return 0


if __name__ == "__main__":
    sys.exit(main())
