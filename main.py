import os

import time

import asyncio

import threading

import traceback

import sqlite3

from datetime import datetime, timezone

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

from pyquotex.stable_api import Quotex

# =========================================================

# CONFIG

# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

CHAT_ID = os.getenv("CHAT_ID", "").strip()

QUOTEX_EMAIL = os.getenv("QUOTEX_EMAIL", "").strip()

QUOTEX_PASSWORD = os.getenv("QUOTEX_PASSWORD", "").strip()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

PORT = int(os.getenv("PORT", "10000"))

VERSION = "v12"

PERIOD = 60

CANDLE_COUNT = 120

SCAN_DELAY = 5

# Do not send duplicate signal for same asset/candle

signal_memory = {}

# Pending outcomes

pending_outcomes = []

pending_lock = threading.Lock()

quotex_client = None

quotex_status = "NOT_STARTED"

telegram_status = "NOT_STARTED"

last_error = ""

telegram_bot_username = ""

# =========================================================

# FLASK

# =========================================================

app = Flask(__name__)

@app.route("/")

def home():

    return f"Adil SAFE WIN {VERSION} LIVE"

@app.route("/health")

def health():

    return {

        "status": "ok",

        "version": VERSION,

        "telegram": telegram_status,

        "quotex": quotex_status,

        "time": datetime.now(timezone.utc).isoformat(),

    }

# =========================================================

# ASSETS

# =========================================================

ASSETS = {

    "EURUSD": [

        "EURUSD",

        "EURUSD_otc",

        "EURUSD-OTC",

    ],

    "BTCUSD": [

        "BTCUSD",

        "BTCUSD_otc",

        "BTCUSD-OTC",

    ],

    "XAUUSD": [

        "XAUUSD",

        "GOLD",

        "XAUUSD_otc",

        "GOLD_otc",

        "GOLD-OTC",

    ],

}

# =========================================================

# DATABASE

# =========================================================

SQLITE_DB = "signals.db"

def db_connection():

    return sqlite3.connect(

        SQLITE_DB,

        check_same_thread=False

    )

def db_init():

    try:

        if DATABASE_URL:

            import psycopg2

            conn = psycopg2.connect(DATABASE_URL)

            cur = conn.cursor()

            cur.execute("""

                CREATE TABLE IF NOT EXISTS signals (

                    id SERIAL PRIMARY KEY,

                    created_at TIMESTAMP,

                    asset TEXT,

                    direction TEXT,

                    confidence REAL,

                    entry REAL,

                    analysis_close REAL,

                    expiry_close REAL,

                    result TEXT,

                    analysis_time TIMESTAMP,

                    entry_time TIMESTAMP,

                    expiry_time TIMESTAMP

                )

            """)

            conn.commit()

            cur.close()

            conn.close()

            print("DATABASE: PostgreSQL READY")

            return

    except Exception as e:

        print("DATABASE: PostgreSQL failed")

        print(repr(e))

        print("DATABASE: switching to SQLite")

    try:

        conn = db_connection()

        cur = conn.cursor()

        cur.execute("""

            CREATE TABLE IF NOT EXISTS signals (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                created_at TEXT,

                asset TEXT,

                direction TEXT,

                confidence REAL,

                entry REAL,

                analysis_close REAL,

                expiry_close REAL,

                result TEXT,

                analysis_time TEXT,

                entry_time TEXT,

                expiry_time TEXT

            )

        """)

        conn.commit()

        conn.close()

        print("DATABASE: SQLite READY")

    except Exception as e:

        print("DATABASE ERROR:", repr(e))

