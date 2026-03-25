from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Dict, Generator, List

from requests import RequestException
import yfinance as yf


ROOT_DIR = Path(__file__).resolve().parent.parent
WATCHLIST_FILE = "watchlist.stocks"
INDEXES = {
    "ftse100": "^FTSE",
    "ftse250": "^FTMC",
}


def _read_float_env(name: str, default: float, *, minimum: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
        return max(minimum, value)
    except ValueError:
        return default


def _read_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
        return min(max(value, minimum), maximum)
    except ValueError:
        return default


YF_TIMEOUT_SECONDS = _read_float_env("STOCK_API_TIMEOUT_SECONDS", 8.0, minimum=0.5)
YF_MAX_RETRIES = _read_int_env("STOCK_API_MAX_RETRIES", 2, minimum=0, maximum=6)
YF_RETRY_BACKOFF_SECONDS = _read_float_env("STOCK_API_RETRY_BACKOFF_SECONDS", 0.5, minimum=0.05)


class UpstreamTimeoutError(RuntimeError):
    """Raised when Yahoo Finance requests time out after retries."""


class UpstreamServiceError(RuntimeError):
    """Raised when Yahoo Finance requests fail for non-timeout reasons."""


def _is_timeout_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return isinstance(exc, TimeoutError) or "timeout" in message or "timed out" in message


def _is_retryable_error(exc: Exception) -> bool:
    if _is_timeout_error(exc):
        return True
    if isinstance(exc, RequestException):
        return True
    message = str(exc).lower()
    return "429" in message or "too many requests" in message or "temporarily unavailable" in message


def _call_history_with_retry(ticker: str, period: str):
    attempts = YF_MAX_RETRIES + 1
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            return yf.Ticker(ticker).history(period=period, timeout=YF_TIMEOUT_SECONDS)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if not _is_retryable_error(exc) or attempt == attempts:
                break
            sleep_seconds = YF_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
            time.sleep(sleep_seconds)

    if last_error and _is_timeout_error(last_error):
        raise UpstreamTimeoutError(
            f"Yahoo Finance request timed out for {ticker} after {attempts} attempt(s)."
        ) from last_error

    raise UpstreamServiceError(
        f"Yahoo Finance request failed for {ticker} after {attempts} attempt(s)."
    ) from last_error


def list_stock_files() -> List[str]:
    return sorted(p.name for p in ROOT_DIR.glob("*.stocks"))


def read_stock_list(filename: str) -> List[str]:
    file_path = ROOT_DIR / filename
    if not file_path.exists() or file_path.suffix != ".stocks":
        raise FileNotFoundError(f"Unknown stock list: {filename}")

    with file_path.open("r", encoding="utf-8") as stream:
        return [line.strip() for line in stream if line.strip()]


def _watchlist_path() -> Path:
    return ROOT_DIR / WATCHLIST_FILE


def _write_watchlist(tickers: List[str]) -> None:
    file_path = _watchlist_path()
    with file_path.open("w", encoding="utf-8") as stream:
        if tickers:
            stream.write("\n".join(tickers) + "\n")
        else:
            stream.write("")


def get_watchlist() -> List[str]:
    file_path = _watchlist_path()
    if not file_path.exists():
        _write_watchlist([])
        return []

    with file_path.open("r", encoding="utf-8") as stream:
        # Keep watchlist unique and normalized to uppercase ticker symbols.
        normalized = [line.strip().upper() for line in stream if line.strip()]

    unique_tickers: List[str] = []
    seen: set[str] = set()
    for ticker in normalized:
        if ticker in seen:
            continue
        seen.add(ticker)
        unique_tickers.append(ticker)
    return unique_tickers


def add_watchlist_ticker(ticker: str) -> tuple[bool, List[str]]:
    watchlist = get_watchlist()
    if ticker in watchlist:
        return False, watchlist

    watchlist.append(ticker)
    _write_watchlist(watchlist)
    return True, watchlist


def remove_watchlist_ticker(ticker: str) -> tuple[bool, List[str]]:
    watchlist = get_watchlist()
    if ticker not in watchlist:
        return False, watchlist

    updated = [item for item in watchlist if item != ticker]
    _write_watchlist(updated)
    return True, updated


def _fetch_latest_ohlcv(ticker: str, period: str = "1d") -> Dict[str, float] | None:
    history = _call_history_with_retry(ticker, period)
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
    history = _call_history_with_retry(ticker, period)
    if history.empty:
        return []
    return [
        {
            "date": str(idx.date()),
            "close": float(row["Close"]),
            "volume": int(row["Volume"]),
        }
        for idx, row in history.iterrows()
    ]


def fetch_ticker_history_ohlc(ticker: str, period: str = "1mo") -> list:
    history = _call_history_with_retry(ticker, period)
    if history.empty:
        return []
    return [
        {
            "date": str(idx.date()),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": int(row["Volume"]),
        }
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


def screen_stock_list_stream(
    filename: str, period: str = "1d"
) -> Generator[Dict[str, object], None, None]:
    """Yield progress events then a final complete event for SSE streaming."""
    tickers = read_stock_list(filename)
    total = len(tickers)
    results: List[Dict[str, float]] = []

    for i, ticker in enumerate(tickers, 1):
        try:
            data = _fetch_latest_ohlcv(ticker, period=period)
            if data:
                results.append(data)
        except Exception:
            pass
        yield {"type": "progress", "done": i, "total": total}

    yield {
        "type": "complete",
        "stock_list": filename,
        "requested": total,
        "retrieved": len(results),
        "stocks": results,
        "indexes": fetch_index_snapshot(),
    }
