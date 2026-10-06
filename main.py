from pyquotex.stable_api import Quotex
import os
import time
import asyncio
import threading
import queue
import requests
import sqlite3
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
import pandas as pd
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
QUOTEX_EMAIL = os.getenv("QUOTEX_EMAIL")
QUOTEX_PASS = os.getenv("QUOTEX_PASS")

BASE_PAIRS = ["EURUSD", "GBPUSD", "EURJPY"]
OTC_MAP = {"EURUSD": "EURUSD_otc", "GBPUSD": "GBPUSD_otc", "EURJPY": "EURJPY_otc"}
PERIOD = 60
DB_PATH = os.getenv("DB_PATH", "/tmp/quotex_v10.db")

app = Flask(__name__)
@app.route("/")
def home():
    return "QUOTEX v10.6 ASYNC LIVE FIXED"
@app.route("/health")
def health():
    return "OK"

sent_cache = OrderedDict()
outcome_queue = queue.Queue()
cache_lock = threading.Lock()
last_scanned_entry_ts = None

def normalize_qx_ts(ts):
    try: ts = int(float(ts))
    except: return 0
    if ts > 1_000_000_000_000: ts //= 1000
    return ts

def get_draw_threshold(asset, price):
    return 0.005 if "JPY" in asset.upper() else 0.00002

def get_next_candle_times(last_entry=None):
    now = time.time()
    current_minute = int(now // 60) * 60
    entry_ts = current_minute - 60
    if last_entry is not None and entry_ts <= last_entry:
        entry_ts += 60
    expiry_ts = entry_ts + 60
    expiry_close_ts = expiry_ts + 60
    scan_ts = entry_ts + 62
    sleep_sec = max(0, scan_ts - now)
    entry_dt = datetime.fromtimestamp(entry_ts, tz=timezone.utc)
    expiry_dt = datetime.fromtimestamp(expiry_ts, tz=timezone.utc)
    expiry_close_dt = datetime.fromtimestamp(expiry_close_ts, tz=timezone.utc)
    return entry_dt, expiry_dt, expiry_close_dt, sleep_sec, entry_ts, expiry_ts, expiry_close_ts

def cache_add(key):
    with cache_lock:
        if key in sent_cache: return False
        sent_cache[key] = True
        if len(sent_cache) > 200: sent_cache.popitem(last=False)
        return True

def send_tg(text):
    if not BOT_TOKEN or not CHAT_ID: return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for _ in range(2):
        try:
            r = requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=15)
            if r.status_code == 200: return True
        except: pass
        time.sleep(1)
    return False

def get_db_conn():
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        import psycopg2
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        return conn, "postgres"
    conn = sqlite3.connect(DB_PATH, timeout=30)
    return conn, "sqlite"

def init_db():
    conn, db_type = get_db_conn()
    cur = conn.cursor()
    if db_type == "postgres":
        cur.execute("""CREATE TABLE IF NOT EXISTS signals (id TEXT PRIMARY KEY, timestamp TEXT, asset TEXT, base_asset TEXT, is_otc INTEGER, signal TEXT, entry_price DOUBLE PRECISION, entry_candle_time BIGINT, expiry_candle_time BIGINT, expiry_close DOUBLE PRECISION, outcome TEXT, rsi DOUBLE PRECISION, confidence TEXT)""")
    else:
        cur.execute("""CREATE TABLE IF NOT EXISTS signals (id TEXT PRIMARY KEY, timestamp TEXT, asset TEXT, base_asset TEXT, is_otc INTEGER, signal TEXT, entry_price REAL, entry_candle_time INTEGER, expiry_candle_time INTEGER, expiry_close REAL, outcome TEXT, rsi REAL, confidence TEXT)""")
        conn.commit()
    conn.close()

def db_insert(data):
    conn, db_type = get_db_conn()
    cur = conn.cursor()
    if db_type == "postgres":
        cur.execute("""INSERT INTO signals (id, timestamp, asset, base_asset, is_otc, signal, entry_price, entry_candle_time, expiry_candle_time, expiry_close, outcome, rsi, confidence) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""", (data["id"], data["timestamp"], data["asset"], data["base_asset"], data["is_otc"], data["signal"], data["entry_price"], data["entry_candle_time"], data["expiry_candle_time"], data["expiry_close"], data["outcome"], data["rsi"], data["confidence"]))
    else:
        cur.execute("""INSERT OR IGNORE INTO signals VALUES (:id,:timestamp,:asset,:base_asset,:is_otc,:signal,:entry_price,:entry_candle_time,:expiry_candle_time,:expiry_close,:outcome,:rsi,:confidence)""", data)
        conn.commit()
    conn.close()

