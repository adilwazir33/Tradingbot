import os

import time

import threading

from datetime import datetime, timedelta

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

if not BOT_TOKEN:

    print("WARNING: BOT_TOKEN missing")

if not CHAT_ID:

    print("WARNING: CHAT_ID missing")

if not TWELVE_DATA_API_KEY:

    print("WARNING: TWELVE_DATA_API_KEY missing")

SYMBOLS = {

    "XAUUSD.r": {

        "name": "GOLD",

        "td_symbol": "XAU/USD",

    },

    "EURUSD.r": {

        "name": "EUR",

        "td_symbol": "EUR/USD",

    },

    "BTCUSD.r": {

        "name": "BTC",

        "td_symbol": "BTC/USD",

    },

}

TIMEFRAMES = {

    "4h": "4h",

    "1h": "1h",

    "15m": "15min",

}

SL_ATR = 1.2

TP1_ATR = 1.5

TP2_ATR = 2.5

TP3_ATR = 3.5

SCAN_SECONDS = 300

# ============================================================

# FLASK

# ============================================================

flask_app = Flask(__name__)

@flask_app.route("/")

def home():

    return "ADIL PRO MARKET MOOD v14 LIVE"

@flask_app.route("/health")

def health():

    return "OK"

def flask_loop():

    port = int(os.getenv("PORT", "10000"))

    flask_app.run(

        host="0.0.0.0",

        port=port,

        use_reloader=False,

    )

# ============================================================

# TELEGRAM

# ============================================================

def send_telegram(message):

    if not BOT_TOKEN or not CHAT_ID:

        print("Telegram credentials missing")

        return False

    try:

        url = (

            f"https://api.telegram.org/bot"

            f"{BOT_TOKEN}/sendMessage"

        )

        payload = {

            "chat_id": CHAT_ID,

            "text": message,

        }

        response = requests.post(

            url,

            json=payload,

            timeout=30,

        )

        if response.status_code != 200:

            print(

                "Telegram error:",

                response.status_code,

                response.text,

            )

            return False

        return True

    except Exception as e:

        print("Telegram exception:", e)

        return False

# ============================================================

# TWELVE DATA

# ============================================================

