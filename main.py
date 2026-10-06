import os
import json
import asyncio
import logging
import threading
from bisect import bisect_right
from datetime import datetime, timezone

import requests
from flask import Flask
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ============================================================
# ADIL v18 PRO PAPER ENGINE
# PAPER SIGNALS ONLY - NO REAL ORDERS
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN missing")

if not CHAT_ID:
    raise RuntimeError("CHAT_ID missing")


# ============================================================
# CONFIG
# ============================================================

SYMBOLS = {
    "BTCUSDT": "BTC",
    "PAXGUSDT": "GOLD",
}

SIGNAL_TF = "15m"
HTF1 = "1h"
HTF2 = "4h"
MONITOR_TF = "1m"

SIGNAL_LIMIT = 1000
HTF_LIMIT = 500
MONITOR_LIMIT = 10

MAX_SIGNALS_PER_DAY = 2

# $2 risk per trade.
# Daily stop = $4.
RISK_PER_TRADE_USD = 2.0
MAX_DAILY_LOSS_USD = 4.0

# Backtest requirements
MIN_SAMPLE = 40
MIN_WIN_RATE = 60.0
MIN_EXPECTANCY_R = 0.15

# Backtest horizon
BACKTEST_HORIZON = 10

# Trading costs used ONLY in paper/backtest accounting.
FEE_RATE = 0.001       # 0.10% each side
SLIPPAGE_RATE = 0.0003 # 0.03% each side

# Strategy
SL_ATR = 1.0
TP1_ATR = 1.5
TP2_ATR = 2.5

# After TP1:
# 50% position closed at TP1.
# Remaining 50% SL moves to entry.
TP1_PARTIAL = 0.50

# Volume confirmation
VOLUME_MULTIPLIER = 1.10

# RSI
SELL_RSI_MIN = 35
SELL_RSI_MAX = 55

BUY_RSI_MIN = 45
BUY_RSI_MAX = 65

# Polling
SCANNER_SECONDS = 20
MONITOR_SECONDS = 10


# ============================================================
# FLASK HEALTH SERVER
# ============================================================

flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "Adil v18 PRO PAPER ENGINE LIVE"


# ============================================================
# STATE
# ============================================================

STATE_FILE = "v18_state.json"


def default_state():
    return {
        "date": str(datetime.now(timezone.utc).date()),
        "signals_today": 0,
        "loss_today_usd": 0.0,
        "last_signal_candle": {},
        "active": {},
        "stats": {
            "wins": 0,
            "losses": 0,
            "breakeven": 0,
            "signals": 0,
            "pnl_r": 0.0,
            "pnl_usd": 0.0,
        },
        "history": [],
    }


def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            s = json.load(f)

        base = default_state()

        # Defensive migration for older state files
        for key, value in base.items():
            if key not in s:
                s[key] = value

        for key, value in base["stats"].items():
            if key not in s["stats"]:
                s["stats"][key] = value

        return s

    except Exception:
        return default_state()


state = load_state()


def save_state():
    tmp = STATE_FILE + ".tmp"

    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)

    os.replace(tmp, STATE_FILE)


def reset_daily_state_if_needed():
    today = str(datetime.now(timezone.utc).date())

    if state["date"] != today:
        state["date"] = today
        state["signals_today"] = 0
        state["loss_today_usd"] = 0.0
        save_state()


# ============================================================
# BINANCE REST
# ============================================================

BINANCE_URL = "https://api.binance.com/api/v3"


def http_get(path, params=None):
    url = BINANCE_URL + path

    r = requests.get(
        url,
        params=params,
        timeout=10,
    )

    r.raise_for_status()

    data = r.json()

    if isinstance(data, dict) and "code" in data:
        raise RuntimeError(str(data))

    return data


def get_klines_sync(symbol, interval, limit):
    return http_get(
        "/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
    )


def get_ticker_sync(symbol):
    return http_get(
        "/ticker/price",
        {"symbol": symbol}
    )


# Binance's ticker endpoint returns latest price.
# We use it only for informational fallback.
def get_live_price_sync(symbol):
    data = get_ticker_sync(symbol)
    return float(data["price"])


