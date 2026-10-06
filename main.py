import os
import time
import threading
import asyncio
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
    MessageHandler,
    ContextTypes,
    filters,
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
        "icon": "🥇",
    },
    "EURUSD.r": {
        "td_symbol": "EUR/USD",
        "name": "EUR",
        "icon": "💱",
    },
    "BTCUSD.r": {
        "td_symbol": "BTC/USD",
        "name": "BTC",
        "icon": "₿",
    },
}
TIMEFRAMES = {
    "15M": "15min",
    "1H": "1h",
    "4H": "4h",
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
    return "ADIL PRO MARKET MOOD LIVE"
@flask_app.route("/health")
def health():
    return "OK"
def run_flask():
    port = int(os.getenv("PORT", "10000"))
    flask_app.run(
        host="0.0.0.0",
        port=port,
    )
# =========================================================
# TELEGRAM SEND
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
        print("Telegram exception:", repr(e))
        return False
# =========================================================
# TELEGRAM COMMANDS
# =========================================================
async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "🟢 ADIL PRO MARKET MOOD\n\n"
        "Bot is online.\n\n"
        "📊 Fresh market check:\n"
        "Type: market\n"
        "or: mood\n"
        "or: signal\n\n"
        "Pairs:\n"
        "🥇 GOLD (XAUUSD.r)\n"
        "💱 EURUSD.r\n"
        "₿ BTCUSD.r\n\n"
        "Timeframes:\n"
        "15M / 1H / 4H\n\n"
        "/start - Bot status\n"
        "/status - System status\n"
        "/test - Telegram test"
    )
async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "📊 ADIL PRO MARKET MOOD STATUS\n\n"
        f"Twelve Data: "
        f"{'✅ OK' if TWELVE_API_KEY else '❌ MISSING'}\n"
        f"Telegram: "
        f"{'✅ OK' if CHAT_ID else '❌ MISSING'}\n\n"
        "Timeframes: 15M / 1H / 4H\n"
        "Pairs: GOLD / EUR / BTC\n"
        "Auto Scan: Every 5 minutes\n"
        "Manual Scan: market / mood / signal\n\n"
        "🏦 Broker: Lirunex MT5\n"
        "⚙️ Execution: Manual"
    )
async def test_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "🟢 ADIL PRO MARKET MOOD TEST OK"
    )
# =========================================================
# MANUAL MARKET MESSAGE
# =========================================================
async def market_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip().lower()
    commands = {
        "market",
        "mood",
        "signal",
        "market mood",
    }
    if text not in commands:
        return
    await update.message.reply_text(
        "⏳ Fresh market data check kar raha hoon...\n"
        "15M + 1H + 4H\n"
        "BTC + GOLD + EUR"
    )
    try:
        # Run blocking API work outside Telegram event loop
        results = await asyncio.to_thread(
            scan_markets
        )
        message = build_message(
            results,
            manual=True
        )
        await update.message.reply_text(
            message
        )
    except Exception as e:
        print(
            "Manual market error:",
            repr(e)
        )
        await update.message.reply_text(
            "❌ Market data error.\n\n"
            "Please try again."
        )
# =========================================================
# TELEGRAM START
# =========================================================
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
        CommandHandler(
            "start",
            start_command
        )
    )
    app.add_handler(
        CommandHandler(
            "status",
            status_command
        )
    )
    app.add_handler(
        CommandHandler(
            "test",
            test_command
        )
    )
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            market_message
        )
    )
    print(
        "Telegram polling started"
    )
    send_telegram(
        "🟢 ADIL PRO MARKET MOOD\n\n"
        "Bot is LIVE.\n\n"
        "✅ Telegram\n"
        "✅ Twelve Data\n"
        "✅ 15M\n"
        "✅ 1H\n"
        "✅ 4H\n"
        "✅ GOLD\n"
        "✅ EUR\n"
        "✅ BTC\n\n"
        "📩 Type 'market' for a fresh market mood."
    )
    app.run_polling(
        drop_pending_updates=True
    )