def get_candles(

    symbol,

    interval,

    outputsize=250,

):

    """

    Live data.

    Twelve Data returns newest candles first by default.

    We sort ascending and remove the currently forming candle.

    """

    if symbol not in SYMBOLS:

        return None

    td_symbol = SYMBOLS[symbol]["td_symbol"]

    url = "https://api.twelvedata.com/time_series"

    params = {

        "symbol": td_symbol,

        "interval": interval,

        "outputsize": outputsize,

        "apikey": TWELVE_DATA_API_KEY,

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

                f"TWELVE DATA LIVE ERROR "

                f"{symbol} {interval}: "

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

            if col in df.columns:

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

        # Last candle may still be forming.

        if len(df) > 2:

            df = df.iloc[:-1].copy()

        return df.reset_index(drop=True)

    except Exception as e:

        print(

            f"GET CANDLES ERROR "

            f"{symbol} {interval}: {e}"

        )

        return None

# ============================================================

# INDICATORS

# ============================================================

def add_indicators(df):

    df = df.copy()

    if len(df) < 210:

        return None

    close = df["close"]

    df["ema21"] = close.ewm(

        span=21,

        adjust=False,

    ).mean()

    df["ema50"] = close.ewm(

        span=50,

        adjust=False,

    ).mean()

    df["ema200"] = close.ewm(

        span=200,

        adjust=False,

    ).mean()

    # RSI 14

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

    df["rsi"] = 100 - (

        100 / (1 + rs)

    )

    # True Range / ATR

    previous_close = close.shift(1)

    tr1 = (

        df["high"] - df["low"]

    )

    tr2 = (

        df["high"] - previous_close

    ).abs()

    tr3 = (

        df["low"] - previous_close

    ).abs()

    df["tr"] = pd.concat(

        [tr1, tr2, tr3],

        axis=1,

    ).max(axis=1)

    df["atr"] = df["tr"].rolling(

        14

    ).mean()

    # Simple momentum

    df["momentum"] = (

        close - close.shift(10)

    )

    return df.dropna().reset_index(

        drop=True

    )

# ============================================================

# TREND

# ============================================================

def timeframe_trend(df):

    if df is None or len(df) < 2:

        return "WAIT"

    row = df.iloc[-1]

    if (

        row["ema21"] > row["ema50"]

        and row["close"] > row["ema200"]

    ):

        return "BUY"

    if (

        row["ema21"] < row["ema50"]

        and row["close"] < row["ema200"]

    ):

        return "SELL"

    return "WAIT"

# ============================================================

# 15M ENTRY CONFIRMATION

# ============================================================

def entry_confirmation(df):

    if df is None or len(df) < 3:

        return "WAIT"

    row = df.iloc[-1]

    prev = df.iloc[-2]

    # --------------------------------------------------------

    # BUY

    # --------------------------------------------------------

    buy = (

        row["ema21"] > row["ema50"]

        and row["close"] > row["ema200"]

        and 50 <= row["rsi"] <= 68

        and row["momentum"] > 0

        and row["close"] > prev["close"]

        and row["close"] > row["ema21"]

    )

    if buy:

        return "BUY"

    # --------------------------------------------------------

    # SELL

    # --------------------------------------------------------

    sell = (

        row["ema21"] < row["ema50"]

        and row["close"] < row["ema200"]

        and 32 <= row["rsi"] <= 50

        and row["momentum"] < 0

        and row["close"] < prev["close"]

        and row["close"] < row["ema21"]

    )

    if sell:

        return "SELL"

    return "WAIT"

# ============================================================

# FULL SYMBOL ANALYSIS

# ============================================================

def analyze_symbol(symbol):

    try:

        data_4h = get_candles(

            symbol,

            TIMEFRAMES["4h"],

            250,

        )

        data_1h = get_candles(

            symbol,

            TIMEFRAMES["1h"],

            250,

        )

        data_15m = get_candles(

            symbol,

            TIMEFRAMES["15m"],

            250,

        )

        if (

            data_4h is None

            or data_1h is None

            or data_15m is None

        ):

            return {

                "signal": "WAIT",

                "reason": "DATA_ERROR",

            }

        data_4h = add_indicators(data_4h)

        data_1h = add_indicators(data_1h)

        data_15m = add_indicators(data_15m)

        if (

            data_4h is None

            or data_1h is None

            or data_15m is None

        ):

            return {

                "signal": "WAIT",

                "reason": "NOT_ENOUGH_DATA",

            }

        trend_4h = timeframe_trend(data_4h)

        trend_1h = timeframe_trend(data_1h)

        entry_15m = entry_confirmation(data_15m)

        row = data_15m.iloc[-1]

        # Higher timeframe agreement is mandatory.

        if trend_4h == "WAIT":

            signal = "WAIT"

            reason = "4H trend unclear"

        elif trend_1h == "WAIT":

            signal = "WAIT"

            reason = "1H trend unclear"

        elif trend_4h != trend_1h:

            signal = "WAIT"

            reason = "4H / 1H conflict"

        elif entry_15m != trend_4h:

            signal = "WAIT"

            reason = "15M confirmation missing"

        else:

            signal = entry_15m

            reason = "4H + 1H + 15M confirmed"

        return {

            "signal": signal,

            "reason": reason,

            "trend_4h": trend_4h,

            "trend_1h": trend_1h,

            "entry_15m": entry_15m,

            "price": float(row["close"]),

            "atr": float(row["atr"]),

            "rsi": float(row["rsi"]),

            "momentum": float(row["momentum"]),

            "candle_time": row["datetime"],

        }

    except Exception as e:

        print(

            f"ANALYSIS ERROR {symbol}: {e}"

        )

        return {

            "signal": "WAIT",

            "reason": "ANALYSIS_ERROR",

        }

# ============================================================

# SIGNAL MESSAGE

# ============================================================

def signal_message(symbol, result):

    name = SYMBOLS[symbol]["name"]

    direction = result["signal"]

    price = result["price"]

    atr = result["atr"]

    if direction == "BUY":

        sl = price - (

            SL_ATR * atr

        )

        tp1 = price + (

            TP1_ATR * atr

        )

        tp2 = price + (

            TP2_ATR * atr

        )

        tp3 = price + (

            TP3_ATR * atr

        )

        emoji = "🟢"

    elif direction == "SELL":

        sl = price + (

            SL_ATR * atr

        )

        tp1 = price - (

            TP1_ATR * atr

        )

        tp2 = price - (

            TP2_ATR * atr

        )

        tp3 = price - (

            TP3_ATR * atr

        )

        emoji = "🔴"

    else:

        return None

    return (

        f"{emoji} {direction} SIGNAL\n"

        f"━━━━━━━━━━━━━━━━━━\n"

        f"📊 {name} ({symbol})\n\n"

        f"💰 Entry: {price:.5f}\n\n"

        f"🛑 SL: {sl:.5f}\n"

        f"🎯 TP1: {tp1:.5f}\n"

        f"🎯 TP2: {tp2:.5f}\n"

        f"🎯 TP3: {tp3:.5f}\n\n"

        f"📈 4H: {result['trend_4h']}\n"

        f"📈 1H: {result['trend_1h']}\n"

        f"⚡ 15M: {result['entry_15m']}\n"

        f"RSI: {result['rsi']:.1f}\n\n"

        f"🧠 {result['reason']}\n\n"

        f"📡 Data: Twelve Data public feed\n"

        f"🏦 Broker: Lirunex MT5\n"

        f"🖐 Execution: Manual\n\n"

        f"⚠️ Twelve Data price may differ from "

        f"Lirunex MT5.\n"

        f"⚠️ No guaranteed profit."

    )

# ============================================================

# MARKET REPORT

# ============================================================

def market_report():

    lines = [

        "📊 MARKET REPORT",

        "━━━━━━━━━━━━━━━━━━",

    ]

    for symbol in SYMBOLS:

        result = analyze_symbol(symbol)

        name = SYMBOLS[symbol]["name"]

        signal = result.get("signal", "WAIT")

        if signal == "BUY":

            icon = "🟢"

        elif signal == "SELL":

            icon = "🔴"

        else:

            icon = "⚪"

        lines.append(

            f"{icon} {name} ({symbol})"

        )

        lines.append(

            f"4H: {result.get('trend_4h', 'WAIT')} | "

            f"1H: {result.get('trend_1h', 'WAIT')} | "

            f"15M: {result.get('entry_15m', 'WAIT')}"

        )

        if "price" in result:

            lines.append(

                f"Price: {result['price']:.5f}"

            )

        lines.append(

            f"Status: {signal}"

        )

        lines.append("")

    lines.extend(

        [

            "━━━━━━━━━━━━━━━━━━",

            "📡 Data: Twelve Data public feed",

            "🏦 Broker: Lirunex MT5",

            "🖐 Execution: Manual",

            "",

            "⚠️ Public feed prices may differ "

            "from Lirunex MT5.",

        ]

    )

    return "\n".join(lines)

# ============================================================

# DUPLICATE PROTECTION

# ============================================================

last_sent = {}

def should_send_signal(

    symbol,

    signal,

    candle_time,

):

    if signal not in [

        "BUY",

        "SELL",

    ]:

        return False

    key = (

        symbol,

        signal,

        str(candle_time),

    )

    if key in last_sent:

        return False

    last_sent[key] = True

    # Keep dictionary from growing forever.

    if len(last_sent) > 200:

        first_key = next(

            iter(last_sent)

        )

        del last_sent[first_key]

    return True

# ============================================================

# LIVE SCANNER

# ============================================================

def scanner_loop():

    print("Scanner started.")

    while True:

        try:

            print(

                f"Scanner check: "

                f"{datetime.utcnow()}"

            )

            for symbol in SYMBOLS:

                result = analyze_symbol(

                    symbol

                )

                signal = result.get(

                    "signal",

                    "WAIT",

                )

                candle_time = result.get(

                    "candle_time"

                )

                print(

                    f"{symbol}: "

                    f"{signal}"

                )

                if (

                    signal in [

                        "BUY",

                        "SELL",

                    ]

                    and candle_time is not None

                ):

                    if should_send_signal(

                        symbol,

                        signal,

                        candle_time,

                    ):

                        message = signal_message(

                            symbol,

                            result,

                        )

                        if message:

                            send_telegram(

                                message

                            )

                # Avoid hammering API.

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

def get_backtest_data(

    symbol,

    interval,

    days=90,

):

    """

    Historical data fetch.

    Twelve Data max outputsize is 5000.

    Therefore 15M data is split into chunks.

    """

    if symbol not in SYMBOLS:

        return None

    try:

        now = pd.Timestamp.utcnow()

        if now.tzinfo is not None:

            now = now.tz_localize(None)

        start = (

            now

            - pd.Timedelta(days=days)

        )

        # Maximum safe chunks.

        #

        # 15M:

        # 25 days ~= 2400 candles

        #

        # 1H:

        # 60 days ~= 1440 candles

        #

        # 4H:

        # 90 days ~= 540 candles

        chunk_days = {

            "15min": 25,

            "1h": 60,

            "4h": 90,

        }

        chunk = chunk_days[interval]

        all_parts = []

        current = start

        while current < now:

            current_end = min(

                current

                + pd.Timedelta(

                    days=chunk

                ),

                now,

            )

            url = (

                "https://api.twelvedata.com/"

                "time_series"

            )

            params = {

                "symbol": SYMBOLS[symbol][

                    "td_symbol"

                ],

                "interval": interval,

                "start_date": current.strftime(

                    "%Y-%m-%dT%H:%M:%S"

                ),

                "end_date": current_end.strftime(

                    "%Y-%m-%dT%H:%M:%S"

                ),

                "apikey": TWELVE_DATA_API_KEY,

                "format": "JSON",

                "order": "ASC",

            }

            print(

                f"BACKTEST FETCH "

                f"{symbol} {interval} "

                f"{current.date()} -> "

                f"{current_end.date()}"

            )

            response = requests.get(

                url,

                params=params,

                timeout=60,

            )

            try:

                data = response.json()

            except Exception:

                print(

                    "INVALID JSON:",

                    response.text[:500],

                )

                return None

            if "values" not in data:

                print(

                    "TWELVE DATA "

                    "BACKTEST ERROR:"

                )

                print(data)

                return None

            part = pd.DataFrame(

                data["values"]

            )

            if part.empty:

                current = current_end

                time.sleep(1)

                continue

            part["datetime"] = pd.to_datetime(

                part["datetime"],

                errors="coerce",

            )

            for col in [

                "open",

                "high",

                "low",

                "close",

                "volume",

            ]:

                if col in part.columns:

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

            all_parts.append(part)

            current = current_end

            # Rate-limit protection.

            time.sleep(2)

        if not all_parts:

            print(

                f"NO DATA: "

                f"{symbol} {interval}"

            )

            return None

        df = pd.concat(

            all_parts,

            ignore_index=True,

        )

        df = (

            df.drop_duplicates(

                subset=["datetime"]

            )

            .sort_values("datetime")

            .reset_index(drop=True)

        )

        # We don't want future/current candle.

        df = df[

            df["datetime"] <= now

        ].copy()

        # Remove last candle because it may be incomplete.

        if len(df) > 2:

            df = df.iloc[:-1].copy()

        df = df.reset_index(

            drop=True

        )

        print(

            f"BACKTEST DATA OK "

            f"{symbol} {interval}: "

            f"{len(df)} candles"

        )

        return df

    except Exception as e:

        print(

            f"BACKTEST DATA ERROR "

            f"{symbol} {interval}: {e}"

        )

        return None

# ============================================================

# PREPARE BACKTEST

# ============================================================

def prepare_backtest(symbol):

    df15 = get_backtest_data(

        symbol,

        "15min",

        90,

    )

    df1h = get_backtest_data(

        symbol,

        "1h",

        90,

    )

    df4h = get_backtest_data(

        symbol,

        "4h",

        90,

    )

    if (

        df15 is None

        or df1h is None

        or df4h is None

    ):

        return None

    df15 = add_indicators(df15)

    df1h = add_indicators(df1h)

    df4h = add_indicators(df4h)

    if (

        df15 is None

        or df1h is None

        or df4h is None

    ):

        return None

    return {

        "15m": df15,

        "1h": df1h,

        "4h": df4h,

    }

# ============================================================

# HISTORICAL TREND AT TIMESTAMP

# ============================================================

def trend_at(df, timestamp):

    available = df[

        df["datetime"] <= timestamp

    ]

    if len(available) == 0:

        return "WAIT"

    row = available.iloc[-1]

    if (

        row["ema21"] > row["ema50"]

        and row["close"] > row["ema200"]

    ):

        return "BUY"

    if (

        row["ema21"] < row["ema50"]

        and row["close"] < row["ema200"]

    ):

        return "SELL"

    return "WAIT"

# ============================================================

# BACKTEST ENTRY

# ============================================================

def backtest_entry(

    data,

    i,

):

    df15 = data["15m"]

    df1h = data["1h"]

    df4h = data["4h"]

    if i < 2:

        return None

    row = df15.iloc[i]

    prev = df15.iloc[i - 1]

    timestamp = row["datetime"]

    trend4 = trend_at(

        df4h,

        timestamp,

    )

    trend1 = trend_at(

        df1h,

        timestamp,

    )

    # Higher timeframes must agree.

    if trend4 == "WAIT":

        return None

    if trend1 == "WAIT":

        return None

    if trend4 != trend1:

        return None

    # --------------------------------------------------------

    # BUY

    # --------------------------------------------------------

    buy = (

        row["ema21"] > row["ema50"]

        and row["close"] > row["ema200"]

        and 50 <= row["rsi"] <= 68

        and row["momentum"] > 0

        and row["close"] > prev["close"]

        and row["close"] > row["ema21"]

    )

    # --------------------------------------------------------

    # SELL

    # --------------------------------------------------------

    sell = (

        row["ema21"] < row["ema50"]

        and row["close"] < row["ema200"]

        and 32 <= row["rsi"] <= 50

        and row["momentum"] < 0

        and row["close"] < prev["close"]

        and row["close"] < row["ema21"]

    )

    if not buy and not sell:

        return None

    direction = (

        "BUY"

        if buy

        else "SELL"

    )

    entry = float(

        row["close"]

    )

    atr = float(

        row["atr"]

    )

    if not np.isfinite(atr):

        return None

    if atr <= 0:

        return None

    if direction == "BUY":

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

        "direction": direction,

        "signal_time": timestamp,

        "entry": entry,

        "sl": sl,

        "tp1": tp1,

        "tp2": tp2,

        "tp3": tp3,

        "atr": atr,

    }

