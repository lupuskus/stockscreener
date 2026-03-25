from __future__ import annotations

from typing import Dict, List

import os
import re

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.service import fetch_index_snapshot, fetch_ticker_history, list_stock_files, read_stock_list, screen_stock_list


app = FastAPI(title="Stock Screener API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")


@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


class ScreenRequest(BaseModel):
    stock_list: str = Field(..., description="Name of the .stocks file")
    period: str = Field("1d", description="Yahoo Finance period string")


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/stock-lists")
def stock_lists() -> Dict[str, List[str]]:
    return {"stock_lists": list_stock_files()}


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


_TICKER_RE = re.compile(r'^[\w.\-\^=]{1,20}$')


@app.get("/history/{ticker}")
def history(ticker: str, period: str = "1mo") -> Dict[str, object]:
    if not _TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker symbol")
    try:
        series = fetch_ticker_history(ticker, period=period)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ticker": ticker, "series": series}


@app.post("/screen")
def screen(payload: ScreenRequest) -> Dict[str, object]:
    try:
        return screen_stock_list(payload.stock_list, period=payload.period)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
