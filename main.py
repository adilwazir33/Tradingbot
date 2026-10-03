import os
import time
import requests
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime

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

def get_indicators(df):
    df['EMA21'] = df['Close'].ewm(span=21).mean()
    df['EMA50'] = df['Close'].ewm(span=50).mean()
    df['EMA200'] = df['Close'].ewm(span=200).mean()
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    ema12 = df['Close'].ewm(span=12).mean()
    ema26 = df['Close'].ewm(span=26).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_SIGNAL'] = df['MACD'].ewm(span=9).mean()
    tr1 = df['High'] - df['Low']
    tr2 = (df['High'] - df['Close'].shift()).abs()
    tr3 = (df['Low'] - df['Close'].shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()
    df['BB_MID'] = df['Close'].rolling(20).mean()
    df['BB_STD'] = df['Close'].rolling(20).std()
    df['BB_UP'] = df['BB_MID'] + 2*df['BB_STD']
    df['BB_LOW'] = df['BB_MID'] - 2*df['BB_STD']
    return df

def analyze(name, ticker):
    try:
        # TRIPLE TIMEFRAME DATA
        df_15m = yf.download(ticker, period="5d", interval="15m", progress=False, auto_adjust=True)
        df_1h = yf.download(ticker, period="10d", interval="1h", progress=False, auto_adjust=True)
        df_4h = yf.download(ticker, period="30d", interval="4h", progress=False, auto_adjust=True)
        
        if len(df_15m) < 100 or len(df_1h) < 50 or len(df_4h) < 50:
            return f"⚪ {name}: WAIT - Low Data"

        df_15m = get_indicators(df_15m)
        df_1h = get_indicators(df_1h)
        df_4h = get_indicators(df_4h)

        c15 = df_15m.iloc[-1]
        c1 = df_1h.iloc[-1]
        c4 = df_4h.iloc[-1]

        price = float(c15['Close'])
        atr = float(c15['ATR']) if not np.isnan(c15['ATR']) else price*0.003
        rsi15 = float(c15['RSI'])
        rsi1 = float(c1['RSI'])

        # TRENDS
        trend_4h_bull = c4['Close'] > c4['EMA50'] and c4['EMA21'] > c4['EMA50']
        trend_4h_bear = c4['Close'] < c4['EMA50'] and c4['EMA21'] < c4['EMA50']
        trend_1h_bull = c1['Close'] > c1['EMA50'] and c1['EMA21'] > c1['EMA50']
        trend_1h_bear = c1['Close'] < c1['EMA50'] and c1['EMA21'] < c1['EMA50']
        
        # 15m structure
        price_above_ema21_15 = price > float(c15['EMA21'])
        ema_stack_bull_15 = c15['EMA21'] > c15['EMA50'] > c15['EMA200']
        ema_stack_bear_15 = c15['EMA21'] < c15['EMA50'] < c15['EMA200']

        score = 0
        reasons = []

        # 4H BIG TREND = 3 points
        if trend_4h_bull:
            score += 2
            reasons.append("4H BULL")
        if trend_4h_bear:
            score += 2
            reasons.append("4H BEAR")

        # 1H TREND = 2 points
        if trend_1h_bull and trend_4h_bull:
            score += 3
            reasons.append("1H+4H BULL ALIGN")
        elif trend_1h_bear and trend_4h_bear:
            score += 3
            reasons.append("1H+4H BEAR ALIGN")
        elif trend_1h_bull:
            score += 1
        elif trend_1h_bear:
            score += 1

        # 15m ENTRY LOGIC
        if rsi15 < 32 and price < float(c15['BB_LOW']) and trend_1h_bull:
            score += 3
            reasons.append(f"15m OVERSOLD RSI {rsi15:.0f}")
        elif rsi15 < 42 and price_above_ema21_15 and trend_4h_bull:
            score += 2
            reasons.append(f"15m BUY DIP RSI {rsi15:.0f}")
        elif rsi15 > 68 and price > float(c15['BB_UP']) and trend_1h_bear:
            score += 3
            reasons.append(f"15m OVERBOUGHT RSI {rsi15:.0f}")
        elif rsi15 > 58 and not price_above_ema21_15 and trend_4h_bear:
            score += 2
            reasons.append(f"15m SELL RALLY RSI {rsi15:.0f}")

        if float(c15['MACD']) > float(c15['MACD_SIGNAL']):
            if trend_4h_bull: score += 1
            reasons.append("15m MACD BULL")
        else:
            if trend_4h_bear: score += 1
            reasons.append("15m MACD BEAR")

        # FINAL DECISION - Triple Confirmation
        if score >= 8 and trend_4h_bull and trend_1h_bull and rsi15 < 50:
            sig = "STRONG BUY"
            emoji = "🟢🟢🟢"
        elif score >= 8 and trend_4h_bear and trend_1h_bear and rsi15 > 50:
            sig = "STRONG SELL"
            emoji = "🔴🔴🔴"
        elif score >= 6 and trend_1h_bull and rsi15 < 48:
            sig = "BUY"
            emoji = "🟢"
        elif score >= 6 and trend_1h_bear and rsi15 > 52:
            sig = "SELL"
            emoji = "🔴"
        else:
            return f"⚪ {name}: WAIT @ {price:.2f} | 15m RSI:{rsi15:.0f} 1H RSI:{rsi1:.0f} | Score:{score}/10 | 4H:{'BULL' if trend_4h_bull else 'BEAR' if trend_4h_bear else 'SIDE'}"

        sl = price - (atr*1.8) if "BUY" in sig else price + (atr*1.8)
        tp1 = price + (atr*2.2) if "BUY" in sig else price - (atr*2.2)
        tp2 = price + (atr*3.8) if "BUY" in sig else price - (atr*3.8)
        rr = abs(tp2-price) / abs(price-sl)

        return (f"{emoji} {name} {sig} @ {price:.2f}\n"
                f"   TF: 15m+1H+4H | Score:{score}/10 | RR:1:{rr:.1f}\n"
                f"   SL:{sl:.2f} TP1:{tp1:.2f} TP2:{tp2:.2f}\n"
                f"   {', '.join(reasons)}")

    except Exception as e:
        return f"⚪ {name}: WAIT - {str(e)[:60]}"

def send(msg):
    if not BOT_TOKEN or not CHAT_ID:
        print(msg)
        return
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=15)
    except Exception as e:
        print(e)

if __name__ == "__main__":
    send("🏦 *TRIPLE TF BOT LIVE*\n15Min + 1H + 4H Institutional Model Active!")
    while True:
        try:
            all_signals = [analyze(n, t) for n, t in SYMBOLS]
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            final = f"🏦 *15m | 1H | 4H - ALL SIGNALS* 🏦\n_{now}_\n\n" + "\n\n".join(all_signals)
            send(final)
            print(f"Sent {now}")
        except Exception as e:
            print(f"Loop Error {e}")
        time.sleep(900) # 15 min loop