# ============================================================

# CHECK TRADE

# ============================================================

def check_trade(

    df,

    start_index,

    trade,

):

    """

    Conservative rule:

    If TP and SL are both touched in

    the same candle, SL is assumed first.

    Backtest result is based on TP1.

    TP2/TP3 remain additional display targets.

    """

    direction = trade["direction"]

    for j in range(

        start_index + 1,

        len(df),

    ):

        candle = df.iloc[j]

        high = float(

            candle["high"]

        )

        low = float(

            candle["low"]

        )

        if direction == "BUY":

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

        # Conservative same-candle handling.

        if hit_sl and hit_tp:

            return {

                "result": "LOSS",

                "r": -1.0,

                "exit_time": candle[

                    "datetime"

                ],

                "exit": trade["sl"],

                "exit_index": j,

            }

        if hit_sl:

            return {

                "result": "LOSS",

                "r": -1.0,

                "exit_time": candle[

                    "datetime"

                ],

                "exit": trade["sl"],

                "exit_index": j,

            }

        if hit_tp:

            return {

                "result": "WIN",

                "r": TP1_ATR / SL_ATR,

                "exit_time": candle[

                    "datetime"

                ],

                "exit": trade["tp1"],

                "exit_index": j,

            }

    return {

        "result": "OPEN",

        "r": 0.0,

        "exit_time": None,

        "exit": None,

        "exit_index": len(df) - 1,

    }

