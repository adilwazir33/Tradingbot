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
# Current scoring system has a maximum of 7.
# 6 = strong enough while still allowing Forex/Gold
# where volume may not be available.
MIN_SCORE = 6
COOLDOWN_MINUTES = 45
SL_ATR = 1.20
TP1_ATR = 1.50
TP2_ATR = 2.50
# 3 symbols x 3 timeframes = 9 API calls.
# 5-minute cycle keeps Twelve Data request rate safely lower.
SCAN_SECONDS = 300
API_URL = "https://api.twelvedata.com/time_series"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
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
def telegram_request(method, payload=None, timeout=30):
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN missing")
        return None
    url = f"{TELEGRAM_API}/{method}"
    try:
        response = requests.post(
            url,
            json=payload or {},
            timeout=timeout,
        )
        data = response.json()
        if not response.ok or not data.get("ok"):
            print(
                f"Telegram {method} error:",
                data.get("description", response.text)
            )
            return None
        return data
    except Exception as e:
        print(f"Telegram {method} exception:", e)
        return None
def send_telegram(message, chat_id=None):
    target_chat = chat_id or CHAT_ID
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN missing")
        return False
    if not target_chat:
        print("ERROR: CHAT_ID missing")
        return False
    result = telegram_request(
        "sendMessage",
        {
            "chat_id": target_chat,
            "text": message,
            "parse_mode": "HTML",
        },
        timeout=20,
    )
    if result:
        print("Telegram message sent: OK")
        return True
    print("Telegram message sent: FAILED")
    return False
def telegram_check():
    if not BOT_TOKEN:
        print("TELEGRAM STATUS: BOT_TOKEN missing")
        return False
    result = telegram_request("getMe", {}, timeout=15)
    if not result:
        print("TELEGRAM STATUS: FAILED")
        return False
    bot = result["result"]
    print(
        "TELEGRAM STATUS: OK | "
        f"@{bot.get('username', 'unknown')}"
    )
    return True
def telegram_startup_message():
    message = """
<b>🟢 ADIL SIGNAL BOT ONLINE</b>
✅ Telegram Connected
✅ Twelve Data Configured
📊 Scanner Active
<b>Symbols:</b>
XAUUSD.r
EURUSD.r
BTCUSD.r
<b>Timeframes:</b>
M15 + H1 + H4
<b>Broker:</b> Lirunex MT5
<b>Execution:</b> Manual
⚠️ Twelve Data public-feed price may differ from Lirunex MT5.
"""
    return send_telegram(message)
def telegram_listener():
    """
    Handles /start, /status and /test.
    Uses Telegram Bot API directly, so no extra package is needed.
    """
    if not BOT_TOKEN:
        print("Telegram listener stopped: BOT_TOKEN missing")
        return
    # Remove any old webhook so long polling can work.
    telegram_request(
        "deleteWebhook",
        {"drop_pending_updates": False},
        timeout=15,
    )
    offset = None
    print("Telegram command listener started")
    while True:
        try:
            payload = {
                "timeout": 25,
                "allowed_updates": ["message"],
            }
            if offset is not None:
                payload["offset"] = offset
            result = telegram_request(
                "getUpdates",
                payload,
                timeout=35,
            )
            if not result:
                time.sleep(5)
                continue
            updates = result.get("result", [])
            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message")
                if not message:
                    continue
                text = message.get("text", "").strip()
                chat = message.get("chat", {})
                chat_id = str(chat.get("id", ""))
                # Only respond to the configured chat.
                if CHAT_ID and chat_id != str(CHAT_ID):
                    print(
                        f"Ignored Telegram command from chat {chat_id}"
                    )
                    continue
                if text.startswith("/start"):
                    send_telegram(
                        """
<b>🟢 ADIL SIGNAL BOT</b>
Bot is online and scanning.
✅ Telegram
✅ Twelve Data
✅ M15
✅ H1
✅ H4
Commands:
/start - bot status
/status - system status
/test - Telegram test
""",
                        chat_id,
                    )
                elif text.startswith("/status"):
                    send_telegram(
                        """
<b>📊 ADIL BOT STATUS</b>
🟢 Render: Running
🟢 Telegram: Connected
🟢 Twelve Data: Configured
🟢 Scanner: Active
<b>Symbols:</b>
XAUUSD.r
EURUSD.r
BTCUSD.r
<b>Scan interval:</b>
5 minutes
""",
                        chat_id,
                    )
                elif text.startswith("/test"):
                    send_telegram(
                        """
<b>🧪 TELEGRAM TEST</b>
Telegram connection is working correctly.
🟢 Bot is ready.
""",
                        chat_id,
                    )
        except Exception as e:
            print("Telegram listener error:", e)
            time.sleep(5)
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
        if data.get("status") == "error":
            print(
                f"DATA ERROR {symbol} {interval}:",
                data.get("message"),
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
                print(
                    f"Missing {column}: {symbol} {interval}"
                )
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
                errors="coerce",
            )
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(
                df["volume"],
                errors="coerce",
            )
        else:
            df["volume"] = 0.0
        df = df.dropna(
            subset=[
                "open",
                "high",
                "low",
                "close",
            ]
        )
        df = df.sort_values("time").reset_index(drop=True)
        print(
            f"DATA OK | {symbol} | {interval} | "
            f"{len(df)} candles"
        )
        return df
    except Exception as e:
        print(
            f"Market data error {symbol} {interval}:",
            e,
        )
        return None
