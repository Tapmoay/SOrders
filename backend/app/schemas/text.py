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
"""

from typing import Annotated

from pydantic import StringConstraints

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
