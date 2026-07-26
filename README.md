# StockScope

미국 주식 **기술적 분석 스크리닝** + **매매 진입 타이밍 시그널** 웹 서비스.  
두 서비스가 완전 독립으로 동작하며 Watchlist로 연동된다.

---

## 서비스 구성

| 서비스 | URL | 핵심 질문 |
|--------|-----|---------|
| 스크리닝 | `/screen` | 이 종목이 기술적으로 건강한가? |
| 매매시그널 | `/signals` | 지금 진입 타이밍인가? |
| About | `/about` | 시스템 설명 |

---

## 주요 기능

### 스크리닝 `/screen`
- **Finviz 사전 필터** — 미국 상장 · 평균거래량 2M↑ · 주가 $10↑ · 상대거래량 1.5배↑ ·
  MA20/50/200 위 · EPS QoQ 양수 (`config.py: FINVIZ_FILTERS`)
- **7개 기술적 체크리스트** — MA 정배열, RSI, MACD, 볼린저밴드, 거래량, 지지선, 추세 지속성
- **S / A / B / SKIP 등급** — 비율 기반 자동 분류, 목표가(+8%/+15%) · 손절(-7%) 자동 계산
- **펀더멘털 배지** — 실적발표 D-N, 숏비율, 애널리스트 목표가, 내부자 매수 여부
- **외부 시그널** — Google Trends 관심도, 의원 거래 내역
- **사이드바 라이브** — SPY · VIX · 공포탐욕지수 (15분 캐시), FRED 매크로 (7일 캐시)

### 매매시그널 `/signals`
- **3축 독립 스코어링** — 진입 포지션(40%) + 모멘텀 강도(35%) + 구조 확인(25%) + 수급 보너스(+5%)
  - **진입 포지션**: ATR 진입존(MA60~MA20+0.5ATR) 위치 + BB %B 과매도 위치
  - **모멘텀 강도**: RSI 종형 곡선(45~65 최고점) + ADX 추세 강도
  - **구조 확인**: LiquiditySweep / FVG / POC 기관 신호 + 캔들 패턴
  - **수급 보너스**: CMF + OBV 이중 확인 시 가산 (최대 +0.05)
- **STRONG BUY / BUY / HOLD / NO SIGNAL** 4등급, 진입가 밴드 + 손절가 표시
- **SPY MA50 국면 필터** — 하락장(SPY < MA50) 시 STRONG BUY·BUY → HOLD 자동 캡핑
- **실적발표 캡핑** — D-0~3 시 STRONG BUY·BUY → HOLD, D-4~7 시 STRONG BUY → BUY (변동성 함정 회피)
- **EXIT 조건 감지** — 손절선 이탈 / RSI > 78 / MA 역배열 전환 / 진입존 극단 이탈 시 카드에 `⚠ EXIT` 배지 + 모달에 사유 표시
- **Confluence Check** — 구조 지지·모멘텀 회복·자금 유입 3개 독립 레이어 동시 충족 여부 표시
- **관심종목 관리** — Watchlist 추가/삭제, 서버 영구 저장 (`data/watchlist.json`)
- **유니버스 자동 확장** — Watchlist가 10개 미만이면 Finviz 필터 결과를 **시가총액 내림차순**으로 채워 30개 랭킹 보드 구성
- **SSE 실시간 스트리밍** — 분석 진행 상황 즉시 반영

### 캔들 차트 모달
- **Lightweight Charts 4.2** — OHLCV 캔들스틱 + MA20
- **매수 마커 6종** — MA5골든 / FVG반등 / RSI+볼륨 / RSI반등 / MACD전환 / 볼륨급증
- **매도 마커 4종** — 데드크로스 / RSI과열이탈 / MA20붕괴 / 샹들리에이탈(Chandelier Exit)

---

## Tech Stack

| 레이어 | 기술 |
|--------|------|
| 백엔드 | FastAPI + Jinja2 + SSE, Python 3.12 |
| 데이터 | yfinance · pytrends · quiverquant |
| 스크래핑 | Finviz 스크리너 (requests + lxml 직접 파싱), CNN 공포탐욕지수 |
| 외부 API | FRED REST API (매크로), Yahoo Finance Search (티커 자동완성) |
| 캐시 | diskcache (TTL별 다단계) |
| 프론트엔드 | Vanilla JS · TomSelect · Lightweight Charts 4.2 |
| 배포 | Render (free plan) |
| 스케줄 | GitHub Actions (keepalive + daily batch) |

