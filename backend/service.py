from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Generator, List
from zoneinfo import ZoneInfo

from requests import RequestException
import yfinance as yf

logger = logging.getLogger(__name__)


ROOT_DIR = Path(__file__).resolve().parent.parent
WATCHLIST_FILE = "watchlist.stocks"
INDEXES = {
    "ftse100": "^FTSE",
    "ftse250": "^FTMC",
    "dax": "^GDAXI",
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
STOCK_CACHE_REFRESH_SECONDS = _read_int_env("STOCK_CACHE_REFRESH_SECONDS", 900, minimum=60, maximum=86400)
STOCK_MARKET_TIMEZONE = os.getenv("STOCK_MARKET_TIMEZONE", "Europe/London")
STOCK_MARKET_CLOSE_HOUR = _read_int_env("STOCK_MARKET_CLOSE_HOUR", 16, minimum=0, maximum=23)
STOCK_MARKET_CLOSE_MINUTE = _read_int_env("STOCK_MARKET_CLOSE_MINUTE", 35, minimum=0, maximum=59)
INTRADAY_CACHE_DIR = ROOT_DIR / ".cache"
INTRADAY_CACHE_FILE = INTRADAY_CACHE_DIR / "intraday_quotes.json"
HISTORICAL_CACHE_FILE = INTRADAY_CACHE_DIR / "historical_prices.json"
INDEX_TICKERS = set(INDEXES.values())

_intraday_cache_lock = threading.RLock()
_intraday_cache_stop_event = threading.Event()
_intraday_cache_thread: threading.Thread | None = None
_intraday_cache: Dict[str, Dict[str, object]] = {}
_historical_cache_lock = threading.RLock()
_historical_cache: Dict[str, Dict[str, object]] = {}

try:
    _MARKET_TZ: ZoneInfo | None = ZoneInfo(STOCK_MARKET_TIMEZONE)
except Exception:  # noqa: BLE001
    _MARKET_TZ = None


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
                logger.warning("[yfinance] %s attempt %d/%d failed: %s", ticker, attempt, attempts, exc)
                break
            logger.info("[yfinance] %s attempt %d/%d failed, retrying: %s", ticker, attempt, attempts, exc)
            sleep_seconds = YF_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
            time.sleep(sleep_seconds)

    if last_error and _is_timeout_error(last_error):
        msg = f"Yahoo Finance request timed out for {ticker} after {attempts} attempt(s)."
        logger.error("[yfinance] TIMEOUT: %s", msg)
        raise UpstreamTimeoutError(msg) from last_error

    msg = f"Yahoo Finance request failed for {ticker} after {attempts} attempt(s): {last_error}"
    logger.error("[yfinance] ERROR: %s", msg)
    raise UpstreamServiceError(msg) from last_error


def _is_same_local_day(timestamp: float) -> bool:
    now = time.localtime()
    then = time.localtime(timestamp)
    return now.tm_year == then.tm_year and now.tm_yday == then.tm_yday


def _ensure_intraday_cache_dir() -> None:
    INTRADAY_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _today_local() -> date:
    return date.today()


def _today_local_str() -> str:
    return _today_local().isoformat()


def _market_datetime(timestamp: float) -> datetime:
    if _MARKET_TZ is not None:
        return datetime.fromtimestamp(timestamp, tz=_MARKET_TZ)
    return datetime.fromtimestamp(timestamp)


def _is_same_market_day(ts_a: float, ts_b: float) -> bool:
    return _market_datetime(ts_a).date() == _market_datetime(ts_b).date()


def _market_close_timestamp(reference_timestamp: float) -> float:
    reference = _market_datetime(reference_timestamp)
    close_time = reference.replace(
        hour=STOCK_MARKET_CLOSE_HOUR,
        minute=STOCK_MARKET_CLOSE_MINUTE,
        second=0,
        microsecond=0,
    )
    return close_time.timestamp()


def _historical_cache_is_fresh(saved_at: float) -> bool:
    now = time.time()
    if not _is_same_market_day(saved_at, now):
        return False

    close_ts = _market_close_timestamp(now)
    if now < close_ts:
        return True

    # After market close, force one refresh unless the cache was written post-close.
    return saved_at >= close_ts


def _sanitize_json_value(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _sanitize_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_json_value(item) for item in value]
    return value


def _persist_intraday_cache() -> None:
    _ensure_intraday_cache_dir()
    with _intraday_cache_lock:
        payload = {
            "saved_at": time.time(),
            "entries": _intraday_cache,
        }
    fd, tmp_path = tempfile.mkstemp(prefix=f"{INTRADAY_CACHE_FILE.stem}.", suffix=".tmp", dir=str(INTRADAY_CACHE_DIR))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
        os.replace(tmp_path, INTRADAY_CACHE_FILE)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:  # noqa: BLE001
            pass


def _load_intraday_cache() -> None:
    if not INTRADAY_CACHE_FILE.exists():
        return

    try:
        with INTRADAY_CACHE_FILE.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[cache] Failed to load intraday cache: %s", exc)
        return

    entries = payload.get("entries", {}) if isinstance(payload, dict) else {}
    if not isinstance(entries, dict):
        return

    cleaned: Dict[str, Dict[str, object]] = {}
    for ticker, entry in entries.items():
        if not isinstance(ticker, str) or not isinstance(entry, dict):
            continue
        updated_at = entry.get("updated_at")
        data = entry.get("data")
        if not isinstance(updated_at, (int, float)) or not isinstance(data, dict):
            continue
        if not _is_same_local_day(float(updated_at)):
            continue
        cleaned[ticker.upper()] = {
            "updated_at": float(updated_at),
            "data": _sanitize_json_value(dict(data)),
        }

    with _intraday_cache_lock:
        _intraday_cache.clear()
        _intraday_cache.update(cleaned)


def _historical_cache_key(ticker: str, period: str) -> str:
    return f"{ticker.upper()}|{period}"


def _persist_historical_cache() -> None:
    _ensure_intraday_cache_dir()
    with _historical_cache_lock:
        payload = {
            "saved_at": time.time(),
            "entries": _historical_cache,
        }
    fd, tmp_path = tempfile.mkstemp(prefix=f"{HISTORICAL_CACHE_FILE.stem}.", suffix=".tmp", dir=str(INTRADAY_CACHE_DIR))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
        os.replace(tmp_path, HISTORICAL_CACHE_FILE)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:  # noqa: BLE001
            pass


def _load_historical_cache() -> None:
    if not HISTORICAL_CACHE_FILE.exists():
        return

    try:
        with HISTORICAL_CACHE_FILE.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[cache] Failed to load historical cache: %s", exc)
        return

    entries = payload.get("entries", {}) if isinstance(payload, dict) else {}
    if not isinstance(entries, dict):
        return

    cleaned: Dict[str, Dict[str, object]] = {}
    for cache_key, entry in entries.items():
        if not isinstance(cache_key, str) or not isinstance(entry, dict):
            continue
        saved_at = entry.get("saved_at")
        rows = entry.get("rows")
        if not isinstance(saved_at, (int, float)) or not isinstance(rows, list):
            continue
        cleaned[cache_key] = {
            "saved_at": float(saved_at),
            "rows": _sanitize_json_value(rows),
        }

    with _historical_cache_lock:
        _historical_cache.clear()
        _historical_cache.update(cleaned)


def _get_cached_historical_rows(ticker: str, period: str) -> List[Dict[str, object]] | None:
    cache_key = _historical_cache_key(ticker, period)
    with _historical_cache_lock:
        entry = _historical_cache.get(cache_key)
        if not entry:
            return None
        saved_at = entry.get("saved_at")
        rows = entry.get("rows")
        if not isinstance(saved_at, (int, float)) or not isinstance(rows, list):
            return None
        if not _historical_cache_is_fresh(float(saved_at)):
            return None
        return [
            _sanitize_json_value(dict(row))
            for row in rows
            if isinstance(row, dict)
        ]


def _store_cached_historical_rows(ticker: str, period: str, rows: List[Dict[str, object]]) -> None:
    cache_key = _historical_cache_key(ticker, period)
    with _historical_cache_lock:
        _historical_cache[cache_key] = {
            "saved_at": time.time(),
            "rows": _sanitize_json_value([dict(row) for row in rows]),
        }
    try:
        _persist_historical_cache()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[cache] Failed to persist historical cache: %s", exc)


def _history_to_ohlc_rows(history) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    today = _today_local()
    for idx, row in history.iterrows():
        row_date = idx.date()
        if row_date >= today:
            continue

        open_value = _to_float(row.get("Open"))
        high_value = _to_float(row.get("High"))
        low_value = _to_float(row.get("Low"))
        close_value = _to_float(row.get("Close"))
        volume_value = _to_int(row.get("Volume"))
        if (
            open_value is None
            or high_value is None
            or low_value is None
            or close_value is None
            or volume_value is None
        ):
            continue

        rows.append(
            {
                "date": str(row_date),
                "open": open_value,
                "high": high_value,
                "low": low_value,
                "close": close_value,
                "volume": volume_value,
            }
        )
    return rows


def _get_or_fetch_historical_rows(ticker: str, period: str) -> List[Dict[str, object]]:
    cached = _get_cached_historical_rows(ticker, period)
    if cached is not None:
        return cached

    history = _call_history_with_retry(ticker, period)
    if history.empty:
        return []

    rows = _history_to_ohlc_rows(history)
    _store_cached_historical_rows(ticker, period, rows)
    return rows


def _append_intraday_row(
    rows: List[Dict[str, object]],
    intraday_snapshot: Dict[str, object] | None,
) -> List[Dict[str, object]]:
    if intraday_snapshot is None:
        return rows

    open_value = _to_float(intraday_snapshot.get("open"))
    high_value = _to_float(intraday_snapshot.get("high"))
    low_value = _to_float(intraday_snapshot.get("low"))
    close_value = _to_float(intraday_snapshot.get("close"))
    volume_value = _to_int(intraday_snapshot.get("volume"))
    if (
        open_value is None
        or high_value is None
        or low_value is None
        or close_value is None
        or volume_value is None
    ):
        return rows

    today_str = _today_local_str()
    combined = [dict(row) for row in rows]
    if combined and combined[-1].get("date") == today_str:
        return combined

    combined.append(
        {
            "date": today_str,
            "open": open_value,
            "high": high_value,
            "low": low_value,
            "close": close_value,
            "volume": volume_value,
        }
    )
    return combined


def _get_cached_intraday_snapshot(ticker: str) -> Dict[str, object] | None:
    normalized = ticker.upper()
    with _intraday_cache_lock:
        entry = _intraday_cache.get(normalized)
        if not entry:
            return None
        updated_at = entry.get("updated_at")
        data = entry.get("data")
        if not isinstance(updated_at, (int, float)) or not isinstance(data, dict):
            return None
        if not _is_same_local_day(float(updated_at)):
            return None
        return _sanitize_json_value(dict(data))


def _store_cached_intraday_snapshot(
    ticker: str,
    data: Dict[str, object],
    *,
    updated_at: float | None = None,
    persist: bool = True,
) -> None:
    normalized = ticker.upper()
    timestamp = updated_at if updated_at is not None else time.time()
    with _intraday_cache_lock:
        _intraday_cache[normalized] = {
            "updated_at": timestamp,
            "data": _sanitize_json_value(dict(data)),
        }
    if persist:
        _persist_intraday_cache()


def list_stock_files() -> List[str]:
    return sorted(p.name for p in ROOT_DIR.glob("*.stocks"))


def read_stock_list(filename: str) -> List[str]:
    file_path = ROOT_DIR / filename
    if not file_path.exists() or file_path.suffix != ".stocks":
        raise FileNotFoundError(f"Unknown stock list: {filename}")

    with file_path.open("r", encoding="utf-8") as stream:
        return [line.strip() for line in stream if line.strip()]


def _collect_intraday_cache_tickers() -> List[str]:
    tickers: List[str] = []
    seen: set[str] = set()

    for filename in list_stock_files():
        try:
            file_tickers = read_stock_list(filename)
        except Exception:  # noqa: BLE001
            continue
        for ticker in file_tickers:
            normalized = ticker.upper()
            if normalized in seen:
                continue
            seen.add(normalized)
            tickers.append(normalized)

    for ticker in INDEX_TICKERS:
        if ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)

    return tickers


