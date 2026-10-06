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

    "XAUUSD.r": {

        "name": "GOLD",

        "td": "XAU/USD",

    },

    "EURUSD.r": {

        "name": "EURUSD",

        "td": "EUR/USD",

    },

    "BTCUSD.r": {

        "name": "BTC",

        "td": "BTC/USD",

    },

}

flask_app = Flask(__name__)

# =========================================================

# FLASK

# =========================================================

@flask_app.route("/")

def home():

    return "ADIL PRO MARKET MOOD v15 LIVE"

@flask_app.route("/health")

def health():

    return {

        "status": "online",

        "telegram": bool(BOT_TOKEN),

        "twelve_data": bool(TWELVE_DATA_API_KEY),

        "chat_id": bool(CHAT_ID),

    }

# =========================================================

# INDICATORS

# =========================================================

def ema(series, period):

    return series.ewm(span=period, adjust=False).mean()

def rsi(series, period=14):

    delta = series.diff()

    gain = delta.clip(lower=0)

    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()

    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)

    value = 100 - (100 / (1 + rs))

    return value.fillna(50)

def atr(df, period=14):

    high_low = df["high"] - df["low"]

    high_close = abs(df["high"] - df["close"].shift())

    low_close = abs(df["low"] - df["close"].shift())

    tr = pd.concat(

        [high_low, high_close, low_close],

        axis=1

    ).max(axis=1)

    return tr.rolling(period).mean()

# =========================================================

# TWELVE DATA

# =========================================================

def get_data(symbol, interval, outputsize=250):

    if not TWELVE_DATA_API_KEY:

        print("ERROR: TWELVE_DATA_API_KEY missing", flush=True)

        return None

    if symbol not in SYMBOLS:

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

        response = requests.get(

            url,

            params=params,

            timeout=30

        )

        data = response.json()

        if "values" not in data:

            print(

                f"DATA ERROR {symbol} {interval}: {data}",

                flush=True

            )

            return None

        df = pd.DataFrame(data["values"])

        if df.empty:

            return None

        df["datetime"] = pd.to_datetime(df["datetime"])

        for col in [

            "open",

            "high",

            "low",

            "close"

        ]:

            df[col] = pd.to_numeric(

                df[col],

                errors="coerce"

            )

        df = df.dropna()

        df = df.sort_values("datetime")

        df = df.reset_index(drop=True)

        return df

    except Exception as e:

        print(

            f"DATA EXCEPTION {symbol} {interval}: {e}",

            flush=True

        )

        return None

# =========================================================

# MARKET ANALYSIS

# =========================================================

def analyze_trend(df):

    if df is None or len(df) < 210:

        return "WAIT", "NOT_ENOUGH_DATA"

    df = df.copy()

    df["ema50"] = ema(df["close"], 50)

    df["ema200"] = ema(df["close"], 200)

    last = df.iloc[-1]

    if (

        last["close"] > last["ema200"]

        and last["ema50"] > last["ema200"]

    ):

        return "BUY", "BULLISH TREND"

    if (

        last["close"] < last["ema200"]

        and last["ema50"] < last["ema200"]

    ):

        return "SELL", "BEARISH TREND"

    return "WAIT", "NO CLEAR TREND"

def analyze_momentum(df):

    if df is None or len(df) < 60:

        return "WAIT", "NOT_ENOUGH_DATA"

    df = df.copy()

    df["ema50"] = ema(df["close"], 50)

    df["ema200"] = ema(df["close"], 200)

    df["rsi"] = rsi(df["close"])

    df["atr"] = atr(df)

    last = df.iloc[-1]

    bullish = (

        last["close"] > last["ema50"]

        and last["ema50"] > last["ema200"]

        and 50 <= last["rsi"] <= 70

    )

    bearish = (

        last["close"] < last["ema50"]

        and last["ema50"] < last["ema200"]

        and 30 <= last["rsi"] <= 50

    )

    if bullish:

        return "BUY", "BULLISH MOMENTUM"

    if bearish:

        return "SELL", "BEARISH MOMENTUM"

    return "WAIT", "NO ENTRY"

