# -*- coding: utf-8 -*-
"""看得见的字（2026-10-04 BUG-0009）—— 机器判据。

## 这条是怎么来的

用户 2026-10-03 走查时指着地点卡上那张名字与地址都是六个问号的历史数据，要求
「查清楚写入端、修编码/校验兜底」，并提示「可能是关于 AI 的功能」。查下来的结论是：
库里存的**就是问号本身**（`shipper_locations` id=94 / `orders` id=426 的三个字段），
原文已经不可能还原；同一张表相邻两行是正常中文，我们自己的代码里没有任何
「把汉字换成问号」的实现 —— 是**写进来的那一刻就已经坏了**。所以只剩拦在入口一条路。

## 为什么必须有机器的判据

修法是一层入参闸（`app/core/text_guard.py` 判字符 + `app/schemas/text.py` 的
`ShowableModel` 负责"哪些字段过闸"）。它有三个**看不出来**的失败方式：

1. 谁把"只由问号组成"那条收紧成"含连续问号"，页面上不会报错，只会在用户填
   「门牌???」时把人拦住 —— 判据与用例都把**放行的边界**逐条钉住；
2. 谁把 `SHOWABLE_FIELDS` 写成普通类属性（不写 `ClassVar`），Pydantic 会把它当成
   一个**字段**（每个请求都要带一列 `showable_fields`），页面上的表现是"什么也没变"，
   而落库的请求里多了一串没人看的字段；
3. 谁把某个模型从 `ShowableModel` 的继承里摘掉、或在名单里打错一个字段名
   （`ensure_fields` 用 `getattr` 取值，取不到就按"没填"跳过）—— **闸静默失效**，
   下一次脏数据还是要等到用户在页面上看见六个问号才知道。

R4-BOUNDARY-JUSTIFICATION: **为什么代码边界解决不了这件事。**
（⛔ 标记里必须是**ASCII 冒号**：`_check_r3_constraints.py::probe_checker_budget` 认的是
`R3-BOUNDARY-JUSTIFICATION:` / `R4-BOUNDARY-JUSTIFICATION:` 这两个**逐字**字符串。）

「这一串字是不是能看的字」不是某一个类型的属性 —— 它是**一批自由文本字段共同的口径**：
每个 schema 各自看都合法（`max_length=512` 也满足、必填也满足），只有把
「判据的唯一实现」「名单挂在哪几个模型上」「名单里的名字是不是真字段」三件事放在一起看，
才知道这道闸是开着的还是空转的。类型标注挡不住"名单里少一个字段名"这一手：
它不报错、不抛异常，只是那个字段从此不再过闸。

**反向破坏用例**：`_tools/qa/_reverse_verify_unshowable_text_guard.py` 逐条把修复撤回
（问号集合漏掉全角、坏字符那条失效、`None` 被当成问号、名单里删掉 `address_detail`、
`_showable` 校验器改成空名单、`FIELD_CN` 少一个键、`ClassVar` 写掉、某个模型不再继承、
`identify_error` 里的 `text_guard.find` 拿掉、登记表 / 文档 / 用例改名……），
每条都要求判据或回归用例报红，跑完把被碰过的文件**逐字节**还原。

**静默空转保护**：本判据只读源码，锚点少一个就当场报红（`py_func` 切段失败 = 正文过短 = 红），
**不做**"找不到就跳过"的软处理；名单里的名字还逐条回到 schema 里核对是不是**真字段**。
不碰数据库、不发请求、不改任何文件；它管的是"这道闸有没有被悄悄关掉"。

用法：
    python _tools/qa/_check_unshowable_text_guard.py
    python _tools/qa/_check_unshowable_text_guard.py --list
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))

from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
GUARD = BACKEND / "app/core/text_guard.py"
TEXT = BACKEND / "app/schemas/text.py"
ORDER = BACKEND / "app/schemas/order.py"
SHIPPER = BACKEND / "app/schemas/shipper.py"
PLACE = BACKEND / "app/services/place_service.py"
VERR = BACKEND / "app/core/validation_errors.py"
KTEST = BACKEND / "tests/test_text_guard.py"
DOC = ROOT / "docs/changes/BUG-0009.md"
REGISTRY = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"

#: 断言"至少扫到这么多后端 .py"—— 防"一个文件都没扫到也算过"。
MIN_FILES = 200
#: 回归用例条数下界（实测 13 条；加用例可以，删用例必须同时把这里改小 —— 但请别改）。
MIN_CASES = 13
#: 过闸字段名总数下界（实测 29 个：订单 6+6、地址 4+4、地点 4+4、联系人 1+1）。
MIN_NAMES = 20
#: 改动文档的九节（`_check_dev_spec.py` 对 docs/changes/*.md 提的是同一件事）。
REQUIRED_PARTS = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨"]


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def py_code(src: str) -> str:
    """剥 Python 的散文（三引号块 + 整行 `#` 注释）：判据只许锚在代码上。

    ⚠️ 教训（BUG-0006 判据的第一条假阳性）：函数体里的一句注释把纯子串判断喂饱了。
    """
    out = re.sub(r'"""(?:.|\n)*?"""', "", src)
    out = re.sub(r"'''(?:.|\n)*?'''", "", out)
    return "\n".join(ln for ln in out.splitlines() if not ln.strip().startswith("#"))


def py_func(src: str, name: str) -> str:
    """取一个**顶层**函数的正文：从 `def name(` 到下一个顶格的 def/class/@ 或文件末。"""
    i = src.find(f"def {name}(")
    if i < 0:
        return ""
    m = re.search(r"(?m)^(?=def |class |@)", src[i + 1 :])
    return src[i : i + 1 + (m.start() if m else len(src) - i - 1)]


def showable_names(src: str) -> list[str]:
    """把一份 schema 里所有 `SHOWABLE_FIELDS = (…)` 的字段名抠出来（按出现顺序）。"""
    names: list[str] = []
    for m in re.finditer(r"SHOWABLE_FIELDS = \(([^)]*)\)", src):
        names += re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"', m.group(1))
    return names


def class_names(src: str, cls: str) -> list[str]:
    """只抠**某一个类**自己那段 `SHOWABLE_FIELDS = (…)` 里的字段名。

    按类抠是必须的：一份文件里好几个模型各挂一份名单，只看「全文件出现过」
    会把「某一个模型的名单被摘掉一项」当成没发生。
    """
    m = re.search(r"(?ms)^class %s\b.*?(?=^class |\Z)" % re.escape(cls), src)
    if not m:
        return []
    return [
        n
        for block in re.findall(r"SHOWABLE_FIELDS = \(([^)]*)\)", m.group(0))
        for n in re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"', block)
    ]


def missing_fields(src: str) -> list[str]:
    """名单里写了、但本文件里**没有这个字段**（`getattr` 会让打错的名字静默跳过）。"""
    return [n for n in showable_names(src) if f"\n    {n}:" not in src]


class Checker:
    def __init__(self) -> None:
        self.fails = 0
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print(f"  [OK]   {label}")
        else:
            self.fails += 1
            print(f"  [FAIL] {label}" + (f"\n         → {detail}" if detail else ""))

    def report(self, title: str) -> int:
        print()
        print(f"===== {title} =====")
        print(f"  通过 {self.passes} 项，失败 {self.fails} 项")
        return 1 if self.fails else 0


def section(title: str) -> None:
    print()
    print(f"-- {title} --")


def main() -> int:
    if refuse_if_injecting("看得见的字（BUG-0009）的检查"):
        return 1

    c = Checker()
    guard_raw = read(GUARD)
    guard = py_code(guard_raw)
    text = py_code(read(TEXT))
    order = py_code(read(ORDER))
    shipper = py_code(read(SHIPPER))
    place = py_code(read(PLACE))
    verr = py_code(read(VERR))
    ktest = py_code(read(KTEST))
    doc = read(DOC)
    registry = read(REGISTRY)
    claim = read(CLAIM)

    find = py_func(guard, "find")
    ensure = py_func(guard, "ensure")
    ensure_fields = py_func(guard, "ensure_fields")
    label = py_func(guard, "_label")
    identify = py_func(py_code(read(PLACE)), "identify_error")

    py_files = list(BACKEND.rglob("*.py"))

    section("零、现场")
    c.ok(
        f"扫到 {len(py_files)} 个后端 .py（下界 {MIN_FILES}）",
        len(py_files) >= MIN_FILES,
        "一个文件都没扫到的时候，下面每一条都会「看起来」通过",
    )
    c.ok(
        f"text_guard.py 读到了（正文 {len(guard)} 字符）",
        len(guard) > 400,
        "正文过短 = 文件被清空或路径变了",
    )
    for name, src in (
        ("schemas/text.py", text),
        ("schemas/order.py", order),
        ("schemas/shipper.py", shipper),
        ("services/place_service.py", place),
        ("core/validation_errors.py", verr),
        ("tests/test_text_guard.py", ktest),
    ):
        c.ok(f"{name} 读到了", bool(src.strip()))
    for name, body in (
        ("find", find),
        ("ensure", ensure),
        ("ensure_fields", ensure_fields),
        ("_label", label),
        ("identify_error", identify),
    ):
        c.ok(
            f"取到了 {name} 的正文（{len(body)} 字符）",
            len(body) > 60,
            "py_func 切段失败 = 红：不做「找不到就跳过」的软处理",
        )

    section("一、判据只有一处实现（app/core/text_guard.py）")
    c.ok("坏字符用了编译好的正则", "_BAD_CHARS = re.compile(" in guard)
    m = re.search(r'_BAD_CHARS = re\.compile\("([^"]*)"\)', guard)
    pat = m.group(1) if m else ""
    c.ok("替换符 U+FFFD 在模式里（解码失败留下的那一个）", "\\ufffd" in pat, f"模式 = {pat[:60]}")
    c.ok("孤立代理项 U+D800-U+DFFF 在模式里（写库或序列化时才炸）", "\\ud800-\\udfff" in pat)
    c.ok(
        "C0/C1 控制字符四段齐全（\\u0000-\\u0008 / \\u000b\\u000c / \\u000e-\\u001f / \\u007f-\\u009f）",
        all(x in pat for x in ("\\u0000-\\u0008", "\\u000b\\u000c", "\\u000e-\\u001f", "\\u007f-\\u009f")),
        f"模式 = {pat[:60]}",
    )
    c.ok("问号形态半角与全角都在（`?` = 编码坏掉的默认替换符，`？` = 中文输入法手打的占位）", '_QUESTION_MARKS = "?？"' in guard)
    c.ok("find 的签名与返回（能给用户那句话，也能说「能看」）", "-> str | None" in find and "def find(value: str | None, field: str) -> str | None:" in guard)
    c.ok("「没填」直接放行（None / 空串不在这里判必填）", "if not text:" in find and "return None" in find)
    c.ok("去掉首尾空白之后再看是不是只剩问号", "stripped = text.strip()" in find)
    c.ok(
        "只有问号那条的写法（半角/全角/夹空白都算）",
        "all(ch in _QUESTION_MARKS or ch.isspace() for ch in stripped)" in find,
        "收紧成「含连续问号」会拒掉真实表达（门牌???）",
    )
    c.ok(
        "先判坏字符、再判整串问号（顺序不能反：坏字符那句话更准）",
        find.find("_BAD_CHARS.search(text)") >= 0
        and find.find("_BAD_CHARS.search(text)") < find.find("stripped = text.strip()"),
    )
    m1 = re.search(r'BAD_CHAR_TEXT = "([^"]*)"', guard)
    m2 = re.search(r'ONLY_MARKS_TEXT = "([^"]*)"', guard)
    c.ok(
        "两句文案是模块级常量、都留了 {field} 占位（字段中文名由 FIELD_CN 填）",
        bool(m1) and bool(m2) and "{field}" in m1.group(1) and "{field}" in m2.group(1),
        "内联字符串会让 `--list` 与文案用例对不上",
    )
    c.ok(
        "_label 复用 validation_errors.FIELD_CN（不抄第二份字段中文名）",
        "from app.core.validation_errors import FIELD_CN" in guard and "FIELD_CN.get(field, field)" in label,
        "查不到就退回字段名本身（不猜）",
    )
    c.ok("ensure 抛的就是那句话（422 的 detail 直接是它）", "err = find(value, field)" in ensure and "raise ValueError(err)" in ensure)
    c.ok(
        "ensure_fields 按名单逐条过闸，取不到的属性按「没填」跳过",
        "for name in fields:" in ensure_fields and "getattr(obj, name, None)" in ensure_fields,
    )
    c.ok(
        "docstring 写明了**不判**什么（正常文字里夹问号：门牌???）",
        "门牌???" in guard_raw,
        "边界不写下来，下一轮「顺手加严」就会误伤真实表达",
    )
    c.ok(
        "docstring 写明长度与空白归别处（_clean / max_length）",
        "max_length" in guard_raw and "_clean" in guard_raw,
    )
    c.ok(
        "docstring 记着这条是怎么来的（shipper_locations id=94 / orders id=426 的现场）",
        "shipper_locations" in guard_raw and "id=94" in guard_raw and "id=426" in guard_raw,
    )

    section("二、闸挂在哪几个字段上（名单 = 覆盖面）")
    c.ok("混入类 ShowableModel 在（子类声明名单就自动过闸）", "class ShowableModel(BaseModel):" in text)
    c.ok(
        "SHOWABLE_FIELDS 写成 ClassVar（不写的话 Pydantic 会把它当成一个字段）",
        "SHOWABLE_FIELDS: ClassVar[tuple[str, ...]] = ()" in text,
        "写成普通属性 = 每个请求都要带一列 showable_fields，而它根本不进数据库",
    )
    c.ok(
        "校验器是 model_validator(mode=\"after\") 且调 text_guard.ensure_fields",
        '@model_validator(mode="after")' in text
        and "text_guard.ensure_fields(self, type(self).SHOWABLE_FIELDS)" in text,
    )
    c.ok("text.py 自己 import 了 text_guard（判据不在这一层重写）", "from app.core import text_guard" in text)
    c.ok("混入按**子类自己**声明的名单走（type(self)，不是基类的空名单）", "type(self).SHOWABLE_FIELDS" in text)

    ON = ("delivery_description", "address_detail", "contact_dongjia_name", "contact_boss_name")
    o_names = showable_names(order)
    s_names = showable_names(shipper)
    c.ok("OrderCreate 继承混入", "class OrderCreate(ShowableModel, GeoInput):" in order)
    c.ok("OrderUpdate 继承混入（改单那条路也挂上）", "class OrderUpdate(ShowableModel, GeoInput):" in order)
    c.ok(
        "地址（线路）建与改都继承混入",
        "class AddressCreate(ShowableModel, GeoInput):" in shipper
        and "class AddressUpdate(ShowableModel, GeoInput):" in shipper,
    )
    c.ok(
        "地点（就是出脏数据的那张表）建与改都继承混入",
        "class LocationCreate(ShowableModel, GeoInput):" in shipper
        and "class LocationUpdate(ShowableModel, GeoInput):" in shipper,
    )
    c.ok(
        "联系人建与改都继承混入",
        "class ContactCreate(ShowableModel):" in shipper
        and "class ContactUpdate(ShowableModel):" in shipper,
    )
    #: 每个模型**自己**那份名单必须含哪些字段（按类抠：只看「全文件出现过」会漏掉摘项）。
    EXPECT = (
        ("OrderCreate", order, ON, "送货地址 / 送货说明 / 收货人姓名 / 下单人姓名"),
        ("OrderUpdate", order, ON, "送货地址 / 送货说明 / 收货人姓名 / 下单人姓名"),
        ("AddressCreate", shipper, ("receiver_name", "detail_address", "origin_address"), "收货人 / 详细地址 / 发货地址"),
        ("AddressUpdate", shipper, ("receiver_name", "detail_address", "origin_address"), "收货人 / 详细地址 / 发货地址"),
        ("LocationCreate", shipper, ("name", "detail_address", "contact_name"), "名称 / 详细地址 / 联系人姓名"),
        ("LocationUpdate", shipper, ("name", "detail_address", "contact_name"), "名称 / 详细地址 / 联系人姓名"),
        ("ContactCreate", shipper, ("display_name",), "显示名"),
        ("ContactUpdate", shipper, ("display_name",), "显示名"),
    )
    for cls, src, need, cn in EXPECT:
        mine = class_names(src, cls)
        c.ok(
            f"{cls} 自己那份名单含 {cn}",
            all(n in mine for n in need),
            f"实测 {cls} 名单 = " + "、".join(mine),
        )
    six = re.findall(r"class (?:Address|Location|Contact)(?:Create|Update)\(ShowableModel[,)]", shipper)
    c.ok(
        f"shipper.py 里六个建改模型**全部**继承了混入（实测 {len(six)} 个）",
        len(six) == 6,
        "摘掉任何一个 = 那条路不再过闸，而页面上什么也不会变",
    )
    all_names = o_names + s_names
    c.ok(
        f"名单里一共 {len(all_names)} 个字段名（下界 {MIN_NAMES}）",
        len(all_names) >= MIN_NAMES,
        "、".join(all_names),
    )
    bad_names = missing_fields(order) + missing_fields(shipper)
    c.ok(
        "名单里的每个名字在各自 schema 里都是**真字段**（打错一个字就静默失效）",
        not bad_names,
        "名单里写了但文件里没有：" + "、".join(bad_names[:5]),
    )
    c.ok(
        "place_service.identify_error 里走同一道闸（共享地点库：建与改共用一句话）",
        "text_guard.find(value, field)" in identify and "from app.core import text_guard" in place,
    )
    c.ok(
        "find 的循环在「名称与地址不能都是空」那句判词**之前**",
        identify.find("text_guard.find(value, field)") >= 0
        and identify.find("text_guard.find(value, field)") < identify.find("NO_NAME_TEXT"),
        "顺序反了：一串问号会先撞上必填判词，用户看到的是另一句话",
    )
    c.ok(
        "FIELD_CN 补齐三个字段的中文名（提示里说的是「收货人姓名」不是英文 key）",
        '"contact_name": "联系人姓名",' in verr
        and '"contact_dongjia_name": "收货人姓名",' in verr
        and '"contact_boss_name": "下单人姓名",' in verr,
        "缺一个键，那一格就会把英文 key 直接端到用户眼前",
    )

    section("三、回归测试钉住了行为")
    cases = re.findall(r"(?m)^def (test_\w+)\(", ktest)
    c.ok(f"回归用例 {len(cases)} 条（下界 {MIN_CASES}）", len(cases) >= MIN_CASES, "、".join(cases))
    c.ok(
        "用例点到四件事：只有问号 / 夹问号放行 / 看不见的字符 / 空白放行",
        all(k in ktest for k in ("只有问号", "门牌???", "看不见的字符", r"a\tb")),
        "边界与判据一样重要：只钉「拦什么」会漏掉「误伤什么」",
    )
    c.ok(
        "用例覆盖四条写入路径（我的地点 / 订单 / 共享地点库 / 线路与联系人）",
        all(p in ktest for p in ("/api/v1/shipper/locations", "/api/v1/orders", "/api/v1/places", "/api/v1/shipper/addresses", "/api/v1/shipper/contacts")),
    )
    c.ok(
        "用例有正常值的正对照（闸不许把正常下单也堵上）",
        "assert ok.status_code == 201" in ktest,
    )
    c.ok(
        "422 与 400 两条路都验了（建单走 Pydantic，改共享地址走服务层的 ValueError）",
        "status_code == 422" in ktest and "status_code == 400" in ktest,
    )
    c.ok(
        "用例断言「被拦下来的那次一行都没落库」",
        "len(after) == len(before)" in ktest,
        "只看状态码的话，「拦了但已经写进去」也会过",
    )
    c.ok(
        "用例专门钉住历史脏行不被误伤（闸只看这次送上来的值）",
        "test_dirty_row_can_still_be_edited_field_by_field" in ktest
        and 'json={"remark": "改个备注"}' in ktest,
        "否则「改个电话」也要先把库里的问号改掉，用户当场无路可走",
    )

    section("四、文档与登记")
    c.ok("改动文档在（docs/changes/BUG-0009.md）", "BUG-0009" in doc and "text_guard" in doc, "文件不存在或缺关键词")
    c.ok(
        "文档写清了根因与修法（写进来时就已经是问号 → 只剩拦在入口）",
        "ShowableModel" in doc and "问号" in doc and "拦在入口" in doc,
    )
    missing_parts = [p for p in REQUIRED_PARTS if p not in doc]
    c.ok("改动文档九节齐全（①–⑨）", not missing_parts, "缺：" + "、".join(missing_parts))
    c.ok(
        "文档写明历史脏数据（id=94）要经用户确认再清",
        "id=94" in doc and "用户" in doc,
        "上一次（E2E 报告 §5.1）判的就是「不修」，删数据不能顺手做",
    )
    c.ok("改动登记表里有 BUG-0009 行", "| `BUG-0009` |" in registry, "docs/changes/README.md")
    c.ok("认领簿里有 BUG-0009 的块", "BUG-0009" in claim)

    if "--list" in sys.argv:
        print()
        print("  == 它到底在查什么 ==")
        print("  · 判据只有一处：`app/core/text_guard.py` 判坏字符（U+FFFD / 孤立代理项 / C0·C1）与「整串只有问号」，文案、字段中文名、边界都写在那里；")
        print("  · 名单 = 覆盖面：`ShowableModel` 管「哪些字段过闸」，订单 / 地址 / 地点 / 联系人四类建改模型都挂着，名单里的名字必须是真的字段；")
        print("  · 共享地点库走 `place_service.identify_error`（建与改同一句话），`FIELD_CN` 补齐中文名；")
        print("  · 回归用例 ≥12 条：拦什么、放行什么、四条写入路径、422 与 400、被拦当场不落库、历史脏行不被误伤；")
        print("  · 改动文档 + 登记表 + 认领簿都在，历史脏数据清理写明要经用户确认。")

    return c.report("看得见的字（BUG-0009）")


if __name__ == "__main__":
    sys.exit(main())