def db_insert(

    asset,

    direction,

    confidence,

    entry,

    analysis_close,

    analysis_time,

    entry_time,

    expiry_time

):

    try:

        if DATABASE_URL:

            import psycopg2

            conn = psycopg2.connect(DATABASE_URL)

            cur = conn.cursor()

            cur.execute("""

                INSERT INTO signals (

                    created_at,

                    asset,

                    direction,

                    confidence,

                    entry,

                    analysis_close,

                    expiry_close,

                    result,

                    analysis_time,

                    entry_time,

                    expiry_time

                )

                VALUES (

                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s

                )

            """, (

                datetime.now(timezone.utc),

                asset,

                direction,

                confidence,

                entry,

                analysis_close,

                None,

                "PENDING",

                analysis_time,

                entry_time,

                expiry_time,

            ))

            conn.commit()

            cur.close()

            conn.close()

            return

    except Exception as e:

        print("PostgreSQL INSERT ERROR:", repr(e))

    try:

        conn = db_connection()

        cur = conn.cursor()

        cur.execute("""

            INSERT INTO signals (

                created_at,

                asset,

                direction,

                confidence,

                entry,

                analysis_close,

                expiry_close,

                result,

                analysis_time,

                entry_time,

                expiry_time

            )

            VALUES (?,?,?,?,?,?,?,?,?,?,?)

        """, (

            datetime.now(timezone.utc).isoformat(),

            asset,

            direction,

            confidence,

            entry,

            analysis_close,

            None,

            "PENDING",

            analysis_time.isoformat(),

            entry_time.isoformat(),

            expiry_time.isoformat(),

        ))

        conn.commit()

        conn.close()

    except Exception as e:

        print("SQLite INSERT ERROR:", repr(e))

def db_update(

    asset,

    entry_time,

    expiry_close,

    result

):

    try:

        if DATABASE_URL:

            import psycopg2

            conn = psycopg2.connect(DATABASE_URL)

            cur = conn.cursor()

            cur.execute("""

                UPDATE signals

                SET expiry_close=%s,

                    result=%s

                WHERE asset=%s

                AND entry_time=%s

                AND result='PENDING'

            """, (

                expiry_close,

                result,

                asset,

                entry_time,

            ))

            conn.commit()

            cur.close()

            conn.close()

            return

    except Exception as e:

        print("PostgreSQL UPDATE ERROR:", repr(e))

    try:

        conn = db_connection()

        cur = conn.cursor()

        cur.execute("""

            UPDATE signals

            SET expiry_close=?,

                result=?

            WHERE asset=?

            AND entry_time=?

            AND result='PENDING'

        """, (

            expiry_close,

            result,

            asset,

            entry_time.isoformat(),

        ))

        conn.commit()

        conn.close()

    except Exception as e:

        print("SQLite UPDATE ERROR:", repr(e))

def db_stats():

    try:

        if DATABASE_URL:

            import psycopg2

            conn = psycopg2.connect(DATABASE_URL)

            cur = conn.cursor()

            cur.execute("""

                SELECT

                    COUNT(*),

                    COUNT(*) FILTER (WHERE result='WIN'),

                    COUNT(*) FILTER (WHERE result='LOSS'),

                    COUNT(*) FILTER (WHERE result='DRAW'),

                    COUNT(*) FILTER (WHERE result='PENDING')

                FROM signals

            """)

            result = cur.fetchone()

            cur.close()

            conn.close()

            return result

    except Exception:

        pass

    try:

        conn = db_connection()

        cur = conn.cursor()

        cur.execute("""

            SELECT

                COUNT(*),

                SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END),

                SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END),

                SUM(CASE WHEN result='DRAW' THEN 1 ELSE 0 END),

                SUM(CASE WHEN result='PENDING' THEN 1 ELSE 0 END)

            FROM signals

        """)

        result = cur.fetchone()

        conn.close()

        return tuple(

            0 if x is None else x

            for x in result

        )

    except Exception:

        return (0, 0, 0, 0, 0)

# =========================================================

# TELEGRAM RAW API

# =========================================================

def telegram_api(method, payload=None):

    if not BOT_TOKEN:

        return None

    url = (

        f"https://api.telegram.org/bot"

        f"{BOT_TOKEN}/{method}"

    )

    try:

        response = requests.post(

            url,

            json=payload or {},

            timeout=20

        )

        if not response.ok:

            print(

                "Telegram HTTP ERROR:",

                response.status_code,

                response.text[:500]

            )

            return None

        data = response.json()

        if not data.get("ok"):

            print(

                "Telegram API ERROR:",

                data

            )

            return None

        return data

    except Exception as e:

        print(

            "Telegram REQUEST ERROR:",

            repr(e)

        )

        return None

