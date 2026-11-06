"""Date windows, API parsing, title matching and deterministic sorting."""

import unicodedata
from datetime import datetime, time, timedelta
from typing import assert_never
from urllib.parse import urlsplit

from pydantic import ValidationError

from nara.models import (
    KST,
    Body,
    Category,
    Envelope,
    ItemWrapper,
    NaraError,
    Notice,
    NoticeNumber,
    RawNotice,
    Window,
)


def normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def query_window(days: int, now: datetime) -> Window:
    local = now.astimezone(KST).replace(microsecond=0)
    first = local.date() - timedelta(days=days - 1)
    return Window(datetime.combine(first, time.min, KST), local)


def daily_windows(window: Window) -> list[Window]:
    """Use single calendar days, avoiding long-range API query limits."""
    result: list[Window] = []
    start = window.start
    while start <= window.end:
        end = min(start.replace(hour=23, minute=59, second=59), window.end)
        result.append(Window(start, end))
        start = (start + timedelta(days=1)).replace(hour=0, minute=0, second=0)
    return result


def parse_page(content: bytes) -> Body:
    try:
        envelope = Envelope.model_validate_json(content)
    except ValidationError:
        raise NaraError("API 응답 형식이 올바르지 않습니다.") from None
    response = envelope.response
    if response.header.resultCode not in {"00", "0"}:
        raise NaraError("API 업무 오류입니다. 인증키·승인·호출 한도를 확인하세요.")
    if response.body is None:
        raise NaraError("API 응답에 body가 없습니다.")
    return response.body


def page_items(body: Body) -> list[RawNotice]:
    match body.items:
        case list() as items:
            return items
        case ItemWrapper(item=wrapped):
            match wrapped:
                case list() as items:
                    return items
                case RawNotice() as item:
                    return [item]
                case None:
                    return []
                case unreachable:
                    assert_never(unreachable)
        case str() as text:
            if text.strip():
                raise NaraError("API items 형식이 올바르지 않습니다.")
            return []
        case None:
            return []
        case unreachable:
            assert_never(unreachable)


def parse_date(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.strip())
    except ValueError:
        raise NaraError("API 날짜 필드가 올바르지 않습니다.") from None
    return result.replace(tzinfo=KST) if result.tzinfo is None else result.astimezone(KST)


def to_notice(raw: RawNotice, category: Category) -> Notice:
    if not all(v.strip() for v in (raw.bidNtceNo, raw.bidNtceOrd, raw.bidNtceNm)):
        raise NaraError("API 공고 식별자 또는 제목이 비어 있습니다.")
    url = raw.bidNtceDtlUrl or ""
    try:
        if url and urlsplit(url).scheme not in {"https", "http"}:
            raise NaraError("API 원문 URL 형식이 올바르지 않습니다.")
    except ValueError:
        raise NaraError("API 원문 URL 형식이 올바르지 않습니다.") from None
    return Notice(
        category,
        NoticeNumber(raw.bidNtceNo),
        raw.bidNtceOrd,
        raw.bidNtceNm,
        raw.ntceInsttNm or "",
        parse_date(raw.bidNtceDt),
        parse_date(raw.bidClseDt) if raw.bidClseDt and raw.bidClseDt.strip() else None,
        url,
    )


def find_notices(notices: list[Notice], keyword: str, excludes: list[str]) -> list[Notice]:
    needle = normalize(keyword)
    blocked = [normalize(word) for word in excludes]
    found = [
        n
        for n in notices
        if needle in normalize(n.title) and not any(word in normalize(n.title) for word in blocked)
    ]
    found.sort(key=lambda n: (n.number, n.order))
    found.sort(key=lambda n: n.published, reverse=True)
    return found
