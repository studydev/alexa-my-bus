# Project Guidelines — echo-bus (BusWatch Home)

## Overview
Echo Show 10/15용 실시간 버스 도착 정보 Alexa Custom Skill 백엔드.
GBIS 공공데이터 API → FastAPI → Alexa Skill (APL 디스플레이).

## Tech Stack
- **Language:** Python 3.12
- **Framework:** FastAPI + Uvicorn
- **Alexa SDK:** ask-sdk-core, ask-sdk-webservice-support
- **HTTP Client:** httpx (async)
- **Config:** pydantic-settings (`.env` + `settings.json` 동적 오버라이드)
- **Container:** Docker (python:3.12-slim 기반)
- **Deploy Target:** TrueNAS 25.10.3 Docker (192.168.1.92)

## Architecture
```
backend/app/
├── main.py          # FastAPI 엔트리포인트, 라우트 정의
├── config.py        # 환경변수 + settings.json 동적 설정
├── gbis/client.py   # GBIS 버스 도착 정보 API 클라이언트
├── weather/client.py # OpenWeatherMap 날씨 API 클라이언트
├── alexa/
│   ├── handler.py   # Alexa Intent 핸들러 (LaunchRequest, BusArrival 등)
│   └── apl.py       # APL 문서 로더
├── apl_documents/   # APL JSON 템플릿
└── static/          # 설정 웹 UI (settings.html, preview.html)
```

## Code Conventions
- 모든 API 호출은 `httpx.AsyncClient`로 async 처리
- 데이터 모델은 `@dataclass` 사용 (Pydantic model이 아님)
- 설정값은 `app.config`의 `get_active_*()` 함수로 접근 (settings.json 동적 오버라이드 지원)
- 한국어 주석, 한국어 로그 메시지 사용
- Import 순서: stdlib → third-party → local (`app.`)
- 타입 힌트: `int | None` (PEP 604 union 문법)

## Build & Deploy
```bash
# 로컬 개발
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload --app-dir .

# 원클릭 배포 (TrueNAS)
make deploy        # rsync → docker build → restart → health check

# 개별 단계
make sync          # 소스 동기화만
make build         # sync + 이미지 빌드
make logs          # 컨테이너 로그
make health        # 헬스체크
```

## Docker
- 빌드 전용: `docker-compose.yml` — 이미지 `backend-buswatch:latest` 생성
- 실행용: `docker-compose.truenas.yml` — TrueNAS Custom App, 포트 8081→8080
- `.env`와 `settings.json`은 볼륨 마운트 (이미지에 포함하지 않음)

## API Endpoints
| Method | Path | 용도 |
|--------|------|------|
| POST | `/alexa` | Alexa Skill 요청 |
| GET | `/health` | 헬스체크 |
| GET | `/api/bus-arrival` | 디버깅용 도착 정보 |
| GET | `/settings` | 설정 웹 UI |
| GET/PUT | `/api/settings` | 설정 조회/저장 |
| GET | `/api/stations/search?keyword=` | 정류소 검색 |
| GET | `/api/stations/{id}/routes` | 경유 노선 조회 |

## Key Patterns
- **GBIS API 응답:** `response.msgBody.busArrivalItem` 구조, `flag` 값으로 운행 상태 판별 (RUN/PASS/STOP/WAIT)
- **APL 디스플레이:** `apl_documents/*.json` 템플릿에 데이터 바인딩, 60초 간격 자동 갱신 (handleTick + SendEvent)
- **버스 색상:** routeTypeName 기반 — 직행/좌석→빨강, 일반→파랑, 마을→초록
- **에러 처리:** GBIS API 장애 시 오류 APL 화면 표시, httpx timeout 10초

## Infrastructure
- 배포 서버: TrueNAS (192.168.1.92), 경로 `/mnt/workspace/custom_apps/echo-bus`
- 계정: `studydev` (SSH/rsync)
- 개발 PC: Mac mini M4 (192.168.1.109)
- 자세한 인프라 구성은 `docs/infrastructure.md` 참조

## Documentation Rules
기능 추가·변경·삭제 시 아래 문서를 함께 업데이트해야 한다:

| 변경 유형 | 업데이트 대상 |
|-----------|-------------|
| API 엔드포인트 추가/변경 | `README.md` (API 엔드포인트 표), 이 파일의 API Endpoints 섹션 |
| 프로젝트 파일/폴더 추가/삭제 | `README.md` (프로젝트 구조 트리) |
| 배포 방식 변경 | `README.md` (배포 섹션), `docs/infrastructure.md`, `docs/cicd.md` |
| 환경변수·설정 키 추가 | `.env.example`, `README.md` (환경 설정 섹션) |
| 새 Alexa Intent 추가 | `README.md` (음성 명령 표), `skill-package/` 인터랙션 모델 |
| 주요 기능 추가/변경 | `README.md` (주요 기능 표) |
| 외부 패키지 추가/삭제 | `backend/requirements.txt`, 이 파일의 Tech Stack 섹션 |
| 인프라·서버 변경 | `docs/infrastructure.md` |

코드 변경과 문서 업데이트는 **같은 작업 단위**로 수행한다. 문서만 나중에 따로 하지 않는다.
