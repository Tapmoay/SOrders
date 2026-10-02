# -*- coding: utf-8 -*-
"""红线：**联系人可以被挑、也可以绑在「地点 / 线路」上**（2026-09-24 用户要求）；
**手机号选填、补上了就存回档案**（CHG-0010，2026-10-03）。

## 用户原话
> 「给户主也加一个在选择下单的时候**可以选择联系人**，就**不用每次要手动填入了**。同时再给他
>  添加个功能就是**可以通过地点来绑定联系人**，就大家选择地点之后，自动填入对应的联系人。…
>  我们的**派单员**，它也要具有这个功能，也可以通过**地点或者是线路**去绑定联系人，
>  ⛔ 货主他也可以通过线路绑定联系人都是可以的。」
> （原文里"不过一般线路，它是自动的会需要填入联系人的。到时候你看着办。"）

## 这条为什么必须有机器的判据
"收货人名称 / 收货人电话"这两栏现在有**四个来源**：手打、选联系人、选线路、选地点。
覆盖规矩写错**一个都不会报错**，表现只是：

* 名字还在、**电话换成了上一个人的**（名册里那个人没写名字时"只换一半"的典型后果）—— 司机会打给错的人；
* 刚敲好的名字被**一次选点**清掉（用户选那个地点只是为了填地址）；
* 地点编辑保存一次就把绑定**静默清掉**（地点更新是"整份回传"语义，界面不回填就等于解绑）。

所以判据分五层：

1. **只有一处实现**：`fillReceiver`（回填判据）/ `hasBoundContact` / `boundContactLabel` /
   `ContactPickerSheet`（挑选弹层）各只有一处定义，**0 处也红**（零件被改名/删掉时判据不许空转）；
2. **两处消费**：下单页与「地址与联系人」都调用**同一个**弹层；两个 VM 的回填都走 `fillReceiver`
   （不许再出现 `draftName = c.displayName`、`dongjiaName = l.contactName` 这种内联写法）；
3. **共享地点不绑人**：`places` 是全库共用的（司机补录的坐标大家都能选），
   往它上面绑一个人的电话等于给所有人换了默认收货人 —— `applyPlace` 与 `PlaceDto` 里
   都不许出现 contact 字段；
4. **存快照串、不存外键**：与线路（`receiver_name`/`phone`）同一口径（名册删人/改名都不该动它），
   而且"改地点/由 AI 改地点"必须**回填**已绑的联系人（不回填 = 静默解绑）；
5. **删除仍可恢复 + 单测 + 反向验证**：软删恢复后联系人还在（后端用例钉着）、
   回填判据有 JVM 单测、这条红线自己配了反向验证。

用法：python _tools/qa/_check_contact_binding.py
     python _tools/qa/_check_contact_binding.py --list
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _check_product_card_single_source import strip_comments  # noqa: E402
from _airepo import ai_write_source, refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
BE = ROOT / "backend/app"

FILL = AND / "ui/common/ContactFill.kt"
SHEET = AND / "ui/common/ContactPickerSheet.kt"
ORDER_SCREEN = AND / "ui/shipper/OrderCreateScreen.kt"
ORDER_VM = AND / "ui/shipper/OrderCreateViewModel.kt"
ADDR_SCREEN = AND / "ui/shipper/AddressScreen.kt"
ADDR_VM = AND / "ui/shipper/AddressViewModel.kt"
AI_SVC = AND / "ai/AiWriteService.kt"
AI_DATA = AND / "ai/AiWriteBasicData.kt"
DTOS = AND / "data/remote/dto/Dtos.kt"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/common/ContactFillTest.kt"

BE_MODEL = BE / "models/shipper.py"
BE_PLACE = BE / "models/place.py"
BE_SCHEMA = BE / "schemas/shipper.py"
BE_API = BE / "api/v1/shipper.py"
BE_BOOT = BE / "core/schema_bootstrap.py"
BE_TEST = ROOT / "backend/tests/test_location_contact.py"
#: CHG-0010（2026-10-03）：联系人**手机号选填** + 下单时补的号写回档案
BE_MIG = BE / "migrations/011_contact_phone_optional.py"
BE_TEST_OPT = ROOT / "backend/tests/test_contact_phone_optional.py"
IN_RULES = AND / "core/InputRules.kt"
#: 姓名与电话"至少填一个"这条下限，客户端与服务端**共用**的半句（两边不许各写各的）
IDENTITY_CORE = "姓名和手机号至少填一个"

REVERSE = "_tools/qa/_reverse_verify_contact_binding.py"
DOC = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"

#: 扫到的界面文件数下限（防目录改名/搬走之后"一个文件都没扫到"也算过）
MIN_UI_FILES = 100
#: 抽出来的函数体字符数下限（**抽取失效比判据腐烂更危险** —— 那会变成一条永远绿的检查）
BODY_FLOOR = 80


def read(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def code(p: Path) -> str:
    return strip_comments(read(p))


def fn_body(src: str, sig: str) -> str:
    """`sig`（如 `private fun applyPlace(`）那个函数的**函数体**（大括号配对，不按行猜）。"""
    i = src.find(sig)
    if i < 0:
        return ""
    b = src.find("{", i)
    if b < 0:
        return ""
    depth = 0
    for j in range(b, len(src)):
        c = src[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[b : j + 1]
    return ""


def count(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text))


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

    def report(self, title: str) -> int:
        print()
        print(f"===== {title} =====")
        print(f"  通过 {self.passes} 项，失败 {len(self.fails)} 项")
        for f in self.fails:
            print(f"    - {f}")
        return 1 if self.fails else 0


def main() -> int:
    if refuse_if_injecting("联系人绑定检查"):
        return 1

    c = Checker()
    print("联系人（可选 / 可绑在地点与线路上）：2026-09-24")

    ui_files = list(AND.rglob("*.kt"))
    c.ok(
        f"扫到的界面文件数 ≥ {MIN_UI_FILES}（防目录搬走 → 判据空转）",
        len(ui_files) >= MIN_UI_FILES,
        f"实际 {len(ui_files)}",
    )

    # ---- 1. 文件都在 ----
    for p, why in (
        (FILL, "回填判据的唯一实现处"),
        (SHEET, "挑选联系人的唯一弹层"),
        (TEST, "回填判据的 JVM 单测"),
        (BE_TEST, "后端那条链路的用例（含软删恢复）"),
    ):
        c.ok(f"{p.relative_to(ROOT).as_posix()} 存在（{why}）", p.exists(), "文件被搬走/改名了")

    fill = code(FILL)
    sheet = code(SHEET)
    order_screen = code(ORDER_SCREEN)
    order_vm = code(ORDER_VM)
    addr_screen = code(ADDR_SCREEN)
    addr_vm = code(ADDR_VM)

    # ---- 2. 只有一处定义（0 处也红）----
    for name in ("fillReceiver", "hasBoundContact", "boundContactLabel"):
        here = count(rf"fun {name}\(", fill)
        elsewhere = [
            p.relative_to(AND).as_posix() for p in ui_files if p != FILL and count(rf"fun {name}\(", code(p))
        ]
        c.ok(
            f"`{name}` 只有一处定义（在 ui/common/ContactFill.kt，且别处 0 处）",
            here == 1 and not elsewhere,
            f"这里 {here} 处；别处还有 {elsewhere}",
        )
    sheet_defs = [p.relative_to(AND).as_posix() for p in ui_files if count(r"fun ContactPickerSheet\(", code(p))]
    c.ok(
        "`ContactPickerSheet` 只有一处定义",
        sheet_defs == ["ui/common/ContactPickerSheet.kt"],
        f"定义处：{sheet_defs}",
    )

    # ---- 3. 两个页面都用同一个弹层（各写一份 = 同一个人在一处挑得到、另一处挑不到）----
    for label, src in (("下单页", order_screen), ("地址与联系人", addr_screen)):
        c.ok(f"{label} 用共用弹层 `ContactPickerSheet(`", "ContactPickerSheet(" in src, "没用共用弹层")
    c.ok(
        "两个页面都没有第二份「联系人列表」（不许再拿 `vm.contacts.*` 摊成菜单）",
        # ⚠️ 只禁**渲染名册**的那几种（forEach / map / sorted…）：`vm.contacts.filter { … }`
        #    是「联系人」那一段自己的本地搜索，不是第二份挑选实现 —— 禁它会把好人打成假红。
        not count(r"vm\.contacts\.(forEach|map|mapNotNull|sortedBy|sortedWith|asSequence)\s*[({]", order_screen)
        and not count(r"vm\.contacts\.(forEach|map|mapNotNull|sortedBy|sortedWith|asSequence)\s*[({]", addr_screen),
        "又有人把名册摊成一个下拉了 —— 该走 ContactPickerSheet",
    )

    # ---- 3b. 那一行排在**收货人名称上面**（CHG-0005，用户 2026-09-28 点名）----
    #
    # ⚠️ **顺序被用户改过一次**：原来它在「收货人名称 / 收货人电话」**下面**。
    #    用户原话：「从联系人选收货人放在**收货人名称的上面**，不要放在他们的下面」。
    #    判的是**位置**而不是"有没有"（有没有已经由第 3 组管了）：它是"一次填两栏"的**另一种做法**，
    #    压在下面会被读成"填完了再补充" —— 顺序反了。
    pos_pick = order_screen.find('label = "从联系人里选收货人"')
    pos_name = order_screen.find('label = "收货人名称"')
    pos_phone = order_screen.find('label = "收货人电话"')
    c.ok(
        "「从联系人里选收货人」排在「收货人名称 / 收货人电话」**上面**",
        -1 < pos_pick < pos_name < pos_phone,
        f"位置：选联系人={pos_pick} 名称={pos_name} 电话={pos_phone}（要求 选联系人 < 名称 < 电话）",
    )

    # ---- 3c. 代理下单页**不显示**那一行（CHG-0006，用户 2026-09-28 给截图点名）----
    #
    # 用户原话：「是我红色框那个地方，**派单员是不需要的**，它已经有了，相当于功能重叠」。
    # 派单员的收货人是**跟着线路/地点带出来的**（`applyAddress`/`applyLocation` → `fillReceiver`），
    # 再给一行"从名册里挑"就是同一件事两个入口。
    # ⛔ 判的是**那一行被 `if (!proxyMode)` 包着**，不是"文件里还有没有这句话" ——
    #    只判后者的话，把守卫删掉（货主与派单员都显示）照样绿。
    c.ok(
        "「从联系人里选收货人」只在货主自下单时出现（代理下单页不显示）",
        re.search(r'if \(!proxyMode\) \{[\s\S]{0,400}?label = "从联系人里选收货人"', order_screen)
        is not None,
        "代理下单页又出现这一行了 —— 用户 2026-09-28 截图点名：「他自己上面就可以选择货主，"
        "这样子的话属于功能重叠，他根本就不需要这个」",
    )

    # ---- 4. 回填判据只有一份：两个 VM 都走 fillReceiver，不许内联 ----


    c.ok(
        "下单页 VM 走共用回填判据（`fillReceiver(` 至少 2 处：挑人 / 选地点）",
        count(r"fillReceiver\(", order_vm) >= 2,
        f"只有 {count(r'fillReceiver\(', order_vm)} 处",
    )
    c.ok(
        "地址与联系人 VM 走共用回填判据（线路挑人 / 地点挑人 / 选终点地点）",
        count(r"fillReceiver\(", addr_vm) >= 3,
        f"只有 {count(r'fillReceiver\(', addr_vm)} 处",
    )
    inline = []
    if count(r"dongjiaName\s*=\s*l\.contact", order_vm):
        inline.append("OrderCreateViewModel: dongjiaName = l.contact*")
    if count(r"draftName\s*=\s*c\.displayName", addr_vm):
        inline.append("AddressViewModel: draftName = c.displayName")
    if count(r"draftName\s*=\s*l\.contact", addr_vm):
        inline.append("AddressViewModel: draftName = l.contact*")
    c.ok(
        "两个 VM 里没有第二份回填写法（内联 `= c.displayName` / `= l.contact*`）",
        not inline,
        f"又抄回去了：{inline}",
    )

    # ---- 5. 共享地点**不绑人**（那是全库共用的一张表）----
    place_body = fn_body(order_vm, "fun applyPlace(")
    c.ok(
        "选**共享地点**时不许碰联系人（`applyPlace` 体里没有 contact 字段，≥ %d 字符才当真" % BODY_FLOOR,
        len(place_body) >= BODY_FLOOR and not re.search(r"contact", place_body, re.I),
        f"体长 {len(place_body)}；出现了 contact",
    )
    place_dto = code(DTOS)
    m = re.search(r"data class PlaceDto\(([\s\S]*?)\n\)", place_dto)
    c.ok(
        "`PlaceDto` 里没有联系人字段（共享库不绑人）",
        m is not None and not re.search(r"contact", m.group(1), re.I),
        "PlaceDto 多了 contact 字段 —— 共享地点库是全库共用的",
    )
    c.ok(
        "后端 `places` 表也没有联系人列",
        not re.search(r"contact", code(BE_PLACE), re.I),
        "models/place.py 里出现了 contact",
    )

    # ---- 6. 存快照串、不存外键（与线路同一口径）----
    model = code(BE_MODEL)
    # ⚠️ `ShipperLocation` 是这个文件的**最后一个类** —— 用 `class …([\s\S]*?)\nclass ` 去截会
    #    截到空串，于是下面两条断言全变成"空体上恒真"（假绿）。所以从类名一路取到文件末尾，
    #    并加一条体长下限兜住它。
    i = model.find("class ShipperLocation(")
    loc_body = model[i:] if i >= 0 else ""
    c.ok(
        "抽出了 `ShipperLocation` 的类体（≥ 500 字符 —— 抽取失效会让下面两条变成假绿）",
        len(loc_body) >= 500,
        f"只有 {len(loc_body)} 字符",
    )
    c.ok(
        "`shipper_locations` 有 contact_name / contact_phone 两列（String 快照串）",
        count(r"contact_name: Mapped\[str\] = mapped_column\(String\(128\)", loc_body) == 1
        and count(r"contact_phone: Mapped\[str\] = mapped_column\(String\(32\)", loc_body) == 1,
        "两列没找到（或类型变了）",
    )
    c.ok(
        "⛔ 不是外键（不许挂 `shipper_contacts.id`：名册删人/改名不该动这一份快照）",
        "shipper_contacts" not in loc_body,
        "contact_* 挂上了 shipper_contacts 的外键",
    )

    # ---- 7. 后端三件套：schema 出入参 + API 写入 + 线上补列 ----
    schema = code(BE_SCHEMA)
    # ⚠️ 用「字段声明」而不是 `"contact_name" in body`：后者会被 `contact_name_xxx` 骗过去
    #    （反向验证实测：把 `contactName` 改名成 `contactNameZZZ`，`in` 判据照样绿）。
    for cls, want in (
        ("LocationCreate", r"contact_name: str = Field\("),
        ("LocationUpdate", r"contact_name: str \| None = Field\("),
        ("LocationOut", r'contact_name: str = ""'),
    ):
        seg = re.search(rf"class {cls}\(([\s\S]*?)\n\n\n", schema)
        body = seg.group(1) if seg else ""
        c.ok(
            f"`{cls}` 有 contact_name / contact_phone（按**字段声明**判，不是子串）",
            re.search(want, body) is not None and re.search(r"contact_phone: ", body) is not None,
            f"{cls} 里缺字段",
        )
    api = code(BE_API)
    c.ok(
        "POST /shipper/locations 写入联系人",
        count(r"contact_name=body\.contact_name", api) >= 1 and count(r"contact_phone=body\.contact_phone", api) >= 1,
        "create 没写进去",
    )
    c.ok(
        "PATCH 走三档语义（`is not None` 才改 —— 不传 = 不改、空串 = 解绑）",
        count(r"if body\.contact_name is not None:", api) == 1
        and count(r"if body\.contact_phone is not None:", api) == 1,
        "PATCH 的 None 语义被写丢了（改个名字会把绑定清掉）",
    )
    boot = code(BE_BOOT)
    c.ok(
        "线上补列在 `schema_bootstrap` 里（旧库也要有这两列，否则读一地点的接口直接 500）",
        re.search(r'\("contact_name",\s*"VARCHAR\(128\) DEFAULT', boot) is not None
        and re.search(r'\("contact_phone",\s*"VARCHAR\(32\) DEFAULT', boot) is not None
        and "shipper_locations ADD COLUMN {col}" in boot,
        "核心区那个补列循环没找到（或列名/类型与模型不一致）",
    )
    c.ok(
        "补列的列宽与模型一致（128 / 32）",
        'VARCHAR(128) DEFAULT' in boot and 'VARCHAR(32) DEFAULT' in boot,
        "列宽与 model 不一致（MySQL 上会截断/报错）",
    )

    # ---- 8. Android DTO：整体回传语义 → 编辑必须回填 ----
    # ⚠️ 按**声明**判（`@SerialName("contact_name") val contactName: String`），不用 `in`：
    #    `contactNameZZZ` 这种改名会把 `"contactName" in body` 骗成绿的（反向验证实测）。
    loc_dto = re.search(r"data class LocationDto\(([\s\S]*?)\n\)", code(DTOS))
    dto_body = loc_dto.group(1) if loc_dto else ""
    c.ok(
        "`LocationDto` 有 contactName / contactPhone（出参，界面靠它显示已绑的人）",
        count(r'@SerialName\("contact_name"\)\s*val contactName: String', dto_body) == 1
        and count(r'@SerialName\("contact_phone"\)\s*val contactPhone: String', dto_body) == 1,
        "出参 DTO 缺字段（界面永远显示「未绑定」）",
    )
    req = re.search(r"data class LocationCreateRequest\(([\s\S]*?)\n\)", code(DTOS))
    req_body = req.group(1) if req else ""
    c.ok(
        "`LocationCreateRequest` 有 contactName / contactPhone（POST 与 PATCH 共用这一份）",
        count(r'@SerialName\("contact_name"\)\s*val contactName: String', req_body) == 1
        and count(r'@SerialName\("contact_phone"\)\s*val contactPhone: String', req_body) == 1,
        "请求 DTO 缺字段",
    )
    edit_body = fn_body(addr_vm, "fun openLocationEdit(")
    c.ok(
        "打开地点编辑时**回填**联系人（不回填 = 改个地点名把绑定静默清掉）",
        "locContactName = l.contactName" in edit_body and "locContactPhone = l.contactPhone" in edit_body,
        "openLocationEdit 里没有回填",
    )
    save_body = fn_body(addr_vm, "fun saveLocation(")
    c.ok(
        "保存地点时把联系人带进请求体",
        "contactName = locContactName" in save_body and "contactPhone = locContactPhone" in save_body,
        "saveLocation 没带联系人",
    )

    # ---- 9. AI 改地点也必须回填（否则模型说"改个名字"= 静默解绑）----
    # 2026-09-25（报告 11 第 3 步）：数据源已拆去 AiWriteDataSource.kt —— 读这一族的并集。
    ai_body = fn_body(ai_write_source(ROOT), "override suspend fun updateLocation(")
    c.ok(
        "AI 改地点时回填已绑的联系人（`?: cur.contactName`）",
        "?: cur.contactName" in ai_body and "?: cur.contactPhone" in ai_body,
        "AI 那条路没回填 —— 说一句「改个名」就把绑定清了",
    )
    c.ok(
        "AI 的键白名单里有 contact_name / contact_phone（否则卡片上写了也传不进去）",
        # 两个动作各一处字段声明（新增地点 / 改地点）→ ≥ 2；再钉住 LOCATION_KEYS 里也有那两个键
        count(r'textField\("contact_name"', code(AI_DATA)) >= 2
        and count(r'textField\("contact_phone"', code(AI_DATA)) >= 2
        and re.search(r'LOCATION_KEYS = setOf\([\s\S]*?"contact_name",\s*"contact_phone",', code(AI_DATA)) is not None,
        "AiWriteBasicData 的 LOCATION_KEYS / 字段表里缺这两个键",
    )

    # ---- 10. 头号场景：下单页那两栏真的接上了 ----
    order_body = fn_body(order_vm, "fun applyLocation(")
    c.ok(
        "下单页选「我的地点」时把地点绑的联系人带出来",
        "fillReceiver(" in order_body and "l.contactName" in order_body,
        "applyLocation 没接上联系人",
    )
    c.ok(
        "带出用的是 BROUGHT（有值才覆盖 —— 没绑人的地点不许清掉用户刚填的）",
        "ContactFillMode.BROUGHT" in order_body,
        "模式不对（PICKED 会把用户填的清掉）",
    )
    pick_body = fn_body(order_vm, "fun pickReceiver(")
    c.ok(
        "挑人用的是 PICKED（整对替换）",
        "ContactFillMode.PICKED" in pick_body,
        "模式不对（BROUGHT 会拼出「名字上一位、电话这一位」的人）",
    )
    c.ok(
        "下单页有「从联系人里选」的入口（`openContactSheet()`）",
        "vm.openContactSheet()" in order_screen,
        "界面上没有入口（功能等于没做）",
    )

    # ---- 11. 单测 + 文档 + 反向验证 ----
    test = read(TEST)
    c.ok(
        "回填判据有 JVM 单测，且两条规矩各钉了用例（BROUGHT / PICKED）",
        test.count("@Test") >= 8
        and test.count("fillReceiver(") >= 6
        and "ContactFillMode.BROUGHT" in test
        and "ContactFillMode.PICKED" in test,
        f"@Test {test.count('@Test')} 个、fillReceiver( {test.count('fillReceiver(')} 处",
    )
    c.ok("这条红线配了反向验证脚本", (ROOT / REVERSE).exists(), f"找不到 {REVERSE}")
    c.ok(
        "设计规范里记着这条（否则下一个人还会各写一份）",
        DOC.exists() and "ContactFill" in read(DOC),
        "06_DESIGN_SYSTEM.md 里没记联系人绑定这一节",
    )

    # ---- 12. CHG-0010：手机号**选填**、补上了就存回档案（2026-10-03 用户点名）----
    #
    # 用户原话：「新建联系人的时候**不需要必填手机号**」+「在下单的时候……**一旦补上去了，他就
    # 自动的做一份保存**」—— 两句连起来是**一条**功能：不填也能建 + 补了就存回去。
    #
    # 三段判据，各防一种"改了但没生效"：
    #   ① 客户端两处"必填"真的松开（只说选填、校验还拦着 = 用户还是建不出来）；
    #   ② "这一单的收货人是名册里的哪一位"被记住，且**任何一次手改**都清掉它 ——
    #      不清的话，这次补的号码会写到**上一位**头上（比不写更坏）；
    #   ③ 服务端那条写回的路真的通：列可空（空串在唯一索引里是真值，两条"没填"会撞键）、
    #      删除时不给空号编假号码、恢复时不拿 NULL 去调 `.endswith`。
    rules = code(IN_RULES)
    ident = re.search(
        r"fun contactIdentityError\(name: String, phone: String\): String\? =\s*\n"
        r'\s*if \(name\.isBlank\(\) && phone\.isBlank\(\)\) "([^"]+)" else null',
        rules,
    )
    c.ok(
        "`InputRules.contactIdentityError` 在（姓名与电话**至少填一个**的下限；按声明判，改名也红）",
        ident is not None,
        "找不到这个函数（或形状变了）—— 下限没了，两个都空也能存成一条谁也认不出的记录",
    )
    c.ok(
        f"客户端那句话里含着后端同一条下限「{IDENTITY_CORE}」（两边不许各写各的）",
        ident is not None and IDENTITY_CORE in ident.group(1),
        f"客户端现在说的是「{ident.group(1) if ident else '<没找到>'}」",
    )
    c.ok(
        "后端 Create 与 Update **两处**都拦这条下限（只有一处 = 另一个入口能把人存成空白）",
        count(re.escape(IDENTITY_CORE), api) >= 2,
        f"只找到 {count(re.escape(IDENTITY_CORE), api)} 处",
    )

    # 12a. 客户端：新建联系人的弹层 + 两个 VM 的入口都按"选填"走
    c.ok(
        "新建联系人弹层里电话是**选填**（`phoneError(…, required = false)`）",
        re.search(r"InputRules\.phoneError\(phone\.trim\(\), required = false\)", sheet) is not None,
        "又变回必填了 —— 用户 2026-10-03：「新建联系人的时候不需要必填手机号」",
    )
    c.ok(
        "弹层里那句占位符是「手机号（选填）」",
        "手机号（选填）" in sheet,
        "占位符还写着「必填」（用户看到的字与校验对不上）",
    )
    c.ok(
        "弹层把这条下限也接上了（两个都空就地提示，不用等后端 400 回来）",
        count(r"InputRules\.contactIdentityError\(", sheet) >= 1,
        "弹层里没接下限",
    )
    for label, src in (("地址与联系人", addr_vm), ("下单页", order_vm)):
        c.ok(
            f"{label} VM 里新建联系人也是选填 + 有下限（`required = false` 与 `contactIdentityError` 各 ≥1）",
            count(r"required = false", src) >= 1 and count(r"InputRules\.contactIdentityError\(", src) >= 1,
            "这条路上还是必填 / 没有下限",
        )

    # 12b. 下单页：记住"挑的是谁"，并且**手改就清掉**
    c.ok(
        "`pickedContactId` 是 `private set`（界面直接赋值会绕过清理，让编译期挡住）",
        re.search(r"var pickedContactId by mutableStateOf<Long\?>\(null\)\n\s*private set", order_vm) is not None,
        "声明处没有 `private set`",
    )
    c.ok(
        "挑人时记下「这一单的收货人是名册里的哪一位」（`pickedContactId = c.id` 全文件只有一处）",
        count(r"pickedContactId = c\.id", order_vm) == 1,
        f"{count(r'pickedContactId = c.id', order_vm)} 处 —— 多一处就可能写到别人头上",
    )
    c.ok(
        "手改「收货人名称」清掉 `pickedContactId`（换人 = 不许把这次的号写到上一位头上）",
        "pickedContactId = null" in fn_body(order_vm, "fun onReceiverNameChange("),
        "名称那一栏没清",
    )
    # ⚠️ 电话那一栏**必须不清**：清了它，"挑一个没号码的联系人 → 下单时补号 → 存回档案"
    #    这条链永远不会触发（模拟器 E2E 抓到的：联系人 42 下单成功后 phone 还是 NULL）。
    c.ok(
        "手改「收货人电话」**不清** `pickedContactId`（清了 = 补号写回档案永远不会触发）",
        "pickedContactId = null" not in fn_body(order_vm, "fun onReceiverPhoneChange("),
        "电话那一栏把 pickedContactId 清了 —— 这个功能就此失效",
    )
    c.ok(
        "三条**自动带出**收货人的来源清（预设单 / 线路 / 我的地点；加手改名称 1 处共 ≥ 4 处清空）",
        count(r"pickedContactId = null", order_vm) >= 4,
        f"只有 {count(r'pickedContactId = null', order_vm)} 处清空",
    )
    c.ok(
        "下单页那两栏改走 VM 的手改入口（`vm.onReceiverNameChange(` / `vm.onReceiverPhoneChange(`）",
        "vm.onReceiverNameChange(" in order_screen and "vm.onReceiverPhoneChange(" in order_screen,
        "界面还在直接写那两栏 —— 手改不会清 pickedContactId",
    )
    c.ok(
        "收货人两栏在 VM 外面**没有人**直接写（`dongjiaName =` / `dongjiaPhone =` 只许出现在 VM 里）",
        not [
            p.relative_to(AND).as_posix()
            for p in ui_files
            if p != ORDER_VM and count(r"\bdongjia(Name|Phone)\s*=[^=]", code(p))
        ],
        "界面上又出现直写 —— 手改不会清 pickedContactId",
    )

    # 12c. 写回档案：一处实现 + 三条守卫 + 只在成功之后
    write_body = fn_body(order_vm, "private suspend fun savePickedContactPhone(")
    c.ok(
        "写回只有一处实现、且是 `suspend`（它要发请求；改成普通 fun 编译不过）",
        count(r"private suspend fun savePickedContactPhone\(", order_vm) == 1 and len(write_body) >= BODY_FLOOR,
        f"定义 {order_vm.count('private suspend fun savePickedContactPhone(')} 处，体长 {len(write_body)}",
    )
    c.ok(
        "三条守卫都在：没挑人 / 这次没填 / 档案里本来就有号 → 都不写",
        "pickedContactId ?: return" in write_body
        and "if (newPhone.isEmpty()) return" in write_body
        and "if (archived.phone.isNotBlank()) return" in write_body,
        "缺守卫 —— 会给没挑人的单子乱写，或把别人填的号覆盖掉",
    )
    submit_body = fn_body(order_vm, "fun submit(")
    c.ok(
        "写回发生在**下单成功之后**（`savePickedContactPhone()` 排在 `onDone()` 前面）",
        "savePickedContactPhone()" in submit_body
        and -1 < submit_body.find("savePickedContactPhone()") < submit_body.find("onDone()"),
        "没调（补的号没人存）或调在了成功之外（单子没下成也动名册）",
    )

    # 12d. 服务端：列真的可空、空号不撞唯一索引、删/恢复不编假号码
    c.ok(
        "迁移 011 在（列的可空性只能走迁移，见 migrations/README.md 的分工）",
        BE_MIG.exists(),
        "文件不在",
    )
    mig_src = code(BE_MIG)
    c.ok(
        "迁移 011 的 VERSION / NAME 在册（版本号跳号或改名 = 线上 upgrade 会跳过它）",
        BE_MIG.exists() and "VERSION = 11" in mig_src and 'NAME = "contact_phone_optional"' in mig_src,
        "版本号 / 名字对不上（或文件不在）",
    )
    c.ok(
        "MySQL 那条路真的把列改成可空（`MODIFY COLUMN {COLUMN} VARCHAR(32) NULL`）",
        re.search(r"MODIFY COLUMN \{COLUMN\} VARCHAR\(32\) NULL", mig_src) is not None,
        "MySQL 上这一列还是 NOT NULL —— 两条「没填号」的联系人照样撞唯一索引",
    )
    c.ok(
        "SQLite 那条路走整表重建（SQLite 的 ALTER 不支持 MODIFY COLUMN）",
        "_sqlite_rebuild(engine)" in mig_src and "CREATE TABLE" in mig_src,
        "SQLite 上没有可走的路（本地/测试库 upgrade 直接报错）",
    )
    i_nullable = mig_src.find("if nullable:")
    c.ok(
        "迁移能重跑（列已经是可空就安静返回 —— migrations/README.md 的硬要求）",
        i_nullable >= 0 and "return" in mig_src[i_nullable : i_nullable + 200],
        "少了这条早退 —— 第二次 upgrade 会炸",
    )
    contact_cls = re.search(r"class ShipperContact\(([\s\S]*?)\n\n\n", model)
    contact_body = contact_cls.group(1) if contact_cls else ""
    c.ok(
        "抽出了 `ShipperContact` 的类体（≥ 300 字符 —— 抽取失效会让下面那条变成假绿）",
        len(contact_body) >= 300,
        f"只有 {len(contact_body)} 字符",
    )
    c.ok(
        "`shipper_contacts.phone` 可空（「没填」存 NULL —— 唯一索引里**空串是真值**，两条空串会撞键）",
        re.search(r"phone: Mapped\[str \| None\] = mapped_column\(String\(32\),[^\n]*nullable=True", contact_body)
        is not None,
        "这一列又是 NOT NULL 了",
    )
    c.ok(
        "空号判重走 `phone.is_(None)`（不是在比空串）",
        count(r"phone\.is_\(None\)", api) >= 1,
        "空号判重又按空串比 —— 两条「没填号」的联系人会互相当成同一条",
    )
    c.ok(
        "删除时**跳过**给空号编假号码（`if c.phone:` 守卫）",
        count(r"if c\.phone:", api) == 1,
        "没号的行走进了 del_suffix —— 往「电话」列写一个假号码",
    )
    c.ok(
        "恢复时不再对 NULL 调 `.endswith`（`(c.phone or \"\")`）",
        count(r'\(c\.phone or ""\)', api) >= 1,
        "没填号的那条恢复会 AttributeError → 500",
    )
    c.ok(
        "出参把 None 归一成空串（客户端的 `ContactDto.phone` 是非空 String）",
        re.search(r'@field_validator\("phone", mode="before"\)', schema) is not None,
        "ContactOut 少归一 —— Gson 会得到字面量 null",
    )
    c.ok(
        "`ContactCreate.phone` 有默认空串（不传 phone 也能建）",
        re.search(r'phone: ContactPhone = Field\(default=""', schema) is not None,
        "没默认值 = 不传 phone 直接 422",
    )
    opt_test = read(BE_TEST_OPT)
    c.ok(
        "回归用例在，且钉了「存 NULL 而不是空串」这条（≥ 7 个用例）",
        opt_test.count("def test_") >= 7 and "row.phone is None" in opt_test,
        f"用例 {opt_test.count('def test_')} 个；NULL 断言{'在' if 'row.phone is None' in opt_test else '不在'}",
    )

    # 12e. 「地址与联系人 → 联系人」抽屉是**另一处**电话输入（一个独立的 @Composable 表单，
    #      不是 ContactPickerSheet 那个弹层）：它的必填标记不归 12a 管 —— 12a 第 ④ 条只查两个 VM，
    #      第一轮就是在这里漏掉的（模拟器上看见「电话」还挂着红星）。
    i_cd = addr_screen.find("if (vm.showContactDialog)")
    j_cd = addr_screen.find("@Composable", i_cd) if i_cd >= 0 else -1
    contact_drawer = addr_screen[i_cd:j_cd] if i_cd >= 0 and j_cd > i_cd else ""
    c.ok(
        "抽出了联系人抽屉那一段（≥ 300 字符、且里面真有那两栏 —— 抽取失效会让下面那条假绿）",
        len(contact_drawer) >= 300
        and "vm.contactPhone" in contact_drawer
        and "InputRules.phoneInput(" in contact_drawer,
        f"只抽到 {len(contact_drawer)} 字符",
    )
    c.ok(
        "抽屉里的电话**没有**挂必填标记（required = true）—— 校验放开了，标记也得跟着放开",
        count(r"required = true", contact_drawer) == 0,
        "联系人抽屉的电话又挂上必填标记了：用户看到红星、其实能空着存（2026-10-03 模拟器上抓到的）",
    )
    c.ok(
        "抽屉里留着那句「为什么不能再挂必填」的注释（下一个人动这里之前能看见）",
        "别再挂 required = true" in read(ADDR_SCREEN),
        "注释被删了 —— 下一个人会把红星再加回来，而校验依然是放开的",
    )

    if "--list" in sys.argv:
        print()
        print("  == 它到底在查什么 ==")
        print("     · 唯一实现：fillReceiver / hasBoundContact / boundContactLabel / ContactPickerSheet")
        print("     · 两处消费：下单页与地址与联系人都用同一个弹层、都走 fillReceiver")
        print("     · 共享地点不绑人（applyPlace / PlaceDto / models/place.py 里都不许有 contact）")
        print("     · 快照串不是外键；编辑与 AI 改地点都必须回填（不回填 = 静默解绑）")
        print("     · 后端三件套（schema / API / schema_bootstrap 补列）+ 单测 + 反向验证")
        print("     · CHG-0010：手机号选填（弹层 required=false + 后端列可空存 NULL）")
        print("     · CHG-0010：pickedContactId 记住挑的是谁、手改**名称**才清（改电话不清）；下单成功后把补的号写回档案")
        print("     · CHG-0010：联系人抽屉（地址与联系人）的电话同样不许再挂必填标记")

    return c.report("联系人（可选 / 可绑在地点与线路上）")


if __name__ == "__main__":
    sys.exit(main())