# ============================================================
# CLOSED CANDLES
# ============================================================

def get_closed_klines_sync(symbol, interval, limit):
    data = get_klines_sync(symbol, interval, limit)

    now_ms = int(
        datetime.now(timezone.utc).timestamp() * 1000
    )

    # Binance kline:
    # [0] open time
    # [2] high
    # [3] low
    # [4] close
    # [5] volume
    # [6] close time

    return [
        k for k in data
        if int(k[6]) < now_ms
    ]


async def get_closed_klines(symbol, interval, limit):
    return await asyncio.to_thread(
        get_closed_klines_sync,
        symbol,
        interval,
        limit
    )


# ============================================================
# PARSER
# ============================================================

def parse(klines):
    return {
        "open": [float(k[1]) for k in klines],
        "high": [float(k[2]) for k in klines],
        "low": [float(k[3]) for k in klines],
        "close": [float(k[4]) for k in klines],
        "vol": [float(k[5]) for k in klines],
        "ot": [int(k[0]) for k in klines],
        "ct": [int(k[6]) for k in klines],
    }


# ============================================================
# INDICATORS
# ============================================================

def ema(values, period):
    if len(values) < period:
        return None

    e = sum(values[:period]) / period
    alpha = 2 / (period + 1)

    for value in values[period:]:
        e = value * alpha + e * (1 - alpha)

    return e


def rsi(values, period=14):
    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]

        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100.0 - (100.0 / (1.0 + rs))


def atr(high, low, close, period=14):
    if len(close) < period + 1:
        return None

    tr = []

    for i in range(1, len(close)):
        true_range = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )

        tr.append(true_range)

    return sum(tr[-period:]) / period


# ============================================================
# EXACT HTF ALIGNMENT
# ============================================================

def htf_index_for_time(htf_close_times, timestamp):
    """
    Return the latest HTF candle whose CLOSE TIME
    is <= the 15m candle close time.

    This prevents future HTF information from leaking
    into the historical 15m signal.
    """

    idx = bisect_right(
        htf_close_times,
        timestamp
    ) - 1

    return idx


def get_htf_snapshot(d15_ct, dhtf):
    """
    For every 15m candle, find the exact already-closed
    HTF candle available at that moment.
    """

    result = []

    times = dhtf["ct"]

    for t in d15_ct:
        idx = htf_index_for_time(times, t)

        if idx < 0:
            result.append(None)
        else:
            result.append(idx)

    return result


# ============================================================
# STRATEGY
# ============================================================

def strategy_signal(
    i,
    d15,
    d1h,
    d4h,
):
    """
    Evaluate strategy at 15m candle i.

    IMPORTANT:
    i represents a CLOSED 15m candle.

    HTF candles are selected strictly by timestamp.
    """

    c = d15["close"]
    h = d15["high"]
    l = d15["low"]
    v = d15["vol"]
    ct = d15["ct"]

    if i < 210:
        return None

    pc = c[:i + 1]
    ph = h[:i + 1]
    pl = l[:i + 1]

    e21 = ema(pc, 21)
    e50 = ema(pc, 50)
    e200 = ema(pc, 200)

    r = rsi(pc)
    atr_v = atr(ph, pl, pc)

    if None in [e21, e50, e200, r, atr_v]:
        return None

    if atr_v <= 0:
        return None

    # Exact HTF alignment
    idx1 = htf_index_for_time(
        d1h["ct"],
        ct[i]
    )

    idx4 = htf_index_for_time(
        d4h["ct"],
        ct[i]
    )

    if idx1 < 49 or idx4 < 49:
        return None

    c1 = d1h["close"][:idx1 + 1]
    c4 = d4h["close"][:idx4 + 1]

    e50_1h = ema(c1, 50)
    e50_4h = ema(c4, 50)

    if e50_1h is None or e50_4h is None:
        return None

    price = c[i]

    # Volume uses only candles available at this point
    vol_window = v[max(0, i - 20):i]

    if len(vol_window) < 20:
        return None

    vol_avg = sum(vol_window) / len(vol_window)

    vol_ok = v[i] > vol_avg * VOLUME_MULTIPLIER

    h1_close = c1[-1]
    h4_close = c4[-1]

    sell = (
        price < e21 < e50 < e200
        and SELL_RSI_MIN < r < SELL_RSI_MAX
        and h1_close < e50_1h
        and h4_close < e50_4h
        and vol_ok
    )

    buy = (
        price > e21 > e50 > e200
        and BUY_RSI_MIN < r < BUY_RSI_MAX
        and h1_close > e50_1h
        and h4_close > e50_4h
        and vol_ok
    )

    if not sell and not buy:
        return None

    side = "SELL" if sell else "BUY"

    return {
        "side": side,
        "signal_close": price,
        "atr": atr_v,
        "rsi": r,
        "volume_ok": vol_ok,
        "h1": h1_close > e50_1h if buy else h1_close < e50_1h,
        "h4": h4_close > e50_4h if buy else h4_close < e50_4h,
        "signal_ct": ct[i],
    }


