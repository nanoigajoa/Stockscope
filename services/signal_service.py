"""
매매시그널 서비스 — Watchlist 티커를 받아 4카테고리 시그널 채점.
스크리닝 파이프라인과 완전 독립으로 실행 가능.
"""
import logging
from concurrent.futures import ThreadPoolExecutor

from screener.data_fetcher import fetch_ohlcv, fetch_intraday, is_market_open
from screener.signal_scorer import score_signals
from screener import watchlist_store

logger = logging.getLogger(__name__)

_GRADE_ORDER = {"STRONG BUY": 0, "BUY": 1, "HOLD": 2, "NO SIGNAL": 3}


def run_signal_analysis(tickers: list[str] | None = None) -> dict:
    """
    Watchlist(또는 지정 티커)에 대해 4카테고리 시그널 채점 후 결과 반환.

    Args:
        tickers: None이면 watchlist_store.load() 자동 로드

    Returns:
        {
            "results": [...],    # STRONG BUY 순 정렬
            "summary": {...},
            "watchlist": [...]   # 실제 사용된 티커 목록
        }
    """
    if tickers is None:
        tickers = watchlist_store.load()

    tickers = [t.strip().upper() for t in tickers if t.strip()]

    if not tickers:
        return {
            "results": [],
            "summary": {"total": 0, "strong_buy": 0, "buy": 0, "watch": 0, "no_signal": 0},
            "watchlist": [],
        }

    # 일봉 수집 (당일 캐시 재사용) — SPY 포함
    ohlcv_map = fetch_ohlcv(tickers + ["SPY"] if "SPY" not in tickers else tickers)
    market_open = is_market_open()

    # 시장 국면 필터: SPY MA50 기준 상승장/하락장 판단
    # 하락장(SPY < MA50)에서는 STRONG BUY·BUY → WATCH로 캡핑
    # 개별 종목 강세 신호가 맞더라도 시장 조류에 역행하는 진입 위험 차단
    spy_regime = True  # 데이터 오류 시 상승장 가정 (보수적)
    try:
        spy_df = ohlcv_map.get("SPY")
        if spy_df is not None and len(spy_df) >= 50:
            spy_ma50  = float(spy_df["Close"].rolling(50).mean().iloc[-1])
            spy_close = float(spy_df["Close"].iloc[-1])
            spy_regime = spy_close > spy_ma50
    except Exception:
        pass

    # 장 중이면 fast_info로 최신 가격 일괄 수집 (5분 캐시)
    live_prices: dict[str, float] = {}
    if market_open:
        from screener.cache_manager import cache as _cache
        from concurrent.futures import ThreadPoolExecutor as _TP
        import yfinance as yf

        def _live(tk: str) -> tuple[str, float]:
            ck = f"price_live_{tk}"
            cached = _cache.get(ck)
            if cached:
                return tk, cached
            try:
                p = float(yf.Ticker(tk).fast_info["lastPrice"] or 0)
                if p > 0:
                    _cache.set(ck, p, expire=300)
                    return tk, p
            except Exception:
                pass
            return tk, 0.0

        with _TP(max_workers=6) as ex:
            for tk, price in ex.map(_live, tickers):
                if price > 0:
                    live_prices[tk] = price

    # 펀더멘털 수집 (로고용)
    from screener.fundamental_fetcher import fetch_fundamentals
    fund_map = fetch_fundamentals(tickers)

    def _analyze(ticker: str) -> dict:
        df_daily = ohlcv_map.get(ticker)
        fund = fund_map.get(ticker, {})
        
        # website_domain 추출
        website = fund.get("website", "")
        domain = ""
        if website:
            domain = website.replace("http://", "").replace("https://", "").replace("www.", "").split("/")[0]

        if df_daily is None or df_daily.empty:
            return {
                "ticker": ticker, "price": 0.0,
                "signal_grade": "NO SIGNAL", "signal_score": 0.0,
                "signal_breakdown": {"entry": 0.0, "momentum": 0.0, "structure": 0.0, "volume": 0.0},
                "entry_low": None, "entry_high": None, "signal_stop": None,
                "confluence_count": 0, "confluence_layers": [], "confluence_detail": {},
                "extras": {
                    "short_name": fund.get("short_name", ""),
                    "website_domain": domain
                }
            }

        close_price = float(df_daily["Close"].iloc[-1])
        live_price  = live_prices.get(ticker, 0.0)
        price = live_price if live_price > 0 else close_price
        prev_price = float(df_daily["Close"].iloc[-2]) if len(df_daily) > 1 else close_price
        change = round((price - prev_price) / prev_price * 100, 2) if prev_price > 0 else 0.0
        df_hourly = fetch_intraday(ticker, "1h", "60d")
        sig = score_signals(df_daily, df_hourly)

        # 수익발표 근접 시 시그널 캡: 변동성 함정 방지
        days_to_earn = fund.get("days_to_earnings")
        if days_to_earn is not None:
            if 0 <= days_to_earn <= 3:
                if sig["signal_grade"] in ("STRONG BUY", "BUY"):
                    sig["signal_grade"] = "HOLD"
                    sig["earnings_cap"] = True
            elif 4 <= days_to_earn <= 7:
                if sig["signal_grade"] == "STRONG BUY":
                    sig["signal_grade"] = "BUY"
                    sig["earnings_cap"] = True

        return {
            "ticker": ticker,
            "price": price,
            "change": change,
            **sig,
            "extras": {
                "short_name": fund.get("short_name", ""),
                "website_domain": domain
            }
        }

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ticker: ex.submit(_analyze, ticker) for ticker in tickers}

    results = [futures[t].result() for t in tickers]

    # 하락장 캡핑: STRONG BUY / BUY → HOLD
    if not spy_regime:
        for r in results:
            if r["signal_grade"] in ("STRONG BUY", "BUY"):
                r["signal_grade"] = "HOLD"
                r["regime_capped"] = True   # UI 경고 표시용

    # STRONG BUY 순 정렬, 동점은 signal_score 내림차순
    results.sort(key=lambda r: (
        _GRADE_ORDER.get(r["signal_grade"], 9),
        -r["signal_score"],
    ))

    counts = {"strong_buy": 0, "buy": 0, "hold": 0, "no_signal": 0}
    for r in results:
        g = r["signal_grade"]
        if g == "STRONG BUY":
            counts["strong_buy"] += 1
        elif g == "BUY":
            counts["buy"] += 1
        elif g == "HOLD":
            counts["hold"] += 1
        else:
            counts["no_signal"] += 1

    logger.info(
        f"[Signal] 완료: {len(results)}개 | "
        f"STRONG BUY {counts['strong_buy']} | BUY {counts['buy']} | "
        f"HOLD {counts['hold']} | NO SIGNAL {counts['no_signal']}"
    )

    return {
        "results": results,
        "summary": {
            "total": len(results),
            **counts,
            "watch": counts["hold"],  # 하위 호환 (템플릿 watch 참조 대비)
            "market_open": market_open,
            "spy_regime": spy_regime,
        },
        "watchlist": tickers,
    }
