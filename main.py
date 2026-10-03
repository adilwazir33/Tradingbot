import os
import time
import threading
import requests
import yfinance as yf
import pandas as pd
import numpy as np
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

# --- Port fix for Render Web Service ---
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Live")
    def log_message(self, *a):
        return
def run_s():
    p=int(os.environ.get("PORT",10000))
    HTTPServer(("0.0.0.0",p),H).serve_forever()
threading.Thread(target=run_s,daemon=True).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SYMBOLS = [
    ("EURUSD=X", "EUR/USD"),
    ("GBPUSD=X", "GBP/USD"),
    ("USDJPY=X", "USD/JPY"),
    ("BTC-USD", "BTC/USD"),
    ("ETH-USD", "ETH/USD"),
    ("SOL-USD", "SOL/USD"),
    ("GC=F", "GOLD"),
    ("SI=F", "SILVER"),
]

def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except:
        pass

def get_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def check_signal(ticker):
    try:
        # 15m, 1H, 4H data
        df_15 = yf.download(ticker, period="5d", interval="15m", progress=False)
        df_1h = yf.download(ticker, period="1mo", interval="1h", progress=False)
        df_4h = yf.download(ticker, period="3mo", interval="4h", progress=False)
        if df_15.empty or df_1h.empty or df_4h.empty:
            return None
        
        # RSI 15m
        rsi_15 = get_rsi(df_15['Close']).