# ============================================================
# BACKTEST
# ============================================================

def apply_cost_to_r(
    gross_r,
    entry,
    exit_price,
    risk_distance
):
    """
    Convert approximate round-trip fee + slippage
    into R units.
    """

    if risk_distance <= 0:
        return gross_r

    cost_price = (
        entry * (FEE_RATE + SLIPPAGE_RATE)
        + exit_price * (FEE_RATE + SLIPPAGE_RATE)
    )

    cost_r = cost_price / risk_distance

    return gross_r - cost_r


def simulate_trade(
    side,
    entry,
    sl,
    tp2,
    d15,
    start_index,
):
    """
    Conservative intrabar simulation.

    If TP and SL occur inside the same candle and OHLC
    cannot establish order, SL wins.
    """

    c = d15["close"]
    h = d15["high"]
    l = d15["low"]

    for j in range(
        start_index,
        min(
            start_index + BACKTEST_HORIZON,
            len(c)
        )
    ):

        hi = h[j]
        lo = l[j]

        if side == "BUY":
            hit_tp = hi >= tp2
            hit_sl = lo <= sl
        else:
            hit_tp = lo <= tp2
            hit_sl = hi >= sl

        # Conservative ambiguity handling
        if hit_tp and hit_sl:
            return "LOSS", sl

        if hit_sl:
            return "LOSS", sl

        if hit_tp:
            return "WIN", tp2

    return "TIMEOUT", c[
        min(
            start_index + BACKTEST_HORIZON - 1,
            len(c) - 1
        )
    ]


def run_backtest(
    d15,
    d1h,
    d4h,
):
    wins = 0
    losses = 0
    timeouts = 0

    gross_r = 0.0
    net_r = 0.0

    start = 210

    end = len(d15["close"]) - BACKTEST_HORIZON - 2

    for i in range(start, end):

        setup = strategy_signal(
            i,
            d15,
            d1h,
            d4h
        )

        if not setup:
            continue

        side = setup["side"]

        # Realistic historical entry:
        # signal closes -> next candle opens
        entry = d15["open"][i + 1]

        atr_v = setup["atr"]

        if side == "BUY":
            sl = entry - atr_v * SL_ATR
            tp2 = entry + atr_v * TP2_ATR
        else:
            sl = entry + atr_v * SL_ATR
            tp2 = entry - atr_v * TP2_ATR

        result, exit_price = simulate_trade(
            side,
            entry,
            sl,
            tp2,
            d15,
            i + 1
        )

        risk_distance = abs(entry - sl)

        if side == "BUY":
            raw_r = (
                exit_price - entry
            ) / risk_distance
        else:
            raw_r = (
                entry - exit_price
            ) / risk_distance

        if result == "WIN":
            wins += 1

            gross_r += raw_r

            net_r += apply_cost_to_r(
                raw_r,
                entry,
                exit_price,
                risk_distance
            )

        elif result == "LOSS":
            losses += 1

            gross_r -= 1.0

            net_r += apply_cost_to_r(
                -1.0,
                entry,
                exit_price,
                risk_distance
            )

        else:
            timeouts += 1

    decided = wins + losses

    if decided < MIN_SAMPLE:
        return {
            "valid": False,
            "sample": decided,
            "wins": wins,
            "losses": losses,
            "timeouts": timeouts,
            "win_rate": 0.0,
            "gross_r": 0.0,
            "net_r": 0.0,
            "expectancy": 0.0,
        }

    win_rate = (
        wins / decided
    ) * 100.0

    expectancy = (
        net_r / decided
    )

    return {
        "valid": True,
        "sample": decided,
        "wins": wins,
        "losses": losses,
        "timeouts": timeouts,
        "win_rate": round(win_rate, 2),
        "gross_r": round(gross_r, 2),
        "net_r": round(net_r, 2),
        "expectancy": round(expectancy, 3),
    }


