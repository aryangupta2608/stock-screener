import yfinance as yf

stock = yf.Ticker("AAPL")
price = stock.info['currentPrice']
print(f"Apple's current price: ${price}")