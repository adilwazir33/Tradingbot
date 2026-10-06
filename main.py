import os
import time
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
import numpy as np
import pandas as pd
from flask import Flask
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
# =========================================================
# CONFIG
# =========================================================
TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TWELVE_API_KEY = os.getenv("TWELVE_DATA_API_KEY")
SCAN_INTERVAL = 300  # 5 minutes
SYMBOLS = {
    "XAUUSD.r": {
        "td_symbol": "XAU/USD",
        "name": "GOLD",
    },
    "EURUSD.r": {
        "td_symbol": "EUR/USD",
        "name": "EURUSD.r",
    },
    "BTCUSD.r": {
        "td_symbol": "BTC/USD",
        "name": "BTCUSD.r",
    },
}
TIMEFRAMES = {
    "4H": "4h",
    "1H": "1h",
    "15M": "15min",
}
# Strategy
EMA_FAST = 21
EMA_MID = 50
EMA_SLOW = 200
RSI_PERIOD = 14
ATR_PERIOD = 14
SL_ATR = 1.2
TP1_ATR = 1.5
TP2_ATR = 2.5
TP3_ATR = 3.5
# Sideways threshold
EMA_SIDEWAYS_PCT = 0.05
PRICE_EMA200_SIDEWAYS_PCT = 0.10
DUBAI_TZ = ZoneInfo("Asia/Dubai")
# =========================================================
# FLASK
# =========================================================
flask_app = Flask(__name__)
@flask_app.route("/")
def home():
    return "ADIL PRO FIXED LIVE"
@flask_app.route("/health")
def health():
    return "OK"
def run_flask():
    port = int(os.getenv("PORT", "10000"))
    flask_app.run(host="0.0.0.0", port=port)
# =========================================================
# TELEGRAM
# =========================================================
telegram_app = None
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🟢 ADIL PRO FIXED\n\n"
        "Bot is online and scanning.\n\n"
        "✅ Telegram\n"
        "✅ Twelve Data\n"
        "✅ 4H\n"
        "✅ 1H\n"
        "✅ 15M\n\n"
        "Pairs:\n"
        "🟡 GOLD (XAUUSD.r)\n"
        "💱 EURUSD.r\n"
        "₿ BTCUSD.r\n\n"
        "Commands:\n"
        "/start - bot status\n"
        "/status - system status\n"
        "/test - Telegram test"
    )
    await update.message.reply_text(msg)
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    api_status = "✅ FOUND" if TWELVE_API_KEY else "❌ MISSING"
    chat_status = "✅ CONFIGURED" if CHAT_ID else "❌ MISSING"
    msg = (
        "📊 ADIL PRO FIXED STATUS\n\n"
        f"Twelve Data API: {api_status}\n"
        f"Telegram Chat ID: {chat_status}\n"
        "Timeframes: 4H / 1H / 15M\n"
        "Pairs: GOLD / EURUSD.r / BTCUSD.r\n"
        "Scan: Every 5 minutes\n"
        "Execution: Manual MT5\n"
        "Broker: Lirunex MT5\n"
        "Data: Twelve Data public feed"
    )
    await update.message.reply_text(msg)
async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🟢 ADIL PRO FIXED TEST OK\n"
        "Telegram connection is working."
    )
def send_telegram(message):
    if not TOKEN or not CHAT_ID:
        print("Telegram configuration missing")
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        response = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message,
            },
            timeout=20,
        )
        if response.ok:
            print("Telegram message sent: OK")
            return True
        print("Telegram error:", response.text)
        return False
    except Exception as e:
        print("Telegram exception:", e)
        return False
# =========================================================
# TWELVE DATA
# =========================================================
def get_candles(symbol, interval, outputsize=260):
    if not TWELVE_API_KEY:
        print("Twelve Data API key missing")
        return None
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": TWELVE_API_KEY,
        "format": "JSON",
    }
    try:
        r = requests.get(
            url,
            params=params,
            timeout=30,
        )
        data = r.json()
        if "values" not in data:
            print(
                f"Twelve Data error for {symbol} {interval}:",
                data
            )
            return None
        df = pd.DataFrame(data["values"])
        if df.empty:
            return None
        # Numeric conversion
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(
                    df[col],
                    errors="coerce"
                )
        df["datetime"] = pd.to_datetime(
            df["datetime"],
            errors="coerce"
        )
        df = df.sort_values("datetime").reset_index(drop=True)
        # Remove invalid rows
        df = df.dropna(
            subset=["open", "high", "low", "close"]
        ).reset_index(drop=True)
        return df
    except Exception as e:
        print(
            f"Candle request exception "
            f"{symbol} {interval}: {e}"
        )
        return None