def send_telegram(text):

    if not CHAT_ID:

        print("Telegram: CHAT_ID missing")

        return False

    result = telegram_api(

        "sendMessage",

        {

            "chat_id": CHAT_ID,

            "text": text,

            "parse_mode": "HTML",

            "disable_web_page_preview": True,

        }

    )

    return result is not None

def verify_telegram():

    global telegram_status

    global telegram_bot_username

    print("Telegram: checking BOT_TOKEN...")

    if not BOT_TOKEN:

        telegram_status = "TOKEN_MISSING"

        print("ERROR: BOT_TOKEN is missing")

        return False

    result = telegram_api("getMe")

    if not result:

        telegram_status = "TOKEN_INVALID_OR_NETWORK_ERROR"

        print(

            "ERROR: Telegram token could not be verified"

        )

        return False

    user = result["result"]

    telegram_bot_username = (

        user.get("username") or ""

    )

    telegram_status = "VERIFIED"

    print(

        f"Telegram: token verified "

        f"@{telegram_bot_username}"

    )

    if not CHAT_ID:

        print(

            "WARNING: CHAT_ID is missing. "

            "Bot commands can still work, "

            "but automatic signals cannot be sent."

        )

    return True

# =========================================================

# TELEGRAM COMMANDS

# =========================================================

async def cmd_start(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE

):

    text = (

        "✅ <b>Adil SAFE WIN Bot</b>\n\n"

        f"Version: <b>{VERSION}</b>\n"

        "Engine: <b>1 Minute</b>\n"

        "Markets: <b>BTC + EURUSD + GOLD + OTC</b>\n\n"

        "Commands:\n"

        "/status\n"

        "/market\n"

        "/stats"

    )

    await update.message.reply_text(

        text,

        parse_mode="HTML"

    )

async def cmd_status(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE

):

    text = (

        "📊 <b>BOT STATUS</b>\n\n"

        f"Telegram: <b>{telegram_status}</b>\n"

        f"Quotex: <b>{quotex_status}</b>\n"

        f"Version: <b>{VERSION}</b>\n"

        f"Pending outcomes: <b>{len(pending_outcomes)}</b>"

    )

    await update.message.reply_text(

        text,

        parse_mode="HTML"

    )

async def cmd_market(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE

):

    text = (

        "📈 <b>MARKETS</b>\n\n"

        "🪙 BTCUSD\n"

        "💱 EURUSD\n"

        "🥇 XAUUSD / GOLD\n\n"

        "OTC symbols bhi scanner mein included hain."

    )

    await update.message.reply_text(

        text,

        parse_mode="HTML"

    )

async def cmd_stats(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE

):

    total, wins, losses, draws, pending = db_stats()

    completed = wins + losses + draws

    if completed:

        winrate = (

            wins / completed

        ) * 100

    else:

        winrate = 0

    text = (

        "📊 <b>STATISTICS</b>\n\n"

        f"Total: <b>{total}</b>\n"

        f"WIN: <b>{wins}</b>\n"

        f"LOSS: <b>{losses}</b>\n"

        f"DRAW: <b>{draws}</b>\n"

        f"PENDING: <b>{pending}</b>\n\n"

        f"Completed win rate: "

        f"<b>{winrate:.1f}%</b>"

    )

    await update.message.reply_text(

        text,

        parse_mode="HTML"

    )

async def telegram_main():

    global telegram_status

    print("Telegram: initializing...")

    if not verify_telegram():

        return

    try:

        application = (

            ApplicationBuilder()

            .token(BOT_TOKEN)

            .build()

        )

        application.add_handler(

            CommandHandler(

                "start",

                cmd_start

            )

        )

        application.add_handler(

            CommandHandler(

                "status",

                cmd_status

            )

        )

        application.add_handler(

            CommandHandler(

                "market",

                cmd_market

            )

        )

        application.add_handler(

            CommandHandler(

                "stats",

                cmd_stats

            )

        )

        print(

            "Telegram: application initializing..."

        )

        await application.initialize()

        print(

            "Telegram: application initialized"

        )

        await application.start()

        print(

            "Telegram: application started"

        )

        if application.updater is None:

            raise RuntimeError(

                "Telegram updater is unavailable"

            )

        print(

            "Telegram: starting polling..."

        )

        await application.updater.start_polling(

            drop_pending_updates=True

        )

        telegram_status = "LIVE"

        print(

            f"Telegram bot LIVE "

            f"@{telegram_bot_username}"

        )

        while True:

            await asyncio.sleep(3600)

    except Exception as e:

        telegram_status = "ERROR"

        print(

            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"

        )

        print(

            "TELEGRAM THREAD ERROR"

        )

        print(

            repr(e)

        )

        traceback.print_exc()

        print(

            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"

        )

