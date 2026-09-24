"""红线：**列表排序规则**（用户 2026-09-22 定的）不许走样。

## 规则（用户原话摘录）
> 我们那个**隐性规则**，它是**优先级第一**的，它的规则是**大于基础排序**的……
> **技术是按人来搞**……看请求吧，他请求要拉哪个列表……**所有的列表，包括列表的抓取
> 以及列表的排序**，全按照我们这样的规则进行。

于是：**挑东西的列表** = ① 常用度降序（按人，`usage_counters`）→ ② 先创建的在前（`id` 升序）。
⛔ **看记录的列表**（订单/账本/消息/审计/流水/账单/结算）**不适用** —— 那些必须最新在前，
否则翻账要往下翻几万行。

## 这一页在防什么（每一条都对应一种"静默失效"）
1. **记了但没人按它排** → `kind` 定义了、列表却没接：界面上一切照常，只是永远不往前；
2. **各写一份排序** → 有的带 `coalesce`、有的不带（漏了的那些，"没用过的行"因为 NULL 沉到最后，
   与"先创建的在前"正好相反，看起来只是"顺序有点怪"）；
3. **顺手给订单也套上** → 订单列表突然不再最新在前（灾难级，但改的人当时看不出）；
4. **计数改成读改写** → 两部手机同时点会丢一次（2026-09-19 审计与库存同一个形状）；
5. **App 不带 id** → 真机上下单**一次都不计分**（后端接口是可选字段，所以不报错）。

用法：python _tools/qa/_check_list_order.py
配套：python _tools/qa/_reverse_verify_list_order.py（9 种破坏方式全被抓）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_hints import Checker, read, strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "backend" / "app" / "api" / "v1"
SVC = ROOT / "backend" / "app" / "services" / "usage_service.py"
MODEL = ROOT / "backend" / "app" / "models" / "usage.py"
BOOT = ROOT / "backend" / "app" / "core" / "schema_bootstrap.py"
ORDER_SCHEMA = ROOT / "backend" / "app" / "schemas" / "order.py"
USAGE_API = ROOT / "backend" / "app" / "api" / "v1" / "usage.py"
BASIC_SETTINGS = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders" / "ui" / "profile" / "BasicSettingsScreen.kt"
WRITE_COVERAGE = ROOT / "_tools" / "ai" / "_write_coverage.py"
ANDROID = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"
DTS = ANDROID / "data" / "remote" / "dto" / "Dtos.kt"
ORDER_VM = ANDROID / "ui" / "shipper" / "OrderCreateViewModel.kt"

# ── 挑东西的列表：**每个 kind 必须有一个列表接上它**（表里的键必须与 usage_service 的常量集合一致）──
# 每条都写清"是哪一页的哪个列表"；锚点是那一行真实调用（改了要连这条一起改）。
PICK_LISTS: dict[str, tuple[str, str, str]] = {
    "KIND_CONTACT": ("shipper.py", "with_popularity(stmt, ShipperContact, usage_service.KIND_CONTACT, current)",
                     "常用联系人"),
    "KIND_ADDRESS": ("shipper.py", "with_popularity(stmt, ShipperAddress, usage_service.KIND_ADDRESS, current)",
                     "常用线路（默认线路仍在最前）"),
    "KIND_LOCATION": ("shipper.py", "with_popularity(stmt, ShipperLocation, usage_service.KIND_LOCATION, current)",
                      "我的地点"),
    "KIND_PLACE": ("places.py", "with_popularity(stmt, Place, usage_service.KIND_PLACE, current)",
                   "共享地点库（按**我自己**用过的次数，不是全库次数）"),
    "KIND_PRODUCT": ("products.py", "with_popularity(q, Product, usage_service.KIND_PRODUCT, current)",
                     "商品（手工置顶/拖动仍在更前面）"),
    "KIND_USER": ("users.py", "with_popularity(", "货主 / 批发商 / 司机"),
    "KIND_CUSTOMER": ("customers.py", "with_popularity(", "客户"),
    "KIND_ARREARS_UNIT": ("arrears.py", "with_popularity(", "挂靠单位"),
    "KIND_VEHICLE": ("vehicles.py", "with_popularity(", "车辆"),
    "KIND_FREIGHT_TEMPLATE": ("freight_templates.py", "with_popularity(", "运费模板"),
    "KIND_BILLING_RULE": ("driver_billing_rules.py", "with_popularity(", "司机计费规则"),
    "KIND_PRICE_RULE": ("price_rules.py", "with_popularity(", "批发商专属价"),
    # 预订单（2026-09-22）：用过哪张预设单下单，它就往前排（`POST /order-templates/{id}/use` 记的）。
    "KIND_ORDER_TEMPLATE": ("order_templates.py", "with_popularity(", "预设单"),
    # 供应商 / 厂商（2026-09-22）：**记账时最常打交道的那几个**排前面 ——
    # 记账点有三处（建/改应付单、付款、翻他的账），都调 `_touch`（同一个 kind，⛔ 不许分叉）。
    "KIND_SUPPLIER": ("suppliers.py", "with_popularity(", "供应商 / 厂商（账本管理 → 供应商/应付）"),
}

# ── 看记录的列表：**必须最新在前**，⛔ 不许套用常用度（每条写清为什么）──
RECORD_LISTS: list[tuple[str, str]] = [
    ("orders_query.py", "订单：最新的单在最上面（派单员一进来要看到刚下的单）"),
    ("ledger.py", "账本流水：按发生时间倒序"),
    ("cash_flows.py", "现金流水：同上"),
    ("notifications.py", "消息：最新的在最上面"),
    ("operation_logs.py", "审计日志：最新的在最上面"),
    ("inventory.py", "库存流水：最新的在最上面"),
    ("driver_bills.py", "司机账单：按月倒序"),
    ("driver_settlements.py", "结算单：按月倒序"),
    ("return_requests.py", "退货申请：最新的在最上面"),
    ("shipper_ledger.py", "货主核销：最新的在最上面"),
]


def strip_py_comments(src: str) -> str:
    """剥掉 Python 的 `#` 注释（**保留字符串字面量**）。

    ⚠️ 为什么不用 `_check_hints.strip_comments`：那个是给 **Kotlin** 写的（`//` 与 `/* */`），
    对 `.py` 里的 `#` 视而不见 —— 于是"注释里提到 `with_popularity`"会被当成真的用了它
    （2026-09-22 实测：orders.py 的注释里提了一句就把这条判据弄红了）。
    """
    out = []
    for line in src.split("\n"):
        i = line.find("#")
        if i >= 0:
            # 行内 `#` 前面若有引号，简单起见保留整行（宁可少剥，也不要切坏字符串）
            if line.count('"') % 2 or line.count("'") % 2:
                out.append(line)
                continue
            line = line[:i]
        out.append(line)
    return "\n".join(out)


def main() -> int:
    c = Checker()

    c.section("0. 反空转（文件搬走/被清空时先喊）")
    for p in (SVC, MODEL, BOOT, ORDER_SCHEMA, DTS, ORDER_VM):
        c.ok(f"{p.name} 在", p.exists())
    if c.fails:
        print("\n❌ 关键文件不在，后面的判据没有意义")
        return 1
    svc = strip_py_comments(read(SVC))
    model = read(MODEL)
    boot = read(BOOT)
    order_schema = read(ORDER_SCHEMA)
    dts = read(DTS)
    vm = read(ORDER_VM)
    api_files = {p.name: strip_py_comments(read(p)) for p in API.glob("*.py")}

    c.section("1. kind 常量与「挑东西的列表」一一对上（记了必须有人按它排）")
    kinds = set(re.findall(r"^(KIND_[A-Z_]+) = ", svc, re.M))
    c.ok(f"usage_service 里定义了 {len(kinds)} 个 kind（下限 8）", len(kinds) >= 8)
    missing = sorted(k for k in kinds if k not in PICK_LISTS)
    stale = sorted(k for k in PICK_LISTS if k not in kinds)
    c.ok("每个 kind 都有一个列表接上它（新增 kind 必须同时登记它排哪个列表）", not missing,
         f"没人用的 kind：{missing}")
    c.ok("登记表里没有已经删掉的 kind（防化石）", not stale, f"表里多余的：{stale}")
    for kind, (fname, anchor, why) in PICK_LISTS.items():
        c.ok(f"{fname} 的「{why}」走了共用排序入口", anchor in api_files.get(fname, ""),
             f"锚点：{anchor}")

    c.section("2. 看记录的列表**不许**套用常用度（最新在前是硬要求）")
    for fname, why in RECORD_LISTS:
        src = api_files.get(fname)
        c.ok(f"{fname} 仍然是时间/编号倒序、不套常用度（{why}）",
             src is not None and "with_popularity" not in src and ".desc()" in src)

    c.section("3. 排序只有一份实现（各写一份必然长歪）")
    c.ok("共用的排序入口在 usage_service 里", "def with_popularity(" in svc)
    c.ok("必备 coalesce（漏了会让「没用过的」沉到最后，与「先创建的在前」正好相反）",
         "func.coalesce(uc.use_count, 0).desc()" in svc)
    # ⚠️ 两段必须在**同一行**：只断言 `model.id.asc()` 是不够的 —— 它在"认不出人"的兜底分支里
    #    也出现了一次，于是把**主排序**改成 id 降序时判据照样绿（2026-09-22 反向验证第 ⑤ 条
    #    当场抓出来的洞，这里收紧成"降序 + 升序连在一起"）。
    c.ok("第二键是 id 升序（先创建的在前），且与常用度降序写在同一行",
         "func.coalesce(uc.use_count, 0).desc(), model.id.asc()" in svc)
    bad = [n for n, s in api_files.items() if "order_by(func.coalesce" in s or "order_by(uc." in s]
    c.ok("端点文件里没有自己写的常用度排序（都必须走那一个入口）", not bad, f"自己写了的：{bad}")

    c.section("4. 计数的方式（并发下不许丢）")
    c.ok("计数由数据库自增（`UPDATE … SET use_count = use_count + 1`）",
         "values(use_count=func.coalesce(UsageCounter.use_count, 0) + 1" in svc)
    c.ok("⛔ 没有读改写（`row.use_count = … + 1`）",
         re.search(r"\.use_count\s*=\s*[^=\n]*\+\s*1", svc) is None,
         "读改写会在两部手机同时点时丢一次（2026-09-19 审计，与库存同一个形状）")
    c.ok("按人计数（唯一键 user_id + kind + target_id）",
         'UniqueConstraint("user_id", "kind", "target_id"' in model)
    c.ok("旧表的数据有一次搬迁（不然老用户的常用地点的计数从 0 开始）",
         "place_user_usage" in boot and "INSERT INTO usage_counters" in boot)

    c.section("5. 「真机会计分」这条链不许断（后端收 id、App 传 id）")
    c.ok("后端 OrderCreate 收 contact_id / address_id / location_id（都可选）",
         all(f"{f}: int | None = Field(" in order_schema
             for f in ("contact_id", "address_id", "location_id")))
    c.ok("下单成功时真的记了（联系人/线路/地点/商品/货主）",
         "usage_service.record_usage(db, user=current, kind=kind, target_id=target)" in api_files.get("orders.py", ""))
    c.ok("派单时记了司机（记在**派单员**名下）",
         "kind=usage_service.KIND_USER, target_id=body.driver_id" in api_files.get("orders.py", ""))
    c.ok("App 的请求体带这三个字段", all(f"val {f}Id: Long? = null" in dts
                                        for f in ("contact", "address", "location")))
    c.ok("选了线路/地点时记下 id", "pickedAddressId = a.id" in vm and "pickedLocationId = l.id" in vm)
    c.ok("地图自己选点时**清掉** id（别把上一次的线路记到这一单头上）",
         "pickedAddressId = null\n        pickedLocationId = null" in vm)
    c.ok("下单时把 id 一起提交", "addressId = pickedAddressId" in vm and "locationId = pickedLocationId" in vm)

    c.section("6. 「重置计数」这一格（用户 2026-09-22：「在我的基础设置里加一个重置计数」）")
    basic = read(BASIC_SETTINGS)
    usage_api = strip_py_comments(read(USAGE_API))
    c.ok("「基础设置」里有「重置计数」那一格", 'title = "重置计数"' in basic)
    # ⛔ 这一条最要紧：清了**不还原**（派生统计、不做软删），所以必须在**点之前**说清后果。
    c.ok("点它**先弹确认框**（复用全 App 那一个危险操作弹层）",
         "onClick = { showResetConfirm = true }" in basic and "DangerConfirmDialog(" in basic,
         "直接调 reset ＝ 误碰一下就清光了，而且没法还原")
    c.ok("确认框里说清「只清你自己」＋「没法还原」",
         "只清你自己的，不影响别人" in basic and "没法还原" in basic)
    c.ok("⛔ 后端**只清自己的行**（`user_id == current.id`）",
         "UsageCounter.user_id == current.id" in usage_api,
         "清别人的 ＝ 替所有人把「常用」抹掉，而界面上看不出是谁干的")
    c.ok("⛔ 后端没有「清全表」的写法（delete 必须带 where）",
         "delete(UsageCounter)" in usage_api and "where(UsageCounter.user_id" in usage_api)
    c.ok("结果**如实回执**（清掉几行；0 条也要说）",
         "deleted=int(n)" in usage_api and "container.repo.resetUsage()" in basic)
    c.ok("这个写端点在 `_write_coverage` 有一条「不做 AI 动作」的理由",
         '("POST", "usage/reset")' in read(WRITE_COVERAGE))

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项未通过（通过 {c.n_ok} 项）：")
        for label, _ in c.fails:
            print(f"   - {label}")
        return 1
    print(f"✅ 全部 {c.n_ok} 项通过：挑东西的列表都按「常用度 → 先创建」、看记录的列表都没被套上、"
          f"计数由库自增、真机那条链是通的。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
