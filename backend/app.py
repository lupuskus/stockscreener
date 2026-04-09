from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from datetime import datetime, timezone
import json
import os
import re
import subprocess

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from fastapi import Request
from pydantic import BaseModel, Field

from backend.service import (
    UpstreamServiceError,
    UpstreamTimeoutError,
    add_watchlist_ticker,
    fetch_index_snapshot,
    fetch_ticker_history,
    fetch_ticker_history_ohlc,
    fetch_ticker_history_ohlc_interval,
    get_watchlist,
    list_stock_files,
    read_stock_list,
    remove_watchlist_ticker,
    screen_stock_list,
    screen_stock_list_stream,
    start_intraday_cache_worker,
    stop_intraday_cache_worker,
)


app = FastAPI(title="Stock Screener API", version=os.getenv("APP_VERSION", "0.3.0"))

@app.on_event("startup")
def startup_event() -> None:
    start_intraday_cache_worker()


@app.on_event("shutdown")
def shutdown_event() -> None:
    stop_intraday_cache_worker()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TABLE_PRESETS_PATH = Path(__file__).resolve().parent.parent / "table_presets.toml"
_CHART_PRESETS_PATH = Path(__file__).resolve().parent.parent / "chart_presets.toml"
_TICKER_RE = re.compile(r'^[\w.\-\^=]{1,20}$')
_STOCK_LIST_RE = re.compile(r'^[A-Za-z0-9._\-]+\.stocks$')
_ALLOWED_PERIODS = {
    "1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"
}
_ALLOWED_CHART_INTERVALS = {"1h", "4h", "1d", "1wk"}
_APP_VERSION = os.getenv("APP_VERSION", "0.3.0")


