# TODO / Future Plans

This file tracks upcoming work outside the changelog.

## Next

- Add input validation for `period` on `/screen` and `/history`.
- Add request timeout and retry strategy around Yahoo Finance calls.
- Add basic tests for backend service functions and API routes.
- Add clear API error payload format for frontend display.
- add local logs for frontend and backend
- add watchlist functions (create watchlist, add to/delete from watchlist)
- add candle charts
- Add caching layer for repeated requests
- Add technical indicators (SMA, EMA, RSI, ADX/DMI) and fundamental screening.

## Soon

- Add selectable screening period from the frontend UI.
- Add sorting and filtering controls in frontend result table.
- Add ticker details panel with mini chart via `/history/{ticker}`.

## Later

- Add export options (CSV/JSON) for screening results.
- Add Docker setup for one-command local startup.
- Add CI checks (lint + tests) for pull requests.
