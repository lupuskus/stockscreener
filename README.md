# FTSE Stock Screener

A Python stock screener for UK markets with:
- a command-line script
- a FastAPI backend
- browser UIs (a React app in `frontend/` and a static UI served from `static/`)

The app fetches OHLCV market data from Yahoo Finance for stock lists (`*.stocks`) and index snapshots for FTSE 100 (`^FTSE`) and FTSE 250 (`^FTMC`).

## Current Features

- List and load stock list files automatically (`ftse100.stocks`, `ftse250.stocks`, `watchlist.stocks`)
- Screen a selected list and return latest OHLCV data per ticker
- Fetch market index snapshots (FTSE 100 and FTSE 250)
- Fetch ticker close-price history for charting
- FastAPI endpoints for UI and API integration
- React frontend with list selection, ticker preview, result table, and index cards
- Simple script `startstockserver` for local backend startup

## Project Structure

- `stockscreener.py`: command-line screener
- `backend/app.py`: FastAPI app and API routes
- `backend/service.py`: data fetching and stock list logic
- `startstockserver`: helper script to start Uvicorn
- `frontend/`: React + Vite frontend
- `static/index.html`: static browser UI served by backend root route
- `*.stocks`: stock universe files

## Requirements

- Python 3.10+
- Node.js 20+ and npm (for React frontend development)

Python dependencies are listed in `requirements.txt`:
- `yfinance>=0.2.0`
- `pandas>=1.5.0`
- `fastapi>=0.115.0`
- `uvicorn>=0.30.0`

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

### 3. React frontend (Vite)

From repository root:

```bash
cd frontend
npm install
npm run dev
```

By default it calls `http://127.0.0.1:8000`. Override with `frontend/.env.local`:

```bash
VITE_API_URL=http://127.0.0.1:8000
```

## API Endpoints

- `GET /` serves `static/index.html`
- `GET /health`
- `GET /stock-lists`
- `GET /stock-lists/{filename}`
- `GET /indexes`
- `GET /history/{ticker}?period=1mo`
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

## Disclaimer

This project is for educational and informational use only, and is not financial advice.