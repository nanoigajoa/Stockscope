import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from config import DATA_PERIOD, SHOW_GRADES, MAX_RESULTS, NEWS_FILTER_ENABLED
from api.deps import templates

router = APIRouter()
_executor = ThreadPoolExecutor(max_workers=6)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/screen", response_class=HTMLResponse)
def screen_page(request: Request):
    from screener.macro_fetcher import get_sidebar_macro, get_macro_context
    macro = get_sidebar_macro()
    fred_macro = get_macro_context()
    return templates.TemplateResponse(
        request=request,
        name="screen.html",
        context={"active_page": "screen", "macro": macro, "fred_macro": fred_macro},
    )


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/stream/screen")
async def stream_screen(
    tickers: str = "",
    grade_filter: str = "",
    period: str = DATA_PERIOD,
    rsi_min: int = 45,
    rsi_max: int = 65,
    checks: str = "",
    target_1: float = 0,
    target_2: float = 0,
    stop_loss: float = 0,
    include_penny: bool = False,
):
    tickers_list = [t.strip().upper() for t in tickers.split(",") if t.strip()] or None
    gf       = grade_filter.strip() or None
    enabled  = [c.strip() for c in checks.split(",") if c.strip()] or None
    t1       = target_1 / 100 if target_1 > 0 else None
    t2       = target_2 / 100 if target_2 > 0 else None
    sl       = stop_loss / 100 if stop_loss > 0 else None

    async def generate():
        from screener.finviz_filter import get_filtered_tickers
        from screener.data_fetcher import fetch_ohlcv
        from services.screener_service import (
            _compute_change, _parallel_news_check,
            _score_all_parallel, _fetch_extras_parallel, _GRADE_ORDER,
        )

        loop = asyncio.get_running_loop()

        # ── Phase 1: 종목 수집 ──────────────────────────────────
        yield _sse("progress", {"stage": "Finviz 종목 필터링 중..."})
        try:
            if tickers_list:
                all_tickers = tickers_list
            else:
                all_tickers = await asyncio.wait_for(
                    loop.run_in_executor(_executor, partial(get_filtered_tickers, include_penny=include_penny)),
                    timeout=30.0,
                )
        except asyncio.TimeoutError:
            yield _sse("error", {"message": "Finviz 연결 시간 초과 (30s)"})
            return
        except Exception as e:
            yield _sse("error", {"message": f"종목 수집 실패: {e}"})
            return

        if not all_tickers:
            yield _sse("done", {"html": '<p style="color:var(--text-faint);text-align:center;padding:3rem">조건에 맞는 종목이 없습니다.</p>'})
            return

        # ── Phase 2: OHLCV 배치 수집 ───────────────────────────
        yield _sse("progress", {"stage": f"{len(all_tickers)}개 종목 OHLCV 수집 중..."})
        try:
            ohlcv_map = await asyncio.wait_for(
                loop.run_in_executor(_executor, partial(fetch_ohlcv, all_tickers, period)),
                timeout=60.0,
            )
        except asyncio.TimeoutError:
            yield _sse("error", {"message": "OHLCV 수집 시간 초과 (60s)"})
            return

        if not ohlcv_map:
            yield _sse("done", {"html": '<p style="color:var(--text-faint);text-align:center;padding:3rem">데이터를 가져올 수 없습니다.</p>'})
            return

        # ── Phase 3: 변동률 계산 (즉시, API 없음) ──────────────
        changes = {t: _compute_change(df) for t, df in ohlcv_map.items()}

        # ── Phase 4: 뉴스 병렬 체크 ────────────────────────────
        if NEWS_FILTER_ENABLED:
            yield _sse("progress", {"stage": "뉴스 위험 키워드 필터 검사 중..."})
            news_map = await loop.run_in_executor(
                _executor, _parallel_news_check, list(ohlcv_map.keys())
            )
        else:
            news_map = {t: (False, "") for t in ohlcv_map}

        # ── Phase 5: 병렬 채점 ─────────────────────────────────
        yield _sse("progress", {"stage": f"{len(ohlcv_map)}개 종목 기술적 분석 중..."})
        results = await loop.run_in_executor(
            _executor,
            partial(
                _score_all_parallel,
                ohlcv_map, changes, news_map,
                rsi_min, rsi_max, enabled,
                t1, t2, sl,
            ),
        )

        # ── 정렬 + 필터 ────────────────────────────────────────
        results.sort(key=lambda r: (_GRADE_ORDER.get(r["grade"], 5), -r.get("score", 0)))
        show_grades = [gf.upper()] if gf else SHOW_GRADES
        displayable = [r for r in results if r["grade"] in show_grades][:MAX_RESULTS]
        skipped     = sum(1 for r in results if r["grade"] == "SKIP")
        summary     = {"total": len(results), "skipped": skipped, "displayed": len(displayable)}

        # ── Phase 6: 카드 스트리밍 (extras 없이 즉시) ──────────
        yield _sse("init", {"summary": summary})
        card_tpl = templates.get_template("partials/_screen_card.html")

        if not displayable:
            yield _sse("empty", {})
            yield _sse("done", {})
            return

        for r in displayable:
            card_html = card_tpl.render(r=r)
            yield _sse("card", {"html": card_html})

        # ── Phase 7: extras 수집 + 스트리밍 ───────────────────
        yield _sse("progress", {"stage": "펀더멘털 · 외부 데이터 수집 중..."})
        display_tickers = [r["ticker"] for r in displayable]
        extras_map = await loop.run_in_executor(
            _executor, partial(_fetch_extras_parallel, display_tickers)
        )

        extras_tpl = templates.get_template("partials/_screen_card_extras.html")
        for r in displayable:
            tk = r["ticker"]
            ex = extras_map.get(tk, {})
            extras_html = extras_tpl.render(r=r, extras=ex)
            yield _sse("extras", {"ticker": tk, "html": extras_html})

        yield _sse("done", {})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
