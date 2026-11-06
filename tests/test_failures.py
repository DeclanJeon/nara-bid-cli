from datetime import datetime
from pathlib import Path

import httpx2
import pytest
from typer.testing import CliRunner

from nara.api import BidClient, retry_delay
from nara.cli import app
from nara.export import check_destination, write_csv
from nara.models import (
    KST,
    Body,
    Category,
    Envelope,
    Header,
    NaraError,
    RawNotice,
    Response,
    Window,
)


def test_network_failure_sanitizes_key() -> None:
    calls: list[float] = []

    def fail(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("url contains SECRET-KEY", request=request)

    now = datetime.now(KST)
    with httpx2.Client(transport=httpx2.MockTransport(fail)) as http:
        client = BidClient(http, "SECRET-KEY", sleep=calls.append)
        with pytest.raises(NaraError) as error:
            client.request(Category.SERVICE, Window(now, now), 1)
    assert "SECRET-KEY" not in str(error.value)
    assert calls == [1.0, 2.0]
    assert client.attempts == 3


def test_partial_failure_no_csv_or_table(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    now = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = [
        RawNotice(
            bidNtceNo=f"SYNTHETIC-{index}",
            bidNtceOrd="000",
            bidNtceNm="AI 합성 테스트",
            bidNtceDt=now.strftime("%Y-%m-%d %H:%M:%S"),
        )
        for index in range(100)
    ]
    pages: list[int] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        page = int(request.url.params["pageNo"])
        pages.append(page)
        if page == 2:
            return httpx2.Response(403)
        data = Envelope(
            response=Response(
                header=Header(resultCode="00"),
                body=Body(items=rows, totalCount=101, pageNo=1, numOfRows=100),
            ),
        )
        return httpx2.Response(200, content=data.model_dump_json().encode())

    monkeypatch.setenv("NARA_API_KEY", "SYNTHETIC-KEY")
    monkeypatch.setattr(
        "nara.cli.create_client",
        lambda: httpx2.Client(transport=httpx2.MockTransport(handle)),
    )
    target = tmp_path / "not-created.csv"
    result = CliRunner().invoke(app, ["search", "AI", "--days", "1", "--csv", str(target)])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert not target.exists()
    assert pages == [1, 2]
    assert "SYNTHETIC-KEY" not in result.output


def test_csv_write_failure_cleans_temp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fail(source: Path, target: Path) -> None:
        raise OSError("synthetic filesystem failure")

    monkeypatch.setattr("nara.export.os.link", fail)
    target = tmp_path / "failed.csv"
    with pytest.raises(NaraError):
        write_csv(target, [], datetime.now(KST))
    assert not target.exists()
    assert not list(tmp_path.glob(".nara-*"))


def test_missing_parent(tmp_path: Path) -> None:
    with pytest.raises(NaraError) as error:
        check_destination(tmp_path / "missing" / "result.csv")
    assert error.value.exit_code == 2


def test_earlier_retry_date_is_immediate() -> None:
    assert retry_delay("Thu, 01 Jan 1970 00:00:00 GMT", 0) == 0
