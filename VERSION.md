# Version History and Plan

This document summarizes the main stock screener releases and their key changes.

## Released

### release/0.3.0 (current release state)

- Added Wilder screening table columns: ATR(14), ADX(14), +DI(14), -DI(14), ADXR(14), and ADXRxATR.
- Added chart preset split between Bollinger and Welles Wilder views.
- Added Parabolic SAR support in chart rendering.
- Added technical indicator rendering in charts (RSI, ATR, ADX/DMI/ADXR, Wilder Pack) and richer chart presets.
- Added robust SSE payload sanitization for non-finite numeric values.
- Added intraday cache for latest 1d snapshots with background refresh (default every 15 minutes).
- Added historical OHLC cache with market-close-aware refresh behavior.
- Hardened history assembly against incomplete upstream rows to avoid intermittent 400 responses.
- Added stable build/version metadata endpoint and frontend display (version, build, timestamp, branch/commit).
- Added persistent frontend view state restore (selected list/view/chart period/presets/ticker).
- Added DAX index snapshot support and DAX constituents list.
- Added chart timeframes: Weekly, Daily, 4H, 1H, with zoom controls and viewport-based default bars (mobile 20 / desktop 30).
- Improved mobile layout behavior for market strip and chart controls.

### release/0.2.0

- uploaded to Render.
- Added stricter validation for `/screen` and `/history` requests.
- Added clearer `400` error responses with field-specific details.
- Added configurable timeout and retry handling for Yahoo Finance requests.
- Added watchlist endpoints with persistent ticker storage.
- Added candlestick charts for price history.
- Added trading volume overlays to charts.
- Added table, chart, and split frontend views.
- Added a progress indicator for longer screening runs.

### release/0.1.0

- First deployed version running on Render: https://stockscreener-tvyp.onrender.com
- Added a FastAPI backend for the stock screening API.
- Added a static browser UI for list selection and results.
- Added endpoints for stock lists, screening, market indexes, and price history.
- Added FTSE 100 and FTSE 250 snapshots for market comparison.

