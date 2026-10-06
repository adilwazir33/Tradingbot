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
from telegram.ext import Application, CommandHandler, ContextTypes
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
EMA_FAST = 21
EMA_MID = 50
EMA_SLOW = 200
RSI_PERIOD = 14
ATR_PERIOD = 14
SL_ATR = 1.2
TP1_ATR = 1.5
TP2_ATR = 2.5
TP3_ATR = 3.5
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
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
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
        "/start - bot status\n"
        "/status - system status\n"
        "/test - Telegram test"
    )
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📊 ADIL PRO FIXED STATUS\n\n"
        f"Twelve Data: "
        f"{'✅ OK' if TWELVE_API_KEY else '❌ MISSING'}\n"
        f"Telegram: "
        f"{'✅ OK' if CHAT_ID else '❌ MISSING'}\n"
        "Timeframes: 4H / 1H / 15M\n"
        "Pairs: GOLD / EURUSD.r / BTCUSD.r\n"
        "Scan: Every 5 minutes\n"
        "Broker: Lirunex MT5\n"
        "Execution: Manual"
    )
async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🟢 ADIL PRO FIXED TEST OK"
    )
def start_telegram():
    if not TOKEN:
        print("BOT_TOKEN missing")
        return
    app = (
        Application.builder()
        .token(TOKEN)
        .build()
    )
    app.add_handler(
        CommandHandler("start", start_command)
    )
    app.add_handler(
        CommandHandler("status", status_command)
    )
    app.add_handler(
        CommandHandler("test", test_command)
    )
    print("Telegram polling started")
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
        "📊 Scan every 5 minutes."
    )
    app.run_polling(
        drop_pending_updates=True
    )
# =========================================================
# TWELVE DATA
# =========================================================
def get_candles(symbol, interval, outputsize=260):
    if not TWELVE_API_KEY:
        print("TWELVE_DATA_API_KEY missing")
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
            timeout=30
        )
        data = r.json()
        if "values" not in data:
            print(
                "Twelve Data error:",
                symbol,
                interval,
                data
            )
            return None
        df = pd.DataFrame(data["values"])
        if df.empty:
            return None
        for column in [
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]:
            if column in df.columns:
                df[column] = pd.to_numeric(
                    df[column],
                    errors="coerce"
                )
        df["datetime"] = pd.to_datetime(
            df["datetime"],
            errors="coerce"
        )
        df = df.sort_values(
            "datetime"
        ).reset_index(drop=True)
        df = df.dropna(
            subset=[
                "open",
                "high",
                "low",
                "close"
            ]
        ).reset_index(drop=True)
        return df
    except Exception as e:
        print(
            "Twelve Data exception:",
            symbol,
            interval,
            e
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
        adjust=False
    ).mean()
    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()
    rs = avg_gain / avg_loss.replace(
        0,
        np.nan
    )
    return 100 - (
        100 / (1 + rs)
    )
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
    previous_close = close.shift(1)
    tr1 = df["high"] - df["low"]
    tr2 = (
        df["high"] - previous_close
    ).abs()
    tr3 = (
        df["low"] - previous_close
    ).abs()
    true_range = pd.concat(
        [tr1, tr2, tr3],
        axis=1
    ).max(axis=1)
    df["atr"] = true_range.rolling(
        ATR_PERIOD
    ).mean()
    df["momentum"] = (
        close.pct_change(5) * 100
    )
    if "volume" in df.columns:
        df["volume_ma"] = (
            df["volume"].rolling(20).mean()
        )
    return df
# =========================================================
# PRICE FORMAT
# =========================================================
def format_price(symbol, value):
    if value is None:
        return "N/A"
    try:
        value = float(value)
    except Exception:
        return "N/A"
    if not np.isfinite(value):
        return "N/A"
    if symbol == "EURUSD.r":
        return f"{value:.5f}"
    return f"{value:.2f}"
# =========================================================
# MARKET ANALYSIS
# =========================================================
def analyze_market(df, symbol):
    if df is None or len(df) < 220:
        return {
            "status": "DATA ERROR",
            "price": None,
            "strength": 0,
        }
    df = add_indicators(df)
    row = df.iloc[-1]
    try:
        price = float(row["close"])
        ema21 = float(row["ema21"])
        ema50 = float(row["ema50"])
        ema200 = float(row["ema200"])
        rsi = float(row["rsi"])
        atr = float(row["atr"])
        momentum = float(row["momentum"])
    except Exception:
        return {
            "status": "DATA ERROR",
            "price": None,
            "strength": 0,
        }
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
            "price": price,
            "strength": 0,
        }
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
        volume = row.get("volume")
        volume_ma = row.get("volume_ma")
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
    score = max(
        buy_score,
        sell_score
    )
    # Direction
    if buy_score > sell_score:
        side = "BUY"
    elif sell_score > buy_score:
        side = "SELL"
    else:
        side = (
            "BUY"
            if price >= ema21
            else "SELL"
        )
    # Sideways
    ema_spread_pct = (
        abs(ema21 - ema50)
        / price
        * 100
    )
    price_ema200_pct = (
        abs(price - ema200)
        / price
        * 100
    )
    sideways = (
        ema_spread_pct < 0.05
        and price_ema200_pct < 0.10
    )
    # Strength
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
    strength = strength_map.get(
        score,
        0
    )
    # Status
    if sideways or score <= 2:
        status = "WAIT"
    elif score >= 6:
        status = f"{side} STRONG"
    elif score == 5:
        status = side
    else:
        status = f"{side} WEAK"
    # Entry / SL / TP
    entry = price
    if side == "BUY":
        sl = entry - (
            SL_ATR * atr
        )
        tp1 = entry + (
            TP1_ATR * atr
        )
        tp2 = entry + (
            TP2_ATR * atr
        )
        tp3 = entry + (
            TP3_ATR * atr
        )
    else:
        sl = entry + (
            SL_ATR * atr
        )
        tp1 = entry - (
            TP1_ATR * atr
        )
        tp2 = entry - (
            TP2_ATR * atr
        )
        tp3 = entry - (
            TP3_ATR * atr
        )
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
        "sideways_pct": ema_spread_pct,
    }
