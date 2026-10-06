import os

import time

import asyncio

import threading

import queue

import requests

import sqlite3

import uuid

import math

from collections import OrderedDict

from datetime import datetime, timezone

import pandas as pd

from flask import Flask

from telegram import Update

from telegram.ext import (

    ApplicationBuilder,

    CommandHandler,

    ContextTypes,

)

from pyquotex.stable_api import Quotex

# ============================================================

# CONFIG

# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

CHAT_ID = os.getenv("CHAT_ID")

QUOTEX_EMAIL = os.getenv("QUOTEX_EMAIL")

QUOTEX_PASS = os.getenv("QUOTEX_PASS")

PERIOD = 60

DB_PATH = os.getenv("DB_PATH", "/tmp/quotex_v11.db")

# Main assets requested

ASSET_GROUPS = {

    "EURUSD": {

        "normal": ["EURUSD"],

        "otc": ["EURUSD_otc"],

    },

    "BTCUSD": {

        "normal": ["BTCUSD", "BTCUSD-OTC"],

        "otc": ["BTCUSD_otc", "BTCUSD-OTC"],

    },

    "XAUUSD": {

        "normal": ["XAUUSD", "GOLD"],

        "otc": ["XAUUSD_otc", "GOLD_otc", "GOLD-OTC"],

    },

}

BASE_PAIRS = list(ASSET_GROUPS.keys())

# ============================================================

# FLASK / RENDER

# ============================================================

app = Flask(__name__)

@app.route("/")

def home():

    return "QUOTEX v11 FULL UPGRADE LIVE"

@app.route("/health")

def health():

    return "OK"

# ============================================================

# GLOBAL STATE

# ============================================================

sent_cache = OrderedDict()

cache_lock = threading.Lock()

outcome_queue = queue.Queue()

last_scanned_entry_ts = None

# ============================================================

# TIME HELPERS

# ============================================================

def normalize_qx_ts(ts):

    try:

        ts = int(float(ts))

    except Exception:

        return 0

    # milliseconds -> seconds

    if ts > 1_000_000_000_000:

        ts //= 1000

    return ts

def utc_dt(ts):

    return datetime.fromtimestamp(

        int(ts),

        tz=timezone.utc

    )

def get_draw_threshold(asset, price):

    """

    Simple absolute draw tolerance.

    This is NOT a broker-defined rule.

    """

    asset_u = asset.upper()

    if "JPY" in asset_u:

        return 0.005

    if "BTC" in asset_u:

        return max(price * 0.00002, 0.01)

    if "XAU" in asset_u or "GOLD" in asset_u:

        return 0.02

    return 0.00002

