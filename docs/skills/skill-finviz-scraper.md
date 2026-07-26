## Skill: Finviz Scraper

- **Purpose:** Finviz 스크리너 필터를 적용해 조건에 맞는 미국 주식 티커 리스트를 반환한다.
- **Inputs:** `FINVIZ_FILTERS: dict` (config.py에서 로드), `include_penny: bool`, `order: str`
- **Outputs:** `list[str]` — 티커 리스트 (ETF·중복 제거 완료)
- **File:** `screener/finviz_filter.py`
- **Deps:** `requests` + `lxml` (finviz 라이브러리 미사용 — 아래 참조)

### Best Practices
- 필터 키를 `f"{k}_{v}"` 형식으로 조합해 `f=` 쿼리 파라미터에 콤마로 연결
- **티커는 텍스트 평면화(`td//text()`)로 뽑지 말고 `td`의 `data-boxover-ticker` 속성 사용**
  (없으면 `a.tab-link` 앵커 텍스트로 폴백)
- ETF 키워드(`ETF`, `FUND`, `TRUST`, `SHARES`, `INDEX`, `NOTES`, `PROSHARES`) 기반 제거
- 페이지네이션: `r=1, 21, 41...`, 페이지 결과가 20개 미만이면 종료, 최대 20페이지 캡
- 재시도 3회, 지수 백오프(1s, 2s, 4s) 적용
- 네트워크 실패 시 빈 리스트 반환 (caller가 처리)
- **호출측이 결과를 앞에서 잘라 쓰면 `order`를 반드시 지정** —
  기본 `"ticker"`는 알파벳순이라 A로 시작하는 종목만 남는다 (`"-marketcap"`, `"-volume"` 등)

### Anti-patterns
- `finviz` 라이브러리의 `Screener(...).data` 사용 → **컬럼이 한 칸씩 밀린다.**
  Finviz 티커 셀이 로고 `<img>` + 폴백 이니셜 `<span>C</span>`을 함께 담고 있어
  `td//text()`가 `['C', 'CLBK']` 2개 노드를 반환 → 헤더 11개와 `zip` 시 전 컬럼 shift,
  `Ticker`에 알파벳 한 글자가 들어가고 `Volume`은 유실됨
- 재시도 없이 단일 요청 → Finviz 일시 차단 시 전체 실패
- ETF 제거 없이 반환 → 채점 결과에 ETF 혼입
- 정렬 미지정 + 상위 N개 절단 → 유니버스가 알파벳 앞쪽으로 편향

### Example
```python
from screener.finviz_filter import get_filtered_tickers

tickers = get_filtered_tickers()                      # 알파벳순 전체
top30   = get_filtered_tickers(order="-marketcap")[:30]   # 시총 상위 30
penny   = get_filtered_tickers(include_penny=True)    # 가격 하한 해제
```

### Verification
```python
# Finviz 자체 표기 "#1 / N Total"과 수집 개수가 일치해야 한다
assert len(get_filtered_tickers(include_penny=True)) == N
```
