import yfinance as yf
import pandas as pd
import warnings
import os

# Suppress yfinance warnings
warnings.filterwarnings('ignore')

# List available stock list files
script_dir = os.path.dirname(__file__)
txt_files = [f for f in os.listdir(script_dir) if f.endswith('.txt')]

print("Available stock list files:")
for i, filename in enumerate(txt_files, 1):
    print(f"{i}. {filename}")

# Get user choice
while True:
    try:
        choice = int(input("\nEnter the number of the stock list file to use: "))
        if 1 <= choice <= len(txt_files):
            selected_file = txt_files[choice - 1]
            break
        else:
            print(f"Please enter a number between 1 and {len(txt_files)}")
    except ValueError:
        print("Please enter a valid number")

# Load selected stock list
stocks_file = os.path.join(script_dir, selected_file)
with open(stocks_file, 'r') as f:
    stocklist = [line.strip() for line in f if line.strip()]

print(f"\nLoading {len(stocklist)} stocks from {selected_file}...")

# Fetch the most recent data for each stock
data_list = []

for ticker in stocklist:
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period='1d')
        if not hist.empty:
            latest = hist.iloc[-1]
            data_list.append({
                'Ticker': ticker,
                'Open': f"{latest['Open']:>10.2f}",
                'High': f"{latest['High']:>10.2f}",
                'Low': f"{latest['Low']:>10.2f}",
                'Close': f"{latest['Close']:>10.2f}",
                'Volume': f"{int(latest['Volume']):>12,}"
            })
    except Exception as e:
        pass  # Silently skip unavailable tickers

# Create and display DataFrame
if data_list:
    df = pd.DataFrame(data_list)
    print("\n" + "=" * 110)
    print(f"Latest Trading Data (OHLCV) - {selected_file}")
    print("=" * 110)
    print(df.to_string(index=False))
    print("=" * 110)
    print(f"\nTotal stocks retrieved: {len(df)}/{len(stocklist)}")
else:
    print("No data retrieved")