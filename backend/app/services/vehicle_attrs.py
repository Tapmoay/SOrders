"""车辆属性的**唯一一份判据**：车身型式 → 这辆车有哪些属性、每项叫什么、合法范围是多少。

## 用户要的是什么（2026-09-27 原话）

> 「可以给一辆车**固定一个属性**。因为他不是有对应的车子吗，还有车牌，其实给这辆车固定属性，
>  他的属性是不是**不可能变**；也就是说，在**创建车辆的时候就需要填相应的属性**。
>  **不同的车型会需要填的属性是不同的**……别说有可能是个**平板车**、有可能是一个**自卸车**。」
>
> 「（车辆属性）**是要算钱的**。不过主要的一些是不会算的，主要的是**吨和方**这种即便（计量）单位……
>  我们在计算的时候**可以直接拉取这些属性，然后直接进行单位换算**。」

属性清单本身是需求方 2026-09-27 深夜逐条批准过的（「**属性清单可以啊，就可以就这样子**」）。

## ⛔ 为什么另起一个「车身型式」，而不是扩 `vehicles.vehicle_type`

`vehicles.vehicle_type`（小货车 / 大货车 / 挂车）回答的不是「这辆车长什么样」，
而是「**这辆车按什么算钱**」。同一套取值被五处共用：

| 落点 | 它在那儿管什么 |
|---|---|
| `api/v1/vehicles.py::_clean_type` | 车辆台账自己的校验 |
| `api/v1/driver_billing_rules.py::_VEHICLE_CN` | 司机计费规则的「适用车型」 |
| `api/v1/freight_templates.py::_VALID_VEHICLE` | 运费模板的「适用车型」 |
| `services/driver_pay.py::_VEHICLE_TYPES` | 司机应付的取数口径 |
| `models/user.py::resolve_billing_mode` | **trailer → 按单计费、其余 → 固定工资** —— 这一行是**钱** |

往里塞 `box` / `flat` / `dump`，等于问「箱式车按什么算钱」——而这个问题**从来没有人回答过**，
回答错了也不会报错，只会让某些司机从固定工资悄悄变成按单计费（规范 §三十三 第④条：
同一个业务事实出现两个 Owner 时就该停下来重设计）。

所以本模块把两件事**分开**：

* **车型**（`vehicles.vehicle_type`，原样不动）＝ 怎么算钱；
* **车身型式**（`vehicles.body_type`，本模块新增）＝ 这辆车能填哪些属性。

界面上一个是「车型」chips，一个是「车身型式」chips，提示语各写各的用途。

## 为什么吨 / 方对**每一种型式**都开放（本事项对批准清单的唯一一处解释性扩大）

需求方给的清单里，`载重(吨)` 只写在平板车 / 自卸车 / 挂车下面，`容积(方)` 只写在箱式车 /
自卸车 / 挂车下面。但同一段话里他也说了「**主要的是吨和方这种计量单位**」——
这两个是**任何一辆货车都有**的容量事实，缺了它「一车 = 多少方 / 多少吨」就没有依据
（而那正是他要这些属性去干的事）。

所以本模块把 `载重` / `容积` 放进**通用**那一档（对所有型式开放，仍然**选填**），
其余（车厢 / 台面 / 车斗的尺寸、轴数）严格按他给的那张表**按型式区分**。
⛔ 这是「多给一个选填框」，不是「改口径」：一个字节的钱都不在这里算。

## 这个模块**不做**什么

* ⛔ 不参与任何金额计算，也不接进单位换算的消费点。需求方的原话是「计算的时候可以直接拉取
  这些属性，然后直接进行单位换算」——那一步要先回答「**这一单算哪辆车**」（订单上没有车辆，
  车辆挂在司机名下），是一个独立的、会穿孔到下单/显示四个消费点的改动，
  因此单独立案（见 `docs/changes/` 里 FEAT-0001 的「留给下一件事」一节）。
* ⛔ 不 import ORM：判据要能在**没有数据库**的情况下逐条单测
  （`backend/tests/test_vehicle_attrs.py`），所以只做纯函数，取数据由 API 层喂进来。
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

# ---------------------------------------------------------------- 车身型式

BODY_NONE = ""
BODY_BOX = "box"
BODY_FLAT = "flat"
BODY_DUMP = "dump"
BODY_TRAILER = "trailer"

#: 型式 → 中文名。**只有这一份**：错误文案、审计日志、接口出参都从它取。
#: ⚠️ Android 侧 `VehicleManageScreen.kt` 里有一份**镜像**（界面要离线画 chips）——
#:    两份不一致时 `_tools/qa/_check_vehicle_attrs.py` 会报红，别只改一边。
BODY_LABELS: dict[str, str] = {
    BODY_NONE: "未设置",
    BODY_BOX: "箱式车",
    BODY_FLAT: "平板车",
    BODY_DUMP: "自卸车",
    BODY_TRAILER: "挂车",
}

#: 界面上 chips 的顺序（常见车型在前，「未设置」垫底）。
BODY_CHOICES: tuple[str, ...] = (BODY_BOX, BODY_FLAT, BODY_DUMP, BODY_TRAILER, BODY_NONE)

#: 合法的全部取值（校验用；含「未设置」——它是老库与新车的正式缺省，不是错误）。
BODY_TYPES: tuple[str, ...] = (BODY_NONE, BODY_BOX, BODY_FLAT, BODY_DUMP, BODY_TRAILER)

# ---------------------------------------------------------------- 字段规格

#: 所有型式都能填的属性（含「未设置」）——「不管什么车都有」的那几项。
_ALL = BODY_TYPES
#: 有货厢（车厢 / 台面 / 车斗）的型式。
_HAS_BED = (BODY_BOX, BODY_FLAT, BODY_DUMP)
#: 货厢有**高度**的型式（平板车没有「台面高」——那是需求方清单里就没有的一项）。
_HAS_BED_HEIGHT = (BODY_BOX, BODY_DUMP)


@dataclass(frozen=True)
class AttrField:
    """一项车辆属性：它在库里是哪一列、叫什么、量纲是什么、什么范围、哪些型式能填。"""

    #: 接口上的键（也是数据库列名——**一列一个事实，不合并、不复制**）
    key: str
    #: 通用中文名（错误文案用；界面上按型式可能有别的叫法，见 [label_of]）
    label: str
    #: 量纲（"米" / "吨" / "方" / "个"）——写在界面上，避免"车高填了 4 还是 400"
    unit: str
    #: 上限（含）。下限恒为「> 0」，写在 [parse_attrs] 里，不在这里重复一遍。
    max_value: Decimal
    #: 必须是整数（目前只有轴数）
    integer: bool
    #: 哪些型式能填它
    bodies: tuple[str, ...]
    #: 按型式换叫法（缺省用 [label]）。例：`cargo_length_m` 在箱式车叫「车厢长」、自卸车叫「车斗长」——
    #:  **同一个事实**（载货区长），只是不同车叫法不同；拆成三列会让"这辆车载货区多长"有三个 Owner。
    per_body: dict[str, str] = dc_field(default_factory=dict)


def _d(text: str) -> Decimal:
    return Decimal(text)


#: ⭐ **属性表的唯一一份**。改这里就是改"一辆车能填哪些属性"。
#:
#: 上限不是"业务规矩"，是**防手滑**：车高填 400（厘米当米填了）在界面上看不出来，
#: 而它会一路进到"一车 = 多少方"的换算里。宁可当场拒绝并给一句中文，也不要存一个荒谬的数。
FIELDS: tuple[AttrField, ...] = (
    AttrField("height_m", "车高", "米", _d("10"), False, _ALL),
    AttrField("width_m", "车宽", "米", _d("10"), False, _ALL),
    AttrField("curb_weight_t", "净重", "吨", _d("200"), False, _ALL),
    # ⭐ 这两项是**要参与换算**的（需求方：「主要的是吨和方这种计量单位」）
    AttrField("load_tons", "载重", "吨", _d("200"), False, _ALL),
    AttrField(
        "volume_cubic", "容积", "方", _d("500"), False, _ALL,
        per_body={BODY_DUMP: "斗容"},   # 自卸车的"容积"就是它车斗的容量，用户嘴里的词是"斗容"
    ),
    AttrField(
        "cargo_length_m", "货厢长", "米", _d("50"), False, _HAS_BED,
        per_body={BODY_BOX: "车厢长", BODY_FLAT: "台面长", BODY_DUMP: "车斗长"},
    ),
    AttrField(
        "cargo_width_m", "货厢宽", "米", _d("10"), False, _HAS_BED,
        per_body={BODY_BOX: "车厢宽", BODY_FLAT: "台面宽", BODY_DUMP: "车斗宽"},
    ),
    AttrField(
        "cargo_height_m", "货厢高", "米", _d("10"), False, _HAS_BED_HEIGHT,
        per_body={BODY_BOX: "车厢高", BODY_DUMP: "车斗高"},
    ),
    AttrField("axle_count", "轴数", "个", _d("10"), True, (BODY_TRAILER,)),
)

#: 键 → 规格。判据与 API 都从这里取，**没有第二份 when/if**。
FIELDS_BY_KEY: dict[str, AttrField] = {f.key: f for f in FIELDS}

#: 全部属性的键（顺序即界面顺序）。
ATTR_KEYS: tuple[str, ...] = tuple(f.key for f in FIELDS)

#: ⭐ **参与换算**的那两项（吨 / 方）。列在这里是给判据与下一件事（FEAT-0005）一个明确的锚：
#: 「哪些属性是钱相关的」不靠读注释猜。
CAPACITY_KEYS: tuple[str, ...] = ("load_tons", "volume_cubic")

#: 小数位：与列宽 `NUMERIC(…,3)` 一致。换算率那边是 4 位（`Numeric(14,4)`），
#: 这里 3 位够（毫米级；车长 12.345 米已经比卷尺准）。
_QUANT = Decimal("0.001")


# ---------------------------------------------------------------- 纯函数


def format_value(value: Decimal) -> str:
    """属性值怎么显示 / 怎么出参：去掉末尾多余的 0（`8.000` → `8`，`12.500` → `12.5`）。

    与单位换算那边 `services/unit_conversion.py::format_factor` **同一个口径**
    （设计系统 §4.1.1：末尾多余的 0 一律去掉）。不复用那个函数是因为它的注释里
    写死了"那是换算率"，把车的属性接上去会让那句话变成假的。
    """
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def body_label(raw: str | None) -> str:
    """车身型式 → 中文名。认不出的取值**原样返回**（不编一个名字出来）。"""
    key = (raw or "").strip()
    return BODY_LABELS.get(key, key)


def clean_body(raw: str | None) -> str:
    """校验车身型式，返回归一的取值；不合法就抛一句**能照着改的中文**。

    `None` / 空串 = 「未设置」——它是**正式取值**（老库里的车、以及"我还不知道这车是什么型式"），
    不是错误。⛔ 不许在这里给它兜一个 `box` 之类的默认值：那等于替用户认了一辆车的型式。
    """
    key = (raw or "").strip()
    if key not in BODY_TYPES:
        allowed = " / ".join(BODY_LABELS[b] for b in BODY_CHOICES if b)
        raise ValueError(f"车身型式只能是：{allowed}（或者不填 = 未设置）")
    return key


def fields_for(body: str | None) -> tuple[AttrField, ...]:
    """这个型式**能填**哪些属性（顺序即界面顺序）。未设置 = 只有通用那几项。"""
    key = (body or "").strip()
    return tuple(f for f in FIELDS if key in f.bodies)


def label_of(f: AttrField, body: str | None) -> str:
    """这一项在**这种车**上叫什么（箱式车的 `cargo_length_m` 叫「车厢长」）。"""
    return f.per_body.get((body or "").strip(), f.label)


def title_of(f: AttrField, body: str | None) -> str:
    """带量纲的完整叫法：「载重(吨)」。界面的输入框标题、错误文案都用它。"""
    return f"{label_of(f, body)}({f.unit})"


def _parse_number(f: AttrField, body: str | None, raw: object) -> Decimal:
    """把用户填的一个格子变成 Decimal；不合法就抛中文（带上这一项在这辆车上的叫法）。"""
    title = title_of(f, body)
    try:
        value = raw if isinstance(raw, Decimal) else Decimal(str(raw).strip())
    except (InvalidOperation, ArithmeticError, ValueError):
        raise ValueError(f"「{title}」不是数字（只填数字，不要带单位）") from None
    if not value.is_finite():
        raise ValueError(f"「{title}」不是数字（只填数字，不要带单位）")
    value = value.quantize(_QUANT, rounding=ROUND_HALF_UP)
    if value <= 0:
        raise ValueError(f"「{title}」必须大于 0（一辆 0 米长的车不是一个正经台账）")
    if value > f.max_value:
        raise ValueError(
            f"「{title}」太大了（上限 {format_value(f.max_value)}{f.unit}）—— 是不是单位填错了？"
        )
    if f.integer and value != value.to_integral_value():
        raise ValueError(f"「{title}」要填整数（{format_value(value)} 个轴不对）")
    return value


def parse_attrs(body: str | None, raw: dict | None) -> dict[str, Decimal]:
    """校验一份属性，返回**只含填了的那些**的 `{键: Decimal}`。

    四条判据（每一条都对应一种"存进去就再也说不清"的东西）：

    | 判据 | 不判的后果 |
    |---|---|
    | 键必须认识 | 打错一个字母（`load_ton`）会变成一条**永远读不出来**的属性，而界面上什么都不显示 |
    | 这一项必须属于这个型式 | 给平板车存一个"车厢高"，两边的叫法从此对不上（界面上也永远填不出来） |
    | 必须是 > 0 的数 | `0` 与空在界面上长得一样，但 `0` 会让"一车 = 0 方"看起来像个正经结果 |
    | 不许超过上限 | 厘米当米填（车高 400）在界面上看不出来，却会一路进到换算里 |

    ⛔ 空值（`None` / 空串 / 纯空格）**不算填了**：调用方可以整份传过来，
    没填的那几项自然就是"没这一项"，不需要客户端自己先筛一遍。
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("车辆属性要按「属性名: 数值」的形式传")
    key_body = (body or "").strip()
    out: dict[str, Decimal] = {}
    for key, value in raw.items():
        name = str(key).strip()
        f = FIELDS_BY_KEY.get(name)
        if f is None:
            raise ValueError(
                f"不认识的车辆属性「{name}」（可填的是：{'、'.join(ATTR_KEYS)}）"
            )
        if isinstance(value, str) and not value.strip():
            continue
        if value is None:
            continue
        if key_body not in f.bodies:
            who = " / ".join(BODY_LABELS[b] for b in f.bodies if b)
            raise ValueError(
                f"「{title_of(f, key_body)}」不是{BODY_LABELS.get(key_body, key_body) or '未设置'}的属性"
                f"（这一项只有 {who} 才有）"
            )
        out[name] = _parse_number(f, key_body, value)
    return out