def get_next_cycle(last_entry=None):

    """

    At 19:27:02:

        analysis candle = 19:26

        entry candle    = 19:27

        expiry candle   = 19:27

        result available around 19:28+

    This avoids calling an already closed candle "Entry OPEN".

    """

    now = time.time()

    current_minute = int(now // PERIOD) * PERIOD

    analysis_ts = current_minute - PERIOD

    entry_ts = current_minute

    if last_entry is not None and entry_ts <= last_entry:

        entry_ts = last_entry + PERIOD

        analysis_ts = entry_ts - PERIOD

    expiry_ts = entry_ts

    expiry_close_ts = entry_ts + PERIOD

    scan_ts = entry_ts + 2

    sleep_sec = max(0, scan_ts - now)

    return {

        "analysis_ts": analysis_ts,

        "entry_ts": entry_ts,

        "expiry_ts": expiry_ts,

        "expiry_close_ts": expiry_close_ts,

        "sleep_sec": sleep_sec,

    }

# ============================================================

# CACHE

# ============================================================

def cache_add(key):

    with cache_lock:

        if key in sent_cache:

            return False

        sent_cache[key] = True

        if len(sent_cache) > 500:

            sent_cache.popitem(last=False)

        return True

# ============================================================

# TELEGRAM

# ============================================================

def send_tg(text):

    if not BOT_TOKEN or not CHAT_ID:

        print("Telegram credentials missing")

        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    try:

        response = requests.post(

            url,

            json={

                "chat_id": CHAT_ID,

                "text": text,

            },

            timeout=15,

        )

        if response.status_code == 200:

            return True

        print(

            "Telegram error:",

            response.status_code,

            response.text[:300],

        )

    except Exception as e:

        print("Telegram send error:", e)

    return False

# ============================================================

# DATABASE

# ============================================================

def get_db_conn():

    db_url = os.getenv("DATABASE_URL")

    if db_url:

        import psycopg2

        conn = psycopg2.connect(db_url)

        conn.autocommit = True

        return conn, "postgres"

    conn = sqlite3.connect(

        DB_PATH,

        timeout=30,

    )

    return conn, "sqlite"

def init_db():

    conn, db_type = get_db_conn()

    cur = conn.cursor()

    try:

        if db_type == "postgres":

            cur.execute("""

                CREATE TABLE IF NOT EXISTS signals (

                    id TEXT PRIMARY KEY,

                    timestamp TEXT,

                    asset TEXT,

                    base_asset TEXT,

                    is_otc INTEGER,

                    signal TEXT,

                    entry_price DOUBLE PRECISION,

                    entry_candle_time BIGINT,

                    expiry_candle_time BIGINT,

                    expiry_close DOUBLE PRECISION,

                    outcome TEXT,

                    rsi DOUBLE PRECISION,

                    confidence TEXT

                )

            """)

        else:

            cur.execute("""

                CREATE TABLE IF NOT EXISTS signals (

                    id TEXT PRIMARY KEY,

                    timestamp TEXT,

                    asset TEXT,

                    base_asset TEXT,

                    is_otc INTEGER,

                    signal TEXT,

                    entry_price REAL,

                    entry_candle_time INTEGER,

                    expiry_candle_time INTEGER,

                    expiry_close REAL,

                    outcome TEXT,

                    rsi REAL,

                    confidence TEXT

                )

            """)

        if db_type == "sqlite":

            conn.commit()

    finally:

        conn.close()

def db_insert(data):

    try:

        conn, db_type = get_db_conn()

        cur = conn.cursor()

        if db_type == "postgres":

            cur.execute("""

                INSERT INTO signals (

                    id,

                    timestamp,

                    asset,

                    base_asset,

                    is_otc,

                    signal,

                    entry_price,

                    entry_candle_time,

                    expiry_candle_time,

                    expiry_close,

                    outcome,

                    rsi,

                    confidence

                )

                VALUES (

                    %s,%s,%s,%s,%s,%s,%s,

                    %s,%s,%s,%s,%s,%s

                )

                ON CONFLICT (id) DO NOTHING

            """, (

                data["id"],

                data["timestamp"],

                data["asset"],

                data["base_asset"],

                data["is_otc"],

                data["signal"],

                data["entry_price"],

                data["entry_candle_time"],

                data["expiry_candle_time"],

                data["expiry_close"],

                data["outcome"],

                data["rsi"],

                data["confidence"],

            ))

        else:

            cur.execute("""

                INSERT OR IGNORE INTO signals (

                    id,

                    timestamp,

                    asset,

                    base_asset,

                    is_otc,

                    signal,

                    entry_price,

                    entry_candle_time,

                    expiry_candle_time,

                    expiry_close,

                    outcome,

                    rsi,

                    confidence

                )

                VALUES (

                    :id,

                    :timestamp,

                    :asset,

                    :base_asset,

                    :is_otc,

                    :signal,

                    :entry_price,

                    :entry_candle_time,

                    :expiry_candle_time,

                    :expiry_close,

                    :outcome,

                    :rsi,

                    :confidence

                )

            """, data)

            conn.commit()

        conn.close()

        return True

    except Exception as e:

        print("DB INSERT ERROR:", e)

        try:

            conn.close()

        except Exception:

            pass

        return False

def db_update(signal_id, expiry_close, outcome):

    try:

        conn, db_type = get_db_conn()

        cur = conn.cursor()

        if db_type == "postgres":

            cur.execute("""

                UPDATE signals

                SET expiry_close=%s,

                    outcome=%s

                WHERE id=%s

            """, (

                expiry_close,

                outcome,

                signal_id,

            ))

        else:

            cur.execute("""

                UPDATE signals

                SET expiry_close=?,

                    outcome=?

                WHERE id=?

            """, (

                expiry_close,

                outcome,

                signal_id,

            ))

            conn.commit()

        conn.close()

        return True

    except Exception as e:

        print("DB UPDATE ERROR:", e)

        try:

            conn.close()

        except Exception:

            pass

        return False

def db_stats():

    conn, db_type = get_db_conn()

    cur = conn.cursor()

    def winrate(extra=""):

        cur.execute(f"""

            SELECT

                COUNT(*),

                SUM(

                    CASE

                        WHEN outcome='WIN'

                        THEN 1

                        ELSE 0

                    END

                )

            FROM signals

            WHERE outcome IN ('WIN','LOSS')

            {extra}

        """)

        total, wins = cur.fetchone()

        total = total or 0

        wins = wins or 0

        rate = (wins / total * 100) if total else 0

        return total, wins, rate

    stats = {}

    stats["ALL"] = winrate()

    for pair in BASE_PAIRS:

        stats[pair] = winrate(

            f"AND base_asset='{pair}'"

        )

    stats["OTC"] = winrate(

        "AND is_otc=1"

    )

    stats["NORMAL"] = winrate(

        "AND is_otc=0"

    )

    stats["CALL"] = winrate(

        "AND signal='CALL'"

    )

    stats["PUT"] = winrate(

        "AND signal='PUT'"

    )

    stats["HIGH"] = winrate(

        "AND confidence='HIGH'"

    )

    stats["MEDIUM"] = winrate(

        "AND confidence='MEDIUM'"

    )

    conn.close()

    return stats

init_db()

# ============================================================

# QUOTEX LOGIN

# ============================================================

async def login_qx_safe():

    if not QUOTEX_EMAIL or not QUOTEX_PASS:

        print(

            "ERROR: QUOTEX_EMAIL / QUOTEX_PASS missing"

        )

        return None

    for attempt in range(1, 4):

        qx = None

        try:

            qx = Quotex(

                email=QUOTEX_EMAIL,

                password=QUOTEX_PASS,

                lang="en",

                host="qxbroker.com",

                period_default=PERIOD,

            )

            ok, reason = await qx.connect()

            if ok:

                print(

                    f"Quotex connected: {reason}"

                )

                return qx

            print(

                f"Quotex login failed "

                f"{attempt}/3: {reason}"

            )

        except Exception as e:

            print(

                f"Quotex login exception "

                f"{attempt}/3: {e}"

            )

        if qx:

            try:

                await qx.close()

            except Exception:

                pass

        await asyncio.sleep(

            min(5 * attempt, 15)

        )

    return None

# ============================================================

# ASSET DISCOVERY

# ============================================================

async def try_asset(qx, candidate):

    try:

        asset_name, info = await qx.get_available_asset(

            candidate,

            force_open=True,

        )

        if info and len(info) > 2:

            is_open = bool(info[2])

            if is_open:

                return asset_name, True

    except Exception as e:

        print(

            f"Asset check failed "

            f"{candidate}: {e}"

        )

    return None, False

async def get_open_asset(qx, base):

    group = ASSET_GROUPS.get(base)

    if not group:

        return None, 0

    # -----------------------------------------

    # NORMAL

    # -----------------------------------------

    for candidate in group["normal"]:

        asset, opened = await try_asset(

            qx,

            candidate,

        )

        if opened:

            return asset, 0

    # -----------------------------------------

    # OTC

    # -----------------------------------------

    for candidate in group["otc"]:

        asset, opened = await try_asset(

            qx,

            candidate,

        )

        if opened:

            return asset, 1

    return None, 0

# ============================================================

# INDICATORS

# ============================================================

def ema(series, period):

    return series.ewm(

        span=period,

        adjust=False,

    ).mean()

def rsi_calc(series, period=14):

    delta = series.diff()

    gain = delta.clip(lower=0)

    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(

        alpha=1 / period,

        adjust=False,

    ).mean()

    avg_loss = loss.ewm(

        alpha=1 / period,

        adjust=False,

    ).mean()

    rs = avg_gain / avg_loss.replace(

        0,

        float("nan"),

    )

    rsi = 100 - (

        100 / (1 + rs)

    )

    # Handle zero-loss / zero-gain cases

    rsi = rsi.mask(

        (avg_loss == 0) & (avg_gain > 0),

        100,

    )

    rsi = rsi.mask(

        (avg_gain == 0) & (avg_loss > 0),

        0,

    )

    return rsi

def atr_calc(df, period=14):

    high_low = (

        df["high"] - df["low"]

    )

    high_close = (

        df["high"]

        - df["close"].shift(1)

    ).abs()

    low_close = (

        df["low"]

        - df["close"].shift(1)

    ).abs()

    true_range = pd.concat(

        [

            high_low,

            high_close,

            low_close,

        ],

        axis=1,

    ).max(axis=1)

    return true_range.rolling(

        period

    ).mean()

# ============================================================

# CANDLE FETCH

# ============================================================

async def get_candles_safe(

    qx,

    asset,

    count=120,

):

    try:

        return await qx.get_candles(

            asset,

            time.time(),

            PERIOD * count,

            PERIOD,

            timeout=15,

            use_cache=False,

        )

    except TypeError:

        try:

            return await qx.get_candles(

                asset,

                time.time(),

                PERIOD * count,

                PERIOD,

            )

        except Exception as e:

            print(

                f"get_candles error "

                f"{asset}: {e}"

            )

            return None

    except Exception as e:

        print(

            f"get_candles error "

            f"{asset}: {e}"

        )

        return None

def candles_to_df(candles):

    if not candles:

        return None

    df = pd.DataFrame(candles)

    if "time" not in df.columns:

        return None

    for col in [

        "open",

        "close",

        "high",

        "low",

    ]:

        if col not in df.columns:

            return None

        df[col] = pd.to_numeric(

            df[col],

            errors="coerce",

        )

    df["time"] = df["time"].apply(

        normalize_qx_ts

    )

    df = df.dropna(

        subset=[

            "time",

            "open",

            "close",

            "high",

            "low",

        ]

    )

    df = (

        df.sort_values("time")

        .drop_duplicates(

            "time",

            keep="last",

        )

        .reset_index(drop=True)

    )

    return df

# ============================================================

# ANALYSIS

# ============================================================

async def analyze_pair(

    qx,

    asset,

    analysis_ts,

):

    candles = await get_candles_safe(

        qx,

        asset,

        count=120,

    )

    df = candles_to_df(candles)

    if df is None:

        return None

    df = df[

        df["time"] <= analysis_ts

    ].copy()

    if len(df) < 60:

        return None

    if int(df.iloc[-1]["time"]) != int(

        analysis_ts

    ):

        return None

    df["ema14"] = ema(

        df["close"],

        14,

    )

    df["ema50"] = ema(

        df["close"],

        50,

    )

    df["rsi"] = rsi_calc(

        df["close"],

        14,

    )

    df["mom"] = (

        df["close"]

        - df["close"].shift(10)

    )

    df["atr"] = atr_calc(

        df,

        14,

    )

    last = df.iloc[-1]

    if any(

        pd.isna(last[x])

        for x in [

            "ema14",

            "ema50",

            "rsi",

            "mom",

            "atr",

        ]

    ):

        return None

    atr = float(last["atr"])

    if atr <= 0:

        return None

    ema_distance = abs(

        float(last["ema14"])

        - float(last["ema50"])

    )

    if (

        ema_distance > atr * 0.30

        and 40 < float(last["rsi"]) < 60

    ):

        confidence = "HIGH"

    elif ema_distance > atr * 0.15:

        confidence = "MEDIUM"

    else:

        confidence = "LOW"

    if confidence == "LOW":

        return None

    recent = df.iloc[-14:-2]

    if recent.empty:

        return None

    resistance = float(

        recent["high"].max()

    )

    support = float(

        recent["low"].min()

    )

    close = float(last["close"])

    ema14 = float(last["ema14"])

    ema50 = float(last["ema50"])

    rsi = float(last["rsi"])

    momentum = float(last["mom"])

    signal = None

    # CALL

    if (

        close > ema14 > ema50

        and rsi > 50

        and momentum > 0

        and close > resistance

    ):

        signal = "CALL"

    # PUT

    elif (

        close < ema14 < ema50

        and rsi < 50

        and momentum < 0

        and close < support

    ):

        signal = "PUT"

    if not signal:

        return None

    return {

        "signal": signal,

        "analysis_close": close,

        "analysis_time": int(

            last["time"]

        ),

        "rsi": rsi,

        "conf": confidence,

        "ema14": ema14,

        "ema50": ema50,

        "atr": atr,

    }

# ============================================================

# ENTRY PRICE

# ============================================================

async def get_entry_price(

    qx,

    asset,

    entry_ts,

):

    candles = await get_candles_safe(

        qx,

        asset,

        count=10,

    )

    df = candles_to_df(candles)

    if df is None:

        return None

    row = df[

        df["time"] == int(entry_ts)

    ]

    if row.empty:

        return None

    candle = row.iloc[-1]

    entry_open = float(

        candle["open"]

    )

    if not math.isfinite(entry_open):

        return None

    return entry_open

# ============================================================

# EXPIRY CANDLE

# ============================================================

async def fetch_expiry_candle(

    qx,

    asset,

    target_ts,

    retries=6,

):

    for attempt in range(

        1,

        retries + 1,

    ):

        try:

            candles = await get_candles_safe(

                qx,

                asset,

                count=20,

            )

            df = candles_to_df(

                candles

            )

            if df is not None:

                row = df[

                    df["time"]

                    == int(target_ts)

                ]

                if not row.empty:

                    return row.iloc[-1].to_dict()

        except Exception as e:

            print(

                "Expiry fetch error:",

                e,

            )

        if attempt < retries:

            await asyncio.sleep(

                2 + attempt * 2

            )

    return None

# ============================================================

# OUTCOME WORKER

# ============================================================

async def outcome_worker_loop():

    print(

        "Outcome worker v11 started"

    )

    qx = await login_qx_safe()

    while True:

        job = None

        try:

            job = await asyncio.to_thread(

                outcome_queue.get

            )

            (

                asset,

                result,

                signal_id,

                entry_ts,

                expiry_ts,

                expiry_close_ts,

            ) = job

            # Wait until expiry candle is actually closed

            wait = (

                expiry_close_ts + 5

            ) - time.time()

            if wait > 0:

                await asyncio.sleep(

                    wait

                )

            # Reconnect if needed

            if not qx:

                qx = await login_qx_safe()

            else:

                try:

                    connected = (

                        await qx.check_connect()

                    )

                except Exception:

                    connected = False

                if not connected:

                    try:

                        await qx.close()

                    except Exception:

                        pass

                    qx = await login_qx_safe()

            if not qx:

                db_update(

                    signal_id,

                    None,

                    "LOGIN_FAIL",

                )

                continue

            candle = await fetch_expiry_candle(

                qx,

                asset,

                expiry_ts,

            )

            if candle is None:

                db_update(

                    signal_id,

                    None,

                    "FETCH_FAIL",

                )

                send_tg(

                    f"⚠️ RESULT FETCH FAIL\n"

                    f"{asset}\n"

                    f"{result['signal']}\n"

                    f"ID: {signal_id[:8]}"

                )

                continue

            expiry_close = float(

                candle["close"]

            )

            entry_price = float(

                result["entry_price"]

            )

            threshold = get_draw_threshold(

                asset,

                entry_price,

            )

            difference = abs(

                expiry_close

                - entry_price

            )

            if difference <= threshold:

                outcome = "DRAW"

            elif (

                result["signal"] == "CALL"

                and expiry_close > entry_price

            ):

                outcome = "WIN"

            elif (

                result["signal"] == "PUT"

                and expiry_close < entry_price

            ):

                outcome = "WIN"

            else:

                outcome = "LOSS"

            db_update(

                signal_id,

                expiry_close,

                outcome,

            )

            if outcome == "WIN":

                emoji = "✅"

            elif outcome == "LOSS":

                emoji = "❌"

            else:

                emoji = "➖"

            send_tg(

                f"{emoji} RESULT\n"

                f"{asset} {result['signal']}\n"

                f"ID: {signal_id[:8]}\n"

                f"Entry: {entry_price:.8f}\n"

                f"Expiry: {expiry_close:.8f}\n"

                f"Result: {outcome}"

            )

            print(

                f"RESULT {asset} "

                f"{result['signal']} "

                f"{outcome}"

            )

        except Exception as e:

            print(

                "Outcome worker error:",

                e,

            )

            if job:

                try:

                    db_update(

                        job[2],

                        None,

                        "ERROR",

                    )

                except Exception:

                    pass

            await asyncio.sleep(2)

        finally:

            if job is not None:

                try:

                    outcome_queue.task_done()

                except Exception:

                    pass

def outcome_worker_thread():

    asyncio.run(

        outcome_worker_loop()

    )

# ============================================================

# SCANNER

# ============================================================

async def scanner_loop():

    global last_scanned_entry_ts

    print(

        "Scanner v11 started"

    )

    qx = await login_qx_safe()

    while True:

        try:

            if not qx:

                qx = await login_qx_safe()

                if not qx:

                    await asyncio.sleep(30)

                    continue

            try:

                connected = (

                    await qx.check_connect()

                )

            except Exception:

                connected = False

            if not connected:

                try:

                    await qx.close()

                except Exception:

                    pass

                qx = await login_qx_safe()

                if not qx:

                    await asyncio.sleep(30)

                    continue

            cycle = get_next_cycle(

                last_scanned_entry_ts

            )

            analysis_ts = cycle[

                "analysis_ts"

            ]

            entry_ts = cycle[

                "entry_ts"

            ]

            expiry_ts = cycle[

                "expiry_ts"

            ]

            expiry_close_ts = cycle[

                "expiry_close_ts"

            ]

            sleep_sec = cycle[

                "sleep_sec"

            ]

            print(

                f"Next scan "

                f"{utc_dt(entry_ts).strftime('%H:%M:%S')} UTC "

                f"in {sleep_sec:.1f}s"

            )

            if sleep_sec > 0:

                await asyncio.sleep(

                    sleep_sec

                )

            last_scanned_entry_ts = (

                entry_ts

            )

            # -----------------------------------------

            # Scan every requested asset

            # -----------------------------------------

            for base in BASE_PAIRS:

                try:

                    asset, is_otc = (

                        await get_open_asset(

                            qx,

                            base,

                        )

                    )

                    if not asset:

                        print(

                            f"{base}: CLOSED / NOT AVAILABLE"

                        )

                        continue

                    # Analyze the candle that just closed

                    analysis = (

                        await analyze_pair(

                            qx,

                            asset,

                            analysis_ts,

                        )

                    )

                    if not analysis:

                        print(

                            f"{base} {asset}: WAIT"

                        )

                        continue

                    # -----------------------------------------

                    # Get actual next candle open

                    # -----------------------------------------

                    entry_price = (

                        await get_entry_price(

                            qx,

                            asset,

                            entry_ts,

                        )

                    )

                    # Sometimes the candle open is not yet returned

                    # immediately. Use analysis close as fallback.

                    if entry_price is None:

                        entry_price = float(

                            analysis[

                                "analysis_close"

                            ]

                        )

                        entry_price_fallback = True

                    else:

                        entry_price_fallback = False

                    signal = analysis[

                        "signal"

                    ]

                    key = (

                        asset,

                        signal,

                        entry_ts,

                    )

                    if not cache_add(key):

                        continue

                    signal_id = str(

                        uuid.uuid4()

                    )

                    data = {

                        "id": signal_id,

                        "timestamp": datetime.now(

                            timezone.utc

                        ).isoformat(),

                        "asset": asset,

                        "base_asset": base,

                        "is_otc": is_otc,

                        "signal": signal,

                        "entry_price": entry_price,

                        "entry_candle_time": entry_ts,

                        "expiry_candle_time": expiry_ts,

                        "expiry_close": None,

                        "outcome": None,

                        "rsi": analysis["rsi"],

                        "confidence": analysis["conf"],

                    }

                    inserted = db_insert(

                        data

                    )

                    if not inserted:

                        print(

                            f"{base}: DB insert failed"

                        )

                        continue

                    if signal == "CALL":

                        emoji = "🟢"

                    else:

                        emoji = "🔴"

                    otc_text = (

                        " OTC"

                        if is_otc

                        else ""

                    )

                    fallback_text = (

                        "\n⚠️ Entry price fallback"

                        if entry_price_fallback

                        else ""

                    )

                    send_tg(

                        f"{emoji} "

                        f"{signal} "

                        f"{asset}{otc_text}\n"

                        f"ID: {signal_id[:8]}\n"

                        f"Entry: "

                        f"{utc_dt(entry_ts).strftime('%H:%M:%S')} UTC\n"

                        f"Price: {entry_price:.8f}\n"

                        f"RSI: {analysis['rsi']:.1f}\n"

                        f"Confidence: {analysis['conf']}\n"

                        f"Expiry: "

                        f"{utc_dt(expiry_close_ts).strftime('%H:%M:%S')} UTC"

                        f"{fallback_text}"

                    )

                    outcome_queue.put(

                        (

                            asset,

                            {

                                "signal": signal,

                                "entry_price": entry_price,

                                "rsi": analysis["rsi"],

                                "conf": analysis["conf"],

                            },

                            signal_id,

                            entry_ts,

                            expiry_ts,

                            expiry_close_ts,

                        )

                    )

                    print(

                        f"SIGNAL "

                        f"{base} "

                        f"{asset} "

                        f"{signal} "

                        f"{analysis['conf']}"

                    )

                    await asyncio.sleep(

                        0.5

                    )

                except Exception as e:

                    print(

                        f"Pair {base} error:",

                        e,

                    )

                    continue

        except Exception as e:

            print(

                "Scanner error:",

                e,

            )

            try:

                if qx:

                    await qx.close()

            except Exception:

                pass

            qx = None

            await asyncio.sleep(5)

def scanner_thread():

    asyncio.run(

        scanner_loop()

    )

# ============================================================

# TELEGRAM COMMANDS

# ============================================================

async def start(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE,

):

    await update.message.reply_text(

        "🟢 QUOTEX v11 ONLINE\n\n"

        "Assets:\n"

        "• EURUSD\n"

        "• BTCUSD\n"

        "• XAUUSD / GOLD\n"

        "• Normal + OTC fallback\n\n"

        "Commands:\n"

        "/status\n"

        "/market\n"

        "/stats"

    )

async def status(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE,

):

    await update.message.reply_text(

        "🟢 QUOTEX v11 ONLINE\n"

        f"Outcome Queue: "

        f"{outcome_queue.qsize()}\n"

        f"Assets: {', '.join(BASE_PAIRS)}"

    )

async def market(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE,

):

    await update.message.reply_text(

        "⏳ Checking market..."

    )

    cycle = get_next_cycle(None)

    analysis_ts = cycle[

        "analysis_ts"

    ]

    qx = await login_qx_safe()

    if not qx:

        await update.message.reply_text(

            "❌ Quotex login failed"

        )

        return

    try:

        lines = [

            "📊 QUOTEX v11 MARKET",

            "",

            "Analysis: "

            + utc_dt(

                analysis_ts

            ).strftime(

                "%H:%M:%S"

            )

            + " UTC",

        ]

        for base in BASE_PAIRS:

            try:

                asset, is_otc = (

                    await get_open_asset(

                        qx,

                        base,

                    )

                )

                if not asset:

                    lines.append(

                        f"⚪ {base}: CLOSED"

                    )

                    continue

                result = await analyze_pair(

                    qx,

                    asset,

                    analysis_ts,

                )

                otc_text = (

                    " OTC"

                    if is_otc

                    else ""

                )

                if result:

                    emoji = (

                        "🟢"

                        if result["signal"]

                        == "CALL"

                        else "🔴"

                    )

                    lines.append(

                        f"{emoji} "

                        f"{asset}{otc_text}: "

                        f"{result['signal']} "

                        f"[{result['conf']}]"

                    )

                else:

                    lines.append(

                        f"⚪ "

                        f"{asset}{otc_text}: WAIT"

                    )

            except Exception as e:

                lines.append(

                    f"⚠️ {base}: ERROR"

                )

                print(

                    f"Market {base} error:",

                    e,

                )

        await update.message.reply_text(

            "\n".join(lines)

        )

    finally:

        try:

            await qx.close()

        except Exception:

            pass

async def stats_cmd(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE,

):

    try:

        stats = await asyncio.to_thread(

            db_stats

        )

        total, wins, rate = stats[

            "ALL"

        ]

        if total == 0:

            await update.message.reply_text(

                "📊 No WIN/LOSS results yet."

            )

            return

        msg = (

            "📊 QUOTEX v11 STATS\n\n"

            f"Overall: "

            f"{wins}/{total} "

            f"= {rate:.1f}%\n"

        )

        for pair in BASE_PAIRS:

            t, w, r = stats[pair]

            msg += (

                f"{pair}: "

                f"{w}/{t} = {r:.1f}%\n"

            )

        t, w, r = stats["NORMAL"]

        msg += (

            f"\nNORMAL: "

            f"{w}/{t} = {r:.1f}%\n"

        )

        t, w, r = stats["OTC"]

        msg += (

            f"OTC: "

            f"{w}/{t} = {r:.1f}%\n"

        )

        t, w, r = stats["CALL"]

        msg += (

            f"\nCALL: "

            f"{w}/{t} = {r:.1f}%\n"

        )

        t, w, r = stats["PUT"]

        msg += (

            f"PUT: "

            f"{w}/{t} = {r:.1f}%"

        )

        await update.message.reply_text(

            msg

        )

    except Exception as e:

        print(

            "Stats error:",

            e,

        )

        await update.message.reply_text(

            "❌ Stats error"

        )

# ============================================================

# TELEGRAM BOT

# ============================================================

async def telegram_main():

    application = (

        ApplicationBuilder()

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

            "market",

            market,

        )

    )

    application.add_handler(

        CommandHandler(

            "stats",

            stats_cmd,

        )

    )

    print(

        "Telegram bot initializing..."

    )

    await application.initialize()

    await application.start()

    if application.updater:

        await application.updater.start_polling(

            drop_pending_updates=True

        )

    print(

        "Telegram bot LIVE"

    )

    try:

        while True:

            await asyncio.sleep(

                3600

            )

    finally:

        if application.updater:

            await application.updater.stop()

        await application.stop()

        await application.shutdown()