def db_update(signal_id, expiry_close, outcome):
    conn, db_type = get_db_conn()
    cur = conn.cursor()
    if db_type == "postgres": cur.execute("""UPDATE signals SET expiry_close=%s, outcome=%s WHERE id=%s""", (expiry_close, outcome, signal_id))
    else: cur.execute("""UPDATE signals SET expiry_close=?, outcome=? WHERE id=?""", (expiry_close, outcome, signal_id)); conn.commit()
    conn.close()

def db_stats():
    conn, db_type = get_db_conn()
    cur = conn.cursor()
    def winrate(extra=""):
        cur.execute(f"""SELECT COUNT(*), SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) FROM signals WHERE outcome IN ('WIN','LOSS') {extra}""")
        total, wins = cur.fetchone()
        total = total or 0; wins = wins or 0
        return total, wins, wins / total * 100 if total else 0
    stats = {}
    stats["ALL"] = winrate()
    for pair in BASE_PAIRS: stats[pair] = winrate(f"AND base_asset='{pair}'")
    stats["OTC"] = winrate("AND is_otc=1"); stats["NORMAL"] = winrate("AND is_otc=0")
    stats["CALL"] = winrate("AND signal='CALL'"); stats["PUT"] = winrate("AND signal='PUT'")
    stats["HIGH"] = winrate("AND confidence='HIGH'"); stats["MEDIUM"] = winrate("AND confidence='MEDIUM'")
    conn.close()
    return stats

init_db()

async def login_qx_safe():
    if not QUOTEX_EMAIL or not QUOTEX_PASS:
        print("ERROR: QUOTEX_EMAIL / QUOTEX_PASS missing"); return None
    for attempt in range(1, 4):
        qx = None
        try:
            qx = Quotex(email=QUOTEX_EMAIL, password=QUOTEX_PASS, lang="en", host="qxbroker.com", period_default=PERIOD)
            ok, reason = await qx.connect()
            if ok:
                print(f"Quotex connected: {reason}"); return qx
            print(f"Quotex login failed {attempt}/3: {reason}")
        except Exception as e: print(f"Quotex login exception {attempt}/3: {e}")
        if qx:
            try: await qx.close()
            except: pass
        await asyncio.sleep(min(5 * attempt, 15))
    return None

async def get_open_asset(qx, base):
    try:
        asset, info = await qx.get_available_asset(base, force_open=True)
        if info and len(info) > 2 and info[2]: return asset, 0
    except Exception as e: print(f"{base} normal check:", e)
    otc = OTC_MAP.get(base)
    if otc:
        try:
            asset, info = await qx.get_available_asset(otc, force_open=True)
            if info and len(info) > 2 and info[2]: return asset, 1
        except Exception as e: print(f"{base} OTC check:", e)
    return None, 0

def ema(series, period): return series.ewm(span=period, adjust=False).mean()
def rsi_calc(series, period=14):
    delta = series.diff(); gain = delta.clip(lower=0); loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean(); avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))

async def get_candles_safe(qx, asset, count=100):
    try: return await qx.get_candles(asset, time.time(), PERIOD * count, PERIOD, timeout=15, use_cache=False)
    except TypeError: return await qx.get_candles(asset, time.time(), PERIOD * count, PERIOD)

async def analyze_pair(qx, asset, entry_ts):
    candles = await get_candles_safe(qx, asset, count=100)
    if not candles or len(candles) < 60: return None
    df = pd.DataFrame(candles)
    for col in ["time","open","close","high","low"]:
        if col not in df.columns: return None
    df["time"] = df["time"].apply(normalize_qx_ts)
    for col in ["open","close","high","low"]: df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["time","close","high","low"]).sort_values("time").drop_duplicates("time", keep="last")
    df = df[df["time"] <= entry_ts].copy()
    if len(df) < 50: return None
    if int(df.iloc[-1]["time"])!= int(entry_ts): return None
    df["ema14"] = ema(df["close"], 14); df["ema50"] = ema(df["close"], 50); df["rsi"] = rsi_calc(df["close"], 14); df["mom"] = df["close"] - df["close"].shift(10)
    last = df.iloc[-1]
    dist = abs(last["ema14"] - last["ema50"]); atr = (df["high"] - df["low"]).rolling(14).mean().iloc[-1]
    if pd.isna(atr): return None
    if dist > atr * 0.30 and 40 < last["rsi"] < 60: confidence = "HIGH"
    elif dist > atr * 0.15: confidence = "MEDIUM"
    else: confidence = "LOW"
    if confidence == "LOW": return None
    recent = df.iloc[-12:-2]
    if recent.empty: return None
    resistance = recent["high"].max(); support = recent["low"].min()
    signal = None
    if last["close"] > last["ema14"] > last["ema50"] and last["rsi"] > 50 and last["mom"] > 0 and last["close"] > resistance: signal = "CALL"
    elif last["close"] < last["ema14"] < last["ema50"] and last["rsi"] < 50 and last["mom"] < 0 and last["close"] < support: signal = "PUT"
    if not signal: return None
    return {"signal": signal, "close": float(last["close"]), "time": int(last["time"]), "rsi": float(last["rsi"]), "conf": confidence}