# =========================================================
# TWELVE DATA
# =========================================================
def get_candles(
    symbol,
    interval,
    outputsize=260,
):
    if not TWELVE_API_KEY:
        print(
            "TWELVE_DATA_API_KEY missing"
        )
        return None
    url = (
        "https://api.twelvedata.com/time_series"
    )
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": TWELVE_API_KEY,
        "format": "JSON",
    }
    try:
        response = requests.get(
            url,
            params=params,
            timeout=30,
        )
        data = response.json()
        if "values" not in data:
            print(
                "Twelve Data error:",
                symbol,
                interval,
                data,
            )
            return None
        df = pd.DataFrame(
            data["values"]
        )
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
                    errors="coerce",
                )
        df["datetime"] = pd.to_datetime(
            df["datetime"],
            errors="coerce",
        )
        df = df.sort_values(
            "datetime"
        ).reset_index(
            drop=True
        )
        df = df.dropna(
            subset=[
                "open",
                "high",
                "low",
                "close",
            ]
        ).reset_index(
            drop=True
        )
        return df
    except Exception as e:
        print(
            "Twelve Data exception:",
            symbol,
            interval,
            repr(e),
        )
        return None
# =========================================================
# INDICATORS
# =========================================================
def calculate_rsi(
    close,
    period=14,
):
    delta = close.diff()
    gain = delta.clip(
        lower=0
    )
    loss = -delta.clip(
        upper=0
    )
    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False,
    ).mean()
    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False,
    ).mean()
    rs = (
        avg_gain
        / avg_loss.replace(
            0,
            np.nan,
        )
    )
    return 100 - (
        100 / (1 + rs)
    )
def add_indicators(df):
    df = df.copy()
    close = df["close"]
    df["ema21"] = close.ewm(
        span=EMA_FAST,
        adjust=False,
    ).mean()
    df["ema50"] = close.ewm(
        span=EMA_MID,
        adjust=False,
    ).mean()
    df["ema200"] = close.ewm(
        span=EMA_SLOW,
        adjust=False,
    ).mean()
    df["rsi"] = calculate_rsi(
        close,
        RSI_PERIOD,
    )
    previous_close = close.shift(1)
    tr1 = (
        df["high"]
        - df["low"]
    )
    tr2 = (
        df["high"]
        - previous_close
    ).abs()
    tr3 = (
        df["low"]
        - previous_close
    ).abs()
    true_range = pd.concat(
        [
            tr1,
            tr2,
            tr3,
        ],
        axis=1,
    ).max(axis=1)
    df["atr"] = (
        true_range
        .rolling(
            ATR_PERIOD
        )
        .mean()
    )
    df["momentum"] = (
        close.pct_change(5)
        * 100
    )
    if "volume" in df.columns:
        df["volume_ma"] = (
            df["volume"]
            .rolling(20)
            .mean()
        )
    return df
