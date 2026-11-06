"""Typed API boundary and small domain values."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import ClassVar, Final, NewType

from pydantic import BaseModel, ConfigDict, Field

KST: Final = timezone(timedelta(hours=9))
NoticeNumber = NewType("NoticeNumber", str)


class Category(StrEnum):
    SERVICE = "service"
    GOODS = "goods"
    CONSTRUCTION = "construction"


class NaraError(Exception):
    """User-safe failure; never include request URLs or response bodies."""

    message: str
    exit_code: int

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


class ApiModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")


class RawNotice(ApiModel):
    bidNtceNo: str = Field(min_length=1)
    bidNtceOrd: str = Field(min_length=1)
    bidNtceNm: str = Field(min_length=1)
    bidNtceDt: str = Field(min_length=1)
    ntceInsttNm: str | None = None
    bidClseDt: str | None = None
    bidNtceDtlUrl: str | None = None


class ItemWrapper(ApiModel):
    item: list[RawNotice] | RawNotice | None = None


class Body(ApiModel):
    items: list[RawNotice] | ItemWrapper | str | None = None
    totalCount: int = Field(ge=0)
    pageNo: int = Field(ge=1)
    numOfRows: int = Field(ge=1)


class Header(ApiModel):
    resultCode: str


class Response(ApiModel):
    header: Header
    body: Body | None = None


class Envelope(ApiModel):
    response: Response


@dataclass(frozen=True, slots=True)
class Notice:
    category: Category
    number: NoticeNumber
    order: str
    title: str
    agency: str
    published: datetime
    deadline: datetime | None
    url: str


@dataclass(frozen=True, slots=True)
class Window:
    start: datetime
    end: datetime
