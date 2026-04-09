# FTSE Stock Screener

A Python stock screener for UK markets with:
- a command-line script
- a FastAPI backend
- a static browser UI served from `static/`

The app fetches OHLCV market data from Yahoo Finance for stock lists (`*.stocks`) and index snapshots for FTSE 100 (`^FTSE`), FTSE 250 (`^FTMC`), and DAX (`^GDAXI`).

## Current Features

- List and load stock list files automatically (`ftse100.stocks`, `ftse250.stocks`, `dax.stocks`, `watchlist.stocks`)
  - `dax.stocks` contains DAX constituents (company tickers), while the market strip index snapshot uses `^GDAXI`.
- Screen a selected list and return latest OHLCV data per ticker
- Fetch market index snapshots (FTSE 100, FTSE 250, and DAX)
- Fetch ticker close-price history for charting
- FastAPI endpoints for UI and API integration
- Static UI with list selection, ticker preview, result table, chart, and watchlist actions
- Static UI remembers your last selected list/view/chart period/presets between sessions
- Simple script `startstockserver` for local backend startup

## Project Structure

- `stockscreener.py`: command-line screener
- `backend/app.py`: FastAPI app and API routes
- `backend/service.py`: data fetching and stock list logic
- `startstockserver`: helper script to start Uvicorn
- `static/index.html`: static browser UI served by backend root route
- `*.stocks`: stock universe files

## Requirements

- Python 3.10+

Python dependencies are listed in `requirements.txt`:
- `yfinance>=0.2.0`
- `pandas>=1.5.0`
- `fastapi>=0.115.0`
- `uvicorn>=0.30.0`

Optional backend environment variables:
- `STOCK_API_TIMEOUT_SECONDS` (default: `8.0`)
- `STOCK_API_MAX_RETRIES` (default: `2`)
- `STOCK_API_RETRY_BACKOFF_SECONDS` (default: `0.5`)
- `STOCK_CACHE_REFRESH_SECONDS` (default: `900`)
- `STOCK_MARKET_TIMEZONE` (default: `Europe/London`)
- `STOCK_MARKET_CLOSE_HOUR` (default: `16`)
- `STOCK_MARKET_CLOSE_MINUTE` (default: `35`)

Latest `1d` stock and index data is cached locally in `.cache/intraday_quotes.json`. The backend reuses that cache for screen loads and refreshes it in the background every 15 minutes by default.

Historical OHLC data up to yesterday is cached locally in `.cache/historical_prices.json`. That cache is reused for chart/history requests and for indicator calculations. It is refreshed lazily when needed, including once after market close on the same market day (default London close `16:35`) and again on new market days.

## Setup

1. Clone repository:

```bash
git clone https://github.com/lupuskus/stockscreener.git
cd stockscreener
```

2. Create and activate virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. Install Python dependencies:

```bash
pip install -r requirements.txt
```

## Usage

### 1. CLI mode

```bash
python stockscreener.py
```

### 2. Backend API

Run with helper script:

```bash
./startstockserver
```

Or run directly:

```bash
uvicorn backend.app:app --reload
```

The API is available at `http://127.0.0.1:8000`.

To tune Yahoo Finance request behavior:

```bash
export STOCK_API_TIMEOUT_SECONDS=8
export STOCK_API_MAX_RETRIES=2
export STOCK_API_RETRY_BACKOFF_SECONDS=0.5
uvicorn backend.app:app --reload
```

### 3. Static browser UI

Open the backend URL directly in your browser:

```text
http://127.0.0.1:8000
```

## API Endpoints

- `GET /` serves `static/index.html`
- `GET /health`
- `GET /stock-lists`
- `GET /stock-lists/{filename}`
- `GET /watchlist`
- `POST /watchlist`
- `DELETE /watchlist/{ticker}`
- `GET /indexes`
- `GET /history/{ticker}?period=1mo`
- `GET /history-ohlc/{ticker}?period=1mo`
- `POST /screen`

Example screen request:

```bash
curl -X POST "http://127.0.0.1:8000/screen" \
  -H "Content-Type: application/json" \
  -d '{"stock_list":"ftse100.stocks","period":"1d"}'
```

## Data Source

Data is sourced from Yahoo Finance via `yfinance`.

- Availability depends on Yahoo Finance responses.
- Some tickers may intermittently return no data.

## Roadmap / TODO

For active and planned work, see `TODO.md`.

## Version History and Plan

For key past versions and planned future versions, see `VERSION.md`.

## Versioning and Build Metadata

- Current app version default: `0.3.0` (can be overridden with `APP_VERSION`).
- The backend exposes `GET /build-info` with:
  - `version`
  - `build_number`
  - `built_at`
  - `branch`
  - `commit`
  - `short_commit`
- Build number behavior:
  - Uses `BUILD_NUMBER` if provided by deployment.
  - Otherwise derives from git commit history (`git rev-list --count`).
  - If git metadata is unavailable, it falls back to a commit-based numeric value.
- The frontend header displays version, build number, build date/time, and branch/commit.

## Disclaimer

This project is for educational and informational use only, and is not financial advice.