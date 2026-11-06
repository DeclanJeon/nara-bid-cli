"""No-overwrite CSV export and terminal-safe plain text."""

import csv
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Final

from nara.models import NaraError, Notice

COLUMNS: Final = (
    "category",
    "notice_no",
    "notice_order",
    "title",
    "agency",
    "published_at",
    "deadline_at",
    "url",
    "fetched_at",
)


def terminal_text(value: str) -> str:
    """Prevent terminal control sequences from executing in untrusted API text."""
    return "".join(char if char.isprintable() else " " for char in value)


def csv_text(value: str) -> str:
    if value.lstrip("\ufeff \t\r\n").startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def check_destination(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise NaraError("CSV 대상이 이미 존재합니다. 다른 파일명을 사용하세요.", 2)
    if not path.parent.is_dir():
        raise NaraError("CSV 부모 디렉터리가 없습니다.", 2)


def write_csv(path: Path, notices: list[Notice], fetched_at: datetime) -> None:
    """Publish by hard link: atomic create that cannot replace an existing path."""
    temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            newline="",
            dir=path.parent,
            prefix=".nara-",
            suffix=".csv",
            delete=False,
        ) as stream:
            temp = Path(stream.name)
            writer = csv.writer(stream)
            writer.writerow(COLUMNS)
            for n in notices:
                values = (
                    n.category.value,
                    n.number,
                    n.order,
                    n.title,
                    n.agency,
                    n.published.isoformat(),
                    n.deadline.isoformat() if n.deadline else "",
                    n.url,
                    fetched_at.isoformat(),
                )
                writer.writerow([csv_text(value) for value in values])
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, path)
    except FileExistsError:
        raise NaraError("CSV 대상이 이미 존재합니다. 기존 파일은 보존했습니다.", 2) from None
    except OSError:
        raise NaraError("CSV 저장에 실패했습니다. 경로·권한·파일시스템을 확인하세요.") from None
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
