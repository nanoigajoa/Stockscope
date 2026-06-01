"""
CLI·웹 공용 스크리닝 서비스.
"""
import logging
from concurrent.futures import ThreadPoolExecutor

from config import (
    SHOW_GRADES, MAX_RESULTS,
    TODAY_CHANGE_MIN, TODAY_CHANGE_MAX, NEWS_FILTER_ENABLED,
    DATA_PERIOD, RSI_IDEAL_MIN, RSI_IDEAL_MAX,
)
from screener.finviz_filter import get_filtered_tickers
from screener.data_fetcher import fetch_ohlcv
from screener.indicators import calculate_indicators
from screener.checklist import score_ticker
from screener.grader import grade
from screener.news_filter import check_news_risk
from screener.fundamental_fetcher import fetch_fundamentals
from screener.trends_fetcher import get_trend_scores
from screener.insider_fetcher import get_insider_buys

logger = logging.getLogger(__name__)

_GRADE_ORDER = {"R": 0, "S": 1, "A": 2, "B": 3, "C": 4, "SKIP": 5}


def _make_skip(ticker: str, reason: str) -> dict:
    return {
        "ticker": ticker, "price": 0, "rsi": None, "grade": "SKIP",
        "score": 0, "max_score": 7, "action": "진입 금지",
        "checklist": {}, "target_1": None, "target_2": None, "stop_loss": None,
        "reason": reason, "news_ok": None, "extras": {},
    }


def _compute_change(df) -> float:
    """OHLCV 마지막 두 행으로 당일 변동률(%) 계산. API 호출 없음."""
    if df is None or len(df) < 2:
        return 0.0
    prev = float(df["Close"].iloc[-2])
    curr = float(df["Close"].iloc[-1])
    return round((curr - prev) / prev * 100, 2) if prev > 0 else 0.0


def _parallel_news_check(tickers: list[str]) -> dict[str, tuple[bool, str]]:
    """뉴스 위험 키워드 병렬 체크. {ticker: (is_risky, reason)}"""
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {t: ex.submit(check_news_risk, t) for t in tickers}
    return {t: fut.result() for t, fut in futures.items()}


def _score_one_ticker(
    ticker: str,
    df,
    today_change: float,
    is_risky: bool,
    news_reason: str,
    rsi_min: int,
    rsi_max: int,
    enabled_checks: list[str] | None,
    target_1_pct: float | None,
    target_2_pct: float | None,
    stop_loss_pct: float | None,
) -> dict | None:
    """단일 티커 채점 → result dict. 오류 시 None."""
    if not (TODAY_CHANGE_MIN <= today_change <= TODAY_CHANGE_MAX):
        direction = "급등" if today_change > 0 else "급락"
        return _make_skip(ticker, f"당일변동 {today_change:+.1f}% ({direction} 제외)")

    if is_risky:
        return _make_skip(ticker, news_reason)

    try:
        ind = calculate_indicators(df)
        if ind is None:
            return None

        score_result = score_ticker(ind, rsi_min=rsi_min, rsi_max=rsi_max, enabled_checks=enabled_checks)
        result = grade(
            score_result, ticker, ind["price"],
            target_1_pct=target_1_pct,
            target_2_pct=target_2_pct,
            stop_loss_pct=stop_loss_pct,
        )
        result["news_ok"] = (not is_risky) if NEWS_FILTER_ENABLED else None
        result["rsi"] = ind.get("rsi")
        result.setdefault("extras", {})
        return result
    except Exception:
        logger.exception(f"[Screener] 채점 오류: {ticker}")
        return None


def _score_all_parallel(
    ohlcv_map: dict,
    changes: dict,
    news_map: dict,
    rsi_min: int,
    rsi_max: int,
    enabled_checks: list[str] | None,
    target_1_pct: float | None,
    target_2_pct: float | None,
    stop_loss_pct: float | None,
) -> list[dict]:
    """모든 티커를 ThreadPoolExecutor로 병렬 채점."""
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {
            ticker: ex.submit(
                _score_one_ticker,
                ticker, df,
                changes.get(ticker, 0.0),
                news_map.get(ticker, (False, ""))[0],
                news_map.get(ticker, (False, ""))[1],
                rsi_min, rsi_max, enabled_checks,
                target_1_pct, target_2_pct, stop_loss_pct,
            )
            for ticker, df in ohlcv_map.items()
        }
    return [r for r in (fut.result() for fut in futures.values()) if r is not None]