def _run_git_command(args: List[str]) -> str | None:
    try:
        value = subprocess.check_output(
            ["git", *args],
            cwd=str(_PROJECT_ROOT),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return None
    return value or None


def _build_number_from_commit(commit: str) -> str | None:
    hex_part = "".join(ch for ch in commit.lower() if ch in "0123456789abcdef")[:8]
    if not hex_part:
        return None
    try:
        return str(int(hex_part, 16))
    except ValueError:
        return None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_metadata() -> Dict[str, str]:
    branch = os.getenv("RENDER_GIT_BRANCH") or os.getenv("GIT_BRANCH") or _run_git_command(["rev-parse", "--abbrev-ref", "HEAD"]) or "local"
    commit = os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT") or _run_git_command(["rev-parse", "HEAD"]) or "local"
    short_commit = commit[:7] if commit != "local" else commit

    build_number = os.getenv("BUILD_NUMBER")
    if not build_number and commit != "local":
        build_number = _run_git_command(["rev-list", "--count", commit])
    if not build_number and commit != "local":
        build_number = _build_number_from_commit(commit)
    if not build_number:
        build_number = "0"

    built_at = os.getenv("BUILD_TIMESTAMP")
    if not built_at and commit != "local":
        built_at = _run_git_command(["show", "-s", "--format=%cI", commit])
    if not built_at:
        built_at = _utc_now_iso()

    return {
        "version": _APP_VERSION,
        "branch": branch,
        "commit": commit,
        "short_commit": short_commit,
        "build_number": build_number,
        "built_at": built_at,
    }


_BUILD_METADATA = _build_metadata()


def _default_table_presets() -> Dict[str, object]:
    return {
        "default_preset": "ohlcv",
        "presets": [
            {
                "id": "ohlcv",
                "label": "OHLC + Volume",
                "columns": [
                    {"key": "ticker", "label": "Ticker", "format": "text", "sortable": True},
                    {"key": "watch_toggle", "label": "Watch", "format": "watch_toggle", "sortable": False},
                    {"key": "close", "label": "Close", "format": "price", "sortable": True},
                    {"key": "chg", "label": "Chg", "format": "price", "sortable": True},
                    {"key": "chgpct", "label": "Chg %", "format": "percent", "sortable": True},
                    {"key": "open", "label": "Open", "format": "price", "sortable": True},
                    {"key": "high", "label": "High", "format": "price", "sortable": True},
                    {"key": "low", "label": "Low", "format": "price", "sortable": True},
                    {"key": "volume", "label": "Volume", "format": "volume", "sortable": True},
                ],
            }
        ],
    }


def _normalize_table_presets(raw_payload: Dict[str, object]) -> Dict[str, object]:
    presets = raw_payload.get("presets", []) if isinstance(raw_payload, dict) else []
    normalized_presets: List[Dict[str, object]] = []

    if isinstance(presets, list):
        for preset in presets:
            if not isinstance(preset, dict):
                continue
            preset_id = str(preset.get("id", "")).strip()
            preset_label = str(preset.get("label", preset_id)).strip()
            if not preset_id:
                continue

            columns_raw = preset.get("columns", [])
            columns: List[Dict[str, object]] = []
            if isinstance(columns_raw, list):
                for column in columns_raw:
                    if not isinstance(column, dict):
                        continue
                    key = str(column.get("key", "")).strip()
                    label = str(column.get("label", key)).strip()
                    if not key:
                        continue
                    columns.append(
                        {
                            "key": key,
                            "label": label or key,
                            "format": str(column.get("format", "text")).strip() or "text",
                            "sortable": bool(column.get("sortable", True)),
                        }
                    )

            if columns:
                normalized_presets.append({"id": preset_id, "label": preset_label or preset_id, "columns": columns})

    if not normalized_presets:
        return _default_table_presets()

    default_preset = str(raw_payload.get("default_preset", "")).strip() if isinstance(raw_payload, dict) else ""
    available_ids = {preset["id"] for preset in normalized_presets}
    if default_preset not in available_ids:
        default_preset = normalized_presets[0]["id"]

    return {
        "default_preset": default_preset,
        "presets": normalized_presets,
    }


def _load_table_presets() -> Dict[str, object]:
    if not _TABLE_PRESETS_PATH.exists():
        return _default_table_presets()

    try:
        with _TABLE_PRESETS_PATH.open("rb") as stream:
            payload = tomllib.load(stream)
        return _normalize_table_presets(payload)
    except Exception:
        return _default_table_presets()


def _default_chart_presets() -> Dict[str, object]:
    return {
        "default_preset": "candles_volume",
        "presets": [
            {
                "id": "candles_volume",
                "label": "Candles + Volume",
                "mode": "candles",
                "default_indicator": "rsi",
            },
            {
                "id": "technical_indicators",
                "label": "Bollinger + Indicators",
                "mode": "technical",
                "default_indicator": "rsi",
            },
            {
                "id": "welles_wilder",
                "label": "Welles Wilder",
                "mode": "wilder",
                "default_indicator": "wilder_pack",
            },
        ],
    }


def _normalize_chart_presets(raw_payload: Dict[str, object]) -> Dict[str, object]:
    presets = raw_payload.get("presets", []) if isinstance(raw_payload, dict) else []
    normalized_presets: List[Dict[str, str]] = []

    if isinstance(presets, list):
        for preset in presets:
            if not isinstance(preset, dict):
                continue
            preset_id = str(preset.get("id", "")).strip()
            label = str(preset.get("label", preset_id)).strip()
            mode = str(preset.get("mode", "candles")).strip().lower()
            default_indicator = str(preset.get("default_indicator", "rsi")).strip().lower()
            if not preset_id:
                continue
            if mode not in {"candles", "technical", "wilder"}:
                mode = "candles"
            if default_indicator not in {"rsi", "atr", "adx_dmi", "wilder_pack"}:
                default_indicator = "rsi"

            normalized_presets.append(
                {
                    "id": preset_id,
                    "label": label or preset_id,
                    "mode": mode,
                    "default_indicator": default_indicator,
                }
            )

    if not normalized_presets:
        return _default_chart_presets()

    default_preset = str(raw_payload.get("default_preset", "")).strip() if isinstance(raw_payload, dict) else ""
    available_ids = {preset["id"] for preset in normalized_presets}
    if default_preset not in available_ids:
        default_preset = normalized_presets[0]["id"]

    return {
        "default_preset": default_preset,
        "presets": normalized_presets,
    }


def _load_chart_presets() -> Dict[str, object]:
    if not _CHART_PRESETS_PATH.exists():
        return _default_chart_presets()

    try:
        with _CHART_PRESETS_PATH.open("rb") as stream:
            payload = tomllib.load(stream)
        return _normalize_chart_presets(payload)
    except Exception:
        return _default_chart_presets()


def _bad_request_detail(*, code: str, message: str, field: str, value: str | None = None) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "error": {
            "type": "bad_request",
            "code": code,
            "message": message,
            "field": field,
        }
    }
    if value is not None:
        payload["error"]["value"] = value
    return payload