# ============================================================
# CONFIDENCE
# ============================================================

def confidence(stats):
    if not stats["valid"]:
        return None

    if stats["sample"] < MIN_SAMPLE:
        return None

    if stats["win_rate"] < MIN_WIN_RATE:
        return None

    if stats["expectancy"] < MIN_EXPECTANCY_R:
        return None

    if stats["win_rate"] >= 70:
        return "VERY HIGH"

    if stats["win_rate"] >= 65:
        return "HIGH"

    return "NORMAL"


# ============================================================
# BUILD SIGNAL
# ============================================================

async def build_signal(symbol, name):

    reset_daily_state_if_needed()

    if state["signals_today"] >= MAX_SIGNALS_PER_DAY:
        return None

    if state["loss_today_usd"] >= MAX_DAILY_LOSS_USD:
        return None

    if symbol in state["active"]:
        return None

    # Fetch market data concurrently
    k15_task = get_closed_klines(
        symbol,
        SIGNAL_TF,
        SIGNAL_LIMIT
    )

    k1_task = get_closed_klines(
        symbol,
        HTF1,
        HTF_LIMIT
    )

    k4_task = get_closed_klines(
        symbol,
        HTF2,
        HTF_LIMIT
    )

    k15, k1h, k4h = await asyncio.gather(
        k15_task,
        k1_task,
        k4_task
    )

    if (
        len(k15) < 250
        or len(k1h) < 70
        or len(k4h) < 70
    ):
        return None

    d15 = parse(k15)
    d1h = parse(k1h)
    d4h = parse(k4h)

    last_candle = d15["ot"][-1]

    # One signal per 15m candle
    if (
        state["last_signal_candle"].get(symbol)
        == last_candle
    ):
        return None

    setup = strategy_signal(
        len(d15["close"]) - 1,
        d15,
        d1h,
        d4h
    )

    if not setup:
        return None

    # Backtest on same historical dataset
    bt = run_backtest(
        d15,
        d1h,
        d4h
    )

    tier = confidence(bt)

    if tier is None:
        return None

    price = setup["signal_close"]
    atr_v = setup["atr"]
    side = setup["side"]

    if side == "BUY":
        sl = price - atr_v * SL_ATR
        tp1 = price + atr_v * TP1_ATR
        tp2 = price + atr_v * TP2_ATR
    else:
        sl = price + atr_v * SL_ATR
        tp1 = price - atr_v * TP1_ATR
        tp2 = price - atr_v * TP2_ATR

    risk_distance = abs(price - sl)

    if risk_distance <= 0:
        return None

    msg = f"""
{'🟢' if side == 'BUY' else '🔴'} {name} {side} — {tier}

ENTRY: {price:.4f}
SL:    {sl:.4f}  (1R)
TP1:   {tp1:.4f}  (1.5R / 50%)
TP2:   {tp2:.4f}  (2.5R)

BACKTEST
Win Rate: {bt['win_rate']:.1f}%
W/L: {bt['wins']}W / {bt['losses']}L
Samples: {bt['sample']}
Expectancy: {bt['expectancy']:.3f}R
Net PnL: {bt['net_r']:.2f}R

CONFIRMATION
15m Trend: ✅
1H: {'✅' if setup['h1'] else '❌'}
4H: {'✅' if setup['h4'] else '❌'}
Volume: {'✅' if setup['volume_ok'] else '❌'}
RSI: {setup['rsi']:.1f}
ATR: {atr_v:.4f}

PAPER MODE ONLY
No real order has been placed.
Historical statistics are NOT a future guarantee.
"""

    meta = {
        "symbol": symbol,
        "name": name,
        "side": side,
        "entry": price,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "risk_distance": risk_distance,
        "opened_at": int(
            datetime.now(timezone.utc).timestamp() * 1000
        ),
        "candle_open": last_candle,
        "tp1_hit": False,
        "remaining_fraction": 1.0,
        "realized_r": 0.0,
        "status": "OPEN",
    }

    return {
        "message": msg.strip(),
        "candle_open": last_candle,
        "meta": meta,
    }


