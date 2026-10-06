import os
import time
import requests
import pandas as pd
import numpy as np
from flask import Flask
from threading import Thread
# ============================================================
# CONFIG
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")
SYMBOLS = {
    "XAUUSD.r": "XAU/USD",
    "EURUSD.r": "EUR/USD",
    "BTCUSD.r": "BTC/USD",
}
INTERVALS = {
    "M15": "15min",
    "H1": "1h",
    "H4": "4h",
}
MIN_SCORE = 8
COOLDOWN_MINUTES = 45
SL_ATR = 1.20
TP1_ATR = 1.50
TP2_ATR = 2.50
API_URL = "https://api.twelvedata.com/time_series"
app = Flask(__name__)
last_signal = {}
# ============================================================
# HEALTH
# ============================================================
@app.route("/")
def home():
    return "ADIL 3-SYMBOL SIGNAL BOT LIVE"
def flask_server():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
# ============================================================
# TELEGRAM
# ============================================================
def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("ERROR: BOT_TOKEN or CHAT_ID missing")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        response = requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
            },
            timeout=20,
        )
        print("Telegram:", response.status_code)
        return response.ok
    except Exception as e:
        print("Telegram error:", e)
        return False
# ============================================================
# TWELVE DATA
# ============================================================
def get_market_data(symbol, interval):
    if not TWELVE_DATA_API_KEY:
        print("ERROR: TWELVE_DATA_API_KEY missing")
        return None
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": 300,
        "apikey": TWELVE_DATA_API_KEY,
        "format": "JSON",
    }
    try:
        response = requests.get(
            API_URL,
            params=params,
            timeout=20,
        )
        data = response.json()
        if "status" in data and data["status"] == "error":
            print(
                f"DATA ERROR {symbol} {interval}:",
                data.get("message")
            )
            return None
        values = data.get("values")
        if not values:
            print(f"No data: {symbol} {interval}")
            return None
        df = pd.DataFrame(values)
        required = [
            "datetime",
            "open",
            "high",
            "low",
            "close",
        ]
        for column in required:
            if column not in df.columns:
                print(f"Missing {column}: {symbol}")
                return None
        df["time"] = pd.to_datetime(df["datetime"])
        for column in [
            "open",
            "high",
            "low",
            "close",
        ]:
            df[column] = pd.to_numeric(
                df[column],
                errors="coerce"
            )
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(
                df["volume"],
                errors="coerce"
            )
        else:
            # Forex/gold feeds may not provide volume.
            df["volume"] = 0.0
        df = df.dropna(
            subset=[
                "open",
                "high",
                "low",
                "close",
            ]
        )
        # Twelve Data commonly returns newest first.
        df = df.sort_values("time").reset_index(drop=True)
        return df
    except Exception as e:
        print(
            f"Market data error {symbol} {interval}:",
            e
        )
        return None
# ============================================================
# INDICATORS
# ============================================================
def ema(series, period):
    return series.ewm(
        span=period,
        adjust=False
    ).mean()
def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False
    ).mean()
    avg_loss = loss.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False
    ).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (
        100 / (1 + rs)
    )
def atr(df, period=14):
    high_low = df["high"] - df["low"]
    high_close = (
        df["high"] - df["close"].shift()
    ).abs()
    low_close = (
        df["low"] - df["close"].shift()
    ).abs()
    true_range = pd.concat(
        [
            high_low,
            high_close,
            low_close
        ],
        axis=1
    ).max(axis=1)
    return true_range.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False
    ).mean()
# ============================================================
# TIMEFRAME ANALYSIS
# ============================================================
def analyze(df):
    if df is None or len(df) < 220:
        return None
    df = df.copy()
    df["ema21"] = ema(df["close"], 21)
    df["ema50"] = ema(df["close"], 50)
    df["ema200"] = ema(df["close"], 200)
    df["rsi"] = rsi(df["close"], 14)
    df["atr"] = atr(df, 14)
    df["volume_avg"] = (
        df["volume"]
        .rolling(20)
        .mean()
    )
    # Last closed candle
    row = df.iloc[-2]
    previous = df.iloc[-3]
    buy = 0
    sell = 0
    # EMA trend
    if row["ema21"] > row["ema50"]:
        buy += 2
    elif row["ema21"] < row["ema50"]:
        sell += 2
    # Long-term trend
    if row["close"] > row["ema200"]:
        buy += 2
    elif row["close"] < row["ema200"]:
        sell += 2
    # RSI
    if 52 <= row["rsi"] <= 68:
        buy += 1
    elif 32 <= row["rsi"] <= 48:
        sell += 1
    # Momentum
    if row["close"] > previous["close"]:
        buy += 1
    elif row["close"] < previous["close"]:
        sell += 1
    # Volume only when actual volume exists
    if row["volume"] > 0 and row["volume_avg"] > 0:
        if row["volume"] > row["volume_avg"]:
            if row["close"] > previous["close"]:
                buy += 1
            elif row["close"] < previous["close"]:
                sell += 1
    # Require strong directional setup
    if buy >= MIN_SCORE and buy > sell:
        return {
            "side": "BUY",
            "score": buy,
            "price": float(row["close"]),
            "atr": float(row["atr"]),
        }
    if sell >= MIN_SCORE and sell > buy:
        return {
            "side": "SELL",
            "score": sell,
            "price": float(row["close"]),
            "atr": float(row["atr"]),
        }
    return None