def start_intraday_cache_worker() -> None:
    global _intraday_cache_thread

    _load_intraday_cache()
    if _intraday_cache_thread and _intraday_cache_thread.is_alive():
        return

    _intraday_cache_stop_event.clear()

    def _worker() -> None:
        while not _intraday_cache_stop_event.is_set():
            try:
                refresh_intraday_cache()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[cache] Background refresh failed: %s", exc)
            if _intraday_cache_stop_event.wait(STOCK_CACHE_REFRESH_SECONDS):
                break

    _intraday_cache_thread = threading.Thread(
        target=_worker,
        name="intraday-cache-refresh",
        daemon=True,
    )
    _intraday_cache_thread.start()


def stop_intraday_cache_worker() -> None:
    global _intraday_cache_thread

    _intraday_cache_stop_event.set()
    if _intraday_cache_thread and _intraday_cache_thread.is_alive():
        _intraday_cache_thread.join(timeout=1.0)
    _intraday_cache_thread = None


def get_intraday_cache_status() -> Dict[str, object]:
    with _intraday_cache_lock:
        count = len(_intraday_cache)
        newest = max((entry["updated_at"] for entry in _intraday_cache.values()), default=None)
    return {
        "entries": count,
        "refresh_seconds": STOCK_CACHE_REFRESH_SECONDS,
        "cache_file": str(INTRADAY_CACHE_FILE),
        "last_updated": newest,
    }


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