# =========================================================
# INDICATORS
# =========================================================
def calculate_rsi(close, period=14):
    delta = close.diff()
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
    rsi = 100 - (100 / (1 + rs))
    return rsi
def add_indicators(df):
    df = df.copy()
    close = df["close"]
    df["ema21"] = close.ewm(
        span=EMA_FAST,
        adjust=False
    ).mean()
    df["ema50"] = close.ewm(
        span=EMA_MID,
        adjust=False
    ).mean()
    df["ema200"] = close.ewm(
        span=EMA_SLOW,
        adjust=False
    ).mean()
    df["rsi"] = calculate_rsi(
        close,
        RSI_PERIOD
    )
    prev_close = close.shift(1)
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - prev_close).abs()
    tr3 = (df["low"] - prev_close).abs()
    true_range = pd.concat(
        [tr1, tr2, tr3],
        axis=1
    ).max(axis=1)
    df["atr"] = true_range.rolling(
        ATR_PERIOD
    ).mean()
    # Momentum
    df["momentum"] = close.pct_change(5) * 100
    # Volume if available
    if "volume" in df.columns:
        df["volume_ma"] = df["volume"].rolling(20).mean()
    return df
# =========================================================
# PRICE FORMATTING
# =========================================================
def decimals_for(symbol, price):
    if symbol == "BTCUSD.r":
        return 2
    if symbol == "XAUUSD.r":
        return 2
    return 5
def fmt_price(symbol, price):
    if price is None or not np.isfinite(price):
        return "N/A"
    decimals = decimals_for(symbol, price)
    return f"{price:.{decimals}f}"
# =========================================================
# MARKET ANALYSIS
# =========================================================
def analyze_market(df, symbol):
    if df is None or len(df) < 220:
        return {
            "status": "DATA ERROR",
            "side": None,
            "strength": 0,
            "price": None,
        }
    df = add_indicators(df)
    row = df.iloc[-1]
    price = float(row["close"])
    ema21 = float(row["ema21"])
    ema50 = float(row["ema50"])
    ema200 = float(row["ema200"])
    rsi = float(row["rsi"])
    atr = float(row["atr"])
    momentum = float(row["momentum"])
    if not all(
        np.isfinite(x)
        for x in [
            price,
            ema21,
            ema50,
            ema200,
            rsi,
            atr,
            momentum,
        ]
    ):
        return {
            "status": "DATA ERROR",
            "side": None,
            "strength": 0,
            "price": price,
        }
    # -----------------------------------------------------
    # BUY SCORE
    # -----------------------------------------------------
    buy_score = 0
    sell_score = 0
    # EMA 21 / 50
    if ema21 > ema50:
        buy_score += 2
    elif ema21 < ema50:
        sell_score += 2
    # EMA 200
    if price > ema200:
        buy_score += 2
    elif price < ema200:
        sell_score += 2
    # RSI
    if rsi >= 55:
        buy_score += 1
    elif rsi <= 45:
        sell_score += 1
    # Momentum
    if momentum > 0:
        buy_score += 1
    elif momentum < 0:
        sell_score += 1
    # Volume
    if "volume" in df.columns:
        volume = row["volume"]
        volume_ma = row["volume_ma"]
        if (
            pd.notna(volume)
            and pd.notna(volume_ma)
            and volume_ma > 0
            and volume > volume_ma
        ):
            if buy_score >= sell_score:
                buy_score += 1
            else:
                sell_score += 1
    max_score = 7
    # -----------------------------------------------------
    # SIDEWAYS DETECTION
    # -----------------------------------------------------
    ema_spread_pct = (
        abs(ema21 - ema50) / price
    ) * 100
    price_ema200_pct = (
        abs(price - ema200) / price
    ) * 100
    sideways = (
        ema_spread_pct < EMA_SIDEWAYS_PCT
        and price_ema200_pct < PRICE_EMA200_SIDEWAYS_PCT
    )
    # -----------------------------------------------------
    # DIRECTION
    # -----------------------------------------------------
    if buy_score > sell_score:
        side = "BUY"
        score = buy_score
    elif sell_score > buy_score:
        side = "SELL"
        score = sell_score
    else:
        # Tie breaker
        if price >= ema21:
            side = "BUY"
        else:
            side = "SELL"
        score = max(buy_score, sell_score)
    # -----------------------------------------------------
    # STRENGTH
    # -----------------------------------------------------
    strength_map = {
        0: 0,
        1: 1,
        2: 3,
        3: 4,
        4: 6,
        5: 7,
        6: 9,
        7: 10,
    }
    strength = strength_map.get(score, 0)
    # -----------------------------------------------------
    # STATUS
    # -----------------------------------------------------
    if sideways or score <= 2:
        status = "WAIT"
    elif score >= 6:
        status = f"{side} STRONG"
    elif score == 5:
        status = side
    else:
        status = f"{side} WEAK"
    # -----------------------------------------------------
    # ENTRY / SL / TPS
    # -----------------------------------------------------
    entry = price
    if side == "BUY":
        sl = entry - (SL_ATR * atr)
        tp1 = entry + (TP1_ATR * atr)
        tp2 = entry + (TP2_ATR * atr)
        tp3 = entry + (TP3_ATR * atr)
    else:
        sl = entry + (SL_ATR * atr)
        tp1 = entry - (TP1_ATR * atr)
        tp2 = entry - (TP2_ATR * atr)
        tp3 = entry - (TP3_ATR * atr)
    return {
        "status": status,
        "side": side,
        "score": score,
        "strength": strength,
        "price": price,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "atr": atr,
        "rsi": rsi,
        "momentum": momentum,
        "ema_spread_pct": ema_spread_pct,
        "price_ema200_pct": price_ema200_pct,
        "sideways": sideways,
    }
