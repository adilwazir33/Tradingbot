import os, threading, time
from datetime import datetime, timedelta
from flask import Flask
import telebot
import yfinance as yf
import pandas as pd
import numpy as np

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
@app.route('/')
def home(): return "ADIL 99% BOT LIVE"

PAIRS = {"GOLD":"GC=F","EURUSD.r":"EURUSD=X","BTCUSD.r":"BTC-USD"}
REAL = {"GOLD":"GOLD","EURUSD.r":"EURUSD.r","BTCUSD.r":"BTCUSD.r"}

def fmt(n,p):
    if p==0: return "---"
    if "GOLD" in n: return f"{p:.2f}"
    if "EUR" in n: return f"{p:.5f}"
    return f"{p:.2f}"

def rsi_calc(close, period=14):
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def get_99_signal(ticker, tf):
    try:
        hist = yf.Ticker(ticker).history(period="5d" if tf=="15m" else "1mo", interval=tf)
        if len(hist) < 50: return "WAIT",0,0,0,0,0,"Data Kam",0

        close = hist['Close']
        last = float(close.iloc[-1])
        
        # Indicators
        ema9 = float(close.ewm(span=9).mean().iloc[-1])
        ema21 = float(close.ewm(span=21).mean().iloc[-1])
        sma50 = float(close.rolling(50).mean().iloc[-1])
        rsi = float(rsi_calc(close).iloc[-1])
        
        # MACD
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd = ema12 - ema26
        signal_line = macd.ewm(span=9).mean()
        macd_last = float(macd.iloc[-1])
        sig_last = float(signal_line.iloc[-1])
        macd_prev = float(macd.iloc[-2])
        sig_prev = float(signal_line.iloc[-2])

        # Score System - 99% Logic
        buy_score = 0
        sell_score = 0

        # 1. EMA Trend
        if ema9 > ema21 > sma50: buy_score += 1
        if ema9 < ema21 < sma50: sell_score += 1

        # 2. RSI Filter
        if 50 < rsi < 70: buy_score += 1
        if 30 < rsi < 50: sell_score += 1
        if rsi > 75 or rsi < 25: return "WAIT",last,0,0,0,0,f"RSI Over {rsi:.1f}",rsi

        # 3. MACD Cross
        if macd_prev < sig_prev and macd_last > sig_last: buy_score += 1
        if macd_prev > sig_prev and macd_last < sig_last: sell_score += 1

        # 4. Price vs EMA
        if last > ema9: buy_score += 1
        if last < ema9: sell_score += 1

        # Sideways Check
        diff = abs(last - sma50)/sma50*100
        if diff < 0.05 and "EUR" not in ticker and "BTC" not in ticker:
            return "WAIT",last,0,0,0,0,f"Sideways {diff:.2f}%",rsi
        if "EUR" in ticker and diff < 0.015:
            return "WAIT",last,0,0,0,0,f"Sideways {diff:.3f}%",rsi

        # News Time
        now = datetime.utcnow() + timedelta(hours=4)
        if 16 <= now.hour <= 18 and ("GC" in ticker or "EUR" in ticker):
            return "WAIT",last,0,0,0,0,"US News WAIT",rsi

        # Final Decision - 99% Logic: Kam se kam 3 point chahiye
        if buy_score >= 3:
            sig = "BUY"
        elif sell_score >= 3:
            sig = "SELL"
        else:
            return "WAIT",last,0,0,0,0,f"Score B:{buy_score} S:{sell_score}",rsi

        # ATR SL/TP
        if "GC" in ticker: sl_p,tp1_p,tp2_p,tp3_p = (0.004,0.006,0.012,0.020) if tf=="15m" else (0.006,0.008,0.015,0.025)
        elif "BTC" in ticker: sl_p,tp1_p,tp2_p,tp3_p = (0.008,0.01,0.02,0.035) if tf=="15m" else (0.012,0.015,0.03,0.05)
        else: sl_p,tp1_p,tp2_p,tp3_p = (0.001,0.0015,0.003,0.005) if tf=="15m" else (0.002,0.003,0.006,0.01)

        if