# =========================================================
# PRICE FORMAT
# =========================================================
def format_price(
    symbol,
    value,
):
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
def analyze_market(
    df,
    symbol,
):
    if df is None or len(df) < 220:
        return {
            "status": "DATA ERROR",
            "price": None,
            "strength": 0,
            "confidence": 0,
        }
    df = add_indicators(df)
    row = df.iloc[-1]
    try:
        price = float(
            row["close"]
        )
        ema21 = float(
            row["ema21"]
        )
        ema50 = float(
            row["ema50"]
        )
        ema200 = float(
            row["ema200"]
        )
        rsi = float(
            row["rsi"]
        )
        atr = float(
            row["atr"]
        )
        momentum = float(
            row["momentum"]
        )
    except Exception:
        return {
            "status": "DATA ERROR",
            "price": None,
            "strength": 0,
            "confidence": 0,
        }
    values = [
        price,
        ema21,
        ema50,
        ema200,
        rsi,
        atr,
        momentum,
    ]
    if not all(
        np.isfinite(x)
        for x in values
    ):
        return {
            "status": "DATA ERROR",
            "price": price,
            "strength": 0,
            "confidence": 0,
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
        volume = row.get(
            "volume"
        )
        volume_ma = row.get(
            "volume_ma"
        )
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
        sell_score,
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
    # Trend / sideways
    ema_spread_pct = (
        abs(
            ema21 - ema50
        )
        / price
        * 100
    )
    price_ema200_pct = (
        abs(
            price - ema200
        )
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
        0,
    )
    # Confidence
    confidence_map = {
        0: 40,
        1: 40,
        2: 45,
        3: 55,
        4: 65,
        5: 78,
        6: 90,
        7: 95,
    }
    confidence = confidence_map.get(
        score,
        40,
    )
    # Status
    if sideways or score <= 2:
        status = "WAIT"
        confidence = 40
    elif score >= 6:
        status = f"{side} STRONG"
    elif score == 5:
        status = side
    else:
        status = f"{side} WEAK"
    # Entry / SL / TP
    # Only calculate them for active signals.
    entry = price
    sl = None
    tp1 = None
    tp2 = None
    tp3 = None
    if status != "WAIT":
        if side == "BUY":
            sl = (
                entry
                - SL_ATR * atr
            )
            tp1 = (
                entry
                + TP1_ATR * atr
            )
            tp2 = (
                entry
                + TP2_ATR * atr
            )
            tp3 = (
                entry
                + TP3_ATR * atr
            )
        else:
            sl = (
                entry
                + SL_ATR * atr
            )
            tp1 = (
                entry
                - TP1_ATR * atr
            )
            tp2 = (
                entry
                - TP2_ATR * atr
            )
            tp3 = (
                entry
                - TP3_ATR * atr
            )
    return {
        "status": status,
        "side": side,
        "score": score,
        "strength": strength,
        "confidence": confidence,
        "price": price,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rsi": rsi,
        "momentum": momentum,
        "ema21": ema21,
        "ema50": ema50,
        "ema200": ema200,
        "sideways_pct": ema_spread_pct,
    }
# =========================================================
# RESULT FORMAT
# =========================================================
def format_result(
    symbol,
    result,
):
    info = SYMBOLS[symbol]
    name = info["name"]
    icon = info["icon"]
    status = result.get(
        "status",
        "DATA ERROR",
    )
    price = format_price(
        symbol,
        result.get("price"),
    )
    rsi = result.get(
        "rsi"
    )
    if rsi is not None:
        rsi_text = f"{rsi:.0f}"
    else:
        rsi_text = "N/A"
    # DATA ERROR
    if status == "DATA ERROR":
        return (
            f"⚠️ {icon} {name}\n"
            f"Price: {price}\n"
            f"DATA ERROR"
        )
    # WAIT
    if status == "WAIT":
        return (
            f"⚪ {icon} {name} | "
            f"WAIT ⚠️ | "
            f"RSI:{rsi_text} | "
            f"Conf:"
            f"{result.get('confidence', 40)}%\n"
            f"Price:{price} "
            f"Score:"
            f"{result.get('score', 0)}"
        )
    # Active signal
    if status.startswith("BUY"):
        signal_icon = "🟢"
        trend = "BULLISH 🟢"
    elif status.startswith("SELL"):
        signal_icon = "🔴"
        trend = "BEARISH 🔴"
    else:
        signal_icon = "⚪"
        trend = "NEUTRAL"
    return (
        f"{signal_icon} {icon} {name} | "
        f"{trend} | "
        f"RSI:{rsi_text} | "
        f"{status} "
        f"{'🚀' if 'STRONG' in status else '✅'} | "
        f"Conf:"
        f"{result.get('confidence', 0)}%\n"
        f"Price:{price} "
        f"TP1:{format_price(symbol, result.get('tp1'))} "
        f"SL:{format_price(symbol, result.get('sl'))} "
        f"Score:"
        f"{result.get('score', 0)}"
    )
# =========================================================
# SCAN
# =========================================================
def scan_one(
    timeframe,
    interval,
    symbol,
    info,
):
    print(
        f"Fetching {symbol} {timeframe}"
    )
    df = get_candles(
        info["td_symbol"],
        interval,
        260,
    )
    result = analyze_market(
        df,
        symbol,
    )
    return (
        timeframe,
        symbol,
        result,
    )
def scan_markets():
    all_results = {}
    # Faster scan:
    # requests are done in parallel instead
    # of waiting 3 seconds between every pair.
    from concurrent.futures import ThreadPoolExecutor
    jobs = []
    for timeframe, interval in TIMEFRAMES.items():
        all_results[timeframe] = {}
        for symbol, info in SYMBOLS.items():
            jobs.append(
                (
                    timeframe,
                    interval,
                    symbol,
                    info,
                )
            )
    with ThreadPoolExecutor(
        max_workers=9
    ) as executor:
        futures = [
            executor.submit(
                scan_one,
                *job,
            )
            for job in jobs
        ]
        for future in futures:
            try:
                timeframe, symbol, result = (
                    future.result()
                )
                all_results[
                    timeframe
                ][symbol] = result
            except Exception as e:
                print(
                    "Scan job error:",
                    repr(e),
                )
    return all_results
# =========================================================
# TELEGRAM MESSAGE
# =========================================================
def build_message(
    results,
    manual=False,
):
    now = datetime.now(
        DUBAI_TZ
    )
    timestamp = now.strftime(
        "%d-%m %I:%M %p"
    )
    title = (
        "💎 ADIL MARKET MOOD"
        if manual
        else "💎 ADIL PRO MARKET SCAN"
    )
    message = (
        f"{title}\n"
        f"🕐 {timestamp} Dubai\n\n"
    )
    # Display order
    for timeframe in [
        "15M",
        "1H",
        "4H",
    ]:
        message += (
            f"━━━━ {timeframe} ━━━━\n"
        )
        for symbol in [
            "BTCUSD.r",
            "XAUUSD.r",
            "EURUSD.r",
        ]:
            result = results.get(
                timeframe,
                {},
            ).get(
                symbol,
                {
                    "status": "DATA ERROR",
                    "price": None,
                    "strength": 0,
                    "confidence": 0,
                },
            )
            message += (
                format_result(
                    symbol,
                    result,
                )
                + "\n"
            )
        message += "\n"
    message += (
        "━━━━━━━━━━━━━━\n"
        "📊 Data: Twelve Data public feed\n"
        "🏦 Broker: Lirunex MT5\n"
        "⚙️ Execution: Manual\n"
        "⚠️ Public feed price may differ "
        "from Lirunex MT5\n"
        "⚠️ Technical signal only — "
        "no profit guarantee."
    )
    return message
# =========================================================
# BACKGROUND AUTO SCANNER
# =========================================================
def scanner_loop():
    print(
        "ADIL PRO MARKET SCANNER STARTED"
    )
    while True:
        try:
            print(
                "Starting automatic market scan..."
            )
            results = scan_markets()
            message = build_message(
                results,
                manual=False,
            )
            print(message)
            send_telegram(
                message
            )
        except Exception as e:
            print(
                "Scanner error:",
                repr(e),
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
    print(
        "=============================="
    )
    print(
        "ADIL PRO MARKET MOOD"
    )
    print(
        "=============================="
    )
    print(
        "Symbols:",
        list(
            SYMBOLS.keys()
        ),
    )
    print(
        "Twelve Data:",
        "API KEY FOUND"
        if TWELVE_API_KEY
        else "API KEY MISSING",
    )
    print(
        "Telegram:",
        "CONFIGURED"
        if CHAT_ID
        else "CHAT ID MISSING",
    )
    # Flask
    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True,
    )
    flask_thread.start()
    # Automatic scanner
    scanner_thread = threading.Thread(
        target=scanner_loop,
        daemon=True,
    )
    scanner_thread.start()
    # Telegram
    start_telegram()