# ============================================================
# PAPER TRADE MONITOR
# ============================================================

def evaluate_1m_candle(pos, candle):
    """
    candle = [open, high, low, close, close_time]

    Conservative:
    if TP and SL are both touched on the same 1m candle,
    SL gets priority.
    """

    high = candle["high"]
    low = candle["low"]

    side = pos["side"]

    if side == "BUY":

        if not pos["tp1_hit"]:
            hit_tp1 = high >= pos["tp1"]
            hit_sl = low <= pos["sl"]

            if hit_tp1 and hit_sl:
                return "SL"

            if hit_sl:
                return "SL"

            if hit_tp1:
                return "TP1"

        # After TP1 remaining SL is breakeven
        if pos["tp1_hit"]:
            if low <= pos["entry"]:
                return "BE"

            if high >= pos["tp2"]:
                return "TP2"

    else:

        if not pos["tp1_hit"]:
            hit_tp1 = low <= pos["tp1"]
            hit_sl = high >= pos["sl"]

            if hit_tp1 and hit_sl:
                return "SL"

            if hit_sl:
                return "SL"

            if hit_tp1:
                return "TP1"

        if pos["tp1_hit"]:
            if high >= pos["entry"]:
                return "BE"

            if low <= pos["tp2"]:
                return "TP2"

    return None


def result_r(pos, result):
    """
    Position:
      50% closes at TP1 = +0.75R
      remaining 50%:
         BE = 0R
         TP2 = +1.25R
         SL = -0.50R

    Total:
      TP1 + BE = +0.75R
      TP1 + TP2 = +2.00R
      TP1 + SL = +0.25R
      SL before TP1 = -1.00R
    """

    if result == "SL":
        return -1.0

    if result == "TP1":
        return 0.75

    if result == "BE":
        return 0.75

    if result == "TP2":
        return 2.0

    return 0.0