async def fetch_expiry_candle(qx, asset, target_ts, retries=5):
    for attempt in range(1, retries + 1):
        try:
            candles = await get_candles_safe(qx, asset, count=20)
            if candles:
                for candle in candles:
                    raw_time = candle.get("time", candle.get("timestamp"))
                    if raw_time is None: continue
                    if normalize_qx_ts(raw_time) == int(target_ts): return candle
        except Exception as e: print(f"Expiry fetch {attempt}/{retries}: {e}")
        if attempt < retries: await asyncio.sleep(2 + (attempt * 2))
    return None

async def outcome_worker_loop():
    print("Outcome worker v10.6 started")
    qx = await login_qx_safe()
    while True:
        job = None
        try:
            job = await asyncio.to_thread(outcome_queue.get)
            asset, result, signal_id, entry_ts, expiry_ts, expiry_close_ts = job
            wait_until = expiry_close_ts + 5
            sleep_needed = wait_until - time.time()
            if sleep_needed > 0: await asyncio.sleep(sleep_needed)
            if not qx:
                qx = await login_qx_safe()
            else:
                try: connected = await qx.check_connect()
                except: connected = False
                if not connected:
                    try: await qx.close()
                    except: pass
                    qx = await login_qx_safe()
            if not qx:
                db_update(signal_id, None, "LOGIN_FAIL"); continue
            candle = await fetch_expiry_candle(qx, asset, expiry_ts, retries=5)
            expiry_close = None; outcome = "UNKNOWN"
            if candle:
                expiry_close = float(candle["close"]); entry_close = float(result["close"]); draw_threshold = get_draw_threshold(asset, entry_close); difference = abs(expiry_close - entry_close)
                if difference <= draw_threshold: outcome = "DRAW"
                elif (result["signal"] == "CALL" and expiry_close > entry_close) or (result["signal"] == "PUT" and expiry_close < entry_close): outcome = "WIN"
                else: outcome = "LOSS"
            else: outcome = "FETCH_FAIL"
            db_update(signal_id, expiry_close, outcome)
            emoji = "✅" if outcome == "WIN" else "❌" if outcome == "LOSS" else "➖"
            send_tg(f"{emoji} RESULT {asset} {result['signal']} ID:{signal_id[:8]}\nEntry {result['close']:.5f} → Exp {expiry_close} = {outcome}")
        except Exception as e:
            print("Outcome worker error:", e)
            if job:
                try: db_update(job[2], None, "ERROR")
                except: pass
            await asyncio.sleep(2)
        finally:
            if job is not None:
                try: outcome_queue.task_done()
                except: pass

def outcome_worker_thread(): asyncio.run(outcome_worker_loop())

async def scanner_loop():
    global last_scanned_entry_ts
    print("Scanner v10.6 started")
    qx = await login_qx_safe()
    while True:
        try:
            if not qx:
                qx = await login_qx_safe()
                if not qx:
                    await asyncio.sleep(30); continue
            try: connected = await qx.check_connect()
            except: connected = False
            if not connected:
                print("Quotex disconnected. Reconnecting...")
                try: await qx.close()
                except: pass
                qx = await login_qx_safe()
                if not qx:
                    await asyncio.sleep(30); continue
            entry_dt, expiry_dt, expiry_close_dt, sleep_sec, entry_ts, expiry_ts, expiry_close_ts = get_next_candle_times(last_scanned_entry_ts)
            print(f"Sleep {sleep_sec:.1f}s -> Entry {entry_dt.strftime('%H:%M:%S')} Exp {expiry_close_dt.strftime('%H:%M:%S')} UTC")
            if sleep_sec > 0: await asyncio.sleep(sleep_sec)
            last_scanned_entry_ts = entry_ts
            for base in BASE_PAIRS:
                try:
                    asset, is_otc = await get_open_asset(qx, base)
                    if not asset: print(f"{base}: CLOSED"); continue
                    result = await analyze_pair(qx, asset, entry_ts)
                    if not result: print(f"{base}: WAIT"); continue
                    key = (asset, result["signal"], entry_ts)
                    if not cache_add(key): continue
                    signal_id = str(uuid.uuid4())
                    db_insert({"id": signal_id, "timestamp": datetime.now(timezone.utc).isoformat(), "asset": asset, "base_asset": base, "is_otc": is_otc, "signal": result["signal"], "entry_price": result["close"], "entry_candle_time": entry_ts, "expiry_candle_time": expiry_ts, "expiry_close": None, "outcome": None, "rsi": result["rsi"], "confidence": result["conf"]})
                    emoji = "🟢" if result["signal"] == "CALL" else "🔴"
                    send_tg(f"{emoji} {result['signal']} {asset} ID:{signal_id[:8]}\nEntry OPEN {entry_dt.strftime('%H:%M:%S')} @ {result['close']:.5f}\nRSI {result['rsi']:.1f} [{result['conf']}]\nExpiry CLOSE {expiry_close_dt.strftime('%H:%M:%S')} UTC")
                    outcome_queue.put((asset, result, signal_id, entry_ts, expiry_ts, expiry_close_ts))
                    print(f"SIGNAL {base} {asset} {result['signal']} {result['conf']}")
                    await asyncio.sleep(0.5)
                except Exception as pair_error: print(f"Pair {base} error {pair_error} - skipping"); continue
        except Exception as e:
            print("Scanner error:", e)
            try:
                if qx: await qx.close()
            except: pass
            qx = None; await asyncio.sleep(5)

