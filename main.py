import os

import time

import threading

import requests

import pandas as pd

import numpy as np

from flask import Flask

from telegram import Update

from telegram.ext import (

    Application,

    CommandHandler,

    ContextTypes,

    MessageHandler,

    filters,

)

# ============================================================

# CONFIG

# ============================================================

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

SL_ATR_BUFFER = 0.25

TP1_R = 1.0

TP2_R = 2.0

TP3_R = 3.0

RISK_MIN = 0.5

RISK_MAX = 1.0

SCAN_SECONDS = 300

# ============================================================

# FLASK

# ============================================================

app = Flask(__name__)

@app.route("/")

def home():

    return "ADIL PRO TREND PULLBACK BOT LIVE"

@app.route("/health")

def health():

    return "OK"

def flask_loop():

    port = int(os.getenv("PORT", "10000"))

    app.run(

        host="0.0.0.0",

        port=port,

        use_reloader=False,

    )

# ============================================================

# TELEGRAM

# ============================================================

def send_telegram(text):

    if not BOT_TOKEN or not CHAT_ID:

        print("Telegram credentials missing")

        return False

    try:

        url = (

            f"https://api.telegram.org/bot"

            f"{BOT_TOKEN}/sendMessage"

        )

        r = requests.post(

            url,

            json={

                "chat_id": CHAT_ID,

                "text": text,

            },

            timeout=30,

        )

        if r.status_code != 200:

            print("Telegram error:", r.text)

            return False

        return True

    except Exception as e:

        print("Telegram exception:", e)

        return False

# ============================================================

# DATA

# ============================================================

def get_data(symbol, interval, outputsize=250):

    try:

        url = "https://api.twelvedata.com/time_series"

        params = {

            "symbol": SYMBOLS[symbol]["td"],

            "interval": interval,

            "outputsize": outputsize,

            "apikey": TWELVE_DATA_API_KEY,

            "format": "JSON",

        }

        r = requests.get(

            url,

            params=params,

            timeout=40,

        )

        data = r.json()

        if "values" not in data:

            print(

                f"DATA ERROR {symbol} {interval}: "

                f"{data}"

            )

            return None

        df = pd.DataFrame(data["values"])

        if df.empty:

            return None

        df["datetime"] = pd.to_datetime(

            df["datetime"],

            errors="coerce",

        )

        for col in [

            "open",

            "high",

            "low",

            "close",

            "volume",

        ]:

            if col in df:

                df[col] = pd.to_numeric(

                    df[col],

                    errors="coerce",

                )

        df = df.dropna(

            subset=[

                "datetime",

                "open",

                "high",

                "low",

                "close",

            ]

        )

        df = (

            df.sort_values("datetime")

            .drop_duplicates("datetime")

            .reset_index(drop=True)

        )

        # Remove current unfinished candle.

        if len(df) > 3:

            df = df.iloc[:-1].copy()

        return df.reset_index(drop=True)

    except Exception as e:

        print(

            f"GET DATA ERROR "

            f"{symbol} {interval}: {e}"

        )

        return None

# ============================================================

# INDICATORS

# ============================================================

def indicators(df):

    if df is None or len(df) < 220:

        return None

    df = df.copy()

    close = df["close"]

    df["ema50"] = close.ewm(

        span=50,

        adjust=False,

    ).mean()

    df["ema200"] = close.ewm(

        span=200,

        adjust=False,

    ).mean()

    # RSI

    delta = close.diff()

    gain = delta.clip(lower=0)

    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(

        alpha=1 / 14,

        adjust=False,

    ).mean()

    avg_loss = loss.ewm(

        alpha=1 / 14,

        adjust=False,

    ).mean()

    rs = avg_gain / avg_loss.replace(

        0,

        np.nan,

    )

    df["rsi"] = (

        100 - (100 / (1 + rs))

    )

    # ATR

    prev_close = close.shift(1)

    tr = pd.concat(

        [

            df["high"] - df["low"],

            (df["high"] - prev_close).abs(),

            (df["low"] - prev_close).abs(),

        ],

        axis=1,

    ).max(axis=1)

    df["atr"] = tr.rolling(14).mean()

    # Momentum

    df["momentum"] = (

        close - close.shift(10)

    )

    return df.dropna().reset_index(

        drop=True

    )