def attrs_of(vehicle: object) -> dict[str, str]:
    """把一辆车（ORM 对象或任何带这些字段的东西）读成出参要的 `{键: 字符串}`。

    ⛔ 只回**填过的**那些：没填的属性回一个 `null` 或 `0`，界面上就会画出一个"系统说是 0"的数。
    没有就是没有 —— 与单位换算那边「宁可拒绝，也不猜」同一条规矩。
    """
    out: dict[str, str] = {}
    for f in FIELDS:
        raw = getattr(vehicle, f.key, None)
        if raw is None:
            continue
        value = raw if isinstance(raw, Decimal) else Decimal(str(raw))
        out[f.key] = format_value(value)
    return out


def apply_attrs(vehicle: object, values: dict[str, Decimal]) -> None:
    """把一份**已经校验过**的属性写到车上（整份替换：没在 [values] 里的列一律清空）。

    ⚠️ 为什么是"整份替换"而不是"逐项改"：需求方要的是「**属性不可能变**」——
    改就是一次说清"这辆车现在是什么样"，而不是让两次改动之间留一个谁也说不清的状态。
    客户端（安卓 `explicitNulls = false`）也正好发不出"显式 null"，
    整份替换把"清空某一项"表达成"不带这一项"，不需要额外协议。
    """
    for f in FIELDS:
        setattr(vehicle, f.key, values.get(f.key))


__all__ = [
    "ATTR_KEYS",
    "BODY_BOX",
    "BODY_CHOICES",
    "BODY_DUMP",
    "BODY_FLAT",
    "BODY_LABELS",
    "BODY_NONE",
    "BODY_TRAILER",
    "BODY_TYPES",
    "CAPACITY_KEYS",
    "FIELDS",
    "FIELDS_BY_KEY",
    "AttrField",
    "apply_attrs",
    "attrs_of",
    "body_label",
    "clean_body",
    "fields_for",
    "format_value",
    "label_of",
    "parse_attrs",
    "title_of",
]
