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

TOKEN = os.getenv("BOT_TOKEN")

CHAT_ID = os.getenv("CHAT_ID")

TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")

SCAN_INTERVAL = 300

EMA_FAST = 21

EMA_MID = 50

EMA_SLOW = 200

RSI_PERIOD = 14

ATR_PERIOD = 14

MOMENTUM_PERIOD = 5

SL_ATR = 1.2

TP1_ATR = 1.5

TP2_ATR = 2.5

TP3_ATR = 3.5

SYMBOLS = {

    "XAU/USD": {

        "broker": "XAUUSD.r",

        "name": "🥇 GOLD",

    },

    "EUR/USD": {

        "broker": "EURUSD.r",

        "name": "💱 EUR",

    },

    "BTC/USD": {

        "broker": "BTCUSD.r",

        "name": "₿ BTC",

    },

}

last_sent_signals = {}

# ============================================================

# FLASK

# ============================================================

flask_app = Flask(__name__)

@flask_app.route("/")

def home():

    return "ADIL CONFIRMED STRATEGY v15 LIVE"

@flask_app.route("/health")

def health():

    return "OK"

def run_flask():

    port = int(os.environ.get("PORT", 10000))

    flask_app.run(

        host="0.0.0.0",

        port=port

    )

# ============================================================

# TELEGRAM

# ============================================================

def send_telegram(message):

    if not TOKEN or not CHAT_ID:

        print("Telegram config missing")

        return False

    try:

        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

        r = requests.post(

            url,

            data={

                "chat_id": CHAT_ID,

                "text": message,

            },

            timeout=20,

        )

        if r.ok:

            return True

        print("Telegram error:", r.text)

        return False

    except Exception as e:

        print("Telegram exception:", e)

        return False

# ============================================================

# TWELVE DATA

# ============================================================

def get_candles(

    symbol,

    interval,

    outputsize=5000

):

    url = "https://api.twelvedata.com/time_series"

    params = {

        "symbol": symbol,

        "interval": interval,

        "outputsize": outputsize,

        "apikey": TWELVE_DATA_API_KEY,

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

                f"DATA ERROR {symbol} {interval}: "

                f"{data.get('message', data)}"

            )

            return None

        df = pd.DataFrame(data["values"])

        if df.empty:

            return None

        df["datetime"] = pd.to_datetime(

            df["datetime"]

        )

        for col in [

            "open",

            "high",

            "low",

            "close",

        ]:

            df[col] = pd.to_numeric(

                df[col],

                errors="coerce"

            )

        df = (

            df.sort_values("datetime")

            .dropna(

                subset=[

                    "open",

                    "high",

                    "low",

                    "close",

                ]

            )

            .reset_index(drop=True)

        )

        if len(df) < 250:

            return None

        # Remove currently forming candle.

        df = df.iloc[:-1].copy()

        return df.reset_index(drop=True)

    except Exception as e:

        print(

            f"get_candles error "

            f"{symbol} {interval}: {e}"

        )

        return None

# ============================================================

# INDICATORS

# ============================================================

