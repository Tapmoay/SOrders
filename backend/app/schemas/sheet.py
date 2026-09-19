from pydantic import BaseModel, Field


class SheetTableOut(BaseModel):
    """读出来的一张表。"""

    name: str
    rows: list[list[str]]
    #: **截断前**的真实行数（用户和模型都要知道"这表到底多大"）
    row_count: int
    col_count: int
    truncated: bool


class SheetParseOut(BaseModel):
    """上传一个表格文件 → 读成文本表格。"""

    filename: str
    #: xlsx | text | tsv
    kind: str
    tables: list[SheetTableOut] = Field(default_factory=list)
    #: 一定要显示给用户看的话：编码是猜的、行被截断了、有工作表没读……
    warnings: list[str] = Field(default_factory=list)