def telegram_thread():

    try:

        asyncio.run(

            telegram_main()

        )

    except Exception as e:

        print(

            "Telegram asyncio ERROR:",

            repr(e)

        )

        traceback.print_exc()

# =========================================================

# INDICATORS

# =========================================================

def rsi(series, period=14):

    delta = series.diff()

    gain = delta.clip(

        lower=0

    )

    loss = -delta.clip(

        upper=0

    )

    avg_gain = gain.rolling(

        period

    ).mean()

    avg_loss = loss.rolling(

        period

    ).mean()

    rs = (

        avg_gain /

        avg_loss.replace(

            0,

            np.nan

        )

    )

    result = 100 - (

        100 / (1 + rs)

    )

    result = result.where(

        ~(

            (avg_loss == 0) &

            (avg_gain > 0)

        ),

        100

    )

    result = result.where(

        ~(

            (avg_gain == 0) &

            (avg_loss > 0)

        ),

        0

    )

    return result

def atr(df, period=14):

    previous_close = df["close"].shift(1)

    tr = pd.concat(

        [

            df["high"] - df["low"],

            (

                df["high"] -

                previous_close

            ).abs(),

            (

                df["low"] -

                previous_close

            ).abs(),

        ],

        axis=1

    ).max(axis=1)

    return tr.rolling(

        period

    ).mean()

# =========================================================

# QUOTEX CANDLE HELPERS

# =========================================================

def normalize_candles(raw):

    if raw is None:

        return None

    # Some versions can return dict

    if isinstance(raw, dict):

        if "data" in raw:

            raw = raw["data"]

        elif "candles" in raw:

            raw = raw["candles"]

        else:

            raw = [raw]

    if not isinstance(raw, list):

        return None

    rows = []

    for item in raw:

        if not isinstance(item, dict):

            continue

        try:

            t = (

                item.get("time")

                or item.get("from")

                or item.get("timestamp")

            )

            o = item.get("open")

            h = item.get("high")

            l = item.get("low")

            c = item.get("close")

            # Some Quotex responses use max/min

            if h is None:

                h = item.get("max")

            if l is None:

                l = item.get("min")

            if (

                t is None or

                o is None or

                h is None or

                l is None or

                c is None

            ):

                continue

            rows.append({

                "time": int(float(t)),

                "open": float(o),

                "high": float(h),

                "low": float(l),

                "close": float(c),

            })

        except Exception:

            continue

    if len(rows) < 20:

        return None

    df = pd.DataFrame(rows)

    df = df.drop_duplicates(

        subset=["time"]

    )

    df = df.sort_values(

        "time"

    )

    return df.reset_index(

        drop=True

    )

async def get_candles_async(

    client,

    symbol

):

    try:

        end_time = time.time()

        offset = 3600

        raw = await client.get_candles(

            symbol,

            end_time,

            offset,

            PERIOD

        )

        return normalize_candles(raw)

    except Exception as e:

        print(

            f"Candle ERROR [{symbol}]:",

            repr(e)

        )

        return None

# =========================================================

# ANALYSIS

# =========================================================

