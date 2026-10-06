import os
import threading
import time
import requests
import pandas as pd
import numpy as np
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# =========================================================
# CONFIG
# =========================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")

SYMBOLS = {
    "XAUUSD.r": {"name": "GOLD", "td": "XAU/USD"},
    "EURUSD.r": {"name": "EURUSD", "td": "EUR/USD"},
    "BTCUSD.r": {"name": "BTC", "td": "BTC/USD"},
}

flask_app = Flask(__name__)

# =========================================================
# FLASK
# =========================================================
@flask_app.route("/")
def home():
    return "ADIL PRO MARKET MOOD v15.1 LIVE"

@flask_app.route("/health")
def health():
    return {
        "status": "online",
        "telegram": bool(BOT_TOKEN),
        "twelve_data": bool(TWELVE_DATA_API_KEY),
    }

# =========================================================
# HELPERS
# =========================================================
def fmt_price(symbol, price):
    try:
        price = float(price)
        if "XAU" in symbol or "BTC" in symbol:
            return f"{price:.2f}"
        return f"{price:.5f}"
    except:
        return "N/A"

def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    value = 100 - (100 / (1 + rs))
    return value.fillna(50)

def atr(df, period=14):
    high_low = df["high"] - df["low"]
    high_close = abs(df["high"] - df["close"].shift())
    low_close = abs(df["low"] - df["close"].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=20)
        return r.status_code == 200
    except:
        return False

# =========================================================
# DATA
# =========================================================
def get_data(symbol, interval, outputsize=250):
    if not TWELVE_DATA_API_KEY or symbol not in SYMBOLS:
        return None
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": SYMBOLS[symbol]["td"],
        "interval": interval,
        "outputsize": outputsize,
        "apikey": TWELVE_DATA_API_KEY,
        "format": "JSON",
    }
    try:
        data = requests.get(url, params=params, timeout=30).json()
        if "values" not in data:
            print(f"DATA ERROR {symbol} {interval}: {data}")
            return None
        df = pd.DataFrame(data["values"])
        df["datetime"] = pd.to_datetime(df["datetime"])
        for col in ["open","high","low","close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna().sort_values("datetime").reset_index(drop=True)
        # Remove forming candle
        if len(df) > 2:
            df = df.iloc[:-1].copy()
        return df
    except Exception as e:
        print(f"DATA EXCEPTION {symbol} {interval}: {e}")
        return None

# =========================================================
# ANALYSIS
# =========================================================
def analyze_trend(df):
    if df is None or len(df) < 210:
        return "WAIT", "NOT_ENOUGH_DATA"
    df = df.copy()
    df["ema50"] = ema(df["close"], 50)
    df["ema200"] = ema(df["close"], 200)
    last = df.iloc[-1]
    if last["close"] > last["ema200"] and last["ema50"] > last["ema200"]:
        return "BUY", "BULLISH TREND"
    if last["close"] < last["ema200"] and last["ema50"] < last["ema200"]:
        return "SELL", "BEARISH TREND"
    return "WAIT", "NO CLEAR TREND"

def analyze_momentum(df):
    if df is None or len(df) < 60:
        return "WAIT", "NOT_ENOUGH_DATA"
    df = df.copy()
    df["ema50"] = ema(df["close"], 50)
    df["ema200"] = ema(df["close"], 200)
    df["rsi"] = rsi(df["close"])
    last = df.iloc[-1]
    if last["close"] > last["ema50"] and last["ema50"] > last["ema200"] and 50 <= last["rsi"] <= 70:
        return "BUY", "BULLISH MOMENTUM"
    if last["close"] < last["ema50"] and last["ema50"] < last["ema200"] and 30 <= last["rsi"] <= 50:
        return "SELL", "BEARISH MOMENTUM"
    return "WAIT", "NO ENTRY"

def generate_signal(symbol):
    df4h = get_data(symbol, "4h", 250)
    if df4h is None: return {"signal":"WAIT","reason":"DATA_ERROR"}
    trend, trend_reason = analyze_trend(df4h)
    if trend == "WAIT": return {"signal":"WAIT","reason":trend_reason}

    df15 = get_data(symbol, "15min", 250)
    if df15 is None: return {"signal":"WAIT","reason":"15M_DATA_ERROR"}

    momentum, momentum_reason = analyze_momentum(df15)
    if momentum!= trend:
        return {"signal":"WAIT","reason":"TIMEFRAME_CONFLICT"}

    last = df15.iloc[-1]
    atr_val = atr(df15).iloc[-1]
    if not np.isfinite(atr_val) or atr_val <= 0:
        return {"signal":"WAIT","reason":"ATR_ERROR"}

    entry = float(last["close"])
    if trend == "BUY":
        sl = entry - 1.2*atr_val
        risk = entry - sl
        tp1, tp2, tp3 = entry+risk, entry+2*risk, entry+3*risk
    else:
        sl = entry + 1.2*atr_val
        risk = sl - entry
        tp1, tp2, tp3 = entry-risk, entry-2*risk, entry-3*risk

    return {"signal":trend,"reason":"4H TREND + 15M MOMENTUM","entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"candle":str(last["datetime"])}

# =========================================================
# FORMAT
# =========================================================
def format_signal(symbol):
    result = generate_signal(symbol)
    name = SYMBOLS[symbol]["name"]
    if result["signal"] == "WAIT":
        return f"⚪ {name} | WAIT | {result['reason']}"
    return (
        f"{'🟢' if result['signal']=='BUY' else '🔴'} {result['signal']} {name}\n"
        f"Entry: {fmt_price(symbol, result['entry'])}\n"
        f"SL: {fmt_price(symbol, result['sl'])}\n"
        f"TP1: {fmt_price(symbol, result['tp1'])} | TP2: {fmt_price(symbol, result['tp2'])} | TP3: {fmt_price(symbol, result['tp3'])}\n"
        f"Reason: {result['reason']}"
    )

# =========================================================
# TELEGRAM COMMANDS
# =========================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🟢 ADIL PRO v15.1\nChat ID: {update.effective_chat.id}\n\n/market /signal /status /test"
    )

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"✅ OK | Chat ID: {update.effective_chat.id}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🟢 ONLINE\nStrategy: 4H Trend + 15M Momentum\nRisk: 0.5-1%")

