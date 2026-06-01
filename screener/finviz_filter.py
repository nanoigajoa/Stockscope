import time
from finviz.screener import Screener
from config import FINVIZ_FILTERS

# ETF 패턴 — 이름에 포함되면 제거
_ETF_KEYWORDS = ("ETF", "FUND", "TRUST", "SHARES", "INDEX", "NOTES", "PROSHARES")


def _is_etf(ticker: str, company_name: str) -> bool:
    name_upper = company_name.upper()
    return any(kw in name_upper for kw in _ETF_KEYWORDS)


def get_filtered_tickers(retries: int = 3, include_penny: bool = False) -> list[str]:
    """Finviz 필터 적용 후 ETF 제거한 티커 리스트 반환.
    include_penny=True: sh_price(≥$10) 필터 제거, 거래량 기준 완화.
    """
    base = dict(FINVIZ_FILTERS)
    if include_penny:
        base.pop("sh_price", None)          # 가격 하한 제거
        base["sh_avgvol"] = "o500"          # 거래량 기준 완화 (500k)
    filters = [f"{k}_{v}" for k, v in base.items()]

    for attempt in range(retries):
        try:
            screener = Screener(filters=filters, table="Overview", order="ticker")
            rows = screener.data if screener.data else []
            break
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"[Finviz] 연결 실패: {e}")
                return []

    if not rows:
        print("[Finviz] 필터 조건에 맞는 종목 없음.")
        return []

    all_tickers = [(r.get("Ticker", ""), r.get("Company", "")) for r in rows]
    tickers = [t for t, name in all_tickers if t and not _is_etf(t, name)]

    removed = len(all_tickers) - len(tickers)
    print(f"[Finviz] {len(all_tickers)}개 발견 → ETF {removed}개 제거 → 개별주 {len(tickers)}개")
    return tickers