def analyze(df):

    if df is None:

        return None

    if len(df) < 60:

        return None

    data = df.copy()

    data["ema14"] = (

        data["close"]

        .ewm(

            span=14,

            adjust=False

        )

        .mean()

    )

    data["ema50"] = (

        data["close"]

        .ewm(

            span=50,

            adjust=False

        )

        .mean()

    )

    data["rsi"] = rsi(

        data["close"],

        14

    )

    data["atr"] = atr(

        data,

        14

    )

    # Last completed candle

    last = data.iloc[-2]

    previous = data.iloc[-3]

    score_call = 0

    score_put = 0

    # EMA

    if last["ema14"] > last["ema50"]:

        score_call += 2

    elif last["ema14"] < last["ema50"]:

        score_put += 2

    # RSI

    if 52 <= last["rsi"] <= 68:

        score_call += 2

    elif 32 <= last["rsi"] <= 48:

        score_put += 2

    # Momentum

    if last["close"] > previous["close"]:

        score_call += 1

    elif last["close"] < previous["close"]:

        score_put += 1

    # Candle

    if last["close"] > last["open"]:

        score_call += 1

    elif last["close"] < last["open"]:

        score_put += 1

    # Recent breakout

    recent = data.iloc[-7:-2]

    if len(recent):

        recent_high = recent["high"].max()

        recent_low = recent["low"].min()

        if last["close"] > recent_high:

            score_call += 2

        elif last["close"] < recent_low:

            score_put += 2

    if score_call == score_put:

        return None

    if score_call > score_put:

        direction = "CALL"

        score = score_call

    else:

        direction = "PUT"

        score = score_put

    confidence = min(

        95,

        50 + score * 5

    )

    return {

        "direction": direction,

        "confidence": confidence,

        "analysis_close": float(

            last["close"]

        ),

        "analysis_time": int(

            last["time"]

        ),

    }

# =========================================================

# ASSET TEST

# =========================================================

async def find_working_asset(

    client,

    base_name

):

    candidates = ASSETS.get(

        base_name,

        []

    )

    for symbol in candidates:

        try:

            df = await get_candles_async(

                client,

                symbol

            )

            if df is not None and len(df) >= 60:

                print(

                    f"ASSET OK: "

                    f"{base_name} -> {symbol}"

                )

                return symbol, df

            print(

                f"ASSET NO DATA: {symbol}"

            )

        except Exception as e:

            print(

                f"ASSET ERROR {symbol}:",

                repr(e)

            )

    return None, None

# =========================================================

# SIGNAL

# =========================================================

async def generate_signal(

    client,

    base_name

):

    symbol, df = await find_working_asset(

        client,

        base_name

    )

    if symbol is None:

        return

    result = analyze(df)

    if result is None:

        return

    # Current candle = entry candle

    current_candle = df.iloc[-1]

    entry = float(

        current_candle["open"]

    )

    entry_time = int(

        current_candle["time"]

    )

    analysis_time = int(

        result["analysis_time"]

    )

    # Avoid duplicate candle signal

    memory_key = (

        base_name,

        symbol,

        entry_time

    )

    if memory_key in signal_memory:

        return

    signal_memory[memory_key] = True

    direction = result["direction"]

    confidence = result["confidence"]

    analysis_close = result[

        "analysis_close"

    ]

    # Expiry = one minute

    expiry_time = (

        entry_time + PERIOD

    )

    signal_text = (

        "🚨 <b>1 MIN SIGNAL</b>\n\n"

        f"📊 Asset: <b>{symbol}</b>\n"

        f"🎯 Direction: "

        f"<b>{direction}</b>\n"

        f"💰 Entry: <b>{entry:.8f}</b>\n"

        f"📈 Confidence: "

        f"<b>{confidence:.0f}%</b>\n"

        f"⏱ Expiry: <b>1 MIN</b>\n\n"

        "⚠️ Confidence is a technical score, "

        "not a guaranteed win probability."

    )

    print(

        f"SIGNAL | {symbol} | "

        f"{direction} | "

        f"Entry={entry} | "

        f"Confidence={confidence:.0f}%"

    )

    # Database

    db_insert(

        asset=symbol,

        direction=direction,

        confidence=confidence,

        entry=entry,

        analysis_close=analysis_close,

        analysis_time=datetime.fromtimestamp(

            analysis_time,

            timezone.utc

        ),

        entry_time=datetime.fromtimestamp(

            entry_time,

            timezone.utc

        ),

        expiry_time=datetime.fromtimestamp(

            expiry_time,

            timezone.utc

        )

    )

    # Telegram

    send_telegram(

        signal_text

    )

    # Queue outcome

    with pending_lock:

        pending_outcomes.append({

            "asset": symbol,

            "direction": direction,

            "entry": entry,

            "entry_time": entry_time,

            "expiry_time": expiry_time,

        })

