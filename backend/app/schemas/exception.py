from pydantic import BaseModel


class ExceptionResolveBody(BaseModel):
    note: str | None = None
