import logging
from fastapi import APIRouter, HTTPException

router = APIRouter()
logger = logging.getLogger(__name__)

_VALID_PERIODS = {"1mo", "3mo", "6mo", "1y", "2y", "3y", "5y"}


def _get_df(ticker: str, period: str = "6mo"):
    """캐시에서 df 조회. 없으면 지정 기간으로 수집."""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
    from screener.data_fetcher import fetch_ohlcv
    from screener.cache_manager import cache

    ticker = ticker.upper()
    cache_key = f"ohlcv_{ticker}_{period}"
    cached_data = cache.get(cache_key)

    if cached_data:
        return cached_data[1]

    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(fetch_ohlcv, [ticker], period)
        try:
            result = fut.result(timeout=20)
        except FuturesTimeoutError:
            raise HTTPException(status_code=503, detail="데이터 조회 시간 초과 (20s)")

    if not result or ticker not in result:
        raise HTTPException(status_code=404, detail=f"데이터 없음: {ticker}")

    return result[ticker]


def _to_ohlcv(df) -> list[dict]:
    """DataFrame → Lightweight Charts candlestick 포맷 (벡터화)."""
    import numpy as np
    dates = [str(ts.date() if hasattr(ts, "date") else ts) for ts in df.index]
    o = df["Open"].values
    h = df["High"].values
    l = df["Low"].values
    c = df["Close"].values
    v = df["Volume"].values
    return [
        {"time": d, "open": round(float(ov), 4), "high": round(float(hv), 4),
         "low": round(float(lv), 4), "close": round(float(cv), 4), "volume": int(vv)}
        for d, ov, hv, lv, cv, vv in zip(dates, o, h, l, c, v)
        if not (np.isnan(cv) or np.isnan(ov))
    ]


def _to_ma(df, window: int) -> list[dict]:
    """MA(n) 시리즈 → Lightweight Charts line 포맷 (벡터화)."""
    import numpy as np
    ma = df["Close"].rolling(window).mean().values
    dates = [str(ts.date() if hasattr(ts, "date") else ts) for ts in df.index]
    return [
        {"time": d, "value": round(float(v), 4)}
        for d, v in zip(dates, ma)
        if not np.isnan(v)
    ]


def _to_ma20(df) -> list[dict]:
    return _to_ma(df, 20)


def _to_ma60(df) -> list[dict]:
    return _to_ma(df, 60)


def _merge_markers(df) -> list[dict]:
    """buy_signal + sell_signal 독립 계산 후 시간순 병합."""
    from screener.buy_signal import compute_buy_signals
    from screener.sell_signal import compute_sell_signals

    buy  = compute_buy_signals(df)
    sell = compute_sell_signals(df)
    return sorted(buy + sell, key=lambda m: m["time"])


@router.get("/api/chart-data/{ticker}")
def get_chart_data(ticker: str, period: str = "6mo"):
    """Lightweight Charts용 OHLCV + MA20 + 마스터 시그널 마커 반환."""
    if period not in _VALID_PERIODS:
        period = "6mo"
    ticker = ticker.upper()

    # 차트 응답 전체를 5분 캐시 (markers 재계산 방지)
    from screener.cache_manager import cache
    resp_key = f"chart_resp_{ticker}_{period}"
    cached_resp = cache.get(resp_key)
    if cached_resp:
        return cached_resp

    try:
        df = _get_df(ticker, period)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[Chart] {ticker} 데이터 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    resp = {
        "ticker":  ticker,
        "ohlcv":   _to_ohlcv(df),
        "ma20":    _to_ma20(df),
        "ma60":    _to_ma60(df),
        "markers": _merge_markers(df),
    }
    cache.set(resp_key, resp, expire=300)
    return resp
