from __future__ import annotations

from typing import Dict, List

import json
import os
import re

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
    get_watchlist,
    list_stock_files,
    read_stock_list,
    remove_watchlist_ticker,
    screen_stock_list,
    screen_stock_list_stream,
)


app = FastAPI(title="Stock Screener API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")
_TICKER_RE = re.compile(r'^[\w.\-\^=]{1,20}$')
_STOCK_LIST_RE = re.compile(r'^[A-Za-z0-9._\-]+\.stocks$')
_ALLOWED_PERIODS = {
    "1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"
}


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


@app.get("/stock-lists")
def stock_lists() -> Dict[str, List[str]]:
    return {"stock_lists": list_stock_files()}


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
def history_ohlc(ticker: str, period: str = "1mo") -> Dict[str, object]:
    normalized_ticker = _normalize_ticker(ticker)
    normalized_period = _normalize_period(period)
    try:
        series = fetch_ticker_history_ohlc(normalized_ticker, period=normalized_period)
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
