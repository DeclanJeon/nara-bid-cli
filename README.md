# nara-bid-cli

나라장터 공공데이터 API로 **입찰공고 제목을 검색하고 CSV로 저장**하는 작은 Python CLI입니다.
명령은 `nara search` 하나입니다. 웹 서버·DB·AI·자동 투찰은 사용하지 않습니다.

> **상태: 실험적 MVP 0.1.0.** Linux/Python 3.12에서 실제 API 조회·CSV 저장을 확인했습니다.
> 독립 QA의 API 종료 분 경계 검증은 추가 근거 재검토 중이며, 운영 검증 완료 제품으로 보장하지 않습니다.
> 최종 일정·참가자격·공고 내용은 반드시 나라장터 원문에서 확인하세요.

## 주요 기능

- 용역(`service`), 물품(`goods`), 공사(`construction`) 중 한 분야 조회
- 최근 1~31일 게시공고의 공고명 부분 문자열 검색
- 반복 지정 가능한 제외어
- 전체 페이지 수집 후 결과 출력, 오류와 정상 0건 구분
- Excel 호환 UTF-8 BOM CSV 저장, 기존 파일 덮어쓰기 방지
- 제한된 재시도 및 실행당 HTTP 요청 시도 최대 100회
- 인증키는 `NARA_API_KEY` 환경변수에서만 읽기

## 1. 내려받기

GitHub의 **Code → Download ZIP**으로 내려받아 압축을 풀거나 Git으로 복제합니다.

```bash
git clone https://github.com/DeclanJeon/nara-bid-cli.git
cd nara-bid-cli
```

이후 명령은 `pyproject.toml`이 있는 폴더에서 실행하세요. ZIP 안에서 바로 실행하지 마세요.

## 2. 실행 환경 설치