def _fetch_extras_parallel(display_tickers: list[str]) -> dict[str, dict]:
    """표시 종목의 펀더멘털·트렌드·내부자 병렬 수집."""
    if not display_tickers:
        return {}
    try:
        with ThreadPoolExecutor(max_workers=3) as ex:
            f_fund    = ex.submit(fetch_fundamentals, display_tickers)
            f_trends  = ex.submit(get_trend_scores, display_tickers)
            f_insider = ex.submit(
                lambda tks: {t: get_insider_buys(t) for t in tks},
                display_tickers,
            )
        fund_map    = f_fund.result()
        trend_map   = f_trends.result()
        insider_map = f_insider.result()
    except Exception:
        logger.exception("[Screener] 추가 데이터 수집 오류")
        return {}

    result = {}
    for tk in display_tickers:
        extras = fund_map.get(tk, {}).copy()
        extras["trend_score"]    = trend_map.get(tk, 0)
        extras["insider_bought"] = insider_map.get(tk, extras.get("insider_bought", False))
        website = extras.get("website", "")
        if website:
            extras["website_domain"] = (
                website.replace("http://", "").replace("https://", "")
                .replace("www.", "").split("/")[0]
            )
        result[tk] = extras
    return result


def run_analysis(
    tickers_override: list[str] | None = None,
    grade_filter: str | None = None,
    period: str = DATA_PERIOD,
    rsi_min: int = RSI_IDEAL_MIN,
    rsi_max: int = RSI_IDEAL_MAX,
    enabled_checks: list[str] | None = None,
    target_1_pct: float | None = None,
    target_2_pct: float | None = None,
    stop_loss_pct: float | None = None,
    include_penny: bool = False,
) -> dict:
    """스크리닝 파이프라인 전체 실행 (배치 모드)."""
    # 1. 종목 수집
    try:
        if tickers_override:
            tickers = [t.upper() for t in tickers_override]
        else:
            tickers = get_filtered_tickers(include_penny=include_penny)
    except Exception:
        logger.exception("종목 수집 오류")
        return _empty_result()

    if not tickers:
        return _empty_result()

    # 2. OHLCV 배치 수집
    try:
        ohlcv_map = fetch_ohlcv(tickers, period=period)
    except Exception:
        logger.exception("OHLCV 수집 오류")
        return _empty_result()

    if not ohlcv_map:
        return _empty_result()

    # 3. 당일 변동률 — ohlcv_map에서 직접 계산 (API 호출 없음)
    changes = {t: _compute_change(df) for t, df in ohlcv_map.items()}

    # 4. 뉴스 필터 병렬 선제 조회
    if NEWS_FILTER_ENABLED:
        news_map = _parallel_news_check(list(ohlcv_map.keys()))
    else:
        news_map = {t: (False, "") for t in ohlcv_map}

    # 5. 병렬 채점
    results = _score_all_parallel(
        ohlcv_map, changes, news_map,
        rsi_min, rsi_max, enabled_checks,
        target_1_pct, target_2_pct, stop_loss_pct,
    )

    # 6. 정렬
    results.sort(key=lambda r: (_GRADE_ORDER.get(r["grade"], 5), -r.get("score", 0)))

    # 7. 필터링
    show_grades = [grade_filter.upper()] if grade_filter else SHOW_GRADES
    displayable = [r for r in results if r["grade"] in show_grades][:MAX_RESULTS]

    # 8. 추가 데이터 (표시 종목만)
    display_tickers = [r["ticker"] for r in displayable]
    extras_map = _fetch_extras_parallel(display_tickers)
    for r in displayable:
        r["extras"] = extras_map.get(r["ticker"], {})

    skipped = sum(1 for r in results if r["grade"] == "SKIP")
    logger.info(f"[Screener] 완료: 총 {len(results)}개 | SKIP {skipped}개 | 표시 {len(displayable)}개")

    return {
        "results": results,
        "displayable": displayable,
        "summary": {"total": len(results), "skipped": skipped, "displayed": len(displayable)},
    }


def _empty_result() -> dict:
    return {
        "results": [], "displayable": [],
        "summary": {"total": 0, "skipped": 0, "displayed": 0},
    }
