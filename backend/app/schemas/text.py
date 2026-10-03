"""文本入参的长度上限：**唯一定义处**（数字别在十几个 schema 里各写一遍）。

### 为什么要有这一层（2026-09-18 按用户要求「文本长度做一个限制」）
- 列是 `String(N)` 的字段，超长在本地 SQLite **照收**，到生产 MySQL 就是
  `Data too long for column`（轻则被兜底成一句笼统的 400，重则 500）；
- 列是 TEXT 的字段（备注、正文）**根本没有上限**：8000 字的备注能存进去，
  然后出现在列表页、导出文件、AI 上下文与手机通知里；
- 而"太长"是用户能自助修好的错误——前提是那句话说得清**哪个字段、最多多少字**。
  光加 `max_length=` 会得到 Pydantic 的英文结构体，所以配套有
  `app/core/validation_errors.py`（422 的 body 换成人话，状态码不变）。

⚠️ 这些数字要与**列宽**一致（不一致就是生产 MySQL 上的下一颗雷）：
`_tools/qa/_audit_text_fields.py` 会把两边逐字段比一遍，超了直接非零退出。

### 2026-10-04 加了字符那一半（BUG-0009）
长度之外，"这一串字符本身是不是能看的字"也归这一层：判据在 `app/core/text_guard.py`
（`??????` 这种**写进来时就已经坏掉**的值只剩拦在入口一条路），本文件提供 `ShowableModel`
这个混入 —— 子类声明 `SHOWABLE_FIELDS` 就自动过闸。长度（上面那批数字）与字符（那一层）
是同一件事的两半，都不要再抄到别处。
"""

from typing import Annotated, ClassVar

from pydantic import BaseModel, StringConstraints, model_validator

from app.core import text_guard

#: 图片/文件 URL：与 `String(512)` 列宽一致
MAX_URL = 512
#: 一条记录最多几张图（Android 相册多选也是 9 张，见 `OrderCreateViewModel`）
MAX_IMAGES = 9
#: 备注类（列多为 `String(256)`）
MAX_NOTE = 256
#: 说明/正文类（TEXT 列）。4000 与既有的 `internal_note` / `exception_reason` 口径一致
MAX_TEXT = 4000
#: 原因（撤销原因等）
MAX_REASON = 1024
#: 电话
MAX_PHONE = 32
#: 地点/商品分类/单位一类的短名（列多为 `String(32)`）
MAX_SHORT_NAME = 32
#: 名称类（地点名、收货人等，列多为 `String(128)`）
MAX_NAME = 128
#: 地址类（列多为 `String(512)`）
MAX_ADDRESS = 512

#: 单个 URL（`list[Url]` 用：列表本身的条数上限另外写在字段上）
Url = Annotated[str, StringConstraints(max_length=MAX_URL)]


class ShowableModel(BaseModel):
    """自由文本字段的"看得见"闸（BUG-0009）：子类声明 `SHOWABLE_FIELDS` 就自动挂上。

    判据与那句话的唯一实现在 `app/core/text_guard.py`；这一层只管一件事：**哪些字段送去过闸**
    （名单写在各自 schema 的 `SHOWABLE_FIELDS` 里，判据脚本逐条钉住它）。

    ⚠️ `SHOWABLE_FIELDS` 必须写成 `ClassVar`：不写的话 Pydantic 会把它当成一个**字段**
    （于是每个请求都要带 `showable_fields`，而它根本不进数据库）。
    """

    #: 会被端到用户眼前的自由文本字段（与模型属性同名，中文名由 `FIELD_CN` 给）
    SHOWABLE_FIELDS: ClassVar[tuple[str, ...]] = ()

    @model_validator(mode="after")
    def _showable(self) -> "ShowableModel":
        text_guard.ensure_fields(self, type(self).SHOWABLE_FIELDS)
        return self