# =========================================================

# OUTCOME

# =========================================================

async def process_outcomes(

    client

):

    now = int(

        time.time()

    )

    due = []

    with pending_lock:

        for item in pending_outcomes:

            if now >= (

                item["expiry_time"] + 5

            ):

                due.append(item)

    for item in due:

        symbol = item["asset"]

        try:

            df = await get_candles_async(

                client,

                symbol

            )

            if df is None:

                print(

                    "Outcome: no candle",

                    symbol

                )

                continue

            target = None

            expiry_time = item[

                "expiry_time"

            ]

            # Find expiry candle

            for _, candle in df.iterrows():

                candle_time = int(

                    candle["time"]

                )

                if candle_time >= expiry_time:

                    target = candle

                    break

            if target is None:

                print(

                    "Outcome: target candle "

                    "not available:",

                    symbol

                )

                continue

            expiry_close = float(

                target["close"]

            )

            entry = float(

                item["entry"]

            )

            direction = item[

                "direction"

            ]

            # Small movement = DRAW

            difference = abs(

                expiry_close - entry

            )

            threshold = max(

                abs(entry) * 0.00003,

                0.00000001

            )

            if difference <= threshold:

                result = "DRAW"

            elif direction == "CALL":

                result = (

                    "WIN"

                    if expiry_close > entry

                    else "LOSS"

                )

            else:

                result = (

                    "WIN"

                    if expiry_close < entry

                    else "LOSS"

                )

            entry_dt = datetime.fromtimestamp(

                item["entry_time"],

                timezone.utc

            )

            db_update(

                asset=symbol,

                entry_time=entry_dt,

                expiry_close=expiry_close,

                result=result

            )

            emoji = {

                "WIN": "✅",

                "LOSS": "❌",

                "DRAW": "➖",

            }.get(

                result,

                "ℹ️"

            )

            text = (

                f"{emoji} <b>RESULT</b>\n\n"

                f"📊 {symbol}\n"

                f"🎯 {direction}\n"

                f"Entry: <b>{entry:.8f}</b>\n"

                f"Close: <b>{expiry_close:.8f}</b>\n"

                f"Result: <b>{result}</b>"

            )

            print(

                f"RESULT | {symbol} | "

                f"{direction} | "

                f"{result}"

            )

            send_telegram(

                text

            )

            with pending_lock:

                if item in pending_outcomes:

                    pending_outcomes.remove(

                        item

                    )

        except Exception as e:

            print(

                "OUTCOME ERROR:",

                repr(e)

            )

            traceback.print_exc()

# =========================================================

# QUOTEX ENGINE

# =========================================================