# ============================================================

# RUN BACKTEST FOR ONE SYMBOL

# ============================================================

def run_backtest_symbol(symbol):

    data = prepare_backtest(

        symbol

    )

    if data is None:

        return []

    df15 = data["15m"]

    trades = []

    i = 2

    while i < len(df15) - 1:

        trade = backtest_entry(

            data,

            i,

        )

        if trade is None:

            i += 1

            continue

        result = check_trade(

            df15,

            i,

            trade,

        )

        if result["result"] == "OPEN":

            break

        trade.update(result)

        trades.append(trade)

        # Don't open another trade

        # while the previous one is active.

        i = result["exit_index"] + 1

    return trades

# ============================================================

# STATISTICS

# ============================================================

def calculate_stats(trades):

    if not trades:

        return {

            "total": 0,

            "wins": 0,

            "losses": 0,

            "win_rate": 0.0,

            "net_r": 0.0,

            "max_dd": 0.0,

            "max_loss_streak": 0,

        }

    wins = sum(

        1

        for t in trades

        if t["result"] == "WIN"

    )

    losses = sum(

        1

        for t in trades

        if t["result"] == "LOSS"

    )

    total = wins + losses

    win_rate = (

        wins / total * 100

        if total

        else 0

    )

    net_r = sum(

        t["r"]

        for t in trades

    )

    equity = 0.0

    peak = 0.0

    max_dd = 0.0

    losing_streak = 0

    max_loss_streak = 0

    for trade in trades:

        equity += trade["r"]

        peak = max(

            peak,

            equity,

        )

        drawdown = (

            peak - equity

        )

        max_dd = max(

            max_dd,

            drawdown,

        )

        if trade["result"] == "LOSS":

            losing_streak += 1

            max_loss_streak = max(

                max_loss_streak,

                losing_streak,

            )

        else:

            losing_streak = 0

    return {

        "total": total,

        "wins": wins,

        "losses": losses,

        "win_rate": win_rate,

        "net_r": net_r,

        "max_dd": max_dd,

        "max_loss_streak": max_loss_streak,

    }