async def monitor_active(app):

    while True:

        try:

            if not state["active"]:
                await asyncio.sleep(MONITOR_SECONDS)
                continue

            for symbol, pos in list(
                state["active"].items()
            ):

                try:
                    candles = await get_closed_klines(
                        symbol,
                        MONITOR_TF,
                        MONITOR_LIMIT
                    )
                except Exception as e:
                    logging.error(
                        f"Monitor data error {symbol}: {e}"
                    )
                    continue

                if not candles:
                    continue

                d = parse(candles)

                last_checked = pos.get(
                    "last_checked_ct",
                    0
                )

                for i, ct in enumerate(d["ct"]):

                    if ct <= last_checked:
                        continue

                    # Ignore 1m candles that closed before trade entry
                    if ct < pos["opened_at"]:
                        continue

                    candle = {
                        "open": d["open"][i],
                        "high": d["high"][i],
                        "low": d["low"][i],
                        "close": d["close"][i],
                        "close_time": ct,
                    }

                    result = evaluate_1m_candle(
                        pos,
                        candle
                    )

                    pos["last_checked_ct"] = ct

                    if result == "TP1":

                        if not pos["tp1_hit"]:

                            pos["tp1_hit"] = True
                            pos["remaining_fraction"] = (
                                1.0 - TP1_PARTIAL
                            )

                            await app.bot.send_message(
                                chat_id=CHAT_ID,
                                text=(
                                    f"🟡 {symbol} "
                                    f"{pos['side']} TP1 HIT\n"
                                    f"50% paper position closed "
                                    f"at +1.5R.\n"
                                    f"Remaining 50% → "
                                    f"SL moved to ENTRY."
                                )
                            )

                            save_state()

                            continue

                    if result in [
                        "SL",
                        "BE",
                        "TP2",
                    ]:

                        final_r = result_r(
                            pos,
                            result
                        )

                        # Account actual paper risk
                        pnl_usd = (
                            final_r *
                            RISK_PER_TRADE_USD
                        )

                        state["stats"]["pnl_r"] += final_r
                        state["stats"]["pnl_usd"] += pnl_usd

                        if final_r > 0:
                            state["stats"]["wins"] += 1

                        elif final_r < 0:
                            state["stats"]["losses"] += 1
                            state["loss_today_usd"] += abs(
                                pnl_usd
                            )

                        else:
                            state["stats"]["breakeven"] += 1

                        if result == "TP2":
                            text = (
                                f"✅ {symbol} "
                                f"{pos['side']} TP2\n"
                                f"Paper result: +{final_r:.2f}R"
                            )

                        elif result == "BE":
                            text = (
                                f"🟡 {symbol} "
                                f"{pos['side']} BREAKEVEN\n"
                                f"Paper result: "
                                f"+{final_r:.2f}R"
                            )

                        else:
                            text = (
                                f"❌ {symbol} "
                                f"{pos['side']} SL\n"
                                f"Paper result: "
                                f"{final_r:.2f}R"
                            )

                        text += (
                            f"\nToday loss: "
                            f"${state['loss_today_usd']:.2f}"
                            f"/${MAX_DAILY_LOSS_USD:.2f}"
                        )

                        await app.bot.send_message(
                            chat_id=CHAT_ID,
                            text=text
                        )

                        state["history"].append({
                            "symbol": symbol,
                            "side": pos["side"],
                            "entry": pos["entry"],
                            "result": result,
                            "r": final_r,
                            "pnl_usd": pnl_usd,
                            "time": datetime.now(
                                timezone.utc
                            ).isoformat(),
                        })

                        # Keep history manageable
                        state["history"] = (
                            state["history"][-200:]
                        )

                        del state["active"][symbol]

                        save_state()

                        break

                save_state()

            await asyncio.sleep(MONITOR_SECONDS)

        except Exception as e:

            logging.exception(
                f"Monitor error: {e}"
            )

            await asyncio.sleep(
                MONITOR_SECONDS
            )


# ============================================================
# SCANNER
# ============================================================

async def scanner(app):

    while True:

        try:

            reset_daily_state_if_needed()

            if (
                state["signals_today"]
                >= MAX_SIGNALS_PER_DAY
            ):
                await asyncio.sleep(
                    SCANNER_SECONDS
                )
                continue

            if (
                state["loss_today_usd"]
                >= MAX_DAILY_LOSS_USD
            ):
                await asyncio.sleep(
                    SCANNER_SECONDS
                )
                continue

            for symbol, name in SYMBOLS.items():

                try:

                    result = await build_signal(
                        symbol,
                        name
                    )

                    if not result:
                        continue

                    # Send first
                    await app.bot.send_message(
                        chat_id=CHAT_ID,
                        text=result["message"]
                    )

                    # Only commit state after Telegram succeeds
                    state["last_signal_candle"][symbol] = (
                        result["candle_open"]
                    )

                    state["active"][symbol] = (
                        result["meta"]
                    )

                    state["signals_today"] += 1
                    state["stats"]["signals"] += 1

                    save_state()

                    logging.info(
                        f"SIGNAL SENT: "
                        f"{symbol} "
                        f"{result['meta']['side']}"
                    )

                except Exception as e:

                    logging.exception(
                        f"Scanner {symbol}: {e}"
                    )

            await asyncio.sleep(
                SCANNER_SECONDS
            )

        except Exception as e:

            logging.exception(
                f"Scanner error: {e}"
            )

            await asyncio.sleep(30)


