from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Literal, assert_never

import httpx2
import pytest

from nara.api import BidClient, retry_delay
from nara.export import csv_text, terminal_text, write_csv
from nara.models import (
    KST,
    Body,
    Category,
    Envelope,
    Header,
    ItemWrapper,
    NaraError,
    RawNotice,
    Response,
    Window,
)
from nara.search import (
    daily_windows,
    find_notices,
    page_items,
    parse_date,
    parse_page,
    query_window,
    to_notice,
)

NOW = datetime(2026, 11, 6, 14, 30, 42, tzinfo=KST)
SPAN = Window(NOW.replace(hour=0, minute=0, second=0), NOW)


def raw(index: int = 1, title: str = "AI 개발 용역") -> RawNotice:
    return RawNotice(
        bidNtceNo=f"TEST-{index:04}",
        bidNtceOrd="000",
        bidNtceNm=title,
        bidNtceDt="2026-11-06 10:00:01",
    )


def payload(items: list[RawNotice], total: int, page: int = 1, code: str = "00") -> bytes:
    return (
        Envelope(
            response=Response(
                header=Header(resultCode=code),
                body=Body(items=items, totalCount=total, pageNo=page, numOfRows=100),
            )
        )
        .model_dump_json()
        .encode()
    )


def test_filter_and_sort() -> None:
    notices = [
        to_notice(raw(2, "ＡＩ   개발"), Category.SERVICE),
        to_notice(raw(1, "ai 임대"), Category.SERVICE),
        to_notice(raw(3, "머신러닝 개발"), Category.SERVICE),
    ]
    assert [n.number for n in find_notices(notices, " AI ", ["임대"])] == ["TEST-0002"]
    assert find_notices(notices, "인공지능", []) == []


def test_window_preserves_execution_seconds_and_day_end() -> None:
    window = query_window(7, NOW)
    assert window.start == datetime(2026, 10, 31, tzinfo=KST)
    assert window.end == NOW
    spans = daily_windows(window)
    assert len(spans) == 7
    assert spans[0].end.second == 59
    assert spans[-1].end == NOW


def test_all_pages_and_posting_time_endpoint() -> None:
    pages: list[int] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path.endswith("getBidPblancListInfoServcPPSSrch02")
        assert request.url.params["inqryDiv"] == "1"
        assert request.url.params["bidClseExcpYn"] == "N"
        page = int(request.url.params["pageNo"])
        pages.append(page)
        first = (page - 1) * 100
        return httpx2.Response(
            200,
            content=payload(
                [raw(i) for i in range(first, min(first + 100, 205))],
                205,
                page,
            ),
        )

    with httpx2.Client(transport=httpx2.MockTransport(handle)) as http:
        rows = BidClient(http, "test-key").collect(Category.SERVICE, SPAN)
    assert len(rows) == 205
    assert pages == [1, 2, 3]


@pytest.mark.parametrize("wrapped", [False, True])
def test_zero_items(wrapped: bool) -> None:
    body = Body(
        totalCount=0,
        pageNo=1,
        numOfRows=100,
        items=ItemWrapper(item=None) if wrapped else "",
    )
    assert page_items(body) == []


def test_single_wrapper_item() -> None:
    body = Body(totalCount=1, pageNo=1, numOfRows=100, items=ItemWrapper(item=raw()))
    assert page_items(body) == [raw()]


@pytest.mark.parametrize(
    "content",
    [
        b"<xml>error</xml>",
        b"{}",
        b'{"response":{"header":{"resultCode":"99"}}}',
        b'{"response":{"header":{"resultCode":"00"}}}',
    ],
)
def test_bad_response(content: bytes) -> None:
    with pytest.raises(NaraError):
        parse_page(content)


@pytest.mark.parametrize("bad", ["invalid", "2026-02-30 10:00:00", ""])
def test_bad_date(bad: str) -> None:
    with pytest.raises(NaraError):
        parse_date(bad)


def test_optional_fields_and_order() -> None:
    notice = to_notice(raw(), Category.SERVICE)
    assert notice.order == "000"
    assert notice.deadline is None
    assert notice.agency == notice.url == ""


