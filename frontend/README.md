# Stock Screener Frontend

React frontend for the Stock Screener backend.

## Development

Start the Python backend from the repository root:

```bash
.venv/bin/python -m uvicorn backend.app:app --reload
```

Start the React app from this directory:

```bash
npm install
npm run dev
```

The app expects the backend at `http://127.0.0.1:8000` by default.

To override it, create a `.env.local` file in this directory:

```bash
VITE_API_URL=http://127.0.0.1:8000
```

## Build

```bash
npm run build
```
