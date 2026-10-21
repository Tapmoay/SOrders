#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_check_order_delivery_date.py —— 「下单时选送达日期」这一笔（FEAT-0028）的判据。

### 用户要的是什么（2026-10-21 原话）

> 「货主和批发商以及派单员，他们在下单的时候有一个界面有个功能就是**可以选择送到的日期**，
>   UI 我们也做好；然后我们还要加一个警示，**在那个日期选择前面加一个红色的警示**……
>   告诉他们**订单必须提前一天下达，当天下的单不一定能准时送达**。」

### 这一笔最容易走样的四处（都不报错）

| # | 走样的写法 | 后果（界面上看不出来） |
| --- | --- | --- |
| 1 | 把"送达日"塞进 `order_date` | 下单日 = 送达日，"提前一天"永远成立；报表分桶也跟着错位 |
| 2 | 拿 `order_date + 1` 现算而不落库 | 详情 / 派单 / 司机端永远查不到"这单约的是哪天"，改一次单就更不知道了 |
| 3 | 红条画在**日期那一行下面**，或画成橙色 | 用户点名"**前面**"、点名"**红色**"；顺序与颜色都是他给的验收条件 |
| 4 | 把写死的校验放在**日历选择层以外**不管 | 用户能选出一个注定被后端拒的日子，同一个错误要说两遍 |

所以判据盯四组：**后端那一列与那道闸** / **客户端数据面** / **页面形状（顺序 + 颜色 + 逐字文案）** /
**日期规则只住一处（UTC 毫秒口径）**。

### ⛔ 它证不了什么

- 证不了真机上"点开抽屉 → 选明天 → 提交 → 库里真的写着明天" —— 那要跑一遍下单链路
  （本轮的真机证据见 `docs/changes/FEAT-0028.md` ⑧）。
- 证不了"用户接受这条红字的位置与措辞"：那是他看过截图之后的事。

用法：
    python _tools/qa/_check_order_delivery_date.py           # 打印逐项
    python _tools/qa/_check_order_delivery_date.py --check   # 非零退出＝有问题（进 _check_all.py）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "backend/app/models/order.py"
MIGRATION = ROOT / "backend/app/migrations/036_order_delivery_date.py"
SCHEMA = ROOT / "backend/app/schemas/order.py"
COMMAND = ROOT / "backend/app/commands/order.py"
FLOW = ROOT / "backend/app/services/order_flow.py"
BOOTSTRAP = ROOT / "backend/app/core/schema_bootstrap.py"
DTOS = ROOT / "android/app/src/main/java/com/tapmoay/sorders/data/remote/dto/Dtos.kt"
VM = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/OrderCreateViewModel.kt"
SCREEN = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/OrderCreateScreen.kt"
RULES = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/common/DeliveryDate.kt"
CARD = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/common/OrderCard.kt"
DETAIL = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailScreen.kt"
DETAIL_VM = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailViewModel.kt"
EDIT_INLINE = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderEditInline.kt"
#: 毫秒换算的**唯一**那一份（车辆年检页与下单页共用；FEAT-0028 顺带把它从设备时区改成 UTC 零点）。
SHARED_MILLIS = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/VehicleInspection.kt"

#: 判据条数下限：低于它就说明源码形状变了、判据空转了（永远绿的检查 = 没有检查）。
MIN_RULES = 24

bad: list[str] = []
checked = 0


def _ok(m: str) -> None:
    global checked
    checked += 1
    print("  OK   " + m)


def _bad(m: str) -> None:
    global checked
    checked += 1
    print("  BAD  " + m)
    bad.append(m)


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def _code_only(src: str) -> str:
    """去掉注释与文档字符串 —— 判据只许锚在**代码**上（注释里会提到这些名字来解释"为什么"）。"""
    src = re.sub(r'"""[sS]*?"""', "", src)
    src = re.sub(r"'''[sS]*?'''", "", src)
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return re.sub(r"^[ \t]*//.*$", "", src, flags=re.M)