# =========================================================

# SIGNAL

# =========================================================

def generate_signal(symbol):

    df4h = get_data(symbol, "4h", 250)

    if df4h is None:

        return {

            "signal": "WAIT",

            "reason": "DATA_ERROR",

        }

    trend, trend_reason = analyze_trend(df4h)

    if trend == "WAIT":

        return {

            "signal": "WAIT",

            "reason": trend_reason,

        }

    df1h = get_data(symbol, "1h", 250)

    if df1h is None:

        return {

            "signal": "WAIT",

            "reason": "1H_DATA_ERROR",

        }

    df15 = get_data(symbol, "15min", 250)

    if df15 is None:

        return {

            "signal": "WAIT",

            "reason": "15M_DATA_ERROR",

        }

    momentum, momentum_reason = analyze_momentum(df15)

    if momentum != trend:

        return {

            "signal": "WAIT",

            "reason": "TIMEFRAME_CONFLICT",

        }

    last = df15.iloc[-1]

    entry = float(last["close"])

    atr_value = float(

        atr(df15).iloc[-1]

    )

    if not np.isfinite(atr_value) or atr_value <= 0:

        return {

            "signal": "WAIT",

            "reason": "ATR_ERROR",

        }

    if trend == "BUY":

        sl = entry - (1.2 * atr_value)

        risk = entry - sl

        tp1 = entry + risk

        tp2 = entry + (2 * risk)

        tp3 = entry + (3 * risk)

    else:

        sl = entry + (1.2 * atr_value)

        risk = sl - entry

        tp1 = entry - risk

        tp2 = entry - (2 * risk)

        tp3 = entry - (3 * risk)

    return {

        "signal": trend,

        "reason": "4H TREND + 15M MOMENTUM",

        "entry": entry,

        "sl": sl,

        "tp1": tp1,

        "tp2": tp2,

        "tp3": tp3,

    }

# =========================================================

# FORMAT

# =========================================================

def format_signal(symbol):

    result = generate_signal(symbol)

    name = SYMBOLS[symbol]["name"]

    signal = result["signal"]

    text = (

        f"📊 {name}\n"

        f"Signal: {signal}\n"

        f"Reason: {result['reason']}\n"

    )

    if signal in ("BUY", "SELL"):

        text += (

            f"\nEntry: {result['entry']:.5f}"

            f"\nSL: {result['sl']:.5f}"

            f"\nTP1: {result['tp1']:.5f}"

            f"\nTP2: {result['tp2']:.5f}"

            f"\nTP3: {result['tp3']:.5f}"

            f"\n\nRisk: 0.5–1% max"

        )

    return text

# =========================================================

# TELEGRAM COMMANDS

# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id

    print(

        f"CHAT_ID FOUND: {chat_id}",

        flush=True

    )

    await update.message.reply_text(

        "🟢 ADIL PRO MARKET MOOD v15\n\n"

        f"Your Chat ID: {chat_id}\n\n"

        "Bot is online.\n\n"

        "📊 Commands:\n"

        "/market\n"

        "/mood\n"

        "/signal\n"

        "/status\n"

        "/test"

    )

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id

    await update.message.reply_text(

        "✅ TELEGRAM TEST OK\n\n"

        f"CHAT_ID: {chat_id}"

    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(

        "🟢 ADIL PRO MARKET MOOD\n\n"

        "Telegram: ONLINE\n"

        f"Twelve Data: {'CONFIGURED' if TWELVE_DATA_API_KEY else 'MISSING'}\n"

        f"CHAT_ID: {update.effective_chat.id}\n\n"

        "Broker: Lirunex MT5\n"

        "Execution: Manual"

    )

async def market(update: Update, context: ContextTypes.DEFAULT_TYPE):

    lines = [

        "📊 PRO MARKET CHECK",

        "━━━━━━━━━━━━━━━━━━"

    ]

    for symbol in SYMBOLS:

        result = generate_signal(symbol)

        name = SYMBOLS[symbol]["name"]

        lines.append(

            f"\n{'🟢' if result['signal']=='BUY' else '🔴' if result['signal']=='SELL' else '⚪'} {name}"

        )

        lines.append(

            f"Signal: {result['signal']}"

        )

        lines.append(

            f"Reason: {result['reason']}"

        )

    lines.extend([

        "",

        "━━━━━━━━━━━━━━━━━━",

        "📡 Data: Twelve Data public feed",

        "🏦 Broker: Lirunex MT5",

        "🖐 Execution: Manual",

        "",

        "⚠️ Public feed prices may differ from Lirunex MT5."

    ])

    await update.message.reply_text(

        "\n".join(lines)

    )

async def mood(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await market(update, context)

async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):

    messages = []

    for symbol in SYMBOLS:

        messages.append(

            format_signal(symbol)

        )

    messages.append(

        "\n━━━━━━━━━━━━━━━━━━\n"

        "📡 Data: Twelve Data public feed\n"

        "🏦 Broker: Lirunex MT5\n"

        "🖐 Execution: Manual\n"

        "⚠️ Public feed prices may differ from Lirunex MT5."

    )

    await update.message.reply_text(

        "\n\n".join(messages)

    )

# =========================================================

# TELEGRAM BOT

# =========================================================

def run_bot():

    if not BOT_TOKEN:

        print(

            "ERROR: BOT_TOKEN missing",

            flush=True

        )

        return

    print(

        "Starting Telegram bot...",

        flush=True

    )

    try:

        application = (

            ApplicationBuilder()

            .token(BOT_TOKEN)

            .build()

        )

        application.add_handler(

            CommandHandler("start", start)

        )

        application.add_handler(

            CommandHandler("test", test)

        )

        application.add_handler(

            CommandHandler("status", status)

        )

        application.add_handler(

            CommandHandler("market", market)

        )

        application.add_handler(

            CommandHandler("mood", mood)

        )

        application.add_handler(

            CommandHandler("signal", signal)

        )

        print(

            "Telegram polling started.",

            flush=True

        )

        application.run_polling(

            drop_pending_updates=True,

            allowed_updates=Update.ALL_TYPES

        )

    except Exception as e:

        print(

            f"TELEGRAM ERROR: {e}",

            flush=True

        )

# =========================================================

# SCANNER

# =========================================================

def scanner():

    print(

        "Scanner started.",

        flush=True

    )

    while True:

        try:

            # Scanner intentionally kept light

            # to avoid excessive Twelve Data requests.

            time.sleep(300)

        except Exception as e:

            print(

                f"SCANNER ERROR: {e}",

                flush=True

            )

            time.sleep(60)

# =========================================================

# START

# =========================================================

if __name__ == "__main__":

    print(

        "================================",

        flush=True

    )

    print(

        "ADIL PRO MARKET MOOD v15",

        flush=True

    )

    print(

        "Starting...",

        flush=True

    )

    print(

        "================================",

        flush=True

    )

    if not BOT_TOKEN:

        print(

            "WARNING: BOT_TOKEN missing",

            flush=True

        )

    if not TWELVE_DATA_API_KEY:

        print(

            "WARNING: TWELVE_DATA_API_KEY missing",

            flush=True

        )

    if not CHAT_ID:

        print(

            "INFO: CHAT_ID not set yet.",

            flush=True

        )

    threading.Thread(

        target=scanner,

        daemon=True

    ).start()

    threading.Thread(

        target=run_bot,

        daemon=True

    ).start()

    flask_app.run(

        host="0.0.0.0",

        port=int(

            os.environ.get(

                "PORT",

                10000

            )

        )

    )