# ============================================================
# MULTI-TIMEFRAME SIGNAL
# ============================================================
def build_signal(display_symbol):
    api_symbol = SYMBOLS[display_symbol]
    frames = {}
    for name, interval in INTERVALS.items():
        df = get_market_data(
            api_symbol,
            interval
        )
        if df is None:
            return None
        frames[name] = df
    m15 = analyze(frames["M15"])
    h1 = analyze(frames["H1"])
    h4 = analyze(frames["H4"])
    if not m15 or not h1 or not h4:
        return None
    # STRICT:
    # M15 + H1 + H4 must agree.
    if not (
        m15["side"]
        == h1["side"]
        == h4["side"]
    ):
        return None
    side = m15["side"]
    entry = m15["price"]
    atr_value = m15["atr"]
    if not np.isfinite(atr_value) or atr_value <= 0:
        return None
    if side == "BUY":
        sl = entry - (
            SL_ATR * atr_value
        )
        tp1 = entry + (
            TP1_ATR * atr_value
        )
        tp2 = entry + (
            TP2_ATR * atr_value
        )
    else:
        sl = entry + (
            SL_ATR * atr_value
        )
        tp1 = entry - (
            TP1_ATR * atr_value
        )
        tp2 = entry - (
            TP2_ATR * atr_value
        )
    return {
        "symbol": display_symbol,
        "side": side,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "score": m15["score"],
    }
# ============================================================
# COOLDOWN
# ============================================================
def signal_allowed(symbol, side):
    key = f"{symbol}:{side}"
    now = time.time()
    old = last_signal.get(key, 0)
    if (
        now - old
        < COOLDOWN_MINUTES * 60
    ):
        return False
    last_signal[key] = now
    return True
# ============================================================
# DECIMAL FORMATTING
# ============================================================
def price_text(symbol, value):
    if symbol == "BTCUSD.r":
        return f"{value:.2f}"
    if symbol == "XAUUSD.r":
        return f"{value:.2f}"
    return f"{value:.5f}"
# ============================================================
# TELEGRAM MESSAGE
# ============================================================
def signal_message(signal):
    symbol = signal["symbol"]
    if signal["side"] == "BUY":
        emoji = "🟢"
    else:
        emoji = "🔴"
    return f"""
<b>{emoji} ADIL MTF SIGNAL</b>
<b>Symbol:</b> {symbol}
<b>Direction:</b> {signal["side"]}
<b>Entry:</b> {price_text(symbol, signal["entry"])}
<b>SL:</b> {price_text(symbol, signal["sl"])}
<b>TP1:</b> {price_text(symbol, signal["tp1"])}
<b>TP2:</b> {price_text(symbol, signal["tp2"])}
<b>M15:</b> ✅
<b>H1:</b> ✅
<b>H4:</b> ✅
<b>Score:</b> {signal["score"]}
<b>Data:</b> Twelve Data public feed
<b>Broker:</b> Lirunex MT5
<b>Execution:</b> Manual
⚠️ Public-feed price may differ from Lirunex MT5.
"""
# ============================================================
# SCANNER
# ============================================================
def scanner():
    print(
        "ADIL SIGNAL BOT STARTED"
    )
    print(
        "Symbols:",
        list(SYMBOLS.keys())
    )
    while True:
        for symbol in SYMBOLS:
            try:
                signal = build_signal(symbol)
                if not signal:
                    continue
                if not signal_allowed(
                    signal["symbol"],
                    signal["side"]
                ):
                    continue
                message = signal_message(
                    signal
                )
                send_telegram(message)
                time.sleep(2)
            except Exception as e:
                print(
                    f"Scanner error {symbol}:",
                    e
                )
        # Scan once per minute
        time.sleep(60)
# ============================================================
# START
# ============================================================
if __name__ == "__main__":
    Thread(
        target=flask_server,
        daemon=True
    ).start()
    scanner()