@pytest.mark.parametrize("broken", ["repeat", "short", "count", "page", "conflict"])
def test_incomplete_collections_fail(
    broken: Literal["repeat", "short", "count", "page", "conflict"],
) -> None:
    def handle(request: httpx2.Request) -> httpx2.Response:
        page = int(request.url.params["pageNo"])
        rows = [raw(i) for i in range(100)]
        total = 200
        match broken:
            case "repeat":
                pass
            case "short":
                rows = rows[:1]
            case "count":
                total += page - 1
            case "page":
                page = 9
            case "conflict":
                rows[1] = raw(0, "다른 제목")
            case unreachable:
                assert_never(unreachable)
        return httpx2.Response(200, content=payload(rows, total, page))

    with (
        httpx2.Client(transport=httpx2.MockTransport(handle)) as http,
        pytest.raises(NaraError),
    ):
        BidClient(http, "secret").collect(Category.SERVICE, SPAN)


def test_duplicate_and_revision() -> None:
    first = raw()
    second = first.model_copy(update={"bidNtceOrd": "001"})
    with httpx2.Client(
        transport=httpx2.MockTransport(
            lambda _: httpx2.Response(200, content=payload([first, first, second], 3)),
        )
    ) as http:
        rows = BidClient(http, "test").collect(Category.SERVICE, SPAN)
    assert [row.order for row in rows] == ["000", "001"]


@pytest.mark.parametrize("status", [429, 500, 503])
def test_retry_and_budget(status: int) -> None:
    calls: list[float] = []
    with httpx2.Client(
        transport=httpx2.MockTransport(
            lambda _: httpx2.Response(status, headers={"Retry-After": "0"}),
        )
    ) as http:
        client = BidClient(http, "secret", sleep=calls.append)
        with pytest.raises(NaraError):
            client.request(Category.SERVICE, SPAN, 1)
    assert client.attempts == 3
    assert calls == [0, 0]


def test_budget_includes_retries() -> None:
    with httpx2.Client(
        transport=httpx2.MockTransport(
            lambda _: httpx2.Response(503),
        )
    ) as http:
        client = BidClient(http, "secret", sleep=lambda _: None, request_limit=2)
        with pytest.raises(NaraError, match="한도"):
            client.request(Category.SERVICE, SPAN, 1)
    assert client.attempts == 2


def test_raw_and_encoded_keys_are_encoded_once() -> None:
    observed: list[str] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        observed.append(request.url.params["serviceKey"])
        return httpx2.Response(200, content=payload([], 0))

    with httpx2.Client(transport=httpx2.MockTransport(handle)) as http:
        for key in ["a+b/c==", "a%2Bb%2Fc%3D%3D"]:
            BidClient(http, key).request(Category.SERVICE, SPAN, 1)
    assert observed == ["a+b/c==", "a+b/c=="]


@pytest.mark.parametrize("value", ["NaN", "inf", "61", "-1", "invalid"])
def test_invalid_retry_after(value: str) -> None:
    with pytest.raises(NaraError):
        retry_delay(value, 0)


def test_csv_and_no_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "bids.csv"
    notice = replace(to_notice(raw(title='=SUM(1,2)"한글'), Category.SERVICE), agency="\t@unsafe")
    write_csv(path, [notice], NOW)
    original = path.read_bytes()
    assert original.startswith(b"\xef\xbb\xbf")
    assert "'=SUM" in original.decode("utf-8-sig")
    assert "'\t@unsafe" in original.decode("utf-8-sig")
    with pytest.raises(NaraError):
        write_csv(path, [], NOW)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".nara-*"))


def test_zero_csv_has_only_header(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    write_csv(path, [], NOW)
    assert len(path.read_text(encoding="utf-8-sig").splitlines()) == 1


def test_terminal_controls_and_formula() -> None:
    assert "\x1b" not in terminal_text("\x1b[31m\nhello")
    assert csv_text("  =cmd()").startswith("'")