def _to_float(value) -> float | None:
    try:
        if value is None:
            return None
        converted = float(value)
        if not math.isfinite(converted):
            return None
        return converted
    except (TypeError, ValueError):
        return None


def _to_int(value) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (OverflowError, TypeError, ValueError):
        return None


def _safe_mapping_get(mapping, *keys):
    if mapping is None:
        return None

    getter = getattr(mapping, "get", None)
    if callable(getter):
        for key in keys:
            value = getter(key)
            if value is not None:
                return value

    for key in keys:
        try:
            value = mapping[key]
            if value is not None:
                return value
        except Exception:  # noqa: BLE001
            continue
    return None


def _last_non_none(values: List[float | None]) -> float | None:
    for value in reversed(values):
        if value is not None:
            return value
    return None


def _compute_wilder_indicators(
    highs: List[float], lows: List[float], closes: List[float], period: int = 14
) -> Dict[str, float | None]:
    length = len(closes)
    if length <= period:
        return {
            "atr": None,
            "adx": None,
            "plus_di": None,
            "minus_di": None,
            "adxr": None,
        }

    tr: List[float] = [0.0] * length
    atr: List[float | None] = [None] * length
    plus_dm: List[float] = [0.0] * length
    minus_dm: List[float] = [0.0] * length
    plus_di: List[float | None] = [None] * length
    minus_di: List[float | None] = [None] * length
    dx: List[float | None] = [None] * length
    adx: List[float | None] = [None] * length
    adxr: List[float | None] = [None] * length

    tr[0] = highs[0] - lows[0]
    for i in range(1, length):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm[i] = up_move if up_move > down_move and up_move > 0 else 0.0
        minus_dm[i] = down_move if down_move > up_move and down_move > 0 else 0.0
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )

    first_atr = sum(tr[1 : period + 1]) / period
    atr[period] = first_atr
    for i in range(period + 1, length):
        previous_atr = atr[i - 1]
        if previous_atr is None:
            continue
        atr[i] = ((previous_atr * (period - 1)) + tr[i]) / period

    smoothed_tr = sum(tr[1 : period + 1])
    smoothed_plus = sum(plus_dm[1 : period + 1])
    smoothed_minus = sum(minus_dm[1 : period + 1])

    for i in range(period, length):
        if i > period:
            smoothed_tr = smoothed_tr - (smoothed_tr / period) + tr[i]
            smoothed_plus = smoothed_plus - (smoothed_plus / period) + plus_dm[i]
            smoothed_minus = smoothed_minus - (smoothed_minus / period) + minus_dm[i]

        if smoothed_tr <= 0:
            continue

        plus_di[i] = (smoothed_plus / smoothed_tr) * 100.0
        minus_di[i] = (smoothed_minus / smoothed_tr) * 100.0
        denominator = plus_di[i] + minus_di[i]
        if denominator > 0:
            dx[i] = (abs(plus_di[i] - minus_di[i]) / denominator) * 100.0

    adx_seed_values = [value for value in dx[period : period * 2] if value is not None]
    first_adx_index = (period * 2) - 1
    if adx_seed_values and first_adx_index < length:
        adx[first_adx_index] = sum(adx_seed_values) / len(adx_seed_values)
        for i in range(first_adx_index + 1, length):
            previous_adx = adx[i - 1]
            if previous_adx is None or dx[i] is None:
                continue
            adx[i] = ((previous_adx * (period - 1)) + dx[i]) / period

    for i in range(period, length):
        previous_index = i - period
        if adx[i] is None or adx[previous_index] is None:
            continue
        adxr[i] = (adx[i] + adx[previous_index]) / 2.0

    return {
        "atr": _last_non_none(atr),
        "adx": _last_non_none(adx),
        "plus_di": _last_non_none(plus_di),
        "minus_di": _last_non_none(minus_di),
        "adxr": _last_non_none(adxr),
    }