---

## 로컬 실행

```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. 환경 변수 (.env 파일 생성)
FRED_API_KEY=your_fred_api_key          # fred.stlouisfed.org 무료 발급
QUIVERQUANT_API_KEY=your_qq_api_key     # quiverquant.com 무료 tier
REFRESH_TOKEN=your_secret_token         # 임의 생성 예시:
                                        # python3 -c "import secrets; print(secrets.token_hex(32))"

# 3. 서버 실행
./run.sh
# 또는 직접 실행:
uvicorn api.main:app --reload --port 8000
```

`http://localhost:8000` 접속 → `/about` 자동 리다이렉트.

---

## 환경 변수

| 변수 | 필수 | 설명 |
|------|:----:|------|
| `FRED_API_KEY` | 권장 | FRED 매크로 데이터. 없으면 사이드바 매크로 배너 숨김 |
| `QUIVERQUANT_API_KEY` | 선택 | 의원 거래 데이터. 없으면 해당 배지 스킵 |
| `REFRESH_TOKEN` | 배포 필수 | GitHub Actions → Render 배치 refresh 인증 |
| `RENDER_URL` | 배포 필수 | GitHub Actions keepalive · daily-batch 워크플로우에서 사용 |

---

## 프로젝트 구조

```
fin_auto/
├── api/
│   ├── main.py                 # FastAPI 앱, lifespan, refresh 엔드포인트
│   ├── deps.py                 # Jinja2 templates 싱글턴 + 필터 등록
│   └── routes/
│       ├── screen.py           # /screen, /stream/screen SSE
│       ├── signals.py          # /signals, /stream/signals SSE
│       ├── watchlist.py        # /api/watchlist CRUD
│       ├── chart.py            # /api/chart-data/{ticker}
│       └── tickers.py          # /api/tickers 자동완성
├── services/
│   ├── screener_service.py     # run_analysis() — 스크리닝 파이프라인
│   └── signal_service.py       # run_signal_analysis() — 시그널 파이프라인
├── screener/
│   ├── data_fetcher.py         # OHLCV 일봉·분봉 수집, TTL 캐시
│   ├── indicators.py           # 기술적 지표 계산 (MA/RSI/MACD/BB/ATR/StochRSI/OBV/CMF)
│   ├── checklist.py            # 7개 체크리스트 채점, RSI 하드게이트
│   ├── grader.py               # S/A/B/SKIP 비율 기반 등급
│   ├── signal_scorer.py        # 3축 가중 시그널 채점 + EXIT 조건 판정
│   ├── buy_signal.py           # 매수 마커 생성 (6종 이유)
│   ├── sell_signal.py          # 매도 마커 생성 (4종 이유)
│   ├── finviz_filter.py        # Finviz 사전 필터 (requests + lxml, 페이지네이션)
│   ├── cache_manager.py        # diskcache 중앙 관리
│   ├── watchlist_store.py      # Watchlist JSON CRUD
│   ├── fundamental_fetcher.py  # 펀더멘털 (실적일/숏비율/목표가)
│   ├── macro_fetcher.py        # FRED + yfinance 사이드바 라이브 데이터
│   ├── fear_greed_fetcher.py   # CNN 공포탐욕지수
│   ├── trends_fetcher.py       # Google Trends
│   ├── congress_fetcher.py     # 의원 거래 내역
│   ├── insider_fetcher.py      # SEC Form 4 내부자 거래
│   ├── news_filter.py          # 뉴스 위험 키워드 필터
│   ├── nl_generator.py         # 기술적 지표 기반 자연어 브리핑
│   └── batch_scheduler.py      # 서버 시작 시 백그라운드 배치
├── templates/
│   ├── base.html               # 사이드바 + 매크로 레이아웃
│   ├── screen.html             # 스크리닝 대시보드
│   ├── signals.html            # 매매시그널 대시보드
│   ├── about.html              # 시스템 설명
│   └── partials/
│       ├── screen_cards.html   # 스크리닝 결과 카드 리스트 (Jinja2 partial)
│       ├── _screen_card.html   # 스크리닝 카드 단일 매크로
│       ├── _screen_card_extras.html # 펀더멘털·외부 시그널 배지
│       └── signal_cards.html   # 시그널 결과 카드 (Jinja2 partial)
├── static/
│   ├── css/                    # base · layouts · shells · sidebars · variants
│   │                           #   + screen · signals · about
│   └── js/                     # screen.js · signals.js
├── data/
│   └── watchlist.json          # Watchlist 영구 저장 (git 제외)
├── docs/
│   ├── design_doc.md           # 전체 시스템 설계
│   ├── architecture.md         # 아키텍처 + API 목록
│   ├── signal-scoring-logic.md # 시그널 스코어링 수식 레퍼런스
│   ├── changelog.md
│   ├── adr/                    # 의사결정 기록 ADR-001 ~ 019
│   ├── skills/                 # 재사용 구현 스킬 레퍼런스 (5종)
│   └── phases/                 # 페이즈별 구현 이력 + 향후 계획
├── tests/
├── .github/workflows/
│   ├── keepalive.yml           # 10분 간격 ping (Render 슬립 방지)
│   └── daily-batch.yml         # KST 07:00 배치 refresh 트리거
├── INDICATORS.md               # 사용 지표 논리 + 계산식 레퍼런스
├── CLAUDE.md                   # Claude Code 작업 규약 (워크플로·문서 로딩 전략)
├── DEVLOG.md                   # 개발 일지
├── config.py                   # 전역 설정값
├── render.yaml                 # Render 배포 설정
└── .python-version             # Python 3.12.0 고정
```