Python 3.11 이상과 [uv](https://docs.astral.sh/uv/getting-started/installation/)가 필요합니다.
검증에 사용한 Python 3.12를 설치하고 고정된 의존성으로 준비합니다.

```bash
uv python install 3.12
uv sync --frozen --python 3.12
uv run nara search --help
```

첫 설치에는 인터넷이 필요합니다. 의존성은 프로젝트의 `.venv`에 설치됩니다.
도움말이 표시되면 CLI 설치가 완료된 것입니다. 도움말에는 API 키가 필요 없습니다.

## 3. API 키 설정

[공공데이터포털의 조달청_나라장터 입찰공고정보서비스](https://www.data.go.kr/data/15129394/openapi.do)에
활용신청한 뒤 일반 인증키를 사용하세요. 이 저장소는 인증키를 제공하지 않습니다.

실제 키를 명령어 본문·코드·README·CSV·이슈·로그에 붙여넣지 마세요.
아래 명령은 키를 화면과 셸 명령 이력에 직접 남기지 않고 입력받습니다.

### macOS / Linux — Bash

기본 셸이 다르면 먼저 `bash`를 실행한 다음, 아래 명령을 **한 줄씩** 실행합니다.
첫 줄에서 입력을 기다리면 키를 붙여넣고 Enter를 누르세요. 키가 화면에 보이지 않아도 정상입니다.

```bash
read -r -s -p "나라장터 API 키: " NARA_API_KEY
echo
export NARA_API_KEY
```

### Windows — PowerShell

첫 줄에서 키를 붙여넣고 Enter를 누른 뒤 나머지 줄을 실행합니다.

```powershell
$secureKey = Read-Host "나라장터 API 키" -AsSecureString
$env:NARA_API_KEY = [System.Net.NetworkCredential]::new("", $secureKey).Password
Remove-Variable secureKey
```

키는 **현재 터미널과 자식 프로세스에서만** 사용됩니다. 새 터미널에서는 다시 설정해야 합니다.
`.env` 파일 자동 로딩은 지원하지 않습니다. 원문 키와 URL 인코딩된 키를 지원하며,
키를 다시 수동으로 URL 인코딩할 필요는 없습니다.

## 4. 검색하고 CSV 저장하기

```bash
# 기본: 용역, 최근 7일
uv run nara search "미디어아트" --csv media-art.csv

# VR 제목 검색
uv run nara search "VR" --days 7 --csv vr.csv

# 물품 / 제외어 / 최근 14일
uv run nara search "컴퓨터" --category goods --days 14 --exclude "임대" --csv computers.csv

# 공사
uv run nara search "보수" --category construction --days 1

# 제외어는 여러 번 지정 가능
uv run nara search "시스템" --exclude "유지보수" --exclude "임대"
```

CSV는 별도 경로를 지정하지 않으면 **현재 터미널의 작업 폴더**에 저장됩니다.
예를 들어 `media-art.csv`는 프로젝트 폴더에서 실행했다면 그 폴더에 생깁니다.
파일을 Excel로 열 수 있으며, 공고 원문 주소는 `url` 열에 있습니다.

이미 같은 파일이 있으면 덮어쓰지 않습니다. `media-art-2.csv`처럼 새 이름을 지정하세요.
정상 0건인 경우에도 열 이름만 있는 CSV가 생성됩니다. 조회 중 실패한 경우에는 결과 CSV를 만들지 않습니다.

### 옵션

| 입력 | 기본값 / 의미 |
|---|---|
| `KEYWORD` | 필수. 공고명에 포함될 단일 문자열 |
| `--category` | `service`(용역), `goods`(물품), `construction`(공사). 기본 용역 |
| `--days` | 실행일 포함 최근 1~31일, 기본 7일. 한국 시간의 공고게시일 기준 |
| `--exclude` | 하나라도 제목에 포함되면 제외. 반복 지정 가능 |
| `--csv PATH` | 선택. 기존 파일을 덮어쓰지 않는 CSV 저장 경로 |

### CSV 열

```text
category,notice_no,notice_order,title,agency,published_at,deadline_at,url,fetched_at
```

번호·차수는 문자열로 보존하고, 날짜는 한국 시간 오프셋을 포함합니다.
기관·마감·원문 URL이 없으면 CSV에서는 빈 값으로 표시합니다.
수식으로 해석될 수 있는 텍스트에는 안전 처리를 위해 작은따옴표를 앞에 추가합니다.

## 검색할 때 알아둘 점

- **제목만 검색합니다.** 과업지시서·제안요청서·첨부문서 본문은 검색하지 않습니다.
- NFKC·영문 대소문자·연속 공백을 정규화한 부분 문자열 검색입니다. 자동 동의어 확장은 없습니다.
- `VR`은 `LBVR`이나 `AVR`에도 일치합니다. 가상현실 관련성까지 판정하지 않습니다.
- `인공지능`과 `인공 지능`은 서로 다른 검색어입니다.
- 마감 공고를 자동 제외하지 않습니다. 취소 공고도 포함될 수 있습니다.
- 과거에 게시되어 아직 진행 중이어도 조회 게시기간 밖이면 결과에 나오지 않습니다.
- 참가자격·지역 제한·면허·예산·낙찰 가능성을 판정하지 않습니다. 자동 투찰도 하지 않습니다.
- 분야·기간·조회시각 등 안내와 오류는 stderr, 결과 표는 stdout으로 출력합니다.

## 오류 해결

| 증상 | 확인 사항 |
|---|---|
| `NARA_API_KEY` 오류 | 검색할 터미널에서 키를 다시 설정하세요. |
| 인증·승인 관련 API 오류 | 해당 서비스의 활용신청 상태·키·계정 호출 한도를 확인하세요. |
| CSV 파일이 이미 존재함 | 다른 파일명으로 저장하세요. |
| CSV 저장 오류 | 부모 폴더·권한·디스크·파일시스템을 확인하세요. |
| 조회 미완료·건수 변경·요청 한도 | `--days 1`처럼 기간을 줄이거나 잠시 후 다시 조회하세요. |
| 결과 0건 | 분야·기간·키워드를 확인하세요. 0건은 정상 결과일 수 있습니다. |

종료 코드: `0` 성공(0건 포함), `2` 입력·키 누락·기존 CSV 충돌, `1` API·통신·수집·저장 오류.

CSV는 임시 파일 쓰기 완료 후 하드링크로 확정합니다. 하드링크를 지원하지 않는 파일시스템에서는
저장 오류로 종료하며, 기존 파일을 덮어쓰는 방식으로 우회하지 않습니다.
원천 데이터는 조회 중 변경될 수 있습니다. 완전한 시점 스냅샷과 무누락 수집을 보장하지 않습니다.

## 선택: 폴더 밖에서도 `nara`로 실행하기

```bash
uv tool install --python 3.12 .
nara search "미디어아트" --csv media-art.csv
```

이 방법은 별도 사용자 전용 환경에 설치합니다. `uv tool install`은 `uv.lock`을 사용하지 않으므로
프로젝트 방식과 의존성 버전이 다를 수 있습니다. 고정 버전 재현에는 위의 `uv sync --frozen` 방식을 사용하세요.
설치 도구의 실행 폴더가 PATH에 있어야 하며, 필요하면 uv 안내에 따라 터미널을 다시 여세요.

제거:

```bash
uv tool uninstall nara-bid-cli
```

## 개발·테스트

```bash
uv sync --frozen
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
uv build
```

기존 합성 테스트 52개와 Linux/Python 3.12의 실제 세 분야 API 조회·CSV 저장을 확인했습니다.
합성 테스트에는 실제 인증키가 필요 없습니다. Windows/macOS 실동작·장기 운영·원문 전수 대조는 미검증입니다.
실제 API의 종료 분에 초 단위 공고가 포함되는 표본을 관측했지만, 모든 시점의 경계 동작을 일반적으로 보장하지 않습니다.

## 공개 범위와 보안

소스·합성 테스트·설정·이 README만 공개합니다. 실제 인증키·사용자 첨부·원본 API 응답·실제 조회 CSV·내부 검토 자료는 포함하지 않습니다.
키가 노출되었다면 발급처에서 폐기·재발급하고 Git 이력에서도 노출 여부를 확인하세요.
보안 문제를 알릴 때는 키나 비공개 원본을 공개 이슈에 올리지 마세요.