def _raise_bad_request(*, code: str, message: str, field: str, value: str | None = None) -> None:
    raise HTTPException(
        status_code=400,
        detail=_bad_request_detail(code=code, message=message, field=field, value=value),
    )


def _normalize_period(period: str) -> str:
    normalized = period.strip().lower()
    if normalized not in _ALLOWED_PERIODS:
        _raise_bad_request(
            code="invalid_period",
            message="Unsupported period. Use one of: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max.",
            field="period",
            value=period,
        )
    return normalized


def _normalize_ticker(ticker: str) -> str:
    normalized = ticker.strip().upper()
    if not _TICKER_RE.match(normalized):
        _raise_bad_request(
            code="invalid_ticker",
            message="Ticker contains unsupported characters or length.",
            field="ticker",
            value=ticker,
        )
    return normalized


def _normalize_chart_interval(interval: str) -> str:
    normalized = interval.strip().lower()
    if normalized not in _ALLOWED_CHART_INTERVALS:
        _raise_bad_request(
            code="invalid_interval",
            message="Unsupported interval. Use one of: 1h, 4h, 1d, 1wk.",
            field="interval",
            value=interval,
        )
    return normalized


def _normalize_stock_list(stock_list: str) -> str:
    normalized = stock_list.strip()
    if not _STOCK_LIST_RE.match(normalized):
        _raise_bad_request(
            code="invalid_stock_list",
            message="Stock list must be a .stocks filename (letters, numbers, dot, underscore, hyphen).",
            field="stock_list",
            value=stock_list,
        )
    return normalized


@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


class ScreenRequest(BaseModel):
    stock_list: str = Field(..., description="Name of the .stocks file")
    period: str = Field("1d", description="Yahoo Finance period string")


class WatchlistRequest(BaseModel):
    ticker: str = Field(..., description="Ticker symbol to add/remove from watchlist")


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    first_error = exc.errors()[0] if exc.errors() else {}
    location = first_error.get("loc", [])
    field = str(location[-1]) if location else "request"
    message = first_error.get("msg", "Invalid request payload.")
    return JSONResponse(
        status_code=400,
        content=_bad_request_detail(code="invalid_request", message=message, field=field),
    )


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/build-info")
def build_info() -> Dict[str, str]:
    return _BUILD_METADATA


@app.get("/stock-lists")
def stock_lists() -> Dict[str, List[str]]:
    return {"stock_lists": list_stock_files()}


@app.get("/table-presets")
def table_presets() -> Dict[str, object]:
    return _load_table_presets()


@app.get("/chart-presets")
def chart_presets() -> Dict[str, object]:
    return _load_chart_presets()


@app.get("/watchlist")
def watchlist() -> Dict[str, object]:
    tickers = get_watchlist()
    return {
        "watchlist": tickers,
        "count": len(tickers),
    }


@app.post("/watchlist")
def add_watchlist(payload: WatchlistRequest) -> Dict[str, object]:
    normalized_ticker = _normalize_ticker(payload.ticker)
    added, tickers = add_watchlist_ticker(normalized_ticker)
    return {
        "ticker": normalized_ticker,
        "added": added,
        "watchlist": tickers,
        "count": len(tickers),
    }


@app.delete("/watchlist/{ticker}")
def remove_watchlist(ticker: str) -> Dict[str, object]:
    normalized_ticker = _normalize_ticker(ticker)
    removed, tickers = remove_watchlist_ticker(normalized_ticker)
    return {
        "ticker": normalized_ticker,
        "removed": removed,
        "watchlist": tickers,
        "count": len(tickers),
    }