async def quotex_engine():

    global quotex_client

    global quotex_status

    if not QUOTEX_EMAIL:

        quotex_status = "EMAIL_MISSING"

        print(

            "ERROR: QUOTEX_EMAIL missing"

        )

        return

    if not QUOTEX_PASSWORD:

        quotex_status = "PASSWORD_MISSING"

        print(

            "ERROR: QUOTEX_PASSWORD missing"

        )

        return

    print(

        "Quotex: creating client..."

    )

    try:

        client = Quotex(

            email=QUOTEX_EMAIL,

            password=QUOTEX_PASSWORD,

            lang="en",

            user_data_dir="browser",

        )

        quotex_client = client

        print(

            "Quotex: client created"

        )

    except Exception as e:

        quotex_status = "CLIENT_ERROR"

        print(

            "QUOTEX CLIENT ERROR:",

            repr(e)

        )

        traceback.print_exc()

        return

    while True:

        try:

            print(

                "Quotex: connecting..."

            )

            connected, reason = (

                await client.connect()

            )

            print(

                "Quotex connect response:",

                connected,

                reason

            )

            if not connected:

                quotex_status = "LOGIN_FAILED"

                print(

                    "Quotex: connection failed:",

                    reason

                )

                await asyncio.sleep(

                    15

                )

                continue

            quotex_status = "CONNECTED"

            print(

                "=========================================="

            )

            print(

                "QUOTEX CONNECTED"

            )

            print(

                "Signal scanner is LIVE"

            )

            print(

                "=========================================="

            )

            # Initial test

            test_symbol, test_df = (

                await find_working_asset(

                    client,

                    "EURUSD"

                )

            )

            if test_symbol:

                print(

                    f"Quotex candle test OK: "

                    f"{test_symbol} "

                    f"{len(test_df)} candles"

                )

            else:

                print(

                    "WARNING: EURUSD candle test "

                    "returned no data"

                )

            # Main scanner

            while True:

                try:

                    connected_now = (

                        await client.check_connect()

                    )

                    if not connected_now:

                        print(

                            "Quotex disconnected. "

                            "Reconnecting..."

                        )

                        quotex_status = (

                            "RECONNECTING"

                        )

                        break

                    for base_name in ASSETS:

                        try:

                            await generate_signal(

                                client,

                                base_name

                            )

                        except Exception as e:

                            print(

                                f"Scanner error "

                                f"{base_name}:",

                                repr(e)

                            )

                            traceback.print_exc()

                    await process_outcomes(

                        client

                    )

                    await asyncio.sleep(

                        SCAN_DELAY

                    )

                except Exception as e:

                    print(

                        "Scanner loop ERROR:",

                        repr(e)

                    )

                    traceback.print_exc()

                    await asyncio.sleep(

                        10

                    )

        except Exception as e:

            quotex_status = "ERROR"

            print(

                "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"

            )

            print(

                "QUOTEX ENGINE ERROR"

            )

            print(

                repr(e)

            )

            traceback.print_exc()

            print(

                "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"

            )

            await asyncio.sleep(

                15

            )

def quotex_thread():

    try:

        asyncio.run(

            quotex_engine()

        )

    except Exception as e:

        print(

            "Quotex asyncio ERROR:",

            repr(e)

        )

        traceback.print_exc()

# =========================================================

# STARTUP

# =========================================================

def print_config_status():

    print(

        "=========================================="

    )

    print(

        f"QUOTEX SIGNAL BOT {VERSION}"

    )

    print(

        "BTC + EURUSD + GOLD + OTC"

    )

    print(

        "1 MINUTE SIGNAL ENGINE"

    )

    print(

        "Telegram diagnostic FIXED"

    )

    print(

        "Quotex async engine FIXED"

    )

    print(

        "PostgreSQL / SQLite"

    )

    print(

        "=========================================="

    )

    print(

        "BOT_TOKEN:",

        "SET" if BOT_TOKEN else "MISSING"

    )

    print(

        "CHAT_ID:",

        "SET" if CHAT_ID else "MISSING"

    )

    print(

        "QUOTEX_EMAIL:",

        "SET" if QUOTEX_EMAIL else "MISSING"

    )

    print(

        "QUOTEX_PASSWORD:",

        "SET" if QUOTEX_PASSWORD else "MISSING"

    )

    print(

        "DATABASE_URL:",

        "SET" if DATABASE_URL else "NOT SET (SQLite)"

    )

    print(

        "=========================================="

    )

def main():

    print_config_status()

    db_init()

    # Telegram

    t1 = threading.Thread(

        target=telegram_thread,

        name="TelegramThread",

        daemon=True

    )

    t1.start()

    # Quotex

    t2 = threading.Thread(

        target=quotex_thread,

        name="QuotexThread",

        daemon=True

    )

    t2.start()

    print(

        "Scanner thread started"

    )

    print(

        "Outcome worker included"

    )

    print(

        f"Flask starting on port {PORT}"

    )

    app.run(

        host="0.0.0.0",

        port=PORT,

        debug=False,

        use_reloader=False,

    )

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(

            "Bot stopped."

        )

    except Exception as e:

        print(

            "MAIN ERROR:",

            repr(e)

        )

        traceback.print_exc()
