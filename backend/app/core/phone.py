"""电话格式：**唯一实现处**（schema 只标注类型别名，不许自己再写一遍规则）。

## 为什么要有这条规则（生产库实证，2026-09-19）
用户反馈的原话是「电话号码只能填数字，而且必须填正确的格式，不能填字母和文字」。
查生产库，这不是"理论上可能"：

- `orders.contact_dongjia_phone` 里真的有 `[嘿嘿] [嘻嘻] [问问] [刚刚好]` 这样的**中文**值；
- `shipper_contacts` 里有一条 `[222]`。

也就是说这些列当时接受任何文本。真实后果不是"数据不干净"，而是**司机拿着单打不了电话**：
派单端把这一列当"货主电话"显示与拨号，值不是号码时电话打不出去，而单子已经派出去了
—— 只能靠人再问一遍、再改一遍。

改之前全项目唯一有约束的电话字段是建账号用的 `UserCreate.phone`（`^1\\d{10}$`），
其余电话字段一律是 `max_length=32` 的自由文本。规则一旦散在十几个 schema 里必然走散
（改一处漏三处，而且漏掉的那几处不报错），所以两条规则都收在这里。

## 两条规则**故意不合并**（用途不同，合法取值集合就不同）

| 用途 | 规则 | 谁在用 |
|---|---|---|
| **手机号**（= 登录账号） | `^1\\d{10}$`（11 位数字且以 1 开头） | `UserCreate.phone` / `UserUpdate.phone` |
| **联系电话**（收货人/下单人/联系人/挂账单位/客户） | 去首尾空格后**全是数字**，**7~12 位** | 订单两个联系电话、地址、联系人、挂账单位、客户档案 |

⚠️ 联系电话**故意不要求**"11 位就必须以 1 开头"：`01012345678`（北京座机 010 + 8 位）
是合法的 11 位电话号码，加上"1 开头"会把它挡在门外 —— 而座机在收货人、挂账单位里很常见。
**"手机号"与"能打通的号码"是两件事**，混成一条规则的代价就是把座机挡掉。

⚠️ 上限取 **12** 是为了容纳 `057188888888`（区号 0571 + 8 位 = 12 位）；下限取 **7**
是因为 7 位短号真实存在。两头都不能再收紧（收紧一次就少一批真号码，而用户只会看到
"我的号码填不进去"）。

## 错误消息为什么必须是中文
App 端 `android/.../core/ApiClient.kt::humanizeValidation` 对**含中文**的 `msg` 原样显示，
对英文的走一张翻译表。也就是说这条 `ValueError` 会一字不差地出现在用户眼前，
所以它必须写成"照着改就能过"的样子（说清是什么、多长、举例），而不是"invalid phone"。
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator

#: 联系电话的位数区间（见模块文档：为什么是 7 与 12）
CONTACT_MIN_DIGITS = 7
CONTACT_MAX_DIGITS = 12

#: 手机号（登录账号）：11 位数字、以 1 开头。**唯一一份**，别在 schema 里再写一次。
MOBILE_PATTERN = r"^1\d{10}$"

# ⛔ `re.ASCII` 不是装饰，少了它这条规则会被全角数字绕过：
#    Python 的 `\d`（str 模式默认 `re.UNICODE`）匹配**任何 Unicode 十进制数字**，
#    于是 `１３８００００００００`（全角）与 `1３８０００００００` 都能通过 ——
#    而全角号码在拨号盘/短信/导出里都不是号码。
#    实测踩到过：第一版没加 `re.ASCII`，全角那一条用例直接"通过"了。
#    加了之后 `\d` 与 JSON-Schema（ECMA）里的 `\d` 同义，规则与 `MOBILE_PATTERN` 一致。
_MOBILE_RE = re.compile(MOBILE_PATTERN, re.ASCII)
#: 联系电话：整串都是 ASCII 数字（理由同上：全角数字必须挡）
_CONTACT_RE = re.compile(
    rf"^\d{{{CONTACT_MIN_DIGITS},{CONTACT_MAX_DIGITS}}}$", re.ASCII
)

#: 错误消息（App 会原样显示给用户，所以写成"照着改就能过"的句子）
CONTACT_PHONE_MESSAGE = (
    f"电话只能是数字，{CONTACT_MIN_DIGITS}~{CONTACT_MAX_DIGITS} 位"
    "（例如 13800000000）；不要填汉字、字母或符号"
)
MOBILE_PHONE_MESSAGE = "手机号必须是 11 位数字，且以 1 开头（例如 13800000000）"


def validate_contact_phone(value: str | None) -> str | None:
    """联系电话（收货人/下单人/联系人/挂账单位/客户）：去空格后必须全是数字，7~12 位。

    空串 / 纯空格 / `None` 一律当"没填"（这些字段大多是可选的，逼用户填是在制造假数据）。

    返回**去掉首尾空格**后的值：号码常是从别处复制来的，首尾带空格很常见；
    "去空格后合法"却把空格原样存进去，到了拨号/导出/短信还是同一个问题。
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return ""
    if not _CONTACT_RE.match(text):
        raise ValueError(CONTACT_PHONE_MESSAGE)
    return text


def validate_mobile_phone(value: str | None) -> str | None:
    """手机号（登录账号）：必须 11 位数字且以 1 开头。

    ⚠️ 这里**故意不做 strip**：规则是从 `UserCreate.phone` 原来的 `pattern=r"^1\\d{10}$"`
    原样搬过来的 —— 账号同时是登录名，登录接口按字符串**精确匹配**
    `users.username / users.phone`，静默接受一个带空格的账号，等于造出一个
    "建得出来、再也登不进去"的号。搬规则时合法取值集合必须一模一样。
    """
    if value is None:
        return None
    if not _MOBILE_RE.match(value):
        raise ValueError(MOBILE_PHONE_MESSAGE)
    return value


#: 必填联系电话
ContactPhone = Annotated[str, AfterValidator(validate_contact_phone)]
#: 可选联系电话（PATCH 语义：`None` = 不改这条，所以必须放行 None）
OptionalContactPhone = Annotated[str | None, AfterValidator(validate_contact_phone)]
#: 必填手机号（登录账号）
MobilePhone = Annotated[str, AfterValidator(validate_mobile_phone)]
#: 可选手机号（改账号时）
OptionalMobilePhone = Annotated[str | None, AfterValidator(validate_mobile_phone)]