# ============================================================

# FULL 90-DAY BACKTEST

# ============================================================

def run_full_backtest():

    start_time = time.time()

    lines = [

        "📊 90-DAY BACKTEST",

        "🧠 SAME LIVE STRATEGY",

        "4H → 1H → 15M",

        "━━━━━━━━━━━━━━━━━━",

        "",

    ]

    all_trades = []

    successful_symbols = 0

    for symbol in SYMBOLS:

        name = SYMBOLS[symbol]["name"]

        lines.append(

            f"⏳ Testing {name}..."

        )

        print(

            f"Starting backtest: "

            f"{symbol}"

        )

        try:

            trades = run_backtest_symbol(

                symbol

            )

            if trades is None:

                trades = []

            if trades:

                successful_symbols += 1

            stats = calculate_stats(

                trades

            )

            all_trades.extend(

                trades

            )

            lines.append(

                f"Trades: {stats['total']}"

            )

            lines.append(

                f"Wins: {stats['wins']} | "

                f"Losses: {stats['losses']}"

            )

            lines.append(

                f"Win rate: "

                f"{stats['win_rate']:.1f}%"

            )

            lines.append(

                f"Net: "

                f"{stats['net_r']:+.2f}R"

            )

            lines.append("")

        except Exception as e:

            print(

                f"SYMBOL BACKTEST ERROR "

                f"{symbol}: {e}"

            )

            lines.append(

                "⚠️ DATA/TEST ERROR"

            )

            lines.append("")

    # --------------------------------------------------------

    # Overall

    # --------------------------------------------------------

    overall = calculate_stats(

        all_trades

    )

    elapsed = (

        time.time()

        - start_time

    )

    lines.extend(

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

            f"{overall['win_rate']:.1f}%",

            f"Net result: "

            f"{overall['net_r']:+.2f}R",

            f"Max drawdown: "

            f"{overall['max_dd']:.2f}R",

            f"Max losing streak: "

            f"{overall['max_loss_streak']}",

            "",

            f"⏱ Backtest time: "

            f"{elapsed:.0f}s",

            "",

            "📊 Data: Twelve Data",

            "🏦 Broker: Lirunex MT5",

            "🖐 Execution: Manual",

            "",

            "⚠️ TP1 used as the backtest win target.",

            "⚠️ If TP and SL occur in the same candle,",

            "   SL is counted first.",

            "⚠️ Historical results do not guarantee",

            "   future performance.",

        ]

    )

    if successful_symbols == 0:

        lines.extend(

            [

                "",

                "❗ No valid symbol produced a backtest.",

                "Check Render logs for the exact",

                "Twelve Data API error.",

            ]

        )

    return "\n".join(lines)

