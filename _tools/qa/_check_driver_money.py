"""司机端**不显示任何金额**（2026-09-21 用户定案）。

## 规矩
用户原话：「更改司机的配送规则…按固定工资的话他的卡片不显示任何的钱…**干脆以后就这样子搞：所有的司机
都不显示金钱是多少**，但是按单计费或者按提成的话依然会在**我的账单**里显示 —— 也就是说他只有在我的
账单里才能看到这笔订单是多少钱，正常的订单是不会显示的」。

也就是：**司机端订单一律不画钱**（运费 / 工资 / 货款都不画），
钱只出现在「我的账单」（`ui/driver/DriverFreightScreen.kt`，那里算的是**司机应得**，
口径在 `backend/app/services/driver_pay.py` 一处）。

## 为什么这条必须有机器的判据
改之前的口径是「固定工资司机零金额；**按单计费(PIECE)司机显示已定价的运费**」——
它是一个 `if`，谁都能顺手加回来，而且**加回来不报错、不崩、测试也不会有反应**：
界面上只是多出一个 ¥ 数字，而用户明确说过那个数字不该出现（他会以为那是他这一单的工资）。
这类"多显示一个数"的回归本仓库抓过多次（金额渲染两次、司机端货款泄漏），
所以判据要钉在**源码结构**上，能证明"这条分支不在"。

## 判据（每条都能被反向验证弄红，见 `_reverse_verify_driver_money.py`）
1. 订单卡片（`ui/common/OrderCard.kt`）司机分支不出现运费；
2. 订单详情（`ui/order/OrderDetailScreen.kt`）司机分支不出现运费，且详情页里仅剩的运费
   渲染在**派单员**那一块（`role == Role.DISPATCHER`）；
3. 详情页商品行仍不给司机看货款（`role != Role.DRIVER` 那道门没被顺手删掉）；
4. ⚠️ **不能删过头**：`order.freightVisible` 仍被「完成流程」用着（按单计费的司机可以直接完成、
   固定工资的司机要走拍照送达）——把那个 `if` 一起删掉＝改坏了流程；
5. ⚠️ **不能靠"把后端那个数抹成 0"来实现**：后端司机视角门控
   （`order_response.py::apply_driver_view_gating`）必须还在、且仍按**这一单**的模式判；
6. 钱的算法一处都没动：`driver_pay.py::order_pay` 与其消费点仍在；
7. 「我的账单」仍然画钱（防"把司机端所有金额都删了"这种过度执行）；
8. `ui/driver/` 下只有「我的账单」在画钱（清单**自己算**：扫目录，不手写文件名）；
9. 两处都留了"为什么删"的注释与"别加回来"的指路（否则下一轮没人知道这条规矩）。

用法：python _tools/qa/_check_driver_money.py
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
CARD = AND / "ui/common/OrderCard.kt"
DETAIL = AND / "ui/order/OrderDetailScreen.kt"
FREIGHT = AND / "ui/driver/DriverFreightScreen.kt"
PROFILE_SCREEN = AND / "ui/profile/ProfileScreen.kt"
DRIVER_DIR = AND / "ui/driver"
ORDER_RESPONSE = ROOT / "backend/app/services/order_response.py"
DRIVER_PAY = ROOT / "backend/app/services/driver_pay.py"

#: `ui/driver/` 下**允许**画金额的文件（就这一个：我的账单）。
#: ⛔ 不写成"要检查哪些文件"的手写清单 —— 目录自己算，新增文件自动进来。
MONEY_ALLOWED_IN_DRIVER_DIR = {"DriverFreightScreen.kt"}

#: 这一批文件至少要有这么多（防"目录被搬走 → 一个都没扫到 → 全绿"）。
MIN_DRIVER_FILES = 3


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print(f"  [OK]   {label}")
        else:
            self.fails.append(label + (f" —— {detail}" if detail else ""))
            print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))

    def absent(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is None, f"命中：{m.group(0)!r}" if m else "")

    def present(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is not None, f"没找到 {pattern!r}")


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（被改名/搬走了？这条判据要跟着改）")
    return p.read_text(encoding="utf-8")


def main() -> int:
    c = Checker()
    card = read(CARD)
    detail = read(DETAIL)
    freight = read(FREIGHT)

    print("== 1. 订单卡片：司机那一支不画钱 ==")
    # 这一条就是用户看到的那张卡。删掉之后卡片上没有任何金额键。
    c.absent("卡片里不再读 `order.freightFee`（司机运费那一档已删）", card, r"order\.freightFee")
    c.absent("卡片里不再按 `freightVisible` 决定画钱", card, r"freightVisible")
    c.present("非司机那一支仍在画「合计」（司机端只是不画，不是把金额功能删了）",
              card, r"if \(!driverMode\) \{\s*\n\s*Text\(\s*\n\s*\"¥\" \+ formatMoney\(total")
    c.present("留了『为什么删』的注释（下一轮才看得见这条规矩）",
              card, r"司机端订单卡片\*\*一律不画金额\*\*")
    # 光有"为什么"不够：还得**指路到判据脚本**。上一版只有前半句，
    # 于是把 ⛔ 那行删掉照样全绿（反向验证当场抓到的 MISS）——说明这条注释当时没人守着。
    c.present("注释里点了判据脚本的名字（『别加回来』要指路，否则没人找得到这条检查）",
              card, r"⛔ 别在这里\"顺手加回来\"：判据在 `_tools/qa/_check_driver_money\.py`")
    # 判据的兜底：这张卡至少还在画"件数/时间"，别为了删金额把整行删空
    # ⚠️ 2026-09-22 起「合计」那一行的单位不再是写死的「件」：全单同一个单位时写真单位
    #    （「共 6 桶」），混装才退回口语的「件」—— 见 `Units.kt::sharedUnitOf`。
    #    所以锚点从字面量 `" 件 · "` 改成「单位来自 sharedUnitOf + 紧接着是 · 时间」，
    #    **意图一字不改**：这一行还在、且它后面没有钱（钱那一支仍是 `if (!driverMode)`）。
    c.present("卡片仍然画件数与时间（那一行没被整行删掉）",
              card,
              r"sharedUnitOf\(order\.orderProducts\.map \{ it\.unit \}\)"
              r"[\s\S]{0,160}?\" · \" \+ formatDateTime\(order\.createdAt\)")

    print("\n== 2. 订单详情：司机那一支不画钱，剩下的运费只在派单员那一块 ==")
    c.absent("详情页不再按 `driverBillingMode == \"PIECE\"` 给司机显示运费",
             detail, r"driverBillingMode == \"PIECE\" && order\.freightVisible")
    c.present("详情页的资金总额那一行是 `role != Role.DRIVER` 才画",
              detail,
              r"司机端详情页\*\*一律不画金额\*\*[\s\S]{0,400}?if \(role != Role\.DRIVER\) \{\s*\n\s*Row\(")
    # 详情页里**仅剩**的运费渲染必须落在派单员的收款块之后（块外＝司机可能看到）
    disp = detail.find("if (role == Role.DISPATCHER) {")
    fees = [m.start() for m in re.finditer(r"order\.freightFee", detail)]
    c.ok(
        f"详情页里仅剩的 {len(fees)} 处 `order.freightFee` 全在派单员收款块内",
        disp >= 0 and bool(fees) and all(i > disp for i in fees),
        f"派单员块起点={disp}，运费用法={fees}",
    )
    c.present("派单员那一块仍然显示司机运费（司机端不画 ≠ 派单员也不画）",
              detail, r"if \(order\.freightFee != null\) \"¥\" \+ formatMoney\(order\.freightFee\)")
    c.present("详情页也留了『别加回来』的指路",
              detail, r"⛔ 别加回来：判据 `_tools/qa/_check_driver_money\.py`")

    print("\n== 3. 详情页商品行：司机仍然看不到货款 ==")
    c.present("商品行的小计有 `role != Role.DRIVER` 这道门",
              detail,
              r"if \(role != Role\.DRIVER\) \{\s*\n\s*Text\(\s*\n\s*\"¥\" \+ formatMoney\(line\.lineTotal\)")

    print("\n== 4. 别删过头：完成流程那两档还在（按单计费可直接完成 / 固定工资走拍照）==")
    c.present("`order.freightVisible` 仍被完成流程用着", detail, r"if \(order\.freightVisible\) \{")
    c.present("收现金 / 挂账 两个按钮还在（挂车直结那条路）", detail, r"Text\(\"收取现金\", style")

    print("\n== 5. 后端门控还在，且仍按『这一单』的模式判（不是靠把数抹成 0）==")
    orsp = read(ORDER_RESPONSE)
    c.present("司机视角门控仍在", orsp, r"def apply_driver_view_gating\(")
    c.present("门控判据是这一单的模式（`has_per_order_pay(order)`）",
              orsp, r"per_order = has_per_order_pay\(order\)")
    c.present("不按单的单把运费置 None（**不发**下去，而不是发 0）", orsp, r"data\[\"freight_fee\"\] = None")

    print("\n== 6. 钱的算法一处都没动 ==")
    dpay = read(DRIVER_PAY)
    c.present("`driver_pay.order_pay` 仍在（司机应得只有这一处实现）", dpay, r"def order_pay\(")
    c.present("`has_per_order_pay` 仍在（账单怎么算与界面显示同一口径）", dpay, r"def has_per_order_pay\(")

    print("\n== 7. 「我的账单」仍然画钱（防过度执行）==")
    c.present("我的账单显示司机应得合计", freight, r"\"¥\" \+ formatMoney\(vm\.total\(\)\.toString\(\)\)")
    c.present("我的账单逐单显示司机应得", freight, r"\"¥\" \+ formatMoney\(e\.payTotal\)")

    print("\n== 8. 司机端只有「我的账单」在画钱（清单自己算）==")
    files = sorted(DRIVER_DIR.glob("*.kt"))
    money_files = {f.name for f in files if "formatMoney(" in read(f)}
    c.ok(f"`ui/driver/` 下画金额的文件只有 {sorted(MONEY_ALLOWED_IN_DRIVER_DIR)}",
         money_files == MONEY_ALLOWED_IN_DRIVER_DIR, f"实际：{sorted(money_files)}")
    c.ok(f"`ui/driver/` 扫到 {len(files)} 个文件（≥{MIN_DRIVER_FILES}，防目录被搬走时空转）",
         len(files) >= MIN_DRIVER_FILES, f"实际 {len(files)}")

    # ============================================================ 9. 「我的账单」入口
    # 2026-09-21 真机抓到的洞：入口原来只看"他现在按不按单拿钱"，于是被改成固定工资的司机
    # 那一格消失，而他改规则**之前**攒下的按单账单还在（prod 实测 92 笔 / ¥2024）——
    # 订单卡片又已经不画金额了，那笔钱在 App 里就彻底看不见。
    print("\n== 9. 「我的账单」入口：有钱要对就显示（2026-09-21 真机补的）==")
    dpay = read(DRIVER_PAY)
    uschema = read(ROOT / "backend/app/schemas/user.py")
    users_api = read(ROOT / "backend/app/api/v1/users.py")
    dtos = read(AND / "data/remote/dto/Dtos.kt")

    c.present("判据落在 `driver_pay`（钱的唯一口径处），不是散在接口里",
              dpay, r"def has_per_order_earnings\(")
    c.present("判据的两头都在：**当前按单** → 直接算有",
              dpay, r'if snapshot_mode\(driver\) == "PIECE":\s*\n\s*return True')
    c.present("另一头：**账上已有按单账单** → 也算有",
              dpay, r"DriverBill\.bill_type")
    # ⛔ 大小写必须归一：`DriverBillType.PIECE` 的值是小写 "piece"，MySQL 的 = 不区分大小写
    #    （线上照样命中），而 SQLite 的 = **区分**大小写（本地永远查不到）——"线上对、本地空"。
    c.present("账单类型比大小写归一（否则 SQLite 上永远查不到）",
              dpay, r'func\.upper\(DriverBill\.bill_type\) == "PIECE"')
    c.present("`/users/me` 真的把它算出填进出参",
              users_api, r"out\.has_per_order_earnings = has_per_order_earnings\(db, current\)")
    c.present("出参 schema 里有这个字段", uschema, r"has_per_order_earnings: bool \| None = None")
    c.present("客户端 DTO 里有这个字段",
              dtos, r'@SerialName\("has_per_order_earnings"\)')
    c.present("客户端入口是**两个字段的或**（不是只看 paysPerOrder）",
              read(PROFILE_SCREEN),
              r"vm\.user\?\.paysPerOrder == true \|\| vm\.user\?\.hasPerOrderEarnings == true")
    # ⛔ 别把两个概念合并：`pays_per_order` 是"以后派的单按不按单算"，派单端靠它决定运费框
    c.present("`pays_per_order` 的原语义没被改（派单端还在用它决定运费框）",
              users_api, r'out\.pays_per_order = snapshot_mode\(u\) == "PIECE"')
    c.present("派单端仍然读 `paysPerOrder`",
              read(AND / "ui/dispatcher/DispatcherPoolViewModel.kt"),
              r"u\.paysPerOrder\?\.let \{ return it \}")
    api_test = read(ROOT / "backend/tests/test_driver_billing_api.py")
    c.present("后端有测试钉住『改成固定工资后仍要能对账』",
              api_test, r"def test_改成固定工资之后_账上的按单钱仍然要能对账")
    c.present("后端也有测试钉住『没按单跑过的纯固定工资司机仍然没有这一格』",
              api_test, r"def test_一直拿固定工资没按单跑过的司机_没有我的账单入口")


    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项不通过：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