# =========================================================
# SIGNAL TEXT
# =========================================================
def pair_header(symbol, result):
    name = SYMBOLS[symbol]["name"]
    if result["status"] == "WAIT":
        return f"⏳ {name} ({symbol}) — WAIT"
    if result["status"].startswith("BUY"):
        return f"🟢 {name} ({symbol}) — {result['status']}"
    if result["status"].startswith("SELL"):
        return f"🔴 {name} ({symbol}) — {result['status']}"
    return f"⚪ {name} ({symbol}) — {result['status']}"
def format_result(symbol, result):
    header = pair_header(symbol, result)
    price = fmt_price(
        symbol,
        result.get("price")
    )
    # Data error
    if result["status"] == "DATA ERROR":
        return (
            f"⚠️ {header}\n"
            f"Price: {price}\n"
            f"Data unavailable"
        )
    # WAIT / sideways
    if result["status"] == "WAIT":
        sideways_pct = result.get(
            "ema_spread_pct",
            0
        )
        return (
            f"{header}\n"
            f"Price: {price}\n"
            f"Sideways {sideways_pct:.3f}%\n"
            f"Strength: {result['strength']}/10"
        )
    return (
        f"{header}\n"
        f"Price: {price}\n"
        f"Entry: {fmt_price(symbol, result['entry'])}\n"
        f"SL: {fmt_price(symbol, result['sl'])}\n"
        f"TP1: {fmt_price(symbol, result['tp1'])}\n"
        f"TP2: {fmt_price(symbol, result['tp2'])}\n"
        f"TP3: {fmt_price(symbol, result['tp3'])}\n"
        f"Strength: {result['strength']}/10"
    )
# =========================================================
# SCAN
# =========================================================
def scan_all_markets():
    results = {}
    for tf_name, td_interval in TIMEFRAMES.items():
        results[tf_name] = {}
        for symbol, info in SYMBOLS.items():
            print(
                f"Scanning {symbol} "
                f"{tf_name}..."
            )
            df = get_candles(
                info["td_symbol"],
                td_interval,
                outputsize=260
            )
            result = analyze_market(
                df,
                symbol
            )
            results[tf_name][symbol] = result
            # Small delay to reduce API burst/rate-limit risk
            time.sleep(3)
    return results
