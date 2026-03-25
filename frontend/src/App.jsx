import { useEffect, useState } from 'react'
import './App.css'

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

function formatPrice(value) {
  return new Intl.NumberFormat('en-GB', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

function formatVolume(value) {
  return new Intl.NumberFormat('en-GB').format(value)
}

function formatListName(filename) {
  return filename.replace('.stocks', '').replace(/[-_]/g, ' ').toUpperCase()
}

function sessionRange(stock) {
  return stock.high - stock.low
}

function App() {
  const [backendStatus, setBackendStatus] = useState('checking')
  const [stockLists, setStockLists] = useState([])
  const [selectedList, setSelectedList] = useState('')
  const [listDetails, setListDetails] = useState(null)
  const [screenResult, setScreenResult] = useState(null)
  const [loadingLists, setLoadingLists] = useState(true)
  const [loadingDetails, setLoadingDetails] = useState(false)
  const [loadingScreen, setLoadingScreen] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')

  useEffect(() => {
    async function loadInitialData() {
      setLoadingLists(true)
      setErrorMessage('')

      try {
        const healthResponse = await fetch(`${API_BASE_URL}/health`)
        setBackendStatus(healthResponse.ok ? 'online' : 'offline')

        const stockListResponse = await fetch(`${API_BASE_URL}/stock-lists`)
        if (!stockListResponse.ok) {
          throw new Error('Unable to load stock lists from the backend.')
        }

        const stockListPayload = await stockListResponse.json()
        const availableLists = stockListPayload.stock_lists ?? []

        setStockLists(availableLists)

        if (availableLists.length > 0) {
          setSelectedList(availableLists[0])
        }
      } catch (error) {
        setBackendStatus('offline')
        setErrorMessage(error.message)
      } finally {
        setLoadingLists(false)
      }
    }

    loadInitialData()
  }, [])

  useEffect(() => {
    if (!selectedList) {
      return
    }

    async function loadListDetails() {
      setLoadingDetails(true)

      try {
        const response = await fetch(`${API_BASE_URL}/stock-lists/${selectedList}`)
        if (!response.ok) {
          throw new Error('Unable to load stock list contents.')
        }

        const payload = await response.json()
        setListDetails(payload)
      } catch (error) {
        setErrorMessage(error.message)
      } finally {
        setLoadingDetails(false)
      }
    }

    loadListDetails()
  }, [selectedList])

  async function handleScreenSubmit(event) {
    event.preventDefault()

    if (!selectedList) {
      return
    }

    setLoadingScreen(true)
    setErrorMessage('')

    try {
      const response = await fetch(`${API_BASE_URL}/screen`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          stock_list: selectedList,
          period: '1d',
        }),
      })

      if (!response.ok) {
        throw new Error('Unable to screen the selected stock list.')
      }

      const payload = await response.json()
      setScreenResult(payload)
    } catch (error) {
      setErrorMessage(error.message)
    } finally {
      setLoadingScreen(false)
    }
  }

  const activeIndexes = Object.entries(screenResult?.indexes ?? {})

  return (
    <main className="app-shell">
      <section className="hero-panel">
        <div className="hero-copy">
          <p className="eyebrow">FTSE market monitor</p>
          <h1>Screen UK stocks from a browser instead of a Java console.</h1>
          <p className="lead">
            Pick a saved list, run a fresh screen against the Python backend, and
            compare price action with the FTSE 100 and FTSE 250 snapshots.
          </p>
        </div>

        <div className="status-strip">
          <div className={`status-pill status-pill--${backendStatus}`}>
            Backend {backendStatus}
          </div>
          <div className="status-pill">API {API_BASE_URL}</div>
        </div>
      </section>

      <section className="workspace-grid">
        <form className="control-panel" onSubmit={handleScreenSubmit}>
          <div className="panel-heading">
            <p className="section-label">List selection</p>
            <h2>Choose what to screen</h2>
          </div>

          <label className="field-label" htmlFor="stock-list">
            Saved stock list
          </label>
          <select
            id="stock-list"
            className="list-select"
            value={selectedList}
            disabled={loadingLists || stockLists.length === 0}
            onChange={(event) => setSelectedList(event.target.value)}
          >
            {stockLists.map((stockList) => (
              <option key={stockList} value={stockList}>
                {formatListName(stockList)}
              </option>
            ))}
          </select>

          <button
            className="screen-button"
            type="submit"
            disabled={!selectedList || loadingScreen}
          >
            {loadingScreen ? 'Screening…' : 'Run 1-day screen'}
          </button>

          <div className="meta-block">
            <span>Available lists</span>
            <strong>{loadingLists ? 'Loading…' : stockLists.length}</strong>
          </div>

          <div className="meta-block">
            <span>Tickers in selection</span>
            <strong>
              {loadingDetails ? 'Loading…' : listDetails?.count ?? 'Not loaded'}
            </strong>
          </div>

          {errorMessage ? <p className="error-banner">{errorMessage}</p> : null}
        </form>

        <aside className="detail-panel">
          <div className="panel-heading">
            <p className="section-label">List contents</p>
            <h2>{selectedList ? formatListName(selectedList) : 'No list selected'}</h2>
          </div>

          <div className="ticker-cloud">
            {(listDetails?.tickers ?? []).map((ticker) => (
              <span key={ticker} className="ticker-chip">
                {ticker}
              </span>
            ))}
          </div>
        </aside>
      </section>

      <section className="results-panel">
        <div className="panel-heading panel-heading--wide">
          <div>
            <p className="section-label">Market snapshot</p>
            <h2>Indexes and screened stocks</h2>
          </div>
          {screenResult ? (
            <div className="result-summary">
              Retrieved {screenResult.retrieved} of {screenResult.requested}
            </div>
          ) : null}
        </div>

        <div className="index-grid">
          {activeIndexes.length === 0 ? (
            <div className="empty-state">Run a screen to load the latest index data.</div>
          ) : (
            activeIndexes.map(([indexName, indexData]) => (
              <article key={indexName} className="index-card">
                <p className="index-card__label">{indexName.toUpperCase()}</p>
                <strong>{formatPrice(indexData.close)}</strong>
                <span>
                  Day range {formatPrice(indexData.low)} to {formatPrice(indexData.high)}
                </span>
              </article>
            ))
          )}
        </div>

        <div className="table-shell">
          {screenResult ? (
            <table>
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th>Open</th>
                  <th>High</th>
                  <th>Low</th>
                  <th>Close</th>
                  <th>Range</th>
                  <th>Volume</th>
                </tr>
              </thead>
              <tbody>
                {screenResult.stocks.map((stock) => (
                  <tr key={stock.ticker}>
                    <td>{stock.ticker}</td>
                    <td>{formatPrice(stock.open)}</td>
                    <td>{formatPrice(stock.high)}</td>
                    <td>{formatPrice(stock.low)}</td>
                    <td>{formatPrice(stock.close)}</td>
                    <td>{formatPrice(sessionRange(stock))}</td>
                    <td>{formatVolume(stock.volume)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="empty-state empty-state--table">
              Select a list and run the screen to populate the table.
            </div>
          )}
        </div>
      </section>
    </main>
  )
}

export default App
