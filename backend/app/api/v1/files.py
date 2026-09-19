"""文件相关：把用户从手机里选的表格读成文本，交给 AI 助手分析。

### 这个域为什么只有"读"、没有"写"
传进来的是**用户自己的文件**，读完就还给他，服务器什么都不留（不落盘、不进库）。
所以这里不需要 operation_logs、也不需要撤回——它没有改变任何业务状态。

### 谁能用
派单员与货主（AI 助手只对这两个角色开放，见 [AiRole]）。司机端没有 AI 入口，
所以也不该能调这个接口。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.deps import require_roles
from app.models import User
from app.models.enums import UserRole
from app.schemas.sheet import SheetParseOut, SheetTableOut
from app.services.sheet_parser import (
    DEFAULT_MAX_ROWS,
    MAX_MAX_ROWS,
    SheetParseError,
    parse_upload,
)

router = APIRouter(prefix="/files", tags=["files"])

AiUser = Annotated[User, Depends(require_roles(UserRole.DISPATCHER, UserRole.SHIPPER))]


@router.post("/parse-sheet", response_model=SheetParseOut)
async def parse_sheet(
    current: AiUser,
    file: UploadFile = File(...),
    max_rows: int = Query(
        DEFAULT_MAX_ROWS,
        ge=1,
        le=MAX_MAX_ROWS,
        description="每张表最多读几行（防止一张几万行的表把 AI 的上下文塞满）",
    ),
) -> SheetParseOut:
    """上传 Excel(.xlsx/.xlsm) 或文本表格(.csv/.tsv/.txt)，读成「一格一格」的文本。

    **服务器不保存这个文件**：读一遍、返回结果、内存释放。
    这一点是刻意的——用户传的可能是有成本价的商品表，留副本就要回答
    "存哪、留多久、谁能下" 三个问题，而这三个问题在这里没有存在的必要。
    """
    raw = await file.read()
    try:
        parsed = parse_upload(file.filename or "", raw, max_rows=max_rows)
    except SheetParseError as e:
        # 读数失败是**用户能自己解决**的事（另存为 xlsx、拆小、去掉公式），
        # 所以一律 400 + 一句能照着做的话，而不是 500。
        raise HTTPException(status_code=400, detail=str(e)) from e

    return SheetParseOut(
        filename=file.filename or "",
        kind=parsed.kind,
        tables=[
            SheetTableOut(
                name=t.name,
                rows=t.rows,
                row_count=t.row_count,
                col_count=t.col_count,
                truncated=t.truncated,
            )
            for t in parsed.tables
        ],
        warnings=parsed.warnings,
    )
