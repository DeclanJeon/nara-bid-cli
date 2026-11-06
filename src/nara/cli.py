"""One-command interface: nara search."""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Annotated, Final

import typer
from rich.console import Console
from rich.table import Table

from nara.api import BidClient, create_client
from nara.export import check_destination, terminal_text, write_csv
from nara.models import KST, Category, NaraError, Notice
from nara.search import find_notices, normalize, query_window

app: Final = typer.Typer(
    help="나라장터 공고명 키워드 검색. DB·자동 투찰 없이 조회합니다.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


@app.callback()
def main() -> None:
    """Keep the search subcommand even when there is only one command."""


def print_results(notices: list[Notice]) -> None:
    console = Console(markup=False, highlight=False)
    if not notices:
        console.print("조건에 맞는 공고 0건")
        return
    table = Table(title=f"검색 결과 {len(notices)}건", show_lines=True)
    for column in ("공고번호·차수", "제목", "공고기관", "게시일(KST)", "입찰마감(KST)"):
        table.add_column(column)
    for n in notices:
        table.add_row(
            terminal_text(f"{n.number}-{n.order}"),
            terminal_text(n.title),
            terminal_text(n.agency) or "미확인",
            n.published.isoformat(),
            n.deadline.isoformat() if n.deadline else "미확인",
        )
    console.print(table)


@app.command()
def search(
    keyword: Annotated[str, typer.Argument(help="공고명에 포함될 단일 키워드")],
    category: Annotated[
        Category, typer.Option(help="service=용역, goods=물품, construction=공사")
    ] = Category.SERVICE,
    days: Annotated[int, typer.Option(min=1, max=31, help="실행일 포함 최근 게시기간")] = 7,
    exclude: Annotated[list[str] | None, typer.Option(help="제외어. 여러 번 지정 가능")] = None,
    csv: Annotated[Path | None, typer.Option(help="CSV 저장 경로. 기존 파일 보존")] = None,
) -> None:
    """API 전체 페이지를 조회한 뒤 제목을 검색합니다. 마감 공고도 포함합니다."""
    try:
        excludes = exclude or []
        if not normalize(keyword) or any(not normalize(word) for word in excludes):
            raise NaraError("키워드와 제외어는 공백만 입력할 수 없습니다.", 2)
        key = os.environ.get("NARA_API_KEY", "").strip()
        if not key:
            raise NaraError("NARA_API_KEY 환경변수에 인증키를 설정하세요.", 2)
        if csv is not None:
            check_destination(csv)
        now = datetime.now(KST)
        window = query_window(days, now)
        # Upstream INFO request logs can include the full credential-bearing URL.
        logging.getLogger("httpx2").setLevel(logging.WARNING)
        logging.getLogger("httpcore2").setLevel(logging.WARNING)
        with create_client() as http:
            client = BidClient(http, key)
            notices = client.collect(category, window)
        results = find_notices(notices, keyword, excludes)
        if csv is not None:
            write_csv(csv, results, now)
        period = f"{window.start.isoformat()} ~ {window.end.isoformat()}"
        typer.echo(
            " | ".join(
                (
                    f"분야={category.value}",
                    f"게시기간={period}",
                    f"조회시각={now.isoformat()}",
                    f"HTTP 시도={client.attempts}",
                )
            ),
            err=True,
        )
        typer.echo("게시기간 내 공고명 검색 결과입니다. 마감 공고 포함·참가자격 미판정.", err=True)
        print_results(results)
    except NaraError as error:
        typer.echo(f"오류: {error.message}", err=True)
        raise typer.Exit(error.exit_code) from None
