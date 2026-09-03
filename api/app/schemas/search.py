from typing import Literal

from pydantic import BaseModel

SearchResultType = Literal["unit", "catalog_item", "delivery_note", "location"]


class SearchResult(BaseModel):
    type: SearchResultType
    id: str
    label: str
    sublabel: str | None = None
    path: str


class SearchResponse(BaseModel):
    results: list[SearchResult]