def add_indicators(df):

    df = df.copy()

    df["ema21"] = df["close"].ewm(

        span=EMA_FAST,

        adjust=False

    ).mean()

    df["ema50"] = df["close"].ewm(

        span=EMA_MID,

        adjust=False

    ).mean()

    df["ema200"] = df["close"].ewm(

        span=EMA_SLOW,

        adjust=False

    ).mean()

    delta = df["close"].diff()

    gain = delta.clip(lower=0)

    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(

        alpha=1 / RSI_PERIOD,

        adjust=False

    ).mean()

    avg_loss = loss.ewm(

        alpha=1 / RSI_PERIOD,

        adjust=False

    ).mean()

    rs = avg_gain / avg_loss.replace(

        0,

        np.nan

    )

    df["rsi"] = 100 - (

        100 / (1 + rs)

    )

    previous_close = df["close"].shift(1)

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

        df["close"].pct_change(

            MOMENTUM_PERIOD

        ) * 100

    )

    return (

        df.dropna()

        .reset_index(drop=True)

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

# 15M ENTRY

# ============================================================

def entry_confirmation(df):

    if df is None or len(df) < 3:

        return "WAIT"

    row = df.iloc[-1]

    prev = df.iloc[-2]

    price = row["close"]

    buy = [

        row["ema21"] > row["ema50"],

        price > row["ema200"],

        50 <= row["rsi"] <= 68,

        row["momentum"] > 0,

        price > prev["close"],

        price > row["ema21"],

    ]

    sell = [

        row["ema21"] < row["ema50"],

        price < row["ema200"],

        32 <= row["rsi"] <= 50,

        row["momentum"] < 0,

        price < prev["close"],

        price < row["ema21"],

    ]

    buy_score = sum(buy)

    sell_score = sum(sell)

    if buy_score == 6:

        return "BUY"

    if sell_score == 6:

        return "SELL"

    return "WAIT"

# ============================================================

# ANALYZE ONE SYMBOL

# ============================================================

def analyze_symbol(symbol):

    frames = {}

    for interval in [

        "4h",

        "1h",

        "15min",

    ]:

        df = get_candles(

            symbol,

            interval

        )

        if df is None:

            return {

                "status": "DATA ERROR",

                "error": True,

            }

        df = add_indicators(df)

        if df.empty:

            return {

                "status": "DATA ERROR",

                "error": True,

            }

        frames[interval] = df

    trend4 = timeframe_trend(

        frames["4h"]

    )

    trend1 = timeframe_trend(

        frames["1h"]

    )

    trend15 = timeframe_trend(

        frames["15min"]

    )

    # Higher timeframe agreement

    if (

        trend4 not in ["BUY", "SELL"]

        or trend1 != trend4

        or trend15 != trend4

    ):

        return {

            "status": "WAIT",

            "trend4": trend4,

            "trend1": trend1,

            "trend15": trend15,

        }

    entry = entry_confirmation(

        frames["15min"]

    )

    if entry != trend4:

        return {

            "status": "WAIT",

            "trend4": trend4,

            "trend1": trend1,

            "trend15": trend15,

        }

    row = frames["15min"].iloc[-1]

    price = float(row["close"])

    atr = float(row["atr"])

    if entry == "BUY":

        sl = price - atr * SL_ATR

        tp1 = price + atr * TP1_ATR

        tp2 = price + atr * TP2_ATR

        tp3 = price + atr * TP3_ATR

    else:

        sl = price + atr * SL_ATR

        tp1 = price - atr * TP1_ATR

        tp2 = price - atr * TP2_ATR

        tp3 = price - atr * TP3_ATR

    return {

        "status": f"CONFIRMED {entry}",

        "direction": entry,

        "trend4": trend4,

        "trend1": trend1,

        "trend15": trend15,

        "entry": price,

        "atr": atr,

        "rsi": float(row["rsi"]),

        "momentum": float(

            row["momentum"]

        ),

        "sl": sl,

        "tp1": tp1,

        "tp2": tp2,

        "tp3": tp3,

        "time": row["datetime"],

    }

# ============================================================

# PRICE FORMAT

# ============================================================

def fmt_price(value):

    if value is None:

        return "N/A"

    value = float(value)

    if value >= 1000:

        return f"{value:.2f}"

    if value >= 10:

        return f"{value:.4f}"

    return f"{value:.5f}"

# ============================================================

# MARKET COMMAND

# ============================================================

def market_report():

    lines = [

        "💎 ADIL MARKET",

        "🧠 4H → 1H → 15M",

        "━━━━━━━━━━━━━━━━━━",

        "",

    ]

    for symbol, info in SYMBOLS.items():

        result = analyze_symbol(symbol)

        lines.append(

            f"{info['name']} "

            f"({info['broker']})"

        )

        if result.get("error"):

            lines.append(

                "⚠️ DATA ERROR"

            )

            lines.append("")

            continue

        if result["status"].startswith(

            "CONFIRMED"

        ):

            direction = result["direction"]

            emoji = (

                "🟢"

                if direction == "BUY"

                else "🔴"

            )

            lines.append(

                f"{emoji} {result['status']}"

            )

            lines.append(

                f"4H {result['trend4']} | "

                f"1H {result['trend1']} | "

                f"15M {result['trend15']}"

            )

            lines.append(

                f"Entry: "

                f"{fmt_price(result['entry'])}"

            )

            lines.append(

                f"TP1: "

                f"{fmt_price(result['tp1'])}"

            )

            lines.append(

                f"TP2: "

                f"{fmt_price(result['tp2'])}"

            )

            lines.append(

                f"TP3: "

                f"{fmt_price(result['tp3'])}"

            )

            lines.append(

                f"SL: "

                f"{fmt_price(result['sl'])}"

            )

            lines.append(

                f"RSI: "

                f"{result['rsi']:.1f}"

            )

        else:

            lines.append(

                "⚪ WAIT"

            )

            lines.append(

                f"4H {result.get('trend4', 'WAIT')} | "

                f"1H {result.get('trend1', 'WAIT')} | "

                f"15M {result.get('trend15', 'WAIT')}"

            )

        lines.append("")

    lines.extend([

        "━━━━━━━━━━━━━━━━━━",

        "📊 Data: Twelve Data public feed",

        "🏦 Broker: Lirunex MT5",

        "🖐 Execution: Manual",

        "",

        "⚠️ Twelve Data price may differ",

        "from Lirunex MT5.",

    ])

    return "\n".join(lines)

# ============================================================

# SIGNAL MESSAGE

# ============================================================

def signal_message(

    symbol,

    info,

    result

):

    direction = result["direction"]

    emoji = (

        "🟢"

        if direction == "BUY"

        else "🔴"

    )

    return (

        f"{emoji}🔥 CONFIRMED {direction}\n\n"

        f"{info['name']} "

        f"({info['broker']})\n\n"

        f"4H: {result['trend4']} ✅\n"

        f"1H: {result['trend1']} ✅\n"

        f"15M: {result['trend15']} ✅\n\n"

        f"Entry: {fmt_price(result['entry'])}\n"

        f"TP1: {fmt_price(result['tp1'])}\n"

        f"TP2: {fmt_price(result['tp2'])}\n"

        f"TP3: {fmt_price(result['tp3'])}\n"

        f"SL: {fmt_price(result['sl'])}\n\n"

        f"RSI: {result['rsi']:.1f}\n"

        f"Momentum: "

        f"{result['momentum']:.2f}%\n\n"

        f"📊 Data: Twelve Data public feed\n"

        f"🏦 Broker: Lirunex MT5\n"

        f"🖐 Execution: Manual\n\n"

        f"⚠️ Public feed price may differ "

        f"from Lirunex MT5."

    )

# ============================================================

# AUTO SCANNER

# ============================================================

def scanner_loop():

    print("🟢 AUTO SCANNER STARTED")

    while True:

        try:

            for symbol, info in SYMBOLS.items():

                result = analyze_symbol(

                    symbol

                )

                if not result.get(

                    "status",

                    ""

                ).startswith(

                    "CONFIRMED"

                ):

                    continue

                candle_time = str(

                    result["time"]

                )

                key = (

                    symbol,

                    result["direction"],

                    candle_time,

                )

                # Don't send same signal twice

                if last_sent_signals.get(

                    symbol

                ) == key:

                    continue

                last_sent_signals[

                    symbol

                ] = key

                send_telegram(

                    signal_message(

                        symbol,

                        info,

                        result

                    )

                )

                print(

                    "SIGNAL SENT:",

                    symbol,

                    result["direction"]

                )

                time.sleep(2)

        except Exception as e:

            print(

                "Scanner error:",

                e

            )

        time.sleep(

            SCAN_INTERVAL

        )

# ============================================================

# BACKTEST HELPERS

# ============================================================

def get_backtest_data(

    symbol,

    interval,

    days=90

):

    """

    Twelve Data historical candles.

    15M needs about 8640 candles for 90 days.

    """

    outputsize = {

        "15min": 9000,

        "1h": 2500,

        "4h": 700,

    }[interval]

    url = (

        "https://api.twelvedata.com/"

        "time_series"

    )

    params = {

        "symbol": symbol,

        "interval": interval,

        "outputsize": outputsize,

        "apikey": TWELVE_DATA_API_KEY,

        "format": "JSON",

    }

    try:

        r = requests.get(

            url,

            params=params,

            timeout=60

        )

        data = r.json()

        if "values" not in data:

            print(

                "Backtest data error:",

                symbol,

                interval,

                data

            )

            return None

        df = pd.DataFrame(

            data["values"]

        )

        df["datetime"] = pd.to_datetime(

            df["datetime"]

        )

        for col in [

            "open",

            "high",

            "low",

            "close",

        ]:

            df[col] = pd.to_numeric(

                df[col],

                errors="coerce"

            )

        df = (

            df.sort_values("datetime")

            .dropna(

                subset=[

                    "open",

                    "high",

                    "low",

                    "close",

                ]

            )

            .reset_index(drop=True)

        )

        # Remove current incomplete candle

        if len(df) > 2:

            df = df.iloc[:-1]

        cutoff = (

            pd.Timestamp.utcnow()

            - pd.Timedelta(

                days=days

            )

        )

        df = df[

            df["datetime"] >= cutoff

        ]

        return (

            df.reset_index(drop=True)

        )

    except Exception as e:

        print(

            "Backtest fetch error:",

            symbol,

            interval,

            e

        )

        return None

# ============================================================

# PREPARE BACKTEST DATA

# ============================================================

def prepare_backtest(symbol):

    print(

        f"Downloading {symbol}..."

    )

    data15 = get_backtest_data(

        symbol,

        "15min",

        90

    )

    time.sleep(2)

    data1h = get_backtest_data(

        symbol,

        "1h",

        90

    )

    time.sleep(2)

    data4h = get_backtest_data(

        symbol,

        "4h",

        90

    )

    if (

        data15 is None

        or data1h is None

        or data4h is None

    ):

        return None

    data15 = add_indicators(

        data15

    )

    data1h = add_indicators(

        data1h

    )

    data4h = add_indicators(

        data4h

    )

    return {

        "15m": data15,

        "1h": data1h,

        "4h": data4h,

    }

# ============================================================

# BACKTEST TREND AT TIMESTAMP

# ============================================================

def trend_at(

    df,

    timestamp

):

    available = df[

        df["datetime"] <= timestamp

    ]

    if available.empty:

        return "WAIT", None

    row = available.iloc[-1]

    if (

        row["ema21"] > row["ema50"]

        and row["close"] > row["ema200"]

    ):

        return "BUY", row

    if (

        row["ema21"] < row["ema50"]

        and row["close"] < row["ema200"]

    ):

        return "SELL", row

    return "WAIT", row

# ============================================================

# BACKTEST ENTRY

# ============================================================

def backtest_entry(

    data,

    i

):

    df15 = data["15m"]

    row = df15.iloc[i]

    timestamp = row["datetime"]

    trend4, row4 = trend_at(

        data["4h"],

        timestamp

    )

    trend1, row1 = trend_at(

        data["1h"],

        timestamp

    )

    if (

        trend4 not in ["BUY", "SELL"]

        or trend1 != trend4

    ):

        return None

    price = row["close"]

    buy = [

        row["ema21"] > row["ema50"],

        price > row["ema200"],

        50 <= row["rsi"] <= 68,

        row["momentum"] > 0,

        price > df15.iloc[i - 1]["close"],

        price > row["ema21"],

    ]

    sell = [

        row["ema21"] < row["ema50"],

        price < row["ema200"],

        32 <= row["rsi"] <= 50,

        row["momentum"] < 0,

        price < df15.iloc[i - 1]["close"],

        price < row["ema21"],

    ]

    if (

        trend4 == "BUY"

        and all(buy)

    ):

        direction = "BUY"

    elif (

        trend4 == "SELL"

        and all(sell)

    ):

        direction = "SELL"

    else:

        return None

    atr = float(row["atr"])

    if direction == "BUY":

        sl = price - atr * SL_ATR

        tp1 = price + atr * TP1_ATR

        tp2 = price + atr * TP2_ATR

        tp3 = price + atr * TP3_ATR

    else:

        sl = price + atr * SL_ATR

        tp1 = price - atr * TP1_ATR

        tp2 = price - atr * TP2_ATR

        tp3 = price - atr * TP3_ATR

    return {

        "time": timestamp,

        "direction": direction,

        "entry": price,

        "sl": sl,

        "tp1": tp1,

        "tp2": tp2,

        "tp3": tp3,

    }

# ============================================================

# CHECK TRADE RESULT

# ============================================================

def check_trade(

    df,

    start_index,

    trade

):

    direction = trade["direction"]

    for j in range(

        start_index + 1,

        len(df)

    ):

        candle = df.iloc[j]

        high = candle["high"]

        low = candle["low"]

        if direction == "BUY":

            # Conservative:

            # If TP and SL hit same candle,

            # count SL first.

            if low <= trade["sl"]:

                return {

                    "result": "SL",

                    "r": -1.0,

                    "exit_time":

                        candle["datetime"],

                }

            if high >= trade["tp1"]:

                return {

                    "result": "TP1",

                    "r": TP1_ATR / SL_ATR,

                    "exit_time":

                        candle["datetime"],

                }

        else:

            if high >= trade["sl"]:

                return {

                    "result": "SL",

                    "r": -1.0,

                    "exit_time":

                        candle["datetime"],

                }

            if low <= trade["tp1"]:

                return {

                    "result": "TP1",

                    "r": TP1_ATR / SL_ATR,

                    "exit_time":

                        candle["datetime"],

                }

    return {

        "result": "OPEN",

        "r": 0.0,

        "exit_time": None,

    }

# ============================================================

# RUN BACKTEST

# ============================================================

def run_backtest_symbol(

    symbol

):

    data = prepare_backtest(

        symbol

    )

    if data is None:

        return None

    df15 = data["15m"]

    trades = []

    i = 1

    while i < len(df15) - 2:

        trade = backtest_entry(

            data,

            i

        )

        if trade is None:

            i += 1

            continue

        outcome = check_trade(

            df15,

            i,

            trade

        )

        trade.update(

            outcome

        )

        trades.append(trade)

        # Don't immediately open another trade.

        # Move to after the trade exit.

        exit_time = outcome.get(

            "exit_time"

        )

        if exit_time is not None:

            future = df15[

                df15["datetime"]

                > exit_time

            ]

            if not future.empty:

                i = future.index[0]

            else:

                break

        else:

            break

    return trades

# ============================================================

# BACKTEST STATISTICS

# ============================================================

def calculate_stats(

    trades

):

    if not trades:

        return {

            "trades": 0,

            "wins": 0,

            "losses": 0,

            "win_rate": 0,

            "net_r": 0,

            "max_dd": 0,

            "max_loss_streak": 0,

        }

    wins = sum(

        1

        for t in trades

        if t["result"] != "SL"

        and t["result"] != "OPEN"

    )

    losses = sum(

        1

        for t in trades

        if t["result"] == "SL"

    )

    closed = wins + losses

    win_rate = (

        wins / closed * 100

        if closed

        else 0

    )

    equity = 0

    peak = 0

    max_dd = 0

    losing_streak = 0

    max_losing_streak = 0

    for trade in trades:

        equity += trade["r"]

        peak = max(

            peak,

            equity

        )

        dd = peak - equity

        max_dd = max(

            max_dd,

            dd

        )

        if trade["result"] == "SL":

            losing_streak += 1

            max_losing_streak = max(

                max_losing_streak,

                losing_streak

            )

        else:

            losing_streak = 0

    return {

        "trades": len(trades),

        "wins": wins,

        "losses": losses,

        "win_rate": win_rate,

        "net_r": equity,

        "max_dd": max_dd,

        "max_loss_streak":

            max_losing_streak,

    }

# ============================================================

# FULL 90-DAY BACKTEST

# ============================================================

def run_full_backtest():

    start = time.time()

    lines = [

        "📊 90-DAY BACKTEST",

        "🧠 Same live strategy",

        "4H → 1H → 15M",

        "━━━━━━━━━━━━━━━━━━",

        "",

    ]

    all_trades = []

    for symbol, info in SYMBOLS.items():

        lines.append(

            f"⏳ Testing {info['name']}..."

        )

        trades = run_backtest_symbol(

            symbol

        )

        if trades is None:

            lines.append(

                "⚠️ DATA ERROR"

            )

            lines.append("")

            continue

        stats = calculate_stats(

            trades

        )

        all_trades.extend(

            trades

        )

        lines.append(

            f"{info['name']}"

        )

        lines.append(

            f"Trades: {stats['trades']}"

        )

        lines.append(

            f"✅ Wins: {stats['wins']}"

        )

        lines.append(

            f"❌ Losses: {stats['losses']}"

        )

        lines.append(

            f"🎯 Win rate: "

            f"{stats['win_rate']:.1f}%"

        )

        lines.append(

            f"💰 Net R: "

            f"{stats['net_r']:.2f}R"

        )

        lines.append(

            f"📉 Max DD: "

            f"{stats['max_dd']:.2f}R"

        )

        lines.append(

            f"🔥 Max losing streak: "

            f"{stats['max_loss_streak']}"

        )

        lines.append("")

        # Conservative pause for public API

        time.sleep(3)

    overall = calculate_stats(

        all_trades

    )

    elapsed = time.time() - start

    lines.extend([

        "━━━━━━━━━━━━━━━━━━",

        "🏆 OVERALL",

        "",

        f"Total trades: "

        f"{overall['trades']}",

        f"Wins: "

        f"{overall['wins']}",

        f"Losses: "

        f"{overall['losses']}",

        f"Win rate: "

        f"{overall['win_rate']:.1f}%",

        f"Net result: "

        f"{overall['net_r']:.2f}R",

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

        "⚠️ Backtest is historical analysis,",

        "not a guarantee of future profit.",

    ])

    return "\n".join(lines)

# ============================================================

# TELEGRAM COMMANDS

# ============================================================

async def start_command(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE

):

    await update.message.reply_text(

        "🟢 ADIL CONFIRMED STRATEGY v15\n\n"

        "4H → 1H → 15M\n"

        "Closed-candle confirmation\n\n"

        "Commands:\n"

        "/market - Current market\n"

        "/signal - Confirmed signals\n"

        "/backtest - 90-day backtest\n"

        "/status - Bot status\n"

        "/test - Telegram test"

    )

async def status_command(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE

):

    await update.message.reply_text(

        "🟢 BOT ONLINE\n\n"

        "Strategy: 4H → 1H → 15M\n"

        "Mode: Manual execution\n"

        "Scanner: 5 minutes\n"

        "Backtest: 90 days"

    )

async def test_command(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE

):

    await update.message.reply_text(

        "✅ Telegram test successful."

    )

async def market_command(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE

):

    await update.message.reply_text(

        "🔎 Checking market..."

    )

    try:

        message = market_report()

        await update.message.reply_text(

            message

        )

    except Exception as e:

        await update.message.reply_text(

            f"⚠️ Error:\n{e}"

        )

async def signal_command(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE

):

    await update.message.reply_text(

        "🔎 Checking confirmed signals..."

    )

    try:

        found = False

        for symbol, info in SYMBOLS.items():

            result = analyze_symbol(

                symbol

            )

            if result.get(

                "status",

                ""

            ).startswith(

                "CONFIRMED"

            ):

                found = True

                await update.message.reply_text(

                    signal_message(

                        symbol,

                        info,

                        result

                    )

                )

        if not found:

            await update.message.reply_text(

                "⚪ No confirmed signal right now.\n"

                "WAIT."

            )

    except Exception as e:

        await update.message.reply_text(

            f"⚠️ Signal error:\n{e}"

        )

async def backtest_command(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE

):

    await update.message.reply_text(

        "⏳ 90-day backtest started.\n\n"

        "Testing GOLD + EURUSD + BTC...\n"

        "Ismein kuch time lag sakta hai."

    )

    try:

        result = await __import__(

            "asyncio"

        ).to_thread(

            run_full_backtest

        )

        # Telegram message limit protection

        if len(result) > 3900:

            parts = [

                result[i:i + 3900]

                for i in range(

                    0,

                    len(result),

                    3900

                )

            ]

            for part in parts:

                await update.message.reply_text(

                    part

                )

        else:

            await update.message.reply_text(

                result

            )

    except Exception as e:

        await update.message.reply_text(

            f"❌ Backtest error:\n{e}"

        )

async def text_handler(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE

):

    text = (

        update.message.text

        .strip()

        .lower()

    )

    if text == "market":

        await market_command(

            update,

            context

        )

    elif text in [

        "signal",

        "signals",

    ]:

        await signal_command(

            update,

            context

        )

    elif text in [

        "backtest",

        "test strategy",

    ]:

        await backtest_command(

            update,

            context

        )

    elif text in [

        "status",

        "bot status",

    ]:

        await status_command(

            update,

            context

        )

    elif text == "mood":

        await market_command(

            update,

            context

        )

# ============================================================

# TELEGRAM START

# ============================================================

def start_telegram():

    application = (

        Application.builder()

        .token(TOKEN)

        .build()

    )

    application.add_handler(

        CommandHandler(

            "start",

            start_command

        )

    )

    application.add_handler(

        CommandHandler(

            "status",

            status_command

        )

    )

    application.add_handler(

        CommandHandler(

            "test",

            test_command

        )

    )

    application.add_handler(

        CommandHandler(

            "market",

            market_command

        )

    )

    application.add_handler(

        CommandHandler(

            "signal",

            signal_command

        )

    )

    application.add_handler(

        CommandHandler(

            "backtest",

            backtest_command

        )

    )

    application.add_handler(

        MessageHandler(

            filters.TEXT

            & ~filters.COMMAND,

            text_handler

        )

    )

    print(

        "🟢 TELEGRAM BOT STARTED"

    )

    application.run_polling()

# ============================================================

# MAIN

# ============================================================

if __name__ == "__main__":

    threading.Thread(

        target=run_flask,

        daemon=True

    ).start()

    print(

        "🟢 ADIL CONFIRMED STRATEGY v15 LIVE"

    )

    print(

        "📊 4H → 1H → 15M"

    )

    print(

        "🥇 GOLD | 💱 EUR | ₿ BTC"

    )

    print(

        "📈 90-day automatic backtest"

    )

    threading.Thread(

        target=scanner_loop,

        daemon=True

    ).start()

    start_telegram()
