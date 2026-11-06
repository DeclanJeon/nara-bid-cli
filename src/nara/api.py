"""Sequential G2B API client with one visible retry/budget layer."""

import logging
import socket
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Final
from urllib.parse import unquote

import httpx2

from nara.models import Category, NaraError, Notice, Window
from nara.search import daily_windows, page_items, parse_page, to_notice

BASE_URL: Final = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService02/"
OPERATIONS: Final = {
    Category.SERVICE: "getBidPblancListInfoServcPPSSrch02",
    Category.GOODS: "getBidPblancListInfoThngPPSSrch02",
    Category.CONSTRUCTION: "getBidPblancListInfoCnstwkPPSSrch02",
}
PAGE_SIZE: Final = 100
REQUEST_LIMIT: Final = 100
LOGGER: Final = logging.getLogger(__name__)


def log_response(response: httpx2.Response) -> None:
    """Observe status only: the URL contains a credential."""
    LOGGER.info("나라장터 HTTP status=%d", response.status_code)


def create_client() -> httpx2.Client:
    """Use HTTP/2/pooling; no hidden retries or credential-bearing redirects."""
    limits = httpx2.Limits(max_connections=200, max_keepalive_connections=40, keepalive_expiry=30)
    transport = httpx2.HTTPTransport(
        http2=True,
        limits=limits,
        retries=0,
        socket_options=[(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)],
    )
    return httpx2.Client(
        transport=transport,
        timeout=httpx2.Timeout(connect=5, read=20, write=10, pool=10),
        follow_redirects=False,
        event_hooks={"response": [log_response]},
    )


def retry_delay(value: str | None, attempt: int) -> float:
    if value is None:
        return 2.0**attempt
    try:
        wait = float(value)
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                target = target.replace(tzinfo=UTC)
            wait = max(0.0, (target - datetime.now(UTC)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            raise NaraError("Retry-After 값이 올바르지 않습니다.") from None
    if not 0 <= wait <= 60:
        raise NaraError("API가 긴 대기를 요청했습니다. 잠시 후 다시 실행하세요.")
    return wait


class BidClient:
    """Mutable request counter owns the per-search 100-attempt budget."""

    client: httpx2.Client
    key: str
    sleep: Callable[[float], None]
    attempts: int
    request_limit: int

    def __init__(
        self,
        client: httpx2.Client,
        key: str,
        *,
        sleep: Callable[[float], None] = time.sleep,
        request_limit: int = REQUEST_LIMIT,
    ) -> None:
        self.client = client
        self.key = unquote(key.strip())
        self.sleep = sleep
        self.attempts = 0
        self.request_limit = request_limit

    def request(self, category: Category, window: Window, page: int) -> bytes:
        params = {
            "serviceKey": self.key,
            "pageNo": str(page),
            "numOfRows": str(PAGE_SIZE),
            "type": "json",
            "inqryDiv": "1",
            "bidClseExcpYn": "N",
            "inqryBgnDt": window.start.strftime("%Y%m%d%H%M"),
            "inqryEndDt": window.end.strftime("%Y%m%d%H%M"),
        }
        for attempt in range(3):
            if self.attempts >= self.request_limit:
                raise NaraError("요청 100회 한도로 조회 미완료입니다. --days를 줄이세요.")
            self.attempts += 1
            try:
                response = self.client.get(BASE_URL + OPERATIONS[category], params=params)
            except (httpx2.TimeoutException, httpx2.NetworkError, httpx2.RemoteProtocolError):
                if attempt == 2:
                    raise NaraError("네트워크 연결 또는 시간 제한 오류입니다.") from None
                self.sleep(2.0**attempt)
                continue
            except httpx2.HTTPError:
                raise NaraError("HTTP 통신에 실패했습니다.") from None
            status = response.status_code
            if status == 429 or 500 <= status <= 599:
                if attempt == 2:
                    raise NaraError(f"API가 HTTP {status} 오류를 반환했습니다.")
                self.sleep(retry_delay(response.headers.get("Retry-After"), attempt))
                continue
            if status != 200:
                raise NaraError(f"API가 HTTP {status} 오류를 반환했습니다. 키·승인을 확인하세요.")
            return response.content
        raise NaraError("API 요청을 완료하지 못했습니다.")

    def collect(self, category: Category, window: Window) -> list[Notice]:  # noqa: C901
        notices: dict[tuple[str, str], Notice] = {}
        for span in daily_windows(window):
            page = 1
            expected_total: int | None = None
            received = 0
            fingerprints: set[tuple[Notice, ...]] = set()
            while True:
                body = parse_page(self.request(category, span, page))
                raw = page_items(body)
                if body.pageNo != page or body.numOfRows != PAGE_SIZE:
                    raise NaraError("API 페이지 번호 또는 페이지 크기가 일치하지 않습니다.")
                if expected_total is None:
                    expected_total = body.totalCount
                if body.totalCount != expected_total:
                    raise NaraError("조회 중 전체 건수가 변경되었습니다. 다시 조회하세요.")
                rows = tuple(to_notice(item, category) for item in raw)
                if rows and rows in fingerprints:
                    raise NaraError("API가 같은 페이지를 반복했습니다. 조회 미완료입니다.")
                fingerprints.add(rows)
                received += len(rows)
                if received > expected_total or len(rows) > PAGE_SIZE:
                    raise NaraError("API 전체 건수와 페이지 결과가 일치하지 않습니다.")
                for notice in rows:
                    key = (notice.number, notice.order)
                    if key in notices and notices[key] != notice:
                        raise NaraError("동일 공고의 내용이 충돌했습니다. 다시 조회하세요.")
                    notices[key] = notice
                if received == expected_total:
                    break
                if len(rows) < PAGE_SIZE:
                    raise NaraError("API 페이지가 부족합니다. 조회 미완료입니다.")
                page += 1
        return [n for n in notices.values() if window.start <= n.published <= window.end]
