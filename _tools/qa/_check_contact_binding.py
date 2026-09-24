# -*- coding: utf-8 -*-
"""红线：**联系人可以被挑、也可以绑在「地点 / 线路」上**（2026-09-24 用户要求）。

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

    if "--list" in sys.argv:
        print()
        print("  == 它到底在查什么 ==")
        print("     · 唯一实现：fillReceiver / hasBoundContact / boundContactLabel / ContactPickerSheet")
        print("     · 两处消费：下单页与地址与联系人都用同一个弹层、都走 fillReceiver")
        print("     · 共享地点不绑人（applyPlace / PlaceDto / models/place.py 里都不许有 contact）")
        print("     · 快照串不是外键；编辑与 AI 改地点都必须回填（不回填 = 静默解绑）")
        print("     · 后端三件套（schema / API / schema_bootstrap 补列）+ 单测 + 反向验证")

    return c.report("联系人（可选 / 可绑在地点与线路上）")


if __name__ == "__main__":
    sys.exit(main())