# ============================================================

# TELEGRAM COMMANDS

# ============================================================

async def start_command(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE,

):

    text = (

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

        "/test - Telegram test\n"

        "/market - Market report\n"

        "/signal - Confirmed signals\n"

        "/backtest - 90-day backtest"

    )

    await update.message.reply_text(

        text

    )

async def status_command(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE,

):

    await update.message.reply_text(

        "🟢 BOT ONLINE\n\n"

        "Strategy: 4H → 1H → 15M\n"

        "Risk model: ATR\n"

        "SL: 1.2 ATR\n"

        "TP1: 1.5 ATR\n"

        "TP2: 2.5 ATR\n"

        "TP3: 3.5 ATR\n\n"

        "Scanner: every 5 minutes\n"

        "Execution: Manual MT5"

    )

async def test_command(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE,

):

    await update.message.reply_text(

        "✅ Telegram test successful.\n"

        "Bot communication is working."

    )

async def market_command(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE,

):

    await update.message.reply_text(

        "⏳ Checking market..."

    )

    report = market_report()

    await update.message.reply_text(

        report

    )

async def signal_command(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE,

):

    await update.message.reply_text(

        "⏳ Checking confirmed signals..."

    )

    found = 0

    for symbol in SYMBOLS:

        result = analyze_symbol(

            symbol

        )

        if result.get(

            "signal"

        ) in [

            "BUY",

            "SELL",

        ]:

            message = signal_message(

                symbol,

                result,

            )

            if message:

                await update.message.reply_text(

                    message

                )

                found += 1

        time.sleep(2)

    if found == 0:

        await update.message.reply_text(

            "⚪ No confirmed signal right now.\n\n"

            "4H → 1H → 15M confirmation "

            "is not complete."

        )

