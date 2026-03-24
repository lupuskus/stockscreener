# FTSE Stock Screener

A Python-based stock screener that fetches real-time OHLCV (Open, High, Low, Close, Volume) data for FTSE 100 and FTSE 250 stocks using Yahoo Finance data.

## Features

- **Interactive Stock List Selection**: Choose between FTSE 100 or FTSE 250 stock lists
- **Real-time Data**: Fetches the latest trading data from Yahoo Finance
- **Comprehensive OHLCV Display**: Shows Open, High, Low, Close prices and trading volume
- **Error Handling**: Gracefully handles unavailable tickers
- **Clean Output**: Formatted table display for easy reading

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/lupuskus/stockscreener.git
   cd stockscreener
   ```

2. **Create a virtual environment (recommended):**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

## Usage

Run the stock screener:
```bash
python stockscreener.py
```

The program will:
1. Display available stock list files (FTSE 100 and FTSE 250)
2. Prompt you to select which list to screen
3. Fetch and display the latest OHLCV data for all stocks in the selected list

### Example Output
```
================================================================================
Latest Trading Data (OHLCV) - ftse100_stocks.txt
================================================================================
Ticker       Open       High        Low      Close        Volume
================================================================================
AAL.L      2345.00    2370.00    2330.00    2355.00    2,145,678
ABF.L       245.60     248.20     244.80     247.10    4,567,890
...
================================================================================

Total stocks retrieved: 98/100
```

## Stock Lists

The program includes two comprehensive stock lists:

- **ftse100_stocks.stocks**: Contains all 100 FTSE 100 index constituents
- **ftse250_stocks.stocks**: Contains 250+ FTSE 250 index constituents

All tickers use the `.L` suffix for London Stock Exchange listings.

## Requirements

- Python 3.7+
- yfinance (Yahoo Finance API)
- pandas (Data manipulation)

## Dependencies

- `yfinance>=0.2.0` - Yahoo Finance data API
- `pandas>=1.5.0` - Data analysis and display

## Data Source

Stock data is sourced from Yahoo Finance via the yfinance library. Please note:
- Data availability depends on Yahoo Finance's API
- Some stocks may be temporarily unavailable
- Historical data period is set to '1d' (latest trading day)

## Contributing

Feel free to contribute by:
- Adding more stock indices
- Improving error handling
- Adding new features like technical indicators
- Updating stock lists as indices change

## License

This project is open source. Feel free to use and modify as needed.

## Disclaimer

This tool is for educational and informational purposes only. Not intended as financial advice. Always do your own research before making investment decisions.