# =========================================================
# RESULT FORMAT
# =========================================================
def format_result(symbol, result):
    name = SYMBOLS[symbol]["name"]
    status = result.get(
        "status",
        "DATA ERROR"
    )
    price = format_price(
        symbol,
        result.get("price")
    )
    if status == "WAIT":
        sideways_pct = result.get(
            "sideways_pct",
            0
        )
        return (
            f"⏳ {name} ({symbol}) — WAIT\n"
            f"Price: {price}\n"
            f"Sideways {sideways_pct:.3f}%\n"
            f"Strength: "
            f"{result.get('strength', 0)}/10"
        )
    if status == "DATA ERROR":
        return (
            f"⚠️ {name} ({symbol}) — DATA ERROR\n"
            f"Price: {price}"
        )
    if status.startswith("BUY"):
        icon = "🟢"
    elif status.startswith("SELL"):
        icon = "🔴"
    else:
        icon = "⚪"
    return (
        f"{icon} {name} ({symbol}) — {status}\n"
        f"Price: {price}\n"
        f"Entry: "
        f"{format_price(symbol, result['entry'])}\n"
        f"SL: "
        f"{format_price(symbol, result['sl'])}\n"
        f"TP1: "
        f"{format_price(symbol, result['tp1'])}\n"
        f"TP2: "
        f"{format_price(symbol, result['tp2'])}\n"
        f"TP3: "
        f"{format_price(symbol, result['tp3'])}\n"
        f"Strength: "
        f"{result['strength']}/10"
    )
# =========================================================
# SCAN
# =========================================================
def scan_markets():
    all_results = {}
    for timeframe, interval in TIMEFRAMES.items():
        print(
            f"===== SCANNING {timeframe} ====="
        )
        all_results[timeframe] = {}
        for symbol, info in SYMBOLS.items():
            print(
                f"Fetching {symbol} "
                f"{timeframe}"
            )
            df = get_candles(
                info["td_symbol"],
                interval,
                260
            )
            result = analyze_market(
                df,
                symbol
            )
            all_results[
                timeframe
            ][symbol] = result
            # Prevent API burst
            time.sleep(3)
    return all_results
# =========================================================
# TELEGRAM MESSAGE
# =========================================================
def build_message(results):
    now = datetime.now(
        DUBAI_TZ
    )
    timestamp = now.strftime(
        "%d-%m %I:%M %p"
    )
    message = (
        "💰 ADIL PRO FIXED\n"
        f"🕐 {timestamp} Dubai\n\n"
        "📊 Data: Twelve Data public feed\n"
        "🏦 Broker: Lirunex MT5\n"
        "⚙️ Execution: Manual\n"
        "⚠️ Public feed price may differ "
        "from Lirunex MT5\n\n"
    )
    for timeframe in [
        "4H",
        "1H",
        "15M"
    ]:
        message += (
            f"===== {timeframe} =====\n"
        )
        for symbol in SYMBOLS:
            result = results.get(
                timeframe,
                {}
            ).get(
                symbol,
                {
                    "status": "DATA ERROR",
                    "price": None,
                    "strength": 0,
                }
            )
            message += (
                format_result(
                    symbol,
                    result
                )
                + "\n\n"
            )
    message += (
        "━━━━━━━━━━━━━━\n"
        "⚠️ Technical signal only.\n"
        "No profit guarantee."
    )
    return message
# =========================================================
# BACKGROUND SCANNER
# =========================================================
def scanner_loop():
    print(
        "ADIL PRO FIXED SCANNER STARTED"
    )
    while True:
        try:
            print(
                "Starting new market scan..."
            )
            results = scan_markets()
            message = build_message(
                results
            )
            print(message)
            send_telegram(message)
        except Exception as e:
            print(
                "Scanner error:",
                repr(e)
            )
        print(
            f"Next scan in "
            f"{SCAN_INTERVAL} seconds"
        )
        time.sleep(
            SCAN_INTERVAL
        )
# =========================================================
# MAIN
# =========================================================
if __name__ == "__main__":
    print("==============================")
    print("ADIL PRO FIXED")
    print("==============================")
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
        "Telegram:",
        "CONFIGURED"
        if CHAT_ID
        else "CHAT ID MISSING"
    )
    # Flask
    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )
    flask_thread.start()
    # Scanner
    scanner_thread = threading.Thread(
        target=scanner_loop,
        daemon=True
    )
    scanner_thread.start()
    # Telegram
    start_telegram()
