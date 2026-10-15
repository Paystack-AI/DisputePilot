import math

from pydantic import BaseModel, ConfigDict, Field

MAX_PAGE_LIMIT: int = 100


class PageParams(BaseModel):
    # unknown query params (e.g. cache busters added by proxies) are ignored, not rejected
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=MAX_PAGE_LIMIT)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit


class PageMeta(BaseModel):
    page: int
    limit: int
    total: int
    total_pages: int

    @classmethod
    def build(cls, params: PageParams, total: int) -> "PageMeta":
        return cls(
            page=params.page,
            limit=params.limit,
            total=total,
            total_pages=math.ceil(total / params.limit),
        )
