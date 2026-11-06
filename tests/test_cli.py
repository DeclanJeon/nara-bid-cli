from datetime import datetime
from pathlib import Path

import httpx2
import pytest
from typer.testing import CliRunner

from nara.cli import app
from nara.models import KST, Body, Envelope, Header, RawNotice, Response


def install_mock(monkeypatch: pytest.MonkeyPatch, response: httpx2.Response) -> list[str]:
    calls: list[str] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        calls.append(request.url.path)
        return response

    monkeypatch.setattr(
        "nara.cli.create_client",
        lambda: httpx2.Client(
            transport=httpx2.MockTransport(handle),
        ),
    )
    monkeypatch.setenv("NARA_API_KEY", "SYNTHETIC-SECRET-NOT-A-REAL-KEY")
    return calls


def zero_response() -> httpx2.Response:
    data = Envelope(
        response=Response(
            header=Header(resultCode="00"),
            body=Body(items=[], totalCount=0, pageNo=1, numOfRows=100),
        )
    )
    return httpx2.Response(200, content=data.model_dump_json().encode())


def test_help() -> None:
    result = CliRunner().invoke(app, ["search", "--help"])
    assert result.exit_code == 0
    assert "--csv" in result.stdout


@pytest.mark.parametrize(
    "arguments",
    [
        ["search", " "],
        ["search", "AI", "--days", "0"],
        ["search", "AI", "--days", "32"],
        ["search", "AI", "--category", "other"],
        ["search", "AI", "--exclude", " "],
    ],
)
def test_invalid_inputs_no_requests(monkeypatch: pytest.MonkeyPatch, arguments: list[str]) -> None:
    calls = install_mock(monkeypatch, zero_response())
    result = CliRunner().invoke(app, arguments)
    assert result.exit_code == 2
    assert calls == []


def test_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NARA_API_KEY", raising=False)
    result = CliRunner().invoke(app, ["search", "AI"])
    assert result.exit_code == 2
    assert "NARA_API_KEY" in result.stderr


def test_zero_result_csv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = install_mock(monkeypatch, zero_response())
    destination = tmp_path / "empty.csv"
    result = CliRunner().invoke(app, ["search", "AI", "--days", "1", "--csv", str(destination)])
    assert result.exit_code == 0
    assert "0건" in result.stdout
    assert destination.read_bytes().startswith(b"\xef\xbb\xbf")
    assert len(calls) == 1
    assert "SYNTHETIC-SECRET" not in result.output


def test_existing_csv_no_request(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = install_mock(monkeypatch, zero_response())
    destination = tmp_path / "existing.csv"
    destination.write_text("preserve")
    result = CliRunner().invoke(app, ["search", "AI", "--csv", str(destination)])
    assert result.exit_code == 2
    assert calls == []
    assert destination.read_text() == "preserve"


@pytest.mark.parametrize("status", [301, 401, 403])
def test_http_failure_no_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: int,
) -> None:
    calls = install_mock(monkeypatch, httpx2.Response(status))
    destination = tmp_path / "not-written.csv"
    result = CliRunner().invoke(app, ["search", "AI", "--days", "1", "--csv", str(destination)])
    assert result.exit_code == 1
    assert len(calls) == 1
    assert not destination.exists()
    assert "0건" not in result.stdout
    assert "SYNTHETIC-SECRET" not in result.output


def test_http_200_business_error_no_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    data = Envelope(response=Response(header=Header(resultCode="30")))
    install_mock(monkeypatch, httpx2.Response(200, content=data.model_dump_json().encode()))
    destination = tmp_path / "not-written.csv"
    result = CliRunner().invoke(app, ["search", "AI", "--days", "1", "--csv", str(destination)])
    assert result.exit_code == 1
    assert not destination.exists()


def test_happy_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    now = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0)
    raw = RawNotice(
        bidNtceNo="SYNTHETIC-001",
        bidNtceOrd="000",
        bidNtceNm="AI 개발 [test]",
        bidNtceDt=now.strftime("%Y-%m-%d %H:%M:%S"),
    )
    data = Envelope(
        response=Response(
            header=Header(resultCode="00"),
            body=Body(items=[raw], totalCount=1, pageNo=1, numOfRows=100),
        )
    )
    install_mock(monkeypatch, httpx2.Response(200, content=data.model_dump_json().encode()))
    destination = tmp_path / "happy.csv"
    result = CliRunner().invoke(
        app,
        [
            "search",
            "ai",
            "--days",
            "1",
            "--category",
            "goods",
            "--csv",
            str(destination),
        ],
    )
    assert result.exit_code == 0
    assert "1건" in result.stdout
    assert "AI 개발 [test]" in result.stdout
    assert "goods" in destination.read_text(encoding="utf-8-sig")