def _need(name: str, cond: bool, why: str = "") -> None:
    if cond:
        _ok(name)
    else:
        _bad(name + ("　—— " + why if why else ""))


def main() -> int:
    model = _code_only(_read(MODEL))
    mig = _read(MIGRATION)
    mig_code = _code_only(mig)
    schema = _code_only(_read(SCHEMA))
    cmd = _code_only(_read(COMMAND))
    flow = _code_only(_read(FLOW))
    boot = _code_only(_read(BOOTSTRAP))
    dtos = _code_only(_read(DTOS))
    vm = _code_only(_read(VM))
    screen = _code_only(_read(SCREEN))
    rules = _code_only(_read(RULES))
    shared_millis = _code_only(_read(SHARED_MILLIS))
    card = _code_only(_read(CARD))
    detail = _code_only(_read(DETAIL))

    print("1. 后端：这一列与这一道闸")
    _need(
        "orders 有独立的 delivery_date 列（date，可空）",
        bool(re.search(r"delivery_date:\s*Mapped\[date \| None\]\s*=\s*mapped_column\(\s*Date", model)),
        "没这一列，日期只能塞进 order_date（那就再也分不出是哪天下的单）",
    )
    _need(
        "⛔ order_date 的注释里写明它与送达日不是同一件事",
        "期望送达日" in _read(MODEL) and "order_date" in _read(MODEL),
    )
    _need(
        "迁移 036 存在且 VERSION = 36（与文件名同号）",
        bool(mig) and re.search(r"^VERSION\s*=\s*36\s*$", mig, re.M) is not None,
        "正式变更走 migrations/，缺了它生产库就永远没有这一列",
    )
    _need(
        "迁移先判存在再 ALTER（可重跑）",
        "ADD COLUMN delivery_date DATE" in mig_code and "delivery_date" in mig_code and "in cols" in mig_code,
        "MySQL 的 DDL 隐式提交，失败可能留半截",
    )
    _need(
        "⛔ schema_bootstrap 里没有第二份（两个来源 = 本项目头号忌讳）",
        "delivery_date" not in boot,
        "两处都写，改一处漏一处时谁都不知道最终结构是什么",
    )
    _need(
        "入参 OrderCreate 收 delivery_date（可空）",
        bool(re.search(r"class OrderCreate\([\s\S]*?\bdelivery_date:\s*date \| None", schema)),
        "不收就落不了库",
    )
    _need(
        "出参 OrderOut 带 delivery_date",
        bool(re.search(r"class OrderOut\([\s\S]*?\bdelivery_date:\s*date \| None", schema)),
        "出参没有它，详情 / 卡片 / AI 都读不到",
    )
    _need(
        "create_order 拒「早于今天」（business_today 那一条）",
        "body.delivery_date < business_today()" in cmd and "送达日期不能早于今天" in cmd,
        "业务当地日才算数 —— 用 date.today() 在东八区会差一天",
    )
    _need(
        "create_order 把它写进 Order(...)",
        "delivery_date=body.delivery_date" in cmd,
    )
    _need(
        "拆分单继承送达日（同一趟货）",
        "delivery_date=order.delivery_date" in flow,
        "拆出来的货还是同一趟，日子丢了就只能猜",
    )
    _need(
        "转货新开单继承送达日",
        "delivery_date=source.delivery_date" in cmd,
        "转货抄的是「这趟货」的信息，送达日属于这趟货",
    )

    print("2. 客户端数据面")
    _need(
        "OrderCreateRequest 带 delivery_date",
        '@SerialName("delivery_date") val deliveryDate: String? = null' in dtos,
    )
    _need(
        "OrderDto 读得出 delivery_date",
        dtos.count('@SerialName("delivery_date")') >= 2,
    )
    _need(
        "VM 的初值是**空串**（⛔ 不替用户预选明天 —— 用户 2026-10-22 逐字纠正过）",
        'var deliveryDate by mutableStateOf("")' in vm and "defaultDeliveryDate()" not in vm,
        "预填一个日子 = 替他做了一个他没做过的决定，而这一格是给司机/派单员去履约的承诺",
    )
    _need(
        "空着提交会被拦住（说清是去选日期，不是让服务端猜）",
        "deliveryDate.isBlank() -> error =" in vm and "请先选送达日期" in vm,
    )
    _need(
        "VM 提交前再判一次（页面开着过夜也不能发出去）",
        "!deliveryDateAllowed(deliveryDate)" in vm and "送达日期已经过去了" in vm,
    )
    _need(
        "VM 把值放进请求体",
        "deliveryDate = deliveryDate," in vm,
    )

    print("3. 页面形状：红条在日期那一行**前面**（用户点名）")
    _need(
        "页面有「送达日期」分组",
        'title = "送达日期"' in screen,
    )
    pos_notice = screen.find("DeliveryLeadNotice()")
    pos_row = screen.find('label = "哪天送到"')
    _need(
        "红条画在日期那一行之前（上面）",
        pos_notice >= 0 and pos_row >= 0 and pos_notice < pos_row,
        "用户原话是「在日期选择**前面**加一个红色的警示」；画在下面就是另一句话了",
    )
    _need(
        "警告是**红**的（errorContainer 底 + DangerRed 的字与图标）",
        "color = MaterialTheme.colorScheme.errorContainer" in screen
        and "tint = Color(DangerRed)" in screen
        and "color = Color(DangerRed)" in screen,
        "用户点名要做成红色",
    )
    _need(
        "警告逐字写着「提前一天」＋「下单」＋「当天…不一定能准时送达」",
        "提前一天" in screen and '"下单"' in screen and "不一定能准时送达" in screen,
        "用户 2026-10-22 纠正过措辞：是「提前一天**下单**」，不是「下达」",
    )
    # ⚠️ 这一条**必须切出函数体**再判：只在整页里搜 "Text(" 的话，页面其它地方到处都是 Text，
    #    把这条红字改成 Hint 也不会红 —— 那就是一条永远绿的断言。
    _notice = re.search(r"private fun DeliveryLeadNotice\(\)[\s\S]*?\n\}", screen)
    _notice_body = _notice.group(0) if _notice else ""
    _need(
        "警告走 Text，⛔ 不走 Hint（总开关关掉之后它仍然必须看得见）",
        "Text(" in _notice_body and "Hint(" not in _notice_body,
        "红条是警告不是解释句；写成 Hint 会被提示总开关一起关掉",
    )
    _need(
        "抽屉给「今天 / 明天 / 后天 / 大后天」四档 + 「选其他日期」",
        "deliveryDateChoices().forEach" in screen and "选其他日期…" in screen,
    )
    _need(
        "那一行空着时显示占位「请选择」（不是空荡荡一行）",
        'placeholder = "请选择",' in screen,
    )
    _need(
        "「不保证准时」是**深红胶囊**（与红条同一个观感）",
        "noteAccent = when {" in screen
        and "deliveryLeadDays(iso) == 0L -> Color(DangerRed)" in screen
        and re.search(r"val accent = noteAccent[\s\S]{0,160}?Surface\(color = accent, shape = CircleShape\)", screen) is not None,
        "用户 2026-10-22：「这个不保证准时……也同样用胶囊背景色，用红色的深色胶囊框起来，美观一点」",
    )
    _need(
        "「推荐」是**深绿胶囊**（绿色那一条也要有底）",
        "iso == recommended -> Color(ThemeGreenDeep)" in screen,
        "用户 2026-10-22：「那你也给那个绿色的推荐搞一个绿色深绿色的底啊」",
    )
    _need(
        "抽屉里那句提示有**警示黄底色**（WarningAmber，与下面的红区分开，且底色挂在 Hint 上）",
        "background(Color(WarningAmber), RoundedCornerShape(10.dp))" in screen
        and re.search(r"Hint\([\s\S]{0,120}?提前一天下单，才排得进明天的车", screen) is not None,
        "用户 2026-10-22：「就搞黄色吧，就是我们常用的警示黄色」",
    )
    _need(
        "抽屉里把「明天」标成**推荐**（还是让用户自己点，⛔ 不预选）",
        'val recommended = defaultDeliveryDate()' in screen and '"推荐"' in screen,
    )
    _need(
        "今天那一行如实标「不保证准时」",
        "不保证准时" in screen and "deliveryLeadDays(iso) == 0L" in screen,
    )
    _need(
        "日历里过去的日子点不动（selectableDates）",
        "selectableDates = object : SelectableDates" in screen
        and "deliveryDateSelectable(utcTimeMillis)" in screen,
        "让用户选出一个注定被拒的日子，是同一个错误要说两遍",
    )
    _need(
        "确认时再判一次（草稿里本来就过期的日子不许写回）",
        "if (picked != null && deliveryDateSelectable(picked))" in screen,
    )
    _need(
        "⛔ 下单页自己不碰 java.time（规则只住 DeliveryDate.kt）",
        "LocalDate" not in screen,
        "界面里再来一份 \"是不是昨天\"，迟早跟规则文件对不上",
    )

    print("4. 日期规则：一处实现 + UTC 毫秒口径")
    _need(
        "规则文件里有默认值 / 能不能选 / 显示三件事",
        "fun defaultDeliveryDate(" in rules
        and "fun deliveryDateAllowed(" in rules
        and "fun deliveryDateLabel(" in rules,
    )
    _need(
        "「提前一天」是一个具名常量（不是散落的 +1）",
        re.search(r"const val DELIVERY_LEAD_DAYS: Long = 1L", rules) is not None,
    )
    # 毫秒换算**不在**本单的规则文件里：全 App 只有那一份（车辆年检页那对 internal fun，
    # 判据 _check_vehicle_inspection_ui.py:158 盯着"只有一处"）。FEAT-0028 顺手把它改成了 UTC，
    # 所以这里既要盯"共用"，也要盯"口径是 UTC"。
    _need(
        "⛔ 规则文件不自己再抄一份毫秒换算（复用全 App 那一份）",
        "fun isoDateOfMillis(" not in rules and "fun isoDateToMillis(" not in rules,
        "两对同名函数 = 两份换算，迟早一处改了一处没改",
    )
    _need(
        "共用的毫秒换算是 **UTC 零点**（按设备时区在东八区会差一天）",
        "atZone(ZoneOffset.UTC)" in shared_millis and "atStartOfDay(ZoneOffset.UTC)" in shared_millis,
        "DatePicker 的约定就是 UTC 零点毫秒；用 systemDefault 会打开时停在前一天",
    )
    _need(
        "⛔ 规则文件里没有 systemDefault 换算",
        "ZoneId.systemDefault()" not in rules,
    )

    print("5. 「提前一天」更显眼（深红胶囊）＋ 卡片与详情都能看到（CHG-0134）")
    _notice2 = re.search(r"private fun DeliveryLeadNotice\(\)[\s\S]*?\n\}", screen)
    _notice2_body = _notice2.group(0) if _notice2 else ""
    _need(
        "**只有「提前一天」三个字**是深红胶囊（Surface + Color(DangerRed) + CircleShape）",
        "color = Color(DangerRed)" in _notice2_body
        and "shape = CircleShape" in _notice2_body
        and '"提前一天"' in _notice2_body,
        "用户 2026-10-22 逐字校正：「真正需要搞的信息就是 3 个字，提前一天……其他的没必要搞」",
    )
    _need(
        "⛔ 整句没有塞进胶囊（只有那三个字）",
        "订单必须提前一天下单" not in _notice2_body,
        "整句染深既刺眼、又看不出哪三个字是重点",
    )
    _need(
        "下半句仍是红字（只染「提前一天」三个字，⛔ 整条染深就刺眼）",
        "当天下的单，不一定能准时送达。" in _notice2_body,
    )
    _need(
        "订单卡片上有一行送达日期（三端共用那一张卡）",
        re.search(r"deliveryDateDisplay\(order\.deliveryDate, order\.status\)", card) is not None,
        "司机与派单员都是在这张卡上看单的 —— 卡片没有，就等于只有下单的人知道",
    )
    _need(
        "订单详情有一行「送达日期」",
        re.search(r"\"送达日期　\" \+ deliveryDateDisplay\(", detail) is not None,
        "详情页是三方都要看的那一页（货主 / 派单员 / 司机）",
    )
    _need(
        "没选过的单**明说**「未选择送达日期」，不许整行消失",
        '"未选择送达日期"' in rules
        and re.search(r"deliveryDateDisplay\(order\.deliveryDate, order\.status\)", card) is not None
        and re.search(r"\"送达日期　\" \+ deliveryDateDisplay\(", detail) is not None,
        "用户 2026-10-22：「如果他没选择的话，订单里就有一条信息说他没有选择送达日期」",
    )
    _need(
        "倒计时只有一处算法（界面不自己拼「还有 N 天」）",
        len(re.findall(r"fun deliveryCountdown\(", rules)) == 1
        and "还有 " not in card
        and "还有 " not in detail,
        "同一句话两个算法，迟早一处改了另一处没改",
    )
    _need(
        "终态订单不再显示倒计时（DELIVERED / CANCELLED / RETURNED 只印日期）",
        "if (status.uppercase() in FINISHED_STATUS) return md" in rules
        and '"DELIVERED"' in rules and '"CANCELLED"' in rules and '"RETURNED"' in rules,
        "已送达的单上写「还有 1 天」会被读成「还没到」",
    )

    print("6. 派单员能在详情页改它（CHG-0135）")
    vmdetail = _code_only(_read(DETAIL_VM))
    _need(
        "入参 OrderUpdate 也收 delivery_date（PATCH 语义：None = 不改）",
        "class OrderUpdate(" in schema and re.search(r"class OrderUpdate\([\s\S]*?\bdelivery_date:\s*date \| None", schema) is not None,
    )
    _need(
        "它进了 DISPATCHER_ONLY_FIELDS（货主那扇「只补联系信息」的门撞到它要 403）",
        '("delivery_date", "送达日期")' in cmd,
        "少了这一行 = 货主能改送达日期，那是把派单员的编辑权让出去",
    )
    _need(
        "改单那道闸也拒「早于今天」（与下单同一条口径，两处各有一个判断）",
        "if body.delivery_date is not None and body.delivery_date < business_today():" in cmd
        and "if body.delivery_date < business_today():" in cmd
        and cmd.count("送达日期不能早于今天") == 2,
    )
    _need(
        "VM 的 saveEdit 会把它报上去（空串 = null = 不改，⛔ 不拿它去清空）",
        "deliveryDate = draft(OrderEditField.DELIVERY_DATE).trim().ifBlank { null }" in vmdetail,
    )
    _need(
        "详情页那一行有**图标 + 语义色**，且只有派单员看得到竖杠与铅笔",
        "TintedIcon(Icons.Default.Event" in detail
        and "EditHint(onClick = { edit.startEdit(OrderEditField.DELIVERY_DATE) })" in detail
        and "if (canEditInfo) EditRail()" in detail,
        "用户 2026-10-22：「要有对应的图标和语义色……我们的派单员是可以修改这个信息的」",
    )
    _need(
        "改日期弹层存在，且选择层就封顶今天（复用同一条规则）",
        "fun DeliveryDateEditBlock(" in _code_only(_read(EDIT_INLINE))
        and "deliveryDateSelectable(utcTimeMillis)" in _code_only(_read(EDIT_INLINE)),
    )

    print()
    if bad:
        print("❌ 失败 %d 项（共 %d）：" % (len(bad), checked))
        for b in bad:
            print("   - " + b)
        return 1
    if checked < MIN_RULES:
        print("❌ 只跑到 %d 项（下限 %d）—— 源码形状多半变了，先别信这条判据" % (checked, MIN_RULES))
        return 1
    print("✅ 全部通过：%d 项" % checked)
    return 0


if __name__ == "__main__":
    sys.exit(main())
