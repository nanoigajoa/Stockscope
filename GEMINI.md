# StockScope Project Context

## Project Overview
StockScope is a technical analysis screening and trading signal web service for US stocks. It consists of two independent but integrated services that share a watchlist:
1.  **Screening (`/screen`)**: Technical health check based on a 7-item checklist.
2.  **Trading Signals (`/signals`)**: Entry timing analysis using a weighted scoring model (Trend, Momentum, Volume, Pattern).

The project is built with **Python 3.12**, **FastAPI**, **Jinja2**, and uses **SSE (Server-Sent Events)** for real-time analysis updates.

## Key Technologies
- **Backend**: FastAPI, Jinja2, SSE.
- **Data**: `yfinance`, `pandas-ta` (technical indicators), `finviz` (universe filtering), `pytrends` (Google Trends), `fredapi` (macro data), `quiverquant` (congressional trading).
- **Frontend**: Vanilla JavaScript, Lightweight Charts 4.2 (TradingView), TomSelect (autocomplete).
- **Caching**: `diskcache` for multi-level TTL-based caching.
- **Deployment**: Render (free plan) with GitHub Actions for keepalive and daily batches.

## Project Structure
- `api/`: FastAPI application, routes, and dependency management.
- `services/`: Service layer that orchestrates data fetching, processing, and scoring.
- `screener/`: Core logic modules.
    - `indicators.py`: Technical indicator calculations using `pandas-ta`.
    - `checklist.py`: 7-item scoring logic for screening.
    - `signal_scorer.py`: 4-category weighted scoring for trading signals.
    - `data_fetcher.py`: OHLCV and intraday data retrieval with caching.
- `static/`, `templates/`: Frontend assets and Jinja2 templates.
- `docs/`: Extensive documentation including ADRs (Architecture Decision Records) and Design Docs.
- `data/`: Local storage for `watchlist.json`.
- `INDICATORS.md`: Detailed logic and formulas for all technical indicators used.

## Building and Running
### Prerequisites
- Python 3.12
- Environment variables (in `.env` or system):
    - `FRED_API_KEY`: For macro data banner.
    - `QUIVERQUANT_API_KEY`: For congressional trading badges.
    - `REFRESH_TOKEN`: For GitHub Actions authentication.

### Key Commands
- **Install dependencies**: `pip install -r requirements.txt`
- **Run server (recommended)**: `./run.sh`
- **Manual run**: `uvicorn api.main:app --reload --port 8000`
- **Run tests**: `pytest`

## Development Conventions
### SSE (Server-Sent Events)
The application uses SSE for long-running analysis tasks.
- Frontend: `EventSource` connects to `/stream/screen` or `/stream/signals`.
- Backend: A generator function yields progress updates and eventually renders partial HTML cards (`partials/screen_cards.html`, `partials/signal_cards.html`).

### Pipeline Flows
- **Screening**: `Finviz Filter` -> `OHLCV Fetch` -> `Indicators` -> `Checklist` -> `Grade (S/A/B/SKIP)` -> `Parallel Extras (Fundamentals, Trends, etc.)`.
- **Signals**: `Watchlist Load` -> `OHLCV + Intraday Fetch` -> `Signal Scorer` -> `Signal Grade (STRONG BUY/BUY/WATCH/NO SIGNAL)`.

### Scoring & Grading
- **Screening Grade**: Based on the ratio of passed items in the checklist (default 7 items).
    - `S` (≥ 67%), `A` (≥ 44%), `B` (≥ 22%), `SKIP` (< 22% or RSI ≥ 80).
- **Signal Scoring**: Weighted average of 4 categories:
    - **Trend (35%)**: MA Alignment + Entry Zone.
    - **Momentum (25%)**: RSI + StochRSI + Z-Score.
    - **Volume (25%)**: CMF + OBV Divergence.
    - **Pattern (15%)**: Candlestick patterns (Hammer, Engulfing, etc.).

### Caching Strategy
- Uses `diskcache` with various TTLs (e.g., 15 mins for stock prices, 24 hours for trends, 7 days for macro data) to minimize API calls and improve performance.

## Documentation
- Refer to `docs/design_doc.md` for the system architecture.
- Refer to `INDICATORS.md` for technical indicator definitions.
- Refer to `docs/adr/` for historical architectural decisions.
