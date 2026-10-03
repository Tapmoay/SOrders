"""看得见的字：自由文本入参里的「不可显示字符」与「整串问号」一律拒收（唯一实现）。

### 为什么有这一层（2026-10-04，BUG-0009）
开发库那张脏地点卡（`shipper_locations` id=94：名字与地址都是六个问号，同一单
`orders` id=426 的 `address_detail` / `delivery_description` / `contact_dongjia_name`
同样）里存的**就是问号本身**，原文已经不可能还原。查下来的结论：
- 不是显示端：同一张表相邻两行是正常中文（id=93 / id=95）；
- 不是我们自己的代码：客户端与服务端全仓没有任何"把汉字换成问号"的实现（唯一的 ASCII
  替换在 `services/ledger_export.py::_ascii_cell`，只用于导出 Excel）；
- 是**写进来的那一刻就已经是问号**：同一单里从库里挑的商品名/单位完好、手机号完好，
  只有手输的自由文本是问号 —— 而问号正是"用装不下汉字的编码去编码"时的默认替换字符。

当年走的是人手工填还是 AI 助手代填，已经分辨不出来了（`operation_logs.origin` 列
2026-09-25 才有，设备上的 AI 会话记录已随 `pm clear` 消失），但两条路走的是**同一个入参**，
所以闸设在这里：**自由文本字段写进来之前，先看它是不是人看得见的字**。

### 判什么
1. **不可能是人打出来的字符**：解码失败留下的替换符 `U+FFFD`、孤立代理项
   （`U+D800-U+DFFF`，Python 里能存在，写库或序列化时才炸）、除制表/换行外的
   C0/C1 控制字符（`\\x00-\\x08`、`\\x0b`、`\\x0c`、`\\x0e-\\x1f`、`\\x7f-\\x9f`）。
2. **整串（去掉首尾空白后）只有问号**（半角或全角，中间可以夹空白）：占位符或者编码
   坏掉的形状，原文不可还原 —— 填的人只能重新填一遍。

### 不判什么（边界，写清楚免得下一轮"顺手加严"误伤）
- **正常文字里夹着的问号**（`幸福路 1 号？`、`门牌???`）：放行。收紧成"含连续问号"会拒掉
  真实表达（"这个门牌我不确定"就是这么写的）。
- **长度与空白**：归 `services/place_service._clean` 与各 schema 的 `max_length`
  （`schemas/text.py` 是长度上限的唯一来源），本模块只管**字符本身**。
- **不是所有字段**：只挂"会被端到用户眼前"的自由文本字段（各 schema 的 `SHOWABLE_FIELDS`）。
  手机号、金额、日期那些有各自的类型与规则，不走这里。

### 用法
判据是这里的 `find` / `ensure`（纯函数，不依赖 FastAPI 也不依赖 Pydantic）；要挂到入参上，
继承 `app/schemas/text.py` 的 `ShowableModel` 并声明 `SHOWABLE_FIELDS` 即可。

`raise ValueError(中文)` 之后，`app/core/validation_errors.py` 会把这句中文原样放进 422
响应的 `detail`（`describe` 认得 `value_error` + 汉字），字段名也用它的 `FIELD_CN` 翻成中文 ——
用户看到的是「送货地址」里只有问号，不是一串英文 key。
"""

from __future__ import annotations

import re
from typing import Any

from app.core.validation_errors import FIELD_CN

#: 不可能是人打出来的字符：替换符、孤立代理项、除 \t \n \r 外的 C0/C1 控制字符
_BAD_CHARS = re.compile("[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\ufffd\ud800-\udfff]")

#: 问号形态：半角（编码坏掉时的默认替换字符）+ 全角（中文输入法手打的占位）
_QUESTION_MARKS = "?？"

BAD_CHAR_TEXT = "「{field}」里有看不见的字符（复制、粘贴或编码出错时会带上这种字符），请删掉后重新填写"
ONLY_MARKS_TEXT = "「{field}」里只有问号，这像是占位符或者编码出错留下的，请填写真实内容"


def _label(field: str) -> str:
    """字段名 → 给用户看的中文（复用 `validation_errors.FIELD_CN`，不在这里抄第二份）。"""
    return FIELD_CN.get(field, field)


def find(value: str | None, field: str) -> str | None:
    """这一串能不能端到用户眼前？能 = None；不能 = 给用户看的那句话（带字段中文名）。

    `None` / 空串一律放行："没填"是各 schema 自己的必填规则管的事，不在这里判。
    """
    text = value or ""
    if not text:
        return None
    if _BAD_CHARS.search(text):
        return BAD_CHAR_TEXT.format(field=_label(field))
    stripped = text.strip()
    if stripped and all(ch in _QUESTION_MARKS or ch.isspace() for ch in stripped):
        return ONLY_MARKS_TEXT.format(field=_label(field))
    return None


def ensure(value: str | None, field: str) -> None:
    """不合法就 `raise ValueError(那句话)`（在 Pydantic 校验器里用；422 的 detail 就是它）。"""
    err = find(value, field)
    if err is not None:
        raise ValueError(err)


def ensure_fields(obj: Any, fields: tuple[str, ...]) -> None:
    """按 schema 自己声明的名单逐条过闸（`getattr` 取不到就按"没填"跳过）。"""
    for name in fields:
        ensure(getattr(obj, name, None), name)