def _fetch_extended_metrics(ticker: str, latest_close: float) -> Dict[str, object]:
    extended: Dict[str, object] = {
        "last_close": None,
        "current_price": latest_close,
        "sma5": None,
        "sma20": None,
        "sma50": None,
        "sma200": None,
        "atr": None,
        "adx": None,
        "plus_di": None,
        "minus_di": None,
        "adxr": None,
        "adxr_x_atr": None,
        "market_cap": None,
        "trailing_pe": None,
        "forward_pe": None,
        "dividend_yield": None,
    }

    try:
        history_rows = _get_or_fetch_historical_rows(ticker, "1y")
        closes = [_to_float(row.get("close")) for row in history_rows]
        closes = [value for value in closes if value is not None]
        if closes:
            extended["last_close"] = closes[-1]

            if len(closes) >= 5:
                extended["sma5"] = _to_float(sum(closes[-5:]) / 5)
            if len(closes) >= 20:
                extended["sma20"] = _to_float(sum(closes[-20:]) / 20)
            if len(closes) >= 50:
                extended["sma50"] = _to_float(sum(closes[-50:]) / 50)
            if len(closes) >= 200:
                extended["sma200"] = _to_float(sum(closes[-200:]) / 200)

        ohlc_rows: List[tuple[float, float, float]] = []
        for row in history_rows:
            high_value = _to_float(row.get("high"))
            low_value = _to_float(row.get("low"))
            close_value = _to_float(row.get("close"))
            if high_value is None or low_value is None or close_value is None:
                continue
            ohlc_rows.append((high_value, low_value, close_value))

        if len(ohlc_rows) > 14:
            highs = [item[0] for item in ohlc_rows]
            lows = [item[1] for item in ohlc_rows]
            closes_for_indicators = [item[2] for item in ohlc_rows]
            indicators = _compute_wilder_indicators(highs, lows, closes_for_indicators, period=14)
            extended.update(indicators)
            if indicators["adxr"] is not None and indicators["atr"] is not None:
                extended["adxr_x_atr"] = indicators["adxr"] * indicators["atr"]
    except Exception:
        pass

    try:
        ticker_obj = yf.Ticker(ticker)
        fast_info = getattr(ticker_obj, "fast_info", None)

        fast_last = _to_float(_safe_mapping_get(fast_info, "lastPrice", "last_price"))
        if fast_last is not None:
            extended["current_price"] = fast_last

        fast_prev = _to_float(_safe_mapping_get(fast_info, "previousClose", "previous_close"))
        if fast_prev is not None:
            extended["last_close"] = fast_prev

        fast_market_cap = _to_int(_safe_mapping_get(fast_info, "marketCap", "market_cap"))
        if fast_market_cap is not None:
            extended["market_cap"] = fast_market_cap

        info = getattr(ticker_obj, "info", {}) or {}
        if extended["market_cap"] is None:
            extended["market_cap"] = _to_int(info.get("marketCap"))
        extended["trailing_pe"] = _to_float(info.get("trailingPE"))
        extended["forward_pe"] = _to_float(info.get("forwardPE"))

        dividend_yield = _to_float(info.get("dividendYield"))
        if dividend_yield is not None:
            extended["dividend_yield"] = dividend_yield
    except Exception:
        pass

    return extended