def run_bot():

    if not BOT_TOKEN:

        print(

            "ERROR: BOT_TOKEN missing"

        )

        return

    try:

        asyncio.run(

            telegram_main()

        )

    except Exception as e:

        print(

            "Telegram thread crashed:",

            e,

        )

# ============================================================

# MAIN

# ============================================================

if __name__ == "__main__":

    print(

        "=========================================="

    )

    print(

        "QUOTEX v11 FULL UPGRADE"

    )

    print(

        "BTC + EURUSD + GOLD + OTC"

    )

    print(

        "1 MINUTE SIGNAL ENGINE"

    )

    print(

        "Telegram asyncio FIXED"

    )

    print(

        "PostgreSQL / SQLite FIXED"

    )

    print(

        "=========================================="

    )

    # Scanner

    threading.Thread(

        target=scanner_thread,

        name="Scanner",

        daemon=True,

    ).start()

    # Outcome worker

    threading.Thread(

        target=outcome_worker_thread,

        name="OutcomeWorker",

        daemon=True,

    ).start()

    # Telegram

    threading.Thread(

        target=run_bot,

        name="TelegramBot",

        daemon=True,

    ).start()

    port = int(

        os.getenv(

            "PORT",

            "10000",

        )

    )

    print(

        f"Flask starting on port {port}"

    )

    app.run(

        host="0.0.0.0",

        port=port,

        threaded=True,

    )
