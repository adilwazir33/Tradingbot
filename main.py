import time
import requests
from datetime import datetime

print("Bot Started - 24/7 Live")

SYMBOL = "BTCUSDT"

def get_price():
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={SYMBOL}"
        r = requests.get(url, timeout=10)
        return float(r.json()['price'])
    except:
        return None

while True:
    price = get_price()
    if price:
        print(f"{datetime.now()} | {SYMBOL}: ${price}")
    time.sleep(60)