@app.get("/stock-lists/{filename}")
def stock_list_contents(filename: str) -> Dict[str, object]:
    try:
        tickers = read_stock_list(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "stock_list": filename,
        "count": len(tickers),
        "tickers": tickers,
    }


@app.get("/indexes")
def indexes() -> Dict[str, Dict[str, float]]:
    data = fetch_index_snapshot()
    # Remove 'ticker' field (it's a string, response should be all floats)
    return {name: {k: v for k, v in d.items() if k != 'ticker'} for name, d in data.items()}


@app.get("/history/{ticker}")
def history(ticker: str, period: str = "1mo") -> Dict[str, object]:
    normalized_ticker = _normalize_ticker(ticker)
    normalized_period = _normalize_period(period)
    try:
        series = fetch_ticker_history(normalized_ticker, period=normalized_period)
    except UpstreamTimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail={
                "error": {
                    "type": "upstream_timeout",
                    "code": "yahoo_timeout",
                    "message": str(exc),
                    "field": "ticker",
                    "value": normalized_ticker,
                    "retryable": True,
                }
            },
        ) from exc
    except UpstreamServiceError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "type": "upstream_error",
                    "code": "yahoo_request_failed",
                    "message": str(exc),
                    "field": "ticker",
                    "value": normalized_ticker,
                    "retryable": True,
                }
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=_bad_request_detail(
                code="history_fetch_failed",
                message=str(exc),
                field="ticker",
                value=normalized_ticker,
            ),
        ) from exc
    return {"ticker": normalized_ticker, "series": series}


@app.get("/history-ohlc/{ticker}")
def history_ohlc(ticker: str, period: str = "1mo", interval: str = "1d") -> Dict[str, object]:
    normalized_ticker = _normalize_ticker(ticker)
    normalized_interval = _normalize_chart_interval(interval)
    try:
        if normalized_interval == "1d":
            normalized_period = _normalize_period(period)
            series = fetch_ticker_history_ohlc(normalized_ticker, period=normalized_period)
        else:
            series = fetch_ticker_history_ohlc_interval(normalized_ticker, interval=normalized_interval)
    except UpstreamTimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail={
                "error": {
                    "type": "upstream_timeout",
                    "code": "yahoo_timeout",
                    "message": str(exc),
                    "field": "ticker",
                    "value": normalized_ticker,
                    "retryable": True,
                }
            },
        ) from exc
    except UpstreamServiceError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "type": "upstream_error",
                    "code": "yahoo_request_failed",
                    "message": str(exc),
                    "field": "ticker",
                    "value": normalized_ticker,
                    "retryable": True,
                }
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=_bad_request_detail(
                code="history_fetch_failed",
                message=str(exc),
                field="ticker",
                value=normalized_ticker,
            ),
        ) from exc
    return {"ticker": normalized_ticker, "series": series}


@app.get("/screen/stream")
def screen_stream(stock_list: str, period: str = "1d"):
    normalized_stock_list = _normalize_stock_list(stock_list)
    normalized_period = _normalize_period(period)

    def generate():
        try:
            for event in screen_stock_list_stream(normalized_stock_list, normalized_period):
                yield f"data: {json.dumps(event)}\n\n"
        except FileNotFoundError as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        except Exception:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Screen failed'})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/screen")
def screen(payload: ScreenRequest) -> Dict[str, object]:
    normalized_stock_list = _normalize_stock_list(payload.stock_list)
    normalized_period = _normalize_period(payload.period)
    try:
        return screen_stock_list(normalized_stock_list, period=normalized_period)
    except UpstreamTimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail={
                "error": {
                    "type": "upstream_timeout",
                    "code": "yahoo_timeout",
                    "message": str(exc),
                    "field": "period",
                    "value": normalized_period,
                    "retryable": True,
                }
            },
        ) from exc
    except UpstreamServiceError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "type": "upstream_error",
                    "code": "yahoo_request_failed",
                    "message": str(exc),
                    "field": "period",
                    "value": normalized_period,
                    "retryable": True,
                }
            },
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