def scanner_thread(): asyncio.run(scanner_loop())

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🟢 QUOTEX v10.6 ONLINE\n\n/stats\n/market\n/status")
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🟢 v10.6 ONLINE\nOutcome Queue: {outcome_queue.qsize()}")
async def market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Checking market...")
    entry_dt, expiry_dt, expiry_close_dt, _, entry_ts, expiry_ts, expiry_close_ts = get_next_candle_times(None)
    qx = await login_qx_safe()
    if not qx:
        await update.message.reply_text("❌ Quotex login failed"); return
    try:
        lines = [f"📊 v10.6 MARKET", f"Candle: {entry_dt.strftime('%H:%M:%S')} UTC"]
        for base in BASE_PAIRS:
            try:
                asset, is_otc = await get_open_asset(qx, base)
                if not asset: lines.append(f"⚪ {base}: CLOSED"); continue
                note = " (OTC)" if is_otc else ""
                result = await analyze_pair(qx, asset, entry_ts)
                if result:
                    emoji = "🟢" if result["signal"] == "CALL" else "🔴"
                    lines.append(f"{emoji} {asset}{note}: {result['signal']} [{result['conf']}]")
                else: lines.append(f"⚪ {asset}{note}: WAIT")
            except Exception as e: lines.append(f"⚠️ {base}: ERROR"); print(f"/market {base}:", e)
        await update.message.reply_text("\n".join(lines))
    finally:
        try: await qx.close()
        except: pass
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        stats = await asyncio.to_thread(db_stats)
        if stats["ALL"][0] == 0: await update.message.reply_text("📊 No WIN/LOSS outcomes yet."); return
        message = f"📊 v10.6 STATS\n\nOverall: {stats['ALL'][1]}/{stats['ALL'][0]} = {stats['ALL'][2]:.1f}%\n"
        for pair in BASE_PAIRS: message += f"{pair}: {stats[pair][1]}/{stats[pair][0]} = {stats[pair][2]:.1f}%\n"
        message += f"\nNORMAL: {stats['NORMAL'][1]}/{stats['NORMAL'][0]} = {stats['NORMAL'][2]:.1f}%\nOTC: {stats['OTC'][1]}/{stats['OTC'][0]} = {stats['OTC'][2]:.1f}%\n\nCALL: {stats['CALL'][1]}/{stats['CALL'][0]} = {stats['CALL'][2]:.1f}%\nPUT: {stats['PUT'][1]}/{stats['PUT'][0]} = {stats['PUT'][2]:.1f}%\n\nHIGH: {stats['HIGH'][1]}/{stats['HIGH'][0]} = {stats['HIGH'][2]:.1f}%\nMEDIUM: {stats['MEDIUM'][1]}/{stats['MEDIUM'][0]} = {stats['MEDIUM'][2]:.1f}%"
        await update.message.reply_text(message)
    except Exception as e: print("/stats error:", e); await update.message.reply_text("❌ Stats error")

def run_bot():
    if not BOT_TOKEN: print("BOT_TOKEN missing"); return
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("market", market))
    application.add_handler(CommandHandler("stats", stats_cmd))
    print("Telegram bot starting...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    print("====================================")
    print("QUOTEX v10.6 ASYNC STARTING")
    print("Python Quotex API: pyquotex 1.1.0")
    print("Auto trading: OFF")
    print("====================================")
    threading.Thread(target=scanner_thread, daemon=True).start()
    threading.Thread(target=outcome_worker_thread, daemon=True).start()
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