def _fetch_latest_ohlcv(ticker: str, period: str = "1d", include_extended: bool = True) -> Dict[str, object] | None:
    history = _call_history_with_retry(ticker, period)
    if history.empty:
        logger.warning("[yfinance] Empty history for %s (period=%s) — no data returned by Yahoo Finance", ticker, period)
        return None

    latest = history.iloc[-1]
    latest_close = float(latest["Close"])
    payload: Dict[str, object] = {
        "ticker": ticker,
        "open": float(latest["Open"]),
        "high": float(latest["High"]),
        "low": float(latest["Low"]),
        "close": latest_close,
        "volume": int(latest["Volume"]),
    }

    if include_extended:
        payload.update(_fetch_extended_metrics(ticker, latest_close))

    return payload


def fetch_ticker_history(ticker: str, period: str = "1mo") -> list:
    intraday_snapshot = _get_or_fetch_intraday_snapshot(ticker, include_extended=False)
    rows = _get_or_fetch_historical_rows(ticker, period)
    series = _append_intraday_row(rows, intraday_snapshot)
    points: List[Dict[str, object]] = []
    for row in series:
        close_value = _to_float(row.get("close"))
        volume_value = _to_int(row.get("volume"))
        if close_value is None or volume_value is None:
            continue
        points.append(
            {
                "date": str(row["date"]),
                "close": close_value,
                "volume": volume_value,
            }
        )
    return points