---

## 등급 기준

### 스크리닝 (체크리스트 비율 기반)

| 등급 | 조건 | 행동 |
|------|------|------|
| S | score/max ≥ 0.67 | 즉시 진입 검토 |
| A | score/max ≥ 0.44 | 분할 진입 검토 |
| B | score/max ≥ 0.22 | 대기 |
| SKIP | RSI ≥ 80 또는 비율 미달 | 진입 금지 |

체크리스트 항목 비활성화 시 분모(max) 자동 조정.

### 매매시그널 (3축 가중 합산)

| 등급 | 조건 |
|------|------|
| STRONG BUY | 가중합 ≥ 0.60 + MA 정배열(MA20 > MA60) |
| BUY | 가중합 ≥ 0.40 (또는 MA 역배열 시 0.60 이상도 BUY로 캡핑) |
| HOLD | 가중합 ≥ 0.20 |
| NO SIGNAL | 진입 포지션 또는 모멘텀이 0 / 가중합 < 0.20 |

### 등급 캡핑 (점수와 무관하게 하향 조정)

| 트리거 | 캡핑 | 표시 |
|--------|------|------|
| SPY < MA50 (하락장) | STRONG BUY·BUY → HOLD | 국면 경고 배너 |
| 실적발표 D-0~3 | STRONG BUY·BUY → HOLD | `📅 발표임박` 배지 |
| 실적발표 D-4~7 | STRONG BUY → BUY | `📅 발표임박` 배지 |

### EXIT 조건 (등급과 독립, 보유 포지션 대상)

손절선 이탈 / RSI > 78 / MA 일봉 역배열 전환 / 진입존 극단 이탈(`entry_high + ATR` 초과) 중
하나라도 충족되면 카드에 `⚠ EXIT` 배지, 모달에 사유 목록 표시.

---

## GitHub Actions 설정

Render free plan은 15분 비활성 시 슬립 → 두 워크플로우로 방지.

### Repository Secrets

**Settings → Secrets and variables → Actions**:

| Secret | 값 |
|--------|----|
| `RENDER_URL` | `https://your-app.onrender.com` |
| `REFRESH_TOKEN` | Render 환경변수에 설정한 동일 토큰 |

### Render Environment Variables

**Render 대시보드 → Environment 탭**:

| 변수 | 값 |
|------|----|
| `FRED_API_KEY` | FRED API 키 |
| `QUIVERQUANT_API_KEY` | QuiverQuant API 키 |
| `REFRESH_TOKEN` | GitHub Secrets의 `REFRESH_TOKEN`과 동일 |

---

## 지표 레퍼런스

사용하는 모든 기술적 지표의 계산식과 논리 → **[INDICATORS.md](INDICATORS.md)**