# =========================================================
# MESSAGE BUILDER
# =========================================================
def build_message(results):
    now = datetime.now(DUBAI_TZ)
    timestamp = now.strftime(
        "%d-%m %I:%M %p"
    )
    lines = [
        "💰 ADIL PRO FIXED",
        f"🕐 {timestamp} Dubai",
        "",
        "📊 Data: Twelve Data public feed",
        "🏦 Broker: Lirunex MT5",
        "⚙️ Execution: Manual",
        "⚠️ Public feed price may differ from Lirunex MT5",
        "",
    ]
    for tf_name in ["4H", "1H", "15M"]:
        lines.append(
            f"===== {tf_name} ====="
        )
        for symbol in SYMBOLS:
            result = results.get(
                tf_name,
                {}
            ).get(
                symbol
            )
            if result is None:
                result = {
                    "status": "DATA ERROR",
                    "price": None,
                    "strength": 0,
                }
            lines.append(
                format_result(
                    symbol,
                    result
                )
            )
            lines.append("")
    lines.extend([
        "━━━━━━━━━━━━━━",
        "⚠️ Signal = technical analysis only",
        "No profit guarantee.",
        "Use Lirunex MT5 for actual execution."
    ])
    return "\n".join(lines)
# =========================================================
# BACKGROUND SCANNER
# =========================================================
def scanner_loop():
    print("ADIL PRO FIXED SCANNER STARTED")
    while True:
        try:
            print("Starting market scan...")
            results = scan_all_markets()
            message = build_message(results)
            print(message)
            send_telegram(message)
        except Exception as e:
            print(
                "Scanner error:",
                repr(e)
            )
        print(
            f"Waiting {SCAN_INTERVAL} seconds..."
        )
        time.sleep(SCAN_INTERVAL)
# =========================================================
# TELEGRAM STARTUP
# =========================================================
def start_telegram():
    global telegram_app
    if not TOKEN:
        print("BOT_TOKEN missing")
        return
    if not CHAT_ID:
        print("CHAT_ID missing")
        return
    telegram_app = (
        Application.builder()
        .token(TOKEN)
        .build()
    )
    telegram_app.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )
    telegram_app.add_handler(
        CommandHandler(
            "status",
            status_command
        )
    )
    telegram_app.add_handler(
        CommandHandler(
            "test",
            test_command
        )
    )
    print("Telegram bot starting...")
    # Send startup message
    send_telegram(
        "🟢 ADIL PRO FIXED\n"
        "Bot is LIVE.\n\n"
        "✅ Telegram\n"
        "✅ Twelve Data\n"
        "✅ 4H\n"
        "✅ 1H\n"
        "✅ 15M\n"
        "✅ GOLD\n"
        "✅ EURUSD.r\n"
        "✅ BTCUSD.r\n\n"
        "📊 Scanning every 5 minutes."
    )
    telegram_app.run_polling(
        drop_pending_updates=True
    )
# =========================================================
# MAIN
# =========================================================
if __name__ == "__main__":
    print("================================")
    print("ADIL PRO FIXED")
    print("================================")
    print(
        "Symbols:",
        list(SYMBOLS.keys())
    )
    print(
        "Twelve Data:",
        "API KEY FOUND"
        if TWELVE_API_KEY
        else "API KEY MISSING"
    )
    print(
        "Telegram Chat ID:",
        "CONFIGURED"
        if CHAT_ID
        else "MISSING"
    )
    # Flask in background
    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )
    flask_thread.start()
    # Scanner in background
    scanner_thread = threading.Thread(
        target=scanner_loop,
        daemon=True
    )
    scanner_thread.start()
    # Telegram polling in main thread
    start_telegram()

Is code mein hard-coded BTC/GOLD/EURUSD price nahi hai — har scan Twelve Data se candles leta hai aur usi actual returned price par calculation karta hai.

Ek important point: 9 candle requests har 5 minutes hain (3 pairs × 3 timeframes), isliye code requests ke darmiyan delay rakhta hai taake Twelve Data rate-limit ka chance kam ho. Render par purana main.py replace karke redeploy kar dena.