async def backtest_command(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE,

):

    await update.message.reply_text(

        "⏳ 90-day backtest started.\n"

        "This may take a few minutes because "

        "historical data is downloaded in chunks."

    )

    try:

        result = run_full_backtest()

        # Telegram has message-size limits.

        if len(result) > 3900:

            result = result[

                :3900

            ]

        await update.message.reply_text(

            result

        )

    except Exception as e:

        print(

            "BACKTEST COMMAND ERROR:",

            e,

        )

        await update.message.reply_text(

            "❌ Backtest error.\n\n"

            f"{str(e)[:1000]}"

        )

# ============================================================

# TEXT COMMANDS

# ============================================================

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

        await market_command(

            update,

            context,

        )

    elif text == "signal":

        await signal_command(

            update,

            context,

        )

    elif text == "backtest":

        await backtest_command(

            update,

            context,

        )

    elif text == "status":

        await status_command(

            update,

            context,

        )

# ============================================================

# TELEGRAM APP

# ============================================================

def telegram_loop():

    print(

        "Starting Telegram bot..."

    )

    application = (

        Application.builder()

        .token(BOT_TOKEN)

        .build()

    )

    application.add_handler(

        CommandHandler(

            "start",

            start_command,

        )

    )

    application.add_handler(

        CommandHandler(

            "status",

            status_command,

        )

    )

    application.add_handler(

        CommandHandler(

            "test",

            test_command,

        )

    )

    application.add_handler(

        CommandHandler(

            "market",

            market_command,

        )

    )

    application.add_handler(

        CommandHandler(

            "signal",

            signal_command,

        )

    )

    application.add_handler(

        CommandHandler(

            "backtest",

            backtest_command,

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

        "Telegram polling started."

    )

    application.run_polling(

        drop_pending_updates=True

    )

# ============================================================

# MAIN

# ============================================================

if __name__ == "__main__":

    print(

        "================================"

    )

    print(

        "ADIL PRO MARKET MOOD v14"

    )

    print(

        "Starting..."

    )

    print(

        "================================"

    )

    # Flask

    threading.Thread(

        target=flask_loop,

        daemon=True,

    ).start()

    # Scanner

    threading.Thread(

        target=scanner_loop,

        daemon=True,

    ).start()

    # Telegram

    telegram_loop()
