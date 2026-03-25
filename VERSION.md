# Version History and Plan

This document summarizes key past milestones and planned future milestones.

## Released

### release/0.1.0 (current release state)

- first version running on Render (https://stockscreener-tvyp.onrender.com) 
- Added FastAPI backend in `backend/`.
- Added endpoints for stock lists, screening, indexes, and ticker history.
- Added React frontend in `frontend/` for list selection and result display.
- Added startup helper script `startstockserver`.
- Added market sentiment comparison with FTSE 100 and FTSE 250 index snapshots.

## Planned

### release/0.2.0 (planned)

- Improve resilience for data fetch failures.
- Add backend tests and baseline CI.
- Improve frontend error and loading states.

### release/0.3.0 (planned)

- Add technical indicators and richer charting support.
- Add export options for screening results.
- Add containerized local run option.