# ============================================================

# MARKET STRUCTURE

# ============================================================

def structure(df, lookback=3):

    if df is None or len(df) < 20:

        return "NEUTRAL"

    recent = df.iloc[

        -lookback * 4:

    ].copy()

    highs = recent["high"].values

    lows = recent["low"].values

    if len(highs) < 8:

        return "NEUTRAL"

    # Simple recent swing structure.

    h1 = max(highs[: len(highs)//2])

    h2 = max(highs[len(highs)//2:])

    l1 = min(lows[: len(lows)//2])

    l2 = min(lows[len(lows)//2:])

    if h2 > h1 and l2 > l1:

        return "BULLISH"

    if h2 < h1 and l2 < l1:

        return "BEARISH"

    return "NEUTRAL"

# ============================================================

# HIGHER TIMEFRAME TREND

# ============================================================

def get_trend(df):

    if df is None or len(df) < 5:

        return "WAIT"

    row = df.iloc[-1]

    st = structure(df)

    bullish = (

        row["close"] > row["ema200"]

        and row["ema50"] > row["ema200"]

        and st == "BULLISH"

    )

    bearish = (

        row["close"] < row["ema200"]

        and row["ema50"] < row["ema200"]

        and st == "BEARISH"

    )

    if bullish:

        return "BUY"

    if bearish:

        return "SELL"

    return "WAIT"

# ============================================================

# 1H PULLBACK

# ============================================================

def pullback_confirmation(

    df,

    direction,

):

    if df is None or len(df) < 10:

        return False

    row = df.iloc[-1]

    prev = df.iloc[-2]

    atr = row["atr"]

    if not np.isfinite(atr) or atr <= 0:

        return False

    # BUY:

    # trend remains bullish but price pulls

    # toward EMA50 / EMA200 area.

    if direction == "BUY":

        near_ema50 = abs(

            row["close"] - row["ema50"]

        ) <= atr * 1.5

        previous_pullback = (

            prev["low"] <= prev["ema50"]

            or prev["close"] < prev["ema50"]

        )

        recovered = (

            row["close"] > row["ema50"]

        )

        return (

            near_ema50

            or (

                previous_pullback

                and recovered

            )

        )

    # SELL

    if direction == "SELL":

        near_ema50 = abs(

            row["close"] - row["ema50"]

        ) <= atr * 1.5

        previous_pullback = (

            prev["high"] >= prev["ema50"]

            or prev["close"] > prev["ema50"]

        )

        rejected = (

            row["close"] < row["ema50"]

        )

        return (

            near_ema50

            or (

                previous_pullback

                and rejected

            )

        )

    return False

# ============================================================

# 15M BREAK OF STRUCTURE

# ============================================================

def entry_confirmation(

    df,

    direction,

):

    if df is None or len(df) < 30:

        return None

    row = df.iloc[-1]

    prev = df.iloc[-2]

    lookback = df.iloc[-8:-2]

    recent_high = lookback["high"].max()

    recent_low = lookback["low"].min()

    # BUY BOS

    if direction == "BUY":

        bos = (

            row["close"] > recent_high

            and prev["close"] <= recent_high

        )

        momentum = (

            row["momentum"] > 0

        )

        candle = (

            row["close"] > prev["close"]

            and row["close"] > row["open"]

        )

        trend = (

            row["close"] > row["ema50"]

            and row["ema50"] > row["ema200"]

        )

        rsi_ok = (

            50 <= row["rsi"] <= 70

        )

        if (

            bos

            and momentum

            and candle

            and trend

            and rsi_ok

        ):

            return "BUY"

    # SELL BOS

    if direction == "SELL":

        bos = (

            row["close"] < recent_low

            and prev["close"] >= recent_low

        )

        momentum = (

            row["momentum"] < 0

        )

        candle = (

            row["close"] < prev["close"]

            and row["close"] < row["open"]

        )

        trend = (

            row["close"] < row["ema50"]

            and row["ema50"] < row["ema200"]

        )

        rsi_ok = (

            30 <= row["rsi"] <= 50

        )

        if (

            bos

            and momentum

            and candle

            and trend

            and rsi_ok

        ):

            return "SELL"

    return None

# ============================================================

# TRADE LEVELS

# ============================================================

def make_trade(

    df15,

    direction,

):

    row = df15.iloc[-1]

    entry = float(row["close"])

    atr = float(row["atr"])

    recent_low = float(

        df15.iloc[-8:-1]["low"].min()

    )

    recent_high = float(

        df15.iloc[-8:-1]["high"].max()

    )

    if direction == "BUY":

        structure_sl = (

            recent_low

            - atr * SL_ATR_BUFFER

        )

        atr_sl = (

            entry - atr * 1.2

        )

        # Use the wider logical stop.

        sl = min(

            structure_sl,

            atr_sl,

        )

        risk = entry - sl

        if risk <= 0:

            return None

        tp1 = entry + risk * TP1_R

        tp2 = entry + risk * TP2_R

        tp3 = entry + risk * TP3_R

    else:

        structure_sl = (

            recent_high

            + atr * SL_ATR_BUFFER

        )

        atr_sl = (

            entry + atr * 1.2

        )

        sl = max(

            structure_sl,

            atr_sl,

        )

        risk = sl - entry

        if risk <= 0:

            return None

        tp1 = entry - risk * TP1_R

        tp2 = entry - risk * TP2_R

        tp3 = entry - risk * TP3_R

    return {

        "direction": direction,

        "entry": entry,

        "sl": sl,

        "tp1": tp1,

        "tp2": tp2,

        "tp3": tp3,

        "risk_distance": risk,

        "atr": atr,

        "candle": row["datetime"],

    }

# ============================================================

# COMPLETE ANALYSIS

# ============================================================

def analyze(symbol):

    df4 = get_data(

        symbol,

        "4h",

        300,

    )

    df1 = get_data(

        symbol,

        "1h",

        300,

    )

    df15 = get_data(

        symbol,

        "15min",

        300,

    )

    if (

        df4 is None

        or df1 is None

        or df15 is None

    ):

        return {

            "signal": "WAIT",

            "reason": "DATA_ERROR",

        }

    df4 = indicators(df4)

    df1 = indicators(df1)

    df15 = indicators(df15)

    if (

        df4 is None

        or df1 is None

        or df15 is None

    ):

        return {

            "signal": "WAIT",

            "reason": "NOT_ENOUGH_DATA",

        }

    trend4 = get_trend(df4)

    trend1 = get_trend(df1)

    if trend4 == "WAIT":

        return {

            "signal": "WAIT",

            "reason": "4H trend unclear",

            "trend4": trend4,

            "trend1": trend1,

        }

    if trend1 != trend4:

        return {

            "signal": "WAIT",

            "reason": "4H / 1H trend conflict",

            "trend4": trend4,

            "trend1": trend1,

        }

    pullback = pullback_confirmation(

        df1,

        trend4,

    )

    if not pullback:

        return {

            "signal": "WAIT",

            "reason": "1H pullback not ready",

            "trend4": trend4,

            "trend1": trend1,

        }

    entry = entry_confirmation(

        df15,

        trend4,

    )

    if entry != trend4:

        return {

            "signal": "WAIT",

            "reason": "15M BOS confirmation missing",

            "trend4": trend4,

            "trend1": trend1,

        }

    trade = make_trade(

        df15,

        trend4,

    )

    if trade is None:

        return {

            "signal": "WAIT",

            "reason": "Invalid trade levels",

            "trend4": trend4,

            "trend1": trend1,

        }

    row = df15.iloc[-1]

    return {

        "signal": trend4,

        "reason": (

            "4H trend + 1H pullback + "

            "15M BOS confirmed"

        ),

        "trend4": trend4,

        "trend1": trend1,

        "pullback": True,

        "rsi": float(row["rsi"]),

        "momentum": float(row["momentum"]),

        "price": float(row["close"]),

        "candle": row["datetime"],

        "trade": trade,

    }

# ============================================================

# SIGNAL MESSAGE

# ============================================================

def signal_message(

    symbol,

    result,

):

    trade = result["trade"]

    name = SYMBOLS[symbol]["name"]

    direction = trade["direction"]

    emoji = (

        "🟢"

        if direction == "BUY"

        else "🔴"

    )

    return (

        f"{emoji} {direction} SIGNAL\n"

        f"━━━━━━━━━━━━━━━━━━\n"

        f"📊 {name} ({symbol})\n\n"

        f"💰 Entry: {trade['entry']:.5f}\n"

        f"🛑 SL: {trade['sl']:.5f}\n\n"

        f"🎯 TP1: {trade['tp1']:.5f}\n"

        f"🎯 TP2: {trade['tp2']:.5f}\n"

        f"🎯 TP3: {trade['tp3']:.5f}\n\n"

        f"📈 4H Trend: {result['trend4']}\n"

        f"📈 1H Trend: {result['trend1']}\n"

        f"🔄 1H Pullback: CONFIRMED\n"

        f"⚡ 15M BOS: CONFIRMED\n"

        f"RSI: {result['rsi']:.1f}\n\n"

        f"🧠 {result['reason']}\n\n"

        f"⚠️ Suggested risk: "

        f"{RISK_MIN:.1f}%–{RISK_MAX:.1f}%\n"

        f"📡 Data: Twelve Data public feed\n"

        f"🏦 Broker: Lirunex MT5\n"

        f"🖐 Execution: Manual\n\n"

        f"⚠️ Twelve Data price may differ "

        f"from Lirunex MT5."

    )

# ============================================================

# MARKET

# ============================================================

def market_report():

    lines = [

        "📊 PRO MARKET CHECK",

        "━━━━━━━━━━━━━━━━━━",

        "",

    ]

    for symbol in SYMBOLS:

        result = analyze(symbol)

        signal = result.get(

            "signal",

            "WAIT",

        )

        icon = {

            "BUY": "🟢",

            "SELL": "🔴",

            "WAIT": "⚪",

        }.get(signal, "⚪")

        lines.append(

            f"{icon} {SYMBOLS[symbol]['name']}"

        )

        lines.append(

            f"4H: {result.get('trend4', 'WAIT')}"

        )

        lines.append(

            f"1H: {result.get('trend1', 'WAIT')}"

        )

        lines.append(

            f"Status: {signal}"

        )

        lines.append(

            f"Reason: "

            f"{result.get('reason', '-')}"

        )

        lines.append("")

        time.sleep(1)

    lines.extend(

        [

            "━━━━━━━━━━━━━━━━━━",

            "📡 Twelve Data public feed",

            "🏦 Lirunex MT5",

            "🖐 Manual execution",

        ]

    )

    return "\n".join(lines)

# ============================================================

# DUPLICATE PROTECTION

# ============================================================

sent_signals = set()

def new_signal(

    symbol,

    direction,

    candle,

):

    key = (

        symbol,

        direction,

        str(candle),

    )

    if key in sent_signals:

        return False

    sent_signals.add(key)

    if len(sent_signals) > 300:

        sent_signals.pop()

    return True

# ============================================================

# SCANNER

# ============================================================

def scanner_loop():

    print(

        "PRO TREND PULLBACK SCANNER STARTED"

    )

    while True:

        try:

            for symbol in SYMBOLS:

                result = analyze(symbol)

                signal = result.get(

                    "signal",

                    "WAIT",

                )

                print(

                    f"{symbol}: {signal} | "

                    f"{result.get('reason', '')}"

                )

                if signal in [

                    "BUY",

                    "SELL",

                ]:

                    candle = result.get(

                        "candle"

                    )

                    if candle and new_signal(

                        symbol,

                        signal,

                        candle,

                    ):

                        send_telegram(

                            signal_message(

                                symbol,

                                result,

                            )

                        )

                time.sleep(2)

        except Exception as e:

            print(

                "SCANNER ERROR:",

                e,

            )

        time.sleep(

            SCAN_SECONDS

        )

# ============================================================

# BACKTEST DATA

# ============================================================

def historical_data(

    symbol,

    interval,

    days=90,

):

    try:

        now = pd.Timestamp.utcnow()

        if now.tzinfo is not None:

            now = now.tz_localize(None)

        start = (

            now

            - pd.Timedelta(days=days)

        )

        chunk_days = {

            "15min": 25,

            "1h": 60,

            "4h": 90,

        }[interval]

        parts = []

        current = start

        while current < now:

            end = min(

                current

                + pd.Timedelta(

                    days=chunk_days

                ),

                now,

            )

            url = (

                "https://api.twelvedata.com/"

                "time_series"

            )

            params = {

                "symbol": SYMBOLS[symbol]["td"],

                "interval": interval,

                "start_date": current.strftime(

                    "%Y-%m-%dT%H:%M:%S"

                ),

                "end_date": end.strftime(

                    "%Y-%m-%dT%H:%M:%S"

                ),

                "apikey": TWELVE_DATA_API_KEY,

                "format": "JSON",

                "order": "ASC",

            }

            print(

                f"BACKTEST "

                f"{symbol} {interval}: "

                f"{current.date()} -> "

                f"{end.date()}"

            )

            r = requests.get(

                url,

                params=params,

                timeout=60,

            )

            data = r.json()

            if "values" not in data:

                print(

                    "BACKTEST API ERROR:",

                    data,

                )

                return None

            part = pd.DataFrame(

                data["values"]

            )

            if not part.empty:

                part["datetime"] = pd.to_datetime(

                    part["datetime"],

                    errors="coerce",

                )

                for col in [

                    "open",

                    "high",

                    "low",

                    "close",

                ]:

                    part[col] = pd.to_numeric(

                        part[col],

                        errors="coerce",

                    )

                part = part.dropna(

                    subset=[

                        "datetime",

                        "open",

                        "high",

                        "low",

                        "close",

                    ]

                )

                parts.append(part)

            current = end

            time.sleep(2)

        if not parts:

            return None

        df = pd.concat(

            parts,

            ignore_index=True,

        )

        df = (

            df.drop_duplicates(

                "datetime"

            )

            .sort_values("datetime")

            .reset_index(drop=True)

        )

        if len(df) > 2:

            df = df.iloc[:-1]

        print(

            f"BACKTEST READY "

            f"{symbol} {interval}: "

            f"{len(df)} candles"

        )

        return df.reset_index(

            drop=True

        )

    except Exception as e:

        print(

            "HISTORICAL DATA ERROR:",

            e,

        )

        return None

# ============================================================

# BACKTEST HELPERS

# ============================================================

def latest_before(

    df,

    timestamp,

):

    x = df[

        df["datetime"] <= timestamp

    ]

    if x.empty:

        return None

    return x.iloc[-1]

def backtest_trend(

    df,

    timestamp,

):

    row = latest_before(

        df,

        timestamp,

    )

    if row is None:

        return "WAIT"

    available = df[

        df["datetime"] <= timestamp

    ]

    if len(available) < 20:

        return "WAIT"

    st = structure(

        available

    )

    if (

        row["close"] > row["ema200"]

        and row["ema50"] > row["ema200"]

        and st == "BULLISH"

    ):

        return "BUY"

    if (

        row["close"] < row["ema200"]

        and row["ema50"] < row["ema200"]

        and st == "BEARISH"

    ):

        return "SELL"

    return "WAIT"

def backtest_pullback(

    df,

    timestamp,

    direction,

):

    available = df[

        df["datetime"] <= timestamp

    ]

    if len(available) < 10:

        return False

    return pullback_confirmation(

        available,

        direction,

    )

def backtest_entry(

    df,

    i,

    direction,

):

    if i < 10:

        return None

    row = df.iloc[i]

    prev = df.iloc[i - 1]

    lookback = df.iloc[

        i - 8:i - 2

    ]

    recent_high = (

        lookback["high"].max()

    )

    recent_low = (

        lookback["low"].min()

    )

    if direction == "BUY":

        bos = (

            row["close"] > recent_high

            and prev["close"] <= recent_high

        )

        valid = (

            bos

            and row["momentum"] > 0

            and row["close"] > row["open"]

            and row["close"] > row["ema50"]

            and row["ema50"] > row["ema200"]

            and 50 <= row["rsi"] <= 70

        )

        if not valid:

            return None

    else:

        bos = (

            row["close"] < recent_low

            and prev["close"] >= recent_low

        )

        valid = (

            bos

            and row["momentum"] < 0

            and row["close"] < row["open"]

            and row["close"] < row["ema50"]

            and row["ema50"] < row["ema200"]

            and 30 <= row["rsi"] <= 50

        )

        if not valid:

            return None

    entry = float(

        row["close"]

    )

    atr = float(

        row["atr"]

    )

    recent_low = float(

        df.iloc[i - 8:i]["low"].min()

    )

    recent_high = float(

        df.iloc[i - 8:i]["high"].max()

    )

    if direction == "BUY":

        sl = min(

            recent_low - atr * SL_ATR_BUFFER,

            entry - atr * 1.2,

        )

        risk = entry - sl

        tp1 = entry + risk

        tp2 = entry + risk * 2

        tp3 = entry + risk * 3

    else:

        sl = max(

            recent_high + atr * SL_ATR_BUFFER,

            entry + atr * 1.2,

        )

        risk = sl - entry

        tp1 = entry - risk

        tp2 = entry - risk * 2

        tp3 = entry - risk * 3

    if risk <= 0:

        return None

    return {

        "direction": direction,

        "entry": entry,

        "sl": sl,

        "tp1": tp1,

        "tp2": tp2,

        "tp3": tp3,

        "time": row["datetime"],

    }

def check_exit(

    df,

    start,

    trade,

):

    for j in range(

        start + 1,

        len(df),

    ):

        row = df.iloc[j]

        high = float(

            row["high"]

        )

        low = float(

            row["low"]

        )

        if trade["direction"] == "BUY":

            hit_sl = (

                low <= trade["sl"]

            )

            hit_tp = (

                high >= trade["tp1"]

            )

        else:

            hit_sl = (

                high >= trade["sl"]

            )

            hit_tp = (

                low <= trade["tp1"]

            )

        # Conservative assumption.

        if hit_sl and hit_tp:

            return (

                "LOSS",

                -1.0,

                j,

            )

        if hit_sl:

            return (

                "LOSS",

                -1.0,

                j,

            )

        if hit_tp:

            return (

                "WIN",

                1.0,

                j,

            )

    return (

        "OPEN",

        0.0,

        len(df) - 1,

    )

# ============================================================

# ONE SYMBOL BACKTEST

# ============================================================

def backtest_symbol(symbol):

    df4 = historical_data(

        symbol,

        "4h",

        90,

    )

    df1 = historical_data(

        symbol,

        "1h",

        90,

    )

    df15 = historical_data(

        symbol,

        "15min",

        90,

    )

    if (

        df4 is None

        or df1 is None

        or df15 is None

    ):

        return []

    df4 = indicators(df4)

    df1 = indicators(df1)

    df15 = indicators(df15)

    if (

        df4 is None

        or df1 is None

        or df15 is None

    ):

        return []

    trades = []

    i = 20

    while i < len(df15) - 1:

        timestamp = df15.iloc[i][

            "datetime"

        ]

        trend4 = backtest_trend(

            df4,

            timestamp,

        )

        trend1 = backtest_trend(

            df1,

            timestamp,

        )

        if (

            trend4 == "WAIT"

            or trend1 != trend4

        ):

            i += 1

            continue

        if not backtest_pullback(

            df1,

            timestamp,

            trend4,

        ):

            i += 1

            continue

        trade = backtest_entry(

            df15,

            i,

            trend4,

        )

        if trade is None:

            i += 1

            continue

        result, r, exit_index = (

            check_exit(

                df15,

                i,

                trade,

            )

        )

        if result == "OPEN":

            break

        trade["result"] = result

        trade["r"] = r

        trades.append(trade)

        i = exit_index + 1

    return trades

# ============================================================

# BACKTEST STATS

# ============================================================

def stats(trades):

    wins = sum(

        t["result"] == "WIN"

        for t in trades

    )

    losses = sum(

        t["result"] == "LOSS"

        for t in trades

    )

    total = wins + losses

    winrate = (

        wins / total * 100

        if total

        else 0

    )

    net = sum(

        t["r"]

        for t in trades

    )

    equity = 0

    peak = 0

    max_dd = 0

    losing = 0

    max_losing = 0

    for t in trades:

        equity += t["r"]

        peak = max(

            peak,

            equity,

        )

        max_dd = max(

            max_dd,

            peak - equity,

        )

        if t["result"] == "LOSS":

            losing += 1

            max_losing = max(

                max_losing,

                losing,

            )

        else:

            losing = 0

    return {

        "total": total,

        "wins": wins,

        "losses": losses,

        "winrate": winrate,

        "net": net,

        "dd": max_dd,

        "losing": max_losing,

    }

# ============================================================

# FULL BACKTEST

# ============================================================

def run_backtest():

    start = time.time()

    all_trades = []

    text = [

        "📊 90-DAY PRO STRATEGY BACKTEST",

        "━━━━━━━━━━━━━━━━━━",

        "4H TREND",

        "1H PULLBACK",

        "15M BOS ENTRY",

        "",

    ]

    for symbol in SYMBOLS:

        name = SYMBOLS[symbol]["name"]

        text.append(

            f"⏳ Testing {name}..."

        )

        try:

            trades = backtest_symbol(

                symbol

            )

            all_trades.extend(

                trades

            )

            s = stats(trades)

            text.extend(

                [

                    f"Trades: {s['total']}",

                    f"Wins: {s['wins']}",

                    f"Losses: {s['losses']}",

                    f"Win rate: "

                    f"{s['winrate']:.1f}%",

                    f"Net: "

                    f"{s['net']:+.2f}R",

                    "",

                ]

            )

        except Exception as e:

            print(

                f"BACKTEST ERROR "

                f"{symbol}: {e}"

            )

            text.extend(

                [

                    "⚠️ DATA/TEST ERROR",

                    "",

                ]

            )

    overall = stats(

        all_trades

    )

    elapsed = (

        time.time() - start

    )

    text.extend(

        [

            "━━━━━━━━━━━━━━━━━━",

            "🏆 OVERALL",

            "",

            f"Total trades: "

            f"{overall['total']}",

            f"Wins: "

            f"{overall['wins']}",

            f"Losses: "

            f"{overall['losses']}",

            f"Win rate: "

            f"{overall['winrate']:.1f}%",

            f"Net result: "

            f"{overall['net']:+.2f}R",

            f"Max drawdown: "

            f"{overall['dd']:.2f}R",

            f"Max losing streak: "

            f"{overall['losing']}",

            "",

            f"⏱ Time: {elapsed:.0f}s",

            "",

            "📡 Data: Twelve Data",

            "🏦 Broker: Lirunex MT5",

            "🖐 Execution: Manual",

            "",

            "⚠️ TP1 = 1R backtest target.",

            "⚠️ Same-candle TP/SL = LOSS.",

            "⚠️ Historical performance is not",

            "a guarantee of future results.",

        ]

    )

    return "\n".join(text)

# ============================================================

# TELEGRAM COMMANDS

# ============================================================

async def start(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE,

):

    await update.message.reply_text(

        "🟢 ADIL PRO TREND PULLBACK BOT\n\n"

        "4H → Trend\n"

        "1H → Pullback\n"

        "15M → BOS Entry\n\n"

        "Pairs:\n"

        "🥇 GOLD\n"

        "💱 EURUSD\n"

        "₿ BTC\n\n"

        "Commands:\n"

        "/market\n"

        "/signal\n"

        "/backtest\n"

        "/status\n"

        "/test"

    )

async def status(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE,

):

    await update.message.reply_text(

        "🟢 BOT ONLINE\n\n"

        "Strategy: Trend + Pullback + BOS\n"

        "4H: Trend\n"

        "1H: Pullback\n"

        "15M: Entry\n\n"

        "SL: Structure + ATR\n"

        "TP1: 1R\n"

        "TP2: 2R\n"

        "TP3: 3R\n\n"

        "Scanner: 5 minutes\n"

        "Execution: Manual MT5"

    )

async def test(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE,

):

    await update.message.reply_text(

        "✅ Telegram connection working."

    )

async def market(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE,

):

    await update.message.reply_text(

        "⏳ Checking..."

    )

    await update.message.reply_text(

        market_report()

    )

async def signal(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE,

):

    await update.message.reply_text(

        "⏳ Searching confirmed setups..."

    )

    found = 0

    for symbol in SYMBOLS:

        result = analyze(symbol)

        if result.get(

            "signal"

        ) in [

            "BUY",

            "SELL",

        ]:

            await update.message.reply_text(

                signal_message(

                    symbol,

                    result,

                )

            )

            found += 1

        time.sleep(1)

    if found == 0:

        await update.message.reply_text(

            "⚪ No confirmed setup right now.\n\n"

            "The bot is waiting for:\n"

            "4H trend → 1H pullback → "

            "15M BOS."

        )

async def backtest(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE,

):

    await update.message.reply_text(

        "⏳ 90-day backtest starting...\n"

        "Historical data is being downloaded "

        "in safe chunks."

    )

    try:

        result = run_backtest()

        await update.message.reply_text(

            result[:3900]

        )

    except Exception as e:

        print(

            "BACKTEST COMMAND ERROR:",

            e,

        )

        await update.message.reply_text(

            f"❌ Backtest error:\n{str(e)[:1000]}"

        )

async def text_handler(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE,

):

    if not update.message:

        return

    text = (

        update.message.text

        .strip()

        .lower()

    )

    if text in [

        "market",

        "mood",

    ]:

        await market(

            update,

            context,

        )

    elif text == "signal":

        await signal(

            update,

            context,

        )

    elif text == "backtest":

        await backtest(

            update,

            context,

        )

    elif text == "status":

        await status(

            update,

            context,

        )

# ============================================================

# TELEGRAM LOOP

# ============================================================

def telegram_loop():

    application = (

        Application.builder()

        .token(BOT_TOKEN)

        .build()

    )

    application.add_handler(

        CommandHandler(

            "start",

            start,

        )

    )

    application.add_handler(

        CommandHandler(

            "status",

            status,

        )

    )

    application.add_handler(

        CommandHandler(

            "test",

            test,

        )

    )

    application.add_handler(

        CommandHandler(

            "market",

            market,

        )

    )

    application.add_handler(

        CommandHandler(

            "signal",

            signal,

        )

    )

    application.add_handler(

        CommandHandler(

            "backtest",

            backtest,

        )

    )

    application.add_handler(

        MessageHandler(

            filters.TEXT

            & ~filters.COMMAND,

            text_handler,

        )

    )

    print(

        "Telegram bot started."

    )

    application.run_polling(

        drop_pending_updates=True

    )

# ============================================================

# MAIN

# ============================================================

if __name__ == "__main__":

    print(

        "===================================="

    )

    print(

        "ADIL PRO TREND PULLBACK BOT"

    )

    print(

        "===================================="

    )

    threading.Thread(

        target=flask_loop,

        daemon=True,

    ).start()

    threading.Thread(

        target=scanner_loop,

        daemon=True,

    ).start()

    telegram_loop()