# ============================================================
# TELEGRAM COMMANDS
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🛡️ Adil v18 PRO PAPER ON\n\n"
        "Exact HTF alignment ✅\n"
        "No-lookahead backtest ✅\n"
        "Intrabar 1m monitoring ✅\n"
        "TP1 partial + BE ✅\n"
        "R + USD PnL ✅\n"
        "Max 2 signals/day ✅\n"
        "Daily $4 loss stop ✅\n\n"
        "PAPER MODE ONLY."
    )


async def status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    reset_daily_state_if_needed()

    active = []

    for symbol, pos in state["active"].items():

        active.append(
            f"{symbol} {pos['side']} "
            f"Entry={pos['entry']:.4f}"
        )

    active_text = (
        "\n".join(active)
        if active
        else "None"
    )

    s = state["stats"]

    await update.message.reply_text(
        f"📊 v18 STATUS\n\n"
        f"Signals today: "
        f"{state['signals_today']}/{MAX_SIGNALS_PER_DAY}\n"
        f"Daily loss: "
        f"${state['loss_today_usd']:.2f}"
        f"/${MAX_DAILY_LOSS_USD:.2f}\n\n"
        f"Wins: {s['wins']}\n"
        f"Losses: {s['losses']}\n"
        f"Breakeven: {s['breakeven']}\n"
        f"Signals: {s['signals']}\n"
        f"PnL: {s['pnl_r']:.2f}R\n"
        f"PnL USD: ${s['pnl_usd']:.2f}\n\n"
        f"ACTIVE:\n{active_text}"
    )


async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    s = state["stats"]

    decided = s["wins"] + s["losses"]

    if decided:
        wr = (
            s["wins"] / decided
        ) * 100
    else:
        wr = 0

    await update.message.reply_text(
        f"📈 v18 PAPER STATS\n\n"
        f"Wins: {s['wins']}\n"
        f"Losses: {s['losses']}\n"
        f"Breakeven: {s['breakeven']}\n"
        f"Win rate: {wr:.1f}%\n"
        f"PnL: {s['pnl_r']:.2f}R\n"
        f"PnL USD: ${s['pnl_usd']:.2f}"
    )


async def active(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not state["active"]:

        await update.message.reply_text(
            "No active paper trades."
        )

        return

    lines = []

    for symbol, p in state["active"].items():

        lines.append(
            f"{symbol} {p['side']}\n"
            f"Entry: {p['entry']:.4f}\n"
            f"SL: {p['sl']:.4f}\n"
            f"TP1: {p['tp1']:.4f}\n"
            f"TP2: {p['tp2']:.4f}\n"
            f"TP1 hit: "
            f"{'YES' if p['tp1_hit'] else 'NO'}"
        )

    await update.message.reply_text(
        "\n\n".join(lines)
    )


async def reset(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    # Safety:
    # do not reset while active trades exist.
    if state["active"]:

        await update.message.reply_text(
            "Cannot reset while active paper trades exist."
        )

        return

    state["signals_today"] = 0
    state["loss_today_usd"] = 0.0

    save_state()

    await update.message.reply_text(
        "Daily paper limits reset."
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def telegram_error(
    update,
    context
):

    logging.exception(
        "Telegram error",
        exc_info=context.error
    )


# ============================================================
# STARTUP
# ============================================================

async def post_init(
    application: Application
):

    logging.info(
        "Starting v18 scanner + monitor..."
    )

    application.create_task(
        scanner(application)
    )

    application.create_task(
        monitor_active(application)
    )

    await application.bot.send_message(
        chat_id=CHAT_ID,
        text=(
            "🟢 Adil v18 PRO PAPER STARTED\n"
            "Scanner + monitor online.\n"
            "No real orders."
        )
    )


# ============================================================
# MAIN
# ============================================================

def run_flask():

    flask_app.run(
        host="0.0.0.0",
        port=int(
            os.getenv("PORT", "10000")
        )
    )


def main():

    threading.Thread(
        target=run_flask,
        daemon=True
    ).start()

    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("status", status)
    )

    application.add_handler(
        CommandHandler("stats", stats)
    )

    application.add_handler(
        CommandHandler("active", active)
    )

    application.add_handler(
        CommandHandler("reset", reset)
    )

    application.add_error_handler(
        telegram_error
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