def fetch_ticker_history_ohlc(ticker: str, period: str = "1mo") -> list:
    intraday_snapshot = _get_or_fetch_intraday_snapshot(ticker, include_extended=False)
    rows = _get_or_fetch_historical_rows(ticker, period)
    return _append_intraday_row(rows, intraday_snapshot)


def _get_or_fetch_intraday_snapshot(ticker: str, *, include_extended: bool) -> Dict[str, object] | None:
    cached = _get_cached_intraday_snapshot(ticker)
    if cached is not None:
        if include_extended:
            metric_keys = ("atr", "adx", "plus_di", "minus_di", "adxr", "adxr_x_atr")
            has_all_metrics = all(_to_float(cached.get(key)) is not None for key in metric_keys)
            if not has_all_metrics:
                close_value = _to_float(cached.get("close"))
                if close_value is not None:
                    try:
                        enriched = dict(cached)
                        enriched.update(_fetch_extended_metrics(ticker, close_value))
                        _store_cached_intraday_snapshot(ticker, enriched)
                        return enriched
                    except Exception:
                        pass
        return cached

    data = _fetch_latest_ohlcv(ticker, period="1d", include_extended=include_extended)
    if data is not None:
        _store_cached_intraday_snapshot(ticker, data)
    return data


def refresh_intraday_cache() -> Dict[str, int]:
    refreshed = 0
    failed = 0

    for ticker in _collect_intraday_cache_tickers():
        try:
            data = _fetch_latest_ohlcv(ticker, period="1d", include_extended=ticker not in INDEX_TICKERS)
            if data is None:
                failed += 1
                continue
            _store_cached_intraday_snapshot(ticker, data, persist=False)
            refreshed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            logger.warning("[cache] Refresh failed for %s: %s", ticker, exc)

    if refreshed > 0:
        _persist_intraday_cache()

    logger.info("[cache] Intraday refresh complete: %d refreshed, %d failed", refreshed, failed)
    return {"refreshed": refreshed, "failed": failed}


def fetch_index_snapshot() -> Dict[str, Dict[str, float]]:
    snapshots: Dict[str, Dict[str, float]] = {}
    for name, ticker in INDEXES.items():
        try:
            data = _get_or_fetch_intraday_snapshot(ticker, include_extended=False)
            if data:
                snapshots[name] = {
                    "ticker": data["ticker"],
                    "open": data["open"],
                    "high": data["high"],
                    "low": data["low"],
                    "close": data["close"],
                    "volume": data["volume"],
                }
        except Exception:
            continue
    return snapshots


def _fetch_screen_snapshot(ticker: str, period: str) -> Dict[str, object] | None:
    if period == "1d":
        return _get_or_fetch_intraday_snapshot(ticker, include_extended=True)
    return _fetch_latest_ohlcv(ticker, period=period)


def screen_stock_list(filename: str, period: str = "1d") -> Dict[str, object]:
    tickers = read_stock_list(filename)
    results: List[Dict[str, object]] = []

    for ticker in tickers:
        try:
            data = _fetch_screen_snapshot(ticker, period)
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
    results: List[Dict[str, object]] = []

    failed = 0
    for i, ticker in enumerate(tickers, 1):
        try:
            data = _fetch_screen_snapshot(ticker, period)
            if data:
                results.append(data)
            else:
                failed += 1
                logger.warning("[screen] No data for %s", ticker)
        except UpstreamTimeoutError as exc:
            failed += 1
            logger.warning("[screen] Timeout for %s: %s", ticker, exc)
        except UpstreamServiceError as exc:
            failed += 1
            logger.warning("[screen] Service error for %s: %s", ticker, exc)
        except Exception as exc:
            failed += 1
            logger.warning("[screen] Unexpected error for %s: %s", ticker, exc)
        yield {"type": "progress", "done": i, "total": total}

    if failed > 0:
        logger.warning("[screen] Completed %s: %d/%d retrieved, %d failed", filename, len(results), total, failed)

    yield {
        "type": "complete",
        "stock_list": filename,
        "requested": total,
        "retrieved": len(results),
        "failed": failed,
        "stocks": results,
        "indexes": fetch_index_snapshot(),
    }


_load_intraday_cache()
_load_historical_cache()
