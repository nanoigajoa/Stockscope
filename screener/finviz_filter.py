import time

import requests
from lxml import html

from config import FINVIZ_FILTERS

# ETF 패턴 — 이름에 포함되면 제거
_ETF_KEYWORDS = ("ETF", "FUND", "TRUST", "SHARES", "INDEX", "NOTES", "PROSHARES")

_FINVIZ_URL  = "https://finviz.com/screener.ashx"
_USER_AGENT  = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_ROWS_PER_PAGE = 20
_MAX_PAGES     = 20     # 안전장치: 최대 400개


def _is_etf(ticker: str, company_name: str) -> bool:
    name_upper = company_name.upper()
    return any(kw in name_upper for kw in _ETF_KEYWORDS)


def _parse_rows(page_html: str) -> list[tuple[str, str]]:
    """Overview 테이블에서 (티커, 회사명) 추출.

    Finviz 티커 셀은 로고 이미지 + 폴백 이니셜 <span>을 함께 담고 있어
    셀 전체 텍스트를 평면화하면 "C"(이니셜)와 "CLBK"(티커)가 뒤섞인다.
    (finviz 라이브러리가 td//text()로 긁어 컬럼이 한 칸씩 밀리는 원인)
    → 텍스트 대신 td의 data-boxover-* 속성을 우선 사용하고,
      없으면 a.tab-link 앵커 텍스트로 폴백한다.
    """
    page = html.fromstring(page_html)
    out: list[tuple[str, str]] = []

    for row in page.cssselect('tr[valign="top"]'):
        tds = row.xpath("td")
        if len(tds) < 3:
            continue

        cell    = tds[1]
        ticker  = (cell.get("data-boxover-ticker") or "").strip()
        company = (cell.get("data-boxover-company") or "").strip()

        if not ticker:
            link = cell.cssselect("a.tab-link")
            if link:
                ticker = link[0].text_content().strip()
        if not company:
            company = tds[2].text_content().strip()

        if ticker:
            out.append((ticker.upper(), company))

    return out


def _fetch_all_rows(filters: list[str], order: str, retries: int) -> list[tuple[str, str]]:
    """필터 결과를 페이지네이션으로 전부 수집. 실패 시 지수 백오프 재시도."""
    params_base = {"v": "111", "f": ",".join(filters), "o": order}
    headers     = {"User-Agent": _USER_AGENT}

    rows: list[tuple[str, str]] = []
    offset = 1

    with requests.Session() as session:
        for _ in range(_MAX_PAGES):
            params = dict(params_base)
            if offset > 1:
                params["r"] = str(offset)

            page_html = None
            for attempt in range(retries):
                try:
                    resp = session.get(_FINVIZ_URL, params=params, headers=headers, timeout=10)
                    resp.raise_for_status()
                    page_html = resp.text
                    break
                except Exception as e:
                    if attempt < retries - 1:
                        time.sleep(2 ** attempt)
                    else:
                        print(f"[Finviz] 연결 실패 (offset={offset}): {e}")
                        return rows

            page_rows = _parse_rows(page_html or "")
            if not page_rows:
                break

            rows.extend(page_rows)
            if len(page_rows) < _ROWS_PER_PAGE:
                break
            offset += _ROWS_PER_PAGE

    return rows


def get_filtered_tickers(
    retries: int = 3,
    include_penny: bool = False,
    order: str = "ticker",
) -> list[str]:
    """Finviz 필터 적용 후 ETF 제거한 티커 리스트 반환.
    include_penny=True: sh_price(≥$10) 필터 제거, 거래량 기준 완화.
    order: Finviz 정렬 키. 기본 "ticker"(알파벳). 호출측이 결과를 앞에서 잘라
           쓰는 경우 "-marketcap" / "-volume" 등으로 의미 있는 순서를 지정한다.
    """
    base = dict(FINVIZ_FILTERS)
    if include_penny:
        base.pop("sh_price", None)          # 가격 하한 제거
        base["sh_avgvol"] = "o500"          # 거래량 기준 완화 (500k)
    filters = [f"{k}_{v}" for k, v in base.items()]

    all_tickers = _fetch_all_rows(filters, order, retries)

    if not all_tickers:
        print("[Finviz] 필터 조건에 맞는 종목 없음.")
        return []

    # 중복 제거(페이지 경계 대비) + 순서 유지
    seen: set[str] = set()
    tickers: list[str] = []
    for t, name in all_tickers:
        if t in seen or _is_etf(t, name):
            continue
        seen.add(t)
        tickers.append(t)

    removed = len(all_tickers) - len(tickers)
    print(f"[Finviz] {len(all_tickers)}개 발견 → ETF/중복 {removed}개 제거 → 개별주 {len(tickers)}개")
    return tickers