# ============================================================
# INDICATORS
# ============================================================
def ema(series, period):
    return series.ewm(
        span=period,
        adjust=False,
    ).mean()
def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False,
    ).mean()
    avg_loss = loss.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False,
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
            low_close,
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False,
    ).mean()
# ============================================================
# TIMEFRAME ANALYSIS
# ============================================================
def analyze(df):
    if df is None or len(df) < 220:
        return None
    df = df.copy()
    df["ema21"] = ema(
        df["close"],
        21,
    )
    df["ema50"] = ema(
        df["close"],
        50,
    )
    df["ema200"] = ema(
        df["close"],
        200,
    )
    df["rsi"] = rsi(
        df["close"],
        14,
    )
    df["atr"] = atr(
        df,
        14,
    )
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
    # Volume when available
    if (
        row["volume"] > 0
        and row["volume_avg"] > 0
        and row["volume"] > row["volume_avg"]
    ):
        if row["close"] > previous["close"]:
            buy += 1
        elif row["close"] < previous["close"]:
            sell += 1
    if not np.isfinite(row["atr"]):
        return None
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
            interval,
        )
        if df is None:
            print(
                f"FAILED DATA | {display_symbol} | {name}"
            )
            return None
        frames[name] = df
    m15 = analyze(frames["M15"])
    h1 = analyze(frames["H1"])
    h4 = analyze(frames["H4"])
    m15_side = m15["side"] if m15 else "NONE"
    h1_side = h1["side"] if h1 else "NONE"
    h4_side = h4["side"] if h4 else "NONE"
    print(
        f"ANALYSIS | {display_symbol} | "
        f"M15={m15_side} H1={h1_side} H4={h4_side}"
    )
    if not m15 or not h1 or not h4:
        return None
    # Strict M15 + H1 + H4 confirmation
    if not (
        m15["side"]
        == h1["side"]
        == h4["side"]
    ):
        print(
            f"NO SIGNAL | {display_symbol} | "
            "Timeframes disagree"
        )
        return None
    side = m15["side"]
    entry = m15["price"]
    atr_value = m15["atr"]
    if (
        not np.isfinite(atr_value)
        or atr_value <= 0
    ):
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
    if symbol in [
        "BTCUSD.r",
        "XAUUSD.r",
    ]:
        return f"{value:.2f}"
    return f"{value:.5f}"
# ============================================================
# TELEGRAM SIGNAL MESSAGE
# ============================================================
def signal_message(signal):
    symbol = signal["symbol"]
    emoji = (
        "🟢"
        if signal["side"] == "BUY"
        else "🔴"
    )
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
    print("")
    print("======================================")
    print("ADIL SIGNAL BOT STARTED")
    print("======================================")
    print("Symbols:", list(SYMBOLS.keys()))
    print("MIN_SCORE:", MIN_SCORE)
    print("SCAN_SECONDS:", SCAN_SECONDS)
    if not TWELVE_DATA_API_KEY:
        print("ERROR: Twelve Data API key missing")
    else:
        print("TWELVE DATA STATUS: API KEY FOUND")
    if not CHAT_ID:
        print("ERROR: CHAT_ID missing")
    else:
        print("TELEGRAM CHAT_ID: CONFIGURED")
    telegram_check()
    # Send startup message
    if CHAT_ID:
        telegram_startup_message()
    while True:
        cycle_start = time.time()
        print("")
        print("======================================")
        print("NEW SCAN CYCLE")
        print("======================================")
        for symbol in SYMBOLS:
            try:
                signal = build_signal(symbol)
                if not signal:
                    print(
                        f"{symbol}: No confirmed signal"
                    )
                    continue
                print(
                    f"SIGNAL FOUND | "
                    f"{symbol} | "
                    f"{signal['side']} | "
                    f"Score {signal['score']}"
                )
                if not signal_allowed(
                    signal["symbol"],
                    signal["side"],
                ):
                    print(
                        f"{symbol}: Cooldown active"
                    )
                    continue
                message = signal_message(
                    signal
                )
                send_telegram(message)
                time.sleep(2)
            except Exception as e:
                print(
                    f"Scanner error {symbol}:",
                    e,
                )
        elapsed = time.time() - cycle_start
        sleep_time = max(
            5,
            SCAN_SECONDS - elapsed,
        )
        print(
            f"Scan complete. "
            f"Next scan in ~{sleep_time:.0f} seconds."
        )
        time.sleep(sleep_time)
# ============================================================
# START
# ============================================================
if __name__ == "__main__":
    Thread(
        target=flask_server,
        daemon=True,
    ).start()
    Thread(
        target=telegram_listener,
        daemon=True,
    ).start()
    scanner()
