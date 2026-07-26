import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from api.deps import templates

router = APIRouter()
_executor = ThreadPoolExecutor(max_workers=4)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/signals", response_class=HTMLResponse)
def signals_page(request: Request):
    from screener import watchlist_store
    from screener.macro_fetcher import get_sidebar_macro
    watchlist = watchlist_store.load()
    macro = get_sidebar_macro()
    return templates.TemplateResponse(
        request=request,
        name="signals.html",
        context={"active_page": "signals", "watchlist": watchlist, "macro": macro},
    )


@router.get("/stream/signals")
async def stream_signals(tickers: str = ""):
    tickers_list = [t.strip().upper() for t in tickers.split(",") if t.strip()] or None

    async def generate():
        from services.signal_service import run_signal_analysis
        from screener import watchlist_store
        from screener.finviz_filter import get_filtered_tickers

        wl = tickers_list or watchlist_store.load()

        if not tickers_list and len(wl) < 10:
            yield _sse("progress", {"stage": "실시간 랭킹 보드 구성을 위해 유니버스 확장 중..."})
            # 아래에서 [:30]으로 잘라 쓰므로 알파벳순이면 A~로 시작하는 종목만 남는다.
            # 시가총액 내림차순으로 받아 유동성 높은 대형주가 랭킹 보드에 오르게 한다.
            extra_tickers = get_filtered_tickers(order="-marketcap")
            wl = list(dict.fromkeys(wl + extra_tickers))[:30]

        if not wl:
            yield _sse("done", {
                "html": '<div class="result-empty"><p>분석할 종목이 없습니다. 스크리너에서 종목을 찾거나 관심종목을 추가하세요.</p></div>',
                "watchlist": [],
            })
            return

        yield _sse("progress", {"stage": f"{len(wl)}개 종목 매수 매력도 랭킹 산출 중..."})

        loop = asyncio.get_running_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    _executor,
                    lambda: run_signal_analysis(wl),
                ),
                timeout=120.0,
            )
            results   = result.get("results", [])
            summary   = result.get("summary", {})
            watchlist = result.get("watchlist", [])

            if not results:
                html = '<div class="result-empty"><p>분석 결과가 없습니다.</p></div>'
            else:
                mo  = summary.get("market_open", False)
                tpl = templates.get_template("partials/signal_cards.html")
                html = tpl.render(results=results, summary=summary, market_open=mo)

            yield _sse("done", {"html": html, "watchlist": watchlist})

        except asyncio.TimeoutError:
            yield _sse("error", {"message": "분석 시간이 초과되었습니다 (120초). 관심종목 수를 줄이거나 다시 시도해 주세요."})
        except Exception as e:
            yield _sse("error", {"message": str(e)})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