async def market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["📊 PRO MARKET CHECK","━━━━━━━━━━"]
    for s in SYMBOLS:
        r = generate_signal(s)
        icon = "🟢" if r["signal"]=="BUY" else "🔴" if r["signal"]=="SELL" else "⚪"
        lines.append(f"{icon} {SYMBOLS[s]['name']}: {r['signal']} | {r['reason']}")
        time.sleep(1)
    await update.message.reply_text("\n".join(lines))

async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msgs = [format_signal(s) for s in SYMBOLS]
    await update.message.reply_text("\n\n".join(msgs))

# =========================================================
# BOT + SCANNER
# =========================================================
sent = set()
def scanner_loop():
    print("Scanner started - only BUY/SELL will be pushed")
    while True:
        try:
            for sym in SYMBOLS:
                res = generate_signal(sym)
                if res["signal"] in ("BUY","SELL"):
                    key = (sym, res["signal"], res.get("candle"))
                    if key not in sent:
                        send_telegram(format_signal(sym))
                        sent.add(key)
                time.sleep(3)
        except Exception as e:
            print(f"SCANNER ERROR: {e}")
        time.sleep(300)

def run_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("market", market))
    app.add_handler(CommandHandler("mood", market))
    app.add_handler(CommandHandler("signal", signal))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    threading.Thread(target=scanner_loop, daemon=True).start()
    threading.Thread(target=run_bot, daemon=True).start()
    flask_app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
