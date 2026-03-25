from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import yfinance as yf


ROOT_DIR = Path(__file__).resolve().parent.parent
INDEXES = {
    "ftse100": "^FTSE",
    "ftse250": "^FTMC",
}


def list_stock_files() -> List[str]:
    return sorted(p.name for p in ROOT_DIR.glob("*.stocks"))


def read_stock_list(filename: str) -> List[str]:
    file_path = ROOT_DIR / filename
    if not file_path.exists() or file_path.suffix != ".stocks":
        raise FileNotFoundError(f"Unknown stock list: {filename}")

    with file_path.open("r", encoding="utf-8") as stream:
        return [line.strip() for line in stream if line.strip()]


def _fetch_latest_ohlcv(ticker: str, period: str = "1d") -> Dict[str, float] | None:
    history = yf.Ticker(ticker).history(period=period)
    if history.empty:
        return None

    latest = history.iloc[-1]
    return {
        "ticker": ticker,
        "open": float(latest["Open"]),
        "high": float(latest["High"]),
        "low": float(latest["Low"]),
        "close": float(latest["Close"]),
        "volume": int(latest["Volume"]),
    }


def fetch_ticker_history(ticker: str, period: str = "1mo") -> list:
    history = yf.Ticker(ticker).history(period=period)
    if history.empty:
        return []
    return [
        {"date": str(idx.date()), "close": float(row["Close"])}
        for idx, row in history.iterrows()
    ]


def fetch_index_snapshot() -> Dict[str, Dict[str, float]]:
    snapshots: Dict[str, Dict[str, float]] = {}
    for name, ticker in INDEXES.items():
        try:
            data = _fetch_latest_ohlcv(ticker)
            if data:
                snapshots[name] = data
        except Exception:
            continue
    return snapshots


def screen_stock_list(filename: str, period: str = "1d") -> Dict[str, object]:
    tickers = read_stock_list(filename)
    results: List[Dict[str, float]] = []

    for ticker in tickers:
        try:
            data = _fetch_latest_ohlcv(ticker, period=period)
            if data:
                results.append(data)
        except Exception:
            continue

    return {
        "stock_list": filename,
        "requested": len(tickers),
        "retrieved": len(results),
        "stocks": results,
        "indexes": fetch_index_snapshot(),
    }
